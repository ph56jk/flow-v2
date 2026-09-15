"""Làn nhanh SKU với cây ``taskFull`` bị cắt: thẻ ngoài cây vẫn nhận mã.

Seller cần thẻ kéo sang Working có SKU trong 5 phút.  Cụm 04628 (PROJ-0018)
có gần 100 thẻ con, ERP cắt cây ở 60 nút.  Thẻ Working nằm ngoài phần nhận
được thì ``sku_fill_is_due`` không bao giờ thấy nó, nên làn nhanh trả
``not_due`` rồi đứng chờ 300 giây, mãi mãi.  Chỉ còn lượt quét 120 giây lo.

Làn nhanh đọc thêm cây của chính thẻ ấy, mỗi nhịp tối đa một cây.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from flow_web import sku
from flow_web.agent_bot import build_sku_fast_lane, tree_is_cut
from flow_web.sku import SkuFastLaneConfig, fill_cost
from tests.test_agent_bot import BOT, FakeClient, build_bot, comment, task_node
from tests.test_sku import LANE_BOT, _LaneWorld, board_row

GOC = "TASK-2026-04628"
DU_AN = "PROJ-0018"
LOI_429 = "ERP đang giới hạn tốc độ token bot (HTTP 429)."


def _ten(so: int) -> str:
    return f"TASK-2026-{so:05d}"


#: Thẻ vừa kéo sang Working, nằm ngoài phần cây ERP trả về.
KEO = _ten(6900)


def _nut(name: str, status: str, *, cho_phieu: bool = False) -> Dict[str, Any]:
    return {"name": name, "status": status, "parent_task": GOC, "cho_phieu": cho_phieu, "subtasks": []}


def _cay_goc(con: List[Dict[str, Any]] | None = None, *, tong: int = 97) -> Dict[str, Any]:
    """Gốc 04628 như ERP trả khi cắt: 97 con, nhận 59, cả 59 còn ở Open."""
    if con is None:
        con = [_nut(_ten(6800 + i), "Open") for i in range(59)]
    root = {"name": GOC, "status": "Working", "subtasks": con, "child_total": tong}
    return {"root": root, "node_count": len(con) + 1, "max_nodes": 60}


def _bang(cay: Dict[str, Any], ngoai: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Dòng ``taskBoard``: gốc gắn bot, mọi thẻ trong cây, rồi thẻ bị cắt."""
    rows = [board_row(GOC, status="Working", agents=[LANE_BOT])]
    rows += [board_row(node["name"], parent=GOC, status=node["status"]) for node in cay["root"]["subtasks"]]
    return rows + ngoai


def _den_han(payload: Dict[str, Any], ids) -> bool:
    """Như ``sku_fill_is_due``: chỉ xét thẻ **có trong** cây vừa đọc."""
    root = payload.get("root") if isinstance(payload.get("root"), dict) else payload
    wanted = set(ids)
    stack = [root]
    while stack:
        node = stack.pop()
        if node.get("name") in wanted and node.get("status") == "Working" and not node.get("cho_phieu"):
            return True
        stack.extend(node.get("subtasks") or [])
    return False


class _Cay:
    """Cây ``taskFull`` giả: ghi từng lượt đọc vào sổ request của ``_LaneWorld``."""

    def __init__(self, world: _LaneWorld, trees: Dict[str, Dict[str, Any]], loi: Dict[str, Exception] | None = None):
        self.world = world
        self.trees = trees
        self.loi = loi or {}
        self.doc: List[str] = []

    def __call__(self, name: str) -> Dict[str, Any]:
        self.doc.append(name)
        self.world.spent.append((self.world.now, 1, "tree:" + name))
        if name in self.loi:
            raise self.loi[name]
        return self.trees.get(name, {"root": {}})


def _cum_cat(*, cho_phieu: bool = False, loi: Dict[str, Exception] | None = None):
    cay = _cay_goc()
    ngoai = [board_row(_ten(6860 + i), parent=GOC, status="Open") for i in range(37)]
    ngoai.append(board_row(KEO, parent=GOC, status="Working"))
    world = _LaneWorld({DU_AN: _bang(cay, ngoai)})
    tree = _Cay(world, {GOC: cay, KEO: {"root": _nut(KEO, "Working", cho_phieu=cho_phieu)}}, loi)
    return world, tree


#: Hai thẻ Working ngoài cây, theo thứ tự dòng bảng.
A, B = _ten(6901), _ten(6902)

