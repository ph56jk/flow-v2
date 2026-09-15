"""Script soát trích dẫn ``tệp.py:dòng`` trong tài liệu."""
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC / "tools"))

from kiem_trich_dan import doc_trich_dan, main  # noqa: E402


class DocTrichDanTests(unittest.TestCase):
    def test_bat_trich_dan_trong_nhay(self):
        got = doc_trich_dan("xem `flow_web/sku.py:1307-1324` nhé")
        self.assertEqual(got, [("flow_web/sku.py", 1307, 1324)])

    def test_mot_dong_thi_dau_bang_cuoi(self):
        got = doc_trich_dan("`flow_web/sku.py:1293`")
        self.assertEqual(got, [("flow_web/sku.py", 1293, 1293)])

    def test_dang_chi_co_dong_noi_vao_tep_gan_nhat(self):
        got = doc_trich_dan("`flow_web/sku.py:1307`, `:1415`")
        self.assertEqual(
            got, [("flow_web/sku.py", 1307, 1307), ("flow_web/sku.py", 1415, 1415)]
        )

    def test_bo_qua_so_ngoai_nhay(self):
        # "bảng 8765" là cổng, không phải trích dẫn.
        self.assertEqual(doc_trich_dan("bảng chạy ở cổng 8765, xem board.py:12"), [])

    def test_bo_qua_cau_van_trong_nhay(self):
        self.assertEqual(doc_trich_dan("`ERP_SKU_FAST_LANE=1`"), [])

    def test_dong_le_khong_co_tep_truoc_do_thi_bo(self):
        self.assertEqual(doc_trich_dan("`:1415`"), [])

    def test_backtick_chi_co_ten_tep_cung_dat_moc(self):
        # "Lượt quét chính — `flow_web/agent_bot.py`: … `:115`"
        got = doc_trich_dan("xem `flow_web/agent_bot.py` rồi `:115`")
        self.assertEqual(got, [("flow_web/agent_bot.py", 115, 115)])

    def test_ten_tep_du_lieu_khong_dat_moc(self):
        # `DATA_DIR/…json` là chỗ chứa dữ liệu; `:3413` sau nó vẫn nói về bot.
        got = doc_trich_dan(
            "`flow_web/agent_bot.py` … `DATA_DIR/erp-agent-nhip.json` … `:3413`"
        )
        self.assertEqual(got, [("flow_web/agent_bot.py", 3413, 3413)])

    def test_khong_noi_tiep_qua_tep_md(self):
        # `:120` nói về sku.py, không phải về tài liệu vừa nhắc.
        got = doc_trich_dan("`flow_web/sku.py:10`, xem `docs/a.md:3`, rồi `:120`")
        self.assertEqual(
            got,
            [
                ("flow_web/sku.py", 10, 10),
                ("docs/a.md", 3, 3),
                ("flow_web/sku.py", 120, 120),
            ],
        )


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        (self.tmp / "flow_web").mkdir()
        (self.tmp / "flow_web" / "x.py").write_text("mot\nhai\nba\n", encoding="utf-8")

    def _doc(self, noi_dung: str) -> Path:
        p = self.tmp / "tai-lieu.md"
        p.write_text(noi_dung, encoding="utf-8")
        return p

    def test_tra_duoc_het_thi_ma_thoat_0(self):
        doc = self._doc("xem `flow_web/x.py:2`")
        self.assertEqual(main([str(doc), str(self.tmp)]), 0)

    def test_dong_qua_cuoi_tep_thi_ma_thoat_1(self):
        doc = self._doc("xem `flow_web/x.py:99`")
        self.assertEqual(main([str(doc), str(self.tmp)]), 1)

    def test_thieu_tep_thi_ma_thoat_1(self):
        doc = self._doc("xem `flow_web/khong-co.py:1`")
        self.assertEqual(main([str(doc), str(self.tmp)]), 1)

    def test_ten_tep_tran_tra_trong_flow_web(self):
        # Tài liệu cũ viết `service.py:123`, không kèm thư mục.
        doc = self._doc("xem `x.py:2`")
        self.assertEqual(main([str(doc), str(self.tmp)]), 0)


if __name__ == "__main__":
    unittest.main()
