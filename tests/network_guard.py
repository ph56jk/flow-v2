"""Chốt mạng cho bộ test.

Lượt soát đợt A tìm ra một bài test gọi thẳng vào ERP **production**
(`erp.havigroup.llc:443`) qua một fixture giả lập nhầm chỗ.  Nó không lộ khoá
và không ghi được lên thẻ thật — nó chết ở lần đọc đầu với 401 — nhưng mỗi
lượt chạy bộ test lại bắn một loạt request sai khoá vào ERP của doanh nghiệp,
và ERP nào khoá tài khoản theo số lần sai thì chính bộ test tự khoá tài khoản.
Điều tệ hơn: chuyện ấy chạy im lặng suốt, không ai biết cho tới khi bài đó
tình cờ đỏ vì một lý do khác.

Module này biến "im lặng" thành "đỏ ngay tại chỗ, kèm địa chỉ đã gọi".  Nó
chặn mọi kết nối ra ngoài máy; loopback vẫn mở vì có bài dựng server thật trên
``127.0.0.1``.

Không có biến môi trường nào tắt được chốt này.  Một cái công tắc trong env là
cái sẽ bị bật lên trong CI rồi không ai gỡ.  Bài tích hợp có chủ đích thì bọc
bằng :func:`allow_outbound` — nó bắt phải viết ra lý do, và lý do ấy nằm trong
diff để người soát nhìn thấy.
"""

from __future__ import annotations

import contextlib
import ipaddress
import socket
import threading

__all__ = [
    "OutboundNetworkBlocked",
    "install",
    "allow_outbound",
    "is_installed",
]


class OutboundNetworkBlocked(RuntimeError):
    """Bộ test vừa cố gọi ra ngoài máy."""


#: Địa chỉ loopback được đi qua.  Bài dựng server thật trên ``127.0.0.1`` là
#: chuyện bình thường và không chạm dịch vụ của ai.
_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})

#: Cờ mở tạm, riêng cho từng luồng.  Riêng-từng-luồng để một bài tích hợp mở
#: cửa cho mình không vô tình mở luôn cho bài đang chạy song song.
_local = threading.local()

_installed = False
_real = {}


def _thread_is_allowed() -> bool:
    return bool(getattr(_local, "allowed", 0))


def _is_loopback(host) -> bool:
    if host is None:
        return True
    if not isinstance(host, (str, bytes)):
        return False
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return False
    host = host.strip().strip("[]").lower()
    if host in _LOOPBACK_NAMES or host in {"", "0.0.0.0", "::"}:
        return True
    # Phần số phải so bằng ĐỊA CHỈ, không so tiền tố chuỗi.  `startswith("127.")`
    # cho `127.0.0.1.example.com` đi lọt — đó là một tên máy ngoài, do người
    # khác cầm DNS, chỉ tình cờ bắt đầu bằng mấy ký tự ấy.
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        # Không phải địa chỉ IP thì là một cái tên, và tên nào không nằm trong
        # _LOOPBACK_NAMES đều phải đi hỏi DNS — tức là ra khỏi máy.
        #
        # Kèm theo: `2130706433` và `0177.0.0.1` — 127.0.0.1 viết kiểu khác —
        # rơi vào đây và bị TỪ CHỐI.  Cố ý.  Chặn nhầm một cửa loopback thì bài
        # đỏ ngay; cho lọt nhầm một địa chỉ ngoài thì không ai thấy gì.
        return False


def _refuse(where: str, host, port) -> None:
    target = f"{host}:{port}" if port is not None else str(host)
    raise OutboundNetworkBlocked(
        f"Bộ test vừa gọi ra ngoài máy: {target} (qua {where}).\n"
        "Test không được chạm dịch vụ thật — hãy giả lập lớp HTTP của bài này.\n"
        "Nếu đây là bài tích hợp có chủ đích, bọc nó bằng\n"
        '    with tests.network_guard.allow_outbound("lý do"):\n'
        "và nói rõ lý do trong diff."
    )