#: Trần cho các bài dò thẻ ngoài cây.  Bảng nóng đọc 15 giây một lần, nên
#: phút nào cũng có 4 lượt đọc bảng + cây gốc 1 + cây thẻ 1 +
#: ``fill_cost(2, cut_new=2)`` 15 = 21.  Các bài này kiểm thứ tự dò, không
#: kiểm trần; hành vi ở trần 20 nằm ở ``test_the_cat_khong_chan_lan``.
_TRAN_21 = SkuFastLaneConfig(enabled=True, budget_per_minute=21)


def _cum_ngoai(*the: tuple):
    """Cụm cắt với nhiều thẻ Working ngoài cây.  ``the``: ``(tên, tới lượt?)``."""
    cay = _cay_goc()
    ngoai = [board_row(name, parent=GOC, status="Working") for name, _ in the]
    world = _LaneWorld({DU_AN: _bang(cay, ngoai)})
    trees = {GOC: cay}
    trees.update({name: {"root": _nut(name, "Working", cho_phieu=not den)} for name, den in the})
    return world, _Cay(world, trees)


class LanNhanhCayCatTests(unittest.TestCase):
    def test_the_card_dragged_past_the_cut_gets_its_code_in_one_beat(self):
        world, tree = _cum_cat()
        lane = world.lane(tree=tree, is_due=_den_han)

        result = lane.tick()

        self.assertEqual([GOC], world.filled)
        self.assertEqual(GOC, result.get("filled"))
        self.assertEqual([GOC, KEO], tree.doc)

    def test_a_card_past_the_cut_still_waiting_on_votes_is_left_to_the_slow_path(self):
        world, tree = _cum_cat(cho_phieu=True)
        lane = world.lane(tree=tree, is_due=_den_han)

        result = lane.tick()

        self.assertEqual({"not_due": GOC}, {k: v for k, v in result.items() if k != "read"})
        self.assertEqual([], world.filled)
        # Đã hỏi đúng cây của thẻ ngoài cây, rồi mới chịu đứng chờ.
        self.assertEqual([GOC, KEO], tree.doc)
        self.assertIn((DU_AN, GOC), lane._stuck)
        # Đứng chờ thật: nhịp sau không đọc lại hai cây ấy.
        world.beat(lane)
        self.assertEqual([GOC, KEO], tree.doc)

    def test_no_room_for_the_second_tree_waits_without_reading_it(self):
        world, tree = _cum_cat()
        lane = world.lane(tree=tree, is_due=_den_han)
        # Phút này làn đã tiêu gần hết: còn đúng chỗ cho một lượt đọc bảng,
        # một cây và một lượt đánh số — thiếu một chỗ cho cây thứ hai.
        ceiling = SkuFastLaneConfig().budget_per_minute
        self.assertTrue(lane.budget.take(ceiling - (1 + 1 + fill_cost(1))))

        result = lane.tick()

        self.assertEqual({"waiting": GOC}, {k: v for k, v in result.items() if k != "read"})
        self.assertEqual([GOC], tree.doc)
        self.assertEqual([], world.filled)
        # Chờ ngân sách không phải là kẹt: phút sau làm tiếp, không đợi 300 giây.
        self.assertNotIn((DU_AN, GOC), lane._stuck)
        world.beat(lane, 60)
        self.assertEqual([GOC], world.filled)

    def test_a_429_on_the_second_tree_rests_the_lane(self):
        world, tree = _cum_cat(loi={KEO: RuntimeError(LOI_429)})
        lane = world.lane(tree=tree, is_due=_den_han)

        result = lane.tick()

        self.assertIn("429", result.get("error", ""))
        self.assertEqual([], world.filled)
        self.assertNotIn((DU_AN, GOC), lane._stuck)
        spent = len(world.spent)
        for _ in range(3):
            self.assertTrue(world.beat(lane).get("resting"))
        self.assertEqual(spent, len(world.spent))
        world.beat(lane)
        self.assertGreater(len(world.spent), spent)

    def test_any_other_failure_on_the_second_tree_parks_the_cluster(self):
        world, tree = _cum_cat(loi={KEO: RuntimeError("Task not found")})
        lane = world.lane(tree=tree, is_due=_den_han)

        with self.assertLogs("flow_web.sku", "WARNING"):
            lane.tick()

        self.assertEqual([], world.filled)
        self.assertIn((DU_AN, GOC), lane._stuck)
        self.assertFalse(world.beat(lane).get("resting"))

    def test_a_card_past_the_cut_not_yet_due_does_not_hide_the_next_one(self):
        world, tree = _cum_ngoai((A, False), (B, True))
        lane = world.lane(_TRAN_21, tree=tree, is_due=_den_han)

        lane.tick()

        self.assertEqual([], world.filled)
        self.assertEqual([GOC, A], tree.doc)
        # A chưa tới lượt chưa phải cả cụm chưa tới lượt: B còn chưa ai hỏi.
        self.assertNotIn((DU_AN, GOC), lane._stuck)

        world.beat(lane)

        self.assertEqual([GOC], world.filled)
        self.assertEqual([GOC, A, GOC, B], tree.doc)

    # Hai thẻ chứ không ba: ``fill_cost(3)`` = 18, cộng đọc bảng, cây gốc và
    # cây thẻ là 21 — quá trần 20/phút, làn không bao giờ dò nổi cụm ấy.

    def test_the_cluster_waits_only_once_every_card_past_the_cut_said_no(self):
        world, tree = _cum_ngoai((A, False), (B, False))
        lane = world.lane(_TRAN_21, tree=tree, is_due=_den_han)

        lane.tick()
        self.assertNotIn((DU_AN, GOC), lane._stuck)
        world.beat(lane)

        self.assertEqual([GOC, A, GOC, B], tree.doc)
        self.assertIn((DU_AN, GOC), lane._stuck)
        self.assertEqual([], world.filled)
        # Đứng chờ thật: không đọc lặp thẻ nào trong lúc chờ.
        for _ in range(5):
            world.beat(lane)
        self.assertEqual([GOC, A, GOC, B], tree.doc)
        # Hết hạn chờ thì thử lại từ thẻ đầu, như mọi cụm đứng chờ khác.
        world.beat(lane, SkuFastLaneConfig().rediscover_s)
        self.assertEqual([GOC, A], tree.doc[4:])

    def test_a_changed_row_starts_the_cards_past_the_cut_over(self):
        world, tree = _cum_ngoai((A, False), (B, False))
        lane = world.lane(_TRAN_21, tree=tree, is_due=_den_han)

        lane.tick()
        self.assertEqual([GOC, A], tree.doc)

        # Có người sửa thẻ A: điều làn biết về các thẻ ngoài cây có thể đã cũ.
        # Nghỉ 60 giây để ngân sách phút trước không che mất bài này.
        next(row for row in world.boards[DU_AN] if row["name"] == A)["modified"] = "2026-09-11 16:05:00"
        world.beat(lane, 60)
        self.assertEqual([GOC, A, GOC, A], tree.doc)
        self.assertNotIn((DU_AN, GOC), lane._stuck)

        world.beat(lane)
        self.assertEqual([GOC, A, GOC, A, GOC, B], tree.doc)
        self.assertEqual([], world.filled)

    def test_a_card_past_the_cut_that_fails_to_read_does_not_hide_the_next_one(self):
        world, tree = _cum_ngoai((A, True), (B, True))
        tree.loi[A] = RuntimeError("Task not found")
        lane = world.lane(_TRAN_21, tree=tree, is_due=_den_han)

        with self.assertLogs("flow_web.sku", "WARNING"):
            lane.tick()
        self.assertNotIn((DU_AN, GOC), lane._stuck)
        world.beat(lane)

        self.assertEqual([GOC], world.filled)
        self.assertEqual([GOC, A, GOC, B], tree.doc)

    def test_an_uncut_tree_is_read_once(self):
        keo = [board_row(KEO, parent=GOC, status="Working")]
        cases = (
            ("thẻ tới lượt", [_nut(KEO, "Working")], [], [GOC]),
            ("thẻ chờ phiếu", [_nut(KEO, "Working", cho_phieu=True)], [], []),
            # Dòng bảng lệch với cây, mà cây không bị cắt: không đọc thêm.
            ("thẻ vắng mặt", [_nut(_ten(6800), "Open")], keo, []),
        )
        for label, con, ngoai, filled in cases:
            with self.subTest(label):
                cay = _cay_goc(con, tong=1)
                world = _LaneWorld({DU_AN: _bang(cay, ngoai)})
                tree = _Cay(world, {GOC: cay, KEO: {"root": _nut(KEO, "Working")}})
                lane = world.lane(tree=tree, is_due=_den_han)

                lane.tick()

                self.assertEqual(filled, world.filled)
                self.assertEqual([GOC], tree.doc)

    def test_the_cut_check_matches_the_bots(self):
        # ``sku.py`` không import được ``agent_bot`` nên chép luật cắt; hai
        # bản lệch nhau thì làn nhanh và lượt quét thấy hai cây khác nhau.
        la = task_node("L", status="Open")
        cases = {
            "cây trọn": ({"root": _cay_goc([_nut(KEO, "Open")], tong=1)["root"]}, False),
            "ERP báo cắt": ({"root": {"name": GOC}, "truncated": True}, True),
            "chạm trần nút": ({"root": {"name": GOC}, "node_count": 60, "max_nodes": 60}, True),
            "dưới trần nút": ({"root": {"name": GOC}, "node_count": 59, "max_nodes": 60}, False),
            "trần 0": ({"root": {"name": GOC}, "node_count": 5, "max_nodes": 0}, False),
            "số hỏng": ({"root": {"name": GOC}, "node_count": "x", "max_nodes": 60}, False),
            "cháu thiếu con": ({"root": task_node(GOC, subtasks=[task_node("C", subtasks=[la], child_total=3)])}, True),
            "child_total hỏng": ({"root": {"name": GOC, "child_total": "x"}}, False),
            "không có gốc": ({}, False),
        }
        for label, (payload, cut) in cases.items():
            with self.subTest(label):
                self.assertEqual(cut, tree_is_cut(payload))
                self.assertEqual(cut, sku._tree_is_cut(payload))


