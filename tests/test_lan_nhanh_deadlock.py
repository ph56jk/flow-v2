"""Làn nhanh SKU gặp ERP 500 ``QueryDeadlockError``: đọc lại ở nhịp kế.

Sau dot7 (12/09, hvg-pc), từ 12:54 tới 13:56 log có 12 dòng
``Làn nhanh SKU không đọc được bảng …: ERP HTTP 500: {"exc_type":"QueryDeadlockError"}``.
Cả 12 đều ở lượt đọc bảng của làn nhanh.  Bot đọc cùng các bảng, cùng query,
thì không lần nào.  Code 52a9383 coi lỗi này như mọi lỗi khác: dời bảng ấy
300 s (``rediscover_s``).  Bảng nóng gặp nó thì thẻ vừa kéo chờ thêm tới
5 phút.

Luật mới (PRD ``tasks/lan-nhanh-deadlock.md``):

- lỗi mang chữ ``QueryDeadlockError`` thì đọc lại bảng ấy ở nhịp kế
  (``interval_s``), đúng **một** lần; lần thử lại cũng lỗi thì về 300 s;
- đọc được thì lượt thử lại tính lại từ đầu;
- lần thử lại đi qua ``RequestBudget`` như mọi lần đọc: trần 20/phút giữ;
- 429 vẫn nghỉ cả làn ``rest_s``; lỗi khác vẫn dời 300 s;
- mỗi lần lỗi vẫn một dòng cảnh báo, giữ đầu câu cũ để c8 đếm được, và
  bắt buộc có đuôi: ``(đọc lại ở nhịp kế)`` khi còn lượt thử lại,
  ``(dời <N> giây)`` khi không.  Đếm hai loại đuôi là ra tỉ lệ đọc lại
  thành công.

Không mạng: bảng, đồng hồ và lượt đánh số giả lấy từ ``_LaneWorld``.
"""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from flow_web.agent_bot import AgentBotClient, AgentBotConfig
from flow_web.sku import SkuFastLaneConfig
from tests.test_sku import _cluster, _LaneWorld, board_row

DU_AN = "PROJ-0027"
#: Đúng chuỗi ``AgentBotClient.graphql`` dựng (agent_bot.py:431), như trong log.
LOI_DEADLOCK = 'ERP HTTP 500: {"exc_type":"QueryDeadlockError"}'
LOI_429 = "ERP đang giới hạn tốc độ token bot (HTTP 429)."
LOI_500_KHAC = 'ERP HTTP 500: {"exc_type":"ValidationError"}'
NHIP = SkuFastLaneConfig().interval_s
DOI = SkuFastLaneConfig().rediscover_s
#: Đuôi dòng cảnh báo (PRD mục 4, luật 6).  B là cách đo duy nhất: c8 đếm
#: hai loại đuôi để tính tỉ lệ đọc lại thành công.
DUOI_DOC_LAI = r" \(đọc lại ở nhịp kế\)$"
DUOI_DOI = r" \(dời %d giây\)$" % DOI


class _TheGioiLoi(_LaneWorld):
    """``_LaneWorld`` với lỗi riêng từng bảng.

    ``loi[du_an]`` là hàng lỗi ném lần lượt, hết hàng thì đọc được.
    ``hong[du_an]`` là lỗi ném mãi.  Lần đọc lỗi vẫn tính là một request.
    """

    def __init__(self, boards, **kwargs):
        super().__init__(boards, **kwargs)
        self.loi = {}
        self.hong = {}

    def board(self, project):
        rows = super().board(project)
        if project in self.hong:
            raise self.hong[project]
        queue = self.loi.get(project)
        if queue:
            raise queue.pop(0)
        return rows

    def luc_doc(self, project):
        return [when for when, _, what in self.spent if what == "board:" + project]


def _deadlock():
    return RuntimeError(LOI_DEADLOCK)


