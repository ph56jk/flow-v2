"""Phần "SKU & Thuộc tính" của bảng điều khiển: flow_web/sku_board.py.

Bot đọc cây rồi ghi tệp, bảng đọc tệp. Test giữ hai lời hứa: số trên bảng
đúng với cây bot đã đọc, và tệp hỏng hay chưa có thì bảng vẫn mở được.
"""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

from flow_web import sku_board
from flow_web.board import BoardServer
from flow_web.listing_board import Checks
from flow_web.sku_board import SKU_STATUS_FILE, build_sku, snapshot, status_path, write_status
from tests.test_board import FakeListing as BoardListing, read_events, sse

NOW = datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc)
ROOT = "TASK-2026-04628"
REPO = Path(__file__).resolve().parents[1]

ATTRS = "\n".join([
    "product_type: khan tay",
    "product_group: vai",
    "fulfillment: tu lam",
    "sales_channel: etsy",
    "content: Khăn tay thêu tên",
])
FULL = ATTRS + "\naccount: acc07\ncopysku: KT_1_001"


def task(n: int) -> str:
    return f"TASK-2026-{n:05d}"


def node(name: str, status: str = "Open", meta: str = "", *, subtasks: List[Dict[str, Any]] = (),
         children: Optional[List[Dict[str, Any]]] = None, comments: List[Dict[str, Any]] = (),
         meta_auto: str = "", **extra: Any) -> Dict[str, Any]:
    """Một node dựng theo đúng hình ``taskFull`` trả về."""
    data: Dict[str, Any] = {
        "name": name,
        "subject": f"Thẻ {name}",
        "status": status,
        "project": "PROJ-0170",
        "project_name": "Bảng Etsy 1",
        "meta": meta,
        "meta_auto": meta_auto,
        "subtasks": list(subtasks),
        "comments": list(comments),
    }
    data["children"] = (
        [{"name": s["name"], "subject": s["subject"], "status": s["status"]} for s in data["subtasks"]]
        if children is None else children
    )
    data["child_total"] = len(data["children"])
    data.update(extra)
    return data


