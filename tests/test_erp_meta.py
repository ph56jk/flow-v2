"""Reading the ERP Task's own metadata — the block that says what a Task *is*.

This repo's agent works image cards; the listing half of the family works Etsy
cards.  Both live in the same ERP and are told apart by one thing: the
*Thuộc tính* panel block that ``flow_web.erp_meta`` parses::

    action_1: listing
    acc: acc32

An image card writes no ``action_*`` at all, so "said nothing" has to keep
meaning *carry on as before* — never *reject*.  That asymmetry is the reason
this file exists here and not only in the listing repo: it is what lets one
agent hold both kinds of card without either half stepping on the other.

The parser half of the listing repo's ``tests/test_erp_task_meta.py``, carried
over unchanged.  The half that exercises ``FlowWebService`` did not come with
it — this repo has no Etsy service to exercise yet.
"""

from __future__ import annotations

import unittest

from flow_web.erp_meta import (
    LISTING_ACTIONS,
    TaskMeta,
    account_from_labels,
    agent_users,
    inherit,
    machine_for_account,
    missing_from_parent,
    parent_task_id,
    normalize_action,
    parse_meta_block,
    resolve_routing,
    task_meta,
)

from flow_web.store import StateStore


class ParseMetaBlockTests(unittest.TestCase):
    def test_reads_the_panel_block_as_the_panel_writes_it(self) -> None:
        parsed = parse_meta_block("action_1: listing\nacc: acc32\n")

        self.assertEqual({"action_1": "listing", "acc": "acc32"}, parsed)

    def test_a_broken_line_is_skipped_instead_of_taking_the_sweep_down(self) -> None:
        parsed = parse_meta_block(
            "\n".join(
                [
                    "# ghi chú",
                    "acc: acc32",
                    "khong-co-dau-hai-cham",
                    "Không Hợp Lệ: x",
                    "- listing",
                    "",
                    "action: listing",
                ]
            )
        )

        self.assertEqual({"acc": "acc32", "action": "listing"}, parsed)

    def test_quotes_lists_and_nulls_flatten_to_plain_text(self) -> None:
        parsed = parse_meta_block(
            "\n".join(
                [
                    'acc: "acc32"',
                    "_labels: [urgent, etsy]",
                    "note: null",
                    "empty: ~",
                ]
            )
        )

        self.assertEqual("acc32", parsed["acc"])
        self.assertEqual("urgent, etsy", parsed["_labels"])
        self.assertEqual("", parsed["note"])
        self.assertEqual("", parsed["empty"])

    def test_a_repeated_key_keeps_the_last_value(self) -> None:
        self.assertEqual({"acc": "acc16"}, parse_meta_block("acc: acc32\nacc: acc16"))


class TaskMetaTests(unittest.TestCase):
    def test_actions_come_back_in_panel_order(self) -> None:
        meta = TaskMeta(attributes=parse_meta_block("action_2: review\naction_1: listing\naction: check"))

        self.assertEqual(["check", "listing", "review"], meta.actions)

    def test_one_key_may_hold_several_actions(self) -> None:
        meta = TaskMeta(attributes=parse_meta_block("action_1: Listing Etsy, review"))

        self.assertEqual(["listing_etsy", "review"], meta.actions)
        self.assertTrue(meta.is_listing)

    def test_a_task_that_names_no_action_declares_nothing(self) -> None:
        meta = TaskMeta(attributes=parse_meta_block("acc: acc32"))

        self.assertFalse(meta.declares_actions)
        self.assertFalse(meta.is_listing)
        self.assertEqual("acc32", meta.account_id)

    def test_account_is_read_from_any_of_the_accepted_keys(self) -> None:
        self.assertEqual("acc32", TaskMeta(attributes={"account": "ACC32"}).account_id)
        self.assertEqual("acc32", TaskMeta(attributes={"etsy_account": " acc32 "}).account_id)
        # "default"/"auto" mean "nothing was said", not an account named that.
        self.assertEqual("", TaskMeta(attributes={"acc": "default"}).account_id)

    def test_it_reads_a_task_detail_or_the_card_built_from_one(self) -> None:
        detail = {"name": "TASK-2026-01148", "meta": "acc: acc32", "meta_auto": "_status: Open"}

        self.assertEqual("acc32", task_meta(detail).account_id)
        self.assertEqual("acc32", task_meta({"id": "TASK-2026-01148", "_erp_raw": detail}).account_id)
        self.assertEqual("Open", task_meta(detail).get("_status"))

    def test_a_task_with_no_metadata_at_all_is_silent_not_an_error(self) -> None:
        meta = task_meta({"id": "TASK-2026-01148"})

        self.assertEqual([], meta.actions)
        self.assertEqual("", meta.account_id)
        self.assertEqual("", meta.machine_id)


