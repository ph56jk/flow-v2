from __future__ import annotations

import unittest

from flow_web.pipeline import (
    COL_CANCELLED,
    COL_DOING,
    COL_DONE,
    COL_REVIEW,
    COL_TODO,
    COLUMN_HINTS,
    CardStage,
    Move,
    column_help,
    column_name,
    decide,
    is_forward,
    needs_sku_fill,
    normalize_status,
    unknown_columns,
)


class NormalizeStatusTests(unittest.TestCase):
    def test_the_english_name_is_its_own_key(self):
        self.assertEqual(COL_REVIEW, normalize_status("Pending Review"))

    def test_the_vietnamese_column_name_resolves_too(self):
        # Người vận hành đọc tên cột trên bảng và gõ lại đúng chữ ấy.
        self.assertEqual(COL_DOING, normalize_status("Đang làm"))
        self.assertEqual(COL_REVIEW, normalize_status("Đang review"))
        self.assertEqual(COL_TODO, normalize_status("Cần làm"))

    def test_d_with_stroke_is_not_swallowed(self):
        # ``unicodedata`` không tách được ``đ``; thiếu bước thay tay thì
        # "Đang làm" nén thành "anglam" và không khớp gì cả.
        self.assertEqual(COL_CANCELLED, normalize_status("Đã huỷ"))

    def test_case_and_spacing_do_not_matter(self):
        self.assertEqual(COL_DONE, normalize_status("  completed "))

    def test_an_unknown_column_resolves_to_nothing(self):
        self.assertEqual("", normalize_status("Chờ khách duyệt"))

    def test_nothing_in_nothing_out(self):
        self.assertEqual("", normalize_status(None))

    def test_the_name_shown_to_people_is_vietnamese(self):
        self.assertEqual("Đang review", column_name("Pending Review"))

    def test_an_unknown_column_is_echoed_back_as_typed(self):
        self.assertEqual("Chờ khách", column_name("Chờ khách"))


class TodoColumnTests(unittest.TestCase):
    """*Cần làm* là nơi máy làm ảnh; chỉ người duyệt mới đẩy thẻ đi."""

    def test_a_card_with_no_images_stays(self):
        move = decide(CardStage(status=COL_TODO))
        self.assertFalse(move)
        self.assertIn("chưa có ảnh", move.reason)

    def test_posting_images_for_review_does_not_move_the_card(self):
        # Đây là cái luật cũ làm sai: đăng ảnh lên duyệt là đẩy thẻ sang
        # *Đang review* ngay, khiến cột ấy có nghĩa "chờ bấm 👍".
        move = decide(CardStage(status=COL_TODO, images_total=4, images_pending=4))
        self.assertFalse(move)
        self.assertIn("4 ảnh chờ", move.reason)

    def test_one_image_still_waiting_holds_the_whole_card(self):
        move = decide(
            CardStage(status=COL_TODO, images_total=4, images_pending=1, images_kept=3)
        )
        self.assertFalse(move)

    def test_a_finished_review_moves_the_card_to_doing(self):
        move = decide(
            CardStage(status=COL_TODO, images_total=4, images_pending=0, images_kept=3)
        )
        self.assertEqual(COL_DOING, move.status)
        self.assertIn("3 ảnh", move.reason)

    def test_dropping_every_image_leaves_the_card_where_it_is(self):
        # Không còn ảnh nào thì chẳng có gì để mang sang cột sau; thẻ ở lại để
        # chạy lại.
        move = decide(CardStage(status=COL_TODO, images_total=3, images_kept=0))
        self.assertFalse(move)
        self.assertIn("bỏ hết ảnh", move.reason)


