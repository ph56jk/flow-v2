"""Hết quota Flow vẫn phải tách thẻ con và nhắc thuộc tính — tối 11/09.

Mọi profile Flow bị khoá quota (24 giờ trượt, có chủ ý) thì ``_agent_bot_autorun``
từng ``return`` ngay sau bước vá, không tới ``enqueue_erp_idea_jobs``.  Mà chốt
thuộc tính, nhắc thiếu, tách ảnh bình luận thành thẻ con nằm cả trong đó và
không cần Flow.  Hậu quả: seller thả ảnh cả ngày không thấy thẻ con nào, không
được nhắc thiếu thuộc tính, cho tới khi quota mở lại.

Yêu cầu: khoá quota thì vẫn chốt thuộc tính, vẫn tách thẻ con, chỉ KHÔNG tạo job
ảnh (kể cả thẻ cha khai ``content: Có``).  Hết khoá thì y hệt cũ.  Nút tay trên
dashboard không đổi.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from flow_web.schemas import ERPConfig, ERPIdeaBatchRequest
from flow_web.service import FlowBrowserProfile, FlowWebService
from flow_web.store import StateStore

PARENT = "TASK-2026-00202"
CHILD_A = "TASK-2026-00615"
CHILD_B = "TASK-2026-00616"

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
THIEU_HAI = "product_type: Khăn tay cô dâu thêu tay\nfulfillment: HaviGroup\ncontent: Có"

BA_ANH = (
    "/private/files/tho-noel.jpg",
    "/private/files/xe-tai-thong.jpg",
    "/private/files/vong-hoa.jpg",
)


class _HetQuotaTestCase(unittest.TestCase):
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

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tempdir.cleanup()
        self.loop.close()
        asyncio.set_event_loop(None)

    def _khoa_quota(self, locked: bool) -> None:
        """Khoá (hay mở) quota của profile Flow duy nhất trong test."""
        if locked:
            self.service._flow_profile_quota_blocked_until = {self.profile.key: time.time() + 3600}
        else:
            self.service._flow_profile_quota_blocked_until = {}

    def _details(self, *, parent_meta: str, dropped: tuple = (), children: tuple = (CHILD_A, CHILD_B)) -> dict:
        """Thẻ cha có ảnh sản phẩm làm bìa, N ảnh idea thả trong bình luận."""
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
                "subject": f"Idea {index + 1}",
                "status": "Open",
                "description": "<p>Khăn tay đặt cạnh cây thông</p>",
                "cover_image": "",
                "comments": [],
            }
        return details

    def _wire(self, details: dict):
        """Thay mọi lượt ghi ERP bằng hàm giả, ghi lại những gì bot làm."""
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
                "subject": subject,
                "status": status,
                "description": description,
                "cover_image": "",
                "comments": [],
            }
            return child_id

        def _attach(
            _key, _token, task_id, data, mime, name, set_cover,
            parent_comment="", comment_text="", silent_comment=False,
        ):
            url = f"/private/files/{name}"
            details[task_id]["comments"].append(
                {"name": f"cmt-{name}", "content": comment_text, "attachments": [{"file_url": url, "file_name": name}]}
            )
            return {"url": url, "name": name}

        def _cover(_key, _token, task_id, data, _mime, name):
            details[task_id]["cover_image"] = f"/private/files/{name}"

        def _comment(_key, _token, task_id, content, parent_comment="", meta=""):
            notes.append({"task_id": task_id, "content": content, "meta": meta})
            # ERP thật: bình luận vừa đăng hiện ra ở lần đọc thẻ sau.
            details[task_id].setdefault("comments", []).append(
                {"name": f"note-{len(notes)}", "content": content, "meta": meta}
            )
            return {"comment": f"note-{len(notes)}"}

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
            # Cấp SKU là việc của bộ khác; chặn lại để test không gọi ERP thật.
            sync_erp_skus=AsyncMock(return_value={"written": []}),
            # Vá thẻ con là bước riêng, giữ nguyên; ở đây chỉ ghi nhận nó được gọi.
            repair_erp_idea_children=self.repair,
        )
        return created, notes, detail_reads, wiring

    def _autorun(self, details: dict, *, locked: bool):
        """Một lượt autorun của bot trên thẻ cha, quota khoá hay mở tuỳ ``locked``."""
        self._khoa_quota(locked)
        created, notes, detail_reads, wiring = self._wire(details)
        with wiring, patch.object(self.service, "_flow_profile_specs", return_value=[self.profile]), patch.object(
            self.service, "_run_flow_job", new_callable=AsyncMock
        ) as run:
            # Lý do quota đọc trong cùng ngữ cảnh patch, để so với ``reason`` trả về.
            self.paused = self.service._flow_quota_pause_reason()
            response = self.loop.run_until_complete(self.service._agent_bot_autorun(PARENT))
            for _ in range(3):
                self.loop.run_until_complete(asyncio.sleep(0))
        return response, created, notes, detail_reads, run

    def _watcher(self, details: dict, *, locked: bool):
        """Một vòng watcher thẻ Idea cha cấu hình sẵn (``autorun_erp_idea_children``)."""
        self._khoa_quota(locked)
        created, notes, detail_reads, wiring = self._wire(details)
        with wiring, patch.object(self.service, "_flow_profile_specs", return_value=[self.profile]), patch.object(
            self.service, "_run_flow_job", new_callable=AsyncMock
        ) as run:
            self.paused = self.service._flow_quota_pause_reason()
            response = self.loop.run_until_complete(self.service.autorun_erp_idea_children())
            for _ in range(3):
                self.loop.run_until_complete(asyncio.sleep(0))
        return response, created, notes, detail_reads, run

    def _nut_tay(self, details: dict, *, locked: bool, request: ERPIdeaBatchRequest | None = None):
        """Nút "Chạy" trên dashboard: gọi thẳng ``enqueue_erp_idea_jobs``."""
        self._khoa_quota(locked)
        created, notes, detail_reads, wiring = self._wire(details)
        with wiring, patch.object(self.service, "_flow_profile_specs", return_value=[self.profile]), patch.object(
            self.service, "_run_flow_job", new_callable=AsyncMock
        ) as run:
            response = self.loop.run_until_complete(
                self.service.enqueue_erp_idea_jobs(request or ERPIdeaBatchRequest(task_id=PARENT))
            )
            for _ in range(3):
                self.loop.run_until_complete(asyncio.sleep(0))
        return response, created, notes, detail_reads, run

    def _so_job_trong_kho(self) -> int:
        return len(list(self.store.snapshot().jobs or []))


class KhoaQuotaVanChotThuocTinhTests(_HetQuotaTestCase):
    """Khoá quota, thiếu thuộc tính: vẫn nhắc trên thẻ, đúng một lần."""

    def test_thieu_thuoc_tinh_thi_van_nhac_tren_the(self) -> None:
        details = self._details(parent_meta=THIEU_HAI, dropped=BA_ANH[:1])

        response, created, notes, _reads, run = self._autorun(details, locked=True)

        self.assertEqual(["product_group", "sales_channel"], response["missing_meta"])
        self.assertTrue(response["notified"])
        self.assertEqual(1, len(notes))
        self.assertEqual(PARENT, notes[0]["task_id"])
        self.assertIn("product_group", notes[0]["content"])
        self.assertIn("sales_channel", notes[0]["content"])
        self.assertEqual([], created)
        self.assertEqual([], response["queued"])
        run.assert_not_awaited()

    def test_luot_hai_khong_nhac_them(self) -> None:
        details = self._details(parent_meta=THIEU_HAI, dropped=BA_ANH[:1])

        first, _c, notes, _r, _run = self._autorun(details, locked=True)
        second, _c, notes2, _r, _run = self._autorun(details, locked=True)

        self.assertTrue(first["notified"])
        self.assertFalse(second["notified"])
        self.assertEqual(1, len(notes) + len(notes2))

    def test_thieu_thuoc_tinh_khong_doc_them_the_nao_khac(self) -> None:
        # Trần ~60 request/phút chung: chốt hụt thì dừng ngay ở thẻ cha.
        details = self._details(parent_meta=THIEU_HAI, dropped=BA_ANH[:1])

        _resp, _c, _n, reads, _run = self._autorun(details, locked=True)

        self.assertEqual([PARENT], reads)


class KhoaQuotaVanTachTheConTests(_HetQuotaTestCase):
    """Khoá quota, đủ thuộc tính: tách ảnh thành thẻ con, không một job ảnh nào."""

    def test_ba_anh_thanh_ba_the_con_khong_job(self) -> None:
        details = self._details(parent_meta=DU_BON_KHOA, dropped=BA_ANH)

        response, created, notes, _r, run = self._autorun(details, locked=True)

        self.assertEqual(["TASK-NEW-0", "TASK-NEW-1", "TASK-NEW-2"], [item["id"] for item in created])
        self.assertEqual(
            ["TASK-NEW-0", "TASK-NEW-1", "TASK-NEW-2"], [item["task_id"] for item in response["created"]]
        )
        self.assertEqual([], response["queued"])
        self.assertEqual([], notes)
        self.assertEqual(0, self._so_job_trong_kho())
        run.assert_not_awaited()

    def test_anh_tha_lam_anh_dai_dien_the_con(self) -> None:
        details = self._details(parent_meta=DU_BON_KHOA, dropped=BA_ANH)

        self._autorun(details, locked=True)

        self.assertEqual("/private/files/tho-noel.jpg", details["TASK-NEW-0"]["cover_image"])
        self.assertEqual("/private/files/xe-tai-thong.jpg", details["TASK-NEW-1"]["cover_image"])
        self.assertEqual("/private/files/vong-hoa.jpg", details["TASK-NEW-2"]["cover_image"])

    def test_ly_do_noi_ro_het_quota(self) -> None:
        details = self._details(parent_meta=CO_CONTENT, dropped=BA_ANH)

        response, _c, _n, _r, _run = self._autorun(details, locked=True)

        self.assertIn("hết quota Agent", response["reason"])
        self.assertEqual(self.paused, response["reason"])

    def test_chua_khai_content_thi_ly_do_van_la_content(self) -> None:
        # Chốt content đứng trước chốt quota: thẻ chưa khai content thì dù
        # quota có mở hay khoá, seller cũng đọc được cùng một lời giải thích.
        details = self._details(parent_meta=DU_BON_KHOA, dropped=BA_ANH)

        response, created, _n, _r, _run = self._autorun(details, locked=True)

        self.assertEqual(3, len(created))
        self.assertEqual([], response["queued"])
        self.assertIn("content", response["reason"])
        self.assertNotIn("quota", response["reason"])

    def test_luot_sau_khong_tach_lai(self) -> None:
        # Thẻ con đã mang ảnh thì lượt autorun sau (sau cooldown) không đẻ thêm.
        details = self._details(parent_meta=DU_BON_KHOA, dropped=BA_ANH[:2])

        first, created, _n, _r, _run = self._autorun(details, locked=True)
        second, created2, _n, _r, _run = self._autorun(details, locked=True)

        self.assertEqual(2, len(first["created"]))
        self.assertEqual([], second["created"])
        self.assertEqual(2, len(created) + len(created2))

    def test_van_va_the_con_truoc_khi_tach(self) -> None:
        details = self._details(parent_meta=DU_BON_KHOA, dropped=BA_ANH[:1])

        response, _c, _n, _r, _run = self._autorun(details, locked=True)

        self.repair.assert_awaited_once_with(PARENT)
        self.assertEqual({"republished": [], "topped_up": [], "skipped": []}, response["repaired"])


class KhoaQuotaContentCoTests(_HetQuotaTestCase):
    """Khoá quota, thẻ cha khai ``content: Có``: vẫn tách, vẫn 0 job, lý do là quota."""

    def test_content_co_van_khong_tao_job(self) -> None:
        details = self._details(parent_meta=CO_CONTENT, dropped=BA_ANH[:1])

        response, created, _n, _r, run = self._autorun(details, locked=True)

        self.assertEqual(["TASK-NEW-0"], [item["task_id"] for item in response["created"]])
        self.assertEqual(1, len(created))
        self.assertEqual([], response["queued"])
        self.assertEqual(0, self._so_job_trong_kho())
        self.assertIn("hết quota Agent", response["reason"])
        run.assert_not_awaited()

    def test_khong_doc_the_con_nao_khi_da_khoa(self) -> None:
        # Không xếp job thì không cần đọc thẻ con để xếp: giữ trần request ERP.
        details = self._details(parent_meta=CO_CONTENT, dropped=())

        _resp, _c, _n, reads, _run = self._autorun(details, locked=True)

        self.assertEqual([PARENT], reads)


class HetKhoaThiNhuCuTests(_HetQuotaTestCase):
    """Quota còn: đường autorun y hệt cũ."""

    def test_content_co_thi_tao_job_nhu_cu(self) -> None:
        details = self._details(parent_meta=CO_CONTENT, dropped=BA_ANH[:1])

        response, created, _n, _r, run = self._autorun(details, locked=False)

        self.assertEqual(1, len(created))
        self.assertEqual([CHILD_A, CHILD_B, "TASK-NEW-0"], [item["task_id"] for item in response["queued"]])
        self.assertEqual(3, self._so_job_trong_kho())
        self.assertNotIn("quota", str(response.get("reason") or ""))
        self.assertTrue(run.await_count >= 1)

    def test_khong_content_thi_chi_tach(self) -> None:
        details = self._details(parent_meta=DU_BON_KHOA, dropped=BA_ANH[:2])

        response, created, _n, _r, run = self._autorun(details, locked=False)

        self.assertEqual(2, len(created))
        self.assertEqual([], response["queued"])
        self.assertIn("content", response["reason"])
        run.assert_not_awaited()


class WatcherKhoaQuotaTests(_HetQuotaTestCase):
    """Watcher thẻ Idea cha cấu hình sẵn đi cùng luật với bot: khoá quota vẫn tách, 0 job."""

    def test_watcher_khoa_quota_van_tach_the_con_khong_job(self) -> None:
        details = self._details(parent_meta=CO_CONTENT, dropped=BA_ANH)

        response, created, _n, _r, run = self._watcher(details, locked=True)

        self.assertEqual(PARENT, response["parent_task_id"])
        self.assertEqual(["TASK-NEW-0", "TASK-NEW-1", "TASK-NEW-2"], [item["id"] for item in created])
        self.assertEqual(
            ["TASK-NEW-0", "TASK-NEW-1", "TASK-NEW-2"], [item["task_id"] for item in response["created"]]
        )
        self.assertEqual([], response["queued"])
        self.assertEqual(0, self._so_job_trong_kho())
        self.assertEqual(self.paused, response["reason"])
        self.assertIn("hết quota Agent", response["reason"])
        run.assert_not_awaited()

    def test_watcher_khoa_quota_van_nhac_thieu_thuoc_tinh(self) -> None:
        details = self._details(parent_meta=THIEU_HAI, dropped=BA_ANH[:1])

        response, created, notes, reads, _run = self._watcher(details, locked=True)

        self.assertEqual(["product_group", "sales_channel"], response["missing_meta"])
        self.assertTrue(response["notified"])
        self.assertEqual(1, len(notes))
        self.assertEqual([], created)
        self.assertEqual([PARENT], reads)

    def test_watcher_van_va_truoc_khi_tach(self) -> None:
        details = self._details(parent_meta=DU_BON_KHOA, dropped=BA_ANH[:1])

        response, _c, _n, _r, _run = self._watcher(details, locked=True)

        self.repair.assert_awaited_once_with(PARENT)
        self.assertEqual({"republished": [], "topped_up": [], "skipped": []}, response["repaired"])

    def test_watcher_het_khoa_thi_nhu_cu(self) -> None:
        details = self._details(parent_meta=CO_CONTENT, dropped=BA_ANH[:1])

        response, created, _n, _r, run = self._watcher(details, locked=False)

        self.assertEqual(1, len(created))
        self.assertEqual([CHILD_A, CHILD_B, "TASK-NEW-0"], [item["task_id"] for item in response["queued"]])
        self.assertEqual(3, self._so_job_trong_kho())
        self.assertNotIn("quota", str(response.get("reason") or ""))
        self.assertTrue(run.await_count >= 1)


class NutTayKhongDoiTests(_HetQuotaTestCase):
    """Nút tay trên dashboard gọi thẳng ``enqueue_erp_idea_jobs``: không chốt quota."""

    def test_nut_tay_khoa_quota_van_xep_job_nhu_cu(self) -> None:
        details = self._details(parent_meta=CO_CONTENT, dropped=BA_ANH[:1])

        response, created, _n, _r, _run = self._nut_tay(details, locked=True)

        self.assertEqual(1, len(created))
        self.assertEqual([CHILD_A, CHILD_B, "TASK-NEW-0"], [item["task_id"] for item in response["queued"]])
        self.assertEqual(3, self._so_job_trong_kho())
        self.assertNotIn("quota", str(response.get("reason") or ""))

    def test_nut_tay_khong_content_van_chi_tach(self) -> None:
        details = self._details(parent_meta=DU_BON_KHOA, dropped=BA_ANH[:1])

        response, created, _n, _r, run = self._nut_tay(details, locked=True)

        self.assertEqual(1, len(created))
        self.assertEqual([], response["queued"])
        self.assertIn("content", response["reason"])
        run.assert_not_awaited()

    def test_nut_tay_khong_can_tham_so_moi(self) -> None:
        # Request từ dashboard giữ nguyên hình dạng: chốt quota không chui vào schema.
        request = ERPIdeaBatchRequest(task_id=PARENT)

        self.assertFalse(hasattr(request, "hold_jobs_reason"))


if __name__ == "__main__":
    unittest.main()
