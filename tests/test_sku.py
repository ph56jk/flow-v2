"""Đánh số SKU cho một cây thẻ ERP — mô hình dự án/idea.

Người vận hành tạo thẻ idea cha, khai ``product: bờm``; bảng sheet nói ``bờm``
là ``BT``; người duyệt kéo từng thẻ idea con sang *Đang làm* và thẻ ấy nhận::

    {mã sản phẩm}_{số nhận dạng dự án}_{số nhận dạng idea}

Ba lời hứa khiến thứ này dùng được trên một cái bảng đang chạy thật, và là
thứ file này canh:

* **số giữa là của cả dự án** — mọi idea cha, mọi idea con trong cùng một
  board ERP mang chung một số, và board cũ giữ số của nó vĩnh viễn kể cả sau
  khi board mới đã mở;
* **số đuôi đếm xuyên dự án** — dự án một dừng ở ``BT_1_050`` thì dự án hai
  mở màn ``BT_2_051``, không bao giờ quay về ``001``;
* **mã đã cấp thì không đổi, số đã dùng thì không cấp lại** — kể cả số nằm
  trong mã gõ tay, kể cả khi số bị bỏ trống ở giữa.

Không có lượt gọi mạng nào trong file này: :mod:`flow_web.sku` chỉ nhận vào
những thẻ đã đọc sẵn, nên nó test được mà không chạm vào ERP thật.
"""

from __future__ import annotations

import asyncio
import collections
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from flow_web import pipeline, sku
from flow_web.erp_meta import parse_meta_block, render_meta_block, task_meta
from flow_web.schemas import SkuSyncRequest
from flow_web.sku import (
    IDEA_DIGITS,
    ProductBook,
    RequestBudget,
    Sku,
    SkuCard,
    SkuFastLane,
    SkuFastLaneConfig,
    SkuLedger,
    SkuPlan,
    board_is_hot,
    card_from_node,
    card_is_ready,
    cards_missing_sku,
    column_positions,
    derive_prefix,
    fill_cost,
    flatten_tree,
    hot_clusters,
    normalize_product,
    plan_skus,
    plan_tree,
    sku_pass,
    sku_pass_priority_waiting,
    sku_pass_yield_to_priority,
    strip_accents,
    task_number,
)


BOOK = ProductBook.from_mapping({"khăn tay": "KT", "bờm": "BT"})


def card(
    task_id: str,
    parent: str = "",
    meta: str = "",
    subject: str = "",
    board: str = "",
    project: str = "",
    status: str = "",
) -> SkuCard:
    """Một thẻ như ``taskFull`` trả về, rút gọn còn phần đánh số cần."""
    return SkuCard(task_id, parent, subject, task_meta({"meta": meta}), board, project, status)


def with_meta_line(item: SkuCard, line: str) -> SkuCard:
    """Bản sao thẻ với thêm một dòng thuộc tính — giữ nguyên board/project/status.

    ``replace`` chứ không dựng lại bằng vị trí, cùng lý do với ``flatten_tree``:
    thêm một trường vào :class:`SkuCard` thì bản sao ở đây không được lặng lẽ
    trả trường ấy về mặc định.
    """
    return replace(item, meta=task_meta({"meta": f"{item.meta.raw}\n{line}".strip()}))


def tree(*cards: SkuCard, **kwargs):
    """Mã của từng thẻ sau khi tính, dạng ``{thẻ: mã}``.

    Mặc định gắn cụm vào một board có mã (``PROJ-0170``) vì board ERP thật nào
    cũng có mã dự án; test nào canh riêng lối thiếu mã dự án thì tự truyền
    ``project_id=""``.
    """
    kwargs.setdefault("root_id", cards[0].task_id)
    kwargs.setdefault("project_id", "PROJ-0170")
    plan = plan_skus(cards, BOOK, **kwargs)
    return {item.task_id: item.sku for item in plan.assignments}, plan


class NormalizeTests(unittest.TestCase):
    def test_strips_vietnamese_accents(self):
        self.assertEqual(strip_accents("bờm"), "bom")
        self.assertEqual(strip_accents("khăn tay"), "khan tay")

    def test_d_with_stroke_is_not_a_combining_mark(self):
        """``đ`` không tách được bằng NFD, nên nó phải được xử riêng."""
        self.assertEqual(strip_accents("đèn"), "den")

    def test_product_key_ignores_accents_case_and_spacing(self):
        for spelling in ("khăn tay", "Khan  Tay", "KHĂN-TAY", " khan_tay "):
            self.assertEqual(normalize_product(spelling), "khan tay", spelling)

    def test_book_matches_however_the_card_spells_it(self):
        """Bảng gõ có dấu, thẻ gõ không dấu — vẫn phải khớp."""
        self.assertEqual(BOOK.lookup("khan tay"), ("KT", "book"))
        self.assertEqual(BOOK.lookup("KHĂN TAY"), ("KT", "book"))

    def test_missing_row_is_derived_and_says_so(self):
        prefix, source = BOOK.lookup("túi vải")
        self.assertEqual(prefix, "TV")
        self.assertEqual(source, "derived")

    def test_derived_prefix_shapes(self):
        self.assertEqual(derive_prefix("khan tay"), "KT")
        self.assertEqual(derive_prefix("bờm"), "BO")
        self.assertEqual(derive_prefix(""), "")

    def test_no_product_name_derives_nothing(self):
        """Không có tên sản phẩm thì không có gì để đoán — và không được đoán."""
        self.assertEqual(BOOK.lookup(""), ("", ""))


class ProductBookTests(unittest.TestCase):
    def test_reads_a_sheet_whatever_the_columns_are_called(self):
        book = ProductBook.from_rows(
            [
                {"Product Name": "khăn tay", "SKU Prefix": "kt"},
                {"Product Name": "bờm", "SKU Prefix": "BT"},
            ]
        )
        self.assertEqual(book.as_dict(), {"khan tay": "KT", "bom": "BT"})

    def test_the_real_workshop_sheet_shape(self):
        """Bảng thật của xưởng: cột tên là ``TEN HANG``, cạnh nó là tên tiếng Anh.

        Cột ``TEN MOI``/``TEN KHAI BAO`` là tên khai hải quan (``Headband``),
        còn thẻ ERP thì người ta gõ ``bờm``.  Nhận nhầm cột tiếng Anh làm tên
        sản phẩm thì bảng có đủ dòng mà tra vẫn trượt hết.
        """
        book = ProductBook.from_rows(
            [
                {
                    "TEN HANG": "bờm",
                    "TEN MỚI": "Headband",
                    "TEN KHAI BAO": "Polyester headband",
                    "SKU": "BT",
                },
                {
                    "TEN HANG": "khăn tay",
                    "TEN MỚI": "Handkerchief",
                    "TEN KHAI BAO": "linen handkerchief",
                    "SKU": "HA",
                },
            ]
        )
        self.assertEqual({"bom": "BT", "khan tay": "HA"}, book.as_dict())
        self.assertEqual(("BT", "book"), book.lookup("bờm"))

    def test_the_sheet_calls_the_name_column_product_type(self):
        """Sheet của xưởng đặt tên cột tên hàng là ``product_type``.

        Cột ấy ghi tiếng Việt (``khăn tay``), còn ``TÊN MỚI`` mới là tiếng Anh.
        Không nhận ``product_type`` thì cả bảng 55 dòng nạp về **0 dòng**: bí
        danh tiếng Anh vẫn vào được, nên bảng trông như có chữ mà tra tên tiếng
        Việt thì trượt sạch, và mọi mã đều rơi xuống mã bot tự đoán.
        """
        book = ProductBook.from_rows(
            [
                {
                    "product_group": "physical",
                    "product_type": "khăn tay",
                    "TÊN MỚI": "Handkerchief",
                    "SKU": "HA",
                },
                {
                    "product_group": "handmade",
                    "product_type": "tạp dề",
                    "TÊN MỚI": "Apron",
                    "SKU": "TD",
                },
            ]
        )
        self.assertEqual({"khan tay": "HA", "tap de": "TD"}, book.as_dict())
        self.assertEqual(("HA", "book"), book.lookup("khăn tay"))

    def test_rows_missing_either_half_are_skipped(self):
        book = ProductBook.from_rows(
            [{"product": "khăn tay"}, {"sku": "XX"}, {"product": "bờm", "sku": "BT"}]
        )
        self.assertEqual(book.as_dict(), {"bom": "BT"})

    def test_merged_prefers_the_nearer_table(self):
        near = ProductBook.from_mapping({"bờm": "BX"})
        self.assertEqual(near.merged(BOOK).as_dict()["bom"], "BX")
        self.assertEqual(near.merged(BOOK).as_dict()["khan tay"], "KT")

    def test_a_cell_with_several_codes_keeps_the_first_and_remembers_the_rest(self):
        """Ô ``KT,OR,HK`` là ba biến thể của một mặt hàng, không phải mã ``KTORHK``."""
        book = ProductBook.from_mapping({"khung thêu": "KT,OR,HK"})
        self.assertEqual("KT", book.prefix_for("khung theu"))
        self.assertEqual(("KT", "OR", "HK"), book.options("khung thêu"))
        # Lưu xuống đĩa rồi đọc lại không được làm rơi mất hai mã phụ.
        self.assertEqual(book.as_dict(), ProductBook.from_mapping(book.as_dict()).as_dict())


    def test_a_board_name_that_wraps_a_row_still_finds_it(self):
        """Bảng ghi ``ornament thêu``, board tên ``XMAS Ornament Thêu Tròn``.

        Không ai đi đặt tên board đúng bằng tên trong bảng: board còn phải mang
        mùa, mang hình dáng.  Đòi khớp từng chữ thì cái bảng đầy đủ vẫn trượt,
        và mã rơi về ``derive_prefix`` — ``XOTT``, một mã chưa từng có trong
        bảng nào.  Đường nhận ảnh đã đọc tên board theo lối này rồi; đường đánh
        số phải đọc giống hệt, không thì hai đường nói hai sản phẩm khác nhau.
        """
        book = ProductBook.from_mapping({"ornament thêu": "OR", "bờm": "BT"})
        self.assertEqual(("OR", "book-contains"), book.lookup("XMAS Ornament Thêu Tròn"))

    def test_the_row_that_says_more_wins_when_two_rows_both_fit(self):
        """``ornament thêu`` thắng ``thêu``: dòng nói rõ hơn thì đúng hơn."""
        book = ProductBook.from_mapping({"ornament thêu": "OR", "thêu": "TH"})
        self.assertEqual("OR", book.prefix_for("XMAS Ornament Thêu Tròn"))

    def test_an_exact_row_never_loses_to_a_row_hiding_inside_the_name(self):
        """Khớp đủ tên vẫn thắng, và vẫn khai nguồn là ``book``."""
        book = ProductBook.from_mapping({"thêu": "TH", "ornament thêu": "OR"})
        self.assertEqual(("TH", "book"), book.lookup("thêu"))

    def test_half_a_word_is_not_a_row(self):
        """``sổ`` nằm trong ``sofa`` là trùng chữ, không phải trùng hàng.

        Cắt theo chữ thì mã của cuốn sổ nhảy sang cái ghế.  Chỉ khớp trọn từ.
        """
        book = ProductBook.from_mapping({"sổ": "WB"})
        self.assertEqual(("SO", "derived"), book.lookup("sofa"))


class SkuShapeTests(unittest.TestCase):
    """Hình dạng một mã.  Bẫy chính: thứ tự trường vừa đổi thành (dự án, idea).

    ``BT_2_051`` giờ đọc là *bờm, dự án thứ hai, idea thứ 51* — cả bảng lệch
    một nấc nếu ai đó đọc số giữa thành idea như bản cũ.
    """

    def test_the_middle_number_is_the_project_and_the_tail_is_the_idea(self):
        parsed = Sku.parse("BT_2_051")
        self.assertEqual("BT", parsed.prefix)
        self.assertEqual(2, parsed.project)
        self.assertEqual(51, parsed.idea)
        self.assertEqual("BT_2_051", Sku("BT", 2, 51).text)
        self.assertEqual(parsed, Sku(prefix="BT", project=2, idea=51))

    def test_the_idea_number_wears_three_digits(self):
        """``001`` chứ không phải ``1`` — đuôi mã là thứ người ta đọc trên nhãn."""
        self.assertEqual(3, IDEA_DIGITS)
        self.assertEqual("BT_1_007", Sku("BT", 1, 7).text)

    def test_lower_case_is_the_same_code(self):
        """Người gõ tay ``kt_2_009``; đó là mã của ``KT_2_009``, không phải mã mới."""
        self.assertEqual(Sku.parse("kt_2_009"), Sku("KT", 2, 9))

    def test_half_typed_codes_are_not_codes(self):
        """``KT_1`` trên thẻ gốc là ghi chú dở, không giữ chỗ cho số nào."""
        for text in ("KT_1", "khantay_101", "", "KT__1", "1_2_003"):
            self.assertIsNone(Sku.parse(text), text)

    def test_task_number_orders_by_creation(self):
        self.assertLess(task_number("TASK-2026-00906"), task_number("TASK-2026-02118"))

    def test_unreadable_task_id_sorts_last(self):
        self.assertGreater(task_number("nothing"), task_number("TASK-2026-99999"))


class SpecExampleTests(unittest.TestCase):
    """Từng dòng ví dụ của chủ sản phẩm, chốt bằng chuỗi mã thật.

    > idea con đầu tiên kéo sang lấy ``BT_1_001``, các idea kéo sang tiếp theo
    > ``BT_1_002``, ``BT_1_003``... Tạo thêm task idea cha trong dự án đó thì
    > số nhận dạng dự án KHÔNG đổi. Dự án bờm thứ hai: ``BT_2_xxx``. Dự án một
    > dừng ở ``BT_1_050`` thì dự án hai bắt đầu ``BT_2_051``.

    Mỗi test chốt cả ``role``/``project``/``idea`` chứ không chỉ so chuỗi:
    chuỗi đúng mà trường lệch nghĩa là cả bảng đang lệch một tầng và mọi phép
    đọc-lại-mã về sau sẽ hiểu sai.
    """

    def test_the_first_ideas_of_the_first_project_count_bt_1_001_002_003(self):
        plan = plan_skus(
            [
                card("TASK-2026-00202", meta="product: bờm", status="Working"),
                card("TASK-2026-00906", "TASK-2026-00202", status="Working"),
                card("TASK-2026-00907", "TASK-2026-00202", status="Working"),
                card("TASK-2026-00908", "TASK-2026-00202", status="Working"),
            ],
            BOOK,
            root_id="TASK-2026-00202",
            project_id="PROJ-0170",
        )
        self.assertEqual(
            [
                ("TASK-2026-00906", "BT_1_001", "idea", 1, 1),
                ("TASK-2026-00907", "BT_1_002", "idea", 1, 2),
                ("TASK-2026-00908", "BT_1_003", "idea", 1, 3),
            ],
            [(i.task_id, i.sku, i.role, i.project, i.idea) for i in plan.assignments],
        )

    def test_a_second_parent_idea_in_the_same_project_keeps_the_middle_number(self):
        """Bao nhiêu idea cha trong một dự án cũng chung một số dự án.

        Bẫy: mô hình cũ cho mỗi idea cha một số giữa riêng — nếu ai đó quay
        lại lối đó, cây thứ hai ở đây sẽ ra ``BT_2_003`` thay vì ``BT_1_003``.
        """
        so = SkuLedger()
        first = plan_skus(
            [card("TASK-1", meta="product: bờm"), card("TASK-2", "TASK-1"), card("TASK-3", "TASK-1")],
            BOOK, root_id="TASK-1", ledger=so, project_id="PROJ-0170",
        )
        so.observe_plan(first)
        second = plan_skus(
            [card("TASK-5", meta="product: bờm"), card("TASK-6", "TASK-5"), card("TASK-7", "TASK-5")],
            BOOK, root_id="TASK-5", ledger=so, project_id="PROJ-0170",
        )
        self.assertEqual(["BT_1_001", "BT_1_002"], [i.sku for i in first.assignments])
        self.assertEqual(["BT_1_003", "BT_1_004"], [i.sku for i in second.assignments])
        self.assertEqual({1}, {i.project for i in (*first.assignments, *second.assignments)})
        self.assertEqual([3, 4], [i.idea for i in second.assignments])

    def test_the_second_project_opens_at_bt_2_051_when_the_first_stopped_at_050(self):
        """Số giữa tăng theo dự án, số đuôi chạy tiếp xuyên dự án — nguyên văn spec."""
        so = SkuLedger()
        so.observe_sku("BT_1_050", "PROJ-BOM-1")
        plan = plan_skus(
            [card("TASK-9", meta="product: bờm"), card("TASK-10", "TASK-9")],
            BOOK, root_id="TASK-9", ledger=so, project_id="PROJ-BOM-2",
        )
        opened = plan.assignments[0]
        self.assertEqual("BT_2_051", opened.sku)
        self.assertEqual(("idea", 2, 51), (opened.role, opened.project, opened.idea))

    def test_coming_back_to_the_old_project_restores_its_old_number(self):
        """Cái bẫy đắt nhất: sổ quên board nào mang số nào.

        Sổ chỉ nhớ "bờm đã có 2 dự án" thì lượt quay lại dự án một sẽ được cấp
        số 3 — và hai thẻ cạnh nhau trên cùng bảng mang hai số dự án khác nhau,
        trong khi mã cũ đã in ra nhãn rồi.
        """
        so = SkuLedger()
        first = plan_skus(
            [card("TASK-1", meta="product: bờm"), card("TASK-2", "TASK-1")],
            BOOK, root_id="TASK-1", ledger=so, project_id="PROJ-1",
        )
        so.observe_plan(first)
        second = plan_skus(
            [card("TASK-5", meta="product: bờm"), card("TASK-6", "TASK-5")],
            BOOK, root_id="TASK-5", ledger=so, project_id="PROJ-2",
        )
        so.observe_plan(second)
        back = plan_skus(
            [card("TASK-8", meta="product: bờm"), card("TASK-9", "TASK-8")],
            BOOK, root_id="TASK-8", ledger=so, project_id="PROJ-1",
        )
        self.assertEqual([1], [i.project for i in first.assignments])
        self.assertEqual([2], [i.project for i in second.assignments])
        self.assertEqual([1], [i.project for i in back.assignments], "board cũ phải về đúng số cũ")
        self.assertEqual(["BT_1_003"], [i.sku for i in back.assignments])

    def test_a_kept_code_reteaches_which_number_this_board_wears(self):
        """Mất sổ không được thành mất ánh xạ board → số dự án.

        Mã đang nằm trên thẻ là lời khai chắc nhất: sổ trống mà thấy ``BT_2_006``
        trên bảng thì thẻ trắng bên cạnh phải nhận ``BT_2_007``, không phải
        ``BT_3_007``.
        """
        so = SkuLedger()
        plan = plan_skus(
            [
                card("TASK-1", meta="product: bờm"),
                card("TASK-2", "TASK-1", "sku: BT_2_006"),
                card("TASK-3", "TASK-1"),
            ],
            BOOK, root_id="TASK-1", ledger=so, project_id="PROJ-X",
        )
        fresh = {i.task_id: i for i in plan.assignments}["TASK-3"]
        self.assertEqual("BT_2_007", fresh.sku)
        self.assertEqual(2, fresh.project)
        # Và sổ đã nhớ hẳn: hỏi lại không tiêu thêm số.
        self.assertEqual(2, so.project_number("BT", "PROJ-X"))
        self.assertEqual(2, so.floor_project("BT"))


