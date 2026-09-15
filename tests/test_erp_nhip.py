from __future__ import annotations

import asyncio
import io
import json
import os
import threading
import unittest
from email.message import Message
from types import SimpleNamespace
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.error import HTTPError

from flow_web.service import FlowWebService
from flow_web.store import ERPConfig, StateStore


class _FakeClock:
    """A thread-safe simulated monotonic clock and sleeper."""

    def __init__(self, start: float = 1000.0) -> None:
        self.lock = threading.Lock()
        self.now = float(start)
        self.sleeps: List[float] = []

    def monotonic(self) -> float:
        with self.lock:
            return self.now

    def sleep(self, seconds: float) -> None:
        with self.lock:
            self.now += float(seconds)
            self.sleeps.append(float(seconds))


def _make_response(data: dict) -> Any:
    payload = json.dumps(data).encode("utf-8")
    resp = io.BytesIO(payload)
    setattr(resp, "status", 200)
    setattr(resp, "getcode", lambda: 200)
    return resp


def _make_http_429(retry_after: Optional[str] = None) -> HTTPError:
    hdrs = Message()
    if retry_after is not None:
        hdrs["Retry-After"] = str(retry_after)
    return HTTPError(
        url="https://erp.havigroup.llc/graphql",
        code=429,
        msg="Too Many Requests",
        hdrs=hdrs,
        fp=io.BytesIO(b"{}"),
    )


class ErpNhipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = _FakeClock(1000.0)
        self.store = StateStore()
        # Ensure fresh ERP config
        self.store.snapshot().erp_config.api_key = "test-key"
        self.store.snapshot().erp_config.api_secret = "test-secret"
        self.service = FlowWebService(self.store)

        # Reset limiter if class/instance has reset hook
        limiter = getattr(self.service, "_erp_rate_limiter", None)
        if limiter is not None and hasattr(limiter, "reset"):
            limiter.reset()

        self.patches = [
            patch("flow_web.service.time.monotonic", side_effect=self.clock.monotonic),
            patch("flow_web.service.time.sleep", side_effect=self.clock.sleep),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        os.environ.pop("ERP_GRAPHQL_PER_MINUTE", None)

    def test_first_10_requests_burst_without_sleep(self) -> None:
        with patch("flow_web.service.urlopen", side_effect=lambda *a, **kw: _make_response({"data": {"test": 1}})):
            for i in range(10):
                res = self.service._erp_graphql(
                    "query { test }",
                    {},
                    "Test",
                    key="k",
                    token="t",
                )
                self.assertEqual({"test": 1}, res)

        self.assertEqual([], self.clock.sleeps)

    def test_100_requests_respects_rate_limit_in_60s_windows(self) -> None:
        timestamps: List[float] = []
        with patch("flow_web.service.urlopen", side_effect=lambda *a, **kw: _make_response({"data": {"test": 1}})):
            for i in range(100):
                self.service._erp_graphql(
                    "query { test }",
                    {},
                    "Test",
                    key="k",
                    token="t",
                )
                timestamps.append(self.clock.monotonic())

        self.assertEqual(100, len(timestamps))
        # First 10 were burst without sleep
        self.assertEqual(timestamps[0], timestamps[9])
        # In any 60-second window, request count must be <= 10 + 40 = 50
        for i, t_start in enumerate(timestamps):
            t_end = t_start + 60.0
            window_count = sum(1 for t in timestamps if t_start <= t <= t_end)
            self.assertLessEqual(
                window_count,
                50,
                f"Window starting at {t_start} had {window_count} requests (> 50)",
            )

    def test_rate_limit_disabled_when_env_zero(self) -> None:
        os.environ["ERP_GRAPHQL_PER_MINUTE"] = "0"
        with patch("flow_web.service.urlopen", side_effect=lambda *a, **kw: _make_response({"data": {"test": 1}})):
            for _ in range(100):
                self.service._erp_graphql(
                    "query { test }",
                    {},
                    "Test",
                    key="k",
                    token="t",
                )

        self.assertEqual([], self.clock.sleeps)

    def test_429_retry_once_then_200_sleeps_10s(self) -> None:
        responses = [
            _make_http_429(),
            _make_response({"data": {"success": True}}),
        ]
        with patch("flow_web.service.urlopen", side_effect=responses):
            res = self.service._erp_graphql(
                "query { test }",
                {},
                "Test",
                key="k",
                token="t",
            )
            self.assertEqual({"success": True}, res)

        # First request consumed token without sleep, 429 slept 10s, retry succeeded
        self.assertEqual([10.0], self.clock.sleeps)

    def test_429_retry_once_with_retry_after_header(self) -> None:
        responses = [
            _make_http_429(retry_after="7"),
            _make_response({"data": {"success": True}}),
        ]
        with patch("flow_web.service.urlopen", side_effect=responses):
            res = self.service._erp_graphql(
                "query { test }",
                {},
                "Test",
                key="k",
                token="t",
            )
            self.assertEqual({"success": True}, res)

        self.assertEqual([7.0], self.clock.sleeps)

    def test_429_four_times_raises_runtime_error_and_sleeps_100s(self) -> None:
        responses = [
            _make_http_429(),
            _make_http_429(),
            _make_http_429(),
            _make_http_429(),
        ]
        with patch("flow_web.service.urlopen", side_effect=responses):
            with self.assertRaises(RuntimeError) as ctx:
                self.service._erp_graphql(
                    "query { test }",
                    {},
                    "Test",
                    key="k",
                    token="t",
                )
            self.assertIn("HTTP 429", str(ctx.exception))

        # Sleeps: 10s + 30s + 60s = 100s
        self.assertEqual([10.0, 30.0, 60.0], self.clock.sleeps)
        self.assertEqual(100.0, sum(self.clock.sleeps))

    def test_multithreaded_8_threads_respects_limit(self) -> None:
        timestamps: List[float] = []
        ts_lock = threading.Lock()
        errors: List[Exception] = []

        def worker() -> None:
            try:
                for _ in range(10):
                    self.service._erp_graphql(
                        "query { test }",
                        {},
                        "Test",
                        key="k",
                        token="t",
                    )
                    with ts_lock:
                        timestamps.append(self.clock.monotonic())
            except Exception as e:
                with ts_lock:
                    errors.append(e)

        with patch("flow_web.service.urlopen", side_effect=lambda *a, **kw: _make_response({"data": {"test": 1}})):
            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual([], errors)
        self.assertEqual(80, len(timestamps))

        # Check rate limit across all 80 requests
        timestamps.sort()
        for i, t_start in enumerate(timestamps):
            t_end = t_start + 60.0
            window_count = sum(1 for t in timestamps if t_start <= t <= t_end)
            self.assertLessEqual(
                window_count,
                50,
                f"Window starting at {t_start} had {window_count} requests (> 50)",
            )

    def test_event_loop_thread_graphql_429_does_not_sleep_and_raises_immediately(self) -> None:
        async def call_on_loop():
            return self.service._erp_graphql(
                "query { test }",
                {},
                "TestOp",
                key="k",
                token="t",
            )

        urlopen_mock = MagicMock(side_effect=_make_http_429())
        with patch("flow_web.service.urlopen", urlopen_mock):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(call_on_loop())
            self.assertIn("HTTP 429", str(ctx.exception))

        # time.sleep must NOT be called on event loop thread
        self.assertEqual([], self.clock.sleeps)
        # urlopen called exactly once (no retry)
        self.assertEqual(1, urlopen_mock.call_count)

    def test_event_loop_thread_graphql_with_empty_bucket_does_not_sleep(self) -> None:
        limiter = getattr(self.service, "_erp_rate_limiter", None)
        if limiter is not None:
            limiter.reset(capacity=10.0)
            limiter.tokens = 0.0

        async def call_on_loop():
            return self.service._erp_graphql(
                "query { test }",
                {},
                "TestOp",
                key="k",
                token="t",
            )

        with patch("flow_web.service.urlopen", side_effect=lambda *a, **kw: _make_response({"data": {"test": 1}})):
            res = asyncio.run(call_on_loop())
            self.assertEqual({"test": 1}, res)

        # time.sleep must NOT be called on event loop thread
        self.assertEqual([], self.clock.sleeps)

    def test_to_thread_graphql_429_retries_with_backoff(self) -> None:
        responses = [
            _make_http_429(),
            _make_response({"data": {"success": True}}),
        ]
        urlopen_mock = MagicMock(side_effect=responses)

        async def call_via_to_thread():
            return await asyncio.to_thread(
                self.service._erp_graphql,
                "query { test }",
                {},
                "TestOp",
                key="k",
                token="t",
            )

        with patch("flow_web.service.urlopen", urlopen_mock):
            res = asyncio.run(call_via_to_thread())
            self.assertEqual({"success": True}, res)

        self.assertEqual([10.0], self.clock.sleeps)
        self.assertEqual(2, urlopen_mock.call_count)

    def test_advance_erp_pipeline_runs_assert_and_cluster_root_on_worker_thread(self) -> None:
        loop_thread = None
        called_threads = {}

        def fake_assert(k, t, target):
            called_threads["assert"] = threading.current_thread()

        def fake_cluster_root(k, t, node):
            called_threads["cluster_root"] = threading.current_thread()
            return "TASK-123"

        async def run_pipeline():
            nonlocal loop_thread
            loop_thread = threading.current_thread()
            with patch.object(self.service, "_erp_assert_task_in_project", side_effect=fake_assert), \
                 patch.object(self.service, "_erp_cluster_root", side_effect=fake_cluster_root), \
                 patch.object(self.service, "_erp_task_full", return_value={"name": "TASK-123"}), \
                 patch.object(self.service, "_erp_pipeline_stage", return_value=SimpleNamespace(status="Open")):
                return await self.service.advance_erp_pipeline("TASK-123")

        asyncio.run(run_pipeline())

        self.assertIn("assert", called_threads)
        self.assertIn("cluster_root", called_threads)
        self.assertIsNotNone(loop_thread)
        self.assertNotEqual(loop_thread, called_threads["assert"])
        self.assertNotEqual(loop_thread, called_threads["cluster_root"])

    def test_request_with_erp_source_images_runs_auto_source_list_ids_on_worker_thread(self) -> None:
        from flow_web.schemas import CreateJobRequest

        loop_thread = None
        called_thread = None

        def fake_auto_source_list_ids(k, t, p, r):
            nonlocal called_thread
            called_thread = threading.current_thread()
            return ["OPEN-LIST-ID"]

        request = CreateJobRequest(
            type="image",
            prompt="test",
            erp_project_id="PROJ-1",
            erp_source_task_id="TASK-1",
            automation_graph={
                "modules": [
                    {
                        "id": "m1",
                        "enabled": True,
                        "type": "erp_source",
                        "settings": {},
                    }
                ]
            },
        )

        async def run_req():
            nonlocal loop_thread
            loop_thread = threading.current_thread()
            with patch.object(self.service, "_erp_auto_source_list_ids", side_effect=fake_auto_source_list_ids), \
                 patch.object(self.service, "_set_automation_module_status", new=AsyncMock()), \
                 patch.object(self.service, "_erp_task_hint_by_id", return_value={"name": "TASK-1", "status": "OPEN-LIST-ID"}), \
                 patch.object(self.service, "_download_erp_task_image_attachments", return_value=["/fake/path.png"]), \
                 patch.object(self.service.store, "append_log", new=AsyncMock()):
                return await self.service._request_with_erp_source_images("job1", request)

        asyncio.run(run_req())

        self.assertIsNotNone(called_thread)
        self.assertIsNotNone(loop_thread)
        self.assertNotEqual(loop_thread, called_thread)

    def test_continuous_auto_erp_batch_runs_idle_message_on_worker_thread(self) -> None:
        from fastapi import HTTPException
        from flow_web.schemas import CreateJobRequest

        loop_thread = None
        called_thread = None

        def fake_idle_message(req, poll_s):
            nonlocal called_thread
            called_thread = threading.current_thread()
            return "idle message"

        request = CreateJobRequest(
            type="image",
            prompt="test",
            erp_project_id="PROJ-1",
        )

        class StopLoop(Exception):
            pass

        async def run_batch():
            nonlocal loop_thread
            loop_thread = threading.current_thread()
            with patch.object(self.service, "_prompt_batch_stop_requested", return_value=False), \
                 patch.object(self.service, "_continuous_auto_erp_idle_message", side_effect=fake_idle_message), \
                 patch.object(self.service, "_expand_prompt_batch_with_erp_images", side_effect=HTTPException(status_code=400, detail="Empty")), \
                 patch.object(self.service, "_auto_erp_waitable_empty_error", return_value=True), \
                 patch.object(self.service, "_sleep_continuous_auto_erp", side_effect=StopLoop), \
                 patch.object(self.service, "_patch_prompt_batch_result", new=AsyncMock()), \
                 patch.object(self.service.store, "set_progress_hint", new=AsyncMock()), \
                 patch.object(self.service.store, "patch_job", new=AsyncMock()), \
                 patch.object(self.service.store, "append_log", new=AsyncMock()):
                try:
                    await self.service._run_continuous_auto_erp_batch("batch1", request, [], 5)
                except StopLoop:
                    pass

        asyncio.run(run_batch())

        self.assertIsNotNone(called_thread)
        self.assertIsNotNone(loop_thread)
        self.assertNotEqual(loop_thread, called_thread)


if __name__ == "__main__":
    unittest.main()

