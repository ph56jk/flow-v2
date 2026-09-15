"""Theo dõi hàng đợi đăng Etsy từ máy dev, và soát bản nháp vừa lưu.

Chỉ gọi API của bản Listing trên hvg-pc, chỉ dùng thư viện chuẩn. Việc soát là
việc chỉ đọc (`verifyOnly`): máy Etsy tìm bản nháp theo SKU, mở trình sửa, đọc
bộ đếm "Add photos N remaining". Nó không bấm lưu, không sửa gì trên Etsy.

    .venv/bin/python -m flow_web.listing_watch              # theo dõi, tự soát
    .venv/bin/python -m flow_web.listing_watch --no-check   # chỉ xem trạng thái
    .venv/bin/python -m flow_web.listing_watch --card TASK-2026-05133

Cách làm và bẫy: docs/bat-listing-etsy.md, mục "Soát bản nháp không cần remote".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

# portproxy :80 trên hvg-pc trỏ về bản Listing :8001. Gọi thẳng :8001 qua
# Tailscale thì gặp tailscaled, trả 404.
DEFAULT_BASE = "http://100.75.125.80"
LISTINGS_SEARCH = (
    "https://www.etsy.com/your/shops/me/tools/listings"
    "?state=draft&sort=update_date&search_query="
)
INSPECT = "__INSPECT_EDITOR__"
# Việc chỉ đọc vẫn bắt buộc có link Trello. Link thẻ /c/ không đổi bảng của máy.
TRELLO_STUB = "https://trello.com/c/xac-minh-ban-nhap"
ETSY_MAX_PHOTOS = 20
DONE = {"completed", "failed", "blocked", "stopped"}

EDIT_RE = re.compile(r"/listing-editor/edit/(\d+)")
PHOTOS_RE = re.compile(r"add photos?.*?\b(\d+)\s+remaining\b", re.I)
VIDEO_RE = re.compile(r"add video.*?\b(\d+)\s+remaining\b", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+")

STATUS_VI = {
    "queued": "chờ máy",
    "in_progress": "đang đăng",
    "completed": "xong",
    "failed": "hỏng",
    "blocked": "bị chặn",
    "stopped": "đã dừng",
}


def mask(text: Any) -> str:
    """Kết quả việc có email hồ sơ Etsy/Trello: không in ra."""
    return EMAIL_RE.sub("<email>", str(text))


class ListingApi:
    def __init__(self, base: str = DEFAULT_BASE, timeout: float = 20.0) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout

    def _call(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def copy_tasks(self) -> List[dict]:
        """Việc đăng từ ERP, mọi máy."""
        return list(self._call("GET", "/api/etsy/browser-copy/queue").get("tasks") or [])

    def machines(self) -> List[dict]:
        return list(self._call("GET", "/api/listing2/machines").get("machines") or [])

    def lister_status(self, name: str) -> dict:
        """Tệp Review Lister ghi mỗi lượt vào thư mục tải xuống của bản Listing."""
        return self._call("GET", "/files/downloads/" + urllib.parse.quote(name))

    def listing2_tasks(self, machine_id: str) -> List[dict]:
        query = urllib.parse.urlencode({"machine_id": machine_id, "page_size": 50})
        return list(self._call("GET", "/api/listing2/tasks?" + query).get("tasks") or [])

    def create_check(self, machine_id: str, title: str, url: str) -> str:
        body = {
            "trelloUrl": TRELLO_STUB,
            "machineId": machine_id,
            "verifyOnly": True,
            "verifyTitle": title,
            "verifyUrl": url,
        }
        reply = self._call("POST", "/api/listing2/tasks", body)
        task_id = str((reply.get("task") or {}).get("id") or "")
        if not task_id:
            raise RuntimeError("Bản Listing không nhận việc soát: " + mask(json.dumps(reply, ensure_ascii=False))[:300])
        return task_id


def wait_task(
    api: ListingApi,
    machine_id: str,
    task_id: str,
    timeout: float = 900,
    poll: float = 10,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Optional[dict]:
    """Chờ việc chỉ đọc xong. Hết giờ thì trả None."""
    end = clock() + timeout
    while True:
        for task in api.listing2_tasks(machine_id):
            if task.get("id") == task_id and task.get("status") in DONE:
                return task
        if clock() >= end:
            return None
        sleep(poll)


def _texts(result: dict) -> List[str]:
    rows: List[Any] = list(result.get("optionLabels") or []) + list(result.get("buttons") or [])
    rows += list((result.get("mediaDebug") or {}).get("mediaControls") or [])
    return [str(row.get("text") or "") for row in rows if isinstance(row, dict)]


def _remaining(texts: List[str], pattern: "re.Pattern[str]") -> Optional[int]:
    # Như extension: lấy chuỗi ngắn nhất, để khỏi dính chữ của nút bên cạnh.
    for text in sorted((t for t in texts if pattern.search(t)), key=len):
        count = int(pattern.search(text).group(1))
        if 0 <= count <= ETSY_MAX_PHOTOS:
            return count
    return None


def read_editor(result: dict) -> dict:
    """Đọc kết quả `__INSPECT_EDITOR__` thành số ảnh, video, sửa dở."""
    texts = _texts(result)
    photos_left = _remaining(texts, PHOTOS_RE)
    video_left = _remaining(texts, VIDEO_RE)
    media = result.get("mediaDebug") or {}
    tiles = media.get("mediaTiles")
    save = [
        b for b in result.get("buttons") or []
        if isinstance(b, dict) and str(b.get("text") or "").strip().lower() == "save draft"
    ]
    match = EDIT_RE.search(str(result.get("url") or result.get("editorUrl") or ""))
    return {
        "listing_id": match.group(1) if match else "",
        "title": str(result.get("title") or ""),
        # imagePreviewCount đếm cả ảnh xem trước: không dùng làm số ảnh.
        "photos": ETSY_MAX_PHOTOS - photos_left if photos_left is not None else None,
        "tiles": len(tiles) if isinstance(tiles, list) else media.get("mediaTileCount"),
        "has_video": (video_left == 0) if video_left is not None else None,
        "unsaved": (not save[0].get("disabled")) if save else None,
    }


def find_draft(api: ListingApi, machine_id: str, sku: str, **wait: Any) -> dict:
    """Bước 1: tìm bản nháp mới nhất có SKU này, lấy link trình sửa."""
    task_id = api.create_check(machine_id, sku, LISTINGS_SEARCH + urllib.parse.quote(sku))
    task = wait_task(api, machine_id, task_id, **wait)
    if task is None:
        return {"task_id": task_id, "error": "hết giờ chờ máy Etsy"}
    result = task.get("result") or {}
    url = str(result.get("draftUrl") or "")
    # Tiêu đề không chứa SKU nên việc báo failed; có draftUrl là đã tìm thấy.
    if not EDIT_RE.search(url):
        error = task.get("error") or result.get("error") or "không thấy bản nháp theo SKU"
        return {"task_id": task_id, "error": mask(error)}
    return {"task_id": task_id, "draft_url": url}


def inspect_draft(api: ListingApi, machine_id: str, draft_url: str, **wait: Any) -> dict:
    """Bước 2: mở trình sửa, đọc bộ đếm ảnh."""
    task_id = api.create_check(machine_id, INSPECT, draft_url)
    task = wait_task(api, machine_id, task_id, **wait)
    if task is None:
        return {"task_id": task_id, "error": "hết giờ chờ máy Etsy"}
    if task.get("status") != "completed":
        return {"task_id": task_id, "error": mask(task.get("error") or task.get("status"))}
    info = read_editor(task.get("result") or {})
    info["task_id"] = task_id
    return info


def check_draft(
    api: ListingApi,
    machine_id: str,
    sku: str,
    expected: Optional[int] = None,
    **wait: Any,
) -> dict:
    report: Dict[str, Any] = {"machine_id": machine_id, "sku": sku, "expected": expected}
    found = find_draft(api, machine_id, sku, **wait)
    if found.get("error"):
        report["error"] = found["error"]
        return report
    report["draft_url"] = found["draft_url"]
    report.update(inspect_draft(api, machine_id, found["draft_url"], **wait))
    if not report.get("error") and expected is not None and report.get("photos") is not None:
        report["ok"] = report["photos"] == expected
    return report


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def format_report(report: dict) -> str:
    head = f"soát {report.get('sku')} trên {report.get('machine_id')}:"
    if report.get("error"):
        return f"{head} không soát được: {report['error']}"
    photos = report.get("photos")
    expected = report.get("expected")
    if photos is None:
        count = f"không đọc được bộ đếm ảnh ({report.get('tiles')} ô ảnh)"
    elif expected is None:
        count = f"{photos} ảnh"
    else:
        count = f"{photos}/{expected} ảnh"
    parts = [f"listing {report.get('listing_id') or '?'}", count]
    if report.get("has_video"):
        parts.append("CÒN VIDEO (có thể là video của mẫu)")
    elif report.get("has_video") is False:
        parts.append("không video")
    if report.get("unsaved"):
        parts.append("có sửa dở chưa lưu")
    verdict = {True: "ĐÚNG", False: "LỆCH"}.get(report.get("ok"), "")
    line = f"{head} {' · '.join(parts)}" + (f" · {verdict}" if verdict else "")
    return line + f"\n           {report.get('draft_url')}"


def _task_line(task: dict) -> str:
    status = str(task.get("status") or "")
    result = task.get("result") or {}
    bits = [
        str(task.get("card_id") or task.get("id")),
        str(task.get("sku") or "-"),
        str(task.get("claimed_machine_id") or task.get("machine_id") or "-"),
        f"{task.get('image_count')} ảnh",
        STATUS_VI.get(status, status),
    ]
    if status == "completed":
        bits.append("đã lưu nháp" if result.get("draftSaved") else "KHÔNG thấy draftSaved")
    error = task.get("error") or result.get("error")
    if error and status != "completed":
        bits.append(mask(error)[:200])
    return " · ".join(bits)


def watch(
    api: ListingApi,
    interval: float = 15,
    check: bool = True,
    out: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
    rounds: Optional[int] = None,
    **wait: Any,
) -> None:
    """In mỗi lần một việc đăng đổi trạng thái; bản nháp vừa lưu thì soát."""
    wait.setdefault("sleep", sleep)
    seen: Dict[str, str] = {}
    first = True
    done_rounds = 0
    while rounds is None or done_rounds < rounds:
        done_rounds += 1
        try:
            tasks = api.copy_tasks()
        except (OSError, urllib.error.URLError, ValueError) as exc:
            out(f"[{_now()}] không gọi được bản Listing: {mask(exc)}")
            sleep(interval)
            continue
        tasks.sort(key=lambda t: str(t.get("created_at") or ""))
        if first:
            open_tasks = [t for t in tasks if t.get("status") in ("queued", "in_progress")]
            out(f"[{_now()}] đang theo dõi {len(tasks)} việc đăng, {len(open_tasks)} việc chưa xong. Ctrl+C để dừng.")
            for task in open_tasks:
                out(f"[{_now()}] {_task_line(task)}")
        for task in tasks:
            task_id = str(task.get("id") or "")
            status = str(task.get("status") or "")
            if seen.get(task_id) == status:
                continue
            seen[task_id] = status
            if first:
                continue
            out(f"[{_now()}] {_task_line(task)}")
            saved = (task.get("result") or {}).get("draftSaved")
            if check and status == "completed" and saved and task.get("sku"):
                machine = str(task.get("claimed_machine_id") or task.get("machine_id") or "")
                expected = task.get("image_count")
                report = check_draft(
                    api, machine, str(task["sku"]),
                    int(expected) if isinstance(expected, int) else None, **wait,
                )
                out(f"[{_now()}] {task.get('card_id')} {format_report(report)}")
        first = False
        sleep(interval)


def _find_card(api: ListingApi, card_id: str) -> Optional[dict]:
    hits = [t for t in api.copy_tasks() if t.get("card_id") == card_id]
    hits.sort(key=lambda t: str(t.get("created_at") or ""))
    return hits[-1] if hits else None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m flow_web.listing_watch",
        description="Theo dõi việc đăng Etsy và soát bản nháp (chỉ đọc).",
    )
    parser.add_argument("--base", default=DEFAULT_BASE, help="địa chỉ bản Listing (mặc định %(default)s)")
    parser.add_argument("--no-check", action="store_true", help="chỉ in trạng thái, không soát bản nháp")
    parser.add_argument("--interval", type=float, default=15, help="giây giữa hai lần hỏi (mặc định %(default)s)")
    parser.add_argument("--card", help="soát ngay bản nháp của một thẻ, ví dụ TASK-2026-05133")
    parser.add_argument("--sku", help="soát ngay bản nháp mới nhất có SKU này")
    parser.add_argument("--machine", default="etsy-vn31", help="máy Etsy cho --sku (mặc định %(default)s)")
    parser.add_argument("--expect", type=int, help="số ảnh phải có, cho --sku")
    args = parser.parse_args(argv)
    api = ListingApi(args.base)
    try:
        if args.card or args.sku:
            sku, machine, expected, label = args.sku, args.machine, args.expect, args.sku
            if args.card:
                task = _find_card(api, args.card)
                if task is None:
                    print(f"Không thấy việc đăng nào của {args.card} trong hàng đợi.")
                    return 1
                print(f"[{_now()}] {_task_line(task)}")
                sku = str(task.get("sku") or "")
                machine = str(task.get("claimed_machine_id") or task.get("machine_id") or machine)
                expected = task.get("image_count") if args.expect is None else args.expect
                label = args.card
            print(f"[{_now()}] đang nhờ {machine} mở bản nháp, mất 1-3 phút...")
            report = check_draft(api, machine, str(sku), expected)
            print(f"[{_now()}] {label} {format_report(report)}")
            return 0 if report.get("ok") is not False and not report.get("error") else 2
        watch(api, interval=args.interval, check=not args.no_check)
    except KeyboardInterrupt:
        print("\nĐã dừng theo dõi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