class DoingColumnTests(unittest.TestCase):
    """*Đang làm* là nơi máy điền mã SKU."""

    #: Bộ ảnh đã chốt — điều kiện để thẻ có mặt ở cột này ngay từ đầu.
    SETTLED = dict(images_total=3, images_pending=0, images_kept=3)

    def test_a_card_without_a_code_waits(self):
        move = decide(CardStage(status=COL_DOING, **self.SETTLED))
        self.assertFalse(move)
        # Nguyên văn, vì đây là câu người vận hành đọc trên thẻ khi hỏi bot
        # "sao thẻ tôi đứng im" — đổi chữ là đổi câu trả lời của bot.
        self.assertEqual("chưa điền được mã SKU", move.reason)

    def test_a_coded_card_moves_even_while_siblings_are_missing_codes(self):
        """Canh đúng cái khoá chết vừa gỡ: ``cards_missing_sku > 0`` hết quyền chặn.

        Mã chỉ phát cho thẻ đã được kéo sang *Đang làm*, nên anh chị em còn
        nằm ở *Cần làm* sẽ không bao giờ có mã.  Luật cũ ("cả cụm đủ mã mới
        đi") vì thế là một cái khoá không ai mở được: thẻ đầu tiên kéo sang
        đứng đó vĩnh viễn, chờ những thẻ mà theo đúng thiết kế thì chưa tới
        lượt.  Nếu ai đó "thấy thiếu" mà thêm lại điều kiện cụm, bài này đỏ.
        """
        move = decide(
            CardStage(status=COL_DOING, has_sku=True, cards_missing_sku=2, **self.SETTLED)
        )
        self.assertEqual(COL_REVIEW, move.status)
        self.assertEqual("đã có mã SKU", move.reason)

    def test_a_card_with_its_own_code_moves_to_review(self):
        move = decide(CardStage(status=COL_DOING, has_sku=True, **self.SETTLED))
        self.assertEqual(COL_REVIEW, move.status)
        # Lý do nói về chính thẻ; "cả cụm đã có mã SKU" là câu của luật cũ.
        self.assertEqual("đã có mã SKU", move.reason)

    def test_a_card_dragged_in_by_hand_is_still_checked_for_votes(self):
        # Người ta kéo thẻ bằng tay bất cứ lúc nào, và thẻ cũ nằm sẵn ở cột này
        # từ trước khi có luật.  Cột không được tin cột trước đã làm xong việc
        # của nó — nếu không, một thẻ chưa ai xem ảnh sẽ nằm trên bàn của người
        # viết listing.
        move = decide(
            CardStage(status=COL_DOING, has_sku=True, images_total=11, images_pending=11)
        )
        self.assertFalse(move)
        self.assertIn("11 ảnh chờ", move.reason)

    def test_unsettled_images_still_hold_a_coded_card(self):
        # Gỡ điều kiện cụm không được kéo điều kiện ảnh lỏng theo: thẻ có mã
        # mà ảnh chưa ai chốt thì vẫn đứng lại, kể cả khi cụm còn thẻ trống mã
        # — hai điều kiện nằm ở hai câu hỏi khác nhau.
        move = decide(
            CardStage(
                status=COL_DOING,
                has_sku=True,
                cards_missing_sku=3,
                images_total=5,
                images_pending=2,
                images_kept=3,
            )
        )
        self.assertFalse(move)
        self.assertIn("2 ảnh chờ", move.reason)

    def test_a_card_whose_images_were_all_dropped_does_not_go_forward(self):
        move = decide(
            CardStage(status=COL_DOING, has_sku=True, images_total=3, images_kept=0)
        )
        self.assertFalse(move)
        self.assertIn("bỏ hết ảnh", move.reason)

    def test_a_card_with_no_images_at_all_does_not_go_forward(self):
        move = decide(CardStage(status=COL_DOING, has_sku=True))
        self.assertFalse(move)
        self.assertIn("chưa có ảnh", move.reason)


