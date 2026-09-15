from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from flow_web.agent_brain import BrainVerdict
from flow_web.agent_bot import (
    _RateLimiter,
    AgentBot,
    AgentBotConfig,
    AgentBotError,
    AgentBotState,
    card_is_in_source_column,
    card_stage,
    COLUMN_NOTE_MARK,
    compact_status,
    count_card_images,
    has_hidden_files,
    count_decisions,
    DECISION_DELETE,
    DECISION_KEEP,
    DECISION_PENDING,
    DEFAULT_MAX_COLUMN_ALERTS,
    is_idea_card,
    is_listing_card,
    is_review_post,
    iter_review_posts,
    iter_tree_nodes,
    META_INHERIT_PER_SCAN,
    build_sku_fast_lane,
    sku_fill_is_due,
    task_has_agent,
    vote_decision,
)
from flow_web.erp_meta import task_meta
from flow_web import pipeline
from flow_web.sku import SkuFastLaneConfig, cards_missing_sku


BOT = "agent-kin-test-agent@bots.hvg.internal"


def comment(
    name: str,
    *,
    mine: int = 1,
    like: int = 0,
    dislike: int = 0,
    content: str = "[FLOW_V2_REVIEW job#0] Ảnh 1/2 chờ duyệt",
    attachments: List[Dict[str, Any]] | None = None,
    replies: List[Dict[str, Any]] | None = None,
    owner: str = BOT,
) -> Dict[str, Any]:
    """One comment shaped the way ``taskFull`` really returns them."""
    return {
        "name": name,
        "owner": owner,
        "is_bot": 1 if mine else 0,
        "mine": mine,
        "content": content,
        "like_count": like,
        "dislike_count": dislike,
        "my_vote": "",
        "attachments": attachments if attachments is not None else [{"file_name": f"{name}.png"}],
        "replies": replies or [],
    }


def question(name: str, content: str, *, replies: List[Dict[str, Any]] | None = None, **overrides) -> Dict[str, Any]:
    """A comment a real person typed, shaped the way ``taskFull`` returns them."""
    node = {
        "name": name,
        "owner": "linh.duongthikhanh@havigroup.llc",
        "by_name": "Dương Thị Khánh Linh",
        "is_bot": 0,
        "mine": 0,
        "content": content,
        "meta": "",
        "mentions": [],
        "like_count": 0,
        "dislike_count": 0,
        "attachments": [],
        "replies": replies or [],
    }
    node.update(overrides)
    return node


def task_node(
    name: str,
    *,
    agents: List[str] = (),
    comments: List[Dict[str, Any]] = (),
    subtasks=(),
    child_total: int = 0,
    **extra: Any,
):
    node = {
        "name": name,
        "subject": name,
        "agents": [{"bot_user": item} for item in agents],
        "comments": list(comments),
        "subtasks": list(subtasks),
        "children": [{"name": item["name"]} for item in subtasks],
        "child_total": child_total or len(subtasks),
    }
    # ``status`` và ``meta`` chỉ vài bài kiểm cần tới, nhưng cột và khối Thuộc
    # tính là thứ luật chuyển cột đọc — nên chúng phải đặt được từ ngoài.
    node.update(extra)
    return node


class FakeClient:
    """Only the calls ``AgentBot`` makes, recording every write."""

    def __init__(
        self,
        projects: List[str],
        boards: Dict[str, List[Dict[str, Any]]],
        trees: Dict[str, Dict[str, Any]],
        columns: Dict[str, List[str]] | None = None,
    ):
        self._projects = projects
        self._boards = boards
        self._trees = trees
        self._columns = columns or {}
        self.board_reads: List[str] = []
        self.deleted: List[tuple[str, str]] = []
        self.comments: List[tuple[str, str, str, str]] = []
        self.agents_added: List[tuple[str, str]] = []

    def task_projects(self) -> List[Dict[str, Any]]:
        return [{"name": name, "project_name": name} for name in self._projects]

    def board_snapshot(self, project: str) -> tuple[List[Dict[str, Any]], tuple[str, ...]]:
        self.board_reads.append(project)
        tasks = self._boards.get(project, [])
        columns = self._columns.get(project)
        if columns is None:
            # Bảng thật bày cột trước rồi mới bày thẻ vào; bảng giả suy ngược
            # ra từ cột các thẻ đang đứng, để bài kiểm nào không quan tâm tới
            # tên cột thì khỏi phải khai chúng.
            columns = []
            for task in tasks:
                label = str(task.get("status") or "").strip()
                if label and label not in columns:
                    columns.append(label)
        return list(tasks), tuple(columns)

    def task_board(self, project: str) -> List[Dict[str, Any]]:
        return self.board_snapshot(project)[0]

    def task_full(self, name: str, depth: int = 1) -> Dict[str, Any]:
        return self._trees.get(name, {"root": {}})

    def add_comment(
        self, task: str, content: str, attachments=None, parent: str = "", meta: str = ""
    ) -> Dict[str, Any]:
        self.comments.append((task, content, parent, meta))
        return {"ok": True, "linked": len(attachments or [])}

    def delete_comment(self, task: str, comment_id: str) -> Dict[str, Any]:
        self.deleted.append((task, comment_id))
        return {"ok": True, "files": 1, "replies": 0}

    def add_task_agent(self, task: str, bot_user: str) -> Dict[str, Any]:
        self.agents_added.append((task, bot_user))
        return {"ok": True}


def build_bot(client: FakeClient, tmp: Path, **overrides) -> AgentBot:
    config = AgentBotConfig(token="t0ken", bot_user=BOT, **overrides)
    return AgentBot(config, client=client, state=AgentBotState.load(tmp / "state.json"))


class VoteDecisionTests(unittest.TestCase):
    """Reading 👍/👎 counts into keep, delete, or "nobody has said"."""

    def test_more_dislikes_deletes_and_more_likes_keeps(self) -> None:
        self.assertEqual(DECISION_DELETE, vote_decision({"like_count": 0, "dislike_count": 1}))
        self.assertEqual(DECISION_DELETE, vote_decision({"like_count": 1, "dislike_count": 3}))
        self.assertEqual(DECISION_KEEP, vote_decision({"like_count": 1, "dislike_count": 0}))
        self.assertEqual(DECISION_KEEP, vote_decision({"like_count": 4, "dislike_count": 2}))

    def test_nobody_voted_decides_nothing(self) -> None:
        self.assertEqual(DECISION_PENDING, vote_decision({}))
        self.assertEqual(DECISION_PENDING, vote_decision({"like_count": 0, "dislike_count": 0}))

    def test_a_tie_is_undecided_rather_than_a_delete(self) -> None:
        # Deleting is not undoable, so a split room must leave the image alone
        # instead of letting whoever clicked first win.
        self.assertEqual(DECISION_PENDING, vote_decision({"like_count": 1, "dislike_count": 1}))
        self.assertEqual(DECISION_PENDING, vote_decision({"like_count": 3, "dislike_count": 3}))


class ReviewPostTests(unittest.TestCase):
    """Which comments the bot may act on at all."""

    def test_only_the_bots_own_posts_count(self) -> None:
        # The bot cannot delete somebody else's comment, so claiming one as
        # its work would mean promising a 👎 that never removes anything.
        self.assertTrue(is_review_post(comment("a", mine=1)))
        self.assertFalse(is_review_post(comment("a", mine=0, owner="phong.hothanh@havigroup.llc")))

    def test_the_bots_own_result_notes_are_not_review_posts(self) -> None:
        # Otherwise the next pass would tidy away the note the last pass left.
        note = comment("n", content="[AGENT_BOT] 👎 Đã gỡ ảnh a.png khỏi thẻ.", attachments=[])
        self.assertFalse(is_review_post(note))
        legacy = comment("r", content="[FLOW_V2_REVIEW_RESULT] ✅ Đã duyệt ảnh 1.", attachments=[])
        self.assertFalse(is_review_post(legacy))

    def test_a_bare_chat_message_from_the_bot_is_not_a_review_post(self) -> None:
        self.assertFalse(is_review_post(comment("c", content="Đã nhận việc", attachments=[])))

    def test_a_wordless_review_post_is_recognised_by_its_meta(self) -> None:
        # Bình luận ảnh chờ duyệt không còn chữ nào; dấu ở ``meta`` là thứ duy
        # nhất nói nó là việc của bot khi hàng đính kèm đọc về rỗng.
        wordless = comment("w", content="\u200b", attachments=[])
        wordless["meta"] = "[FLOW_V2_REVIEW abc#3]"
        self.assertTrue(is_review_post(wordless))

    def test_the_legacy_review_tag_counts_even_without_an_attachment_row(self) -> None:
        # Images published through the old REST upload path show an empty
        # attachments list, but the tag still says what the comment is.
        tagged = comment("t", content="[FLOW_V2_REVIEW abc#3] Ảnh 4/12 chờ duyệt", attachments=[])
        self.assertTrue(is_review_post(tagged))


class TreeWalkTests(unittest.TestCase):
    """``taskFull`` hides the real subtree behind ``subtasks``."""

    def test_the_walk_follows_subtasks_not_the_thin_children_list(self) -> None:
        child = task_node("TASK-2", comments=[comment("c2")])
        root = task_node("TASK-1", subtasks=[child])
        # ``children`` carries no comments at all; walking it would find none.
        self.assertEqual(["TASK-1", "TASK-2"], [node["name"] for node in iter_tree_nodes(root)])

    def test_replies_are_reviewed_alongside_top_level_comments(self) -> None:
        parent = comment("p", content="Ảnh nguồn cho AI", attachments=[], replies=[comment("r")])
        node = task_node("TASK-1", comments=[parent])
        self.assertEqual(["r"], [item["name"] for item in iter_review_posts(node)])

    def test_agent_membership_is_read_off_the_task(self) -> None:
        self.assertTrue(task_has_agent(task_node("T", agents=[BOT]), BOT))
        self.assertFalse(task_has_agent(task_node("T", agents=["agent-other@bots.hvg.internal"]), BOT))
        self.assertFalse(task_has_agent(task_node("T"), BOT))


class CardStageTests(unittest.TestCase):
    """Đọc một thẻ thật thành mấy con số mà luật chuyển cột hỏi tới."""

    def test_the_votes_on_the_card_become_the_image_counts(self) -> None:
        node = task_node(
            "TASK-1",
            status="Open",
            comments=[comment("c1", like=1), comment("c2", dislike=1), comment("c3")],
        )

        stage = card_stage(node)

        self.assertEqual(3, stage.images_total)
        self.assertEqual(1, stage.images_kept)
        self.assertEqual(1, stage.images_pending)

    def test_the_column_comes_straight_off_the_card(self) -> None:
        self.assertEqual("Working", card_stage(task_node("T", status="Working")).status)

    def test_the_code_in_the_properties_block_counts_as_a_code(self) -> None:
        node = task_node("T", status="Working", meta="sku: HA_2_006\n")

        self.assertTrue(card_stage(node).has_sku)

    def test_a_card_with_no_properties_block_has_no_code(self) -> None:
        self.assertFalse(card_stage(task_node("T", status="Working")).has_sku)

    def test_a_listing_card_is_only_done_once_the_post_went_up(self) -> None:
        # Ảnh đã chốt mới là *đăng được*; đã đăng hay chưa thì chỉ sổ chạy việc
        # của bot biết, nên nó được truyền vào chứ không đọc từ thẻ.
        node = task_node(
            "T",
            status="Pending Review",
            meta="action_1: listing\n",
            comments=[comment("c1", like=1)],
        )

        self.assertFalse(card_stage(node).listing_done)
        self.assertTrue(card_stage(node, listed=True).listing_done)

    def test_a_listing_card_with_an_unvoted_image_is_not_done(self) -> None:
        node = task_node(
            "T",
            status="Pending Review",
            meta="action_1: listing\n",
            comments=[comment("c1", like=1), comment("c2")],
        )

        self.assertFalse(card_stage(node, listed=True).listing_done)

    def test_a_negative_missing_count_is_read_as_none_missing(self) -> None:
        self.assertEqual(0, card_stage(task_node("T"), cards_missing_sku=-3).cards_missing_sku)

    def test_a_child_card_with_no_machine_image_is_a_product_card(self) -> None:
        # Ảnh Trello nằm ở tệp đính kèm của thẻ, bình luận thì trống.
        node = task_node("T", status="Working", parent_task="P", attachment_count=3)

        self.assertTrue(card_stage(node).is_product)

    def test_a_persons_image_comment_leaves_it_a_product_card(self) -> None:
        # Bình luận ảnh của Linh 16:23 ngày 10/09 trên 05463: có ảnh, 0 phiếu.
        linh = question("q1", "", attachments=[{"file_name": "mau.jpg"}])
        stage = card_stage(task_node("T", status="Working", parent_task="P", comments=[linh]))

        self.assertTrue(stage.is_product)
        # Con số đếm ảnh không đổi: bot vẫn kể đúng trên thẻ đang có gì.
        self.assertEqual(1, stage.images_pending)

    def test_the_bots_review_image_makes_it_an_idea_card(self) -> None:
        node = task_node("T", status="Working", parent_task="P", comments=[comment("c1")])

        self.assertFalse(card_stage(node).is_product)

    def test_an_app_image_posted_under_a_persons_name_makes_it_an_idea_card(self) -> None:
        # ``service.py`` đăng ảnh dưới danh tính người thật, kèm dấu của app.
        foreign = comment(
            "c1", mine=0, owner="phong.hothanh@havigroup.llc", content="​", attachments=[]
        )
        foreign["meta"] = "[FLOW_V2_REVIEW job#2]"
        node = task_node("T", status="Working", parent_task="P", comments=[foreign])

        self.assertFalse(card_stage(node).is_product)

    def test_a_machine_image_in_a_reply_counts_too(self) -> None:
        parent = question("q1", "ảnh nguồn", replies=[comment("r1")])
        node = task_node("T", status="Working", parent_task="P", comments=[parent])

        self.assertFalse(card_stage(node).is_product)

    def test_the_bots_own_result_note_does_not_make_an_idea_card(self) -> None:
        note = comment("n1", content="[FLOW_V2_REVIEW_RESULT] ✅ Đã duyệt ảnh 1.", attachments=[])
        node = task_node("T", status="Working", parent_task="P", comments=[note])

        self.assertTrue(card_stage(node).is_product)

    def test_a_cluster_root_is_never_a_product_card(self) -> None:
        # Thẻ gốc không bao giờ mang mã. Coi nó là thẻ sản phẩm thì mỗi lượt
        # quét lại gọi đánh số một lần mà không ghi được gì.
        self.assertFalse(card_stage(task_node("T", status="Working")).is_product)


class SkuFillDueTests(unittest.TestCase):
    """Làn nhanh đọc cây trước khi đánh số: cụm 👎 hết thì chưa tới lượt."""

    @staticmethod
    def _tree(*children) -> Dict[str, Any]:
        return {"root": task_node("ROOT", status="Working", subtasks=list(children))}

    def test_a_product_card_just_dragged_over_is_due(self) -> None:
        child = task_node("C1", status="Working", parent_task="ROOT")

        self.assertTrue(sku_fill_is_due(self._tree(child), ["C1"]))

    def test_an_idea_card_waiting_on_votes_is_due_too(self) -> None:
        # Cổng làn nhanh gọi thẳng ``pipeline.needs_sku_fill`` nên luật mới —
        # kéo sang *Đang làm* là đủ — phải đi theo tới đây, không kẹt lại.
        child = task_node("C1", status="Working", parent_task="ROOT", comments=[comment("c1")])

        self.assertTrue(sku_fill_is_due(self._tree(child), ["C1"]))

    def test_an_idea_card_whose_images_were_all_binned_is_not_due(self) -> None:
        child = task_node(
            "C1", status="Working", parent_task="ROOT", comments=[comment("c1", dislike=1)]
        )

        self.assertFalse(sku_fill_is_due(self._tree(child), ["C1"]))

    def test_only_the_cards_asked_about_count(self) -> None:
        product = task_node("C1", status="Working", parent_task="ROOT")
        # C2 bị 👎 hết nên tự nó không tới lượt; hỏi riêng nó thì làn nhanh
        # phải lắc, chứ không được nhìn sang C1 rồi gật hộ.
        binned = task_node(
            "C2", status="Working", parent_task="ROOT", comments=[comment("c2", dislike=1)]
        )
        tree = self._tree(product, binned)

        self.assertFalse(sku_fill_is_due(tree, ["C2"]))
        self.assertTrue(sku_fill_is_due(tree, ["C2", "C1"]))

    def test_a_card_that_already_has_a_code_is_not_due(self) -> None:
        child = task_node("C1", status="Working", parent_task="ROOT", meta="sku: OL_1_049\n")

        self.assertFalse(sku_fill_is_due(self._tree(child), ["C1"]))


