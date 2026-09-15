"""Vá thẻ con không được đọc ERP cho thẻ chưa có job — tải ERP, 11/09.

``repair_erp_idea_children`` đọc ``_erp_task_detail`` cho MỌI thẻ con của thẻ
cha mỗi lượt autorun (cụm 05384 ≈50 lượt đọc/lượt, 04628 hơn 60).  App không có
hàng chờ ERP; trần 60 lượt/phút/token dùng chung với lister Etsy và bộ bê Trello
nên dội 429.  Mà thẻ con không có job nào của app thì cả hai nhánh của vòng lặp
(đăng bù ``_erp_unfinished_review_job_id``, chạy bù ``_erp_idea_image_shortfall``)
đều bắt đầu bằng ``_erp_child_jobs`` và trả rỗng — không cần đọc thẻ.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from flow_web.schemas import ERPConfig, JobArtifact, JobRecord
from flow_web.service import FlowWebService
from flow_web.store import StateStore

PARENT = "TASK-2026-05384"

CO_CONTENT = "\n".join(
    [
        "product_type: Khăn tay cô dâu thêu tay",
        "product_group: Thêu tay",
        "fulfillment: HaviGroup",
        "sales_channel: Etsy",
        "content: Có",
    ]
)


def _child_id(index: int) -> str:
    return f"TASK-2026-1{index:04d}"


class _RepairTestCase(unittest.TestCase):
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
                ERPConfig(api_key="test-key", api_secret="test-secret", project_id="PROJ-0013", task_id=PARENT)
            )
        )

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tempdir.cleanup()
        self.loop.close()
        asyncio.set_event_loop(None)

    def _cay(self, so_the_con: int) -> dict:
        """Thẻ cha đủ thuộc tính, ``content: Có``, N thẻ con trắng trơn ở Open."""
        children = [_child_id(index) for index in range(so_the_con)]
        details: dict = {
            PARENT: {
                "name": PARENT,
                "subject": "Idea",
                "status": "Working",
                "meta": CO_CONTENT,
                "cover_image": "/private/files/khan-tay.jpg",
                "children": [{"name": child, "subject": f"Idea {index + 1}"} for index, child in enumerate(children)],
                "comments": [],
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

    def _job(
        self, child: str, *, status: str = "completed", count: int = 2, images: int = 2, da_duyet: bool = False
    ) -> JobRecord:
        """Một job của app cho thẻ con; ``da_duyet`` = người duyệt đã quyết ảnh trên dashboard."""
        result = {"dashboard_approvals": {"0": {"status": "approved"}}} if da_duyet else {}
        job = JobRecord(
            type="image",
            status=status,
            title=f"Idea ({child})",
            input={"erp_output_task_id": child, "count": count, "erp_enabled": True},
            result=result,
            artifacts=[
                JobArtifact(media_name=f"{child}-{index}.jpg", url=f"https://media.example/{child}-{index}.jpg")
                for index in range(images)
            ],
        )
        self.loop.run_until_complete(self.store.add_job(job))
        return job

    def _repair(self, details: dict):
        reads: list[str] = []

        def _read(_key, _token, task_id):
            reads.append(task_id)
            return details[task_id]

        with patch.dict(os.environ, {"ERP_IDEA_TOPUP": "1"}), patch.object(
            self.service, "_erp_task_project_id", return_value="PROJ-0013"
        ), patch.object(self.service, "_erp_task_detail", side_effect=_read), patch.object(
            self.service, "publish_erp_review", new_callable=AsyncMock, return_value={"published": 2}
        ) as publish, patch.object(
            self.service, "enqueue_erp_idea_jobs", new_callable=AsyncMock, return_value={"queued": []}
        ) as enqueue, patch.object(self.service, "_flow_quota_pause_reason", return_value=""):
            response = self.loop.run_until_complete(self.service.repair_erp_idea_children(PARENT))
        return response, reads, publish, enqueue


class KhongDocTheChuaCoJobTests(_RepairTestCase):
    """Thẻ con chưa có job nào của app thì không tốn một lượt đọc ERP."""

    def test_cay_50_the_con_2_co_job_chi_doc_3_the(self) -> None:
        details = self._cay(50)
        # Thẻ 5: lượt hứa 12 trả 1, tấm duy nhất người duyệt đã quyết → không
        # còn gì để đăng bù, nhưng thiếu 11 tấm chưa từng tạo → phải chạy bù.
        thieu = self._job(_child_id(5), count=12, images=1, da_duyet=True)
        # Thẻ 17: đủ ảnh đã tạo mà chưa lên thẻ → đăng bù.
        chua_dang = self._job(_child_id(17), count=2, images=2)

        response, reads, publish, enqueue = self._repair(details)

        self.assertEqual([PARENT, _child_id(5), _child_id(17)], reads)
        self.assertEqual(
            [{"task_id": _child_id(17), "job_id": chua_dang.id, "published": 2}], response["republished"]
        )
        self.assertEqual([_child_id(5)], response["topped_up"][0]["task_ids"])
        self.assertEqual(11, response["topped_up"][0]["count"])
        self.assertEqual([], response["skipped"])
        publish.assert_awaited_once_with(chua_dang.id)
        enqueue.assert_awaited_once()
        self.assertEqual(12, thieu.input["count"])

    def test_the_co_job_completed_chua_dang_anh_van_duoc_dang_bu(self) -> None:
        details = self._cay(1)
        job = self._job(_child_id(0), count=2, images=2)

        response, reads, publish, _enqueue = self._repair(details)

        self.assertEqual([PARENT, _child_id(0)], reads)
        publish.assert_awaited_once_with(job.id)
        self.assertEqual([{"task_id": _child_id(0), "job_id": job.id, "published": 2}], response["republished"])

    def test_the_khong_job_khong_doc_khong_ghi_gi(self) -> None:
        details = self._cay(50)

        response, reads, publish, enqueue = self._repair(details)

        self.assertEqual([PARENT], reads)
        self.assertEqual([], response["republished"])
        self.assertEqual([], response["topped_up"])
        self.assertEqual([], response["skipped"])
        publish.assert_not_awaited()
        enqueue.assert_not_awaited()

    def test_the_chi_co_job_chet_cung_khong_doc(self) -> None:
        # ``interrupted`` là job chết: ``_erp_child_jobs`` đã bỏ nó, hai nhánh
        # vá đều rỗng — y như thẻ không job, nên cũng không đọc.
        details = self._cay(3)
        self._job(_child_id(1), status="interrupted", count=2, images=0)

        response, reads, _publish, _enqueue = self._repair(details)

        self.assertEqual([PARENT], reads)
        self.assertEqual([], response["skipped"])

    def test_the_co_job_dang_chay_van_duoc_doc_nhu_cu(self) -> None:
        # Thẻ có job thì hành vi y hệt cũ: vẫn đọc, đang chạy thì chưa biết
        # thiếu bao nhiêu nên không vá gì.
        details = self._cay(3)
        self._job(_child_id(2), status="running", count=2, images=0)

        response, reads, publish, enqueue = self._repair(details)

        self.assertEqual([PARENT, _child_id(2)], reads)
        self.assertEqual([], response["republished"])
        self.assertEqual([], response["topped_up"])
        publish.assert_not_awaited()
        enqueue.assert_not_awaited()

    def test_the_da_completed_co_job_van_bo_qua_nhu_cu(self) -> None:
        details = self._cay(2)
        details[_child_id(0)]["status"] = FlowWebService.ERP_STATUS_COMPLETED
        self._job(_child_id(0), count=2, images=2)

        response, reads, publish, _enqueue = self._repair(details)

        self.assertEqual([PARENT, _child_id(0)], reads)
        self.assertEqual([], response["republished"])
        publish.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