class ReviewColumnTests(unittest.TestCase):
    """*Đang review* là bàn làm việc của người viết listing."""

    def test_an_image_card_is_never_closed_by_the_machine(self):
        move = decide(CardStage(status=COL_REVIEW, has_sku=True))
        self.assertFalse(move)
        self.assertIn("người làm listing", move.reason)

    def test_a_listing_card_waits_until_the_post_is_up(self):
        # Thẻ này không có tấm ảnh nào của riêng nó — chuyện bình thường, ảnh
        # nằm ở thẻ sản phẩm khác trong cụm.  Ở cột này than "chưa có ảnh nào
        # để duyệt" là nói sai chỗ.
        move = decide(CardStage(status=COL_REVIEW, is_listing=True))
        self.assertFalse(move)
        self.assertIn("chờ listing", move.reason)

    def test_a_posted_listing_card_is_done(self):
        move = decide(CardStage(status=COL_REVIEW, is_listing=True, listing_done=True))
        self.assertEqual(COL_DONE, move.status)

    def test_a_card_that_slipped_in_with_unvoted_images_says_so(self):
        # Trước đây thẻ này bị báo "chờ người làm listing" — họ mở ra và không
        # có tấm nào đã duyệt để dùng.
        move = decide(
            CardStage(status=COL_REVIEW, has_sku=True, images_total=15, images_pending=15)
        )
        self.assertFalse(move)
        self.assertIn("15 ảnh chờ", move.reason)

    def test_a_card_whose_images_were_all_dropped_says_so(self):
        move = decide(
            CardStage(status=COL_REVIEW, is_listing=True, images_total=4, images_kept=0)
        )
        self.assertFalse(move)
        self.assertIn("bỏ hết ảnh", move.reason)

    def test_a_finished_listing_closes_even_if_nobody_ever_voted(self):
        # Bài đã lên shop thật rồi thì luật cột không có quyền giữ thẻ lại.
        move = decide(
            CardStage(
                status=COL_REVIEW,
                is_listing=True,
                listing_done=True,
                images_total=6,
                images_pending=6,
            )
        )
        self.assertEqual(COL_DONE, move.status)


class ClosedColumnTests(unittest.TestCase):
    def test_a_finished_card_is_left_alone(self):
        for status in (COL_DONE, COL_CANCELLED):
            move = decide(CardStage(status=status, images_total=3, images_kept=3))
            self.assertFalse(move, status)
            self.assertIn("đã đóng", move.reason)

    def test_an_unknown_column_stops_everything(self):
        # Cột lạ nghĩa là bảng này không phải bảng luật ở đây mô tả.
        move = decide(CardStage(status="Chờ khách duyệt", images_total=2, images_kept=2))
        self.assertFalse(move)
        self.assertIn("không nhận ra", move.reason)


class UnknownColumnTests(unittest.TestCase):
    """Bảng đặt tên cột lạ thì thẻ đứng im — chỗ này lo phần *nói ra* điều đó.

    Cái bẫy đắt nhất của tool không phải là bot làm sai, mà là bot không làm gì
    và không ai biết tại sao.  Hai hàm dưới đây tồn tại để biến sự im lặng ấy
    thành một câu đọc được.
    """

    def test_a_board_named_the_way_the_rules_expect_has_nothing_to_report(self):
        self.assertEqual((), unknown_columns(["Open", "Đang làm", "Pending Review"]))

    def test_a_stray_column_comes_back_word_for_word(self):
        # Nguyên văn, không nén: người đọc phải dò được đúng chữ ấy trên bảng.
        self.assertEqual(("Backlog",), unknown_columns(["Cần làm", "Backlog"]))

    def test_a_column_with_no_name_is_not_worth_complaining_about(self):
        # ERP thỉnh thoảng trả về một cột không tên; than phiền về nó chỉ khiến
        # người đọc đi tìm một thứ không có trên bảng.
        self.assertEqual((), unknown_columns(["", "   ", None, "Working"]))

    def test_the_same_stray_name_is_only_said_once(self):
        self.assertEqual(
            ("Backlog", "In Review"),
            unknown_columns(["Backlog", "Đang làm", "Backlog", "In Review"]),
        )

    def test_the_advice_names_the_column_the_reader_is_looking_at(self):
        loi = column_help(["Backlog"])
        self.assertIn("Backlog", loi)
        # Và nói thẳng rằng ảnh vẫn được tạo, để không ai tưởng bot đã chết.
        self.assertIn("ảnh vẫn được tạo", loi)

    def test_the_advice_still_stands_up_when_no_column_is_named(self):
        # Gọi trống thì câu vẫn phải đọc được, không được hở ra ", nên".
        loi = column_help()
        self.assertIn("của bảng này", loi)

    def test_every_alias_the_advice_offers_actually_works(self):
        """Lời khuyên sai còn tệ hơn không khuyên gì.

        Người vận hành sẽ đổi tên cột đúng theo chữ bot đọc cho họ; nếu một
        cách gọi trong bảng gợi ý không thật sự khớp luật thì họ đổi xong mà
        thẻ vẫn đứng im, và lần sau họ không tin bot nữa.
        """
        for label, aliases in COLUMN_HINTS:
            for alias in aliases.split("/"):
                with self.subTest(alias=alias):
                    self.assertTrue(normalize_status(alias))
            self.assertEqual(label, column_name(normalize_status(label)))


