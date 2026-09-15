"""Hồi quy cho hai lỗi chỉ lộ ra khi runner làm việc dài.

Runner chạy bằng một luồng chính, nên heartbeat phải có vòng riêng: một lượt
model/test kéo dài không được biến một tiến trình vẫn sống thành runner_offline.
Đồng thời, timeout test phải giữ lại bằng chứng đã in trước khi subprocess bị
dừng, để người duyệt biết lệnh nào đã treo ở đâu.
"""

from __future__ import annotations

import importlib.util
import io
import os
import shlex
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


HERE = Path(__file__).resolve().parent
CENTER = HERE.parent


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "orchestrator_runner_resilience", CENTER / "runner" / "orchestrator_runner.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = load_runner()


class HeartbeatNenKhongBiKhoaBoilong(unittest.TestCase):
    """Nhịp nền phải sống độc lập với một lượt xử lý đang chặn."""

    def setUp(self):
        self.saved = {name: getattr(runner, name) for name in (
            "RUNNER_SECRET", "REPO_DIR", "HEARTBEAT_SECONDS", "center_request",
            "chon_nha_cung_cap", "require_repo_root", "handle_request")}

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(runner, name, value)

    def _run_main_with_blocked_request(self, failed_beats: int = 0) -> int:
        beats = []
        runner.RUNNER_SECRET = "test-secret"
        runner.REPO_DIR = Path("/tmp/repo-agent-test")
        runner.HEARTBEAT_SECONDS = 0.01
        runner.chon_nha_cung_cap = lambda *args: "openai"
        runner.require_repo_root = lambda: None

        def center_gia(path, **kwargs):
            if path == "/api/runner/heartbeat":
                beats.append(path)
                if len(beats) <= failed_beats:
                    raise RuntimeError("Center tạm lỗi")
                return {}
            if path.startswith("/api/runner/code/approved"):
                return {"requests": []}
            if path == "/api/runner/code/claim":
                return {"request": {"id": "req-bi-chan"}}
            raise AssertionError(f"Center nhận đường dẫn lạ: {path}")

        def xu_ly_bi_chan(request):
            # Đóng vai lượt model/test lâu hơn ngưỡng stale đã rút ngắn của
            # test. KeyboardInterrupt là lối dừng có chủ ý của main().
            time.sleep(0.08)
            raise KeyboardInterrupt

        runner.center_request = center_gia
        runner.handle_request = xu_ly_bi_chan
        with redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(), 0)
        self.assertFalse(any(
            thread.name == "orchestrator-heartbeat" and thread.is_alive()
            for thread in threading.enumerate()
        ))
        return len(beats)

    def test_nhip_nen_van_chay_khi_luot_chinh_bi_chan(self):
        self.assertGreaterEqual(self._run_main_with_blocked_request(), 4)

    def test_nhip_nen_nuot_loi_va_luot_chinh_van_di_toi_cuoi(self):
        # Hai nhịp đầu lỗi nhưng main vẫn đi hết lượt bị chặn rồi dừng có chủ ý.
        self.assertGreaterEqual(self._run_main_with_blocked_request(failed_beats=2), 4)

    def test_khoi_dong_that_bai_khong_bao_song_ho(self):
        """Không được tạo heartbeat trước khi provider/repo đã được kiểm xong."""
        sent = []
        runner.RUNNER_SECRET = "test-secret"
        runner.REPO_DIR = Path("/tmp/repo-agent-test")
        runner.chon_nha_cung_cap = lambda *args: "openai"
        runner.center_request = lambda path, **kwargs: sent.append(path) or {}

        def repo_khong_hop_le():
            raise RuntimeError("repo test không phải gốc git")

        runner.require_repo_root = repo_khong_hop_le
        with redirect_stderr(io.StringIO()):
            self.assertEqual(runner.main(), 2)

        self.assertEqual(sent, [])
        self.assertFalse(any(
            thread.name == "orchestrator-heartbeat" and thread.is_alive()
            for thread in threading.enumerate()
        ))


