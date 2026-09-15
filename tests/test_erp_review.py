from __future__ import annotations

import asyncio
import base64
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

from fastapi import HTTPException

from flow_web.schemas import CreateJobRequest, ERPConfig, JobArtifact, JobRecord
from flow_web.service import FlowWebService
from flow_web.store import StateStore


class ErpReviewDecisionTests(unittest.TestCase):
    """Reading a Vietnamese reply as approve, reject, or neither."""

    def setUp(self) -> None:
        self.service = FlowWebService.__new__(FlowWebService)

    def _decide(self, text: str) -> str:
        return FlowWebService._erp_review_decision(self.service, text)

    def test_reads_the_plain_verdicts(self) -> None:
        self.assertEqual("approved", self._decide("DUYỆT"))
        self.assertEqual("approved", self._decide("<p>duyệt nhé em</p>"))
        self.assertEqual("approved", self._decide("ok em"))
        self.assertEqual("approved", self._decide("Ảnh này đẹp, lấy nhé"))
        self.assertEqual("rejected", self._decide("bỏ"))
        self.assertEqual("rejected", self._decide("Bỏ ảnh này đi em"))
        self.assertEqual("rejected", self._decide("loại"))

    def test_a_refusal_that_contains_the_approve_word_is_still_a_refusal(self) -> None:
        # "không duyệt" contains "duyệt"; reading it as approval would send an
        # image to the client that a reviewer had just turned down.
        self.assertEqual("rejected", self._decide("không duyệt"))
        self.assertEqual("rejected", self._decide("ko duyệt em ơi"))
        self.assertEqual("rejected", self._decide("Ảnh ok về màu nhưng không duyệt"))

    def test_reads_the_tick_and_cross_marks(self) -> None:
        self.assertEqual("approved", self._decide("✅"))
        self.assertEqual("approved", self._decide("👍 luôn"))
        self.assertEqual("rejected", self._decide("❌"))

    def test_a_comment_without_a_verdict_decides_nothing(self) -> None:
        self.assertEqual("", self._decide("Ảnh này chỉnh lại màu nền giúp chị"))
        self.assertEqual("", self._decide(""))
        # A word that merely contains a keyword must not vote: "bò" is not "bỏ",
        # and "boong" is not "bo".
        self.assertEqual("", self._decide("con bò sữa trong ảnh hơi nhỏ"))
        self.assertEqual("", self._decide("nền boong tàu chưa rõ"))


