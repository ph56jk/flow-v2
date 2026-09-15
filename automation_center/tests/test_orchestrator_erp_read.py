"""Agent điều phối đọc dữ liệu ERP: runner gọi hộ, model không tự ra mạng.

Model xin qua đúng action "read" đã có sẵn cho file repo — một "path" dạng
"erp:..." được runner hiểu là tham chiếu ERP thay vì file, tự gọi GraphQL rồi
trả lại một cục văn bản.  Test này khoá: model không đụng gì tới
``read_repo_file``/``is_protected`` khi xin "erp:...", ERP chưa cấu hình
credential thì báo lỗi rõ ràng thay vì hỏng ngầm, và ba dạng tham chiếu
(dự án / board Task / một Task) gọi đúng operation GraphQL tương ứng.

Chạy:  python3 automation_center/tests/test_orchestrator_erp_read.py
"""

from __future__ import annotations

import importlib.util
import io
import json
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


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class DocChuaCauHinh(unittest.TestCase):
    def setUp(self):
        self.saved = (runner.ERP_BOT_TOKEN, runner.ERP_API_KEY, runner.ERP_API_SECRET)
        runner.ERP_BOT_TOKEN = ""
        runner.ERP_API_KEY = ""
        runner.ERP_API_SECRET = ""

    def tearDown(self):
        runner.ERP_BOT_TOKEN, runner.ERP_API_KEY, runner.ERP_API_SECRET = self.saved

    def test_chua_cau_hinh_thi_bao_ro_khong_hong_ngam(self):
        text = runner.read_erp_resource("PROJ-0170")
        self.assertIn("chưa cấu hình", text)
        self.assertIn("lỗi đọc ERP", text)


class GoiGraphQLDungOperation(unittest.TestCase):
    def setUp(self):
        self.saved = (runner.ERP_BOT_TOKEN, runner.ERP_API_KEY, runner.ERP_API_SECRET,
                      runner.ERP_MIN_INTERVAL_SECONDS, runner.urllib.request.urlopen)
        runner.ERP_BOT_TOKEN = "token-test"
        runner.ERP_API_KEY = ""
        runner.ERP_API_SECRET = ""
        runner.ERP_MIN_INTERVAL_SECONDS = 0
        self.captured = []

    def tearDown(self):
        (runner.ERP_BOT_TOKEN, runner.ERP_API_KEY, runner.ERP_API_SECRET,
         runner.ERP_MIN_INTERVAL_SECONDS, runner.urllib.request.urlopen) = self.saved

    def _stub(self, data_by_field: dict):
        def fake_urlopen(request, timeout=None):
            self.captured.append({
                "url": request.full_url,
                "authorization": request.get_header("Authorization"),
                "body": json.loads(request.data.decode("utf-8")),
            })
            return FakeResponse(json.dumps({"data": data_by_field}).encode("utf-8"))
        runner.urllib.request.urlopen = fake_urlopen

    def test_ma_du_an_don_goi_project_overview(self):
        self._stub({"projectOverview": {"project": "PROJ-0170", "task_count": 5}})
        text = runner.read_erp_resource("PROJ-0170")
        self.assertEqual(self.captured[0]["body"]["operationName"], "ProjectOverview")
        self.assertEqual(self.captured[0]["body"]["variables"], {"project": "PROJ-0170"})
        self.assertEqual(self.captured[0]["authorization"], "HVGToken token-test")
        self.assertIn("PROJ-0170", text)
        self.assertIn("task_count", text)

    def test_ma_du_an_kem_tasks_goi_task_board(self):
        self._stub({"taskBoard": {"tasks": []}})
        runner.read_erp_resource("PROJ-0170/tasks")
        self.assertEqual(self.captured[0]["body"]["operationName"], "TaskBoard")
        self.assertEqual(self.captured[0]["body"]["variables"],
                          {"project": "PROJ-0170", "includeArchived": False})

    def test_ma_task_goi_task_detail(self):
        self._stub({"taskDetail": {"name": "TASK-9999"}})
        runner.read_erp_resource("TASK-9999")
        self.assertEqual(self.captured[0]["body"]["operationName"], "TaskDetail")
        self.assertEqual(self.captured[0]["body"]["variables"], {"name": "TASK-9999"})

    def test_hau_to_la_thu_gi_khac_tasks_thi_bao_khong_hieu(self):
        text = runner.read_erp_resource("PROJ-0170/comments")
        self.assertIn("không hiểu dạng erp:", text)
        self.assertEqual(self.captured, [])

    def test_khoa_api_key_secret_cung_dung_duoc_khi_khong_co_bot_token(self):
        runner.ERP_BOT_TOKEN = ""
        runner.ERP_API_KEY = "key-1"
        runner.ERP_API_SECRET = "secret-1"
        self._stub({"projectOverview": {}})
        runner.read_erp_resource("PROJ-0170")
        self.assertEqual(self.captured[0]["authorization"], "token key-1:secret-1")

    def test_erp_bao_loi_graphql_thi_tra_ve_van_ban_khong_nem_ra_ngoai(self):
        def fake_urlopen(request, timeout=None):
            return FakeResponse(json.dumps(
                {"errors": [{"message": "Project không tồn tại"}]}).encode("utf-8"))
        runner.urllib.request.urlopen = fake_urlopen
        text = runner.read_erp_resource("PROJ-KHONG-CO")
        self.assertIn("Project không tồn tại", text)


class ReadLoopDinhTuyenErpKhongDungFile(unittest.TestCase):
    """"erp:" trong action "read" không được đi qua read_repo_file/is_protected.

    Trộn cả file thật lẫn tham chiếu ERP trong cùng một lượt "read" là tình
    huống bình thường (model có thể vừa cần xem code vừa cần xem ERP); nếu
    nhánh "erp:" lỡ rơi qua is_protected, một dự án tên trùng ngẫu nhiên với
    một mục PROTECTED_GLOBS sẽ bị từ chối đọc vô lý.
    """

    def setUp(self):
        self.saved = {name: getattr(runner, name) for name in (
            "read_repo_file", "is_protected", "read_erp_resource", "call_model")}
        self.repo_file_calls = []
        self.protected_calls = []
        self.capture_read_phase = False
        runner.read_repo_file = lambda path: (
            self.repo_file_calls.append(path) or f"nội dung của {path}")
        original_is_protected = runner.is_protected

        def record_is_protected(path):
            if self.capture_read_phase:
                self.protected_calls.append(path)
            return original_is_protected(path)

        runner.is_protected = record_is_protected
        runner.read_erp_resource = lambda ref: f"ERP:{ref}"

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(runner, name, value)

    def test_erp_bo_qua_is_protected_va_read_repo_file(self):
        replies = iter([
            {"action": "read", "paths": ["erp:PROJ-0170", "flow_web/x.py"]},
            {"action": "answer", "summary": "xong"},
        ])

        def next_reply(messages):
            self.capture_read_phase = True
            return next(replies)

        runner.call_model = next_reply
        result = runner.plan_change(
            {"requested_by": "a", "requested_role": "owner", "history": [],
             "instruction": "xem PROJ-0170"},
            {"allow_globs": ["flow_web/**"], "max_files": 5, "max_lines": 500},
        )
        self.assertEqual(result, {"action": "answer", "summary": "xong"})
        self.assertEqual(self.repo_file_calls, ["flow_web/x.py"])
        self.assertEqual(self.protected_calls, ["flow_web/x.py"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
