"""Agent điều phối điều khiển bot khác: ranh giới ở phía runner.

Quyền thật nằm ở Worker — nhánh ``bot_action`` kiểm lại ``capability(role,
"run")`` rồi chạy đúng lõi mà nút bấm trên web dùng.  Nhưng runner là nơi
quyết định *có gửi lệnh nào đi hay không*, và nó cũng là nơi duy nhất chạm vào
git.  Test này khoá hai điều: runner không rò tên bot cho người không có
quyền, và một yêu cầu điều khiển bot không được đụng vào repo.

Chạy:  python3 automation_center/tests/test_orchestrator_bot.py
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CENTER = HERE.parent


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "orchestrator_runner", CENTER / "runner" / "orchestrator_runner.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load_runner()

BOTS = [
    {"id": "bot-anh", "name": "Agent tạo ảnh", "status": "active"},
    {"id": "bot-erp", "name": "Đăng ERP", "status": "paused"},
]


class NguCanhBot(unittest.TestCase):
    def test_khong_co_quyen_thi_khong_thay_ten_bot(self):
        # Center vẫn chặn lần nữa, nhưng đưa danh sách bot cho một người không
        # điều khiển được bot là mời model thử — và mỗi lần thử là một yêu cầu
        # thất bại mà người dùng phải tự hiểu vì sao.
        lines = runner.bot_context_lines(
            {"may_control_bots": False, "bots": BOTS})
        joined = "\n".join(lines)
        self.assertNotIn("bot-anh", joined)
        self.assertNotIn("bot-erp", joined)

    def test_co_quyen_thi_thay_du_id_de_goi_dung(self):
        joined = "\n".join(runner.bot_context_lines(
            {"may_control_bots": True, "bots": BOTS}))
        self.assertIn("bot-anh", joined)
        self.assertIn("bot-erp", joined)

    def test_khong_co_bot_nao_thi_noi_thang_la_khong_co(self):
        joined = "\n".join(runner.bot_context_lines(
            {"may_control_bots": True, "bots": []}))
        self.assertNotIn("bot_id=", joined)


class DieuKhienBotKhongChamGit(unittest.TestCase):
    """``handle_request`` với action "bot" phải báo cáo rồi dọn sạch, không commit gì.

    Từ bản có công cụ thật, nhánh ``agent/<id>`` đã được checkout ra TRƯỚC KHI
    gọi model — kể cả cho một yêu cầu hoá ra chỉ là "dừng bot" — nên vế "không
    chạm git" cũ không còn đúng nữa. Điều vẫn phải đúng: một lệnh điều khiển
    bot không được để lại commit hay nhánh rác nào, vì lần sửa code kế tiếp sẽ
    hỏng vì lý do không liên quan.
    """

    def setUp(self):
        self.reported = []
        self.git_calls = []
        self._report = runner.report
        self._git = runner.git
        self._plan = runner.plan_change
        self._require_clean_repo = runner.require_clean_repo
        runner.report = lambda request_id, status, **extra: (
            self.reported.append((request_id, status, extra)) or {})
        runner.git = lambda *args, **kwargs: self.git_calls.append(args) or ""
        runner.require_clean_repo = lambda: None

    def tearDown(self):
        runner.report = self._report
        runner.git = self._git
        runner.plan_change = self._plan
        runner.require_clean_repo = self._require_clean_repo

    def request(self):
        return {"id": "req-1", "scope": {"allow_globs": ["flow_web/**"],
                                         "max_files": 3, "max_lines": 200}}

    def _khong_commit_khong_bo_sot_nhanh(self, branch: str):
        self.assertIn(("checkout", "-B", branch, runner.BASE_BRANCH), self.git_calls)
        self.assertIn(("branch", "-D", branch), self.git_calls)
        self.assertFalse(any(call[:1] == ("commit",) for call in self.git_calls),
                          "điều khiển bot không được tạo commit nào")
        self.assertFalse(any(call[:1] == ("add",) for call in self.git_calls),
                          "điều khiển bot không được ghi/stage file nào")

    def test_lenh_bot_duoc_chuyen_di_ma_khong_de_lai_commit(self):
        commands = [{"bot_id": "bot-anh", "command": "pause"}]
        runner.plan_change = lambda request, scope: {
            "action": "bot", "summary": "Tạm dừng bot tạo ảnh", "commands": commands}
        runner.handle_request(self.request())
        self._khong_commit_khong_bo_sot_nhanh("agent/req-1")
        self.assertEqual(len(self.reported), 1)
        request_id, status, extra = self.reported[0]
        self.assertEqual((request_id, status), ("req-1", "bot_action"))
        self.assertEqual(extra["bot_commands"], commands)

    def test_nhieu_lenh_bi_cat_con_nam(self):
        # Trần này lặp lại trần của Worker.  Một model đi chệch có thể sinh ra
        # hàng chục lệnh; cắt ở cả hai đầu để không bên nào là chỗ duy nhất giữ.
        runner.plan_change = lambda request, scope: {
            "action": "bot", "summary": "x",
            "commands": [{"bot_id": f"bot-{i}", "command": "run"} for i in range(9)]}
        runner.handle_request(self.request())
        self.assertEqual(len(self.reported[0][2]["bot_commands"]), 5)

    def test_noi_dieu_khien_bot_nhung_khong_dua_lenh_nao_thi_that_bai(self):
        runner.plan_change = lambda request, scope: {
            "action": "bot", "summary": "Tôi sẽ dừng bot", "commands": []}
        runner.handle_request(self.request())
        self.assertEqual(self.reported[0][1], "failed")
        self._khong_commit_khong_bo_sot_nhanh("agent/req-1")

    def test_khong_co_pham_vi_thi_khong_toi_duoc_buoc_hoi_chatgpt(self):
        # Người chưa được cấp phạm vi không dùng agent được, kể cả để điều
        # khiển bot: Worker đã chặn từ lúc xếp việc, runner chặn lại lần nữa.
        def khong_duoc_goi(request, scope):
            raise AssertionError("plan_change không được chạy khi thiếu phạm vi")

        runner.plan_change = khong_duoc_goi
        runner.handle_request({"id": "req-2", "scope": {"allow_globs": []}})
        self.assertEqual(self.reported[0][1], "failed")
        self.assertEqual(self.git_calls, [],
                          "thiếu phạm vi phải bị chặn trước cả bước checkout")


class DiffBiCatThiPhaiNoiRaLaBiCat(unittest.TestCase):
    """Cờ "diff đã bị cắt" phải do runner gửi, không phải Worker đoán.

    Runner là chỗ **duy nhất** còn nhìn thấy diff đầy đủ.  Thứ gửi lên Center
    đã cắt sẵn, nên bên kia so độ dài trước/sau lúc nào cũng thấy bằng nhau và
    kết luận "không bị cắt" — người duyệt đọc nửa diff mà màn hình báo là đủ.
    """

    def setUp(self):
        self.reported = []
        self.saved = {name: getattr(runner, name) for name in (
            "report", "git", "plan_change", "require_clean_repo",
            "validate_touched_paths", "branch_diff_stats", "run_tests", "is_cancelled")}
        runner.report = lambda request_id, status, **extra: (
            self.reported.append((request_id, status, extra)) or {})
        runner.git = lambda *args, **kwargs: (
            "deadbeefcafe\n" if args[:1] == ("rev-parse",)
            else "M flow_web/x.py\n" if args[:1] == ("status",)
            else "")
        runner.require_clean_repo = lambda: None
        # Model tự ghi file bằng công cụ của chính nó — không còn write_files()
        # để mock nữa, chỉ còn bước soi lại đường dẫn sau khi đã có diff.
        runner.validate_touched_paths = lambda paths, allow_globs, max_files: None
        runner.run_tests = lambda: (True, "test xanh")
        runner.is_cancelled = lambda request_id: False
        runner.plan_change = lambda request, scope: {
            "action": "edit", "summary": "sửa một dòng"}

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(runner, name, value)

    def _run(self, diff: str):
        runner.branch_diff_stats = lambda: (["flow_web/x.py"], 3, diff)
        runner.handle_request({"id": "req-diff", "scope": {
            "allow_globs": ["flow_web/**"], "max_files": 3, "max_lines": 200}})
        self.assertEqual(len(self.reported), 1, self.reported)
        request_id, status, extra = self.reported[0]
        self.assertEqual(status, "awaiting_approval", extra.get("error"))
        return extra

    def test_diff_dai_hon_tran_thi_cat_va_bao_da_cat(self):
        extra = self._run("d" * (runner.DIFF_LIMIT + 4000))
        self.assertEqual(extra["diff_truncated"], 1)
        self.assertEqual(len(extra["diff_text"]), runner.DIFF_LIMIT)

    def test_diff_vua_tran_thi_khong_bao_nham_la_da_cat(self):
        # Báo nhầm cũng hỏng theo kiểu khác: cảnh báo đỏ hiện ở mọi yêu cầu thì
        # chẳng ai còn đọc nó, và lần bị cắt thật sẽ trôi qua như mọi lần.
        extra = self._run("d" * runner.DIFF_LIMIT)
        self.assertEqual(extra["diff_truncated"], 0)
        self.assertEqual(len(extra["diff_text"]), runner.DIFF_LIMIT)

    def test_diff_ngan_thi_di_nguyen_ven(self):
        extra = self._run("diff --git a/x b/x\n+một dòng\n")
        self.assertEqual(extra["diff_truncated"], 0)
        self.assertEqual(extra["diff_text"], "diff --git a/x b/x\n+một dòng\n")


class MergeXongThiDonNhanh(unittest.TestCase):
    """Nhánh ``agent/<id>`` không được ở lại, và cũng không được biến mất sớm.

    Máy trung tâm chạy hết yêu cầu này tới yêu cầu khác trên cùng một bản làm
    việc.  Nhánh đã merge không còn nghĩa gì nữa nhưng vẫn nằm lại, nên sau vài
    chục lượt ``git branch`` là một danh sách rác — và ngày nào tên nhánh trùng
    lại (12 ký tự đầu của id) thì ``checkout -B`` ghi đè im lặng lên nhánh cũ.

    Hai đường xoá, và chúng khác nhau ở chỗ **ai xác nhận**:

    - **merge xong** — xoá ngay tại chỗ, sau lệnh merge. Không còn gì để mất.
    - **merge hỏng** — *không* xoá tại chỗ. Vào sổ ``HELD_BRANCHES``, đợi
      ``/api/runner/code/finished`` của Center xác nhận trạng thái cuối rồi
      ``drop_finished_branches`` mới xoá ở vòng poll kế tiếp. Xoá ngay trong
      ``except`` là xoá **trước khi** Center kịp ghi nhận: Center chết đúng
      khoảnh khắc ấy thì nhánh mất mà yêu cầu vẫn treo ``applying``.

    Bản trước của lớp này chỉ có hai bài và bài thứ hai tên là *"merge hỏng thì
    giữ nhánh lại để còn xem"* — lời hứa ấy sai với hệ thật (nhánh bị dọn một
    vòng poll sau), còn assertion thì bỏ trống hẳn nửa "rồi ai dọn". Bốn bài
    dưới đây khoá cả hai chiều; đã đo bằng bốn đột biến, xem PR.
    """

    def setUp(self):
        self.reported = []
        self.git_calls = []
        self.saved = {name: getattr(runner, name)
                      for name in ("report", "git", "require_clean_repo")}
        runner.report = lambda request_id, status, **extra: (
            self.reported.append((request_id, status, extra)) or {})

        def fake_git(*args, **kwargs):
            self.git_calls.append(args)
            return "deadbeefcafe\n" if args[:1] == ("rev-parse",) else ""

        runner.git = fake_git
        runner.require_clean_repo = lambda: None

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(runner, name, value)

    def test_merge_xong_thi_xoa_nhanh(self):
        runner.apply_approved({"id": "req-2", "branch": "agent/abc123"})
        self.assertIn(("branch", "-D", "agent/abc123"), self.git_calls)
        # Xoá **sau** khi merge, không phải trước: xoá trước là mất luôn thay đổi.
        self.assertLess(self.git_calls.index(("merge", "--no-edit", "agent/abc123")),
                        self.git_calls.index(("branch", "-D", "agent/abc123")))
        self.assertEqual(self.reported[-1][1], "applied")

    def _merge_hong(self, request_id="req-3", branch="agent/abc123"):
        """Cho merge ném lỗi rồi chạy apply_approved một lượt."""
        def fake_git(*args, **kwargs):
            self.git_calls.append(args)
            if args[:1] == ("merge",) and "--abort" not in args:
                raise RuntimeError("xung đột")
            return ""

        runner.git = fake_git
        runner.HELD_BRANCHES.clear()
        runner.apply_approved({"id": request_id, "branch": branch})

    def test_merge_hong_thi_khong_xoa_ngay_tai_cho(self):
        # Xoá ngay trong ``except`` là xoá **trước khi** Center kịp ghi nhận
        # yêu cầu đã hỏng.  Center chết giữa chừng ở đúng khoảnh khắc ấy thì
        # nhánh mất mà yêu cầu vẫn treo "applying" — không ai dựng lại được.
        self._merge_hong()
        self.assertNotIn(("branch", "-D", "agent/abc123"), self.git_calls)
        self.assertEqual(self.reported[-1][1], "failed")

    def test_merge_hong_thi_vao_so_de_vong_poll_sau_con_biet_ma_don(self):
        # Đây là nửa mà bản cũ của bài này bỏ trống: "không xoá ngay" một mình
        # đọc như "giữ nhánh lại mãi mãi", và một bản cài đặt quên hẳn việc dọn
        # vẫn xanh.  Vào sổ mới là thứ khiến nhánh thật sự biến mất.
        self._merge_hong()
        self.assertEqual(runner.HELD_BRANCHES.get("req-3"), "agent/abc123")

    def test_vong_poll_sau_xoa_that_cai_nhanh_merge_hong(self):
        # Rò số 1 của PRD B3 đóng ở đây, không đóng trong ``except`` của
        # apply_approved: Center xác nhận trạng thái cuối rồi runner mới xoá.
        self._merge_hong()
        hoi = []
        runner.center_request = lambda path, method="GET", payload=None: (
            hoi.append((path, method, payload))
            or {"finished": [{"id": "req-3", "status": "failed"}]})
        try:
            runner.drop_finished_branches()
        finally:
            del runner.center_request
        self.assertEqual(hoi[0][0], "/api/runner/code/finished")
        self.assertIn("req-3", hoi[0][2]["ids"])
        self.assertIn(("branch", "-D", "agent/abc123"), self.git_calls)
        self.assertNotIn("req-3", runner.HELD_BRANCHES)

    def test_center_chua_chot_thi_nhanh_o_lai(self):
        # Chiều ngược lại, và nó là chiều quan trọng hơn: một bản cài đặt xoá
        # sạch HELD_BRANCHES mỗi vòng poll cũng làm ba bài trên xanh hết.
        self._merge_hong()
        runner.center_request = lambda path, method="GET", payload=None: {"finished": []}
        try:
            runner.drop_finished_branches()
        finally:
            del runner.center_request
        self.assertNotIn(("branch", "-D", "agent/abc123"), self.git_calls)
        self.assertEqual(runner.HELD_BRANCHES.get("req-3"), "agent/abc123")


class TuVungDieuKhienBot(unittest.TestCase):
    """Prompt/schema chỉ được mời những động từ Worker có nghĩa thật."""

    def test_khong_con_resume_va_khong_bia_prompt_tao_anh(self):
        self.assertNotIn("resume", runner.SYSTEM_PROMPT)
        self.assertEqual(
            ["run", "pause"],
            runner.OUTPUT_SCHEMA["properties"]["commands"]["items"]["properties"]["command"]["enum"],
        )
        prompt = runner.SYSTEM_PROMPT.lower()
        self.assertIn('chỉ dùng command "run" khi người dùng đã nói rõ nội dung ảnh', prompt)
        self.assertIn('dùng action "answer" để hỏi lại nội dung', prompt)



if __name__ == "__main__":
    unittest.main(verbosity=2)
