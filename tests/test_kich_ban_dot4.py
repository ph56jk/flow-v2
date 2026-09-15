"""Kịch bản seller đầu–cuối trên agent/hvg-pc-dot4 — R3 (tests/test_kich_ban_dot4.py).

Kiểm tra các luật theo quy trình seller (lời anh Trung Anh):
1. Tạo idea, rồi "Chuyển thành task cha".
2. Khai 4 thuộc tính.
3. Mỗi ảnh trong bình luận thành một idea con.
4. Chỉ làm ảnh content khi thẻ cha có content: có. Không khai thì không làm.
5. Đủ ảnh đã duyệt thì gắn nhãn DONE. Duyệt 3/4 ảnh thì không DONE.
6. Bot không ghi content thay seller.

Bổ sung từ 12/09:
- Bot chép Thuộc tính của thẻ cha xuống thẻ con, nhưng KHÔNG chép content.
- Bắt buộc hai ca kiểm thử:
  (a) Thẻ cha content: có, chạy lượt chép Thuộc tính xong thì cổng ảnh content
      vẫn mở (vì đọc thẻ cha), còn thẻ con không có content.
  (b) Thẻ cha viết content: Có, co, yes đều mở cổng; không và ô trống thì đóng.
      Dùng hàm thật _erp_idea_gate_reason / _erp_idea_content_enabled trong flow_web/service.py.
"""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple
import unittest
from unittest.mock import AsyncMock, patch

from flow_web.agent_bot import (
    AgentBot,
    AgentBotConfig,
    AgentBotState,
    BOARD_ROW_KEY,
)
from flow_web.erp_meta import task_meta
from flow_web.schemas import ERPConfig
from flow_web.service import FlowWebService
from flow_web.store import StateStore

BOT_USER = "agent-seller-bot@bots.hvg.internal"
PROJ_ID = "PROJ-0013"

DU_BON_KHOA = (
    "product_type: Khăn tay cô dâu thêu tay\n"
    "product_group: Thêu tay\n"
    "fulfillment: HaviGroup\n"
    "sales_channel: Etsy"
)
CO_CONTENT = DU_BON_KHOA + "\ncontent: Có"


