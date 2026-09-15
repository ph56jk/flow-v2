"""Phần đăng Etsy của bảng điều khiển (``python -m flow_web.board``).

Gộp ba nguồn trên hvg-pc, đều đọc qua HTTP:

- hàng đợi đăng của bản Listing: ``/api/etsy/browser-copy/queue``
- máy Etsy: ``/api/listing2/machines``
- tệp Review Lister ghi mỗi lượt: ``/files/downloads/review_lister_status.json``

Nút *Soát* nhờ máy Etsy mở bản nháp và đếm ảnh, như ``listing_watch --card``.
Việc soát chỉ đọc, không bấm lưu. Máy chủ và cửa mật khẩu nằm ở flow_web/board.py.

Cách đọc bảng: docs/bang-dieu-khien.md.
"""

from __future__ import annotations

import threading
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from .listing_watch import STATUS_VI, check_draft, format_report, mask
from .review_lister import STATUS_FILE

VN = timezone(timedelta(hours=7))

# acc32 và acc16 đã bỏ từ 11/09/2026: máy vẫn báo về nhưng không nhận thẻ nào.
RETIRED = {"etsy-vn32": "acc32 đã bỏ", "etsy-16": "acc16 đã bỏ"}

# Ngưỡng báo, tính bằng giây.
MACHINE_SILENT = 180  # agent báo về mỗi ~30 giây
QUEUED_TOO_LONG = 600  # máy rảnh nhận việc trong vài giây
RUNNING_TOO_LONG = 900  # một bản nháp 9 ảnh mất 2-6 phút
FAILED_RECENT = 86400  # lượt hỏng quá một ngày thì thôi báo

JOB_TONE = {
    "queued": "wait",
    "in_progress": "run",
    "completed": "ok",
    "failed": "bad",
    "blocked": "bad",
    "stopped": "off",
}


# ── giờ và số ─────────────────────────────────────────────────────────


