"""Bảng SKU với thẻ ngoài cây bị cắt, và lời nhắc "bảng SKU chưa có dòng" đã cũ.

Sau đợt 5, ``sku_status.json`` báo thẻ ngoài cây của cụm 04628 (vd 05245)
là ``reason: "cut"``, ``sku: ""``, dù trên ERP thẻ ấy có ``OR_1_084``.
Seller nhìn bảng tưởng bot không đánh mã. Dòng ``taskBoard`` bot đọc mỗi
lượt quét đã có ``custom_sku`` của mọi thẻ, nên bảng lấy mã từ đó. Thẻ không
có nguồn nào thì là "chưa đọc được", tách khỏi "thiếu mã".

Lời nhắc [AGENT_BOT_SKU] nằm mãi trên thẻ gốc: bảng mã đã có dòng thì bảng
không được nói "chưa có dòng" nữa.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

from flow_web import sku_board
from flow_web.sku import ProductBook
from flow_web.sku_board import build_sku, snapshot
from tests.test_agent_bot import BOT, FakeClient, build_bot, task_node
from tests.test_sku_board import ATTRS, FULL, NOW, ROOT, SKU_NOTE, FakeListing, card, node, task, tree

REPO = Path(__file__).resolve().parents[1]
KHAN_TAY = ATTRS.replace("product_type: khan tay", "product: khan tay")


def dong(name: str, status: str, parent: str = ROOT, sku: str = "", **extra: Any) -> Dict[str, Any]:
    """Một dòng ``taskBoard``: không kèm bình luận hay khối Thuộc tính, có ``custom_sku``."""
    row = {"name": name, "subject": f"Dòng {name}", "status": status, "parent_task": parent, "custom_sku": sku}
    row.update(extra)
    return row


def ve_bang(data: Dict[str, Any]) -> Dict[str, Any]:
    written = json.loads(json.dumps(data, ensure_ascii=False))
    return build_sku(FakeListing(written), now=NOW)


def cum_04628() -> Dict[str, Any]:
    """Cụm bị cắt: ba thẻ trong cây, hai thẻ chỉ có tên trong ``children``."""
    kids = [node(task(10001 + i), "Working", "sku: OR_1_%03d" % (1 + i)) for i in range(3)]
    thin = [{"name": k["name"], "subject": k["subject"], "status": k["status"]} for k in kids]
    thin += [
        {"name": task(5245), "subject": "Idea 5245", "status": "Working"},
        {"name": task(5246), "subject": "Idea 5246", "status": "Working"},
    ]
    return node(ROOT, "Working", FULL, subtasks=kids, children=thin, child_total=184)


class TheNgoaiCayCoMaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = [
            dong(ROOT, "Working", parent=""),
            # Trong ``children``, ngoài ``subtasks``: dòng bảng có mã.
            dong(task(5245), "Working", sku="OR_1_084"),
            # Không có cả trong ``children``: chỉ dòng bảng biết.
            dong(task(5300), "Pending Review", sku="OR_1_090"),
            # Thẻ cháu, cha cũng nằm ngoài cây.
            dong(task(5301), "Open", parent=task(5300)),
            # Thẻ cụm khác: không được lẫn vào.
            dong(task(9999), "Working", parent="TASK-2026-00202", sku="KT_1_001"),
        ]
        self.data = snapshot([tree(cum_04628(), truncated=True)], NOW, rows=self.rows)

    def test_the_ngoai_cay_mang_dung_ma_cua_dong_bang(self) -> None:
        the = card(self.data, task(5245))
        self.assertEqual(the["sku"], "OR_1_084")
        self.assertEqual(the["reason"], "")
        self.assertFalse(the["working_no_sku"])
        self.assertEqual(the["column"], "Đang làm")
        self.assertEqual(the["source"], "board")

    def test_the_chi_dong_bang_biet_cung_duoc_ve(self) -> None:
        self.assertEqual(card(self.data, task(5300))["sku"], "OR_1_090")
        chau = card(self.data, task(5301))
        self.assertEqual((chau["parent"], chau["reason"]), (task(5300), "todo"))
        self.assertNotIn(task(9999), {c["task"] for c in self.data["cards"]})

    def test_khong_tinh_la_thieu_ma(self) -> None:
        cluster = self.data["clusters"][0]
        self.assertEqual(self.data["totals"]["working_no_sku"], 0)
        # Chỉ 5301 (Cần làm) là chưa có mã; 5246 là "chưa đọc được".
        self.assertEqual(cluster["no_sku"], 1)
        self.assertEqual(cluster["unread"], 1)
        self.assertEqual(cluster["from_board"], 3)
        self.assertEqual(self.data["totals"]["unread"], 1)
        # Số của cây taskFull giữ nguyên: bot vẫn chỉ đọc được 3/184 qua cây.
        self.assertEqual((cluster["received"], cluster["total"]), (3, 184))

    def test_bang_giu_ma_va_noi_ro_nguon(self) -> None:
        shown = ve_bang(self.data)
        the = card(shown, task(5245))
        self.assertEqual((the["sku"], the["source"]), ("OR_1_084", "board"))
        self.assertEqual(shown["kpi"]["unread"], 1)
        self.assertEqual(shown["clusters"][0]["from_board"], 3)
        alert = next(a for a in shown["alerts"] if a["text"].startswith(f"Cụm {ROOT}"))
        self.assertIn("3 thẻ đọc mã từ dòng bảng", alert["text"])
        self.assertIn("1 thẻ chưa đọc được", alert["text"])

    def test_dong_bang_dang_lam_chua_ma_van_la_thieu_ma(self) -> None:
        # ``custom_sku`` là ô ERP giữ mã: trống ở Đang làm là thiếu mã thật.
        rows = [dong(task(5245), "Working")]
        the = card(snapshot([tree(cum_04628(), truncated=True)], NOW, rows=rows), task(5245))
        self.assertEqual((the["sku"], the["reason"]), ("", "wait"))
        self.assertTrue(the["working_no_sku"])

    def test_dong_bang_khong_co_thuoc_tinh_thi_khong_bao_thieu_account(self) -> None:
        # Dòng bảng không kèm khối Thuộc tính: không biết, không phải thiếu.
        root = node(ROOT, "Working", ATTRS, subtasks=[], children=[], child_total=1)
        the = card(snapshot([tree(root)], NOW, rows=[dong(task(5245), "Working", sku="OR_1_084")]), task(5245))
        self.assertEqual((the["account_state"], the["copysku_state"]), ("", ""))


class TheKhongNguonTests(unittest.TestCase):
    def test_the_khong_nguon_la_chua_doc_duoc_khong_phai_thieu_ma(self) -> None:
        kids = [node(task(20001 + i), "Working", "sku: KT_1_%03d" % i) for i in range(81)]
        thin = [{"name": k["name"], "subject": k["subject"], "status": k["status"]} for k in kids]
        root = node(ROOT, "Working", FULL, subtasks=kids[:59], children=thin)
        data = snapshot([tree(root)], NOW)

        cut = [c for c in data["cards"] if c["reason"] == "cut"]
        self.assertEqual(len(cut), 22)
        self.assertTrue(all("chưa đọc được" in c["why"] for c in cut))
        self.assertTrue(all(c["sku"] == "" and not c["working_no_sku"] for c in cut))
        cluster = data["clusters"][0]
        self.assertEqual((cluster["no_sku"], cluster["unread"], cluster["from_board"]), (0, 22, 0))
        self.assertEqual((data["totals"]["working_no_sku"], data["totals"]["unread"]), (0, 22))

        shown = ve_bang(data)
        self.assertEqual(shown["kpi"]["unread"], 22)
        self.assertEqual(shown["clusters"][0]["unread"], 22)

    def test_board_html_tach_hai_trang_thai(self) -> None:
        html = (REPO / "flow_web" / "static" / "board.html").read_text(encoding="utf-8")
        # Lọc "Chưa có SKU" không được gộp thẻ chưa đọc được vào.
        self.assertNotIn("['nosku', 'Chưa có SKU', (c) => !!c.reason]", html)
        self.assertIn("c.reason !== 'cut'", html)
        self.assertIn("Chưa đọc được", html)
        self.assertNotIn("'Bot chưa thấy'", html)
        # Mã lấy từ dòng bảng thì nói ra nguồn.
        self.assertIn("c.source === 'board'", html)
        self.assertIn("c.unread", html)


class LoiNhacCuTests(unittest.TestCase):
    """Bổ sung 11:58: lời nhắc cũ trong khi bảng mã đã có dòng."""

    def _cum(self, note: Dict[str, Any]) -> Dict[str, Any]:
        return tree(node(ROOT, "Working", KHAN_TAY, subtasks=[node(task(40030), "Working")], comments=[note]))

    def test_bang_ma_da_co_dong_thi_khong_con_thieu_dong(self) -> None:
        note = dict(SKU_NOTE, creation="2026-09-12 10:29:14")
        for kw in ("book", "book_rows"):
            with self.subTest(tham_so=kw):
                data = snapshot([self._cum(note)], NOW, **{kw: ProductBook.from_mapping({"khăn tay": "KT"})})
                self.assertEqual(data["clusters"][0]["unlisted"], [])
                self.assertEqual(card(data, task(40030))["reason"], "wait")

    def test_bang_ma_van_thieu_dong_thi_giu_book_kem_gio(self) -> None:
        note = dict(SKU_NOTE, creation="2026-09-12 10:29:14")
        data = snapshot([self._cum(note)], NOW, book_rows=ProductBook.from_mapping({"bờm": "BT"}))
        self.assertEqual(data["clusters"][0]["unlisted"], ["khăn tay"])
        the = card(data, task(40030))
        self.assertEqual(the["reason"], "book")
        self.assertEqual(the["why"], "bảng SKU chưa có dòng cho “khan tay” (bot ghi 10:29)")

    def test_bang_ma_tren_dia_khong_tu_them_ly_do_book(self) -> None:
        # Bảng trên đĩa thiếu dòng sheet đang có: nó chỉ được gỡ lời nhắc, không được tự nhắc.
        root = node(ROOT, "Working", KHAN_TAY, subtasks=[node(task(40031), "Working")])
        data = snapshot([tree(root)], NOW, book_rows=ProductBook.from_mapping({"bờm": "BT"}))
        self.assertEqual(card(data, task(40031))["reason"], "wait")

    def test_doc_bang_ma_tren_dia(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sku_book.json"
            self.assertIsNone(sku_board.load_disk_book(path))
            path.write_text(json.dumps({"entries": {"Embroidered Ornament": "OR"}}), encoding="utf-8")
            self.assertEqual(sku_board.load_disk_book(path).lookup("embroidered ornament"), ("OR", "book"))
            path.write_text(json.dumps({"khăn tay": "KT"}), encoding="utf-8")
            self.assertEqual(sku_board.load_disk_book(path).lookup("khan tay"), ("KT", "book"))
            path.write_text("{hỏng", encoding="utf-8")
            with self.assertLogs("flow_web.sku_board", level="WARNING"):
                self.assertIsNone(sku_board.load_disk_book(path))


class DemRequest(FakeClient):
    """``FakeClient`` ghi lại mọi lần gọi ERP."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.requests: List[str] = []

    def task_projects(self):
        self.requests.append("taskProjects")
        return super().task_projects()

    def board_snapshot(self, project: str):
        self.requests.append(f"taskBoard:{project}")
        return super().board_snapshot(project)

    def task_full(self, name: str, depth: int = 1):
        self.requests.append(f"taskFull:{name}")
        return super().task_full(name, depth)

    def add_comment(self, *args: Any, **kwargs: Any):
        self.requests.append("addTaskComment")
        return super().add_comment(*args, **kwargs)

    def delete_comment(self, *args: Any, **kwargs: Any):
        self.requests.append("deleteTaskComment")
        return super().delete_comment(*args, **kwargs)

    def add_task_agent(self, *args: Any, **kwargs: Any):
        self.requests.append("addTaskAgent")
        return super().add_task_agent(*args, **kwargs)


