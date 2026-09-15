"""Lỗi 2K "'NoneType' object has no attribute 'pages'" (d6, việc 3).

Lô 2K (``_upsample_artifacts_bytes``) mở client Flow một lần rồi trả khoá
phiên trình duyệt (``hold_session_lock=False``) để thẻ sau tạo ảnh. Trong
lúc ấy một job khác chạm trần quota: ``_mark_flow_profile_quota_limited``
đóng trình duyệt dùng chung. ``BrowserManager.stop()`` của flow-py đặt
``_ctx = None``; lượt mint token kế của lô gọi ``_bm.page()`` và vỡ ở
``self._ctx.pages``. Ảnh đã tạo xong, credit đã tiêu, mà thẻ bị giữ ở 1K.

Đã sửa: mẻ 2K thấy client chết thì mở client mới đúng một lần
(``FLOW_UPSAMPLE_REOPEN_MAX``), chỉ cho ảnh chưa ra 2K.

Trình duyệt, trang và Flow đều giả; ``BrowserManager`` là
lớp thật của flow-py (chỉ gắn context giả), để lỗi ra đúng câu chữ log thật.
Không mạng, không Chrome, không credit.
"""

from __future__ import annotations

import asyncio
import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from flow._browser import BrowserManager

from flow_web.schemas import JobArtifact
from flow_web.service import FlowBrowserProfile, FlowWebService
from flow_web.store import StateStore

PROJECT = "42f50a6f-5ab5-407b-ade1-eb6c23158377"
MEDIA_1 = "3f2b9c1e-8a4d-4e21-9b7a-0c5d6e7f8a9b"
MEDIA_2 = "7a1c2d3e-4b5f-4a6b-8c7d-9e0f1a2b3c4d"
MEDIA_3 = "c5d6e7f8-9a0b-4c1d-8e2f-3a4b5c6d7e8f"
BIG = b"anh-2k-that"
LOI_LOG_THAT = "'NoneType' object has no attribute 'pages'"


class _FakePage:
    url = f"https://labs.google/fx/tools/flow/project/{PROJECT}"

    def is_closed(self) -> bool:
        return False

    async def evaluate(self, *_args, **_kwargs):
        return "complete"


class _FakeContext:
    def __init__(self) -> None:
        self.pages = [_FakePage()]

    async def close(self) -> None:
        return None


class _FakePlaywright:
    async def stop(self) -> None:
        return None


def _started_browser(root: Path) -> BrowserManager:
    """BrowserManager thật của flow-py, như vừa ``start()`` xong."""
    browser = BrowserManager(headless=True, profile_dir=root / "profile")
    browser._pw = _FakePlaywright()
    browser._ctx = _FakeContext()
    return browser


class _FakeApi:
    """Hai chỗ lô 2K chạm vào ``client._api``, đi qua trang như bản thật.

    ``_client_context`` của flow-py mint reCAPTCHA qua ``self._bm.page()``;
    ``_fetch`` (bản compat trong service) lấy Bearer qua ``self._bm.page()``
    khi chưa có token. Trình duyệt đã ``stop()`` thì cả hai vỡ đúng câu log.
    """

    def __init__(self, client: "_FakeClient") -> None:
        self._client = client
        self.project_id = PROJECT
        self._flow_recaptcha_action = ""

    async def _client_context(self):
        await self._client._bm.page()
        return {"projectId": PROJECT, "recaptchaContext": {"token": "tok"}}

    async def _fetch(self, method: str, path: str, payload):
        await self._client._bm.page()
        self._client.test.fetches += 1
        self._client.test.fetched_media.append(payload.get("mediaId"))
        hook = self._client.test.on_first_fetch
        if hook is not None:
            self._client.test.on_first_fetch = None
            await hook()
        return {"encodedImage": base64.b64encode(BIG).decode()}


class _FakeClient:
    def __init__(self, test: "_UpsampleContextBase", browser: BrowserManager) -> None:
        self.test = test
        self._bm = browser
        self._api = _FakeApi(self)
        self._project_url = f"https://labs.google/fx/tools/flow/project/{PROJECT}"


