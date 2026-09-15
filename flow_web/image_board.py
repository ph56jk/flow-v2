"""Phần tạo ảnh của bảng điều khiển (``python -m flow_web.board``).

Đọc hai nguồn của flow-v2 trên hvg-pc (cổng 8000):

- ``GET /api/state``: bản rút gọn các job, profile Flow, đăng nhập Google, sức
  khoẻ dự án. Thường tốn chừng 50 ms. Lần đầu sau khi có job đổi thì tốn cỡ
  1 giây (quét thư mục dọn dẹp), mà suốt lúc ấy flow-v2 không trả lời ai. Nên
  bản đọc được giữ ``CACHE_SECONDS`` giây, ai mở bảng cũng dùng chung.
- ``data/state.json`` (``--flow-state-file``): tệp flow-v2 ghi lại mỗi lần job
  đổi. Xem giờ sửa tệp thì không tốn gì; tệp đổi mới đọc lại, cách nhau ít nhất
  ``READ_GAP`` giây. Danh sách job lấy ở đây, nên bảng thấy job đổi sau ~2 giây
  mà không bắt flow-v2 làm thêm việc gì.

Không gọi ``/api/jobs``: nặng 24 MB. Không bao giờ gọi ``/api/credits`` theo
nhịp: nó mở trình duyệt và hay bị 429.

Máy tạo ảnh DESKTOP-DPTR5BH (hvg-img) chạy flow_web riêng, chỉ nghe 127.0.0.1:
bảng này không thấy các worker 3169-3171 ấy.

Cách đọc bảng: docs/bang-dieu-khien.md.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .listing_board import VN, _int, _iso, _minutes, _seconds, parse_time
from .listing_watch import mask

DEFAULT_FLOW_BASE = "http://127.0.0.1:8000"
ERP_TASK_URL = "https://erp.havigroup.llc/app/task/"
CACHE_SECONDS = 15
READ_GAP = 2.0  # state.json: hai lần đọc cách nhau ít nhất chừng này giây

# Ngưỡng báo, tính bằng giây.
SILENT_TOO_LONG = 1200  # job đang chạy mà 20 phút không có tín hiệu nào
RECENT = 86400  # job hỏng quá một ngày thì thôi báo
ALERT_JOBS = 10  # quá số này thì gộp phần còn lại thành một dòng

# Câu lỗi quota viết không dấu. error_snapshot lại xếp nó vào "lỗi browser",
# nên phải nhận ra bằng chữ.
QUOTA_TEXT = "het quota"
# flow-v2 ghi giờ mở khoá theo giờ máy hvg-pc, tức giờ VN.
QUOTA_UNTIL = re.compile(r"Khoa toi (\d{1,2}:\d{2} \d{1,2}/\d{1,2})")

ACTIVE = ("running", "polling")
STATUS = {
    "queued": ("wait", "chờ chạy"),
    "running": ("run", "đang tạo"),
    "polling": ("run", "đang chạy"),
    "completed": ("ok", "xong"),
    "failed": ("bad", "hỏng"),
    "error": ("bad", "lỗi"),
    "interrupted": ("wait", "bị ngắt"),
    "cancelled": ("off", "đã huỷ"),
}

# Tone của project_health trong flow-v2 đổi sang tone của bảng.
HEALTH_TONE = {
    "success": "ok", "positive": "ok", "good": "ok", "ok": "ok",
    "warning": "wait", "caution": "wait", "attention": "wait",
    "danger": "bad", "error": "bad", "critical": "bad", "negative": "bad", "bad": "bad",
    "info": "run", "active": "run",
}


def slim_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Chỉ giữ những gì ``image_job_view`` đọc. Job thật mang cả log lẫn prompt dài."""

    def part(value: Any, keys: Tuple[str, ...]) -> Dict[str, Any]:
        value = value if isinstance(value, dict) else {}
        return {key: value[key] for key in keys if key in value}

    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    review = result.get("erp_review") if isinstance(result.get("erp_review"), dict) else {}
    items = review.get("items")
    logs = [log for log in job.get("logs") or [] if isinstance(log, dict)]
    artifacts = job.get("artifacts")
    return {
        **part(job, ("id", "type", "status", "title", "error", "created_at", "updated_at")),
        "input": part(job.get("input"), ("erp_task_id", "erp_project_id", "count", "aspect")),
        "result": {"erp_review": {"items": {key: {} for key in items}}} if isinstance(items, dict) else {},
        "progress_snapshot": part(job.get("progress_snapshot"), ("stage_label", "detail", "last_signal_at")),
        "logs": [{"message": logs[-1].get("message")}] if logs else [],
        "artifacts": [{} for _ in artifacts] if isinstance(artifacts, list) else artifacts,
    }