class _FakeUpsampleClient:
    """A Flow client that hands out reCAPTCHA tokens and can refuse them.

    Only the two things ``_upsample_image_via_flow`` touches are real: minting
    a token (``_client_context``, which on the live client drives the page)
    and posting the upscale (``_fetch``). ``refuse_tokens`` names the tokens
    Google answers with the 403 that left images at 1024.
    """

    BIG = b"anh-2k-that"

    def __init__(
        self,
        test: unittest.TestCase,
        *,
        refuse_tokens: set[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._test = test
        self._refuse = set(refuse_tokens or ())
        self._error = error
        self.contexts = 0
        self.tokens_used: List[str] = []
        self.lock_held_while_minting: List[bool] = []
        self._api = self

    async def _client_context(self) -> Dict[str, Any]:
        self.contexts += 1
        self.lock_held_while_minting.append(self._test.service._browser_session_lock.locked())
        return {"token": f"tok-{self.contexts}"}

    async def _fetch(self, method: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        token = str((payload.get("clientContext") or {}).get("token") or "")
        self.tokens_used.append(token)
        if self._error is not None:
            raise self._error
        if token in self._refuse:
            raise RuntimeError("HTTP 403 on upsampleImage: reCAPTCHA evaluation failed")
        return {"encodedImage": base64.b64encode(self.BIG).decode()}


class ErpReviewFlowTests(unittest.TestCase):
    TASK = "TASK-2026-00616"

    def setUp(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.root = root
        self.patches = [
            # The Flow-UI "2K Upscaled" path (Trello-worker parity) drives a real browser; these tests
            # exercise the upsample API batch, so it is switched off here and covered on its own.
            patch.dict(os.environ, {"FLOW_UI_UPSCALE_2K_ENABLED": "0"}, clear=False),
            patch("flow_web.store.STATE_FILE", root / "state.json"),
            patch("flow_web.store.ensure_app_dirs", lambda: root.mkdir(parents=True, exist_ok=True)),
            patch("flow_web.service.ensure_app_dirs", lambda: root.mkdir(parents=True, exist_ok=True)),
            # Đổi host URL project làm registry flow-py cần tự chuẩn hoá lại.
            # Test không được ghi vào hồ sơ thật của người dùng.
            patch("flow._storage.CONFIG_FILE", root / "flow-config.json"),
            patch("flow._storage.PROJECTS_FILE", root / "flow-projects.json"),
        ]
        for item in self.patches:
            item.start()
        self.store = StateStore()
        self.service = FlowWebService(self.store)
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(api_key="test-key", api_secret="test-secret", project_id="PROJ-0013")
            )
        )
        self.comments: List[Dict[str, Any]] = []
        self.replies: List[Dict[str, Any]] = []
        # The card's own state, plus what this app writes back onto it. Both
        # are faked here because a rejection now removes a comment and a
        # finished idea moves column - neither may reach the real ERP in a test.
        self.task_status = "Open"
        self.deleted: List[str] = []
        self.notes: List[str] = []
        self.status_writes: List[str] = []
        for item in (
            patch.object(self.service, "_erp_delete_task_comment", side_effect=self._fake_delete),
            patch.object(self.service, "_erp_comment", side_effect=self._fake_note),
            patch.object(self.service, "_erp_update_task_status", side_effect=self._fake_status),
        ):
            self.patches.append(item)
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tempdir.cleanup()
        self.loop.close()
        asyncio.set_event_loop(None)

    def _job(self, count: int = 3) -> JobRecord:
        artifacts = []
        for index in range(count):
            path = self.root / f"anh-{index}.png"
            path.write_bytes(b"png-bytes-%d" % index)
            artifacts.append(JobArtifact(local_path=str(path), mime_type="image/png", url=""))
        job = JobRecord(
            id="job-erp",
            type="image",
            status="completed",
            input={
                "type": "image",
                "prompt": "khăn tay",
                "count": count,
                "erp_enabled": True,
                "erp_task_id": "TASK-2026-00202",
                "erp_output_task_id": self.TASK,
                "erp_project_id": "PROJ-0013",
            },
            artifacts=artifacts,
        )
        return self.loop.run_until_complete(self.store.add_job(job))

    def _fake_add_comment(self, query, variables, operation, *, key, token):
        comment = {
            "name": f"cmt-{len(self.comments)}",
            "content": variables["content"],
            "meta": variables.get("meta") or "",
            "attachments": [{"file_url": item} for item in variables.get("attachments") or []],
            "replies": [],
        }
        self.comments.append(comment)
        return {"addTaskComment": {"name": comment["name"], "linked": 1}}

    def _detail(self, *_args, **_kwargs) -> Dict[str, Any]:
        return {"name": self.TASK, "status": self.task_status, "comments": list(self.comments)}

    def _fake_delete(self, key, token, task_id, comment) -> Dict[str, Any]:
        self.deleted.append(comment)
        self.comments = [item for item in self.comments if item["name"] != comment]
        return {"deleted": comment}

    def _fake_note(self, key, token, task_id, content, parent_comment: str = "") -> Dict[str, Any]:
        self.notes.append(content)
        return {"comment": {"name": f"note-{len(self.notes)}"}}

    def _fake_status(self, key, token, task_id, status) -> Dict[str, Any]:
        self.status_writes.append(status)
        self.task_status = status
        return {"name": task_id, "status": status}

    def _fake_reply(self, key, token, task_id, content, *, parent_comment, attachments=None):
        self.replies.append({"parent": parent_comment, "content": content})
        return {"name": f"reply-{len(self.replies)}"}

    def _publish(self, job_id: str = "job-erp") -> Dict[str, Any]:
        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_task_detail", side_effect=self._detail
        ), patch.object(
            self.service, "_erp_upload_file", side_effect=lambda *a: f"/private/files/{a[-1]}"
        ), patch.object(
            self.service, "_erp_graphql", side_effect=self._fake_add_comment
        ), patch.object(
            self.service, "_upsample_artifact_bytes", side_effect=Exception("no flow session")
        ):
            return self.loop.run_until_complete(self.service.publish_erp_review(job_id))

    def _sync(self, job_id: str = "job-erp") -> Dict[str, Any]:
        with patch.object(self.service, "_erp_task_detail", side_effect=self._detail), patch.object(
            self.service, "_erp_reply_comment", side_effect=self._fake_reply
        ):
            return self.loop.run_until_complete(self.service.sync_erp_review(job_id))

    def _answer(self, comment_index: int, text: str, *, by: str = "Khánh Linh", creation: str = "2026-08-14 10:00:00") -> None:
        self.comments[comment_index]["replies"].append(
            {"name": f"ans-{comment_index}", "content": text, "by_name": by, "creation": creation}
        )

    def test_publish_puts_every_undecided_image_on_the_card(self) -> None:
        self._job()

        summary = self._publish()

        self.assertEqual(3, summary["published"])
        self.assertEqual(0, summary["failed"])
        self.assertEqual(3, summary["pending"])
        self.assertEqual(self.TASK, summary["task_id"])
        self.assertEqual(3, len(self.comments))
        # Nothing readable goes on the card: the marker rides in ``meta`` and
        # the body is the invisible character that keeps ERP from writing
        # "(đã đính kèm tệp)" in its place.
        self.assertEqual("[FLOW_V2_REVIEW job-erp#0]", self.comments[0]["meta"])
        self.assertEqual("\u200b", self.comments[0]["content"])
        self.assertNotIn("DUYỆT", " ".join(item["content"] for item in self.comments))
        self.assertEqual(1, len(self.comments[0]["attachments"]))

        review = self.store.get_job("job-erp").result["erp_review"]
        self.assertEqual(self.TASK, review["task_id"])
        self.assertEqual("cmt-0", review["items"]["0"]["comment"])
        self.assertTrue(review["items"]["2"]["url"].endswith(".png"))

    def test_a_finished_job_puts_its_images_on_the_card_without_being_asked(self) -> None:
        # Reviewers never open this app, so a run that only fills the local
        # dashboard reads on the board as "the bot did nothing".
        job = self._job()
        request = CreateJobRequest(**job.input)

        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_task_detail", side_effect=self._detail
        ), patch.object(
            self.service, "_erp_upload_file", side_effect=lambda *a: f"/private/files/{a[-1]}"
        ), patch.object(
            self.service, "_erp_graphql", side_effect=self._fake_add_comment
        ), patch.object(
            self.service, "_upsample_artifact_bytes", side_effect=Exception("no flow session")
        ):
            published = self.loop.run_until_complete(
                self.service._auto_publish_erp_review("job-erp", request)
            )

        self.assertEqual(3, published)
        self.assertEqual(3, len(self.comments))
        # Đăng ảnh lên chờ 👍/👎 không phải là xong một bước: thẻ vẫn nằm ở
        # *Cần làm* cho tới khi có người duyệt.
        self.assertEqual([], self.status_writes)

    def test_the_whole_batch_is_upscaled_in_one_flow_session(self) -> None:
        # Opening a Flow project page per image is what made the upload step
        # take longer than the generation it was uploading: twelve page loads
        # at roughly half a minute each, one after another.
        job = self._job()
        request = CreateJobRequest(**job.input)
        sessions = 0
        held: list[bool] = []
        upscaled: list[str] = []

        async def _with_client(fn, workflow_id="", timeout_s=0, hold_session_lock=True, needs_agent_quota=True):
            nonlocal sessions
            sessions += 1
            held.append(hold_session_lock)
            return await fn(object())

        async def _via_flow(_client, jpeg_bytes, **kwargs):
            upscaled.append(str(kwargs.get("media_generation_id") or ""))
            return jpeg_bytes

        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_task_detail", side_effect=self._detail
        ), patch.object(
            self.service, "_erp_upload_file", side_effect=lambda *a: f"/private/files/{a[-1]}"
        ), patch.object(
            self.service, "_erp_graphql", side_effect=self._fake_add_comment
        ), patch.object(
            self.service, "_flow_upsample_api_enabled", return_value=True
        ), patch.object(
            self.service, "_with_client", side_effect=_with_client
        ), patch.object(
            self.service, "_upsample_image_via_flow", side_effect=_via_flow
        ):
            published = self.loop.run_until_complete(
                self.service._auto_publish_erp_review("job-erp", request)
            )

        self.assertEqual(3, published)
        self.assertEqual(1, sessions)
        self.assertEqual(3, len(upscaled))
        # And it does not keep the browser while it waits on those upscales.
        self.assertEqual([False], held)

    def test_the_batch_can_send_several_upscales_at_once(self) -> None:
        # Off by default - four at a time measured slower than one at a time on
        # live cards, and dropped images. The knob is what lets that be
        # re-measured, so it has to actually reach the batch.
        job = self._job()
        request = CreateJobRequest(**job.input)
        in_flight = 0
        peak = 0

        async def _with_client(fn, workflow_id="", timeout_s=0, hold_session_lock=True, needs_agent_quota=True):
            return await fn(object())

        all_three = asyncio.Event()

        async def _via_flow(_client, jpeg_bytes, **_kwargs):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            if in_flight >= 3:
                all_three.set()
            try:
                # One at a time, nobody ever sets this and each image waits
                # out the timeout instead.
                await asyncio.wait_for(all_three.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass
            in_flight -= 1
            return jpeg_bytes

        with patch.dict("os.environ", {"FLOW_UPSAMPLE_CONCURRENCY": "4"}), patch.object(
            self.service, "_erp_assert_task_in_project"
        ), patch.object(
            self.service, "_erp_task_detail", side_effect=self._detail
        ), patch.object(
            self.service, "_erp_upload_file", side_effect=lambda *a: f"/private/files/{a[-1]}"
        ), patch.object(
            self.service, "_erp_graphql", side_effect=self._fake_add_comment
        ), patch.object(
            self.service, "_flow_upsample_api_enabled", return_value=True
        ), patch.object(
            self.service, "_with_client", side_effect=_with_client
        ), patch.object(
            self.service, "_upsample_image_via_flow", side_effect=_via_flow
        ):
            published = self.loop.run_until_complete(
                self.service._auto_publish_erp_review("job-erp", request)
            )

        self.assertEqual(3, published)
        self.assertEqual(3, peak)

    def test_two_cards_take_turns_on_the_2k_batch(self) -> None:
        # The batch lets go of the browser so the next card can generate, but
        # it must not let go of Google. Two batches in flight measured 87-105s
        # an image against 31s alone on live cards, and 5 of one card's 12
        # images came back un-upscaled. Overlap the browser, not the queue.
        from flow_web.service import ImageUpscaleResult

        order: list[str] = []
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        async def _with_client(fn, workflow_id="", timeout_s=0, hold_session_lock=True, needs_agent_quota=True):
            return await fn(object())

        async def _one(artifact, _url, *, client=None, session_lock_held=True):
            card = str(artifact.local_path)
            order.append(f"{card} bắt đầu")
            if card == "a":
                first_started.set()
                await release_first.wait()
            order.append(f"{card} xong")
            return ImageUpscaleResult()

        def _items(card: str):
            artifact = JobArtifact(local_path=card, mime_type="image/png", url="http://x/1.png")
            return [(0, artifact, "http://x/1.png")]

        async def _run() -> None:
            with patch.object(
                self.service, "_flow_upsample_api_enabled", return_value=True
            ), patch.object(
                self.service, "_with_client", side_effect=_with_client
            ), patch.object(
                self.service, "_upsample_artifact_bytes", side_effect=_one
            ):
                first = asyncio.create_task(self.service._upsample_artifacts_bytes(_items("a")))
                await asyncio.wait_for(first_started.wait(), timeout=2)
                second = asyncio.create_task(self.service._upsample_artifacts_bytes(_items("b")))
                # Every chance to slip in alongside the first batch.
                for _ in range(30):
                    await asyncio.sleep(0)
                release_first.set()
                await asyncio.wait_for(asyncio.gather(first, second), timeout=2)

        self.loop.run_until_complete(_run())
        self.assertEqual(["a bắt đầu", "a xong", "b bắt đầu", "b xong"], order)

    def test_auto_publish_can_be_turned_off(self) -> None:
        job = self._job()
        request = CreateJobRequest(**job.input)

        with patch.dict("os.environ", {"ERP_REVIEW_AUTOPUBLISH": "0"}), patch.object(
            self.service, "publish_erp_review"
        ) as publish:
            published = self.loop.run_until_complete(
                self.service._auto_publish_erp_review("job-erp", request)
            )

        self.assertEqual(0, published)
        publish.assert_not_called()

    def test_a_failed_publish_leaves_the_job_alone(self) -> None:
        # The images already exist; a broken ERP call must not lose them.
        job = self._job()
        request = CreateJobRequest(**job.input)

        with patch.object(
            self.service, "publish_erp_review", side_effect=HTTPException(status_code=502, detail="ERP lỗi")
        ):
            published = self.loop.run_until_complete(
                self.service._auto_publish_erp_review("job-erp", request)
            )

        self.assertEqual(0, published)
        logs = " ".join(entry.message for entry in self.store.get_job("job-erp").logs)
        self.assertIn("Không đăng được ảnh lên thẻ ERP để duyệt", logs)

    def test_publishing_twice_does_not_post_a_second_copy(self) -> None:
        self._job()
        self._publish()

        summary = self._publish()

        self.assertEqual(0, summary["published"])
        self.assertEqual(3, len(self.comments))

    def test_publish_skips_images_that_already_have_a_decision(self) -> None:
        self._job()
        self.loop.run_until_complete(self.service.apply_dashboard_approval("job-erp", 1, "rejected"))

        summary = self._publish()

        self.assertEqual(2, summary["published"])
        self.assertEqual(2, summary["pending"])
        self.assertNotIn("job-erp#1", " ".join(item["meta"] for item in self.comments))

    def test_sync_records_the_replies_as_decisions_and_writes_nothing_back(self) -> None:
        self._job()
        self._publish()
        self._answer(0, "Duyệt em nhé")
        self._answer(2, "bỏ")

        summary = self._sync()

        self.assertEqual(2, summary["decided"])
        self.assertEqual(1, summary["pending"])
        approvals = self.store.get_job("job-erp").result["dashboard_approvals"]
        self.assertEqual("approved", approvals["0"]["status"])
        self.assertEqual("rejected", approvals["2"]["status"])
        self.assertEqual("Khánh Linh", approvals["0"]["reviewer"]["name"])
        self.assertEqual("erp", approvals["0"]["source"])
        self.assertNotIn("1", approvals)
        # The card answers for itself - an approved image stays, a rejected one
        # disappears - so the app writes no word of its own either way.
        self.assertEqual([], self.replies)
        self.assertEqual(["cmt-2"], self.deleted)
        self.assertEqual([], self.notes)

    def test_sync_keeps_the_first_answer_when_a_reviewer_changes_their_mind(self) -> None:
        self._job()
        self._publish()
        self._answer(0, "duyệt", creation="2026-08-14 10:00:00")
        self._answer(0, "thôi bỏ đi", creation="2026-08-14 11:00:00")

        self._sync()
        # A second sync must not be able to overturn a recorded decision.
        again = self._sync()

        self.assertEqual(0, again["decided"])
        approvals = self.store.get_job("job-erp").result["dashboard_approvals"]
        self.assertEqual("approved", approvals["0"]["status"])

    def test_sync_ignores_our_own_comments_and_undecided_chatter(self) -> None:
        self._job()
        self._publish()
        self._answer(0, "[FLOW_V2_REVIEW_RESULT] ✅ Đã duyệt ảnh 1.")
        self._answer(1, "chỉnh lại ánh sáng giúp chị")

        summary = self._sync()

        self.assertEqual(0, summary["decided"])
        self.assertEqual(3, summary["pending"])
        self.assertEqual([], self.replies)

    def _vote(self, comment_index: int, *, like: int = 0, dislike: int = 0) -> None:
        self.comments[comment_index]["like_count"] = like
        self.comments[comment_index]["dislike_count"] = dislike

    def test_sync_reads_the_thumbs_buttons_when_nobody_typed_an_answer(self) -> None:
        # The ERP grew 👍/👎 buttons after this flow was built. A reviewer who
        # presses one has answered, and leaving those images pending forever
        # would be the app ignoring them.
        self._job()
        self._publish()
        self._vote(0, like=1)
        self._vote(2, dislike=2)

        summary = self._sync()

        self.assertEqual(2, summary["decided"])
        approvals = self.store.get_job("job-erp").result["dashboard_approvals"]
        self.assertEqual("approved", approvals["0"]["status"])
        self.assertEqual("rejected", approvals["2"]["status"])
        # 👎 takes the image off the card, exactly like a typed "bỏ".
        self.assertEqual(["cmt-2"], self.deleted)

    def test_a_typed_answer_beats_the_buttons(self) -> None:
        # A reply says who decided and why; a count says neither.
        self._job()
        self._publish()
        self._vote(0, dislike=3)
        self._answer(0, "duyệt nhé")

        self._sync()

        approvals = self.store.get_job("job-erp").result["dashboard_approvals"]
        self.assertEqual("approved", approvals["0"]["status"])
        self.assertEqual("Khánh Linh", approvals["0"]["reviewer"]["name"])
        self.assertEqual([], self.deleted)

    def test_a_split_vote_is_left_for_a_person_to_settle(self) -> None:
        self._job()
        self._publish()
        self._vote(0, like=2, dislike=2)
        self._vote(1, like=0, dislike=0)

        summary = self._sync()

        self.assertEqual(0, summary["decided"])
        self.assertEqual([], self.deleted)

    def test_sync_without_a_published_review_says_so(self) -> None:
        self._job()

        with self.assertRaises(HTTPException) as caught:
            self._sync()

        self.assertEqual(409, caught.exception.status_code)

    def test_publish_rejects_a_job_that_does_not_write_to_erp(self) -> None:
        job = self._job()
        job.input["erp_enabled"] = False
        self.loop.run_until_complete(self.store.patch_job(job.id, result={}))

        with self.assertRaises(HTTPException) as caught:
            self._publish()

        self.assertEqual(400, caught.exception.status_code)

    def test_only_jobs_with_an_open_review_are_polled(self) -> None:
        self._job()
        self.assertEqual([], self.service.erp_review_jobs_to_sync())

        self._publish()
        self.assertEqual(["job-erp"], self.service.erp_review_jobs_to_sync())

        for index in range(3):
            self.loop.run_until_complete(self.service.apply_dashboard_approval("job-erp", index, "approved"))
        # Every image answered: the card has nothing left to read.
        self.assertEqual([], self.service.erp_review_jobs_to_sync())

    def test_the_agent_network_wait_can_be_shortened(self) -> None:
        # Phép đo ấy đã có, nên con số đã đổi. Bài này trước đây chốt 45.0 và
        # sàn 5.0 với ghi chú "the default stays put until that is measured";
        # ``execution-notes.md`` đo trên ba card thật: cả ba đều hết giờ rồi
        # mới thấy ảnh qua project poll ~10s sau, và ở 15s ảnh vẫn sạch, vẫn
        # 2K — tiết kiệm 30s một card. PRD A1.1 hạ mặc định xuống 15.0, A1.2
        # hạ sàn xuống 0.0 để nói được "đừng chờ" — Agent mode không sinh
        # batchGenerateImages thành công thì kẹp dưới 5s là bắt chờ vô ích.
        # Hợp đồng đầy đủ nằm ở tests/test_agent_improvements.AgentModeDeadWaitTests.
        self.assertEqual(15.0, self.service._flow_agent_network_wait_seconds())

        with patch.dict("os.environ", {"FLOW_AGENT_NETWORK_WAIT_SECONDS": "12"}):
            self.assertEqual(12.0, self.service._flow_agent_network_wait_seconds())
        with patch.dict("os.environ", {"FLOW_AGENT_NETWORK_WAIT_SECONDS": "0"}):
            self.assertEqual(0.0, self.service._flow_agent_network_wait_seconds(), "tắt được hẳn")
        with patch.dict("os.environ", {"FLOW_AGENT_NETWORK_WAIT_SECONDS": "linh tinh"}):
            self.assertEqual(15.0, self.service._flow_agent_network_wait_seconds())

    def test_a_finished_run_keeps_the_review_it_published(self) -> None:
        # The post-module runner works from a snapshot taken before the
        # modules ran, but the approval module publishes to the card by
        # patching the job directly. Writing that stale snapshot back on
        # completion dropped erp_review - and a job with no items is one
        # erp_review_jobs_to_sync skips, so the card's 👍/👎 replies were
        # never read again.
        self._job()
        self._publish()
        stale = {"count": 3, "mode": "image"}

        merged = self.service._result_with_module_side_writes("job-erp", stale)
        self.loop.run_until_complete(self.store.patch_job("job-erp", result=merged))

        self.assertEqual(3, len(merged["erp_review"]["items"]))
        self.assertEqual(3, merged["count"], "the snapshot's own keys still win")
        self.assertEqual(["job-erp"], self.service.erp_review_jobs_to_sync())

    def test_the_card_fan_out_sizes_itself_to_the_machine(self) -> None:
        # Two cores a card, two held back for Chrome and the app.
        for cores, expected in ((None, 1), (2, 1), (4, 1), (6, 2), (8, 3), (10, 3), (64, 3)):
            with patch.dict("os.environ", {"ERP_IDEA_CONCURRENCY": ""}), patch(
                "os.cpu_count", return_value=cores
            ):
                self.assertEqual(
                    expected, self.service._erp_idea_concurrency(), f"{cores} nhân"
                )

    def test_a_number_set_by_hand_still_beats_the_machine(self) -> None:
        with patch("os.cpu_count", return_value=4):
            with patch.dict("os.environ", {"ERP_IDEA_CONCURRENCY": "4"}):
                self.assertEqual(4, self.service._erp_idea_concurrency())
            with patch.dict("os.environ", {"ERP_IDEA_CONCURRENCY": "9"}):
                self.assertEqual(4, self.service._erp_idea_concurrency(), "trần tay là 4")
            with patch.dict("os.environ", {"ERP_IDEA_CONCURRENCY": "0"}):
                self.assertEqual(1, self.service._erp_idea_concurrency())
            # Anything that is not a number falls back to the machine, not to
            # a hardcoded guess.
            for value in ("auto", "AUTO", "linh tinh"):
                with patch.dict("os.environ", {"ERP_IDEA_CONCURRENCY": value}):
                    self.assertEqual(1, self.service._erp_idea_concurrency(), value)

    def test_the_number_of_recaptcha_rounds_is_bounded(self) -> None:
        self.assertEqual(3, self.service._flow_upsample_recaptcha_rounds())
        with patch.dict("os.environ", {"FLOW_UPSAMPLE_RECAPTCHA_ROUNDS": "2"}):
            self.assertEqual(2, self.service._flow_upsample_recaptcha_rounds())
        with patch.dict("os.environ", {"FLOW_UPSAMPLE_RECAPTCHA_ROUNDS": "0"}):
            self.assertEqual(1, self.service._flow_upsample_recaptcha_rounds(), "ít nhất 1 lượt")
        with patch.dict("os.environ", {"FLOW_UPSAMPLE_RECAPTCHA_ROUNDS": "99"}):
            self.assertEqual(5, self.service._flow_upsample_recaptcha_rounds(), "trần 5 lượt")
        with patch.dict("os.environ", {"FLOW_UPSAMPLE_RECAPTCHA_ROUNDS": "linh tinh"}):
            self.assertEqual(3, self.service._flow_upsample_recaptcha_rounds())

    def test_a_refused_recaptcha_token_is_retried_with_a_fresh_one(self) -> None:
        # The live cards' un-upscaled images were all one 403: "reCAPTCHA
        # evaluation failed". One token used to be one chance, so a refused
        # token left the image at 1024 for good.
        client = _FakeUpsampleClient(self, refuse_tokens={"tok-1"})

        upscaled = self._upsample(client)

        self.assertEqual(_FakeUpsampleClient.BIG, upscaled)
        self.assertEqual(2, client.contexts, "lượt hai phải xin token mới")
        self.assertEqual({"tok-1", "tok-2"}, set(client.tokens_used))

    def test_a_failure_that_is_not_the_token_is_not_paid_for_twice(self) -> None:
        # A fresh token cannot help a 500, so re-minting one only spends time.
        client = _FakeUpsampleClient(self, error=RuntimeError("HTTP 500 internal"))

        upscaled = self._upsample(client)

        self.assertEqual(b"anh-goc", upscaled, "trả lại ảnh gốc để vẫn đăng được")
        self.assertEqual(1, client.contexts)

    def test_the_token_is_minted_under_the_browser_lock_once_the_batch_let_go(self) -> None:
        # Minting runs grecaptcha through page.evaluate and may reload the
        # page. The 2K batch hands the browser back so the next card can
        # generate, so an unguarded mint lands on that card's page - which is
        # what got the token refused in the first place.
        client = _FakeUpsampleClient(self, refuse_tokens={"tok-1"})

        self._upsample(client, session_lock_held=False)

        self.assertEqual([True, True], client.lock_held_while_minting)
        self.assertFalse(self.service._browser_session_lock.locked(), "phải trả khoá lại")

    def test_the_token_is_minted_in_place_while_the_batch_still_holds_the_browser(self) -> None:
        # Taking the same non-reentrant lock a second time would hang forever.
        client = _FakeUpsampleClient(self, refuse_tokens=set())

        self.loop.run_until_complete(self.service._browser_session_lock.acquire())
        try:
            upscaled = self._upsample(client, session_lock_held=True)
        finally:
            self.service._browser_session_lock.release()

        self.assertEqual(_FakeUpsampleClient.BIG, upscaled)

    def test_a_refused_media_is_marked_and_never_retried_automatically(self) -> None:
        # The decision is scoped to the one ERP job/media, not a process-wide
        # streak that would also penalize the next unrelated image.
        job = self._job(count=1)
        always_refused = {f"tok-{n}" for n in range(1, 40)}
        with patch.dict(
            "os.environ",
            {"FLOW_UPSAMPLE_RECAPTCHA_MANUAL_AFTER": "2", "FLOW_UPSAMPLE_RECAPTCHA_ROUNDS": "1"},
        ):
            first = _FakeUpsampleClient(self, refuse_tokens=always_refused)
            second = _FakeUpsampleClient(self, refuse_tokens=always_refused)
            blocked = _FakeUpsampleClient(self, refuse_tokens=always_refused)
            self._upsample(first, erp_task_id=self.TASK, job_id=job.id)
            self._upsample(second, erp_task_id=self.TASK, job_id=job.id)
            self._upsample(blocked, erp_task_id=self.TASK, job_id=job.id)

        self.assertEqual(1, first.contexts)
        self.assertEqual(1, second.contexts)
        self.assertEqual(0, blocked.contexts, "media đã gắn cờ không được gọi Flow lại")
        state_key = self.service._flow_upsample_recaptcha_state_key(
            self.TASK, job.id, "11111111-2222-3333-4444-555555555555"
        )
        record = self.store.get_job(job.id).result["flow_upsample_recaptcha"]["media"][state_key]
        self.assertEqual(2, record["rejected_count"])
        self.assertTrue(record["needs_manual_review"])
        self.assertTrue(record["next_retry_at"])
        self.assertTrue(any("Cần xem thủ công" in entry.message for entry in self.store.get_job(job.id).logs))

    def test_the_manual_recaptcha_state_survives_a_restart(self) -> None:
        job = self._job(count=1)
        always_refused = {f"tok-{n}" for n in range(1, 40)}
        with patch.dict(
            "os.environ",
            {"FLOW_UPSAMPLE_RECAPTCHA_MANUAL_AFTER": "2", "FLOW_UPSAMPLE_RECAPTCHA_ROUNDS": "1"},
        ):
            self._upsample(_FakeUpsampleClient(self, refuse_tokens=always_refused), erp_task_id=self.TASK, job_id=job.id)
            self._upsample(_FakeUpsampleClient(self, refuse_tokens=always_refused), erp_task_id=self.TASK, job_id=job.id)
            restarted_store = StateStore()
            restarted_service = FlowWebService(restarted_store)

        record = restarted_service._flow_upsample_recaptcha_record(
            job.id, self.TASK, "11111111-2222-3333-4444-555555555555"
        )
        self.assertEqual(job.id, record["job_id"])
        self.assertEqual(self.TASK, record["task_id"])
        self.assertTrue(record["needs_manual_review"])
        self.assertTrue(record["next_retry_at"])

    def test_a_successful_2k_result_clears_only_its_old_recaptcha_count(self) -> None:
        job = self._job(count=1)
        refused = _FakeUpsampleClient(self, refuse_tokens={f"tok-{n}" for n in range(1, 40)})
        self._upsample(refused, erp_task_id=self.TASK, job_id=job.id)
        self.assertTrue(
            self.service._flow_upsample_recaptcha_record(
                job.id, self.TASK, "11111111-2222-3333-4444-555555555555"
            )
        )

        self._upsample(_FakeUpsampleClient(self, refuse_tokens=set()), erp_task_id=self.TASK, job_id=job.id)

        self.assertEqual(
            {},
            self.service._flow_upsample_recaptcha_record(
                job.id, self.TASK, "11111111-2222-3333-4444-555555555555"
            ),
        )

    def test_a_plain_failure_does_not_create_a_recaptcha_record(self) -> None:
        job = self._job(count=1)
        self._upsample(
            _FakeUpsampleClient(self, error=RuntimeError("HTTP 500 internal")),
            erp_task_id=self.TASK,
            job_id=job.id,
        )

        self.assertEqual(
            {},
            self.service._flow_upsample_recaptcha_record(
                job.id, self.TASK, "11111111-2222-3333-4444-555555555555"
            ),
        )

    def _upsample(
        self,
        client: Any,
        *,
        session_lock_held: bool = True,
        erp_task_id: str = "",
        job_id: str = "",
    ) -> bytes:
        """Run one upscale against a fake client, with the slow parts stubbed."""

        async def no_ui_download(*_args, **_kwargs):
            return b""

        with patch.object(self.service, "FLOW_UPSAMPLE_RECAPTCHA_BACKOFF_S", 0.0), patch.object(
            self.service, "_upsample_image_via_flow_ui_download", side_effect=no_ui_download
        ), patch.object(
            self.service,
            "_image_size_from_bytes",
            lambda data: (2048, 2048) if data == _FakeUpsampleClient.BIG else (1024, 1024),
        ):
            return self.loop.run_until_complete(
                self.service._upsample_image_via_flow(
                    client,
                    b"anh-goc",
                    media_generation_id="11111111-2222-3333-4444-555555555555",
                    erp_task_id=erp_task_id,
                    job_id=job_id,
                    session_lock_held=session_lock_held,
                )
            )

    def test_the_poller_reads_every_open_review_on_its_own(self) -> None:
        self._job()
        self._publish()
        calls: List[str] = []
        slept: List[Any] = []

        async def fake_sleep(seconds):
            # One lap, then stop the loop the way a shutdown would.
            if slept:
                raise asyncio.CancelledError
            slept.append(seconds)

        async def fake_sync(job_id):
            calls.append(job_id)
            return {}

        with patch.object(self.service, "sync_erp_review", side_effect=fake_sync), patch(
            "flow_web.service.asyncio.sleep", side_effect=fake_sleep
        ):
            with self.assertRaises(asyncio.CancelledError):
                self.loop.run_until_complete(self.service.watch_erp_reviews())

        self.assertEqual(["job-erp"], calls)
        self.assertEqual([self.service.ERP_REVIEW_POLL_DEFAULT_S], slept)

    def test_the_poller_can_be_switched_off(self) -> None:
        with patch.dict("os.environ", {"ERP_REVIEW_POLL_SECONDS": "0"}), patch(
            "flow_web.service.asyncio.sleep"
        ) as sleep:
            self.loop.run_until_complete(self.service.watch_erp_reviews())
        sleep.assert_not_called()

    def _reject_by_tool(self, index: int) -> None:
        job = self.store.get_job("job-erp")
        result = dict(job.result or {})
        approvals = dict(result.get("dashboard_approvals") or {})
        approvals[str(index)] = {
            "artifact_index": index,
            "status": "rejected",
            "reviewer": {"name": "Flow v2 (còn watermark Gemini)"},
            "source": "dashboard",
        }
        result["dashboard_approvals"] = approvals
        self.loop.run_until_complete(self.store.patch_job("job-erp", result=result))

    def test_reopen_returns_tool_rejections_to_the_reviewers(self) -> None:
        job = self._job()
        for artifact in job.artifacts:
            artifact.watermark_status = "cleaned"
        self.loop.run_until_complete(self.store.replace_artifacts("job-erp", list(job.artifacts)))
        self._reject_by_tool(1)
        self.loop.run_until_complete(self.service.apply_dashboard_approval("job-erp", 2, "rejected", "Khánh Linh"))

        summary = self.loop.run_until_complete(self.service.reopen_watermark_rejections("job-erp"))

        self.assertEqual([1], summary["reopened"])
        approvals = self.store.get_job("job-erp").result["dashboard_approvals"]
        # The reviewer's own "no" is untouched; only the tool's is re-opened.
        self.assertNotIn("1", approvals)
        self.assertEqual("rejected", approvals["2"]["status"])
        self.assertEqual(1, len(self.store.get_job("job-erp").result["reopened_approvals"]))
        # And the re-opened image goes back onto the card for a real answer.
        self.assertEqual(2, self._publish()["published"])

    def test_reopen_arms_the_delivery_step_again(self) -> None:
        # The card was already archived once. Without re-arming the ERP step the
        # re-opened image would be approved and then never delivered, because a
        # finished module is skipped when the pipeline resumes.
        job = self._job()
        for artifact in job.artifacts:
            artifact.watermark_status = "cleaned"
        self.loop.run_until_complete(self.store.replace_artifacts("job-erp", list(job.artifacts)))
        result = {
            "automation_execution": {
                "nodes": [
                    {"id": "approval-1", "type": "approval", "status": "completed"},
                    {"id": "erp-1", "type": "erp", "status": "completed", "completed_at": "2026-08-14 10:00:00"},
                ],
                "completed": True,
            }
        }
        self.loop.run_until_complete(self.store.patch_job("job-erp", result=result))
        self._reject_by_tool(1)

        self.loop.run_until_complete(self.service.reopen_watermark_rejections("job-erp"))

        nodes = self.store.get_job("job-erp").result["automation_execution"]["nodes"]
        erp_node = next(node for node in nodes if node["type"] == "erp")
        self.assertEqual("pending", erp_node["status"])
        self.assertNotIn("completed_at", erp_node)
        self.assertFalse(self.store.get_job("job-erp").result["automation_execution"]["completed"])

    def test_reopen_leaves_an_image_that_is_still_marked(self) -> None:
        job = self._job()
        job.artifacts[1].watermark_status = "metadata_only"
        self.loop.run_until_complete(self.store.replace_artifacts("job-erp", list(job.artifacts)))
        self._reject_by_tool(1)

        summary = self.loop.run_until_complete(self.service.reopen_watermark_rejections("job-erp"))

        self.assertEqual([], summary["reopened"])
        self.assertEqual("rejected", self.store.get_job("job-erp").result["dashboard_approvals"]["1"]["status"])

    def test_the_archive_never_posts_an_image_to_the_same_card_twice(self) -> None:
        from flow_web.schemas import CreateJobRequest

        job = self._job()
        request = CreateJobRequest(**job.input)
        for index in range(3):
            self.loop.run_until_complete(self.service.apply_dashboard_approval("job-erp", index, "approved"))

        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_upload_file", side_effect=lambda *a: f"/private/files/{a[-1]}"
        ), patch.object(self.service, "_erp_graphql", side_effect=self._fake_add_comment), patch.object(
            self.service, "_upsample_artifact_bytes", side_effect=Exception("no flow session")
        ), patch.object(self.service, "_erp_add_task_label", return_value={}):
            first = self.loop.run_until_complete(
                self.service._archive_erp_artifacts("job-erp", request, list(job.artifacts))
            )
        self.loop.run_until_complete(
            self.store.patch_job("job-erp", result={**(self.store.get_job("job-erp").result or {}), "erp": first})
        )

        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_upload_file"
        ) as upload, patch.object(self.service, "_erp_add_task_label", return_value={}):
            second = self.loop.run_until_complete(
                self.service._archive_erp_artifacts("job-erp", request, list(job.artifacts))
            )

        self.assertEqual(3, first["sent"])
        self.assertEqual(3, second["sent"])
        self.assertEqual(3, second["reused_review_comments"])
        upload.assert_not_called()

    def test_the_archive_reuses_the_comments_the_reviewer_already_saw(self) -> None:
        from flow_web.schemas import CreateJobRequest

        job = self._job()
        self._publish()
        self._answer(0, "duyệt")
        self._answer(1, "duyệt")
        self._answer(2, "bỏ")
        self._sync()

        request = CreateJobRequest(**job.input)
        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_upload_file"
        ) as upload, patch.object(self.service, "_erp_task_detail", side_effect=self._detail), patch.object(
            self.service, "_erp_add_task_label", return_value={}
        ):
            result = self.loop.run_until_complete(
                self.service._archive_erp_artifacts("job-erp", request, list(job.artifacts))
            )

        # Nothing is uploaded a second time: the approved images are already on
        # the card as the very files the reviewer approved.
        upload.assert_not_called()
        self.assertEqual(2, result["sent"])
        self.assertEqual(2, result["reused_review_comments"])
        self.assertEqual(0, result["failed"])
        self.assertEqual(1, result["rejected"])

    def test_a_dislike_takes_the_image_off_the_card(self) -> None:
        self._job()
        self._publish()

        self.loop.run_until_complete(
            self.service.apply_dashboard_approval("job-erp", 1, "rejected", "Khánh Linh")
        )

        # The picture is gone from the card and nothing is written in its place;
        # who dropped it is recorded in the job log instead.
        self.assertEqual(["cmt-1"], self.deleted)
        self.assertEqual(["cmt-0", "cmt-2"], [item["name"] for item in self.comments])
        self.assertEqual([], self.notes)
        logs = " ".join(entry.message for entry in self.store.get_job("job-erp").logs)
        self.assertIn("Đã gỡ ảnh 2", logs)
        self.assertIn("Khánh Linh", logs)
        items = self.store.get_job("job-erp").result["erp_review"]["items"]
        self.assertEqual("", items["1"]["comment"])
        self.assertTrue(items["1"]["deleted_at"])

    def test_bot_request_reloads_the_card_then_app_key_deletes_only_the_same_disliked_review_image(self) -> None:
        self._job()
        self._publish()
        self._vote(1, dislike=2)

        with patch.object(self.service, "_erp_assert_task_in_project") as in_project, patch.object(
            self.service, "_erp_task_detail", side_effect=self._detail
        ) as reread:
            deleted = self.service.delete_disliked_erp_review_image_for_agent(self.TASK, "cmt-1")

        self.assertTrue(deleted)
        in_project.assert_called_once_with("test-key", "test-secret", self.TASK)
        reread.assert_called_once_with("test-key", "test-secret", self.TASK)
        self.service._erp_delete_task_comment.assert_called_once_with(
            "test-key", "test-secret", self.TASK, "cmt-1"
        )
        self.assertEqual(["cmt-1"], self.deleted)

    def test_bot_request_does_not_delete_when_the_fresh_vote_is_no_longer_dislike(self) -> None:
        self._job()
        self._publish()
        # The bot's old tree may have seen 👎. The only fact that matters is
        # the card the app reads immediately before the destructive call.
        self._vote(1, like=3, dislike=2)

        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_task_detail", side_effect=self._detail
        ):
            deleted = self.service.delete_disliked_erp_review_image_for_agent(self.TASK, "cmt-1")

        self.assertFalse(deleted)
        self.assertEqual([], self.deleted)
        self.assertEqual(3, len(self.comments))

    def test_bot_request_does_not_delete_an_unmarked_image_even_when_people_dislike_it(self) -> None:
        self._job()
        self._publish()
        self.comments[1]["meta"] = ""
        self.comments[1]["content"] = "Ảnh người dùng tự thêm"
        self._vote(1, dislike=3)

        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_task_detail", side_effect=self._detail
        ):
            deleted = self.service.delete_disliked_erp_review_image_for_agent(self.TASK, "cmt-1")

        self.assertFalse(deleted)
        self.assertEqual([], self.deleted)

    def test_bot_request_does_not_treat_a_review_result_note_as_a_deletable_review_image(self) -> None:
        self._job()
        self._publish()
        self.comments[1]["meta"] = "[FLOW_V2_REVIEW_RESULT] ảnh đã xử lý"
        self._vote(1, dislike=3)

        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_task_detail", side_effect=self._detail
        ):
            deleted = self.service.delete_disliked_erp_review_image_for_agent(self.TASK, "cmt-1")

        self.assertFalse(deleted)
        self.assertEqual([], self.deleted)

    def test_the_log_does_not_stutter_when_the_button_is_the_reviewer(self) -> None:
        # A vote has no name to credit, so the reviewer string is the button
        # itself and the line must not read "vì 👎 trên thẻ ERP không thích".
        self._job()
        self._publish()

        self.loop.run_until_complete(
            self.service.apply_dashboard_approval("job-erp", 1, "rejected", "👎 trên thẻ ERP")
        )

        logs = " ".join(entry.message for entry in self.store.get_job("job-erp").logs)
        self.assertIn("theo 👎 trên thẻ ERP", logs)
        self.assertNotIn("👎 trên thẻ ERP không thích", logs)

    def test_a_like_leaves_the_image_where_the_reviewer_can_see_it(self) -> None:
        self._job()
        self._publish()

        self.loop.run_until_complete(self.service.apply_dashboard_approval("job-erp", 0, "approved"))

        self.assertEqual([], self.deleted)
        self.assertEqual(3, len(self.comments))

    def test_the_same_image_is_never_deleted_twice(self) -> None:
        self._job()
        self._publish()
        self.loop.run_until_complete(self.service.apply_dashboard_approval("job-erp", 1, "rejected"))

        # A repeat of the same decision is a no-op, so no second delete call.
        self.loop.run_until_complete(self.service.apply_dashboard_approval("job-erp", 1, "rejected"))
        self.loop.run_until_complete(self.service._erp_discard_rejected_review_image("job-erp", 1))

        self.assertEqual(["cmt-1"], self.deleted)

    def test_an_image_the_tool_refused_for_a_watermark_stays_on_the_card(self) -> None:
        # It has not been reviewed by anyone yet: reopen_watermark_rejections
        # hands it back once the mark is cleaned, which needs it to still exist.
        self._job()
        self._publish()

        self.loop.run_until_complete(
            self.service.apply_dashboard_approval("job-erp", 1, "rejected", "Flow v2", source="watermark_gate")
        )

        self.assertEqual([], self.deleted)
        self.assertEqual(3, len(self.comments))

    def test_publishing_leaves_the_idea_card_in_the_todo_column(self) -> None:
        # Cột chỉ đổi khi một bước *đã xong*. Ảnh mới đưa lên bảng thì bước
        # duyệt còn chưa bắt đầu, nên thẻ ở nguyên *Cần làm*.
        self._job()

        self._publish()

        self.assertEqual([], self.status_writes)

    def test_a_card_a_person_already_closed_is_not_moved(self) -> None:
        self._job()
        self.task_status = "Cancelled"

        self._publish()

        self.assertEqual([], self.status_writes)

    def test_the_idea_card_moves_to_doing_once_its_approved_images_land(self) -> None:
        from flow_web.schemas import CreateJobRequest

        job = self._job()
        self._publish()
        self._answer(0, "👍")
        self._answer(1, "👎")
        self._answer(2, "duyệt")
        self._sync()
        self.status_writes.clear()

        request = CreateJobRequest(**job.input)
        # Gắn nhãn DONE là lượt ghi ERP riêng; giả đi để chạy lẻ module không gọi ra ngoài.
        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_task_detail", side_effect=self._detail
        ), patch.object(self.service, "_erp_add_task_label", return_value={}):
            result = self.loop.run_until_complete(
                self.service._archive_erp_artifacts("job-erp", request, list(job.artifacts))
            )

        self.assertEqual(2, result["sent"])
        # Duyệt xong ảnh là xong bước làm ảnh, không phải xong thẻ: bước kế là
        # điền mã SKU, và đó là việc của cột *Đang làm*.
        self.assertEqual(["Working"], self.status_writes)

    def test_a_card_whose_images_were_all_disliked_stays_open(self) -> None:
        from flow_web.schemas import CreateJobRequest

        job = self._job()
        self._publish()
        for index in range(3):
            self._answer(index, "bỏ")
        self._sync()
        self.status_writes.clear()

        request = CreateJobRequest(**job.input)
        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_task_detail", side_effect=self._detail
        ), patch.object(self.service, "_erp_add_task_label", return_value={}) as label:
            result = self.loop.run_until_complete(
                self.service._archive_erp_artifacts("job-erp", request, list(job.artifacts))
            )

        self.assertEqual(0, result["sent"])
        self.assertEqual([], self.status_writes)
        # Không ảnh nào lên thẻ thì không có gì để gắn DONE.
        label.assert_not_called()

    def test_the_dashboard_payload_still_carries_the_review_state(self) -> None:
        # The browser gets the compacted jobs, so anything the review queue reads
        # has to survive compaction - otherwise a decided image reads as pending
        # and the ERP row never learns which card the images went to.
        self._job()
        self._publish()
        self._answer(0, "duyệt")
        self._sync()

        job = next(item for item in self.service.get_state_payload()["jobs"] if item["id"] == "job-erp")
        result = job["result"]

        self.assertEqual("approved", result["dashboard_approvals"]["0"]["status"])
        self.assertEqual(1, result["dashboard_approval_summary"]["approved"])
        self.assertEqual(self.TASK, result["erp_review"]["task_id"])
        self.assertEqual({"0", "1", "2"}, set(result["erp_review"]["items"]))
        self.assertTrue(result["erp_review"]["items"]["0"]["url"])


