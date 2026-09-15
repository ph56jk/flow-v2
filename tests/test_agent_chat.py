from __future__ import annotations

import unittest

from flow_web.agent_chat import (
    sounds_like_an_order,
    ACTION_NONE,
    ACTION_PAUSE,
    ACTION_RESUME,
    ACTION_RUN,
    CardBrief,
    INTENT_ACCOUNT,
    INTENT_HELP,
    INTENT_LISTING,
    INTENT_PAUSE,
    INTENT_RESUME,
    INTENT_RUN,
    ACTION_SET,
    ACTION_SKU_FILL,
    ACTION_SKU_RENUMBER,
    INTENT_SET,
    INTENT_SKU,
    INTENT_SKU_FILL,
    INTENT_SKU_RENUMBER,
    INTENT_STATUS,
    INTENT_UNKNOWN,
    addressed_to_bot,
    answer,
    as_record,
    compose,
    has_trigger,
    normalize,
    parse_edits,
    resolve_field,
    strip_trigger,
    strip_trigger_raw,
    understand,
)


BOT = "agent-kin-test-agent@bots.hvg.internal"


def human(content: str, **overrides) -> dict:
    """Một bình luận của người thật, đúng hình dạng ``taskFull`` trả về."""
    node = {
        "name": "cmt1",
        "owner": "linh.duongthikhanh@havigroup.llc",
        "by_name": "Dương Thị Khánh Linh",
        "is_bot": 0,
        "mine": 0,
        "content": content,
        "mentions": [],
        "replies": [],
    }
    node.update(overrides)
    return node


class NormalizeTests(unittest.TestCase):
    def test_it_drops_accents_and_punctuation(self):
        self.assertEqual("chay lai giup minh", normalize("Chạy lại giúp mình!"))

    def test_it_turns_d_with_stroke_into_plain_d(self):
        # ``unicodedata`` không tách được ``đ``; thiếu bước thay tay thì "đăng"
        # nén thành "ang" và mọi lệnh có chữ đ trượt hết.
        self.assertEqual("dang listing", normalize("Đăng listing"))

    def test_it_keeps_digits(self):
        self.assertEqual("sku bt 3 001", normalize("SKU BT_3_001"))

    def test_nothing_in_nothing_out(self):
        self.assertEqual("", normalize(None))


class TriggerTests(unittest.TestCase):
    def test_at_bot_anywhere_counts(self):
        self.assertTrue(has_trigger("nhờ @bot xem hộ cái"))

    def test_leading_word_counts(self):
        self.assertTrue(has_trigger("Bot: trạng thái thế nào"))

    def test_talking_about_the_bot_does_not_count(self):
        # Nói *về* bot với đồng nghiệp thì bot phải im.
        self.assertFalse(has_trigger("hình như con bot chưa chạy thẻ này"))

    def test_it_strips_every_leading_trigger_word(self):
        self.assertEqual("chay lai", strip_trigger("@bot agent chạy lại"))

    def test_a_bare_call_leaves_nothing(self):
        self.assertEqual("", strip_trigger("@bot"))


class AddressingTests(unittest.TestCase):
    def test_a_named_call_is_for_the_bot(self):
        self.assertTrue(addressed_to_bot(human("@bot trạng thái"), BOT))

    def test_a_mention_is_for_the_bot(self):
        comment = human("cho mình xin cái SKU", mentions=[BOT])
        self.assertTrue(addressed_to_bot(comment, BOT))

    def test_a_mention_record_is_for_the_bot(self):
        comment = human("cho mình xin cái SKU", mentions=[{"user": BOT}])
        self.assertTrue(addressed_to_bot(comment, BOT))

    def test_two_people_talking_is_not_for_the_bot(self):
        self.assertFalse(addressed_to_bot(human("chị xem hộ em thẻ này với"), BOT))

    def test_a_reply_inside_the_bots_thread_is_for_the_bot(self):
        self.assertTrue(
            addressed_to_bot(human("chạy lại giúp mình"), BOT, in_bot_thread=True)
        )

    def test_the_bot_never_answers_itself(self):
        self.assertFalse(addressed_to_bot(human("@bot chạy", mine=1), BOT))

    def test_the_bot_never_answers_another_bot(self):
        # Bỏ hàng rào này thì hai con bot nói chuyện với nhau đến hết quota.
        self.assertFalse(addressed_to_bot(human("@bot chạy", is_bot=1), BOT))

    def test_an_empty_reply_in_a_thread_is_not_a_question(self):
        # Bình luận ảnh của luồng cũ mang đúng một ký tự vô hình.
        self.assertFalse(addressed_to_bot(human("​"), BOT, in_bot_thread=True))


