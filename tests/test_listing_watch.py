"""Lệnh theo dõi đăng Etsy: đọc bộ đếm ảnh, tìm bản nháp, in trạng thái.

Không gọi mạng: API giả trả kết quả dựng theo kết quả thật ngày 10/09/2026.
"""

import unittest

from flow_web import listing_watch as lw

EDIT_05133 = "https://www.etsy.com/your/shops/me/listing-editor/edit/4572586100"


def inspect_result(photos_left=11, video_left=1, save_disabled=True, tiles=9, url=EDIT_05133):
    tile = {"key": "https://i.etsystatic.com/1/r/il/a/1/il_224xN.1_x.jpg", "metadata": "image-delete-button"}
    return {
        "url": url,
        "title": "Goose Baby's First Christmas Embroidered Ornament",
        "imagePreviewCount": 11,
        "buttons": [
            {"text": "SKU", "disabled": False},
            {"text": "Save draft", "disabled": save_disabled},
            {"text": "Publish", "disabled": False},
        ],
        "optionLabels": [
            {"text": f"Add video Add video {video_left} remaining"},
            {"text": f"Add photos Add photos {photos_left} remaining"},
        ],
        "mediaDebug": {"mediaTileCount": tiles, "mediaTiles": [tile] * tiles, "mediaControls": []},
    }


class FakeApi:
    """Mỗi việc soát tạo ra thì lần hỏi sau đã xong, với kết quả định sẵn."""

    def __init__(self, results, snapshots=None):
        self.results = list(results)
        self.snapshots = list(snapshots or [])
        self.created = []
        self.done = []

    def create_check(self, machine_id, title, url):
        task_id = f"listing2-t{len(self.created) + 1}"
        self.created.append({"id": task_id, "machine": machine_id, "title": title, "url": url})
        status, result, error = self.results.pop(0)
        self.done.append({"id": task_id, "status": status, "result": result, "error": error})
        return task_id

    def listing2_tasks(self, machine_id):
        return list(reversed(self.done))

    def copy_tasks(self):
        if len(self.snapshots) > 1:
            return [dict(t) for t in self.snapshots.pop(0)]
        return [dict(t) for t in self.snapshots[0]]


FOUND = ("failed", {"found": True, "draftUrl": EDIT_05133, "titleMatches": False}, "Draft editor chưa hiển thị đủ tiêu đề hoặc ảnh.")
NO_WAIT = {"poll": 0, "sleep": lambda s: None}


class ReadEditorTest(unittest.TestCase):
    def test_reads_photo_counter_not_preview_count(self):
        info = lw.read_editor(inspect_result())
        self.assertEqual(info["listing_id"], "4572586100")
        self.assertEqual(info["photos"], 9)
        self.assertEqual(info["tiles"], 9)
        self.assertIs(info["has_video"], False)
        self.assertIs(info["unsaved"], False)

    def test_video_slot_used_means_video_present(self):
        info = lw.read_editor(inspect_result(photos_left=19, video_left=0, tiles=1))
        self.assertEqual(info["photos"], 1)
        self.assertIs(info["has_video"], True)

    def test_enabled_save_button_means_unsaved_edits(self):
        self.assertIs(lw.read_editor(inspect_result(save_disabled=False))["unsaved"], True)

    def test_no_counter_gives_none_not_a_guess(self):
        result = inspect_result()
        result["optionLabels"] = []
        info = lw.read_editor(result)
        self.assertIsNone(info["photos"])
        self.assertIsNone(info["has_video"])
        self.assertEqual(info["tiles"], 9)

    def test_counter_found_in_media_controls(self):
        result = inspect_result()
        result["optionLabels"] = []
        result["mediaDebug"]["mediaControls"] = [{"text": "Add photos Add photos 14 remaining"}]
        self.assertEqual(lw.read_editor(result)["photos"], 6)


class CheckDraftTest(unittest.TestCase):
    def test_sku_search_failed_status_with_draft_url_counts_as_found(self):
        api = FakeApi([FOUND, ("completed", inspect_result(), "")])
        report = lw.check_draft(api, "etsy-vn31", "SKUTESTTEST", 9, **NO_WAIT)
        self.assertTrue(report["ok"])
        self.assertEqual(report["listing_id"], "4572586100")
        first, second = api.created
        self.assertEqual(first["title"], "SKUTESTTEST")
        self.assertIn("state=draft", first["url"])
        self.assertIn("sort=update_date", first["url"])
        self.assertTrue(first["url"].endswith("search_query=SKUTESTTEST"))
        self.assertEqual(second["title"], lw.INSPECT)
        self.assertEqual(second["url"], EDIT_05133)
        self.assertEqual({c["machine"] for c in api.created}, {"etsy-vn31"})

    def test_photo_mismatch_is_not_ok(self):
        api = FakeApi([FOUND, ("completed", inspect_result(photos_left=19, tiles=1), "")])
        report = lw.check_draft(api, "etsy-vn31", "SKUTESTTEST", 9, **NO_WAIT)
        self.assertIs(report["ok"], False)
        self.assertIn("1/9 ảnh", lw.format_report(report))
        self.assertIn("LỆCH", lw.format_report(report))

    def test_no_draft_url_is_error_and_no_inspect(self):
        api = FakeApi([("failed", {"found": False}, "Không tìm thấy Etsy Draft có tiêu đề SKUX.")])
        report = lw.check_draft(api, "etsy-vn31", "SKUX", 3, **NO_WAIT)
        self.assertIn("Không tìm thấy", report["error"])
        self.assertEqual(len(api.created), 1)
        self.assertNotIn("ok", report)

    def test_errors_are_masked(self):
        api = FakeApi([("failed", {}, "hồ sơ a.b@example.com chưa đăng nhập")])
        report = lw.check_draft(api, "etsy-vn31", "SKUX", None, **NO_WAIT)
        self.assertNotIn("@", report["error"])

    def test_timeout_returns_none(self):
        class Never(FakeApi):
            def listing2_tasks(self, machine_id):
                return []

        ticks = iter(range(100))
        task = lw.wait_task(Never([]), "etsy-vn31", "x", timeout=3, poll=0,
                            sleep=lambda s: None, clock=lambda: next(ticks))
        self.assertIsNone(task)


