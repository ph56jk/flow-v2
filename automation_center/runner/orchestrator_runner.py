#!/usr/bin/env python3
"""Agent điều phối — runner sửa code trên máy trung tâm.

Nó nhận yêu cầu từ Automation Center, hỏi model cách sửa, ghi file, chạy
test, rồi báo diff ngược lại để người có quyền duyệt.  Máy cá nhân không tham
gia bước nào.

Model được hỏi qua một trong ba đường: HTTP tới OpenAI bằng ``OPENAI_API_KEY``,
Claude CLI, hoặc Codex CLI — hai CLI đăng nhập sẵn trên máy này.  Khi không có
khoá, ``auto`` thử Claude trước rồi mới tới Codex; cả hai đường CLI đều bỏ được
việc phải cất một khoá API trên máy trung tâm.

QUYẾT ĐỊNH CÓ CHỦ Ý, 2026-09-01: hai đường CLI chạy với CÔNG CỤ THẬT — Bash,
đọc/ghi file, mạng, MCP đã cấu hình sẵn — y như một phiên Claude Code hay Codex
bình thường, không còn là "đường truyền chữ" như thiết kế ban đầu của module
này (xem lịch sử git nếu cần đối chiếu bản cũ).  Đây là yêu cầu trực tiếp của
người vận hành, cân nhắc rủi ro rồi vẫn chọn chạy thẳng trên máy trung tâm này
— nơi giữ secret thật (``AUTOMATION_RUNNER_SECRET``, ``ERP_BOT_TOKEN``/
``ERP_API_KEY``+``ERP_API_SECRET``, ``CF_ACCESS_CLIENT_ID``/
``CF_ACCESS_CLIENT_SECRET``) — thay vì cô lập ở một máy/VM riêng không secret
thật.  Ba điều cần nhớ khi đọc code phía dưới:

1.  Một model có Bash thật CÓ THỂ đọc bất kỳ file nào tài khoản hệ điều hành
    đọc được (kể cả ``orchestrator.env`` cạnh đó) và gửi ra ngoài qua mạng thật
    của nó.  ``subprocess_env()`` lọc bớt các biến môi trường bí mật khỏi tiến
    trình CLI — model không CẦN chúng để làm việc — nhưng đó chỉ là giảm bớt
    một đường lộ thừa, không phải một sandbox: file trên đĩa vẫn đọc được nếu
    model chủ động đi tìm.
2.  Lớp chặn còn nguyên và vẫn có tác dụng: PROTECTED_GLOBS + phạm vi
    (``allow_globs``) được soi lại SAU khi model xong việc, qua
    ``validate_touched_paths`` — không còn soi TRƯỚC khi ghi như bản cũ (không
    còn "trước khi ghi" nào để soi, vì model tự ghi bằng công cụ của nó), nhưng
    một thay đổi phạm vi sai hay đụng file bảo vệ vẫn bị từ chối trước khi tới
    tay người duyệt.  Nhánh ``agent/<id>`` vẫn cô lập mọi thay đổi tới lúc có
    quyết định duyệt.
3.  Cổng duyệt tay (bước 5-6 ở ``docs/architecture.md``) không còn là hàng rào
    *kỹ thuật* duy nhất nữa — một model có Bash có thể tự ``git push`` nếu nó
    muốn và nếu bản clone này có credential push.  Bản clone này được dựng qua
    git-bundle chính vì máy trung tâm không đăng nhập được GitHub, nên trong
    điều kiện bình thường không có credential push thật ở đây; đó là một sự
    trùng hợp về hạ tầng, không phải một chốt chặn được thiết kế.

Repo mà runner đụng vào là một bản clone riêng (``AGENT_REPO_DIR``), không
phải bản đang chạy dịch vụ.  Việc triển khai bản đã merge vẫn là bước tay.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):  # Windows mặc định cp1252; log có tiếng Việt.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


CENTER_URL = os.environ.get("AUTOMATION_CENTER_URL", "https://automation.havigroup.llc").rstrip("/")
RUNNER_KEY = os.environ.get("AUTOMATION_RUNNER_KEY", "orchestrator-runner").strip()
RUNNER_SECRET = os.environ.get("AUTOMATION_RUNNER_SECRET", "").strip()
RUNNER_LABEL = os.environ.get("AUTOMATION_RUNNER_LABEL", "Agent điều phối (máy trung tâm)").strip()
POLL_SECONDS = max(1.0, float(os.environ.get("AUTOMATION_RUNNER_POLL_SECONDS", "3")))
ACCESS_CLIENT_ID = os.environ.get("CF_ACCESS_CLIENT_ID", "").strip()
ACCESS_CLIENT_SECRET = os.environ.get("CF_ACCESS_CLIENT_SECRET", "").strip()

REPO_DIR = Path(os.environ.get("AGENT_REPO_DIR", "")).expanduser()
BASE_BRANCH = os.environ.get("AGENT_BASE_BRANCH", "main").strip() or "main"
PUSH_AFTER_MERGE = os.environ.get("AGENT_PUSH_REMOTE", "").strip().lower() in {"1", "true", "yes"}
TEST_COMMAND = os.environ.get("AGENT_TEST_COMMAND", "").strip()
TEST_TIMEOUT = max(30, int(os.environ.get("AGENT_TEST_TIMEOUT_SECONDS", "900")))


def env_seconds(name: str, default: float, minimum: float) -> float:
    """Đọc một khoảng chờ từ môi trường, không để cấu hình lỗi làm runner chết."""
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


# Heartbeat không được chậm hơn 5 giây chỉ vì ai đó đặt nhầm biến môi trường.
# Nó chạy độc lập với lượt model/test có thể kéo dài nhiều phút.
HEARTBEAT_SECONDS = env_seconds("AGENT_HEARTBEAT_SECONDS", 15, 5)
# urllib có thể đang chờ Center tới 60 giây. Khi tắt runner chỉ chờ ngắn để
# nhịp đang xong tự dọn; không được join vô hạn rồi treo cả tiến trình.
HEARTBEAT_JOIN_SECONDS = 1
# Trần độ dài diff gửi lên Center.  Phải khớp trần bên Worker: bên đó cắt lần
# nữa, và nếu bên đó cắt trước thì cờ "đã cắt" runner gửi lên là cờ sai.
DIFF_LIMIT = 60000

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5").strip()
# Ngân sách này ôm trọn một lượt model đọc, nghĩ và sửa, không chỉ một HTTP
# request; test có AGENT_TEST_TIMEOUT_SECONDS riêng nên không dùng chung. Mốc
# 300s từng làm 140b4f63 hết giờ ngày 02/09/2026, trong khi lượt duy nhất qua
# được khi đó chỉ là ghi file với nội dung cho sẵn, nên giữ mặc định 1800s.
OPENAI_TIMEOUT = max(30, int(os.environ.get("OPENAI_TIMEOUT_SECONDS", "1800")))

# auto = có OPENAI_API_KEY thì đi HTTP, không thì Claude CLI, không nữa thì
# Codex CLI — cái nào đăng nhập sẵn trên máy này.  Đặt thẳng "claude",
# "codex" hay "openai" khi muốn hỏng to thay vì âm thầm đổi đường: một lượt
# đổi đường không ai hay là một lượt trả lời bằng model khác giá khác.
MODEL_PROVIDER = os.environ.get("AGENT_MODEL_PROVIDER", "auto").strip().lower() or "auto"
# Để trống thì tìm "codex" trong PATH.  Scheduled Task chạy kiểu S4U có PATH
# hẹp hơn PATH của phiên đăng nhập, nên trỏ tuyệt đối là chắc chắn hơn.
CODEX_BIN = os.environ.get("CODEX_BIN", "").strip()
# Để trống thì dùng model mặc định của codex.  Đừng nhét OPENAI_MODEL vào đây:
# tên model của API và tên model của codex không cùng một bộ.
CODEX_MODEL = os.environ.get("CODEX_MODEL", "").strip()

# Để trống thì tìm "claude" trong PATH.  Trên Windows npm cài ra một file
# ``claude.cmd`` chứ không phải .exe, và Scheduled Task kiểu S4U có PATH hẹp
# hơn phiên đăng nhập — trỏ tuyệt đối tới file .cmd ấy là chắc chắn hơn.
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "").strip()
# Tên model của Claude CLI ("haiku", "sonnet", "opus", hoặc tên đầy đủ).
# Mặc định "sonnet": lượt điều phối vừa phải đọc được cả file vừa phải trả lời
# nhanh, và người đang chờ trong khung chat đếm từng giây.
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "sonnet").strip()

RUNNER_VERSION = "1.0.0"
# Cloudflare WAF chặn User-Agent mặc định của urllib (lỗi 1010).
USER_AGENT = f"HaviGroupOrchestratorRunner/{RUNNER_VERSION} (+{RUNNER_KEY})"

# Bản sao cứng của danh sách bảo vệ phía Worker.  Trùng lặp là cố ý: nếu
# Center bị cấu hình sai, runner vẫn không đọc và không ghi những file này.
PROTECTED_GLOBS = (
    ".env", ".env.*", "*/.env", "*/.env.*", "*.env",
    "*.pem", "*.key", "*credentials*", "*secret*",
    ".gitignore", ".github/*",
    "wrangler.jsonc", "wrangler.toml", "*/wrangler.jsonc", "*/wrangler.toml",
    "automation_center/src/worker.js",
    "automation_center/migrations/*",
    "automation_center/runner/*",
    "automation_center/scripts/*",
    # Luật của chính hệ này: CLAUDE.md, định nghĩa ba vai agent, và lệnh chạy
    # test.  Xem chú thích dài hơn ở worker.js.
    "claude.md", "*/claude.md",
    ".claude/*",
    "scripts/*",
    # Hai cái tên còn lại của điều 3 CLAUDE.md.  Xem chú thích ở worker.js.
    ".dev.vars", ".dev.vars.*", "*/.dev.vars", "*/.dev.vars.*",
    "data/state.json*", "*/data/state.json*",
)

MAX_CONTEXT_FILES = 400
MAX_READ_BYTES = 120_000
MAX_WRITE_BYTES = 400_000
MAX_ROUNDS = 4

# ERP HaviGroup, đọc-only, do runner gọi hộ chứ model không bao giờ tự ra
# mạng (xem docstring đầu file).  Bot Token ưu tiên ("HVGToken ..."); để trống
# thì dùng cặp key/secret kiểu Frappe ("token key:secret").  Không đọc macOS
# Keychain như mcp/hvg_erp_mcp.py — máy trung tâm chạy Windows, Keychain đó là
# của máy cá nhân, không dùng lại được ở đây.
ERP_BASE_URL = os.environ.get("ERP_BASE_URL", "https://erp.havigroup.llc").rstrip("/")
ERP_GRAPHQL_PATH = os.environ.get(
    "ERP_GRAPHQL_PATH", "/api/method/hvg_workspace.graphql.endpoint.graphql").strip()
ERP_BOT_TOKEN = os.environ.get("ERP_BOT_TOKEN", "").strip()
ERP_API_KEY = os.environ.get("ERP_API_KEY", "").strip()
ERP_API_SECRET = os.environ.get("ERP_API_SECRET", "").strip()
ERP_TIMEOUT_SECONDS = max(5, int(os.environ.get("ERP_TIMEOUT_SECONDS", "30")))
# Giữ dưới hạn 60 request/phút của ERP, giống mcp/hvg_erp_mcp.py.
ERP_MIN_INTERVAL_SECONDS = 1.1

# Biến môi trường bí mật của chính runner — model không CẦN chúng để làm việc
# code, và đưa nguyên env cho một tiến trình có Bash thật là đưa luôn chìa
# khoá.  Xem mục 1 ở docstring đầu file: đây là giảm một đường lộ thừa, KHÔNG
# phải một sandbox — file trên đĩa vẫn đọc được nếu model chủ động đi tìm.
SECRET_ENV_NAMES = (
    "AUTOMATION_RUNNER_SECRET",
    "OPENAI_API_KEY",
    "ERP_BOT_TOKEN",
    "ERP_API_KEY",
    "ERP_API_SECRET",
    "CF_ACCESS_CLIENT_ID",
    "CF_ACCESS_CLIENT_SECRET",
)


def subprocess_env() -> dict[str, str]:
    """Env cho tiến trình con CLI: bản sao của os.environ, trừ các khoá bí mật.

    Dùng cho ``call_codex``/``call_claude`` — không dùng cho ``run_tests`` hay
    các lệnh ``git`` khác, những chỗ đó vẫn chạy trong tiến trình runner với
    quyền của chính nó, không phải của model.
    """
    env = dict(os.environ)
    for name in SECRET_ENV_NAMES:
        env.pop(name, None)
    return env


# ─── Nói chuyện với Automation Center ───────────────────────────────────────

def request_json(url: str, *, method: str = "GET", payload: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None, timeout: int = 60) -> dict[str, Any]:
    all_headers = {"accept": "application/json", "user-agent": USER_AGENT, **(headers or {})}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        all_headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            content_type = str(response.headers.get("content-type") or "")
            if "json" not in content_type.lower():
                final_url = response.geturl()
                if "cloudflareaccess.com" in final_url or "/cdn-cgi/access/" in final_url:
                    raise RuntimeError(
                        "Cloudflare Access chặn runner: thiếu hoặc sai CF_ACCESS_CLIENT_ID/"
                        "CF_ACCESS_CLIENT_SECRET, hoặc Service Token chưa gắn vào policy."
                    )
                raise RuntimeError(f"Phản hồi không phải JSON (content-type: {content_type or 'không rõ'}).")
            return json.loads(body or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:600]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Không kết nối được {url}: {exc.reason}") from exc


def center_request(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"x-automation-runner-secret": RUNNER_SECRET}
    if ACCESS_CLIENT_ID and ACCESS_CLIENT_SECRET:
        headers["CF-Access-Client-Id"] = ACCESS_CLIENT_ID
        headers["CF-Access-Client-Secret"] = ACCESS_CLIENT_SECRET
    return request_json(f"{CENTER_URL}{path}", method=method, payload=payload, headers=headers)


def heartbeat() -> None:
    center_request("/api/runner/heartbeat", method="POST", payload={
        "runner_key": RUNNER_KEY, "label": RUNNER_LABEL, "version": RUNNER_VERSION,
    })


def heartbeat_forever(stop_event: threading.Event) -> None:
    """Gửi heartbeat nền; lỗi Center không được làm chết lượt đang xử lý."""
    while not stop_event.is_set():
        try:
            heartbeat()
        except Exception as exc:
            print(f"Heartbeat lỗi: {exc}", file=sys.stderr)
        stop_event.wait(HEARTBEAT_SECONDS)


def start_heartbeat_thread(stop_event: threading.Event | None = None) -> threading.Thread:
    """Khởi động nhịp daemon sau khi runner đã qua mọi kiểm tra khởi động."""
    event = stop_event or threading.Event()
    thread = threading.Thread(
        target=heartbeat_forever,
        args=(event,),
        name="orchestrator-heartbeat",
        daemon=True,
    )
    thread.start()
    return thread


def report(request_id: str, status: str, **extra: Any) -> dict[str, Any]:
    return center_request(f"/api/runner/code/{urllib.parse.quote(request_id)}", method="POST", payload={
        "runner_key": RUNNER_KEY, "status": status, **extra,
    })


def is_cancelled(request_id: str) -> bool:
    state = center_request(
        f"/api/runner/code/{urllib.parse.quote(request_id)}?runner_key={urllib.parse.quote(RUNNER_KEY)}"
    )
    return str(state.get("request", {}).get("status") or "") == "cancelled"


# ─── Git ────────────────────────────────────────────────────────────────────

def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_DIR, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} hỏng: {(result.stderr or result.stdout).strip()[:600]}")
    return result.stdout


def repo_prefix() -> str:
    """Chỗ REPO_DIR nằm, tính từ gốc git — rỗng nếu REPO_DIR chính là gốc."""
    return git("rev-parse", "--show-prefix").strip()


def require_repo_root() -> None:
    """REPO_DIR phải là *gốc* git, không được là một thư mục con.

    Hai lệnh git mà runner này dùng đếm đường dẫn theo hai hệ quy chiếu khác
    nhau — đo chứ không đoán:

        git ls-files                        → tính từ THƯ MỤC ĐANG ĐỨNG
        git diff BASE_BRANCH --numstat      → tính từ GỐC GIT

    REPO_DIR là gốc thì hai hệ trùng nhau và không ai để ý.  REPO_DIR là thư
    mục con (clone thành ``agent-workspace/flow-v2`` chẳng hạn) thì cùng một
    file mang hai tên khác nhau ở hai chỗ trong cùng một tiến trình:
    ``repo_files`` gọi nó là ``automation_center/src/worker.js`` còn
    ``branch_diff_stats`` gọi nó là ``flow-v2/automation_center/src/worker.js``.

    Chỗ chết người là bốn mục trong ``PROTECTED_GLOBS`` —
    ``automation_center/src/worker.js``, ``automation_center/migrations/**``,
    ``runner/**``, ``scripts/**`` — neo ở gốc repo, không mở đầu bằng ``**/``.
    Tên thứ hai không khớp mục nào, nên lớp bảo vệ biến mất **im lặng**: không
    lỗi, không cảnh báo, worker.js và migrations thành file sửa tự do.  Đúng
    thứ PRD §0 cấm.

    Và nó không lộ ra trong một dàn test đường dẫn thường: mọi mục còn lại đều
    có anh em ``**/`` (``**/.env``, ``**/wrangler.jsonc``, ``**/*credentials*``)
    che mất khác biệt ở mức gốc — ``flow-v2/.env`` vẫn được bảo vệ.  Phải lấy
    đúng worker.js hay migrations mới thấy đỏ.

    Thà không khởi động còn hơn chạy mà không còn lớp bảo vệ.
    """
    if not REPO_DIR or not (REPO_DIR / ".git").exists():
        raise RuntimeError(f"AGENT_REPO_DIR không phải một repo git: {REPO_DIR or '(chưa đặt)'}")
    prefix = repo_prefix()
    if prefix:
        raise RuntimeError(
            f"AGENT_REPO_DIR ({REPO_DIR}) là thư mục con '{prefix.rstrip('/')}' của một "
            "repo git lớn hơn. Đường dẫn git khi ấy mang thêm tiền tố đó và không còn "
            "khớp PROTECTED_GLOBS, tức worker.js cùng migrations mất lớp bảo vệ mà "
            "không báo gì. Hãy trỏ AGENT_REPO_DIR vào đúng gốc repo."
        )


def require_clean_repo() -> None:
    require_repo_root()
    if git("status", "--porcelain").strip():
        raise RuntimeError(
            "Bản làm việc của agent còn thay đổi chưa dọn. Hãy vào máy trung tâm "
            f"dọn {REPO_DIR} trước khi agent chạy tiếp."
        )


# ─── Phạm vi ────────────────────────────────────────────────────────────────

def is_protected(path: str) -> bool:
    # Không phân biệt hoa thường, giống Worker: máy này chạy Windows, ở đó
    # "Secrets.json" và "secrets.json" là cùng một file.  fnmatch.fnmatch đã tự
    # hạ hoa thường trên Windows nhưng không làm thế trên máy dev, nên hạ tay
    # để hai nơi cho cùng một kết quả.
    lowered = path.lower()
    return any(fnmatch.fnmatchcase(lowered, pattern)
               or fnmatch.fnmatchcase(f"x/{lowered}", pattern)
               for pattern in PROTECTED_GLOBS)


def glob_to_regex(glob: str) -> re.Pattern[str]:
    """Cùng ngữ nghĩa với Worker: ``**`` đi qua dấu /, ``*`` thì không."""
    pattern = ["^"]
    index = 0
    while index < len(glob):
        char = glob[index]
        if char == "*":
            if glob[index + 1:index + 2] == "*":
                if glob[index + 2:index + 3] == "/":
                    pattern.append("(?:.*/)?")
                    index += 3
                    continue
                pattern.append(".*")
                index += 2
                continue
            pattern.append("[^/]*")
        elif char == "?":
            pattern.append("[^/]")
        else:
            pattern.append(re.escape(char))
        index += 1
    pattern.append("$")
    return re.compile("".join(pattern))