class AssignedAgentTests(unittest.TestCase):
    """The other half of the family routes by the assigned bot, so we read it too."""

    def test_the_assignment_comes_from_the_task_detail(self) -> None:
        meta = task_meta(
            {
                "id": "TASK-2026-01148",
                "agents": [{"bot_user": "flow-bot@havigroup.llc"}, {"bot_user": "listing-bot@havigroup.llc"}],
            }
        )

        self.assertEqual(("flow-bot@havigroup.llc", "listing-bot@havigroup.llc"), meta.agent_users)
        self.assertTrue(meta.assigned_to("Flow-Bot@havigroup.llc"))
        self.assertFalse(meta.assigned_to("someone-else@havigroup.llc"))

    def test_the_rendered_line_is_used_when_the_detail_carries_no_agent_list(self) -> None:
        meta = task_meta({"meta_auto": "_agents: flow-bot@havigroup.llc, listing-bot@havigroup.llc"})

        self.assertEqual(("flow-bot@havigroup.llc", "listing-bot@havigroup.llc"), meta.agent_users)

    def test_the_real_field_beats_the_rendered_line(self) -> None:
        meta = task_meta(
            {
                "meta_auto": "_agents: stale-bot@havigroup.llc",
                "agents": [{"bot_user": "flow-bot@havigroup.llc"}],
            }
        )

        self.assertEqual(("flow-bot@havigroup.llc",), meta.agent_users)

    def test_an_unassigned_task_answers_no_to_everyone(self) -> None:
        meta = task_meta({"id": "TASK-2026-01148"})

        self.assertEqual((), meta.agent_users)
        self.assertFalse(meta.assigned_to("flow-bot@havigroup.llc"))
        self.assertFalse(meta.assigned_to(""))

    def test_a_duplicated_or_empty_assignment_does_not_produce_a_phantom_bot(self) -> None:
        self.assertEqual(
            ("flow-bot@havigroup.llc",),
            agent_users({"agents": [{"bot_user": "flow-bot@havigroup.llc"}, {"bot_user": " "}, {"bot_user": "flow-bot@havigroup.llc"}]}),
        )
        self.assertEqual((), agent_users(None))


class FlowProfileTests(unittest.TestCase):
    """``profile:`` names a Google Flow browser profile, not an Etsy account."""

    def test_the_profile_label_is_kept_exactly_as_written(self) -> None:
        meta = task_meta({"meta": "profile: Acc 32 Flow\nacc: acc32"})

        self.assertEqual("Acc 32 Flow", meta.flow_profile)
        self.assertEqual("acc32", meta.account_id)

    def test_a_profile_named_default_survives(self) -> None:
        self.assertEqual("default", task_meta({"meta": "flow_profile: default"}).flow_profile)

    def test_an_account_alone_says_nothing_about_the_flow_profile(self) -> None:
        self.assertEqual("", task_meta({"meta": "acc: acc32"}).flow_profile)


class MachineForAccountTests(unittest.TestCase):
    FLEET = ("etsy-vn32", "etsy-16", "capa-hinh")

    def test_the_fleet_number_is_what_an_operator_means_by_acc32(self) -> None:
        self.assertEqual("etsy-vn32", machine_for_account("acc32", self.FLEET))
        self.assertEqual("etsy-16", machine_for_account("acc16", self.FLEET))

    def test_an_account_named_exactly_like_a_machine_matches_first(self) -> None:
        self.assertEqual("etsy-16", machine_for_account("etsy-16", self.FLEET))

    def test_an_ambiguous_number_resolves_to_nothing_rather_than_a_guess(self) -> None:
        self.assertEqual("", machine_for_account("acc32", ("etsy-vn32", "etsy-32")))

    def test_an_account_with_no_number_and_no_match_resolves_to_nothing(self) -> None:
        self.assertEqual("", machine_for_account("shop-noel", self.FLEET))
        self.assertEqual("", machine_for_account("", self.FLEET))