class ErpAdvanceStatusTests(unittest.TestCase):
    """Chuyển cột thẻ ERP sau khi ảnh xong — và khi nào thì không chuyển."""

    TASK = "TASK-2026-00906"

    class _Store:
        def __init__(self) -> None:
            self.logs: List[str] = []

        async def append_log(self, job_id: str, line: str) -> None:
            self.logs.append(line)

    def setUp(self) -> None:
        self.service = FlowWebService.__new__(FlowWebService)
        self.service.store = self._Store()
        self.moves: List[Dict[str, str]] = []

    def _advance(self, status: str, *, meta: str, current: str = "Pending Review") -> bool:
        detail = {"name": self.TASK, "status": current, "meta": meta}

        def update(key: str, token: str, task: str, wanted: str) -> Dict[str, Any]:
            self.moves.append({"task": task, "status": wanted})
            return {"name": task, "status": wanted}

        with patch.object(self.service, "_erp_credentials", return_value=("key", "token")), \
                patch.object(self.service, "_erp_task_detail", return_value=detail), \
                patch.object(self.service, "_erp_update_task_status", side_effect=update):
            return asyncio.run(
                self.service._erp_advance_task_status("job-1", self.TASK, status)
            )

    def test_a_plain_card_is_never_closed_by_the_machine(self) -> None:
        # Thẻ không khai listing dừng ở *Đang review* — đó là bàn của người
        # viết bài. Máy dọn thẻ khỏi bàn ấy là làm mất việc của họ.
        moved = self._advance(FlowWebService.ERP_STATUS_COMPLETED, meta="")

        self.assertFalse(moved)
        self.assertEqual([], self.moves)
        self.assertTrue(
            any("Đang review" in line for line in self.service.store.logs),
            self.service.store.logs,
        )

    def test_a_listing_card_is_closed_once_its_post_is_up(self) -> None:
        # Chỉ thẻ listing mới có cái mốc "xong" mà máy tự nhìn thấy được: bài
        # đã lên shop. Thời điểm gọi là do ``pipeline.decide`` canh, hàng rào ở
        # đây chỉ lo đúng một việc — không đóng nhầm thẻ ảnh.
        moved = self._advance(
            FlowWebService.ERP_STATUS_COMPLETED, meta="action_1: listing\nacc: acc32\n"
        )

        self.assertTrue(moved)
        self.assertEqual([{"task": self.TASK, "status": "Completed"}], self.moves)

    def test_a_card_is_never_dragged_backwards(self) -> None:
        # Người ta kéo tay thẻ sang cột sau là có ý; máy kéo ngược về là xoá ý
        # đó đi.
        moved = self._advance(
            FlowWebService.ERP_STATUS_DOING, meta="", current="Pending Review"
        )

        self.assertFalse(moved)
        self.assertEqual([], self.moves)

    def test_a_card_a_person_closed_is_not_reopened(self) -> None:
        moved = self._advance(
            FlowWebService.ERP_STATUS_DOING, meta="", current="Cancelled"
        )

        self.assertFalse(moved)
        self.assertEqual([], self.moves)

    def test_a_listing_card_still_moves_to_pending_review(self) -> None:
        # Chỉ chặn đúng nước đóng thẻ. Đưa ảnh lên chờ 👍/👎 vẫn phải chạy,
        # nếu không thì người duyệt không thấy thẻ ở đâu cả.
        moved = self._advance(
            FlowWebService.ERP_STATUS_PENDING_REVIEW,
            meta="action_1: listing\n",
            current="Working",
        )

        self.assertTrue(moved)
        self.assertEqual([{"task": self.TASK, "status": "Pending Review"}], self.moves)