class UnderstandTests(unittest.TestCase):
    def test_a_bare_call_asks_for_help(self):
        self.assertEqual(INTENT_HELP, understand("@bot"))

    def test_status_in_many_shapes(self):
        for message in ("@bot trạng thái", "bot: thẻ này sao rồi", "@bot xong chưa", "@bot status"):
            self.assertEqual(INTENT_STATUS, understand(message), message)

    def test_run_beats_the_shorter_word_inside_it(self):
        # "chạy lại" dài hơn "chạy" nên không bao giờ bị nuốt mất.
        self.assertEqual(INTENT_RUN, understand("@bot chạy lại giúp mình"))

    def test_stop_and_resume_are_different_intents(self):
        self.assertEqual(INTENT_PAUSE, understand("@bot dừng lại đã"))
        self.assertEqual(INTENT_RESUME, understand("@bot tiếp tục nhé"))

    def test_sku_question(self):
        self.assertEqual(INTENT_SKU, understand("@bot SKU của thẻ này là gì"))

    def test_listing_question(self):
        self.assertEqual(INTENT_LISTING, understand("@bot listing đăng chưa"))

    def test_accentless_typing_still_works(self):
        # Nửa nhóm gõ không dấu; hiểu được cả hai là điều kiện sống của tính năng.
        self.assertEqual(INTENT_RUN, understand("@bot chay lai di"))
        self.assertEqual(INTENT_STATUS, understand("bot trang thai the nao"))

    def test_small_talk_is_unknown(self):
        self.assertEqual(INTENT_UNKNOWN, understand("@bot ăn cơm chưa"))


BRIEF = CardBrief(
    task="TASK-2026-00202",
    title="Bờm Giáng sinh",
    status="Open",
    sku="BT_3_001",
    product="bờm",
    children=4,
    images_kept=2,
    images_pending=1,
    poll_seconds=120,
    root_task="TASK-2026-00202",
)



class AccountIntentTests(unittest.TestCase):
    """“acc?” — thẻ này lên shop nào, chạy ở máy nào."""

    BOOKED = CardBrief(
        task="TASK-1",
        account="acc32",
        shop="Havi Home",
        machine="etsy-vn32",
        account_source="label",
        account_in_book=True,
    )

    def test_the_question_is_recognised(self):
        for text in ("@bot acc nào", "@bot tài khoản nào", "@bot shop nào?", "@bot acc"):
            self.assertEqual(INTENT_ACCOUNT, understand(text), text)

    def test_listing_still_wins_its_own_word(self):
        # Cụm dài nhất thắng, nên "acc" nằm cạnh "listing" trong bảng lệnh mà
        # không nuốt mất câu hỏi về listing.
        self.assertEqual(INTENT_LISTING, understand("@bot đăng listing chưa"))

    def test_the_answer_names_the_shop_and_the_machine(self):
        text = compose(INTENT_ACCOUNT, self.BOOKED).text

        self.assertIn("acc32", text)
        self.assertIn("Havi Home", text)
        self.assertIn("etsy-vn32", text)

    def test_the_answer_says_where_it_read_the_account_from(self):
        # Người viết listing cần biết máy đọc được cái đó ở đâu để sửa đúng chỗ
        # khi nó sai.
        self.assertIn("nhãn trên thẻ", compose(INTENT_ACCOUNT, self.BOOKED).text)
        typed = CardBrief(task="T", account="acc32", account_source="meta_acc", account_in_book=True)
        self.assertIn("khối Thuộc tính", compose(INTENT_ACCOUNT, typed).text)

    def test_an_account_missing_from_the_book_is_flagged(self):
        # Không có dòng trong sổ thì máy chỉ đoán theo quy ước số; nói thẳng ra
        # còn hơn để người ta tin một cái máy đoán sai.
        brief = CardBrief(task="T", account="acc99", machine="etsy-99", account_source="label")

        text = compose(INTENT_ACCOUNT, brief).text
        self.assertIn("Sổ tay chưa có dòng", text)
        self.assertIn("đoán máy theo quy ước", text)

    def test_an_unknown_account_with_no_machine_does_not_claim_a_guess(self):
        # Quy ước tên chỉ ra được máy nếu máy đó có thật trong cấu hình. Không
        # có thì câu trả lời phải là "chưa biết", không phải một lời hứa suông.
        brief = CardBrief(task="T", account="havi-home", account_source="meta_acc")

        text = compose(INTENT_ACCOUNT, brief).text
        self.assertIn("chưa biết nó chạy ở máy nào", text)
        self.assertNotIn("Máy chạy listing", text)

    def test_a_card_with_no_account_is_told_how_to_add_one(self):
        text = compose(INTENT_ACCOUNT, CardBrief(task="T")).text

        self.assertIn("acc:", text)
        self.assertIn("nhãn", text)

    def test_asking_about_the_account_changes_nothing(self):
        self.assertEqual(ACTION_NONE, compose(INTENT_ACCOUNT, self.BOOKED).action)

    def test_a_listing_answer_carries_the_account_too(self):
        # Ai hỏi về listing là đang chuẩn bị đăng bài; tài khoản là thứ họ cần
        # ngay sau đó, không phải sau một câu hỏi nữa.
        brief = CardBrief(
            task="T",
            is_listing=True,
            listing_ready=True,
            account="acc32",
            shop="Havi Home",
            account_in_book=True,
        )

        self.assertIn("Havi Home", compose(INTENT_LISTING, brief).text)

    def test_help_mentions_the_account_book(self):
        self.assertIn("sổ tay", compose(INTENT_HELP, BRIEF).text)


