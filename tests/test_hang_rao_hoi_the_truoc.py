"""Hàng rào dự án ngoài lượt đánh số: hỏi thẻ trước, đừng đọc cả chục bảng.

Mỗi lần bot kéo thẻ sang cột khác, bình luận hay gắn nhãn, hàng rào lại đọc
bảng từng dự án theo thứ tự tới khi thấy thẻ.  Trên hvg-pc có 30 dự án được
phép, PROJ-0087 đứng thứ 27: một lần kéo thẻ OL tốn 27 lượt đọc bảng, khoảng
40 giây ở nhịp 40/phút.

Giờ ngoài lượt đánh số, hàng rào hỏi ``taskDetail`` xem thẻ nằm dự án nào rồi
đọc tươi bảng ấy trước.  Luật không đổi: dự án chỉ được nhận khi nằm trong
danh sách được phép **và** bảng tươi của nó liệt kê thẻ.

ERP giả và đồng hồ giả lấy từ ``test_sku_nhanh_moi_the``.
"""

from __future__ import annotations

import collections
import io
import json
import unittest
from typing import Any, Dict, List
from urllib.error import HTTPError

from flow_web.service import FlowWebService
from tests.test_sku_nhanh_moi_the import (
    K_OL,
    K_OR,
    PROJECT,
    ROOT,
    DongHoGia,
    ErpGia,
    allowed_projects,
    child_id,
    do_luot,
    erp_gia,
)

CARD = child_id(3)
K_HVG = 30  # hvg-pc có 30 dự án được phép


class _ErpAn(ErpGia):
    """ERP giả mà ``lan`` lần đọc bảng cụm đầu tiên chưa liệt kê thẻ ``an``.

    Giống thẻ vừa sang bảng sau lúc lượt đánh số đọc bảng: ``taskDetail`` đã
    khai đúng dự án, mà bảng nhớ đầu lượt chưa có thẻ.
    """

    def __init__(self, clock: DongHoGia, working: List[int], an: str, lan: int = 1) -> None:
        super().__init__(clock, working)
        self._an = an
        self._lan = lan

    def board(self, project: str) -> Dict[str, Any]:
        if project != PROJECT or self._lan <= 0:
            return super().board(project)
        self._lan -= 1
        self.away.add(self._an)
        try:
            return super().board(project)
        finally:
            self.away.discard(self._an)


class HangRaoHoiTheTruocTests(unittest.TestCase):
    def _hoi(self, k: int, erp: ErpGia, clock: DongHoGia, card: str = CARD) -> str:
        with erp_gia(clock, erp, k) as svc:
            return svc._erp_task_project_id("k", "t", card)

    def test_moi_lan_hoi_toi_da_hai_request(self):
        for k in (1, K_OR, K_OL):
            with self.subTest(k=k):
                clock = DongHoGia()
                erp = ErpGia(clock, [])
                self.assertEqual(PROJECT, self._hoi(k, erp, clock))
                self.assertLessEqual(sum(erp.calls.values()), 2, dict(erp.calls))
                if k == 1:
                    # Cách cũ đọc đúng một bảng: không được tệ hơn quá 1 request.
                    self.assertLessEqual(sum(erp.calls.values()), 1 + 1)

    def test_du_an_ngoai_danh_sach_bi_choi_sau_khi_doc_du(self):
        # Thẻ khai PROJ-7777, không nằm trong danh sách: chối, nhưng chỉ sau
        # khi đã đọc tươi đủ mọi bảng được phép.
        clock = DongHoGia()
        erp = ErpGia(clock, [], away=[3])
        with self.assertRaisesRegex(RuntimeError, "không thuộc Project"):
            self._hoi(K_OR, erp, clock)
        self.assertEqual(K_OR, erp.calls["TaskBoard"])

    def test_the_khai_du_an_A_ma_bang_A_khong_co_the(self):
        # Thẻ khai một dự án được phép, nhưng bảng ấy không liệt kê nó: không
        # nhận dự án ấy, quét tiếp như cũ tới đúng bảng có thẻ.
        clock = DongHoGia()
        erp = ErpGia(clock, [])
        claimed = allowed_projects(K_OR)[4]
        erp.nodes[CARD]["project"] = claimed
        self.assertEqual(PROJECT, self._hoi(K_OR, erp, clock))
        self.assertEqual(K_OR, erp.calls["TaskBoard"])

    def _loi_khi_hoi_the(self, erp: ErpGia, code: int) -> None:
        real = erp.urlopen

        def urlopen(request: Any, timeout: Any = None):
            if json.loads(request.data.decode("utf-8"))["operationName"] == "TaskDetail":
                erp.calls["TaskDetail"] += 1
                raise HTTPError(request.full_url, code, "lỗi giả", {}, io.BytesIO(b""))
            return real(request, timeout)

        erp.urlopen = urlopen

    def test_hoi_the_loi_thuong_thi_roi_ve_cach_cu(self):
        clock = DongHoGia()
        erp = ErpGia(clock, [])
        self._loi_khi_hoi_the(erp, 500)
        self.assertEqual(PROJECT, self._hoi(K_OR, erp, clock))
        self.assertEqual(K_OR, erp.calls["TaskBoard"])

    def test_hoi_the_429_thi_loi_noi_len(self):
        # ERP đang chặn mà quét tiếp 27 bảng là gõ đúng vào chỗ đau.
        clock = DongHoGia()
        erp = ErpGia(clock, [])
        self._loi_khi_hoi_the(erp, 429)
        with self.assertRaisesRegex(RuntimeError, "429"):
            self._hoi(K_OL, erp, clock)
        self.assertEqual(0, erp.calls["TaskBoard"])

    def test_hai_lan_hoi_lien_tiep_deu_doc_tuoi(self):
        clock = DongHoGia()
        erp = ErpGia(clock, [])
        with erp_gia(clock, erp, K_OR) as svc:
            svc._erp_task_project_id("k", "t", child_id(3))
            svc._erp_task_project_id("k", "t", child_id(3))
        self.assertEqual(2, erp.calls["TaskBoard"], "ngoài lượt không nhớ bảng")
        self.assertEqual(2, erp.calls["TaskDetail"])


