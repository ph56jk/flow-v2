import contextlib
import http.client
import io
import json
import tempfile
import threading
import time
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from flow_web import board as board_module
from flow_web.board import PUSH_ANYWAY, BoardServer, Feed, Gate, hash_password, main, verify_password
from flow_web.listing_board import Checks

NOW = datetime(2026, 9, 11, 3, 0, tzinfo=timezone.utc)
FAST = 1000  # vòng băm ít cho test nhanh; bản thật dùng HASH_ITERATIONS


def task(task_id, card, status):
    return {
        "id": task_id,
        "card_id": card,
        "status": status,
        "claimed_machine_id": "etsy-vn31",
        "sku": "SKU-" + card,
        "image_count": 9,
        "created_at": (NOW - timedelta(minutes=30)).isoformat(),
        "started_at": (NOW - timedelta(minutes=29)).isoformat(),
        "finished_at": (NOW - timedelta(minutes=27)).isoformat(),
        "result": {"draftSaved": True},
    }


class FakeListing:
    base = "http://listing"

    def __init__(self):
        # Máy chủ tính theo giờ thật, không theo NOW: máy phải vừa báo về theo giờ thật.
        self.live = {"id": "etsy-vn31", "online": True, "last_seen": datetime.now(timezone.utc).isoformat()}

    def copy_tasks(self):
        return [task("j1", "TASK-1", "completed")]

    def machines(self):
        return [self.live]

    def lister_status(self, name):
        return {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "every": 300, "cards": []}


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class RunningFlow:
    base = "http://flow"

    def state(self):
        return {"jobs": [{"id": "g1", "status": "running", "input": {"erp_task_id": "TASK-7"}}]}


def sse(resp):
    """Từng mục của luồng SSE: {"event": …, "data": …}, hoặc {"comment": …} cho dòng giữ kết nối."""
    item = {}
    while True:
        line = resp.readline()
        if not line:
            return
        line = line.decode("utf-8").rstrip("\r\n")
        if line.startswith(":"):
            yield {"comment": line[1:].strip()}
        elif line:
            field, _, value = line.partition(":")
            item[field] = value[1:] if value.startswith(" ") else value
        elif item:
            yield item
            item = {}


def read_events(items, names):
    """Đọc tới khi mỗi phần trong ``names`` có ít nhất một bản; trả bản cuối của từng phần."""
    got = {}
    for item in items:
        if "event" in item:
            got[item["event"]] = json.loads(item["data"])
        if names <= set(got):
            return got
    raise AssertionError(f"luồng đóng khi mới có {sorted(got)}")


class PasswordTest(unittest.TestCase):
    def test_file_keeps_a_hash_not_the_password(self):
        stored = hash_password("phong-test", iterations=FAST)
        self.assertNotIn("phong-test", stored)
        self.assertTrue(verify_password(stored, "phong-test"))
        self.assertFalse(verify_password(stored, "phong-tesT"))
        self.assertFalse(verify_password("rác", "phong-test"))
        with self.assertRaises(ValueError):
            Gate("phong-test")

    def test_session_expires_and_dies_with_a_new_password(self):
        clock = Clock()
        gate = Gate(hash_password("mot", iterations=FAST), clock=clock)
        token = gate.issue()
        self.assertTrue(gate.valid(token))
        self.assertFalse(Gate(hash_password("hai", iterations=FAST), clock=clock).valid(token))
        expires, _, signature = token.partition(".")
        self.assertFalse(gate.valid(f"{int(expires) + 86400}.{signature}"))
        self.assertFalse(gate.valid("abc"))
        clock.now += Gate.TTL + 1
        self.assertFalse(gate.valid(token))

    def test_guessing_locks_that_client_then_everyone(self):
        clock = Clock()
        gate = Gate(hash_password("dung", iterations=FAST), clock=clock)
        for _ in range(Gate.PER_CLIENT):
            self.assertEqual(gate.attempt("1.1.1.1", "sai"), ("", 0))
        token, wait = gate.attempt("1.1.1.1", "dung")
        self.assertEqual(token, "")
        self.assertEqual(wait, Gate.WINDOW)
        self.assertTrue(gate.attempt("2.2.2.2", "dung")[0])
        clock.now += Gate.WINDOW + 1
        self.assertTrue(gate.attempt("1.1.1.1", "dung")[0])
        for index in range(Gate.OVERALL):
            gate.attempt(f"10.0.0.{index}", "sai")
        self.assertGreater(gate.attempt("3.3.3.3", "dung")[1], 0)