class NextStepTests(unittest.TestCase):
    """Câu người ta thật sự muốn nghe: thẻ đang chờ gì để đi tiếp."""

    def test_the_status_answer_names_the_next_column(self):
        brief = CardBrief(task="T", next_column="Đang review", waiting="cả cụm đã có mã SKU")

        text = compose(INTENT_STATUS, brief).text

        self.assertIn("Bước kế: chuyển sang cột Đang review", text)
        self.assertIn("cả cụm đã có mã SKU", text)

    def test_a_card_staying_put_says_what_it_is_waiting_for(self):
        brief = CardBrief(task="T", waiting="còn 2 ảnh chờ 👍/👎")

        text = compose(INTENT_STATUS, brief).text

        self.assertIn("ở lại cột này", text)
        self.assertIn("còn 2 ảnh chờ", text)

    def test_no_step_line_is_invented_when_the_rule_was_never_asked(self):
        # ``waiting`` rỗng nghĩa là chưa ai hỏi luật cột, không phải "không có
        # gì để chờ". Viết ra một dòng "Bước kế" ở đây là bịa.
        self.assertNotIn("Bước kế", compose(INTENT_STATUS, CardBrief(task="T")).text)

    def test_a_card_with_no_column_says_so_plainly(self):
        self.assertIn("chưa rõ cột", compose(INTENT_STATUS, CardBrief(task="T")).text)
        self.assertNotIn("cột chưa rõ", compose(INTENT_STATUS, CardBrief(task="T")).text)

    def test_asking_straight_out_about_the_next_step_is_understood(self):
        # Đo trên bảng thật: người ta gõ đúng những chữ này, và trước đây bot
        # trả về "Tôi chưa hiểu ý này" — trong khi câu trả lời nằm sẵn ở dòng
        # cuối khối trạng thái.
        for said in (
            "bước kế là gì",
            "bước tiếp theo?",
            "tiếp theo là gì",
            "sang cột nào",
            "khi nào chuyển cột",
            "đang chờ gì vậy",
            "còn thiếu gì không",
            "khi nào xong",
            "vướng gì à",
        ):
            self.assertEqual(INTENT_STATUS, understand(said), said)

    def test_asking_to_carry_on_is_still_not_a_question_about_the_next_step(self):
        # "tiếp" ở đây là lời sai việc, không phải câu hỏi. Nhận nhầm thành
        # câu hỏi là bot đứng im khi được bảo chạy tiếp.
        self.assertEqual(INTENT_RESUME, understand("chạy tiếp"))
        self.assertEqual(INTENT_RESUME, understand("tiếp tục đi"))

    def test_the_column_is_named_the_way_it_is_on_the_board(self):
        # Người vận hành nhìn bảng thấy "Cần làm"; bot trả lời "Open" là bắt họ
        # tự dịch.
        self.assertIn("Cần làm", compose(INTENT_STATUS, CardBrief(task="T", status="Open")).text)
        self.assertIn(
            "Đang review",
            compose(INTENT_STATUS, CardBrief(task="T", status="Pending Review")).text,
        )


