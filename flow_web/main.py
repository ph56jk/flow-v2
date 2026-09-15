from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .paths import DOWNLOADS_DIR, PROJECT_ROOT, STATIC_DIR, UPLOADS_DIR, ensure_app_dirs
from .schemas import (
    AccountBookUpdateRequest,
    ArtifactOpenRequest,
    CleanupRequest,
    ConfigUpdateRequest,
    CreateJobRequest,
    DashboardApprovalRequest,
    DashboardArtifactAddRequest,
    DownloadRequest,
    ERPConfigUpdateRequest,
    ERPIdeaBatchRequest,
    ERPReviewDeleteRequest,
    FlowOperatorRequest,
    IntegrationConfigUpdateRequest,
    PipelineAdvanceRequest,
    PromptBatchRequest,
    PromptCreateRequest,
    ReplayCleanupRequest,
    ResetReadyERPRequest,
    SkuBookUpdateRequest,
    SkuSyncRequest,
    StoryboardPlanRequest,
    TaskMetaEditRequest,
    UserAssistantRequest,
)
from .service import FlowWebService
from .store import StateStore


ENV_FILE = Path(
    os.path.expandvars(
        os.path.expanduser(os.environ.get("FLOW_ENV_FILE", "").strip())
    )
) if os.environ.get("FLOW_ENV_FILE", "").strip() else PROJECT_ROOT / ".env.local"
if not ENV_FILE.is_absolute():
    ENV_FILE = (PROJECT_ROOT / ENV_FILE).resolve()


