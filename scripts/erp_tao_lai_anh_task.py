#!/usr/bin/env python3
"""Tạo lại bộ ảnh cho một thẻ ERP bằng app agenthavi đang chạy (bản mới).

    python scripts/erp_tao_lai_anh_task.py --task TASK-2026-06082
    python scripts/erp_tao_lai_anh_task.py --task TASK-2026-06082 --flow-web-url http://127.0.0.1:8000

Thẻ là **thẻ con idea** (có thẻ cha) → gọi ``POST /api/erp/idea-batch`` cho thẻ cha với
``child_task_ids=[thẻ]`` và ``include_done=true`` (chạy lại dù thẻ đã có ảnh Flow).
Thẻ là **thẻ cha idea** → chạy lại mọi thẻ con của nó.
Ảnh cũ trên thẻ không bị xoá ở đây; xoá trước bằng ``erp_anh_flow_theo_ngay.py``
nếu muốn thẻ chỉ còn bộ ảnh mới.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from flow_web.erp_meta import parent_task_id  # noqa: E402
from flow_web.main import load_local_env  # noqa: E402
from flow_web.service import FlowWebService  # noqa: E402
from flow_web.store import StateStore  # noqa: E402


def _post(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        raise SystemExit(f"App trả lỗi HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:500]}") from exc
    except URLError as exc:
        raise SystemExit(f"Không nối được app tại {url}: {exc.reason}. App agenthavi có đang chạy không?") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", required=True, help="Mã Task ERP, ví dụ TASK-2026-06082")
    parser.add_argument("--flow-web-url", default="http://127.0.0.1:8000", help="URL app agenthavi đang chạy")
    parser.add_argument("--count", type=int, default=0, help="Số ảnh mỗi idea; 0 = mặc định app (12 theo rule)")
    args = parser.parse_args()

    load_local_env()
    service = FlowWebService(StateStore())
    key, token = service._erp_credentials()
    if not key or not token:
        print("Chưa có ERP_API_KEY/ERP_API_SECRET.", file=sys.stderr)
        return 2
    task_id = service._normalize_erp_task_id(args.task)
    detail = service._erp_task_detail(key, token, task_id)
    parent = service._normalize_erp_task_id(parent_task_id(detail))
    children = [c for c in (detail.get("children") or []) if isinstance(c, dict)]

    if parent:
        payload = {"task_id": parent, "child_task_ids": [task_id], "include_done": True, "count": args.count}
        print(f"{task_id} là thẻ con của {parent}: chạy lại riêng thẻ này.")
    elif children:
        payload = {"task_id": task_id, "include_done": True, "count": args.count}
        print(f"{task_id} là thẻ cha có {len(children)} thẻ con: chạy lại tất cả thẻ con.")
    else:
        print(f"{task_id} không có thẻ cha lẫn thẻ con; idea-batch cần thẻ Idea (cha/con).", file=sys.stderr)
        return 2

    result = _post(f"{args.flow_web_url.rstrip('/')}/api/erp/idea-batch", payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Theo dõi tại {args.flow_web_url}/ (Jobs) hoặc GET {args.flow_web_url}/api/jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
