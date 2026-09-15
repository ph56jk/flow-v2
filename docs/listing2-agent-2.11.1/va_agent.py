"""Vá listing2_vps_agent.py: thêm nguồn việc thứ hai là hàng đợi ERP browser-copy.

Chỉ cộng thêm. Mỗi mỏ neo phải xuất hiện đúng một lần, không thì dừng.
"""
import sys
from pathlib import Path

src_path, dst_path = Path(sys.argv[1]), Path(sys.argv[2])
text = src_path.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Mỏ neo xuất hiện {count} lần, cần đúng 1:\n{old[:200]}")
    text = text.replace(old, new, 1)


# E1. Nâng phiên bản để máy tự kéo bản mới ở lượt chạy sau.
replace_once('AGENT_VERSION = "2.10.99"\n', 'AGENT_VERSION = "2.11.1"\n')

# E2. Hàm phụ cho việc ERP, đặt ngay trước required_extension_roles.
ERP_HELPERS = r'''
# ---------------------------------------------------------------------------
# Nguồn việc thứ hai: hàng đợi ERP browser-copy.
#
# ERP xếp việc listing vào /api/extension/etsy-browser-copy/*. Trước bản 2.11.0
# không máy nào rút hàng đợi này, nên việc ERP nằm im. Agent giờ rút nó khi
# lượt này không có thẻ Trello thật; việc đồng bộ cột nền không tính là thẻ.
# Extension Etsy không đổi: nó vẫn chỉ nhận lệnh create_draft từ bridge cục
# bộ, không biết việc đến từ Trello hay ERP.
# ---------------------------------------------------------------------------
ERP_BROWSER_COPY_NEXT = "api/extension/etsy-browser-copy/next"
ERP_BROWSER_COPY_REPORT = "api/extension/etsy-browser-copy/report"
ERP_BROWSER_COPY_QUEUE = "api/etsy/browser-copy/queue"
ERP_MAX_IMAGES = 20


def erp_queue_enabled() -> bool:
    """Tắt riêng từng máy bằng LISTING2_ERP_QUEUE=0 mà không cần sửa code."""

    return str(os.getenv("LISTING2_ERP_QUEUE", "1")).strip().lower() not in {"0", "false", "no", "off"}


def erp_accept_unpinned() -> bool:
    """Việc không ghim máy thì không biết thuộc shop nào: mặc định không nhận."""

    return str(os.getenv("LISTING2_ERP_ACCEPT_UNPINNED", "")).strip().lower() in {"1", "true", "yes", "on"}


def erp_worker_id(config: "AgentConfig") -> str:
    return f"listing2-agent-{config.machine_id}"


def erp_norm_machine(value: Any) -> str:
    """Chuẩn hoá mã máy y như controller, để so việc ghim máy cho đúng."""

    text = str(value or "").strip().lower()
    text = "".join(ch if (ch.isalnum() or ch in "_-") else "-" for ch in text).strip("-")
    return "" if text in {"", "auto", "any", "default"} else text


def erp_accounts_to_ask(snapshot: dict[str, Any], machine_id: str) -> list[str]:
    """Tài khoản cần hỏi hàng đợi, lấy từ chính các việc đang ghim vào máy này.

    Controller chỉ trao việc khi accountId khớp từng chữ. Thẻ ERP thật mang
    nhãn tài khoản (acc32), nên hỏi bằng tài khoản rỗng thì không bao giờ nhận
    được thẻ nào. Không có việc nào ghim vào máy thì trả rỗng: không hỏi gì,
    để không nhận nhầm việc của máy khác hay việc không ghim máy.
    """

    me = erp_norm_machine(machine_id)
    accept_unpinned = erp_accept_unpinned()
    accounts: list[str] = []
    for task in snapshot.get("tasks") or []:
        if not isinstance(task, dict) or str(task.get("status") or "") != "queued":
            continue
        pinned = erp_norm_machine(task.get("machine_id"))
        if pinned != me and not (accept_unpinned and not pinned):
            continue
        # Controller đã chuẩn hoá account_id trong ảnh chụp hàng đợi.
        account = str(task.get("account_id") or "").strip()
        if account not in accounts:
            accounts.append(account)
    return accounts


def erp_template_listing_url(raw: dict[str, Any]) -> str:
    template_url = str(raw.get("templateListingUrl") or "").strip()
    if template_url:
        return template_url
    template_id = listing_id_from_value(str(raw.get("templateListingId") or ""))
    if template_id:
        return f"https://www.etsy.com/listing/{template_id}"
    return ""


def erp_template_source_sku(raw: dict[str, Any]) -> str:
    """SKU của listing mẫu. Rỗng nghĩa là ERP không chỉ được mẫu nào."""

    source_sku = str(raw.get("templateSourceSku") or "").strip()
    if source_sku:
        return source_sku
    for key in ("templateSearchQueries", "templateSearchTerms"):
        values = raw.get(key)
        if isinstance(values, list):
            for value in values:
                if str(value or "").strip():
                    return str(value).strip()
    return str(raw.get("templateSearchQuery") or "").strip()


def erp_image_urls(raw: dict[str, Any], backend: str) -> list[dict[str, str]]:
    """Link ảnh tuyệt đối theo đúng thứ tự rank ERP đã xếp.

    Controller trả link tương đối /files/downloads/..., nên phải ghép với
    địa chỉ backend mà agent đang dùng.
    """

    base = str(backend or "").rstrip("/")
    images = raw.get("images") if isinstance(raw.get("images"), list) else []
    items: list[dict[str, str]] = []
    for index, image in enumerate(images):
        if not isinstance(image, dict):
            continue
        link = str(image.get("download_url") or image.get("url") or "").strip()
        if not link:
            continue
        items.append(
            {
                "url": link if link.startswith(("http://", "https://")) else f"{base}/{link.lstrip('/')}",
                "name": str(image.get("file_name") or image.get("erp_name") or f"erp-{index + 1:02d}.jpg").strip(),
                "mime": str(image.get("mime_type") or "").strip(),
            }
        )
    if not items:
        for index, link in enumerate(raw.get("imageUrls") or []):
            link = str(link or "").strip()
            if link:
                items.append(
                    {
                        "url": link if link.startswith(("http://", "https://")) else f"{base}/{link.lstrip('/')}",
                        "name": f"erp-{index + 1:02d}.jpg",
                        "mime": "",
                    }
                )
    limit = int(raw.get("maxUploadImages") or 10)
    return items[: max(1, min(limit, ERP_MAX_IMAGES))]


def download_erp_images(
    raw: dict[str, Any],
    backend: str,
    task_root: Path,
) -> list[dict[str, str]]:
    """Tải ảnh ERP về thư mục của task để bridge phát cho extension Etsy."""

    task_root.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": f"Listing2Agent/{AGENT_VERSION}"}
    token = str(os.getenv("LISTING2_AGENT_TOKEN", "")).strip()
    if token:
        headers["X-Listing2-Agent-Token"] = token
    files: list[dict[str, str]] = []
    for index, item in enumerate(erp_image_urls(raw, backend), start=1):
        suffix = Path(urllib.parse.urlparse(item["url"]).path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            suffix = ".jpg"
        target = (task_root / f"erp-{index:02d}{suffix}").resolve()
        target.relative_to(task_root.resolve())
        request = urllib.request.Request(item["url"], headers=headers)
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read()
            mime = str(response.headers.get("Content-Type") or item["mime"] or "").split(";", 1)[0].strip().lower()
        if not data:
            raise AgentError(f"Ảnh ERP số {index} rỗng: {item['name']}")
        if mime and not mime.startswith("image/"):
            raise AgentError(f"Link ảnh ERP số {index} không trả về ảnh ({mime}).")
        target.write_bytes(data)
        files.append(
            {
                "path": str(target),
                "name": Path(item["name"]).name or target.name,
                "mime": mime or mimetypes.guess_type(target.name)[0] or "image/jpeg",
            }
        )
    if not files:
        raise AgentError("Việc ERP không có ảnh nào để đăng lên Etsy.")
    return files


def erp_agent_task(
    config: "AgentConfig",
    erp_task: dict[str, Any],
    files: list[dict[str, str]],
) -> dict[str, Any]:
    """Bọc việc ERP thành đúng hình task mà ExtensionBridge đang chạy."""

    raw = erp_task.get("payload") if isinstance(erp_task.get("payload"), dict) else {}
    sku = str(raw.get("sku") or erp_task.get("sku") or "").strip()
    if not sku:
        raise AgentError("Việc ERP thiếu SKU; không tạo Draft.")
    template_url = erp_template_listing_url(raw)
    source_sku = erp_template_source_sku(raw)
    if not listing_id_from_value(template_url) and not source_sku:
        raise AgentError(
            "Việc ERP không chỉ được listing mẫu (không có templateListingId, "
            "templateSourceSku hay từ khoá tìm mẫu); không tạo Draft."
        )
    payload: dict[str, Any] = {
        "erp_browser_copy": True,
        "erp_job_id": str(erp_task.get("job_id") or raw.get("jobId") or "").strip(),
        "erp_card_id": str(erp_task.get("card_id") or raw.get("cardId") or "").strip(),
        "erp_card_url": str(erp_task.get("card_url") or raw.get("cardUrl") or "").strip(),
        "erp_sku": sku,
        "erp_files": files,
        "trello_profile": config.trello_email,
        "etsy_profile": config.etsy_email,
        "template_listing_url": template_url,
        "template_source_sku": source_sku,
        "dry_run_only": bool(raw.get("dryRun")),
        "move_to_done": False,
    }
    return {
        "id": str(erp_task.get("id") or "").strip(),
        "attempts": max(1, int(erp_task.get("attempts") or 1)),
        "payload": payload,
    }


'''
replace_once(
    "\ndef required_extension_roles(payload: dict[str, Any]) -> set[str]:\n",
    ERP_HELPERS + "def required_extension_roles(payload: dict[str, Any]) -> set[str]:\n",
)