#: Cụm lớn đứng trước, cụm một thẻ đứng sau.
LON, NHO = _ten(4701), _ten(4702)


def _cum_tron(goc: str, the: List[str]):
    """Cụm không cắt, mọi thẻ con ở Working và tới lượt: (dòng bảng, cây)."""
    rows = [board_row(goc, status="Working", agents=[LANE_BOT])]
    rows += [board_row(name, parent=goc, status="Working") for name in the]
    con = [dict(_nut(name, "Working"), parent_task=goc) for name in the]
    return rows, {"root": {"name": goc, "status": "Working", "subtasks": con}}


def _hai_cum(so_the: int, *, cung_bang: bool = True):
    """Cụm ``LON`` có ``so_the`` thẻ đứng trước cụm ``NHO`` một thẻ."""
    lon, cay_lon = _cum_tron(LON, [_ten(4710 + i) for i in range(so_the)])
    nho, cay_nho = _cum_tron(NHO, [_ten(4720)])
    boards = {DU_AN: lon + nho} if cung_bang else {DU_AN: lon, "PROJ-0019": nho}
    world = _LaneWorld(boards)
    return world, _Cay(world, {LON: cay_lon, NHO: cay_nho})


def _de_luot_quet(seen) -> int:
    return sum("để lượt quét chính" in line for line in seen.output)


