"""Kiểm thử kịch bản SKU dùng thật (OL, đánh từ trên xuống, không đoán, không trùng, sau restart).

Được viết theo brief briefs/r3.md và briefs/chung.md.
Tất cả kịch bản chạy trên ERP giả lập (mocked), sổ cái và bảng mã nằm trong thư mục tạm.
Tuyệt đối không gọi mạng thật và không ghi vào sổ cái thật.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
from unittest.mock import patch

from flow_web import pipeline, sku
from flow_web.erp_meta import render_meta_block, task_meta
from flow_web.service import FlowWebService
from flow_web.sku import (
    ProductBook,
    Sku,
    SkuCard,
    SkuLedger,
    SkuPlan,
    card_from_node,
    card_is_ready,
    cards_missing_sku,
    column_positions,
    flatten_tree,
    normalize_product,
    plan_skus,
    plan_tree,
    sku_pass,
    strip_accents,
    task_number,
)


def make_card(
    task_id: str,
    parent: str = "",
    meta: str = "",
    subject: str = "",
    board: str = "",
    project: str = "",
    status: str = "",
) -> SkuCard:
    """Tạo một SkuCard giả lập."""
    return SkuCard(task_id, parent, subject, task_meta({"meta": meta}), board, project, status)


def board_payload(columns: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Tạo payload taskBoard giả lập với các cột và danh sách task."""
    return {"columns": list(columns)}


class SkuTestHarness:
    """Môi trường giả lập ERP, sổ cái và bảng mã trong thư mục tạm."""

    def __init__(self, tmp_dir: str, *, project_id: str = "PROJ-0087"):
        self.tmp_dir = Path(tmp_dir)
        self.project_id = project_id
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.columns: Dict[str, List[str]] = {}  # col_status -> [task_id]
        self.comments: List[tuple[str, str]] = []
        self.titles: Dict[str, str] = {}
        self.metas: Dict[str, str] = {}
        self.book_entries: Dict[str, str] = {}
        self.sheet_rows: List[Dict[str, Any]] = []
        self.sheet_url: str = ""
        self.writes_count: Dict[str, int] = {}
        self.task_full_calls: List[tuple[str, int]] = []
        self.custom_task_full: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def add_task(
        self,
        task_id: str,
        *,
        parent: str = "",
        subject: str = "",
        meta: str = "",
        status: str = "Working",
        project: str = "",
        project_name: str = "",
    ) -> None:
        proj = project or self.project_id
        self.tasks[task_id] = {
            "name": task_id,
            "parent_task": parent,
            "subject": subject,
            "meta": meta,
            "status": status,
            "project": proj,
            "project_name": project_name,
            "subtasks": [],
            "children": [],
        }
        self.titles[task_id] = subject
        self.metas[task_id] = meta

    def set_column(self, status: str, task_ids: Sequence[str]) -> None:
        self.columns[status] = list(task_ids)

    def build_tree_payload(self, root_id: str) -> Dict[str, Any]:
        """Dựng payload taskFull dạng nested subtasks."""
        root_data = dict(self.tasks.get(root_id, {}))
        if not root_data:
            root_data = {
                "name": root_id,
                "subject": "",
                "meta": "",
                "status": "",
                "project": self.project_id,
            }
        subtasks = []
        children = []
        for tid, tdata in self.tasks.items():
            if tdata.get("parent_task") == root_id:
                node = dict(tdata)
                subtasks.append(node)
                children.append({"name": tid, "subject": tdata.get("subject", "")})
        root_data["subtasks"] = subtasks
        root_data["children"] = children
        return {"root": root_data}

    def build_board_payload(self) -> Dict[str, Any]:
        cols = []
        for status, tids in self.columns.items():
            cols.append({
                "status": status,
                "tasks": [
                    {
                        "name": tid,
                        "parent_task": self.tasks.get(tid, {}).get("parent_task", ""),
                        "status": status,
                        "project": self.project_id,
                        "custom_sku": task_meta({"meta": self.metas.get(tid, "")}).sku,
                    }
                    for tid in tids
                ],
            })
        return {"columns": cols}

    def create_service(self) -> FlowWebService:
        """Tạo một instance FlowWebService cô lập trên thư mục tạm."""
        svc = FlowWebService.__new__(FlowWebService)
        svc._sku_ledger_path = lambda: self.tmp_dir / "sku_ledger.json"
        svc._sku_book_path = lambda: self.tmp_dir / "sku_book.json"
        svc._erp_credentials = lambda: ("test_key", "test_token")
        svc._normalize_erp_task_id = lambda value: str(value or "").strip()
        svc._erp_assert_task_in_project = lambda *a, **k: None

        def read_task_full(key, token, root, depth=0):
            with self._lock:
                self.task_full_calls.append((root, depth))
                if root in self.custom_task_full:
                    custom = self.custom_task_full[root]
                    if callable(custom):
                        return custom(key, token, root, depth)
                    return custom
                return self.build_tree_payload(root)

        svc._erp_task_full = read_task_full

        def read_task_board(key, token, project):
            return self.build_board_payload()

        svc._erp_task_board = read_task_board

        def read_task_detail(key, token, task_id):
            with self._lock:
                return {
                    "name": task_id,
                    "meta": self.metas.get(task_id, ""),
                    "subject": self.titles.get(task_id, ""),
                    "status": self.tasks.get(task_id, {}).get("status", ""),
                    "project": self.project_id,
                }

        svc._erp_task_detail = read_task_detail

        def update_meta(key, token, task_id, block):
            with self._lock:
                self.writes_count[task_id] = self.writes_count.get(task_id, 0) + 1
                self.metas[task_id] = block
                if task_id in self.tasks:
                    self.tasks[task_id]["meta"] = block
            return {}

        svc._erp_update_task_meta = update_meta

        def update_title(key, token, task_id, subject):
            with self._lock:
                self.titles[task_id] = subject
                if task_id in self.tasks:
                    self.tasks[task_id]["subject"] = subject
            return {}

        svc._erp_update_task_title = update_title

        def post_comment(key, token, task_id, content, **kw):
            with self._lock:
                self.comments.append((task_id, content))
            return {}

        svc._erp_comment = post_comment

        def load_prompt_source(url):
            return self.sheet_rows

        svc._load_prompt_source_url = load_prompt_source
        svc._erp_sku_sheet_url = lambda: self.sheet_url

        return svc


