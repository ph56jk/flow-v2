"""Bảng mã SKU trên sheet tự đọc lại, không chờ khởi động lại app.

Trước đây ``load_sku_book`` nhớ sheet tới lần restart sau.  Người vận hành
thêm dòng vào sheet thì bot không thấy, thẻ cứ trống mã.  Lúc khởi động mà
đọc sheet hỏng thì bot nhớ luôn một bảng rỗng.

Giờ sheet đọc được thì nhớ ``SKU_SHEET_TTL_SECONDS``, hết hạn thì đọc lại.
Đọc hỏng thì giữ bảng tốt gần nhất và chờ ``SKU_SHEET_RETRY_SECONDS`` mới thử
lại.  Đồng hồ tiêm vào, không ``sleep``, không gọi mạng.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List
from unittest.mock import patch

from flow_web.service import FlowWebService

URL_A = "https://docs.google.com/spreadsheets/d/a/edit#gid=284085791"
URL_B = "https://docs.google.com/spreadsheets/d/b/edit"
TTL = FlowWebService.SHEET_TTL_SECONDS
RETRY = FlowWebService.SHEET_RETRY_SECONDS


class SkuSheetTtlTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = patch.dict(os.environ, {"FLOW_SKU_MAP": ""})
        env.start()
        self.addCleanup(env.stop)
        self.log = patch("flow_web.service.log").start()
        self.addCleanup(patch.stopall)

        self.now = 0.0
        self.url = URL_A
        self.rows: List[Dict[str, str]] = [{"Sản phẩm": "ornament thêu", "Mã": "OR"}]
        self.explodes = False
        self.reads: List[str] = []

        tmp = Path(self._tmp.name)
        svc = FlowWebService.__new__(FlowWebService)
        svc._sku_book_path = lambda: tmp / "sku_book.json"
        svc._redact_erp_secret = lambda value: value
        svc._erp_sku_sheet_url = lambda: self.url
        svc._sheet_clock = lambda: self.now

        def read_sheet(url):
            self.reads.append(url)
            if self.explodes:
                raise ConnectionError("Google trả 503")
            return [dict(row) for row in self.rows]

        svc._load_prompt_source_url = read_sheet
        self.svc = svc

    def _book(self, at: float, **kwargs):
        self.now = at
        return self.svc.load_sku_book(**kwargs)

    def test_trong_han_khong_doc_lai_sheet(self):
        self._book(0)
        self._book(15)
        book = self._book(TTL - 1)

        self.assertEqual([URL_A], self.reads)
        self.assertEqual(("OR", "book"), book.lookup("ornament thêu"))

    def test_het_han_thi_doc_lai_va_dong_moi_co_hieu_luc(self):
        self._book(0)
        self.rows.append({"Sản phẩm": "ornament len chọc", "Mã": "OL"})

        before = self._book(TTL - 1)
        self.assertNotEqual("book", before.lookup("ornament len chọc")[1], "chưa hết hạn thì chưa thấy dòng mới")

        after = self._book(TTL)
        self.assertEqual(2, len(self.reads))
        self.assertEqual(("OL", "book"), after.lookup("ornament len chọc"))
        self.assertEqual(("OR", "book"), after.lookup("ornament thêu"))

    def test_doc_hong_sau_khi_da_co_bang_tot_thi_giu_bang_tot(self):
        self._book(0)
        self.explodes = True

        book = self._book(TTL)

        self.assertEqual(2, len(self.reads), "hết hạn thì phải thử đọc lại")
        self.assertEqual(("OR", "book"), book.lookup("ornament thêu"))
        self.assertTrue(self.log.warning.called, "đọc hỏng phải ghi log")

    def test_doc_hong_lien_tuc_thi_khong_goi_lai_truoc_han_thu_lai(self):
        self._book(0)
        self.explodes = True
        self._book(TTL)  # lượt hỏng thứ nhất

        self._book(TTL + 15)
        book = self._book(TTL + RETRY - 1)
        self.assertEqual(2, len(self.reads), "trong khoảng chờ thì không gọi Google")
        self.assertEqual(("OR", "book"), book.lookup("ornament thêu"))

        book = self._book(TTL + RETRY)
        self.assertEqual(3, len(self.reads))
        self.assertEqual(("OR", "book"), book.lookup("ornament thêu"))

        # Sheet sống lại thì bảng mới lại được nhớ trọn một hạn.
        self.explodes = False
        self.rows.append({"Sản phẩm": "ornament len chọc", "Mã": "OL"})
        book = self._book(TTL + 2 * RETRY)
        self.assertEqual(4, len(self.reads))
        self.assertEqual(("OL", "book"), book.lookup("ornament len chọc"))
        self._book(TTL + 2 * RETRY + TTL - 1)
        self.assertEqual(4, len(self.reads))

    def test_chua_doc_duoc_lan_nao_thi_dung_bang_rong_va_cho_thu_lai(self):
        self.explodes = True

        book = self._book(0)
        self.assertNotEqual("book", book.lookup("ornament thêu")[1])
        self._book(RETRY - 1)
        self.assertEqual(1, len(self.reads))

        self.explodes = False
        book = self._book(RETRY)
        self.assertEqual(2, len(self.reads))
        self.assertEqual(("OR", "book"), book.lookup("ornament thêu"))

    def test_refresh_luon_doc_lai(self):
        self._book(0)
        self._book(1, refresh=True)
        self.assertEqual(2, len(self.reads))

        # Cả trong khoảng chờ sau lượt hỏng, refresh vẫn đọc ngay.
        self.explodes = True
        self._book(2, refresh=True)
        self.explodes = False
        self.rows.append({"Sản phẩm": "ornament len chọc", "Mã": "OL"})
        book = self._book(3, refresh=True)
        self.assertEqual(4, len(self.reads))
        self.assertEqual(("OL", "book"), book.lookup("ornament len chọc"))

    def test_doi_link_hay_xoa_cache_thi_doc_lai(self):
        self._book(0)

        self.url = URL_B
        self._book(10)
        self.assertEqual([URL_A, URL_B], self.reads)

        # Lưu cấu hình ERP đổi link thì đặt ``_sku_sheet_cache = None``.
        # Đổi đi rồi đổi lại đúng link cũ vẫn phải đọc lại, không trả bảng rỗng.
        self.url = URL_A
        self.svc._sku_sheet_cache = None
        book = self._book(20)
        self.assertEqual([URL_A, URL_B, URL_A], self.reads)
        self.svc._sku_sheet_cache = None
        book = self._book(21)
        self.assertEqual(4, len(self.reads))
        self.assertEqual(("OR", "book"), book.lookup("ornament thêu"))

    def test_link_moi_doc_hong_thi_khong_dung_bang_cua_link_cu(self):
        self._book(0)
        self.url = URL_B
        self.explodes = True

        book = self._book(10)

        self.assertEqual([URL_A, URL_B], self.reads)
        self.assertNotEqual("book", book.lookup("ornament thêu")[1], "bảng của link cũ không phải bảng của link mới")


ACC_URL = "https://docs.google.com/spreadsheets/d/acc/edit"


class AccountSheetTtlTests(unittest.TestCase):
    """Sổ tài khoản trên sheet ``FLOW_ACC_SHEET_URL`` theo cùng luật.

    Seller thêm tài khoản mới vào sheet thì lister phải tự thấy sau vài
    phút, không phải chờ khởi động lại app.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = patch.dict(
            os.environ,
            {"FLOW_ACC_SHEET_URL": ACC_URL, "FLOW_ERP_ACC_MACHINES": "", "FLOW_SKU_MAP": ""},
        )
        env.start()
        self.addCleanup(env.stop)
        self.log = patch("flow_web.service.log").start()
        self.addCleanup(patch.stopall)

        self.now = 0.0
        self.sheets: Dict[str, List[Dict[str, str]]] = {
            ACC_URL: [{"Account": "acc40", "Shop": "Havi Home", "Machine": "etsy-40"}],
            URL_A: [{"Sản phẩm": "ornament thêu", "Mã": "OR"}],
        }
        self.explodes = False
        self.reads: List[str] = []

        tmp = Path(self._tmp.name)
        svc = FlowWebService.__new__(FlowWebService)
        svc._account_book_path = lambda: tmp / "account_book.json"
        svc._sku_book_path = lambda: tmp / "sku_book.json"
        svc._erp_sku_sheet_url = lambda: URL_A
        svc._redact_erp_secret = lambda value: value
        svc._sheet_clock = lambda: self.now

        def read_sheet(url):
            self.reads.append(url)
            if self.explodes:
                raise ConnectionError("Google trả 503")
            return [dict(row) for row in self.sheets[url]]

        svc._load_prompt_source_url = read_sheet
        self.svc = svc

    def _accounts(self, at: float, **kwargs):
        self.now = at
        return self.svc.load_account_book(**kwargs)

    def _add_account(self) -> None:
        self.sheets[ACC_URL].append({"Account": "acc41", "Shop": "Havi Craft", "Machine": "etsy-41"})

    def test_trong_han_khong_doc_lai_het_han_thi_thay_tai_khoan_moi(self):
        self._accounts(0)
        self._add_account()

        before = self._accounts(TTL - 1)
        self.assertEqual([ACC_URL], self.reads)
        self.assertFalse(before.knows("acc41"), "chưa hết hạn thì chưa thấy tài khoản mới")

        after = self._accounts(TTL)
        self.assertEqual(2, len(self.reads))
        self.assertEqual("etsy-41", after.machine_for("acc41"))
        self.assertEqual("etsy-40", after.machine_for("acc40"))

    def test_doc_hong_thi_giu_so_tot_va_cho_thu_lai(self):
        self._accounts(0)
        self.explodes = True

        book = self._accounts(TTL)
        self.assertEqual(2, len(self.reads))
        self.assertEqual("etsy-40", book.machine_for("acc40"), "đọc hỏng không được làm mất sổ tốt")
        self.assertTrue(self.log.warning.called)

        book = self._accounts(TTL + RETRY - 1)
        self.assertEqual(2, len(self.reads), "trong khoảng chờ thì không gọi Google")
        self.assertEqual("etsy-40", book.machine_for("acc40"))

        self.explodes = False
        self._add_account()
        book = self._accounts(TTL + RETRY)
        self.assertEqual(3, len(self.reads))
        self.assertEqual("etsy-41", book.machine_for("acc41"))

    def test_chua_doc_duoc_lan_nao_thi_so_trong_va_cho_thu_lai(self):
        self.explodes = True

        book = self._accounts(0)
        self.assertFalse(book.knows("acc40"))
        self._accounts(RETRY - 1)
        self.assertEqual(1, len(self.reads))

        self.explodes = False
        book = self._accounts(RETRY)
        self.assertEqual("etsy-40", book.machine_for("acc40"))

    def test_refresh_luon_doc_lai(self):
        # Màn hình sổ tài khoản (GET /api/erp/accounts) gọi refresh=True.
        self._accounts(0)
        self._add_account()
        book = self._accounts(1, refresh=True)
        self.assertEqual(2, len(self.reads))
        self.assertTrue(book.knows("acc41"))

    def test_so_tai_khoan_va_bang_ma_nho_rieng(self):
        # Đọc bảng mã không được tính là đã đọc sổ tài khoản, và ngược lại.
        self._accounts(0)
        self.now = 10
        self.svc.load_sku_book()
        self.assertEqual([ACC_URL, URL_A], self.reads)

        self._accounts(TTL)
        self.assertEqual([ACC_URL, URL_A, ACC_URL], self.reads)
        self.now = TTL + 1
        self.svc.load_sku_book()
        self.assertEqual([ACC_URL, URL_A, ACC_URL], self.reads, "bảng mã còn hạn tới 310")


if __name__ == "__main__":
    unittest.main()
