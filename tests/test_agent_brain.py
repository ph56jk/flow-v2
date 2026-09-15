"""Phần đoán ý: câu tự do → mấy ô cần sửa, và chỗ nào phải chịu thua.

Không test nào ở đây gọi ``claude`` thật. Mọi lượt đều đi qua ``runner`` giả —
vừa vì một lượt hỏi thật tốn tiền và mất mấy giây, vừa vì thứ đáng test không
phải là "model có thông minh không" mà là **cái bọc quanh nó**: hàng rào lọc ô,
cách đọc JSON méo, và lời hứa "hỏng thì trả None chứ không ném".
"""

from __future__ import annotations

import json
import subprocess
import unittest

from flow_web.agent_brain import (
    INTENT_BRAIN,
    MAX_VALUE_LEN,
    PROVIDER_CLAUDE,
    PROVIDER_CODEX,
    BrainConfig,
    BrainVerdict,
    build_argv,
    build_brain_hook,
    build_prompt,
    build_stdin,
    describe_card,
    detect_provider,
    understand_freely,
    verdict_reply,
)
from flow_web.agent_chat import ACTION_SET, CardBrief

ON = BrainConfig(enabled=True)


def envelope(body) -> str:
    """Bọc câu trả lời như ``claude -p --output-format json`` vẫn bọc."""
    inner = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    return json.dumps({"result": inner, "is_error": False}, ensure_ascii=False)


def fake(body, *, box=None):
    """Runner giả: nuốt argv, trả về đúng chuỗi mình dựng sẵn."""

    def runner(argv, stdin_text):
        if box is not None:
            box.append((list(argv), stdin_text))
        return body

    return runner


BRIEF = CardBrief(
    task="TASK-1",
    title="Bờm nơ hồng",
    status="Đang làm",
    sku="BT_3_009",
    product="bờm",
    template="mockup-01",
    account="acc32",
    known_accounts=("acc32", "acc16"),
)


class PromptTests(unittest.TestCase):
    """Cái gửi đi phải đủ để hiểu, và tách bạch luật với dữ liệu."""

    def test_ke_ca_gia_tri_dang_co_chu_khong_chi_ten_o(self):
        # "đổi mẫu khác đi" chỉ hiểu được khi biết mẫu hiện tại là gì.
        text = describe_card(BRIEF)
        self.assertIn('Ô template đang là: "mockup-01"', text)
        self.assertIn('Ô sku đang là: "BT_3_009"', text)

    def test_o_acc_lay_ma_da_tra_so(self):
        # ``brief`` không có ô ``acc``; mã đã tra sổ nằm ở ``account``.
        self.assertIn('Ô acc đang là: "acc32"', describe_card(BRIEF))

    def test_ke_ca_so_tay_tai_khoan(self):
        # Model thấy mã có thật thì bớt tật viết lại mã cho "gọn".
        self.assertIn("Sổ tay tài khoản đang biết các mã: acc32, acc16", describe_card(BRIEF))

    def test_so_tay_rong_thi_khong_co_dong_thua(self):
        self.assertNotIn("Sổ tay", describe_card(CardBrief(task="TASK-9")))

    def test_luat_bat_chep_nguyen_xi_ma_acc(self):
        # Mã acc là khoá tra sổ: "acc16" thành "acc-16" là tra không ra nữa.
        from flow_web.agent_brain import SYSTEM_PROMPT
        self.assertIn("nguyên xi", SYSTEM_PROMPT)

    def test_cau_nguoi_ta_noi_nam_rieng_mot_muc(self):
        prompt = build_prompt("@bot đổi mẫu sang mockup-02", BRIEF)
        self.assertIn("THẺ", prompt)
        self.assertIn("CÂU NÓI", prompt)
        # Tiền tố gọi bot bị cắt: nó là cách gọi, không phải nội dung.
        self.assertIn("đổi mẫu sang mockup-02", prompt)
        self.assertNotIn("@bot", prompt.split("CÂU NÓI")[1])


