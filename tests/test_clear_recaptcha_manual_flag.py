from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "clear_recaptcha_manual_flag.py"
SPEC = importlib.util.spec_from_file_location("clear_recaptcha_manual_flag_for_test", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
clear_flag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(clear_flag)


class ClearRecaptchaManualFlagTests(unittest.TestCase):
    TASK = "TASK-2026-02120"
    JOB = "job-recpatcha"
    MEDIA = "ecfa92a6-ec9e-45b2-a82e-afeb692eb5ec"

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.state_file = Path(self.tempdir.name) / "state.json"
        self.target_key = clear_flag.state_key(self.TASK, self.JOB, self.MEDIA)
        self.other_key = clear_flag.state_key(self.TASK, self.JOB, "898d33ba-2d78-4be7-ad13-185804ba7148")
        self.state_file.write_text(json.dumps(self._state(), indent=2), encoding="utf-8")

    def _state(self) -> dict:
        return {
            "jobs": [
                {
                    "id": self.JOB,
                    "result": {
                        "erp_review": {"items": {"0": {"comment": "keep"}}},
                        "flow_upsample_recaptcha": {
                            "version": 1,
                            "media": {
                                self.target_key: {
                                    "task_id": self.TASK,
                                    "job_id": self.JOB,
                                    "media_id": self.MEDIA,
                                    "rejected_count": 2,
                                    "needs_manual_review": True,
                                    "next_retry_at": "2026-09-01T00:00:00+00:00",
                                },
                                self.other_key: {
                                    "task_id": self.TASK,
                                    "job_id": self.JOB,
                                    "media_id": "898d33ba-2d78-4be7-ad13-185804ba7148",
                                    "rejected_count": 2,
                                    "needs_manual_review": True,
                                    "next_retry_at": "2026-09-01T00:00:00+00:00",
                                },
                            },
                        },
                    },
                }
            ]
        }

    def _run(self, *extra: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        args = [self.TASK, self.JOB, self.MEDIA, "--state-file", str(self.state_file), *extra]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = clear_flag.main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_default_is_a_dry_run_and_never_changes_the_file(self) -> None:
        before = self.state_file.read_bytes()

        code, stdout, stderr = self._run()

        self.assertEqual(0, code, stderr)
        self.assertIn("DRY-RUN", stdout)
        self.assertEqual(before, self.state_file.read_bytes())
        self.assertEqual([], list(self.state_file.parent.glob("state.json.bak-clear-recaptcha-*")))

    def test_apply_removes_only_the_target_and_creates_a_backup(self) -> None:
        before = self.state_file.read_bytes()

        code, stdout, stderr = self._run("--apply")

        self.assertEqual(0, code, stderr)
        self.assertIn("Đã xoá record manual", stdout)
        saved = json.loads(self.state_file.read_text(encoding="utf-8"))
        result = saved["jobs"][0]["result"]
        self.assertNotIn(self.target_key, result["flow_upsample_recaptcha"]["media"])
        self.assertIn(self.other_key, result["flow_upsample_recaptcha"]["media"])
        self.assertEqual({"items": {"0": {"comment": "keep"}}}, result["erp_review"])
        backups = list(self.state_file.parent.glob("state.json.bak-clear-recaptcha-*"))
        self.assertEqual(1, len(backups))
        self.assertEqual(before, backups[0].read_bytes())

    def test_refuses_to_remove_a_record_that_is_not_manually_blocked(self) -> None:
        state = self._state()
        state["jobs"][0]["result"]["flow_upsample_recaptcha"]["media"][self.target_key].update(
            {"needs_manual_review": False, "next_retry_at": ""}
        )
        self.state_file.write_text(json.dumps(state), encoding="utf-8")
        before = self.state_file.read_bytes()

        code, _stdout, stderr = self._run("--apply")

        self.assertEqual(2, code)
        self.assertIn("không đang bị manual block", stderr)
        self.assertEqual(before, self.state_file.read_bytes())
