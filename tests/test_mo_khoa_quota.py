"""Kịch bản mở khoá quota Flow — R3 (tests/test_mo_khoa_quota.py).

Bao phủ đầy đủ 5 kịch bản A, B, C, D, E theo yêu cầu trong briefs/r3-mo-khoa.md:
- A: Thẻ cha đủ 4 thuộc tính, content: Có, 3 ảnh. Khoá: tách 3 con, 0 job.
     Mở khoá: đúng 3 job (1 job/thẻ con, erp_output_task_id đúng). Lượt 3: 0 job mới, 0 con mới.
- B: Như A nhưng có job interrupted trước khi mở khoá. Thử cả 2 thứ tự (resume trước và autorun trước):
     Mỗi thẻ con đúng 1 job còn sống, không thẻ nào 2 job sống.
- C: Thẻ cha content khác "Có": khoá hay mở cũng 0 job; thẻ con tách đúng 1 lần.
- D: Thiếu thuộc tính lúc khoá: nhắc đúng 1 lần. Bổ sung đủ: tách con, 0 job, không nhắc lại. Mở khoá: đủ job.
- E: agent_bot.autorun_pass: lúc khoá gọi mark_autorun (cooldown 900s). Giả đồng hồ vượt 900s sau mở khoá ->
     lượt kế giao lại cho hook. Ghi rõ trong báo cáo sau 20:51 chậm nhất bao lâu thẻ được chạy.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from flow_web.agent_bot import AgentBot, AgentBotConfig, AgentBotState
from flow_web.schemas import CreateJobRequest, ERPConfig, ERPIdeaBatchRequest, JobRecord
from flow_web.service import FlowBrowserProfile, FlowWebService
from flow_web.store import StateStore

PARENT = "TASK-2026-00202"

#: Bốn thuộc tính seller phải khai trên thẻ cha.
DU_BON_KHOA = "\n".join(
    [
        "product_type: Khăn tay cô dâu thêu tay",
        "product_group: Thêu tay",
        "fulfillment: HaviGroup",
        "sales_channel: Etsy",
    ]
)
CO_CONTENT = DU_BON_KHOA + "\ncontent: Có"
KHONG_CONTENT = DU_BON_KHOA + "\ncontent: Không"
THIEU_HAI = "product_type: Khăn tay cô dâu thêu tay\nfulfillment: HaviGroup\ncontent: Có"

BA_ANH = (
    "/private/files/tho-noel.jpg",
    "/private/files/xe-tai-thong.jpg",
    "/private/files/vong-hoa.jpg",
)


class _MoKhoaQuotaBaseTestCase(unittest.TestCase):
    """Kho tạm + service có ERP key/secret giả, mọi lượt ERP đều được giả."""

    def setUp(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.patches = [
            patch("flow_web.store.STATE_FILE", root / "state.json"),
            patch("flow_web.store.ensure_app_dirs", lambda: root.mkdir(parents=True, exist_ok=True)),
            patch("flow_web.service.ensure_app_dirs", lambda: root.mkdir(parents=True, exist_ok=True)),
        ]
        for item in self.patches:
            item.start()
        self.store = StateStore()
        self.service = FlowWebService(self.store)
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(
                    api_key="test-key",
                    api_secret="test-secret",
                    project_id="PROJ-0013",
                    task_id=PARENT,
                )
            )
        )
        self.profile = FlowBrowserProfile(index=0, label="Flow profile 1", path=root / "profile")
        self.is_locked = True

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tempdir.cleanup()
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()
        if pending:
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self.loop.close()
        asyncio.set_event_loop(None)

    def _khoa_quota(self, locked: bool) -> None:
        self.is_locked = locked
        if locked:
            self.service._flow_profile_quota_blocked_until = {self.profile.key: time.time() + 3600}
        else:
            self.service._flow_profile_quota_blocked_until = {}

    def _details(self, *, parent_meta: str, dropped: tuple = (), children: tuple = ()) -> dict:
        details: dict = {
            PARENT: {
                "name": PARENT,
                "subject": "Idea",
                "status": "Working",
                "description": "<p>Tạo idea cho khăn tay cô dâu thêu tay</p>",
                "cover_image": "/private/files/khan-tay.jpg",
                "meta": parent_meta,
                "children": [{"name": child, "subject": f"Idea {index + 1}"} for index, child in enumerate(children)],
                "comments": [
                    {
                        "name": f"drop-{index}",
                        "content": "",
                        "attachments": [{"file_url": url, "file_name": Path(url).name}],
                    }
                    for index, url in enumerate(dropped)
                ],
            }
        }
        for index, child in enumerate(children):
            details[child] = {
                "name": child,
                "parent_task": PARENT,
                "subject": f"Idea {index + 1}",
                "status": "Open",
                "description": "<p>Khăn tay đặt cạnh cây thông</p>",
                "cover_image": "",
                "comments": [],
            }
        return details

    def _wire(self, details: dict):
        created: list[dict] = []
        notes: list[dict] = []
        detail_reads: list[str] = []
        self.repair = AsyncMock(return_value={"republished": [], "topped_up": [], "skipped": []})

        def _read(_key, _token, task_id):
            detail_reads.append(task_id)
            return details[task_id]

        def _create(_key, _token, parent, project, subject, *, status="Open", description=""):
            child_id = f"TASK-NEW-{len(created)}"
            created.append({"id": child_id, "subject": subject})
            details[parent]["children"].append({"name": child_id, "subject": subject})
            details[child_id] = {
                "name": child_id,
                "parent_task": parent,
                "subject": subject,
                "status": status,
                "description": description or "<p>Idea content</p>",
                "cover_image": "",
                "comments": [],
            }
            return child_id

        def _attach(
            _key, _token, task_id, data, mime, name, set_cover,
            parent_comment="", comment_text="", silent_comment=False,
        ):
            url = f"/private/files/{name}"
            details[task_id].setdefault("comments", []).append(
                {"name": f"cmt-{name}", "content": comment_text, "attachments": [{"file_url": url, "file_name": name}]}
            )
            return {"url": url, "name": name}

        def _cover(_key, _token, task_id, data, _mime, name):
            details[task_id]["cover_image"] = f"/private/files/{name}"

        def _comment(_key, _token, task_id, content, parent_comment="", meta=""):
            notes.append({"task_id": task_id, "content": content, "meta": meta})
            details[task_id].setdefault("comments", []).append(
                {"name": f"note-{len(notes)}", "content": content, "meta": meta}
            )
            return {"comment": f"note-{len(notes)}"}

        def _quota_reason():
            return "mọi profile Flow đang hết quota Agent" if self.is_locked else ""

        def _update_meta(_key, _token, task_id, meta, *, project=""):
            details[task_id]["meta"] = meta
            return {"name": task_id, "meta": meta}

        wiring = patch.multiple(
            self.service,
            _erp_task_project_id=lambda *_args, **_kwargs: "PROJ-0013",
            _erp_task_detail=_read,
            _erp_task_attachment_files=lambda *_args, **_kwargs: [],
            _erp_board_name=lambda *_args, **_kwargs: "",
            _erp_create_child_task=_create,
            _erp_download_attachment_bytes=lambda _k, _t, _task, att: (
                f"bytes:{att.get('name')}".encode(),
                "image/jpeg",
            ),
            _erp_attach_file_bytes=_attach,
            _erp_set_task_cover=_cover,
            _erp_add_task_agent=lambda *_args, **_kwargs: None,
            _erp_comment=_comment,
            _erp_update_task_meta=_update_meta,
            _flow_quota_pause_reason=_quota_reason,
            sync_erp_skus=AsyncMock(return_value={"written": []}),
            repair_erp_idea_children=self.repair,
        )
        return created, notes, detail_reads, wiring

    def _autorun(self, details: dict, *, locked: bool):
        self._khoa_quota(locked)
        created, notes, detail_reads, wiring = self._wire(details)
        with wiring, patch.object(self.service, "_flow_profile_specs", return_value=[self.profile]), patch.object(
            self.service, "_run_flow_job", new_callable=AsyncMock
        ) as run:
            response = self.loop.run_until_complete(self.service._agent_bot_autorun(PARENT))
            for _ in range(3):
                self.loop.run_until_complete(asyncio.sleep(0))
        return response, created, notes, detail_reads, run

    def _so_job_song_theo_the(self, child_task_id: str) -> int:
        """Đếm số job còn sống (không thuộc trạng thái chết) của một thẻ con."""
        return len(self.service._erp_child_jobs(child_task_id))


class KichBanAMoKhoaTaoDuJobTests(_MoKhoaQuotaBaseTestCase):
    """Kịch bản A:
    Thẻ cha đủ 4 thuộc tính, content: Có, 3 ảnh.
    - Lúc khoá: tách 3 thẻ con, 0 job.
    - Mở khoá, lượt autorun kế: đúng 3 job, mỗi thẻ con 1 job, erp_output_task_id đúng từng thẻ.
    - Lượt thứ ba: 0 job mới, 0 thẻ con mới.
    """

    def test_kich_ban_a_mo_khoa_quota(self) -> None:
        details = self._details(parent_meta=CO_CONTENT, dropped=BA_ANH, children=())

        # 1. Lượt 1: Đang khoá quota
        res1, created1, notes1, _r1, run1 = self._autorun(details, locked=True)

        self.assertEqual(3, len(created1), "Khoá quota vẫn phải tách đủ 3 thẻ con")
        child_ids = [item["id"] for item in created1]
        self.assertEqual(["TASK-NEW-0", "TASK-NEW-1", "TASK-NEW-2"], child_ids)
        self.assertEqual([], res1.get("queued") or [], "Lúc khoá không được tạo bất kỳ job nào")
        self.assertIn("quota", str(res1.get("reason") or ""))
        self.assertEqual(0, len(self.store.snapshot().jobs or []))
        run1.assert_not_awaited()

        # 2. Lượt 2: Mở khoá quota
        res2, created2, notes2, _r2, run2 = self._autorun(details, locked=False)

        self.assertEqual(0, len(created2), "Lượt 2 không được tách thêm thẻ con")
        queued2 = res2.get("queued") or []
        self.assertEqual(3, len(queued2), "Mở khoá: phải xếp đúng 3 job cho 3 thẻ con")
        queued_task_ids = [item["task_id"] for item in queued2]
        self.assertEqual(child_ids, queued_task_ids)

        # Kiểm tra chi tiết từng job trong store
        jobs = list(self.store.snapshot().jobs or [])
        self.assertEqual(3, len(jobs))
        job_targets = [str(j.input.get("erp_output_task_id") or "") for j in jobs]
        self.assertEqual(set(child_ids), set(job_targets), "erp_output_task_id phải đúng từng thẻ con")
        for cid in child_ids:
            self.assertEqual(1, self._so_job_song_theo_the(cid), f"Thẻ con {cid} phải có đúng 1 job sống")

        # 3. Lượt 3: Vẫn mở khoá, autorun tiếp
        res3, created3, notes3, _r3, run3 = self._autorun(details, locked=False)

        self.assertEqual(0, len(created3), "Lượt 3: 0 thẻ con mới")
        self.assertEqual([], res3.get("queued") or [], "Lượt 3: 0 job mới")
        skipped3 = [item["task_id"] for item in res3.get("skipped") or []]
        self.assertEqual(set(child_ids), set(skipped3), "Cả 3 thẻ con đều được bỏ qua vì đã có lượt chạy")
        self.assertEqual(3, len(list(self.store.snapshot().jobs or [])), "Tổng số job trong kho vẫn đúng 3")


class KichBanBCoJobInterruptedTests(_MoKhoaQuotaBaseTestCase):
    """Kịch bản B:
    Như A, nhưng trước khi mở khoá, mỗi thẻ con có 1 job interrupted trong kho.
    Mở khoá, chạy cả resume_interrupted_erp_idea_jobs lẫn autorun:
    - Thử cả hai thứ tự: resume trước autorun sau, và autorun trước resume sau.
    - Mỗi thẻ con đúng 1 job còn sống. Không thẻ con nào 2 job sống.
    """

    def test_kich_ban_b_resume_truoc_autorun_sau(self) -> None:
        details = self._details(parent_meta=CO_CONTENT, dropped=BA_ANH, children=())

        # 1. Tách thẻ lúc khoá
        _res1, created, _n, _r, _run = self._autorun(details, locked=True)
        child_ids = [item["id"] for item in created]
        self.assertEqual(["TASK-NEW-0", "TASK-NEW-1", "TASK-NEW-2"], child_ids)

        # 2. Tạo sẵn 1 job interrupted trong kho cho mỗi thẻ con
        interrupted_ids = []
        for cid in child_ids:
            jid = f"job-interrupted-{cid}"
            job = JobRecord(
                id=jid,
                type="image",
                status="interrupted",
                title=f"Idea ({cid})",
                input={
                    "type": "image",
                    "prompt": "Test prompt",
                    "erp_output_task_id": cid,
                    "erp_enabled": True,
                    "erp_project_id": "PROJ-0013",
                    "erp_task_id": PARENT,
                },
            )
            self.loop.run_until_complete(self.store.add_job(job))
            interrupted_ids.append(jid)

        self._khoa_quota(False)
        _created, _notes, _reads, wiring = self._wire(details)
        with wiring, patch.object(self.service, "_flow_profile_specs", return_value=[self.profile]), patch.object(
            self.service, "_run_flow_job", new_callable=AsyncMock
        ):
            # Thứ tự 1: resume_interrupted_erp_idea_jobs trước
            resume_outcome = self.loop.run_until_complete(
                self.service.resume_interrupted_erp_idea_jobs(interrupted_ids)
            )
            self.assertEqual(3, len(resume_outcome.get("resumed") or []))

            # Sau đó chạy autorun
            autorun_outcome = self.loop.run_until_complete(self.service._agent_bot_autorun(PARENT))
            self.assertEqual(
                [], autorun_outcome.get("queued") or [], "Autorun không được tạo đè thêm job khi đã resume"
            )

        # Kiểm tra: mỗi thẻ con đúng 1 job còn sống, không thẻ con nào 2 job sống
        for cid in child_ids:
            live_count = self._so_job_song_theo_the(cid)
            self.assertEqual(1, live_count, f"Thẻ {cid} phải có đúng 1 job sống (không được có {live_count} job sống)")

    def test_kich_ban_b_autorun_truoc_resume_sau(self) -> None:
        details = self._details(parent_meta=CO_CONTENT, dropped=BA_ANH, children=())

        # 1. Tách thẻ lúc khoá
        _res1, created, _n, _r, _run = self._autorun(details, locked=True)
        child_ids = [item["id"] for item in created]
        self.assertEqual(["TASK-NEW-0", "TASK-NEW-1", "TASK-NEW-2"], child_ids)

        # 2. Tạo sẵn 1 job interrupted trong kho cho mỗi thẻ con
        interrupted_ids = []
        for cid in child_ids:
            jid = f"job-interrupted-{cid}"
            job = JobRecord(
                id=jid,
                type="image",
                status="interrupted",
                title=f"Idea ({cid})",
                input={
                    "type": "image",
                    "prompt": "Test prompt",
                    "erp_output_task_id": cid,
                    "erp_enabled": True,
                    "erp_project_id": "PROJ-0013",
                    "erp_task_id": PARENT,
                },
            )
            self.loop.run_until_complete(self.store.add_job(job))
            interrupted_ids.append(jid)

        self._khoa_quota(False)
        _created, _notes, _reads, wiring = self._wire(details)
        with wiring, patch.object(self.service, "_flow_profile_specs", return_value=[self.profile]), patch.object(
            self.service, "_run_flow_job", new_callable=AsyncMock
        ):
            # Thứ tự 2: autorun trước
            autorun_outcome = self.loop.run_until_complete(self.service._agent_bot_autorun(PARENT))
            self.assertEqual(3, len(autorun_outcome.get("queued") or []), "Autorun xếp 3 job mới cho 3 thẻ con")

            # Sau đó chạy resume_interrupted_erp_idea_jobs
            resume_outcome = self.loop.run_until_complete(
                self.service.resume_interrupted_erp_idea_jobs(interrupted_ids)
            )
            # Vì autorun đã xếp job rồi, resume phải bỏ qua không xếp đè
            self.assertEqual(
                0, len(resume_outcome.get("resumed") or []), "Resume phải bỏ qua các thẻ đã có job mới từ autorun"
            )
            self.assertEqual(3, len(resume_outcome.get("skipped") or []))

        # Kiểm tra: mỗi thẻ con đúng 1 job còn sống, không thẻ con nào 2 job sống
        for cid in child_ids:
            live_count = self._so_job_song_theo_the(cid)
            self.assertEqual(1, live_count, f"Thẻ {cid} phải có đúng 1 job sống (không được có {live_count} job sống)")


class KichBanCContentKhacCoTests(_MoKhoaQuotaBaseTestCase):
    """Kịch bản C:
    Thẻ cha content khác "Có": khoá hay mở cũng 0 job; thẻ con vẫn được tách đúng 1 lần.
    """

    def test_content_khac_co_khoa_hay_mo_cung_khong_job_tach_con_mot_lan(self) -> None:
        details = self._details(parent_meta=KHONG_CONTENT, dropped=BA_ANH, children=())

        # Lượt 1: Khoá
        res1, created1, _n1, _r1, run1 = self._autorun(details, locked=True)
        self.assertEqual(3, len(created1), "Thẻ con vẫn phải được tách đủ 1 lần")
        self.assertEqual([], res1.get("queued") or [])
        self.assertFalse(res1.get("content", True))
        self.assertEqual(0, len(self.store.snapshot().jobs or []))
        run1.assert_not_awaited()

        # Lượt 2: Mở khoá
        res2, created2, _n2, _r2, run2 = self._autorun(details, locked=False)
        self.assertEqual(0, len(created2), "Lượt sau không được tách lại thẻ con")
        self.assertEqual([], res2.get("queued") or [], "content khác Có thì mở khoá vẫn 0 job")
        self.assertFalse(res2.get("content", True))
        self.assertEqual(0, len(self.store.snapshot().jobs or []))
        run2.assert_not_awaited()


class KichBanDThieuThuocTinhTests(_MoKhoaQuotaBaseTestCase):
    """Kịch bản D:
    Thẻ cha thiếu thuộc tính lúc khoá: nhắc đúng 1 bình luận.
    Seller bổ sung đủ, vẫn đang khoá: tách con, 0 job, không nhắc lại.
    Mở khoá: đủ job.
    """

    def test_thieu_thuoc_tinh_nhac_mot_lan_bo_sung_tach_con_mo_khoa_du_job(self) -> None:
        # 1. Lúc khoá, thiếu thuộc tính
        details = self._details(parent_meta=THIEU_HAI, dropped=BA_ANH, children=())
        res1, created1, notes1, _r1, run1 = self._autorun(details, locked=True)

        self.assertEqual([], created1, "Thiếu thuộc tính không được tách thẻ con")
        self.assertEqual([], res1.get("queued") or [])
        self.assertTrue(res1.get("notified"), "Phải nhắc thiếu thuộc tính")
        self.assertEqual(1, len(notes1), "Chỉ nhắc đúng 1 bình luận")
        self.assertIn("product_group", notes1[0]["content"])
        self.assertIn("sales_channel", notes1[0]["content"])

        # 2. Seller bổ sung đủ, vẫn đang khoá
        details[PARENT]["meta"] = CO_CONTENT
        res2, created2, notes2, _r2, run2 = self._autorun(details, locked=True)

        self.assertEqual(3, len(created2), "Bổ sung đủ thuộc tính thì tách đủ 3 thẻ con")
        self.assertEqual([], res2.get("queued") or [], "Vẫn đang khoá thì 0 job")
        self.assertFalse(res2.get("notified", False), "Không được nhắc lại bình luận khi đã đủ thuộc tính")
        self.assertEqual(0, len(notes2), "Không có bình luận nhắc mới")

        # 3. Mở khoá
        res3, created3, notes3, _r3, run3 = self._autorun(details, locked=False)

        self.assertEqual(0, len(created3), "Không tách thêm thẻ con mới")
        queued3 = res3.get("queued") or []
        self.assertEqual(3, len(queued3), "Mở khoá: phải tạo đủ 3 job cho 3 thẻ con")
        self.assertEqual(3, len(self.store.snapshot().jobs or []))


class KichBanEAutorunPassCooldownTests(unittest.TestCase):
    """Kịch bản E:
    Bot agent_bot.autorun_pass: lượt lúc khoá có gọi mark_autorun (cooldown 900 s).
    Giả đồng hồ vượt 900 s sau khi mở khoá -> lượt kế giao lại cho hook.
    Ghi rõ trong báo cáo: sau 20:51 thì chậm nhất bao lâu thẻ được chạy.
    """

    def test_autorun_pass_cooldown_va_delay_sau_mo_khoa(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = AgentBotState(path=Path(tmp) / "state.json")
            hook_mock = AsyncMock(return_value={"parent_task_id": PARENT, "queued": []})
            config = AgentBotConfig(
                token="test-token",
                autorun=True,
                autorun_cooldown_seconds=900,
                poll_seconds=120,
            )
            bot = AgentBot(config=config, client=AsyncMock(), state=state, autorun_hook=hook_mock)

            # Cây thẻ cha có ảnh bìa + 2 ảnh idea
            tree = {
                "root": {
                    "name": PARENT,
                    "subject": "Idea cha",
                    "child_total": 0,
                    "cover_image": "/private/files/bia.jpg",
                    "comments": [
                        {
                            "attachments": [
                                {"file_url": "/private/files/1.jpg", "file_name": "1.jpg"},
                                {"file_url": "/private/files/2.jpg", "file_name": "2.jpg"},
                            ]
                        }
                    ],
                }
            }

            loop = asyncio.new_event_loop()
            try:
                # 1. Lượt lúc khoá (ở thời điểm T0): autorun_pass gọi hook và gọi mark_autorun
                res1 = loop.run_until_complete(bot.autorun_pass(tree))
                self.assertIsNotNone(res1)
                self.assertEqual(PARENT, res1["task"])
                hook_mock.assert_awaited_once_with(PARENT)
                self.assertIn(PARENT, state.runs, "Phải ghi nhận mark_autorun cho thẻ cha")

                # 2. Vòng quét kế tiếp ngay sau đó (< 900s, ví dụ sau 120s): bị cooldown chặn
                hook_mock.reset_mock()
                res2 = loop.run_until_complete(bot.autorun_pass(tree))
                self.assertIsNone(res2, "Trong vòng 900s, autorun_pass phải trả về None do cooldown")
                hook_mock.assert_not_awaited()

                # 3. Giả đồng hồ vượt 900s sau khi mở khoá (ví dụ 901 giây kể từ lần chạy trước)
                t_past = (datetime.now(timezone.utc) - timedelta(seconds=901)).isoformat()
                state.runs[PARENT] = t_past

                # Lượt kế tiếp: cooldown đã hết -> giao lại cho hook
                res3 = loop.run_until_complete(bot.autorun_pass(tree))
                self.assertIsNotNone(res3, "Sau khi vượt cooldown 900s, thẻ phải được giao lại cho hook")
                self.assertEqual(PARENT, res3["task"])
                hook_mock.assert_awaited_once_with(PARENT)

                # 4. Khẳng định tính toán thời gian chậm nhất sau 20:51
                # - Thời gian cooldown: 900 giây (15 phút).
                # - Chu kỳ vòng quét của bot: config.poll_seconds = 120 giây (2 phút).
                # - Trường hợp xấu nhất: thẻ vừa được autorun lúc 20:50:59 ngay trước khi mở khoá lúc 20:51:00.
                #   Cooldown sẽ hết lúc 21:05:59 (15 phút).
                #   Vòng quét của bot nhận thẻ ở lần quét kế tiếp (tối đa thêm 120s).
                #   -> Thời gian chậm nhất thẻ được chạy lại sau 20:51 là: 900s + 120s = 1020s (17 phút), tức khoảng 21:08.
                cooldown = config.autorun_cooldown_seconds
                interval = config.poll_seconds
                worst_case_seconds = cooldown + interval
                self.assertEqual(900, cooldown)
                self.assertEqual(120, interval)
                self.assertEqual(1020, worst_case_seconds)
            finally:
                loop.close()


if __name__ == "__main__":
    unittest.main()