class ResolveRoutingTests(unittest.TestCase):
    FLEET = ("etsy-vn32", "etsy-16")

    def test_a_machine_written_on_the_task_beats_every_other_source(self) -> None:
        meta = TaskMeta(attributes=parse_meta_block("acc: acc32\nmachine: capa-hinh"))

        routing = resolve_routing(
            meta,
            known_machines=self.FLEET,
            account_machines={"acc32": "etsy-vn32"},
        )

        self.assertEqual("acc32", routing.account_id)
        self.assertEqual("capa-hinh", routing.machine_id)
        self.assertEqual("meta_machine", routing.machine_source)

    def test_the_configured_machine_beats_the_naming_convention(self) -> None:
        routing = resolve_routing(
            TaskMeta(attributes={"acc": "acc32"}),
            known_machines=self.FLEET,
            account_machines={"acc32": "etsy-16"},
        )

        self.assertEqual("etsy-16", routing.machine_id)
        self.assertEqual("account_config", routing.machine_source)

    def test_with_nothing_configured_the_fleet_number_decides(self) -> None:
        routing = resolve_routing(TaskMeta(attributes={"acc": "acc32"}), known_machines=self.FLEET)

        self.assertEqual("etsy-vn32", routing.machine_id)
        self.assertEqual("fleet_number", routing.machine_source)
        self.assertEqual("meta_acc", routing.account_source)

    def test_an_account_with_no_machine_anywhere_stays_claimable_by_any_machine(self) -> None:
        routing = resolve_routing(TaskMeta(attributes={"acc": "shop-noel"}), known_machines=self.FLEET)

        self.assertEqual("shop-noel", routing.account_id)
        self.assertEqual("", routing.machine_id)
        self.assertFalse(routing.known_account)

    def test_a_registered_account_is_reported_as_known(self) -> None:
        routing = resolve_routing(
            TaskMeta(attributes={"acc": "acc32"}),
            known_accounts=("acc32", "acc16"),
            known_machines=self.FLEET,
        )

        self.assertTrue(routing.known_account)

    def test_a_task_that_says_nothing_routes_nowhere(self) -> None:
        routing = resolve_routing(TaskMeta(), known_machines=self.FLEET)

        self.assertFalse(routing.resolved)
        self.assertEqual("", routing.account_id)


class LabelRoutingTests(unittest.TestCase):
    """Dán nhãn lên thẻ là đủ để biết listing thuộc tài khoản nào.

    Người viết listing gõ bài bằng tay rồi gắn nhãn, chứ không mở panel
    *Thuộc tính* gõ thêm dòng ``acc:``.  ERP đồng bộ nhãn xuống ``_labels``
    của ``meta_auto``, nên đó là chỗ đọc.
    """

    FLEET = ("etsy-vn32", "etsy-16")

    def test_a_tag_names_the_account(self) -> None:
        meta = task_meta({"meta": "action_1: listing", "meta_auto": "_labels: [acc32, gap]"})

        routing = resolve_routing(meta, known_machines=self.FLEET)

        self.assertEqual("acc32", routing.account_id)
        self.assertEqual("label", routing.account_source)
        self.assertEqual("etsy-vn32", routing.machine_id)

    def test_a_typed_line_still_beats_a_tag(self) -> None:
        # Dán nhầm nhãn không được phép kéo một thẻ đã ghi rõ acc đi shop khác.
        meta = task_meta({"meta": "acc: acc16", "meta_auto": "_labels: [acc32]"})

        routing = resolve_routing(meta, known_machines=self.FLEET)

        self.assertEqual("acc16", routing.account_id)
        self.assertEqual("meta_acc", routing.account_source)

    def test_an_ordinary_tag_is_not_an_account(self) -> None:
        meta = task_meta({"meta": "", "meta_auto": "_labels: [gap, cho-anh]"})

        self.assertEqual("", resolve_routing(meta).account_id)

    def test_two_account_tags_resolve_to_nothing(self) -> None:
        # Đoán một trong hai là gửi hàng lên nhầm shop, và không ai biết vì sao.
        meta = task_meta({"meta": "", "meta_auto": "_labels: [acc32, acc16]"})

        self.assertEqual("", resolve_routing(meta).account_id)

    def test_a_shop_with_its_own_name_is_matched_by_the_known_list(self) -> None:
        meta = task_meta({"meta": "", "meta_auto": "_labels: [havi-home]"})

        routing = resolve_routing(meta, known_accounts=("havi-home",))

        self.assertEqual("havi-home", routing.account_id)
        self.assertTrue(routing.known_account)

    def test_a_card_with_no_tags_reads_as_no_tags(self) -> None:
        self.assertEqual((), task_meta({"meta_auto": "_labels: []"}).labels)
        self.assertEqual("", account_from_labels(()))