def luot_quet_gia() -> DemRequest:
    """Hai dự án. PROJ-1 có cụm bị cắt, ba thẻ ngoài cây có mã trên dòng bảng."""
    kids = [task_node(f"TASK-{i}", status="Open", parent_task="TASK-1") for i in range(10, 13)]
    root = task_node("TASK-1", agents=[BOT], status="Working", project="PROJ-1", subtasks=kids, child_total=6)
    board1 = [{"name": "TASK-1", "status": "Working", "agents": [{"bot_user": BOT}], "child_total": 6}]
    board1 += [{"name": k["name"], "status": "Open", "parent_task": "TASK-1", "custom_sku": ""} for k in kids]
    board1 += [
        {"name": f"TASK-{i}", "status": "Working", "parent_task": "TASK-1", "custom_sku": f"OR_1_{i:03d}"}
        for i in range(20, 23)
    ]
    other = task_node("TASK-9", agents=[BOT], status="Working", project="PROJ-2")
    board2 = [{"name": "TASK-9", "status": "Working", "agents": [{"bot_user": BOT}], "child_total": 0}]
    return DemRequest(
        ["PROJ-1", "PROJ-2"],
        {"PROJ-1": board1, "PROJ-2": board2},
        {"TASK-1": {"root": root}, "TASK-9": {"root": other}},
    )


class BotGhiBangSkuTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.target = self.tmp / "downloads" / sku_board.SKU_STATUS_FILE
        env = mock.patch.dict(os.environ, {"ERP_SKU_STATUS_FILE": str(self.target)})
        env.start()
        self.addCleanup(env.stop)

    def _bot(self, client: DemRequest, folder: str):
        (self.tmp / folder).mkdir(exist_ok=True)
        return build_bot(client, self.tmp / folder, autorun=False)

    def _quet(self, client: DemRequest, **attrs: Any) -> Dict[str, Any]:
        bot = self._bot(client, "quet")
        for key, value in attrs.items():
            setattr(bot, key, value)
        asyncio.run(bot.run_once())
        return json.loads(self.target.read_text(encoding="utf-8"))

    def test_mot_luot_quet_ve_ma_the_ngoai_cay_khong_them_request(self) -> None:
        # Số cũ: cùng lượt quét mà không ghi tệp bảng.
        goc = luot_quet_gia()
        with mock.patch.object(sku_board, "write_status", return_value=True):
            asyncio.run(self._bot(goc, "goc").run_once())

        client = luot_quet_gia()
        data = self._quet(client)

        self.assertEqual({card(data, f"TASK-{i}")["sku"] for i in range(20, 23)},
                         {"OR_1_020", "OR_1_021", "OR_1_022"})
        self.assertEqual(data["totals"]["working_no_sku"], 0)
        # Trần theo brief: số cũ + số dự án. Bảng đã đọc sẵn nên thật ra là +0.
        self.assertLessEqual(len(client.requests), len(goc.requests) + 2)
        self.assertEqual(sorted(client.requests), sorted(goc.requests))

    def test_doc_bang_toi_da_mot_lan_moi_du_an(self) -> None:
        client = luot_quet_gia()
        bot = self._bot(client, "rong")
        cut = client.task_full("TASK-1")
        whole = client.task_full("TASK-9")
        client.requests.clear()
        # Lượt quét chưa đọc bảng (cache rỗng): hai cây cắt cùng dự án, một cây nguyên.
        rows = bot._sku_board_rows([cut, dict(cut), whole])
        self.assertEqual(client.requests, ["taskBoard:PROJ-1"])
        self.assertIn("TASK-20", {row["name"] for row in rows})
        self.assertEqual(len(rows), len({row["name"] for row in rows}))

    def test_bot_go_loi_nhac_cu_khi_bang_ma_da_co_dong(self) -> None:
        kid = task_node("TASK-2", status="Working", parent_task="TASK-1")
        note = dict(SKU_NOTE, creation="2026-09-12 10:29:14")
        root = task_node("TASK-1", agents=[BOT], status="Working", project="PROJ-1",
                         subtasks=[kid], comments=[note], meta=KHAN_TAY)
        client = DemRequest(
            ["PROJ-1"],
            {"PROJ-1": [{"name": "TASK-1", "status": "Working", "agents": [{"bot_user": BOT}], "child_total": 1}]},
            {"TASK-1": {"root": root}},
        )
        data = self._quet(client, sku_book_loader=lambda: ProductBook.from_mapping({"khăn tay": "KT"}))
        self.assertEqual(data["clusters"][0]["unlisted"], [])
        self.assertEqual(card(data, "TASK-2")["reason"], "wait")


if __name__ == "__main__":
    unittest.main()