class _UpsampleContextBase(unittest.TestCase):
    def setUp(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        root = self.root
        self.patches = [
            patch.dict(os.environ, {"FLOW_UPSAMPLE_API_ENABLED": "1"}, clear=False),
            patch("flow_web.store.STATE_FILE", root / "state.json"),
            patch("flow_web.store.ensure_app_dirs", lambda: root.mkdir(parents=True, exist_ok=True)),
            patch("flow_web.service.ensure_app_dirs", lambda: root.mkdir(parents=True, exist_ok=True)),
            patch("flow._storage.CONFIG_FILE", root / "flow-config.json"),
            patch("flow._storage.PROJECTS_FILE", root / "flow-projects.json"),
        ]
        for item in self.patches:
            item.start()
        self.store = StateStore()
        self.service = FlowWebService(self.store)
        self.profile = FlowBrowserProfile(
            index=0, label="Flow profile 1", path=root / "profile", project_id=PROJECT
        )
        self.opened: list[BrowserManager] = []
        self.fetches = 0
        self.fetched_media: list[str] = []
        self.on_first_fetch = None

        async def _ensure_shared_browser(profile=None, *, visible=False):
            # Như bản thật: còn dùng được thì trả lại, không thì mở cái mới.
            current = self.service._shared_browser
            if current is not None and getattr(current, "_ctx", None) is not None:
                return current
            browser = _started_browser(root)
            self.opened.append(browser)
            self.service._shared_browser = browser
            self.service._shared_browser_profile_key = (profile or self.profile).key
            return browser

        async def _build_client(browser, **_kwargs):
            return _FakeClient(self, browser)

        for item in (
            patch.object(self.service, "_flow_profile_specs", return_value=[self.profile]),
            patch.object(self.service, "_should_keep_flow_browser_open", return_value=True),
            patch.object(self.service, "_flow_modules", return_value=(object, None, None, None, None)),
            patch.object(self.service, "_ensure_shared_browser", side_effect=_ensure_shared_browser),
            patch.object(self.service, "_build_client_from_shared_browser", side_effect=_build_client),
            patch.object(
                self.service,
                "_image_size_from_bytes",
                side_effect=lambda data: (2048, 2048) if data == BIG else (1024, 1024),
            ),
        ):
            item.start()
            self.patches.append(item)

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()
        if pending:
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self.loop.close()
        asyncio.set_event_loop(None)
        self.tempdir.cleanup()

    def _artifact(self, media: str, name: str) -> tuple[JobArtifact, str]:
        path = self.root / name
        path.write_bytes(f"anh-1k-{name}".encode())
        url = f"https://flow-content.google/image/{media}"
        return JobArtifact(media_name=media, url=url, local_path=str(path), mime_type="image/jpeg"), url

    async def _job_khac_cham_tran_quota(self) -> None:
        # Job tạo ảnh của thẻ sau cầm khoá phiên như ``_with_client`` thật,
        # rồi Flow báo hết quota Agent (20:51:39 ngày 11/09).
        async with self.service._browser_session_lock:
            await self.service._mark_flow_profile_quota_limited(
                self.profile,
                RuntimeError("I wasn't able to generate the images because the daily quota for the model has been reached."),
            )

    async def _job_khac_dong_trinh_duyet_moi_lan(self) -> None:
        # Job khác đóng trình duyệt dùng chung, và làm vậy với mọi client mới:
        # lượt fetch đầu của client nào cũng kéo theo một lần đóng.
        self.on_first_fetch = self._job_khac_dong_trinh_duyet_moi_lan
        async with self.service._browser_session_lock:
            await self.service._close_shared_browser()

    def _chay_lo(self, items) -> dict:
        # Có hạn chờ: mở lại không trần thì bài đỏ vì quá giờ, không treo.
        return self.loop.run_until_complete(
            asyncio.wait_for(self.service._upsample_artifacts_bytes(items), timeout=30)
        )


class TaiHienLoiTests(_UpsampleContextBase):
    def test_browser_manager_da_stop_vo_dung_cau_log_that(self) -> None:
        # Bài chứng cứ (xanh): câu lỗi sinh ra từ flow/_browser.py, BrowserManager.page().
        browser = _started_browser(self.root)
        self.loop.run_until_complete(browser.stop())
        with self.assertRaises(AttributeError) as caught:
            self.loop.run_until_complete(browser.page())
        self.assertEqual(LOI_LOG_THAT, str(caught.exception))


class LoHaiKGapQuotaGiuaChungTests(_UpsampleContextBase):
    def test_lo_2k_van_ra_du_2k_khi_job_khac_cham_tran_quota_giua_chung(self) -> None:
        first, first_url = self._artifact(MEDIA_1, "anh-1.jpg")
        second, second_url = self._artifact(MEDIA_2, "anh-2.jpg")
        self.on_first_fetch = self._job_khac_cham_tran_quota

        results = self.loop.run_until_complete(
            self.service._upsample_artifacts_bytes([(0, first, first_url), (1, second, second_url)])
        )

        self.assertIn(self.profile.key, self.service._flow_profile_quota_blocked_until, "tiền đề: quota đã bị khoá")
        self.assertEqual("flow_2k", results[0].source)
        self.assertEqual(
            ("flow_2k", BIG),
            (results[1].source, results[1].bytes),
            "khoá quota tạo ảnh không được làm hỏng bước 2K của ảnh đã tạo xong "
            f"(log thật: {LOI_LOG_THAT})",
        )


class LoHaiKMoLaiClientTests(_UpsampleContextBase):
    """Mẻ 2K thấy client chết thì mở lại đúng một lần, chỉ cho ảnh chưa xong."""

    def test_anh_da_ra_2k_truoc_khi_chet_khong_bi_nang_lai(self) -> None:
        first, first_url = self._artifact(MEDIA_1, "anh-1.jpg")
        second, second_url = self._artifact(MEDIA_2, "anh-2.jpg")
        self.on_first_fetch = self._job_khac_cham_tran_quota

        results = self._chay_lo([(0, first, first_url), (1, second, second_url)])

        self.assertEqual(("flow_2k", BIG), (results[0].source, results[0].bytes))
        self.assertEqual(("flow_2k", BIG), (results[1].source, results[1].bytes))
        self.assertEqual(
            [MEDIA_1, MEDIA_2],
            self.fetched_media,
            "ảnh 1 đã ra 2K trước khi trình duyệt chết: không được gửi nâng lại",
        )
        self.assertEqual(2, len(self.opened), "mở lại client đúng một lần")

    def test_trinh_duyet_chet_lan_hai_trong_cung_me_thi_dung(self) -> None:
        items = []
        for index, media in enumerate((MEDIA_1, MEDIA_2, MEDIA_3)):
            artifact, url = self._artifact(media, f"anh-{index + 1}.jpg")
            items.append((index, artifact, url))
        self.on_first_fetch = self._job_khac_dong_trinh_duyet_moi_lan

        results = self._chay_lo(items)

        self.assertEqual(2, len(self.opened), "trần: một lần mở lại mỗi mẻ, không vòng lặp")
        self.assertEqual([MEDIA_1, MEDIA_2], self.fetched_media)
        self.assertEqual("flow_2k", results[0].source)
        self.assertEqual("flow_2k", results[1].source)
        self.assertEqual("flow_unavailable", results[2].source, "chết lần hai: ảnh còn lại dừng như cũ")
        self.assertFalse(results[2].bytes, "không có bytes 2K thì không được đăng 1K thay")


class NhanRaClientCuTests(_UpsampleContextBase):
    def test_loi_client_da_dong_duoc_xep_la_trinh_duyet_da_dong(self) -> None:
        # Chỉ đúng với phương án B (nhận ra client cũ qua câu lỗi rồi mở lại).
        # Chọn cách nhận ra bằng ``client._bm._ctx is None`` thì thay bài này.
        browser = _started_browser(self.root)
        self.loop.run_until_complete(browser.stop())
        try:
            self.loop.run_until_complete(browser.page())
        except AttributeError as exc:
            error = exc
        else:  # pragma: no cover - bài chứng cứ ở trên đã chốt nhánh này
            self.fail("BrowserManager đã stop phải vỡ ở page()")
        self.assertTrue(
            self.service._is_browser_closed_error(error),
            "câu lỗi của BrowserManager đã stop phải được coi là trình duyệt đã đóng",
        )


class WithClientChiDongTrinhDuyetCuaMinhTests(_UpsampleContextBase):
    """``_with_client`` gặp lỗi trình duyệt đã đóng thì chỉ đóng trình duyệt của lượt thử.

    Kịch bản (brief sửa 1): job A cầm client trên BM1. Job C chạm trần quota
    và đóng BM1. Job B mở BM2 và đang tạo ảnh. Rồi ``fn`` của A vỡ vì BM1 đã
    stop. Không được đóng BM2 dưới chân B.
    """

    def setUp(self) -> None:
        super().setUp()
        self.stopped: list[BrowserManager] = []

    def _dem_stop(self, browser: BrowserManager) -> BrowserManager:
        goc = browser.stop

        async def stop() -> None:
            self.stopped.append(browser)
            await goc()

        browser.stop = stop
        return browser

    def _goi_with_client(self, fn) -> HTTPException:
        with self.assertRaises(HTTPException) as caught:
            self.loop.run_until_complete(
                asyncio.wait_for(
                    self.service._with_client(fn, hold_session_lock=False, needs_agent_quota=False),
                    timeout=30,
                )
            )
        return caught.exception

    def _job_khac_thay_trinh_duyet_roi_vo(self, loi: str):
        async def fn(client) -> None:
            self._dem_stop(client._bm)
            async with self.service._browser_session_lock:
                # Job C chạm trần quota: đóng BM1.
                await self.service._close_shared_browser()
                # Job B vào sau: mở BM2.
                moi = await self.service._ensure_shared_browser(self.profile)
            self._dem_stop(moi)
            raise Exception(loi)

        return fn

    def _kiem_khong_dong_trinh_duyet_moi(self, loi: str) -> None:
        caught = self._goi_with_client(self._job_khac_thay_trinh_duyet_roi_vo(loi))

        self.assertEqual(2, len(self.opened), "tiền đề: job khác đã mở trình duyệt mới")
        cu, moi = self.opened
        self.assertIsNot(cu, moi)
        self.assertEqual([cu], self.stopped, "chỉ trình duyệt cũ bị stop (bởi job khác); trình duyệt mới không bị đóng")
        self.assertIsNotNone(moi._ctx, "trình duyệt mới còn sống")
        self.assertIs(moi, self.service._shared_browser, "trình duyệt dùng chung vẫn là cái mới")
        self.assertEqual(500, caught.status_code)

    def test_a_loi_client_cu_khong_dong_trinh_duyet_moi_cua_job_khac(self) -> None:
        self._kiem_khong_dong_trinh_duyet_moi(LOI_LOG_THAT)

    def test_b_loi_client_cu_van_dong_trinh_duyet_cua_chinh_luot_thu(self) -> None:
        async def fn(client) -> None:
            self._dem_stop(client._bm)
            raise Exception(LOI_LOG_THAT)

        caught = self._goi_with_client(fn)

        self.assertEqual(1, len(self.opened))
        self.assertEqual(self.opened, self.stopped, "trình duyệt của lượt thử vẫn bị đóng như 62b18d5")
        self.assertIsNone(self.service._shared_browser)
        self.assertEqual(500, caught.status_code)

    def test_c_cau_cu_browser_has_been_closed_cung_khong_dong_trinh_duyet_moi(self) -> None:
        self._kiem_khong_dong_trinh_duyet_moi("Browser has been closed")


if __name__ == "__main__":
    unittest.main()