class InheritedMetaTests(unittest.TestCase):
    """ERP hands nothing down by itself, so the reader does it."""

    def test_the_parent_is_found_under_any_of_the_spellings(self) -> None:
        self.assertEqual("TASK-2026-01000", parent_task_id({"parent_task": "TASK-2026-01000"}))
        self.assertEqual("TASK-2026-01000", parent_task_id({"parentTask": "TASK-2026-01000"}))
        self.assertEqual("TASK-2026-01000", parent_task_id({"parent": {"name": "TASK-2026-01000"}}))
        self.assertEqual("", parent_task_id({"parent_task": "None"}))
        self.assertEqual("", parent_task_id(None))

    def test_the_child_takes_what_it_did_not_write_itself(self) -> None:
        parent = task_meta({"meta": "action_1: listing\nacc: acc32"})
        child = task_meta({"meta": "note: mau do"})

        merged = inherit(child, parent)

        self.assertEqual("acc32", merged.account_id)
        self.assertTrue(merged.is_listing)
        self.assertEqual("mau do", merged.get("note"))

    def test_a_line_the_child_wrote_beats_the_parent(self) -> None:
        parent = task_meta({"meta": "acc: acc32\nmachine: etsy-vn32"})
        child = task_meta({"meta": "acc: acc16"})

        merged = inherit(child, parent)

        self.assertEqual("acc16", merged.account_id)
        self.assertEqual("etsy-vn32", merged.machine_id)

    def test_meta_auto_is_never_inherited(self) -> None:
        parent = task_meta({"meta_auto": "_task: TASK-2026-01000\n_status: Completed"})
        child = task_meta({"meta_auto": "_task: TASK-2026-01148\n_status: Open", "meta": "acc: acc32"})

        merged = inherit(child, parent)

        self.assertEqual("TASK-2026-01148", merged.auto.get("_task"))
        self.assertEqual("Open", merged.auto.get("_status"))

    def test_agents_come_down_only_when_the_child_has_none(self) -> None:
        parent = task_meta({"agents": [{"bot_user": "flow-bot@havigroup.llc"}]})

        self.assertEqual(("flow-bot@havigroup.llc",), inherit(task_meta({}), parent).agent_users)
        self.assertEqual(
            ("listing-bot@havigroup.llc",),
            inherit(task_meta({"agents": [{"bot_user": "listing-bot@havigroup.llc"}]}), parent).agent_users,
        )

    def test_a_task_with_no_parent_is_returned_untouched(self) -> None:
        child = task_meta({"meta": "acc: acc32"})

        self.assertIs(child, inherit(child, None))
        self.assertIs(child, inherit(child, TaskMeta()))