def normalise_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or len(raw) > 400 or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        return ""
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return ""
    # Giống Worker: loại ký tự điều khiển.  Một đường dẫn có \n vẫn đi lọt qua
    # fnmatch (fnmatch dịch sang chế độ DOTALL) và làm hỏng việc đọc
    # ``git diff --numstat`` theo dòng, nên phải chặn ngay từ đây thay vì trông
    # vào việc Worker sẽ bắt được sau khi file đã bị ghi.
    if re.search(r"[\0\n\r]", raw):
        return ""
    return "/".join(parts)


def in_scope(path: str, allow_globs: list[str]) -> bool:
    return any(glob_to_regex(glob).match(path) for glob in allow_globs)


def repo_files() -> list[str]:
    """Chỉ file git đang theo dõi — bỏ qua build, venv và mọi thứ đã ignore."""
    return [line for line in git("ls-files").splitlines() if line.strip()]


def read_repo_file(path: str) -> str:
    target = REPO_DIR / path
    if not target.is_file():
        return f"(không có file {path})"
    data = target.read_bytes()[:MAX_READ_BYTES]
    return data.decode("utf-8", "replace")


# ─── ERP HaviGroup (đọc-only) ───────────────────────────────────────────────
#
# Model xin dữ liệu ERP qua đúng action "read" đã có sẵn — một "path" dạng
# "erp:MA_DU_AN", "erp:MA_DU_AN/tasks" hay "erp:MA_TASK" được coi như một
# tham chiếu ERP thay vì file repo (xem plan_change).  Runner là bên thật sự
# gọi GraphQL, lọc lỗi, rồi trả lại đúng một cục văn bản y như khi đọc file —
# model không cầm token, không tự mở kết nối nào.  Chỉ ba tool ĐỌC của
# mcp/hvg_erp_mcp.py được lặp lại ở đây (tổng quan dự án, board Task, một
# Task); tool GHI (tạo Task, đổi trạng thái, thêm comment) cố tình không có
# đường vào đây, vì luồng chat không có bước "confirmed" của người dùng như
# MCP cá nhân — cho model tự ghi ERP qua đường này là nới quyền ngoài những gì
# đã xin.
_ERP_LAST_REQUEST_AT = 0.0

