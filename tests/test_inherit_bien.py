"""Tests ca biên cho cơ chế 'thẻ con nhận Thuộc tính của thẻ cha'.

Bao phủ các quy tắc nghiệp vụ theo brief r2-bien-inherit:
1. Chỉ điền ô còn trống.
2. Không bao giờ chép content, sku (mọi cách viết), action_*, fatheridea/idea,
   parent_task, ten_cu, và các ô hệ thống bắt đầu bằng '_'.
3. Thẻ cháu nhận theo thẻ ngay trên nó, không nhảy lên gốc.
4. Trần META_INHERIT_PER_SCAN = 8 thẻ mỗi lượt quét.
5. Hook ném lỗi thì dừng ngay lượt quét và bật cooldown META_INHERIT_BACKOFF_SECONDS.
6. dry_run không gọi hook và không sửa node.
7. Scope ``card``: thẻ cha không gắn đích danh bot thì bỏ qua hoàn toàn.
   Scope ``board``: thẻ Idea không gắn agent nào vẫn là việc của bot — con của
   nó (kể cả thẻ tạo tay) cũng được điền; thẻ gắn agent khác thì bỏ qua.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
from typing import Any, Dict, List
import unittest
from unittest.mock import patch

from flow_web.agent_bot import (
    AgentBot,
    AgentBotConfig,
    AgentBotState,
    META_INHERIT_BACKOFF_SECONDS,
    META_INHERIT_PER_SCAN,
    SCOPE_CARD,
)
from flow_web.erp_meta import (
    missing_from_parent,
    task_meta,
)
from flow_web.service import FlowWebService


BOT = "agent-kin-test-agent@bots.hvg.internal"


def task_node(
    name: str,
    *,
    agents: List[str] = (),
    comments: List[Dict[str, Any]] = (),
    subtasks=(),
    child_total: int = 0,
    **extra: Any,
) -> Dict[str, Any]:
    node = {
        "name": name,
        "subject": name,
        "agents": [{"bot_user": item} for item in agents],
        "comments": list(comments),
        "subtasks": list(subtasks),
        "children": [{"name": item["name"]} for item in subtasks],
        "child_total": child_total or len(subtasks),
    }
    node.update(extra)
    return node


class FakeClient:
    def __init__(
        self,
        projects: List[str],
        boards: Dict[str, List[Dict[str, Any]]],
        trees: Dict[str, Dict[str, Any]],
    ):
        self._projects = projects
        self._boards = boards
        self._trees = trees

    def task_projects(self) -> List[Dict[str, Any]]:
        return [{"name": name, "project_name": name} for name in self._projects]

    def board_snapshot(self, project: str):
        return self._boards.get(project, []), ()

    def task_detail_full(self, task_id: str) -> Dict[str, Any]:
        return self._trees.get(task_id, {})


def build_test_bot(client: FakeClient, tmp: Path, **overrides) -> AgentBot:
    config = AgentBotConfig(token="t0ken", bot_user=BOT, **overrides)
    return AgentBot(config, client=client, state=AgentBotState.load(tmp / "state.json"))


class MissingFromParentEdgeTests(unittest.TestCase):
    """Kiểm thử ca biên trực tiếp trên hàm missing_from_parent."""

    def test_cha_co_content_the_con_trong_khong_nhan_content(self) -> None:
        """Thẻ cha có content: có (hoặc viết hoa CONTENT: có), thẻ con trống

        Thẻ con không bao giờ nhận content vì content do seller khai trên cha,
        bot tuyệt đối không ghi content thay seller.
        """
        parent = {"content": "Có", "sales_channel": "Etsy"}
        written = missing_from_parent({}, parent)
        self.assertNotIn("content", written)
        self.assertEqual({"sales_channel": "Etsy"}, written)

        # Kiểm tra thêm trường hợp key viết hoa CONTENT
        parent_upper = {"CONTENT": "Có", "sales_channel": "Etsy"}
        written_upper = missing_from_parent({}, parent_upper)
        self.assertNotIn("content", written_upper)
        self.assertNotIn("CONTENT", written_upper)
        self.assertEqual({"sales_channel": "Etsy"}, written_upper)

    def test_the_con_da_co_account_the_cha_co_acc_khong_ghi_de(self) -> None:
        """Thẻ con đã có account, thẻ cha có acc -> không ghi đè.

        acc và account cùng nhóm _SAME_FIELD, ô con đã có thì giữ của con.
        """
        child = {"account": "acc32"}
        parent = {"acc": "acc16", "fulfillment": "FBM"}
        written = missing_from_parent(child, parent)
        self.assertNotIn("acc", written)
        self.assertNotIn("account", written)
        self.assertEqual({"fulfillment": "FBM"}, written)

        # Ngược lại: con có acc, cha có account, shop -> không ghi đè
        child_rev = {"acc": "acc32"}
        parent_rev = {"account": "acc16", "shop": "shop_etsy"}
        self.assertEqual({}, missing_from_parent(child_rev, parent_rev))

    def test_action_moi_loai_khong_xuong_the_con(self) -> None:
        """action_1: idea hoặc bất kỳ action nào không xuống thẻ con.

        _ACTION_RE chặn action, action_1, action_2, action_0...
        """
        parent = {
            "action": "listing",
            "action_1": "idea",
            "action_2": "review",
            "action_0": "check",
            "action10": "ship",
            "fulfillment": "FBM",
        }
        written = missing_from_parent({}, parent)
        for k in parent:
            if k != "fulfillment":
                self.assertNotIn(k, written)
        self.assertEqual({"fulfillment": "FBM"}, written)

    def test_sku_cac_bien_the_khong_xuong_the_con(self) -> None:
        """Mọi biến thể của SKU trong SKU_KEYS không xuống thẻ con."""
        parent = {
            "sku": "OR_01",
            "ma_sku": "OR_02",
            "masku": "OR_03",
            "sku_code": "OR_04",
            "product_key": "OR_05",
            "productkey": "OR_06",
            "fulfillment": "FBM",
        }
        written = missing_from_parent({}, parent)
        self.assertEqual({"fulfillment": "FBM"}, written)

    def test_master_sku_khong_xuong_the_con(self) -> None:
        """Brief quy định: 'sku/master_sku không xuống'.

        master_sku / mastersku là mã sản phẩm gốc, không được chép xuống thẻ con.
        """
        parent = {"master_sku": "MSKU-888", "mastersku": "MSKU-999", "fulfillment": "FBM"}
        written = missing_from_parent({}, parent)
        self.assertNotIn("master_sku", written)
        self.assertNotIn("mastersku", written)
        self.assertEqual({"fulfillment": "FBM"}, written)

    def test_o_the_cha_de_trong_khong_xuong_the_con(self) -> None:
        """Ô thẻ cha để trống (hoặc whitespace, None) không xuống thẻ con."""
        parent = {
            "account": "",
            "note": "   ",
            "color": None,
            "fulfillment": "FBM",
        }
        written = missing_from_parent({}, parent)
        self.assertEqual({"fulfillment": "FBM"}, written)

    def test_key_cha_chua_khoang_trang_hoac_ky_tu_khong_hop_le_bi_loai_bo(self) -> None:
        """Key có khoảng trắng hoặc ký tự lạ không hợp lệ theo _KEY_RE thì bị loại bỏ.

        Key viết hoa hoặc có khoảng trắng ở đầu/cuối được chuẩn hoá.
        """
        parent = {
            "product type": "ao",
            "ten-san-pham": "quan",
            "1st_key": "val",
            "@tag": "val2",
            "  FULFILLMENT  ": "FBM",
        }
        written = missing_from_parent({}, parent)
        self.assertEqual({"fulfillment": "FBM"}, written)

    def test_cac_key_dinh_danh_rieng_the_khong_xuong_the_con(self) -> None:
        """fatheridea, dadidea, idea, parent_task, ten_cu không xuống thẻ con."""
        parent = {
            "fatheridea": "TASK-1",
            "father_idea": "TASK-1",
            "dadidea": "TASK-1",
            "dad_idea": "TASK-1",
            "idea": "TASK-1",
            "idea_id": "TASK-1",
            "parent_task": "TASK-0",
            "parenttask": "TASK-0",
            "parent": "TASK-0",
            "parent_task_id": "TASK-0",
            "parent_id": "TASK-0",
            "ten_cu": "Cu 01",
            "fulfillment": "FBM",
        }
        written = missing_from_parent({}, parent)
        self.assertEqual({"fulfillment": "FBM"}, written)

    def test_o_he_thong_bat_dau_bang_underscore_khong_xuong_the_con(self) -> None:
        """Ô hệ thống bắt đầu bằng dấu gạch dưới không bao giờ xuống."""
        parent = {
            "_task": "TASK-ROOT",
            "_status": "Working",
            "_labels": "urgent",
            "_agents": "bot",
            "fulfillment": "FBM",
        }
        written = missing_from_parent({}, parent)
        self.assertEqual({"fulfillment": "FBM"}, written)

    def test_cac_nhom_dong_nghia_khac_khong_ghi_de(self) -> None:
        """Machine, profile, product, template: đã có 1 đại diện thì không nhận cái khác."""
        # Machine
        self.assertEqual({}, missing_from_parent({"pc": "may01"}, {"machine": "may02", "vps": "may03"}))
        # Profile
        self.assertEqual({}, missing_from_parent({"profile_label": "p1"}, {"flow_profile": "p2"}))
        # Product
        self.assertEqual({}, missing_from_parent({"san_pham": "ao"}, {"product": "quan", "product_type": "vay"}))
        # Template / Copy SKU
        self.assertEqual({}, missing_from_parent({"template": "S1"}, {"copysku": "S2", "copy_sku": "S3"}))


class MetaInheritPassEdgeTests(unittest.TestCase):
    """Kiểm thử ca biên trên AgentBot.meta_inherit_pass."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.writes: List[tuple[str, Dict[str, str]]] = []

    def _record_hook(self, task_id: str, values: Dict[str, str]) -> Dict[str, Any]:
        self.writes.append((task_id, dict(values)))
        return {"task_id": task_id, "written": dict(values)}

    def _bot(self, root: Dict[str, Any], hook="record", **overrides) -> AgentBot:
        rows = [
            {
                "name": root["name"],
                "child_total": root["child_total"],
                "status": "Working",
                "agents": root.get("agents") or [],
                "parent_task": "",
            }
        ]
        client = FakeClient(["PROJ-0087"], {"PROJ-0087": rows}, {root["name"]: {"root": root}})
        bot = build_test_bot(client, self.tmp, **overrides)
        bot.meta_inherit_hook = self._record_hook if hook == "record" else hook
        return bot

    def test_the_chau_nhan_theo_the_con_chu_khong_nhay_len_goc(self) -> None:
        """Thẻ cháu nhận theo thẻ con trực tiếp, không nhảy lên gốc.

        Root có fulfillment: FBM, sales_channel: Etsy.
        Con có fulfillment: FBA (ghi đè), color: Red.
        Cháu trống: nhận fulfillment: FBA (từ con), color: Red, sales_channel: Etsy.
        Tuyệt đối không nhận fulfillment: FBM từ Root.
        """
        grandchild = task_node("TASK-GRANDCHILD", meta="")
        child = task_node("TASK-CHILD", meta="fulfillment: FBA\ncolor: Red", subtasks=[grandchild])
        root = task_node(
            "TASK-ROOT",
            agents=[BOT],
            meta="fulfillment: FBM\nsales_channel: Etsy\nproduct: Cup",
            subtasks=[child],
        )
        bot = self._bot(root)

        bot.meta_inherit_pass({"root": root}, BOT)

        writes_map = dict(self.writes)
        self.assertIn("TASK-GRANDCHILD", writes_map)
        gc_values = writes_map["TASK-GRANDCHILD"]
        self.assertEqual("FBA", gc_values.get("fulfillment"))
        self.assertEqual("Red", gc_values.get("color"))
        self.assertEqual("Etsy", gc_values.get("sales_channel"))
        self.assertEqual("Cup", gc_values.get("product"))

    def test_qua_8_the_con_dung_o_tran_meta_inherit_per_scan(self) -> None:
        """Quá 8 thẻ trong một lượt thì dừng ở META_INHERIT_PER_SCAN = 8."""
        children = [task_node(f"TASK-C-{i:02d}", meta="") for i in range(12)]
        root = task_node(
            "TASK-ROOT",
            agents=[BOT],
            meta="fulfillment: FBM\nsales_channel: Etsy",
            subtasks=children,
        )
        bot = self._bot(root)

        # Lượt 1: chỉ chạy tối đa 8 thẻ
        done = bot.meta_inherit_pass({"root": root}, BOT)
        self.assertEqual(META_INHERIT_PER_SCAN, len(done))
        self.assertEqual(META_INHERIT_PER_SCAN, len(self.writes))
        self.assertEqual(0, bot._meta_inherit_left)

        # Reset ngân sách lượt quét để chạy tiếp lượt 2
        bot._meta_inherit_left = META_INHERIT_PER_SCAN
        done_round2 = bot.meta_inherit_pass({"root": root}, BOT)
        self.assertEqual(4, len(done_round2))
        self.assertEqual(12, len(self.writes))

    def test_hook_nem_loi_thi_dung_luot_va_danh_dau_cooldown(self) -> None:
        """Hook ném lỗi -> dừng ngay lượt quét và đánh dấu cooldown META_INHERIT_BACKOFF_SECONDS."""
        tried: List[str] = []

        def fail_hook(task_id: str, values: Dict[str, str]) -> Dict[str, Any]:
            tried.append(task_id)
            raise RuntimeError("ERP rate limit HTTP 429")

        c1 = task_node("TASK-C-1", meta="")
        c2 = task_node("TASK-C-2", meta="")
        root = task_node("TASK-ROOT", agents=[BOT], meta="fulfillment: FBM", subtasks=[c1, c2])
        bot = self._bot(root, hook=fail_hook)

        done = bot.meta_inherit_pass({"root": root}, BOT)
        self.assertEqual([], done)
        self.assertEqual(["TASK-C-1"], tried)  # Thẻ 2 không bị gọi
        self.assertEqual(0, bot._meta_inherit_left)

        # Kiểm tra cooldown đã được ghi nhận trong state store
        self.assertFalse(bot.state.autorun_is_cool("meta:TASK-ROOT", META_INHERIT_BACKOFF_SECONDS))

        # Lượt kế tiếp ngay sau đó: bị chặn bởi cooldown
        done2 = bot.meta_inherit_pass({"root": root}, BOT)
        self.assertEqual([], done2)
        self.assertEqual(["TASK-C-1"], tried)

    def test_dry_run_khong_goi_hook_va_khong_sua_node(self) -> None:
        """dry_run = True thì không gọi hook và không sửa node['meta']."""
        child = task_node("TASK-C-1", meta="")
        root = task_node("TASK-ROOT", agents=[BOT], meta="fulfillment: FBM", subtasks=[child])
        bot = self._bot(root, dry_run=True)

        done = bot.meta_inherit_pass({"root": root}, BOT)
        self.assertEqual([], self.writes)
        self.assertEqual([{"task": "TASK-C-1", "keys": ["fulfillment"], "dry_run": True}], done)
        self.assertEqual("", child.get("meta", ""))

    def test_scope_board_the_idea_khong_gan_ai_con_van_duoc_dien(self) -> None:
        """Scope board: thẻ Idea không gắn agent nào vẫn là việc của bot.

        Bot đã nhận cả cây ấy (autorun, dọn phiếu đều chạy trên nó) nên thẻ
        con của nó — kể cả thẻ tạo tay — cũng được điền Thuộc tính, không đợi
        ai gắn đích danh bot lên thẻ cha.
        """
        child = task_node("TASK-C-1", meta="")
        root = task_node("TASK-ROOT", agents=[], meta="fulfillment: FBM", subtasks=[child])
        bot = self._bot(root)

        done = bot.meta_inherit_pass({"root": root}, BOT)
        self.assertEqual([{"task": "TASK-C-1", "keys": ["fulfillment"]}], done)
        self.assertEqual({"TASK-C-1": {"fulfillment": "FBM"}}, dict(self.writes))

    def test_scope_board_the_gan_agent_khac_thi_bo_qua(self) -> None:
        """Thẻ gắn một agent khác (không phải bot này) thì không phải việc."""
        child = task_node("TASK-C-1", meta="")
        root = task_node(
            "TASK-ROOT",
            agents=["agent-khac@bots.hvg.internal"],
            meta="fulfillment: FBM",
            subtasks=[child],
        )
        bot = self._bot(root)

        self.assertEqual([], bot.meta_inherit_pass({"root": root}, BOT))
        self.assertEqual([], self.writes)

    def test_scope_board_the_khong_phai_idea_thi_bo_qua(self) -> None:
        """Thẻ không con, không ảnh, không group: không phải thẻ Idea."""
        root = task_node("TASK-ROOT", agents=[], meta="fulfillment: FBM")
        bot = self._bot(root)

        self.assertEqual([], bot.meta_inherit_pass({"root": root}, BOT))
        self.assertEqual([], self.writes)

    def test_scope_card_van_doi_gan_dich_danh(self) -> None:
        """Scope card giữ hàng rào cũ: cha không gắn bot thì bỏ qua.

        bot_user rỗng hay hook ghi là None cũng không làm gì.
        """
        child = task_node("TASK-C-1", meta="")
        root = task_node("TASK-ROOT", agents=[], meta="fulfillment: FBM", subtasks=[child])
        bot = self._bot(root, scope=SCOPE_CARD)

        self.assertEqual([], bot.meta_inherit_pass({"root": root}, BOT))
        self.assertEqual([], bot.meta_inherit_pass({"root": root}, ""))

        bot.meta_inherit_hook = None
        root_bot = task_node(
            "TASK-ROOT-2", agents=[BOT], meta="fulfillment: FBM", subtasks=[child]
        )
        self.assertEqual([], bot.meta_inherit_pass({"root": root_bot}, BOT))
        self.assertEqual([], self.writes)

    def test_cooldown_doc_lap_giua_cac_the_cha(self) -> None:
        """Cooldown của thẻ cha này không ảnh hưởng đến thẻ cha khác."""
        def fail_first(task_id: str, values: Dict[str, str]) -> Dict[str, Any]:
            if "R1" in task_id:
                raise RuntimeError("Lỗi mạng ERP trên R1")
            self.writes.append((task_id, values))
            return {"task_id": task_id, "written": values}

        c1 = task_node("TASK-R1-c", meta="")
        r1 = task_node("TASK-R1", agents=[BOT], meta="fulfillment: FBM", subtasks=[c1])

        c2 = task_node("TASK-R2-c", meta="")
        r2 = task_node("TASK-R2", agents=[BOT], meta="fulfillment: FBM", subtasks=[c2])

        bot = self._bot(r1, hook=fail_first)

        # Quét r1 -> lỗi, bật cooldown cho TASK-R1
        bot.meta_inherit_pass({"root": r1}, BOT)
        self.assertFalse(bot.state.autorun_is_cool("meta:TASK-R1", META_INHERIT_BACKOFF_SECONDS))

        # Phục hồi ngân sách lượt quét
        bot._meta_inherit_left = META_INHERIT_PER_SCAN

        # Quét r2 -> vẫn chạy bình thường vì key meta:TASK-R2 còn mát
        done_r2 = bot.meta_inherit_pass({"root": r2}, BOT)
        self.assertEqual(1, len(done_r2))
        self.assertIn("TASK-R2-c", dict(self.writes))