def _address_host_port(address):
    """Tách (host, port) khỏi một địa chỉ socket bất kỳ.

    Trả về ``None`` khi địa chỉ không phải kiểu IP — AF_UNIX (đường dẫn str),
    AF_BLUETOOTH… — vì những cái ấy không ra khỏi máy.
    """
    if isinstance(address, (str, bytes, int)):
        return None
    if isinstance(address, tuple) and address:
        host = address[0]
        port = address[1] if len(address) > 1 else None
        return host, port
    return None


def install() -> None:
    """Bật chốt.  Gọi nhiều lần cũng chỉ bật một lần."""
    global _installed
    if _installed:
        return

    _real["getaddrinfo"] = socket.getaddrinfo
    _real["gethostbyname"] = socket.gethostbyname
    _real["connect"] = socket.socket.connect
    _real["connect_ex"] = socket.socket.connect_ex
    _real["sendto"] = socket.socket.sendto
    # Windows không có socket.sendmsg (chỉ Linux/macOS): thiếu thì bỏ chốt ấy, các chốt khác vẫn bật.
    _real["sendmsg"] = getattr(socket.socket, "sendmsg", None)

    def guarded_getaddrinfo(host, port, *args, **kwargs):
        # Chặn ngay ở khâu phân giải tên: đây là chỗ bắt được cả trường hợp
        # kết nối chưa kịp mở mà đã lộ ra mình định gọi đi đâu.
        if not _thread_is_allowed() and not _is_loopback(host):
            _refuse("getaddrinfo", host, port)
        return _real["getaddrinfo"](host, port, *args, **kwargs)

    def guarded_gethostbyname(hostname):
        if not _thread_is_allowed() and not _is_loopback(hostname):
            _refuse("gethostbyname", hostname, None)
        return _real["gethostbyname"](hostname)

    def guarded_connect(self, address):
        # Còn đây là chỗ bắt trường hợp quay thẳng số IP, không qua DNS.
        parts = _address_host_port(address)
        if parts is not None and not _thread_is_allowed() and not _is_loopback(parts[0]):
            _refuse("socket.connect", parts[0], parts[1])
        return _real["connect"](self, address)

    def guarded_connect_ex(self, address):
        parts = _address_host_port(address)
        if parts is not None and not _thread_is_allowed() and not _is_loopback(parts[0]):
            _refuse("socket.connect_ex", parts[0], parts[1])
        return _real["connect_ex"](self, address)

    def guarded_sendto(self, *args):
        # UDP đi thẳng, không qua connect — hai chốt trên không thấy nó.  Địa
        # chỉ là tham số cuối: sendto(data, address) hoặc
        # sendto(data, flags, address).
        if args:
            parts = _address_host_port(args[-1])
            if parts is not None and not _thread_is_allowed() and not _is_loopback(parts[0]):
                _refuse("socket.sendto", parts[0], parts[1])
        return _real["sendto"](self, *args)

    def guarded_sendmsg(self, *args, **kwargs):
        # sendmsg(buffers[, ancdata[, flags[, address]]]) — địa chỉ là tham số
        # thứ tư, và vắng mặt khi socket đã connect (lúc ấy connect đã canh).
        address = args[3] if len(args) > 3 else kwargs.get("address")
        parts = _address_host_port(address)
        if parts is not None and not _thread_is_allowed() and not _is_loopback(parts[0]):
            _refuse("socket.sendmsg", parts[0], parts[1])
        return _real["sendmsg"](self, *args, **kwargs)

    socket.getaddrinfo = guarded_getaddrinfo
    socket.gethostbyname = guarded_gethostbyname
    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.socket.sendto = guarded_sendto
    if _real["sendmsg"] is not None:
        socket.socket.sendmsg = guarded_sendmsg
    _installed = True


def is_installed() -> bool:
    return _installed


@contextlib.contextmanager
def allow_outbound(reason: str):
    """Mở cửa cho đúng luồng này, trong đúng khối ``with`` này.

    ``reason`` là bắt buộc và phải nói được cho người soát biết vì sao một bài
    test cần chạm mạng thật.  Không nhận chuỗi rỗng.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError(
            "allow_outbound cần một lý do viết ra được — người soát diff phải "
            "đọc được vì sao bài này cần mạng thật."
        )
    previous = getattr(_local, "allowed", 0)
    _local.allowed = previous + 1
    try:
        yield
    finally:
        _local.allowed = previous
