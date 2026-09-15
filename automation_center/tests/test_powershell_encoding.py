"""Script PowerShell có tiếng Việt phải mở đầu bằng BOM UTF-8.

Windows PowerShell 5.1 — bản duy nhất có sẵn trên máy trung tâm — đọc file
``.ps1`` **không BOM** theo code page ANSI của máy (Windows-1252), chứ không
phải UTF-8.  Mỗi ký tự tiếng Việt khi ấy vỡ thành hai ba byte lạ, và một số byte
rơi trúng những ký tự mà chính PowerShell coi là **dấu nháy mở/đóng chuỗi**:
``‘`` U+2018, ``’`` U+2019, ``“`` U+201C, ``”`` U+201D…  Một dấu nháy giả nằm
trong chuỗi là đủ để đóng chuỗi sớm, và phần còn lại của dòng biến thành mã.

Đây không phải chuyện hiển thị.  Ngày 2026-08-26, chạy
``install-windows-services.ps1`` qua ssh trên máy trung tâm thì ba dòng
``Write-Host '  Start-ScheduledTask …'`` cuối file in ra nguyên văn cả chữ
``Write-Host`` — parser đã trượt khỏi chuỗi.  Script vẫn "chạy xong", vẫn trả về
mã 0, chỉ là làm sai.  Không có gì đỏ để mà nhìn.

Chạy:  python3 automation_center/tests/test_powershell_encoding.py
"""

from __future__ import annotations

import unittest
from pathlib import Path

CENTER = Path(__file__).resolve().parent.parent

BOM = b"\xef\xbb\xbf"

# Windows-1252 để trống 5 byte này; .NET ánh xạ chúng về đúng code point cùng số
# thay vì báo lỗi, nên phải mô phỏng lại — codec cp1252 của Python thì ném lỗi.
KHONG_DINH_NGHIA = {0x81, 0x8D, 0x8F, 0x90, 0x9D}

# Bộ ký tự PowerShell chấp nhận làm dấu nháy, ngoài ' và " thường.
NHAY_THONG_MINH = {0x2018, 0x2019, 0x201A, 0x201B, 0x201C, 0x201D, 0x201E}


def cac_script() -> list[Path]:
    return sorted(CENTER.rglob("*.ps1"))


def co_ky_tu_ngoai_ascii(raw: bytes) -> bool:
    return any(byte > 0x7F for byte in raw)


def giai_kieu_windows_1252(raw: bytes) -> str:
    ky_tu = []
    for byte in raw:
        if byte in KHONG_DINH_NGHIA:
            ky_tu.append(chr(byte))
        else:
            ky_tu.append(bytes([byte]).decode("cp1252"))
    return "".join(ky_tu)


class MaHoaScriptPowerShell(unittest.TestCase):
    def test_script_co_tieng_viet_deu_co_bom(self):
        script = cac_script()
        self.assertTrue(script, "không tìm thấy file .ps1 nào")
        for path in script:
            raw = path.read_bytes()
            if not co_ky_tu_ngoai_ascii(raw):
                continue  # Thuần ASCII thì đọc kiểu nào cũng ra một kết quả.
            with self.subTest(script=path.relative_to(CENTER).as_posix()):
                self.assertTrue(
                    raw.startswith(BOM),
                    f"{path.relative_to(CENTER)} có ký tự ngoài ASCII nhưng "
                    "không có BOM UTF-8: PowerShell 5.1 sẽ đọc nó theo "
                    "Windows-1252 và chuỗi tiếng Việt có thể bị đóng sớm")

    def test_luat_bom_that_su_chan_duoc_nhay_gia(self):
        # Neo lại *lý do*: nếu ngày nào tiếng Việt không còn sinh ra dấu nháy
        # giả nữa thì luật trên thành một luật vô cớ.  Test này đỏ trước để nói.
        co_nguy_co = []
        for path in cac_script():
            raw = path.read_bytes()
            if not co_ky_tu_ngoai_ascii(raw):
                continue
            than = raw[len(BOM):] if raw.startswith(BOM) else raw
            if any(ord(c) in NHAY_THONG_MINH for c in giai_kieu_windows_1252(than)):
                co_nguy_co.append(path.relative_to(CENTER).as_posix())
        self.assertTrue(
            co_nguy_co,
            "không script nào còn sinh ra dấu nháy giả khi đọc nhầm — "
            "luật bắt buộc BOM ở trên đã hết lý do, hãy bỏ nó đi")


if __name__ == "__main__":
    unittest.main()
