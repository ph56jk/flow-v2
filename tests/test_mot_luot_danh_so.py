"""Mỗi lượt quét, mỗi cây chỉ gọi đánh số một lần.

Hook đánh số của app (``advance_erp_pipeline``) đánh **cả cụm** từ thẻ gốc.
Lần gọi đầu đã đánh xong, những lần sau chỉ đọc lại cây mà không ghi gì.
Mỗi lần tốn ít nhất năm request.  Cụm 37 thẻ vừa kéo sang *Đang làm* thành
khoảng 200 request một lượt, token bot chỉ có 60 mỗi phút: bị 429, lượt quét
kéo dài, thẻ chờ ~35 phút mới có mã.  Seller cần mã trong 5 phút.

Luật mới: thẻ chỉ chờ mã (không có nước đi, đang chờ máy điền mã) thì mỗi
cây gọi hook tới khi có **một** lần thành công.  Thẻ có nước đi thật vẫn
gọi như cũ.  Không nhớ qua lượt.

Hook thật không ném lỗi: ``advance_erp_pipeline`` bắt mọi lỗi rồi trả
``{task_id, moved: False, sku: {}, reason}``.  Chỉ đường thành công mới có
``root_task_id``, nên đó là dấu thành công.  Mỗi cây mỗi lượt hỏng tối đa
ba lần, để hỏng vì 429 không biến thành bão request qua cả cụm.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from flow_web.agent_bot import AgentBot
from tests.test_agent_bot import FakeClient, build_bot, comment, task_node


def cho_ma(name: str) -> Dict[str, Any]:
    """Thẻ con sản phẩm đã kéo sang *Đang làm*, chưa có mã: chỉ chờ máy."""
    return task_node(name, status="Working", parent_task="TASK-1", attachment_count=3)


def co_nuoc_di(name: str) -> Dict[str, Any]:
    """Thẻ ảnh đã duyệt, đã có mã: nước đi thật sang *Đang review*."""
    return task_node(
        name, status="Working", parent_task="TASK-1",
        meta="sku: KT_1_002\n", comments=[comment(f"c-{name}", like=1)],
    )


def cay(*kids: Dict[str, Any]) -> Dict[str, Any]:
    return {"root": task_node("TASK-1", status="Open", subtasks=list(kids))}


def thanh_cong(task_id: str) -> Dict[str, Any]:
    """Dạng trả về của ``advance_erp_pipeline`` khi chạy trót lọt."""
    return {"task_id": task_id, "root_task_id": "TASK-1", "moved": task_id.startswith("TASK-2"), "sku": {}}


def that_bai(task_id: str) -> Dict[str, Any]:
    """Dạng trả về của ``advance_erp_pipeline`` khi hỏng: không ném, không có gốc."""
    return {"task_id": task_id, "moved": False, "sku": {}, "reason": "ERP HTTP 403: không có quyền"}


def ghi_ma_hong(task_id: str) -> Dict[str, Any]:
    """Chạy trót lọt nhưng ghi mã hỏng một thẻ: vẫn có gốc, lỗi nằm ở ``sku.failed``."""
    return {
        "task_id": task_id, "root_task_id": "TASK-1", "moved": False,
        "sku": {"failed": [{"task_id": "TASK-11", "sku": "", "error": "429"}]},
    }


class MotLuotDanhSoTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.asked: List[str] = []
        self.hong: set[str] = set()  # hook ném lỗi
        self.tra_hong: set[str] = set()  # hook trả dạng lỗi thật, không ném
        self.ghi_hong: set[str] = set()  # hook chạy trót lọt nhưng ghi mã hỏng vài thẻ

    def _bot(self) -> AgentBot:
        async def hook(task_id: str) -> Dict[str, Any]:
            self.asked.append(task_id)
            if task_id in self.hong:
                raise RuntimeError("ERP trả 429")
            if task_id in self.tra_hong:
                return that_bai(task_id)
            if task_id in self.ghi_hong:
                return ghi_ma_hong(task_id)
            return thanh_cong(task_id)

        bot = build_bot(FakeClient([], {}, {}), Path(self._tmp.name))
        bot.pipeline_hook = hook
        return bot

    def _run(self, bot: AgentBot, tree: Dict[str, Any]) -> List[Dict[str, Any]]:
        return asyncio.run(bot.pipeline_pass(tree))

    def test_nam_the_cho_ma_chi_goi_hook_mot_lan(self):
        tree = cay(*(cho_ma(f"TASK-1{i}") for i in range(1, 6)))

        moves = self._run(self._bot(), tree)

        self.assertEqual(["TASK-11"], self.asked, "hook đánh cả cụm, gọi lần hai là phí request")
        self.assertEqual([{"task": "TASK-11", "result": thanh_cong("TASK-11")}], moves)

    def test_lan_dau_nem_loi_thi_the_ke_duoc_thu(self):
        self.hong = {"TASK-11"}
        tree = cay(*(cho_ma(f"TASK-1{i}") for i in range(1, 6)))

        moves = self._run(self._bot(), tree)

        self.assertEqual(["TASK-11", "TASK-12"], self.asked)
        self.assertEqual("ERP trả 429", moves[0]["error"])
        self.assertEqual(thanh_cong("TASK-12"), moves[1]["result"])

    def test_hong_ca_thi_thu_het(self):
        # Chưa lần nào ghi được thì chưa có gì chắc là cụm đã có mã.
        self.hong = {f"TASK-1{i}" for i in range(1, 4)}
        tree = cay(*(cho_ma(f"TASK-1{i}") for i in range(1, 4)))

        moves = self._run(self._bot(), tree)

        self.assertEqual(["TASK-11", "TASK-12", "TASK-13"], self.asked)
        self.assertEqual(3, sum(1 for item in moves if "error" in item))

    def test_the_co_nuoc_di_that_van_duoc_goi(self):
        tree = cay(cho_ma("TASK-11"), cho_ma("TASK-12"), cho_ma("TASK-13"), co_nuoc_di("TASK-21"))

        moves = self._run(self._bot(), tree)

        self.assertEqual(["TASK-11", "TASK-21"], self.asked)
        self.assertEqual(thanh_cong("TASK-21"), moves[-1]["result"])

    def test_goc_tam_dung_thi_khong_goi(self):
        bot = self._bot()
        bot.state.pause("TASK-1")

        self.assertEqual([], self._run(bot, cay(*(cho_ma(f"TASK-1{i}") for i in range(1, 6)))))
        self.assertEqual([], self.asked)

    def test_khong_nho_qua_luot(self):
        # Lượt sau phải thử lại: lượt trước có thể ghi hỏng giữa chừng.
        bot = self._bot()
        tree = cay(*(cho_ma(f"TASK-1{i}") for i in range(1, 4)))

        self._run(bot, tree)
        self._run(bot, tree)

        self.assertEqual(["TASK-11", "TASK-11"], self.asked)

    def test_hook_tra_dang_loi_that_thi_the_ke_duoc_thu(self):
        # Hook thật không ném: nó trả ``reason`` mà không có ``root_task_id``.
        self.tra_hong = {"TASK-11"}
        tree = cay(*(cho_ma(f"TASK-1{i}") for i in range(1, 6)))

        moves = self._run(self._bot(), tree)

        self.assertEqual(["TASK-11", "TASK-12"], self.asked, "chỉ lần có root_task_id mới tính là đã đánh số")
        self.assertEqual(that_bai("TASK-11"), moves[0]["result"])
        self.assertEqual(thanh_cong("TASK-12"), moves[1]["result"])

    def test_the_dau_luon_hong_khong_lam_cay_chet_doi(self):
        # Thẻ đầu hỏng vì lý do riêng (403, ngoài dự án).  Cây luôn đi cùng
        # thứ tự, nên lượt nào nó cũng được gọi đầu; thẻ anh em vẫn phải có lượt.
        self.tra_hong = {"TASK-11"}
        bot = self._bot()
        tree = cay(*(cho_ma(f"TASK-1{i}") for i in range(1, 6)))

        self._run(bot, tree)
        self._run(bot, tree)

        self.assertEqual(["TASK-11", "TASK-12", "TASK-11", "TASK-12"], self.asked)

    def test_hong_toi_lan_thu_ba_thi_thoi(self):
        # Hỏng vì 429 mà thử hết cả cụm là lại bão request.
        for kieu in ("tra_hong", "hong"):
            with self.subTest(kieu=kieu):
                self.asked = []
                self.hong, self.tra_hong = set(), set()
                setattr(self, kieu, {f"TASK-1{i}" for i in range(1, 6)})
                tree = cay(*(cho_ma(f"TASK-1{i}") for i in range(1, 6)))

                self._run(self._bot(), tree)

                self.assertEqual(["TASK-11", "TASK-12", "TASK-13"], self.asked)

    def test_het_luot_hong_van_goi_the_co_nuoc_di(self):
        self.tra_hong = {f"TASK-1{i}" for i in range(1, 6)}
        tree = cay(*(cho_ma(f"TASK-1{i}") for i in range(1, 6)), co_nuoc_di("TASK-21"))

        self._run(self._bot(), tree)

        self.assertEqual(["TASK-11", "TASK-12", "TASK-13", "TASK-21"], self.asked)

    def test_sku_failed_van_la_thanh_cong(self):
        # Sync đã đi qua mọi thẻ trong kế hoạch.  Gọi lại ngay giữa lúc 429
        # chỉ làm bão thêm; lượt sau (120 giây) thử lại thẻ còn thiếu mã.
        self.ghi_hong = {f"TASK-1{i}" for i in range(1, 6)}
        bot = self._bot()
        tree = cay(*(cho_ma(f"TASK-1{i}") for i in range(1, 6)))

        moves = self._run(bot, tree)

        self.assertEqual(["TASK-11"], self.asked, "sku.failed không cộng vào trần, không gọi thẻ kế")
        self.assertEqual([{"task": "TASK-11", "result": ghi_ma_hong("TASK-11")}], moves)

        self._run(bot, tree)

        self.assertEqual(["TASK-11", "TASK-11"], self.asked, "lượt sau thử lại đúng một lần")


if __name__ == "__main__":
    unittest.main()