class MissingFromParentTests(unittest.TestCase):
    """Ô nào của thẻ cha phải *ghi* xuống thẻ con — khác ``inherit`` chỉ đọc.

    Khối dưới đây chép từ thẻ cha thật TASK-2026-05384 (PROJ-0087): người ta
    khai một lần ở thẻ cha, còn 48 thẻ con để trống trơn.
    """

    PARENT = parse_meta_block(
        "account:\nsku:\nproduct_type: Punch Needle Ornament\nproduct_group: handmade\n"
        "fulfillment: FBM\nsales_channel: Etsy\n"
    )

    def test_a_blank_child_gets_every_attribute_the_parent_filled(self) -> None:
        self.assertEqual(
            {
                "product_type": "Punch Needle Ornament",
                "product_group": "handmade",
                "fulfillment": "FBM",
                "sales_channel": "Etsy",
            },
            missing_from_parent({}, self.PARENT),
        )

    def test_content_stays_on_the_parent(self) -> None:
        # ``content: Có`` là seller khai trên thẻ cha, và cổng ảnh content chỉ
        # đọc thẻ cha.  Bot chép xuống là tự ghi content thay seller.
        written = missing_from_parent({}, {"content": "Có", "fulfillment": "FBM"})

        self.assertEqual({"fulfillment": "FBM"}, written)

    def test_a_line_the_parent_left_blank_is_not_written(self) -> None:
        # ``account:`` trống trên thẻ cha là "chưa có", không phải "xoá đi".
        written = missing_from_parent({}, self.PARENT)

        self.assertNotIn("account", written)
        self.assertNotIn("sku", written)

    def test_what_the_child_wrote_itself_is_never_overwritten(self) -> None:
        written = missing_from_parent({"fulfillment": "FBA"}, self.PARENT)

        self.assertNotIn("fulfillment", written)
        self.assertEqual("Etsy", written["sales_channel"])

    def test_a_blank_line_on_the_child_counts_as_not_filled(self) -> None:
        # Panel ERP tự dựng sẵn ``account:``/``sku:`` trống trên thẻ mới.
        written = missing_from_parent({"account": ""}, {"account": "acc32"})

        self.assertEqual({"account": "acc32"}, written)

    def test_the_account_and_template_the_lister_needs_come_down(self) -> None:
        # Review Lister đòi ``account`` + ``copysku`` trên chính thẻ con.
        written = missing_from_parent({}, {"account": "acc32", "copysku": "OR_18_007"})

        self.assertEqual({"account": "acc32", "copysku": "OR_18_007"}, written)

    def test_a_child_that_named_the_field_another_way_keeps_its_own(self) -> None:
        # ``acc`` được tin trước ``account``: chép ``acc`` của thẻ cha lên thẻ
        # con đang khai ``account`` là để thẻ cha thắng thẻ con.
        self.assertEqual({}, missing_from_parent({"account": "acc16"}, {"acc": "acc32"}))
        self.assertEqual({}, missing_from_parent({"template": "OR_1"}, {"copysku": "OR_2"}))
        self.assertEqual({}, missing_from_parent({"product_type": "khan"}, {"product": "bom"}))

    def test_what_belongs_to_one_card_only_never_comes_down(self) -> None:
        # Mỗi thẻ một mã: chép ``sku`` xuống là cả cụm trùng mã. ``action_1:
        # idea`` chép xuống là biến mỗi thẻ con thành một thẻ Idea tự đẻ con.
        parent = {
            "sku": "OR_18_000",
            "ma_sku": "OR_18_000",
            "ten_cu": "Idea 7",
            "fatheridea": "TASK-2026-01000",
            "parent_task": "TASK-2026-01000",
            "action_1": "idea",
            "action": "listing",
            "fulfillment": "FBM",
        }

        self.assertEqual({"fulfillment": "FBM"}, missing_from_parent({}, parent))

    def test_system_keys_never_come_down(self) -> None:
        self.assertEqual({}, missing_from_parent({}, {"_task": "TASK-2026-05384", "_status": "Open"}))

    def test_nothing_to_write_when_the_child_already_has_it_all(self) -> None:
        child = dict(self.PARENT)

        self.assertEqual({}, missing_from_parent(child, self.PARENT))