class ReadyGateTests(unittest.TestCase):
    """Chỉ thẻ đã kéo sang *Đang làm* mới được cấp mã.

    Số nhận dạng idea tiêu rồi không đòi lại được, nên thẻ còn ở *Cần làm* —
    thứ có thể bị bỏ — phải trắng mã.  Nhưng chặn theo phỏng đoán thì mọi lối
    gọi không đọc cột đứng im, nên thẻ không nói được cột của mình thì đi qua.
    """

    def test_a_card_still_in_todo_gets_no_code_and_burns_no_number(self):
        """Thẻ chưa duyệt bị bỏ qua, và số nó *không* nhận không được biến mất."""
        skus, plan = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202", status="Open"),
            card("TASK-2026-00907", "TASK-2026-00202", status="Working"),
        )
        self.assertNotIn("TASK-2026-00906", skus)
        self.assertEqual("KT_1_001", skus["TASK-2026-00907"], "số 001 không bị thẻ chưa duyệt tiêu mất")
        self.assertEqual((("TASK-2026-00906", "chưa sang cột Đang làm"),), plan.skipped)

    def test_a_cancelled_card_never_gets_a_code(self):
        skus, plan = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202", status="Cancelled"),
        )
        self.assertEqual({}, skus)
        self.assertEqual(["TASK-2026-00906"], [task for task, _ in plan.skipped])

    def test_a_card_with_no_column_is_not_blocked(self):
        """Rỗng nghĩa là *người gọi không đưa cột*, không nghĩa là thẻ chưa sẵn sàng.

        Chặn ở đây là làm đứng im mọi lối gọi không kèm cột — hỏng kiểu im lặng.
        """
        skus, _ = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202", status=""),
        )
        self.assertEqual({"TASK-2026-00906": "KT_1_001"}, skus)

    def test_an_unrecognised_column_is_not_blocked_either(self):
        """Bảng đổi tên cột là chuyện của người, không phải lý do ngừng cấp mã."""
        skus, _ = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202", status="Cột lạ ai đó vừa đặt"),
        )
        self.assertEqual({"TASK-2026-00906": "KT_1_001"}, skus)

    def test_columns_past_doing_still_get_codes(self):
        """Thẻ đã đi qua *Đang làm* mà còn trắng mã là thẻ bị sót — phải điền nốt."""
        skus, _ = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202", status="Pending Review"),
            card("TASK-2026-00907", "TASK-2026-00202", status="Completed"),
        )
        self.assertEqual({"TASK-2026-00906": "KT_1_001", "TASK-2026-00907": "KT_1_002"}, skus)

    def test_card_is_ready_answers_for_every_kind_of_column(self):
        for status in ("Open", "To do", "Cần làm", "Cancelled", "Đã huỷ"):
            with self.subTest(status=status):
                self.assertFalse(card_is_ready(card("TASK-1", status=status)))
        for status in ("", "Working", "Đang làm", "Pending Review", "Completed", "Cột lạ"):
            with self.subTest(status=status):
                self.assertTrue(card_is_ready(card("TASK-1", status=status)))

    def test_no_card_at_all_is_not_ready(self):
        """``None`` là *không có thẻ*, khác với *thẻ không khai cột* — không được cấp."""
        self.assertFalse(card_is_ready(None))


class ParentIdeaTests(unittest.TestCase):
    """Thẻ idea cha không bao giờ có mã.

    Nó là chỗ khai ``product:`` và chỗ ảnh bắn vào; cấp mã cho nó là nó ăn mất
    ``_001`` và thẻ con đầu tiên — thứ thật sự lên listing — mang ``_002``.
    """

    def test_the_root_card_is_never_assigned_and_never_in_changes(self):
        _, plan = tree(
            card("TASK-2026-00202", meta="product: khăn tay", status="Working"),
            card("TASK-2026-00906", "TASK-2026-00202", status="Working"),
        )
        self.assertNotIn("TASK-2026-00202", {i.task_id for i in plan.assignments})
        self.assertNotIn("TASK-2026-00202", {i.task_id for i in plan.changes})
        self.assertEqual("TASK-2026-00202", plan.root_id)

    def test_even_a_root_on_a_named_board_stays_blank(self):
        """Bẫy hồi quy từ mô hình cũ: lối "tên bảng" từng cấp mã cho chính thẻ gốc.

        Giờ chỉ còn một luật — gốc cụm là idea cha, trắng mã — kể cả khi tên
        sản phẩm đến từ tên bảng chứ không từ ``product:``.
        """
        plan = plan_skus(
            [
                card("TASK-1", board="khăn tay", project="PROJ-0170"),
                card("TASK-2", "TASK-1", board="khăn tay", project="PROJ-0170"),
            ],
            BOOK,
            root_id="TASK-1",
        )
        self.assertEqual(
            [("TASK-2", "KT_1_001", "idea", 1, 1)],
            [(i.task_id, i.sku, i.role, i.project, i.idea) for i in plan.assignments],
        )

    def test_grandchildren_of_the_parent_idea_are_numbered_too(self):
        """Cây sâu hơn hai tầng: cháu, chắt của idea cha đều là idea con có mã.

        Bẫy: phép đi tầng dừng ở con trực tiếp thì chắt trắng mã vĩnh viễn mà
        không ai báo — ``cards_missing_sku`` sẽ đếm nó, kế hoạch lại không cấp.
        """
        plan = plan_skus(
            [
                card("TASK-2026-00202", meta="product: bờm"),
                card("TASK-2026-00906", "TASK-2026-00202"),
                card("TASK-2026-00920", "TASK-2026-00906"),
                card("TASK-2026-00921", "TASK-2026-00920"),
            ],
            BOOK,
            root_id="TASK-2026-00202",
            project_id="PROJ-0170",
        )
        self.assertEqual(
            [
                ("TASK-2026-00906", "BT_1_001", "idea", 1, 1),
                ("TASK-2026-00920", "BT_1_002", "idea", 1, 2),
                ("TASK-2026-00921", "BT_1_003", "idea", 1, 3),
            ],
            [(i.task_id, i.sku, i.role, i.project, i.idea) for i in plan.assignments],
        )

    def test_every_assignment_wears_the_idea_role(self):
        """Chỉ còn một vai.  Vai ``product`` hay tầng nào khác xuất hiện lại là
        mô hình cũ đang lẻn về."""
        _, plan = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202"),
            card("TASK-2026-00920", "TASK-2026-00906"),
        )
        self.assertEqual({"idea"}, {i.role for i in plan.assignments})
        self.assertEqual({"idea"}, {i.as_dict()["role"] for i in plan.assignments})

    def test_assignment_as_dict_speaks_the_new_field_names(self):
        """API ra ngoài: khoá ``project``/``idea``, không còn khoá ``product``."""
        _, plan = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202"),
        )
        rendered = plan.assignments[0].as_dict()
        self.assertEqual(1, rendered["project"])
        self.assertEqual(1, rendered["idea"])
        self.assertNotIn("product", rendered)
        self.assertEqual("PROJ-0170", plan.as_dict()["project"])


class ExistingCodesTests(unittest.TestCase):
    def test_a_card_that_has_a_code_keeps_it(self):
        _, plan = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202", "sku: KT_4_001"),
        )
        held = plan.assignments[0]
        self.assertEqual("KT_4_001", held.sku)
        self.assertTrue(held.kept)
        self.assertEqual(("idea", 4, 1), (held.role, held.project, held.idea))
        self.assertEqual((), plan.changes)

    def test_running_twice_changes_nothing(self):
        cards = [
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202"),
            card("TASK-2026-00907", "TASK-2026-00202"),
            card("TASK-2026-00920", "TASK-2026-00907"),
        ]
        first = plan_skus(cards, BOOK, root_id=cards[0].task_id, project_id="PROJ-0170")
        written = {item.task_id: item.sku for item in first.assignments}
        again = [
            with_meta_line(item, f"sku: {written[item.task_id]}") if item.task_id in written else item
            for item in cards
        ]
        second = plan_skus(again, BOOK, root_id=cards[0].task_id, project_id="PROJ-0170")
        self.assertEqual((), second.changes)
        self.assertEqual({item.task_id: item.sku for item in second.assignments}, written)

    def test_a_gap_left_by_a_deleted_card_is_not_handed_out_again(self):
        """Idea 1 và 5 đang dùng thì idea mới là 6 — số 2 có thể đã đi ra ngoài."""
        skus, _ = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202", "sku: KT_1_001"),
            card("TASK-2026-00907", "TASK-2026-00202", "sku: KT_1_005"),
            card("TASK-2026-00908", "TASK-2026-00202"),
        )
        self.assertEqual("KT_1_006", skus["TASK-2026-00908"])

    def test_a_hand_typed_lower_case_code_still_reserves_its_numbers(self):
        skus, _ = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202", "sku: kt_3_001"),
            card("TASK-2026-00907", "TASK-2026-00202"),
        )
        # Mã gõ thường dạy cả số dự án của board lẫn số idea đã chiếm.
        self.assertEqual("KT_3_002", skus["TASK-2026-00907"])

    def test_half_typed_code_on_the_root_does_not_block_the_board(self):
        """``sku: KT_1`` gõ dở trên thẻ gốc không được giữ chỗ cho số nào."""
        skus, _ = tree(
            card("TASK-2026-00202", meta="product: khăn tay\nsku: KT_1"),
            card("TASK-2026-00906", "TASK-2026-00202"),
        )
        self.assertEqual("KT_1_001", skus["TASK-2026-00906"])

    def test_order_of_the_input_does_not_change_the_result(self):
        """ERP trả thẻ theo cột, không theo thứ tự ra đời; mã phải theo thứ tự ra đời."""
        cards = [
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00908", "TASK-2026-00202"),
            card("TASK-2026-00906", "TASK-2026-00202"),
            card("TASK-2026-00907", "TASK-2026-00202"),
        ]
        plan = plan_skus(cards, BOOK, root_id="TASK-2026-00202", project_id="PROJ-0170")
        skus = {item.task_id: item.sku for item in plan.assignments}
        self.assertEqual("KT_1_001", skus["TASK-2026-00906"])
        self.assertEqual("KT_1_002", skus["TASK-2026-00907"])
        self.assertEqual("KT_1_003", skus["TASK-2026-00908"])

    def test_a_number_is_never_handed_to_two_cards(self):
        """Đuôi số là số đếm duy nhất của cả sản phẩm — trùng là hai thẻ một mã."""
        _, plan = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202", "sku: KT_1_002"),
            card("TASK-2026-00907", "TASK-2026-00202"),
            card("TASK-2026-00920", "TASK-2026-00906"),
            card("TASK-2026-00930", "TASK-2026-00907"),
        )
        tails = [item.idea for item in plan.assignments]
        self.assertEqual(len(tails), len(set(tails)))


class HandTypedCodeTests(unittest.TestCase):
    """Mã người ta tự gõ mà máy đọc không ra thì để yên, và nói ra là đã để yên.

    Đo trên bảng thật: một thẻ mang ``sku: khantay_101``.  Nếu kế hoạch coi nó
    là thẻ trống mà hứa cấp mã mới, còn lượt ghi thấy ô ``sku`` không rỗng nên
    nhường người, thì mọi lượt chạy sau đều báo còn một thẻ chưa ghi, mãi mãi.
    """

    def test_a_code_that_does_not_parse_is_left_to_its_owner(self):
        _, plan = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00911", "TASK-2026-00202", "sku: khantay_101"),
        )
        self.assertEqual((), plan.assignments)
        self.assertEqual(1, len(plan.skipped))
        task_id, reason = plan.skipped[0]
        self.assertEqual("TASK-2026-00911", task_id)
        # Mã hiện ra ở dạng đã gấp hoa, đúng dạng phần đánh số nhìn thấy nó.
        self.assertIn("KHANTAY_101", reason)

    def test_it_does_not_hold_up_the_cards_beside_it(self):
        skus, _ = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00911", "TASK-2026-00202", "sku: khantay_101"),
            card("TASK-2026-00912", "TASK-2026-00202"),
        )
        self.assertEqual({"TASK-2026-00912": "KT_1_001"}, skus)

    def test_the_plan_and_the_write_agree_so_a_rerun_settles(self):
        # Chỉ thẻ nào kế hoạch hứa ghi mới được ghi; chạy lại là không còn gì.
        cards = [
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00911", "TASK-2026-00202", "sku: khantay_101"),
            card("TASK-2026-00912", "TASK-2026-00202"),
        ]
        first = plan_skus(cards, BOOK, root_id=cards[0].task_id, project_id="PROJ-0170")
        written = {item.task_id: item.sku for item in first.changes}
        again = [
            with_meta_line(item, f"sku: {written[item.task_id]}") if item.task_id in written else item
            for item in cards
        ]
        second = plan_skus(again, BOOK, root_id=cards[0].task_id, project_id="PROJ-0170")
        self.assertEqual((), second.changes)


class RenumberTests(unittest.TestCase):
    """Đánh số lại cả cây khi cây đã ghi sai luật.

    Mặc định mã đã có là bất khả xâm phạm; ``renumber=True`` là ngoại lệ người
    vận hành phải tự yêu cầu — và kể cả khi ấy, sổ vẫn giữ mốc: đánh lại là để
    cây tự nhất quán, không phải để thu hồi số đã đi ra ngoài phần mềm.
    """

    def test_by_default_an_existing_code_is_never_touched(self):
        _, plan = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202", "sku: KT_1_001"),
            card("TASK-2026-00907", "TASK-2026-00202", "sku: KT_1_002"),
        )
        self.assertEqual((), plan.changes)

    def test_renumbering_lays_the_whole_tree_out_again(self):
        cards = (
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202", "sku: KT_9_004"),
            card("TASK-2026-00907", "TASK-2026-00202", "sku: KT_4_009"),
            card("TASK-2026-00908", "TASK-2026-00202"),
        )
        plan = plan_skus(cards, BOOK, root_id="TASK-2026-00202", renumber=True, project_id="PROJ-0170")
        self.assertEqual(
            [
                ("TASK-2026-00906", "KT_1_001", 1, 1),
                ("TASK-2026-00907", "KT_1_002", 1, 2),
                ("TASK-2026-00908", "KT_1_003", 1, 3),
            ],
            [(i.task_id, i.sku, i.project, i.idea) for i in plan.assignments],
        )
        self.assertEqual(3, len(plan.changes))

    def test_renumbering_does_not_walk_back_under_the_ledger_floor(self):
        """Cây khác vẫn giữ mã cũ của họ; đánh lại từ 001 là đâm thẳng vào đó."""
        so = SkuLedger()
        so.observe_sku("KT_1_010", "PROJ-A")
        plan = plan_skus(
            [
                card("TASK-2026-00202", meta="product: khăn tay"),
                card("TASK-2026-00906", "TASK-2026-00202", "sku: KT_1_001"),
                card("TASK-2026-00907", "TASK-2026-00202", "sku: KT_1_002"),
            ],
            BOOK, root_id="TASK-2026-00202", renumber=True, ledger=so, project_id="PROJ-A",
        )
        self.assertEqual(
            [("KT_1_011", 1, 11), ("KT_1_012", 1, 12)],
            [(i.sku, i.project, i.idea) for i in plan.assignments],
        )

    def test_renumbering_still_leaves_a_hand_typed_code_alone(self):
        """Bật đánh số lại không phải là giấy phép ghi đè chữ người ta gõ."""
        cards = (
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202", "sku: khantay_101"),
            card("TASK-2026-00907", "TASK-2026-00202", "sku: KT_2_001"),
        )
        plan = plan_skus(cards, BOOK, root_id="TASK-2026-00202", renumber=True, project_id="PROJ-0170")
        self.assertNotIn("TASK-2026-00906", {item.task_id for item in plan.assignments})
        self.assertEqual(["TASK-2026-00906"], [task for task, _ in plan.skipped])

    def test_renumbering_twice_settles(self):
        cards = (
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202", "sku: KT_9_001"),
            card("TASK-2026-00907", "TASK-2026-00202", "sku: KT_4_001"),
        )
        first = plan_skus(cards, BOOK, root_id="TASK-2026-00202", renumber=True, project_id="PROJ-0170")
        settled = tuple(
            card(item.task_id, "TASK-2026-00202", f"sku: {item.sku}")
            for item in first.assignments
        )
        second = plan_skus(
            (card("TASK-2026-00202", meta="product: khăn tay"), *settled),
            BOOK,
            root_id="TASK-2026-00202",
            renumber=True,
            project_id="PROJ-0170",
        )
        self.assertEqual(
            {item.task_id: item.sku for item in first.assignments},
            {item.task_id: item.sku for item in second.assignments},
        )


class LedgerTests(unittest.TestCase):
    """Sổ số đã phát — trí nhớ nằm ngoài mọi cây thẻ.

    Ba phần, ba câu hỏi: ``project_seq`` — bờm đã có mấy dự án; ``idea_seq`` —
    bờm đã có tổng bao nhiêu idea; ``projects`` — **board nào** mang số mấy.
    Phần thứ ba là thứ hai con số kia không thay được: thiếu nó thì board cũ
    quay lại bị cấp số mới.
    """

    def test_an_empty_ledger_starts_everyone_at_one(self):
        so = SkuLedger()
        self.assertEqual(0, so.floor_project("BT"))
        self.assertEqual(0, so.floor_idea("BT"))

    def test_a_code_teaches_the_ledger_both_numbers_and_the_board(self):
        so = SkuLedger()
        self.assertTrue(so.observe_sku("BT_2_006", "PROJ-B"))
        self.assertEqual(2, so.floor_project("BT"))
        self.assertEqual(6, so.floor_idea("BT"))
        # Board đã có số thì hỏi lại phải ra đúng số ấy, không tiêu số mới.
        self.assertEqual(2, so.project_number("BT", "PROJ-B"))
        self.assertEqual(2, so.floor_project("BT"))

    def test_project_number_hands_each_board_one_number_forever(self):
        so = SkuLedger()
        self.assertEqual(1, so.project_number("BT", "PROJ-1"))
        self.assertEqual(2, so.project_number("BT", "PROJ-2"))
        self.assertEqual(1, so.project_number("BT", "PROJ-1"), "board cũ giữ số cũ vĩnh viễn")
        self.assertEqual(2, so.floor_project("BT"))
        # Mã board so không phân biệt hoa thường: cùng một board, một số.
        self.assertEqual(1, so.project_number("BT", "proj-1"))
        self.assertEqual(0, so.project_number("", "PROJ-1"), "chưa có tên SKU thì chưa có gì để đếm")

    def test_the_prefix_is_read_the_way_people_type_it(self):
        # Người gõ tay lúc hoa lúc thường; sổ mà phân biệt thì nó tách làm hai.
        so = SkuLedger()
        so.observe_sku("bt_1_003")
        self.assertEqual(3, so.floor_idea("  BT "))

    def test_a_line_that_is_not_a_code_teaches_nothing(self):
        so = SkuLedger()
        self.assertFalse(so.observe_sku("chưa có mã"))
        self.assertFalse(so.observe_sku(None))
        self.assertEqual({"project_seq": {}, "idea_seq": {}, "projects": {}}, so.as_dict())

    def test_the_ledger_only_ever_moves_up(self):
        # Một thẻ cũ đọc sau thẻ mới không được kéo mốc tụt xuống, nếu không
        # lượt cấp kế tiếp sẽ đâm vào mã đã in lên nhãn rồi.
        so = SkuLedger()
        so.observe_sku("BT_3_009")
        self.assertFalse(so.observe_sku("BT_1_002"))
        self.assertEqual((3, 9), (so.floor_project("BT"), so.floor_idea("BT")))

    def test_two_prefixes_do_not_borrow_each_other_numbers(self):
        so = SkuLedger()
        so.observe_sku("BT_4_012")
        self.assertEqual(0, so.floor_project("KT"))
        self.assertEqual(0, so.floor_idea("KT"))

    def test_a_ledger_survives_a_trip_through_disk_with_all_three_parts(self):
        """``as_dict`` → ``from_mapping`` không được rơi phần nào — nhất là ánh xạ board."""
        so = SkuLedger()
        so.observe_sku("BT_1_007", "PROJ-1")
        so.project_number("KT", "PROJ-9")
        back = SkuLedger.from_mapping(so.as_dict())
        self.assertEqual(so.as_dict(), back.as_dict())
        self.assertEqual((1, 7), (back.floor_project("BT"), back.floor_idea("BT")))
        # Ánh xạ board sống sót: hỏi lại board cũ không tiêu số mới.
        self.assertEqual(1, back.project_number("BT", "PROJ-1"))
        self.assertEqual(1, back.project_number("KT", "PROJ-9"))
        self.assertEqual(1, back.floor_project("BT"))

    def test_an_old_ledger_file_still_hands_over_its_floors(self):
        """File sổ cũ viết ``ideas``/``products`` — mốc trong đó là mốc thật.

        Bỏ qua chúng là lượt chạy đầu sau khi cập nhật đếm lại từ ``001`` và
        cấp đè lên những mã đã đi ra ngoài.
        """
        old = SkuLedger.from_mapping({"ideas": {"BT": 2}, "products": {"BT": 51}})
        self.assertEqual(2, old.floor_project("BT"))
        self.assertEqual(51, old.floor_idea("BT"))
        # Và mốc cũ điều khiển được lượt cấp mới: dự án kế là số 3, idea kế 52.
        plan = plan_skus(
            [card("TASK-1", meta="product: bờm"), card("TASK-2", "TASK-1")],
            BOOK, root_id="TASK-1", ledger=old, project_id="PROJ-MOI",
        )
        self.assertEqual(["BT_3_052"], [i.sku for i in plan.assignments])

    def test_new_keys_win_over_old_keys_by_taking_the_higher_floor(self):
        both = SkuLedger.from_mapping({"ideas": {"BT": 2}, "project_seq": {"BT": 5}})
        self.assertEqual(5, both.floor_project("BT"))

    def test_a_damaged_file_costs_the_numbers_not_the_run(self):
        """Sổ hỏng thì bot vẫn phải chạy được.

        Sổ chỉ là trí nhớ; mã thật nằm trên thẻ.  Ngã ra ngoại lệ ở đây là dừng
        cả lượt quét vì một file rác — mà lượt quét sau sẽ tự học lại mốc từ
        chính những mã đang nằm trên thẻ.
        """
        broken = (
            None,
            "hỏng",
            [],
            {"products": "hỏng"},
            {"ideas": {"BT": "x"}},
            {"projects": "hỏng"},
            {"projects": {"BT": "x"}},
            {"projects": {"BT": {"PROJ-1": "x"}}},
        )
        for garbage in broken:
            with self.subTest(garbage=garbage):
                so = SkuLedger.from_mapping(garbage)
                self.assertEqual(0, so.floor_project("BT"))
                self.assertEqual(0, so.floor_idea("BT"))
                self.assertEqual({}, so.as_dict()["projects"])


