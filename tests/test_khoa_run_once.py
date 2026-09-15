"""Khoá lượt quét: mỗi thể hiện bot chỉ một ``run_once`` chạy tại một lúc.

Nút ``/api/agent-bot/run`` gọi ``run_once`` trên đúng thể hiện bot mà
``run_forever`` đang quét. Không khoá thì hai lượt đan nhau: ``_scan_boards``
bị gán lại giữa chừng, bảng bị đọc hai lần, sổ trạng thái bị ghi chồng.
Lượt tới sau trả ngay "đang quét", không chờ và không quét lần hai.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
import threading
import time
import unittest
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

from flow_web.agent_bot import build_sku_fast_lane
from flow_web.sku import SkuFastLaneConfig
from tests.test_agent_bot import BOT, FakeClient, build_bot, task_node

# Giây. Test chờ quá mức này là hỏng, không phải chậm.
CHO = 5.0


class DemRequest(FakeClient):
    """Client giả đếm request. Lời gọi ``taskProjects`` đầu tiên chặn lại hoặc ném lỗi được."""

    def __init__(self, *args: Any, chan_dau: bool = False, loi_dau: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.requests: List[str] = []
        self.chan_dau = chan_dau
        self.loi_dau = loi_dau
        self.da_vao = threading.Event()
        self.tha = threading.Event()
        self._lan_dau = True
        self._khoa = threading.Lock()

    def task_projects(self) -> List[Dict[str, Any]]:
        with self._khoa:
            self.requests.append("taskProjects")
            dau, self._lan_dau = self._lan_dau, False
        if dau and self.loi_dau:
            raise RuntimeError("ERP hỏng giữa lượt")
        if dau and self.chan_dau:
            self.da_vao.set()
            if not self.tha.wait(CHO):
                raise RuntimeError("test không thả lượt đầu")
        return super().task_projects()

    def board_snapshot(self, project: str):
        with self._khoa:
            self.requests.append("taskBoard")
        return super().board_snapshot(project)

    def task_full(self, name: str, depth: int = 1) -> Dict[str, Any]:
        with self._khoa:
            self.requests.append("taskFull")
        return super().task_full(name, depth)


def client(**kwargs: Any) -> DemRequest:
    """Một dự án, một thẻ gốc gắn bot, một thẻ con Working chưa có mã."""
    child = task_node("C1", status="Working", parent_task="R")
    root = task_node("R", status="Working", agents=[BOT], project="PROJ-1", subtasks=[child])
    rows = [
        {"name": "R", "parent_task": "", "status": "Working", "custom_sku": "",
         "agents": [{"bot_user": BOT}], "modified": "2026-09-12 12:00:00"},
        {"name": "C1", "parent_task": "R", "status": "Working", "custom_sku": "",
         "agents": [], "modified": "2026-09-12 12:00:00"},
    ]
    return DemRequest(["PROJ-1"], {"PROJ-1": rows}, {"R": {"root": root}}, **kwargs)


class KhoaRunOnceTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        # Bảng SKU ghi vào thư mục tạm, không bao giờ vào DATA_DIR thật.
        env = mock.patch.dict(os.environ, {"ERP_SKU_STATUS_FILE": str(self.tmp / "sku_status.json")})
        env.start()
        self.addCleanup(env.stop)

    def _bot(self, c: DemRequest, **overrides: Any):
        folder = self.tmp / f"bot-{id(c)}"
        folder.mkdir()
        return build_bot(c, folder, autorun=False, **overrides)

    def _mot_luot(self) -> DemRequest:
        """Số request và số lần ghi của đúng một lượt quét, để so."""
        c = client()
        asyncio.run(self._bot(c).run_once())
        return c

    async def _chen_luot_tay(self, bot: Any, c: DemRequest):
        """Lượt đầu chặn ở ``taskProjects``; gọi lượt thứ hai đúng lúc ấy."""
        dau = asyncio.create_task(bot.run_once())
        try:
            self.assertTrue(await asyncio.to_thread(c.da_vao.wait, CHO), "lượt đầu không tới taskProjects")
            bat_dau = time.monotonic()
            hai = await asyncio.wait_for(bot.run_once(), CHO)
            tre = time.monotonic() - bat_dau
        finally:
            c.tha.set()
        return await asyncio.wait_for(dau, CHO), hai, tre

    def test_hai_luot_dong_thoi_chi_mot_luot_quet(self) -> None:
        mot = self._mot_luot()
        c = client(chan_dau=True)
        bot = self._bot(c)

        dau, hai, tre = asyncio.run(self._chen_luot_tay(bot, c))

        self.assertEqual(["R"], dau["tasks"])
        # Lượt thứ hai: cùng dạng dict nút đang trả, thêm cờ và lý do.
        self.assertTrue(hai.get("busy"), hai)
        self.assertTrue(hai.get("enabled"), hai)
        self.assertIn("đang quét", hai.get("reason", ""))
        self.assertNotIn("tasks", hai)
        # Trả ngay, không chờ lượt đầu xong.
        self.assertLess(tre, 1.0)
        # Request và lần ghi đúng bằng một lượt.
        self.assertEqual(Counter(mot.requests), Counter(c.requests))
        self.assertEqual(1, Counter(c.requests)["taskProjects"])
        self.assertEqual(len(mot.agents_added), len(c.agents_added))

    def test_luot_dau_nem_loi_thi_khoa_duoc_nha(self) -> None:
        c = client(loi_dau=True)
        bot = self._bot(c)

        with self.assertRaises(RuntimeError):
            asyncio.run(bot.run_once())
        sau = asyncio.run(bot.run_once())

        self.assertNotIn("busy", sau)
        self.assertEqual(["R"], sau["tasks"])

    def test_luot_dau_bi_huy_thi_khoa_duoc_nha(self) -> None:
        c = client(chan_dau=True)
        bot = self._bot(c)

        async def chay() -> Dict[str, Any]:
            dau = asyncio.create_task(bot.run_once())
            try:
                self.assertTrue(await asyncio.to_thread(c.da_vao.wait, CHO))
                dau.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await dau
            finally:
                c.tha.set()
            return await asyncio.wait_for(bot.run_once(), CHO)

        sau = asyncio.run(chay())

        self.assertNotIn("busy", sau)
        self.assertEqual(["R"], sau["tasks"])

    def test_hai_luot_noi_tiep_deu_quet(self) -> None:
        c = client()
        bot = self._bot(c)

        dau = asyncio.run(bot.run_once())
        sau = asyncio.run(bot.run_once())

        self.assertEqual(["R"], dau["tasks"])
        self.assertEqual(["R"], sau["tasks"])
        self.assertNotIn("busy", sau)
        self.assertEqual(2, Counter(c.requests)["taskProjects"])

    def test_luot_nen_gap_luot_tay_thi_bo_luot_va_giu_nhip(self) -> None:
        c = client(chan_dau=True)
        bot = self._bot(c, poll_seconds=3600)

        async def chay() -> None:
            tay = asyncio.create_task(bot.run_once())
            nen = None
            try:
                self.assertTrue(await asyncio.to_thread(c.da_vao.wait, CHO))
                with self.assertLogs("flow_web.agent_bot", "INFO") as logs:
                    nen = asyncio.create_task(bot.run_forever(immediate=True))
                    await asyncio.sleep(0.3)
                # Lượt nền bỏ lượt ấy rồi ngủ tới nhịp sau, không đổ, không chờ.
                self.assertFalse(nen.done())
                self.assertEqual(1, Counter(c.requests)["taskProjects"])
                self.assertTrue(any("đang quét" in line for line in logs.output), logs.output)
            finally:
                c.tha.set()
                if nen is not None:
                    nen.cancel()
            await asyncio.wait_for(tay, CHO)
            if nen is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await nen

        asyncio.run(chay())

    def test_lan_nhanh_khong_bi_khoa_chan(self) -> None:
        c = client(chan_dau=True)
        bot = self._bot(c)
        # Đây đúng là cảnh khởi động lại: ``task_projects`` lượt đầu còn đang
        # kẹt, phạm vi làn nhanh lấy từ sổ cũ. ``load`` luôn điền cả hai danh
        # sách một lượt, nên mồi cả hai.
        bot.state.projects = ["PROJ-1"]
        bot.state.fast_lane_projects = ["PROJ-1"]
        filled: List[str] = []

        def fill(root: str) -> Dict[str, Any]:
            filled.append(root)
            return {"written": [{"task_id": root}], "failed": []}

        lane = build_sku_fast_lane(bot, fill, SkuFastLaneConfig(enabled=True))

        async def chay() -> None:
            tay = asyncio.create_task(bot.run_once())
            try:
                self.assertTrue(await asyncio.to_thread(c.da_vao.wait, CHO))
                # Lượt quét đang giữ khoá; làn nhanh vẫn đánh số được.
                await asyncio.wait_for(asyncio.to_thread(lane.tick), CHO)
            finally:
                c.tha.set()
            await asyncio.wait_for(tay, CHO)

        asyncio.run(chay())

        self.assertEqual(["R"], filled)


if __name__ == "__main__":
    unittest.main()
