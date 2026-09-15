import json
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone

from flow_web.listing_board import (
    Checks,
    build_board,
    card_views,
    job_view,
    machine_view,
)
from flow_web.listing_watch import ListingApi
from flow_web.review_lister import STATUS_FILE

NOW = datetime(2026, 9, 11, 3, 0, tzinfo=timezone.utc)


def ago(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat()


def task(task_id, card, status, machine="etsy-vn31", minutes=30, saved=True, error="", images=9):
    done = status in ("completed", "failed")
    return {
        "id": task_id,
        "card_id": card,
        "status": status,
        "claimed_machine_id": machine,
        "machine_id": machine,
        "sku": "SKU-" + card,
        "image_count": images,
        "title": "Idea 4",
        "card_url": "https://erp/app/task/" + card,
        "account_id": "etsy---vn31",
        "attempts": 1,
        "created_at": ago(minutes),
        "started_at": ago(minutes - 1) if status != "queued" else None,
        "finished_at": ago(minutes - 3) if done else None,
        "error": error,
        "result": {"draftSaved": saved, "message": "Đã lưu Etsy Draft bằng a.b@gmail.com"} if status == "completed" else {},
    }


def machine(machine_id, seen_s=10, online=True):
    return {
        "id": machine_id,
        "label": machine_id.upper(),
        "online": online,
        "last_seen": (NOW - timedelta(seconds=seen_s)).isoformat(),
        "agent_version": "2.11.1",
        "etsy_extension_version": "2.11.49",
        "etsy_profile": "someone@gmail.com",
        "computer_name": "DESKTOP-1",
        "tailscale_ip": "100.1.1.1",
    }


def lister(cards, minutes=2, errors=()):
    at = (NOW - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"at": at, "every": 300, "cards": cards, "errors": list(errors), "ledger": {}}


class FakeApi:
    base = "http://listing"

    def __init__(self, tasks=(), machines=(), status=None, status_error=None):
        self.tasks = list(tasks)
        self._machines = list(machines)
        self.status = status if status is not None else lister([])
        self.status_error = status_error
        self.asked_status = None

    def copy_tasks(self):
        return list(self.tasks)

    def machines(self):
        return list(self._machines)

    def lister_status(self, name):
        self.asked_status = name
        if self.status_error:
            raise self.status_error
        return self.status


class ViewTest(unittest.TestCase):
    def test_job_hides_emails_and_names_its_state(self):
        done = job_view(task("j1", "TASK-1", "completed"), NOW)
        self.assertEqual((done["label"], done["tone"], done["images"]), ("xong", "ok", 9))
        self.assertIn("<email>", done["message"])
        self.assertNotIn("@", json.dumps(done))
        failed = job_view(task("j2", "TASK-2", "failed", error="AgentError: không có ảnh"), NOW)
        self.assertEqual((failed["tone"], failed["error"]), ("bad", "AgentError: không có ảnh"))
        unsaved = job_view(task("j3", "TASK-3", "completed", saved=False), NOW)
        self.assertEqual(unsaved["tone"], "bad")
        self.assertIn("draftSaved", unsaved["error"])
        queued = job_view(task("j4", "TASK-4", "queued", minutes=12), NOW)
        self.assertEqual(queued["wait_s"], 12 * 60)

    def test_card_follows_its_latest_run(self):
        jobs = [
            job_view(task("old", "TASK-1", "failed", minutes=90, error="hỏng"), NOW),
            job_view(task("new", "TASK-1", "completed", minutes=20), NOW),
        ]
        (card,) = card_views([{"task": "TASK-1", "state": "done", "title": "Idea 4"}], jobs)
        self.assertEqual((card["stage"], card["tone"], card["runs"], card["job"]), (3, "ok", 2, "new"))
        self.assertTrue(card["can_check"])
        self.assertEqual(card["note"], "")

    def test_card_waiting_for_declaration_says_what_is_missing(self):
        (card,) = card_views([{"task": "TASK-9", "state": "waiting", "note": "thiếu account, copysku"}], [])
        self.assertEqual((card["stage"], card["tone"], card["label"]), (0, "wait", "chờ khai"))
        self.assertEqual(card["note"], "thiếu account, copysku")
        self.assertFalse(card["can_check"])

    def test_ledger_stands_in_when_the_queue_forgot_the_run(self):
        # Bản Listing khởi động lại thì hàng đợi trong RAM mất; sổ lister còn.
        (card,) = card_views(
            [{"task": "TASK-5", "state": "done", "queue_task_id": "etsy-copy-x", "machine_id": "etsy-vn33", "image_count": 6, "at": "2026-09-10 17:50:13"}],
            [],
        )
        self.assertEqual((card["stage"], card["tone"], card["machine"], card["images"]), (3, "ok", "etsy-vn33", 6))
        self.assertEqual(card["updated_at"], "2026-09-10T10:50:13+00:00")

    def test_run_whose_card_left_the_review_column_still_shows(self):
        cards = card_views([], [job_view(task("j", "TASK-OLD", "completed"), NOW)])
        self.assertEqual([(c["task"], c["in_review"]) for c in cards], [("TASK-OLD", False)])

    def test_card_the_lister_moved_to_done_says_so(self):
        # Từ 11/09/2026 lưu nháp xong thì lister tự chuyển thẻ sang Hoàn thành.
        # Thẻ rời cột vì thế là đường bình thường, không phải chuyện lạ.
        jobs = [job_view(task("j1", "TASK-MOVED", "completed"), NOW), job_view(task("j2", "TASK-LEFT", "completed"), NOW)]
        ledger = {"TASK-MOVED": {"state": "done", "draft_saved": True, "closed_at": "2026-09-11T02:59:00Z"}}
        cards = {c["task"]: c for c in card_views([{"task": "TASK-NOW", "state": "done", "closed_at": "2026-09-11T02:59:30Z"}], jobs, ledger)}
        self.assertEqual((cards["TASK-MOVED"]["in_review"], cards["TASK-MOVED"]["closed"]), (False, True))
        self.assertEqual((cards["TASK-LEFT"]["in_review"], cards["TASK-LEFT"]["closed"]), (False, False))
        # Chuyển ngay trong lượt quét vừa rồi: tệp trạng thái vẫn liệt kê thẻ ở cột review.
        self.assertEqual((cards["TASK-NOW"]["in_review"], cards["TASK-NOW"]["closed"]), (True, True))

    def test_card_whose_draft_was_not_saved_is_broken(self):
        (card,) = card_views([{"task": "TASK-U", "state": "unsaved", "queue_task_id": "etsy-copy-u"}], [])
        self.assertEqual((card["stage"], card["tone"], card["label"]), (2, "bad", "xong, không lưu nháp"))

    def test_card_that_would_not_move_to_done_asks_for_a_person(self):
        jobs = [job_view(task("j", "TASK-E", "completed"), NOW)]
        (card,) = card_views([{"task": "TASK-E", "state": "done", "close_error": "ERP từ chối UpdateTaskStatus (HTTP 500)."}], jobs)
        self.assertEqual((card["stage"], card["tone"], card["label"]), (3, "bad", "chưa sang Hoàn thành"))
        self.assertIn("HTTP 500", card["note"])
        self.assertFalse(card["closed"])

    def test_broken_cards_come_first(self):
        cards = card_views(
            [{"task": "TASK-W", "state": "waiting"}, {"task": "TASK-D", "state": "done"}],
            [job_view(task("j", "TASK-F", "failed"), NOW)],
        )
        self.assertEqual([card["task"] for card in cards], ["TASK-F", "TASK-D", "TASK-W"])

    def test_machines(self):
        jobs = [job_view(task("j", "TASK-1", "in_progress", machine="etsy-vn33"), NOW)]
        busy = machine_view(machine("etsy-vn33"), NOW, jobs)
        self.assertEqual((busy["online"], busy["tone"], busy["busy"]), (True, "run", "TASK-1"))
        silent = machine_view(machine("etsy-vn34", seen_s=400), NOW, jobs)
        self.assertEqual((silent["online"], silent["tone"]), (False, "bad"))
        retired = machine_view(machine("etsy-vn32", seen_s=4000), NOW, jobs)
        self.assertEqual((retired["tone"], retired["retired"]), ("off", "acc32 đã bỏ"))
        self.assertNotIn("@", json.dumps([busy, silent, retired]))


class BoardTest(unittest.TestCase):
    def test_alerts_name_what_needs_a_person(self):
        api = FakeApi(
            tasks=[
                task("a", "TASK-1", "failed", minutes=200, error="AgentError: cũ"),
                task("b", "TASK-1", "completed", minutes=100),
                task("c", "TASK-2", "failed", minutes=60, error="AgentError: không có ảnh"),
                task("d", "TASK-3", "queued", minutes=15),
            ],
            machines=[machine("etsy-vn31"), machine("etsy-vn34", seen_s=900), machine("etsy-vn32", seen_s=9000)],
            status=lister([{"task": "TASK-7", "state": "waiting", "note": "thiếu copysku"}], minutes=20),
        )
        board = build_board(api, now=NOW)
        texts = [alert["text"] for alert in board["alerts"]]
        self.assertTrue(any("Review Lister im 20 phút" in text for text in texts))
        self.assertTrue(any(text.startswith("TASK-2: hỏng trên etsy-vn31") for text in texts))
        self.assertTrue(any("TASK-3 chờ etsy-vn31" in text for text in texts))
        self.assertTrue(any("ETSY-VN34 mất liên lạc 15 phút" in text for text in texts))
        self.assertFalse(any("TASK-1" in text or "VN32" in text or "TASK-7" in text for text in texts))
        self.assertEqual(api.asked_status, STATUS_FILE)
        kpi = board["kpi"]
        self.assertEqual((kpi["review"], kpi["declare"], kpi["running"], kpi["drafts"], kpi["broken"]), (1, 1, 1, 1, 1))
        self.assertEqual((kpi["machines_on"], kpi["machines"]), (1, 2))

    def test_card_not_yet_checked_is_not_counted_as_waiting_for_declaration(self):
        api = FakeApi(status=lister([
            {"task": "TASK-A", "state": "waiting", "note": "thiếu copysku"},
            {"task": "TASK-B", "state": "unchecked", "note": "chưa tới lượt soi"},
        ]))
        kpi = build_board(api, now=NOW)["kpi"]
        self.assertEqual((kpi["review"], kpi["declare"], kpi["unchecked"]), (2, 1, 1))

    def test_board_reads_the_ledger_to_tell_moved_cards(self):
        status = lister([])
        status["ledger"] = {"TASK-1": {"state": "done", "draft_saved": True, "closed_at": "2026-09-11T02:59:00Z"}}
        board = build_board(FakeApi(tasks=[task("j", "TASK-1", "completed")], status=status), now=NOW)
        self.assertEqual([(c["task"], c["closed"]) for c in board["cards"]], [("TASK-1", True)])

    def test_board_survives_a_missing_status_file(self):
        missing = urllib.error.HTTPError("http://listing/x", 404, "Not Found", {}, None)
        api = FakeApi(tasks=[task("j", "TASK-1", "completed")], status_error=missing)
        board = build_board(api, now=NOW)
        self.assertEqual(board["sources"], {"queue": "", "machines": "", "lister": "HTTP 404"})
        self.assertIn("chưa có tệp trạng thái", board["alerts"][0]["text"])
        self.assertIsNone(board["kpi"]["review"])
        self.assertEqual([card["task"] for card in board["cards"]], ["TASK-1"])

    def test_listing_api_reads_the_status_file_from_downloads(self):
        api = ListingApi("http://listing")
        calls = []
        api._call = lambda method, path, body=None: calls.append((method, path)) or {"machines": [{"id": "m"}]}
        api.lister_status(STATUS_FILE)
        self.assertEqual(api.machines(), [{"id": "m"}])
        self.assertEqual(calls[0], ("GET", "/files/downloads/review_lister_status.json"))


class ChecksTest(unittest.TestCase):
    def test_one_check_per_machine_and_the_result_lands_on_the_board(self):
        pending = []
        seen = []

        def runner(api, machine_id, sku, expected):
            seen.append((machine_id, sku, expected))
            return {"machine_id": machine_id, "sku": sku, "expected": expected, "photos": 9, "ok": True,
                    "listing_id": "42", "draft_url": "https://www.etsy.com/your/shops/me/listing-editor/edit/42"}

        checks = Checks(object(), runner=runner, spawn=pending.append)
        first = job_view(task("j1", "TASK-1", "completed"), NOW)
        second = job_view(task("j2", "TASK-2", "completed"), NOW)
        self.assertEqual(checks.start(first), "")
        self.assertIn("đang soát", checks.start(second))
        self.assertEqual(checks.get("j1")["state"], "running")
        pending.pop()()
        result = checks.get("j1")
        self.assertEqual((result["state"], result["ok"], result["photos"]), ("done", True, 9))
        self.assertIn("9/9 ảnh", result["text"])
        self.assertEqual(seen, [("etsy-vn31", "SKU-TASK-1", 9)])
        self.assertEqual(checks.start(second), "")

    def test_check_needs_a_saved_draft(self):
        checks = Checks(object(), runner=lambda *a: {}, spawn=lambda work: work())
        self.assertIn("chưa lưu", checks.start(job_view(task("j", "TASK-1", "failed"), NOW)))
        self.assertIn("chưa lưu", checks.start(job_view(task("k", "TASK-2", "completed", saved=False), NOW)))

    def test_runner_crash_shows_as_an_error_not_a_hang(self):
        def runner(*args):
            raise OSError("máy x@y.com không trả lời")

        checks = Checks(object(), runner=runner, spawn=lambda work: work())
        checks.start(job_view(task("j", "TASK-1", "completed"), NOW))
        result = checks.get("j")
        self.assertEqual(result["state"], "done")
        self.assertIn("<email>", result["error"])


if __name__ == "__main__":
    unittest.main()