class InMemoryERP:
    """ERP giả trong bộ nhớ mô phỏng đầy đủ thẻ, bình luận, tệp, thuộc tính, nhãn."""

    def __init__(self, project_id: str = PROJ_ID) -> None:
        self.project_id = project_id
        self.columns = ["Cần làm", "Đang làm", "Hoàn thành"]
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.assigned_labels: Dict[str, set[str]] = {}
        self.child_counter = 0
        self.comment_counter = 0
        self.task_attachments: Dict[str, List[Dict[str, Any]]] = {}

    def add_task(
        self,
        task_id: str,
        *,
        subject: str = "Idea Khăn tay",
        status: str = "Cần làm",
        meta: str = "",
        meta_auto: str = "",
        cover_image: str = "",
        parent_task: str = "",
        children: Optional[List[Dict[str, Any]]] = None,
        comments: Optional[List[Dict[str, Any]]] = None,
        agents: Optional[List[str]] = None,
        attachment_count: int = 0,
    ) -> Dict[str, Any]:
        task = {
            "name": task_id,
            "subject": subject,
            "status": status,
            "project": self.project_id,
            "meta": meta,
            "meta_auto": meta_auto,
            "cover_image": cover_image,
            "parent_task": parent_task,
            "children": list(children or []),
            "comments": list(comments or []),
            "agents": [{"bot_user": a} for a in (agents or [])],
            "attachment_count": attachment_count,
        }
        self.tasks[task_id] = task
        self.assigned_labels.setdefault(task_id, set())
        return task

    def task_projects(self) -> List[Dict[str, Any]]:
        return [{"name": self.project_id, "project_name": self.project_id}]

    def board_snapshot(self, project: str) -> Tuple[List[Dict[str, Any]], Tuple[str, ...]]:
        rows: List[Dict[str, Any]] = []
        for task in self.tasks.values():
            if task.get("project") != project:
                continue
            rows.append(
                {
                    "name": task["name"],
                    "subject": task["subject"],
                    "status": task["status"],
                    "project": project,
                    "attachment_count": task.get("attachment_count", 0),
                    "child_total": len(task.get("children") or []),
                    "agents": list(task.get("agents") or []),
                    "parent_task": task.get("parent_task") or "",
                    "cover_image": task.get("cover_image") or "",
                }
            )
        return rows, tuple(self.columns)

    def task_full(self, name: str, depth: int = 1) -> Dict[str, Any]:
        task = self.tasks.get(name)
        if not task:
            return {"root": {}}
        subtasks = []
        for child_ref in task.get("children") or []:
            child_name = child_ref.get("name")
            if child_name in self.tasks:
                subtasks.append(copy.deepcopy(self.tasks[child_name]))
            else:
                subtasks.append(copy.deepcopy(child_ref))
        root = copy.deepcopy(task)
        root["subtasks"] = subtasks
        root["child_total"] = len(subtasks)
        return {"root": root}

    def add_comment(
        self,
        task: str,
        content: str,
        attachments: Optional[List[Any]] = None,
        parent: str = "",
        meta: str = "",
    ) -> Dict[str, Any]:
        self.comment_counter += 1
        cmt_name = f"cmt-{self.comment_counter}"
        comment_obj = {
            "name": cmt_name,
            "content": content,
            "meta": meta,
            "attachments": list(attachments or []),
        }
        if task in self.tasks:
            self.tasks[task].setdefault("comments", []).append(comment_obj)
        return comment_obj

    def _erp_task_project_id(self, key: str, token: str, task_id: str) -> str:
        return self.tasks.get(task_id, {}).get("project", self.project_id)

    def _erp_task_detail(self, key: str, token: str, task_id: str) -> Dict[str, Any]:
        if task_id not in self.tasks:
            raise RuntimeError(f"ERP task not found: {task_id}")
        return copy.deepcopy(self.tasks[task_id])

    def _erp_create_child_task(
        self,
        key: str,
        token: str,
        parent: str,
        project: str,
        subject: str,
        *,
        status: str = "Cần làm",
        description: str = "",
    ) -> str:
        self.child_counter += 1
        child_id = f"TASK-CHILD-{self.child_counter}"
        child_task = {
            "name": child_id,
            "subject": subject,
            "status": status,
            "project": project,
            "description": description,
            "meta": "",
            "meta_auto": "",
            "cover_image": "",
            "parent_task": parent,
            "children": [],
            "comments": [],
            "agents": [],
            "attachment_count": 0,
        }
        self.tasks[child_id] = child_task
        self.assigned_labels[child_id] = set()
        if parent in self.tasks:
            self.tasks[parent].setdefault("children", []).append({"name": child_id, "subject": subject})
        return child_id

    def _erp_download_attachment_bytes(
        self, key: str, token: str, task_id: str, attachment: Dict[str, Any]
    ) -> Tuple[bytes, str]:
        name = str(attachment.get("name") or "image.jpg")
        return f"fake-image-bytes-for-{name}".encode("utf-8"), "image/jpeg"

    def _erp_attach_file_bytes(
        self,
        key: str,
        token: str,
        task_id: str,
        data: bytes,
        mime: str,
        name: str,
        set_cover: bool,
        parent_comment: str = "",
        comment_text: str = "",
        silent_comment: bool = False,
    ) -> Dict[str, Any]:
        self.comment_counter += 1
        url = f"/files/{name}"
        cmt = {
            "name": f"cmt-{self.comment_counter}",
            "content": comment_text,
            "meta": "",
            "attachments": [{"file_url": url, "file_name": name}],
        }
        if task_id in self.tasks:
            self.tasks[task_id].setdefault("comments", []).append(cmt)
            if set_cover:
                self.tasks[task_id]["cover_image"] = url
        return {"name": name, "url": url}

    def _erp_set_task_cover(
        self, key: str, token: str, task_id: str, data: bytes, mime: str, name: str
    ) -> None:
        if task_id in self.tasks:
            self.tasks[task_id]["cover_image"] = f"/files/{name}"

    def _erp_comment(
        self,
        key: str,
        token: str,
        task_id: str,
        content: str,
        parent_comment: str = "",
        meta: str = "",
    ) -> Dict[str, Any]:
        return self.add_comment(task_id, content, parent=parent_comment, meta=meta)

    def _erp_update_task_meta(
        self,
        key: str,
        token: str,
        task_id: str,
        meta_content: str,
        *,
        project: str = "",
    ) -> Dict[str, Any]:
        if task_id in self.tasks:
            self.tasks[task_id]["meta"] = meta_content
        return {"name": task_id, "meta": meta_content}