def tree(root: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    info = {"root": root, "truncated": False, "node_count": 1 + len(root["subtasks"]), "max_nodes": 60}
    info.update(extra)
    return info


def review_image(name: str) -> Dict[str, Any]:
    """Ảnh bot đăng chờ 👍/👎, chưa ai bấm."""
    return {
        "name": name, "owner": "agent-kin-test-agent@bots.hvg.internal", "is_bot": 1, "mine": 1,
        "content": "[FLOW_V2_REVIEW job#0] Ảnh 1/2 chờ duyệt", "meta": "",
        "like_count": 0, "dislike_count": 0, "my_vote": "",
        "attachments": [{"file_name": f"{name}.png"}], "replies": [],
    }


SKU_NOTE = {
    "name": "c-sku", "is_bot": 1, "mine": 1, "meta": "[AGENT_BOT_SKU]",
    "content": "Chưa có mã trong bảng SKU cho “khăn tay”, nên bot để trống mã các thẻ của món này.",
    "attachments": [], "replies": [],
}


def card(data: Dict[str, Any], name: str) -> Dict[str, Any]:
    return next(c for c in data["cards"] if c["task"] == name)


class FakeListing:
    """Bản Listing giả: chỉ có lối đọc tệp ``/files/downloads``."""

    base = "http://listing.test"

    def __init__(self, value: Any = None, error: Optional[BaseException] = None) -> None:
        self.value, self.error, self.asked = value, error, []

    def lister_status(self, name: str) -> Any:
        self.asked.append(name)
        if self.error:
            raise self.error
        return self.value


def board(trees: List[Dict[str, Any]], *, later: int = 60, every: int = 120) -> Dict[str, Any]:
    """Bot ghi tệp lúc NOW, bảng đọc sau ``later`` giây."""
    written = json.loads(json.dumps(snapshot(trees, NOW, every=every), ensure_ascii=False))
    return build_sku(FakeListing(written), now=NOW + timedelta(seconds=later))


class TruncatedClusterTest(unittest.TestCase):
    def test_cluster_of_159_that_bot_read_60(self) -> None:
        # Đúng cảnh TASK-2026-04628: ERP đếm 159 con, trả 60 node, cả 60 ở Open.
        kids = [node(task(10001 + i), "Open") for i in range(60)]
        root = node(ROOT, "Working", FULL, subtasks=kids, child_total=159)
        data = snapshot([tree(root, truncated=True, node_count=60)], NOW)

        cluster = data["clusters"][0]
        self.assertEqual((cluster["received"], cluster["total"], cluster["unseen"]), (60, 159, 99))
        self.assertTrue(cluster["truncated"])
        self.assertEqual(cluster["columns"], [{"status": "Open", "name": "Cần làm", "n": 60}])
        self.assertEqual(data["totals"]["truncated"], 1)
        self.assertEqual(data["totals"]["unseen"], 99)
        self.assertEqual(len(data["cards"]), 60)
        self.assertEqual({c["reason"] for c in data["cards"]}, {"todo"})

        shown = board([tree(root, truncated=True, node_count=60)])
        first = shown["alerts"][0]
        self.assertEqual(first["tone"], "bad")
        self.assertEqual(first["text"], f"Cụm {ROOT}: bot chỉ đọc được 60/159 thẻ.")
        self.assertEqual(first["link"], "https://erp.havigroup.llc/app/task/" + ROOT)
        self.assertEqual(shown["kpi"]["truncated"], 1)

    def test_children_complete_but_subtasks_cut(self) -> None:
        # ``children`` đủ 81, ``subtasks`` chỉ 59: 22 thẻ bot có tên mà không có meta.
        kids = [node(task(20001 + i), "Working", "sku: KT_1_%03d" % i) for i in range(81)]
        thin = [{"name": k["name"], "subject": k["subject"], "status": k["status"]} for k in kids]
        root = node(ROOT, "Working", FULL, subtasks=kids[:59], children=thin)
        data = snapshot([tree(root)], NOW)

        cluster = data["clusters"][0]
        self.assertEqual((cluster["received"], cluster["total"], cluster["unseen"]), (59, 81, 22))
        self.assertTrue(cluster["truncated"])
        cut = [c for c in data["cards"] if c["reason"] == "cut"]
        self.assertEqual(len(cut), 22)
        self.assertEqual({c["task"] for c in cut}, {k["name"] for k in kids[59:]})
        self.assertTrue(all(not c["seen"] and c["column"] == "Đang làm" for c in cut))
        # Thẻ bot chưa thấy không bị tính là "Đang làm chưa có SKU": bot không biết.
        self.assertEqual(data["totals"]["working_no_sku"], 0)

    def test_node_limit_alone_marks_cluster_cut(self) -> None:
        root = node(ROOT, "Working", FULL, subtasks=[node(task(30001), "Open")])
        data = snapshot([tree(root, node_count=60, max_nodes=60)], NOW)
        self.assertTrue(data["clusters"][0]["truncated"])
        self.assertEqual(data["clusters"][0]["unseen"], 0)
        shown = board([tree(root, node_count=60, max_nodes=60)])
        self.assertIn(f"Cụm {ROOT}: ERP cắt cây ở 60 node", shown["alerts"][0]["text"])

    def test_whole_tree_is_not_cut(self) -> None:
        root = node(ROOT, "Working", FULL, subtasks=[node(task(30002), "Working", "sku: KT_1_001")])
        data = snapshot([tree(root)], NOW)
        self.assertFalse(data["clusters"][0]["truncated"])
        self.assertEqual(board([tree(root)])["alerts"], [])


class MissingSkuTest(unittest.TestCase):
    def test_working_card_without_sku(self) -> None:
        kids = [
            node(task(40001), "Working"),
            node(task(40002), "Working", "sku: KT_1_002"),
            node(task(40003), "Pending Review"),
        ]
        root = node(ROOT, "Working", FULL, subtasks=kids)
        data = snapshot([tree(root)], NOW)

        stuck = card(data, task(40001))
        self.assertEqual(stuck["reason"], "wait")
        self.assertTrue(stuck["working_no_sku"])
        self.assertEqual(stuck["column"], "Đang làm")
        self.assertEqual(card(data, task(40002))["sku"], "KT_1_002")
        self.assertEqual(card(data, task(40002))["reason"], "")
        self.assertTrue(card(data, task(40003))["working_no_sku"])
        self.assertEqual(data["totals"]["working_no_sku"], 2)
        self.assertEqual(data["clusters"][0]["working_no_sku"], 2)
        # Thẻ kẹt đứng đầu bảng.
        self.assertEqual([c["task"] for c in data["cards"][:2]], [task(40001), task(40003)])

        alerts = board([tree(root)])["alerts"]
        self.assertIn({"tone": "bad", "text": "2 thẻ ở Đang làm chưa có SKU (tính cả 1 thẻ đã sang cột sau).",
                       "link": "https://erp.havigroup.llc/app/task/" + ROOT}, alerts)

    def test_open_card_waits_for_its_column_not_for_the_bot(self) -> None:
        root = node(ROOT, "Working", FULL, subtasks=[node(task(40010), "Open")])
        data = snapshot([tree(root)], NOW)
        self.assertEqual(card(data, task(40010))["reason"], "todo")
        self.assertIn("chưa sang Đang làm", card(data, task(40010))["why"])
        self.assertFalse(card(data, task(40010))["working_no_sku"])

    def test_pending_images_reason(self) -> None:
        kid = node(task(40020), "Open", comments=[review_image("c1"), review_image("c2")])
        data = snapshot([tree(node(ROOT, "Working", FULL, subtasks=[kid]))], NOW)
        self.assertEqual(card(data, task(40020))["reason"], "images")
        self.assertEqual(card(data, task(40020))["why"], "còn 2 ảnh chờ duyệt")

    def test_sku_note_on_parent_means_book_has_no_row(self) -> None:
        # service.py để lời nhắc trên thẻ cha; thẻ cha ghi không dấu, lời nhắc có dấu.
        meta = ATTRS.replace("product_type: khan tay", "product: khan tay")
        root = node(ROOT, "Working", meta, subtasks=[node(task(40030), "Working")], comments=[SKU_NOTE])
        data = snapshot([tree(root)], NOW)
        self.assertEqual(card(data, task(40030))["reason"], "book")
        self.assertEqual(card(data, task(40030))["why"], "bảng SKU chưa có dòng cho “khan tay”")
        self.assertEqual(data["clusters"][0]["unlisted"], ["khăn tay"])

    def test_stale_note_comes_after_every_surer_reason(self) -> None:
        # (a) Lời nhắc "bảng SKU chưa có dòng" nằm mãi trên thẻ gốc, cũ đi được.
        # Nó chỉ là lý do khi không còn lý do nào chắc hơn.
        meta = ATTRS.replace("product_type: khan tay", "product: khan tay")
        note = dict(SKU_NOTE, creation="2026-09-12 10:29:14.123")
        kids = [
            node(task(40070), "Working", "sku: KT_1_070"),
            node(task(40071), "Open"),
            node(task(40072), "Open", comments=[review_image("c1")]),
            node(task(40073), "Working"),
        ]
        hidden = {"name": task(40074), "subject": "Idea 74", "status": "Working"}
        thin = [{"name": k["name"], "subject": k["subject"], "status": k["status"]} for k in kids] + [hidden]
        root = node(ROOT, "Working", meta, subtasks=kids, children=thin, comments=[note])
        data = snapshot([tree(root)], NOW)
        self.assertEqual([card(data, task(n))["reason"] for n in range(40070, 40075)],
                         ["", "todo", "images", "book", "cut"])

    def test_note_on_04628_does_not_blame_the_book_for_open_cards(self) -> None:
        # (a) Cảnh thật 12/09: lời nhắc lúc 10:29, 10:29:14 bảng đã có dòng.
        # 60 thẻ bot đọc được đều ở Cần làm: lý do là cột, không phải bảng SKU.
        kids = [node(task(10001 + i), "Open") for i in range(60)]
        note = dict(SKU_NOTE, creation="2026-09-12 10:29:00")
        root = node(ROOT, "Working", FULL, subtasks=kids, child_total=159, comments=[note])
        data = snapshot([tree(root, truncated=True, node_count=60)], NOW)
        self.assertEqual({c["reason"] for c in data["cards"]}, {"todo"})
        self.assertEqual(data["clusters"][0]["unlisted"], ["khăn tay"])

    def test_book_reason_says_when_the_bot_wrote_the_note(self) -> None:
        # (b) Lý do kèm giờ bot ghi, để người xem tự thấy lời nhắc cũ chưa.
        # ERP trả giờ không đuôi múi, theo giờ VN. Lời nhắc mới nhất thắng.
        meta = ATTRS.replace("product_type: khan tay", "product: khan tay")
        older = dict(SKU_NOTE, name="c-sku-1", creation="2026-09-12 09:05:00")
        newer = dict(SKU_NOTE, name="c-sku-2", creation="2026-09-12 10:29:14.123")
        root = node(ROOT, "Working", meta, subtasks=[node(task(40080), "Working")], comments=[newer, older])
        stuck = card(snapshot([tree(root)], NOW), task(40080))
        self.assertEqual(stuck["why"], "bảng SKU chưa có dòng cho “khan tay” (bot ghi 10:29)")
        self.assertEqual(stuck["note_at"], "2026-09-12T03:29:14+00:00")
        # Bảng đọc lại từ tệp vẫn giữ nguyên.
        shown = card(board([tree(root)]), task(40080))
        self.assertEqual((shown["why"], shown["note_at"]), (stuck["why"], stuck["note_at"]))

        # Lời nhắc hôm trước thì ghi cả ngày.
        yesterday = dict(SKU_NOTE, creation="2026-09-11 10:29:00")
        root = node(ROOT, "Working", meta, subtasks=[node(task(40081), "Working")], comments=[yesterday])
        self.assertEqual(card(snapshot([tree(root)], NOW), task(40081))["why"],
                         "bảng SKU chưa có dòng cho “khan tay” (bot ghi 11/09 10:29)")

        # Bình luận không có giờ thì không in giờ, không đoán.
        root = node(ROOT, "Working", meta, subtasks=[node(task(40082), "Working")], comments=[SKU_NOTE])
        bare = card(snapshot([tree(root)], NOW), task(40082))
        self.assertEqual((bare["why"], bare["note_at"]), ("bảng SKU chưa có dòng cho “khan tay”", ""))

    def test_note_is_not_called_stale_without_a_sku_time(self) -> None:
        # (c) chưa làm: cây không ghi thẻ nhận mã lúc nào. Node không có giờ
        # đánh mã, bot cũng không để bình luận khi đánh mã. Thẻ anh em đã có mã
        # chưa đủ để nói lời nhắc cũ: mã ấy có thể có trước lời nhắc. Lý do vẫn
        # là "book", kèm giờ để người xem tự so.
        meta = ATTRS.replace("product_type: khan tay", "product: khan tay")
        note = dict(SKU_NOTE, creation="2026-09-12 10:29:14")
        kids = [node(task(40090), "Working", "sku: KT_1_082"), node(task(40091), "Working")]
        root = node(ROOT, "Working", meta, subtasks=kids, comments=[note])
        stuck = card(snapshot([tree(root)], NOW), task(40091))
        self.assertEqual(stuck["reason"], "book")
        self.assertTrue(stuck["why"].endswith("(bot ghi 10:29)"))

    def test_book_passed_by_the_bot(self) -> None:
        class Book:
            def __init__(self, source: str) -> None:
                self.source = source

            def lookup(self, product: str) -> tuple:
                return "KT", self.source

        root = node(ROOT, "Working", FULL, subtasks=[node(task(40040), "Working")])
        guessed = snapshot([tree(root)], NOW, book=Book("initials"))
        self.assertEqual(card(guessed, task(40040))["reason"], "book")
        listed = snapshot([tree(root)], NOW, book=Book("book"))
        self.assertEqual(card(listed, task(40040))["reason"], "wait")

    def test_card_without_product_anywhere(self) -> None:
        meta = ATTRS.replace("product_type: khan tay\n", "")
        root = node(ROOT, "Working", meta, subtasks=[node(task(40050), "Working")])
        data = snapshot([tree(root)], NOW)
        self.assertEqual(card(data, task(40050))["reason"], "product")
        self.assertEqual(data["clusters"][0]["missing"], ["product_type"])

    def test_cancelled_card_is_not_a_problem(self) -> None:
        root = node(ROOT, "Working", ATTRS, subtasks=[node(task(40060), "Cancelled")])
        data = snapshot([tree(root)], NOW)
        cancelled = card(data, task(40060))
        self.assertEqual((cancelled["reason"], cancelled["working_no_sku"]), ("", False))
        self.assertEqual((cancelled["account_state"], cancelled["copysku_state"]), ("", ""))
        self.assertEqual(data["totals"]["missing_account"], 0)


class AttributesTest(unittest.TestCase):
    def test_parent_missing_attributes(self) -> None:
        meta = "product: khan tay\nfulfillment: tu lam\ncontent: Khăn tay thêu tên"
        root = node(ROOT, "Working", meta, subtasks=[node(task(50001), "Open")])
        data = snapshot([tree(root)], NOW)

        cluster = data["clusters"][0]
        self.assertEqual(cluster["missing"], ["product_group", "sales_channel"])
        # ``product`` là một tên gọi khác của product_type: việc đánh số đọc được thì không thiếu.
        self.assertEqual(cluster["attributes"]["product_type"], "khan tay")
        self.assertEqual(cluster["content"], "Khăn tay thêu tên")
        self.assertEqual((cluster["board"], cluster["project"]), ("Bảng Etsy 1", "PROJ-0170"))
        self.assertEqual(data["totals"]["missing_attrs"], 1)

        alerts = board([tree(root)])["alerts"]
        self.assertIn({"tone": "warn", "text": f"1 cụm thiếu thuộc tính: {ROOT} (product_group, sales_channel).",
                       "link": "https://erp.havigroup.llc/app/task/" + ROOT}, alerts)

    def test_content_is_shown_but_not_required(self) -> None:
        root = node(ROOT, "Working", ATTRS.replace("\ncontent: Khăn tay thêu tên", ""))
        data = snapshot([tree(root)], NOW)
        self.assertEqual(data["clusters"][0]["missing"], [])
        self.assertEqual(data["clusters"][0]["content"], "")


class AccountTest(unittest.TestCase):
    def test_card_missing_account(self) -> None:
        kids = [
            node(task(60001), "Working", "sku: KT_1_001\naccount: acc07\ncopysku: KT_1_000"),
            node(task(60002), "Working", "sku: KT_1_002"),
        ]
        root = node(ROOT, "Working", ATTRS, subtasks=kids)
        data = snapshot([tree(root)], NOW)

        self.assertEqual((card(data, task(60001))["account_state"], card(data, task(60001))["account"]), ("ok", "acc07"))
        self.assertEqual(card(data, task(60002))["account_state"], "missing")
        self.assertEqual(card(data, task(60002))["copysku_state"], "missing")
        self.assertEqual((data["totals"]["missing_account"], data["totals"]["missing_copysku"]), (1, 1))

        alerts = board([tree(root)])["alerts"]
        self.assertIn({"tone": "warn", "text": "1 thẻ thiếu account: thẻ con và thẻ cha đều chưa khai.", "link": ""}, alerts)

    def test_parent_account_is_inherited(self) -> None:
        root = node(ROOT, "Working", FULL, subtasks=[node(task(60010), "Working", "sku: KT_1_010")])
        data = snapshot([tree(root)], NOW)
        kid = card(data, task(60010))
        self.assertEqual((kid["account_state"], kid["account"]), ("inherit", "acc07"))
        self.assertEqual((kid["copysku_state"], kid["copysku"]), ("inherit", "KT_1_001"))
        self.assertEqual(data["totals"]["missing_account"], 0)

    def test_account_label_on_parent(self) -> None:
        root = node(ROOT, "Working", ATTRS, meta_auto="_labels: acc07",
                    subtasks=[node(task(60020), "Working", "sku: KT_1_020")])
        data = snapshot([tree(root)], NOW)
        self.assertEqual(card(data, task(60020))["account_state"], "inherit")
        self.assertEqual(card(data, task(60020))["account"], "acc07")

    def test_done_label(self) -> None:
        kids = [node(task(60030), "Completed", "sku: KT_1_030", meta_auto="_labels: DONE"),
                node(task(60031), "Completed", "sku: KT_1_031")]
        data = snapshot([tree(node(ROOT, "Working", FULL, subtasks=kids))], NOW)
        self.assertTrue(card(data, task(60030))["done"])
        self.assertFalse(card(data, task(60031))["done"])
        self.assertEqual(data["totals"]["done"], 1)


class SnapshotShapeTest(unittest.TestCase):
    def test_nested_cards_and_duplicate_clusters(self) -> None:
        grandchild = node(task(70003), "Working")
        kid = node(task(70002), "Working", "sku: KT_1_002", subtasks=[grandchild])
        root = node(ROOT, "Working", FULL, subtasks=[kid])
        data = snapshot([tree(root), tree(root), {"root": {}}, "rác"], NOW, every=90)
        self.assertEqual(len(data["clusters"]), 1)
        self.assertEqual({c["task"] for c in data["cards"]}, {task(70002), task(70003)})
        self.assertEqual(card(data, task(70003))["parent"], task(70002))
        self.assertEqual(data["every"], 90)
        self.assertEqual(data["at"], "2026-09-12T08:00:00+00:00")
        json.dumps(data)  # ghi được ra tệp

    def test_board_process_does_not_load_the_bot(self) -> None:
        code = "import sys, flow_web.board; print('flow_web.agent_bot' in sys.modules)"
        out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "False")


class WriteStatusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "downloads" / SKU_STATUS_FILE
        self.trees = [tree(node(ROOT, "Working", FULL, subtasks=[node(task(80001), "Working")]))]

    def test_writes_whole_file_and_leaves_no_temp(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("tệp cũ", encoding="utf-8")
        self.assertTrue(write_status(self.trees, self.path, now=NOW, every=120))
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["totals"]["working_no_sku"], 1)
        self.assertEqual(data["every"], 120)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), [SKU_STATUS_FILE])

    def test_replaces_in_one_step(self) -> None:
        with mock.patch.object(sku_board.os, "replace", wraps=os.replace) as replace:
            self.assertTrue(write_status(self.trees, self.path, now=NOW))
        replace.assert_called_once_with(self.path.with_name(SKU_STATUS_FILE + ".tmp"), self.path)

    def test_failure_is_logged_not_raised(self) -> None:
        blocker = Path(self.dir.name) / "la-tep"
        blocker.write_text("x", encoding="utf-8")
        with self.assertLogs("flow_web.sku_board", level="WARNING"):
            self.assertFalse(write_status(self.trees, blocker / SKU_STATUS_FILE, now=NOW))

    def test_broken_tree_is_logged_not_raised(self) -> None:
        class Boom:
            def __iter__(self):
                raise RuntimeError("cây hỏng")

        with self.assertLogs("flow_web.sku_board", level="WARNING"):
            self.assertFalse(write_status(Boom(), self.path, now=NOW))
        self.assertFalse(self.path.exists())

    def test_no_path_configured(self) -> None:
        with mock.patch.object(sku_board, "status_path", return_value=None), \
                mock.patch.object(sku_board, "_warned_no_path", False), \
                self.assertLogs("flow_web.sku_board", level="WARNING") as logs:
            self.assertFalse(write_status(self.trees, now=NOW))
            self.assertFalse(write_status(self.trees, now=NOW))
        self.assertEqual(len(logs.records), 1)  # nhắc một lần, không mỗi lượt quét

    def test_status_path_from_env(self) -> None:
        self.assertEqual(status_path({"ERP_SKU_STATUS_FILE": "/a/b.json", "ERP_LISTING_FILES_DIR": "/c"}), Path("/a/b.json"))
        self.assertEqual(status_path({"ERP_LISTING_FILES_DIR": "/c"}), Path("/c") / SKU_STATUS_FILE)
        self.assertIsNone(status_path({}))


