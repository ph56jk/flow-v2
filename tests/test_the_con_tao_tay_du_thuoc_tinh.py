"""Thẻ con tạo tay cũng phải đủ Thuộc tính của thẻ cha (kịch bản PROJ-0229).

Thẻ con tạo bằng tay trên ERP không đi qua đường tạo của app, nên không ai
điền Thuộc tính cho nó: ô Người phụ trách trống, khối Thuộc tính trống, Review
Lister đọc ra thiếu khoá. Luật chốt: tạo tay hay tự động thì thẻ con đều đủ
Thuộc tính của cha — chỉ ô còn trống mới được điền, ô thẻ con đã gõ là của nó.

Hai chỗ khâu lại được kiểm ở đây:
- ``_enqueue_erp_idea_jobs_unlocked``: lượt nào đụng thẻ cha (nút Chạy tay,
  autorun bot, watcher) cũng đổ Thuộc tính xuống mọi thẻ con trước — kể cả
  lượt "chỉ tách" không content. Lượt bị giữ job vì quota thì không đọc thêm
  thẻ nào, phần điền để lượt sau.
- ``AgentBot.meta_inherit_pass``: ở scope ``board`` (mặc định), thẻ Idea
  không gắn agent nào vẫn là việc của bot nên con của nó cũng được điền —
  giống hệt cây có gắn bot. Scope ``card`` vẫn đòi gắn đích danh.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
from typing import Any, Dict, List
import unittest
from unittest.mock import AsyncMock, patch

from flow_web.agent_bot import (
    AgentBot,
    AgentBotConfig,
    AgentBotState,
    SCOPE_CARD,
)
from flow_web.erp_meta import parse_meta_block
from flow_web.schemas import ERPConfig, ERPIdeaBatchRequest
from flow_web.service import FlowWebService
from flow_web.store import StateStore


BOT = "agent-bot@bots.hvg.internal"
PARENT = "TASK-CHA-229"
CHILD_A = "TASK-CON-A"
CHILD_B = "TASK-CON-B"

DU_BON_KHOA = (
    "product_type: Khăn tay cô dâu thêu tay\n"
    "product_group: Thêu tay\n"
    "fulfillment: HaviGroup\n"
    "sales_channel: Etsy"
)
CO_CONTENT = DU_BON_KHOA + "\ncontent: Có"


class _EnqueueTestCase(unittest.TestCase):
    """Service có ERP key/secret giả, mọi lượt ghi ERP đều là hàm giả."""

    def setUp(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.patches = [
            patch("flow_web.store.STATE_FILE", root / "state.json"),
            patch("flow_web.store.ensure_app_dirs", lambda: root.mkdir(parents=True, exist_ok=True)),
            patch("flow_web.service.ensure_app_dirs", lambda: root.mkdir(parents=True, exist_ok=True)),
        ]
        for item in self.patches:
            item.start()
        self.store = StateStore()
        self.service = FlowWebService(self.store)
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(
                    api_key="test-key",
                    api_secret="test-secret",
                    project_id="PROJ-0229",
                    task_id=PARENT,
                )
            )
        )

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tempdir.cleanup()
        self.loop.close()
        asyncio.set_event_loop(None)

    def _details(
        self,
        *,
        parent_meta: str,
        dropped: tuple = (),
        children: tuple = (CHILD_A, CHILD_B),
        children_meta: Dict[str, str] | None = None,
    ) -> dict:
        """Thẻ cha đã khai Thuộc tính; thẻ con tạo tay, trống trơn như trên ERP."""
        details: dict = {
            PARENT: {
                "name": PARENT,
                "subject": "Idea Khăn tay",
                "status": "Working",
                "description": "<p>Idea cho khăn tay cô dâu</p>",
                "cover_image": "/private/files/khan-tay.jpg",
                "meta": parent_meta,
                "children": [
                    {"name": child, "subject": f"Idea {index + 1}"}
                    for index, child in enumerate(children)
                ],
                "comments": [
                    {
                        "name": f"drop-{index}",
                        "content": "",
                        "attachments": [{"file_url": url, "file_name": Path(url).name}],
                    }
                    for index, url in enumerate(dropped)
                ],
            }
        }
        for index, child in enumerate(children):
            details[child] = {
                "name": child,
                "subject": f"Idea {index + 1}",
                "status": "Open",
                "description": "<p>Khăn tay đặt cạnh cây thông</p>",
                "meta": (children_meta or {}).get(child, ""),
                "comments": [],
            }
        return details

    def _wire(self, details: dict):
        """Mọi đường đọc/ghi ERP là hàm giả; lượt ghi meta được ghi lại."""
        created: list[dict] = []
        meta_writes: list[tuple[str, str]] = []
        detail_reads: list[str] = []

        def _read(_key, _token, task_id):
            detail_reads.append(task_id)
            return details[task_id]

        def _create(_key, _token, parent, project, subject, *, status="Open", description=""):
            child_id = f"TASK-NEW-{len(created)}"
            created.append({"id": child_id, "subject": subject})
            details[parent]["children"].append({"name": child_id, "subject": subject})
            details[child_id] = {
                "name": child_id,
                "subject": subject,
                "status": status,
                "description": description,
                "meta": "",
                "cover_image": "",
                "comments": [],
            }
            return child_id

        def _attach(
            _key, _token, task_id, data, mime, name, set_cover,
            parent_comment="", comment_text="", silent_comment=False,
        ):
            url = f"/private/files/{name}"
            details[task_id]["comments"].append(
                {"name": f"cmt-{name}", "content": comment_text, "attachments": [{"file_url": url, "file_name": name}]}
            )
            return {"url": url, "name": name}

        def _update_meta(_key, _token, task_id, meta, *, project=""):
            meta_writes.append((task_id, meta))
            details[task_id]["meta"] = meta
            return {"name": task_id, "meta": meta}

        wiring = patch.multiple(
            self.service,
            _erp_task_project_id=lambda *_args, **_kwargs: "PROJ-0229",
            _erp_task_detail=_read,
            _erp_task_attachment_files=lambda *_args, **_kwargs: [],
            _erp_board_name=lambda *_args, **_kwargs: "",
            _erp_create_child_task=_create,
            _erp_download_attachment_bytes=lambda _k, _t, _task, att: (
                f"bytes:{att.get('name')}".encode(),
                "image/jpeg",
            ),
            _erp_attach_file_bytes=_attach,
            _erp_set_task_cover=lambda *_args, **_kwargs: None,
            _erp_add_task_agent=lambda *_args, **_kwargs: None,
            _erp_comment=lambda *_args, **_kwargs: {},
            _erp_update_task_meta=_update_meta,
            sync_erp_skus=AsyncMock(return_value={"written": []}),
        )
        return created, meta_writes, detail_reads, wiring

    def _enqueue(
        self,
        details: dict,
        request: ERPIdeaBatchRequest | None = None,
        *,
        hold_jobs_reason: str = "",
    ):
        created, meta_writes, detail_reads, wiring = self._wire(details)
        with wiring, patch.object(self.service, "_run_flow_job", new_callable=AsyncMock) as run:
            response = self.loop.run_until_complete(
                self.service.enqueue_erp_idea_jobs(
                    request or ERPIdeaBatchRequest(task_id=PARENT),
                    hold_jobs_reason=hold_jobs_reason,
                )
            )
            for _ in range(3):
                self.loop.run_until_complete(asyncio.sleep(0))
        return response, created, meta_writes, detail_reads, run


class DienThuocTinhTheConTaoTayTests(_EnqueueTestCase):
    """Nút Chạy / autorun đụng thẻ cha là mọi thẻ con được điền Thuộc tính."""

    def test_the_con_tao_tay_nhan_du_thuoc_tinh_cha(self) -> None:
        """PROJ-0229: cả hai thẻ con tạo tay, meta trống → nhận đủ bốn khoá."""
        details = self._details(parent_meta=CO_CONTENT)

        response, _created, meta_writes, _reads, _run = self._enqueue(details)

        filled = {task_id: meta for task_id, meta in meta_writes}
        self.assertEqual({CHILD_A, CHILD_B}, set(filled))
        for child in (CHILD_A, CHILD_B):
            attrs = parse_meta_block(filled[child])
            for key in ("product_type", "product_group", "fulfillment", "sales_channel"):
                self.assertIn(key, attrs, f"{child} thiếu {key}")
        # Kết quả lượt chạy cũng kể lại những thẻ đã được điền.
        inherited = {item["task_id"] for item in response.get("meta_inherited") or []}
        self.assertEqual({CHILD_A, CHILD_B}, inherited)

    def test_o_con_da_go_la_cua_con_cha_khong_ghi_de(self) -> None:
        """Con khai fulfillment: FBA riêng thì giữ FBA, chỉ nhận ba ô còn lại."""
        details = self._details(
            parent_meta=CO_CONTENT,
            children_meta={CHILD_A: "fulfillment: FBA"},
        )

        _response, _created, meta_writes, _reads, _run = self._enqueue(details)

        filled = dict(meta_writes)
        self.assertIn(CHILD_A, filled)
        attrs_a = parse_meta_block(filled[CHILD_A])
        self.assertEqual("FBA", attrs_a.get("fulfillment"))
        self.assertEqual("Etsy", attrs_a.get("sales_channel"))
        self.assertNotIn("HaviGroup", str(attrs_a.get("fulfillment") or ""))

    def test_o_rieng_the_con_khong_bao_gio_xuong(self) -> None:
        """content, sku, action_*, fatheridea của cha không xuống thẻ con."""
        parent_meta = (
            CO_CONTENT
            + "\nsku: SKU-CHA-01\naction_1: idea\nfatheridea: TASK-KHAC"
        )
        details = self._details(parent_meta=parent_meta)

        _response, _created, meta_writes, _reads, _run = self._enqueue(details)

        for _task_id, meta in meta_writes:
            block = parse_meta_block(meta)
            for banned in ("content", "sku", "action_1", "fatheridea"):
                self.assertNotIn(banned, block)

    def test_luot_chi_tach_khong_content_van_dien_the_con(self) -> None:
        """Không khai content thì chỉ tách thẻ — nhưng thẻ con vẫn đủ thuộc tính."""
        details = self._details(parent_meta=DU_BON_KHOA)

        response, _created, meta_writes, _reads, run = self._enqueue(details)

        self.assertEqual([], response["queued"])
        run.assert_not_awaited()
        filled = {task_id for task_id, _meta in meta_writes}
        self.assertEqual({CHILD_A, CHILD_B}, filled)

    def test_giu_job_vi_quota_thi_khong_doc_them_the_con(self) -> None:
        """Lượt bị giữ job: không đọc thẻ con nào ngoài cha (trần request ERP).

        Phần điền Thuộc tính để lượt sau — lượt quét của bot cũng điền được,
        nên thẻ con không bị bỏ quên.
        """
        details = self._details(parent_meta=CO_CONTENT)

        _response, _created, meta_writes, reads, run = self._enqueue(
            details, hold_jobs_reason="hết quota Agent"
        )

        run.assert_not_awaited()
        self.assertEqual([PARENT], reads)
        self.assertEqual([], meta_writes)

    def test_luot_sau_khong_ghi_lai(self) -> None:
        """Điền một lần rồi thôi: lượt thứ hai không phát sinh lượt ghi nào."""
        details = self._details(parent_meta=CO_CONTENT)

        self._enqueue(details)
        _response, _created, meta_writes2, _reads, _run = self._enqueue(details)

        self.assertEqual([], meta_writes2)

    def test_the_con_tu_dong_vua_tao_cung_duoc_dien_ngay_luot_nay(self) -> None:
        """Ảnh thả lên vừa thành thẻ con: thẻ mới cũng đủ thuộc tính ngay."""
        details = self._details(
            parent_meta=CO_CONTENT,
            dropped=("/private/files/idea-moi.jpg",),
            children=(),
        )

        response, created, meta_writes, _reads, _run = self._enqueue(details)

        self.assertEqual(1, len(created))
        new_id = created[0]["id"]
        filled = dict(meta_writes)
        self.assertIn(new_id, filled)
        attrs = parse_meta_block(filled[new_id])
        self.assertEqual("Etsy", attrs.get("sales_channel"))
        inherited = {item["task_id"] for item in response.get("meta_inherited") or []}
        self.assertIn(new_id, inherited)

    def test_cha_thieu_thuoc_tinh_dung_ngay_khong_doc_con(self) -> None:
        """Cha thiếu khoá bắt buộc: dừng ở thẻ cha, không đọc thẻ con nào."""
        details = self._details(parent_meta="product_type: Khăn tay\nfulfillment: HaviGroup")

        response, _created, meta_writes, reads, _run = self._enqueue(details)

        self.assertEqual(["product_group", "sales_channel"], response["missing_meta"])
        self.assertEqual([PARENT], reads)
        self.assertEqual([], meta_writes)


class MetaInheritBoardScopeTests(unittest.TestCase):
    """``meta_inherit_pass`` ở scope board: cây là việc của bot thì con được điền."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.writes: List[tuple[str, Dict[str, str]]] = []

    def _record_hook(self, task_id: str, values: Dict[str, str]) -> Dict[str, Any]:
        self.writes.append((task_id, dict(values)))
        return {"task_id": task_id, "written": dict(values)}

    def _task_node(self, name: str, **extra: Any) -> Dict[str, Any]:
        node = {
            "name": name,
            "subject": name,
            "agents": [],
            "comments": [],
            "subtasks": [],
            "children": [],
            "child_total": 0,
        }
        node.update(extra)
        return node

    def _bot(self, root: Dict[str, Any], **overrides) -> AgentBot:
        config = AgentBotConfig(token="t0ken", bot_user=BOT, **overrides)
        bot = AgentBot(config, client=None, state=AgentBotState.load(self.tmp / "state.json"))
        bot.meta_inherit_hook = self._record_hook
        return bot

    def test_scope_board_the_idea_khong_gan_ai_con_van_duoc_dien(self) -> None:
        """Thẻ Idea không gắn agent nào vẫn là việc của bot (scope board mặc
        định): bot đã autorun/dọn phiếu cho cây ấy thì con của nó cũng được
        điền Thuộc tính — đúng luật thẻ con tạo tay cũng đủ."""
        child = self._task_node(CHILD_A, meta="")
        root = self._task_node(
            PARENT,
            status="Cần làm",
            meta="fulfillment: FBM\nsales_channel: Etsy",
            subtasks=[child],
            children=[{"name": CHILD_A}],
            child_total=1,
        )
        bot = self._bot(root)

        done = bot.meta_inherit_pass({"root": root}, BOT)

        self.assertEqual([{"task": CHILD_A, "keys": ["fulfillment", "sales_channel"]}], done)
        self.assertEqual(
            {CHILD_A: {"fulfillment": "FBM", "sales_channel": "Etsy"}}, dict(self.writes)
        )

    def test_scope_board_the_gan_agent_khac_bo_qua(self) -> None:
        """Thẻ gắn một agent khác (không phải bot này) thì không phải việc."""
        child = self._task_node(CHILD_A, meta="")
        root = self._task_node(
            PARENT,
            status="Cần làm",
            agents=[{"bot_user": "agent-khac@bots.hvg.internal"}],
            meta="fulfillment: FBM",
            subtasks=[child],
            children=[{"name": CHILD_A}],
            child_total=1,
        )
        bot = self._bot(root)

        self.assertEqual([], bot.meta_inherit_pass({"root": root}, BOT))
        self.assertEqual([], self.writes)

    def test_scope_board_the_khong_phai_idea_bo_qua(self) -> None:
        """Thẻ không con, không ảnh, không group: không phải thẻ Idea."""
        root = self._task_node(PARENT, status="Cần làm", meta="fulfillment: FBM")
        bot = self._bot(root)

        self.assertEqual([], bot.meta_inherit_pass({"root": root}, BOT))
        self.assertEqual([], self.writes)

    def test_scope_card_van_doi_gan_dich_danh(self) -> None:
        """Scope card giữ nguyên hàng rào cũ: cha không gắn bot thì bỏ qua."""
        child = self._task_node(CHILD_A, meta="")
        root = self._task_node(
            PARENT,
            status="Cần làm",
            meta="fulfillment: FBM",
            subtasks=[child],
            children=[{"name": CHILD_A}],
            child_total=1,
        )
        bot = self._bot(root, scope=SCOPE_CARD)

        self.assertEqual([], bot.meta_inherit_pass({"root": root}, BOT))
        self.assertEqual([], self.writes)

    def test_bot_user_rong_hoac_hook_none_van_bo_qua(self) -> None:
        """Chưa biết danh tính bot hay chưa nối hook ghi thì không làm gì."""
        child = self._task_node(CHILD_A, meta="")
        root = self._task_node(
            PARENT,
            status="Cần làm",
            meta="fulfillment: FBM",
            subtasks=[child],
            children=[{"name": CHILD_A}],
            child_total=1,
        )
        bot = self._bot(root)

        self.assertEqual([], bot.meta_inherit_pass({"root": root}, ""))
        bot.meta_inherit_hook = None
        self.assertEqual([], bot.meta_inherit_pass({"root": root}, BOT))
        self.assertEqual([], self.writes)


if __name__ == "__main__":
    unittest.main()