# E3. Việc ERP chỉ cần extension Etsy.
replace_once(
    "def required_extension_roles(payload: dict[str, Any]) -> set[str]:\n    if bool(\n",
    "def required_extension_roles(payload: dict[str, Any]) -> set[str]:\n"
    "    if bool(payload.get(\"erp_browser_copy\")):\n"
    "        # Việc ERP không đọc Trello: chỉ chờ extension Etsy.\n"
    "        return {\"etsy\"}\n"
    "    if bool(\n",
)

# E4. Bridge nhận sẵn ảnh và trường listing cho việc ERP.
replace_once(
    "        self._server: ThreadingHTTPServer | None = None\n"
    "        self._thread: threading.Thread | None = None\n"
    "\n"
    "    def _command_id(",
    "        self._server: ThreadingHTTPServer | None = None\n"
    "        self._thread: threading.Thread | None = None\n"
    "        self.erp_browser_copy = bool(self.payload.get(\"erp_browser_copy\"))\n"
    "        if self.erp_browser_copy:\n"
    "            self._adopt_erp_task()\n"
    "\n"
    "    def _adopt_erp_task(self) -> None:\n"
    "        \"\"\"Việc ERP đã có ảnh và SKU: bỏ bước đọc Trello, vào thẳng Etsy.\n"
    "\n"
    "        Nhánh create_draft trong poll() chạy khi self._trello có giá trị, nên\n"
    "        chỉ cần điền sẵn nó. Luồng Trello không đi qua hàm này.\n"
    "        \"\"\"\n"
    "\n"
    "        files: list[dict[str, Any]] = []\n"
    "        for item in self.payload.get(\"erp_files\") or []:\n"
    "            if not isinstance(item, dict):\n"
    "                continue\n"
    "            path = Path(str(item.get(\"path\") or \"\"))\n"
    "            if path.is_file() and path.stat().st_size > 0:\n"
    "                files.append(\n"
    "                    {\n"
    "                        \"path\": path,\n"
    "                        \"name\": str(item.get(\"name\") or path.name),\n"
    "                        \"mime\": str(item.get(\"mime\") or \"image/jpeg\"),\n"
    "                    }\n"
    "                )\n"
    "        if not files:\n"
    "            raise AgentError(\"Việc ERP không còn ảnh nào trên máy để đăng.\")\n"
    "        self._files = files\n"
    "        sku = str(self.payload.get(\"erp_sku\") or \"\").strip()\n"
    "        fields: dict[str, str] = {\"sku\": sku}\n"
    "        if self._template_source_sku:\n"
    "            fields[\"template_source_sku\"] = self._template_source_sku\n"
    "        self._trello = {\n"
    "            \"card_url\": str(self.payload.get(\"erp_card_url\") or \"\"),\n"
    "            \"title\": sku,\n"
    "            \"description\": \"\",\n"
    "            \"list_title\": \"\",\n"
    "            \"template_source_sku\": self._template_source_sku,\n"
    "            \"image_attachment_count\": len(files),\n"
    "            \"attachment_debug\": {\"source\": \"erp\"},\n"
    "            \"fields\": fields,\n"
    "        }\n"
    "        self._stage = \"waiting_extensions\"\n"
    "\n"
    "    def _command_id(",
)

