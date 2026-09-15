#!/usr/bin/env python3
"""Gỡ một cờ reCAPTCHA manual của Flow v2 một cách có kiểm soát.

Mặc định chỉ kiểm tra và in thay đổi sẽ thực hiện. Chỉ ``--apply`` mới tạo bản
sao lưu và thay thế state file. Luôn dừng flow-v2 trước khi dùng ``--apply``;
script không tự dừng hoặc khởi động lại service.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RECAPTCHA_RESULT_KEY = "flow_upsample_recaptcha"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ManualFlagError(ValueError):
    """The requested record is absent, malformed, or not manually blocked."""


def default_state_file() -> Path:
    """Resolve the same default data location as ``flow_web.paths``."""
    raw_data_dir = os.environ.get("FLOW_DATA_DIR", "").strip()
    if not raw_data_dir:
        return PROJECT_ROOT / "data" / "state.json"
    data_dir = Path(os.path.expandvars(os.path.expanduser(raw_data_dir)))
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    return data_dir.resolve() / "state.json"


def state_key(task_id: str, job_id: str, media_id: str) -> str:
    return "::".join((task_id.strip(), job_id.strip(), media_id.strip()))


def load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManualFlagError(f"Không tìm thấy state file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ManualFlagError(f"State file không phải JSON hợp lệ: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ManualFlagError("State JSON phải là object ở cấp cao nhất.")
    return payload


def target_record(
    payload: dict[str, Any], *, task_id: str, job_id: str, media_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
    """Return the job/result/map/record for exactly one manually blocked media."""
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise ManualFlagError("State JSON không có mảng jobs hợp lệ.")
    matches = [job for job in jobs if isinstance(job, dict) and str(job.get("id") or "") == job_id]
    if not matches:
        raise ManualFlagError(f"Không tìm thấy job_id {job_id!r} trong state file.")
    if len(matches) > 1:
        raise ManualFlagError(f"State file có nhiều job trùng id {job_id!r}; từ chối sửa mơ hồ.")
    job = matches[0]
    result = job.get("result")
    if not isinstance(result, dict):
        raise ManualFlagError(f"Job {job_id!r} không có result hợp lệ.")
    recaptcha = result.get(RECAPTCHA_RESULT_KEY)
    if not isinstance(recaptcha, dict) or not isinstance(recaptcha.get("media"), dict):
        raise ManualFlagError(f"Job {job_id!r} không có {RECAPTCHA_RESULT_KEY}.media hợp lệ.")
    media_records = recaptcha["media"]
    key = state_key(task_id, job_id, media_id)
    record = media_records.get(key)
    if not isinstance(record, dict):
        raise ManualFlagError(f"Không tìm thấy record chính xác {key!r}.")
    mismatches = {
        field: (str(record.get(field) or ""), expected)
        for field, expected in (("task_id", task_id), ("job_id", job_id), ("media_id", media_id))
        if str(record.get(field) or "") != expected
    }
    if mismatches:
        details = ", ".join(f"{field}={actual!r}" for field, (actual, _expected) in mismatches.items())
        raise ManualFlagError(f"Record {key!r} không khớp bộ ba được yêu cầu: {details}.")
    if not (bool(record.get("needs_manual_review")) or bool(record.get("next_retry_at"))):
        raise ManualFlagError(f"Record {key!r} không đang bị manual block; từ chối xoá bộ đếm tạm.")
    return job, result, recaptcha, record, key


def remove_record(
    payload: dict[str, Any], *, task_id: str, job_id: str, media_id: str
) -> dict[str, Any]:
    """Remove only the selected block and keep all other result data intact."""
    _job, result, recaptcha, _record, key = target_record(
        payload, task_id=task_id, job_id=job_id, media_id=media_id
    )
    media_records = recaptcha["media"]
    del media_records[key]
    if media_records:
        return payload
    # No manual records remain in the job, so remove only this namespaced
    # result entry—not the job, its artifacts, logs, approvals, or ERP review.
    result.pop(RECAPTCHA_RESULT_KEY, None)
    return payload


def backup_path_for(state_file: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = state_file.with_name(f"{state_file.name}.bak-clear-recaptcha-{stamp}")
    suffix = 1
    while candidate.exists():
        candidate = state_file.with_name(f"{state_file.name}.bak-clear-recaptcha-{stamp}-{suffix}")
        suffix += 1
    return candidate


def backup_and_replace(state_file: Path, payload: dict[str, Any]) -> Path:
    """Copy the original then atomically replace it with validated JSON."""
    backup = backup_path_for(state_file)
    shutil.copy2(state_file, backup)
    source_mode = stat.S_IMODE(state_file.stat().st_mode)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=state_file.parent, prefix=f".{state_file.name}.", delete=False
        ) as temporary:
            temp_name = temporary.name
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temp_name, source_mode)
        os.replace(temp_name, state_file)
    except Exception:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
        raise
    return backup


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id", help="ERP task id, ví dụ TASK-2026-02120")
    parser.add_argument("job_id", help="Flow job id chứa record manual")
    parser.add_argument("media_id", help="UUID media Flow cần gỡ cờ")
    parser.add_argument(
        "--state-file",
        type=Path,
        default=default_state_file(),
        help="state.json cần đọc (mặc định theo FLOW_DATA_DIR hoặc data/state.json)",
    )
    parser.add_argument("--apply", action="store_true", help="Ghi thật; mặc định chỉ dry-run")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    task_id = str(args.task_id or "").strip()
    job_id = str(args.job_id or "").strip()
    media_id = str(args.media_id or "").strip()
    if not task_id or not job_id or not media_id:
        print("task_id, job_id và media_id đều không được để trống.", file=sys.stderr)
        return 2
    state_file = Path(args.state_file).expanduser().resolve()
    try:
        payload = load_state(state_file)
        _job, _result, _recaptcha, record, key = target_record(
            payload, task_id=task_id, job_id=job_id, media_id=media_id
        )
    except ManualFlagError as exc:
        print(f"Từ chối: {exc}", file=sys.stderr)
        return 2

    print(f"State file: {state_file}")
    print(f"Record bị nhắm: {key}")
    print(
        "Hiện tại: "
        f"rejected_count={record.get('rejected_count')!r}, "
        f"needs_manual_review={record.get('needs_manual_review')!r}, "
        f"next_retry_at={record.get('next_retry_at')!r}"
    )
    if not args.apply:
        print("DRY-RUN: sẽ xoá đúng record này; chưa ghi state file.")
        print("Chỉ sau khi dừng flow-v2 và kiểm tra backup, chạy lại cùng tham số kèm --apply.")
        return 0

    try:
        updated = remove_record(payload, task_id=task_id, job_id=job_id, media_id=media_id)
        backup = backup_and_replace(state_file, updated)
    except (ManualFlagError, OSError, TypeError, ValueError) as exc:
        print(f"Không ghi state file: {exc}", file=sys.stderr)
        return 2
    print(f"Đã xoá record manual. Backup nguyên trạng: {backup}")
    print("State file đã được thay atomically. Chỉ khởi động lại flow-v2 sau khi tự kiểm tra state.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
