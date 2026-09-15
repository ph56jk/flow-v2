"""Giao thẻ listing sang bản Listing để đăng ảnh đã duyệt lên Etsy.

Một agent, hai loại việc. Thẻ nào viết ``action_1: listing`` trong khối
*Thuộc tính* là việc lên Etsy, và phần đuôi của việc đó — chép ảnh sang máy
Etsy rồi để extension dựng bản nháp trong shop — nằm ở bản Listing, không nằm
ở đây. Module này là chỗ duy nhất hai bên chạm nhau.

Vì sao là "đăng" chứ không phải "làm lại từ đầu": nửa làm ảnh đã tạo ảnh trên
đúng thẻ ERP đó và đã có người bấm 👍 duyệt. Bảo bản Listing chạy
``/api/jobs`` là bắt nó mở Google Flow tạo một bộ ảnh khác — tốn quota, và
người duyệt sẽ phải duyệt lại một bộ ảnh mà họ chưa từng thấy. Nên bridge gọi
``/api/etsy/browser-copy/enqueue``: đầu kia đọc chính thẻ ấy, tải ảnh đính kèm
đã duyệt, chép sang máy ảo và xếp hàng cho extension. Không có lượt tạo ảnh
thứ hai, và cũng không có tiến trình thứ hai tranh Chrome trên cùng cái máy.

Hệ quả về quyền: bản Listing chỉ *đọc* thẻ, ở đúng dự án mà thẻ đang nằm
(``ERP_LISTING_PROJECT``, mặc định trùng dự án của nửa làm ảnh). Nó không cần
thêm quyền ghi nào ngoài những gì nó vốn có.

``ERP_LISTING_API_URL`` để trống là tắt: bot vẫn nhận ra thẻ listing và vẫn
không đụng vào nó, chỉ là không giao đi đâu cả. Đó là trạng thái đúng cho một
máy chưa dựng bản Listing.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .account_book import AccountBook
from .erp_meta import resolve_routing, task_meta

log = logging.getLogger(__name__)


# Thẻ nằm ở dự án nào thì bản Listing phải đọc ở đúng dự án ấy. Mặc định trùng
# dự án của nửa làm ảnh vì đây là cùng một thẻ, chỉ khác nửa nào đang cầm.
DEFAULT_PROJECT = "PROJ-0013"
DEFAULT_TIMEOUT_S = 120

# Đường bản Listing dùng để chuẩn bị + xếp hàng một thẻ, không tạo ảnh mới.
ENQUEUE_PATH = "/api/etsy/browser-copy/enqueue"

# Đường hỏi lại: lượt vừa giao đã chạy xong trên máy Etsy chưa. Xếp được hàng
# và dựng xong bản nháp là hai chuyện khác nhau — máy ảo có thể đang ngủ, hoặc
# Chrome bên đó chết giữa chừng — nên luật cột không được đọc cái trước thành
# cái sau.
QUEUE_PATH = "/api/etsy/browser-copy/queue"

# Trạng thái bên kia đặt cho một lượt trong hàng đợi.
QUEUE_DONE = "completed"
QUEUE_OPEN = ("queued", "in_progress")

# Bản Listing bỏ qua thẻ vì chính nó, không phải vì hỏng. Giữ nguyên tên lý do
# của đầu kia để đọc log hai bên còn khớp nhau.
SKIP_REASONS = {
    "meta_action_not_listing": "thẻ khai action khác, không phải listing",
    "already_in_done": "thẻ đã ở cột Done",
    "card_name_equals_list_name": "tên thẻ trùng tên cột",
}


class ListingBridgeError(RuntimeError):
    """Không giao được thẻ sang bản Listing."""


@dataclass(frozen=True)
class ListingBridgeConfig:
    """Bản Listing nằm ở đâu và thẻ của nó đi về máy nào."""

    api_url: str = ""
    project_id: str = DEFAULT_PROJECT
    status_id: str = ""
    # Đội máy Etsy mà bản Listing này phục vụ. Dùng để đổi ``acc32`` trên thẻ
    # thành tên máy thật theo quy ước số.
    machines: Tuple[str, ...] = ()
    # Máy nhận khi thẻ không nói gì. Trong đợt thử một máy thì đây chính là
    # cái máy duy nhất được phép nhận việc.
    default_machine: str = ""
    timeout_s: int = DEFAULT_TIMEOUT_S

    @property
    def enabled(self) -> bool:
        return bool(self.api_url.strip())

    @classmethod
    def from_env(cls) -> "ListingBridgeConfig":
        raw_machines = os.getenv("ERP_LISTING_MACHINES", "")
        machines = tuple(
            item.strip()
            for item in raw_machines.replace(";", ",").split(",")
            if item.strip()
        )
        timeout = os.getenv("ERP_LISTING_TIMEOUT_SECONDS", "").strip()
        project = (
            os.getenv("ERP_LISTING_PROJECT", "").strip()
            or os.getenv("ERP_PROJECT_ID", "").strip()
            or DEFAULT_PROJECT
        )
        return cls(
            api_url=os.getenv("ERP_LISTING_API_URL", "").strip().rstrip("/"),
            project_id=project.upper(),
            status_id=os.getenv("ERP_LISTING_STATUS", "").strip(),
            machines=machines,
            default_machine=os.getenv("ERP_LISTING_MACHINE", "").strip(),
            timeout_s=int(timeout) if timeout.isdigit() and int(timeout) > 0 else DEFAULT_TIMEOUT_S,
        )


# Đổi request thành dict trả về. Tách ra để test không phải mở cổng nào.
Transport = Callable[[str, Dict[str, Any], int], Dict[str, Any]]
Fetch = Callable[[str, int], Dict[str, Any]]


def _post_json(url: str, payload: Dict[str, Any], timeout_s: int) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8", "replace")
    except HTTPError as exc:  # bản Listing từ chối: đọc phần thân để biết vì sao
        detail = exc.read().decode("utf-8", "replace")[:400] if exc.fp else ""
        raise ListingBridgeError(f"Bản Listing trả lỗi HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ListingBridgeError(f"Không gọi được bản Listing tại {url}: {exc.reason}") from exc
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise ListingBridgeError(f"Bản Listing trả về thứ không phải JSON: {raw[:200]}") from exc


def _get_json(url: str, timeout_s: int) -> Dict[str, Any]:
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400] if exc.fp else ""
        raise ListingBridgeError(f"Bản Listing trả lỗi HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ListingBridgeError(f"Không gọi được bản Listing tại {url}: {exc.reason}") from exc
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise ListingBridgeError(f"Bản Listing trả về thứ không phải JSON: {raw[:200]}") from exc


class ListingBridge:
    """Một thẻ ERP → một lượt xếp hàng đăng Etsy bên bản Listing."""

    def __init__(
        self,
        config: ListingBridgeConfig,
        transport: Transport | None = None,
        book: AccountBook | None = None,
        fetch: Fetch | None = None,
    ) -> None:
        self.config = config
        self._post = transport or _post_json
        self._get = fetch or _get_json
        # Sổ tay tài khoản. Người làm listing chỉ khai tài khoản — gõ ``acc:``
        # hoặc dán nhãn ``acc32`` — nên đây là chỗ duy nhất biến chừng ấy chữ
        # thành máy chạy và tên shop. Không có sổ thì cư xử y như trước: quy
        # ước số đuôi của đội máy.
        self.book = book if book is not None else AccountBook()

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def routing_for(self, root: Mapping[str, Any]):
        """Thẻ này thuộc tài khoản nào và chạy ở máy nào.

        Thứ tự rõ ràng nhất trước: ``machine:`` viết trên thẻ thắng tất cả;
        rồi tới máy quyển sổ ghi cho tài khoản ấy; cuối cùng mới là quy ước số
        của đội máy (``acc32`` → ``etsy-vn32``).

        Tài khoản thì đọc từ ``acc:`` trên thẻ, và nếu thẻ không gõ dòng ấy thì
        đọc từ **nhãn** — đó là cách người làm listing đang dùng: viết bài bằng
        tay rồi dán cái nhãn tài khoản lên thẻ. Quyển sổ cho phép cả những cái
        nhãn không theo quy ước ``acc`` + số, ví dụ một shop tên ``havi-home``.
        """
        return resolve_routing(
            task_meta(root),
            known_accounts=self.book.account_ids,
            known_machines=self.config.machines or tuple(self.book.account_machines.values()),
            account_machines=self.book.account_machines,
        )

    def machine_for(self, root: Mapping[str, Any]) -> str:
        """Máy Etsy nhận thẻ này, hoặc máy mặc định của cấu hình.

        Máy mặc định chỉ đỡ cho thẻ **không nói gì về tài khoản**. Thẻ đã khai
        ``acc:`` mà đội máy không tra ra thì để trống: nó nói rõ nó thuộc shop
        nào, và đẩy nó về máy mặc định là đăng bộ ảnh ấy lên đúng cái shop nó
        không thuộc về. Gặp thật trong lần chạy đầu: thẻ khai ``acc: acc16``,
        cấu hình chỉ biết ``etsy-vn32``, và payload rơi về vn32 không một
        tiếng động.
        """
        return self._machine_for(self.routing_for(root))

    def _machine_for(self, routing) -> str:
        if routing.machine_id:
            return routing.machine_id
        return "" if routing.account_id else self.config.default_machine

    def payload(self, task_id: str, root: Mapping[str, Any]) -> Dict[str, Any]:
        """Yêu cầu đăng đúng thẻ này, không kèm lượt tạo ảnh nào.

        Tên trường là tên lịch sử của bản Listing (``erp_*``, ``etsy_*``);
        đầu kia đọc chúng và chỉ đi qua HaviGroup ERP. Giữ nguyên tên nghĩa là
        không phải sửa gì bên đó cho đợt thử này.
        """
        meta = task_meta(root)
        routing = self.routing_for(root)
        machine = self._machine_for(routing)
        if not machine and routing.account_id:
            raise ListingBridgeError(
                f"Thẻ {task_id} khai tài khoản `{routing.account_id}` nhưng không tra ra máy "
                "nào chạy nó: sổ tay tài khoản chưa có dòng cho nó, và ERP_LISTING_MACHINES "
                "cũng không có máy mang số ấy. Không dùng ERP_LISTING_MACHINE thay vào đây — "
                "thẻ đã nói nó thuộc shop nào rồi."
            )
        if not machine:
            raise ListingBridgeError(
                f"Thẻ {task_id} chưa chỉ được máy Etsy nào: thẻ không ghi `machine:`/`acc:`, "
                "sổ tay tài khoản chưa có dòng cho nó, và cấu hình cũng chưa đặt "
                "ERP_LISTING_MACHINE."
            )
        subject = str(root.get("subject") or "").strip()
        return {
            # ``type`` là trường bắt buộc của lược đồ bên kia. Ở đường này nó
            # không kích hoạt lượt tạo ảnh nào — route enqueue đọc thẳng thẻ.
            "type": "image",
            "title": subject or f"Listing {task_id}",
            # Không có job thật ở đây; chuỗi này chỉ để đầu kia gắn nhãn.
            "source_job_id": f"erp-{task_id}",
            "erp_enabled": True,
            # Đầu kia để ``telegram_enabled`` **mặc định True**, nên không gửi
            # gì tức là đã đồng ý gửi. Ảnh đã được duyệt 👍 ngay trên thẻ ERP
            # rồi; bắt người ta duyệt lại lần nữa qua Telegram là hỏi một câu
            # đã có câu trả lời. Nói thẳng ra ở đây để ý định nằm trong payload,
            # chứ không nằm ở chỗ "may mà đường enqueue bên kia không đọc tới
            # trường này" — cái may ấy tan ngay khi bên kia sửa mã.
            #
            # Đợt gỡ Telegram (PRD C1) **không** chạm tới dòng này, và đây là
            # chỗ dễ nhầm nhất trong cả module: C1 gỡ Telegram khỏi *app này*
            # (``IntegrationConfigUpdateRequest``, ``CreateJobRequest``). Còn
            # ``telegram_enabled`` ở đây là trường của **lược đồ bên kia**, một
            # app khác chạy ở ``ERP_LISTING_API_URL`` mà repo này không chứa —
            # cứ tra ``etsy_publish`` hay ``etsy_listing_sku`` trong
            # ``schemas.py`` thì thấy: không có trường nào trong số này là của
            # ta cả. Xoá dòng này vì "app mình bỏ Telegram rồi" là trả đầu kia
            # về mặc định True, tức là bật lại đúng cái vừa tắt.
            "telegram_enabled": False,
            "erp_project_id": self.config.project_id,
            "erp_status_id": self.config.status_id,
            "erp_task_id": task_id,
            "erp_source_task_id": task_id,
            "etsy_enabled": True,
            "etsy_browser_copy_enabled": True,
            # Tài khoản đã tra qua sổ, nên cái **nhãn** ``acc32`` dán trên thẻ
            # cũng tính — không chỉ dòng ``acc:`` gõ tay. Đó là cách người làm
            # listing đang khai tài khoản.
            "etsy_account_id": routing.account_id or meta.account_id,
            "etsy_machine_id": machine,
            "etsy_keep_color_chart": True,
            "etsy_delete_existing_images": True,
            # Mã SKU của chính thẻ này. Trước đây bridge chỉ *đọc lại* cái SKU
            # bản Listing tự đặt, nên hai bên gọi cùng một sản phẩm bằng hai
            # mã khác nhau và không ai lần được từ listing về thẻ đã sinh ra
            # nó. Thẻ không có mã thì gửi chuỗi rỗng — đầu kia vẫn tự đặt như
            # cũ, nên đây là thêm chứ không phải đổi.
            #
            # Tên trường phải là ``etsy_listing_sku``: lược đồ bên kia bỏ qua
            # mọi khoá lạ trong im lặng, nên gửi ``sku`` trông y hệt gửi đúng
            # — chỉ khác là mã không bao giờ tới nơi. Đã gặp thật: thẻ mang
            # ``VT_1_001`` mà bản Listing vẫn tự đặt ``ANHMAUMAC-602161``.
            "etsy_listing_sku": meta.sku,
            # Chỉ dựng bản nháp. Không có bước nào trong đợt thử này được phép
            # đẩy hàng lên shop thật.
            "etsy_publish": False,
        }

    def dispatch(self, task_id: str, root: Mapping[str, Any]) -> Dict[str, Any]:
        """Giao thẻ đi. Trả về mã hàng đợi bên kia để còn lần theo được."""
        if not self.enabled:
            raise ListingBridgeError(
                "Chưa đặt ERP_LISTING_API_URL nên không có chỗ nào để giao thẻ listing."
            )
        payload = self.payload(task_id, root)
        response = self._post(
            f"{self.config.api_url}{ENQUEUE_PATH}", payload, self.config.timeout_s
        )
        return self._read(task_id, payload, response)

    def confirm(self, queue_task_id: str, machine_id: str = "") -> Dict[str, Any]:
        """Lượt đã giao ấy bên kia chạy tới đâu rồi.

        Xếp được hàng **không** phải là đăng xong. Giữa hai chuyện đó còn cả
        một máy ảo phải thức dậy, mở Chrome, chép ảnh và bấm lưu — và bất kỳ
        chặng nào cũng có thể hỏng. Luật cột đọc *đăng xong*, nên nó phải hỏi
        lại chỗ này chứ không được suy ra từ lúc giao.

        Ba câu trả lời, cố ý tách bạch:

        ``done``   bên kia báo ``completed``. Kèm ``draft_saved``: bản nháp đã
                   lưu trong shop hay chưa.
        ``failed`` bên kia báo hỏng. Kèm luôn câu lỗi để người đọc biết đường.
        Không cái nào — còn đang chạy, hoặc **không tra ra**. Ảnh chụp hàng đợi
        bên kia chỉ giữ ít lượt gần nhất, nên "không thấy" là *không biết*,
        không phải *hỏng*: đọc nhầm thành hỏng sẽ giao lại một thẻ đã đăng rồi,
        tức là hai bản nháp cho cùng một sản phẩm.
        """
        if not self.enabled:
            raise ListingBridgeError(
                "Chưa đặt ERP_LISTING_API_URL nên không hỏi được bản Listing."
            )
        queue_task_id = str(queue_task_id or "").strip()
        if not queue_task_id:
            return {"unknown": True, "reason": "không có mã hàng đợi để hỏi"}
        url = f"{self.config.api_url}{QUEUE_PATH}"
        machine = str(machine_id or "").strip()
        if machine:
            # Hỏi đúng máy được giao: ảnh chụp cắt còn ít lượt gần nhất, và
            # lọc theo máy thì lượt của mình ở lại lâu hơn trong khung ấy.
            url = f"{url}?machine_id={quote(machine, safe='')}"
        response = self._get(url, self.config.timeout_s)
        tasks = response.get("tasks") if isinstance(response, Mapping) else None
        found = None
        for item in tasks or []:
            if isinstance(item, Mapping) and str(item.get("id") or "") == queue_task_id:
                found = item
                break
        if found is None:
            return {
                "unknown": True,
                "reason": f"bản Listing không còn giữ lượt {queue_task_id} trong ảnh chụp hàng đợi",
            }
        status = str(found.get("status") or "").strip()
        if status == QUEUE_DONE:
            result = found.get("result")
            return {
                "done": True,
                "status": status,
                "card_moved": bool((found.get("erp_done_move") or {}).get("moved")),
                # Máy báo ``completed`` cả khi không bấm lưu được bản nháp.
                # Review Lister chỉ chuyển thẻ sang *Hoàn thành* khi cờ này thật.
                "draft_saved": bool(isinstance(result, Mapping) and result.get("draftSaved")),
            }
        if status in QUEUE_OPEN:
            return {"pending": True, "status": status}
        return {
            "failed": True,
            "status": status or "không rõ",
            "error": str(found.get("error") or "").strip() or "bản Listing không nói lý do",
        }

    def _read(
        self, task_id: str, payload: Mapping[str, Any], response: Any
    ) -> Dict[str, Any]:
        """Đọc câu trả lời của bản Listing, tách "nó từ chối" khỏi "nó hỏng"."""
        body = response.get("etsy_browser_copy") if isinstance(response, Mapping) else None
        if not isinstance(body, Mapping):
            raise ListingBridgeError(
                f"Bản Listing trả về thứ không đọc được cho thẻ {task_id}: {str(response)[:200]}"
            )
        machine = payload["etsy_machine_id"]

        if not body.get("configured", True):
            missing = ", ".join(str(item) for item in (body.get("missing") or [])) or "không rõ"
            raise ListingBridgeError(f"Bản Listing chưa cấu hình xong: thiếu {missing}.")

        if body.get("skipped"):
            reason = str(body.get("skip_reason") or "").strip()
            log.info("Bản Listing bỏ qua thẻ %s: %s.", task_id, SKIP_REASONS.get(reason, reason))
            return {
                "machine_id": machine,
                "skipped": SKIP_REASONS.get(reason, reason or "bản Listing không nói lý do"),
            }

        queue_task = body.get("queue_task")
        queue_id = str((queue_task or {}).get("id") or "").strip()
        if not body.get("enqueued") or not queue_id:
            missing = ", ".join(str(item) for item in (body.get("missing") or []))
            raise ListingBridgeError(
                f"Bản Listing không xếp hàng được thẻ {task_id}"
                + (f": thiếu {missing}." if missing else ".")
            )

        log.info(
            "Giao thẻ listing %s cho máy %s, hàng đợi %s bên bản Listing (%s ảnh).",
            task_id,
            machine,
            queue_id,
            body.get("image_count") or 0,
        )
        return {
            "queue_task_id": queue_id,
            "machine_id": machine,
            "sku": str(body.get("sku") or ""),
            "image_count": int(body.get("image_count") or 0),
        }


def build_listing_hook(bridge: ListingBridge | None):
    """Hook cho agent bot. ``None``/chưa bật thì trả về ``None`` — bot bỏ qua."""
    if bridge is None or not bridge.enabled:
        return None

    async def hook(task_id: str, root: Mapping[str, Any]) -> Dict[str, Any]:
        import asyncio

        return await asyncio.to_thread(bridge.dispatch, task_id, root)

    return hook


def build_listing_confirm_hook(bridge: ListingBridge | None):
    """Hook hỏi lại kết quả. Cùng điều kiện bật/tắt với hook giao thẻ."""
    if bridge is None or not bridge.enabled:
        return None

    async def hook(queue_task_id: str, machine_id: str) -> Dict[str, Any]:
        import asyncio

        return await asyncio.to_thread(bridge.confirm, queue_task_id, machine_id)

    return hook