# E5. Agent nhớ việc nào là việc ERP để báo về đúng chỗ.
replace_once(
    "        self.extension_bridge: ExtensionBridge | None = None\n"
    "        self.session_probes: dict[str, dict[str, Any]] = {}\n"
    "\n"
    "    def heartbeat(self) -> dict[str, Any]:\n",
    "        self.extension_bridge: ExtensionBridge | None = None\n"
    "        self.session_probes: dict[str, dict[str, Any]] = {}\n"
    "        self._erp_task_ids: set[str] = set()\n"
    "\n"
    "    def heartbeat(self) -> dict[str, Any]:\n",
)

# E6. progress(): hàng đợi ERP không có endpoint tiến độ, chỉ in ra log máy.
replace_once(
    "    def progress(self, task_id: str, phase: str, message: str) -> None:\n"
    "        response = http_json(\n",
    "    def progress(self, task_id: str, phase: str, message: str) -> None:\n"
    "        if task_id in self._erp_task_ids:\n"
    "            print(f\"[ERP {task_id}] {phase}: {message}\", flush=True)\n"
    "            return\n"
    "        response = http_json(\n",
)

# E7. report(): việc ERP báo về /api/extension/etsy-browser-copy/report.
replace_once(
    "    def report(self, task_id: str, status: str, message: str, *, result: dict[str, Any] | None = None, error: str = \"\") -> None:\n"
    "        http_json(\n"
    "            self.config.endpoint(\"api/listing2/tasks/report\"),\n",
    "    def report(self, task_id: str, status: str, message: str, *, result: dict[str, Any] | None = None, error: str = \"\") -> None:\n"
    "        if task_id in self._erp_task_ids:\n"
    "            self.report_erp(task_id, status, message, result=result, error=error)\n"
    "            return\n"
    "        http_json(\n"
    "            self.config.endpoint(\"api/listing2/tasks/report\"),\n",
)