class BuildSkuFastLaneTests(unittest.TestCase):
    """Làn nhanh nối vào đúng client, sổ tạm dừng và bot_user của bot."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.filled: List[str] = []

    def _fill(self, root: str) -> Dict[str, Any]:
        self.filled.append(root)
        return {"written": [{"task_id": root}], "failed": []}

    def _bot(self, child: Dict[str, Any], **overrides) -> AgentBot:
        root = task_node("R", status="Working", agents=[BOT], subtasks=[child])
        rows = [
            {"name": "R", "parent_task": "", "status": "Working", "custom_sku": "",
             "agents": [{"bot_user": BOT}], "modified": "2026-09-11 16:00:00"},
            {"name": child["name"], "parent_task": "R", "status": child["status"], "custom_sku": "",
             "agents": [], "modified": "2026-09-11 16:00:00"},
        ]
        client = FakeClient(["PROJ-1"], {"PROJ-1": rows}, {"R": {"root": root}})
        bot = build_bot(client, self.tmp, **overrides)
        # Đi đúng đường code thật: chỉ ``scope_projects`` mới ghi phạm vi, và
        # nó ghi cả danh sách riêng của làn nhanh. Gán tay là bỏ qua chỗ đó.
        bot.scope_projects()
        return bot

    def test_the_lane_stays_home_unless_switched_on(self) -> None:
        bot = self._bot(task_node("C1", status="Working", parent_task="R"))

        self.assertIsNone(build_sku_fast_lane(bot, self._fill, SkuFastLaneConfig()))

    def test_a_dry_run_bot_does_not_number_on_the_side(self) -> None:
        bot = self._bot(task_node("C1", status="Working", parent_task="R"), dry_run=True)

        self.assertIsNone(build_sku_fast_lane(bot, self._fill, SkuFastLaneConfig(enabled=True)))

    def test_the_lane_numbers_a_product_card_on_the_bots_board(self) -> None:
        bot = self._bot(task_node("C1", status="Working", parent_task="R"))

        build_sku_fast_lane(bot, self._fill, SkuFastLaneConfig(enabled=True)).tick()

        self.assertEqual(["R"], self.filled)

    def test_the_lane_learns_the_token_ceiling_from_the_clients_limiter(self) -> None:
        # Hàng rào tự kiểm đọc trần bằng ``limiter.limit``. Lớp limiter nào đặt
        # tên khác là nó lặng lẽ coi như không có trần, và cấu hình sai lọt.
        bot = self._bot(task_node("C1", status="Working", parent_task="R"))
        bot.client._limiter = _RateLimiter(limit=123)

        lane = build_sku_fast_lane(bot, self._fill, SkuFastLaneConfig(enabled=True))

        self.assertEqual(123, lane._token_limit)

    def test_the_lane_leaves_a_paused_card_alone(self) -> None:
        bot = self._bot(task_node("C1", status="Working", parent_task="R"))
        bot.state.pause("R")

        build_sku_fast_lane(bot, self._fill, SkuFastLaneConfig(enabled=True)).tick()

        self.assertEqual([], self.filled)

    def test_an_idea_card_waiting_on_votes_goes_through_the_fast_lane(self) -> None:
        # Người kéo thẻ sang *Đang làm* rồi ngồi nhìn: làn nhanh cấp mã trong
        # vài giây, không bắt họ đợi hết một lượt quét 120 giây.
        child = task_node("C1", status="Working", parent_task="R", comments=[comment("c1")])
        bot = self._bot(child)

        build_sku_fast_lane(bot, self._fill, SkuFastLaneConfig(enabled=True)).tick()

        self.assertEqual(["R"], self.filled)

    def test_a_cluster_with_every_image_binned_is_left_to_the_slow_path(self) -> None:
        # 👎 hết thì không có gì để bán; làn nhanh không đụng tới.
        child = task_node(
            "C1", status="Working", parent_task="R", comments=[comment("c1", dislike=1)]
        )
        bot = self._bot(child)

        build_sku_fast_lane(bot, self._fill, SkuFastLaneConfig(enabled=True)).tick()

        self.assertEqual([], self.filled)


class CountDecisionsTests(unittest.TestCase):
    def test_the_three_buckets_add_up_to_every_image(self) -> None:
        node = task_node(
            "T",
            comments=[comment("c1", like=1), comment("c2", dislike=1), comment("c3")],
        )

        self.assertEqual((1, 1, 1), count_decisions(node))

    def test_a_card_with_no_images_counts_nothing(self) -> None:
        self.assertEqual((0, 0, 0), count_decisions(task_node("T")))


class PipelinePassTests(unittest.TestCase):
    """Bot nhìn ra việc *người* vừa làm xong và đẩy thẻ sang cột kế.

    Không lượt chạy nào của app đang mở khi ai đó bấm 👍 trên ERP, nên bot quét
    bảng là chỗ duy nhất nhận ra điều đó.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.asked: List[str] = []

    def _bot(self, **overrides) -> AgentBot:
        async def hook(task_id: str) -> Dict[str, Any]:
            self.asked.append(task_id)
            return {"task_id": task_id, "moved": True}

        bot = build_bot(FakeClient([], {}, {}), self.tmp, **overrides)
        bot.pipeline_hook = hook
        return bot

    def _run(self, bot: AgentBot, root: Dict[str, Any]) -> List[Dict[str, Any]]:
        return asyncio.run(bot.pipeline_pass({"root": root}))

    def test_a_reviewed_card_is_handed_to_the_hook(self) -> None:
        root = task_node("TASK-1", status="Open", comments=[comment("c1", like=1)])

        moves = self._run(self._bot(), root)

        self.assertEqual(["TASK-1"], self.asked)
        self.assertEqual([{"task": "TASK-1", "result": {"task_id": "TASK-1", "moved": True}}], moves)

    def test_a_card_still_waiting_for_a_vote_costs_no_request(self) -> None:
        # Gần như mọi thẻ trong mọi lượt quét đều ở trạng thái này; hỏi lại ERP
        # về từng thẻ ấy là tự ăn hết hạn mức 60 request mỗi phút.
        root = task_node("TASK-1", status="Open", comments=[comment("c1")])

        self.assertEqual([], self._run(self._bot(), root))
        self.assertEqual([], self.asked)

    def test_a_card_waiting_on_the_machine_to_number_it_is_handed_over(self) -> None:
        # *Đang làm* là cột bot có việc phải làm — điền mã. Thẻ chưa có mã thì
        # chưa có nước đi, nhưng đúng vì thế mới cần gọi hook.
        root = task_node("TASK-1", status="Working", comments=[comment("c1", like=1)])

        self._run(self._bot(), root)

        self.assertEqual(["TASK-1"], self.asked)

    def test_a_card_dragged_into_doing_is_handed_over_even_unvoted(self) -> None:
        # Thẻ kéo tay vào *Đang làm* khi ảnh chưa ai xem: chính cú kéo là cái
        # chốt, nên máy phải nhận việc điền mã.  Không lo vỡ hạn mức request —
        # chỉ thẻ ở *Đang làm* mà **trắng mã** mới được hỏi, và hỏi xong là nó
        # có mã, lượt sau thôi hỏi.  Thẻ ở *Cần làm* vẫn không tốn request nào
        # (xem ``test_a_card_still_waiting_for_a_vote_costs_no_request``).
        root = task_node("TASK-1", status="Working", comments=[comment("c1")])

        self._run(self._bot(), root)

        self.assertEqual(["TASK-1"], self.asked)

    def test_a_card_in_doing_with_every_image_binned_costs_no_request(self) -> None:
        # 👎 hết: idea tay trắng, chờ chạy lại ảnh chứ không chờ mã.
        root = task_node("TASK-1", status="Working", comments=[comment("c1", dislike=1)])

        self.assertEqual([], self._run(self._bot(), root))
        self.assertEqual([], self.asked)

    def test_a_product_card_dragged_into_doing_is_handed_over(self) -> None:
        # Thẻ con không có ảnh máy: ảnh Trello nằm ở tệp đính kèm. Người kéo
        # sang *Đang làm* là đã chốt, nên máy phải đánh số.
        child = task_node("TASK-2", status="Working", parent_task="TASK-1", attachment_count=3)
        root = task_node("TASK-1", status="Working", subtasks=[child])

        self._run(self._bot(), root)

        self.assertIn("TASK-2", self.asked)

    def test_a_finished_card_is_left_alone(self) -> None:
        root = task_node("TASK-1", status="Completed", comments=[comment("c1", like=1)])

        self.assertEqual([], self._run(self._bot(), root))
        self.assertEqual([], self.asked)

    def test_children_are_walked_not_just_the_root(self) -> None:
        # Ảnh nằm trên thẻ con, nên phán quyết 👍/👎 cũng ở đó.
        child = task_node("TASK-2", status="Open", comments=[comment("c1", like=1)])
        root = task_node("TASK-1", status="Open", subtasks=[child])

        self._run(self._bot(), root)

        self.assertIn("TASK-2", self.asked)

    def test_siblings_left_in_todo_are_not_counted_as_missing_codes(self) -> None:
        """Chốt đường nối ``cards_missing_sku(root)`` mà ``pipeline_pass`` đọc.

        Thẻ còn ở *Cần làm* chưa tới lượt cấp mã, nên không được đếm là
        "thiếu mã".  Đếm chúng vào thì con số này không bao giờ về 0 — và bất
        cứ ai đọc nó làm điều kiện sẽ giữ thẻ có mã đứng chờ vĩnh viễn những
        thẻ mà theo đúng thiết kế thì chưa được phát mã.
        """
        bot = self._bot(dry_run=True)
        sibling = task_node("TASK-3", status="Open")
        coded = task_node(
            "TASK-2", status="Working", meta="sku: KT_1_002\n",
            comments=[comment("c1", like=1)],
        )
        root = task_node(
            "TASK-1", status="Working", project_name="khăn tay",
            subtasks=[coded, sibling],
        )

        self.assertEqual(0, cards_missing_sku(root))

        moves = self._run(bot, root)

        self.assertEqual(
            [{"task": "TASK-2", "to": "Pending Review", "reason": "đã có mã SKU", "dry_run": True}],
            moves,
        )

    def test_a_ready_sibling_without_a_code_is_counted_but_blocks_nothing(self) -> None:
        """Thẻ đã sang *Đang làm* mà trắng mã thì ĐƯỢC đếm — máy còn việc và
        lượt quét phải gọi hook đánh số — nhưng không giữ chân thẻ anh em đã
        có mã: điều kiện "cả cụm đủ mã" đã bị gỡ khỏi luật cột.
        """
        bot = self._bot(dry_run=True)
        blank = task_node("TASK-3", status="Working", comments=[comment("c2", like=1)])
        coded = task_node(
            "TASK-2", status="Working", meta="sku: KT_1_002\n",
            comments=[comment("c1", like=1)],
        )
        root = task_node(
            "TASK-1", status="Working", project_name="khăn tay",
            subtasks=[coded, blank],
        )

        self.assertEqual(1, cards_missing_sku(root))

        moves = self._run(bot, root)

        self.assertEqual(
            [
                {"task": "TASK-2", "to": "Pending Review", "reason": "đã có mã SKU", "dry_run": True},
                {"task": "TASK-3", "to": "", "reason": "chưa điền được mã SKU", "dry_run": True},
            ],
            moves,
        )

    def test_a_paused_card_is_never_moved(self) -> None:
        # "Dừng" phải thắng cả suy đoán đúng luật, nếu không thì bảo bot dừng
        # hoá ra vô nghĩa.
        bot = self._bot()
        bot.state.pause("TASK-1")
        root = task_node("TASK-1", status="Open", comments=[comment("c1", like=1)])

        self.assertEqual([], self._run(bot, root))
        self.assertEqual([], self.asked)

    def test_pausing_the_root_pauses_its_children_too(self) -> None:
        bot = self._bot()
        bot.state.pause("TASK-1")
        child = task_node("TASK-2", status="Open", comments=[comment("c1", like=1)])
        root = task_node("TASK-1", status="Open", subtasks=[child])

        self.assertEqual([], self._run(bot, root))

    def test_a_dry_run_reports_the_move_without_making_it(self) -> None:
        bot = self._bot(dry_run=True)
        root = task_node("TASK-1", status="Open", comments=[comment("c1", like=1)])

        moves = self._run(bot, root)

        self.assertEqual([], self.asked)
        self.assertEqual("Working", moves[0]["to"])
        self.assertTrue(moves[0]["dry_run"])
        self.assertTrue(moves[0]["reason"])

    def test_a_blank_root_idea_never_holds_its_coded_children(self) -> None:
        """Thẻ idea cha trắng mã là ĐÚNG thiết kế, không phải thẻ "thiếu mã".

        Nó khai ``product:`` và giữ ảnh; mã thuộc về thẻ idea con.  Luật cũ
        trên bảng có tên coi thẻ gốc là idea chưa đánh số và giữ cả cụm lại —
        một cái chặn không bao giờ mở, vì máy không đời nào cấp mã cho thẻ
        gốc.  Thẻ con đã có mã phải đi tiếp bình thường.
        """
        bot = self._bot(dry_run=True)
        child = task_node(
            "TASK-2", status="Working", meta="sku: KT_1_002\n",
            project_name="khăn tay", comments=[comment("c1", like=1)],
        )
        root = task_node("TASK-1", status="Working", project_name="khăn tay", subtasks=[child])

        self.assertEqual(0, cards_missing_sku(root))

        moves = self._run(bot, root)

        self.assertEqual(
            [{"task": "TASK-2", "to": "Pending Review", "reason": "đã có mã SKU", "dry_run": True}],
            moves,
        )

    def test_a_root_that_declares_product_moves_its_coded_child(self) -> None:
        # Thẻ gốc khai ``product:`` là thẻ idea cha đúng nghĩa: không mang mã
        # và không vì thế mà giữ con.  Lý do phải nói về chính thẻ con —
        # "cả cụm đã có mã SKU" là câu của luật cũ, cụm giờ không còn là đơn
        # vị chuyển cột nữa.
        bot = self._bot(dry_run=True)
        child = task_node(
            "TASK-2", status="Working", meta="sku: KT_1_001\n",
            project_name="khăn tay", comments=[comment("c1", like=1)],
        )
        root = task_node(
            "TASK-1", status="Working", meta="product: khăn tay\n",
            project_name="khăn tay", subtasks=[child],
        )

        moves = self._run(bot, root)

        self.assertEqual("Pending Review", moves[0]["to"])
        self.assertEqual("đã có mã SKU", moves[0]["reason"])

    def test_with_no_hook_wired_up_nothing_happens(self) -> None:
        bot = build_bot(FakeClient([], {}, {}), self.tmp)
        root = task_node("TASK-1", status="Open", comments=[comment("c1", like=1)])

        self.assertEqual([], asyncio.run(bot.pipeline_pass({"root": root})))

    def test_a_hook_that_blows_up_does_not_stop_the_scan(self) -> None:
        # Hook là mã của app và nó nói chuyện với ERP qua mạng; một thẻ hỏng
        # không được kéo theo cả lượt quét.
        bot = self._bot()
        seen: List[str] = []

        async def hook(task_id: str) -> Dict[str, Any]:
            seen.append(task_id)
            if task_id == "TASK-1":
                raise RuntimeError("ERP trả 500")
            return {"moved": True}

        bot.pipeline_hook = hook
        child = task_node("TASK-2", status="Open", comments=[comment("c1", like=1)])
        root = task_node("TASK-1", status="Open", subtasks=[child], comments=[comment("c2", like=1)])

        moves = self._run(bot, root)

        self.assertEqual(["TASK-1", "TASK-2"], seen)
        self.assertEqual("ERP trả 500", moves[0]["error"])
        self.assertEqual({"moved": True}, moves[1]["result"])

    def test_a_card_with_no_id_is_skipped(self) -> None:
        self.assertEqual([], self._run(self._bot(), task_node("", status="Open")))