class AgentChatEditTests(unittest.TestCase):
    """Đường ghi của lệnh sửa bằng lời: giữ nguyên khối cũ, chỉ đổi ô được phép."""

    TASK = "TASK-2026-00906"

    def setUp(self) -> None:
        self.service = FlowWebService.__new__(FlowWebService)
        self.blocks: List[str] = []

    def _edit(self, edits, *, meta: str) -> Dict[str, Any]:
        detail = {"name": self.TASK, "status": "Working", "meta": meta}

        def write(key: str, token: str, task: str, block: str) -> Dict[str, Any]:
            self.blocks.append(block)
            return {"name": task}

        with patch.object(self.service, "_erp_credentials", return_value=("key", "token")), \
                patch.object(self.service, "_erp_task_detail", return_value=detail), \
                patch.object(self.service, "_erp_update_task_meta", side_effect=write):
            return self.service.edit_task_meta(self.TASK, edits)

    def test_the_rest_of_the_panel_survives_the_write(self) -> None:
        # ``updateTaskMeta`` thay **cả khối**. Ghi mỗi dòng mình quan tâm là
        # xoá sạch mọi thuộc tính người ta đã gõ.
        self._edit(
            (("acc", "acc32"),), meta="product: khăn tay\naction_1: listing\nacc: acc7\n"
        )

        self.assertEqual(1, len(self.blocks))
        self.assertIn("product: khăn tay", self.blocks[0])
        self.assertIn("action_1: listing", self.blocks[0])
        self.assertIn("acc: acc32", self.blocks[0])
        self.assertNotIn("acc7", self.blocks[0])

    def test_a_field_outside_the_list_is_refused_at_the_write_path_too(self) -> None:
        # Bên soạn lời đã lọc rồi, nhưng đây là đường **ghi**: một đường ghi
        # không được dựa vào việc bên gọi có lọc hay không.
        outcome = self._edit((("status", "Completed"), ("action_1", "listing")), meta="")

        self.assertEqual({}, outcome["written"])
        self.assertEqual([], self.blocks)

    def test_clearing_a_field_leaves_the_line_standing_and_empty(self) -> None:
        # Dòng ``acc:`` để trống là lời nhắn "tài khoản còn chờ", không phải
        # rác — xoá luôn cả dòng là tự ý sửa thẻ thêm một bước nữa.
        self._edit((("acc", ""),), meta="acc: acc32\nproduct: bờm\n")

        self.assertIn("acc:", self.blocks[0])
        self.assertNotIn("acc32", self.blocks[0])
        self.assertIn("product: bờm", self.blocks[0])

    def test_the_card_is_read_again_right_before_it_is_written(self) -> None:
        # Cây đọc đầu lượt quét có thể đã cũ vài giây, và vài giây đó đủ để ai
        # đó gõ thêm một dòng — dòng sẽ biến mất nếu ghi từ bản đọc cũ.
        detail = {"name": self.TASK, "meta": "product: bờm\n"}
        reads: List[str] = []

        def read(key: str, token: str, task: str) -> Dict[str, Any]:
            reads.append(task)
            return detail

        with patch.object(self.service, "_erp_credentials", return_value=("key", "token")), \
                patch.object(self.service, "_erp_task_detail", side_effect=read), \
                patch.object(self.service, "_erp_update_task_meta", return_value={}):
            self.service.edit_task_meta(self.TASK, (("sku", "BT_3_007"),))

        self.assertEqual([self.TASK], reads)