class DeadlockDocLaiTests(unittest.TestCase):
    """Một lần deadlock chỉ được làm chậm một nhịp, không phải năm phút."""

    def test_the_vua_keo_gap_mot_deadlock_van_co_ma_trong_45_giay(self):
        world = _TheGioiLoi({DU_AN: _cluster("R", ("C1", "Open"))})
        lane = world.lane()
        lane.tick()
        self.assertEqual([], world.filled)

        # Người kéo C1 sang Đang làm; lần đọc bảng kế tiếp gặp deadlock.
        world.boards[DU_AN][1]["status"] = "Working"
        world.loi[DU_AN] = [_deadlock()]
        dragged = world.now
        with self.assertLogs("flow_web.sku", "WARNING"):
            while not world.filled and world.now - dragged < 400:
                world.beat(lane)

        self.assertEqual(["R"], world.filled)
        # Hứa 30 s; một lần deadlock tốn thêm đúng một nhịp.
        self.assertLessEqual(world.now - dragged, 30 + NHIP)

    def test_bang_chua_doc_lan_nao_gap_deadlock_duoc_doc_lai_o_nhip_ke(self):
        world = _TheGioiLoi({DU_AN: _cluster("R", ("C1", "Working"))})
        world.loi[DU_AN] = [_deadlock()]
        lane = world.lane()
        start = world.now

        with self.assertLogs("flow_web.sku", "WARNING"):
            lane.tick()
        self.assertEqual([], world.filled)
        while not world.filled and world.now - start < 400:
            world.beat(lane)

        self.assertEqual(["R"], world.filled)
        self.assertLessEqual(world.now - start, 2 * NHIP)

    def test_hai_bang_deadlock_cung_nhip_deu_duoc_doc_lai(self):
        # Như 13:25:28: PROJ-0013 và PROJ-0018 cùng lỗi trong một nhịp.
        world = _TheGioiLoi(
            {"PROJ-0013": _cluster("R1", ("C1", "Open")), "PROJ-0018": _cluster("R2", ("C2", "Open"))}
        )
        lane = world.lane()
        lane.tick()
        world.loi = {"PROJ-0013": [_deadlock()], "PROJ-0018": [_deadlock()]}
        with self.assertLogs("flow_web.sku", "WARNING"):
            world.beat(lane)
        before = len(world.reads())

        world.beat(lane)

        self.assertEqual({"board:PROJ-0013", "board:PROJ-0018"}, set(world.reads()[before:]))

    def test_doc_duoc_thi_luot_thu_lai_tinh_lai_tu_dau(self):
        # Deadlock, đọc lại được, rồi deadlock lần nữa: lần sau vẫn được đọc
        # lại ở nhịp kế.  Đếm tổng số lần lỗi của bảng là sai.
        world = _TheGioiLoi({DU_AN: _cluster("R", ("C1", "Open"))})
        lane = world.lane()
        lane.tick()

        with self.assertLogs("flow_web.sku", "WARNING") as seen:
            world.loi[DU_AN] = [_deadlock()]
            world.beat(lane)
            world.beat(lane)
            world.loi[DU_AN] = [_deadlock()]
            world.beat(lane)
        failed = world.now
        world.beat(lane)

        self.assertIn(failed + NHIP, world.luc_doc(DU_AN))
        # Cả hai lần đều còn lượt thử lại.
        self.assertEqual(2, len(seen.output), seen.output)
        for line in seen.output:
            self.assertRegex(line, DUOI_DOC_LAI)

    def test_deadlock_cung_nhip_voi_429_het_nghi_la_doc_lai(self):
        world = _TheGioiLoi({DU_AN: _cluster("R", ("C1", "Open")), "PROJ-0068": _cluster("S", ("D1", "Open"))})
        lane = world.lane()
        lane.tick()
        world.loi = {DU_AN: [_deadlock()], "PROJ-0068": [RuntimeError(LOI_429)]}
        with self.assertLogs("flow_web.sku", "WARNING"):
            self.assertTrue(world.beat(lane).get("resting"))
        failed = world.now

        while world.now - failed < SkuFastLaneConfig().rest_s:
            world.beat(lane)

        # Nghỉ xong thì bảng deadlock đến hạn luôn, không chờ tới 300 s.
        self.assertIn(world.now, world.luc_doc(DU_AN))

    def test_loi_that_tu_graphql_duoc_nhan_la_deadlock(self):
        # Lỗi đi đúng đường thật: HTTP 500 → ``AgentBotClient.graphql`` →
        # ``board_snapshot`` → làn nhanh.  Không mạng: ``urlopen`` giả.
        rows = _cluster("R", ("C1", "Working"))
        client = AgentBotClient(AgentBotConfig(token="t", timeout_s=0.01))
        calls = []

        def urlopen(request, timeout=None):
            calls.append(request)
            if len(calls) == 1:
                body = io.BytesIO(b'{"exc_type":"QueryDeadlockError"}')
                raise HTTPError(request.full_url, 500, "Internal Server Error", {}, body)
            return _Response({"data": {"taskBoard": {"columns": [{"name": "Working", "tasks": rows}]}}})

        world = _TheGioiLoi({DU_AN: rows})
        lane = world.lane(board=lambda project: client.board_snapshot(project)[0])
        start = world.now
        with patch("flow_web.agent_bot.urlopen", side_effect=urlopen), patch("flow_web.agent_bot.time.sleep"):
            with self.assertLogs("flow_web.sku", "WARNING") as seen:
                lane.tick()
            self.assertIn("QueryDeadlockError", "\n".join(seen.output))
            while not world.filled and world.now - start < 400:
                world.beat(lane)

        self.assertEqual(["R"], world.filled)
        self.assertLessEqual(world.now - start, 2 * NHIP)
        # Dòng thật, như c8 sẽ thấy trong log.
        self.assertRegex(seen.output[0], r"PROJ-0027: ERP HTTP 500: .*QueryDeadlockError.*" + DUOI_DOC_LAI)