class LedgerReservationTests(unittest.TestCase):
    """Chỗ giữ số: một mã đã cấp mà chưa chắc đã lên thẻ, đứng tên đúng thẻ ấy.

    Sổ chỉ giữ mốc cao nhất, nên một mã cấp hụt là một lỗ không lấp lại được.
    Chỗ giữ là cách lấp: mốc vẫn dịch lên (không bảng nào cấp trùng), còn số
    thì vẫn thuộc về thẻ đã ghi hụt cho tới khi nó nhận được.
    """

    def test_a_reservation_survives_a_trip_through_json(self):
        so = SkuLedger()
        so.reserve("TASK-2", "BT_1_001")
        lai = SkuLedger.from_mapping(so.as_dict())
        self.assertEqual("BT_1_001", lai.reserved_for("TASK-2"))

    def test_releasing_a_reservation_empties_it(self):
        so = SkuLedger()
        so.reserve("TASK-2", "BT_1_001")
        self.assertTrue(so.release("TASK-2"))
        self.assertEqual("", so.reserved_for("TASK-2"))
        # Trả lại lần nữa không làm sổ dịch — người gọi đọc giá trị này để
        # biết có phải ghi xuống đĩa không.
        self.assertFalse(so.release("TASK-2"))

    def test_a_reservation_does_not_move_the_floor_by_itself(self):
        """Giữ chỗ không phải là khai số.  Hai việc khác nhau, gọi riêng.

        Khai số dịch mốc lên để bảng khác không cấp trùng; giữ chỗ chỉ nói
        "số này là của thẻ kia".  Gộp lại thì một lượt giữ chỗ nhầm sẽ đẩy mốc
        đi mà chẳng thẻ nào mang mã.
        """
        so = SkuLedger()
        so.reserve("TASK-2", "BT_1_009")
        self.assertEqual(0, so.floor_idea("BT"))

    def test_a_code_that_will_not_parse_is_not_reserved(self):
        # Cùng luật với ``observe_sku``: máy đọc không ra thì bỏ qua, không đoán.
        so = SkuLedger()
        self.assertFalse(so.reserve("TASK-2", "khantay_101"))
        self.assertEqual("", so.reserved_for("TASK-2"))


class LedgerAcrossTreesTests(unittest.TestCase):
    """Sổ là thứ duy nhất nối hai cây thẻ rời nhau lại với nhau.

    ``plan_skus`` chỉ nhìn thấy một cây mỗi lượt — đọc cả bảng mỗi lần là vượt
    trần 60 lượt gọi/phút của ERP.  Không có sổ, hai thẻ gốc cùng khai
    ``product: bờm`` đều thấy mình là cái đầu tiên và đều phát ``BT_1_001``.
    """

    def test_two_separate_projects_do_not_both_claim_the_first_code(self):
        so = SkuLedger()
        first = plan_skus(
            [card("TASK-1", meta="product: bờm"), card("TASK-2", "TASK-1")],
            BOOK, root_id="TASK-1", ledger=so, project_id="PROJ-A",
        )
        so.observe_plan(first)
        second = plan_skus(
            [card("TASK-9", meta="product: bờm"), card("TASK-10", "TASK-9")],
            BOOK, root_id="TASK-9", ledger=so, project_id="PROJ-B",
        )
        first_codes = [item.sku for item in first.assignments]
        second_codes = [item.sku for item in second.assignments]
        self.assertEqual(["BT_1_001"], first_codes)
        self.assertEqual(["BT_2_002"], second_codes)
        self.assertEqual(set(), set(first_codes) & set(second_codes))

    def test_a_second_project_keeps_counting_where_the_first_stopped(self):
        so = SkuLedger()
        so.observe_sku("BT_3_005", "PROJ-CU")
        plan = plan_skus(
            [card("TASK-9", meta="product: bờm"), card("TASK-10", "TASK-9")],
            BOOK, root_id="TASK-9", ledger=so, project_id="PROJ-MOI",
        )
        self.assertEqual("BT_4_006", plan.assignments[0].sku)

    def test_a_ledger_for_another_product_changes_nothing(self):
        # Bộ đếm đi theo tên SKU, không theo bảng: hai mặt hàng khác nhau
        # không được đẩy số của nhau lên.
        so = SkuLedger()
        so.observe_sku("KT_9_099", "PROJ-KHAC")
        plan = plan_skus(
            [card("TASK-1", meta="product: bờm"), card("TASK-2", "TASK-1")],
            BOOK, root_id="TASK-1", ledger=so, project_id="PROJ-A",
        )
        self.assertEqual("BT_1_001", plan.assignments[0].sku)

    def test_without_a_ledger_a_single_tree_still_opens_at_one(self):
        skus, _ = tree(card("TASK-1", meta="product: bờm"), card("TASK-2", "TASK-1"))
        self.assertEqual("BT_1_001", skus["TASK-2"])

    def test_a_code_already_on_a_card_is_still_left_alone(self):
        """Sổ chỉ nâng sàn cho mã *mới*; mã đã đi ra ngoài thì không đụng tới.

        Và thẻ trắng ngay cạnh phải mang **cùng số dự án** với mã cũ ấy — số
        giữa là của cả board, không phải của mốc sổ.
        """
        so = SkuLedger()
        so.observe_sku("BT_5_020", "PROJ-Z")
        plan = plan_skus(
            [
                card("TASK-1", meta="product: bờm"),
                card("TASK-2", "TASK-1", "sku: BT_1_001"),
                card("TASK-3", "TASK-2"),
            ],
            BOOK, root_id="TASK-1", ledger=so, project_id="PROJ-A",
        )
        by_id = {item.task_id: item for item in plan.assignments}
        self.assertEqual("BT_1_001", by_id["TASK-2"].sku)
        self.assertTrue(by_id["TASK-2"].kept)
        self.assertEqual("BT_1_021", by_id["TASK-3"].sku)
        self.assertEqual(1, by_id["TASK-3"].project, "hai thẻ cạnh nhau cùng board, cùng số dự án")

    def test_observe_plan_reports_the_plan_own_project_when_none_is_given(self):
        so = SkuLedger()
        plan = plan_skus(
            [card("TASK-1", meta="product: bờm"), card("TASK-2", "TASK-1")],
            BOOK, root_id="TASK-1", ledger=so, project_id="PROJ-7",
        )
        fresh = SkuLedger()
        self.assertTrue(fresh.observe_plan(plan))
        self.assertEqual(1, fresh.floor_idea("BT"))
        # Không truyền board thì kế hoạch tự khai board của nó — ánh xạ không rơi.
        self.assertEqual(1, fresh.project_number("BT", "PROJ-7"))
        self.assertEqual(1, fresh.floor_project("BT"))


class BoardNameTests(unittest.TestCase):
    """Tên sản phẩm lấy từ tên bảng khi không thẻ nào khai ``product:``.

    Hai lối cùng nói một chuyện: bảng tên ``khăn tay`` và thẻ cha khai
    ``product: khăn tay`` phải ra cùng một mã — nhưng lời khai trên thẻ, khi
    có, luôn thắng tên bảng.
    """

    @staticmethod
    def _board_card(task_id, parent="", meta="", board="khăn tay"):
        return card(task_id, parent, meta, board=board, project="PROJ-0170")

    def test_the_board_name_names_the_product_when_no_card_does(self):
        plan = plan_skus(
            [self._board_card("TASK-1"), self._board_card("TASK-2", "TASK-1")],
            BOOK,
            root_id="TASK-1",
        )
        self.assertEqual("khăn tay", plan.product)
        self.assertEqual("KT", plan.prefix)
        self.assertEqual("book", plan.prefix_source)
        self.assertEqual("PROJ-0170", plan.project)
        self.assertEqual(
            [("TASK-2", "KT_1_001", "idea", 1, 1)],
            [(i.task_id, i.sku, i.role, i.project, i.idea) for i in plan.assignments],
        )

    def test_a_product_declared_on_a_card_beats_the_board_name(self):
        plan = plan_skus(
            [
                self._board_card("TASK-1"),
                self._board_card("TASK-2", "TASK-1"),
                self._board_card("TASK-3", "TASK-1", "product: bờm"),
            ],
            BOOK,
            root_id="TASK-1",
        )
        by_id = {item.task_id: item for item in plan.assignments}
        self.assertEqual("KT_1_001", by_id["TASK-2"].sku)
        self.assertEqual("BT_1_001", by_id["TASK-3"].sku)
        # Hai tên SKU đếm riêng: cùng board nên cùng là dự án số 1 của mỗi bên.
        self.assertEqual((1, 1), (by_id["TASK-2"].project, by_id["TASK-3"].project))

    def test_a_product_declared_on_the_root_beats_the_board_name_for_the_tree(self):
        plan = plan_skus(
            [
                self._board_card("TASK-1", meta="product: bờm"),
                self._board_card("TASK-2", "TASK-1"),
            ],
            BOOK,
            root_id="TASK-1",
        )
        self.assertEqual("bờm", plan.product)
        self.assertEqual(["BT_1_001"], [item.sku for item in plan.assignments])

    def test_the_caller_may_name_the_board_when_the_cards_do_not(self):
        """``board_product`` truyền tay đỡ cho thẻ không mang ``project_name``."""
        plan = plan_skus(
            [card("TASK-1"), card("TASK-2", "TASK-1")],
            BOOK,
            root_id="TASK-1",
            board_product="khăn tay",
            project_id="PROJ-0170",
        )
        self.assertEqual([("TASK-2", "KT_1_001")], [(i.task_id, i.sku) for i in plan.assignments])

    def test_a_nameless_board_with_a_silent_root_hands_out_nothing(self):
        """Không tên bảng, không ``product:`` — chưa có gì để đánh số, không đoán."""
        plan = plan_skus(
            [card("TASK-1"), card("TASK-2", "TASK-1")],
            BOOK,
            root_id="TASK-1",
            project_id="",
        )
        self.assertEqual((), plan.assignments)
        self.assertEqual((("TASK-2", "chưa có product để tra bảng SKU"),), plan.skipped)


    def test_the_xmas_ornament_board_gets_the_code_its_row_says(self):
        """Board thật của xưởng: ``XMAS Ornament Thêu Tròn``, bảng ghi ``OR``.

        Đây là cái bảng người ta chạy thử, và nó không khai ``product:`` ở đâu
        cả — tên board là tất cả những gì có.  Ra ``XOTT`` thì tem in ra sai,
        mà tem đã in thì không gọi về được.
        """
        book = ProductBook.from_mapping({"ornament thêu": "OR"})
        plan = plan_skus(
            [
                card("TASK-1", board="XMAS Ornament Thêu Tròn", project="PROJ-0018"),
                card("TASK-2", "TASK-1", board="XMAS Ornament Thêu Tròn", project="PROJ-0018"),
            ],
            book,
            root_id="TASK-1",
        )
        self.assertEqual("OR", plan.prefix)
        self.assertEqual(["OR_1_001"], [item.sku for item in plan.assignments])


class FatherIdeaTests(unittest.TestCase):
    """``fatheridea`` là lời khai "tôi thuộc idea kia" — thuộc tính đi theo lời
    khai chứ không theo chỗ thẻ đang nằm."""

    def test_a_card_reads_its_product_from_the_idea_it_declares(self):
        skus, _ = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202", "product: bờm"),
            card("TASK-2026-00907", "TASK-2026-00202", "fatheridea: TASK-2026-00906"),
        )
        self.assertEqual("BT_1_001", skus["TASK-2026-00906"])
        self.assertEqual("BT_1_002", skus["TASK-2026-00907"], "sản phẩm theo lời khai, không theo cây")

    def test_dadidea_is_read_too(self):
        """Chữ đã có sẵn trên bảng, gõ tay từ trước khi việc này tồn tại."""
        skus, _ = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202", "product: bờm"),
            card("TASK-2026-00907", "TASK-2026-00202", "dadidea: TASK-2026-00906"),
        )
        self.assertEqual("BT_1_002", skus["TASK-2026-00907"])

    def test_naming_a_card_that_is_not_here_falls_back_to_the_tree(self):
        skus, _ = tree(
            card("TASK-2026-00202", meta="product: khăn tay"),
            card("TASK-2026-00906", "TASK-2026-00202", "fatheridea: TASK-2026-99999"),
        )
        self.assertEqual("KT_1_001", skus["TASK-2026-00906"])


class NoProductTests(unittest.TestCase):
    def test_a_tree_with_no_product_hands_out_nothing(self):
        """Chưa gõ ``product`` thì chưa có gì để đánh số — và không được đoán."""
        _, plan = tree(
            card("TASK-2026-00202"),
            card("TASK-2026-00906", "TASK-2026-00202"),
        )
        self.assertEqual((), plan.changes)
        self.assertEqual(
            (("TASK-2026-00906", "chưa có product để tra bảng SKU"),),
            plan.skipped,
        )

    def test_empty_input(self):
        self.assertEqual((), plan_skus([], BOOK).assignments)


class TaskFullTests(unittest.TestCase):
    """Đọc payload ``taskFull`` — cây lồng nhau, ``meta``/cột/dự án nằm ở ``subtasks``."""

    PAYLOAD = {
        "root": {
            "name": "TASK-2026-00202",
            "subject": "Idea",
            "parent_task": None,
            "meta": "product: khăn tay",
            "project": "PROJ-0170",
            "project_name": "khăn tay",
            "status": "Working",
            # ``children`` chỉ có tên; ``meta`` chỉ có ở ``subtasks``.
            "children": [{"name": "TASK-2026-00906", "subject": "Idea 7"}],
            "subtasks": [
                {
                    "name": "TASK-2026-00906",
                    "subject": "Idea 7",
                    "parent_task": "TASK-2026-00202",
                    "meta": "product: \nsku: \nacc: \ntemplate:",
                    "project": "PROJ-0170",
                    "status": "Working",
                    "subtasks": [
                        {
                            "name": "TASK-2026-00920",
                            "subject": "Ảnh 1",
                            "parent_task": "TASK-2026-00906",
                            "meta": "",
                            "project": "PROJ-0170",
                            "status": "Working",
                            "subtasks": [],
                        }
                    ],
                }
            ],
        }
    }

    def test_flatten_reads_the_whole_tree_root_first(self):
        cards = flatten_tree(self.PAYLOAD["root"])
        self.assertEqual(
            ["TASK-2026-00202", "TASK-2026-00906", "TASK-2026-00920"],
            [item.task_id for item in cards],
        )
        self.assertEqual("TASK-2026-00906", cards[2].parent_id)
        # Cột và mã dự án phải đi theo từng thẻ — chúng quyết mã của chính thẻ ấy.
        self.assertEqual("Working", cards[1].status)
        self.assertEqual("PROJ-0170", cards[2].project)
        self.assertEqual("khăn tay", cards[0].board)

    def test_plan_tree_accepts_the_payload_as_returned(self):
        plan = plan_tree(self.PAYLOAD, BOOK)
        self.assertEqual("TASK-2026-00202", plan.root_id)
        self.assertEqual("KT", plan.prefix)
        self.assertEqual("PROJ-0170", plan.project, "mã dự án đọc từ chính payload, không cần hỏi lại ERP")
        self.assertEqual(
            [
                ("TASK-2026-00906", "KT_1_001", "idea", 1, 1),
                ("TASK-2026-00920", "KT_1_002", "idea", 1, 2),
            ],
            [(i.task_id, i.sku, i.role, i.project, i.idea) for i in plan.assignments],
        )

    def test_blank_attribute_lines_are_not_a_code(self):
        """``sku:`` để trống là ô chờ điền, không phải mã."""
        plan = plan_tree(self.PAYLOAD, BOOK)
        self.assertTrue(all(item.changed for item in plan.assignments))

    def test_card_from_node_reads_every_spelling_the_erp_uses(self):
        """Payload lúc viết ``project_name``, lúc ``projectName`` — cùng một bảng."""
        self.assertEqual("khăn tay", card_from_node({"name": "T", "project_name": "khăn tay"}).board)
        self.assertEqual("khăn tay", card_from_node({"name": "T", "projectName": " khăn tay "}).board)
        self.assertEqual("PROJ-0170", card_from_node({"name": "T", "project": "PROJ-0170"}).project)
        self.assertEqual("PROJ-0170", card_from_node({"name": "T", "projectId": " PROJ-0170 "}).project)
        self.assertEqual("Working", card_from_node({"name": "T", "status": " Working "}).status)


class MissingCountTests(unittest.TestCase):
    """``cards_missing_sku`` và ``plan_skus`` phải trả lời giống hệt nhau.

    Luật cột đọc con số này để quyết thẻ đi hay ở, còn kế hoạch mới là bên
    điền mã.  Đếm nhiều hơn kế hoạch một thẻ là cụm đứng ở *Đang làm* mãi mãi
    với "còn 1 thẻ chưa có mã" mà không ai điền được; đếm ít hơn là cụm bị
    đẩy đi trong lúc idea còn trắng.
    """

    MIXED = {
        "root": {
            "name": "TASK-2026-00001",
            "subject": "Idea khăn thêu",
            "meta": "",
            "project": "PROJ-0170",
            "project_name": "khăn tay",
            "status": "Working",
            "subtasks": [
                # Sẽ được cấp mã: đã sang Đang làm, ô sku còn trắng.
                {"name": "TASK-2026-00002", "parent_task": "TASK-2026-00001",
                 "meta": "", "project": "PROJ-0170", "status": "Working", "subtasks": []},
                # Chưa duyệt: không đếm, không cấp.
                {"name": "TASK-2026-00003", "parent_task": "TASK-2026-00001",
                 "meta": "", "project": "PROJ-0170", "status": "Open", "subtasks": []},
                # Đã huỷ: không đếm, không cấp.
                {"name": "TASK-2026-00004", "parent_task": "TASK-2026-00001",
                 "meta": "", "project": "PROJ-0170", "status": "Cancelled", "subtasks": []},
                # Đã có mã: không đếm, giữ nguyên.
                {"name": "TASK-2026-00005", "parent_task": "TASK-2026-00001",
                 "meta": "sku: KT_1_001", "project": "PROJ-0170", "status": "Working", "subtasks": []},
                # Mã gõ tay sai dạng: ô không trống nên không đếm — và không cấp.
                {"name": "TASK-2026-00006", "parent_task": "TASK-2026-00001",
                 "meta": "sku: khantay_101", "project": "PROJ-0170", "status": "Working", "subtasks": []},
            ],
        }
    }

    @staticmethod
    def _with_meta(payload, meta_by_task):
        """Bản sao payload với khối ``meta`` mới trên những thẻ được nêu tên."""
        import copy

        root = copy.deepcopy(payload["root"])

        def walk(node):
            if node.get("name") in meta_by_task:
                node["meta"] = meta_by_task[node["name"]]
            for child in node.get("subtasks") or ():
                walk(child)

        walk(root)
        return {"root": root}

    def test_the_count_and_the_plan_agree_card_for_card(self):
        plan = plan_tree(self.MIXED, BOOK)
        self.assertEqual(len(plan.changes), cards_missing_sku(self.MIXED["root"]))
        self.assertEqual(
            ["TASK-2026-00002"], [item.task_id for item in plan.changes],
            "đúng một thẻ sẵn sàng và còn trắng — hai bên cùng chỉ vào nó",
        )
        self.assertEqual("KT_1_002", plan.changes[0].sku, "số 001 đã có chủ, không cấp lại")

    def test_the_parent_idea_card_is_never_counted_as_missing(self):
        """Thẻ gốc cố ý không bao giờ có mã — đếm nó là đếm một thứ không bao
        giờ về 0."""
        self.assertEqual(1, cards_missing_sku(self.MIXED["root"]))

    def test_cards_not_yet_in_doing_are_not_counted(self):
        """Kế hoạch cố ý chưa cấp cho thẻ chưa duyệt, nên phép đếm cũng phải chừa ra.

        Đếm chúng vào là cụm bị giữ lại vì những thẻ mà máy cố ý không điền.
        """
        plan = plan_tree(self.MIXED, BOOK)
        skipped = dict(plan.skipped)
        self.assertEqual("chưa sang cột Đang làm", skipped["TASK-2026-00003"])
        self.assertEqual("chưa sang cột Đang làm", skipped["TASK-2026-00004"])
        self.assertIn("KHANTAY_101", skipped["TASK-2026-00006"])

    def test_filling_exactly_what_the_plan_promises_brings_the_count_to_zero(self):
        """Vòng đời thật: đếm → cấp → ghi → đếm lại phải về 0 và chạy lại không đẻ gì."""
        plan = plan_tree(self.MIXED, BOOK)
        filled = self._with_meta(
            self.MIXED,
            {item.task_id: f"sku: {item.sku}" for item in plan.changes},
        )
        self.assertEqual(0, cards_missing_sku(filled["root"]))
        self.assertEqual((), plan_tree(filled, BOOK).changes)

    def test_an_empty_payload_counts_nothing(self):
        self.assertEqual(0, cards_missing_sku(None))
        self.assertEqual(0, cards_missing_sku({}))