_ERP_FIELD_BY_OPERATION = {
    "ProjectOverview": "projectOverview",
    "TaskBoard": "taskBoard",
    "TaskDetail": "taskDetail",
}


def _erp_authorization() -> str:
    if ERP_BOT_TOKEN:
        return f"HVGToken {ERP_BOT_TOKEN}"
    if ERP_API_KEY and ERP_API_SECRET:
        return f"token {ERP_API_KEY}:{ERP_API_SECRET}"
    return ""


def _erp_throttle() -> None:
    global _ERP_LAST_REQUEST_AT
    wait = ERP_MIN_INTERVAL_SECONDS - (time.monotonic() - _ERP_LAST_REQUEST_AT)
    if wait > 0:
        time.sleep(wait)
    _ERP_LAST_REQUEST_AT = time.monotonic()


def erp_request(operation_name: str, query: str, variables: dict[str, Any]) -> Any:
    authorization = _erp_authorization()
    if not authorization:
        raise RuntimeError(
            "chưa cấu hình ERP_BOT_TOKEN (hoặc ERP_API_KEY + ERP_API_SECRET) trên máy trung tâm."
        )
    _erp_throttle()
    body = json.dumps(
        {"query": query, "variables": variables, "operationName": operation_name}, ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{ERP_BASE_URL}{ERP_GRAPHQL_PATH}", data=body, method="POST",
        headers={
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": USER_AGENT,
            "authorization": authorization,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=ERP_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"ERP từ chối request (HTTP {exc.code}): {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"không kết nối được ERP: {exc.reason}") from exc
    except (TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("ERP trả về phản hồi không hợp lệ hoặc quá thời gian.") from exc
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if errors:
        messages = [str(error.get("message") or "") for error in errors if isinstance(error, dict)]
        raise RuntimeError("ERP báo lỗi: " + ("; ".join(m for m in messages if m)[:400] or "(không rõ)"))
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError("ERP không trả dữ liệu GraphQL hợp lệ.")
    return data.get(_ERP_FIELD_BY_OPERATION[operation_name])


def read_erp_resource(reference: str) -> str:
    """``reference`` là phần sau ``erp:`` trong một "path" mà model xin đọc.

    Ba dạng, cùng shape với ba tool đọc của mcp/hvg_erp_mcp.py:
      MA_DU_AN            → tổng quan dự án
      MA_DU_AN/tasks       → board Task của dự án (không kèm Task đã lưu trữ)
      TASK-xxxx            → một Task

    Không bao giờ ném lỗi ra ngoài — lỗi cũng là một cục văn bản như khi đọc
    file thiếu, để model tự "answer" giải thích thay vì cả lượt hỏng theo.
    """
    target = reference.strip().strip("/")
    try:
        if not target:
            raise RuntimeError("erp: cần kèm mã dự án hoặc mã Task, ví dụ erp:PROJ-0170.")
        if re.fullmatch(r"(?i)task-[a-z0-9._-]+", target):
            payload = erp_request(
                "TaskDetail", "query TaskDetail($name: String!) { taskDetail(name: $name) }",
                {"name": target},
            )
        elif "/" in target:
            project, _, rest = target.partition("/")
            if rest.strip("/").lower() != "tasks":
                raise RuntimeError(f"không hiểu dạng erp:{reference} (chỉ hỗ trợ .../tasks).")
            payload = erp_request(
                "TaskBoard",
                "query TaskBoard($project: String!, $includeArchived: Boolean!) "
                "{ taskBoard(project: $project, includeArchived: $includeArchived) }",
                {"project": project, "includeArchived": False},
            )
        else:
            payload = erp_request(
                "ProjectOverview",
                "query ProjectOverview($project: String!) { projectOverview(project: $project) }",
                {"project": target},
            )
    except RuntimeError as exc:
        return f"(lỗi đọc ERP: {exc})"
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


# ─── ChatGPT ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Bạn là agent điều phối của HaviGroup, sửa code trong repo flow-v2 theo yêu cầu của nhân viên.

Bạn đang đứng THẬT trong repo, tại nhánh riêng đã checkout sẵn cho đúng yêu cầu này, và có công cụ thật: đọc/ghi file, chạy shell, chạy test — y như một phiên Claude Code hay Codex bình thường. Đừng đợi runner đọc hộ file nữa: cứ tự mở, tự sửa, tự chạy thử bằng công cụ của bạn trước khi trả lời.

Khi xong việc (dù có sửa file hay không), bạn LUÔN kết thúc lượt bằng một đối tượng JSON duy nhất, không kèm chữ nào khác, theo một trong bốn dạng:

1. Cần xem dữ liệu ERP mà bạn không tự lấy được (không có token ERP trong tay):
   {"action": "read", "paths": ["erp:MA_DU_AN", "erp:MA_DU_AN/tasks", "erp:MA_TASK", ...]}
2. Yêu cầu chỉ là câu hỏi, hoặc bạn đã trả lời xong mà không cần sửa file:
   {"action": "answer", "summary": "câu trả lời bằng tiếng Việt"}
3. Bạn đã tự sửa file xong bằng công cụ của mình:
   {"action": "edit", "summary": "giải thích ngắn bằng tiếng Việt cho người không đọc diff"}
4. Yêu cầu là điều khiển một agent/bot khác, không phải sửa code:
   {"action": "bot", "summary": "nói rõ bằng tiếng Việt bạn sắp làm gì",
    "commands": [{"bot_id": "id-cua-bot", "command": "run|pause",
                  "prompt": "chỉ khi command=run", "count": 1, "aspect": "landscape"}]}

Quy tắc bắt buộc:
- Chỉ được sửa những đường dẫn nằm trong danh sách phạm vi được cấp ở dưới. Runner soi lại TOÀN BỘ diff SAU KHI bạn báo xong — sửa ra ngoài phạm vi, hoặc đụng vào file trong danh sách bảo vệ, sẽ làm CẢ yêu cầu bị từ chối, không có ngoại lệ và không có đường vòng.
- Tôn trọng giới hạn số file và số dòng được nêu. Nếu yêu cầu không thể làm trong giới hạn đó, dùng "answer" để nói rõ vì sao thay vì cố nhét cho vừa.
- Không có ai đang ngồi chờ trả lời câu hỏi làm rõ giữa chừng — đây là tiến trình chạy nền. Nếu yêu cầu mơ hồ tới mức sửa sai sẽ gây hại, dùng "answer" để nói rõ điều đó thay vì đoán liều.
- Viết code khớp với phong cách xung quanh: cách đặt tên, mật độ chú thích, thành ngữ của file đang sửa.
- Một "path" dạng "erp:..." (qua action "read") là dữ liệu ERP chứ không phải file: "erp:MA_DU_AN" trả tổng quan dự án, "erp:MA_DU_AN/tasks" trả board Task của dự án đó, "erp:MA_TASK" (dạng TASK-xxxx) trả một Task. Đọc được mọi dự án ERP, không giới hạn một mã cố định. Chỉ đọc — không có cách tạo, sửa hay bình luận ERP qua đường này lẫn qua công cụ của bạn (không có token ERP nào trong môi trường bạn đang chạy).
- Chỉ dùng "bot" khi danh sách bot ở dưới có mặt và yêu cầu đúng là chạy hoặc dừng một bot. "bot_id" phải lấy đúng từ danh sách đó, không được bịa.
- Chỉ dùng command "run" khi người dùng đã nói rõ NỘI DUNG ẢNH cần tạo. Nếu họ mới chỉ bảo "mở bot"/"cho chạy" mà chưa nói tạo ảnh gì, dùng action "answer" để hỏi lại nội dung — TUYỆT ĐỐI không tự nghĩ hộ prompt.
- Một yêu cầu hoặc là sửa code, hoặc là điều khiển bot — đừng gộp cả hai vào một lượt."""


def call_chatgpt(messages: list[dict[str, str]]) -> dict[str, Any]:
    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    body = request_json(
        f"{OPENAI_BASE_URL}/chat/completions",
        method="POST",
        payload=payload,
        headers={"authorization": f"Bearer {OPENAI_API_KEY}"},
        timeout=OPENAI_TIMEOUT,
    )
    # Chỗ duy nhất trong ba provider có số token thật: call_claude và call_codex
    # là subprocess CLI, chúng không báo gì.  Ghi ra log để còn xem lại chi phí
    # một lượt; KHÔNG dùng làm trần — trần theo token sẽ lệch tuỳ provider, nên
    # trần đếm theo số yêu cầu (CODE_REQUEST_LIMITS phía Worker).
    usage = body.get("usage") or {}
    if usage:
        print(
            f"token: prompt {usage.get('prompt_tokens')} · completion "
            f"{usage.get('completion_tokens')} · tổng {usage.get('total_tokens')}"
        )
    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError("ChatGPT không trả về nội dung nào.")
    content = str(choices[0].get("message", {}).get("content") or "").strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ChatGPT trả về thứ không phải JSON: {content[:300]}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("ChatGPT trả về JSON nhưng không phải một đối tượng.")
    return parsed


# ─── Hỏi model qua CLI: Claude hoặc Codex ───────────────────────────────────

# Structured output đòi mọi khoá đều nằm trong "required", nên khoá không dùng
# tới ở một action được khai nullable thay vì bỏ đi.  Bốn action phải khớp với
# SYSTEM_PROMPT ở trên: thiếu một cái nghĩa là model không nói ra được nó, và
# nhánh xử lý tương ứng trong plan_change() thành mã chết mà không ai hay.
#
# Không còn "files": model giờ tự ghi file bằng công cụ thật của nó (xem
# docstring đầu file, mục 2026-09-01), lược đồ chỉ còn ép đúng bốn dạng hành
# động chứ không ép nội dung file phải đi qua JSON nữa.  Dùng chung cho cả
# codex (``--output-schema``, nhận đường dẫn file) lẫn claude (``--json-schema``,
# nhận chuỗi JSON trực tiếp).
OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "summary", "paths", "commands"],
    "properties": {
        "action": {"type": "string", "enum": ["read", "answer", "edit", "bot"]},
        "summary": {"type": ["string", "null"]},
        "paths": {"type": ["array", "null"], "items": {"type": "string"}},
        "commands": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["bot_id", "command", "prompt", "count", "aspect"],
                "properties": {
                    "bot_id": {"type": "string"},
                    "command": {"type": "string", "enum": ["run", "pause"]},
                    "prompt": {"type": ["string", "null"]},
                    "count": {"type": ["integer", "null"]},
                    "aspect": {"type": ["string", "null"]},
                },
            },
        },
    },
}

NHAN_VAI = {"system": "[Hệ thống]", "user": "[Người dùng]", "assistant": "[Bạn đã trả lời]"}

# QUYẾT ĐỊNH 2026-09-01: model có công cụ thật — Bash, đọc/ghi file, mạng, MCP
# (xem docstring đầu file).  Lời nhắc này chỉ còn nhắc lại điều đó thật ngắn
# cho cả hai đường CLI, không còn phải dặn "đừng thử chạy lệnh" như bản sandbox
# cũ (codex ``--sandbox read-only`` / claude ``--allowed-tools ""``) vì lệnh
# giờ chạy thật và cần chạy được.
NHAC_CO_CONG_CU = (
    "Bạn có công cụ thật ở đây: đọc/ghi file, chạy shell, chạy test — cứ dùng "
    "trước khi trả lời, đừng đoán nội dung file bạn chưa mở. "
    "Môi trường tiến trình của bạn không có token ERP hay khoá bí mật nào của "
    'hệ thống; cần dữ liệu ERP thì vẫn phải trả về action "read" với path dạng '
    '"erp:...", phía gọi sẽ đọc hộ và gửi lại ở lượt sau. '
    "Khi xong việc, trả lời bằng đúng một đối tượng JSON theo lược đồ đã cho, "
    "không kèm lời dẫn, không bọc trong hàng rào markdown."
)


def tim_codex(duong_dan: str = "") -> str | None:
    # Đi qua _tim_cli chứ đừng "dọn" về shutil.which: codex cũng là gói npm
    # toàn cục, codex.cmd nằm cùng %APPDATA%\npm với claude.cmd, mà PATH của
    # Scheduled Task kiểu S4U hẹp hơn PATH phiên đăng nhập.  Chỉ which thì
    # chạy nền sẽ thấy claude mà mù codex — auto lặng lẽ đổi đường, đúng cái
    # mà docstring chon_nha_cung_cap nói là phải tránh.
    return _tim_cli(duong_dan, "codex")


def tim_claude(duong_dan: str = "") -> str | None:
    return _tim_cli(duong_dan, "claude")


def _tim_cli(duong_dan: str, ten: str) -> str | None:
    """Đường dẫn tuyệt đối tới một CLI, hoặc ``None``.

    ``shutil.which`` trên Windows đã tự thử các đuôi trong ``PATHEXT`` nên tìm
    ra ``claude.cmd``; nhưng nó chỉ tìm trong ``PATH``, và ``PATH`` của một
    Scheduled Task không phải ``PATH`` của phiên đăng nhập.  Vì vậy thư mục
    npm toàn cục được thử thêm bằng tay — đó là chỗ ``npm install -g`` đặt
    file, và cũng là chỗ hay vắng mặt trong PATH của tiến trình nền.
    """
    if duong_dan:
        return duong_dan if Path(duong_dan).exists() else None
    found = shutil.which(ten)
    if found:
        return found
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        for duoi in (".cmd", ".exe", ""):
            ung_vien = Path(appdata) / "npm" / f"{ten}{duoi}"
            if ung_vien.exists():
                return str(ung_vien)
    return None


def chon_nha_cung_cap(
    cai_dat: str, api_key: str, codex: str | None, claude: str | None = None
) -> str:
    """Chốt đường gọi model, và hỏng to ngay nếu không có đường nào.

    Chọn bừa ở đây nghĩa là runner khởi động bình thường rồi mới hỏng ở yêu cầu
    đầu tiên của một người thật.

    Thứ tự của ``auto`` — khoá API, rồi Claude CLI, rồi Codex CLI — là thứ tự
    "cái nào chắc chắn nhất trước".  Nó cố ý *không* phải một lựa chọn về chất
    lượng: máy nào có sẵn hai CLI thì hãy nói thẳng tên đường trong
    ``AGENT_MODEL_PROVIDER`` chứ đừng để hàm này đoán hộ.
    """
    cai_dat = (cai_dat or "auto").strip().lower() or "auto"
    if cai_dat == "openai":
        if not api_key:
            raise RuntimeError("AGENT_MODEL_PROVIDER=openai nhưng OPENAI_API_KEY trống.")
        return "openai"
    if cai_dat == "codex":
        if not codex:
            raise RuntimeError(
                "AGENT_MODEL_PROVIDER=codex nhưng không tìm thấy codex CLI; "
                "đặt CODEX_BIN trỏ tới đường dẫn tuyệt đối của nó.")
        return "codex"
    if cai_dat == "claude":
        if not claude:
            raise RuntimeError(
                "AGENT_MODEL_PROVIDER=claude nhưng không tìm thấy claude CLI; "
                "cài bằng `npm install -g @anthropic-ai/claude-code` rồi đặt "
                "CLAUDE_BIN trỏ tới đường dẫn tuyệt đối của nó.")
        return "claude"
    if cai_dat != "auto":
        raise RuntimeError(f"AGENT_MODEL_PROVIDER không hiểu được: {cai_dat}")
    if api_key:
        return "openai"
    if claude:
        return "claude"
    if codex:
        return "codex"
    raise RuntimeError(
        "Không gọi được model: OPENAI_API_KEY trống và cũng không tìm thấy "
        "claude CLI lẫn codex CLI.")


def codex_argv(binary: str, *, work_dir: Path, schema_path: Path, out_path: Path,
               model: str = "") -> list[str]:
    """Cờ dòng lệnh cho một lượt hỏi codex — full quyền, có chủ ý (2026-09-01).

    ``--dangerously-bypass-approvals-and-sandbox`` thay cho ``--sandbox
    read-only`` cũ: codex chạy Bash, đọc/ghi file thật, không dừng lại hỏi
    duyệt lệnh nào giữa chừng — đúng như một phiên codex thường, không còn là
    "đường truyền chữ" (xem docstring đầu file).  ``work_dir`` giờ là chính
    REPO_DIR đã checkout sẵn nhánh ``agent/<id>`` (xem ``handle_request``), nên
    không cần ``--skip-git-repo-check`` như bản làm việc trong thư mục tạm
    rỗng trước đây. Lớp chặn không còn nằm ở cờ dòng lệnh nữa mà ở
    ``validate_touched_paths`` — soi diff SAU khi model xong việc.
    """
    argv = [
        binary, "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--cd", str(work_dir),
        # Không để lại bản sao lời nhắc (có nội dung file của repo) trong ~/.codex.
        "--ephemeral",
        # config.toml của người dùng không được đổi model hay hook của một tiến
        # trình chạy không người trông.  Auth vẫn lấy từ CODEX_HOME.
        "--ignore-user-config",
        "--color", "never",
        "--output-schema", str(schema_path),
        "--output-last-message", str(out_path),
    ]
    if model:
        argv += ["--model", model]
    # Lời nhắc đọc từ stdin: vòng "read" gửi lại cả lịch sử mỗi lượt, mà dòng
    # lệnh Windows cắt ở ~32k ký tự và agent sẽ lặng lẽ mất ngữ cảnh.
    argv.append("-")
    return argv


def claude_argv(binary: str, *, work_dir: Path, model: str = "") -> list[str]:
    """Cờ dòng lệnh cho một lượt hỏi Claude CLI — full quyền, có chủ ý (2026-09-01).

    ``--dangerously-skip-permissions`` thay cho cặp ``--allowed-tools ""`` +
    ``--strict-mcp-config`` cũ: Claude Code chạy Bash, Read, Write, Edit, MCP
    thật, không dừng lại hỏi duyệt gì giữa chừng — đúng như một phiên Claude
    Code thường, không còn là "đường truyền chữ" (xem docstring đầu file).
    Lớp chặn không còn nằm ở cờ dòng lệnh nữa mà ở ``validate_touched_paths`` —
    soi diff SAU khi model xong việc.

    ``--json-schema`` ép Claude kết thúc lượt bằng đúng ``OUTPUT_SCHEMA``,
    dùng chung với codex.  Cờ này (khác ``--output-schema`` của codex, nhận
    đường dẫn file) nhận thẳng chuỗi JSON trên dòng lệnh — kiểm lại bằng
    `claude --help` (2026-09-01) trước khi dùng, vì bản docstring cũ của module
    này từng ghi nhầm là Claude CLI không có cờ tương đương.

    ``work_dir`` cố ý không thành cờ nào: claude không có ``--cd``, nó nhận thư
    mục làm việc qua ``cwd`` của ``subprocess.run`` bên ``call_claude`` — giờ
    là chính REPO_DIR đã checkout sẵn nhánh ``agent/<id>``, không còn là thư
    mục tạm rỗng.  Vẫn bắt truyền vào đây để lời gọi tự nói rõ ý, khớp khuôn
    với ``codex_argv``.
    """
    del work_dir  # Chỉ để ép người gọi nói rõ; đường đi thật là cwd của subprocess.
    argv = [
        binary,
        # In một lượt rồi thoát, không mở phiên tương tác chờ bàn phím.
        "-p",
        # Phong bì JSON gọn trên stdout; "text" thì lẫn câu trả lời với lời dẫn.
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "--json-schema", json.dumps(OUTPUT_SCHEMA),
    ]
    if model:
        argv += ["--model", model]
    # Không có "-" cuối như codex: ``claude -p`` không kèm lời nhắc trên dòng
    # lệnh thì tự đọc stdin.  Lời nhắc phải đi đường đó — vòng "read" gửi lại
    # cả lịch sử mỗi lượt, mà dòng lệnh Windows cắt ở ~32k ký tự và agent sẽ
    # lặng lẽ mất ngữ cảnh.
    return argv


def gop_loi_nhac(messages: list[dict[str, str]]) -> str:
    khuc = [
        f"{NHAN_VAI.get(m.get('role'), m.get('role'))}\n{m.get('content') or ''}"
        for m in messages
    ]
    khuc.append(f"[Hệ thống]\n{NHAC_CO_CONG_CU}")
    return "\n\n".join(khuc)


def doc_json_khoan_dung(text: str, nhan: str) -> dict[str, Any]:
    """Bóc một đối tượng JSON từ chuỗi model trả về, khoan dung với lời dẫn.

    Model được dặn trả JSON trần (bên codex còn có ``--output-schema`` chặn
    giúp), nhưng "được dặn" không phải "chắc chắn": vẫn có lúc nó bọc JSON
    trong ```json … ``` hoặc kẹp giữa hai câu dẫn.  Cắt lấy phần đọc được rẻ
    hơn nhiều so với hỏng cả lượt rồi bắt người ta gõ lại yêu cầu.

    ``nhan`` là tên đường gọi ("Codex", "Claude") để thông báo lỗi chỉ thẳng
    bên nào trả lời hỏng — hai CLI cùng chạy trên một máy, lỗi không ghi tên
    thì người trực phải đoán.
    """
    raw = (text or "").strip()
    if not raw:
        raise RuntimeError(f"{nhan} không trả về nội dung nào.")
    ung_vien = [raw]
    rao = re.search(r"```(?:json)?\s*(.+?)\s*```", raw, re.DOTALL)
    if rao:
        ung_vien.insert(0, rao.group(1))
    dau, cuoi = raw.find("{"), raw.rfind("}")
    if dau >= 0 and cuoi > dau:
        ung_vien.append(raw[dau:cuoi + 1])
    for manh in ung_vien:
        try:
            parsed = json.loads(manh)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise RuntimeError(f"{nhan} trả về thứ không phải JSON: {raw[:300]}")


def doc_ket_qua_codex(text: str) -> dict[str, Any]:
    # Lớp bọc mỏng giữ tên cũ: test đang gọi đích danh hàm này, và tên cũng là
    # một phần hợp đồng — xoá nó là đổi API công khai của module chứ không phải
    # dọn dẹp nội bộ.
    return doc_json_khoan_dung(text, "Codex")


def call_codex(messages: list[dict[str, str]], *, chay=None) -> dict[str, Any]:
    binary = tim_codex(CODEX_BIN)
    if not binary:
        raise RuntimeError("Không tìm thấy codex CLI; đặt CODEX_BIN nếu nó không nằm trong PATH.")
    chay = chay or subprocess.run
    # codex đứng thật trong REPO_DIR — nhánh agent/<id> đã checkout sẵn ở
    # handle_request (xem docstring đầu file) — chỉ có schema/kết quả của
    # riêng lượt gọi này là nằm ngoài repo, trong một thư mục tạm dùng xong bỏ.
    tam = Path(tempfile.mkdtemp(prefix="agent-codex-"))
    try:
        schema_path = tam / "luoc-do.json"
        out_path = tam / "tra-loi.json"
        schema_path.write_text(json.dumps(OUTPUT_SCHEMA), encoding="utf-8")
        argv = codex_argv(binary, work_dir=REPO_DIR, schema_path=schema_path,
                          out_path=out_path, model=CODEX_MODEL)
        try:
            ket_qua = chay(
                argv, input=gop_loi_nhac(messages), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=OPENAI_TIMEOUT,
                env=subprocess_env(),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Codex CLI quá {OPENAI_TIMEOUT}s chưa trả lời (OPENAI_TIMEOUT_SECONDS)."
            ) from exc
        if ket_qua.returncode != 0:
            loi = (ket_qua.stderr or ket_qua.stdout or "").strip()[-1500:]
            raise RuntimeError(
                f"Codex CLI thoát với mã {ket_qua.returncode}: {loi or 'không có thông báo'}")
        if not out_path.exists():
            raise RuntimeError("Codex CLI chạy xong nhưng không ghi câu trả lời cuối.")
        return doc_ket_qua_codex(out_path.read_text(encoding="utf-8", errors="replace"))
    finally:
        shutil.rmtree(tam, ignore_errors=True)


# Dấu hiệu CLI từ chối vì chưa đăng nhập, hạ hoa thường sẵn.  Mã thoát của
# claude không phân biệt "chưa login" với các lỗi khác, mà dòng chữ nó in thì
# đổi theo phiên bản — nên dò vài cụm bền thay vì so khớp nguyên câu.  Dò trượt
# cũng không sao: thông báo chung bên dưới vẫn kèm nguyên văn stderr.
DAU_HIEU_CHUA_DANG_NHAP = ("login", "logged in", "log in", "api key", "authenticat")


def call_claude(messages: list[dict[str, str]], *, chay=None) -> dict[str, Any]:
    """Một lượt hỏi qua Claude CLI, cùng khuôn với ``call_codex``.

    ``chay`` mặc định là ``subprocess.run`` và tiêm được trong test — CLI thật
    đòi đăng nhập sẵn nên test mà gọi thật là test chỉ xanh trên đúng một máy.
    """
    binary = tim_claude(CLAUDE_BIN)
    if not binary:
        raise RuntimeError("Không tìm thấy claude CLI; đặt CLAUDE_BIN nếu nó không nằm trong PATH.")
    chay = chay or subprocess.run
    # claude đứng thật trong REPO_DIR — nhánh agent/<id> đã checkout sẵn ở
    # handle_request (xem docstring đầu file).  Nó tự đọc CLAUDE.md và .claude/
    # của thư mục đang đứng: đó là điều muốn, không phải rủi ro — một phiên
    # Claude Code thường cũng vậy.
    argv = claude_argv(binary, work_dir=REPO_DIR, model=CLAUDE_MODEL)
    try:
        # binary là đường dẫn tuyệt đối tới claude.cmd (npm trên Windows
        # không cài .exe): CreateProcess tự chạy được file .cmd gọi đủ
        # đường dẫn, nên không cần — và không được — shell=True, vì thêm
        # một lớp cmd.exe là thêm một lớp trích dẫn để sai.
        ket_qua = chay(
            argv, input=gop_loi_nhac(messages), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=OPENAI_TIMEOUT,
            cwd=str(REPO_DIR), env=subprocess_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Claude CLI quá {OPENAI_TIMEOUT}s chưa trả lời (OPENAI_TIMEOUT_SECONDS)."
        ) from exc
    if ket_qua.returncode != 0:
        loi = (ket_qua.stderr or ket_qua.stdout or "").strip()[-1500:]
        if any(dau in loi.lower() for dau in DAU_HIEU_CHUA_DANG_NHAP):
            raise RuntimeError(
                "Claude CLI chưa đăng nhập trên máy này. Mở một phiên đăng nhập "
                "của đúng user chạy Scheduled Task, chạy `claude` rồi `/login` "
                f"(hoặc `claude setup-token`). CLI báo: {loi}")
        raise RuntimeError(
            f"Claude CLI thoát với mã {ket_qua.returncode}: {loi or 'không có thông báo'}")
    # ``--output-format json`` in ra một PHONG BÌ — {"type": "result",
    # "is_error": false, "result": "<chuỗi>"} — chứ không phải JSON nghiệp vụ.
    # Phải bóc hai lớp: phong bì trước, rồi mới tới JSON theo SYSTEM_PROMPT nằm
    # trong "result".  Đọc thẳng một lớp thì lượt nào cũng "action lạ" vì phong
    # bì không có khoá "action" — hỏng 100% chứ không hỏng thỉnh thoảng.
    phong_bi = doc_json_khoan_dung(ket_qua.stdout, "Claude")
    if phong_bi.get("is_error"):
        # is_error đi kèm mã thoát 0: CLI chạy trọn vẹn nhưng lượt hỏi hỏng
        # (hết hạn mức, model từ chối…).  Nuốt nó là trả phong bì lỗi cho
        # plan_change như thể một câu trả lời thật.
        chi_tiet = str(phong_bi.get("result") or phong_bi.get("subtype") or "").strip()
        raise RuntimeError(f"Claude CLI báo lỗi: {chi_tiet[:600] or 'không có thông báo'}")
    if "result" not in phong_bi:
        # Không thấy phong bì quen thuộc: hoặc test tiêm thẳng JSON nghiệp vụ,
        # hoặc bản CLI sau đổi định dạng.  Nếu chính nó đã là JSON nghiệp vụ
        # thì plan_change đọc được; nếu không, chỗ kiểm "action" ở đó sẽ báo.
        return phong_bi
    ruot = phong_bi.get("result")
    if isinstance(ruot, dict):
        # Phòng khi CLI trả sẵn đối tượng thay vì chuỗi; str() lên một dict sẽ
        # ra repr Python ('single quote') mà json.loads không đọc nổi.
        return ruot
    return doc_json_khoan_dung(str(ruot or ""), "Claude")


def call_model(messages: list[dict[str, str]]) -> dict[str, Any]:
    nha = chon_nha_cung_cap(
        MODEL_PROVIDER, OPENAI_API_KEY, tim_codex(CODEX_BIN), tim_claude(CLAUDE_BIN))
    if nha == "claude":
        return call_claude(messages)
    if nha == "codex":
        return call_codex(messages)
    return call_chatgpt(messages)


def build_context(request: dict[str, Any], allow_globs: list[str], scope: dict[str, Any]) -> str:
    tracked = repo_files()
    editable = [path for path in tracked if in_scope(path, allow_globs) and not is_protected(path)]
    listing = editable[:MAX_CONTEXT_FILES]
    history_lines = []
    for message in request.get("history") or []:
        who = {"user": "Người dùng", "agent": "Agent", "system": "Hệ thống"}.get(message.get("kind"), "?")
        history_lines.append(f"[{who}] {str(message.get('content') or '')[:1500]}")
    return "\n".join([
        f"Người gửi: {request.get('requested_by')} (vai trò {request.get('requested_role')})",
        f"Phạm vi được cấp: {', '.join(allow_globs)}",
        f"Giới hạn: tối đa {scope.get('max_files')} file, {scope.get('max_lines')} dòng thay đổi.",
        "",
        f"File bạn được phép sửa ({len(editable)} file, liệt kê {len(listing)}):",
        *(f"  {path}" for path in listing),
        "" if len(editable) <= len(listing) else f"  … và {len(editable) - len(listing)} file nữa.",
        "",
        "Trao đổi trong luồng:",
        *history_lines,
        "",
        f"Yêu cầu cần xử lý: {request.get('instruction')}",
        "",
        *bot_context_lines(request),
    ])


def bot_context_lines(request: dict[str, Any]) -> list[str]:
    """Model chỉ thấy bot khi Center nói người gửi có quyền điều khiển bot.

    Không thấy thì không gọi tên được, và kể cả có bịa ra một bot_id thì Center
    vẫn kiểm quyền lần nữa lúc thực thi.
    """
    bots = request.get("bots") or []
    if not request.get("may_control_bots") or not bots:
        return ["Người gửi không có quyền điều khiển bot, nên đừng dùng action \"bot\"."]
    lines = ["Các bot trong chương trình này (dùng cho action \"bot\"):"]
    for bot in bots:
        lines.append(
            f"  bot_id={bot.get('id')} · {bot.get('name')} · đang {bot.get('status')}"
        )
    return lines


def plan_change(request: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    """Hỏi model tới khi nó chốt "edit", "answer" hay "bot"; tối đa MAX_ROUNDS lượt."""
    allow_globs = [glob for glob in (scope.get("allow_globs") or []) if glob]
    # Rỗng khi ai đó gọi plan_change ngoài vòng đời một yêu cầu thật (test);
    # khi đó không có gì để báo về Center.
    request_id = str(request.get("id") or "")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_context(request, allow_globs, scope)},
    ]
    for _ in range(MAX_ROUNDS):
        reply = call_model(messages)
        action = str(reply.get("action") or "").lower()
        if action in {"answer", "edit", "bot"}:
            return reply
        if action != "read":
            raise RuntimeError(f"Model trả về action lạ: {action or '(trống)'}")
        wanted = [normalise_path(path) for path in (reply.get("paths") or [])][:12]
        chunks = []
        for path in wanted:
            if not path:
                continue
            if path.lower().startswith("erp:"):
                chunks.append(f"### {path}\n```\n{read_erp_resource(path[4:])}\n```")
                continue
            # Đọc rộng hơn quyền ghi là có chủ ý — agent cần hiểu chỗ xung
            # quanh mới sửa đúng — nhưng file được bảo vệ thì không rời máy.
            if is_protected(path):
                chunks.append(f"### {path}\n(file được bảo vệ, không gửi nội dung)")
                continue
            chunks.append(f"### {path}\n```\n{read_repo_file(path)}\n```")
        messages.append({"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)})
        messages.append({"role": "user", "content": "\n\n".join(chunks) or "(không đọc được file nào)"})
        # Vòng "read" vừa xong, còn ít nhất một vòng nữa: lên tiếng để watchdog
        # của Center không thấy một khoảng im lặng liền mạch.  Heartbeat runner
        # chỉ chạm bảng runners, còn orphanCodeRequests nhìn đúng
        # code_change_requests.updated_at — và worker.js bump cột ấy cho đường
        # "planning".  Center hỏng thì lượt đang chạy vẫn phải chạy tiếp.
        if request_id:
            try:
                report(request_id, "planning")
            except Exception as exc:
                print(f"Không báo được nhịp planning: {exc}", file=sys.stderr)
    raise RuntimeError("Model chỉ đòi đọc file mà không đưa ra thay đổi nào sau nhiều lượt.")


# ─── Thực thi ───────────────────────────────────────────────────────────────

def process_output_text(value: str | bytes | None) -> str:
    """TimeoutExpired có thể mang None, bytes, hoặc str dù text=True."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def test_output_tail(stdout: str | bytes | None, stderr: str | bytes | None) -> str:
    """Ghép output và giữ cùng trần 6000 ký tự cho mọi lối ra của test."""
    return (process_output_text(stdout) + process_output_text(stderr)).strip()[-6000:]


def run_tests() -> tuple[bool, str]:
    if not TEST_COMMAND:
        return False, "Chưa cấu hình AGENT_TEST_COMMAND nên không có test nào chạy; thay đổi luôn cần người duyệt."
    try:
        result = subprocess.run(
            TEST_COMMAND, cwd=REPO_DIR, shell=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=TEST_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        output = test_output_tail(exc.stdout, exc.stderr)
        message = f"Test `{TEST_COMMAND}` quá {TEST_TIMEOUT}s nên bị dừng."
        if output:
            return False, f"{message}\n\nOutput trước khi dừng:\n{output}"
        return False, message
    output = test_output_tail(result.stdout, result.stderr)
    return result.returncode == 0, output or "(test không in ra gì)"


def validate_touched_paths(paths: list[str], allow_globs: list[str], max_files: int) -> None:
    """Soi lại SAU KHI model đã tự ghi file bằng công cụ của nó.

    Trước đây (``write_files``) đây là kiểm TRƯỚC khi ghi; giờ không còn
    "trước khi ghi" nào để soi nữa — model có Bash thật và tự ghi trực tiếp
    (xem docstring đầu file, mục 2026-09-01).  Danh sách ``paths`` tới từ
    ``branch_diff_stats()``, tức từ chính git chứ không phải từ lời model tự
    khai — không có đường nào để model nói dối về việc nó đã đụng gì.

    Ném lỗi là toàn bộ yêu cầu bị từ chối (xem ``handle_request``): không có
    cách "chỉ nhận phần trong phạm vi" — một request đụng cả file bảo vệ lẫn
    file hợp lệ vẫn hỏng nguyên cục, đúng ngữ nghĩa cũ của ``write_files``.
    """
    if len(paths) > max_files:
        raise RuntimeError(f"Agent đã sửa {len(paths)} file, vượt mức {max_files} của phạm vi.")
    for path in paths:
        if is_protected(path):
            raise RuntimeError(f"{path} nằm trong danh sách bảo vệ, agent không được ghi.")
        if not in_scope(path, allow_globs):
            raise RuntimeError(f"{path} nằm ngoài phạm vi được cấp.")
        target = REPO_DIR / path
        if target.is_file() and target.stat().st_size > MAX_WRITE_BYTES:
            raise RuntimeError(f"Nội dung mới của {path} quá lớn.")


def branch_diff_stats() -> tuple[list[str], int, str]:
    """So working tree hiện tại với BASE_BRANCH — không phải ``--cached``.

    Trước đây (``staged_stats``) so với chỉ số (``--cached``, tức so với
    HEAD): đúng khi runner là bên duy nhất ghi và ``add`` file.  Giờ model có
    Bash thật và có thể tự ``git commit`` giữa chừng (xem docstring đầu file) —
    lúc đó ``--cached`` không còn gì để so (đã nằm trong HEAD) và sẽ báo nhầm
    "không có gì thay đổi", âm thầm nuốt mất toàn bộ việc model vừa làm.  So
    thẳng với BASE_BRANCH thì thấy đúng tổng delta trên nhánh, bất kể model đã
    commit hay chưa.
    """
    # ``--numstat`` đếm từ gốc git, không từ thư mục đang đứng, nên quy về khung
    # của repo trước khi trả ra: mọi thứ phía sau — ``is_protected``, báo cáo lên
    # Center — đều nói bằng khung repo.  ``require_repo_root`` khiến tiền tố này
    # luôn rỗng trên máy cấu hình đúng; giữ bước quy đổi để nếu ngày nào đó cái
    # chốt kia bị nới ra thì đường dẫn vẫn nằm trong đúng một khung.
    prefix = repo_prefix()
    paths, lines = [], 0
    for row in git("diff", BASE_BRANCH, "--numstat").splitlines():
        parts = row.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        if prefix:
            if not path.startswith(prefix):
                raise RuntimeError(
                    f"File {path} nằm ngoài {REPO_DIR}; runner không nhận thay đổi "
                    "ở ngoài repo của chính nó."
                )
            path = path[len(prefix):]
        paths.append(path)
        for value in (added, deleted):
            if value.isdigit():
                lines += int(value)
    # Trả diff đầy đủ.  Cắt ở đây là vứt mất thông tin "đã cắt" ngay tại chỗ
    # duy nhất còn biết điều đó — sau bước này không ai suy ngược ra được nữa.
    return paths, lines, git("diff", BASE_BRANCH)


def cleanup_branch(branch: str) -> None:
    """Đưa repo về BASE_BRANCH sạch và xoá nhánh tạm của agent.

    Dùng ở MỌI lối ra của handle_request — kể cả "answer"/"bot" và trường hợp
    không có gì thay đổi — vì nhánh agent/<id> đã được checkout ra TRƯỚC KHI
    gọi model: model cầm công cụ thật, có thể tự sửa file ngay trong lúc
    "lên kế hoạch", nên không còn lối ra nào được phép bỏ qua bước dọn này.
    """
    git("reset", "--hard", check=False)
    git("clean", "-fd", check=False)
    git("checkout", BASE_BRANCH, check=False)
    git("branch", "-D", branch, check=False)


# Nhánh runner đang cầm, tra theo id yêu cầu.  Chỉ những nhánh đang chờ người
# duyệt mới nằm đây: mọi lối ra khác đã dọn ngay tại chỗ.
HELD_BRANCHES: dict[str, str] = {}


def drop_finished_branches() -> None:
    """Xoá nhánh của những yêu cầu mà Center nói đã xong hẳn.

    Ba đường kết thúc không đi qua runner: người gửi huỷ muộn, người duyệt từ
    chối, và watchdog của Center đóng yêu cầu.  Không hỏi lại thì nhánh nằm đó
    tới ngày một id sau trùng 12 ký tự đầu và ``checkout -B`` đè lên nó.

    Chỉ ``branch -D``, không gọi cleanup_branch: ở đây runner đang đứng trên
    BASE_BRANCH, không cần reset/clean cây làm việc.  Lỗi mạng hay Worker chưa
    có route này không được phép chặn đường nhận việc.
    """
    if not HELD_BRANCHES:
        return
    try:
        answer = center_request("/api/runner/code/finished", method="POST", payload={
            "runner_key": RUNNER_KEY, "ids": list(HELD_BRANCHES),
        })
    except Exception as exc:
        print(f"Không hỏi được danh sách yêu cầu đã kết thúc: {exc}", file=sys.stderr)
        return
    for row in answer.get("finished") or []:
        request_id = str(row.get("id") or "")
        branch = HELD_BRANCHES.pop(request_id, "")
        if branch:
            print(f"[{request_id}] {row.get('status')} → xoá nhánh {branch}")
            git("branch", "-D", branch, check=False)



def sweep_stale_branches() -> None:
    """Quét nhánh agent/* sót lại từ lần chạy trước và dọn cái đã xong hẳn.

    HELD_BRANCHES nằm trong bộ nhớ, nên một lần kill -9 hay một lần khởi động
    lại là mất sạch: nhánh còn trên đĩa mà không ai còn nhớ nó của yêu cầu nào.
    Tên nhánh chỉ mang 12 ký tự đầu của id nên runner KHÔNG tự dựng lại id
    được; cột branch của Center là bên duy nhất giữ cả hai đầu, nên phải hỏi.

    Chỉ xoá nhánh Center xác nhận đã kết thúc.  Nhánh Center không nhận ra thì
    GIỮ và in ra cho người trực: một nhánh thừa tốn vài KB, còn xoá nhầm một
    nhánh đang chờ duyệt là mất cả lượt model — đúng thứ B3 sinh ra để chống.
    """
    try:
        listed = git("branch", "--list", "agent/*", check=False)
    except Exception as exc:
        # Dọn dẹp là việc phụ.  Repo chưa sẵn sàng hay git lỗi thì bỏ qua lượt
        # quét, tuyệt đối không được chặn runner nhận việc.
        print(f"Không quét được nhánh agent/* lúc khởi động: {exc}", file=sys.stderr)
        return
    branches = [line.strip().lstrip("*+ ").strip() for line in listed.splitlines()]
    branches = [name for name in branches if name.startswith("agent/")]
    if not branches:
        return
    try:
        answer = center_request("/api/runner/code/finished", method="POST", payload={
            "runner_key": RUNNER_KEY, "branches": branches,
        })
    except Exception as exc:
        print(f"Không hỏi được trạng thái {len(branches)} nhánh agent/* còn sót: {exc}", file=sys.stderr)
        return
    xong = {str(row.get("branch") or ""): str(row.get("status") or "") for row in answer.get("finished") or []}
    for name in branches:
        status = xong.get(name)
        if status:
            print(f"[khởi động] {name} ({status}) → xoá")
            git("branch", "-D", name, check=False)
        else:
            print(
                f"[khởi động] {name} chưa xong hoặc Center không biết — giữ lại. "
                f"Xoá tay khi đã xem: git branch -D {name}",
                file=sys.stderr,
            )


def handle_request(request: dict[str, Any]) -> None:
    request_id = str(request["id"])
    scope = request.get("scope") or {}
    allow_globs = [glob for glob in (scope.get("allow_globs") or []) if glob]
    if not allow_globs:
        report(request_id, "failed", error="Yêu cầu không kèm phạm vi nào nên bị bỏ qua.")
        return

    branch = f"agent/{request_id[:12]}"
    require_clean_repo()
    # Tên nhánh chỉ lấy 12 ký tự đầu của id nên trùng tên là chuyện có thật, và
    # nhánh cũ có thể đang giữ một thay đổi chờ người duyệt.  Không chặn —
    # yêu cầu mới vẫn phải chạy — nhưng đè thì phải để lại dấu vết đọc được.
    if git("branch", "--list", branch, check=False).strip():
        print(f"[{request_id}] nhánh {branch} đã tồn tại, checkout -B sẽ ghi đè lên nó.", file=sys.stderr)
    git("checkout", "-B", branch, BASE_BRANCH)
    summary = ""
    # Nhánh chỉ được giữ lại ở đúng một ca: thay đổi đã commit và đang chờ
    # người duyệt, vì apply_approved còn cần nó.  Mọi lối ra khác đều dọn — kể
    # cả lối ra do một ngoại lệ không ai lường trước, đó là việc của finally.
    keep_branch = False
    try:
        plan = plan_change(request, scope)
        action = str(plan.get("action") or "").lower()
        summary = str(plan.get("summary") or "").strip()

        if action == "answer":
            report(request_id, "answered", plan_summary=summary)
            return

        if action == "bot":
            # Điều khiển bot không sinh diff, nhưng nhánh vẫn đã tạo ở trên nên
            # vẫn phải dọn: runner chỉ chuyển lệnh, còn quyền thì Center kiểm
            # lại bằng đúng lõi mà nút bấm trên web dùng.  Không tự lọc theo
            # danh sách bot ở đây — lọc hai nơi thì một ngày nào đó hai nơi sẽ
            # khác nhau, và bên nới hơn sẽ là bên có hiệu lực.
            commands = plan.get("commands")
            summary = summary or "Agent điều khiển bot."
            if not isinstance(commands, list) or not commands:
                report(request_id, "failed", plan_summary=summary,
                       error="Agent nói sẽ điều khiển bot nhưng không đưa ra lệnh nào.")
                return
            report(request_id, "bot_action", plan_summary=summary, bot_commands=commands[:5])
            return

        summary = summary or "Agent không mô tả thay đổi."

        # Model đã tự ghi file bằng công cụ của chính nó ngay trong lúc
        # plan_change chạy — không còn write_files() nào để gọi ở đây nữa.
        # git add -A gom cả phần nó có thể đã lỡ để ngoài staging; nếu nó đã
        # tự git commit rồi thì lệnh này không còn gì để thêm.
        git("add", "-A")
        paths, lines, full_diff = branch_diff_stats()
        if not paths:
            report(request_id, "answered", plan_summary=f"{summary}\n\n(Không có gì thay đổi so với bản hiện tại.)")
            return
        validate_touched_paths(paths, allow_globs, int(scope.get("max_files") or 1))
        max_lines = int(scope.get("max_lines") or 1)
        if lines > max_lines:
            raise RuntimeError(f"Thay đổi {lines} dòng, vượt mức {max_lines} của phạm vi.")
        if is_cancelled(request_id):
            raise RuntimeError("Người gửi đã rút lại yêu cầu trước khi test chạy xong.")
        passed, output = run_tests()
        diff_text = full_diff[:DIFF_LIMIT]
        diff_truncated = 1 if len(full_diff) > DIFF_LIMIT else 0
        # Model có thể đã tự commit bằng Bash của chính nó; chỉ commit hộ khi
        # còn gì đó chưa được đóng gói.
        if git("status", "--porcelain").strip():
            git("commit", "--no-verify", "-m", f"agent: {summary[:70]}\n\nYêu cầu {request_id} · {request.get('requested_by')}")
        commit = git("rev-parse", "HEAD").strip()
        # Từ đây nhánh đang giữ commit chờ người duyệt: apply_approved sẽ merge
        # nó ở một lượt sau, nên đây là lối ra duy nhất không dọn.
        keep_branch = True
    except Exception as exc:
        report(request_id, "failed", plan_summary=summary, error=str(exc)[:2000])
        return
    finally:
        if keep_branch:
            HELD_BRANCHES[request_id] = branch
        else:
            HELD_BRANCHES.pop(request_id, None)
            cleanup_branch(branch)

    git("checkout", BASE_BRANCH)
    response = report(
        request_id, "awaiting_approval",
        plan_summary=summary,
        files=[{"path": path} for path in paths],
        lines_changed=lines,
        diff_text=diff_text,
        # Cờ đi kèm diff, không để Worker đoán: thứ gửi đi đã cắt sẵn nên bên
        # kia đo bao nhiêu cũng chỉ thấy một diff vừa khít trần.
        diff_truncated=diff_truncated,
        test_output=output,
        tests_passed=passed,
        branch=branch,
    )
    if response.get("blocked"):
        HELD_BRANCHES.pop(request_id, None)
        git("branch", "-D", branch, check=False)
        return
    print(f"[{request_id}] {len(paths)} file, {lines} dòng, test {'xanh' if passed else 'chưa xanh'} → {response.get('status')} (commit {commit[:8]})")


def apply_approved(request: dict[str, Any]) -> None:
    request_id = str(request["id"])
    branch = str(request.get("branch") or "").strip()
    if not branch:
        report(request_id, "failed", error="Yêu cầu đã được duyệt nhưng không có nhánh nào để áp.")
        return
    # Vào sổ trước khi merge.  Duyệt thường tới ở lượt sau, có khi sau cả một
    # lần khởi động lại, lúc HELD_BRANCHES đã rỗng: không ghi lại ở đây thì
    # đường merge hỏng bỏ nhánh lại mà không ai theo dõi.  Ghi rồi thì yêu cầu
    # chuyển sang "failed" là trạng thái cuối, và drop_finished_branches xoá
    # nhánh ngay vòng poll kế tiếp.
    HELD_BRANCHES[request_id] = branch
    report(request_id, "applying")
    try:
        require_clean_repo()
        git("checkout", BASE_BRANCH)
        git("merge", "--no-edit", branch)
        commit = git("rev-parse", "HEAD").strip()
        if PUSH_AFTER_MERGE:
            git("push", "origin", BASE_BRANCH)
    except Exception as exc:
        git("merge", "--abort", check=False)
        git("checkout", BASE_BRANCH, check=False)
        report(request_id, "failed", error=f"Không merge được nhánh {branch}: {exc}"[:2000])
        return
    # Nhánh đã merge không còn nghĩa gì.  Để lại thì mỗi lượt bồi thêm một
    # nhánh vào ``git branch`` của máy trung tâm, và ngày nào 12 ký tự đầu của
    # một id trùng lại thì ``checkout -B`` ở lượt sau ghi đè im lặng lên nhánh
    # cũ.  ``check=False``: không xoá được cũng không được phép biến một lần
    # merge đã thành công thành thất bại.
    git("branch", "-D", branch, check=False)
    HELD_BRANCHES.pop(request_id, None)
    report(request_id, "applied", branch=branch, commit_sha=commit)
    print(f"[{request_id}] đã merge {branch} vào {BASE_BRANCH} ({commit[:8]})")


def main() -> int:
    missing = [name for name, value in (
        ("AUTOMATION_RUNNER_SECRET", RUNNER_SECRET),
        ("AGENT_REPO_DIR", str(REPO_DIR)),
    ) if not value]
    if missing:
        print(f"Thiếu {', '.join(missing)}; runner không khởi động.", file=sys.stderr)
        return 2
    # Chốt đường gọi model ngay lúc khởi động.  Để tới yêu cầu đầu tiên mới
    # phát hiện là hỏng trước mặt một người đang chờ.
    try:
        nha = chon_nha_cung_cap(
            MODEL_PROVIDER, OPENAI_API_KEY, tim_codex(CODEX_BIN), tim_claude(CLAUDE_BIN))
        require_repo_root()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # Dòng log khởi động phải nói đúng model của đúng đường: đây là chỗ duy
    # nhất người trực nhìn ra "à, hôm nay agent trả lời bằng gì" mà không cần
    # đọc code hay .env.
    mo_ta = {
        "openai": OPENAI_MODEL,
        "claude": CLAUDE_MODEL or "mặc định của claude",
        "codex": CODEX_MODEL or "mặc định của codex",
    }[nha]
    print(f"{RUNNER_LABEL} · repo {REPO_DIR} · nhánh nền {BASE_BRANCH} · model {mo_ta} qua {nha}")
    print(f"Poll {CENTER_URL} với runner key {RUNNER_KEY}")
    # Sau các kiểm tra khởi động mới được báo sống.  Nhịp này nằm riêng để
    # handle_request/apply_approved có chặn lâu cũng không thành runner_offline.
    heartbeat_stop = threading.Event()
    heartbeat_thread = start_heartbeat_thread(heartbeat_stop)
    # Sau heartbeat: quét là một lượt gọi mạng, chậm mà chưa báo sống thì
    # dashboard nói runner offline ngay lúc nó vừa bật.
    sweep_stale_branches()
    while True:
        try:
            # Hỏi trước khi nhận việc mới: nhánh của một yêu cầu vừa bị huỷ hay
            # bị từ chối phải đi trước khi một id trùng tên kịp tới.
            drop_finished_branches()
            approved = center_request(
                f"/api/runner/code/approved?runner_key={urllib.parse.quote(RUNNER_KEY)}"
            ).get("requests") or []
            if approved:
                apply_approved(approved[0])
                continue
            claimed = center_request("/api/runner/code/claim", method="POST", payload={"runner_key": RUNNER_KEY})
            request = claimed.get("request")
            if request:
                handle_request(request)
            else:
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=HEARTBEAT_JOIN_SECONDS)
            return 0
        except Exception as exc:
            print(f"Runner lỗi: {exc}", file=sys.stderr)
            time.sleep(max(POLL_SECONDS, 5))


if __name__ == "__main__":
    raise SystemExit(main())
