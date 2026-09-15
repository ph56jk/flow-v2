"""Gọi model qua Claude CLI, mà giờ CLI cầm công cụ thật một cách có chủ ý.

QUYẾT ĐỊNH 2026-09-01: cùng lý do với ``test_codex_provider.py`` — agent điều
phối không còn là "đường truyền chữ". Claude CLI chạy Bash, Read, Write, Edit,
MCP thật ngay trong REPO_DIR đã checkout sẵn nhánh ``agent/<id>``. Ba lớp giữ
an toàn cũ (phạm vi glob, danh sách bảo vệ, nhánh ``agent/<id>``) không còn
đứng TRƯỚC khi ghi mà chuyển thành ``validate_touched_paths()`` — soi lại toàn
bộ diff SAU khi model đã tự ghi xong.

Trước bản này, "khoá tay" gồm bốn chốt: ``--allowed-tools ""`` (không công cụ
nào), ``--strict-mcp-config`` không kèm cấu hình, thư mục làm việc là thư mục
tạm rỗng chứ không phải bản repo, và lời nhắc đi qua stdin. Ba chốt đầu bị bỏ
hẳn (thay bằng ``--dangerously-skip-permissions`` + chạy thẳng trong REPO_DIR
— đọc ``CLAUDE.md``/``.claude/`` của repo giờ là điều muốn, không phải rủi
ro); chốt thứ tư — lời nhắc qua stdin, vì dòng lệnh Windows cắt ở ~32k ký tự —
vẫn còn nguyên, nên test tương ứng không đổi.

Khác codex, ``--output-format json`` của claude không in thẳng câu trả lời:
nó bọc trong một phong bì ``{"type": "result", "is_error": ..., "result":
"<chuỗi>"}``.  Phải bóc phong bì trước, đọc JSON nghiệp vụ nằm trong
``result`` sau — và ``is_error`` phải nổ thành lỗi đọc được chứ không lặng lẽ
đưa rác cho ``plan_change()``.

Chạy:  python3 automation_center/tests/test_claude_provider.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

CENTER = Path(__file__).resolve().parent.parent
RUNNER = CENTER / "runner" / "orchestrator_runner.py"

# Cờ nào xuất hiện là mở thêm quyền NGOÀI những gì bản 2026-09-01 đã chủ ý bật
# (``--dangerously-skip-permissions``). "bypassPermissions"/"acceptEdits" là
# giá trị của --permission-mode — thừa, vì --dangerously-skip-permissions đã
# bao trùm; "--add-dir" mở thêm thư mục ngoài cwd; "--mcp-config" cắm thêm
# server công cụ ngoài cấu hình sẵn có của user; "--permission-prompt-tool"
# giao việc duyệt quyền cho một tool trả lời hộ (không cần, vì không còn hỏi
# quyền nữa); "--dangerously-bypass-approvals-and-sandbox" là cờ của codex,
# không có chỗ trong argv của claude.
CO_MO_QUYEN_NGOAI_Y_DINH = (
    "--dangerously-bypass-approvals-and-sandbox",
    "bypassPermissions",
    "acceptEdits",
    "--add-dir",
    "--mcp-config",
    "--permission-prompt-tool",
)


def nap_runner():
    spec = importlib.util.spec_from_file_location("orchestrator_runner_duoi_test_claude", RUNNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = nap_runner()


TRA_LOI_MAU = json.dumps({
    "action": "answer",
    "summary": "xong",
    "paths": None,
    "commands": None,
}, ensure_ascii=False)


def claude_gia(tra_loi: str, *, ma_thoat: int = 0, stderr: str = "",
               phong_bi: dict | None = None, stdout_tho: str | None = None):
    """Đóng vai ``subprocess.run`` cho một lượt gọi claude.

    Ghi lại argv, stdin, cwd và timeout để test soi, rồi in ra stdout đúng
    phong bì JSON mà ``--output-format json`` của claude thật in — trừ khi
    test đưa sẵn ``phong_bi`` (phong bì tự chế) hay ``stdout_tho`` (stdout
    không phải phong bì).
    """
    da_goi = {}

    def chay(argv, **kwargs):
        da_goi["argv"] = list(argv)
        da_goi["stdin"] = kwargs.get("input")
        da_goi["timeout"] = kwargs.get("timeout")
        da_goi["cwd"] = kwargs.get("cwd")
        if stdout_tho is not None:
            stdout = stdout_tho
        else:
            vo = phong_bi if phong_bi is not None else {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "duration_ms": 1234,
                "num_turns": 1,
                "session_id": "phien-gia",
                "total_cost_usd": 0.01,
                "result": tra_loi,
            }
            stdout = json.dumps(vo, ensure_ascii=False)
        return SimpleNamespace(returncode=ma_thoat, stdout=stdout, stderr=stderr)

    return chay, da_goi


class KhoaTayClaude(unittest.TestCase):
    def test_full_quyen_duoc_bat_co_chu_dich(self):
        argv = runner.claude_argv("claude", work_dir=Path("/tmp/lam-viec"), model="sonnet")
        self.assertIn("-p", argv)
        self.assertEqual("json", argv[argv.index("--output-format") + 1])
        self.assertIn("--dangerously-skip-permissions", argv,
                      "bản 2026-09-01 cố ý bỏ lớp hỏi quyền — thiếu cờ này là thụt lùi")
        self.assertIn("--json-schema", argv,
                      "OUTPUT_SCHEMA phải được ép qua --json-schema, dùng chung với codex")
        self.assertEqual(
            runner.OUTPUT_SCHEMA,
            json.loads(argv[argv.index("--json-schema") + 1]))
        self.assertNotIn("--allowed-tools", argv,
                         "--allowed-tools là thiết kế cũ (chuỗi rỗng để cấm mọi công cụ)")
        self.assertNotIn("--strict-mcp-config", argv,
                         "--strict-mcp-config là thiết kế cũ, không còn ý nghĩa khi đã "
                         "--dangerously-skip-permissions")
        for co in CO_MO_QUYEN_NGOAI_Y_DINH:
            with self.subTest(co=co):
                self.assertNotIn(co, argv,
                                 f"{co} mở thêm quyền ngoài những gì bản 2026-09-01 đã chốt")

    def test_model_truyen_xuong_dung_co(self):
        argv = runner.claude_argv("claude", work_dir=Path("/tmp/lam-viec"), model="opus")
        self.assertEqual("opus", argv[argv.index("--model") + 1])

    def test_loi_nhac_di_qua_stdin_va_giu_du_moi_luot(self):
        # Vòng "read" của plan_change gửi lại cả lịch sử mỗi lượt.  Ép lời nhắc
        # qua argv thì Windows cắt ở ~32k ký tự và agent lặng lẽ mất ngữ cảnh.
        chay, da_goi = claude_gia(TRA_LOI_MAU)
        runner.call_claude([
            {"role": "system", "content": "luật chơi"},
            {"role": "user", "content": "yêu cầu gốc"},
            {"role": "assistant", "content": '{"action":"read"}'},
            {"role": "user", "content": "nội dung file vừa đọc"},
        ], chay=chay)
        stdin = da_goi["stdin"] or ""
        for manh in ("luật chơi", "yêu cầu gốc", '{"action":"read"}', "nội dung file vừa đọc"):
            with self.subTest(manh=manh):
                self.assertIn(manh, stdin)
        self.assertNotIn("luật chơi", " ".join(da_goi["argv"]))

    def test_thu_muc_lam_viec_la_chinh_repo_cua_agent(self):
        # Từ bản có công cụ thật, claude đứng ngay trong REPO_DIR đã checkout
        # sẵn nhánh agent/<id> — đọc CLAUDE.md/.claude/ của chính repo giờ là
        # điều muốn (một phiên Claude Code thường cũng vậy), không phải rủi ro
        # cần cách ly bằng thư mục tạm rỗng như thiết kế cũ.
        with tempfile.TemporaryDirectory() as repo:
            cu = runner.REPO_DIR
            runner.REPO_DIR = Path(repo)
            chay, da_goi = claude_gia(TRA_LOI_MAU)
            try:
                runner.call_claude([{"role": "user", "content": "chào"}], chay=chay)
            finally:
                runner.REPO_DIR = cu
            lam_viec = da_goi.get("cwd")
            self.assertTrue(lam_viec, "call_claude phải trỏ CLI vào REPO_DIR qua cwd")
            self.assertEqual(Path(lam_viec).resolve(), Path(repo).resolve(),
                             "claude phải đứng thẳng trong REPO_DIR, không phải thư mục tạm")

    def test_co_timeout_cung(self):
        chay, da_goi = claude_gia(TRA_LOI_MAU)
        runner.call_claude([{"role": "user", "content": "chào"}], chay=chay)
        self.assertEqual(runner.OPENAI_TIMEOUT, da_goi["timeout"],
                         "thiếu timeout thì một lượt hỏng treo runner vô hạn")


class BocPhongBi(unittest.TestCase):
    def test_boc_phong_bi_va_tra_dung_doi_tuong_nghiep_vu(self):
        chay, _ = claude_gia(TRA_LOI_MAU)
        ket = runner.call_claude([{"role": "user", "content": "chào"}], chay=chay)
        self.assertEqual(json.loads(TRA_LOI_MAU), ket)

    def test_phong_bi_bao_loi_thi_no_chu_khong_tra_rac(self):
        # is_error mà vẫn trả về được nghĩa là plan_change nhận rác và ghi rác.
        cac_vo = (
            {"type": "result", "subtype": "error_during_execution", "is_error": True,
             "session_id": "phien-gia", "result": "Execution failed: hỏng giữa chừng"},
            # subtype error_max_turns của claude thật KHÔNG có khoá "result";
            # bóc phong bì mà mò thẳng vo["result"] là KeyError chứ không phải
            # thông báo đọc được.
            {"type": "result", "subtype": "error_max_turns", "is_error": True,
             "session_id": "phien-gia"},
        )
        for vo in cac_vo:
            with self.subTest(subtype=vo["subtype"]):
                chay, _ = claude_gia("", phong_bi=vo)
                with self.assertRaises(RuntimeError) as bat:
                    runner.call_claude([{"role": "user", "content": "chào"}], chay=chay)
                # "Đọc được" nghĩa là chi tiết trong phong bì phải lên tới log:
                # có "result" thì nguyên văn nó, không có thì ít nhất subtype.
                self.assertIn(vo.get("result") or vo["subtype"], str(bat.exception))

    def test_json_nghiep_vu_boc_trong_hang_rao_van_boc_duoc(self):
        raw = 'Đây là kết quả:\n```json\n{"action": "answer", "summary": "ừ"}\n```\n'
        chay, _ = claude_gia(raw)
        ket = runner.call_claude([{"role": "user", "content": "chào"}], chay=chay)
        self.assertEqual("answer", ket["action"])

    def test_json_kep_giua_hai_cau_dan_van_boc_duoc(self):
        raw = 'Tôi đã xem xong. {"action": "answer", "summary": "ừ"} Mong là đúng ý.'
        chay, _ = claude_gia(raw)
        ket = runner.call_claude([{"role": "user", "content": "chào"}], chay=chay)
        self.assertEqual("answer", ket["action"])

    def test_khong_phai_json_thi_bao_loi_kem_nguyen_van(self):
        chay, _ = claude_gia("xin lỗi, tôi không làm được")
        with self.assertRaises(RuntimeError) as bat:
            runner.call_claude([{"role": "user", "content": "chào"}], chay=chay)
        self.assertIn("xin lỗi", str(bat.exception))

    def test_stdout_khong_phai_phong_bi_thi_bao_loi(self):
        chay, _ = claude_gia("", stdout_tho="Segmentation fault")
        with self.assertRaises(RuntimeError) as bat:
            runner.call_claude([{"role": "user", "content": "chào"}], chay=chay)
        self.assertTrue(str(bat.exception).strip(), "lỗi phải có thông báo đọc được")

    def test_thoat_loi_thi_khong_nuot_stderr(self):
        chay, _ = claude_gia("", ma_thoat=127, stderr="'node' is not recognized as an internal command")
        with self.assertRaises(RuntimeError) as bat:
            runner.call_claude([{"role": "user", "content": "chào"}], chay=chay)
        self.assertIn("not recognized", str(bat.exception))

    def test_chua_dang_nhap_thi_chi_duong_dang_nhap(self):
        # Người vận hành nhìn log lúc 2 giờ sáng phải biết ngay việc cần làm là
        # mở phiên trên máy trung tâm và chạy `claude login` — không phải đi mò.
        chay, _ = claude_gia("", ma_thoat=1, stderr="Invalid API key · Please run /login")
        with self.assertRaises(RuntimeError) as bat:
            runner.call_claude([{"role": "user", "content": "chào"}], chay=chay)
        thong_bao = str(bat.exception).lower()
        self.assertIn("claude", thong_bao)
        self.assertIn("login", thong_bao)

    def test_qua_gio_thi_bao_loi_nhac_dung_bien_moi_truong(self):
        def chay(argv, **kwargs):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout") or 1)

        with self.assertRaises(RuntimeError) as bat:
            runner.call_claude([{"role": "user", "content": "chào"}], chay=chay)
        self.assertIn("OPENAI_TIMEOUT_SECONDS", str(bat.exception),
                      "không nhắc tên biến thì người vận hành không biết vặn nút nào")


class ChonNhaCungCapVoiClaude(unittest.TestCase):
    def test_ep_claude_ma_khong_co_binary_thi_chi_cach_cai(self):
        with self.assertRaises(RuntimeError) as bat:
            runner.chon_nha_cung_cap("claude", "", "/usr/bin/codex", None)
        thong_bao = str(bat.exception)
        self.assertIn("npm install -g @anthropic-ai/claude-code", thong_bao)
        self.assertIn("CLAUDE_BIN", thong_bao)

    def test_auto_co_ca_hai_cli_thi_chon_claude(self):
        self.assertEqual("claude", runner.chon_nha_cung_cap(
            "auto", "", "/usr/bin/codex", "/usr/bin/claude"))

    def test_auto_co_khoa_api_thi_van_di_duong_http_cu(self):
        self.assertEqual("openai", runner.chon_nha_cung_cap(
            "auto", "sk-abc", "/usr/bin/codex", "/usr/bin/claude"))

    def test_ep_duoc_claude_khi_co_binary(self):
        self.assertEqual("claude", runner.chon_nha_cung_cap(
            "claude", "sk-abc", None, "/usr/bin/claude"))

    def test_chu_ky_ba_tham_so_kieu_cu_van_goi_duoc(self):
        # Chỗ gọi cũ trong call_model()/main() và test cũ đều truyền 3 tham số;
        # thêm claude mà phá chữ ký là hỏng cả những chỗ chưa kịp đổi.
        self.assertEqual("codex", runner.chon_nha_cung_cap("auto", "", "/usr/bin/codex"))
        self.assertEqual("openai", runner.chon_nha_cung_cap("openai", "sk-abc", None))


class NoiVaoCallModel(unittest.TestCase):
    def test_call_model_re_dung_duong_claude(self):
        # chon_nha_cung_cap trả "claude" mà call_model không biết rẽ thì hoặc
        # nổ, hoặc âm thầm đi đường khác — cả hai đều hỏng trước mặt người chờ.
        def khong_duoc_goi(ten):
            def _no(*_a, **_k):
                raise AssertionError(f"call_model rẽ nhầm sang {ten}")
            return _no

        with tempfile.TemporaryDirectory() as goc:
            binary = Path(goc) / "claude.cmd"
            binary.write_text("@echo off\r\n", encoding="utf-8")
            da_nhan = {}

            def claude_gia_lam(messages, **_):
                da_nhan["messages"] = messages
                return {"action": "answer", "summary": "xong"}

            cu = (runner.MODEL_PROVIDER, runner.CLAUDE_BIN, runner.call_claude,
                  runner.call_chatgpt, runner.call_codex)
            runner.MODEL_PROVIDER = "claude"
            runner.CLAUDE_BIN = str(binary)
            runner.call_claude = claude_gia_lam
            runner.call_chatgpt = khong_duoc_goi("openai")
            runner.call_codex = khong_duoc_goi("codex")
            try:
                ket = runner.call_model([{"role": "user", "content": "chào"}])
            finally:
                (runner.MODEL_PROVIDER, runner.CLAUDE_BIN, runner.call_claude,
                 runner.call_chatgpt, runner.call_codex) = cu
            self.assertEqual("answer", ket.get("action"))
            self.assertEqual([{"role": "user", "content": "chào"}], da_nhan["messages"])


class TimCliTrongAppData(unittest.TestCase):
    def test_which_bo_cuoc_van_tim_ra_claude_cmd_trong_appdata(self):
        # PATH của Scheduled Task kiểu S4U không phải PATH của phiên đăng nhập:
        # shutil.which trả None dù `claude` gõ tay vẫn chạy.  %APPDATA%\npm là
        # chỗ npm install -g đặt file, nên phải thử thêm bằng tay.
        with tempfile.TemporaryDirectory() as goc:
            npm = Path(goc) / "npm"
            npm.mkdir()
            cmd = npm / "claude.cmd"
            cmd.write_text("@echo off\r\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"APPDATA": goc}), \
                    mock.patch.object(runner.shutil, "which", lambda *_a, **_k: None):
                self.assertEqual(str(cmd), runner._tim_cli("", "claude"))
                self.assertEqual(str(cmd), runner.tim_claude())

    def test_khong_dau_co_thi_tra_none_chu_khong_doan(self):
        with tempfile.TemporaryDirectory() as goc:
            with mock.patch.dict(os.environ, {"APPDATA": goc}), \
                    mock.patch.object(runner.shutil, "which", lambda *_a, **_k: None):
                self.assertIsNone(runner.tim_claude())

    def test_duong_dan_chi_dinh_phai_ton_tai(self):
        self.assertIsNone(runner.tim_claude("/duong/dan/khong/ton/tai/claude.cmd"))
        with tempfile.NamedTemporaryFile(suffix=".cmd") as tep:
            self.assertEqual(tep.name, runner.tim_claude(tep.name))


class DocKetQuaCodexVanCon(unittest.TestCase):
    def test_lop_boc_van_con_va_van_boc_duoc(self):
        # Nếu phần bóc JSON được tách thành hàm chung cho cả hai CLI thì
        # doc_ket_qua_codex vẫn phải còn làm lớp bọc mỏng: test cũ và mọi chỗ
        # gọi cũ đều trỏ vào tên đó.
        self.assertTrue(callable(getattr(runner, "doc_ket_qua_codex", None)),
                        "doc_ket_qua_codex biến mất khỏi orchestrator_runner")
        self.assertEqual({"action": "answer"}, runner.doc_ket_qua_codex('{"action": "answer"}'))
        raw = 'Kết quả:\n```json\n{"action": "read"}\n```\n'
        self.assertEqual("read", runner.doc_ket_qua_codex(raw)["action"])


if __name__ == "__main__":
    unittest.main()