class NeedsSkuFillTests(unittest.TestCase):
    """Thẻ nào đang chờ *máy* điền mã — dùng để khỏi hỏi lại ERP vô ích."""

    SETTLED = dict(images_total=3, images_pending=0, images_kept=3)

    def test_a_settled_card_with_no_code_is_the_machines_turn(self):
        self.assertTrue(needs_sku_fill(CardStage(status=COL_DOING, **self.SETTLED)))

    def test_a_cluster_with_one_code_missing_is_still_the_machines_turn(self):
        # ``cards_missing_sku`` giờ chỉ đếm thẻ *đã tới lượt* mà trắng mã —
        # và còn một thẻ như thế nghĩa là máy còn một lượt đánh số phải gọi
        # cho cả cụm, dù chính thẻ này đã xong phần của nó.
        stage = CardStage(status=COL_DOING, has_sku=True, cards_missing_sku=1, **self.SETTLED)
        self.assertTrue(needs_sku_fill(stage))

    def test_moving_on_and_cluster_work_left_are_independent_questions(self):
        """``cards_missing_sku`` thôi làm điều kiện chuyển cột nhưng vẫn là cờ còn việc.

        Cùng một thẻ phải trả lời được cả hai câu: nó đi tiếp (chính nó đã có
        mã) *và* máy vẫn còn lượt đánh số cho cụm.  Trói hai câu ấy vào nhau
        chính là cái khoá chết cũ mà ``_leave_doing`` vừa gỡ.
        """
        stage = CardStage(status=COL_DOING, has_sku=True, cards_missing_sku=1, **self.SETTLED)
        self.assertEqual(COL_REVIEW, decide(stage).status)
        self.assertTrue(needs_sku_fill(stage))

    def test_a_fully_numbered_card_has_nothing_left_to_fill(self):
        self.assertFalse(needs_sku_fill(CardStage(status=COL_DOING, has_sku=True, **self.SETTLED)))

    def test_dragging_the_card_over_is_the_whole_ritual(self):
        """Kéo sang *Đang làm* là đủ để có mã — không phải bấm tấm nào.

        Luật cũ đòi bấm 👍/👎 **hết** từng tấm rồi mới cấp mã.  Người đặt việc
        chốt lại ngày 15/09/2026: thao tác duy nhất là kéo thẻ sang cột này.
        Bốn thẻ ``TASK-2026-06082``…``06085`` nằm im cả ngày vì luật cũ.
        """
        stage = CardStage(status=COL_DOING, images_total=11, images_pending=11)
        self.assertTrue(needs_sku_fill(stage))

    def test_one_thumbs_down_does_not_hold_the_rest_hostage(self):
        # 1 tấm 👎, 11 tấm chưa ai bấm: vẫn còn ảnh dùng được nên vẫn cấp mã.
        stage = CardStage(status=COL_DOING, images_total=12, images_pending=11, images_kept=0)
        self.assertTrue(needs_sku_fill(stage))

    def test_a_card_with_no_images_has_nothing_to_sell(self):
        # Không ảnh thì không có gì để lên listing; cấp mã là đốt số.
        self.assertFalse(needs_sku_fill(CardStage(status=COL_DOING)))

    def test_a_card_whose_every_image_was_binned_gets_no_code(self):
        # Mọi tấm đều 👎: idea này tay trắng thật, để nó chạy lại ảnh.
        stage = CardStage(status=COL_DOING, images_total=9, images_pending=0, images_kept=0)
        self.assertFalse(needs_sku_fill(stage))

    def test_getting_a_code_does_not_buy_a_ticket_to_the_next_column(self):
        """Cổng cấp mã nới, cổng chuyển cột **không**.

        Đây là chỗ bản 14/09 làm hỏng: nó sửa ``_votes_outstanding``, mà hàm
        ấy nuôi cả ba cổng — nên thẻ vừa nhận mã là biến khỏi cột của người
        vừa kéo nó, sang bàn người viết listing với cả chục tấm chưa ai nhìn.
        """
        stage = CardStage(status=COL_DOING, images_total=11, images_pending=11, has_sku=True)
        move = decide(stage)
        self.assertEqual("", move.status)
        self.assertEqual("còn 11 ảnh chờ 👍/👎", move.reason)

    def test_the_todo_column_still_waits_for_people(self):
        # Luật nới chỉ chạm cổng cấp mã; *Cần làm* vẫn không tự đi.
        stage = CardStage(status=COL_TODO, images_total=11, images_pending=11)
        self.assertEqual("", decide(stage).status)

    def test_only_the_doing_column_is_the_machines(self):
        for status in (COL_TODO, COL_REVIEW, COL_DONE, COL_CANCELLED, "lạ hoắc"):
            self.assertFalse(needs_sku_fill(CardStage(status=status, **self.SETTLED)), status)


