#!/usr/bin/env python3
"""Kiểm kê (và, khi được bảo, xoá) ảnh do Flow đăng lên ERP trong một ngày.

Chạy trên máy đang cài agenthavi (đọc ERP key/secret từ ``.env.local``):

    python scripts/erp_anh_flow_theo_ngay.py --day 2026-09-10            # chỉ liệt kê
    python scripts/erp_anh_flow_theo_ngay.py --day 2026-09-10 --delete   # xoá thật

Ảnh "do Flow đăng" = comment mang dấu FLOW_V2_REVIEW (ảnh chờ duyệt 👍/👎) hoặc
FLOW_V2_ARTIFACT (ảnh đã archive) trong ``meta``/thân comment. Ngày lấy theo trường
``creation`` của comment (giờ máy chủ ERP). Xoá đi qua đúng đường ERP web UI dùng
(``hvg_workspace.api.delete_task_comment``) nên ảnh đính kèm mất theo comment và
KHÔNG khôi phục được - vì thế mặc định chỉ liệt kê, và ``--delete`` hỏi xác nhận.

Sau khi xoá, muốn tạo lại ảnh cho một thẻ: ``python scripts/erp_tao_lai_anh_task.py --task TASK-...``.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from flow_web.main import load_local_env  # noqa: E402  (đọc .env.local như app)
from flow_web.service import FlowWebService  # noqa: E402
from flow_web.store import StateStore  # noqa: E402

MARKERS = ("FLOW_V2_REVIEW", "FLOW_V2_ARTIFACT")


def _open_tasks(service: FlowWebService, key: str, token: str, project_id: str) -> List[Dict[str, Any]]:
    payload = service._erp_get_json(
        f"boards/{project_id}/cards",
        key,
        token,
        fields={"fields": "id,name,idList,closed", "filter": "open"},
    )
    return [card for card in (payload if isinstance(payload, list) else []) if isinstance(card, dict) and not card.get("closed")]


def _flow_comments(service: FlowWebService, detail: Dict[str, Any], day: str) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    for comment in detail.get("comments") or []:
        if not isinstance(comment, dict):
            continue
        markers = service._erp_comment_markers(comment)
        if not any(marker in markers for marker in MARKERS):
            continue
        creation = str(comment.get("creation") or comment.get("modified") or "").strip()
        if day and not creation.startswith(day):
            continue
        attachments = [
            str(item.get("file_url") or item.get("url") or "")
            for item in (comment.get("attachments") or [])
            if isinstance(item, dict)
        ]
        found.append(
            {
                "comment": str(comment.get("name") or ""),
                "creation": creation,
                "marker": "REVIEW" if "FLOW_V2_REVIEW" in markers else "ARTIFACT",
                "attachments": attachments,
                "replies": len(comment.get("replies") or []),
            }
        )
    return found


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--day", required=True, help="Ngày theo giờ ERP, dạng YYYY-MM-DD (ví dụ 2026-09-10)")
    parser.add_argument("--project", default="", help="Mã dự án ERP; bỏ trống = ERP_PROJECT_ID trong .env.local")
    parser.add_argument("--task", action="append", default=[], help="Chỉ xét (các) Task này thay vì cả bảng")
    parser.add_argument("--delete", action="store_true", help="Xoá thật các comment tìm thấy (hỏi xác nhận)")
    parser.add_argument("--yes", action="store_true", help="Không hỏi xác nhận khi --delete")
    parser.add_argument("--json", action="store_true", help="In JSON thay vì bảng")
    args = parser.parse_args()

    load_local_env()
    store = StateStore()
    service = FlowWebService(store)
    key, token = service._erp_credentials()
    if not key or not token:
        print("Chưa có ERP_API_KEY/ERP_API_SECRET (.env.local hoặc cấu hình app).", file=sys.stderr)
        return 2
    project_id = service._erp_required_project_id(args.project)

    if args.task:
        task_ids = [service._normalize_erp_task_id(item) for item in args.task]
    else:
        task_ids = [
            str(card.get("id") or "").strip()
            for card in await asyncio.to_thread(_open_tasks, service, key, token, project_id)
        ]
    task_ids = [item for item in task_ids if item]

    report: List[Dict[str, Any]] = []
    for task_id in task_ids:
        try:
            detail = await asyncio.to_thread(service._erp_task_detail, key, token, task_id)
        except Exception as exc:  # noqa: BLE001 - one unreadable task must not stop the inventory
            print(f"[bỏ qua] {task_id}: {exc}", file=sys.stderr)
            continue
        comments = _flow_comments(service, detail, args.day)
        if comments:
            report.append({"task": task_id, "subject": str(detail.get("subject") or ""), "comments": comments})
        # Thẻ con (idea) mang ảnh riêng: taskDetail của thẻ cha liệt kê chúng.
        for child in detail.get("children") or []:
            child_id = service._normalize_erp_task_id(str((child or {}).get("name") or "")) if isinstance(child, dict) else ""
            if child_id and child_id not in task_ids:
                task_ids.append(child_id)

    total = sum(len(item["comments"]) for item in report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for item in report:
            print(f"{item['task']}  {item['subject'][:60]}")
            for comment in item["comments"]:
                print(f"    {comment['comment']:<24} {comment['creation']:<20} {comment['marker']:<8} {len(comment['attachments'])} file, {comment['replies']} trả lời")
        print(f"\nTổng: {total} comment ảnh Flow trong ngày {args.day} trên {len(report)} thẻ (dự án {project_id}).")
    if not args.delete or not total:
        return 0

    if not args.yes:
        answer = input(f"XOÁ {total} comment (kèm ảnh) trên ERP? Không khôi phục được. Gõ 'xoa' để tiếp tục: ").strip().lower()
        if answer != "xoa":
            print("Không xoá gì.")
            return 1
    deleted = 0
    for item in report:
        for comment in item["comments"]:
            try:
                await asyncio.to_thread(service._erp_delete_task_comment, key, token, item["task"], comment["comment"])
                deleted += 1
                print(f"đã xoá {item['task']} / {comment['comment']}")
            except Exception as exc:  # noqa: BLE001
                print(f"KHÔNG xoá được {item['task']} / {comment['comment']}: {exc}", file=sys.stderr)
    print(f"Đã xoá {deleted}/{total} comment.")
    return 0 if deleted == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