class CreateCheckPayloadTest(unittest.TestCase):
    def test_payload_is_read_only_and_uses_card_link(self):
        sent = {}

        class Api(lw.ListingApi):
            def _call(self, method, path, body=None):
                sent.update(method=method, path=path, body=body)
                return {"task": {"id": "listing2-abc"}}

        self.assertEqual(Api().create_check("etsy-vn31", "SKU1", "https://x"), "listing2-abc")
        self.assertEqual(sent["path"], "/api/listing2/tasks")
        self.assertIs(sent["body"]["verifyOnly"], True)
        self.assertEqual(sent["body"]["machineId"], "etsy-vn31")
        # Link bảng kèm machineId sẽ đổi bảng của máy: phải là link thẻ /c/.
        self.assertIn("trello.com/c/", sent["body"]["trelloUrl"])


def copy_task(status, saved=None, **extra):
    task = {
        "id": "etsy-copy-a5bc3bb6ffb8", "card_id": "TASK-2026-05133", "sku": "SKUTESTTEST",
        "machine_id": "etsy-vn31", "claimed_machine_id": "etsy-vn31", "image_count": 9,
        "status": status, "created_at": "2026-09-10T10:50:00+00:00", "error": "",
        "result": {} if saved is None else {"draftSaved": saved},
    }
    task.update(extra)
    return task


OLD = copy_task("completed", True, id="etsy-copy-old", card_id="TASK-2026-04789", sku="SKUTEST",
                image_count=2, created_at="2026-09-10T09:10:00+00:00")


class WatchTest(unittest.TestCase):
    def run_watch(self, snapshots, results, rounds, check=True):
        api = FakeApi(results, snapshots)
        lines = []
        lw.watch(api, interval=0, check=check, out=lines.append, sleep=lambda s: None, rounds=rounds, poll=0)
        return api, lines

    def test_old_completed_tasks_are_not_rechecked(self):
        api, lines = self.run_watch([[OLD]], [], rounds=3)
        self.assertEqual(api.created, [])
        self.assertIn("đang theo dõi 1 việc đăng, 0 việc chưa xong", lines[0])
        self.assertEqual(len(lines), 1)

    def test_new_draft_is_checked_once(self):
        snapshots = [[OLD], [OLD, copy_task("in_progress")], [OLD, copy_task("completed", True)]]
        api, lines = self.run_watch(snapshots, [FOUND, ("completed", inspect_result(), "")], rounds=5)
        self.assertEqual(len(api.created), 2)
        text = "\n".join(lines)
        self.assertIn("TASK-2026-05133 · SKUTESTTEST · etsy-vn31 · 9 ảnh · đang đăng", text)
        self.assertIn("xong · đã lưu nháp", text)
        self.assertIn("listing 4572586100 · 9/9 ảnh · không video · ĐÚNG", text)

    def test_no_check_flag_only_prints(self):
        snapshots = [[OLD], [OLD, copy_task("completed", True)]]
        api, lines = self.run_watch(snapshots, [], rounds=3, check=False)
        self.assertEqual(api.created, [])
        self.assertIn("đã lưu nháp", lines[-1])

    def test_failed_copy_prints_masked_error_and_is_not_checked(self):
        bad = copy_task("failed", None, error="Etsy chỉ hiển thị 3/9 ảnh; hồ sơ x@y.com")
        api, lines = self.run_watch([[OLD], [OLD, bad]], [], rounds=3)
        self.assertEqual(api.created, [])
        self.assertIn("hỏng", lines[-1])
        self.assertIn("3/9 ảnh", lines[-1])
        self.assertNotIn("@", lines[-1])

    def test_unreachable_api_keeps_watching(self):
        class Down(FakeApi):
            calls = 0

            def copy_tasks(self):
                Down.calls += 1
                if Down.calls == 1:
                    raise OSError("timed out")
                return [OLD]

        lines = []
        lw.watch(Down([], [[OLD]]), interval=0, out=lines.append, sleep=lambda s: None, rounds=2)
        self.assertIn("không gọi được bản Listing", lines[0])
        self.assertIn("đang theo dõi 1 việc đăng", lines[1])


if __name__ == "__main__":
    unittest.main()
