"""Thẻ nằm ở cột *Đang review* là thẻ cần đăng lên Etsy.

Luật do người vận hành chốt ngày 10/09/2026:

* Kéo thẻ sang cột *Đang review* là lời giao việc.
* ``account`` nói đăng vào tài khoản nào.
* ``copysku`` nói chép bài mẫu từ SKU nào trên tài khoản ấy.

Luật thêm ngày 11/09/2026: bản nháp lưu xong là xong việc. Người bán không
soát nữa; lister tự chuyển thẻ sang *Hoàn thành*. Máy báo xong mà không lưu
được bản nháp thì thẻ nằm lại *Đang review*, kèm bình luận.

Chạy riêng một tiến trình, không đi qua vòng quét của agent bot. Cửa vào
``/api/etsy/browser-copy/enqueue`` của bản Listing chỉ đọc thẻ Trello, nên ở
đây đi cửa ``enqueue-direct``: tự tải ảnh trên thẻ ERP về thư mục tải xuống
của bản Listing, rồi đưa đường dẫn tương đối để máy Etsy kéo về.

Mỗi thẻ chỉ giao **một lần**. Sổ ghi ở ``data/review_lister.json``: thẻ có
thể nằm lại *Đang review* (chưa lưu nháp, chưa chuyển được cột), không có sổ
thì mỗi lượt quét lại thêm một bản nháp cho cùng một sản phẩm.

Ảnh đọc bằng **khoá app** (``ERP_API_KEY``/``ERP_API_SECRET``), không bằng
token bot. Token bot không thấy tệp riêng tư trong bình luận, và ``taskFull``
không trả tệp treo thẳng trên thẻ. Ngày 10/09/2026 hai thẻ đầu tiên lên Etsy
thiếu ảnh vì hai chỗ mù đó.
"""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Collection, Dict, List, Mapping, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen

from .erp_meta import ACCOUNT_KEYS, COPY_SKU_KEYS, task_meta
from .listing_bridge import QUEUE_DONE, QUEUE_OPEN, QUEUE_PATH, ListingBridge, ListingBridgeConfig, ListingBridgeError
from .paths import DATA_DIR, PROJECT_ROOT
from .pipeline import COL_DONE, COL_REVIEW, normalize_status

log = logging.getLogger(__name__)

DIRECT_PATH = "/api/etsy/browser-copy/enqueue-direct"
FILES_PREFIX = "/files/downloads"
REVIEW_STATUSES = frozenset({"pending-review", "pending_review", "pending review", "dang review", "đang review", "review"})
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")
DONE_NOTE = "Đã list xong lên Etsy (bản nháp)."
UNSAVED_NOTE = (
    "Máy Etsy báo xong nhưng không lưu được bản nháp. Thẻ nằm lại Đang review: "
    "người xem trên Etsy, rồi kéo tay sang Hoàn thành hoặc nhờ đăng lại."
)
LEDGER_FILE = DATA_DIR / "review_lister.json"
# Ảnh chụp mỗi lượt quét, ghi vào thư mục tải xuống của bản Listing. Bản Listing
# phục vụ thư mục ấy ở ``/files/downloads/``, nên bảng theo dõi trên máy dev
# (``flow_web.listing_board``) đọc được qua HTTP, không cần ssh.
STATUS_FILE = "review_lister_status.json"
MAX_IMAGES = 9
# Chỗ cất tệp treo thẳng trên thẻ ngay trong node, giống ``_board_row`` của
# agent bot. Gạch dưới ở đầu để không đụng field nào của ERP.
CARD_FILES_KEY = "_card_files"
TASK_ATTACHMENTS = "query TaskAttachments($task: String!) { taskAttachments(task: $task) }"
TASK_DETAIL = "query TaskDetail($name: String!) { taskDetail(name: $name) }"
# Cùng câu ``service.py`` dùng. Đi bằng khoá app: token bot không đổi cột.
UPDATE_TASK_STATUS = "mutation UpdateTaskStatus($name: String!, $status: String!) { updateTaskStatus(name: $name, status: $status) }"
# Mỗi lượt quét gọi ``taskFull`` tối đa chừng này lần: token bot có trần 60
# request/phút, và vòng quét của agent bot đang dùng chung nó.
MAX_FULL_PER_PASS = 5