class ParseTests(unittest.TestCase):
    """Model trả về đủ kiểu; chỉ những kiểu dùng được mới đi tiếp."""

    def test_cau_thuong_ra_dung_hai_o(self):
        runner = fake(envelope({
            "edits": {"template": "mockup-bom-02", "product": "bờm nơ hồng"},
            "say": "bạn muốn đổi mẫu và đặt lại tên sản phẩm",
            "refused": "",
        }))
        got = understand_freely("đổi mẫu sang mockup-bom-02 với lại thẻ này là bờm nơ hồng nhé",
                                BRIEF, ON, runner=runner)
        self.assertEqual(dict(got.edits), {"template": "mockup-bom-02", "product": "bờm nơ hồng"})
        self.assertIn("đổi mẫu", got.say)

    def test_o_ngoai_danh_sach_bi_vut(self):
        # Hàng rào thật: chữ trên thẻ là dữ liệu người lạ, và một bình luận
        # hoàn toàn có thể dụ model trả về ``action_1``.
        runner = fake(envelope({"edits": {"acc": "acc16", "action_1": "listing", "status": "Xong"}}))
        got = understand_freely("làm gì đó đi", BRIEF, ON, runner=runner)
        self.assertEqual(dict(got.edits), {"acc": "acc16"})

    def test_ma_acc_di_qua_dung_bo_loc_cua_duong_go_tay(self):
        # ``acc-32`` chứ không phải ``acc32``: đây đúng là thứ ``normalize_account``
        # trả ra cho "ACC 32" ở đường gõ tay. Cùng một câu, hai lối vào, một kết quả.
        runner = fake(envelope({"edits": {"acc": "ACC 32"}}))
        got = understand_freely("chuyển sang acc 32", BRIEF, ON, runner=runner)
        self.assertEqual(dict(got.edits), {"acc": "acc-32"})

    def test_gia_tri_dai_loang_ngoang_bi_vut(self):
        runner = fake(envelope({"edits": {"product": "x" * (MAX_VALUE_LEN + 1)}}))
        got = understand_freely("kể chuyện đi", BRIEF, ON, runner=runner)
        self.assertEqual(got.edits, ())

    def test_xoa_trang_mot_o_van_di_qua(self):
        # Chuỗi rỗng là một lệnh thật (xoá ô), không phải "không có gì".
        runner = fake(envelope({"edits": {"template": ""}}))
        got = understand_freely("bỏ mẫu listing đi", BRIEF, ON, runner=runner)
        self.assertEqual(got.edits, (("template", ""),))

    def test_json_goi_trong_markdown_van_doc_duoc(self):
        runner = fake(envelope('```json\n{"edits": {"sku": "BT_1_002"}}\n```'))
        got = understand_freely("đổi sku", BRIEF, ON, runner=runner)
        self.assertEqual(dict(got.edits), {"sku": "BT_1_002"})

    def test_model_noi_them_truoc_json_van_doc_duoc(self):
        runner = fake(envelope('Được rồi nhé: {"edits": {"sku": "BT_1_003"}} xong.'))
        got = understand_freely("đổi sku", BRIEF, ON, runner=runner)
        self.assertEqual(dict(got.edits), {"sku": "BT_1_003"})

    def test_tu_choi_khac_han_voi_hong(self):
        # Có ``BrainVerdict`` nghĩa là Claude đã đọc; ``edits`` rỗng là cố ý.
        runner = fake(envelope({"edits": {}, "say": "", "refused": "câu này chỉ là lời chào"}))
        got = understand_freely("chào em", BRIEF, ON, runner=runner)
        self.assertIsNotNone(got)
        self.assertEqual(got.edits, ())
        self.assertIn("lời chào", got.refused)


class FailureTests(unittest.TestCase):
    """Mọi kiểu hỏng đều phải ra ``None``, không kiểu nào được ném lên."""

    def test_tat_thi_khong_goi_gi(self):
        box = []
        self.assertIsNone(understand_freely("gì đó", BRIEF, BrainConfig(), runner=fake("{}", box=box)))
        self.assertEqual(box, [])

    def test_cau_rong_khong_ton_mot_luot_hoi(self):
        box = []
        self.assertIsNone(understand_freely("@bot   ", BRIEF, ON, runner=fake("{}", box=box)))
        self.assertEqual(box, [])

    def test_json_meo_ra_none(self):
        self.assertIsNone(understand_freely("gì đó", BRIEF, ON, runner=fake("không phải json")))

    def test_claude_bao_loi_ra_none(self):
        body = json.dumps({"result": "quá tải", "is_error": True}, ensure_ascii=False)
        self.assertIsNone(understand_freely("gì đó", BRIEF, ON, runner=fake(body)))

    def test_het_gio_ra_none_chu_khong_nem(self):
        def runner(argv, stdin_text):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

        self.assertIsNone(understand_freely("gì đó", BRIEF, ON, runner=runner))

    def test_loi_bat_ngo_ra_none_chu_khong_nem(self):
        def runner(argv, stdin_text):
            raise RuntimeError("máy chưa đăng nhập claude")

        self.assertIsNone(understand_freely("gì đó", BRIEF, ON, runner=runner))