class ProductCardTests(unittest.TestCase):
    """Thẻ sản phẩm: người kéo sang *Đang làm* chính là cái chốt.

    Thẻ sản phẩm là thẻ không có ảnh nào của máy chờ 👍/👎 — ảnh Trello nằm ở
    tệp đính kèm, ảnh người dán vào bình luận, hoặc chẳng có ảnh nào.  Không
    ai bỏ phiếu cho những ảnh ấy, nên chờ phiếu là chờ mãi.
    """

    def test_a_product_card_in_doing_without_a_code_is_the_machines_turn(self):
        self.assertTrue(needs_sku_fill(CardStage(status=COL_DOING, is_product=True)))

    def test_a_persons_unvoted_image_does_not_hold_a_product_card(self):
        # Bình luận ảnh của người, 0 phiếu: vẫn đếm là 1 ảnh chờ, nhưng đó
        # không phải ảnh máy đăng chờ chốt.
        stage = CardStage(status=COL_DOING, images_total=1, images_pending=1, is_product=True)
        self.assertTrue(needs_sku_fill(stage))
        self.assertEqual("chưa điền được mã SKU", decide(stage).reason)

    def test_a_numbered_product_card_waits_for_people_to_move_it(self):
        # Hôm 10/09 người dùng bảo trả về chỗ cũ những thẻ máy tự kéo sang
        # Đang review. Thẻ sản phẩm có mã rồi thì đứng yên chờ người kéo.
        stage = CardStage(status=COL_DOING, has_sku=True, is_product=True)
        move = decide(stage)
        self.assertFalse(move)
        self.assertIn("tự kéo", move.reason)
        self.assertFalse(needs_sku_fill(stage))

    def test_a_numbered_product_card_still_calls_for_its_siblings(self):
        stage = CardStage(status=COL_DOING, has_sku=True, cards_missing_sku=2, is_product=True)
        self.assertFalse(decide(stage))
        self.assertTrue(needs_sku_fill(stage))

    def test_a_product_card_outside_doing_is_not_numbered(self):
        for status in (COL_TODO, COL_REVIEW, COL_DONE, COL_CANCELLED, "lạ hoắc"):
            self.assertFalse(needs_sku_fill(CardStage(status=status, is_product=True)), status)

    def test_a_product_card_in_todo_is_not_pulled_forward(self):
        # Kéo sang Đang làm là việc của người; máy không làm thay.
        self.assertFalse(decide(CardStage(status=COL_TODO, is_product=True)))

    def test_an_idea_card_is_not_a_product_card_by_default(self):
        # ``is_product`` phải tự bật, không được suy ra từ "có ảnh chờ phiếu":
        # thẻ Idea và thẻ sản phẩm nay cùng được cấp mã, nên nếu hai loại lẫn
        # vào nhau thì chẳng test nào ở lớp này còn bắt được gì.
        stage = CardStage(status=COL_DOING, images_total=11, images_pending=11)
        self.assertFalse(stage.is_product)
        # Nhưng cổng chuyển cột thì hai loại vẫn khác nhau, và đó là chỗ phân biệt.
        self.assertEqual("còn 11 ảnh chờ 👍/👎", decide(stage).reason)


