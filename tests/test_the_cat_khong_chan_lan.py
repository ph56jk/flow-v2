"""Làn nhanh SKU: cụm bị cắt mà giá thật vượt trần thì nhường, không chắn làn.

Trước khi đọc cây, làn chưa biết thẻ nào nằm ngoài cây, nên tính giá như cây
trọn.  Đọc cây gốc xong mới biết: mỗi thẻ mới ngoài cây tốn thêm một
``taskFull`` (``cut_new``).  Cụm đã tới lượt mà giá mới vượt trần một phút
thì chờ bao lâu cũng không lọt.  Đứng "waiting" ở đó là chắn mọi cụm phía
sau, mãi mãi.  Cụm ấy phải nhường lượt quét chính, như cụm quá lớn khác.

Có cụm không vượt trần trên giấy mà phút nào cũng thiếu chỗ: bảng nóng đọc
15 giây một lần, chiếm sẵn phần của cửa sổ.  Cụm chờ trọn một cửa sổ mà dấu
dòng không đổi thì cũng nhường.  Chờ ngắn hơn thì vẫn đợi được.
"""

from __future__ import annotations

import unittest

from flow_web.sku import SkuFastLaneConfig, fill_cost
from tests.test_lan_nhanh_cay_cat import (
    DU_AN,
    GOC,
    NHO,
    _bang,
    _Cay,
    _cay_goc,
    _cum_cat,
    _cum_tron,
    _den_han,
    _nut,
    _ten,
)
from tests.test_sku import _LaneWorld, board_row

#: Thẻ Working nằm trong phần cây ERP trả về: cụm tới lượt ngay.
TRONG = _ten(6800)
#: Hai thẻ Working nằm ngoài cây.
A, B = _ten(6901), _ten(6902)
#: Thẻ con của cụm ``NHO``.
THE_NHO = _ten(4720)
#: Bảng thứ hai, cho ca khác bảng.
DU_AN_KHAC = "PROJ-0019"


def _cum_toi_luot_vuot_tran(*, cung_bang: bool = True):
    """Cụm cắt tới lượt, ba thẻ cần mã (một trong cây, hai ngoài), rồi cụm ``NHO``."""
    con = [_nut(TRONG, "Working")] + [_nut(_ten(6801 + i), "Open") for i in range(58)]
    cay = _cay_goc(con)
    ngoai = [board_row(name, parent=GOC, status="Working") for name in (A, B)]
    nho, cay_nho = _cum_tron(NHO, [THE_NHO])
    lon = _bang(cay, ngoai)
    world = _LaneWorld({DU_AN: lon + nho} if cung_bang else {DU_AN: lon, DU_AN_KHAC: nho})
    trees = {GOC: cay, NHO: cay_nho}
    trees.update({name: {"root": _nut(name, "Working")} for name in (A, B)})
    return world, _Cay(world, trees)


def _bang_nong_roi_keo():
    """Bảng đã nóng một phút, rồi seller kéo A, B và thẻ ``NHO`` sang Working.

    Cụm cắt chỉ có A, B, cả hai ngoài cây và tới lượt.  Phút nào cũng có
    4 lượt đọc bảng, nên cụm cần 4 + cây gốc 1 + cây thẻ 1 +
    ``fill_cost(2, cut_new=2)`` 15 = 21, trần 20.
    """
    cay = _cay_goc()
    ngoai = [board_row(name, parent=GOC, status="Open") for name in (A, B)]
    nho, cay_nho = _cum_tron(NHO, [THE_NHO])
    world = _LaneWorld({DU_AN: _bang(cay, ngoai) + nho})
    _dong(world, THE_NHO)["status"] = "Open"
    trees = {GOC: cay, NHO: cay_nho}
    trees.update({name: {"root": _nut(name, "Working")} for name in (A, B)})
    tree = _Cay(world, trees)
    lane = world.lane(tree=tree, is_due=_den_han)
    # Một phút bảng nóng: thẻ gốc còn thẻ con ở Open, chưa cụm nào tới lượt.
    lane.tick()
    for _ in range(3):
        world.beat(lane)
    for name in (A, B, THE_NHO):
        _dong(world, name).update(status="Working", modified="2026-09-11 16:05:00")
    return world, tree, lane


def _dong(world: _LaneWorld, name: str):
    return next(row for rows in world.boards.values() for row in rows if row["name"] == name)


def _nhuong(seen) -> int:
    return sum("nhường" in line and "cho lượt quét chính" in line for line in seen.output)


def _doc_cum_cat(tree: _Cay) -> int:
    return sum(name in (GOC, A, B) for name in tree.doc)