class LanNhanhCumLonTests(unittest.TestCase):
    """Cụm không bao giờ lọt trần không được chắn cả làn.

    Nhịp nào làn cũng đọc bảng trước khi đánh số, nên phần tối thiểu của một
    cụm là: đọc bảng 1, đọc cây, rồi ``fill_cost``.  Lớn hơn trần một phút
    thì chờ bao lâu cũng không lọt — việc ấy của lượt quét chính.
    """

    def test_a_cluster_past_the_ceiling_does_not_hold_up_the_next_one(self):
        # Bốn thẻ: đọc bảng 1 + cây 1 + fill_cost(4) 23 = 25, trần 20.
        self.assertGreater(1 + 1 + fill_cost(4), SkuFastLaneConfig().budget_per_minute)
        for label, cung_bang in (("cùng bảng", True), ("khác bảng", False)):
            with self.subTest(label):
                world, tree = _hai_cum(4, cung_bang=cung_bang)
                lane = world.lane(tree=tree, is_due=_den_han)

                result = lane.tick()

                self.assertEqual([NHO], world.filled)
                self.assertEqual(NHO, result.get("filled"))
                # Không tiêu lượt đọc cây nào cho cụm không bao giờ lọt.
                self.assertEqual([NHO], tree.doc)

    def test_a_cluster_past_the_ceiling_is_logged_once_per_row_stamp(self):
        world, tree = _hai_cum(4)
        lane = world.lane(tree=tree, is_due=_den_han)

        with self.assertLogs("flow_web.sku", "INFO") as seen:
            lane.tick()
            world.beat(lane)
        self.assertEqual(1, _de_luot_quet(seen))

        # Dòng bảng đổi thì xét lại cụm, và ghi lại đúng một dòng.
        next(row for row in world.boards[DU_AN] if row["name"] == _ten(4710))["modified"] = "2026-09-11 16:05:00"
        with self.assertLogs("flow_web.sku", "INFO") as seen:
            world.beat(lane)
            world.beat(lane)
        self.assertEqual(1, _de_luot_quet(seen))

        self.assertEqual([NHO], world.filled)
        self.assertNotIn(LON, tree.doc)

    def test_a_cluster_that_fits_an_empty_minute_still_waits_for_room(self):
        # Ba thẻ: đọc bảng 1 + cây 1 + fill_cost(3) 18 = 20, vừa khít trần.
        # Lọt được, chỉ là không phải phút này.
        self.assertEqual(1 + 1 + fill_cost(3), SkuFastLaneConfig().budget_per_minute)
        world, tree = _hai_cum(3)
        lane = world.lane(tree=tree, is_due=_den_han)
        self.assertTrue(lane.budget.take(5))

        # Chờ được ngân sách là một nhịp bỏ có chủ đích; phải nói ra một lần
        # để người vận hành phân biệt với cụm kẹt hay khoá bận.
        with self.assertLogs("flow_web.sku", "INFO") as seen:
            result = lane.tick()

        self.assertEqual({"waiting": LON}, {k: v for k, v in result.items() if k != "read"})
        self.assertTrue(any("chờ ngân sách request" in line for line in seen.output), seen.output)
        self.assertEqual([], world.filled)
        self.assertNotIn((DU_AN, LON), lane._stuck)
        world.beat(lane, 60)
        self.assertEqual([LON], world.filled)

    def test_a_cut_cluster_past_the_ceiling_reads_its_root_once_then_steps_aside(self):
        # Ba thẻ ngoài cây: đọc bảng 1 + cây gốc 1 + cây thẻ 1 + fill_cost(3)
        # 18 = 21.  Chỉ biết cây bị cắt sau khi đọc cây gốc.
        the = [_ten(6901 + i) for i in range(3)]
        cay = _cay_goc()
        ngoai = [board_row(name, parent=GOC, status="Working") for name in the]
        nho, cay_nho = _cum_tron(NHO, [_ten(4720)])
        world = _LaneWorld({DU_AN: _bang(cay, ngoai) + nho})
        trees = {GOC: cay, NHO: cay_nho}
        trees.update({name: {"root": _nut(name, "Working")} for name in the})
        tree = _Cay(world, trees)
        lane = world.lane(tree=tree, is_due=_den_han)

        with self.assertLogs("flow_web.sku", "INFO") as seen:
            lane.tick()
            world.beat(lane)
            world.beat(lane)

        self.assertEqual([NHO], world.filled)
        # Cây gốc đọc một lần mới biết bị cắt; cùng dấu dòng thì không đọc lại.
        self.assertEqual([GOC, NHO], tree.doc)
        self.assertEqual(1, _de_luot_quet(seen))
        self.assertNotIn((DU_AN, GOC), lane._stuck)


