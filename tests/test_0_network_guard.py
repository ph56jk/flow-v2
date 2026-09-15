"""Bật chốt mạng, và chứng minh là nó chặn thật.

Tên file bắt đầu bằng ``0`` là cố ý.  ``unittest discover`` nạp module theo
``sorted(os.listdir(...))``, nên file này được **nạp trước mọi file test khác**
— chốt đã đứng sẵn trước khi bài đầu tiên chạy, kể cả code ở thân module của
các bài khác.  Đổi tên file này thành cái gì đó sắp sau ``test_a…`` là bỏ chốt
đi mà không ai nhận ra.
"""

from __future__ import annotations

import os
import socket
import threading
import unittest
from unittest import mock

try:  # chạy từ gốc repo: `python -m unittest discover -s tests`
    from tests import network_guard
except ImportError:  # chạy với `tests/` là top-level dir
    import network_guard  # type: ignore[no-redef]

# Bật ngay lúc nạp module, không đợi setUpModule: setUp* chỉ chạy khi bài của
# module này chạy, còn việc nạp thì luôn xảy ra trước tất cả.
network_guard.install()


class TheGuardIsUpTests(unittest.TestCase):
    def test_it_is_installed_before_any_test_runs(self):
        self.assertTrue(network_guard.is_installed())

    def test_this_file_is_still_the_first_one_discovery_loads(self):
        # Chốt chỉ đứng trước tất cả nếu file này còn sắp đầu. Đổi tên nó là
        # bỏ chốt đi một cách im lặng — bài này làm việc ấy kêu thành tiếng.
        here = os.path.dirname(os.path.abspath(__file__))
        modules = sorted(
            name
            for name in os.listdir(here)
            if name.startswith("test_") and name.endswith(".py")
        )
        self.assertEqual(modules[0], os.path.basename(__file__))

    def test_installing_twice_does_not_stack_wrappers(self):
        # Nếu install() bọc chồng lên chính nó, mỗi lần gọi lại thêm một lớp
        # và thông báo lỗi sẽ nhân lên. Gọi lại phải là không-làm-gì.
        before = socket.getaddrinfo
        network_guard.install()
        self.assertIs(socket.getaddrinfo, before)