class CommandTests(unittest.TestCase):
    """Lượt gọi phải khoá chặt: không tool, không MCP, prompt qua stdin."""

    def _argv(self):
        box = []
        understand_freely("gì đó", BRIEF, ON, runner=fake(envelope({"edits": {}}), box=box))
        return box[0]

    def test_khong_mo_tool_va_khong_nap_mcp(self):
        argv, _ = self._argv()
        self.assertIn("--allowed-tools", argv)
        self.assertEqual(argv[argv.index("--allowed-tools") + 1], "")
        self.assertIn("--strict-mcp-config", argv)

    def test_cau_nguoi_ta_noi_di_qua_stdin_chu_khong_qua_dong_lenh(self):
        # Câu người lạ gõ mà nằm trong argv thì mỗi dấu nháy là một chỗ hỏng.
        argv, stdin_text = self._argv()
        self.assertNotIn("gì đó", " ".join(argv))
        self.assertIn("gì đó", stdin_text)

    def test_luat_nam_o_system_prompt(self):
        argv, _ = self._argv()
        self.assertIn("--append-system-prompt", argv)
        contract = argv[argv.index("--append-system-prompt") + 1]
        for name in ("acc", "product", "sku", "template"):
            self.assertIn(name, contract)


class ProviderTests(unittest.TestCase):
    """Hai đường CLI, một hợp đồng.

    Máy này có ``claude``, máy trung tâm có ``codex`` đăng nhập sẵn.  Cùng một
    câu tiếng Việt phải ra cùng một kiểu phán quyết, nên chỗ đáng test là mấy
    chỗ hai bên **khác nhau**: tên cờ, chỗ nhét luật, và cái bẫy model name.
    """

    def test_doan_duong_tu_ten_lenh(self):
        self.assertEqual(detect_provider("codex"), PROVIDER_CODEX)
        self.assertEqual(detect_provider(r"C:\Users\admin\bin\codex.exe"), PROVIDER_CODEX)
        self.assertEqual(detect_provider("codex.cmd"), PROVIDER_CODEX)
        self.assertEqual(detect_provider("/usr/local/bin/claude"), PROVIDER_CLAUDE)
        # Tên lạ thì về đường mặc định chứ không nổ.
        self.assertEqual(detect_provider("mo-hinh-nao-do"), PROVIDER_CLAUDE)

    def test_noi_thang_duong_thi_thang_ten_lenh(self):
        cfg = BrainConfig(command="chay-agent.cmd", provider="codex")
        self.assertEqual(cfg.resolved_provider(), PROVIDER_CODEX)
        # Chữ vớ vẩn thì bỏ qua, quay về suy từ tên lệnh.
        self.assertEqual(
            BrainConfig(command="codex", provider="linh tinh").resolved_provider(),
            PROVIDER_CODEX,
        )

    def test_argv_codex_khoa_tay_va_doc_stdin(self):
        argv = build_argv(BrainConfig(command="codex"), PROVIDER_CODEX)
        self.assertEqual(argv[1], "exec")
        self.assertIn("--sandbox", argv)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertIn("--skip-git-repo-check", argv)
        # ``-`` cuối cùng mới là thứ bảo nó đọc prompt từ stdin.
        self.assertEqual(argv[-1], "-")
        self.assertNotIn("--append-system-prompt", argv)

    def test_argv_codex_khong_nhan_ten_model_cua_claude(self):
        # Đặt sẵn FLOW_AGENT_BRAIN_MODEL=haiku cho cả nhà rồi đổi lệnh sang
        # codex là chuyện thường; đưa "-m haiku" cho codex thì hỏng ngay.
        argv = build_argv(BrainConfig(command="codex", model="haiku"), PROVIDER_CODEX)
        self.assertNotIn("-m", argv)
        argv = build_argv(BrainConfig(command="codex", model="gpt-5"), PROVIDER_CODEX)
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-5")

    def test_argv_claude_van_co_model_mac_dinh(self):
        argv = build_argv(BrainConfig(command="claude"), PROVIDER_CLAUDE)
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")

    def test_tep_cau_cuoi_chi_hien_khi_co_cho_ghi(self):
        khong = build_argv(BrainConfig(command="codex"), PROVIDER_CODEX)
        self.assertNotIn("--output-last-message", khong)
        co = build_argv(BrainConfig(command="codex"), PROVIDER_CODEX, result_path="/tmp/x.txt")
        self.assertEqual(co[co.index("--output-last-message") + 1], "/tmp/x.txt")

    def test_codex_nhet_luat_vao_dau_prompt(self):
        # Không có --append-system-prompt thì luật phải đi cùng dữ liệu, mà
        # vẫn tách bằng nhãn để chữ người lạ không đứng lẫn vào chỗ đặt luật.
        text = build_stdin(PROVIDER_CODEX, "đổi acc sang acc16", BRIEF)
        self.assertIn("CHỈ được ghi những ô sau", text)
        self.assertIn("CÂU NÓI", text)
        self.assertIn("đổi acc sang acc16", text)
        # Đường claude thì luật nằm ở argv, không lặp lại trong stdin.
        self.assertNotIn("CHỈ được ghi những ô sau", build_stdin(PROVIDER_CLAUDE, "x", BRIEF))

    def test_codex_tra_json_tran_van_doc_duoc(self):
        # ``codex exec --output-last-message`` cho ra đúng câu cuối, không có
        # phong bì ``result`` như claude.
        box = []
        verdict = understand_freely(
            "cho về acc16 nhé",
            BRIEF,
            BrainConfig(enabled=True, command="codex"),
            runner=fake('{"edits":{"acc":"acc16"},"say":"đổi acc","refused":""}', box=box),
        )
        self.assertEqual(verdict.edits, (("acc", "acc16"),))
        argv, stdin_text = box[0]
        self.assertEqual(argv[1], "exec")
        self.assertNotIn("cho về acc16 nhé", " ".join(argv))
        self.assertIn("cho về acc16 nhé", stdin_text)


