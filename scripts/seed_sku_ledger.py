#!/usr/bin/env python3
"""Nạp sổ số SKU từ những mã đang nằm trên bảng ERP. Chạy một lần mỗi máy.

Sổ (``data/sku_ledger.json``) là trí nhớ nối các cây thẻ rời nhau lại. Cho
mỗi tên SKU nó giữ ba thứ: số nhận dạng dự án cao nhất đã phát, số nhận dạng
idea cao nhất đã phát, và — không kém quan trọng — **dự án nào là dự án thứ
mấy** (mã dự án ERP → số giữa của mã). Thiếu mốc số thì hai thẻ gốc cùng khai
một ``product`` cùng mở màn ở ``BT_1_001``; thiếu ánh xạ dự án thì cùng một
bảng mỗi lượt lại nhận một số dự án mới, và ``BT_3_051`` mọc ra ngay dưới
``BT_1_050`` của cùng dự án.

Sổ tự học lại từ mã trên thẻ mỗi lần đánh số — học cả mốc lẫn ánh xạ, vì mã
đã in ra là lời khai chắc nhất về việc dự án nào mang số mấy — nên nó tự lành
sau khi mất. Cái nó *không* tự lành được là cây đầu tiên trên một máy vừa
dựng: nếu cây ấy còn trắng thì sổ trống, nó cấp lại đúng những số đang nằm
trên một cây anh em chưa từng đọc và coi một dự án đã có số là dự án mới
toanh. Chạy script này sau khi cài, trước khi bật bot.

Chỉ đọc: không ghi gì lên ERP.

    .venv/bin/python -m scripts.seed_sku_ledger                # mọi bảng được phép
    .venv/bin/python -m scripts.seed_sku_ledger PROJ-0170      # đúng một bảng
"""

from __future__ import annotations

import json
import logging
import sys

from flow_web.main import load_local_env
from flow_web.service import FlowWebService
from flow_web.store import StateStore


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_local_env()
    service = FlowWebService(StateStore())
    summary = service.seed_sku_ledger(projects=argv)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