class CaGTests(unittest.TestCase):
    """Ca G của 49: dự án thẻ khai đang nằm trong bảng nhớ, mà bảng nhớ chưa có thẻ.

    Cách cũ tin bảng nhớ, đọc tươi mọi bảng khác rồi mới đọc lại bảng ấy:
    31 lượt đọc bảng trên hvg-pc.  Muốn: đọc tươi đúng bảng thẻ khai trước.
    """

    def test_doc_tuoi_bang_du_an_the_khai_truoc(self):
        clock = DongHoGia()
        erp = _ErpAn(clock, [], CARD)
        with erp_gia(clock, erp, K_HVG) as svc, svc._erp_board_memo():
            svc._erp_task_board("k", "t", PROJECT)
            erp.calls.clear()
            self.assertEqual(PROJECT, svc._erp_task_project_id("k", "t", CARD))
        self.assertEqual({"TaskDetail": 1, "TaskBoard": 1}, dict(erp.calls))

    def test_bang_tuoi_van_khong_co_the_thi_moi_bang_doc_mot_lan(self):
        # Luật không đổi: bảng tươi không liệt kê thẻ thì vẫn quét đủ rồi chối.
        # Bảng vừa đọc tươi không bị đọc lại lần nữa ở bước đọc lại bảng nhớ.
        clock = DongHoGia()
        erp = _ErpAn(clock, [], CARD, lan=99)
        with erp_gia(clock, erp, K_OR) as svc, svc._erp_board_memo():
            svc._erp_task_board("k", "t", PROJECT)
            erp.calls.clear()
            with self.assertRaisesRegex(RuntimeError, "không thuộc Project"):
                svc._erp_task_project_id("k", "t", CARD)
        self.assertEqual(K_OR, erp.calls["TaskBoard"])

    def test_mot_luot_the_vang_tren_bang_dau_luot(self):
        # So với chính lượt sạch cùng k: chỉ thêm một lượt đọc tươi bảng thẻ
        # khai, cộng một lượt hỏi thẻ khi danh sách dài hơn hai dự án.
        for k in (1, K_OR, K_OL, K_HVG):
            with self.subTest(k=k):
                mong = collections.Counter(do_luot(1, k)["calls"])
                mong["TaskBoard"] += 1
                if k > 2:
                    mong["TaskDetail"] += 1
                clock = DongHoGia()
                erp = _ErpAn(clock, [0], child_id(0))
                with erp_gia(clock, erp, k) as svc:
                    result = FlowWebService.fill_task_skus(svc, ROOT)
                self.assertEqual(1, len(result["written"]), result)
                self.assertEqual(dict(mong), dict(erp.calls))


if __name__ == "__main__":
    unittest.main()
