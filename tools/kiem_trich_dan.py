"""In nội dung thật của mọi trích dẫn ``tệp.py:dòng`` trong một tài liệu.

Tài liệu trong ``docs/`` và ``tasks/`` trích số dòng của code.  Code dịch một
đợt là số trôi hết, mà không có gì báo.  Script này in ra dòng thật ở mỗi chỗ
được trích, để người viết soát bằng mắt::

    .venv/bin/python tools/kiem_trich_dan.py docs/bang-dieu-khien.md

Chỉ đọc trích dẫn nằm **trong dấu nháy ngược**.  Ngoài nháy có đủ thứ số trông
giống trích dẫn — cổng 8765 chẳng hạn.  Dạng ``:1415`` không kèm tên tệp thì
nối vào tệp được nhắc gần nhất, đúng như lối viết trong tài liệu.

Mã thoát 1 khi có chỗ không tra được (sai tên tệp, hoặc số dòng quá cuối tệp).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Tuple

TRONG_NHAY = re.compile(r"`([^`\n]+)`")
DUOI = r"(?:py|js|mjs|html|json|md)"
TRICH_DAN = re.compile(rf"^([\w./-]+\.{DUOI})?:(\d+)(?:-(\d+))?$")
#: Backtick chỉ có tên tệp mã: không phải trích dẫn, nhưng ``:123`` đứng sau nó
#: là nói về tệp ấy — mục 2.4 của ``docs/bang-dieu-khien.md`` viết đúng lối này.
#: Chỉ nhận tệp mã: ``DATA_DIR/erp-agent-nhip.json`` là chỗ chứa dữ liệu, đứng
#: giữa bảng, không phải chỗ để trích dòng.
CHI_TEN_TEP = re.compile(r"^([\w./-]+\.(?:py|js|mjs))$")


def doc_trich_dan(text: str) -> List[Tuple[str, int, int]]:
    """Danh sách ``(tệp, dòng đầu, dòng cuối)`` theo thứ tự xuất hiện."""
    tep_gan_nhat = None
    ket: List[Tuple[str, int, int]] = []
    for nhay in TRONG_NHAY.finditer(text):
        trong = nhay.group(1).strip()
        m = TRICH_DAN.match(trong)
        if m is None:
            chi_ten = CHI_TEN_TEP.match(trong)
            if chi_ten is not None and not trong.endswith(".md"):
                tep_gan_nhat = chi_ten.group(1)
            continue
        tep, dau, cuoi = m.group(1), int(m.group(2)), m.group(3)
        if tep and not tep.endswith(".md"):
            # Tài liệu trích dòng của tài liệu khác thì không mang theo: dạng
            # ``:123`` đứng sau đó gần như luôn nói về tệp mã nhắc trước đó.
            tep_gan_nhat = tep
        tep = tep or tep_gan_nhat
        if tep is None:
            continue
        ket.append((tep, dau, int(cuoi) if cuoi else dau))
    return ket


#: Tài liệu cũ viết tên tệp trần (``service.py:123``).  Thử các thư mục này.
THU_MUC = ("", "flow_web", "automation_center", "tools", "scripts")


def tim_tep(goc: Path, tep: str):
    """Đường dẫn thật của ``tep``, hoặc ``None``."""
    for thu_muc in THU_MUC:
        p = (goc / thu_muc / tep) if thu_muc else (goc / tep)
        if p.is_file():
            return p
    return None


def main(argv: List[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    doc = Path(argv[0])
    goc = Path(argv[1]) if len(argv) > 1 else Path.cwd()
    ket = doc_trich_dan(doc.read_text(encoding="utf-8"))

    hong = 0
    for tep, dau, cuoi in ket:
        p = tim_tep(goc, tep)
        if p is None:
            print(f"!! không có tệp {tep}")
            hong += 1
            continue
        lines = p.read_text(encoding="utf-8").splitlines()
        if dau > len(lines):
            print(f"!! {tep}:{dau} quá cuối tệp ({len(lines)} dòng)")
            hong += 1
            continue
        nhan = f"{tep}:{dau}" + (f"-{cuoi}" if cuoi != dau else "")
        print(nhan)
        print(f"    ▸ {lines[dau - 1].strip()[:100]}")
        if cuoi != dau:
            print(f"    ◂ {lines[min(cuoi, len(lines)) - 1].strip()[:100]}")
    print(f"\n--- {len(ket)} trích dẫn, {hong} chỗ không tra được")
    return 1 if hong else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