class AgentMetaInheritWriteTests(unittest.TestCase):
    """Đường ghi khi bot chép Thuộc tính của thẻ cha xuống thẻ con.

    Bot chỉ nói "thẻ này thiếu mấy ô này"; app đọc lại thẻ rồi mới ghi, và chỉ
    điền ô còn trống — ô người ta đã gõ trên thẻ con là của thẻ con.
    """

    TASK = "TASK-2026-05391"
    FROM_PARENT = {
        "product_type": "Punch Needle Ornament",
        "product_group": "handmade",
        "fulfillment": "FBM",
        "sales_channel": "Etsy",
    }

    def setUp(self) -> None:
        self.service = FlowWebService.__new__(FlowWebService)
        self.writes: List[Dict[str, Any]] = []

    def _inherit(self, values, *, meta: str, project: str = "PROJ-0087") -> Dict[str, Any]:
        detail = {"name": self.TASK, "status": "Working", "meta": meta, "project": project}

        def write(key: str, token: str, task: str, block: str, **kwargs: Any) -> Dict[str, Any]:
            self.writes.append({"task": task, "block": block, **kwargs})
            return {"name": task}

        with patch.object(self.service, "_erp_credentials", return_value=("key", "token")), \
                patch.object(self.service, "_erp_task_detail", return_value=detail), \
                patch.object(self.service, "_erp_update_task_meta", side_effect=write):
            return self.service.inherit_task_meta(self.TASK, values)

    def test_only_blank_fields_are_filled_and_the_rest_of_the_block_survives(self) -> None:
        outcome = self._inherit(self.FROM_PARENT, meta="fulfillment: FBA\nnote: mau do\naccount:\n")

        self.assertEqual(1, len(self.writes))
        block = self.writes[0]["block"]
        self.assertIn("fulfillment: FBA", block)
        self.assertNotIn("FBM", block)
        self.assertIn("note: mau do", block)
        self.assertIn("product_type: Punch Needle Ornament", block)
        self.assertIn("sales_channel: Etsy", block)
        self.assertEqual(
            {"product_type": "Punch Needle Ornament", "product_group": "handmade", "sales_channel": "Etsy"},
            outcome["written"],
        )

    def test_per_card_fields_are_refused_at_the_write_path_too(self) -> None:
        # Mã SKU và ``action_1`` là của riêng từng thẻ. Bên bot đã lọc, nhưng
        # đây là đường **ghi**: không dựa vào việc bên gọi có lọc hay không.
        outcome = self._inherit({"sku": "OR_1_001", "action_1": "listing", "parent_task": "TASK-X"}, meta="")

        self.assertEqual({}, outcome["written"])
        self.assertEqual([], self.writes)

    def test_a_card_that_got_filled_meanwhile_is_not_written(self) -> None:
        # Cây bot đọc đầu lượt quét có thể đã cũ: người ta vừa điền tay xong
        # thì không còn gì để chép, và ghi lại là một request phí.
        full = "\n".join(f"{key}: {value}" for key, value in self.FROM_PARENT.items())

        outcome = self._inherit(self.FROM_PARENT, meta=full)

        self.assertEqual({}, outcome["written"])
        self.assertEqual([], self.writes)

    def test_the_card_is_read_again_right_before_it_is_written(self) -> None:
        reads: List[str] = []

        def read(key: str, token: str, task: str) -> Dict[str, Any]:
            reads.append(task)
            return {"name": self.TASK, "meta": "", "project": "PROJ-0087"}

        with patch.object(self.service, "_erp_credentials", return_value=("key", "token")), \
                patch.object(self.service, "_erp_task_detail", side_effect=read), \
                patch.object(self.service, "_erp_update_task_meta", return_value={}):
            self.service.inherit_task_meta(self.TASK, self.FROM_PARENT)

        self.assertEqual([self.TASK], reads)

    def test_the_project_read_off_the_card_goes_to_the_fence(self) -> None:
        # Hàng rào cũ quét bảng của mọi dự án được phép để tìm thẻ: 48 thẻ con
        # là vài trăm request. Thẻ vừa đọc lại đã tự nói nó ở dự án nào.
        self._inherit(self.FROM_PARENT, meta="")

        self.assertEqual("PROJ-0087", self.writes[0].get("project"))


