import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flow_web.listing_bridge import ListingBridge, ListingBridgeConfig
from flow_web.review_lister import (
    CARD_FILES_KEY,
    DIRECT_PATH,
    DONE_NOTE,
    MAX_FULL_PER_PASS,
    MAX_IMAGES,
    STATUS_FILE,
    UNSAVED_NOTE,
    ErpFiles,
    ReviewListerError,
    build_from_env,
    main,
    read_card,
    scan_once,
    ReviewLister,
    card_image_urls,
    is_review_status,
    missing_fields,
)


def card(meta: str, comments=None, name="TASK-2026-04789"):
    return {"name": name, "subject": "Idea 4", "meta": meta, "comments": comments or []}


def image_comment(url, like=0, dislike=0):
    return {"attachments": [{"file_url": url}], "like_count": like, "dislike_count": dislike}


def saved_run(queue_id, card_id="TASK-2026-04789"):
    # Lượt đăng xong như bản Listing thật báo ngày 11/09/2026: có ``result.draftSaved``.
    return {"id": queue_id, "card_id": card_id, "status": "completed", "result": {"draftSaved": True}}


# TASK-2026-05133 ngày 10/09/2026: ``taskAttachments`` trả chín tệp, mới trước.
# Ảnh bìa là tệp cũ nhất; tám ảnh Flow thả vào sau. Lister cũ chỉ thấy ảnh bìa.
FLOW_FILES_05133 = [
    {"file_url": f"/private/files/flow-3492691c-{n}.jpg", "creation": f"2026-09-09 13:{m}"}
    for n, m in ((11, "06:00"), (10, "05:56"), (9, "05:53"), (8, "05:50"), (7, "05:46"), (6, "05:43"), (4, "05:40"), (3, "05:36"))
] + [{"file_url": "/private/files/ornament round (39).jpeg", "creation": "2026-09-09 13:05:33"}]


class Client:
    """ERP giả qua token bot: ``taskFull`` trả thân thẻ, không trả tệp riêng tư."""

    def __init__(self, nodes):
        self.nodes = nodes
        self.asked = []
        self.notes = []

    def task_projects(self):
        return [{"name": "P1"}]

    def task_board(self, project):
        return [{"name": name, "status": "Pending Review"} for name in self.nodes]

    def task_full(self, name):
        self.asked.append(name)
        return {"root": self.nodes[name]}

    def add_comment(self, task, text):
        self.notes.append((task, text))


class Config:
    projects = ()


class ReviewListerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.files = root / "downloads"
        self.ledger = root / "ledger.json"
        self.posts = []
        # Ảnh chụp hàng đợi của bản Listing: lister hỏi nó trước khi giao.
        self.queue = []
        self.fetched = []

        def fetch(url, timeout):
            self.fetched.append(url)
            return {"ok": True, "tasks": list(self.queue)}

        self.bridge = ListingBridge(
            ListingBridgeConfig(api_url="http://listing", machines=("etsy-vn31", "etsy-vn35")),
            fetch=fetch,
        )

        def post(url, payload, timeout):
            self.posts.append((url, payload))
            # Route thật bọc kết quả: ``{"etsy_browser_copy": {...}}`` (main.py của bản Listing).
            return {
                "etsy_browser_copy": {
                    "ok": True,
                    "configured": True,
                    "status": "ready_for_browser",
                    "enqueued": True,
                    "queue_task": {"id": f"etsy-copy-{len(self.posts)}"},
                }
            }

        self.post = post

        self.lister = ReviewLister(
            self.bridge,
            self.files,
            lambda url: (b"img:" + url.encode(), "image/jpeg"),
            post=post,
            ledger_file=self.ledger,
            card_url="https://erp/app/task",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_review_column_is_the_trigger(self):
        self.assertTrue(is_review_status("pending-review"))
        self.assertTrue(is_review_status("Đang review"))
        self.assertFalse(is_review_status("in-progress"))
        self.assertFalse(is_review_status("done"))

    def test_card_without_account_or_copysku_waits(self):
        node = card("sku: HVG-1", [image_comment("/private/files/a.jpg")])
        self.assertEqual(missing_fields(node), ["account", "copysku"])
        outcome = self.lister.list_card(node)
        self.assertIn("waiting", outcome)
        self.assertIn("account", outcome["waiting"])
        self.assertEqual(self.posts, [])

    def test_card_without_images_waits(self):
        node = card("account: acc31\ncopysku: HVG-OLD-1")
        self.assertEqual(missing_fields(node), ["ảnh trên thẻ"])
        self.assertEqual(self.posts, [])

    def test_disliked_images_and_non_images_are_left_out(self):
        node = card(
            "account: acc31\ncopysku: HVG-OLD-1",
            [
                image_comment("/private/files/a.jpg", like=1),
                image_comment("/private/files/b.jpg", dislike=1),
                image_comment("/private/files/gia.pdf"),
                {"attachments": [], "replies": [image_comment("/files/c.png")]},
            ],
        )
        self.assertEqual(card_image_urls(node), ["/private/files/a.jpg", "/files/c.png"])

    def test_cover_counts_but_comment_image_field_is_the_author_avatar(self):
        # TASK-2026-04789, 10/09/2026: hai bình luận đính hai bộ tệp khác nhau mà
        # cùng trả một ``image`` — ảnh đại diện 512×512 của người bình luận. Lister
        # cũ đăng ảnh chân dung ấy làm ảnh thứ hai của sản phẩm.
        avatar = "/files/1786068916100_1856441704389779774_267537167333445195_0fbf11fea24f441387b84cb29869ed93.jpg"
        node = card(
            "account: acc31\ncopysku: HVG-OLD-1",
            [
                {"image": avatar, "attachments": [{"file_url": "/private/files/17bdb9c.jpg"}]},
                {"image": avatar, "attachments": [{"file_url": "/private/files/color 1.jpg"}]},
            ],
        )
        node["cover_image"] = "/private/files/ornament round (1).jpeg"
        self.assertEqual(
            card_image_urls(node),
            ["/private/files/ornament round (1).jpeg", "/private/files/17bdb9c.jpg", "/private/files/color 1.jpg"],
        )
        self.assertEqual(missing_fields(node), [])
        only_avatar = card("account: acc31\ncopysku: HVG-OLD-1", [{"image": avatar, "attachments": []}])
        self.assertEqual(missing_fields(only_avatar), ["ảnh trên thẻ"])

    def test_files_hung_on_the_card_follow_the_cover_oldest_first(self):
        node = card("account: acc31\ncopysku: ORC5_1439")
        node["cover_image"] = "/private/files/ornament round (39).jpeg"
        node[CARD_FILES_KEY] = FLOW_FILES_05133
        self.assertEqual(
            card_image_urls(node),
            ["/private/files/ornament round (39).jpeg"]
            + [f"/private/files/flow-3492691c-{n}.jpg" for n in (3, 4, 6, 7, 8, 9, 10, 11)],
        )

    def test_same_file_written_two_ways_is_listed_once(self):
        node = card("account: acc31\ncopysku: HVG-OLD-1", [image_comment("https://erp/private/files/ornament%20round%20(1).jpeg")])
        node["cover_image"] = "/private/files/ornament round (1).jpeg"
        node[CARD_FILES_KEY] = [{"file_url": "/private/files/ornament round (1).jpeg", "creation": "2026-09-08"}]
        self.assertEqual(card_image_urls(node), ["/private/files/ornament round (1).jpeg"])

    def test_enqueues_direct_with_copysku_account_and_staged_images(self):
        node = card(
            "account: acc31\ncopysku: HVG-OLD-1\nsku: HVG-XMAS-0001",
            [image_comment("/private/files/a.jpg"), image_comment("/private/files/b.png")],
        )
        outcome = self.lister.list_card(node)
        self.assertEqual(outcome["queue_task_id"], "etsy-copy-1")
        self.assertEqual(outcome["machine_id"], "etsy-vn31")
        url, payload = self.posts[0]
        self.assertEqual(url, "http://listing" + DIRECT_PATH)
        self.assertEqual(payload["templateSourceSku"], "HVG-OLD-1")
        self.assertEqual(payload["sku"], "HVG-XMAS-0001")
        self.assertEqual(payload["machineId"], "etsy-vn31")
        self.assertEqual(payload["cardId"], "TASK-2026-04789")
        self.assertEqual(payload["jobId"], "erp-TASK-2026-04789")
        self.assertEqual(
            payload["imageUrls"],
            [
                "/files/downloads/erp-TASK-2026-04789/01.jpg",
                "/files/downloads/erp-TASK-2026-04789/02.png",
            ],
        )
        self.assertEqual(payload["images"][0]["download_url"], payload["imageUrls"][0])
        staged = self.files / "erp-TASK-2026-04789" / "01.jpg"
        self.assertEqual(staged.read_bytes(), b"img:/private/files/a.jpg")

    def test_same_card_is_never_enqueued_twice(self):
        node = card("account: acc31\ncopysku: HVG-OLD-1", [image_comment("/private/files/a.jpg")])
        self.lister.list_card(node)
        again = self.lister.list_card(node)
        self.assertEqual(again, {"task": "TASK-2026-04789", "already": "etsy-copy-1"})
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(json.loads(self.ledger.read_text(encoding="utf-8"))["TASK-2026-04789"]["state"], "queued")

    def test_reply_without_the_wrapper_is_not_taken_as_listed(self):
        self.lister.post = lambda url, payload, timeout: {"enqueued": True, "queue_task": {"id": "x"}}
        node = card("account: acc31\ncopysku: HVG-OLD-1", [image_comment("/private/files/a.jpg")])
        with self.assertRaises(Exception) as caught:
            self.lister.list_card(node)
        self.assertIn("TASK-2026-04789", str(caught.exception))
        self.assertEqual(self.lister.ledger(), {})

    def test_card_already_on_the_controller_is_adopted_not_listed_again(self):
        # 10/09/2026: bản Listing đã nhận và đăng xong thẻ này, còn sổ thì trống
        # vì câu trả lời đọc hỏng. Lượt quét sau suýt đăng thêm một bản nháp.
        self.queue.append(
            {"id": "etsy-copy-fa1a06d575cf", "card_id": "TASK-2026-04789", "status": "completed", "machine_id": "etsy-vn31"}
        )
        node = card("account: ETSY - VN31\ncopysku: ORC5_1439", [image_comment("/private/files/a.jpg")])
        outcome = self.lister.list_card(node)
        self.assertEqual(outcome["queue_task_id"], "etsy-copy-fa1a06d575cf")
        self.assertEqual(outcome["machine_id"], "etsy-vn31")
        self.assertTrue(outcome["adopted"])
        self.assertEqual(self.posts, [])
        self.assertFalse((self.files / "erp-TASK-2026-04789").exists())
        self.assertIn("machine_id=etsy-vn31", self.fetched[0])
        notes = []
        self.lister.follow_up(lambda task, text: notes.append(task))
        self.assertEqual(notes, ["TASK-2026-04789"])

    def test_failed_run_on_the_controller_does_not_block_a_new_one(self):
        self.queue.append(
            {"id": "etsy-copy-old", "card_id": "TASK-2026-04789", "status": "failed", "machine_id": "etsy-vn31"}
        )
        node = card("account: acc31\ncopysku: HVG-OLD-1", [image_comment("/private/files/a.jpg")])
        outcome = self.lister.list_card(node)
        self.assertEqual(outcome["queue_task_id"], "etsy-copy-1")
        self.assertEqual(len(self.posts), 1)

    def test_account_without_machine_is_refused(self):
        node = card("account: acc77\ncopysku: HVG-OLD-1", [image_comment("/private/files/a.jpg")])
        with self.assertRaises(Exception) as caught:
            self.lister.list_card(node)
        self.assertIn("acc77", str(caught.exception))
        self.assertEqual(self.posts, [])

    def test_follow_up_comments_when_listed(self):
        node = card("account: acc31\ncopysku: HVG-OLD-1", [image_comment("/private/files/a.jpg")])
        self.lister.list_card(node)
        # Từ 11/09/2026 "đăng xong" là ``completed`` kèm ``draftSaved``. Lượt
        # ``completed`` trơn nay là bài test_completed_without_a_saved_draft_stays_for_a_person.
        self.bridge._get = lambda url, timeout: {"tasks": [saved_run("etsy-copy-1")]}
        notes = []
        lines = self.lister.follow_up(lambda task, text: notes.append((task, text)))
        self.assertEqual(lines, [{"task": "TASK-2026-04789", "listed": True}])
        self.assertEqual(notes[0], ("TASK-2026-04789", DONE_NOTE))
        self.assertEqual(json.loads(self.ledger.read_text(encoding="utf-8"))["TASK-2026-04789"]["state"], "done")
        self.assertEqual(self.lister.follow_up(lambda task, text: notes.append((task, text))), [])
        self.assertEqual(len(notes), 1)

    # ── lưu nháp xong thì thẻ tự sang Hoàn thành (luật 11/09/2026) ─────

    def _listed(self, name="TASK-2026-04789"):
        self.lister.list_card(card("account: acc31\ncopysku: HVG-OLD-1", [image_comment("/private/files/a.jpg")], name=name))

    def test_saved_draft_moves_the_card_to_done(self):
        # Người bán không soát bản nháp nữa: lưu được là xong việc.
        closed = []
        self.lister.closer = closed.append
        self._listed()
        self.bridge._get = lambda url, timeout: {"tasks": [saved_run("etsy-copy-1")]}
        notes = []
        lines = self.lister.follow_up(lambda task, text: notes.append((task, text)), in_review={"TASK-2026-04789"})
        self.assertEqual(lines, [{"task": "TASK-2026-04789", "listed": True}, {"task": "TASK-2026-04789", "closed": True}])
        self.assertEqual(closed, ["TASK-2026-04789"])
        self.assertEqual(notes, [("TASK-2026-04789", DONE_NOTE)])
        entry = self.lister.ledger()["TASK-2026-04789"]
        self.assertEqual((entry["state"], entry["draft_saved"]), ("done", True))
        self.assertRegex(entry["closed_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        # Chuyển một lần thôi.
        self.assertEqual(self.lister.follow_up(lambda task, text: notes.append((task, text)), in_review={"TASK-2026-04789"}), [])
        self.assertEqual((closed, len(notes)), (["TASK-2026-04789"], 1))

    def test_completed_without_a_saved_draft_stays_for_a_person(self):
        # Máy báo ``completed`` mà không bấm lưu được: không có gì trên Etsy để
        # coi là xong. Thẻ nằm lại *Đang review*, bình luận nói rõ vì sao.
        self.lister.closer = lambda task_id: self.fail("chưa lưu nháp thì không được chuyển sang Hoàn thành")
        self._listed()
        for result in (None, {"draftSaved": False}):
            self.bridge._get = lambda url, timeout, result=result: {
                "tasks": [{"id": "etsy-copy-1", "status": "completed", "result": result}]
            }
            ledger = self.lister.ledger()
            ledger["TASK-2026-04789"]["state"] = "queued"
            self.lister._save(ledger)
            notes = []
            lines = self.lister.follow_up(lambda task, text: notes.append((task, text)), in_review={"TASK-2026-04789"})
            self.assertEqual(lines, [{"task": "TASK-2026-04789", "unsaved": True}])
            self.assertEqual(notes, [("TASK-2026-04789", UNSAVED_NOTE)])
            self.assertEqual(self.lister.ledger()["TASK-2026-04789"]["state"], "unsaved")
            # Không hỏi lại, không bình luận lại.
            self.assertEqual(self.lister.follow_up(lambda task, text: notes.append((task, text)), in_review={"TASK-2026-04789"}), [])
            self.assertEqual(len(notes), 1)

    def test_card_not_seen_in_review_waits_for_a_pass_that_sees_it(self):
        # Bảng của dự án đọc hỏng, hoặc thẻ đang ở cột khác: không chuyển mù.
        closed = []
        self.lister.closer = closed.append
        self._listed()
        self.bridge._get = lambda url, timeout: {"tasks": [saved_run("etsy-copy-1")]}
        self.assertEqual(self.lister.follow_up(in_review=set()), [{"task": "TASK-2026-04789", "listed": True}])
        self.assertEqual(closed, [])
        self.assertNotIn("closed_at", self.lister.ledger()["TASK-2026-04789"])
        self.assertEqual(self.lister.follow_up(in_review={"TASK-2026-04789"}), [{"task": "TASK-2026-04789", "closed": True}])
        self.assertEqual(closed, ["TASK-2026-04789"])

    def test_close_that_fails_is_tried_again_next_pass(self):
        attempts = []

        def closer(task_id):
            attempts.append(task_id)
            if len(attempts) == 1:
                raise ReviewListerError("ERP từ chối UpdateTaskStatus (HTTP 500).")

        self.lister.closer = closer
        self._listed()
        self.bridge._get = lambda url, timeout: {"tasks": [saved_run("etsy-copy-1")]}
        notes = []
        with self.assertLogs("flow_web.review_lister", "WARNING") as logs:
            lines = self.lister.follow_up(lambda task, text: notes.append(task), in_review={"TASK-2026-04789"})
        self.assertIn("Không chuyển được thẻ TASK-2026-04789 sang Hoàn thành", logs.output[0])
        self.assertEqual(lines[0], {"task": "TASK-2026-04789", "listed": True})
        self.assertEqual(lines[1]["task"], "TASK-2026-04789")
        self.assertIn("HTTP 500", lines[1]["close_error"])
        entry = self.lister.ledger()["TASK-2026-04789"]
        self.assertIn("HTTP 500", entry["close_error"])
        self.assertNotIn("closed_at", entry)
        lines = self.lister.follow_up(lambda task, text: notes.append(task), in_review={"TASK-2026-04789"})
        self.assertEqual(lines, [{"task": "TASK-2026-04789", "closed": True}])
        entry = self.lister.ledger()["TASK-2026-04789"]
        self.assertIn("closed_at", entry)
        self.assertNotIn("close_error", entry)
        self.assertEqual((attempts, notes), (["TASK-2026-04789"] * 2, ["TASK-2026-04789"]))

    def test_one_refused_close_stops_the_moves_for_this_pass(self):
        # ERP từ chối một lần ghi (429, 503 bảo trì) thì lần sau cũng thế:
        # thôi ghi tới lượt sau, không dội tiếp vào ERP.
        refuse = [True]
        attempts = []

        def closer(task_id):
            attempts.append(task_id)
            if refuse[0]:
                raise ReviewListerError("ERP từ chối UpdateTaskStatus (HTTP 429).")

        self.lister.closer = closer
        self._listed("TASK-A")
        self._listed("TASK-B")
        self.bridge._get = lambda url, timeout: {"tasks": [saved_run("etsy-copy-1", "TASK-A"), saved_run("etsy-copy-2", "TASK-B")]}
        with self.assertLogs("flow_web.review_lister", "WARNING") as logs:
            self.lister.follow_up(in_review={"TASK-A", "TASK-B"})
        self.assertEqual(len(logs.output), 1)
        self.assertEqual(attempts, ["TASK-A"])
        refuse[0] = False
        lines = self.lister.follow_up(in_review={"TASK-A", "TASK-B"})
        self.assertEqual(lines, [{"task": "TASK-A", "closed": True}, {"task": "TASK-B", "closed": True}])

    def test_queue_read_failing_midway_keeps_the_receipts_already_made(self):
        # Thẻ A đã bình luận và đã sang Hoàn thành thì sổ phải nhớ, dù hỏi
        # hàng đợi cho thẻ B hỏng: không thì lượt sau bình luận lần hai.
        closed = []
        self.lister.closer = closed.append
        self._listed("TASK-A")
        self._listed("TASK-B")
        asked = []

        def fetch(url, timeout):
            asked.append(url)
            if len(asked) > 1:
                raise ReviewListerError("Không gọi được bản Listing")
            return {"tasks": [saved_run("etsy-copy-1", "TASK-A")]}

        self.bridge._get = fetch
        with self.assertRaises(ReviewListerError):
            self.lister.follow_up(lambda task, text: None, in_review={"TASK-A", "TASK-B"})
        ledger = self.lister.ledger()
        self.assertEqual((ledger["TASK-A"]["state"], ledger["TASK-B"]["state"]), ("done", "queued"))
        self.assertIn("closed_at", ledger["TASK-A"])
        self.assertEqual(closed, ["TASK-A"])

    def test_cards_listed_under_the_old_rule_are_left_to_people(self):
        # Sổ trước 11/09/2026 không ghi ``draft_saved``: những thẻ ấy chờ người
        # bán soát như luật cũ. Lister không tự đóng hàng loạt.
        self.ledger.write_text(
            json.dumps({"TASK-OLD": {"queue_task_id": "etsy-copy-9", "machine_id": "etsy-vn31", "state": "done", "noted": True}}),
            encoding="utf-8",
        )
        self.lister.closer = lambda task_id: self.fail("thẻ đăng theo luật cũ: người bán soát rồi kéo tay")
        self.assertEqual(self.lister.follow_up(in_review={"TASK-OLD"}), [])

    def test_scan_moves_saved_cards_it_sees_in_review(self):
        class BoardClient(Client):
            def task_board(self, project):
                return [{"name": "TASK-A", "status": "Pending Review"}, {"name": "TASK-B", "status": "Working"}]

        self._listed("TASK-A")
        self._listed("TASK-B")
        self.queue[:] = [saved_run("etsy-copy-1", "TASK-A"), saved_run("etsy-copy-2", "TASK-B")]
        closed = []
        self.lister.closer = closed.append
        client = BoardClient({})
        scan_once(client, Config(), self.lister)
        self.assertEqual(closed, ["TASK-A"])
        self.assertEqual(sorted(task for task, _ in client.notes), ["TASK-A", "TASK-B"])
        (row,) = self._status()["cards"]
        self.assertEqual((row["task"], row["state"]), ("TASK-A", "done"))
        self.assertIn("closed_at", row)

    def test_app_key_moves_a_card_still_in_review_to_done(self):
        erp = ErpFiles("https://erp", "k", "s")
        calls = []

        def graphql(query, variables, operation):
            calls.append((operation, variables))
            if operation == "TaskDetail":
                return {"taskDetail": {"name": variables["name"], "status": "Pending Review"}}
            self.assertIn("updateTaskStatus(name: $name, status: $status)", query)
            return {"updateTaskStatus": True}

        erp.graphql = graphql
        erp.close_card("TASK-1")
        self.assertEqual(
            calls,
            [("TaskDetail", {"name": "TASK-1"}), ("UpdateTaskStatus", {"name": "TASK-1", "status": "Completed"})],
        )

    def test_app_key_leaves_a_card_that_moved_on(self):
        # Đọc lại cột ngay trước khi ghi: thẻ người đã kéo đi thì không kéo về.
        for status in ("Working", "Open", "Cancelled", ""):
            with self.subTest(status=status):
                erp = ErpFiles("https://erp", "k", "s")
                calls = []
                erp.graphql = lambda query, variables, operation, status=status, calls=calls: (
                    calls.append(operation) or {"taskDetail": {"name": variables["name"], "status": status}}
                )
                with self.assertRaises(ReviewListerError):
                    erp.close_card("TASK-1")
                self.assertEqual(calls, ["TaskDetail"])
        # Người đã kéo sang Hoàn thành trước: xong rồi, khỏi ghi.
        erp = ErpFiles("https://erp", "k", "s")
        calls = []
        erp.graphql = lambda query, variables, operation: (
            calls.append(operation) or {"taskDetail": {"name": variables["name"], "status": "Completed"}}
        )
        erp.close_card("TASK-1")
        self.assertEqual(calls, ["TaskDetail"])
        # Khoá app không thấy thẻ: lỗi, không ghi.
        for detail in (None, {}, {"name": "TASK-OTHER", "status": "Pending Review"}):
            erp = ErpFiles("https://erp", "k", "s")
            erp.graphql = lambda query, variables, operation, detail=detail: (
                {"taskDetail": detail} if operation == "TaskDetail" else self.fail("không thấy thẻ thì không ghi")
            )
            with self.assertRaises(ReviewListerError):
                erp.close_card("TASK-1")

    def test_app_key_mover_without_key_refuses(self):
        with self.assertRaises(ReviewListerError):
            ErpFiles("https://erp").close_card("TASK-1")

    def test_lister_built_from_env_moves_cards_with_the_app_key(self):
        env = {
            "FLOW_ENV_FILE": str(Path(self.tmp.name) / "khong-co.env"),
            "ERP_AGENT_TOKEN": "t",
            "ERP_BASE_URL": "https://erp",
            "ERP_API_KEY": "k",
            "ERP_API_SECRET": "s",
            "ERP_LISTING_API_URL": "http://listing",
            "ERP_LISTING_FILES_DIR": str(self.files),
        }
        with mock.patch.dict(os.environ, env, clear=True):
            _, _, lister = build_from_env()
        self.assertIsInstance(lister.download, ErpFiles)
        self.assertEqual(lister.closer, lister.download.close_card)

    def test_scan_lists_every_picture_the_app_key_sees(self):
        # Token bot: không tệp trên thẻ, bình luận chỉ còn ảnh đại diện.
        bot_view = card("account: ETSY - VN31\ncopysku: ORC5_1439\nsku: skutesttest", name="TASK-2026-05133")
        bot_view["cover_image"] = "/private/files/ornament round (39).jpeg"
        client = Client({"TASK-2026-05133": bot_view})
        read = []

        def reader(task_id):
            read.append(task_id)
            return {"files": FLOW_FILES_05133, "comments": [image_comment("/private/files/hand.jpg")]}

        self.lister.reader = reader
        with self.assertLogs("flow_web.review_lister", "WARNING") as logs:
            lines = scan_once(client, Config(), self.lister)
        self.assertIn("10 ảnh", logs.output[0])
        self.assertEqual(read, ["TASK-2026-05133"])
        self.assertEqual(lines[0]["image_count"], MAX_IMAGES)
        self.assertEqual(lines[0]["images_left_out"], 1)
        staged = sorted(path.name for path in (self.files / "erp-TASK-2026-05133").iterdir())
        self.assertEqual(len(staged), MAX_IMAGES)
        self.assertEqual(
            (self.files / "erp-TASK-2026-05133" / "02.jpg").read_bytes(), b"img:/private/files/flow-3492691c-3.jpg"
        )

    def test_card_not_declared_yet_costs_no_app_read(self):
        client = Client({"TASK-1": card("sku: X", name="TASK-1")})
        self.lister.reader = lambda task_id: self.fail("thẻ chưa khai account/copysku thì khỏi đọc thêm")
        node = read_card(client, self.lister, "TASK-1")
        self.assertNotIn(CARD_FILES_KEY, node)

    def test_app_read_failing_blocks_the_card_instead_of_listing_short(self):
        node = card("account: acc31\ncopysku: HVG-OLD-1", name="TASK-2")
        node["cover_image"] = "/private/files/a.jpg"
        client = Client({"TASK-2": node})

        def reader(task_id):
            raise ReviewListerError("ERP không cho đọc TaskAttachments (HTTP 500).")

        self.lister.reader = reader
        lines = scan_once(client, Config(), self.lister)
        self.assertEqual(lines[0]["task"], "TASK-2")
        self.assertIn("HTTP 500", lines[0]["error"])
        self.assertEqual(self.posts, [])
        self.assertEqual(self.lister.ledger(), {})

    def test_app_reader_reads_card_files_and_full_comments(self):
        erp = ErpFiles("https://erp", "k", "s")
        calls = []

        def graphql(query, variables, operation):
            calls.append((operation, variables))
            if operation == "TaskAttachments":
                return {"taskAttachments": {"files": FLOW_FILES_05133}}
            return {"taskDetail": {"name": variables["name"], "comments": [image_comment("/private/files/hand.jpg"), "rác"]}}

        erp.graphql = graphql
        extra = erp.card_files("TASK-2026-05133")
        self.assertEqual(calls, [("TaskAttachments", {"task": "TASK-2026-05133"}), ("TaskDetail", {"name": "TASK-2026-05133"})])
        self.assertEqual(len(extra["files"]), 9)
        self.assertEqual(extra["comments"], [image_comment("/private/files/hand.jpg")])

    def test_app_reader_without_key_refuses(self):
        with self.assertRaises(ReviewListerError):
            ErpFiles("https://erp").card_files("TASK-1")

    def test_app_reader_refuses_a_card_it_cannot_see(self):
        # Khoá app không đọc được thẻ thì trả rỗng: coi là lỗi, không phải "thẻ không có ảnh".
        for detail in (None, {}, {"name": "TASK-OTHER", "comments": []}):
            erp = ErpFiles("https://erp", "k", "s")
            erp.graphql = lambda query, variables, operation, detail=detail: (
                {"taskAttachments": {"files": []}} if operation == "TaskAttachments" else {"taskDetail": detail}
            )
            with self.assertRaises(ReviewListerError):
                erp.card_files("TASK-1")
        erp = ErpFiles("https://erp", "k", "s")
        erp.graphql = lambda query, variables, operation: {"taskAttachments": None}
        with self.assertRaises(ReviewListerError):
            erp.card_files("TASK-1")

    def test_again_lists_a_done_card_once_more_and_remembers_the_old_run(self):
        node = card("account: acc31\ncopysku: HVG-OLD-1", [image_comment("/private/files/a.jpg")])
        self.lister.list_card(node)
        self.queue.append({"id": "etsy-copy-1", "card_id": "TASK-2026-04789", "status": "completed"})
        self.assertEqual(self.lister.list_card(node), {"task": "TASK-2026-04789", "already": "etsy-copy-1"})
        outcome = self.lister.list_card(node, again=True)
        self.assertEqual(outcome["queue_task_id"], "etsy-copy-2")
        self.assertEqual(len(self.posts), 2)
        entry = self.lister.ledger()["TASK-2026-04789"]
        self.assertEqual(entry["state"], "queued")
        self.assertEqual(entry["replaces"], ["etsy-copy-1"])

    def test_again_still_waits_for_a_run_in_flight(self):
        node = card("account: acc31\ncopysku: HVG-OLD-1", [image_comment("/private/files/a.jpg")])
        self.queue.append({"id": "etsy-copy-running", "card_id": "TASK-2026-04789", "status": "in_progress"})
        outcome = self.lister.list_card(node, again=True)
        self.assertEqual(outcome["queue_task_id"], "etsy-copy-running")
        self.assertTrue(outcome["adopted"])
        self.assertEqual(self.posts, [])

    def test_again_only_goes_with_one_task_and_one_pass(self):
        for argv in (["--again"], ["--again", "--task", "TASK-1", "--loop", "300"]):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()) as err:
                main(argv)
            self.assertIn("--again", err.getvalue())

    def test_scan_rotates_under_the_taskfull_cap(self):
        names = [f"TASK-{i}" for i in range(MAX_FULL_PER_PASS + 3)]
        asked = []

        class Client:
            def task_projects(self):
                return [{"name": "P1"}]

            def task_board(self, project):
                rows = [{"name": name, "status": "Pending Review"} for name in names]
                return rows + [{"name": "TASK-WORKING", "status": "Working"}]

            def task_full(self, name):
                asked.append(name)
                return {"root": card("sku: X", name=name)}

            def add_comment(self, task, text):
                raise AssertionError("chưa thẻ nào đăng xong")

        class Config:
            projects = ()

        scan_once(Client(), Config(), self.lister)
        scan_once(Client(), Config(), self.lister)
        self.assertNotIn("TASK-WORKING", asked)
        self.assertEqual(set(asked), set(names))
        self.assertEqual(len(asked), 2 * MAX_FULL_PER_PASS)

    # ── tệp trạng thái cho bảng theo dõi ───────────────────────────────

    def _status(self):
        return json.loads((self.files / STATUS_FILE).read_text(encoding="utf-8"))

    def test_scan_leaves_a_status_file_for_the_board(self):
        ready = card(
            "account: acc31\ncopysku: HVG-OLD-1\nsku: HVG-9", [image_comment("/private/files/a.jpg")], name="TASK-READY"
        )
        client = Client({"TASK-READY": ready, "TASK-BARE": card("sku: HVG-2", name="TASK-BARE")})
        scan_once(client, Config(), self.lister)
        status = self._status()
        cards = {row["task"]: row for row in status["cards"]}
        self.assertEqual(set(cards), {"TASK-READY", "TASK-BARE"})
        self.assertEqual(cards["TASK-BARE"]["state"], "waiting")
        self.assertEqual(cards["TASK-BARE"]["note"], "thiếu account, copysku, ảnh trên thẻ")
        self.assertEqual(cards["TASK-BARE"]["title"], "Idea 4")
        self.assertEqual(cards["TASK-READY"]["state"], "queued")
        self.assertEqual(cards["TASK-READY"]["queue_task_id"], "etsy-copy-1")
        self.assertEqual(cards["TASK-READY"]["machine_id"], "etsy-vn31")
        self.assertEqual(cards["TASK-READY"]["copysku"], "HVG-OLD-1")
        self.assertEqual(cards["TASK-READY"]["url"], "https://erp/app/task/TASK-READY")
        self.assertRegex(status["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIn("TASK-READY", status["ledger"])

    def test_card_not_reached_this_pass_keeps_its_place_on_the_board(self):
        names = [f"TASK-{i}" for i in range(MAX_FULL_PER_PASS + 1)]
        client = Client({name: card("sku: X", name=name) for name in names})
        scan_once(client, Config(), self.lister)
        states = [row["state"] for row in self._status()["cards"]]
        self.assertEqual(states.count("unchecked"), 1)
        self.assertEqual(states.count("waiting"), MAX_FULL_PER_PASS)
        scan_once(client, Config(), self.lister)
        self.assertEqual([row["state"] for row in self._status()["cards"]], ["waiting"] * len(names))

    def test_row_that_shows_missing_fields_is_on_the_board_without_a_taskfull(self):
        class BoardClient(Client):
            def task_board(self, project):
                return [{"name": "TASK-META", "status": "Pending Review", "subject": "Idea 7", "meta": "account: acc31"}]

        client = BoardClient({})
        scan_once(client, Config(), self.lister)
        self.assertEqual(client.asked, [])
        (row,) = self._status()["cards"]
        self.assertEqual(
            (row["task"], row["state"], row["note"], row["account"], row["title"]),
            ("TASK-META", "waiting", "thiếu copysku", "acc31", "Idea 7"),
        )

    def test_board_error_reaches_the_status_file(self):
        class Broken(Client):
            def task_board(self, project):
                raise RuntimeError("HTTP 500 QueryDeadlockError")

        scan_once(Broken({}), Config(), self.lister)
        self.assertEqual(self._status()["errors"], ["P1: HTTP 500 QueryDeadlockError"])

    def test_status_file_that_cannot_be_written_does_not_stop_the_pass(self):
        (self.files / STATUS_FILE).mkdir(parents=True)
        client = Client({"TASK-BARE": card("sku: HVG-2", name="TASK-BARE")})
        with self.assertLogs("flow_web.review_lister", "WARNING") as logs:
            lines = scan_once(client, Config(), self.lister)
        self.assertIn("waiting", lines[0])
        self.assertIn(STATUS_FILE, logs.output[0])


if __name__ == "__main__":
    unittest.main()