class BuildSkuTest(unittest.TestCase):
    def test_reads_only_the_status_file(self) -> None:
        api = FakeListing(json.loads(json.dumps(snapshot([], NOW))))
        data = build_sku(api, now=NOW)
        self.assertEqual(api.asked, [SKU_STATUS_FILE])
        self.assertEqual(data["sources"], {"sku": ""})
        self.assertEqual(data["bot"]["tone"], "ok")
        self.assertEqual(data["base"], "http://listing.test")

    def test_fresh_file(self) -> None:
        root = node(ROOT, "Working", FULL, subtasks=[node(task(90001), "Working", "sku: KT_1_001")])
        data = board([tree(root)], later=60)
        self.assertEqual((data["bot"]["stale"], data["bot"]["age_s"], data["bot"]["every"]), (False, 60, 120))
        self.assertEqual(data["cards"][0]["url"], "https://erp.havigroup.llc/app/task/" + task(90001))
        self.assertEqual(data["kpi"]["clusters"], 1)

    def test_stale_file_after_two_passes(self) -> None:
        # Quét mỗi 120 giây: quá 2 lượt (cộng 120 giây dư) mà chưa ghi thì báo.
        root = node(ROOT, "Working", FULL)
        self.assertFalse(board([tree(root)], later=360)["bot"]["stale"])
        data = board([tree(root)], later=400)
        self.assertTrue(data["bot"]["stale"])
        self.assertEqual(data["bot"]["tone"], "bad")
        self.assertTrue(data["alerts"][0]["text"].startswith("Bot chưa ghi mới"))

    def test_missing_file(self) -> None:
        missing = urllib.error.HTTPError("http://listing.test/files/downloads/sku_status.json", 404, "Not Found", {}, None)
        data = build_sku(FakeListing(error=missing), now=NOW)
        self.assertEqual(data["sources"], {"sku": "HTTP 404"})
        self.assertEqual((data["clusters"], data["cards"]), ([], []))
        self.assertEqual(data["kpi"]["working_no_sku"], 0)
        # Chưa có tệp thì nói rõ bot chưa ghi, không để bảng trống trơn.
        self.assertEqual(len(data["alerts"]), 1)
        self.assertTrue(data["alerts"][0]["text"].startswith("Bot chưa ghi số SKU"))
        self.assertEqual(data["alerts"][0]["tone"], "bad")
        self.assertIn("ERP_LISTING_FILES_DIR", data["alerts"][0]["text"])
        self.assertIn("ERP_SKU_STATUS_FILE", data["alerts"][0]["text"])
        self.assertEqual(data["bot"]["tone"], "bad")

    def test_broken_file(self) -> None:
        for broken, error in (
            (FakeListing(["không", "phải", "object"]), "tệp trạng thái không phải JSON object"),
            (FakeListing(error=ValueError("Expecting value: line 1 column 1")), "Expecting value: line 1 column 1"),
            (FakeListing(error=OSError("Connection refused")), "Connection refused"),
        ):
            with self.subTest(error=error):
                data = build_sku(broken, now=NOW)
                self.assertEqual(data["sources"]["sku"], error)
                self.assertEqual((data["clusters"], data["cards"]), ([], []))
                self.assertEqual(data["alerts"][0]["tone"], "bad")

    def test_garbage_inside_the_file(self) -> None:
        raw = {
            "at": NOW.isoformat(), "every": "rác",
            "clusters": ["rác", {"task": "TASK-1", "missing": "product_group", "columns": "rác", "attributes": [1]}],
            "cards": [None, {"task": "TASK-2", "working_no_sku": 1}],
        }
        data = build_sku(FakeListing(raw), now=NOW)
        self.assertEqual(data["bot"]["every"], 120)
        self.assertEqual(data["clusters"][0]["missing"], [])
        self.assertEqual(data["clusters"][0]["columns"], [])
        self.assertEqual(data["clusters"][0]["attributes"], {})
        self.assertEqual(data["cards"][0]["task"], "TASK-2")
        self.assertEqual(data["kpi"]["working_no_sku"], 1)

    def test_file_without_clusters(self) -> None:
        # Bản Listing giả của test_board trả cùng một tệp cho mọi tên.
        data = build_sku(FakeListing({"at": NOW.isoformat(), "every": 300, "cards": []}), now=NOW)
        self.assertEqual((data["sources"]["sku"], data["clusters"], data["alerts"]), ("", [], []))