class DeadlockCanhTests(unittest.TestCase):
    """Canh: thử lại có trần, trần request giữ, các lỗi khác đi như cũ."""

    def test_deadlock_mai_chi_doc_toi_da_hai_lan_moi_5_phut(self):
        world = _TheGioiLoi({DU_AN: _cluster("R", ("C1", "Open"))})
        lane = world.lane()
        lane.tick()
        world.hong[DU_AN] = _deadlock()
        start = world.now

        with self.assertLogs("flow_web.sku", "WARNING") as seen:
            while world.now - start < 3 * DOI:
                world.beat(lane)

        times = [when for when in world.luc_doc(DU_AN) if when > start]
        self.assertTrue(times)
        worst = max(sum(1 for when in times if end - DOI < when <= end) for end in times)
        self.assertLessEqual(worst, 2, times)
        self.assertLessEqual(world.worst_minute(), 20)
        # Luật 2 trong log: còn lượt thì đọc lại, hết lượt thì dời 300 s, rồi
        # lần lỗi sau lại được một lượt.  Hai đuôi xen kẽ nhau.
        self.assertGreaterEqual(len(seen.output), 4, seen.output)
        for index, line in enumerate(seen.output):
            self.assertRegex(line, DUOI_DOI if index % 2 else DUOI_DOC_LAI)

    def test_nhieu_bang_deadlock_van_giu_tran_20_request_moi_phut(self):
        # 28 bảng nguội, 2 bảng nóng: gần với hvg-pc.  Ba mươi bảng cùng nóng
        # thì lượt đọc 15 s đã ăn hết trần, không cần deadlock.
        boards = {"PROJ-%04d" % so: [board_row("X%d" % so)] for so in range(1, 29)}
        boards.update({"PROJ-0029": _cluster("R1", ("C1", "Open")), "PROJ-0030": _cluster("R2", ("C2", "Open"))})
        world = _TheGioiLoi(boards)
        lane = world.lane()
        start = world.now

        with self.assertLogs("flow_web.sku", "WARNING"):
            lane.tick()
            while world.now - start < 2 * DOI:
                world.beat(lane)
            # Mọi bảng đều hỏng một lúc, rồi hết hỏng.
            world.hong = {project: _deadlock() for project in boards}
            while world.now - start < 4 * DOI:
                world.beat(lane)
        world.hong = {}
        for project in ("PROJ-0029", "PROJ-0030"):
            boards[project][1]["status"] = "Working"
        while world.now - start < 6 * DOI:
            world.beat(lane)

        self.assertLessEqual(world.worst_minute(), 20)
        self.assertEqual(["R1", "R2"], sorted(world.filled))

    def test_429_van_nghi_ca_lan_mot_phut(self):
        world = _TheGioiLoi({DU_AN: _cluster("R", ("C1", "Open")), "PROJ-0068": _cluster("S", ("D1", "Open"))})
        lane = world.lane()
        lane.tick()
        world.loi = {DU_AN: [_deadlock()], "PROJ-0068": [RuntimeError(LOI_429)]}
        with self.assertLogs("flow_web.sku", "WARNING"):
            self.assertTrue(world.beat(lane).get("resting"))
        before = len(world.reads())

        for _ in range(3):
            self.assertTrue(world.beat(lane).get("resting"))

        self.assertEqual(before, len(world.reads()))

    def test_loi_500_khac_van_doi_5_phut(self):
        for loi in (LOI_500_KHAC, "ERP GraphQL: Không có quyền", "ERP trả dữ liệu không phải JSON."):
            with self.subTest(loi=loi):
                world = _TheGioiLoi({DU_AN: _cluster("R", ("C1", "Open"))})
                lane = world.lane()
                lane.tick()
                world.loi[DU_AN] = [RuntimeError(loi)]
                with self.assertLogs("flow_web.sku", "WARNING") as seen:
                    world.beat(lane)
                failed = world.now

                while world.now - failed < DOI - NHIP:
                    world.beat(lane)

                self.assertEqual([], [when for when in world.luc_doc(DU_AN) if when > failed])
                self.assertEqual(1, len(seen.output), seen.output)
                self.assertRegex(seen.output[0], DUOI_DOI)

    def test_deadlock_van_ghi_mot_dong_canh_bao(self):
        # c8 đếm deadlock bằng dòng này sau deploy: giữ đầu câu, tên lỗi, và
        # đuôi cho biết còn lượt đọc lại.
        world = _TheGioiLoi({DU_AN: _cluster("R", ("C1", "Open"))})
        world.loi[DU_AN] = [_deadlock()]
        lane = world.lane()

        with self.assertLogs("flow_web.sku", "WARNING") as seen:
            lane.tick()

        self.assertEqual(1, len(seen.output))
        self.assertRegex(seen.output[0], r"Làn nhanh SKU không đọc được bảng PROJ-0027: .*QueryDeadlockError")
        self.assertRegex(seen.output[0], DUOI_DOC_LAI)


class _Response:
    """Phản hồi ``urlopen`` giả, đủ cho ``AgentBotClient.graphql``."""

    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._raw


if __name__ == "__main__":
    unittest.main()