class ForwardOnlyTests(unittest.TestCase):
    def test_the_normal_steps_are_forward(self):
        self.assertTrue(is_forward(COL_TODO, COL_DOING))
        self.assertTrue(is_forward(COL_DOING, COL_REVIEW))
        self.assertTrue(is_forward(COL_REVIEW, COL_DONE))

    def test_skipping_a_column_is_still_forward(self):
        # Luật ở đây không sinh ra nước ấy, nhưng nó không phải đi lùi.
        self.assertTrue(is_forward(COL_TODO, COL_DONE))

    def test_going_back_is_refused(self):
        # Thẻ người ta vừa kéo tay sang cột sau không bao giờ bị máy kéo về.
        self.assertFalse(is_forward(COL_REVIEW, COL_TODO))
        self.assertFalse(is_forward(COL_DONE, COL_REVIEW))

    def test_staying_put_is_not_forward(self):
        self.assertFalse(is_forward(COL_DOING, COL_DOING))

    def test_a_cancelled_card_goes_nowhere(self):
        self.assertFalse(is_forward(COL_CANCELLED, COL_DOING))

    def test_cancelling_is_a_persons_job_not_the_machines(self):
        self.assertFalse(is_forward(COL_TODO, COL_CANCELLED))

    def test_an_unknown_column_at_either_end_refuses(self):
        self.assertFalse(is_forward("Chờ khách", COL_DOING))
        self.assertFalse(is_forward(COL_TODO, "Chờ khách"))

    def test_the_vietnamese_names_go_through_the_same_gate(self):
        self.assertTrue(is_forward("Cần làm", "Đang làm"))
        self.assertFalse(is_forward("Đang review", "Cần làm"))


class MoveTests(unittest.TestCase):
    def test_an_empty_move_is_falsy(self):
        self.assertFalse(Move("", "chờ ảnh"))

    def test_a_move_carries_the_vietnamese_column_name(self):
        self.assertEqual("Đang review", Move(COL_REVIEW, "xong mã").column)

    def test_staying_put_names_no_column(self):
        self.assertEqual("", Move("", "chờ ảnh").column)

    def test_every_decision_says_why(self):
        # Thẻ đứng im mà không ai nói vì sao trông y hệt thẻ hỏng.
        stages = [
            CardStage(status=COL_TODO),
            CardStage(status=COL_TODO, images_total=2, images_pending=2),
            CardStage(status=COL_TODO, images_total=2, images_kept=2),
            CardStage(status=COL_DOING),
            CardStage(status=COL_DOING, has_sku=True),
            CardStage(status=COL_REVIEW),
            CardStage(status=COL_REVIEW, is_listing=True, listing_done=True),
            CardStage(status=COL_DONE),
            CardStage(status="lạ hoắc"),
        ]
        for stage in stages:
            self.assertTrue(decide(stage).reason.strip(), stage)


class WholeJourneyTests(unittest.TestCase):
    """Một thẻ đi hết bảng, đúng thứ tự người dùng mô tả trong cuộc họp."""

    def test_a_listing_card_walks_the_board_one_step_at_a_time(self):
        stage = CardStage(status=COL_TODO, images_total=5, images_pending=5, is_listing=True)
        self.assertFalse(decide(stage))  # đang làm ảnh

        stage = CardStage(status=COL_TODO, images_total=5, images_kept=4, is_listing=True)
        self.assertEqual(COL_DOING, decide(stage).status)  # người duyệt xong

        stage = CardStage(status=COL_DOING, images_total=5, images_kept=4, is_listing=True)
        self.assertFalse(decide(stage))  # chờ điền mã

        stage = CardStage(
            status=COL_DOING, images_total=5, images_kept=4, has_sku=True, is_listing=True
        )
        self.assertEqual(COL_REVIEW, decide(stage).status)  # có mã rồi

        stage = CardStage(
            status=COL_REVIEW, images_total=5, images_kept=4, has_sku=True, is_listing=True
        )
        self.assertFalse(decide(stage))  # chờ viết listing

        stage = CardStage(
            status=COL_REVIEW,
            images_total=5,
            images_kept=4,
            has_sku=True,
            is_listing=True,
            listing_done=True,
        )
        self.assertEqual(COL_DONE, decide(stage).status)

    def test_an_image_only_card_stops_at_review(self):
        # Thẻ không khai listing dừng ở *Đang review* — đó là chỗ người viết
        # bài ngồi làm, và máy không dọn thẻ đi khỏi bàn của họ.
        stage = CardStage(status=COL_REVIEW, images_total=3, images_kept=3, has_sku=True)
        self.assertFalse(decide(stage))


if __name__ == "__main__":
    unittest.main()