def parse_time(value: Any, naive: timezone = timezone.utc) -> Optional[datetime]:
    """Giờ ISO của API là UTC. Sổ lister ghi giờ máy hvg-pc, không đuôi múi: truyền ``naive=VN``."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=naive)


def _iso(moment: Optional[datetime]) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds") if moment else ""


def _seconds(start: Optional[datetime], end: Optional[datetime]) -> Optional[int]:
    return round((end - start).total_seconds()) if start and end else None


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _minutes(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} phút"
    return f"{minutes // 60} giờ {minutes % 60:02d} phút"


# ── từng dòng ─────────────────────────────────────────────────────────


def job_view(task: Dict[str, Any], now: datetime, check: Optional[dict] = None) -> Dict[str, Any]:
    status = str(task.get("status") or "")
    result = task.get("result") or {}
    created = parse_time(task.get("created_at"))
    started = parse_time(task.get("started_at"))
    finished = parse_time(task.get("finished_at"))
    saved = bool(result.get("draftSaved"))
    error = task.get("error") or result.get("error") or ""
    label = STATUS_VI.get(status, status or "?")
    tone = JOB_TONE.get(status, "off")
    if status == "completed" and not saved:
        label, tone, error = "xong, không lưu nháp", "bad", error or "máy báo xong mà không có draftSaved"
    return {
        "id": str(task.get("id") or ""),
        "card": str(task.get("card_id") or ""),
        "card_url": str(task.get("card_url") or ""),
        "title": mask(task.get("title") or ""),
        "sku": str(task.get("sku") or ""),
        "machine": str(task.get("claimed_machine_id") or task.get("machine_id") or ""),
        "account": str(task.get("account_id") or ""),
        "images": _int(task.get("image_count")),
        "status": status,
        "label": label,
        "tone": tone,
        "saved": saved,
        "error": mask(error)[:400] if error and (status != "completed" or not saved) else "",
        "message": mask(result.get("message") or "")[:400],
        "created_at": _iso(created),
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "wait_s": _seconds(created, started or (now if status == "queued" else None)),
        "run_s": _seconds(started, finished or (now if status == "in_progress" else None)),
        "attempts": _int(task.get("attempts")),
        "agent": str(result.get("agent_version") or ""),
        "check": check,
    }


def machine_view(row: Dict[str, Any], now: datetime, jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    machine_id = str(row.get("id") or "")
    seen = parse_time(row.get("last_seen"))
    silent = _seconds(seen, now)
    if silent is not None:
        silent = max(0, silent)  # giờ hvg-pc chạy nhanh hơn máy dev vài chục giây
    mine = [job for job in jobs if job["machine"] == machine_id]
    busy = [job for job in mine if job["status"] == "in_progress"]
    online = bool(row.get("online")) and silent is not None and silent < MACHINE_SILENT
    retired = RETIRED.get(machine_id, "")
    if retired:
        tone = "off"
    elif not online:
        tone = "bad"
    else:
        tone = "run" if busy else "ok"
    return {
        "id": machine_id,
        "label": str(row.get("label") or machine_id),
        "online": online,
        "last_seen": _iso(seen),
        "silent_s": silent,
        "agent": str(row.get("agent_version") or ""),
        "extension": str(row.get("etsy_extension_version") or ""),
        "computer": str(row.get("computer_name") or ""),
        "ip": str(row.get("tailscale_ip") or ""),
        "retired": retired,
        "tone": tone,
        "busy": (busy[0]["card"] or busy[0]["id"]) if busy else "",
        "queued": sum(1 for job in mine if job["status"] == "queued"),
        "drafts": sum(1 for job in mine if job["status"] == "completed" and job["saved"]),
    }


STAGE_OF_JOB = {
    "queued": (1, "wait", "chờ máy"),
    "in_progress": (2, "run", "đang đăng"),
    "failed": (2, "bad", "hỏng"),
    "blocked": (2, "bad", "bị chặn"),
    "stopped": (1, "off", "đã dừng"),
}
# Sổ lister thay hàng đợi khi bản Listing khởi động lại: hàng đợi nằm trong RAM.
STAGE_OF_CARD = {
    "done": (3, "ok", "đã lưu nháp"),
    "queued": (1, "wait", "đã giao, chờ máy"),
    "failed": (2, "bad", "hỏng"),
    "unsaved": (2, "bad", "xong, không lưu nháp"),
    "error": (0, "bad", "lỗi khi soi thẻ"),
    "waiting": (0, "wait", "chờ khai"),
}


def _stage(card: Dict[str, Any], last: Optional[Dict[str, Any]]) -> tuple:
    if last is None:
        return STAGE_OF_CARD.get(str(card.get("state") or ""), (0, "off", "chưa soi"))
    if last["status"] == "completed":
        return (3, "ok", "đã lưu nháp") if last["saved"] else (2, "bad", last["label"])
    return STAGE_OF_JOB.get(last["status"], (1, "off", last["label"]))


def _card_view(card: Dict[str, Any], runs: List[Dict[str, Any]], in_review: bool) -> Dict[str, Any]:
    last = runs[-1] if runs else None
    stage, tone, label = _stage(card, last)
    note = mask(card.get("note") or "") if tone != "ok" or last is None else ""
    if last and last["error"]:
        note = last["error"]
    if card.get("close_error"):
        # Nháp đã lưu mà lister không chuyển được thẻ: lượt sau thử lại, nhưng người nên biết.
        tone, label, note = "bad", "chưa sang Hoàn thành", mask(card["close_error"])[:400]
    listed = parse_time(card.get("at"), naive=VN)
    checked = parse_time(card.get("checked_at"))
    if last:
        updated = parse_time(last["finished_at"] or last["started_at"] or last["created_at"])
    else:
        updated = listed or checked
    return {
        "task": str(card.get("task") or ""),
        "title": mask(card.get("title") or (last["title"] if last else "")),
        "url": str(card.get("url") or (last["card_url"] if last else "")),
        "project": str(card.get("project") or ""),
        "account": str(card.get("account") or card.get("account_id") or (last["account"] if last else "")),
        "machine": str(card.get("machine_id") or (last["machine"] if last else "")),
        "copysku": str(card.get("copysku") or ""),
        "sku": str(card.get("sku") or (last["sku"] if last else "")),
        "images": _int(card.get("image_count")) or (last["images"] if last else None),
        "stage": stage,
        "tone": tone,
        "label": label,
        "note": note,
        "in_review": in_review,
        # Lister đã tự chuyển thẻ sang Hoàn thành (luật 11/09/2026).
        "closed": bool(card.get("closed_at")),
        "runs": len(runs),
        "job": last["id"] if last else str(card.get("queue_task_id") or ""),
        "checked_at": _iso(checked),
        "updated_at": _iso(updated),
        "old_drafts": len(card.get("replaces") or []),
        "check": last["check"] if last else None,
        "can_check": bool(last and last["status"] == "completed" and last["saved"] and last["sku"]),
    }


def _rank(card: Dict[str, Any]) -> int:
    if card["tone"] == "bad":
        return 0
    if card["tone"] == "run":
        return 1
    if 1 <= card["stage"] < 3:
        return 2
    if card["stage"] == 3:
        return 3
    return 4 if card["tone"] == "wait" else 5


def card_views(
    lister_cards: List[Dict[str, Any]],
    jobs: List[Dict[str, Any]],
    ledger: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Một dòng mỗi thẻ: thẻ lister thấy ở cột review, cộng thẻ chỉ còn trong hàng đợi.

    Sổ lister cho biết thẻ nào rời cột vì đã được chuyển sang Hoàn thành.
    """
    ledger = ledger or {}
    runs: Dict[str, List[Dict[str, Any]]] = {}
    for job in jobs:
        if job["card"]:
            runs.setdefault(job["card"], []).append(job)
    for items in runs.values():
        items.sort(key=lambda job: job["created_at"])
    views: List[Dict[str, Any]] = []
    for card in lister_cards:
        task_id = str(card.get("task") or "")
        if task_id:
            views.append(_card_view(card, runs.pop(task_id, []), in_review=True))
    for task_id, items in runs.items():
        entry = ledger.get(task_id)
        closed_at = entry.get("closed_at") if isinstance(entry, dict) else None
        views.append(_card_view({"task": task_id, "closed_at": closed_at}, items, in_review=False))
    views.sort(key=lambda card: card["updated_at"], reverse=True)
    views.sort(key=_rank)
    return views


