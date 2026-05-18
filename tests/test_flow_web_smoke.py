from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, UploadFile

from flow_web.messages import classify_job_error, humanize_flow_error
from flow_web.schemas import (
    AppConfig,
    AuthStatus,
    CreateJobRequest,
    IntegrationConfigUpdateRequest,
    JobArtifact,
    JobRecord,
    PromptBatchRequest,
    PromptCreateRequest,
    SkillRecord,
    StateSnapshot,
    StoryboardPlanRequest,
    TrelloConfigUpdateRequest,
)
from flow_web.service import FlowWebService
from flow_web.store import StateStore


class TempAppPathsMixin:
    def start_temp_paths(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self._tempdir.name)
        self.data_dir = self.temp_root / "data"
        self.uploads_dir = self.data_dir / "uploads"
        self.downloads_dir = self.data_dir / "downloads"
        self.state_file = self.data_dir / "state.json"

        def ensure_temp_dirs() -> None:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.uploads_dir.mkdir(parents=True, exist_ok=True)
            self.downloads_dir.mkdir(parents=True, exist_ok=True)

        self._patches = [
            patch("flow_web.paths.DATA_DIR", self.data_dir),
            patch("flow_web.paths.STATE_FILE", self.state_file),
            patch("flow_web.paths.UPLOADS_DIR", self.uploads_dir),
            patch("flow_web.paths.DOWNLOADS_DIR", self.downloads_dir),
            patch("flow_web.store.STATE_FILE", self.state_file),
            patch("flow_web.store.ensure_app_dirs", ensure_temp_dirs),
            patch("flow_web.service.UPLOADS_DIR", self.uploads_dir),
            patch("flow_web.service.DOWNLOADS_DIR", self.downloads_dir),
            patch("flow_web.service.ensure_app_dirs", ensure_temp_dirs),
        ]
        for patcher in self._patches:
            patcher.start()
        ensure_temp_dirs()
        self.addCleanup(self.stop_temp_paths)

    def stop_temp_paths(self) -> None:
        for patcher in reversed(getattr(self, "_patches", [])):
            patcher.stop()
        if hasattr(self, "_tempdir"):
            self._tempdir.cleanup()