class TheCatKhongChanLanTests(unittest.TestCase):
    def test_the_numbers_behind_this_case(self):
        tran = SkuFastLaneConfig().budget_per_minute
        # Trước khi đọc cây: đọc bảng 1 + cây gốc 1 + fill_cost(3) = 20, lọt.
        self.assertLessEqual(1 + 1 + fill_cost(3), tran)
        # Sau khi đọc cây: thêm hai thẻ ngoài cây, 1 + 1 + 20 = 22, không lọt.
        self.assertGreater(1 + 1 + fill_cost(3, cut_new=2), tran)
        # Cụm hai thẻ ngoài cây: một lượt đọc bảng thì lọt, bốn lượt thì không.
        self.assertLessEqual(1 + 1 + 1 + fill_cost(2, cut_new=2), tran)
        self.assertGreater(4 + 1 + 1 + fill_cost(2, cut_new=2), tran)

    def test_a_due_cut_cluster_past_the_ceiling_steps_aside_for_the_next_one(self):
        world, tree = _cum_toi_luot_vuot_tran()
        lane = world.lane(tree=tree, is_due=_den_han)

        with self.assertLogs("flow_web.sku", "INFO"):
            result = lane.tick()

        # Cụm sau vẫn được đánh số ngay nhịp đầu.
        self.assertEqual([NHO], world.filled)
        self.assertEqual(NHO, result.get("filled"))
        # Cây gốc đọc một lần mới biết bị cắt; không đọc cây thẻ nào.
        self.assertEqual([GOC, NHO], tree.doc)

    def test_a_due_cut_cluster_past_the_ceiling_never_waits_for_budget(self):
        world, tree = _cum_toi_luot_vuot_tran()
        lane = world.lane(tree=tree, is_due=_den_han)

        with self.assertLogs("flow_web.sku", "INFO"):
            results = [lane.tick()]
            # Đủ nhiều phút trống: nếu cụm chờ ngân sách thì phút nào cũng "waiting".
            for _ in range(5):
                results.append(world.beat(lane, 60))

        for result in results:
            self.assertNotIn("waiting", result)
        self.assertEqual([NHO], world.filled)
        # Cùng dấu dòng thì không đọc lại cây gốc.
        self.assertEqual([GOC, NHO], tree.doc)
        self.assertNotIn((DU_AN, GOC), lane._stuck)

    def test_on_another_board_the_cluster_behind_gets_its_turn_within_a_minute(self):
        # Hai bảng nóng: mỗi nhịp đọc 2 bảng.  Lượt đọc cây gốc cần
        # 2 + 1 + fill_cost(3) 18 = 21, nên cụm cắt không bao giờ đọc nổi cây.
        world, tree = _cum_toi_luot_vuot_tran(cung_bang=False)
        lane = world.lane(tree=tree, is_due=_den_han)

        with self.assertLogs("flow_web.sku", "INFO") as seen:
            results = [lane.tick()]
            # 60 giây cộng một nhịp.
            for _ in range(4):
                results.append(world.beat(lane))

        self.assertEqual({"waiting": GOC}, {k: v for k, v in results[0].items() if k != "read"})
        self.assertEqual([NHO], world.filled)
        self.assertEqual(NHO, results[-1].get("filled"))
        self.assertEqual(1, _nhuong(seen))
        self.assertEqual([NHO], tree.doc)

    def test_a_cut_cluster_short_of_room_every_minute_steps_aside_within_a_minute(self):
        world, tree, lane = _bang_nong_roi_keo()

        with self.assertLogs("flow_web.sku", "INFO") as seen:
            # Nhịp đầu sau khi kéo, rồi 60 giây.
            results = [world.beat(lane) for _ in range(5)]
            self.assertEqual([NHO], world.filled)
            self.assertEqual(NHO, results[-1].get("filled"))
            self.assertEqual({"waiting": GOC}, {k: v for k, v in results[0].items() if k != "read"})

            # Đã nhường thì không đọc lại cây nào của cụm, dù bao nhiêu phút.
            doc = _doc_cum_cat(tree)
            for _ in range(4):
                world.beat(lane)
            for _ in range(3):
                world.beat(lane, 60)

        self.assertEqual(doc, _doc_cum_cat(tree))
        self.assertEqual(1, _nhuong(seen))
        self.assertNotIn(GOC, world.filled)
        self.assertNotIn((DU_AN, GOC), lane._stuck)

    def test_a_changed_row_brings_the_cut_cluster_back(self):
        world, tree, lane = _bang_nong_roi_keo()
        with self.assertLogs("flow_web.sku", "INFO"):
            for _ in range(5):
                world.beat(lane)
        self.assertEqual([NHO], world.filled)
        doc = len(tree.doc)

        # Có người sửa thẻ A: dấu dòng đổi, làn xét lại cụm từ đầu.  Phút này
        # còn phần NHO vừa tiêu, nên cụm chờ, đọc lại cây gốc khi có chỗ, rồi
        # chờ trọn một cửa sổ mới nhường lần nữa.
        _dong(world, A)["modified"] = "2026-09-11 16:10:00"
        with self.assertLogs("flow_web.sku", "INFO") as seen:
            result = world.beat(lane)
            for _ in range(4):
                world.beat(lane)

        self.assertEqual({"waiting": GOC}, {k: v for k, v in result.items() if k != "read"})
        self.assertIn(GOC, tree.doc[doc:])
        self.assertEqual(1, _nhuong(seen))
        self.assertEqual([NHO], world.filled)

    def test_a_short_wait_still_gets_its_turn(self):
        # Cụm cắt một thẻ ngoài cây: đọc bảng 1 + cây gốc 1 + cây thẻ 1 +
        # fill_cost(1, cut_new=1) 9 = 12, lọt trần 20.  Phút trước làn đã tiêu
        # 10 chỗ, 30 giây trước nhịp đầu: cụm chờ hai nhịp rồi lọt.
        world, tree = _cum_cat()
        lane = world.lane(tree=tree, is_due=_den_han)
        world.now -= 30
        self.assertTrue(lane.budget.take(10))
        world.now += 30

        results = [lane.tick(), world.beat(lane), world.beat(lane)]

        self.assertEqual({"waiting": GOC}, {k: v for k, v in results[0].items() if k != "read"})
        self.assertEqual({"waiting": GOC}, {k: v for k, v in results[1].items() if k != "read"})
        self.assertEqual(GOC, results[2].get("filled"))
        self.assertEqual([GOC], world.filled)


if __name__ == "__main__":
    unittest.main()