# ── cả bảng ───────────────────────────────────────────────────────────


def board_alerts(
    lister: Dict[str, Any],
    cards: List[Dict[str, Any]],
    jobs: List[Dict[str, Any]],
    machines: List[Dict[str, Any]],
    now: datetime,
) -> List[Dict[str, str]]:
    """Việc cần người nhìn. Thẻ chờ khai account/copysku không tính: đó là bước tay có chủ ý."""
    out: List[Dict[str, str]] = []

    def add(tone: str, text: str, link: str = "") -> None:
        out.append({"tone": tone, "text": text, "link": link})

    if lister["error"]:
        hint = (
            "chưa có tệp trạng thái: bản lister trên hvg-pc chưa cập nhật, hoặc chưa xong lượt nào"
            if lister["error"] == "HTTP 404"
            else lister["error"]
        )
        add("bad", f"Không đọc được trạng thái Review Lister ({hint}).")
    elif lister["age_s"] is not None and lister["age_s"] > lister["stale_after"]:
        add(
            "bad",
            f"Review Lister im {_minutes(lister['age_s'])}: xem Scheduled Task "
            "'HaviGroup Review Lister' và C:\\HaviGroup\\logs\\review-lister.log trên hvg-pc.",
        )
    for error in lister["errors"]:
        add("warn", f"Lister: {error}")
    for card in cards:
        age = _seconds(parse_time(card["updated_at"]), now)
        if card["tone"] != "bad" or (age is not None and age > FAILED_RECENT):
            continue
        text = f"{card['task']}: {card['label']}"
        if card["machine"]:
            text += f" trên {card['machine']}"
        if card["note"]:
            text += f" — {card['note'][:200]}"
        add("bad", text, card["url"])
    for job in jobs:
        name = job["card"] or job["id"]
        if job["status"] == "queued" and (job["wait_s"] or 0) > QUEUED_TOO_LONG:
            add("warn", f"{name} chờ {job['machine'] or 'máy'} đã {_minutes(job['wait_s'])}: máy bận, hay agent tắt?")
        if job["status"] == "in_progress" and (job["run_s"] or 0) > RUNNING_TOO_LONG:
            add("warn", f"{name} đăng trên {job['machine']} đã {_minutes(job['run_s'])}, lâu hơn thường lệ.")
    for machine in machines:
        if not machine["retired"] and not machine["online"]:
            silent = f" {_minutes(machine['silent_s'])}" if machine["silent_s"] is not None else ""
            add("bad", f"{machine['label']} mất liên lạc{silent}.")
    out.sort(key=lambda item: item["tone"] != "bad")
    return out


