"""Gọi model qua Codex CLI, mà giờ CLI cầm công cụ thật một cách có chủ ý.

QUYẾT ĐỊNH 2026-09-01: agent điều phối không còn là "đường truyền chữ" —
Codex CLI chạy Bash, đọc/ghi file, mạng, MCP thật ngay trong REPO_DIR đã
checkout sẵn nhánh ``agent/<id>`` (xem docstring đầu ``runner/orchestrator_runner.py``).
Ba lớp giữ an toàn cũ (phạm vi glob, danh sách bảo vệ, nhánh ``agent/<id>``)
không còn đứng TRƯỚC khi ghi (không còn ``write_files()`` nào để lọc qua) mà
chuyển thành ``validate_touched_paths()`` — soi lại toàn bộ diff SAU khi model
đã tự ghi xong, trước khi cho phép sang bước duyệt.

Trước bản này, đo thật trên máy trung tâm ngày 2026-08-26 với ``-s
read-only``: lệnh shell do model sinh ra chết ngay lúc khởi tạo tiến trình
(``STATUS_DLL_INIT_FAILED``, dấu hiệu AppContainer chặn) và một lượt loay
hoay với công cụ đã chết chạy quá 5 phút không ra kết quả. Đó là lý do sandbox
bị bỏ hẳn thay vì nới từng phần — công cụ chết nửa vời còn tệ hơn công cụ chạy
thật có soi lại.

Test dưới đây neo đúng những gì còn lại: cờ full quyền phải có mặt (không bị
thụt lùi về sandbox), work_dir của codex phải là chính REPO_DIR (không phải
thư mục tạm), và lược đồ đầu ra không còn khoá ``files``.

Chạy:  python3 automation_center/tests/test_codex_provider.py
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

CENTER = Path(__file__).resolve().parent.parent
RUNNER = CENTER / "runner" / "orchestrator_runner.py"

# Cờ nào xuất hiện là mở thêm quyền NGOÀI những gì bản 2026-09-01 đã chủ ý
# bật. "workspace-write" và "danger-full-access" là hai cách khác để mở ghi
# (thừa, vì "--dangerously-bypass-approvals-and-sandbox" đã bao trùm); "--add-dir"
# mở thêm thư mục ghi được ngoài work_dir; "--approve-for-me" và
# "--dangerously-bypass-hook-trust" không liên quan tới lượt gọi một lần này.
# Không cờ nào trong danh sách này được codex_argv() thêm vào — nếu có, nghĩa
# là quyền đang nới rộng hơn thiết kế đã chốt mà không ai để ý.
CO_MO_QUYEN_NGOAI_Y_DINH = (
    "workspace-write",
    "danger-full-access",
    "--add-dir",
    "--approve-for-me",
    "--dangerously-bypass-hook-trust",
)


def nap_runner():
    spec = importlib.util.spec_from_file_location("orchestrator_runner_duoi_test", RUNNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = nap_runner()


def codex_gia(tra_loi: str, *, ma_thoat: int = 0, stderr: str = "", ghi_file: bool = True):
    """Đóng vai ``subprocess.run`` cho một lượt gọi codex.

    Ghi lại argv và stdin để test soi, rồi ghi ``tra_loi`` vào đúng file mà
    ``--output-last-message`` chỉ tới — y như codex thật.
    """
    da_goi = {}

    def chay(argv, **kwargs):
        da_goi["argv"] = list(argv)
        da_goi["stdin"] = kwargs.get("input")
        da_goi["timeout"] = kwargs.get("timeout")
        if ghi_file:
            vi_tri = argv.index("--output-last-message")
            Path(argv[vi_tri + 1]).write_text(tra_loi, encoding="utf-8")
        return SimpleNamespace(returncode=ma_thoat, stdout="", stderr=stderr)

    return chay, da_goi


TRA_LOI_MAU = json.dumps({
    "action": "answer",
    "summary": "xong",
    "paths": None,
    "commands": None,
}, ensure_ascii=False)


class KhoaTayCodex(unittest.TestCase):
    def test_full_quyen_duoc_bat_co_chu_dich(self):
        argv = runner.codex_argv(
            "codex",
            work_dir=Path("/tmp/lam-viec"),
            schema_path=Path("/tmp/lam-viec/schema.json"),
            out_path=Path("/tmp/lam-viec/ra.json"),
        )
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", argv,
                      "bản 2026-09-01 cố ý bỏ sandbox — thiếu cờ này là thụt lùi")
        self.assertNotIn("--sandbox", argv,
                         "--sandbox read-only là thiết kế cũ, không còn dùng nữa")
        for co in CO_MO_QUYEN_NGOAI_Y_DINH:
            with self.subTest(co=co):
                self.assertNotIn(co, argv,
                                 f"{co} mở thêm quyền ngoài những gì bản 2026-09-01 đã chốt")

    def test_thu_muc_lam_viec_la_chinh_repo_cua_agent(self):
        # Từ bản có công cụ thật, codex đứng ngay trong REPO_DIR đã checkout
        # sẵn nhánh agent/<id> — không còn thư mục tạm rỗng nào để cách ly nó
        # khỏi phần còn lại của repo (bao gồm cả CLAUDE.md/.codex nếu có).
        with tempfile.TemporaryDirectory() as repo:
            cu = runner.REPO_DIR
            runner.REPO_DIR = Path(repo)
            try:
                chay, da_goi = codex_gia(TRA_LOI_MAU)
                runner.call_codex([{"role": "user", "content": "chào"}], chay=chay)
            finally:
                runner.REPO_DIR = cu
            argv = da_goi["argv"]
            self.assertIn("--cd", argv)
            lam_viec = Path(argv[argv.index("--cd") + 1]).resolve()
            repo_path = Path(repo).resolve()
            self.assertEqual(lam_viec, repo_path,
                             "codex phải đứng thẳng trong REPO_DIR, không phải thư mục tạm")

    def test_loi_nhac_di_qua_stdin_va_giu_du_moi_luot(self):
        # Vòng "read" của plan_change gửi lại cả lịch sử mỗi lượt. Ép lời nhắc
        # qua argv thì Windows cắt ở ~32k ký tự và agent lặng lẽ mất ngữ cảnh.
        chay, da_goi = codex_gia(TRA_LOI_MAU)
        runner.call_codex([
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

    def test_noi_thang_rang_co_cong_cu_that_dung_duoc(self):
        # Nói ngược ("không có công cụ nào") trong khi cờ dòng lệnh đã mở toang
        # quyền là mời model thử shell tới khi timeout — đúng thứ bản sandbox
        # cũ từng gặp. Lời nhắc phải khớp với cờ thật.
        chay, da_goi = codex_gia(TRA_LOI_MAU)
        runner.call_codex([{"role": "user", "content": "chào"}], chay=chay)
        stdin = (da_goi["stdin"] or "")
        self.assertRegex(stdin, r"có công cụ thật")
        self.assertRegex(stdin.lower(), r"chạy shell")

    def test_co_timeout_cung(self):
        chay, da_goi = codex_gia(TRA_LOI_MAU)
        runner.call_codex([{"role": "user", "content": "chào"}], chay=chay)
        self.assertTrue(da_goi["timeout"], "thiếu timeout thì một lượt hỏng treo runner vô hạn")


class ChonNhaCungCap(unittest.TestCase):
    def test_khong_co_khoa_thi_dung_codex(self):
        # Chữ ký mới chen claude vào giữa (auto: openai → claude → codex), nên
        # codex chỉ được chọn khi vắng cả khoá API lẫn claude CLI.
        self.assertEqual("codex", runner.chon_nha_cung_cap("auto", "", "/usr/bin/codex", None))

    def test_co_khoa_thi_giu_duong_http_cu(self):
        self.assertEqual("openai", runner.chon_nha_cung_cap("auto", "sk-abc", "/usr/bin/codex"))

    def test_ep_duoc_tung_ben(self):
        self.assertEqual("codex", runner.chon_nha_cung_cap("codex", "sk-abc", "/usr/bin/codex"))
        self.assertEqual("openai", runner.chon_nha_cung_cap("openai", "sk-abc", None))

    def test_khong_co_duong_nao_thi_bao_thang(self):
        # Im lặng chọn bừa ở đây nghĩa là runner sống dậy rồi hỏng ở yêu cầu đầu
        # tiên của một người thật, chứ không phải lúc khởi động.
        for cai_dat, khoa, codex, claude in (
            ("auto", "", None, None),
            ("codex", "sk-abc", None, "/usr/bin/claude"),
            ("openai", "", "/usr/bin/codex", "/usr/bin/claude"),
            ("claude", "sk-abc", "/usr/bin/codex", None),
        ):
            with self.subTest(cai_dat=cai_dat):
                with self.assertRaises(RuntimeError):
                    runner.chon_nha_cung_cap(cai_dat, khoa, codex, claude)


class DocKetQua(unittest.TestCase):
    def test_doc_duoc_json_tran(self):
        self.assertEqual({"action": "answer"}, runner.doc_ket_qua_codex('{"action": "answer"}'))

    def test_doc_duoc_json_boc_trong_hang_rao(self):
        raw = 'Đây là kết quả:\n```json\n{"action": "answer", "summary": "ừ"}\n```\n'
        self.assertEqual("answer", runner.doc_ket_qua_codex(raw)["action"])

    def test_khong_phai_json_thi_bao_loi_kem_nguyen_van(self):
        with self.assertRaises(RuntimeError) as bat:
            runner.doc_ket_qua_codex("xin lỗi, tôi không làm được")
        self.assertIn("xin lỗi", str(bat.exception))

    def test_codex_thoat_loi_thi_khong_nuot(self):
        chay, _ = codex_gia("", ma_thoat=1, stderr="not logged in", ghi_file=False)
        with self.assertRaises(RuntimeError) as bat:
            runner.call_codex([{"role": "user", "content": "chào"}], chay=chay)
        self.assertIn("not logged in", str(bat.exception))

    def test_qua_gio_thi_bao_loi_chu_khong_treo(self):
        def chay(argv, **kwargs):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout") or 1)

        with self.assertRaises(RuntimeError):
            runner.call_codex([{"role": "user", "content": "chào"}], chay=chay)


class LuocDoDauRaDungChung(unittest.TestCase):
    """``OUTPUT_SCHEMA`` giờ dùng chung cho cả codex (``--output-schema``) lẫn
    Claude (``--json-schema``) — không còn khoá ``files``, vì model tự ghi
    file bằng công cụ thật thay vì trả nội dung qua JSON."""

    def test_du_bon_hanh_dong_va_moi_khoa_runner_doc(self):
        # Lược đồ thiếu một action nghĩa là model không nói ra được nó, và cái
        # nhánh xử lý tương ứng trong plan_change() thành mã chết mà không ai hay.
        luoc_do = runner.OUTPUT_SCHEMA
        self.assertEqual(
            {"read", "answer", "edit", "bot"},
            set(luoc_do["properties"]["action"]["enum"]))
        for khoa in ("action", "summary", "paths", "commands"):
            with self.subTest(khoa=khoa):
                self.assertIn(khoa, luoc_do["properties"])
                self.assertIn(khoa, luoc_do["required"])
        self.assertNotIn(
            "files", luoc_do["properties"],
            "model tự ghi file bằng công cụ thật; \"files\" trong JSON là thiết kế cũ")
        lenh = luoc_do["properties"]["commands"]["items"]
        self.assertEqual({"bot_id", "command", "prompt", "count", "aspect"}, set(lenh["properties"]))

    def test_luoc_do_la_json_hop_le(self):
        json.loads(json.dumps(runner.OUTPUT_SCHEMA))


if __name__ == "__main__":
    unittest.main()