class JobsFile:
    """Danh sách job đọc thẳng từ state.json của flow-v2, chỉ đọc, không bao giờ ghi.

    flow-v2 ghi đè cả tệp tại chỗ, nên có lúc đọc trúng tệp đang ghi dở. Khi ấy
    giữ bản đọc được lần trước; tệp đổi ngay trong lúc đọc cũng không tin.
    """

    def __init__(
        self,
        path: Any,
        clock: Callable[[], float] = time.monotonic,
        gap: float = READ_GAP,
        read: Optional[Callable[[Path], bytes]] = None,
    ) -> None:
        self.path = Path(path)
        self.clock = clock
        self.gap = gap
        self.read = read or Path.read_bytes
        self.lock = threading.Lock()
        self.seen: Optional[Tuple[int, int]] = None  # (giờ sửa, cỡ) của bản đang giữ
        self.read_at: Optional[float] = None
        self.jobs: Optional[List[Dict[str, Any]]] = None

    def _sign(self) -> Tuple[int, int]:
        info = os.stat(self.path)
        return info.st_mtime_ns, info.st_size

    def load(self) -> Optional[List[Dict[str, Any]]]:
        with self.lock:
            try:
                sign = self._sign()
            except OSError:
                self.seen = self.jobs = None
                return None
            now = self.clock()
            if sign == self.seen or (self.read_at is not None and now - self.read_at < self.gap):
                return self.jobs
            self.read_at = now
            try:
                raw = self.read(self.path)
                if self._sign() != sign:
                    return self.jobs
                jobs = json.loads(raw).get("jobs")
            except (OSError, ValueError, AttributeError):
                return self.jobs
            if not isinstance(jobs, list):
                return self.jobs
            self.seen = sign
            self.jobs = [slim_job(job) for job in jobs if isinstance(job, dict)]
            return self.jobs


def _newest(jobs: Any) -> datetime:
    times = [parse_time(job.get("updated_at")) for job in jobs or [] if isinstance(job, dict)]
    return max((at for at in times if at), default=datetime.min.replace(tzinfo=timezone.utc))