def _nghi_429(seen) -> int:
    return sum("bị 429" in line for line in seen.output)


class LanNhanhNghi429Tests(unittest.TestCase):
    """Gặp 429 thì làn nghỉ ``rest_s``.  Sau deploy phải thấy được trong log."""

    def test_a_429_logs_one_line_per_rest(self):
        lon, _ = _cum_tron(LON, [_ten(4710)])
        nho, _ = _cum_tron(NHO, [_ten(4720)])
        world = _LaneWorld({DU_AN: lon, "PROJ-0019": nho})
        world.fail_board = RuntimeError(LOI_429)
        lane = world.lane()

        # Hai bảng cùng 429 trong một nhịp: một lần nghỉ, một dòng.
        with self.assertLogs("flow_web.sku", "WARNING") as seen:
            self.assertTrue(lane.tick().get("resting"))
        self.assertEqual(2, len(world.reads()))
        self.assertEqual(1, _nghi_429(seen))
        self.assertRegex("\n".join(seen.output), r"nghỉ tới \d\d:\d\d:\d\d")

        # Đang nghỉ thì không ghi thêm.
        with self.assertNoLogs("flow_web.sku", "WARNING"):
            for _ in range(3):
                self.assertTrue(world.beat(lane).get("resting"))

        # Hết nghỉ mà vẫn 429: lần nghỉ mới, thêm đúng một dòng.
        with self.assertLogs("flow_web.sku", "WARNING") as seen:
            self.assertTrue(world.beat(lane).get("resting"))
        self.assertEqual(1, _nghi_429(seen))

    def test_every_way_into_the_rest_logs_the_line_once(self):
        cases = {}
        world, tree = _cum_cat(loi={KEO: RuntimeError(LOI_429)})
        cases["cây thẻ trả 429"] = (world, world.lane(tree=tree, is_due=_den_han))
        rows, _ = _cum_tron(NHO, [_ten(4720)])
        world = _LaneWorld(
            {DU_AN: rows}, fill_result=lambda root: {"written": [], "failed": [{"error": LOI_429}]}
        )
        cases["lượt đánh số trả 429"] = (world, world.lane())
        for label, (world, lane) in cases.items():
            with self.subTest(label):
                with self.assertLogs("flow_web.sku", "WARNING") as seen:
                    lane.tick()
                    for _ in range(3):
                        self.assertTrue(world.beat(lane).get("resting"))
                self.assertEqual(1, _nghi_429(seen))