class FeedTest(unittest.TestCase):
    """Nhịp nền của luồng trực tiếp, chạy tay từng nhịp."""

    def setUp(self):
        self.now = [0.0]
        self.data = {
            "img": {"at": "t0", "kpi": {"active": 1}, "jobs": [{"id": "g1", "status": "running", "run_s": 5}]},
            "etsy": {"at": "t0", "lister": {"at": "l0", "age_s": 3}, "jobs": []},
        }
        self.builds = {"img": 0, "etsy": 0}
        self.started = []
        self.feed = Feed(
            {"img": (1, self.builder("img")), "etsy": (5, self.builder("etsy"))},
            clock=lambda: self.now[0],
            spawn=self.started.append,
        )
        self.assertTrue(self.feed.join())

    def builder(self, name):
        def build():
            self.builds[name] += 1
            value = self.data[name]
            if isinstance(value, Exception):
                raise value
            return json.loads(json.dumps(value))

        return build

    def news(self, seen):
        return {name: json.loads(body) for name, body in self.feed.wait(seen, 0)}

    def beat(self, seconds=1):
        self.now[0] += seconds
        self.feed.step()

    def test_first_beat_sends_both_parts_then_only_what_changed(self):
        seen = {}
        self.feed.step()
        self.assertEqual(set(self.news(seen)), {"img", "etsy"})
        self.beat()
        self.assertEqual(self.news(seen), {})
        self.data["img"]["jobs"][0]["status"] = "completed"
        self.beat()
        self.assertEqual(self.news(seen)["img"]["jobs"][0]["status"], "completed")
        self.assertEqual(self.news({})["etsy"]["lister"]["at"], "l0")  # người mới vào nhận đủ hai phần

    def test_clock_only_changes_are_not_news(self):
        seen = {}
        self.feed.step()
        self.news(seen)
        self.data["img"]["at"] = "t1"
        self.data["img"]["jobs"][0]["run_s"] = 6
        self.data["etsy"]["at"] = "t1"
        self.data["etsy"]["lister"]["age_s"] = 9
        self.beat(5)
        self.assertEqual(self.news(seen), {})
        # Lâu không gửi thì vẫn gửi lại, để số giây trên bảng không đứng im.
        self.beat(PUSH_ANYWAY)
        self.assertEqual(set(self.news(seen)), {"img", "etsy"})

    def test_each_part_on_its_own_beat(self):
        self.feed.step()
        for _ in range(4):
            self.beat()
        self.assertEqual(self.builds, {"img": 5, "etsy": 1})
        self.beat()
        self.assertEqual(self.builds, {"img": 6, "etsy": 2})

    def test_broken_part_keeps_the_last_good_copy(self):
        seen = {}
        self.feed.step()
        self.news(seen)
        self.data["img"] = RuntimeError("lỗi lạ trong build_images")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.beat()
        self.assertIn("lỗi lạ", err.getvalue())
        self.assertEqual(self.news(seen), {})
        self.assertEqual(self.news({})["img"]["kpi"], {"active": 1})

    def test_one_background_beat_for_all_viewers_and_a_cap(self):
        self.feed.limit = 3
        self.assertTrue(self.feed.join())
        self.assertTrue(self.feed.join())
        self.assertFalse(self.feed.join())
        self.assertEqual(len(self.started), 1)
        self.feed.step()
        for _ in range(3):
            self.feed.leave()
        # Không ai xem: bỏ bản cũ, người sau chờ bản mới.
        self.assertEqual(self.feed.wait({}, 0), [])

    def test_wait_gives_up_after_the_heartbeat(self):
        started = time.monotonic()
        self.assertEqual(self.feed.wait({}, 0.05), [])
        self.assertGreaterEqual(time.monotonic() - started, 0.04)

    def test_background_beat_stops_when_nobody_watches(self):
        calls = []
        feed = Feed({"img": (0, lambda: calls.append(1) or {"n": len(calls)})})
        feed.tick = 0.01
        self.addCleanup(feed.stop)
        self.assertTrue(feed.join())
        self.assertTrue(feed.wait({}, 2))
        feed.leave()
        time.sleep(0.05)
        count = len(calls)
        time.sleep(0.1)
        self.assertEqual(len(calls), count)