class KichBan1ThuTuCotTests(unittest.TestCase):
    """Kịch bản 1:
    Sổ cái OL đang ở 48. 10 thẻ 'Punch Needle Ornament' trong cột Đang làm,
    bảng mã có 'punch needle ornament': 'OL' -> OL_1_049..058 đúng THỨ TỰ TỪ TRÊN XUỐNG của cột.
    """

    def test_cap_ma_ol_tu_tren_xuong_dung_thu_tu_cot(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = SkuTestHarness(tmp, project_id="PROJ-0087")
            # Thiết lập sổ cái ban đầu: OL đã phát tới 48
            initial_ledger = SkuLedger()
            initial_ledger.observe("OL", project=1, idea=48, project_id="PROJ-0087")
            (Path(tmp) / "sku_ledger.json").write_text(
                json.dumps(initial_ledger.as_dict()), encoding="utf-8"
            )

            # Bảng mã giả: punch needle ornament -> OL
            book = ProductBook.from_mapping({"punch needle ornament": "OL"})

            root_id = "TASK-2026-05384"
            harness.add_task(root_id, subject="Idea Root", meta="product: Punch Needle Ornament")

            # 10 thẻ con: đặt thứ tự ID không theo thứ tự số
            child_ids = [
                "TASK-2026-05410",
                "TASK-2026-05402",
                "TASK-2026-05409",
                "TASK-2026-05401",
                "TASK-2026-05408",
                "TASK-2026-05403",
                "TASK-2026-05407",
                "TASK-2026-05404",
                "TASK-2026-05406",
                "TASK-2026-05405",
            ]
            for cid in child_ids:
                harness.add_task(cid, parent=root_id, subject=f"Child {cid}", status="Working")

            # Thứ tự trên cột Đang làm (từ trên xuống):
            # Cột Working sắp theo đúng thứ tự child_ids
            harness.set_column("Working", child_ids)
            board = harness.build_board_payload()
            positions = column_positions(board)

            cards = [harness.tasks[root_id]] + [harness.tasks[cid] for cid in child_ids]
            sku_cards = [
                make_card(
                    c["name"],
                    c["parent_task"],
                    c["meta"],
                    c["subject"],
                    project=c["project"],
                    status=c["status"],
                )
                for c in cards
            ]

            # 1. Chạy plan_skus trực tiếp
            ledger_copy = SkuLedger.from_mapping(initial_ledger.as_dict())
            plan = plan_skus(
                sku_cards,
                book,
                root_id=root_id,
                ledger=ledger_copy,
                project_id="PROJ-0087",
                positions=positions,
            )

            # Kiểm tra: mỗi thẻ theo thứ tự từ trên xuống nhận OL_1_049 .. OL_1_058
            expected_skus = [f"OL_1_{i:03d}" for i in range(49, 59)]
            assigned_dict = {item.task_id: item.sku for item in plan.assignments}

            for cid, expected_sku in zip(child_ids, expected_skus):
                self.assertEqual(
                    expected_sku,
                    assigned_dict.get(cid),
                    f"Thẻ {cid} tại vị trí cột phải nhận {expected_sku}",
                )

            # 2. Chạy qua plan_erp_skus và fill_task_skus của service
            svc = harness.create_service()
            svc.load_sku_book = lambda *a, **k: book
            with patch("flow_web.service.log"), patch("flow_web.service.time.sleep"):
                res = svc.fill_task_skus(root_id)

            written_dict = {item["task_id"]: item["sku"] for item in res["written"]}
            for cid, expected_sku in zip(child_ids, expected_skus):
                self.assertEqual(
                    expected_sku,
                    written_dict.get(cid),
                    f"Thẻ {cid} sau khi ghi phải nhận {expected_sku}",
                )

            # Sổ cái sau khi ghi phải chạm mốc 58
            final_ledger = svc.load_sku_ledger()
            self.assertEqual(58, final_ledger.floor_idea("OL"))
            self.assertEqual(1, final_ledger.floor_project("OL"))


class KichBan2KhongDoanMaTests(unittest.TestCase):
    """Kịch bản 2:
    Không có dòng trong bảng mã -> KHÔNG cấp mã, không đoán (không được ra PNO hay tiền tố nào khác),
    thẻ vào skipped kèm lý do, unlisted có tên sản phẩm, ghi chú lên thẻ gốc đúng 1 lần.
    """

    def test_khong_doan_ma_va_ghi_chu_the_goc_dung_mot_lan(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = SkuTestHarness(tmp)
            book = ProductBook.from_mapping({"bờm": "BT"})  # Không có "Punch Needle Ornament"

            root_id = "TASK-2026-05384"
            harness.add_task(root_id, subject="Idea Root", meta="product: Punch Needle Ornament")
            child_1 = "TASK-2026-05401"
            child_2 = "TASK-2026-05402"
            harness.add_task(child_1, parent=root_id, status="Working")
            harness.add_task(child_2, parent=root_id, status="Working")
            harness.set_column("Working", [child_1, child_2])

            svc = harness.create_service()
            svc.load_sku_book = lambda *a, **k: book

            with patch("flow_web.service.log"), patch("flow_web.service.time.sleep"):
                # Lần 1: fill_task_skus
                res1 = svc.fill_task_skus(root_id)

            # Không cấp mã nào
            self.assertEqual([], res1["written"])
            self.assertEqual([], res1["changes"])
            # Không đoán mã ra PNO
            for item in res1.get("assignments", []):
                self.assertFalse(item["sku"].startswith("PNO"))

            # unlisted có tên sản phẩm
            self.assertEqual(["Punch Needle Ornament"], res1["unlisted"])

            # Thẻ con vào skipped kèm lý do
            skipped_reasons = {item["task_id"]: item["reason"] for item in res1["skipped"]}
            self.assertIn("chưa có mã trong bảng SKU cho Punch Needle Ornament", skipped_reasons.get(child_1, ""))
            self.assertIn("chưa có mã trong bảng SKU cho Punch Needle Ornament", skipped_reasons.get(child_2, ""))

            # Ghi chú lên thẻ gốc đúng 1 lần
            self.assertEqual(1, len(harness.comments))
            comment_target, comment_body = harness.comments[0]
            self.assertEqual(root_id, comment_target)
            self.assertIn("Chưa có mã trong bảng SKU cho “Punch Needle Ornament”", comment_body)

            # Lần 2: chạy lại trên cùng service -> KHÔNG ghi chú thêm lần nữa
            with patch("flow_web.service.log"), patch("flow_web.service.time.sleep"):
                res2 = svc.fill_task_skus(root_id)

            self.assertEqual(1, len(harness.comments), "Không được đăng bình luận trùng lặp trên cùng phiên chạy")


class KichBan3SheetTenMoiVaChuanHoaTests(unittest.TestCase):
    """Kịch bản 3:
    Sheet có ô TÊN MỚI = 'Punch Needle Ornament' ở dòng 'ornament len chọc' -> ra OL.
    Khoá có dấu / không dấu / hoa thường / thừa khoảng trắng đều khớp.
    """

    def test_sheet_ten_moi_va_chuan_hoa_khop_moi_kieu_go(self):
        # Tạo bảng sheet giả lập với cột TÊN HÀNG, TÊN MỚI, SKU
        rows = [
            {
                "TÊN HÀNG": "ornament len chọc",
                "TÊN MỚI": "Punch Needle Ornament",
                "SKU": "OL",
            }
        ]
        book = ProductBook.from_rows(rows)

        # 1. Tra cứu trực tiếp
        self.assertEqual(("OL", "book"), book.lookup("ornament len chọc"))
        self.assertEqual(("OL", "book"), book.lookup("ornament len choc"))
        self.assertEqual(("OL", "book-alias"), book.lookup("Punch Needle Ornament"))
        self.assertEqual(("OL", "book-alias"), book.lookup("punch needle ornament"))
        self.assertEqual(("OL", "book-alias"), book.lookup("PUNCH NEEDLE ORNAMENT"))
        self.assertEqual(("OL", "book-alias"), book.lookup("  Punch   Needle   Ornament  "))
        self.assertEqual(("OL", "book"), book.lookup("  ORNAMENT   LEN   CHỌC  "))

        # 2. Thử trong plan_skus với các cách viết khác nhau trên thẻ
        test_cases = [
            "Punch Needle Ornament",
            "punch needle ornament",
            "PUNCH NEEDLE ORNAMENT",
            "  Punch   Needle   Ornament  ",
            "ornament len chọc",
            "ornament len choc",
            "  ORNAMENT  LEN  CHỌC  ",
        ]

        for product_spelling in test_cases:
            with self.subTest(spelling=product_spelling):
                cards = [
                    make_card("TASK-1", meta=f"product: {product_spelling}"),
                    make_card("TASK-2", parent="TASK-1", status="Working"),
                ]
                plan = plan_skus(cards, book, root_id="TASK-1", project_id="PROJ-0087")
                self.assertEqual("OL", plan.prefix)
                self.assertEqual((), plan.unlisted)
                self.assertEqual(1, len(plan.assignments))
                self.assertEqual("OL_1_001", plan.assignments[0].sku)


class KichBan4ThuTuUuTienBangMaTests(unittest.TestCase):
    """Kịch bản 4:
    Thứ tự ưu tiên: FLOW_SKU_MAP env > sheet > sku_book.json. Ghi lại thực tế.
    """

    def test_thu_tu_uu_tien_bang_ma(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = SkuTestHarness(tmp)
            svc = harness.create_service()

            # 1. sku_book.json trên đĩa khai: ao khoac = AK
            disk_path = Path(tmp) / "sku_book.json"
            disk_path.write_text(
                json.dumps({"entries": {"ao khoac": "AK"}}), encoding="utf-8"
            )

            # 2. Sheet khai: ao khoac = JK (jacket)
            harness.sheet_rows = [
                {"TÊN HÀNG": "ao khoac", "SKU": "JK"}
            ]
            harness.sheet_url = "https://docs.google.com/spreadsheets/d/test_sheet"

            # 3. Biến môi trường FLOW_SKU_MAP: ao khoac = CO (coat)
            with patch.dict(os.environ, {"FLOW_SKU_MAP": "ao khoac=CO"}):
                book = svc.load_sku_book(refresh=True)
                code, src = book.lookup("ao khoac")
                self.assertEqual("CO", code, "FLOW_SKU_MAP (env) phải có độ ưu tiên cao nhất")

            # 4. Khi không có env: sheet thắng đĩa (JK > AK)
            with patch.dict(os.environ, {}, clear=True):
                # đảm bảo FLOW_SKU_MAP không có trong env
                book_no_env = svc.load_sku_book(refresh=True)
                code, src = book_no_env.lookup("ao khoac")
                self.assertEqual("JK", code, "Sheet phải ưu tiên hơn sku_book.json trên đĩa")

            # 5. Khi sheet không có dòng (hoặc không có sheet): fallback về sku_book.json trên đĩa
            harness.sheet_rows = []
            with patch.dict(os.environ, {}, clear=True):
                book_disk_only = svc.load_sku_book(refresh=True)
                code, src = book_disk_only.lookup("ao khoac")
                self.assertEqual("AK", code, "sku_book.json trên đĩa là fallback khi env và sheet không có")


class KichBan5GiuMaCuVaRenumberTests(unittest.TestCase):
    """Kịch bản 5:
    Thẻ đã có mã giữ nguyên mã khi quét lại. Thẻ mới vào Đang làm nhận số tiếp theo (không đánh xen).
    renumber=True đánh lại đúng cụm, theo thứ tự cột.
    """

    def test_giu_ma_cu_khong_danh_xen_va_renumber_theo_cot(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = SkuTestHarness(tmp, project_id="PROJ-0087")
            book = ProductBook.from_mapping({"punch needle ornament": "OL"})

            root_id = "TASK-ROOT"
            harness.add_task(root_id, subject="Idea Root", meta="product: Punch Needle Ornament")

            # Thẻ TASK-1 đã có mã OL_1_005
            harness.add_task("TASK-1", parent=root_id, meta="sku: OL_1_005", status="Working")
            # Thẻ TASK-2 mới vào Đang làm, chưa có mã
            harness.add_task("TASK-2", parent=root_id, meta="", status="Working")

            harness.set_column("Working", ["TASK-1", "TASK-2"])
            svc = harness.create_service()
            svc.load_sku_book = lambda *a, **k: book

            # Quét lần đầu (renumber=False)
            with patch("flow_web.service.log"), patch("flow_web.service.time.sleep"):
                res1 = svc.fill_task_skus(root_id, renumber=False)

            # TASK-1 giữ nguyên mã OL_1_005
            written_1 = {item["task_id"]: item["sku"] for item in res1["written"]}
            self.assertNotIn("TASK-1", written_1, "Thẻ đã có mã không được ghi lại")
            self.assertEqual("OL_1_005", task_meta({"meta": harness.metas["TASK-1"]}).sku)

            # TASK-2 nhận số tiếp theo (OL_1_006), không đánh xen vào 001..004
            self.assertEqual("OL_1_006", written_1.get("TASK-2"))

            # Thêm thẻ TASK-3 vào đỉnh cột: thứ tự cột giờ là TASK-3, TASK-2, TASK-1
            harness.add_task("TASK-3", parent=root_id, meta="", status="Working")
            harness.set_column("Working", ["TASK-3", "TASK-2", "TASK-1"])

            # Chạy renumber=True: cả cụm đánh lại theo thứ tự cột
            # Sàn hiện tại là 006, nên đánh lại nhận các số 007, 008, 009
            with patch("flow_web.service.log"), patch("flow_web.service.time.sleep"):
                res2 = svc.fill_task_skus(root_id, renumber=True)

            written_2 = {item["task_id"]: item["sku"] for item in res2["written"]}
            # TASK-3 ở đỉnh cột -> nhận OL_1_007
            # TASK-2 ở giữa cột -> nhận OL_1_008
            # TASK-1 ở đáy cột -> nhận OL_1_009
            self.assertEqual("OL_1_007", written_2.get("TASK-3"))
            self.assertEqual("OL_1_008", written_2.get("TASK-2"))
            self.assertEqual("OL_1_009", written_2.get("TASK-1"))


class KichBan6ChayChongNhauKhongTrungTests(unittest.TestCase):
    """Kịch bản 6:
    Hai lượt sku_pass chạy chồng nhau (asyncio.gather) -> không số nào cấp hai lần (ERP không chặn trùng).
    """

    def test_hai_luot_chay_chong_nhau_khong_cap_trung_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = SkuTestHarness(tmp, project_id="PROJ-0087")
            book = ProductBook.from_mapping({"punch needle ornament": "OL"})

            # Tạo 2 cụm cha khác nhau nhưng cùng dùng chung mã OL
            root_a = "TASK-ROOT-A"
            root_b = "TASK-ROOT-B"
            harness.add_task(root_a, meta="product: Punch Needle Ornament")
            harness.add_task(root_b, meta="product: Punch Needle Ornament")

            # Cụm A có 3 thẻ con
            c_a1 = "TASK-A-1"
            c_a2 = "TASK-A-2"
            c_a3 = "TASK-A-3"
            for cid in (c_a1, c_a2, c_a3):
                harness.add_task(cid, parent=root_a, status="Working")

            # Cụm B có 3 thẻ con
            c_b1 = "TASK-B-1"
            c_b2 = "TASK-B-2"
            c_b3 = "TASK-B-3"
            for cid in (c_b1, c_b2, c_b3):
                harness.add_task(cid, parent=root_b, status="Working")

            harness.set_column("Working", [c_a1, c_a2, c_a3, c_b1, c_b2, c_b3])
            svc = harness.create_service()
            svc.load_sku_book = lambda *a, **k: book

            # Chạy đồng thời 2 lượt đánh số bằng asyncio.gather
            async def run_concurrent():
                with patch("flow_web.service.log"), patch("flow_web.service.time.sleep"):
                    task_a = svc.sync_erp_skus(root_a)
                    task_b = svc.sync_erp_skus(root_b)
                    return await asyncio.gather(task_a, task_b)

            res_a, res_b = asyncio.run(run_concurrent())

            skus_a = [item["sku"] for item in res_a["written"]]
            skus_b = [item["sku"] for item in res_b["written"]]

            all_skus = skus_a + skus_b
            self.assertEqual(6, len(all_skus), "Tổng số mã cấp phải là 6")
            # KHÔNG SỐ NÀO CẤP HAI LẦN
            self.assertEqual(len(all_skus), len(set(all_skus)), f"Không được có mã trùng lặp: {all_skus}")


class KichBan7RestartDichVuTests(unittest.TestCase):
    """Kịch bản 7:
    'Restart': tạo service mới đọc lại sổ cái từ đĩa -> không cấp lại số đã dùng, không nhảy số.
    """

    def test_restart_doc_so_cai_tu_dia_khong_cap_lai_khong_nhay_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = SkuTestHarness(tmp, project_id="PROJ-0087")
            book = ProductBook.from_mapping({"punch needle ornament": "OL"})

            root_1 = "TASK-ROOT-1"
            harness.add_task(root_1, meta="product: Punch Needle Ornament")
            harness.add_task("TASK-1", parent=root_1, status="Working")
            harness.add_task("TASK-2", parent=root_1, status="Working")
            harness.set_column("Working", ["TASK-1", "TASK-2"])

            # Phiên 1 của service
            svc1 = harness.create_service()
            svc1.load_sku_book = lambda *a, **k: book

            with patch("flow_web.service.log"), patch("flow_web.service.time.sleep"):
                res1 = svc1.fill_task_skus(root_1)

            skus_1 = [item["sku"] for item in res1["written"]]
            self.assertEqual(["OL_1_001", "OL_1_002"], skus_1)

            # Mô phỏng restart: Huỷ svc1, tạo svc2 hoàn toàn mới
            del svc1

            root_2 = "TASK-ROOT-2"
            harness.add_task(root_2, meta="product: Punch Needle Ornament")
            harness.add_task("TASK-3", parent=root_2, status="Working")
            harness.add_task("TASK-4", parent=root_2, status="Working")
            harness.set_column("Working", ["TASK-1", "TASK-2", "TASK-3", "TASK-4"])

            svc2 = harness.create_service()
            svc2.load_sku_book = lambda *a, **k: book

            # Svc2 đọc lại sổ cái từ đĩa
            ledger_loaded = svc2.load_sku_ledger()
            self.assertEqual(2, ledger_loaded.floor_idea("OL"))

            with patch("flow_web.service.log"), patch("flow_web.service.time.sleep"):
                res2 = svc2.fill_task_skus(root_2)

            skus_2 = [item["sku"] for item in res2["written"]]
            # Không cấp lại 001, 002 và không nhảy số -> phải là 003, 004
            self.assertEqual(["OL_1_003", "OL_1_004"], skus_2)


class KichBan8CatSubtasks59TheTests(unittest.TestCase):
    """Kịch bản 8:
    Thẻ cha có 80 thẻ con (ERP taskFull.subtasks bị cắt ở 59) -> tất cả thẻ con trong Đang làm đều được
    xét; không được im lặng bỏ sót mà báo skipped: 0.
    Kịch bản 8b: Thẻ 60 đã có mã không bị cấp đè, không nhảy số.
    Kịch bản 8c: Thẻ 60 khi renumber=True được đánh lại đúng thứ tự cột.
    ERP Request Count: Cây 60 node chỉ thêm đúng 1 lượt đọc, cây <=59 không thêm lượt nào.
    """

    def test_the_cha_80_the_con_subtasks_cat_o_59_khong_bo_sot(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = SkuTestHarness(tmp, project_id="PROJ-0087")
            book = ProductBook.from_mapping({"punch needle ornament": "OL"})

            root_id = "TASK-ROOT-80"
            harness.add_task(root_id, subject="Root 80", meta="product: Punch Needle Ornament")

            all_child_ids = [f"TASK-CHILD-{i:03d}" for i in range(1, 81)]
            for cid in all_child_ids:
                harness.add_task(cid, parent=root_id, subject=f"Child {cid}", status="Working")

            # Mô phỏng ERP taskFull chuẩn:
            # children chứa đủ 80 thẻ con CHỈ CÓ name và subject!
            # subtasks chỉ chứa 59 thẻ con đầu tiên có đủ meta!
            custom_payload = {
                "root": {
                    "name": root_id,
                    "subject": "Root 80",
                    "meta": "product: Punch Needle Ornament",
                    "project": "PROJ-0087",
                    "project_name": "punch needle ornament",
                    "status": "Working",
                    "children": [
                        {"name": cid, "subject": f"Child {cid}"}
                        for cid in all_child_ids
                    ],
                    "subtasks": [
                        {
                            "name": cid,
                            "parent_task": root_id,
                            "subject": f"Child {cid}",
                            "status": "Working",
                            "project": "PROJ-0087",
                            "meta": "",
                            "subtasks": [],
                        }
                        for cid in all_child_ids[:59]  # CẮT Ở 59!
                    ],
                }
            }

            # 1. flatten_tree độc lập chỉ đi qua subtasks (chỉ có 1 cha + 59 con = 60 cards)
            cards = flatten_tree(custom_payload["root"])
            self.assertEqual(60, len(cards), "flatten_tree chỉ đi qua subtasks và gốc")

            # 2. plan_erp_skus qua service phải đọc bổ sung 21 thẻ con bị cắt và gom đủ 80 thẻ
            harness.custom_task_full[root_id] = custom_payload
            harness.set_column("Working", all_child_ids)
            svc = harness.create_service()
            svc.load_sku_book = lambda *a, **k: book

            plan_erp = svc.plan_erp_skus("key", "token", root_id)
            self.assertEqual(
                80,
                len(plan_erp.assignments),
                "plan_erp_skus phải trả kế hoạch cho đủ 80 thẻ con",
            )
            assigned_ids = {item.task_id for item in plan_erp.assignments}
            for cid in all_child_ids:
                self.assertIn(cid, assigned_ids, f"Thẻ con {cid} không được bị bỏ sót")

            # Khẳng định số request:
            # 1 request đọc root + đúng 21 request đọc 21 thẻ con (từ 60 đến 80) bị cắt khỏi subtasks
            child_reads = [t for t, _ in harness.task_full_calls if t != root_id]
            self.assertEqual(
                all_child_ids[59:],
                child_reads,
                "Chỉ đọc bổ sung đúng 21 thẻ con nằm ngoài subtasks",
            )

    def test_the_con_ngoai_subtasks_chua_sang_dang_lam_thi_bao_skipped_chu_khong_bo_sot(self):
        """Nếu 59 thẻ ở Đang làm, 21 thẻ ở Cần làm:
        21 thẻ ở Cần làm phải vào skipped, KHÔNG được im lặng bỏ sót mà báo skipped: 0.
        """
        with tempfile.TemporaryDirectory() as tmp:
            harness = SkuTestHarness(tmp, project_id="PROJ-0087")
            book = ProductBook.from_mapping({"punch needle ornament": "OL"})

            root_id = "TASK-ROOT-80"
            harness.add_task(root_id, subject="Root 80", meta="product: Punch Needle Ornament")

            all_child_ids = [f"TASK-CHILD-{i:03d}" for i in range(1, 81)]
            doing_ids = all_child_ids[:59]
            todo_ids = all_child_ids[59:]

            for cid in doing_ids:
                harness.add_task(cid, parent=root_id, subject=f"Child {cid}", status="Working")
            for cid in todo_ids:
                harness.add_task(cid, parent=root_id, subject=f"Child {cid}", status="Open")

            custom_payload = {
                "root": {
                    "name": root_id,
                    "subject": "Root 80",
                    "meta": "product: Punch Needle Ornament",
                    "project": "PROJ-0087",
                    "project_name": "punch needle ornament",
                    "status": "Working",
                    "children": [
                        {"name": cid, "subject": f"Child {cid}"}
                        for cid in all_child_ids
                    ],
                    "subtasks": [
                        {
                            "name": cid,
                            "parent_task": root_id,
                            "subject": f"Child {cid}",
                            "status": "Working",
                            "project": "PROJ-0087",
                            "meta": "",
                            "subtasks": [],
                        }
                        for cid in doing_ids
                    ],
                }
            }

            harness.custom_task_full[root_id] = custom_payload
            svc = harness.create_service()
            svc.load_sku_book = lambda *a, **k: book

            plan_erp = svc.plan_erp_skus("key", "token", root_id)

            self.assertEqual(59, len(plan_erp.assignments), "59 thẻ ở Đang làm được cấp mã")
            # 21 thẻ ở Cần làm phải nằm trong skipped, KHÔNG ĐƯỢC BÁO SKIPPED: 0
            skipped_ids = {task_id for task_id, _ in plan_erp.skipped}
            self.assertEqual(21, len(plan_erp.skipped), "21 thẻ ở Cần làm phải được báo trong skipped")
            for tid in todo_ids:
                self.assertIn(tid, skipped_ids, f"Thẻ {tid} phải nằm trong skipped")

    def test_the_con_thu_60_da_co_ma_khong_bi_cap_de(self):
        """Kịch bản 8b:
        Thẻ con thứ 60 (chỉ nằm trong children) ĐÃ CÓ custom_sku = OL_1_060 trên ERP,
        ở cột Đang làm. Chạy renumber=False với 2 thẻ mới ->
        Thẻ 60 KHÔNG được cấp mã mới, KHÔNG nằm trong changes, sổ không nhảy số.
        """
        with tempfile.TemporaryDirectory() as tmp:
            harness = SkuTestHarness(tmp, project_id="PROJ-0087")
            book = ProductBook.from_mapping({"punch needle ornament": "OL"})

            root_id = "TASK-ROOT-60"
            harness.add_task(root_id, subject="Root 60", meta="product: Punch Needle Ornament")

            all_child_ids = [f"TASK-CHILD-{i:03d}" for i in range(1, 61)]
            # 2 thẻ đầu là thẻ mới chưa có mã:
            harness.add_task("TASK-CHILD-001", parent=root_id, subject="Child 001", status="Working", meta="")
            harness.add_task("TASK-CHILD-002", parent=root_id, subject="Child 002", status="Working", meta="")
            # Thẻ 003..059 đã có mã:
            for i in range(3, 60):
                cid = f"TASK-CHILD-{i:03d}"
                harness.add_task(cid, parent=root_id, subject=f"Child {i:03d}", status="Working", meta=f"sku: OL_1_{i:03d}")
            # Thẻ 060 ĐÃ CÓ MÃ trên ERP:
            harness.add_task("TASK-CHILD-060", parent=root_id, subject="Child 060", status="Working", meta="sku: OL_1_060")

            custom_payload = {
                "root": {
                    "name": root_id,
                    "subject": "Root 60",
                    "meta": "product: Punch Needle Ornament",
                    "project": "PROJ-0087",
                    "project_name": "punch needle ornament",
                    "status": "Working",
                    "children": [
                        {"name": cid, "subject": f"Child {cid}"}
                        for cid in all_child_ids
                    ],
                    "subtasks": [
                        {
                            "name": cid,
                            "parent_task": root_id,
                            "subject": f"Child {cid}",
                            "status": "Working",
                            "project": "PROJ-0087",
                            "meta": harness.tasks[cid]["meta"],
                            "subtasks": [],
                        }
                        for cid in all_child_ids[:59]
                    ],
                }
            }

            harness.custom_task_full[root_id] = custom_payload
            harness.set_column("Working", all_child_ids)

            svc = harness.create_service()
            svc.load_sku_book = lambda *a, **k: book

            # Khởi tạo sổ cái ở mốc 60 (đã có thẻ 60 trên hệ thống)
            ledger = SkuLedger()
            ledger.observe_sku("OL_1_060", "PROJ-0087")

            plan = svc.plan_erp_skus("key", "token", root_id, renumber=False, ledger=ledger)

            # Thẻ 60 KHÔNG nằm trong changes
            changed_ids = [c.task_id for c in plan.changes]
            self.assertNotIn("TASK-CHILD-060", changed_ids, "Thẻ 60 đã có mã không được cấp lại mã mới")

            # Thẻ 60 giữ nguyên mã cũ
            assign_60 = next((a for a in plan.assignments if a.task_id == "TASK-CHILD-060"), None)
            self.assertIsNotNone(assign_60, "Thẻ 60 phải có mặt trong assignments")
            self.assertEqual("OL_1_060", assign_60.sku)
            self.assertTrue(assign_60.kept)

            # 2 thẻ mới (001, 002) nhận mã số tiếp theo (không đè 060): 061, 062
            assign_1 = next((a for a in plan.assignments if a.task_id == "TASK-CHILD-001"), None)
            assign_2 = next((a for a in plan.assignments if a.task_id == "TASK-CHILD-002"), None)
            self.assertIsNotNone(assign_1)
            self.assertIsNotNone(assign_2)
            self.assertEqual("OL_1_061", assign_1.sku)
            self.assertEqual("OL_1_062", assign_2.sku)
            self.assertFalse(assign_1.kept)
            self.assertFalse(assign_2.kept)

            # Số request: đúng 1 request đọc thêm cho thẻ 60
            child_reads = [t for t, _ in harness.task_full_calls if t != root_id]
            self.assertEqual(["TASK-CHILD-060"], child_reads)

    def test_the_con_thu_60_renumber_danh_lai_dung_thu_tu_cot(self):
        """Kịch bản 8c:
        renumber=True -> thẻ 60 được đánh lại đúng thứ tự cột như mọi thẻ khác (nó có trong cụm),
        không trùng số.
        """
        with tempfile.TemporaryDirectory() as tmp:
            harness = SkuTestHarness(tmp, project_id="PROJ-0087")
            book = ProductBook.from_mapping({"punch needle ornament": "OL"})

            root_id = "TASK-ROOT-60"
            harness.add_task(root_id, subject="Root 60", meta="product: Punch Needle Ornament")

            all_child_ids = [f"TASK-CHILD-{i:03d}" for i in range(1, 61)]
            for cid in all_child_ids:
                harness.add_task(cid, parent=root_id, subject=f"Child {cid}", status="Working", meta="")

            custom_payload = {
                "root": {
                    "name": root_id,
                    "subject": "Root 60",
                    "meta": "product: Punch Needle Ornament",
                    "project": "PROJ-0087",
                    "project_name": "punch needle ornament",
                    "status": "Working",
                    "children": [
                        {"name": cid, "subject": f"Child {cid}"}
                        for cid in all_child_ids
                    ],
                    "subtasks": [
                        {
                            "name": cid,
                            "parent_task": root_id,
                            "subject": f"Child {cid}",
                            "status": "Working",
                            "project": "PROJ-0087",
                            "meta": "",
                            "subtasks": [],
                        }
                        for cid in all_child_ids[:59]
                    ],
                }
            }

            # Thứ tự trên cột xáo trộn để kiểm tra: đảo ngược thứ tự
            column_order = list(reversed(all_child_ids))
            harness.set_column("Working", column_order)

            harness.custom_task_full[root_id] = custom_payload
            svc = harness.create_service()
            svc.load_sku_book = lambda *a, **k: book

            plan = svc.plan_erp_skus("key", "token", root_id, renumber=True)

            self.assertEqual(60, len(plan.assignments))
            assigned_skus = [a.sku for a in plan.assignments]
            self.assertEqual(60, len(set(assigned_skus)), "Không được có mã SKU trùng lặp")

            # Thẻ đứng đầu cột (TASK-CHILD-060) phải nhận OL_1_001
            assign_60 = next((a for a in plan.assignments if a.task_id == "TASK-CHILD-060"), None)
            self.assertIsNotNone(assign_60)
            self.assertEqual("OL_1_001", assign_60.sku)

    def test_cay_duoi_60_node_khong_them_request_erp(self):
        """Cây <= 59 thẻ con:
        Tất cả đã có trong subtasks, plan_erp_skus KHÔNG gọi thêm bất kỳ request nào đọc thẻ con.
        """
        with tempfile.TemporaryDirectory() as tmp:
            harness = SkuTestHarness(tmp, project_id="PROJ-0087")
            book = ProductBook.from_mapping({"punch needle ornament": "OL"})

            root_id = "TASK-ROOT-10"
            harness.add_task(root_id, subject="Root 10", meta="product: Punch Needle Ornament")

            child_ids = [f"TASK-CHILD-{i:03d}" for i in range(1, 11)]
            for cid in child_ids:
                harness.add_task(cid, parent=root_id, subject=f"Child {cid}", status="Working")

            harness.set_column("Working", child_ids)
            svc = harness.create_service()
            svc.load_sku_book = lambda *a, **k: book

            plan = svc.plan_erp_skus("key", "token", root_id)
            self.assertEqual(10, len(plan.assignments))

            # Số request: chỉ 1 request đọc root_id, 0 request đọc thẻ con!
            child_reads = [t for t, _ in harness.task_full_calls if t != root_id]
            self.assertEqual([], child_reads, "Cây <= 59 thẻ con không được thêm lượt đọc thẻ con nào")

    def test_doc_the_con_ngoai_subtasks_that_bai_thi_dung_ca_luot(self):
        """Nếu đọc thẻ con ngoài subtasks bị lỗi (ERP chập chờn/mạng lỗi),
        plan_erp_skus phải raise RuntimeError dừng cả lượt, không đoán.
        """
        with tempfile.TemporaryDirectory() as tmp:
            harness = SkuTestHarness(tmp, project_id="PROJ-0087")
            book = ProductBook.from_mapping({"punch needle ornament": "OL"})

            root_id = "TASK-ROOT-60"
            harness.add_task(root_id, subject="Root 60", meta="product: Punch Needle Ornament")

            all_child_ids = [f"TASK-CHILD-{i:03d}" for i in range(1, 61)]
            for cid in all_child_ids:
                harness.add_task(cid, parent=root_id, subject=f"Child {cid}", status="Working")

            custom_payload = {
                "root": {
                    "name": root_id,
                    "subject": "Root 60",
                    "meta": "product: Punch Needle Ornament",
                    "project": "PROJ-0087",
                    "project_name": "punch needle ornament",
                    "status": "Working",
                    "children": [
                        {"name": cid, "subject": f"Child {cid}"}
                        for cid in all_child_ids
                    ],
                    "subtasks": [
                        {
                            "name": cid,
                            "parent_task": root_id,
                            "subject": f"Child {cid}",
                            "status": "Working",
                            "project": "PROJ-0087",
                            "meta": "",
                            "subtasks": [],
                        }
                        for cid in all_child_ids[:59]
                    ],
                }
            }

            harness.custom_task_full[root_id] = custom_payload

            def error_reader(key, token, root, depth=0):
                raise ConnectionError("ERP network error")

            harness.custom_task_full["TASK-CHILD-060"] = error_reader

            svc = harness.create_service()
            svc.load_sku_book = lambda *a, **k: book

            with self.assertRaises(RuntimeError) as cm:
                svc.plan_erp_skus("key", "token", root_id)
            self.assertIn("TASK-CHILD-060", str(cm.exception))


class KichBan9TheCotKhacDangLamTests(unittest.TestCase):
    """Kịch bản 9:
    Thẻ ở cột khác Đang làm (Cần làm, Open, Cancelled) -> không cấp mã.
    """

    def test_the_o_cot_khac_dang_lam_khong_duoc_cap_ma(self):
        book = ProductBook.from_mapping({"punch needle ornament": "OL"})
        root_id = "TASK-ROOT"

        cards = [
            make_card(root_id, meta="product: Punch Needle Ornament", status="Working"),
            make_card("TASK-TODO", parent=root_id, status="Open"),
            make_card("TASK-CAN-LAM", parent=root_id, status="Cần làm"),
            make_card("TASK-CANCELLED", parent=root_id, status="Cancelled"),
            make_card("TASK-DOING", parent=root_id, status="Working"),
        ]

        plan = plan_skus(cards, book, root_id=root_id, project_id="PROJ-0087")

        # Chỉ duy nhất thẻ TASK-DOING được cấp mã
        self.assertEqual(1, len(plan.assignments))
        self.assertEqual("TASK-DOING", plan.assignments[0].task_id)

        # Các thẻ khác phải nằm trong skipped kèm lý do
        skipped_dict = dict(plan.skipped)
        self.assertIn("TASK-TODO", skipped_dict)
        self.assertIn("chưa sang cột Đang làm", skipped_dict["TASK-TODO"])
        self.assertIn("TASK-CAN-LAM", skipped_dict)
        self.assertIn("chưa sang cột Đang làm", skipped_dict["TASK-CAN-LAM"])
        self.assertIn("TASK-CANCELLED", skipped_dict)
        self.assertIn("chưa sang cột Đang làm", skipped_dict["TASK-CANCELLED"])


if __name__ == "__main__":
    unittest.main()
