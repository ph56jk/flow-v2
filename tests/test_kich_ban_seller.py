"""Kịch bản đầu-cuối quy trình seller: idea → idea con → ảnh content → DONE.

Kiểm tra quy trình seller qua nhiều lượt quét của bot trên một ERP giả trong bộ nhớ:
thẻ, bình luận, thuộc tính, nhãn, tệp đính kèm. Không gọi mạng.
Mỗi lượt gọi đúng đường code thật:
- AgentBot.autorun_pass / candidate_tasks (flow_web/agent_bot.py)
- _agent_bot_autorun (flow_web/service.py)
- repair_erp_idea_children (flow_web/service.py)
- _enqueue_erp_idea_jobs_unlocked (flow_web/service.py)
- resume_interrupted_erp_idea_jobs (flow_web/service.py)
- _archive_erp_artifacts (flow_web/service.py)
- _erp_idea_mark_done (flow_web/service.py)
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
from flow_web.erp_meta import parse_meta_block
from flow_web.schemas import (
    CreateJobRequest,
    ERPConfig,
    JobArtifact,
    JobRecord,
)
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
        self.label_mutation_calls: List[Tuple[str, str]] = []
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

    # ── Các API cho AgentBotClient ──────────────────────────────────────────

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

    def add_task_agent(self, task_id: str, bot_user: str) -> Dict[str, Any]:
        task = self.tasks.get(task_id)
        if task:
            agents = task.setdefault("agents", [])
            if not any(item.get("bot_user") == bot_user for item in agents):
                agents.append({"bot_user": bot_user})
        return {}

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

    def delete_comment(self, task: str, comment_name: str) -> Dict[str, Any]:
        if task in self.tasks:
            comments = self.tasks[task].get("comments", [])
            self.tasks[task]["comments"] = [c for c in comments if c.get("name") != comment_name]
        return {}

    # ── Các API cho FlowWebService ──────────────────────────────────────────

    def _erp_task_project_id(self, key: str, token: str, task_id: str) -> str:
        return self.tasks.get(task_id, {}).get("project", self.project_id)

    def _erp_task_detail(self, key: str, token: str, task_id: str) -> Dict[str, Any]:
        if task_id not in self.tasks:
            raise RuntimeError(f"ERP task not found: {task_id}")
        task = copy.deepcopy(self.tasks[task_id])
        labels = sorted(self.assigned_labels.get(task_id, set()))
        if labels:
            existing_auto = task.get("meta_auto") or ""
            task["meta_auto"] = f"_labels: [{', '.join(labels)}]\n{existing_auto}".strip()
        return task

    def _erp_task_attachment_files(self, key: str, token: str, task_id: str) -> List[Dict[str, Any]]:
        return list(self.task_attachments.get(task_id, []))

    def _erp_board_name(self, key: str, token: str, project_id: str, task_id: str) -> str:
        return "Bảng Idea Test"

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

    def _erp_attach_url(
        self,
        key: str,
        token: str,
        task_id: str,
        url: str,
        name: str,
        set_cover: bool = False,
        parent_comment: str = "",
    ) -> Dict[str, Any]:
        self.comment_counter += 1
        cmt = {
            "name": f"cmt-{self.comment_counter}",
            "content": "",
            "meta": "",
            "attachments": [{"file_url": url, "file_name": name}],
        }
        if task_id in self.tasks:
            self.tasks[task_id].setdefault("comments", []).append(cmt)
            if set_cover:
                self.tasks[task_id]["cover_image"] = url
        return {"id": url, "name": name, "url": url}

    def _erp_set_task_cover(
        self, key: str, token: str, task_id: str, data: bytes, mime: str, name: str
    ) -> None:
        if task_id in self.tasks:
            self.tasks[task_id]["cover_image"] = f"/files/{name}"

    def _erp_add_task_agent(self, key: str, token: str, task_id: str, bot_user: str) -> None:
        self.add_task_agent(task_id, bot_user)

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

    def _erp_add_task_label(self, key: str, token: str, task_id: str, label: str) -> Dict[str, Any]:
        target = str(task_id or "").strip()
        self.label_mutation_calls.append((target, label))
        self.assigned_labels.setdefault(target, set()).add(label)
        if target in self.tasks:
            labels = sorted(self.assigned_labels[target])
            self.tasks[target]["meta_auto"] = f"_labels: [{', '.join(labels)}]"
        return {"name": target, "label": label}

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

    async def _erp_advance_task_status(
        self, job_id: str, task_id: str, target_status: str
    ) -> bool:
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = target_status
            return True
        return False


class KichBanSellerTestCase(unittest.TestCase):
    """Bộ kiểm tra quy trình seller qua nhiều lượt quét trên ERP giả trong bộ nhớ."""

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
        service._erp_task_attachment_files = erp._erp_task_attachment_files
        service._erp_board_name = erp._erp_board_name
        service._erp_create_child_task = erp._erp_create_child_task
        service._erp_download_attachment_bytes = erp._erp_download_attachment_bytes
        service._erp_attach_file_bytes = erp._erp_attach_file_bytes
        service._erp_attach_url = erp._erp_attach_url
        service._erp_set_task_cover = erp._erp_set_task_cover
        service._erp_add_task_agent = erp._erp_add_task_agent
        service._erp_comment = erp._erp_comment
        service._erp_add_task_label = erp._erp_add_task_label
        service._erp_update_task_meta = erp._erp_update_task_meta
        service._erp_advance_task_status = erp._erp_advance_task_status
        service._erp_assert_task_in_project = lambda *_args, **_kwargs: None
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
            state=AgentBotState(path=state_file, bot_user=BOT_USER),
        )

    async def _run_bot_scan(
        self,
        bot: AgentBot,
        erp: InMemoryERP,
        target_task_id: str = "",
    ) -> List[Dict[str, Any]]:
        """Chạy đúng đường code quét của bot: candidate_tasks -> task_full -> autorun_pass."""
        candidates = bot.candidate_tasks([erp.project_id], BOT_USER)
        if target_task_id:
            candidates = [c for c in candidates if str(c.get("name") or "") == target_task_id]

        outcomes: List[Dict[str, Any]] = []
        for task_row in candidates:
            task_id = str(task_row.get("name") or "")
            tree = erp.task_full(task_id)
            tree[BOARD_ROW_KEY] = task_row
            outcome = await bot.autorun_pass(tree)
            if outcome is not None:
                outcomes.append(outcome)
        return outcomes

    # ────────────────────────────────────────────────────────────────────────
    # Kịch bản 1: Thẻ cha đủ 4 thuộc tính, 3 ảnh cmt, KHÔNG content
    # → 3 idea con, ảnh làm đại diện, 0 job ảnh, 0 bình luận nhắc.
    # ────────────────────────────────────────────────────────────────────────
    def test_01_the_cha_du_bon_thuoc_tinh_khong_content_tach_3_con_khong_job_khong_nhac(self) -> None:
        parent_id = "TASK-PARENT-1"
        comments = [
            {"name": "cmt-drop-1", "content": "", "attachments": [{"file_url": "/files/drop-1.jpg", "file_name": "drop-1.jpg"}]},
            {"name": "cmt-drop-2", "content": "", "attachments": [{"file_url": "/files/drop-2.jpg", "file_name": "drop-2.jpg"}]},
            {"name": "cmt-drop-3", "content": "", "attachments": [{"file_url": "/files/drop-3.jpg", "file_name": "drop-3.jpg"}]},
        ]
        self.erp.add_task(
            parent_id,
            subject="Idea Khăn tay",
            cover_image="/files/cover-sp.jpg",
            meta=DU_BON_KHOA,
            comments=comments,
            agents=[BOT_USER],
            attachment_count=4,
        )
        bot = self._create_bot(self.service, self.erp)

        with patch.object(self.service, "_run_flow_job", new_callable=AsyncMock) as mock_run:
            outcomes = self.loop.run_until_complete(self._run_bot_scan(bot, self.erp, parent_id))

        self.assertEqual(1, len(outcomes))
        result = outcomes[0].get("result") or {}
        created = result.get("created") or []
        queued = result.get("queued") or []

        # Đúng 3 idea con được tạo
        self.assertEqual(3, len(created))
        self.assertEqual(3, len(self.erp.tasks[parent_id]["children"]))

        # Mỗi con lấy đúng ảnh của nó làm ảnh đại diện
        child_tasks = [self.erp.tasks[item["task_id"]] for item in created]
        self.assertEqual("/files/drop-1.jpg", child_tasks[0]["cover_image"])
        self.assertEqual("/files/drop-2.jpg", child_tasks[1]["cover_image"])
        self.assertEqual("/files/drop-3.jpg", child_tasks[2]["cover_image"])

        # 0 job ảnh được xếp hoặc chạy
        self.assertEqual([], queued)
        self.assertFalse(result.get("content"))
        mock_run.assert_not_awaited()

        # 0 bình luận nhắc thiếu thuộc tính
        parent_comments = self.erp.tasks[parent_id].get("comments") or []
        reminder_comments = [
            c for c in parent_comments
            if FlowWebService.ERP_IDEA_META_NOTE_MARK in (str(c.get("meta") or "") + str(c.get("content") or ""))
        ]
        self.assertEqual([], reminder_comments)

    # ────────────────────────────────────────────────────────────────────────
    # Kịch bản 2: Thiếu thuộc tính → đúng 1 bình luận nhắc liệt kê khoá thiếu.
    # Lượt 2: không nhắc thêm. Restart: không nhắc thêm. Khai đủ: lượt sau tách.
    # ────────────────────────────────────────────────────────────────────────
    def test_02_thieu_thuoc_tinh_nhac_1_lan_restart_khong_nhac_lai_khai_du_thi_tach(self) -> None:
        parent_id = "TASK-PARENT-2"
        thieu_meta = "product_type: Khăn tay cô dâu\nfulfillment: HaviGroup"
        comments = [
            {"name": "cmt-drop-1", "content": "", "attachments": [{"file_url": "/files/drop-1.jpg", "file_name": "drop-1.jpg"}]},
        ]
        self.erp.add_task(
            parent_id,
            subject="Idea Thiếu Thuộc Tính",
            cover_image="/files/cover-sp.jpg",
            meta=thieu_meta,
            comments=comments,
            agents=[BOT_USER],
            attachment_count=2,
        )
        bot = self._create_bot(self.service, self.erp)

        # Lượt 1: Quét khi thiếu thuộc tính
        outcomes1 = self.loop.run_until_complete(self._run_bot_scan(bot, self.erp, parent_id))
        result1 = outcomes1[0].get("result") or {}
        self.assertTrue(result1.get("notified"))
        self.assertEqual(["product_group", "sales_channel"], result1.get("missing_meta"))

        def get_reminders():
            return [
                c for c in self.erp.tasks[parent_id].get("comments") or []
                if FlowWebService.ERP_IDEA_META_NOTE_MARK in (str(c.get("meta") or "") + str(c.get("content") or ""))
            ]

        reminders = get_reminders()
        self.assertEqual(1, len(reminders))
        self.assertIn("product_group", reminders[0]["content"])
        self.assertIn("sales_channel", reminders[0]["content"])
        self.assertNotIn("product_type", reminders[0]["content"])

        # Lượt 2: Quét lại trên cùng service -> Không nhắc thêm
        outcomes2 = self.loop.run_until_complete(self._run_bot_scan(bot, self.erp, parent_id))
        result2 = outcomes2[0].get("result") or {}
        self.assertFalse(result2.get("notified"))
        self.assertEqual(1, len(get_reminders()))

        # "Restart": tạo service mới và bot mới trên cùng ERP giả
        service_restarted = self._create_service(self.store, self.erp)
        bot_restarted = self._create_bot(service_restarted, self.erp)
        outcomes3 = self.loop.run_until_complete(self._run_bot_scan(bot_restarted, self.erp, parent_id))
        result3 = outcomes3[0].get("result") or {}
        self.assertFalse(result3.get("notified"))
        self.assertEqual(1, len(get_reminders()))

        # Khai đủ thuộc tính
        self.erp.tasks[parent_id]["meta"] = DU_BON_KHOA
        outcomes4 = self.loop.run_until_complete(self._run_bot_scan(bot_restarted, self.erp, parent_id))
        result4 = outcomes4[0].get("result") or {}
        self.assertEqual(1, len(result4.get("created") or []))
        self.assertEqual(1, len(self.erp.tasks[parent_id]["children"]))

    # ────────────────────────────────────────────────────────────────────────
    # Kịch bản 3: content: "Có" → mỗi idea con có job theo prompt.
    # Thử các cách gõ: "Có", "có", "CÓ", "co", "Co", " Có ", "Yes", "Không", "".
    # ────────────────────────────────────────────────────────────────────────
    def test_03_content_co_tao_job_thu_cac_cach_seller_go(self) -> None:
        affirmative_cases = ["Có", "có", "CÓ", "co", "Co", " Có ", "Yes"]
        negative_cases = ["Không", ""]

        for val in affirmative_cases:
            with self.subTest(affirmative=val):
                parent_id = f"TASK-PARENT-3-AFF-{val.strip()}"
                comments = [
                    {"name": "cmt-1", "content": "", "attachments": [{"file_url": "/files/drop-1.jpg", "file_name": "drop-1.jpg"}]},
                ]
                self.erp.add_task(
                    parent_id,
                    subject="Idea Khăn tay",
                    cover_image="/files/cover.jpg",
                    meta=f"{DU_BON_KHOA}\ncontent: {val}",
                    comments=comments,
                    agents=[BOT_USER],
                    attachment_count=2,
                )
                bot = self._create_bot(self.service, self.erp)
                with patch.object(self.service, "_run_flow_job", new_callable=AsyncMock):
                    outcomes = self.loop.run_until_complete(self._run_bot_scan(bot, self.erp, parent_id))

                res = outcomes[0].get("result") or {}
                self.assertTrue(
                    self.service._erp_idea_content_enabled(self.erp.tasks[parent_id]),
                    f"Hàm _erp_idea_content_enabled lẽ ra phải chấp nhận cách gõ content: '{val}'",
                )
                self.assertNotEqual(res.get("content"), False)
                self.assertTrue(len(res.get("queued") or []) >= 1, f"Lẽ ra phải có job được xếp với content: '{val}'")

        for val in negative_cases:
            with self.subTest(negative=val):
                parent_id = f"TASK-PARENT-3-NEG-{val.strip() or 'EMPTY'}"
                comments = [
                    {"name": "cmt-1", "content": "", "attachments": [{"file_url": "/files/drop-1.jpg", "file_name": "drop-1.jpg"}]},
                ]
                meta_content = f"{DU_BON_KHOA}\ncontent: {val}" if val else DU_BON_KHOA
                self.erp.add_task(
                    parent_id,
                    subject="Idea Khăn tay",
                    cover_image="/files/cover.jpg",
                    meta=meta_content,
                    comments=comments,
                    agents=[BOT_USER],
                    attachment_count=2,
                )
                bot = self._create_bot(self.service, self.erp)
                with patch.object(self.service, "_run_flow_job", new_callable=AsyncMock):
                    outcomes = self.loop.run_until_complete(self._run_bot_scan(bot, self.erp, parent_id))

                res = outcomes[0].get("result") or {}
                self.assertFalse(self.service._erp_idea_content_enabled(self.erp.tasks[parent_id]))
                self.assertFalse(res.get("content"))
                self.assertEqual([], res.get("queued") or [])

    # ────────────────────────────────────────────────────────────────────────
    # Kịch bản 4: Job xong, duyệt đủ ảnh lên thẻ → assignTaskLabel gọi đúng 1 lần
    # nhãn DONE. Duyệt thiếu → không gắn. Archive lần hai → không gắn lại.
    # ────────────────────────────────────────────────────────────────────────
    def test_04_job_xong_duyet_du_gan_done_1_lan_duyet_thieu_khong_archive_lan_2_khong_gan_lai(self) -> None:
        child_id = "TASK-CHILD-4"
        parent_id = "TASK-PARENT-4"
        self.erp.add_task(child_id, subject="Idea Con", parent_task=parent_id)

        artifacts = [
            JobArtifact(media_name="idea-0.jpg", url="https://media.example/idea-0.jpg"),
            JobArtifact(media_name="idea-1.jpg", url="https://media.example/idea-1.jpg"),
        ]
        job = JobRecord(
            type="image",
            title=f"Idea 1 ({child_id})",
            result={"dashboard_approvals": {"0": {"status": "approved"}, "1": {"status": "approved"}}},
        )
        self.loop.run_until_complete(self.store.add_job(job))
        req = CreateJobRequest(
            type="image",
            erp_enabled=True,
            erp_project_id=PROJ_ID,
            erp_task_id=parent_id,
            erp_source_task_id=parent_id,
            erp_output_task_id=child_id,
            count=2,
        )

        with patch.object(self.service, "_erp_add_task_label", wraps=self.erp._erp_add_task_label) as label_mock:
            # Lần 1: Duyệt đủ 2/2 ảnh
            res1 = self.loop.run_until_complete(self.service._archive_erp_artifacts(job.id, req, artifacts))
            self.assertEqual(1, label_mock.call_count)
            self.assertTrue(res1["done_label"]["marked"])
            self.assertEqual(child_id, res1["done_label"]["task_id"])

            # Cập nhật kết quả archive vào job.result giống pipeline thật
            latest_job = self.store.get_job(job.id)
            updated_res = dict(latest_job.result or {})
            updated_res["erp"] = res1
            self.loop.run_until_complete(self.store.patch_job(job.id, result=updated_res))

            # Lần 2: Chạy lại archive lần hai → không gắn lại!
            res2 = self.loop.run_until_complete(self.service._archive_erp_artifacts(job.id, req, artifacts))
            self.assertEqual(1, label_mock.call_count, "Chạy lại archive lần 2 không được gọi assignTaskLabel lại!")
            self.assertFalse(res2["done_label"]["marked"])
            self.assertIn("DONE", res2["done_label"]["reason"])

        # Duyệt thiếu: 1 approved, 1 rejected
        child_id_thieu = "TASK-CHILD-4-THIEU"
        self.erp.add_task(child_id_thieu, subject="Idea Thiếu", parent_task=parent_id)
        job_thieu = JobRecord(
            type="image",
            title=f"Idea Thieu ({child_id_thieu})",
            result={"dashboard_approvals": {"0": {"status": "approved"}, "1": {"status": "rejected"}}},
        )
        self.loop.run_until_complete(self.store.add_job(job_thieu))
        req_thieu = CreateJobRequest(
            type="image",
            erp_enabled=True,
            erp_project_id=PROJ_ID,
            erp_task_id=parent_id,
            erp_source_task_id=parent_id,
            erp_output_task_id=child_id_thieu,
            count=2,
        )
        with patch.object(self.service, "_erp_add_task_label", wraps=self.erp._erp_add_task_label) as label_mock_thieu:
            res_thieu = self.loop.run_until_complete(self.service._archive_erp_artifacts(job_thieu.id, req_thieu, artifacts))
            label_mock_thieu.assert_not_called()
            self.assertFalse(res_thieu["done_label"]["marked"])
            self.assertIn("1/2", res_thieu["done_label"]["reason"])

    def test_04_archive_khong_patch_job_va_khong_de_truong_khac_trong_result(self) -> None:
        """_archive_erp_artifacts KHÔNG gọi store.patch_job ghi đè result.

        Nếu một trường khác được ghi vào job.result trong lúc archive đang chạy
        (giả lập tác vụ đồng thời gọi store.patch_job), thì sau archive trường đó
        vẫn còn nguyên vẹn, không bị ảnh chụp job.result cũ đè mất.
        """
        child_id = "TASK-CHILD-4-ISOLATE"
        parent_id = "TASK-PARENT-4-ISOLATE"
        self.erp.add_task(child_id, subject="Idea Con Isolate", parent_task=parent_id)

        artifacts = [
            JobArtifact(media_name="idea-0.jpg", url="https://media.example/idea-0.jpg"),
        ]
        job = JobRecord(
            type="image",
            title=f"Idea ({child_id})",
            result={
                "dashboard_approvals": {"0": {"status": "approved"}},
                "keep_me": "original_value",
            },
        )
        self.loop.run_until_complete(self.store.add_job(job))
        req = CreateJobRequest(
            type="image",
            erp_enabled=True,
            erp_project_id=PROJ_ID,
            erp_task_id=parent_id,
            erp_source_task_id=parent_id,
            erp_output_task_id=child_id,
            count=1,
        )

        def mock_add_label(*args: Any, **kwargs: Any) -> None:
            self.erp._erp_add_task_label(*args, **kwargs)
            asyncio.run_coroutine_threadsafe(
                self.store.patch_job(job.id, result={**(self.store.get_job(job.id).result or {}), "concurrent_key": "concurrent_val"}),
                self.loop,
            ).result()

        with patch.object(self.service, "_erp_add_task_label", side_effect=mock_add_label):
            with patch.object(self.store, "patch_job", wraps=self.store.patch_job) as patch_mock:
                res = self.loop.run_until_complete(
                    self.service._archive_erp_artifacts(job.id, req, artifacts)
                )
                self.assertEqual(1, patch_mock.call_count)

        latest = self.store.get_job(job.id)
        self.assertEqual("original_value", latest.result.get("keep_me"))
        self.assertEqual("concurrent_val", latest.result.get("concurrent_key"))


    # ────────────────────────────────────────────────────────────────────────
    # Kịch bản 5: Restart giữa chừng: job của thẻ cha không content bị bỏ;
    # thẻ cha có content thì job chạy tiếp; không job nào bị nhân đôi.
    # ────────────────────────────────────────────────────────────────────────
    def test_05_restart_giua_chung_bo_job_khong_content_chay_tiep_job_co_content_khong_nhan_doi(self) -> None:
        parent_no_content = "TASK-PARENT-5-NO"
        parent_with_content = "TASK-PARENT-5-YES"
        child_no = "TASK-CHILD-5-NO"
        child_yes = "TASK-CHILD-5-YES"

        self.erp.add_task(parent_no_content, meta=DU_BON_KHOA)
        self.erp.add_task(parent_with_content, meta=CO_CONTENT)
        self.erp.add_task(child_no, parent_task=parent_no_content)
        self.erp.add_task(child_yes, parent_task=parent_with_content)

        job_no = JobRecord(
            type="image",
            status="running",
            title=f"Idea No ({child_no})",
            input={
                "type": "image",
                "prompt": "khăn tay",
                "count": 2,
                "erp_enabled": True,
                "erp_task_id": parent_no_content,
                "erp_source_task_id": parent_no_content,
                "erp_output_task_id": child_no,
            },
        )
        job_yes = JobRecord(
            type="image",
            status="running",
            title=f"Idea Yes ({child_yes})",
            input={
                "type": "image",
                "prompt": "khăn tay hoa",
                "count": 2,
                "erp_enabled": True,
                "erp_task_id": parent_with_content,
                "erp_source_task_id": parent_with_content,
                "erp_output_task_id": child_yes,
            },
        )
        self.loop.run_until_complete(self.store.add_job(job_no))
        self.loop.run_until_complete(self.store.add_job(job_yes))

        # Khởi động lại: Store mới đánh dấu mọi job đang chạy là 'interrupted'
        store_restarted = StateStore()
        service_restarted = self._create_service(store_restarted, self.erp)

        with patch.object(service_restarted, "_run_erp_idea_jobs", new_callable=AsyncMock) as run_batch:
            outcome = self.loop.run_until_complete(service_restarted.resume_interrupted_erp_idea_jobs())

        # Thẻ cha không content bị bỏ
        skipped_ids = [item["task_id"] for item in outcome["skipped"]]
        self.assertIn(child_no, skipped_ids)
        self.assertEqual("interrupted", store_restarted.get_job(job_no.id).status)

        # Thẻ cha có content được xếp lại và chạy tiếp
        resumed_ids = [item["task_id"] for item in outcome["resumed"]]
        self.assertIn(child_yes, resumed_ids)
        run_batch.assert_called_once()

        # Gọi lại resume lần 2: Không job nào bị nhân đôi
        with patch.object(service_restarted, "_run_erp_idea_jobs", new_callable=AsyncMock) as run_batch2:
            outcome2 = self.loop.run_until_complete(service_restarted.resume_interrupted_erp_idea_jobs())
        self.assertEqual([], outcome2["resumed"])
        run_batch2.assert_not_called()

    # ────────────────────────────────────────────────────────────────────────
    # Kịch bản 6: Quét lặp 3 lượt liên tiếp → không tạo idea con trùng.
    # Seller thêm bình luận MỚI 2 ảnh → chỉ tạo thêm 2 con.
    # ────────────────────────────────────────────────────────────────────────
    def test_06_quet_lap_3_luot_khong_trung_them_2_anh_moi_chi_tao_them_2_con(self) -> None:
        parent_id = "TASK-PARENT-6"
        initial_comments = [
            {"name": "cmt-1", "content": "", "attachments": [{"file_url": "/files/pic-1.jpg", "file_name": "pic-1.jpg"}]},
            {"name": "cmt-2", "content": "", "attachments": [{"file_url": "/files/pic-2.jpg", "file_name": "pic-2.jpg"}]},
        ]
        self.erp.add_task(
            parent_id,
            subject="Idea Quét Lặp",
            cover_image="/files/cover-sp.jpg",
            meta=DU_BON_KHOA,
            comments=initial_comments,
            agents=[BOT_USER],
            attachment_count=3,
        )
        bot = self._create_bot(self.service, self.erp)

        # Lượt 1: Tạo đúng 2 thẻ con
        out1 = self.loop.run_until_complete(self._run_bot_scan(bot, self.erp, parent_id))
        created1 = out1[0]["result"]["created"]
        self.assertEqual(2, len(created1))
        self.assertEqual(2, len(self.erp.tasks[parent_id]["children"]))

        # Lượt 2: Không tạo thêm
        out2 = self.loop.run_until_complete(self._run_bot_scan(bot, self.erp, parent_id))
        created2 = out2[0]["result"]["created"]
        self.assertEqual([], created2)
        self.assertEqual(2, len(self.erp.tasks[parent_id]["children"]))

        # Lượt 3: Không tạo thêm
        out3 = self.loop.run_until_complete(self._run_bot_scan(bot, self.erp, parent_id))
        created3 = out3[0]["result"]["created"]
        self.assertEqual([], created3)
        self.assertEqual(2, len(self.erp.tasks[parent_id]["children"]))

        # Seller thêm bình luận MỚI chứa 2 ảnh mới
        self.erp.add_comment(
            parent_id,
            "Thêm 2 mẫu idea mới",
            attachments=[
                {"file_url": "/files/pic-3.jpg", "file_name": "pic-3.jpg"},
                {"file_url": "/files/pic-4.jpg", "file_name": "pic-4.jpg"},
            ],
        )
        self.erp.tasks[parent_id]["attachment_count"] = 5

        # Lượt 4: Chỉ tạo thêm đúng 2 thẻ con mới
        out4 = self.loop.run_until_complete(self._run_bot_scan(bot, self.erp, parent_id))
        created4 = out4[0]["result"]["created"]
        self.assertEqual(2, len(created4))
        self.assertEqual(4, len(self.erp.tasks[parent_id]["children"]))
        new_children = [self.erp.tasks[c["task_id"]] for c in created4]
        self.assertEqual({"/files/pic-3.jpg", "/files/pic-4.jpg"}, {c["cover_image"] for c in new_children})

    # ────────────────────────────────────────────────────────────────────────
    # Kịch bản 7: Thẻ con (thừa kế từ cha gắn bot) không bị coi là thẻ cha.
    # ────────────────────────────────────────────────────────────────────────
    def test_07_the_con_thua_ke_tu_cha_gan_bot_khong_bi_coi_la_the_cha(self) -> None:
        parent_id = "TASK-PARENT-7"
        child_id_1 = "TASK-CHILD-7-1"
        child_id_2 = "TASK-CHILD-7-2"

        self.erp.add_task(
            parent_id,
            subject="Idea Cha",
            meta=CO_CONTENT,
            agents=[BOT_USER],
            children=[{"name": child_id_1}, {"name": child_id_2}],
        )
        # Cả 2 con thừa kế bot từ cha và có parent_task trỏ về cha
        self.erp.add_task(
            child_id_1,
            subject="Idea Con 1",
            parent_task=parent_id,
            agents=[BOT_USER],
            cover_image="/files/child1.jpg",
            attachment_count=1,
        )
        self.erp.add_task(
            child_id_2,
            subject="Idea Con 2",
            parent_task=parent_id,
            agents=[BOT_USER],
            cover_image="/files/child2.jpg",
            attachment_count=1,
        )

        bot = self._create_bot(self.service, self.erp)

        # candidate_tasks phải lọc bỏ các thẻ con, chỉ chọn thẻ cha
        candidates = bot.candidate_tasks([self.erp.project_id], BOT_USER)
        candidate_names = [c.get("name") for c in candidates]

        self.assertIn(parent_id, candidate_names)
        self.assertNotIn(child_id_1, candidate_names)
        self.assertNotIn(child_id_2, candidate_names)

        # Nếu trực tiếp gọi autorun_pass cho thẻ con thì autorun_pass bỏ qua (trả None)
        child_tree = self.erp.task_full(child_id_1)
        child_tree[BOARD_ROW_KEY] = {"attachment_count": 1, "child_total": 0}
        outcome = self.loop.run_until_complete(bot.autorun_pass(child_tree))
        self.assertIsNone(outcome)

    # ────────────────────────────────────────────────────────────────────────
    # Kịch bản 8: Thuộc tính khai trên thẻ cha khác hoa/thường hoặc có dấu cách
    # ────────────────────────────────────────────────────────────────────────
    def test_08_thuoc_tinh_khac_hoa_thuong_va_co_dau_cach(self) -> None:
        # Trường hợp 1: Chữ hoa thường hỗn hợp và chữ in hoa toàn bộ
        casing_meta = (
            "Product_Type: Khăn tay cô dâu thêu tay\n"
            "PRODUCT_GROUP: Thêu tay\n"
            "Fulfillment: HaviGroup\n"
            "Sales_Channel: Etsy\n"
            "CONTENT: Có"
        )
        self.assertEqual([], self.service._erp_idea_missing_meta({"meta": casing_meta}))
        self.assertTrue(self.service._erp_idea_content_enabled({"meta": casing_meta}))

        # Trường hợp 2: Có dấu cách quanh tên khoá không đặt trong ngoặc kép
        spaces_around_keys = (
            "  product_type  : Khăn tay cô dâu thêu tay\n"
            "  product_group  : Thêu tay\n"
            "  fulfillment  : HaviGroup\n"
            "  sales_channel  : Etsy\n"
            "  content  : Có"
        )
        self.assertEqual([], self.service._erp_idea_missing_meta({"meta": spaces_around_keys}))
        self.assertTrue(self.service._erp_idea_content_enabled({"meta": spaces_around_keys}))

        # Trường hợp 3: Khoá đặt trong ngoặc kép có chứa dấu cách bên trong ngoặc:
        # Ghi nhận hành vi của parse_meta_block:
        # '\" Product_Type \": ...' -> raw_key.strip().strip('\"\'') -> ' Product_Type '
        # Do strip('\"\'') để lại khoảng trắng bên trong dấu ngoặc kép, _KEY_RE từ chối.
        inner_quoted_spaces = (
            '" Product_Type ": Khăn tay\n'
            '" Product_Group ": Thêu tay\n'
            '" Fulfillment ": HaviGroup\n'
            '" Sales_Channel ": Etsy'
        )
        parsed_quoted = parse_meta_block(inner_quoted_spaces)
        self.assertEqual({}, parsed_quoted)
        self.assertEqual(
            ["product_type", "product_group", "fulfillment", "sales_channel"],
            self.service._erp_idea_missing_meta({"meta": inner_quoted_spaces}),
        )

    # ────────────────────────────────────────────────────────────────────────
    # Kịch bản 9: Thẻ cha chỉ có đúng 1 ảnh trong bình luận (không ảnh bìa)
    # ────────────────────────────────────────────────────────────────────────
    def test_09_the_cha_1_anh_binh_luan_khong_bia_tach_dung_1_con(self) -> None:
        # Trường hợp 1: Thẻ cha chỉ có đúng 1 ảnh trong bình luận, không ảnh bìa,
        # không tệp đính kèm nào khác, đủ 4 thuộc tính.
        # Mong đợi: bot giao thẻ cho hook (không bị bỏ qua do images < 2),
        # và hook tách ra đúng 1 thẻ con, ảnh đó làm ảnh đại diện.
        parent_id_1 = "TASK-PARENT-9-1"
        self.erp.add_task(
            parent_id_1,
            subject="Idea 1 ảnh không bìa",
            meta=DU_BON_KHOA,
            agents=[BOT_USER],
            cover_image="",
            attachment_count=1,
        )
        self.erp.add_comment(
            parent_id_1,
            "Một mẫu idea duy nhất",
            attachments=[{"file_url": "/files/single-idea.jpg", "file_name": "single-idea.jpg"}],
        )

        bot = self._create_bot(self.service, self.erp)

        tree1 = self.erp.task_full(parent_id_1)
        tree1[BOARD_ROW_KEY] = {"attachment_count": 1, "child_total": 0}
        outcome1 = self.loop.run_until_complete(bot.autorun_pass(tree1))

        self.assertIsNotNone(outcome1, "Bot không được bỏ qua thẻ cha chỉ có 1 ảnh idea khi không có ảnh bìa")
        created1 = outcome1.get("result", {}).get("created", [])
        self.assertEqual(1, len(created1))
        child1_id = created1[0]["task_id"]
        self.assertEqual("/files/single-idea.jpg", self.erp.tasks[child1_id]["cover_image"])

        # Trường hợp 2: Bình luận chỉ đính tệp bot không thấy (has_hidden_files is True)
        # Token của bot đọc taskFull thấy comment thân "(đã đính kèm tệp)" và attachments rỗng,
        # nhưng tài khoản app gọi task_attachment_files đọc được file ảnh.
        parent_id_2 = "TASK-PARENT-9-2"
        self.erp.add_task(
            parent_id_2,
            subject="Idea bình luận đính tệp riêng tư",
            meta=DU_BON_KHOA,
            agents=[BOT_USER],
            cover_image="",
            attachment_count=1,
        )
        self.erp.add_comment(
            parent_id_2,
            "(đã đính kèm tệp)",
            attachments=[],
        )
        self.erp.task_attachments[parent_id_2] = [
            {"file_url": "/files/private-idea.jpg", "file_name": "private-idea.jpg", "url": "/files/private-idea.jpg"}
        ]

        tree2 = self.erp.task_full(parent_id_2)
        tree2[BOARD_ROW_KEY] = {"attachment_count": 1, "child_total": 0}
        outcome2 = self.loop.run_until_complete(bot.autorun_pass(tree2))

        self.assertIsNotNone(outcome2, "Bot phải giao thẻ cho hook khi has_hidden_files là True")
        created2 = outcome2.get("result", {}).get("created", [])
        self.assertEqual(1, len(created2))
        child2_id = created2[0]["task_id"]
        self.assertEqual("/files/private-idea.jpg", self.erp.tasks[child2_id]["cover_image"])

        # Trường hợp 3: Thẻ có 1 ảnh bìa + 1 ảnh trong bình luận -> đúng 1 thẻ con (không lấy ảnh bìa làm idea)
        parent_id_3 = "TASK-PARENT-9-3"
        self.erp.add_task(
            parent_id_3,
            subject="Idea có 1 bìa và 1 bình luận",
            meta=DU_BON_KHOA,
            agents=[BOT_USER],
            cover_image="/files/cover-product.jpg",
            attachment_count=2,
        )
        self.erp.add_comment(
            parent_id_3,
            "Ảnh idea thực sự",
            attachments=[{"file_url": "/files/idea-design.jpg", "file_name": "idea-design.jpg"}],
        )

        tree3 = self.erp.task_full(parent_id_3)
        tree3[BOARD_ROW_KEY] = {"attachment_count": 2, "child_total": 0}
        outcome3 = self.loop.run_until_complete(bot.autorun_pass(tree3))

        self.assertIsNotNone(outcome3)
        created3 = outcome3.get("result", {}).get("created", [])
        self.assertEqual(1, len(created3))
        child3_id = created3[0]["task_id"]
        # Thẻ con phải mang ảnh idea, KHÔNG lấy ảnh bìa làm idea
        self.assertEqual("/files/idea-design.jpg", self.erp.tasks[child3_id]["cover_image"])
        self.assertNotEqual("/files/cover-product.jpg", self.erp.tasks[child3_id]["cover_image"])

    # ────────────────────────────────────────────────────────────────────────
    # Kịch bản 10: Seller thả thêm ảnh vào bình luận MỚI sau khi đã tách
    # ────────────────────────────────────────────────────────────────────────
    def test_10_seller_tha_them_anh_vao_binh_luan_moi_sau_khi_da_tach(self) -> None:
        parent_id = "TASK-PARENT-10"
        self.erp.add_task(
            parent_id,
            subject="Idea khăn tay nhiều mẫu",
            meta=DU_BON_KHOA,
            agents=[BOT_USER],
            attachment_count=3,
        )
        self.erp.add_comment(
            parent_id,
            "Đợt 1: 3 mẫu idea",
            attachments=[
                {"file_url": "/files/mau-1.jpg", "file_name": "mau-1.jpg"},
                {"file_url": "/files/mau-2.jpg", "file_name": "mau-2.jpg"},
                {"file_url": "/files/mau-3.jpg", "file_name": "mau-3.jpg"},
            ],
        )

        bot = self._create_bot(self.service, self.erp)

        # Lượt 1: Tách đúng 3 thẻ con
        out1 = self.loop.run_until_complete(self._run_bot_scan(bot, self.erp, parent_id))
        created1 = out1[0]["result"]["created"]
        self.assertEqual(3, len(created1))
        self.assertEqual(3, len(self.erp.tasks[parent_id]["children"]))
        covers1 = {self.erp.tasks[c["task_id"]]["cover_image"] for c in created1}
        self.assertEqual({"/files/mau-1.jpg", "/files/mau-2.jpg", "/files/mau-3.jpg"}, covers1)

        # Seller thả thêm bình luận MỚI chứa 2 ảnh
        self.erp.add_comment(
            parent_id,
            "Đợt 2: Thêm 2 mẫu idea mới",
            attachments=[
                {"file_url": "/files/mau-4.jpg", "file_name": "mau-4.jpg"},
                {"file_url": "/files/mau-5.jpg", "file_name": "mau-5.jpg"},
            ],
        )
        self.erp.tasks[parent_id]["attachment_count"] = 5

        # Lượt 2: Quét lại -> thêm đúng 2 thẻ con, không tách lại 3 ảnh cũ
        out2 = self.loop.run_until_complete(self._run_bot_scan(bot, self.erp, parent_id))
        created2 = out2[0]["result"]["created"]
        self.assertEqual(2, len(created2))
        self.assertEqual(5, len(self.erp.tasks[parent_id]["children"]))
        covers2 = {self.erp.tasks[c["task_id"]]["cover_image"] for c in created2}
        self.assertEqual({"/files/mau-4.jpg", "/files/mau-5.jpg"}, covers2)

        # Kiểm tra toàn bộ 5 thẻ con không bị trùng bìa
        all_child_covers = [self.erp.tasks[c["name"]]["cover_image"] for c in self.erp.tasks[parent_id]["children"]]
        self.assertEqual(5, len(all_child_covers))
        self.assertEqual(5, len(set(all_child_covers)))


if __name__ == "__main__":
    unittest.main()

