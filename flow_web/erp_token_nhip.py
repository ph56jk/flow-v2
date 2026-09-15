"""Nhịp token bot ERP dùng chung giữa các tiến trình.

Chỉ dùng thư viện chuẩn Python (chuẩn bị để script ngoài repo nạp độc lập).
Khoá file ngắn hạn, lưu mốc giờ (giờ tường) vào file JSON chia sẻ.
Hỗ trợ cả POSIX (fcntl.flock) và Windows (msvcrt.locking).
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, List

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

try:
    import msvcrt
    _HAS_MSVCRT = True
except ImportError:
    _HAS_MSVCRT = False

log = logging.getLogger(__name__)


class SharedRateLimiter:
    """Cửa sổ trượt dùng chung giữa các tiến trình qua file JSON và file khoá."""

    def __init__(
        self,
        path: str | Path,
        limit: int,
        window_s: float = 60.0,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.path = Path(path).resolve()
        self.lock_path = Path(str(self.path) + ".lock")
        self.limit = max(1, int(limit))
        self.window_s = float(window_s)
        self.clock = clock
        self.sleep = sleep

        self._warned = False
        self._in_process_history: List[float] = []
        self._in_process_lock = threading.Lock()

    @staticmethod
    @contextmanager
    def _file_lock(lock_path: Path):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o666)
        try:
            if _HAS_FCNTL:
                fcntl.flock(fd, fcntl.LOCK_EX)
            elif _HAS_MSVCRT:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                if _HAS_FCNTL:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                elif _HAS_MSVCRT:
                    try:
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
        finally:
            os.close(fd)

    def _fallback_acquire(self) -> None:
        """Bộ đếm dự phòng trong tiến trình khi hệ thống tệp gặp sự cố."""
        while True:
            with self._in_process_lock:
                now = float(self.clock())
                self._in_process_history = [
                    t
                    for t in self._in_process_history
                    if now - self.window_s < t <= now + 5.0
                ]
                if len(self._in_process_history) < self.limit:
                    self._in_process_history.append(now)
                    return
                oldest = self._in_process_history[0]
                wait_s = oldest + self.window_s - now
            self.sleep(max(0.05, wait_s))

    def acquire(self) -> None:
        """Xin một lượt gửi request, chờ ngoài khoá nếu chạm trần."""
        while True:
            try:
                with self._file_lock(self.lock_path):
                    now = float(self.clock())
                    history: List[float] = []
                    if self.path.exists():
                        try:
                            content = self.path.read_text(encoding="utf-8").strip()
                            if content:
                                parsed = json.loads(content)
                                if isinstance(parsed, list):
                                    history = [float(x) for x in parsed if isinstance(x, (int, float))]
                        except Exception:
                            history = []

                    # Bỏ mốc cũ hơn now - window_s và mốc lớn hơn now + 5.0 (đồng hồ lùi/lệch)
                    history = [t for t in history if now - self.window_s < t <= now + 5.0]

                    if len(history) < self.limit:
                        history.append(now)
                        tmp_path = self.path.with_name(
                            f"{self.path.name}.tmp.{os.getpid()}.{threading.get_ident()}"
                        )
                        try:
                            tmp_path.write_text(json.dumps(history), encoding="utf-8")
                            os.replace(tmp_path, self.path)
                        except Exception:
                            if tmp_path.exists():
                                try:
                                    tmp_path.unlink()
                                except OSError:
                                    pass
                            raise
                        return
                    else:
                        oldest = history[0]
                        wait_s = oldest + self.window_s - now
                # ĐÃ NHẢ KHOÁ FILE TRƯỚC KHI NGỦ
                self.sleep(max(0.05, wait_s))
            except OSError as exc:
                if not self._warned:
                    self._warned = True
                    log.warning(
                        "Lỗi khoá/ghi sổ nhịp token %s, rơi về bộ đếm trong tiến trình: %s",
                        self.path,
                        exc,
                    )
                self._fallback_acquire()
                return
