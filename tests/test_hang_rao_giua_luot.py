"""Hàng rào dự án giữa lượt đánh số: tin lượt đọc tươi, không tin bảng nhớ.

Trong lượt, hàng rào dò bảng nhớ đọc từ đầu lượt.  Thẻ bị kéo sang dự án
không được phép sau lúc ấy vẫn còn trên bảng nhớ, và d48d3dc vẫn ghi mã rồi
đổi tên nó.  Bài của 49 (``test_soat_d48d3dc``) canh bước ghi mã.  Tệp này
canh thêm hai chỗ:

- sổ không dịch cho thẻ bị chối;
- thẻ bị kéo đi giữa lúc ghi mã và lúc đọc kiểm thì không bị đổi tên.

ERP giả và đồng hồ giả lấy từ ``test_sku_nhanh_moi_the``.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, Callable, List

from flow_web import service as service_mod
from flow_web.service import FlowWebService
from tests.test_sku_nhanh_moi_the import K_OR, ROOT, DongHoGia, ErpGia, child_id, erp_gia

LA = "PROJ-7777"


class _ErpMoc(ErpGia):
    """ERP giả gọi ``truoc(task)`` trước và ``sau(task)`` sau mỗi lượt ghi mã."""

    def __init__(
        self,
        clock: DongHoGia,
        working: List[int],
        truoc: Callable[[str], None] = lambda task: None,
        sau: Callable[[str], None] = lambda task: None,
    ) -> None:
        super().__init__(clock, working)
        self._truoc = truoc
        self._sau = sau

    def urlopen(self, request: Any, timeout: Any = None) -> Any:
        body = json.loads(request.data.decode("utf-8"))
        ghi = body["operationName"] == "UpdateTaskMeta"
        if ghi:
            self._truoc(body["variables"]["task"])
        out = super().urlopen(request, timeout)
        if ghi:
            self._sau(body["variables"]["task"])
        return out

    def keo_di(self, task: str) -> None:
        self.away.add(task)
        self.nodes[task]["project"] = LA


class HangRaoGiuaLuotTests(unittest.TestCase):
    def test_the_bi_choi_thi_so_khong_dich(self):
        # Thẻ 2 bị kéo đi trước lượt ghi của nó.  Chỉ thẻ 1 nhận mã, nên mốc
        # số của sổ chỉ được đi tới đúng mã của thẻ 1.
        moved = child_id(2)
        for k in (1, K_OR):
            with self.subTest(k=k):
                clock = DongHoGia()

                def truoc(task: str) -> None:
                    if task != moved:
                        erp.keo_di(moved)

                erp = _ErpMoc(clock, [1, 2], truoc=truoc)
                with erp_gia(clock, erp, k) as svc:
                    result = FlowWebService.fill_task_skus(svc, ROOT)
                    so = json.loads(svc._sku_ledger_path().read_text())
                self.assertEqual([moved], [item["task_id"] for item in result["failed"]])
                self.assertIn("không thuộc Project", result["failed"][0]["error"])
                self.assertEqual(1, len(result["written"]))
                ma = result["written"][0]["sku"]
                self.assertEqual(int(ma.rsplit("_", 1)[1]), max(so["idea_seq"].values()), so)
                self.assertNotIn(moved, so.get("pending", {}))

    def test_the_bi_keo_di_sau_khi_ghi_thi_khong_doi_ten(self):
        # Mã đã lên thẻ rồi thẻ mới bị kéo đi: mã giữ, tên giữ, có WARNING.
        moved = child_id(2)
        for k in (1, K_OR):
            with self.subTest(k=k):
                clock = DongHoGia()

                def sau(task: str) -> None:
                    if task == moved:
                        erp.keo_di(moved)

                erp = _ErpMoc(clock, [1, 2], sau=sau)
                with erp_gia(clock, erp, k) as svc:
                    result = FlowWebService.fill_task_skus(svc, ROOT)
                    canh_bao = [str(call) for call in service_mod.log.warning.call_args_list]
                self.assertEqual([], result["failed"])
                self.assertEqual("Idea 3", erp.nodes[moved]["subject"])
                self.assertEqual([moved], [item["task_id"] for item in result["rename_failed"]])
                self.assertEqual([child_id(1)], [item["task_id"] for item in result["renamed"]])
                self.assertTrue(any(moved in line and LA in line for line in canh_bao), canh_bao)

    def test_the_o_yen_thi_khong_ton_them_request(self):
        # Hai chỗ kiểm mới dùng lại lượt đọc sẵn có: không thêm request nào.
        # Mỗi thẻ: đọc trước khi ghi, ghi mã, đọc kiểm, đổi tên.
        for k in (1, K_OR):
            with self.subTest(k=k):
                clock = DongHoGia()
                erp = _ErpMoc(clock, [1, 2])
                with erp_gia(clock, erp, k) as svc:
                    result = FlowWebService.fill_task_skus(svc, ROOT)
                self.assertEqual(2, len(result["renamed"]), result)
                self.assertEqual(2, erp.calls["UpdateTaskMeta"])
                self.assertEqual(2, erp.calls["UpdateTaskTitle"])
                self.assertEqual(2 * 2 + (0 if k == 1 else 1), erp.calls["TaskDetail"])


if __name__ == "__main__":
    unittest.main()