class OneAgentTwoKindsOfCardTests(unittest.TestCase):
    """The dispatch this repo needs: image card or listing card, from ``meta``.

    Both shapes below are copied off real cards, not invented.  The image card
    is what the *Thuộc tính* panel holds on an idea card in this repo; the
    listing card is what the Etsy half writes.
    """

    IMAGE_CARD = {"meta": "sku:\nproduct: khan tay\nfatheridea:\n"}
    LISTING_CARD = {"meta": "action_1: listing\nacc: acc32\n"}

    def test_an_image_card_is_not_mistaken_for_a_listing(self) -> None:
        meta = task_meta(self.IMAGE_CARD)

        self.assertFalse(meta.is_listing)
        self.assertEqual([], meta.actions)
        self.assertEqual("khan tay", meta.get("product"))

    def test_a_card_declaring_the_product_as_product_type_is_read(self) -> None:
        # Trên bảng thật người ta khai bằng ``product_type``, không phải
        # ``product``. Đọc sót chữ này thì thẻ coi như không khai sản phẩm,
        # bot rơi về đoán theo tên thẻ và tên bảng — im lặng, không báo lỗi.
        meta = task_meta({"meta": "sku:\nproduct_type: Ornament Theu Tron\nfatheridea:\n"})

        self.assertEqual("Ornament Theu Tron", meta.product)

    def test_every_spelling_the_panel_has_used_for_the_product_is_read(self) -> None:
        for spelling in ("product", "san_pham", "product_name", "product_type", "loai_san_pham"):
            with self.subTest(spelling=spelling):
                self.assertEqual(
                    "khan tay", task_meta({"meta": f"{spelling}: khan tay"}).product
                )

    def test_product_wins_over_product_type_when_a_card_carries_both(self) -> None:
        # ``product`` là chữ người ta gõ có chủ đích cho đúng thẻ này; kiểu
        # hàng chỉ là chỗ dựa khi không có nó.
        meta = task_meta({"meta": "product: khan tay\nproduct_type: Ornament\n"})

        self.assertEqual("khan tay", meta.product)

    def test_an_image_card_declares_nothing_so_it_keeps_its_old_behaviour(self) -> None:
        # The whole safety of putting both halves on one agent rests here: a
        # card that names no action must read as "carry on", never as "reject".
        self.assertFalse(task_meta(self.IMAGE_CARD).declares_actions)

    def test_a_listing_card_is_recognised_and_names_its_account(self) -> None:
        meta = task_meta(self.LISTING_CARD)

        self.assertTrue(meta.is_listing)
        self.assertEqual("acc32", meta.account_id)

    def test_every_spelling_the_panel_has_used_for_listing_is_recognised(self) -> None:
        for spelling in ("listing", "Listing Etsy", "listing-etsy", "dang listing", "LEN_LISTING"):
            with self.subTest(spelling=spelling):
                self.assertTrue(task_meta({"meta": f"action_1: {spelling}"}).is_listing)

    def test_normalising_is_what_makes_those_spellings_meet(self) -> None:
        self.assertEqual("etsy_listing", normalize_action("Etsy Listing"))
        self.assertEqual("etsy_listing", normalize_action(" etsy-listing "))
        self.assertIn(normalize_action("Listing"), LISTING_ACTIONS)

    def test_a_card_asking_for_other_work_is_not_a_listing_but_still_speaks(self) -> None:
        meta = task_meta({"meta": "action_1: watermark"})

        self.assertFalse(meta.is_listing)
        self.assertTrue(meta.declares_actions)

    def test_a_listing_child_of_an_image_parent_keeps_its_own_action(self) -> None:
        merged = inherit(task_meta(self.LISTING_CARD), task_meta(self.IMAGE_CARD))

        self.assertTrue(merged.is_listing)
        self.assertEqual("khan tay", merged.get("product"))


class ListingActionAccentSpellingTests(unittest.TestCase):
    """PRD list tự động lên Etsy, T4: chữ có dấu người Việt gõ vẫn là listing.

    ``LISTING_ACTIONS`` đã có ``dang_listing``, ``len_listing`` — nhưng
    ``normalize_action`` không bỏ dấu, nên ``đăng listing`` (chữ người ta gõ
    thật) thành ``đăng_listing`` và không khớp. Thẻ đứng im, không lỗi.
    """

    def test_accented_vietnamese_spellings_are_listing(self) -> None:
        for spelling in ("đăng listing", "Đăng Listing", "lên listing", "LÊN LISTING"):
            with self.subTest(spelling=spelling):
                self.assertTrue(
                    task_meta({"meta": f"action_1: {spelling}"}).is_listing,
                    f"{spelling!r} là chữ người dùng gõ trên panel; normalize_action giữ "
                    "nguyên dấu nên không khớp LISTING_ACTIONS — thẻ không được nhận là listing",
                )

    def test_normalising_strips_accents_the_same_way_compact_status_does(self) -> None:
        self.assertEqual("dang_listing", normalize_action("đăng listing"),
                         "phải bỏ dấu (đ→d rồi NFD) như agent_bot.compact_status")
        self.assertEqual("len_listing", normalize_action("lên listing"))

    def test_parentheses_and_punctuation_do_not_break_the_match(self) -> None:
        self.assertEqual("listing_etsy", normalize_action("Listing (Etsy)"),
                         "dấu ngoặc phải bị bỏ, không dính vào chữ")
        self.assertTrue(task_meta({"meta": "action_1: Listing (Etsy)"}).is_listing)

    def test_the_old_spellings_still_meet_and_keys_are_untouched(self) -> None:
        # Chốt chặn: không được đổi cách đọc KHOÁ, chỉ đổi cách đọc giá trị action.
        self.assertEqual("etsy_listing", normalize_action("Etsy Listing"))
        self.assertEqual("etsy_listing", normalize_action(" etsy-listing "))
        meta = task_meta({"meta": "action_1: đăng listing\nacc: acc32"})
        self.assertEqual("acc32", meta.account_id)
        self.assertFalse(task_meta({"meta": "action_1: watermark"}).is_listing)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