class OrderShapeTests(unittest.TestCase):
    """Phân biệt "đang sai việc" với "đang hỏi" — chỉ bằng hình dạng câu.

    Cái ranh giới này quyết định câu nào đáng nhờ Claude đọc hộ. Kéo rộng quá
    thì mỗi câu hỏi tình trạng là một hoá đơn; hẹp quá thì đúng những câu người
    ta gõ nhiều nhất lại rơi ra ngoài.
    """

    def test_cau_sai_viec_thi_nhan_ra(self) -> None:
        for said in (
            "@bot đổi mẫu listing sang mockup-bom-02",
            "@bot sửa acc giúp tôi",
            "@bot chuyển thẻ này sang shop kia đi",
            "@bot cập nhật tên sản phẩm nhé",
            "@bot xoá cái template đó đi",
        ):
            self.assertTrue(sounds_like_an_order(said), said)

    def test_cau_hoi_thi_khong(self) -> None:
        # Quan trọng hơn vế trên: một câu hỏi bị nhận nhầm thành lệnh là một
        # lượt hỏi mất tiền, mà câu trả lời đang đúng sẵn rồi.
        for said in (
            "@bot sku của thẻ này là gì",
            "@bot trạng thái",
            "@bot listing xong chưa",
            "@bot bước kế là gì",
            "@bot bờm nơ hồng",
        ):
            self.assertFalse(sounds_like_an_order(said), said)

    def test_goi_ten_roi_thoi_thi_khong_phai_lenh(self) -> None:
        self.assertFalse(sounds_like_an_order("@bot"))
        self.assertFalse(sounds_like_an_order(""))


class SkuCommandTests(unittest.TestCase):
    """“Điền sku đi” là **lệnh**, còn “sku là gì” là câu hỏi — hai chuyện khác nhau.

    Gộp làm một thì mỗi lần ai đó hỏi thăm mã của thẻ, bot lại ghi đè một lượt
    mã lên cả cụm.  Và tách ``fill`` khỏi ``renumber`` vì hậu quả khác hẳn:
    một bên điền chỗ trống, một bên xoá mã đã in lên tem.
    """

    def test_asking_and_ordering_are_different_intents(self):
        self.assertEqual(INTENT_SKU, understand("@bot sku của thẻ này là gì"))
        self.assertEqual(INTENT_SKU_FILL, understand("@bot điền sku đi"))

    def test_renumbering_is_never_reached_by_asking_to_fill(self):
        # Cụm chữ dài thắng cụm ngắn: "đánh số lại" không được rơi vào
        # "đánh số", vì một bên giữ mã cũ còn một bên xoá sạch.
        self.assertEqual(INTENT_SKU_FILL, understand("@bot đánh số"))
        self.assertEqual(INTENT_SKU_RENUMBER, understand("@bot đánh số lại giúp mình"))
        self.assertEqual(INTENT_SKU_RENUMBER, understand("@bot đổi mã sku"))

    def test_a_typed_value_still_beats_the_command(self):
        # "sku: BT_1_001" là người ta gõ tay một mã cụ thể cho *thẻ này*, không
        # phải nhờ đánh số cả cụm.
        self.assertEqual(INTENT_SET, understand("@bot sku: BT_1_001"))

    def test_accentless_typing_works_here_too(self):
        self.assertEqual(INTENT_SKU_FILL, understand("@bot dien sku"))
        self.assertEqual(INTENT_SKU_RENUMBER, understand("@bot renumber"))

    def test_the_command_runs_from_the_root_not_from_the_card_spoken_on(self):
        # Số cuối trong mã là hàng chung của cả cụm. Đánh số riêng một nhánh
        # thì hai nhánh cùng ra ``_001``.
        brief = CardBrief(task="TASK-2", root_task="TASK-1")
        self.assertIn("TASK-1", compose(INTENT_SKU_FILL, brief).text)
        self.assertNotIn("TASK-2", compose(INTENT_SKU_FILL, brief).text)

    def test_a_card_with_no_root_numbers_itself(self):
        self.assertIn("TASK-9", compose(INTENT_SKU_FILL, CardBrief(task="TASK-9")).text)

    def test_filling_promises_to_keep_the_codes_that_exist(self):
        reply = compose(INTENT_SKU_FILL, CardBrief(task="TASK-1"))
        self.assertEqual(ACTION_SKU_FILL, reply.action)
        self.assertIn("giữ nguyên", reply.text)

    def test_renumbering_says_out_loud_what_it_destroys(self):
        # Mã SKU đã đi ra ngoài phần mềm — in lên tem, gõ vào shop. Đổi nó mà
        # không nói gì là để người ta phát hiện ở khâu đóng gói.
        reply = compose(INTENT_SKU_RENUMBER, CardBrief(task="TASK-1"))
        self.assertEqual(ACTION_SKU_RENUMBER, reply.action)
        self.assertIn("ghi đè", reply.text)
        self.assertIn("tem", reply.text)

    def test_asking_the_question_writes_nothing(self):
        self.assertEqual(ACTION_NONE, compose(INTENT_SKU, CardBrief(task="TASK-1")).action)

    def test_help_mentions_both_commands(self):
        text = compose(INTENT_HELP, CardBrief(task="TASK-1")).text
        self.assertIn("điền sku", text.lower())
        self.assertIn("đánh số lại", text.lower())