Download = Callable[[str], Tuple[bytes, str]]
Post = Callable[[str, Dict[str, Any], int], Dict[str, Any]]
# Đọc bằng khoá app: ``{"files": [...], "comments": [...]}`` của một thẻ.
Reader = Callable[[str], Dict[str, Any]]
# Chuyển một thẻ sang *Hoàn thành*. Lỗi thì ném ra, lượt sau thử lại.
Closer = Callable[[str], Any]


class ReviewListerError(RuntimeError):
    """Thẻ chưa đăng được — câu lỗi viết cho người đọc."""


def is_review_status(value: Any) -> bool:
    return str(value or "").strip().lower() in REVIEW_STATUSES


def _vote_dropped(node: Mapping[str, Any]) -> bool:
    """Ảnh bị 👎 nhiều hơn 👍 thì không đăng."""
    return int(node.get("dislike_count") or 0) > int(node.get("like_count") or 0)


def _url_key(url: str) -> str:
    """Cùng một tệp có thể về dạng tuyệt đối hoặc tương đối, có hoặc không mã hoá."""
    return unquote(urlparse(url).path)


def card_image_urls(task_node: Mapping[str, Any]) -> List[str]:
    """Mọi ảnh trên thẻ, bỏ ảnh bị 👎.

    Thứ tự: ảnh bìa, tệp treo thẳng trên thẻ (cũ trước), rồi ảnh đính trong
    bình luận theo thứ tự bình luận. Kéo thẻ sang *Đang review* đã là lời
    duyệt, nên không đòi 👍 từng tấm.

    Trường ``image`` của bình luận **không** phải ảnh đính kèm: đó là ảnh đại
    diện của người bình luận. Hai bình luận đính hai bộ tệp khác nhau vẫn trả
    cùng một ``image``, tệp công khai 512×512. Ngày 10/09/2026 lister đã đăng
    ảnh chân dung ấy làm ảnh thứ hai của TASK-2026-04789.
    """
    urls: List[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        url = str(value or "").strip()
        tail = url.split("?", 1)[0].rsplit("/", 1)[-1].lower()
        if url and tail.endswith(IMAGE_SUFFIXES) and _url_key(url) not in seen:
            seen.add(_url_key(url))
            urls.append(url)

    # Ảnh bìa đứng đầu: người vận hành thả ảnh sản phẩm làm bìa thẻ.
    add(task_node.get("cover_image"))
    # Tệp kéo thả vào thẻ nằm ở danh sách tệp của thẻ, không ở bình luận nào.
    # ``taskAttachments`` trả mới trước; đảo lại để ảnh đầu tiên thả vào đứng đầu.
    card_files = [item for item in task_node.get(CARD_FILES_KEY) or [] if isinstance(item, Mapping)]
    for item in sorted(card_files, key=lambda row: str(row.get("creation") or "")):
        add(item.get("file_url") or item.get("url"))
    for comment in task_node.get("comments") or []:
        if not isinstance(comment, Mapping):
            continue
        for item in (comment, *(comment.get("replies") or [])):
            if not isinstance(item, Mapping) or _vote_dropped(item):
                continue
            for attachment in item.get("attachments") or []:
                if isinstance(attachment, Mapping):
                    add(attachment.get("file_url") or attachment.get("url"))
                else:
                    add(attachment)
    return urls


def card_fields(task_node: Mapping[str, Any]) -> Dict[str, str]:
    meta = task_meta(task_node)
    return {
        "account": meta.get(*ACCOUNT_KEYS),
        "copysku": meta.get(*COPY_SKU_KEYS),
        "sku": meta.sku or str(task_node.get("sku") or "").strip(),
        "title": str(task_node.get("subject") or task_node.get("title") or "").strip(),
    }


def missing_fields(task_node: Mapping[str, Any]) -> List[str]:
    fields = card_fields(task_node)
    missing = [name for name in ("account", "copysku") if not fields[name]]
    if not card_image_urls(task_node):
        missing.append("ảnh trên thẻ")
    return missing


class ErpFiles:
    """Tải ảnh ERP. Ảnh ``/private/files/`` phải đi qua ``download_file`` kèm khoá API."""

    def __init__(self, base_url: str, key: str = "", secret: str = "", timeout_s: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.key = key
        self.secret = secret
        self.timeout_s = timeout_s

    @classmethod
    def from_env(cls, base_url: str) -> "ErpFiles":
        return cls(
            os.getenv("ERP_BASE_URL", "").strip() or base_url,
            os.getenv("ERP_API_KEY", "").strip(),
            os.getenv("ERP_API_SECRET", "").strip(),
        )

    def __call__(self, url: str) -> Tuple[bytes, str]:
        if url.startswith("/"):
            url = f"{self.base_url}{url}"
        parsed = urlparse(url)
        headers = {"User-Agent": "Flow-v2-HaviGroup-ERP/1.0"}
        if parsed.netloc == urlparse(self.base_url).netloc and parsed.path.startswith("/private/files/"):
            if not (self.key and self.secret):
                raise ReviewListerError("Thiếu ERP_API_KEY/ERP_API_SECRET nên không tải được ảnh riêng tư của ERP.")
            url = (
                f"{self.base_url}/api/method/frappe.core.doctype.file.file.download_file"
                f"?file_url={quote(parsed.path, safe='')}"
            )
            headers["Authorization"] = f"token {self.key}:{self.secret}"
        try:
            with urlopen(Request(url, headers=headers), timeout=self.timeout_s) as response:
                kind = response.headers.get_content_type() if response.headers else ""
                return response.read(), kind
        except HTTPError as exc:
            raise ReviewListerError(f"Không tải được ảnh trên thẻ (HTTP {exc.code}).") from exc
        except (URLError, TimeoutError) as exc:
            raise ReviewListerError(f"Không kết nối được ERP để tải ảnh: {getattr(exc, 'reason', exc)}") from exc

    def graphql(self, query: str, variables: Dict[str, Any], operation: str) -> Dict[str, Any]:
        if not (self.key and self.secret):
            raise ReviewListerError("Thiếu ERP_API_KEY/ERP_API_SECRET nên không đọc được tệp trên thẻ.")
        request = Request(
            f"{self.base_url}/api/method/hvg_workspace.graphql.endpoint.graphql",
            data=json.dumps({"query": query, "variables": variables, "operationName": operation}).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Flow-v2-HaviGroup-ERP/1.0",
                "Authorization": f"token {self.key}:{self.secret}",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                body = json.loads(response.read().decode("utf-8") or "{}")
        except HTTPError as exc:
            raise ReviewListerError(f"ERP từ chối {operation} (HTTP {exc.code}).") from exc
        except (URLError, TimeoutError, ValueError) as exc:
            raise ReviewListerError(f"Không gọi được {operation} trên ERP: {getattr(exc, 'reason', exc)}") from exc
        if isinstance(body, dict) and body.get("errors"):
            raise ReviewListerError(f"ERP báo lỗi {operation}: {str(body.get('errors'))[:200]}")
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise ReviewListerError(f"ERP trả {operation} không đúng dạng.")
        return data

    def card_files(self, task_id: str) -> Dict[str, Any]:
        """Tệp treo trên thẻ và bình luận kèm đủ tệp, đọc bằng khoá app.

        Lỗi thì ném ra, không trả rỗng: thiếu tệp mà vẫn đăng là ra một bản
        nháp thiếu ảnh, còn lỗi thì lượt quét sau đọc lại.
        """
        files = self.graphql(TASK_ATTACHMENTS, {"task": task_id}, "TaskAttachments").get("taskAttachments")
        rows = files.get("files") if isinstance(files, dict) else None
        if not isinstance(rows, list):
            raise ReviewListerError(f"ERP không trả danh sách tệp của {task_id}.")
        detail = self.graphql(TASK_DETAIL, {"name": task_id}, "TaskDetail").get("taskDetail")
        if not isinstance(detail, dict) or str(detail.get("name") or "").strip() != task_id:
            raise ReviewListerError(f"ERP không trả thẻ {task_id} cho khoá app.")
        return {
            "files": [row for row in rows if isinstance(row, dict)],
            "comments": [row for row in detail.get("comments") or [] if isinstance(row, dict)],
        }

    def close_card(self, task_id: str) -> None:
        """Chuyển thẻ đã lưu nháp sang *Hoàn thành*, bằng khoá app.

        Đọc lại cột ngay trước khi ghi. Còn ở *Đang review* thì chuyển. Đã ở
        *Hoàn thành* thì thôi: người kéo tay trước rồi. Ở cột khác thì ném lỗi
        mà không ghi: người đã kéo thẻ đi, máy không kéo về.
        """
        if not (self.key and self.secret):
            raise ReviewListerError("Thiếu ERP_API_KEY/ERP_API_SECRET nên không chuyển được thẻ sang Hoàn thành.")
        detail = self.graphql(TASK_DETAIL, {"name": task_id}, "TaskDetail").get("taskDetail")
        if not isinstance(detail, dict) or str(detail.get("name") or "").strip() != task_id:
            raise ReviewListerError(f"ERP không trả thẻ {task_id} cho khoá app.")
        status = normalize_status(detail.get("status"))
        if status == COL_DONE:
            return
        if status != COL_REVIEW:
            raise ReviewListerError(
                f"Thẻ {task_id} đang ở cột {detail.get('status') or '?'}, không tự chuyển sang Hoàn thành."
            )
        self.graphql(UPDATE_TASK_STATUS, {"name": task_id, "status": COL_DONE}, "UpdateTaskStatus")


def _post_json(url: str, payload: Dict[str, Any], timeout_s: int) -> Dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise ReviewListerError(f"Bản Listing từ chối (HTTP {exc.code}): {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise ReviewListerError(f"Không gọi được bản Listing: {getattr(exc, 'reason', exc)}") from exc


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-") or "the"


def _utc(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


class ReviewLister:
    def __init__(
        self,
        bridge: ListingBridge,
        files_dir: Path | str,
        download: Download,
        post: Post | None = None,
        ledger_file: Path | str = LEDGER_FILE,
        card_url: str = "",
        reader: Reader | None = None,
        closer: Closer | None = None,
    ) -> None:
        self.bridge = bridge
        self.reader = reader
        # Không có thì lister không đổi cột thẻ nào, như trước 11/09/2026.
        self.closer = closer
        self.files_dir = Path(files_dir)
        self.download = download
        self.post = post or _post_json
        self.ledger_file = Path(ledger_file)
        self.card_url = card_url.rstrip("/")
        # Lần cuối soi từng thẻ, để vòng quét xoay vòng dưới trần taskFull.
        self.checked: Dict[str, float] = {}
        # Kết quả soi gần nhất của từng thẻ, cho tệp trạng thái. Mỗi lượt chỉ
        # soi 5 thẻ, nên thẻ chưa tới lượt giữ kết quả của lượt trước.
        self.last_seen: Dict[str, Dict[str, Any]] = {}
        self.loop_seconds = 0

    # ── sổ ─────────────────────────────────────────────────────────────

    def ledger(self) -> Dict[str, Dict[str, Any]]:
        try:
            data = json.loads(self.ledger_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, ledger: Mapping[str, Any]) -> None:
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ledger_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.ledger_file)

    # ── tệp trạng thái cho bảng theo dõi ───────────────────────────────

    def note(self, task_id: str, outcome: Mapping[str, Any], fields: Mapping[str, str] | None = None) -> None:
        seen: Dict[str, Any] = {key: outcome[key] for key in ("waiting", "error") if outcome.get(key)}
        for key in ("account", "copysku", "sku", "title"):
            if fields and fields.get(key):
                seen[key] = fields[key]
        seen["checked_at"] = _utc(time.time())
        self.last_seen[task_id] = seen

    def status(self, review: List[Mapping[str, Any]], errors: List[str]) -> Dict[str, Any]:
        """Mọi thẻ ở cột review, mỗi thẻ một trạng thái: sổ trước, rồi lần soi gần nhất."""
        ledger = self.ledger()
        cards: List[Dict[str, Any]] = []
        for row in review:
            task_id = str(row["task"])
            seen = self.last_seen.get(task_id, {})
            entry = ledger.get(task_id)
            card: Dict[str, Any] = {
                "task": task_id,
                "project": row.get("project", ""),
                "title": seen.get("title") or row.get("title") or "",
                "url": f"{self.card_url}/{task_id}" if self.card_url else "",
                "checked_at": seen.get("checked_at", ""),
                **{key: seen.get(key, "") for key in ("account", "copysku", "sku")},
            }
            if entry:
                card["state"] = str(entry.get("state") or "queued")
                keys = (
                    "queue_task_id", "machine_id", "account_id", "sku", "copysku", "image_count", "at", "replaces",
                    "draft_saved", "closed_at", "close_error",
                )
                card.update({key: entry[key] for key in keys if key in entry})
            elif seen.get("error"):
                card.update(state="error", note=seen["error"])
            elif seen.get("waiting"):
                card.update(state="waiting", note=seen["waiting"])
            else:
                card.update(state="unchecked", note="chưa tới lượt soi")
            cards.append(card)
        return {"at": _utc(time.time()), "every": self.loop_seconds, "cards": cards, "errors": errors, "ledger": ledger}

    def publish_status(self, review: List[Mapping[str, Any]], errors: List[str]) -> None:
        """Ghi tệp trạng thái. Tệp này để người xem: ghi hỏng thì chỉ ghi log."""
        target = self.files_dir / STATUS_FILE
        try:
            snapshot = self.status(review, errors)
            self.files_dir.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(target)
        except Exception as exc:  # Windows: bản Listing đang đọc tệp thì replace hỏng
            log.warning("Không ghi được %s: %s", target, exc)

    # ── một thẻ ────────────────────────────────────────────────────────

    def stage_images(self, task_id: str, urls: List[str]) -> List[str]:
        """Tải ảnh về thư mục tải xuống của bản Listing, trả về đường dẫn tương đối."""
        folder_name = f"erp-{_safe_name(task_id)}"
        folder = self.files_dir / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        relative: List[str] = []
        for index, url in enumerate(urls[:MAX_IMAGES], start=1):
            data, kind = self.download(url)
            if not data:
                raise ReviewListerError(f"Ảnh thứ {index} trên thẻ tải về rỗng.")
            suffix = Path(urlparse(url).path).suffix.lower()
            if suffix not in IMAGE_SUFFIXES:
                suffix = mimetypes.guess_extension(kind or "") or ".jpg"
            name = f"{index:02d}{suffix}"
            (folder / name).write_bytes(data)
            relative.append(f"{FILES_PREFIX}/{folder_name}/{name}")
        return relative

    def payload(self, task_id: str, node: Mapping[str, Any], image_urls: List[str]) -> Dict[str, Any]:
        fields = card_fields(node)
        routing = self.bridge.routing_for(node)
        machine = self.bridge._machine_for(routing)
        if not machine:
            raise ReviewListerError(
                f"Tài khoản {fields['account']} chưa gắn máy Etsy nào (sổ tài khoản / ERP_LISTING_MACHINES)."
            )
        sku = fields["sku"] or task_id
        return {
            "title": fields["title"] or sku,
            "sku": sku,
            "templateSourceSku": fields["copysku"],
            "imageUrls": image_urls,
            "images": [{"download_url": url, "name": url.rsplit("/", 1)[-1]} for url in image_urls],
            "accountId": routing.account_id or fields["account"],
            "machineId": machine,
            "cardId": task_id,
            "cardUrl": f"{self.card_url}/{task_id}" if self.card_url else "",
            "jobId": f"erp-{task_id}",
            "moduleId": "erp_review_lister",
            "keepColorChart": True,
            "deleteExistingImages": True,
        }

    def list_card(self, node: Mapping[str, Any], again: bool = False) -> Dict[str, Any]:
        """Giao một thẻ cho máy Etsy.

        ``again`` là đăng lại thẻ đã đăng — người gõ tay, khi bản nháp cũ sai.
        Nó bỏ qua sổ và lượt đã xong, nhưng lượt còn đang chờ/chạy thì vẫn chặn.
        Bản nháp cũ trên Etsy vẫn còn đó, người phải xoá.
        """
        task_id = str(node.get("name") or "").strip()
        if not task_id:
            raise ReviewListerError("Thẻ không có mã.")
        missing = missing_fields(node)
        if missing:
            return {"task": task_id, "waiting": "thiếu " + ", ".join(missing)}
        ledger = self.ledger()
        previous = ledger.get(task_id)
        if previous and not again:
            return {"task": task_id, "already": previous.get("queue_task_id")}
        # Hỏi máy trước khi tải ảnh: thẻ từ chối thì không để rác trong thư mục tải xuống.
        routing = self.bridge.routing_for(node)
        machine = self.bridge._machine_for(routing)
        if not machine:
            self.payload(task_id, node, [])
        existing = self.existing_run(task_id, machine, include_done=not again)
        if existing:
            fields = card_fields(node)
            ledger[task_id] = self._entry(existing, machine, routing.account_id or fields["account"], fields["sku"] or task_id, fields["copysku"], 0)
            ledger[task_id]["adopted"] = True
            self._save(ledger)
            log.info("Thẻ %s đã có lượt %s bên bản Listing; ghi sổ, không giao lại.", task_id, existing)
            return {"task": task_id, "queue_task_id": existing, "machine_id": machine, "adopted": True}
        urls = card_image_urls(node)
        if len(urls) > MAX_IMAGES:
            log.warning("Thẻ %s có %s ảnh, chỉ đăng %s ảnh đầu.", task_id, len(urls), MAX_IMAGES)
        staged = self.stage_images(task_id, urls)
        payload = self.payload(task_id, node, staged)
        response = self.post(f"{self.bridge.config.api_url}{DIRECT_PATH}", payload, self.bridge.config.timeout_s)
        # Route thật bọc kết quả trong ``etsy_browser_copy``, giống cửa ``enqueue``.
        body = response.get("etsy_browser_copy") if isinstance(response, Mapping) else None
        queue_id = str(((body if isinstance(body, Mapping) else {}).get("queue_task") or {}).get("id") or "").strip()
        if not isinstance(body, Mapping) or not body.get("enqueued") or not queue_id:
            raise ReviewListerError(f"Bản Listing không xếp hàng được thẻ {task_id}: {str(response)[:200]}")
        ledger[task_id] = self._entry(
            queue_id, payload["machineId"], payload["accountId"], payload["sku"], payload["templateSourceSku"], len(staged)
        )
        if previous:
            # Giữ vết bản nháp cũ: người phải xoá nó trên Etsy.
            ledger[task_id]["replaces"] = [*previous.get("replaces", []), previous.get("queue_task_id")]
        self._save(ledger)
        log.info("Giao thẻ %s cho máy %s, hàng đợi %s (%s ảnh).", task_id, payload["machineId"], queue_id, len(staged))
        outcome = {"task": task_id, "queue_task_id": queue_id, "machine_id": payload["machineId"], "image_count": len(staged)}
        if len(urls) > MAX_IMAGES:
            outcome["images_left_out"] = len(urls) - MAX_IMAGES
        return outcome

    @staticmethod
    def _entry(queue_id: str, machine: str, account: str, sku: str, copysku: str, image_count: int) -> Dict[str, Any]:
        return {
            "queue_task_id": queue_id,
            "machine_id": machine,
            "account_id": account,
            "sku": sku,
            "copysku": copysku,
            "image_count": image_count,
            "state": "queued",
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def existing_run(self, task_id: str, machine: str, include_done: bool = True) -> str:
        """Lượt của thẻ này mà bản Listing còn giữ, nếu có.

        Sổ có thể lỡ không ghi trong khi bên kia đã nhận: câu trả lời đọc hỏng,
        tiến trình chết giữa chừng. Hỏi hàng đợi trước khi giao là chốt cuối,
        để một sản phẩm không bao giờ có hai bản nháp. Lượt hỏng không tính:
        thẻ ấy được giao lại. Không hỏi được thì không giao — lượt sau thử lại.
        """
        wanted = (*QUEUE_OPEN, QUEUE_DONE) if include_done else tuple(QUEUE_OPEN)
        url = f"{self.bridge.config.api_url}{QUEUE_PATH}?machine_id={quote(machine, safe='')}"
        response = self.bridge._get(url, self.bridge.config.timeout_s)
        for item in (response.get("tasks") if isinstance(response, Mapping) else None) or []:
            if not isinstance(item, Mapping) or str(item.get("card_id") or "").strip() != task_id:
                continue
            if str(item.get("status") or "").strip() in wanted:
                return str(item.get("id") or "").strip()
        return ""

    def follow_up(
        self, comment: Callable[[str, str], Any] | None = None, in_review: Collection[str] = ()
    ) -> List[Dict[str, Any]]:
        """Hỏi lại các lượt đã giao, rồi chuyển thẻ đã lưu nháp sang *Hoàn thành*.

        Lưu được nháp thì ghi sổ ``done`` và bình luận lên thẻ. Máy báo xong
        mà không lưu được thì ghi ``unsaved``, bình luận, để thẻ lại cho người.

        Chỉ chuyển thẻ có trong ``in_review``: thẻ lượt quét này thấy ở cột
        *Đang review*. Bảng đọc hỏng, hay thẻ đã sang cột khác, thì không đụng.
        Một lần chuyển hỏng thì thôi chuyển tới lượt sau. Sổ cũ không có
        ``draft_saved``: thẻ đăng theo luật cũ, người bán vẫn tự kéo.
        """
        ledger = self.ledger()
        lines: List[Dict[str, Any]] = []
        changed = False
        closing = self.closer is not None
        try:
            for task_id, entry in ledger.items():
                if entry.get("state") == "queued":
                    outcome = self.bridge.confirm(str(entry.get("queue_task_id") or ""), str(entry.get("machine_id") or ""))
                    if outcome.get("done"):
                        saved = bool(outcome.get("draft_saved"))
                        entry["state"] = "done" if saved else "unsaved"
                        entry["draft_saved"] = saved
                        changed = True
                        if comment is not None:
                            try:
                                comment(task_id, DONE_NOTE if saved else UNSAVED_NOTE)
                                entry["noted"] = True
                            except Exception as exc:  # bình luận hỏng không được làm mất biên lai
                                log.warning("Không bình luận được lên thẻ %s: %s", task_id, exc)
                        lines.append({"task": task_id, "listed": True} if saved else {"task": task_id, "unsaved": True})
                    elif outcome.get("failed"):
                        entry["state"] = "failed"
                        entry["error"] = outcome.get("error")
                        changed = True
                        lines.append({"task": task_id, "failed": outcome.get("error")})
                if not (
                    closing
                    and entry.get("state") == "done"
                    and entry.get("draft_saved")
                    and not entry.get("closed_at")
                    and task_id in in_review
                ):
                    continue
                changed = True
                try:
                    self.closer(task_id)
                except Exception as exc:  # ERP từ chối một lần (429, 503) thì lần sau cũng thế
                    entry["close_error"] = str(exc)
                    closing = False
                    log.warning("Không chuyển được thẻ %s sang Hoàn thành: %s", task_id, exc)
                    lines.append({"task": task_id, "close_error": str(exc)})
                else:
                    entry["closed_at"] = _utc(time.time())
                    entry.pop("close_error", None)
                    lines.append({"task": task_id, "closed": True})
        finally:
            # Hỏi hàng đợi hỏng giữa chừng thì vẫn giữ biên lai của các thẻ đã xử lý.
            if changed:
                self._save(ledger)
        return lines


# ── chạy tay / chạy vòng ──────────────────────────────────────────────


def _load_env_file(path: Path) -> None:
    """Đọc ``.env.local`` như ``main.py``: biến đã có trong môi trường thì thắng."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def build_from_env():
    from .agent_bot import AgentBotClient, AgentBotConfig, shared_limiter_from_env

    env_file = os.environ.get("FLOW_ENV_FILE", "").strip()
    _load_env_file(Path(env_file) if env_file else PROJECT_ROOT / ".env.local")
    config = AgentBotConfig.from_env()
    client = AgentBotClient(config, limiter=shared_limiter_from_env())
    bridge_config = ListingBridgeConfig.from_env()
    if not bridge_config.enabled:
        raise ReviewListerError("Chưa đặt ERP_LISTING_API_URL.")
    files_dir = os.getenv("ERP_LISTING_FILES_DIR", "").strip()
    if not files_dir:
        raise ReviewListerError("Chưa đặt ERP_LISTING_FILES_DIR (thư mục data\\downloads của bản Listing).")
    # Không có sổ tài khoản thì bridge tra máy theo số: acc31 → etsy-vn31
    # trong ERP_LISTING_MACHINES. Thẻ khai tài khoản mà không tra ra máy thì từ chối.
    bridge = ListingBridge(bridge_config)
    erp = ErpFiles.from_env(config.base_url)
    lister = ReviewLister(
        bridge,
        files_dir,
        erp,
        card_url=os.getenv("ERP_CARD_URL_BASE", "").strip() or f"{config.base_url}/app/task",
        reader=erp.card_files,
        closer=erp.close_card,
    )
    return client, config, lister


def _card(full: Any) -> Dict[str, Any]:
    """``taskFull`` gói thẻ trong ``root``, giống cây agent bot đọc."""
    if not isinstance(full, dict):
        return {}
    root = full.get("root")
    return root if isinstance(root, dict) else full


def read_card(client, lister: ReviewLister, task_id: str) -> Dict[str, Any]:
    """Thẻ để đăng: thân thẻ từ ``taskFull``, ảnh đọc lại bằng khoá app.

    Chỉ đọc thêm khi thẻ đã khai đủ ``account`` và ``copysku``: thẻ chưa khai
    thì đằng nào cũng chờ, khỏi tốn hai lời gọi.
    """
    node = dict(_card(client.task_full(task_id)))
    node.setdefault("name", task_id)
    if lister.reader is not None and all(card_fields(node)[name] for name in ("account", "copysku")):
        extra = lister.reader(task_id)
        node[CARD_FILES_KEY] = list(extra.get("files") or [])
        # Bình luận đọc bằng khoá app mới có đủ tệp đính kèm.
        node["comments"] = list(extra.get("comments") or [])
    return node


def scan_once(client, config, lister: ReviewLister) -> List[Dict[str, Any]]:
    projects = list(config.projects) or [
        str(item.get("name") or item.get("id") or "") for item in client.task_projects()
    ]
    lines: List[Dict[str, Any]] = []
    done = set(lister.ledger())
    rows: List[Mapping[str, Any]] = []
    # Mọi thẻ ở cột review, kể cả thẻ đã đăng: cho tệp trạng thái.
    review: Dict[str, Dict[str, Any]] = {}
    for project in [item for item in projects if item]:
        try:
            board = client.task_board(project)
        except Exception as exc:
            lines.append({"project": project, "error": str(exc)})
            continue
        for row in board:
            task_id = str(row.get("name") or "").strip()
            if not task_id or not is_review_status(row.get("status")):
                continue
            fields = card_fields(row)
            review.setdefault(task_id, {"task": task_id, "project": project, "title": fields["title"]})
            if task_id in done:
                continue
            if "meta" in row and not all(fields[name] for name in ("account", "copysku")):
                # Dòng bảng đã mang khối Thuộc tính: chưa khai đủ thì khỏi gọi
                # ``taskFull``. Token này dùng chung trần 60 request/phút với bot.
                missing = [name for name in ("account", "copysku") if not fields[name]]
                lister.note(task_id, {"waiting": "thiếu " + ", ".join(missing)}, fields)
                continue
            rows.append(row)
    # Thẻ lâu chưa soi đi trước: có trần mỗi lượt thì phải xoay vòng, không
    # thì năm thẻ đầu cột chiếm hết suất và thẻ cuối cột không bao giờ tới lượt.
    rows.sort(key=lambda row: lister.checked.get(str(row.get("name")), 0.0))
    for row in rows[:MAX_FULL_PER_PASS]:
        task_id = str(row.get("name")).strip()
        lister.checked[task_id] = time.time()
        node: Dict[str, Any] = {}
        try:
            node = read_card(client, lister, task_id)
            outcome = lister.list_card(node)
        except Exception as exc:  # ERP 500 một thẻ không được làm chết cả lượt
            outcome = {"task": task_id, "error": str(exc)}
        lines.append(outcome)
        lister.note(task_id, outcome, card_fields(node) if node else None)
    if len(rows) > MAX_FULL_PER_PASS:
        lines.append({"review_cards": len(rows), "checked_this_pass": MAX_FULL_PER_PASS})
    try:
        # Chỉ thẻ vừa thấy ở cột review mới được chuyển sang Hoàn thành.
        lines.extend(lister.follow_up(lambda task, text: client.add_comment(task, text), in_review=set(review)))
    except Exception as exc:
        lines.append({"follow_up": "error", "error": str(exc)})
    errors = [
        f"{line.get('project') or 'follow_up'}: {line['error']}"
        for line in lines
        if line.get("error") and "task" not in line
    ]
    lister.publish_status(list(review.values()), errors)
    return lines


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Đăng lên Etsy các thẻ ERP ở cột Đang review.")
    parser.add_argument("--task", help="Chỉ đăng một thẻ, bỏ qua cột.")
    parser.add_argument("--loop", type=int, default=0, help="Quét lại sau N giây; 0 = một lượt.")
    parser.add_argument(
        "--again",
        action="store_true",
        help="Đăng lại thẻ --task dù sổ ghi đã đăng. Bản nháp cũ trên Etsy phải xoá tay.",
    )
    args = parser.parse_args(argv)
    if args.again and (not args.task or args.loop):
        parser.error("--again chỉ đi với --task và chạy một lượt.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client, config, lister = build_from_env()
    lister.loop_seconds = max(120, args.loop) if args.loop else 0
    while True:
        try:
            if args.task:
                lines = [lister.list_card(read_card(client, lister, args.task), again=args.again)]
                lines += lister.follow_up(client.add_comment)
            else:
                lines = scan_once(client, config, lister)
        except Exception as exc:  # vòng chạy nền: lỗi một lượt thì lượt sau thử lại
            lines = [{"task": args.task or "*", "error": str(exc)}]
        for line in lines:
            print(json.dumps(line, ensure_ascii=False), flush=True)
        if not args.loop:
            return 0
        time.sleep(max(120, args.loop))


if __name__ == "__main__":
    raise SystemExit(main())
