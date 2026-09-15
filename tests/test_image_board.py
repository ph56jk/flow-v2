import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flow_web.image_board import (
    ALERT_JOBS,
    CACHE_SECONDS,
    READ_GAP,
    FlowApi,
    JobsFile,
    build_images,
    image_job_view,
    slim_job,
)

NOW = datetime(2026, 9, 11, 3, 0, tzinfo=timezone.utc)  # 10:00 giờ VN
QUOTA = (
    "Tat ca Chrome profile Flow da het quota Agent (Flow profile 1). App da dung thay vi quay lai "
    "profile da het quota. Hay dang nhap them profile khac hoac cho quota reset. Khoa toi 14:00 11/09."
)


def at(**delta):
    return (NOW - timedelta(**delta)).isoformat()


def job(job_id, status, updated, task="", **extra):
    base = {
        "id": job_id,
        "type": "image",
        "status": status,
        "title": f"Idea Idea {job_id} ({task})" if task else f"Idea {job_id}",
        "input": {"count": 12, "erp_task_id": task, "erp_project_id": "PROJ-0013"},
        "result": {},
        "artifacts": [],
        "logs": [],
        "error": "",
        "progress_snapshot": {"stage_label": "", "detail": "", "last_signal_at": updated},
        "created_at": at(hours=12),
        "updated_at": updated,
    }
    base.update(extra)
    return base


def state(jobs, blocked=True, authenticated=True):
    return {
        "jobs": jobs,
        "auth": {"authenticated": authenticated},
        "integrations": {"runtime": {"flow_profiles": [{"label": "Flow profile 1", "active": True, "quota_blocked": blocked}]}},
        "project_health": {
            "status_label": "Ổn",
            "headline": "Dự án chạy được",
            "trust_signals": [{"key": "auth", "tone": "success", "label": "Đăng nhập", "detail": "ok", "status_label": "Tốt"}],
            "timeline": [{"key": "a", "tone": "warning", "title": "Job hỏng", "detail": "x", "at": at(hours=1)}],
        },
    }


def sample_jobs():
    images = [{"label": f"Ảnh {n}"} for n in range(12)]
    review = {"task_id": "TASK-1", "items": {str(n): {"url": "u", "comment": "c"} for n in range(12)}}
    return [
        # 01:00 giờ VN hôm nay
        job("today", "completed", "2026-09-10T18:00:00+00:00", "TASK-1", artifacts=images, result={"erp_review": review}),
        # 23:00 giờ VN hôm qua: trong 24 giờ nhưng không phải hôm nay
        job("yesterday", "completed", "2026-09-10T16:00:00+00:00", "TASK-0", artifacts=images),
        job("quota", "failed", at(hours=7), "TASK-9", error=QUOTA),
        job("broken", "failed", at(hours=2), "TASK-2", error="Không mở được thẻ cho ops@havigroup.llc"),
        job("old", "failed", at(days=2), "TASK-3", error="hỏng lâu rồi"),
        job(
            "busy",
            "running",
            at(minutes=1),
            "TASK-4",
            progress_snapshot={"stage_label": "Đang chờ Flow Agent", "detail": "", "last_signal_at": at(minutes=30)},
        ),
        job("cut", "interrupted", at(hours=3), "TASK-5", error="Máy chủ đã khởi động lại khi tác vụ đang chạy."),
        job("next", "queued", at(minutes=5), "TASK-6"),
    ]


class FakeFlow:
    base = "http://flow"

    def __init__(self, payload):
        self.payload = payload

    def state(self):
        return self.payload


class FlowApiTest(unittest.TestCase):
    def test_state_is_shared_for_a_few_seconds(self):
        calls = []
        now = [100.0]

        def fetch(path):
            calls.append(path)
            if len(calls) == 1:
                raise OSError("flow-v2 đang khởi động")
            return {"jobs": [], "n": len(calls)}

        api = FlowApi("http://flow/", fetch=fetch, clock=lambda: now[0])
        self.assertEqual(api.base, "http://flow")
        with self.assertRaises(OSError):
            api.state()
        first = api.state()  # lỗi không được giữ lại
        now[0] += CACHE_SECONDS - 1
        self.assertIs(api.state(), first)
        now[0] += 2
        self.assertEqual(api.state()["n"], 3)
        self.assertEqual(calls, ["/api/state"] * 3)

    def test_non_object_is_refused(self):
        with self.assertRaises(ValueError):
            FlowApi(fetch=lambda path: []).state()


class StateFileCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "state.json"
        self.now = [100.0]
        self.stamp = 1_000_000_000_000_000_000

    def write(self, jobs, text=None):
        # flow-v2 ghi lại cả tệp mỗi lần job đổi. Đặt mtime tay: hai lần ghi
        # trong cùng một tích tắc đồng hồ vẫn phải khác nhau.
        self.path.write_text(text if text is not None else json.dumps({"config": {}, "jobs": jobs}, indent=2), encoding="utf-8")
        self.stamp += 1_000_000_000
        os.utime(self.path, ns=(self.stamp, self.stamp))

    def jobs_file(self, **kwargs):
        return JobsFile(self.path, clock=lambda: self.now[0], **kwargs)