class ServiceInheritTaskMetaEdgeTests(unittest.TestCase):
    """Kiểm thử ca biên trên FlowWebService.inherit_task_meta."""

    def setUp(self) -> None:
        self.service = FlowWebService.__new__(FlowWebService)
        self.writes: List[Dict[str, Any]] = []

    def _inherit(self, values: Dict[str, Any], *, meta: str, project: str = "PROJ-0087") -> Dict[str, Any]:
        detail = {"name": "TASK-CHILD", "status": "Working", "meta": meta, "project": project}

        def write(key: str, token: str, task: str, block: str, **kwargs: Any) -> Dict[str, Any]:
            self.writes.append({"task": task, "block": block, **kwargs})
            return {"name": task}

        with patch.object(self.service, "_erp_credentials", return_value=("k", "t")), \
                patch.object(self.service, "_erp_task_detail", return_value=detail), \
                patch.object(self.service, "_erp_update_task_meta", side_effect=write):
            return self.service.inherit_task_meta("TASK-CHILD", values)

    def test_service_the_con_da_co_khong_ghi_de(self) -> None:
        """Nếu thẻ con trên ERP đã có giá trị, service không ghi đè và không gọi API."""
        outcome = self._inherit(
            {"fulfillment": "FBM", "sales_channel": "Etsy"},
            meta="fulfillment: FBA\nsales_channel: Etsy",
        )
        self.assertEqual({}, outcome["written"])
        self.assertEqual([], self.writes)

    def test_service_chan_cac_o_cam_ngay_tai_duong_ghi(self) -> None:
        """Đường ghi inherit_task_meta tự lọc ô cấm (sku, action_1, parent_task, content)."""
        outcome = self._inherit(
            {
                "sku": "SKU-999",
                "action_1": "idea",
                "parent_task": "TASK-ROOT",
                "content": "Có",
                "_task": "TASK-123",
                "fulfillment": "FBM",
            },
            meta="",
        )
        self.assertEqual({"fulfillment": "FBM"}, outcome["written"])
        self.assertEqual(1, len(self.writes))
        block = self.writes[0]["block"]
        self.assertIn("fulfillment: FBM", block)
        self.assertNotIn("sku", block)
        self.assertNotIn("action", block)
        self.assertNotIn("parent_task", block)
        self.assertNotIn("content", block)


if __name__ == "__main__":
    unittest.main()
