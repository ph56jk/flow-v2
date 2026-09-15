"""Ghim luật: khi nào bot tự đánh mã SKU cho thẻ con.

Seller báo thẻ hơn 1 tiếng vẫn chưa có mã.  Bot chỉ đánh số khi
``pipeline.needs_sku_fill(stage)`` đúng; khi ấy ``AgentBot.pipeline_pass``
gọi ``pipeline_hook`` cho thẻ.  Các ca dưới đây dùng hàm thật để khoanh
đúng thẻ nào được gọi, thẻ nào không.

Lưu ý: hook còn được gọi khi thẻ có **nước đi chuyển cột** (``decide``
trả cột đích).  Ca ``Open`` và ca "đã có sku" vì thế kiểm riêng
``needs_sku_fill`` — hook có được gọi ở đó thì là để chuyển cột, không
phải để đánh số.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock

from flow_web import pipeline
from flow_web.agent_bot import AgentBot, AgentBotError, card_stage
from flow_web.sku import cards_missing_sku
from tests.test_agent_bot import FakeClient, build_bot, comment, task_node


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


def _con(name: str = "TASK-2", **extra: Any) -> Dict[str, Any]:
    """Thẻ con idea: có thẻ cha, mang ảnh máy."""
    extra.setdefault("comments", [comment("c1", like=1), comment("c2", like=1)])
    return task_node(name, parent_task="TASK-1", **extra)


def _goc(*con: Dict[str, Any], status: str = "Working") -> Dict[str, Any]:
    return task_node("TASK-1", status=status, subtasks=list(con))


def _cay_bi_cat(goc: str = "TASK-1", dau: int = 100) -> Dict[str, Any]:
    """Cây như ERP trả khi cắt: 79 con, nhận 60, cả 60 ở Open, ảnh còn chờ phiếu.

    Ảnh chờ phiếu là cố ý: 60 thẻ Open không có nước đi nào, nên hook có
    được gọi thì chỉ có thể là để đánh số, không phải để chuyển cột.
    """
    con = [
        task_node(f"TASK-{i}", status="Open", parent_task=goc, comments=[comment(f"c{i}")])
        for i in range(dau, dau + 60)
    ]
    return task_node(goc, status="Working", project="PROJ-1", subtasks=con, child_total=79)


def _dong(name: str, status: str, parent: str = "TASK-1", sku: str = "") -> Dict[str, Any]:
    """Một dòng ``taskBoard``: không kèm bình luận, có ``custom_sku``."""
    return {"name": name, "status": status, "parent_task": parent, "custom_sku": sku}


class DanhSoCotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _bot(self, client: FakeClient | None = None, **overrides: Any) -> AgentBot:
        bot = build_bot(client or FakeClient([], {}, {}), self.tmp, **overrides)
        bot.pipeline_hook = AsyncMock(return_value={"moved": False})
        return bot

    def _goi(self, root: Dict[str, Any], client: FakeClient | None = None, **overrides: Any) -> List[str]:
        """Chạy một lượt ``pipeline_pass``, trả danh sách thẻ hook được gọi."""
        bot = self._bot(client, **overrides)
        asyncio.run(bot.pipeline_pass({"root": root}))
        return [call.args[0] for call in bot.pipeline_hook.await_args_list]

    def _stage(self, node: Dict[str, Any], root: Dict[str, Any]) -> pipeline.CardStage:
        return card_stage(node, cards_missing_sku=cards_missing_sku(root))

    # 1. Cột Working, ảnh đã 👍 hết, chưa có sku: hook được gọi.
    def test_working_anh_da_chot_chua_sku_thi_goi_hook(self) -> None:
        con = _con(status="Working")
        root = _goc(con)

        self.assertTrue(pipeline.needs_sku_fill(self._stage(con, root)))
        self.assertEqual(["TASK-2"], self._goi(root))

    # 2. Như trên, cột viết tiếng Việt.
    def test_cot_tieng_viet_dang_lam_cung_goi_hook(self) -> None:
        for ten in ("Đang làm", "đang làm", "Dang lam"):
            with self.subTest(cot=ten):
                con = _con(status=ten)
                root = _goc(con)

                self.assertEqual("Working", pipeline.normalize_status(ten))
                self.assertTrue(pipeline.needs_sku_fill(self._stage(con, root)))
                self.assertEqual(["TASK-2"], self._goi(root))

    # 3. Cột Open / Cần làm: không đánh số.  Ảnh đã chốt nên có nước đi sang
    # Working — hook có gọi thì là để chuyển cột, không phải đánh số.
    def test_open_hay_can_lam_khong_danh_so(self) -> None:
        for ten in ("Open", "Cần làm"):
            with self.subTest(cot=ten):
                con = _con(status=ten)
                root = _goc(con)
                stage = self._stage(con, root)

                self.assertFalse(pipeline.needs_sku_fill(stage))
                self.assertEqual("Working", pipeline.decide(stage).status)

    # 4. Working còn ảnh chờ 👍/👎: vẫn gọi — kéo sang cột này là đã chốt.
    def test_working_con_anh_cho_phieu_van_goi(self) -> None:
        con = _con(status="Working", comments=[comment("c1", like=1), comment("c2")])
        root = _goc(con)

        self.assertTrue(pipeline.needs_sku_fill(self._stage(con, root)))
        self.assertEqual(["TASK-2"], self._goi(root))

    # 4b. Nhưng 👎 hết thì không: idea ấy tay trắng, chờ chạy lại ảnh.
    def test_working_bi_bo_het_anh_thi_khong_goi(self) -> None:
        con = _con(status="Working", comments=[comment("c1", dislike=1), comment("c2", dislike=1)])
        root = _goc(con)

        self.assertFalse(pipeline.needs_sku_fill(self._stage(con, root)))
        self.assertEqual([], self._goi(root))

    # 5. Working đã có sku, cả cụm cũng có: không cần đánh số.  Có nước đi sang
    # Pending Review nên hook vẫn được gọi — để chuyển cột.
    def test_working_da_co_sku_ca_cum_du_ma_thi_khong_danh_so(self) -> None:
        a = _con("TASK-2", status="Working", meta="sku: OL_1_001\n")
        b = _con("TASK-3", status="Working", meta="sku: OL_1_002\n")
        root = _goc(a, b)

        self.assertEqual(0, cards_missing_sku(root))
        for con in (a, b):
            stage = self._stage(con, root)
            self.assertFalse(pipeline.needs_sku_fill(stage))
            self.assertEqual("Pending Review", pipeline.decide(stage).status)

    # 6. Thẻ sản phẩm (có cha, không ảnh máy) ở Working, chưa sku: gọi.
    def test_the_san_pham_o_working_chua_sku_thi_goi_hook(self) -> None:
        con = task_node("TASK-2", status="Working", parent_task="TASK-1", attachment_count=3)
        root = _goc(con)
        stage = self._stage(con, root)

        self.assertTrue(stage.is_product)
        self.assertTrue(pipeline.needs_sku_fill(stage))
        self.assertEqual(["TASK-2"], self._goi(root))

    # 7. Nguyên nhân thật vụ seller (c8 tìm ra): ERP cắt ``taskFull`` còn 60
    # nút, cả 60 ở Open.  Thẻ con Working thiếu sku nằm ngoài phần bị cắt
    # (``child_total`` 79 > 60 nút nhận được) — nó chỉ còn thấy được trên
    # ``taskBoard``.  Lượt quét vẫn phải gọi hook đánh số cho cụm, qua đúng
    # thẻ bị giấu đó.
    def test_cay_bi_cat_60_nut_van_danh_so(self) -> None:
        root = _cay_bi_cat()
        self.assertEqual(60, len(root["subtasks"]))
        self.assertGreater(root["child_total"], len(root["subtasks"]))
        bang = [_dong("TASK-1", "Working", parent="")]
        bang += [_dong(node["name"], "Open") for node in root["subtasks"]]
        bang.append(_dong("TASK-200", "Working"))
        client = _DemBang(["PROJ-1"], {"PROJ-1": bang}, {})

        goi = self._goi(root, client)

        self.assertTrue(
            goi,
            "cây bị cắt (79 con, nhận 60, cả 60 ở Open): thẻ Working thiếu sku nằm "
            "ngoài phần nhận được, nhưng pipeline_pass không gọi hook đánh số lần nào",
        )
        self.assertEqual(["TASK-200"], goi)
        self.assertEqual(["PROJ-1"], client.doc_bang)

    # 8. Cây không bị cắt thì không tốn request đọc bảng nào.
    def test_cay_khong_cat_thi_khong_doc_task_board(self) -> None:
        con = [_con(f"TASK-{i}", status="Open", comments=[comment(f"c{i}")]) for i in (2, 3, 4)]
        root = task_node("TASK-1", status="Working", project="PROJ-1", subtasks=con)
        self.assertEqual(3, root["child_total"])
        client = _DemBang(["PROJ-1"], {"PROJ-1": [_dong("TASK-200", "Working")]}, {})

        self.assertEqual([], self._goi(root, client))
        self.assertEqual([], client.doc_bang)

    # 9. Đọc taskBoard hỏng: ghi log, bỏ qua, lượt quét vẫn chạy nốt.
    def test_task_board_loi_thi_luot_quet_van_chay(self) -> None:
        root = _cay_bi_cat()
        # Một thẻ Open ảnh đã chốt: có nước đi sang Working, hook phải được gọi
        # cho nó dù bước đọc bảng phía sau hỏng.
        root["subtasks"][0] = _con("TASK-100", status="Open")
        client = _DemBang(["PROJ-1"], {}, {}, loi=AgentBotError("ERP trả 500"))
        bot = self._bot(client)

        with self.assertLogs("flow_web.agent_bot", level="WARNING") as nhat_ky:
            moves = asyncio.run(bot.pipeline_pass({"root": root}))

        self.assertEqual(["TASK-100"], [call.args[0] for call in bot.pipeline_hook.await_args_list])
        self.assertEqual(["TASK-100"], [item["task"] for item in moves])
        self.assertEqual(["PROJ-1"], client.doc_bang)
        self.assertTrue(any("ERP trả 500" in dong for dong in nhat_ky.output))

    # 10. Mỗi dự án đọc bảng tối đa một lần mỗi lượt quét, kể cả khi hai cây
    # cùng dự án đều bị cắt.
    def test_hai_cay_bi_cat_cung_du_an_chi_doc_bang_mot_lan(self) -> None:
        a, b = _cay_bi_cat("TASK-1", 100), _cay_bi_cat("TASK-2", 300)
        bang = [_dong("TASK-1", "Working", parent=""), _dong("TASK-2", "Working", parent="")]
        bang += [_dong("TASK-201", "Working", parent="TASK-1"), _dong("TASK-202", "Working", parent="TASK-2")]
        client = _DemBang(["PROJ-1"], {"PROJ-1": bang}, {})
        bot = self._bot(client)

        asyncio.run(bot.pipeline_pass({"root": a}))
        asyncio.run(bot.pipeline_pass({"root": b}))

        self.assertEqual(["TASK-201", "TASK-202"], [call.args[0] for call in bot.pipeline_hook.await_args_list])
        self.assertEqual(["PROJ-1"], client.doc_bang)

    # 11. Thẻ Working bị cắt đã có mã, hoặc thuộc cụm khác: không gọi.
    def test_cay_bi_cat_nhung_the_an_da_co_ma_hoac_cum_khac_thi_khong_goi(self) -> None:
        bang = [
            _dong("TASK-1", "Working", parent=""),
            _dong("TASK-200", "Working", sku="OL_1_001"),
            _dong("TASK-900", "Working", parent="TASK-9"),
        ]
        client = _DemBang(["PROJ-1"], {"PROJ-1": bang}, {})

        self.assertEqual([], self._goi(_cay_bi_cat(), client))
        self.assertEqual(["PROJ-1"], client.doc_bang)

    # 12. Chỉ đo, không assert: tên cột lạ đọc ra cột nào.
    def test_do_normalize_status_ten_cot_la(self) -> None:
        for ten in ("In Progress", "Doing", "Đang thực hiện", "WIP", "Working",
                    "Đang làm", "Pending Review", "Đang review"):
            print(f"  normalize_status({ten!r}) = {pipeline.normalize_status(ten)!r}")


if __name__ == "__main__":
    unittest.main()