class JobsFileTest(StateFileCase):
    def test_reads_again_only_when_the_file_changes(self):
        reads = []

        def read(path):
            reads.append(path)
            return path.read_bytes()

        self.write([job("a", "running", at(minutes=1))])
        jobs = self.jobs_file(read=read)
        self.assertEqual([item["id"] for item in jobs.load()], ["a"])
        self.now[0] += READ_GAP + 1
        jobs.load()
        self.assertEqual(len(reads), 1)
        self.write([job("a", "completed", at(minutes=0))])
        self.assertEqual(jobs.load()[0]["status"], "completed")
        self.assertEqual(len(reads), 2)

    def test_reads_are_spaced_out(self):
        # Tệp thật nặng ~27 MB, flow-v2 ghi lại mỗi dòng log: đừng đọc theo từng lần ghi.
        self.write([job("a", "queued", at(minutes=2))])
        jobs = self.jobs_file()
        jobs.load()
        self.write([job("a", "running", at(minutes=1))])
        self.now[0] += READ_GAP - 0.5
        self.assertEqual(jobs.load()[0]["status"], "queued")
        self.now[0] += 1
        self.assertEqual(jobs.load()[0]["status"], "running")

    def test_half_written_file_keeps_the_last_good_read(self):
        self.write([job("a", "running", at(minutes=1))])
        jobs = self.jobs_file(gap=0)
        jobs.load()
        self.write(None, text='{"config": {}, "jobs": [{"id": "a", "sta')
        self.assertEqual(jobs.load()[0]["status"], "running")
        self.write([job("a", "completed", at(minutes=0))])
        self.assertEqual(jobs.load()[0]["status"], "completed")

    def test_file_changing_during_the_read_is_not_trusted(self):
        self.write([job("a", "running", at(minutes=1))])
        good = self.path.read_bytes()
        calls = []

        def read(path):
            calls.append(1)
            if len(calls) == 1:
                self.write([job("a", "completed", at(minutes=0))])  # flow-v2 ghi chen vào giữa lượt đọc
                return good
            return path.read_bytes()

        jobs = self.jobs_file(read=read, gap=0)
        self.assertIsNone(jobs.load())
        self.assertEqual(jobs.load()[0]["status"], "completed")  # lượt sau đọc lại cho đủ
        self.assertEqual(len(calls), 2)

    def test_missing_file_gives_nothing(self):
        jobs = self.jobs_file()
        self.assertIsNone(jobs.load())
        self.write([job("a", "running", at(minutes=1))])
        self.assertEqual(len(jobs.load()), 1)
        self.path.unlink()
        self.assertIsNone(jobs.load())

    def test_slim_job_reads_the_same(self):
        for item in sample_jobs():
            heavy = {
                **item,
                "logs": [{"message": "cũ " * 500}, {"message": "Đang tải ảnh 3/12"}],
                "input": {**item["input"], "prompt": "p" * 5000},
            }
            slim = slim_job(heavy)
            self.assertEqual(image_job_view(slim, NOW), image_job_view(heavy, NOW), item["id"])
            self.assertLess(len(json.dumps(slim)), len(json.dumps(heavy)) // 4)


class FlowApiFileTest(StateFileCase):
    def api(self, api_jobs):
        fetch = lambda path: state(api_jobs)
        return FlowApi("http://flow", fetch=fetch, clock=lambda: self.now[0], jobs_file=self.jobs_file())

    def test_newer_jobs_from_the_file_win(self):
        # /api/state được giữ 15 giây; state.json thì đổi ngay khi job đổi.
        self.write([job("a", "running", at(minutes=0), "TASK-1")])
        data = self.api([job("a", "queued", at(minutes=1), "TASK-1")]).state()
        self.assertEqual(data["jobs"][0]["status"], "running")
        self.assertEqual(data["auth"], {"authenticated": True})  # phần còn lại vẫn của /api/state
        board = build_images(self.api([]), now=NOW)
        self.assertEqual(board["kpi"]["active"], 1)

    def test_stale_file_loses(self):
        # flow-v2 đổi thư mục dữ liệu mà bảng vẫn trỏ tệp cũ: đừng hiện job cũ mãi.
        self.write([job("old", "running", at(days=3))])
        data = self.api([job("a", "completed", at(minutes=5))]).state()
        self.assertEqual([item["id"] for item in data["jobs"]], ["a"])

    def test_no_file_means_api_jobs(self):
        data = self.api([job("a", "completed", at(minutes=5))]).state()
        self.assertEqual([item["id"] for item in data["jobs"]], ["a"])


class JobViewTest(unittest.TestCase):
    def test_quota_is_not_a_real_failure(self):
        view = image_job_view(job("q", "failed", at(hours=1), "TASK-9", error=QUOTA), NOW)
        self.assertTrue(view["quota"])
        self.assertEqual((view["tone"], view["label"]), ("wait", "hết quota"))

    def test_row_fields(self):
        jobs = {item["id"]: image_job_view(item, NOW) for item in sample_jobs()}
        done = jobs["today"]
        self.assertEqual(done["title"], "Idea today")
        self.assertEqual(done["task_url"], "https://erp.havigroup.llc/app/task/TASK-1")
        self.assertEqual((done["made"], done["requested"], done["sent"]), (12, 12, 12))
        self.assertEqual(done["run_s"], 3 * 3600)  # tạo 15:00 UTC hôm qua, xong 18:00 UTC
        self.assertEqual(done["error"], "")
        self.assertIsNone(done["silent_s"])
        broken = jobs["broken"]
        self.assertEqual((broken["tone"], broken["quota"]), ("bad", False))
        self.assertNotIn("@", broken["error"])
        self.assertEqual(jobs["busy"]["silent_s"], 1800)
        self.assertEqual(jobs["busy"]["run_s"], 12 * 3600)
        self.assertEqual(jobs["cut"]["tone"], "wait")


class BuildImagesTest(unittest.TestCase):
    def test_no_flow(self):
        board = build_images(None, now=NOW)
        self.assertTrue(board["sources"]["state"])
        self.assertEqual((board["jobs"], board["alerts"], board["profiles"]), ([], [], []))
        self.assertEqual(board["kpi"]["images_today"], 0)
        self.assertIsNone(board["auth"])

    def test_flow_down_is_reported_masked(self):
        class Down:
            base = "http://flow"

            def state(self):
                raise OSError("từ chối kết nối, gửi báo cho ops@havigroup.llc")

        board = build_images(Down(), now=NOW)
        self.assertIn("từ chối", board["sources"]["state"])
        self.assertNotIn("@", board["sources"]["state"])

    def test_counts(self):
        board = build_images(FakeFlow(state(sample_jobs())), now=NOW)
        self.assertEqual(board["sources"], {"state": ""})
        self.assertEqual(
            board["kpi"],
            {
                "active": 1,
                "queued": 1,
                "done_today": 1,
                "images_today": 12,
                "failed": 1,
                "quota_failed": 1,
                "interrupted": 1,
                "profiles": 1,
                "profiles_open": 0,
                "jobs": 8,
            },
        )
        self.assertEqual([item["id"] for item in board["jobs"]][:2], ["busy", "next"])
        self.assertEqual(board["quota_until"], "14:00 11/09")
        self.assertEqual(board["health"]["signals"][0]["tone"], "ok")
        self.assertEqual(board["health"]["timeline"][0]["tone"], "wait")

    def test_alerts(self):
        board = build_images(FakeFlow(state(sample_jobs(), authenticated=False)), now=NOW)
        alerts = board["alerts"]
        texts = [item["text"] for item in alerts]
        self.assertEqual(alerts[0]["tone"], "bad")
        self.assertTrue(any("đăng nhập" in text for text in texts))
        quota = next(item for item in alerts if "Hết quota" in item["text"])
        self.assertEqual(quota["tone"], "warn")
        self.assertIn("14:00 11/09", quota["text"])
        self.assertIn("1 job đã hỏng vì quota", quota["text"])
        broken = next(item for item in alerts if item["text"].startswith("TASK-2"))
        self.assertEqual(broken["link"], "https://erp.havigroup.llc/app/task/TASK-2")
        self.assertFalse(any(text.startswith("TASK-3") for text in texts))  # hỏng quá một ngày
        self.assertTrue(any("TASK-4 không có tín hiệu 30 phút" in text for text in texts))
        self.assertTrue(any("1 job bị ngắt" in text for text in texts))

    def test_quota_open_again(self):
        board = build_images(FakeFlow(state(sample_jobs(), blocked=False)), now=NOW)
        self.assertEqual(board["quota_until"], "")
        self.assertEqual(board["kpi"]["profiles_open"], 1)
        self.assertTrue(any("Quota đã mở lại" in item["text"] for item in board["alerts"]))

    def test_many_failures_fold_into_one_line(self):
        jobs = [job(f"f{n}", "failed", at(minutes=n + 1), f"TASK-{n}", error="hỏng") for n in range(ALERT_JOBS + 4)]
        alerts = build_images(FakeFlow(state(jobs, blocked=False)), now=NOW)["alerts"]
        self.assertEqual(len(alerts), ALERT_JOBS + 1)
        self.assertIn("4 job hỏng nữa", alerts[-1]["text"])


if __name__ == "__main__":
    unittest.main()