class _DemCay(FakeClient):
    """``FakeClient`` ghi lại từng lượt đọc ``taskFull``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.doc: List[str] = []

    def task_full(self, name: str, depth: int = 1) -> Dict[str, Any]:
        self.doc.append(name)
        return super().task_full(name, depth)


class BuildSkuFastLaneCayCatTests(unittest.TestCase):
    """Đi qua ``build_sku_fast_lane`` thật: client, ``sku_fill_is_due`` thật."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.filled: List[str] = []

    def _fill(self, root: str) -> Dict[str, Any]:
        self.filled.append(root)
        return {"written": [{"task_id": KEO}], "failed": []}

    def _lane(self, keo: Dict[str, Any]):
        con = [task_node(_ten(6800 + i), status="Open", parent_task=GOC) for i in range(59)]
        goc = task_node(GOC, agents=[BOT], status="Working", project=DU_AN, subtasks=con, child_total=97)
        rows = [board_row(GOC, status="Working", agents=[BOT])]
        rows += [board_row(node["name"], parent=GOC, status="Open") for node in con]
        rows += [board_row(_ten(6860 + i), parent=GOC, status="Open") for i in range(37)]
        rows.append(board_row(KEO, parent=GOC, status="Working"))
        client = _DemCay(
            [DU_AN],
            {DU_AN: rows},
            {GOC: {"root": goc, "node_count": 60, "max_nodes": 60}, KEO: {"root": keo}},
        )
        bot = build_bot(client, self.tmp)
        # Chỉ ``scope_projects`` mới ghi phạm vi, kèm danh sách riêng của làn
        # nhanh. Gán tay ``state.projects`` là bỏ qua chỗ đó.
        bot.scope_projects()
        return client, build_sku_fast_lane(bot, self._fill, SkuFastLaneConfig(enabled=True))

    def test_a_product_card_past_the_cut_is_numbered(self) -> None:
        client, lane = self._lane(task_node(KEO, status="Working", parent_task=GOC))

        lane.tick()

        self.assertEqual([GOC], self.filled)
        self.assertEqual([GOC, KEO], client.doc)

    def test_an_idea_card_past_the_cut_waiting_on_votes_is_numbered_too(self) -> None:
        # Thẻ nằm ngoài cây bị cắt vẫn phải theo đúng luật của thẻ trong cây:
        # kéo sang *Đang làm* là đủ, không phải bấm 👍/👎 tấm nào.
        client, lane = self._lane(task_node(KEO, status="Working", parent_task=GOC, comments=[comment("c1")]))

        lane.tick()

        self.assertEqual([GOC], self.filled)
        self.assertEqual([GOC, KEO], client.doc)

    def test_an_idea_card_past_the_cut_with_every_image_binned_is_not(self) -> None:
        client, lane = self._lane(
            task_node(KEO, status="Working", parent_task=GOC, comments=[comment("c1", dislike=1)])
        )

        lane.tick()

        self.assertEqual([], self.filled)
        self.assertEqual([GOC, KEO], client.doc)


if __name__ == "__main__":
    unittest.main()
