"""Kiểm tra nhịp token bot ERP dùng chung giữa các tiến trình.

Không gọi mạng, không ghi vào thư mục data/ thật của repo.
Tổng thời gian chạy bộ test này < 10 giây.
"""

from __future__ import annotations

import json
import logging
import multiprocessing as mp
import os
from pathlib import Path
import tempfile
import time
from typing import Any, List
import unittest
from unittest.mock import patch

from flow_web.agent_bot import (
    AgentBotClient,
    AgentBotConfig,
    _RateLimiter,
    build_agent_bot,
    shared_limiter_from_env,
)
from flow_web.erp_token_nhip import SharedRateLimiter


def _mp_worker(path_str: str, limit: int, window_s: float, count: int, queue: Any) -> None:
    """Worker độc lập cho kiểm tra multiprocessing thật."""
    limiter = SharedRateLimiter(path_str, limit=limit, window_s=window_s)
    for _ in range(count):
        limiter.acquire()
        queue.put(time.time())


class ErpTokenNhipTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.rate_file = Path(self.tmp_dir.name) / "erp-agent-nhip.json"

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    # ────────────────────────────────────────────────────────────────────────
    # 1. Hai limiter cùng 1 file, đồng hồ giả: 120 lượt xen kẽ ≤ limit / 60s
    # ────────────────────────────────────────────────────────────────────────
    def test_01_two_limiters_share_window_and_limit(self) -> None:
        simulated_now = 1000.0

        def fake_clock() -> float:
            return simulated_now

        def fake_sleep(duration: float) -> None:
            nonlocal simulated_now
            simulated_now += duration

        limiter_a = SharedRateLimiter(self.rate_file, limit=50, window_s=60.0, clock=fake_clock, sleep=fake_sleep)
        limiter_b = SharedRateLimiter(self.rate_file, limit=50, window_s=60.0, clock=fake_clock, sleep=fake_sleep)

        timestamps: List[float] = []
        for i in range(120):
            limiter = limiter_a if i % 2 == 0 else limiter_b
            limiter.acquire()
            timestamps.append(simulated_now)
            # Giữa các lượt có một chút thời gian trôi đi
            simulated_now += 0.2

        # Kiểm tra mọi cửa sổ trượt 60 giây đều có số lượt ≤ 50
        for i, start_t in enumerate(timestamps):
            window_end = start_t + 60.0
            hits_in_window = sum(1 for t in timestamps if start_t <= t < window_end - 1e-7)
            self.assertLessEqual(
                hits_in_window,
                50,
                f"Tại mốc {start_t}s, cửa sổ 60s có {hits_in_window} lượt (> 50)",
            )

    # ────────────────────────────────────────────────────────────────────────
    # 2. 50 lượt đầu không ngủ, lượt 51 ngủ tới khi mốc cũ nhất ra khỏi cửa sổ
    # ────────────────────────────────────────────────────────────────────────
    def test_02_first_50_do_not_sleep_then_51_sleeps_accurately(self) -> None:
        simulated_now = 2000.0
        sleep_calls: List[float] = []

        def fake_clock() -> float:
            return simulated_now

        def fake_sleep(duration: float) -> None:
            nonlocal simulated_now
            sleep_calls.append(duration)
            simulated_now += duration

        limiter = SharedRateLimiter(self.rate_file, limit=50, window_s=60.0, clock=fake_clock, sleep=fake_sleep)

        # 50 lượt đầu tại các mốc: 2000.0, 2000.5, 2001.0, ...
        for _ in range(50):
            limiter.acquire()
            simulated_now += 0.5

        self.assertEqual([], sleep_calls, "50 lượt đầu tiên không được ngủ")

        # Lượt 51: lúc này simulated_now = 2000.0 + 50 * 0.5 = 2025.0
        # Mốc cũ nhất là 2000.0, window 60s -> hết hạn lúc 2060.0.
        # Thời gian cần ngủ = 2060.0 - 2025.0 = 35.0s
        limiter.acquire()
        self.assertEqual(1, len(sleep_calls))
        self.assertAlmostEqual(35.0, sleep_calls[0], delta=0.01)

    # ────────────────────────────────────────────────────────────────────────
    # 3. Tiến trình thật: multiprocessing 3 tiến trình × 5 lượt, limit=5, window=1.0s
    # ────────────────────────────────────────────────────────────────────────
    def test_03_multiprocessing_three_processes(self) -> None:
        ctx = mp.get_context("spawn")
        queue = ctx.Queue()
        processes = [
            ctx.Process(target=_mp_worker, args=(str(self.rate_file), 5, 1.0, 5, queue))
            for _ in range(3)
        ]
        for p in processes:
            p.start()

        results: List[float] = []
        for _ in range(15):
            results.append(queue.get(timeout=10.0))

        for p in processes:
            p.join(timeout=5.0)

        self.assertEqual(15, len(results))
        results.sort()

        # Kiểm tra mọi cửa sổ trượt 1.0s đều ≤ 5 lượt
        for start_t in results:
            window_end = start_t + 1.0
            hits = sum(1 for t in results if start_t <= t < window_end - 1e-7)
            self.assertLessEqual(hits, 5, f"Cửa sổ 1s tại {start_t} có {hits} lượt (> 5)")

    # ────────────────────────────────────────────────────────────────────────
    # 4. File hỏng (ghi rác) → vẫn chạy, ghi lại JSON đúng
    # ────────────────────────────────────────────────────────────────────────
    def test_04_corrupted_file_overwritten_safely(self) -> None:
        self.rate_file.write_text("{{corrupted_json: broken content... invalid-junk!!", encoding="utf-8")
        limiter = SharedRateLimiter(self.rate_file, limit=5)
        limiter.acquire()

        data = json.loads(self.rate_file.read_text(encoding="utf-8"))
        self.assertIsInstance(data, list)
        self.assertEqual(1, len(data))

    # ────────────────────────────────────────────────────────────────────────
    # 5. Khoá lỗi (OSError) → rơi về bộ đếm trong tiến trình, log đúng 1 lần
    # ────────────────────────────────────────────────────────────────────────
    def test_05_lock_error_falls_back_and_logs_once(self) -> None:
        limiter = SharedRateLimiter(self.rate_file, limit=5)
        with patch.object(SharedRateLimiter, "_file_lock", side_effect=OSError("Disk failure")):
            with self.assertLogs("flow_web.erp_token_nhip", level="WARNING") as log_cm:
                limiter.acquire()
                limiter.acquire()
                limiter.acquire()

        # Log cảnh báo đúng 1 lần duy nhất
        warning_logs = [r.getMessage() for r in log_cm.records if "Disk failure" in r.getMessage() or "rơi về bộ đếm" in r.getMessage()]
        self.assertEqual(1, len(warning_logs))

    # ────────────────────────────────────────────────────────────────────────
    # 6. Không ngủ trong lúc giữ khoá file
    # ────────────────────────────────────────────────────────────────────────
    def test_06_lock_is_not_held_during_sleep(self) -> None:
        simulated_now = 3000.0

        def fake_clock() -> float:
            return simulated_now

        def fake_sleep_and_verify_unlocked(duration: float) -> None:
            nonlocal simulated_now
            # Khi đang sleep, ta thử khoá file từ bên ngoài. Nếu lock chưa nhả,
            # thao tác này sẽ thất bại hoặc bị chặn.
            lock_path = Path(str(self.rate_file) + ".lock")
            self.assertTrue(lock_path.exists())
            with SharedRateLimiter._file_lock(lock_path):
                pass
            simulated_now += duration

        limiter = SharedRateLimiter(
            self.rate_file,
            limit=2,
            window_s=60.0,
            clock=fake_clock,
            sleep=fake_sleep_and_verify_unlocked,
        )
        limiter.acquire()
        limiter.acquire()
        # Lượt 3: hết chỗ, sẽ kích hoạt fake_sleep_and_verify_unlocked
        limiter.acquire()

    # ────────────────────────────────────────────────────────────────────────
    # 7. build_agent_bot với env → dùng SharedRateLimiter đúng path, đúng limit
    # ────────────────────────────────────────────────────────────────────────
    def test_07_build_agent_bot_uses_shared_limiter(self) -> None:
        env_vars = {
            "ERP_AGENT_TOKEN": "test-bot-token",
            "ERP_AGENT_RATE_FILE": str(self.rate_file),
            "ERP_AGENT_RATE_PER_MINUTE": "45",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            bot = build_agent_bot(AgentBotConfig.from_env())
            self.assertIsNotNone(bot)
            self.assertIsInstance(bot.client._limiter, SharedRateLimiter)
            self.assertEqual(self.rate_file.resolve(), bot.client._limiter.path)
            self.assertEqual(45, bot.client._limiter.limit)

        # Mặc định khi không có ERP_AGENT_RATE_PER_MINUTE là 50
        env_vars_default_rate = {
            "ERP_AGENT_TOKEN": "test-bot-token",
            "ERP_AGENT_RATE_FILE": str(self.rate_file),
        }
        with patch.dict(os.environ, env_vars_default_rate, clear=False):
            os.environ.pop("ERP_AGENT_RATE_PER_MINUTE", None)
            bot_default = build_agent_bot(AgentBotConfig.from_env())
            self.assertIsNotNone(bot_default)
            self.assertIsInstance(bot_default.client._limiter, SharedRateLimiter)
            self.assertEqual(50, bot_default.client._limiter.limit)

    # ────────────────────────────────────────────────────────────────────────
    # 8. review_lister build_from_env → cũng dùng SharedRateLimiter cùng path
    # ────────────────────────────────────────────────────────────────────────
    def test_08_review_lister_uses_shared_limiter(self) -> None:
        from flow_web import review_lister

        env_vars = {
            "ERP_AGENT_TOKEN": "test-bot-token",
            "ERP_LISTING_API_URL": "http://127.0.0.1:9999",
            "ERP_LISTING_FILES_DIR": self.tmp_dir.name,
            "ERP_AGENT_RATE_FILE": str(self.rate_file),
            "ERP_AGENT_RATE_PER_MINUTE": "40",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            with patch.object(review_lister, "ErpFiles"):
                with patch.object(review_lister, "ListingBridge"):
                    client, config, lister = review_lister.build_from_env()
                    self.assertIsInstance(client._limiter, SharedRateLimiter)
                    self.assertEqual(self.rate_file.resolve(), client._limiter.path)
                    self.assertEqual(40, client._limiter.limit)

    # ────────────────────────────────────────────────────────────────────────
    # 9. AgentBotClient(config) trần → vẫn _RateLimiter trong tiến trình
    # ────────────────────────────────────────────────────────────────────────
    def test_09_raw_agent_bot_client_uses_in_process_limiter(self) -> None:
        cfg = AgentBotConfig(token="test-token")
        client = AgentBotClient(cfg)
        self.assertIsInstance(client._limiter, _RateLimiter)
        self.assertNotIsInstance(client._limiter, SharedRateLimiter)

    # ────────────────────────────────────────────────────────────────────────
    # 10. shared_limiter_from_env log 1 dòng INFO
    # ────────────────────────────────────────────────────────────────────────
    def test_10_shared_limiter_from_env_logs_info(self) -> None:
        env_vars = {
            "ERP_AGENT_RATE_FILE": str(self.rate_file),
            "ERP_AGENT_RATE_PER_MINUTE": "35",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            with self.assertLogs("flow_web.agent_bot", level="INFO") as log_cm:
                limiter = shared_limiter_from_env()

            self.assertIsInstance(limiter, SharedRateLimiter)
            expected_msg = f"Nhịp token bot chung: {self.rate_file.resolve()}, 35/phút"
            self.assertTrue(any(expected_msg in r.getMessage() for r in log_cm.records))

    # ────────────────────────────────────────────────────────────────────────
    # 11. Env nhịp sai ("0", "-5", "501", "abc") → limit 50 + cảnh báo log đúng 1 lần
    # ────────────────────────────────────────────────────────────────────────
    def test_11_invalid_rate_env_falls_back_to_50_with_warning(self) -> None:
        invalid_values = ["0", "-5", "501", "abc"]
        for bad_val in invalid_values:
            with self.subTest(bad_val=bad_val):
                env_vars = {
                    "ERP_AGENT_RATE_FILE": str(self.rate_file),
                    "ERP_AGENT_RATE_PER_MINUTE": bad_val,
                }
                with patch.dict(os.environ, env_vars, clear=False):
                    with self.assertLogs("flow_web.agent_bot", level="WARNING") as log_cm:
                        limiter = shared_limiter_from_env()

                    self.assertEqual(50, limiter.limit)
                    warning_records = [r for r in log_cm.records if r.levelno == logging.WARNING]
                    self.assertEqual(1, len(warning_records), f"Phải có đúng 1 cảnh báo cho {bad_val}")
                    msg = warning_records[0].getMessage()
                    self.assertIn(bad_val, msg, "Cảnh báo phải nêu rõ giá trị sai")
                    self.assertIn("50", msg, "Cảnh báo phải nêu rõ giá trị dùng thay thế (50)")

    # ────────────────────────────────────────────────────────────────────────
    # 12. Env nhịp hợp lệ ("500", "1", "30") → đúng số đó, không cảnh báo
    # ────────────────────────────────────────────────────────────────────────
    def test_12_valid_rate_env_uses_specified_limit_without_warning(self) -> None:
        valid_values = ["500", "1", "30"]
        for val in valid_values:
            with self.subTest(val=val):
                env_vars = {
                    "ERP_AGENT_RATE_FILE": str(self.rate_file),
                    "ERP_AGENT_RATE_PER_MINUTE": val,
                }
                with patch.dict(os.environ, env_vars, clear=False):
                    logger = logging.getLogger("flow_web.agent_bot")
                    with patch.object(logger, "warning") as warn_mock:
                        limiter = shared_limiter_from_env()
                        warn_mock.assert_not_called()
                    self.assertEqual(int(val), limiter.limit)

    # ────────────────────────────────────────────────────────────────────────
    # 13. Không có env ERP_AGENT_RATE_PER_MINUTE → 50, không cảnh báo
    # ────────────────────────────────────────────────────────────────────────
    def test_13_missing_rate_env_defaults_to_50_without_warning(self) -> None:
        env_vars = {
            "ERP_AGENT_RATE_FILE": str(self.rate_file),
        }
        with patch.dict(os.environ, env_vars, clear=False):
            os.environ.pop("ERP_AGENT_RATE_PER_MINUTE", None)
            logger = logging.getLogger("flow_web.agent_bot")
            with patch.object(logger, "warning") as warn_mock:
                limiter = shared_limiter_from_env()
                warn_mock.assert_not_called()
            self.assertEqual(50, limiter.limit)


if __name__ == "__main__":
    unittest.main()
