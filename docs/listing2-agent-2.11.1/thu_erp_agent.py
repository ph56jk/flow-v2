"""Chạy thử trọn vòng: hàng đợi ERP giả -> agent 2.11.1 -> extension Etsy giả.

Không chạm máy thật. Controller giả nghe ở 127.0.0.1:18001, bridge thật của
agent nghe ở 127.0.0.1:38421 như trên VM.
"""
import importlib.util, json, os, sys, tempfile, threading, time, unittest, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

AGENT_PATH = Path(sys.argv.pop(1))
spec = importlib.util.spec_from_file_location("agent", AGENT_PATH)
agent = importlib.util.module_from_spec(spec)
sys.modules["agent"] = agent
spec.loader.exec_module(agent)

WRONG_SKU = False
MACHINE = ["etsy-vn31"]
ACCOUNT = [""]
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000")  # đủ để khác rỗng


def make_erp_task(**over):
    payload = {
        "mode": "etsy_browser_copy", "jobId": "job-1", "cardId": "card-1",
        "cardUrl": "https://erp.example/c/card-1", "title": "", "sku": "SKU-ABC-01",
        "templateSourceSku": "SKU-MAU", "templateListingUrl": "", "templateListingId": "",
        "templateSearchQueries": ["SKU-MAU"], "templateSearchTerms": [],
        "imageUrls": ["/files/downloads/etsy-browser-copy/job-1/a.png", "/files/downloads/etsy-browser-copy/job-1/b.png"],
        "images": [
            {"rank": 1, "file_name": "a.png", "download_url": "/files/downloads/etsy-browser-copy/job-1/a.png", "mime_type": "image/png"},
            {"rank": 2, "file_name": "b.png", "download_url": "/files/downloads/etsy-browser-copy/job-1/b.png", "mime_type": "image/png"},
        ],
        "maxUploadImages": 9, "keepColorChart": True, "deleteExistingImages": True, "dryRun": False,
    }
    payload.update(over)
    machine = MACHINE[0]
    return {"id": "etsy-copy-1", "job_id": "job-1", "sku": payload["sku"], "card_id": "card-1", "machine_id": machine,
            "account_id": ACCOUNT[0],
            "card_url": payload["cardUrl"], "attempts": 1, "payload": payload}


def norm(value):
    return agent.erp_norm_machine(value)


