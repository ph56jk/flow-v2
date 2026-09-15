from __future__ import annotations

import unittest

from flow_web.account_book import Account, AccountBook


class FromMappingTests(unittest.TestCase):
    def test_a_full_row_is_read(self):
        book = AccountBook.from_mapping(
            {"acc32": {"shop": "Havi Home", "machine": "etsy-vn32", "note": "shop chính"}}
        )

        found = book.lookup("acc32")
        self.assertEqual("Havi Home", found.shop)
        self.assertEqual("etsy-vn32", found.machine)
        self.assertEqual("shop chính", found.note)

    def test_a_bare_string_is_read_as_the_machine(self):
        # Người ta gõ nhanh nhất khi tất cả những gì họ biết là "acc này chạy
        # ở máy kia".
        book = AccountBook.from_mapping({"acc16": "etsy-16"})

        self.assertEqual("etsy-16", book.machine_for("acc16"))
        self.assertEqual("", book.lookup("acc16").shop)

    def test_the_two_shapes_live_in_one_book(self):
        book = AccountBook.from_mapping(
            {"acc32": {"shop": "Havi Home"}, "acc16": "etsy-16"}
        )

        self.assertEqual(2, len(book))

    def test_the_column_names_are_the_operators_not_the_codes(self):
        book = AccountBook.from_mapping(
            {"acc32": {"Tên shop": "Havi Home", "Máy chạy": "etsy-vn32", "Ghi chú": "x"}}
        )

        found = book.lookup("acc32")
        self.assertEqual("Havi Home", found.shop)
        self.assertEqual("etsy-vn32", found.machine)
        self.assertEqual("x", found.note)

    def test_a_row_with_no_account_is_dropped(self):
        self.assertEqual(0, len(AccountBook.from_mapping({"  ": {"shop": "Havi Home"}})))

    def test_nothing_in_an_empty_book_out(self):
        self.assertEqual(0, len(AccountBook.from_mapping(None)))
        self.assertFalse(AccountBook.from_mapping({}))


class FromRowsTests(unittest.TestCase):
    def test_a_sheet_row_becomes_an_entry(self):
        book = AccountBook.from_rows(
            [
                {
                    "Tài khoản": "havi-home",
                    "Tên shop": "Havi Home",
                    "Máy chạy": "capa-hinh",
                    "Ghi chú": "shop chính",
                }
            ]
        )

        found = book.lookup("havi-home")
        self.assertEqual("Havi Home", found.shop)
        self.assertEqual("capa-hinh", found.machine)
        self.assertEqual("shop chính", found.note)

    def test_an_account_that_breaks_the_naming_convention_is_still_a_row(self):
        # Cả lý do quyển sổ tồn tại: ``machine_for_account`` đoán được "acc32"
        # vì có số 32 trong tên, và đoán trượt mọi cái tên khác.
        book = AccountBook.from_rows([{"acc": "havi-home", "may": "capa-hinh"}])

        self.assertEqual("capa-hinh", book.machine_for("havi-home"))

    def test_a_row_with_no_account_column_is_skipped(self):
        book = AccountBook.from_rows([{"Tên shop": "Havi Home", "Máy": "etsy-1"}])

        self.assertEqual(0, len(book))

    def test_junk_between_the_rows_does_not_stop_the_read(self):
        # Sheet do người gõ; một ô lạc loài không được làm hỏng cả quyển sổ.
        book = AccountBook.from_rows([None, "acc32", {"acc": "acc32", "may": "etsy-32"}])

        self.assertEqual(1, len(book))

    def test_the_last_row_of_a_repeated_account_wins(self):
        book = AccountBook.from_rows(
            [{"acc": "acc32", "may": "cu"}, {"acc": "acc32", "may": "moi"}]
        )

        self.assertEqual("moi", book.machine_for("acc32"))


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.book = AccountBook.from_mapping(
            {"acc32": {"shop": "Havi Home", "machine": "etsy-vn32"}}
        )

    def test_the_way_it_is_typed_on_the_card_does_not_matter(self):
        # Nhãn trên thẻ do người dán, khối Thuộc tính do người gõ; hai chỗ ấy
        # không bao giờ khớp nhau từng ký tự.
        for typed in ("acc32", "ACC32", " Acc32 "):
            self.assertTrue(self.book.knows(typed), typed)

    def test_a_space_inside_the_id_makes_it_a_different_account(self):
        # ``acc 32`` chuẩn hoá thành ``acc-32`` — cùng một luật slug với mã máy
        # và với mọi chỗ khác trong app.  Sổ tay không được tự nới luật ấy ra
        # riêng cho mình, nếu không thì cùng cái nhãn sẽ tra ra hai kết quả
        # khác nhau tuỳ đường đi.
        self.assertFalse(self.book.knows("acc 32"))

    def test_an_account_the_book_never_heard_of(self):
        self.assertIsNone(self.book.lookup("acc99"))
        self.assertFalse(self.book.knows("acc99"))
        self.assertEqual("", self.book.machine_for("acc99"))

    def test_asking_for_nothing_finds_nothing(self):
        self.assertIsNone(self.book.lookup(""))
        self.assertIsNone(self.book.lookup(None))

    def test_the_ids_feed_the_label_reader(self):
        self.assertEqual(("acc32",), self.book.account_ids)

    def test_the_routing_table_leaves_out_rows_with_no_machine(self):
        book = AccountBook.from_mapping({"acc32": "etsy-vn32", "acc16": {"shop": "B"}})

        self.assertEqual({"acc32": "etsy-vn32"}, book.account_machines)


class MergeTests(unittest.TestCase):
    def test_this_book_wins_over_that_one(self):
        # Thứ tự gộp trong ``service`` là env → đĩa → sheet, và cái người vận
        # hành vừa đặt tay phải đè lên cái đọc được từ xa.
        near = AccountBook.from_mapping({"acc32": "may-tay"})
        far = AccountBook.from_mapping({"acc32": "may-sheet", "acc16": "etsy-16"})

        merged = near.merged(far)

        self.assertEqual("may-tay", merged.machine_for("acc32"))
        self.assertEqual("etsy-16", merged.machine_for("acc16"))

    def test_merging_with_nothing_changes_nothing(self):
        book = AccountBook.from_mapping({"acc32": "etsy-vn32"})

        self.assertEqual(book, book.merged(None))

    def test_merging_does_not_touch_either_book(self):
        near = AccountBook.from_mapping({"acc32": "a"})
        far = AccountBook.from_mapping({"acc16": "b"})

        near.merged(far)

        self.assertEqual(1, len(near))
        self.assertEqual(1, len(far))


class AccountTests(unittest.TestCase):
    def test_the_label_names_the_shop_when_it_is_known(self):
        self.assertEqual("acc32 (Havi Home)", Account("acc32", shop="Havi Home").label)

    def test_the_label_falls_back_to_the_bare_id(self):
        self.assertEqual("acc32", Account("acc32").label)

    def test_a_row_round_trips_through_a_dict(self):
        # ``as_dict`` là thứ đi ra ``GET /api/erp/account/book`` và quay lại qua
        # ``PUT``; đi một vòng mà mất chữ thì màn hình cấu hình tự xoá sổ.
        book = AccountBook.from_mapping(
            {"acc32": {"shop": "Havi Home", "machine": "etsy-vn32", "note": "chính"}}
        )

        self.assertEqual(book, AccountBook.from_mapping(book.as_dict()))


if __name__ == "__main__":
    unittest.main()
