"""Soát d48d3dc: bảng nhớ của lượt đánh số không rò, không làm lỏng hàng rào.

Dùng lại ERP giả của ``tests/test_sku_nhanh_moi_the.py``: ``_erp_graphql``,
bộ nhịp và hàng rào dự án đều là code thật, đồng hồ giả.
"""

from __future__ import annotations

import json
import threading
import unittest
from typing import Any, Callable, Dict, List

from flow_web.service import FlowWebService
from tests.test_sku_nhanh_moi_the import K_OR, PROJECT, ROOT, DongHoGia, ErpGia, child_id, erp_gia


class _ErpMoc(ErpGia):
    """ERP giả gọi ``moc(task)`` ngay trước mỗi lượt ghi mã."""

    def __init__(self, clock: DongHoGia, working: List[int], moc: Callable[[str], None]) -> None:
        super().__init__(clock, working)
        self._moc = moc

    def urlopen(self, request: Any, timeout: Any = None) -> Any:
        body = json.loads(request.data.decode("utf-8"))
        if body["operationName"] == "UpdateTaskMeta":
            self._moc(body["variables"]["task"])
        return super().urlopen(request, timeout)


class BangNhoTests(unittest.TestCase):
    def test_bang_nho_chi_song_trong_luot(self):
        # Hết lượt là hết bảng nhớ, kể cả lượt ném lỗi.  Lượt sau đọc bảng tươi.
        clock = DongHoGia()
        erp = ErpGia(clock, [1, 2])
        with erp_gia(clock, erp, K_OR) as svc:
            self.assertIsNone(svc._erp_board_memo_boards())
            result = FlowWebService.fill_task_skus(svc, ROOT)
            self.assertEqual(2, len(result["written"]), result["failed"])
            self.assertIsNone(svc._erp_board_memo_boards())

            erp.nodes[child_id(3)]["status"] = "Working"
            erp.calls.clear()
            FlowWebService.fill_task_skus(svc, ROOT)
            self.assertGreaterEqual(erp.calls["TaskBoard"], 1, "lượt sau không được dùng bảng của lượt trước")

            def hong(*a: Any, **kw: Any) -> Dict[str, Any]:
                raise RuntimeError("cây hỏng")

            svc._erp_task_full = hong
            with self.assertRaises(RuntimeError):
                FlowWebService.fill_task_skus(svc, ROOT)
            self.assertIsNone(svc._erp_board_memo_boards())

    def test_bang_nho_rieng_tung_luong(self):
        # Làn nhanh gọi ``fill`` từ luồng của ``asyncio.to_thread``.  Luồng khác
        # hỏi hàng rào cùng lúc thì không được thấy bảng nhớ của lượt này.
        clock = DongHoGia()
        seen: Dict[str, Any] = {}

        def moc(task: str) -> None:
            seen["luong_nay"] = svc._erp_board_memo_boards()
            other = threading.Thread(target=lambda: seen.update(luong_khac=svc._erp_board_memo_boards()))
            other.start()
            other.join()

        erp = _ErpMoc(clock, [1], moc)
        with erp_gia(clock, erp, K_OR) as svc:
            FlowWebService.fill_task_skus(svc, ROOT)
        self.assertIn(PROJECT, seen["luong_nay"])
        self.assertIsNone(seen["luong_khac"])

    def test_the_sang_du_an_la_giua_luot_khong_nhan_ma(self):
        # Hàng rào chạy trước mỗi lần ghi để chặn thẻ không còn thuộc dự án
        # được phép.  Thẻ bị kéo sang dự án lạ sau lúc đọc bảng đầu lượt, trước
        # lúc tới lượt ghi của nó, thì không nhận mã, không bị đổi tên.
        moved = child_id(2)
        for k in (1, K_OR):
            with self.subTest(k=k):
                clock = DongHoGia()

                def moc(task: str) -> None:
                    if task != moved:
                        erp.away.add(moved)
                        erp.nodes[moved]["project"] = "PROJ-7777"

                erp = _ErpMoc(clock, [1, 2], moc)
                with erp_gia(clock, erp, k) as svc:
                    result = FlowWebService.fill_task_skus(svc, ROOT)
                self.assertEqual([moved], [item["task_id"] for item in result["failed"]])
                self.assertEqual("", erp.nodes[moved]["meta"])
                self.assertEqual("Idea 3", erp.nodes[moved]["subject"])


if __name__ == "__main__":
    unittest.main()