class UnknownColumnAlertTests(unittest.TestCase):
    """Thêm bot vào một bảng đặt tên cột khác thì bot phải nói ra.

    Không có bước này, cái bảng ấy đọc y hệt một bảng đang chạy tốt: ảnh vẫn
    được tạo, vẫn đăng lên chờ duyệt — nhưng không thẻ nào nhúc nhích được và
    sẽ không bao giờ nhúc nhích, mà cũng chẳng có lỗi nào để lần ra.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _bot(self, cot: str = "Backlog", **overrides) -> AgentBot:
        the = task_node("TASK-1", agents=[BOT], status=cot, child_total=1)
        client = FakeClient(["PROJ-1"], {"PROJ-1": [the]}, {}, columns={"PROJ-1": [cot]})
        return build_bot(client, self.tmp, **overrides)

    def _quet(self, bot: AgentBot) -> List[Dict[str, Any]]:
        bot.candidate_tasks(["PROJ-1"], BOT)
        return bot.column_pass()

    def test_a_stray_column_gets_said_out_loud_on_the_stranded_card(self) -> None:
        bot = self._bot()
        nhac = self._quet(bot)

        self.assertEqual([{"task": "TASK-1", "column": "Backlog"}], nhac)
        task, content, _, meta = bot.client.comments[0]
        self.assertEqual("TASK-1", task)
        self.assertEqual(COLUMN_NOTE_MARK, meta)
        # Nguyên văn tên cột, để người đọc dò được nó trên bảng của họ.
        self.assertIn("Backlog", content)
        # Và đúng lời khuyên ấy, không phải một bản viết lại.
        self.assertEqual(pipeline.column_help(["Backlog"]), content)

    def test_a_board_named_the_way_the_rules_expect_says_nothing(self) -> None:
        bot = self._bot("Working")
        self.assertEqual([], self._quet(bot))
        self.assertEqual([], bot.client.comments)

    def test_the_same_card_in_the_same_column_is_only_told_once(self) -> None:
        # Quét mỗi hai phút; nhắc mỗi lượt thì lời nhắc thành tiếng ồn, và
        # tiếng ồn thì người ta tắt bot chứ không sửa bảng.
        bot = self._bot()
        self._quet(bot)
        self.assertEqual([], self._quet(bot))
        self.assertEqual(1, len(bot.client.comments))

    def test_dragging_the_card_to_another_strange_column_is_worth_saying_again(self) -> None:
        bot = self._bot()
        self._quet(bot)

        bot.client._boards["PROJ-1"][0]["status"] = "Chờ khách duyệt"
        bot.client._columns["PROJ-1"] = ["Chờ khách duyệt"]
        nhac = self._quet(bot)

        self.assertEqual(["Chờ khách duyệt"], [item["column"] for item in nhac])
        self.assertIn("Chờ khách duyệt", bot.client.comments[1][1])

    def test_a_dry_run_reports_the_warning_without_writing_it(self) -> None:
        bot = self._bot(dry_run=True)
        nhac = self._quet(bot)

        self.assertEqual([{"task": "TASK-1", "column": "Backlog", "dry_run": True}], nhac)
        self.assertEqual([], bot.client.comments)
        # Và không ghi sổ: ghi rồi thì lượt chạy thật sau đó tưởng đã nhắc, và
        # lời nhắc không bao giờ tới nơi.
        self.assertFalse(bot.state.already_warned_column("TASK-1", "Backlog"))

    def test_a_post_erp_refused_is_retried_next_pass(self) -> None:
        bot = self._bot()

        def tu_choi(*a, **k):
            raise AgentBotError("ERP trả 500")

        bot.client.add_comment = tu_choi
        self.assertEqual([], self._quet(bot))
        self.assertFalse(bot.state.already_warned_column("TASK-1", "Backlog"))

        del bot.client.add_comment
        self.assertEqual(["Backlog"], [item["column"] for item in self._quet(bot)])

    def test_the_warning_can_be_switched_off_entirely(self) -> None:
        bot = self._bot(column_alert=False)
        self.assertEqual([], self._quet(bot))
        self.assertEqual([], bot.client.comments)

    def test_one_badly_named_board_does_not_get_a_comment_on_every_card(self) -> None:
        # Một bảng ba mươi thẻ đặt sai tên cột không được biến thành ba mươi
        # bình luận giống hệt nhau; một hai thẻ là đủ để người ta nhìn thấy.
        the = [
            task_node(f"TASK-{n}", agents=[BOT], status="Backlog", child_total=1)
            for n in range(1, 8)
        ]
        client = FakeClient(["PROJ-1"], {"PROJ-1": the}, {}, columns={"PROJ-1": ["Backlog"]})
        bot = build_bot(client, self.tmp, max_column_alerts=2)
        self.assertEqual(2, len(self._quet(bot)))

    def test_a_stray_column_is_reported_even_when_it_leaves_no_work_to_do(self) -> None:
        """Đúng cái bảng cần nghe nhất là cái bảng không sinh ra việc nào.

        ``run_once`` gọi lượt này *trước* chỗ thoát sớm vì không có thẻ nào:
        bảng đặt sai tên cột thường trả về đúng không thẻ, và nếu lời nhắc đi
        sau chỗ thoát thì nó không bao giờ được nói ra.
        """
        # Thẻ nằm ngoài cột nguồn thì không lọt vào danh sách việc — nhưng nó
        # nằm ngoài *chính vì* cột của nó không đọc được, nên đó đúng là thẻ
        # cần nghe lời nhắc nhất.
        the = task_node("TASK-1", status="Backlog", child_total=1)
        client = FakeClient(["PROJ-1"], {"PROJ-1": [the]}, {}, columns={"PROJ-1": ["Backlog"]})
        bot = build_bot(client, self.tmp, source_statuses=("Working",))
        self.assertEqual([], bot.candidate_tasks(["PROJ-1"], BOT))
        self.assertEqual(["Backlog"], [item["column"] for item in bot.column_pass()])

    def test_the_warning_survives_a_restart_of_the_bot(self) -> None:
        bot = self._bot()
        self._quet(bot)
        bot.state.save()

        the = task_node("TASK-1", agents=[BOT], status="Backlog", child_total=1)
        client = FakeClient(["PROJ-1"], {"PROJ-1": [the]}, {}, columns={"PROJ-1": ["Backlog"]})
        restarted = build_bot(client, self.tmp)
        self.assertEqual([], self._quet(restarted))
        self.assertEqual([], client.comments)


class JanitorTests(unittest.TestCase):
    """👎 takes the image off the card, 👍 leaves it there."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _tree(self, *comments: Dict[str, Any]) -> Dict[str, Any]:
        return {"root": task_node("TASK-1", agents=[BOT], comments=list(comments))}

    def test_a_disliked_image_is_deleted_and_nothing_is_written_in_its_place(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        applied = bot.janitor_pass(self._tree(comment("c1", dislike=2)))

        self.assertEqual([{"decision": DECISION_DELETE, "comment": "c1"}], [
            {"decision": item["decision"], "comment": item["comment"]} for item in applied
        ])
        self.assertEqual([("TASK-1", "c1")], client.deleted)
        # The bot used to leave a "đã gỡ" note per image, which on a card of a
        # dozen images became the thing the reviewer scrolled past. The record
        # belongs in the app log, not on the card.
        self.assertEqual([], client.comments)

    def test_a_liked_image_stays_on_the_card(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        applied = bot.janitor_pass(self._tree(comment("c1", like=1)))

        self.assertEqual([DECISION_KEEP], [item["decision"] for item in applied])
        self.assertEqual([], client.deleted)

    def test_an_unvoted_image_is_left_completely_alone(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        self.assertEqual([], bot.janitor_pass(self._tree(comment("c1"))))
        self.assertEqual([], client.deleted)
        self.assertEqual([], client.comments)

    def test_a_decision_is_applied_once_even_if_the_card_still_shows_it(self) -> None:
        # The card is read again every poll, and a kept image keeps its 👍
        # forever: without the ledger the bot would re-decide it every pass.
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        tree = self._tree(comment("c1", like=1))
        self.assertEqual(1, len(bot.janitor_pass(tree)))
        self.assertEqual([], bot.janitor_pass(tree))
        self.assertEqual([], client.comments)

    def test_a_ledger_written_to_disk_survives_a_restart(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        bot.janitor_pass(self._tree(comment("c1", dislike=1)))
        bot.state.save()

        restarted = build_bot(FakeClient([], {}, {}), self.tmp)
        self.assertTrue(restarted.state.already_handled("c1"))

    def test_dry_run_reports_the_decision_without_touching_the_card(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp, dry_run=True)
        applied = bot.janitor_pass(self._tree(comment("c1", dislike=1)))

        self.assertEqual([DECISION_DELETE], [item["decision"] for item in applied])
        self.assertEqual([], client.deleted)
        self.assertEqual([], client.comments)
        # And it must not be recorded, or the real run would skip it.
        self.assertFalse(bot.state.already_handled("c1"))

    def test_a_failed_delete_is_not_recorded_as_done(self) -> None:
        class Refusing(FakeClient):
            def delete_comment(self, task: str, comment_id: str):
                raise AgentBotError("ERP từ chối xoá")

        client = Refusing([], {}, {})
        bot = build_bot(client, self.tmp)
        self.assertEqual([], bot.janitor_pass(self._tree(comment("c1", dislike=1))))
        # Next pass must try again rather than leave a disliked image up.
        self.assertFalse(bot.state.already_handled("c1"))

    def test_images_on_child_cards_are_cleaned_too(self) -> None:
        # One card per idea: the images live on the children, not the parent.
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        child = task_node("TASK-2", comments=[comment("c2", dislike=1)])
        tree = {"root": task_node("TASK-1", agents=[BOT], subtasks=[child])}
        bot.janitor_pass(tree)
        self.assertEqual([("TASK-2", "c2")], client.deleted)


class AppKeyReviewDeletionTests(unittest.TestCase):
    """Ảnh review của app bị 👎 thì bot nhờ chính app gỡ an toàn.

    App là tác giả của ảnh review nên chỉ API key của app mới xoá được. Bot chỉ
    chuyển mã thẻ và mã comment; app phải đọc lại ERP và tự chốt đúng ảnh review
    vẫn đang nghiêng 👎 trước khi ghi. Đừng biến nhánh này thành xoá thẳng bằng
    token bot, và cũng đừng mở rộng nó sang ảnh người dùng tự đính kèm.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _foreign(self, name: str, **kwargs: Any) -> Dict[str, Any]:
        return comment(name, mine=0, owner="phong.hothanh@havigroup.llc", **kwargs)

    def test_anh_review_cua_app_bi_ghet_thi_bot_nho_app_go_bang_khoa_app(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        requests: List[tuple[str, str]] = []

        def app_delete(task_id: str, comment_id: str) -> bool:
            requests.append((task_id, comment_id))
            return True

        bot.delete_review_hook = app_delete
        tree = {"root": task_node("TASK-1", agents=[BOT],
                                  comments=[self._foreign("c1", dislike=3),
                                            self._foreign("c2", dislike=2)])}
        with self.assertNoLogs("flow_web.agent_bot", level="WARNING"):
            applied = bot.janitor_pass(tree)

        self.assertEqual([("TASK-1", "c1"), ("TASK-1", "c2")], requests)
        self.assertEqual([], client.deleted, "token bot không được xoá ảnh do app đăng")
        self.assertEqual([DECISION_DELETE, DECISION_DELETE], [item["decision"] for item in applied])
        self.assertTrue(bot.state.already_handled("c1"))
        self.assertTrue(bot.state.already_handled("c2"))

    def test_the_khong_co_anh_la_thi_khong_canh_bao_gi(self) -> None:
        # Cảnh báo nào cũng kêu thì không còn là cảnh báo. Ảnh của chính bot,
        # kể cả chưa ai bỏ phiếu, không được chạm vào dòng log này.
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        tree = {"root": task_node("TASK-1", agents=[BOT],
                                  comments=[comment("c1"), comment("c2", like=1)])}
        with self.assertNoLogs("flow_web.agent_bot", level="WARNING"):
            bot.janitor_pass(tree)

    def test_anh_cua_app_chua_ai_bo_phieu_thi_khong_go(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        tree = {"root": task_node("TASK-1", agents=[BOT], comments=[self._foreign("c1")])}
        with self.assertNoLogs("flow_web.agent_bot", level="WARNING"):
            bot.janitor_pass(tree)

    def test_anh_cua_app_duoc_giu_lai_thi_khong_go(self) -> None:
        # 👍 nghĩa là giữ, mà giữ thì bot chẳng phải làm gì — ảnh của người
        # khác được duyệt giữ **không** phải việc mắc kẹt. Kêu ở đây là kêu vô
        # cớ, và vì thẻ ấy nằm lại mãi nên nó kêu mỗi lượt quét cho tới hết
        # đời thẻ. Đúng cách dạy người đọc bỏ qua dòng cảnh báo này.
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        tree = {"root": task_node("TASK-1", agents=[BOT],
                                  comments=[self._foreign("c1", like=4),
                                            self._foreign("c2", like=1)])}
        with self.assertNoLogs("flow_web.agent_bot", level="WARNING"):
            bot.janitor_pass(tree)

    def test_app_tu_choi_thi_bot_khong_ghi_so_de_luot_sau_thu_lai(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        calls: List[tuple[str, str]] = []

        def app_refuses(task_id: str, comment_id: str) -> bool:
            calls.append((task_id, comment_id))
            return False

        bot.delete_review_hook = app_refuses
        tree = {"root": task_node("TASK-1", agents=[BOT], comments=[self._foreign("c1", dislike=2)])}

        self.assertEqual([], bot.janitor_pass(tree))
        self.assertEqual([("TASK-1", "c1")], calls)
        self.assertFalse(bot.state.already_handled("c1"))

    def test_anh_nguoi_dung_tu_dinh_kem_du_bi_ghet_cung_khong_duoc_chuyen_cho_app_xoa(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        calls: List[tuple[str, str]] = []
        bot.delete_review_hook = lambda task_id, comment_id: calls.append((task_id, comment_id)) or True
        personal_photo = self._foreign("photo", dislike=2, content="Ảnh mẫu khách vừa thêm")

        self.assertEqual([], bot.janitor_pass({"root": task_node("TASK-1", comments=[personal_photo])}))
        self.assertEqual([], calls)
        self.assertFalse(bot.state.already_handled("photo"))

    def test_note_ket_qua_khong_duoc_gui_cho_app_xoa_du_co_anh_va_bi_ghet(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        calls: List[tuple[str, str]] = []
        bot.delete_review_hook = lambda task_id, comment_id: calls.append((task_id, comment_id)) or True
        result_note = self._foreign("result", dislike=2, content="")
        result_note["meta"] = "[FLOW_V2_REVIEW_RESULT] ảnh đã xử lý"

        self.assertEqual([], bot.janitor_pass({"root": task_node("TASK-1", comments=[result_note])}))
        self.assertEqual([], calls)
        self.assertFalse(bot.state.already_handled("result"))

    def test_publish_image_van_chua_duoc_noi_nhung_app_da_co_duong_go_an_toan(self) -> None:
        # Đường đăng bot vẫn chưa dùng; thay vì đổi tác giả của mọi ảnh review,
        # bot gọi app là chủ comment. Tài liệu phải nói đúng đường đang sống.
        root = Path(__file__).resolve().parents[1]
        goi = []
        for path in sorted(root.glob("flow_web/*.py")) + sorted(root.glob("scripts/*.py")):
            if path.name == "agent_bot.py":
                continue
            if "publish_image" in path.read_text(encoding="utf-8"):
                goi.append(str(path.relative_to(root)))
        self.assertEqual(
            [], goi,
            "publish_image đã được nối — hãy cập nhật README mục 4.1e và bỏ dòng "
            "cảnh báo 'chưa nối' trong janitor_pass cho khớp thực tế")

        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("khoá của app", readme,
                      "README phải nói rõ app là bên gỡ ảnh review của chính mình")


class ScopeTests(unittest.TestCase):
    """The ERP decides the scope, not the config file."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_no_configured_projects_means_every_project_the_bot_can_see(self) -> None:
        client = FakeClient(["PROJ-0013", "PROJ-0049"], {}, {})
        bot = build_bot(client, self.tmp)
        self.assertEqual(["PROJ-0013", "PROJ-0049"], bot.scope_projects())

    def test_a_configured_project_the_bot_cannot_see_is_dropped(self) -> None:
        # Being named in .env does not grant Project User membership, and
        # pretending it does would only produce permission errors later.
        client = FakeClient(["PROJ-0013"], {}, {})
        bot = build_bot(client, self.tmp, projects=("PROJ-0013", "PROJ-9999"))
        self.assertEqual(["PROJ-0013"], bot.scope_projects())

    def test_the_scope_is_written_down_for_the_rest_of_the_app(self) -> None:
        # Hàng rào dự án của app đọc đúng sổ này, nên "thêm bot vào board" là
        # thao tác duy nhất — không phải khai lại board ở .env.local.
        client = FakeClient(["PROJ-0013", "PROJ-0049"], {}, {})
        bot = build_bot(client, self.tmp)
        bot.scope_projects()
        self.assertEqual(["PROJ-0013", "PROJ-0049"], bot.state.projects)

    def test_a_narrowed_scope_is_what_gets_written_down(self) -> None:
        client = FakeClient(["PROJ-0013", "PROJ-0049"], {}, {})
        bot = build_bot(client, self.tmp, projects=("PROJ-0013",))
        bot.scope_projects()
        self.assertEqual(["PROJ-0013"], bot.state.projects)

    def test_the_scope_survives_a_restart(self) -> None:
        # App vừa bật lại thì bot còn ngủ hết một chu kỳ mới quét; hàng rào
        # phải biết ngay chứ không đợi hai phút.
        client = FakeClient(["PROJ-0013", "PROJ-0049"], {}, {})
        bot = build_bot(client, self.tmp)
        bot.scope_projects()
        bot.state.save()
        self.assertEqual(
            ["PROJ-0013", "PROJ-0049"], AgentBotState.load(self.tmp / "state.json").projects
        )
        self.assertEqual(
            ["PROJ-0013", "PROJ-0049"], AgentBotState.load(self.tmp / "state.json").fast_lane_projects
        )

    def test_completed_projects_stay_in_the_scan_but_leave_the_fast_lane(self) -> None:
        client = FakeClient(["PROJ-OPEN", "PROJ-DONE"], {}, {})
        client.task_projects = lambda: [
            {"name": "PROJ-OPEN", "project_name": "Đang mở", "status": "Open", "task_count": 1},
            {"name": "PROJ-DONE", "project_name": "Đã xong", "status": "Completed", "task_count": 1},
        ]
        bot = build_bot(client, self.tmp)

        self.assertEqual(["PROJ-OPEN", "PROJ-DONE"], bot.scope_projects())
        self.assertEqual(["PROJ-OPEN", "PROJ-DONE"], bot.state.projects)
        self.assertEqual(["PROJ-OPEN"], bot.state.fast_lane_projects)

    def test_a_board_the_bot_was_dropped_from_disappears_from_the_note(self) -> None:
        client = FakeClient(["PROJ-0013"], {}, {})
        bot = build_bot(client, self.tmp)
        bot.state.projects = ["PROJ-0013", "PROJ-0049"]
        bot.scope_projects()
        self.assertEqual(["PROJ-0013"], bot.state.projects)


class RunOnceTests(unittest.TestCase):
    """One full pass: find the attached cards, judge them, run them."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _client(self) -> FakeClient:
        mine = {"name": "TASK-1", "agents": [{"bot_user": BOT}], "child_total": 1}
        theirs = {"name": "TASK-9", "agents": [{"bot_user": "agent-other@bots.hvg.internal"}], "child_total": 0}
        child = task_node("TASK-2", comments=[comment("c1", dislike=1), comment("c2", like=1)])
        return FakeClient(
            ["PROJ-0049"],
            {"PROJ-0049": [mine, theirs]},
            {"TASK-1": {"root": task_node("TASK-1", agents=[BOT], subtasks=[child])}},
        )

    def test_only_the_cards_this_bot_is_attached_to_are_touched(self) -> None:
        client = self._client()
        bot = build_bot(client, self.tmp, autorun=False)
        summary = asyncio.run(bot.run_once())

        self.assertEqual(["TASK-1"], summary["tasks"])
        self.assertEqual(1, summary["deleted"])
        self.assertEqual(1, summary["kept"])
        self.assertEqual([("TASK-2", "c1")], client.deleted)

    def test_the_attached_parent_card_is_handed_to_the_run_hook(self) -> None:
        client = self._client()
        seen: List[str] = []

        async def hook(task_id: str) -> Dict[str, Any]:
            seen.append(task_id)
            return {"queued": [{"task_id": "TASK-2"}]}

        bot = build_bot(client, self.tmp)
        bot.autorun_hook = hook
        summary = asyncio.run(bot.run_once())

        self.assertEqual(["TASK-1"], seen)
        self.assertEqual([{"task": "TASK-1", "result": {"queued": [{"task_id": "TASK-2"}]}}], summary["autorun"])

    def test_the_same_card_is_not_re_run_inside_the_cooldown(self) -> None:
        client = self._client()
        calls: List[str] = []

        async def hook(task_id: str) -> Dict[str, Any]:
            calls.append(task_id)
            return {}

        bot = build_bot(client, self.tmp, autorun_cooldown_seconds=900)
        bot.autorun_hook = hook
        asyncio.run(bot.run_once())
        asyncio.run(bot.run_once())
        self.assertEqual(["TASK-1"], calls)

    def test_a_hook_that_raises_does_not_break_the_pass(self) -> None:
        client = self._client()

        async def hook(task_id: str) -> Dict[str, Any]:
            raise RuntimeError("Flow đang bận")

        bot = build_bot(client, self.tmp)
        bot.autorun_hook = hook
        summary = asyncio.run(bot.run_once())
        self.assertEqual("Flow đang bận", summary["autorun"][0]["error"])
        # The janitor still did its half of the job.
        self.assertEqual(1, summary["deleted"])

    def test_a_strangely_named_column_is_reported_in_the_pass_summary(self) -> None:
        # Lời nhắc phải đi ra tới bản tóm tắt: đó là thứ trang Agent Bot và
        # người đọc log nhìn thấy, và là chỗ duy nhất họ biết bảng có vấn đề.
        client = self._client()
        client._boards["PROJ-0049"][0]["status"] = "Backlog"
        client._columns["PROJ-0049"] = ["Backlog"]
        bot = build_bot(client, self.tmp, autorun=False)
        summary = asyncio.run(bot.run_once())

        self.assertEqual([{"task": "TASK-1", "column": "Backlog"}], summary["columns"])

    def test_a_board_named_the_way_the_rules_expect_reports_nothing(self) -> None:
        client = self._client()
        client._columns["PROJ-0049"] = ["Open", "Working", "Đang review", "Hoàn thành"]
        summary = asyncio.run(build_bot(client, self.tmp, autorun=False).run_once())
        self.assertEqual([], summary["columns"])
        self.assertEqual([], client.comments)

    def test_a_bot_in_no_project_reports_that_instead_of_failing(self) -> None:
        bot = build_bot(FakeClient([], {}, {}), self.tmp)
        summary = asyncio.run(bot.run_once())
        self.assertEqual([], summary["projects"])
        self.assertIn("dự án", summary["reason"])

    def test_no_token_means_the_bot_reports_itself_off(self) -> None:
        bot = AgentBot(AgentBotConfig(), client=FakeClient([], {}, {}), state=AgentBotState.load(self.tmp / "s.json"))
        self.assertFalse(asyncio.run(bot.run_once())["enabled"])


class BoardScopeTests(unittest.TestCase):
    """Thêm bot vào dự án là đủ — không phải gắn vào từng thẻ."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.calls: List[str] = []

    async def _hook(self, task_id: str) -> Dict[str, Any]:
        self.calls.append(task_id)
        return {"queued": []}

    def _client(self, board: List[Dict[str, Any]]) -> FakeClient:
        trees = {
            item["name"]: {"root": task_node(item["name"], subtasks=[task_node(f"{item['name']}-c")])}
            for item in board
        }
        for name, tree in trees.items():
            root = tree["root"]
            source = next(item for item in board if item["name"] == name)
            root["agents"] = source.get("agents") or []
            root["status"] = source.get("status") or ""
            root["child_total"] = source.get("child_total", 1)
        return FakeClient(["PROJ-0013"], {"PROJ-0013": board}, trees)

    def _run(self, board: List[Dict[str, Any]], **overrides) -> Dict[str, Any]:
        bot = build_bot(self._client(board), self.tmp, **overrides)
        bot.autorun_hook = self._hook
        return asyncio.run(bot.run_once())

    def test_an_idea_card_nobody_attached_the_bot_to_is_still_run(self) -> None:
        summary = self._run([{"name": "TASK-1", "child_total": 3, "status": "Working"}])
        self.assertEqual(["TASK-1"], summary["tasks"])
        self.assertEqual(["TASK-1"], self.calls)

    def test_a_card_with_no_children_is_not_an_idea_card(self) -> None:
        summary = self._run([{"name": "TASK-1", "child_total": 0, "status": "Open"}])
        self.assertEqual([], summary["tasks"])
        self.assertEqual([], self.calls)

    def test_a_finished_or_cancelled_card_is_left_closed(self) -> None:
        board = [
            {"name": "TASK-1", "child_total": 2, "status": "Completed"},
            {"name": "TASK-2", "child_total": 2, "status": "Cancelled"},
        ]
        self.assertEqual([], self._run(board)["tasks"])
        self.assertEqual([], self.calls)

    def test_attaching_the_bot_to_one_card_narrows_that_project_to_it(self) -> None:
        # Gắn vào một thẻ chỉ có một nghĩa: chạy đúng thẻ này.
        board = [
            {"name": "TASK-1", "child_total": 2, "status": "Working"},
            {"name": "TASK-2", "child_total": 2, "status": "Working", "agents": [{"bot_user": BOT}]},
        ]
        summary = self._run(board)
        self.assertEqual(["TASK-2"], summary["tasks"])
        self.assertEqual(["TASK-2"], self.calls)

    def test_a_card_carrying_somebody_elses_bot_is_not_taken_over(self) -> None:
        board = [
            {"name": "TASK-1", "child_total": 2, "status": "Working"},
            {
                "name": "TASK-2",
                "child_total": 2,
                "status": "Working",
                "agents": [{"bot_user": "agent-other@bots.hvg.internal"}],
            },
        ]
        self.assertEqual(["TASK-1"], self._run(board)["tasks"])

    def test_card_scope_still_waits_to_be_attached_to_a_card(self) -> None:
        board = [{"name": "TASK-1", "child_total": 2, "status": "Working"}]
        self.assertEqual([], self._run(board, scope="card")["tasks"])
        self.assertEqual([], self.calls)

    def test_a_whole_board_does_not_become_a_whole_board_of_jobs_at_once(self) -> None:
        # Một trình duyệt, một phiên Flow: xếp cả board vào hàng chỉ làm hàng
        # đợi dài chứ không nhanh hơn.
        board = [
            {"name": f"TASK-{index}", "child_total": 2, "status": "Working"} for index in range(1, 6)
        ]
        summary = self._run(board, max_cards_per_scan=2)
        self.assertEqual(2, len(self.calls))
        # Nhưng phiếu 👍/👎 thì vẫn được đọc trên toàn bộ thẻ.
        self.assertEqual(5, len(summary["tasks"]))


class SourceColumnTests(unittest.TestCase):
    """Cột nào là lời giao việc — và cột nào chỉ là chỗ gõ dở.

    Không có hàng rào này thì mọi thẻ chưa đóng đều bị nhặt, kể cả thẻ vừa tạo
    mà người ta còn đang gõ ``action_1: listing`` vào. Có nó thì thao tác kéo
    thẻ sang cột làm việc mới là nút "chạy đi".
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.calls: List[str] = []

    async def _hook(self, task_id: str) -> Dict[str, Any]:
        self.calls.append(task_id)
        return {"queued": []}

    def _run(self, board: List[Dict[str, Any]], **overrides) -> Dict[str, Any]:
        # Dùng lại đúng bộ đồ chơi của BoardScopeTests: hai lớp này hỏi về cùng
        # một bước lọc, chỉ khác chỗ đứng.
        bot = build_bot(BoardScopeTests._client(self, board), self.tmp, **overrides)
        bot.autorun_hook = self._hook
        return asyncio.run(bot.run_once())

    def test_an_empty_setting_still_means_every_open_column(self) -> None:
        # Câu này canh chỗ nguy nhất: thêm hàng rào mà lỡ bật sẵn thì mọi máy
        # đang chạy đứng im, và đứng im đọc y hệt "board đã làm xong".
        board = [
            {"name": "TASK-1", "child_total": 2, "status": "Open"},
            {"name": "TASK-2", "child_total": 2, "status": "Working"},
        ]
        self.assertEqual(["TASK-1", "TASK-2"], sorted(self._run(board)["tasks"]))
        self.assertEqual(["TASK-1", "TASK-2"], sorted(self.calls))

    def test_only_the_named_column_is_taken_as_work(self) -> None:
        board = [
            {"name": "TASK-1", "child_total": 2, "status": "Open"},
            {"name": "TASK-2", "child_total": 2, "status": "Working"},
        ]
        summary = self._run(board, source_statuses=("Working",))
        self.assertEqual(["TASK-2"], summary["tasks"])
        self.assertEqual(["TASK-2"], self.calls)

    def test_more_than_one_column_can_be_named(self) -> None:
        board = [
            {"name": "TASK-1", "child_total": 2, "status": "Open"},
            {"name": "TASK-2", "child_total": 2, "status": "Working"},
            {"name": "TASK-3", "child_total": 2, "status": "Pending Review"},
        ]
        summary = self._run(board, source_statuses=("Open", "Working"))
        self.assertEqual(["TASK-1", "TASK-2"], sorted(summary["tasks"]))

    def test_a_card_the_bot_was_attached_to_runs_from_any_column(self) -> None:
        # Gắn bot vào thẻ là lối cứu duy nhất cho thẻ lỡ nhịp (``action_1:
        # listing`` gõ muộn). Bắt nó qua hàng rào cột nữa là bịt luôn lối ấy.
        board = [
            {"name": "TASK-1", "child_total": 2, "status": "Working"},
            {
                "name": "TASK-2",
                "child_total": 2,
                "status": "Open",
                "agents": [{"bot_user": BOT}],
            },
        ]
        summary = self._run(board, source_statuses=("Working",))
        self.assertEqual(["TASK-2"], summary["tasks"])

    def test_the_column_name_is_matched_the_way_every_other_column_name_is(self) -> None:
        # ``compact_status`` cả hai đầu: người ta gõ tên cột mình đang nhìn
        # thấy, không phải gõ đúng kiểu chữ mà mã nguồn muốn.
        self.assertTrue(card_is_in_source_column({"status": "Working"}, ("  working ",)))
        self.assertTrue(card_is_in_source_column({"status": "WORKING"}, ("Working",)))
        self.assertTrue(card_is_in_source_column({"status": "Đang làm"}, ("dang lam",)))
        self.assertFalse(card_is_in_source_column({"status": "Open"}, ("Working",)))
        # Bảng rỗng nghĩa là không hỏi gì, chứ không phải cấm tất.
        self.assertTrue(card_is_in_source_column({"status": "Open"}, ()))
        self.assertTrue(card_is_in_source_column({"status": "Open"}, ("", "   ")))

    def test_a_column_name_that_matches_nothing_says_so_out_loud(self) -> None:
        # Gõ sai một chữ thì cả board biến mất. Log phải kể tên các cột đang
        # thật sự có, nếu không người đọc chỉ thấy bot "không có việc".
        board = [
            {"name": "TASK-1", "child_total": 2, "status": "Open"},
            {"name": "TASK-2", "child_total": 2, "status": "Pending Review"},
        ]
        with self.assertLogs("flow_web.agent_bot", level="WARNING") as caught:
            summary = self._run(board, source_statuses=("Workign",))
        self.assertEqual([], summary["tasks"])
        noise = "\n".join(caught.output)
        self.assertIn("Workign", noise)
        self.assertIn("Open", noise)
        self.assertIn("Pending Review", noise)

    def test_a_board_with_nothing_open_is_not_reported_as_a_typo(self) -> None:
        # Board đã làm xong hết thì im lặng là đúng — cảnh báo ở đây sẽ kêu mỗi
        # hai phút cho tới khi có người gõ thẻ mới, và cảnh báo kêu mãi thì
        # chẳng ai đọc cảnh báo nào nữa.
        board = [{"name": "TASK-1", "child_total": 2, "status": "Completed"}]
        with self.assertNoLogs("flow_web.agent_bot", level="WARNING"):
            self.assertEqual([], self._run(board, source_statuses=("Working",))["tasks"])

    def test_the_typo_warning_says_its_piece_once_per_board(self) -> None:
        """Kêu một lần cho mỗi bảng, đừng kêu lại mỗi lượt quét.

        Thẻ nằm chờ ở "Open" cho tới khi có người kéo sang "Working" là trạng
        thái *nghỉ bình thường* của mọi bảng, không phải lỗi gõ. Đo trên hvg-pc
        ngày 13/09/2026: cảnh báo này lặp mỗi hai phút trên 8 bảng — khoảng 185
        dòng mỗi giờ, suốt ngày đêm — nên lỗi thật chìm nghỉm giữa đống đó.
        Cảnh báo kêu mãi là cảnh báo không ai đọc, tức là bằng không có.
        """
        board = [{"name": "TASK-1", "child_total": 2, "status": "Open"}]
        client = BoardScopeTests._client(self, board)
        bot = build_bot(client, self.tmp, source_statuses=("Working",))
        bot.autorun_hook = self._hook

        with self.assertLogs("flow_web.agent_bot", level="WARNING") as lan_dau:
            asyncio.run(bot.run_once())
        self.assertEqual(1, len(lan_dau.output))
        self.assertIn("Working", lan_dau.output[0])
        self.assertIn("Open", lan_dau.output[0])

        # Bảng y nguyên thì hai lượt sau im.
        with self.assertNoLogs("flow_web.agent_bot", level="WARNING"):
            asyncio.run(bot.run_once())
            asyncio.run(bot.run_once())

    def test_the_typo_warning_comes_back_when_the_columns_change(self) -> None:
        """Im lặng chỉ áp cho đúng tình hình đã kêu rồi.

        Nhớ mỗi "bảng này kêu rồi" mà quên đã kêu vì cột nào thì bẫy gõ sai tên
        cột tàng hình trở lại: bảng đổi cột là tình hình mới, phải kêu lại.
        """
        board = [{"name": "TASK-1", "child_total": 2, "status": "Open"}]
        client = BoardScopeTests._client(self, board)
        bot = build_bot(client, self.tmp, source_statuses=("Working",))
        bot.autorun_hook = self._hook

        with self.assertLogs("flow_web.agent_bot", level="WARNING"):
            asyncio.run(bot.run_once())
        with self.assertNoLogs("flow_web.agent_bot", level="WARNING"):
            asyncio.run(bot.run_once())

        board[0]["status"] = "Pending Review"
        with self.assertLogs("flow_web.agent_bot", level="WARNING") as keu_lai:
            asyncio.run(bot.run_once())
        self.assertIn("Pending Review", "\n".join(keu_lai.output))

    def test_a_board_that_starts_matching_again_is_allowed_to_warn_later(self) -> None:
        """Kéo thẻ vào đúng cột rồi kéo ra lại thì cảnh báo phải sống lại.

        Nếu không, lượt đầu tiên sau khi bảng trống trở lại sẽ im lặng mãi mãi
        — và im lặng ấy đọc y hệt "bảng đang chạy tốt".
        """
        board = [{"name": "TASK-1", "child_total": 2, "status": "Open"}]
        client = BoardScopeTests._client(self, board)
        bot = build_bot(client, self.tmp, source_statuses=("Working",))
        bot.autorun_hook = self._hook

        with self.assertLogs("flow_web.agent_bot", level="WARNING"):
            asyncio.run(bot.run_once())

        board[0]["status"] = "Working"
        asyncio.run(bot.run_once())

        board[0]["status"] = "Open"
        with self.assertLogs("flow_web.agent_bot", level="WARNING") as keu_lai:
            asyncio.run(bot.run_once())
        self.assertIn("Working", "\n".join(keu_lai.output))


class ListingCardTests(unittest.TestCase):
    """Một agent, một thẻ, hai chặng: làm ảnh xong rồi mới đăng lên Etsy.

    Thẻ nói mình là listing (``action_1: listing``) vẫn đi qua nửa làm ảnh —
    ảnh phải có từ đâu đó, và nửa listing không tạo ảnh, nó chỉ chép bộ ảnh
    đang nằm trên thẻ sang máy Etsy. Chặng đăng chỉ mở khi người duyệt đã bấm
    xong 👍/👎. Thẻ ảnh không viết ``action_*`` nào, nên im lặng vẫn là "làm
    như cũ".
    """

    LISTING_META = "action_1: listing\nacc: acc32"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.calls: List[str] = []

    async def _hook(self, task_id: str) -> Dict[str, Any]:
        self.calls.append(task_id)
        return {"queued": []}

    def _run(self, roots: List[Dict[str, Any]], listing_hook=None):
        rows = [
            {
                "name": root["name"],
                "child_total": root.get("child_total", 0),
                "status": "Working",
                "agents": root.get("agents") or [],
                "parent_task": "",
            }
            for root in roots
        ]
        client = FakeClient(
            ["PROJ-0013"],
            {"PROJ-0013": rows},
            {root["name"]: {"root": root} for root in roots},
        )
        bot = build_bot(client, self.tmp)
        bot.autorun_hook = self._hook
        bot.listing_hook = listing_hook
        return asyncio.run(bot.run_once()), client

    def _listing_root(self, name: str = "TASK-L", **kwargs) -> Dict[str, Any]:
        return {**task_node(name, agents=[BOT], **kwargs), "meta": self.LISTING_META}

    def _approved(self, name: str = "TASK-L") -> Dict[str, Any]:
        """Thẻ listing đã chạy xong ảnh và người duyệt đã bấm 👍."""
        return self._listing_root(
            name, comments=[comment("L-1", like=1), comment("L-2", like=2)]
        )

    async def _queued(self, task_id: str, root: Dict[str, Any]) -> Dict[str, Any]:
        return {"queue_task_id": "etsy-copy-1", "machine_id": "etsy-vn32"}

    def test_the_shape_written_in_the_panel_is_what_marks_a_listing_card(self) -> None:
        self.assertTrue(is_listing_card(self._listing_root()))
        # Thật sự lấy từ thẻ ảnh đang chạy trên ERP, không phải bịa.
        self.assertFalse(is_listing_card({"meta": "sku: \nproduct: khan tay\nfatheridea:"}))
        self.assertFalse(is_listing_card({"meta": "prompt:"}))
        self.assertFalse(is_listing_card({}))

    # ── chặng 1: thẻ listing vẫn phải có ảnh trước đã ──────────────────

    def test_a_listing_card_with_no_images_yet_goes_through_the_image_half(self) -> None:
        # Nếu nửa listing chiếm luôn thẻ ngay từ đầu thì sẽ không bao giờ có
        # ảnh nào để nó đăng.
        root = self._listing_root(subtasks=[task_node("TASK-L-a")])
        summary, _ = self._run([root], listing_hook=self._queued)

        self.assertEqual(["TASK-L"], self.calls)
        self.assertEqual("thẻ chưa có ảnh nào để đăng", summary["listing"][0]["waiting"])

    def test_a_card_still_waiting_on_a_thumb_is_not_handed_over(self) -> None:
        root = self._listing_root(comments=[comment("L-1", like=1), comment("L-2")])
        handed: List[str] = []

        async def listing_hook(task_id: str, node: Dict[str, Any]) -> Dict[str, Any]:
            handed.append(task_id)
            return {"queue_task_id": "x"}

        summary, _ = self._run([root], listing_hook=listing_hook)

        self.assertEqual([], handed)
        self.assertIn("chờ 👍/👎", summary["listing"][0]["waiting"])

    def test_a_card_whose_images_were_all_rejected_is_not_published_empty(self) -> None:
        root = self._listing_root(comments=[comment("L-1", dislike=1)])
        summary, client = self._run([root], listing_hook=self._queued)

        self.assertEqual("không còn ảnh nào được giữ", summary["listing"][0]["waiting"])
        # Phiếu 👎 vẫn được thi hành như mọi thẻ khác.
        self.assertEqual([("TASK-L", "L-1")], client.deleted)

    # ── chặng 2: ảnh đã chốt thì giao đi ───────────────────────────────

    def test_an_approved_card_is_handed_over_with_the_card_itself(self) -> None:
        handed: List[tuple[str, str]] = []

        async def listing_hook(task_id: str, root: Dict[str, Any]) -> Dict[str, Any]:
            # Nhận cả thẻ, không chỉ mã: bên kia cần ``meta`` để biết máy nào.
            handed.append((task_id, str(root.get("meta") or "")))
            return {"queue_task_id": "etsy-copy-1", "machine_id": "etsy-vn32"}

        summary, _ = self._run([self._approved()], listing_hook=listing_hook)

        self.assertEqual([("TASK-L", self.LISTING_META)], handed)
        self.assertEqual(
            {"queue_task_id": "etsy-copy-1", "machine_id": "etsy-vn32"},
            summary["listing"][0]["result"],
        )

    def test_images_the_bot_did_not_post_still_open_the_listing_gate(self) -> None:
        # Cái cổng này từng đóng vĩnh viễn: nó chỉ đếm ảnh ``mine == 1``, mà
        # đường tạo ảnh của app đăng dưới danh tính người thật, nên thẻ nào
        # cũng đọc ra "chưa có ảnh nào để đăng" và không bao giờ được giao đi.
        # Nửa listing tải ảnh về từ chính thẻ chứ không phải từ bot, nên tác
        # giả bình luận không liên quan gì tới câu "bộ ảnh đã chốt chưa".
        theirs = comment("L-1", mine=0, owner="phong.hothanh@havigroup.llc", like=1)
        root = self._listing_root(comments=[theirs])
        handed: List[str] = []

        async def listing_hook(task_id: str, node: Dict[str, Any]) -> Dict[str, Any]:
            handed.append(task_id)
            return {"queue_task_id": "etsy-copy-1", "machine_id": "etsy-vn32"}

        self._run([root], listing_hook=listing_hook)
        self.assertEqual(["TASK-L"], handed)

    def test_a_foreign_image_still_waiting_on_a_thumb_keeps_the_gate_shut(self) -> None:
        # Đếm cả ảnh của người khác thì cũng phải *chờ* cả phiếu của chúng —
        # nếu không, mở cổng rộng ra lại thành đăng khi người duyệt chưa xem.
        forastero = lambda name, **kw: comment(
            name, mine=0, owner="phong.hothanh@havigroup.llc", **kw)
        root = self._listing_root(comments=[forastero("L-1", like=1), forastero("L-2")])
        handed: List[str] = []

        async def listing_hook(task_id: str, node: Dict[str, Any]) -> Dict[str, Any]:
            handed.append(task_id)
            return {"queue_task_id": "x"}

        summary, _ = self._run([root], listing_hook=listing_hook)
        self.assertEqual([], handed)
        self.assertIn("chờ 👍/👎", summary["listing"][0]["waiting"])

    def test_a_card_already_sent_to_etsy_is_not_run_for_images_again(self) -> None:
        summary, _ = self._run([self._approved()], listing_hook=self._queued)
        self.assertEqual([], self.calls)
        self.assertEqual([], summary["autorun"])

    def test_with_no_listing_backend_the_card_is_reported_not_swallowed(self) -> None:
        # Bỏ qua âm thầm trông y hệt thẻ hỏng, mà người dùng vừa gắn agent vào nó.
        summary, _ = self._run([self._approved()])
        self.assertIn("ERP_LISTING_API_URL", summary["listing"][0]["skipped"])

    def test_a_listing_backend_that_is_down_does_not_break_the_sweep(self) -> None:
        async def listing_hook(task_id: str, root: Dict[str, Any]) -> Dict[str, Any]:
            raise RuntimeError("Bản Listing đang tắt")

        image = task_node("TASK-1", agents=[BOT], subtasks=[task_node("TASK-1-a")])
        summary, _ = self._run([self._approved(), image], listing_hook=listing_hook)

        self.assertEqual("Bản Listing đang tắt", summary["listing"][0]["error"])
        # Nửa làm ảnh vẫn chạy hết lượt của nó.
        self.assertEqual(["TASK-1"], self.calls)

    def test_a_card_the_listing_half_declines_can_still_be_retried(self) -> None:
        # "Thẻ đã ở cột Done" là câu trả lời của lần này thôi; người dùng sửa
        # thẻ rồi thì lượt sau phải giao lại được.
        sent: List[str] = []

        async def listing_hook(task_id: str, root: Dict[str, Any]) -> Dict[str, Any]:
            sent.append(task_id)
            return {"machine_id": "etsy-vn32", "skipped": "thẻ đã ở cột Done"}

        root = self._approved()
        rows = [{"name": "TASK-L", "child_total": 0, "status": "Working",
                 "agents": [{"bot_user": BOT}], "parent_task": ""}]
        client = FakeClient(["PROJ-0013"], {"PROJ-0013": rows}, {"TASK-L": {"root": root}})
        bot = build_bot(client, self.tmp, autorun_cooldown_seconds=0)
        bot.listing_hook = listing_hook
        asyncio.run(bot.run_once())
        asyncio.run(bot.run_once())

        self.assertEqual(["TASK-L", "TASK-L"], sent)

    # ── không giao hai lần ─────────────────────────────────────────────

    def test_the_same_card_is_never_published_twice(self) -> None:
        # Hai lần đăng là hai bản nháp trong shop cho cùng một sản phẩm, nên
        # đây là sổ ghi vĩnh viễn chứ không phải hàng rào thời gian.
        sent: List[str] = []

        async def listing_hook(task_id: str, root: Dict[str, Any]) -> Dict[str, Any]:
            sent.append(task_id)
            return {"queue_task_id": "etsy-copy-1", "machine_id": "etsy-vn32"}

        root = self._approved()
        rows = [{"name": "TASK-L", "child_total": 0, "status": "Working",
                 "agents": [{"bot_user": BOT}], "parent_task": ""}]
        client = FakeClient(["PROJ-0013"], {"PROJ-0013": rows}, {"TASK-L": {"root": root}})
        bot = build_bot(client, self.tmp, autorun_cooldown_seconds=0)
        bot.listing_hook = listing_hook
        asyncio.run(bot.run_once())
        asyncio.run(bot.run_once())

        self.assertEqual(["TASK-L"], sent)

    def test_a_restart_does_not_forget_what_was_already_published(self) -> None:
        sent: List[str] = []

        async def listing_hook(task_id: str, root: Dict[str, Any]) -> Dict[str, Any]:
            sent.append(task_id)
            return {"queue_task_id": "etsy-copy-1", "machine_id": "etsy-vn32"}

        rows = [{"name": "TASK-L", "child_total": 0, "status": "Working",
                 "agents": [{"bot_user": BOT}], "parent_task": ""}]
        for _ in range(2):
            client = FakeClient(["PROJ-0013"], {"PROJ-0013": rows}, {"TASK-L": {"root": self._approved()}})
            bot = build_bot(client, self.tmp, autorun_cooldown_seconds=0)
            bot.listing_hook = listing_hook
            asyncio.run(bot.run_once())

        self.assertEqual(["TASK-L"], sent)

    def test_a_second_sweep_inside_the_cooldown_does_not_hand_over_again(self) -> None:
        # Hàng rào thứ hai, cho lượt giao chưa kịp ghi sổ.
        state = AgentBotState.load(self.tmp / "state.json")
        state.mark_autorun("listing:TASK-L")
        state.save()

        summary, _ = self._run([self._approved()], listing_hook=self._queued)
        self.assertIn("nguội", summary["listing"][0]["skipped"])

    # ── giao xong chưa phải đăng xong ──────────────────────────────────

    def _sweep_twice(self, confirm, cooldown: int = 0):
        """Một lượt giao thẻ, rồi một lượt nữa để đi hỏi lại kết quả."""
        rows = [{"name": "TASK-L", "child_total": 0, "status": "Working",
                 "agents": [{"bot_user": BOT}], "parent_task": ""}]
        summaries = []
        for _ in range(2):
            client = FakeClient(["PROJ-0013"], {"PROJ-0013": rows},
                                {"TASK-L": {"root": self._approved()}})
            bot = build_bot(client, self.tmp, autorun_cooldown_seconds=cooldown)
            bot.listing_hook = self._queued
            bot.listing_confirm_hook = confirm
            summaries.append(asyncio.run(bot.run_once()))
        return summaries, bot

    def test_handing_a_card_over_does_not_yet_mean_the_draft_exists(self) -> None:
        # Cái sổ mở cổng sang *Hoàn thành* phải là câu trả lời của máy Etsy,
        # không phải cái biên lai xếp hàng. Máy ảo đang ngủ mà thẻ đã sang
        # *Hoàn thành* thì người vận hành tin vào một bản nháp không có thật.
        async def confirm(queue_task_id: str, machine_id: str) -> Dict[str, Any]:
            return {"pending": True, "status": "queued"}

        summaries, bot = self._sweep_twice(confirm)

        self.assertTrue(bot.state.already_listed("TASK-L"))
        self.assertFalse(bot.state.listing_confirmed("TASK-L"))
        self.assertIn("đang chạy", summaries[1]["listing"][0]["waiting"])

    def test_the_gate_to_done_opens_only_when_etsy_reports_completed(self) -> None:
        asked: List[tuple[str, str]] = []

        async def confirm(queue_task_id: str, machine_id: str) -> Dict[str, Any]:
            asked.append((queue_task_id, machine_id))
            return {"done": True, "status": "completed", "card_moved": True}

        summaries, bot = self._sweep_twice(confirm)

        # Hỏi đúng lượt đã giao, đúng máy đã nhận — cả hai đọc từ sổ.
        self.assertEqual([("etsy-copy-1", "etsy-vn32")], asked)
        self.assertTrue(bot.state.listing_confirmed("TASK-L"))
        self.assertTrue(summaries[1]["listing"][0]["listed"]["done"])

    def test_a_confirmed_card_is_not_asked_about_again(self) -> None:
        asked: List[str] = []

        async def confirm(queue_task_id: str, machine_id: str) -> Dict[str, Any]:
            asked.append(queue_task_id)
            return {"done": True}

        self._sweep_twice(confirm)
        rows = [{"name": "TASK-L", "child_total": 0, "status": "Working",
                 "agents": [{"bot_user": BOT}], "parent_task": ""}]
        client = FakeClient(["PROJ-0013"], {"PROJ-0013": rows},
                            {"TASK-L": {"root": self._approved()}})
        bot = build_bot(client, self.tmp, autorun_cooldown_seconds=0)
        bot.listing_hook = self._queued
        bot.listing_confirm_hook = confirm
        asyncio.run(bot.run_once())

        self.assertEqual(["etsy-copy-1"], asked)

    def test_a_run_that_failed_on_the_etsy_machine_is_said_out_loud(self) -> None:
        # Và **không** giao lại: bản nháp có thể đã dựng dở trong shop, nên
        # việc tiếp theo là người vào xem chứ không phải máy thử lần nữa.
        sent: List[str] = []

        async def listing_hook(task_id: str, root: Dict[str, Any]) -> Dict[str, Any]:
            sent.append(task_id)
            return {"queue_task_id": "etsy-copy-1", "machine_id": "etsy-vn32"}

        async def confirm(queue_task_id: str, machine_id: str) -> Dict[str, Any]:
            return {"failed": True, "status": "failed", "error": "chrome_crashed"}

        rows = [{"name": "TASK-L", "child_total": 0, "status": "Working",
                 "agents": [{"bot_user": BOT}], "parent_task": ""}]
        summary = None
        for _ in range(2):
            client = FakeClient(["PROJ-0013"], {"PROJ-0013": rows},
                                {"TASK-L": {"root": self._approved()}})
            bot = build_bot(client, self.tmp, autorun_cooldown_seconds=0)
            bot.listing_hook = listing_hook
            bot.listing_confirm_hook = confirm
            summary = asyncio.run(bot.run_once())

        self.assertEqual(["TASK-L"], sent)
        self.assertEqual("chrome_crashed", summary["listing"][0]["failed"])
        self.assertFalse(bot.state.listing_confirmed("TASK-L"))

    def test_a_listing_backend_that_is_down_does_not_break_the_confirm_sweep(self) -> None:
        async def confirm(queue_task_id: str, machine_id: str) -> Dict[str, Any]:
            raise RuntimeError("Bản Listing đang tắt")

        summaries, bot = self._sweep_twice(confirm)

        self.assertEqual("Bản Listing đang tắt", summaries[1]["listing"][0]["error"])
        self.assertFalse(bot.state.listing_confirmed("TASK-L"))

    def test_without_a_confirm_hook_the_card_simply_waits_for_a_person(self) -> None:
        # Chưa nối đường hỏi lại thì luật cột không tự đóng thẻ. Đứng lại ở
        # *Đang review* là đúng: chỗ đó là bàn của người làm listing.
        summaries, bot = self._sweep_twice(None)

        self.assertTrue(bot.state.already_listed("TASK-L"))
        self.assertFalse(bot.state.listing_confirmed("TASK-L"))
        self.assertEqual([], summaries[1]["listing"])

    # ── phần còn lại của lượt quét không bị ảnh hưởng ──────────────────

    def test_a_listing_card_is_still_this_agent_s_card(self) -> None:
        root = self._listing_root(subtasks=[task_node("TASK-L-a")])
        summary, client = self._run([root])

        self.assertEqual(["TASK-L"], summary["tasks"])
        self.assertEqual([("TASK-L-a", BOT)], client.agents_added)

    def test_an_image_card_in_the_same_sweep_is_untouched_by_all_this(self) -> None:
        image = task_node(
            "TASK-1",
            agents=[BOT],
            subtasks=[task_node("TASK-1-a", comments=[comment("c1", dislike=1)])],
        )
        summary, client = self._run([self._approved(), image], listing_hook=self._queued)

        self.assertEqual(["TASK-L"], [item["task"] for item in summary["listing"]])
        self.assertEqual(["TASK-1"], self.calls)
        self.assertEqual([("TASK-1-a", "c1")], client.deleted)


class AgentInheritanceTests(unittest.TestCase):
    """Gắn bot vào thẻ cha là gắn cho cả cụm: thẻ con được gắn theo."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.calls: List[str] = []

    async def _hook(self, task_id: str) -> Dict[str, Any]:
        self.calls.append(task_id)
        return {"queued": []}

    def _run(self, root: Dict[str, Any], board=None, **overrides):
        name = root["name"]
        rows = board or [
            {
                "name": name,
                "child_total": root.get("child_total", 0),
                "status": "Working",
                "agents": root.get("agents") or [],
                "parent_task": root.get("parent_task") or "",
            }
        ]
        client = FakeClient(["PROJ-0013"], {"PROJ-0013": rows}, {name: {"root": root}})
        bot = build_bot(client, self.tmp, **overrides)
        bot.autorun_hook = self._hook
        return asyncio.run(bot.run_once()), client

    def test_children_of_an_attached_parent_are_attached_too(self) -> None:
        root = task_node(
            "TASK-1",
            agents=[BOT],
            subtasks=[task_node("TASK-1-a"), task_node("TASK-1-b")],
        )
        summary, client = self._run(root)
        self.assertEqual([("TASK-1-a", BOT), ("TASK-1-b", BOT)], client.agents_added)
        self.assertEqual(["TASK-1-a", "TASK-1-b"], [item["task"] for item in summary["inherited"]])

    def test_a_child_that_already_carries_the_bot_is_left_alone(self) -> None:
        root = task_node(
            "TASK-1",
            agents=[BOT],
            subtasks=[task_node("TASK-1-a", agents=[BOT]), task_node("TASK-1-b")],
        )
        _, client = self._run(root)
        self.assertEqual([("TASK-1-b", BOT)], client.agents_added)

    def test_grandchildren_are_attached_as_well(self) -> None:
        # Cụm việc sâu hai tầng vẫn là một cụm việc.
        deep = task_node("TASK-1-a", subtasks=[task_node("TASK-1-a-1")])
        summary, client = self._run(task_node("TASK-1", agents=[BOT], subtasks=[deep]))
        self.assertEqual(
            [("TASK-1-a", BOT), ("TASK-1-a-1", BOT)], client.agents_added
        )
        self.assertEqual(2, len(summary["inherited"]))

    def test_a_card_the_bot_only_reached_through_the_project_spreads_nothing(self) -> None:
        # Không ai gắn bot vào đâu cả: bot đang làm vì nó ở trong dự án, và tự
        # đi gắn mình vào từng thẻ con là ghi lên thẻ của người khác.
        root = task_node("TASK-1", subtasks=[task_node("TASK-1-a")], child_total=1)
        _, client = self._run(root)
        self.assertEqual([], client.agents_added)

    def test_somebody_elses_bot_on_the_parent_spreads_nothing(self) -> None:
        root = task_node("TASK-1", agents=["agent-other@bots.hvg.internal"], subtasks=[task_node("TASK-1-a")])
        _, client = self._run(root)
        self.assertEqual([], client.agents_added)

    def test_dry_run_says_what_it_would_attach_and_writes_nothing(self) -> None:
        root = task_node("TASK-1", agents=[BOT], subtasks=[task_node("TASK-1-a")])
        summary, client = self._run(root, dry_run=True)
        self.assertEqual([], client.agents_added)
        self.assertEqual([{"task": "TASK-1-a", "dry_run": True}], summary["inherited"])

    def test_the_parent_still_gets_the_scan_slot_its_children_would_have_eaten(self) -> None:
        # Sau khi lan xuống, thẻ con cũng mang bot nên cũng lọt bộ lọc "gắn
        # đích danh". Thẻ cha đã chứa sẵn cây của con, nên chạy thêm từng thẻ
        # con là vừa thừa vừa ăn mất trần mỗi lượt.
        board = [
            {"name": "TASK-1", "child_total": 2, "status": "Working", "agents": [{"bot_user": BOT}]},
            {"name": "TASK-1-a", "child_total": 0, "status": "Working",
             "agents": [{"bot_user": BOT}], "parent_task": "TASK-1"},
            {"name": "TASK-1-b", "child_total": 0, "status": "Working",
             "agents": [{"bot_user": BOT}], "parent_task": "TASK-1"},
        ]
        root = task_node("TASK-1", agents=[BOT], subtasks=[task_node("TASK-1-a"), task_node("TASK-1-b")])
        summary, _ = self._run(root, board=board)
        self.assertEqual(["TASK-1"], summary["tasks"])
        self.assertEqual(["TASK-1"], self.calls)

    def test_a_child_attached_on_its_own_is_still_run_on_its_own(self) -> None:
        # Cha không gắn thì gắn vào con là người dùng cố ý chỉ đúng thẻ đó.
        board = [
            {"name": "TASK-1", "child_total": 2, "status": "Working"},
            {"name": "TASK-1-a", "child_total": 2, "status": "Working",
             "agents": [{"bot_user": BOT}], "parent_task": "TASK-1"},
        ]
        root = task_node("TASK-1-a", agents=[BOT], child_total=2)
        client = FakeClient(["PROJ-0013"], {"PROJ-0013": board}, {"TASK-1-a": {"root": root}})
        bot = build_bot(client, self.tmp)
        bot.autorun_hook = self._hook
        summary = asyncio.run(bot.run_once())
        self.assertEqual(["TASK-1-a"], summary["tasks"])
        self.assertEqual(["TASK-1-a"], self.calls)


class MetaInheritanceTests(unittest.TestCase):
    """Thẻ cha khai Thuộc tính một lần thì thẻ con nhận theo — ERP không tự chép.

    Ca thật: TASK-2026-05384 (PROJ-0087) khai đủ bốn ô, 48 thẻ con để trống,
    và Review Lister đọc đúng khối của thẻ con nên thẻ nào cũng "thiếu".
    """

    PARENT_META = (
        "account:\nsku:\nproduct_type: Punch Needle Ornament\nproduct_group: handmade\n"
        "fulfillment: FBM\nsales_channel: Etsy"
    )
    FOUR = {
        "product_type": "Punch Needle Ornament",
        "product_group": "handmade",
        "fulfillment": "FBM",
        "sales_channel": "Etsy",
    }

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.writes: List[tuple[str, Dict[str, str]]] = []

    def _record(self, task_id: str, values: Dict[str, str]) -> Dict[str, Any]:
        self.writes.append((task_id, dict(values)))
        return {"task_id": task_id, "written": dict(values)}

    async def _autorun(self, task_id: str) -> Dict[str, Any]:
        return {"queued": []}

    def _parent(self, children: List[Dict[str, Any]], *, agents=(BOT,), meta: str = "") -> Dict[str, Any]:
        return task_node("TASK-P", agents=list(agents), meta=meta or self.PARENT_META, subtasks=children)

    def _bot(self, root: Dict[str, Any], hook="record", **overrides) -> AgentBot:
        rows = [
            {
                "name": root["name"],
                "child_total": root["child_total"],
                "status": "Working",
                "agents": root.get("agents") or [],
                "parent_task": "",
            }
        ]
        client = FakeClient(["PROJ-0087"], {"PROJ-0087": rows}, {root["name"]: {"root": root}})
        bot = build_bot(client, self.tmp, **overrides)
        bot.autorun_hook = self._autorun
        bot.meta_inherit_hook = self._record if hook == "record" else hook
        return bot

    def test_blank_children_get_what_the_parent_filled(self) -> None:
        root = self._parent([task_node("TASK-P-a", meta=""), task_node("TASK-P-b", meta="")])

        summary = asyncio.run(self._bot(root).run_once())

        self.assertEqual([("TASK-P-a", self.FOUR), ("TASK-P-b", self.FOUR)], self.writes)
        self.assertEqual(
            [{"task": "TASK-P-a", "keys": sorted(self.FOUR)}, {"task": "TASK-P-b", "keys": sorted(self.FOUR)}],
            summary["meta_inherited"],
        )

    def test_a_child_that_already_has_it_all_is_not_written(self) -> None:
        full = task_node("TASK-P-a", meta=self.PARENT_META)
        root = self._parent([full, task_node("TASK-P-b", meta="")])

        asyncio.run(self._bot(root).run_once())

        self.assertEqual(["TASK-P-b"], [task for task, _ in self.writes])

    def test_what_the_child_wrote_itself_is_not_sent_down(self) -> None:
        root = self._parent([task_node("TASK-P-a", meta="fulfillment: FBA")])

        asyncio.run(self._bot(root).run_once())

        self.assertNotIn("fulfillment", self.writes[0][1])
        self.assertEqual("Etsy", self.writes[0][1]["sales_channel"])

    def test_a_parent_the_bot_reached_through_the_project_fills_its_children(self) -> None:
        # Scope board: thẻ Idea không gắn ai đã lọt qua ``candidate_tasks``
        # nghĩa là việc của bot — autorun và dọn phiếu đều chạy trên cây ấy —
        # nên thẻ con của nó (kể cả thẻ tạo tay) cũng được điền Thuộc tính.
        # Chỉ scope card mới đòi gắn đích danh.
        root = self._parent([task_node("TASK-P-a", meta="")], agents=())

        summary = asyncio.run(self._bot(root).run_once())

        self.assertEqual([("TASK-P-a", self.FOUR)], self.writes)
        self.assertEqual(
            [{"task": "TASK-P-a", "keys": sorted(self.FOUR)}],
            summary["meta_inherited"],
        )

    def test_dry_run_names_the_cards_and_writes_nothing(self) -> None:
        root = self._parent([task_node("TASK-P-a", meta="")])

        summary = asyncio.run(self._bot(root, dry_run=True).run_once())

        self.assertEqual([], self.writes)
        self.assertEqual(
            [{"task": "TASK-P-a", "keys": sorted(self.FOUR), "dry_run": True}], summary["meta_inherited"]
        )

    def test_one_scan_writes_at_most_the_cap_and_the_rest_waits_its_turn(self) -> None:
        # Mỗi thẻ là một lượt đọc lại + một lượt ghi của app. Thẻ cha 48 con
        # chép hết một lượt là gần trăm request dồn vào một phút.
        children = [task_node(f"TASK-P-{index:02d}", meta="") for index in range(META_INHERIT_PER_SCAN + 4)]
        bot = self._bot(self._parent(children))

        asyncio.run(bot.run_once())
        self.assertEqual(META_INHERIT_PER_SCAN, len(self.writes))

        asyncio.run(bot.run_once())
        written = [task for task, _ in self.writes]
        self.assertEqual(META_INHERIT_PER_SCAN + 4, len(written))
        self.assertEqual(len(written), len(set(written)))

    def test_a_failed_write_stops_the_cluster_and_the_next_scan_backs_off(self) -> None:
        # Hỏng thường là ERP chặn 429: gõ tiếp thẻ sau là gõ vào đúng chỗ đau.
        tried: List[str] = []

        def refuse(task_id: str, values: Dict[str, str]) -> Dict[str, Any]:
            tried.append(task_id)
            raise RuntimeError("ERP đang giới hạn request (HTTP 429). Hãy thử lại sau với backoff.")

        root = self._parent([task_node("TASK-P-a", meta=""), task_node("TASK-P-b", meta="")])
        bot = self._bot(root, hook=refuse)

        summary = asyncio.run(bot.run_once())
        self.assertEqual(["TASK-P-a"], tried)
        self.assertEqual([], summary["meta_inherited"])

        asyncio.run(bot.run_once())
        self.assertEqual(["TASK-P-a"], tried)

    def test_without_a_hook_nothing_is_written_and_the_scan_goes_on(self) -> None:
        root = self._parent([task_node("TASK-P-a", meta="")])

        summary = asyncio.run(self._bot(root, hook=None).run_once())

        self.assertEqual([], summary["meta_inherited"])
        self.assertEqual(["TASK-P"], summary["tasks"])

    def test_a_grandchild_follows_the_card_right_above_it(self) -> None:
        # Thẻ con khai riêng FBA thì cả nhánh dưới nó đi theo FBA, không nhảy
        # thẳng lên gốc lấy FBM.
        grandchild = task_node("TASK-P-a-1", meta="")
        child = task_node("TASK-P-a", meta="fulfillment: FBA", subtasks=[grandchild])
        root = self._parent([child])
        bot = self._bot(root)

        bot.meta_inherit_pass({"root": root}, BOT)

        self.assertEqual({**self.FOUR, "fulfillment": "FBA"}, dict(self.writes)["TASK-P-a-1"])

    def test_what_was_written_is_what_the_rest_of_the_scan_reads(self) -> None:
        # Luật cột và nửa listing đọc thẻ con ngay trong cùng lượt quét; đọc
        # bản cũ thì thẻ vừa được điền vẫn trông như còn thiếu.
        child = task_node("TASK-P-a", meta="note: mau do")
        root = self._parent([child])

        self._bot(root).meta_inherit_pass({"root": root}, BOT)

        self.assertEqual("FBM", task_meta(child).get("fulfillment"))
        self.assertEqual("mau do", task_meta(child).get("note"))


class IdeaIntakeGateTests(unittest.TestCase):
    """Thẻ Idea vừa được thả ảnh: chưa có thẻ con nhưng vẫn phải nhận."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.calls: List[str] = []

    async def _hook(self, task_id: str) -> Dict[str, Any]:
        self.calls.append(task_id)
        return {"created": [{"task_id": "TASK-NEW-0"}], "queued": []}

    @staticmethod
    def _card(name: str, *, cover: str = "", images: tuple = (), child_total: int = 0, is_group: int = 1):
        root = task_node(name, child_total=child_total)
        root.update({"status": "Working", "cover_image": cover, "is_group": is_group})
        root["comments"] = [
            {
                "name": f"drop-{index}",
                "content": "",
                "attachments": [{"file_url": url, "file_name": Path(url).name}],
            }
            for index, url in enumerate(images)
        ]
        return root

    def _run(self, root: Dict[str, Any], attachment_count: int = 0) -> Dict[str, Any]:
        board = [
            {
                "name": root["name"],
                "child_total": root["child_total"],
                "status": root["status"],
                "is_group": root["is_group"],
                "attachment_count": attachment_count,
            }
        ]
        client = FakeClient(["PROJ-0013"], {"PROJ-0013": board}, {root["name"]: {"root": root}})
        bot = build_bot(client, self.tmp)
        bot.autorun_hook = self._hook
        return asyncio.run(bot.run_once())

    def test_a_card_with_a_second_image_and_no_children_yet_is_run(self) -> None:
        # Người dùng vừa thả ảnh idea lên thẻ; thẻ con chưa tồn tại vì chính
        # lượt chạy này mới tạo ra nó.
        root = self._card(
            "TASK-1", cover="/private/files/khan-tay.jpg", images=("/private/files/tho-noel.jpg",)
        )
        self.assertEqual(["TASK-1"], self._run(root)["tasks"])
        self.assertEqual(["TASK-1"], self.calls)

    def test_a_card_carrying_only_its_product_photo_is_left_alone(self) -> None:
        root = self._card("TASK-1", cover="/private/files/khan-tay.jpg")
        self.assertEqual([], self.calls)
        self._run(root)
        self.assertEqual([], self.calls)

    def test_a_plain_card_with_no_children_is_still_not_an_idea_card(self) -> None:
        self.assertFalse(is_idea_card({"name": "TASK-1", "child_total": 0, "status": "Open"}))
        self.assertTrue(is_idea_card({"name": "TASK-1", "child_total": 0, "status": "Open", "is_group": 1}))
        self.assertTrue(is_idea_card({"name": "TASK-1", "child_total": 2, "status": "Open"}))
        # Thẻ trắng vừa được kéo ảnh sản phẩm + ảnh idea vào: đây mới là đường
        # người dùng thật đi, và nó không phải thẻ nhóm.
        self.assertTrue(
            is_idea_card({"name": "TASK-1", "child_total": 0, "status": "Open", "attachment_count": 2})
        )
        # Một tệp là ảnh sản phẩm đứng một mình, chưa có idea nào.
        self.assertFalse(
            is_idea_card({"name": "TASK-1", "child_total": 0, "status": "Open", "attachment_count": 1})
        )

    def test_a_card_whose_images_were_dragged_straight_on_is_still_run(self) -> None:
        # taskFull không trả tệp treo thẳng trên thẻ, nên thẻ này đọc về trắng
        # trơn: không bìa, không bình luận, không thẻ con. Chỉ dòng của nó trên
        # bảng dự án biết là đang có 3 tệp.
        root = self._card("TASK-1", is_group=0)
        self.assertEqual(["TASK-1"], self._run(root, attachment_count=3)["tasks"])
        self.assertEqual(["TASK-1"], self.calls)

    def test_a_dragged_on_product_photo_by_itself_is_left_alone(self) -> None:
        root = self._card("TASK-1", is_group=0)
        self._run(root, attachment_count=1)
        self.assertEqual([], self.calls)

    def test_flow_output_images_are_not_counted_as_dropped_ideas(self) -> None:
        # Nếu tính cả ảnh Flow thì thẻ nào chạy xong cũng trông như vừa được
        # thả thêm ảnh, và bot sẽ chạy lại nó mãi.
        node = {
            "cover_image": "/private/files/khan-tay.jpg",
            "comments": [
                {
                    "content": "[FLOW_V2_ARTIFACT] flow-1.png",
                    "attachments": [{"file_url": "/files/flow-1.png", "file_name": "flow-1.png"}],
                },
                {"content": "", "attachments": [{"file_url": "/files/ghi-chu.pdf", "file_name": "ghi-chu.pdf"}]},
            ],
        }
        self.assertEqual(1, count_card_images(node))
        # Dòng bảng đếm cả tệp treo thẳng trên thẻ, thứ taskFull không thấy;
        # lấy số lớn hơn chứ không cộng, hai bên đếm chồng lên nhau.
        self.assertEqual(3, count_card_images(node, {"attachment_count": 3}))
        self.assertEqual(1, count_card_images(node, {"attachment_count": 0}))

    def test_images_living_inside_a_comment_are_counted(self) -> None:
        # taskFull trả bình luận với attachments rỗng và đúng một ảnh đại diện,
        # dù taskDetail của chính bình luận ấy có cả chục tấm. Không đếm ảnh đại
        # diện thì thẻ kiểu này đọc về mỗi tấm bìa và bị từ chối vĩnh viễn.
        node = {
            "cover_image": "/private/files/khan-tay.jpg",
            "comments": [{"content": "(đã đính kèm tệp)", "attachments": [], "image": "/files/tho-noel.jpg"}],
        }
        self.assertEqual(2, count_card_images(node))

    def test_a_flow_artifact_comment_image_is_not_counted(self) -> None:
        node = {
            "cover_image": "/private/files/khan-tay.jpg",
            "comments": [
                {"content": "[FLOW_V2_ARTIFACT] flow-1.png", "attachments": [], "image": "/files/flow-1.png"},
                {"content": "", "attachments": [], "image": "/files/flow-2.png"},
                {"content": "", "attachments": [], "image": "/files/ghi-chu.pdf"},
            ],
        }
        self.assertEqual(1, count_card_images(node))

    def test_a_flow_image_marked_only_in_meta_is_not_counted(self) -> None:
        # Ảnh Flow bây giờ lên thẻ không kèm chữ nào, dấu nằm ở ``meta``. Đọc
        # sót dấu ấy thì thẻ vừa chạy xong trông như vừa được thả ảnh mới, và
        # bot sẽ chạy lại nó vòng này qua vòng khác.
        node = {
            "cover_image": "/private/files/khan-tay.jpg",
            "comments": [
                {
                    "content": "\u200b",
                    "meta": "[FLOW_V2_ARTIFACT] flow-1.png",
                    "attachments": [{"file_url": "/files/flow-1.png", "file_name": "flow-1.png"}],
                    "image": "/files/flow-1.png",
                },
            ],
        }
        self.assertEqual(1, count_card_images(node))

    def test_a_card_whose_ideas_sit_in_one_comment_is_run(self) -> None:
        root = task_node("TASK-1", child_total=0)
        root.update({"status": "Open", "cover_image": "/private/files/khan-tay.jpg", "is_group": 1})
        root["comments"] = [{"name": "c1", "content": "(đã đính kèm tệp)", "attachments": [], "image": "/files/tho-noel.jpg"}]
        self.assertEqual(["TASK-1"], self._run(root)["tasks"])
        self.assertEqual(["TASK-1"], self.calls)

    def test_a_card_whose_dropped_files_the_bot_cannot_see_is_run(self) -> None:
        # TASK-2026-05740: hai mươi tấm idea thả vào một bình luận. Tệp riêng
        # tư, token của bot đọc về attachments rỗng, image rỗng; chỉ còn thân
        # do ERP tự ghi. Thẻ không bìa, không con - trước đây bị bỏ qua mãi.
        root = task_node("TASK-1", child_total=0)
        root.update({"status": "Open", "cover_image": "", "is_group": 1})
        root["comments"] = [{"name": "c1", "content": "(đã đính kèm tệp)", "attachments": [], "image": None, "is_bot": 0}]
        self.assertEqual(0, count_card_images(root))
        self.assertEqual(["TASK-1"], self._run(root)["tasks"])
        self.assertEqual(["TASK-1"], self.calls)

    def test_a_text_comment_alone_does_not_wake_a_childless_card(self) -> None:
        # Người dùng chỉ gõ chữ: không có tệp nào để tách, không giao.
        root = task_node("TASK-1", child_total=0)
        root.update({"status": "Open", "cover_image": "/private/files/khan-tay.jpg", "is_group": 1})
        root["comments"] = [{"name": "c1", "content": "làm tông đỏ nhé", "attachments": [], "image": None, "is_bot": 0}]
        self._run(root)
        self.assertEqual([], self.calls)

    def test_hidden_files_ignore_the_bot_and_flow_output(self) -> None:
        body = "(đã đính kèm tệp)"
        self.assertTrue(has_hidden_files({"comments": [{"content": body, "attachments": [], "image": None}]}))
        # Bot thấy được tệp thì count_card_images đã đếm, không phải tệp ẩn.
        self.assertFalse(has_hidden_files({"comments": [{"content": body, "attachments": [], "image": "/files/a.jpg"}]}))
        self.assertFalse(has_hidden_files({"comments": [{"content": body, "is_bot": 1, "attachments": []}]}))
        self.assertFalse(
            has_hidden_files({"comments": [{"content": body, "meta": "[FLOW_V2_ARTIFACT] flow-1.png", "attachments": []}]})
        )
        self.assertFalse(has_hidden_files({"comments": [{"content": "\u200b", "attachments": []}]}))
        self.assertFalse(has_hidden_files({"comments": []}))


class ClosedColumnTests(unittest.TestCase):
    """Cột kết thúc phải được nhận ra kể cả khi board đặt tên tiếng Việt."""

    def _card(self, status: str) -> Dict[str, Any]:
        return {"name": "TASK-1", "child_total": 3, "status": status}

    def test_the_real_columns_of_proj_0013(self) -> None:
        for status in ("Open", "Working", "Pending Review"):
            self.assertTrue(is_idea_card(self._card(status)), status)
        for status in ("Completed", "Cancelled"):
            self.assertFalse(is_idea_card(self._card(status)), status)

    def test_a_vietnamese_board_closes_its_cards_too(self) -> None:
        # Bot chạy trên *bất kỳ* board nào nó được thêm vào, và app này nói
        # tiếng Việt — một board đặt cột là "Đã hủy" hoàn toàn có thật. So
        # nguyên văn chữ tiếng Anh thì thẻ người ta đã huỷ vẫn được đếm là
        # việc đang chờ, và bot đốt quota tạo ảnh cho nó.
        for status in ("Đã hủy", "Huỷ bỏ", "Hoàn thành", "Đã đóng"):
            self.assertFalse(is_idea_card(self._card(status)), status)
        for status in ("Chờ duyệt", "Đang làm", "Mới"):
            self.assertTrue(is_idea_card(self._card(status)), status)

    def test_the_d_with_stroke_is_folded_before_accents_are_stripped(self) -> None:
        # ``đ`` là một chữ cái riêng, không phải ``d`` cộng dấu, nên
        # ``unicodedata`` không tách được nó. Không gấp nó lại trước thì
        # "Đã hủy" nén thành "ahuy" và bảng ở trên phải viết đúng chuỗi trông
        # như gõ nhầm ấy mới khớp.
        self.assertEqual("dahuy", compact_status("Đã hủy"))
        self.assertEqual("dahuy", compact_status("  ĐÃ HỦY  "))
        self.assertEqual("pendingreview", compact_status("Pending Review"))
        self.assertEqual("", compact_status(None))


class IdentityTests(unittest.TestCase):
    """How the bot learns which ERP user it is."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_it_reads_its_own_identity_off_a_comment_marked_mine(self) -> None:
        # Free, and it avoids writing a probe comment onto somebody's card.
        client = FakeClient([], {}, {})
        config = AgentBotConfig(token="t0ken")
        bot = AgentBot(config, client=client, state=AgentBotState.load(self.tmp / "s.json"))
        trees = [{"root": task_node("TASK-1", comments=[comment("c1", mine=1)])}]
        self.assertEqual(BOT, bot.resolve_bot_user(trees))

    def test_a_card_with_only_other_peoples_comments_teaches_it_nothing(self) -> None:
        client = FakeClient([], {}, {})
        bot = AgentBot(AgentBotConfig(token="t0ken"), client=client, state=AgentBotState.load(self.tmp / "s.json"))
        trees = [{"root": task_node("TASK-1", comments=[comment("c1", mine=0, owner="phong@havigroup.llc")])}]
        self.assertEqual("", bot.resolve_bot_user(trees))

    def test_the_write_probe_cleans_up_after_itself(self) -> None:
        class ProbeClient(FakeClient):
            def task_full(self, name: str, depth: int = 1) -> Dict[str, Any]:
                posted = self.comments[-1][1]
                return {"root": task_node(name, comments=[comment("probe", mine=1, content=posted, attachments=[])])}

        client = ProbeClient([], {}, {})
        bot = AgentBot(AgentBotConfig(token="t0ken"), client=client, state=AgentBotState.load(self.tmp / "s.json"))
        self.assertEqual(BOT, bot.probe_bot_user("TASK-1"))
        self.assertEqual([("TASK-1", "probe")], client.deleted)


class ChatTests(unittest.TestCase):
    """Nói chuyện với agent ngay trên thẻ: hỏi thì được trả lời, ra lệnh thì bot nghe."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _tree(self, *comments: Dict[str, Any], name: str = "TASK-1") -> Dict[str, Any]:
        return {"root": task_node(name, agents=[BOT], comments=list(comments), child_total=2)}

    def test_a_named_question_is_answered_inside_its_own_thread(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        answered = bot.chat_pass(self._tree(question("q1", "@bot trạng thái thế nào rồi")), BOT)

        self.assertEqual(1, len(answered))
        self.assertEqual("status", answered[0]["intent"])
        task, content, parent, meta = client.comments[0]
        self.assertEqual("TASK-1", task)
        # Trả lời vào đúng thread của câu hỏi, không đẻ thêm một cột bình luận rời.
        self.assertEqual("q1", parent)
        self.assertIn("TASK-1", content)
        # Dấu nằm ở meta nên người đọc thấy câu trả lời sạch, còn bot vẫn nhận ra bài mình.
        self.assertIn("[AGENT_BOT]", meta)
        self.assertNotIn("[AGENT_BOT]", content)

    def test_two_people_talking_to_each_other_are_left_alone(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        answered = bot.chat_pass(self._tree(question("q1", "chị duyệt hộ em bộ ảnh này với")), BOT)

        self.assertEqual([], answered)
        self.assertEqual([], client.comments)

    def test_a_reply_inside_the_bots_own_thread_needs_no_name(self) -> None:
        thread = comment("bot-post", mine=1, replies=[question("r1", "chạy lại giúp mình")])
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        answered = bot.chat_pass(self._tree(thread), BOT)

        self.assertEqual(["run"], [item["intent"] for item in answered])
        # Reply cấp hai vẫn đăng vào thread gốc, vì đó là thread ERP mở ra.
        self.assertEqual("bot-post", client.comments[0][2])

    def test_small_talk_inside_the_bots_thread_stays_unanswered(self) -> None:
        # "ok em", "đẹp đấy" mà lần nào cũng bị dội lại một bản hướng dẫn thì
        # chính bot dạy người ta bỏ qua nó.
        thread = comment("bot-post", mine=1, replies=[question("r1", "ok em đẹp đấy")])
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        self.assertEqual([], bot.chat_pass(self._tree(thread), BOT))
        self.assertEqual([], client.comments)

    def test_a_question_is_answered_once_and_never_again(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        tree = self._tree(question("q1", "@bot sku"))
        bot.chat_pass(tree, BOT)
        bot.chat_pass(tree, BOT)
        self.assertEqual(1, len(client.comments))

    def test_stop_parks_the_card_and_the_run_pass_obeys(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        ran: List[str] = []

        async def hook(task_id: str) -> Dict[str, Any]:
            ran.append(task_id)
            return {}

        bot.autorun_hook = hook
        tree = self._tree(question("q1", "@bot dừng lại đã"))
        self.assertEqual(["pause"], [item["intent"] for item in bot.chat_pass(tree, BOT)])
        self.assertTrue(bot.state.is_paused("TASK-1"))
        self.assertIsNone(asyncio.run(bot.autorun_pass(tree)))
        self.assertEqual([], ran)

    def test_resume_unparks_the_card_and_clears_the_cooldown(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        bot.state.pause("TASK-1")
        bot.state.mark_autorun("TASK-1")
        ran: List[str] = []

        async def hook(task_id: str) -> Dict[str, Any]:
            ran.append(task_id)
            return {}

        bot.autorun_hook = hook
        tree = self._tree(question("q1", "@bot tiếp tục"))
        self.assertEqual(["resume"], [item["intent"] for item in bot.chat_pass(tree, BOT)])
        self.assertFalse(bot.state.is_paused("TASK-1"))
        asyncio.run(bot.autorun_pass(tree))
        self.assertEqual(["TASK-1"], ran)

    def test_run_takes_effect_in_the_same_scan(self) -> None:
        # Lệnh "chạy đi" mà phải đợi thêm một chu kỳ nữa thì người ra lệnh chỉ
        # thấy bot đứng im — đúng thứ tính năng này sinh ra để chữa.
        row = {"name": "TASK-1", "agents": [{"bot_user": BOT}], "child_total": 2}
        tree = self._tree(question("q1", "@bot chạy lại đi"))
        client = FakeClient(["PROJ-0049"], {"PROJ-0049": [row]}, {"TASK-1": tree})
        bot = build_bot(client, self.tmp, autorun_cooldown_seconds=900)
        bot.state.mark_autorun("TASK-1")
        ran: List[str] = []

        async def hook(task_id: str) -> Dict[str, Any]:
            ran.append(task_id)
            return {}

        bot.autorun_hook = hook
        summary = asyncio.run(bot.run_once())

        self.assertEqual(["run"], [item["intent"] for item in summary["chats"]])
        self.assertEqual(["TASK-1"], ran)

    def test_a_pause_on_a_child_card_stops_the_whole_cluster(self) -> None:
        child = task_node("TASK-2", comments=[question("q1", "@bot dừng lại")])
        tree = {"root": task_node("TASK-1", agents=[BOT], subtasks=[child], child_total=1)}
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        bot.chat_pass(tree, BOT)
        self.assertTrue(bot.state.is_paused("TASK-1"))

    def test_the_status_answer_counts_images_the_bot_cannot_delete(self) -> None:
        # Ảnh hôm nay do service.py đăng dưới danh tính người thật (mine = 0).
        # Người hỏi "còn mấy ảnh chờ" muốn biết trên thẻ có gì, không muốn nghe
        # bot kể phần nào thuộc quyền ai.
        theirs = comment("img1", mine=0, owner="phong.hothanh@havigroup.llc", like=1)
        waiting = comment("img2", mine=0, owner="phong.hothanh@havigroup.llc")
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        bot.chat_pass(self._tree(theirs, waiting, question("q1", "@bot trạng thái")), BOT)
        self.assertIn("1 đã giữ", client.comments[0][1])
        self.assertIn("1 đang chờ", client.comments[0][1])

    def test_dry_run_says_what_it_would_answer_and_writes_nothing(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp, dry_run=True)
        answered = bot.chat_pass(self._tree(question("q1", "@bot dừng lại")), BOT)

        self.assertTrue(answered[0]["dry_run"])
        self.assertIn("tạm dừng", answered[0]["reply"])
        self.assertEqual([], client.comments)
        self.assertFalse(bot.state.is_paused("TASK-1"))
        self.assertFalse(bot.state.already_handled("q1"))

    def test_a_scan_answers_at_most_the_configured_number_of_questions(self) -> None:
        # Một board vừa thả bot vào có thể mang cả trăm bình luận cũ; trả lời
        # hết một lượt là đổ một trận mưa thông báo lên đầu cả nhóm.
        asked = [question(f"q{index}", "@bot trạng thái") for index in range(5)]
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp, max_chat_replies_per_scan=2)
        self.assertEqual(2, len(bot.chat_pass(self._tree(*asked), BOT)))
        self.assertEqual(2, len(client.comments))

    def test_a_failed_post_is_not_written_off_as_answered(self) -> None:
        client = FakeClient([], {}, {})

        def refuse(*args, **kwargs):
            raise AgentBotError("ERP đang giới hạn tốc độ")

        client.add_comment = refuse  # type: ignore[assignment]
        bot = build_bot(client, self.tmp)
        self.assertEqual([], bot.chat_pass(self._tree(question("q1", "@bot sku")), BOT))
        # Câu hỏi phải còn nguyên cho lượt sau, nếu không nó chìm luôn.
        self.assertFalse(bot.state.already_handled("q1"))

    def test_chat_can_be_switched_off(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp, chat=False)
        self.assertEqual([], bot.chat_pass(self._tree(question("q1", "@bot trạng thái")), BOT))
        self.assertEqual([], client.comments)


class ChatEditTests(unittest.TestCase):
    """“acc: acc32” gõ trên thẻ phải thành một dòng thật trong khối Thuộc tính."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.written: List[Any] = []

    def _tree(self, *comments: Dict[str, Any]) -> Dict[str, Any]:
        return {"root": task_node("TASK-1", agents=[BOT], comments=list(comments))}

    def _bot(self, client: FakeClient, hook: Any = None, **overrides) -> AgentBot:
        bot = build_bot(client, self.tmp, **overrides)
        bot.edit_hook = hook if hook is not None else self._record
        return bot

    def _record(self, task_id: str, edits) -> Dict[str, Any]:
        self.written.append((task_id, tuple(edits)))
        return {"task_id": task_id, "written": dict(edits)}

    def test_a_spoken_edit_reaches_the_write_hook(self) -> None:
        client = FakeClient([], {}, {})
        bot = self._bot(client)
        answered = bot.chat_pass(self._tree(question("q1", "@bot acc: acc32")), BOT)

        self.assertEqual(["set"], [item["intent"] for item in answered])
        self.assertEqual([("TASK-1", (("acc", "acc32"),))], self.written)
        self.assertIn("Tôi ghi acc", client.comments[0][1])

    def test_the_edit_lands_on_the_card_that_was_talked_to(self) -> None:
        # Người ta mở thẻ con ra gõ thì sửa thẻ con. Ghi lên thẻ gốc là sửa
        # nhầm thẻ, và không ai nhìn thấy để sửa lại.
        child = task_node("TASK-2", comments=[question("q1", "@bot product: khăn tay")])
        tree = {"root": task_node("TASK-1", agents=[BOT], subtasks=[child])}
        bot = self._bot(FakeClient([], {}, {}))
        bot.chat_pass(tree, BOT)

        self.assertEqual([("TASK-2", (("product", "khăn tay"),))], self.written)

    def test_a_refused_write_is_admitted_in_the_same_breath(self) -> None:
        # Hứa "tôi ghi rồi" trong khi thẻ không đổi gì là thứ tệ hơn cả im lặng:
        # người ra lệnh bỏ đi, tin là xong.
        def refuse(task_id: str, edits) -> Dict[str, Any]:
            raise RuntimeError("ERP không nhận")

        client = FakeClient([], {}, {})
        bot = self._bot(client, hook=refuse)
        answered = bot.chat_pass(self._tree(question("q1", "@bot acc: acc32")), BOT)

        self.assertIn("ERP không nhận", client.comments[0][1])
        self.assertIn("nguyên như cũ", client.comments[0][1])
        self.assertIn("ERP không nhận", answered[0]["error"])

    def test_a_machine_with_no_write_path_says_so_instead_of_nodding(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)  # cố ý không nối hook
        bot.chat_pass(self._tree(question("q1", "@bot acc: acc32")), BOT)

        self.assertIn("chưa nối đường ghi", client.comments[0][1])

    def test_dry_run_names_the_fields_and_writes_nothing(self) -> None:
        client = FakeClient([], {}, {})
        bot = self._bot(client, dry_run=True)
        answered = bot.chat_pass(self._tree(question("q1", "@bot acc: acc32")), BOT)

        self.assertEqual({"acc": "acc32"}, answered[0]["edits"])
        self.assertEqual([], self.written)
        self.assertEqual([], client.comments)

    def test_a_question_about_the_account_still_writes_nothing(self) -> None:
        client = FakeClient([], {}, {})
        bot = self._bot(client)
        bot.chat_pass(self._tree(question("q1", "@bot acc nào vậy")), BOT)

        self.assertEqual([], self.written)

    def test_the_book_is_consulted_before_warning_about_an_account(self) -> None:
        # Sổ tay nằm ở bot, còn phần soạn lời thì không cầm sổ — nên brief phải
        # mang cả quyển sang. Quên chỗ này thì mọi acc đều bị kêu là lạ.
        from flow_web.account_book import Account, AccountBook

        client = FakeClient([], {}, {})
        bot = self._bot(client)
        bot.book = AccountBook(entries={"acc32": Account(account_id="acc32", shop="Havi Home")})
        bot.chat_pass(self._tree(question("q1", "@bot acc: acc32")), BOT)

        self.assertNotIn("sổ tay tài khoản chưa có", client.comments[0][1])


class ChatSkuTests(unittest.TestCase):
    """“Điền sku đi” gõ trên thẻ phải chạy ra đường đánh số thật của app.

    Đây là chỗ vá lại cái phải làm bằng tay suốt: đổi ``product:`` xong thì
    còn phải có ai đó gọi một lượt cấp mã, mà người gõ ``product:`` thì đang
    đứng trên ERP chứ không đứng ở dòng lệnh.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.goi: List[Any] = []

    def _tree(self, *comments: Dict[str, Any]) -> Dict[str, Any]:
        return {"root": task_node("TASK-1", agents=[BOT], comments=list(comments))}

    def _bot(self, client: FakeClient, hook: Any = None, **overrides) -> AgentBot:
        bot = build_bot(client, self.tmp, **overrides)
        bot.sku_hook = hook if hook is not None else self._record
        return bot

    def _record(self, root_task_id: str, renumber: bool) -> Dict[str, Any]:
        self.goi.append((root_task_id, renumber))
        return {"written": [{"task_id": "TASK-2", "sku": "BT_1_001"}], "failed": [], "skipped": []}

    def test_a_spoken_order_reaches_the_sku_hook(self) -> None:
        client = FakeClient([], {}, {})
        answered = self._bot(client).chat_pass(
            self._tree(question("q1", "@bot điền sku đi")), BOT)

        self.assertEqual(["sku_fill"], [item["intent"] for item in answered])
        self.assertEqual([("TASK-1", False)], self.goi)

    def test_the_order_numbers_the_whole_cluster_not_the_card_spoken_on(self) -> None:
        # Số cuối trong mã là hàng chung. Đánh riêng một nhánh thì nhánh kia
        # cũng mở màn bằng ``_001`` và hai sản phẩm khác nhau mang chung mã.
        child = task_node("TASK-2", comments=[question("q1", "@bot điền sku đi")])
        tree = {"root": task_node("TASK-1", agents=[BOT], subtasks=[child])}
        self._bot(FakeClient([], {}, {})).chat_pass(tree, BOT)

        self.assertEqual([("TASK-1", False)], self.goi)

    def test_renumbering_carries_the_overwrite_flag_across(self) -> None:
        # Cờ này là khác biệt giữa "điền chỗ trống" và "xoá mã đã in lên tem".
        client = FakeClient([], {}, {})
        self._bot(client).chat_pass(self._tree(question("q1", "@bot đánh số lại")), BOT)

        self.assertEqual([("TASK-1", True)], self.goi)

    def test_asking_what_the_code_is_writes_nothing(self) -> None:
        client = FakeClient([], {}, {})
        self._bot(client).chat_pass(
            self._tree(question("q1", "@bot sku của thẻ này là gì")), BOT)

        self.assertEqual([], self.goi)

    def test_the_answer_names_the_codes_it_actually_wrote(self) -> None:
        # "Xong rồi" nói cho một lượt ghi 0 thẻ và một lượt ghi 10 thẻ nghe
        # giống hệt nhau, mà cái thứ nhất nghĩa là có gì đó đang chặn.
        def hook(root: str, renumber: bool) -> Dict[str, Any]:
            return {"written": [{"task_id": "TASK-2", "sku": "BT_1_001"},
                                {"task_id": "TASK-3", "sku": "BT_1_002"}]}

        client = FakeClient([], {}, {})
        self._bot(client, hook=hook).chat_pass(
            self._tree(question("q1", "@bot điền sku đi")), BOT)

        loi = client.comments[0][1]
        self.assertIn("2 thẻ", loi)
        self.assertIn("TASK-2 → BT_1_001", loi)
        self.assertIn("TASK-3 → BT_1_002", loi)

    def test_a_run_that_changed_nothing_says_so_without_crying_failure(self) -> None:
        # Cụm đã đủ mã là chuyện bình thường, không phải lỗi — nhưng im lặng
        # thì người ra lệnh không biết bot có nghe thấy hay không.
        client = FakeClient([], {}, {})
        answered = self._bot(client, hook=lambda root, renumber: {}).chat_pass(
            self._tree(question("q1", "@bot điền sku đi")), BOT)

        self.assertIn("Không thẻ nào phải đổi mã", client.comments[0][1])
        self.assertNotIn("error", answered[0])

    def test_the_reason_a_card_was_skipped_comes_back_to_the_person(self) -> None:
        # Lý do hay gặp nhất: thẻ gốc chưa có dòng ``product:`` nên không tra
        # được bảng SKU. Người ta sửa được ngay — nếu biết.
        def hook(root: str, renumber: bool) -> Dict[str, Any]:
            return {"written": [], "skipped": [
                {"task_id": "TASK-2", "reason": "thẻ gốc chưa có product"}]}

        client = FakeClient([], {}, {})
        self._bot(client, hook=hook).chat_pass(
            self._tree(question("q1", "@bot điền sku đi")), BOT)

        self.assertIn("thẻ gốc chưa có product", client.comments[0][1])

    def test_a_card_that_kept_its_old_name_is_reported_too(self) -> None:
        # Ghi mã xong thì thẻ đổi tên theo mã. Đổi tên hỏng mà không nói ra
        # thì người ta nhìn bảng thấy tên cũ và tưởng cả lượt chưa chạy.
        def hook(root: str, renumber: bool) -> Dict[str, Any]:
            return {
                "written": [{"task_id": "TASK-2", "sku": "BT_1_001"}],
                "rename_failed": [{"task_id": "TASK-2", "sku": "BT_1_001", "error": "ERP trả 500"}],
            }

        client = FakeClient([], {}, {})
        self._bot(client, hook=hook).chat_pass(
            self._tree(question("q1", "@bot điền sku đi")), BOT)

        loi = client.comments[0][1]
        self.assertIn("TASK-2 → BT_1_001", loi)
        self.assertIn("giữ tên cũ", loi)
        self.assertIn("ERP trả 500", loi)

    def test_a_long_run_is_summarised_instead_of_flooding_the_card(self) -> None:
        # Một bình luận, không phải bản log: kể tên ba mươi thẻ thì cái lý do
        # quan trọng nhất trôi mất tăm.
        def hook(root: str, renumber: bool) -> Dict[str, Any]:
            return {"written": [{"task_id": f"TASK-{i}", "sku": f"BT_1_{i:03d}"}
                                for i in range(30)]}

        client = FakeClient([], {}, {})
        self._bot(client, hook=hook).chat_pass(
            self._tree(question("q1", "@bot điền sku đi")), BOT)

        loi = client.comments[0][1]
        self.assertIn("30 thẻ", loi)
        self.assertIn("và 25 thẻ nữa", loi)
        self.assertNotIn("TASK-29", loi)

    def test_a_machine_with_no_sku_path_says_so_instead_of_nodding(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)  # cố ý không nối hook
        answered = bot.chat_pass(self._tree(question("q1", "@bot điền sku đi")), BOT)

        self.assertIn("chưa nối đường đánh số", client.comments[0][1])
        self.assertIn("chưa nối đường đánh số", answered[0]["error"])

    def test_a_refused_run_is_admitted_in_the_same_breath(self) -> None:
        def refuse(root: str, renumber: bool) -> Dict[str, Any]:
            raise RuntimeError("ERP không nhận")

        client = FakeClient([], {}, {})
        answered = self._bot(client, hook=refuse).chat_pass(
            self._tree(question("q1", "@bot điền sku đi")), BOT)

        self.assertIn("ERP không nhận", client.comments[0][1])
        self.assertIn("nguyên như cũ", client.comments[0][1])
        self.assertIn("ERP không nhận", answered[0]["error"])

    def test_dry_run_calls_nothing_and_posts_nothing(self) -> None:
        client = FakeClient([], {}, {})
        self._bot(client, dry_run=True).chat_pass(
            self._tree(question("q1", "@bot đánh số lại")), BOT)

        self.assertEqual([], self.goi)
        self.assertEqual([], client.comments)


class ChatBrainTests(unittest.TestCase):
    """Câu ngoài từ khoá: bot nhờ Claude đọc hộ, rồi ghi bằng đường ghi cũ.

    Không test nào ở đây gọi ``claude`` thật — hook là hàm giả. Thứ đáng giữ
    không phải là model đoán giỏi tới đâu, mà là **ranh giới**: bảng từ khoá
    luôn được ưu tiên, phần đoán ý không mở thêm quyền nào, và hỏng thì rơi về
    đúng câu trả lời cũ chứ không làm chết một lượt quét.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.hoi: List[Any] = []
        self.ghi: List[Any] = []

    def _tree(self, *comments: Dict[str, Any]) -> Dict[str, Any]:
        return {"root": task_node("TASK-1", agents=[BOT], comments=list(comments))}

    def _bot(self, client: FakeClient, verdict: Any = "mac dinh", **overrides) -> AgentBot:
        bot = build_bot(client, self.tmp, **overrides)

        def brain(said: str, brief: Any) -> Any:
            self.hoi.append(said)
            if verdict == "mac dinh":
                return BrainVerdict(
                    edits=(("template", "mockup-bom-02"), ("product", "bờm nơ hồng")),
                    say="bạn muốn đổi mẫu và đặt lại tên sản phẩm",
                )
            return verdict

        bot.brain_hook = brain
        bot.edit_hook = lambda task_id, edits: self.ghi.append((task_id, tuple(edits)))
        return bot

    def test_cau_ngoai_tu_khoa_van_duoc_sua(self) -> None:
        # Đúng câu thật trên bảng thật mà bảng từ khoá chịu thua.
        client = FakeClient([], {}, {})
        answered = self._bot(client).chat_pass(
            self._tree(question("q1", "@bot đổi mẫu listing sang mockup-bom-02 "
                                      "với lại thẻ này là bờm nơ hồng nhé")), BOT)

        self.assertEqual(["brain_set"], [item["intent"] for item in answered])
        self.assertEqual(
            [("TASK-1", (("template", "mockup-bom-02"), ("product", "bờm nơ hồng")))],
            self.ghi,
        )

    def test_bot_ke_lai_no_hieu_gi(self) -> None:
        # Câu tự do có chỗ hiểu sai; người đọc chỉ bắt được khi thấy diễn giải.
        client = FakeClient([], {}, {})
        self._bot(client).chat_pass(self._tree(question("q1", "@bot đổi mẫu đi mà")), BOT)
        posted = client.comments[0][1]
        self.assertIn("Tôi hiểu là bạn muốn đổi mẫu", posted)
        self.assertIn("mockup-bom-02", posted)

    def test_bang_tu_khoa_thang_thi_khong_ton_mot_luot_hoi(self) -> None:
        # "acc: acc32" hiểu được không mất tiền, và phải luôn như vậy.
        client = FakeClient([], {}, {})
        self._bot(client).chat_pass(self._tree(question("q1", "@bot acc: acc32")), BOT)
        self.assertEqual([], self.hoi)

    def test_cau_buot_mieng_trong_thread_bot_khong_ton_luot_hoi(self) -> None:
        # "ok em" không phải lệnh; im lặng vẫn đúng, và đúng miễn phí.
        reply = question("r1", "ok em", mine=0)
        thread = question("q1", "Đã xong nhé", is_bot=1, mine=1, replies=[reply])
        client = FakeClient([], {}, {})
        answered = self._bot(client).chat_pass(self._tree(thread), BOT)

        self.assertEqual([], answered)
        self.assertEqual([], self.hoi)

    def test_mot_chu_giup_lac_trong_cau_khong_lam_hong_lenh(self) -> None:
        # Câu thật: bảng từ khoá bắt chữ "giúp" rồi dội ra bản hướng dẫn, còn
        # việc người ta nhờ thì không ai làm.
        client = FakeClient([], {}, {})
        bot = self._bot(client, verdict=BrainVerdict(edits=(("acc", "acc32"),), say="cho acc về acc32"))
        answered = bot.chat_pass(
            self._tree(question("q1", "@bot ơi cái acc lúc nãy anh nói nhầm, "
                                      "cho về acc32 giúp anh với")), BOT)

        self.assertEqual(["brain_set"], [item["intent"] for item in answered])
        self.assertEqual([("TASK-1", (("acc", "acc32"),))], self.ghi)

    def test_goi_ten_roi_thoi_van_ra_ban_huong_dan_khong_ton_luot_hoi(self) -> None:
        # "@bot" trống là "ê, mày làm được gì" — câu ấy đã có sẵn câu trả lời.
        client = FakeClient([], {}, {})
        bot = self._bot(client, verdict=None)
        answered = bot.chat_pass(self._tree(question("q1", "@bot")), BOT)

        self.assertEqual(["help"], [item["intent"] for item in answered])
        self.assertEqual([], self.ghi)

    def test_cau_hoi_tinh_trang_khong_ton_mot_luot_hoi(self) -> None:
        # Câu hỏi đã có câu trả lời đúng sẵn; hỏi thêm chỉ tốn tiền và mở cửa
        # cho một lượt đoán ý ghi đè lên nó.
        client = FakeClient([], {}, {})
        self._bot(client).chat_pass(self._tree(question("q1", "@bot sku của thẻ này là gì")), BOT)
        self.assertEqual([], self.hoi)

    def test_claude_doc_xong_ma_khong_rut_ra_o_nao_thi_tra_loi_nhu_cu(self) -> None:
        client = FakeClient([], {}, {})
        answered = self._bot(client, verdict=BrainVerdict(refused="chỉ là lời chào")).chat_pass(
            self._tree(question("q1", "@bot chào em nhé")), BOT)

        self.assertEqual(["unknown"], [item["intent"] for item in answered])
        self.assertEqual([], self.ghi)

    def test_khong_noi_phan_doan_y_thi_moi_thu_y_nhu_truoc(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)
        answered = bot.chat_pass(self._tree(question("q1", "@bot đổi mẫu đi mà")), BOT)

        self.assertEqual(["unknown"], [item["intent"] for item in answered])

    def test_phan_doan_y_hong_thi_khong_lam_chet_luot_quet(self) -> None:
        client = FakeClient([], {}, {})
        bot = build_bot(client, self.tmp)

        def no(said: str, brief: Any) -> Any:
            raise RuntimeError("máy chưa đăng nhập claude")

        bot.brain_hook = no
        answered = bot.chat_pass(self._tree(question("q1", "@bot đổi mẫu đi mà")), BOT)
        self.assertEqual(["unknown"], [item["intent"] for item in answered])

    def test_tran_moi_luot_quet_chan_mot_bang_dang_tan_gau(self) -> None:
        # Mỗi lượt hỏi là tiền thật, nên một bảng ồn ào không được thành hoá đơn.
        client = FakeClient([], {}, {})
        cards = [
            task_node(f"TASK-{i}", comments=[question(f"q{i}", "@bot đổi mẫu đi mà")])
            for i in range(2, 8)
        ]
        tree = {"root": task_node("TASK-1", agents=[BOT], subtasks=cards)}
        bot = self._bot(client, max_chat_replies_per_scan=99)
        bot.brain_max_calls = 2
        bot.chat_pass(tree, BOT)

        self.assertEqual(2, len(self.hoi))

    def test_tran_la_tran_cua_ca_bang_chu_khong_phai_cua_moi_the(self) -> None:
        # Trần đếm theo *lượt quét*, nên hai thẻ gốc trên cùng một bảng phải
        # chia nhau đúng ngần ấy lượt hỏi. Đếm lại ở mỗi cây thì một bảng ba
        # mươi thẻ tiêu ba mươi lần trần, và hoá đơn nhân lên thầm lặng.
        # Ba câu mỗi thẻ, trần là hai: mỗi cây tự nó đã đủ chạm trần, nên nếu
        # bộ đếm đặt lại ở mỗi cây thì tổng ra bốn chứ không phải hai.
        noi = lambda ten: task_node(
            ten,
            agents=[BOT],
            comments=[question("q%s-%d" % (ten, i), "@bot đổi mẫu đi mà")
                      for i in range(3)],
        )
        client = FakeClient(
            ["PROJ-1"],
            {"PROJ-1": [{"name": "TASK-1", "agents": [{"bot_user": BOT}]},
                        {"name": "TASK-2", "agents": [{"bot_user": BOT}]}]},
            {"TASK-1": {"root": noi("TASK-1")}, "TASK-2": {"root": noi("TASK-2")}},
        )
        bot = self._bot(client, autorun=False)
        bot.brain_max_calls = 2
        summary = asyncio.run(bot.run_once())

        self.assertEqual(["TASK-1", "TASK-2"], summary["tasks"])
        self.assertEqual(2, len(self.hoi))

    def test_goi_le_mot_cay_thi_cay_ay_la_ca_luot(self) -> None:
        # Gọi ``chat_pass`` ngoài ``run_once`` (script tay, test) không có ai
        # đặt trần hộ, nên nó phải tự đếm lại — nếu không, lượt gọi thứ hai
        # thừa hưởng bộ đếm cũ và im lặng không hỏi gì.
        client = FakeClient([], {}, {})
        bot = self._bot(client)
        bot.brain_max_calls = 1
        bot.chat_pass(self._tree(question("q1", "@bot đổi mẫu đi mà")), BOT)
        bot.chat_pass(self._tree(question("q2", "@bot đổi mẫu đi nữa")), BOT, True)

        self.assertEqual(2, len(self.hoi))

    def test_dem_lai_tu_dau_o_luot_quet_sau(self) -> None:
        # Trần là trần *mỗi lượt*: hết trần lượt này không phải là tắt hẳn.
        client = FakeClient([], {}, {})
        bot = self._bot(client)
        bot.brain_max_calls = 1
        bot.chat_pass(self._tree(question("q1", "@bot đổi mẫu đi mà")), BOT)
        bot.chat_pass(self._tree(question("q2", "@bot đổi mẫu đi nữa")), BOT)

        self.assertEqual(2, len(self.hoi))

    def test_o_ngoai_danh_sach_khong_bao_gio_toi_duoc_duong_ghi(self) -> None:
        # Hàng rào đôi: bên ``agent_brain`` lọc một lần, và đường ghi của app
        # lọc lần nữa. Đây là lần thứ nhất, đo từ phía bot.
        client = FakeClient([], {}, {})
        bot = self._bot(client, verdict=BrainVerdict(edits=(("acc", "acc16"),), say="đổi shop"))
        bot.chat_pass(self._tree(question("q1", "@bot chuyển thẻ này sang shop kia đi")), BOT)

        self.assertEqual([("TASK-1", (("acc", "acc16"),))], self.ghi)

    def test_chay_kho_thi_khong_ghi_gi_ca(self) -> None:
        client = FakeClient([], {}, {})
        bot = self._bot(client, dry_run=True)
        bot.chat_pass(self._tree(question("q1", "@bot đổi mẫu đi mà")), BOT)

        self.assertEqual([], self.ghi)
        self.assertEqual([], client.comments)


class NetworkFailureTests(unittest.TestCase):
    """Một cái board đọc chậm không được phép giết cả vòng quét.

    ``urlopen`` hết giờ ném ``TimeoutError``, mà ``TimeoutError`` không phải là
    con của ``URLError``.  Bắt thiếu nó thì lỗi mạng thường gặp nhất chui thẳng
    qua chỗ ``candidate_tasks`` bắt lỗi từng dự án và làm hỏng cả lượt — mọi câu
    hỏi đang chờ trả lời và mọi thẻ đang chờ chạy mất theo.  Gặp trên ERP thật:
    ``POST /api/agent-bot/run`` trả 500 sau 93 giây.
    """

    def _client(self):
        from flow_web.agent_bot import AgentBotClient

        return AgentBotClient(AgentBotConfig(token="t", timeout_s=0.01))

    def test_a_timeout_becomes_a_readable_bot_error(self) -> None:
        from unittest.mock import patch

        client = self._client()
        with patch("flow_web.agent_bot.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(AgentBotError):
                client.graphql("query Q { q }", {}, "Q", retries=0)

    def test_a_timeout_is_retried_like_any_other_network_hiccup(self) -> None:
        from unittest.mock import patch

        calls = {"n": 0}

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"data": {"ok": 1}}'

        def flaky(request, timeout=0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("timed out")
            return _Response()

        client = self._client()
        with patch("flow_web.agent_bot.urlopen", side_effect=flaky), patch("flow_web.agent_bot.time.sleep"):
            self.assertEqual({"ok": 1}, client.graphql("query Q { q }", {}, "Q", retries=1))
        self.assertEqual(2, calls["n"])

    def test_one_slow_board_only_loses_that_project(self) -> None:
        from unittest.mock import patch

        bot = AgentBot(AgentBotConfig(token="t"))
        good = {"name": "TASK-1", "agents": [{"bot_user": "b"}], "status": "Open"}

        def boards(project: str):
            if project == "PROJ-SLOW":
                raise AgentBotError("hết giờ đọc")
            return [good], ("Open",)

        with patch.object(bot.client, "board_snapshot", side_effect=boards):
            found = bot.candidate_tasks(["PROJ-SLOW", "PROJ-OK"], "b")
        self.assertEqual(["TASK-1"], [task["name"] for task in found])


class StateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_corrupt_state_file_starts_empty_rather_than_crashing(self) -> None:
        path = self.tmp / "state.json"
        path.write_text("{ not json", encoding="utf-8")
        state = AgentBotState.load(path)
        self.assertEqual({}, state.handled)

    def test_old_decisions_are_pruned_but_recent_ones_are_not(self) -> None:
        state = AgentBotState(path=self.tmp / "state.json")
        old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds")
        state.handled = {
            "old": {"task": "T", "decision": "keep", "at": old},
            "new": {"task": "T", "decision": "keep", "at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        }
        state.prune()
        self.assertEqual(["new"], sorted(state.handled))

    def test_a_state_file_from_before_the_split_still_feeds_the_fast_lane(self) -> None:
        # Sổ cũ chỉ có "projects". Đọc lên mà bỏ trống thì làn nhanh mù cho tới
        # lượt quét chính đầu tiên — mất vài phút không ai đánh số.
        path = self.tmp / "state.json"
        path.write_text(json.dumps({"projects": ["PROJ-0013", "PROJ-0049"]}), encoding="utf-8")
        state = AgentBotState.load(path)
        self.assertEqual(["PROJ-0013", "PROJ-0049"], state.fast_lane_projects)

    def test_an_empty_fast_lane_list_on_disk_is_obeyed_not_refilled(self) -> None:
        # Đã lọc ra rỗng thật thì tôn trọng, đừng "sửa" thành cả phạm vi.
        path = self.tmp / "state.json"
        path.write_text(
            json.dumps({"projects": ["PROJ-0013"], "fast_lane_projects": []}), encoding="utf-8"
        )
        self.assertEqual([], AgentBotState.load(path).fast_lane_projects)

    def test_saving_leaves_no_half_written_file_behind(self) -> None:
        state = AgentBotState(path=self.tmp / "state.json")
        state.record("c1", "TASK-1", "keep")
        state.save()
        self.assertEqual("c1", next(iter(json.loads(state.path.read_text(encoding="utf-8"))["handled"])))
        self.assertFalse(state.path.with_suffix(".tmp").exists())


class RateLimitTests(unittest.TestCase):
    def test_it_blocks_once_the_window_is_full(self) -> None:
        # The bot ceiling is 60/minute; going over turns a scan into a 429.
        limiter = _RateLimiter(limit=2, window_s=0.3)
        started = time.monotonic()
        for _ in range(3):
            limiter.acquire()
        self.assertGreaterEqual(time.monotonic() - started, 0.25)


class ConfigTests(unittest.TestCase):
    def test_the_project_list_accepts_commas_semicolons_and_stray_spaces(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"ERP_AGENT_TOKEN": "t", "ERP_AGENT_PROJECTS": " proj-0013 ; PROJ-0049,"}):
            config = AgentBotConfig.from_env()
        self.assertEqual(("PROJ-0013", "PROJ-0049"), config.projects)
        self.assertTrue(config.enabled)

    def test_narrowing_the_scope_still_keeps_the_project_the_app_lives_in(self) -> None:
        # Otherwise "add PROJ-0013 to the bot" would quietly take the bot off
        # the board the rest of Flow v2 is already pointed at.
        import os
        from unittest.mock import patch

        env = {"ERP_AGENT_TOKEN": "t", "ERP_AGENT_PROJECTS": "PROJ-0013", "ERP_PROJECT_ID": "PROJ-0049"}
        with patch.dict(os.environ, env):
            self.assertEqual(("PROJ-0013", "PROJ-0049"), AgentBotConfig.from_env().projects)

    def test_an_empty_project_list_still_means_every_visible_project(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"ERP_AGENT_TOKEN": "t", "ERP_AGENT_PROJECTS": "", "ERP_PROJECT_ID": "PROJ-0049"}):
            self.assertEqual((), AgentBotConfig.from_env().projects)

    def test_board_is_the_default_scope_and_card_is_opt_in(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"ERP_AGENT_TOKEN": "t", "ERP_AGENT_SCOPE": ""}):
            self.assertEqual("board", AgentBotConfig.from_env().scope)
        with patch.dict(os.environ, {"ERP_AGENT_TOKEN": "t", "ERP_AGENT_SCOPE": " Card "}):
            self.assertEqual("card", AgentBotConfig.from_env().scope)
        # Một giá trị gõ sai không được âm thầm tắt bot khỏi cả board.
        with patch.dict(os.environ, {"ERP_AGENT_TOKEN": "t", "ERP_AGENT_SCOPE": "cards"}):
            self.assertEqual("board", AgentBotConfig.from_env().scope)

    def test_the_column_warning_is_on_unless_it_is_turned_off(self) -> None:
        # Mặc định bật: người gặp cái bẫy này là người vừa thêm bot vào bảng
        # mới, tức là người chưa biết có biến môi trường nào để bật.
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"ERP_AGENT_TOKEN": "t"}, clear=True):
            self.assertTrue(AgentBotConfig.from_env().column_alert)
        with patch.dict(os.environ, {"ERP_AGENT_TOKEN": "t", "ERP_AGENT_COLUMN_ALERT": "0"}):
            self.assertFalse(AgentBotConfig.from_env().column_alert)

    def test_a_nonsense_alert_ceiling_falls_back_to_the_default(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"ERP_AGENT_TOKEN": "t", "ERP_AGENT_MAX_COLUMN_ALERTS": "3"}):
            self.assertEqual(3, AgentBotConfig.from_env().max_column_alerts)
        for rac in ("hai", " ", ""):
            with self.subTest(rac=rac):
                with patch.dict(
                    os.environ, {"ERP_AGENT_TOKEN": "t", "ERP_AGENT_MAX_COLUMN_ALERTS": rac}
                ):
                    self.assertEqual(
                        DEFAULT_MAX_COLUMN_ALERTS, AgentBotConfig.from_env().max_column_alerts
                    )

    def test_asking_for_zero_alerts_still_leaves_one_card_told(self) -> None:
        """Trần ``0`` không phải là cách tắt lời nhắc.

        Tắt hẳn đã có ``ERP_AGENT_COLUMN_ALERT=0``; một con số ``0`` gõ vào
        đây gần như luôn là gõ nhầm, và hiểu nó thành "im lặng" là dựng lại
        đúng cái bẫy im lặng mà cả hai biến này sinh ra để phá.
        """
        import os
        import tempfile
        from unittest.mock import patch

        with patch.dict(os.environ, {"ERP_AGENT_TOKEN": "t", "ERP_AGENT_MAX_COLUMN_ALERTS": "0"}):
            self.assertEqual(0, AgentBotConfig.from_env().max_column_alerts)

        the = [
            task_node(f"TASK-{n}", agents=[BOT], status="Backlog", child_total=1)
            for n in (1, 2, 3)
        ]
        client = FakeClient(["PROJ-1"], {"PROJ-1": the}, {}, columns={"PROJ-1": ["Backlog"]})
        with tempfile.TemporaryDirectory() as tmp:
            bot = build_bot(client, Path(tmp), max_column_alerts=0)
            bot.candidate_tasks(["PROJ-1"], BOT)
            self.assertEqual(1, len(bot.column_pass()))

    def test_the_source_column_accepts_commas_semicolons_and_stray_spaces(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"ERP_AGENT_TOKEN": "t", "ERP_AGENT_SOURCE_STATUS": ""}):
            self.assertEqual((), AgentBotConfig.from_env().source_statuses)
        with patch.dict(
            os.environ, {"ERP_AGENT_TOKEN": "t", "ERP_AGENT_SOURCE_STATUS": " Working ; Open,"}
        ):
            self.assertEqual(("Working", "Open"), AgentBotConfig.from_env().source_statuses)

    def test_pointing_the_source_column_at_a_closed_column_is_said_out_loud(self) -> None:
        # ``is_idea_card`` loại thẻ ở cột đã đóng *trước* hàng rào cột nguồn,
        # nên cấu hình này làm bot không bao giờ nhận việc mà không có lỗi nào
        # để đọc. Giá trị vẫn được giữ nguyên: cảnh báo, không sửa lưng người.
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"ERP_AGENT_TOKEN": "t", "ERP_AGENT_SOURCE_STATUS": "Đã hoàn thành"}):
            with self.assertLogs("flow_web.agent_bot", level="WARNING") as caught:
                config = AgentBotConfig.from_env()
        self.assertEqual(("Đã hoàn thành",), config.source_statuses)
        self.assertIn("Đã hoàn thành", "\n".join(caught.output))

    def test_an_empty_token_leaves_the_bot_off(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"ERP_AGENT_TOKEN": "  "}):
            self.assertFalse(AgentBotConfig.from_env().enabled)