def _strip_env_quotes(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text


def load_local_env() -> None:
    if not ENV_FILE.exists():
        return
    try:
        raw_text = ENV_FILE.read_text(encoding="utf-8")
    except OSError:
        return
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _strip_env_quotes(value)


def configure_logging() -> None:
    """Cho log của app đi ra cùng chỗ với log uvicorn.

    Uvicorn chỉ gắn handler cho logger của chính nó, nên khi máy trung tâm
    chạy 24/7 không ai ngồi trước màn hình thì mọi dòng INFO của agent bot và
    các watcher rơi vào hư không. Gắn handler cho root logger một lần lúc
    khởi động để file log ghi lại được bot đã quét và chạy thẻ nào.
    """

    level_name = os.environ.get("FLOW_LOG_LEVEL", "INFO").strip().upper() or "INFO"
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    if not any(getattr(handler, "_flow_web_handler", False) for handler in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        handler._flow_web_handler = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    logging.getLogger("flow_web").setLevel(level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_app_dirs()
    load_local_env()
    configure_logging()
    store = StateStore()
    app.state.flow_service = FlowWebService(store)
    sync_task = asyncio.create_task(app.state.flow_service.ensure_media_skill_library())
    # Reviewers answer on the ERP card, so the decisions have to be fetched
    # here instead of waiting for somebody to open this app.
    erp_review_task = asyncio.create_task(app.state.flow_service.watch_erp_reviews())
    # Adding a child card under the Idea card is the only instruction needed:
    # this picks up the ones that still have no images and runs them.
    erp_idea_task = asyncio.create_task(app.state.flow_service.watch_erp_idea_children())
    # Attaching the agent bot to a card on the ERP is the whole instruction:
    # this reads those cards, applies 👍/👎, and runs the ones that need work.
    # No token configured means the coroutine returns at once.
    agent_bot_task = asyncio.create_task(app.state.flow_service.watch_agent_bot())
    # Lần khởi động này vừa cắt ngang lượt nào thì xếp lại lượt ấy: đẩy code
    # hay máy tự khởi động lại không được làm cả lô nằm im chờ người.
    resume_task = asyncio.create_task(app.state.flow_service.resume_after_restart())
    try:
        yield
    finally:
        for task in (sync_task, erp_review_task, erp_idea_task, agent_bot_task, resume_task):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await app.state.flow_service.close()


app = FastAPI(
    title="Flow v2",
    version="0.1.0",
    lifespan=lifespan,
)

ensure_app_dirs()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/files/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")
app.mount("/files/downloads", StaticFiles(directory=DOWNLOADS_DIR), name="downloads")


def service(request: Request) -> FlowWebService:
    return request.app.state.flow_service


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(
        (STATIC_DIR / "index.html").read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/health")
async def health() -> Dict[str, str]:
    return {
        "status": "ok",
        "instance": os.environ.get("FLOW_WORKER_NAME", "primary").strip() or "primary",
    }


@app.get("/api/state")
async def get_state(request: Request) -> Dict[str, Any]:
    return service(request).get_state_payload()


@app.put("/api/config")
async def update_config(request: Request, payload: ConfigUpdateRequest) -> Dict[str, Any]:
    flow_service = service(request)
    config = await flow_service.update_config(payload)
    return {"config": config}


@app.put("/api/integrations/erp")
async def update_erp_config(request: Request, payload: ERPConfigUpdateRequest) -> Dict[str, Any]:
    return {"erp": await service(request).update_erp_config(payload)}


@app.post("/api/erp/ready/status")
async def ready_erp_status(request: Request, payload: ResetReadyERPRequest) -> Dict[str, Any]:
    return await service(request).ready_erp_status(payload)


@app.post("/api/erp/idea-batch")
async def enqueue_erp_idea_jobs(request: Request, payload: ERPIdeaBatchRequest) -> Dict[str, Any]:
    return await service(request).enqueue_erp_idea_jobs(payload)


@app.post("/api/erp/idea-batch/auto")
async def autorun_erp_idea_children(request: Request) -> Dict[str, Any]:
    """Run the watcher's pass now, against the configured Idea card."""
    return await service(request).autorun_erp_idea_children()


@app.post("/api/erp/idea-batch/repair")
async def repair_erp_idea_children(request: Request) -> Dict[str, Any]:
    """Đăng bù ảnh đã tạo và chạy bù ảnh còn thiếu cho thẻ Idea đang cấu hình."""
    return await service(request).repair_erp_idea_children()


@app.get("/api/erp/sku/book")
async def read_sku_book(request: Request) -> Dict[str, Any]:
    """Bảng sản phẩm → phần tên SKU mà app đang dùng."""
    return {"entries": service(request).load_sku_book(refresh=True).as_dict()}


@app.put("/api/erp/sku/book")
async def write_sku_book(request: Request, payload: SkuBookUpdateRequest) -> Dict[str, Any]:
    """Ghi bảng sản phẩm của app.  Sheet và biến môi trường vẫn chồng lên trên."""
    return {"entries": service(request).save_sku_book(payload.entries).as_dict()}


@app.get("/api/erp/account/book")
async def read_account_book(request: Request) -> Dict[str, Any]:
    """Sổ tay tài khoản listing mà app đang dùng."""
    return {"entries": service(request).load_account_book(refresh=True).as_dict()}


@app.put("/api/erp/account/book")
async def write_account_book(request: Request, payload: AccountBookUpdateRequest) -> Dict[str, Any]:
    """Ghi sổ tài khoản của app.  Sheet và biến môi trường vẫn chồng lên trên."""
    return {"entries": service(request).save_account_book(payload.entries).as_dict()}


@app.post("/api/erp/pipeline/advance")
async def advance_erp_pipeline(request: Request, payload: PipelineAdvanceRequest) -> Dict[str, Any]:
    """Đẩy một thẻ đi một bước trên bảng: điền mã nếu đang ở *Đang làm*, rồi chuyển cột."""
    task_id = (payload.task_id or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="Thiếu ERP Task ID của thẻ cần đẩy sang cột kế.")
    return await service(request).advance_erp_pipeline(task_id)


@app.post("/api/erp/task/meta-edit")
async def edit_erp_task_meta(request: Request, payload: TaskMetaEditRequest) -> Dict[str, Any]:
    """Ghi vài ô Thuộc tính lên một thẻ — đường mà con bot chạy rời gọi vào.

    Bot bản rời không cầm nổi API key của app, nên nó nhờ app ghi hộ.  Danh
    sách ô được phép sửa nằm trong ``service``; ở đây chỉ chặn thẻ trống.
    """
    task_id = (payload.task_id or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="Thiếu ERP Task ID của thẻ cần sửa thuộc tính.")
    edits = [(str(field), str(value)) for field, value in (payload.edits or [])]
    return await asyncio.to_thread(service(request).edit_task_meta, task_id, edits)


@app.post("/api/erp/review/delete-disliked")
async def delete_disliked_erp_review_image(
    request: Request,
    payload: ERPReviewDeleteRequest,
) -> Dict[str, Any]:
    """Let a remote agent ask the app to safely delete one review image.

    The app re-reads ERP and independently checks the marker, image attachment
    and current vote before it writes. A stale request receives ``deleted:
    false`` rather than turning an old bot snapshot into a deletion.
    """
    task_id = (payload.task_id or "").strip()
    comment_id = (payload.comment_id or "").strip()
    if not task_id or not comment_id:
        raise HTTPException(status_code=400, detail="Thiếu ERP Task ID hoặc comment ID cần kiểm tra để gỡ ảnh.")
    deleted = await asyncio.to_thread(
        service(request).delete_disliked_erp_review_image_for_agent,
        task_id,
        comment_id,
    )
    return {"deleted": deleted}


def _sku_task_id(payload: SkuSyncRequest) -> str:
    """Thẻ gốc là bắt buộc.  Thiếu nó là lỗi của người gọi, không phải lỗi máy chủ."""
    task_id = (payload.task_id or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="Thiếu ERP Task ID của thẻ gốc để đánh số SKU.")
    return task_id


@app.post("/api/erp/sku/plan")
async def plan_erp_skus(request: Request, payload: SkuSyncRequest) -> Dict[str, Any]:
    """Xem trước mã của từng thẻ dưới một thẻ gốc, không ghi gì lên ERP."""
    return await service(request).sync_erp_skus(
        _sku_task_id(payload), dry_run=True, renumber=payload.renumber
    )


@app.post("/api/erp/sku/sync")
async def sync_erp_skus(request: Request, payload: SkuSyncRequest) -> Dict[str, Any]:
    """Cấp mã cho mọi thẻ còn trống dưới một thẻ gốc."""
    return await service(request).sync_erp_skus(
        _sku_task_id(payload), dry_run=payload.dry_run, renumber=payload.renumber
    )


@app.post("/api/agent-bot/run")
async def run_agent_bot_once(request: Request) -> Dict[str, Any]:
    """Run one agent-bot scan now instead of waiting for the timer."""
    return await service(request).run_agent_bot_once()


@app.get("/api/erp/tasks/{task_id}/attachments/{attachment_id}/preview")
async def erp_attachment_preview(request: Request, task_id: str, attachment_id: str) -> Response:
    payload = await service(request).erp_attachment_preview(task_id, attachment_id)
    return Response(
        content=payload["content"],
        media_type=payload["media_type"],
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.put("/api/integrations/settings")
async def update_integration_config(request: Request, payload: IntegrationConfigUpdateRequest) -> Dict[str, Any]:
    return {"integrations": await service(request).update_integration_config(payload)}


@app.post("/api/jobs/{job_id}/artifacts/{artifact_index}/approval")
async def apply_dashboard_approval(
    request: Request,
    job_id: str,
    artifact_index: int,
    payload: DashboardApprovalRequest,
) -> Dict[str, Any]:
    approval = await service(request).apply_dashboard_approval(
        job_id,
        artifact_index,
        payload.status,
        payload.reviewer,
    )
    return {"approval": approval}


@app.post("/api/jobs/{job_id}/approvals/reopen")
async def reopen_watermark_rejections(request: Request, job_id: str) -> Dict[str, Any]:
    return await service(request).reopen_watermark_rejections(job_id)


async def _erp_review_indices(request: Request) -> Any:
    """Đọc ``indices`` (tuỳ chọn) từ body của lệnh đăng duyệt ERP.

    A6.3. Không có body, hoặc ``indices`` rỗng, giữ nguyên nghĩa cũ: **đăng
    bù mọi ảnh còn thiếu trên thẻ**. Khi đang sửa đúng một ảnh thì phải gửi
    ``{"indices": [i]}`` — gọi trống là một lệnh khác, và đã từng biến một
    thẻ 12 ảnh thành 17.

    "Không có body" và "có body mà đọc không ra" là **hai chuyện khác nhau**.
    Trước đây cả hai cùng trả ``None``, tức là cùng nghĩa "đăng tất cả": một
    request bị cắt giữa đường (``{"indices": [1]``) không nổ, không báo, mà
    lặng lẽ thành lệnh đăng bù toàn bộ — đúng hình dạng của sự cố 12 → 17 ảnh
    mà A6 sinh ra để chặn. Body rỗng vẫn là "đăng tất cả"; body có mà hỏng
    thì trả 400 và không đăng gì.
    """
    raw_body = await request.body()
    if not raw_body.strip():
        return None
    try:
        payload = json.loads(raw_body)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Body của lệnh đăng duyệt không phải JSON đọc được: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail="Body của lệnh đăng duyệt phải là một object JSON.",
        )
    raw = payload.get("indices")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="indices phải là danh sách chỉ số ảnh.")
    return raw or None


@app.post("/api/jobs/{job_id}/erp-review/publish")
async def publish_erp_review(request: Request, job_id: str) -> Dict[str, Any]:
    indices = await _erp_review_indices(request)
    return await service(request).publish_erp_review(job_id, indices=indices)


@app.post("/api/jobs/{job_id}/erp-review/sync")
async def sync_erp_review(request: Request, job_id: str) -> Dict[str, Any]:
    return await service(request).sync_erp_review(job_id)


@app.post("/api/jobs/{job_id}/watermark/retry")
async def retry_job_watermarks(request: Request, job_id: str) -> Dict[str, Any]:
    return await service(request).retry_job_watermarks(job_id)


@app.post("/api/jobs/{job_id}/artifacts")
async def add_dashboard_artifact(
    request: Request,
    job_id: str,
    payload: DashboardArtifactAddRequest,
) -> Dict[str, Any]:
    artifact = await service(request).add_dashboard_artifact(
        job_id,
        payload.url,
        payload.label,
        payload.reviewer,
    )
    return {"artifact": artifact}


@app.post("/api/prompt-sources/preview")
async def preview_prompt_source(
    request: Request,
    source_url: str = Form(""),
    text: str = Form(""),
    file: UploadFile | None = File(None),
) -> Dict[str, Any]:
    return await service(request).preview_prompt_source(file=file, text=text, source_url=source_url)


@app.post("/api/auth/login")
async def login(request: Request) -> Dict[str, Any]:
    flow_service = service(request)
    job = await flow_service.enqueue_login()
    return {"job": job}


@app.post("/api/auth/logout")
async def logout(request: Request) -> Dict[str, Any]:
    return await service(request).logout_flow()


@app.post("/api/flow/open-login")
async def open_login_surface(request: Request) -> Dict[str, Any]:
    return await service(request).open_flow_login_surface()


@app.post("/api/flow/open-project")
async def open_project_surface(request: Request) -> Dict[str, Any]:
    return await service(request).open_flow_project_surface()


@app.get("/api/credits")
async def credits(request: Request) -> Dict[str, Any]:
    return await service(request).get_credits()


@app.get("/api/workflows")
async def workflows(request: Request) -> Dict[str, Any]:
    return {"items": await service(request).get_workflows()}


@app.get("/api/flow/project-debug")
async def flow_project_debug(request: Request) -> Dict[str, Any]:
    return await service(request).get_project_debug()


@app.get("/api/flow/agent-ui-debug")
async def flow_agent_ui_debug(request: Request, probe: str = "", prefill: int = 0, variant: str = "") -> Dict[str, Any]:
    return await service(request).get_flow_agent_ui_debug(probe, prefill, variant)


@app.get("/api/models")
async def models(request: Request) -> Dict[str, Any]:
    return await service(request).get_model_config()


@app.post("/api/uploads")
async def upload_file(request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
    return await service(request).save_upload(file)


@app.post("/api/jobs")
async def create_job(request: Request, payload: CreateJobRequest) -> Dict[str, Any]:
    job = await service(request).enqueue_job(payload)
    return {"job": job}


@app.post("/api/jobs/batch")
async def create_prompt_batch(request: Request, payload: PromptBatchRequest) -> Dict[str, Any]:
    job = await service(request).enqueue_prompt_batch(payload)
    return {"job": job}


@app.get("/api/gemini/usage")
async def gemini_usage(request: Request) -> Dict[str, Any]:
    return service(request).get_gemini_usage()


@app.post("/api/jobs/{job_id}/retry-erp-upload")
async def retry_erp_upload(request: Request, job_id: str) -> Dict[str, Any]:
    return await service(request).retry_erp_upload(job_id)


@app.post("/api/jobs/{job_id}/stop")
async def stop_job(request: Request, job_id: str) -> Dict[str, Any]:
    job = await service(request).request_stop_job(job_id)
    return {"job": job}


@app.get("/api/skills")
async def list_skills(request: Request) -> Dict[str, Any]:
    return {"items": service(request).get_state()["skills"]}


@app.post("/api/skills/sync-media")
async def sync_media_skills(request: Request) -> Dict[str, Any]:
    return await service(request).sync_media_skills()


@app.post("/api/prompt-ai/generate")
async def generate_prompt_ai(request: Request, payload: PromptCreateRequest) -> Dict[str, Any]:
    return await service(request).generate_prompt_draft(payload)


@app.post("/api/assistant/help")
async def assistant_help(request: Request, payload: UserAssistantRequest) -> Dict[str, Any]:
    return await service(request).answer_user_assistant(payload)


@app.post("/api/flow-ai/plan")
async def plan_flow_ai_operator(request: Request, payload: FlowOperatorRequest) -> Dict[str, Any]:
    return await service(request).plan_flow_operator(payload)


@app.post("/api/storyboard/plan")
async def plan_storyboard(request: Request, payload: StoryboardPlanRequest) -> Dict[str, Any]:
    return await service(request).plan_storyboard(payload)


@app.post("/api/jobs/{job_id}/download")
async def download_job_output(request: Request, job_id: str, payload: DownloadRequest) -> Dict[str, Any]:
    return await service(request).download_artifact(job_id, payload)


@app.post("/api/jobs/{job_id}/artifacts/open")
async def open_job_artifact(request: Request, job_id: str, payload: ArtifactOpenRequest) -> Dict[str, Any]:
    return await service(request).open_artifact(job_id, payload)


@app.get("/api/jobs/{job_id}/artifacts/{artifact_index}/file")
async def open_job_artifact_file(request: Request, job_id: str, artifact_index: int) -> FileResponse:
    return FileResponse(service(request).artifact_file_path(job_id, artifact_index))


@app.post("/api/replay-pack/cleanup")
async def cleanup_replay_pack(request: Request, payload: ReplayCleanupRequest) -> Dict[str, Any]:
    return await service(request).cleanup_replay_pack(payload)


@app.post("/api/cleanup")
async def cleanup_scope(request: Request, payload: CleanupRequest) -> Dict[str, Any]:
    return await service(request).cleanup_scope(payload)


@app.get("/api/jobs")
async def list_jobs(request: Request) -> Dict[str, Any]:
    return {"items": service(request).get_state()["jobs"]}


@app.get("/api/jobs/{job_id}")
async def get_job(request: Request, job_id: str) -> Dict[str, Any]:
    job = service(request).store.get_job(job_id)
    if job is None:
        return {"item": None}
    return {"item": job}


@app.get("/download/{file_name}")
async def download_file(file_name: str) -> FileResponse:
    target = (DOWNLOADS_DIR / file_name).resolve()
    if not str(target).startswith(str(DOWNLOADS_DIR.resolve())) or not target.exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy tệp.")
    return FileResponse(target)