class EditIntentTests(unittest.TestCase):
    """Sửa thẻ bằng lời nói: “acc: acc32” phải là **lệnh**, không phải câu hỏi."""

    def test_a_value_typed_after_a_colon_is_a_command_not_a_question(self):
        # "acc" và "acc: acc32" đều chứa đúng chữ "acc". Hình dạng gán giá trị
        # phải thắng bảng lệnh, nếu không lệnh sửa nào cũng bị trả lời bằng
        # một bài kể lể về tài khoản hiện tại.
        self.assertEqual(INTENT_SET, understand("acc: acc32"))
        self.assertEqual(INTENT_ACCOUNT, understand("acc nào vậy"))

    def test_the_field_is_recognised_with_or_without_its_accents(self):
        self.assertEqual("product", resolve_field("sản phẩm"))
        self.assertEqual("product", resolve_field("san pham"))
        self.assertEqual("acc", resolve_field("Tài khoản"))
        self.assertEqual("", resolve_field("action_1"))

    def test_only_the_four_named_fields_may_be_written(self):
        # Cho gõ tên ô tuỳ ý nghĩa là một câu lỡ tay đè được ``action_1`` và
        # biến thẻ ảnh thành thẻ listing.
        self.assertEqual((), parse_edits("@bot action_1: listing"))
        self.assertEqual((), parse_edits("@bot status: Hoàn thành"))

    def test_the_value_keeps_its_accents_exactly_as_typed(self):
        # Giá trị này nằm nguyên xi lên thẻ. Lưu bản đã bóc dấu là tự tay sửa
        # "khăn tay" thành "khan tay" trên bảng của người ta.
        self.assertEqual((("product", "khăn tay"),), parse_edits("@bot sửa sản phẩm thành khăn tay"))

    def test_an_account_is_written_in_the_one_shape_the_book_reads(self):
        # Sổ tay tra theo ``normalize_token``; ghi "ACC 32" nguyên văn lên thẻ
        # là tra sổ không ra dòng nào.
        self.assertEqual((("acc", "acc-32"),), parse_edits("@bot acc: ACC 32"))

    def test_several_fields_in_one_message_are_all_read(self):
        self.assertEqual(
            (("acc", "acc32"), ("product", "bờm")),
            parse_edits("@bot acc: acc32\nproduct: bờm"),
        )

    def test_clearing_a_field_is_an_empty_value_not_a_field_named_xoa(self):
        self.assertEqual((("acc", ""),), parse_edits("@bot xoá acc"))

    def test_a_plain_question_carries_no_edits_at_all(self):
        self.assertEqual((), parse_edits("@bot trạng thái thế nào rồi"))

    def test_the_trigger_is_stripped_without_losing_the_accents(self):
        self.assertEqual("sửa sản phẩm thành bờm", strip_trigger_raw("@bot sửa sản phẩm thành bờm"))

    def test_the_answer_promises_the_write_but_does_not_claim_it_happened(self):
        # Lúc soạn câu thì chưa ghi gì cả — ``chat_pass`` mới gọi ERP, và nó
        # có quyền thất bại. Hứa "đã ghi xong" ở đây là hứa hộ một việc chưa
        # xảy ra.
        reply = answer("@bot acc: acc32", CardBrief(task="T", known_accounts=("acc32",)))

        self.assertEqual(INTENT_SET, reply.intent)
        self.assertEqual(ACTION_SET, reply.action)
        self.assertEqual((("acc", "acc32"),), reply.edits)
        self.assertIn("Tôi ghi acc", reply.text)
        self.assertNotIn("đã ghi xong", reply.text)

    def test_the_book_decides_how_an_account_is_spelled(self):
        # Đo trên bảng thật: gõ "ACC 32" thì luật chuẩn hoá cho ra "acc-32",
        # còn sổ tay ghi "acc32" — thẻ mang "acc-32" tra sổ không ra dòng nào
        # nên chạy sai máy. Sổ tay là nơi quyết cách viết.
        book = CardBrief(task="T", known_accounts=("acc32", "acc16"))
        for said in ("@bot acc: ACC 32", "@bot acc: acc-32", "@bot tài khoản: Acc 32"):
            reply = answer(said, book)
            self.assertEqual((("acc", "acc32"),), reply.edits, said)
            self.assertNotIn("sổ tay tài khoản chưa có", reply.text, said)

    def test_an_account_missing_from_the_book_is_written_but_flagged(self):
        # Vẫn ghi: người ta có thể vừa mở shop mới và chưa kịp ghi sổ. Nhưng
        # im lặng thì tới lúc thẻ chạy nhầm máy mới có người biết.
        reply = answer("@bot acc: acc99", CardBrief(task="T", known_accounts=("acc32",)))

        self.assertEqual((("acc", "acc99"),), reply.edits)
        self.assertIn("sổ tay tài khoản chưa có", reply.text)

    def test_a_sku_in_the_wrong_shape_is_written_but_flagged(self):
        reply = answer("@bot sku: linh tinh", CardBrief(task="T"))

        self.assertIn("không đúng dạng", reply.text)
        self.assertIn("bỏ qua thẻ này", reply.text)

    def test_a_sku_in_the_right_shape_draws_no_complaint(self):
        self.assertNotIn("không đúng dạng", answer("@bot sku: BT_3_007", CardBrief(task="T")).text)

    def test_clearing_a_field_is_described_as_clearing_not_as_writing(self):
        self.assertIn("xoá trắng", answer("@bot xoá acc", CardBrief(task="T")).text)

    def test_the_run_record_says_which_fields_were_asked_for(self):
        # Người bật ``dry_run`` bật nó lên đúng để hỏi câu này: *sẽ* ghi gì.
        reply = answer("@bot acc: acc32", CardBrief(task="T", known_accounts=("acc32",)))
        self.assertEqual({"acc": "acc32"}, as_record({"name": "c1"}, "T", reply)["edits"])

    def test_a_question_leaves_no_edits_on_the_record(self):
        self.assertNotIn("edits", as_record({"name": "c1"}, "T", answer("@bot sku", CardBrief(task="T"))))