class FlowApi:
    """Đọc flow-v2 qua HTTP. Mỗi lần đọc được thì giữ lại ``CACHE_SECONDS`` giây.

    Có ``jobs_file`` thì danh sách job lấy từ state.json, miễn là tệp không cũ
    hơn bản ``/api/state`` (bảng trỏ nhầm tệp thì đừng hiện job cũ mãi).
    """

    def __init__(
        self,
        base: str = DEFAULT_FLOW_BASE,
        timeout: float = 25.0,
        fetch: Optional[Callable[[str], Any]] = None,
        clock: Callable[[], float] = time.monotonic,
        jobs_file: Optional[JobsFile] = None,
    ) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.fetch = fetch or self._get
        self.clock = clock
        self.jobs_file = jobs_file
        self.lock = threading.Lock()
        self.cached: Optional[tuple] = None

    def _get(self, path: str) -> Any:
        request = urllib.request.Request(self.base + path, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _fetch_state(self) -> Dict[str, Any]:
        # Giữ khoá trong lúc gọi: hai người mở bảng cùng lúc thì flow-v2 chỉ phải dựng một lần.
        with self.lock:
            if self.cached and self.clock() - self.cached[0] < CACHE_SECONDS:
                return self.cached[1]
            data = self.fetch("/api/state")
            if not isinstance(data, dict):
                raise ValueError("/api/state không trả JSON object")
            self.cached = (self.clock(), data)
            return data

    def state(self) -> Dict[str, Any]:
        data = self._fetch_state()
        jobs = self.jobs_file.load() if self.jobs_file else None
        if jobs is not None and _newest(jobs) >= _newest(data.get("jobs")):
            return {**data, "jobs": jobs}
        return data


# ── từng job ──────────────────────────────────────────────────────────


def _title(raw: Any, task: str) -> str:
    title = mask(raw or "")
    if task:
        title = re.sub(r"\s*\(" + re.escape(task) + r"\)\s*$", "", title)
    # Thẻ ERP tên "Idea 39" thì job thành "Idea Idea 39".
    return re.sub(r"^(\w+) \1\b", r"\1", title).strip()


def image_job_view(job: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    status = str(job.get("status") or "")
    tone, label = STATUS.get(status, ("off", status or "?"))
    data = job.get("input") or {}
    result = job.get("result") or {}
    progress = job.get("progress_snapshot") or {}
    error = str(job.get("error") or "")
    quota = status == "failed" and QUOTA_TEXT in error.lower()
    if quota:
        tone, label = "wait", "hết quota"
    created = parse_time(job.get("created_at"))
    updated = parse_time(job.get("updated_at"))
    signal = parse_time(progress.get("last_signal_at")) or updated
    active = status in ACTIVE
    task = str(data.get("erp_task_id") or "")
    review = (result.get("erp_review") or {}).get("items")
    logs = [log for log in job.get("logs") or [] if isinstance(log, dict)]
    artifacts = job.get("artifacts")
    shown_error = ""
    if status in ("failed", "error", "interrupted", "cancelled"):
        shown_error = mask(error or progress.get("detail") or "")[:400]
    return {
        "id": str(job.get("id") or ""),
        "type": str(job.get("type") or ""),
        "status": status,
        "label": label,
        "tone": tone,
        "quota": quota,
        "title": _title(job.get("title"), task),
        "task": task,
        "task_url": ERP_TASK_URL + task if task else "",
        "project": str(data.get("erp_project_id") or ""),
        "requested": _int(data.get("count")),
        "made": len(artifacts) if isinstance(artifacts, list) else None,
        "sent": len(review) if isinstance(review, dict) else 0,
        "aspect": str(data.get("aspect") or ""),
        "stage": mask(progress.get("stage_label") or "")[:120],
        "detail": mask(progress.get("detail") or "")[:300],
        "error": shown_error,
        "last_log": mask(logs[-1].get("message") or "")[:300] if logs else "",
        "created_at": _iso(created),
        "updated_at": _iso(updated),
        "signal_at": _iso(signal),
        "run_s": _seconds(created, now if active or status == "queued" else updated),
        "silent_s": max(0, _seconds(signal, now) or 0) if active and signal else None,
    }


def _rank(job: Dict[str, Any]) -> int:
    if job["status"] in ACTIVE:
        return 0
    return 1 if job["status"] == "queued" else 2


# ── cả phần ───────────────────────────────────────────────────────────


def image_alerts(
    jobs: List[Dict[str, Any]],
    profiles: List[Dict[str, Any]],
    auth: Optional[bool],
    quota_until: str,
    now: datetime,
) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []

    def add(tone: str, text: str, link: str = "") -> None:
        out.append({"tone": tone, "text": text, "link": link})

    def recent(job: Dict[str, Any]) -> bool:
        age = _seconds(parse_time(job["updated_at"]), now)
        return age is not None and age <= RECENT

    if auth is False:
        add("bad", "Flow chưa đăng nhập Google: mở flow-v2 trên hvg-pc và đăng nhập lại. Job mới sẽ hỏng tới lúc ấy.")

    blocked = [profile["label"] for profile in profiles if profile["quota_blocked"]]
    quota_jobs = [job for job in jobs if job["quota"] and recent(job)]
    if profiles and len(blocked) == len(profiles):
        until = f"khoá tới {quota_until} giờ VN" if quota_until else "thường mở lại khoảng 14:00 giờ VN"
        text = f"Hết quota Flow ({', '.join(blocked)}), {until}."
        if quota_jobs:
            text += f" {len(quota_jobs)} job đã hỏng vì quota."
        add("warn", text + " Thẻ có gắn bot tự xếp lại sau giờ ấy; thẻ chạy tay phải bấm lại.")
    elif blocked:
        add("warn", f"Hết quota ở {', '.join(blocked)}; còn chạy được bằng profile khác.")
    elif quota_jobs:
        add(
            "warn",
            f"{len(quota_jobs)} job hỏng vì hết quota trong 24 giờ qua. Quota đã mở lại: "
            "thẻ có gắn bot tự xếp lại (15 phút một lượt), thẻ chạy tay phải bấm lại.",
        )

    failed = [job for job in jobs if job["tone"] == "bad" and recent(job)]
    for job in failed[:ALERT_JOBS]:
        name = job["task"] or job["title"] or job["id"]
        add("bad", f"{name}: {job['label']} — {job['error'][:200] or 'không có câu lỗi'}", job["task_url"])
    if len(failed) > ALERT_JOBS:
        add("bad", f"… và {len(failed) - ALERT_JOBS} job hỏng nữa trong 24 giờ: xem tab Job, lọc Hỏng.")

    interrupted = [job for job in jobs if job["status"] == "interrupted" and recent(job)]
    if interrupted:
        add(
            "warn",
            f"{len(interrupted)} job bị ngắt vì flow-v2 khởi động lại giữa chừng. "
            "Xem mục Replay trong flow-v2 để chạy lại.",
        )

    for job in jobs:
        if job["silent_s"] is not None and job["silent_s"] > SILENT_TOO_LONG:
            name = job["task"] or job["title"] or job["id"]
            stage = f" ở bước '{job['stage']}'" if job["stage"] else ""
            add("warn", f"{name} không có tín hiệu {_minutes(job['silent_s'])}{stage}: kẹt?", job["task_url"])

    out.sort(key=lambda item: item["tone"] != "bad")
    return out


def _health(raw: Any) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}

    def tone(value: Any) -> str:
        return HEALTH_TONE.get(str(value or "").lower(), "off")

    return {
        "status_label": mask(raw.get("status_label") or ""),
        "headline": mask(raw.get("headline") or ""),
        "summary": mask(raw.get("summary") or ""),
        "last_activity_at": _iso(parse_time(raw.get("last_activity_at"))),
        "signals": [
            {
                "tone": tone(item.get("tone")),
                "label": mask(item.get("label") or ""),
                "status_label": mask(item.get("status_label") or ""),
                "detail": mask(item.get("detail") or "")[:300],
            }
            for item in raw.get("trust_signals") or []
            if isinstance(item, dict)
        ],
        "timeline": [
            {
                "tone": tone(item.get("tone")),
                "title": mask(item.get("title") or ""),
                "detail": mask(item.get("detail") or "")[:300],
                "at": _iso(parse_time(item.get("at"))),
            }
            for item in (raw.get("timeline") or [])[:10]
            if isinstance(item, dict)
        ],
    }


def build_images(flow: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    sources: Dict[str, str] = {}
    state: Dict[str, Any] = {}
    if flow is None:
        sources["state"] = "bảng chưa được trỏ tới flow-v2"
    else:
        try:
            state = flow.state()
        except urllib.error.HTTPError as exc:
            sources["state"] = f"HTTP {exc.code}"
        except (OSError, ValueError) as exc:
            sources["state"] = mask(exc)[:200]
        else:
            sources["state"] = ""

    jobs = [image_job_view(job, now) for job in state.get("jobs") or [] if isinstance(job, dict)]
    jobs.sort(key=lambda job: job["updated_at"], reverse=True)
    jobs.sort(key=_rank)

    runtime = (state.get("integrations") or {}).get("runtime") or {}
    profiles = [
        {
            "label": mask(profile.get("label") or ""),
            "active": bool(profile.get("active")),
            "quota_blocked": bool(profile.get("quota_blocked")),
        }
        for profile in runtime.get("flow_profiles") or []
        if isinstance(profile, dict)
    ]
    auth_raw = (state.get("auth") or {}).get("authenticated") if isinstance(state.get("auth"), dict) else None
    auth = bool(auth_raw) if auth_raw is not None else None

    quota_until = ""
    if profiles and all(profile["quota_blocked"] for profile in profiles):
        for job in jobs:  # đã xếp mới trước: lấy giờ khoá của lần hỏng gần nhất
            found = QUOTA_UNTIL.search(job["error"]) if job["quota"] else None
            if found:
                quota_until = found.group(1)
                break

    today = now.astimezone(VN).date()
    done_today = [
        job
        for job in jobs
        if job["status"] == "completed"
        and job["updated_at"]
        and parse_time(job["updated_at"]).astimezone(VN).date() == today
    ]
    day_ago = _iso(now - timedelta(seconds=RECENT))
    kpi = {
        "active": sum(1 for job in jobs if job["status"] in ACTIVE),
        "queued": sum(1 for job in jobs if job["status"] == "queued"),
        "done_today": len(done_today),
        "images_today": sum(job["made"] or 0 for job in done_today),
        # Chỉ tính trong các job flow-v2 còn giữ: là số tối thiểu.
        "failed": sum(1 for job in jobs if job["tone"] == "bad" and job["updated_at"] >= day_ago),
        "quota_failed": sum(1 for job in jobs if job["quota"] and job["updated_at"] >= day_ago),
        "interrupted": sum(1 for job in jobs if job["status"] == "interrupted" and job["updated_at"] >= day_ago),
        "profiles": len(profiles),
        "profiles_open": sum(1 for profile in profiles if not profile["quota_blocked"]),
        "jobs": len(jobs),
    }
    return {
        "at": _iso(now),
        "base": getattr(flow, "base", ""),
        "sources": sources,
        "kpi": kpi,
        "auth": auth,
        "profiles": profiles,
        "quota_until": quota_until,
        "alerts": image_alerts(jobs, profiles, auth, quota_until, now) if not sources["state"] else [],
        "health": _health(state.get("project_health")),
        "jobs": jobs,
    }
