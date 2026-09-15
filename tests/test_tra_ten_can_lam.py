"""Kéo thẻ về *Cần làm* thì tên thẻ về lại tên cũ.

Bot đánh số xong là đổi tên thẻ thành mã, và cất tên gốc vào ``ten_cu:``.
Người vận hành kéo nhầm một thẻ sang *Đang làm* thì vài giây sau nó mang tên
``OL_1_050``; kéo ngược về *Cần làm* thì trước đây tên ấy nằm lại, phải chép
tay từ khối thuộc tính ra.

PRD: ``tasks/tra-ten-khi-keo-ve-can-lam.md``.  Mã và ``ten_cu:`` giữ nguyên —
chỉ cái tiêu đề đi qua đi lại.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flow_web.agent_bot import sku_fill_is_due  # noqa: E402
from flow_web.sku import (  # noqa: E402
    SkuFastLaneConfig,
    name_fix_for,
    plan_skus,
    repair_clusters,
    restore_clusters,
)
from tests.test_sku import BOOK, LANE_BOT, _LaneWorld, board_row, card  # noqa: E402


SKU = "BT_1_050"
CU = "Vòng cổ mèo len"


def _cards(status, *, sku=SKU, subject=SKU, ten_cu=CU):
    """Cụm hai thẻ: một gốc khai ``product:``, một thẻ con đã mang mã."""
    lines = [f"sku: {sku}"] if sku else []
    if ten_cu:
        lines.append(f"ten_cu: {ten_cu}")
    return [
        card("TASK-1", "", "product: bờm", subject="Idea", project="PROJ-0170"),
        card("TASK-2", "TASK-1", "\n".join(lines), subject=subject, status=status,
             project="PROJ-0170"),
    ]


def _plan(status, **kwargs):
    return plan_skus(_cards(status, **kwargs), BOOK, root_id="TASK-1", project_id="PROJ-0170")


class NameFixRuleTests(unittest.TestCase):
    """Luật trần: tên thẻ *đáng lẽ* phải là gì, theo cột nó đang đứng."""

    def test_a_card_dragged_back_to_todo_wants_its_old_name(self):
        self.assertEqual(CU, name_fix_for("Open", SKU, SKU, CU))

    def test_a_card_in_doing_wants_the_code(self):
        self.assertEqual(SKU, name_fix_for("Working", SKU, CU, CU))

    def test_a_name_a_person_typed_is_never_touched(self):
        """Tên thứ ba — không phải mã, không phải ``ten_cu`` — là tên của người."""
        self.assertEqual("", name_fix_for("Open", SKU, "Tên người gõ", CU))
        self.assertEqual("", name_fix_for("Working", SKU, "Tên người gõ", CU))

    def test_without_ten_cu_there_is_nowhere_to_go_back_to(self):
        self.assertEqual("", name_fix_for("Open", SKU, SKU, ""))

    def test_a_cancelled_card_is_left_alone(self):
        self.assertEqual("", name_fix_for("Cancelled", SKU, SKU, CU))
        self.assertEqual("", name_fix_for("Cancelled", SKU, CU, CU))

    def test_a_card_without_a_code_has_no_name_to_fix(self):
        self.assertEqual("", name_fix_for("Open", "", CU, CU))


class PlanRestoreTests(unittest.TestCase):
    """``plan_skus`` gom thẻ chờ trả tên vào ô riêng."""

    def test_a_coded_card_sitting_in_todo_is_queued_for_its_old_name(self):
        plan = _plan("Open")
        self.assertEqual(["TASK-2"], [item.task_id for item in plan.restores])
        self.assertEqual(CU, plan.restores[0].name_to_restore)

    def test_the_same_card_in_doing_is_not_restored(self):
        self.assertEqual((), _plan("Working").restores)

    def test_a_card_in_todo_is_never_renamed_back_to_the_code(self):
        """Chống hồi quy: luật ``name_left_behind`` cũ không xét cột.

        Thẻ vừa được trả tên đứng ở *Cần làm* với ``ten_cu`` đúng bằng tên nó
        đang mang — đúng chữ ký của một lượt đổi tên chưa chạy xong.  Không
        thêm điều kiện cột thì lượt chữa tên ngay sau đó đổi nó lại thành mã,
        và tính năng này tự phá chính nó sau một nhịp.
        """
        plan = _plan("Open", subject=CU)
        self.assertEqual((), plan.repairs)
        self.assertEqual((), plan.restores)

    def test_a_card_in_doing_with_the_old_name_is_still_repaired(self):
        plan = _plan("Working", subject=CU)
        self.assertEqual(["TASK-2"], [item.task_id for item in plan.repairs])
        self.assertEqual(SKU, plan.repairs[0].name_fix)

    def test_a_person_renamed_card_in_todo_is_left_alone(self):
        self.assertEqual((), _plan("Open", subject="Tên người gõ").restores)

    def test_a_card_in_todo_without_ten_cu_is_left_alone(self):
        self.assertEqual((), _plan("Open", ten_cu="").restores)

    def test_a_cancelled_card_is_left_alone(self):
        self.assertEqual((), _plan("Cancelled").restores)

    def test_restoring_never_touches_the_code(self):
        """Người đặt việc chốt: trả tên, **giữ** mã trên thẻ."""
        plan = _plan("Open")
        self.assertEqual((), plan.changes)
        self.assertEqual(SKU, plan.sku_for("TASK-2"))


class _Erp:
    """ERP giả có trí nhớ: khối thuộc tính, tiêu đề, và cột của từng thẻ."""

    def __init__(self, status, *, subject=SKU, ten_cu=CU, refuse_renames=None):
        lines = [f"sku: {SKU}"]
        if ten_cu:
            lines.append(f"ten_cu: {ten_cu}")
        self.metas = {"TASK-1": "product: bờm", "TASK-2": "\n".join(lines)}
        self.titles = {"TASK-1": "Idea", "TASK-2": subject}
        self.status = status
        self.renames = []
        self.meta_writes = []
        self.refuse_renames = refuse_renames

    def payload(self):
        child = {
            "name": "TASK-2",
            "subject": self.titles["TASK-2"],
            "parent_task": "TASK-1",
            "meta": self.metas["TASK-2"],
            "status": self.status,
            "project": "PROJ-0170",
            "subtasks": [],
        }
        return {
            "root": {
                "name": "TASK-1",
                "subject": self.titles["TASK-1"],
                "parent_task": "",
                "meta": self.metas["TASK-1"],
                "status": "Working",
                "project": "PROJ-0170",
                "subtasks": [child],
            }
        }

    def run(self, *, dry_run=False):
        import contextlib
        import tempfile
        from unittest.mock import patch

        from flow_web.service import FlowWebService

        with tempfile.TemporaryDirectory() as tmp:
            svc = FlowWebService.__new__(FlowWebService)
            svc._sku_ledger_path = lambda: Path(tmp) / "sku_ledger.json"
            svc._erp_credentials = lambda: ("k", "t")
            svc._normalize_erp_task_id = lambda value: value
            svc._erp_assert_task_in_project = lambda *a, **k: None
            svc._erp_task_full = lambda key, token, root: self.payload()
            svc.load_sku_book = lambda *a, **k: BOOK
            svc._erp_task_board = lambda key, token, project: [
                {"name": "TASK-2", "status": self.status, "custom_sku": SKU}
            ]
            svc._erp_task_detail = lambda key, token, task_id: {
                "meta": self.metas.get(task_id, ""),
                "subject": self.titles.get(task_id, ""),
            }

            def write_meta(key, token, task_id, block):
                self.meta_writes.append((task_id, block))
                self.metas[task_id] = block
                return {}

            svc._erp_update_task_meta = write_meta

            def rename(key, token, task_id, subject):
                if self.refuse_renames is not None:
                    raise RuntimeError(self.refuse_renames)
                self.renames.append((task_id, subject))
                self.titles[task_id] = subject
                return {}

            svc._erp_update_task_title = rename
            svc._erp_comment = lambda *a, **k: {}
            with patch("flow_web.service.log"), patch("flow_web.service.time.sleep"):
                return FlowWebService.fill_task_skus(svc, "TASK-1", dry_run=dry_run)


class FillTaskSkusRestoreTests(unittest.TestCase):
    """Một lượt thật: đổi đúng một tiêu đề, không đụng gì khác."""

    def test_the_old_name_goes_back_on_the_card(self):
        erp = _Erp("Open")
        result = erp.run()
        self.assertEqual([("TASK-2", CU)], erp.renames)
        self.assertEqual(CU, erp.titles["TASK-2"])
        self.assertEqual([{"task_id": "TASK-2", "sku": SKU, "subject": SKU, "title": CU}],
                         result["renamed"])

    def test_restoring_writes_nothing_into_the_meta_block(self):
        """Mã và ``ten_cu`` phải đứng nguyên: chiều về cần cả hai."""
        erp = _Erp("Open")
        erp.run()
        self.assertEqual([], erp.meta_writes)
        self.assertIn(f"sku: {SKU}", erp.metas["TASK-2"])
        self.assertIn(f"ten_cu: {CU}", erp.metas["TASK-2"])

    def test_a_dry_run_renames_nothing(self):
        erp = _Erp("Open")
        erp.run(dry_run=True)
        self.assertEqual([], erp.renames)

    def test_erp_blocking_leaves_the_card_alone_and_says_so(self):
        erp = _Erp("Open", refuse_renames="ERP đang giới hạn request (HTTP 429).")
        result = erp.run()
        self.assertEqual([], erp.renames)
        self.assertEqual(SKU, erp.titles["TASK-2"])
        self.assertEqual(["TASK-2"], [item["task_id"] for item in result["rename_failed"]])

    def test_dragging_back_to_doing_puts_the_code_back(self):
        erp = _Erp("Open")
        erp.run()
        erp.status = "Working"
        erp.run()
        self.assertEqual([("TASK-2", CU), ("TASK-2", SKU)], erp.renames)
        # Không cấp số mới: vẫn đúng cái mã cũ.
        self.assertIn(f"sku: {SKU}", erp.metas["TASK-2"])

    def test_a_second_pass_does_not_rename_again(self):
        erp = _Erp("Open")
        erp.run()
        erp.run()
        self.assertEqual([("TASK-2", CU)], erp.renames)


def _row(name, **kwargs):
    subject = kwargs.pop("subject", "")
    return dict(board_row(name, **kwargs), subject=subject)


class ClusterGateTests(unittest.TestCase):
    """Cổng thô đọc từ dòng bảng: cụm nào đáng đọc cây."""

    def _rows(self, status, subject, *, sku=SKU, agents=(LANE_BOT,)):
        return [
            _row("R", status="Working", agents=list(agents), subject="Idea"),
            _row("C1", parent="R", status=status, sku=sku, subject=subject),
        ]

    def test_a_coded_card_in_todo_still_wearing_the_code_wants_restoring(self):
        self.assertEqual({"R": ["C1"]}, restore_clusters(self._rows("Open", SKU), LANE_BOT))

    def test_a_card_whose_name_is_already_back_is_done(self):
        self.assertEqual({}, restore_clusters(self._rows("Open", CU), LANE_BOT))

    def test_a_card_without_the_bot_is_not_ours(self):
        self.assertEqual({}, restore_clusters(self._rows("Open", SKU, agents=()), LANE_BOT))

    def test_a_card_without_a_code_is_the_numbering_lanes_job(self):
        self.assertEqual({}, restore_clusters(self._rows("Open", "", sku=""), LANE_BOT))

    def test_a_coded_card_in_doing_wearing_another_name_wants_repairing(self):
        self.assertEqual({"R": ["C1"]}, repair_clusters(self._rows("Working", CU), LANE_BOT))

    def test_a_row_with_no_subject_at_all_is_not_guessed_at(self):
        """Dòng bảng thiếu ``subject`` là *không biết*, không phải "tên sai"."""
        self.assertEqual({}, repair_clusters(self._rows("Working", ""), LANE_BOT))

    def test_a_card_in_doing_wearing_the_code_is_already_right(self):
        self.assertEqual({}, repair_clusters(self._rows("Working", SKU), LANE_BOT))

    def test_todo_and_doing_do_not_answer_each_others_question(self):
        self.assertEqual({}, repair_clusters(self._rows("Open", SKU), LANE_BOT))
        self.assertEqual({}, restore_clusters(self._rows("Working", CU), LANE_BOT))


class IsDueTests(unittest.TestCase):
    """Cổng đọc cây: cây chỉ có thẻ chờ trả tên vẫn phải được gật."""

    def _tree(self, status, subject):
        return {
            "root": {
                "name": "R",
                "subject": "Idea",
                "meta": "product: bờm",
                "status": "Working",
                "subtasks": [
                    {
                        "name": "C1",
                        "subject": subject,
                        "parent_task": "R",
                        "meta": f"sku: {SKU}\nten_cu: {CU}",
                        "status": status,
                        "subtasks": [],
                    }
                ],
            }
        }

    def test_a_card_waiting_for_its_old_name_is_due(self):
        self.assertTrue(sku_fill_is_due(self._tree("Open", SKU), ["C1"]))

    def test_a_card_waiting_for_its_code_back_is_due(self):
        self.assertTrue(sku_fill_is_due(self._tree("Working", CU), ["C1"]))

    def test_a_card_whose_name_is_already_right_is_not_due(self):
        self.assertFalse(sku_fill_is_due(self._tree("Open", CU), ["C1"]))
        self.assertFalse(sku_fill_is_due(self._tree("Working", SKU), ["C1"]))


class FastLaneRestoreTests(unittest.TestCase):
    """Làn nhanh phải *thấy* cụm không còn thẻ nào chờ mã."""

    def _boards(self, status, subject):
        return {
            "PROJ-0087": [
                _row("R", status="Working", agents=[LANE_BOT], subject="Idea"),
                _row("C1", parent="R", status=status, sku=SKU, subject=subject),
            ]
        }

    def _lane(self, world):
        return world.lane(SkuFastLaneConfig(enabled=True))

    def test_a_card_dragged_back_to_todo_gets_its_cluster_picked_up(self):
        world = _LaneWorld(self._boards("Open", SKU), fill_result=lambda root: {})
        lane = self._lane(world)
        lane.tick()
        self.assertEqual(["R"], world.filled)

    def test_a_card_dragged_back_to_doing_gets_its_cluster_picked_up(self):
        world = _LaneWorld(self._boards("Working", CU), fill_result=lambda root: {})
        lane = self._lane(world)
        lane.tick()
        self.assertEqual(["R"], world.filled)

    def test_a_settled_board_is_left_alone(self):
        world = _LaneWorld(self._boards("Open", CU), fill_result=lambda root: {})
        lane = self._lane(world)
        for _ in range(4):
            world.beat(lane)
        self.assertEqual([], world.filled)

    def test_a_cluster_that_wrote_nothing_rests_instead_of_asking_every_beat(self):
        """Đọc cây rồi không có gì để ghi thì nghỉ, đừng hỏi lại mỗi nhịp.

        Cụm mà người ta gõ tên tay vào sẽ mãi mãi có tên khác mã.  Không có
        cái chặn này thì nó ăn một lượt đọc cây mỗi 15 giây, vĩnh viễn.
        """
        world = _LaneWorld(self._boards("Working", CU), fill_result=lambda root: {})
        lane = self._lane(world)
        lane.tick()
        for _ in range(4):
            world.beat(lane)
        self.assertEqual(["R"], world.filled)

    def test_a_cluster_that_only_renamed_a_card_did_write_after_all(self):
        """Chữa tên cũng là ghi, đừng báo "chưa ghi được" rồi cho nghỉ.

        Cụm chỉ có mỗi việc chữa tên thì ``written`` rỗng — mà thẻ đã mang tên
        mới thật.  Đọc dòng ấy trong log lúc 20:40 ngày 13/09 là tưởng làn
        hỏng, trong khi ``TASK-2026-05406`` vừa đổi tên xong.
        """
        world = _LaneWorld(
            self._boards("Working", CU),
            fill_result=lambda root: {"written": [], "failed": [], "renamed": [{"task_id": "C1"}]},
        )
        lane = self._lane(world)

        with self.assertLogs("flow_web.sku", "INFO") as ghi:
            lane.tick()

        self.assertEqual(["R"], world.filled)
        self.assertEqual([], [d for d in ghi.output if "chưa ghi được" in d], ghi.output)
        self.assertNotIn(("PROJ-0087", "R"), lane._stuck)


if __name__ == "__main__":
    unittest.main()
