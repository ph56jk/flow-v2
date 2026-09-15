"""Tiền tố SKU lấy thẳng từ danh mục sản phẩm ERP (`product_type`), không đoán theo tên.

Bối cảnh — xem `tasks/sku-tu-product-type.md`: bot hiện đoán tiền tố SKU bằng
cách bổ chữ cái đầu tên sản phẩm gõ tay (`derive_prefix`, `flow_web/sku.py:213-230`).
Đoán kiểu ấy từng ra ``PNO`` cho "Punch Needle Ornament" trong khi xưởng gọi
món ấy là ``OL`` (xem đúng câu này trong docstring `derive_prefix`, sku.py:221).
ERP thì đã có danh mục sản phẩm riêng (`productCategories`), mỗi dòng mang sẵn
`sku_prefix`, và mỗi thẻ trỏ vào một dòng bằng `product_type` (taskDetail, cấp
1) hoặc `custom_product_type` (taskBoard) — chuỗi tên trần, không kèm mã.

File này tả hành vi **sau khi cài** nguồn mã mới `"erp-category"`, đứng trước
`book`/`book-contains`/`book-alias`/`derived`. Tất cả đỏ ngay bây giờ vì tính
năng chưa tồn tại — không đỏ vì lỗi cú pháp hay import sai.

Chạy từ gốc worktree (không phải trong `tests/`):
    .venv/bin/python -m unittest tests.test_sku_product_type -v
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

from flow_web import sku as sku_module
from flow_web.erp_meta import render_meta_block, task_meta
from flow_web.sku import (
    SkuCard,
    SkuLedger,
    card_from_node,
    la_ma_doan,
    plan_skus,
)

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Dữ liệu mẫu: bốn dòng đo thật ngày 12/09 trên hvg-pc, chép từ
# briefs/danh-muc-erp-do-12-09.txt (dòng 39-41, 4).  Thêm một dòng `kind:
# group` (không sku_prefix) đúng dạng 30/127 dòng thật cùng loại, để test được
# luật "dòng nhóm không có sku_prefix thì phải bị bỏ".
# ---------------------------------------------------------------------------
CATEGORY_ROWS: List[Dict[str, Any]] = [
    {
        "code": "HOM-SEA-OL",
        "kind": "type",
        "name_vi": "Ornament len chọc",
        "name_en": "Punch Needle Ornament",
        "sku_prefix": "OL",
        "status": "active",
    },
    {
        "code": "HOM-SEA-OR",
        "kind": "type",
        "name_vi": "Ornament thêu",
        "name_en": "Embroidered Ornament",
        "sku_prefix": "OR",
        "status": "active",
    },
    {
        "code": "FAS-CLO-TS",
        "kind": "type",
        "name_vi": "Áo phông in",
        "name_en": "Printed T-Shirt",
        "sku_prefix": "TS",
        "status": "active",
    },
    {
        # Dòng nhóm cha — đo thật: 30/127 dòng dạng này, sku_prefix luôn null.
        "code": "HOM-SEA",
        "kind": "group",
        "name_vi": "Trang trí mùa lễ",
        "name_en": "Seasonal & Holiday Décor",
        "sku_prefix": None,
        "status": "active",
    },
]


def _category_book(rows: List[Dict[str, Any]] = CATEGORY_ROWS):
    """Dựng `ProductCategoryBook` — nguồn mã mới `"erp-category"`.

    Chưa tồn tại thì báo rõ, đừng để bài test rơi vào AttributeError khó đọc.
    """
    cls = getattr(sku_module, "ProductCategoryBook", None)
    if cls is None:
        raise AssertionError(
            "flow_web.sku chưa có lớp ProductCategoryBook — danh mục sản phẩm ERP "
            "(nguồn 'erp-category', PRD mục 3.1) chưa được cài."
        )
    return cls.from_rows(rows)


class ProductCategoryBookTests(unittest.TestCase):
    """`ProductCategoryBook` — tra `product_type` theo danh mục ERP, không phải đoán."""

    def test_khop_theo_ten_tieng_anh(self):
        book = _category_book()
        self.assertEqual(
            ("OL", "erp-category"),
            book.lookup("Punch Needle Ornament"),
            "phải tra ra đúng ('OL', 'erp-category') cho tên_en đo thật của thẻ TASK-2026-05391",
        )

    def test_khop_theo_ten_tieng_viet_khong_dau(self):
        book = _category_book()
        self.assertEqual(
            ("OL", "erp-category"),
            book.lookup("Ornament len choc"),
            "phải bỏ dấu trước khi so (dùng chung normalize_product với ProductBook, sku.py:156-160)",
        )

    def test_khop_theo_ma_code(self):
        book = _category_book()
        self.assertEqual(
            ("TS", "erp-category"),
            book.lookup("FAS-CLO-TS"),
            "PRD mục 3.1 (theo brief mục 4) yêu cầu khớp thêm theo 'code', không chỉ name_vi/name_en",
        )

    def test_dong_nhom_khong_co_sku_prefix_khong_duoc_tra_ra(self):
        book = _category_book()
        self.assertEqual(
            ("", ""),
            book.lookup("Seasonal & Holiday Décor"),
            "dòng kind=group không có sku_prefix (đo thật 30/127 dòng) phải bị bỏ qua, "
            "không được coi một mã rỗng là khớp",
        )

    def test_khong_co_dong_nao_khop_thi_tra_rong(self):
        book = _category_book()
        self.assertEqual(
            ("", ""),
            book.lookup("Một sản phẩm ngoài danh mục"),
            "không khớp danh mục ERP thì phải trả rỗng để rơi xuống nguồn kế tiếp (book), "
            "không được tự đoán ở tầng này",
        )

    def test_dong_khong_active_thi_khong_duoc_dung(self):
        rows = CATEGORY_ROWS + [
            {
                "code": "HOM-SEA-OL2",
                "kind": "type",
                "name_vi": "Ornament thử nghiệm",
                "name_en": "Trial Ornament",
                "sku_prefix": "TR",
                "status": "inactive",
            }
        ]
        book = _category_book(rows)
        self.assertEqual(
            ("", ""),
            book.lookup("Trial Ornament"),
            "brief mục 4 yêu cầu 'chỉ lấy dòng status: active' — dòng inactive không được dùng để tra",
        )

    def test_hai_dong_trung_ten_khac_ma_thi_bo_khong_doan(self):
        # Đo thật 12/09 chưa gặp ca này (danh mục sạch, mỗi tên một mã). Đây là
        # tình huống giả định để canh luật an toàn khi ERP lỡ có hai dòng cùng
        # tên_en khác mã — ProductBook.from_rows (sku.py:358-367) đã có tiền lệ
        # bỏ bí danh trùng thay vì đoán đại, ProductCategoryBook phải theo lối đó.
        rows = CATEGORY_ROWS + [
            {
                "code": "POD-ORN-DUP",
                "kind": "type",
                "name_vi": "Trùng tên với OL",
                "name_en": "Punch Needle Ornament",
                "sku_prefix": "ZZ",
                "status": "active",
            }
        ]
        book = _category_book(rows)
        self.assertEqual(
            ("", ""),
            book.lookup("Punch Needle Ornament"),
            "hai dòng ERP cùng name_en khác sku_prefix: phải bỏ cả hai, không đoán đại một mã",
        )


class LaMaDoanErpCategoryTests(unittest.TestCase):
    """`la_ma_doan` (sku.py:133-140) phải biết 'erp-category' không phải mã đoán."""

    def test_erp_category_khong_phai_ma_doan(self):
        self.assertFalse(
            la_ma_doan("erp-category"),
            "nguồn 'erp-category' là mã ERP tự ghi trong danh mục sản phẩm, không phải bot đoán; "
            "la_ma_doan phải trả False giống 'book'/'book-contains'/'book-alias' (BOOK_SOURCES, sku.py:130)",
        )

    def test_cac_nguon_cu_khong_bi_doi(self):
        # Chốt chặn: đừng vô tình biến mọi nguồn thành "không phải đoán".
        self.assertTrue(la_ma_doan("derived"), "'derived' vẫn phải là mã đoán, không được đổi hành vi cũ")
        self.assertTrue(la_ma_doan(""), "nguồn rỗng vẫn phải coi là mã đoán, không được đổi hành vi cũ")


def _product_type_of(card: SkuCard, testcase: unittest.TestCase) -> str:
    try:
        return card.product_type  # type: ignore[attr-defined]
    except AttributeError:
        testcase.fail(
            "SkuCard chưa có field product_type — cần thêm vào dataclass SkuCard "
            "(flow_web/sku.py:478-503) rồi đọc nó trong card_from_node (sku.py:861-875)"
        )


class CardFromNodeProductTypeTests(unittest.TestCase):
    """`card_from_node` phải đọc product_type cấp 1 / custom_product_type."""

    def test_doc_product_type_cap_mot_tu_taskdetail(self):
        node = {"name": "TASK-2026-05391", "product_type": "Punch Needle Ornament"}
        card = card_from_node(node)
        self.assertEqual("Punch Needle Ornament", _product_type_of(card, self))

    def test_doc_custom_product_type_tu_taskboard(self):
        # taskBoard không có 'product_type' cấp 1, chỉ có 'custom_product_type'
        # (đo thật PROJ-0018, briefs/danh-muc-erp-do-12-09.txt mục 3).
        node = {"name": "TASK-2026-04628", "custom_product_type": "Punch Needle Ornament"}
        card = card_from_node(node)
        self.assertEqual("Punch Needle Ornament", _product_type_of(card, self))

    def test_thieu_ca_hai_thi_rong_khong_loi(self):
        node = {"name": "TASK-X"}
        card = card_from_node(node)
        self.assertEqual("", _product_type_of(card, self))

    def test_product_type_cap_mot_thang_custom_product_type_khi_co_ca_hai(self):
        node = {
            "name": "TASK-Y",
            "product_type": "Punch Needle Ornament",
            "custom_product_type": "Embroidered Ornament",
        }
        card = card_from_node(node)
        self.assertEqual(
            "Punch Needle Ornament",
            _product_type_of(card, self),
            "taskDetail trả product_type cấp 1, taskBoard trả custom_product_type — hai trường "
            "này không nên cùng khác giá trị thật, nhưng cấp 1 phải thắng nếu cả hai cùng có mặt",
        )

    def test_bo_khoang_trang_giong_cac_truong_khac(self):
        node = {"name": "TASK-Z", "product_type": "  Punch Needle Ornament  "}
        card = card_from_node(node)
        self.assertEqual(
            "Punch Needle Ornament",
            _product_type_of(card, self),
            "các trường khác của card_from_node đều .strip() (board/project/status, sku.py:872-874); "
            "product_type phải theo cùng lối",
        )

    def test_khong_lay_nham_tu_khoi_meta_gom_tay(self):
        # 'product_type' cũng là một khoá PRODUCT_KEYS (erp_meta.py:73-83) người
        # ta gõ tay trong khối text 'meta' — đúng khoá ERP_IDEA_REQUIRED_META
        # (service.py:3530) đang đọc cho một tính năng khác hẳn ("chốt thuộc
        # tính idea cha"). Trường cấp 1 mà PRD này nói tới nằm ở payload thô,
        # không phải dòng người gõ tay trong khối meta. card_from_node không
        # được lẫn hai chỗ này.
        node = {
            "name": "TASK-MIX",
            "meta": render_meta_block({"product_type": "Nhầm từ khối Thuộc tính"}),
        }
        card = card_from_node(node)
        got = _product_type_of(card, self)
        self.assertEqual(
            "",
            got,
            f"product_type đọc ra {got!r} từ khối meta gõ tay — card_from_node chỉ được đọc "
            "trường cấp 1 product_type/custom_product_type của payload ERP, không phải dòng "
            "trong khối 'meta' (đó là chỗ TaskMeta.product/PRODUCT_KEYS lo, việc khác hẳn)",
        )


def _plan(cards, book, **kwargs):
    """Gọi `plan_skus` — nếu chưa nhận `categories=` thì báo rõ vì sao đỏ."""
    try:
        return plan_skus(cards, book, **kwargs)
    except TypeError as exc:
        if "categories" in str(exc):
            raise AssertionError(
                "plan_skus (flow_web/sku.py:977-987) chưa nhận từ khoá categories: "
                f"Optional[ProductCategoryBook] — {exc}"
            ) from exc
        raise


def _card(
    task_id: str,
    *,
    parent: str = "",
    subject: str = "",
    meta: str = "",
    board: str = "",
    project: str = "",
    status: str = "",
    product_type: str = "",
) -> SkuCard:
    try:
        return SkuCard(
            task_id=task_id,
            parent_id=parent,
            subject=subject,
            meta=task_meta({"meta": meta}),
            board=board,
            project=project,
            status=status,
            product_type=product_type,  # type: ignore[call-arg]
        )
    except TypeError as exc:
        raise AssertionError(
            "SkuCard chưa nhận được từ khoá product_type — thêm field product_type vào "
            f"dataclass SkuCard (flow_web/sku.py:478-503) trước khi test này chạy được: {exc}"
        ) from exc


class PlanSkusErpCategoryTests(unittest.TestCase):
    """`plan_skus` phải thử danh mục ERP trước khi rơi về bảng sheet / đoán.

    Không gọi ERP: `book` và `categories` đều dựng tay, giống lối
    `tests/test_sku.py` đang làm với `BOOK = ProductBook.from_mapping(...)`.
    """

    def setUp(self) -> None:
        from flow_web.sku import ProductBook

        self.book = ProductBook.from_mapping({"khăn tay": "KT"})
        self.categories = _category_book()

    def test_the_khai_product_type_khop_danh_muc_duoc_cap_ma_erp_khong_can_sheet(self):
        root = _card("TASK-2026-05391", subject="Ornament", product_type="Punch Needle Ornament")
        child = _card(
            "TASK-2026-05392",
            parent="TASK-2026-05391",
            subject="Ornament con 1",
            product_type="Punch Needle Ornament",
        )
        plan = _plan(
            [root, child],
            self.book,
            root_id=root.task_id,
            ledger=SkuLedger(),
            project_id="PROJ-0018",
            categories=self.categories,
        )
        self.assertEqual((), plan.skipped, f"không được bỏ thẻ nào ở đây: {plan.skipped}")
        assignments = {item.task_id: item for item in plan.assignments}
        self.assertIn(child.task_id, assignments, "thẻ đã sẵn sàng và khai product_type khớp phải được cấp mã")
        assignment = assignments[child.task_id]
        self.assertTrue(
            assignment.sku.startswith("OL_"),
            f"mã phải mang tiền tố OL (từ danh mục ERP), mã thật ra là {assignment.sku!r}",
        )
        self.assertEqual(
            "erp-category",
            assignment.prefix_source,
            "prefix_source phải ghi 'erp-category' để soát được thẻ nào lấy mã từ ERP (brief mục 4)",
        )

    def test_khong_khop_danh_muc_thi_roi_ve_bang_sheet(self):
        root = _card("TASK-2026-05391", subject="Khăn")
        child = _card(
            "TASK-2026-05393",
            parent="TASK-2026-05391",
            subject="Khăn con 1",
            meta="product: khăn tay",
            product_type="Sản phẩm không có trong danh mục ERP",
        )
        plan = _plan(
            [root, child],
            self.book,
            root_id=root.task_id,
            ledger=SkuLedger(),
            project_id="PROJ-0018",
            categories=self.categories,
        )
        assignments = {item.task_id: item for item in plan.assignments}
        self.assertIn(child.task_id, assignments)
        assignment = assignments[child.task_id]
        self.assertTrue(
            assignment.sku.startswith("KT_"),
            f"product_type không khớp danh mục ERP thì phải rơi về bảng sheet (KT), mã thật là {assignment.sku!r}",
        )
        self.assertEqual("book", assignment.prefix_source)

    def test_khong_khop_ca_erp_lan_sheet_thi_bo_khong_doan(self):
        root = _card("TASK-2026-05391", subject="Lạ")
        child = _card(
            "TASK-2026-05394",
            parent="TASK-2026-05391",
            subject="Sản phẩm lạ hoàn toàn",
            product_type="Không khớp danh mục ERP cũng không khớp sheet",
        )
        plan = _plan(
            [root, child],
            self.book,
            root_id=root.task_id,
            ledger=SkuLedger(),
            project_id="PROJ-0018",
            categories=self.categories,
        )
        assignments = {item.task_id: item for item in plan.assignments}
        self.assertNotIn(
            child.task_id,
            assignments,
            "không khớp erp-category lẫn book thì KHÔNG được cấp mã đoán (derive_prefix) — "
            "đây chính là luật 'không đoán tiền tố SKU' người dùng đã yêu cầu",
        )
        self.assertTrue(
            any(child.task_id == task_id for task_id, _ in plan.skipped),
            f"thẻ phải nằm trong plan.skipped, thực tế: {plan.skipped}",
        )

    def test_the_da_co_ma_thi_khong_doi_du_erp_noi_mot_ma_khac(self):
        root = _card("TASK-2026-05391", subject="Ornament")
        child = _card(
            "TASK-2026-05395",
            parent="TASK-2026-05391",
            subject="Ornament con cũ",
            meta="sku: OR_1_099",
            product_type="Punch Needle Ornament",  # khớp OL nếu tính lại từ đầu
        )
        plan = _plan(
            [root, child],
            self.book,
            root_id=root.task_id,
            ledger=SkuLedger(),
            project_id="PROJ-0018",
            categories=self.categories,
        )
        assignments = {item.task_id: item for item in plan.assignments}
        self.assertIn(child.task_id, assignments)
        assignment = assignments[child.task_id]
        self.assertEqual(
            "OR_1_099",
            assignment.sku,
            "thẻ đã có mã hợp lệ thì không được đổi dù product_type khớp một mã ERP khác — "
            "luật cũ ở docstring module (sku.py:1-59) vẫn phải giữ nguyên",
        )
        self.assertTrue(assignment.kept)

    def test_goc_tu_khai_product_type_cung_duoc_tra_theo_danh_muc(self):
        # Thẻ TASK-2026-05391 thật (đo 12/09): idea cha tự khai product_type =
        # "Punch Needle Ornament", sku="". plan.prefix/plan.prefix_source phải
        # phản ánh đúng nguồn ERP cho chính thẻ gốc, không chỉ cho thẻ con.
        root = _card("TASK-2026-05391", subject="Ornament", product_type="Punch Needle Ornament")
        plan = _plan(
            [root],
            self.book,
            root_id=root.task_id,
            ledger=SkuLedger(),
            project_id="PROJ-0018",
            categories=self.categories,
        )
        self.assertEqual("OL", plan.prefix, f"plan.prefix phải là OL, thực tế {plan.prefix!r}")
        self.assertEqual("erp-category", plan.prefix_source)

    def test_khong_truyen_categories_van_chay_dung_nhu_truoc(self):
        # Callers cũ (test_sku.py) gọi plan_skus không kèm categories — không
        # được bắt buộc tham số này, categories=None phải là mặc định an toàn.
        root = _card("TASK-2026-05391", subject="Khăn")
        child = _card(
            "TASK-2026-05392",
            parent="TASK-2026-05391",
            subject="Khăn con 1",
            meta="product: khăn tay",
        )
        plan = plan_skus(
            [root, child],
            self.book,
            root_id=root.task_id,
            ledger=SkuLedger(),
            project_id="PROJ-0018",
        )
        assignments = {item.task_id: item for item in plan.assignments}
        self.assertTrue(assignments[child.task_id].sku.startswith("KT_"))


class FlowWebServiceProductCategoryCacheTests(unittest.TestCase):
    """Danh mục sản phẩm ERP nhớ trong tiến trình, hết hạn tự đọc lại.

    Mô hình y hệt `load_sku_book` (`tests/test_sku_sheet_ttl.py`,
    `SHEET_TTL_SECONDS`/`SHEET_RETRY_SECONDS`) nhưng nguồn là ERP GraphQL
    (`_erp_graphql`), không phải Google Sheet — nên MỖI lượt đọc lại tốn đúng
    một request nằm trong trần ERP, thứ `load_sku_book` không có (Google Sheet
    không đi qua `_erp_graphql`/`RequestBudget`).
    """

    def setUp(self) -> None:
        from flow_web.service import FlowWebService

        self.FlowWebService = FlowWebService
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.log = patch("flow_web.service.log").start()
        self.addCleanup(patch.stopall)

        self.now = 0.0
        self.rows: List[Dict[str, Any]] = [dict(row) for row in CATEGORY_ROWS[:1]]  # chỉ dòng OL
        self.explodes = False
        self.calls: List[Any] = []

        tmp = Path(self._tmp.name)
        svc = FlowWebService.__new__(FlowWebService)
        svc._product_categories_path = lambda: tmp / "product_categories.json"
        svc._redact_erp_secret = lambda value: value
        svc._sheet_clock = lambda: self.now

        def fake_graphql(query, variables, operation_name, *, key, token):
            self.calls.append((key, token))
            if self.explodes:
                raise ConnectionError("ERP trả 503")
            return {"productCategories": {"rows": [dict(row) for row in self.rows]}}

        svc._erp_graphql = fake_graphql
        self.svc = svc

    def _load(self, at: float, **kwargs):
        self.now = at
        try:
            return self.svc.load_product_categories("erp-key", "erp-token", **kwargs)
        except AttributeError as exc:
            raise AssertionError(
                "FlowWebService chưa có load_product_categories(key, token, *, refresh=False) "
                f"— cache danh mục ERP (PRD mục 3.2) chưa được cài: {exc}"
            ) from exc

    def test_co_hang_so_nhip_doc_lai_va_nhip_thu_lai(self):
        self.assertTrue(
            hasattr(self.FlowWebService, "PRODUCT_CATEGORY_TTL_SECONDS"),
            "PRD đề xuất PRODUCT_CATEGORY_TTL_SECONDS = 1800.0 (30 phút) — danh mục 127 dòng "
            "đổi rất chậm ('modified' mới nhất 08/09), cần hằng số này để cấu hình/đo được",
        )
        self.assertEqual(
            1800.0,
            getattr(self.FlowWebService, "PRODUCT_CATEGORY_TTL_SECONDS", None),
            "PRD chốt nhịp nạp lại là 1800 giây (30 phút) — dài hơn SHEET_TTL_SECONDS (300s) "
            "vì danh mục ERP đổi chậm hơn bảng sheet nhiều",
        )
        self.assertEqual(
            self.FlowWebService.SHEET_RETRY_SECONDS,
            getattr(self.FlowWebService, "PRODUCT_CATEGORY_RETRY_SECONDS", None),
            "PRD đề xuất dùng lại đúng nhịp thử-lại-sau-lỗi của SHEET_RETRY_SECONDS (60s)",
        )

    def test_trong_han_khong_doc_lai_erp(self):
        self._load(0)
        ttl = self.FlowWebService.PRODUCT_CATEGORY_TTL_SECONDS if hasattr(
            self.FlowWebService, "PRODUCT_CATEGORY_TTL_SECONDS"
        ) else 1800.0
        book = self._load(ttl - 1)
        self.assertEqual(1, len(self.calls), "còn trong hạn thì không được gọi ERP lần hai")
        self.assertEqual(("OL", "erp-category"), book.lookup("Punch Needle Ornament"))

    def test_het_han_thi_doc_lai_va_thay_dong_moi(self):
        ttl = getattr(self.FlowWebService, "PRODUCT_CATEGORY_TTL_SECONDS", 1800.0)
        self._load(0)
        self.rows.append(dict(CATEGORY_ROWS[1]))  # thêm dòng OR

        before = self._load(ttl - 1)
        self.assertEqual(("", ""), before.lookup("Embroidered Ornament"), "chưa hết hạn thì chưa thấy dòng mới")

        after = self._load(ttl)
        self.assertEqual(2, len(self.calls), "hết hạn phải gọi lại ERP đúng một lần nữa")
        self.assertEqual(("OR", "erp-category"), after.lookup("Embroidered Ornament"))

    def test_doc_hong_thi_giu_ban_tot_va_cho_thu_lai(self):
        ttl = getattr(self.FlowWebService, "PRODUCT_CATEGORY_TTL_SECONDS", 1800.0)
        self._load(0)
        self.explodes = True

        book = self._load(ttl)
        self.assertEqual(2, len(self.calls), "hết hạn thì vẫn phải thử đọc lại")
        self.assertEqual(("OL", "erp-category"), book.lookup("Punch Needle Ornament"), "đọc hỏng không được làm mất bản tốt")
        self.assertTrue(self.log.warning.called, "đọc hỏng phải ghi log cảnh báo")

    def test_refresh_luon_doc_lai_bat_ke_con_han(self):
        self._load(0)
        self.rows.append(dict(CATEGORY_ROWS[1]))
        book = self._load(1, refresh=True)
        self.assertEqual(2, len(self.calls), "refresh=True phải đọc lại ngay dù còn hạn")
        self.assertEqual(("OR", "erp-category"), book.lookup("Embroidered Ornament"))

    def test_moi_lan_doc_lai_ton_dung_mot_luot_erp(self):
        # Danh mục 127 dòng trả về trong MỘT lượt gọi productCategories (brief
        # mục 2a) — không được phân trang thành nhiều request cho một lần đọc.
        self._load(0)
        self.assertEqual(
            1,
            len(self.calls),
            "một lượt nạp danh mục sản phẩm chỉ được tốn đúng 1 request ERP, để PRD "
            "tính đúng chi phí thêm vào trần request của làn nhanh SKU",
        )


class PlanErpSkusWiringTests(unittest.TestCase):
    """`plan_erp_skus` (flow_web/service.py) phải nạp danh mục và truyền vào plan_skus.

    Đọc thẳng source bằng regex — import cả `flow_web.service` (module rất
    nặng, gọi ERP thật nếu thiếu mock) không cần thiết chỉ để soát một chỗ nối
    dây. Ghim vào tên hàm/từ khoá gọi, không ghim vào cách xuống dòng.
    """

    def setUp(self) -> None:
        self.source = (REPO / "flow_web" / "service.py").read_text(encoding="utf-8")

    def test_plan_erp_skus_goi_load_product_categories(self):
        self.assertRegex(
            self.source,
            r"load_product_categories\(",
            "plan_erp_skus (flow_web/service.py:14244) chưa gọi load_product_categories — "
            "danh mục ERP chưa được nạp vào luồng cấp SKU thật, chỉ mới có trong test",
        )

    def test_categories_nap_ngay_canh_load_sku_book(self):
        self.assertRegex(
            self.source,
            r"book = self\.load_sku_book\(\)\s*\n\s*categories = self\.load_product_categories\(",
            "load_product_categories nên gọi ngay sau load_sku_book trong plan_erp_skus "
            "(flow_web/service.py gần dòng 14422), dùng chung key/token của lượt đánh số này",
        )

    def test_plan_skus_duoc_goi_kem_tu_khoa_categories(self):
        self.assertRegex(
            self.source,
            r"plan_skus\(\s*cards,\s*book,[^)]*categories\s*=",
            "lời gọi plan_skus bên trong hàm plan() lồng trong plan_erp_skus "
            "(flow_web/service.py:14429-14439) chưa truyền categories= — nguồn 'erp-category' "
            "sẽ không bao giờ được dùng dù load_product_categories đã nạp xong",
        )


if __name__ == "__main__":
    unittest.main()
