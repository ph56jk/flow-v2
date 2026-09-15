"""plan_erp_skus đọc ít thẻ bị cắt hơn.

``taskFull`` cắt ``subtasks`` ở khoảng 60 thẻ.  Thẻ bị cắt chỉ còn tên trong
``children``.  Trước đây bot đọc từng thẻ một: cụm 159 thẻ con tốn cả trăm
request, và chỉ một lượt 429 là dừng cả lượt đánh số.

Giờ bot đọc bảng trước, một request.  Chỉ đọc ``taskFull`` cho thẻ đã tới lúc
cấp mã, hoặc đã mang mã.  Thẻ còn ở Cần làm thì lấy luôn dòng trên bảng.
ERP giả lập, không gọi mạng.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from flow_web.service import FlowWebService
from flow_web.sku import ProductBook, SkuLedger

ROOT = "TASK-ROOT"
PROJECT = "PROJ-0087"
# Hai thẻ con nằm trong ``subtasks``, đã có mã.
SHOWN = {"TASK-C001": "OL_1_001", "TASK-C002": "OL_1_002"}
# Ba thẻ bị cắt: một ở Đang làm chưa có mã, một ở Cần làm, một đã có mã.
HID_WORK = "TASK-H-WORK"
HID_OPEN = "TASK-H-OPEN"
HID_SKU = "TASK-H-SKU"
HID_SKU_CODE = "OL_1_005"
STATUS = {HID_WORK: "Working", HID_OPEN: "Open", HID_SKU: "Open"}
META = {HID_WORK: "", HID_OPEN: "", HID_SKU: f"sku: {HID_SKU_CODE}"}


def _node(task_id: str, status: str, meta: str) -> Dict[str, Any]:
    return {
        "name": task_id,
        "parent_task": ROOT,
        "subject": task_id,
        "status": status,
        "project": PROJECT,
        "project_name": "punch needle ornament",
        "meta": meta,
        "subtasks": [],
    }


def _tree() -> Dict[str, Any]:
    hidden = [HID_WORK, HID_OPEN, HID_SKU]
    return {
        "root": {
            "name": ROOT,
            "subject": "Root",
            "meta": "product: Punch Needle Ornament",
            "project": PROJECT,
            "project_name": "punch needle ornament",
            "status": "Working",
            "children": [{"name": name} for name in [*SHOWN, *hidden]],
            "subtasks": [_node(name, "Working", f"sku: {code}") for name, code in SHOWN.items()],
        }
    }


def _board(rows_on_board: List[str]) -> Dict[str, Any]:
    columns: Dict[str, List[Dict[str, Any]]] = {"Working": [], "Open": []}
    for name in [*SHOWN, *rows_on_board]:
        status = STATUS.get(name, "Working")
        code = SHOWN.get(name) or (HID_SKU_CODE if name == HID_SKU else "")
        columns[status].append({"name": name, "parent_task": ROOT, "project": PROJECT, "custom_sku": code})
    return {"columns": [{"status": status, "tasks": tasks} for status, tasks in columns.items()]}


class PlanSkuItDocTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.full_calls: List[str] = []
        self.board_calls: List[str] = []
        self.board_error: Exception | None = None
        self.rows_on_board = [HID_WORK, HID_OPEN, HID_SKU]

    def _service(self) -> FlowWebService:
        tmp = Path(self._tmp.name)
        svc = FlowWebService.__new__(FlowWebService)
        svc._sku_ledger_path = lambda: tmp / "sku_ledger.json"
        svc._sku_book_path = lambda: tmp / "sku_book.json"
        svc._normalize_erp_task_id = lambda value: str(value or "").strip()
        svc._erp_assert_task_in_project = lambda *a, **k: None
        svc.load_sku_book = lambda *a, **k: ProductBook.from_mapping({"punch needle ornament": "OL"})

        def read_full(key, token, task_id, depth=0):
            self.full_calls.append(task_id)
            if task_id == ROOT:
                return _tree()
            return {"root": _node(task_id, STATUS[task_id], META[task_id])}

        def read_board(key, token, project=""):
            self.board_calls.append(project)
            if self.board_error is not None:
                raise self.board_error
            return _board(self.rows_on_board)

        svc._erp_task_full = read_full
        svc._erp_task_board = read_board
        return svc

    def _plan(self):
        ledger = SkuLedger()
        for code in SHOWN.values():
            ledger.observe_sku(code, PROJECT)
        return self._service().plan_erp_skus("key", "token", ROOT, ledger=ledger)

    def test_chi_doc_the_dang_lam_va_the_da_co_ma(self):
        plan = self._plan()

        self.assertEqual([ROOT, HID_WORK, HID_SKU], self.full_calls)
        self.assertEqual([PROJECT], self.board_calls, "bảng chỉ đọc một lần")
        work = next((item for item in plan.assignments if item.task_id == HID_WORK), None)
        self.assertIsNotNone(work, "thẻ Đang làm bị cắt vẫn phải nhận mã")
        self.assertFalse(work.kept)
        self.assertEqual("OL_1_006", str(work.sku), "không cấp trùng mã của thẻ bị cắt đã có mã")
        self.assertEqual([HID_WORK], [item.task_id for item in plan.changes])
        self.assertIn(HID_OPEN, {task_id for task_id, _ in plan.skipped}, "thẻ Cần làm vẫn được báo skipped")

    def test_doc_bang_hong_thi_doc_tung_the_nhu_cu(self):
        self.board_error = ConnectionError("ERP 429")

        plan = self._plan()

        self.assertEqual([ROOT, HID_WORK, HID_OPEN, HID_SKU], self.full_calls)
        self.assertIn(HID_OPEN, {task_id for task_id, _ in plan.skipped})
        work = next(item for item in plan.assignments if item.task_id == HID_WORK)
        self.assertEqual("OL_1_006", str(work.sku))

    def test_the_khong_co_tren_bang_thi_doc_chu_khong_doan(self):
        self.rows_on_board = [HID_WORK, HID_SKU]

        plan = self._plan()

        self.assertEqual([ROOT, HID_WORK, HID_OPEN, HID_SKU], self.full_calls)
        self.assertIn(HID_OPEN, {task_id for task_id, _ in plan.skipped})


if __name__ == "__main__":
    unittest.main()
