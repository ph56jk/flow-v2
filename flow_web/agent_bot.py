"""Agent bot: thả bot vào một dự án ERP rồi để thẻ tự chạy.

Đây là một module đứng riêng chứ không phải một nhánh nữa của ``service.py``,
và lý do nằm ở chỗ nó chạy bằng **danh tính khác**.

``service.py`` gọi ERP bằng cặp API key/secret của một người thật: mọi bình
luận nó đăng đều mang tên người đó. Nhưng ``deleteTaskComment`` chỉ xoá được
bình luận **của chính mình**, nên một tiến trình mang danh người A không bao
giờ dọn được thứ do người B đăng. Muốn "👎 là xoá" thành sự thật thì đúng một
danh tính phải vừa đăng ảnh vừa xoá ảnh — và đó là việc của một ``HVG Agent
Bot`` với token riêng.

Token bot mở đúng một đường: endpoint GraphQL. Nó không mở REST của Frappe,
nên module này cố tình đi trọn vẹn qua GraphQL (``uploadTaskFile`` +
``addTaskComment`` + ``deleteTaskComment``) thay vì mượn các helper REST của
``service.py``.

Phạm vi của bot được quyết định **trên chính ERP**, không phải trong file cấu
hình: bot chỉ đọc những dự án mà nó là ``Project User``, và trong mỗi dự án đó
nó nhận mọi thẻ Idea còn mở. Thả agent vào một dự án là toàn bộ thao tác cần
làm; gỡ agent ra là tắt. Gắn agent vào một thẻ cụ thể bằng ``addTaskAgent`` là
cách nói "chỉ chạy thẻ này thôi": hễ một dự án có thẻ gắn đích danh bot thì dự
án ấy thu về đúng những thẻ đó.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import threading
import time
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Mapping, Sequence, Tuple
from urllib.error import HTTPError, URLError

from urllib.request import Request, urlopen

from .agent_brain import BrainVerdict, verdict_reply
from .agent_chat import (
    ACTION_NONE,
    ACTION_PAUSE,
    ACTION_RESUME,
    ACTION_RUN,
    ACTION_SET,
    ACTION_SKU_FILL,
    ACTION_SKU_RENUMBER,
    INTENT_HELP,
    INTENT_UNKNOWN,
    CardBrief,
    Reply,
    addressed_to_bot,
    comment_author,
    parse_allowed_authors,
    answer,
    as_record,
    sounds_like_an_order,
)
from .account_book import AccountBook
# ``_rows_by_name``/``_ancestors`` là hàm của làn nhanh SKU; dùng lại để lọc
# dòng ``taskBoard`` theo cụm, khỏi viết cách leo thẻ cha thứ hai.
from .sku import (
    SkuFastLane,
    SkuFastLaneConfig,
    _ancestors,
    _row_parent,
    _rows_by_name,
    cards_missing_sku,
    flatten_tree,
    name_fix_for,
)
from .erp_meta import (
    ACCOUNT_KEYS,
    MACHINE_KEYS,
    account_from_labels,
    missing_from_parent,
    parent_task_id,
    render_meta_block,
    resolve_routing,
    task_meta,
)
from .paths import DATA_DIR
from .erp_token_nhip import SharedRateLimiter
from . import pipeline
from . import sku_board

log = logging.getLogger(__name__)


GRAPHQL_PATH = "/api/method/hvg_workspace.graphql.endpoint.graphql"
DEFAULT_BASE_URL = "https://erp.havigroup.llc"

# Cùng tiền tố mà service.py dùng cho ảnh chờ duyệt, để bot nhận ra bài đăng
# của luồng cũ chứ không chỉ bài của chính nó.
REVIEW_PREFIX = "FLOW_V2_REVIEW"
RESULT_PREFIX = f"{REVIEW_PREFIX}_RESULT"
# Ghi chú do chính bot để lại. Bot không được coi ghi chú của mình là một ảnh
# chờ duyệt, nếu không vòng sau nó sẽ tự dọn dấu vết của vòng trước.
BOT_NOTE_MARK = "[AGENT_BOT]"
# Dấu riêng của lời nhắc về tên cột, đặt ở ``meta`` như mọi bài của bot: thân
# bình luận là chữ người đọc, còn dấu là chỗ bot nhận ra bài của chính mình.
COLUMN_NOTE_MARK = "[AGENT_BOT_COLUMN]"

DECISION_KEEP = "keep"
DECISION_DELETE = "delete"
DECISION_PENDING = ""

# Trần thật là 60 request/phút cho token bot (mục 8 của tài liệu API). Chừa
# một khoảng đệm: một lượt quét không đáng để đánh đổi lấy HTTP 429 làm hỏng
# cả vòng lặp.
RATE_LIMIT_PER_MINUTE = 50
# ``taskFull`` là field "nặng", trần 3 field nặng mỗi request — nên mỗi lượt
# gọi ở đây luôn chỉ hỏi đúng một cái.
TASK_FULL_DEPTH = 1

DEFAULT_POLL_SECONDS = 120
DEFAULT_AUTORUN_COOLDOWN_SECONDS = 900

# Phạm vi nhận việc.
SCOPE_BOARD = "board"  # thêm bot vào dự án là đủ; bot tự tìm thẻ Idea trong đó
SCOPE_CARD = "card"  # chỉ chạy thẻ có gắn bot
# Thẻ đã đóng thì không phải việc đang chờ, dù nó còn thẻ con chưa có ảnh.
#
# So khớp sau khi nén tên cột (bỏ dấu, bỏ mọi ký tự không phải chữ/số) chứ
# không so nguyên văn: bot được thiết kế để chạy trên *bất kỳ* board nào nó
# được thêm vào, và một board HaviGroup hoàn toàn có thể đặt tên cột bằng
# tiếng Việt. Nếu chỉ so đúng chữ tiếng Anh thì trên board như thế, một thẻ
# người ta đã huỷ vẫn được đếm là việc đang chờ và bot vẫn đốt quota tạo ảnh
# cho nó.
CLOSED_STATUSES = (
    "completed", "complete", "done", "cancelled", "canceled", "cancel", "closed",
    "hoanthanh", "dahoanthanh", "huy", "dahuy", "huybo", "dadong",
)
# Trần số thẻ Idea được khởi động trong một lượt quét. Cả app chỉ có một phiên
# Flow, nên xếp cả board vào hàng chỉ làm hàng đợi dài chứ không nhanh hơn; và
# một board mới thêm bot vào không nên biến thành hàng trăm job trong một phút.
DEFAULT_MAX_CARDS_PER_SCAN = 3
# Trần số câu trả lời trong một lượt quét. Một board vừa được thả bot vào có
# thể đang mang cả trăm bình luận cũ; trả lời hết một lượt là đổ một trận mưa
# thông báo lên đầu cả nhóm, mà mỗi lượt quét sau vẫn còn phần chưa trả lời.
DEFAULT_MAX_CHAT_REPLIES = 5
# Trần số thẻ được nhắc về cột lạ trong một lượt quét, tính theo từng bảng.
# Một bảng đặt sai tên cột thì *mọi* thẻ của nó đều mắc, và nhắc hết một lượt
# là đổ hàng chục bình luận giống hệt nhau lên đầu cả nhóm để nói đúng một
# việc — việc ấy nằm ở cái bảng, không nằm ở từng thẻ.
DEFAULT_MAX_COLUMN_ALERTS = 2
# Trần số thẻ con được chép Thuộc tính của thẻ cha trong một lượt quét, tính
# chung cả bảng. Mỗi thẻ là một lượt đọc lại + một lượt ghi của app, và token
# ERP dùng chung với Review Lister: thẻ cha 48 con chép hết một lượt là gần
# trăm request dồn vào một phút. Phần còn lại chờ lượt sau, hai phút một lần.
META_INHERIT_PER_SCAN = 8
# Ghi hỏng thì cả cụm nghỉ chừng này giây. Hỏng thường là ERP chặn 429, và gõ
# tiếp ngay lượt sau là gõ vào đúng chỗ đau.
META_INHERIT_BACKOFF_SECONDS = 300
# Trần số lần gọi đánh số hỏng cho thẻ chỉ chờ mã, mỗi cây mỗi lượt quét.
# Hỏng thường là 429; thử tiếp qua cả chục thẻ anh em là lại bão request.
# Chạm trần thì thôi, lượt sau thử lại.
SKU_FILL_FAILURES_PER_TREE = 3
# Dấu riêng của câu trả lời trò chuyện, đặt ở ``meta`` chứ không ở thân bình
# luận: người đọc thấy đúng câu trả lời sạch sẽ, còn bot vẫn nhận ra bài của
# mình để không bao giờ coi nó là ảnh chờ duyệt.
CHAT_NOTE_MARK = f"{BOT_NOTE_MARK} chat"

# Quyết định đã ghi thì giữ đủ lâu để một lần khởi động lại không làm bot
# quyết lại từ đầu, nhưng không giữ mãi để file state khỏi phình vô hạn.
HANDLED_RETENTION_DAYS = 45


class AgentBotError(RuntimeError):
    """Lỗi đã được diễn giải sang tiếng Việt cho người vận hành."""


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


#: Sổ lượt hỏi model giữ đúng một ngày: bằng cửa sổ dài nhất đang cần đọc, nên
#: nó không phình ra mà vẫn đủ để trả lời cả trần giờ và trần ngày.
BRAIN_CALL_LEDGER_WINDOW = timedelta(days=1)


def _read_stamp(text: str) -> datetime | None:
    """Mốc giờ trong sổ, hoặc ``None`` khi dòng đó không đọc được.

    Dòng lạ đọc thành ``None`` chứ không nổ: một file state bị sửa tay không
    được phép làm bot đứng.
    """
    try:
        when = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)


def _truthy(value: str, default: bool) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text in {"0", "false", "no", "off", "tat", "tắt"}:
        return False
    if text in {"1", "true", "yes", "on", "bat", "bật"}:
        return True
    return default


def _positive_int(value: str, default: int) -> int:
    text = str(value or "").strip()
    if not text:
        return default
    try:
        return max(0, int(text))
    except ValueError:
        return default


@dataclass(frozen=True)
class AgentBotConfig:
    """Cấu hình của bot. Chỉ ``token`` là bắt buộc."""

    token: str = ""
    base_url: str = DEFAULT_BASE_URL
    # Bỏ trống thì bot tự nhận ra chính mình (xem ``AgentBot.resolve_bot_user``).
    bot_user: str = ""
    # Bỏ trống nghĩa là "mọi dự án bot nhìn thấy" — đúng tinh thần "thả agent
    # vào dự án nào thì nó chạy ở đó". Điền vào để thu hẹp lại.
    projects: Tuple[str, ...] = ()
    poll_seconds: int = DEFAULT_POLL_SECONDS
    autorun: bool = True
    autorun_cooldown_seconds: int = DEFAULT_AUTORUN_COOLDOWN_SECONDS
    # ``board``: thêm bot vào dự án là xong, bot tự tìm thẻ Idea trong dự án đó.
    # ``card``: chỉ chạy thẻ có gắn bot. Ngay cả ở ``board``, hễ trong một dự án
    # có thẻ gắn bot thì dự án đó thu về đúng những thẻ ấy — nói rõ vẫn thắng suy
    # đoán, và đó là cách chỉ định "chỉ chạy thẻ này thôi".
    scope: str = SCOPE_BOARD
    # Cột nguồn của phạm vi ``board``: bỏ trống = mọi cột chưa đóng, đúng như
    # trước. Điền vào thì kéo thẻ sang cột ấy mới là lời giao việc, còn cột
    # nháp bên trái vẫn là chỗ gõ dở mà bot không đụng vào. Chỉ chặn phạm vi
    # ``board``: thẻ đã gắn đích danh bot vẫn chạy dù nằm ở cột nào, vì gắn bot
    # là cách duy nhất cứu một thẻ lỡ nhịp — chặn cả chỗ đó thì mất lối cứu.
    source_statuses: Tuple[str, ...] = ()
    max_cards_per_scan: int = DEFAULT_MAX_CARDS_PER_SCAN
    # Trả lời bình luận. Bật sẵn: người dùng gọi đích danh bot mà bot im lặng
    # thì tính năng này coi như không tồn tại. Tắt bằng ERP_AGENT_CHAT=0.
    chat: bool = True
    max_chat_replies_per_scan: int = DEFAULT_MAX_CHAT_REPLIES
    # Nhắc trên thẻ khi bảng đặt tên cột lạ. Bật sẵn, vì im lặng ở chỗ này
    # đúng bằng việc bảng đó không bao giờ chạy mà không ai biết vì sao.
    # Tắt bằng ERP_AGENT_COLUMN_ALERT=0.
    column_alert: bool = True
    max_column_alerts: int = DEFAULT_MAX_COLUMN_ALERTS
    # Chạy khô: ghi log quyết định nhưng không xoá gì. Dùng khi mới cắm bot
    # vào một dự án lạ và chưa tin phạm vi của nó.
    dry_run: bool = False
    timeout_s: int = 60
    # Ai được ra lệnh cho bot (C3.1). Trống = **không khoá**, giữ nguyên hành vi
    # hôm nay: bật hàng rào lên trước khi có người kịp điền danh sách thì bot
    # câm trên một bảng đang chạy, và không ai biết vì sao. Đổi lại, bot ghi
    # log cảnh báo mỗi lượt quét khi đang chạy không khoá.
    allowed_authors: Tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        return bool(self.token.strip())

    @classmethod
    def from_env(cls, base_url: str = "") -> "AgentBotConfig":
        raw_projects = os.getenv("ERP_AGENT_PROJECTS", "")
        names = [
            item.strip().upper()
            for item in raw_projects.replace(";", ",").split(",")
            if item.strip()
        ]
        # Narrowing the bot must never push it out of the project the rest of
        # the app already works in: listing the extra projects is meant to add
        # to the scope, and silently dropping the home project instead would
        # stop the bot exactly where it is most expected to run.
        home = os.getenv("ERP_PROJECT_ID", "").strip().upper()
        if names and home and home not in names:
            names.append(home)
        projects = tuple(names)
        raw_source = os.getenv("ERP_AGENT_SOURCE_STATUS", "").replace(";", ",")
        source_statuses = tuple(item.strip() for item in raw_source.split(",") if item.strip())
        for wanted in source_statuses:
            if compact_status(wanted) in CLOSED_STATUSES:
                # Đặt cột nguồn vào một cột đã đóng là hỏng câm: ``is_idea_card``
                # loại thẻ ở cột đóng trước cả bước này, nên bot sẽ quét mãi mà
                # không bao giờ nhận việc, và không có lỗi nào để mà đọc.
                log.warning(
                    "ERP_AGENT_SOURCE_STATUS=%r trỏ vào một cột đã đóng — bot sẽ "
                    "không bao giờ nhận được thẻ nào từ phạm vi board.",
                    wanted,
                )
        configured_base = (
            str(base_url or "").strip()
            or os.getenv("ERP_BASE_URL", "").strip()
            or DEFAULT_BASE_URL
        )
        return cls(
            token=os.getenv("ERP_AGENT_TOKEN", "").strip(),
            base_url=configured_base.rstrip("/"),
            bot_user=os.getenv("ERP_AGENT_BOT_USER", "").strip(),
            projects=projects,
            poll_seconds=_positive_int(os.getenv("ERP_AGENT_POLL_SECONDS", ""), DEFAULT_POLL_SECONDS),
            autorun=_truthy(os.getenv("ERP_AGENT_AUTORUN", ""), True),
            autorun_cooldown_seconds=_positive_int(
                os.getenv("ERP_AGENT_AUTORUN_COOLDOWN_SECONDS", ""),
                DEFAULT_AUTORUN_COOLDOWN_SECONDS,
            ),
            scope=SCOPE_CARD
            if os.getenv("ERP_AGENT_SCOPE", "").strip().lower() == SCOPE_CARD
            else SCOPE_BOARD,
            source_statuses=source_statuses,
            max_cards_per_scan=_positive_int(
                os.getenv("ERP_AGENT_MAX_CARDS_PER_SCAN", ""), DEFAULT_MAX_CARDS_PER_SCAN
            ),
            allowed_authors=parse_allowed_authors(
                os.getenv("FLOW_AGENT_BOT_ALLOWED_AUTHORS", "")
            ),
            chat=_truthy(os.getenv("ERP_AGENT_CHAT", ""), True),
            max_chat_replies_per_scan=_positive_int(
                os.getenv("ERP_AGENT_MAX_CHAT_REPLIES", ""), DEFAULT_MAX_CHAT_REPLIES
            ),
            column_alert=_truthy(os.getenv("ERP_AGENT_COLUMN_ALERT", ""), True),
            max_column_alerts=_positive_int(
                os.getenv("ERP_AGENT_MAX_COLUMN_ALERTS", ""), DEFAULT_MAX_COLUMN_ALERTS
            ),
            dry_run=_truthy(os.getenv("ERP_AGENT_DRY_RUN", ""), False),
        )


class _RateLimiter:
    """Cửa sổ trượt cho trần 60 request/phút của token bot.

    Chặn thay vì ném lỗi: một lượt quét chậm vài giây vẫn tốt hơn một lượt
    quét hỏng giữa chừng vì 429.
    """

    def __init__(self, limit: int = RATE_LIMIT_PER_MINUTE, window_s: float = 60.0) -> None:
        # Cùng tên công khai với ``SharedRateLimiter.limit``: ai đọc trần token
        # qua ``limiter.limit`` cũng phải thấy, dù client dùng limiter nào.
        self.limit = max(1, int(limit))
        self._limit = self.limit
        self._window_s = float(window_s)
        self._hits: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._hits and now - self._hits[0] >= self._window_s:
                    self._hits.popleft()
                if len(self._hits) < self._limit:
                    self._hits.append(now)
                    return
                wait_s = self._window_s - (now - self._hits[0])
            time.sleep(max(0.05, wait_s))


class AgentBotClient:
    """Client GraphQL thuần, xác thực bằng ``Authorization: HVGToken <token>``.

    Đồng bộ (urllib) giống các helper ERP sẵn có trong ``service.py``; phía
    async gọi nó qua ``asyncio.to_thread``.
    """

    def __init__(self, config: AgentBotConfig, limiter: Any | None = None) -> None:
        if not config.enabled:
            raise AgentBotError("Chưa có ERP_AGENT_TOKEN nên không dựng được client cho agent bot.")
        self._config = config
        self._limiter = limiter or _RateLimiter()

    # ── nền ────────────────────────────────────────────────────────────

    def _redact(self, value: Any) -> str:
        """Không bao giờ để token bot rơi vào log hay thông điệp lỗi."""
        text = str(value or "")
        token = self._config.token.strip()
        return text.replace(token, "[redacted]") if token else text

    def graphql(
        self,
        query: str,
        variables: Dict[str, Any] | None = None,
        operation_name: str = "",
        *,
        retries: int = 2,
    ) -> Dict[str, Any]:
        endpoint = f"{self._config.base_url}{GRAPHQL_PATH}"
        body = json.dumps(
            {
                "query": query,
                "variables": variables or {},
                "operationName": operation_name or None,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        attempt = 0
        while True:
            self._limiter.acquire()
            request = Request(
                endpoint,
                data=body,
                method="POST",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    # Lớp Cloudflare của ERP chặn chữ ký urllib mặc định.
                    "User-Agent": "Flow-v2-HaviGroup-ERP/1.0",
                    "Authorization": f"HVGToken {self._config.token}",
                },
            )
            try:
                with urlopen(request, timeout=self._config.timeout_s) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                break
            except HTTPError as exc:
                detail = self._redact(exc.read().decode("utf-8", errors="replace") or exc.reason)
                if exc.code == 401:
                    # Sáu điều kiện làm token vô hiệu, và phản hồi cố ý không
                    # nói rõ điều nào — nên liệt kê cả sáu cho người vận hành.
                    raise AgentBotError(
                        "ERP từ chối token agent bot (HTTP 401). Kiểm tra: token đã thu hồi, "
                        "bot bị tắt (kill-switch), hoặc người chịu trách nhiệm của bot bị khoá."
                    ) from exc
                if exc.code == 429 and attempt < retries:
                    attempt += 1
                    time.sleep(min(30.0, 5.0 * attempt))
                    continue
                if exc.code == 429:
                    raise AgentBotError(
                        "ERP đang giới hạn tốc độ token bot (HTTP 429). Hãy giãn ERP_AGENT_POLL_SECONDS."
                    ) from exc
                raise AgentBotError(f"ERP HTTP {exc.code}: {detail}") from exc
            except (URLError, TimeoutError) as exc:
                # Hết giờ đọc socket ném thẳng ``TimeoutError``, **không** phải
                # ``URLError``.  Bỏ sót nó thì sự cố mạng hay gặp nhất lại thành
                # sự cố duy nhất không được thử lại: nó chui khỏi ``graphql``,
                # vượt qua chỗ ``candidate_tasks`` bắt lỗi từng dự án, và giết
                # cả vòng quét — kéo theo mọi câu hỏi đang chờ trả lời và mọi
                # thẻ đang chờ chạy, chỉ vì một cái board đọc chậm.
                if attempt < retries:
                    attempt += 1
                    time.sleep(min(15.0, 3.0 * attempt))
                    continue
                reason = getattr(exc, "reason", None) or exc
                raise AgentBotError(self._redact(reason)) from exc

        try:
            envelope = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise AgentBotError("ERP trả dữ liệu không phải JSON.") from exc
        errors = envelope.get("errors") if isinstance(envelope, dict) else None
        if isinstance(errors, list) and errors:
            messages = [str(item.get("message") or "GraphQL error") for item in errors if isinstance(item, dict)]
            raise AgentBotError(self._redact("ERP GraphQL: " + "; ".join(messages)))
        data = envelope.get("data") if isinstance(envelope, dict) else None
        if not isinstance(data, dict):
            raise AgentBotError("ERP GraphQL không trả data hợp lệ.")
        return data

    # ── query ──────────────────────────────────────────────────────────

    def task_projects(self) -> List[Dict[str, Any]]:
        payload = self.graphql("query TaskProjects { taskProjects }", {}, "TaskProjects")
        projects = (payload.get("taskProjects") or {}).get("projects")
        return [item for item in (projects or []) if isinstance(item, dict)]

    def board_snapshot(self, project: str) -> Tuple[List[Dict[str, Any]], Tuple[str, ...]]:
        """Task đã trải phẳng, **kèm** tên các cột đúng như bảng đang đặt.

        Trải phẳng task ra khỏi cột là đúng cho mọi bước chọn việc, nhưng tên
        cột thì ném đi mất — mà đó chính là thứ cho biết bảng này có nói cùng
        thứ tiếng với luật cột hay không.  Trả cả hai trong *một* request, vì
        hỏi lại lần nữa chỉ để lấy mấy cái tên là phí một suất trong trần 60
        request/phút.
        """
        payload = self.graphql(
            "query TaskBoard($project: String!) { taskBoard(project: $project, includeArchived: false) }",
            {"project": project},
            "TaskBoard",
        )
        board = payload.get("taskBoard") or {}
        tasks: List[Dict[str, Any]] = []
        columns: List[str] = []
        for column in board.get("columns") or []:
            if not isinstance(column, dict):
                continue
            label = str(column.get("name") or column.get("status") or column.get("title") or "").strip()
            if label:
                columns.append(label)
            for task in column.get("tasks") or []:
                if isinstance(task, dict):
                    tasks.append(task)
        return tasks, tuple(columns)

    def task_board(self, project: str) -> List[Dict[str, Any]]:
        """Mọi task chưa lưu trữ của một dự án, đã trải phẳng khỏi các cột."""
        return self.board_snapshot(project)[0]

    def task_full(self, name: str, depth: int = TASK_FULL_DEPTH) -> Dict[str, Any]:
        payload = self.graphql(
            "query TaskFull($name: String!, $depth: Int) { taskFull(name: $name, depth: $depth) }",
            {"name": name, "depth": int(depth)},
            "TaskFull",
        )
        return payload.get("taskFull") or {}

    # ── mutation ───────────────────────────────────────────────────────

    def add_comment(
        self,
        task: str,
        content: str,
        attachments: Sequence[str] | None = None,
        parent: str = "",
        meta: str = "",
    ) -> Dict[str, Any]:
        """Đăng một bình luận, tuỳ chọn nằm trong thread của bình luận khác.

        ``meta`` là chỗ cất dấu riêng của app. Đặt dấu ở đó chứ không ở thân
        bình luận vì thân là thứ người dùng đọc: một câu trả lời mở đầu bằng
        ``[AGENT_BOT]`` thì đúng nhưng khó chịu, mà bỏ dấu đi thì vòng quét sau
        bot không phân biệt nổi bài của mình với bài người ta.
        """
        variables: Dict[str, Any] = {"name": task, "content": content}
        if attachments:
            variables["attachments"] = list(attachments)
        if parent:
            variables["parent"] = parent
        if meta:
            variables["meta"] = meta
        payload = self.graphql(
            "mutation AddTaskComment($name: String!, $content: String!, "
            "$attachments: [String!], $parent: String, $meta: String) "
            "{ addTaskComment(name: $name, content: $content, attachments: $attachments, "
            "parent: $parent, meta: $meta) }",
            variables,
            "AddTaskComment",
        )
        return payload.get("addTaskComment") or {}

    def upload_file(self, task: str, file_name: str, content: bytes, purpose: str = "comment") -> Dict[str, Any]:
        """Tải tệp lên task và trả về bản ghi File (có ``file_url``).

        ``purpose`` phải là ``comment`` nếu tệp sắp đi kèm một bình luận: tải
        bằng ``attachment`` rồi truyền vào ``addTaskComment`` vẫn ra HTTP 200
        nhưng ``linked = 0`` và tệp không hiện trong bình luận.
        """
        payload = self.graphql(
            "mutation UploadTaskFile($task: String!, $fileName: String!, "
            "$contentBase64: String!, $purpose: String) "
            "{ uploadTaskFile(task: $task, fileName: $fileName, "
            "contentBase64: $contentBase64, purpose: $purpose) }",
            {
                "task": task,
                "fileName": file_name,
                "contentBase64": base64.b64encode(content).decode("ascii"),
                "purpose": purpose,
            },
            "UploadTaskFile",
        )
        uploaded = payload.get("uploadTaskFile") or {}
        if not str(uploaded.get("file_url") or "").strip():
            raise AgentBotError(f"ERP không trả file_url khi tải {file_name} lên {task}.")
        return uploaded

    def delete_comment(self, task: str, comment: str) -> Dict[str, Any]:
        payload = self.graphql(
            "mutation DeleteTaskComment($name: String!, $comment: String!) "
            "{ deleteTaskComment(name: $name, comment: $comment) }",
            {"name": task, "comment": comment},
            "DeleteTaskComment",
        )
        return payload.get("deleteTaskComment") or {}

    def set_comment_vote(self, task: str, comment: str, vote: str) -> Dict[str, Any]:
        """Đặt phiếu theo trạng thái đích.

        Cố ý dùng ``setTaskCommentVote`` chứ không phải ``toggle``: toggle đọc
        rồi ghi ngoài một đoạn tuần tự hoá, nên hai lượt song song có thể nuốt
        mất một thao tác. Đặt trạng thái đích thì miễn nhiễm với ca đó.
        """
        payload = self.graphql(
            "mutation SetTaskCommentVote($name: String!, $comment: String!, $vote: String!) "
            "{ setTaskCommentVote(name: $name, comment: $comment, vote: $vote) }",
            {"name": task, "comment": comment, "vote": vote},
            "SetTaskCommentVote",
        )
        return payload.get("setTaskCommentVote") or {}

    def add_task_agent(self, task: str, bot_user: str) -> Dict[str, Any]:
        """Gắn bot vào một thẻ — đúng thao tác chọn agent ở ô Người phụ trách."""
        payload = self.graphql(
            "mutation AddTaskAgent($task: String!, $botUser: String!) "
            "{ addTaskAgent(task: $task, botUser: $botUser) }",
            {"task": task, "botUser": bot_user},
            "AddTaskAgent",
        )
        result = payload.get("addTaskAgent")
        return result if isinstance(result, dict) else {}

    def publish_image(
        self,
        task: str,
        file_name: str,
        content: bytes,
        body: str,
        parent: str = "",
    ) -> Dict[str, Any]:
        """Đăng một ảnh thành bình luận **của bot** để người ta bấm 👍/👎.

        Đây là điểm mấu chốt của cả module: chỉ khi bình luận thuộc về bot thì
        ``deleteTaskComment`` mới xoá được nó lúc bị 👎.

        **Chưa có ai gọi hàm này.** Ảnh hiện do ``flow_web/service.py`` đăng
        bằng ``ERP_API_KEY``/``ERP_API_SECRET``, tức dưới danh tính người thật,
        nên ``mine`` của chúng là 0 và nhánh "👎 là xoá" của bot không chạm tới
        được — xem dòng cảnh báo trong ``janitor_pass``. Nối hàm này vào luồng
        đăng ảnh là việc còn lại để nhánh ấy sống; ``tests/test_agent_bot.py``
        khoá đúng điều kiện đó lại.
        """
        uploaded = self.upload_file(task, file_name, content, purpose="comment")
        file_url = str(uploaded.get("file_url") or "")
        result = self.add_comment(task, body, attachments=[file_url], parent=parent)
        linked = int(result.get("linked") or 0)
        if linked < 1:
            # HTTP 200 mà tệp vẫn rơi mất là ca đã biết của addTaskComment; đối
            # chiếu ``linked`` là cách duy nhất phát hiện.
            raise AgentBotError(
                f"ERP nhận bình luận nhưng không gắn được ảnh {file_name} vào (linked=0)."
            )
        return {"file_url": file_url, "file": uploaded, "linked": linked}


# ── Đọc phiếu ──────────────────────────────────────────────────────────


def plain_text(content: Any) -> str:
    """Nội dung bình luận về dưới dạng HTML của trình soạn thảo."""
    text = re.sub(r"<[^>]+>", " ", str(content or ""))
    return re.sub(r"\s+", " ", unescape(text)).strip()


def vote_decision(node: Dict[str, Any]) -> str:
    """Đọc 👍/👎 của một bình luận thành quyết định.

    Hoà phiếu — kể cả 3-3 — cố ý là **chưa ngã ngũ**, không phải "giữ". Xoá là
    thao tác không hoàn tác được, nên nó chỉ xảy ra khi phía 👎 thực sự thắng.
    """
    like = int(node.get("like_count") or 0)
    dislike = int(node.get("dislike_count") or 0)
    if dislike > like:
        return DECISION_DELETE
    if like > dislike:
        return DECISION_KEEP
    return DECISION_PENDING


def node_markers(node: Dict[str, Any]) -> str:
    """Dấu của app trên một bình luận, dù nó nằm ở ``meta`` hay ở thân.

    Bình luận ảnh bây giờ không mang chữ nào - dấu chuyển hết sang ``meta`` để
    thẻ chỉ còn tấm ảnh - nhưng bình luận của các lượt chạy cũ vẫn mang dấu
    trong thân, nên đọc cả hai chỗ.
    """
    if not isinstance(node, dict):
        return ""
    parts = (str(node.get("meta") or ""), plain_text(node.get("content")))
    return " ".join(part for part in parts if part)


def is_bot_note(node: Dict[str, Any]) -> bool:
    """Ghi chú kết quả do chính bot để lại, không phải một ảnh chờ duyệt."""
    text = node_markers(node)
    return BOT_NOTE_MARK in text or RESULT_PREFIX in text


IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def has_image_attachment(node: Dict[str, Any]) -> bool:
    """Bình luận này có treo **ảnh** không — tệp khác không tính.

    Trước đây chỗ này chỉ hỏi "có ``attachments`` không", nên một tệp PDF hay
    một file Excel ai đó dán vào thẻ cũng thành một ảnh chờ 👍/👎. Không ai
    bấm phiếu cho một bảng giá được, nên thẻ đứng mãi ở *còn 1 ảnh chờ* và
    cổng sang listing không bao giờ mở.

    Không đọc được tên tệp thì vẫn tính là ảnh: ERP không phải lúc nào cũng
    trả ``file_name``, và bỏ sót một ảnh thật là bỏ sót một phiếu người đã
    bấm — hỏng nặng hơn hẳn việc đếm thừa một tệp lạ.

    "Không đọc được" gồm cả một URL **không có đuôi** (``/files/abc``): ERP
    hay trả đường dẫn theo mã tệp chứ không theo tên. Chỉ khi có một cái đuôi
    đọc được mà nó không phải đuôi ảnh thì tệp ấy mới bị loại.
    """
    for attachment in node.get("attachments") or []:
        if not isinstance(attachment, dict):
            return True
        name = str(
            attachment.get("file_name")
            or attachment.get("name")
            or attachment.get("file_url")
            or attachment.get("url")
            or ""
        ).strip()
        if not name:
            return True
        # Bỏ chuỗi truy vấn và mảnh neo trước, rồi lấy đoạn cuối đường dẫn:
        # ``https://erp/files/abc.pdf?fid=1`` phải đọc ra ``.pdf``.
        tail = name.rsplit("?", 1)[0].rsplit("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        if "." not in tail:
            return True
        if tail.lower().endswith(IMAGE_SUFFIXES):
            return True
    return False


def is_review_post(node: Dict[str, Any]) -> bool:
    """Một bình luận có phải là "ảnh đang chờ duyệt" hay không.

    Hai điều kiện, và điều kiện quyền là điều kiện cứng:

    * ``mine`` — bot phải là tác giả, vì nó chỉ xoá được bình luận của chính
      mình. Ảnh do luồng cũ đăng dưới danh tính người thật thì bot đọc được
      phiếu nhưng **không** dọn được, nên không nhận là việc của mình.
    * có **ảnh** đính kèm, hoặc mang thẻ ``[FLOW_V2_REVIEW ...]`` của luồng cũ.
    """
    if int(node.get("mine") or 0) != 1:
        return False
    if is_bot_note(node):
        return False
    if node.get("attachments"):
        # Có tệp thật thì chính tệp ấy quyết: dấu ``[FLOW_V2_REVIEW]`` là lối
        # dự phòng cho lúc ERP trả về bình luận **không** kèm tệp, chứ không
        # biến một bảng giá PDF thành ảnh chờ phiếu.
        return has_image_attachment(node)
    return REVIEW_PREFIX in node_markers(node)


def iter_tree_nodes(root: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """Duyệt task gốc cùng toàn bộ cây việc con mà ``taskFull`` trả về.

    ``children`` chỉ là danh sách mỏng (tên, tiêu đề, trạng thái); cây đầy đủ
    kèm bình luận nằm ở ``subtasks``. Ảnh thường nằm trên thẻ con chứ không
    phải thẻ cha, nên đi nhầm nhánh là bỏ sót toàn bộ việc.
    """
    if not isinstance(root, dict):
        return
    yield root
    for child in root.get("subtasks") or []:
        if isinstance(child, dict):
            yield from iter_tree_nodes(child)


def tree_is_cut(tree: Dict[str, Any]) -> bool:
    """Cây ``taskFull`` này có bị ERP cắt bớt không.

    Ba dấu hiệu, cái nào cũng đủ: ERP tự báo ``truncated``; số nút chạm
    trần ``max_nodes``; hoặc một thẻ có ``child_total`` lớn hơn số
    ``subtasks`` thật sự nhận được.  Cây bị cắt thì thẻ nằm ngoài phần nhận
    được là thẻ bot không nhìn thấy.
    """
    if tree.get("truncated"):
        return True
    try:
        if int(tree.get("node_count") or 0) >= int(tree.get("max_nodes") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    for node in iter_tree_nodes(tree.get("root") or {}):
        try:
            total = int(node.get("child_total") or 0)
        except (TypeError, ValueError):
            continue
        if total > len(node.get("subtasks") or []):
            return True
    return False


def has_children(node: Dict[str, Any]) -> bool:
    """Thẻ này có thẻ con không — hỏi cả hai chỗ ERP nói ra.

    ``subtasks`` là cây đầy đủ, nhưng ``taskFull`` cắt nó ở 59 thẻ, nên một
    thẻ cha đông con vẫn phải đọc được là cha. ``child_total`` là con số ERP
    tự đếm và không bị cắt.
    """
    if node.get("subtasks"):
        return True
    try:
        return int(node.get("child_total") or 0) > 0
    except (TypeError, ValueError):
        return False


def is_foreign_review_post(node: Dict[str, Any]) -> bool:
    """Ảnh chờ duyệt nhưng **không** phải của bot, nên bot không dọn được.

    Cùng hình dạng với ``is_review_post``, khác đúng một điều kiện: tác giả.
    Tách ra để cái nhánh nằm im có tên gọi và đếm được — nếu không, "không có
    việc nào" và "có việc mà không làm nổi" trông giống hệt nhau trong log.
    """
    if int(node.get("mine") or 0) == 1:
        return False
    if is_bot_note(node):
        return False
    if node.get("attachments"):
        # Có tệp thật thì chính tệp ấy quyết: dấu ``[FLOW_V2_REVIEW]`` là lối
        # dự phòng cho lúc ERP trả về bình luận **không** kèm tệp, chứ không
        # biến một bảng giá PDF thành ảnh chờ phiếu.
        return has_image_attachment(node)
    return REVIEW_PREFIX in node_markers(node)


def iter_foreign_review_posts(task_node: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """Như ``iter_review_posts`` nhưng cho phía bot không với tới được."""
    for comment in task_node.get("comments") or []:
        if not isinstance(comment, dict):
            continue
        if is_foreign_review_post(comment):
            yield comment
        for reply in comment.get("replies") or []:
            if isinstance(reply, dict) and is_foreign_review_post(reply):
                yield reply


def iter_review_posts(task_node: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """Mọi bình luận (cấp task lẫn phản hồi trong thread) đang chờ phán quyết."""
    for comment in task_node.get("comments") or []:
        if not isinstance(comment, dict):
            continue
        if is_review_post(comment):
            yield comment
        for reply in comment.get("replies") or []:
            if isinstance(reply, dict) and is_review_post(reply):
                yield reply


# Chỗ cất dòng bảng dự án của thẻ ngay trong cây ``taskFull``. Gạch dưới ở đầu
# để không đụng field nào của ERP, hôm nay hay mai kia.
BOARD_ROW_KEY = "_board_row"


def count_card_images(task_node: Dict[str, Any], board_row: Dict[str, Any] | None = None) -> int:
    """Bao nhiêu ảnh đang nằm trên chính thẻ này (bìa + ảnh trong bình luận).

    Dùng để nhận ra thẻ Idea vừa được thả thêm ảnh: ảnh đầu là ảnh sản phẩm,
    từ ảnh thứ hai trở đi là idea người dùng vừa đưa vào và chưa thành thẻ con.
    Ảnh Flow tự sinh ra không tính - chúng nằm ở thẻ con chứ không ở đây, và
    đếm nhầm chúng sẽ khiến thẻ nào chạy xong cũng trông như vừa có ảnh mới.

    ``taskFull`` **không** trả về tệp treo thẳng trên thẻ, mà kéo-thả một tấm
    ảnh vào thẻ thì nó nằm đúng ở đó: thẻ vừa được thả ba tấm đọc về không bìa,
    không bình luận, không gì cả. Dòng của thẻ trên bảng dự án thì có
    ``attachment_count``, nên nếu gọi kèm dòng đó thì lấy số nào lớn hơn. Con
    số ấy đếm cả tệp không phải ảnh, nhưng đây là bước *nhận thẻ đáng đọc*, còn
    việc lọc ảnh thật thì ``enqueue_erp_idea_jobs`` làm sau và làm đúng.
    """
    hung_on_card = int((board_row or {}).get("attachment_count") or 0)
    seen: set[str] = set()
    cover = str(task_node.get("cover_image") or "").strip()
    if cover:
        seen.add(cover)
    for comment in task_node.get("comments") or []:
        if not isinstance(comment, dict):
            continue
        if "FLOW_V2_ARTIFACT" in node_markers(comment):
            continue
        for attachment in comment.get("attachments") or []:
            if not isinstance(attachment, dict):
                continue
            name = str(attachment.get("file_name") or attachment.get("name") or "").strip()
            url = str(attachment.get("file_url") or attachment.get("url") or "").strip()
            if not name.lower().endswith(IMAGE_SUFFIXES) or name.lower().startswith("flow-"):
                continue
            seen.add(url or name)
        # ``taskFull`` trả bình luận với ``attachments`` **rỗng** và chỉ giữ một
        # ``image`` đại diện, trong khi ``taskDetail`` của đúng bình luận ấy trả
        # đủ cả mười tấm. Thẻ có ảnh idea dán trong bình luận vì thế đọc về vỏn
        # vẹn một tấm bìa và bị từ chối ngay tại cửa. Đếm thêm ảnh đại diện đó:
        # bước này chỉ hỏi "thẻ này có gì ngoài ảnh sản phẩm không", còn đếm cho
        # đủ là việc của ``enqueue_erp_idea_jobs`` — nó đọc ``taskDetail``.
        image = str(comment.get("image") or "").strip()
        if image.lower().endswith(IMAGE_SUFFIXES) and not image.rsplit("/", 1)[-1].lower().startswith("flow-"):
            seen.add(image)
    return max(len(seen), hung_on_card)


# ERP tự ghi câu này làm thân khi người dùng chỉ thả tệp, không gõ chữ.
ERP_FILES_ONLY_BODY = "(đã đính kèm tệp)"


def has_hidden_files(task_node: Dict[str, Any]) -> bool:
    """Thẻ có bình luận chỉ đính tệp, mà bot không thấy tệp nào.

    Tệp dán vào bình luận là tệp riêng tư (``/private/files/...``). Token của
    bot không đọc được chúng, nên ``taskFull`` trả bình luận ấy với
    ``attachments`` rỗng và ``image`` rỗng. TASK-2026-05740 được thả hai mươi
    tấm idea kiểu này: bot đếm ra không tấm nào và bỏ qua thẻ mãi.

    Dấu còn lại là thân bình luận do ERP tự ghi. Thấy thân ấy mà không thấy
    tệp thì giao thẻ cho hook: hook đọc bằng tài khoản app, thấy đủ tệp và tự
    lọc ảnh thật. Tệp nào không phải ảnh thì hook không tạo gì.
    """
    for comment in task_node.get("comments") or []:
        if not isinstance(comment, dict):
            continue
        if str(comment.get("is_bot") or "0") not in ("0", "False"):
            continue
        if "FLOW_V2" in node_markers(comment):
            continue
        if plain_text(comment.get("content")).strip() != ERP_FILES_ONLY_BODY:
            continue
        if not (comment.get("attachments") or []) and not str(comment.get("image") or "").strip():
            return True
    return False


def compact_status(value: Any) -> str:
    """Tên cột ERP nén lại để so khớp: bỏ dấu, bỏ ký tự thừa, còn chữ thường.

    ``"Đã hủy"`` → ``"dahuy"``, ``"Pending Review"`` → ``"pendingreview"``.

    ``đ`` được đổi thành ``d`` *trước* khi bỏ dấu, vì ``unicodedata`` không
    tách được nó: nó là một chữ cái riêng chứ không phải ``d`` cộng dấu. Bỏ
    bước này thì ``"Đã hủy"`` nén thành ``"ahuy"`` — vẫn khớp được nếu ta viết
    đúng chuỗi đó vào bảng, nhưng người đọc sau sẽ tưởng là gõ nhầm và "sửa"
    nó thành ``"dahuy"``, lúc ấy hàng rào im lặng thủng.
    """
    text = str(value or "").strip().lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in text if ch.isascii() and ch.isalnum())


def is_idea_card(task: Dict[str, Any], board_row: Dict[str, Any] | None = None) -> bool:
    """Thẻ Idea: thẻ cha còn mở, có thẻ con - hoặc sắp có.

    Đây là bộ lọc của chế độ ``board``, và nó cố ý hẹp. Thẻ đã Hoàn thành/Huỷ
    thì việc của nó đã xong, và tự chạy lại một thẻ người ta vừa đóng là cách
    nhanh nhất để bot bị tắt.

    Thẻ chưa có con vẫn được nhận trong hai trường hợp: nó là thẻ nhóm
    (``is_group``), hoặc nó đang mang từ hai tệp trở lên. Cái sau mới là đường
    của người dùng thật - kéo ảnh sản phẩm cùng mấy ảnh idea vào một thẻ trắng
    - và ``attachment_count`` của bảng dự án là chỗ duy nhất đếm được chúng mà
    không tốn thêm request. Một tệp thì chưa có gì để làm: đó là ảnh sản phẩm
    đứng một mình.
    """
    if not isinstance(task, dict):
        return False
    # ``taskFull`` không có ``attachment_count``; chỉ dòng của thẻ trên bảng dự
    # án mới có, nên khi xét một cây thì phải đưa kèm dòng đó vào.
    attachments = max(
        int(task.get("attachment_count") or 0),
        int((board_row or {}).get("attachment_count") or 0),
    )
    if int(task.get("child_total") or 0) <= 0 and not task.get("is_group") and attachments < 2:
        return False
    return compact_status(task.get("status")) not in CLOSED_STATUSES


def card_is_in_source_column(task: Dict[str, Any], wanted: Sequence[str]) -> bool:
    """Thẻ có đang nằm ở cột nguồn không. ``wanted`` rỗng = mọi cột đều tính.

    So bằng ``compact_status`` ở *cả hai* đầu, nên ``Working`` trong file cấu
    hình khớp cả ``working`` lẫn ``WORKING``, và một board đặt tên cột bằng
    tiếng Việt vẫn khớp được. So nguyên văn thì người ta gõ đúng tên cột mình
    đang nhìn thấy mà bot vẫn đứng im — đúng kiểu hỏng không ai đọc ra.
    """
    keys = {compact_status(name) for name in wanted}
    keys.discard("")
    if not keys:
        return True
    return compact_status(task.get("status")) in keys


def is_listing_card(task_node: Dict[str, Any]) -> bool:
    """Thẻ này có tự nhận mình là việc listing Etsy không.

    Hai nửa của hệ — làm ảnh và lên listing Etsy — dùng chung một ERP và sẽ
    dùng chung một agent. Thứ phân biệt chúng là khối *Thuộc tính* của thẻ::

        action_1: listing
        acc: acc32

    Thẻ ảnh không viết ``action_*`` nào cả (``sku`` / ``product`` /
    ``fatheridea`` / ``prompt``), nên "không nói gì" bắt buộc phải có nghĩa là
    *làm như cũ*, không bao giờ là *từ chối*. Nhờ vậy thêm khả năng listing
    không đụng một thẻ ảnh nào đang chạy.

    ``taskFull`` trả sẵn ``meta`` trong ``root`` (đo thật trên
    TASK-2026-00202), nên bước phân loại này không tốn thêm request nào.
    """
    return task_meta(task_node).is_listing


# Dòng nào của thẻ cha được phép đi xuống thẻ con: chỉ những dòng nói **thẻ
# này là việc gì** và **chạy ở đâu**. ``sku:``, ``product:``, ``template:`` là
# chuyện của riêng từng thẻ — cho con mượn là gửi mã của cha lên bản Listing
# cho một sản phẩm khác.
_ACTION_KEY_RE = re.compile(r"^action(?:_?\d+)?$")
ROUTING_KEYS: Tuple[str, ...] = ACCOUNT_KEYS + MACHINE_KEYS


def inherited_meta_node(
    node: Dict[str, Any],
    root: Dict[str, Any],
    *,
    known_accounts: Sequence[str] = (),
) -> Dict[str, Any]:
    """Thẻ con đọc kèm **dòng định tuyến** của thẻ cha, chỉ trong cụm listing.

    Hình dạng thật trên ERP tách đôi thứ cần đi cùng nhau: ``action_1:
    listing`` chỉ có ở thẻ cha, còn ảnh và phiếu 👍 lại nằm trên thẻ con — thẻ
    con được tạo trắng, không một dòng nào. Thành ra thẻ *biết* mình là listing
    thì không có ảnh, còn thẻ *có* ảnh thì không biết mình là listing, và cổng
    giữa hai nửa không bao giờ mở.

    Chỉ chép xuống ``action*``, ``acc``/``shop``… và ``machine``… Dòng con
    viết luôn thắng, đúng luật của :func:`erp_meta.inherit`: cha không được
    kéo con sang tài khoản khác, và cũng không được cho con mượn mã SKU của
    mình.

    Tài khoản còn có thể khai bằng **nhãn** ERP chứ không phải dòng ``acc:``
    — người làm listing dán ``acc32`` lên thẻ cha là xong. Nhãn nằm ở
    ``meta_auto`` của cha, mà ``meta_auto`` thì không bao giờ đi xuống con
    (:func:`erp_meta.inherit`), nên ở đây phải dịch nó thành một dòng ``acc:``
    thật. Không dịch thì ``account_id`` của con rỗng, và bản Listing rơi về
    máy mặc định — tức là đăng bộ ảnh ấy lên đúng cái shop nó không thuộc về.

    Chỉ làm khi cha là thẻ listing. Cụm ảnh có luật đánh số riêng.
    """
    if node is root:
        return node
    parent = task_meta(root)
    if not parent.is_listing:
        return node
    inherited: Dict[str, str] = {}
    for key, value in parent.attributes.items():
        text = str(value or "").strip()
        if not text:
            continue
        if _ACTION_KEY_RE.match(key) or key in ROUTING_KEYS:
            inherited[key] = text
    if not any(key in inherited for key in ACCOUNT_KEYS):
        labelled = account_from_labels(parent.labels, known_accounts)
        if labelled:
            inherited["acc"] = labelled
    if not inherited:
        return node
    parent_lines = "\n".join(f"{key}: {value}" for key, value in inherited.items())
    child_raw = str(task_meta(node).raw or "").strip()
    merged = f"{parent_lines}\n{child_raw}" if child_raw else parent_lines
    return {**node, "meta": merged}


def _listing_wait_text(outcome: Dict[str, Any]) -> str:
    """Lượt đã giao còn treo vì lý do gì, nói bằng tiếng người."""
    if outcome.get("unknown"):
        return str(outcome.get("reason") or "bản Listing không tra ra lượt đã giao")
    status = str(outcome.get("status") or "").strip()
    return f"máy Etsy đang chạy ({status})" if status else "máy Etsy chưa báo kết quả"


def listing_readiness(task_node: Dict[str, Any]) -> Tuple[bool, str]:
    """Thẻ listing này đã đăng được chưa, và nếu chưa thì còn thiếu gì.

    Nửa listing không tạo ảnh: nó lấy đúng bộ ảnh đang nằm trên thẻ, chép sang
    máy Etsy rồi dựng bản nháp. Nên "đăng được" nghĩa là bộ ảnh trên thẻ đã
    chốt — mọi ảnh đều đã có người bấm 👍 hoặc 👎, và còn lại ít nhất một ảnh
    được giữ.

    Chỉ ảnh *chờ* mới chặn. Ảnh bị 👎 coi như đã chốt: cùng lượt quét này
    ``janitor_pass`` gỡ nó khỏi thẻ, nên thứ bản Listing tải về sẽ không còn
    nó nữa.

    Chưa có ảnh nào cũng là "chưa xong", không phải hỏng: thẻ vừa được gắn
    agent thì nửa làm ảnh chạy trước, xong rồi mới tới lượt đăng.

    Đếm qua :func:`count_decisions`, tức là đếm **cả** ảnh bot không xoá được
    (``mine = 0``).  Trước đây chỗ này chỉ đếm ảnh của chính bot, và vì đường
    tạo ảnh của app đăng dưới danh tính người thật nên gần như mọi thẻ đều đọc
    ra "chưa có ảnh nào để đăng" — cái cổng này không bao giờ mở.  Câu hỏi ở
    đây là *bộ ảnh trên thẻ đã chốt chưa*, và ai là tác giả bình luận không
    liên quan gì tới câu ấy: nửa listing tải ảnh về từ chính thẻ, không phải
    từ bot.  Ảnh bị 👎 mà bot không gỡ được thì ``sync_erp_review`` của app tự
    gỡ, vì chính app đã đăng nó.

    Và đây phải là **cùng một bản đếm** với luật cột (:func:`card_stage`),
    nếu không thì bot nói "đăng được rồi" trong khi bảng vẫn giữ thẻ lại.
    """
    kept, pending, dropped = count_decisions(task_node)
    if kept + pending + dropped == 0:
        return False, "thẻ chưa có ảnh nào để đăng"
    if pending:
        return False, f"còn {pending} ảnh chờ 👍/👎"
    if not kept:
        return False, "không còn ảnh nào được giữ"
    return True, ""


def count_decisions(task_node: Dict[str, Any]) -> Tuple[int, int, int]:
    """``(giữ, chờ, bỏ)`` — phán quyết 👍/👎 của mọi ảnh đang treo trên một thẻ.

    Đếm **cả** ảnh bot không xoá được (``mine = 0``, do ``service.py`` đăng
    dưới danh tính người thật).  Ai hỏi "còn mấy ảnh chờ duyệt" cũng muốn biết
    trên thẻ đang có gì, chứ không muốn nghe kể phần nào thuộc quyền ai.

    Tách riêng vì hai bên đọc chung một con số: câu trả lời của bot trên thẻ,
    và luật cột quyết định thẻ có rời *Cần làm* được chưa.  Hai bản đếm khác
    nhau thì bot sẽ nói một đằng còn bảng chạy một nẻo.
    """
    kept = pending = dropped = 0
    for comment in task_node.get("comments") or []:
        if not isinstance(comment, dict):
            continue
        for item in (comment, *(comment.get("replies") or [])):
            if not isinstance(item, dict):
                continue
            if not (is_review_post(item) or is_foreign_review_post(item)):
                continue
            decision = vote_decision(item)
            if decision == DECISION_KEEP:
                kept += 1
            elif decision == DECISION_DELETE:
                dropped += 1
            else:
                pending += 1
    return kept, pending, dropped


def card_stage(
    task_node: Dict[str, Any],
    *,
    cards_missing_sku: int = 0,
    listed: bool = False,
    is_listing: bool | None = None,
) -> pipeline.CardStage:
    """Đọc một thẻ ERP thành nắm sự kiện mà luật cột cần.

    Chỗ duy nhất dịch từ hình dạng ERP sang :class:`pipeline.CardStage`.  Hai
    đường đẩy thẻ — bot quét bảng và app vừa chạy xong ảnh — phải nhìn thấy
    cùng một thẻ theo cùng một cách, nếu không thì cột nào thẻ đứng lại phụ
    thuộc vào việc ai chạm vào nó trước.

    ``cards_missing_sku`` do người gọi đếm, vì nó là chuyện của **cả cụm** chứ
    không đọc được từ một nút.  ``listed`` cũng vậy: chỉ sổ của bot biết bài
    đã lên shop hay chưa.

    ``is_listing`` cũng đè được từ ngoài, và **chỉ** nó: thẻ con trong cụm
    listing mượn ``action_1`` của thẻ cha, nhưng ``sku`` thì không — mã là của
    riêng từng thẻ, cho con mượn mã của cha là đẩy một thẻ chưa đánh số sang
    cột kế.
    """
    meta = task_meta(task_node)
    kept, pending, dropped = count_decisions(task_node)
    ready, _missing = listing_readiness(task_node)
    return pipeline.CardStage(
        status=str(task_node.get("status") or "").strip(),
        images_total=kept + pending + dropped,
        images_pending=pending,
        images_kept=kept,
        has_sku=bool(meta.sku),
        cards_missing_sku=max(0, int(cards_missing_sku or 0)),
        is_listing=meta.is_listing if is_listing is None else bool(is_listing),
        listing_done=bool(ready and listed),
        # Thẻ gốc không bao giờ mang mã; tính nó là thẻ sản phẩm thì lượt
        # quét nào cũng gọi đánh số mà không ghi được gì.
        is_product=bool(parent_task_id(task_node)) and not _carries_machine_image(task_node),
    )


def is_machine_image(node: Dict[str, Any]) -> bool:
    """Ảnh máy tạo ra, chờ người bấm 👍/👎 — bot đăng, hay app đăng dưới tên người.

    Khác :func:`is_foreign_review_post` ở một chỗ: ảnh người thật tự dán vào
    (ảnh mẫu, ảnh tham khảo) không mang dấu của app, nên không phải ảnh máy.
    """
    if not isinstance(node, dict):
        return False
    return is_review_post(node) or (REVIEW_PREFIX in node_markers(node) and not is_bot_note(node))


def _carries_machine_image(task_node: Dict[str, Any]) -> bool:
    for comment in task_node.get("comments") or []:
        if not isinstance(comment, dict):
            continue
        if any(is_machine_image(item) for item in (comment, *(comment.get("replies") or []))):
            return True
    return False


def sku_fill_is_due(tree: Dict[str, Any], task_ids: Sequence[str] = ()) -> bool:
    """Trong ``task_ids`` có thẻ nào đang chờ **máy** điền mã — hay chữa tên — không.

    Cổng của làn nhanh.  Dòng ``taskBoard`` không kèm bình luận, nên không
    phân biệt được thẻ sản phẩm với thẻ Idea còn ảnh chờ phiếu — đánh số thẻ
    Idea lúc ấy là cấp mã sớm.  Đọc cây rồi hỏi đúng luật cột.

    Cổng gật cả cho thẻ **đã có mã** mà tên đang lệch: thẻ bị kéo về *Cần làm*
    còn mang mã làm tên thì chẳng có thẻ nào "chờ mã" cả, và chỉ hỏi mỗi câu
    ấy là lắc đúng lượt cần đi.  Dòng ``ten_cu:`` chỉ có trên cây, nên đây mới
    là chỗ áp được luật "tên người gõ thì không đụng".
    """
    root = tree.get("root") if isinstance(tree.get("root"), dict) else tree
    missing = cards_missing_sku(root)
    wanted = {str(item).strip() for item in task_ids if str(item).strip()}
    for node in iter_tree_nodes(root):
        if wanted and str(node.get("name") or "").strip() not in wanted:
            continue
        if pipeline.needs_sku_fill(card_stage(node, cards_missing_sku=missing)):
            return True
    # ``flatten_tree`` chứ không phải ``iter_tree_nodes``: node con của
    # ``taskFull`` có thể không kèm ``parent_task``, và nó mới là thứ tách thẻ
    # gốc — thẻ không mang mã theo thiết kế — ra khỏi thẻ sản phẩm.
    for card in flatten_tree(root)[1:]:
        if wanted and card.task_id not in wanted:
            continue
        if name_fix_for(card.status, card.meta.sku, card.subject, card.meta.get("ten_cu")):
            return True
    return False


def task_has_agent(task_node: Dict[str, Any], bot_user: str) -> bool:
    if not bot_user:
        return False
    for agent in task_node.get("agents") or []:
        if isinstance(agent, dict) and str(agent.get("bot_user") or "").strip() == bot_user:
            return True
    return False


# ── Trạng thái ─────────────────────────────────────────────────────────


@dataclass
class AgentBotState:
    """Sổ ghi của bot, để một lần khởi động lại không quyết lại từ đầu."""

    path: Path
    bot_user: str = ""
    handled: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    runs: Dict[str, str] = field(default_factory=dict)
    # Thẻ đã giao sang bản Listing. Cố ý **không** nằm trong ``handled`` vì sổ
    # đó tự hết hạn sau ít ngày: quên một thẻ đã đăng nghĩa là đăng lần hai,
    # tức là hai bản nháp trong shop cho cùng một sản phẩm.
    listed: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Thẻ người dùng đã bảo dừng ngay trên thẻ ("@bot dừng lại"). Cũng **không**
    # nằm trong ``handled``: lệnh dừng phải sống cho tới khi có người mở lại,
    # chứ không được tự hết hạn sau ít ngày rồi bot lặng lẽ chạy lại thứ người
    # ta vừa bảo dừng.
    paused: Dict[str, str] = field(default_factory=dict)
    # Những dự án lượt quét gần nhất thấy được. Ghi ra đĩa để phần còn lại của
    # app biết ngay từ lúc khởi động là bot đang đứng ở những board nào, thay
    # vì phải đợi hết một chu kỳ quét mới biết.
    projects: List[str] = field(default_factory=list)
    # Làn nhanh chỉ đọc bảng đang mở. Danh sách này lấy cùng ``taskProjects``
    # với ``projects``; không được gọi ERP thêm chỉ để hỏi trạng thái bảng.
    fast_lane_projects: List[str] = field(default_factory=list)
    # Thẻ đã được nhắc "cột này không nằm trong luật", kèm đúng cái tên cột lúc
    # nhắc. Cũng **không** nằm trong ``handled``: sổ đó tự hết hạn sau ít ngày,
    # mà một bảng đặt sai tên cột thì sai mãi cho tới khi có người sửa — hết
    # hạn ở đây nghĩa là cứ vài ngày lại nhắc lại đúng một câu.
    #
    # Nhớ kèm tên cột chứ không chỉ nhớ thẻ: người ta kéo thẻ sang một cột lạ
    # *khác* thì đó là chuyện mới, và im lặng lúc ấy là bỏ sót.
    warned_columns: Dict[str, str] = field(default_factory=dict)
    # Giờ của từng lượt đã hỏi CLI model, để trần giờ/ngày **sống qua khởi
    # động lại** (A9.1). Trần chỉ nằm trong bộ nhớ là trần bị xoá mỗi lần khởi
    # động lại, mà khởi động lại là chuyện thường trên máy trung tâm — và mỗi
    # lượt là tiền thật, nên nó phải nằm cùng chỗ với ``already_handled``.
    brain_calls: List[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> "AgentBotState":
        target = Path(path) if path is not None else DATA_DIR / "agent_bot_state.json"
        state = cls(path=target)
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return state
        if not isinstance(raw, dict):
            return state
        state.bot_user = str(raw.get("bot_user") or "").strip()
        handled = raw.get("handled")
        if isinstance(handled, dict):
            state.handled = {str(k): v for k, v in handled.items() if isinstance(v, dict)}
        runs = raw.get("runs")
        if isinstance(runs, dict):
            state.runs = {str(k): str(v) for k, v in runs.items()}
        listed = raw.get("listed")
        if isinstance(listed, dict):
            state.listed = {str(k): v for k, v in listed.items() if isinstance(v, dict)}
        paused = raw.get("paused")
        if isinstance(paused, dict):
            state.paused = {str(k): str(v) for k, v in paused.items() if str(k).strip()}
        warned = raw.get("warned_columns")
        if isinstance(warned, dict):
            state.warned_columns = {
                str(k): str(v) for k, v in warned.items() if str(k).strip()
            }
        projects = raw.get("projects")
        if isinstance(projects, list):
            state.projects = [
                name for name in (str(item).strip().upper() for item in projects) if name
            ]
        fast_lane_projects = raw.get("fast_lane_projects")
        if isinstance(fast_lane_projects, list):
            state.fast_lane_projects = [
                name for name in (str(item).strip().upper() for item in fast_lane_projects) if name
            ]
        else:
            # Sổ cũ chưa có khoá này. Đừng để làn nhanh mù cho tới lượt quét
            # chính đầu tiên — cứ lấy tạm cả phạm vi, lượt quét sau lọc lại.
            state.fast_lane_projects = list(state.projects)
        brain_calls = raw.get("brain_calls")
        if isinstance(brain_calls, list):
            state.brain_calls = [stamp for stamp in (str(item).strip() for item in brain_calls) if stamp]
            state.prune_brain_calls()
        return state

    def save(self) -> None:
        self.prune()
        payload = {
            "bot_user": self.bot_user,
            "handled": self.handled,
            "runs": self.runs,
            "listed": self.listed,
            "paused": self.paused,
            "warned_columns": self.warned_columns,
            "projects": self.projects,
            "fast_lane_projects": self.fast_lane_projects,
            "brain_calls": self.brain_calls,
            "saved_at": _utc_now_text(),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Ghi qua tệp tạm rồi thay chỗ: một lần tắt máy giữa chừng không
            # được phép để lại file state cụt làm bot quyết lại từ đầu.
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        except OSError as exc:
            log.warning("Không ghi được state của agent bot: %s", exc)

    def prune(self) -> None:
        self.prune_brain_calls()
        cutoff = datetime.now(timezone.utc) - timedelta(days=HANDLED_RETENTION_DAYS)
        for comment_id, entry in list(self.handled.items()):
            stamp = str(entry.get("at") or "")
            try:
                when = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when < cutoff:
                self.handled.pop(comment_id, None)

    def prune_brain_calls(self, *, now: datetime | None = None) -> None:
        """Bỏ những lượt đã ra khỏi cửa sổ dài nhất (một ngày).

        Cửa sổ *cuốn chiếu*, không phải mốc nửa đêm: trần theo mốc nghĩa là
        23:59 hết trần thì 00:01 mở lại cả ví.
        """
        floor = (now or datetime.now(timezone.utc)) - BRAIN_CALL_LEDGER_WINDOW
        self.brain_calls = [
            stamp
            for stamp in self.brain_calls
            if (when := _read_stamp(stamp)) is not None and when >= floor
        ]

    def record_brain_call(self, *, now: datetime | None = None) -> None:
        moment = now or datetime.now(timezone.utc)
        self.brain_calls.append(moment.isoformat(timespec="seconds"))
        self.prune_brain_calls(now=moment)

    def brain_calls_within(self, window: timedelta, *, now: datetime | None = None) -> int:
        """Số lượt đã hỏi trong ``window`` gần nhất."""
        moment = now or datetime.now(timezone.utc)
        floor = moment - window
        return sum(1 for stamp in self.brain_calls if (when := _read_stamp(stamp)) and when >= floor)

    def already_handled(self, comment_id: str) -> bool:
        return bool(comment_id) and comment_id in self.handled

    def record(self, comment_id: str, task: str, decision: str) -> None:
        if not comment_id:
            return
        self.handled[comment_id] = {"task": task, "decision": decision, "at": _utc_now_text()}

    def already_listed(self, task: str) -> bool:
        return bool(task) and task in self.listed

    def record_listing(self, task: str, outcome: Dict[str, Any]) -> None:
        """Ghi lúc **giao đi**. Chưa phải lúc đăng xong — xem ``confirm_listing``."""
        if not task:
            return
        self.listed[task] = {
            "queue_task": str(outcome.get("queue_task_id") or ""),
            "machine": str(outcome.get("machine_id") or ""),
            "at": _utc_now_text(),
            "confirmed": False,
        }

    def listing_confirmed(self, task: str) -> bool:
        """Bản nháp đã thật sự nằm trong shop chưa.

        Khác ``already_listed`` một chữ mà khác hẳn về hậu quả: cái kia chặn
        giao lần hai nên phải bật lên **ngay lúc giao**; cái này mở cổng sang
        *Hoàn thành* nên chỉ được bật khi bản Listing báo chạy xong. Trộn hai
        câu hỏi làm một thì một máy ảo đang ngủ cũng đủ để thẻ nhảy sang
        *Hoàn thành* với cái shop trống không.

        Dòng sổ cũ chưa có khoá ``confirmed`` (ghi trước khi có bước hỏi lại)
        đọc thành *chưa xác nhận*: cùng lắm là hỏi lại bên kia một lượt.
        """
        entry = self.listed.get(task) if task else None
        return bool(isinstance(entry, dict) and entry.get("confirmed"))

    def listing_handover(self, task: str) -> Dict[str, Any]:
        """Lượt đã giao cho thẻ này: mã hàng đợi và máy, để còn đi hỏi lại."""
        entry = self.listed.get(task) if task else None
        return dict(entry) if isinstance(entry, dict) else {}

    def confirm_listing(self, task: str, outcome: Dict[str, Any]) -> None:
        entry = self.listed.get(task)
        if not isinstance(entry, dict):
            return
        entry["confirmed"] = True
        entry["confirmed_at"] = _utc_now_text()
        if outcome.get("card_moved"):
            # Bản Listing tự kéo thẻ sang Done khi chạy xong. Ghi lại để đọc
            # log còn biết cột đổi vì bên kia hay vì luật cột bên này.
            entry["card_moved_by_listing"] = True

    def already_warned_column(self, task: str, column: str) -> bool:
        """Thẻ này đã được nhắc về đúng cái cột đang đứng chưa."""
        return bool(task) and self.warned_columns.get(task, "") == str(column or "").strip()

    def warn_column(self, task: str, column: str) -> None:
        if task:
            self.warned_columns[task] = str(column or "").strip()

    def is_paused(self, task: str) -> bool:
        return bool(task) and task in self.paused

    def pause(self, task: str) -> None:
        if task:
            self.paused[task] = _utc_now_text()

    def resume(self, task: str) -> None:
        self.paused.pop(task, None)

    def clear_cooldown(self, task: str) -> None:
        """Quên dấu thời gian lượt chạy gần nhất, để lượt quét sau nhận thẻ ngay.

        Đây là toàn bộ nội dung của lệnh "chạy đi" trên thẻ: bot không chạy
        thẳng giữa lượt quét — chạy thẳng nghĩa là hai đường cùng gọi một
        ``autorun_hook`` mà cả app chỉ có một phiên Flow — nó chỉ gỡ cái phanh
        nguội để thẻ được nhận ở lượt kế tiếp.
        """
        self.runs.pop(task, None)

    def autorun_is_cool(self, task: str, cooldown_s: int) -> bool:
        stamp = self.runs.get(task)
        if not stamp or cooldown_s <= 0:
            return True
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            return True
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - when >= timedelta(seconds=cooldown_s)

    def mark_autorun(self, task: str) -> None:
        self.runs[task] = _utc_now_text()


# ── Bot ────────────────────────────────────────────────────────────────

# Hook chạy việc: nhận id task cha đã gắn agent, trả về payload tuỳ ý.
AutorunHook = Callable[[str], Awaitable[Dict[str, Any]]]
# Hook listing nhận thêm chính thẻ đã đọc: bên kia cần ``meta`` để biết máy
# Etsy nào nhận, và đọc lại thẻ lần nữa chỉ để lấy thứ đang cầm trên tay là
# tốn một request của trần 60/phút.
ListingHook = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]
# Hook hỏi lại: nhận mã hàng đợi + máy đã giao, trả về lượt ấy bên kia chạy tới
# đâu. Tách khỏi ``ListingHook`` vì hai câu hỏi khác nhau, và vì giao xong rồi
# thì không còn cần cái cây thẻ nữa — chỉ cần biên lai đã ghi trong sổ.
ListingConfirmHook = Callable[[str, str], Awaitable[Dict[str, Any]]]
# Hook luật cột: nhận id một thẻ, đẩy nó đi một bước và trả về nước đã đi.
# Bot cố ý **không** tự gọi ``updateTaskStatus``: đường ghi trạng thái duy nhất
# của app đi qua ``service.py``, nơi có hàng rào kiểm thẻ có thuộc dự án được
# phép hay không. Thêm một đường ghi thứ hai là thêm một chỗ hàng rào ấy vắng
# mặt.
PipelineHook = Callable[[str], Awaitable[Dict[str, Any]]]
# Hook sửa thẻ: nhận id thẻ và những ô người ta vừa bảo sửa, ghi xuống ERP.
# Cùng lý do với ``PipelineHook`` — đường ghi đi qua ``service.py`` để hàng rào
# kiểm dự án nằm trên **mọi** đường ghi, chứ không riêng đường của nút bấm.
# Đồng bộ chứ không ``async``: ``chat_pass`` chạy trong ``asyncio.to_thread``,
# nên bên trong nó không có vòng lặp sự kiện nào để ``await``.
EditHook = Callable[[str, Tuple[Tuple[str, str], ...]], Dict[str, Any]]
# Hook đánh số: nhận một thẻ của cụm và cờ *ghi đè cả mã đã có*, trả về
# đúng payload của ``service.fill_task_skus``.  Không buộc phải đưa đúng thẻ
# gốc: app tự leo lên gốc thật trước khi tính, vì chỉ app mới đọc được thẻ
# cha nằm ngoài cái cây bot đang cầm — mà gốc (idea cha) mới là chỗ khai
# ``product:``.  Đi qua app cùng lý do với hai hook trên, thêm một lý do
# riêng: bảng tra mã (tên sản phẩm → phần tên SKU) và sổ số đếm xuyên dự án
# đều nằm bên app, bot không cầm.  Đồng bộ, vì ``chat_pass`` gọi nó từ trong
# ``asyncio.to_thread`` như ``EditHook``.
SkuHook = Callable[[str, bool], Dict[str, Any]]
# Hook chép Thuộc tính: nhận id thẻ con và những ô thẻ con còn thiếu so với
# thẻ cha, trả về ``{"written": {...}}`` — những ô thật sự đã ghi. Đi qua app
# cùng lý do với ``EditHook``: hàng rào dự án nằm trên mọi đường ghi, và app
# đọc lại thẻ ngay trước khi ghi vì ``updateTaskMeta`` thay cả khối. Đồng bộ,
# vì ``meta_inherit_pass`` chạy trong ``asyncio.to_thread``.
MetaInheritHook = Callable[[str, Dict[str, str]], Dict[str, Any]]

#: Câu bảng từ khoá không hiểu → phán quyết của Claude, hoặc ``None`` nếu
#: không dùng được (tắt, hỏng, hết giờ).  Nhận thẳng ``CardBrief`` chứ không
#: nhận một dict: bên kia cần biết ô nào **đang** là gì mới hiểu nổi câu "đổi
#: mẫu khác đi", mà dựng lại bối cảnh ấy một lần nữa là dựng lại một lần sai.
BrainHook = Callable[[str, "CardBrief"], BrainVerdict | None]


@dataclass(frozen=True)
class ChatActionOutcome:
    """Việc bot làm sau khi soạn câu trả lời, kể lại thành một câu.

    ``note`` nối vào cuối câu trả lời và có thể là tin vui ("đã ghi mã cho
    10 thẻ") lẫn tin buồn ("ERP không nhận").  ``failed`` mới là thứ quyết
    định bản ghi có dòng ``error`` hay không — một câu kể việc đã xong mà
    bị đánh dấu là lỗi thì mọi bảng đếm lỗi sau này đều sai.
    """

    note: str = ""
    failed: bool = False


def _sku_outcome_line(result: Dict[str, Any]) -> str:
    """Payload của lượt đánh số → một câu kể lại cho người vừa hỏi.

    Bốn chuyện phải tách bạch, vì người đọc làm bốn việc khác nhau sau đó: ghi
    được mấy thẻ (xong, đi tiếp), không thẻ nào cần đổi (cũng xong — nhưng
    không nói ra thì người ta tưởng bot lờ mình), thẻ bị bỏ qua kèm lý do
    (chưa được kéo sang *Đang làm* thì chờ người duyệt, thiếu dòng
    ``product:`` trên thẻ idea cha thì đi điền), và thẻ có mã nhưng chưa đổi
    được tên (mã vẫn đúng, chỉ cái bảng nhìn vào là còn tên cũ).

    Cắt danh sách ở vài thẻ đầu: đây là một bình luận trên thẻ, không phải bản
    log — kể tên đủ ba mươi thẻ thì cái lý do quan trọng nhất trôi mất tăm.
    """
    written = [item for item in (result.get("written") or []) if isinstance(item, dict)]
    failed = [item for item in (result.get("failed") or []) if isinstance(item, dict)]
    skipped = [item for item in (result.get("skipped") or []) if isinstance(item, dict)]
    rename_failed = [item for item in (result.get("rename_failed") or []) if isinstance(item, dict)]
    parts: List[str] = []
    if written:
        shown = ", ".join(f"{item.get('task_id')} → {item.get('sku')}" for item in written[:5])
        more = f" và {len(written) - 5} thẻ nữa" if len(written) > 5 else ""
        parts.append(f"Đã ghi mã cho {len(written)} thẻ: {shown}{more}.")
    else:
        parts.append("Không thẻ nào phải đổi mã.")
    if failed:
        detail = "; ".join(f"{item.get('task_id')} ({item.get('error')})" for item in failed[:3])
        parts.append(f"{len(failed)} thẻ ERP không nhận: {detail}.")
    if skipped:
        detail = "; ".join(f"{item.get('task_id')} — {item.get('reason')}" for item in skipped[:3])
        more = f" (và {len(skipped) - 3} thẻ nữa)" if len(skipped) > 3 else ""
        parts.append(f"Bỏ qua {len(skipped)} thẻ: {detail}{more}.")
    if rename_failed:
        # Mã đã nằm trên thẻ rồi, chỉ tên là chưa đổi.  Không nói ra thì người
        # ta nhìn bảng thấy tên cũ và tưởng cả lượt chưa chạy.
        detail = "; ".join(f"{item.get('task_id')} ({item.get('error')})" for item in rename_failed[:3])
        parts.append(f"{len(rename_failed)} thẻ có mã nhưng giữ tên cũ: {detail}.")
    return " ".join(parts)


class AgentBot:
    """Một lượt quét: tìm task đã gắn agent → dọn theo phiếu → chạy việc."""

    def __init__(
        self,
        config: AgentBotConfig,
        client: AgentBotClient | None = None,
        state: AgentBotState | None = None,
        autorun_hook: AutorunHook | None = None,
        listing_hook: ListingHook | None = None,
        listing_confirm_hook: ListingConfirmHook | None = None,
        pipeline_hook: PipelineHook | None = None,
        book: AccountBook | None = None,
        edit_hook: EditHook | None = None,
        sku_hook: SkuHook | None = None,
        brain_hook: BrainHook | None = None,
        brain_max_calls: int = 5,
        brain_max_calls_per_hour: int = 30,
        brain_max_calls_per_day: int = 150,
        meta_inherit_hook: MetaInheritHook | None = None,
        sku_book: Callable[[], Any] | None = None,
    ) -> None:
        self.config = config
        self.client = client or AgentBotClient(config)
        self.state = state if state is not None else AgentBotState.load()
        self.autorun_hook = autorun_hook
        self.listing_hook = listing_hook
        self.listing_confirm_hook = listing_confirm_hook
        self.pipeline_hook = pipeline_hook
        # Sổ tay tài khoản, để bot trả lời được câu "thẻ này lên shop nào".
        # Không có sổ thì vẫn đọc được cái nhãn ``acc32`` theo quy ước, chỉ là
        # không biết tên shop — đúng mức hiểu biết của một máy chưa có sổ.
        self.book = book if book is not None else AccountBook()
        # Không có hook thì bot vẫn *hiểu* lệnh sửa, chỉ là không ghi được —
        # và nó nói thẳng ra như vậy chứ không im lặng gật đầu.
        self.edit_hook = edit_hook
        # Cũng vậy: không có hook thì bot vẫn nhận lệnh đánh số và vẫn nói
        # rõ là chưa nối được đường ghi, chứ không gật đầu rồi thôi.
        self.sku_hook = sku_hook
        # Không có hook thì thẻ con vẫn được *đọc* kèm Thuộc tính của thẻ cha
        # (``inherit``), chỉ là không ghi xuống — Review Lister thì đọc đúng
        # khối của thẻ con nên vẫn thấy thiếu.
        self.meta_inherit_hook = meta_inherit_hook
        # Đọc bảng mã trên đĩa cho bảng SKU, để gỡ lời nhắc "bảng SKU chưa có
        # dòng" đã cũ. Không có thì bảng giữ lời nhắc như cũ.
        self.sku_book_loader = sku_book
        # Suất chép còn lại của lượt quét này; đặt lại ở đầu mỗi lượt.
        self._meta_inherit_left = META_INHERIT_PER_SCAN
        # Thẻ ngoài cây bị cắt đã hỏi ERP rồi, kèm dấu vân tay giá trị cha lúc
        # hỏi. Dòng bảng không có khối Thuộc tính, nên không nhớ thì mỗi lượt
        # quét lại đọc lại đúng những thẻ đã đủ. Sống trong RAM, **không** đặt
        # lại mỗi lượt; khởi động lại thì hỏi lại một vòng.
        self._meta_inherit_asked: Dict[str, Tuple[Tuple[str, str], ...]] = {}
        self.brain_hook = brain_hook
        # Trần **mỗi lượt quét**, không phải trần mỗi thẻ: một bảng đang tán
        # gẫu có thể có hàng chục câu bot không hiểu, và mỗi câu là tiền thật.
        self.brain_max_calls = max(0, int(brain_max_calls))
        self._brain_calls = 0
        # Và trần **cuốn chiếu theo giờ/ngày**, nằm trên đĩa nên nó sống qua
        # khởi động lại (A9.1).  Trần mỗi vòng quét ở trên bị đặt lại về 0 ở
        # đầu mỗi lượt, mà lượt quét chạy mỗi ~3 phút: một mình nó thì trần
        # thật là 5 × 20 = 100 lượt mỗi giờ, tức là không có trần nào.
        self.brain_max_calls_per_hour = max(0, int(brain_max_calls_per_hour))
        self.brain_max_calls_per_day = max(0, int(brain_max_calls_per_day))
        # Cửa sổ nào đã nói "hết trần" rồi thì không nói lại (A9.3): mỗi câu
        # một dòng nghĩa là một bảng đang tán gẫu làm log không đọc được nữa.
        self._brain_budget_said: set[str] = set()
        # Thẻ đang mắc ở một cột lạ, gom trong lúc chọn việc và đăng ở
        # ``column_pass``. Vòng đời đúng một lượt quét.
        self._column_alerts: List[Tuple[str, str]] = []
        # Dòng ``taskBoard`` của từng dự án, và dự án của từng thẻ, đọc trong
        # ``candidate_tasks``. Vòng đời đúng một lượt quét: ``pipeline_pass``
        # dùng lại khi cây bị cắt, khỏi tốn thêm request đọc bảng.
        self._scan_boards: Dict[str, List[Dict[str, Any]]] = {}
        self._scan_task_project: Dict[str, str] = {}
        # Dự án nào đã kêu "cột nguồn không khớp", và kêu lúc bảng đang bày
        # những cột nào.  Trong bộ nhớ, không vào sổ: câu này nói cho người đọc
        # log của lần chạy *này*, và một dòng nhắc lại sau khi khởi động lại thì
        # rẻ hơn nhiều so với việc bỏ sót một bảng gõ sai tên cột.
        self._cot_nguon_da_keu: Dict[str, str] = {}
        # Đã nhắc "đang chạy không khoá tác giả" trong lượt quét này chưa
        # (C3.2). Vòng đời đúng một lượt quét, đặt lại cùng chỗ với trần hỏi.
        self._author_lock_warned = False
        # Những bình luận đã bị hàng rào tác giả từ chối và đã ghi log. Trong
        # bộ nhớ chứ không vào sổ ``handled``: sổ ấy là "đã quyết xong", còn
        # đây chỉ là "đã nhắc rồi" — ghi vào sổ thì thêm người vào danh sách
        # cũng không cứu được câu cũ, mà xoá khỏi bộ nhớ thì cùng lắm là nhắc
        # lại một dòng sau khi khởi động lại.
        self._author_refused_said: set[str] = set()
        # Mỗi thể hiện bot chỉ một lượt quét chạy tại một lúc. Nút "chạy ngay"
        # gọi ``run_once`` trên đúng bot mà ``run_forever`` đang quét; không
        # khoá thì hai lượt đan nhau: ``_scan_boards``, trần mỗi lượt, cảnh báo
        # cột và ``state.save()`` bị lượt kia gán lại giữa chừng. Khoá của
        # ``threading`` chứ không phải ``asyncio.Lock``: khoá asyncio gắn với
        # một event loop, mà bot sống qua nhiều loop (script, test). Làn nhanh
        # SKU không gọi ``run_once`` nên không bao giờ đụng khoá này.
        self._scan_lock = threading.Lock()

    # ── phạm vi ────────────────────────────────────────────────────────

    def scope_projects(self) -> List[str]:
        """Các dự án bot được phép quét.

        Không cấu hình thì lấy đúng danh sách ERP trả về — tức là những dự án
        bot đã được thêm vào ``Project User``. Phạm vi do ERP quyết, không do
        file cấu hình, nên gỡ bot khỏi dự án là nó hết thấy dự án đó ngay.
        """
        catalog = self.client.task_projects()
        visible = [
            str(item.get("name") or "").strip().upper()
            for item in catalog
            if str(item.get("name") or "").strip()
        ]
        completed = {
            str(item.get("name") or "").strip().upper()
            for item in catalog
            if str(item.get("name") or "").strip()
            and str(item.get("status") or "").strip().casefold() == "completed"
        }
        if not self.config.projects:
            return self._remember(visible, completed)
        wanted = set(self.config.projects)
        allowed = [name for name in visible if name in wanted]
        for missing in sorted(wanted - set(visible)):
            log.warning(
                "Agent bot được cấu hình cho %s nhưng ERP không cho nó thấy dự án đó "
                "(chưa thêm bot vào Project User?).",
                missing,
            )
        return self._remember(allowed, completed)

    def _remember(self, projects: List[str], completed: set[str] | None = None) -> List[str]:
        """Ghi lại phạm vi vừa thấy, cho phần còn lại của app dùng chung.

        Thêm bot vào một board trên ERP là xong — không phải khai lại board đó
        ở đâu nữa. Nhưng hàng rào dự án của app lại là một sổ riêng, nên nó đọc
        đúng cái sổ này để hai bên không bao giờ lệch nhau.
        """
        self.state.projects = list(projects)
        # Lượt quét chính vẫn phải đọc cả bảng đã xong: người dùng có thể kéo
        # thẻ trở lại đó. Chỉ làn nhanh bỏ chúng để khỏi gõ vô ích mỗi nhịp.
        self.state.fast_lane_projects = [
            project for project in projects if project not in (completed or set())
        ]
        return projects

    @staticmethod
    def _drop_inherited_children(attached: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Bỏ thẻ con khi thẻ cha của chính nó cũng đang gắn bot.

        Gắn bot vào thẻ cha là lan xuống cả thẻ con (``inherit_pass``), mà cây
        của thẻ cha vốn đã chứa sẵn bình luận của con. Không lọc thì trần
        ``max_cards_per_scan`` bị chính đám con ăn hết còn thẻ cha phải đợi
        lượt sau — gắn bot vào một thẻ hoá ra làm thẻ ấy chạy chậm đi.

        Thẻ con được gắn *một mình*, cha không gắn, thì vẫn giữ: đó là người
        dùng cố ý chỉ đúng một thẻ.
        """
        names = {
            name for name in (str(task.get("name") or "").strip() for task in attached) if name
        }
        return [
            task
            for task in attached
            if str(task.get("parent_task") or "").strip() not in names
        ]

    def _note_unknown_columns(
        self,
        project: str,
        tasks: Sequence[Dict[str, Any]],
        columns: Sequence[str],
    ) -> None:
        """Bảng đặt tên cột lạ thì kêu lên, thay vì để thẻ đứng im vô thời hạn.

        Đây là cái bẫy đắt nhất của việc thêm bot vào một bảng mới.
        ``normalize_status`` không nhận ra tên cột thì ``decide`` trả nước đi
        rỗng và bot lặng lẽ đi tiếp: không exception, không lỗi HTTP, không
        một dòng log.  Nhưng nó **vẫn** tạo ảnh và vẫn đăng ảnh lên chờ duyệt
        — nên cái bảng ấy đọc y hệt một bảng đã làm xong, trong khi thật ra
        không thẻ nào nhúc nhích được và sẽ không bao giờ nhúc nhích.

        Chỉ *ghi nhận* ở đây, việc đăng để dành cho :meth:`column_pass`: bước
        chọn thẻ là bước chỉ-đọc, và trộn một lượt ghi vào giữa nó thì một lần
        ERP từ chối sẽ làm hỏng cả lượt quét.
        """
        strays = pipeline.unknown_columns(columns)
        if not strays:
            return
        stranded = [
            task
            for task in tasks
            if is_idea_card(task) and not pipeline.normalize_status(task.get("status"))
        ]
        # Kể tên cột nguyên văn, ngay trong log: người đọc log phải sửa được
        # mà không cần mở ERP ra dò xem bảng đang đặt tên là gì.
        log.warning(
            "Bảng %s có cột không nằm trong luật cột: %s. %s thẻ Idea đang mắc "
            "ở đó — bot vẫn tạo ảnh nhưng không đẩy cột được.",
            project,
            ", ".join(strays),
            len(stranded),
        )
        for task in stranded[: max(1, self.config.max_column_alerts)]:
            task_id = str(task.get("name") or "").strip()
            column = str(task.get("status") or "").strip()
            if not task_id or self.state.already_warned_column(task_id, column):
                continue
            self._column_alerts.append((task_id, column))

    def candidate_tasks(self, projects: Sequence[str], bot_user: str = "") -> List[Dict[str, Any]]:
        """Những thẻ bot nhận là việc của mình, xét theo từng dự án.

        Thêm bot vào một dự án đã là lời giao việc rồi — đó là điều người dùng
        thấy trên trang Agent Bot — nên mặc định bot nhận mọi thẻ Idea của dự án
        đó. Nhưng nếu trong dự án có thẻ được gắn đích danh bot, thì dự án ấy
        thu về đúng những thẻ đó: gắn vào một thẻ chỉ có nghĩa duy nhất là "chạy
        thẻ này", và hiểu ngược lại thì thao tác gắn thẻ hoá ra không làm gì cả.

        Bảng dự án đã trả sẵn ``child_total`` và ``status`` nên bước lọc này
        không tốn thêm request nào — ``taskFull`` chỉ được tiêu cho thẻ đã chọn.
        """
        # Dọn sổ nhắc của lượt trước: danh sách này sống đúng một lượt quét, và
        # một lượt kết thúc sớm (chưa nhận ra danh tính bot) không được để lại
        # thẻ cũ cho lượt sau nhắc nhầm.
        self._column_alerts = []
        self._scan_boards = {}
        self._scan_task_project = {}
        found: List[Dict[str, Any]] = []
        for project in projects:
            try:
                tasks, columns = self.client.board_snapshot(project)
            except AgentBotError as exc:
                log.warning("Không đọc được bảng %s: %s", project, exc)
                continue
            self._note_unknown_columns(project, tasks, columns)
            self._scan_boards[project] = tasks
            for task in tasks:
                name = str(task.get("name") or "").strip()
                if name:
                    self._scan_task_project[name] = project
            if bot_user:
                attached = [task for task in tasks if task_has_agent(task, bot_user)]
            else:
                # Chưa biết mình là ai thì thẻ gắn agent bất kỳ vẫn đáng đọc:
                # chính nó là chỗ rẻ nhất để nhận ra danh tính của bot.
                attached = [task for task in tasks if task.get("agents")]
            if attached:
                found.extend(self._drop_inherited_children(attached))
                continue
            if self.config.scope != SCOPE_BOARD:
                continue
            wanted = self.config.source_statuses
            open_cards = [task for task in tasks if is_idea_card(task)]
            picked = [task for task in open_cards if card_is_in_source_column(task, wanted)]
            if wanted and open_cards and not picked:
                # Gõ sai tên cột thì bot im lặng bỏ cả board, và im lặng ấy đọc
                # y hệt một board đã làm xong. Kể tên các cột đang thật sự có
                # để người đọc log sửa được ngay mà không phải mở ERP ra dò.
                dang_co = ", ".join(
                    sorted(
                        {str(task.get("status") or "").strip() or "(trống)" for task in open_cards}
                    )
                )
                # Nhưng kêu *một lần* thôi. Thẻ nằm chờ ở cột ngoài cho tới khi
                # có người kéo sang cột nguồn là trạng thái nghỉ bình thường của
                # mọi bảng, không phải lỗi gõ — và trên hvg-pc ngày 13/09/2026
                # câu này lặp mỗi hai phút trên 8 bảng, khoảng 185 dòng mỗi giờ
                # suốt ngày đêm. Cảnh báo kêu mãi thì lỗi thật chìm mất giữa nó.
                # Nhớ kèm danh sách cột: bảng đổi cột là tình hình mới, phải kêu
                # lại, nếu không thì cái bẫy gõ sai tên cột tàng hình trở lại.
                if self._cot_nguon_da_keu.get(project) != dang_co:
                    self._cot_nguon_da_keu[project] = dang_co
                    log.warning(
                        "Cột nguồn %s không khớp thẻ đang mở nào của %s; đang có: %s.",
                        ", ".join(wanted),
                        project,
                        dang_co,
                    )
            elif picked:
                # Bảng chạy lại được thì xoá sổ nhắc: kéo thẻ vào đúng cột rồi
                # kéo ra lại phải kêu lần nữa, chứ im luôn thì lượt trống kế
                # tiếp đọc y hệt "bảng đang chạy tốt".
                self._cot_nguon_da_keu.pop(project, None)
            found.extend(picked)
            found.extend(self._listing_stragglers(tasks, picked))
        return found

    def _listing_stragglers(
        self,
        tasks: Sequence[Dict[str, Any]],
        picked: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Thẻ đã giao cho Etsy nhưng luật cột vừa đẩy nó khỏi cột nguồn.

        Lọc theo cột chạy **trước** khi có ai nhìn vào sổ listed, nên một thẻ
        rời *Cần làm* đúng vào lúc nó được giao đi là rơi khỏi tầm quét đúng
        vào lúc nó cần được hỏi lại nhất. Không ai hỏi thì không bao giờ có
        ``done``, và không có ``done`` thì cổng sang *Hoàn thành* đóng vĩnh
        viễn — thẻ nằm ở *Đang review* trong khi bản nháp đã nằm sẵn trong shop.

        Kéo về đúng những thẻ ấy, không hơn: đã xác nhận rồi thì thôi, và thẻ
        đã đóng thì việc của nó xong rồi. Thẻ con đi theo cây của thẻ cha, nên
        con còn treo thì kéo cha về.
        """
        pending = {
            str(task.get("name") or "")
            for task in tasks
            if self.state.already_listed(str(task.get("name") or ""))
            and not self.state.listing_confirmed(str(task.get("name") or ""))
        }
        pending |= {
            str(task.get("parent_task") or "")
            for task in tasks
            if str(task.get("name") or "") in pending
        }
        pending.discard("")
        chosen = {str(task.get("name") or "") for task in picked}
        stragglers: List[Dict[str, Any]] = []
        for task in tasks:
            task_id = str(task.get("name") or "")
            if not task_id or task_id in chosen or task_id not in pending:
                continue
            if str(task.get("parent_task") or ""):
                continue
            if compact_status(task.get("status")) in CLOSED_STATUSES:
                continue
            stragglers.append(task)
        return stragglers

    def resolve_bot_user(self, trees: Sequence[Dict[str, Any]] = ()) -> str:
        """Danh tính của chính bot, ưu tiên cách không phải ghi gì lên ERP.

        GraphQL không có field "tôi là ai", nên thứ tự là: cấu hình → sổ ghi →
        suy ra từ ``mine = 1`` của một bình luận bot từng đăng. Chỉ khi cả ba
        đều trắng mới cần dò bằng cách ghi (``probe_bot_user``), vì lượt dò đó
        để lại một bình luận trên thẻ của người khác dù chỉ trong chốc lát.
        """
        if self.config.bot_user:
            return self.config.bot_user
        if self.state.bot_user:
            return self.state.bot_user
        for tree in trees:
            for node in iter_tree_nodes(tree.get("root") or {}):
                for comment in node.get("comments") or []:
                    if not isinstance(comment, dict):
                        continue
                    candidates = [comment, *(comment.get("replies") or [])]
                    for item in candidates:
                        if isinstance(item, dict) and int(item.get("mine") or 0) == 1:
                            owner = str(item.get("owner") or "").strip()
                            if owner:
                                self.state.bot_user = owner
                                return owner
        return ""

    def probe_bot_user(self, task: str) -> str:
        """Hỏi ERP "tôi là ai" bằng một bình luận rồi xoá ngay.

        Cách cuối cùng, và cố ý gây tiếng động nhỏ nhất có thể: một bình luận
        mang dấu riêng, đọc ``owner`` ở đúng bản ghi có ``mine = 1``, rồi xoá.
        Đặt ``ERP_AGENT_BOT_USER`` là khỏi cần lượt này.
        """
        mark = f"{BOT_NOTE_MARK} nhận diện agent {int(time.time())}"
        self.client.add_comment(task, f"{mark} — bình luận kỹ thuật, sẽ tự xoá.")
        owner = ""
        comment_id = ""
        root = (self.client.task_full(task, depth=0) or {}).get("root") or {}
        for comment in root.get("comments") or []:
            if not isinstance(comment, dict) or mark not in plain_text(comment.get("content")):
                continue
            comment_id = str(comment.get("name") or "")
            owner = str(comment.get("owner") or "").strip()
            break
        if comment_id:
            try:
                self.client.delete_comment(task, comment_id)
            except AgentBotError as exc:
                log.warning("Không xoá được bình luận nhận diện trên %s: %s", task, exc)
        if owner:
            self.state.bot_user = owner
        return owner

    # ── dọn theo phiếu ─────────────────────────────────────────────────

    def janitor_pass(self, tree: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Áp 👍 giữ / 👎 xoá lên mọi ảnh bot đã đăng trong cây task này."""
        applied: List[Dict[str, Any]] = []
        if tree.get("truncated"):
            # Hai trần độc lập (số node, ngân sách hàng) có thể cắt cây; im
            # lặng bỏ qua phần bị cắt sẽ trông y hệt "không có gì để làm".
            log.warning(
                "taskFull cắt bớt cây của %s (node=%s/%s, row=%s/%s) — lượt này chưa quét hết.",
                ((tree.get("root") or {}).get("name")),
                tree.get("node_count"),
                tree.get("max_nodes"),
                tree.get("row_count"),
                tree.get("max_rows"),
            )
        for node in iter_tree_nodes(tree.get("root") or {}):
            task_id = str(node.get("name") or "").strip()
            if not task_id:
                continue
            self._warn_about_foreign_posts(task_id, node)
            for post in iter_review_posts(node):
                comment_id = str(post.get("name") or "").strip()
                if not comment_id or self.state.already_handled(comment_id):
                    continue
                decision = vote_decision(post)
                if decision == DECISION_PENDING:
                    continue
                outcome = self._apply_decision(task_id, post, decision)
                if outcome is not None:
                    applied.append(outcome)
        return applied

    def _warn_about_foreign_posts(self, task_id: str, node: Dict[str, Any]) -> int:
        """Nói ra khi có việc bot nhìn thấy mà không với tới được.

        Nhánh "👎 là xoá" chỉ chạy trên ảnh do chính bot đăng, mà hôm nay ảnh
        do ``service.py`` đăng dưới danh tính người thật. Một nhánh chết lặng
        lẽ trông y hệt một nhánh không có việc, nên chỗ này phải kêu: có bao
        nhiêu ảnh **đáng lẽ đã bị gỡ** mà vẫn nằm nguyên, và thiếu cái gì.

        Chỉ đếm phiếu 👎. Ảnh được 👍 giữ thì chẳng có việc gì phải làm, kêu
        lên là kêu vô cớ — mà một cảnh báo lặp lại mỗi lượt quét trên thẻ đã
        duyệt xong thì chính nó dạy người đọc bỏ qua dòng này.
        """
        stuck = [post for post in iter_foreign_review_posts(node)
                 if vote_decision(post) == DECISION_DELETE]
        if not stuck:
            return 0
        log.warning(
            "%s: %s ảnh bị 👎 nhưng bot không gỡ được vì không phải "
            "bot đăng (mine=0). Nhánh “👎 là xoá” còn nằm im cho tới khi ảnh được "
            "đăng qua AgentBotClient.publish_image.",
            task_id,
            len(stuck),
        )
        return len(stuck)

    def _apply_decision(self, task_id: str, post: Dict[str, Any], decision: str) -> Dict[str, Any] | None:
        comment_id = str(post.get("name") or "")
        label = self._post_label(post)
        record = {
            "task": task_id,
            "comment": comment_id,
            "decision": decision,
            "label": label,
            "like": int(post.get("like_count") or 0),
            "dislike": int(post.get("dislike_count") or 0),
        }
        if self.config.dry_run:
            record["dry_run"] = True
            log.info("[chạy khô] %s %s trên %s (%s)", decision, label, task_id, comment_id)
            return record

        # Quyết định cố ý **không** để lại ghi chú trên thẻ. Bot từng viết một
        # dòng "đã gỡ / đã giữ" cho mỗi ảnh, và trên thẻ nhiều ảnh thì đúng thứ
        # người duyệt phải cuộn qua lại là những dòng đó. Người duyệt vừa tự tay
        # bấm 👍/👎 nên đã biết mình quyết gì rồi; chỗ cần lưu vết là log của
        # app, không phải thẻ.
        if decision == DECISION_DELETE:
            try:
                self.client.delete_comment(task_id, comment_id)
            except AgentBotError as exc:
                log.warning("Không gỡ được %s khỏi %s: %s", label, task_id, exc)
                return None
            log.info(
                "Đã gỡ %s khỏi %s theo phiếu %s 👎 / %s 👍.",
                label,
                task_id,
                record["dislike"],
                record["like"],
            )
        else:
            log.info(
                "Giữ %s trên %s theo phiếu %s 👍 / %s 👎.",
                label,
                task_id,
                record["like"],
                record["dislike"],
            )

        self.state.record(comment_id, task_id, decision)
        return record

    @staticmethod
    def _post_label(post: Dict[str, Any]) -> str:
        for attachment in post.get("attachments") or []:
            if isinstance(attachment, dict):
                name = str(attachment.get("file_name") or "").strip()
                if name:
                    return f"ảnh {name}"
        text = plain_text(post.get("content"))
        return f"bình luận “{text[:40]}”" if text else "bình luận"

    # ── nói chuyện ─────────────────────────────────────────────────────

    def card_brief(self, node: Dict[str, Any], tree: Dict[str, Any] | None = None) -> CardBrief:
        """Gói mọi thứ bot biết về một thẻ thành thứ phần trả lời đọc được.

        Cố ý dựng từ cây đã đọc chứ không hỏi ERP thêm câu nào: một lượt quét
        có trần 60 request/phút, mà trả lời một câu hỏi thì không đáng tốn
        thêm request nào cả.  Phần đếm ảnh nằm ở :func:`count_decisions`, dùng
        chung với luật cột.
        """
        tree = tree or {}
        root = tree.get("root") or node
        root_id = str(root.get("name") or "").strip()
        task_id = str(node.get("name") or "").strip()
        meta = task_meta(node)
        kept, pending, dropped = count_decisions(node)
        listing_ready, missing = listing_readiness(node)
        paused_key = root_id or task_id
        # Cùng luật cột mà ``pipeline_pass`` chạy, hỏi lại ở đây để câu trả lời
        # và nước đi thật không bao giờ nói hai chuyện khác nhau.
        brief_is_listing = is_listing_card(inherited_meta_node(node, root))
        stage = card_stage(
            node,
            cards_missing_sku=cards_missing_sku(root),
            listed=self.state.listing_confirmed(task_id),
            is_listing=brief_is_listing,
        )
        move = pipeline.decide(stage)
        routing = resolve_routing(
            meta,
            known_accounts=self.book.account_ids,
            account_machines=self.book.account_machines,
        )
        in_book = self.book.knows(routing.account_id)
        found = self.book.lookup(routing.account_id)
        return CardBrief(
            task=task_id,
            title=str(node.get("subject") or "").strip(),
            status=str(node.get("status") or "").strip(),
            sku=meta.sku,
            product=meta.product,
            template=meta.get("template"),
            is_listing=brief_is_listing,
            children=int(node.get("child_total") or 0),
            images_kept=kept,
            images_pending=pending,
            images_dropped=dropped,
            listing_ready=listing_ready,
            listing_missing=missing,
            listed=self.state.already_listed(task_id),
            paused=self.state.is_paused(paused_key),
            autorun=self.config.autorun,
            poll_seconds=self.config.poll_seconds,
            last_run=self.state.runs.get(paused_key, ""),
            root_task=root_id,
            account=routing.account_id,
            shop=found.shop if found else "",
            machine=routing.machine_id,
            account_source=routing.account_source,
            account_in_book=in_book,
            # Cả quyển sổ, không chỉ dòng của thẻ này: lệnh "acc: acc99"
            # cần biết acc99 có trong sổ hay không *trước khi* ghi, mà lúc
            # dựng câu trả lời thì phần soạn lời không cầm quyển sổ.
            known_accounts=self.book.account_ids,
            next_column=move.column,
            waiting=move.reason,
        )

    def _apply_chat_action(
        self,
        action: str,
        brief: CardBrief,
        edits: Sequence[Tuple[str, str]] = (),
    ) -> ChatActionOutcome:
        """Lệnh trong câu nói → sổ ghi. Chỉ đúng chỗ này được đụng vào sổ.

        Ba lệnh chạy/dừng/tiếp chỉ sửa sổ trong máy nên không hỏng được và
        không có gì để kể thêm.  Hai lệnh còn lại — sửa thẻ và đánh số — đi ra
        ERP, và ERP có quyền từ chối; chúng trả về một câu nối vào cuối câu
        trả lời.  Câu ấy phải kể đúng chuyện đã xảy ra: hứa "tôi ghi rồi"
        trong khi thẻ không đổi gì là thứ tệ hơn cả im lặng.
        """
        target = brief.root_task or brief.task
        if action == ACTION_RUN:
            self.state.clear_cooldown(target)
        elif action == ACTION_PAUSE:
            self.state.pause(target)
        elif action == ACTION_RESUME:
            self.state.resume(target)
            self.state.clear_cooldown(target)
        elif action == ACTION_SET:
            # Ghi lên **chính thẻ có câu nói ấy**, không phải thẻ gốc: người ta
            # gõ "acc: acc32" khi đang mở thẻ nào thì sửa thẻ đó.
            return self._write_edits(brief.task, edits)
        elif action in (ACTION_SKU_FILL, ACTION_SKU_RENUMBER):
            # Ngược lại với lệnh sửa: đánh số luôn chạy từ thẻ **gốc**, vì
            # ``product:`` khai trên idea cha và một lượt từ gốc phủ luôn
            # những thẻ anh em cũng vừa được kéo sang.  ``target`` là gốc của
            # cây bot đã đọc; nếu cây ấy hoá ra chỉ là một nhánh (thẻ gốc
            # thật nằm ngoài) thì ``plan_erp_skus`` bên app tự leo nốt lên
            # gốc trước khi tính.
            return self._fill_skus(target, renumber=action == ACTION_SKU_RENUMBER)
        return ChatActionOutcome()

    def _write_edits(
        self, task_id: str, edits: Sequence[Tuple[str, str]]
    ) -> ChatActionOutcome:
        """Ghi mấy ô vừa nghe được xuống thẻ, qua hook của app.

        Bot cố ý **không** tự gọi ``updateTaskMeta``: cùng lý do với luật cột,
        đường ghi của app đi qua ``service.py`` nơi có hàng rào kiểm thẻ thuộc
        dự án được phép.  Một câu chat không được mở thêm đường vòng qua đó.
        """
        if not edits:
            return ChatActionOutcome()
        if self.edit_hook is None:
            return ChatActionOutcome(
                "Nhưng máy này chưa nối đường ghi thuộc tính, nên thẻ vẫn nguyên như cũ.",
                failed=True,
            )
        try:
            self.edit_hook(task_id, tuple(edits))
        except Exception as exc:  # hook là mã của app; lỗi của nó không giết lượt quét
            log.warning("Không ghi được thuộc tính lên %s: %s", task_id, exc)
            return ChatActionOutcome(
                f"Nhưng ERP không nhận: {exc} — thẻ vẫn nguyên như cũ.", failed=True
            )
        log.info("Thẻ %s sửa theo lời người dùng: %s.", task_id, ", ".join(name for name, _ in edits))
        return ChatActionOutcome()

    @staticmethod
    def _worth_guessing(said: str, reply: Reply) -> bool:
        """Câu này có đáng một lượt hỏi Claude không.

        Hai trường hợp, và chỉ hai:

        * bảng từ khoá không hiểu gì cả — kể cả khi nó chịu thua thành bản
          hướng dẫn (``help``), vì chỉ một chữ "giúp" lạc trong câu là đủ kéo
          nó về đó;
        * bảng từ khoá *hiểu nhầm*: người ta rõ ràng đang sai bot sửa
          ("đổi mẫu listing sang mockup-02"), mà câu trả lời dựng ra lại chẳng
          làm gì — chữ "listing" kéo nó về thành câu hỏi tình trạng.

        Câu hỏi thật ("sku của thẻ này là gì") không rơi vào đâu cả: nó không
        có động từ sai việc, nên vừa không tốn tiền, vừa không có cửa cho một
        lượt đoán ý ghi đè lên câu trả lời đang đúng.
        """
        if reply.intent in (INTENT_UNKNOWN, INTENT_HELP):
            return True
        return reply.action == ACTION_NONE and sounds_like_an_order(said)

    def _out_of_brain_budget(self) -> bool:
        """Đã chạm trần giờ hoặc trần ngày chưa.

        Đọc sổ trên đĩa, nên câu trả lời không bị một lần khởi động lại xoá đi.
        Chạm trần thì ghi **một** dòng cho mỗi cửa sổ (A9.3) và trả về ``True``
        để câu lạ rơi về bản hướng dẫn, y như khi chưa nối CLI.
        """
        now = datetime.now(timezone.utc)
        windows = (
            ("một giờ", self.brain_max_calls_per_hour, timedelta(hours=1), now.strftime("gio-%Y%m%dT%H")),
            ("một ngày", self.brain_max_calls_per_day, timedelta(days=1), now.strftime("ngay-%Y%m%d")),
        )
        for label, ceiling, window, key in windows:
            used = self.state.brain_calls_within(window, now=now)
            if used < ceiling:
                continue
            if key not in self._brain_budget_said:
                self._brain_budget_said.add(key)
                log.info(
                    "Đã hỏi Claude %s lượt trong %s (trần %s) nên tới khi qua cửa sổ này "
                    "câu lạ để nguyên.",
                    used,
                    label,
                    ceiling,
                )
            return True
        return False

    def _guess_harder(self, said: str, brief: CardBrief) -> Reply | None:
        """Câu không khớp từ khoá nào → nhờ Claude đọc hộ.

        ``None`` nghĩa là *giữ nguyên câu trả lời cũ*: chưa nối, quá trần,
        Claude đọc xong mà không rút ra ô nào. Cả ba đều rơi về bản hướng dẫn
        như trước — thêm phần này không lấy đi câu trả lời nào đang có.

        Nuốt mọi lỗi ở đây thay vì để nó nổi lên: một lượt quét lo cả bảng, và
        không đáng để cả bảng đứng hình vì một câu khó hiểu.
        """
        if self.brain_hook is None:
            return None
        if self._brain_calls >= self.brain_max_calls:
            log.info(
                "Đã hỏi Claude %s lượt trong vòng quét này (trần %s) nên câu sau để nguyên.",
                self._brain_calls,
                self.brain_max_calls,
            )
            return None
        if self._out_of_brain_budget():
            return None
        self._brain_calls += 1
        # Ghi ngay chứ không đợi câu trả lời: một lượt CLI treo tới hết giờ vẫn
        # là một lượt đã tốn tiền và đã chiếm 45s của vòng quét.
        self.state.record_brain_call()
        self.state.save()
        try:
            verdict = self.brain_hook(said, brief)
        except Exception as exc:
            log.warning("Phần đoán ý hỏng trên %s: %s", brief.task, exc)
            return None
        if verdict is None:
            return None
        if not verdict.edits:
            # Claude *đã* đọc và cố ý không sửa gì. Ghi lại lý do rồi trả câu
            # hướng dẫn như cũ: đọc log là biết bot bỏ qua vì hiểu, hay vì hỏng.
            log.info(
                "Claude đọc câu trên %s nhưng không rút ra ô nào: %s",
                brief.task,
                verdict.refused or verdict.say or "không nói lý do",
            )
            return None
        reply = verdict_reply(verdict, brief)
        if reply is not None:
            log.info(
                "Claude hiểu câu trên %s thành %s.",
                brief.task,
                ", ".join(f"{name}={value!r}" for name, value in reply.edits),
            )
        return reply

    def _fill_skus(self, root_task_id: str, *, renumber: bool) -> ChatActionOutcome:
        """Đánh số cả cụm dưới một thẻ gốc, qua hook của app.

        Kể lại **con số thật** chứ không chỉ "xong rồi": một lượt ghi 0 thẻ và
        một lượt ghi 10 thẻ nghe giống hệt nhau nếu chỉ nói "xong", mà hai
        chuyện ấy khác nhau hoàn toàn — cái thứ nhất nghĩa là có gì đó đang
        chặn, và người hỏi cần biết ngay chứ không phải mở bảng ra dò.
        """
        if self.sku_hook is None:
            return ChatActionOutcome(
                "Nhưng máy này chưa nối đường đánh số, nên mã trên thẻ vẫn nguyên như cũ.",
                failed=True,
            )
        try:
            result = self.sku_hook(root_task_id, renumber)
        except Exception as exc:  # hook là mã của app; lỗi của nó không giết lượt quét
            log.warning("Không đánh số được cụm %s: %s", root_task_id, exc)
            return ChatActionOutcome(
                f"Nhưng ERP không nhận: {exc} — mã trên thẻ vẫn nguyên như cũ.", failed=True
            )
        return ChatActionOutcome(_sku_outcome_line(result if isinstance(result, dict) else {}))

    def chat_pass(
        self,
        tree: Dict[str, Any],
        bot_user: str,
        reset_budget: bool = True,
    ) -> List[Dict[str, Any]]:
        """Trả lời những câu người thật nói với bot trong cây task này.

        Chạy **sau** ``janitor_pass`` và **trước** ``autorun_pass`` của cùng
        lượt: sau, để câu "còn mấy ảnh chờ" kể đúng phiếu vừa áp xong; trước,
        để lệnh "chạy đi" kịp có tác dụng ngay trong lượt này chứ không phải
        đợi thêm một chu kỳ nữa.

        Câu trả lời đăng vào đúng thread của câu hỏi (``parent``), nên thẻ
        không dài thêm một cột bình luận rời rạc.

        ``reset_budget`` là chỗ trần hỏi model được tính. Gọi lẻ một cây thì
        cây ấy *là* cả lượt, nên mặc định đếm lại từ đầu. Còn ``run_once`` lo
        cả bảng: nó đặt lại đúng một lần rồi truyền ``False`` xuống, vì trần
        này để chặn **một bảng** đang tán gẫu biến thành hoá đơn — đếm lại ở
        mỗi cây thì một bảng ba mươi thẻ vẫn tiêu ba mươi lần trần.
        """
        if not self.config.chat:
            return []
        if reset_budget:
            self._brain_calls = 0
            self._author_lock_warned = False
        allowed = self.config.allowed_authors
        answered: List[Dict[str, Any]] = []
        deferred = 0
        ceiling = max(1, self.config.max_chat_replies_per_scan)
        for node in iter_tree_nodes(tree.get("root") or {}):
            task_id = str(node.get("name") or "").strip()
            if not task_id:
                continue
            for comment in node.get("comments") or []:
                if not isinstance(comment, dict):
                    continue
                thread_id = str(comment.get("name") or "").strip()
                # Chỉ bình luận *trong* thread của bot mới được coi là đang nói
                # với bot mà không cần gọi tên; bình luận cấp thẻ thì phải gọi.
                bot_thread = int(comment.get("mine") or 0) == 1
                asked = [(comment, False)]
                asked += [
                    (reply, True)
                    for reply in comment.get("replies") or []
                    if isinstance(reply, dict)
                ]
                for item, is_reply in asked:
                    comment_id = str(item.get("name") or "").strip()
                    if not comment_id or self.state.already_handled(comment_id):
                        continue
                    named = addressed_to_bot(item, bot_user, allowed_authors=allowed)
                    in_thread = bot_thread and is_reply and addressed_to_bot(
                        item, bot_user, in_bot_thread=True, allowed_authors=allowed
                    )
                    if not named and not in_thread:
                        self._note_refused_author(task_id, item, bot_user, bot_thread and is_reply)
                        continue
                    if not allowed and not self._author_lock_warned:
                        # C3.2: không khoá thì vẫn chạy, nhưng không được im.
                        self._author_lock_warned = True
                        log.warning(
                            "Agent bot đang chạy **không khoá tác giả**: ai bình luận được "
                            "lên thẻ là ra lệnh được cho bot (chạy lại automation, ghi thuộc "
                            "tính, đánh số lại SKU). Điền FLOW_AGENT_BOT_ALLOWED_AUTHORS để khoá."
                        )
                    if len(answered) >= ceiling:
                        deferred += 1
                        continue
                    outcome = self._reply_to(
                        task_id, thread_id or comment_id, item, tree, node, named=named
                    )
                    if outcome is not None:
                        answered.append(outcome)
        if deferred:
            # Trần bị chạm mà im lặng thì người hỏi tưởng bot lờ mình.
            log.info(
                "Agent bot còn %s câu hỏi chưa trả lời trong lượt này (trần %s câu).",
                deferred,
                ceiling,
            )
        return answered

    def _note_refused_author(
        self, task_id: str, comment: Mapping[str, Any], bot_user: str, in_bot_thread: bool
    ) -> None:
        """Ghi log đúng một dòng cho một bình luận bị hàng rào tác giả chặn.

        Chỉ ghi khi câu ấy **thật sự đang nói với bot** — bằng cách hỏi lại
        không kèm danh sách.  Không có bước đó thì mọi bình luận trên bảng đều
        thành một dòng log, và dòng cần đọc chìm mất.

        Không trả lời gì (C3.3): một câu từ chối là một cách xác nhận cho người
        lạ rằng bot có ở đây và đang nghe.
        """
        if not self.config.allowed_authors:
            return
        comment_id = str(comment.get("name") or "").strip()
        if comment_id and comment_id in self._author_refused_said:
            return
        spoken_to_bot = addressed_to_bot(comment, bot_user) or (
            in_bot_thread and addressed_to_bot(comment, bot_user, in_bot_thread=True)
        )
        if not spoken_to_bot:
            return
        if comment_id:
            self._author_refused_said.add(comment_id)
        log.warning(
            "Bỏ qua lệnh trên %s: tác giả %s không có trong danh sách được phép ra lệnh.",
            task_id or "một thẻ",
            comment_author(comment) or "không đọc được",
        )

    def _reply_to(
        self,
        task_id: str,
        thread_id: str,
        comment: Dict[str, Any],
        tree: Dict[str, Any],
        node: Dict[str, Any],
        *,
        named: bool = True,
    ) -> Dict[str, Any] | None:
        """Soạn và đăng đúng một câu trả lời.

        Dựng lại ``card_brief`` cho từng câu chứ không dùng lại bản cũ: hai câu
        liền nhau hoàn toàn có thể là "dừng lại" rồi "chạy đi", và câu thứ hai
        phải nhìn thấy hậu quả của câu thứ nhất.

        ``named`` phân biệt hai kiểu được gọi. Gọi đích danh thì im lặng là
        thô lỗ, nên câu nào không hiểu vẫn phải trả lời kèm bản hướng dẫn. Còn
        một câu buột miệng trong thread của bot ("ok em", "đẹp đấy") thì không:
        dội một bản hướng dẫn vào đó mỗi lần chính là dạy người ta bỏ qua bot.
        """
        brief = self.card_brief(node, tree)
        said = plain_text(comment.get("content"))
        reply = answer(said, brief)
        if named and self._worth_guessing(said, reply):
            # Chỉ những câu gọi đích danh mới đáng một lượt hỏi có phí. Một
            # tiếng "ok em" buột miệng trong thread của bot thì im lặng vẫn
            # đúng hơn, và đúng *miễn phí*.
            reply = self._guess_harder(said, brief) or reply
        if not named and reply.intent == INTENT_UNKNOWN:
            return None
        record = as_record(comment, task_id, reply)
        if self.config.dry_run:
            record["dry_run"] = True
            record["reply"] = reply.text
            log.info("[chạy khô] trả lời %s trên %s: %s", record["intent"], task_id, reply.text)
            return record
        # Làm việc **trước** khi đăng, rồi mới soạn câu cuối: chỉ sau khi thử
        # ghi mới biết nên nói "tôi ghi rồi" hay "ERP không nhận".
        outcome = self._apply_chat_action(reply.action, brief, reply.edits)
        if outcome.failed:
            record["error"] = outcome.note
        text = f"{reply.text}\n{outcome.note}" if outcome.note else reply.text
        try:
            self.client.add_comment(
                task_id,
                text,
                parent=thread_id,
                meta=CHAT_NOTE_MARK,
            )
        except AgentBotError as exc:
            # Ghi sổ *sau* khi đăng được: đăng hỏng mà vẫn ghi là câu hỏi ấy
            # chìm luôn, người hỏi không bao giờ nhận được trả lời.
            log.warning("Không trả lời được bình luận %s trên %s: %s", comment.get("name"), task_id, exc)
            return None
        self.state.record(str(comment.get("name") or ""), task_id, f"chat:{reply.intent}")
        log.info(
            "Đã trả lời %s trên %s (%s).",
            record["asked_by"] or "người dùng",
            task_id,
            reply.intent,
        )
        return record

    # ── chạy việc ──────────────────────────────────────────────────────

    def column_pass(self) -> List[Dict[str, Any]]:
        """Nói ngay trên thẻ rằng cột của nó không nằm trong luật cột.

        Mỗi thẻ đúng một lần cho mỗi cột — sổ nhớ kèm tên cột, nên kéo thẻ
        sang một cột lạ *khác* thì được nhắc lại, còn để yên thì không.  Nhắc
        lại mỗi hai phút thì lời nhắc thành tiếng ồn, và tiếng ồn thì người ta
        tắt bot chứ không sửa bảng.

        Câu chữ lấy từ :func:`pipeline.column_help` chứ không viết lại ở đây:
        log và bình luận phải nói cùng một lời khuyên.
        """
        alerts, self._column_alerts = self._column_alerts, []
        if not self.config.column_alert:
            return []
        done: List[Dict[str, Any]] = []
        for task_id, column in alerts:
            if self.config.dry_run:
                # Không ghi sổ trong lượt chạy khô: ghi rồi thì lượt chạy thật
                # sau đó tưởng đã nhắc, và lời nhắc không bao giờ tới nơi.
                done.append({"task": task_id, "column": column, "dry_run": True})
                continue
            try:
                self.client.add_comment(
                    task_id, pipeline.column_help([column]), meta=COLUMN_NOTE_MARK
                )
            except AgentBotError as exc:
                log.warning("Không nhắc được về cột lạ trên %s: %s", task_id, exc)
                continue
            # Ghi sổ *sau* khi đăng được, như mọi đường đăng khác của bot:
            # đăng hỏng mà vẫn ghi là lời nhắc chìm luôn, không bao giờ quay lại.
            self.state.warn_column(task_id, column)
            done.append({"task": task_id, "column": column})
        return done

    def inherit_pass(self, tree: Dict[str, Any], bot_user: str) -> List[Dict[str, Any]]:
        """Thẻ cha đã gắn bot thì mọi thẻ con cũng được gắn theo.

        Chọn agent ở ô "Người phụ trách" của thẻ cha là người dùng đã nói xong ý
        mình: cả cụm việc này là của bot. Thẻ con thì không tự có — kể cả thẻ
        vừa do phần nhận ảnh sinh ra — nên bot tự khâu lại, để thẻ con hiện
        đúng người phụ trách như thẻ cha thay vì trống trơn.

        Chỉ lan xuống, không bao giờ lan lên: gắn bot vào một thẻ con là cố ý
        chỉ đúng thẻ ấy, và tự tiện gắn ngược lên thẻ cha sẽ kéo theo cả những
        thẻ con khác mà người dùng không hề chọn.
        """
        root = tree.get("root") or {}
        if not bot_user or not task_has_agent(root, bot_user):
            return []
        attached: List[Dict[str, Any]] = []
        for node in iter_tree_nodes(root):
            if node is root or task_has_agent(node, bot_user):
                continue
            task_id = str(node.get("name") or "").strip()
            if not task_id:
                continue
            if self.config.dry_run:
                attached.append({"task": task_id, "dry_run": True})
                continue
            try:
                self.client.add_task_agent(task_id, bot_user)
            except AgentBotError as exc:
                log.warning("Không gắn được bot vào thẻ con %s: %s", task_id, exc)
                continue
            agents = node.get("agents")
            if not isinstance(agents, list):
                agents = []
                node["agents"] = agents
            agents.append({"bot_user": bot_user})
            attached.append({"task": task_id})
            log.info("Gắn bot vào thẻ con %s theo thẻ cha %s.", task_id, root.get("name"))
        return attached

    def meta_inherit_pass(self, tree: Dict[str, Any], bot_user: str) -> List[Dict[str, Any]]:
        """Thẻ cha khai Thuộc tính một lần thì thẻ con được ghi theo.

        ERP không tự chép khối Thuộc tính xuống thẻ con, còn Review Lister và
        bảng ERP đọc đúng khối của thẻ con — nên thẻ cha khai đủ mà 48 thẻ con
        vẫn "thiếu" (TASK-2026-05384). Bot tự khâu lại, chỉ điền ô còn trống:
        ô thẻ con đã gõ là của thẻ con (``missing_from_parent``).

        Cùng hàng rào với vòng quét: cây phải là việc của bot (``_is_mine``).
        Scope ``card`` nghĩa là thẻ cha gắn đích danh bot; scope ``board`` thì
        thẻ Idea không gắn agent nào cũng đã là việc — bot autorun và dọn phiếu
        cho cây ấy rồi, nên thẻ con (kể cả thẻ tạo tay) cũng được điền.
        Thẻ cháu nhận theo thẻ ngay trên nó, không nhảy thẳng lên gốc — thẻ con
        khai riêng ``fulfillment: FBA`` thì cả nhánh dưới nó đi theo FBA.

        Mỗi lượt quét chép tối đa ``META_INHERIT_PER_SCAN`` thẻ, tính chung cả
        bảng. Ghi hỏng thì dừng hết lượt này và cụm ấy nghỉ
        ``META_INHERIT_BACKOFF_SECONDS`` giây.

        Cây bị cắt thì đi cây nhìn thấy trước, trần còn thì mới tới thẻ nằm
        ngoài cây (``_meta_inherit_hidden``).
        """
        root = tree.get("root") or {}
        if self.meta_inherit_hook is None or not bot_user or not self._is_mine(tree, bot_user):
            return []
        root_id = str(root.get("name") or "").strip()
        cooldown_key = f"meta:{root_id}"
        if not self.state.autorun_is_cool(cooldown_key, META_INHERIT_BACKOFF_SECONDS):
            return []
        done: List[Dict[str, Any]] = []
        # Thẻ đi kèm Thuộc tính *thực có* của thẻ ngay trên nó — gồm cả những ô
        # thẻ ấy vừa nhận, nên thẻ cháu không phải chờ thêm một lượt quét.
        above = {key: value for key, value in task_meta(root).attributes.items() if value}
        # Giá trị từng thẻ trong cây truyền xuống con nó; thẻ ngoài cây bị cắt
        # mà có cha nằm trong cây thì nhận đúng giá trị này.
        values_for: Dict[str, Dict[str, str]] = {}
        stack = [(child, above) for child in reversed(root.get("subtasks") or []) if isinstance(child, dict)]
        while stack:
            if self._meta_inherit_left <= 0:
                break
            node, parent_values = stack.pop()
            meta = task_meta(node)
            missing = missing_from_parent(meta.attributes, parent_values)
            own = {key: value for key, value in meta.attributes.items() if value}
            stack.extend(
                (child, {**own, **missing})
                for child in reversed(node.get("subtasks") or [])
                if isinstance(child, dict)
            )
            task_id = str(node.get("name") or "").strip()
            if task_id:
                values_for[task_id] = {**own, **missing}
            if not missing or not task_id:
                continue
            self._meta_inherit_left -= 1
            if self.config.dry_run:
                done.append({"task": task_id, "keys": sorted(missing), "dry_run": True})
                continue
            try:
                result = self.meta_inherit_hook(task_id, dict(missing))
            except Exception as exc:  # hook là mã của app; lỗi của nó không giết lượt quét
                log.warning(
                    "Không chép được Thuộc tính của %s xuống thẻ con %s: %s — nghỉ %s giây.",
                    root_id,
                    task_id,
                    exc,
                    META_INHERIT_BACKOFF_SECONDS,
                )
                self.state.mark_autorun(cooldown_key)
                self._meta_inherit_left = 0
                break
            written = (result or {}).get("written") if isinstance(result, dict) else None
            if not isinstance(written, dict):
                written = missing
            if not written:
                continue
            # Luật cột và nửa listing đọc thẻ con ngay trong lượt quét này;
            # đọc bản cũ thì thẻ vừa được điền vẫn trông như còn thiếu.
            node["meta"] = render_meta_block(written, meta.raw)
            done.append({"task": task_id, "keys": sorted(written)})
            log.info(
                "Chép Thuộc tính của %s xuống thẻ con %s: %s.", root_id, task_id, ", ".join(sorted(written))
            )
        if self._meta_inherit_left > 0 and tree_is_cut(tree):
            done.extend(self._meta_inherit_hidden(tree, above, values_for, cooldown_key))
        return done

    def _cut_tree_rows(self, tree: Dict[str, Any], why: str) -> List[Dict[str, Any]]:
        """Dòng ``taskBoard`` của dự án chứa cây bị cắt, hoặc ``[]``.

        Dùng chung cho mọi bước cần nhìn thẻ nằm ngoài cây: mỗi dự án đọc bảng
        tối đa một lần mỗi lượt quét.  Lượt quét thường đã đọc sẵn trong
        ``candidate_tasks`` nên không tốn thêm request.  Đọc hỏng thì ghi log
        và trả ``[]`` — không được làm đổ lượt quét.
        """
        root = tree.get("root") or {}
        root_id = str(root.get("name") or "").strip()
        board_row = tree.get(BOARD_ROW_KEY) or {}
        project = (
            self._scan_task_project.get(root_id)
            or str(root.get("project") or board_row.get("project") or "").strip()
        )
        if not root_id or not project:
            log.warning("Cây %s bị cắt nhưng không biết dự án nào để đọc bảng.", root_id)
            return []
        rows = self._scan_boards.get(project)
        if rows is None:
            try:
                rows = self.client.board_snapshot(project)[0]
            except Exception as exc:  # đọc bảng hỏng không được làm đổ lượt quét
                log.warning("Cây %s bị cắt, đọc bảng %s để %s hỏng: %s", root_id, project, why, exc)
                rows = []
            # Lưu cả khi hỏng: mỗi dự án đọc tối đa một lần mỗi lượt quét.
            self._scan_boards[project] = rows
        return rows

    def _sku_board_rows(self, trees: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Dòng ``taskBoard`` cho bảng SKU: chỉ dự án có cây bị cắt.

        Đi qua ``_cut_tree_rows``: lượt quét thường đã đọc sẵn bảng nên không
        tốn request nào; thiếu thì mỗi dự án đọc tối đa một lần.
        """
        rows: List[Dict[str, Any]] = []
        lists: set[int] = set()
        names: set[str] = set()
        for tree in trees:
            try:
                if not tree_is_cut(tree):
                    continue
                got = self._cut_tree_rows(tree, "vẽ bảng SKU")
            except Exception as exc:  # bảng mất dòng còn hơn lượt quét đổ
                log.warning("Không lấy được dòng bảng cho bảng SKU: %s", exc)
                continue
            # Nhiều cây cùng dự án trả cùng một danh sách.
            if id(got) in lists:
                continue
            lists.add(id(got))
            for row in got:
                name = str((row or {}).get("name") or "").strip()
                if name and name not in names:
                    names.add(name)
                    rows.append(row)
        return rows

    def _write_sku_status(self, trees: Sequence[Dict[str, Any]]) -> bool:
        """Ghi ``sku_status.json`` kèm dòng bảng và bảng mã trên đĩa. Chạy trong thread."""
        rows = self._sku_board_rows(trees)
        book = None
        if self.sku_book_loader is not None:
            try:
                book = self.sku_book_loader()
            except Exception as exc:
                log.warning("Không đọc được bảng mã cho bảng SKU: %s", exc)
        # Sổ bot giữ bên ERP đi kèm luôn: bảng không gọi ERP thêm lượt nào.
        # Gom sổ hỏng thì bỏ khối này, đừng bỏ cả lượt ghi số SKU.
        brain = None
        try:
            brain = sku_board.brain_from_disk(self.state)
        except Exception as exc:
            log.warning("Không gom được sổ bot cho bảng: %s", exc)
        return sku_board.write_status(trees, None, every=self.config.poll_seconds, rows=rows,
                                      book_rows=book, brain=brain)

    def _meta_inherit_hidden(
        self,
        tree: Dict[str, Any],
        above: Dict[str, str],
        values_for: Dict[str, Dict[str, str]],
        cooldown_key: str,
    ) -> List[Dict[str, Any]]:
        """Chép Thuộc tính cho thẻ con mà cây ``taskFull`` bị cắt giấu mất.

        ``taskFull`` cắt cây ở trần số nút, nên cụm đông con có thẻ không bao
        giờ vào vòng đi cây của ``meta_inherit_pass`` (cụm 04628: 37 thẻ
        Working trống cả 4 ô, Review Lister không đăng được).  Thẻ ấy chỉ còn
        thấy trên ``taskBoard``.

        Giá trị cha theo đúng luật "cháu nhận theo thẻ ngay trên nó":

        - thẻ cha trực tiếp (theo dòng bảng) là gốc: nhận ``above``;
        - thẻ cha nằm trong cây: nhận giá trị đã tính cho thẻ đó (``values_for``);
        - thẻ cha cũng bị giấu: **bỏ qua**, vì không biết thẻ cha ấy khai riêng
          gì.  Còn bị giấu thì lượt nào cũng bỏ qua.

        Dòng bảng không kèm khối Thuộc tính, nên bot không biết thẻ đã đủ
        chưa: gửi cả giá trị cha, hook tự đọc lại thẻ và chỉ điền ô trống.
        Mỗi lần gọi hook tính vào trần ``_meta_inherit_left``, kể cả khi nó trả
        rỗng.  Hỏi xong thì nhớ dấu vân tay giá trị cha (``_meta_inherit_asked``);
        giá trị cha chưa đổi thì lượt sau không hỏi lại.

        Thứ tự: cột đi xa hơn trước — Completed, Pending Review, Working rồi
        mới Open (Review Lister đọc các cột sau) — cùng cột theo số thẻ.
        """
        root = tree.get("root") or {}
        root_id = str(root.get("name") or "").strip()
        by_name = _rows_by_name(self._cut_tree_rows(tree, "chép Thuộc tính"))
        seen = {str(node.get("name") or "").strip() for node in iter_tree_nodes(root)}
        order = tuple(reversed(pipeline.ORDER))
        hidden: List[Tuple[Tuple[int, int, str], str, Dict[str, str]]] = []
        for name, row in by_name.items():
            if name in seen or root_id not in _ancestors(name, by_name):
                continue
            status = pipeline.normalize_status(row.get("status"))
            if status == pipeline.COL_CANCELLED or self.state.is_paused(name):
                continue
            parent = _row_parent(row)
            if parent == root_id:
                parent_values = above
            elif parent in values_for:
                parent_values = values_for[parent]
            else:
                continue
            values = missing_from_parent({}, parent_values)
            if not values:
                continue
            rank = order.index(status) if status in order else len(order)
            hidden.append(((rank, len(name), name), name, values))
        hidden.sort(key=lambda item: item[0])

        done: List[Dict[str, Any]] = []
        asked = 0
        for _, task_id, values in hidden:
            if self._meta_inherit_left <= 0:
                break
            print_ = tuple(sorted(values.items()))
            if self._meta_inherit_asked.get(task_id) == print_:
                continue
            self._meta_inherit_left -= 1
            asked += 1
            if self.config.dry_run:
                done.append({"task": task_id, "keys": sorted(values), "dry_run": True})
                continue
            try:
                result = self.meta_inherit_hook(task_id, dict(values))
            except Exception as exc:  # cùng lý do như vòng đi cây
                log.warning(
                    "Không chép được Thuộc tính của %s xuống thẻ con %s: %s — nghỉ %s giây.",
                    root_id,
                    task_id,
                    exc,
                    META_INHERIT_BACKOFF_SECONDS,
                )
                self.state.mark_autorun(cooldown_key)
                self._meta_inherit_left = 0
                break
            # Nhớ cả khi hook trả rỗng: thẻ đã đủ thì hỏi lại chỉ tốn request.
            self._meta_inherit_asked[task_id] = print_
            written = (result or {}).get("written") if isinstance(result, dict) else None
            if not isinstance(written, dict):
                written = values
            if not written:
                continue
            done.append({"task": task_id, "keys": sorted(written)})
            log.info(
                "Chép Thuộc tính của %s xuống thẻ con %s: %s.", root_id, task_id, ", ".join(sorted(written))
            )
        if hidden:
            # Cây bị cắt nào cũng có dòng này; chỉ lên INFO khi lượt này có hỏi,
            # để cụm đã đủ không lặp một dòng giống hệt sau mỗi lượt quét.
            log.log(
                logging.INFO if asked else logging.DEBUG,
                "Cây %s bị cắt: %s thẻ ngoài cây, lượt này hỏi %s thẻ, chép được %s thẻ.",
                root_id,
                len(hidden),
                asked,
                sum(1 for item in done if not item.get("dry_run")),
            )
        return done

    def _hidden_sku_card(self, tree: Dict[str, Any]) -> str:
        """Thẻ con *Đang làm* chưa có mã mà cây bị cắt giấu mất, hoặc ``""``.

        ``taskFull`` cắt cây ở trần số nút.  Cụm đông con thì phần nhận được
        có thể toàn thẻ *Cần làm*, còn thẻ vừa kéo sang *Đang làm* nằm ngoài —
        và bot không bao giờ đánh số cho nó.  Chỉ khi cây bị cắt mới đọc
        ``taskBoard``, mỗi dự án một lần mỗi lượt quét; lượt quét thường đã
        đọc sẵn trong ``candidate_tasks`` nên không tốn thêm request.

        Chỉ xét thẻ **ngoài** cây: dòng bảng không kèm bình luận, nên không
        biết thẻ còn ảnh chờ phiếu hay không.  Thẻ trong cây đã được luật cột
        xét đủ.  Hook đọc lại thẻ và hỏi lại luật trước khi đánh số.
        """
        if not tree_is_cut(tree):
            return ""
        root = tree.get("root") or {}
        root_id = str(root.get("name") or "").strip()
        rows = self._cut_tree_rows(tree, "tìm thẻ chờ mã")
        if not rows:
            return ""
        seen = {str(node.get("name") or "").strip() for node in iter_tree_nodes(root)}
        by_name = _rows_by_name(rows)
        for name, row in by_name.items():
            if name in seen or str(row.get("custom_sku") or "").strip():
                continue
            if pipeline.normalize_status(row.get("status")) != pipeline.COL_DOING:
                continue
            if root_id not in _ancestors(name, by_name) or self.state.is_paused(name):
                continue
            return name
        return ""

    async def pipeline_pass(self, tree: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Đẩy những thẻ đã xong việc của cột mình sang cột kế.

        Đây là đường đi của việc **người** làm: ai đó bấm 👍 lên bộ ảnh trên
        ERP, và không có lượt chạy nào của app đang mở để nhận ra điều đó.  Bot
        quét bảng thấy trước, nên bot là chỗ đúng để nhận ra.

        Luật được hỏi **tại chỗ**, từ cây đã đọc rồi: không tốn thêm request
        nào cho những thẻ chưa tới lúc đi, mà đó là gần như mọi thẻ trong mọi
        lượt quét.  Chỉ thẻ thật sự có nước đi mới gọi hook — và hook mới là
        thứ đọc lại thẻ, điền mã, rồi ghi trạng thái.

        Quét cả cây chứ không chỉ thẻ gốc: ảnh nằm trên thẻ con, nên phán quyết
        👍/👎 cũng nằm ở đó, và cột của thẻ con mới là chỗ người vận hành nhìn
        vào để biết một sản phẩm đang ở chặng nào.
        """
        moves: List[Dict[str, Any]] = []
        if self.pipeline_hook is None:
            return moves
        root = tree.get("root") or {}
        # Bao nhiêu thẻ trong cụm *đã tới lượt* (đã sang Đang làm) mà chưa
        # có mã — một con số cho cả cây, đếm một lần.  Không còn là điều kiện
        # chuyển cột: ``_leave_doing`` chỉ hỏi chính thẻ; nó chỉ nuôi
        # ``needs_sku_fill``, để lượt quét biết cụm còn việc đánh số cho máy
        # mà gọi hook, thay vì bỏ qua những thẻ anh em cũng vừa được kéo sang.
        missing = cards_missing_sku(root)
        # Lượt này đã gọi đánh số cho cụm qua một thẻ trong cây chưa.  Hook
        # đánh số cả cụm từ gốc, nên có rồi thì khỏi tìm thẻ bị cắt.
        numbered = False
        # Lượt này đã có một lần gọi hook cho thẻ chỉ chờ mã thành công chưa.
        # Hook đánh cả cụm từ gốc, nên lần đầu đã đánh xong; gọi tiếp cho thẻ
        # anh em chỉ đọc lại cây, mỗi lần ít nhất năm request mà không ghi gì.
        # Cụm vài chục thẻ thành vài trăm request một lượt và bị 429.
        # Chỉ nhớ trong lượt: lượt sau phải thử lại, lỡ lượt này ghi hỏng.
        cluster_filled = False
        fill_failures = 0
        for node in iter_tree_nodes(root):
            task_id = str(node.get("name") or "").strip()
            if not task_id:
                continue
            if self.state.is_paused(task_id) or self.state.is_paused(str(root.get("name") or "")):
                # "Dừng" phải thắng mọi suy đoán khác của bot, kể cả suy đoán
                # đúng luật — nếu không thì bảo bot dừng hoá ra vô nghĩa.
                continue
            stage = card_stage(
                node,
                cards_missing_sku=missing,
                listed=self.state.listing_confirmed(task_id),
                # Cùng một thẻ phải đọc ra cùng một thứ ở cả hai đường: thẻ con
                # trong cụm listing mượn ``action_1`` của cha ở đây y như lúc
                # được giao đi. Không thì bot giao con lên Etsy xong mà luật
                # cột vẫn coi nó là thẻ ảnh và giữ nó lại ở *Đang review*.
                is_listing=is_listing_card(
                    inherited_meta_node(node, root, known_accounts=self.book.account_ids)
                ),
            )
            move = pipeline.decide(stage)
            if pipeline.needs_sku_fill(stage):
                numbered = True
            if not move and not pipeline.needs_sku_fill(stage):
                # Không có nước đi, và cũng không đang chờ chính máy điền mã.
                # Bỏ qua, không tốn request nào — đây là gần như mọi thẻ trong
                # gần như mọi lượt quét.
                continue
            waiting_only = not move
            if waiting_only and (cluster_filled or fill_failures >= SKU_FILL_FAILURES_PER_TREE):
                # Cụm đã được đánh số lượt này, hoặc đã hỏng đủ trần.  Thẻ này
                # có mã rồi thì lượt sau mới rời cột, chậm một nhịp quét, đổi
                # lại khỏi bị 429.
                continue
            # Phanh nguội chỉ dựng cho **nước đi bị từ chối**. Thẻ *Đang làm*
            # đang chờ chính máy điền mã (``move`` rỗng) phải được gọi mỗi
            # lượt như cũ, nếu không thì việc đánh số bị giãn ra 15 phút một
            # bước.
            cooldown_key = f"pipeline:{task_id}"
            if move and not self.state.autorun_is_cool(cooldown_key, self.config.autorun_cooldown_seconds):
                moves.append({"task": task_id, "skipped": "vừa đề nghị, đang chờ nguội"})
                continue
            if self.config.dry_run:
                moves.append({"task": task_id, "to": move.status, "reason": move.reason, "dry_run": True})
                continue
            try:
                outcome = await self.pipeline_hook(task_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # hook là mã của app; lỗi của nó không giết vòng quét
                log.warning("Không đẩy được thẻ %s sang cột kế: %s", task_id, exc)
                moves.append({"task": task_id, "error": str(exc)})
                if waiting_only:
                    fill_failures += 1
                continue
            if waiting_only:
                # Hook của app không ném: hỏng thì nó trả ``reason`` mà không
                # có ``root_task_id``.  Chỉ đường chạy trót lọt mới có gốc cụm.
                # Tin mọi câu trả lời là thành công thì thẻ đầu hỏng vì lý do
                # riêng (403, ngoài dự án) sẽ chặn cả cây, lượt nào cũng vậy.
                # ``sku.failed`` khác rỗng vẫn là thành công: lượt sau thử lại.
                if isinstance(outcome, dict) and outcome.get("root_task_id"):
                    cluster_filled = True
                else:
                    fill_failures += 1
            if move and not (isinstance(outcome, dict) and outcome.get("moved")):
                # App từ chối nước đi này. Nguyên nhân thường không tự hết
                # trong một lượt — thẻ con trong cụm listing không khai
                # ``action_1`` nên cổng đóng của app không mở cho nó — nên hỏi
                # lại mỗi 120 giây chỉ đốt hạn mức request và rải log giả.
                self.state.mark_autorun(cooldown_key)
            moves.append({"task": task_id, "result": outcome})
        if numbered or self.state.is_paused(str(root.get("name") or "")):
            return moves
        # Cây bị cắt: thẻ chờ mã có thể nằm ngoài phần nhận được.
        hidden = await asyncio.to_thread(self._hidden_sku_card, tree)
        if not hidden:
            return moves
        if self.config.dry_run:
            moves.append({"task": hidden, "to": "", "reason": "cây bị cắt, thẻ chờ mã", "dry_run": True})
            return moves
        try:
            outcome = await self.pipeline_hook(hidden)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # cùng lý do như vòng trên
            log.warning("Không đánh số được cụm của thẻ bị cắt %s: %s", hidden, exc)
            moves.append({"task": hidden, "error": str(exc)})
            return moves
        moves.append({"task": hidden, "result": outcome})
        return moves

    async def autorun_pass(self, tree: Dict[str, Any]) -> Dict[str, Any] | None:
        """Giao thẻ cha đã gắn agent cho hook chạy việc.

        Bot cố ý **không** tự quyết thẻ con nào cần chạy: ``enqueue_erp_idea_jobs``
        đã bỏ qua thẻ con đã có ảnh rồi, nên nhân đôi phép lọc đó ở đây chỉ tạo
        thêm một chỗ để hai bên lệch nhau.

        Thẻ chưa có con vẫn được giao nếu nó đang mang từ hai ảnh trở lên: ảnh
        đầu là ảnh sản phẩm, những ảnh sau là idea vừa thả vào và hook sẽ biến
        chúng thành thẻ con. Một thẻ chỉ có mỗi ảnh bìa thì không có gì để làm.
        Bình luận chỉ đính tệp mà bot không thấy tệp (``has_hidden_files``) cũng
        được giao: bot không đếm được, còn hook thì đếm được.
        """
        if not self.config.autorun or self.autorun_hook is None:
            return None
        root = tree.get("root") or {}
        task_id = str(root.get("name") or "").strip()
        if not task_id:
            return None
        if self.state.is_paused(task_id):
            # Người dùng đã nói "dừng" ngay trên thẻ. Lệnh ấy phải thắng mọi
            # suy đoán khác của bot, nếu không thì nói với agent hoá ra vô nghĩa.
            #
            # Trả ``None`` chứ không trả một dòng "đã bỏ qua": dòng ấy sẽ chiếm
            # một suất của ``max_cards_per_scan`` và đẩy một thẻ đang chờ thật
            # sang lượt sau. Người ra lệnh dừng đã được bot trả lời ngay trên
            # thẻ rồi, nên chỗ cần lưu vết ở đây là log.
            log.info("Bỏ qua %s: đang tạm dừng theo yêu cầu trên thẻ.", task_id)
            return None
        images = count_card_images(root, tree.get(BOARD_ROW_KEY))
        has_cover = bool(str(root.get("cover_image") or "").strip())
        min_images = 2 if has_cover else 1
        if int(root.get("child_total") or 0) <= 0 and images < min_images and not has_hidden_files(root):
            return None
        if not self.state.autorun_is_cool(task_id, self.config.autorun_cooldown_seconds):
            return None
        if self.config.dry_run:
            return {"task": task_id, "dry_run": True}
        self.state.mark_autorun(task_id)
        try:
            outcome = await self.autorun_hook(task_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # hook là mã của app, lỗi của nó không được giết vòng lặp
            log.warning("Không chạy được việc của %s: %s", task_id, exc)
            return {"task": task_id, "error": str(exc)}
        return {"task": task_id, "result": outcome}

    async def _listing_confirm(self, task_id: str) -> Dict[str, Any] | None:
        """Thẻ đã giao rồi: hỏi bản Listing xem lượt ấy đã dựng xong bản nháp chưa.

        Chỉ hỏi khi còn treo. Xác nhận rồi thì im — thẻ đã sang *Hoàn thành*,
        hỏi lại mỗi lượt quét chỉ tốn request của trần 60/phút.

        Ba ngả, và không ngả nào được xoá dòng sổ: xoá đi là mất hàng rào chặn
        giao lần hai, kể cả trong ngả *hỏng*. Lượt hỏng thì bản nháp có thể đã
        dựng được một nửa trong shop, nên việc tiếp theo là người vào xem, chứ
        không phải máy tự giao lại.
        """
        if self.state.listing_confirmed(task_id):
            return None
        if self.listing_confirm_hook is None:
            return None
        handover = self.state.listing_handover(task_id)
        queue_task = str(handover.get("queue_task") or "")
        if not queue_task:
            return None
        try:
            outcome = await self.listing_confirm_hook(queue_task, str(handover.get("machine") or ""))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # bản Listing tắt không được làm chết vòng quét
            log.warning("Không hỏi được kết quả listing của %s: %s", task_id, exc)
            return {"task": task_id, "error": str(exc)}
        if not isinstance(outcome, dict):
            return None
        if outcome.get("done"):
            self.state.confirm_listing(task_id, outcome)
            return {"task": task_id, "listed": outcome}
        if outcome.get("failed"):
            return {"task": task_id, "failed": outcome.get("error") or outcome.get("status")}
        return {"task": task_id, "waiting": _listing_wait_text(outcome)}

    async def listing_pass(self, tree: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Giao những thẻ đã duyệt xong ảnh cho nửa Etsy đăng lên shop.

        Đi hết cây chứ không chỉ thẻ gốc. Ảnh nằm trên **thẻ con** — một thẻ
        con là một sản phẩm, và người duyệt bấm 👍 ở đó — nên nhìn mỗi thẻ gốc
        thì thẻ cha đời đời báo "chưa có ảnh nào để đăng" trong khi lũ con đã
        chốt ảnh từ lâu. Cả hai nửa đứng im, không một dòng lỗi.

        Gọi sau ``janitor_pass`` của chính lượt này, vì phán quyết 👍/👎 vừa
        áp xong mới cho biết bộ ảnh đã chốt hay chưa.

        Mọi ngả rẽ của một thẻ đều trả về một dòng chứ không im lặng: thẻ bị bỏ
        qua âm thầm trông y hệt thẻ hỏng, mà người dùng thì vừa gắn agent vào
        nó.

        Sổ nguội dùng khoá riêng ``listing:<thẻ>``: một thẻ listing vẫn đi qua
        ``autorun_pass`` để có ảnh, nên hai đường không được giẫm lên dấu thời
        gian của nhau.
        """
        root = tree.get("root") or {}
        lines: List[Dict[str, Any]] = []
        for node in iter_tree_nodes(root):
            card = inherited_meta_node(node, root, known_accounts=self.book.account_ids)
            if not is_listing_card(card):
                continue
            outcome = await self._listing_one(
                card,
                # Hàng rào SKU chỉ dựng cho thẻ **con**: mã là do
                # ``advance_erp_pipeline`` phát cho thẻ trong cụm Idea. Gốc
                # đứng một mình là thẻ người tự dựng, không đi qua bước ấy.
                child=node is not root,
                # Đọc mã từ khối **riêng** của con, không phải khối đã nối:
                # hàng rào không được phụ thuộc vào việc cha có mã hay không.
                own_sku=task_meta(node).sku,
            )
            if outcome is not None:
                lines.append(outcome)
        return lines

    async def _listing_one(
        self,
        node: Dict[str, Any],
        *,
        child: bool = False,
        own_sku: str = "",
    ) -> Dict[str, Any] | None:
        """Một thẻ trong cụm listing: giao đi, hoặc nói vì sao chưa giao được."""
        task_id = str(node.get("name") or "").strip()
        if not task_id:
            return None
        if self.state.already_listed(task_id):
            # Đăng lần hai là hai bản nháp trong shop cho cùng một sản phẩm.
            # Nhưng đã giao *không* phải đã đăng: lượt còn treo thì đi hỏi lại
            # bên kia, vì cái mở cổng sang *Hoàn thành* là câu trả lời ấy.
            #
            # Hỏi trước cả hàng rào thẻ cha bên dưới: thẻ đã có biên lai thì
            # phải được hỏi lại dù nó là thẻ gì, kể cả biên lai của bản cũ ghi
            # theo thẻ cha.
            return await self._listing_confirm(task_id)
        if has_children(node):
            # Thẻ cha là cái hộp, không phải sản phẩm: nó gom ảnh của cả cụm
            # nên trông như một thẻ khổng lồ chưa chốt, và ghi sổ cho nó thì
            # lần sau không thẻ con nào được giao nữa. Lũ con nói thay nó.
            return None
        if self.state.is_paused(task_id):
            return {"task": task_id, "skipped": "đang tạm dừng theo yêu cầu trên thẻ"}
        ready, missing = listing_readiness(node)
        if not ready:
            # ``needs_images`` là thứ phân biệt *chờ người bấm 👍* với *chờ máy
            # Etsy chạy xong*. Chỉ cái trước mới được rơi xuống nửa làm ảnh.
            return {"task": task_id, "waiting": missing, "needs_images": True}
        if child and not own_sku:
            # Trong cùng một lượt quét, ``pipeline_pass`` chạy **trước** và chỉ
            # kéo thẻ *Cần làm* → *Đang làm*; mã SKU thì lượt sau mới điền —
            # ``advance_erp_pipeline`` cố ý đi một bước mỗi lượt gọi. Giao ngay
            # lúc này là gửi ``etsy_listing_sku`` rỗng, bản Listing tự đặt mã
            # của nó, và từ đó không ai lần từ bài listing về lại thẻ đã sinh
            # ra nó nữa. Chờ đúng một lượt là đủ.
            #
            # Không đặt ``needs_images``: thứ đang thiếu là con số chứ không
            # phải tấm ảnh, nên đừng mở nửa làm ảnh vì dòng này.
            return {"task": task_id, "waiting": "chờ máy điền SKU"}
        if self.listing_hook is None:
            return {"task": task_id, "skipped": "chưa cấu hình ERP_LISTING_API_URL"}
        cooldown_key = f"listing:{task_id}"
        if not self.state.autorun_is_cool(cooldown_key, self.config.autorun_cooldown_seconds):
            return {"task": task_id, "skipped": "vừa giao xong, đang chờ nguội"}
        if self.config.dry_run:
            return {"task": task_id, "dry_run": True}
        self.state.mark_autorun(cooldown_key)
        try:
            outcome = await self.listing_hook(task_id, node)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # bản Listing tắt không được làm chết vòng quét
            log.warning("Không giao được thẻ listing %s: %s", task_id, exc)
            return {"task": task_id, "error": str(exc)}
        if isinstance(outcome, dict) and outcome.get("queue_task_id"):
            # Chỉ ghi sổ khi bên kia thật sự xếp hàng được. Một lượt bị từ chối
            # ("thẻ đã ở cột Done") phải còn đường quay lại nếu người dùng sửa.
            self.state.record_listing(task_id, outcome)
        return {"task": task_id, "result": outcome}

    # ── một lượt ───────────────────────────────────────────────────────

    def _is_mine(self, tree: Dict[str, Any], bot_user: str) -> bool:
        """Cây này có phải việc của bot không.

        Ở chế độ ``card`` thì phải gắn đích danh. Ở ``board`` thì thẻ đã lọt qua
        ``candidate_tasks`` rồi — hoặc vì gắn bot, hoặc vì là thẻ Idea của một
        dự án bot đang ở trong — nên kiểm lại lần nữa chỉ để loại đúng những thẻ
        gắn bot khác.
        """
        root = tree.get("root") or {}
        if self.config.scope == SCOPE_CARD:
            return task_has_agent(root, bot_user)
        agents = root.get("agents") or []
        return (
            task_has_agent(root, bot_user)
            if agents
            else is_idea_card(root, tree.get(BOARD_ROW_KEY))
        )

    async def run_once(self) -> Dict[str, Any]:
        """Quét một vòng, trừ khi đang có một lượt quét khác chạy.

        Lượt tới sau trả ngay, không chờ: người bấm "chạy ngay" giữa lúc bot
        đang quét muốn biết bot đang làm, không muốn treo nút tới hết lượt kia
        rồi quét lại đúng những thẻ vừa quét. Lượt nền gặp lượt tay thì bỏ lượt
        ấy, ngủ tới nhịp sau như thường — nhịp không đổi.
        """
        if not self._scan_lock.acquire(blocking=False):
            log.info("Agent bot bỏ lượt này: đang quét một lượt khác.")
            return {"enabled": True, "busy": True, "reason": "bot đang quét một lượt khác; lượt này bỏ qua"}
        try:
            return await self._scan_once()
        finally:
            self._scan_lock.release()

    async def _scan_once(self) -> Dict[str, Any]:
        """Quét một vòng. Không ném lỗi vì một dự án hỏng, chỉ bỏ qua nó."""
        if not self.config.enabled:
            return {"enabled": False, "reason": "chưa cấu hình ERP_AGENT_TOKEN"}

        projects = await asyncio.to_thread(self.scope_projects)
        if not projects:
            return {"enabled": True, "projects": [], "reason": "bot chưa được thêm vào dự án nào"}

        # Danh tính trước, để bước chọn thẻ biết thẻ nào gắn đích danh bot này
        # thay vì gắn một bot khác.
        bot_user = self.resolve_bot_user()
        candidates = await asyncio.to_thread(self.candidate_tasks, projects, bot_user)
        # Nhắc về cột lạ ngay đây, trước mọi bước đọc cây: một bảng đặt sai tên
        # cột thì thường **không** có thẻ nào lọt vào ``candidates`` cả, nên đặt
        # lời nhắc ở cuối vòng quét là đặt vào chỗ nó không bao giờ tới.
        columns = await asyncio.to_thread(self.column_pass)

        trees: List[Dict[str, Any]] = []
        for task in candidates:
            task_id = str(task.get("name") or "").strip()
            if not task_id:
                continue
            try:
                tree = await asyncio.to_thread(self.client.task_full, task_id, TASK_FULL_DEPTH)
            except AgentBotError as exc:
                log.warning("Không đọc được task %s: %s", task_id, exc)
                continue
            # Dòng của thẻ trên bảng biết số tệp treo thẳng trên thẻ; taskFull
            # thì không. Giữ nó lại để bước giao việc còn thấy ảnh vừa kéo vào.
            tree[BOARD_ROW_KEY] = task
            trees.append(tree)

        if not bot_user:
            bot_user = self.resolve_bot_user(trees)
        if not bot_user and candidates:
            bot_user = await asyncio.to_thread(
                self.probe_bot_user, str(candidates[0].get("name") or "")
            )
        if not bot_user:
            self.state.save()
            return {
                "enabled": True,
                "projects": projects,
                "tasks": [],
                "reason": "chưa xác định được danh tính bot; đặt ERP_AGENT_BOT_USER",
            }
        self.state.bot_user = bot_user

        mine = [tree for tree in trees if self._is_mine(tree, bot_user)]
        applied: List[Dict[str, Any]] = []
        queued: List[Dict[str, Any]] = []
        inherited: List[Dict[str, Any]] = []
        meta_inherited: List[Dict[str, Any]] = []
        listing: List[Dict[str, Any]] = []
        chats: List[Dict[str, Any]] = []
        moved: List[Dict[str, Any]] = []
        deferred: List[str] = []
        ceiling = max(1, self.config.max_cards_per_scan)
        # Trần hỏi model đặt lại đúng một lần ở đây, không phải ở mỗi cây: một
        # lượt quét là một hoá đơn, và hoá đơn ấy phải cộng cả bảng lại.
        self._brain_calls = 0
        # Suất chép Thuộc tính cũng vậy: trần của cả lượt, không phải của cây.
        self._meta_inherit_left = META_INHERIT_PER_SCAN
        for tree in mine:
            # Lan xuống trước: thẻ con phải mang đúng người phụ trách của thẻ
            # cha, kể cả khi lượt này không còn suất chạy việc nào.
            inherited.extend(await asyncio.to_thread(self.inherit_pass, tree, bot_user))
            # Rồi tới Thuộc tính, trước mọi bước đọc thẻ con bên dưới — luật
            # cột và nửa listing phải thấy thẻ con đã được điền.
            meta_inherited.extend(await asyncio.to_thread(self.meta_inherit_pass, tree, bot_user))
            root = tree.get("root") or {}
            # Dọn phiếu cho mọi thẻ: nó rẻ, và trần dưới đây là trần của việc
            # tạo ảnh chứ không phải của việc đọc 👍/👎.
            applied.extend(await asyncio.to_thread(self.janitor_pass, tree))
            # Trả lời trước khi chạy việc: câu "chạy đi" vừa gỡ phanh nguội thì
            # ngay dưới đây thẻ được nhận luôn, chứ không phải đợi lượt sau.
            chats.extend(await asyncio.to_thread(self.chat_pass, tree, bot_user, False))
            # Sau ``janitor_pass`` của chính lượt này: phán quyết 👍/👎 vừa áp
            # xong mới cho biết bộ ảnh đã chốt hay chưa, và đó chính là thứ
            # đẩy thẻ rời cột *Cần làm*.
            moved.extend(await self.pipeline_pass(tree))
            if is_listing_card(root):
                # Một agent, hai chặng của **cùng một thẻ**: làm ảnh ở đây, rồi
                # đăng bộ ảnh ấy lên Etsy. Chặng đăng chỉ chạy khi ảnh đã chốt,
                # nên thẻ mới gắn agent vẫn rơi xuống nửa làm ảnh bên dưới —
                # nếu nửa listing chiếm luôn thẻ thì sẽ không bao giờ có ảnh
                # nào để nó đăng.
                outcomes = await self.listing_pass(tree)
                listing.extend(outcomes)
                if not any(item.get("needs_images") for item in outcomes) and not has_children(root):
                    # Chỉ thẻ còn *thiếu ảnh* mới rơi xuống nửa làm ảnh. Thẻ đã
                    # giao đi mà máy Etsy còn đang chạy cũng là "chờ", nhưng
                    # chạy ảnh lại cho nó là đẻ thêm ảnh mới lên bộ ảnh đã chốt
                    # và đã gửi đi rồi.
                    #
                    # Hàng rào ấy chỉ đúng với **gốc đứng một mình** — thẻ mang
                    # ảnh trên chính nó. Cây có con thì ảnh idea mới được thả
                    # lên thẻ **cha**, và fan-out bỏ qua con đã có ảnh, nên
                    # chặn ở đây là khoá luôn đường tách idea mới: người phải
                    # bấm chạy tay trên dashboard cho tới hết đời cái cây.
                    continue
            if len(queued) >= ceiling:
                deferred.append(str(root.get("name") or ""))
                continue
            outcome = await self.autorun_pass(tree)
            if outcome is not None:
                queued.append(outcome)
        if deferred:
            # Nói ra chỗ bị cắt: im lặng dừng lại trông y hệt "board này không
            # còn thẻ nào để chạy".
            log.info(
                "Agent bot chạy %s thẻ trong lượt này; để lượt sau: %s.",
                len(queued),
                ", ".join(deferred),
            )

        self.state.save()
        # Phần "SKU & Thuộc tính" của bảng điều khiển đọc tệp này qua bản
        # Listing. Ghi hỏng thì write_status tự ghi log rồi thôi: bảng mất một
        # lượt số, bot vẫn quét. Thẻ ngoài cây bị cắt lấy mã từ dòng bảng đã
        # đọc trong lượt này.
        await asyncio.to_thread(self._write_sku_status, mine)
        summary = {
            "enabled": True,
            "bot_user": bot_user,
            "scope": self.config.scope,
            "projects": projects,
            "tasks": [str((tree.get("root") or {}).get("name") or "") for tree in mine],
            "applied": applied,
            "kept": sum(1 for item in applied if item["decision"] == DECISION_KEEP),
            "deleted": sum(1 for item in applied if item["decision"] == DECISION_DELETE),
            "autorun": queued,
            "chats": chats,
            "inherited": inherited,
            "meta_inherited": meta_inherited,
            "listing": listing,
            "moved": moved,
            "columns": columns,
            "dry_run": self.config.dry_run,
        }
        if listing:
            # Nói ra từng thẻ listing và nó đang đứng ở chặng nào: im lặng bỏ
            # qua trông y hệt thẻ hỏng.
            log.info(
                "Agent bot: %s thẻ listing — %s.",
                len(listing),
                "; ".join(
                    "{} {}".format(
                        item.get("task") or "",
                        item.get("waiting")
                        or item.get("skipped")
                        or item.get("error")
                        or (
                            "listing HỎNG bên máy Etsy: {}".format(item["failed"])
                            if item.get("failed")
                            else "bản nháp đã vào shop"
                            if item.get("listed")
                            else "đã giao"
                            if item.get("result")
                            else "chạy khô"
                        ),
                    )
                    for item in listing
                ),
            )
        if moved:
            # Nói ra từng nước đi: một thẻ tự nhiên đổi cột mà không ai biết vì
            # sao là thứ khiến người vận hành mất tin vào cái bảng.
            log.info(
                "Agent bot đẩy %s thẻ sang cột kế — %s.",
                len(moved),
                "; ".join(
                    "{} {}".format(
                        item.get("task") or "",
                        (item.get("result") or {}).get("next_column")
                        or (item.get("result") or {}).get("reason")
                        or item.get("error")
                        or item.get("to")
                        or "",
                    )
                    for item in moved
                ),
            )
        if applied or queued or inherited or meta_inherited or chats or moved:
            log.info(
                "Agent bot: %s thẻ, giữ %s, gỡ %s, chạy %s, gắn thêm %s thẻ con, "
                "chép Thuộc tính xuống %s thẻ con, trả lời %s câu, chuyển cột %s thẻ.",
                len(mine),
                summary["kept"],
                summary["deleted"],
                len(queued),
                len(inherited),
                len(meta_inherited),
                len(chats),
                len(moved),
            )
        return summary

    async def run_forever(self, immediate: bool = False) -> None:
        """Vòng lặp nền. ``poll_seconds = 0`` là tắt hẳn.

        Mặc định ngủ trước rồi mới quét: khi chạy trong app, lượt đầu không nên
        tranh tài nguyên với lúc khởi động. Chạy tay bằng script thì ``immediate``
        cho kết quả ngay thay vì im lặng cả chu kỳ đầu.
        """
        interval = self.config.poll_seconds
        # Tắt cũng phải nói ra tên biến cần đặt. Máy trung tâm chạy nền không ai
        # ngồi trước màn hình: bot tắt và bot chết đều là log trống, và người
        # vận hành không có cách nào phân biệt hai thứ ấy.
        if not self.config.enabled:
            log.info("Agent bot tắt: chưa đặt ERP_AGENT_TOKEN.")
            return
        if interval <= 0:
            log.info("Agent bot tắt: ERP_AGENT_POLL_SECONDS = %s (đặt số giây > 0 để bật).", interval)
            return
        # Máy trung tâm chạy 24/7 không ai ngồi trước màn hình, nên phải có một
        # dòng nói rõ bot đã bật và đang đứng ở đâu. Các dòng còn lại chỉ hiện
        # khi bot thật sự làm gì; im lặng khi không có việc là đúng, nhưng im
        # lặng ngay từ lúc khởi động thì không phân biệt được với chết hẳn.
        log.info(
            "Agent bot bật: quét mỗi %ss, phạm vi %s%s, tự chạy %s%s.",
            interval,
            self.config.scope,
            # Cột nguồn là thứ dễ làm bot trông như chết nhất: gõ sai một chữ
            # là không thẻ nào lọt. Nói ngay ở dòng khởi động thì người đọc log
            # đối chiếu được với board mà không phải mở file cấu hình ra.
            f" (cột nguồn: {', '.join(self.config.source_statuses)})"
            if self.config.source_statuses
            else "",
            "bật" if self.config.autorun else "tắt",
            " (chạy khô)" if self.config.dry_run else "",
        )
        first = True
        while True:
            if not (first and immediate):
                await asyncio.sleep(interval)
            first = False
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except AgentBotError as exc:
                log.warning("Agent bot bỏ lượt này: %s", exc)
            except Exception as exc:
                log.exception("Agent bot gặp lỗi ngoài dự tính: %s", exc)


def shared_limiter_from_env() -> SharedRateLimiter:
    """Tạo bộ điều tiết nhịp dùng chung giữa các tiến trình từ biến môi trường."""
    raw_path = os.getenv("ERP_AGENT_RATE_FILE", "").strip()
    rate_path = Path(raw_path).resolve() if raw_path else (DATA_DIR / "erp-agent-nhip.json").resolve()
    raw_limit = os.getenv("ERP_AGENT_RATE_PER_MINUTE", "").strip()
    if not raw_limit:
        limit = RATE_LIMIT_PER_MINUTE
    else:
        try:
            parsed = int(raw_limit)
            if 1 <= parsed <= 500:
                limit = parsed
            else:
                limit = RATE_LIMIT_PER_MINUTE
                log.warning(
                    "ERP_AGENT_RATE_PER_MINUTE=%r không hợp lệ (cần 1..500), dùng %d/phút thay thế.",
                    raw_limit,
                    limit,
                )
        except ValueError:
            limit = RATE_LIMIT_PER_MINUTE
            log.warning(
                "ERP_AGENT_RATE_PER_MINUTE=%r không phải số nguyên, dùng %d/phút thay thế.",
                raw_limit,
                limit,
            )
    limiter = SharedRateLimiter(rate_path, limit=limit)
    log.info("Nhịp token bot chung: %s, %d/phút", str(rate_path), limit)
    return limiter


def build_agent_bot(
    config: AgentBotConfig | None = None,
    autorun_hook: AutorunHook | None = None,
    state_path: Path | None = None,
    listing_hook: ListingHook | None = None,
    listing_confirm_hook: ListingConfirmHook | None = None,
    pipeline_hook: PipelineHook | None = None,
    book: AccountBook | None = None,
    edit_hook: EditHook | None = None,
    sku_hook: SkuHook | None = None,
    brain_hook: BrainHook | None = None,
    brain_max_calls: int = 5,
    brain_max_calls_per_hour: int = 30,
    brain_max_calls_per_day: int = 150,
    meta_inherit_hook: MetaInheritHook | None = None,
    sku_book: Callable[[], Any] | None = None,
) -> AgentBot | None:
    """Dựng bot, hoặc ``None`` khi chưa cấu hình token."""
    resolved = config or AgentBotConfig.from_env()
    if not resolved.enabled:
        # Nói ra ngay tại đây, đừng để dành cho ``run_forever``: đường của app
        # là ``watch_agent_bot`` → ``agent_bot()`` → hàm này → ``None`` →
        # ``return``. ``run_forever`` không bao giờ được gọi, nên hai dòng log
        # của nó không hiện trên máy trung tâm. Thiếu token mà im lặng trông y
        # hệt bot chết hẳn.
        log.info("Agent bot tắt: chưa đặt ERP_AGENT_TOKEN.")
        return None
    client = AgentBotClient(resolved, limiter=shared_limiter_from_env())
    return AgentBot(
        resolved,
        client=client,
        state=AgentBotState.load(state_path),
        autorun_hook=autorun_hook,
        listing_hook=listing_hook,
        listing_confirm_hook=listing_confirm_hook,
        pipeline_hook=pipeline_hook,
        book=book,
        edit_hook=edit_hook,
        sku_hook=sku_hook,
        brain_hook=brain_hook,
        brain_max_calls=brain_max_calls,
        brain_max_calls_per_hour=brain_max_calls_per_hour,
        brain_max_calls_per_day=brain_max_calls_per_day,
        meta_inherit_hook=meta_inherit_hook,
        # Bot thật đọc bảng mã trên đĩa cho bảng SKU; bot dựng trong test thì không.
        sku_book=sku_book if sku_book is not None else sku_board.load_disk_book,
    )


def build_sku_fast_lane(
    bot: AgentBot,
    fill: Callable[[str], Dict[str, Any]],
    config: SkuFastLaneConfig | None = None,
) -> SkuFastLane | None:
    """Làn nhanh đánh số, nối vào đúng client, sổ tạm dừng và bot_user của bot.

    ``None`` khi chưa bật, hoặc khi bot đang chạy thử: bot không ghi gì thì làn
    bên cạnh cũng không được ghi.  ``fill`` là lượt đánh số của app — làn này
    không tự tính mã.
    """
    resolved = config or SkuFastLaneConfig.from_env()
    if not resolved.enabled or bot.config.dry_run:
        return None
    return SkuFastLane(
        resolved,
        # ``scope_projects`` đã đọc ``taskProjects`` và giữ lại trạng thái.
        # Đừng gọi lại ở từng nhịp chỉ để lọc bảng Completed.
        projects=lambda: list(bot.state.fast_lane_projects),
        board=lambda project: bot.client.board_snapshot(project)[0],
        bot_user=lambda: bot.state.bot_user or bot.config.bot_user,
        fill=fill,
        tree=bot.client.task_full,
        is_due=sku_fill_is_due,
        paused=bot.state.is_paused,
        token_limit=getattr(getattr(bot.client, "_limiter", None), "limit", None),
    )
