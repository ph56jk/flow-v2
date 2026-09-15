"""Bảng điều khiển HaviGroup: một trang, ba phần — đăng Etsy, tạo ảnh, SKU & thuộc tính.

    .venv/bin/python -m flow_web.board                 # máy dev: mở http://127.0.0.1:8765

Trên hvg-pc bảng chạy bằng Scheduled Task (scripts/run-board.ps1), sau
Cloudflare Tunnel: https://phongdzso1tg.phonh.io.vn. Máy chủ chỉ nghe
127.0.0.1; đường ra ngoài duy nhất là cloudflared chạy trên cùng máy.

Có ``--password-file`` thì mọi trang phải đăng nhập. Tệp chỉ giữ mã băm:

    python -m flow_web.board --hash-password < mat-khau.txt > password.txt

Trang nghe ``/api/stream`` (Server-Sent Events): một luồng nền dựng ba phần,
phần nào đổi thì đẩy ngay cho mọi người đang xem. Không ai xem thì luồng nền
ngủ. Luồng hỏng hoặc quá đông thì trang tự quay về hỏi 10 giây một lần.

Phần đăng Etsy: flow_web/listing_board.py. Phần tạo ảnh: flow_web/image_board.py.
Phần SKU: flow_web/sku_board.py — đọc tệp bot ghi, không gọi ERP.
Cách đọc bảng và cách dựng lại: docs/bang-dieu-khien.md.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import html
import json
import math
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .image_board import DEFAULT_FLOW_BASE, FlowApi, JobsFile, build_images
from .listing_board import Checks, build_board, job_view
from .listing_watch import DEFAULT_BASE, ListingApi, mask
from .sku_board import build_sku

STATIC = Path(__file__).resolve().parent / "static"
PAGE = STATIC / "board.html"
LOGIN_PAGE = STATIC / "board-login.html"
LOOPBACK = ("127.0.0.1", "localhost")

# Luồng trực tiếp, tính bằng giây.
TICK = 1.0  # nhịp của luồng nền; phần tạo ảnh dựng lại mỗi nhịp
ETSY_EVERY = 5.0  # phần Etsy hỏi bản Listing thưa hơn
SKU_EVERY = 5.0  # phần SKU cũng đọc qua bản Listing; bot chỉ ghi tệp mỗi lượt quét
PUSH_ANYWAY = 15.0  # không có gì mới thì vẫn gửi lại để số giây trên bảng khỏi đứng im
HEARTBEAT = 15.0  # Cloudflare cắt kết nối im quá 100 giây
MAX_STREAMS = 20  # mỗi luồng giữ một thread; quá số này thì trang tự hỏi 10 giây một lần

# Trang tự viết hết, không tải gì của máy khác.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # Không để no-referrer: trình duyệt sẽ gửi Origin: null cho mọi POST, kể cả
    # cùng trang, và đăng nhập bị chặn. same-origin vẫn không lộ gì ra trang khác.
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
}


# ── mật khẩu ──────────────────────────────────────────────────────────

HASH_ITERATIONS = 240_000


def hash_password(password: str, salt: Optional[bytes] = None, iterations: int = HASH_ITERATIONS) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(stored: str, password: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.strip().split("$")
        if scheme != "pbkdf2_sha256":
            return False
        test = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
    except ValueError:
        return False
    return hmac.compare_digest(test.hex(), digest)


class Gate:
    """Cửa mật khẩu. Phiên là cookie ký bằng mã băm: đổi mật khẩu là mọi phiên cũ hết."""

    COOKIE = "havi_board"
    TTL = 30 * 86400
    # Sai quá số lần trong cửa sổ thì khoá. Bảng mở ra Internet: phải chặn dò mật khẩu.
    WINDOW = 15 * 60
    PER_CLIENT = 8
    OVERALL = 40

    def __init__(self, stored: str, clock: Callable[[], float] = time.time) -> None:
        stored = stored.strip()
        if not stored.startswith("pbkdf2_sha256$"):
            raise ValueError("tệp mật khẩu phải chứa mã băm pbkdf2_sha256$…, tạo bằng --hash-password")
        self.stored = stored
        self.key = hashlib.sha256(b"havi-board-session\0" + stored.encode("utf-8")).digest()
        self.clock = clock
        self.lock = threading.Lock()
        self.failures: List[Tuple[float, str]] = []

    def _sign(self, expires: int) -> str:
        return hmac.new(self.key, str(expires).encode("ascii"), hashlib.sha256).hexdigest()

    def issue(self) -> str:
        expires = int(self.clock()) + self.TTL
        return f"{expires}.{self._sign(expires)}"

    def valid(self, token: str) -> bool:
        expires, _, signature = (token or "").partition(".")
        if not expires.isdigit() or int(expires) <= self.clock():
            return False
        return hmac.compare_digest(signature, self._sign(int(expires)))

    def wait(self, client: str) -> int:
        """Số giây còn bị khoá; 0 là được thử."""
        now = self.clock()
        with self.lock:
            self.failures = [item for item in self.failures if item[0] > now - self.WINDOW]
            mine = [at for at, who in self.failures if who == client]
            if len(mine) >= self.PER_CLIENT:
                return math.ceil(mine[0] + self.WINDOW - now)
            if len(self.failures) >= self.OVERALL:
                return math.ceil(self.failures[0][0] + self.WINDOW - now)
        return 0

    def attempt(self, client: str, password: str) -> Tuple[str, int]:
        """Trả (phiên, 0) khi đúng, ("", giây chờ) khi đang khoá, ("", 0) khi sai."""
        wait = self.wait(client)
        if wait:
            return "", wait
        if verify_password(self.stored, password):
            return self.issue(), 0
        with self.lock:
            self.failures.append((self.clock(), client))
        return "", 0


# ── luồng trực tiếp ───────────────────────────────────────────────────


def _steady(value: Any) -> Any:
    # Bỏ những gì chỉ đổi theo đồng hồ: số giây (*_s). "at" ở đầu mỗi phần là giờ dựng.
    if isinstance(value, dict):
        return {key: _steady(item) for key, item in value.items() if not str(key).endswith("_s")}
    if isinstance(value, list):
        return [_steady(item) for item in value]
    return value


def _mark(data: Any) -> str:
    steady = _steady(data)
    if isinstance(steady, dict):
        steady.pop("at", None)
    return hashlib.sha256(json.dumps(steady, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class Feed:
    """Một luồng nền dựng các phần của bảng, ai đang xem cũng dùng chung.

    ``parts``: tên → (cách mấy giây dựng lại, hàm dựng). Phần nào đổi thì mang
    số phiên bản mới; mỗi người xem nhớ bản cuối mình đã nhận.
    """

    def __init__(
        self,
        parts: Dict[str, Tuple[float, Callable[[], Any]]],
        clock: Callable[[], float] = time.monotonic,
        spawn: Optional[Callable[[Callable[[], None]], None]] = None,
    ) -> None:
        self.parts = parts
        self.clock = clock
        self.spawn = spawn or (lambda work: threading.Thread(target=work, daemon=True, name="board-feed").start())
        self.tick = TICK
        self.heartbeat = HEARTBEAT
        self.limit = MAX_STREAMS
        self.cond = threading.Condition()
        self.latest: Dict[str, Tuple[int, bytes]] = {}
        self.marks: Dict[str, Tuple[str, float]] = {}
        self.due: Dict[str, float] = {}
        self.version = 0
        self.viewers = 0
        self.started = False
        self.stopped = False

    def join(self) -> bool:
        with self.cond:
            if self.stopped or self.viewers >= self.limit:
                return False
            self.viewers += 1
            start, self.started = not self.started, True
            self.cond.notify_all()
        if start:
            self.spawn(self._run)
        return True

    def leave(self) -> None:
        with self.cond:
            self.viewers = max(0, self.viewers - 1)
            if not self.viewers:
                # Không ai xem: bỏ bản cũ. Người sau nhận bản dựng mới, không phải bản để lâu.
                self.latest, self.marks, self.due = {}, {}, {}

    def stop(self) -> None:
        with self.cond:
            self.stopped = True
            self.cond.notify_all()

    def step(self) -> None:
        now = self.clock()
        with self.cond:
            if not self.viewers:
                return
            names = [name for name, (every, _) in self.parts.items() if now >= self.due.get(name, now)]
            for name in names:
                self.due[name] = now + self.parts[name][0]
        for name in names:
            try:
                data = self.parts[name][1]()
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                mark = _mark(data)
            except Exception as exc:  # một phần hỏng không được làm chết luồng nền
                print(f"[board] dựng phần {name} lỗi: {exc!r}", file=sys.stderr, flush=True)
                continue
            with self.cond:
                old = self.marks.get(name)
                if not self.viewers or (old and old[0] == mark and now - old[1] < PUSH_ANYWAY):
                    continue
                self.marks[name] = (mark, now)
                self.version += 1
                self.latest[name] = (self.version, body)
                self.cond.notify_all()

    def _run(self) -> None:
        while True:
            with self.cond:
                while not self.stopped and not self.viewers:
                    self.cond.wait()
                if self.stopped:
                    return
            self.step()
            with self.cond:
                if not self.stopped:
                    self.cond.wait(self.tick)

    def wait(self, seen: Dict[str, int], timeout: float) -> List[Tuple[str, bytes]]:
        """Các phần có bản mới hơn ``seen`` (và ghi lại vào ``seen``); hết giờ thì []."""
        deadline = time.monotonic() + timeout
        with self.cond:
            while True:
                news = [(name, body) for name, (version, body) in self.latest.items() if seen.get(name) != version]
                if news or self.stopped:
                    for name, _ in news:
                        seen[name] = self.latest[name][0]
                    return news
                left = deadline - time.monotonic()
                if left <= 0:
                    return []
                self.cond.wait(left)


# ── máy chủ ───────────────────────────────────────────────────────────


class BoardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple,
        listing: Any,
        flow: Any = None,
        checks: Optional[Checks] = None,
        gate: Optional[Gate] = None,
        hosts: Iterable[str] = (),
    ) -> None:
        super().__init__(address, BoardHandler)
        self.listing = listing
        self.flow = flow
        self.checks = checks or Checks(listing)
        self.gate = gate
        self.hosts = frozenset(LOOPBACK) | {host.lower() for host in hosts}
        # Hàm dựng đọc self.flow lúc chạy: đổi flow thì luồng thấy ngay.
        self.feed = Feed(
            {
                "img": (0, lambda: build_images(self.flow)),
                "etsy": (ETSY_EVERY, lambda: build_board(self.listing, self.checks)),
                "sku": (SKU_EVERY, lambda: build_sku(self.listing)),
            }
        )

    def server_close(self) -> None:
        self.feed.stop()  # các luồng đang mở tự đóng, trang tự nối lại khi bảng lên
        super().server_close()


class BoardHandler(BaseHTTPRequestHandler):
    server: BoardServer

    def log_message(self, format: str, *args: Any) -> None:  # trang hỏi liên tục: đừng in
        pass

    # ── gửi ──

    def _send(self, code: int, body: bytes, kind: str, headers: Iterable[Tuple[str, str]] = ()) -> None:
        self.send_response(code)
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data: Any) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _redirect(self, where: str, headers: Iterable[Tuple[str, str]] = ()) -> None:
        self._send(303, b"", "text/plain; charset=utf-8", [("Location", where), *headers])

    def _login_page(self, code: int = 200, error: str = "", headers: Iterable[Tuple[str, str]] = ()) -> None:
        page = LOGIN_PAGE.read_text(encoding="utf-8")
        note = f'<p class="err" role="alert">{html.escape(error)}</p>' if error else ""
        self._send(code, page.replace("<!--error-->", note).encode("utf-8"), "text/html; charset=utf-8", headers)

    # ── ai đang gọi ──

    def _host(self) -> str:
        return (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()

    def _allowed(self) -> bool:
        # Chặn DNS rebinding: tên miền lạ trỏ về 127.0.0.1 thì không mở được bảng.
        if self._host() in self.server.hosts:
            return True
        self._json(403, {"error": "tên miền này không mở được bảng"})
        return False

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        if origin == "null":
            # Trình duyệt giấu Origin (chính sách referrer, tiện ích chặn…).
            # Sec-Fetch-Site do trình duyệt tự đặt, trang khác không giả được.
            return self.headers.get("Sec-Fetch-Site") == "same-origin"
        return (urllib.parse.urlsplit(origin).hostname or "") in self.server.hosts

    def _client(self) -> str:
        # Qua tunnel thì mọi yêu cầu tới từ cloudflared trên máy này; địa chỉ thật
        # nằm trong CF-Connecting-IP. Gọi thẳng từ máy khác thì không tin header ấy.
        address = self.client_address[0]
        forwarded = (self.headers.get("CF-Connecting-IP") or "").strip()
        return forwarded if forwarded and address in ("127.0.0.1", "::1") else address

    def _signed_in(self) -> bool:
        gate = self.server.gate
        if gate is None:
            return True
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie") or "")
        except CookieError:
            return False
        morsel = cookie.get(Gate.COOKIE)
        return bool(morsel and gate.valid(morsel.value))

    def _cookie(self, value: str, max_age: int) -> Tuple[str, str]:
        # Qua tên miền thật thì trình duyệt thấy https (Cloudflare giữ TLS): gắn Secure.
        secure = "" if self._host() in LOOPBACK else "; Secure"
        return ("Set-Cookie", f"{Gate.COOKIE}={value}; Max-Age={max_age}; Path=/; HttpOnly; SameSite=Lax{secure}")

    def _body(self, limit: int) -> bytes:
        length = min(max(_int(self.headers.get("Content-Length")), 0), limit)
        return self.rfile.read(length) if length else b""

    # ── đường dẫn ──

    def do_GET(self) -> None:
        if not self._allowed():
            return
        path = self.path.split("?", 1)[0]
        if path == "/login":
            if self.server.gate is None or self._signed_in():
                return self._redirect("/")
            return self._login_page()
        if not self._signed_in():
            if path.startswith("/api/"):
                return self._json(401, {"error": "cần đăng nhập"})
            return self._redirect("/login")
        if path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/etsy":
            self._json(200, build_board(self.server.listing, self.server.checks))
        elif path == "/api/images":
            self._json(200, build_images(self.server.flow))
        elif path == "/api/sku":
            self._json(200, build_sku(self.server.listing))
        elif path == "/api/stream":
            self._stream()
        elif path == "/api/me":
            self._json(200, {"gate": self.server.gate is not None})
        else:
            self._json(404, {"error": "không có trang này"})

    def do_POST(self) -> None:
        if not self._allowed():
            return
        if not self._same_origin():
            return self._json(403, {"error": "yêu cầu từ trang khác"})
        path = self.path.split("?", 1)[0]
        if path == "/login":
            return self._login()
        if path == "/logout":
            return self._redirect("/login" if self.server.gate else "/", [self._cookie("", 0)])
        if not self._signed_in():
            return self._json(401, {"error": "cần đăng nhập"})
        if path == "/api/check":
            return self._check()
        self._json(404, {"error": "không có trang này"})

    def _stream(self) -> None:
        feed = self.server.feed
        if not feed.join():
            return self._json(503, {"error": "đang quá đông người xem trực tiếp; trang tự làm mới 10 giây một lần"})
        try:
            self.send_response(200)
            for name, value in SECURITY_HEADERS.items():
                self.send_header(name, value)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            # Người xem không đọc nữa thì lần ghi kẹt quá 30 giây sẽ lỗi, thread được thả.
            self.connection.settimeout(30)
            self.wfile.write(b"retry: 3000\n\n")
            seen: Dict[str, int] = {}
            while True:
                news = feed.wait(seen, feed.heartbeat)
                # Phiên hết hạn hoặc đổi mật khẩu giữa chừng thì đóng luồng.
                if feed.stopped or not self._signed_in():
                    break
                if not news:
                    self.wfile.write(b": ping\n\n")
                for name, body in news:
                    self.wfile.write(b"event: " + name.encode("ascii") + b"\ndata: " + body + b"\n\n")
        except OSError:  # người xem đóng tab: BrokenPipe, ConnectionReset, hết giờ ghi
            pass
        finally:
            feed.leave()
            self.close_connection = True

    def _login(self) -> None:
        gate = self.server.gate
        if gate is None:
            return self._redirect("/")
        form = urllib.parse.parse_qs(self._body(4096).decode("utf-8", "replace"))
        token, wait = gate.attempt(self._client(), (form.get("password") or [""])[0])
        if token:
            return self._redirect("/", [self._cookie(token, Gate.TTL)])
        if wait:
            text = f"Sai quá nhiều lần. Thử lại sau {math.ceil(wait / 60)} phút."
            return self._login_page(429, text, [("Retry-After", str(wait))])
        self._login_page(401, "Sai mật khẩu.")

    def _check(self) -> None:
        # Chỉ nhận JSON: trang lạ muốn gửi JSON sang đây phải qua preflight,
        # mà máy chủ này không trả lời preflight.
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json(415, {"error": "chỉ nhận application/json"})
        try:
            body = json.loads(self._body(10_000) or b"{}")
        except ValueError:
            return self._json(400, {"error": "JSON hỏng"})
        job_id = str((body if isinstance(body, dict) else {}).get("job") or "")
        try:
            tasks = self.server.listing.copy_tasks()
        except (OSError, ValueError) as exc:
            return self._json(502, {"error": "không gọi được bản Listing: " + mask(exc)[:200]})
        now = datetime.now(timezone.utc)
        job = next((job_view(task, now) for task in tasks if str(task.get("id") or "") == job_id), None)
        if job is None:
            return self._json(404, {"error": f"không thấy việc {job_id}"})
        refused = self.server.checks.start(job)
        if refused:
            return self._json(409, {"error": refused})
        self._json(202, {"ok": True})


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ── lệnh ──────────────────────────────────────────────────────────────


def _read_new_password() -> str:
    if sys.stdin.isatty():
        first = getpass.getpass("Mật khẩu mới: ")
        if getpass.getpass("Gõ lại: ") != first:
            raise SystemExit("Hai lần gõ không khớp.")
        return first
    return sys.stdin.readline().strip()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m flow_web.board",
        description="Bảng điều khiển HaviGroup: đăng Etsy, tạo ảnh, SKU & thuộc tính, mở trong trình duyệt.",
    )
    parser.add_argument("--listing-base", "--base", default=DEFAULT_BASE, help="địa chỉ bản Listing (mặc định %(default)s)")
    parser.add_argument("--flow-base", default=DEFAULT_FLOW_BASE, help="địa chỉ flow-v2 (mặc định %(default)s)")
    parser.add_argument(
        "--flow-state-file", help="data/state.json của flow-v2 trên cùng máy: bảng thấy job đổi sau ~2 giây"
    )
    parser.add_argument("--port", type=int, default=8765, help="cổng trên máy này (mặc định %(default)s)")
    parser.add_argument("--password-file", help="tệp chứa mã băm mật khẩu; có tệp này thì phải đăng nhập")
    parser.add_argument(
        "--host-name", action="append", default=[], help="tên miền được mở bảng, ví dụ phongdzso1tg.phonh.io.vn"
    )
    parser.add_argument("--no-open", action="store_true", help="không tự mở trình duyệt")
    parser.add_argument("--hash-password", action="store_true", help="đọc mật khẩu từ stdin, in mã băm rồi thoát")
    args = parser.parse_args(argv)

    if args.hash_password:
        password = _read_new_password()
        if len(password) < 6:
            print("Mật khẩu ngắn quá (ít nhất 6 ký tự).", file=sys.stderr)
            return 2
        print(hash_password(password))
        return 0

    gate = None
    if args.password_file:
        try:
            gate = Gate(Path(args.password_file).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            print(f"Không đọc được tệp mật khẩu {args.password_file}: {exc}", file=sys.stderr)
            return 2
    if args.host_name and gate is None:
        print("Mở bảng bằng tên miền thì phải có --password-file.", file=sys.stderr)
        return 2

    listing = ListingApi(args.listing_base)
    flow = FlowApi(args.flow_base, jobs_file=JobsFile(args.flow_state_file) if args.flow_state_file else None)
    try:
        server = BoardServer(("127.0.0.1", args.port), listing, flow, gate=gate, hosts=args.host_name)
    except OSError as exc:
        print(f"Không mở được cổng {args.port}: {exc}. Thử --port khác.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    names = ", ".join(f"https://{name}/" for name in args.host_name)
    print(f"Bảng điều khiển: {url}{'  ·  ' + names if names else ''}   (Ctrl+C để tắt)", flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã tắt bảng.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