def build_board(api: Any, checks: Optional["Checks"] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    sources: Dict[str, str] = {}

    def fetch(name: str, call: Callable[[], Any], default: Any) -> Any:
        try:
            value = call()
        except urllib.error.HTTPError as exc:
            sources[name] = f"HTTP {exc.code}"
        except (OSError, ValueError) as exc:
            sources[name] = mask(exc)[:200]
        else:
            sources[name] = ""
            return value
        return default

    raw_jobs = fetch("queue", api.copy_tasks, [])
    raw_machines = fetch("machines", api.machines, [])
    status = fetch("lister", lambda: api.lister_status(STATUS_FILE), {})
    if not isinstance(status, dict):
        status, sources["lister"] = {}, "tệp trạng thái không phải JSON object"

    jobs = [job_view(task, now, checks.get(str(task.get("id") or "")) if checks else None) for task in raw_jobs]
    jobs.sort(key=lambda job: job["created_at"], reverse=True)
    machines = [machine_view(row, now, jobs) for row in raw_machines]
    machines.sort(key=lambda machine: (bool(machine["retired"]), machine["id"]))
    lister_cards = [card for card in status.get("cards") or [] if isinstance(card, dict)]
    ledger = status.get("ledger")
    cards = card_views(lister_cards, jobs, ledger if isinstance(ledger, dict) else None)

    at = parse_time(status.get("at"))
    every = _int(status.get("every")) or 300
    lister = {
        "at": _iso(at),
        "age_s": _seconds(at, now),
        "every": every,
        # Tệp ghi cuối mỗi lượt; một lượt là thời gian quét cộng thời gian ngủ.
        "stale_after": 2 * every + 120,
        "errors": [mask(error)[:300] for error in status.get("errors") or []],
        "error": sources["lister"],
    }
    lister["tone"] = "bad" if lister["error"] or (lister["age_s"] or 0) > lister["stale_after"] else "ok"

    active = [machine for machine in machines if not machine["retired"]]
    kpi = {
        "review": sum(1 for card in cards if card["in_review"]) if not sources["lister"] else None,
        # Chỉ thẻ lister đã soi và thấy thiếu. Thẻ chưa tới lượt soi thì chưa biết.
        "declare": sum(1 for card in cards if card["stage"] == 0 and card["tone"] == "wait"),
        "unchecked": sum(1 for card in cards if card["stage"] == 0 and card["tone"] == "off"),
        "running": sum(1 for job in jobs if job["status"] in ("queued", "in_progress")),
        "drafts": sum(1 for card in cards if card["stage"] == 3),
        "broken": sum(1 for card in cards if card["tone"] == "bad"),
        "machines_on": sum(1 for machine in active if machine["online"]),
        "machines": len(active),
    }
    return {
        "at": _iso(now),
        "base": getattr(api, "base", ""),
        "sources": sources,
        "kpi": kpi,
        "alerts": board_alerts(lister, cards, jobs, machines, now),
        "lister": lister,
        "cards": cards,
        "jobs": jobs,
        "machines": machines,
    }


# ── soát bản nháp ─────────────────────────────────────────────────────


class Checks:
    """Việc soát đang chạy và kết quả, theo mã việc đăng. Mỗi máy soát một bản một lúc."""

    def __init__(
        self,
        api: Any,
        runner: Callable[..., dict] = check_draft,
        spawn: Optional[Callable[[Callable[[], None]], None]] = None,
    ) -> None:
        self.api = api
        self.runner = runner
        self.spawn = spawn or (lambda work: threading.Thread(target=work, daemon=True).start())
        self.lock = threading.Lock()
        self.items: Dict[str, dict] = {}

    def get(self, job_id: str) -> Optional[dict]:
        with self.lock:
            item = self.items.get(job_id)
            return dict(item) if item else None

    def start(self, job: Dict[str, Any]) -> str:
        """Bắt đầu soát. Trả lý do từ chối; chuỗi rỗng là đã nhận."""
        machine, sku = job["machine"], job["sku"]
        if job["status"] != "completed" or not job["saved"]:
            return "việc này chưa lưu bản nháp"
        if not machine or not sku:
            return "việc thiếu máy hoặc SKU"
        with self.lock:
            if any(item["state"] == "running" and item["machine"] == machine for item in self.items.values()):
                return f"{machine} đang soát một bản nháp khác"
            self.items[job["id"]] = {"state": "running", "machine": machine, "at": _iso(datetime.now(timezone.utc))}

        def work() -> None:
            try:
                report = self.runner(self.api, machine, sku, job["images"])
            except Exception as exc:  # luồng nền: lỗi phải hiện lên bảng, không được mất
                report = {"machine_id": machine, "sku": sku, "error": mask(exc)[:300]}
            with self.lock:
                self.items[job["id"]] = {
                    "state": "done",
                    "machine": machine,
                    "at": _iso(datetime.now(timezone.utc)),
                    "ok": report.get("ok"),
                    "photos": report.get("photos"),
                    "expected": report.get("expected"),
                    "has_video": report.get("has_video"),
                    "unsaved": report.get("unsaved"),
                    "draft_url": str(report.get("draft_url") or ""),
                    "error": mask(report.get("error") or ""),
                    "text": mask(format_report(report)),
                }

        self.spawn(work)
        return ""


# ── lệnh cũ ───────────────────────────────────────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    """Lệnh cũ ``python -m flow_web.listing_board``: nay mở bảng gộp ``flow_web.board``."""
    from .board import main as board_main

    return board_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
