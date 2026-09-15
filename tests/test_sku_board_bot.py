"""Bot ghi ``sku_status.json`` sau mỗi lượt quét, cho phần "SKU & Thuộc tính" của bảng.

Bảng điều khiển không gọi ERP: nó chỉ đọc tệp này qua bản Listing. Bot không
ghi thì bảng đứng ở "chưa có số" mãi, dù bot vẫn quét đều. Ghi hỏng thì bảng
mất một lượt số, còn lượt quét của bot phải xong như thường.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flow_web import sku_board
from tests.test_agent_bot import BOT, FakeClient, build_bot, comment, task_node


def _client() -> FakeClient:
    mine = {"name": "TASK-1", "agents": [{"bot_user": BOT}], "child_total": 1}
    child = task_node("TASK-2", comments=[comment("c1", like=1)])
    return FakeClient(
        ["PROJ-0049"],
        {"PROJ-0049": [mine]},
        {"TASK-1": {"root": task_node("TASK-1", agents=[BOT], subtasks=[child])}},
    )


class BotGhiTepSkuTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.target = self.tmp / "downloads" / sku_board.SKU_STATUS_FILE
        env = mock.patch.dict(os.environ, {"ERP_SKU_STATUS_FILE": str(self.target)})
        env.start()
        self.addCleanup(env.stop)

    def test_moi_luot_quet_ghi_tep_cho_bang(self) -> None:
        bot = build_bot(_client(), self.tmp, autorun=False, poll_seconds=30)
        summary = asyncio.run(bot.run_once())

        self.assertEqual(["TASK-1"], summary["tasks"])
        data = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertEqual(["TASK-1"], [cluster["task"] for cluster in data["clusters"]])
        self.assertEqual(["TASK-2"], [card["task"] for card in data["cards"]])
        # Bảng dựa vào nhịp này để biết số đã cũ chưa.
        self.assertEqual(30, data["every"])

    def test_bang_doc_duoc_dung_tep_bot_vua_ghi(self) -> None:
        asyncio.run(build_bot(_client(), self.tmp, autorun=False).run_once())
        api = mock.Mock(base="http://listing")
        api.lister_status.side_effect = lambda name: json.loads(
            (self.target.parent / name).read_text(encoding="utf-8")
        )

        view = sku_board.build_sku(api)

        self.assertEqual("", view["sources"]["sku"])
        self.assertEqual("ok", view["bot"]["tone"])
        self.assertEqual(["TASK-1"], [cluster["task"] for cluster in view["clusters"]])

    def test_ghi_tep_hong_thi_luot_quet_van_xong(self) -> None:
        with mock.patch.object(sku_board, "snapshot", side_effect=RuntimeError("hỏng")):
            with self.assertLogs("flow_web.sku_board", level="WARNING") as nhat_ky:
                summary = asyncio.run(build_bot(_client(), self.tmp, autorun=False).run_once())

        self.assertEqual(["TASK-1"], summary["tasks"])
        self.assertFalse(self.target.exists())
        self.assertTrue(any("không ghi được" in dong for dong in nhat_ky.output))

    def test_khong_dat_bien_nao_thi_bot_van_quet(self) -> None:
        os.environ.pop("ERP_SKU_STATUS_FILE", None)
        os.environ.pop("ERP_LISTING_FILES_DIR", None)

        summary = asyncio.run(build_bot(_client(), self.tmp, autorun=False).run_once())

        self.assertEqual(["TASK-1"], summary["tasks"])
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