class SkuListing(BoardListing):
    """Bản Listing giả của test_board, thêm tệp ``sku_status.json``."""

    def __init__(self, sku: Any = None, error: Optional[BaseException] = None) -> None:
        super().__init__()
        self.sku, self.error = sku, error

    def lister_status(self, name: str) -> Any:
        if name != SKU_STATUS_FILE:
            return super().lister_status(name)
        if self.error:
            raise self.error
        return self.sku


class SkuServerTest(unittest.TestCase):
    def start(self, listing: SkuListing) -> BoardServer:
        server = BoardServer(("127.0.0.1", 0), listing, None,
                             Checks(listing, runner=lambda *args: {}, spawn=lambda work: work()), gate=None, hosts=())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def get(self, server: BoardServer, path: str) -> tuple:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        self.addCleanup(conn.close)
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8")

    def written(self) -> Dict[str, Any]:
        root = node(ROOT, "Working", FULL, subtasks=[node(task(95001), "Working")], child_total=159)
        return json.loads(json.dumps(snapshot([tree(root)], every=120), ensure_ascii=False))

    def test_sku_part_and_page(self) -> None:
        server = self.start(SkuListing(self.written()))
        code, body = self.get(server, "/api/sku")
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertEqual((data["kpi"]["working_no_sku"], data["kpi"]["truncated"]), (1, 1))
        self.assertEqual(data["alerts"][0]["text"], f"Cụm {ROOT}: bot chỉ đọc được 1/159 thẻ.")
        code, page = self.get(server, "/")
        self.assertEqual(code, 200)
        self.assertIn("name: 'SKU & Thuộc tính'", page)
        self.assertIn("url: '/api/sku'", page)

    def test_broken_file_does_not_break_the_board(self) -> None:
        for error in (ValueError("Expecting value"),
                      urllib.error.HTTPError("http://listing/files/downloads/sku_status.json", 404, "Not Found", {}, None)):
            with self.subTest(error=type(error).__name__):
                server = self.start(SkuListing(error=error))
                code, body = self.get(server, "/api/sku")
                self.assertEqual(code, 200)
                self.assertTrue(json.loads(body)["sources"]["sku"])
                self.assertEqual(self.get(server, "/api/etsy")[0], 200)
                self.assertEqual(self.get(server, "/")[0], 200)

    def test_no_file_says_the_bot_has_not_written(self) -> None:
        missing = urllib.error.HTTPError("http://listing/files/downloads/sku_status.json", 404, "Not Found", {}, None)
        server = self.start(SkuListing(error=missing))
        code, body = self.get(server, "/api/sku")
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertEqual(data["sources"], {"sku": "HTTP 404"})
        self.assertTrue(data["alerts"][0]["text"].startswith("Bot chưa ghi số SKU"))
        # Trang vẽ đúng câu ấy ở nút phần, ở pill, ở bảng rỗng.
        code, page = self.get(server, "/")
        self.assertEqual(code, 200)
        self.assertIn("'bot chưa ghi số SKU'", page)
        self.assertIn("'Bot chưa ghi số SKU'", page)
        self.assertIn("'Bot chưa ghi số SKU.'", page)
        # Luồng trực tiếp cũng mang câu ấy, không đợi người bấm Làm mới.
        server.feed.tick = 0.02
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        self.addCleanup(conn.close)
        conn.request("GET", "/api/stream")
        got = read_events(sse(conn.getresponse()), {"etsy", "img", "sku"})
        self.assertTrue(got["sku"]["alerts"][0]["text"].startswith("Bot chưa ghi số SKU"))

    def test_stream_carries_the_sku_part(self) -> None:
        server = self.start(SkuListing(self.written()))
        server.feed.tick = 0.02
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        self.addCleanup(conn.close)
        conn.request("GET", "/api/stream")
        got = read_events(sse(conn.getresponse()), {"etsy", "img", "sku"})
        self.assertEqual(got["sku"]["kpi"]["working_no_sku"], 1)


if __name__ == "__main__":
    unittest.main()
