"""TDD cho PRD ``tasks/prd-agent-improvements.md`` — phần cần ``flow_web.service``.

    ./.venv/bin/python -m unittest tests.test_agent_improvements -v

**Mọi bài ở đây đang ĐỎ và phải đỏ.** Chúng tả hành vi *sau* khi các mục
A1–A7, C1, C2 của PRD được cài. Phần không cần ``fastapi``/``flow`` nằm ở
``tests/test_agent_guardrails.py``.

Khuôn dựng lấy nguyên từ ``tests/test_erp_review.py``: cùng cách vá
``STATE_FILE``/``ensure_app_dirs``, cùng ``_FakeUpsampleClient``. Hai file
chạy cạnh nhau nên chúng phải dựng giống nhau.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import inspect
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from flow_web.schemas import (
    ERPConfig,
    IntegrationConfig,
    IntegrationConfigUpdateRequest,
    JobArtifact,
    JobRecord,
)
from flow_web.service import (
    PROJECT_POLL_SECOND_CHANCE_FLOOR_S,
    FlowBrowserProfile,
    FlowWebService,
    ImageUpscaleResult,
    race_interceptor_and_project_poll,
    remaining_project_poll_budget,
)
from flow_web.store import JOB_HISTORY_LIMIT, StateStore, trim_job_history


def chay_co_gioi_han(bai: Callable[[], Awaitable[Any]], gioi_han: float = 2.0) -> Any:
    """Chạy một coroutine test dưới trần thời gian, rồi báo bài đỏ nếu quá trần.

    Cuộc đua A1.3 có mấy kiểu hỏng "chờ mãi": một future không ai giải quyết,
    một vế huỷ bị gỡ khỏi ``finally``. Không có trần này thì bản cài đặt sai
    làm **treo** cả bộ test — CI chỉ báo hết giờ và không nói được bài nào.
    Đo thật: gỡ vế huỷ, hoặc bỏ nhánh ảnh poll thắng, đều treo vô hạn thay vì
    đỏ. Có trần thì hai lỗi ấy đỏ ngay tại chỗ, kèm câu đọc ra được.
    """

    async def _bao() -> Any:
        # Không dùng ``wait_for`` + ``except asyncio.TimeoutError``: từ Python
        # 3.11 ``asyncio.TimeoutError`` **chính là** ``TimeoutError``, nên
        # nhánh ấy nuốt luôn cái ``TimeoutError`` mà chính hàm đang test ném
        # ra — đúng cái hành vi A1.3 phải chốt. Ở đây hỏi thẳng trạng thái
        # task: chưa xong thì mới là quá trần.
        viec = asyncio.ensure_future(bai())
        xong, _con = await asyncio.wait({viec}, timeout=gioi_han)
        if not xong:
            viec.cancel()
            with contextlib.suppress(BaseException):
                await viec
            raise AssertionError(
                f"cuộc đua không kết thúc trong {gioi_han}s. Trần này không "
                "phân biệt được nguyên nhân — hãy tự xét: đường thua không "
                "được huỷ · vòng lặp còn chờ một future không ai giải quyết · "
                "hoặc máy đang quá tải (bình thường cả lớp chạy hết ~0,2s, "
                f"trần {gioi_han}s là dư hơn mười lần)"
            )
        return viec.result()

    return asyncio.run(_bao())


class AgentModeDeadWaitTests(unittest.TestCase):
    """A1 — khoảng chờ 45s trong Agent mode là chờ một thứ không bao giờ đến.

    Docstring của chính hàm đã ghi: trong Agent mode khoảng chờ này *hầu như
    luôn* hết giờ, rồi ảnh được tìm thấy bằng project poll khoảng mười giây
    sau. Đo trên ba card thật: cả ba đều như vậy. Đo ở 15 giây: ảnh vẫn sạch
    và vẫn 2K, tiết kiệm 30 giây mỗi ý tưởng.

    **Bảy bài về cuộc đua A1.3 đã được đo bằng đột biến.** Trước đây phần này
    chỉ có hai câu ``inspect.getsource`` + ``assertIn`` — xanh kể cả khi nối
    dây sai. Giờ đua chạy thật trên ``asyncio.Future``, và mỗi đột biến vào
    ``race_interceptor_and_project_poll`` đều làm đỏ đúng bài của nó:

    ==== =========================================== ==================================
    Đột  Sửa gì trong hàm                            Bài đỏ
    ==== =========================================== ==================================
    A    ``while`` → ``if`` (đua một lượt)           hai bài ``..._does_not_end_the_race``
    B    bỏ ``interceptor_error = task_exc``         ``..._raises_the_interceptor_error...``
    C    bỏ ``await on_poll_error(task_exc)``        ``..._does_not_read_as_a_plain_timeout`` + 1 bài khác
    D    bỏ vế ``task.cancel()``                     ``..._nothing_leaks`` + 2 bài khác
    E    bỏ ``raced_images = list(outcome)``         ``..._the_project_poll_can_win...`` + 1 bài khác
    F    ``got_result = True`` → ``False``           ``..._races_the_poll...`` + 3 bài khác
    G    bỏ ``await asyncio.gather(...)``            ``..._nothing_leaks``
    ==== =========================================== ==================================

    Hai chỗ tự bẫy mình khi dựng bảng này, ghi lại để đừng lặp:

    - ``await asyncio.sleep(0)`` ở nhánh về sau là **vô dụng**: bên kia kịp
      xong ngay trong lượt ``asyncio.wait`` đầu tiên, nên đột biến A vẫn xanh.
      Phải chờ thật (50ms) thì bài mới đòi được vòng thứ hai.
    - Đột biến D và E ban đầu không làm đỏ mà làm **treo** — bài giữ những
      future không ai giải quyết. Treo là tín hiệu tồi: CI chỉ báo hết giờ,
      không nói được bài nào. Trần thời gian ở ``chay_co_gioi_han`` biến cả
      hai thành bài đỏ đọc ra được.
    """

    def setUp(self) -> None:
        self.service = FlowWebService.__new__(FlowWebService)

    def _wait(self) -> float:
        return FlowWebService._flow_agent_network_wait_seconds(self.service)

    def test_the_default_is_no_longer_forty_five_seconds(self) -> None:
        with patch.dict(os.environ, {"FLOW_AGENT_NETWORK_WAIT_SECONDS": ""}, clear=False):
            self.assertEqual(15.0, self._wait())

    def test_the_env_knob_still_works_for_measuring(self) -> None:
        # Giữ đường đo lại: con số 15 đến từ một mẫu, không phải từ ba.
        with patch.dict(os.environ, {"FLOW_AGENT_NETWORK_WAIT_SECONDS": "25"}, clear=False):
            self.assertEqual(25.0, self._wait())

    def test_the_wait_can_be_switched_off_entirely(self) -> None:
        # Kẹp dưới hôm nay là 5.0. Agent mode không sinh batchGenerateImages
        # thành công, nên phải nói được "đừng chờ" thay vì "chờ ít thôi".
        with patch.dict(os.environ, {"FLOW_AGENT_NETWORK_WAIT_SECONDS": "0"}, clear=False):
            self.assertEqual(0.0, self._wait())

    def test_a_nonsense_value_still_falls_back_to_the_new_default(self) -> None:
        with patch.dict(os.environ, {"FLOW_AGENT_NETWORK_WAIT_SECONDS": "nhanh lên"}, clear=False):
            self.assertEqual(15.0, self._wait())

    def test_the_agent_path_races_the_poll_instead_of_queueing_behind_it(self) -> None:
        # A1.3. Đường không-Agent (``_compat_generate_image``) đã đua hai việc
        # bằng asyncio.wait(FIRST_COMPLETED); đường Agent thì chờ xong mới
        # poll. Chính chỗ tuần tự ấy là khoảng chết.
        #
        # Bài này đo HÀNH VI, không grep chữ trong source. Bản cũ chỉ hỏi
        # source có chứa "FIRST_COMPLETED" — xanh kể cả khi cuộc đua nối dây
        # sai, task bị rò, hay cả hai đường cùng hỏng mà không ai báo.
        async def bai() -> Any:
            interceptor: asyncio.Future = asyncio.get_running_loop().create_future()
            project: asyncio.Future = asyncio.get_running_loop().create_future()
            interceptor.set_result("ảnh của interceptor")
            return await race_interceptor_and_project_poll(interceptor, project)

        result, raced = chay_co_gioi_han(bai)

        self.assertEqual("ảnh của interceptor", result)
        self.assertEqual([], raced)

    def test_the_race_does_not_make_a_failing_run_slower_than_before(self) -> None:
        """A1.3 — cuộc đua và nhánh timeout tiêu **chung** một ngân sách poll.

        Soát đợt A đo ra: cuộc đua chờ tới khi một đường thắng hoặc **cả hai**
        xong, rồi nhánh ``except`` gọi project poll **lần thứ hai** với đúng
        ngân sách đầy. Lượt không có ảnh nào vì thế mất ~2P (tới ~240s), so
        với 45s + P (~165s) của bản cũ. A1 hứa tiết kiệm 30s một card — hoá ra
        chỉ đúng khi có ảnh, còn khi hỏng thì đắt hơn hẳn, và không bài nào
        nhìn thấy vì không bài nào đo tổng thời gian.

        Bài này canh phép trừ, không canh chữ trong source.
        """
        budget = 120.0

        # Cuộc đua chưa tiêu gì thì lần sau vẫn còn nguyên ngân sách.
        self.assertEqual(budget, remaining_project_poll_budget(budget, 0.0))

        # Tiêu bao nhiêu thì trừ bấy nhiêu — đây là chỗ cắt ~2P xuống ~P.
        self.assertEqual(105.0, remaining_project_poll_budget(budget, 15.0))
        self.assertEqual(20.0, remaining_project_poll_budget(budget, 100.0))

        # Tổng hai lần chờ không bao giờ vượt ngân sách cộng sàn. Đây là câu
        # nói ra điều bản cũ vi phạm: 120 + 120 = 240 > 120 + 10.
        for waited in (0.0, 1.0, 15.0, 60.0, 119.9, 120.0, 300.0):
            total = min(waited, budget) + remaining_project_poll_budget(budget, waited)
            self.assertLessEqual(
                total,
                budget + PROJECT_POLL_SECOND_CHANCE_FLOOR_S,
                f"chờ {waited}s rồi còn được chờ thêm quá nhiều: tổng {total}s",
            )

        # Sàn: câu hỏi "ảnh đã hiện sẵn trong grid chưa" luôn được hỏi, kể cả
        # khi cuộc đua đã tiêu sạch giờ. Hỏi rồi trả lời ngay, không phải chờ.
        self.assertEqual(
            PROJECT_POLL_SECOND_CHANCE_FLOOR_S,
            remaining_project_poll_budget(budget, 10_000.0),
        )
        # Thời gian đã chờ âm (đồng hồ nhảy ngược) không được thành tín dụng.
        self.assertEqual(budget, remaining_project_poll_budget(budget, -50.0))

    def test_a_broken_project_poll_does_not_read_as_a_plain_timeout(self) -> None:
        # Trong cuộc đua, chỉ lỗi của interceptor được giữ lại; đường poll nổ
        # thì `continue` trơn — không log, không ai đọc. Một bug trong poll vì
        # thế trông y hệt một lần hết giờ bình thường, và log lượt chạy chỉ
        # ghi "timeout/recaptcha". Nay nó phải ghi ra câu lỗi thật.
        #
        # Đo hành vi: đường poll nổ, interceptor thắng sau đó, và câu lỗi thật
        # của poll phải đi ra ngoài qua ``on_poll_error``.
        ghi_lai: List[str] = []

        async def bai() -> Any:
            interceptor: asyncio.Future = asyncio.get_running_loop().create_future()
            project: asyncio.Future = asyncio.get_running_loop().create_future()
            project.set_exception(RuntimeError("selector grid đổi tên"))

            async def ghi(loi: BaseException) -> None:
                ghi_lai.append(str(loi))

            async def interceptor_thang() -> None:
                await asyncio.sleep(0)
                if not interceptor.done():
                    interceptor.set_result("ảnh của interceptor")

            asyncio.get_running_loop().create_task(interceptor_thang())
            return await race_interceptor_and_project_poll(
                interceptor, project, on_poll_error=ghi
            )

        result, raced = chay_co_gioi_han(bai)

        self.assertEqual("ảnh của interceptor", result)
        self.assertEqual([], raced)
        self.assertEqual(1, len(ghi_lai), "lỗi của đường poll phải được nói ra đúng một lần")
        self.assertIn("selector grid đổi tên", ghi_lai[0])

    def test_the_project_poll_can_win_the_race(self) -> None:
        # Nửa còn lại của cuộc đua: poll về trước thì ảnh của nó được nhận, và
        # interceptor chưa xong phải bị huỷ chứ không để rò sang lượt sau.
        giu = {}

        async def bai() -> Any:
            interceptor: asyncio.Future = asyncio.get_running_loop().create_future()
            project: asyncio.Future = asyncio.get_running_loop().create_future()
            project.set_result(["ảnh A", "ảnh B"])
            giu["interceptor"] = interceptor
            return await race_interceptor_and_project_poll(interceptor, project)

        result, raced = chay_co_gioi_han(bai)

        self.assertIsNone(result)
        self.assertEqual(["ảnh A", "ảnh B"], raced)
        self.assertTrue(giu["interceptor"].cancelled(), "đường thua phải bị huỷ, không được rò")

    def test_both_paths_failing_raises_the_interceptor_error_not_a_bare_timeout(self) -> None:
        # Ca cả hai đường cùng hỏng. Lỗi của interceptor là lỗi được ném ra —
        # nó là câu nói được vì sao lượt này không có ảnh. Bản cũ không có bài
        # nào đi qua đây.
        ghi_lai: List[str] = []

        async def bai() -> Any:
            interceptor: asyncio.Future = asyncio.get_running_loop().create_future()
            project: asyncio.Future = asyncio.get_running_loop().create_future()
            interceptor.set_exception(TimeoutError("interceptor hết giờ"))
            project.set_exception(RuntimeError("poll nổ"))

            async def ghi(loi: BaseException) -> None:
                ghi_lai.append(str(loi))

            return await race_interceptor_and_project_poll(
                interceptor, project, on_poll_error=ghi
            )

        with self.assertRaises(TimeoutError) as bat:
            chay_co_gioi_han(bai)

        self.assertIn("interceptor hết giờ", str(bat.exception))
        self.assertEqual(["poll nổ"], ghi_lai, "lỗi của poll vẫn phải được nói ra")

    def test_a_poll_that_finds_nothing_does_not_end_the_race(self) -> None:
        # Poll về trước nhưng KHÔNG có ảnh nào: cuộc đua chưa kết thúc, phải
        # chờ tiếp interceptor. Một bản cài đặt coi "poll xong" là "xong" sẽ
        # trả về tay không dù interceptor còn đang có ảnh.
        async def bai() -> Any:
            interceptor: asyncio.Future = asyncio.get_running_loop().create_future()
            project: asyncio.Future = asyncio.get_running_loop().create_future()
            project.set_result([])

            async def interceptor_ve_sau() -> None:
                # Phải là khoảng chờ THẬT, không phải ``sleep(0)``: với
                # ``sleep(0)`` interceptor xong ngay trong lượt ``asyncio.wait``
                # đầu tiên, nên một bản cài đặt chỉ quay đúng một vòng vẫn
                # xanh. Chờ hẳn 50ms thì vòng đầu chỉ thấy mỗi poll, và bài
                # này mới thật sự đòi vòng thứ hai.
                await asyncio.sleep(0.05)
                if not interceptor.done():
                    interceptor.set_result("ảnh về sau")

            asyncio.get_running_loop().create_task(interceptor_ve_sau())
            return await race_interceptor_and_project_poll(interceptor, project)

        result, raced = chay_co_gioi_han(bai)

        self.assertEqual("ảnh về sau", result)
        self.assertEqual([], raced)

    def test_an_interceptor_timeout_does_not_end_the_race(self) -> None:
        # Chốt câu đắt nhất của cuộc đua: interceptor hết giờ là chuyện THƯỜNG
        # trong Agent mode — nó gần như luôn hết giờ. Nếu lỗi ấy kết thúc cuộc
        # đua thì project poll không bao giờ kịp thắng, và A1.3 mất sạch ý
        # nghĩa. Ở đây interceptor nổ trước, poll về sau và phải được nhận.
        async def bai() -> Any:
            interceptor: asyncio.Future = asyncio.get_running_loop().create_future()
            project: asyncio.Future = asyncio.get_running_loop().create_future()
            interceptor.set_exception(TimeoutError("interceptor hết giờ như thường lệ"))

            async def poll_ve_sau() -> None:
                # Chờ thật, cùng lý do như bài trên: poll phải về SAU khi vòng
                # ``asyncio.wait`` đầu tiên đã trả về với mỗi lỗi interceptor.
                await asyncio.sleep(0.05)
                if not project.done():
                    project.set_result(["ảnh poll tìm được"])

            asyncio.get_running_loop().create_task(poll_ve_sau())
            return await race_interceptor_and_project_poll(interceptor, project)

        result, raced = chay_co_gioi_han(bai)

        self.assertIsNone(result)
        self.assertEqual(["ảnh poll tìm được"], raced)

    def test_the_loser_is_cancelled_and_awaited_so_nothing_leaks(self) -> None:
        # Chốt phần dọn dẹp: đường thua bị huỷ VÀ được await lại. Thiếu vế sau
        # thì Python in "Task exception was never retrieved" ở một lượt sau,
        # lạc hẳn khỏi chỗ gây ra nó.
        da_don = {"project": False, "don_xong": False}

        async def bai() -> Any:
            interceptor: asyncio.Future = asyncio.get_running_loop().create_future()
            interceptor.set_result("xong ngay")

            async def poll_cham() -> List[Any]:
                # Ngắn thôi: nếu vế huỷ bị gỡ, ``gather`` sẽ chờ hết khoảng
                # này rồi bài đỏ ở ``da_don`` — hỏng nhanh và nói được, thay
                # vì treo cả bộ test.
                try:
                    await asyncio.sleep(0.5)
                    return []
                except asyncio.CancelledError:
                    da_don["project"] = True
                    # Dọn dẹp có điểm chờ — ngoài đời là đóng page/context.
                    # Chính chỗ này phân biệt "đã gọi cancel()" với "đã await
                    # lại cho xong": thiếu ``gather`` thì cuộc đua trả về
                    # ngay sau ``cancel()``, task chưa kịp chạy hết nhánh
                    # dọn, và ``don_xong`` còn False.
                    await asyncio.sleep(0.05)
                    da_don["don_xong"] = True
                    raise

            project = asyncio.get_running_loop().create_task(poll_cham())
            return await race_interceptor_and_project_poll(interceptor, project), project

        (result, _raced), project = chay_co_gioi_han(bai)

        self.assertEqual("xong ngay", result)
        self.assertTrue(da_don["project"], "đường thua phải nhận được lệnh huỷ")
        self.assertTrue(project.done(), "đường thua phải xong hẳn, không để rò")
        self.assertTrue(
            da_don["don_xong"],
            "cuộc đua phải await lại đường đã huỷ cho tới khi nó dọn xong, "
            "không chỉ gọi cancel() rồi bỏ đi",
        )


class ApprovalDialogWaitTests(unittest.TestCase):
    """A2 — chờ hộp phê duyệt cũng đốt hết giờ khi không có hộp nào.

    Khi Flow đã nhớ "không hỏi lại" từ lượt trước, hộp không bao giờ hiện,
    nhưng vòng poll vẫn quay đủ tới 45 giây rồi mới trả về. ``execution-notes``
    đo bước này lệch 26 giây giữa hai lượt — đủ để nuốt trọn 30 giây vừa tiết
    kiệm được ở A1.

    Thông tin cần để thoát sớm **đã có sẵn**: script trong ``page.evaluate``
    trả ``waiting`` để phân biệt "chữ phê duyệt có hiện, nút chưa tìm ra" với
    "không có hộp nào". Cờ ấy đang bị bỏ đi.
    """

    def setUp(self) -> None:
        self.service = FlowWebService.__new__(FlowWebService)
        self.polls = 0

    def _page(self, *, waiting: bool) -> Any:
        test = self

        class _Page:
            def get_by_role(self, *_args: Any, **_kwargs: Any) -> Any:
                # Playwright thật ném khi không tìm thấy; vòng lặp bắt và đi
                # tiếp xuống page.evaluate. Bài này chỉ quan tâm nhánh đó.
                raise RuntimeError("no button")

            async def evaluate(self, _script: str) -> Dict[str, Any]:
                test.polls += 1
                return {
                    "ok": False,
                    "waiting": waiting,
                    "detail": (
                        "approval text visible, approve button not found"
                        if waiting
                        else "approval dialog not visible"
                    ),
                }

        return _Page()

    def _approve(self, page: Any, timeout_s: float) -> tuple[float, tuple[bool, str]]:
        async def go() -> tuple[bool, str]:
            return await FlowWebService._approve_flow_agent_generation(
                self.service, page, timeout_s=timeout_s
            )

        started = time.monotonic()
        result = asyncio.run(go())
        return time.monotonic() - started, result

    def test_a_visible_dialog_is_still_waited_out(self) -> None:
        # Không được đánh đổi: hộp *có* hiện mà chưa bấm được là sự cố thật,
        # phải chờ hết giờ như cũ chứ không bỏ sớm.
        with patch.dict(os.environ, {"FLOW_AGENT_APPROVAL_GRACE_S": "1"}, clear=False):
            elapsed, (ok, _detail) = self._approve(self._page(waiting=True), timeout_s=3.0)
        self.assertFalse(ok)
        self.assertGreaterEqual(elapsed, 2.5)

    def test_the_two_cases_do_not_read_the_same_in_the_run_log(self) -> None:
        # A2.2: ca "Flow không hỏi nữa" là bình thường; ca "có hỏi mà không bấm
        # được" cần người xem. Hôm nay cả hai rơi về cùng một câu.
        with patch.dict(os.environ, {"FLOW_AGENT_APPROVAL_GRACE_S": "1"}, clear=False):
            _e1, (_ok1, quiet) = self._approve(self._page(waiting=False), timeout_s=30.0)
            self.polls = 0
            _e2, (_ok2, stuck) = self._approve(self._page(waiting=True), timeout_s=3.0)
        self.assertNotEqual(quiet, stuck)

    def test_the_grace_window_is_a_named_knob(self) -> None:
        self.assertTrue(
            hasattr(FlowWebService, "_flow_agent_approval_grace_seconds"),
            "cửa sổ ân hạn phải là một hằng số có tên, đặt cạnh chỗ dùng (A2.3)",
        )


class RecaptchaActionTests(unittest.TestCase):
    """A3 — token cho 2K đang mint bằng action của việc sinh ảnh.

    ``_compat_get_recaptcha_token`` viết cứng ``action: 'GENERATE'`` và là
    nguồn token cho **cả** sinh ảnh **lẫn** ``flow/upsampleImage``. reCAPTCHA
    Enterprise chấm điểm theo cặp (site key, action), nên gửi sai action là
    một lý do rất đời thường để ăn 403 — đúng lỗi đã ăn mọi ảnh chưa được 2K
    trên card thật.

    **Đây vẫn là giả thuyết chưa xác minh.** Bài test không đòi đổi action;
    nó đòi đổi được action mà không phải sửa chuỗi lồng trong f-string.
    """

    def test_the_script_is_built_by_a_named_function(self) -> None:
        self.assertTrue(
            hasattr(FlowWebService, "_recaptcha_token_script"),
            "phải tách _recaptcha_token_script(action) ra khỏi thân hàm (A3.1)",
        )

    def test_the_action_is_a_parameter_not_a_literal(self) -> None:
        script = FlowWebService._recaptcha_token_script("UPSCALE_IMAGE")
        self.assertIn("UPSCALE_IMAGE", script)
        self.assertNotIn("'GENERATE'", script)

    def test_the_generate_path_keeps_todays_action(self) -> None:
        # Đợt này **không** đổi hành vi: đường sinh ảnh vẫn GENERATE.
        script = FlowWebService._recaptcha_token_script("GENERATE")
        self.assertIn("GENERATE", script)

    def test_the_upscale_action_comes_from_the_environment(self) -> None:
        # A3.3: mặc định vẫn GENERATE cho tới khi đo được cái Flow thật gửi,
        # đúng lối FLOW_AGENT_NETWORK_WAIT_SECONDS đã dùng để đo A1.
        service = FlowWebService.__new__(FlowWebService)
        with patch.dict(os.environ, {"FLOW_UPSAMPLE_RECAPTCHA_ACTION": ""}, clear=False):
            self.assertEqual("GENERATE", service._flow_upsample_recaptcha_action())
        with patch.dict(os.environ, {"FLOW_UPSAMPLE_RECAPTCHA_ACTION": "UPSCALE"}, clear=False):
            self.assertEqual("UPSCALE", service._flow_upsample_recaptcha_action())

    def test_no_hardcoded_action_is_left_in_the_compat_patch(self) -> None:
        source = inspect.getsource(FlowWebService._patch_flow_runtime_compat)
        self.assertNotIn(
            "action: 'GENERATE'",
            source,
            "action viết cứng trong f-string là chỗ không đổi được mà không sửa code",
        )


class HistoryKeepsRealRunsTests(unittest.TestCase):
    """A7 — một loạt lượt hỏng 5 giây không được đẩy lịch sử thật ra.

    Trong sự cố quota, watcher và agent bot mỗi cái fan-out một job cho mỗi
    thẻ con, mỗi 3 phút, mỗi job chết trong ~5 giây ở bước trình duyệt và
    **không có artifact nào**. Sáu thẻ lấp đầy cả 50 ô trước trưa. Đó là thứ
    làm sự cố trông như "không có gì chạy" thay vì "hết quota".
    """

    def _failure(self, index: int) -> JobRecord:
        return JobRecord(id=f"fail-{index}", type="image", status="failed", input={}, artifacts=[])

    def _success(self, index: int) -> JobRecord:
        return JobRecord(
            id=f"ok-{index}",
            type="image",
            status="completed",
            input={},
            artifacts=[JobArtifact(local_path=f"/tmp/anh-{index}.png", mime_type="image/png", url="")],
        )

    def test_a_flood_of_empty_failures_does_not_evict_every_real_run(self) -> None:
        jobs = [self._failure(i) for i in range(60)] + [self._success(i) for i in range(5)]
        kept = trim_job_history(jobs)
        survivors = [job.id for job in kept if job.id.startswith("ok-")]
        self.assertEqual(
            5,
            len(survivors),
            "60 lượt hỏng không artifact đã đẩy mọi lượt thật ra khỏi dashboard",
        )

    def test_the_reserved_slots_are_a_named_constant(self) -> None:
        from flow_web import store

        self.assertTrue(
            hasattr(store, "JOB_HISTORY_MIN_WITH_ARTIFACTS"),
            "hạn ngạch tối thiểu phải có tên để người sau đọc được (A7.1)",
        )

    def test_newest_first_order_is_untouched(self) -> None:
        # A7.3: đây là nguồn cho dashboard; đảo thứ tự là đổi giao diện.
        jobs = [self._success(i) for i in range(10)]
        self.assertEqual([job.id for job in jobs], [job.id for job in trim_job_history(jobs)])

    def test_a_short_history_is_returned_unchanged(self) -> None:
        jobs = [self._failure(i) for i in range(JOB_HISTORY_LIMIT - 1)]
        self.assertEqual(len(jobs), len(trim_job_history(jobs)))


class _FakeUpsampleClient:
    """Y hệt bản trong ``tests/test_erp_review.py``.

    Chỉ hai thứ ``_upsample_image_via_flow`` thật sự chạm là thật: mint token
    (``_client_context``) và POST bản upscale (``_fetch``). ``refuse_tokens``
    gọi tên những token Google trả lại bằng đúng cái 403 đã để ảnh ở 1024.
    """

    BIG = b"anh-2k-that"

    def __init__(self, test: unittest.TestCase, *, refuse_all: bool = False) -> None:
        self._test = test
        self._refuse_all = refuse_all
        self.contexts = 0
        self.tokens_used: List[str] = []
        self._api = self

    async def _client_context(self) -> Dict[str, Any]:
        self.contexts += 1
        return {"token": f"tok-{self.contexts}"}

    async def _fetch(self, method: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        token = str((payload.get("clientContext") or {}).get("token") or "")
        self.tokens_used.append(token)
        if self._refuse_all:
            raise RuntimeError("HTTP 403 on upsampleImage: reCAPTCHA evaluation failed")
        return {"encodedImage": base64.b64encode(self.BIG).decode()}


class _ServiceCase(unittest.TestCase):
    """Khuôn dựng dùng chung, chép từ ``ErpReviewFlowTests``."""

    TASK = "TASK-2026-00616"

    def setUp(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.patches = [
            patch("flow_web.store.STATE_FILE", self.root / "state.json"),
            patch("flow_web.store.ensure_app_dirs", lambda: self.root.mkdir(parents=True, exist_ok=True)),
            patch("flow_web.service.ensure_app_dirs", lambda: self.root.mkdir(parents=True, exist_ok=True)),
        ]
        for item in self.patches:
            item.start()
        self.store = StateStore()
        self.service = FlowWebService(self.store)
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(api_key="test-key", api_secret="test-secret", project_id="PROJ-0013")
            )
        )

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tempdir.cleanup()
        self.loop.close()
        asyncio.set_event_loop(None)

    def _job(self, count: int = 3) -> JobRecord:
        artifacts = []
        for index in range(count):
            path = self.root / f"anh-{index}.png"
            path.write_bytes(b"png-bytes-%d" % index)
            artifacts.append(JobArtifact(local_path=str(path), mime_type="image/png", url=""))
        job = JobRecord(
            id="job-erp",
            type="image",
            status="completed",
            input={
                "type": "image",
                "prompt": "khăn tay",
                "count": count,
                "erp_enabled": True,
                "erp_task_id": "TASK-2026-00202",
                "erp_output_task_id": self.TASK,
                "erp_project_id": "PROJ-0013",
            },
            artifacts=artifacts,
        )
        return self.loop.run_until_complete(self.store.add_job(job))


class UiFallbackBeforeManualFlagTests(_ServiceCase):
    """A4 — cờ chờ người đang tắt đúng đường cứu được ảnh.

    Lượt vượt ngưỡng ``needs_manual_review`` trả nguyên bytes cũ **trước khi**
    thử ``_upsample_image_via_flow_ui_download``, và mọi lượt sau đó bị chốt
    chặn đầu hàm chặn luôn. Nhưng số đo nói chính đường ấy là đường cứu ảnh:
    *"the retry is not what saves the image; _upsample_image_via_flow_ui_download is."*

    Chú ý: ``_flow_upsample_rounds_for_next_image`` và
    ``FLOW_UPSAMPLE_RECAPTCHA_GIVE_UP_AFTER`` mà ``execution-notes.md`` còn
    nhắc **đã bị gỡ** ở ``17d860a``. Bài này không đòi khôi phục chúng — bộ
    đếm theo lượt chạy ở A4.4 là thứ khác, và mang tên khác
    (``FLOW_UPSAMPLE_RECAPTCHA_RUN_GIVE_UP_AFTER``) đúng để không ai nhầm nó
    với cái knob cũ.
    """

    @staticmethod
    def _flow_media_name(label: str) -> str:
        """Tên media của Flow là UUID; nhãn ``media-1`` không phải.

        Sửa **fixture**, không sửa phép thử: ``_normal_flow_media_name`` loại
        thẳng mọi thứ không có hình UUID (đúng việc của nó — nó chặn URL và
        rác), nên với nhãn ``media-1`` thì ``_upsample_image_via_flow`` trả về
        ngay ở chốt đầu hàm và không câu nào bên dưới được chạy. Mỗi nhãn cho
        một UUID riêng, y như ``tests/test_erp_review.py`` đang dùng.
        """
        digits = "".join(ch for ch in str(label) if ch.isdigit()) or "0"
        return f"{int(digits):08d}-2222-3333-4444-555555555555"

    def _upsample(self, client: Any, media: str = "media-1") -> bytes:
        return self.loop.run_until_complete(
            self.service._upsample_image_via_flow(
                client,
                b"anh-1024",
                media_generation_id=self._flow_media_name(media),
                erp_task_id=self.TASK,
                job_id="job-erp",
                session_lock_held=True,
            )
        )

    def test_the_ui_path_is_tried_before_a_media_is_handed_to_a_human(self) -> None:
        self._job()
        client = _FakeUpsampleClient(self, refuse_all=True)
        tried: List[str] = []

        async def fake_ui(_client: Any, media_id: str) -> bytes:
            tried.append(media_id)
            return _FakeUpsampleClient.BIG

        with patch.object(self.service, "_upsample_image_via_flow_ui_download", side_effect=fake_ui):
            with patch.object(self.service, "_image_size_from_bytes", return_value=(2048, 2048)):
                for _pass in range(3):
                    self._upsample(client)
        self.assertGreaterEqual(
            len(tried),
            3,
            "mọi lượt phải thử đường UI: nó không tiêu token reCAPTCHA nào (A4.1)",
        )

    def test_media_da_gan_co_cho_nguoi_van_duoc_thu_ui_moi_luot(self) -> None:
        """A4.2 — chốt chặn đầu hàm chỉ được chặn đường API.

        Bài trên **không** khoá được A4.2 và đừng nhầm là có: ở đó đường UI
        cứu được ảnh mỗi lượt, nên bản ghi bền chỉ là ``api_refused``,
        ``api_blocked`` không bao giờ bật, và chốt chặn không bao giờ được hỏi
        tới. Bài này bật cờ thật trước, rồi mới hỏi.
        """
        self._job()
        client = _FakeUpsampleClient(self, refuse_all=True)

        async def ui_hong(_client: Any, _media_id: str) -> bytes:
            return b""

        # Hỏng cả hai đường đủ số lượt để media bị gắn cờ chờ người.
        with patch.object(self.service, "_upsample_image_via_flow_ui_download", side_effect=ui_hong):
            for _pass in range(3):
                self._upsample(client)
        self.assertTrue(
            self.service._flow_upsample_recaptcha_blocked_media("job-erp", self.TASK),
            "dựng cảnh hỏng: chưa gắn được cờ thì lượt sau không kiểm tra được gì",
        )

        # Lượt sau khi đã gắn cờ: token không được mint nữa, nhưng đường UI —
        # thứ không tiêu token nào và là thứ thật sự cứu được ảnh — vẫn phải
        # được thử đúng một lần.
        sau_khi_gan_co: List[str] = []

        async def ui_dem(_client: Any, media_id: str) -> bytes:
            sau_khi_gan_co.append(media_id)
            return b""

        with patch.object(self.service, "_upsample_image_via_flow_ui_download", side_effect=ui_dem):
            self._upsample(client)
        self.assertEqual(
            [self._flow_media_name("media-1")],
            sau_khi_gan_co,
            "media đã gắn cờ vẫn phải được thử đường UI một lần mỗi lượt (A4.2)",
        )

    def test_a_media_the_ui_path_rescues_is_not_flagged_for_a_human(self) -> None:
        self._job()
        client = _FakeUpsampleClient(self, refuse_all=True)

        async def fake_ui(_client: Any, _media_id: str) -> bytes:
            return _FakeUpsampleClient.BIG

        with patch.object(self.service, "_upsample_image_via_flow_ui_download", side_effect=fake_ui):
            with patch.object(self.service, "_image_size_from_bytes", return_value=(2048, 2048)):
                for _pass in range(3):
                    self._upsample(client)
        blocked = self.service._flow_upsample_recaptcha_blocked_media("job-erp", self.TASK)
        self.assertEqual(
            [],
            blocked,
            "ảnh đã được cứu thì không có gì để người xem lại (A4.3)",
        )

    def test_a_media_both_paths_fail_on_is_still_flagged(self) -> None:
        # Không được đánh đổi: hỏng cả hai đường vẫn phải gọi người.
        self._job()
        client = _FakeUpsampleClient(self, refuse_all=True)

        async def fake_ui(_client: Any, _media_id: str) -> bytes:
            return b""

        with patch.object(self.service, "_upsample_image_via_flow_ui_download", side_effect=fake_ui):
            for _pass in range(3):
                self._upsample(client)
        blocked = self.service._flow_upsample_recaptcha_blocked_media("job-erp", self.TASK)
        self.assertTrue(blocked, "hỏng cả hai đường thì phải gọi người")

    def test_a_run_stops_paying_three_rounds_per_image_once_it_knows(self) -> None:
        # A4.4. Bản ghi bền theo media không cứu được chỗ này: media mới thì
        # chưa có bản ghi, nên ảnh nào cũng trả đủ 3 vòng cho lần đầu. Trên
        # card 12 ảnh với reCAPTCHA hỏng toàn cục đó là 36 lần mint, mỗi lần
        # một lượt giành _browser_session_lock.
        self._job()
        client = _FakeUpsampleClient(self, refuse_all=True)

        async def fake_ui(_client: Any, _media_id: str) -> bytes:
            return b""

        with patch.dict(os.environ, {"FLOW_UPSAMPLE_RECAPTCHA_RUN_GIVE_UP_AFTER": "2"}, clear=False):
            with patch.object(self.service, "_upsample_image_via_flow_ui_download", side_effect=fake_ui):
                for index in range(6):
                    self._upsample(client, media=f"media-{index}")
        self.assertLess(
            client.contexts,
            12,
            "sau hai ảnh bị từ chối mọi vòng, những ảnh sau chỉ được mint một lần",
        )


class UiDownloadLogsSuccessTests(_ServiceCase):
    """A5 — đường cứu 2K bằng UI im lặng đúng lúc nó thành công.

    Bốn nhánh hỏng đều ``log.warning``; nhánh thành công không ghi gì. Người
    đọc log thấy ba dòng 403 rồi im lặng, kết luận là ảnh hỏng — trong khi ảnh
    đã được cứu. ``execution-notes`` gọi thẳng: *"it does not log on success,
    which is why the path is easy to miss."*
    """

    # Tên media của Flow là UUID (xem ``_flow_media_name`` ở lớp A4): sửa
    # fixture, không sửa phép thử — nhãn ``media-1`` bị
    # ``_normal_flow_media_name`` loại ngay ở chốt đầu hàm.
    MEDIA = "00000001-2222-3333-4444-555555555555"

    def _job_log_text(self, job_id: str) -> str:
        """Nối các dòng log của lượt chạy — ``JobRecord.logs`` là ``List[JobLog]``."""
        job = self.store.get_job(job_id)
        self.assertIsNotNone(job, f"không tìm thấy lượt chạy {job_id}")
        return " ".join(str(getattr(entry, "message", entry)) for entry in (job.logs or []))

    def test_a_rescued_image_says_so_in_the_run_log(self) -> None:
        self._job()
        client = _FakeUpsampleClient(self, refuse_all=True)

        async def fake_ui(_client: Any, _media_id: str) -> bytes:
            return _FakeUpsampleClient.BIG

        with patch.object(self.service, "_upsample_image_via_flow_ui_download", side_effect=fake_ui):
            with patch.object(self.service, "_image_size_from_bytes", return_value=(2048, 2048)):
                self.loop.run_until_complete(
                    self.service._upsample_image_via_flow(
                        client,
                        b"anh-1024",
                        media_generation_id=self.MEDIA,
                        erp_task_id=self.TASK,
                        job_id="job-erp",
                        session_lock_held=True,
                    )
                )
        dong = self._job_log_text("job-erp")
        self.assertIn(
            "ui_download",
            dong,
            "dashboard là nơi người vận hành thật sự đọc, không phải log tiến trình (A5.2)",
        )
        # A5.1 đòi đủ ba thứ, không chỉ tên đường: thiếu media id thì trên một
        # card 12 ảnh không ai biết dòng này nói về ảnh nào, và thiếu số byte
        # thì không phân biệt được ảnh 2K thật với một khung trắng 2K.
        self.assertIn(self.MEDIA, dong, "log phải gọi tên media (A5.1)")
        self.assertIn(
            f"{len(_FakeUpsampleClient.BIG)} byte",
            dong,
            "log phải nói số byte, không chỉ kích thước (A5.1)",
        )

    def test_the_api_path_names_itself_too(self) -> None:
        # Đọc log phải biết được đường nào cho ra ảnh, chứ không chỉ biết là có.
        self._job()
        client = _FakeUpsampleClient(self)
        with patch.object(self.service, "_image_size_from_bytes", return_value=(2048, 2048)):
            self.loop.run_until_complete(
                self.service._upsample_image_via_flow(
                    client,
                    b"anh-1024",
                    media_generation_id=self.MEDIA,
                    erp_task_id=self.TASK,
                    job_id="job-erp",
                    session_lock_held=True,
                )
            )
        dong = self._job_log_text("job-erp")
        # ``assertIn("api", ...)`` một mình quá lỏng: dòng của đường ui_download
        # cũng chứa chữ "api" ("đường api đã bị từ chối"), nên một bản cài đặt
        # để đường api im lặng rồi rơi xuống UI vẫn đi qua được câu ấy. Hỏi
        # đúng cụm, và hỏi luôn rằng dòng này **không phải** dòng của đường kia.
        self.assertIn("đường api", dong)
        self.assertNotIn("ui_download", dong)
        self.assertIn(self.MEDIA, dong, "log phải gọi tên media (A5.1)")
        self.assertIn(
            f"{len(_FakeUpsampleClient.BIG)} byte",
            dong,
            "log phải nói số byte, không chỉ kích thước (A5.1)",
        )


class _FakeGridPage:
    """Trang Flow giả chỉ có một thứ: lưới ô ảnh, theo ``src``.

    Lưới thật là ``cdk-virtual-scroll-viewport``: chỉ ``drawn`` ô quanh chỗ
    đang cuộn là có trong DOM. ``evaluate`` làm đúng việc của đoạn JS: tìm ô
    có ``src`` chứa một trong các mẩu Python đưa sang; không thấy thì cuộn
    (về đầu nếu được hỏi ``fromTop``, không thì xuống một màn) và báo đã chạm
    đáy hay chưa.
    """

    def __init__(self, srcs: List[str], *, drawn: int = 0, top: int = 0) -> None:
        self.srcs = srcs
        self.drawn = drawn or len(srcs)
        self.top = top
        self.asked: List[Any] = []

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        self.asked.append(arg)
        arg = arg if isinstance(arg, dict) else {}
        needles = list(arg.get("needles") or [])
        for index in range(self.top, min(len(self.srcs), self.top + self.drawn)):
            if any(needle and needle in self.srcs[index] for needle in needles):
                return {"x": 10.0, "y": 100.0 * index, "width": 256.0, "height": 256.0, "visible": True}
        if "cdk-virtual-scroll-viewport" not in script:
            # Đoạn JS không biết lưới cuộn ảo thì nó cũng không cuộn gì.
            return None
        if arg.get("fromTop") and self.top > 0:
            self.top = 0
            return {"scrolled": True, "exhausted": False}
        if self.top + self.drawn >= len(self.srcs):
            return {"scrolled": True, "exhausted": True}
        self.top += self.drawn
        return {"scrolled": True, "exhausted": False}


class VisibleGridImagesGetTheir2KTests(_ServiceCase):
    """Ảnh lấy từ grid Flow cũng phải lên 2K.

    Flow giờ hiện ảnh bằng ``https://flow-content.google/image/<uuid>``. Cả
    95 ảnh Flow Agent ngày 10/09 đều đi đường dự phòng UI: ``media_name`` là
    ``visible-flow-N.jpg``, mã media thật chỉ nằm trong đường dẫn. App đọc mã
    từ ``media_name`` nên thấy rỗng, log "missing Flow media id", rồi đăng
    nguyên ảnh 1K lên ERP.
    """

    MEDIA = "3f2b9c1e-8a4d-4e21-9b7a-0c5d6e7f8a9b"
    URL = f"https://flow-content.google/image/{MEDIA}"

    def _grid_artifact(self) -> JobArtifact:
        path = self.root / "visible-flow-1.jpg"
        path.write_bytes(b"anh-1024")
        return JobArtifact(
            label="Ảnh 1",
            media_name="visible-flow-1.jpg",
            url=self.URL,
            local_path=str(path),
            mime_type="image/jpeg",
        )

    def test_the_media_id_is_read_from_the_image_address(self) -> None:
        asked: List[str] = []

        async def fake_flow(_client: Any, _bytes: bytes, **kwargs: Any) -> bytes:
            asked.append(str(kwargs.get("media_generation_id") or ""))
            return _FakeUpsampleClient.BIG

        def size(data: bytes) -> tuple:
            return (2048, 2048) if data == _FakeUpsampleClient.BIG else (1024, 1024)

        with patch.object(self.service, "_upsample_image_via_flow", side_effect=fake_flow):
            with patch.object(self.service, "_image_size_from_bytes", side_effect=size):
                result = self.loop.run_until_complete(
                    self.service._upsample_artifact_bytes(
                        self._grid_artifact(), self.URL, client=object(), job_id="job-erp"
                    )
                )
        self.assertEqual(asked, [self.MEDIA], "mã media phải lấy từ đường dẫn flow-content")
        self.assertEqual(result.source, "flow_2k")
        self.assertEqual(result.bytes, _FakeUpsampleClient.BIG)

    def test_an_old_style_redirect_address_still_gives_its_media_id(self) -> None:
        artifact = self._grid_artifact()
        artifact.url = (
            "https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name=" + self.MEDIA
        )
        self.assertEqual(self.service._artifact_flow_media_name(artifact), self.MEDIA)

    def test_a_real_media_name_wins_over_the_address(self) -> None:
        other = "00000001-2222-3333-4444-555555555555"
        artifact = self._grid_artifact()
        artifact.media_name = other
        self.assertEqual(self.service._artifact_flow_media_name(artifact), other)

    def test_an_address_without_a_media_id_gives_nothing(self) -> None:
        artifact = self._grid_artifact()
        artifact.url = "https://lh3.googleusercontent.com/some-random-image"
        self.assertEqual(self.service._artifact_flow_media_name(artifact), "")

    def test_the_ui_2k_download_finds_a_flow_content_tile(self) -> None:
        page = _FakeGridPage(
            [
                "https://flow-content.google/image/00000009-2222-3333-4444-555555555555",
                self.URL,
            ]
        )
        rect = self.loop.run_until_complete(
            self.service._flow_ui_image_rect_for_media(page, self.MEDIA)
        )
        self.assertEqual(rect.get("y"), 100.0, "phải bấm đúng ô có ảnh này, không phải ô đầu")
        self.assertEqual(rect.get("width"), 256.0)

    def test_the_ui_2k_download_still_finds_a_redirect_tile(self) -> None:
        page = _FakeGridPage(
            ["https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name=" + self.MEDIA]
        )
        rect = self.loop.run_until_complete(
            self.service._flow_ui_image_rect_for_media(page, self.MEDIA)
        )
        self.assertEqual(rect.get("width"), 256.0)

    def _others(self, count: int) -> List[str]:
        return [
            f"https://flow-content.google/image/{index:08d}-2222-3333-4444-555555555555"
            for index in range(100, 100 + count)
        ]

    def test_a_tile_pushed_below_the_drawn_rows_is_found_by_scrolling(self) -> None:
        """Mỗi thẻ mới đẩy 12 ô lên trên. Tới lượt 2K thì ô đã ra khỏi DOM."""
        page = _FakeGridPage(self._others(30) + [self.URL], drawn=12)
        rect = self.loop.run_until_complete(
            self.service._flow_ui_image_rect_for_media(page, self.MEDIA)
        )
        self.assertEqual(
            (rect.get("y"), rect.get("width")), (3000.0, 256.0), "phải cuộn lưới tới đúng ô của ảnh"
        )

    def test_the_search_starts_from_the_top_of_the_grid(self) -> None:
        """Ảnh mới nằm trên cùng. Lượt tìm trước cuộn xuống đâu thì mặc nó."""
        page = _FakeGridPage([self.URL] + self._others(40), drawn=12, top=24)
        rect = self.loop.run_until_complete(
            self.service._flow_ui_image_rect_for_media(page, self.MEDIA)
        )
        self.assertEqual((rect.get("y"), rect.get("width")), (0.0, 256.0))

    def test_a_tile_missing_from_the_whole_grid_does_not_hold_the_browser_45s(self) -> None:
        """Mỗi ảnh không thấy ô từng giữ trình duyệt 45 giây.

        Đường này giữ khoá phiên trình duyệt, nên 45 giây ấy là 45 giây không
        thẻ nào được tạo ảnh. Nhân 12 ảnh một thẻ là 9 phút. Cuộn hết lưới mà
        không thấy thì thôi.
        """
        page = _FakeGridPage(self._others(30), drawn=12)
        started = time.monotonic()
        rect = self.loop.run_until_complete(
            self.service._flow_ui_image_rect_for_media(page, self.MEDIA)
        )
        self.assertEqual(rect, {})
        self.assertLess(time.monotonic() - started, 10.0, "hết lưới rồi thì không chờ thêm")

    def test_a_grid_image_waiting_for_a_person_is_not_posted_at_1k(self) -> None:
        """Cờ chờ người ghi theo mã media. Khâu đăng ERP phải tra đúng mã ấy.

        Tra bằng ``media_name`` thì ảnh grid ra mã rỗng, không khớp cờ nào, và
        ảnh 1K lại được đăng lên thẻ như chưa hề có cờ.
        """
        state_key = self.service._flow_upsample_recaptcha_state_key(self.TASK, "job-erp", self.MEDIA)
        job = JobRecord(
            id="job-erp",
            type="image",
            status="completed",
            input={
                "type": "image",
                "prompt": "khăn tay",
                "count": 1,
                "erp_enabled": True,
                "erp_task_id": "TASK-2026-00202",
                "erp_output_task_id": self.TASK,
                "erp_project_id": "PROJ-0013",
            },
            artifacts=[self._grid_artifact()],
        )
        job.result = {
            "flow_upsample_recaptcha": {
                "version": 1,
                "media": {
                    state_key: {
                        "job_id": "job-erp",
                        "task_id": self.TASK,
                        "media_id": self.MEDIA,
                        "needs_manual_review": True,
                        "next_retry_at": "2026-09-11T00:00:00+00:00",
                    }
                },
            }
        }
        self.loop.run_until_complete(self.store.add_job(job))
        posted: List[Any] = []
        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_task_detail", return_value={"name": self.TASK, "comments": []}
        ), patch.object(
            self.service, "_erp_publish_review_comment", side_effect=lambda *a: posted.append(a) or {}
        ), patch.object(
            self.service, "_upsample_artifact_bytes", side_effect=Exception("no flow session")
        ):
            summary = self.loop.run_until_complete(self.service.publish_erp_review("job-erp"))
        self.assertEqual(posted, [], "ảnh đang chờ người không được đăng bản 1K")
        self.assertEqual([item["media_id"] for item in summary["manual_review"]], [self.MEDIA])


class SpentAgentQuotaStillGets2KTests(_ServiceCase):
    """Hết quota tạo ảnh không được kéo luôn bước nâng 2K xuống.

    Tối 10/9, 20:20: Flow báo hết quota ngày của Nano Banana 2 và app khoá
    profile tới 13:59 hôm sau. Lượt đang chạy vẫn còn ảnh vừa tạo xong, nhưng
    ``_with_client`` từ chối mở Flow cho mọi việc, kể cả việc tải bản 2K. Log
    20:21 có tám dòng "Flow 2K upscaling client failed: Tat ca Chrome profile
    Flow da het quota", và tám ảnh ấy lên thẻ ở 1K. Quota ấy là quota tạo ảnh;
    nâng 2K không tạo ảnh mới.
    """

    PROJECT = "42f50a6f-5ab5-407b-ade1-eb6c23158377"
    MEDIA = "3f2b9c1e-8a4d-4e21-9b7a-0c5d6e7f8a9b"
    URL = f"https://flow-content.google/image/{MEDIA}"

    def setUp(self) -> None:
        super().setUp()
        self.profile = FlowBrowserProfile(
            index=0, label="Flow profile 1", path=self.root / "profile", project_id=self.PROJECT
        )
        self.blocked_until = time.time() + 3600
        self.service._flow_profile_quota_blocked_until = {self.profile.key: self.blocked_until}
        self.client = object()
        self.opened = AsyncMock(return_value=object())
        for item in (
            patch.object(self.service, "_flow_profile_specs", return_value=[self.profile]),
            patch.object(self.service, "_should_keep_flow_browser_open", return_value=True),
            patch.object(self.service, "_flow_modules", return_value=(object, None, None, None, None)),
            patch.object(self.service, "_ensure_shared_browser", self.opened),
            patch.object(
                self.service, "_build_client_from_shared_browser", AsyncMock(return_value=self.client)
            ),
        ):
            item.start()
            self.addCleanup(item.stop)

    def _artifact(self) -> JobArtifact:
        path = self.root / "anh-1k.jpg"
        path.write_bytes(b"anh-1024")
        return JobArtifact(media_name=self.MEDIA, url=self.URL, local_path=str(path), mime_type="image/jpeg")

    def test_the_2k_batch_opens_flow_while_the_agent_quota_is_spent(self) -> None:
        upscaled = ImageUpscaleResult(bytes=b"anh-2k", mime_type="image/jpeg", source="flow_2k")
        with patch.object(self.service, "_upsample_artifact_bytes", AsyncMock(return_value=upscaled)):
            results = self.loop.run_until_complete(
                self.service._upsample_artifacts_bytes(
                    [(0, self._artifact(), self.URL)], erp_task_id=self.TASK, job_id="job-erp"
                )
            )
        self.assertEqual(1, self.opened.await_count, "bước 2K phải được mở Flow dù quota tạo ảnh đã hết")
        self.assertEqual(b"anh-2k", results[0].bytes)

    def test_a_single_image_also_gets_its_2k_while_the_agent_quota_is_spent(self) -> None:
        sizes = iter([(1024, 1024), (2048, 2048)])
        with patch.object(
            self.service, "_upsample_image_via_flow", AsyncMock(return_value=b"anh-2k")
        ) as upsample, patch.object(self.service, "_image_size_from_bytes", side_effect=lambda _b: next(sizes)):
            result = self.loop.run_until_complete(
                self.service._upsample_artifact_bytes(self._artifact(), self.URL)
            )
        upsample.assert_awaited_once()
        self.assertEqual(("flow_2k", b"anh-2k"), (result.source, result.bytes))

    def test_generating_still_refuses_a_profile_out_of_quota(self) -> None:
        called: List[Any] = []

        async def generate(client: Any) -> str:
            called.append(client)
            return "anh"

        with self.assertRaises(HTTPException) as ctx:
            self.loop.run_until_complete(self.service._with_client(generate))
        self.assertEqual(429, ctx.exception.status_code)
        self.assertEqual([], called)
        self.opened.assert_not_awaited()

    def test_the_quota_message_says_when_flow_opens_again(self) -> None:
        from datetime import datetime

        stamp = datetime.fromtimestamp(self.blocked_until).astimezone().strftime("%H:%M %d/%m")
        detail = self.service._flow_profiles_all_quota_blocked_detail()
        self.assertTrue(detail.startswith("Tat ca Chrome profile Flow da het quota"), detail)
        self.assertIn(f"khoa toi {stamp}", detail.lower())


class PublishScopedToIndicesTests(_ServiceCase):
    """A6 — ``publish_erp_review`` không có cách nào thu hẹp.

    Hàm duyệt **mọi** artifact và đăng bất cứ chỉ số nào chưa có quyết định,
    chưa có bình luận, chưa nằm trên thẻ. ``reopen_watermark_rejections`` xoá
    entry duyệt, nên chỉ số vừa mở lại thoả cả ba điều kiện. Đó là sự cố thật:
    *"one call meant to replace a single image posted six and took the card
    from 12 attachments to 17."*
    """

    @contextlib.contextmanager
    def _offline_erp(self):
        """Chặn mọi đường ra ERP thật của ``publish_erp_review``.

        Sửa **fixture**, không sửa phép thử: bộ test không được gọi ERP của
        doanh nghiệp. ``_erp_comment`` không nằm trên đường đi của hàm này,
        nên nếu chỉ vá nó thì bài chạy thẳng vào ERP thật và ăn HTTP 401.
        Bốn hàm dưới đây là toàn bộ chỗ hàm chạm mạng và đĩa.
        """
        posted = {"comment": "c-1", "id": "1", "url": "", "name": "anh.png"}
        patched = {}
        with contextlib.ExitStack() as stack:
            for name, value in (
                ("_erp_assert_task_in_project", None),
                ("_erp_task_detail", {}),
                ("_erp_publish_review_comment", posted),
                ("_upsample_artifacts_bytes", {}),
                ("_erp_outgoing_file_bytes", (b"anh-2k", "image/png")),
            ):
                patched[name] = stack.enter_context(
                    patch.object(self.service, name, return_value=value)
                )
            # Đường tải 2K qua giao diện Flow mở trình duyệt thật; trong test offline
            # cần tắt như conftest.py và test_erp_review.py đã làm.
            stack.enter_context(
                patch.dict(os.environ, {"FLOW_UI_UPSCALE_2K_ENABLED": "0"}, clear=False)
            )
            # Trả các mock ra ngoài để bài test đếm được **số ảnh thật sự đã
            # đăng**. Không có con số ấy thì một bản cài đặt bỏ qua ``indices``
            # và đăng cả sáu ảnh vẫn xanh — tức là bài test không canh đúng
            # cái sự cố mà A6 sinh ra để chặn.
            yield patched

    def test_it_accepts_a_list_of_indices(self) -> None:
        self._job(count=3)
        with self._offline_erp() as erp:
            result = self.loop.run_until_complete(
                self.service.publish_erp_review("job-erp", indices=[1])
            )
        self.assertIsInstance(result, dict)
        # Đây mới là câu canh đúng mục A6. "Trả về một dict" thì một bản cài
        # đặt bỏ qua ``indices`` và đăng cả ba ảnh cũng thoả — mà đó chính là
        # sự cố 12 → 17. Xin **một** chỉ số thì phải đăng **đúng một** ảnh.
        self.assertEqual(
            1,
            erp["_erp_publish_review_comment"].call_count,
            "xin đăng một chỉ số mà đăng nhiều hơn một ảnh",
        )

    def test_indices_outside_the_range_are_refused_not_ignored(self) -> None:
        self._job(count=3)
        with self.assertRaises(HTTPException) as caught:
            self.loop.run_until_complete(self.service.publish_erp_review("job-erp", indices=[9]))
        self.assertEqual(400, caught.exception.status_code)

    def test_no_indices_keeps_todays_behaviour(self) -> None:
        # A6.1: đường cũ không được đổi. Gọi trống vẫn là "đăng bù mọi ảnh
        # còn thiếu" — chỉ là bây giờ đó là một lựa chọn, không phải mặc định
        # duy nhất.
        self._job(count=3)
        signature = inspect.signature(FlowWebService.publish_erp_review)
        self.assertIn("indices", signature.parameters)
        self.assertIsNone(signature.parameters["indices"].default)

    def test_a_body_that_will_not_parse_is_refused_not_read_as_publish_all(self) -> None:
        """A6.3 — "không có body" và "body hỏng" phải là hai câu trả lời khác nhau.

        Route helper trước đây nuốt mọi lỗi đọc body và trả ``None``, mà
        ``None`` nghĩa là *đăng bù mọi ảnh còn thiếu*. Nên một request bị cắt
        giữa đường — ``{"indices": [1]`` — không nổ, không báo, mà lặng lẽ
        thành lệnh đăng toàn bộ. Đúng hình dạng sự cố 12 → 17 ảnh mà chính
        mục A6 sinh ra để chặn, chỉ khác đường vào.
        """
        from flow_web.main import _erp_review_indices

        class _Body:
            def __init__(self, raw: bytes) -> None:
                self._raw = raw

            async def body(self) -> bytes:
                return self._raw

        # Body rỗng vẫn giữ nguyên nghĩa cũ: đăng bù tất cả.
        for empty in (b"", b"   ", b"\n"):
            self.assertIsNone(
                self.loop.run_until_complete(_erp_review_indices(_Body(empty))),
                "body rỗng phải giữ nguyên hành vi hôm nay",
            )

        # Body có mà đọc không ra thì trả 400, không đăng gì.
        for broken in (b'{"indices": [1]', b"[1, 2]", b'"mot chuoi"', b"khong-phai-json"):
            with self.assertRaises(HTTPException) as caught:
                self.loop.run_until_complete(_erp_review_indices(_Body(broken)))
            self.assertEqual(400, caught.exception.status_code, broken)

        # Và đường đúng vẫn đi qua như cũ.
        self.assertEqual(
            [1],
            self.loop.run_until_complete(_erp_review_indices(_Body(b'{"indices": [1]}'))),
        )

    def test_the_result_says_what_it_skipped(self) -> None:
        self._job(count=3)
        with self._offline_erp() as erp:
            result = self.loop.run_until_complete(
                self.service.publish_erp_review("job-erp", indices=[0])
            )
        self.assertIn("skipped", result, "phải kể rõ đã bỏ qua bao nhiêu chỉ số (A6.4)")
        # Ba ảnh, xin một: hai ảnh bị bỏ qua, và con số ấy phải nói ra được.
        self.assertEqual(2, result["skipped"], "ba ảnh xin một thì bỏ qua đúng hai")
        self.assertEqual(1, erp["_erp_publish_review_comment"].call_count)


class TelegramConnectorRemovedTests(_ServiceCase):
    """C1 — connector đã gỡ mà kho thông tin xác thực vẫn sống.

    Đường chạy đã bỏ Telegram: ``_automation_graph_payload`` loại module ấy,
    runner có thêm một lớp chặn nữa, và ``_send_telegram_review_pack`` /
    ``run_telegram_approval_sync_loop`` / ``sync_telegram_approvals`` không
    còn ai gọi. Nhưng ``PUT /api/integrations/settings`` vẫn nhận token, vẫn
    ghi vào ``data/state.json``, và snapshot vẫn trả ngược ra cho trình duyệt.
    Một connector đã gỡ mà giữ một kho khoá sống, cách đường gửi đúng một lời
    gọi hàm, là bề mặt không có lý do tồn tại.
    """

    def test_the_request_no_longer_carries_a_telegram_token(self) -> None:
        self.assertNotIn("telegram_bot_token", IntegrationConfigUpdateRequest.model_fields)
        self.assertNotIn("clear_telegram_bot_token", IntegrationConfigUpdateRequest.model_fields)

    def test_a_payload_that_still_sends_one_is_refused_out_loud(self) -> None:
        # C1.3: im lặng bỏ qua làm người gọi tưởng đã lưu.
        with self.assertRaises((HTTPException, TypeError, ValueError)):
            request = IntegrationConfigUpdateRequest.model_validate(
                {"telegram_bot_token": "123:abc", "telegram_chat_id": "-100"}
            )
            self.loop.run_until_complete(self.service.update_integration_config(request))

    def test_the_snapshot_no_longer_advertises_telegram(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "-100"}, clear=False):
            snapshot = self.service._integration_config_snapshot(IntegrationConfig())
        self.assertNotIn("telegram", snapshot)

    def test_the_dead_send_path_is_gone(self) -> None:
        # C1.5: mã chết không được ở lại cạnh một kho khoá.
        for name in (
            "_send_telegram_review_pack",
            "run_telegram_approval_sync_loop",
            "sync_telegram_approvals",
            "_telegram_credentials",
        ):
            with self.subTest(name=name):
                self.assertFalse(hasattr(FlowWebService, name), f"{name} không còn ai gọi")

    def test_creating_a_job_no_longer_defaults_telegram_on(self) -> None:
        # C1.6: telegram_enabled đang mặc định True, nên hôm nay đường duy
        # nhất chặn nó là việc không ai gọi hàm gửi.
        from flow_web.schemas import CreateJobRequest

        self.assertNotIn("telegram_enabled", CreateJobRequest.model_fields)
        self.assertNotIn("telegram_chat_id", CreateJobRequest.model_fields)


class ClearGeminiKeyTellsTheTruthTests(_ServiceCase):
    """C2 — nút "Xoá Gemini key" báo đã xoá trong khi khoá vẫn sống.

    ``_integration_config_snapshot`` dựng khoá lại từ ``GEMINI_API_KEY`` /
    ``GOOGLE_API_KEY`` / ``GOOGLE_GENAI_API_KEY`` ngay sau khi state bị xoá.
    Trên máy có ``.env.local`` — tức là máy thật — bấm nút xong: state trống,
    khoá vẫn sống, app vẫn gọi Gemini được, giao diện vẫn báo đã cấu hình.
    Người bấm tin rằng khoá đã đi; nó không đi đâu cả.
    """

    ENV = {"GEMINI_API_KEY": "khoa-trong-env"}

    def _clear(self) -> Dict[str, Any]:
        request = IntegrationConfigUpdateRequest(clear_gemini_api_key=True)
        return self.loop.run_until_complete(self.service.update_integration_config(request))

    def test_after_an_explicit_clear_the_key_reads_as_gone(self) -> None:
        with patch.dict(os.environ, self.ENV, clear=False):
            snapshot = self._clear()
        self.assertFalse(
            snapshot["gemini"]["configured"],
            "xoá xong mà vẫn báo đã cấu hình thì cái nút đang nói dối",
        )
        self.assertEqual("", snapshot["gemini"]["credentials_source"])

    def test_the_answer_says_the_env_still_holds_one(self) -> None:
        # C2.2: nói đúng bệnh. Người bấm cần biết phải xoá nốt ở đâu.
        with patch.dict(os.environ, self.ENV, clear=False):
            snapshot = self._clear()
        self.assertTrue(
            snapshot["gemini"].get("env_still_set"),
            "phải nói ra rằng máy này còn khoá trong .env.local",
        )

    def test_the_env_fallback_still_works_when_nobody_cleared_anything(self) -> None:
        # Không được đánh đổi: chủ nhân set một lần qua .env.local thì UI vẫn
        # phải báo "Đã lưu" dù data/state.json bị reset. Đó là lý do fallback
        # tồn tại, và nó vẫn đúng — chỉ là không được đè lên một lệnh xoá.
        with patch.dict(os.environ, self.ENV, clear=False):
            snapshot = self.service._integration_config_snapshot(IntegrationConfig())
        self.assertTrue(snapshot["gemini"]["configured"])
        self.assertEqual("env", snapshot["gemini"]["credentials_source"])

    def test_the_key_value_never_reaches_the_browser(self) -> None:
        # C2.4: giữ nguyên hành vi che hiện có, đây không phải chỗ nới.
        with patch.dict(os.environ, self.ENV, clear=False):
            snapshot = self.service._integration_config_snapshot(IntegrationConfig())
        self.assertNotIn("khoa-trong-env", str(snapshot))


if __name__ == "__main__":
    unittest.main()
