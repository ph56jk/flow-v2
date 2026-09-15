"""``scripts/run_agent_bot.py`` phải dựng bot đủ mọi loại việc.

Script này là đường chạy bot ở một máy **không** có Flow — đúng cảnh mà bản
Listing sinh ra để phục vụ. Nếu nó dựng bot mà quên nối cầu Listing thì bot vẫn
sống, vẫn quét, vẫn dọn phiếu, và mọi thẻ ``action_1: listing`` nhận đúng một
câu trả lời: "chưa cấu hình ERP_LISTING_API_URL" — kể cả khi biến đó đã được
đặt đàng hoàng trong ``.env.local``. Không có gì đỏ, không có gì kêu.

Cùng một kiểu hỏng ấy lặp lại với bốn đường ghi thêm sau này — luật cột, sửa
thẻ bằng lời nói, đánh số SKU, và quyển sổ tài khoản. Bản trong app
(:meth:`FlowWebService.agent_bot`) nối đủ cả; bản chạy rời quên thì thẻ đứng
nguyên một cột mãi mãi và mọi câu "sửa hộ tôi" đều bị từ chối, trong khi log
vẫn chạy đều. Nên mỗi hook có một test riêng ở đây.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_script():
    spec = importlib.util.spec_from_file_location(
        "run_agent_bot_script", ROOT / "scripts" / "run_agent_bot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


class BotGia:
    async def run_once(self) -> Dict[str, Any]:
        return {"scanned": 0}


class DungBotDuHaiLoaiViec(unittest.TestCase):
    def _chay(self, env: Dict[str, str]) -> Dict[str, Any]:
        ghi_lai: Dict[str, Any] = {}

        def build(config, **kwargs):
            ghi_lai.update(kwargs)
            ghi_lai["config"] = config
            return BotGia()

        moi_truong = {
            "ERP_AGENT_TOKEN": "token-gia-cho-test",
            "ERP_API_URL": "https://erp.invalid/api/method/hvg_workspace.api.graphql",
            "ERP_LISTING_API_URL": "",
            "ERP_LISTING_MACHINE": "",
            "ERP_LISTING_MACHINES": "",
            **env,
        }
        with mock.patch.dict(os.environ, moi_truong, clear=False), \
                mock.patch.object(script, "build_agent_bot", build), \
                mock.patch.object(script, "load_local_env", lambda: None):
            ma = asyncio.run(script.main(["--once", "--dry-run"]))
        self.assertEqual(ma, 0)
        return ghi_lai

    def test_da_dat_erp_listing_api_url_thi_cau_listing_duoc_noi(self):
        ghi_lai = self._chay({"ERP_LISTING_API_URL": "http://127.0.0.1:9100",
                              "ERP_LISTING_MACHINE": "may-01"})
        self.assertIsNotNone(
            ghi_lai.get("listing_hook"),
            "script dựng bot mà không truyền listing_hook: mọi thẻ listing sẽ "
            "nhận 'chưa cấu hình ERP_LISTING_API_URL' dù biến đã được đặt")

    def test_chua_dat_thi_hook_van_la_none_chu_khong_dung_cau_hong(self):
        # Chưa dựng bản Listing thì im lặng nhận diện rồi để yên là đúng — nối
        # một cầu trỏ vào hư không còn tệ hơn: mỗi thẻ thành một lần chờ timeout.
        ghi_lai = self._chay({})
        self.assertIsNone(ghi_lai.get("listing_hook"))

    def test_khong_co_flow_web_url_thi_van_khong_tu_chay_flow(self):
        # Ranh giới cũ, giữ nguyên: một máy không có Flow thì phần tạo ảnh phải
        # tắt hẳn chứ không được âm thầm không làm gì.
        ghi_lai = self._chay({"ERP_LISTING_API_URL": "http://127.0.0.1:9100"})
        self.assertIsNone(ghi_lai.get("autorun_hook"))
        self.assertFalse(ghi_lai["config"].autorun)


class NoiDuBaDuongGhiQuaHTTP(unittest.TestCase):
    """Có ``--flow-web-url`` thì mọi đường ghi phải được nối, không chỉ tạo ảnh."""

    def setUp(self) -> None:
        self.goi: list[tuple[str, Any]] = []
        # Chặn cứng mọi request thật. Hook được gọi *sau* khi ``main`` trả về,
        # nên một bản vá đặt sai chỗ sẽ lặng lẽ bắn vào app đang chạy trên máy
        # người viết test và vẫn xanh. Ở đây thì nó đỏ.
        cam = mock.patch.object(
            script, "urlopen",
            mock.Mock(side_effect=AssertionError("test không được gọi mạng thật")))
        cam.start()
        self.addCleanup(cam.stop)

    def _gia_lap(self, base, path, payload, *, timeout_s, what):
        self.goi.append((f"{base}{path}", payload))
        if path.endswith("/account/book"):
            return {"entries": {"acc32": {"shop": "Havi Home", "machine": "etsy-vn32"}}}
        return {"ok": True}

    def _chay(self, argv: list[str], sau=None, goi=None) -> Dict[str, Any]:
        """Chạy script; ``sau`` được gọi **bên trong** bản vá.

        Ba hook đều tra ``_call_flow_web`` ở thời điểm gọi, không phải lúc
        dựng — nên gọi chúng sau khi ``with`` đóng lại là gọi vào hàm thật.
        """
        ghi_lai: Dict[str, Any] = {}

        def build(config, **kwargs):
            ghi_lai.update(kwargs)
            ghi_lai["config"] = config
            return BotGia()

        moi_truong = {
            "ERP_AGENT_TOKEN": "token-gia-cho-test",
            "ERP_API_URL": "https://erp.invalid/api/method/hvg_workspace.api.graphql",
            "ERP_LISTING_API_URL": "",
            "ERP_LISTING_MACHINE": "",
            "ERP_LISTING_MACHINES": "",
        }
        with mock.patch.dict(os.environ, moi_truong, clear=False), \
                mock.patch.object(script, "build_agent_bot", build), \
                mock.patch.object(script, "_call_flow_web", goi or self._gia_lap), \
                mock.patch.object(script, "load_local_env", lambda: None):
            ma = asyncio.run(script.main(argv))
            if sau is not None:
                sau(ghi_lai)
        self.assertEqual(ma, 0)
        return ghi_lai

    def _voi_url(self, sau=None) -> Dict[str, Any]:
        return self._chay(
            ["--once", "--dry-run", "--flow-web-url", "http://127.0.0.1:8000"], sau=sau)

    def test_luat_cot_duoc_noi_chu_khong_de_the_dung_mot_cho_mai_mai(self) -> None:
        def sau(ghi_lai):
            hook = ghi_lai.get("pipeline_hook")
            self.assertIsNotNone(hook, "thiếu pipeline_hook: bot không đẩy được thẻ sang cột kế")
            asyncio.run(hook("TASK-1"))

        self._voi_url(sau)
        self.assertIn(
            ("http://127.0.0.1:8000/api/erp/pipeline/advance", {"task_id": "TASK-1"}), self.goi)

    def test_sua_the_bang_loi_noi_duoc_noi(self) -> None:
        def sau(ghi_lai):
            hook = ghi_lai.get("edit_hook")
            self.assertIsNotNone(hook, "thiếu edit_hook: mọi câu 'sửa hộ tôi' đều bị từ chối")
            # **Đồng bộ**: ``chat_pass`` gọi nó từ trong ``asyncio.to_thread``,
            # ở đó không có vòng lặp sự kiện nào để ``await``. Trả về một
            # coroutine là hỏng, và hỏng theo kiểu chỉ lộ ra khi chạy thật.
            self.assertEqual({"ok": True}, hook("TASK-1", (("acc", "acc32"),)))

        self._voi_url(sau)
        self.assertIn(
            ("http://127.0.0.1:8000/api/erp/task/meta-edit",
             {"task_id": "TASK-1", "edits": [["acc", "acc32"]]}),
            self.goi)

    def test_danh_so_sku_duoc_noi(self) -> None:
        def sau(ghi_lai):
            hook = ghi_lai.get("sku_hook")
            self.assertIsNotNone(
                hook, "thiếu sku_hook: mọi câu 'điền sku đi' đều nhận lời từ chối")
            # **Đồng bộ** như ``edit_hook``, cùng lý do: ``chat_pass`` gọi nó
            # từ trong ``asyncio.to_thread``.
            self.assertEqual({"ok": True}, hook("TASK-1", False))

        self._voi_url(sau)
        self.assertIn(
            ("http://127.0.0.1:8000/api/erp/sku/sync",
             {"task_id": "TASK-1", "dry_run": False, "renumber": False}),
            self.goi)

    def test_co_danh_so_lai_thi_co_ghi_de_di_theo(self) -> None:
        # Cờ này là khác biệt giữa "điền chỗ trống" và "xoá mã đã in lên tem".
        # Đánh rơi nó trên đường HTTP thì lệnh đánh số lại im lặng không làm gì.
        def sau(ghi_lai):
            ghi_lai["sku_hook"]("TASK-1", True)

        self._voi_url(sau)
        self.assertIn(
            ("http://127.0.0.1:8000/api/erp/sku/sync",
             {"task_id": "TASK-1", "dry_run": False, "renumber": True}),
            self.goi)

    def test_danh_so_khong_bao_gio_chay_kho_qua_duong_nay(self) -> None:
        # ``--dry-run`` của script là chạy khô *lượt quét*; tới đây thì bot đã
        # quyết định ghi và đã hứa với người ta. Gửi ``dry_run: True`` là trả
        # về một bản kế hoạch rồi bảo "xong rồi" trong khi thẻ không đổi gì.
        def sau(ghi_lai):
            ghi_lai["sku_hook"]("TASK-1", False)

        self._voi_url(sau)
        payloads = [payload for url, payload in self.goi if url.endswith("/api/erp/sku/sync")]
        self.assertEqual([False], [payload["dry_run"] for payload in payloads])

    def test_tao_anh_van_di_qua_dung_duong_cu(self) -> None:
        def sau(ghi_lai):
            asyncio.run(ghi_lai["autorun_hook"]("TASK-1"))

        self._voi_url(sau)
        self.assertIn(
            ("http://127.0.0.1:8000/api/erp/idea-batch", {"task_id": "TASK-1"}), self.goi)

    def test_so_tai_khoan_duoc_xin_ve_tu_app(self) -> None:
        # Máy chạy bot không có file sổ và không có sheet, nhưng vẫn phải trả
        # lời đúng câu "thẻ này lên shop nào".
        book = self._voi_url().get("book")
        self.assertIsNotNone(book)
        self.assertEqual("Havi Home", book.lookup("acc32").shop)

    def test_so_hong_thi_bot_van_chay_chu_khong_chet(self) -> None:
        def hong(base, path, payload, *, timeout_s, what):
            raise script.AgentBotError("app tắt")

        with self.assertLogs("agent_bot", level="WARNING"):
            ghi_lai = self._chay(
                ["--once", "--dry-run", "--flow-web-url", "http://127.0.0.1:8000"], goi=hong)
        self.assertIsNone(ghi_lai.get("book"))
        self.assertIsNotNone(ghi_lai.get("pipeline_hook"), "sổ hỏng không được gỡ hook nào")

    def test_khong_co_url_thi_khong_noi_duong_ghi_nao_tro_vao_hu_khong(self) -> None:
        ghi_lai = self._chay(["--once", "--dry-run"])
        self.assertIsNone(ghi_lai.get("pipeline_hook"))
        self.assertIsNone(ghi_lai.get("edit_hook"))
        self.assertIsNone(ghi_lai.get("sku_hook"))
        self.assertIsNone(ghi_lai.get("book"))
        self.assertEqual([], self.goi)

    def test_co_state_rieng_thi_bot_khong_de_len_file_nho_mac_dinh(self) -> None:
        # File nhớ mặc định bị **ghi đè** chứ không gộp: chạy thử một bot khác
        # trên cùng máy mà dùng chung file là xoá sạch phạm vi dự án của bot
        # đang chạy thật.
        ghi_lai = self._chay(["--once", "--dry-run", "--state", "/tmp/bot-thu.json"])
        self.assertEqual(Path("/tmp/bot-thu.json"), ghi_lai.get("state_path"))

    def test_khong_khai_state_thi_giu_nguyen_file_mac_dinh(self) -> None:
        self.assertIsNone(self._chay(["--once", "--dry-run"]).get("state_path"))

    def test_moi_duong_script_goi_deu_la_route_that_cua_app(self) -> None:
        """Năm địa chỉ script gõ vào phải tồn tại bên app.

        Không có test này thì một đường ghi mới trông như đã nối xong: hook có
        mặt, log không kêu, và mỗi lần bot gọi là một cái 404 lặng lẽ nằm trong
        câu trả lời trên thẻ. Gõ sai một chữ trong đường dẫn cũng đủ.
        """
        from flow_web.main import app

        co_that = {getattr(route, "path", "") for route in app.routes}
        def sau(ghi_lai):
            asyncio.run(ghi_lai["autorun_hook"]("TASK-1"))
            asyncio.run(ghi_lai["pipeline_hook"]("TASK-1"))
            ghi_lai["edit_hook"]("TASK-1", (("acc", "acc32"),))
            ghi_lai["sku_hook"]("TASK-1", False)

        self._voi_url(sau)
        da_goi = {url.split("http://127.0.0.1:8000", 1)[-1] for url, _ in self.goi}
        self.assertEqual(
            {
                "/api/erp/account/book",
                "/api/erp/idea-batch",
                "/api/erp/pipeline/advance",
                "/api/erp/sku/sync",
                "/api/erp/task/meta-edit",
            },
            da_goi,
        )
        self.assertEqual(set(), da_goi - co_that, "script gọi vào đường app không có")


class NoiCauHoiLaiListing(unittest.TestCase):
    """PRD list tự động lên Etsy, T2: bản chạy rời phải nối cả đường hỏi lại.

    Không có ``listing_confirm_hook`` thì ``AgentBot._listing_confirm`` trả
    ``None`` ngay: thẻ giao đi rồi không bao giờ được xác nhận, và luật cột
    không bao giờ mở cổng sang *Hoàn thành*. Bản trong app
    (``service.py: agent_bot()``) nối; bản rời quên.
    """

    def _chay(self, env: Dict[str, str]) -> Dict[str, Any]:
        ghi_lai: Dict[str, Any] = {}

        def build(config, **kwargs):
            ghi_lai.update(kwargs)
            ghi_lai["config"] = config
            return BotGia()

        moi_truong = {
            "ERP_AGENT_TOKEN": "token-gia-cho-test",
            "ERP_API_URL": "https://erp.invalid/api/method/hvg_workspace.api.graphql",
            "ERP_LISTING_API_URL": "",
            "ERP_LISTING_MACHINE": "",
            "ERP_LISTING_MACHINES": "",
            **env,
        }
        with mock.patch.dict(os.environ, moi_truong, clear=False), \
                mock.patch.object(script, "build_agent_bot", build), \
                mock.patch.object(script, "load_local_env", lambda: None):
            ma = asyncio.run(script.main(["--once", "--dry-run"]))
        self.assertEqual(ma, 0)
        return ghi_lai

    def test_da_dat_url_thi_cau_hoi_lai_cung_duoc_noi(self):
        ghi_lai = self._chay({"ERP_LISTING_API_URL": "http://127.0.0.1:9100",
                              "ERP_LISTING_MACHINE": "may-01"})
        self.assertIsNotNone(
            ghi_lai.get("listing_confirm_hook"),
            "script dựng bot không truyền listing_confirm_hook: thẻ giao đi rồi không "
            "bao giờ được hỏi lại, sổ listed mãi confirmed=False, thẻ không bao giờ "
            "sang Hoàn thành — dù ERP_LISTING_API_URL đã đặt")

    def test_chua_dat_thi_cau_hoi_lai_la_none(self):
        # Chốt chặn: không có bản Listing thì không nối cầu trỏ vào hư không.
        ghi_lai = self._chay({})
        self.assertIsNone(ghi_lai.get("listing_confirm_hook"))


if __name__ == "__main__":
    unittest.main()