# ── PRD list tự động lên Etsy (tasks/prd-list-tu-dong-etsy.md) ─────────────
# Các lớp dưới đây tả hành vi *sau khi cài*. Đỏ hôm nay là đúng.

from flow_web.erp_meta import task_meta as _task_meta


class ListingChildCardTests(unittest.TestCase):
    """T1 — hình dạng thật của thẻ trên ERP: cha khai, con mang ảnh.

    ``service.py`` tách một thẻ Idea thành mỗi thẻ con một ảnh, và người duyệt
    bấm 👍 trên **thẻ con**. Thẻ cha là nơi duy nhất có ``action_1: listing``
    (thẻ con được tạo trắng, "không một chữ nào lên thẻ"). Bộ test cũ chỉ
    dựng thẻ listing đứng một mình mang ảnh trên chính nó — hình dạng app
    không bao giờ tạo ra — nên xanh mà đường thật vẫn đứng.
    """

    PARENT_META = "action_1: listing\nacc: acc32"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.handed: List[tuple[str, Dict[str, Any]]] = []
        self.autorun_calls: List[str] = []
        self.pipeline_calls: List[str] = []
        self.asked: List[tuple[str, str]] = []

    async def _listing_hook(self, task_id: str, node: Dict[str, Any]) -> Dict[str, Any]:
        self.handed.append((task_id, node))
        return {"queue_task_id": f"etsy-copy-{len(self.handed)}", "machine_id": "etsy-vn32"}

    async def _autorun(self, task_id: str) -> Dict[str, Any]:
        self.autorun_calls.append(task_id)
        return {"queued": []}

    async def _pipeline(self, task_id: str) -> Dict[str, Any]:
        self.pipeline_calls.append(task_id)
        return {"moved": True}

    async def _confirm_done(self, queue_task_id: str, machine_id: str) -> Dict[str, Any]:
        self.asked.append((queue_task_id, machine_id))
        return {"done": True, "status": "completed"}

    def _child(self, name: str, *, comments, meta: str = "sku: KT-0001", status: str = "Pending Review"):
        # Thẻ con đã đi hết Cần làm → Đang làm (được điền SKU) → Đang review.
        # Nó KHÔNG có ``action_*``: đó là hình dạng ``_erp_create_child_task``
        # tạo ra, và cũng là lý do đường list đứng.
        return task_node(name, agents=[BOT], comments=comments, status=status,
                         parent_task="TASK-P", meta=meta)

    def _tree(self, *children: Dict[str, Any]) -> Dict[str, Any]:
        root = task_node("TASK-P", agents=[BOT], subtasks=list(children))
        root.update({"meta": self.PARENT_META, "status": "Working"})
        return root

    def _rows(self, root: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = [{"name": "TASK-P", "child_total": len(root["subtasks"]), "status": "Working",
                 "agents": [{"bot_user": BOT}], "parent_task": "", "attachment_count": 0}]
        for child in root["subtasks"]:
            rows.append({"name": child["name"], "child_total": 0, "status": child.get("status"),
                         "agents": [{"bot_user": BOT}], "parent_task": "TASK-P",
                         "attachment_count": 0})
        return rows

    def _sweep(self, root: Dict[str, Any], *, times: int = 1, confirm=None, pipeline=None):
        summaries = []
        bot = None
        for _ in range(times):
            client = FakeClient(["PROJ-0013"], {"PROJ-0013": self._rows(root)},
                                {"TASK-P": {"root": root}})
            bot = build_bot(client, self.tmp, autorun_cooldown_seconds=0)
            bot.listing_hook = self._listing_hook
            bot.listing_confirm_hook = confirm
            bot.autorun_hook = self._autorun
            bot.pipeline_hook = pipeline
            summaries.append(asyncio.run(bot.run_once()))
        return summaries, bot

    def test_the_child_carrying_the_approved_images_is_what_gets_handed_over(self) -> None:
        root = self._tree(self._child("TASK-P-a", comments=[comment("L-1", like=1), comment("L-2", like=2)]))
        summaries, bot = self._sweep(root)

        self.assertEqual(
            ["TASK-P-a"], [task_id for task_id, _ in self.handed],
            "listing_pass chỉ nhìn thẻ gốc: cha không có ảnh nên bot trả 'thẻ chưa có ảnh "
            "nào để đăng' và không bao giờ giao thẻ con đã 👍 cho bản Listing",
        )
        self.assertTrue(
            bot.state.already_listed("TASK-P-a"),
            "sổ listed phải ghi theo mã thẻ CON — đó là thẻ có ảnh, có SKU, và là thẻ "
            "luật cột sẽ đóng",
        )
        self.assertFalse(
            bot.state.already_listed("TASK-P"),
            "thẻ cha là cái hộp, không phải sản phẩm; ghi sổ cho cha thì lần sau không "
            "thẻ con nào được giao nữa",
        )

    def test_the_child_is_handed_over_with_the_parent_s_routing_lines(self) -> None:
        root = self._tree(self._child("TASK-P-a", comments=[comment("L-1", like=1)]))
        self._sweep(root)

        self.assertEqual(1, len(self.handed), "chưa giao thẻ con nào (xem bài trên)")
        task_id, node = self.handed[0]
        merged = _task_meta(node)
        self.assertTrue(
            merged.is_listing,
            "node đưa cho listing_hook phải mang action_1: listing thừa kế từ cha — "
            "ListingBridge.payload đọc task_meta(node) để định tuyến, thiếu dòng này "
            "thì payload không có action",
        )
        self.assertEqual(
            "acc32", merged.account_id,
            "acc: acc32 của cha phải đi theo thẻ con, nếu không ListingBridge.payload "
            "ném 'không tìm được máy' vì không biết tài khoản nào",
        )
        self.assertEqual(
            "TASK-P-a", str(node.get("name")),
            "node đưa cho hook phải là thẻ con (erp_task_id = thẻ con), không phải cha",
        )

    def test_a_child_s_own_line_wins_over_the_parent_s(self) -> None:
        root = self._tree(self._child("TASK-P-a", comments=[comment("L-1", like=1)],
                                      meta="sku: KT-0001\nacc: acc16"))
        self._sweep(root)

        self.assertEqual(1, len(self.handed), "chưa giao thẻ con nào (xem bài đầu)")
        merged = _task_meta(self.handed[0][1])
        self.assertEqual(
            "acc16", merged.account_id,
            "thừa kế là erp_meta.inherit(con, cha): dòng con viết luôn thắng — cha không "
            "được kéo con sang tài khoản khác",
        )
        self.assertTrue(merged.is_listing, "action của cha vẫn phải xuống con khi con không khai")

    def test_a_child_still_waiting_for_votes_is_not_handed_and_says_so_by_name(self) -> None:
        root = self._tree(self._child("TASK-P-a", comments=[comment("L-1", like=1), comment("L-2")]))
        summaries, _ = self._sweep(root)

        self.assertEqual([], [task_id for task_id, _ in self.handed],
                         "còn ảnh chờ 👍/👎 thì không được giao")
        lines = {line.get("task"): line for line in summaries[0]["listing"]}
        self.assertIn(
            "TASK-P-a", lines,
            "tóm tắt lượt quét phải có một dòng cho từng thẻ con listing; hôm nay chỉ có "
            "dòng của cha 'thẻ chưa có ảnh nào để đăng', đọc log không biết con nào đang kẹt",
        )
        self.assertEqual("còn 1 ảnh chờ 👍/👎", lines["TASK-P-a"].get("waiting"))

    def test_two_approved_children_are_two_handovers_with_two_receipts(self) -> None:
        root = self._tree(
            self._child("TASK-P-a", comments=[comment("L-1", like=1)]),
            self._child("TASK-P-b", comments=[comment("L-2", like=1)]),
        )
        _, bot = self._sweep(root)

        self.assertEqual(
            ["TASK-P-a", "TASK-P-b"], [task_id for task_id, _ in self.handed],
            "mỗi thẻ con là một sản phẩm đi lên listing riêng (pipeline._leave_doing) — "
            "hai con đã 👍 là hai lượt giao",
        )
        self.assertEqual("etsy-copy-1", bot.state.listing_handover("TASK-P-a").get("queue_task"))
        self.assertEqual("etsy-copy-2", bot.state.listing_handover("TASK-P-b").get("queue_task"))

    def test_the_second_sweep_asks_etsy_about_the_child_and_never_hands_it_twice(self) -> None:
        root = self._tree(self._child("TASK-P-a", comments=[comment("L-1", like=1)]))
        _, bot = self._sweep(root, times=2, confirm=self._confirm_done)

        self.assertEqual(1, len(self.handed), "lượt hai không được giao lại thẻ con đã có biên lai")
        self.assertEqual(
            [("etsy-copy-1", "etsy-vn32")], self.asked,
            "lượt hai phải hỏi bản Listing về đúng biên lai của thẻ CON; hôm nay không hỏi "
            "vì sổ chỉ ghi theo thẻ gốc",
        )
        self.assertTrue(bot.state.listing_confirmed("TASK-P-a"))

    def test_once_etsy_confirms_the_child_is_proposed_for_done(self) -> None:
        # Lượt 1 giao, lượt 2 hỏi lại → xác nhận, lượt 3 luật cột thấy
        # listing_confirmed(con) và đề nghị chuyển con sang Hoàn thành.
        root = self._tree(self._child("TASK-P-a", comments=[comment("L-1", like=1)]))
        self._sweep(root, times=3, confirm=self._confirm_done, pipeline=self._pipeline)

        self.assertIn(
            "TASK-P-a", self.pipeline_calls,
            "pipeline_pass dựng card_stage từ meta của chính thẻ con (không có action) nên "
            "is_listing=False và _leave_review trả 'chờ người làm listing' — thẻ con không "
            "bao giờ được đề nghị sang Hoàn thành dù bản Listing đã báo xong",
        )

    # ── chốt chặn thêm sau phán quyết hội đồng (hình dạng cha+con) ─────

    def test_images_posted_under_a_person_s_identity_still_hand_the_child_over(self) -> None:
        # App đăng ảnh review bằng ERP_API_KEY của người thật
        # (service._erp_publish_review_comment), nên bot đọc về mine=0. Phiếu
        # trên ảnh ấy vẫn phải mở cổng giao — count_decisions đếm cả hai tác giả.
        root = self._tree(self._child(
            "TASK-P-a",
            comments=[comment("L-1", mine=0, like=1), comment("L-2", mine=0, like=1)],
        ))
        self._sweep(root)

        self.assertEqual(
            ["TASK-P-a"], [task_id for task_id, _ in self.handed],
            "ảnh đăng dưới danh tính người (mine=0) đã 👍 đủ mà con không được giao: "
            "listing_readiness đang lọc theo tác giả",
        )

    def test_a_child_waiting_for_votes_keeps_the_image_half_open_on_the_parent(self) -> None:
        # Nửa ảnh chạy ở thẻ CHA: con còn ảnh chờ phiếu thì autorun_hook vẫn
        # nhận TASK-P, không nhận TASK-P-a, và không im.
        root = self._tree(self._child("TASK-P-a", comments=[comment("L-1", like=1), comment("L-2")]))
        self._sweep(root)

        self.assertEqual(
            ["TASK-P"], self.autorun_calls,
            "con còn ảnh chờ 👍/👎 (needs_images) thì cây phải rơi xuống autorun_pass "
            "với mã thẻ cha — đó là chỗ enqueue_erp_idea_jobs nhận việc",
        )


class ReviewPostAttachmentSuffixTests(unittest.TestCase):
    """T3 — tệp không phải ảnh không được tính là ảnh chờ duyệt."""

    def test_a_pdf_the_bot_posted_is_not_an_image_waiting_for_a_vote(self) -> None:
        self.assertFalse(
            is_review_post({"mine": 1, "content": "", "attachments": [{"file_name": "bang-gia.pdf"}]}),
            "is_review_post chỉ hỏi 'có attachments không' — một tệp PDF cũng thành ảnh "
            "chờ 👍/👎 và giữ thẻ ở 'còn 1 ảnh chờ' mãi mãi",
        )

    def test_a_pdf_a_person_posted_is_not_a_foreign_image_either(self) -> None:
        from flow_web.agent_bot import is_foreign_review_post

        self.assertFalse(
            is_foreign_review_post({"mine": 0, "content": "", "attachments": [{"file_name": "bang-gia.pdf"}]}),
            "is_foreign_review_post cùng lỗ với is_review_post: PDF của người cũng bị đếm",
        )

    def test_images_of_either_author_still_count(self) -> None:
        from flow_web.agent_bot import is_foreign_review_post

        # Chốt chặn: sửa suffix không được làm mất ảnh thật, kể cả ảnh người đăng.
        self.assertTrue(is_review_post({"mine": 1, "content": "", "attachments": [{"file_name": "a.png"}]}))
        self.assertTrue(is_foreign_review_post({"mine": 0, "content": "", "attachments": [{"file_name": "b.JPG"}]}))
        self.assertTrue(is_review_post({"mine": 1, "content": "", "attachments": [{"name": "c.webp"}]}))

    def test_an_attachment_without_a_readable_name_is_still_trusted_as_an_image(self) -> None:
        # ERP không phải lúc nào cũng trả tên tệp; không đọc được thì giữ luật cũ.
        self.assertTrue(is_review_post({"mine": 1, "content": "", "attachments": [{"file_url": ""}]}))
        self.assertTrue(is_review_post({"mine": 1, "content": "", "attachments": [{}]}))

    def test_count_decisions_and_readiness_ignore_the_pdf(self) -> None:
        from flow_web.agent_bot import listing_readiness

        # Ghi chú PDF của **người thật**: không mang dấu [FLOW_V2_REVIEW] của
        # app, không phải của bot. Fixture cũ dùng ``comment("note", …)`` nên
        # mang nguyên dấu app — hình dạng ngoài đời không có.
        node = {"comments": [
            comment("L-1", like=1),
            comment("L-2", like=1),
            comment("note", mine=0, content="", attachments=[{"file_name": "bang-gia.pdf"}]),
        ]}
        self.assertEqual(
            (2, 0, 0), count_decisions(node),
            "PDF đang được đếm thành một ảnh chờ: (2, 1, 0) thay vì (2, 0, 0)",
        )
        ready, missing = listing_readiness(node)
        self.assertTrue(ready, f"thẻ đã 👍 đủ hai ảnh mà vẫn bị giữ lại vì PDF: {missing!r}")

    def test_a_real_file_outranks_the_review_marker(self) -> None:
        # Gọi tên luật đã cài (T3.3 viết lại): có tệp thật thì đuôi tệp quyết;
        # dấu [FLOW_V2_REVIEW] chỉ là lối dự phòng khi ERP trả attachments rỗng.
        from flow_web.agent_bot import is_foreign_review_post

        marked = "[FLOW_V2_REVIEW job#0] Ảnh 1/2 chờ duyệt"
        self.assertFalse(
            is_review_post({"mine": 1, "content": marked, "attachments": [{"file_name": "bang-gia.pdf"}]}),
            "dấu app không được biến một PDF thành ảnh chờ phiếu",
        )
        self.assertFalse(
            is_foreign_review_post({"mine": 0, "content": marked, "attachments": [{"file_name": "bang-gia.pdf"}]}),
            "cùng luật cho phía không phải của bot",
        )
        self.assertTrue(
            is_review_post({"mine": 1, "content": marked, "attachments": [{"file_name": "a.png"}]}),
            "ảnh thật mang dấu vẫn là ảnh chờ",
        )
        self.assertTrue(
            is_review_post({"mine": 1, "content": marked, "attachments": []}),
            "không có tệp thì dấu app là thứ duy nhất còn lại để nhận ra ảnh chờ",
        )

    def test_a_url_without_any_suffix_is_still_trusted_as_an_image(self) -> None:
        # Đợt 4, T15. Docstring has_image_attachment hứa "không đọc được tên tệp
        # thì vẫn tính là ảnh", nhưng một URL không có đuôi đang bị coi là tên
        # đọc được rồi bị loại. Phải khớp lời hứa: không có đuôi = không đọc được.
        from flow_web.agent_bot import has_image_attachment

        self.assertTrue(
            has_image_attachment({"attachments": [{"file_url": "https://erp/files/abc"}]}),
            "URL không có đuôi tệp là 'không đọc được tên' — phải tin là ảnh, "
            "bỏ sót một ảnh thật là bỏ sót một phiếu người đã bấm",
        )
        self.assertTrue(
            is_review_post(comment("x", attachments=[{"file_url": "https://erp/files/abc"}])),
            "is_review_post phải đi theo cùng luật với has_image_attachment",
        )
        self.assertFalse(
            has_image_attachment({"attachments": [{"file_url": "https://erp/files/abc.pdf?fid=1"}]}),
            "có đuôi đọc được mà không phải ảnh thì vẫn loại — đừng sửa quá tay",
        )


class ListedCardAfterHandoverTests(unittest.TestCase):
    """T6/T7 — thẻ đã giao đi thì không tự chạy ảnh lại, và không rơi khỏi tầm quét."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.autorun_calls: List[str] = []
        self.asked: List[tuple[str, str]] = []

    async def _autorun(self, task_id: str) -> Dict[str, Any]:
        self.autorun_calls.append(task_id)
        return {"queued": []}

    async def _queued(self, task_id: str, root: Dict[str, Any]) -> Dict[str, Any]:
        return {"queue_task_id": "etsy-copy-1", "machine_id": "etsy-vn32"}

    async def _pending(self, queue_task_id: str, machine_id: str) -> Dict[str, Any]:
        self.asked.append((queue_task_id, machine_id))
        return {"pending": True, "status": "queued"}

    @staticmethod
    def _approved_root(agents=(BOT,)) -> Dict[str, Any]:
        root = task_node("TASK-L", agents=list(agents),
                         comments=[comment("L-1", like=1), comment("L-2", like=2)])
        root["meta"] = "action_1: listing\nacc: acc32"
        return root

    def test_a_card_waiting_for_etsy_to_finish_is_not_run_for_images_again(self) -> None:
        # T7. Lượt 1 giao xong. Lượt 2 bản Listing còn treo → dòng 'waiting' →
        # hôm nay rơi xuống autorun_pass và thẻ có 2 ảnh nên bị chạy ảnh lại.
        rows = [{"name": "TASK-L", "child_total": 0, "status": "Working",
                 "agents": [{"bot_user": BOT}], "parent_task": ""}]
        for _ in range(2):
            client = FakeClient(["PROJ-0013"], {"PROJ-0013": rows}, {"TASK-L": {"root": self._approved_root()}})
            bot = build_bot(client, self.tmp, autorun_cooldown_seconds=0)
            bot.listing_hook = self._queued
            bot.listing_confirm_hook = self._pending
            bot.autorun_hook = self._autorun
            asyncio.run(bot.run_once())

        self.assertEqual(1, len(self.asked), "lượt hai phải hỏi lại bản Listing đúng một lần")
        self.assertEqual(
            [], self.autorun_calls,
            "thẻ đã có dòng sổ listed mà vẫn rơi xuống autorun_pass: bot chạy ảnh lại một "
            "thẻ đang chờ Etsy dựng bản nháp, đẻ thêm ảnh mới lên bộ ảnh đã chốt",
        )

    def test_a_handed_over_idea_card_stays_in_scope_after_leaving_the_source_column(self) -> None:
        # T6. Phạm vi board, cột nguồn Working. Thẻ listing không gắn agent đích
        # danh đã được giao ở cột Working rồi luật cột đẩy sang Đang review.
        # Bây giờ nó không còn ở cột nguồn → candidate_tasks bỏ → không ai hỏi
        # lại bản Listing → không bao giờ xác nhận → không bao giờ Hoàn thành.
        #
        # Bài này chỉ canh **bộ lọc cột** của candidate_tasks. Hình dạng thẻ cố
        # ý tối giản (gốc đứng một mình, mine=1, attachment_count=2): app không
        # sinh thẻ như vậy, nhưng cơ chế được canh không phụ thuộc hình dạng.
        row = {"name": "TASK-L", "child_total": 0, "status": "Pending Review",
               "agents": [], "parent_task": "", "attachment_count": 2}
        root = self._approved_root(agents=())
        root["status"] = "Pending Review"
        state = AgentBotState.load(self.tmp / "state.json")
        state.record_listing("TASK-L", {"queue_task_id": "etsy-copy-1", "machine_id": "etsy-vn32"})
        state.save()

        client = FakeClient(["PROJ-0013"], {"PROJ-0013": [row]}, {"TASK-L": {"root": root}})
        bot = build_bot(client, self.tmp, source_statuses=("Working",), autorun_cooldown_seconds=0)
        bot.listing_hook = self._queued
        bot.listing_confirm_hook = self._pending
        bot.autorun_hook = self._autorun
        asyncio.run(bot.run_once())

        self.assertEqual(
            [("etsy-copy-1", "etsy-vn32")], self.asked,
            "candidate_tasks lọc theo cột nguồn trước khi nhìn sổ listed: thẻ đã giao đi rời "
            "cột Working là rơi khỏi tầm quét, bước hỏi lại không bao giờ chạy",
        )


class RunForeverOffLogTests(unittest.TestCase):
    """T5 — bot tắt thì phải nói vì sao, ở mức INFO, trước khi im."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _bot(self, **overrides) -> AgentBot:
        config = AgentBotConfig(bot_user=BOT, **overrides)
        client = FakeClient(["PROJ-0013"], {"PROJ-0013": []}, {})
        return AgentBot(config, client=client, state=AgentBotState.load(self.tmp / "state.json"))

    def _run(self, bot: AgentBot) -> str:
        with self.assertLogs("flow_web.agent_bot", level="INFO") as caught:
            asyncio.run(asyncio.wait_for(bot.run_forever(immediate=True), timeout=2))
        return "\n".join(caught.output)

    def test_missing_token_is_said_out_loud_not_swallowed(self) -> None:
        try:
            text = self._run(self._bot(token=""))
        except AssertionError as exc:
            self.fail(
                "run_forever trả về im lặng khi thiếu token: trên hvg-pc log không có một "
                "dòng nào, không phân biệt được 'tắt' với 'chết'. Phải log INFO nêu tên "
                f"ERP_AGENT_TOKEN trước khi return ({exc})"
            )
        self.assertIn("ERP_AGENT_TOKEN", text, "dòng log phải nêu đúng tên biến người vận hành cần đặt")

    def test_poll_zero_is_said_out_loud_with_the_variable_name(self) -> None:
        try:
            text = self._run(self._bot(token="t0ken", poll_seconds=0))
        except AssertionError as exc:
            self.fail(
                "run_forever trả về im lặng khi poll_seconds=0: phải log INFO nêu tên "
                f"ERP_AGENT_POLL_SECONDS trước khi return ({exc})"
            )
        self.assertIn("ERP_AGENT_POLL_SECONDS", text, "dòng log phải nêu đúng tên biến")


# ── Đợt 4 — sau phán quyết hội đồng về PRD list tự động lên Etsy ─────────


class _ListingTreeHarness:
    """Cây cha+con đúng hình dạng ERP, dùng chung cho các lớp đợt 4.

    Không phải ``TestCase`` để unittest không gom nó thành bài. Cha khai
    ``action_1: listing``; con được tạo trắng, chỉ có ảnh và (khi đã qua bước
    đánh số) một dòng ``sku:`` của riêng nó.
    """

    PARENT_META = "action_1: listing\nacc: acc32"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.handed: List[tuple[str, Dict[str, Any]]] = []
        self.autorun_calls: List[str] = []
        self.pipeline_calls: List[str] = []
        self.asked: List[tuple[str, str]] = []
        self.pipeline_answer: Dict[str, Any] = {"moved": True}
        self.confirm_answer: Dict[str, Any] = {"done": True, "status": "completed"}

    async def _listing_hook(self, task_id: str, node: Dict[str, Any]) -> Dict[str, Any]:
        self.handed.append((task_id, node))
        return {"queue_task_id": f"etsy-copy-{len(self.handed)}", "machine_id": "etsy-vn32"}

    async def _autorun(self, task_id: str) -> Dict[str, Any]:
        self.autorun_calls.append(task_id)
        return {"queued": []}

    async def _pipeline(self, task_id: str) -> Dict[str, Any]:
        self.pipeline_calls.append(task_id)
        return dict(self.pipeline_answer)

    async def _confirm(self, queue_task_id: str, machine_id: str) -> Dict[str, Any]:
        self.asked.append((queue_task_id, machine_id))
        return dict(self.confirm_answer)

    def _child(self, name: str, *, comments, meta: str = "sku: KT-0001", status: str = "Pending Review"):
        return task_node(name, agents=[BOT], comments=comments, status=status,
                         parent_task="TASK-P", meta=meta)

    def _tree(self, *children: Dict[str, Any], meta: str | None = None, **root_extra: Any) -> Dict[str, Any]:
        root = task_node("TASK-P", agents=[BOT], subtasks=list(children))
        root.update({"meta": self.PARENT_META if meta is None else meta, "status": "Working"})
        root.update(root_extra)
        return root

    def _rows(self, root: Dict[str, Any], *, root_attachments: int = 0) -> List[Dict[str, Any]]:
        rows = [{"name": "TASK-P", "child_total": len(root["subtasks"]), "status": "Working",
                 "agents": [{"bot_user": BOT}], "parent_task": "",
                 "attachment_count": root_attachments}]
        for child in root["subtasks"]:
            rows.append({"name": child["name"], "child_total": 0, "status": child.get("status"),
                         "agents": [{"bot_user": BOT}], "parent_task": "TASK-P",
                         "attachment_count": 0})
        return rows

    def _sweep(self, root: Dict[str, Any], *, times: int = 1, confirm: bool = False,
               pipeline: bool = False, root_attachments: int = 0, cooldown: int = 0):
        summaries = []
        bot = None
        for _ in range(times):
            client = FakeClient(["PROJ-0013"], {"PROJ-0013": self._rows(root, root_attachments=root_attachments)},
                                {"TASK-P": {"root": root}})
            bot = build_bot(client, self.tmp, autorun_cooldown_seconds=cooldown)
            bot.listing_hook = self._listing_hook
            bot.listing_confirm_hook = self._confirm if confirm else None
            bot.autorun_hook = self._autorun
            bot.pipeline_hook = self._pipeline if pipeline else None
            summaries.append(asyncio.run(bot.run_once()))
        return summaries, bot


class ListingChildSkuGateTests(_ListingTreeHarness, unittest.TestCase):
    """T8 — thẻ con chưa có mã SKU của chính nó thì chưa giao.

    Thứ tự thật của một lượt quét: ``pipeline_pass`` đẩy con *Cần làm* →
    *Đang làm* ngay khi đủ phiếu, nhưng ``advance_erp_pipeline`` chỉ điền SKU
    ở lượt **sau** (một bước mỗi lượt, ``service.py:12928-12940``). Cùng lượt
    đó ``listing_pass`` chạy sau và thấy con đủ phiếu → giao luôn với
    ``etsy_listing_sku = ""`` — bản Listing tự đặt mã, không ai lần từ listing
    về thẻ được nữa (``listing_bridge.py:277-286``).
    """

    def test_a_child_without_its_own_sku_waits_for_the_number_instead_of_being_handed(self) -> None:
        root = self._tree(self._child(
            "TASK-P-a",
            comments=[comment("L-1", like=1), comment("L-2", like=1)],
            meta="",
            status="Open",
        ))
        summaries, _ = self._sweep(root, pipeline=True)

        self.assertEqual(
            [], [task_id for task_id, _ in self.handed],
            "con đủ 👍 nhưng chưa có sku: của riêng nó vẫn bị giao — bản Listing nhận "
            "etsy_listing_sku rỗng và tự đặt mã; phải chờ bước điền SKU của lượt sau",
        )
        lines = {line.get("task"): line for line in summaries[0]["listing"]}
        self.assertIn("TASK-P-a", lines, "tóm tắt phải có dòng của con nói vì sao chưa giao")
        self.assertIn(
            "SKU", str(lines["TASK-P-a"].get("waiting") or ""),
            "dòng waiting phải nêu đúng thứ đang thiếu là mã SKU",
        )
        self.assertFalse(
            lines["TASK-P-a"].get("needs_images"),
            "chờ SKU không phải chờ ảnh — không được mở nửa làm ảnh vì dòng này",
        )

    def test_the_same_child_is_handed_once_it_carries_its_sku(self) -> None:
        blank = self._tree(self._child(
            "TASK-P-a", comments=[comment("L-1", like=1)], meta="", status="Open",
        ))
        self._sweep(blank, pipeline=True)
        self.assertEqual([], [task_id for task_id, _ in self.handed],
                         "lượt 1: con chưa có mã thì chưa giao (xem bài trên)")

        numbered = self._tree(self._child(
            "TASK-P-a", comments=[comment("L-1", like=1)], meta="sku: KT-0001",
        ))
        self._sweep(numbered, pipeline=True)

        self.assertEqual(["TASK-P-a"], [task_id for task_id, _ in self.handed],
                         "lượt 2: con đã có sku: KT-0001 phải được giao")
        self.assertEqual(
            "KT-0001", _task_meta(self.handed[0][1]).sku,
            "node đưa cho hook phải mang đúng mã của con — ListingBridge.payload đọc "
            "meta.sku của node này thành etsy_listing_sku",
        )


class ListingChildRoutingInheritanceTests(_ListingTreeHarness, unittest.TestCase):
    """T9, T10 — con chỉ mượn dòng **định tuyến** của cha, và mượn cả nhãn.

    T9: người làm listing khai tài khoản bằng **nhãn** ERP (``acc32`` trong
    ``meta_auto._labels``), không gõ ``acc:``. ``inherited_meta_node`` chỉ nối
    khối *Thuộc tính* nên nhãn không xuống con → ``account_id`` rỗng →
    ``resolve_routing`` rơi về máy mặc định (đăng nhầm shop) hoặc ném
    ``ListingBridgeError``.

    T10: ``inherited_meta_node`` đang nối **nguyên** khối của cha, nên
    ``sku: PARENT`` hay ``template:`` của cha rò xuống con trắng.
    """

    def test_the_parent_s_account_label_reaches_the_child_as_an_acc_line(self) -> None:
        root = self._tree(
            self._child("TASK-P-a", comments=[comment("L-1", like=1)]),
            meta="action_1: listing",
            meta_auto="_labels: [acc32]",
        )
        self._sweep(root)

        self.assertEqual(1, len(self.handed), "con đã 👍 và có sku phải được giao")
        merged = _task_meta(self.handed[0][1])
        self.assertEqual(
            "acc32", merged.account_id,
            "cha chỉ dán nhãn acc32 (không có dòng acc:) → node giao đi không có tài khoản; "
            "phải tính account_from_labels(task_meta(cha).labels, book.account_ids) và ghi "
            "acc: acc32 vào khối meta của bản sao con",
        )

    def test_an_acc_line_on_the_parent_still_beats_its_label(self) -> None:
        # Chốt: dòng gõ tay thắng nhãn, đúng thứ tự của resolve_routing.
        root = self._tree(
            self._child("TASK-P-a", comments=[comment("L-1", like=1)]),
            meta="action_1: listing\nacc: acc16",
            meta_auto="_labels: [acc32]",
        )
        self._sweep(root)

        self.assertEqual("acc16", _task_meta(self.handed[0][1]).account_id)

    def test_only_routing_lines_come_down_from_the_parent(self) -> None:
        root = self._tree(
            self._child("TASK-P-a", comments=[comment("L-1", like=1)], meta="sku: KT-0001"),
            meta="action_1: listing\nacc: acc32\nmachine: etsy-vn32\nsku: PARENT\ntemplate: T1",
        )
        self._sweep(root)

        self.assertEqual(1, len(self.handed), "con đã 👍 và có sku phải được giao")
        merged = _task_meta(self.handed[0][1])
        self.assertTrue(merged.is_listing)
        self.assertEqual("acc32", merged.account_id)
        self.assertEqual("etsy-vn32", merged.machine_id)
        self.assertEqual("KT-0001", merged.sku, "sku của con là của con")
        self.assertEqual(
            "", merged.get("template"),
            "template: của cha không phải khoá định tuyến — không được rò xuống con",
        )

    def test_a_blank_child_does_not_borrow_the_parent_s_sku(self) -> None:
        from flow_web.agent_bot import inherited_meta_node

        root = self._tree(meta="action_1: listing\nacc: acc32\nsku: PARENT")
        merged = _task_meta(inherited_meta_node({"name": "TASK-P-a", "meta": ""}, root))

        self.assertTrue(merged.is_listing, "action_1 vẫn phải xuống con")
        self.assertEqual("acc32", merged.account_id, "acc vẫn phải xuống con")
        self.assertEqual(
            "", merged.sku,
            "con trắng đang mượn sku: PARENT của cha — mã là của riêng từng thẻ, "
            "cho con mượn là gửi mã của cha lên bản Listing cho một sản phẩm khác",
        )


class ListingTreeAutorunTests(_ListingTreeHarness, unittest.TestCase):
    """T11 — cây có con không được đóng băng nửa làm ảnh sau khi con đã listed.

    Idea mới không đến dưới dạng thẻ con: người thả ảnh **lên thẻ cha**
    (``service.py:3160-3200``), rồi ``enqueue_erp_idea_jobs`` mới tách thành
    con. Hôm nay khi mọi con đã có dòng sổ thì ``run_once`` ``continue`` trước
    ``autorun_pass`` → không ai tách ảnh mới nữa. Fan-out vốn idempotent
    (``service.py:19512`` bỏ qua con đã có ảnh), nên mở lại autorun cho cây có
    con là an toàn; chỉ hình dạng gốc-đứng-một-mình (T7) mới cần chặn.
    """

    def test_a_tree_whose_children_are_all_listed_still_runs_new_ideas_dropped_on_the_parent(self) -> None:
        root = self._tree(
            self._child("TASK-P-a", comments=[comment("L-1", like=1)], meta="sku: KT-0001"),
            self._child("TASK-P-b", comments=[comment("L-2", like=1)], meta="sku: KT-0002"),
        )
        # Lượt 1 giao hai con, lượt 2 hỏi lại → cả hai confirmed.
        _, bot = self._sweep(root, times=2, confirm=True)
        self.assertTrue(bot.state.listing_confirmed("TASK-P-a"))
        self.assertTrue(bot.state.listing_confirmed("TASK-P-b"))
        self.autorun_calls.clear()

        # Lượt 3: người vừa thả thêm một ảnh idea lên thẻ CHA (attachment_count 3 > 2 con).
        self._sweep(root, confirm=True, root_attachments=3)

        self.assertEqual(
            ["TASK-P"], self.autorun_calls,
            "cây có con đã listed hết → run_once bỏ autorun_pass → ảnh idea mới thả lên "
            "cha không bao giờ được tách thành thẻ con; người phải bấm chạy tay trên dashboard",
        )

    def test_a_lone_listed_root_is_still_not_run_for_images_again(self) -> None:
        # Chốt T7: hình dạng gốc đứng một mình (không con) vẫn bị chặn.
        rows = [{"name": "TASK-L", "child_total": 0, "status": "Working",
                 "agents": [{"bot_user": BOT}], "parent_task": ""}]
        root = task_node("TASK-L", agents=[BOT],
                         comments=[comment("L-1", like=1), comment("L-2", like=2)])
        root["meta"] = self.PARENT_META
        self.confirm_answer = {"pending": True, "status": "queued"}
        for _ in range(2):
            client = FakeClient(["PROJ-0013"], {"PROJ-0013": rows}, {"TASK-L": {"root": root}})
            bot = build_bot(client, self.tmp, autorun_cooldown_seconds=0)
            bot.listing_hook = self._listing_hook
            bot.listing_confirm_hook = self._confirm
            bot.autorun_hook = self._autorun
            asyncio.run(bot.run_once())

        self.assertEqual([], self.autorun_calls,
                         "gốc đứng một mình đã giao đi mà còn chạy ảnh lại là đẻ ảnh mới lên bộ đã chốt")


class DoneProposalThrottleTests(_ListingTreeHarness, unittest.TestCase):
    """T12 — đề nghị Done bị từ chối thì không lặp lại mỗi lượt quét.

    Từ lượt ``listing_confirmed(con)`` trở đi, ``pipeline_pass`` thấy
    ``card_stage(is_listing=True, listed=True)`` → ``_leave_review`` bảo sang
    *Hoàn thành* → gọi ``pipeline_hook`` → app từ chối (N2 chưa làm). Không có
    cooldown nào ở ``pipeline_pass`` (``agent_bot.py:2320-2382``), nên cứ 120
    giây lại một request ERP thừa, mãi cho tới khi Q1 xong.
    """

    def test_a_refused_done_proposal_is_not_repeated_every_sweep(self) -> None:
        root = self._tree(self._child("TASK-P-a", comments=[comment("L-1", like=1)]))
        self.pipeline_answer = {"moved": False, "reason": "chờ người làm listing"}
        self._sweep(root, times=5, confirm=True, pipeline=True, cooldown=600)

        self.assertEqual(
            1, self.pipeline_calls.count("TASK-P-a"),
            "app đã trả moved=False mà lượt sau vẫn đề nghị lại y hệt: phải ghi cooldown "
            "'pipeline:<mã thẻ>' (autorun_cooldown_seconds) khi hook không báo moved=True",
        )

    def test_a_proposal_that_moved_the_card_is_not_throttled(self) -> None:
        # Chốt: cooldown chỉ cho đề nghị bị từ chối. Cây tĩnh trong test nên
        # con "đã chuyển" vẫn hiện cột cũ ở lượt sau — và vẫn được đề nghị lại.
        root = self._tree(self._child("TASK-P-a", comments=[comment("L-1", like=1)]))
        self.pipeline_answer = {"moved": True}
        self._sweep(root, times=5, confirm=True, pipeline=True, cooldown=600)

        self.assertGreaterEqual(
            self.pipeline_calls.count("TASK-P-a"), 2,
            "moved=True không được ghi cooldown — nếu không thì thẻ Đang làm chờ điền SKU "
            "cũng bị giãn 15 phút",
        )


class BuildAgentBotOffLogTests(unittest.TestCase):
    """T13 — đường app: ``build_agent_bot`` trả ``None`` thì phải nói tên biến.

    ``service.watch_agent_bot`` (``:19544-19548``) gọi ``self.agent_bot()`` →
    ``build_agent_bot`` → ``None`` khi thiếu token → ``return``. ``run_forever``
    không bao giờ được gọi, nên hai dòng log T5.1 ở đó không hiện trên hvg-pc.
    """

    def test_build_agent_bot_says_the_token_is_missing_before_returning_none(self) -> None:
        from flow_web.agent_bot import build_agent_bot

        with tempfile.TemporaryDirectory() as tmp:
            try:
                with self.assertLogs("flow_web.agent_bot", level="INFO") as caught:
                    bot = build_agent_bot(
                        AgentBotConfig(bot_user=BOT, token=""),
                        state_path=Path(tmp) / "state.json",
                    )
            except AssertionError as exc:
                self.fail(
                    "build_agent_bot trả None im lặng khi thiếu token: trên hvg-pc "
                    "watch_agent_bot return ngay, không có dòng nào trong log. Phải log INFO "
                    f"nêu tên ERP_AGENT_TOKEN trước khi return None ({exc})"
                )
        self.assertIsNone(bot, "thiếu token vẫn phải trả None — không dựng bot nửa vời")
        self.assertIn("ERP_AGENT_TOKEN", "\n".join(caught.output),
                      "dòng log phải nêu đúng tên biến người vận hành cần đặt")


if __name__ == "__main__":
    unittest.main()