# E8. Hàm rút + chạy + báo việc ERP, đặt ngay trước run_once.
ERP_AGENT_METHODS = r'''    def report_erp(
        self,
        task_id: str,
        status: str,
        message: str,
        *,
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        # Hàng đợi ERP chỉ hiểu completed/failed. blocked_login, stopped đều
        # là "chưa tạo được Draft" nên báo failed kèm lý do gốc.
        ok = status == "completed"
        body = dict(result or {})
        body["agent_status"] = status
        body["agent_version"] = AGENT_VERSION
        body["machine_id"] = self.config.machine_id
        body.setdefault("message", message if ok else (error or message))
        if error:
            body.setdefault("error", error)
        http_json(
            self.config.endpoint(ERP_BROWSER_COPY_REPORT),
            method="POST",
            payload={
                "taskId": task_id,
                "status": "completed" if ok else "failed",
                "workerId": erp_worker_id(self.config),
                "result": body,
            },
        )
        print(f"[ERP {task_id}] báo về ERP: {'completed' if ok else 'failed'} — {body['message']}", flush=True)

    def next_erp_task(self) -> dict[str, Any] | None:
        """Rút một việc ERP ghim vào máy này. Lỗi ở đây không bao giờ được làm hỏng luồng Trello."""

        if not erp_queue_enabled():
            return None
        try:
            snapshot = http_json(
                self.config.endpoint(ERP_BROWSER_COPY_QUEUE)
                + "?machine_id="
                + urllib.parse.quote(self.config.machine_id, safe=""),
                attempts=1,
            )
        except Exception as exc:
            print(f"Không đọc được hàng đợi ERP: {type(exc).__name__}: {exc}")
            return None
        accounts = erp_accounts_to_ask(snapshot, self.config.machine_id)
        if not accounts:
            return None
        for account in accounts:
            try:
                response = http_json(
                    self.config.endpoint(ERP_BROWSER_COPY_NEXT),
                    method="POST",
                    payload={
                        "workerId": erp_worker_id(self.config),
                        "machineId": self.config.machine_id,
                        "machineLabel": self.config.machine_label,
                        "accountId": account,
                        "workerVersion": EXTENSION_VERSION,
                        "extensionVersion": EXTENSION_VERSION,
                        "trigger": f"listing2-agent-{AGENT_VERSION}",
                    },
                    attempts=1,
                )
            except Exception as exc:
                print(f"Không hỏi được hàng đợi ERP: {type(exc).__name__}: {exc}")
                return None
            task = response.get("task")
            if isinstance(task, dict) and str(task.get("id") or "").strip():
                return task
            reason = str(response.get("reason") or "").strip()
            if reason:
                print(f"Hàng đợi ERP chưa giao việc cho tài khoản {account or 'mặc định'}: {reason}")
        return None

    def process_erp(self, erp_task: dict[str, Any]) -> None:
        task_id = str(erp_task.get("id") or "").strip()
        self._erp_task_ids.add(task_id)
        print(f"[ERP {task_id}] nhận việc SKU {erp_task.get('sku') or '?'}", flush=True)
        if not str(erp_task.get("machine_id") or "").strip() and not erp_accept_unpinned():
            # Mỗi máy là một shop Etsy riêng. Việc không ghim máy mà vẫn chạy
            # thì bộ ảnh rơi vào shop của máy nào rảnh trước.
            self.report(
                task_id,
                "failed",
                "Chưa mở Etsy: việc ERP không ghim máy nên không biết đăng lên shop nào.",
                error=(
                    f"Việc {task_id} không có machine_id. Ghi `machine:`/`acc:` trên thẻ ERP "
                    "rồi xếp lại; hoặc đặt LISTING2_ERP_ACCEPT_UNPINNED=1 trên máy được phép nhận."
                ),
            )
            return
        task_root = Path.home() / "Downloads" / "Listing2" / task_id
        try:
            raw = erp_task.get("payload") if isinstance(erp_task.get("payload"), dict) else {}
            files = download_erp_images(raw, self.config.backend, task_root)
            agent_task = erp_agent_task(self.config, erp_task, files)
        except Exception as exc:
            self.report(
                task_id,
                "failed",
                "Chưa mở Etsy: không chuẩn bị được việc ERP.",
                error=f"{type(exc).__name__}: {exc}",
            )
            shutil.rmtree(task_root, ignore_errors=True)
            return
        self.process(agent_task)

'''
replace_once(
    "    def run_once(self, *, open_profiles_only: bool = False) -> int:\n",
    ERP_AGENT_METHODS + "    def run_once(self, *, open_profiles_only: bool = False) -> int:\n",
)

