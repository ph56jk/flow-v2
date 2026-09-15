"""Quy trình đẩy ảnh idea và tạo ảnh content — a Trung Anh, 11/09 17:01.

Seller tạo thẻ idea, chuyển thành thẻ cha, khai bốn thuộc tính rồi thả N ảnh
vào bình luận.  Bot tách N thẻ con, ảnh làm ảnh đại diện.  Ảnh content chỉ làm
khi thẻ cha khai ``content: Có``.  Thẻ con đủ ảnh theo prompt thì gắn nhãn DONE.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from flow_web.schemas import (
    CreateJobRequest,
    ERPConfig,
    ERPIdeaBatchRequest,
    JobArtifact,
    JobRecord,
)
from flow_web.service import FlowWebService
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


class _QuyTrinhTestCase(unittest.TestCase):
    """Kho tạm + service có ERP key/secret giả, không gọi ra ngoài."""

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

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tempdir.cleanup()
        self.loop.close()
        asyncio.set_event_loop(None)

    def _details(
        self,
        *,
        parent_meta: str,
        dropped: tuple = (),
        children: tuple = (CHILD_A, CHILD_B),
        parent_comments: list | None = None,
    ) -> dict:
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
                ]
                + list(parent_comments or []),
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

    def _wire(self, details: dict, *, echo_notes: bool = True):
        """Thay mọi lượt ghi ERP bằng hàm giả, ghi lại những gì bot làm."""
        created: list[dict] = []
        notes: list[dict] = []
        detail_reads: list[str] = []

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
            if echo_notes:
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
            # Cấp SKU là việc của bộ khác; ở đây chặn lại để test không gọi ERP thật.
            sync_erp_skus=AsyncMock(return_value={"written": []}),
        )
        return created, notes, detail_reads, wiring

    def _enqueue(self, details: dict, request: ERPIdeaBatchRequest | None = None, *, echo_notes: bool = True):
        created, notes, detail_reads, wiring = self._wire(details, echo_notes=echo_notes)
        with wiring, patch.object(self.service, "_run_flow_job", new_callable=AsyncMock) as run:
            response = self.loop.run_until_complete(
                self.service.enqueue_erp_idea_jobs(request or ERPIdeaBatchRequest(task_id=PARENT))
            )
            for _ in range(3):
                self.loop.run_until_complete(asyncio.sleep(0))
        return response, created, notes, detail_reads, run


class ChotBonThuocTinhTests(_QuyTrinhTestCase):
    """Thiếu một thuộc tính là không tách, không tạo ảnh; bot báo trên thẻ."""

    THIEU_HAI = "product_type: Khăn tay cô dâu thêu tay\nfulfillment: HaviGroup\ncontent: Có"

    def test_bon_khoa_bat_buoc_dung_ten_quy_trinh(self) -> None:
        self.assertEqual(
            ("product_type", "product_group", "fulfillment", "sales_channel"),
            FlowWebService.ERP_IDEA_REQUIRED_META,
        )

    def test_thieu_thuoc_tinh_thi_khong_tach_khong_tao_anh(self) -> None:
        details = self._details(
            parent_meta=self.THIEU_HAI,
            dropped=("/private/files/tho-noel.jpg", "/private/files/xe-tai-thong.jpg"),
        )

        response, created, _notes, _reads, run = self._enqueue(details)

        self.assertEqual([], created)
        self.assertEqual([], response["created"])
        self.assertEqual([], response["queued"])
        self.assertEqual(["product_group", "sales_channel"], response["missing_meta"])
        run.assert_not_awaited()

    def test_bot_bao_tren_the_cha_dung_khoa_con_thieu(self) -> None:
        details = self._details(parent_meta=self.THIEU_HAI, dropped=("/private/files/tho-noel.jpg",))

        response, _created, notes, _reads, _run = self._enqueue(details)

        self.assertTrue(response["notified"])
        self.assertEqual(1, len(notes))
        self.assertEqual(PARENT, notes[0]["task_id"])
        self.assertIn("product_group", notes[0]["content"])
        self.assertIn("sales_channel", notes[0]["content"])
        self.assertNotIn("product_type", notes[0]["content"].split("product_group")[0])
        self.assertIn(FlowWebService.ERP_IDEA_META_NOTE_MARK, notes[0]["meta"])

    def test_chi_bao_mot_lan_cho_moi_bo_khoa_thieu(self) -> None:
        details = self._details(parent_meta=self.THIEU_HAI, dropped=("/private/files/tho-noel.jpg",))

        first, _c, notes, _r, _run = self._enqueue(details)
        second, _c, notes2, _r, _run = self._enqueue(details)

        self.assertTrue(first["notified"])
        self.assertFalse(second["notified"])
        self.assertEqual(1, len(notes) + len(notes2))

    def test_khong_bao_lai_ke_ca_khi_the_doc_ve_chua_thay_binh_luan(self) -> None:
        # Bot vừa đăng mà ERP trả thẻ cũ (cache) thì vẫn không được đăng lần hai.
        details = self._details(parent_meta=self.THIEU_HAI, dropped=("/private/files/tho-noel.jpg",))

        self._enqueue(details, echo_notes=False)
        second, _c, notes, _r, _run = self._enqueue(details, echo_notes=False)

        self.assertFalse(second["notified"])
        self.assertEqual([], notes)

    def test_da_bao_tren_the_thi_sau_khoi_dong_lai_khong_bao_nua(self) -> None:
        # Sổ nhớ trong RAM mất khi app khởi động lại; dấu trên bình luận thì còn.
        marker = f"{FlowWebService.ERP_IDEA_META_NOTE_MARK} thiếu=product_group,sales_channel"
        details = self._details(
            parent_meta=self.THIEU_HAI,
            dropped=("/private/files/tho-noel.jpg",),
            parent_comments=[{"name": "note-cu", "content": "Thẻ thiếu thuộc tính", "meta": marker}],
        )

        response, _c, notes, _r, _run = self._enqueue(details)

        self.assertFalse(response["notified"])
        self.assertEqual([], notes)

    def test_bo_khoa_thieu_doi_thi_bao_lai(self) -> None:
        details = self._details(parent_meta=self.THIEU_HAI, dropped=("/private/files/tho-noel.jpg",))
        self._enqueue(details)
        # Seller khai thêm một khoá, vẫn còn thiếu một: bộ khoá đổi, báo lại.
        details[PARENT]["meta"] = self.THIEU_HAI + "\nproduct_group: Thêu tay"

        response, _c, notes, _r, _run = self._enqueue(details)

        self.assertTrue(response["notified"])
        self.assertEqual(["sales_channel"], response["missing_meta"])
        self.assertEqual(1, len(notes))
        self.assertIn("sales_channel", notes[0]["content"])
        self.assertNotIn("product_group", notes[0]["content"])

    def test_khoa_khong_phan_biet_hoa_thuong(self) -> None:
        detail = {
            "meta": "Product_Type: Khăn tay\nPRODUCT_GROUP: Thêu tay\nFulfillment: HaviGroup\nSales_Channel: Etsy"
        }

        self.assertEqual([], self.service._erp_idea_missing_meta(detail))

    def test_khoa_co_ma_gia_tri_trong_van_la_thieu(self) -> None:
        detail = {"meta": "product_type: Khăn tay\nproduct_group:\nfulfillment: HaviGroup\nsales_channel: Etsy"}

        self.assertEqual(["product_group"], self.service._erp_idea_missing_meta(detail))

    def test_the_khong_co_khoi_thuoc_tinh_thi_thieu_ca_bon(self) -> None:
        self.assertEqual(
            ["product_type", "product_group", "fulfillment", "sales_channel"],
            self.service._erp_idea_missing_meta({"name": PARENT}),
        )

    def test_thieu_thuoc_tinh_khong_doc_them_the_nao_khac(self) -> None:
        # Trần ~60 request/phút chung ba máy: chốt hụt thì dừng ngay ở thẻ cha.
        details = self._details(parent_meta=self.THIEU_HAI, dropped=("/private/files/tho-noel.jpg",))

        _resp, _c, _notes, reads, _run = self._enqueue(details)

        self.assertEqual([PARENT], reads)

    def test_nut_tay_tren_dashboard_cung_bi_chot(self) -> None:
        details = self._details(parent_meta=self.THIEU_HAI)

        response, _c, notes, _r, run = self._enqueue(
            details,
            ERPIdeaBatchRequest(task_id=PARENT, child_task_ids=[CHILD_A], count=6, include_done=True),
        )

        self.assertEqual([], response["queued"])
        self.assertEqual(1, len(notes))
        run.assert_not_awaited()


class TachIdeaConTests(_QuyTrinhTestCase):
    """Đủ bốn khoá thì tách N ảnh thành N thẻ con, kể cả khi không có content."""

    def test_du_bon_khoa_khong_content_thi_tach_the_con_nhung_khong_tao_anh(self) -> None:
        details = self._details(
            parent_meta=DU_BON_KHOA,
            dropped=("/private/files/tho-noel.jpg", "/private/files/xe-tai-thong.jpg"),
        )

        response, created, notes, _r, run = self._enqueue(details)

        self.assertEqual(["TASK-NEW-0", "TASK-NEW-1"], [item["id"] for item in created])
        self.assertEqual(["TASK-NEW-0", "TASK-NEW-1"], [item["task_id"] for item in response["created"]])
        self.assertEqual([], response["queued"])
        self.assertIn("content", response["reason"])
        self.assertEqual([], notes)
        run.assert_not_awaited()

    def test_anh_tha_lam_anh_dai_dien_the_con(self) -> None:
        details = self._details(parent_meta=DU_BON_KHOA, dropped=("/private/files/tho-noel.jpg",))

        self._enqueue(details)

        self.assertEqual("/private/files/tho-noel.jpg", details["TASK-NEW-0"]["cover_image"])

    def test_content_khac_co_cung_khong_tao_anh(self) -> None:
        details = self._details(parent_meta=DU_BON_KHOA + "\ncontent: Không", dropped=("/private/files/tho-noel.jpg",))

        response, created, _n, _r, run = self._enqueue(details)

        self.assertEqual(1, len(created))
        self.assertEqual([], response["queued"])
        run.assert_not_awaited()

    def test_content_co_thi_tao_anh_nhu_cu(self) -> None:
        details = self._details(parent_meta=CO_CONTENT, dropped=("/private/files/tho-noel.jpg",))

        response, created, _n, _r, run = self._enqueue(details)

        self.assertEqual(1, len(created))
        self.assertEqual(
            [CHILD_A, CHILD_B, "TASK-NEW-0"], [item["task_id"] for item in response["queued"]]
        )
        self.assertTrue(run.await_count >= 1)

    def test_content_khong_doc_them_request_nao(self) -> None:
        # Khoá content đọc từ chính ``parent_detail`` đã lấy: không hỏi ERP thêm
        # cho riêng nó. Lượt đọc thẻ con dưới đây là của phần đổ Thuộc tính của
        # cha xuống thẻ con (thẻ tạo tay cũng phải đủ), chứ không phải của chốt
        # content.
        details = self._details(parent_meta=DU_BON_KHOA, dropped=())

        _resp, _c, _n, reads, _run = self._enqueue(details)

        # Mỗi thẻ con tốn hai lượt đọc: fill nhìn trước, ``inherit_task_meta``
        # đọc lại ngay trước khi ghi (ghi từ bản cũ là xoá ô người vừa gõ).
        self.assertEqual([PARENT, CHILD_A, CHILD_A, CHILD_B, CHILD_B], reads)

    def test_cac_cach_viet_co(self) -> None:
        for value in ("Có", "có", "co", "CÓ", "yes", "Yes", "true", "TRUE", "1", " Có "):
            with self.subTest(value=value):
                self.assertTrue(self.service._erp_idea_content_enabled({"meta": f"content: {value}"}))
        for value in ("", "Không", "không", "khong", "no", "false", "0", "chưa"):
            with self.subTest(value=value):
                self.assertFalse(self.service._erp_idea_content_enabled({"meta": f"content: {value}"}))
        self.assertFalse(self.service._erp_idea_content_enabled({"meta": DU_BON_KHOA}))
        self.assertTrue(self.service._erp_idea_content_enabled({"meta": "CONTENT: Có"}))


class ChotContentMoiDuongTests(_QuyTrinhTestCase):
    """Nút tay, chạy bù và xếp lại sau khởi động đều theo cùng một chốt content."""

    def test_nut_tay_tren_dashboard_cung_bi_chot_content(self) -> None:
        details = self._details(parent_meta=DU_BON_KHOA)

        response, _c, _n, _r, run = self._enqueue(
            details,
            ERPIdeaBatchRequest(task_id=PARENT, child_task_ids=[CHILD_A], count=6, include_done=True),
        )

        self.assertEqual([], response["queued"])
        self.assertIn("content", response["reason"])
        run.assert_not_awaited()

    def _topup_board(self, parent_meta: str, *, images: int = 1, wanted: int = 12) -> dict:
        """Một lượt hứa 12 ảnh mà Flow trả 1: ảnh ấy đã lên thẻ chờ duyệt, 11 tấm kia chưa từng có."""
        job = JobRecord(
            type="image",
            status="completed",
            title=f"Idea 1 ({CHILD_A})",
            input={"erp_output_task_id": CHILD_A, "count": wanted, "erp_enabled": True},
            artifacts=[
                JobArtifact(media_name=f"idea-{index}.jpg", url=f"https://media.example/idea-{index}.jpg")
                for index in range(images)
            ],
        )
        self.loop.run_until_complete(self.store.add_job(job))
        details = self._details(parent_meta=parent_meta, children=(CHILD_A,))
        details[CHILD_A]["comments"] = [
            {
                "name": f"cmt-{index}",
                "content": "​",
                "meta": f"[FLOW_V2_REVIEW {job.id}#{index}]",
                "attachments": [{"file_url": f"/files/flow-{index}.jpg"}],
            }
            for index in range(images)
        ]
        return details

    def _repair(self, details: dict):
        with patch.dict(os.environ, {"ERP_IDEA_TOPUP": "1"}), patch.object(
            self.service, "_erp_task_project_id", return_value="PROJ-0013"
        ), patch.object(
            self.service, "_erp_task_detail", side_effect=lambda _k, _t, task_id: details[task_id]
        ), patch.object(
            self.service, "publish_erp_review", new_callable=AsyncMock
        ), patch.object(
            self.service, "enqueue_erp_idea_jobs", new_callable=AsyncMock
        ) as enqueue:
            enqueue.return_value = {"queued": []}
            response = self.loop.run_until_complete(self.service.repair_erp_idea_children())
        return response, enqueue

    def test_chay_bu_bi_chot_khi_khong_content(self) -> None:
        details = self._topup_board(DU_BON_KHOA)

        response, enqueue = self._repair(details)

        self.assertEqual([], response["topped_up"])
        self.assertEqual([CHILD_A], [item["task_id"] for item in response["skipped"]])
        self.assertIn("content", response["skipped"][0]["reason"])
        enqueue.assert_not_awaited()

    def test_chay_bu_bi_chot_khi_thieu_thuoc_tinh(self) -> None:
        details = self._topup_board("product_type: Khăn tay\ncontent: Có")

        response, enqueue = self._repair(details)

        self.assertEqual([], response["topped_up"])
        self.assertIn("product_group", response["skipped"][0]["reason"])
        enqueue.assert_not_awaited()

    def test_chay_bu_van_chay_khi_the_cha_co_content(self) -> None:
        details = self._topup_board(CO_CONTENT)

        response, enqueue = self._repair(details)

        self.assertEqual([CHILD_A], response["topped_up"][0]["task_ids"])
        self.assertEqual(11, response["topped_up"][0]["count"])
        enqueue.assert_awaited_once()

    def _interrupted(self, *children: str) -> list[JobRecord]:
        jobs = []
        for child in children:
            job = JobRecord(
                type="image",
                status="running",
                title=f"Idea hoa ({child})",
                input={
                    "type": "image",
                    "prompt": f"idea cho {child}",
                    "count": 12,
                    "aspect": "square",
                    "erp_enabled": True,
                    "erp_task_id": PARENT,
                    "erp_source_task_id": PARENT,
                    "erp_output_task_id": child,
                },
            )
            self.loop.run_until_complete(self.store.add_job(job))
            jobs.append(job)
        # Khởi động lại: store mới dán ``interrupted`` lên mọi lượt còn dở.
        self.store = StateStore()
        self.service = FlowWebService(self.store)
        return jobs

    def _resume(self, parent_meta: str, *children: str):
        details = {
            PARENT: {"name": PARENT, "subject": "Idea", "meta": parent_meta, "children": []},
        }
        for child in children:
            details[child] = {
                "name": child,
                "subject": "Hoa thêu tay",
                "description": "ý tưởng",
                "parent_task": PARENT,
                "attachments": [],
                "comments": [],
            }
        reads: list[str] = []

        def _read(_key, _token, task_id):
            reads.append(task_id)
            return details[task_id]

        run = AsyncMock()
        with patch.object(self.service, "_erp_task_detail", side_effect=_read), patch.object(
            self.service, "_run_erp_idea_jobs", new=run
        ), patch.object(self.service, "_flow_quota_pause_reason", return_value=""):
            outcome = self.loop.run_until_complete(self.service.resume_interrupted_erp_idea_jobs())
            for _ in range(3):
                self.loop.run_until_complete(asyncio.sleep(0))
        return outcome, reads, run

    def test_khoi_dong_lai_bo_job_cua_the_cha_khong_content(self) -> None:
        old = self._interrupted(CHILD_A)[0]

        outcome, _reads, run = self._resume(DU_BON_KHOA, CHILD_A)

        self.assertEqual([], outcome["resumed"])
        self.assertEqual([CHILD_A], [item["task_id"] for item in outcome["skipped"]])
        self.assertIn("content", outcome["skipped"][0]["reason"])
        self.assertEqual("interrupted", self.store.get_job(old.id).status)
        run.assert_not_awaited()

    def test_khoi_dong_lai_van_xep_lai_khi_the_cha_co_content(self) -> None:
        self._interrupted(CHILD_A)

        outcome, _reads, run = self._resume(CO_CONTENT, CHILD_A)

        self.assertEqual([CHILD_A], [item["task_id"] for item in outcome["resumed"]])
        run.assert_awaited_once()

    def test_khoi_dong_lai_doc_the_cha_mot_lan_cho_moi_cha(self) -> None:
        self._interrupted(CHILD_A, CHILD_B)

        outcome, reads, _run = self._resume(CO_CONTENT, CHILD_A, CHILD_B)

        self.assertEqual(2, len(outcome["resumed"]))
        self.assertEqual(1, reads.count(PARENT))


class NhanDoneTests(_QuyTrinhTestCase):
    """Thẻ con có đủ ảnh đã duyệt lên thẻ thì gắn nhãn DONE, gắn rồi thì thôi.

    Đếm ảnh **đã duyệt và đã ghi lên thẻ**, không đếm ảnh tạo ra: thẻ bị bỏ
    hết ảnh, duyệt 3/4, hay ghi hỏng một ảnh thì chưa DONE.
    """

    def _request(self, count: int = 2, **extra) -> CreateJobRequest:
        payload = dict(
            type="image",
            erp_enabled=True,
            erp_project_id="PROJ-0013",
            erp_task_id=PARENT,
            erp_source_task_id=PARENT,
            erp_output_task_id=CHILD_A,
            count=count,
            title=f"Idea 1 ({CHILD_A})",
        )
        payload.update(extra)
        return CreateJobRequest(**payload)

    @staticmethod
    def _artifacts(total: int) -> list[JobArtifact]:
        return [
            JobArtifact(media_name=f"idea-{index}.jpg", url=f"https://media.example/idea-{index}.jpg")
            for index in range(total)
        ]

    def test_nhan_la_chu_done(self) -> None:
        self.assertEqual("DONE", FlowWebService.ERP_IDEA_DONE_LABEL)

    def test_du_anh_len_the_thi_xung_dang_done(self) -> None:
        self.assertEqual("", self.service._erp_idea_done_reason(self._request(2), 2))
        self.assertEqual("", self.service._erp_idea_done_reason(self._request(2), 3))

    def test_thieu_anh_len_the_thi_chua_done(self) -> None:
        reason = self.service._erp_idea_done_reason(self._request(12), 11)

        self.assertIn("11/12", reason)
        self.assertIn("lên thẻ", reason)

    def test_khong_anh_nao_len_the_thi_chua_done(self) -> None:
        self.assertIn("0/2", self.service._erp_idea_done_reason(self._request(2), 0))

    def test_luot_khong_phai_the_con_thi_khong_done(self) -> None:
        plain = CreateJobRequest(type="image", erp_enabled=True, erp_task_id=PARENT, count=2)

        self.assertNotEqual("", self.service._erp_idea_done_reason(plain, 2))

    def test_da_co_nhan_done_thi_khong_gan_lai(self) -> None:
        detail = {"name": CHILD_A, "meta_auto": "_labels: [acc32, DONE]"}

        reason = self.service._erp_idea_done_reason(self._request(2), 2, detail)

        self.assertIn("DONE", reason)
        self.assertEqual("", self.service._erp_idea_done_reason(self._request(2), 2, {"meta_auto": "_labels: [acc32]"}))

    def test_mark_done_goi_ghi_nhan_dung_mot_lan(self) -> None:
        job = JobRecord(type="image", title=f"Idea 1 ({CHILD_A})")
        self.loop.run_until_complete(self.store.add_job(job))

        with patch.object(self.service, "_erp_add_task_label", return_value={}) as label:
            result = self.loop.run_until_complete(
                self.service._erp_idea_mark_done(job.id, self._request(2), 2)
            )

        label.assert_called_once_with("test-key", "test-secret", CHILD_A, "DONE")
        self.assertTrue(result["marked"])
        self.assertEqual(CHILD_A, result["task_id"])
        self.assertTrue(
            any("2/2 ảnh đã lên thẻ" in entry.message for entry in self.store.get_job(job.id).logs),
            [entry.message for entry in self.store.get_job(job.id).logs],
        )

    def test_thieu_anh_thi_mark_done_khong_goi_ghi_nhan(self) -> None:
        job = JobRecord(type="image", title=f"Idea 1 ({CHILD_A})")
        self.loop.run_until_complete(self.store.add_job(job))

        with patch.object(self.service, "_erp_add_task_label") as label:
            result = self.loop.run_until_complete(
                self.service._erp_idea_mark_done(job.id, self._request(3), 2)
            )

        label.assert_not_called()
        self.assertFalse(result["marked"])
        self.assertIn("2/3", result["reason"])

    def test_erp_tu_choi_nhan_thi_ghi_log_khong_nem_loi(self) -> None:
        # ERP bảo nhãn chưa có (hoặc lỗi gì khác): lượt vẫn xong, chỉ ghi nhật ký.
        job = JobRecord(type="image", title=f"Idea 1 ({CHILD_A})")
        self.loop.run_until_complete(self.store.add_job(job))

        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_graphql", side_effect=RuntimeError("Task Label DONE not found")
        ):
            result = self.loop.run_until_complete(
                self.service._erp_idea_mark_done(job.id, self._request(2), 2)
            )

        self.assertFalse(result["marked"])
        self.assertIn("nhãn", result["reason"])
        self.assertIn("not found", result["reason"])
        self.assertTrue(any("DONE" in entry.message for entry in self.store.get_job(job.id).logs))

    def test_ghi_nhan_goi_dung_mutation_assign_task_label(self) -> None:
        # ERP có assignTaskLabel(task, label); ghi theo mẫu UpdateTaskMeta.
        with patch.object(self.service, "_erp_assert_task_in_project") as guard, patch.object(
            self.service, "_erp_graphql", return_value={"assignTaskLabel": {"name": CHILD_A}}
        ) as graphql:
            result = self.service._erp_add_task_label("test-key", "test-secret", CHILD_A, "DONE")

        guard.assert_called_once_with("test-key", "test-secret", CHILD_A)
        graphql.assert_called_once()
        query, variables, operation = graphql.call_args.args
        self.assertIn("mutation AssignTaskLabel", query)
        self.assertIn("assignTaskLabel(task: $task, label: $label)", query)
        self.assertEqual({"task": CHILD_A, "label": "DONE"}, variables)
        self.assertEqual("AssignTaskLabel", operation)
        self.assertEqual({"key": "test-key", "token": "test-secret"}, graphql.call_args.kwargs)
        self.assertEqual({"name": CHILD_A}, result)

    def test_ghi_nhan_khong_tu_tao_nhan(self) -> None:
        # Tạo nhãn là ghi cấp toàn ERP, phải có người duyệt: không gọi createTaskLabel.
        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_graphql", return_value={}
        ) as graphql:
            self.service._erp_add_task_label("test-key", "test-secret", CHILD_A, "DONE")

        self.assertEqual(1, graphql.call_count)
        self.assertNotIn("createTaskLabel", graphql.call_args.args[0])

    def test_ghi_nhan_chuan_hoa_ma_the(self) -> None:
        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_graphql", return_value={}
        ) as graphql:
            result = self.service._erp_add_task_label("test-key", "test-secret", f"  {CHILD_A} ", "DONE")

        self.assertEqual(CHILD_A, graphql.call_args.args[1]["task"])
        self.assertEqual({}, result)

    def test_ghi_nhan_thieu_ma_the_thi_bao_ro(self) -> None:
        with patch.object(self.service, "_erp_graphql") as graphql:
            with self.assertRaises(RuntimeError):
                self.service._erp_add_task_label("test-key", "test-secret", "", "DONE")

        graphql.assert_not_called()

    def test_archive_xong_thi_gan_done_cho_the_con(self) -> None:
        job = JobRecord(
            type="image",
            title=f"Idea 1 ({CHILD_A})",
            result={"dashboard_approvals": {"0": {"status": "approved"}, "1": {"status": "approved"}}},
        )
        self.loop.run_until_complete(self.store.add_job(job))

        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service,
            "_erp_attach_url",
            side_effect=lambda _k, _t, _task, url, name, *_a: {"id": url, "name": name, "url": url},
        ), patch.object(
            self.service, "_erp_advance_task_status", new_callable=AsyncMock, return_value=False
        ), patch.object(self.service, "_erp_add_task_label", return_value={}) as label:
            result = self.loop.run_until_complete(
                self.service._archive_erp_artifacts(job.id, self._request(2), self._artifacts(2))
            )

        label.assert_called_once_with("test-key", "test-secret", CHILD_A, "DONE")
        self.assertEqual(2, result["sent"])
        self.assertTrue(result["done_label"]["marked"])

    def test_archive_thieu_anh_thi_khong_gan_done(self) -> None:
        job = JobRecord(
            type="image",
            title=f"Idea 1 ({CHILD_A})",
            result={"dashboard_approvals": {"0": {"status": "approved"}, "1": {"status": "approved"}}},
        )
        self.loop.run_until_complete(self.store.add_job(job))

        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service,
            "_erp_attach_url",
            side_effect=lambda _k, _t, _task, url, name, *_a: {"id": url, "name": name, "url": url},
        ), patch.object(
            self.service, "_erp_advance_task_status", new_callable=AsyncMock, return_value=False
        ), patch.object(self.service, "_erp_add_task_label") as label:
            result = self.loop.run_until_complete(
                self.service._archive_erp_artifacts(job.id, self._request(3), self._artifacts(2))
            )

        label.assert_not_called()
        self.assertFalse(result["done_label"]["marked"])

    def _archive_with(self, job: JobRecord, request: CreateJobRequest, artifacts, *, attach=None):
        attach = attach or (lambda _k, _t, _task, url, name, *_a: {"id": url, "name": name, "url": url})
        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_attach_url", side_effect=attach
        ), patch.object(
            self.service, "_erp_advance_task_status", new_callable=AsyncMock, return_value=False
        ), patch.object(self.service, "_erp_add_task_label", return_value={}) as label:
            result = self.loop.run_until_complete(self.service._archive_erp_artifacts(job.id, request, artifacts))
        return result, label

    def test_archive_duyet_3_tren_4_thi_khong_done(self) -> None:
        # Tạo đủ 4 ảnh nhưng người duyệt bỏ 1: chỉ 3 ảnh lên thẻ, chưa DONE.
        job = JobRecord(
            type="image",
            title=f"Idea 1 ({CHILD_A})",
            result={
                "dashboard_approvals": {
                    "0": {"status": "approved"},
                    "1": {"status": "approved"},
                    "2": {"status": "rejected"},
                    "3": {"status": "approved"},
                }
            },
        )
        self.loop.run_until_complete(self.store.add_job(job))

        result, label = self._archive_with(job, self._request(4), self._artifacts(4))

        label.assert_not_called()
        self.assertEqual(3, result["sent"])
        self.assertFalse(result["done_label"]["marked"])
        self.assertIn("3/4", result["done_label"]["reason"])

    def test_archive_bo_het_anh_thi_khong_done(self) -> None:
        job = JobRecord(
            type="image",
            title=f"Idea 1 ({CHILD_A})",
            result={"dashboard_approvals": {"0": {"status": "rejected"}, "1": {"status": "rejected"}}},
        )
        self.loop.run_until_complete(self.store.add_job(job))

        result, label = self._archive_with(job, self._request(2), self._artifacts(2))

        label.assert_not_called()
        self.assertEqual(0, result["sent"])
        self.assertIn("0/2", result["done_label"]["reason"])

    def test_archive_ghi_hong_mot_anh_thi_khong_done(self) -> None:
        # Duyệt đủ 2/2 nhưng ERP từ chối một ảnh: trên thẻ chỉ có 1, chưa DONE.
        job = JobRecord(
            type="image",
            title=f"Idea 1 ({CHILD_A})",
            result={"dashboard_approvals": {"0": {"status": "approved"}, "1": {"status": "approved"}}},
        )
        self.loop.run_until_complete(self.store.add_job(job))

        def attach(_k, _t, _task, url, name, *_a):
            if name.endswith("-2.jpg") or url.endswith("idea-1.jpg"):
                raise RuntimeError("ERP 500")
            return {"id": url, "name": name, "url": url}

        result, label = self._archive_with(job, self._request(2), self._artifacts(2), attach=attach)

        label.assert_not_called()
        self.assertEqual(1, result["sent"])
        self.assertEqual(1, result["failed"])
        self.assertIn("1/2", result["done_label"]["reason"])


if __name__ == "__main__":
    unittest.main()
