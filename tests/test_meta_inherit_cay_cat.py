"""Cây ``taskFull`` bị cắt: thẻ con nằm ngoài cây vẫn nhận Thuộc tính của cha.

12/09, cụm 04628 (PROJ-0018): ERP cắt cây ở 60 nút, 37 thẻ Working nằm
ngoài phần nhận được trống cả 4 ô Thuộc tính.  ``meta_inherit_pass`` chỉ đi
cây nhìn thấy nên không bao giờ chạm tới chúng, và Review Lister — đọc khối
Thuộc tính của thẻ con — không đăng được.  Thẻ ngoài cây chỉ còn thấy trên
``taskBoard``.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock

from flow_web.agent_bot import (
    META_INHERIT_BACKOFF_SECONDS,
    META_INHERIT_PER_SCAN,
    AgentBot,
    AgentBotError,
)
from tests.test_agent_bot import BOT, FakeClient, build_bot, task_node

GOC = "TASK-2026-04628"
DU_AN = "PROJ-0018"
BON_O = {
    "product_type": "Embroidered Ornament",
    "production_type": "handmade",
    "fulfillment": "FBM",
    "sales_channel": "Etsy",
}
META_GOC = "".join(f"{key}: {value}\n" for key, value in BON_O.items())


class _DemBang(FakeClient):
    """``FakeClient`` đếm lượt đọc ``taskBoard``, và hỏng khi được bảo."""

    def __init__(self, *args: Any, loi: Exception | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.doc_bang: List[str] = []
        self._loi = loi

    def board_snapshot(self, project: str):
        self.doc_bang.append(project)
        if self._loi is not None:
            raise self._loi
        return super().board_snapshot(project)


def _ten(so: int) -> str:
    return f"TASK-2026-{so:05d}"


def _dong(name: str, status: str = "Working", parent: str = GOC) -> Dict[str, Any]:
    """Một dòng ``taskBoard``: không kèm khối Thuộc tính."""
    return {"name": name, "status": status, "parent_task": parent, "custom_sku": ""}


def _cay_cat(con_trong_cay: List[Dict[str, Any]] | None = None, *, meta: str = META_GOC) -> Dict[str, Any]:
    """Gốc 04628 như ERP trả khi cắt: 97 con, nhận 60, cả 60 đã đủ Thuộc tính."""
    if con_trong_cay is None:
        con_trong_cay = [
            task_node(_ten(6800 + i), status="Open", parent_task=GOC, meta=META_GOC) for i in range(60)
        ]
    return task_node(
        GOC, agents=[BOT], status="Working", project=DU_AN, meta=meta, subtasks=con_trong_cay, child_total=97
    )


def _bang(root: Dict[str, Any], an: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Bảng dự án: gốc, mọi thẻ trong cây, rồi các thẻ bị cắt khỏi cây."""
    rows = [{"name": GOC, "status": "Working", "parent_task": "", "agents": [{"bot_user": BOT}]}]
    rows += [_dong(node["name"], node.get("status") or "Open") for node in root["subtasks"]]
    return rows + an


class MetaInheritCayCatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.goi: List[tuple[str, Dict[str, str]]] = []

    def _hook(self, task_id: str, values: Dict[str, str]) -> Dict[str, Any]:
        self.goi.append((task_id, dict(values)))
        return {"task_id": task_id, "written": dict(values)}

    def _bot(self, client: FakeClient, hook=None, **overrides: Any) -> AgentBot:
        bot = build_bot(client, self.tmp, **overrides)
        bot.meta_inherit_hook = hook or self._hook
        return bot

    def _luot(self, bot: AgentBot, root: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Một lượt quét, chỉ phần chép Thuộc tính: trần và bảng mới."""
        bot._meta_inherit_left = META_INHERIT_PER_SCAN
        bot._scan_boards = {}
        return bot.meta_inherit_pass({"root": root}, BOT)

    def _da_hoi(self) -> List[str]:
        return [task for task, _ in self.goi]

    # 1. Ca thật: 37 thẻ Working ngoài cây, cộng vài thẻ Open ngoài cây.
    # Mỗi lượt hỏi đúng 8 thẻ, Working trước; thẻ đã hỏi không bị hỏi lại.
    def test_37_the_working_ngoai_cay_nhan_thuoc_tinh_moi_luot_8_the(self) -> None:
        root = _cay_cat()
        working = [_dong(_ten(5200 + i)) for i in range(37)]
        open_ = [_dong(_ten(5100 + i), "Open") for i in range(3)]
        client = _DemBang([DU_AN], {DU_AN: _bang(root, open_ + working)}, {})
        bot = self._bot(client)

        self._luot(bot, root)
        self.assertEqual([row["name"] for row in working[:8]], self._da_hoi())
        self.assertTrue(all(values == BON_O for _, values in self.goi))

        self._luot(bot, root)
        self.assertEqual([row["name"] for row in working[:16]], self._da_hoi())

        for _ in range(10):
            self._luot(bot, root)
        hoi = self._da_hoi()
        self.assertEqual(40, len(hoi))
        self.assertEqual(len(hoi), len(set(hoi)), "thẻ đã hỏi mà giá trị cha không đổi bị hỏi lại")
        self.assertEqual([row["name"] for row in working + open_], hoi)

        # Thẻ cha đổi giá trị: cả cụm được hỏi lại, với giá trị mới.
        root["meta"] = META_GOC.replace("FBM", "FBA")
        self._luot(bot, root)
        self.assertEqual(40 + META_INHERIT_PER_SCAN, len(self.goi))
        self.assertEqual("FBA", self.goi[-1][1]["fulfillment"])

    # 2. Cây không bị cắt: không đọc bảng.
    def test_cay_khong_cat_thi_khong_doc_task_board(self) -> None:
        con = [task_node(_ten(6800 + i), parent_task=GOC, meta="") for i in range(3)]
        root = task_node(GOC, agents=[BOT], project=DU_AN, meta=META_GOC, subtasks=con)
        client = _DemBang([DU_AN], {DU_AN: _bang(root, [_dong(_ten(5200))])}, {})

        self._luot(self._bot(client), root)

        self.assertEqual([], client.doc_bang)
        self.assertEqual([node["name"] for node in con], self._da_hoi())

    # 3. Chép Thuộc tính và đánh số trong cùng lượt: mỗi dự án đọc bảng một lần.
    def test_chep_thuoc_tinh_va_danh_so_cung_luot_doc_bang_mot_lan(self) -> None:
        root = _cay_cat()
        client = _DemBang([DU_AN], {DU_AN: _bang(root, [_dong(_ten(5200))])}, {})
        bot = self._bot(client)
        bot.pipeline_hook = AsyncMock(return_value={"moved": False})

        self._luot(bot, root)
        asyncio.run(bot.pipeline_pass({"root": root}))

        self.assertEqual([_ten(5200)], self._da_hoi())
        self.assertEqual([_ten(5200)], [call.args[0] for call in bot.pipeline_hook.await_args_list])
        self.assertEqual([DU_AN], client.doc_bang)

    # 3b. Lượt quét thật, qua constructor thật: bảng đọc trong
    # ``candidate_tasks`` được dùng lại, và lượt sau không hỏi lại thẻ đã hỏi.
    def test_luot_quet_that_khong_doc_them_bang_va_khong_hoi_lai(self) -> None:
        root = _cay_cat()
        client = _DemBang([DU_AN], {DU_AN: _bang(root, [_dong(_ten(5200))])}, {GOC: {"root": root}})
        bot = self._bot(client)
        bot.autorun_hook = AsyncMock(return_value={"queued": []})

        summary = asyncio.run(bot.run_once())

        self.assertEqual([_ten(5200)], self._da_hoi())
        self.assertEqual([{"task": _ten(5200), "keys": sorted(BON_O)}], summary["meta_inherited"])
        self.assertEqual([DU_AN], client.doc_bang)

        summary = asyncio.run(bot.run_once())

        self.assertEqual([_ten(5200)], self._da_hoi())
        self.assertEqual([], summary["meta_inherited"])
        self.assertEqual([DU_AN, DU_AN], client.doc_bang)

    # 4. Đọc bảng hỏng: lượt quét không đổ, phần cây nhìn thấy vẫn chép.
    def test_doc_bang_hong_van_chep_phan_cay_nhin_thay(self) -> None:
        con = [task_node(_ten(6800 + i), status="Open", parent_task=GOC, meta=META_GOC) for i in range(60)]
        con[0] = task_node(_ten(6800), status="Open", parent_task=GOC, meta="")
        root = _cay_cat(con)
        client = _DemBang([DU_AN], {}, {}, loi=AgentBotError("ERP trả 500"))

        with self.assertLogs("flow_web.agent_bot", level="WARNING") as nhat_ky:
            done = self._luot(self._bot(client), root)

        self.assertEqual([_ten(6800)], self._da_hoi())
        self.assertEqual([_ten(6800)], [item["task"] for item in done])
        self.assertEqual([DU_AN], client.doc_bang)
        self.assertTrue(any("ERP trả 500" in dong for dong in nhat_ky.output))

    # 5. Thẻ Cancelled, thẻ bị tạm dừng, thẻ của cụm khác: không gọi hook.
    def test_the_huy_tam_dung_hay_cum_khac_thi_khong_goi(self) -> None:
        root = _cay_cat()
        an = [
            _dong(_ten(5200), "Cancelled"),
            _dong(_ten(5201)),
            _dong(_ten(5202), parent="TASK-2026-09999"),
            _dong(_ten(5203)),
        ]
        client = _DemBang([DU_AN], {DU_AN: _bang(root, an)}, {})
        bot = self._bot(client)
        bot.state.pause(_ten(5201))

        self._luot(bot, root)

        self.assertEqual([_ten(5203)], self._da_hoi())

    # 6. Thẻ cha trực tiếp nằm trong cây, khai riêng FBA: thẻ ngoài cây nhận FBA.
    # Thẻ cha cũng bị giấu: bỏ qua, vì không biết thẻ cha ấy khai riêng gì.
    def test_cha_trong_cay_khai_fba_thi_the_ngoai_cay_nhan_fba(self) -> None:
        con = [task_node(_ten(6800 + i), status="Open", parent_task=GOC, meta=META_GOC) for i in range(60)]
        cha = _ten(6800)
        con[0] = task_node(cha, status="Open", parent_task=GOC, meta="fulfillment: FBA\n")
        root = _cay_cat(con)
        an = [_dong(_ten(5200), parent=cha), _dong(_ten(5300)), _dong(_ten(5301), parent=_ten(5300))]
        client = _DemBang([DU_AN], {DU_AN: _bang(root, an)}, {})

        self._luot(self._bot(client), root)

        goi = dict(self.goi)
        self.assertEqual({**BON_O, "fulfillment": "FBA"}, goi[_ten(5200)])
        self.assertEqual(BON_O, goi[_ten(5300)])
        self.assertNotIn(_ten(5301), goi)

    # 7. Ô của riêng từng thẻ không xuống thẻ ngoài cây.
    def test_khong_truyen_content_master_sku_sku_xuong(self) -> None:
        meta = META_GOC + "content: mo ta rieng\nmaster_sku: OR_1\nsku: OR_1_001\n"
        root = _cay_cat(meta=meta)
        client = _DemBang([DU_AN], {DU_AN: _bang(root, [_dong(_ten(5200))])}, {})

        self._luot(self._bot(client), root)

        self.assertEqual([(_ten(5200), BON_O)], self.goi)

    # 8. Hook ném lỗi: dừng lượt, cụm nghỉ như cũ.
    def test_hook_loi_thi_cum_nghi_nhu_cu(self) -> None:
        def tu_choi(task_id: str, values: Dict[str, str]) -> Dict[str, Any]:
            self.goi.append((task_id, dict(values)))
            raise RuntimeError("ERP đang giới hạn request (HTTP 429).")

        root = _cay_cat()
        client = _DemBang([DU_AN], {DU_AN: _bang(root, [_dong(_ten(5200)), _dong(_ten(5201))])}, {})
        bot = self._bot(client, hook=tu_choi)

        self.assertEqual([], self._luot(bot, root))
        self.assertEqual([_ten(5200)], self._da_hoi())
        self.assertFalse(bot.state.autorun_is_cool(f"meta:{GOC}", META_INHERIT_BACKOFF_SECONDS))

        self._luot(bot, root)
        self.assertEqual([_ten(5200)], self._da_hoi())

    # 9. Trần tính chung: cây nhìn thấy dùng 5 thì ngoài cây chỉ còn 3.
    def test_tran_tinh_chung_voi_phan_cay_nhin_thay(self) -> None:
        con = [task_node(_ten(6800 + i), status="Open", parent_task=GOC, meta=META_GOC) for i in range(60)]
        for i in range(5):
            con[i] = task_node(_ten(6800 + i), status="Open", parent_task=GOC, meta="")
        root = _cay_cat(con)
        an = [_dong(_ten(5200 + i)) for i in range(10)]
        client = _DemBang([DU_AN], {DU_AN: _bang(root, an)}, {})

        self._luot(self._bot(client), root)

        self.assertEqual(
            [_ten(6800 + i) for i in range(5)] + [_ten(5200 + i) for i in range(META_INHERIT_PER_SCAN - 5)],
            self._da_hoi(),
        )

    # 10. Hook trả rỗng (thẻ đã đủ): vẫn tính vào trần, và được nhớ.
    def test_the_da_du_van_tinh_tran_va_khong_hoi_lai(self) -> None:
        root = _cay_cat()
        an = [_dong(_ten(5200 + i)) for i in range(10)]
        client = _DemBang([DU_AN], {DU_AN: _bang(root, an)}, {})

        def da_du(task_id: str, values: Dict[str, str]) -> Dict[str, Any]:
            self.goi.append((task_id, dict(values)))
            return {"task_id": task_id, "written": {}}

        bot = self._bot(client, hook=da_du)
        self.assertEqual([], self._luot(bot, root))
        self.assertEqual(META_INHERIT_PER_SCAN, len(self.goi))

        self._luot(bot, root)
        self._luot(bot, root)
        self.assertEqual(10, len(self.goi))
        self.assertEqual(10, len(set(self._da_hoi())))

    # 11. dry_run: kể tên, không gọi hook.
    def test_dry_run_ke_ten_khong_ghi(self) -> None:
        root = _cay_cat()
        client = _DemBang([DU_AN], {DU_AN: _bang(root, [_dong(_ten(5200))])}, {})

        done = self._luot(self._bot(client, dry_run=True), root)

        self.assertEqual([], self.goi)
        self.assertEqual([{"task": _ten(5200), "keys": sorted(BON_O), "dry_run": True}], done)


if __name__ == "__main__":
    unittest.main()