class ServerCase(unittest.TestCase):
    gate = None
    hosts = ()

    def setUp(self):
        self.listing = FakeListing()
        runner = lambda api, machine_id, sku, expected: {"sku": sku, "machine_id": machine_id, "photos": 9, "expected": expected, "ok": True}
        self.server = BoardServer(
            ("127.0.0.1", 0),
            self.listing,
            None,
            Checks(self.listing, runner=runner, spawn=lambda work: work()),
            gate=self.gate,
            hosts=self.hosts,
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read().decode("utf-8")
        conn.close()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data

    def open_stream(self, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        conn.request("GET", "/api/stream", headers=headers or {})
        return conn.getresponse()


class OpenServerTest(ServerCase):
    """Không có tệp mật khẩu: máy dev, chỉ 127.0.0.1."""

    def test_page_and_board(self):
        code, _, page = self.call("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn("<title>Bảng điều khiển HaviGroup</title>", page)
        self.assertIn("new EventSource('/api/stream')", page)
        code, headers, body = self.call("GET", "/api/etsy")
        self.assertEqual(code, 200)
        self.assertIn("frame-ancestors 'none'", headers["content-security-policy"])
        # no-referrer làm trình duyệt gửi Origin: null cho mọi POST, kể cả cùng trang:
        # đăng nhập thật bị chặn "yêu cầu từ trang khác".
        self.assertEqual(headers["referrer-policy"], "same-origin")
        board = json.loads(body)
        self.assertEqual(board["jobs"][0]["id"], "j1")
        self.assertEqual(board["kpi"]["machines_on"], 1)

    def test_images_part(self):
        code, _, body = self.call("GET", "/api/images")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["sources"]["state"])  # máy chủ này không trỏ tới flow-v2

        class Flow:
            base = "http://flow"

            def state(self):
                return {"jobs": [{"id": "g1", "status": "running", "input": {"erp_task_id": "TASK-7"}}]}

        self.server.flow = Flow()
        board = json.loads(self.call("GET", "/api/images")[2])
        self.assertEqual((board["kpi"]["active"], board["jobs"][0]["task"]), (1, "TASK-7"))

    def test_stream_sends_both_parts_then_what_changed(self):
        self.server.feed.tick = 0.02
        resp = self.open_stream()
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.getheader("Content-Type").startswith("text/event-stream"))
        self.assertIsNone(resp.getheader("Content-Length"))
        self.assertIn("frame-ancestors 'none'", resp.getheader("Content-Security-Policy"))
        items = sse(resp)
        got = read_events(items, {"etsy", "img"})
        self.assertEqual(got["etsy"]["jobs"][0]["id"], "j1")
        self.assertTrue(got["img"]["sources"]["state"])  # máy chủ này không trỏ tới flow-v2
        self.server.flow = RunningFlow()
        got = read_events(items, {"img"})
        self.assertEqual((got["img"]["kpi"]["active"], got["img"]["jobs"][0]["task"]), (1, "TASK-7"))

    def test_quiet_stream_keeps_the_line_open(self):
        # Cloudflare cắt kết nối im quá 100 giây: không có gì mới thì gửi dòng chú thích.
        self.server.feed.tick = 0.02
        self.server.feed.heartbeat = 0.05
        items = sse(self.open_stream())
        read_events(items, {"etsy", "img", "sku"})
        self.assertEqual(next(items), {"comment": "ping"})

    def test_too_many_viewers_fall_back_to_polling(self):
        self.server.feed.limit = 0
        code, _, body = self.call("GET", "/api/stream")
        self.assertEqual(code, 503)
        self.assertIn("10 giây", json.loads(body)["error"])

    def test_check_goes_through_json_only(self):
        post = lambda body, kind="application/json": self.call("POST", "/api/check", body, {"Content-Type": kind})[0]
        self.assertEqual(post(b'{"job": "j1"}', kind="text/plain"), 415)
        self.assertEqual(post(b'{"job": "nope"}'), 404)
        self.assertEqual(post(b'{"job": "j1"}'), 202)
        board = json.loads(self.call("GET", "/api/etsy")[2])
        self.assertEqual(board["jobs"][0]["check"]["photos"], 9)
        self.assertEqual(board["cards"][0]["check"]["ok"], True)

    def test_foreign_host_is_refused(self):
        self.assertEqual(self.call("GET", "/api/etsy", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.call("GET", "/api/stream", headers={"Host": "evil.example"})[0], 403)
        headers = {"Host": "evil.example:8765", "Content-Type": "application/json"}
        self.assertEqual(self.call("POST", "/api/check", b'{"job": "j1"}', headers)[0], 403)

    def test_login_page_is_not_needed(self):
        self.assertEqual(self.call("GET", "/login")[:2][0], 303)


class GateServerTest(ServerCase):
    gate = Gate(hash_password("dung-roi", iterations=FAST))
    hosts = ("board.example",)

    def login(self, password, headers=None):
        body = urllib.parse.urlencode({"password": password})
        base = {"Content-Type": "application/x-www-form-urlencoded"}
        return self.call("POST", "/login", body, {**base, **(headers or {})})

    def setUp(self):
        self.gate.failures.clear()
        super().setUp()

    def test_everything_waits_behind_the_password(self):
        code, headers, _ = self.call("GET", "/")
        self.assertEqual((code, headers["location"]), (303, "/login"))
        self.assertEqual(self.call("GET", "/api/etsy")[0], 401)
        self.assertEqual(self.call("GET", "/api/images")[0], 401)
        self.assertEqual(self.call("POST", "/api/check", b'{"job": "j1"}', {"Content-Type": "application/json"})[0], 401)
        code, _, page = self.call("GET", "/login")
        self.assertEqual(code, 200)
        self.assertIn('name="password"', page)

    def test_wrong_then_right_password(self):
        code, _, page = self.login("sai")
        self.assertEqual(code, 401)
        self.assertIn("Sai mật khẩu", page)
        code, headers, _ = self.login("dung-roi")
        self.assertEqual((code, headers["location"]), (303, "/"))
        cookie = headers["set-cookie"]
        for part in ("HttpOnly", "SameSite=Lax", f"Max-Age={Gate.TTL}"):
            self.assertIn(part, cookie)
        self.assertNotIn("Secure", cookie)  # 127.0.0.1 là http
        session = {"Cookie": cookie.split(";", 1)[0]}
        self.assertEqual(self.call("GET", "/api/etsy", headers=session)[0], 200)
        self.assertEqual(self.call("GET", "/login", headers=session)[:1], (303,))
        self.assertEqual(self.call("GET", "/api/etsy", headers={"Cookie": "havi_board=1.abc"})[0], 401)

    def test_public_name_gets_a_secure_cookie(self):
        code, headers, _ = self.login("dung-roi", {"Host": "board.example"})
        self.assertEqual(code, 303)
        self.assertIn("; Secure", headers["set-cookie"])
        self.assertEqual(self.login("dung-roi", {"Host": "board.evil"})[0], 403)

    def test_lockout_follows_the_address_cloudflare_reports(self):
        for _ in range(Gate.PER_CLIENT):
            self.login("sai", {"CF-Connecting-IP": "1.2.3.4"})
        code, headers, page = self.login("dung-roi", {"CF-Connecting-IP": "1.2.3.4"})
        self.assertEqual(code, 429)
        self.assertIn("Thử lại sau", page)
        self.assertIn("retry-after", headers)
        self.assertEqual(self.login("dung-roi", {"CF-Connecting-IP": "5.6.7.8"})[0], 303)

    def test_cross_site_post_is_refused(self):
        self.assertEqual(self.login("dung-roi", {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.login("dung-roi", {"Origin": "null"})[0], 403)
        self.assertEqual(self.login("dung-roi", {"Origin": "null", "Sec-Fetch-Site": "cross-site"})[0], 403)
        cookie = self.login("dung-roi")[1]["set-cookie"].split(";", 1)[0]
        headers = {"Cookie": cookie, "Content-Type": "application/json", "Origin": "https://evil.example"}
        self.assertEqual(self.call("POST", "/api/check", b'{"job": "j1"}', headers)[0], 403)
        headers["Origin"] = "https://board.example"
        self.assertEqual(self.call("POST", "/api/check", b'{"job": "j1"}', headers)[0], 202)

    def test_browser_that_hides_origin_still_logs_in(self):
        # Origin: null mà Sec-Fetch-Site là same-origin thì vẫn là cùng trang.
        # Sec-Fetch-Site do trình duyệt tự đặt, trang khác không giả được.
        headers = {"Origin": "null", "Sec-Fetch-Site": "same-origin"}
        self.assertEqual(self.login("dung-roi", headers)[0], 303)

    def test_logout_clears_the_cookie(self):
        code, headers, _ = self.call("POST", "/logout")
        self.assertEqual((code, headers["location"]), (303, "/login"))
        self.assertIn("Max-Age=0", headers["set-cookie"])


class StreamGateTest(ServerCase):
    hosts = ("board.example",)

    def setUp(self):
        self.clock = Clock()
        self.gate = Gate(hash_password("dung-roi", iterations=FAST), clock=self.clock)
        super().setUp()
        self.server.feed.tick = 0.02
        self.server.feed.heartbeat = 0.05

    def test_stream_needs_a_session_and_ends_with_it(self):
        self.assertEqual(self.call("GET", "/api/stream")[0], 401)
        resp = self.open_stream({"Cookie": f"{Gate.COOKIE}={self.gate.issue()}"})
        self.assertEqual(resp.status, 200)
        items = sse(resp)
        read_events(items, {"etsy", "img"})
        # Phiên hết hạn giữa chừng: máy chủ đóng luồng ở nhịp kế tiếp.
        self.clock.now += Gate.TTL + 1
        self.assertLess(len(list(items)), 10)


class CommandTest(unittest.TestCase):
    def run_main(self, argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(stdin)), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_hash_password_prints_a_hash_only(self):
        code, out, _ = self.run_main(["--hash-password"], stdin="phong-test\r\n")
        self.assertEqual(code, 0)
        self.assertNotIn("phong-test", out)
        self.assertTrue(verify_password(out, "phong-test"))
        self.assertEqual(self.run_main(["--hash-password"], stdin="ngan\n")[0], 2)

    def test_public_name_needs_a_password_file(self):
        with mock.patch.object(board_module, "BoardServer") as server:
            code, _, err = self.run_main(["--host-name", "board.example", "--no-open"])
        self.assertEqual(code, 2)
        self.assertIn("--password-file", err)
        server.assert_not_called()

    def test_plain_password_file_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "password.txt"
            path.write_text("phong-test\n", encoding="utf-8")
            with mock.patch.object(board_module, "BoardServer") as server:
                code, _, err = self.run_main(["--password-file", str(path), "--no-open"])
        self.assertEqual(code, 2)
        self.assertIn("pbkdf2_sha256", err)
        server.assert_not_called()


if __name__ == "__main__":
    unittest.main()
