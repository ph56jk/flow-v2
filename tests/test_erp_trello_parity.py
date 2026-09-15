"""The ERP pipeline behaves like the Trello workers (flowautomation, 2026-09-04..11):

* Gemini design QA gates every upload: off-design images are marked rejected by "Gemini QA",
  too few survivors or a Gemini outage hold the set (nothing reaches the card).
* The 2K files come from Flow's own "2K Upscaled" download; without a real 2K the card is held,
  never filled with 1K images, and the continuous Auto batch stops on that signal.
* A 2K upload is retried three times and then holds the card instead of posting a 1K link.
* ``retry_erp_upload`` finishes a held card from the images already generated.
* Cards that already hold a usable partial set (>= FLOW_ERP_QA_MIN_GOOD_IMAGES) are never regenerated.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from flow_web.schemas import CreateJobRequest, ERPConfig, JobArtifact, JobRecord
from flow_web.service import FlowUiUpscaleUnavailableError, FlowWebService, ImageUpscaleResult
from flow_web.store import StateStore


def _graph() -> Dict[str, Any]:
    return {
        "modules": [
            {"id": "erp-source-1", "type": "erp_source", "title": "ERP Image Source"},
            {"id": "flow-1", "type": "flow", "title": "Google Flow"},
            {"id": "erp-1", "type": "erp", "title": "ERP Archive"},
        ]
    }


class _FakeResponse:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None


class ErpTrelloParityTests(unittest.TestCase):
    TASK = "TASK-2026-00616"

    def setUp(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.patches = [
            patch.dict(os.environ, {"FLOW_UI_UPSCALE_2K_ENABLED": "0", "REMOVE_LOGO_ENABLED": "0"}, clear=False),
            patch("flow_web.store.STATE_FILE", self.root / "state.json"),
            patch("flow_web.store.ensure_app_dirs", lambda: self.root.mkdir(parents=True, exist_ok=True)),
            patch("flow_web.service.ensure_app_dirs", lambda: self.root.mkdir(parents=True, exist_ok=True)),
        ]
        for item in self.patches:
            item.start()
        self.store = StateStore()
        self.service = FlowWebService(self.store)
        self.loop.run_until_complete(
            self.store.replace_erp_config(ERPConfig(api_key="test-key", api_secret="test-secret", project_id="PROJ-0013"))
        )
        self.comments: List[Dict[str, Any]] = []
        self.uploads: List[str] = []
        for item in (
            patch.object(self.service, "_download_root", return_value=self.root / "downloads"),
            patch.object(self.service, "_erp_assert_task_in_project"),
            patch.object(self.service, "_erp_task_detail", side_effect=self._detail),
            patch.object(self.service, "_erp_graphql", side_effect=self._fake_add_comment),
        ):
            self.patches.append(item)
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tempdir.cleanup()
        self.loop.close()
        asyncio.set_event_loop(None)

    # ------------------------------------------------------------------ fakes
    def _detail(self, *_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        return {"name": self.TASK, "status": "Open", "comments": list(self.comments)}

    def _fake_add_comment(self, query: str, variables: Dict[str, Any], operation: str, *, key: str, token: str) -> Dict[str, Any]:
        comment = {
            "name": f"cmt-{len(self.comments)}",
            "content": variables["content"],
            "meta": variables.get("meta") or "",
            "attachments": [{"file_url": item} for item in variables.get("attachments") or []],
            "replies": [],
        }
        self.comments.append(comment)
        return {"addTaskComment": {"name": comment["name"], "linked": 1}}

    def _fake_upload(self, key: str, token: str, task_id: str, file_bytes: bytes, mime: str, name: str) -> str:
        self.uploads.append(name)
        return f"/private/files/{name}"

    def _job(self, count: int = 3, *, with_source: bool = False, urls: bool = False) -> JobRecord:
        artifacts = []
        for index in range(count):
            path = self.root / f"anh-{index}.png"
            path.write_bytes(b"png-bytes-%d" % index)
            artifacts.append(
                JobArtifact(
                    local_path=str(path),
                    mime_type="image/png",
                    url=f"https://flow.example/media/{index}.jpg" if urls else "",
                    workflow_id="wf-1",
                )
            )
        payload: Dict[str, Any] = {
            "type": "image",
            "prompt": "khăn tay",
            "count": count,
            "erp_enabled": True,
            "erp_task_id": "TASK-2026-00202",
            "erp_output_task_id": self.TASK,
            "erp_project_id": "PROJ-0013",
        }
        if with_source:
            source = self.root / "erp-source.jpg"
            source.write_bytes(b"source-bytes")
            payload["reference_image_paths"] = [str(source)]
            payload["automation_graph"] = _graph()
        job = JobRecord(id="job-erp", type="image", status="completed", input=payload, artifacts=artifacts)
        return self.loop.run_until_complete(self.store.add_job(job))

    def _publish(self, job_id: str = "job-erp") -> Dict[str, Any]:
        with patch.object(self.service, "_erp_upload_file", side_effect=self._fake_upload), patch.object(
            self.service, "_upsample_artifact_bytes", side_effect=Exception("no flow session")
        ):
            return self.loop.run_until_complete(self.service.publish_erp_review(job_id))

    # ------------------------------------------------------------------ Gemini design QA
    def test_design_qa_marks_off_design_images_rejected_and_publishes_the_rest(self) -> None:
        # Four images, one off-design: three survive, which meets FLOW_ERP_QA_MIN_GOOD_IMAGES (3).
        self._job(count=4, with_source=True)
        verdict = {"ok": False, "reason": "motif changed on image 2", "bad_indexes": [1], "confidence": 0.9}

        with patch.object(self.service, "_gemini_api_key", return_value="test-gemini"), patch.object(self.service, "_gemini_validate_erp_source_artifacts", return_value=verdict) as gemini:
            summary = self._publish()
            # A second publish (the archive step, a poll) must not pay for a second Gemini call.
            second = self._publish()

        self.assertEqual(1, gemini.call_count)
        self.assertEqual(3, summary["published"])
        self.assertEqual(1, summary["qa_dropped"])
        self.assertEqual(3, len(self.comments))
        self.assertEqual(0, second["published"])
        job = self.store.get_job("job-erp")
        approvals = job.result["dashboard_approvals"]
        self.assertEqual("rejected", approvals["1"]["status"])
        self.assertEqual("gemini_qa", approvals["1"]["source"])
        self.assertNotIn("0", approvals)
        self.assertEqual(1, job.result["erp_design_qa"]["dropped"])
        logs = " ".join(entry.message for entry in job.logs)
        self.assertIn("không tạo bù", logs)

    def test_design_qa_outage_holds_the_set_and_fails_the_job(self) -> None:
        self._job(with_source=True)
        request = CreateJobRequest(**self.store.get_job("job-erp").input)

        with patch.object(self.service, "_gemini_api_key", return_value="test-gemini"), patch.object(
            self.service, "_gemini_validate_erp_source_artifacts", side_effect=RuntimeError("Gemini API returned HTTP 503.")
        ):
            with self.assertRaises(RuntimeError) as raised:
                self._publish()
            with patch.object(self.service, "_erp_upload_file", side_effect=self._fake_upload):
                with self.assertRaises(RuntimeError):
                    self.loop.run_until_complete(self.service._auto_publish_erp_review("job-erp", request))

        self.assertIn("Gemini QA không chạy được", str(raised.exception))
        self.assertTrue(self.service._auto_erp_is_design_qa_unavailable(str(raised.exception)))
        self.assertFalse(self.service._auto_erp_should_stop_on_child_error(str(raised.exception)))
        self.assertEqual([], self.comments)

    def test_design_qa_rejects_the_set_when_too_few_images_pass(self) -> None:
        self._job(with_source=True)
        verdict = {"ok": False, "reason": "wrong product", "bad_indexes": [0, 1], "confidence": 0.95}

        with patch.object(self.service, "_gemini_api_key", return_value="test-gemini"), patch.object(self.service, "_gemini_validate_erp_source_artifacts", return_value=verdict):
            with self.assertRaises(RuntimeError) as raised:
                self._publish()

        self.assertIn("Gemini chặn upload ERP", str(raised.exception))
        self.assertTrue(self.service._auto_erp_is_design_qa_rejection(str(raised.exception)))
        self.assertEqual([], self.comments)

    def test_design_qa_is_skipped_when_gemini_is_not_configured(self) -> None:
        self._job(with_source=True)
        with patch.object(self.service, "_gemini_api_key", return_value=""), patch.object(
            self.service, "_gemini_validate_erp_source_artifacts"
        ) as gemini:
            summary = self._publish()
        gemini.assert_not_called()
        self.assertEqual(3, summary["published"])
        logs = " ".join(entry.message for entry in self.store.get_job("job-erp").logs)
        self.assertIn("bỏ qua bước QA thiết kế", logs)

    def test_design_qa_is_skipped_for_jobs_without_an_erp_source(self) -> None:
        self._job()
        with patch.object(self.service, "_gemini_api_key", return_value="test-gemini"), patch.object(self.service, "_gemini_validate_erp_source_artifacts") as gemini:
            summary = self._publish()
        gemini.assert_not_called()
        self.assertEqual(3, summary["published"])

    # ------------------------------------------------------------------ Flow-UI 2K
    def test_publish_holds_the_card_when_flow_gives_no_2k(self) -> None:
        self._job()
        request = CreateJobRequest(**self.store.get_job("job-erp").input)
        held = AsyncMock(return_value="")

        with patch.dict(os.environ, {"FLOW_UI_UPSCALE_2K_ENABLED": ""}, clear=False), patch.object(
            self.service,
            "_with_client",
            new=AsyncMock(side_effect=FlowUiUpscaleUnavailableError("Flow khong tra ban 2K (3 anh khong tai duoc, moi 0/3 anh co 2K)")),
        ), patch.object(self.service, "_persist_held_artifact_files", new=held), patch.object(
            self.service, "_erp_upload_file", side_effect=self._fake_upload
        ):
            with self.assertRaises(FlowUiUpscaleUnavailableError) as raised:
                self.loop.run_until_complete(self.service.publish_erp_review("job-erp"))
            with self.assertRaises(FlowUiUpscaleUnavailableError):
                self.loop.run_until_complete(self.service._auto_publish_erp_review("job-erp", request))

        self.assertIn("khong upload anh 1K", str(raised.exception))
        self.assertTrue(self.service._auto_erp_should_stop_on_child_error(str(raised.exception)))
        self.assertEqual([], self.comments)
        self.assertEqual([], self.uploads)
        self.assertTrue(held.await_count >= 1)

    def test_publish_holds_the_rest_of_the_card_when_one_image_has_no_real_2k(self) -> None:
        self._job()
        held = AsyncMock(return_value="")
        results = {
            0: ImageUpscaleResult(bytes=b"anh-2k-0", mime_type="image/jpeg", source="flow_2k", target_size=(2048, 1536), used_flow=True),
            1: ImageUpscaleResult(source="flow_unavailable", failure_reason="Flow returned original bytes"),
            2: ImageUpscaleResult(bytes=b"anh-2k-2", mime_type="image/jpeg", source="flow_2k", target_size=(2048, 1536), used_flow=True),
        }

        with patch.dict(os.environ, {"FLOW_UI_UPSCALE_2K_ENABLED": ""}, clear=False), patch.object(
            self.service, "_with_client", new=AsyncMock(return_value=[{"bytes": b"candidate", "name": "x.jpeg"}])
        ), patch.object(
            self.service, "_upsample_artifacts_bytes", new=AsyncMock(return_value=results)
        ) as batch, patch.object(self.service, "_persist_held_artifact_files", new=held), patch.object(
            self.service, "_erp_upload_file", side_effect=self._fake_upload
        ):
            with self.assertRaises(FlowUiUpscaleUnavailableError) as raised:
                self.loop.run_until_complete(self.service.publish_erp_review("job-erp"))

        self.assertEqual([{"bytes": b"candidate", "name": "x.jpeg"}], batch.await_args.kwargs["ui_candidates"])
        self.assertIn("Anh 2/3 khong co ban 2K that", str(raised.exception))
        self.assertTrue(self.service._auto_erp_should_stop_on_child_error(str(raised.exception)))
        # The first image (real 2K) went up before the hold; the 1K one never did.
        self.assertEqual(1, len(self.comments))
        self.assertEqual(1, len(self.uploads))
        self.assertTrue(held.await_count >= 1)

    def test_publish_retries_a_2k_upload_then_holds_instead_of_posting_1k(self) -> None:
        self._job(count=1)
        held = AsyncMock(return_value="")
        results = {0: ImageUpscaleResult(bytes=b"anh-2k-0", mime_type="image/jpeg", source="flow_2k", target_size=(2048, 1536), used_flow=True)}

        with patch.dict(os.environ, {"FLOW_UI_UPSCALE_2K_ENABLED": ""}, clear=False), patch.object(
            FlowWebService, "ERP_2K_UPLOAD_RETRY_DELAYS_S", (0.0, 0.0)
        ), patch.object(
            self.service, "_with_client", new=AsyncMock(return_value=[{"bytes": b"candidate", "name": "x.jpeg"}])
        ), patch.object(
            self.service, "_upsample_artifacts_bytes", new=AsyncMock(return_value=results)
        ), patch.object(self.service, "_persist_held_artifact_files", new=held), patch.object(
            self.service, "_erp_upload_file", side_effect=RuntimeError("EOF occurred in violation of protocol")
        ) as upload:
            with self.assertRaises(FlowUiUpscaleUnavailableError) as raised:
                self.loop.run_until_complete(self.service.publish_erp_review("job-erp"))

        self.assertEqual(FlowWebService.ERP_2K_UPLOAD_ATTEMPTS, upload.call_count)
        self.assertIn("Khong upload duoc ban 2K", str(raised.exception))
        self.assertTrue(self.service._auto_erp_should_stop_on_child_error(str(raised.exception)))
        self.assertEqual([], self.comments)

    def test_a_1k_upload_failure_without_the_2k_policy_is_still_just_a_failed_image(self) -> None:
        self._job(count=2)
        with patch.object(self.service, "_erp_upload_file", side_effect=RuntimeError("ERP down")), patch.object(
            self.service, "_upsample_artifact_bytes", side_effect=Exception("no flow session")
        ):
            summary = self.loop.run_until_complete(self.service.publish_erp_review("job-erp"))
        self.assertEqual(0, summary["published"])
        self.assertEqual(2, summary["failed"])

    def test_upscale_result_policy(self) -> None:
        ok = ImageUpscaleResult(bytes=b"x", source="flow_2k", target_size=(2048, 2048))
        self.assertTrue(self.service._erp_upscale_result_is_2k(ok))
        self.assertTrue(self.service._erp_upscale_result_is_2k(ImageUpscaleResult()))  # original already >= 2K
        self.assertFalse(self.service._erp_upscale_result_is_2k(ImageUpscaleResult(failure_reason="Flow returned original bytes")))
        self.assertFalse(self.service._erp_upscale_result_is_2k(None))

    def test_erp_upload_uses_the_long_timeout_for_2k_files(self) -> None:
        with patch("flow_web.service.urlopen", return_value=_FakeResponse({"message": {"file_url": "/private/files/a.jpg"}})) as opened:
            hosted = self.service._erp_upload_file("k", "t", self.TASK, b"jpeg", "image/jpeg", "a.jpg")
        self.assertEqual("/private/files/a.jpg", hosted)
        self.assertEqual(FlowWebService.ERP_UPLOAD_TIMEOUT_S, opened.call_args.kwargs["timeout"])
        self.assertEqual(180, FlowWebService.ERP_UPLOAD_TIMEOUT_S)

    # ------------------------------------------------------------------ retry endpoint
    def test_retry_erp_upload_refetches_images_and_republishes(self) -> None:
        job = self._job(urls=True)
        result = dict(job.result or {})
        result["dashboard_approvals"] = {"0": {"status": "rejected", "source": "gemini_qa", "reviewer": {"name": "Gemini QA"}}}
        result["erp_design_qa"] = {"checked": True, "artifact_count": 3, "dropped": 1}
        self.loop.run_until_complete(self.store.patch_job("job-erp", result=result))

        with patch.object(self.service, "_read_remote_file", return_value=(b"fresh-bytes", "image/jpeg")) as fetch, patch.object(
            self.service, "_erp_upload_file", side_effect=self._fake_upload
        ), patch.object(self.service, "_upsample_artifact_bytes", side_effect=Exception("no flow session")):
            outcome = self.loop.run_until_complete(self.service.retry_erp_upload("job-erp"))

        self.assertEqual(3, fetch.call_count)
        self.assertEqual("completed", outcome["status"])
        self.assertEqual(3, outcome["published"])
        self.assertEqual(3, len(self.comments))
        saved = self.store.get_job("job-erp")
        self.assertEqual("completed", saved.status)
        self.assertNotIn("erp_design_qa", saved.result)
        self.assertEqual({}, saved.result.get("dashboard_approvals"))
        self.assertTrue(all(str(a.local_path).endswith(f"retry-job-erp-{i + 1}.jpg") for i, a in enumerate(saved.artifacts)))

    def test_retry_erp_upload_rejects_running_jobs_and_missing_urls(self) -> None:
        self._job()
        with self.assertRaises(HTTPException) as no_url:
            self.loop.run_until_complete(self.service.retry_erp_upload("job-erp"))
        self.assertEqual(400, no_url.exception.status_code)
        self.assertIn("không còn URL Flow", no_url.exception.detail)

        self.loop.run_until_complete(self.store.patch_job("job-erp", status="running"))
        with self.assertRaises(HTTPException) as running:
            self.loop.run_until_complete(self.service.retry_erp_upload("job-erp"))
        self.assertEqual(409, running.exception.status_code)

    # ------------------------------------------------------------------ Auto batch policies
    def test_stop_signals_cover_the_2k_holds(self) -> None:
        for text in (
            "Flow khong tra ban 2K; app giu card, khong upload anh 1K.",
            "Anh 3/12 khong co ban 2K that; app giu phan con lai cua the.",
            "Khong upload duoc ban 2K cua anh 2/12 len ERP sau 3 lan.",
            "Tất cả Chrome profile Flow đã hết quota Agent (Acc15)",
        ):
            self.assertTrue(self.service._auto_erp_should_stop_on_child_error(text), text)
        self.assertFalse(self.service._auto_erp_should_stop_on_child_error("Gemini QA không chạy được nên app chưa upload ERP"))
        self.assertFalse(self.service._auto_erp_should_stop_on_child_error("Gemini chặn upload ERP vì ảnh generated không khớp"))

    def test_auto_scan_finishes_cards_with_a_usable_partial_set_instead_of_regenerating(self) -> None:
        request = CreateJobRequest(type="image", title="Auto image from ERP card", count=4)

        def card(count: int) -> Dict[str, Any]:
            return {
                "id": f"card-{count}",
                "shortLink": f"c{count}",
                "idList": "ready",
                "name": "embroidered apron",
                "url": f"https://erp.example/c/{count}",
                "_image_attachments": [{"id": "source-att", "name": "source.jpg", "mimeType": "image/jpeg"}],
                "_selected_attachment_ids": ["source-att"],
                "_flow_output_count": count,
            }

        complete = card(3)
        sparse = card(2)
        items = self.service._erp_ai_prompt_items_for_image_cards([complete, sparse], request, 40)

        self.assertEqual(1, len(items))
        self.assertEqual("card-2", items[0]["erp_task_id"])
        self.assertEqual(12, items[0]["flow_agent_image_count"])
        self.assertEqual("complete_output_set", complete["_auto_erp_skip_code"])
        self.assertIn("khong tao bu", complete["_auto_erp_skip_reason"])
        self.assertNotIn("_auto_erp_skip_code", sparse)

    def test_min_good_images_env_accepts_both_names(self) -> None:
        self.assertEqual(3, self.service._erp_source_qa_min_good_images())
        with patch.dict(os.environ, {"FLOW_ERP_QA_MIN_GOOD_IMAGES": "5"}, clear=False):
            self.assertEqual(5, self.service._erp_source_qa_min_good_images())
        with patch.dict(os.environ, {"FLOW_TRELLO_QA_MIN_GOOD_IMAGES": "4"}, clear=False):
            self.assertEqual(4, self.service._erp_source_qa_min_good_images())
        self.assertTrue(self.service._erp_source_qa_strict())
        with patch.dict(os.environ, {"FLOW_ERP_QA_STRICT": "0"}, clear=False):
            self.assertFalse(self.service._erp_source_qa_strict())


if __name__ == "__main__":
    unittest.main()