class KichBanDot4Tests(unittest.TestCase):
    """Kiểm tra các kịch bản đợt 4 và các luật chưa được che."""

    def setUp(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.patches = [
            patch("flow_web.store.STATE_FILE", self.root / "state.json"),
            patch("flow_web.store.ensure_app_dirs", lambda: self.root.mkdir(parents=True, exist_ok=True)),
            patch("flow_web.service.ensure_app_dirs", lambda: self.root.mkdir(parents=True, exist_ok=True)),
        ]
        for p in self.patches:
            p.start()

        self.store = StateStore()
        self.erp = InMemoryERP()
        self.service = self._create_service(self.store, self.erp)

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        self.tempdir.cleanup()
        self.loop.close()
        asyncio.set_event_loop(None)

    def _create_service(self, store: StateStore, erp: InMemoryERP) -> FlowWebService:
        service = FlowWebService(store)
        self.loop.run_until_complete(
            store.replace_erp_config(
                ERPConfig(
                    api_key="test-api-key",
                    api_secret="test-api-secret",
                    project_id=erp.project_id,
                )
            )
        )
        service._erp_task_project_id = erp._erp_task_project_id
        service._erp_task_detail = erp._erp_task_detail
        service._erp_task_attachment_files = lambda *_a, **_k: []
        service._erp_board_name = lambda *_a, **_k: "Bảng Test"
        service._erp_create_child_task = erp._erp_create_child_task
        service._erp_download_attachment_bytes = erp._erp_download_attachment_bytes
        service._erp_attach_file_bytes = erp._erp_attach_file_bytes
        service._erp_set_task_cover = erp._erp_set_task_cover
        service._erp_add_task_agent = lambda *_a, **_k: None
        service._erp_comment = erp._erp_comment
        service._erp_update_task_meta = erp._erp_update_task_meta
        service._erp_credentials = lambda: ("test-api-key", "test-api-secret")
        service._erp_assert_task_in_project = lambda *_a, **_k: None
        service.sync_erp_skus = AsyncMock(return_value={"written": []})
        return service

    def _create_bot(self, service: FlowWebService, erp: InMemoryERP) -> AgentBot:
        state_file = self.root / f"bot_state_{len(getattr(self, '_bot_states', []))}.json"
        self._bot_states = getattr(self, "_bot_states", []) + [state_file]
        return AgentBot(
            config=AgentBotConfig(
                token="test-bot-token",
                base_url="https://erp.havigroup.llc",
                autorun=True,
                autorun_cooldown_seconds=0,
                max_cards_per_scan=10,
            ),
            client=erp,
            autorun_hook=service._agent_bot_autorun,
            meta_inherit_hook=service.inherit_task_meta,
            state=AgentBotState(path=state_file, bot_user=BOT_USER),
        )

    # ────────────────────────────────────────────────────────────────────────
    # Ca (a) bắt buộc theo brief:
    # Thẻ cha content: có, chạy lượt chép Thuộc tính xong thì cổng ảnh content
    # vẫn mở (vì đọc thẻ cha), còn thẻ con không có content.
    # ────────────────────────────────────────────────────────────────────────
    def test_ca_a_chep_thuoc_tinh_khong_chep_content_va_cong_content_van_mo(self) -> None:
        parent_id = "TASK-PARENT-DOT4-A"
        child_id = "TASK-CHILD-DOT4-A"

        # Thẻ cha có đủ 4 thuộc tính và content: có
        parent_meta = (
            "product_type: Khăn tay cô dâu thêu tay\n"
            "product_group: Thêu tay\n"
            "fulfillment: HaviGroup\n"
            "sales_channel: Etsy\n"
            "content: có"
        )
        self.erp.add_task(
            parent_id,
            subject="Idea cha",
            meta=parent_meta,
            agents=[BOT_USER],
            children=[{"name": child_id, "subject": "Idea con"}],
        )
        # Thẻ con ban đầu trống thuộc tính
        self.erp.add_task(
            child_id,
            subject="Idea con",
            meta="",
            parent_task=parent_id,
        )

        bot = self._create_bot(self.service, self.erp)

        # 1. Chạy lượt chép Thuộc tính (meta_inherit_pass)
        tree = self.erp.task_full(parent_id)
        inherited = bot.meta_inherit_pass(tree, BOT_USER)

        self.assertEqual(1, len(inherited), "Phải chép thuộc tính cho 1 thẻ con")
        self.assertEqual(child_id, inherited[0]["task"])
        # Thuộc tính được chép phải gồm 4 thuộc tính, TUYỆT ĐỐI KHÔNG có content
        copied_keys = set(inherited[0]["keys"])
        self.assertEqual(
            {"fulfillment", "product_group", "product_type", "sales_channel"},
            copied_keys,
            "Chỉ chép 4 thuộc tính hợp lệ",
        )
        self.assertNotIn("content", copied_keys, "Tuyệt đối không chép content từ cha xuống con")

        # 2. Kiểm tra bản ghi của thẻ con trên ERP: không có trường content
        child_task = self.erp.tasks[child_id]
        child_meta = task_meta(child_task)
        self.assertEqual("Khăn tay cô dâu thêu tay", child_meta.get("product_type"))
        self.assertEqual("Thêu tay", child_meta.get("product_group"))
        self.assertEqual("HaviGroup", child_meta.get("fulfillment"))
        self.assertEqual("Etsy", child_meta.get("sales_channel"))
        self.assertEqual("", child_meta.get("content"), "Thẻ con không được có content")
        self.assertNotIn("content", child_meta.attributes, "Thẻ con không được có content trong attributes")
        self.assertNotIn("content:", child_task["meta"])

        # 3. Kiểm tra cổng ảnh content:
        # Cổng ảnh content đối với thẻ cha: VẪN MỞ vì đọc thẻ cha!
        parent_detail = self.erp.tasks[parent_id]
        self.assertTrue(
            self.service._erp_idea_content_enabled(parent_detail),
            "Hàm _erp_idea_content_enabled trên thẻ cha phải trả về True",
        )
        gate_reason = self.service._erp_idea_gate_reason(parent_detail)
        self.assertEqual("", gate_reason, f"Cổng ảnh content của thẻ cha phải mở (gate_reason rỗng), nhưng nhận: '{gate_reason}'")

        # 4. Kiểm tra đối chứng: nếu kiểm tra trên thẻ con thì content không bật
        # (chứng minh cổng mở là do đọc thẻ cha, không phải do thẻ con)
        self.assertFalse(
            self.service._erp_idea_content_enabled(child_task),
            "Thẻ con không có content nên _erp_idea_content_enabled trên thẻ con phải trả về False",
        )

    # ────────────────────────────────────────────────────────────────────────
    # Ca (b) bắt buộc theo brief:
    # Thẻ cha viết content: Có, co, yes đều mở cổng; không và ô trống thì đóng.
    # Dùng hàm thật _erp_idea_gate_reason / _erp_idea_content_enabled trong flow_web/service.py.
    # ────────────────────────────────────────────────────────────────────────
    def test_ca_b_cac_cach_viet_content_dong_mo_cong_that(self) -> None:
        # Nhóm mở cổng: Có, co, yes (và các biến thể hoa/thường, khoảng trắng)
        mo_cong_cases = ["Có", "có", "co", "Co", "CÓ", "yes", "Yes", "YES", " Có ", " co "]
        for val in mo_cong_cases:
            with self.subTest(mo_cong=val):
                parent_detail = {
                    "name": "TASK-PARENT-TEST-OPEN",
                    "meta": f"{DU_BON_KHOA}\ncontent: {val}",
                }
                # _erp_idea_content_enabled phải trả về True
                self.assertTrue(
                    self.service._erp_idea_content_enabled(parent_detail),
                    f"content: '{val}' lẽ ra phải được _erp_idea_content_enabled công nhận là True",
                )
                # _erp_idea_gate_reason phải trả về chuỗi rỗng "" (cổng mở hoàn toàn)
                reason = self.service._erp_idea_gate_reason(parent_detail)
                self.assertEqual(
                    "",
                    reason,
                    f"content: '{val}' lẽ ra phải mở cổng (_erp_idea_gate_reason == ''), nhưng nhận: '{reason}'",
                )

        # Nhóm đóng cổng: không (và các biến thể khác)
        dong_cong_cases = ["Không", "không", "khong", "no", "false", "0", "chưa", "k", "KO"]
        for val in dong_cong_cases:
            with self.subTest(dong_cong=val):
                parent_detail = {
                    "name": "TASK-PARENT-TEST-CLOSED",
                    "meta": f"{DU_BON_KHOA}\ncontent: {val}",
                }
                # _erp_idea_content_enabled phải trả về False
                self.assertFalse(
                    self.service._erp_idea_content_enabled(parent_detail),
                    f"content: '{val}' lẽ ra phải được _erp_idea_content_enabled coi là False",
                )
                # _erp_idea_gate_reason phải báo lý do đóng cổng
                reason = self.service._erp_idea_gate_reason(parent_detail)
                self.assertIn(
                    "content: Có",
                    reason,
                    f"content: '{val}' phải đóng cổng và báo lý do chưa khai content: Có, nhận: '{reason}'",
                )

        # Nhóm đóng cổng: ô trống hoặc không khai dòng content
        trong_cases = [
            ("content_trong", f"{DU_BON_KHOA}\ncontent:"),
            ("content_khoang_trang", f"{DU_BON_KHOA}\ncontent:   "),
            ("khong_co_dong_content", DU_BON_KHOA),
        ]
        for name, meta_val in trong_cases:
            with self.subTest(trong=name):
                parent_detail = {
                    "name": "TASK-PARENT-TEST-EMPTY",
                    "meta": meta_val,
                }
                self.assertFalse(
                    self.service._erp_idea_content_enabled(parent_detail),
                    f"Trường hợp {name} phải có _erp_idea_content_enabled là False",
                )
                reason = self.service._erp_idea_gate_reason(parent_detail)
                self.assertIn(
                    "content: Có",
                    reason,
                    f"Trường hợp {name} phải đóng cổng và báo lý do chưa khai content: Có, nhận: '{reason}'",
                )

    # ────────────────────────────────────────────────────────────────────────
    # Ca bổ sung kiểm tra Luật 1:
    # "Tạo idea, rồi Chuyển thành task cha"
    # Thẻ ban đầu là idea đơn (chưa có con), sau đó chuyển thành task cha
    # (gắn bot, đính ảnh trong bình luận, khai đủ 4 thuộc tính).
    # Bot nhận diện đúng là thẻ cha, không nhầm lẫn giữa thẻ cha và con.
    # ────────────────────────────────────────────────────────────────────────
    def test_luat_1_tao_idea_roi_chuyen_thanh_task_cha(self) -> None:
        idea_id = "TASK-SELLER-IDEA-1"

        # Bước 1.1: Seller mới tạo idea đơn: chưa có bot, chưa có ảnh, chưa chuyển thành task cha
        self.erp.add_task(
            idea_id,
            subject="Idea mới tạo",
            meta=DU_BON_KHOA,
            agents=[],
            comments=[],
            children=[],
        )
        bot = self._create_bot(self.service, self.erp)

        # candidate_tasks không chọn thẻ này vì chưa được giao (chưa có bot)
        candidates1 = bot.candidate_tasks([self.erp.project_id], BOT_USER)
        self.assertNotIn(idea_id, [c.get("name") for c in candidates1])

        # Bước 1.2: Seller "Chuyển thành task cha":
        # - Gắn bot vào thẻ
        # - Thả ảnh ý tưởng vào bình luận để chuẩn bị sinh thẻ con
        self.erp.tasks[idea_id]["agents"] = [{"bot_user": BOT_USER}]
        self.erp.add_comment(
            idea_id,
            "Ảnh mẫu 1",
            attachments=[{"file_url": "/files/m1.jpg", "file_name": "m1.jpg"}],
        )
        self.erp.add_comment(
            idea_id,
            "Ảnh mẫu 2",
            attachments=[{"file_url": "/files/m2.jpg", "file_name": "m2.jpg"}],
        )
        self.erp.tasks[idea_id]["attachment_count"] = 2

        # candidate_tasks nhận diện đúng thẻ cha này
        candidates2 = bot.candidate_tasks([self.erp.project_id], BOT_USER)
        candidate_ids = [c.get("name") for c in candidates2]
        self.assertIn(idea_id, candidate_ids, "Bot phải nhận diện được thẻ cha sau khi chuyển và gắn bot")

        # Chạy autorun_pass: bot tách đúng 2 thẻ con
        with patch.object(self.service, "_run_flow_job", new_callable=AsyncMock):
            tree = self.erp.task_full(idea_id)
            tree[BOARD_ROW_KEY] = candidates2[0]
            outcome = self.loop.run_until_complete(bot.autorun_pass(tree))

        self.assertIsNotNone(outcome)
        created = outcome.get("result", {}).get("created", [])
        self.assertEqual(2, len(created), "Phải tách ra đúng 2 idea con từ bình luận")
        self.assertEqual(2, len(self.erp.tasks[idea_id]["children"]))

        # Các thẻ con sinh ra có parent_task trỏ về thẻ cha
        for child_ref in created:
            c_id = child_ref["task_id"]
            self.assertEqual(idea_id, self.erp.tasks[c_id]["parent_task"])

    # ────────────────────────────────────────────────────────────────────────
    # Ca bổ sung kiểm tra Luật 6:
    # "Bot không ghi content thay seller"
    # - Khi thẻ cha KHÔNG khai content, bot chạy autorun và chép thuộc tính
    #   tuyệt đối không tự ý ghi content lên thẻ cha lẫn thẻ con.
    # ────────────────────────────────────────────────────────────────────────
    def test_luat_6_bot_khong_ghi_content_thay_seller(self) -> None:
        parent_id = "TASK-PARENT-LUAT6"
        child_id = "TASK-CHILD-LUAT6"

        # Thẻ cha đủ 4 thuộc tính nhưng cố ý KHÔNG khai content
        self.erp.add_task(
            parent_id,
            subject="Idea cha không content",
            meta=DU_BON_KHOA,
            agents=[BOT_USER],
            children=[{"name": child_id, "subject": "Idea con"}],
        )
        self.erp.add_task(
            child_id,
            subject="Idea con",
            meta="",
            parent_task=parent_id,
        )

        bot = self._create_bot(self.service, self.erp)

        # Chép thuộc tính
        tree = self.erp.task_full(parent_id)
        bot.meta_inherit_pass(tree, BOT_USER)

        # Kiểm tra thẻ cha: không bị bot chèn content
        parent_meta_after = task_meta(self.erp.tasks[parent_id])
        self.assertEqual("", parent_meta_after.get("content"), "Bot không được tự ghi content lên thẻ cha")
        self.assertNotIn("content", parent_meta_after.attributes, "Thẻ cha không có content trong attributes")
        self.assertNotIn("content", self.erp.tasks[parent_id]["meta"])

        # Kiểm tra thẻ con: không bị bot chèn content
        child_meta_after = task_meta(self.erp.tasks[child_id])
        self.assertEqual("", child_meta_after.get("content"), "Bot không được tự ghi content lên thẻ con")
        self.assertNotIn("content", child_meta_after.attributes, "Thẻ con không có content trong attributes")
        self.assertNotIn("content", self.erp.tasks[child_id]["meta"])

        # Cổng content vẫn phải đóng
        self.assertFalse(self.service._erp_idea_content_enabled(self.erp.tasks[parent_id]))
        self.assertIn("content: Có", self.service._erp_idea_gate_reason(self.erp.tasks[parent_id]))


if __name__ == "__main__":
    unittest.main()