class UpdateTaskMetaProjectFenceTests(unittest.TestCase):
    """``_erp_update_task_meta`` kiểm dự án — rẻ khi người gọi đã biết dự án."""

    def setUp(self) -> None:
        self.service = FlowWebService.__new__(FlowWebService)
        self.calls: List[str] = []

    def _graphql(self, query: str, variables: Dict[str, Any], operation: str, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(operation)
        if operation == "TaskBoard":
            return {"taskBoard": {"columns": [{"tasks": [{"name": "TASK-2026-05391"}]}]}}
        return {"updateTaskMeta": {"name": variables.get("task")}}

    def _write(self, **kwargs: Any) -> None:
        with patch.object(self.service, "_erp_allowed_project_ids", return_value=["PROJ-0013", "PROJ-0087"]), \
                patch.object(self.service, "_erp_graphql", side_effect=self._graphql):
            self.service._erp_update_task_meta("key", "token", "TASK-2026-05391", "fulfillment: FBM\n", **kwargs)

    def test_a_known_allowed_project_skips_the_board_scan(self) -> None:
        self._write(project="PROJ-0087")

        self.assertEqual(["UpdateTaskMeta"], self.calls)

    def test_a_project_outside_the_fence_is_refused_before_any_write(self) -> None:
        with self.assertRaises(RuntimeError):
            self._write(project="PROJ-9999")

        self.assertEqual([], self.calls)

    def test_without_a_project_the_old_board_scan_still_guards_the_write(self) -> None:
        self._write()

        self.assertEqual(["TaskBoard", "UpdateTaskMeta"], self.calls)


class BotMetaInheritHookTests(unittest.TestCase):
    """App dựng bot thì phải nối cả đường chép Thuộc tính xuống thẻ con.

    Nối thiếu thì hỏng kiểu không kêu: bot vẫn quét, thẻ cha vẫn đầy đủ, chỉ
    là thẻ con mãi trống — đúng ca của TASK-2026-05384.
    """

    def _service(self):
        from flow_web.account_book import AccountBook

        svc = FlowWebService.__new__(FlowWebService)
        svc._erp_base_url = lambda: "https://erp.invalid"
        svc.load_account_book = lambda: AccountBook(entries={})
        return svc

    def _hook(self, svc):
        seen: Dict[str, Any] = {}

        def build(config, **kwargs):
            seen.update(kwargs)
            return object()

        with patch("flow_web.service.build_agent_bot", build):
            svc.agent_bot()
        return seen.get("meta_inherit_hook")

    def test_the_app_hands_the_bot_a_way_to_fill_children(self) -> None:
        self.assertIsNotNone(self._hook(self._service()))

    def test_the_hook_reaches_the_real_write_path(self) -> None:
        svc = self._service()
        calls: List[tuple] = []
        svc.inherit_task_meta = lambda task_id, values: calls.append((task_id, dict(values))) or {}

        self._hook(svc)("TASK-1", {"fulfillment": "FBM"})

        self.assertEqual([("TASK-1", {"fulfillment": "FBM"})], calls)


class AdvanceErpPipelineTests(unittest.TestCase):
    """Một lượt đẩy thẻ: đọc thẻ thật, hỏi luật cột, làm nốt việc của cột."""

    TASK = "TASK-2026-00906"
    ROOT = "TASK-2026-00900"

    class _Store:
        def __init__(self) -> None:
            self.logs: List[str] = []

        async def append_log(self, job_id: str, line: str) -> None:
            self.logs.append(line)

    def setUp(self) -> None:
        self.service = FlowWebService.__new__(FlowWebService)
        self.service.store = self._Store()
        self.moves: List[str] = []
        self.synced: List[str] = []
        self.listed = False

    @staticmethod
    def _node(name: str, status: str, *, meta: str = "", images=(), subtasks=()) -> Dict[str, Any]:
        return {
            "name": name,
            "subject": name,
            "status": status,
            "meta": meta,
            "comments": [
                {
                    "name": f"{name}-c{index}",
                    "mine": 1,
                    "is_bot": 1,
                    "content": "[FLOW_V2_REVIEW job#0] Ảnh chờ duyệt",
                    "attachments": [{"file_name": "a.png"}],
                    "like_count": like,
                    "dislike_count": dislike,
                    "replies": [],
                }
                for index, (like, dislike) in enumerate(images)
            ],
            "subtasks": list(subtasks),
            # ``taskFull`` trả cây hai lần và nhánh này cố ý mỏng, y như thật.
            "children": [{"name": item["name"], "subject": item["name"]} for item in subtasks],
        }

    def _run(self, tree: Dict[str, Any], *, trees: Dict[str, Any] | None = None) -> Dict[str, Any]:
        pool = dict(trees or {})
        pool.setdefault(str(tree["name"]), tree)

        def task_full(key: str, token: str, task_id: str, depth: int = 0) -> Dict[str, Any]:
            return {"root": pool[task_id]}

        async def sync(root_id: str) -> Dict[str, Any]:
            self.synced.append(root_id)
            return {"applied": 1}

        async def advance(job_id: str, task_id: str, status: str) -> bool:
            self.moves.append(status)
            return True

        with patch.object(self.service, "_erp_credentials", return_value=("key", "token")), \
                patch.object(self.service, "_erp_assert_task_in_project"), \
                patch.object(self.service, "_erp_task_full", side_effect=task_full), \
                patch.object(self.service, "_erp_listing_recorded", side_effect=lambda _t: self.listed), \
                patch.object(self.service, "sync_erp_skus", side_effect=sync), \
                patch.object(self.service, "_erp_advance_task_status", side_effect=advance):
            return asyncio.run(self.service.advance_erp_pipeline(self.TASK, job_id="job-1"))

    def test_a_reviewed_card_leaves_the_todo_column(self) -> None:
        outcome = self._run(self._node(self.TASK, "Open", images=[(1, 0), (0, 1)]))

        self.assertTrue(outcome["moved"])
        self.assertEqual(["Working"], self.moves)
        self.assertEqual("Đang làm", outcome["next_column"])

    def test_a_card_with_an_unvoted_image_stays_and_says_why(self) -> None:
        outcome = self._run(self._node(self.TASK, "Open", images=[(1, 0), (0, 0)]))

        self.assertFalse(outcome["moved"])
        self.assertEqual([], self.moves)
        self.assertIn("1 ảnh chờ", outcome["reason"])
        self.assertTrue(any("Cần làm" in line for line in self.service.store.logs))

    def test_the_doing_column_fills_the_code_in_before_deciding_again(self) -> None:
        # Cột *Đang làm* nghĩa là "máy đang điền mã"; thẻ không phải chờ tới
        # lượt quét sau mới được đi tiếp.
        # Ảnh đã chốt: điều kiện để thẻ có mặt ở cột này ngay từ đầu.
        before = self._node(self.TASK, "Working", images=[(1, 0)])
        after = self._node(self.TASK, "Working", meta="sku: HA_1_001\n", images=[(1, 0)])

        pool = {self.TASK: before}

        def task_full(key: str, token: str, task_id: str, depth: int = 0) -> Dict[str, Any]:
            node = pool[task_id]
            pool[task_id] = after  # lượt đọc lại, sau khi mã đã được điền
            return {"root": node}

        async def sync(root_id: str) -> Dict[str, Any]:
            self.synced.append(root_id)
            return {"applied": 1}

        async def advance(job_id: str, task_id: str, status: str) -> bool:
            self.moves.append(status)
            return True

        with patch.object(self.service, "_erp_credentials", return_value=("key", "token")), \
                patch.object(self.service, "_erp_assert_task_in_project"), \
                patch.object(self.service, "_erp_task_full", side_effect=task_full), \
                patch.object(self.service, "_erp_listing_recorded", return_value=False), \
                patch.object(self.service, "sync_erp_skus", side_effect=sync), \
                patch.object(self.service, "_erp_advance_task_status", side_effect=advance):
            outcome = asyncio.run(self.service.advance_erp_pipeline(self.TASK))

        self.assertEqual([self.TASK], self.synced)
        self.assertEqual(["Pending Review"], self.moves)
        self.assertTrue(outcome["sku"])

    def test_a_sibling_without_a_code_no_longer_holds_the_card_in_doing(self) -> None:
        # Luật cũ giữ thẻ lại tới khi *cả cụm* đủ mã. Với mô hình mã mới thì đó
        # là cái khoá không ai mở được: thẻ em còn nằm ở *Cần làm* sẽ không bao
        # giờ được cấp mã, nên thẻ anh sẽ đứng ở *Đang làm* vĩnh viễn. Giờ luật
        # chỉ hỏi mã của chính thẻ đang xét.
        child = self._node("TASK-2026-00907", "Open")
        root = self._node(
            self.TASK, "Working", meta="sku: HA_1_001\n", images=[(1, 0)], subtasks=[child]
        )

        outcome = self._run(root)

        # Không phải chạy lại đánh số: thẻ em ở *Cần làm* chưa tới lượt nhận mã,
        # nên máy không còn việc nào để làm trên cụm này.
        self.assertEqual([], self.synced)
        self.assertEqual(["Pending Review"], self.moves)
        self.assertTrue(outcome["moved"])
        self.assertIn("đã có mã SKU", outcome["reason"])

    def test_an_image_card_is_left_on_the_listing_writers_desk(self) -> None:
        outcome = self._run(self._node(self.TASK, "Pending Review", meta="sku: HA_1_001\n", images=[(1, 0)]))

        self.assertFalse(outcome["moved"])
        self.assertIn("người làm listing", outcome["reason"])

    def test_a_listing_card_closes_once_the_bot_recorded_the_post(self) -> None:
        self.listed = True
        node = self._node(
            self.TASK, "Pending Review", meta="action_1: listing\nsku: HA_1_001\n", images=[(1, 0)]
        )

        outcome = self._run(node)

        self.assertEqual(["Completed"], self.moves)
        self.assertTrue(outcome["moved"])

    def test_a_child_card_is_numbered_from_its_cluster_root(self) -> None:
        # Đánh số tính trên cả cây; đánh riêng một thẻ con là đánh trên cây một
        # nút và cái đuôi số sẽ đụng ngay thẻ khác.
        child = dict(self._node(self.TASK, "Working"), parent_task=self.ROOT)
        root = self._node(self.ROOT, "Working", meta="sku: HA_1_001\n", subtasks=[child])

        def detail(key: str, token: str, task_id: str) -> Dict[str, Any]:
            return {"name": task_id, "status": "Working", "meta": ""}

        with patch.object(self.service, "_erp_task_detail", side_effect=detail):
            outcome = self._run(child, trees={self.ROOT: root, self.TASK: child})

        self.assertEqual(self.ROOT, outcome["root_task_id"])
        self.assertEqual([self.ROOT], self.synced)

    def test_a_child_card_is_read_back_in_full_after_it_is_numbered(self) -> None:
        # ``taskFull`` trả cây hai lần và ``children`` chỉ có tên với tiêu đề.
        # Đọc lại thẻ con từ nhánh mỏng ấy thì nó trông như không có cột, không
        # có mã, không có ảnh — và thẻ sẽ đứng im ở *Đang làm* mãi mãi.
        child = dict(self._node(self.TASK, "Working", images=[(1, 0)]), parent_task=self.ROOT)
        numbered = dict(
            self._node(self.TASK, "Working", meta="sku: HA_1_002\n", images=[(1, 0)]),
            parent_task=self.ROOT,
        )
        before = self._node(self.ROOT, "Working", meta="sku: HA_1_001\n", subtasks=[child])
        after = self._node(self.ROOT, "Working", meta="sku: HA_1_001\n", subtasks=[numbered])
        pool = {self.TASK: child, self.ROOT: before}

        def task_full(key: str, token: str, task_id: str, depth: int = 0) -> Dict[str, Any]:
            node = pool[task_id]
            pool[self.ROOT] = after  # lượt đọc lại, sau khi cả cụm đã có mã
            return {"root": node}

        def detail(key: str, token: str, task_id: str) -> Dict[str, Any]:
            return {"name": task_id, "status": "Working", "meta": ""}

        async def sync(root_id: str) -> Dict[str, Any]:
            self.synced.append(root_id)
            return {"applied": 1}

        async def advance(job_id: str, task_id: str, status: str) -> bool:
            self.moves.append(status)
            return True

        with patch.object(self.service, "_erp_credentials", return_value=("key", "token")), \
                patch.object(self.service, "_erp_assert_task_in_project"), \
                patch.object(self.service, "_erp_task_full", side_effect=task_full), \
                patch.object(self.service, "_erp_task_detail", side_effect=detail), \
                patch.object(self.service, "_erp_listing_recorded", return_value=False), \
                patch.object(self.service, "sync_erp_skus", side_effect=sync), \
                patch.object(self.service, "_erp_advance_task_status", side_effect=advance):
            outcome = asyncio.run(self.service.advance_erp_pipeline(self.TASK))

        self.assertEqual("Working", outcome["status"])
        self.assertEqual(["Pending Review"], self.moves)

    def test_a_card_the_bot_may_not_touch_is_reported_not_raised(self) -> None:
        # Hàm này chạy nối đuôi một lượt tạo ảnh vừa xong; một cái bảng không
        # chịu đổi cột không được phép làm hỏng bộ ảnh vừa làm ra.
        with patch.object(self.service, "_erp_credentials", return_value=("key", "token")), \
                patch.object(
                    self.service,
                    "_erp_assert_task_in_project",
                    side_effect=RuntimeError("Thẻ không thuộc dự án được phép."),
                ):
            outcome = asyncio.run(self.service.advance_erp_pipeline(self.TASK, job_id="job-1"))

        self.assertFalse(outcome["moved"])
        self.assertIn("dự án", outcome["reason"])
        self.assertTrue(self.service.store.logs)

    def test_with_no_erp_key_nothing_is_attempted(self) -> None:
        with patch.object(self.service, "_erp_credentials", return_value=("", "")):
            outcome = asyncio.run(self.service.advance_erp_pipeline(self.TASK))

        self.assertFalse(outcome["moved"])
        self.assertIn("key", outcome["reason"])



if __name__ == "__main__":
    unittest.main()