class TimeoutTestGiuBangChung(unittest.TestCase):
    def setUp(self):
        self.saved = runner.TEST_COMMAND, runner.TEST_TIMEOUT, runner.REPO_DIR

    def tearDown(self):
        runner.TEST_COMMAND, runner.TEST_TIMEOUT, runner.REPO_DIR = self.saved

    def test_timeout_co_lenh_va_output_da_in(self):
        code = (
            "import sys, time; "
            "print('dong stdout truoc khi treo', flush=True); "
            "print('dong stderr truoc khi treo', file=sys.stderr, flush=True); "
            "time.sleep(5)"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            runner.REPO_DIR = Path(temp_dir)
            runner.TEST_COMMAND = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"
            runner.TEST_TIMEOUT = 0.15
            passed, output = runner.run_tests()

        self.assertFalse(passed)
        self.assertIn(runner.TEST_COMMAND, output)
        self.assertIn("dong stdout truoc khi treo", output)
        self.assertIn("dong stderr truoc khi treo", output)

        # subprocess.TimeoutExpired không luôn tôn trọng text=True: có đường
        # trả bytes, và stderr/stdout có thể là None. Khối except phải vẫn tự
        # báo được thay vì ném một TypeError thứ hai.
        original_run = runner.subprocess.run
        runner.TEST_COMMAND = "lenh-gia-bi-timeout"
        try:
            def timeout_gia(*args, **kwargs):
                raise runner.subprocess.TimeoutExpired(
                    cmd="lenh-gia-bi-timeout", timeout=0.1,
                    output=b"dong bytes \xff truoc khi dung", stderr=None)

            runner.subprocess.run = timeout_gia
            passed, output = runner.run_tests()
        finally:
            runner.subprocess.run = original_run

        self.assertFalse(passed)
        self.assertIn("lenh-gia-bi-timeout", output)
        self.assertIn("dong bytes � truoc khi dung", output)


class NganSachModelVaTestTachRieng(unittest.TestCase):
    """Timeout model/test phải có hai núm chỉnh riêng, không kéo nhau theo."""

    ENV_NAMES = ("OPENAI_TIMEOUT_SECONDS", "AGENT_TEST_TIMEOUT_SECONDS")

    def setUp(self):
        self.saved_env = {name: os.environ.get(name) for name in self.ENV_NAMES}
        self.runner_dir = str(CENTER / "runner")
        self.added_runner_dir = self.runner_dir not in sys.path
        if self.added_runner_dir:
            sys.path.insert(0, self.runner_dir)
        self.reloadable_runner = importlib.import_module("orchestrator_runner")

    def tearDown(self):
        for name, value in self.saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        importlib.reload(self.reloadable_runner)
        if self.added_runner_dir:
            sys.path.remove(self.runner_dir)

    def _reload_with(self, **values: str | None):
        for name, value in values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        return importlib.reload(self.reloadable_runner)

    def test_model_timeout_mac_dinh_dai_va_tach_rieng_test_timeout(self):
        defaults = self._reload_with(
            OPENAI_TIMEOUT_SECONDS=None,
            AGENT_TEST_TIMEOUT_SECONDS=None,
        )
        self.assertEqual(1800, defaults.OPENAI_TIMEOUT)
        self.assertEqual(900, defaults.TEST_TIMEOUT)

        overridden = self._reload_with(
            OPENAI_TIMEOUT_SECONDS="61",
            AGENT_TEST_TIMEOUT_SECONDS="73",
        )
        self.assertEqual(61, overridden.OPENAI_TIMEOUT)
        self.assertEqual(73, overridden.TEST_TIMEOUT)

        floored = self._reload_with(
            OPENAI_TIMEOUT_SECONDS="1",
            AGENT_TEST_TIMEOUT_SECONDS="1",
        )
        self.assertEqual(30, floored.OPENAI_TIMEOUT)
        self.assertEqual(30, floored.TEST_TIMEOUT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