class FakeController:
    """Lọc việc y như controller thật: tài khoản khớp từng chữ, máy ghim khác thì bỏ qua."""

    def __init__(self, erp_task, listing2_task=None):
        self.tasks = [dict(erp_task, status="queued")] if erp_task else []
        self.listing2_task = listing2_task
        self.calls, self.reports, self.listing2_reports = [], [], []
        outer = self

        def public(task):
            return {k: v for k, v in task.items() if k != "payload"}

        def snapshot(machine):
            m = norm(machine)
            tasks = [t for t in outer.tasks if not m or norm(t.get("machine_id")) in ("", m)]
            return {"ok": True, "queued": len([t for t in tasks if t["status"] == "queued"]),
                    "in_progress": len([t for t in tasks if t["status"] == "in_progress"]),
                    "tasks": [public(t) for t in tasks], "machine_id_filter": m}

        def claim(body):
            account = str(body.get("accountId") or "").strip().lower()
            account = "" if account == "default" else account
            machine = norm(body.get("machineId"))
            for t in outer.tasks:
                if t["status"] != "queued" or str(t.get("account_id") or "") != account:
                    continue
                if norm(t.get("machine_id")) and norm(t.get("machine_id")) != machine:
                    continue
                t["status"] = "in_progress"
                return t
            return None

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def _send(self, code, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code); self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            def do_GET(self):
                outer.calls.append(("GET", self.path))
                if self.path.startswith("/files/downloads/"):
                    return self._send(200, PNG, "image/png")
                url = urllib.parse.urlsplit(self.path)
                if url.path == "/api/etsy/browser-copy/queue":
                    q = urllib.parse.parse_qs(url.query)
                    return self._send(200, snapshot((q.get("machine_id") or [""])[0]))
                self._send(404, {"ok": False})
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                outer.calls.append(("POST", self.path, body))
                if self.path == "/api/listing2/machines/heartbeat":
                    return self._send(200, {"ok": True})
                if self.path == "/api/listing2/tasks/next":
                    return self._send(200, {"ok": True, "task": outer.listing2_task})
                if self.path == "/api/listing2/tasks/report":
                    outer.listing2_reports.append(body); return self._send(200, {"ok": True})
                if self.path == "/api/extension/etsy-browser-copy/next":
                    return self._send(200, {"ok": True, "task": claim(body)})
                if self.path == "/api/extension/etsy-browser-copy/report":
                    outer.reports.append(body); return self._send(200, {"ok": True})
                self._send(404, {"ok": False})

        self.server = ThreadingHTTPServer(("127.0.0.1", 18001), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown(); self.server.server_close()


def fake_etsy_extension(stop, seen, draft_saved=True):
    """Giả extension Etsy 2.11.49: poll bridge, tải ảnh, trả kết quả."""
    base = f"http://127.0.0.1:{agent.BRIDGE_PORT}"
    hdr = {"X-Listing2-Bridge": agent.BRIDGE_HEADER_VALUE}
    while not stop.is_set():
        try:
            req = urllib.request.Request(f"{base}/api/poll?role=etsy&build={agent.EXTENSION_VERSION}&profileEmail=etsy@example.com", headers=hdr)
            cmd = json.loads(urllib.request.urlopen(req, timeout=5).read())["command"]
        except Exception:
            time.sleep(0.2); continue
        kind = cmd.get("type")
        if kind in ("wait", None, ""):
            time.sleep(0.2); continue
        seen.append(cmd)
        if kind == "resolve_template_sku":
            result = {"exactSku": True, "sourceSku": cmd["sourceSku"], "actualSku": ("SKU-KHAC" if WRONG_SKU else cmd["sourceSku"]), "listingId": "4455667788"}
        elif kind == "create_draft":
            sizes = [len(urllib.request.urlopen(urllib.request.Request(f["url"], headers=hdr), timeout=5).read()) for f in cmd["files"]]
            cmd["_sizes"] = sizes
            result = {"draftSaved": draft_saved, "draftUrl": "https://www.etsy.com/your/shops/me/listing-editor/edit/999", "listingId": "999"}
        else:
            result = {}
        body = json.dumps({"role": "etsy", "taskId": cmd["taskId"], "commandId": cmd["commandId"], "ok": True, "result": result}).encode()
        urllib.request.urlopen(urllib.request.Request(f"{base}/api/result", data=body, headers={**hdr, "Content-Type": "application/json"}, method="POST"), timeout=5).read()
        time.sleep(0.2)


def make_agent(tmp):
    cfg = agent.AgentConfig(backend="http://127.0.0.1:18001", machine_id="etsy-vn31", machine_label="ETSY - VN31",
                            tailscale_ip="", root=Path(tmp), trello_email="trello@example.com", etsy_email="etsy@example.com")
    a = agent.Listing2Agent(cfg)
    a.stop_isolated_extension_workers = lambda roles: None
    a.start_extension_workers = lambda **kw: (_ for _ in ()).throw(AssertionError("không được mở worker Chrome"))
    return a


class ThuERP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["HOME"] = self.tmp  # ảnh tạm rơi vào ~/Downloads/Listing2 trong thư mục tạm

    def run_flow(self, erp_task, draft_saved=True, listing2_task=None):
        ctl = FakeController(erp_task, listing2_task)
        stop, seen = threading.Event(), []
        t = threading.Thread(target=fake_etsy_extension, args=(stop, seen, draft_saved), daemon=True); t.start()
        a = make_agent(self.tmp)
        real_process, self.processed = a.process, []

        def process(task):
            # Việc Trello giả coi như xong ngay; việc ERP chạy thật qua bridge.
            self.processed.append(task.get("id"))
            if listing2_task and task.get("id") == listing2_task["id"]:
                return None
            return real_process(task)

        a.process = process
        try:
            rc = a.run_once()
        finally:
            stop.set(); t.join(2); ctl.close()
        return rc, ctl, seen

    # --- hàm phụ ---
    def test_vai_tro_extension(self):
        self.assertEqual(agent.required_extension_roles({"erp_browser_copy": True}), {"etsy"})
        self.assertEqual(agent.required_extension_roles({"trello_url": "https://trello.com/c/x"}), {"trello", "etsy"})
        self.assertEqual(agent.required_extension_roles({"verify_only": True}), {"etsy"})

    def test_link_anh_thanh_tuyet_doi(self):
        items = agent.erp_image_urls(make_erp_task()["payload"], "http://h:8001/")
        self.assertEqual([i["url"] for i in items], ["http://h:8001/files/downloads/etsy-browser-copy/job-1/a.png",
                                                     "http://h:8001/files/downloads/etsy-browser-copy/job-1/b.png"])

    def test_thieu_mau_thi_tu_choi(self):
        t = make_erp_task(templateSourceSku="", templateSearchQueries=[], templateListingId="")
        with self.assertRaises(agent.AgentError):
            agent.erp_agent_task(make_agent(self.tmp).config, t, [{"path": "x", "name": "x", "mime": "image/png"}])

    def test_bridge_trello_khong_doi(self):
        b = agent.ExtensionBridge({"id": "t1", "payload": {"trello_url": "https://trello.com/c/x"}})
        self.assertEqual(b.poll("trello")["command"]["type"], "read_trello")
        self.assertEqual(b.poll("etsy")["command"]["type"], "wait")

    # --- trọn vòng ---
    def test_tron_vong_tim_mau_theo_sku_roi_tao_draft(self):
        rc, ctl, seen = self.run_flow(make_erp_task())
        self.assertEqual(rc, 0)
        self.assertEqual([c["type"] for c in seen], ["resolve_template_sku", "create_draft"])
        draft = seen[1]
        self.assertEqual(draft["fields"]["sku"], "SKU-ABC-01")
        self.assertEqual(draft["url"], "https://www.etsy.com/your/shops/me/listing-editor/copy/4455667788")
        self.assertEqual(len(draft["files"]), 2)
        self.assertEqual(draft["_sizes"], [len(PNG), len(PNG)])
        self.assertTrue(draft["saveDraft"])
        self.assertEqual(len(ctl.reports), 1)
        rep = ctl.reports[0]
        self.assertEqual(rep["taskId"], "etsy-copy-1")
        self.assertEqual(rep["status"], "completed")
        self.assertEqual(rep["result"]["draftUrl"], "https://www.etsy.com/your/shops/me/listing-editor/edit/999")
        self.assertEqual(ctl.listing2_reports, [], "việc ERP không được báo vào sổ Trello")
        nxt = [c for c in ctl.calls if c[1] == "/api/extension/etsy-browser-copy/next"][0][2]
        self.assertEqual(nxt["machineId"], "etsy-vn31")
        self.assertEqual(nxt["accountId"], "")

    def test_mau_lech_sku_thi_dung(self):
        global WRONG_SKU
        WRONG_SKU = True
        try:
            rc, ctl, seen = self.run_flow(make_erp_task())
        finally:
            WRONG_SKU = False
        self.assertEqual([c["type"] for c in seen], ["resolve_template_sku"])
        self.assertEqual(ctl.reports[0]["status"], "failed")

    def test_viec_khong_ghim_may_thi_khong_nhan(self):
        MACHINE[0] = ""
        try:
            rc, ctl, seen = self.run_flow(make_erp_task())
        finally:
            MACHINE[0] = "etsy-vn31"
        self.assertEqual(seen, [], "không được gửi lệnh nào cho extension Etsy")
        self.assertFalse([c for c in ctl.calls if c[1] == "/api/extension/etsy-browser-copy/next"], "không được rút việc")
        self.assertEqual(ctl.reports, [])
        self.assertEqual(ctl.tasks[0]["status"], "queued", "việc phải nằm nguyên trong hàng đợi")
        self.assertFalse([c for c in ctl.calls if c[0] == "GET" and c[1].startswith("/files/")], "không tải ảnh")

    def test_chot_chan_viec_khong_ghim_may_thi_khong_mo_etsy(self):
        MACHINE[0] = ""
        try:
            task = make_erp_task()
        finally:
            MACHINE[0] = "etsy-vn31"
        ctl = FakeController(None)
        try:
            make_agent(self.tmp).process_erp(task)
        finally:
            ctl.close()
        self.assertEqual(ctl.reports[0]["status"], "failed")
        self.assertIn("machine_id", ctl.reports[0]["result"]["error"])
        self.assertFalse([c for c in ctl.calls if c[0] == "GET" and c[1].startswith("/files/")], "không tải ảnh")

    def test_the_mang_nhan_tai_khoan_duoc_nhan(self):
        ACCOUNT[0] = "acc31"
        try:
            rc, ctl, seen = self.run_flow(make_erp_task())
        finally:
            ACCOUNT[0] = ""
        self.assertEqual([c["type"] for c in seen], ["resolve_template_sku", "create_draft"])
        self.assertEqual(ctl.reports[0]["status"], "completed")
        nxt = [c for c in ctl.calls if c[1] == "/api/extension/etsy-browser-copy/next"]
        self.assertEqual([c[2]["accountId"] for c in nxt], ["acc31"])

    def test_viec_cua_may_khac_thi_khong_hoi_next(self):
        MACHINE[0] = "etsy-vn32"
        try:
            rc, ctl, seen = self.run_flow(make_erp_task())
        finally:
            MACHINE[0] = "etsy-vn31"
        self.assertEqual(seen, [])
        self.assertFalse([c for c in ctl.calls if c[1] == "/api/extension/etsy-browser-copy/next"],
                         "không hỏi next: hỏi là controller ghi máy này vào đội Etsy")
        self.assertEqual(ctl.tasks[0]["status"], "queued")

    def test_viec_khong_ghim_may_duoc_nhan_khi_bat_env(self):
        MACHINE[0] = ""
        os.environ["LISTING2_ERP_ACCEPT_UNPINNED"] = "1"
        try:
            rc, ctl, seen = self.run_flow(make_erp_task())
        finally:
            MACHINE[0] = "etsy-vn31"
            del os.environ["LISTING2_ERP_ACCEPT_UNPINNED"]
        self.assertEqual(ctl.reports[0]["status"], "completed")

    def test_tron_vong_co_san_id_mau(self):
        rc, ctl, seen = self.run_flow(make_erp_task(templateListingId="1234567890", templateSourceSku="", templateSearchQueries=[]))
        self.assertEqual([c["type"] for c in seen], ["create_draft"])
        self.assertEqual(seen[0]["url"], "https://www.etsy.com/your/shops/me/listing-editor/copy/1234567890")
        self.assertEqual(ctl.reports[0]["status"], "completed")

    def test_etsy_khong_luu_draft_thi_bao_failed(self):
        rc, ctl, seen = self.run_flow(make_erp_task(), draft_saved=False)
        self.assertEqual(ctl.reports[0]["status"], "failed")
        self.assertTrue(ctl.reports[0]["result"]["message"])

    def test_hang_doi_erp_trong_thi_khong_lam_gi(self):
        rc, ctl, seen = self.run_flow(None)
        self.assertEqual(rc, 0)
        self.assertEqual(seen, [])
        self.assertEqual(ctl.reports, [])
        self.assertFalse([c for c in ctl.calls if c[1] == "/api/extension/etsy-browser-copy/next"])

    def test_dong_bo_cot_trello_xong_van_rut_viec_erp(self):
        # Controller giao việc đồng bộ cột gần như mỗi phút. Dừng sau việc đó
        # là hàng đợi ERP không bao giờ tới lượt (soi được trên vn31 ngày 10/09).
        sync = {"id": "listing2-sync-etsy-vn31", "payload": {"background_sync": True}}
        rc, ctl, seen = self.run_flow(make_erp_task(), listing2_task=sync)
        self.assertEqual(rc, 0)
        self.assertEqual(self.processed, ["listing2-sync-etsy-vn31", "etsy-copy-1"])
        self.assertEqual([c["type"] for c in seen], ["resolve_template_sku", "create_draft"])
        self.assertEqual(ctl.reports[0]["status"], "completed")

    def test_the_trello_that_thi_khong_hoi_erp(self):
        card = {"id": "listing2-the-that", "payload": {"trello_url": "https://trello.com/c/x"}}
        rc, ctl, seen = self.run_flow(make_erp_task(), listing2_task=card)
        self.assertEqual(self.processed, ["listing2-the-that"])
        self.assertFalse([c for c in ctl.calls if c[0] == "GET" and c[1].startswith("/api/etsy/browser-copy/queue")],
                         "thẻ Trello thật chạy trước, lượt này không đụng hàng ERP")
        self.assertEqual(ctl.tasks[0]["status"], "queued")

    def test_tat_hang_doi_erp_bang_env(self):
        os.environ["LISTING2_ERP_QUEUE"] = "0"
        try:
            rc, ctl, seen = self.run_flow(make_erp_task())
        finally:
            del os.environ["LISTING2_ERP_QUEUE"]
        self.assertFalse([c for c in ctl.calls if c[1] == "/api/extension/etsy-browser-copy/next"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
