from __future__ import annotations

import asyncio
import csv
import ctypes
import io
import json
import logging
import mimetypes
import os
import random
import re
import shlex
import shutil
import subprocess
import time
import unicodedata
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Dict, List, Optional
from xml.etree import ElementTree as ET

from fastapi import HTTPException, UploadFile

from .messages import humanize_flow_error
from .paths import DOWNLOADS_DIR, PROJECT_ROOT, UPLOADS_DIR, ensure_app_dirs
from .schemas import (
    AppConfig,
    ArtifactOpenRequest,
    AuthStatus,
    CleanupAssistantSnapshot,
    CleanupGroupSnapshot,
    CleanupItemSnapshot,
    CleanupRequest,
    ConfigUpdateRequest,
    CreateJobRequest,
    DownloadRequest,
    FlowOperatorRequest,
    IntegrationConfig,
    IntegrationConfigUpdateRequest,
    InterruptedReplayGroup,
    InterruptedReplayItem,
    InterruptedReplayPack,
    JobArtifact,
    ProjectHealthSignal,
    ProjectHealthSnapshot,
    ProjectHealthTimelineEntry,
    JobRecord,
    JobRetrySnapshot,
    OutputShelfItem,
    OutputShelfSnapshot,
    PromptAssistantSnapshot,
    PromptBatchItemRequest,
    PromptBatchRequest,
    PromptCreateRequest,
    ProjectEntry,
    ReplayCleanupRequest,
    PublicSkillSnapshot,
    SkillCreateRequest,
    SkillImportRequest,
    SkillRecord,
    StoryboardPlanRequest,
    StoryboardScene,
    TrelloConfig,
    TrelloConfigUpdateRequest,
    UserAssistantRequest,
    WorkspaceJobCounts,
    WorkspaceSnapshot,
    canonical_project_url,
    normalize_project_id,
    normalized_app_config,
    utc_now,
)
from .store import StateStore


def _model_dump(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def _parse_iso_datetime(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class FlowWebService:
    MAX_OUTPUT_SHELF_ITEMS = 6
    PROJECT_HEALTH_TIMELINE_LIMIT = 4
    PROJECT_HEALTH_RECENCY_DAYS = 14
    CLEANUP_PREVIEW_LIMIT = 3
    CLEANUP_UPLOAD_GRACE_HOURS = 2
    CLEANUP_DOWNLOAD_RETENTION_DAYS = 7
    CLEANUP_HISTORY_RETENTION_DAYS = 14
    MAX_PROMPT_BATCH_ITEMS = 40
    SKILL_TEXT_EXTENSIONS = {".sh", ".md", ".txt", ".skill", ".cfg", ".ini", ".env"}
    MEDIA_SKILL_REPO = "inference-sh/skills"
    MEDIA_SKILL_SOURCE_URL = "https://github.com/inference-sh/skills"
    MEDIA_SKILL_PATH_PATTERN = re.compile(r"^.+/SKILL\.md$", re.IGNORECASE)
    GEMINI_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
    GEMINI_TIMEOUT_S = 30
    USER_ASSISTANT_CONTEXT_LIMIT = 1200
    USER_ASSISTANT_ANSWER_LIMIT = 1400
    AI_PROMPT_SUITE_SIZE = 6
    TELEGRAM_API_URL_TEMPLATE = "https://api.telegram.org/bot{token}/{method}"
    TELEGRAM_TIMEOUT_S = 20
    TRELLO_API_BASE_URL = "https://api.trello.com/1"
    TRELLO_TIMEOUT_S = 30
    DEFAULT_TRELLO_SOURCE_LIST_NAME = "Ready for AI"
    DEFAULT_VIDEO_MODEL = "Veo 3.1 - Fast"
    DEFAULT_IMAGE_MODEL = "NARWHAL"
    IMAGE_MODEL_LABELS = {
        "NARWHAL": "Nano Banana 2",
        "IMAGEN_3": "Imagen 3",
    }
    IMAGE_MODEL_EDIT_VALUES = {
        "NARWHAL": "GEM_PIX_2",
        "IMAGEN_3": "IMAGEN_3",
    }
    VIDEO_MODEL_DISPLAY_ALIASES = {
        "veo 3.1 - fast": "Veo 3.1 - Fast",
        "veo 3.1 fast": "Veo 3.1 - Fast",
        "veo 3.1 - quality": "Veo 3.1 - Quality",
        "veo 3.1 quality": "Veo 3.1 - Quality",
        "veo 2 - fast": "Veo 2 - Fast",
        "veo 2 fast": "Veo 2 - Fast",
        "veo 2 - quality": "Veo 2 - Quality",
        "veo 2 quality": "Veo 2 - Quality",
        "veo 3.1 - fast [lower priority]": "Veo 3.1 - Fast [Lower Priority]",
    }
    IMAGE_MODEL_ALIASES = {
        "narwhal": "NARWHAL",
        "gem_pix_2": "NARWHAL",
        "nano banana": "NARWHAL",
        "nano banana 2": "NARWHAL",
        "imagen 3": "IMAGEN_3",
        "imagen3": "IMAGEN_3",
        "imagen_3": "IMAGEN_3",
    }
    POLICY_MINOR_TERMS = (
        "tre vi thanh nien",
        "vi thanh nien",
        "tre em",
        "em be",
        "be gai",
        "be trai",
        "thieu nien",
        "tuoi teen",
        "teen",
        "hoc sinh",
        "minor",
        "underage",
        "child",
        "kid",
        "young girl",
        "young boy",
        "schoolgirl",
        "school boy",
    )
    POLICY_APPEARANCE_TERMS = (
        "dep trai hon",
        "dep gai hon",
        "dep hon",
        "lam dep",
        "fashion",
        "nguoi mau",
        "model",
        "sexy",
        "goi cam",
        "nong bong",
        "makeup",
        "trang diem",
        "body",
        "than hinh",
        "bo kinh",
        "thay do",
        "mac do",
        "mac ao",
        "thu do",
    )
    POLICY_APPAREL_TERMS = (
        "ao",
        "logo",
        "dong phuc",
        "quan ao",
        "quan",
        "vay",
        "thoi trang",
        "outfit",
        "shirt",
        "dress",
        "clothing",
        "fashion",
    )
    REFERENCE_IMAGE_ROLES = ("base", "logo", "product", "reference")
    REFERENCE_IMAGE_ROLE_LABELS = {
        "base": "ảnh chính",
        "logo": "logo",
        "product": "sản phẩm",
        "reference": "tham chiếu",
    }
    PROMPT_SKILL_PREFIXES = (
        "guides/design/",
        "guides/photo/",
        "guides/prompting/",
        "guides/video/",
        "tools/image/",
        "tools/video/",
    )
    SUPPORTED_SKILL_TYPES = {
        "video",
        "image",
        "extend",
        "upscale",
        "camera_motion",
        "camera_position",
        "insert",
        "remove",
    }
    _FLOW_RUNTIME_PATCHED = False

    def __init__(self, store: StateStore) -> None:
        ensure_app_dirs()
        self.store = store
        self._apply_runtime_integration_env()
        self._tasks: Dict[str, asyncio.Task] = {}
        self._browser_session_lock = asyncio.Lock()
        self._telegram_approval_sync_lock = asyncio.Lock()
        self._last_telegram_approval_sync_error = ""
        self._shared_browser: Any | None = None

    async def close(self) -> None:
        async with self._browser_session_lock:
            await self._close_shared_browser()

    def get_state(self) -> Dict[str, Any]:
        snapshot = self.store.snapshot()
        return {
            "config": _model_dump(self._normalized_config(snapshot.config)),
            "jobs": snapshot.jobs,
            "skills": [self._public_skill_payload(skill) for skill in snapshot.skills],
        }

    def get_state_payload(self) -> Dict[str, Any]:
        base_state = self.get_state()
        snapshot = self.store.snapshot()
        auth = self.get_auth_status()
        projects = self.list_projects()
        workspace = self._workspace_snapshot(base_state["config"], auth, base_state["jobs"], projects)
        output_shelf = self._build_output_shelf(base_state["jobs"])
        replay_pack = self._build_replay_pack(base_state["jobs"])
        cleanup_assistant, _ = self._build_cleanup_assistant(base_state["config"], base_state["jobs"], output_shelf)
        return {
            **base_state,
            "projects": projects,
            "auth": auth,
            "integrations": self._integration_config_snapshot(snapshot.integration_config),
            "trello": self._trello_config_snapshot(snapshot.trello_config),
            "workspace": workspace,
            "output_shelf": output_shelf,
            "replay_pack": replay_pack,
            "cleanup_assistant": cleanup_assistant,
            "project_health": self._build_project_health(base_state["config"], auth, base_state["jobs"], projects),
            "prompt_assistant": self._prompt_assistant_snapshot(snapshot.skills),
        }

    def _public_skill_payload(self, skill: SkillRecord) -> Dict[str, Any]:
        snapshot = PublicSkillSnapshot(
            id=skill.id,
            name=skill.name,
            summary=skill.summary,
            source_repo=skill.source_repo,
            source_path=skill.source_path,
            source_url=skill.source_url,
            is_builtin=skill.is_builtin,
            type=skill.type,
            prompt=skill.prompt,
            aspect=skill.aspect,
            count=skill.count,
        )
        return _model_dump(snapshot)

    async def update_config(self, request: ConfigUpdateRequest) -> AppConfig:
        project_id = self._normalize_project_id(request.project_id)
        config = AppConfig(
            project_id=project_id,
            project_name=request.project_name.strip(),
            project_url=self._project_url(project_id),
            active_workflow_id=request.active_workflow_id.strip(),
            headless=request.headless,
            cdp_url=request.cdp_url.strip(),
            generation_timeout_s=max(30, request.generation_timeout_s),
            poll_interval_s=max(1.0, request.poll_interval_s),
            output_dir=request.output_dir.strip(),
        )
        await self.store.replace_config(config)
        config = self._normalized_config(config)
        self._sync_project_to_flow_storage(config)
        return config

    async def update_integration_config(self, request: IntegrationConfigUpdateRequest) -> Dict[str, Any]:
        current = self.store.snapshot().integration_config

        gemini_api_key = request.gemini_api_key.strip()
        telegram_bot_token = request.telegram_bot_token.strip()
        if not request.clear_gemini_api_key:
            gemini_api_key = gemini_api_key or current.gemini_api_key
        if not request.clear_telegram_bot_token:
            telegram_bot_token = telegram_bot_token or current.telegram_bot_token

        gemini_model = self._sanitize_gemini_model(request.gemini_model or current.gemini_model or self.GEMINI_DEFAULT_MODEL)
        config = IntegrationConfig(
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            telegram_bot_token=telegram_bot_token,
            telegram_chat_id=request.telegram_chat_id.strip(),
            playwright_browsers_path=request.playwright_browsers_path.strip(),
            updated_at=utc_now(),
        )
        saved = await self.store.replace_integration_config(config)
        self._apply_runtime_integration_env(saved)
        return self._integration_config_snapshot(saved)

    def _integration_config_snapshot(self, config: IntegrationConfig) -> Dict[str, Any]:
        # Same .env.local fallback rationale as _trello_config_snapshot: chủ
        # nhân set 1 lần qua .env.local thì UI vẫn báo "Đã lưu" dù
        # data/state.json bị reset.
        state_gemini_api_key = str(config.gemini_api_key or "").strip()
        gemini_api_key = state_gemini_api_key
        if not gemini_api_key:
            for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
                env_value = os.getenv(env_name, "").strip()
                if env_value:
                    gemini_api_key = env_value
                    break

        state_telegram_bot_token = str(config.telegram_bot_token or "").strip()
        telegram_bot_token = state_telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

        state_telegram_chat_id = str(config.telegram_chat_id or "").strip()
        telegram_chat_id = state_telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID", "").strip()

        gemini_model = self._sanitize_gemini_model(config.gemini_model or self.GEMINI_DEFAULT_MODEL)
        playwright_browsers_path = str(config.playwright_browsers_path or "").strip()
        runtime_playwright_path = playwright_browsers_path or os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()

        gemini_source = "env" if (gemini_api_key and not state_gemini_api_key) else ("state" if gemini_api_key else "")
        telegram_source = (
            "env"
            if (telegram_bot_token and telegram_chat_id and not (state_telegram_bot_token and state_telegram_chat_id))
            else ("state" if telegram_bot_token and telegram_chat_id else "")
        )

        return {
            "gemini": {
                "configured": bool(gemini_api_key),
                "api_key_saved": bool(gemini_api_key),
                "credentials_source": gemini_source,
                "model": gemini_model,
            },
            "telegram": {
                "configured": bool(telegram_bot_token and telegram_chat_id),
                "bot_token_saved": bool(telegram_bot_token),
                "chat_id": telegram_chat_id,
                "credentials_source": telegram_source,
            },
            "runtime": {
                "playwright_browsers_path": runtime_playwright_path,
                "playwright_browsers_path_set": bool(runtime_playwright_path),
            },
            "updated_at": config.updated_at,
        }

    async def update_trello_config(self, request: TrelloConfigUpdateRequest) -> Dict[str, Any]:
        current = self.store.snapshot().trello_config
        api_key = request.api_key.strip()
        token = request.token.strip()
        if not request.clear_credentials:
            api_key = api_key or current.api_key
            token = token or current.token

        upload_mode = request.upload_mode.strip().lower() or current.upload_mode or "file"
        if upload_mode not in {"file", "url"}:
            upload_mode = "file"

        board_id = self._normalize_trello_board_id(request.board_id)
        card_id = self._normalize_trello_card_id(request.card_id)
        list_id = self._normalize_trello_id(request.list_id)

        config = TrelloConfig(
            api_key=api_key,
            token=token,
            board_id=board_id,
            card_id=card_id,
            list_id=list_id,
            upload_mode=upload_mode,
            set_cover=request.set_cover,
            upscale_to_2k=bool(request.upscale_to_2k),
            updated_at=utc_now(),
        )
        saved = await self.store.replace_trello_config(config)

        persist_result: Dict[str, Any] = {"persisted_to_env": False}
        if request.persist_to_env and not request.clear_credentials:
            persist_payload = {
                "TRELLO_API_KEY": api_key,
                "TRELLO_TOKEN": token,
                "TRELLO_BOARD_ID": board_id,
                "TRELLO_CARD_ID": card_id,
                "TRELLO_LIST_ID": list_id,
            }
            persist_result = self._persist_env_local(
                {key: value for key, value in persist_payload.items() if value}
            )

        snapshot = self._trello_config_snapshot(saved)
        snapshot.update(persist_result)
        return snapshot

    def _persist_env_local(self, values: Dict[str, str]) -> Dict[str, Any]:
        """Write or update ``values`` into ``.env.local`` at repo root.

        Preserves any unrelated lines (other keys, comments, blank lines).
        Returns ``{"persisted_to_env": bool, "persist_error": str, "env_file": str}``
        so the UI can confirm the one-time setup succeeded.

        Also mirrors the values into ``os.environ`` immediately so the running
        process picks them up without a restart.
        """
        from .main import ENV_FILE  # imported lazily to avoid circular import

        env_path = Path(ENV_FILE)
        try:
            existing_lines: List[str] = []
            if env_path.exists():
                existing_lines = env_path.read_text(encoding="utf-8").splitlines()

            updated_lines: List[str] = []
            keys_seen: set[str] = set()
            for raw_line in existing_lines:
                stripped = raw_line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    updated_lines.append(raw_line)
                    continue
                key_part, _ = stripped.split("=", 1)
                key_name = key_part.strip()
                if key_name in values:
                    updated_lines.append(f"{key_name}={values[key_name]}")
                    keys_seen.add(key_name)
                else:
                    updated_lines.append(raw_line)

            appended_any = False
            for key_name, value in values.items():
                if key_name in keys_seen:
                    continue
                if not appended_any and updated_lines and updated_lines[-1].strip():
                    updated_lines.append("")
                if not appended_any:
                    updated_lines.append("# Added by Flow v2 setup wizard")
                    appended_any = True
                updated_lines.append(f"{key_name}={value}")

            env_path.parent.mkdir(parents=True, exist_ok=True)
            env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
        except OSError as exc:
            log.warning("Failed to persist Trello creds to %s: %s", env_path, exc)
            return {
                "persisted_to_env": False,
                "persist_error": str(exc),
                "env_file": str(env_path),
            }

        for key_name, value in values.items():
            os.environ[key_name] = value

        return {
            "persisted_to_env": True,
            "persist_error": "",
            "env_file": str(env_path),
        }

    def _trello_config_snapshot(self, config: TrelloConfig) -> Dict[str, Any]:
        # Fall back to environment variables (loaded from `.env.local` on
        # startup) so the UI's "Đã lưu / Cần thiết lập" badges reflect
        # credentials that live outside ``data/state.json``. This lets chủ
        # nhân set up Trello once via .env.local and skip re-entering creds
        # every time state.json is reset.
        api_key = str(config.api_key or "").strip() or os.getenv("TRELLO_API_KEY", "").strip()
        token = str(config.token or "").strip() or os.getenv("TRELLO_TOKEN", "").strip()
        board_id = self._normalize_trello_board_id(
            str(config.board_id or "").strip() or os.getenv("TRELLO_BOARD_ID", "").strip()
        )
        card_id = self._normalize_trello_card_id(
            str(config.card_id or "").strip() or os.getenv("TRELLO_CARD_ID", "").strip()
        )
        list_id = self._normalize_trello_id(
            str(config.list_id or "").strip() or os.getenv("TRELLO_LIST_ID", "").strip()
        )
        upload_mode = (
            str(config.upload_mode or "").strip().lower()
            or os.getenv("TRELLO_UPLOAD_MODE", "").strip().lower()
            or "file"
        )
        if upload_mode not in {"file", "url"}:
            upload_mode = "file"
        env_credentials_used = (
            (not str(config.api_key or "").strip() and bool(api_key))
            or (not str(config.token or "").strip() and bool(token))
        )
        return {
            "configured": bool(api_key and token and (board_id or card_id or list_id)),
            "credentials_saved": bool(api_key and token),
            "api_key_saved": bool(api_key),
            "token_saved": bool(token),
            "credentials_source": "env" if env_credentials_used else ("state" if api_key and token else ""),
            "board_id": board_id,
            "card_id": card_id,
            "list_id": list_id,
            "upload_mode": upload_mode,
            "set_cover": config.set_cover is not False,
            "upscale_to_2k": bool(getattr(config, "upscale_to_2k", True)),
            "updated_at": config.updated_at,
        }

    async def preview_prompt_source(
        self,
        *,
        file: UploadFile | None = None,
        text: str = "",
        source_url: str = "",
    ) -> Dict[str, Any]:
        source_url = str(source_url or "").strip()
        text = str(text or "").strip()
        rows: List[Dict[str, str]] = []
        source_label = ""

        if file is not None and str(file.filename or "").strip():
            source_label = str(file.filename or "").strip()
            payload = await file.read()
            rows = self._parse_prompt_source_bytes(source_label, payload)
        elif text:
            source_label = "pasted table"
            rows = self._parse_delimited_prompt_table(text)
        elif source_url:
            source_label = source_url
            rows = self._load_prompt_source_url(source_url)
        else:
            raise HTTPException(
                status_code=400,
                detail="Hãy dán link Google Sheet, upload file .xlsx/.csv hoặc paste bảng từ Google Sheets.",
            )

        return self._prompt_source_preview_payload(rows, source_label)

    def _parse_prompt_source_bytes(self, file_name: str, payload: bytes) -> List[Dict[str, str]]:
        suffix = Path(str(file_name or "").lower()).suffix
        if suffix == ".xlsx":
            return self._parse_xlsx_prompt_table(payload)
        if suffix in {".csv", ".tsv", ".txt"}:
            text = self._decode_table_bytes(payload)
            return self._parse_delimited_prompt_table(text)
        raise HTTPException(status_code=400, detail="App hiện hỗ trợ file .xlsx, .csv, .tsv hoặc bảng copy từ Google Sheets.")

    def _load_prompt_source_url(self, source_url: str) -> List[Dict[str, str]]:
        csv_url = self._google_sheet_csv_url(source_url) or source_url
        request = Request(csv_url, headers={"User-Agent": "Flow-Web-UI/1.0"})
        try:
            with urlopen(request, timeout=20) as response:
                payload = response.read()
                content_type = str(response.headers.get("content-type") or "").lower()
        except HTTPError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Không đọc được Google Sheet/CSV (HTTP {exc.code}). Nếu sheet đang riêng tư, hãy tải .xlsx rồi upload vào app.",
            ) from exc
        except TimeoutError as exc:
            raise HTTPException(
                status_code=400,
                detail="Đọc Google Sheet quá lâu. Hãy thử lại, hoặc tải sheet thành file .xlsx rồi upload vào app.",
            ) from exc
        except URLError as exc:
            raise HTTPException(status_code=400, detail=f"Không đọc được link sheet: {exc.reason}") from exc

        if "html" in content_type:
            raise HTTPException(
                status_code=400,
                detail="Link này trả về HTML chứ không phải CSV. Nếu Google Sheet đang riêng tư, hãy tải .xlsx rồi upload vào app.",
            )
        return self._parse_delimited_prompt_table(self._decode_table_bytes(payload))

    def _google_sheet_csv_url(self, source_url: str) -> str:
        parsed = urlparse(str(source_url or "").strip())
        if "docs.google.com" not in parsed.netloc or "/spreadsheets/d/" not in parsed.path:
            return ""
        sheet_id = parsed.path.split("/spreadsheets/d/", 1)[1].split("/", 1)[0].strip()
        if not sheet_id:
            return ""
        query = dict(item.split("=", 1) for item in parsed.query.split("&") if "=" in item)
        gid = query.get("gid", "0") or "0"
        return f"https://docs.google.com/spreadsheets/d/{quote(sheet_id, safe='')}/export?format=csv&gid={quote(gid, safe='')}"

    def _decode_table_bytes(self, payload: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "latin-1"):
            try:
                return payload.decode(encoding)
            except UnicodeDecodeError:
                continue
        return payload.decode("utf-8", errors="replace")

    def _parse_delimited_prompt_table(self, text: str) -> List[Dict[str, str]]:
        rows_text = [line for line in str(text or "").splitlines() if line.strip()]
        if not rows_text:
            return []
        sample = "\n".join(rows_text[:8])
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters="\t,;")
        except csv.Error:
            dialect = csv.excel_tab if sample.count("\t") >= sample.count(",") else csv.excel
        reader = csv.reader(rows_text, dialect)
        return self._table_rows_to_dicts([list(row) for row in reader])

    def _parse_xlsx_prompt_table(self, payload: bytes) -> List[Dict[str, str]]:
        try:
            archive = zipfile.ZipFile(io.BytesIO(payload))
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail="File .xlsx không hợp lệ.") from exc
        with archive:
            sheet_path = self._xlsx_first_sheet_path(archive)
            shared_strings = self._xlsx_shared_strings(archive)
            try:
                root = ET.fromstring(archive.read(sheet_path))
            except KeyError as exc:
                raise HTTPException(status_code=400, detail="Không đọc được sheet đầu tiên trong file .xlsx.") from exc
            matrix: List[List[str]] = []
            for row in root.findall(".//{*}sheetData/{*}row"):
                values: Dict[int, str] = {}
                for cell in row.findall("{*}c"):
                    ref = str(cell.attrib.get("r") or "")
                    column_index = self._xlsx_column_index(ref)
                    if column_index < 0:
                        column_index = len(values)
                    values[column_index] = self._xlsx_cell_value(cell, shared_strings)
                if not values:
                    continue
                width = max(values) + 1
                matrix.append([values.get(index, "") for index in range(width)])
            return self._table_rows_to_dicts(matrix)

    def _xlsx_first_sheet_path(self, archive: zipfile.ZipFile) -> str:
        try:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            first_sheet = workbook.find(".//{*}sheets/{*}sheet")
            rel_id = str(first_sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id") or "") if first_sheet is not None else ""
            relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            for relationship in relationships.findall("{*}Relationship"):
                if relationship.attrib.get("Id") != rel_id:
                    continue
                target = str(relationship.attrib.get("Target") or "worksheets/sheet1.xml").lstrip("/")
                return target if target.startswith("xl/") else f"xl/{target}"
        except Exception:
            pass
        return "xl/worksheets/sheet1.xml"

    def _xlsx_shared_strings(self, archive: zipfile.ZipFile) -> List[str]:
        try:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        except KeyError:
            return []
        values: List[str] = []
        for item in root.findall("{*}si"):
            texts = [node.text or "" for node in item.findall(".//{*}t")]
            values.append("".join(texts))
        return values

    def _xlsx_column_index(self, cell_ref: str) -> int:
        letters = re.sub(r"[^A-Za-z]", "", str(cell_ref or "")).upper()
        if not letters:
            return -1
        value = 0
        for letter in letters:
            value = value * 26 + (ord(letter) - ord("A") + 1)
        return value - 1

    def _xlsx_cell_value(self, cell: ET.Element, shared_strings: List[str]) -> str:
        cell_type = str(cell.attrib.get("t") or "")
        if cell_type == "inlineStr":
            return "".join(node.text or "" for node in cell.findall(".//{*}is/{*}t")).strip()
        value = cell.find("{*}v")
        raw = str(value.text or "") if value is not None else ""
        if cell_type == "s":
            try:
                return shared_strings[int(raw)].strip()
            except Exception:
                return ""
        if cell_type == "b":
            return "TRUE" if raw == "1" else "FALSE"
        return raw.strip()

    def _table_rows_to_dicts(self, matrix: List[List[str]]) -> List[Dict[str, str]]:
        cleaned = [[str(cell or "").strip() for cell in row] for row in matrix if any(str(cell or "").strip() for cell in row)]
        if not cleaned:
            return []
        header_index = 0
        for index, row in enumerate(cleaned[:20]):
            normalized = {self._normalize_prompt_source_header(cell) for cell in row}
            if {"promptcontent", "prompt", "content"} & normalized:
                header_index = index
                break
        headers = cleaned[header_index]
        rows: List[Dict[str, str]] = []
        for raw_row in cleaned[header_index + 1:]:
            item: Dict[str, str] = {}
            for index, header in enumerate(headers):
                key = header or f"Column_{index + 1}"
                item[key] = raw_row[index] if index < len(raw_row) else ""
            if any(value for value in item.values()):
                rows.append(item)
        return rows

    def _prompt_source_preview_payload(self, rows: List[Dict[str, str]], source_label: str) -> Dict[str, Any]:
        columns = list(rows[0].keys()) if rows else []
        prompt_column = self._find_prompt_source_column(columns, {"promptcontent", "prompt", "content"})
        active_column = self._find_prompt_source_column(columns, {"active", "enabled", "use", "run"})
        used_column = self._find_prompt_source_column(
            columns,
            {"used", "done", "completed", "generated", "processed", "dadung", "dungroi", "xong"},
        )
        product_key_column = self._find_prompt_source_column(columns, {"productkey", "productid", "productcode", "sku"})
        product_name_column = self._find_prompt_source_column(columns, {"productname", "producttitle", "product"})
        product_column = product_name_column or product_key_column
        index_column = self._find_prompt_source_column(columns, {"promptindex", "index", "stt"})
        notes_column = self._find_prompt_source_column(columns, {"notes", "note", "ghichu"})
        trello_card_column = self._find_prompt_source_column(
            columns,
            {"trellocard", "trellocardid", "trellocardurl", "card", "cardid", "cardurl", "sourcecard", "sourcecardurl"},
        )
        trello_list_column = self._find_prompt_source_column(
            columns,
            {"trellolist", "trellolistid", "list", "listid", "sourcelist"},
        )

        if not prompt_column:
            raise HTTPException(
                status_code=400,
                detail="Không thấy cột prompt. Hãy đặt tên cột là Prompt_Content hoặc Prompt rồi thử lại.",
            )

        prompts: List[Dict[str, Any]] = []
        for row_number, row in enumerate(rows, start=2):
            prompt = str(row.get(prompt_column) or "").strip()
            if not prompt:
                continue
            active = True if not active_column else self._truthy_sheet_value(row.get(active_column, ""))
            used = False if not used_column else self._truthy_sheet_value(row.get(used_column, ""))
            product_key = str(row.get(product_key_column) or "").strip() if product_key_column else ""
            product_name = str(row.get(product_name_column) or "").strip() if product_name_column else ""
            prompts.append(
                {
                    "row": row_number,
                    "active": active and not used,
                    "used": used,
                    "prompt": prompt,
                    "product": str(row.get(product_column) or "").strip() if product_column else "",
                    "product_key": product_key,
                    "product_name": product_name,
                    "index": str(row.get(index_column) or "").strip() if index_column else "",
                    "notes": str(row.get(notes_column) or "").strip() if notes_column else "",
                    "trello_card_id": str(row.get(trello_card_column) or "").strip() if trello_card_column else "",
                    "trello_list_id": str(row.get(trello_list_column) or "").strip() if trello_list_column else "",
                }
            )

        active_prompts = [item for item in prompts if item["active"]]
        selected = active_prompts[0] if active_prompts else prompts[0] if prompts else {}
        prompt = str(selected.get("prompt") or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="File/bảng này chưa có prompt nào dùng được.")

        preview = []
        for item in (active_prompts or prompts)[:8]:
            text = str(item.get("prompt") or "")
            preview.append(
                {
                    **item,
                    "prompt": text if len(text) <= 220 else f"{text[:217]}...",
                }
            )

        return {
            "source": source_label,
            "columns": columns,
            "row_count": len(rows),
            "prompt_count": len(prompts),
            "active_count": len(active_prompts),
            "used_count": sum(1 for item in prompts if item.get("used")),
            "prompt": prompt,
            "selected": selected,
            "items": active_prompts or prompts,
            "preview": preview,
        }

    def _find_prompt_source_column(self, columns: List[str], candidates: set[str]) -> str:
        for column in columns:
            if self._normalize_prompt_source_header(column) in candidates:
                return column
        return ""

    def _normalize_prompt_source_header(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]+", "", normalized.lower())

    def _truthy_sheet_value(self, value: str) -> bool:
        normalized = self._normalize_prompt_source_header(value)
        return normalized in {"true", "1", "yes", "y", "active", "on", "x", "co", "yesrun"}

    def _apply_runtime_integration_env(self, config: IntegrationConfig | None = None) -> None:
        current = config or self.store.snapshot().integration_config
        playwright_path = str(current.playwright_browsers_path or "").strip()
        if playwright_path:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = playwright_path
            return
        if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
            return
        local_path = PROJECT_ROOT / ".pw-browsers"
        if self._playwright_browsers_installed(local_path):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(local_path)

    def _playwright_browsers_installed(self, path: Path) -> bool:
        if not path.exists():
            return False
        executable_names = {"chrome", "Chromium", "chrome.exe", "Google Chrome for Testing", "chrome-headless-shell"}
        try:
            return any(candidate.is_file() and candidate.name in executable_names for candidate in path.rglob("*"))
        except OSError:
            return False

    def get_auth_status(self) -> AuthStatus:
        _, is_authenticated, _, _, _ = self._flow_modules()
        authenticated = False
        try:
            authenticated = bool(is_authenticated())
        except Exception:
            authenticated = False
        if not authenticated:
            authenticated = self._flow_profile_has_auth_cookies()
        return AuthStatus(authenticated=authenticated)

    def _flow_profile_has_auth_cookies(self) -> bool:
        try:
            from flow._storage import PROFILE_DIR
        except Exception:
            return False

        profile_dir = Path(PROFILE_DIR)
        candidates = [
            profile_dir / "Default" / "Cookies",
            profile_dir / "Default" / "Network" / "Cookies",
        ]
        for candidate in candidates:
            try:
                if candidate.exists() and candidate.stat().st_size > 0:
                    return True
            except OSError:
                continue
        return False

    async def logout_flow(self) -> Dict[str, Any]:
        snapshot = self.store.snapshot()
        config = self._normalized_config(snapshot.config)
        active_jobs = [job for job in snapshot.jobs if job.status in {"queued", "running", "polling"}]

        if active_jobs:
            raise HTTPException(
                status_code=409,
                detail="Đang có tác vụ chạy. Hãy chờ xong rồi đăng xuất Google Flow để tránh ngắt phiên giữa chừng.",
            )

        if config.cdp_url:
            raise HTTPException(
                status_code=400,
                detail="Phiên này đang dùng Chrome ngoài qua CDP. Hãy đăng xuất trực tiếp trong trình duyệt Chrome đó.",
            )

        from flow._storage import PROFILE_DIR, ensure_dirs

        profile_dir = Path(PROFILE_DIR)
        cookies_path = profile_dir / "Default" / "Cookies"
        had_session = cookies_path.exists() and cookies_path.stat().st_size > 0

        try:
            await self.close()
            if profile_dir.exists():
                shutil.rmtree(profile_dir)
            ensure_dirs()
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="Không thể xóa phiên Google Flow hiện tại. Nếu còn cửa sổ Chromium của Flow đang mở, hãy đóng nó rồi thử lại.",
            ) from exc

        return {
            "ok": True,
            "had_session": had_session,
            "auth": _model_dump(self.get_auth_status()),
        }

    async def open_flow_login_surface(self) -> Dict[str, Any]:
        self._assert_windows_interactive_browser_session("đăng nhập Google Flow")
        async with self._browser_session_lock:
            browser = await self._ensure_shared_browser()
            page = await self._open_login_flow_page(browser)
        return {
            "ok": True,
            "url": str(getattr(page, "url", "") or "https://labs.google/fx/vi/tools/flow"),
        }

    async def open_flow_project_surface(self) -> Dict[str, Any]:
        self._assert_windows_interactive_browser_session("mở project Google Flow")
        config = self._normalized_config(self.store.snapshot().config)
        target_url = self._project_url(config.project_id) if config.project_id else "https://labs.google/fx/vi/tools/flow"
        async with self._browser_session_lock:
            browser = await self._ensure_shared_browser()
            if config.project_id:
                await self._repair_placeholder_flow_tabs(browser, target_url)
                page = await self._acquire_fresh_flow_page(browser, target_url)
                await self._ensure_valid_flow_project_page(page, target_url)
                try:
                    await page.bring_to_front()
                except Exception:
                    pass
                await self._foreground_native_flow_window()
            else:
                page = await self._open_login_flow_page(browser)
        return {
            "ok": True,
            "url": str(getattr(page, "url", "") or target_url),
        }

    def list_projects(self) -> List[ProjectEntry]:
        _, _, load_projects, get_active_project, _ = self._flow_modules()
        projects = load_projects()
        active_id, _ = get_active_project()
        normalized_projects, changed = self._normalize_projects_payload(projects)
        normalized_active_id = self._normalize_project_id(active_id or "")

        if normalized_active_id and normalized_active_id not in normalized_projects:
            config = self._normalized_config(self.store.snapshot().config)
            normalized_projects[normalized_active_id] = {
                "name": config.project_name or "web-ui",
                "url": self._project_url(normalized_active_id),
            }
            changed = True

        if changed or normalized_active_id != (active_id or ""):
            self._save_project_registry(normalized_projects, normalized_active_id)

        return [
            ProjectEntry(
                id=project_id,
                name=payload.get("name", ""),
                url=payload.get("url", ""),
                is_active=project_id == normalized_active_id,
            )
            for project_id, payload in normalized_projects.items()
        ]

    def _workspace_snapshot(
        self,
        config: Dict[str, Any] | AppConfig,
        auth: AuthStatus,
        jobs: List[JobRecord],
        projects: List[ProjectEntry],
    ) -> WorkspaceSnapshot:
        normalized_config = self._normalized_config(config)
        active_jobs = sum(1 for job in jobs if job.status in {"queued", "running", "polling"})
        completed_jobs = sum(1 for job in jobs if job.status == "completed")
        failed_jobs = sum(1 for job in jobs if job.status in {"failed", "interrupted"})
        return WorkspaceSnapshot(
            project_id=normalized_config.project_id,
            project_name=normalized_config.project_name,
            project_url=normalized_config.project_url,
            active_workflow_id=normalized_config.active_workflow_id,
            authenticated=auth.authenticated,
            saved_project_count=len(projects),
            job_counts=WorkspaceJobCounts(
                total=len(jobs),
                active=active_jobs,
                completed=completed_jobs,
                failed=failed_jobs,
            ),
        )

    def _build_project_health(
        self,
        config: Dict[str, Any] | AppConfig,
        auth: AuthStatus,
        jobs: List[JobRecord],
        projects: List[ProjectEntry],
    ) -> ProjectHealthSnapshot:
        normalized_config = self._normalized_config(config)
        sorted_jobs = self._sorted_jobs_by_activity(jobs)
        last_activity_at = next((self._job_activity_at(job) for job in sorted_jobs if self._job_activity_at(job)), "")

        if not any([normalized_config.project_id, normalized_config.active_workflow_id, auth.authenticated, sorted_jobs]):
            return ProjectHealthSnapshot()

        signals = [
            self._build_project_signal(normalized_config, projects),
            self._build_auth_signal(auth, sorted_jobs),
            self._build_workflow_signal(normalized_config, sorted_jobs),
            self._build_local_artifact_signal(sorted_jobs),
        ]
        recent_jobs = self._recent_jobs(sorted_jobs, days=self.PROJECT_HEALTH_RECENCY_DAYS)
        timeline = self._build_project_health_timeline(normalized_config, auth, recent_jobs, sorted_jobs)
        status_label, headline, summary = self._project_health_overview(normalized_config, auth, signals, timeline)

        return ProjectHealthSnapshot(
            visible=True,
            status_label=status_label,
            headline=headline,
            summary=summary,
            last_activity_at=last_activity_at,
            trust_signals=signals,
            timeline=timeline,
        )

    def _build_project_signal(self, config: AppConfig, projects: List[ProjectEntry]) -> ProjectHealthSignal:
        project_id = str(config.project_id or "").strip()
        if not project_id:
            return ProjectHealthSignal(
                key="project",
                tone="warning",
                label="Chưa có project",
                detail="Workspace hiện chưa giữ mã project chuẩn, nên app chưa thể kết luận môi trường có sẵn để chạy tiếp.",
                status_label="Thiếu",
            )

        project_name = str(config.project_name or project_id).strip() or project_id
        if any(project.id == project_id for project in projects):
            detail = f"Project {project_name} đang được lưu chuẩn và vẫn xuất hiện trong thư viện project đã lưu."
        else:
            detail = f"Project {project_name} đang được lưu chuẩn trong workspace hiện tại."

        return ProjectHealthSignal(
            key="project",
            tone="positive",
            label="Project hợp lệ",
            detail=detail,
            status_label="Ổn",
        )

    def _build_auth_signal(self, auth: AuthStatus, jobs: List[JobRecord]) -> ProjectHealthSignal:
        latest_success = next((job for job in jobs if job.type == "login" and job.status == "completed"), None)
        latest_failure = next((job for job in jobs if job.type == "login" and job.status in {"failed", "interrupted"}), None)

        if auth.authenticated:
            detail = "Phiên Google Flow hiện còn hiệu lực, nên có thể chạy tiếp mà không phải đăng nhập lại ngay."
            if latest_success is not None:
                detail = "App vẫn nhận diện được phiên Google Flow từ lần đăng nhập gần nhất."
            return ProjectHealthSignal(
                key="auth",
                tone="positive",
                label="Đăng nhập còn hiệu lực",
                detail=detail,
                status_label="Ổn",
            )

        if latest_failure is not None:
            return ProjectHealthSignal(
                key="auth",
                tone="warning",
                label="Đăng nhập cần làm mới",
                detail="Có dấu hiệu phiên Flow vừa lỗi hoặc bị ngắt. Nên mở lại đăng nhập trước khi chạy tiếp.",
                status_label="Chú ý",
            )

        if latest_success is not None:
            return ProjectHealthSignal(
                key="auth",
                tone="watch",
                label="Đăng nhập cần làm mới",
                detail="App còn nhớ lần đăng nhập thành công gần đây, nhưng phiên Flow hiện tại không còn được nhận diện.",
                status_label="Nhắc lại",
            )

        return ProjectHealthSignal(
            key="auth",
            tone="warning",
            label="Chưa đăng nhập",
            detail="Workspace chưa có phiên Google Flow sẵn sàng, nên các tác vụ mới sẽ bị chặn cho tới khi đăng nhập.",
            status_label="Thiếu",
        )

    def _build_workflow_signal(self, config: AppConfig, jobs: List[JobRecord]) -> ProjectHealthSignal:
        active_workflow_id = str(config.active_workflow_id or "").strip()
        recent_workflow_id = self._recent_workflow_id(jobs)
        if active_workflow_id:
            detail = f"Workflow mặc định {active_workflow_id} đang được ghim cho các lần chỉnh sửa tiếp theo."
            if recent_workflow_id and recent_workflow_id != active_workflow_id:
                detail = (
                    f"Workflow mặc định {active_workflow_id} đang được ghim; lịch sử gần đây cũng đã có workflow để quay lại nhanh."
                )
            return ProjectHealthSignal(
                key="workflow",
                tone="positive",
                label="Workflow có sẵn",
                detail=detail,
                status_label="Ổn",
            )

        if recent_workflow_id:
            return ProjectHealthSignal(
                key="workflow",
                tone="watch",
                label="Workflow đang để trống",
                detail=(
                    f"Lịch sử gần đây vẫn có workflow {recent_workflow_id}, nhưng workspace hiện chưa ghim workflow mặc định nào."
                ),
                status_label="Nhắc lại",
            )

        return ProjectHealthSignal(
            key="workflow",
            tone="watch",
            label="Workflow đang để trống",
            detail="Tạo mới vẫn chạy được, nhưng form sửa sẽ ít ngữ cảnh hơn cho tới khi lưu một workflow mặc định.",
            status_label="Tùy chọn",
        )

    def _build_local_artifact_signal(self, jobs: List[JobRecord]) -> ProjectHealthSignal:
        status = self._local_artifact_status(jobs)
        available_count = status["available"]
        missing_count = status["missing"]
        remote_count = status["remote_only"]

        if available_count:
            tone = "watch" if missing_count else "positive"
            detail = f"{available_count} artifact local gần đây vẫn còn mở được trên máy."
            if missing_count:
                detail = f"{available_count} artifact local còn mở được, nhưng {missing_count} tệp khác đã không còn trên máy."
            return ProjectHealthSignal(
                key="artifact",
                tone=tone,
                label="Artifact local còn tồn tại",
                detail=detail,
                status_label="Ổn" if tone == "positive" else "Cần xem",
            )

        if missing_count:
            return ProjectHealthSignal(
                key="artifact",
                tone="warning",
                label="Artifact local đã mất",
                detail=f"Có {missing_count} artifact từng được lưu local nhưng file hiện không còn trên máy.",
                status_label="Chú ý",
            )

        if remote_count:
            return ProjectHealthSignal(
                key="artifact",
                tone="watch",
                label="Chưa có artifact local",
                detail="Lịch sử gần đây đã có kết quả hoàn tất, nhưng hiện mới thấy link gốc chứ chưa có file local trên máy.",
                status_label="Tùy chọn",
            )

        return ProjectHealthSignal(
            key="artifact",
            tone="neutral",
            label="Chưa có artifact local",
            detail="Khi lưu kết quả về máy, app sẽ theo dõi tình trạng file local ngay tại đây.",
            status_label="Nền",
        )

    def _build_project_health_timeline(
        self,
        config: AppConfig,
        auth: AuthStatus,
        recent_jobs: List[JobRecord],
        all_jobs: List[JobRecord],
    ) -> List[ProjectHealthTimelineEntry]:
        if not recent_jobs:
            last_activity_at = next((self._job_activity_at(job) for job in all_jobs if self._job_activity_at(job)), "")
            if not last_activity_at:
                return []
            return [
                ProjectHealthTimelineEntry(
                    key="stale-history",
                    tone="neutral",
                    title="Chưa có hoạt động đủ gần",
                    detail=(
                        f"Lịch sử vẫn còn lưu nhưng đã cũ hơn {self.PROJECT_HEALTH_RECENCY_DAYS} ngày, nên trust signals bên trên đáng tin hơn timeline."
                    ),
                    at=last_activity_at,
                )
            ]

        entries = [
            self._build_login_timeline_entry(auth, recent_jobs),
            self._build_timeout_timeline_entry(recent_jobs),
            self._build_workflow_timeline_entry(config, recent_jobs),
            self._build_interrupted_timeline_entry(recent_jobs),
            self._build_local_artifact_timeline_entry(recent_jobs),
        ]
        timeline = [entry for entry in entries if entry is not None]
        if not timeline:
            success_entry = self._build_recent_success_timeline_entry(recent_jobs)
            if success_entry is not None:
                timeline.append(success_entry)

        timeline.sort(key=lambda item: item.at or "", reverse=True)
        return timeline[: self.PROJECT_HEALTH_TIMELINE_LIMIT]

    def _build_login_timeline_entry(
        self,
        auth: AuthStatus,
        recent_jobs: List[JobRecord],
    ) -> ProjectHealthTimelineEntry | None:
        recent_login_jobs = [job for job in recent_jobs if job.type == "login"]
        latest_success = next((job for job in recent_login_jobs if job.status == "completed"), None)
        latest_failure = next((job for job in recent_login_jobs if job.status in {"failed", "interrupted"}), None)

        if auth.authenticated and latest_success is not None:
            return ProjectHealthTimelineEntry(
                key="login-ok",
                tone="positive",
                title="Login ổn",
                detail="Lần đăng nhập gần nhất vẫn còn nền tốt để quay lại chạy tiếp mà không phải thiết lập lại từ đầu.",
                at=self._job_activity_at(latest_success),
            )

        if auth.authenticated and recent_login_jobs:
            return ProjectHealthTimelineEntry(
                key="login-ok",
                tone="positive",
                title="Login ổn",
                detail="App vẫn đang nhìn thấy phiên Google Flow hoạt động bình thường trong project hiện tại.",
                at=self._job_activity_at(recent_login_jobs[0]),
            )

        if latest_failure is not None:
            return ProjectHealthTimelineEntry(
                key="login-refresh",
                tone="warning",
                title="Đăng nhập cần làm mới",
                detail="Timeline gần đây cho thấy phiên Flow đã bị lỗi hoặc bị ngắt, nên đăng nhập lại trước khi chạy các tác vụ mới.",
                at=self._job_activity_at(latest_failure),
            )

        if latest_success is not None:
            return ProjectHealthTimelineEntry(
                key="login-refresh",
                tone="watch",
                title="Phiên đăng nhập cần làm mới",
                detail="App còn nhớ lần đăng nhập thành công gần đây, nhưng hiện không còn nhìn thấy phiên Flow còn hiệu lực.",
                at=self._job_activity_at(latest_success),
            )

        return None

    def _build_timeout_timeline_entry(self, recent_jobs: List[JobRecord]) -> ProjectHealthTimelineEntry | None:
        timeout_jobs = [
            job
            for job in recent_jobs
            if str(getattr(getattr(job, "error_snapshot", None), "category", "") or "").strip() == "timeout"
        ]
        if not timeout_jobs:
            return None

        ordered = list(reversed(timeout_jobs))
        timeout_values = [self._job_timeout_limit(job) for job in ordered if self._job_timeout_limit(job) > 0]
        latest_job = timeout_jobs[0]
        latest_timeout = self._job_timeout_limit(latest_job)
        if len(timeout_values) >= 2 and timeout_values[-1] > min(timeout_values[:-1]):
            return ProjectHealthTimelineEntry(
                key="timeout-trend",
                tone="warning",
                title="Timeout tăng",
                detail=(
                    f"Các lần lỗi gần đây đã tăng timeout từ {min(timeout_values)}s lên {timeout_values[-1]}s nhưng vẫn có job chạm trần."
                ),
                at=self._job_activity_at(latest_job),
            )

        if len(timeout_jobs) >= 2:
            return ProjectHealthTimelineEntry(
                key="timeout-repeat",
                tone="warning",
                title="Timeout lặp lại",
                detail=(
                    f"Đã có {len(timeout_jobs)} job gần đây cùng chạm giới hạn thời gian chờ. Nên tăng timeout hoặc rút gọn payload trước."
                ),
                at=self._job_activity_at(latest_job),
            )

        return ProjectHealthTimelineEntry(
            key="timeout-single",
            tone="watch",
            title="Có timeout gần đây",
            detail=(
                f"Job gần nhất đã chạm giới hạn {latest_timeout}s. Nếu tiếp tục tác vụ dài, nên tăng timeout trước khi chạy lại."
                if latest_timeout > 0
                else "Job gần nhất đã chạm giới hạn thời gian chờ. Nếu tiếp tục tác vụ dài, nên tăng timeout trước khi chạy lại."
            ),
            at=self._job_activity_at(latest_job),
        )

    def _build_workflow_timeline_entry(
        self,
        config: AppConfig,
        recent_jobs: List[JobRecord],
    ) -> ProjectHealthTimelineEntry | None:
        active_workflow_id = str(config.active_workflow_id or "").strip()
        if active_workflow_id:
            return None

        recent_workflow_id = self._recent_workflow_id(recent_jobs)
        relevant_jobs = [job for job in recent_jobs if job.type != "login"]
        if not relevant_jobs:
            return None

        detail = "Việc tạo mới không bị chặn, nhưng form sửa sẽ không tự điền workflow cho tới khi lưu lại workflow mặc định."
        if recent_workflow_id:
            detail = (
                f"Lịch sử gần đây từng dùng workflow {recent_workflow_id}, nhưng workspace hiện vẫn để trống workflow mặc định."
            )

        return ProjectHealthTimelineEntry(
            key="workflow-empty",
            tone="watch",
            title="Workflow đang để trống",
            detail=detail,
            at=self._job_activity_at(relevant_jobs[0]),
        )

    def _build_interrupted_timeline_entry(self, recent_jobs: List[JobRecord]) -> ProjectHealthTimelineEntry | None:
        interrupted_jobs = [job for job in recent_jobs if job.status == "interrupted"]
        if not interrupted_jobs:
            return None

        latest_job = interrupted_jobs[0]
        count = len(interrupted_jobs)
        return ProjectHealthTimelineEntry(
            key="interrupted-jobs",
            tone="warning",
            title="Có job bị ngắt",
            detail=(
                f"Có {count} job bị ngắt trong timeline gần đây. Replay pack đã giữ input recovery để mở retry nhanh."
            ),
            at=self._job_activity_at(latest_job),
        )

    def _build_local_artifact_timeline_entry(self, recent_jobs: List[JobRecord]) -> ProjectHealthTimelineEntry | None:
        status = self._local_artifact_status(recent_jobs)
        if not status["missing"]:
            return None

        return ProjectHealthTimelineEntry(
            key="artifact-missing",
            tone="watch",
            title="Có artifact local cần kiểm tra",
            detail=f"{status['missing']} tệp local trong lịch sử gần đây đã không còn trên máy, nên output shelf có thể thiếu bản mở nhanh.",
            at=status["latest_local_at"],
        )

    def _build_recent_success_timeline_entry(self, recent_jobs: List[JobRecord]) -> ProjectHealthTimelineEntry | None:
        latest_completed = next((job for job in recent_jobs if job.type != "login" and job.status == "completed"), None)
        if latest_completed is None:
            latest_completed = next((job for job in recent_jobs if job.status == "completed"), None)
        if latest_completed is None:
            return None

        title = latest_completed.title or self._job_type_label(latest_completed.type)
        return ProjectHealthTimelineEntry(
            key="recent-success",
            tone="positive",
            title="Hoạt động gần đây chạy ổn",
            detail=f"Lần chạy gần nhất của {title.lower()} đã hoàn tất, nên project này vẫn có nền tốt để tiếp tục.",
            at=self._job_activity_at(latest_completed),
        )

    def _project_health_overview(
        self,
        config: AppConfig,
        auth: AuthStatus,
        signals: List[ProjectHealthSignal],
        timeline: List[ProjectHealthTimelineEntry],
    ) -> tuple[str, str, str]:
        signal_by_key = {signal.key: signal for signal in signals}
        has_project = str(config.project_id or "").strip() != ""
        has_workflow = str(config.active_workflow_id or "").strip() != ""
        auth_ok = bool(auth.authenticated)
        has_warning_timeline = any(entry.tone in {"watch", "warning"} for entry in timeline)
        local_signal = signal_by_key.get("artifact")

        if has_project and auth_ok and not has_warning_timeline:
            status_label = "Có thể chạy tiếp"
            headline = "Workspace hiện tại đủ nền để tiếp tục công việc mà không cần thiết lập lại."
        elif has_project and not auth_ok:
            status_label = "Cần làm mới đăng nhập"
            headline = "Project vẫn còn đó, nhưng phiên Google Flow cần được làm mới trước khi chạy tiếp."
        elif not has_project:
            status_label = "Cần lưu project"
            headline = "App chưa có project hợp lệ để nối lại công việc gần đây."
        else:
            status_label = "Nên kiểm tra nhanh"
            headline = "Có vài dấu hiệu nên rà lại trước khi chạy tiếp."

        summary_bits = [
            "Project đang được lưu chuẩn." if has_project else "Project chưa được lưu.",
            "Đăng nhập còn hiệu lực." if auth_ok else "Đăng nhập cần làm mới.",
            "Workflow mặc định đã có sẵn." if has_workflow else "Workflow mặc định đang để trống.",
        ]
        if local_signal is not None:
            if local_signal.label == "Artifact local còn tồn tại":
                summary_bits.append("Artifact local vẫn còn trên máy.")
            elif local_signal.label == "Artifact local đã mất":
                summary_bits.append("Artifact local cần được kiểm tra lại.")
        if any(entry.key.startswith("timeout") for entry in timeline):
            summary_bits.append("Timeline gần đây có dấu hiệu timeout.")
        if any(entry.key == "interrupted-jobs" for entry in timeline):
            summary_bits.append("Replay pack đang giữ các job bị ngắt.")

        return status_label, headline, " ".join(summary_bits[:5])

    def _sorted_jobs_by_activity(self, jobs: List[JobRecord]) -> List[JobRecord]:
        return sorted(jobs, key=lambda job: self._job_activity_datetime(job) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    def _recent_jobs(self, jobs: List[JobRecord], *, days: int) -> List[JobRecord]:
        now = datetime.now(timezone.utc)
        threshold = now - timedelta(days=max(1, int(days or 1)))
        recent: List[JobRecord] = []
        for job in jobs:
            at = self._job_activity_datetime(job)
            if at is None or at < threshold:
                continue
            recent.append(job)
        return recent

    def _recent_workflow_id(self, jobs: List[JobRecord]) -> str:
        for job in jobs:
            job_input = job.input if isinstance(job.input, dict) else {}
            workflow_id = str(job_input.get("workflow_id", "") or "").strip()
            if workflow_id:
                return workflow_id
            for artifact in job.artifacts:
                artifact_workflow_id = str(getattr(artifact, "workflow_id", "") or "").strip()
                if artifact_workflow_id:
                    return artifact_workflow_id
        return ""

    def _local_artifact_status(self, jobs: List[JobRecord]) -> Dict[str, Any]:
        available = 0
        missing = 0
        remote_only = 0
        latest_local_at = ""

        for job in jobs:
            activity_at = self._job_activity_at(job)
            for artifact in job.artifacts:
                local_path = str(getattr(artifact, "local_path", "") or "").strip()
                if local_path:
                    if activity_at and activity_at > latest_local_at:
                        latest_local_at = activity_at
                    if self._artifact_local_exists(local_path):
                        available += 1
                    else:
                        missing += 1
                    continue

                if str(getattr(artifact, "url", "") or "").strip() or str(getattr(artifact, "public_url", "") or "").strip():
                    remote_only += 1

        return {
            "available": available,
            "missing": missing,
            "remote_only": remote_only,
            "latest_local_at": latest_local_at,
        }

    def _job_timeout_limit(self, job: JobRecord) -> int:
        job_input = job.input if isinstance(job.input, dict) else {}
        try:
            timeout_s = int(job_input.get("timeout_s") or 0)
        except (TypeError, ValueError):
            timeout_s = 0
        if timeout_s > 0:
            return timeout_s

        candidates = [
            str(job.error or "").strip(),
            str(getattr(getattr(job, "error_snapshot", None), "message", "") or "").strip(),
        ]
        for candidate in candidates:
            match = re.search(r"(?P<seconds>\d+)\s*(?:giây|s)\b", candidate, re.IGNORECASE)
            if match:
                try:
                    return max(0, int(match.group("seconds")))
                except (TypeError, ValueError):
                    continue
        return 0

    def _job_activity_at(self, job: JobRecord) -> str:
        return str(job.updated_at or job.created_at or "").strip()

    def _job_activity_datetime(self, job: JobRecord) -> datetime | None:
        return _parse_iso_datetime(self._job_activity_at(job))

    def _build_replay_pack(self, jobs: List[JobRecord]) -> InterruptedReplayPack:
        order = {"auth": 0, "video": 1, "image": 2, "edit": 3, "other": 4}
        grouped: Dict[str, InterruptedReplayGroup] = {}

        for job in jobs:
            snapshot = getattr(job, "replay_snapshot", None)
            if job.status != "interrupted" or snapshot is None or not snapshot.available or snapshot.cleared_at:
                continue

            group_key = str(snapshot.group_key or "edit").strip() or "edit"
            group_meta = self._replay_group_meta(group_key)
            group = grouped.get(group_key)
            if group is None:
                group = InterruptedReplayGroup(
                    key=group_key,
                    label=group_meta["label"],
                    description=group_meta["description"],
                )
                grouped[group_key] = group

            group.items.append(
                InterruptedReplayItem(
                    job_id=job.id,
                    title=job.title or self._job_type_label(job.type),
                    job_type=job.type,
                    job_type_label=self._job_type_label(job.type),
                    summary=snapshot.summary,
                    previous_status=snapshot.previous_status,
                    previous_status_label=snapshot.previous_status_label,
                    created_at=job.created_at,
                    interrupted_at=snapshot.interrupted_at or job.updated_at,
                    last_log_at=snapshot.last_log_at,
                    last_log_message=snapshot.last_log_message,
                    prompt_excerpt=snapshot.prompt_excerpt,
                    input_fields=list(snapshot.input_fields or []),
                    can_retry=job.type in self.SUPPORTED_SKILL_TYPES,
                    can_cleanup=True,
                )
            )

        if not grouped:
            return InterruptedReplayPack()

        groups = sorted(grouped.values(), key=lambda item: order.get(item.key, 99))
        for group in groups:
            group.items.sort(key=lambda item: (item.interrupted_at or item.created_at or ""), reverse=True)
            group.item_count = len(group.items)

        total_items = sum(group.item_count for group in groups)
        return InterruptedReplayPack(
            has_items=bool(total_items),
            total_items=total_items,
            groups=groups,
            cleanup_note="Dọn metadata recovery chỉ gỡ replay pack khỏi khu interrupted work. Log, history và mọi artifact local đã lưu vẫn được giữ nguyên.",
        )

    async def get_credits(self) -> Dict[str, Any]:
        async def _go(client: Any) -> Dict[str, Any]:
            credits = await client.get_credits()
            return {
                "credits": getattr(credits, "credits", 0),
                "tier": getattr(credits, "tier", ""),
                "sku": getattr(credits, "sku", ""),
                "service_tier": getattr(credits, "service_tier", ""),
            }

        return await self._with_client(_go)

    async def get_workflows(self) -> List[Dict[str, Any]]:
        async def _go(client: Any) -> List[Dict[str, Any]]:
            workflows = await client.get_workflows()
            return [
                {
                    "name": getattr(workflow, "name", ""),
                    "display_name": getattr(workflow, "display_name", ""),
                    "create_time": getattr(workflow, "create_time", ""),
                    "primary_media_id": getattr(workflow, "primary_media_id", ""),
                    "batch_id": getattr(workflow, "batch_id", ""),
                    "project_id": getattr(workflow, "project_id", ""),
                    "media_count": len(getattr(workflow, "medias", []) or []),
                    "media_preview": [
                        self._workflow_media_preview(media)
                        for media in (getattr(workflow, "medias", []) or [])[:3]
                        if isinstance(media, dict)
                    ],
                }
                for workflow in workflows
            ]

        return await self._with_client(_go)

    def _workflow_media_preview(self, media: Dict[str, Any]) -> Dict[str, Any]:
        image = (media.get("image") or {}).get("generatedImage") or {}
        video = (media.get("video") or {}).get("encodedVideo") or {}
        return {
            "name": str(media.get("name") or media.get("mediaName") or "").strip(),
            "keys": sorted(str(key) for key in media.keys())[:20],
            "image_keys": sorted(str(key) for key in image.keys())[:20],
            "video_keys": sorted(str(key) for key in video.keys())[:20],
            "has_image_url": bool(image.get("fifeUrl") or image.get("url") or media.get("fifeUrl")),
            "has_video_url": bool(video.get("fifeUrl") or video.get("url") or media.get("fifeUrl")),
            "raw_excerpt": json.dumps(media, ensure_ascii=False, default=str)[:1200],
        }

    async def get_project_debug(self) -> Dict[str, Any]:
        async def _go(client: Any) -> Dict[str, Any]:
            project_data = await client._api.get_project_data()
            return self._project_debug_payload(project_data)

        return await self._with_client(_go)

    def _project_debug_payload(self, project_data: Dict[str, Any]) -> Dict[str, Any]:
        project_contents = project_data.get("projectContents", {}) if isinstance(project_data, dict) else {}
        workflows = project_contents.get("workflows", []) if isinstance(project_contents, dict) else []
        media_collection = project_contents.get("media") if isinstance(project_contents, dict) else None
        if isinstance(media_collection, dict):
            media_items = [item for item in media_collection.values() if isinstance(item, dict)]
        elif isinstance(media_collection, list):
            media_items = [item for item in media_collection if isinstance(item, dict)]
        else:
            media_items = []
        samples: List[Dict[str, Any]] = []

        def visit(value: Any, path: str = "$") -> None:
            if len(samples) >= 30:
                return
            if isinstance(value, dict):
                keys = set(value.keys())
                interesting = (
                    {"media", "medias", "mediaId", "mediaName", "primaryMediaId", "fifeUrl", "generatedImage", "image"}
                    & keys
                )
                if interesting:
                    samples.append(
                        {
                            "path": path,
                            "keys": sorted(str(key) for key in value.keys())[:40],
                            "excerpt": json.dumps(value, ensure_ascii=False, default=str)[:1800],
                        }
                    )
                for key, child in value.items():
                    visit(child, f"{path}.{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value[:20]):
                    visit(child, f"{path}[{index}]")

        visit(project_data)
        sorted_workflows = sorted(
            [item for item in workflows if isinstance(item, dict)],
            key=lambda item: str((item.get("metadata") or {}).get("createTime") or ""),
            reverse=True,
        )
        return {
            "top_keys": sorted(str(key) for key in project_data.keys()) if isinstance(project_data, dict) else [],
            "project_contents_keys": sorted(str(key) for key in project_contents.keys()) if isinstance(project_contents, dict) else [],
            "workflow_count": len(workflows or []),
            "media_collection_type": type(media_collection).__name__,
            "media_count": len(media_items),
            "latest_media": [self._workflow_media_preview(media) for media in media_items[:10]],
            "latest_workflows": [
                {
                    "name": str(workflow.get("name") or ""),
                    "metadata": workflow.get("metadata", {}),
                    "project_id": str(workflow.get("projectId") or ""),
                    "keys": sorted(str(key) for key in workflow.keys()),
                }
                for workflow in sorted_workflows[:5]
            ],
            "samples": samples,
        }

    async def get_model_config(self) -> Dict[str, Any]:
        async def _go(client: Any) -> Dict[str, Any]:
            return await client.get_model_config()

        try:
            return await self._with_client(_go)
        except Exception as exc:
            logging.warning("Falling back to bundled model options after Flow model config failed: %s", exc)
            return {
                "result": {"videoModels": []},
                "fallback": True,
                "error": humanize_flow_error(str(exc)),
            }

    async def save_upload(self, upload: UploadFile) -> Dict[str, str]:
        ensure_app_dirs()
        file_name = Path(upload.filename or "upload.bin").name
        target = UPLOADS_DIR / file_name
        stem = target.stem
        suffix = target.suffix
        counter = 1
        while target.exists():
            target = UPLOADS_DIR / f"{stem}-{counter}{suffix}"
            counter += 1
        with target.open("wb") as handle:
            shutil.copyfileobj(upload.file, handle)
        upload.file.close()
        return {
            "file_name": target.name,
            "saved_path": str(target),
            "public_url": f"/files/uploads/{target.name}",
        }

    async def enqueue_login(self) -> JobRecord:
        job = JobRecord(type="login", status="queued", title="Đăng nhập Google Flow")
        await self.store.add_job(job)
        try:
            page = await self._launch_login_browser(job.id)
        except HTTPException:
            raise
        except Exception as exc:
            detail = self._flow_error_detail(exc)
            await self.store.patch_job(job.id, status="failed", error=detail)
            await self.store.append_log(job.id, f"Đăng nhập thất bại: {detail}")
            raise HTTPException(
                status_code=self._flow_error_status(exc),
                detail=detail,
            ) from exc
        self._tasks[job.id] = asyncio.create_task(self._wait_for_login_completion(job.id, page))
        return job

    async def enqueue_job(self, request: CreateJobRequest) -> JobRecord:
        config = self._normalized_config(self.store.snapshot().config)
        if not config.project_id:
            raise HTTPException(status_code=400, detail="Vui lòng lưu mã project trước.")
        request = self._resolve_job_request(request, config)
        self._validate_job_request(request)
        source_job = self._resolve_retry_source(request.source_job_id, request.type)

        title = request.title.strip() or self._default_title(request)
        job = JobRecord(
            type=request.type,
            status="queued",
            title=title,
            input=_model_dump(request),
            source_job_id=request.source_job_id,
            retry_snapshot=self._build_retry_snapshot(source_job),
        )
        await self.store.add_job(job)
        if source_job is not None:
            await self.store.append_log(
                job.id,
                f"Đã clone payload từ job {source_job.id[:8]} để tạo lần chạy lại mới.",
            )
        policy_notice = self._policy_preflight_notice(request)
        if policy_notice:
            await self.store.append_log(job.id, policy_notice)
        self._tasks[job.id] = asyncio.create_task(self._run_flow_job(job.id, request))
        return job

    async def enqueue_prompt_batch(self, request: PromptBatchRequest) -> JobRecord:
        config = self._normalized_config(self.store.snapshot().config)
        if not config.project_id:
            raise HTTPException(status_code=400, detail="Vui lòng lưu mã project trước.")
        if not self.get_auth_status().authenticated:
            raise HTTPException(
                status_code=400,
                detail="Cần đăng nhập Google Flow trước khi chạy batch prompt từ sheet.",
            )

        base_request = self._resolve_job_request(request.job, config)
        if base_request.type != "image":
            raise HTTPException(status_code=400, detail="Batch prompt từ sheet hiện chỉ hỗ trợ tạo ảnh.")

        limit = max(1, min(self.MAX_PROMPT_BATCH_ITEMS, int(request.limit or self.MAX_PROMPT_BATCH_ITEMS)))
        source_item_count = len(request.items or [])
        items = self._prompt_batch_items(request.items, max(limit, source_item_count))
        if not items and not request.auto_trello:
            raise HTTPException(
                status_code=400,
                detail="Hãy nhập prompt, hoặc bật Auto Trello để AI tự viết prompt từ card có ảnh.",
            )
        if request.auto_trello:
            base_request, items, trello_source_hint = await self._expand_prompt_batch_with_trello_images(
                base_request,
                items,
                limit,
            )
        else:
            base_request, items, trello_source_hint = await self._align_prompt_batch_with_trello_source(base_request, items)

        if not items:
            raise HTTPException(status_code=400, detail="Không tìm thấy card Trello có ảnh trong list nguồn để AI tự viết prompt.")
        if not request.auto_trello and trello_source_hint.get("card_id") and len(items) > 1:
            items = items[:1]
        items = items[:limit]
        batch_key = self._prompt_batch_key(base_request, items, trello_source_hint)
        active_batch = self._active_prompt_batch_by_key(batch_key)
        if active_batch is not None:
            return active_batch

        validation_payload = _model_dump(base_request)
        validation_payload["prompt"] = items[0]["prompt"]
        self._validate_job_request(CreateJobRequest(**validation_payload))

        title = (
            str(request.title or "").strip()
            or (
                f"Auto Trello AI: tạo {len(items)} ảnh từ card có ảnh"
                if request.auto_trello and any(item.get("generated_by_ai") for item in items)
                else f"Auto Trello: tạo {len(items)} ảnh từ card có ảnh"
                if request.auto_trello
                else f"Chạy {len(items)} prompt cho card {trello_source_hint.get('card_name')}"
                if trello_source_hint.get("card_name")
                else f"Chạy batch {len(items)} prompt từ sheet"
            )
        )
        batch_job = JobRecord(
            type="batch_image",
            status="queued",
            title=title,
            input={
                "type": "batch_image",
                "total": len(items),
                "limit": limit,
                "job": _model_dump(base_request),
                "items": items,
                "trello_source_hint": trello_source_hint,
                "batch_key": batch_key,
            },
            result={"total": len(items), "completed": 0, "failed": 0, "child_job_ids": [], "trello_source_hint": trello_source_hint, "batch_key": batch_key},
        )
        await self.store.add_job(batch_job)
        self._tasks[batch_job.id] = asyncio.create_task(self._run_prompt_batch(batch_job.id, base_request, items))
        return batch_job

    def _prompt_batch_items(self, items: List[PromptBatchItemRequest], limit: int) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for item in items or []:
            prompt = str(item.prompt or "").strip()
            if not prompt or item.active is False or item.used is True:
                continue
            normalized.append(
                {
                    "row": int(item.row or 0),
                    "active": True,
                    "used": False,
                    "prompt": prompt,
                    "product": str(item.product or "").strip(),
                    "product_key": str(item.product_key or "").strip(),
                    "product_name": str(item.product_name or "").strip(),
                    "index": str(item.index or "").strip(),
                    "notes": str(item.notes or "").strip(),
                    "trello_card_id": str(item.trello_card_id or "").strip(),
                    "trello_list_id": str(item.trello_list_id or "").strip(),
                    "trello_attachment_ids": self._normalize_trello_attachment_ids(item.trello_attachment_ids),
                }
            )
            if len(normalized) >= limit:
                break
        return normalized

    async def _align_prompt_batch_with_trello_source(
        self,
        base_request: CreateJobRequest,
        items: List[Dict[str, Any]],
    ) -> tuple[CreateJobRequest, List[Dict[str, Any]], Dict[str, Any]]:
        if not items or any(str(item.get("trello_card_id") or "").strip() for item in items):
            return base_request, items, {}

        graph = self._automation_graph_payload(base_request)
        module = next(
            (
                item
                for item in graph["modules"]
                if item["enabled"] and item["type"] == "trello_source"
            ),
            None,
        )
        if module is None:
            return base_request, items, {}

        module_request = self._request_with_automation_module_settings(base_request, module)
        source_hint = await asyncio.to_thread(self._trello_source_card_hint, module_request)
        if not source_hint:
            source_hint = await asyncio.to_thread(self._trello_matching_image_card_hint, module_request, items)
        if not source_hint:
            return base_request, items, {}

        matched = [item for item in items if self._prompt_batch_item_matches_trello_source(item, source_hint)]
        if not matched:
            source_label = source_hint.get("card_name") or source_hint.get("card_id") or "card Trello đang ở list nguồn"
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Card Trello nguồn là {source_label}, nhưng sheet chưa có prompt Active khớp Product_Key/Product_Name. "
                    "Hãy đổi tên card theo Product_Key trong sheet, điền ô Lọc sản phẩm, hoặc thêm cột Trello_Card/Card_URL vào sheet."
                ),
            )

        payload = _model_dump(base_request)
        payload["trello_card_id"] = payload.get("trello_card_id") or str(source_hint.get("card_id") or "")
        if source_hint.get("list_id"):
            payload["trello_list_id"] = payload.get("trello_list_id") or str(source_hint.get("list_id") or "")
        return CreateJobRequest(**payload), matched, source_hint

    async def _expand_prompt_batch_with_trello_images(
        self,
        base_request: CreateJobRequest,
        items: List[Dict[str, Any]],
        limit: int,
    ) -> tuple[CreateJobRequest, List[Dict[str, Any]], Dict[str, Any]]:
        graph = self._automation_graph_payload(base_request)
        module = next(
            (
                item
                for item in graph["modules"]
                if item["enabled"] and item["type"] == "trello_source"
            ),
            None,
        )
        if module is None:
            raise HTTPException(status_code=400, detail="Auto Trello cần bật cục Trello Image Source.")

        module_request = self._request_with_automation_module_settings(base_request, module)
        try:
            expanded_items, discovery = await asyncio.to_thread(
                self._trello_prompt_items_for_image_cards,
                module_request,
                items,
                limit,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=humanize_flow_error(str(exc))) from exc

        payload = _model_dump(base_request)
        if discovery.get("board_id"):
            payload["trello_board_id"] = payload.get("trello_board_id") or str(discovery.get("board_id") or "")
        if discovery.get("list_id"):
            payload["trello_list_id"] = str(discovery.get("list_id") or "")
        return CreateJobRequest(**payload), expanded_items, discovery

    def _prompt_batch_item_matches_trello_source(self, item: Dict[str, Any], source_hint: Dict[str, Any]) -> bool:
        item_card_id = self._normalize_trello_card_id(str(item.get("trello_card_id") or ""))
        source_card_id = self._normalize_trello_card_id(str(source_hint.get("card_id") or ""))
        if item_card_id:
            return bool(source_card_id and item_card_id == source_card_id)

        source_terms = [source_hint.get("card_name")]
        source_text = " ".join(self._compact_match_text(value) for value in source_terms if value)
        if not source_text:
            return False

        item_terms = [
            item.get("product_key"),
            item.get("product_name"),
            item.get("product"),
            item.get("notes"),
        ]
        for value in item_terms:
            normalized = self._compact_match_text(value)
            if normalized and (normalized in source_text or source_text in normalized):
                return True
        return False

    def _compact_match_text(self, value: Any) -> str:
        stripped = self._strip_accents(str(value or "")).strip().lower()
        return re.sub(r"[^a-z0-9]+", "", stripped)

    def _prompt_batch_key(
        self,
        request: CreateJobRequest,
        items: List[Dict[str, Any]],
        trello_source_hint: Dict[str, Any],
    ) -> str:
        card_id = str(trello_source_hint.get("card_id") or request.trello_card_id or "").strip()
        list_id = str(trello_source_hint.get("list_id") or request.trello_list_id or "").strip()
        rows = ",".join(str(item.get("row") or "") for item in items)
        prompt_keys = ",".join(str(item.get("product_key") or item.get("product") or "") for item in items)
        item_card_ids = ",".join(str(item.get("trello_card_id") or "") for item in items)
        attachment_ids = ",".join(self._normalize_trello_attachment_ids(request.trello_attachment_ids))
        item_attachment_ids = ",".join(
            ",".join(self._normalize_trello_attachment_ids(item.get("trello_attachment_ids")))
            for item in items
        )
        return "|".join([card_id, list_id, attachment_ids, rows, prompt_keys, item_card_ids, item_attachment_ids]).strip("|")

    def _active_prompt_batch_by_key(self, batch_key: str) -> JobRecord | None:
        if not batch_key:
            return None
        for job in self.store.snapshot().jobs:
            if job.type != "batch_image" or job.status not in {"queued", "running", "polling"}:
                continue
            job_key = str((job.input or {}).get("batch_key") or (job.result or {}).get("batch_key") or "").strip()
            if job_key == batch_key:
                return job
        return None

    def _prompt_batch_child_title(self, item: Dict[str, Any], index: int, total: int) -> str:
        if item.get("generated_by_ai"):
            label = str(item.get("trello_card_name") or item.get("product") or "").strip() or f"Card {index + 1}"
            shot_label = str(item.get("shot_label") or "").strip()
            suffix = f" · {shot_label}" if shot_label else ""
            return f"AI {index + 1}/{total} · {label}{suffix}"[:120]
        label = str(item.get("product") or "").strip() or f"Prompt dòng {item.get('row') or index + 1}"
        prompt_index = str(item.get("index") or "").strip()
        suffix = f" #{prompt_index}" if prompt_index else ""
        return f"Sheet {index + 1}/{total} · {label}{suffix}"[:120]

    def _prompt_batch_child_request(self, base_request: CreateJobRequest, item: Dict[str, Any], index: int, total: int) -> CreateJobRequest:
        payload = _model_dump(base_request)
        payload["prompt"] = str(item.get("prompt") or "").strip()
        payload["title"] = self._prompt_batch_child_title(item, index, total)
        payload["source_job_id"] = ""
        payload["prompt_source_row"] = int(item.get("row") or 0)
        payload["prompt_product"] = str(item.get("product") or "").strip()
        payload["prompt_product_key"] = str(item.get("product_key") or "").strip()
        payload["prompt_index"] = str(item.get("index") or "").strip()
        payload["prompt_notes"] = str(item.get("notes") or "").strip()
        if item.get("trello_card_id"):
            payload["trello_card_id"] = str(item.get("trello_card_id") or "").strip()
        if item.get("trello_list_id"):
            payload["trello_list_id"] = str(item.get("trello_list_id") or "").strip()
        if item.get("trello_attachment_ids"):
            payload["trello_attachment_ids"] = self._normalize_trello_attachment_ids(item.get("trello_attachment_ids"))
        return CreateJobRequest(**payload)

    async def _patch_prompt_batch_result(
        self,
        batch_id: str,
        *,
        total: int,
        child_job_ids: List[str],
        completed: int,
        failed: int,
        current_index: int = 0,
        current_child_job_id: str = "",
    ) -> None:
        existing = self.store.get_job(batch_id)
        existing_input = existing.input if existing is not None and isinstance(existing.input, dict) else {}
        existing_result = existing.result if existing is not None and isinstance(existing.result, dict) else {}
        trello_source_hint = existing_result.get("trello_source_hint") or existing_input.get("trello_source_hint") or {}
        batch_key = str(existing_result.get("batch_key") or existing_input.get("batch_key") or "").strip()
        result = {
            "total": total,
            "completed": completed,
            "failed": failed,
            "remaining": max(0, total - completed - failed),
            "child_job_ids": child_job_ids,
            "current_index": current_index,
            "current_child_job_id": current_child_job_id,
        }
        if trello_source_hint:
            result["trello_source_hint"] = trello_source_hint
        if batch_key:
            result["batch_key"] = batch_key
        await self.store.patch_job(
            batch_id,
            result=result,
        )

    async def _run_prompt_batch(self, batch_id: str, base_request: CreateJobRequest, items: List[Dict[str, Any]]) -> None:
        total = len(items)
        child_job_ids: List[str] = []
        completed = 0
        failed = 0
        await self.store.patch_job(batch_id, status="running")
        await self.store.append_log(batch_id, f"Bắt đầu vòng lặp {total} prompt active từ sheet.")

        try:
            for index, item in enumerate(items):
                child_request = self._prompt_batch_child_request(base_request, item, index, total)
                self._validate_job_request(child_request)
                child_job = JobRecord(
                    type="image",
                    status="queued",
                    title=child_request.title or self._default_title(child_request),
                    input=_model_dump(child_request),
                )
                await self.store.add_job(child_job)
                child_job_ids.append(child_job.id)
                await self._patch_prompt_batch_result(
                    batch_id,
                    total=total,
                    child_job_ids=child_job_ids,
                    completed=completed,
                    failed=failed,
                    current_index=index + 1,
                    current_child_job_id=child_job.id,
                )
                await self.store.set_progress_hint(
                    batch_id,
                    stage="sending_request",
                    detail=f"Đang chạy prompt {index + 1}/{total}: {child_request.title}",
                )
                await self.store.append_log(batch_id, f"Đang chạy prompt {index + 1}/{total}: {child_request.title}")

                await self._run_flow_job(child_job.id, child_request)
                saved_child = self.store.get_job(child_job.id)
                if saved_child is not None and saved_child.status == "completed":
                    completed += 1
                    await self.store.append_log(batch_id, f"Prompt {index + 1}/{total} đã tạo ảnh và gửi qua các module sau Flow.")
                else:
                    failed += 1
                    detail = saved_child.error if saved_child is not None else "Không tìm thấy job con sau khi chạy."
                    await self.store.append_log(batch_id, f"Prompt {index + 1}/{total} bị lỗi: {detail}")

                await self._patch_prompt_batch_result(
                    batch_id,
                    total=total,
                    child_job_ids=child_job_ids,
                    completed=completed,
                    failed=failed,
                    current_index=index + 1,
                    current_child_job_id="",
                )

            final_status = "failed" if failed == total else "completed"
            error = f"{failed}/{total} prompt bị lỗi trong batch." if failed == total else ""
            await self.store.patch_job(batch_id, status=final_status, error=error)
            await self.store.append_log(batch_id, f"Batch sheet hoàn tất: {completed} xong, {failed} lỗi.")
        except Exception as exc:
            detail = self._flow_error_detail(exc)
            await self.store.patch_job(batch_id, status="failed", error=detail)
            await self.store.append_log(batch_id, f"Batch sheet thất bại: {detail}")

    async def create_skill(self, request: SkillCreateRequest) -> SkillRecord:
        fields_set = self._fields_set(request)
        parsed = self._parse_skill_text(request.skill_text) if request.skill_text.strip() else {}

        name = self._pick_skill_value(fields_set, "name", request.name, parsed.get("name", ""))
        if not name:
            name = self._suggest_skill_name(
                self._pick_skill_value(fields_set, "type", request.type, parsed.get("type", "video")) or "video",
                self._pick_skill_value(fields_set, "prompt", request.prompt, parsed.get("prompt", "")),
            )

        skill_type = self._pick_skill_value(fields_set, "type", request.type, parsed.get("type", "video")) or "video"
        if skill_type not in self.SUPPORTED_SKILL_TYPES:
            raise HTTPException(status_code=400, detail="Loại kỹ năng này chưa được hỗ trợ.")

        skill = SkillRecord(
            name=name,
            summary=self._pick_skill_value(fields_set, "summary", request.summary, parsed.get("summary", "")),
            skill_text=request.skill_text.strip(),
            source_repo=self._pick_skill_value(fields_set, "source_repo", request.source_repo, ""),
            source_path=self._pick_skill_value(fields_set, "source_path", request.source_path, ""),
            source_url=self._pick_skill_value(fields_set, "source_url", request.source_url, ""),
            is_builtin=bool(self._pick_skill_value(fields_set, "is_builtin", request.is_builtin, False)),
            type=skill_type,
            prompt=self._pick_skill_value(fields_set, "prompt", request.prompt, parsed.get("prompt", "")),
            aspect=self._pick_skill_value(fields_set, "aspect", request.aspect, parsed.get("aspect", "landscape")) or "landscape",
            count=max(1, min(4, int(self._pick_skill_value(fields_set, "count", request.count, parsed.get("count", 1)) or 1))),
            reference_media_names=self._normalize_reference_media_names(
                self._pick_skill_list(fields_set, "reference_media_names", request.reference_media_names, parsed.get("reference_media_names", []))
            ),
            media_id=self._pick_skill_value(fields_set, "media_id", request.media_id, parsed.get("media_id", "")),
            workflow_id=self._pick_skill_value(fields_set, "workflow_id", request.workflow_id, parsed.get("workflow_id", "")),
            motion=self._pick_skill_value(fields_set, "motion", request.motion, parsed.get("motion", "")),
            position=self._pick_skill_value(fields_set, "position", request.position, parsed.get("position", "")),
            resolution=self._pick_skill_value(fields_set, "resolution", request.resolution, parsed.get("resolution", "1080p")) or "1080p",
            mask_x=min(1.0, max(0.0, float(self._pick_skill_value(fields_set, "mask_x", request.mask_x, parsed.get("mask_x", 0.5)) or 0.5))),
            mask_y=min(1.0, max(0.0, float(self._pick_skill_value(fields_set, "mask_y", request.mask_y, parsed.get("mask_y", 0.5)) or 0.5))),
            brush_size=max(5, min(100, int(self._pick_skill_value(fields_set, "brush_size", request.brush_size, parsed.get("brush_size", 40)) or 40))),
            source_job_id=self._pick_skill_value(fields_set, "source_job_id", request.source_job_id, parsed.get("source_job_id", "")),
        )
        await self.store.add_skill(skill)
        return skill

    async def ensure_media_skill_library(self) -> Dict[str, Any]:
        snapshot = self.store.snapshot()
        if snapshot.skills and all(skill.is_builtin and skill.source_repo == self.MEDIA_SKILL_REPO for skill in snapshot.skills):
            has_prompting_guides = any("/prompting/" in str(skill.source_path or "").lower() for skill in snapshot.skills)
            if has_prompting_guides:
                return {
                    "items": [self._public_skill_payload(skill) for skill in snapshot.skills],
                    "imported_count": len(snapshot.skills),
                    "mode": "cached",
                    "source_url": self.MEDIA_SKILL_SOURCE_URL,
                }
        return await self.sync_media_skills()

    def _prompt_assistant_snapshot(self, skills: List[SkillRecord]) -> Dict[str, Any]:
        relevant = self._prompt_relevant_skills(skills)
        image_count = sum(1 for skill in relevant if self._skill_targets_mode(skill, "image"))
        video_count = sum(1 for skill in relevant if self._skill_targets_mode(skill, "video"))
        prompting_count = sum(1 for skill in relevant if "/prompting/" in str(skill.source_path or "").lower())
        engine = self._prompt_ai_engine()
        if relevant and engine["configured"]:
            headline = "AI viết prompt đang dùng Gemini."
            summary = f"Đang dùng {engine['model']} cùng {len(relevant)} skill để viết prompt dài, rõ và sát ý cho ảnh/video."
        elif relevant:
            headline = "AI viết prompt đang dùng bộ máy nội bộ."
            summary = f"Đã nạp {len(relevant)} skill để mở rộng prompt chi tiết hơn. Có thể thêm GEMINI_API_KEY để bật Gemini thật."
        elif engine["configured"]:
            headline = "Gemini đã sẵn sàng."
            summary = "Gemini đã bật, còn kho skill viết prompt đang được chuẩn bị."
        else:
            headline = "AI viết prompt đang chờ đồng bộ skill."
            summary = "Chưa có kho skill để viết prompt. Có thể thêm GEMINI_API_KEY để bật Gemini sau."
        snapshot = PromptAssistantSnapshot(
            ready=bool(relevant),
            configured=engine["configured"],
            engine=engine["engine"],
            engine_label=engine["engine_label"],
            model=engine["model"],
            skill_count=len(relevant),
            image_skill_count=image_count,
            video_skill_count=video_count,
            prompt_skill_count=prompting_count,
            source_url=self.MEDIA_SKILL_SOURCE_URL,
            headline=headline,
            summary=summary,
            sample_skill_names=[skill.name for skill in relevant[:6]],
        )
        return _model_dump(snapshot)

    def _prompt_ai_engine(self) -> Dict[str, Any]:
        model = self._gemini_model()
        if self._gemini_api_key():
            return {
                "configured": True,
                "engine": "gemini",
                "engine_label": "Gemini",
                "model": model,
            }
        return {
            "configured": False,
            "engine": "local",
            "engine_label": "Nội bộ",
            "model": "",
        }

    def _flow_operator_requested(self, text: str) -> bool:
        normalized = self._normalize_skill_token(text)
        if not normalized:
            return False
        if "ai" in normalized and "flow" in normalized:
            return True
        return any(
            term in normalized
            for term in (
                "flow_ai",
                "ai_flow",
                "ai_cua_flow",
                "operator",
                "automation",
                "he_thong_tu_dong",
                "dieu_khien_flow",
                "thao_tac_voi_ai",
                "tu_lam_theo_yeu_cau",
            )
        )

    def _flow_operator_wants_run(self, instruction: str, run_mode: str = "") -> bool:
        normalized = self._normalize_skill_token(f"{instruction} {run_mode}")
        return any(
            term in normalized
            for term in (
                "auto",
                "automation",
                "chay",
                "run",
                "tao_luon",
                "lam_luon",
                "bat_dau",
                "hang_loat",
                "xu_ly",
            )
        )

    def _flow_operator_brief(self, instruction: str, product_filter: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(instruction or "").strip())
        if product_filter:
            return (
                f"Dựa trên ảnh sản phẩm nguồn từ Trello card, tạo/chỉnh ảnh thương mại về {product_filter}. "
                "Giữ sản phẩm gốc đúng hình dáng, chất liệu và chi tiết chính; chỉ thay bối cảnh, styling, ánh sáng và bố cục theo prompt."
            )
        if cleaned:
            return (
                f"Dựa trên ảnh sản phẩm nguồn từ Trello card, thực hiện yêu cầu: {cleaned}. "
                "Giữ sản phẩm gốc đúng nhận diện, tạo ảnh mới bằng Google Flow theo phong cách thương mại rõ ràng."
            )
        return "Dựa trên ảnh sản phẩm nguồn từ Trello card, tạo ảnh thương mại sạch, thật, dễ duyệt và sẵn sàng lưu lại Trello."

    def _local_flow_operator_prompt(self, instruction: str, product_filter: str) -> str:
        request = PromptCreateRequest(
            mode="image",
            brief=self._flow_operator_brief(instruction, product_filter),
            style="photorealistic commercial product image, clean composition, realistic lighting",
            must_include=(
                "use the selected Trello attachment as the exact source product, preserve product identity, "
                "make the edited/generated result look like a real product photo"
            ),
            avoid="wrong product, random unrelated item, extra text, watermark, distorted logo, mismatched design",
            audience="Telegram approval and Trello product archive",
            aspect="square",
        )
        selected = self._select_prompt_skills("image", request.brief, request.style, request.must_include)
        baseline = self._compose_prompt_draft(request, selected)
        prompt, _ = self._ensure_prompt_detail(baseline, baseline, "image")
        return prompt

    def _flow_operator_steps(
        self,
        context: Dict[str, Any],
        product_filter: str,
        trello_candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        flow = context.get("flow", {})
        trello = context.get("trello", {})
        telegram = context.get("telegram", {})
        ready_candidates = [item for item in trello_candidates if item.get("in_ready_list")]
        source_detail = (
            f"Đã thấy {len(ready_candidates)} card khớp trong Ready for AI."
            if ready_candidates
            else "Chỉ lấy attachment ảnh từ card ở Ready for AI hoặc card đã ghim rõ ràng."
        )
        return [
            {
                "label": "Tìm ảnh Trello",
                "detail": source_detail,
                "status": "sẵn sàng" if trello.get("configured") else "cần Trello",
            },
            {
                "label": "AI viết prompt",
                "detail": (
                    f"Dùng '{product_filter}' làm từ khóa tìm card; nếu có Sheet thì vẫn ưu tiên Product_Key/Product_Name/Card_URL."
                    if product_filter
                    else "Không cần Sheet: AI sẽ viết prompt từ tên card và attachment; Sheet chỉ dùng khi chủ nhân muốn prompt có sẵn."
                ),
                "status": "sẵn sàng",
            },
            {
                "label": "Điều khiển Flow AI",
                "detail": "AI operator viết prompt, đổ vào Flow, mở project Flow và chạy bằng ảnh nguồn đã chọn.",
                "status": "sẵn sàng" if flow.get("project_set") and flow.get("authenticated") else "cần mở Flow",
            },
            {
                "label": "Duyệt Telegram",
                "detail": "Ảnh tạo xong gửi sang Telegram; chỉ ảnh được duyệt mới được lưu lại Trello.",
                "status": "sẵn sàng" if telegram.get("configured") else "cần Telegram",
            },
            {
                "label": "Lưu lại Trello",
                "detail": "Ảnh được duyệt upload về đúng card nguồn, không lưu sang card khác.",
                "status": "sẵn sàng" if trello.get("configured") else "cần Trello",
            },
        ]

    def _dedupe_assistant_actions(self, actions: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
        unique: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for action in actions:
            label = str(action.get("label") or "")
            action_name = str(action.get("action") or "")
            payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
            payload_key = json.dumps(payload, sort_keys=True, ensure_ascii=True)[:240] if payload else ""
            action_key = f"{action_name}:{label}:{payload_key}"
            if action_key in seen:
                continue
            seen.add(action_key)
            unique.append(action)
        return unique[: max(1, int(limit or 10))]

    def _flow_operator_actions(
        self,
        instruction: str,
        flow_prompt: str,
        product_filter: str,
        *,
        run_mode: str = "plan",
    ) -> List[Dict[str, Any]]:
        actions: List[Dict[str, Any]] = [
            {
                "label": "Áp dụng prompt Flow AI",
                "detail": "Đổ prompt AI operator vào ô tạo ảnh và ô chạy thử Flow để dùng ngay.",
                "action": "apply_flow_ai_prompt",
                "payload": {"prompt": flow_prompt},
                "requires_confirmation": False,
            },
            {
                "label": "Kiểm tra nguồn ảnh Trello",
                "detail": "Mở cục Trello Image Source để chắc chắn ảnh lấy từ attachment của đúng card.",
                "action": "select_trello_source",
                "requires_confirmation": False,
            },
            {
                "label": "Prompt Sheet tùy chọn",
                "detail": "Tùy chọn: xem prompt Sheet nếu chủ nhân vẫn muốn dùng prompt có sẵn.",
                "action": "preview_prompt_source",
                "requires_confirmation": False,
            },
            {
                "label": "Mở Flow",
                "detail": "Mở project Google Flow đã lưu để AI operator thao tác trên phiên đăng nhập hiện tại.",
                "action": "open_flow_project",
                "requires_confirmation": False,
            },
        ]
        if product_filter:
            actions.insert(
                0,
                {
                    "label": f"Lọc sản phẩm: {product_filter}",
                    "detail": "Gắn bộ lọc này trước khi quét Trello/Sheet để giảm rủi ro lấy nhầm ảnh.",
                    "action": "apply_product_filter",
                    "payload": {"value": product_filter},
                    "requires_confirmation": False,
                },
            )
        if self._flow_operator_wants_run(instruction, run_mode):
            actions.append(
                {
                    "label": "Chạy automation Flow",
                    "detail": "Quét Ready for AI, lấy ảnh đúng card, AI tự viết prompt, gửi Telegram duyệt rồi lưu lại Trello.",
                    "action": "run_auto_trello",
                    "payload": {"limit": 1, "test_mode": True} if "test" in self._normalize_skill_token(instruction) else {},
                    "requires_confirmation": True,
                }
            )
        actions.append(
            {
                "label": "Đồng bộ duyệt Telegram",
                "detail": "Kiểm tra các ảnh đã được người dùng duyệt rồi đẩy kết quả về Trello.",
                "action": "sync_telegram_approvals",
                "requires_confirmation": False,
            }
        )
        return self._dedupe_assistant_actions(actions, limit=10)

    def _local_flow_operator_plan(
        self,
        instruction: str,
        context: Dict[str, Any],
        trello_candidates: List[Dict[str, Any]],
        *,
        run_mode: str = "plan",
    ) -> Dict[str, Any]:
        product_filter = self._extract_user_assistant_product_filter(instruction)
        flow_prompt = self._local_flow_operator_prompt(instruction, product_filter)
        return {
            "title": "Flow AI Operator",
            "summary": (
                "AI operator sẽ hiểu yêu cầu, chọn đúng nguồn Trello/Sheet, viết prompt cho Google Flow, "
                "gửi Telegram duyệt và chỉ lưu ảnh đã duyệt về đúng card Trello."
            ),
            "intent": "trello_sheet_flow_telegram_automation",
            "product_filter": product_filter,
            "mode": "image",
            "flow_prompt": flow_prompt,
            "steps": self._flow_operator_steps(context, product_filter, trello_candidates),
            "suggested_actions": self._flow_operator_actions(instruction, flow_prompt, product_filter, run_mode=run_mode),
            "requires_confirmation": self._flow_operator_wants_run(instruction, run_mode),
        }

    def _gemini_flow_operator_request(
        self,
        instruction: str,
        context_summary: str,
        local_plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        prompt_text = "\n".join(
            [
                "Bạn là Flow AI Operator trong app Flow v2.",
                "Nhiệm vụ: biến yêu cầu người dùng thành kế hoạch automation có thể thao tác Google Flow.",
                "Quy trình bắt buộc: Trello Ready for AI attachment -> Flow AI Operator tự viết prompt -> Google Flow tạo/chỉnh ảnh bằng ảnh nguồn đúng card -> Telegram duyệt -> upload ảnh duyệt về đúng card Trello.",
                "Bạn không được yêu cầu secret trong chat và không in API key/token/cookie.",
                "Trả về duy nhất JSON object, không markdown.",
                "Schema JSON:",
                '{"title": str, "summary": str, "product_filter": str, "flow_prompt": str, "steps": [{"label": str, "detail": str, "status": str}], "safety_notes": [str]}',
                "flow_prompt phải là prompt ảnh chi tiết có thể dán vào Google Flow, nhấn mạnh dùng selected Trello attachment/reference image và giữ đúng sản phẩm gốc.",
                "steps dùng tiếng Việt rất dễ hiểu, tối đa 5 bước.",
                "",
                "Trạng thái app đã lọc secret:",
                context_summary,
                "",
                "Yêu cầu người dùng:",
                instruction,
                "",
                "Kế hoạch nội bộ để tham khảo:",
                json.dumps(local_plan, ensure_ascii=False)[:2500],
            ]
        )
        return {
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": {
                "temperature": 0.35,
                "topP": 0.9,
                "maxOutputTokens": 1400,
            },
        }

    def _generate_flow_operator_plan_with_gemini(
        self,
        instruction: str,
        context_summary: str,
        local_plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        api_key = self._gemini_api_key()
        if not api_key:
            raise RuntimeError("Chưa cấu hình Gemini.")

        model = self._gemini_model()
        payload = self._gemini_flow_operator_request(instruction, context_summary, local_plan)
        url = self.GEMINI_API_URL_TEMPLATE.format(model=quote(model, safe="._-"))
        request_obj = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )
        try:
            with urlopen(request_obj, timeout=self.GEMINI_TIMEOUT_S) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                error_payload = json.loads(exc.read().decode("utf-8"))
                message = str(error_payload.get("error", {}).get("message", "")).strip()
            except Exception:
                message = ""
            raise RuntimeError(message or f"Gemini API trả về HTTP {exc.code}.") from exc
        except URLError as exc:
            raise RuntimeError(f"Không gọi được Gemini: {exc.reason}") from exc

        text = self._extract_gemini_text(body)
        parsed = self._parse_json_candidate(text)
        if not isinstance(parsed, dict):
            raise RuntimeError("Gemini không trả về kế hoạch Flow AI hợp lệ.")
        return parsed

    def _normalize_flow_operator_plan(
        self,
        raw_plan: Dict[str, Any],
        local_plan: Dict[str, Any],
        instruction: str,
        *,
        run_mode: str = "plan",
    ) -> Dict[str, Any]:
        product_filter = str(raw_plan.get("product_filter") or local_plan.get("product_filter") or "").strip()
        flow_prompt = self._clean_prompt_text(str(raw_plan.get("flow_prompt") or local_plan.get("flow_prompt") or ""))
        if len(flow_prompt) < 160:
            flow_prompt = str(local_plan.get("flow_prompt") or flow_prompt).strip()
        raw_steps = raw_plan.get("steps") if isinstance(raw_plan.get("steps"), list) else local_plan.get("steps", [])
        steps: List[Dict[str, Any]] = []
        for item in raw_steps[:5]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            detail = str(item.get("detail") or "").strip()
            if not label and not detail:
                continue
            steps.append(
                {
                    "label": label or "Bước automation",
                    "detail": detail,
                    "status": str(item.get("status") or "sẵn sàng").strip()[:60],
                }
            )
        if not steps:
            steps = list(local_plan.get("steps") or [])
        plan = {
            **local_plan,
            "title": str(raw_plan.get("title") or local_plan.get("title") or "Flow AI Operator").strip(),
            "summary": str(raw_plan.get("summary") or local_plan.get("summary") or "").strip(),
            "product_filter": product_filter,
            "flow_prompt": flow_prompt,
            "steps": steps,
            "safety_notes": [str(item).strip() for item in raw_plan.get("safety_notes", [])[:4] if str(item).strip()]
            if isinstance(raw_plan.get("safety_notes"), list)
            else [],
        }
        plan["suggested_actions"] = self._flow_operator_actions(instruction, flow_prompt, product_filter, run_mode=run_mode)
        plan["requires_confirmation"] = self._flow_operator_wants_run(instruction, run_mode)
        return plan

    async def plan_flow_operator(self, request: FlowOperatorRequest, *, use_gemini: bool = True) -> Dict[str, Any]:
        instruction = re.sub(r"\s+", " ", str(request.instruction or "").strip())
        if not instruction:
            raise HTTPException(status_code=400, detail="Hãy nhập yêu cầu để Flow AI operator lập kế hoạch.")
        instruction = instruction[:1000]
        ui_context = re.sub(r"\s+", " ", str(request.context or "").strip())[: self.USER_ASSISTANT_CONTEXT_LIMIT]
        run_mode = self._normalize_skill_token(str(request.run_mode or "plan")) or "plan"

        context = self._user_assistant_context_snapshot()
        product_filter = self._extract_user_assistant_product_filter(instruction)
        trello_candidates: List[Dict[str, Any]] = []
        trello_candidate_error = ""
        trello_candidate_scan_attempted = bool(product_filter and context.get("trello", {}).get("configured"))
        if trello_candidate_scan_attempted:
            try:
                trello_candidates = await asyncio.to_thread(self._user_assistant_trello_candidates, product_filter)
            except Exception as exc:
                trello_candidate_error = str(exc)[:180]
        if trello_candidate_scan_attempted:
            context["trello_candidate_scan"] = self._format_user_assistant_trello_candidate_context(trello_candidates, product_filter)
        context_summary = self._format_user_assistant_context(context, ui_context)

        local_plan = self._local_flow_operator_plan(instruction, context, trello_candidates, run_mode=run_mode)
        plan = local_plan
        engine = "local"
        engine_label = "Nội bộ"
        model = ""
        fallback_reason = ""

        if use_gemini and self._gemini_api_key():
            model = self._gemini_model()
            try:
                raw_plan = await asyncio.to_thread(
                    self._generate_flow_operator_plan_with_gemini,
                    instruction,
                    context_summary,
                    local_plan,
                )
                plan = self._normalize_flow_operator_plan(raw_plan, local_plan, instruction, run_mode=run_mode)
                engine = "gemini"
                engine_label = "Gemini"
            except Exception as exc:
                fallback_reason = str(exc)[:180]
                model = ""

        return {
            **plan,
            "engine": engine,
            "engine_label": engine_label,
            "model": model,
            "trello_candidates": trello_candidates,
            "trello_candidates_error": trello_candidate_error,
            "context_summary": context_summary,
            "fallback_reason": fallback_reason,
        }

    def _user_assistant_context_snapshot(self) -> Dict[str, Any]:
        snapshot = self.store.snapshot()
        config = self._normalized_config(snapshot.config)
        trello = self._trello_config_snapshot(snapshot.trello_config)
        integrations = self._integration_config_snapshot(snapshot.integration_config)
        try:
            auth = self.get_auth_status()
        except Exception:
            auth = AuthStatus(authenticated=False)

        jobs = list(snapshot.jobs or [])
        active_jobs = [job for job in jobs if job.status in {"queued", "running", "polling"}]
        completed_jobs = [job for job in jobs if job.status == "completed"]
        failed_jobs = [job for job in jobs if job.status in {"failed", "interrupted"}]
        latest_job = next(iter(self._sorted_jobs_by_activity(jobs)), None) if jobs else None
        latest_failed = next(iter(self._sorted_jobs_by_activity(failed_jobs)), None) if failed_jobs else None

        return {
            "flow": {
                "project_set": bool(config.project_id),
                "project_name": config.project_name or "",
                "workflow_set": bool(config.active_workflow_id),
                "authenticated": bool(auth.authenticated),
            },
            "trello": {
                "configured": bool(trello.get("configured")),
                "credentials_saved": bool(trello.get("credentials_saved")),
                "board_id_set": bool(trello.get("board_id")),
                "card_id_set": bool(trello.get("card_id")),
                "list_id_set": bool(trello.get("list_id")),
                "upload_mode": trello.get("upload_mode") or "file",
                "upscale_to_2k": trello.get("upscale_to_2k") is not False,
            },
            "telegram": {
                "configured": bool(integrations.get("telegram", {}).get("configured")),
                "chat_id_set": bool(integrations.get("telegram", {}).get("chat_id")),
            },
            "gemini": {
                "configured": bool(integrations.get("gemini", {}).get("configured")),
                "model": integrations.get("gemini", {}).get("model") or self.GEMINI_DEFAULT_MODEL,
            },
            "jobs": {
                "total": len(jobs),
                "active": len(active_jobs),
                "completed": len(completed_jobs),
                "failed": len(failed_jobs),
                "latest_status": str(getattr(latest_job, "status", "") or ""),
                "latest_type": str(getattr(latest_job, "type", "") or ""),
                "latest_title": str(getattr(latest_job, "title", "") or "")[:120],
                "latest_failed_category": str(getattr(getattr(latest_failed, "error_snapshot", None), "category", "") or ""),
                "latest_failed_title": str(getattr(getattr(latest_failed, "error_snapshot", None), "title", "") or "")[:140],
            },
            "workflow": {
                "product_source": "Trello card attachment trong list Ready for AI",
                "prompt_source": "Flow AI Operator tự viết prompt theo card Trello; Google Sheet/CSV chỉ là tùy chọn",
                "flow_step": "Google Flow dùng ảnh nguồn từ đúng card và prompt do AI viết để tạo/chỉnh ảnh",
                "approval_step": "Telegram gửi ảnh để người dùng duyệt",
                "archive_step": "Ảnh được duyệt upload lại đúng Trello card nguồn",
            },
        }

    def _format_user_assistant_context(self, context: Dict[str, Any], ui_context: str = "") -> str:
        flow = context.get("flow", {})
        trello = context.get("trello", {})
        telegram = context.get("telegram", {})
        gemini = context.get("gemini", {})
        jobs = context.get("jobs", {})
        lines = [
            "Quy trình chuẩn: Trello Ready for AI card attachment -> Flow AI Operator tự viết prompt -> Google Flow tạo/chỉnh ảnh -> Telegram duyệt -> upload lại đúng card Trello.",
            "Nơi lấy sản phẩm: ảnh sản phẩm gốc nằm trong attachment của từng Trello card ở list Ready for AI; Google Sheet/CSV chỉ là tùy chọn nếu muốn dùng prompt có sẵn.",
            f"Flow: project {'đã lưu' if flow.get('project_set') else 'chưa lưu'}, workflow {'đã chọn' if flow.get('workflow_set') else 'chưa chọn'}, {'đã đăng nhập' if flow.get('authenticated') else 'chưa thấy phiên đăng nhập'}.",
            f"Trello: {'đã cấu hình' if trello.get('configured') else 'chưa đủ cấu hình'}, board {'có' if trello.get('board_id_set') else 'chưa có'}, card mặc định {'có' if trello.get('card_id_set') else 'không'}, list mặc định {'có' if trello.get('list_id_set') else 'không'}, lưu kiểu {trello.get('upload_mode') or 'file'}.",
            f"Telegram: {'đã cấu hình duyệt' if telegram.get('configured') else 'chưa đủ bot/chat để duyệt'}.",
            f"AI: {'Gemini ' + str(gemini.get('model') or '') if gemini.get('configured') else 'trợ lý nội bộ'}.",
            f"Jobs: {jobs.get('active', 0)} đang chạy, {jobs.get('completed', 0)} xong, {jobs.get('failed', 0)} lỗi; job mới nhất {jobs.get('latest_type') or 'chưa có'} / {jobs.get('latest_status') or 'chưa có'}.",
        ]
        cleaned_ui_context = re.sub(r"\s+", " ", str(ui_context or "").strip())
        if cleaned_ui_context:
            lines.append(f"Ngữ cảnh UI: {cleaned_ui_context[: self.USER_ASSISTANT_CONTEXT_LIMIT]}")
        candidate_scan = str(context.get("trello_candidate_scan") or "").strip()
        if candidate_scan:
            lines.append(candidate_scan)
        return "\n".join(lines)

    def _extract_user_assistant_product_filter(self, question: str) -> str:
        raw = re.sub(r"\s+", " ", str(question or "").strip())
        if not raw:
            return ""

        patterns = [
            r"(?:tìm|tim).*?(?:ảnh|anh).*?(?:về|ve|cho)\s+([^\n,.;]{2,48})",
            r"(?:ảnh|anh)\s*(?:về|ve|cho)\s+([^\n,.;]{2,48})",
            r"(?:product[_\s-]*key|product|sản phẩm|san pham|lọc|loc)\s*(?:là|la|=|:)?\s*([^\n,.;]{2,48})",
            r"(?:tạo|tao|chạy|chay|làm|lam)\s+(?:ảnh|anh)?\s*(?:cho|sản phẩm|san pham)?\s*([^\n,.;]{2,48})",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw, flags=re.IGNORECASE)
            if not match:
                continue
            value = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;\"'")
            if value.startswith(("http://", "https://")) or "trello.com/" in value.lower():
                continue
            value = re.sub(
                r"\b(?:cho tôi|cho toi|của tôi|cua toi|rồi|roi|xong|nhé|nhe|giúp|giup|đi|di|auto|trello|flow|telegram|sheet)\b.*$",
                "",
                value,
                flags=re.IGNORECASE,
            ).strip()
            if 2 <= len(value) <= 48:
                return value

        normalized = self._normalize_skill_token(raw)
        tokens = set(self._tokenize_match_words(raw))
        compact = self._compact_match_text(raw)
        common_products = (
            ("tshirt", "tshirt"),
            ("t_shirt", "t_shirt"),
            ("shirt", "shirt"),
            ("gau", "gấu"),
            ("bup_be", "búp bê"),
            ("bupbe", "búp bê"),
            ("doll", "búp bê"),
            ("baby_doll", "búp bê"),
            ("bda", "búp bê"),
            ("ao_thun", "ao thun"),
            ("ao", "ao"),
            ("hoodie", "hoodie"),
            ("mug", "mug"),
            ("tote", "tote"),
            ("wedding_hoop", "wedding_hoop"),
            ("hoops_with_photos", "hoops_with_photos"),
        )
        for token, value in common_products:
            normalized_token = self._normalize_skill_token(token)
            compact_token = normalized_token.replace("_", "")
            if "_" in normalized_token:
                matched = normalized_token in normalized or bool(compact_token and compact_token in compact)
            else:
                matched = normalized_token in tokens
            if matched:
                return value
        return ""

    def _extract_user_assistant_trello_card_hint(self, question: str) -> str:
        raw = re.sub(r"\s+", " ", str(question or "").strip())
        if not raw:
            return ""
        url_match = re.search(r"https?://(?:www\.)?trello\.com/c/[^\s,;]+", raw, flags=re.IGNORECASE)
        if url_match:
            return self._normalize_trello_card_id(url_match.group(0))
        card_match = re.search(
            r"(?:card|thẻ|the)\s*(?:trello)?\s*(?:id|là|la|=|:)?\s*([a-zA-Z0-9_-]{6,32})",
            raw,
            flags=re.IGNORECASE,
        )
        if card_match:
            return self._normalize_trello_card_id(card_match.group(1))
        return ""

    def _user_assistant_suggested_actions(self, question: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        normalized = self._normalize_skill_token(question)
        flow = context.get("flow", {})
        trello = context.get("trello", {})
        telegram = context.get("telegram", {})
        product_filter = self._extract_user_assistant_product_filter(question)
        trello_card_hint = self._extract_user_assistant_trello_card_hint(question)
        test_run = any(term in normalized for term in ("test", "thu", "kiem_tra", "demo", "mot_san_pham", "1_san_pham"))
        actions: List[Dict[str, Any]] = []

        if self._flow_operator_requested(question):
            actions.append(
                {
                    "label": "Lập kế hoạch Flow AI",
                    "detail": "AI operator sẽ viết prompt, chọn nguồn Trello/Sheet và đưa các nút thao tác Flow theo đúng quy trình.",
                    "action": "plan_flow_ai_operator",
                    "payload": {"instruction": question},
                    "requires_confirmation": False,
                }
            )
        if not flow.get("project_set") or not flow.get("authenticated"):
            actions.append(
                {
                    "label": "Kiểm tra Flow",
                    "detail": "Lưu project Flow rồi đăng nhập Google Flow một lần trước khi chạy auto.",
                    "action": "open_flow_project",
                    "requires_confirmation": False,
                }
            )
        if not trello.get("credentials_saved") or not trello.get("board_id_set"):
            actions.append(
                {
                    "label": "Lưu Trello",
                    "detail": "Dán API key, token và board URL trong Trello storage để app lấy ảnh và upload lại đúng card.",
                }
            )
        if not telegram.get("configured"):
            actions.append(
                {
                    "label": "Lưu Telegram",
                    "detail": "Dán bot token và chat id để ảnh tạo xong được gửi sang Telegram chờ duyệt.",
                }
            )

        if product_filter:
            actions.append(
                {
                    "label": f"Lọc sản phẩm: {product_filter}",
                    "detail": "Điền từ khóa này để app tìm đúng card Trello; AI sẽ tự viết prompt nếu không dùng Sheet.",
                    "action": "apply_product_filter",
                    "payload": {"value": product_filter},
                    "requires_confirmation": False,
                }
            )
        if trello_card_hint:
            actions.append(
                {
                    "label": f"Chọn card Trello: {trello_card_hint}",
                    "detail": "Ghim đúng card Trello này làm nguồn ảnh để app không tự chọn card khác.",
                    "action": "set_trello_card",
                    "payload": {"value": trello_card_hint},
                    "requires_confirmation": False,
                }
            )
        if any(term in normalized for term in ("trello", "ready", "card", "list", "anh", "nham")):
            actions.append(
                {
                    "label": "Soát Ready for AI",
                    "detail": "Chỉ để card cần chạy trong list Ready for AI; ảnh nguồn phải nằm trong attachment của chính card đó.",
                    "action": "select_trello_source",
                    "requires_confirmation": False,
                }
            )
        if any(term in normalized for term in ("sheet", "prompt", "active", "product", "loc")):
            actions.append(
                {
                    "label": "Soát prompt sheet",
                    "detail": "Sheet giờ là tùy chọn. Nếu dùng Sheet, prompt cần Active=TRUE và khớp Product_Key/Product_Name hoặc Trello_Card/Card_URL.",
                    "action": "preview_prompt_source",
                    "requires_confirmation": False,
                }
            )
        if any(term in normalized for term in ("duyet", "telegram", "approve", "chap_thuan")):
            actions.append(
                {
                    "label": "Đồng bộ duyệt",
                    "detail": "Sau khi bấm duyệt trên Telegram, app sẽ đồng bộ approval rồi upload ảnh đã duyệt về đúng card Trello.",
                    "action": "sync_telegram_approvals",
                    "requires_confirmation": False,
                }
            )

        if any(term in normalized for term in ("auto", "chay", "tao", "lam", "run", "hang_loat", "bat_dau", "xu_ly")):
            actions.append(
                {
                    "label": "Chạy Auto Trello",
                    "detail": (
                        "Test mode: chỉ chạy 1 prompt/card đầu tiên để kiểm tra sản phẩm thật, Flow và Telegram."
                        if test_run
                        else "App sẽ quét card Ready for AI có ảnh, AI tự viết prompt, tạo/chỉnh bằng Flow rồi gửi Telegram duyệt."
                    ),
                    "action": "run_auto_trello",
                    "payload": {"limit": 1, "test_mode": True} if test_run else {},
                    "requires_confirmation": True,
                }
            )

        if not actions:
            actions.append(
                {
                    "label": "Chạy Auto Trello",
                    "detail": "Khi Flow, Trello và Telegram sẵn sàng, bấm Auto Trello để app tự tìm card, tự viết prompt và chạy hàng loạt.",
                    "action": "run_auto_trello",
                    "requires_confirmation": True,
                }
            )

        return self._dedupe_assistant_actions(actions, limit=8)

    def _user_assistant_trello_candidates(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        query = re.sub(r"\s+", " ", str(query or "").strip())
        if not query:
            return []
        key, token = self._trello_credentials()
        if not key or not token:
            return []

        trello_config = self.store.snapshot().trello_config
        board_id = self._normalize_trello_board_id(trello_config.board_id or os.getenv("TRELLO_BOARD_ID", ""))
        if not board_id:
            return []

        raw_list_id = self._normalize_trello_id(trello_config.list_id or os.getenv("TRELLO_LIST_ID", ""))
        ready_list_id = self._trello_resolve_board_list_id(key, token, board_id, raw_list_id)
        lists = self._trello_board_lists(key, token, board_id)
        list_names = {self._normalize_trello_id(str(item.get("id") or "")): str(item.get("name") or "").strip() for item in lists}

        payload = self._trello_get_json(
            f"boards/{quote(board_id, safe='')}/cards",
            key,
            token,
            fields={
                "fields": "id,name,desc,shortLink,url,idList,closed",
                "filter": "open",
                "attachments": "true",
                "attachment_fields": "id,name,url,mimeType",
            },
        )
        cards = payload if isinstance(payload, list) else []
        query_key = self._compact_match_text(query)
        query_alias_keys = [
            self._compact_match_text(alias)
            for alias in self._trello_query_aliases(query)
            if self._compact_match_text(alias)
        ]
        query_groups = self._user_assistant_trello_query_groups(query)
        candidates: List[Dict[str, Any]] = []

        def candidate_score(
            card: Dict[str, Any],
            image_attachments: List[Dict[str, Any]],
            in_ready_list: bool,
            list_name: str,
        ) -> int:
            card_name_key = self._compact_match_text(card.get("name"))
            haystack_raw = " ".join(
                str(value or "")
                for value in (
                    card.get("name"),
                    card.get("desc"),
                    card.get("url"),
                    list_name,
                    " ".join(str(item.get("name") or "") for item in image_attachments),
                )
            )
            card_text_key = self._compact_match_text(haystack_raw)
            haystack_tokens = set(self._tokenize_match_words(haystack_raw))
            match_score = 0
            if query_key and card_name_key == query_key:
                match_score += 100
            elif query_key and query_key in card_name_key:
                match_score += 80
            elif query_key and query_key in card_text_key:
                match_score += 60
            for alias_key in query_alias_keys:
                if not alias_key or alias_key == query_key:
                    continue
                if card_name_key == alias_key:
                    match_score += 85
                elif alias_key in card_name_key:
                    match_score += 70
                elif alias_key in card_text_key:
                    match_score += 55
            for group in query_groups:
                if group and all(token in haystack_tokens for token in group):
                    match_score += 30 + (len(group) * 12)
            if match_score <= 0:
                return 0
            score = match_score
            if in_ready_list:
                score += 25
            score += min(10, len(image_attachments))
            return score

        for card in cards:
            if not isinstance(card, dict) or card.get("closed"):
                continue
            image_attachments = [
                item
                for item in card.get("attachments") or []
                if isinstance(item, dict) and self._trello_attachment_is_image(item)
            ]
            if not image_attachments:
                continue
            card["_image_attachments"] = image_attachments

            card_list_id = self._normalize_trello_id(str(card.get("idList") or ""))
            list_name = list_names.get(card_list_id) or card_list_id or "Không rõ list"
            in_ready_list = bool(ready_list_id and card_list_id == ready_list_id)
            score = candidate_score(card, image_attachments, in_ready_list, list_name)
            if score <= min(10, len(image_attachments)):
                continue
            candidates.append(
                {
                    "card_id": str(card.get("id") or "").strip(),
                    "short_link": str(card.get("shortLink") or "").strip(),
                    "name": str(card.get("name") or "").strip(),
                    "url": str(card.get("url") or "").strip(),
                    "list_id": card_list_id,
                    "list_name": list_name,
                    "in_ready_list": in_ready_list,
                    "image_count": len(image_attachments),
                    "image_names": [str(item.get("name") or "").strip() for item in image_attachments[:3] if str(item.get("name") or "").strip()],
                    "image_previews": self._trello_candidate_image_previews(str(card.get("id") or "").strip(), image_attachments),
                    "_score": score,
                }
            )

        candidates.sort(key=lambda item: (int(item.get("_score") or 0), bool(item.get("in_ready_list"))), reverse=True)
        cleaned: List[Dict[str, Any]] = []
        for item in candidates[: max(1, min(12, int(limit or 8)))]:
            cleaned.append({key: value for key, value in item.items() if not key.startswith("_")})
        return cleaned

    def _trello_candidate_image_previews(
        self,
        card_id: str,
        image_attachments: List[Dict[str, Any]],
        limit: int = 4,
    ) -> List[Dict[str, str]]:
        previews: List[Dict[str, str]] = []
        normalized_card_id = self._normalize_trello_card_id(card_id)
        for attachment in image_attachments[: max(1, min(6, int(limit or 4)))]:
            if not isinstance(attachment, dict):
                continue
            attachment_id = str(attachment.get("id") or "").strip()
            url = str(attachment.get("url") or "").strip()
            preview_url = url
            if normalized_card_id and attachment_id:
                preview_url = (
                    f"/api/trello/cards/{quote(normalized_card_id, safe='')}/attachments/"
                    f"{quote(attachment_id, safe='')}/preview"
                )
            previews.append(
                {
                    "id": attachment_id,
                    "name": str(attachment.get("name") or "").strip(),
                    "url": url,
                    "preview_url": preview_url,
                    "mime_type": str(attachment.get("mimeType") or "").strip(),
                }
            )
        return previews

    def _tokenize_match_words(self, value: Any) -> List[str]:
        stripped = self._strip_accents(str(value or "")).lower()
        return [token for token in re.findall(r"[a-z0-9]+", stripped) if token]

    def _user_assistant_trello_query_groups(self, query: str) -> List[List[str]]:
        tokens = [token for token in self._tokenize_match_words(query) if len(token) > 1]
        groups: List[List[str]] = []
        if tokens:
            groups.append(tokens)

        token_set = set(tokens)
        compact = self._compact_match_text(query)
        wants_shirt = "ao" in token_set or "shirt" in token_set or "tshirt" in token_set or "tee" in token_set
        wants_child = bool({"tre", "em", "kid", "kids", "baby", "child", "children", "youth", "toddler"} & token_set) or "treem" in compact
        wants_doll = (
            "doll" in token_set
            or "bupbe" in compact
            or ("bup" in token_set and "be" in token_set)
            or "babydoll" in compact
            or "bda" in token_set
        )
        if wants_doll:
            groups.extend([["doll"], ["baby", "doll"], ["bda"]])
        if wants_shirt and not wants_child:
            groups.extend([["shirt"], ["tshirt"], ["tee"]])
        if wants_shirt and wants_child:
            groups.extend(
                [
                    ["shirt", "kids"],
                    ["shirt", "kid"],
                    ["shirt", "baby"],
                    ["shirt", "child"],
                    ["shirt", "children"],
                    ["shirt", "youth"],
                    ["shirt", "toddler"],
                    ["tshirt", "kids"],
                    ["tshirt", "baby"],
                    ["tee", "kids"],
                    ["tee", "baby"],
                ]
            )

        unique: List[List[str]] = []
        seen: set[tuple[str, ...]] = set()
        for group in groups:
            cleaned = [token for token in group if token and len(token) > 1]
            key = tuple(cleaned)
            if not cleaned or key in seen:
                continue
            seen.add(key)
            unique.append(cleaned)
        return unique

    def _format_user_assistant_trello_candidate_context(self, candidates: List[Dict[str, Any]], query: str) -> str:
        if not candidates:
            return f"Trello scan theo '{query}': chưa thấy card có attachment ảnh khớp trên board."
        ready = [item for item in candidates if item.get("in_ready_list")]
        lines = [
            f"Trello scan theo '{query}': tìm thấy {len(candidates)} card có ảnh; {len(ready)} card đang ở Ready for AI.",
        ]
        for item in candidates[:5]:
            status = "đúng Ready for AI" if item.get("in_ready_list") else "chưa ở Ready for AI"
            lines.append(
                "- "
                + f"{item.get('name') or item.get('short_link') or item.get('card_id')} "
                + f"({item.get('list_name') or 'Không rõ list'}, {item.get('image_count') or 0} ảnh, {status}) "
                + f"{item.get('url') or ''}"
            )
        return "\n".join(lines)

    def _append_user_assistant_trello_candidate_notice(
        self,
        answer: str,
        candidates: List[Dict[str, Any]],
        query: str,
        *,
        scan_attempted: bool = False,
    ) -> str:
        if not query or (not candidates and not scan_attempted):
            return answer
        ready = [item for item in candidates if item.get("in_ready_list")]
        if not candidates:
            notice = (
                f"Trello scan: app chưa tìm thấy card có attachment ảnh khớp '{query}' trên board. "
                "App sẽ không chạy Auto Trello cho tới khi có card đúng trong Ready for AI hoặc chủ nhân chọn/dán link card rõ ràng."
            )
        elif ready:
            ready_names = ", ".join(str(item.get("name") or item.get("short_link") or "").strip() for item in ready[:3] if item)
            notice = (
                f"Trello scan: app tìm thấy {len(ready)} card khớp '{query}' đang ở Ready for AI"
                + (f": {ready_names}." if ready_names else ".")
                + " Hãy bấm đúng thumbnail ảnh để khóa chính xác attachment trước khi chạy."
            )
        else:
            first = candidates[0]
            notice = (
                f"Trello scan: app tìm thấy card khớp '{query}' là {first.get('name') or first.get('short_link')} "
                f"đang ở list {first.get('list_name') or 'khác'}. "
                "Chủ nhân có thể bấm đúng thumbnail ảnh ngay trong app; sau khi chọn, Auto Trello sẽ dùng chính attachment đó mà không cần kéo list."
            )
        if notice in answer:
            return answer
        return f"{answer}\n\n{notice}".strip()

    def _refine_user_assistant_actions_for_trello_candidates(
        self,
        actions: List[Dict[str, Any]],
        candidates: List[Dict[str, Any]],
        trello_card_hint: str,
        *,
        scan_attempted: bool = False,
        query: str = "",
    ) -> List[Dict[str, Any]]:
        if not candidates and not scan_attempted:
            return actions
        ready = [item for item in candidates if item.get("in_ready_list")]
        refined: List[Dict[str, Any]] = []
        for action in actions:
            if action.get("action") == "run_auto_trello" and not trello_card_hint:
                if not ready or len(ready) > 1:
                    continue
            refined.append(action)

        if not candidates:
            refined.append(
                {
                    "label": f"Chưa thấy card: {query}" if query else "Chưa thấy card Trello",
                    "detail": "AI đã quét Trello nhưng chưa thấy card có ảnh khớp. Hãy nhập tên sản phẩm rõ hơn hoặc dán link card Trello cụ thể.",
                }
            )
            return refined[:10]

        for item in candidates[:5]:
            value = str(item.get("short_link") or item.get("card_id") or item.get("url") or "").strip()
            if not value:
                continue
            in_ready = bool(item.get("in_ready_list"))
            refined.append(
                {
                    "label": f"Chọn card: {item.get('name') or value}",
                    "detail": (
                        f"Card có {item.get('image_count') or 0} ảnh attachment; "
                        + ("đang ở Ready for AI." if in_ready else "app sẽ chạy trực tiếp card đã chọn, không tự lấy card khác.")
                    ),
                    "action": "set_trello_card",
                    "payload": {"value": value, "list_id": item.get("list_id") or ""},
                    "requires_confirmation": False,
                }
            )
        return refined[:10]

    def _local_user_assistant_reply(self, question: str, context: Dict[str, Any], ui_context: str = "") -> str:
        normalized = self._normalize_skill_token(f"{question} {ui_context}")
        context_summary = self._format_user_assistant_context(context, ui_context="")
        parts: List[str] = []

        if self._flow_operator_requested(f"{question} {ui_context}"):
            parts.append(
                "Flow AI Operator là lớp AI trong app dùng để hiểu yêu cầu của chủ nhân, viết prompt cho Google Flow, mở đúng project Flow và sắp thứ tự các bước Trello -> Sheet -> Flow -> Telegram -> Trello."
            )
            parts.append(
                "Nó không tự lấy secret từ chat. Khi cần tạo thật, app vẫn yêu cầu xác nhận trước khi chạy Auto Trello để tránh lấy nhầm card hoặc tạo hàng loạt ngoài ý muốn."
            )
        elif any(term in normalized for term in ("trello", "ready", "card", "list", "attachment", "anh", "nham")):
            parts.append(
                "Luồng Trello chuẩn là: app chỉ quét list Ready for AI, lấy ảnh attachment nằm trên chính card đó, để AI tự viết prompt, tạo ảnh bằng Flow, gửi Telegram duyệt, rồi upload ảnh đã duyệt về lại đúng card nguồn."
            )
            parts.append(
                "Nếu thấy lấy nhầm ảnh, hãy kiểm tra card có còn nằm trong Ready for AI không, card đó có attachment ảnh thật không, và bộ lọc/card ghim có trỏ đúng sản phẩm không."
            )
        elif any(term in normalized for term in ("sheet", "prompt", "active", "product", "loc")):
            parts.append(
                "Sheet không còn bắt buộc. Nếu chủ nhân không dán Sheet, AI sẽ tự viết prompt từ card Trello và attachment; nếu vẫn dùng Sheet thì Active=TRUE và Product_Key/Product_Name/Card_URL giúp khớp chính xác hơn."
            )
            parts.append(
                "Các dòng đã dùng nên được đánh dấu Used/Used_At nếu sheet có cột đó, để vòng lặp không chạy lại cùng prompt."
            )
        elif any(term in normalized for term in ("telegram", "duyet", "approve", "chap_thuan")):
            parts.append(
                "Ảnh tạo xong sẽ được gửi qua Telegram bằng bot đã lưu. Người dùng bấm duyệt, app đồng bộ quyết định đó, rồi mới upload ảnh được duyệt về Trello."
            )
            parts.append(
                "Nếu không thấy nút duyệt hoạt động, kiểm tra bot token, chat id, và bấm refresh/đồng bộ approval trong app."
            )
        elif any(term in normalized for term in ("flow", "google", "dang_nhap", "project", "recaptcha", "tao_anh", "edit")):
            parts.append(
                "Flow vẫn là nơi tạo/chỉnh ảnh chính. App mở project Flow bằng phiên trình duyệt đã đăng nhập, đẩy prompt và ảnh nguồn vào Flow, rồi chờ kết quả tải về."
            )
            parts.append(
                "Nếu Flow tạo ảnh mới thay vì chỉnh ảnh đã chọn, hãy kiểm tra module Trello Image Source có lấy được attachment không và chế độ tạo ảnh đang nhận reference image từ card."
            )
        elif any(term in normalized for term in ("windows", "mac", "ubuntu", "cai", "install", "chay")):
            parts.append(
                "App là web local nên chạy được trên macOS, Windows và Ubuntu nếu có Python 3.11+, Node để kiểm tra frontend, và Playwright browser được cài đúng thư mục."
            )
            parts.append(
                "Trên Windows nên chạy bằng PowerShell/venv, không phụ thuộc biến env thủ công vì Trello, Telegram và Gemini đều lưu được trong giao diện app."
            )
        else:
            parts.append(
                "Mình có thể hỗ trợ ngay trong app về Trello, Google Sheet, Google Flow, Telegram duyệt, lỗi vòng lặp và cách chạy hàng loạt. Với những việc app đã có nút sẵn, trợ lý sẽ đưa nút thực thi để làm luôn trong giao diện."
            )
            parts.append(
                "Để chạy đúng luồng, cần có card ở Ready for AI, ảnh attachment trên card, Flow đã đăng nhập, Telegram bot đã lưu, rồi bấm Auto Trello. Sheet prompt chỉ là tùy chọn."
            )

        parts.append(f"Trạng thái app hiện tại: {context_summary}")
        return "\n\n".join(parts)

    def _gemini_user_assistant_request(self, question: str, context_summary: str, fallback_answer: str) -> Dict[str, Any]:
        prompt_text = "\n".join(
            [
                "Bạn là trợ lý vận hành trong app Flow v2, trả lời bằng tiếng Việt dễ hiểu cho người không rành kỹ thuật.",
                "Nhiệm vụ: hướng dẫn người dùng dùng app tự động lấy ảnh từ Trello, để Flow AI Operator tự viết prompt, tạo/chỉnh ảnh bằng Google Flow, gửi Telegram duyệt, rồi lưu lại đúng card Trello.",
                "Nếu người dùng nói về AI của Flow, Flow AI, automation operator, hãy giải thích rằng app có Flow AI Operator: AI lập kế hoạch, viết prompt cho Google Flow và đưa các nút thao tác thật trong app.",
                "Bạn phải hiểu nguồn sản phẩm là attachment ảnh trên Trello card trong list Ready for AI. Prompt do AI viết tự động; Google Sheet/CSV/paste chỉ là tùy chọn nếu người dùng muốn prompt có sẵn.",
                "Nếu người dùng yêu cầu app làm việc gì, hãy nói app sẽ dùng các nút hành động kèm theo câu trả lời; không bịa hành động ngoài khả năng hiện có.",
                "Không yêu cầu người dùng dán secret vào chat. Không in API key, token, cookie hay biến môi trường.",
                "Trả lời ngắn, thực dụng, ưu tiên các bước người dùng bấm được trong giao diện.",
                "Nếu người dùng hỏi lỗi lấy nhầm ảnh, nhấn mạnh Ready for AI và attachment phải nằm trên chính card nguồn.",
                "Nếu trạng thái cho thấy thiếu cấu hình, nói rõ thiếu phần nào.",
                "Không dùng markdown bảng. Có thể dùng các dòng ngắn.",
                "",
                "Trạng thái app đã được lọc secret:",
                context_summary,
                "",
                "Câu hỏi người dùng:",
                question,
                "",
                "Bản trả lời nội bộ để tham khảo:",
                fallback_answer,
            ]
        )
        return {
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": {
                "temperature": 0.35,
                "topP": 0.9,
                "maxOutputTokens": 768,
            },
        }

    def _generate_user_assistant_with_gemini(self, question: str, context_summary: str, fallback_answer: str) -> str:
        api_key = self._gemini_api_key()
        if not api_key:
            raise RuntimeError("Chưa cấu hình Gemini.")

        model = self._gemini_model()
        payload = self._gemini_user_assistant_request(question, context_summary, fallback_answer)
        url = self.GEMINI_API_URL_TEMPLATE.format(model=quote(model, safe="._-"))
        request_obj = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )
        try:
            with urlopen(request_obj, timeout=self.GEMINI_TIMEOUT_S) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                error_payload = json.loads(exc.read().decode("utf-8"))
                message = str(error_payload.get("error", {}).get("message", "")).strip()
            except Exception:
                message = ""
            raise RuntimeError(message or f"Gemini API trả về HTTP {exc.code}.") from exc
        except URLError as exc:
            raise RuntimeError(f"Không gọi được Gemini: {exc.reason}") from exc

        answer = self._extract_gemini_text(body)
        if not answer:
            raise RuntimeError("Gemini không trả về nội dung trợ lý.")
        return answer

    def _trim_user_assistant_answer(self, answer: str) -> str:
        text = re.sub(r"\n{3,}", "\n\n", str(answer or "").strip())
        text = re.sub(r"(?i)^\s*draft\s*:\s*\*?\s*", "", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"(?m)^\s*[*-]\s+", "", text)
        if len(text) <= self.USER_ASSISTANT_ANSWER_LIMIT:
            return text
        clipped = text[: self.USER_ASSISTANT_ANSWER_LIMIT]
        boundary = max(clipped.rfind("\n"), clipped.rfind(". "), clipped.rfind("; "))
        if boundary > 500:
            return clipped[:boundary].rstrip(" .;") + "."
        return clipped.rstrip(" .;") + "."

    async def answer_user_assistant(self, request: UserAssistantRequest) -> Dict[str, Any]:
        question = re.sub(r"\s+", " ", str(request.question or "").strip())
        if not question:
            raise HTTPException(status_code=400, detail="Hãy nhập câu hỏi để trợ lý hỗ trợ.")
        question = question[:1000]
        ui_context = re.sub(r"\s+", " ", str(request.context or "").strip())[: self.USER_ASSISTANT_CONTEXT_LIMIT]

        context = self._user_assistant_context_snapshot()
        product_filter = self._extract_user_assistant_product_filter(question)
        trello_card_hint = self._extract_user_assistant_trello_card_hint(question)
        trello_candidates: List[Dict[str, Any]] = []
        trello_candidate_error = ""
        trello_candidate_scan_attempted = bool(product_filter and context.get("trello", {}).get("configured"))
        if trello_candidate_scan_attempted:
            try:
                trello_candidates = await asyncio.to_thread(self._user_assistant_trello_candidates, product_filter)
            except Exception as exc:
                trello_candidate_error = str(exc)[:180]
        if trello_candidate_scan_attempted:
            context["trello_candidate_scan"] = self._format_user_assistant_trello_candidate_context(trello_candidates, product_filter)
        context_summary = self._format_user_assistant_context(context, ui_context)
        local_answer = self._local_user_assistant_reply(question, context, ui_context)
        actions = self._user_assistant_suggested_actions(question, context)
        actions = self._refine_user_assistant_actions_for_trello_candidates(
            actions,
            trello_candidates,
            trello_card_hint,
            scan_attempted=trello_candidate_scan_attempted,
            query=product_filter,
        )
        flow_operator_plan: Dict[str, Any] = {}
        if self._flow_operator_requested(question):
            try:
                flow_operator_plan = await self.plan_flow_operator(
                    FlowOperatorRequest(
                        instruction=question,
                        context=ui_context,
                        run_mode="auto" if self._flow_operator_wants_run(question) else "plan",
                    ),
                    use_gemini=False,
                )
                plan_actions = flow_operator_plan.get("suggested_actions") if isinstance(flow_operator_plan, dict) else []
                if isinstance(plan_actions, list):
                    actions = self._dedupe_assistant_actions([*plan_actions, *actions], limit=10)
            except Exception as exc:
                flow_operator_plan = {
                    "title": "Flow AI Operator",
                    "summary": f"Chưa lập được kế hoạch operator: {str(exc)[:160]}",
                    "steps": [],
                    "suggested_actions": [],
                }

        engine = "local"
        engine_label = "Nội bộ"
        model = ""
        answer = local_answer
        fallback_reason = ""

        if self._gemini_api_key():
            model = self._gemini_model()
            try:
                answer = await asyncio.to_thread(
                    self._generate_user_assistant_with_gemini,
                    question,
                    context_summary,
                    local_answer,
                )
                engine = "gemini"
                engine_label = "Gemini"
            except Exception as exc:
                fallback_reason = str(exc)[:180]
                model = ""
        answer = self._append_user_assistant_trello_candidate_notice(
            answer,
            trello_candidates,
            product_filter,
            scan_attempted=trello_candidate_scan_attempted,
        )

        return {
            "answer": self._trim_user_assistant_answer(answer),
            "engine": engine,
            "engine_label": engine_label,
            "model": model,
            "suggested_actions": actions,
            "flow_operator_plan": flow_operator_plan,
            "trello_candidates": trello_candidates,
            "trello_candidates_error": trello_candidate_error,
            "context_summary": context_summary,
            "fallback_reason": fallback_reason,
        }

    def _gemini_api_key(self) -> str:
        configured = str(self.store.snapshot().integration_config.gemini_api_key or "").strip()
        if configured:
            return configured
        for key_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
            value = str(os.getenv(key_name, "")).strip()
            if value:
                return value
        return ""

    def _gemini_model(self) -> str:
        configured = str(self.store.snapshot().integration_config.gemini_model or "").strip()
        raw = configured or str(os.getenv("GEMINI_MODEL", self.GEMINI_DEFAULT_MODEL)).strip()
        return self._sanitize_gemini_model(raw)

    def _sanitize_gemini_model(self, value: str) -> str:
        raw = str(value or self.GEMINI_DEFAULT_MODEL).strip()
        sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "", raw)
        return sanitized or self.GEMINI_DEFAULT_MODEL

    def _prompt_skill_bucket(self, skill: SkillRecord) -> str:
        path = str(skill.source_path or "").lower().strip()
        name = str(skill.name or "").lower().strip()

        if path.startswith("guides/prompting/") or "prompt" in name:
            return "prompting"
        if path.startswith("guides/video/") or path.startswith("tools/video/"):
            return "video"
        if path.startswith("guides/photo/") or path.startswith("tools/image/"):
            return "image"
        if path.startswith("guides/design/"):
            return "design"
        return "other"

    def _prompt_relevant_skills(self, skills: List[SkillRecord]) -> List[SkillRecord]:
        selected: List[SkillRecord] = []
        for skill in skills:
            path = str(skill.source_path or "").lower()
            name = str(skill.name or "").lower()
            if any(path.startswith(prefix) for prefix in self.PROMPT_SKILL_PREFIXES):
                selected.append(skill)
                continue
            if any(
                token in name
                for token in (
                    "prompt",
                    "image",
                    "video",
                    "photo",
                    "storyboard",
                    "veo",
                    "thumbnail",
                    "design",
                    "marketing",
                    "avatar",
                    "landing",
                    "cover",
                    "screenshot",
                    "logo",
                )
            ):
                selected.append(skill)
        return selected

    def _skill_targets_mode(self, skill: SkillRecord, mode: str) -> bool:
        path = str(skill.source_path or "").lower()
        name = str(skill.name or "").lower()
        bucket = self._prompt_skill_bucket(skill)
        if bucket == "prompting":
            return True
        if mode == "image":
            if bucket in {"image", "design"}:
                return True
            return any(
                token in path or token in name
                for token in ("image", "photo", "thumbnail", "og-image", "design", "cover", "logo", "landing", "screenshot")
            )
        if bucket == "video":
            return True
        return any(
            token in path or token in name
            for token in ("video", "veo", "storyboard", "avatar", "marketing", "explainer", "talking-head", "remotion")
        )

    def _prompt_tokens(self, value: str) -> List[str]:
        lowered = self._normalize_skill_token(value or "")
        tokens = [token for token in re.split(r"[^a-z0-9]+", lowered) if len(token) >= 3]
        stop_words = {"cho", "cua", "the", "and", "with", "this", "that", "from", "tren", "duoi", "mot", "nhung", "video", "image", "prompt"}
        return [token for token in tokens if token not in stop_words]

    def _select_prompt_skills(self, mode: str, brief: str, style: str = "", must_include: str = "") -> List[SkillRecord]:
        relevant = self._prompt_relevant_skills(self.store.snapshot().skills)
        if not relevant:
            return []

        query_tokens = set(self._prompt_tokens(" ".join([brief, style, must_include])))
        scored: List[tuple[int, SkillRecord]] = []
        for skill in relevant:
            score = 0
            path = str(skill.source_path or "").lower()
            combined = " ".join([skill.name, skill.summary, skill.source_path, skill.skill_text[:800]])
            normalized = self._normalize_skill_token(combined)
            bucket = self._prompt_skill_bucket(skill)

            if self._skill_targets_mode(skill, mode):
                score += 6
            if bucket == "prompting":
                score += 5
            if mode == "image" and bucket == "design":
                score += 4
            if mode == "image" and any(token in path for token in ("thumbnail", "og-image", "product-photography", "book-cover", "landing-page", "app-store")):
                score += 4
            if mode == "video" and any(token in path for token in ("google-veo", "ai-video-generation", "video-prompting-guide", "storyboard")):
                score += 5
            if mode == "video" and any(token in path for token in ("explainer-video-guide", "talking-head-production", "video-ad-specs", "ai-marketing-videos")):
                score += 4
            if mode == "image" and any(token in path for token in ("ai-image-generation", "product-photography", "photo", "nano-banana")):
                score += 5
            overlap = sum(1 for token in query_tokens if token in normalized)
            score += min(overlap, 8)
            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda item: (-item[0], item[1].name.lower()))
        return [skill for _, skill in scored[:6]]

    def _style_fragments_from_skills(self, mode: str, skills: List[SkillRecord]) -> List[str]:
        fragments: List[str] = []
        for skill in skills:
            path = str(skill.source_path or "").lower()
            if mode == "video":
                if "prompt-engineering" in path:
                    fragments.extend(["clear subject-action-environment", "specific visual language"])
                if "video-prompting-guide" in path:
                    fragments.extend(["cinematic framing", "clear shot design", "controlled lighting"])
                if "google-veo" in path:
                    fragments.extend(["natural motion", "coherent subject consistency", "high fidelity detail"])
                if "storyboard-creation" in path:
                    fragments.extend(["clear visual beats", "readable action progression"])
                if "ai-marketing-videos" in path:
                    fragments.extend(["polished commercial look", "brand-safe composition"])
                if "explainer-video-guide" in path:
                    fragments.extend(["clear narrative progression", "easy-to-read scene intent"])
                if "talking-head-production" in path:
                    fragments.extend(["natural presenter framing", "clean eye-line composition"])
                if "video-ad-specs" in path:
                    fragments.extend(["strong hook in first seconds", "short-form ad pacing"])
            else:
                if "prompt-engineering" in path:
                    fragments.extend(["specific subject description", "clear visual hierarchy"])
                if "ai-image-generation" in path:
                    fragments.extend(["photorealistic detail", "clean composition"])
                if "product-photography" in path:
                    fragments.extend(["premium product photography", "studio reflections", "commercial polish"])
                if "nano-banana" in path or "qwen-image" in path or "flux-image" in path:
                    fragments.extend(["sharp subject detail", "rich texture rendering"])
                if "og-image-design" in path:
                    fragments.extend(["strong focal hierarchy"])
                if "youtube-thumbnail-design" in path:
                    fragments.extend(["high-contrast focal subject", "immediate visual read"])
                if "book-cover-design" in path:
                    fragments.extend(["hero-led cover composition", "dramatic visual focus"])
                if "landing-page-design" in path or "app-store-screenshots" in path:
                    fragments.extend(["clean commercial presentation", "clear feature-first composition"])
                if "logo-design-guide" in path:
                    fragments.extend(["iconic silhouette", "simple memorable shapes"])
        seen: set[str] = set()
        unique: List[str] = []
        for item in fragments:
            lowered = item.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            unique.append(item)
        return unique[:6]

    def _video_shot_hint(self, brief: str, style: str) -> str:
        text = self._normalize_skill_token(f"{brief} {style}")
        if any(token in text for token in ("product", "san_pham", "watch", "phone", "chuoi")):
            return "Cinematic product hero shot"
        if any(token in text for token in ("city", "thanh_pho", "landscape", "canh_quan", "room", "phong")):
            return "Wide cinematic establishing shot"
        if any(token in text for token in ("person", "human", "nguoi", "piano", "cat", "meo", "dog", "cho")):
            return "Medium cinematic shot"
        return "Cinematic medium-wide shot"

    def _image_framing_hint(self, brief: str, style: str) -> str:
        text = self._normalize_skill_token(f"{brief} {style}")
        if any(token in text for token in ("product", "san_pham", "bottle", "watch", "phone", "food", "chuoi")):
            return "Commercial product hero shot"
        if any(token in text for token in ("portrait", "face", "nguoi", "person", "fashion")):
            return "Editorial portrait composition"
        return "Detailed hero composition"

    def _lighting_hint(self, brief: str, style: str) -> str:
        text = self._normalize_skill_token(f"{brief} {style}")
        if any(token in text for token in ("night", "dem", "neon", "cyber", "futuristic")):
            return "neon cinematic lighting"
        if any(token in text for token in ("sunset", "hoang_hon", "golden", "warm", "am")):
            return "warm golden hour lighting"
        if any(token in text for token in ("dark", "toi", "dramatic", "moody")):
            return "dramatic low-key lighting"
        if any(token in text for token in ("studio", "san_pham", "product")):
            return "soft studio lighting"
        return "soft natural lighting"

    def _mood_hint(self, brief: str, style: str) -> str:
        text = self._normalize_skill_token(f"{brief} {style}")
        if any(token in text for token in ("luxury", "premium", "sang_trong", "elegant", "editorial")):
            return "premium refined mood"
        if any(token in text for token in ("dark", "toi", "dramatic", "moody", "thriller")):
            return "dramatic moody atmosphere"
        if any(token in text for token in ("cute", "de_thuong", "playful", "fun", "happy")):
            return "playful friendly mood"
        if any(token in text for token in ("battle", "fight", "samurai", "action", "epic")):
            return "tense high-energy atmosphere"
        return "cinematic polished atmosphere"

    def _video_camera_hint(self, brief: str, style: str) -> str:
        text = self._normalize_skill_token(f"{brief} {style}")
        if any(token in text for token in ("product", "san_pham", "watch", "phone", "bottle")):
            return "hero product framing with a slow dolly-in, controlled parallax, and crisp focus transitions"
        if any(token in text for token in ("fight", "battle", "samurai", "action", "combat")):
            return "dynamic cinematic coverage with a low-angle hero frame, readable action geography, and subtle camera drift"
        if any(token in text for token in ("portrait", "person", "human", "nguoi", "piano", "cat", "meo", "dog", "cho")):
            return "medium cinematic framing with a natural lens feel, gentle push-in, and clear subject separation"
        return "cinematic framing with layered depth, subtle movement, and a strong focal path through the frame"

    def _video_detail_fragments(self, brief: str, style: str) -> List[str]:
        text = self._normalize_skill_token(f"{brief} {style}")
        details = [
            "clear subject, action, and environment relationship",
            "layered foreground midground and background depth",
            "cohesive color palette with believable contrast",
            "consistent subject identity across the full clip",
            "high texture fidelity and realistic material response",
            "clean frame edges with strong focal hierarchy",
            "polished cinematic color grading",
            "each moment should feel usable as a hero frame",
        ]
        if any(token in text for token in ("person", "human", "nguoi", "portrait", "face")):
            details.extend([
                "natural facial expression and believable anatomy",
                "subtle secondary motion in hair, fabric, and small gestures",
            ])
        if any(token in text for token in ("water", "ocean", "river", "pond", "lake", "koi")):
            details.extend([
                "realistic water caustics, ripples, and reflected highlights",
                "smooth underwater or surface-adjacent motion with convincing fluid behavior",
            ])
        if any(token in text for token in ("battle", "fight", "samurai", "action", "combat")):
            details.extend([
                "clear action beats with readable staging",
                "impactful motion arcs, debris, cloth movement, and environmental reaction",
            ])
        return details[:10]

    def _image_detail_fragments(self, brief: str, style: str) -> List[str]:
        text = self._normalize_skill_token(f"{brief} {style}")
        details = [
            "clean subject separation from the background",
            "high micro-detail and believable material texture",
            "refined highlights, shadows, and edge contrast",
            "strong focal hierarchy with uncluttered composition",
            "realistic depth and dimensionality",
            "polished commercial-grade finish",
        ]
        if any(token in text for token in ("product", "san_pham", "watch", "phone", "bottle", "headphone", "tai_nghe")):
            details.extend([
                "premium product presentation with controlled reflections",
                "precise surface definition on metal, glass, plastic, or fabric",
            ])
        if any(token in text for token in ("portrait", "person", "human", "nguoi", "fashion", "face")):
            details.extend([
                "sharp eye focus and flattering facial structure",
                "natural skin texture without waxy rendering",
            ])
        return details[:8]

    def _aspect_phrase(self, aspect: str, mode: str) -> str:
        normalized = str(aspect or "").strip().lower()
        if normalized == "portrait":
            return "vertical 9:16 framing" if mode == "video" else "vertical 9:16 composition"
        if normalized == "square":
            return "square 1:1 composition"
        return "wide 16:9 framing" if mode == "video" else "wide 16:9 composition"

    def _compose_prompt_draft(self, request: PromptCreateRequest, skills: List[SkillRecord]) -> str:
        mode = self._parse_skill_type(request.mode)
        brief = request.brief.strip()
        style = request.style.strip()
        must_include = request.must_include.strip()
        avoid = request.avoid.strip()
        audience = request.audience.strip()
        aspect = request.aspect.strip() or ("square" if mode == "image" else "landscape")
        fragments = self._style_fragments_from_skills(mode, skills)
        lighting = self._lighting_hint(brief, style)
        mood = self._mood_hint(brief, style)
        aspect_phrase = self._aspect_phrase(aspect, mode)

        if mode == "video":
            opening = self._video_shot_hint(brief, style)
            parts = [
                opening,
                brief,
                f"visual style {style}" if style else "cinematic premium visual treatment",
                f"lighting is {lighting}",
                f"mood is {mood}",
                aspect_phrase,
                self._video_camera_hint(brief, style),
                "smooth realistic motion with stable temporal consistency",
                "professional cinematography with believable depth of field",
            ]
            parts.extend(self._video_detail_fragments(brief, style))
        else:
            opening = self._image_framing_hint(brief, style)
            parts = [
                opening,
                brief,
                f"visual style {style}" if style else "polished premium still-image treatment",
                f"lighting is {lighting}",
                f"mood is {mood}",
                aspect_phrase,
                "photorealistic detail with controlled composition",
                "clear hero subject with strong visual hierarchy",
            ]
            parts.extend(self._image_detail_fragments(brief, style))

        if must_include:
            parts.append(f"must include {must_include}")
        if audience:
            parts.append(f"optimized for {audience}")
        parts.extend(fragments)
        prompt = ", ".join([part.strip() for part in parts if part and part.strip()])
        if avoid:
            prompt = f"{prompt}. Avoid {avoid.strip()}."
        return prompt.strip()

    def _gemini_skill_guidance(self, skills: List[SkillRecord]) -> str:
        lines: List[str] = []
        for skill in skills[:6]:
            summary = str(skill.summary or "").strip()
            if not summary:
                summary = str(skill.source_path or "").strip()
            if not summary:
                summary = "Không có mô tả ngắn."
            lines.append(f"- {skill.name}: {summary}")
        return "\n".join(lines)

    def _clean_prompt_text(self, value: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = re.sub(r"^(final prompt|prompt)\s*:\s*", "", text, flags=re.IGNORECASE)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        cleaned = " ".join(lines).strip()
        return cleaned.strip("\"' ")

    def _extract_gemini_text(self, payload: Dict[str, Any]) -> str:
        candidates = payload.get("candidates") or []
        for candidate in candidates:
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                text = self._clean_prompt_text(part.get("text") or "")
                if text:
                    return text
        return ""

    def _ensure_prompt_detail(self, prompt: str, baseline: str, mode: str) -> tuple[str, bool]:
        candidate = self._clean_prompt_text(prompt)
        fallback = self._clean_prompt_text(baseline)
        minimum_chars = 220 if mode == "video" else 180
        signal_count = sum(candidate.count(token) for token in (",", ".", ";", ":"))

        if candidate and len(candidate) >= minimum_chars and signal_count >= 4:
            return candidate, False

        if not fallback:
            return candidate, False

        if not candidate or len(candidate) < int(minimum_chars * 0.6) or signal_count < 2:
            merged = fallback
        elif candidate.lower() not in fallback.lower():
            merged = f"{candidate}. {fallback}"
        else:
            merged = fallback

        merged = re.sub(r"\s+", " ", merged).strip()
        max_chars = 900 if mode == "video" else 720
        if len(merged) > max_chars:
            clipped = merged[:max_chars]
            last_stop = max(clipped.rfind("."), clipped.rfind(";"), clipped.rfind(","))
            if last_stop > int(minimum_chars * 0.6):
                merged = clipped[:last_stop].rstrip(" ,.;") + "."
            else:
                merged = clipped.rstrip(" ,.;") + "."
        return merged, merged != candidate

    def _gemini_prompt_request(self, request: PromptCreateRequest, skills: List[SkillRecord], baseline: str) -> Dict[str, Any]:
        mode = self._parse_skill_type(request.mode)
        aspect = request.aspect.strip() or ("square" if mode == "image" else "landscape")
        guidance = self._gemini_skill_guidance(skills) or "- Không có skill đặc biệt, chỉ cần viết prompt rõ ràng."
        prompt_text = "\n".join(
            [
                "Bạn là chuyên gia viết prompt cho Google Flow.",
                "Hãy trả về duy nhất một prompt hoàn chỉnh, không markdown, không giải thích, không gạch đầu dòng.",
                "Viết cùng ngôn ngữ với brief gốc của người dùng.",
                "Prompt phải cực kỳ chi tiết, production-ready, giàu hình ảnh và có thể dán chạy ngay.",
                f"Chế độ: {mode}",
                f"Tỉ lệ: {aspect}",
                f"Ý chính người dùng: {request.brief.strip()}",
                f"Phong cách: {request.style.strip() or 'Không ghi rõ'}",
                f"Phải có: {request.must_include.strip() or 'Không ghi rõ'}",
                f"Tránh: {request.avoid.strip() or 'Không ghi rõ'}",
                f"Dành cho ai: {request.audience.strip() or 'Không ghi rõ'}",
                "Hướng dẫn rút ra từ kho skill:",
                guidance,
                "Bản nháp nội bộ hiện có để cải thiện thêm:",
                baseline,
                "Nếu là video, hãy làm rõ chủ thể, hành động, bối cảnh, lớp không gian, camera, nhịp chuyển động, ánh sáng, chất liệu, continuity, và cảm giác dựng hình.",
                "Nếu là ảnh, hãy làm rõ chủ thể, bố cục, góc máy, ánh sáng, bảng màu, vật liệu/chất liệu, chiều sâu, và điểm nhấn thị giác.",
                "Nếu người dùng chưa nói đủ, hãy tự bổ sung các chi tiết hỗ trợ hợp lý nhưng không đổi ý chính.",
                "Không xưng hô với người dùng trong prompt. Không nhắc tới việc bạn là AI. Không viết kiểu meta.",
                "Ưu tiên một prompt dày thông tin, cô đọng nhưng nhiều tín hiệu thị giác, thường dài khoảng 90 đến 180 từ.",
            ]
        )
        return {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt_text,
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.85,
                "topP": 0.95,
                "maxOutputTokens": 768,
            },
        }

    def _generate_prompt_with_gemini(self, request: PromptCreateRequest, skills: List[SkillRecord], baseline: str) -> str:
        api_key = self._gemini_api_key()
        if not api_key:
            raise RuntimeError("Chưa cấu hình GEMINI_API_KEY.")

        model = self._gemini_model()
        payload = self._gemini_prompt_request(request, skills, baseline)
        url = self.GEMINI_API_URL_TEMPLATE.format(model=quote(model, safe="._-"))
        request_obj = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )
        try:
            with urlopen(request_obj, timeout=self.GEMINI_TIMEOUT_S) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                error_payload = json.loads(exc.read().decode("utf-8"))
                message = str(error_payload.get("error", {}).get("message", "")).strip()
            except Exception:
                message = ""
            raise RuntimeError(message or f"Gemini API trả về HTTP {exc.code}.") from exc
        except URLError as exc:
            raise RuntimeError(f"Không gọi được Gemini: {exc.reason}") from exc

        prompt = self._extract_gemini_text(body)
        if not prompt:
            raise RuntimeError("Gemini không trả về prompt text.")
        return prompt

    async def generate_prompt_draft(self, request: PromptCreateRequest) -> Dict[str, Any]:
        brief = str(request.brief or "").strip()
        if not brief:
            raise HTTPException(status_code=400, detail="Hãy nói ngắn gọn điều muốn tạo trước.")

        await self.ensure_media_skill_library()
        mode = self._parse_skill_type(request.mode)
        selected = self._select_prompt_skills(mode, brief, request.style, request.must_include)
        baseline_prompt = self._compose_prompt_draft(request, selected)
        prompt = baseline_prompt
        prompt, expanded_prompt = self._ensure_prompt_detail(prompt, baseline_prompt, mode)
        engine = "local"
        engine_label = "Nội bộ"
        model = ""
        summary = (
            f"Gemini chưa bật, đang dùng bộ viết prompt nội bộ với {len(selected)} skill để mở rộng prompt chi tiết."
            if selected
            else "Gemini chưa bật, đang dùng công thức prompt nội bộ mặc định."
        )
        if self._gemini_api_key():
            try:
                prompt = await asyncio.to_thread(self._generate_prompt_with_gemini, request, selected, baseline_prompt)
                prompt, expanded_prompt = self._ensure_prompt_detail(prompt, baseline_prompt, mode)
                engine = "gemini"
                engine_label = "Gemini"
                model = self._gemini_model()
                summary = (
                    f"Gemini {model} đã viết prompt chi tiết này với {len(selected)} skill nền."
                    if selected
                    else f"Gemini {model} đã viết prompt chi tiết này."
                )
            except Exception:
                model = self._gemini_model()
                summary = (
                    f"Gemini {model} chưa phản hồi ổn định, đã rơi về bộ viết prompt nội bộ với {len(selected)} skill."
                    if selected
                    else f"Gemini {model} chưa phản hồi ổn định, đã rơi về bộ viết prompt nội bộ."
                )
        if expanded_prompt:
            if engine == "gemini":
                summary = f"{summary} App đã bổ sung thêm chi tiết từ skill nền để prompt đầy đủ hơn."
            else:
                summary = f"{summary} Prompt đã được mở rộng thêm chi tiết từ bộ skill nền."
        title = "Prompt video" if mode == "video" else "Prompt ảnh"
        if engine == "gemini":
            title = f"{title} Gemini"
        return {
            "title": title,
            "mode": mode,
            "prompt": prompt,
            "applied_skills": [skill.name for skill in selected],
            "skill_count": len(self._prompt_relevant_skills(self.store.snapshot().skills)),
            "summary": summary,
            "aspect": request.aspect.strip() or ("square" if mode == "image" else "landscape"),
            "engine": engine,
            "engine_label": engine_label,
            "model": model,
        }

    def _storyboard_scene_count(self, script: str, requested: int) -> int:
        try:
            explicit = int(requested or 0)
        except (TypeError, ValueError):
            explicit = 0
        if explicit > 0:
            return max(1, min(8, explicit))

        normalized = str(script or "").replace("\r\n", "\n").replace("\r", "\n")
        paragraphs = [block.strip() for block in re.split(r"\n\s*\n+", normalized) if block.strip()]
        sentences = [
            segment.strip()
            for segment in re.split(r"(?<=[.!?…])\s+|\n+", normalized)
            if segment.strip()
        ]
        rough = len(paragraphs) if len(paragraphs) >= 2 else len(sentences)
        if rough <= 0:
            rough = 4
        if rough == 1 and len(normalized) > 480:
            rough = 4
        return max(1, min(8, rough))

    def _storyboard_clean_unit(self, value: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r"^\s*(?:[-*•]+|\d+[\).:\-])\s*", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _storyboard_segments(self, script: str, scene_count: int) -> List[str]:
        normalized = str(script or "").replace("\r\n", "\n").replace("\r", "\n")
        paragraphs = [
            self._storyboard_clean_unit(block)
            for block in re.split(r"\n\s*\n+", normalized)
            if self._storyboard_clean_unit(block)
        ]
        sentences = [
            self._storyboard_clean_unit(segment)
            for segment in re.split(r"(?<=[.!?…])\s+|\n+", normalized)
            if self._storyboard_clean_unit(segment)
        ]
        units = paragraphs if len(paragraphs) >= max(2, min(scene_count, 3)) else sentences
        if not units:
            cleaned = self._storyboard_clean_unit(normalized)
            return [cleaned] if cleaned else []

        if len(units) == 1 and scene_count > 1:
            phase_labels = ["Mở đầu", "Phát triển", "Cao trào", "Chuyển cảnh", "Kết thúc"]
            return [
                f"{phase_labels[index] if index < len(phase_labels) else f'Nhịp {index + 1}'}: {units[0]}"
                for index in range(scene_count)
            ]

        target = max(1, min(scene_count, len(units)))
        buckets: List[List[str]] = [[] for _ in range(target)]
        total_units = max(1, len(units))
        for index, unit in enumerate(units):
            bucket_index = min(target - 1, (index * target) // total_units)
            buckets[bucket_index].append(unit)
        return [" ".join(bucket).strip() for bucket in buckets if bucket]

    def _storyboard_scene_title(self, beat: str, index: int) -> str:
        words = [token for token in re.split(r"\s+", re.sub(r"[^\w\sÀ-ỹ]", " ", str(beat or "").strip())) if token]
        if not words:
            return f"Cảnh {index}"
        headline = " ".join(words[:6]).strip()
        if len(words) > 6:
            headline = f"{headline}…"
        return headline[:1].upper() + headline[1:] if headline else f"Cảnh {index}"

    def _storyboard_continuity_note(self, request: StoryboardPlanRequest, index: int, total: int) -> str:
        note_parts = [
            "Giữ cùng nhân vật chính, trang phục, ánh sáng và thế giới hình ảnh xuyên suốt storyboard."
        ]
        must_include = str(request.must_include or "").strip()
        if must_include:
            note_parts.append(f"Luôn giữ các chi tiết bắt buộc: {must_include}.")
        if total > 1:
            note_parts.append(f"Đây là cảnh {index}/{total}, nên bố cục phải nối mượt với cảnh trước và cảnh sau.")
        return " ".join(note_parts)

    def _storyboard_scene_prompt(
        self,
        beat: str,
        request: StoryboardPlanRequest,
        skills: List[SkillRecord],
        index: int,
        total: int,
    ) -> str:
        style_parts = [str(request.style or "").strip(), "cinematic storyboard keyframe"]
        style = ", ".join([part for part in style_parts if part])
        must_include_parts = [
            str(request.must_include or "").strip(),
            "storyboard keyframe from a longer video sequence",
            f"scene {index} of {total}",
            "same subject identity, wardrobe, props, lighting direction, and environment continuity across the storyboard",
        ]
        must_include = ", ".join([part for part in must_include_parts if part])
        baseline = self._compose_prompt_draft(
            PromptCreateRequest(
                mode="image",
                brief=beat,
                style=style,
                must_include=must_include,
                avoid=str(request.avoid or "").strip(),
                audience=str(request.audience or "").strip(),
                aspect=self._parse_aspect(request.aspect or "landscape"),
            ),
            skills,
        )
        prompt, _ = self._ensure_prompt_detail(baseline, baseline, "image")
        return prompt

    def _parse_json_candidate(self, raw_text: str) -> Any:
        text = str(raw_text or "").strip()
        if not text:
            raise RuntimeError("Gemini không trả về nội dung storyboard.")

        candidates = [text]
        for block in re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL):
            cleaned = block.strip()
            if cleaned:
                candidates.append(cleaned)
        for opener, closer in (("{", "}"), ("[", "]")):
            start = text.find(opener)
            end = text.rfind(closer)
            if start != -1 and end > start:
                candidates.append(text[start : end + 1].strip())

        seen: set[str] = set()
        for candidate in candidates:
            key = candidate.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        raise RuntimeError("Gemini không trả về JSON storyboard hợp lệ.")

    def _storyboard_from_payload(
        self,
        payload: Any,
        request: StoryboardPlanRequest,
        scene_count: int,
        skills: List[SkillRecord],
    ) -> List[StoryboardScene]:
        raw_items = payload if isinstance(payload, list) else payload.get("scenes") or payload.get("items") or []
        if not isinstance(raw_items, list):
            raise RuntimeError("Payload storyboard không có danh sách cảnh.")

        scenes: List[StoryboardScene] = []
        for index, raw_item in enumerate(raw_items[:scene_count], start=1):
            if not isinstance(raw_item, dict):
                continue
            beat = str(
                raw_item.get("beat")
                or raw_item.get("summary")
                or raw_item.get("scene")
                or raw_item.get("description")
                or ""
            ).strip()
            prompt_text = str(
                raw_item.get("image_prompt")
                or raw_item.get("imagePrompt")
                or raw_item.get("prompt")
                or ""
            ).strip()
            if not beat and prompt_text:
                beat = prompt_text
            if not beat:
                continue
            title = str(raw_item.get("title") or "").strip() or self._storyboard_scene_title(beat, index)
            continuity = str(
                raw_item.get("continuity")
                or raw_item.get("continuity_note")
                or raw_item.get("continuityNote")
                or ""
            ).strip()
            baseline_prompt = self._storyboard_scene_prompt(beat, request, skills, index, scene_count)
            if prompt_text:
                prompt_text, _ = self._ensure_prompt_detail(prompt_text, baseline_prompt, "image")
            else:
                prompt_text = baseline_prompt
            if not continuity:
                continuity = self._storyboard_continuity_note(request, index, scene_count)
            scenes.append(
                StoryboardScene(
                    index=index,
                    title=title,
                    beat=beat,
                    image_prompt=prompt_text,
                    continuity=continuity,
                )
            )
        return scenes

    def _local_storyboard_plan(
        self,
        request: StoryboardPlanRequest,
        scene_count: int,
        skills: List[SkillRecord],
    ) -> List[StoryboardScene]:
        segments = self._storyboard_segments(request.script, scene_count)
        if not segments:
            return []

        scenes: List[StoryboardScene] = []
        total = min(scene_count, len(segments))
        for index, beat in enumerate(segments[:scene_count], start=1):
            scenes.append(
                StoryboardScene(
                    index=index,
                    title=self._storyboard_scene_title(beat, index),
                    beat=beat,
                    image_prompt=self._storyboard_scene_prompt(beat, request, skills, index, total),
                    continuity=self._storyboard_continuity_note(request, index, total),
                )
            )
        return scenes

    def _storyboard_skill_allowed(self, skill: SkillRecord) -> bool:
        path = str(skill.source_path or "").lower()
        if any(
            token in path
            for token in (
                "app-store",
                "landing-page",
                "book-cover",
                "og-image",
                "logo-design",
                "youtube-thumbnail",
            )
        ):
            return False
        return True

    def _gemini_storyboard_request(
        self,
        request: StoryboardPlanRequest,
        skills: List[SkillRecord],
        scene_count: int,
    ) -> Dict[str, Any]:
        guidance = self._gemini_skill_guidance(skills) or "- Không có skill đặc biệt, chỉ cần chia cảnh rõ ràng."
        aspect = self._parse_aspect(request.aspect or "landscape")
        prompt_text = "\n".join(
            [
                "Bạn là đạo diễn storyboard cho Google Flow.",
                "Hãy đọc kịch bản bên dưới và tách thành các ảnh keyframe cần thiết để sau này dựng video.",
                f"Trả về đúng {scene_count} cảnh.",
                "Chỉ trả về JSON hợp lệ, không markdown, không giải thích thêm.",
                'Schema bắt buộc: {"scenes":[{"title":"...","beat":"...","image_prompt":"...","continuity":"..."}]}',
                "Mỗi beat là mô tả ngắn của cảnh bằng ngôn ngữ người dùng đang dùng.",
                "Mỗi image_prompt phải là prompt ảnh cực kỳ chi tiết, dán chạy được ngay trên Flow, giàu thông tin thị giác, nhấn mạnh đây là keyframe của một video dài hơn.",
                "Phải giữ continuity chặt giữa các cảnh: cùng nhân vật, phục trang, đạo cụ, ánh sáng, bối cảnh, hướng chuyển động và mood.",
                f"Tỉ lệ ưu tiên: {self._aspect_phrase(aspect, 'image')}",
                f"Phong cách chung: {str(request.style or '').strip() or 'cinematic storyboard keyframe'}",
                f"Phải có: {str(request.must_include or '').strip() or 'Không ghi rõ'}",
                f"Tránh: {str(request.avoid or '').strip() or 'Không ghi rõ'}",
                f"Dành cho ai: {str(request.audience or '').strip() or 'Không ghi rõ'}",
                "Hướng dẫn rút ra từ kho skill:",
                guidance,
                "Kịch bản nguồn:",
                str(request.script or "").strip(),
            ]
        )
        return {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt_text,
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.8,
                "topP": 0.95,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
            },
        }

    def _generate_storyboard_with_gemini(
        self,
        request: StoryboardPlanRequest,
        skills: List[SkillRecord],
        scene_count: int,
    ) -> List[StoryboardScene]:
        api_key = self._gemini_api_key()
        if not api_key:
            raise RuntimeError("Chưa cấu hình GEMINI_API_KEY.")

        model = self._gemini_model()
        payload = self._gemini_storyboard_request(request, skills, scene_count)
        url = self.GEMINI_API_URL_TEMPLATE.format(model=quote(model, safe="._-"))
        request_obj = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )
        try:
            with urlopen(request_obj, timeout=self.GEMINI_TIMEOUT_S) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                error_payload = json.loads(exc.read().decode("utf-8"))
                message = str(error_payload.get("error", {}).get("message", "")).strip()
            except Exception:
                message = ""
            raise RuntimeError(message or f"Gemini API trả về HTTP {exc.code}.") from exc
        except URLError as exc:
            raise RuntimeError(f"Không gọi được Gemini: {exc.reason}") from exc

        text = self._extract_gemini_text(body)
        parsed = self._parse_json_candidate(text)
        scenes = self._storyboard_from_payload(parsed, request, scene_count, skills)
        if not scenes:
            raise RuntimeError("Gemini không trả về cảnh storyboard hợp lệ.")
        return scenes

    async def plan_storyboard(self, request: StoryboardPlanRequest) -> Dict[str, Any]:
        script = str(request.script or "").strip()
        if not script:
            raise HTTPException(status_code=400, detail="Hãy dán kịch bản trước khi tách cảnh.")

        await self.ensure_media_skill_library()
        normalized_request = StoryboardPlanRequest(
            script=script,
            style=str(request.style or "").strip(),
            must_include=str(request.must_include or "").strip(),
            avoid=str(request.avoid or "").strip(),
            audience=str(request.audience or "").strip(),
            aspect=self._parse_aspect(request.aspect or "landscape"),
            scene_count=int(request.scene_count or 0),
        )
        scene_count = self._storyboard_scene_count(script, normalized_request.scene_count)

        selected: List[SkillRecord] = []
        seen_skills: set[str] = set()
        for skill in self._select_prompt_skills("video", script, normalized_request.style, normalized_request.must_include) + self._select_prompt_skills(
            "image",
            script,
            normalized_request.style,
            normalized_request.must_include,
        ):
            if not self._storyboard_skill_allowed(skill):
                continue
            key = str(skill.id or skill.name or "")
            if not key or key in seen_skills:
                continue
            seen_skills.add(key)
            selected.append(skill)

        fallback_scenes = self._local_storyboard_plan(normalized_request, scene_count, selected)
        scenes = fallback_scenes
        engine = "local"
        engine_label = "Nội bộ"
        model = ""
        summary = (
            f"Đã tách {len(fallback_scenes)} cảnh keyframe và viết prompt ảnh bằng bộ lập cảnh nội bộ."
        )

        if self._gemini_api_key():
            try:
                gemini_scenes = await asyncio.to_thread(
                    self._generate_storyboard_with_gemini,
                    normalized_request,
                    selected,
                    scene_count,
                )
                if len(gemini_scenes) < scene_count and len(fallback_scenes) > len(gemini_scenes):
                    gemini_scenes.extend(fallback_scenes[len(gemini_scenes) : scene_count])
                scenes = gemini_scenes[:scene_count]
                engine = "gemini"
                engine_label = "Gemini"
                model = self._gemini_model()
                summary = (
                    f"Gemini {model} đã tách {len(scenes)} cảnh và viết prompt ảnh storyboard để tạo video từ kịch bản này."
                )
            except Exception:
                model = self._gemini_model()
                summary = (
                    f"Gemini {model} chưa phản hồi ổn định, app đã rơi về bộ lập cảnh nội bộ và vẫn tách được {len(scenes)} cảnh."
                )

        if not scenes:
            raise HTTPException(status_code=400, detail="Kịch bản này chưa đủ rõ để tách thành các cảnh ảnh.")

        return {
            "title": "Storyboard ảnh từ kịch bản",
            "summary": summary,
            "scene_count": len(scenes),
            "aspect": normalized_request.aspect,
            "engine": engine,
            "engine_label": engine_label,
            "model": model,
            "applied_skills": [skill.name for skill in selected],
            "items": [_model_dump(scene) for scene in scenes],
        }

    async def sync_media_skills(self) -> Dict[str, Any]:
        try:
            entries = await asyncio.to_thread(self._media_skill_repo_entries)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Không quét được kho skill: {exc}") from exc

        imported: List[SkillRecord] = []
        skipped: List[str] = []
        for entry in entries:
            try:
                fetched = await asyncio.to_thread(self._download_skill_text, entry["download_url"])
                skill = await self.create_skill(
                    self._build_imported_skill_request(
                        self._name_from_path(entry["path"]) or "Skill media",
                        f"Đồng bộ từ {entry['html_url']}",
                        fetched["text"],
                        entry["path"],
                        source_repo=self.MEDIA_SKILL_REPO,
                        source_path=entry["path"],
                        source_url=entry["html_url"],
                        is_builtin=True,
                    )
                )
                imported.append(skill)
            except HTTPException as exc:
                skipped.append(f"{entry['path']}: {exc.detail}")
            except Exception as exc:
                skipped.append(f"{entry['path']}: {exc}")

        if not imported:
            raise HTTPException(status_code=400, detail="Chưa đồng bộ được skill nào từ repo nguồn.")

        imported.sort(key=lambda skill: (skill.type, skill.name.lower()))
        await self.store.replace_skills(imported)
        return {
            "items": [self._public_skill_payload(skill) for skill in imported],
            "imported_count": len(imported),
            "skipped_count": len(skipped),
            "skipped": skipped[:12],
            "mode": "sync",
            "source_url": self.MEDIA_SKILL_SOURCE_URL,
        }

    async def import_skill_from_url(self, request: SkillImportRequest) -> Dict[str, Any]:
        request = self._resolve_skill_import_request(request)
        raw_url = request.url.strip()
        if not raw_url:
            raise HTTPException(status_code=400, detail="Hãy nhập link, repo hoặc lệnh skills add.")

        github_source = self._parse_github_collection_url(raw_url)
        if github_source:
            return await self._import_skill_collection(github_source, request)

        skill = await self._import_single_skill(raw_url, request)
        return {
            "items": [skill],
            "imported_count": 1,
            "skipped_count": 0,
            "mode": "single",
            "source_url": raw_url,
        }

    async def _import_single_skill(self, raw_url: str, request: SkillImportRequest) -> SkillRecord:
        target_url = self._normalize_skill_source_url(raw_url)
        try:
            fetched = await asyncio.to_thread(self._download_skill_text, target_url)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Không tải được skill từ link này: {exc}") from exc

        name = request.name.strip() or self._name_from_url(fetched["url"])
        summary = request.summary.strip() or f"Tự tải từ link: {fetched['url']}"
        return await self.create_skill(self._build_imported_skill_request(name, summary, fetched["text"], fetched["url"]))

    async def _import_skill_collection(self, source: Dict[str, str], request: SkillImportRequest) -> Dict[str, Any]:
        selected_skills = self._normalize_selected_skills(request.skills)
        missing_requested: List[str] = []
        try:
            if selected_skills:
                selection = await asyncio.to_thread(
                    self._github_selected_skill_entries,
                    source["owner"],
                    source["repo"],
                    source["branch"],
                    source["path"],
                    selected_skills,
                )
                entries = selection["entries"]
                missing_requested = selection["missing"]
            else:
                entries = await asyncio.to_thread(
                    self._github_skill_file_entries,
                    source["owner"],
                    source["repo"],
                    source["branch"],
                    source["path"],
                )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Không quét được repo/thư mục skill: {exc}") from exc

        if not entries:
            if selected_skills:
                missing_text = ", ".join(f'"{skill}"' for skill in missing_requested or selected_skills)
                raise HTTPException(status_code=400, detail=f"Không tìm thấy skill {missing_text} trong repo này.")
            raise HTTPException(status_code=400, detail="Không tìm thấy file skill phù hợp trong repo/thư mục này.")

        existing_signatures = {
            self._skill_signature(skill.name, skill.skill_text or skill.prompt)
            for skill in self.store.snapshot().skills
        }

        imported: List[SkillRecord] = []
        skipped: List[str] = []
        name_prefix = request.name.strip()
        summary_prefix = request.summary.strip()

        for skill_name in missing_requested:
            skipped.append(f"{skill_name}: không tìm thấy skill này trong repo.")

        for entry in entries:
            try:
                fetched = await asyncio.to_thread(self._download_skill_text, entry["download_url"])
                if not self._looks_like_skill_text(fetched["text"], entry["path"]):
                    skipped.append(f"{entry['path']}: nội dung không giống skill.")
                    continue

                base_name = self._name_from_path(entry["path"]) or self._name_from_url(entry["download_url"]) or "Skill mới"
                final_name = f"{name_prefix} / {base_name}" if name_prefix else base_name
                signature = self._skill_signature(final_name, fetched["text"])
                if signature in existing_signatures:
                    skipped.append(f"{entry['path']}: đã có trong thư viện.")
                    continue

                summary = summary_prefix or f"Tự tải từ {entry['html_url']}"
                skill = await self.create_skill(self._build_imported_skill_request(final_name, summary, fetched["text"], entry["path"]))
                imported.append(skill)
                existing_signatures.add(signature)
            except HTTPException as exc:
                skipped.append(f"{entry['path']}: {exc.detail}")
            except Exception as exc:
                skipped.append(f"{entry['path']}: {exc}")

        if not imported:
            raise HTTPException(
                status_code=400,
                detail="Bot chưa import được skill nào từ repo/thư mục này. Hãy thử dùng thư mục chứa các file skill rõ ràng hơn.",
            )

        return {
            "items": imported,
            "imported_count": len(imported),
            "skipped_count": len(skipped),
            "skipped": skipped[:12],
            "mode": "batch",
            "source_url": source["source_url"],
        }

    def _resolve_skill_import_request(self, request: SkillImportRequest) -> SkillImportRequest:
        raw_source = request.url.strip()
        command = request.command.strip()
        name = request.name.strip()
        summary = request.summary.strip()
        selected_skills = self._normalize_selected_skills(request.skills)

        parsed_command: Dict[str, Any] = {}
        command_input = command or (raw_source if self._looks_like_skill_add_command(raw_source) else "")
        if command_input:
            parsed_command = self._parse_skill_add_command(command_input)
            raw_source = parsed_command.get("url", "") or raw_source
            selected_skills = self._normalize_selected_skills(parsed_command.get("skills", []) + selected_skills)
            if not name:
                name = parsed_command.get("name", "")
            if not summary:
                summary = parsed_command.get("summary", "")

        raw_source = self._normalize_skill_source_input(raw_source)

        return SkillImportRequest(
            url=raw_source,
            command=command_input,
            name=name,
            summary=summary,
            skills=selected_skills,
        )

    def _build_imported_skill_request(
        self,
        name: str,
        summary: str,
        skill_text: str,
        source_hint: str,
        *,
        source_repo: str = "",
        source_path: str = "",
        source_url: str = "",
        is_builtin: bool = False,
    ) -> SkillCreateRequest:
        if self._looks_like_instructional_skill_doc(skill_text, source_hint):
            inferred_type = self._infer_skill_type_from_hint(f"{name}\n{source_hint}") or "video"
            return SkillCreateRequest(
                name=name,
                summary=summary,
                skill_text=skill_text,
                source_repo=source_repo,
                source_path=source_path,
                source_url=source_url,
                is_builtin=is_builtin,
                type=inferred_type,
                prompt="",
                aspect="landscape",
                count=1,
                reference_media_names=[],
                media_id="",
                workflow_id="",
                motion="",
                position="",
                resolution="1080p",
                mask_x=0.5,
                mask_y=0.5,
                brush_size=40,
            )

        return SkillCreateRequest(
            name=name,
            summary=summary,
            skill_text=skill_text,
            source_repo=source_repo,
            source_path=source_path,
            source_url=source_url,
            is_builtin=is_builtin,
        )

    async def delete_skill(self, skill_id: str) -> None:
        deleted = await self.store.delete_skill(skill_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Không tìm thấy kỹ năng.")

    async def download_artifact(self, job_id: str, request: DownloadRequest) -> Dict[str, Any]:
        job, artifact = self._get_artifact_or_raise(job_id, request.artifact_index)
        source = artifact.url
        if not source:
            raise HTTPException(status_code=400, detail="Kết quả này chưa có liên kết tải xuống.")

        file_name = self._download_name(job, artifact, request.artifact_index)
        destination = self._download_root() / file_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        await self.store.append_log(job_id, f"Đang lưu kết quả vào {destination.name}")

        async def _go(client: Any) -> str:
            saved = await client.download(source, destination)
            return str(saved)

        job_input = job.input if isinstance(job.input, dict) else {}
        local_path = await self._with_client(_go, workflow_id=artifact.workflow_id or job_input.get("workflow_id", ""))
        artifact.local_path = local_path
        artifact.public_url = self._public_download_url(local_path)
        await self.store.replace_artifacts(job_id, job.artifacts)
        return {
            "path": local_path,
            "public_url": artifact.public_url,
        }

    async def open_artifact(self, job_id: str, request: ArtifactOpenRequest) -> Dict[str, str]:
        job, artifact = self._get_artifact_or_raise(job_id, request.artifact_index)
        target = str(request.target or "best").strip().lower() or "best"
        if target not in {"best", "local", "source"}:
            raise HTTPException(status_code=400, detail="Kiểu mở artifact không hợp lệ.")

        source_url = str(artifact.url or "").strip()
        local_error: HTTPException | None = None

        if target in {"best", "local"} and str(artifact.local_path or "").strip():
            try:
                self._artifact_local_path(artifact)
            except HTTPException as exc:
                local_error = exc
            else:
                return {
                    "url": self._artifact_file_url(job.id, request.artifact_index),
                    "label": "Mở tệp đã lưu",
                    "target": "local",
                }

        if target in {"best", "source"} and source_url:
            return {
                "url": source_url,
                "label": "Mở liên kết gốc",
                "target": "source",
            }

        if local_error is not None:
            raise local_error
        if target == "local":
            raise HTTPException(status_code=400, detail="Artifact này chưa có tệp local đã lưu.")
        if target == "source":
            raise HTTPException(status_code=400, detail="Artifact này chưa có liên kết gốc để mở.")
        raise HTTPException(status_code=400, detail="Artifact này chưa có liên kết để mở.")

    def artifact_file_path(self, job_id: str, artifact_index: int) -> Path:
        _, artifact = self._get_artifact_or_raise(job_id, artifact_index)
        return self._artifact_local_path(artifact)

    async def cleanup_replay_pack(self, request: ReplayCleanupRequest) -> Dict[str, Any]:
        cleared_job_ids = await self.store.clear_replay_metadata(request.job_ids)
        return {
            "cleared_job_ids": cleared_job_ids,
            "replay_pack": self._build_replay_pack(self.store.snapshot().jobs),
        }

    async def cleanup_scope(self, request: CleanupRequest) -> Dict[str, Any]:
        scope = str(request.scope or "").strip().lower()
        snapshot = self.store.snapshot()
        config = self._normalized_config(snapshot.config)
        output_shelf = self._build_output_shelf(snapshot.jobs)
        _, plans = self._build_cleanup_assistant(config, snapshot.jobs, output_shelf)
        plan = plans.get(scope)
        if plan is None:
            raise HTTPException(status_code=400, detail="Nhóm cleanup không hợp lệ.")

        deleted_paths: List[str] = []
        freed_bytes = 0
        cleared_refs: List[Dict[str, Any]] = []
        removed_job_ids: List[str] = []

        if scope == "uploads":
            for path in plan["paths"]:
                freed_bytes += self._file_size(path)
                deleted_paths.append(self._delete_cleanup_file(path, [UPLOADS_DIR.resolve()]))
        elif scope == "downloads":
            deleted_reference_keys: set[str] = set()
            download_roots = self._download_cleanup_roots()
            for path in plan["paths"]:
                freed_bytes += self._file_size(path)
                deleted_paths.append(self._delete_cleanup_file(path, download_roots))
                deleted_reference_keys.add(str(path))

            artifact_refs: List[tuple[str, int]] = []
            for path_key, refs in plan["artifact_refs"].items():
                if path_key not in deleted_reference_keys:
                    continue
                artifact_refs.extend(refs)
            if artifact_refs:
                cleared_refs = await self.store.clear_artifact_local_refs(artifact_refs)
        elif scope == "history":
            removed_job_ids = await self.store.remove_jobs(plan["job_ids"])

        fresh_snapshot = self.store.snapshot()
        fresh_output_shelf = self._build_output_shelf(fresh_snapshot.jobs)
        cleanup_assistant, _ = self._build_cleanup_assistant(config, fresh_snapshot.jobs, fresh_output_shelf)
        return {
            "scope": scope,
            "deleted_count": len(deleted_paths) + len(removed_job_ids),
            "deleted_paths": deleted_paths,
            "freed_bytes": freed_bytes,
            "cleared_artifact_refs": cleared_refs,
            "removed_job_ids": removed_job_ids,
            "cleanup_assistant": cleanup_assistant,
        }

    async def _set_job_progress(
        self,
        job_id: str,
        stage: str,
        detail: str,
        *,
        remote_status: str = "",
    ) -> None:
        await self.store.set_progress_hint(
            job_id,
            stage=stage,
            detail=detail,
            remote_status=remote_status,
        )

    async def _launch_login_browser(self, job_id: str) -> Any:
        self._assert_windows_interactive_browser_session("đăng nhập Google Flow")
        await self.store.patch_job(job_id, status="running")
        await self._set_job_progress(job_id, "launching_browser", "Em đang mở Chromium để đi tới Google Flow.")
        await self.store.append_log(job_id, "Đang mở Chromium để đăng nhập Google Flow")
        async with self._browser_session_lock:
            browser = await self._ensure_shared_browser()
            page = await self._open_login_flow_page(browser)
        await self._set_job_progress(
            job_id,
            "awaiting_login",
            "Chromium đã mở. Đang chờ hoàn tất đăng nhập Google Flow.",
        )
        await self.store.append_log(
            job_id,
            "Nếu chưa thấy tab hiện ra, hãy kiểm tra cửa sổ Chromium/Chrome for Testing vừa được mở trên màn hình."
            if os.name != "nt"
            else "Nếu chưa thấy tab hiện ra, hãy tìm cửa sổ 'Flow - Google Chrome for Testing' trên taskbar hoặc màn hình Windows.",
        )
        return page

    async def _wait_for_login_completion(self, job_id: str, page: Any) -> None:
        try:
            config = self._normalized_config(self.store.snapshot().config)
            email = None
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline:
                if getattr(page, "is_closed", lambda: False)():
                    raise RuntimeError("Cửa sổ đăng nhập đã bị đóng trước khi hoàn tất.")
                if "accounts.google.com" not in page.url:
                    email = await page.evaluate(
                        """
                        () => window.__NEXT_DATA__?.props?.pageProps?.session?.user?.email || null
                        """
                    )
                    if email:
                        break
                await asyncio.sleep(2)
            if not email:
                raise RuntimeError("Hết thời gian chờ đăng nhập Google Flow.")
            if config.project_id:
                await page.goto(self._project_url(config.project_id), wait_until="domcontentloaded")
                await asyncio.sleep(1.5)
            await self.store.append_log(job_id, "Em sẽ giữ nguyên tab Google Flow này để dùng tiếp cho các lượt chạy sau.")
            await self.store.append_log(job_id, f"Đã đăng nhập với tài khoản {email}")
            await self.store.patch_job(job_id, status="completed", result={"email": email})
        except Exception as exc:
            detail = self._flow_error_detail(exc)
            await self.store.patch_job(job_id, status="failed", error=detail)
            await self.store.append_log(job_id, f"Đăng nhập thất bại: {detail}")

    async def _open_login_flow_page(self, browser: Any) -> Any:
        context = getattr(browser, "context", None)
        target_url = "https://labs.google/fx/vi/tools/flow"
        page = None
        if context is not None:
            try:
                page = await context.new_page()
            except Exception:
                page = None
        if page is None:
            page = await browser.page()
        try:
            browser._page = page
        except Exception:
            pass
        try:
            await page.bring_to_front()
        except Exception:
            pass
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            await page.goto(target_url, wait_until="commit", timeout=60_000)
        try:
            await page.bring_to_front()
        except Exception:
            pass
        try:
            await page.evaluate(
                """
                () => {
                  try { window.focus(); } catch (error) {}
                  return true;
                }
                """
            )
        except Exception:
            pass
        await self._foreground_native_flow_window()
        await asyncio.sleep(1.5)
        return page

    async def _foreground_native_flow_window(self) -> None:
        if os.name != "nt":
            return
        await asyncio.to_thread(self._foreground_native_flow_window_sync)

    def _assert_windows_interactive_browser_session(self, action: str) -> None:
        if os.name != "nt":
            return
        session_id = self._current_windows_session_id()
        if session_id == 0:
            raise HTTPException(
                status_code=400,
                detail=(
                "Flow Web UI đang chạy trong session nền của Windows (Session 0), thường là do mở app qua SSH, "
                "tác vụ nền hoặc Task Scheduler. Kiểu này không thể bật cửa sổ để "
                f"{action}. Hãy mở Flow Web UI trực tiếp trên desktop Windows rồi thử lại."
                ),
            )

    def _current_windows_session_id(self) -> int | None:
        if os.name != "nt":
            return None
        try:
            kernel32 = ctypes.windll.kernel32
            process_id = kernel32.GetCurrentProcessId()
            session_id = ctypes.c_uint()
            if kernel32.ProcessIdToSessionId(process_id, ctypes.byref(session_id)):
                return int(session_id.value)
        except Exception:
            pass

        session_name = str(os.environ.get("SESSIONNAME", "") or "").strip().lower()
        if session_name in {"services", "service"}:
            return 0
        if session_name.startswith("console"):
            return 1
        return None

    def _foreground_native_flow_window_sync(self) -> None:
        if os.name != "nt":
            return
        script = r"""
Add-Type -AssemblyName Microsoft.VisualBasic
$deadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $deadline) {
  $window = Get-Process chrome -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 } |
    Sort-Object StartTime -Descending |
    Select-Object -First 1
  if ($window) {
    try {
      [Microsoft.VisualBasic.Interaction]::AppActivate($window.Id) | Out-Null
      exit 0
    } catch {
    }
  }
  foreach ($title in @('Flow - Google Chrome for Testing', 'Google Chrome for Testing', 'Flow')) {
    try {
      [Microsoft.VisualBasic.Interaction]::AppActivate($title) | Out-Null
      exit 0
    } catch {
    }
  }
  Start-Sleep -Milliseconds 350
}
exit 1
"""
        kwargs: Dict[str, Any] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "timeout": 15,
            "check": False,
        }
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if creationflags:
            kwargs["creationflags"] = creationflags
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                **kwargs,
            )
        except Exception:
            return

    def _automation_graph_payload(self, request: CreateJobRequest) -> Dict[str, Any]:
        graph = _model_dump(request.automation_graph)
        raw_modules = graph.get("modules") if isinstance(graph, dict) else []
        modules: List[Dict[str, Any]] = []
        for index, raw_module in enumerate(raw_modules or []):
            module = raw_module if isinstance(raw_module, dict) else {}
            module_type = re.sub(r"[^a-z0-9_]+", "", str(module.get("type") or "custom").strip().lower()) or "custom"
            module_id = str(module.get("id") or f"{module_type}_{index + 1}").strip() or f"{module_type}_{index + 1}"
            title = str(module.get("title") or self._automation_module_default_title(module_type)).strip()
            detail = str(module.get("detail") or "").strip()
            settings = module.get("settings") if isinstance(module.get("settings"), dict) else {}
            modules.append(
                {
                    "id": module_id,
                    "type": module_type,
                    "title": title,
                    "detail": detail,
                    "enabled": module.get("enabled") is not False,
                    "settings": settings,
                    "index": index,
                }
            )

        if not modules:
            modules = [
                {
                    "id": "flow",
                    "type": "flow",
                    "title": self._automation_module_default_title("flow"),
                    "detail": "Tạo artifact bằng Google Flow",
                    "enabled": True,
                    "settings": {},
                    "index": 0,
                }
            ]
            if request.type == "image" and request.telegram_enabled:
                modules.append(
                    {
                        "id": "telegram",
                        "type": "telegram",
                        "title": self._automation_module_default_title("telegram"),
                        "detail": "Gửi ảnh để duyệt",
                        "enabled": True,
                        "settings": {},
                        "index": 1,
                    }
                )
            if request.type == "image" and request.trello_enabled:
                modules.append(
                    {
                        "id": "trello",
                        "type": "trello",
                        "title": self._automation_module_default_title("trello"),
                        "detail": "Lưu ảnh vào Trello",
                        "enabled": True,
                        "settings": {},
                        "index": 2,
                    }
                )

        raw_edges = graph.get("edges") if isinstance(graph, dict) else []
        edges = [
            {
                "source": str(edge.get("source") or "").strip(),
                "target": str(edge.get("target") or "").strip(),
                "condition": str(edge.get("condition") or "success").strip() or "success",
            }
            for edge in (raw_edges or [])
            if isinstance(edge, dict) and str(edge.get("source") or "").strip() and str(edge.get("target") or "").strip()
        ]
        if not edges:
            enabled = [module for module in modules if module["enabled"]]
            edges = [
                {
                    "source": enabled[index]["id"],
                    "target": enabled[index + 1]["id"],
                    "condition": "success",
                }
                for index in range(max(0, len(enabled) - 1))
            ]

        return {
            "version": int(graph.get("version") or 1) if isinstance(graph, dict) else 1,
            "modules": modules,
            "edges": edges,
            "selected_module_id": str(graph.get("selected_module_id") or "").strip() if isinstance(graph, dict) else "",
        }

    def _automation_module_default_title(self, module_type: str) -> str:
        return {
            "source": "Prompt Source",
            "trello_source": "Trello Image Source",
            "normalize": "Normalize Prompt",
            "flow": "Google Flow",
            "telegram": "Telegram Review",
            "trello": "Trello Archive",
            "approval": "Approval",
            "custom": "Custom Module",
        }.get(str(module_type or "").strip().lower(), "Custom Module")

    def _automation_execution_payload(self, request: CreateJobRequest) -> Dict[str, Any]:
        graph = self._automation_graph_payload(request)
        nodes = []
        for module in graph["modules"]:
            nodes.append(
                {
                    "id": module["id"],
                    "type": module["type"],
                    "title": module["title"],
                    "detail": module["detail"],
                    "enabled": module["enabled"],
                    "status": "pending" if module["enabled"] else "disabled",
                    "input": {},
                    "output": {},
                    "error": "",
                    "started_at": "",
                    "completed_at": "",
                }
            )
        return {
            "mode": "graph",
            "version": graph["version"],
            "nodes": nodes,
            "edges": graph["edges"],
            "current_module_id": "",
            "completed": False,
        }

    async def _ensure_automation_execution(self, job_id: str, request: CreateJobRequest) -> Dict[str, Any]:
        job = self.store.get_job(job_id)
        result = dict(job.result or {}) if job is not None else {}
        execution = result.get("automation_execution")
        if not isinstance(execution, dict) or not isinstance(execution.get("nodes"), list):
            execution = self._automation_execution_payload(request)
            result["automation_execution"] = execution
            await self.store.patch_job(job_id, result=result)
        return execution

    async def _set_automation_module_status(
        self,
        job_id: str,
        request: CreateJobRequest,
        module_ref: str,
        status: str,
        *,
        input_data: Dict[str, Any] | None = None,
        output: Dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        await self._ensure_automation_execution(job_id, request)
        job = self.store.get_job(job_id)
        if job is None:
            return
        result = dict(job.result or {})
        execution = dict(result.get("automation_execution") or self._automation_execution_payload(request))
        nodes = list(execution.get("nodes") or [])
        module_ref = str(module_ref or "").strip()
        node = next((item for item in nodes if item.get("id") == module_ref), None)
        if node is None:
            node = next((item for item in nodes if item.get("type") == module_ref), None)
        if node is None:
            return

        now = utc_now()
        node["status"] = status
        if input_data is not None:
            node["input"] = input_data
        if output is not None:
            node["output"] = output
        if error:
            node["error"] = humanize_flow_error(error)
        if status == "running" and not node.get("started_at"):
            node["started_at"] = now
        if status in {"completed", "skipped", "failed", "disabled"}:
            node["completed_at"] = now
        execution["nodes"] = nodes
        execution["current_module_id"] = node.get("id", "") if status == "running" else execution.get("current_module_id", "")
        if status in {"completed", "skipped", "disabled"} and execution.get("current_module_id") == node.get("id"):
            execution["current_module_id"] = ""
        if status == "failed":
            execution["current_module_id"] = node.get("id", "")
        execution["completed"] = all(
            str(item.get("status") or "") in {"completed", "skipped", "disabled"}
            for item in nodes
        )
        result["automation_execution"] = execution
        await self.store.patch_job(job_id, result=result)

    async def _fail_active_automation_module(self, job_id: str, request: CreateJobRequest, detail: str) -> None:
        await self._ensure_automation_execution(job_id, request)
        job = self.store.get_job(job_id)
        execution = (job.result or {}).get("automation_execution") if job is not None else {}
        nodes = execution.get("nodes") if isinstance(execution, dict) else []
        active = next((node for node in nodes if node.get("status") == "running"), None)
        module_ref = active.get("id") if active else "flow"
        await self._set_automation_module_status(job_id, request, module_ref, "failed", error=detail)

    async def _run_automation_pre_modules(self, job_id: str, request: CreateJobRequest) -> None:
        graph = self._automation_graph_payload(request)
        for module in graph["modules"]:
            if not module["enabled"]:
                continue
            module_type = module["type"]
            if module_type == "flow":
                return
            if module_type == "trello_source":
                continue
            if module_type == "source":
                await self._set_automation_module_status(
                    job_id,
                    request,
                    module["id"],
                    "running",
                    input_data={
                        "source_type": module["settings"].get("sourceType") or "manual",
                        "source_location": module["settings"].get("sourceLocation") or "",
                    },
                )
                await self.store.append_log(job_id, f"Module {module['title']}: đã lấy prompt đầu vào.")
                await self._set_automation_module_status(
                    job_id,
                    request,
                    module["id"],
                    "completed",
                    output={"prompt_ready": bool(str(request.prompt or "").strip()), "prompt_length": len(request.prompt or "")},
                )
            elif module_type == "normalize":
                await self._set_automation_module_status(
                    job_id,
                    request,
                    module["id"],
                    "running",
                    input_data={"prompt_length": len(request.prompt or "")},
                )
                normalized_prompt = re.sub(r"\s+", " ", str(request.prompt or "")).strip()
                await self.store.append_log(job_id, f"Module {module['title']}: prompt đã được chuẩn hóa.")
                await self._set_automation_module_status(
                    job_id,
                    request,
                    module["id"],
                    "completed",
                    output={"prompt_length": len(normalized_prompt), "changed": normalized_prompt != str(request.prompt or "")},
                )
            elif module_type == "custom":
                await self._set_automation_module_status(
                    job_id,
                    request,
                    module["id"],
                    "completed",
                    output={"note": module["settings"].get("customNote") or "Custom module không có runner nên được ghi nhận như bước no-op."},
                )

    def _request_with_automation_module_settings(self, request: CreateJobRequest, module: Dict[str, Any]) -> CreateJobRequest:
        settings = module.get("settings") if isinstance(module.get("settings"), dict) else {}
        payload = _model_dump(request)
        if module.get("type") == "telegram" and settings.get("telegramChat"):
            payload["telegram_chat_id"] = str(settings.get("telegramChat") or "").strip()
        if module.get("type") in {"trello", "trello_source"}:
            if settings.get("trelloBoard"):
                payload["trello_board_id"] = str(settings.get("trelloBoard") or "").strip()
            if settings.get("trelloCard"):
                payload["trello_card_id"] = str(settings.get("trelloCard") or "").strip()
            if settings.get("trelloList"):
                payload["trello_list_id"] = str(settings.get("trelloList") or "").strip()
            attachment_ids = self._normalize_trello_attachment_ids(
                settings.get("trelloAttachmentIds") or settings.get("trelloAttachmentId") or []
            )
            if attachment_ids:
                payload["trello_attachment_ids"] = attachment_ids
        return CreateJobRequest(**payload)

    async def _run_automation_post_modules(
        self,
        job_id: str,
        request: CreateJobRequest,
        artifacts: List[JobArtifact],
        result: Dict[str, Any],
        *,
        start_after_module_id: str = "",
        skip_finished: bool = False,
    ) -> Dict[str, Any]:
        graph = self._automation_graph_payload(request)
        next_result = dict(result)
        waiting_for_start = bool(str(start_after_module_id or "").strip())
        for module in graph["modules"]:
            if waiting_for_start:
                if module["id"] == start_after_module_id:
                    waiting_for_start = False
                continue
            if not module["enabled"]:
                continue
            module_type = module["type"]
            if module_type in {"source", "trello_source", "normalize", "flow"}:
                continue
            if skip_finished and self._automation_module_status(job_id, module["id"]) in {"completed", "skipped", "disabled"}:
                continue
            module_request = self._request_with_automation_module_settings(request, module)
            try:
                if module_type == "telegram":
                    await self._set_automation_module_status(
                        job_id,
                        request,
                        module["id"],
                        "running",
                        input_data={"artifact_count": len(artifacts), "chat_id": module_request.telegram_chat_id},
                    )
                    telegram_result = await self._send_telegram_review_pack(job_id, module_request, artifacts)
                    if telegram_result:
                        next_result["telegram"] = telegram_result
                    status = "completed" if telegram_result.get("configured", True) else "skipped"
                    await self._set_automation_module_status(job_id, request, module["id"], status, output=telegram_result or {})
                elif module_type == "trello":
                    await self._set_automation_module_status(
                        job_id,
                        request,
                        module["id"],
                        "running",
                        input_data={
                            "artifact_count": len(artifacts),
                            "card_id": module_request.trello_card_id,
                            "list_id": module_request.trello_list_id,
                        },
                    )
                    trello_result = await self._archive_trello_artifacts(job_id, module_request, artifacts)
                    if trello_result:
                        next_result["trello"] = trello_result
                    status = "completed" if trello_result.get("configured", True) else "skipped"
                    await self._set_automation_module_status(job_id, request, module["id"], status, output=trello_result or {})
                elif module_type == "approval":
                    waiting_for_telegram = bool(request.telegram_enabled and artifacts)
                    await self._set_automation_module_status(
                        job_id,
                        request,
                        module["id"],
                        "running" if waiting_for_telegram else "completed",
                        input_data={"artifact_count": len(artifacts)},
                        output={
                            "awaiting_user_approval": waiting_for_telegram,
                            "pending": len(artifacts) if waiting_for_telegram else 0,
                        },
                    )
                    await self.store.append_log(
                        job_id,
                        f"Module {module['title']}: đang chờ người dùng duyệt trên Telegram."
                        if waiting_for_telegram
                        else f"Module {module['title']}: đã ghi nhận bước duyệt/log theo cấu hình.",
                    )
                    if waiting_for_telegram:
                        return next_result
                else:
                    await self._set_automation_module_status(
                        job_id,
                        request,
                        module["id"],
                        "running",
                        input_data={"artifact_count": len(artifacts), "module_type": module_type},
                    )
                    custom_result = await self._run_custom_automation_module(job_id, request, module, artifacts)
                    if custom_result:
                        custom_results = dict(next_result.get("custom_modules") or {})
                        custom_results[module["id"]] = custom_result
                        next_result["custom_modules"] = custom_results
                    status = "completed" if custom_result.get("configured", True) else "skipped"
                    await self._set_automation_module_status(
                        job_id,
                        request,
                        module["id"],
                        status,
                        output=custom_result,
                    )
            except Exception as exc:
                detail = self._flow_error_detail(exc)
                await self._set_automation_module_status(job_id, request, module["id"], "failed", error=detail)
                raise
        return next_result

    async def _run_custom_automation_module(
        self,
        job_id: str,
        request: CreateJobRequest,
        module: Dict[str, Any],
        artifacts: List[JobArtifact],
    ) -> Dict[str, Any]:
        settings = module.get("settings") if isinstance(module.get("settings"), dict) else {}
        url = str(settings.get("customWebhookUrl") or settings.get("webhookUrl") or "").strip()
        note = str(settings.get("customNote") or "").strip()
        if not url:
            await self.store.append_log(job_id, f"Module {module['title']}: chưa có webhook/API nên đã bỏ qua.")
            return {"configured": False, "note": note or "Chưa cấu hình webhook/API cho cục custom."}

        method = str(settings.get("customWebhookMethod") or settings.get("method") or "POST").strip().upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            method = "POST"
        timeout_s = self._custom_webhook_timeout(settings.get("customWebhookTimeout"))
        context = self._custom_module_context(job_id, request, module, artifacts)
        headers = self._custom_webhook_headers(settings.get("customWebhookHeaders"), context)
        body_template = str(settings.get("customWebhookBody") or "").strip()
        body_bytes = self._custom_webhook_body(method, body_template, context, headers)
        target_url = self._custom_webhook_url(url, method, context, body_template)

        response = await asyncio.to_thread(
            self._custom_webhook_request,
            method,
            target_url,
            headers,
            body_bytes,
            timeout_s,
        )
        await self.store.append_log(job_id, f"Module {module['title']}: webhook/API custom đã chạy xong.")
        return {
            "configured": True,
            "method": method,
            "url": self._redact_url_for_output(target_url),
            "status_code": response.get("status_code"),
            "response": response.get("body"),
        }

    def _custom_webhook_timeout(self, value: Any) -> float:
        try:
            timeout = float(value or 20)
        except (TypeError, ValueError):
            timeout = 20.0
        return max(3.0, min(120.0, timeout))

    def _custom_module_context(
        self,
        job_id: str,
        request: CreateJobRequest,
        module: Dict[str, Any],
        artifacts: List[JobArtifact],
    ) -> Dict[str, Any]:
        artifact_payloads = [_model_dump(artifact) for artifact in artifacts]
        first_artifact = artifact_payloads[0] if artifact_payloads else {}
        public_urls = [str(item.get("public_url") or item.get("url") or "").strip() for item in artifact_payloads]
        public_urls = [url for url in public_urls if url]
        local_paths = [str(item.get("local_path") or "").strip() for item in artifact_payloads]
        local_paths = [path for path in local_paths if path]
        return {
            "job_id": job_id,
            "job_title": request.title or self._default_title(request),
            "job_type": request.type,
            "prompt": request.prompt,
            "model": request.model,
            "aspect": request.aspect,
            "count": request.count,
            "module": {
                "id": module.get("id", ""),
                "type": module.get("type", "custom"),
                "title": module.get("title", ""),
                "detail": module.get("detail", ""),
            },
            "artifact_count": len(artifact_payloads),
            "artifacts": artifact_payloads,
            "artifact_urls": public_urls,
            "artifact_local_paths": local_paths,
            "first_artifact_url": str(first_artifact.get("public_url") or first_artifact.get("url") or ""),
            "first_artifact_path": str(first_artifact.get("local_path") or ""),
            "created_at": utc_now(),
        }

    def _custom_webhook_headers(self, raw_headers: Any, context: Dict[str, Any]) -> Dict[str, str]:
        parsed: Dict[str, Any] = {}
        if isinstance(raw_headers, dict):
            parsed = raw_headers
        else:
            text = str(raw_headers or "").strip()
            if text:
                try:
                    candidate = json.loads(self._render_custom_template(text, context))
                    if isinstance(candidate, dict):
                        parsed = candidate
                except Exception:
                    for line in text.splitlines():
                        if ":" not in line:
                            continue
                        key, value = line.split(":", 1)
                        if key.strip():
                            parsed[key.strip()] = self._render_custom_template(value.strip(), context)
        return {str(key).strip(): str(value) for key, value in parsed.items() if str(key).strip()}

    def _custom_webhook_body(
        self,
        method: str,
        body_template: str,
        context: Dict[str, Any],
        headers: Dict[str, str],
    ) -> bytes | None:
        if method == "GET":
            return None
        if body_template:
            rendered = self._render_custom_template(body_template, context)
            try:
                payload = json.loads(rendered)
                if not any(key.lower() == "content-type" for key in headers):
                    headers["Content-Type"] = "application/json"
                return json.dumps(payload, ensure_ascii=False).encode("utf-8")
            except json.JSONDecodeError:
                if not any(key.lower() == "content-type" for key in headers):
                    headers["Content-Type"] = "text/plain; charset=utf-8"
                return rendered.encode("utf-8")

        if not any(key.lower() == "content-type" for key in headers):
            headers["Content-Type"] = "application/json"
        return json.dumps(context, ensure_ascii=False).encode("utf-8")

    def _custom_webhook_url(self, url: str, method: str, context: Dict[str, Any], body_template: str) -> str:
        rendered = self._render_custom_template(url, context)
        parsed = urlparse(rendered)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError("Webhook/API custom phải là URL http hoặc https hợp lệ.")
        if method != "GET" or body_template:
            return rendered
        query = urlencode({"job_id": context["job_id"], "artifact_count": context["artifact_count"]})
        separator = "&" if parsed.query else "?"
        return f"{rendered}{separator}{query}"

    def _custom_webhook_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> Dict[str, Any]:
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout_s) as response:
                raw = response.read(512_000).decode("utf-8", errors="replace")
                status_code = getattr(response, "status", 200)
        except HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise RuntimeError(f"Webhook/API custom trả lỗi HTTP {exc.code}: {detail or exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"Webhook/API custom không kết nối được: {exc.reason or exc}") from exc

        body_payload: Any = raw[:4000]
        if raw:
            try:
                body_payload = json.loads(raw)
            except json.JSONDecodeError:
                body_payload = raw[:4000]
        return {"status_code": status_code, "body": body_payload}

    def _render_custom_template(self, template: str, context: Dict[str, Any]) -> str:
        def lookup(path: str) -> Any:
            current: Any = context
            for part in path.split("."):
                if isinstance(current, dict):
                    current = current.get(part, "")
                elif isinstance(current, list):
                    try:
                        current = current[int(part)]
                    except (ValueError, IndexError):
                        return ""
                else:
                    return ""
            return current

        def replace(match: re.Match[str]) -> str:
            value = lookup(match.group(1).strip())
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return str(value)

        return re.sub(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}", replace, str(template or ""))

    def _redact_url_for_output(self, url: str) -> str:
        parsed = urlparse(url)
        if not parsed.query:
            return url
        safe_query_parts = []
        for part in parsed.query.split("&"):
            key = part.split("=", 1)[0].lower()
            if any(token in key for token in ("key", "token", "secret", "password", "auth")):
                safe_query_parts.append(f"{part.split('=', 1)[0]}=***")
            else:
                safe_query_parts.append(part)
        return parsed._replace(query="&".join(safe_query_parts)).geturl()

    def _automation_module_status(self, job_id: str, module_id: str) -> str:
        job = self.store.get_job(job_id)
        execution = (job.result or {}).get("automation_execution") if job is not None else {}
        nodes = execution.get("nodes") if isinstance(execution, dict) else []
        node = next((item for item in nodes if item.get("id") == module_id), None)
        return str((node or {}).get("status") or "")

    def _automation_modules_after(self, request: CreateJobRequest, module_id: str) -> List[Dict[str, Any]]:
        graph = self._automation_graph_payload(request)
        modules = graph["modules"]
        for index, module in enumerate(modules):
            if module["id"] == module_id:
                return modules[index + 1 :]
        return []

    async def _skip_pending_automation_modules_after(
        self,
        job_id: str,
        request: CreateJobRequest,
        module_id: str,
        reason: str,
    ) -> None:
        for module in self._automation_modules_after(request, module_id):
            if not module["enabled"] or module["type"] in {"source", "normalize", "flow", "approval"}:
                continue
            if self._automation_module_status(job_id, module["id"]) not in {"", "pending", "running"}:
                continue
            await self._set_automation_module_status(
                job_id,
                request,
                module["id"],
                "skipped",
                output={"reason": reason},
            )

    def _approved_artifacts_for_job(self, job: JobRecord, approvals: Dict[str, Any]) -> List[JobArtifact]:
        approved_indexes: set[int] = set()
        for key, value in approvals.items():
            if not isinstance(value, dict) or value.get("status") != "approved":
                continue
            try:
                approved_indexes.add(int(key))
            except (TypeError, ValueError):
                continue
        return [artifact for index, artifact in enumerate(job.artifacts) if index in approved_indexes]

    async def _request_with_trello_source_images(self, job_id: str, request: CreateJobRequest) -> CreateJobRequest:
        if request.type != "image":
            return request
        graph = self._automation_graph_payload(request)
        module = next(
            (
                item
                for item in graph["modules"]
                if item["enabled"] and item["type"] == "trello_source"
            ),
            None,
        )
        if module is None:
            return request

        module_request = self._request_with_automation_module_settings(request, module)
        trello_config = self.store.snapshot().trello_config
        board_id = self._normalize_trello_board_id(
            module_request.trello_board_id
            or request.trello_board_id
            or trello_config.board_id
            or os.getenv("TRELLO_BOARD_ID", "")
        )
        card_id = self._normalize_trello_card_id(
            module_request.trello_card_id
            or request.trello_card_id
            or trello_config.card_id
            or os.getenv("TRELLO_CARD_ID", "")
        )
        raw_list_id = self._normalize_trello_id(
            module_request.trello_list_id
            or request.trello_list_id
            or trello_config.list_id
            or os.getenv("TRELLO_LIST_ID", "")
        )
        key, token = self._trello_credentials()
        if not key or not token:
            raise RuntimeError("Trello Source cần API key/token Trello để lấy ảnh gốc từ card.")
        list_id = self._trello_resolve_board_list_id(key, token, board_id, raw_list_id) if board_id else raw_list_id
        settings = module.get("settings") if isinstance(module.get("settings"), dict) else {}
        try:
            limit = int(settings.get("trelloAttachmentLimit") or 1)
        except (TypeError, ValueError):
            limit = 1
        limit = max(1, min(4, limit))
        selected_attachment_ids = self._normalize_trello_attachment_ids(
            module_request.trello_attachment_ids or request.trello_attachment_ids
        )
        if selected_attachment_ids:
            limit = min(4, max(limit, len(selected_attachment_ids)))

        await self._set_automation_module_status(
            job_id,
            request,
            module["id"],
            "running",
            input_data={
                "board_id": board_id,
                "card_id": card_id,
                "list_id": list_id,
                "limit": limit,
                "attachment_ids": selected_attachment_ids,
            },
        )

        if not card_id:
            if not board_id:
                raise RuntimeError("Trello Source cần Card ID/link card hoặc Board URL Trello có card chứa attachment ảnh.")
            if request.prompt_source_row:
                prompt_item = {
                    "product_key": request.prompt_product_key,
                    "product": request.prompt_product,
                    "product_name": request.prompt_product,
                    "notes": request.prompt_notes,
                }
                matched_hint = await asyncio.to_thread(self._trello_matching_image_card_hint, module_request, [prompt_item])
                if matched_hint.get("card_id"):
                    card_id = str(matched_hint.get("card_id") or "").strip()
                    list_id = self._normalize_trello_id(str(matched_hint.get("list_id") or list_id or ""))
            if request.prompt_source_row and not list_id:
                product_hint = (
                    request.prompt_product
                    or request.prompt_product_key
                    or f"dòng {request.prompt_source_row}"
                )
                raise RuntimeError(
                    "Batch sheet chưa có Trello card cụ thể và app không tìm thấy cột Ready for AI để lọc ảnh nguồn. "
                    f"Hãy chọn list Ready for AI ở cục Trello Source hoặc thêm cột Trello_Card/Card_URL cho {product_hint}."
                )
            if not card_id:
                card_id = await asyncio.to_thread(self._trello_first_image_card_id_on_board, key, token, board_id, list_id)
            if not card_id:
                scope = f" trong list {list_id}" if list_id else ""
                raise RuntimeError(f"Board Trello này chưa có card nào{scope} chứa attachment ảnh để làm ảnh tham chiếu.")
        elif list_id:
            card_hint = await asyncio.to_thread(self._trello_card_hint_by_id, key, token, card_id)
            if not card_hint:
                raise RuntimeError("Card Trello đã chọn không còn tồn tại hoặc không đọc được.")
            card_list_id = self._normalize_trello_id(str(card_hint.get("list_id") or ""))
            if card_list_id != list_id:
                ready_name = self._trello_list_name(key, token, list_id) or self._default_trello_source_list_name()
                raise RuntimeError(
                    f"Card Trello đã chọn không nằm trong cột {ready_name}; app đã dừng để tránh lấy nhầm ảnh từ cột khác."
                )

        paths = await asyncio.to_thread(
            self._download_trello_card_image_attachments,
            key,
            token,
            card_id,
            job_id,
            limit,
            selected_attachment_ids,
        )
        if not paths:
            raise RuntimeError("Card Trello này chưa có attachment ảnh nào để làm ảnh tham chiếu.")

        payload = _model_dump(request)
        existing_paths = [str(item).strip() for item in payload.get("reference_image_paths", []) if str(item).strip()]
        existing_roles = [str(item).strip() for item in payload.get("reference_image_roles", []) if str(item).strip()]
        available = max(0, 4 - len(existing_paths))
        selected_paths = paths[:available]
        payload["reference_image_paths"] = existing_paths + selected_paths
        payload["reference_image_roles"] = self._normalize_reference_image_roles(
            payload["reference_image_paths"],
            existing_roles
            + [
                "base" if not existing_paths and index == 0 else "reference"
                for index, _ in enumerate(selected_paths)
            ],
        )
        if board_id:
            payload["trello_board_id"] = board_id
        if list_id:
            payload["trello_list_id"] = payload.get("trello_list_id") or list_id
        payload["trello_card_id"] = payload.get("trello_card_id") or card_id

        await self._set_automation_module_status(
            job_id,
            request,
            module["id"],
            "completed",
            output={
                "board_id": board_id,
                "card_id": card_id,
                "list_id": list_id,
                "attachment_ids": selected_attachment_ids,
                "reference_image_count": len(selected_paths),
                "reference_image_names": [Path(path).name for path in selected_paths],
            },
        )
        detail = "ảnh đã chọn" if selected_attachment_ids else "ảnh gốc"
        await self.store.append_log(job_id, f"Đã lấy {len(selected_paths)} {detail} từ card Trello để đưa vào Flow.")
        return CreateJobRequest(**payload)

    async def _resume_automation_after_approval(self, job_id: str, approval_module_id: str) -> None:
        job = self.store.get_job(job_id)
        if job is None or not approval_module_id:
            return
        try:
            request = CreateJobRequest(**(job.input or {}))
        except Exception:
            return
        remaining = [
            module
            for module in self._automation_modules_after(request, approval_module_id)
            if module["enabled"] and module["type"] not in {"source", "normalize", "flow", "approval"}
        ]
        if not remaining:
            return

        result = dict(job.result or {})
        approvals = dict(result.get("telegram_approvals") or {})
        approved_artifacts = self._approved_artifacts_for_job(job, approvals)
        if not approved_artifacts:
            await self._skip_pending_automation_modules_after(
                job_id,
                request,
                approval_module_id,
                "Không có ảnh nào được duyệt trên Telegram.",
            )
            await self.store.append_log(job_id, "Không có ảnh nào được duyệt nên các module sau Approval đã được bỏ qua.")
            latest_job = self.store.get_job(job_id)
            if latest_job is not None:
                latest_result = dict(latest_job.result or result)
                await self.store.patch_job(job_id, result=latest_result)
            return

        await self.store.append_log(job_id, "Telegram đã duyệt xong, tiếp tục chạy các module sau Approval.")
        resumed_result = await self._run_automation_post_modules(
            job_id,
            request,
            approved_artifacts,
            result,
            start_after_module_id=approval_module_id,
            skip_finished=True,
        )
        latest_job = self.store.get_job(job_id)
        latest_execution = (latest_job.result or {}).get("automation_execution") if latest_job is not None else None
        if latest_execution:
            resumed_result = dict(resumed_result)
            resumed_result["automation_execution"] = latest_execution
        await self.store.patch_job(job_id, result=resumed_result)

    async def _run_flow_job(self, job_id: str, request: CreateJobRequest) -> None:
        await self.store.patch_job(job_id, status="running")
        await self._ensure_automation_execution(job_id, request)
        await self._run_automation_pre_modules(job_id, request)
        try:
            request = await self._request_with_trello_source_images(job_id, request)
            await self.store.patch_job(job_id, input=_model_dump(request))
            await self._set_automation_module_status(
                job_id,
                request,
                "flow",
                "running",
                input_data={
                    "type": request.type,
                    "prompt": request.prompt,
                    "model": request.model,
                    "aspect": request.aspect,
                    "count": request.count,
                },
            )
            await self._set_job_progress(job_id, "connecting", "Em đang khởi tạo client và kết nối tới project Flow hiện tại.")
            await self.store.append_log(job_id, "Đang khởi tạo kết nối tới Flow")
        except HTTPException as exc:
            detail = self._flow_error_detail(exc)
            await self._fail_active_automation_module(job_id, request, detail)
            await self.store.patch_job(job_id, status="failed", error=detail)
            await self.store.append_log(job_id, f"Tác vụ thất bại: {detail}")
            return
        except Exception as exc:
            detail = self._flow_error_detail(exc)
            await self._fail_active_automation_module(job_id, request, detail)
            await self.store.patch_job(job_id, status="failed", error=detail)
            await self.store.append_log(job_id, f"Tác vụ thất bại: {detail}")
            return
        artifacts: List[JobArtifact] = []
        result: Dict[str, Any] = {}

        async def _execute(client: Any) -> Dict[str, Any]:
            config = self.store.snapshot().config
            poll_s = config.poll_interval_s
            timeout_s = max(30, int(request.timeout_s or config.generation_timeout_s))

            if request.type == "video":
                requested_count = max(1, int(request.count or 1))
                requested_model = self._normalize_video_model(request.model)
                effective_start_image_path = str(request.start_image_path or "").strip()
                if not effective_start_image_path and (request.reference_image_paths or request.reference_media_names):
                    effective_start_image_path, _ = await self._prepare_video_start_image_from_references(
                        client,
                        job_id,
                        request,
                    )
                    await self._set_job_progress(
                        job_id,
                        "sending_request",
                        "Ảnh khung đầu đã sẵn sàng. Em đang gửi yêu cầu tạo video từ ảnh vừa dựng.",
                    )

                async def _run_video_attempt(model_label: str, *, fallback_from: str = "") -> Dict[str, Any]:
                    if effective_start_image_path:
                        send_timeout_s = timeout_s
                    else:
                        send_timeout_s = max(30, min(timeout_s, 90 * requested_count))

                    if effective_start_image_path:
                        await self.store.append_log(job_id, "Đang chuẩn bị tải ảnh đầu vào và gắn vào ô Start.")
                        await self._set_job_progress(
                            job_id,
                            "sending_request",
                            f"Em đang tải ảnh đầu vào lên Flow rồi gửi video bằng model {model_label}.",
                        )
                    else:
                        await self._set_job_progress(
                            job_id,
                            "sending_request",
                            f"Em đang gửi yêu cầu tạo video tới Flow bằng model {model_label}.",
                        )

                    try:
                        jobs = await asyncio.wait_for(
                            client.generate_video(
                                request.prompt,
                                model=model_label,
                                aspect=request.aspect,
                                count=request.count,
                                start_image=effective_start_image_path or None,
                                timeout_s=timeout_s,
                            ),
                            timeout=send_timeout_s,
                        )
                    except asyncio.TimeoutError as exc:
                        raise RuntimeError(
                            f"Google Flow chưa gửi được yêu cầu tạo video sau {send_timeout_s} giây. "
                            "Có thể Flow đang kẹt ở bước tải ảnh, gắn ảnh vào Start hoặc bấm Create."
                        ) from exc

                    if not jobs:
                        raise RuntimeError("Google Flow chưa khởi tạo được clip video nào từ yêu cầu này.")
                    if len(jobs) < requested_count:
                        raise RuntimeError(
                            f"Google Flow chỉ khởi tạo {len(jobs)}/{requested_count} clip trong lượt gửi này. "
                            "Em không tự bấm gửi thêm để tránh tạo dư clip ngoài ý muốn. Hãy thử chạy lại."
                        )

                    await self.store.append_log(job_id, f"Đã gửi {len(jobs)} tác vụ tạo video bằng model {model_label}")
                    await self._set_job_progress(
                        job_id,
                        "awaiting_response",
                        f"Flow đã nhận yêu cầu tạo video bằng model {model_label}. Đang chờ tín hiệu tiến trình đầu tiên.",
                    )
                    statuses = await asyncio.gather(
                        *[
                            self._wait_for_video_with_progress(
                                client,
                                job_id,
                                job,
                                f"Video {index + 1}",
                                poll_s=poll_s,
                                timeout_s=timeout_s,
                            )
                            for index, job in enumerate(jobs)
                        ]
                    )
                    payload: Dict[str, Any] = {
                        "video_jobs": jobs,
                        "statuses": statuses,
                        "used_model": model_label,
                    }
                    if fallback_from:
                        payload["fallback_from_model"] = fallback_from
                    return payload

                try:
                    return await _run_video_attempt(requested_model)
                except Exception as exc:
                    fallback_model = self._audio_fallback_video_model(requested_model)
                    if not self._is_audio_generation_failure(str(exc)) or not fallback_model:
                        raise

                    await self.store.append_log(
                        job_id,
                        f"Flow vấp ở bước audio với model {requested_model}. Em đang tự thử lại bằng {fallback_model}.",
                    )
                    await self._set_job_progress(
                        job_id,
                        "sending_request",
                        f"Flow bị lỗi audio với model {requested_model}. Em đang tự thử lại bằng {fallback_model} để lấy video im lặng.",
                    )
                    try:
                        return await _run_video_attempt(fallback_model, fallback_from=requested_model)
                    except Exception as retry_exc:
                        retry_detail = humanize_flow_error(str(retry_exc).strip()) or str(retry_exc).strip()
                        raise RuntimeError(
                            f"Flow bị lỗi audio với model {requested_model}. Em đã tự thử lại bằng {fallback_model} nhưng vẫn chưa lấy được clip. {retry_detail}"
                        ) from retry_exc

            if request.type == "image":
                reference_media_names = await self._resolve_image_reference_media(client, job_id, request)
                all_reference_media_names = reference_media_names or list(request.reference_media_names or [])
                if all_reference_media_names:
                    await self._set_job_progress(
                        job_id,
                        "sending_request",
                        f"Em đang gửi yêu cầu chỉnh ảnh với {len(all_reference_media_names)} ảnh tham chiếu tới Flow.",
                    )
                else:
                    await self._set_job_progress(job_id, "sending_request", "Em đang gửi yêu cầu tạo ảnh tới Flow.")

                images = await self._generate_images_with_retry(
                    client,
                    job_id,
                    request,
                    all_reference_media_names,
                )
                await self.store.append_log(job_id, f"Đã tạo {len(images)} ảnh")
                await self._set_job_progress(
                    job_id,
                    "saving_artifacts",
                    f"Flow đã trả về {len(images)} ảnh. Em đang lưu artifact vào lịch sử tác vụ.",
                )
                return {"images": images}

            if request.type == "extend":
                await self._set_job_progress(job_id, "sending_request", "Em đang gửi lệnh kéo dài video tới Flow.")
                job = await client.extend_video(
                    request.media_id,
                    workflow_id=request.workflow_id or None,
                    prompt=request.prompt,
                    timeout_s=timeout_s,
                )
                await self.store.append_log(job_id, f"Đã gửi lệnh kéo dài video cho {request.media_id}")
                await self._set_job_progress(
                    job_id,
                    "awaiting_response",
                    "Flow đã nhận lệnh kéo dài video. Đang chờ tín hiệu tiến trình đầu tiên.",
                )
                status = await self._wait_for_video_with_progress(
                    client,
                    job_id,
                    job,
                    "Tác vụ kéo dài video",
                    poll_s=poll_s,
                    timeout_s=timeout_s,
                )
                return {"video_job": job, "status": status}

            if request.type == "upscale":
                await self._set_job_progress(job_id, "sending_request", "Em đang gửi lệnh nâng chất lượng tới Flow.")
                job = await client.upscale_video(
                    request.media_id,
                    workflow_id=request.workflow_id or None,
                    resolution=request.resolution,
                    timeout_s=timeout_s,
                )
                await self.store.append_log(job_id, f"Đã gửi lệnh nâng chất lượng cho {request.media_id}")
                await self._set_job_progress(
                    job_id,
                    "awaiting_response",
                    "Flow đã nhận lệnh nâng chất lượng. Đang chờ tín hiệu tiến trình đầu tiên.",
                )
                status = await self._wait_for_video_with_progress(
                    client,
                    job_id,
                    job,
                    "Tác vụ nâng chất lượng",
                    poll_s=poll_s,
                    timeout_s=timeout_s,
                )
                return {"video_job": job, "status": status}

            if request.type == "camera_motion":
                await self._set_job_progress(job_id, "sending_request", "Em đang gửi lệnh chuyển động camera tới Flow.")
                job = await client.camera_motion(
                    request.media_id,
                    request.motion,
                    workflow_id=request.workflow_id or None,
                    timeout_s=timeout_s,
                )
                await self.store.append_log(job_id, f"Đã gửi chuyển động camera {request.motion}")
                await self._set_job_progress(
                    job_id,
                    "awaiting_response",
                    "Flow đã nhận lệnh chuyển động camera. Đang chờ tín hiệu tiến trình đầu tiên.",
                )
                status = await self._wait_for_video_with_progress(
                    client,
                    job_id,
                    job,
                    "Tác vụ chuyển động camera",
                    poll_s=poll_s,
                    timeout_s=timeout_s,
                )
                return {"video_job": job, "status": status}

            if request.type == "camera_position":
                await self._set_job_progress(job_id, "sending_request", "Em đang gửi lệnh đổi vị trí camera tới Flow.")
                job = await client.camera_position(
                    request.media_id,
                    request.position,
                    workflow_id=request.workflow_id or None,
                    timeout_s=timeout_s,
                )
                await self.store.append_log(job_id, f"Đã gửi vị trí camera {request.position}")
                await self._set_job_progress(
                    job_id,
                    "awaiting_response",
                    "Flow đã nhận lệnh vị trí camera. Đang chờ tín hiệu tiến trình đầu tiên.",
                )
                status = await self._wait_for_video_with_progress(
                    client,
                    job_id,
                    job,
                    "Tác vụ vị trí camera",
                    poll_s=poll_s,
                    timeout_s=timeout_s,
                )
                return {"video_job": job, "status": status}

            if request.type == "insert":
                await self._set_job_progress(job_id, "sending_request", "Em đang gửi lệnh chèn vật thể tới Flow.")
                job = await client.insert_object(
                    request.media_id,
                    request.prompt,
                    workflow_id=request.workflow_id or None,
                    timeout_s=timeout_s,
                )
                await self.store.append_log(job_id, f"Đã gửi lệnh chèn vật thể cho {request.media_id}")
                await self._set_job_progress(
                    job_id,
                    "awaiting_response",
                    "Flow đã nhận lệnh chèn vật thể. Đang chờ tín hiệu tiến trình đầu tiên.",
                )
                status = await self._wait_for_video_with_progress(
                    client,
                    job_id,
                    job,
                    "Tác vụ chèn vật thể",
                    poll_s=poll_s,
                    timeout_s=timeout_s,
                )
                return {"video_job": job, "status": status}

            if request.type == "remove":
                await self._set_job_progress(job_id, "sending_request", "Em đang gửi lệnh xóa vật thể tới Flow.")
                job = await client.remove_object(
                    request.media_id,
                    workflow_id=request.workflow_id or None,
                    mask_x=request.mask_x,
                    mask_y=request.mask_y,
                    brush_size=request.brush_size,
                    timeout_s=timeout_s,
                )
                await self.store.append_log(job_id, f"Đã gửi lệnh xóa vật thể cho {request.media_id}")
                await self._set_job_progress(
                    job_id,
                    "awaiting_response",
                    "Flow đã nhận lệnh xóa vật thể. Đang chờ tín hiệu tiến trình đầu tiên.",
                )
                status = await self._wait_for_video_with_progress(
                    client,
                    job_id,
                    job,
                    "Tác vụ xóa vật thể",
                    poll_s=poll_s,
                    timeout_s=timeout_s,
                )
                return {"video_job": job, "status": status}

            raise ValueError(f"Loại tác vụ chưa được hỗ trợ: {request.type}")

        try:
            payload = await self._with_client(
                _execute,
                workflow_id=request.workflow_id,
                timeout_s=request.timeout_s,
            )
            if request.type == "image":
                images = payload["images"]
                artifacts = [
                    JobArtifact(
                        label=f"Ảnh {index + 1}",
                        media_name=getattr(image, "media_name", ""),
                        url=getattr(image, "fife_url", ""),
                        workflow_id=getattr(image, "workflow_id", request.workflow_id),
                        mime_type="image/jpeg",
                        prompt=getattr(image, "prompt", request.prompt),
                        dimensions=getattr(image, "dimensions", {}) or {},
                    )
                    for index, image in enumerate(images)
                ]
                result = {
                    "count": len(artifacts),
                    "mode": "image",
                }
            elif request.type == "video":
                video_jobs = payload["video_jobs"]
                statuses = payload["statuses"]
                artifacts, missing_labels = self._build_video_artifacts(video_jobs, statuses, request)
                if not artifacts:
                    raise RuntimeError(
                        "Google Flow báo đã hoàn tất nhưng chưa trả clip video nào về cho ứng dụng. Hãy thử chạy lại."
                    )
                if missing_labels:
                    await self.store.append_log(
                        job_id,
                        f"Flow chưa trả clip cho {len(missing_labels)} mục: {', '.join(missing_labels[:4])}. Em chỉ lưu các clip đã có thật.",
                    )
                result = {
                    "count": len(artifacts),
                    "mode": "video",
                    "missing_count": len(missing_labels),
                    "model": payload.get("used_model") or self._normalize_video_model(request.model),
                }
                if payload.get("fallback_from_model"):
                    result["fallback_from_model"] = payload["fallback_from_model"]
            else:
                job = payload["video_job"]
                status = payload["status"]
                artifacts, missing_labels = self._build_video_artifacts([job], [status], request, default_label=self._default_title(request))
                if not artifacts:
                    raise RuntimeError(
                        "Google Flow báo đã hoàn tất nhưng chưa trả clip video nào về cho ứng dụng. Hãy thử chạy lại."
                    )
                result = {
                    "media_name": getattr(job, "media_name", ""),
                    "mode": "video",
                    "missing_count": len(missing_labels),
                }

            await self._set_job_progress(
                job_id,
                "saving_artifacts",
                f"Đang lưu {len(artifacts)} artifact vào lịch sử tác vụ.",
            )
            current_job = self.store.get_job(job_id)
            if current_job is not None and current_job.result:
                merged_result = dict(current_job.result)
                merged_result.update(result)
                result = merged_result
            await self.store.replace_artifacts(job_id, artifacts)
            await self._set_automation_module_status(
                job_id,
                request,
                "flow",
                "completed",
                output={
                    "artifact_count": len(artifacts),
                    "media_names": [artifact.media_name for artifact in artifacts if artifact.media_name],
                    "mode": result.get("mode", request.type),
                },
            )
            result = await self._run_automation_post_modules(job_id, request, artifacts, result)
            latest_job = self.store.get_job(job_id)
            latest_execution = (latest_job.result or {}).get("automation_execution") if latest_job is not None else None
            if latest_execution:
                result = dict(result)
                result["automation_execution"] = latest_execution
            await self.store.patch_job(job_id, status="completed", result=result)
            await self.store.append_log(job_id, "Tác vụ đã hoàn tất")
        except HTTPException as exc:
            detail = self._flow_error_detail(exc)
            await self._fail_active_automation_module(job_id, request, detail)
            await self.store.patch_job(job_id, status="failed", error=detail)
            await self.store.append_log(job_id, f"Tác vụ thất bại: {detail}")
        except Exception as exc:
            detail = self._flow_error_detail(exc)
            await self._fail_active_automation_module(job_id, request, detail)
            await self.store.patch_job(job_id, status="failed", error=detail)
            await self.store.append_log(job_id, f"Tác vụ thất bại: {detail}")

    async def _archive_trello_artifacts(
        self,
        job_id: str,
        request: CreateJobRequest,
        artifacts: List[JobArtifact],
    ) -> Dict[str, Any]:
        if request.type != "image" or not artifacts or not request.trello_enabled:
            return {}

        key, token = self._trello_credentials()
        if not key or not token:
            return {"configured": False}

        trello_config = self.store.snapshot().trello_config
        card_id = self._normalize_trello_card_id(
            request.trello_card_id or trello_config.card_id or os.getenv("TRELLO_CARD_ID", "")
        )
        list_id = self._normalize_trello_id(request.trello_list_id or trello_config.list_id or os.getenv("TRELLO_LIST_ID", ""))
        set_cover = bool(request.trello_set_cover and trello_config.set_cover is not False)
        card_url = ""
        created_card = False

        if not card_id and list_id:
            try:
                card_payload = await asyncio.to_thread(
                    self._trello_create_card,
                    key,
                    token,
                    list_id,
                    self._trello_card_name(job_id, request),
                    self._trello_card_description(job_id, request),
                )
                card_id = str(card_payload.get("id") or card_payload.get("shortLink") or "").strip()
                card_url = str(card_payload.get("shortUrl") or card_payload.get("url") or "").strip()
                created_card = True
                await self.store.append_log(job_id, f"Đã tạo card Trello để lưu ảnh: {card_url or card_id}")
            except Exception as exc:
                await self.store.append_log(job_id, f"Không tạo được card Trello: {humanize_flow_error(str(exc))}")
                return {
                    "configured": True,
                    "sent": 0,
                    "failed": len(artifacts),
                    "error": humanize_flow_error(str(exc)),
                }

        if not card_id:
            await self.store.append_log(job_id, "Trello đã cấu hình key/token nhưng thiếu Trello card hoặc list để lưu ảnh.")
            return {
                "configured": True,
                "sent": 0,
                "failed": len(artifacts),
                "error": "missing_trello_target",
            }

        upload_mode = (trello_config.upload_mode or os.getenv("TRELLO_UPLOAD_MODE", "file")).strip().lower()
        if upload_mode not in {"file", "url"}:
            upload_mode = "file"
        # 2K upscaling requires re-uploading bytes, which only the "file" mode
        # supports. When the user has explicitly chosen URL mode we keep that
        # choice and skip upscaling instead of surprising them with a switch.
        upscale_2k = bool(getattr(trello_config, "upscale_to_2k", True)) and upload_mode == "file"
        stored = 0
        failed = 0
        attachments: List[Dict[str, Any]] = []
        upscale_announced = False
        for index, artifact in enumerate(artifacts):
            artifact_url = str(artifact.url or artifact.public_url or "").strip()
            if not artifact_url:
                failed += 1
                continue

            name = self._trello_attachment_name(job_id, artifact, index)
            try:
                if upload_mode == "url":
                    attachment_payload = await asyncio.to_thread(
                        self._trello_attach_url,
                        key,
                        token,
                        card_id,
                        artifact_url,
                        name,
                        set_cover and index == 0,
                    )
                else:
                    upscaled_bytes: Optional[bytes] = None
                    upscaled_mime = ""
                    if upscale_2k:
                        try:
                            upscaled_bytes, upscaled_mime = await self._upsample_artifact_bytes(
                                artifact,
                                artifact_url,
                            )
                        except Exception as up_exc:
                            await self.store.append_log(
                                job_id,
                                f"Không nâng được ảnh {index + 1} lên 2K (giữ bản gốc): {humanize_flow_error(str(up_exc))}",
                            )
                            upscaled_bytes = None
                        else:
                            if upscaled_bytes and not upscale_announced:
                                await self.store.append_log(
                                    job_id,
                                    "Đã nâng cấp ảnh lên 2K trước khi upload lên Trello.",
                                )
                                upscale_announced = True
                    try:
                        if upscaled_bytes:
                            attachment_payload = await asyncio.to_thread(
                                self._trello_attach_file_bytes,
                                key,
                                token,
                                card_id,
                                upscaled_bytes,
                                upscaled_mime or artifact.mime_type or "image/jpeg",
                                name,
                                set_cover and index == 0,
                            )
                        else:
                            attachment_payload = await asyncio.to_thread(
                                self._trello_attach_file_from_url,
                                key,
                                token,
                                card_id,
                                artifact_url,
                                name,
                                artifact.mime_type or "image/jpeg",
                                set_cover and index == 0,
                            )
                    except Exception as file_exc:
                        await self.store.append_log(
                            job_id,
                            f"Upload file ảnh {index + 1} lên Trello chưa được, thử attach bằng URL: {humanize_flow_error(str(file_exc))}",
                        )
                        attachment_payload = await asyncio.to_thread(
                            self._trello_attach_url,
                            key,
                            token,
                            card_id,
                            artifact_url,
                            name,
                            set_cover and index == 0,
                        )

                stored += 1
                attachments.append(self._trello_attachment_summary(attachment_payload))
            except Exception as exc:
                failed += 1
                await self.store.append_log(
                    job_id,
                    f"Không lưu được ảnh {index + 1} lên Trello: {humanize_flow_error(str(exc))}",
                )

        if stored:
            await self.store.append_log(job_id, f"Đã lưu {stored} ảnh lên Trello.")
        return {
            "configured": True,
            "sent": stored,
            "failed": failed,
            "card_id": card_id,
            "card_url": card_url,
            "created_card": created_card,
            "attachments": attachments,
        }

    def _trello_credentials(self) -> tuple[str, str]:
        config = self.store.snapshot().trello_config
        key = str(config.api_key or "").strip() or os.getenv("TRELLO_API_KEY", "").strip()
        token = str(config.token or "").strip() or os.getenv("TRELLO_TOKEN", "").strip()
        return key, token

    def _normalize_trello_id(self, value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            parsed = urlparse(raw)
        except Exception:
            return raw.strip().strip("/")
        if parsed.scheme and parsed.netloc:
            raw = parsed.path or raw
        return raw.split("?", 1)[0].split("#", 1)[0].strip().strip("/")

    def _normalize_trello_card_id(self, value: str) -> str:
        raw = self._normalize_trello_id(value)
        if "/c/" in raw:
            raw = raw.split("/c/", 1)[1]
        if raw.startswith("c/"):
            raw = raw[2:]
        if "/" in raw:
            raw = raw.split("/", 1)[0]
        return raw.strip()

    def _normalize_trello_attachment_ids(self, values: Any) -> List[str]:
        if values is None:
            return []
        raw_items: List[Any]
        if isinstance(values, str):
            raw_items = re.split(r"[\s,;]+", values)
        elif isinstance(values, (list, tuple, set)):
            raw_items = list(values)
        else:
            raw_items = [values]
        normalized: List[str] = []
        seen: set[str] = set()
        for item in raw_items:
            attachment_id = self._normalize_trello_id(str(item or ""))
            if not attachment_id or attachment_id in seen:
                continue
            seen.add(attachment_id)
            normalized.append(attachment_id)
        return normalized

    def _normalize_trello_board_id(self, value: str) -> str:
        raw = self._normalize_trello_id(value)
        if "/b/" in raw:
            raw = raw.split("/b/", 1)[1]
        if raw.startswith("b/"):
            raw = raw[2:]
        if "/" in raw:
            raw = raw.split("/", 1)[0]
        return raw.strip()

    def _trello_card_name(self, job_id: str, request: CreateJobRequest) -> str:
        prompt = str(request.prompt or "").strip().replace("\n", " ")
        prompt = re.sub(r"\s+", " ", prompt)
        if len(prompt) > 72:
            prompt = f"{prompt[:69]}..."
        return prompt or f"Flow image {job_id[:8]}"

    def _trello_card_description(self, job_id: str, request: CreateJobRequest) -> str:
        prompt = str(request.prompt or "").strip()
        return "\n".join(
            part
            for part in [
                "Generated by Flow Web UI.",
                f"Job: {job_id}",
                f"Model: {self._image_ui_model_label(request.model or self.DEFAULT_IMAGE_MODEL)}",
                f"Aspect: {request.aspect or 'square'}",
                f"Prompt:\n{prompt}" if prompt else "",
            ]
            if part
        )

    def _trello_attachment_name(self, job_id: str, artifact: JobArtifact, index: int) -> str:
        suffix = Path(str(artifact.media_name or "")).suffix or ".jpg"
        if suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            suffix = ".jpg"
        return f"flow-{job_id[:8]}-{index + 1}{suffix}"

    def _trello_endpoint(self, path: str, key: str, token: str, fields: Dict[str, Any] | None = None) -> str:
        auth_fields = {"key": key, "token": token}
        if fields:
            auth_fields.update({k: v for k, v in fields.items() if str(v) != ""})
        auth = urlencode(auth_fields)
        return f"{self.TRELLO_API_BASE_URL}/{path.strip('/')}?{auth}"

    def _trello_get_json(
        self,
        path: str,
        key: str,
        token: str,
        *,
        fields: Dict[str, Any] | None = None,
    ) -> Any:
        request = Request(
            self._trello_endpoint(path, key, token, fields),
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.TRELLO_TIMEOUT_S) as response:
                raw_payload = response.read().decode("utf-8", errors="replace")
                return json.loads(raw_payload) if raw_payload else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Trello API lỗi {exc.code}: {detail or exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(str(exc.reason or exc)) from exc

    def _download_trello_card_image_attachments(
        self,
        key: str,
        token: str,
        card_id: str,
        job_id: str,
        limit: int,
        attachment_ids: List[str] | None = None,
    ) -> List[str]:
        payload = self._trello_get_json(
            f"cards/{quote(card_id, safe='')}/attachments",
            key,
            token,
            fields={"fields": "id,name,url,mimeType,bytes,date"},
        )
        attachments = payload if isinstance(payload, list) else []
        image_attachments = [
            item
            for item in attachments
            if self._trello_attachment_is_image(item)
        ]
        selected_ids = self._normalize_trello_attachment_ids(attachment_ids)
        if selected_ids:
            by_id = {self._normalize_trello_id(str(item.get("id") or "")): item for item in image_attachments}
            selected_attachments = [by_id[item_id] for item_id in selected_ids if item_id in by_id]
            if not selected_attachments:
                raise RuntimeError("Ảnh Trello đã chọn không nằm trên card này hoặc không phải attachment ảnh.")
            image_attachments = selected_attachments
        image_attachments = image_attachments[: max(1, min(4, int(limit or 4)))]
        paths: List[str] = []
        for index, attachment in enumerate(image_attachments):
            data, mime = self._trello_download_attachment_bytes(key, token, card_id, attachment)
            name = str(attachment.get("name") or f"trello-image-{index + 1}.jpg").strip()
            suffix = Path(name).suffix or mimetypes.guess_extension(mime or "") or ".jpg"
            if suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                suffix = ".jpg"
            target = UPLOADS_DIR / f"trello-{job_id[:8]}-{index + 1}{suffix}"
            target.write_bytes(data)
            paths.append(str(target))
        return paths

    async def trello_attachment_preview(self, card_id: str, attachment_id: str) -> Dict[str, Any]:
        key, token = self._trello_credentials()
        if not key or not token:
            raise HTTPException(status_code=400, detail="Chưa thiết lập Trello API key/token.")
        normalized_card_id = self._normalize_trello_card_id(card_id)
        normalized_attachment_id = self._normalize_trello_id(attachment_id)
        if not normalized_card_id or not normalized_attachment_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy attachment Trello.")
        try:
            attachment = await asyncio.to_thread(
                self._trello_get_json,
                f"cards/{quote(normalized_card_id, safe='')}/attachments/{quote(normalized_attachment_id, safe='')}",
                key,
                token,
                fields={"fields": "id,name,url,mimeType"},
            )
            if not isinstance(attachment, dict) or not attachment:
                raise HTTPException(status_code=404, detail="Không tìm thấy attachment Trello.")
            if not self._trello_attachment_is_image(attachment):
                raise HTTPException(status_code=415, detail="Attachment Trello không phải ảnh.")
            data, media_type = await asyncio.to_thread(
                self._trello_download_attachment_bytes,
                key,
                token,
                normalized_card_id,
                attachment,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=humanize_flow_error(str(exc))) from exc
        return {"content": data, "media_type": media_type or str(attachment.get("mimeType") or "image/jpeg")}

    def _trello_first_image_card_id_on_board(
        self,
        key: str,
        token: str,
        board_id: str,
        list_id: str = "",
    ) -> str:
        card = self._trello_first_image_card_on_board(key, token, board_id, list_id)
        return str(card.get("id") or card.get("shortLink") or "").strip() if card else ""

    def _trello_matching_image_card_hint(
        self,
        request: CreateJobRequest,
        items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        key, token = self._trello_credentials()
        if not key or not token or not items:
            return {}
        trello_config = self.store.snapshot().trello_config
        board_id = self._normalize_trello_board_id(
            request.trello_board_id
            or trello_config.board_id
            or os.getenv("TRELLO_BOARD_ID", "")
        )
        if not board_id:
            return {}
        raw_list_id = self._normalize_trello_id(
            request.trello_list_id
            or trello_config.list_id
            or os.getenv("TRELLO_LIST_ID", "")
        )
        list_id = self._trello_resolve_board_list_id(key, token, board_id, raw_list_id)
        if not list_id:
            return {}
        card = self._trello_matching_image_card_on_board(key, token, board_id, items, list_id)
        if not card:
            return {}
        card_list_id = self._normalize_trello_id(str(card.get("idList") or list_id or ""))
        return {
            "card_id": str(card.get("id") or card.get("shortLink") or "").strip(),
            "card_name": str(card.get("name") or "").strip(),
            "card_short_link": str(card.get("shortLink") or "").strip(),
            "card_url": str(card.get("url") or "").strip(),
            "list_id": card_list_id,
            "list_name": self._trello_list_name(key, token, card_list_id),
        }

    def _trello_source_card_hint(self, request: CreateJobRequest) -> Dict[str, Any]:
        key, token = self._trello_credentials()
        if not key or not token:
            return {}
        trello_config = self.store.snapshot().trello_config
        board_id = self._normalize_trello_board_id(
            request.trello_board_id
            or trello_config.board_id
            or os.getenv("TRELLO_BOARD_ID", "")
        )
        card_id = self._normalize_trello_card_id(
            request.trello_card_id
            or trello_config.card_id
            or os.getenv("TRELLO_CARD_ID", "")
        )
        raw_list_id = self._normalize_trello_id(
            request.trello_list_id
            or trello_config.list_id
            or os.getenv("TRELLO_LIST_ID", "")
        )
        list_id = self._trello_resolve_board_list_id(key, token, board_id, raw_list_id) if board_id else raw_list_id
        if card_id:
            hint = self._trello_card_hint_by_id(key, token, card_id)
            if not hint:
                return {}
            card_list_id = self._normalize_trello_id(str(hint.get("list_id") or ""))
            if list_id and card_list_id and card_list_id != list_id:
                return {}
            return hint
        elif board_id and list_id:
            card = self._trello_first_image_card_on_board(key, token, board_id, list_id)
        else:
            return {}

        if not isinstance(card, dict):
            return {}
        resolved_card_id = str(card.get("id") or card.get("shortLink") or "").strip()
        if not resolved_card_id:
            return {}
        card_list_id = self._normalize_trello_id(str(card.get("idList") or list_id or ""))
        return {
            "card_id": resolved_card_id,
            "card_name": str(card.get("name") or "").strip(),
            "card_short_link": str(card.get("shortLink") or "").strip(),
            "card_url": str(card.get("url") or "").strip(),
            "list_id": card_list_id,
            "list_name": self._trello_list_name(key, token, card_list_id),
        }

    def _trello_list_name(self, key: str, token: str, list_id: str) -> str:
        list_id = self._normalize_trello_id(list_id)
        if not list_id:
            return ""
        try:
            payload = self._trello_get_json(
                f"lists/{quote(list_id, safe='')}",
                key,
                token,
                fields={"fields": "name"},
            )
        except Exception:
            return ""
        return str(payload.get("name") or "").strip() if isinstance(payload, dict) else ""

    def _trello_card_hint_by_id(self, key: str, token: str, card_id: str) -> Dict[str, Any]:
        card_id = self._normalize_trello_card_id(card_id)
        if not card_id:
            return {}
        card = self._trello_get_json(
            f"cards/{quote(card_id, safe='')}",
            key,
            token,
            fields={"fields": "id,name,shortLink,url,idList,closed"},
        )
        if not isinstance(card, dict) or card.get("closed"):
            return {}
        resolved_card_id = str(card.get("id") or card.get("shortLink") or "").strip()
        if not resolved_card_id:
            return {}
        card_list_id = self._normalize_trello_id(str(card.get("idList") or ""))
        return {
            "card_id": resolved_card_id,
            "card_name": str(card.get("name") or "").strip(),
            "card_short_link": str(card.get("shortLink") or "").strip(),
            "card_url": str(card.get("url") or "").strip(),
            "list_id": card_list_id,
            "list_name": self._trello_list_name(key, token, card_list_id),
        }

    def _trello_image_card_by_id(self, key: str, token: str, card_id: str) -> Dict[str, Any]:
        card_id = self._normalize_trello_card_id(card_id)
        if not card_id:
            return {}
        card = self._trello_get_json(
            f"cards/{quote(card_id, safe='')}",
            key,
            token,
            fields={
                "fields": "id,name,desc,shortLink,url,idList,closed",
                "attachments": "true",
                "attachment_fields": "id,name,url,mimeType",
            },
        )
        if not isinstance(card, dict) or card.get("closed"):
            return {}
        attachments = card.get("attachments") if isinstance(card.get("attachments"), list) else []
        if not attachments:
            attachments_payload = self._trello_get_json(
                f"cards/{quote(card_id, safe='')}/attachments",
                key,
                token,
                fields={"fields": "id,name,url,mimeType"},
            )
            attachments = attachments_payload if isinstance(attachments_payload, list) else []
        image_attachments = [
            item for item in attachments if isinstance(item, dict) and self._trello_attachment_is_image(item)
        ]
        if not image_attachments:
            return {}
        card["_image_attachments"] = image_attachments
        return card

    def _select_trello_card_attachments(
        self,
        card: Dict[str, Any],
        attachment_ids: List[str],
    ) -> bool:
        selected_ids = self._normalize_trello_attachment_ids(attachment_ids)
        if not selected_ids:
            card["_selected_attachment_ids"] = []
            return True
        image_attachments = [
            item
            for item in card.get("_image_attachments") or []
            if isinstance(item, dict) and self._trello_attachment_is_image(item)
        ]
        by_id = {self._normalize_trello_id(str(item.get("id") or "")): item for item in image_attachments}
        selected = [by_id[item_id] for item_id in selected_ids if item_id in by_id]
        if not selected:
            return False
        card["_image_attachments"] = selected
        card["_selected_attachment_ids"] = [self._normalize_trello_id(str(item.get("id") or "")) for item in selected if str(item.get("id") or "").strip()]
        return True

    def _default_trello_source_list_name(self) -> str:
        return os.getenv("TRELLO_SOURCE_LIST_NAME", self.DEFAULT_TRELLO_SOURCE_LIST_NAME).strip() or self.DEFAULT_TRELLO_SOURCE_LIST_NAME

    def _trello_board_lists(self, key: str, token: str, board_id: str) -> List[Dict[str, Any]]:
        board_id = self._normalize_trello_board_id(board_id)
        if not board_id:
            return []
        payload = self._trello_get_json(
            f"boards/{quote(board_id, safe='')}/lists",
            key,
            token,
            fields={"fields": "id,name,closed", "filter": "open"},
        )
        return [item for item in payload if isinstance(item, dict) and not item.get("closed")] if isinstance(payload, list) else []

    def _trello_resolve_board_list_id(self, key: str, token: str, board_id: str, list_value: str = "") -> str:
        board_id = self._normalize_trello_board_id(board_id)
        normalized_value = self._normalize_trello_id(list_value)
        if not board_id:
            return normalized_value

        target_name = normalized_value or self._default_trello_source_list_name()
        try:
            lists = self._trello_board_lists(key, token, board_id)
        except Exception:
            return normalized_value

        if normalized_value:
            for item in lists:
                list_id = self._normalize_trello_id(str(item.get("id") or ""))
                if list_id and list_id == normalized_value:
                    return list_id

        target_key = self._compact_match_text(target_name)
        for item in lists:
            list_name = str(item.get("name") or "").strip()
            if list_name and self._compact_match_text(list_name) == target_key:
                return self._normalize_trello_id(str(item.get("id") or ""))

        return normalized_value if normalized_value else ""

    def _trello_matching_image_card_on_board(
        self,
        key: str,
        token: str,
        board_id: str,
        items: List[Dict[str, Any]],
        list_id: str = "",
    ) -> Dict[str, Any]:
        board_id = self._normalize_trello_board_id(board_id)
        list_id = self._normalize_trello_id(list_id)
        if not board_id or not list_id or not items:
            return {}
        payload = self._trello_get_json(
            f"boards/{quote(board_id, safe='')}/cards",
            key,
            token,
            fields={"fields": "id,name,shortLink,url,idList,closed", "filter": "open"},
        )
        cards = [card for card in payload if isinstance(card, dict) and not card.get("closed")] if isinstance(payload, list) else []
        attachment_cache: Dict[str, bool] = {}
        for item in items:
            for card in cards:
                card_list_id = self._normalize_trello_id(str(card.get("idList") or ""))
                if list_id and card_list_id != list_id:
                    continue
                hint = {
                    "card_id": str(card.get("id") or card.get("shortLink") or "").strip(),
                    "card_name": str(card.get("name") or "").strip(),
                    "list_id": card_list_id,
                }
                if not self._prompt_batch_item_matches_trello_source(item, hint):
                    continue
                card_id = str(card.get("id") or card.get("shortLink") or "").strip()
                if not card_id:
                    continue
                if card_id not in attachment_cache:
                    attachments_payload = self._trello_get_json(
                        f"cards/{quote(card_id, safe='')}/attachments",
                        key,
                        token,
                        fields={"fields": "id,name,url,mimeType"},
                    )
                    attachments = attachments_payload if isinstance(attachments_payload, list) else []
                    attachment_cache[card_id] = any(
                        self._trello_attachment_is_image(attachment)
                        for attachment in attachments
                        if isinstance(attachment, dict)
                    )
                if attachment_cache[card_id]:
                    return card
        return {}

    def _trello_prompt_items_for_image_cards(
        self,
        request: CreateJobRequest,
        items: List[Dict[str, Any]],
        limit: int,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        key, token = self._trello_credentials()
        if not key or not token:
            raise RuntimeError("Auto Trello cần API key/token Trello để quét card có ảnh.")

        trello_config = self.store.snapshot().trello_config
        board_id = self._normalize_trello_board_id(
            request.trello_board_id
            or trello_config.board_id
            or os.getenv("TRELLO_BOARD_ID", "")
        )
        if not board_id:
            raise RuntimeError("Auto Trello cần Board URL/Board ID để tìm card có ảnh.")

        raw_list_id = self._normalize_trello_id(
            request.trello_list_id
            or trello_config.list_id
            or os.getenv("TRELLO_LIST_ID", "")
        )
        explicit_card_id = self._normalize_trello_card_id(request.trello_card_id)
        selected_attachment_ids = self._normalize_trello_attachment_ids(request.trello_attachment_ids)
        list_id = self._trello_resolve_board_list_id(key, token, board_id, raw_list_id)
        if not list_id:
            if not explicit_card_id:
                raise RuntimeError(
                    f"Auto Trello chỉ quét cột {self._default_trello_source_list_name()}. "
                    "Hãy tạo/chọn đúng list này trong cục Trello Image Source để tránh lấy nhầm ảnh từ cột khác."
                )
        max_items = max(1, min(self.MAX_PROMPT_BATCH_ITEMS, int(limit or self.MAX_PROMPT_BATCH_ITEMS)))
        if explicit_card_id:
            selected_card = self._trello_image_card_by_id(key, token, explicit_card_id)
            if not selected_card:
                raise RuntimeError(
                    "Card Trello đã chọn chưa có attachment ảnh hoặc app không đọc được card đó. "
                    "App đã dừng để tránh lấy nhầm ảnh từ card khác."
                )
            if selected_attachment_ids and not self._select_trello_card_attachments(selected_card, selected_attachment_ids):
                raise RuntimeError(
                    "Ảnh Trello đã chọn không nằm trên card đã chọn hoặc không phải attachment ảnh. "
                    "App đã dừng để tránh dùng nhầm ảnh khác trong card."
                )
            cards = [selected_card]
            card_list_id = self._normalize_trello_id(str(selected_card.get("idList") or ""))
            if card_list_id:
                list_id = card_list_id
        else:
            cards = self._trello_image_cards_on_board(key, token, board_id, list_id)
        expanded: List[Dict[str, Any]] = []
        used_pairs: set[tuple[str, int, str]] = set()

        if not items:
            expanded = self._trello_ai_prompt_items_for_image_cards(cards, request, max_items)
            if not expanded:
                raise RuntimeError(
                    "Auto Trello chưa tìm thấy card ảnh phù hợp để AI tự viết prompt. "
                    "Hãy chọn card trong trợ lý, dán link card Trello, hoặc điền Lọc sản phẩm rõ hơn."
                )
            discovery = {
                "mode": "auto_trello",
                "board_id": board_id,
                "list_id": list_id,
                "list_name": self._trello_list_name(key, token, list_id),
                "matched_cards": len({item.get("trello_card_id") for item in expanded if item.get("trello_card_id")}),
                "matched_items": len(expanded),
                "match_mode": "ai_prompt",
                "prompt_mode": "ai_generated",
            }
            return expanded, discovery

        for card in cards:
            card_id = str(card.get("id") or card.get("shortLink") or "").strip()
            if not card_id:
                continue
            card_list_id = self._normalize_trello_id(str(card.get("idList") or list_id or ""))
            hint = {
                "card_id": card_id,
                "card_name": str(card.get("name") or "").strip(),
                "card_short_link": str(card.get("shortLink") or "").strip(),
                "card_url": str(card.get("url") or "").strip(),
                "list_id": card_list_id,
            }
            for item in items:
                if not self._prompt_batch_item_matches_trello_source(item, hint):
                    continue
                item_key = (card_id, int(item.get("row") or 0), str(item.get("index") or ""))
                if item_key in used_pairs:
                    continue
                used_pairs.add(item_key)
                expanded.append(
                    {
                        **item,
                        "trello_card_id": card_id,
                        "trello_list_id": card_list_id,
                        "trello_card_name": hint["card_name"],
                        "trello_card_url": hint["card_url"],
                    }
                )
                if len(expanded) >= max_items:
                    break
            if len(expanded) >= max_items:
                break

        if not expanded:
            expanded = self._trello_prompt_items_for_keyword_image_cards(cards, items, request, max_items)

        if not expanded:
            raise RuntimeError(
                "Auto Trello chưa tìm thấy card nào có attachment ảnh khớp Product_Key/Product_Name hoặc từ khóa tìm Trello."
            )

        discovery = {
            "mode": "auto_trello",
            "board_id": board_id,
            "list_id": list_id,
            "list_name": self._trello_list_name(key, token, list_id),
            "matched_cards": len({item.get("trello_card_id") for item in expanded if item.get("trello_card_id")}),
            "matched_items": len(expanded),
            "match_mode": "keyword" if any(item.get("trello_match_mode") == "keyword" for item in expanded) else "product",
        }
        return expanded, discovery

    def _flow_operator_card_product_signals(self, request: CreateJobRequest, card: Dict[str, Any]) -> Dict[str, Any]:
        card_name = str(card.get("name") or "").strip()
        query = self._trello_auto_search_query(request)
        attachment_names = ", ".join(
            str(item.get("name") or "").strip()
            for item in (card.get("_image_attachments") or [])[:4]
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        )
        primary_raw = " ".join([card_name, query, attachment_names]).strip()
        user_instruction = str(request.prompt or "").strip()
        raw = primary_raw or user_instruction
        normalized = self._normalize_skill_token(raw)
        compact = self._compact_match_text(raw)
        tokens = set(self._tokenize_match_words(raw))
        is_child_shirt = (
            ("ao" in tokens or "shirt" in tokens or "tshirt" in tokens or "tee" in tokens)
            and (
                bool({"tre", "em", "kid", "kids", "baby", "child", "children", "youth", "toddler"} & tokens)
                or "treem" in compact
            )
        )
        return {
            "card_name": card_name,
            "card_url": str(card.get("url") or "").strip(),
            "query": query,
            "attachment_names": attachment_names,
            "normalized": normalized,
            "compact": compact,
            "is_apron": any(term in normalized for term in ("tap_de", "apron")) or "tapde" in compact,
            "is_doll": any(term in normalized for term in ("bup_be", "bupbe", "doll", "baby_doll", "babydoll", "bda")),
            "is_plush": any(term in normalized for term in ("gau_bong", "gaubong", "plush", "stuffed", "stuffed_animal", "teddy", "bear", "gau")),
            "is_child_shirt": is_child_shirt,
            "is_shirt": any(term in normalized for term in ("ao", "shirt", "tshirt", "tee")),
            "is_embroidery": any(term in normalized for term in ("theu", "embroider", "embroidery", "handmade", "hand_made")),
            "is_baking": any(term in normalized for term in ("baking", "bakery", "kitchen", "nau_an", "lam_banh")),
        }

    def _flow_operator_relevant_user_instruction_for_trello_card(self, request: CreateJobRequest, card: Dict[str, Any]) -> str:
        instruction = re.sub(r"\s+", " ", str(request.prompt or "").strip())
        if not instruction:
            return ""
        query = self._trello_auto_search_query(request)
        if not query:
            return instruction

        instruction_normalized = self._normalize_skill_token(instruction)
        instruction_compact = self._compact_match_text(instruction)
        card_name = str(card.get("name") or "").strip()
        candidates = [query, card_name, *self._trello_query_aliases(query)]
        for candidate in candidates:
            candidate = str(candidate or "").strip()
            if not candidate:
                continue
            candidate_normalized = self._normalize_skill_token(candidate)
            candidate_compact = self._compact_match_text(candidate)
            if candidate_normalized and candidate_normalized in instruction_normalized:
                return instruction
            if candidate_compact and candidate_compact in instruction_compact:
                return instruction

        # Khi AI chạy theo thumbnail đã chọn, ô prompt có thể còn prompt cũ từ lần trước.
        # Nếu prompt cũ không nhắc tới sản phẩm đang lọc, bỏ qua để tránh đổi sai loại hàng.
        return ""

    def _flow_operator_design_analysis_for_trello_card(self, request: CreateJobRequest, card: Dict[str, Any]) -> str:
        signals = self._flow_operator_card_product_signals(request, card)
        card_name = str(signals.get("card_name") or "").strip()
        card_url = str(signals.get("card_url") or "").strip()
        attachment_names = str(signals.get("attachment_names") or "").strip()

        product_bits: List[str] = []
        if signals.get("is_apron"):
            product_bits.append("apron silhouette, chest bib, waist tie, shoulder/neck straps, hem length, and fit")
        elif signals.get("is_doll"):
            product_bits.append("doll body shape, face, hair/clothing/accessories, fabric texture, proportions, and collectible toy identity")
        elif signals.get("is_plush"):
            product_bits.append("plush toy silhouette, soft fabric pile, stitched seams, facial features, stuffing volume, and cuddly product scale")
        elif signals.get("is_child_shirt"):
            product_bits.append("children shirt silhouette, collar/sleeves/hem, print placement, fabric texture, size scale, and kid-safe styling")
        elif signals.get("is_shirt"):
            product_bits.append("shirt silhouette, front print placement, neckline, sleeves, fabric texture, fit, and apparel scale")
        if signals.get("is_embroidery"):
            product_bits.append("hand-embroidered thread texture, stitch direction, raised thread, motif placement, and handmade craft cues")
        if signals.get("is_baking"):
            product_bits.append("warm bakery/kitchen context, baking tools, flour, pastry props, and clean food-safe styling")
        if not product_bits:
            product_bits.append("product type, base color, material texture, print/embroidery details, silhouette, scale, and hero features")

        visible_sources = ", ".join(part for part in [card_name, attachment_names] if part)
        source_hint = f" Visible Trello clues: {visible_sources}." if visible_sources else ""
        if card_url:
            source_hint += f" Source card: {card_url}."
        return (
            "Before creating images, carefully analyze the selected Trello reference image for "
            + "; ".join(product_bits)
            + ". Keep those design features consistent across the whole image set."
            + source_hint
        )

    def _flow_operator_shot_suite_for_trello_card(
        self,
        request: CreateJobRequest,
        card: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        signals = self._flow_operator_card_product_signals(request, card)
        is_apron = bool(signals.get("is_apron"))
        is_embroidery = bool(signals.get("is_embroidery"))

        if is_apron:
            return [
                {
                    "label": "Hand embroidery detail",
                    "brief": (
                        "Extreme macro close-up of the embroidered area on the apron, showing individual thread fibers, "
                        "raised stitches, needlework texture, and handmade irregularities; this shot must clearly prove the product is hand-embroidered."
                    ),
                    "must_include": "hand-embroidered stitches, visible thread texture, close-up craft detail, selected apron reference design",
                },
                {
                    "label": "Full front hero",
                    "brief": "Full front product hero shot of the apron worn by a model or displayed on a form, showing the complete silhouette, bib, straps, waist, skirt/hem, and embroidery placement.",
                    "must_include": "full apron front, complete fit, embroidery visible, clean premium product photography",
                },
                {
                    "label": "Lifestyle baking action",
                    "brief": "Lifestyle image in a warm bakery or home kitchen, model wearing the apron while decorating pastries or preparing dough, natural movement and believable cooking context.",
                    "must_include": "apron in use, baking props, warm kitchen light, embroidery still visible",
                },
                {
                    "label": "Back tie fit",
                    "brief": "Back or three-quarter view showing apron straps, waist tie, fabric drape, ruffle/edge details if present, and how the apron fits on the body.",
                    "must_include": "back tie, straps, fabric drape, fit detail",
                },
                {
                    "label": "Flat lay styling",
                    "brief": "Overhead flat lay of the apron neatly arranged on a light wooden or linen surface with tasteful baking and craft props around it.",
                    "must_include": "full apron layout, embroidery placement, baking props, clean editorial styling",
                },
                {
                    "label": "Gift artisan scene",
                    "brief": "Artisan gift-ready scene with the apron folded partly open beside embroidery thread, needle, linen ribbon, dried flowers or baking tools, communicating handmade premium quality.",
                    "must_include": "handmade craft props, premium gift presentation, apron embroidery visible",
                },
            ]

        if signals.get("is_doll") or signals.get("is_plush"):
            craft_detail = (
                "Extreme macro close-up of the embroidered or hand-stitched detail on the selected doll/plush, showing thread fibers, seams, fabric pile, "
                "raised stitching, and handmade irregularities; this shot must clearly prove the product craft quality."
                if is_embroidery
                else "Extreme close-up detail of the selected doll/plush material, seams, fabric pile, face, clothing/accessories, and handmade construction cues."
            )
            return [
                {
                    "label": "Craft detail proof",
                    "brief": craft_detail,
                    "must_include": "selected doll/plush reference design, close-up craft detail, fabric texture, seams or embroidery",
                },
                {
                    "label": "Full collection hero",
                    "brief": "Clean full product hero shot showing the entire doll/plush shape, face, clothing/accessories, color palette, scale, and main design feature.",
                    "must_include": "full doll/plush product, exact source identity, clean commercial hero composition",
                },
                {
                    "label": "Lifestyle nursery scene",
                    "brief": "Warm lifestyle product photo in a nursery, playroom, child's bedroom, or gift setting where the doll/plush feels natural and premium.",
                    "must_include": "doll/plush in use, soft child-friendly styling, realistic natural light",
                },
                {
                    "label": "Angle and scale",
                    "brief": "Three-quarter or side angle showing depth, soft volume, stitching, accessories, and realistic scale beside simple child-safe props.",
                    "must_include": "alternate angle, depth, scale cue, construction details",
                },
                {
                    "label": "Flat lay styling",
                    "brief": "Overhead flat lay of the doll/plush arranged neatly on a light wooden or linen surface with tasteful toys, ribbon, name tag, or gift props.",
                    "must_include": "flat lay, full product layout, tasteful toy/gift props",
                },
                {
                    "label": "Gift ready scene",
                    "brief": "Premium gift-ready scene with the doll/plush beside wrapping tissue, ribbon, small card, or keepsake box while preserving the source product identity.",
                    "must_include": "premium gift presentation, doll/plush details visible, clean commercial finish",
                },
            ]

        if signals.get("is_child_shirt") or signals.get("is_shirt"):
            return [
                {
                    "label": "Print detail proof",
                    "brief": "Close-up detail shot of the shirt print/embroidery, fabric weave, ink/thread texture, and edge finish without changing the selected design.",
                    "must_include": "source shirt design, print or embroidery detail, visible fabric texture",
                },
                {
                    "label": "Full front apparel hero",
                    "brief": "Clean full-front apparel product hero showing the shirt shape, neckline, sleeves, hem, print placement, and color exactly from the reference.",
                    "must_include": "full shirt front, exact source design, clean ecommerce composition",
                },
                {
                    "label": "Lifestyle worn shot",
                    "brief": "Realistic model/lifestyle image with the shirt worn naturally in a fitting setting while keeping the print/design visible and undistorted.",
                    "must_include": "shirt worn naturally, design readable, realistic light",
                },
                {
                    "label": "Folded product angle",
                    "brief": "Alternate angle or folded product shot showing fabric thickness, sleeve/hem detail, and premium merchandising styling.",
                    "must_include": "alternate angle, apparel construction, source design visible",
                },
                {
                    "label": "Flat lay styling",
                    "brief": "Overhead flat lay of the shirt arranged neatly with tasteful props matching the product theme.",
                    "must_include": "flat lay, full shirt layout, editorial props",
                },
                {
                    "label": "Gift ready scene",
                    "brief": "Premium packaging or gift-ready apparel scene with folded shirt, tissue paper, tag, or box.",
                    "must_include": "gift presentation, shirt details, clean commercial finish",
                },
            ]

        return [
            {
                "label": "Detail craft proof",
                "brief": "Extreme close-up detail shot of the most important product craftsmanship, material texture, stitching, print/embroidery, edge finish, or surface detail.",
                "must_include": "macro craftsmanship detail, selected Trello reference product, visible material texture",
            },
            {
                "label": "Full front hero",
                "brief": "Clean full product hero shot showing the entire product shape, key design, color, proportions, and main visual feature.",
                "must_include": "full product, clean hero composition, exact source design",
            },
            {
                "label": "Lifestyle use",
                "brief": "Lifestyle scene showing the product being used naturally in a fitting environment, with realistic light and commercial styling.",
                "must_include": "product in use, believable environment, source product identity",
            },
            {
                "label": "Angle and fit",
                "brief": "Three-quarter or alternate angle showing depth, fit, side/back detail, and construction that the front hero does not reveal.",
                "must_include": "alternate angle, construction details, product depth",
            },
            {
                "label": "Flat lay",
                "brief": "Overhead flat lay with the product arranged neatly with tasteful props that match the product story.",
                "must_include": "flat lay, full product layout, editorial props",
            },
            {
                "label": "Gift ready",
                "brief": "Premium packaging or gift-ready scene that makes the product feel handmade, valuable, and ready to sell.",
                "must_include": "premium presentation, product details, clean commercial finish",
            },
        ]

    def _flow_operator_prompt_for_trello_card(
        self,
        request: CreateJobRequest,
        card: Dict[str, Any],
        index: int,
        shot: Dict[str, str] | None = None,
        design_analysis: str = "",
    ) -> str:
        card_name = str(card.get("name") or "").strip()
        card_url = str(card.get("url") or "").strip()
        query = self._trello_auto_search_query(request)
        user_instruction = self._flow_operator_relevant_user_instruction_for_trello_card(request, card)
        product_hint = query or card_name or f"card Trello {index + 1}"
        shot = shot or {}
        shot_label = str(shot.get("label") or f"Shot {index}").strip()
        shot_brief = str(shot.get("brief") or "").strip()
        design_analysis = design_analysis or self._flow_operator_design_analysis_for_trello_card(request, card)
        brief_parts = [
            design_analysis,
            f"Use the selected Trello attachment from card '{card_name or card_url or index + 1}' as the exact source product reference.",
            f"Shot {index} - {shot_label}: {shot_brief}" if shot_brief else f"Shot {index}: create a distinct commercial product image.",
            f"Create or edit a commercial product image for {product_hint}.",
            "Preserve the original product shape, print/design details, colors, fabric/material texture, and product identity.",
            "Only change the scene, styling, lighting, composition, model/background, and presentation around the source product.",
        ]
        if user_instruction:
            brief_parts.append(f"User automation instruction: {user_instruction}.")
        if card_url:
            brief_parts.append(f"Source card: {card_url}.")
        prompt_request = PromptCreateRequest(
            mode="image",
            brief=" ".join(brief_parts),
            style="photorealistic ecommerce product photography, clean commercial styling, realistic lighting",
            must_include=(
                "selected Trello attachment/reference image, exact source product, believable product photo, "
                f"clear hero composition, Telegram approval ready, {shot.get('must_include') or shot_label}"
            ),
            avoid="wrong product, unrelated design, extra text, watermark, distorted logo, deformed product, low quality",
            audience="automation review in Telegram and archive back to the same Trello card",
            aspect=request.aspect or "square",
        )
        selected = self._select_prompt_skills("image", prompt_request.brief, prompt_request.style, prompt_request.must_include)
        baseline = self._compose_prompt_draft(prompt_request, selected)
        prompt = baseline
        if self._gemini_api_key():
            try:
                prompt = self._generate_prompt_with_gemini(prompt_request, selected, baseline)
            except Exception:
                prompt = baseline
        prompt, _ = self._ensure_prompt_detail(prompt, baseline, "image")
        return prompt

    def _trello_ai_prompt_items_for_image_cards(
        self,
        cards: List[Dict[str, Any]],
        request: CreateJobRequest,
        max_items: int,
    ) -> List[Dict[str, Any]]:
        query = self._trello_auto_search_query(request)
        matched_cards = cards
        if query:
            matched_cards = [card for card in cards if self._trello_card_matches_query(card, query)]
            if not matched_cards:
                if len(cards) == 1:
                    matched_cards = cards
                else:
                    return []
        expanded: List[Dict[str, Any]] = []
        for card in matched_cards:
            if len(expanded) >= max_items:
                break
            card_id = str(card.get("id") or card.get("shortLink") or "").strip()
            if not card_id:
                continue
            card_list_id = self._normalize_trello_id(str(card.get("idList") or request.trello_list_id or ""))
            card_name = str(card.get("name") or "").strip()
            card_url = str(card.get("url") or "").strip()
            selected_attachment_ids = self._normalize_trello_attachment_ids(card.get("_selected_attachment_ids") or request.trello_attachment_ids)
            design_analysis = self._flow_operator_design_analysis_for_trello_card(request, card)
            shots = self._flow_operator_shot_suite_for_trello_card(request, card)
            remaining = max_items - len(expanded)
            for shot in shots[: max(1, min(self.AI_PROMPT_SUITE_SIZE, remaining))]:
                prompt = self._flow_operator_prompt_for_trello_card(
                    request,
                    card,
                    len(expanded) + 1,
                    shot=shot,
                    design_analysis=design_analysis,
                )
                expanded.append(
                    {
                        "row": 0,
                        "active": True,
                        "used": False,
                        "prompt": prompt,
                        "product": query or card_name,
                        "product_key": query or str(card.get("shortLink") or card_id).strip(),
                        "product_name": card_name,
                        "index": str(len(expanded) + 1),
                        "notes": f"{design_analysis} Shot: {shot.get('label') or 'AI image'}. Google Sheet prompt not required.",
                        "trello_card_id": card_id,
                        "trello_list_id": card_list_id,
                        "trello_attachment_ids": selected_attachment_ids,
                        "trello_card_name": card_name,
                        "trello_card_url": card_url,
                        "trello_match_mode": "ai_prompt",
                        "trello_search_query": query,
                        "shot_label": shot.get("label") or "",
                        "design_analysis": design_analysis,
                        "generated_by_ai": True,
                    }
                )
                if len(expanded) >= max_items:
                    break
        return expanded

    def _trello_query_aliases(self, query: str) -> List[str]:
        aliases = [str(query or "").strip()]
        normalized = self._normalize_skill_token(query)
        compact = self._compact_match_text(query)
        tokens = set(self._tokenize_match_words(query))
        is_child_shirt_query = (
            ("ao" in tokens or "shirt" in tokens or "tshirt" in tokens or "tee" in tokens)
            and (
                bool({"tre", "em", "kid", "kids", "baby", "child", "children", "youth", "toddler"} & tokens)
                or "treem" in compact
            )
        )
        alias_groups = [
            (("tap_de", "tapde", "apron"), ("apron", "baking apron", "kitchen apron", "tap de")),
            (("theu", "embroider", "embroidery"), ("embroidered", "embroidery", "hand embroidered", "handmade")),
            (("gau", "gau_bong", "gaubong"), ("bear", "teddy bear", "plush", "stuffed toy")),
            (("bup_be", "bupbe", "doll", "baby_doll", "babydoll", "bda"), ("doll", "baby doll", "BDA", "doll dress", "baby doll dress")),
            (("ao_tre_em", "aotreem"), ("kids shirt", "children shirt", "baby shirt", "youth tee")),
            (("ao", "shirt", "tshirt"), ("shirt", "tshirt", "tee")),
        ]
        for triggers, values in alias_groups:
            if is_child_shirt_query and triggers == ("ao", "shirt", "tshirt"):
                continue
            if any(trigger in normalized or trigger in compact for trigger in triggers):
                aliases.extend(values)
        unique: List[str] = []
        seen: set[str] = set()
        for alias in aliases:
            cleaned = re.sub(r"\s+", " ", str(alias or "").strip())
            key = self._compact_match_text(cleaned)
            if not cleaned or key in seen:
                continue
            seen.add(key)
            unique.append(cleaned)
        return unique

    def _trello_prompt_items_for_keyword_image_cards(
        self,
        cards: List[Dict[str, Any]],
        items: List[Dict[str, Any]],
        request: CreateJobRequest,
        max_items: int,
    ) -> List[Dict[str, Any]]:
        query = self._trello_auto_search_query(request)
        if not query or not cards or not items:
            return []

        matched_cards = [card for card in cards if self._trello_card_matches_query(card, query)]
        if not matched_cards:
            return []
        explicit_card_id = self._normalize_trello_card_id(request.trello_card_id)
        if len(matched_cards) > 1 and not explicit_card_id:
            names = ", ".join(str(card.get("name") or card.get("url") or card.get("id") or "").strip() for card in matched_cards[:5])
            raise RuntimeError(
                "Auto Trello tìm thấy nhiều card cùng khớp từ khóa. "
                f"Hãy dán đúng link card Trello hoặc đổi tên card rõ hơn trước khi chạy: {names}"
            )

        expanded: List[Dict[str, Any]] = []
        used_pairs: set[tuple[str, int, str]] = set()
        for card in matched_cards:
            card_id = str(card.get("id") or card.get("shortLink") or "").strip()
            if not card_id:
                continue
            card_list_id = self._normalize_trello_id(str(card.get("idList") or ""))
            selected_attachment_ids = self._normalize_trello_attachment_ids(card.get("_selected_attachment_ids") or request.trello_attachment_ids)
            item = self._best_prompt_item_for_trello_keyword_card(card, items, used_pairs, query)
            if not item:
                card_name = str(card.get("name") or card.get("url") or card_id).strip()
                raise RuntimeError(
                    "Auto Trello đã tìm thấy card ảnh nhưng chưa tìm thấy prompt Active khớp card/từ khóa. "
                    f"Card: {card_name}. Hãy thêm Product_Key/Product_Name/Notes khớp trong sheet hoặc thêm Trello_Card/Card_URL."
                )
            used_pairs.add((card_id, int(item.get("row") or 0), str(item.get("index") or "")))
            expanded.append(
                {
                    **item,
                    "trello_card_id": card_id,
                    "trello_list_id": card_list_id,
                    "trello_attachment_ids": selected_attachment_ids,
                    "trello_card_name": str(card.get("name") or "").strip(),
                    "trello_card_url": str(card.get("url") or "").strip(),
                    "trello_match_mode": "keyword",
                    "trello_search_query": query,
                }
            )
            if len(expanded) >= max_items:
                break
        return expanded

    def _trello_auto_search_query(self, request: CreateJobRequest) -> str:
        for value in (
            request.prompt_product_key,
            request.prompt_product,
            request.prompt_notes,
            request.title,
        ):
            cleaned = str(value or "").strip()
            if cleaned:
                return cleaned[:80]
        return ""

    def _trello_card_matches_query(self, card: Dict[str, Any], query: str) -> bool:
        query_aliases = [self._compact_match_text(alias) for alias in self._trello_query_aliases(query)]
        query_aliases = [alias for alias in query_aliases if alias]
        if not query_aliases:
            return False
        haystack_values = [
            card.get("name"),
            card.get("desc"),
            card.get("url"),
        ]
        for attachment in card.get("_image_attachments") or []:
            if isinstance(attachment, dict):
                haystack_values.extend([attachment.get("name"), attachment.get("url")])
        haystack = self._compact_match_text(" ".join(str(value or "") for value in haystack_values))
        return any(alias in haystack or haystack in alias for alias in query_aliases)

    def _best_prompt_item_for_trello_keyword_card(
        self,
        card: Dict[str, Any],
        items: List[Dict[str, Any]],
        used_pairs: set[tuple[str, int, str]],
        query: str,
    ) -> Dict[str, Any]:
        card_id = str(card.get("id") or card.get("shortLink") or "").strip()
        for item in items:
            item_key = (card_id, int(item.get("row") or 0), str(item.get("index") or ""))
            if item_key in used_pairs:
                continue
            hint = {"card_id": card_id, "card_name": str(card.get("name") or "").strip()}
            if self._prompt_batch_item_matches_trello_source(item, hint):
                return item
        for item in items:
            item_key = (card_id, int(item.get("row") or 0), str(item.get("index") or ""))
            if item_key not in used_pairs and self._prompt_batch_item_matches_query(item, query):
                return item
        return {}

    def _prompt_batch_item_matches_query(self, item: Dict[str, Any], query: str) -> bool:
        query_key = self._compact_match_text(query)
        if not query_key:
            return False
        query_groups = self._user_assistant_trello_query_groups(query)
        for value in (
            item.get("product_key"),
            item.get("product_name"),
            item.get("product"),
            item.get("notes"),
            item.get("trello_card_id"),
        ):
            candidate = self._compact_match_text(value)
            if candidate and (query_key in candidate or candidate in query_key):
                return True
            candidate_tokens = set(self._tokenize_match_words(value))
            if candidate_tokens and any(group and all(token in candidate_tokens for token in group) for group in query_groups):
                return True
        return False

    def _trello_image_cards_on_board(
        self,
        key: str,
        token: str,
        board_id: str,
        list_id: str = "",
    ) -> List[Dict[str, Any]]:
        board_id = self._normalize_trello_board_id(board_id)
        list_id = self._normalize_trello_id(list_id)
        if not board_id or not list_id:
            return []
        payload = self._trello_get_json(
            f"boards/{quote(board_id, safe='')}/cards",
            key,
            token,
            fields={"fields": "id,name,desc,shortLink,url,idList,closed", "filter": "open"},
        )
        cards = payload if isinstance(payload, list) else []
        image_cards: List[Dict[str, Any]] = []
        for card in cards:
            if not isinstance(card, dict) or card.get("closed"):
                continue
            card_id = str(card.get("id") or card.get("shortLink") or "").strip()
            if not card_id:
                continue
            if list_id and self._normalize_trello_id(str(card.get("idList") or "")) != list_id:
                continue
            attachments_payload = self._trello_get_json(
                f"cards/{quote(card_id, safe='')}/attachments",
                key,
                token,
                fields={"fields": "id,name,url,mimeType"},
            )
            attachments = attachments_payload if isinstance(attachments_payload, list) else []
            image_attachments = [
                item for item in attachments if isinstance(item, dict) and self._trello_attachment_is_image(item)
            ]
            if image_attachments:
                card["_image_attachments"] = image_attachments
                image_cards.append(card)
        return image_cards

    def _trello_first_image_card_on_board(
        self,
        key: str,
        token: str,
        board_id: str,
        list_id: str = "",
    ) -> Dict[str, Any]:
        cards = self._trello_image_cards_on_board(key, token, board_id, list_id)
        return cards[0] if cards else {}

    def _trello_attachment_is_image(self, attachment: Dict[str, Any]) -> bool:
        name = str(attachment.get("name") or "").lower()
        mime = str(attachment.get("mimeType") or "").lower()
        return mime.startswith("image/") or Path(name).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}

    def _trello_download_attachment_bytes(
        self,
        key: str,
        token: str,
        card_id: str,
        attachment: Dict[str, Any],
    ) -> tuple[bytes, str]:
        attachment_id = str(attachment.get("id") or "").strip()
        name = str(attachment.get("name") or "image.jpg").strip() or "image.jpg"
        mime = str(attachment.get("mimeType") or mimetypes.guess_type(name)[0] or "image/jpeg")
        if attachment_id:
            path = (
                f"cards/{quote(card_id, safe='')}/attachments/"
                f"{quote(attachment_id, safe='')}/download/{quote(name)}"
            )
            request = Request(self._trello_endpoint(path, key, token), method="GET")
            try:
                with urlopen(request, timeout=self.TRELLO_TIMEOUT_S) as response:
                    return response.read(), response.headers.get_content_type() if response.headers else mime
            except Exception:
                pass
        url = str(attachment.get("url") or "").strip()
        if not url:
            raise RuntimeError(f"Attachment Trello {name} không có URL để tải.")
        return self._read_remote_file(url)

    def _trello_request_json(
        self,
        path: str,
        key: str,
        token: str,
        *,
        fields: Dict[str, Any] | None = None,
        data: bytes | None = None,
        headers: Dict[str, str] | None = None,
    ) -> Any:
        payload = data
        request_headers = {"Accept": "application/json", **(headers or {})}
        if payload is None:
            payload = urlencode({k: v for k, v in (fields or {}).items() if str(v) != ""}).encode("utf-8")
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"

        request = Request(
            self._trello_endpoint(path, key, token),
            data=payload,
            headers=request_headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.TRELLO_TIMEOUT_S) as response:
                raw_payload = response.read().decode("utf-8", errors="replace")
                return json.loads(raw_payload) if raw_payload else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Trello API lỗi {exc.code}: {detail or exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(str(exc.reason or exc)) from exc

    def _trello_create_card(self, key: str, token: str, list_id: str, name: str, description: str) -> Dict[str, Any]:
        payload = self._trello_request_json(
            "cards",
            key,
            token,
            fields={
                "idList": list_id,
                "name": name,
                "desc": description,
                "pos": "top",
            },
        )
        return payload if isinstance(payload, dict) else {}

    def _trello_attach_url(
        self,
        key: str,
        token: str,
        card_id: str,
        artifact_url: str,
        name: str,
        set_cover: bool,
    ) -> Dict[str, Any]:
        payload = self._trello_request_json(
            f"cards/{quote(card_id, safe='')}/attachments",
            key,
            token,
            fields={
                "name": name,
                "url": artifact_url,
                "setCover": "true" if set_cover else "false",
            },
        )
        if isinstance(payload, list):
            return payload[0] if payload else {}
        return payload if isinstance(payload, dict) else {}

    def _trello_attach_file_from_url(
        self,
        key: str,
        token: str,
        card_id: str,
        artifact_url: str,
        name: str,
        mime_type: str,
        set_cover: bool,
    ) -> Dict[str, Any]:
        file_bytes, detected_mime = self._read_remote_file(artifact_url)
        mime = detected_mime or mime_type or mimetypes.guess_type(name)[0] or "image/jpeg"
        return self._trello_attach_file_bytes(
            key,
            token,
            card_id,
            file_bytes,
            mime,
            name,
            set_cover,
        )

    def _trello_attach_file_bytes(
        self,
        key: str,
        token: str,
        card_id: str,
        file_bytes: bytes,
        mime_type: str,
        name: str,
        set_cover: bool,
    ) -> Dict[str, Any]:
        mime = mime_type or mimetypes.guess_type(name)[0] or "image/jpeg"
        body, content_type = self._multipart_form_data(
            fields={
                "name": name,
                "mimeType": mime,
                "setCover": "true" if set_cover else "false",
            },
            file_field="file",
            file_name=name,
            file_mime=mime,
            file_bytes=file_bytes,
        )
        payload = self._trello_request_json(
            f"cards/{quote(card_id, safe='')}/attachments",
            key,
            token,
            data=body,
            headers={"Content-Type": content_type},
        )
        if isinstance(payload, list):
            return payload[0] if payload else {}
        return payload if isinstance(payload, dict) else {}

    # ── Flow image upsampler (POST /v1/flow/upsampleImage) ──────────────────
    # Confirmed via captured DevTools request (2026-05): the endpoint accepts
    # ``{"encodedImage": <base64 JPEG>}`` and returns an upscaled JPEG in the
    # same field. The response is treated defensively in ``_extract_encoded_image``
    # so wrapping objects like ``{"image": {"encodedImage": ...}}`` also work.

    async def _upsample_image_via_flow(self, client: Any, jpeg_bytes: bytes) -> bytes:
        """Call POST /v1/flow/upsampleImage and return the upscaled JPEG bytes.

        Returns the original bytes on any failure so the caller can still
        upload the source image.
        """
        if not jpeg_bytes:
            return jpeg_bytes
        try:
            import base64 as _b64
            encoded_in = _b64.b64encode(jpeg_bytes).decode("ascii")
            data = await client._api._fetch(
                "POST",
                "flow/upsampleImage",
                {"encodedImage": encoded_in},
            )
        except Exception as exc:
            log.warning("flow/upsampleImage failed: %s", self._flow_error_detail(exc))
            return jpeg_bytes
        encoded_out = self._extract_encoded_image(data)
        if not encoded_out:
            log.warning(
                "flow/upsampleImage: response missing encodedImage field (keys=%s)",
                list(data.keys()) if isinstance(data, dict) else type(data).__name__,
            )
            return jpeg_bytes
        try:
            return _b64.b64decode(encoded_out)
        except Exception as exc:
            log.warning("flow/upsampleImage: base64 decode failed: %s", exc)
            return jpeg_bytes

    def _extract_encoded_image(self, payload: Any) -> str:
        """Recursively find the first ``encodedImage`` string in a JSON tree."""
        if isinstance(payload, dict):
            candidate = payload.get("encodedImage")
            if isinstance(candidate, str) and candidate:
                return candidate
            for value in payload.values():
                found = self._extract_encoded_image(value)
                if found:
                    return found
        elif isinstance(payload, list):
            for item in payload:
                found = self._extract_encoded_image(item)
                if found:
                    return found
        return ""

    async def _upsample_artifact_bytes(
        self,
        artifact: JobArtifact,
        artifact_url: str,
    ) -> tuple[Optional[bytes], str]:
        """Fetch an artifact and upsample it via flow/upsampleImage.

        Returns ``(upscaled_bytes, mime)`` on success, or ``(None, "")`` if the
        source bytes could not be fetched. JPEG is preferred since the Flow
        upsampler expects an encoded JPEG payload.
        """
        local_path = str(artifact.local_path or "").strip()
        source_bytes: bytes = b""
        source_mime = str(artifact.mime_type or "").strip()
        if local_path and Path(local_path).expanduser().is_file():
            try:
                source_bytes = Path(local_path).expanduser().read_bytes()
                if not source_mime:
                    source_mime = mimetypes.guess_type(local_path)[0] or "image/jpeg"
            except Exception:
                source_bytes = b""
        if not source_bytes:
            source_bytes, detected_mime = await asyncio.to_thread(
                self._read_remote_file, artifact_url
            )
            source_mime = source_mime or detected_mime or "image/jpeg"
        if not source_bytes:
            return None, ""

        workflow_id = str(artifact.workflow_id or "").strip()

        async def _go(client: Any) -> bytes:
            return await self._upsample_image_via_flow(client, source_bytes)

        upscaled = await self._with_client(_go, workflow_id=workflow_id)
        if not upscaled or upscaled == source_bytes:
            return None, ""
        # The Flow upsampler returns JPEG bytes regardless of input mime.
        return upscaled, "image/jpeg"

    def _read_remote_file(self, url: str) -> tuple[bytes, str]:
        request = Request(url, headers={"User-Agent": "FlowWebUI/0.1"})
        try:
            with urlopen(request, timeout=self.TRELLO_TIMEOUT_S) as response:
                content_type = response.headers.get_content_type() if response.headers else ""
                return response.read(), content_type
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Không tải được ảnh nguồn ({exc.code}): {detail or exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(str(exc.reason or exc)) from exc

    def _multipart_form_data(
        self,
        *,
        fields: Dict[str, Any],
        file_field: str,
        file_name: str,
        file_mime: str,
        file_bytes: bytes,
    ) -> tuple[bytes, str]:
        boundary = f"----flowweb{uuid.uuid4().hex}"
        body = bytearray()
        for key, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'
                f"Content-Type: {file_mime}\r\n\r\n"
            ).encode("utf-8")
        )
        body.extend(file_bytes)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))
        return bytes(body), f"multipart/form-data; boundary={boundary}"

    def _trello_attachment_summary(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(payload.get("id") or "").strip(),
            "name": str(payload.get("name") or "").strip(),
            "url": str(payload.get("url") or "").strip(),
        }

    async def _send_telegram_review_pack(
        self,
        job_id: str,
        request: CreateJobRequest,
        artifacts: List[JobArtifact],
    ) -> Dict[str, Any]:
        if request.type != "image" or not artifacts or not request.telegram_enabled:
            return {}

        token, chat_id = self._telegram_credentials(request.telegram_chat_id)
        if not token or not chat_id:
            return {"configured": False}

        sent = 0
        failed = 0
        messages: List[Dict[str, Any]] = []
        for index, artifact in enumerate(artifacts):
            photo_source = await self._telegram_photo_source(job_id, artifact, index)
            if not photo_source:
                failed += 1
                continue
            caption = self._telegram_review_caption(job_id, request, artifact, index)
            reply_markup = self._telegram_approval_reply_markup(job_id, index)
            try:
                message_payload = await asyncio.to_thread(
                    self._send_telegram_photo,
                    token,
                    chat_id,
                    photo_source,
                    caption,
                    reply_markup,
                )
                sent += 1
                messages.append(
                    {
                        "artifact_index": index,
                        "message_id": str(message_payload.get("message_id") or ""),
                        "chat_id": chat_id,
                        "status": "pending",
                    }
                )
            except Exception as exc:
                failed += 1
                await self.store.append_log(
                    job_id,
                    f"Không gửi được ảnh {index + 1} sang Telegram: {humanize_flow_error(str(exc))}",
                )

        if sent:
            await self.store.append_log(job_id, f"Đã gửi {sent} ảnh sang Telegram để duyệt.")
        return {
            "configured": True,
            "sent": sent,
            "failed": failed,
            "chat_id": chat_id,
            "pending_approvals": sent,
            "messages": messages,
        }

    async def _telegram_photo_source(self, job_id: str, artifact: JobArtifact, artifact_index: int) -> str:
        local_path = str(artifact.local_path or "").strip()
        if local_path and Path(local_path).expanduser().is_file():
            return local_path

        remote_url = str(artifact.url or artifact.public_url or "").strip()
        if not remote_url:
            return ""
        if not self._telegram_requires_file_upload(remote_url):
            return remote_url

        try:
            return await self._materialize_artifact_file(job_id, artifact, artifact_index)
        except Exception as exc:
            await self.store.append_log(
                job_id,
                f"Không tải được ảnh {artifact_index + 1} về máy trước khi gửi Telegram: {humanize_flow_error(str(exc))}",
            )
            return remote_url

    def _telegram_requires_file_upload(self, url: str) -> bool:
        parsed = urlparse(str(url or "").strip())
        return parsed.netloc.endswith("labs.google")

    async def _materialize_artifact_file(self, job_id: str, artifact: JobArtifact, artifact_index: int) -> str:
        local_path = str(artifact.local_path or "").strip()
        if local_path and Path(local_path).expanduser().is_file():
            return local_path

        source = str(artifact.url or artifact.public_url or "").strip()
        if not source:
            return ""

        job = self.store.get_job(job_id)
        if job is not None:
            file_name = self._download_name(job, artifact, artifact_index)
        else:
            file_name = f"{job_id}-{artifact_index + 1}.jpg"
        destination = self._download_root() / file_name
        destination.parent.mkdir(parents=True, exist_ok=True)

        async def _go(client: Any) -> str:
            saved = await client.download(source, destination)
            return str(saved)

        workflow_id = str(artifact.workflow_id or "").strip()
        if not workflow_id and job is not None and isinstance(job.input, dict):
            workflow_id = str(job.input.get("workflow_id") or "").strip()
        local_path = await self._with_client(_go, workflow_id=workflow_id)
        artifact.local_path = local_path
        artifact.public_url = self._public_download_url(local_path)
        if job is not None:
            await self.store.replace_artifacts(job_id, job.artifacts)
        return local_path

    def _telegram_credentials(self, requested_chat_id: str = "") -> tuple[str, str]:
        config = self.store.snapshot().integration_config
        token = str(config.telegram_bot_token or "").strip() or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = (
            str(requested_chat_id or "").strip()
            or str(config.telegram_chat_id or "").strip()
            or os.getenv("TELEGRAM_CHAT_ID", "").strip()
        )
        return token, chat_id

    def _telegram_review_caption(
        self,
        job_id: str,
        request: CreateJobRequest,
        artifact: JobArtifact,
        index: int,
    ) -> str:
        prompt = str(artifact.prompt or request.prompt or "").strip()
        if len(prompt) > 780:
            prompt = f"{prompt[:777]}..."
        parts = [
            f"Flow image #{index + 1}",
            f"Job: {job_id[:8]}",
        ]
        if prompt:
            parts.append(f"Prompt: {prompt}")
        parts.append("Bấm Duyệt hoặc Từ chối bên dưới. Sau đó quay lại app bấm Đồng bộ duyệt Telegram.")
        return "\n".join(parts)

    def _telegram_approval_reply_markup(self, job_id: str, artifact_index: int) -> Dict[str, Any]:
        safe_index = max(0, int(artifact_index))
        return {
            "inline_keyboard": [
                [
                    {
                        "text": "✅ Duyệt",
                        "callback_data": f"fw:approve:{job_id}:{safe_index}",
                    },
                    {
                        "text": "❌ Từ chối",
                        "callback_data": f"fw:reject:{job_id}:{safe_index}",
                    },
                ]
            ]
        }

    def _send_telegram_photo(
        self,
        token: str,
        chat_id: str,
        photo_url: str,
        caption: str,
        reply_markup: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        endpoint = self.TELEGRAM_API_URL_TEMPLATE.format(token=quote(token, safe=":"), method="sendPhoto")
        local_photo = Path(str(photo_url or "")).expanduser()
        if local_photo.is_file():
            fields: Dict[str, Any] = {
                "chat_id": chat_id,
                "caption": caption,
            }
            if reply_markup:
                fields["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
            mime = mimetypes.guess_type(local_photo.name)[0] or "image/jpeg"
            body, content_type = self._multipart_form_data(
                fields=fields,
                file_field="photo",
                file_name=local_photo.name,
                file_mime=mime,
                file_bytes=local_photo.read_bytes(),
            )
            request = Request(
                endpoint,
                data=body,
                headers={"Content-Type": content_type},
                method="POST",
            )
        else:
            payload: Dict[str, Any] = {
                "chat_id": chat_id,
                "photo": photo_url,
                "caption": caption,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            body = json.dumps(payload).encode("utf-8")
            request = Request(
                endpoint,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        try:
            with urlopen(request, timeout=self.TELEGRAM_TIMEOUT_S) as response:
                payload = response.read().decode("utf-8", errors="replace")
                data = json.loads(payload) if payload else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(detail or str(exc)) from exc
        except URLError as exc:
            raise RuntimeError(str(exc.reason or exc)) from exc

        if not data.get("ok", False):
            raise RuntimeError(str(data.get("description") or "Telegram không nhận ảnh."))
        result = data.get("result")
        return result if isinstance(result, dict) else {}

    async def run_telegram_approval_sync_loop(self, interval_s: float = 5.0) -> None:
        interval = max(0.1, float(interval_s or 5.0))
        while True:
            try:
                await self.sync_telegram_approvals()
                self._last_telegram_approval_sync_error = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_telegram_approval_sync_error = humanize_flow_error(str(exc))
            await asyncio.sleep(interval)

    async def sync_telegram_approvals(self) -> Dict[str, Any]:
        async with self._telegram_approval_sync_lock:
            result = await self._sync_telegram_approvals_unlocked()
            if result.get("configured") is not False:
                result["last_error"] = self._last_telegram_approval_sync_error
            return result

    async def _sync_telegram_approvals_unlocked(self) -> Dict[str, Any]:
        token, _ = self._telegram_credentials("")
        if not token:
            return {"configured": False, "processed": 0, "approvals": []}

        updates = await asyncio.to_thread(self._telegram_get_updates, token)
        max_update_id = -1
        approvals: List[Dict[str, Any]] = []
        for update in updates:
            try:
                max_update_id = max(max_update_id, int(update.get("update_id", -1)))
            except Exception:
                pass
            callback = update.get("callback_query") if isinstance(update, dict) else None
            parsed = self._parse_telegram_approval_callback(callback or {})
            if not parsed:
                continue
            approval = await self._apply_telegram_approval(
                parsed["job_id"],
                parsed["artifact_index"],
                parsed["status"],
                callback or {},
            )
            if approval:
                approvals.append(approval)
                callback_id = str((callback or {}).get("id") or "").strip()
                if callback_id:
                    await asyncio.to_thread(
                        self._telegram_answer_callback_query,
                        token,
                        callback_id,
                        "Đã ghi nhận duyệt ảnh." if parsed["status"] == "approved" else "Đã ghi nhận từ chối ảnh.",
                    )

        if max_update_id >= 0:
            await asyncio.to_thread(self._telegram_get_updates, token, max_update_id + 1)

        return {
            "configured": True,
            "processed": len(approvals),
            "approvals": approvals,
        }

    def _telegram_get_updates(self, token: str, offset: int | None = None) -> List[Dict[str, Any]]:
        endpoint = self.TELEGRAM_API_URL_TEMPLATE.format(token=quote(token, safe=":"), method="getUpdates")
        payload: Dict[str, Any] = {
            "timeout": 0,
            "allowed_updates": ["callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.TELEGRAM_TIMEOUT_S) as response:
                raw_payload = response.read().decode("utf-8", errors="replace")
                data = json.loads(raw_payload) if raw_payload else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(detail or str(exc)) from exc
        except URLError as exc:
            raise RuntimeError(str(exc.reason or exc)) from exc
        if not data.get("ok", False):
            raise RuntimeError(str(data.get("description") or "Telegram không trả callback."))
        result = data.get("result")
        return result if isinstance(result, list) else []

    def _telegram_answer_callback_query(self, token: str, callback_query_id: str, text: str) -> None:
        endpoint = self.TELEGRAM_API_URL_TEMPLATE.format(token=quote(token, safe=":"), method="answerCallbackQuery")
        body = json.dumps(
            {
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": False,
            }
        ).encode("utf-8")
        request = Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.TELEGRAM_TIMEOUT_S) as response:
                payload = response.read().decode("utf-8", errors="replace")
                data = json.loads(payload) if payload else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(detail or str(exc)) from exc
        except URLError as exc:
            raise RuntimeError(str(exc.reason or exc)) from exc
        if not data.get("ok", False):
            raise RuntimeError(str(data.get("description") or "Telegram không xác nhận callback."))

    def _parse_telegram_approval_callback(self, callback: Dict[str, Any]) -> Dict[str, Any]:
        data = str(callback.get("data") or "").strip()
        parts = data.split(":")
        if len(parts) != 4 or parts[0] != "fw" or parts[1] not in {"approve", "reject"}:
            return {}
        try:
            artifact_index = int(parts[3])
        except ValueError:
            return {}
        if artifact_index < 0:
            return {}
        return {
            "status": "approved" if parts[1] == "approve" else "rejected",
            "job_id": parts[2],
            "artifact_index": artifact_index,
        }

    async def _apply_telegram_approval(
        self,
        job_id: str,
        artifact_index: int,
        status: str,
        callback: Dict[str, Any],
    ) -> Dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None or artifact_index < 0 or artifact_index >= len(job.artifacts):
            return {}

        result = dict(job.result or {})
        approvals = dict(result.get("telegram_approvals") or {})
        key = str(artifact_index)
        previous = approvals.get(key) if isinstance(approvals.get(key), dict) else {}
        previous_status = str(previous.get("status") or "").strip()
        if previous_status in {"approved", "rejected"}:
            if previous_status != status:
                reviewer = self._telegram_callback_reviewer(callback)
                reviewer_name = reviewer.get("name") or reviewer.get("username") or "Telegram user"
                previous_label = "đã duyệt" if previous_status == "approved" else "đã từ chối"
                await self.store.append_log(
                    job_id,
                    f"Bỏ qua phản hồi Telegram của {reviewer_name} vì ảnh {artifact_index + 1} {previous_label} trước đó.",
                )
            return previous
        reviewer = self._telegram_callback_reviewer(callback)
        message = callback.get("message") if isinstance(callback.get("message"), dict) else {}
        approval = {
            "artifact_index": artifact_index,
            "status": status,
            "reviewer": reviewer,
            "callback_query_id": str(callback.get("id") or "").strip(),
            "message_id": str(message.get("message_id") or "").strip(),
            "chat_id": str((message.get("chat") or {}).get("id") or "").strip()
            if isinstance(message.get("chat"), dict)
            else "",
            "updated_at": utc_now(),
        }
        approvals[key] = approval
        result["telegram_approvals"] = approvals
        summary = self._telegram_approval_summary(approvals, len(job.artifacts))
        result["telegram_approval_summary"] = summary
        approval_module_id = self._sync_automation_approval_execution(result, summary, len(job.artifacts))
        await self.store.patch_job(job_id, result=result)

        if previous.get("status") != status:
            label = "đã duyệt" if status == "approved" else "đã từ chối"
            reviewer_name = reviewer.get("name") or reviewer.get("username") or "Telegram user"
            await self.store.append_log(job_id, f"{reviewer_name} {label} ảnh {artifact_index + 1} trên Telegram.")
        if approval_module_id and summary.get("pending") == 0:
            await self._resume_automation_after_approval(job_id, approval_module_id)
        return approval

    def _telegram_callback_reviewer(self, callback: Dict[str, Any]) -> Dict[str, Any]:
        user = callback.get("from") if isinstance(callback.get("from"), dict) else {}
        first = str(user.get("first_name") or "").strip()
        last = str(user.get("last_name") or "").strip()
        username = str(user.get("username") or "").strip()
        return {
            "id": str(user.get("id") or "").strip(),
            "name": " ".join(part for part in [first, last] if part).strip(),
            "username": username,
        }

    def _telegram_approval_summary(self, approvals: Dict[str, Any], artifact_count: int) -> Dict[str, Any]:
        approved = 0
        rejected = 0
        pending = max(0, artifact_count)
        for value in approvals.values():
            if not isinstance(value, dict):
                continue
            if value.get("status") == "approved":
                approved += 1
            elif value.get("status") == "rejected":
                rejected += 1
        resolved = approved + rejected
        pending = max(0, artifact_count - resolved)
        return {
            "total": artifact_count,
            "approved": approved,
            "rejected": rejected,
            "pending": pending,
            "resolved": resolved,
            "status": "completed" if artifact_count and resolved >= artifact_count else "waiting",
        }

    def _sync_automation_approval_execution(
        self,
        result: Dict[str, Any],
        summary: Dict[str, Any],
        artifact_count: int,
    ) -> str:
        execution = result.get("automation_execution")
        if not isinstance(execution, dict) or not isinstance(execution.get("nodes"), list):
            return ""
        nodes = execution["nodes"]
        approval_node = next((node for node in nodes if node.get("type") == "approval"), None)
        if not approval_node:
            return ""
        now = utc_now()
        approval_node["status"] = "completed" if summary.get("pending") == 0 and artifact_count else "running"
        approval_node["output"] = {
            "awaiting_user_approval": summary.get("pending", 0) > 0,
            "telegram_approval_summary": summary,
        }
        if not approval_node.get("started_at"):
            approval_node["started_at"] = now
        if approval_node["status"] == "completed":
            approval_node["completed_at"] = now
        execution["current_module_id"] = approval_node.get("id", "") if approval_node["status"] == "running" else ""
        execution["completed"] = all(
            str(node.get("status") or "") in {"completed", "skipped", "disabled"}
            for node in nodes
        )
        return str(approval_node.get("id") or "")

    def _build_video_artifacts(
        self,
        video_jobs: List[Any],
        statuses: List[Any],
        request: CreateJobRequest,
        *,
        default_label: str = "",
    ) -> tuple[List[JobArtifact], List[str]]:
        artifacts: List[JobArtifact] = []
        missing_labels: List[str] = []

        for index, (job, status) in enumerate(zip(video_jobs, statuses)):
            label = default_label or f"Video {index + 1}"
            media_name = str(getattr(job, "media_name", "") or "").strip()
            url = self._video_status_url(status, media_name=media_name)
            if not url:
                missing_labels.append(label)
                continue

            artifacts.append(
                JobArtifact(
                    label=label,
                    media_name=media_name,
                    url=url,
                    workflow_id=getattr(job, "workflow_id", request.workflow_id),
                    mime_type="video/mp4",
                    prompt=request.prompt,
                )
            )

        return artifacts, missing_labels

    def _video_status_url(self, status: Any, *, media_name: str = "") -> str:
        candidates = (
            getattr(status, "fife_url", ""),
            getattr(status, "download_url", ""),
            getattr(status, "url", ""),
        )
        for candidate in candidates:
            value = str(candidate or "").strip()
            if value:
                return value
        raw_status = getattr(status, "_raw", {}) or {}
        raw_media = raw_status.get("media", []) if isinstance(raw_status, dict) else []
        for media_item in raw_media or []:
            if not isinstance(media_item, dict):
                continue
            video_payload = media_item.get("video", {})
            if not isinstance(video_payload, dict):
                continue
            generated = video_payload.get("generatedVideo", {})
            if isinstance(generated, dict):
                for key in ("fifeUrl", "downloadUrl", "url"):
                    value = str(generated.get(key) or "").strip()
                    if value:
                        return value
                output_video = generated.get("outputVideo", {})
                if isinstance(output_video, dict):
                    for key in ("fifeUrl", "downloadUrl", "url"):
                        value = str(output_video.get(key) or "").strip()
                        if value:
                            return value
        fallback_media_name = str(media_name or getattr(status, "media_name", "") or "").strip()
        if fallback_media_name:
            return f"https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name={quote(fallback_media_name)}"
        return ""

    def _is_audio_generation_failure(self, message: str) -> bool:
        lowered = str(message or "").strip().lower()
        if not lowered:
            return False
        return (
            "audio generation failed" in lowered
            or "return silent videos" in lowered
            or ("audio" in lowered and "failed" in lowered)
            or ("audio" in lowered and "silent" in lowered)
            or "phần tạo audio bị lỗi" in lowered
            or "âm thanh bị lỗi" in lowered
            or "video im lặng" in lowered
            or "model không audio" in lowered
        )

    def _audio_fallback_video_model(self, model: str) -> str:
        normalized = self._normalize_video_model(model)
        mapping = {
            "Veo 3.1 - Fast": "Veo 2 - Fast",
            "Veo 3.1 - Quality": "Veo 2 - Quality",
            "Veo 3.1 - Fast [Lower Priority]": "Veo 2 - Fast",
        }
        fallback = mapping.get(normalized, "")
        if fallback == normalized:
            return ""
        return fallback

    def _video_status_failure_detail(self, status: Any) -> str:
        raw_status = getattr(status, "_raw", {}) or {}
        if not isinstance(raw_status, dict):
            return ""

        preferred_fields = {
            "message",
            "messages",
            "detail",
            "details",
            "error",
            "errors",
            "errormessage",
            "failuremessage",
            "failurereason",
            "reason",
            "description",
            "statusmessage",
            "usermessage",
            "userfacingmessage",
            "localizedmessage",
            "displaymessage",
            "title",
        }
        seen: set[str] = set()
        audio_messages: list[str] = []
        preferred_messages: list[str] = []
        generic_messages: list[str] = []

        def add_message(target: list[str], value: str) -> None:
            normalized = " ".join(str(value or "").split()).strip()
            if not normalized:
                return
            lowered = normalized.lower()
            if lowered in seen:
                return
            if lowered in {
                "media_generation_status_failed",
                "media_generation_status_rejected",
                "failed",
                "rejected",
            }:
                return
            seen.add(lowered)
            target.append(normalized)

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    key_lower = str(key or "").strip().lower()
                    if isinstance(value, str):
                        lowered = value.strip().lower()
                        if self._is_audio_generation_failure(value):
                            add_message(audio_messages, value)
                        elif key_lower in preferred_fields:
                            add_message(preferred_messages, value)
                        elif any(token in lowered for token in ("failed", "error", "rejected")):
                            add_message(generic_messages, value)
                    else:
                        visit(value)
            elif isinstance(node, list):
                for item in node:
                    visit(item)

        visit(raw_status)

        if audio_messages:
            return " ".join(audio_messages[:2])
        if preferred_messages:
            return preferred_messages[0]
        if generic_messages:
            return generic_messages[0]
        return ""

    async def _with_client(
        self,
        fn: Callable[[Any], Any],
        workflow_id: str = "",
        timeout_s: int = 0,
    ) -> Any:
        FlowClient, _, _, _, _ = self._flow_modules(client_only=True)
        config = self._normalized_config(self.store.snapshot().config)
        if not config.project_id:
            raise HTTPException(status_code=400, detail="Mã project là bắt buộc.")
        effective_timeout_s = max(30, int(timeout_s or config.generation_timeout_s))
        resolved_workflow_id = workflow_id or config.active_workflow_id or None

        if self._should_keep_flow_browser_open(config):
            async with self._browser_session_lock:
                try:
                    browser = await self._ensure_shared_browser()
                    client = await self._build_client_from_shared_browser(
                        browser,
                        project_id=config.project_id,
                        workflow_id=resolved_workflow_id,
                        timeout_s=effective_timeout_s,
                    )
                    return await fn(client)
                except HTTPException:
                    raise
                except Exception as exc:
                    if self._is_browser_closed_error(exc):
                        await self._close_shared_browser()
                    raise HTTPException(
                        status_code=self._flow_error_status(exc),
                        detail=self._flow_error_detail(exc),
                    ) from exc

        try:
            client = await FlowClient.create(
                project_id=config.project_id,
                workflow_id=resolved_workflow_id,
                headless=config.headless,
                cdp_url=config.cdp_url or None,
                timeout_s=effective_timeout_s,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=self._flow_error_status(exc),
                detail=self._flow_error_detail(exc),
            ) from exc
        try:
            return await fn(client)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=self._flow_error_status(exc),
                detail=self._flow_error_detail(exc),
            ) from exc
        finally:
            await client.close()

    def _should_keep_flow_browser_open(self, config: AppConfig) -> bool:
        return not config.headless and not config.cdp_url

    async def _close_shared_browser(self) -> None:
        browser = self._shared_browser
        self._shared_browser = None
        if browser is None:
            return
        try:
            await browser.stop()
        except Exception:
            pass

    async def _shared_browser_is_usable(self) -> bool:
        browser = self._shared_browser
        if browser is None or getattr(browser, "_ctx", None) is None:
            return False
        try:
            page = await browser.page()
            if page.is_closed():
                return False
            await page.evaluate("() => document.readyState")
            return True
        except Exception:
            return False

    async def _ensure_shared_browser(self) -> Any:
        if await self._shared_browser_is_usable():
            return self._shared_browser
        await self._close_shared_browser()
        BrowserManager, _, _, _, _ = self._flow_modules()
        browser = BrowserManager(headless=False)
        await browser.start()
        config = self.store.snapshot().config
        project_id = self._normalize_project_id(config.project_id or config.project_url)
        target_url = self._project_url(project_id) if project_id else "https://labs.google/fx/tools/flow"
        await self._close_placeholder_flow_tabs(browser, target_url)
        self._shared_browser = browser
        return browser

    async def _build_client_from_shared_browser(
        self,
        browser: Any,
        *,
        project_id: str,
        workflow_id: str | None,
        timeout_s: int,
    ) -> Any:
        self._patch_flow_runtime_compat()
        from flow._api import FlowAPI
        from flow._client import FlowClient

        api = FlowAPI(browser, project_id=project_id, default_timeout_s=timeout_s)
        client = FlowClient(api, browser, project_id, workflow_id)
        client.workflow_id = workflow_id
        client._project_url = self._project_url(project_id)

        target_url = client._project_url
        await self._repair_placeholder_flow_tabs(browser, target_url)
        page = await self._acquire_fresh_flow_page(browser, target_url)
        await self._ensure_valid_flow_project_page(page, target_url)
        return client

    def _is_browser_closed_error(self, exc: Exception) -> bool:
        detail = str(exc or "").lower()
        needles = (
            "target page, context or browser has been closed",
            "browser has been closed",
            "context closed",
            "page closed",
        )
        return any(needle in detail for needle in needles)

    def _sync_project_to_flow_storage(self, config: AppConfig) -> None:
        project_id = self._normalize_project_id(config.project_id or config.project_url)
        if not project_id:
            return
        _, _, _, _, sync_project = self._flow_modules()
        sync_project(project_id, config.project_name or "web-ui", self._project_url(project_id))

    def _flow_modules(
        self,
        client_only: bool = False,
    ) -> Any:
        self._patch_flow_runtime_compat()
        from flow._client import FlowClient

        if client_only:
            return FlowClient, None, None, None, None

        from flow._browser import BrowserManager
        from flow._storage import add_project, get_active_project, is_authenticated, load_projects, set_active_project

        def sync_project(project_id: str, project_name: str, project_url: str) -> None:
            set_active_project(project_id, project_url)
            add_project(project_id, project_name, project_url)

        return BrowserManager, is_authenticated, load_projects, get_active_project, sync_project

    def _patch_flow_runtime_compat(self) -> None:
        if self.__class__._FLOW_RUNTIME_PATCHED:
            return

        from flow._api import FlowAPI, GeneratedImage, VideoJob, RECAPTCHA_SITE_KEY
        from flow._client import FlowClient
        from flow._flow_ui import FlowUI
        from flow._models import AspectRatio, GenerationMode
        from flow._ui_interceptor import UIInterceptor

        async def _compat_settings_visible(_self: Any, page: Any) -> bool:
            return bool(await page.evaluate(
                """
                () => {
                  const menus = [...document.querySelectorAll('[role="menu"]')];
                  return menus.some(el => {
                    const style = window.getComputedStyle(el);
                    const text = (el.textContent || '').trim().toLowerCase();
                    return style.display !== 'none'
                      && style.visibility !== 'hidden'
                      && (text.includes('image') || text.includes('hình ảnh') || text.includes('hinh anh'))
                      && text.includes('video')
                      && /x[1-4]/.test(text);
                  });
                }
                """
            ))

        async def _compat_find_create_options_trigger_index(page: Any) -> int:
            index = await page.evaluate(
                """
                () => {
                  const buttons = [...document.querySelectorAll('button[aria-haspopup="menu"]')];
                  const candidates = buttons
                    .map((button, index) => {
                      const text = (button.textContent || '').trim();
                      const rect = button.getBoundingClientRect();
                      const style = window.getComputedStyle(button);
                      return {
                        index,
                        text,
                        top: rect.top,
                        visible: rect.width > 0
                          && rect.height > 0
                          && style.display !== 'none'
                          && style.visibility !== 'hidden',
                      };
                    })
                    .filter(item => item.visible && /(x[1-4]|Nano Banana|Veo|Imagen|Video|Image|🍌)/i.test(item.text))
                    .sort((a, b) => a.top - b.top);
                  return candidates.length ? candidates[candidates.length - 1].index : -1;
                }
                """
            )
            try:
                return int(index)
            except Exception:
                return -1

        async def _compat_find_tabbed_menu_index(page: Any) -> int:
            index = await page.evaluate(
                """
                () => {
                  const menus = [...document.querySelectorAll('[role="menu"]')];
                  const candidates = menus
                    .map((menu, index) => {
                      const style = window.getComputedStyle(menu);
                      const rect = menu.getBoundingClientRect();
                      const tabs = [...menu.querySelectorAll('[role="tab"]')].filter((tab) => {
                        const tabStyle = window.getComputedStyle(tab);
                        const tabRect = tab.getBoundingClientRect();
                        return tabRect.width > 0
                          && tabRect.height > 0
                          && tabStyle.display !== 'none'
                          && tabStyle.visibility !== 'hidden';
                      });
                      return {
                        index,
                        top: rect.top,
                        visible: rect.width > 0
                          && rect.height > 0
                          && style.display !== 'none'
                          && style.visibility !== 'hidden',
                        tabCount: tabs.length,
                      };
                    })
                    .filter((item) => item.visible && item.tabCount > 0)
                    .sort((a, b) => a.top - b.top);
                  return candidates.length ? candidates[candidates.length - 1].index : -1;
                }
                """
            )
            try:
                return int(index)
            except Exception:
                return -1

        async def _compat_get_tabbed_menu(page: Any) -> Any | None:
            index = await _compat_find_tabbed_menu_index(page)
            if index < 0:
                return None
            return page.locator('[role="menu"]').nth(index)

        async def _compat_wait_for_new_call(
            interceptor: Any,
            start_index: int,
            endpoint_tail: str,
            *,
            timeout_s: float,
            fail_on_tails: Optional[List[str]] = None,
        ) -> Any:
            deadline = time.monotonic() + timeout_s
            seen_tails: List[str] = []
            fail_on = [str(item or "") for item in (fail_on_tails or []) if str(item or "")]
            best_match = None
            settle_deadline = 0.0

            def _response_weight(call: Any) -> int:
                if not isinstance(getattr(call, "resp", None), dict):
                    return 0
                resp = call.resp or {}
                return (
                    len(resp.get("jobs", []) or [])
                    + len(resp.get("media", []) or [])
                    + len(resp.get("workflows", []) or [])
                )

            while time.monotonic() < deadline:
                completed = [
                    call
                    for call in getattr(interceptor, "_calls", [])[start_index:]
                    if call.resp is not None
                ]
                if completed:
                    seen_tails = [str(call.tail or "") for call in completed]
                for call in reversed(completed):
                    tail = str(call.tail or "")
                    if any(fragment in tail for fragment in fail_on):
                        raise RuntimeError(
                            "Google Flow đã gửi nhầm endpoint cho thao tác hiện tại. "
                            f"Captured: {tail}"
                        )
                    if endpoint_tail not in tail:
                        continue
                    if call.status not in (200, 201):
                        message = ""
                        if isinstance(call.resp, dict):
                            message = str(((call.resp.get("error") or {}).get("message")) or "").strip()
                        raise RuntimeError(
                            f"{endpoint_tail} failed [{call.status}]: {message or tail}"
                        )
                    if best_match is None or _response_weight(call) >= _response_weight(best_match):
                        best_match = call
                        settle_deadline = time.monotonic() + 1.0
                if best_match is not None and time.monotonic() >= settle_deadline:
                    return best_match
                await asyncio.sleep(0.25)
            raise RuntimeError(
                f"Timed out ({timeout_s}s) waiting for {endpoint_tail}. Captured so far: {seen_tails}"
            )

        async def _compat_wait_for_video_submit_call(
            interceptor: Any,
            start_index: int,
            *,
            timeout_s: float,
            expect_start_image: bool,
        ) -> Any:
            deadline = time.monotonic() + timeout_s
            seen_tails: List[str] = []
            best_match = None
            settle_deadline = 0.0

            def _response_weight(call: Any) -> int:
                if not isinstance(getattr(call, "resp", None), dict):
                    return 0
                resp = call.resp or {}
                return (
                    len(resp.get("jobs", []) or [])
                    + len(resp.get("media", []) or [])
                    + len(resp.get("workflows", []) or [])
                )

            while time.monotonic() < deadline:
                completed = [
                    call
                    for call in getattr(interceptor, "_calls", [])[start_index:]
                    if call.resp is not None
                ]
                if completed:
                    seen_tails = [str(call.tail or "") for call in completed]

                for call in reversed(completed):
                    tail = str(call.tail or "")
                    normalized = tail.lower()
                    if "generatevideo" not in normalized:
                        continue
                    if call.status not in (200, 201):
                        continue
                    if expect_start_image and "text" in normalized:
                        raise RuntimeError(
                            "Google Flow đã gửi nhầm sang text-to-video. Ảnh đầu vào nhiều khả năng chưa được gắn vào Start."
                        )
                    if expect_start_image and not isinstance(getattr(call, "resp", None), dict):
                        continue
                    if expect_start_image and _response_weight(call) == 0:
                        continue
                    if best_match is None or _response_weight(call) >= _response_weight(best_match):
                        best_match = call
                        settle_deadline = time.monotonic() + 1.0

                if best_match is not None and time.monotonic() >= settle_deadline:
                    return best_match
                await asyncio.sleep(0.25)

            label = "image-to-video" if expect_start_image else "text-to-video"
            raise RuntimeError(
                f"Timed out ({timeout_s}s) waiting for {label} submit response. Captured so far: {seen_tails}"
            )

        async def _compat_click_menu_trigger(page: Any) -> bool:
            index = await _compat_find_create_options_trigger_index(page)
            if index < 0:
                return False
            trigger = page.locator('button[aria-haspopup="menu"]').nth(index)
            try:
                await trigger.click(force=True)
            except Exception:
                return False
            await asyncio.sleep(0.5)
            return True

        async def _compat_open_settings_panel(_self: Any, page: Any) -> bool:
            try:
                await page.wait_for_selector("button", timeout=8000)
            except Exception:
                pass
            await asyncio.sleep(0.5)

            if await _compat_settings_visible(_self, page):
                return True

            if await _compat_click_menu_trigger(page):
                await asyncio.sleep(1.0)
                if await _compat_settings_visible(_self, page):
                    return True

            return False

        async def _compat_click_menu_tab(page: Any, labels: List[str]) -> bool:
            menu = await _compat_get_tabbed_menu(page)
            if menu is None:
                return False
            for label in labels:
                wanted = str(label or "").strip().lower()
                tabs = menu.locator('[role="tab"]')
                count = await tabs.count()
                matched = False
                for index in range(count):
                    tab = tabs.nth(index)
                    try:
                        box = await tab.bounding_box()
                    except Exception:
                        box = None
                    if not box:
                        continue
                    text = str(await tab.text_content() or "").replace("\n", " ").strip().lower()
                    if wanted not in text:
                        continue
                    try:
                        await tab.click(force=True)
                    except Exception:
                        continue
                    matched = True
                    break
                if not matched:
                    continue
                await asyncio.sleep(0.45)
                selected_tabs = menu.locator('[role="tab"][aria-selected="true"]')
                selected_count = await selected_tabs.count()
                for selected_index in range(selected_count):
                    text = str(await selected_tabs.nth(selected_index).text_content() or "").replace("\n", " ").strip().lower()
                    if wanted in text:
                        return True
            return False

        async def _compat_click_visible_surface_control(page: Any, labels: List[str]) -> bool:
            wanted_labels = [str(label or "").strip() for label in labels if str(label or "").strip()]
            if not wanted_labels:
                return False

            locators = []
            for label in wanted_labels:
                pattern = re.compile(re.escape(label), re.I)
                locators.extend(
                    [
                        page.locator('[role="tab"]').filter(has_text=pattern),
                        page.locator('button').filter(has_text=pattern),
                        page.locator('[role="button"]').filter(has_text=pattern),
                        page.locator('div[type="button"]').filter(has_text=pattern),
                    ]
                )

            for locator in locators:
                candidate = await _compat_visible_locator(locator)
                if candidate is None:
                    continue
                try:
                    await candidate.scroll_into_view_if_needed()
                except Exception:
                    pass
                try:
                    await candidate.click(force=True)
                    await asyncio.sleep(0.5)
                    return True
                except Exception:
                    continue
            return False

        async def _compat_click_visible_menu_item(page: Any, wanted: str) -> bool:
            wanted = str(wanted or "").strip().lower()
            items = page.locator('[role="menuitem"]')
            count = await items.count()
            for index in range(count):
                item = items.nth(index)
                try:
                    box = await item.bounding_box()
                except Exception:
                    box = None
                if not box:
                    continue
                text = str(await item.text_content() or "").replace("\n", " ").strip().lower()
                if wanted not in text:
                    continue
                try:
                    await item.click(force=True)
                    return True
                except Exception:
                    continue
            return False

        async def _compat_fill_prompt(_self: Any, page: Any, prompt: str) -> bool:
            prompt = str(prompt or "").strip()
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.2)
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.2)
            except Exception:
                pass

            best = None
            best_is_input = False
            best_y = -1.0
            for selector, is_input in (
                ('div[role="textbox"][contenteditable="true"]', False),
                ('div[data-slate-editor="true"][contenteditable="true"]', False),
                ('div[contenteditable="true"]', False),
                ('textarea', True),
                ('input[type="text"]', True),
            ):
                locator = page.locator(selector)
                count = await locator.count()
                for index in range(count):
                    candidate = locator.nth(index)
                    try:
                        box = await candidate.bounding_box()
                    except Exception:
                        box = None
                    if not box:
                        continue
                    if box["width"] < 240 or box["height"] < 18 or box["y"] < 300:
                        continue
                    if box["y"] >= best_y:
                        best = candidate
                        best_is_input = is_input
                        best_y = float(box["y"])

            if best is None:
                return False

            await best.scroll_into_view_if_needed()
            await asyncio.sleep(0.1)
            await best.click(force=True)
            await asyncio.sleep(0.2)

            if best_is_input:
                try:
                    await best.fill(prompt)
                except Exception:
                    return False
                try:
                    value = await best.input_value()
                except Exception:
                    value = await best.text_content()
                return prompt[:20] in str(value or "")

            try:
                await page.keyboard.press("Meta+a")
                await page.keyboard.press("Control+a")
                await asyncio.sleep(0.05)
                await page.keyboard.press("Backspace")
                await asyncio.sleep(0.05)
                await page.keyboard.insert_text(prompt)
                await asyncio.sleep(0.2)
                content = await best.text_content()
                if prompt[:20] in str(content or ""):
                    return True
            except Exception:
                pass

            try:
                injected = await best.evaluate(
                    """
                    (el, value) => {
                      el.focus();
                      if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
                        el.value = value;
                      } else {
                        const paragraph = el.querySelector('[data-slate-node="element"]') || el.firstElementChild || el;
                        if (paragraph) {
                          paragraph.textContent = value;
                        }
                      }
                      el.dispatchEvent(new Event('input', { bubbles: true }));
                      el.dispatchEvent(new Event('change', { bubbles: true }));
                      return (el.textContent || el.value || '').trim();
                    }
                    """,
                    prompt,
                )
            except Exception:
                return False
            return prompt[:20] in str(injected or "")

        async def _compat_switch_mode(_self: Any, page: Any, mode: Any) -> bool:
            await _compat_open_settings_panel(_self, page)
            label_map = {
                GenerationMode.IMAGE: ["Image", "Hình ảnh", "Hinh anh"],
                GenerationMode.VIDEO: ["Video"],
                GenerationMode.FRAME_TO_VIDEO: ["Frames", "Frame", "Khung hình", "Khung"],
            }
            target_labels = label_map.get(mode, [])
            if await _compat_click_menu_tab(page, target_labels):
                return True

            if mode == GenerationMode.FRAME_TO_VIDEO:
                video_labels = label_map.get(GenerationMode.VIDEO, [])
                if await _compat_click_visible_surface_control(page, video_labels):
                    await _compat_open_settings_panel(_self, page)
                    if await _compat_click_menu_tab(page, target_labels):
                        return True
                if await _compat_click_visible_surface_control(page, target_labels):
                    return True
                await _compat_open_settings_panel(_self, page)
                return await _compat_click_menu_tab(page, target_labels)

            if await _compat_click_visible_surface_control(page, target_labels):
                return True

            await _compat_open_settings_panel(_self, page)
            return await _compat_click_menu_tab(page, target_labels)

        async def _compat_set_aspect_ratio(_self: Any, page: Any, ratio: Any) -> bool:
            await _compat_open_settings_panel(_self, page)
            label_map = {
                AspectRatio.LANDSCAPE: ["16:9", "Landscape"],
                AspectRatio.PORTRAIT: ["9:16", "Portrait"],
                AspectRatio.SQUARE: ["1:1", "Square"],
            }
            return await _compat_click_menu_tab(page, label_map.get(ratio, []))

        async def _compat_set_count(_self: Any, page: Any, count: int) -> bool:
            await _compat_open_settings_panel(_self, page)
            return await _compat_click_menu_tab(page, [f"x{max(1, min(4, count))}"])

        async def _compat_get_video_model_selector(_self: Any, page: Any) -> str:
            await _compat_open_settings_panel(_self, page)
            menu = await _compat_get_tabbed_menu(page)
            if menu is None:
                return ""
            button = menu.locator('button[aria-haspopup="menu"]').first
            if await button.count() > 0:
                return str((await button.text_content()) or "").replace("arrow_drop_down", "").strip()
            for label in ["Veo", "Nano Banana", "Imagen"]:
                locator = menu.locator("button").filter(has_text=label).first
                if await locator.count() > 0:
                    return str((await locator.text_content()) or "").replace("arrow_drop_down", "").strip()
            return ""

        async def _compat_select_video_model(_self: Any, page: Any, model_display_name: str) -> bool:
            await _compat_open_settings_panel(_self, page)
            menu = await _compat_get_tabbed_menu(page)
            if menu is None:
                return False
            current = await _compat_get_video_model_selector(_self, page)
            wanted = str(model_display_name or "").strip()
            if wanted and wanted.lower() in current.lower():
                return True

            model_button = menu.locator('button[aria-haspopup="menu"]').first
            if await model_button.count() > 0:
                await model_button.click(force=True)
                await asyncio.sleep(0.5)

            if not wanted:
                return bool(await _compat_get_video_model_selector(_self, page))

            matched = await _compat_click_visible_menu_item(page, wanted)
            if matched:
                await asyncio.sleep(0.5)
                return True
            return False

        async def _compat_get_image_model_selector(_self: Any, page: Any) -> str:
            await _compat_open_settings_panel(_self, page)
            menu = await _compat_get_tabbed_menu(page)
            if menu is None:
                return ""
            button = menu.locator('button[aria-haspopup="menu"]').first
            if await button.count() > 0:
                return str((await button.text_content()) or "").replace("arrow_drop_down", "").strip()
            for label in ["Nano Banana", "Imagen"]:
                locator = menu.locator("button").filter(has_text=label).first
                if await locator.count() > 0:
                    return str((await locator.text_content()) or "").replace("arrow_drop_down", "").strip()
            return ""

        async def _compat_select_image_model(_self: Any, page: Any, model_display_name: str) -> bool:
            await _compat_open_settings_panel(_self, page)
            menu = await _compat_get_tabbed_menu(page)
            if menu is None:
                return False
            current = await _compat_get_image_model_selector(_self, page)
            wanted = str(model_display_name or "").strip()
            if wanted and wanted.lower() in current.lower():
                return True

            model_button = menu.locator('button[aria-haspopup="menu"]').first
            if await model_button.count() > 0:
                await model_button.click(force=True)
                await asyncio.sleep(0.5)

            if not wanted:
                return bool(await _compat_get_image_model_selector(_self, page))

            matched = await _compat_click_visible_menu_item(page, wanted)
            if matched:
                await asyncio.sleep(0.5)
                return True
            return False

        async def _compat_upload_via_file_input(page: Any, image_path: str) -> bool:
            selectors = [
                'input[type="file"][accept*="image"]',
                'input[type="file"]',
            ]
            for selector in selectors:
                locator = page.locator(selector)
                count = await locator.count()
                for index in range(count):
                    candidate = locator.nth(index)
                    try:
                        await candidate.set_input_files(image_path)
                        return True
                    except Exception:
                        continue
            return False

        async def _compat_visible_locator(locator: Any) -> Any | None:
            try:
                count = await locator.count()
            except Exception:
                return None
            for index in range(count):
                candidate = locator.nth(index)
                try:
                    box = await candidate.bounding_box()
                except Exception:
                    box = None
                if not box or box["width"] < 16 or box["height"] < 16:
                    continue
                try:
                    disabled = await candidate.evaluate(
                        """
                        (el) => {
                          const node = el instanceof HTMLElement ? el : el.closest('*');
                          if (!node) return false;
                          const style = window.getComputedStyle(node);
                          return node.hasAttribute('disabled')
                            || node.getAttribute('aria-disabled') === 'true'
                            || style.pointerEvents === 'none';
                        }
                        """
                    )
                except Exception:
                    disabled = False
                if disabled:
                    continue
                return candidate
            return None

        async def _compat_start_trigger(page: Any) -> Any | None:
            locators = [
                page.locator('[aria-label*="Bắt đầu" i]'),
                page.locator('[aria-label*="Bat dau" i]'),
                page.locator('[aria-label*="Start image" i]'),
                page.locator('[aria-label*="Start frame" i]'),
                page.locator('[aria-label*="Add image" i]'),
                page.locator('[aria-label*="Add media" i]'),
                page.locator('[aria-label*="Start" i]'),
                page.locator('[aria-label*="frame" i]'),
                page.locator('button').filter(has_text=re.compile(r"^Bắt đầu$|^Bat dau$", re.I)),
                page.locator('button').filter(has_text=re.compile(r"^Start image$", re.I)),
                page.locator('button').filter(has_text=re.compile(r"^Start frame$", re.I)),
                page.locator('button').filter(has_text=re.compile(r"^Add image$", re.I)),
                page.locator('button').filter(has_text=re.compile(r"^Add Media$", re.I)),
                page.locator('button').filter(has_text=re.compile(r"^Start$", re.I)),
                page.locator('[role="button"]').filter(has_text=re.compile(r"^Bắt đầu$|^Bat dau$", re.I)),
                page.locator('[role="button"]').filter(has_text=re.compile(r"^Start$", re.I)),
                page.locator('[role="button"]').filter(has_text=re.compile(r"^Add image$", re.I)),
                page.locator('[role="button"]').filter(has_text=re.compile(r"^Add Media$", re.I)),
                page.locator('div[type="button"]').filter(has_text=re.compile(r"^Bắt đầu$|^Bat dau$", re.I)),
                page.locator('div[type="button"]').filter(has_text=re.compile(r"^Start$", re.I)),
                page.get_by_text("Bắt đầu", exact=True),
                page.get_by_text("Bat dau", exact=True),
                page.get_by_text("Start", exact=True),
            ]
            for locator in locators:
                candidate = await _compat_visible_locator(locator)
                if candidate is not None:
                    return candidate
            return None

        async def _compat_open_start_dialog(page: Any) -> Any | None:
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                existing = page.locator('[role="dialog"]').last
                if await existing.count() > 0:
                    return existing

                trigger = await _compat_start_trigger(page)
                if trigger is not None:
                    try:
                        await trigger.scroll_into_view_if_needed()
                    except Exception:
                        pass
                    try:
                        await trigger.click(force=True)
                    except Exception:
                        await asyncio.sleep(0.4)
                    try:
                        await page.wait_for_selector('[role="dialog"]', timeout=1500)
                    except Exception:
                        await asyncio.sleep(0.4)
                        continue
                    return page.locator('[role="dialog"]').last
                await asyncio.sleep(0.5)
            return None

        async def _compat_first_start_image_option(dialog: Any) -> Any | None:
            selectors = [
                '[data-index]',
                '[data-item-index]',
                'button:has(img)',
                '[role="button"]:has(img)',
                'img[alt]',
            ]
            for selector in selectors:
                locator = dialog.locator(selector)
                count = await locator.count()
                for index in range(count):
                    candidate = locator.nth(index)
                    try:
                        box = await candidate.bounding_box()
                    except Exception:
                        box = None
                    if not box or box["width"] < 48 or box["height"] < 48:
                        continue
                    return candidate
            return None

        async def _compat_confirm_start_dialog(page: Any, dialog: Any) -> bool:
            labels = ["Use", "Select", "Done", "Add", "Choose", "Dùng", "Chọn", "Xong", "Thêm"]
            for label in labels:
                locator = dialog.locator("button").filter(has_text=label)
                count = await locator.count()
                for index in range(count):
                    button = locator.nth(index)
                    try:
                        box = await button.bounding_box()
                    except Exception:
                        box = None
                    if not box:
                        continue
                    try:
                        await button.click(force=True)
                    except Exception:
                        continue
                    await asyncio.sleep(0.35)
                    if await page.locator('[role="dialog"]').count() == 0:
                        return True
            try:
                await page.keyboard.press("Enter")
                await asyncio.sleep(0.25)
            except Exception:
                pass
            return await page.locator('[role="dialog"]').count() == 0

        async def _compat_describe_start_dialog(dialog: Any) -> str:
            try:
                text = re.sub(r"\s+", " ", str(await dialog.text_content() or "")).strip()
            except Exception:
                text = ""
            try:
                button_count = await dialog.locator("button").count()
            except Exception:
                button_count = 0
            try:
                image_count = await dialog.locator("img").count()
            except Exception:
                image_count = 0
            summary = f"dialog buttons={button_count}, images={image_count}"
            if text:
                return f"{summary}, text='{text[:220]}'"
            return summary

        async def _compat_find_start_image_option(dialog: Any, image_name: str) -> Any | None:
            search = dialog.locator('input[type="text"]').first
            search_terms = self._start_image_search_terms(image_name)
            if not search_terms:
                search_terms = [str(image_name or "").strip()]

            for term in search_terms:
                if await search.count() > 0:
                    try:
                        await search.fill(term)
                        await asyncio.sleep(0.4)
                    except Exception:
                        pass

                candidates = [
                    dialog.locator('[data-index]').filter(has_text=term).last,
                    dialog.locator('[data-item-index]').filter(has_text=term).last,
                    dialog.locator('[role="button"]').filter(has_text=term).last,
                    dialog.locator("button").filter(has_text=term).last,
                    dialog.get_by_text(term, exact=True).last,
                ]
                for candidate in candidates:
                    try:
                        if await candidate.count() > 0:
                            return candidate
                    except Exception:
                        continue

                image_candidates = dialog.locator("img[alt]")
                image_count = await image_candidates.count()
                for index in range(image_count):
                    candidate = image_candidates.nth(index)
                    try:
                        alt_text = str(await candidate.get_attribute("alt") or "").strip()
                    except Exception:
                        alt_text = ""
                    haystack = " ".join(self._start_image_search_terms(alt_text))
                    if term.lower() and term.lower() in haystack.lower():
                        return candidate

            if await search.count() > 0:
                try:
                    await search.fill("")
                    await asyncio.sleep(0.2)
                except Exception:
                    pass

            return await _compat_first_start_image_option(dialog)

        async def _compat_close_dialog(page: Any) -> None:
            if await page.locator('[role="dialog"]').count() == 0:
                return
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.3)
            except Exception:
                pass

        async def _compat_wait_for_uploaded_image(page: Any, image_name: str, *, timeout_s: float = 18.0) -> bool:
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                dialog = await _compat_open_start_dialog(page)
                if dialog is not None:
                    option = await _compat_find_start_image_option(dialog, image_name)
                    await _compat_close_dialog(page)
                    if option is not None:
                        return True
                await asyncio.sleep(1.0)
            return False

        async def _compat_wait_for_project_media_name(client_self: Any, known_media: set[str], *, timeout_s: float = 8.0) -> str:
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                try:
                    data = await client_self._api.get_project_data()
                except Exception:
                    data = {}
                for workflow in data.get("projectContents", {}).get("workflows", []) or []:
                    media_name = str((workflow.get("metadata") or {}).get("primaryMediaId") or "").strip()
                    if media_name and media_name not in known_media:
                        return media_name
                    for media in workflow.get("medias", []) or []:
                        media_name = str(media.get("name") or "").strip()
                        if media_name and media_name not in known_media:
                            return media_name
                await asyncio.sleep(0.8)
            return ""

        def _compat_parse_video_jobs_from_project_data(
            client_self: Any,
            project_data: Dict[str, Any],
            known_media: set[str],
        ) -> list[Any]:
            jobs: List[Any] = []
            seen_media: set[str] = set()
            workflows = project_data.get("projectContents", {}).get("workflows", []) or []
            for workflow in workflows:
                workflow_id = str(workflow.get("name") or "").strip()
                metadata = workflow.get("metadata", {}) or {}
                candidate_media: List[str] = []
                primary_media_id = str(metadata.get("primaryMediaId") or "").strip()
                if primary_media_id:
                    candidate_media.append(primary_media_id)
                for media in workflow.get("medias", []) or []:
                    media_name = str(media.get("name") or "").strip()
                    if media_name:
                        candidate_media.append(media_name)
                for media_name in candidate_media:
                    if not media_name or media_name in known_media or media_name in seen_media:
                        continue
                    seen_media.add(media_name)
                    job = VideoJob.__new__(VideoJob)
                    job.media_name = media_name
                    job.status = "PENDING"
                    job.project_id = client_self.project_id
                    job.workflow_id = workflow_id
                    jobs.append(job)
            return jobs

        async def _compat_wait_for_video_jobs_from_project(
            client_self: Any,
            known_media: set[str],
            *,
            target_count: int,
            timeout_s: float,
        ) -> list[Any]:
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                try:
                    data = await client_self._api.get_project_data()
                except Exception:
                    data = {}
                jobs = _compat_parse_video_jobs_from_project_data(client_self, data, known_media)
                if len(jobs) >= target_count:
                    return jobs[:target_count]
                await asyncio.sleep(1.0)
            return []

        async def _compat_upload_project_image(client_self: Any, page: Any, image_path: str) -> dict[str, str]:
            image_file = Path(str(image_path or "")).expanduser().resolve()
            file_name = image_file.name.strip()
            if not file_name:
                raise RuntimeError("Chưa nhận được đường dẫn ảnh đầu vào hợp lệ.")
            if not image_file.exists():
                raise RuntimeError("Không tìm thấy ảnh đầu vào trên máy để tải lên Flow.")

            known_media: set[str] = set()
            try:
                known_media = self._project_media_names(await client_self._api.get_project_data())
            except Exception:
                known_media = set()

            uploaded = await _compat_upload_via_file_input(page, str(image_file))
            if not uploaded:
                for trigger in (
                    page.locator("button").filter(has_text="Add Media").first,
                    page.get_by_text("Add Media", exact=True).first,
                    page.locator("button").filter(has_text="Upload image").first,
                    page.get_by_text("Upload image", exact=True).first,
                ):
                    try:
                        if await trigger.count() > 0:
                            await trigger.click(force=True)
                            await asyncio.sleep(0.5)
                            uploaded = await _compat_upload_via_file_input(page, str(image_file))
                            if uploaded:
                                break
                    except Exception:
                        continue

            if not uploaded:
                raise RuntimeError("Google Flow chưa tải được ảnh đầu vào lên project.")

            media_name = await _compat_wait_for_project_media_name(client_self, known_media)
            await asyncio.sleep(1.0)
            return {"file_name": file_name, "media_name": media_name}

        async def _compat_attach_start_frame(page: Any, image_name: str, media_name: str = "") -> tuple[bool, str]:
            dialog = await _compat_open_start_dialog(page)
            if dialog is None:
                return False, "Không mở được dialog Start."
            row = await _compat_find_start_image_option(dialog, image_name)
            if row is None and media_name:
                row = await _compat_find_start_image_option(dialog, media_name)
            if row is None:
                search = dialog.locator('input[type="text"]').first
                if await search.count() > 0:
                    await search.fill("")
                    await asyncio.sleep(0.3)
                    row = await _compat_find_start_image_option(dialog, image_name)
                    if row is None and media_name:
                        row = await _compat_find_start_image_option(dialog, media_name)
            if row is None:
                row = await _compat_first_start_image_option(dialog)
                if row is None:
                    await _compat_close_dialog(page)
                    return False, await _compat_describe_start_dialog(dialog)

            click_attempts = [
                (
                    "closest-clickable",
                    lambda: row.evaluate(
                        """(el) => {
                            const target = el.closest('button, [role="button"], [data-index], [data-item-index]') || el;
                            target.click();
                        }"""
                    ),
                ),
                ("row", lambda: row.click(force=True)),
                ("row-double", lambda: row.dblclick(force=True)),
                ("image", lambda: row.locator("img").first.click(force=True)),
                ("first-child", lambda: row.evaluate("(el) => (el.firstElementChild || el).click()")),
                (
                    "dispatch-events",
                    lambda: row.evaluate(
                        """(el) => {
                            const target = el.closest('button, [role="button"], [data-index], [data-item-index]') || el;
                            ['mousedown','mouseup','click','dblclick'].forEach((type) => {
                                target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
                            });
                        }"""
                    ),
                ),
            ]
            for _, action in click_attempts:
                try:
                    await action()
                except Exception:
                    continue
                try:
                    await page.wait_for_function(
                        "() => !document.querySelector('[role=\"dialog\"]')",
                        timeout=5000,
                    )
                except Exception:
                    pass
                await asyncio.sleep(0.5)
                if await page.locator('[role="dialog"]').count() == 0:
                    return True, ""
                if await _compat_confirm_start_dialog(page, dialog):
                    return True, ""
                dialog = page.locator('[role="dialog"]').last
            try:
                detail = await _compat_describe_start_dialog(dialog)
                await _compat_close_dialog(page)
            except Exception:
                detail = ""
            return False, detail

        async def _compat_generate_video(
            client_self: Any,
            prompt: str,
            *,
            model: str = "Veo 3.1 - Fast",
            aspect: str = "landscape",
            count: int = 1,
            start_image: str | None = None,
            workflow_id: str | None = None,
            timeout_s: int = 120,
        ) -> list[Any]:
            page = await client_self._bm.page()
            await client_self._ensure_project_page(page)

            interceptor = UIInterceptor()
            interceptor.attach(page)
            target_count = max(1, min(4, int(count or 1)))

            mode = GenerationMode.FRAME_TO_VIDEO if start_image else GenerationMode.VIDEO
            ratio = AspectRatio.PORTRAIT if aspect == "portrait" else AspectRatio.LANDSCAPE

            await client_self._ui.open_settings_panel(page)
            switched = await client_self._ui.switch_mode(page, mode)
            if start_image and not switched:
                raise RuntimeError(
                    "Google Flow chưa chuyển được sang chế độ video từ ảnh (Frames), nên ảnh đầu vào chưa thể được gắn vào Start."
                )
            await client_self._ui.select_video_model(page, model)
            await client_self._ui.set_aspect_ratio(page, ratio)
            await client_self._ui.set_count(page, target_count)
            await client_self._ui.fill_prompt(page, prompt)
            uploaded_image_info: dict[str, str] = {"file_name": "", "media_name": ""}
            if start_image:
                uploaded_image_info = await _compat_upload_project_image(client_self, page, start_image)
            if uploaded_image_info.get("file_name") or uploaded_image_info.get("media_name"):
                attached, attach_detail = await _compat_attach_start_frame(
                    page,
                    uploaded_image_info.get("file_name", ""),
                    uploaded_image_info.get("media_name", ""),
                )
                if not attached:
                    # Flow thay đổi UI khá thất thường: có lúc upload xong là ảnh đã tự gắn vào Start
                    # mà không còn mở dialog theo đường cũ nữa. Đừng fail sớm ở đây; hãy thử submit
                    # thật và bắt đúng endpoint i2v để biết ảnh có được gắn hay không.
                    await asyncio.sleep(0.75)

            try:
                known_media_before_submit = self._project_media_names(await client_self._api.get_project_data())
            except Exception:
                known_media_before_submit = set()

            call_start = len(getattr(interceptor, "_calls", []))
            await client_self._ui.click_submit(page)
            jobs: list[Any] = []
            submit_error: Exception | None = None
            if start_image:
                submit_task = asyncio.create_task(
                    _compat_wait_for_video_submit_call(
                        interceptor,
                        call_start,
                        timeout_s=timeout_s,
                        expect_start_image=True,
                    )
                )
                project_task = asyncio.create_task(
                    _compat_wait_for_video_jobs_from_project(
                        client_self,
                        known_media_before_submit,
                        target_count=target_count,
                        timeout_s=min(timeout_s, 120),
                    )
                )
                done, pending = await asyncio.wait(
                    {submit_task, project_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    try:
                        result = task.result()
                    except Exception as exc:
                        submit_error = exc
                        continue
                    if isinstance(result, list):
                        jobs = result
                    else:
                        jobs = _compat_parse_video_jobs(client_self, result.resp)
                    break
                if not jobs and submit_error is not None:
                    raise submit_error
            else:
                entry = await _compat_wait_for_video_submit_call(
                    interceptor,
                    call_start,
                    timeout_s=timeout_s,
                    expect_start_image=False,
                )
                jobs = _compat_parse_video_jobs(client_self, entry.resp)
            if not jobs:
                raise RuntimeError("Google Flow chưa khởi tạo được clip video nào từ yêu cầu này.")
            if len(jobs) < target_count:
                raise RuntimeError(
                    f"Google Flow chỉ khởi tạo {len(jobs)}/{target_count} clip trong một lượt gửi. "
                    "Em dừng tại đây để tránh bấm thêm và tạo dư clip ngoài ý muốn. Hãy thử chạy lại."
                )
            return jobs[:target_count]

        async def _compat_ensure_project_page(client_self: Any, page: Any = None) -> None:
            if page is None:
                page = await client_self._bm.page()
            if client_self.project_id in str(page.url or ""):
                return
            try:
                await page.goto(
                    client_self._project_url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
            except Exception:
                await page.goto(
                    client_self._project_url,
                    wait_until="commit",
                    timeout=60_000,
                )
            await asyncio.sleep(2.5)

        async def _compat_generate_image(
            client_self: Any,
            prompt: str,
            *,
            model: str = "Nano Banana 2",
            aspect: str = "landscape",
            count: int = 1,
            reference_images: Optional[list[str]] = None,
            timeout_s: int = 120,
        ) -> list[Any]:
            page = await client_self._bm.page()
            await client_self._ensure_project_page(page)

            interceptor = UIInterceptor()
            interceptor.attach(page)
            target_count = max(1, min(4, int(count or 1)))

            ratio = (
                AspectRatio.PORTRAIT
                if "port" in str(aspect or "").lower()
                else AspectRatio.SQUARE
                if "square" in str(aspect or "").lower()
                else AspectRatio.LANDSCAPE
            )
            images: List[Any] = []
            attempts = 0
            max_attempts = max(target_count, 1) + 1
            while len(images) < target_count and attempts < max_attempts:
                remaining = target_count - len(images)
                batch_target = max(1, min(4, remaining))
                attempts += 1

                try:
                    known_media_before_submit = self._project_media_names(await client_self._api.get_project_data())
                except Exception:
                    known_media_before_submit = set()

                await client_self._ui.open_settings_panel(page)
                switched = await client_self._ui.switch_mode(page, GenerationMode.IMAGE)
                if not switched:
                    raise RuntimeError("Google Flow chưa chuyển sang chế độ tạo ảnh.")
                await client_self._ui.select_image_model(page, model)
                await client_self._ui.set_aspect_ratio(page, ratio)
                await client_self._ui.set_count(page, batch_target)
                await client_self._ui.fill_prompt(page, prompt)
                call_start = len(getattr(interceptor, "_calls", []))
                clicked = await client_self._ui.click_submit(page)
                if not clicked:
                    raise RuntimeError("Google Flow chưa bấm được nút tạo ảnh.")

                endpoint_task = asyncio.create_task(
                    _compat_wait_for_new_call(
                        interceptor,
                        call_start,
                        "batchGenerateImages",
                        timeout_s=max(30, timeout_s),
                        fail_on_tails=["batchAsyncGenerateVideo"],
                    )
                )
                project_task = asyncio.create_task(
                    self._wait_for_new_project_images(
                        client_self,
                        known_media_before_submit,
                        prompt=prompt,
                        target_count=batch_target,
                        timeout_s=max(30, timeout_s),
                    )
                )

                batch_images: List[Any] = []
                errors: List[Exception] = []
                pending = {endpoint_task, project_task}
                while pending and not batch_images:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        try:
                            result = task.result()
                        except Exception as exc:
                            errors.append(exc)
                            continue
                        if isinstance(result, list):
                            batch_images = result
                        else:
                            batch_images = _compat_parse_images(result.resp)
                        if batch_images:
                            break

                for task in pending:
                    task.cancel()

                if not batch_images:
                    if errors:
                        raise errors[-1]
                    raise RuntimeError("Google Flow không trả ảnh nào về từ yêu cầu hiện tại.")
                images.extend(batch_images)

            return images[:target_count]

        def _compat_parse_images(payload: Any) -> list[Any]:
            response = payload if isinstance(payload, dict) else {}
            images: List[Any] = []

            media_items = response.get("media", []) or []
            if media_items:
                for media_item in media_items:
                    if not isinstance(media_item, dict):
                        continue
                    image = GeneratedImage.__new__(GeneratedImage)
                    image._raw = media_item
                    image.media_name = str(media_item.get("name") or media_item.get("mediaName") or "").strip()
                    image.project_id = str(media_item.get("projectId") or "").strip()
                    image.workflow_id = str(media_item.get("workflowId") or "").strip()
                    generated = ((media_item.get("image") or {}).get("generatedImage") or {})
                    image.fife_url = str(
                        generated.get("fifeUrl")
                        or generated.get("url")
                        or media_item.get("fifeUrl")
                        or ""
                    ).strip()
                    image.seed = generated.get("seed", 0)
                    image.model = str(generated.get("modelNameType") or generated.get("model") or "").strip()
                    image.prompt = str(generated.get("prompt") or "").strip()
                    image.dimensions = media_item.get("dimensions", {}) or {}
                    image.file_path = None
                    images.append(image)
                if images:
                    return images

            generated_items = response.get("generatedImages", []) or []
            for item in generated_items:
                if not isinstance(item, dict):
                    continue
                image = GeneratedImage.__new__(GeneratedImage)
                image._raw = item
                image.media_name = str(item.get("mediaName") or item.get("name") or "").strip()
                image.project_id = ""
                image.workflow_id = ""
                image.fife_url = str(item.get("fifeUrl") or item.get("url") or "").strip()
                image.seed = int(item.get("seed", 0) or 0)
                image.model = str(item.get("modelNameType") or item.get("model") or "").strip()
                image.prompt = str(item.get("prompt") or "").strip()
                image.dimensions = item.get("dimensions", {}) or {}
                image.file_path = None
                images.append(image)
            return images

        def _compat_parse_video_jobs(client_self: Any, payload: Any) -> list[Any]:
            response = payload if isinstance(payload, dict) else {}
            jobs: List[Any] = []

            workflows_by_media: Dict[str, str] = {}
            for media_item in response.get("media", []) or []:
                media_name = str(media_item.get("name") or media_item.get("mediaName") or "").strip()
                workflow_id = str(media_item.get("workflowId") or "").strip()
                if media_name and workflow_id:
                    workflows_by_media[media_name] = workflow_id

            if not workflows_by_media:
                for job_data in response.get("jobs", []) or []:
                    media_id = job_data.get("mediaId", {}) if isinstance(job_data, dict) else {}
                    media_name = str(media_id.get("mediaName") or media_id.get("name") or "").strip()
                    workflow_id = str(job_data.get("workflowId") or "").strip()
                    if media_name and workflow_id:
                        workflows_by_media[media_name] = workflow_id

            if response.get("media"):
                for media_item in response.get("media", []) or []:
                    media_name = str(media_item.get("name") or media_item.get("mediaName") or "").strip()
                    if not media_name:
                        continue
                    job = VideoJob.__new__(VideoJob)
                    job.media_name = media_name
                    job.status = "PENDING"
                    job.project_id = client_self.project_id
                    job.workflow_id = workflows_by_media.get(media_name, "")
                    jobs.append(job)
                if jobs:
                    return jobs

            for job_data in response.get("jobs", []) or []:
                media_id = job_data.get("mediaId", {}) if isinstance(job_data, dict) else {}
                media_name = str(media_id.get("mediaName") or media_id.get("name") or "").strip()
                if not media_name:
                    continue
                job = VideoJob.__new__(VideoJob)
                job.media_name = media_name
                job.status = "PENDING"
                job.project_id = client_self.project_id
                job.workflow_id = workflows_by_media.get(media_name, str(job_data.get("workflowId") or "").strip())
                jobs.append(job)
            return jobs

        async def _compat_get_recaptcha_token(api_self: Any) -> str:
            page = await api_self._bm.page()

            is_on_flow = "labs.google" in str(page.url or "")
            if not is_on_flow:
                await api_self._ensure_project_page()
                page = await api_self._bm.page()
            elif getattr(api_self, "project_id", "") and getattr(api_self, "_project_page_url", "") not in str(page.url or ""):
                await api_self._ensure_project_page()
                page = await api_self._bm.page()

            async def _token_once() -> str:
                try:
                    ready = await page.wait_for_function(
                        "() => !!window.grecaptcha?.enterprise?.execute",
                        timeout=12_000,
                    )
                    await ready.dispose()
                except Exception:
                    return ""
                try:
                    token = await page.evaluate(
                        f"""
                        async () => {{
                            try {{
                                return await window.grecaptcha.enterprise.execute(
                                    '{RECAPTCHA_SITE_KEY}',
                                    {{ action: 'GENERATE' }}
                                );
                            }} catch (error) {{
                                return '';
                            }}
                        }}
                        """
                    )
                except Exception:
                    return ""
                return str(token or "").strip()

            for attempt in range(3):
                token = await _token_once()
                if token:
                    return token
                if attempt == 0:
                    try:
                        await page.reload(wait_until="domcontentloaded", timeout=20_000)
                    except Exception:
                        pass
                await asyncio.sleep(1.5)
            return ""

        async def _compat_api_fetch(api_self: Any, method: str, url: str, body: Optional[dict] = None) -> dict:
            if not str(url).startswith("http"):
                url = f"{api_self.API_BASE if hasattr(api_self, 'API_BASE') else 'https://aisandbox-pa.googleapis.com/v1'}/{str(url).lstrip('/')}"

            hdrs = await api_self._get_auth_headers()
            api_key = str(getattr(api_self, "FLOW_API_KEY", "") or "").strip()
            if api_key:
                hdrs["x-goog-api-key"] = api_key
            data = json.dumps(body) if body is not None else None
            ctx = api_self._bm.context.request
            timeout_ms = int(max(30, int(getattr(api_self, "_timeout_s", 300) or 300)) * 1000)

            if method.upper() == "GET":
                resp = await ctx.get(url, headers=hdrs, timeout=timeout_ms)
            elif method.upper() == "PATCH":
                resp = await ctx.patch(url, headers=hdrs, data=data, timeout=timeout_ms)
            else:
                resp = await ctx.post(url, headers=hdrs, data=data, timeout=timeout_ms)

            if resp.status >= 400:
                text = await resp.text()
                endpoint = str(url).split("/")[-1].split(":")[-1]
                if resp.status == 404:
                    raise RuntimeError(
                        f"Endpoint not found (HTTP 404): {endpoint}\n"
                        f"This feature may be deprecated or unavailable via direct API.\n"
                        f"Response: {text[:200]}"
                    )
                if resp.status == 400:
                    try:
                        err_body = json.loads(text)
                        msg = err_body.get("error", {}).get("message", text[:200])
                    except Exception:
                        msg = text[:200]
                    raise RuntimeError(f"HTTP 400 INVALID_ARGUMENT on {endpoint}: {msg}")
                if resp.status in (401, 403):
                    try:
                        err_body = json.loads(text)
                        msg = err_body.get("error", {}).get("message", text[:200])
                    except Exception:
                        msg = text[:200]
                    raise RuntimeError(
                        f"HTTP {resp.status} on {endpoint}: {msg or 'authentication failed. Session cookies may be expired.'}"
                    )
                raise RuntimeError(f"HTTP {resp.status} on {endpoint}: {text[:200]}")

            try:
                return await resp.json()
            except Exception:
                return {}

        def _compat_interceptor_attach(self: Any, page: Any) -> None:
            if getattr(self, "_attached", False):
                return
            self._attached = True

            targets: List[Any] = [page]
            context = getattr(page, "context", None)
            if context is not None and hasattr(context, "on"):
                targets.append(context)

            for target in targets:
                try:
                    target.on("request", self._on_request)
                    target.on("response", self._on_response)
                except Exception:
                    continue

        FlowAPI._fetch = _compat_api_fetch
        FlowAPI.get_recaptcha_token = _compat_get_recaptcha_token
        UIInterceptor.attach = _compat_interceptor_attach
        FlowClient._ensure_project_page = _compat_ensure_project_page
        FlowUI._settings_visible = _compat_settings_visible
        FlowUI.fill_prompt = _compat_fill_prompt
        FlowUI.open_settings_panel = _compat_open_settings_panel
        FlowUI.switch_mode = _compat_switch_mode
        FlowUI.set_aspect_ratio = _compat_set_aspect_ratio
        FlowUI.set_count = _compat_set_count
        FlowUI.get_video_model_selector = _compat_get_video_model_selector
        FlowUI.select_video_model = _compat_select_video_model
        FlowUI.get_image_model_selector = _compat_get_image_model_selector
        FlowUI.select_image_model = _compat_select_image_model
        FlowClient.generate_video = _compat_generate_video
        FlowClient.generate_image = _compat_generate_image
        self.__class__._FLOW_RUNTIME_PATCHED = True

    def _project_url(self, project_id: str) -> str:
        return canonical_project_url(project_id)

    def _looks_like_placeholder_project_url(self, url: str) -> bool:
        candidate = str(url or "").strip().lower()
        if not candidate:
            return False
        return any(
            marker in candidate
            for marker in (
                "/project/[projectid]",
                "/project/%5bprojectid%5d",
                "/project/%5bproject_id%5d",
                "/project/[project_id]",
            )
        )

    async def _ensure_valid_flow_project_page(self, page: Any, project_url: str) -> None:
        target_url = str(project_url or "").strip()
        if not target_url:
            return

        current_url = str(getattr(page, "url", "") or "").strip()
        if current_url.startswith(target_url) and not self._looks_like_placeholder_project_url(current_url):
            return

        if self._looks_like_placeholder_project_url(current_url):
            logging.getLogger(__name__).warning(
                "Flow tab opened placeholder project route (%s); redirecting to %s",
                current_url,
                target_url,
            )

        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            await page.goto(target_url, wait_until="commit", timeout=60_000)
        await asyncio.sleep(2.0)

    async def _repair_placeholder_flow_tabs(self, browser: Any, project_url: str) -> None:
        target_url = str(project_url or "").strip()
        if not target_url:
            return

        context = getattr(browser, "context", None)
        pages = list(getattr(context, "pages", []) or [])
        for candidate in pages:
            current_url = str(getattr(candidate, "url", "") or "").strip()
            if not self._looks_like_placeholder_project_url(current_url):
                continue
            try:
                logging.getLogger(__name__).warning(
                    "Repairing stale Flow placeholder tab (%s) -> %s",
                    current_url,
                    target_url,
                )
                await self._ensure_valid_flow_project_page(candidate, target_url)
            except Exception:
                continue

    async def _acquire_fresh_flow_page(self, browser: Any, project_url: str) -> Any:
        target_url = str(project_url or "").strip()
        context = getattr(browser, "context", None)
        pages = list(getattr(context, "pages", []) or [])

        for candidate in pages:
            current_url = str(getattr(candidate, "url", "") or "").strip()
            if current_url.startswith(target_url) and not self._looks_like_placeholder_project_url(current_url):
                try:
                    browser._page = candidate
                except Exception:
                    pass
                return candidate

        try:
            fresh_page = await context.new_page()
        except Exception:
            fresh_page = await browser.page()
        try:
            browser._page = fresh_page
        except Exception:
            pass
        return fresh_page

    async def _close_placeholder_flow_tabs(self, browser: Any, project_url: str) -> None:
        target_url = str(project_url or "").strip()
        context = getattr(browser, "context", None)
        pages = list(getattr(context, "pages", []) or [])
        stale_pages = [
            candidate
            for candidate in pages
            if self._looks_like_placeholder_project_url(str(getattr(candidate, "url", "") or ""))
        ]
        if not stale_pages:
            return

        logger = logging.getLogger(__name__)
        for candidate in stale_pages:
            current_url = str(getattr(candidate, "url", "") or "").strip()
            try:
                logger.warning("Closing stale Flow placeholder tab (%s)", current_url)
                await candidate.close()
            except Exception:
                continue

        remaining_pages = list(getattr(context, "pages", []) or [])
        if remaining_pages:
            try:
                browser._page = remaining_pages[0]
            except Exception:
                pass
            return

        try:
            fresh_page = await context.new_page()
        except Exception:
            return
        try:
            browser._page = fresh_page
        except Exception:
            pass
        if target_url:
            await self._ensure_valid_flow_project_page(fresh_page, target_url)

    def _normalize_project_id(self, project_value: str) -> str:
        return normalize_project_id(project_value)

    def _normalized_config(self, config: AppConfig) -> AppConfig:
        return normalized_app_config(config)

    def _normalize_projects_payload(self, projects: Dict[str, Dict[str, Any]]) -> tuple[Dict[str, Dict[str, str]], bool]:
        normalized: Dict[str, Dict[str, str]] = {}
        changed = False

        for raw_id, payload in projects.items():
            normalized_id = self._normalize_project_id(raw_id) or self._normalize_project_id(payload.get("url", ""))
            if not normalized_id:
                changed = True
                continue

            normalized_entry = {
                "name": str(payload.get("name", "")),
                "url": self._project_url(normalized_id),
            }
            current = normalized.get(normalized_id)
            if current is None or (not current["name"] and normalized_entry["name"]):
                normalized[normalized_id] = normalized_entry

            if raw_id != normalized_id or payload.get("url", "") != normalized_entry["url"]:
                changed = True

        return normalized, changed

    def _save_project_registry(self, projects: Dict[str, Dict[str, str]], active_id: str) -> None:
        from flow._storage import save_projects, set_active_project

        save_projects(projects)
        set_active_project(active_id or None, self._project_url(active_id) or None)

    def _fields_set(self, model: Any) -> set[str]:
        return set(getattr(model, "model_fields_set", getattr(model, "__fields_set__", set())))

    def _pick_skill_value(self, fields_set: set[str], field_name: str, explicit: Any, fallback: Any) -> Any:
        if field_name in fields_set:
            if isinstance(explicit, str):
                return explicit.strip()
            return explicit
        return fallback

    def _pick_skill_list(self, fields_set: set[str], field_name: str, explicit: List[str], fallback: List[str]) -> List[str]:
        return explicit if field_name in fields_set else fallback

    def _normalize_reference_media_names(self, values: List[str]) -> List[str]:
        return [str(entry).strip() for entry in values if str(entry).strip()]

    def _strip_accents(self, text: str) -> str:
        normalized = unicodedata.normalize("NFD", text)
        return "".join(char for char in normalized if unicodedata.category(char) != "Mn")

    def _normalize_skill_token(self, text: str) -> str:
        stripped = self._strip_accents(text or "").lower()
        stripped = re.sub(r"[^a-z0-9]+", "_", stripped)
        return stripped.strip("_")

    def _suggest_skill_name(self, skill_type: str, prompt: str) -> str:
        labels = {
            "video": "Tạo video",
            "image": "Tạo ảnh",
            "extend": "Kéo dài video",
            "upscale": "Nâng chất lượng",
            "camera_motion": "Chuyển động camera",
            "camera_position": "Vị trí camera",
            "insert": "Chèn vật thể",
            "remove": "Xóa vật thể",
        }
        snippet = (prompt or "").strip().replace("\n", " ")
        if snippet:
            return f"{labels.get(skill_type, skill_type)}: {snippet[:40]}"
        return labels.get(skill_type, "Skill mới")

    def _infer_skill_type(self, text: str) -> str:
        hinted = self._infer_skill_type_from_hint(text)
        if hinted:
            return hinted
        return "video"

    def _infer_skill_type_from_hint(self, text: str) -> str:
        normalized = self._normalize_skill_token(text)
        if any(token in normalized for token in {"tools_video", "guides_video", "video_guide", "video_ad"}):
            return "video"
        if any(token in normalized for token in {"tools_image", "guides_photo", "photo_graphy", "product_photography"}):
            return "image"
        rules = [
            ("camera_position", ["camera_position", "vi_tri_camera", "position_camera"]),
            ("camera_motion", ["camera_motion", "chuyen_dong_camera", "motion_camera"]),
            ("upscale", ["upscale", "nang_chat_luong"]),
            ("extend", ["extend", "keo_dai"]),
            ("insert", ["insert", "chen_vat_the", "them_vat_the"]),
            ("remove", ["remove", "xoa_vat_the"]),
            ("image", ["tao_anh", "image", "anh", "concept"]),
            ("video", ["tao_video", "video", "clip"]),
        ]
        for skill_type, keys in rules:
            if any(key in normalized for key in keys):
                return skill_type
        return ""

    def _parse_skill_type(self, value: str) -> str:
        normalized = self._normalize_skill_token(value)
        mapping = {
            "video": "video",
            "tao_video": "video",
            "image": "image",
            "anh": "image",
            "tao_anh": "image",
            "extend": "extend",
            "keo_dai": "extend",
            "upscale": "upscale",
            "nang_chat_luong": "upscale",
            "camera_motion": "camera_motion",
            "chuyen_dong_camera": "camera_motion",
            "camera_position": "camera_position",
            "vi_tri_camera": "camera_position",
            "insert": "insert",
            "chen_vat_the": "insert",
            "remove": "remove",
            "xoa_vat_the": "remove",
        }
        return mapping.get(normalized, self._infer_skill_type(value))

    def _parse_aspect(self, value: str) -> str:
        normalized = self._normalize_skill_token(value)
        if normalized in {"portrait", "9_16", "doc", "dung", "vertical"}:
            return "portrait"
        if normalized in {"square", "1_1", "vuong"}:
            return "square"
        return "landscape"

    def _parse_skill_text(self, text: str) -> Dict[str, Any]:
        parsed: Dict[str, Any] = {
            "type": self._infer_skill_type(text),
            "summary": "Học từ ô skill tự do.",
            "reference_media_names": [],
            "aspect": "landscape",
            "count": 1,
            "resolution": "1080p",
            "mask_x": 0.5,
            "mask_y": 0.5,
            "brush_size": 40,
        }
        free_lines: List[str] = []

        alias_map = {
            "ten": "name",
            "name": "name",
            "skill": "name",
            "tom_tat": "summary",
            "summary": "summary",
            "ghi_chu": "summary",
            "note": "summary",
            "loai": "type",
            "type": "type",
            "mode": "type",
            "prompt": "prompt",
            "mo_ta": "prompt",
            "description": "prompt",
            "aspect": "aspect",
            "ti_le": "aspect",
            "ratio": "aspect",
            "count": "count",
            "so_luong": "count",
            "quantity": "count",
            "workflow": "workflow_id",
            "workflow_id": "workflow_id",
            "ma_workflow": "workflow_id",
            "media": "media_id",
            "media_id": "media_id",
            "ma_media": "media_id",
            "motion": "motion",
            "huong_camera": "motion",
            "position": "position",
            "vi_tri_camera": "position",
            "resolution": "resolution",
            "do_phan_giai": "resolution",
            "references": "reference_media_names",
            "reference_media_names": "reference_media_names",
            "media_ref": "reference_media_names",
            "mask_x": "mask_x",
            "maskx": "mask_x",
            "mask_y": "mask_y",
            "masky": "mask_y",
            "brush": "brush_size",
            "brush_size": "brush_size",
            "co": "brush_size",
        }

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#!"):
                continue
            if line.startswith("#"):
                continue
            if line.lower().startswith("export "):
                line = line[7:].strip()
            line = line.strip("-").strip()
            if not line:
                continue

            separator = ":" if ":" in line else "=" if "=" in line else ""
            if separator:
                key, value = [part.strip() for part in line.split(separator, 1)]
                value = value.strip().strip('"').strip("'")
                field_name = alias_map.get(self._normalize_skill_token(key), "")
                if not field_name:
                    free_lines.append(line)
                    continue

                if field_name == "type":
                    parsed["type"] = self._parse_skill_type(value)
                elif field_name == "aspect":
                    parsed["aspect"] = self._parse_aspect(value)
                elif field_name == "count":
                    numbers = re.findall(r"\d+", value)
                    if numbers:
                        parsed["count"] = int(numbers[0])
                elif field_name == "reference_media_names":
                    parsed["reference_media_names"] = [entry.strip() for entry in re.split(r"[,\n]", value) if entry.strip()]
                elif field_name in {"mask_x", "mask_y"}:
                    try:
                        parsed[field_name] = float(value)
                    except ValueError:
                        pass
                elif field_name == "brush_size":
                    numbers = re.findall(r"\d+", value)
                    if numbers:
                        parsed["brush_size"] = int(numbers[0])
                else:
                    parsed[field_name] = value
                continue

            free_lines.append(line)

        normalized_text = self._normalize_skill_token(text)
        plain_text = self._strip_accents(text).lower()
        count_match = re.search(r"\b(\d+)\s*(anh|video|ket qua|ket_qua|results?)\b", plain_text)
        if count_match and parsed.get("count", 1) == 1:
            parsed["count"] = int(count_match.group(1))

        if "9_16" in normalized_text or "doc" in normalized_text:
            parsed["aspect"] = "portrait"
        elif "1_1" in normalized_text or "vuong" in normalized_text:
            parsed["aspect"] = "square"
        elif "16_9" in normalized_text or "ngang" in normalized_text:
            parsed["aspect"] = "landscape"

        if "4k" in normalized_text:
            parsed["resolution"] = "4k"

        if not parsed.get("prompt"):
            parsed["prompt"] = "\n".join(free_lines).strip()

        if not parsed.get("name"):
            parsed["name"] = self._suggest_skill_name(parsed.get("type", "video"), parsed.get("prompt", ""))

        return parsed

    def _looks_like_instructional_skill_doc(self, text: str, source_hint: str = "") -> bool:
        source_name = Path(urlparse(source_hint).path or source_hint).name.lower()
        lowered = text.lower()
        has_frontmatter = lowered.startswith("---\n") and ("name:" in lowered[:300] or "description:" in lowered[:600])
        has_markdown_sections = "\n# " in text or text.startswith("# ")
        if source_name in {"skill.md", "readme.md"} and has_markdown_sections:
            return True
        return has_frontmatter and has_markdown_sections and "```" in text

    def _looks_like_skill_add_command(self, value: str) -> bool:
        lowered = value.strip().lower()
        return " skills add " in f" {lowered} " or lowered.startswith("skills add ") or lowered.startswith("npx ")

    def _parse_skill_add_command(self, command: str) -> Dict[str, Any]:
        try:
            tokens = shlex.split(command)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Lệnh skills add không hợp lệ: {exc}") from exc

        if not tokens:
            raise HTTPException(status_code=400, detail="Lệnh skills add đang trống.")

        position = 0
        wrappers = {"npx", "bunx"}
        while position < len(tokens) and tokens[position] in wrappers:
            position += 1
            while position < len(tokens) and tokens[position].startswith("-"):
                position += 1

        if position + 1 < len(tokens) and tokens[position] == "pnpm" and tokens[position + 1] == "dlx":
            position += 2
        elif position + 1 < len(tokens) and tokens[position] == "yarn" and tokens[position + 1] == "dlx":
            position += 2

        if position >= len(tokens) or tokens[position] not in {"skills", "skill"}:
            raise HTTPException(status_code=400, detail="Bot hiện mới hiểu lệnh kiểu `skills add ...`.")

        position += 1
        if position >= len(tokens) or tokens[position] != "add":
            raise HTTPException(status_code=400, detail="Bot hiện mới hỗ trợ lệnh `skills add`.")

        position += 1
        source = ""
        name = ""
        summary = ""
        selected_skills: List[str] = []

        while position < len(tokens):
            token = tokens[position]

            if token in {"--skill", "-s"}:
                position += 1
                if position >= len(tokens):
                    raise HTTPException(status_code=400, detail="Thiếu tên skill sau `--skill`.")
                selected_skills.extend(self._split_skill_selector_values(tokens[position]))
                position += 1
                continue

            if token.startswith("--skill="):
                selected_skills.extend(self._split_skill_selector_values(token.split("=", 1)[1]))
                position += 1
                continue

            if token == "--skills":
                position += 1
                if position >= len(tokens):
                    raise HTTPException(status_code=400, detail="Thiếu danh sách skill sau `--skills`.")
                selected_skills.extend(self._split_skill_selector_values(tokens[position]))
                position += 1
                continue

            if token.startswith("--skills="):
                selected_skills.extend(self._split_skill_selector_values(token.split("=", 1)[1]))
                position += 1
                continue

            if token == "--name":
                position += 1
                if position < len(tokens):
                    name = tokens[position].strip()
                position += 1
                continue

            if token.startswith("--name="):
                name = token.split("=", 1)[1].strip()
                position += 1
                continue

            if token == "--summary":
                position += 1
                if position < len(tokens):
                    summary = tokens[position].strip()
                position += 1
                continue

            if token.startswith("--summary="):
                summary = token.split("=", 1)[1].strip()
                position += 1
                continue

            if token.startswith("-"):
                position += 1
                continue

            if not source:
                source = token
                position += 1
                continue

            selected_skills.extend(self._split_skill_selector_values(token))
            position += 1

        if not source:
            raise HTTPException(status_code=400, detail="Lệnh skills add đang thiếu repo hoặc link skill.")

        return {
            "url": source,
            "skills": self._normalize_selected_skills(selected_skills),
            "name": name,
            "summary": summary,
        }

    def _split_skill_selector_values(self, value: str) -> List[str]:
        return [part.strip() for part in re.split(r"[,\n]", value) if part.strip()]

    def _normalize_selected_skills(self, skills: List[str]) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()
        for raw_skill in skills:
            for value in self._split_skill_selector_values(raw_skill):
                skill = value.strip().strip("/")
                if not skill:
                    continue
                lowered = skill.lower()
                if lowered.endswith("/skill.md"):
                    skill = skill[:-9].rstrip("/")
                elif lowered.endswith("/readme.md"):
                    skill = skill[:-10].rstrip("/")
                elif lowered.endswith(".md") and "/" not in skill:
                    skill = re.sub(r"\.md$", "", skill, flags=re.IGNORECASE)
                key = skill.lower()
                if key in seen:
                    continue
                seen.add(key)
                normalized.append(skill)
        return normalized

    def _normalize_skill_source_input(self, value: str) -> str:
        raw = value.strip()
        if not raw:
            return ""
        if raw.startswith("github.com/"):
            return f"https://{raw}"
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", raw):
            return f"https://github.com/{raw[:-4] if raw.endswith('.git') else raw}"
        return raw

    def _parse_github_collection_url(self, value: str) -> Dict[str, str] | None:
        parsed = urlparse(value.strip())
        if parsed.netloc != "github.com":
            return None

        parts = [segment for segment in parsed.path.strip("/").split("/") if segment]
        if len(parts) < 2:
            return None
        if len(parts) >= 3 and parts[2] == "blob":
            return None

        owner = parts[0]
        repo = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
        branch = ""
        path = ""

        if len(parts) >= 4 and parts[2] == "tree":
            branch = parts[3]
            path = "/".join(parts[4:])
        elif len(parts) > 2:
            return None

        return {
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "path": path,
            "source_url": value.strip(),
        }

    def _normalize_skill_source_url(self, value: str) -> str:
        url = value.strip()
        if url.startswith("www."):
            url = f"https://{url}"

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise HTTPException(status_code=400, detail="Link skill phải bắt đầu bằng http:// hoặc https://")

        if parsed.netloc == "github.com":
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 5 and parts[2] == "blob":
                owner, repo = parts[0], parts[1]
                branch = parts[3]
                file_path = "/".join(parts[4:])
                return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}"

        return url

    def _download_skill_text(self, url: str) -> Dict[str, str]:
        request = Request(url, headers={"User-Agent": "flow-web-ui/0.1"})
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                with urlopen(request, timeout=30) as response:
                    payload = response.read(200_000)
                    content_type = response.headers.get_content_type()
                    charset = response.headers.get_content_charset() or "utf-8"
                    final_url = response.geturl()
                break
            except HTTPError as exc:
                message = f"Không tải được file skill từ link này ({exc.code})."
                if exc.code == 404:
                    message = "Không tìm thấy file skill tại link này."
                raise HTTPException(status_code=400, detail=message) from exc
            except URLError as exc:
                last_error = exc
                if attempt == 1:
                    raise HTTPException(status_code=400, detail=f"Không tải được skill từ link này: {exc.reason}") from exc
                time.sleep(0.5)
        else:
            raise HTTPException(status_code=400, detail=f"Không tải được skill từ link này: {last_error}")

        if content_type not in {
            "text/plain",
            "text/markdown",
            "text/x-shellscript",
            "text/x-sh",
            "application/x-sh",
            "application/octet-stream",
            "text/html",
        }:
            raise HTTPException(status_code=400, detail="Link này không giống tệp văn bản/skill có thể đọc được.")

        text = payload.decode(charset, errors="replace").strip()
        if not text:
            raise HTTPException(status_code=400, detail="Link skill không có nội dung để học.")

        return {
            "url": final_url,
            "text": text,
        }

    def _http_json(self, url: str) -> Any:
        request = Request(
            url,
            headers={
                "User-Agent": "flow-web-ui/0.1",
                "Accept": "application/vnd.github+json",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = response.read(500_000)
        except HTTPError as exc:
            message = f"GitHub trả về lỗi {exc.code}"
            if exc.code == 404:
                message = "Không tìm thấy repo/thư mục GitHub này."
            elif exc.code == 403:
                message = "GitHub tạm chặn hoặc giới hạn lượt truy cập. Hãy thử lại sau ít phút."
            raise HTTPException(status_code=400, detail=message) from exc
        except URLError as exc:
            raise HTTPException(status_code=400, detail=f"Không kết nối được tới GitHub: {exc.reason}") from exc

        try:
            return json.loads(payload.decode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="GitHub trả về dữ liệu không hợp lệ.") from exc

    def _github_default_branch(self, owner: str, repo: str) -> str:
        payload = self._http_json(f"https://api.github.com/repos/{owner}/{repo}")
        branch = str(payload.get("default_branch", "")).strip()
        return branch or "main"

    def _github_contents_api_url(self, owner: str, repo: str, path: str, branch: str) -> str:
        encoded_path = quote(path.strip("/"), safe="/")
        base = f"https://api.github.com/repos/{owner}/{repo}/contents"
        if encoded_path:
            base = f"{base}/{encoded_path}"
        return f"{base}?ref={quote(branch, safe='')}"

    def _github_tree_api_url(self, owner: str, repo: str, branch: str) -> str:
        return f"https://api.github.com/repos/{owner}/{repo}/git/trees/{quote(branch, safe='')}?recursive=1"

    def _media_skill_repo_entries(self) -> List[Dict[str, Any]]:
        owner, repo = self.MEDIA_SKILL_REPO.split("/", 1)
        branch = self._github_default_branch(owner, repo)
        payload = self._http_json(self._github_tree_api_url(owner, repo, branch))
        tree = payload.get("tree", []) if isinstance(payload, dict) else []
        entries: List[Dict[str, Any]] = []

        for item in tree:
            if item.get("type") != "blob":
                continue
            path = str(item.get("path", "")).strip()
            if not self.MEDIA_SKILL_PATH_PATTERN.match(path):
                continue
            entries.append(
                {
                    "path": path,
                    "download_url": f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}",
                    "html_url": f"https://github.com/{owner}/{repo}/blob/{branch}/{path}",
                }
            )

        entries.sort(key=lambda item: item["path"].lower())
        return entries

    def _github_selected_skill_entries(
        self,
        owner: str,
        repo: str,
        branch: str,
        root_path: str,
        selected_skills: List[str],
    ) -> Dict[str, Any]:
        active_branch = branch or self._github_default_branch(owner, repo)
        payload = self._http_json(self._github_tree_api_url(owner, repo, active_branch))
        tree = payload.get("tree", []) if isinstance(payload, dict) else []
        root_prefix = root_path.strip("/").lower()
        candidate_paths: List[str] = []

        for item in tree:
            if item.get("type") != "blob":
                continue
            item_path = str(item.get("path", "")).strip()
            if not item_path:
                continue
            lowered = item_path.lower()
            if root_prefix and lowered != root_prefix and not lowered.startswith(f"{root_prefix}/"):
                continue
            file_name = Path(lowered).name
            if file_name not in {"skill.md", "readme.md"} and Path(lowered).suffix not in self.SKILL_TEXT_EXTENSIONS:
                continue
            candidate_paths.append(item_path)

        entries: List[Dict[str, Any]] = []
        missing: List[str] = []
        seen_paths: set[str] = set()
        for skill in selected_skills:
            matches = self._match_skill_paths(skill, candidate_paths)
            if not matches:
                missing.append(skill)
                continue
            for path in matches:
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                entries.append(
                    {
                        "path": path,
                        "download_url": f"https://raw.githubusercontent.com/{owner}/{repo}/{active_branch}/{path}",
                        "html_url": f"https://github.com/{owner}/{repo}/blob/{active_branch}/{path}",
                        "size": 0,
                    }
                )

        return {
            "entries": entries,
            "missing": missing,
        }

    def _github_skill_file_entries(self, owner: str, repo: str, branch: str, root_path: str) -> List[Dict[str, Any]]:
        active_branch = branch or self._github_default_branch(owner, repo)
        queue = [root_path.strip("/")]
        files: List[Dict[str, Any]] = []
        visited: set[str] = set()
        scanned_dirs = 0

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            scanned_dirs += 1
            if scanned_dirs > 40:
                break

            payload = self._http_json(self._github_contents_api_url(owner, repo, current, active_branch))
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                item_type = item.get("type", "")
                item_path = str(item.get("path", "")).strip()
                if item_type == "dir":
                    queue.append(item_path)
                    continue
                if item_type != "file":
                    continue
                if self._is_skill_candidate_path(item_path):
                    files.append(
                        {
                            "path": item_path,
                            "download_url": item.get("download_url", ""),
                            "html_url": item.get("html_url", ""),
                            "size": int(item.get("size", 0) or 0),
                        }
                    )
                if len(files) >= 25:
                    return files
        return files

    def _match_skill_paths(self, skill: str, candidate_paths: List[str]) -> List[str]:
        normalized_skill = skill.strip().strip("/")
        if not normalized_skill:
            return []

        normalized_skill_lower = normalized_skill.lower()
        skill_base = Path(normalized_skill_lower).name
        direct_file_matches: List[str] = []
        folder_matches: List[str] = []
        fuzzy_matches: List[str] = []

        for path in candidate_paths:
            lowered = path.lower()
            parent = str(Path(lowered).parent)
            file_name = Path(lowered).name

            if lowered == normalized_skill_lower or lowered.endswith(f"/{normalized_skill_lower}"):
                direct_file_matches.append(path)
                continue

            if lowered.endswith(f"/{normalized_skill_lower}/skill.md") or lowered.endswith(f"/{normalized_skill_lower}/readme.md"):
                folder_matches.append(path)
                continue

            if skill_base and (
                parent.endswith(f"/{skill_base}")
                or parent == skill_base
                or lowered.endswith(f"/{skill_base}/skill.md")
                or lowered.endswith(f"/{skill_base}/readme.md")
            ):
                folder_matches.append(path)
                continue

            if normalized_skill_lower in lowered:
                fuzzy_matches.append(path)
                continue

            if file_name in {"skill.md", "readme.md"} and skill_base and skill_base in parent:
                fuzzy_matches.append(path)

        matches = direct_file_matches or folder_matches or fuzzy_matches
        return sorted(
            matches,
            key=lambda path: (
                0 if Path(path).name.lower() == "skill.md" else 1,
                path.count("/"),
                len(path),
            ),
        )[:5]

    def _is_skill_candidate_path(self, path: str) -> bool:
        lower = path.lower()
        name = Path(lower).name
        ext = Path(lower).suffix
        parent = str(Path(lower).parent)
        if ext not in self.SKILL_TEXT_EXTENSIONS:
            return False
        if name.startswith("."):
            return False
        if name == "readme.md" and "skill" not in parent:
            return False
        return True

    def _looks_like_skill_text(self, text: str, path: str = "") -> bool:
        normalized_path = path.lower()
        if "skill" in normalized_path:
            return True

        lowered = self._strip_accents(text).lower()
        signals = [
            "prompt",
            "workflow",
            "workflow_id",
            "type=",
            "type:",
            "aspect",
            "count",
            "tao anh",
            "tao video",
            "image",
            "video",
            "camera_motion",
            "camera_position",
            "upscale",
            "insert",
            "remove",
        ]
        score = sum(1 for signal in signals if signal in lowered)
        return score >= 2

    def _skill_signature(self, name: str, content: str) -> str:
        return f"{name.strip().lower()}::{content.strip()}"

    def _name_from_url(self, url: str) -> str:
        path = urlparse(url).path.rstrip("/")
        file_name = path.split("/")[-1] if path else ""
        if not file_name:
            return ""
        name = re.sub(r"\.[A-Za-z0-9]+$", "", file_name).replace("-", " ").replace("_", " ").strip()
        return name[:80]

    def _name_from_path(self, path: str) -> str:
        path_obj = Path(path)
        file_name = path_obj.name
        if not file_name:
            return ""
        if file_name.lower() in {"skill.md", "readme.md"} and path_obj.parent.name:
            file_name = path_obj.parent.name
        return re.sub(r"\.[A-Za-z0-9]+$", "", file_name).replace("-", " ").replace("_", " ").strip()[:80]

    def _flow_error_status(self, exc: Exception) -> int:
        if isinstance(exc, HTTPException):
            return exc.status_code
        if self._is_profile_lock_error(exc):
            return 409
        return 500

    def _flow_error_detail(self, exc: Exception) -> str:
        if isinstance(exc, HTTPException):
            detail = exc.detail
            if isinstance(detail, str):
                return humanize_flow_error(detail)
            return "Yêu cầu tới Google Flow không thành công."

        return humanize_flow_error(str(exc).strip()) or "Không thể kết nối tới Google Flow."

    def _is_profile_lock_error(self, exc: Exception) -> bool:
        message = str(exc)
        lowered = message.lower()
        return (
            "processsingleton" in message
            or "singletonlock" in lowered
            or "profile directory is already in use" in lowered
        )

    def _download_name(self, job: JobRecord, artifact: JobArtifact, artifact_index: int) -> str:
        extension = ".mp4" if artifact.mime_type.startswith("video") else ".jpg"
        slug = artifact.media_name or f"{job.type}-{job.id[:8]}-{artifact_index + 1}"
        return f"{slug}{extension}"

    def _resolve_job_request(self, request: CreateJobRequest, config: AppConfig) -> CreateJobRequest:
        payload = _model_dump(request)
        raw_timeout = int(payload.get("timeout_s") or 0)
        payload["type"] = str(payload.get("type", "")).strip()
        payload["prompt"] = str(payload.get("prompt", "")).strip()
        payload["title"] = str(payload.get("title", "")).strip()
        payload["model"] = self._normalize_job_model(payload["type"], str(payload.get("model", "")).strip())
        payload["aspect"] = str(payload.get("aspect", "landscape")).strip() or "landscape"
        payload["start_image_path"] = str(payload.get("start_image_path", "")).strip()
        payload["reference_image_paths"] = [
            str(item).strip()
            for item in payload.get("reference_image_paths", [])
            if str(item).strip()
        ]
        payload["reference_image_roles"] = self._normalize_reference_image_roles(
            payload["reference_image_paths"],
            payload.get("reference_image_roles", []),
        )
        payload["reference_media_names"] = [
            str(item).strip()
            for item in payload.get("reference_media_names", [])
            if str(item).strip()
        ]
        payload["media_id"] = str(payload.get("media_id", "")).strip()
        payload["workflow_id"] = str(payload.get("workflow_id", "")).strip() or config.active_workflow_id
        payload["motion"] = str(payload.get("motion", "")).strip()
        payload["position"] = str(payload.get("position", "")).strip()
        payload["resolution"] = str(payload.get("resolution", "1080p")).strip() or "1080p"
        payload["source_job_id"] = str(payload.get("source_job_id", "")).strip()
        payload["timeout_s"] = max(30, raw_timeout) if raw_timeout > 0 else max(30, int(config.generation_timeout_s))
        return CreateJobRequest(**payload)

    def _resolve_retry_source(self, source_job_id: str, request_type: str) -> JobRecord | None:
        source_id = str(source_job_id or "").strip()
        if not source_id:
            return None

        source_job = self.store.get_job(source_id)
        if source_job is None:
            raise HTTPException(status_code=400, detail="Không tìm thấy job gốc để chạy lại.")
        if source_job.status not in {"failed", "interrupted"}:
            raise HTTPException(status_code=400, detail="Chỉ có thể chạy lại job đang lỗi hoặc đã bị ngắt.")
        if source_job.type not in self.SUPPORTED_SKILL_TYPES:
            raise HTTPException(status_code=400, detail="Loại job này chưa hỗ trợ chạy lại.")
        if source_job.type != request_type:
            raise HTTPException(status_code=400, detail="Loại tác vụ chạy lại phải khớp với job gốc.")
        return source_job

    def _build_retry_snapshot(self, source_job: JobRecord | None) -> JobRetrySnapshot:
        if source_job is None:
            return JobRetrySnapshot()
        return JobRetrySnapshot(
            is_retry=True,
            source_job_id=source_job.id,
            source_job_title=source_job.title or source_job.type.replace("_", " ").title(),
            source_job_type=source_job.type,
            source_job_status=source_job.status,
            source_job_created_at=source_job.created_at,
        )

    def _default_title(self, request: CreateJobRequest) -> str:
        if request.type == "video":
            if request.start_image_path:
                return "Tạo video từ ảnh"
            if request.reference_image_paths or request.reference_media_names:
                return "Tạo video từ ảnh tham chiếu"
            return "Tạo video từ prompt"
        if request.type == "image":
            if request.reference_image_paths or request.reference_media_names:
                return "Chỉnh ảnh từ ảnh tham chiếu"
            return "Tạo ảnh từ prompt"
        titles = {
            "extend": "Kéo dài video",
            "upscale": "Nâng chất lượng video",
            "camera_motion": "Chuyển động camera",
            "camera_position": "Vị trí camera",
            "insert": "Chèn vật thể",
            "remove": "Xóa vật thể",
        }
        return titles.get(request.type, request.type.replace("_", " ").title())

    def _job_type_label(self, job_type: str) -> str:
        titles = {
            "login": "Đăng nhập",
            "video": "Tạo video",
            "image": "Tạo ảnh",
            "extend": "Kéo dài video",
            "upscale": "Nâng chất lượng",
            "camera_motion": "Chuyển động camera",
            "camera_position": "Vị trí camera",
            "insert": "Chèn vật thể",
            "remove": "Xóa vật thể",
        }
        return titles.get(str(job_type or "").strip(), str(job_type or "").strip())

    def _build_output_shelf(self, jobs: List[JobRecord]) -> OutputShelfSnapshot:
        items: List[OutputShelfItem] = []

        for job in jobs:
            if job.status != "completed" or not job.artifacts:
                continue

            job_input = job.input if isinstance(job.input, dict) else {}
            for artifact_index, artifact in enumerate(job.artifacts):
                workflow_id = str(artifact.workflow_id or "").strip() or str(job_input.get("workflow_id", "") or "").strip()
                local_path = str(artifact.local_path or "").strip()
                local_exists = self._artifact_local_exists(local_path)
                local_file_url = self._artifact_file_url(job.id, artifact_index) if local_path else ""
                items.append(
                    OutputShelfItem(
                        job_id=job.id,
                        artifact_index=artifact_index,
                        title=artifact.label or f"Kết quả {artifact_index + 1}",
                        job_title=job.title or self._job_type_label(job.type),
                        job_type=job.type,
                        job_type_label=self._job_type_label(job.type),
                        created_at=job.updated_at or job.created_at,
                        media_id=str(artifact.media_name or "").strip(),
                        workflow_id=workflow_id,
                        source_url=str(artifact.url or "").strip(),
                        local_path=local_path,
                        local_file_url=local_file_url,
                        local_exists=local_exists,
                        preview_url=self._artifact_preview_url(job, artifact, artifact_index),
                        mime_type=str(artifact.mime_type or "").strip(),
                        prompt=str(artifact.prompt or job_input.get("prompt", "") or "").strip(),
                        dimensions=artifact.dimensions or {},
                    )
                )
                if len(items) >= self.MAX_OUTPUT_SHELF_ITEMS:
                    break

            if len(items) >= self.MAX_OUTPUT_SHELF_ITEMS:
                break

        if not items:
            return OutputShelfSnapshot()

        job_count = len({item.job_id for item in items})
        return OutputShelfSnapshot(
            has_items=True,
            total_items=len(items),
            job_count=job_count,
            summary=self._output_shelf_summary(len(items), job_count),
            items=items,
        )

    def _replay_group_meta(self, group_key: str) -> Dict[str, str]:
        mapping = {
            "auth": {
                "label": "Cụm đăng nhập bị ngắt",
                "description": "Giữ log cuối để mở lại đăng nhập Google Flow mà không phải mò lại từ đầu.",
            },
            "video": {
                "label": "Cụm tạo video bị ngắt",
                "description": "Giữ prompt, tỉ lệ, ảnh đầu vào và timeout cuối để mở retry nhanh.",
            },
            "image": {
                "label": "Cụm tạo ảnh bị ngắt",
                "description": "Giữ prompt, tỉ lệ, media tham chiếu và timeout cuối để khôi phục nhanh.",
            },
            "edit": {
                "label": "Cụm chỉnh sửa media bị ngắt",
                "description": "Giữ media ID, workflow và tham số chỉnh sửa cuối để mở lại đúng form retry.",
            },
            "other": {
                "label": "Interrupted work khác",
                "description": "Giữ log cuối để quyết định bước recovery phù hợp mà không mất dấu công việc dở dang.",
            },
        }
        return mapping.get(group_key, mapping["edit"])

    def _download_root(self) -> Path:
        configured = self.store.snapshot().config.output_dir.strip()
        if configured:
            return Path(configured).expanduser()
        return DOWNLOADS_DIR

    def _artifact_file_url(self, job_id: str, artifact_index: int) -> str:
        return f"/api/jobs/{quote(str(job_id or '').strip(), safe='')}/artifacts/{int(artifact_index)}/file"

    def _get_artifact_or_raise(self, job_id: str, artifact_index: int) -> tuple[JobRecord, JobArtifact]:
        job = self.store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ.")
        if artifact_index < 0 or artifact_index >= len(job.artifacts):
            raise HTTPException(status_code=400, detail="Chỉ mục kết quả không hợp lệ.")
        return job, job.artifacts[artifact_index]

    def _artifact_local_exists(self, local_path: str) -> bool:
        raw = str(local_path or "").strip()
        if not raw:
            return False
        try:
            return Path(raw).expanduser().exists()
        except OSError:
            return False

    def _artifact_local_roots(self) -> List[Path]:
        roots = [DOWNLOADS_DIR.resolve(), UPLOADS_DIR.resolve()]
        configured = str(self.store.snapshot().config.output_dir or "").strip()
        if configured:
            try:
                roots.insert(0, Path(configured).expanduser().resolve())
            except OSError:
                pass

        unique_roots: List[Path] = []
        seen: set[str] = set()
        for root in roots:
            normalized = str(root)
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_roots.append(root)
        return unique_roots

    def _artifact_local_path(self, artifact: JobArtifact) -> Path:
        raw = str(artifact.local_path or "").strip()
        if not raw:
            raise HTTPException(status_code=400, detail="Artifact này chưa có tệp local đã lưu.")

        try:
            path = Path(raw).expanduser().resolve()
        except OSError as exc:
            raise HTTPException(status_code=404, detail="Không thể đọc tệp local của artifact này.") from exc

        allowed_roots = self._artifact_local_roots()
        if allowed_roots and not any(str(path).startswith(str(root)) for root in allowed_roots):
            raise HTTPException(status_code=403, detail="Tệp local này nằm ngoài vùng app đang phục vụ.")
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="Tệp đã lưu cho artifact này không còn trên máy.")
        return path

    def _artifact_preview_url(self, job: JobRecord, artifact: JobArtifact, artifact_index: int) -> str:
        if str(artifact.local_path or "").strip():
            try:
                self._artifact_local_path(artifact)
            except HTTPException:
                pass
            else:
                return self._artifact_file_url(job.id, artifact_index)
        return str(artifact.public_url or artifact.url or "").strip()

    def _output_shelf_summary(self, item_count: int, job_count: int) -> str:
        return (
            f"{item_count} artifact mới nhất từ {job_count} job hoàn tất gần đây. "
            "Có thể mở, lưu hoặc tái dùng ngay tại đây mà không cần cuộn hết lịch sử tác vụ."
        )

    def _build_cleanup_assistant(
        self,
        config: Dict[str, Any] | AppConfig,
        jobs: List[JobRecord],
        output_shelf: OutputShelfSnapshot,
    ) -> tuple[CleanupAssistantSnapshot, Dict[str, Dict[str, Any]]]:
        normalized_config = self._normalized_config(config)
        upload_group, upload_plan = self._build_upload_cleanup_group(jobs)
        download_group, download_plan = self._build_download_cleanup_group(normalized_config, jobs, output_shelf)
        history_group, history_plan = self._build_history_cleanup_group(normalized_config, jobs, output_shelf)
        groups = [upload_group, download_group, history_group]

        total_safe_count = sum(group.safe_count for group in groups)
        total_safe_bytes = sum(group.safe_bytes for group in groups)
        protected_count = sum(group.protected_count for group in groups)
        protected_bytes = sum(group.protected_bytes for group in groups)
        visible = any(group.safe_count or group.protected_count for group in groups)

        if total_safe_count:
            headline = f"Có {total_safe_count} mục an toàn để dọn ngay"
            if protected_count:
                summary = (
                    f"Em đã tách riêng {total_safe_count} mục an toàn khỏi {protected_count} mục còn mới hoặc còn quan trọng. "
                    "Các nút dọn chỉ xóa trong phạm vi đã được phân loại sẵn."
                )
            else:
                summary = "Các mục hiện có đều nằm trong phạm vi an toàn đã được phân loại sẵn để dọn."
        elif protected_count:
            headline = "Chưa có mục an toàn để dọn"
            summary = (
                "Uploads, downloads và history hiện vẫn còn mới hoặc còn gắn với artifact local quan trọng, "
                "nên em đang giữ lại mặc định."
            )
        else:
            headline = ""
            summary = ""

        return (
            CleanupAssistantSnapshot(
                visible=visible,
                headline=headline,
                summary=summary,
                total_safe_count=total_safe_count,
                total_safe_bytes=total_safe_bytes,
                protected_count=protected_count,
                protected_bytes=protected_bytes,
                groups=groups,
            ),
            {
                "uploads": upload_plan,
                "downloads": download_plan,
                "history": history_plan,
            },
        )

    def _build_upload_cleanup_group(self, jobs: List[JobRecord]) -> tuple[CleanupGroupSnapshot, Dict[str, Any]]:
        root = UPLOADS_DIR.resolve()
        references: Dict[str, Dict[str, int]] = {}

        for job in jobs:
            job_input = job.input if isinstance(job.input, dict) else {}
            raw_paths = [str(job_input.get("start_image_path", "") or "").strip()]
            raw_paths.extend(
                str(item or "").strip()
                for item in job_input.get("reference_image_paths", [])
                if str(item or "").strip()
            )
            for raw_path in raw_paths:
                if not raw_path:
                    continue
                try:
                    path = Path(raw_path).expanduser().resolve()
                except OSError:
                    continue
                if not self._path_within_roots(path, [root]):
                    continue

                key = str(path)
                ref = references.setdefault(key, {"active": 0, "terminal": 0, "total": 0})
                ref["total"] += 1
                if job.status in {"queued", "running", "polling"}:
                    ref["active"] += 1
                else:
                    ref["terminal"] += 1

        safe_entries: List[Dict[str, Any]] = []
        protected_entries: List[Dict[str, Any]] = []
        safe_paths: List[Path] = []
        for path in self._list_cleanup_files([root]):
            modified_at = self._path_modified_datetime(path)
            size_bytes = self._file_size(path)
            ref = references.get(str(path), {"active": 0, "terminal": 0, "total": 0})
            active_count = int(ref.get("active", 0) or 0)
            terminal_count = int(ref.get("terminal", 0) or 0)
            is_recent = self._is_recent_datetime(modified_at, hours=self.CLEANUP_UPLOAD_GRACE_HOURS)

            if active_count:
                detail = f"Ảnh đầu vào này đang được {active_count} job chưa xong tham chiếu, nên em giữ lại."
                protected_entries.append({
                    "path": path,
                    "bytes": size_bytes,
                    "snapshot": self._cleanup_file_item(
                        path,
                        root,
                        detail=detail,
                        size_bytes=size_bytes,
                        status="protected",
                    ),
                })
                continue

            if is_recent:
                detail = (
                    f"Upload này mới xuất hiện trong khoảng {self.CLEANUP_UPLOAD_GRACE_HOURS} giờ gần đây. "
                    "App giữ lại để tránh xóa nhầm trước khi dùng."
                )
                if terminal_count:
                    detail += f" Nó đã từng được dùng cho {terminal_count} job đã xong."
                protected_entries.append({
                    "path": path,
                    "bytes": size_bytes,
                    "snapshot": self._cleanup_file_item(
                        path,
                        root,
                        detail=detail,
                        size_bytes=size_bytes,
                        status="protected",
                    ),
                })
                continue

            detail = "File tạm đã cũ và không còn job đang chạy nào giữ lại."
            if terminal_count:
                detail += f" Nó từng được dùng cho {terminal_count} job đã xong."
            safe_paths.append(path)
            safe_entries.append({
                "path": path,
                "bytes": size_bytes,
                "snapshot": self._cleanup_file_item(
                    path,
                    root,
                    detail=detail,
                    size_bytes=size_bytes,
                    status="safe",
                ),
            })

        safe_entries.sort(key=lambda item: item["snapshot"].path_hint)
        protected_entries.sort(key=lambda item: item["snapshot"].path_hint)
        safe_count = len(safe_entries)
        safe_bytes = sum(item["bytes"] for item in safe_entries)
        protected_count = len(protected_entries)
        protected_bytes = sum(item["bytes"] for item in protected_entries)

        if safe_count:
            summary = "Uploads tạm đã cũ có thể dọn ngay mà không ảnh hưởng các job đang chạy."
        elif protected_count:
            summary = "Uploads hiện còn mới hoặc còn bị job đang chạy giữ lại, nên em chưa xếp chúng vào nhóm an toàn."
        else:
            summary = "Chưa có upload tạm nào để phân loại."

        group = CleanupGroupSnapshot(
            key="uploads",
            label="Uploads tạm",
            action_label="Dọn uploads tạm",
            summary=summary,
            empty_label="Chưa có upload tạm nào cần dọn.",
            safe_count=safe_count,
            safe_bytes=safe_bytes,
            protected_count=protected_count,
            protected_bytes=protected_bytes,
            notes=[
                "Chỉ quét trong thư mục uploads của app.",
                "Upload mới hoặc đang bị job chưa xong tham chiếu sẽ được giữ lại mặc định.",
            ],
            safe_items=[entry["snapshot"] for entry in safe_entries[: self.CLEANUP_PREVIEW_LIMIT]],
            protected_items=[entry["snapshot"] for entry in protected_entries[: self.CLEANUP_PREVIEW_LIMIT]],
        )
        return group, {"paths": safe_paths, "artifact_refs": {}, "job_ids": []}

    def _build_download_cleanup_group(
        self,
        config: AppConfig,
        jobs: List[JobRecord],
        output_shelf: OutputShelfSnapshot,
    ) -> tuple[CleanupGroupSnapshot, Dict[str, Any]]:
        roots = self._download_cleanup_roots()
        reference_map = self._download_artifact_reference_map(jobs, roots)
        shelf_keys = {
            f"{item.job_id}:{int(item.artifact_index)}"
            for item in (output_shelf.items if output_shelf and output_shelf.items else [])
        }
        active_workflow_id = str(config.active_workflow_id or "").strip()

        safe_entries: List[Dict[str, Any]] = []
        protected_entries: List[Dict[str, Any]] = []
        safe_paths: List[Path] = []
        artifact_refs: Dict[str, List[tuple[str, int]]] = {}
        for path in self._list_cleanup_files(roots):
            size_bytes = self._file_size(path)
            refs = reference_map.get(str(path), [])
            protection_reasons = self._download_protection_reasons(refs, shelf_keys, active_workflow_id)

            if protection_reasons:
                protected_entries.append({
                    "path": path,
                    "bytes": size_bytes,
                    "snapshot": self._cleanup_file_item(
                        path,
                        self._matching_cleanup_root(path, roots),
                        detail=" ".join(protection_reasons[:2]),
                        size_bytes=size_bytes,
                        status="protected",
                    ),
                })
                continue

            if refs:
                detail = (
                    f"Artifact local này đã cũ hơn {self.CLEANUP_DOWNLOAD_RETENTION_DAYS} ngày "
                    "và không còn nằm trong nhóm output quan trọng gần đây."
                )
                artifact_refs[str(path)] = [(entry["job"].id, entry["artifact_index"]) for entry in refs]
            else:
                detail = "Tệp đã tải này không còn job history nào tham chiếu, nên có thể dọn an toàn."
                artifact_refs[str(path)] = []

            safe_paths.append(path)
            safe_entries.append({
                "path": path,
                "bytes": size_bytes,
                "snapshot": self._cleanup_file_item(
                    path,
                    self._matching_cleanup_root(path, roots),
                    detail=detail,
                    size_bytes=size_bytes,
                    status="safe",
                ),
            })

        safe_entries.sort(key=lambda item: item["snapshot"].path_hint)
        protected_entries.sort(key=lambda item: item["snapshot"].path_hint)
        safe_count = len(safe_entries)
        safe_bytes = sum(item["bytes"] for item in safe_entries)
        protected_count = len(protected_entries)
        protected_bytes = sum(item["bytes"] for item in protected_entries)

        if safe_count:
            summary = (
                "Các file đã tải cũ hoặc không còn tham chiếu sẽ được xóa, "
                "đồng thời metadata local liên quan trong history cũng được làm sạch."
            )
        elif protected_count:
            summary = "Các file đã tải hiện còn mới, còn nằm trên output shelf hoặc còn gắn với workflow quan trọng nên em giữ lại."
        else:
            summary = "Chưa có file đã tải nào để phân loại."

        group = CleanupGroupSnapshot(
            key="downloads",
            label="Downloads đã lưu",
            action_label="Dọn file đã tải",
            summary=summary,
            empty_label="Chưa có file đã tải nào cần dọn.",
            safe_count=safe_count,
            safe_bytes=safe_bytes,
            protected_count=protected_count,
            protected_bytes=protected_bytes,
            notes=[
                "Chỉ xóa file nằm trong thư mục tải xuống an toàn của app.",
                "Artifact local còn mới, còn trên output shelf hoặc còn trùng workflow mặc định sẽ được giữ lại mặc định.",
            ],
            safe_items=[entry["snapshot"] for entry in safe_entries[: self.CLEANUP_PREVIEW_LIMIT]],
            protected_items=[entry["snapshot"] for entry in protected_entries[: self.CLEANUP_PREVIEW_LIMIT]],
        )
        return group, {"paths": safe_paths, "artifact_refs": artifact_refs, "job_ids": []}

    def _build_history_cleanup_group(
        self,
        config: AppConfig,
        jobs: List[JobRecord],
        output_shelf: OutputShelfSnapshot,
    ) -> tuple[CleanupGroupSnapshot, Dict[str, Any]]:
        safe_entries: List[CleanupItemSnapshot] = []
        protected_entries: List[CleanupItemSnapshot] = []
        removable_job_ids: List[str] = []
        shelf_job_ids = {item.job_id for item in (output_shelf.items if output_shelf and output_shelf.items else [])}
        active_workflow_id = str(config.active_workflow_id or "").strip()

        for job in jobs:
            job_activity = self._job_activity_datetime(job)
            is_recent = self._is_recent_datetime(job_activity, days=self.CLEANUP_HISTORY_RETENTION_DAYS)
            has_local_files = self._job_has_existing_local_artifacts(job)
            touches_active_workflow = self._job_touches_workflow(job, active_workflow_id)

            protected_reason = ""
            if job.status in {"queued", "running", "polling"}:
                protected_reason = "Job này vẫn chưa hoàn tất nên history cần được giữ nguyên."
            elif has_local_files:
                protected_reason = "Job này vẫn còn file local trên máy, nên app giữ history để lần lại artifact."
            elif job.id in shelf_job_ids:
                protected_reason = "Job này vẫn đang góp mặt trong output shelf gần đây."
            elif is_recent:
                protected_reason = f"Job này còn mới trong khoảng {self.CLEANUP_HISTORY_RETENTION_DAYS} ngày gần đây."
            elif touches_active_workflow:
                protected_reason = "Job này còn khớp workflow mặc định đang ghim, nên em giữ lại mặc định."

            if protected_reason:
                protected_entries.append(self._cleanup_job_item(job, protected_reason, status="protected"))
                continue

            if job.type == "login":
                detail = "Lịch sử đăng nhập cũ có thể gỡ đi mà không ảnh hưởng phiên hiện tại."
            elif job.status in {"failed", "interrupted"}:
                detail = "Job lỗi cũ này có thể gỡ khỏi history để bảng tác vụ gọn hơn."
            else:
                detail = "Metadata job hoàn tất đã cũ và không còn giữ file local trên máy."

            removable_job_ids.append(job.id)
            safe_entries.append(self._cleanup_job_item(job, detail, status="safe"))

        safe_count = len(safe_entries)
        protected_count = len(protected_entries)
        if safe_count:
            summary = "Các job cũ này chỉ còn là metadata, nên có thể gỡ khỏi history mà không đụng tới file local còn tồn tại."
        elif protected_count:
            summary = "History hiện chỉ còn các job mới hơn hoặc vẫn còn gắn với artifact local cần giữ."
        else:
            summary = "History hiện chưa có mục cũ nào cần dọn."

        group = CleanupGroupSnapshot(
            key="history",
            label="History cũ",
            action_label="Dọn history cũ",
            summary=summary,
            empty_label="Chưa có metadata history nào cần dọn.",
            safe_count=safe_count,
            safe_bytes=0,
            protected_count=protected_count,
            protected_bytes=0,
            notes=[
                "Chỉ gỡ metadata job cũ khỏi state của app.",
                "Job còn mới hoặc còn gắn với file local trên máy sẽ được giữ lại mặc định.",
            ],
            safe_items=safe_entries[: self.CLEANUP_PREVIEW_LIMIT],
            protected_items=protected_entries[: self.CLEANUP_PREVIEW_LIMIT],
        )
        return group, {"paths": [], "artifact_refs": {}, "job_ids": removable_job_ids}

    def _download_cleanup_roots(self) -> List[Path]:
        roots = [DOWNLOADS_DIR.resolve()]
        configured = str(self.store.snapshot().config.output_dir or "").strip()
        if configured:
            try:
                roots.insert(0, Path(configured).expanduser().resolve())
            except OSError:
                pass

        unique_roots: List[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root)
            if key in seen:
                continue
            seen.add(key)
            unique_roots.append(root)
        return unique_roots

    def _download_artifact_reference_map(
        self,
        jobs: List[JobRecord],
        roots: List[Path],
    ) -> Dict[str, List[Dict[str, Any]]]:
        references: Dict[str, List[Dict[str, Any]]] = {}
        for job in jobs:
            job_input = job.input if isinstance(job.input, dict) else {}
            for artifact_index, artifact in enumerate(job.artifacts):
                raw_path = str(artifact.local_path or "").strip()
                if not raw_path:
                    continue
                try:
                    path = Path(raw_path).expanduser().resolve()
                except OSError:
                    continue
                if not self._path_within_roots(path, roots):
                    continue
                references.setdefault(str(path), []).append({
                    "job": job,
                    "job_input": job_input,
                    "artifact": artifact,
                    "artifact_index": artifact_index,
                })
        return references

    def _download_protection_reasons(
        self,
        refs: List[Dict[str, Any]],
        shelf_keys: set[str],
        active_workflow_id: str,
    ) -> List[str]:
        reasons: List[str] = []
        for entry in refs:
            job = entry["job"]
            artifact = entry["artifact"]
            artifact_index = int(entry["artifact_index"])
            workflow_id = str(artifact.workflow_id or entry["job_input"].get("workflow_id", "") or "").strip()
            activity_at = self._job_activity_datetime(job)

            if job.status in {"queued", "running", "polling"}:
                reasons.append("Tệp này vẫn gắn với job chưa hoàn tất.")
            if self._is_recent_datetime(activity_at, days=self.CLEANUP_DOWNLOAD_RETENTION_DAYS):
                reasons.append(f"Job này còn mới trong khoảng {self.CLEANUP_DOWNLOAD_RETENTION_DAYS} ngày gần đây.")
            if f"{job.id}:{artifact_index}" in shelf_keys:
                reasons.append("Artifact này vẫn đang nằm trên output shelf gần đây.")
            if active_workflow_id and workflow_id and workflow_id == active_workflow_id:
                reasons.append("Artifact này còn thuộc workflow mặc định đang ghim.")

        deduped: List[str] = []
        seen: set[str] = set()
        for reason in reasons:
            if reason in seen:
                continue
            seen.add(reason)
            deduped.append(reason)
        return deduped

    def _cleanup_file_item(
        self,
        path: Path,
        root: Path,
        *,
        detail: str,
        size_bytes: int,
        status: str,
    ) -> CleanupItemSnapshot:
        status_label = "An toàn để xóa" if status == "safe" else "Đang giữ lại"
        relative_path = path.name
        try:
            relative_path = str(path.relative_to(root))
        except ValueError:
            relative_path = path.name
        return CleanupItemSnapshot(
            key=str(path),
            label=path.name,
            detail=detail,
            path_hint=f"{root.name}/{relative_path}".replace("\\", "/"),
            bytes=size_bytes,
            status=status,
            status_label=status_label,
        )

    def _cleanup_job_item(self, job: JobRecord, detail: str, *, status: str) -> CleanupItemSnapshot:
        status_label = "An toàn để xóa" if status == "safe" else "Đang giữ lại"
        return CleanupItemSnapshot(
            key=job.id,
            label=job.title or self._job_type_label(job.type),
            detail=f"{self._job_type_label(job.type)} · {detail}",
            path_hint=f"job {job.id[:8]}",
            bytes=0,
            status=status,
            status_label=status_label,
        )

    def _job_has_existing_local_artifacts(self, job: JobRecord) -> bool:
        for artifact in job.artifacts:
            if str(artifact.local_path or "").strip() and self._artifact_local_exists(str(artifact.local_path or "").strip()):
                return True
        return False

    def _job_touches_workflow(self, job: JobRecord, workflow_id: str) -> bool:
        safe_workflow_id = str(workflow_id or "").strip()
        if not safe_workflow_id:
            return False
        job_input = job.input if isinstance(job.input, dict) else {}
        if str(job_input.get("workflow_id", "") or "").strip() == safe_workflow_id:
            return True
        return any(str(artifact.workflow_id or "").strip() == safe_workflow_id for artifact in job.artifacts)

    def _list_cleanup_files(self, roots: List[Path]) -> List[Path]:
        files: List[Path] = []
        seen: set[str] = set()
        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            for candidate in root.rglob("*"):
                if not candidate.is_file() or candidate.name == ".gitkeep":
                    continue
                try:
                    resolved = candidate.resolve()
                except OSError:
                    continue
                key = str(resolved)
                if key in seen or not self._path_within_roots(resolved, [root]):
                    continue
                seen.add(key)
                files.append(resolved)
        return files

    def _matching_cleanup_root(self, path: Path, roots: List[Path]) -> Path:
        for root in roots:
            if self._path_within_roots(path, [root]):
                return root
        return roots[0]

    def _path_within_roots(self, path: Path, roots: List[Path]) -> bool:
        for root in roots:
            try:
                path.relative_to(root)
            except ValueError:
                continue
            return True
        return False

    def _path_modified_datetime(self, path: Path) -> datetime | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

    def _is_recent_datetime(self, value: datetime | None, *, days: int = 0, hours: int = 0) -> bool:
        if value is None:
            return False
        threshold = datetime.now(timezone.utc) - timedelta(days=max(0, days), hours=max(0, hours))
        return value >= threshold

    def _file_size(self, path: Path) -> int:
        try:
            return int(path.stat().st_size)
        except OSError:
            return 0

    def _delete_cleanup_file(self, path: Path, roots: List[Path]) -> str:
        try:
            resolved = Path(path).expanduser().resolve()
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"Không thể xác định tệp cần dọn: {path}") from exc

        if not self._path_within_roots(resolved, roots):
            raise HTTPException(status_code=403, detail="Tệp cần dọn nằm ngoài phạm vi an toàn của app.")
        if resolved.exists() and not resolved.is_file():
            raise HTTPException(status_code=400, detail="Cleanup chỉ hỗ trợ xóa tệp, không xóa thư mục.")
        if resolved.exists():
            resolved.unlink()
        return str(resolved)

    def _public_download_url(self, local_path: str) -> str:
        path = Path(local_path).resolve()
        default_root = DOWNLOADS_DIR.resolve()
        if str(path).startswith(str(default_root)):
            return f"/files/downloads/{path.name}"
        return ""

    def _validate_job_request(self, request: CreateJobRequest) -> None:
        if request.type != "login" and not self.get_auth_status().authenticated:
            raise HTTPException(
                status_code=400,
                detail="Cần đăng nhập Google Flow trước khi chạy tác vụ. Hãy bấm Đăng nhập Google Flow rồi thử lại.",
            )

        if request.type == "video" and not request.prompt.strip():
            raise HTTPException(status_code=400, detail="Hãy nhập mô tả video trước khi chạy.")

        if request.type == "image" and not request.prompt.strip():
            raise HTTPException(status_code=400, detail="Hãy nhập mô tả ảnh trước khi chạy.")

        if request.type == "image" and len(request.reference_image_paths) > 4:
            raise HTTPException(status_code=400, detail="Tối đa 4 ảnh tham chiếu cho một lượt chỉnh ảnh.")

        if request.type == "video" and len(request.reference_image_paths) > 4:
            raise HTTPException(status_code=400, detail="Tối đa 4 ảnh tham chiếu cho một lượt tạo video.")

        if request.type in {"video", "image"} and not 1 <= int(request.count) <= 4:
            raise HTTPException(status_code=400, detail="Số lượng cho tác vụ tạo nội dung phải nằm trong khoảng 1 đến 4.")

        if request.type == "image" and self._normalize_image_model(request.model) not in self.IMAGE_MODEL_LABELS:
            raise HTTPException(status_code=400, detail="Model ảnh này hiện chưa được hỗ trợ trong app.")

        if request.type in {"extend", "upscale", "camera_motion", "camera_position", "insert", "remove"}:
            if not request.media_id.strip():
                raise HTTPException(status_code=400, detail="Vui lòng nhập Media ID cho tác vụ chỉnh sửa.")

        if request.type == "camera_motion" and not request.motion.strip():
            raise HTTPException(status_code=400, detail="Vui lòng chọn chuyển động camera.")

        if request.type == "camera_position" and not request.position.strip():
            raise HTTPException(status_code=400, detail="Vui lòng chọn vị trí camera.")

        if request.type == "insert" and not request.prompt.strip():
            raise HTTPException(status_code=400, detail="Vui lòng nhập prompt để chèn vật thể.")

    def _image_api_aspect_ratio(self, aspect: str) -> str:
        normalized = self._parse_aspect(aspect or "landscape")
        if normalized == "portrait":
            return "IMAGE_ASPECT_RATIO_PORTRAIT"
        if normalized == "square":
            return "IMAGE_ASPECT_RATIO_SQUARE"
        return "IMAGE_ASPECT_RATIO_LANDSCAPE"

    def _normalize_video_model(self, model: str) -> str:
        raw = str(model or "").strip()
        if not raw:
            return self.DEFAULT_VIDEO_MODEL
        compact = re.sub(r"\s+", " ", raw).strip().lower()
        return self.VIDEO_MODEL_DISPLAY_ALIASES.get(compact, raw)

    def _normalize_image_model(self, model: str) -> str:
        raw = str(model or "").strip()
        if not raw:
            return self.DEFAULT_IMAGE_MODEL
        compact = re.sub(r"\s+", " ", raw).strip().lower()
        normalized = self.IMAGE_MODEL_ALIASES.get(compact, raw.upper())
        if normalized not in self.IMAGE_MODEL_LABELS:
            return self.DEFAULT_IMAGE_MODEL
        return normalized

    def _normalize_job_model(self, request_type: str, model: str) -> str:
        kind = str(request_type or "").strip()
        if kind == "video":
            return self._normalize_video_model(model)
        if kind == "image":
            return self._normalize_image_model(model)
        return str(model or "").strip()

    def _normalize_policy_text(self, value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        normalized = unicodedata.normalize("NFD", raw)
        normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
        normalized = re.sub(r"[^a-zA-Z0-9\s]", " ", normalized).lower()
        return re.sub(r"\s+", " ", normalized).strip()

    def _policy_text_has_any(self, text: str, terms: tuple[str, ...]) -> bool:
        if not text:
            return False
        return any(term in text for term in terms)

    def _policy_preflight_notice(self, request: CreateJobRequest) -> str:
        normalized_prompt = self._normalize_policy_text(request.prompt)
        has_minor = self._policy_text_has_any(normalized_prompt, self.POLICY_MINOR_TERMS)
        has_appearance = self._policy_text_has_any(normalized_prompt, self.POLICY_APPEARANCE_TERMS)
        has_apparel = self._policy_text_has_any(normalized_prompt, self.POLICY_APPAREL_TERMS)
        normalized_roles = self._normalize_reference_image_roles(
            list(request.reference_image_paths or []),
            list(request.reference_image_roles or []),
        )
        has_reference_images = bool(request.start_image_path or request.reference_image_paths or request.reference_media_names)
        has_product_images = any(role == "product" for role in normalized_roles)

        if has_minor and (has_appearance or has_apparel or has_reference_images):
            return (
                "Cảnh báo an toàn: prompt này có nguy cơ bị Google Flow chặn nếu ảnh hoặc mô tả ám chỉ người chưa đủ tuổi. "
                "Nếu đang làm quần áo, logo hoặc beauty edit, hãy đổi sang người mẫu trưởng thành rõ ràng, mannequin hoặc flat-lay."
            )

        if has_reference_images and (has_appearance or has_apparel or has_product_images):
            return (
                "Gợi ý an toàn: nếu ảnh tham chiếu là người trông quá trẻ, Google Flow thường chặn các ca thay đồ, ghép logo lên áo hoặc làm đẹp ngoại hình. "
                "Chủ nhân nên dùng người mẫu trưởng thành, mannequin hoặc ảnh sản phẩm riêng."
            )

        return ""

    def _image_api_model_name(self, model: str) -> str:
        return self._normalize_image_model(model)

    def _image_edit_model_name(self, model: str) -> str:
        normalized = self._normalize_image_model(model)
        return self.IMAGE_MODEL_EDIT_VALUES.get(normalized, self.IMAGE_MODEL_EDIT_VALUES[self.DEFAULT_IMAGE_MODEL])

    def _image_ui_model_label(self, model: str) -> str:
        normalized = self._normalize_image_model(model)
        return self.IMAGE_MODEL_LABELS.get(normalized, self.IMAGE_MODEL_LABELS[self.DEFAULT_IMAGE_MODEL])

    def _normalize_reference_image_role(self, role: str) -> str:
        normalized = re.sub(r"[^a-z]+", "", str(role or "").strip().lower())
        if normalized in {"base", "main", "model", "subject", "primary"}:
            return "base"
        if normalized in {"logo", "brand"}:
            return "logo"
        if normalized in {"product", "item"}:
            return "product"
        return "reference"

    def _start_image_search_terms(self, value: str) -> List[str]:
        raw = str(value or "").strip()
        if not raw:
            return []

        candidates = [raw]
        try:
            path = PureWindowsPath(raw) if ("\\" in raw or re.match(r"^[A-Za-z]:", raw)) else Path(raw)
        except Exception:
            path = None

        if path is not None:
            name = path.name.strip()
            stem = path.stem.strip()
            if name:
                candidates.append(name)
            if stem:
                candidates.append(stem)

        normalized_variants: List[str] = []
        for item in candidates:
            compact = re.sub(r"\s+", " ", str(item or "").strip())
            if compact:
                normalized_variants.append(compact)
            simple = re.sub(r"[^a-z0-9]+", " ", str(item or "").strip().lower())
            simple = re.sub(r"\s+", " ", simple).strip()
            if simple:
                normalized_variants.append(simple)

        ordered: List[str] = []
        seen: set[str] = set()
        for item in normalized_variants:
            key = item.lower()
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(item)
        return ordered

    def _normalize_reference_image_roles(self, image_paths: List[str], roles: List[str]) -> List[str]:
        path_count = len(image_paths or [])
        if path_count <= 0:
            return []

        normalized = [
            self._normalize_reference_image_role(roles[index] if index < len(roles or []) else "")
            for index in range(path_count)
        ]
        if "base" not in normalized:
            normalized[0] = "base"
        else:
            base_index = normalized.index("base")
            normalized = ["reference" if role == "base" and index != base_index else role for index, role in enumerate(normalized)]
        return normalized

    def _ordered_reference_media_names(
        self,
        media_items: List[Dict[str, str]],
        fallback_names: List[str] | None = None,
    ) -> List[str]:
        ordered: List[str] = []
        seen: set[str] = set()

        def push(name: str) -> None:
            safe_name = str(name or "").strip()
            if not safe_name or safe_name in seen:
                return
            seen.add(safe_name)
            ordered.append(safe_name)

        for role in ("base", "product", "logo", "reference"):
            for item in media_items:
                if str(item.get("role") or "") == role:
                    push(item.get("media_name", ""))

        for name in fallback_names or []:
            push(name)
        return ordered

    def _normalize_local_upload_paths(self, values: List[str]) -> List[str]:
        roots = [UPLOADS_DIR.resolve()]
        normalized: List[str] = []
        seen: set[str] = set()
        for value in values:
            raw = str(value or "").strip()
            if not raw:
                continue
            try:
                resolved = Path(raw).expanduser().resolve()
            except OSError:
                continue
            if not resolved.exists() or not resolved.is_file():
                continue
            if not self._path_within_roots(resolved, roots):
                continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(key)
        return normalized

    def _video_reference_prompt_suffix(self, request: CreateJobRequest) -> str:
        prompt_text = self._normalize_skill_token(request.prompt or "")
        suffix_parts = [
            "first storyboard keyframe for a later image-to-video shot",
            "cinematic hero frame with clean full-subject readability",
            "keep the exact product design, logo placement, fabric color, material texture, and silhouette from the reference images",
            "if the reference image is clothing, accessories, or a product, place it naturally on a photoreal human model or in a believable real-world usage scene instead of leaving it as a flat packshot",
            "strong continuity-ready frame that can animate cleanly into a video",
        ]
        if any(
            token in prompt_text
            for token in (
                "ao",
                "shirt",
                "tshirt",
                "hoodie",
                "fashion",
                "thoi trang",
                "jacket",
                "dress",
                "quan",
                "giay",
                "shoe",
                "bag",
            )
        ):
            suffix_parts.append("show a photoreal fashion model wearing the referenced item naturally")
        if any(token in prompt_text for token in ("logo", "brand", "thuong hieu", "nhan")):
            suffix_parts.append("preserve brand marks sharply and naturally on the product")
        return ", ".join(suffix_parts)

    def _video_start_frame_prompt(self, request: CreateJobRequest) -> str:
        selected = self._select_prompt_skills(
            "image",
            request.prompt,
            "cinematic start frame for video",
            self._video_reference_prompt_suffix(request),
        )
        baseline = self._compose_prompt_draft(
            PromptCreateRequest(
                mode="image",
                brief=request.prompt,
                style="cinematic start frame for video",
                must_include=self._video_reference_prompt_suffix(request),
                avoid="flat lay ecommerce photo, isolated catalog cutout, watermark, broken anatomy",
                audience="video generation start frame",
                aspect=self._parse_aspect(request.aspect or "landscape"),
            ),
            selected,
        )
        prompt, _ = self._ensure_prompt_detail(baseline, baseline, "image")
        return prompt

    async def _download_intermediate_image(
        self,
        client: Any,
        job_id: str,
        source_url: str,
        *,
        suffix: str = ".jpg",
    ) -> str:
        target = UPLOADS_DIR / f"{job_id}-video-start{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            saved = await client.download(source_url, target)
        except Exception as exc:
            raise RuntimeError("Flow đã tạo ảnh khung đầu nhưng app chưa tải ảnh đó về máy để dựng video.") from exc
        return str(Path(saved).expanduser().resolve())

    async def _prepare_video_start_image_from_references(
        self,
        client: Any,
        job_id: str,
        request: CreateJobRequest,
    ) -> tuple[str, str]:
        reference_media_names = await self._resolve_image_reference_media(client, job_id, request)
        if not reference_media_names:
            raise RuntimeError("Chưa có ảnh tham chiếu hợp lệ để dựng khung đầu cho video.")

        prompt = self._video_start_frame_prompt(request)
        await self.store.append_log(job_id, "Đang dùng ảnh tham chiếu để dựng một ảnh khung đầu trước khi tạo video.")
        await self._set_job_progress(
            job_id,
            "sending_request",
            "Em đang dựng một ảnh khung đầu từ ảnh tham chiếu để dùng tiếp cho bước tạo video.",
        )
        image_request = CreateJobRequest(
            type="image",
            prompt=prompt,
            model=self.DEFAULT_IMAGE_MODEL,
            aspect=request.aspect,
            count=1,
            timeout_s=max(30, int(request.timeout_s or self.store.snapshot().config.generation_timeout_s or 300)),
            reference_media_names=reference_media_names,
            workflow_id=request.workflow_id or "",
        )
        images = await self._generate_images_with_retry(client, job_id, image_request, reference_media_names)
        if not images:
            raise RuntimeError("Flow chưa dựng được ảnh khung đầu từ các ảnh tham chiếu.")

        first_image = images[0]
        source_url = str(getattr(first_image, "fife_url", "") or "").strip()
        if not source_url:
            raise RuntimeError("Flow đã dựng ảnh khung đầu nhưng chưa trả URL ảnh để tiếp tục tạo video.")
        local_path = await self._download_intermediate_image(client, job_id, source_url)
        current_job = self.store.get_job(job_id)
        current_result = dict(getattr(current_job, "result", {}) or {})
        current_result.update(
            {
                "auto_start_frame_path": local_path,
                "auto_start_frame_public_url": f"/files/uploads/{Path(local_path).name}",
                "auto_start_frame_prompt": prompt,
                "auto_start_frame_at": utc_now(),
            }
        )
        await self.store.patch_job(job_id, result=current_result)
        await self.store.append_log(job_id, f"Đã dựng xong ảnh khung đầu và lưu tạm tại {Path(local_path).name}.")
        return local_path, prompt

    async def _resolve_image_reference_media(self, client: Any, job_id: str, request: CreateJobRequest) -> List[str]:
        reference_media_names = self._normalize_reference_media_names(request.reference_media_names or [])
        reference_image_paths = self._normalize_local_upload_paths(request.reference_image_paths or [])
        if not reference_image_paths:
            return reference_media_names

        reference_roles = self._normalize_reference_image_roles(reference_image_paths, request.reference_image_roles or [])
        total = len(reference_image_paths)
        await self.store.append_log(job_id, f"Đang chuẩn bị {total} ảnh tham chiếu để ghép/chỉnh ảnh.")
        uploaded_items: List[Dict[str, str]] = []
        for index, image_path in enumerate(reference_image_paths):
            role = reference_roles[index] if index < len(reference_roles) else ("base" if index == 0 else "reference")
            role_label = self.REFERENCE_IMAGE_ROLE_LABELS.get(role, "tham chiếu")
            await self._set_job_progress(
                job_id,
                "sending_request",
                f"Em đang tải ảnh {role_label} {index + 1}/{total} lên Flow trước khi chỉnh ảnh.",
            )
            await self.store.append_log(job_id, f"Đang tải ảnh {role_label} {index + 1}/{total}: {Path(image_path).name}")
            media_name = await self._upload_project_image_robust(client, image_path)
            if media_name:
                uploaded_items.append({"role": role, "media_name": media_name})

        return self._ordered_reference_media_names(uploaded_items, reference_media_names)

    async def _upload_project_image_robust(self, client: Any, image_path: str) -> str:
        image_file = Path(str(image_path or "")).expanduser().resolve()
        if not image_file.exists():
            raise RuntimeError(f"Khong tim thay anh de tai len: {image_file}")

        page = await client._bm.page()
        project_url = str(
            getattr(client, "_project_url", "")
            or getattr(getattr(client, "_api", None), "_project_page_url", "")
            or self._project_url(getattr(client, "project_id", ""))
        ).strip()
        await self._ensure_valid_flow_project_page(page, project_url)

        before_data = await client._api.get_project_data()
        known_media = self._project_media_names(before_data)

        selectors = [
            'input[type="file"][accept*="image"]',
            'input[type="file"]',
        ]
        uploaded = False
        for selector in selectors:
            locator = page.locator(selector)
            count = await locator.count()
            for index in range(count):
                candidate = locator.nth(index)
                try:
                    await candidate.set_input_files(str(image_file))
                    uploaded = True
                    break
                except Exception:
                    continue
            if uploaded:
                break

        if not uploaded:
            for trigger in (
                page.locator("button").filter(has_text="Add Media").first,
                page.get_by_text("Add Media", exact=True).first,
                page.locator("button").filter(has_text="Upload image").first,
                page.get_by_text("Upload image", exact=True).first,
            ):
                try:
                    if await trigger.count() == 0:
                        continue
                    await trigger.click(force=True)
                    await asyncio.sleep(0.5)
                    for selector in selectors:
                        locator = page.locator(selector)
                        count = await locator.count()
                        for index in range(count):
                            candidate = locator.nth(index)
                            try:
                                await candidate.set_input_files(str(image_file))
                                uploaded = True
                                break
                            except Exception:
                                continue
                        if uploaded:
                            break
                    if uploaded:
                        break
                except Exception:
                    continue

        if not uploaded:
            raise RuntimeError(f"Failed to upload: {image_file}")

        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline:
            data = await client._api.get_project_data()
            for workflow in data.get("projectContents", {}).get("workflows", []) or []:
                media_name = str((workflow.get("metadata") or {}).get("primaryMediaId") or "").strip()
                if media_name and media_name not in known_media:
                    return media_name
                for media in workflow.get("medias", []) or []:
                    media_name = str(media.get("name") or "").strip()
                    if media_name and media_name not in known_media:
                        return media_name
            await asyncio.sleep(1.0)

        raise RuntimeError(f"Flow da nhan thao tac upload nhung chua thay anh xuat hien: {image_file.name}")

    def _project_media_names(self, project_data: Dict[str, Any]) -> set[str]:
        names: set[str] = set()
        for media in self._project_media_items(project_data):
            media_name = str(media.get("name") or media.get("mediaName") or "").strip()
            if media_name:
                names.add(media_name)
        for workflow in project_data.get("projectContents", {}).get("workflows", []) or []:
            metadata = workflow.get("metadata", {}) or {}
            primary_media_id = str(metadata.get("primaryMediaId") or "").strip()
            if primary_media_id:
                names.add(primary_media_id)
            for media in workflow.get("medias", []) or []:
                media_name = str(media.get("name") or "").strip()
                if media_name:
                    names.add(media_name)
        return names

    def _project_media_items(self, project_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        project_contents = project_data.get("projectContents", {}) if isinstance(project_data, dict) else {}
        media_collection = project_contents.get("media") if isinstance(project_contents, dict) else None
        if isinstance(media_collection, dict):
            return [item for item in media_collection.values() if isinstance(item, dict)]
        if isinstance(media_collection, list):
            return [item for item in media_collection if isinstance(item, dict)]
        return []

    def _project_workflow_metadata_by_id(self, project_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        workflows = ((project_data.get("projectContents") or {}).get("workflows") or []) if isinstance(project_data, dict) else []
        metadata_by_id: Dict[str, Dict[str, Any]] = {}
        for workflow in workflows:
            if not isinstance(workflow, dict):
                continue
            workflow_id = str(workflow.get("name") or "").strip()
            if workflow_id:
                metadata_by_id[workflow_id] = workflow.get("metadata", {}) or {}
        return metadata_by_id

    def _project_generated_images(
        self,
        project_data: Dict[str, Any],
        *,
        known_media: set[str] | None = None,
        prompt: str = "",
        limit: int = 4,
        fallback_workflow_id: str = "",
    ) -> List[Any]:
        from flow._api import GeneratedImage

        known = {str(item or "").strip() for item in (known_media or set()) if str(item or "").strip()}
        images: List[Any] = []
        seen: set[str] = set()
        workflow_metadata_by_id = self._project_workflow_metadata_by_id(project_data)

        media_sources = list(self._project_media_items(project_data))
        workflows = project_data.get("projectContents", {}).get("workflows", []) or []
        for workflow in workflows:
            if not isinstance(workflow, dict):
                continue
            workflow_id = str(workflow.get("name") or fallback_workflow_id or "").strip()
            for media_item in workflow.get("medias", []) or []:
                if not isinstance(media_item, dict):
                    continue
                if not media_item.get("workflowId") and workflow_id:
                    media_item = {**media_item, "workflowId": workflow_id, "projectId": media_item.get("projectId") or workflow.get("projectId")}
                media_sources.append(media_item)

        for media_item in media_sources:
            media_name = str(media_item.get("name") or media_item.get("mediaName") or "").strip()
            if not media_name or media_name in known or media_name in seen:
                continue
            image_node = media_item.get("image") or {}
            generated = image_node.get("generatedImage") or {}
            if not generated:
                continue

            workflow_id = str(media_item.get("workflowId") or fallback_workflow_id or "").strip()
            metadata = workflow_metadata_by_id.get(workflow_id, {})
            media_metadata = media_item.get("mediaMetadata", {}) or {}
            request_data = media_metadata.get("requestData", {}) or {}
            workflow_prompt = str(
                generated.get("prompt")
                or metadata.get("displayName")
                or self._prompt_from_flow_request_data(request_data)
                or prompt
                or ""
            ).strip()
            workflow_create_time = str(
                media_metadata.get("createTime")
                or metadata.get("createTime")
                or ""
            ).strip()
            fife_url = str(
                generated.get("fifeUrl")
                or generated.get("url")
                or image_node.get("fifeUrl")
                or media_item.get("fifeUrl")
                or ""
            ).strip()

            image = GeneratedImage.__new__(GeneratedImage)
            image._raw = media_item
            image.media_name = media_name
            image.project_id = str(media_item.get("projectId") or "").strip()
            image.workflow_id = workflow_id
            image.fife_url = fife_url
            image.seed = generated.get("seed", 0)
            image.model = str(generated.get("modelNameType") or generated.get("model") or "").strip()
            image.prompt = workflow_prompt
            image.dimensions = image_node.get("dimensions") or media_item.get("dimensions", {}) or {}
            image.file_path = None
            image._flow_workflow_create_time = workflow_create_time
            images.append(image)
            seen.add(media_name)

        images.sort(key=lambda item: str(getattr(item, "_flow_workflow_create_time", "") or ""), reverse=True)
        return images[: max(1, min(4, int(limit or 1)))]

    def _prompt_from_flow_request_data(self, request_data: Dict[str, Any]) -> str:
        prompt_inputs = request_data.get("promptInputs", []) if isinstance(request_data, dict) else []
        for prompt_input in prompt_inputs or []:
            if not isinstance(prompt_input, dict):
                continue
            text_input = str(prompt_input.get("textInput") or "").strip()
            if text_input:
                return text_input
            structured = prompt_input.get("structuredPrompt") or {}
            parts = structured.get("parts", []) if isinstance(structured, dict) else []
            text = " ".join(str(part.get("text") or "").strip() for part in parts if isinstance(part, dict)).strip()
            if text:
                return text
        return ""

    async def _flow_project_image_urls_by_workflow(self, client: Any) -> Dict[str, str]:
        page = await client._bm.page()
        try:
            return await page.evaluate(
                """
                () => {
                  const urls = {};
                  const links = [...document.querySelectorAll('a[href*="/edit/"]')];
                  for (const link of links) {
                    const href = link.href || link.getAttribute('href') || '';
                    const match = href.match(/\\/edit\\/([^/?#]+)/);
                    if (!match) continue;
                    const img = link.querySelector('img[src], img[srcset]');
                    const src = img ? (img.currentSrc || img.src || '') : '';
                    if (src && !src.startsWith('data:')) {
                      urls[match[1]] = src;
                    }
                  }
                  return urls;
                }
                """
            )
        except Exception:
            return {}

    async def _wait_for_new_project_images(
        self,
        client: Any,
        known_media: set[str],
        *,
        prompt: str,
        target_count: int,
        timeout_s: float,
        fallback_workflow_id: str = "",
    ) -> List[Any]:
        target = max(1, min(4, int(target_count or 1)))
        deadline = time.monotonic() + max(5.0, float(timeout_s or 30))
        best: List[Any] = []
        first_seen_at = 0.0

        while time.monotonic() < deadline:
            try:
                project_data = await client._api.get_project_data()
            except Exception:
                await asyncio.sleep(1.0)
                continue

            images = self._project_generated_images(
                project_data,
                known_media=known_media,
                prompt=prompt,
                limit=target,
                fallback_workflow_id=fallback_workflow_id,
            )
            if images and any(not str(getattr(image, "fife_url", "") or "").strip() for image in images):
                urls_by_workflow = await self._flow_project_image_urls_by_workflow(client)
                for image in images:
                    if str(getattr(image, "fife_url", "") or "").strip():
                        continue
                    workflow_id = str(getattr(image, "workflow_id", "") or "").strip()
                    image.fife_url = urls_by_workflow.get(workflow_id, "")
                images = [image for image in images if str(getattr(image, "fife_url", "") or "").strip()]
            if len(images) > len(best):
                best = images
                first_seen_at = first_seen_at or time.monotonic()
            if len(best) >= target:
                return best[:target]
            if best and first_seen_at and time.monotonic() - first_seen_at >= 4.0:
                return best[:target]
            await asyncio.sleep(1.0)

        if best:
            return best[:target]
        raise RuntimeError("Google Flow không trả ảnh mới trong project sau khi bấm tạo ảnh.")

    async def _generate_image_edit_result(
        self,
        client: Any,
        prompt: str,
        *,
        model: str,
        aspect: str,
        count: int,
        reference_media_names: List[str],
        workflow_id: str = "",
    ) -> List[Any]:
        normalized_media_names = self._normalize_reference_media_names(reference_media_names)
        if not normalized_media_names:
            raise RuntimeError("Chưa có ảnh nào để dùng làm đầu vào chỉnh sửa.")

        base_media_name = normalized_media_names[0]
        extra_reference_media_names = normalized_media_names[1:]
        resolved_workflow_id = str(workflow_id or "").strip() or await self._find_workflow_id_for_media(client, base_media_name)
        if not resolved_workflow_id:
            raise RuntimeError(
                "Google Flow chưa tìm thấy workflow gắn với ảnh gốc. Hãy thử tải lại ảnh rồi chạy lại giúp em."
            )

        client_context = dict(await client._api._client_context())
        client_context["workflowId"] = resolved_workflow_id

        image_inputs = [
            {
                "imageInputType": "IMAGE_INPUT_TYPE_BASE_IMAGE",
                "name": base_media_name,
            }
        ]
        image_inputs.extend(
            {
                "imageInputType": "IMAGE_INPUT_TYPE_REFERENCE",
                "name": media_name,
            }
            for media_name in extra_reference_media_names
        )

        body = {
            "clientContext": client_context,
            "mediaGenerationContext": {"batchId": str(uuid.uuid4())},
            "useNewMedia": True,
            "requests": [
                {
                    "clientContext": dict(client_context),
                    "imageModelName": self._image_edit_model_name(model),
                    "imageAspectRatio": self._image_api_aspect_ratio(aspect),
                    "structuredPrompt": {"parts": [{"text": prompt}]},
                    "seed": random.randint(0, 2**31 - 1),
                    "imageInputs": list(image_inputs),
                }
                for _ in range(max(1, min(4, int(count or 1))))
            ],
        }
        data = await client._api._fetch(
            "POST",
            f"projects/{client._api.project_id}/flowMedia:batchGenerateImages",
            body,
        )

        from flow._api import GeneratedImage

        images = [GeneratedImage(item) for item in data.get("media", [])]
        for image in images:
            image.prompt = prompt
        if not images:
            raise RuntimeError("Google Flow không trả ảnh nào về từ yêu cầu chỉnh sửa hiện tại.")
        return images

    async def _generate_images_with_retry(
        self,
        client: Any,
        job_id: str,
        request: CreateJobRequest,
        reference_media_names: List[str],
    ) -> List[Any]:
        try:
            return await self._generate_images_once(client, request, reference_media_names)
        except Exception as exc:
            if not self._is_recaptcha_error(exc):
                raise

            await self.store.append_log(
                job_id,
                "Flow API tu choi luot gui tu dong. Em dang chuyen sang duong chay qua giao dien Flow de thu lai.",
            )
            await self._set_job_progress(
                job_id,
                "sending_request",
                "Flow API tu choi luot gui truc tiep. Em dang tai lai project va gui lai bang giao dien Flow.",
            )
            await self._reload_flow_project_page(client)
            return await self._generate_images_via_ui(client, request, reference_media_names, job_id=job_id)

    async def _generate_images_once(
        self,
        client: Any,
        request: CreateJobRequest,
        reference_media_names: List[str],
    ) -> List[Any]:
        target_count = max(1, min(4, int(request.count or 1)))
        if reference_media_names:
            return await self._generate_image_edit_result(
                client,
                request.prompt,
                model=request.model,
                aspect=request.aspect,
                count=target_count,
                reference_media_names=reference_media_names,
                workflow_id=request.workflow_id or "",
            )
        return await client._api.generate_image(
            request.prompt,
            model=self._image_api_model_name(request.model),
            aspect_ratio=self._image_api_aspect_ratio(request.aspect),
            count=target_count,
        )

    async def _generate_images_via_ui(
        self,
        client: Any,
        request: CreateJobRequest,
        reference_media_names: List[str],
        *,
        job_id: str = "",
    ) -> List[Any]:
        if reference_media_names:
            if len(reference_media_names) > 1:
                raise RuntimeError(
                    "Flow API dang chan nhanh ghep nhieu anh, nen em chua the fallback UI an toan cho hon 1 anh tham chieu."
                )
            return await self._generate_single_reference_image_via_ui(
                client,
                request.prompt,
                model=request.model,
                workflow_id=request.workflow_id or "",
                reference_media_name=reference_media_names[0],
                count=max(1, min(4, int(request.count or 1))),
                timeout_s=max(30, int(request.timeout_s or self.store.snapshot().config.generation_timeout_s or 300)),
                job_id=job_id,
            )
        return await client.generate_image(
            request.prompt,
            model=self._image_ui_model_label(request.model),
            aspect=request.aspect,
            count=max(1, min(4, int(request.count or 1))),
            timeout_s=max(30, int(request.timeout_s or self.store.snapshot().config.generation_timeout_s or 300)),
        )

    async def _generate_single_reference_image_via_ui(
        self,
        client: Any,
        prompt: str,
        *,
        model: str,
        reference_media_name: str,
        workflow_id: str = "",
        count: int = 1,
        timeout_s: int = 120,
        job_id: str = "",
    ) -> List[Any]:
        from flow._ui_interceptor import UIInterceptor

        resolved_workflow_id = str(workflow_id or "").strip() or await self._find_workflow_id_for_media(client, reference_media_name)
        if not resolved_workflow_id:
            raise RuntimeError("Google Flow chua tim thay workflow cua anh goc de mo man hinh chinh anh.")

        ui_timeout_s = max(60.0, min(600.0, float(timeout_s or 300)))
        page = await client._bm.page()
        project_url = self._project_url(client.project_id)
        if job_id:
            await self.store.append_log(job_id, f"Fallback UI Flow: mở project và chọn ảnh nguồn {resolved_workflow_id}.")
        try:
            await page.goto(project_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            await page.goto(project_url, wait_until="commit", timeout=60_000)
        await asyncio.sleep(2.5)
        if job_id:
            await self.store.append_log(job_id, f"Fallback UI Flow: tab hiện tại {str(getattr(page, 'url', '') or '')[:160]}.")
        selected, selected_detail = await self._select_flow_edit_target_image(page, reference_media_name)
        if not selected:
            raise RuntimeError(
                "Google Flow chua chon duoc anh goc tren project, nen em dung lai de tranh tao anh moi tu prompt. "
                f"Chi tiet: {selected_detail or 'khong tim thay anh co the click'}"
            )
        if job_id:
            await self.store.append_log(job_id, f"Fallback UI Flow: đã chọn ảnh gốc ({selected_detail[:120]}).")

        interceptor = UIInterceptor()
        interceptor.attach(page)
        interceptor.clear()

        try:
            await client._ui.open_settings_panel(page)
            await client._ui.select_image_model(page, self._image_ui_model_label(model))
            await client._ui.set_count(page, max(1, min(4, int(count or 1))))
        except Exception:
            pass

        filled = await client._ui.fill_prompt(page, prompt)
        if not filled:
            raise RuntimeError("Google Flow chua dien duoc prompt vao man hinh chinh anh.")
        if job_id:
            await self.store.append_log(job_id, "Fallback UI Flow: đã điền prompt vào ô tạo ảnh.")

        try:
            known_media_before_submit = self._project_media_names(await client._api.get_project_data())
        except Exception:
            known_media_before_submit = set()

        clicked, click_detail = await self._click_flow_create_button(page)
        if not clicked:
            clicked = await client._ui.click_submit(page)
            click_detail = "fallback FlowUI.click_submit"
        if not clicked:
            raise RuntimeError(
                "Google Flow chua bam duoc nut tao anh o man hinh chinh anh. "
                f"Chi tiet: {click_detail or 'khong tim thay nut Create/Tao'}"
            )
        if job_id:
            await self.store.append_log(job_id, f"Fallback UI Flow: đã bấm nút tạo ảnh ({click_detail[:120]}), chờ Flow trả ảnh tối đa {int(ui_timeout_s)} giây.")

        try:
            result = await interceptor.wait_for(
                "batchGenerateImages",
                timeout=ui_timeout_s,
                require_success=True,
            )
        except Exception as exc:
            detail = str(exc or "").lower()
            if "timed out" in detail or "timeout" in detail or "recaptcha" in detail:
                if job_id:
                    await self.store.append_log(job_id, f"Fallback UI Flow timeout/recaptcha: {str(exc)[:300]}")
                raise RuntimeError(
                    "Google Flow chua tra ve anh tu man hinh Flow trong thoi gian cho. "
                    "Hay kiem tra tab Flow co dang tao, bi dung o nut Create, hoac co thong bao can thao tac thu cong khong."
                ) from exc
            raise

        if not self._flow_image_call_uses_selected_image(result, reference_media_name, resolved_workflow_id):
            raise RuntimeError(
                "Flow vua gui request tao anh nhung request khong co anh goc dang chon. "
                "Em da dung lai de tranh luu anh moi khong dung card Trello."
            )

        images = self._parse_images_from_flow_payload(
            result.resp,
            prompt=prompt,
            fallback_workflow_id=resolved_workflow_id,
        )
        if not images:
            images = await self._wait_for_new_project_images(
                client,
                known_media_before_submit,
                prompt=prompt,
                target_count=max(1, min(4, int(count or 1))),
                timeout_s=ui_timeout_s,
                fallback_workflow_id=resolved_workflow_id,
            )

        if not images:
            raise RuntimeError("Google Flow khong tra anh nao ve tu man hinh chinh anh.")
        return images[: max(1, min(4, int(count or 1)))]

    async def _click_flow_create_button(self, page: Any) -> tuple[bool, str]:
        try:
            result = await page.evaluate(
                """
                () => {
                  const visible = (el) => {
                    if (!el || !(el instanceof Element)) return false;
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 24 || rect.height < 24) return false;
                    const style = window.getComputedStyle(el);
                    return style.visibility !== 'hidden' && style.display !== 'none' && style.opacity !== '0' && !el.disabled;
                  };
                  const buttons = [...document.querySelectorAll('button')]
                    .filter(visible)
                    .map((el) => ({el, rect: el.getBoundingClientRect(), text: (el.textContent || '').trim()}))
                    .filter(({text}) => /Create|Tạo|Tao|arrow_forward|add_2/i.test(text));
                  const createButtons = buttons
                    .filter(({text}) => /Create|Tạo|Tao|arrow_forward/i.test(text))
                    .sort((a, b) => (b.rect.top - a.rect.top) || (b.rect.right - a.rect.right));
                  const target = createButtons[0] || buttons.sort((a, b) => (b.rect.top - a.rect.top) || (b.rect.right - a.rect.right))[0];
                  if (!target) return {ok: false, detail: 'no visible create button'};
                  const x = target.rect.left + target.rect.width / 2;
                  const y = target.rect.top + target.rect.height / 2;
                  target.el.scrollIntoView({block: 'center', inline: 'center'});
                  return {ok: true, x, y, detail: target.text || target.el.outerHTML?.slice(0, 160) || target.el.tagName};
                }
                """
            )
        except Exception as exc:
            return False, humanize_flow_error(str(exc))

        ok = bool((result or {}).get("ok")) if isinstance(result, dict) else False
        detail = str((result or {}).get("detail") or "").strip() if isinstance(result, dict) else ""
        if not ok:
            return False, detail
        try:
            x = float((result or {}).get("x"))
            y = float((result or {}).get("y"))
            await page.mouse.move(x, y)
            await asyncio.sleep(0.1)
            await page.mouse.click(x, y)
            await asyncio.sleep(0.7)
            return True, detail
        except Exception as exc:
            return False, humanize_flow_error(str(exc))

    async def _select_flow_edit_target_image(self, page: Any, reference_media_name: str) -> tuple[bool, str]:
        media_token = str(reference_media_name or "").strip()
        try:
            result = await page.evaluate(
                """
                (mediaToken) => {
                  const visible = (el) => {
                    if (!el || !(el instanceof Element)) return false;
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 80 || rect.height < 80) return false;
                    const style = window.getComputedStyle(el);
                    return style.visibility !== 'hidden' && style.display !== 'none' && style.opacity !== '0';
                  };
                  const draggable = (el) => (
                    el.closest('[aria-roledescription*="draggable" i], [draggable="true"], [role="button"], [data-index], [data-item-index]')
                    || el.closest('a')
                    || el
                  );
                  const rectInfo = (el) => {
                    const target = draggable(el);
                    target.scrollIntoView({block: 'center', inline: 'center'});
                    const sourceRect = target.getBoundingClientRect();
                    const editors = [...document.querySelectorAll('[contenteditable="true"], div[role="textbox"], textarea')]
                      .filter((candidate) => {
                        const rect = candidate.getBoundingClientRect();
                        const style = window.getComputedStyle(candidate);
                        return rect.width > 120
                          && rect.height > 12
                          && rect.bottom > window.innerHeight * 0.45
                          && style.display !== 'none'
                          && style.visibility !== 'hidden';
                      })
                      .sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom);
                    const editor = editors[0];
                    if (!editor) return {ok: false, detail: 'no visible prompt editor'};
                    const editorRect = editor.getBoundingClientRect();
                    return {
                      ok: true,
                      sourceX: sourceRect.left + sourceRect.width / 2,
                      sourceY: sourceRect.top + sourceRect.height / 2,
                      targetX: editorRect.left + Math.min(editorRect.width - 20, Math.max(20, editorRect.width * 0.15)),
                      targetY: editorRect.top + editorRect.height / 2,
                      detail: `drag ${target.tagName.toLowerCase()} ${Math.round(sourceRect.left)},${Math.round(sourceRect.top)} -> prompt ${Math.round(editorRect.left)},${Math.round(editorRect.top)}`,
                    };
                  };

                  const token = String(mediaToken || '').trim();
                  if (token) {
                    const escaped = token.replace(/["\\\\]/g, '\\\\$&');
                    const exact = [
                      `[data-media-id*="${escaped}"]`,
                      `[data-media-name*="${escaped}"]`,
                      `[data-testid*="${escaped}"]`,
                      `img[alt*="${escaped}"]`,
                      `img[src*="${escaped}"]`,
                    ];
                    for (const selector of exact) {
                      for (const el of document.querySelectorAll(selector)) {
                        if (visible(el)) return rectInfo(el);
                      }
                    }
                    for (const el of [...document.querySelectorAll('img, canvas, [role="img"], [style*="background-image"]')]) {
                      if (!visible(el)) continue;
                      const haystack = `${el.getAttribute('alt') || ''} ${el.getAttribute('src') || ''} ${el.outerHTML || ''}`;
                      if (haystack.includes(token)) return rectInfo(el);
                    }
                  }

                  return {ok: false, detail: token ? `media token not visible: ${token}` : 'missing media token'};
                }
                """,
                media_token,
            )
        except Exception as exc:
            return False, humanize_flow_error(str(exc))

        ok = bool((result or {}).get("ok")) if isinstance(result, dict) else False
        detail = str((result or {}).get("detail") or "").strip() if isinstance(result, dict) else ""
        if ok:
            try:
                source_x = float((result or {}).get("sourceX"))
                source_y = float((result or {}).get("sourceY"))
                target_x = float((result or {}).get("targetX"))
                target_y = float((result or {}).get("targetY"))
                await page.mouse.move(source_x, source_y)
                await asyncio.sleep(0.15)
                await page.mouse.down()
                steps = 12
                for step in range(1, steps + 1):
                    x = source_x + (target_x - source_x) * step / steps
                    y = source_y + (target_y - source_y) * step / steps
                    await page.mouse.move(x, y)
                    await asyncio.sleep(0.03)
                await page.mouse.up()
                await asyncio.sleep(1.0)
                await page.mouse.click(target_x, target_y)
                await asyncio.sleep(0.3)
            except Exception as exc:
                return False, humanize_flow_error(str(exc))
        return ok, detail

    def _flow_image_call_uses_selected_image(self, call: Any, reference_media_name: str, workflow_id: str) -> bool:
        payload = getattr(call, "req", None)
        if not isinstance(payload, dict):
            return False
        expected_media = str(reference_media_name or "").strip()
        expected_workflow = str(workflow_id or "").strip()
        payload_blob = json.dumps(payload, ensure_ascii=False)
        if expected_media and expected_media in payload_blob:
            return True
        if expected_workflow and expected_workflow in payload_blob:
            return True
        requests = payload.get("requests") if isinstance(payload.get("requests"), list) else []
        for item in requests:
            if not isinstance(item, dict):
                continue
            client_context = item.get("clientContext") if isinstance(item.get("clientContext"), dict) else {}
            if expected_workflow and str(client_context.get("workflowId") or "").strip() == expected_workflow:
                return True
            image_inputs = item.get("imageInputs") if isinstance(item.get("imageInputs"), list) else []
            for image_input in image_inputs:
                if not isinstance(image_input, dict):
                    continue
                values = {
                    str(image_input.get("name") or "").strip(),
                    str(image_input.get("mediaName") or "").strip(),
                    str(image_input.get("imageInputType") or "").strip(),
                    str(image_input.get("role") or "").strip(),
                }
                if expected_media and expected_media in values:
                    return True
        return False

    async def _find_workflow_id_for_media(self, client: Any, media_name: str) -> str:
        safe_media_name = str(media_name or "").strip()
        if not safe_media_name:
            return ""

        for attempt in range(3):
            project_data = await client._api.get_project_data()
            workflows = project_data.get("projectContents", {}).get("workflows", [])
            for workflow in workflows:
                workflow_id = str(workflow.get("name") or "").strip()
                if not workflow_id:
                    continue
                metadata = workflow.get("metadata", {}) or {}
                if str(metadata.get("primaryMediaId") or "").strip() == safe_media_name:
                    return workflow_id
                for media in workflow.get("medias", []) or []:
                    if str(media.get("name") or "").strip() == safe_media_name:
                        return workflow_id
            if attempt < 2:
                await asyncio.sleep(1)

        return ""

    async def _reload_flow_project_page(self, client: Any) -> None:
        page = await client._bm.page()
        project_url = str(
            getattr(client, "_project_url", "")
            or getattr(getattr(client, "_api", None), "_project_page_url", "")
            or self._project_url(getattr(client, "project_id", ""))
        ).strip()
        if not project_url:
            return

        await self._ensure_valid_flow_project_page(page, project_url)
        try:
            await page.reload(wait_until="networkidle", timeout=60_000)
        except Exception:
            try:
                await page.reload(wait_until="domcontentloaded", timeout=60_000)
            except Exception:
                await self._ensure_valid_flow_project_page(page, project_url)

        try:
            ready = await page.wait_for_function(
                "() => !!window.grecaptcha?.enterprise?.execute",
                timeout=15_000,
            )
            await ready.dispose()
        except Exception:
            pass
        await asyncio.sleep(2.0)

    def _is_recaptcha_error(self, exc: Exception) -> bool:
        detail = str(exc or "").lower()
        return "recaptcha" in detail and "failed" in detail

    def _parse_images_from_flow_payload(
        self,
        payload: Any,
        *,
        prompt: str,
        fallback_workflow_id: str = "",
    ) -> List[Any]:
        from flow._api import GeneratedImage

        response = payload if isinstance(payload, dict) else {}
        images: List[Any] = []

        for media_item in response.get("media", []) or []:
            if not isinstance(media_item, dict):
                continue
            image = GeneratedImage.__new__(GeneratedImage)
            image._raw = media_item
            image.media_name = str(media_item.get("name") or media_item.get("mediaName") or "").strip()
            image.project_id = str(media_item.get("projectId") or "").strip()
            image.workflow_id = str(media_item.get("workflowId") or fallback_workflow_id or "").strip()
            generated = ((media_item.get("image") or {}).get("generatedImage") or {})
            image.fife_url = str(
                generated.get("fifeUrl")
                or generated.get("url")
                or media_item.get("fifeUrl")
                or ""
            ).strip()
            image.seed = generated.get("seed", 0)
            image.model = str(generated.get("modelNameType") or generated.get("model") or "").strip()
            image.prompt = str(generated.get("prompt") or prompt or "").strip()
            image.dimensions = media_item.get("dimensions", {}) or {}
            image.file_path = None
            images.append(image)

        if images:
            return images

        for item in response.get("generatedImages", []) or []:
            if not isinstance(item, dict):
                continue
            image = GeneratedImage.__new__(GeneratedImage)
            image._raw = item
            image.media_name = str(item.get("mediaName") or item.get("name") or "").strip()
            image.project_id = ""
            image.workflow_id = fallback_workflow_id
            image.fife_url = str(item.get("fifeUrl") or item.get("url") or "").strip()
            image.seed = int(item.get("seed", 0) or 0)
            image.model = str(item.get("modelNameType") or item.get("model") or "").strip()
            image.prompt = str(item.get("prompt") or prompt or "").strip()
            image.dimensions = item.get("dimensions", {}) or {}
            image.file_path = None
            images.append(image)
        return images

    async def _wait_for_video_with_progress(
        self,
        client: Any,
        job_id: str,
        video_job: Any,
        label: str,
        *,
        poll_s: float,
        timeout_s: int,
    ) -> Any:
        await self.store.patch_job(job_id, status="polling")
        started_at = time.monotonic()
        last_state = ""
        last_logged_at = -999.0

        while True:
            elapsed = time.monotonic() - started_at
            if elapsed > timeout_s:
                raise RuntimeError(f"{label} đã hết thời gian chờ sau {timeout_s} giây.")

            status = await client.poll_video(video_job.media_name)
            remote_state = getattr(status, "status", "")
            state_message = self._describe_remote_status(remote_state)
            failure_detail = humanize_flow_error(self._video_status_failure_detail(status))

            should_log = remote_state != last_state or (elapsed - last_logged_at) >= max(15.0, poll_s * 3)
            if should_log:
                if getattr(status, "complete", False):
                    await self._set_job_progress(
                        job_id,
                        "saving_artifacts",
                        f"{label}: Flow đã hoàn tất render sau {int(elapsed)} giây. Em đang chuẩn bị lưu artifact.",
                        remote_status=remote_state,
                    )
                    await self.store.append_log(job_id, f"{label}: đã hoàn tất sau {int(elapsed)} giây.")
                elif getattr(status, "failed", False):
                    log_message = failure_detail or f"Flow báo thất bại với trạng thái {state_message}."
                    await self._set_job_progress(
                        job_id,
                        "polling",
                        f"{label}: {log_message}",
                        remote_status=remote_state,
                    )
                    await self.store.append_log(job_id, f"{label}: {log_message}")
                else:
                    await self._set_job_progress(
                        job_id,
                        "polling",
                        f"{label}: {state_message} ({int(elapsed)} giây).",
                        remote_status=remote_state,
                    )
                    await self.store.append_log(job_id, f"{label}: {state_message} ({int(elapsed)} giây).")
                last_logged_at = elapsed
                last_state = remote_state

            if getattr(status, "complete", False):
                await self._set_job_progress(
                    job_id,
                    "saving_artifacts",
                    f"{label}: Flow đã hoàn tất render. Em đang chuẩn bị lưu artifact.",
                    remote_status=remote_state,
                )
                return status

            if getattr(status, "failed", False):
                raise RuntimeError(failure_detail or f"{label} thất bại với trạng thái {state_message}.")

            await asyncio.sleep(poll_s)

    def _describe_remote_status(self, status: str) -> str:
        mapping = {
            "MEDIA_GENERATION_STATUS_PENDING": "đang chờ xử lý",
            "MEDIA_GENERATION_STATUS_RUNNING": "đang tạo nội dung",
            "MEDIA_GENERATION_STATUS_IN_PROGRESS": "đang xử lý",
            "MEDIA_GENERATION_STATUS_COMPLETE": "đã hoàn tất",
            "MEDIA_GENERATION_STATUS_SUCCESS": "đã hoàn tất",
            "MEDIA_GENERATION_STATUS_SUCCESSFUL": "đã hoàn tất",
            "MEDIA_GENERATION_STATUS_FAILED": "đã thất bại",
            "MEDIA_GENERATION_STATUS_REJECTED": "bị từ chối",
        }
        return mapping.get(status, status.replace("_", " ").lower() if status else "đang xử lý")