class WriteBackTests(unittest.TestCase):
    """``updateTaskMeta`` thay cả khối, nên phải dựng lại từ khối đang có."""

    def test_the_code_lands_on_the_line_that_was_waiting_for_it(self):
        original = "product: \nsku: \nacc: \ntemplate:"
        written = render_meta_block({"sku": "KT_1_001"}, original)
        self.assertEqual(written, "product:\nsku: KT_1_001\nacc:\ntemplate:")

    def test_attributes_the_app_knows_nothing_about_survive(self):
        original = "product: khăn tay\nghi_chu: hàng mẫu\nacc: acc32"
        written = render_meta_block({"sku": "KT_1_001"}, original)
        self.assertEqual(parse_meta_block(written)["ghi_chu"], "hàng mẫu")
        self.assertEqual(parse_meta_block(written)["acc"], "acc32")
        self.assertEqual(parse_meta_block(written)["sku"], "KT_1_001")

    def test_a_key_typed_twice_collapses_to_one_line(self):
        """Panel cho gõ ``sku:`` hai lần; parser đọc dòng cuối, nên ghi ra một dòng."""
        written = render_meta_block({"sku": "KT_2_001"}, "sku: \nproduct: khan tay\nsku: KT_1")
        self.assertEqual(written, "sku: KT_2_001\nproduct: khan tay")

    def test_erp_maintained_keys_are_never_written_back(self):
        written = render_meta_block({"_status": "done", "sku": "KT_1_001"}, "product: khan tay")
        self.assertNotIn("_status", written)
        self.assertIn("sku: KT_1_001", written)

    def test_the_generated_code_reads_back_as_the_card_says_it(self):
        block = render_meta_block({"sku": "KT_1_001"}, "product: khăn tay")
        self.assertEqual(task_meta({"meta": block}).sku, "KT_1_001")
        self.assertEqual(task_meta({"meta": block}).product, "khăn tay")


class MetaCustomTests(unittest.TestCase):
    """Cùng một khối, hai cái tên: ``taskDetail`` gọi ``meta``, ``taskMeta`` gọi ``meta_custom``."""

    def test_meta_custom_is_read_as_the_user_block(self):
        meta = task_meta({"meta_custom": "product: bờm\nsku: BT_2_009"})
        self.assertEqual(meta.product, "bờm")
        self.assertEqual(meta.sku, "BT_2_009")

    def test_meta_still_wins_when_both_are_present(self):
        meta = task_meta({"meta": "sku: KT_1_001", "meta_custom": "sku: BT_2_009"})
        self.assertEqual(meta.sku, "KT_1_001")


class ServiceLedgerTests(unittest.TestCase):
    """Sổ sống trên đĩa, nên nó phải chịu được cả máy tắt lẫn file rác."""

    def _service(self, folder):
        from unittest.mock import patch

        from flow_web.service import FlowWebService

        svc = FlowWebService.__new__(FlowWebService)
        svc._sku_ledger_path = lambda: folder / "sku_ledger.json"
        return svc, patch

    def test_a_ledger_written_now_reads_back_after_a_restart(self):
        import tempfile
        from flow_web.service import FlowWebService

        with tempfile.TemporaryDirectory() as tmp:
            svc, _ = self._service(Path(tmp))
            so = SkuLedger()
            so.observe_sku("BT_2_006", "PROJ-1")
            FlowWebService.save_sku_ledger(svc, so)
            back = FlowWebService.load_sku_ledger(svc)
        self.assertEqual((2, 6), (back.floor_project("BT"), back.floor_idea("BT")))
        # Ánh xạ board sống qua đĩa — mất nó là board cũ bị cấp số mới.
        self.assertEqual(2, back.project_number("BT", "PROJ-1"))

    def test_no_file_yet_is_an_empty_ledger_not_a_crash(self):
        import tempfile
        from flow_web.service import FlowWebService

        with tempfile.TemporaryDirectory() as tmp:
            svc, _ = self._service(Path(tmp))
            self.assertEqual(0, FlowWebService.load_sku_ledger(svc).floor_idea("BT"))

    def test_a_half_written_file_costs_the_numbers_not_the_scan(self):
        # Tắt máy giữa lượt ghi để lại file cụt.  Sổ trống chỉ khiến lượt sau
        # học lại mốc từ mã đang nằm trên thẻ; ném lỗi thì cả bảng đứng im.
        import tempfile
        from flow_web.service import FlowWebService

        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "sku_ledger.json"
            broken.write_text('{"idea_seq": {"BT": 6', encoding="utf-8")
            svc, _ = self._service(Path(tmp))
            self.assertEqual(0, FlowWebService.load_sku_ledger(svc).floor_idea("BT"))

    def test_an_old_ledger_file_on_disk_is_still_read(self):
        """File sổ đang nằm trên máy trung tâm viết bằng tên cũ ``ideas``/``products``."""
        import tempfile
        from flow_web.service import FlowWebService

        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "sku_ledger.json"
            old.write_text('{"ideas": {"BT": 2}, "products": {"BT": 51}}', encoding="utf-8")
            svc, _ = self._service(Path(tmp))
            back = FlowWebService.load_sku_ledger(svc)
        self.assertEqual((2, 51), (back.floor_project("BT"), back.floor_idea("BT")))

    def test_the_file_is_swapped_in_whole_never_written_in_place(self):
        # Ghi thẳng thì một lần tắt máy giữa chừng để lại sổ cụt — mà sổ cụt
        # đọc ra sổ trống, tức là cấp lại đúng những số đang nằm trên bảng.
        import tempfile
        from flow_web.service import FlowWebService

        with tempfile.TemporaryDirectory() as tmp:
            svc, patch = self._service(Path(tmp))
            existing = Path(tmp) / "sku_ledger.json"
            existing.write_text('{"project_seq": {}, "idea_seq": {"BT": 1}}', encoding="utf-8")
            so = SkuLedger()
            so.observe_sku("BT_2_006")
            with patch.object(Path, "replace", side_effect=OSError("máy tắt")):
                FlowWebService.save_sku_ledger(svc, so)
            # Ghi hỏng thì bản cũ vẫn còn nguyên, không thành file rỗng.
            self.assertEqual(1, FlowWebService.load_sku_ledger(svc).floor_idea("BT"))


def _board_of(names, status="Working"):
    """Payload ``taskBoard`` một cột, thẻ theo đúng thứ tự từ trên xuống."""
    return {"columns": [{"status": status, "tasks": [{"name": name} for name in names]}]}


class ColumnPositionTests(unittest.TestCase):
    """Chỗ đứng của thẻ trên bảng.

    ``taskBoard`` không trả khoá nào nói vị trí.  Thứ tự mảng ``tasks`` của
    mỗi cột là thứ tự trên màn hình, phần tử đầu là thẻ trên cùng.
    """

    def test_the_top_card_comes_first(self):
        positions = column_positions(_board_of(["TASK-9", "TASK-2", "TASK-5"]))

        self.assertEqual(["TASK-9", "TASK-2", "TASK-5"], sorted(positions, key=positions.get))

    def test_a_column_further_along_comes_first(self):
        board = {
            "columns": [
                {"status": "Open", "tasks": [{"name": "A"}]},
                {"status": "Working", "tasks": [{"name": "B"}]},
                {"status": "Pending Review", "tasks": [{"name": "C"}]},
                {"status": "Completed", "tasks": [{"name": "D"}]},
                {"status": "Cột lạ", "tasks": [{"name": "E"}]},
            ]
        }
        positions = column_positions(board)

        self.assertEqual(["D", "C", "B", "A", "E"], sorted(positions, key=positions.get))

    def test_a_broken_payload_gives_nothing(self):
        for junk in (None, [], {}, {"columns": "x"}, {"columns": [None, {"tasks": [None, {"name": ""}]}]}):
            self.assertEqual({}, column_positions(junk), junk)


class PlanOrderTests(unittest.TestCase):
    """Mã mới cấp theo chỗ thẻ đứng trong cột, từ trên xuống.

    Ca thật trên PROJ-0087: PNO_1_001..010 đi đúng theo số task — thứ tự thẻ
    được bê từ Trello — chứ không theo chỗ thẻ nằm trên bảng.  Nhìn cột thì
    thấy mã lộn xộn.
    """

    ROOT = card("TASK-1", meta="product: bờm")

    def test_the_top_card_gets_the_smallest_number(self):
        codes, _ = tree(
            self.ROOT,
            card("TASK-2", "TASK-1"),
            card("TASK-3", "TASK-1"),
            card("TASK-4", "TASK-1"),
            positions=column_positions(_board_of(["TASK-4", "TASK-2", "TASK-3"])),
        )

        self.assertEqual({"TASK-4": "BT_1_001", "TASK-2": "BT_1_002", "TASK-3": "BT_1_003"}, codes)

    def test_without_the_board_the_task_number_decides(self):
        codes, _ = tree(self.ROOT, card("TASK-10", "TASK-1"), card("TASK-3", "TASK-1"))

        self.assertEqual({"TASK-3": "BT_1_001", "TASK-10": "BT_1_002"}, codes)

    def test_a_card_missing_from_the_board_goes_last(self):
        codes, _ = tree(
            self.ROOT,
            card("TASK-2", "TASK-1"),
            card("TASK-3", "TASK-1"),
            card("TASK-4", "TASK-1"),
            positions=column_positions(_board_of(["TASK-3"])),
        )

        self.assertEqual({"TASK-3": "BT_1_001", "TASK-2": "BT_1_002", "TASK-4": "BT_1_003"}, codes)

    def test_a_code_already_on_a_card_stays_and_new_ones_go_above_it(self):
        codes, plan = tree(
            self.ROOT,
            card("TASK-2", "TASK-1", "sku: BT_1_005"),
            card("TASK-3", "TASK-1"),
            card("TASK-4", "TASK-1"),
            positions=column_positions(_board_of(["TASK-4", "TASK-2", "TASK-3"])),
        )

        self.assertEqual({"TASK-2": "BT_1_005", "TASK-4": "BT_1_006", "TASK-3": "BT_1_007"}, codes)
        self.assertEqual({"TASK-3", "TASK-4"}, {item.task_id for item in plan.changes})

    def test_renumbering_follows_the_board_above_the_ledger_floor(self):
        so = SkuLedger()
        so.observe_sku("BT_1_010", "PROJ-0170")
        codes, _ = tree(
            self.ROOT,
            card("TASK-2", "TASK-1", "sku: BT_1_001"),
            card("TASK-3", "TASK-1", "sku: BT_1_002"),
            renumber=True,
            ledger=so,
            positions=column_positions(_board_of(["TASK-3", "TASK-2"])),
        )

        self.assertEqual({"TASK-3": "BT_1_011", "TASK-2": "BT_1_012"}, codes)