class WhatItRefusesTests(unittest.TestCase):
    def test_resolving_a_real_service_is_refused(self):
        with self.assertRaises(network_guard.OutboundNetworkBlocked) as caught:
            socket.getaddrinfo("erp.havigroup.llc", 443)
        message = str(caught.exception)
        # Câu lỗi phải nói ra ĐỊA CHỈ. Một câu "network blocked" trơn bắt người
        # đọc phải đi tìm xem bài nào gọi đi đâu — đúng công việc mà chốt này
        # tồn tại để khỏi phải làm.
        self.assertIn("erp.havigroup.llc:443", message)
        self.assertIn("allow_outbound", message)

    def test_looking_up_a_name_the_old_way_is_refused_too(self):
        with self.assertRaises(network_guard.OutboundNetworkBlocked):
            socket.gethostbyname("erp.havigroup.llc")

    def test_dialling_a_public_ip_directly_is_refused(self):
        # Bỏ qua DNS, quay thẳng số IP. Chốt chỉ đặt ở getaddrinfo thì lọt.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(sock.close)
        with self.assertRaises(network_guard.OutboundNetworkBlocked) as caught:
            sock.connect(("203.0.113.7", 443))
        self.assertIn("203.0.113.7:443", str(caught.exception))

    def test_connect_ex_is_refused_as_well(self):
        # connect_ex trả errno thay vì ném — một bài dùng nó sẽ đi qua chốt
        # chặn-bằng-ngoại-lệ nếu ta quên bọc.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(sock.close)
        with self.assertRaises(network_guard.OutboundNetworkBlocked):
            sock.connect_ex(("203.0.113.7", 443))

    def test_a_name_that_merely_begins_with_127_is_still_refused(self):
        # "127.0.0.1.example.com" bắt đầu bằng "127." nhưng là một TÊN MÁY
        # ngoài, do người khác cầm DNS. So tiền tố chuỗi thì nó đi lọt khâu
        # phân giải tên — chốt vẫn chặn ở connect vì IP trả về là IP công
        # cộng, nhưng câu truy vấn DNS thì đã rời khỏi máy rồi.
        with self.assertRaises(network_guard.OutboundNetworkBlocked) as caught:
            socket.getaddrinfo("127.0.0.1.example.com", 443)
        self.assertIn("127.0.0.1.example.com:443", str(caught.exception))

    def test_a_name_that_merely_begins_with_a_loopback_ip_is_refused_via_gethostbyname(self):
        with self.assertRaises(network_guard.OutboundNetworkBlocked):
            socket.gethostbyname("127.0.0.1.evil.example")

    def test_udp_sendto_a_public_ip_is_refused(self):
        # UDP không cần connect, nên một chốt chỉ bọc connect/connect_ex là
        # bỏ ngỏ đường này.  Cần IP viết cứng mới đi được (phân giải tên vẫn
        # bị chặn), nên là lỗ hẹp — nhưng lỗ hẹp vẫn là lỗ.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(sock.close)
        with self.assertRaises(network_guard.OutboundNetworkBlocked) as caught:
            sock.sendto(b"\x00", ("203.0.113.7", 53))
        self.assertIn("203.0.113.7:53", str(caught.exception))

    @unittest.skipUnless(hasattr(socket.socket, "sendmsg"), "socket.sendmsg không có trên Windows")
    def test_udp_sendmsg_a_public_ip_is_refused(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(sock.close)
        with self.assertRaises(network_guard.OutboundNetworkBlocked):
            sock.sendmsg([b"\x00"], [], 0, ("203.0.113.7", 53))


    def test_cach_viet_so_khac_cua_127_0_0_1_bi_tu_choi_va_do_la_chieu_dung(self):
        # `2130706433` và `0177.0.0.1` là 127.0.0.1 viết kiểu khác, hợp lệ với
        # nhiều thư viện.  Chốt này TỪ CHỐI chúng, vì `ipaddress.ip_address`
        # không nhận dạng ấy.  Ghim lại như một quyết định, không phải một chỗ
        # sót: chặn nhầm một cửa loopback thì bài đỏ và người đọc thấy ngay;
        # cho lọt nhầm một địa chỉ ngoài thì không ai thấy gì.  Ai cần mở phải
        # mở có chủ ý, và bài này sẽ đỏ để nhắc.
        for host in ("2130706433", "0177.0.0.1", "0x7f.0.0.1"):
            with self.subTest(host=host):
                self.assertFalse(network_guard._is_loopback(host))


class WhatItStillLetsThroughTests(unittest.TestCase):
    def test_a_real_server_on_loopback_still_works(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(client.close)
        client.settimeout(2.0)
        client.connect(("127.0.0.1", port))
        conn, _ = server.accept()
        self.addCleanup(conn.close)
        conn.sendall(b"xin chao")
        self.assertEqual(client.recv(8), b"xin chao")

    def test_the_name_localhost_still_resolves(self):
        self.assertTrue(socket.getaddrinfo("localhost", 80))

    def test_every_loopback_address_still_counts_as_loopback(self):
        # Sửa chỗ so tiền tố mà chặn nhầm cả 127.0.0.0/8 thì hỏng bài dựng
        # server thật; cả dải này là loopback, không riêng 127.0.0.1.
        for host in ("127.0.0.1", "127.0.0.53", "127.255.255.254", "::1", "[::1]"):
            with self.subTest(host=host):
                self.assertTrue(network_guard._is_loopback(host))

    def test_udp_sendto_loopback_still_works(self):
        # Chặn UDP mà chặn luôn loopback thì hỏng bài nào dựng server UDP thật.
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(server.close)
        server.bind(("127.0.0.1", 0))
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(client.close)
        client.sendto(b"xin chao", server.getsockname())
        data, _ = server.recvfrom(64)
        self.assertEqual(data, b"xin chao")

    def test_unix_socket_pairs_are_untouched(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        left.sendall(b"ok")
        self.assertEqual(right.recv(2), b"ok")


class TheDeliberateDoorTests(unittest.TestCase):
    """``allow_outbound`` — cho bài tích hợp có chủ đích, có lý do viết ra."""

    def test_inside_the_door_the_call_reaches_the_real_resolver(self):
        # Không gọi mạng thật: thay hàm thật bằng một cái bẫy rồi xem nó có
        # được gọi không. Đó chính là điều cần chứng minh — chốt bước sang bên.
        sentinel = mock.Mock(return_value=[("af", "kind", 0, "", ("1.2.3.4", 443))])
        with mock.patch.dict(network_guard._real, {"getaddrinfo": sentinel}):
            with network_guard.allow_outbound("bài tích hợp ERP, chạy tay"):
                result = socket.getaddrinfo("erp.havigroup.llc", 443)
        self.assertEqual(result[0][4], ("1.2.3.4", 443))
        sentinel.assert_called_once()

    def test_the_door_shuts_again_afterwards(self):
        with network_guard.allow_outbound("mở một lượt rồi thôi"):
            pass
        with self.assertRaises(network_guard.OutboundNetworkBlocked):
            socket.getaddrinfo("erp.havigroup.llc", 443)

    def test_the_door_shuts_even_when_the_body_raises(self):
        with self.assertRaises(ZeroDivisionError):
            with network_guard.allow_outbound("thân khối nổ giữa chừng"):
                1 / 0
        with self.assertRaises(network_guard.OutboundNetworkBlocked):
            socket.getaddrinfo("erp.havigroup.llc", 443)

    def test_a_reason_is_not_optional(self):
        for empty in ("", "   "):
            with self.subTest(reason=empty):
                with self.assertRaises(ValueError):
                    with network_guard.allow_outbound(empty):
                        pass

    def test_one_thread_opening_the_door_does_not_open_it_for_another(self):
        # Bộ test chạy song song thì một bài tích hợp mở cửa cho mình không
        # được vô tình mở cửa cho bài bên cạnh.
        seen = {}
        started = threading.Event()
        may_finish = threading.Event()

        def opener():
            with network_guard.allow_outbound("giữ cửa mở trong lúc đo"):
                started.set()
                may_finish.wait(5.0)

        def bystander():
            started.wait(5.0)
            try:
                socket.getaddrinfo("erp.havigroup.llc", 443)
            except network_guard.OutboundNetworkBlocked:
                seen["blocked"] = True
            else:
                seen["blocked"] = False
            may_finish.set()

        threads = [threading.Thread(target=opener), threading.Thread(target=bystander)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10.0)
        self.assertTrue(seen.get("blocked"), "luồng bên cạnh đi lọt qua chốt")


if __name__ == "__main__":
    unittest.main()