class ComposeTests(unittest.TestCase):
    def test_status_reports_the_card(self):
        reply = compose(INTENT_STATUS, BRIEF)
        self.assertIn("TASK-2026-00202", reply.text)
        self.assertIn("BT_3_001", reply.text)
        self.assertIn("2 đã giữ", reply.text)
        self.assertIn("1 đang chờ", reply.text)
        self.assertEqual(ACTION_NONE, reply.action)

    def test_status_counts_images_waiting_to_be_removed(self):
        reply = compose(INTENT_STATUS, CardBrief(task="T", images_dropped=2))
        self.assertIn("2 bị 👎", reply.text)

    def test_sku_answers_with_the_code(self):
        self.assertIn("BT_3_001", compose(INTENT_SKU, BRIEF).text)

    def test_sku_without_a_product_says_what_is_missing(self):
        reply = compose(INTENT_SKU, CardBrief(task="T"))
        self.assertIn("product", reply.text)

    def test_run_asks_for_a_run(self):
        reply = compose(INTENT_RUN, BRIEF)
        self.assertEqual(ACTION_RUN, reply.action)
        self.assertIn("120s", reply.text)

    def test_run_on_a_paused_card_refuses_and_says_how_to_undo(self):
        reply = compose(INTENT_RUN, CardBrief(task="T", paused=True))
        self.assertEqual(ACTION_NONE, reply.action)
        self.assertIn("tiếp tục", reply.text)

    def test_run_says_so_when_autorun_is_off(self):
        reply = compose(INTENT_RUN, CardBrief(task="T", autorun=False))
        self.assertEqual(ACTION_NONE, reply.action)
        self.assertIn("ERP_AGENT_AUTORUN", reply.text)

    def test_pause_names_the_card_it_stops(self):
        reply = compose(INTENT_PAUSE, BRIEF)
        self.assertEqual(ACTION_PAUSE, reply.action)
        self.assertIn("TASK-2026-00202", reply.text)

    def test_pause_on_a_child_stops_the_whole_cluster(self):
        brief = CardBrief(task="TASK-2026-00648", root_task="TASK-2026-00202")
        self.assertIn("TASK-2026-00202", compose(INTENT_PAUSE, brief).text)

    def test_resume_on_a_running_card_says_there_was_nothing_to_resume(self):
        reply = compose(INTENT_RESUME, BRIEF)
        self.assertIn("có bị dừng đâu", reply.text)

    def test_listing_on_a_plain_image_card(self):
        self.assertIn("không khai action listing", compose(INTENT_LISTING, BRIEF).text)

    def test_listing_repeats_what_is_still_missing(self):
        brief = CardBrief(task="T", is_listing=True, listing_missing="còn 2 ảnh chờ 👍/👎")
        self.assertIn("còn 2 ảnh chờ", compose(INTENT_LISTING, brief).text)

    def test_an_unknown_question_still_gets_the_menu(self):
        # Im lặng và "không hiểu" trông giống hệt nhau với người hỏi.
        reply = answer("@bot ăn cơm chưa", BRIEF)
        self.assertIn("chưa hiểu", reply.text)
        self.assertIn("trạng thái", reply.text)

    def test_every_reply_has_words_in_it(self):
        for intent in (
            INTENT_HELP,
            INTENT_STATUS,
            INTENT_SKU,
            INTENT_RUN,
            INTENT_PAUSE,
            INTENT_RESUME,
            INTENT_LISTING,
            INTENT_UNKNOWN,
        ):
            self.assertTrue(compose(intent, BRIEF).text.strip(), intent)


class WireFormatTests(unittest.TestCase):
    """Ô bình luận ERP nhận chữ thuần — đo trên bảng thật, không phải đoán.

    Bản gửi lên từng là HTML với ``<br>``; đăng thử lên ERP rồi đọc lại thì ra
    ``&lt;br&gt;``, tức là người đọc thấy đúng bốn chữ ``<br>`` nằm giữa câu.
    Máy chủ tự escape phần người ta gõ, nên chỗ này chỉ việc xuống dòng.
    """

    def test_lines_are_joined_by_a_real_newline(self):
        self.assertIn("\n", compose(INTENT_HELP, BRIEF).text)

    def test_no_html_tag_is_ever_sent(self):
        self.assertNotIn("<br>", compose(INTENT_HELP, BRIEF).text)

    def test_a_card_title_is_passed_through_untouched(self):
        # Escape ở đây nữa là escape hai lần: một cái tên có "&" sẽ hiện ra
        # thành "&amp;" trên thẻ của người khác.
        brief = CardBrief(task="T", title="Khăn & Bờm", images_kept=1)
        self.assertIn("Khăn & Bờm", compose(INTENT_STATUS, brief).text)


if __name__ == "__main__":
    unittest.main()