class FillLedgerTests(unittest.TestCase):
    """``fill_task_skus`` — lượt hoàn chỉnh: đọc cây, tính, ghi ERP, ghi sổ.

    Sổ trên đĩa là trí nhớ duy nhất nối các cụm, nên hai nhịp ghi sổ ở đây
    phải đúng giờ: số idea *mới* chỉ được khai sau khi ERP nhận (ghi hỏng
    không đốt số), còn mã *đang nằm trên thẻ* được khai ngay trong lúc tính
    và phải xuống đĩa kể cả lượt dry-run — đó là đường sổ mất tự lành.
    ERP ở đây là hai hàm giả: cây trả sẵn, lượt ghi gật hoặc lắc.
    """

    @staticmethod
    def _payload(nodes, subjects=None):
        """Cây ``taskFull`` dựng từ (tên, cha, meta) — đủ cho ``plan_erp_skus`` thật.

        Mang cả ``subject``: payload thật của ``taskFull`` trả tên thẻ ngay
        trong cùng node, và lượt chữa tên đọc đúng chỗ đó.
        """
        titles = dict(subjects or {})
        by_name = {
            name: {
                "name": name,
                "subject": titles.get(name, ""),
                "parent_task": parent,
                "meta": meta,
                "project": "PROJ-0170",
                "subtasks": [],
            }
            for name, parent, meta in nodes
        }
        root = None
        for name, parent, _ in nodes:
            if parent:
                by_name[parent]["subtasks"].append(by_name[name])
            else:
                root = by_name[name]
        return {"root": root}

    def _run(
        self,
        nodes,
        *,
        dry_run=False,
        refuse_writes=False,
        subjects=None,
        refuse_renames=False,
        renumber=False,
        write_vanishes=False,
        verify_explodes=False,
        verify_lags=False,
        ledger_dir=None,
        board=None,
        board_broken=False,
    ):
        """Chạy một lượt thật trên một ERP giả **có trí nhớ**.

        Khối thuộc tính được giữ lại giữa các lượt gọi chứ không phải một
        lambda rỗng: lượt ghi đọc lại đúng cái nó vừa viết.  Có trí nhớ mới
        phân biệt được "ERP nhận" với "ERP gật cho xong mà không ghi" —
        ``write_vanishes=True`` dựng đúng ca thứ hai.
        """
        import contextlib
        import tempfile
        from unittest.mock import patch

        from flow_web.service import FlowWebService

        payload = self._payload(nodes, subjects)
        titles = dict(subjects or {})
        self.metas = {name: meta for name, _, meta in nodes}
        self.renames = []
        # Lời nhắc bot đăng lên thẻ, gom lại để bài test soi: đăng nhầm lúc
        # cũng hỏng như không đăng.
        self.comments = []
        metas = self.metas
        # ``ledger_dir`` cho phép hai lượt chạy dùng chung một quyển sổ — cần
        # thế mới thấy được lượt sau cấp số nào.
        keep = ledger_dir is not None
        with contextlib.nullcontext(ledger_dir) if keep else tempfile.TemporaryDirectory() as tmp:
            svc = FlowWebService.__new__(FlowWebService)
            svc._sku_ledger_path = lambda: Path(tmp) / "sku_ledger.json"
            svc._erp_credentials = lambda: ("k", "t")
            svc._normalize_erp_task_id = lambda value: value
            svc._erp_assert_task_in_project = lambda *a, **k: None
            svc._erp_task_full = lambda key, token, root: payload
            svc.load_sku_book = lambda *a, **k: BOOK
            self.board_reads = 0

            def read_board(key, token, project):
                # Mặc định cột xếp theo số task — đúng thứ tự cũ, để các bài
                # viết trước khi có luật "trên xuống" vẫn nói đúng điều chúng nói.
                self.board_reads += 1
                if board_broken:
                    raise RuntimeError("ERP trả 500")
                if board is not None:
                    return board
                return _board_of(sorted((name for name, parent, _ in nodes if parent), key=sku.task_number))

            svc._erp_task_board = read_board
            reads: dict = {}

            def read_detail(key, token, task_id):
                reads[task_id] = reads.get(task_id, 0) + 1
                # Lượt đọc thứ hai của một thẻ chính là lượt đọc lại sau khi
                # ghi — chỗ ERP có thể trả 429 hoặc hết giờ.
                if verify_explodes and reads[task_id] > 1:
                    raise RuntimeError("ERP đang giới hạn request (HTTP 429).")
                # Bản sao chậm hơn lượt ghi: đọc lần thứ hai vẫn còn thấy khối
                # thuộc tính cũ, tới lần thứ ba mới thấy cái vừa ghi.
                if verify_lags and reads[task_id] == 2:
                    return {"meta": "", "subject": titles.get(task_id, "")}
                return {
                    "meta": metas.get(task_id, ""),
                    "subject": titles.get(task_id, ""),
                }

            svc._erp_task_detail = read_detail

            def write_meta(key, token, task_id, block):
                if refuse_writes:
                    raise RuntimeError("ERP từ chối")
                # ERP gật đầu nhưng không ghi: HTTP 200, không có ``errors``,
                # thẻ vẫn nguyên như cũ.
                if not write_vanishes:
                    metas[task_id] = block
                return {}

            svc._erp_update_task_meta = write_meta

            def rename(key, token, task_id, subject):
                if refuse_renames:
                    raise RuntimeError("ERP từ chối đổi tên")
                self.renames.append((task_id, subject))
                titles[task_id] = subject
                return {}

            svc._erp_update_task_title = rename

            def comment(key, token, task_id, content, **kwargs):
                self.comments.append((task_id, content))
                return {}

            svc._erp_comment = comment
            # Nhịp nghỉ giữa hai lượt hỏi là thật trong code, giả ở đây: bài
            # test không có gì để chờ.
            with patch("flow_web.service.log"), patch("flow_web.service.time.sleep"):
                result = FlowWebService.fill_task_skus(
                    svc, "TASK-1", dry_run=dry_run, renumber=renumber
                )
            return result, FlowWebService.load_sku_ledger(svc)

    def test_a_code_the_bot_wrote_is_claimed_in_the_ledger(self):
        result, so = self._run([("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")])
        self.assertEqual(["BT_1_001"], [item["sku"] for item in result["written"]])
        self.assertEqual((1, 1), (so.floor_project("BT"), so.floor_idea("BT")))
        # Ánh xạ board cũng xuống đĩa: máy khởi động lại, hỏi lại board này
        # vẫn ra số 1 chứ không tiêu số mới.
        self.assertEqual(1, so.project_number("BT", "PROJ-0170"))

    def test_a_write_that_erp_refused_does_not_burn_the_number(self):
        """Khai số *trước* khi ghi thì một lượt ghi hỏng đốt mất một số.

        Và số bị đốt là số không thẻ nào mang — cái lỗ ấy không bao giờ được
        lấp lại nữa, vì sổ chỉ giữ mốc cao nhất chứ không giữ chỗ trống.
        """
        result, so = self._run(
            [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")],
            refuse_writes=True,
        )
        self.assertEqual([], result["written"])
        self.assertEqual(1, len(result["failed"]))
        self.assertEqual(0, so.floor_idea("BT"))

    def test_a_dry_run_never_claims_the_idea_numbers_it_only_proposed(self):
        result, so = self._run(
            [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")],
            dry_run=True,
        )
        self.assertEqual([], result["written"])
        self.assertEqual(0, so.floor_idea("BT"))

    def test_the_ledger_learns_the_highest_code_on_the_tree_not_the_first(self):
        """Bắt được trên bảng thật: vòng học mã từng dừng ngay ở mã đầu tiên nó thấy.

        Sổ dừng non thì cây sau cấp lại đúng những số đang nằm trên bảng — mà
        đó chính là cái lỗi cả cuốn sổ này sinh ra để chặn.
        """
        nodes = [("TASK-1", "", "product: bờm")] + [
            (f"TASK-{n}", "TASK-1", f"sku: BT_{n - 1}_00{n - 1}") for n in range(2, 6)
        ]
        _, so = self._run(nodes, dry_run=True)
        self.assertEqual((4, 4), (so.floor_project("BT"), so.floor_idea("BT")))

    def test_codes_already_on_the_cards_heal_a_ledger_that_was_lost(self):
        """Mất file sổ không được phép thành cấp trùng mã.

        Mã nằm sẵn trên thẻ được khai trong lúc *tính*, nên kể cả một lượt
        dry-run — không ghi gì mới lên ERP — cũng phải để lại sổ đã lành trên
        đĩa, kèm ánh xạ board → số dự án.
        """
        _, so = self._run(
            [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "sku: BT_4_012")],
            dry_run=True,
        )
        self.assertEqual((4, 12), (so.floor_project("BT"), so.floor_idea("BT")))
        # Ánh xạ lành theo: bảng ấy vẫn là dự án số 4 của bờm.
        self.assertEqual(4, so.project_number("BT", "PROJ-0170"))

    def test_a_card_that_got_its_sku_is_renamed_to_that_sku(self):
        """Ghi mã xong thì đổi luôn tên thẻ thành đúng mã ấy.

        Nhìn bảng là biết mã, không phải mở từng thẻ ra đọc khối thuộc tính.
        Tên cũ (``Idea 7``) mất hẳn — ERP không giữ bản trước — và đó là điều
        người vận hành đã chọn khi bật cái này.
        """
        result, _ = self._run(
            [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")],
            subjects={"TASK-2": "Idea 7"},
        )
        self.assertEqual([("TASK-2", "BT_1_001")], self.renames)
        self.assertEqual(
            [{"task_id": "TASK-2", "sku": "BT_1_001", "subject": "Idea 7"}], result["renamed"]
        )

    def test_the_root_card_keeps_its_name(self):
        """Thẻ gốc không mang mã, nên cũng không bị đổi tên.

        Nó là chỗ khai ``product:`` và chỗ chứa ảnh; mất tên ấy là mất chỗ
        nhận ra sản phẩm của cả cụm.
        """
        self._run(
            [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")],
            subjects={"TASK-1": "XMAS Ornament Thêu Tròn", "TASK-2": "Idea 7"},
        )
        self.assertEqual(["TASK-2"], [task for task, _ in self.renames])

    def test_a_card_already_named_after_its_sku_is_not_renamed_again(self):
        # Lượt sau chạy lại trên cùng cây thẻ không được tiêu thêm request ghi.
        result, _ = self._run(
            [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")],
            subjects={"TASK-2": "BT_1_001"},
        )
        self.assertEqual([], self.renames)
        self.assertEqual([], result["renamed"])
        self.assertEqual(["BT_1_001"], [item["sku"] for item in result["written"]])

    def test_a_rename_that_erp_refused_does_not_take_back_the_sku(self):
        """Đổi tên hỏng thì mã vẫn nằm trên thẻ và vẫn được khai vào sổ.

        Mã là thứ thật, tên chỉ là chỗ hiển thị.  Gộp lỗi đổi tên vào
        ``failed`` sẽ khiến người đọc tưởng mã chưa ghi được, nên nó có ô
        riêng.
        """
        result, so = self._run(
            [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")],
            subjects={"TASK-2": "Idea 7"},
            refuse_renames=True,
        )
        self.assertEqual(["BT_1_001"], [item["sku"] for item in result["written"]])
        self.assertEqual([], result["failed"])
        self.assertEqual(1, so.floor_idea("BT"))
        self.assertEqual(["TASK-2"], [item["task_id"] for item in result["rename_failed"]])

    def test_a_dry_run_renames_nothing(self):
        result, _ = self._run(
            [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")],
            subjects={"TASK-2": "Idea 7"},
            dry_run=True,
        )
        self.assertEqual([], self.renames)
        self.assertEqual([], result["renamed"])

    def test_the_rename_can_be_turned_off_by_hand(self):
        # Đường lùi: vẫn cấp mã, nhưng để nguyên tên thẻ.
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"ERP_SKU_RENAME_TASK": "0"}):
            result, _ = self._run(
                [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")],
                subjects={"TASK-2": "Idea 7"},
            )
        self.assertEqual([], self.renames)
        self.assertEqual(["BT_1_001"], [item["sku"] for item in result["written"]])

    def test_the_name_the_rename_replaced_is_parked_on_the_card(self):
        """Tên cũ đi vào ``ten_cu:`` của chính thẻ, trong cùng lượt ghi ấy.

        ERP không giữ bản trước, nên nếu tên cũ không được chép đi đâu cả thì
        đổi tên là mất hẳn.  Chép vào khối thuộc tính thì không tốn thêm một
        request nào — dòng ``sku:`` vẫn đang được ghi ở đúng chỗ đó — mà đổi
        lại được: nhìn thẻ là thấy nó từng tên gì.
        """
        result, _ = self._run(
            [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")],
            subjects={"TASK-2": "Idea 7"},
        )
        self.assertEqual([("TASK-2", "BT_1_001")], self.renames)
        self.assertIn("sku: BT_1_001", self.metas["TASK-2"])
        self.assertIn("ten_cu: Idea 7", self.metas["TASK-2"])

    def test_a_renumber_keeps_the_first_name_it_parked(self):
        """Lượt đánh số lại **không** được đè ``ten_cu`` bằng mã cũ.

        Lượt đầu đã đổi ``Idea 7`` thành ``BT_1_001``; đến lượt đánh số lại,
        tên đang có trên thẻ chính là cái mã ấy.  Chép đè thì ``ten_cu`` hoá
        ``BT_1_001`` và tên người ta đặt biến mất — đúng cái mà ô này sinh ra
        để giữ.
        """
        result, _ = self._run(
            [
                ("TASK-1", "", "product: khăn tay"),
                ("TASK-2", "TASK-1", "sku: BT_1_001\nten_cu: Idea 7"),
            ],
            subjects={"TASK-2": "BT_1_001"},
            renumber=True,
        )
        self.assertEqual(["KT_1_001"], [item["sku"] for item in result["written"]])
        self.assertEqual([("TASK-2", "KT_1_001")], self.renames)
        self.assertIn("ten_cu: Idea 7", self.metas["TASK-2"])
        self.assertNotIn("ten_cu: BT_1_001", self.metas["TASK-2"])

    def test_a_card_with_no_name_parks_nothing(self):
        # Không có gì để mất thì không thêm dòng rác vào khối thuộc tính.
        self._run([("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")])
        self.assertNotIn("ten_cu", self.metas["TASK-2"])

    def test_a_code_that_did_not_land_does_not_cost_the_card_its_name(self):
        """ERP gật đầu mà không ghi: không được coi là đã ghi, và không đổi tên.

        Ghi thuộc tính hỏng thì sửa lại được — chạy lượt sau là xong.  Đổi tên
        hỏng thì không: tên ``Idea 7`` mất hẳn mà mã thì chưa bao giờ lên thẻ,
        và người vận hành đọc báo cáo thấy xanh.  Nên phải đọc lại thẻ, thấy
        mã nằm đúng chỗ rồi mới được đụng vào tên.
        """
        result, so = self._run(
            [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")],
            subjects={"TASK-2": "Idea 7"},
            write_vanishes=True,
        )
        self.assertEqual([], self.renames)
        self.assertEqual([], result["written"])
        self.assertEqual(["TASK-2"], [item["task_id"] for item in result["failed"]])
        # Số chưa lên thẻ thì cũng chưa được khai vào sổ.
        self.assertEqual(0, so.floor_idea("BT"))

    def test_a_check_that_could_not_run_keeps_the_code_and_keeps_the_name(self):
        """Không đọc lại được **không** giống với đọc lại thấy trống.

        ERP trả 429 hay hết giờ ở lượt đọc lại thì lượt ghi trước đó nhiều
        phần đã vào rồi — báo là ``failed`` là nói sai, mà lượt sau sẽ không
        cấp lại số ấy nữa vì mã đã nằm trên thẻ.  Ngược lại cũng không được
        đổi tên: chưa nhìn thấy mã thì chưa được phá cái tên.

        Nên ca này giữ cả hai: mã tính là đã ghi, tên để nguyên, và lý do vào
        ô ``rename_failed`` — đúng ô nghĩa là "mã có rồi, tên thì chưa".
        """
        result, so = self._run(
            [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")],
            subjects={"TASK-2": "Idea 7"},
            verify_explodes=True,
        )
        self.assertEqual(["BT_1_001"], [item["sku"] for item in result["written"]])
        self.assertEqual([], result["failed"])
        self.assertEqual([], self.renames)
        self.assertEqual(["TASK-2"], [item["task_id"] for item in result["rename_failed"]])
        self.assertEqual(1, so.floor_idea("BT"))

    def test_a_replica_one_beat_behind_does_not_cost_the_card_its_code(self):
        """Đọc lại chưa thấy mã thì hỏi lại một lần nữa rồi mới kết luận.

        Lượt đọc ngay sau lượt ghi có thể rơi vào bản sao chưa kịp theo.  Kết
        luận "hỏng" ở đấy là sai một cách khó chữa: thẻ *đã* mang mã nên lượt
        chạy sau không xếp nó vào danh sách cần ghi nữa, và cái tên vì thế
        cũng không bao giờ được đổi.
        """
        result, so = self._run(
            [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")],
            subjects={"TASK-2": "Idea 7"},
            verify_lags=True,
        )
        self.assertEqual(["BT_1_001"], [item["sku"] for item in result["written"]])
        self.assertEqual([], result["failed"])
        self.assertEqual([("TASK-2", "BT_1_001")], self.renames)
        self.assertEqual(1, so.floor_idea("BT"))

    def test_a_name_left_behind_by_a_blind_check_is_fixed_on_the_next_run(self):
        """Mã lên thẻ, lượt đọc lại không chạy nổi, tên đứng nguyên — lượt sau phải chữa.

        Đây là lỗi một chiều nặng nhất của cả đường đánh số.  Lượt đầu ghi
        ``sku:`` và ``ten_cu:`` cùng một nhịp, rồi ERP chặn lượt đọc lại
        (429), nên bot không dám đụng vào tên.  Lượt sau thẻ **đã** mang mã
        nên nó rơi vào nhánh "giữ nguyên", không còn nằm trong danh sách cần
        ghi, và cái tên ``Idea 7`` ở lại vĩnh viễn.

        Dấu vết để nhận ra ca này nằm sẵn trên thẻ: ``ten_cu`` đã được chép,
        mà tên thẻ vẫn *đúng bằng* ``ten_cu`` ấy — tức là bước đổi tên chưa
        bao giờ chạy.  Không tốn request nào để biết: ``taskFull`` trả cả tên
        thẻ lẫn khối thuộc tính.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as chung:
            nodes = [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")]
            dau, _ = self._run(
                nodes,
                subjects={"TASK-2": "Idea 7"},
                verify_explodes=True,
                ledger_dir=chung,
            )
            self.assertEqual([], self.renames)
            self.assertEqual(["TASK-2"], [item["task_id"] for item in dau["rename_failed"]])

            # Lượt sau: thẻ mang mã rồi, nhưng tên vẫn là cái tên cũ đang nằm
            # trong ``ten_cu``.  Đó là chữ ký của một lượt đổi tên chưa chạy.
            sau, _ = self._run(
                [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", self.metas["TASK-2"])],
                subjects={"TASK-2": "Idea 7"},
                ledger_dir=chung,
            )
            self.assertEqual([("TASK-2", "BT_1_001")], self.renames)
            self.assertEqual(
                # ``title`` là tên **mới**: lượt chữa tên nay đi hai chiều, và
                # chiều về đặt lại tên cũ chứ không phải mã.
                [
                    {
                        "task_id": "TASK-2",
                        "sku": "BT_1_001",
                        "subject": "Idea 7",
                        "title": "BT_1_001",
                    }
                ],
                sau["renamed"],
            )
            # Không ghi lại mã: thẻ đã mang đúng mã ấy rồi.
            self.assertEqual([], sau["written"])

    def test_a_name_a_person_typed_after_the_code_is_left_alone(self):
        """Người đặt tên khác sau khi thẻ đã có mã thì bot không được đè lên.

        Cái chốt phân biệt là ``ten_cu``: chữa tên chỉ chạy khi tên thẻ còn
        *đúng bằng* tên đã cất đi.  Người gõ tên khác vào là tên ấy không
        khớp nữa, và lượt chữa đi qua.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as chung:
            ket_qua, _ = self._run(
                [
                    ("TASK-1", "", "product: bờm"),
                    ("TASK-2", "TASK-1", "sku: BT_1_001\nten_cu: Idea 7"),
                ],
                subjects={"TASK-2": "Khăn tay đỏ viền ren"},
                ledger_dir=chung,
            )
            self.assertEqual([], self.renames)
            self.assertEqual([], ket_qua["renamed"])

    def test_the_repair_pass_obeys_the_rename_switch(self):
        # Tắt đổi tên thì lượt chữa cũng phải im, không thì cái công tắc nói dối.
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"ERP_SKU_RENAME_TASK": "0"}):
            ket_qua, _ = self._run(
                [
                    ("TASK-1", "", "product: bờm"),
                    ("TASK-2", "TASK-1", "sku: BT_1_001\nten_cu: Idea 7"),
                ],
                subjects={"TASK-2": "Idea 7"},
            )
        self.assertEqual([], self.renames)
        self.assertEqual([], ket_qua["renamed"])

    def test_a_dry_run_repairs_no_name(self):
        ket_qua, _ = self._run(
            [
                ("TASK-1", "", "product: bờm"),
                ("TASK-2", "TASK-1", "sku: BT_1_001\nten_cu: Idea 7"),
            ],
            subjects={"TASK-2": "Idea 7"},
            dry_run=True,
        )
        self.assertEqual([], self.renames)
        self.assertEqual([], ket_qua["renamed"])

    def test_a_write_that_vanished_while_the_check_was_blind_keeps_its_number(self):
        """Ca xấu nhất còn lại: ERP gật lượt ghi mà không ghi, *và* đọc lại không nổi.

        Trước đây chỗ này cố ý đốt một số: khai vào sổ rồi, lượt sau thẻ nhận
        số kế tiếp, số cũ nằm không.  Lý do vẫn đúng — **không** khai thì sổ
        tụt một nấc và một bảng khác cùng đầu mã có thể cấp trùng đúng số ấy.

        Nhưng "khai vào sổ" và "đốt số" là hai việc, không phải một.  Số vẫn
        được khai, nên mốc không tụt và không bảng nào cấp trùng; đồng thời nó
        được **giữ chỗ theo đúng thẻ** đã ghi hụt.  Lượt sau, chính thẻ ấy
        nhận lại chính số ấy.  Không thủng, cũng không trùng.

        Tên thẻ không bị đụng trong cả hai lượt — đó mới là thứ không lấy lại
        được.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as chung:
            nodes = [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")]
            result, so = self._run(
                nodes,
                subjects={"TASK-2": "Idea 7"},
                write_vanishes=True,
                verify_explodes=True,
                ledger_dir=chung,
            )
            self.assertEqual(["BT_1_001"], [item["sku"] for item in result["written"]])
            self.assertEqual([], self.renames)
            # Mốc vẫn dịch lên: bảng khác cùng đầu mã không được cấp trùng.
            self.assertEqual(1, so.floor_idea("BT"))
            # Và số ấy đứng tên đúng cái thẻ đã ghi hụt.
            self.assertEqual("BT_1_001", so.reserved_for("TASK-2"))

            # Lượt sau: thẻ vẫn trống, nó lại nằm trong danh sách cần ghi — và
            # nhận lại **đúng số đã giữ chỗ**, không phải số kế tiếp.
            lai, so = self._run(nodes, subjects={"TASK-2": "Idea 7"}, ledger_dir=chung)
            self.assertEqual(["BT_1_001"], [item["sku"] for item in lai["written"]])
            self.assertEqual([("TASK-2", "BT_1_001")], self.renames)
            # Ghi xong, đọc lại thấy mã: chỗ giữ trả lại cho sổ.
            self.assertEqual("", so.reserved_for("TASK-2"))

    def test_a_reserved_number_is_never_handed_to_another_card(self):
        """Chỗ giữ là của **một** thẻ, không phải một chỗ trống ai vào cũng được.

        Lượt sau bảng có thêm thẻ mới.  Thẻ ghi hụt lấy lại số của nó, thẻ mới
        phải nhận số kế tiếp — hai thẻ một mã là thứ không gọi về được.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as chung:
            self._run(
                [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")],
                write_vanishes=True,
                verify_explodes=True,
                ledger_dir=chung,
            )
            lai, _ = self._run(
                [
                    ("TASK-1", "", "product: bờm"),
                    ("TASK-2", "TASK-1", ""),
                    ("TASK-3", "TASK-1", ""),
                ],
                ledger_dir=chung,
            )
            self.assertEqual(
                {"TASK-2": "BT_1_001", "TASK-3": "BT_1_002"},
                {item["task_id"]: item["sku"] for item in lai["written"]},
            )

    def test_a_card_that_took_the_code_by_itself_frees_the_reservation(self):
        """Đọc lại được rồi thì chỗ giữ không được nằm lại trong sổ mãi.

        Ca này là ca lành: lượt trước ghi hụt và giữ chỗ, nhưng đến lượt sau
        thẻ đã mang đúng mã ấy (người gõ tay, hoặc lượt ghi kia vào muộn).
        Sổ phải tự dọn, không thì file sổ phình ra bằng số lần ERP chập.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as chung:
            self._run(
                [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")],
                write_vanishes=True,
                verify_explodes=True,
                ledger_dir=chung,
            )
            _, so = self._run(
                [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "sku: BT_1_001")],
                ledger_dir=chung,
            )
            self.assertEqual("", so.reserved_for("TASK-2"))


class SkuBookSourceTests(unittest.TestCase):
    """Nguồn nào thắng nguồn nào khi tra bảng sản phẩm → phần tên SKU.

    Ba nguồn: biến môi trường ``FLOW_SKU_MAP``, bảng Sheet của xưởng, và file
    app giữ trên đĩa.  Sheet là bảng **người ta đang sửa hằng ngày**, nên sửa
    một dòng trên Sheet phải tới được app; file trên đĩa chỉ là bản chép lại
    để lượt chạy không đứng khi mạng chập.
    """

    ROWS = [{"Sản phẩm": "khăn tay", "Mã": "HA"}]

    def _service(self, tmp, *, url="", rows=None, explodes=False, state_url=None):
        from flow_web.service import FlowWebService

        svc = FlowWebService.__new__(FlowWebService)
        svc._sku_book_path = lambda: Path(tmp) / "sku_book.json"

        def doc(_url):
            if explodes:
                raise RuntimeError("Sheet riêng tư, không mở được")
            return list(rows if rows is not None else self.ROWS)

        svc._load_prompt_source_url = doc
        svc._redact_erp_secret = lambda value: value
        svc._erp_sku_sheet_url = lambda: str(state_url if state_url is not None else url or "")
        return svc

    def _disk(self, tmp, entries):
        import json

        path = Path(tmp) / "sku_book.json"
        path.write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")

    def test_the_sheet_beats_the_copy_the_app_keeps_on_disk(self):
        """Sửa Sheet phải tới được app.

        Trước đây file trên đĩa chồng lên Sheet, nên một dòng sửa trên Sheet
        không bao giờ tới nơi: app cứ tra bản chép cũ, và người vận hành sửa
        xong vẫn thấy mã cũ in ra.
        """
        import os
        import tempfile
        from unittest.mock import patch

        from flow_web.service import FlowWebService

        with tempfile.TemporaryDirectory() as tmp:
            self._disk(tmp, {"khăn tay": "KT"})
            svc = self._service(tmp, url="https://docs.google.com/spreadsheets/d/x/edit")
            with patch.dict(os.environ, {"FLOW_SKU_MAP": ""}):
                book = FlowWebService.load_sku_book(svc)
        self.assertEqual("HA", book.lookup("khăn tay")[0])

    def test_a_sheet_that_will_not_open_leaves_the_disk_copy_in_charge(self):
        """Sheet hỏng thì lượt đánh số vẫn chạy, bằng bản chép trên đĩa.

        Đó là lý do bản chép tồn tại.  Link riêng tư, mạng chập, Google chặn —
        không cái nào được phép làm cả bảng đứng lại.
        """
        import os
        import tempfile
        from unittest.mock import patch

        from flow_web.service import FlowWebService

        with tempfile.TemporaryDirectory() as tmp:
            self._disk(tmp, {"khăn tay": "KT"})
            svc = self._service(tmp, url="https://docs.google.com/x", explodes=True)
            with patch.dict(os.environ, {"FLOW_SKU_MAP": ""}), patch("flow_web.service.log"):
                book = FlowWebService.load_sku_book(svc)
        self.assertEqual("KT", book.lookup("khăn tay")[0])

    def test_a_sheet_row_the_sheet_does_not_have_still_comes_off_the_disk(self):
        # Hai nguồn *gộp* lại chứ không thay nhau: Sheet thắng ở dòng nó có,
        # dòng nó không có thì bản trên đĩa vẫn dùng được.
        import os
        import tempfile
        from unittest.mock import patch

        from flow_web.service import FlowWebService

        with tempfile.TemporaryDirectory() as tmp:
            self._disk(tmp, {"khăn tay": "KT", "bờm": "BT"})
            svc = self._service(tmp, url="https://docs.google.com/x")
            with patch.dict(os.environ, {"FLOW_SKU_MAP": ""}):
                book = FlowWebService.load_sku_book(svc)
        self.assertEqual("HA", book.lookup("khăn tay")[0])
        self.assertEqual("BT", book.lookup("bờm")[0])

    def test_the_env_map_still_beats_the_sheet(self):
        """``FLOW_SKU_MAP`` là đường tay, và đường tay thì thắng tất.

        Một máy cần cấp mã ngay trong lúc bảng thật còn đang sửa vẫn phải làm
        được, không thì người ta lại đi sửa thẳng vào Sheet chung.
        """
        import os
        import tempfile
        from unittest.mock import patch

        from flow_web.service import FlowWebService

        with tempfile.TemporaryDirectory() as tmp:
            self._disk(tmp, {"khăn tay": "KT"})
            svc = self._service(tmp, url="https://docs.google.com/x")
            with patch.dict(os.environ, {"FLOW_SKU_MAP": "khăn tay=ZZ"}):
                book = FlowWebService.load_sku_book(svc)
        self.assertEqual("ZZ", book.lookup("khăn tay")[0])

    def test_the_sheet_link_can_live_in_the_app_config_not_only_in_env(self):
        """Link Sheet khai được qua màn hình cấu hình ERP.

        ``.env.local`` là file người ta sửa bằng tay rồi khởi động lại dịch
        vụ.  Đổi bảng SKU thì không nên phải làm thế, nên link còn một chỗ
        nữa: cấu hình ERP của app, sửa xong là ăn ngay.
        """
        import os
        import tempfile
        from unittest.mock import patch

        from flow_web.service import FlowWebService

        with tempfile.TemporaryDirectory() as tmp:
            self._disk(tmp, {"khăn tay": "KT"})
            svc = self._service(tmp, state_url="https://docs.google.com/spreadsheets/d/y/edit")
            with patch.dict(os.environ, {"FLOW_SKU_MAP": "", "FLOW_SKU_SHEET_URL": ""}):
                book = FlowWebService.load_sku_book(svc)
        self.assertEqual("HA", book.lookup("khăn tay")[0])


class SkuSheetUrlTests(unittest.TestCase):
    """``_erp_sku_sheet_url``: cấu hình app thắng, không có thì tới biến môi trường."""

    def _service(self, saved):
        from flow_web.schemas import ERPConfig
        from flow_web.service import FlowWebService

        class _Store:
            def snapshot(self):
                class _Snap:
                    erp_config = ERPConfig(sku_sheet_url=saved)

                return _Snap()

        svc = FlowWebService.__new__(FlowWebService)
        svc.store = _Store()
        return svc

    def test_the_saved_link_wins(self):
        import os
        from unittest.mock import patch

        from flow_web.service import FlowWebService

        svc = self._service("https://docs.google.com/spreadsheets/d/state/edit")
        with patch.dict(os.environ, {"FLOW_SKU_SHEET_URL": "https://docs.google.com/env"}):
            self.assertEqual(
                "https://docs.google.com/spreadsheets/d/state/edit",
                FlowWebService._erp_sku_sheet_url(svc),
            )

    def test_no_saved_link_falls_back_to_env(self):
        import os
        from unittest.mock import patch

        from flow_web.service import FlowWebService

        svc = self._service("")
        with patch.dict(os.environ, {"FLOW_SKU_SHEET_URL": "https://docs.google.com/env"}):
            self.assertEqual(
                "https://docs.google.com/env", FlowWebService._erp_sku_sheet_url(svc)
            )



class SkuSheetUrlSurvivesTheStoreTests(unittest.TestCase):
    """Link sheet phải sống qua lượt lưu, không chỉ sống trong bộ nhớ.

    ``StateStore`` chuẩn hoá cấu hình ERP bằng cách **dựng lại** ``ERPConfig``
    từng trường một.  Trường nào nó không biết thì rơi mất im lặng: API trả 200,
    màn hình bảo đã lưu, mà lượt đọc ngay sau đó thấy ô rỗng — người vận hành
    dán link vào rồi vẫn không hiểu vì sao bot tra bảng cũ.
    """

    LINK = "https://docs.google.com/spreadsheets/d/1LsGG/edit?gid=284085791"

    def setUp(self) -> None:
        import asyncio
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from flow_web.store import StateStore

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.patches = [
            patch("flow_web.store.STATE_FILE", root / "state.json"),
            patch(
                "flow_web.store.ensure_app_dirs",
                lambda: root.mkdir(parents=True, exist_ok=True),
            ),
        ]
        for item in self.patches:
            item.start()
        self.store = StateStore()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tempdir.cleanup()
        self.loop.close()

    def test_the_link_is_still_there_after_the_store_normalises_it(self) -> None:
        from flow_web.schemas import ERPConfig

        saved = self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(
                    api_key="k",
                    api_secret="s",
                    project_id="PROJ-0018",
                    sku_sheet_url=self.LINK,
                )
            )
        )

        self.assertEqual(self.LINK, saved.sku_sheet_url)
        self.assertEqual(self.LINK, self.store.snapshot().erp_config.sku_sheet_url)


class SeedLedgerTests(unittest.TestCase):
    """Nạp sổ một lượt từ bảng, cho cái khe sổ tự lành không với tới được.

    Sổ tự học lại từ mã trên thẻ mỗi lần đánh số — nhưng chỉ trên cây nó chạm
    tới.  Trên máy vừa dựng, cây đầu tiên có thể là một cây còn trắng, và lúc
    ấy sổ trống thì nó cấp lại đúng những số đang nằm trên cây bên cạnh.
    """

    BOARD = {
        "columns": [
            {
                "name": "Open",
                "tasks": [
                    {"name": "TASK-1", "parent_task": ""},
                    {"name": "TASK-2", "parent_task": "TASK-1"},
                    {"name": "TASK-9", "parent_task": ""},
                ],
            }
        ]
    }
    TREES = {
        "TASK-1": {
            "root": {
                "name": "TASK-1",
                "meta": "product: bờm",
                "subtasks": [{"name": "TASK-2", "meta": "sku: BT_3_010", "subtasks": []}],
            }
        },
        "TASK-9": {"root": {"name": "TASK-9", "meta": "sku: KT_1_004", "subtasks": []}},
    }

    def _run(self, tmp, *, board=None, board_broken=False, broken_trees=()):
        from unittest.mock import patch

        from flow_web.service import FlowWebService

        fetched = []
        svc = FlowWebService.__new__(FlowWebService)
        svc._sku_ledger_path = lambda: Path(tmp) / "sku_ledger.json"
        svc._erp_credentials = lambda: ("k", "t")
        svc._erp_allowed_project_ids = lambda: ["PROJ-1"]

        def read_board(key, token, project):
            if board_broken:
                raise RuntimeError("ERP trả 500")
            return board if board is not None else self.BOARD

        def read_tree(key, token, root):
            fetched.append(root)
            if root in broken_trees:
                raise RuntimeError("ERP trả 500")
            return self.TREES.get(root, {"root": {}})

        svc._erp_task_board = read_board
        svc._erp_task_full = read_tree
        with patch("flow_web.service.log"):
            return FlowWebService.seed_sku_ledger(svc), FlowWebService.load_sku_ledger(svc), fetched

    def test_every_code_on_the_board_ends_up_in_the_ledger(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            _, so, _ = self._run(tmp)
        self.assertEqual((3, 10), (so.floor_project("BT"), so.floor_idea("BT")))
        self.assertEqual((1, 4), (so.floor_project("KT"), so.floor_idea("KT")))

    def test_only_the_root_cards_cost_a_request(self):
        # ``flatten_tree`` đã lấy hết con cháu; đọc thêm từng thẻ con chỉ tiêu
        # mất suất trong trần 60 request/phút mà không biết thêm gì.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            _, _, fetched = self._run(tmp)
        self.assertEqual(["TASK-1", "TASK-9"], fetched)

    def test_a_board_that_would_not_load_costs_that_board_only(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result, so, _ = self._run(tmp, board_broken=True)
        self.assertIn("error", result["projects"][0])
        self.assertFalse(result["changed"])
        self.assertEqual(0, so.floor_idea("BT"))

    def test_one_unreadable_tree_does_not_lose_the_others(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            _, so, _ = self._run(tmp, broken_trees=("TASK-1",))
        self.assertEqual(0, so.floor_idea("BT"))
        self.assertEqual(4, so.floor_idea("KT"))

    def test_running_it_twice_changes_nothing_the_second_time(self):
        # Chỉ nâng, không hạ — nên chạy lại bao nhiêu lần cũng vô hại.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            first, _, _ = self._run(tmp)
            second, so, _ = self._run(tmp)
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual((3, 10), (so.floor_project("BT"), so.floor_idea("BT")))

    def test_a_board_with_no_codes_yet_leaves_the_ledger_alone(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result, so, _ = self._run(tmp, board={"columns": []})
        self.assertFalse(result["changed"])
        self.assertEqual({}, so.as_dict()["idea_seq"])

    def test_a_seeded_ledger_stops_the_very_first_tree_from_colliding(self):
        """Cả script này tồn tại vì đúng dòng cuối cùng ở đây.

        Không nạp sổ thì cây trắng đầu tiên trên máy mới cấp lại ``BT_1_001``
        — mã đang nằm trên một thẻ nó chưa từng đọc.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            _, so, _ = self._run(tmp)
        blank = [card("TASK-77", meta="product: bờm"), card("TASK-78", "TASK-77")]
        self.assertEqual(
            "BT_1_001",
            plan_skus(blank, BOOK, root_id="TASK-77", project_id="PROJ-9").assignments[0].sku,
        )
        self.assertEqual(
            "BT_4_011",
            plan_skus(
                blank, BOOK, root_id="TASK-77", ledger=so, project_id="PROJ-9"
            ).assignments[0].sku,
        )


class RouteGuardTests(unittest.TestCase):
    """Thiếu thẻ gốc là lỗi người gọi, và người gọi phải đọc được lý do.

    Không có nó thì ``RuntimeError`` trong service rơi thẳng ra ngoài thành
    ``500 Internal Server Error`` với thân rỗng: người bấm nút chỉ thấy "máy
    chủ hỏng" trong khi thứ duy nhất hỏng là ô Task ID còn trống.
    """

    def test_a_missing_task_id_is_a_400_with_a_readable_reason(self):
        from fastapi import HTTPException

        from flow_web.main import _sku_task_id

        with self.assertRaises(HTTPException) as caught:
            _sku_task_id(SkuSyncRequest())
        self.assertEqual(400, caught.exception.status_code)
        self.assertIn("Task ID", caught.exception.detail)

    def test_a_blank_task_id_is_refused_too(self):
        from fastapi import HTTPException

        from flow_web.main import _sku_task_id

        with self.assertRaises(HTTPException):
            _sku_task_id(SkuSyncRequest(task_id="   "))

    def test_a_real_task_id_comes_back_trimmed(self):
        from flow_web.main import _sku_task_id

        self.assertEqual("TASK-2026-00202", _sku_task_id(SkuSyncRequest(task_id=" TASK-2026-00202 ")))


class BotSkuHookTests(unittest.TestCase):
    """Bot nghe “điền sku đi” trên thẻ thì phải chạm được vào đường đánh số thật.

    Trước đây đổi ``product:`` xong vẫn phải có người mở dòng lệnh gọi một lượt
    cấp mã — mà người gõ ``product:`` thì đang đứng trên ERP.  Cả cái nối này
    hỏng theo kiểu không kêu: bot vẫn trả lời tử tế, chỉ là không thẻ nào có mã.
    """

    def _service(self):
        from flow_web.account_book import AccountBook
        from flow_web.service import FlowWebService

        svc = FlowWebService.__new__(FlowWebService)
        svc._erp_base_url = lambda: "https://erp.invalid"
        svc.load_account_book = lambda: AccountBook(entries={})
        return svc

    def _hook(self, svc):
        from unittest.mock import patch

        seen = {}

        def build(config, **kwargs):
            seen.update(kwargs)
            return object()

        with patch("flow_web.service.build_agent_bot", build):
            svc.agent_bot()
        return seen.get("sku_hook")

    def test_the_app_hands_the_bot_a_way_to_number_a_cluster(self):
        self.assertIsNotNone(
            self._hook(self._service()),
            "app dựng bot mà không nối sku_hook: mọi câu 'điền sku đi' đều bị từ chối")

    def test_the_hook_reaches_the_real_numbering_call(self):
        svc = self._service()
        calls = []
        svc.fill_task_skus = lambda task_id, *, renumber: calls.append((task_id, renumber))
        self._hook(svc)("TASK-1", False)
        self.assertEqual([("TASK-1", False)], calls)

    def test_the_overwrite_flag_survives_the_trip(self):
        # Cờ này là khác biệt giữa "điền chỗ trống" và "xoá mã đã in lên tem".
        svc = self._service()
        calls = []
        svc.fill_task_skus = lambda task_id, *, renumber: calls.append((task_id, renumber))
        self._hook(svc)("TASK-1", True)
        self.assertEqual([("TASK-1", True)], calls)

    def test_the_destructive_flag_cannot_be_passed_by_position(self):
        # Giữ ``renumber`` là keyword-only: một tham số thứ hai lỡ tay truyền
        # theo vị trí ở đây sẽ ghi đè mã của cả một cụm hàng đã lên shop.
        from flow_web.service import FlowWebService

        with self.assertRaises(TypeError):
            FlowWebService.fill_task_skus(self._service(), "TASK-1", True)

    def test_the_http_route_still_gets_an_awaitable_of_the_same_work(self):
        # Route đứng trong vòng lặp sự kiện, bot thì đứng trong ``to_thread``.
        # Hai người gọi, một thuật toán — bản async chỉ được phép là lớp bọc.
        import asyncio

        from flow_web.service import FlowWebService

        svc = self._service()
        calls = []

        def record(task_id, *, dry_run=False, renumber=False):
            calls.append((task_id, dry_run, renumber))
            return {"written": []}

        svc.fill_task_skus = record
        result = asyncio.run(
            FlowWebService.sync_erp_skus(svc, "TASK-1", dry_run=True, renumber=True))

        self.assertEqual([("TASK-1", True, True)], calls)
        self.assertEqual({"written": []}, result)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class SkuDoanThiPhaiNoi(unittest.TestCase):
    """Bảng SKU thiếu dòng thì thẻ **để trống mã**, và bot nói ra điều đó.

    Đổi yêu cầu theo a Trung Anh, 11/09/2026.  Trước đây bot đoán mã theo
    chữ cái đầu rồi nhắc là đang đoán.  Cách ấy đã ghi ``PNO_1_001…010`` lên
    mười thẻ của PROJ-0087: gốc khai ``Punch Needle Ornament``, bảng chưa có
    dòng ấy, trong khi xưởng gọi món này là ``OL`` ("ornament len chọc").
    Mã đã lên thẻ là đi ra listing, nhắc sau không thu lại được.

    Nên giờ: không cấp mã đoán, ghi chú một lần "chưa có mã trong bảng SKU
    cho <sản phẩm>" lên thẻ gốc, và đưa tên sản phẩm vào báo cáo lượt.

    Mượn ERP giả của :class:`FillLedgerTests` chứ không kế thừa nó: kế thừa
    thì cả bộ test của lớp kia chạy lại lần thứ hai dưới tên lớp này.
    """

    _payload = staticmethod(FillLedgerTests._payload)
    _run = FillLedgerTests._run

    def test_cau_nhac_goi_ten_san_pham_va_khong_neu_ma_doan(self):
        loi = pipeline.sku_missing_help("Embroidered Ornament")
        self.assertIn("Chưa có mã trong bảng SKU cho “Embroidered Ornament”", loi)
        # Không nêu mã đoán nào: người đọc thấy "EO" là tưởng bot sắp cấp EO.
        self.assertNotIn("EO", loi)

    def test_san_pham_khong_co_trong_bang_thi_the_de_trong_ma(self):
        result, _ = self._run(
            [("TASK-1", "", "product: Embroidered Ornament"), ("TASK-2", "TASK-1", "")]
        )
        self.assertEqual([], result["written"], "mã đoán không được lên thẻ")
        self.assertEqual([], result["assignments"])
        self.assertNotIn("sku", self.metas["TASK-2"])
        self.assertEqual([], self.renames)
        self.assertIn(
            {"task_id": "TASK-2", "reason": "chưa có mã trong bảng SKU cho Embroidered Ornament"},
            result["skipped"],
        )
        # Báo cáo lượt nói ra món nào đang thiếu dòng, và không nêu mã đoán.
        self.assertEqual(["Embroidered Ornament"], result["unlisted"])
        self.assertEqual("", result["prefix"])

    def test_san_pham_khong_co_trong_bang_thi_bot_ghi_chu_len_the_goc(self):
        self._run(
            [("TASK-1", "", "product: Embroidered Ornament"), ("TASK-2", "TASK-1", "")]
        )
        self.assertEqual(
            1,
            len(self.comments),
            "thẻ trống mã mà không ai nói vì sao thì chỉ người soi mắt mới thấy",
        )
        task_id, noi_dung = self.comments[0]
        self.assertEqual("TASK-1", task_id)
        self.assertIn("Chưa có mã trong bảng SKU cho “Embroidered Ornament”", noi_dung)

    def test_ghi_chu_chi_mot_lan_cho_moi_cum(self):
        """Làn nhanh quét 15 giây một nhịp: nhắc mỗi nhịp là thành tiếng ồn."""
        from flow_web.service import FlowWebService

        svc = FlowWebService.__new__(FlowWebService)
        comments = []
        svc._erp_comment = lambda key, token, task_id, content, **kw: comments.append(task_id)
        plan = SkuPlan(root_id="TASK-1", unlisted=("Embroidered Ornament",))
        with patch("flow_web.service.log"):
            for _ in range(3):
                FlowWebService._note_sku_unlisted(svc, "k", "t", plan)
            FlowWebService._note_sku_unlisted(
                svc, "k", "t", SkuPlan(root_id="TASK-9", unlisted=("Embroidered Ornament",))
            )
        self.assertEqual(["TASK-1", "TASK-9"], comments)

    def test_dang_ghi_chu_hong_thi_nhip_sau_thu_lai(self):
        from flow_web.service import FlowWebService

        svc = FlowWebService.__new__(FlowWebService)
        tries = []

        def comment(key, token, task_id, content, **kw):
            tries.append(task_id)
            if len(tries) == 1:
                raise RuntimeError("ERP trả 500")
            return {}

        svc._erp_comment = comment
        plan = SkuPlan(root_id="TASK-1", unlisted=("Embroidered Ornament",))
        with patch("flow_web.service.log"):
            for _ in range(3):
                FlowWebService._note_sku_unlisted(svc, "k", "t", plan)
        self.assertEqual(["TASK-1", "TASK-1"], tries)

    def test_san_pham_co_trong_so_thi_khong_nhac_gi_ca(self):
        result, _ = self._run(
            [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")]
        )
        self.assertEqual("book", result["prefix_source"])
        self.assertEqual([], result["unlisted"])
        self.assertEqual(
            [], self.comments, "nhắc cả lúc sổ có dòng thì lời nhắc thành tiếng ồn"
        )

    def test_chay_kho_thi_khong_dang_gi_len_ERP(self):
        result, _ = self._run(
            [("TASK-1", "", "product: Embroidered Ornament"), ("TASK-2", "TASK-1", "")],
            dry_run=True,
        )
        self.assertEqual([], self.comments)
        self.assertEqual(["Embroidered Ornament"], result["unlisted"])


class KhongCapMaDoan(unittest.TestCase):
    """Ca thật 11/09/2026: PROJ-0087, gốc 05384 khai ``Punch Needle Ornament``.

    Bảng thật có dòng ``ornament len chọc`` → ``OL`` nhưng không có tên tiếng
    Anh kia.  Bot cũ đoán ra ``PNO`` và ghi lên mười thẻ.
    """

    _GOC = "product_type: Punch Needle Ornament"

    def _cards(self, *, child_meta=""):
        return flatten_tree(
            {
                "name": "TASK-2026-05384",
                "meta": self._GOC,
                "project": "PROJ-0087",
                "subtasks": [
                    {"name": "TASK-2026-05397", "meta": child_meta, "status": "Working", "project": "PROJ-0087"},
                    {"name": "TASK-2026-05400", "meta": child_meta, "status": "Working", "project": "PROJ-0087"},
                ],
            }
        )

    def test_bang_khong_co_ten_tieng_anh_thi_khong_ra_PNO(self):
        book = ProductBook.from_mapping({"ornament len chọc": "OL"})
        plan = plan_skus(self._cards(), book, root_id="TASK-2026-05384")
        self.assertEqual((), plan.assignments)
        self.assertEqual("", plan.prefix, "mã đoán không được nói ra kể cả trong báo cáo")
        self.assertEqual(("Punch Needle Ornament",), plan.unlisted)
        self.assertEqual(
            {
                ("TASK-2026-05397", "chưa có mã trong bảng SKU cho Punch Needle Ornament"),
                ("TASK-2026-05400", "chưa có mã trong bảng SKU cho Punch Needle Ornament"),
            },
            set(plan.skipped),
        )

    def test_sheet_them_ten_tieng_anh_thi_ra_OL(self):
        """Thêm ``Punch Needle Ornament`` vào cột tên mới của dòng OL là đủ."""
        book = ProductBook.from_rows(
            [{"product_type": "ornament len chọc", "TÊN MỚI": "Punch Needle Ornament", "SKU": "OL"}]
        )
        plan = plan_skus(self._cards(), book, root_id="TASK-2026-05384")
        self.assertEqual(["OL_1_001", "OL_1_002"], [item.sku for item in plan.assignments])
        self.assertEqual((), plan.unlisted)

    def test_the_khai_ten_viet_thi_ra_OL(self):
        book = ProductBook.from_mapping({"ornament len chọc": "OL"})
        plan = plan_skus(
            self._cards(child_meta="product_type: ornament len chọc"), book, root_id="TASK-2026-05384"
        )
        self.assertEqual(["OL_1_001", "OL_1_002"], [item.sku for item in plan.assignments])

    def test_the_da_mang_ma_cu_thi_giu_nguyen(self):
        """Người dùng chốt: thẻ đã có mã thì giữ.  Đổi mã chỉ qua đánh lại đích danh."""
        book = ProductBook.from_mapping({"ornament len chọc": "OL"})
        plan = plan_skus(
            self._cards(child_meta="sku: PNO_1_001"), book, root_id="TASK-2026-05384"
        )
        self.assertEqual([], [item for item in plan.assignments if not item.kept])


class BiDanhTiengAnh(unittest.TestCase):
    """Thẻ ERP khai ``product_type`` bằng **tiếng Anh**, sheet đặt tên hàng bằng
    tiếng Việt — hai đầu không bao giờ gặp nhau nếu chỉ đọc một cột.

    Sheet có sẵn cột tên tiếng Anh.  Dùng được nó thì ``Apron`` ra ``TD`` mà
    không ai phải chép tay dòng nào.  Nhưng cột ấy **không** phải khoá: bảy
    tên trong bảng thật ứng với nhiều mặt hàng — ``Tote Bag`` vừa là ``TO``
    (túi tote) vừa là ``GT`` (giỏ thêu).  Gán bừa một trong hai là in sai mã
    lên thùng hàng mà không ai biết.  Tra không ra thì ``lookup`` nói là
    ``derived``, và :func:`plan_skus` để trống mã rồi nói ra là bảng thiếu dòng.
    """

    _rows = [
        {"TÊN HÀNG": "tạp dề", "TÊN MỚI": "Apron", "TÊN KHAI BÁO": "Women's Dress", "SKU": "TD"},
        {"TÊN HÀNG": "túi tote", "TÊN MỚI": "Tote Bag", "TÊN KHAI BÁO": "Cotton Tote bag", "SKU": "TO"},
        {"TÊN HÀNG": "giỏ thêu", "TÊN MỚI": "Tote Bag", "TÊN KHAI BÁO": "Cotton Tote bag", "SKU": "GT"},
    ]

    def test_ten_tieng_anh_mot_nghia_thi_tra_duoc(self):
        book = ProductBook.from_rows(self._rows)
        self.assertEqual(("TD", "book-alias"), book.lookup("Apron"))

    def test_ten_tieng_anh_hai_nghia_thi_khong_tra(self):
        book = ProductBook.from_rows(self._rows)
        ma, nguon = book.lookup("Tote Bag")
        self.assertEqual("derived", nguon, "hai mặt hàng chung một tên thì không được chọn hộ")
        self.assertNotIn(ma, ("TO", "GT"))

    def test_ten_hang_van_thang_ten_tieng_anh(self):
        """Cùng một chữ nằm ở cả hai cột thì cột tên hàng là cột đúng."""
        book = ProductBook.from_rows(
            [
                {"TÊN HÀNG": "apron", "SKU": "AA"},
                {"TÊN HÀNG": "tạp dề", "TÊN MỚI": "Apron", "SKU": "TD"},
            ]
        )
        self.assertEqual(("AA", "book"), book.lookup("Apron"))

    def test_ten_khai_bao_khong_phai_ten_san_pham(self):
        """``TÊN KHAI BÁO`` là câu khai hải quan, cố ý chung chung.

        ``Polyester household ornament`` phủ bốn mặt hàng khác nhau trong bảng
        thật.  Nhận nó làm tên sản phẩm là mở đường cho đúng cái nhầm mà bài
        test trên vừa chặn.
        """
        book = ProductBook.from_rows(self._rows)
        self.assertEqual("derived", book.lookup("Women's Dress")[1])

    def test_bi_danh_khong_ghi_xuong_dia(self):
        """``as_dict`` là hợp đồng của file trên đĩa: chỉ tên hàng, không bí danh.

        Bí danh dựng lại từ sheet mỗi lượt đọc.  Ghi chúng xuống đĩa thì lượt
        sau bản chép cũ vẫn giữ một bí danh mà sheet đã sửa hoặc đã xoá.
        """
        book = ProductBook.from_rows(self._rows)
        self.assertEqual({"tap de": "TD", "tui tote": "TO", "gio theu": "GT"}, book.as_dict())

    def test_ma_tra_duoc_tu_bi_danh_khong_bi_coi_la_doan(self):
        """Bí danh là dòng người ta *đã* khai trong sheet, không phải bot đoán."""
        self.assertFalse(sku.la_ma_doan("book-alias"))
        self.assertFalse(sku.la_ma_doan("book"))
        self.assertFalse(sku.la_ma_doan("book-contains"))
        self.assertTrue(sku.la_ma_doan("derived"))
        self.assertTrue(sku.la_ma_doan(""))


# ── Mỗi lúc một lượt đánh số ──────────────────────────────────────────────


class _ErpMemory:
    """ERP giả có trí nhớ, dùng chung giữa nhiều luồng.

    Lần đầu mỗi luồng đọc ``taskDetail`` thì nó dừng ở một cái barrier: hai
    lượt cùng đọc thẻ trước khi lượt nào kịp ghi — đúng khe hở đã cho 05463
    hai mã OL_1_045 rồi OL_1_046.  Có khoá chung thì lượt thứ hai không bao
    giờ tới barrier khi lượt đầu còn chạy; barrier hết giờ, vỡ, và cả hai đi
    tiếp một mình.
    """

    def __init__(self, clusters, *, ledger_dir, board=None):
        self.clusters = clusters
        self.metas = {name: meta for nodes in clusters.values() for name, _, meta in nodes}
        # Cột *Đang làm* từ trên xuống; mặc định theo số task.
        self.board = board or sorted(
            (name for nodes in clusters.values() for name, parent, _ in nodes if parent),
            key=sku.task_number,
        )
        self.writes = collections.Counter()
        self.barrier = threading.Barrier(2, timeout=0.5)
        self.ledger_dir = ledger_dir
        self._seen = set()
        self._lock = threading.Lock()

    def payload(self, root):
        # Dựng lại từ khối thuộc tính *hiện tại*: lượt sau phải thấy cái lượt
        # trước vừa ghi.
        return FillLedgerTests._payload(
            [(name, parent, self.metas[name]) for name, parent, _ in self.clusters[root]]
        )

    def read_detail(self, key, token, task_id):
        snapshot = {"meta": self.metas.get(task_id, ""), "subject": ""}
        me = threading.get_ident()
        with self._lock:
            first = me not in self._seen
            self._seen.add(me)
        if first:
            try:
                self.barrier.wait()
            except threading.BrokenBarrierError:
                pass
        return snapshot

    def write_meta(self, key, token, task_id, block):
        with self._lock:
            self.writes[task_id] += 1
            self.metas[task_id] = block
        return {}

    def sku(self, task_id):
        return task_meta({"meta": self.metas.get(task_id, "")}).sku

    def service(self):
        from flow_web.service import FlowWebService

        svc = FlowWebService.__new__(FlowWebService)
        svc._sku_ledger_path = lambda: Path(self.ledger_dir) / "sku_ledger.json"
        svc._erp_credentials = lambda: ("k", "t")
        svc._normalize_erp_task_id = lambda value: value
        svc._erp_assert_task_in_project = lambda *a, **k: None
        svc._erp_task_full = lambda key, token, root: self.payload(root)
        svc._erp_task_board = lambda key, token, project: _board_of(self.board)
        svc.load_sku_book = lambda *a, **k: BOOK
        svc._erp_task_detail = self.read_detail
        svc._erp_update_task_meta = self.write_meta
        svc._erp_update_task_title = lambda *a, **k: {}
        svc._erp_comment = lambda *a, **k: {}
        return svc


class ConcurrentFillTests(unittest.TestCase):
    """Hai lượt ``fill_task_skus`` chạy cùng lúc: bot quét, người bấm, làn nhanh.

    Ca thật trên PROJ-0087: 05463 bị ghi hai lần, OL_1_045 rồi OL_1_046.  Hai
    lượt cùng đọc sổ và cây trước khi lượt nào kịp ghi, nên cả hai cùng thấy
    thẻ còn trống.
    """

    def _race(self, erp, calls):
        errors = []

        def run(call):
            try:
                call()
            except Exception as exc:  # pragma: no cover - để bài test in ra lỗi
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(call,)) for call in calls]
        with patch("flow_web.service.log"), patch("flow_web.service.time.sleep"):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
        self.assertEqual([], errors)

    def _fill(self, svc, root):
        from flow_web.service import FlowWebService

        return lambda: FlowWebService.fill_task_skus(svc, root)

    def test_two_passes_over_one_cluster_write_the_card_once(self):
        root = "TASK-2026-05384"
        with tempfile.TemporaryDirectory() as tmp:
            erp = _ErpMemory(
                {
                    root: [
                        (root, "", "product: bờm"),
                        ("TASK-2026-05400", root, "sku: BT_1_044\n"),
                        ("TASK-2026-05463", root, ""),
                    ]
                },
                ledger_dir=tmp,
            )
            svc = erp.service()
            self._race(erp, [self._fill(svc, root), self._fill(svc, root)])

        self.assertEqual(1, erp.writes["TASK-2026-05463"])
        self.assertEqual("BT_1_045", erp.sku("TASK-2026-05463"))

    def test_two_clusters_of_one_product_never_share_a_code(self):
        # Số idea đếm xuyên mọi cụm qua một quyển sổ.  Hai lượt cùng đọc sổ
        # trống thì cả hai cùng cấp BT_1_001.
        with tempfile.TemporaryDirectory() as tmp:
            erp = _ErpMemory(
                {
                    "TASK-1": [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")],
                    "TASK-5": [("TASK-5", "", "product: bờm"), ("TASK-6", "TASK-5", "")],
                },
                ledger_dir=tmp,
            )
            svc = erp.service()
            self._race(erp, [self._fill(svc, "TASK-1"), self._fill(svc, "TASK-5")])

        self.assertEqual({"BT_1_001", "BT_1_002"}, {erp.sku("TASK-2"), erp.sku("TASK-6")})

    def test_a_long_pass_hands_off_without_giving_away_its_next_code(self):
        """Làn nhanh chen giữa hai thẻ vẫn không lấy mã lượt nền đã tính."""
        from flow_web.service import FlowWebService

        errors = []
        with tempfile.TemporaryDirectory() as tmp:
            erp = _ErpMemory(
                {
                    "TASK-1": [
                        ("TASK-1", "", "product: bờm"),
                        ("TASK-2", "TASK-1", ""),
                        ("TASK-3", "TASK-1", ""),
                    ],
                    "TASK-5": [("TASK-5", "", "product: bờm"), ("TASK-6", "TASK-5", "")],
                },
                ledger_dir=tmp,
            )
            svc = erp.service()
            fast_done = threading.Event()

            def fast_lane() -> None:
                try:
                    with sku_pass(wait=True, timeout=1.0, priority=True) as got:
                        self.assertTrue(got)
                        FlowWebService.fill_task_skus(svc, "TASK-5")
                except Exception as exc:  # pragma: no cover - để bài test in ra lỗi
                    errors.append(exc)
                finally:
                    fast_done.set()

            fast = threading.Thread(target=fast_lane)
            original_write = erp.write_meta

            def write_then_handoff(key, token, task_id, block):
                original_write(key, token, task_id, block)
                if task_id == "TASK-2" and not fast.is_alive() and not fast_done.is_set():
                    fast.start()
                    for _ in range(100):
                        if sku_pass_priority_waiting():
                            break
                        threading.Event().wait(0.01)

            svc._erp_update_task_meta = write_then_handoff
            try:
                FlowWebService.fill_task_skus(svc, "TASK-1")
            except Exception as exc:  # pragma: no cover - để bài test in ra lỗi
                errors.append(exc)
            fast.join(5)

        self.assertEqual([], errors)
        self.assertFalse(fast.is_alive())
        self.assertEqual(
            {"BT_1_001", "BT_1_002", "BT_1_003"},
            {erp.sku("TASK-2"), erp.sku("TASK-3"), erp.sku("TASK-6")},
        )

    def test_a_pass_holds_the_shared_lock_while_it_works(self):
        from flow_web.service import FlowWebService

        seen = []

        def probe():
            with sku_pass(wait=False) as got:
                seen.append(got)

        with tempfile.TemporaryDirectory() as tmp:
            erp = _ErpMemory(
                {"TASK-1": [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")]},
                ledger_dir=tmp,
            )
            svc = erp.service()

            def tree(key, token, root):
                other = threading.Thread(target=probe)
                other.start()
                other.join(5)
                return erp.payload(root)

            svc._erp_task_full = tree
            with patch("flow_web.service.log"), patch("flow_web.service.time.sleep"):
                FlowWebService.fill_task_skus(svc, "TASK-1", dry_run=True)

        self.assertEqual([False], seen)


class TopDownFillTests(unittest.TestCase):
    """Lượt ghi thật đánh số theo chỗ thẻ đứng trong cột, từ trên xuống.

    ``taskFull`` xếp thẻ con theo số task, không theo chỗ đứng, nên lượt ghi
    phải đọc thêm ``taskBoard`` — một request, và chỉ khi có từ hai mã mới.
    """

    _run = FillLedgerTests._run
    _payload = staticmethod(FillLedgerTests._payload)

    NODES = [
        ("TASK-1", "", "product: bờm"),
        ("TASK-2", "TASK-1", ""),
        ("TASK-3", "TASK-1", ""),
        ("TASK-4", "TASK-1", ""),
    ]

    def _codes(self):
        return {name: task_meta({"meta": meta}).sku for name, meta in self.metas.items() if name != "TASK-1"}

    def test_the_top_card_gets_the_smallest_number(self):
        self._run(self.NODES, board=_board_of(["TASK-4", "TASK-2", "TASK-3"]))

        self.assertEqual({"TASK-4": "BT_1_001", "TASK-2": "BT_1_002", "TASK-3": "BT_1_003"}, self._codes())
        self.assertEqual(1, self.board_reads)

    def test_a_single_new_code_does_not_read_the_board(self):
        self._run([("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "sku: BT_1_001\n"), ("TASK-3", "TASK-1", "")])

        self.assertEqual("BT_1_002", self._codes()["TASK-3"])
        self.assertEqual(0, self.board_reads)

    def test_a_board_that_will_not_load_stops_the_pass_before_any_write(self):
        # Đánh theo thứ tự sai thì mã đã in ra ngoài không đổi lại được; lượt
        # dừng thì chạy lại được.
        before = {name: meta for name, _, meta in self.NODES}
        with self.assertRaises(RuntimeError):
            self._run(self.NODES, board_broken=True)

        self.assertEqual(before, self.metas)

    def test_four_passes_over_one_cluster_write_each_card_once_top_down(self):
        with tempfile.TemporaryDirectory() as tmp:
            erp = _ErpMemory({"TASK-1": self.NODES}, ledger_dir=tmp, board=["TASK-4", "TASK-2", "TASK-3"])
            svc = erp.service()
            ConcurrentFillTests._race(self, erp, [ConcurrentFillTests._fill(self, svc, "TASK-1") for _ in range(4)])

        self.assertEqual({"TASK-2": 1, "TASK-3": 1, "TASK-4": 1}, dict(erp.writes))
        self.assertEqual(
            ["BT_1_001", "BT_1_002", "BT_1_003"],
            [erp.sku(name) for name in ("TASK-4", "TASK-2", "TASK-3")],
        )

    def test_four_passes_over_two_clusters_number_each_top_down_without_a_clash(self):
        clusters = {
            "TASK-1": [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", ""), ("TASK-3", "TASK-1", "")],
            "TASK-5": [("TASK-5", "", "product: bờm"), ("TASK-6", "TASK-5", ""), ("TASK-7", "TASK-5", "")],
        }
        with tempfile.TemporaryDirectory() as tmp:
            erp = _ErpMemory(clusters, ledger_dir=tmp, board=["TASK-7", "TASK-3", "TASK-6", "TASK-2"])
            svc = erp.service()
            fill = ConcurrentFillTests._fill
            ConcurrentFillTests._race(
                self,
                erp,
                [fill(self, svc, "TASK-1"), fill(self, svc, "TASK-5"), fill(self, svc, "TASK-1"), fill(self, svc, "TASK-5")],
            )

        codes = {name: erp.sku(name) for name in ("TASK-2", "TASK-3", "TASK-6", "TASK-7")}
        self.assertEqual({"BT_1_001", "BT_1_002", "BT_1_003", "BT_1_004"}, set(codes.values()))
        self.assertLess(codes["TASK-3"], codes["TASK-2"])
        self.assertLess(codes["TASK-7"], codes["TASK-6"])
        self.assertEqual(4, sum(erp.writes.values()))


class SkuPassTests(unittest.TestCase):
    """Khoá chung của mọi đường đánh số."""

    @staticmethod
    def _try_from_another_thread():
        seen = []

        def attempt():
            with sku_pass(wait=False) as got:
                seen.append(got)

        other = threading.Thread(target=attempt)
        other.start()
        other.join(5)
        return seen

    def test_the_same_thread_can_go_back_in(self):
        # ``sync_erp_skus`` → ``fill_task_skus`` → làn nhanh: một luồng có thể
        # đi qua hai lớp khoá.  Tự chặn chính mình là treo cả bot.
        with sku_pass() as outer:
            with sku_pass() as inner:
                self.assertTrue(outer and inner)

    def test_another_thread_that_will_not_wait_is_turned_away(self):
        with sku_pass():
            self.assertEqual([False], self._try_from_another_thread())
        self.assertEqual([True], self._try_from_another_thread())


# ── Làn nhanh ──────────────────────────────────────────────────────────────


LANE_BOT = "agent-kin-test-agent@bots.hvg.internal"


def board_row(name, *, parent="", status="Open", sku="", agents=(), modified="2026-09-11 16:00:00"):
    """Một dòng ``taskBoard``, đúng những khoá làn nhanh đọc."""
    return {
        "name": name,
        "parent_task": parent,
        "status": status,
        "custom_sku": sku,
        "agents": [{"bot_user": item, "code": "kin"} for item in agents],
        "modified": modified,
    }


class HotClusterTests(unittest.TestCase):
    """Đọc bảng ra những cụm đang chờ máy đánh số."""

    def test_a_child_in_doing_under_the_bots_card_is_hot(self):
        rows = [
            board_row("R", status="Working", agents=[LANE_BOT]),
            board_row("C1", parent="R", status="Working"),
        ]

        self.assertEqual({"R": ["C1"]}, hot_clusters(rows, LANE_BOT))

    def test_the_bot_on_the_child_itself_counts(self):
        rows = [
            board_row("R", status="Working"),
            board_row("C1", parent="R", status="Working", agents=[LANE_BOT]),
        ]

        self.assertEqual({"R": ["C1"]}, hot_clusters(rows, LANE_BOT))

    def test_a_grandchild_reports_to_the_top_card(self):
        rows = [
            board_row("R", status="Working", agents=[LANE_BOT]),
            board_row("M", parent="R", status="Open"),
            board_row("L", parent="M", status="Working"),
        ]

        self.assertEqual({"R": ["L"]}, hot_clusters(rows, LANE_BOT))

    def test_cards_the_lane_must_not_touch(self):
        rows = [
            board_row("R", status="Working", agents=[LANE_BOT]),
            board_row("C1", parent="R", status="Working", sku="OL_1_049"),
            board_row("C2", parent="R", status="Open"),
            board_row("C3", parent="R", status="Cancelled"),
            board_row("C4", parent="R", status="Pending Review"),
            board_row("S", status="Working"),
            board_row("S1", parent="S", status="Working"),
        ]

        self.assertEqual({}, hot_clusters(rows, LANE_BOT))

    def test_a_loop_in_the_parent_links_does_not_hang(self):
        rows = [
            board_row("A", parent="B", status="Working", agents=[LANE_BOT]),
            board_row("B", parent="A", status="Working", agents=[LANE_BOT]),
        ]

        self.assertIsInstance(hot_clusters(rows, LANE_BOT), dict)

    def test_a_board_with_a_card_still_in_todo_stays_hot(self):
        # Thẻ còn ở *Cần làm* là thẻ sắp được kéo sang: bảng ấy phải được đọc
        # lại theo nhịp nhanh, không phải năm phút một lần.
        rows = [
            board_row("R", status="Working", agents=[LANE_BOT]),
            board_row("C1", parent="R", status="Open"),
        ]
        self.assertTrue(board_is_hot(rows, LANE_BOT))

        rows[1]["custom_sku"] = "OL_1_049"
        self.assertFalse(board_is_hot(rows, LANE_BOT))


class _LaneWorld:
    """Bảng, đồng hồ và lượt đánh số giả, ghi lại từng request đã tiêu."""

    def __init__(self, boards, *, fill_result=None):
        self.boards = boards
        self.now = 1000.0
        self.spent = []
        self.filled = []
        self.fill_result = fill_result or self._number
        self.fail_board = None
        self._lock = threading.Lock()

    def clock(self):
        return self.now

    def board(self, project):
        with self._lock:
            self.spent.append((self.now, 1, "board:" + project))
        if self.fail_board is not None:
            raise self.fail_board
        return [dict(row) for row in self.boards[project]]

    def fill(self, root):
        with self._lock:
            self.filled.append(root)
            self.spent.append((self.now, fill_cost(1), "fill:" + root))
        return self.fill_result(root)

    def _number(self, root):
        """Lượt đánh số thật: thẻ con đang ở *Đang làm* nhận mã."""
        written = []
        for rows in self.boards.values():
            for row in rows:
                if row["parent_task"] == root and row["status"] == "Working" and not row["custom_sku"]:
                    row["custom_sku"] = "BT_1_%03d" % (len(self.filled))
                    written.append({"task_id": row["name"], "sku": row["custom_sku"]})
        return {"written": written, "failed": []}

    def lane(self, config=None, **overrides):
        options = {
            "projects": lambda: list(self.boards),
            "board": self.board,
            "bot_user": LANE_BOT,
            "fill": self.fill,
            "clock": self.clock,
        }
        options.update(overrides)
        return SkuFastLane(config or SkuFastLaneConfig(enabled=True), **options)

    def beat(self, lane, seconds=15.0):
        self.now += seconds
        return lane.tick()

    def reads(self):
        return [what for _, _, what in self.spent if what.startswith("board:")]

    def worst_minute(self):
        """Số request lớn nhất rơi vào một cửa sổ 60 s bất kỳ."""
        return max(
            (sum(cost for when, cost, _ in self.spent if end - 60 < when <= end) for end, _, _ in self.spent),
            default=0,
        )


def _cluster(root, *children, board_status="Working"):
    rows = [board_row(root, status=board_status, agents=[LANE_BOT])]
    for name, status in children:
        rows.append(board_row(name, parent=root, status=status))
    return rows


class SkuFastLaneTests(unittest.TestCase):
    """Kéo thẻ sang *Đang làm* thì thẻ có mã trong 30 giây."""

    def test_a_card_dragged_into_doing_gets_its_code_within_30_seconds(self):
        world = _LaneWorld({"PROJ-0087": _cluster("R", ("C1", "Open"))})
        lane = world.lane()
        lane.tick()
        self.assertEqual([], world.filled)

        world.boards["PROJ-0087"][1]["status"] = "Working"
        dragged = world.now
        while not world.filled and world.now - dragged < 60:
            world.beat(lane)

        self.assertEqual(["R"], world.filled)
        self.assertLessEqual(world.now - dragged, 30)

    def test_coded_cards_and_cards_without_the_bot_are_left_alone(self):
        rows = _cluster("R", ("C1", "Working"))
        rows[1]["custom_sku"] = "OL_1_049"
        rows += [board_row("S", status="Working"), board_row("S1", parent="S", status="Working")]
        world = _LaneWorld({"PROJ-0087": rows})
        lane = world.lane()

        lane.tick()
        for _ in range(4):
            world.beat(lane)

        self.assertEqual([], world.filled)

    def test_one_cluster_per_beat(self):
        # Mỗi lượt đánh số tốn vài request mỗi thẻ; gom hai cụm vào một nhịp là
        # một nhịp vượt trần.
        world = _LaneWorld({"PROJ-0087": _cluster("R1", ("C1", "Working")) + _cluster("R2", ("C2", "Working"))})
        lane = world.lane()

        lane.tick()
        self.assertEqual(1, len(world.filled))

        world.beat(lane)
        self.assertEqual(["R1", "R2"], sorted(world.filled))

    def test_the_cluster_whose_card_sits_higher_goes_first(self):
        # Giữa hai cụm, cụm có thẻ chờ nằm cao hơn trong cột *Đang làm* được
        # đánh số trước.  Dòng ``taskBoard`` giữ đúng thứ tự trên màn hình.
        rows = [
            board_row("R1", status="Working", agents=[LANE_BOT]),
            board_row("R2", status="Working", agents=[LANE_BOT]),
            board_row("C2", parent="R2", status="Working"),
            board_row("C1", parent="R1", status="Working"),
        ]
        world = _LaneWorld({"PROJ-0087": rows})
        lane = world.lane()

        lane.tick()
        self.assertEqual(["R2"], world.filled)
        world.beat(lane)
        self.assertEqual(["R2", "R1"], world.filled)

    def test_a_pass_over_two_cards_pays_for_the_board_read(self):
        # Lượt đánh số đọc bảng để xếp mã từ trên xuống.  Không tính vào thì
        # trần 20 request/phút chỉ đúng trên giấy.  Lần đọc ấy nay nằm trong
        # phần nền cho mọi n (bảng đọc cả để lọc thẻ bị cắt), nên thẻ thứ hai
        # chỉ thêm năm request của chính nó.
        self.assertEqual(fill_cost(1) + 5, fill_cost(2))
        self.assertEqual(13, fill_cost(2))
        # Luật mới không ước hụt so với luật cũ ở cụm sạch.
        for n in range(11):
            with self.subTest(n=n):
                self.assertGreaterEqual(
                    fill_cost(n, cut_new=0, wrong=0), 2 + 5 * n + (1 if n >= 2 else 0)
                )

    def test_the_first_pass_over_29_boards_stays_under_the_ceiling(self):
        boards = {"PROJ-%04d" % number: _cluster("R%d" % number, ("C%d" % number, "Completed")) for number in range(29)}
        world = _LaneWorld(boards)
        lane = world.lane()

        lane.tick()
        while world.now < 1000.0 + 180:
            world.beat(lane)

        self.assertLessEqual(world.worst_minute(), SkuFastLaneConfig().budget_per_minute)
        # Trần giữ được mà vẫn phải nhìn tới đủ 29 bảng, không bỏ đói bảng nào.
        self.assertEqual(set(boards), {what.split(":", 1)[1] for what in world.reads()})

    def test_the_ceiling_holds_for_ten_minutes_of_busy_boards(self):
        boards = {"PROJ-%04d" % number: _cluster("R%d" % number, ("C%d" % number, "Completed")) for number in range(27)}
        # Hai cụm không bao giờ nguội: lượt đánh số "ghi được" mà bảng không
        # đổi.  Làn nhanh sẽ gõ chúng mãi — trần phải chặn được chuyện đó.
        boards["PROJ-0087"] = _cluster("HOT1", ("H1", "Working"))
        boards["PROJ-0170"] = _cluster("HOT2", ("H2", "Working"))
        world = _LaneWorld(boards, fill_result=lambda root: {"written": [{"task_id": root}], "failed": []})
        lane = world.lane()

        lane.tick()
        while world.now < 1000.0 + 600:
            world.beat(lane)

        self.assertGreater(len(world.filled), 0)
        self.assertLessEqual(world.worst_minute(), SkuFastLaneConfig().budget_per_minute)

    def test_four_workers_read_boards_side_by_side(self):
        # Đặt thẳng ``workers=4``, đừng mượn mặc định: bài này đo chuyện đọc
        # song song, còn mặc định là con số vận hành (nay là 2, hạ để bớt
        # ``QueryDeadlockError``).  Hai thứ đó đổi vì lý do khác nhau.
        barrier = threading.Barrier(4, timeout=2)
        broken = []
        boards = {"PROJ-%d" % number: _cluster("R%d" % number, ("C%d" % number, "Completed")) for number in range(4)}
        world = _LaneWorld(boards)

        def board(project):
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                broken.append(project)
            return world.board(project)

        world.lane(SkuFastLaneConfig(enabled=True, workers=4), board=board).tick()

        self.assertEqual([], broken)
        self.assertEqual(4, len(world.reads()))

    def test_the_shared_budget_never_hands_out_more_than_its_ceiling(self):
        budget = RequestBudget(20, clock=lambda: 0.0)
        granted = collections.Counter()

        def grab(worker):
            for _ in range(50):
                if budget.take():
                    granted[worker] += 1

        workers = [threading.Thread(target=grab, args=(index,)) for index in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(5)

        self.assertEqual(20, sum(granted.values()))

    def test_the_budget_frees_up_a_minute_later(self):
        now = [0.0]
        budget = RequestBudget(3, clock=lambda: now[0])
        self.assertTrue(budget.take(3))
        self.assertFalse(budget.take())
        now[0] = 59.9
        self.assertFalse(budget.take())
        now[0] = 60.0
        self.assertTrue(budget.take())

    def test_a_take_that_would_eat_the_reserve_is_refused(self):
        budget = RequestBudget(10, clock=lambda: 0.0)
        self.assertTrue(budget.take(2, keep=8))
        self.assertFalse(budget.take(1, keep=8))
        self.assertTrue(budget.take(8))

    def test_a_429_rests_the_lane_a_full_minute(self):
        world = _LaneWorld({"PROJ-0087": _cluster("R", ("C1", "Open"))})
        lane = world.lane()
        world.fail_board = RuntimeError("ERP đang giới hạn tốc độ token bot (HTTP 429).")
        lane.tick()
        world.fail_board = None
        before = len(world.reads())

        for _ in range(3):
            self.assertTrue(world.beat(lane).get("resting"))
        self.assertEqual(before, len(world.reads()))

        world.beat(lane)
        self.assertGreater(len(world.reads()), before)

    def test_a_429_inside_the_fill_rests_the_lane(self):
        failed = {"task_id": "C1", "sku": "BT_1_001", "error": "ERP đang giới hạn request (HTTP 429)."}
        world = _LaneWorld(
            {"PROJ-0087": _cluster("R", ("C1", "Working"))},
            fill_result=lambda root: {"written": [], "failed": [failed]},
        )
        lane = world.lane()

        lane.tick()

        self.assertEqual(["R"], world.filled)
        self.assertTrue(world.beat(lane).get("resting"))

    def test_a_busy_lock_skips_the_beat(self):
        world = _LaneWorld({"PROJ-0087": _cluster("R", ("C1", "Working"))})
        lane = world.lane(SkuFastLaneConfig(enabled=True, lock_wait_s=0.01))
        held, release = threading.Event(), threading.Event()

        def hold():
            with sku_pass():
                held.set()
                release.wait(5)

        holder = threading.Thread(target=hold)
        holder.start()
        held.wait(5)
        try:
            result = lane.tick()
        finally:
            release.set()
            holder.join(5)

        self.assertTrue(result.get("busy"))
        self.assertEqual([], world.filled)
        world.beat(lane)
        self.assertEqual(["R"], world.filled)

    def test_skip_log_only_repeats_when_its_reason_changes(self):
        world = _LaneWorld({"PROJ-0087": _cluster("R", ("C1", "Working"))})
        lane = world.lane(SkuFastLaneConfig(enabled=True, lock_wait_s=0.01))
        held, release = threading.Event(), threading.Event()

        def hold():
            with sku_pass():
                held.set()
                release.wait(5)

        holder = threading.Thread(target=hold)
        holder.start()
        held.wait(5)
        try:
            with patch("flow_web.sku.log") as logger:
                self.assertTrue(lane.tick().get("busy"))
                self.assertTrue(lane.tick().get("busy"))
            lines = [str(call) for call in logger.info.call_args_list]
        finally:
            release.set()
            holder.join(5)

        self.assertEqual(1, len(lines), lines)
        self.assertIn("khoá lượt đánh số đang bận", lines[0])

    def test_skip_log_names_stuck_too_big_and_budget(self):
        cases = []

        stuck_world = _LaneWorld(
            {"PROJ-0087": _cluster("R", ("C1", "Working"))},
            fill_result=lambda root: {"written": [], "failed": []},
        )
        with patch("flow_web.sku.log") as logger:
            stuck_world.lane().tick()
        cases.extend(str(call) for call in logger.info.call_args_list)

        big_world = _LaneWorld({"PROJ-0087": _cluster("R", ("C1", "Working"))})
        big_lane = big_world.lane(SkuFastLaneConfig(enabled=True, budget_per_minute=5))
        big_lane._rows["PROJ-0087"] = big_world.board("PROJ-0087")
        with patch("flow_web.sku.log") as logger:
            big_lane._fill_one(big_world.now, LANE_BOT)
        cases.extend(str(call) for call in logger.info.call_args_list)

        waiting_world = _LaneWorld({"PROJ-0087": _cluster("R", ("C1", "Working"))})
        waiting_lane = waiting_world.lane()
        waiting_lane._rows["PROJ-0087"] = waiting_world.board("PROJ-0087")
        self.assertTrue(waiting_lane.budget.take(waiting_lane.budget.limit))
        with patch("flow_web.sku.log") as logger:
            self.assertTrue(waiting_lane._fill_one(waiting_world.now, LANE_BOT).get("waiting"))
        cases.extend(str(call) for call in logger.info.call_args_list)

        combined = "\n".join(cases)
        self.assertIn("cụm chưa ghi được", combined)
        self.assertIn("cụm quá lớn", combined)
        self.assertIn("chờ ngân sách request", combined)

    def test_a_priority_waiter_gets_the_next_safe_handoff(self):
        """Lượt nền nhường ngay sau thẻ đang làm, không nhả hàng rào SKU."""
        held, waiting = threading.Event(), threading.Event()
        order = []

        def background():
            with sku_pass():
                held.set()
                waiting.wait(5)
                for _ in range(100):
                    if sku_pass_priority_waiting():
                        break
                    threading.Event().wait(0.01)
                self.assertTrue(sku_pass_yield_to_priority())
                order.append("nen")

        def fast_lane():
            held.wait(5)
            waiting.set()
            with sku_pass(wait=True, timeout=1.0, priority=True) as got:
                self.assertTrue(got)
                order.append("nhanh")

        slow = threading.Thread(target=background)
        fast = threading.Thread(target=fast_lane)
        slow.start()
        fast.start()
        slow.join(5)
        fast.join(5)

        self.assertFalse(slow.is_alive())
        self.assertFalse(fast.is_alive())
        self.assertEqual(["nhanh", "nen"], order)

    def test_a_cold_board_is_looked_at_again_after_five_minutes(self):
        world = _LaneWorld({"PROJ-0087": _cluster("R", ("C1", "Completed"))})
        lane = world.lane()
        lane.tick()

        for _ in range(19):
            world.beat(lane)
        self.assertEqual(1, len(world.reads()))

        world.beat(lane)
        self.assertEqual(2, len(world.reads()))

    def test_a_stuck_cluster_waits_for_its_rows_to_change(self):
        # Lượt đánh số không ghi được gì — bảng SKU thiếu dòng, thẻ gốc chưa
        # khai ``product``.  Gõ lại mỗi 15 giây thì chỉ ăn hạn mức.
        world = _LaneWorld(
            {"PROJ-0087": _cluster("R", ("C1", "Working"))},
            fill_result=lambda root: {"written": [], "failed": []},
        )
        lane = world.lane()
        lane.tick()
        for _ in range(3):
            world.beat(lane)
        self.assertEqual(["R"], world.filled)

        world.boards["PROJ-0087"][1]["modified"] = "2026-09-11 16:05:00"
        world.beat(lane)
        self.assertEqual(["R", "R"], world.filled)

    def test_a_paused_card_is_left_alone(self):
        for paused in ("R", "C1"):
            world = _LaneWorld({"PROJ-0087": _cluster("R", ("C1", "Working"))})
            lane = world.lane(paused=lambda task, paused=paused: task == paused)
            lane.tick()
            world.beat(lane)
            self.assertEqual([], world.filled, paused)

    def test_an_idea_card_waiting_on_votes_is_left_to_the_slow_path(self):
        asked = []
        world = _LaneWorld({"PROJ-0087": _cluster("R", ("C1", "Working"))})

        def tree(root):
            world.spent.append((world.now, 1, "tree:" + root))
            return {"root": {"name": root}}

        def is_due(payload, ids):
            asked.append(list(ids))
            return False

        world.lane(tree=tree, is_due=is_due).tick()

        self.assertEqual([["C1"]], asked)
        self.assertEqual([], world.filled)

    def test_the_lane_never_runs_unless_switched_on(self):
        world = _LaneWorld({"PROJ-0087": _cluster("R", ("C1", "Working"))})
        lane = world.lane(config=SkuFastLaneConfig())

        asyncio.run(asyncio.wait_for(lane.run_forever(), 1))

        self.assertEqual([], world.spent)

    def test_the_lane_and_a_direct_fill_never_hand_out_one_code_twice(self):
        from flow_web.service import FlowWebService

        with tempfile.TemporaryDirectory() as tmp:
            erp = _ErpMemory(
                {
                    "TASK-1": [("TASK-1", "", "product: bờm"), ("TASK-2", "TASK-1", "")],
                    "TASK-5": [("TASK-5", "", "product: bờm"), ("TASK-6", "TASK-5", "")],
                },
                ledger_dir=tmp,
            )
            svc = erp.service()
            rows = [
                board_row("TASK-1", status="Working", agents=[LANE_BOT]),
                board_row("TASK-2", parent="TASK-1", status="Working"),
            ]
            lane = SkuFastLane(
                SkuFastLaneConfig(enabled=True),
                projects=lambda: ["PROJ-0170"],
                board=lambda project: [dict(row) for row in rows],
                bot_user=LANE_BOT,
                fill=lambda root: FlowWebService.fill_task_skus(svc, root),
                clock=lambda: 1000.0,
            )
            ConcurrentFillTests._race(
                self, erp, [lane.tick, lambda: FlowWebService.fill_task_skus(svc, "TASK-5")]
            )
            if not erp.sku("TASK-2"):
                # Làn nhanh gặp khoá bận thì bỏ nhịp; nhịp sau làm nốt.
                with patch("flow_web.service.log"), patch("flow_web.service.time.sleep"):
                    lane.tick()

        self.assertEqual({"BT_1_001", "BT_1_002"}, {erp.sku("TASK-2"), erp.sku("TASK-6")})


class SkuFastLaneConfigTests(unittest.TestCase):
    def test_the_lane_is_off_unless_asked(self):
        # Hai máy dùng chung token bot nhưng mỗi máy một sổ SKU: bật mặc định
        # là hai máy cùng đánh số một cụm từ hai quyển sổ.
        config = SkuFastLaneConfig.from_env({})

        self.assertFalse(config.enabled)
        # ``workers`` là 2, không phải 4: đo trên ERP thật 13/09/2026, cùng nhịp
        # đọc 216 request/phút thì 4 luồng ra 3,8 lỗi ``QueryDeadlockError`` mỗi
        # phút còn 2 luồng ra 2,1.
        self.assertEqual((15, 20, 60, 300, 2), (
            config.interval_s, config.budget_per_minute, config.rest_s, config.rediscover_s, config.workers,
        ))

    def test_numbers_from_the_environment_are_kept_in_bounds(self):
        config = SkuFastLaneConfig.from_env(
            {
                "ERP_SKU_FAST_LANE": "1",
                "ERP_SKU_FAST_LANE_WORKERS": "20",
                "ERP_SKU_FAST_LANE_REST": "5",
                "ERP_SKU_FAST_LANE_BUDGET": "3",
                "ERP_SKU_FAST_LANE_SECONDS": "x",
            }
        )

        self.assertTrue(config.enabled)
        self.assertEqual(8, config.workers)
        self.assertEqual(60, config.rest_s)
        # Dưới mức này thì không đủ một lượt đọc bảng cộng một lượt đánh số.
        self.assertGreaterEqual(config.budget_per_minute, 1 + fill_cost(1) + 1)
        self.assertEqual(15, config.interval_s)