class FlowWebServiceSyncTests(TempAppPathsMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.start_temp_paths()
        self.store = StateStore()
        self.service = FlowWebService(self.store)

    def test_save_upload_deduplicates_file_name(self) -> None:
        first = UploadFile(filename="demo.jpg", file=io.BytesIO(b"first"))
        second = UploadFile(filename="demo.jpg", file=io.BytesIO(b"second"))

        first_payload = asyncio.run(self.service.save_upload(first))
        second_payload = asyncio.run(self.service.save_upload(second))

        self.assertEqual("demo.jpg", first_payload["file_name"])
        self.assertEqual("demo-1.jpg", second_payload["file_name"])
        self.assertTrue((self.uploads_dir / "demo.jpg").exists())
        self.assertTrue((self.uploads_dir / "demo-1.jpg").exists())

    def test_validate_job_request_requires_authentication(self) -> None:
        request = CreateJobRequest(type="video", prompt="test prompt")
        with patch.object(self.service, "get_auth_status", return_value=AuthStatus(authenticated=False)):
            with self.assertRaises(HTTPException) as ctx:
                self.service._validate_job_request(request)

        self.assertEqual(400, ctx.exception.status_code)
        self.assertIn("đăng nhập", str(ctx.exception.detail).lower())

    def test_resolve_job_request_applies_config_defaults(self) -> None:
        config = AppConfig(
            project_id="pid",
            active_workflow_id="wf-default",
            generation_timeout_s=420,
        )
        request = CreateJobRequest(type="video", prompt="run", timeout_s=0, workflow_id="")

        resolved = self.service._resolve_job_request(request, config)

        self.assertEqual(420, resolved.timeout_s)
        self.assertEqual("wf-default", resolved.workflow_id)
        self.assertEqual("Veo 3.1 - Fast", resolved.model)
        self.assertEqual("landscape", resolved.aspect)

    def test_resolve_job_request_normalizes_image_model(self) -> None:
        config = AppConfig(project_id="pid", generation_timeout_s=420)
        request = CreateJobRequest(type="image", prompt="run", model="Nano Banana 2")

        resolved = self.service._resolve_job_request(request, config)

        self.assertEqual("NARWHAL", resolved.model)

    def test_flow_image_call_validation_requires_selected_source(self) -> None:
        good_call = SimpleNamespace(
            req={
                "requests": [
                    {
                        "clientContext": {"workflowId": "workflow-source"},
                        "imageInputs": [{"mediaName": "media-source"}],
                    }
                ]
            }
        )
        prompt_only_call = SimpleNamespace(req={"requests": [{"clientContext": {"workflowId": "fresh-workflow"}}]})

        self.assertTrue(self.service._flow_image_call_uses_selected_image(good_call, "media-source", "workflow-source"))
        self.assertFalse(self.service._flow_image_call_uses_selected_image(prompt_only_call, "media-source", "workflow-source"))

    def test_project_generated_images_extracts_new_flow_media(self) -> None:
        project_data = {
            "projectContents": {
                "workflows": [
                    {
                        "name": "wf-old",
                        "projectId": "pid",
                        "metadata": {"displayName": "Old prompt", "createTime": "2026-05-15T08:00:00Z"},
                        "medias": [
                            {
                                "name": "old-media",
                                "projectId": "pid",
                                "image": {"generatedImage": {"fifeUrl": "https://example.com/old.jpg"}},
                            }
                        ],
                    },
                    {
                        "name": "wf-video",
                        "projectId": "pid",
                        "metadata": {"displayName": "Video item", "createTime": "2026-05-15T08:02:00Z"},
                        "medias": [{"name": "video-media", "video": {"encodedVideo": {"url": "https://example.com/v.mp4"}}}],
                    },
                    {
                        "name": "wf-new",
                        "projectId": "pid",
                        "metadata": {"displayName": "New prompt", "createTime": "2026-05-15T08:01:00Z"},
                        "medias": [
                            {
                                "name": "new-media",
                                "projectId": "pid",
                                "dimensions": {"width": 1024, "height": 1024},
                                "image": {
                                    "generatedImage": {
                                        "fifeUrl": "https://example.com/new.jpg",
                                        "prompt": "Generated prompt",
                                        "seed": 7,
                                        "modelNameType": "NARWHAL",
                                    }
                                },
                            }
                        ],
                    },
                ]
            }
        }

        images = self.service._project_generated_images(project_data, known_media={"old-media"}, prompt="Fallback prompt")

        self.assertEqual(1, len(images))
        self.assertEqual("new-media", images[0].media_name)
        self.assertEqual("wf-new", images[0].workflow_id)
        self.assertEqual("https://example.com/new.jpg", images[0].fife_url)
        self.assertEqual("Generated prompt", images[0].prompt)
        self.assertEqual({"width": 1024, "height": 1024}, images[0].dimensions)

    def test_trello_archive_skips_without_credentials(self) -> None:
        request = CreateJobRequest(type="image", prompt="cat")
        artifact = JobArtifact(label="Ảnh 1", url="https://example.com/cat.jpg", mime_type="image/jpeg")
        job = JobRecord(type="image", status="running", title="test")
        asyncio.run(self.store.add_job(job))

        with patch.dict(os.environ, {"TRELLO_API_KEY": "", "TRELLO_TOKEN": ""}, clear=False):
            result = asyncio.run(self.service._archive_trello_artifacts(job.id, request, [artifact]))

        self.assertEqual({"configured": False}, result)

    def test_trello_archive_attaches_image_to_configured_card(self) -> None:
        request = CreateJobRequest(
            type="image",
            prompt="cat",
            trello_card_id="https://trello.com/c/abc123/demo-card",
        )
        artifact = JobArtifact(label="Ảnh 1", media_name="media", url="https://example.com/cat.jpg", mime_type="image/jpeg")
        job = JobRecord(type="image", status="running", title="test")
        asyncio.run(self.store.add_job(job))

        with patch.dict(
            os.environ,
            {
                "TRELLO_API_KEY": "key",
                "TRELLO_TOKEN": "token",
                "TRELLO_CARD_ID": "",
                "TRELLO_LIST_ID": "",
                "TRELLO_UPLOAD_MODE": "url",
            },
            clear=False,
        ), patch.object(
            self.service,
            "_trello_attach_url",
            return_value={"id": "att-1", "name": "flow-cat.jpg", "url": "https://trello.example/att-1"},
        ) as attach_url:
            result = asyncio.run(self.service._archive_trello_artifacts(job.id, request, [artifact]))

        attach_url.assert_called_once()
        self.assertEqual("abc123", attach_url.call_args.args[2])
        self.assertTrue(attach_url.call_args.args[5])
        self.assertTrue(result["configured"])
        self.assertEqual(1, result["sent"])
        self.assertEqual(0, result["failed"])
        self.assertEqual("abc123", result["card_id"])

    def test_trello_archive_upsamples_image_to_2k_before_file_upload(self) -> None:
        asyncio.run(
            self.service.update_trello_config(
                TrelloConfigUpdateRequest(
                    api_key="key",
                    token="token",
                    card_id="https://trello.com/c/abc123/demo-card",
                    upload_mode="file",
                    upscale_to_2k=True,
                )
            )
        )
        request = CreateJobRequest(type="image", prompt="cat")
        artifact = JobArtifact(label="Ảnh 1", media_name="media", url="https://example.com/cat.jpg", mime_type="image/jpeg")
        job = JobRecord(type="image", status="running", title="test")
        asyncio.run(self.store.add_job(job))

        with patch.dict(
            os.environ,
            {
                "TRELLO_API_KEY": "",
                "TRELLO_TOKEN": "",
                "TRELLO_CARD_ID": "",
                "TRELLO_LIST_ID": "",
                "TRELLO_UPLOAD_MODE": "file",
            },
            clear=False,
        ), patch.object(
            self.service,
            "_upsample_artifact_bytes",
            new=AsyncMock(return_value=(b"upscaled-jpeg-bytes", "image/jpeg")),
        ) as upsample, patch.object(
            self.service,
            "_trello_attach_file_bytes",
            return_value={"id": "att-1", "name": "flow-cat.jpg", "url": "https://trello.example/att-1"},
        ) as attach_bytes, patch.object(
            self.service,
            "_trello_attach_file_from_url",
        ) as attach_from_url:
            result = asyncio.run(self.service._archive_trello_artifacts(job.id, request, [artifact]))

        upsample.assert_awaited_once()
        attach_bytes.assert_called_once()
        attach_from_url.assert_not_called()
        # Positional args: key, token, card_id, file_bytes, mime, name, set_cover
        self.assertEqual(b"upscaled-jpeg-bytes", attach_bytes.call_args.args[3])
        self.assertEqual("image/jpeg", attach_bytes.call_args.args[4])
        self.assertEqual("abc123", attach_bytes.call_args.args[2])
        self.assertTrue(result["configured"])
        self.assertEqual(1, result["sent"])
        self.assertEqual(0, result["failed"])

    def test_trello_archive_skips_upsample_in_url_mode(self) -> None:
        asyncio.run(
            self.service.update_trello_config(
                TrelloConfigUpdateRequest(
                    api_key="key",
                    token="token",
                    card_id="https://trello.com/c/abc123/demo-card",
                    upload_mode="url",
                    upscale_to_2k=True,
                )
            )
        )
        request = CreateJobRequest(type="image", prompt="cat")
        artifact = JobArtifact(label="Ảnh 1", media_name="media", url="https://example.com/cat.jpg", mime_type="image/jpeg")
        job = JobRecord(type="image", status="running", title="test")
        asyncio.run(self.store.add_job(job))

        with patch.object(
            self.service,
            "_upsample_artifact_bytes",
            new=AsyncMock(return_value=(b"upscaled-jpeg-bytes", "image/jpeg")),
        ) as upsample, patch.object(
            self.service,
            "_trello_attach_url",
            return_value={"id": "att-1", "name": "flow-cat.jpg", "url": "https://trello.example/att-1"},
        ) as attach_url:
            result = asyncio.run(self.service._archive_trello_artifacts(job.id, request, [artifact]))

        # URL mode: respect the user's choice — no upsampling, no file upload.
        upsample.assert_not_called()
        attach_url.assert_called_once()
        self.assertTrue(result["configured"])
        self.assertEqual(1, result["sent"])

    def test_update_trello_config_saves_without_exposing_credentials(self) -> None:
        result = asyncio.run(
            self.service.update_trello_config(
                TrelloConfigUpdateRequest(
                    api_key="key",
                    token="token",
                    board_id="https://trello.com/b/board123/demo-board",
                    card_id="https://trello.com/c/abc123/demo-card",
                    upload_mode="url",
                )
            )
        )

        self.assertTrue(result["configured"])
        self.assertTrue(result["credentials_saved"])
        self.assertNotIn("api_key", result)
        self.assertNotIn("token", result)
        self.assertEqual("board123", result["board_id"])
        self.assertEqual("abc123", result["card_id"])
        self.assertEqual("url", result["upload_mode"])

        saved = self.store.snapshot().trello_config
        self.assertEqual("key", saved.api_key)
        self.assertEqual("token", saved.token)
        self.assertEqual("board123", saved.board_id)
        self.assertEqual("abc123", saved.card_id)

    def test_update_trello_config_persists_creds_to_env_local_file(self) -> None:
        env_file = self.temp_root / ".env.local"
        with patch("flow_web.service.ENV_FILE", env_file) if False else patch(
            "flow_web.main.ENV_FILE", env_file
        ), patch.dict(
            os.environ,
            {
                "TRELLO_API_KEY": "",
                "TRELLO_TOKEN": "",
                "TRELLO_BOARD_ID": "",
                "TRELLO_CARD_ID": "",
                "TRELLO_LIST_ID": "",
            },
            clear=False,
        ):
            result = asyncio.run(
                self.service.update_trello_config(
                    TrelloConfigUpdateRequest(
                        api_key="wizard-key",
                        token="wizard-token",
                        board_id="https://trello.com/b/wizardboard/demo",
                        persist_to_env=True,
                    )
                )
            )
            self.assertTrue(result["persisted_to_env"])
            self.assertTrue(env_file.exists())
            contents = env_file.read_text(encoding="utf-8")
            self.assertIn("TRELLO_API_KEY=wizard-key", contents)
            self.assertIn("TRELLO_TOKEN=wizard-token", contents)
            self.assertIn("TRELLO_BOARD_ID=wizardboard", contents)
            # Process env is also updated so the running app picks it up without restart.
            self.assertEqual("wizard-key", os.environ.get("TRELLO_API_KEY", ""))

    def test_update_trello_config_persist_preserves_unrelated_env_lines(self) -> None:
        env_file = self.temp_root / ".env.local"
        env_file.write_text(
            "\n".join(
                [
                    "# preexisting comment",
                    "OTHER_SECRET=keep-me",
                    "TRELLO_API_KEY=old-key",
                    "",
                    "GEMINI_API_KEY=gem-keep",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        with patch("flow_web.main.ENV_FILE", env_file), patch.dict(
            os.environ,
            {"TRELLO_API_KEY": "", "TRELLO_TOKEN": ""},
            clear=False,
        ):
            result = asyncio.run(
                self.service.update_trello_config(
                    TrelloConfigUpdateRequest(
                        api_key="new-key",
                        token="new-token",
                        board_id="https://trello.com/b/newboard/demo",
                        persist_to_env=True,
                    )
                )
            )

        self.assertTrue(result["persisted_to_env"])
        contents = env_file.read_text(encoding="utf-8")
        # Existing unrelated lines must be preserved verbatim.
        self.assertIn("# preexisting comment", contents)
        self.assertIn("OTHER_SECRET=keep-me", contents)
        self.assertIn("GEMINI_API_KEY=gem-keep", contents)
        # The previously stored TRELLO_API_KEY is overwritten in place,
        # not duplicated at the end of the file.
        self.assertNotIn("TRELLO_API_KEY=old-key", contents)
        self.assertEqual(contents.count("TRELLO_API_KEY="), 1)
        self.assertIn("TRELLO_API_KEY=new-key", contents)
        # New keys that weren't in the file before are appended cleanly.
        self.assertIn("TRELLO_TOKEN=new-token", contents)
        self.assertIn("TRELLO_BOARD_ID=newboard", contents)

    def test_trello_config_snapshot_falls_back_to_env_vars(self) -> None:
        # Chủ nhân setup 1 lần qua .env.local: state.json rỗng nhưng env vars
        # phải đủ để UI báo "Đã lưu" thay vì "Cần thiết lập".
        empty_snapshot = self.service._trello_config_snapshot(self.store.snapshot().trello_config)
        self.assertFalse(empty_snapshot["credentials_saved"])
        self.assertEqual("", empty_snapshot["credentials_source"])

        with patch.dict(
            os.environ,
            {
                "TRELLO_API_KEY": "env-key",
                "TRELLO_TOKEN": "env-token",
                "TRELLO_BOARD_ID": "https://trello.com/b/envboard/demo",
                "TRELLO_CARD_ID": "https://trello.com/c/envcard/demo",
                "TRELLO_LIST_ID": "envlist",
                "TRELLO_UPLOAD_MODE": "url",
            },
            clear=False,
        ):
            envonly = self.service._trello_config_snapshot(self.store.snapshot().trello_config)

        self.assertTrue(envonly["configured"])
        self.assertTrue(envonly["credentials_saved"])
        self.assertEqual("env", envonly["credentials_source"])
        self.assertEqual("envboard", envonly["board_id"])
        self.assertEqual("envcard", envonly["card_id"])
        self.assertEqual("envlist", envonly["list_id"])
        # upload_mode trong state.json mặc định "file" — env chỉ override khi
        # state thực sự để trống, khớp với logic trong _archive_trello_artifacts.
        self.assertIn(envonly["upload_mode"], {"file", "url"})
        # Snapshot không bao giờ leak api_key/token raw
        self.assertNotIn("api_key", envonly)
        self.assertNotIn("token", envonly)

    def test_trello_config_snapshot_prefers_state_over_env(self) -> None:
        asyncio.run(
            self.service.update_trello_config(
                TrelloConfigUpdateRequest(
                    api_key="state-key",
                    token="state-token",
                    board_id="https://trello.com/b/stateboard/demo",
                )
            )
        )
        with patch.dict(
            os.environ,
            {"TRELLO_API_KEY": "env-key", "TRELLO_TOKEN": "env-token"},
            clear=False,
        ):
            snap = self.service._trello_config_snapshot(self.store.snapshot().trello_config)

        # State vẫn ưu tiên trước env nên credentials_source = "state".
        self.assertEqual("state", snap["credentials_source"])
        self.assertTrue(snap["credentials_saved"])
        self.assertEqual("stateboard", snap["board_id"])

    def test_trello_archive_uses_app_saved_config(self) -> None:
        asyncio.run(
            self.service.update_trello_config(
                TrelloConfigUpdateRequest(
                    api_key="key",
                    token="token",
                    card_id="https://trello.com/c/abc123/demo-card",
                    upload_mode="url",
                )
            )
        )
        request = CreateJobRequest(type="image", prompt="cat")
        artifact = JobArtifact(label="Ảnh 1", media_name="media", url="https://example.com/cat.jpg", mime_type="image/jpeg")
        job = JobRecord(type="image", status="running", title="test")
        asyncio.run(self.store.add_job(job))

        with patch.dict(
            os.environ,
            {
                "TRELLO_API_KEY": "",
                "TRELLO_TOKEN": "",
                "TRELLO_CARD_ID": "",
                "TRELLO_LIST_ID": "",
                "TRELLO_UPLOAD_MODE": "file",
            },
            clear=False,
        ), patch.object(
            self.service,
            "_trello_attach_url",
            return_value={"id": "att-1", "name": "flow-cat.jpg", "url": "https://trello.example/att-1"},
        ) as attach_url:
            result = asyncio.run(self.service._archive_trello_artifacts(job.id, request, [artifact]))

        attach_url.assert_called_once()
        self.assertEqual("abc123", attach_url.call_args.args[2])
        self.assertEqual("https://example.com/cat.jpg", attach_url.call_args.args[3])
        self.assertTrue(result["configured"])
        self.assertEqual(1, result["sent"])

    def test_trello_resolve_board_list_id_defaults_to_ready_for_ai(self) -> None:
        lists = [
            {"id": "ideas-list", "name": "Ideas"},
            {"id": "ready-list", "name": "Ready for AI"},
        ]

        with patch.object(self.service, "_trello_board_lists", return_value=lists):
            self.assertEqual(
                "ready-list",
                self.service._trello_resolve_board_list_id("key", "token", "board123", ""),
            )
            self.assertEqual(
                "ideas-list",
                self.service._trello_resolve_board_list_id("key", "token", "board123", "Ideas"),
            )
            self.assertEqual(
                "ready-list",
                self.service._trello_resolve_board_list_id("key", "token", "board123", "ready-list"),
            )

    def test_trello_image_card_scan_requires_list_scope(self) -> None:
        with patch.object(self.service, "_trello_get_json") as get_json:
            cards = self.service._trello_image_cards_on_board("key", "token", "board123", "")

        self.assertEqual([], cards)
        get_json.assert_not_called()

    def test_trello_matching_hint_defaults_to_ready_list(self) -> None:
        request = CreateJobRequest(type="image", prompt="", trello_board_id="https://trello.com/b/board123/demo")
        items = [{"product_key": "shirt", "product": "Shirt", "prompt": "prompt"}]
        card = {"id": "ready-card", "name": "shirt", "shortLink": "ready", "url": "https://trello.com/c/ready", "idList": "ready-list"}

        with patch.object(self.service, "_trello_credentials", return_value=("key", "token")), patch.object(
            self.service,
            "_trello_board_lists",
            return_value=[
                {"id": "ideas-list", "name": "Ideas"},
                {"id": "ready-list", "name": "Ready for AI"},
            ],
        ), patch.object(
            self.service,
            "_trello_matching_image_card_on_board",
            return_value=card,
        ) as match_card, patch.object(
            self.service,
            "_trello_list_name",
            return_value="Ready for AI",
        ):
            hint = self.service._trello_matching_image_card_hint(request, items)

        match_card.assert_called_once_with("key", "token", "board123", items, "ready-list")
        self.assertEqual("ready-card", hint["card_id"])
        self.assertEqual("ready-list", hint["list_id"])
        self.assertEqual("Ready for AI", hint["list_name"])

    def test_update_integration_config_saves_without_exposing_credentials(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            result = asyncio.run(
                self.service.update_integration_config(
                    IntegrationConfigUpdateRequest(
                        gemini_api_key="gem-key",
                        gemini_model="gemini-2.5-flash",
                        telegram_bot_token="telegram-token",
                        telegram_chat_id="@review_channel",
                        playwright_browsers_path="/tmp/pw-browsers",
                    )
                )
            )

            self.assertTrue(result["gemini"]["configured"])
            self.assertTrue(result["telegram"]["configured"])
            self.assertTrue(result["runtime"]["playwright_browsers_path_set"])
            self.assertNotIn("gemini_api_key", result["gemini"])
            self.assertNotIn("telegram_bot_token", result["telegram"])
            self.assertEqual("gemini-2.5-flash", result["gemini"]["model"])
            self.assertEqual("@review_channel", result["telegram"]["chat_id"])
            self.assertEqual("/tmp/pw-browsers", os.environ.get("PLAYWRIGHT_BROWSERS_PATH"))

        saved = self.store.snapshot().integration_config
        self.assertEqual("gem-key", saved.gemini_api_key)
        self.assertEqual("telegram-token", saved.telegram_bot_token)
        self.assertEqual("/tmp/pw-browsers", saved.playwright_browsers_path)

    def test_prompt_assistant_uses_app_saved_gemini_settings(self) -> None:
        asyncio.run(
            self.service.update_integration_config(
                IntegrationConfigUpdateRequest(
                    gemini_api_key="gem-key",
                    gemini_model="gemini-2.5-pro",
                )
            )
        )

        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GEMINI_MODEL": ""}, clear=False):
            engine = self.service._prompt_ai_engine()

        self.assertTrue(engine["configured"])
        self.assertEqual("gemini", engine["engine"])
        self.assertEqual("gemini-2.5-pro", engine["model"])

    def test_telegram_review_pack_uses_app_saved_config(self) -> None:
        asyncio.run(
            self.service.update_integration_config(
                IntegrationConfigUpdateRequest(
                    telegram_bot_token="telegram-token",
                    telegram_chat_id="@review_channel",
                )
            )
        )
        request = CreateJobRequest(type="image", prompt="cat")
        artifact = JobArtifact(label="Ảnh 1", url="https://example.com/cat.jpg", mime_type="image/jpeg")
        job = JobRecord(type="image", status="running", title="test")
        asyncio.run(self.store.add_job(job))

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}, clear=False), patch.object(
            self.service,
            "_send_telegram_photo",
        ) as send_photo:
            result = asyncio.run(self.service._send_telegram_review_pack(job.id, request, [artifact]))

        send_photo.assert_called_once()
        self.assertEqual("telegram-token", send_photo.call_args.args[0])
        self.assertEqual("@review_channel", send_photo.call_args.args[1])
        reply_markup = send_photo.call_args.args[4]
        callback_values = [
            button["callback_data"]
            for row in reply_markup["inline_keyboard"]
            for button in row
        ]
        self.assertIn(f"fw:approve:{job.id}:0", callback_values)
        self.assertIn(f"fw:reject:{job.id}:0", callback_values)
        self.assertTrue(result["configured"])
        self.assertEqual(1, result["sent"])
        self.assertEqual(1, result["pending_approvals"])

    def test_sync_telegram_approvals_updates_job_and_approval_node(self) -> None:
        asyncio.run(
            self.service.update_integration_config(
                IntegrationConfigUpdateRequest(
                    telegram_bot_token="telegram-token",
                    telegram_chat_id="@review_channel",
                )
            )
        )
        job = JobRecord(
            type="image",
            status="completed",
            title="test",
            result={
                "automation_execution": {
                    "mode": "graph",
                    "nodes": [
                        {"id": "flow-1", "type": "flow", "status": "completed", "output": {}},
                        {"id": "approval-1", "type": "approval", "status": "running", "output": {}},
                    ],
                    "edges": [],
                    "current_module_id": "approval-1",
                    "completed": False,
                }
            },
            artifacts=[JobArtifact(label="Ảnh 1", url="https://example.com/cat.jpg", mime_type="image/jpeg")],
        )
        asyncio.run(self.store.add_job(job))
        updates = [
            {
                "update_id": 100,
                "callback_query": {
                    "id": "callback-1",
                    "from": {"id": 7, "first_name": "Ellyn", "username": "ellyn"},
                    "message": {"message_id": 42, "chat": {"id": -100}},
                    "data": f"fw:approve:{job.id}:0",
                },
            }
        ]

        with patch.object(self.service, "_telegram_get_updates", side_effect=[updates, []]) as get_updates, patch.object(
            self.service,
            "_telegram_answer_callback_query",
        ) as answer:
            result = asyncio.run(self.service.sync_telegram_approvals())

        self.assertTrue(result["configured"])
        self.assertEqual(1, result["processed"])
        get_updates.assert_any_call("telegram-token")
        get_updates.assert_any_call("telegram-token", 101)
        answer.assert_called_once()
        saved = self.store.get_job(job.id)
        self.assertEqual("approved", saved.result["telegram_approvals"]["0"]["status"])
        self.assertEqual(1, saved.result["telegram_approval_summary"]["approved"])
        approval_node = next(node for node in saved.result["automation_execution"]["nodes"] if node["type"] == "approval")
        self.assertEqual("completed", approval_node["status"])
        self.assertTrue(saved.result["automation_execution"]["completed"])

    def test_telegram_approval_sync_loop_polls_until_cancelled(self) -> None:
        calls = 0

        async def fake_sync() -> dict[str, object]:
            nonlocal calls
            calls += 1
            return {"configured": True, "processed": 0, "approvals": []}

        async def run_loop() -> None:
            task = asyncio.create_task(self.service.run_telegram_approval_sync_loop(interval_s=0.01))
            with patch.object(self.service, "sync_telegram_approvals", side_effect=fake_sync):
                while calls < 2:
                    await asyncio.sleep(0.02)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

        asyncio.run(run_loop())
        self.assertGreaterEqual(calls, 2)

    def test_prompt_source_preview_reads_pasted_google_sheet_rows(self) -> None:
        table = "\n".join(
            [
                "Product_Key\tProduct_Name\tPrompt_Index\tPrompt_Content\tActive\tNotes",
                "wedding_hoop\tWedding Hoop\t1\tinactive prompt\tFALSE\told",
                "hoops_with_photos\tHoops With Photos\t1\tThe product image showcases a personalized embroidery frame.\tTRUE\tNursery shelf decor",
            ]
        )

        result = asyncio.run(self.service.preview_prompt_source(text=table))

        self.assertEqual(2, result["prompt_count"])
        self.assertEqual(1, result["active_count"])
        self.assertIn("personalized embroidery frame", result["prompt"])
        self.assertEqual("Hoops With Photos", result["selected"]["product"])
        self.assertEqual(1, len(result["items"]))
        self.assertIn("personalized embroidery frame", result["items"][0]["prompt"])

    def test_prompt_source_preview_skips_rows_marked_used(self) -> None:
        table = "\n".join(
            [
                "Product_Key\tProduct_Name\tPrompt_Index\tPrompt_Content\tActive\tUsed\tNotes",
                "hoops_with_photos\tHoops With Photos\t1\told prompt should not run\tTRUE\tTRUE\talready done",
                "hoops_with_photos\tHoops With Photos\t2\tfresh prompt should run\tTRUE\tFALSE\tnew",
            ]
        )

        result = asyncio.run(self.service.preview_prompt_source(text=table))

        self.assertEqual(2, result["prompt_count"])
        self.assertEqual(1, result["used_count"])
        self.assertEqual(1, result["active_count"])
        self.assertEqual("fresh prompt should run", result["prompt"])
        self.assertEqual(3, result["selected"]["row"])
        self.assertEqual("fresh prompt should run", result["items"][0]["prompt"])

    def test_prompt_source_preview_reads_xlsx_upload(self) -> None:
        workbook = io.BytesIO()
        with zipfile.ZipFile(workbook, "w") as archive:
            archive.writestr(
                "xl/workbook.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                  <sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>
                </workbook>""",
            )
            archive.writestr(
                "xl/_rels/workbook.xml.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                  <Relationship Id="rId1" Target="worksheets/sheet1.xml"
                    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>
                </Relationships>""",
            )
            archive.writestr(
                "xl/worksheets/sheet1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                  <sheetData>
                    <row r="1">
                      <c r="A1" t="inlineStr"><is><t>Product_Key</t></is></c>
                      <c r="B1" t="inlineStr"><is><t>Prompt_Content</t></is></c>
                      <c r="C1" t="inlineStr"><is><t>Active</t></is></c>
                    </row>
                    <row r="2">
                      <c r="A2" t="inlineStr"><is><t>hoops_with_photos</t></is></c>
                      <c r="B2" t="inlineStr"><is><t>Flow should create the product photo from this prompt.</t></is></c>
                      <c r="C2" t="inlineStr"><is><t>TRUE</t></is></c>
                    </row>
                  </sheetData>
                </worksheet>""",
            )
        upload = UploadFile(filename="prompts.xlsx", file=io.BytesIO(workbook.getvalue()))

        result = asyncio.run(self.service.preview_prompt_source(file=upload))

        self.assertEqual(1, result["prompt_count"])
        self.assertEqual(1, result["active_count"])
        self.assertIn("product photo", result["prompt"])
        self.assertEqual("Flow should create the product photo from this prompt.", result["items"][0]["prompt"])

    def test_prompt_source_preview_reports_sheet_timeout_as_bad_request(self) -> None:
        with patch("flow_web.service.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(self.service.preview_prompt_source(source_url="https://docs.google.com/spreadsheets/d/sheet-id/edit?gid=0"))

        self.assertEqual(400, ctx.exception.status_code)
        self.assertIn("quá lâu", str(ctx.exception.detail))

    def test_get_auth_status_uses_network_cookies_fallback(self) -> None:
        with patch.object(self.service, "_flow_modules", return_value=(None, lambda: False, None, None, None)), patch.object(
            self.service,
            "_flow_profile_has_auth_cookies",
            return_value=True,
        ):
            status = self.service.get_auth_status()

        self.assertTrue(status.authenticated)

    def test_start_image_search_terms_include_file_stem(self) -> None:
        terms = self.service._start_image_search_terms(r"D:\flow\data\uploads\OIP-2.jfif")

        self.assertIn("D:\\flow\\data\\uploads\\OIP-2.jfif", terms)
        self.assertIn("OIP-2.jfif", terms)
        self.assertIn("OIP-2", terms)
        self.assertIn("oip 2", [item.lower() for item in terms])

    def test_resolve_job_request_assigns_reference_image_roles(self) -> None:
        config = AppConfig(project_id="pid", generation_timeout_s=420)
        request = CreateJobRequest(
            type="image",
            prompt="ghép logo lên áo",
            reference_image_paths=["/tmp/model.jpg", "/tmp/logo.png", "/tmp/tag.png"],
            reference_image_roles=["logo", "base", "reference"],
        )

        resolved = self.service._resolve_job_request(request, config)

        self.assertEqual(["logo", "base", "reference"], resolved.reference_image_roles)

    def test_ordered_reference_media_names_keeps_base_first(self) -> None:
        ordered = self.service._ordered_reference_media_names(
            [
                {"role": "logo", "media_name": "media-logo"},
                {"role": "base", "media_name": "media-model"},
                {"role": "product", "media_name": "media-shirt"},
            ]
        )

        self.assertEqual(["media-model", "media-shirt", "media-logo"], ordered)

    def test_canonical_project_url_uses_vi_locale_route(self) -> None:
        self.assertEqual(
            "https://labs.google/fx/vi/tools/flow/project/f2d33dc4-39f7-4f0e-8249-ce97a5c9a403",
            self.service._project_url("f2d33dc4-39f7-4f0e-8249-ce97a5c9a403"),
        )

    def test_detects_placeholder_project_route(self) -> None:
        self.assertTrue(
            self.service._looks_like_placeholder_project_url(
                "https://labs.google/fx/vi/tools/flow/project/[projectId]"
            )
        )
        self.assertTrue(
            self.service._looks_like_placeholder_project_url(
                "https://labs.google/fx/tools/flow/project/%5BprojectId%5D/edit/demo"
            )
        )
        self.assertFalse(
            self.service._looks_like_placeholder_project_url(
                "https://labs.google/fx/tools/flow/project/f2d33dc4-39f7-4f0e-8249-ce97a5c9a403"
            )
        )

    def test_video_status_url_supports_nested_generated_video_payload(self) -> None:
        status = SimpleNamespace(
            fife_url="",
            download_url="",
            url="",
            media_name="media-1",
            _raw={
                "media": [
                    {
                        "video": {
                            "generatedVideo": {
                                "outputVideo": {
                                    "fifeUrl": "https://example.com/fallback.mp4",
                                }
                            }
                        }
                    }
                ]
            },
        )

        url = self.service._video_status_url(status, media_name="media-1")

        self.assertEqual("https://example.com/fallback.mp4", url)

    def test_video_status_failure_detail_prefers_audio_failure_hint(self) -> None:
        status = SimpleNamespace(
            _raw={
                "media": [
                    {
                        "mediaMetadata": {
                            "mediaStatus": {
                                "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_FAILED",
                                "errorMessage": "Audio generation failed. Please try a different prompt or send feedback.",
                                "userFacingMessage": "You can update your settings to return silent videos.",
                            }
                        }
                    }
                ]
            }
        )

        detail = self.service._video_status_failure_detail(status)

        self.assertIn("Audio generation failed", detail)
        self.assertIn("silent videos", detail)

    def test_humanize_flow_error_maps_audio_generation_failure(self) -> None:
        message = humanize_flow_error(
            "Audio generation failed. Please try a different prompt or send feedback. "
            "You can update your settings to return silent videos."
        )

        self.assertIn("phần tạo audio bị lỗi", message)
        self.assertIn("video im lặng", message)

    def test_classify_job_error_maps_audio_generation_failure(self) -> None:
        snapshot = classify_job_error(
            "Audio generation failed. Please try a different prompt or send feedback. "
            "You can update your settings to return silent videos.",
            job_type="video",
        )

        self.assertEqual("audio", snapshot.category)
        self.assertEqual("Lỗi audio", snapshot.label)

    def test_policy_preflight_notice_warns_for_minor_fashion_edit(self) -> None:
        request = CreateJobRequest(
            type="image",
            prompt="ghép logo lên áo cho học sinh tuổi teen này và làm đẹp hơn",
            reference_image_paths=["/tmp/model.jpg"],
            reference_image_roles=["base"],
        )

        notice = self.service._policy_preflight_notice(request)

        self.assertIn("người chưa đủ tuổi", notice)
        self.assertIn("mannequin", notice)

    def test_policy_preflight_notice_warns_for_product_video_with_reference_images(self) -> None:
        request = CreateJobRequest(
            type="video",
            prompt="cho logo này lên áo và làm người mẫu đẹp hơn",
            reference_image_paths=["/tmp/shirt.png"],
            reference_image_roles=["product"],
        )

        notice = self.service._policy_preflight_notice(request)

        self.assertIn("ảnh tham chiếu", notice)
        self.assertIn("người mẫu trưởng thành", notice)

    def test_default_title_marks_video_from_image(self) -> None:
        request = CreateJobRequest(
            type="video",
            prompt="samurai",
            start_image_path="/tmp/source.jpg",
        )

        title = self.service._default_title(request)

        self.assertEqual("Tạo video từ ảnh", title)

    def test_default_title_marks_video_with_references_as_auto_video(self) -> None:
        request = CreateJobRequest(
            type="video",
            prompt="quảng cáo áo này",
            reference_image_paths=["/tmp/shirt.png"],
        )

        title = self.service._default_title(request)

        self.assertEqual("Tạo video từ ảnh tham chiếu", title)

    def test_default_title_marks_image_with_references_as_edit(self) -> None:
        request = CreateJobRequest(
            type="image",
            prompt="ghép logo lên áo",
            reference_image_paths=["/tmp/model.jpg", "/tmp/logo.png"],
        )

        title = self.service._default_title(request)

        self.assertEqual("Chỉnh ảnh từ ảnh tham chiếu", title)

    def test_video_start_frame_prompt_adds_model_and_product_guidance(self) -> None:
        request = CreateJobRequest(
            type="video",
            prompt="quảng cáo chiếc áo hoodie này theo phong cách cinematic",
            reference_image_paths=["/tmp/hoodie.png"],
            reference_image_roles=["product"],
            aspect="landscape",
        )

        prompt = self.service._video_start_frame_prompt(request)

        self.assertIn("photoreal human model", prompt.lower())
        self.assertIn("exact product design", prompt.lower())
        self.assertIn("start frame", prompt.lower())

    def test_prompt_assistant_snapshot_reports_gemini_when_key_exists(self) -> None:
        skills = [
            SkillRecord(
                name="google veo",
                summary="Video prompting for Veo.",
                source_path="guides/video/google-veo/SKILL.md",
                is_builtin=True,
            ),
            SkillRecord(
                name="prompt engineering",
                summary="General prompt writing.",
                source_path="guides/prompting/prompt-engineering/SKILL.md",
                is_builtin=True,
            ),
        ]
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "gemini-2.5-flash"}, clear=False):
            snapshot = self.service._prompt_assistant_snapshot(skills)

        self.assertTrue(snapshot["configured"])
        self.assertEqual("gemini", snapshot["engine"])
        self.assertEqual("Gemini", snapshot["engine_label"])
        self.assertEqual("gemini-2.5-flash", snapshot["model"])

    def test_compose_prompt_draft_adds_dense_detail_for_video(self) -> None:
        request = PromptCreateRequest(
            mode="video",
            brief="hai samurai đối đầu giữa sân đền cổ",
            style="cinematic dramatic",
            must_include="bụi bay, vải áo chuyển động",
            audience="quảng cáo mạng xã hội",
            aspect="landscape",
        )

        prompt = self.service._compose_prompt_draft(request, [])

        self.assertIn("layered foreground midground and background depth", prompt)
        self.assertIn("consistent subject identity across the full clip", prompt)
        self.assertIn("must include bụi bay, vải áo chuyển động", prompt)
        self.assertIn("optimized for quảng cáo mạng xã hội", prompt)
        self.assertGreater(len(prompt), 250)

    def test_gemini_prompt_request_uses_neutral_wording_and_detail_instructions(self) -> None:
        request = PromptCreateRequest(mode="image", brief="ảnh tai nghe màu đen trên nền trắng", aspect="landscape")

        payload = self.service._gemini_prompt_request(request, [], "baseline prompt")
        prompt_text = payload["contents"][0]["parts"][0]["text"]

        self.assertNotIn("chủ nhân", prompt_text.lower())
        self.assertIn("cực kỳ chi tiết", prompt_text)
        self.assertIn("production-ready", prompt_text)
        self.assertIn("Viết cùng ngôn ngữ với brief gốc của người dùng.", prompt_text)

    def test_ensure_prompt_detail_expands_short_prompt_with_baseline(self) -> None:
        short_prompt = "Video quảng cáo cho đồng hồ."
        baseline = (
            "Cinematic product hero shot, đồng hồ cơ màu đen trên nền đá tối, visual style cinematic luxury premium, "
            "lighting is warm golden hour lighting, mood is premium refined mood, wide 16:9 framing, hero product framing "
            "with a slow dolly-in, controlled parallax, and crisp focus transitions, clear subject action and environment "
            "relationship, layered foreground midground and background depth, cohesive color palette with believable contrast, "
            "consistent subject identity across the full clip, high texture fidelity and realistic material response."
        )

        expanded, changed = self.service._ensure_prompt_detail(short_prompt, baseline, "video")

        self.assertTrue(changed)
        self.assertIn("layered foreground midground and background depth", expanded)
        self.assertGreater(len(expanded), len(short_prompt))

    def test_storyboard_scene_count_prefers_explicit_request(self) -> None:
        count = self.service._storyboard_scene_count("Cảnh 1. Cảnh 2. Cảnh 3.", 6)

        self.assertEqual(6, count)

    def test_local_storyboard_plan_builds_scene_prompts(self) -> None:
        request = StoryboardPlanRequest(
            script=(
                "Cảnh 1: Một kiếm sĩ samurai đứng trong mưa trước cổng đền cổ.\n\n"
                "Cảnh 2: Anh ta rút kiếm và lao về phía đối thủ giữa sân đá.\n\n"
                "Cảnh 3: Hai người khóa kiếm, nước mưa bắn tung và đèn lồng rung mạnh."
            ),
            style="cinematic dramatic",
            must_include="mưa lớn, đèn lồng đỏ, giáp samurai",
            avoid="text, watermark",
            aspect="landscape",
        )

        scenes = self.service._local_storyboard_plan(request, 3, [])

        self.assertEqual(3, len(scenes))
        self.assertEqual(1, scenes[0].index)
        self.assertIn("storyboard keyframe", scenes[0].image_prompt.lower())
        self.assertIn("same subject identity", scenes[0].image_prompt.lower())
        self.assertIn("Giữ cùng nhân vật chính", scenes[0].continuity)
        self.assertIn("mưa lớn", scenes[0].continuity)

    def test_logout_flow_clears_local_profile_session(self) -> None:
        profile_dir = self.temp_root / "flow-profile"
        cookies_path = profile_dir / "Default" / "Cookies"
        cookies_path.parent.mkdir(parents=True, exist_ok=True)
        cookies_path.write_bytes(b"cookie-data")

        with patch("flow._storage.PROFILE_DIR", profile_dir), patch("flow._storage.ensure_dirs") as ensure_dirs:
            result = asyncio.run(self.service.logout_flow())

        self.assertTrue(result["ok"])
        self.assertTrue(result["had_session"])
        self.assertFalse(result["auth"]["authenticated"])
        self.assertFalse(cookies_path.exists())
        ensure_dirs.assert_called_once()

    def test_logout_flow_blocks_when_jobs_are_running(self) -> None:
        asyncio.run(self.store.add_job(JobRecord(type="video", status="running", title="Đang chạy")))

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(self.service.logout_flow())

        self.assertEqual(409, ctx.exception.status_code)
        self.assertIn("đang có tác vụ chạy", str(ctx.exception.detail).lower())


class StateStoreRegressionTests(TempAppPathsMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.start_temp_paths()

    def test_store_repairs_incomplete_jobs_after_restart(self) -> None:
        snapshot = StateSnapshot(
            config=AppConfig(project_id="pid"),
            jobs=[
                JobRecord(type="video", status="running", title="Dang chay"),
                JobRecord(type="image", status="polling", title="Dang doi"),
                JobRecord(type="video", status="completed", title="Xong"),
            ],
        )
        self.state_file.write_text(json.dumps(snapshot.model_dump(mode="json"), indent=2), encoding="utf-8")

        store = StateStore()
        jobs = store.snapshot().jobs

        self.assertEqual("interrupted", jobs[0].status)
        self.assertEqual("interrupted", jobs[1].status)
        self.assertEqual("completed", jobs[2].status)
        self.assertIn("khởi động lại", jobs[0].error.lower())


class FlowWebServiceAsyncTests(TempAppPathsMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.start_temp_paths()
        self.store = StateStore()
        self.service = FlowWebService(self.store)

    async def test_plan_storyboard_returns_local_scenes_when_gemini_is_not_configured(self) -> None:
        with patch.object(self.service, "ensure_media_skill_library", AsyncMock(return_value={})), patch.object(
            self.service,
            "_gemini_api_key",
            return_value="",
        ):
            payload = await self.service.plan_storyboard(
                StoryboardPlanRequest(
                    script=(
                        "Mở đầu là cảnh một cô gái đứng trước cửa hàng nhạc cụ vào buổi tối.\n\n"
                        "Sau đó cô bước vào trong, chạm tay vào cây đàn piano đen bóng dưới ánh đèn ấm.\n\n"
                        "Cuối cùng cô ngồi xuống chơi một đoạn ngắn, căn phòng phản chiếu ánh sáng vàng."
                    ),
                    style="cinematic luxury",
                    must_include="đàn piano đen, ánh sáng vàng",
                    aspect="landscape",
                    scene_count=3,
                )
            )

        self.assertEqual("local", payload["engine"])
        self.assertEqual(3, payload["scene_count"])
        self.assertEqual(3, len(payload["items"]))
        self.assertIn("storyboard", payload["items"][0]["image_prompt"].lower())
        self.assertIn("cảnh", payload["items"][0]["continuity"].lower())

    async def test_prepare_video_start_image_from_references_downloads_intermediate_frame(self) -> None:
        job = JobRecord(type="video", status="running", title="test")
        await self.store.add_job(job)
        request = CreateJobRequest(
            type="video",
            prompt="quảng cáo chiếc áo này với người mẫu",
            reference_image_paths=["/tmp/shirt.png"],
            reference_image_roles=["product"],
            aspect="landscape",
            timeout_s=300,
        )
        generated_image = SimpleNamespace(fife_url="https://example.com/frame.jpg")
        client = SimpleNamespace(download=AsyncMock(return_value=str(self.uploads_dir / "job-start.jpg")))

        with patch.object(
            self.service,
            "_resolve_image_reference_media",
            AsyncMock(return_value=["media-shirt"]),
        ) as resolve_media, patch.object(
            self.service,
            "_generate_images_with_retry",
            AsyncMock(return_value=[generated_image]),
        ) as generate_images, patch.object(
            self.service,
            "_set_job_progress",
            AsyncMock(),
        ), patch.object(
            self.service.store,
            "append_log",
            AsyncMock(),
        ):
            local_path, prompt = await self.service._prepare_video_start_image_from_references(client, job.id, request)

        resolve_media.assert_awaited_once()
        generate_images.assert_awaited_once()
        client.download.assert_awaited_once()
        self.assertTrue(local_path.endswith("job-start.jpg"))
        self.assertIn("photoreal human model", prompt.lower())
        saved_job = self.store.get_job(job.id)
        self.assertIsNotNone(saved_job)
        self.assertEqual(local_path, saved_job.result.get("auto_start_frame_path"))
        self.assertEqual("/files/uploads/job-start.jpg", saved_job.result.get("auto_start_frame_public_url"))
        self.assertEqual(prompt, saved_job.result.get("auto_start_frame_prompt"))

    async def test_wait_for_new_project_images_polls_project_data(self) -> None:
        empty_project = {"projectContents": {"workflows": []}}
        ready_project = {
            "projectContents": {
                "workflows": [
                    {
                        "name": "wf-new",
                        "projectId": "pid",
                        "metadata": {"displayName": "Prompt title", "createTime": "2026-05-15T08:01:00Z"},
                        "medias": [
                            {
                                "name": "media-new",
                                "projectId": "pid",
                                "image": {"generatedImage": {"fifeUrl": "https://example.com/new.jpg"}},
                            }
                        ],
                    }
                ]
            }
        }
        client = SimpleNamespace(
            _api=SimpleNamespace(get_project_data=AsyncMock(side_effect=[empty_project, ready_project]))
        )

        images = await self.service._wait_for_new_project_images(
            client,
            {"media-old"},
            prompt="Prompt fallback",
            target_count=1,
            timeout_s=5,
        )

        self.assertEqual(1, len(images))
        self.assertEqual("media-new", images[0].media_name)
        self.assertEqual("https://example.com/new.jpg", images[0].fife_url)
        self.assertEqual(2, client._api.get_project_data.await_count)

    async def test_with_client_keeps_shared_flow_browser_open_in_visible_mode(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", headless=False, generation_timeout_s=300))
        fake_browser = SimpleNamespace()
        fake_client = SimpleNamespace(name="shared-client")

        with patch.object(
            self.service,
            "_ensure_shared_browser",
            AsyncMock(return_value=fake_browser),
        ) as ensure_shared_browser, patch.object(
            self.service,
            "_build_client_from_shared_browser",
            AsyncMock(return_value=fake_client),
        ) as build_client, patch.object(
            self.service,
            "_close_shared_browser",
            AsyncMock(),
        ) as close_shared_browser:
            result = await self.service._with_client(lambda client: asyncio.sleep(0, result=client.name))

        self.assertEqual("shared-client", result)
        ensure_shared_browser.assert_awaited_once()
        build_client.assert_awaited_once()
        close_shared_browser.assert_not_called()

    async def test_open_login_flow_page_opens_new_tab_and_brings_it_to_front(self) -> None:
        page = SimpleNamespace(
            bring_to_front=AsyncMock(),
            goto=AsyncMock(),
            evaluate=AsyncMock(return_value=True),
        )
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        browser = SimpleNamespace(context=context, _page=None, page=AsyncMock(return_value=page))

        with patch.object(
            self.service,
            "_foreground_native_flow_window",
            AsyncMock(),
        ) as foreground_native_window:
            result = await self.service._open_login_flow_page(browser)

        self.assertIs(result, page)
        context.new_page.assert_awaited_once()
        page.bring_to_front.assert_awaited()
        page.goto.assert_awaited()
        self.assertEqual(
            "https://labs.google/fx/vi/tools/flow",
            page.goto.await_args.args[0],
        )
        page.evaluate.assert_awaited()
        foreground_native_window.assert_awaited_once()

    async def test_enqueue_login_fails_immediately_when_browser_cannot_open(self) -> None:
        with patch.object(
            self.service,
            "_launch_login_browser",
            AsyncMock(side_effect=RuntimeError("Khong mo duoc cua so Chromium")),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await self.service.enqueue_login()

        self.assertEqual(500, ctx.exception.status_code)
        self.assertIn("khong mo duoc cua so chromium", str(ctx.exception.detail).lower())
        jobs = self.store.snapshot().jobs
        self.assertEqual(1, len(jobs))
        self.assertEqual("failed", jobs[0].status)

    async def test_open_flow_login_surface_uses_login_page(self) -> None:
        page = SimpleNamespace(url="https://labs.google/fx/vi/tools/flow")
        browser = SimpleNamespace()

        with patch.object(self.service, "_ensure_shared_browser", AsyncMock(return_value=browser)) as ensure_browser, patch.object(
            self.service,
            "_open_login_flow_page",
            AsyncMock(return_value=page),
        ) as open_login_page:
            payload = await self.service.open_flow_login_surface()

        ensure_browser.assert_awaited_once()
        open_login_page.assert_awaited_once_with(browser)
        self.assertTrue(payload["ok"])
        self.assertEqual("https://labs.google/fx/vi/tools/flow", payload["url"])

    async def test_open_flow_login_surface_fails_in_windows_session_zero(self) -> None:
        with patch("flow_web.service.os.name", "nt"), patch.object(
            self.service,
            "_current_windows_session_id",
            return_value=0,
        ), patch.object(self.service, "_ensure_shared_browser", AsyncMock()) as ensure_browser:
            with self.assertRaises(HTTPException) as ctx:
                await self.service.open_flow_login_surface()

        ensure_browser.assert_not_awaited()
        self.assertEqual(400, ctx.exception.status_code)
        self.assertIn("session nền của windows", str(ctx.exception.detail).lower())

    async def test_open_flow_project_surface_opens_saved_project_page(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid-demo"))
        page = SimpleNamespace(url="https://labs.google/fx/vi/tools/flow/project/pid-demo", bring_to_front=AsyncMock())
        browser = SimpleNamespace()

        with patch.object(self.service, "_ensure_shared_browser", AsyncMock(return_value=browser)) as ensure_browser, patch.object(
            self.service,
            "_repair_placeholder_flow_tabs",
            AsyncMock(),
        ) as repair_tabs, patch.object(
            self.service,
            "_acquire_fresh_flow_page",
            AsyncMock(return_value=page),
        ) as acquire_page, patch.object(
            self.service,
            "_ensure_valid_flow_project_page",
            AsyncMock(),
        ) as ensure_project, patch.object(
            self.service,
            "_foreground_native_flow_window",
            AsyncMock(),
        ) as focus_window:
            payload = await self.service.open_flow_project_surface()

        ensure_browser.assert_awaited_once()
        repair_tabs.assert_awaited_once()
        acquire_page.assert_awaited_once()
        ensure_project.assert_awaited_once()
        page.bring_to_front.assert_awaited_once()
        focus_window.assert_awaited_once()
        self.assertTrue(payload["ok"])
        self.assertEqual("https://labs.google/fx/vi/tools/flow/project/pid-demo", payload["url"])

    async def test_open_flow_project_surface_fails_in_windows_session_zero(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid-demo"))
        with patch("flow_web.service.os.name", "nt"), patch.object(
            self.service,
            "_current_windows_session_id",
            return_value=0,
        ), patch.object(self.service, "_ensure_shared_browser", AsyncMock()) as ensure_browser:
            with self.assertRaises(HTTPException) as ctx:
                await self.service.open_flow_project_surface()

        ensure_browser.assert_not_awaited()
        self.assertEqual(400, ctx.exception.status_code)
        self.assertIn("session nền của windows", str(ctx.exception.detail).lower())

    async def test_launch_login_browser_fails_in_windows_session_zero(self) -> None:
        job = JobRecord(type="login", status="queued", title="Đăng nhập Google Flow")
        await self.store.add_job(job)

        with patch("flow_web.service.os.name", "nt"), patch.object(
            self.service,
            "_current_windows_session_id",
            return_value=0,
        ), patch.object(self.service, "_ensure_shared_browser", AsyncMock()) as ensure_browser:
            with self.assertRaises(HTTPException) as ctx:
                await self.service._launch_login_browser(job.id)

        ensure_browser.assert_not_awaited()
        self.assertEqual(400, ctx.exception.status_code)
        self.assertIn("session nền của windows", str(ctx.exception.detail).lower())

    async def test_ensure_valid_flow_project_page_redirects_placeholder_route(self) -> None:
        page = SimpleNamespace(
            url="https://labs.google/fx/vi/tools/flow/project/[projectId]",
            goto=AsyncMock(),
        )

        await self.service._ensure_valid_flow_project_page(
            page,
            "https://labs.google/fx/tools/flow/project/f2d33dc4-39f7-4f0e-8249-ce97a5c9a403",
        )

        page.goto.assert_awaited()
        args = page.goto.await_args.args
        self.assertEqual(
            "https://labs.google/fx/tools/flow/project/f2d33dc4-39f7-4f0e-8249-ce97a5c9a403",
            args[0],
        )

    async def test_repair_placeholder_flow_tabs_redirects_all_stale_tabs(self) -> None:
        stale_page = SimpleNamespace(
            url="https://labs.google/fx/vi/tools/flow/project/[projectId]",
            goto=AsyncMock(),
        )
        good_page = SimpleNamespace(
            url="https://labs.google/fx/tools/flow/project/f2d33dc4-39f7-4f0e-8249-ce97a5c9a403",
            goto=AsyncMock(),
        )
        browser = SimpleNamespace(
            context=SimpleNamespace(
                pages=[stale_page, good_page],
            )
        )

        await self.service._repair_placeholder_flow_tabs(
            browser,
            "https://labs.google/fx/tools/flow/project/f2d33dc4-39f7-4f0e-8249-ce97a5c9a403",
        )

        stale_page.goto.assert_awaited()
        good_page.goto.assert_not_awaited()

    async def test_close_placeholder_flow_tabs_closes_stale_tabs_and_keeps_valid_page(self) -> None:
        stale_page = SimpleNamespace(
            url="https://labs.google/fx/vi/tools/flow/project/[projectId]",
            close=AsyncMock(),
        )
        good_page = SimpleNamespace(
            url="https://labs.google/fx/tools/flow/project/f2d33dc4-39f7-4f0e-8249-ce97a5c9a403",
            close=AsyncMock(),
        )
        browser = SimpleNamespace(
            context=SimpleNamespace(
                pages=[stale_page, good_page],
            ),
            _page=None,
        )

        await self.service._close_placeholder_flow_tabs(
            browser,
            "https://labs.google/fx/tools/flow/project/f2d33dc4-39f7-4f0e-8249-ce97a5c9a403",
        )

        stale_page.close.assert_awaited_once()
        good_page.close.assert_not_awaited()

    async def test_close_placeholder_flow_tabs_opens_fresh_page_when_only_stale_tab_exists(self) -> None:
        stale_page = SimpleNamespace(
            url="https://labs.google/fx/vi/tools/flow/project/[projectId]",
            close=AsyncMock(),
        )
        fresh_page = SimpleNamespace(
            url="about:blank",
            goto=AsyncMock(),
        )
        context = SimpleNamespace(
            pages=[stale_page],
            new_page=AsyncMock(return_value=fresh_page),
        )
        browser = SimpleNamespace(
            context=context,
            _page=None,
        )

        async def pages_after_close() -> list[object]:
            return [fresh_page]

        stale_page.close.side_effect = lambda: context.pages.clear()

        await self.service._close_placeholder_flow_tabs(
            browser,
            "https://labs.google/fx/tools/flow/project/f2d33dc4-39f7-4f0e-8249-ce97a5c9a403",
        )

        stale_page.close.assert_awaited_once()
        context.new_page.assert_awaited_once()
        fresh_page.goto.assert_awaited()

    async def test_acquire_fresh_flow_page_prefers_matching_project_tab(self) -> None:
        matching_page = SimpleNamespace(
            url="https://labs.google/fx/tools/flow/project/f2d33dc4-39f7-4f0e-8249-ce97a5c9a403",
        )
        other_page = SimpleNamespace(
            url="https://labs.google/fx/tools/flow",
        )
        context = SimpleNamespace(
            pages=[other_page, matching_page],
            new_page=AsyncMock(),
        )
        browser = SimpleNamespace(context=context, _page=None)

        page = await self.service._acquire_fresh_flow_page(
            browser,
            "https://labs.google/fx/tools/flow/project/f2d33dc4-39f7-4f0e-8249-ce97a5c9a403",
        )

        self.assertIs(page, matching_page)
        context.new_page.assert_not_awaited()

    async def test_acquire_fresh_flow_page_creates_new_tab_when_no_matching_tab_exists(self) -> None:
        old_page = SimpleNamespace(url="https://labs.google/fx/tools/flow")
        fresh_page = SimpleNamespace(url="about:blank")
        context = SimpleNamespace(
            pages=[old_page],
            new_page=AsyncMock(return_value=fresh_page),
        )
        browser = SimpleNamespace(context=context, _page=None, page=AsyncMock(return_value=old_page))

        page = await self.service._acquire_fresh_flow_page(
            browser,
            "https://labs.google/fx/tools/flow/project/f2d33dc4-39f7-4f0e-8249-ce97a5c9a403",
        )

        self.assertIs(page, fresh_page)
        context.new_page.assert_awaited_once()

    async def test_run_flow_job_saves_video_artifact_from_nested_status_url(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        request = CreateJobRequest(type="video", prompt="samurai fight", count=1)
        job = JobRecord(
            type="video",
            status="queued",
            title=self.service._default_title(request),
            input=request.model_dump(mode="json"),
        )
        await self.store.add_job(job)

        video_job = SimpleNamespace(media_name="media-123", workflow_id="wf-123")
        status = SimpleNamespace(
            fife_url="",
            download_url="",
            url="",
            media_name="media-123",
            _raw={
                "media": [
                    {
                        "video": {
                            "generatedVideo": {
                                "outputVideo": {
                                    "fifeUrl": "https://example.com/video.mp4",
                                }
                            }
                        }
                    }
                ]
            },
        )
        fake_client = SimpleNamespace(generate_video=AsyncMock(return_value=[video_job]))

        async def fake_with_client(fn, workflow_id="", timeout_s=0):
            return await fn(fake_client)

        with patch.object(self.service, "_with_client", side_effect=fake_with_client), patch.object(
            self.service,
            "_wait_for_video_with_progress",
            AsyncMock(return_value=status),
        ):
            await self.service._run_flow_job(job.id, request)

        fake_client.generate_video.assert_awaited_once()
        self.assertEqual("Veo 3.1 - Fast", fake_client.generate_video.await_args.kwargs["model"])
        saved = self.store.get_job(job.id)
        self.assertIsNotNone(saved)
        self.assertEqual("completed", saved.status)
        self.assertEqual(1, len(saved.artifacts))
        self.assertEqual("https://example.com/video.mp4", saved.artifacts[0].url)
        self.assertEqual("video/mp4", saved.artifacts[0].mime_type)

    async def test_enqueue_job_logs_policy_preflight_notice(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        request = CreateJobRequest(
            type="image",
            prompt="ghép logo lên áo cho học sinh tuổi teen này và làm đẹp hơn",
            reference_image_paths=["/tmp/model.jpg"],
            reference_image_roles=["base"],
        )

        started = asyncio.Event()

        async def fake_run_flow_job(*args, **kwargs):
            started.set()
            await asyncio.sleep(60)

        with patch.object(self.service, "_run_flow_job", side_effect=fake_run_flow_job):
            job = await self.service.enqueue_job(request)

        saved = self.store.get_job(job.id)
        self.assertIsNotNone(saved)
        self.assertTrue(any("Cảnh báo an toàn" in log.message for log in saved.logs))
        task = self.service._tasks.get(job.id)
        self.assertIsNotNone(task)
        await started.wait()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def test_run_flow_job_fails_when_video_submit_returns_too_few_jobs(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        request = CreateJobRequest(type="video", prompt="cat", count=2)
        job = JobRecord(
            type="video",
            status="queued",
            title=self.service._default_title(request),
            input=request.model_dump(mode="json"),
        )
        await self.store.add_job(job)

        only_one_job = SimpleNamespace(media_name="media-123", workflow_id="wf-123")
        fake_client = SimpleNamespace(generate_video=AsyncMock(return_value=[only_one_job]))

        async def fake_with_client(fn, workflow_id="", timeout_s=0):
            return await fn(fake_client)

        with patch.object(self.service, "_with_client", side_effect=fake_with_client):
            await self.service._run_flow_job(job.id, request)

        saved = self.store.get_job(job.id)
        self.assertIsNotNone(saved)
        self.assertEqual("failed", saved.status)
        self.assertIn("1/2 clip", saved.error)

    async def test_run_flow_job_marks_send_stage_timeout_clearly(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        request = CreateJobRequest(type="video", prompt="samurai fight", count=1, start_image_path="/tmp/demo.jpg")
        job = JobRecord(
            type="video",
            status="queued",
            title=self.service._default_title(request),
            input=request.model_dump(mode="json"),
        )
        await self.store.add_job(job)

        async def fake_generate_video(*args, **kwargs):
            await asyncio.sleep(0)
            return []

        fake_client = SimpleNamespace(generate_video=fake_generate_video)

        async def fake_with_client(fn, workflow_id="", timeout_s=0):
            return await fn(fake_client)

        async def fake_wait_for(awaitable, timeout=None):
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            raise asyncio.TimeoutError

        with patch.object(self.service, "_with_client", side_effect=fake_with_client), patch(
            "flow_web.service.asyncio.wait_for",
            AsyncMock(side_effect=fake_wait_for),
        ):
            await self.service._run_flow_job(job.id, request)

        saved = self.store.get_job(job.id)
        self.assertIsNotNone(saved)
        self.assertEqual("failed", saved.status)
        self.assertIn("chưa gửi được yêu cầu tạo video", saved.error.lower())

    async def test_run_flow_job_retries_audio_failure_with_no_audio_model(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        request = CreateJobRequest(type="video", prompt="cat cinematic", count=1, model="Veo 3.1 - Fast")
        job = JobRecord(
            type="video",
            status="queued",
            title=self.service._default_title(request),
            input=request.model_dump(mode="json"),
        )
        await self.store.add_job(job)

        video_job = SimpleNamespace(media_name="media-123", workflow_id="wf-123")
        success_status = SimpleNamespace(
            fife_url="",
            download_url="",
            url="",
            media_name="media-123",
            _raw={
                "media": [
                    {
                        "video": {
                            "generatedVideo": {
                                "outputVideo": {
                                    "fifeUrl": "https://example.com/video.mp4",
                                }
                            }
                        }
                    }
                ]
            },
        )
        fake_client = SimpleNamespace(generate_video=AsyncMock(return_value=[video_job]))

        async def fake_with_client(fn, workflow_id="", timeout_s=0):
            return await fn(fake_client)

        with patch.object(self.service, "_with_client", side_effect=fake_with_client), patch.object(
            self.service,
            "_wait_for_video_with_progress",
            AsyncMock(
                side_effect=[
                    RuntimeError(
                        "Audio generation failed. Please try a different prompt or send feedback. "
                        "You can update your settings to return silent videos."
                    ),
                    success_status,
                ]
            ),
        ):
            await self.service._run_flow_job(job.id, request)

        self.assertEqual(2, fake_client.generate_video.await_count)
        first_call = fake_client.generate_video.await_args_list[0]
        second_call = fake_client.generate_video.await_args_list[1]
        self.assertEqual("Veo 3.1 - Fast", first_call.kwargs["model"])
        self.assertEqual("Veo 2 - Fast", second_call.kwargs["model"])

        saved = self.store.get_job(job.id)
        self.assertIsNotNone(saved)
        self.assertEqual("completed", saved.status)
        self.assertEqual("Veo 2 - Fast", saved.result.get("model"))
        self.assertEqual("Veo 3.1 - Fast", saved.result.get("fallback_from_model"))

    async def test_wait_for_video_with_progress_surfaces_audio_failure_detail(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        job = JobRecord(type="video", status="queued", title="test audio fail")
        await self.store.add_job(job)

        status = SimpleNamespace(
            status="MEDIA_GENERATION_STATUS_FAILED",
            complete=False,
            failed=True,
            media_name="media-123",
            _raw={
                "media": [
                    {
                        "mediaMetadata": {
                            "mediaStatus": {
                                "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_FAILED",
                                "errorMessage": "Audio generation failed. Please try a different prompt or send feedback.",
                                "userFacingMessage": "You can update your settings to return silent videos.",
                            }
                        }
                    }
                ]
            },
        )
        client = SimpleNamespace(poll_video=AsyncMock(return_value=status))
        video_job = SimpleNamespace(media_name="media-123")

        with self.assertRaises(RuntimeError) as ctx:
            await self.service._wait_for_video_with_progress(
                client,
                job.id,
                video_job,
                "Video 1",
                poll_s=0.01,
                timeout_s=30,
            )

        self.assertIn("phần tạo audio bị lỗi", str(ctx.exception))

    async def test_run_flow_job_uploads_reference_images_for_image_edit(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        reference_a = self.uploads_dir / "model.jpg"
        reference_b = self.uploads_dir / "logo.png"
        reference_a.write_bytes(b"model")
        reference_b.write_bytes(b"logo")

        request = CreateJobRequest(
            type="image",
            prompt="ghép logo này lên áo của người mẫu",
            count=1,
            reference_image_paths=[str(reference_a), str(reference_b)],
        )
        job = JobRecord(
            type="image",
            status="queued",
            title=self.service._default_title(request),
            input=request.model_dump(mode="json"),
        )
        await self.store.add_job(job)

        fake_image = SimpleNamespace(
            media_name="img-123",
            workflow_id="wf-123",
            fife_url="https://example.com/result.jpg",
            prompt=request.prompt,
            dimensions={"width": 1280, "height": 720},
        )
        captured_body = {}

        async def fake_fetch(method: str, url: str, body: dict):
            captured_body["method"] = method
            captured_body["url"] = url
            captured_body["body"] = body
            return {
                "media": [
                    {
                        "name": fake_image.media_name,
                        "workflowId": fake_image.workflow_id,
                        "image": {"generatedImage": {"fifeUrl": fake_image.fife_url}},
                    }
                ]
            }

        fake_client = SimpleNamespace(
            _api=SimpleNamespace(
                project_id="pid",
                _client_context=AsyncMock(
                    return_value={
                        "projectId": "pid",
                        "tool": "PINHOLE",
                        "sessionId": ";123",
                        "recaptchaContext": {"token": "abc", "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB"},
                    }
                ),
                get_project_data=AsyncMock(
                    return_value={
                        "projectContents": {
                            "workflows": [
                                {"name": "wf-base", "metadata": {"primaryMediaId": "ref-model"}},
                                {"name": "wf-ref", "metadata": {"primaryMediaId": "ref-logo"}},
                            ]
                        }
                    }
                ),
                _fetch=AsyncMock(side_effect=fake_fetch),
                generate_image=AsyncMock(side_effect=AssertionError("Legacy reference_images payload should not be used")),
            ),
            generate_image=AsyncMock(return_value=[fake_image]),
        )

        async def fake_with_client(fn, workflow_id="", timeout_s=0):
            return await fn(fake_client)

        with patch.object(self.service, "_with_client", side_effect=fake_with_client), patch.object(
            self.service,
            "_upload_project_image_robust",
            AsyncMock(side_effect=["ref-model", "ref-logo"]),
        ) as upload_project_image:
            await self.service._run_flow_job(job.id, request)

        upload_project_image.assert_any_await(fake_client, str(reference_a.resolve()))
        upload_project_image.assert_any_await(fake_client, str(reference_b.resolve()))
        fake_client._api._fetch.assert_awaited_once()
        self.assertEqual("POST", captured_body["method"])
        self.assertEqual("projects/pid/flowMedia:batchGenerateImages", captured_body["url"])
        request_body = captured_body["body"]["requests"][0]
        self.assertEqual("wf-base", request_body["clientContext"]["workflowId"])
        self.assertEqual(
            [
                {"imageInputType": "IMAGE_INPUT_TYPE_BASE_IMAGE", "name": "ref-model"},
                {"imageInputType": "IMAGE_INPUT_TYPE_REFERENCE", "name": "ref-logo"},
            ],
            request_body["imageInputs"],
        )

        saved = self.store.get_job(job.id)
        self.assertIsNotNone(saved)
        self.assertEqual("completed", saved.status)
        self.assertEqual(1, len(saved.artifacts))
        self.assertEqual("https://example.com/result.jpg", saved.artifacts[0].url)

    async def test_generate_image_edit_result_uses_first_image_as_base_and_rest_as_reference(self) -> None:
        captured_body = {}

        async def fake_fetch(method: str, url: str, body: dict):
            captured_body["method"] = method
            captured_body["url"] = url
            captured_body["body"] = body
            return {
                "media": [
                    {
                        "name": "img-1",
                        "workflowId": "wf-base",
                        "image": {"generatedImage": {"fifeUrl": "https://example.com/edited.jpg"}},
                    },
                    {
                        "name": "img-2",
                        "workflowId": "wf-base",
                        "image": {"generatedImage": {"fifeUrl": "https://example.com/edited-2.jpg"}},
                    },
                ]
            }

        fake_client = SimpleNamespace(
            _api=SimpleNamespace(
                project_id="pid",
                _client_context=AsyncMock(
                    return_value={
                        "projectId": "pid",
                        "tool": "PINHOLE",
                        "sessionId": ";123",
                        "recaptchaContext": {"token": "abc", "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB"},
                    }
                ),
                _fetch=AsyncMock(side_effect=fake_fetch),
                get_project_data=AsyncMock(
                    return_value={
                        "projectContents": {
                            "workflows": [
                                {"name": "wf-base", "metadata": {"primaryMediaId": "base-media"}},
                                {"name": "wf-ref", "metadata": {"primaryMediaId": "logo-media"}},
                            ]
                        }
                    }
                ),
            )
        )

        images = await self.service._generate_image_edit_result(
            fake_client,
            "ghép logo lên áo",
            model="IMAGEN_3",
            aspect="portrait",
            count=2,
            reference_media_names=["base-media", "logo-media"],
        )

        self.assertEqual(2, len(images))
        self.assertEqual("POST", captured_body["method"])
        self.assertEqual("projects/pid/flowMedia:batchGenerateImages", captured_body["url"])
        self.assertEqual(2, len(captured_body["body"]["requests"]))
        for request_payload in captured_body["body"]["requests"]:
            self.assertEqual("IMAGEN_3", request_payload["imageModelName"])
            self.assertEqual("IMAGE_ASPECT_RATIO_PORTRAIT", request_payload["imageAspectRatio"])
            self.assertEqual("wf-base", request_payload["clientContext"]["workflowId"])
            self.assertEqual(
                [
                    {"imageInputType": "IMAGE_INPUT_TYPE_BASE_IMAGE", "name": "base-media"},
                    {"imageInputType": "IMAGE_INPUT_TYPE_REFERENCE", "name": "logo-media"},
                ],
                request_payload["imageInputs"],
            )

    async def test_run_flow_job_uses_direct_image_api_for_exact_count(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        request = CreateJobRequest(type="image", prompt="meo de thuong", count=2, aspect="square", model="IMAGEN_3")
        job = JobRecord(
            type="image",
            status="queued",
            title=self.service._default_title(request),
            input=request.model_dump(mode="json"),
        )
        await self.store.add_job(job)

        fake_images = [
            SimpleNamespace(
                media_name="img-1",
                workflow_id="wf-1",
                fife_url="https://example.com/img-1.jpg",
                prompt=request.prompt,
                dimensions={"width": 1024, "height": 1024},
            ),
            SimpleNamespace(
                media_name="img-2",
                workflow_id="wf-1",
                fife_url="https://example.com/img-2.jpg",
                prompt=request.prompt,
                dimensions={"width": 1024, "height": 1024},
            ),
        ]
        fake_client = SimpleNamespace(
            _api=SimpleNamespace(generate_image=AsyncMock(return_value=fake_images)),
            generate_image=AsyncMock(side_effect=AssertionError("UI image generation should not be used")),
        )

        async def fake_with_client(fn, workflow_id="", timeout_s=0):
            return await fn(fake_client)

        with patch.object(self.service, "_with_client", side_effect=fake_with_client):
            await self.service._run_flow_job(job.id, request)

        fake_client._api.generate_image.assert_awaited_once()
        kwargs = fake_client._api.generate_image.await_args.kwargs
        self.assertEqual(2, kwargs["count"])
        self.assertEqual("IMAGEN_3", kwargs["model"])
        self.assertEqual("IMAGE_ASPECT_RATIO_SQUARE", kwargs["aspect_ratio"])

        saved = self.store.get_job(job.id)
        self.assertIsNotNone(saved)
        self.assertEqual("completed", saved.status)
        self.assertEqual(2, len(saved.artifacts))

    async def test_run_flow_job_records_make_style_automation_modules(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        request = CreateJobRequest(
            type="image",
            prompt="cat",
            count=1,
            automation_graph={
                "modules": [
                    {"id": "source-1", "type": "source", "title": "Prompt Source", "settings": {"sourceType": "sheets"}},
                    {"id": "normalize-1", "type": "normalize", "title": "Normalize Prompt"},
                    {"id": "flow-1", "type": "flow", "title": "Google Flow"},
                    {"id": "trello-1", "type": "trello", "title": "Trello Archive", "settings": {"trelloCard": "card-1"}},
                    {"id": "telegram-1", "type": "telegram", "title": "Telegram Review", "settings": {"telegramChat": "chat-1"}},
                    {"id": "approval-1", "type": "approval", "title": "Approval"},
                ]
            },
        )
        job = JobRecord(
            type="image",
            status="queued",
            title=self.service._default_title(request),
            input=request.model_dump(mode="json"),
        )
        await self.store.add_job(job)

        fake_images = [
            SimpleNamespace(
                media_name="img-1",
                workflow_id="wf-1",
                fife_url="https://example.com/img-1.jpg",
                prompt=request.prompt,
                dimensions={"width": 1024, "height": 1024},
            )
        ]
        calls: list[str] = []

        async def fake_with_client(fn, workflow_id="", timeout_s=0):
            return await fn(SimpleNamespace())

        async def fake_archive(job_id, module_request, artifacts):
            calls.append("trello")
            return {"configured": True, "sent": len(artifacts), "card_id": module_request.trello_card_id}

        async def fake_telegram(job_id, module_request, artifacts):
            calls.append("telegram")
            return {"configured": True, "sent": len(artifacts), "chat_id": module_request.telegram_chat_id}

        with patch.object(self.service, "_with_client", side_effect=fake_with_client), patch.object(
            self.service,
            "_generate_images_with_retry",
            AsyncMock(return_value=fake_images),
        ), patch.object(
            self.service,
            "_archive_trello_artifacts",
            side_effect=fake_archive,
        ), patch.object(
            self.service,
            "_send_telegram_review_pack",
            side_effect=fake_telegram,
        ):
            await self.service._run_flow_job(job.id, request)

        saved = self.store.get_job(job.id)
        self.assertIsNotNone(saved)
        self.assertEqual("completed", saved.status)
        self.assertEqual(["trello", "telegram"], calls)
        execution = saved.result["automation_execution"]
        self.assertEqual("graph", execution["mode"])
        self.assertFalse(execution["completed"])
        self.assertEqual(
            ["source", "normalize", "flow", "trello", "telegram", "approval"],
            [node["type"] for node in execution["nodes"]],
        )
        self.assertTrue(all(node["status"] == "completed" for node in execution["nodes"] if node["type"] != "approval"))
        approval_node = next(node for node in execution["nodes"] if node["type"] == "approval")
        self.assertEqual("running", approval_node["status"])
        self.assertTrue(approval_node["output"]["awaiting_user_approval"])
        flow_node = next(node for node in execution["nodes"] if node["type"] == "flow")
        self.assertEqual(1, flow_node["output"]["artifact_count"])
        telegram_node = next(node for node in execution["nodes"] if node["type"] == "telegram")
        self.assertEqual("chat-1", telegram_node["output"]["chat_id"])
        trello_node = next(node for node in execution["nodes"] if node["type"] == "trello")
        self.assertEqual("card-1", trello_node["output"]["card_id"])

    async def test_trello_source_feeds_flow_and_resume_archives_to_same_card(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        source_image = self.uploads_dir / "trello-source.jpg"
        source_image.write_bytes(b"source-image")
        request = CreateJobRequest(
            type="image",
            prompt="turn the Trello product photo into an Etsy lifestyle image",
            count=1,
            telegram_enabled=True,
            trello_enabled=True,
            automation_graph={
                "modules": [
                    {"id": "source-1", "type": "source", "title": "Prompt Source"},
                    {
                        "id": "trello-source-1",
                        "type": "trello_source",
                        "title": "Trello Image Source",
                        "settings": {
                            "trelloCard": "https://trello.com/c/abc123/product-card",
                            "trelloAttachmentLimit": 2,
                        },
                    },
                    {"id": "flow-1", "type": "flow", "title": "Google Flow"},
                    {"id": "telegram-1", "type": "telegram", "title": "Telegram Review"},
                    {"id": "approval-1", "type": "approval", "title": "Approval"},
                    {"id": "trello-1", "type": "trello", "title": "Trello Archive"},
                ]
            },
        )
        job = JobRecord(
            type="image",
            status="queued",
            title=self.service._default_title(request),
            input=request.model_dump(mode="json"),
        )
        await self.store.add_job(job)

        fake_image = SimpleNamespace(
            media_name="img-1",
            workflow_id="wf-1",
            fife_url="https://example.com/generated.jpg",
            prompt=request.prompt,
            dimensions={"width": 1024, "height": 1024},
        )
        captured: dict[str, object] = {}

        async def fake_with_client(fn, workflow_id="", timeout_s=0):
            return await fn(SimpleNamespace())

        async def fake_generate_images(client, job_id, module_request, reference_media_names):
            captured["request"] = module_request
            captured["reference_media_names"] = list(reference_media_names)
            return [fake_image]

        async def fake_telegram(job_id, module_request, artifacts):
            return {"configured": True, "sent": len(artifacts), "chat_id": module_request.telegram_chat_id}

        with patch.object(self.service, "_with_client", side_effect=fake_with_client), patch.object(
            self.service,
            "_trello_credentials",
            return_value=("key", "token"),
        ), patch.object(
            self.service,
            "_download_trello_card_image_attachments",
            return_value=[str(source_image)],
        ), patch.object(
            self.service,
            "_resolve_image_reference_media",
            AsyncMock(return_value=["trello-media"]),
        ), patch.object(
            self.service,
            "_generate_images_with_retry",
            side_effect=fake_generate_images,
        ), patch.object(
            self.service,
            "_send_telegram_review_pack",
            side_effect=fake_telegram,
        ):
            await self.service._run_flow_job(job.id, request)

        generated_request = captured["request"]
        self.assertEqual("abc123", generated_request.trello_card_id)
        self.assertEqual([str(source_image)], generated_request.reference_image_paths)
        self.assertEqual(["base"], generated_request.reference_image_roles)
        self.assertEqual(["trello-media"], captured["reference_media_names"])

        saved = self.store.get_job(job.id)
        self.assertIsNotNone(saved)
        self.assertEqual("abc123", saved.input["trello_card_id"])
        execution = saved.result["automation_execution"]
        trello_source_node = next(node for node in execution["nodes"] if node["id"] == "trello-source-1")
        self.assertEqual("completed", trello_source_node["status"])
        self.assertEqual(1, trello_source_node["output"]["reference_image_count"])
        approval_node = next(node for node in execution["nodes"] if node["id"] == "approval-1")
        self.assertEqual("running", approval_node["status"])
        trello_node = next(node for node in execution["nodes"] if node["id"] == "trello-1")
        self.assertEqual("pending", trello_node["status"])

        updated_result = dict(saved.result)
        updated_result["telegram_approvals"] = {"0": {"status": "approved"}}
        await self.store.patch_job(job.id, result=updated_result)
        archive_cards: list[str] = []

        async def fake_archive(job_id, module_request, artifacts):
            archive_cards.append(module_request.trello_card_id)
            return {"configured": True, "sent": len(artifacts), "card_id": module_request.trello_card_id}

        with patch.object(self.service, "_archive_trello_artifacts", side_effect=fake_archive):
            await self.service._resume_automation_after_approval(job.id, "approval-1")

        self.assertEqual(["abc123"], archive_cards)
        resumed = self.store.get_job(job.id)
        resumed_trello_node = next(node for node in resumed.result["automation_execution"]["nodes"] if node["id"] == "trello-1")
        self.assertEqual("completed", resumed_trello_node["status"])
        self.assertEqual("abc123", resumed_trello_node["output"]["card_id"])

    async def test_trello_source_resolves_board_link_to_image_card(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        source_image = self.uploads_dir / "trello-board-source.jpg"
        source_image.write_bytes(b"source-image")
        request = CreateJobRequest(
            type="image",
            prompt="make a product image from the Trello board card",
            count=1,
            telegram_enabled=False,
            trello_enabled=True,
            automation_graph={
                "modules": [
                    {
                        "id": "trello-source-1",
                        "type": "trello_source",
                        "title": "Trello Image Source",
                        "settings": {
                            "trelloBoard": "https://trello.com/b/board123/demo-board",
                            "trelloList": "list-1",
                        },
                    },
                    {"id": "flow-1", "type": "flow", "title": "Google Flow"},
                    {"id": "trello-1", "type": "trello", "title": "Trello Archive"},
                ]
            },
        )
        job = JobRecord(
            type="image",
            status="queued",
            title=self.service._default_title(request),
            input=request.model_dump(mode="json"),
        )
        await self.store.add_job(job)
        fake_image = SimpleNamespace(
            media_name="img-1",
            workflow_id="wf-1",
            fife_url="https://example.com/generated.jpg",
            prompt=request.prompt,
            dimensions={"width": 1024, "height": 1024},
        )
        captured: dict[str, object] = {}

        async def fake_with_client(fn, workflow_id="", timeout_s=0):
            return await fn(SimpleNamespace())

        async def fake_generate_images(client, job_id, module_request, reference_media_names):
            captured["request"] = module_request
            return [fake_image]

        async def fake_archive(job_id, module_request, artifacts):
            captured["archive_card"] = module_request.trello_card_id
            return {"configured": True, "sent": len(artifacts), "card_id": module_request.trello_card_id}

        with patch.object(self.service, "_with_client", side_effect=fake_with_client), patch.object(
            self.service,
            "_trello_credentials",
            return_value=("key", "token"),
        ), patch.object(
            self.service,
            "_trello_resolve_board_list_id",
            return_value="list-1",
        ), patch.object(
            self.service,
            "_trello_first_image_card_id_on_board",
            return_value="card-from-board",
        ) as find_card, patch.object(
            self.service,
            "_download_trello_card_image_attachments",
            return_value=[str(source_image)],
        ) as download_images, patch.object(
            self.service,
            "_resolve_image_reference_media",
            AsyncMock(return_value=["trello-media"]),
        ), patch.object(
            self.service,
            "_generate_images_with_retry",
            side_effect=fake_generate_images,
        ), patch.object(
            self.service,
            "_archive_trello_artifacts",
            side_effect=fake_archive,
        ):
            await self.service._run_flow_job(job.id, request)

        find_card.assert_called_once_with("key", "token", "board123", "list-1")
        download_images.assert_called_once()
        self.assertEqual("card-from-board", download_images.call_args.args[2])
        generated_request = captured["request"]
        self.assertEqual("board123", generated_request.trello_board_id)
        self.assertEqual("card-from-board", generated_request.trello_card_id)
        self.assertEqual("card-from-board", captured["archive_card"])
        saved = self.store.get_job(job.id)
        self.assertEqual("card-from-board", saved.input["trello_card_id"])
        trello_source_node = next(node for node in saved.result["automation_execution"]["nodes"] if node["id"] == "trello-source-1")
        self.assertEqual("board123", trello_source_node["output"]["board_id"])
        self.assertEqual("card-from-board", trello_source_node["output"]["card_id"])

    async def test_approval_module_pauses_and_resumes_downstream_modules(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        request = CreateJobRequest(
            type="image",
            prompt="cat",
            count=1,
            telegram_enabled=True,
            trello_enabled=True,
            automation_graph={
                "modules": [
                    {"id": "source-1", "type": "source", "title": "Prompt Source"},
                    {"id": "flow-1", "type": "flow", "title": "Google Flow"},
                    {"id": "telegram-1", "type": "telegram", "title": "Telegram Review", "settings": {"telegramChat": "chat-1"}},
                    {"id": "approval-1", "type": "approval", "title": "Approval"},
                    {"id": "trello-1", "type": "trello", "title": "Trello Archive", "settings": {"trelloCard": "card-1"}},
                ]
            },
        )
        job = JobRecord(
            type="image",
            status="queued",
            title=self.service._default_title(request),
            input=request.model_dump(mode="json"),
        )
        await self.store.add_job(job)

        fake_images = [
            SimpleNamespace(
                media_name="img-1",
                workflow_id="wf-1",
                fife_url="https://example.com/img-1.jpg",
                prompt=request.prompt,
                dimensions={"width": 1024, "height": 1024},
            )
        ]
        calls: list[str] = []

        async def fake_with_client(fn, workflow_id="", timeout_s=0):
            return await fn(SimpleNamespace())

        async def fake_archive(job_id, module_request, artifacts):
            calls.append("trello")
            return {"configured": True, "sent": len(artifacts), "card_id": module_request.trello_card_id}

        async def fake_telegram(job_id, module_request, artifacts):
            calls.append("telegram")
            return {"configured": True, "sent": len(artifacts), "chat_id": module_request.telegram_chat_id}

        with patch.object(self.service, "_with_client", side_effect=fake_with_client), patch.object(
            self.service,
            "_generate_images_with_retry",
            AsyncMock(return_value=fake_images),
        ), patch.object(
            self.service,
            "_archive_trello_artifacts",
            side_effect=fake_archive,
        ), patch.object(
            self.service,
            "_send_telegram_review_pack",
            side_effect=fake_telegram,
        ):
            await self.service._run_flow_job(job.id, request)

            saved = self.store.get_job(job.id)
            self.assertIsNotNone(saved)
            self.assertEqual(["telegram"], calls)
            execution = saved.result["automation_execution"]
            approval_node = next(node for node in execution["nodes"] if node["id"] == "approval-1")
            trello_node = next(node for node in execution["nodes"] if node["id"] == "trello-1")
            self.assertEqual("running", approval_node["status"])
            self.assertEqual("pending", trello_node["status"])
            self.assertFalse(execution["completed"])

            await self.service._apply_telegram_approval(
                job.id,
                0,
                "approved",
                {
                    "id": "callback-1",
                    "from": {"first_name": "Reviewer"},
                    "message": {"message_id": 42, "chat": {"id": "chat-1"}},
                },
            )

        saved = self.store.get_job(job.id)
        self.assertIsNotNone(saved)
        self.assertEqual(["telegram", "trello"], calls)
        execution = saved.result["automation_execution"]
        approval_node = next(node for node in execution["nodes"] if node["id"] == "approval-1")
        trello_node = next(node for node in execution["nodes"] if node["id"] == "trello-1")
        self.assertEqual("completed", approval_node["status"])
        self.assertEqual("completed", trello_node["status"])
        self.assertTrue(execution["completed"])
        self.assertEqual(1, saved.result["telegram_approval_summary"]["approved"])
        self.assertEqual("card-1", saved.result["trello"]["card_id"])

    async def test_late_telegram_reaction_does_not_flip_completed_approval(self) -> None:
        request = CreateJobRequest(
            type="image",
            prompt="cat",
            count=1,
            telegram_enabled=True,
            trello_enabled=True,
            automation_graph={
                "modules": [
                    {"id": "source-1", "type": "source", "title": "Prompt Source"},
                    {"id": "flow-1", "type": "flow", "title": "Google Flow"},
                    {"id": "telegram-1", "type": "telegram", "title": "Telegram Review"},
                    {"id": "approval-1", "type": "approval", "title": "Approval"},
                    {"id": "trello-1", "type": "trello", "title": "Trello Archive"},
                ]
            },
        )
        job = JobRecord(
            type="image",
            status="completed",
            title="approved job",
            input=request.model_dump(mode="json"),
            result={
                "telegram_approvals": {"0": {"artifact_index": 0, "status": "approved"}},
                "telegram_approval_summary": {
                    "total": 1,
                    "approved": 1,
                    "rejected": 0,
                    "pending": 0,
                    "resolved": 1,
                    "status": "completed",
                },
                "trello": {"configured": True, "sent": 1, "failed": 0, "card_id": "card-1"},
                "automation_execution": {
                    "mode": "graph",
                    "nodes": [
                        {"id": "approval-1", "type": "approval", "status": "completed", "output": {}},
                        {"id": "trello-1", "type": "trello", "status": "completed", "output": {"sent": 1}},
                    ],
                    "edges": [],
                    "current_module_id": "",
                    "completed": True,
                },
            },
            artifacts=[JobArtifact(label="Ảnh 1", url="https://example.com/img.jpg", mime_type="image/jpeg")],
        )
        await self.store.add_job(job)

        with patch.object(self.service, "_archive_trello_artifacts", AsyncMock()) as archive:
            approval = await self.service._apply_telegram_approval(
                job.id,
                0,
                "rejected",
                {"id": "late-callback", "from": {"first_name": "Reviewer"}},
            )

        saved = self.store.get_job(job.id)
        self.assertEqual("approved", approval["status"])
        self.assertEqual("approved", saved.result["telegram_approvals"]["0"]["status"])
        self.assertEqual(1, saved.result["telegram_approval_summary"]["approved"])
        self.assertEqual(0, saved.result["telegram_approval_summary"]["rejected"])
        self.assertEqual("completed", saved.result["automation_execution"]["nodes"][1]["status"])
        self.assertEqual(1, saved.result["trello"]["sent"])
        archive.assert_not_called()
        self.assertIn("Bỏ qua phản hồi Telegram", saved.logs[-1].message)

    async def test_custom_module_runs_user_configured_webhook(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        request = CreateJobRequest(
            type="image",
            prompt="custom prompt",
            title="Webhook demo",
            count=1,
            automation_graph={
                "modules": [
                    {"id": "source-1", "type": "source", "title": "Prompt Source"},
                    {"id": "flow-1", "type": "flow", "title": "Google Flow"},
                    {
                        "id": "custom-1",
                        "type": "custom",
                        "title": "Webhook Custom",
                        "settings": {
                            "customWebhookUrl": "https://hooks.example/run?api_key=secret&job={{job_id}}",
                            "customWebhookMethod": "POST",
                            "customWebhookHeaders": "X-Flow-Job: {{job_id}}\nAuthorization: Bearer demo",
                            "customWebhookBody": '{"id":"{{job_id}}","prompt":"{{prompt}}","url":"{{first_artifact_url}}","artifacts":{{artifacts}}}',
                        },
                    },
                ]
            },
        )
        job = JobRecord(
            type="image",
            status="queued",
            title=self.service._default_title(request),
            input=request.model_dump(mode="json"),
        )
        await self.store.add_job(job)
        fake_images = [
            SimpleNamespace(
                media_name="img-1",
                workflow_id="wf-1",
                fife_url="https://example.com/img-1.jpg",
                prompt=request.prompt,
                dimensions={"width": 1024, "height": 1024},
            )
        ]
        captured: dict[str, object] = {}

        async def fake_with_client(fn, workflow_id="", timeout_s=0):
            return await fn(SimpleNamespace())

        def fake_webhook(method, url, headers, body, timeout_s):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = headers
            captured["body"] = body
            captured["timeout_s"] = timeout_s
            return {"status_code": 200, "body": {"ok": True}}

        with patch.object(self.service, "_with_client", side_effect=fake_with_client), patch.object(
            self.service,
            "_generate_images_with_retry",
            AsyncMock(return_value=fake_images),
        ), patch.object(
            self.service,
            "_custom_webhook_request",
            side_effect=fake_webhook,
        ):
            await self.service._run_flow_job(job.id, request)

        saved = self.store.get_job(job.id)
        self.assertIsNotNone(saved)
        self.assertEqual("completed", saved.status)
        self.assertEqual("POST", captured["method"])
        self.assertIn(f"job={job.id}", captured["url"])
        self.assertEqual(job.id, captured["headers"]["X-Flow-Job"])
        body_payload = json.loads(captured["body"].decode("utf-8"))
        self.assertEqual(job.id, body_payload["id"])
        self.assertEqual("custom prompt", body_payload["prompt"])
        self.assertEqual("https://example.com/img-1.jpg", body_payload["url"])
        self.assertEqual("img-1", body_payload["artifacts"][0]["media_name"])
        custom_result = saved.result["custom_modules"]["custom-1"]
        self.assertTrue(custom_result["configured"])
        self.assertEqual(200, custom_result["status_code"])
        self.assertIn("api_key=***", custom_result["url"])
        custom_node = next(node for node in saved.result["automation_execution"]["nodes"] if node["id"] == "custom-1")
        self.assertEqual("completed", custom_node["status"])

    async def test_prompt_batch_runs_active_sheet_prompts_sequentially(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        request = PromptBatchRequest(
            job=CreateJobRequest(
                type="image",
                prompt="",
                count=1,
                telegram_enabled=True,
                telegram_chat_id="1234567890",
                automation_graph={
                    "modules": [
                        {"id": "source-1", "type": "source", "title": "Prompt Source", "settings": {"sourceType": "sheets"}},
                        {"id": "flow-1", "type": "flow", "title": "Google Flow"},
                        {"id": "telegram-1", "type": "telegram", "title": "Telegram Review"},
                        {"id": "approval-1", "type": "approval", "title": "Approval"},
                    ]
                },
            ),
            items=[
                {"row": 2, "prompt": "first product prompt", "product": "Hoop", "index": "1", "active": True},
                {"row": 3, "prompt": "inactive prompt", "product": "Hoop", "index": "2", "active": False},
                {"row": 4, "prompt": "used prompt", "product": "Blanket", "index": "1", "active": True, "used": True},
                {"row": 5, "prompt": "second product prompt", "product": "Blanket", "index": "2", "active": True},
            ],
        )
        seen_prompts: list[str] = []

        async def fake_run_flow_job(job_id, child_request):
            seen_prompts.append(child_request.prompt)
            await self.store.replace_artifacts(
                job_id,
                [JobArtifact(label="Ảnh 1", url="https://example.com/image.jpg", mime_type="image/jpeg", prompt=child_request.prompt)],
            )
            await self.store.patch_job(job_id, status="completed", result={"count": 1, "mode": "image"})

        with patch.object(self.service, "get_auth_status", return_value=AuthStatus(authenticated=True)), patch.object(
            self.service,
            "_run_flow_job",
            side_effect=fake_run_flow_job,
        ):
            batch = await self.service.enqueue_prompt_batch(request)
            await self.service._tasks[batch.id]

        saved = self.store.get_job(batch.id)
        self.assertIsNotNone(saved)
        self.assertEqual("completed", saved.status)
        self.assertEqual(["first product prompt", "second product prompt"], seen_prompts)
        self.assertEqual(2, saved.result["total"])
        self.assertEqual(2, saved.result["completed"])
        self.assertEqual(0, saved.result["failed"])
        child_jobs = [self.store.get_job(job_id) for job_id in saved.result["child_job_ids"]]
        self.assertEqual(["Sheet 1/2 · Hoop #1", "Sheet 2/2 · Blanket #2"], [job.title for job in child_jobs])

    async def test_trello_prompt_batch_runs_one_matching_prompt_and_dedupes_active_batch(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        request = PromptBatchRequest(
            job=CreateJobRequest(
                type="image",
                prompt="",
                count=1,
                automation_graph={
                    "modules": [
                        {
                            "id": "trello-source-1",
                            "type": "trello_source",
                            "title": "Trello Image Source",
                            "settings": {"trelloCard": "https://trello.com/c/card123/wedding-hoop"},
                        },
                        {"id": "flow-1", "type": "flow", "title": "Google Flow"},
                    ]
                },
            ),
            limit=40,
            items=[
                {"row": 108, "prompt": "prompt 1", "product_key": "wedding_hoop", "product": "Wedding Hoop", "index": "1", "active": True},
                {"row": 109, "prompt": "prompt 2", "product_key": "wedding_hoop", "product": "Wedding Hoop", "index": "2", "active": True},
                {"row": 110, "prompt": "prompt 3", "product_key": "other", "product": "Other", "index": "1", "active": True},
            ],
        )
        started = asyncio.Event()
        release = asyncio.Event()
        seen_prompts: list[str] = []

        async def fake_run_flow_job(job_id, child_request):
            seen_prompts.append(child_request.prompt)
            started.set()
            await release.wait()
            await self.store.patch_job(job_id, status="completed", result={"count": 1, "mode": "image"})

        source_hint = {
            "card_id": "card123",
            "card_name": "wedding_hoop",
            "card_url": "https://trello.com/c/card123/wedding-hoop",
            "list_id": "list-ready",
            "list_name": "Ready for AI",
        }

        with patch.object(self.service, "get_auth_status", return_value=AuthStatus(authenticated=True)), patch.object(
            self.service,
            "_trello_source_card_hint",
            return_value=source_hint,
        ), patch.object(
            self.service,
            "_run_flow_job",
            side_effect=fake_run_flow_job,
        ):
            batch = await self.service.enqueue_prompt_batch(request)
            await asyncio.wait_for(started.wait(), timeout=1)
            duplicate = await self.service.enqueue_prompt_batch(request)
            release.set()
            await self.service._tasks[batch.id]

        self.assertEqual(batch.id, duplicate.id)
        self.assertEqual(["prompt 1"], seen_prompts)
        saved = self.store.get_job(batch.id)
        self.assertEqual("completed", saved.status)
        self.assertEqual(1, saved.result["total"])
        self.assertEqual("card123", saved.result["trello_source_hint"]["card_id"])
        child_job = self.store.get_job(saved.result["child_job_ids"][0])
        self.assertEqual("card123", child_job.input["trello_card_id"])

    async def test_trello_prompt_batch_finds_matching_card_in_ready_list(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        request = PromptBatchRequest(
            job=CreateJobRequest(
                type="image",
                prompt="",
                count=1,
                automation_graph={
                    "modules": [
                        {
                            "id": "trello-source-1",
                            "type": "trello_source",
                            "title": "Trello Image Source",
                            "settings": {
                                "trelloBoard": "https://trello.com/b/board123/demo-board",
                                "trelloList": "empty-ready-list",
                            },
                        },
                        {"id": "flow-1", "type": "flow", "title": "Google Flow"},
                    ]
                },
            ),
            limit=40,
            items=[
                {"row": 2, "prompt": "bear prompt", "product_key": "gau_bong", "product": "Gấu bông", "index": "1", "active": True},
                {"row": 3, "prompt": "hoop prompt", "product_key": "wedding_hoop", "product": "Wedding Hoop", "index": "1", "active": True},
            ],
        )
        seen_prompts: list[str] = []
        matched_hint = {
            "card_id": "matched-card",
            "card_name": "gau_bong",
            "card_url": "https://trello.com/c/matched/gau-bong",
            "list_id": "ready-list",
            "list_name": "Ready for AI",
        }

        async def fake_run_flow_job(job_id, child_request):
            seen_prompts.append(child_request.prompt)
            await self.store.patch_job(job_id, status="completed", result={"count": 1, "mode": "image"})

        with patch.object(self.service, "get_auth_status", return_value=AuthStatus(authenticated=True)), patch.object(
            self.service,
            "_trello_source_card_hint",
            return_value={},
        ), patch.object(
            self.service,
            "_trello_matching_image_card_hint",
            return_value=matched_hint,
        ), patch.object(
            self.service,
            "_run_flow_job",
            side_effect=fake_run_flow_job,
        ):
            batch = await self.service.enqueue_prompt_batch(request)
            await self.service._tasks[batch.id]

        saved = self.store.get_job(batch.id)
        self.assertEqual("completed", saved.status)
        self.assertEqual(["bear prompt"], seen_prompts)
        self.assertEqual(1, saved.result["total"])
        self.assertEqual("matched-card", saved.result["trello_source_hint"]["card_id"])
        child_job = self.store.get_job(saved.result["child_job_ids"][0])
        self.assertEqual("matched-card", child_job.input["trello_card_id"])
        self.assertEqual("ready-list", child_job.input["trello_list_id"])

    async def test_auto_trello_prompt_batch_discovers_multiple_image_cards(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        request = PromptBatchRequest(
            job=CreateJobRequest(
                type="image",
                prompt="",
                count=1,
                trello_board_id="https://trello.com/b/board123/demo-board",
                automation_graph={
                    "modules": [
                        {
                            "id": "trello-source-1",
                            "type": "trello_source",
                            "title": "Trello Image Source",
                            "settings": {"trelloBoard": "https://trello.com/b/board123/demo-board"},
                        },
                        {"id": "flow-1", "type": "flow", "title": "Google Flow"},
                    ]
                },
            ),
            limit=10,
            auto_trello=True,
            items=[
                {"row": 2, "prompt": "bear prompt", "product_key": "gau_bong", "product": "Gấu bông", "index": "1", "active": True},
                {"row": 3, "prompt": "hoop prompt", "product_key": "wedding_hoop", "product": "Wedding Hoop", "index": "1", "active": True},
            ],
        )
        seen: list[tuple[str, str]] = []
        cards = [
            {"id": "card-bear", "name": "gau_bong", "shortLink": "bear", "url": "https://trello.com/c/bear", "idList": "ready-list"},
            {"id": "card-hoop", "name": "wedding_hoop", "shortLink": "hoop", "url": "https://trello.com/c/hoop", "idList": "ready-list"},
        ]

        async def fake_run_flow_job(job_id, child_request):
            seen.append((child_request.prompt, child_request.trello_card_id))
            await self.store.patch_job(job_id, status="completed", result={"count": 1, "mode": "image"})

        with patch.object(self.service, "get_auth_status", return_value=AuthStatus(authenticated=True)), patch.object(
            self.service,
            "_trello_credentials",
            return_value=("key", "token"),
        ), patch.object(
            self.service,
            "_trello_resolve_board_list_id",
            return_value="ready-list",
        ), patch.object(
            self.service,
            "_trello_image_cards_on_board",
            return_value=cards,
        ) as image_cards, patch.object(
            self.service,
            "_trello_list_name",
            return_value="Ready for AI",
        ), patch.object(
            self.service,
            "_run_flow_job",
            side_effect=fake_run_flow_job,
        ):
            batch = await self.service.enqueue_prompt_batch(request)
            await self.service._tasks[batch.id]

        image_cards.assert_called_once_with("key", "token", "board123", "ready-list")
        self.assertEqual([("bear prompt", "card-bear"), ("hoop prompt", "card-hoop")], seen)
        saved = self.store.get_job(batch.id)
        self.assertEqual("completed", saved.status)
        self.assertEqual(2, saved.result["total"])
        self.assertEqual(2, saved.result["completed"])
        self.assertEqual("auto_trello", saved.result["trello_source_hint"]["mode"])
        self.assertEqual("ready-list", saved.result["trello_source_hint"]["list_id"])
        child_jobs = [self.store.get_job(job_id) for job_id in saved.result["child_job_ids"]]
        self.assertEqual(["card-bear", "card-hoop"], [job.input["trello_card_id"] for job in child_jobs])

    async def test_generate_images_with_retry_reloads_project_after_recaptcha_error(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        request = CreateJobRequest(type="image", prompt="meo de thuong", count=1, aspect="square")
        job = JobRecord(
            type="image",
            status="queued",
            title=self.service._default_title(request),
            input=request.model_dump(mode="json"),
        )
        await self.store.add_job(job)

        fake_image = SimpleNamespace(
            media_name="img-1",
            workflow_id="wf-1",
            fife_url="https://example.com/img-1.jpg",
            prompt=request.prompt,
            dimensions={"width": 1024, "height": 1024},
        )
        fake_client = SimpleNamespace()

        with patch.object(
            self.service,
            "_generate_images_once",
            AsyncMock(side_effect=RuntimeError("HTTP 403 on batchGenerateImages: reCAPTCHA evaluation failed")),
        ) as generate_once, patch.object(
            self.service,
            "_reload_flow_project_page",
            AsyncMock(),
        ) as reload_project:
            with patch.object(
                self.service,
                "_generate_images_via_ui",
                AsyncMock(return_value=[fake_image]),
            ) as generate_via_ui:
                result = await self.service._generate_images_with_retry(fake_client, job.id, request, [])

        self.assertEqual([fake_image], result)
        self.assertEqual(1, generate_once.await_count)
        reload_project.assert_awaited_once_with(fake_client)
        generate_via_ui.assert_awaited_once_with(fake_client, request, [], job_id=job.id)

    async def test_generate_images_via_ui_uses_single_reference_fallback(self) -> None:
        request = CreateJobRequest(type="image", prompt="them kinh", count=1, aspect="portrait")
        fake_image = SimpleNamespace(media_name="img-1")
        fake_client = SimpleNamespace()

        with patch.object(
            self.service,
            "_generate_single_reference_image_via_ui",
            AsyncMock(return_value=[fake_image]),
        ) as single_ref:
            result = await self.service._generate_images_via_ui(fake_client, request, ["base-media"])

        self.assertEqual([fake_image], result)
        single_ref.assert_awaited_once()

    async def test_select_flow_edit_target_image_drags_source_into_prompt(self) -> None:
        events: list[tuple[str, float | None, float | None]] = []

        class FakeMouse:
            async def move(self, x: float, y: float) -> None:
                events.append(("move", x, y))

            async def down(self) -> None:
                events.append(("down", None, None))

            async def up(self) -> None:
                events.append(("up", None, None))

            async def click(self, x: float, y: float) -> None:
                events.append(("click", x, y))

        class FakePage:
            mouse = FakeMouse()

            async def evaluate(self, script: str, media_token: str) -> dict:
                self.media_token = media_token
                return {
                    "ok": True,
                    "sourceX": 120,
                    "sourceY": 140,
                    "targetX": 420,
                    "targetY": 820,
                    "detail": "drag div 84,84 -> prompt 431,798",
                }

        page = FakePage()
        ok, detail = await self.service._select_flow_edit_target_image(page, "media-source")

        self.assertTrue(ok)
        self.assertEqual("media-source", page.media_token)
        self.assertIn("drag", detail)
        self.assertIn(("down", None, None), events)
        self.assertIn(("up", None, None), events)
        self.assertEqual(("click", 420, 820), events[-1])

    async def test_resolve_image_reference_media_uses_robust_upload_helper(self) -> None:
        await self.store.replace_config(AppConfig(project_id="pid", generation_timeout_s=300, poll_interval_s=1.0))
        reference_a = self.uploads_dir / "model.jpg"
        reference_b = self.uploads_dir / "logo.png"
        reference_a.write_bytes(b"model")
        reference_b.write_bytes(b"logo")
        job = JobRecord(type="image", status="queued", title="test")
        await self.store.add_job(job)

        request = CreateJobRequest(
            type="image",
            prompt="ghép logo này lên áo của người mẫu",
            count=1,
            reference_image_paths=[str(reference_a), str(reference_b)],
        )
        fake_client = SimpleNamespace()

        with patch.object(
            self.service,
            "_upload_project_image_robust",
            AsyncMock(side_effect=["ref-model", "ref-logo"]),
        ) as upload_project_image:
            result = await self.service._resolve_image_reference_media(fake_client, job.id, request)

        self.assertEqual(["ref-model", "ref-logo"], result)
        upload_project_image.assert_any_await(fake_client, str(reference_a.resolve()))
        upload_project_image.assert_any_await(fake_client, str(reference_b.resolve()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