# E9. run_once(): Trello trống thì hỏi hàng đợi ERP.
replace_once(
    "        task = response.get(\"task\")\n"
    "        if not isinstance(task, dict):\n"
    "            print(\"Không có task Listing 2 cho máy này.\")\n"
    "            return 0\n"
    "        self.process(task)\n"
    "        return 0\n",
    "        task = response.get(\"task\")\n"
    "        if isinstance(task, dict):\n"
    "            self.process(task)\n"
    "            payload = task.get(\"payload\") if isinstance(task.get(\"payload\"), dict) else {}\n"
    "            if not bool(payload.get(\"background_sync\")):\n"
    "                return 0\n"
    "            # Việc đồng bộ cột Trello là việc nền, controller giao gần như mỗi\n"
    "            # phút. Dừng ở đây thì hàng đợi ERP không bao giờ tới lượt.\n"
    "        # Không có thẻ Trello thật: rút việc ERP. Thẻ Trello thật luôn được ưu tiên.\n"
    "        erp_task = self.next_erp_task()\n"
    "        if erp_task is None:\n"
    "            if not isinstance(task, dict):\n"
    "                print(\"Không có task Listing 2 cho máy này.\")\n"
    "            return 0\n"
    "        self.process_erp(erp_task)\n"
    "        return 0\n",
)

with open(dst_path, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(text)
print(f"OK: {dst_path} ({len(text)} ký tự)")