class VerdictReplyTests(unittest.TestCase):
    """Câu trả lời dựng ra phải giống hệt đường gõ tay, chỉ thêm phần diễn giải."""

    def test_di_qua_dung_duong_ghi_cua_lenh_sua(self):
        reply = verdict_reply(BrainVerdict(edits=(("acc", "acc16"),), say="bạn muốn đổi shop"), BRIEF)
        self.assertEqual(reply.action, ACTION_SET)
        self.assertEqual(reply.edits, (("acc", "acc16"),))
        self.assertEqual(reply.intent, INTENT_BRAIN)

    def test_noi_ra_minh_hieu_the_nao(self):
        reply = verdict_reply(BrainVerdict(edits=(("acc", "acc16"),), say="bạn muốn đổi shop"), BRIEF)
        self.assertIn("Tôi hiểu là bạn muốn đổi shop.", reply.lines[0])

    def test_khong_cham_cau_hai_lan(self):
        reply = verdict_reply(BrainVerdict(edits=(("acc", "acc16"),), say="bạn muốn đổi shop."), BRIEF)
        self.assertEqual("Tôi hiểu là bạn muốn đổi shop.", reply.lines[0])

    def test_model_khong_noi_gi_thi_van_co_cau_dan(self):
        reply = verdict_reply(BrainVerdict(edits=(("acc", "acc16"),), say="  "), BRIEF)
        self.assertTrue(reply.lines[0].startswith("Tôi hiểu là "))

    def test_canh_bao_cua_duong_go_tay_van_hien_nguyen(self):
        # acc lạ chưa có trong sổ: nhắc y như khi người ta gõ "acc: acc99".
        reply = verdict_reply(BrainVerdict(edits=(("acc", "acc99"),)), BRIEF)
        self.assertTrue(any("sổ tay tài khoản chưa có" in line for line in reply.lines))

    def test_sku_sai_dang_van_bi_nhac(self):
        reply = verdict_reply(BrainVerdict(edits=(("sku", "linh tinh"),)), BRIEF)
        self.assertTrue(any("không đúng dạng" in line for line in reply.lines))

    def test_khong_rut_ra_o_nao_thi_khong_dung_cau_tra_loi_cu(self):
        self.assertIsNone(verdict_reply(BrainVerdict(refused="chỉ là lời chào"), BRIEF))


class HookTests(unittest.TestCase):
    def test_tat_thi_khong_co_hook(self):
        self.assertIsNone(build_brain_hook(BrainConfig()))

    def test_bat_thi_hook_dua_thang_toi_phan_doan_y(self):
        hook = build_brain_hook(ON, runner=fake(envelope({"edits": {"product": "bờm nơ"}})))
        self.assertEqual(dict(hook("gì đó", BRIEF).edits), {"product": "bờm nơ"})

    def test_doc_bien_moi_truong(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"FLOW_AGENT_BRAIN": "1", "FLOW_AGENT_BRAIN_MAX_CALLS": "2"}):
            cfg = BrainConfig.from_env()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.max_calls, 2)

    def test_mac_dinh_la_tat(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(BrainConfig.from_env().enabled)


if __name__ == "__main__":
    unittest.main()
