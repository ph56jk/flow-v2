"""Sinh mã SKU cho thẻ ERP từ thuộc tính ``product`` người dùng gõ vào panel.

Người dùng gõ đúng một chữ vào khối *Thuộc tính* của thẻ gốc::

    product: khan tay

Một bảng sheet nói ``khan tay`` viết tắt là ``KT``.  Từ đó mọi thẻ **con**
của thẻ ấy tự có mã của mình::

    {mã sản phẩm}_{số nhận dạng dự án}_{số nhận dạng idea}

Ba phần trả lời ba câu khác nhau, và đó là lý do chúng không gộp được:

``BT``
    *Đây là sản phẩm gì.*  Đọc mã là biết bờm, không phải khăn tay.

``2``
    *Đã có bao nhiêu dự án về bờm.*  Con số của **cả dự án**, không phải của
    một thẻ: bao nhiêu thẻ idea cha trong dự án ấy cũng dùng chung số này, và
    nó chỉ nhích lên khi người ta mở một dự án bờm mới.

``051``
    *Đã có bao nhiêu idea cho bờm.*  Đếm xuyên mọi dự án, ba chữ số.  Dự án
    bờm thứ nhất dừng ở ``BT_1_050`` thì thẻ đầu tiên của dự án bờm thứ hai
    là ``BT_2_051``, không phải ``BT_2_001``.

Thẻ **idea cha** không mang mã.  Nó là chỗ người chịu trách nhiệm khai
``product:`` và là chỗ ảnh được bắn vào; mã thuộc về những thẻ **idea con**
tách ra từ nó.  Cấp mã cho thẻ cha nghĩa là nó ăn mất ``_001``, và thẻ con
đầu tiên — thứ thật sự lên listing — sẽ mang ``_002``.

Chỗ này từng làm hai thứ khác: số giữa từng đếm theo *idea* thay vì theo dự
án, và số cuối từng đếm lại từ ``001`` trong mỗi idea.  Cả hai đều khiến mã
không trả lời được câu hỏi người vận hành thật sự hỏi khi cầm cái nhãn lên.

Ba tính chất giữ cho việc này chạy được trên một cái bảng người ta vẫn đang
dùng, chứ không phải trên bảng trắng:

*Không bao giờ đổi mã đã có.*
    Mã SKU đi ra ngoài phần mềm — nó nằm trên listing, trên file ảnh, trong
    sổ tay người vận hành.  Cấp lại một mã khác cho thẻ đã có mã là làm hỏng
    những thứ đó, nên mã hợp lệ luôn được giữ nguyên và chỉ thẻ trống mới
    được cấp.

*Không cấp trùng số đã dùng.*
    Kể cả số nằm trong mã ai đó gõ tay, kể cả khi số ấy để lại lỗ hổng.  Idea
    ``1`` và ``5`` đang dùng thì idea mới là ``6``, không phải ``2``: lấp lỗ
    hổng nghĩa là hai thẻ khác nhau từng mang cùng một mã.

*Chạy lại cho ra đúng kết quả cũ.*
    Thứ tự cấp là thứ tự thẻ ra đời (mã ``TASK-2026-#####`` tăng dần), không
    phải thứ tự ERP trả về, nên chạy hai lần không đảo mã của nhau.

*Chỉ thẻ đã sang* Đang làm *mới được cấp mã.*
    Cột ấy là chỗ người duyệt đã chốt bộ ảnh và kéo thẻ sang bằng tay — tức
    là chỗ họ nói "cái này có thật".  Cấp mã cho thẻ còn nằm ở *Cần làm* là
    tiêu một số nhận dạng idea cho một thứ có thể bị bỏ đi, mà số ấy thì
    không đòi lại được.  Thẻ nào chưa nói được nó đứng ở cột nào thì không bị
    chặn: chặn theo phỏng đoán sẽ làm đứng cả những lối gọi không đọc cột.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import threading
import time
import unicodedata
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from .erp_meta import TaskMeta, task_meta
from .pipeline import COL_CANCELLED, COL_DOING, COL_TODO, ORDER, column_name, normalize_status

log = logging.getLogger(__name__)


#: Hình dạng một mã SKU đầy đủ: ``KT_2_009``.
#:
#: Phần đầu buộc phải có ít nhất một chữ cái.  Không có ràng buộc ấy thì
#: ``1_2_003`` — một dòng ghi chú đánh số của ai đó — đọc ra thành mã hợp lệ
#: với phần đầu là ``1``, và thẻ mang nó sẽ không bao giờ được cấp mã thật.
SKU_RE = re.compile(r"^(?P<prefix>(?=[A-Z0-9-]*[A-Z])[A-Z0-9][A-Z0-9-]*)_(?P<project>\d+)_(?P<idea>\d+)$")
#: Số đuôi của mã thẻ ERP (``TASK-2026-00906`` → ``906``), dùng làm thứ tự ra đời.
_TASK_NUMBER_RE = re.compile(r"(\d+)\s*$")
#: Bao nhiêu chữ số ở phần số nhận dạng idea.  ``001`` chứ không phải ``1``.
IDEA_DIGITS = 3
#: Tên cột của bảng sheet, đã bỏ dấu và bỏ khoảng trắng.
#:
#: Thứ tự là thứ tự ưu tiên, và ``tenhang`` phải đứng trước ``ten``: bảng thật
#: của xưởng có cả ``TEN HANG`` (``bờm`` — thứ người ta gõ lên thẻ ERP) lẫn
#: ``TEN MOI``/``TEN KHAI BAO`` (``Headband`` — tên tiếng Anh để khai hải
#: quan).  Hai cột sau cố tình *không* nằm trong danh sách: nhận nhầm chúng
#: làm tên sản phẩm thì không dòng nào khớp nổi với thẻ nữa.
#:
#: ``producttype`` có mặt vì sheet đang dùng đặt tên cột tên hàng là
#: ``product_type`` — cùng chữ ấy thẻ ERP dùng cho tên tiếng Anh, nhưng ở sheet
#: thì ô ghi ``khăn tay``.  Thiếu nó, bảng 55 dòng nạp về 0 dòng mà không kêu:
#: bí danh tiếng Anh vẫn vào, nên bảng trông như có chữ còn mã thì rơi hết
#: xuống mã bot tự đoán.
BOOK_PRODUCT_COLUMNS = (
    "product",
    "productname",
    "producttitle",
    "producttype",
    "loaisanpham",
    "loaihang",
    "sanpham",
    "tensanpham",
    "tenhang",
    "tenhanghoa",
    "ten",
)
BOOK_PREFIX_COLUMNS = ("sku", "skuprefix", "skuname", "productkey", "productcode", "productid", "ma", "masku", "kyhieu")

#: Cột **tên tiếng Anh** của mặt hàng, dùng làm bí danh chứ không làm khoá.
#: Thẻ ERP khai ``product_type`` bằng tiếng Anh (``Apron``) còn sheet đặt tên
#: hàng bằng tiếng Việt (``tạp dề``); không có cột này thì hai đầu không bao
#: giờ gặp nhau.  Cố ý **không** nhận cột khai hải quan (``TÊN KHAI BÁO``):
#: câu khai ở đó chung chung theo thiết kế — ``Polyester household ornament``
#: phủ bốn mặt hàng khác nhau trong bảng thật.
BOOK_ALIAS_COLUMNS = ("tenmoi", "tenmoinhat", "tentienganh", "tenanh", "englishname", "productnameen")

#: Nguồn của :class:`ProductCategoryBook` — ERP tự ghi trong danh mục sản
#: phẩm, không phải bot suy diễn theo tên.
ERP_CATEGORY_SOURCE = "erp-category"

#: Nguồn mã mà bảng thật sự ghi, đối lại với mã bot tự đoán.  ``erp-category``
#: cũng thuộc nhóm này dù không phải "sheet": ERP tự ghi, không phải bot đoán.
BOOK_SOURCES = ("book", "book-contains", "book-alias", ERP_CATEGORY_SOURCE)


def la_ma_doan(source: Any) -> bool:
    """Mã này là bảng ghi hay bot đoán?

    Một chỗ hỏi cho mọi người gọi: thêm một kiểu tra bảng mới mà quên sửa một
    trong hai chỗ hỏi thì hoặc bot im lúc cần nói, hoặc bot nhắc lúc bảng đã
    có dòng — cả hai đều dạy người ta bỏ qua lời nhắc.
    """
    return str(source or "") not in BOOK_SOURCES

def strip_accents(value: Any) -> str:
    """``bờm`` → ``bom``.

    Bảng sheet do người gõ, thẻ ERP cũng do người gõ, và hai chỗ đó không bao
    giờ bỏ dấu giống nhau (``khan tay`` với ``khăn tay``).  So sánh sau khi bỏ
    dấu là cách duy nhất để một dòng sheet khớp được với thứ người ta thật sự
    gõ trên thẻ.
    """
    text = unicodedata.normalize("NFD", str(value or ""))
    stripped = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    # ``đ`` không phải chữ ``d`` cộng dấu, NFD không tách nó ra được.
    return stripped.replace("đ", "d").replace("Đ", "D")


def normalize_product(value: Any) -> str:
    """Khoá tra bảng của một tên sản phẩm: bỏ dấu, thường hoá, gộp khoảng trắng."""
    text = strip_accents(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def normalize_column(value: Any) -> str:
    """Khoá so cột: ``"SKU Prefix"`` và ``"sku_prefix"`` là một cột."""
    return re.sub(r"[^a-z0-9]+", "", strip_accents(value).lower())


#: Dấu ngăn giữa nhiều mã trong **một** ô của bảng sheet.
_PREFIX_SPLIT_RE = re.compile(r"[,;/|]+")


def split_prefixes(value: Any) -> Tuple[str, ...]:
    """Một ô bảng sheet → những mã nó ghi, theo đúng thứ tự đã gõ.

    Bảng thật có ô ghi nhiều mã cho một mặt hàng: ``sổ A6, A5, A4`` ghi
    ``WB,VB,SD``, ``khung thêu`` ghi ``KT,OR,HK``.  Đó là các biến thể của
    cùng một mặt hàng, không phải một mã dài.

    Trước đây chỗ này bóp cả ô thành một chuỗi (``LM,BD`` → ``LMBD``), và
    ``LMBD`` là một mã không tồn tại ở bảng nào — thẻ mang nó thì người vận
    hành tra sổ không ra, mà mã thì đã đi ra ngoài phần mềm rồi.
    """
    codes: List[str] = []
    for chunk in _PREFIX_SPLIT_RE.split(str(value or "")):
        code = _one_prefix(chunk)
        if code and code not in codes:
            codes.append(code)
    return tuple(codes)


def _one_prefix(value: Any) -> str:
    text = strip_accents(value).upper()
    text = re.sub(r"[^A-Z0-9-]+", "", text).strip("-")
    return text if any(ch.isalpha() for ch in text) else ""


def normalize_prefix(value: Any) -> str:
    """Phần đầu của mã, viết hoa.  ``kt`` và ``KT`` là một.

    Ô ghi nhiều mã thì lấy mã **đầu tiên**: bảng viết mã chính trước, và đánh
    số tự động chỉ có tên mặt hàng trong tay chứ không biết người ta đang làm
    biến thể nào.  Những mã còn lại không mất — :meth:`ProductBook.options`
    giữ chúng để chỗ nào cần thì nói ra là bảng có mấy lựa chọn.

    Một phần đầu toàn số bị trả về rỗng, cùng lý do :data:`SKU_RE` đòi có chữ
    cái: mã sinh ra từ nó sẽ không đọc lại được, nên mỗi lượt chạy lại cấp cho
    thẻ ấy một mã mới.  Thà nói thẳng là sản phẩm này chưa có phần tên SKU.
    """
    codes = split_prefixes(value)
    return codes[0] if codes else ""


def derive_prefix(product: Any) -> str:
    """Mã tạm khi bảng sheet chưa có dòng cho sản phẩm này.

    Nhiều chữ thì lấy chữ cái đầu mỗi chữ (``khan tay`` → ``KT``), một chữ thì
    lấy hai chữ cái đầu (``bom`` → ``BO``).  Nó *không* thay được bảng sheet —
    bảng mới là nơi nói ``bờm`` là ``BT``.

    Mã đoán không bao giờ được lên thẻ: :func:`plan_skus` để trống mã và nói
    ra là bảng thiếu dòng.  Đoán từng ra ``PNO`` cho ``Punch Needle Ornament``
    trong khi xưởng gọi món ấy là ``OL``.  Hàm này chỉ còn để chỗ tra bảng
    biết mình đang không có dòng.
    """
    words = normalize_product(product).split()
    if not words:
        return ""
    if len(words) >= 2:
        return normalize_prefix("".join(word[0] for word in words[:4]))
    return normalize_prefix(words[0][:2])


def task_number(task_id: Any) -> int:
    """Thứ tự ra đời của một thẻ, đọc từ đuôi số của mã thẻ.

    Thẻ nào không đọc được số thì xuống cuối hàng chứ không chen lên đầu.
    """
    found = _TASK_NUMBER_RE.search(str(task_id or ""))
    return int(found.group(1)) if found else 10**12


@dataclass(frozen=True)
class Sku:
    """Một mã SKU đã tách phần.  ``BT_2_051``: bờm, dự án thứ hai, idea thứ 51."""

    prefix: str
    #: Số nhận dạng **dự án** — dự án thứ mấy của sản phẩm này.  Của cả dự án
    #: chứ không của riêng thẻ nào, nên mọi thẻ cùng bảng mang cùng số.
    project: int
    #: Số nhận dạng **idea** — idea thứ mấy của sản phẩm này, đếm xuyên dự án.
    idea: int

    @property
    def text(self) -> str:
        return f"{self.prefix}_{self.project}_{self.idea:0{IDEA_DIGITS}d}"

    def __str__(self) -> str:  # pragma: no cover - tiện khi log
        return self.text

    @classmethod
    def parse(cls, value: Any) -> Optional["Sku"]:
        """Đọc một mã, hoặc ``None`` nếu nó không phải mã đầy đủ.

        ``KT_1`` mà người ta gõ dở trên thẻ gốc trả về ``None``: nó chưa đủ để
        giữ chỗ cho số nào cả, và coi nó là mã hợp lệ sẽ khiến thẻ ấy không
        bao giờ được cấp mã thật.
        """
        found = SKU_RE.match(normalize_prefix_free(value))
        if not found:
            return None
        return cls(
            prefix=found.group("prefix"),
            project=int(found.group("project")),
            idea=int(found.group("idea")),
        )


def normalize_prefix_free(value: Any) -> str:
    """Một mã SKU viết chuẩn hoá để so khớp: viết hoa, bỏ khoảng trắng."""
    return re.sub(r"\s+", "", strip_accents(value).upper())


@dataclass(frozen=True)
class ProductBook:
    """Bảng sheet: tên sản phẩm → phần tên SKU của nó.

    Bảng là nguồn duy nhất nói ``bờm`` là ``BT``; không suy ra được từ chữ
    ``bờm``.  Thiếu dòng thì :func:`derive_prefix` đỡ tạm, và người gọi biết
    được là mình đang dùng bản đỡ tạm qua :meth:`lookup`.
    """

    entries: Dict[str, str] = field(default_factory=dict)
    #: Những mã *khác* mà bảng ghi cho cùng một mặt hàng, không kể mã chính.
    #: Bảng thật ghi ``khung thêu = KT,OR,HK``: ba biến thể của một thứ.  Đánh
    #: số tự động lấy mã đầu, còn chỗ này giữ phần còn lại để bot nói được
    #: "bảng có ba mã, tôi lấy KT" thay vì im lặng chọn hộ.
    alternates: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    #: Tên tiếng Anh → mã, đọc từ cột tên mới của sheet.  Chỉ giữ tên **một
    #: nghĩa**: bảy tên trong bảng thật ứng với nhiều mặt hàng (``Tote Bag``
    #: vừa là ``TO`` vừa là ``GT``), và chọn hộ một trong hai là in sai mã lên
    #: thùng hàng mà không ai biết.  Không nằm trong :meth:`as_dict` — bí danh
    #: dựng lại từ sheet mỗi lượt đọc, ghi xuống đĩa là giữ lại một cái tên
    #: sheet đã sửa.
    aliases: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, values: Optional[Mapping[str, Any]]) -> "ProductBook":
        entries: Dict[str, str] = {}
        alternates: Dict[str, Tuple[str, ...]] = {}
        for name, prefix in (values or {}).items():
            key = normalize_product(name)
            codes = split_prefixes(prefix)
            if key and codes:
                entries[key] = codes[0]
                if codes[1:]:
                    alternates[key] = codes[1:]
        return cls(entries=entries, alternates=alternates)

    @classmethod
    def from_rows(cls, rows: Optional[Iterable[Mapping[str, Any]]]) -> "ProductBook":
        """Đọc bảng từ các dòng sheet đã parse (``{cột: giá trị}``).

        Cột nào là tên và cột nào là mã được nhận theo tên cột, cùng cách bộ
        đọc sheet của app vẫn nhận cột prompt: người vận hành đặt tên cột theo
        thói quen của họ, không theo hằng số trong mã nguồn.
        """
        entries: Dict[str, str] = {}
        alternates: Dict[str, Tuple[str, ...]] = {}
        # Tên tiếng Anh → những mã đã gặp.  Phải đọc hết bảng rồi mới chốt
        # được: một tên chỉ dùng làm bí danh khi *cả bảng* chỉ có một mã cho
        # nó, mà điều đó thì dòng thứ nhất không biết.
        alias_codes: Dict[str, set] = {}
        for row in rows or ():
            if not isinstance(row, Mapping):
                continue
            columns = {normalize_column(key): value for key, value in row.items()}
            name = ""
            for candidate in BOOK_PRODUCT_COLUMNS:
                name = str(columns.get(candidate) or "").strip()
                if name:
                    break
            alias = ""
            for candidate in BOOK_ALIAS_COLUMNS:
                alias = str(columns.get(candidate) or "").strip()
                if alias:
                    break
            code = ""
            for candidate in BOOK_PREFIX_COLUMNS:
                code = str(columns.get(candidate) or "").strip()
                if code:
                    break
            key = normalize_product(name)
            codes = split_prefixes(code)
            if key and codes:
                entries[key] = codes[0]
                if codes[1:]:
                    alternates[key] = codes[1:]
            alias_key = normalize_product(alias)
            if alias_key and codes:
                alias_codes.setdefault(alias_key, set()).add(codes[0])
        aliases = {
            key: next(iter(codes))
            # Tên trùng với một dòng tên hàng thì bỏ: cột tên hàng là cột khoá,
            # bí danh không được phép đè lên nó.
            for key, codes in alias_codes.items()
            if len(codes) == 1 and key not in entries
        }
        return cls(entries=entries, alternates=alternates, aliases=aliases)

    def merged(self, other: Optional["ProductBook"]) -> "ProductBook":
        """Bảng này chồng lên bảng kia; dòng của ``self`` thắng."""
        if other is None:
            return self
        entries = dict(other.entries)
        entries.update(self.entries)
        # Mã phụ đi theo mã chính: bảng nào thắng ở ``entries`` thì cả dòng ấy
        # thắng, chứ không được ghép mã chính của bảng này với mã phụ của bảng
        # kia — ghép thế là dựng ra một dòng không bảng nào từng ghi.
        alternates = {key: value for key, value in other.alternates.items() if key not in self.entries}
        alternates.update(self.alternates)
        aliases = dict(other.aliases)
        aliases.update(self.aliases)
        # Bảng gần hơn có dòng tên hàng nào thì bí danh của bảng xa phải nhường
        # dòng ấy: bí danh là chỗ đỡ tạm, tên hàng mới là điều người ta khai.
        aliases = {key: value for key, value in aliases.items() if key not in entries}
        return ProductBook(entries=entries, alternates=alternates, aliases=aliases)

    def _contained_key(self, key: str) -> str:
        """Dòng dài nhất của bảng nằm trọn trong ``key``, đếm theo *từ*.

        Không ai đặt tên board đúng bằng tên trong bảng: board còn mang mùa,
        mang hình dáng — ``XMAS Ornament Thêu Tròn`` cho dòng ``ornament
        thêu``.  Đòi khớp từng chữ thì cả cái bảng đầy đủ vẫn trượt và mã rơi
        về :func:`derive_prefix`, tức là một mã chưa bảng nào ghi.

        Khớp theo từ chứ không theo chữ: ``sổ`` nằm trong ``sofa`` là trùng
        chữ, không phải trùng hàng.  Dòng nhiều từ hơn thắng, vì nó nói rõ hơn
        — ``ornament thêu`` thắng ``thêu``.
        """
        padded = f" {key} "
        best = ""
        best_rank: Tuple[int, int, str] = (0, 0, "")
        for candidate in self.entries:
            if f" {candidate} " not in padded:
                continue
            # Xếp hạng có cả tên dòng để hai dòng bằng điểm vẫn ra cùng một
            # đáp án mọi lượt chạy: thứ tự dict không phải thứ tự để cấp mã.
            rank = (candidate.count(" ") + 1, len(candidate), candidate)
            if rank > best_rank:
                best, best_rank = candidate, rank
        return best

    def _code_at(self, key: str, source: str) -> str:
        """Mã của một khoá đã tra được, lấy đúng ô mà ``source`` chỉ tới."""
        return self.aliases[key] if source == "book-alias" else self.entries[key]

    def _row_key(self, product: Any) -> Tuple[str, str]:
        """``(khoá dòng, nguồn)``.  Khớp đủ tên trước, chứa trọn dòng sau."""
        key = normalize_product(product)
        if not key:
            return "", ""
        if key in self.entries:
            return key, "book"
        contained = self._contained_key(key)
        if contained:
            return contained, "book-contains"
        if key in self.aliases:
            return key, "book-alias"
        return "", ""

    def lookup(self, product: Any) -> Tuple[str, str]:
        """``(mã, nguồn)`` cho một sản phẩm.

        ``nguồn`` là ``"book"`` khi bảng có đúng dòng ấy, ``"book-contains"``
        khi tên dài hơn nhưng chứa trọn một dòng (tên board), ``"derived"``
        khi phải đoán, và ``""`` khi không có cả tên sản phẩm để mà đoán.
        """
        key, source = self._row_key(product)
        if key:
            return self._code_at(key, source), source
        derived = derive_prefix(product)
        return (derived, "derived") if derived else ("", "")

    def prefix_for(self, product: Any) -> str:
        return self.lookup(product)[0]

    def options(self, product: Any) -> Tuple[str, ...]:
        """Mọi mã bảng ghi cho mặt hàng này, mã chính đứng đầu.

        Rỗng khi bảng không có dòng — cố ý không trả về mã đoán, vì đây là câu
        hỏi *bảng ghi gì*, không phải *lấy mã nào cho xong*.
        """
        key, source = self._row_key(product)
        if not key:
            return ()
        # Bí danh không mang mã phụ: nó chỉ tồn tại khi cả bảng cho nó đúng
        # một mã, nên "mọi mã bảng ghi" ở đây đúng là một mã ấy.
        if source == "book-alias":
            return (self.aliases[key],)
        return (self.entries[key], *self.alternates.get(key, ()))

    def __bool__(self) -> bool:
        return bool(self.entries)

    def as_dict(self) -> Dict[str, str]:
        """Bảng viết phẳng ra để lưu xuống đĩa và để hiện lên màn hình.

        Dòng nhiều mã ghi lại đúng như bảng sheet viết (``"LM,BD"``), vì
        :meth:`from_mapping` đọc ngược lại được — lưu mỗi mã chính là mỗi lượt
        lưu lại làm mất phần bảng gốc có.
        """
        return {
            key: ",".join((code, *self.alternates.get(key, ())))
            for key, code in self.entries.items()
        }


@dataclass(frozen=True)
class ProductCategoryBook:
    """Danh mục sản phẩm ERP (``productCategories``): tên/mã → tiền tố SKU.

    Khác :class:`ProductBook` ở chỗ ERP tự ghi mã này, không phải sheet người
    vận hành gõ tay — nguồn tra ra luôn là :data:`ERP_CATEGORY_SOURCE`, một mã
    ERP đã có sẵn chứ không phải bot đoán (xem :func:`la_ma_doan`).  Chỉ dòng
    ``kind: type`` mới mang tiền tố; dòng nhóm cha (``kind: group``) không có
    ``sku_prefix`` nên không tra ra được gì.
    """

    entries: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_rows(cls, rows: Optional[Iterable[Mapping[str, Any]]]) -> "ProductCategoryBook":
        """Đọc danh mục từ các dòng ``productCategories`` ERP trả về.

        Chỉ nhận dòng ``kind == "type"``, ``status == "active"`` và có
        ``sku_prefix``.  Khớp theo cả ba cột ``name_en``/``name_vi``/``code``
        qua :func:`normalize_product` — dùng chung bộ chuẩn hoá với
        :class:`ProductBook`, không viết lại bộ thứ hai.
        """
        codes_by_key: Dict[str, set] = {}
        for row in rows or ():
            if not isinstance(row, Mapping):
                continue
            if str(row.get("kind") or "").strip() != "type":
                continue
            if str(row.get("status") or "").strip() != "active":
                continue
            prefix = str(row.get("sku_prefix") or "").strip()
            if not prefix:
                continue
            for candidate in (row.get("name_en"), row.get("name_vi"), row.get("code")):
                key = normalize_product(candidate)
                if key:
                    codes_by_key.setdefault(key, set()).add(prefix)
        # Hai dòng khác nhau trùng cùng khoá tra sau chuẩn hoá: bỏ cả hai,
        # theo đúng tiền lệ bí danh trùng của ProductBook.from_rows (358-367)
        # — không đoán đại một mã khi danh mục ERP tự mâu thuẫn.
        entries = {key: next(iter(codes)) for key, codes in codes_by_key.items() if len(codes) == 1}
        return cls(entries=entries)

    def lookup(self, value: Any) -> Tuple[str, str]:
        """``(mã, nguồn)``; ``("", "")`` khi danh mục ERP không có dòng khớp."""
        key = normalize_product(value)
        if key and key in self.entries:
            return self.entries[key], ERP_CATEGORY_SOURCE
        return "", ""

    def __bool__(self) -> bool:
        return bool(self.entries)


@dataclass(frozen=True)
class SkuCard:
    """Một thẻ, rút gọn còn đúng những gì việc đánh số cần biết."""

    task_id: str
    parent_id: str = ""
    subject: str = ""
    meta: TaskMeta = field(default_factory=TaskMeta)
    #: Tên **bảng** thẻ này đang nằm trên (``project_name`` của ERP).
    #:
    #: Đi kèm mỗi thẻ chứ không truyền riêng vì ERP đã trả sẵn nó trong cùng
    #: payload: hỏi lại là một lượt request nữa trong trần 60 lượt/phút, để
    #: biết một thứ đang nằm trong tay.
    board: str = ""
    #: Mã **dự án** trên ERP (``PROJ-0170``) — thứ số giữa của mã SKU đếm.
    #:
    #: Mã chứ không phải tên: tên bảng người ta sửa được bất cứ lúc nào, mà
    #: đổi tên bảng thì không được phép đổi số dự án của những mã đã in ra.
    project: str = ""
    #: Cột thẻ đang đứng, nguyên văn ERP trả về.  Rỗng nghĩa là *không biết*,
    #: và không biết thì không chặn — xem :func:`card_is_ready`.
    status: str = ""
    #: Danh mục sản phẩm ERP thẻ tự khai (``product_type`` cấp 1 của
    #: ``taskDetail``, hoặc ``custom_product_type`` của ``taskBoard``) — chuỗi
    #: tên trần, chưa qua tra bảng.  Khác hẳn ``meta.product`` (thuộc tính
    #: ``product:`` người gõ tay trong khối *Thuộc tính*): trường này đọc
    #: thẳng payload ERP, không đi qua khối ``meta``.  Đặt cuối để những lời
    #: gọi cũ truyền đối số theo vị trí không phải sửa.
    product_type: str = ""

    @property
    def order(self) -> int:
        return task_number(self.task_id)


def name_fix_for(status: Any, sku: Any, subject: Any, old_name: Any) -> str:
    """Tên thẻ này *đáng lẽ* phải là gì.  Rỗng nghĩa là không có gì để chữa.

    Một luật, hai chiều, và cột quyết định chiều nào:

    * Ở **Cần làm** tên phải là tên người đặt.  Người ta kéo nhầm thẻ sang
      *Đang làm* thì vài giây sau nó mang mã; kéo ngược về mà tên nằm lại là
      bắt họ chép tay từ khối thuộc tính ra.
    * Từ **Đang làm** trở đi tên phải là mã, để nhìn bảng là biết mã.

    Cả hai chiều đều chỉ đè lên đúng cái tên **bot tự đặt**: ở chiều về, tên
    hiện tại phải đúng bằng mã; ở chiều đi, đúng bằng ``ten_cu``.  Người gõ
    một cái tên thứ ba vào thì đó là tên của người, không phải chỗ bot chạm.

    ``Đã huỷ`` không chữa: cột ấy máy không đụng vào nữa.  Không có ``ten_cu``
    cũng không chữa — không biết trả về đâu.
    """
    sku = str(sku or "").strip()
    subject = str(subject or "").strip()
    old_name = str(old_name or "").strip()
    if not sku or not subject:
        return ""
    column = normalize_status(status)
    if column == COL_CANCELLED:
        return ""
    if column == COL_TODO:
        return old_name if old_name and subject == sku else ""
    if subject != sku and old_name and subject == old_name:
        return sku
    return ""


@dataclass(frozen=True)
class SkuAssignment:
    """Mã của một thẻ sau khi tính, kèm lý do nó là như vậy."""

    task_id: str
    sku: str
    role: str
    #: Số nhận dạng dự án nằm trong mã.
    project: int
    #: Số nhận dạng idea nằm trong mã.
    idea: int
    kept: bool
    prefix_source: str = ""
    #: Tên thẻ đang mang, đúng lúc tính.  ``taskFull`` trả sẵn nên không tốn
    #: request nào — và thiếu nó thì không nhận ra được một lượt đổi tên đã
    #: ghi ``ten_cu`` rồi mà chưa bao giờ đổi tên.
    subject: str = ""
    #: Dòng ``ten_cu:`` trên thẻ: tên mà lượt đổi tên đã cất đi trước khi phá.
    old_name: str = ""
    #: Cột thẻ đang đứng, nguyên văn ERP trả về — cột quyết định tên thẻ phải
    #: là mã hay là tên người đặt.  Đặt cuối để lời gọi cũ theo vị trí không
    #: phải sửa.
    status: str = ""

    @property
    def changed(self) -> bool:
        return not self.kept

    @property
    def name_fix(self) -> str:
        """Tên đúng của thẻ này, nếu tên nó đang lệch.  Rỗng là không chữa.

        Chỉ xét thẻ **đã mang mã từ trước** (``kept``): thẻ vừa nhận mã trong
        chính lượt này được đổi tên ngay ở đường ghi, không đi qua đây.
        """
        if not self.kept:
            return ""
        return name_fix_for(self.status, self.sku, self.subject, self.old_name)

    @property
    def name_left_behind(self) -> bool:
        """Mã đã lên thẻ mà tên thì chưa đổi — và chắc chắn không phải người đổi.

        Chữ ký của ca ấy: ``ten_cu`` đã được chép, mà tên thẻ vẫn *đúng bằng*
        cái tên đã chép.  Nghĩa là lượt ghi thuộc tính vào rồi, còn bước đổi
        tên ngay sau nó thì chưa bao giờ chạy — ERP chặn lượt đọc lại, hoặc
        chối lượt đổi tên.

        Người gõ một cái tên khác vào sau đó thì hai thứ lệch nhau, và lượt
        chữa đi qua: tên người đặt không phải thứ bot được đè lên.

        Cột cũng phải đúng.  Thẻ vừa được trả tên nằm ở *Cần làm* mang đúng
        chữ ký này — không xét cột thì lượt chữa ngay sau đó đổi nó lại thành
        mã, và tính năng trả tên tự phá chính nó sau một nhịp.
        """
        return bool(self.sku) and self.name_fix == self.sku

    @property
    def name_to_restore(self) -> str:
        """Tên cũ phải trả lại cho thẻ vừa bị kéo về *Cần làm*.  Rỗng là không."""
        fix = self.name_fix
        return fix if fix and fix != self.sku else ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "sku": self.sku,
            "role": self.role,
            "project": self.project,
            "idea": self.idea,
            "kept": self.kept,
            "prefix_source": self.prefix_source,
            "subject": self.subject,
            "old_name": self.old_name,
            "status": self.status,
        }


@dataclass(frozen=True)
class SkuPlan:
    """Kết quả tính cho cả một cây thẻ."""

    root_id: str = ""
    product: str = ""
    prefix: str = ""
    prefix_source: str = ""
    #: Mã dự án ERP của cụm này, để người gọi khai lại với sổ mà không phải
    #: tự đi hỏi payload một lần nữa.
    project: str = ""
    assignments: Tuple[SkuAssignment, ...] = ()
    skipped: Tuple[Tuple[str, str], ...] = ()
    #: Tên sản phẩm bảng SKU chưa có dòng, nên thẻ của chúng để trống mã.
    #: Người gọi nói ra điều này trên thẻ gốc, một lần.
    unlisted: Tuple[str, ...] = ()

    @property
    def repairs(self) -> Tuple["SkuAssignment", ...]:
        """Thẻ đã mang mã nhưng tên còn kẹt ở lượt đổi tên chưa chạy xong.

        Chúng **không** nằm trong :attr:`changes` — mã trên thẻ đã đúng, không
        có gì để ghi.  Không có ô riêng này thì chúng không nằm ở đâu cả, và
        cái tên kẹt ở lại vĩnh viễn.
        """
        return tuple(item for item in self.assignments if item.name_left_behind)

    @property
    def restores(self) -> Tuple["SkuAssignment", ...]:
        """Thẻ bị kéo về *Cần làm* mà tên vẫn là mã — phải trả lại tên cũ.

        Ô riêng, không lẫn vào :attr:`repairs`: hai bên đổi tên ngược chiều
        nhau, gộp một chỗ là mất luôn cái biết chiều nào.
        """
        return tuple(item for item in self.assignments if item.name_to_restore)

    @property
    def name_fixes(self) -> Tuple["SkuAssignment", ...]:
        """Mọi thẻ có tên đang lệch, cả hai chiều — đúng thứ tự trên cây.

        Đường ghi đi qua đây một lượt, lấy tên mới từ :attr:`~SkuAssignment.name_fix`.
        """
        return tuple(item for item in self.assignments if item.name_fix)

    @property
    def changes(self) -> Tuple[SkuAssignment, ...]:
        """Chỉ những thẻ thật sự phải ghi lại."""
        return tuple(item for item in self.assignments if item.changed)

    def sku_for(self, task_id: Any) -> str:
        wanted = str(task_id or "").strip()
        for item in self.assignments:
            if item.task_id == wanted:
                return item.sku
        return ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "root_id": self.root_id,
            "product": self.product,
            "prefix": self.prefix,
            "prefix_source": self.prefix_source,
            "project": self.project,
            "assignments": [item.as_dict() for item in self.assignments],
            "changes": [item.as_dict() for item in self.changes],
            "skipped": [{"task_id": task, "reason": reason} for task, reason in self.skipped],
            "unlisted": list(self.unlisted),
        }


@dataclass
class SkuLedger:
    """Số cao nhất đã phát cho mỗi tên SKU, sống lâu hơn một cây thẻ.

    :func:`plan_skus` chỉ nhìn thấy đúng cái cây nó đang tính.  Hai thẻ gốc
    khác nhau cùng khai ``product: bờm`` vì thế đều đếm từ đầu và đẻ ra hai
    lần ``BT_1_001`` cho hai sản phẩm khác nhau — không chỗ nào phát hiện ra,
    vì mỗi lượt chạy chỉ biết phần của mình.  Sổ này là trí nhớ nằm *ngoài*
    cái cây: mọi lượt cấp mã đều bắt đầu từ trên con số nó ghi.

    Sổ đánh theo tên SKU chứ không theo bảng.  Mã đi ra ngoài phần mềm — lên
    listing, lên tên file ảnh, vào sổ tay người vận hành — nên chỗ nó phải là
    duy nhất là *cả hệ*, không phải một cái bảng.

    Cố ý chỉ giữ mốc cao nhất chứ không giữ cả danh sách đã dùng: một lỗ hổng
    ở giữa là số của thẻ đã bị xoá hoặc lưu trữ, mà mã của thẻ ấy thì đã đi ra
    ngoài rồi.  Lấp lại đúng bằng thứ :func:`_next_free` đang cấm.

    Sổ chỉ đi lên, không bao giờ đi xuống, và mỗi lượt chạy đều khai báo lại
    những mã nó *nhìn thấy* trên thẻ.  Nhờ vậy mất sổ không thành mất số:
    lượt sau chạm vào cây nào là dựng lại được mốc của cây đó, thay vì tụt về
    0 rồi cấp trùng lên những mã đang nằm trên bảng.
    """

    #: Số nhận dạng **dự án** cao nhất đã phát cho mỗi tên SKU.
    project_seq: Dict[str, int] = field(default_factory=dict)
    #: Số nhận dạng **idea** cao nhất đã phát cho mỗi tên SKU.
    idea_seq: Dict[str, int] = field(default_factory=dict)
    #: Tên SKU → {mã dự án ERP → số nhận dạng dự án}.
    #:
    #: Chỗ này là thứ hai con số kia không thay được.  ``project_seq`` chỉ nói
    #: "bờm đã có 2 dự án"; nó không nói **dự án nào là số 2**.  Thiếu ánh xạ
    #: ấy thì mỗi lượt chạy lại cấp cho cùng một cái bảng một số dự án mới, và
    #: thẻ thứ 51 của dự án bờm thứ nhất sẽ mang ``BT_3_051`` trong khi thẻ thứ
    #: 50 ngay trên nó mang ``BT_1_050``.
    projects: Dict[str, Dict[str, int]] = field(default_factory=dict)
    #: Mã đã cấp mà **chưa chắc** đã nằm trên thẻ → thẻ nào đang giữ chỗ.
    #:
    #: ERP có thể gật một lượt ghi rồi lượt đọc lại không chạy nổi.  Lúc ấy
    #: mốc vẫn phải dịch lên — bảng khác cùng đầu mã mà cấp trùng thì hai thẻ
    #: một mã, đi thẳng ra listing.  Nhưng mốc dịch lên mà số không thuộc về
    #: ai là một lỗ vĩnh viễn: sổ chỉ giữ mốc cao nhất, không giữ chỗ trống.
    #:
    #: Nên số ấy đứng tên đúng cái thẻ đã ghi hụt, và lượt sau chính thẻ ấy
    #: nhận lại chính nó.  Không thủng, cũng không trùng.
    pending: Dict[str, str] = field(default_factory=dict)

    @staticmethod
    def _key(prefix: Any) -> str:
        return str(prefix or "").strip().upper()

    @staticmethod
    def _board(project_id: Any) -> str:
        """Khoá của một dự án.

        Rỗng vẫn là một khoá hợp lệ chứ không bị chối: payload thiếu ``project``
        thì mọi bảng chưa biết tên gộp thành "dự án số 1".  Số nhận dạng idea
        vẫn là số đếm duy nhất của cả sản phẩm nên không có hai mã trùng nhau
        — chỉ có phần giữa đọc kém thông tin đi.
        """
        return str(project_id or "").strip().upper()

    def floor_project(self, prefix: Any) -> int:
        """Số dự án cao nhất đã phát cho tên SKU này; ``0`` khi chưa phát gì."""
        return int(self.project_seq.get(self._key(prefix), 0))

    def floor_idea(self, prefix: Any) -> int:
        """Số idea cao nhất đã phát cho tên SKU này."""
        return int(self.idea_seq.get(self._key(prefix), 0))

    def project_number(self, prefix: Any, project_id: Any) -> int:
        """Dự án này là dự án thứ mấy của sản phẩm ấy — cấp mới nếu chưa từng gặp.

        Hàm này **ghi vào sổ**, khác với hai hàm ``floor_*`` chỉ đọc.  Cố ý:
        một dự án phải nhận đúng một số và giữ nó mãi mãi, nên câu trả lời
        buộc phải được nhớ ngay lúc hỏi.  Hỏi lại lần nữa cho cùng một dự án
        trả về đúng số cũ, nên gọi bao nhiêu lần cũng không tiêu thêm số.
        """
        key = self._key(prefix)
        if not key:
            return 0
        board = self._board(project_id)
        known = self.projects.setdefault(key, {})
        if board in known:
            return known[board]
        if not board:
            # Không biết đây là dự án nào thì tuyệt đối đừng đoán là dự án
            # *mới*: đoán sai kiểu ấy đẻ ra hai thẻ cạnh nhau lệch số giữa
            # (``BT_3_007`` giữ nguyên, hàng xóm trắng nhận ``BT_4_008``).
            # Không có danh tính thì hiểu là "vẫn cái dự án đang đếm dở", tức
            # là cái sàn hiện tại — và không ghi gì vào ánh xạ, vì khoá rỗng
            # không nói được nó là dự án nào.
            return self.floor_project(key) or 1
        number = self.floor_project(key) + 1
        known[board] = number
        self.project_seq[key] = number
        return number

    def observe(self, prefix: Any, *, project: int = 0, idea: int = 0, project_id: Any = "") -> bool:
        """Khai báo một mã đang tồn tại.  ``True`` nếu sổ phải dịch lên."""
        key = self._key(prefix)
        if not key:
            return False
        moved = False
        if int(project or 0) > self.floor_project(key):
            self.project_seq[key] = int(project)
            moved = True
        if int(idea or 0) > self.floor_idea(key):
            self.idea_seq[key] = int(idea)
            moved = True
        board = self._board(project_id)
        if board and int(project or 0) > 0:
            # Mã đang nằm trên thẻ là lời khai chắc nhất về việc dự án ấy mang
            # số mấy — chắc hơn cả sổ, vì mã thì đã in ra ngoài rồi.  Nhờ dòng
            # này, mất sổ không thành mất ánh xạ: quét lại bảng là dựng lại đủ.
            known = self.projects.setdefault(key, {})
            if known.get(board) != int(project):
                known[board] = int(project)
                moved = True
        return moved

    def observe_sku(self, code: Any, project_id: Any = "") -> bool:
        """Khai báo một mã viết đầy đủ (``BT_2_006``).

        Mã máy đọc không ra thì bỏ qua chứ không đoán: một dòng ``sku`` gõ tay
        sai dạng không nói được nó đã chiếm số nào.
        """
        parsed = Sku.parse(code)
        if parsed is None:
            return False
        return self.observe(
            parsed.prefix,
            project=parsed.project,
            idea=parsed.idea,
            project_id=project_id,
        )

    def observe_plan(self, plan: "SkuPlan", project_id: Any = "") -> bool:
        """Khai báo mọi mã trong một kế hoạch — cả mã giữ lại lẫn mã vừa cấp."""
        moved = False
        board = project_id or plan.project
        for item in plan.assignments:
            if self.observe_sku(item.sku, board):
                moved = True
        return moved

    @staticmethod
    def _task(task_id: Any) -> str:
        return str(task_id or "").strip()

    def reserve(self, task_id: Any, code: Any) -> bool:
        """Giữ mã ``code`` cho riêng thẻ ``task_id``.  ``True`` nếu sổ phải dịch.

        Chỉ giữ chỗ, **không** khai số: hai việc khác nhau và người gọi gọi
        riêng.  Gộp lại thì một lượt giữ chỗ nhầm đẩy luôn mốc đi, mà mốc đi
        rồi thì không lùi lại được.

        Mã máy đọc không ra thì bỏ qua chứ không đoán — cùng luật với
        :meth:`observe_sku`.
        """
        task = self._task(task_id)
        parsed = Sku.parse(code)
        if not task or parsed is None:
            return False
        if self.pending.get(task) == parsed.text:
            return False
        self.pending[task] = parsed.text
        return True

    def reserved_for(self, task_id: Any) -> str:
        """Mã đang giữ chỗ cho thẻ này; rỗng nghĩa là không giữ gì cả."""
        return str(self.pending.get(self._task(task_id)) or "")

    def release(self, task_id: Any) -> bool:
        """Trả chỗ giữ lại cho sổ.  ``True`` nếu có gì đó để trả."""
        return self.pending.pop(self._task(task_id), None) is not None

    def as_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "project_seq": {key: int(value) for key, value in sorted(self.project_seq.items())},
            "idea_seq": {key: int(value) for key, value in sorted(self.idea_seq.items())},
            "projects": {
                key: {board: int(number) for board, number in sorted(boards.items())}
                for key, boards in sorted(self.projects.items())
                if boards
            },
        }
        # Ô này chỉ hiện khi có gì để giữ: sổ nào không giữ chỗ thì file trên
        # đĩa giữ nguyên hình cũ, và bản cũ của app đọc nó vẫn không lạ.
        held = {key: str(value) for key, value in sorted(self.pending.items()) if value}
        if held:
            payload["pending"] = held
        return payload

    @classmethod
    def from_mapping(cls, raw: Any) -> "SkuLedger":
        """Đọc sổ từ JSON.  Hỏng chỗ nào thì bỏ chỗ ấy, không ném lỗi.

        Một file sổ cụt không được phép làm chết lượt cấp mã: sổ trống chỉ
        khiến bot đếm lại từ những gì nó nhìn thấy trên thẻ, còn ném lỗi thì
        cả bảng đứng im.

        Đọc cả hai tên cũ ``ideas``/``products``.  File sổ đang nằm trên máy
        trung tâm viết bằng tên ấy, và mốc trong đó đúng là hai mốc bây giờ
        gọi khác đi — bỏ qua chúng nghĩa là lượt chạy đầu sau khi cập nhật sẽ
        đếm lại từ ``001`` và cấp đè lên những mã đã đi ra ngoài.
        """
        source: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
        ledger = cls()
        for names, target in (
            (("project_seq", "ideas"), ledger.project_seq),
            (("idea_seq", "products"), ledger.idea_seq),
        ):
            for field_name in names:
                section = source.get(field_name)
                if not isinstance(section, Mapping):
                    continue
                for key, value in section.items():
                    name = cls._key(key)
                    try:
                        number = int(value)
                    except (TypeError, ValueError):
                        continue
                    if name and number > target.get(name, 0):
                        target[name] = number
        boards = source.get("projects")
        if isinstance(boards, Mapping):
            for key, mapping in boards.items():
                name = cls._key(key)
                if not name or not isinstance(mapping, Mapping):
                    continue
                for board, value in mapping.items():
                    try:
                        number = int(value)
                    except (TypeError, ValueError):
                        continue
                    if number > 0:
                        ledger.projects.setdefault(name, {})[cls._board(board)] = number
        held = source.get("pending")
        if isinstance(held, Mapping):
            for task_id, code in held.items():
                ledger.reserve(task_id, code)
        return ledger


def card_from_node(node: Optional[Mapping[str, Any]]) -> SkuCard:
    """Một node ERP (``taskFull``/``taskDetail``/``taskBoard``) đọc thành :class:`SkuCard`."""
    source: Mapping[str, Any] = node if isinstance(node, Mapping) else {}
    parent = source.get("parent_task") or source.get("parentTask") or source.get("parent")
    if isinstance(parent, Mapping):
        parent = parent.get("name") or parent.get("id")
    return SkuCard(
        task_id=str(source.get("name") or source.get("task_id") or "").strip(),
        parent_id=str(parent or "").strip(),
        subject=str(source.get("subject") or "").strip(),
        meta=task_meta(source),
        board=str(source.get("project_name") or source.get("projectName") or "").strip(),
        project=str(source.get("project") or source.get("projectId") or "").strip(),
        status=str(source.get("status") or "").strip(),
        # Trường cấp 1 của payload, không đi qua khối ``meta`` — ``taskDetail``
        # trả ``product_type``, ``taskBoard`` chỉ trả ``custom_product_type``
        # (cây ``taskFull`` bị cắt ở 60 node nên nhánh dự phòng vẫn cần).
        product_type=str(source.get("product_type") or source.get("custom_product_type") or "").strip(),
    )


def flatten_tree(root: Optional[Mapping[str, Any]]) -> List[SkuCard]:
    """Cây ``taskFull`` đọc thành danh sách thẻ, gốc đứng đầu.

    ``taskFull`` trả cây hai lần: ``children`` chỉ có tên và tiêu đề, còn
    ``subtasks`` là cùng những thẻ đó nhưng đầy đủ cả ``meta``.  Chỉ
    ``subtasks`` dùng được ở đây, và nó lồng nhau nên phải đi hết chứ không
    chỉ lấy một tầng.
    """
    source: Mapping[str, Any] = root if isinstance(root, Mapping) else {}
    if not source:
        return []
    cards: List[SkuCard] = []
    seen: set[str] = set()

    def walk(node: Mapping[str, Any], parent_id: str) -> None:
        card = card_from_node(node)
        if not card.task_id or card.task_id in seen:
            return
        if not card.parent_id and parent_id:
            # ``replace`` chứ không dựng lại bằng vị trí: thêm một trường vào
            # :class:`SkuCard` mà quên sửa dòng này thì trường ấy lặng lẽ về
            # mặc định đúng ở những thẻ đi qua đây, và chỉ lộ ra rất muộn.
            card = replace(card, parent_id=parent_id)
        seen.add(card.task_id)
        cards.append(card)
        for child in node.get("subtasks") or ():
            if isinstance(child, Mapping):
                walk(child, card.task_id)

    walk(source, "")
    return cards


def _used_numbers(values: Iterable[int]) -> set[int]:
    return {int(value) for value in values if int(value) > 0}


def _next_free(used: set[int], start: int = 1) -> int:
    """Số kế tiếp: hơn số lớn nhất đã dùng, chứ không lấp vào chỗ trống.

    Lấp chỗ trống thì rẻ hơn nhưng sai: một số bị trống thường là số của thẻ
    đã bị xoá hoặc lưu trữ, mà mã của thẻ ấy đã đi ra ngoài phần mềm rồi.  Cấp
    lại nó cho thẻ mới là để hai thứ khác nhau mang cùng một mã.
    """
    return max([start - 1, *(number for number in used if number >= start)]) + 1


def card_is_ready(card: Optional[SkuCard]) -> bool:
    """Thẻ này đã tới lúc được cấp mã chưa?

    Mã chỉ phát cho thẻ đã sang *Đang làm* — cột người duyệt kéo tay sang sau
    khi chốt bộ ảnh.  Một thẻ còn ở *Cần làm* có thể bị bỏ đi, và số nhận
    dạng idea nó tiêu mất thì không đòi lại được: sổ chỉ đi lên, nên cái lỗ
    ấy nằm lại vĩnh viễn giữa dãy mã đã in ra ngoài.

    Không đọc được cột thì **không chặn**.  Rỗng nghĩa là người gọi không đưa
    cột chứ không nghĩa là thẻ chưa sẵn sàng, và đoán theo hướng chặn sẽ làm
    đứng im mọi lối gọi không kèm cột — hỏng theo kiểu im lặng, thẻ nằm đó
    không ai biết vì sao.  Cột lạ cũng vậy: bảng đổi tên cột là chuyện của
    người, không phải lý do để ngừng cấp mã.

    ``Cancelled`` thì chặn, và đó là ngoại lệ duy nhất đi theo hướng ngược
    lại: thẻ người ta đã bỏ là thẻ chắc chắn không lên listing.
    """
    if card is None:
        return False
    status = normalize_status(card.status)
    if not status:
        return True
    if status == COL_CANCELLED:
        return False
    if status not in ORDER:
        return True
    return ORDER.index(status) >= ORDER.index(COL_DOING)


def cards_missing_sku(root: Optional[Mapping[str, Any]]) -> int:
    """Bao nhiêu thẻ trong cụm *đáng lẽ* phải có mã mà vẫn chưa có.

    Hai loại thẻ bị trừ ra, và cả hai vì cùng một lý do: đếm chúng vào thì con
    số này không bao giờ về 0, và bất cứ luật cột nào đọc nó sẽ giữ cụm lại
    mãi với lý do "còn N thẻ chưa có mã" — những thẻ mà không ai điền được,
    kể cả máy.

    * **Thẻ idea cha** (thẻ gốc của cụm): nó khai ``product:`` và giữ ảnh, nó
      không mang mã theo thiết kế.
    * **Thẻ chưa sang** Đang làm: :func:`plan_skus` cố ý chưa cấp mã cho
      chúng — xem :func:`card_is_ready`.

    Ở một chỗ duy nhất vì hai bên đọc chung con số này: bot quét bảng và app
    vừa chạy xong ảnh.  Hai bản đếm khác nhau thì thẻ đi hay ở phụ thuộc vào
    ai chạm vào nó trước.
    """
    cards = flatten_tree(root)
    if not cards:
        return 0
    return sum(1 for card in cards[1:] if card_is_ready(card) and not card.meta.sku)


def plan_skus(
    cards: Sequence[SkuCard],
    book: Optional[ProductBook] = None,
    *,
    categories: Optional[ProductCategoryBook] = None,
    root_id: str = "",
    renumber: bool = False,
    ledger: Optional[SkuLedger] = None,
    board_product: str = "",
    project_id: str = "",
    positions: Optional[Mapping[str, Tuple[int, int]]] = None,
) -> SkuPlan:
    """Tính mã cho từng thẻ trong một cụm, không đụng tới mã đã có.

    Cụm có hai tầng, và tầng quyết định vai chứ không phải tiêu đề:

    * **Thẻ gốc** là *idea cha*.  Người chịu trách nhiệm khai ``product:`` ở
      đây, ảnh bắn vào đây.  Nó **không mang mã**.
    * **Mọi thẻ dưới nó** là *idea con*, và mỗi thẻ là một sản phẩm sẽ lên
      listing — nên mỗi thẻ có mã riêng.  Cháu chắt cũng vậy: cây sâu hơn hai
      tầng vẫn chỉ có một loại thẻ mang mã, không có tầng nào bị bỏ qua.

    Tên sản phẩm đọc từ ``product:`` gần nhất khi đi ngược lên; không thẻ nào
    khai thì lấy **tên bảng**.  Hai lối cùng tồn tại vì cùng nói một chuyện:
    bảng tên ``bờm`` với thẻ cha khai ``product: bờm`` phải ra cùng một mã.

    ``renumber=True`` bỏ qua mọi mã sẵn có và đánh số lại cả cụm.  Mặc định
    ``False`` vì mã đã đi ra ngoài phần mềm; chỉ bật khi chính người vận hành
    nói rằng cả bảng đánh sai luật và họ chấp nhận đổi.  Mã người ta gõ tay mà
    máy đọc không ra vẫn được để yên kể cả khi bật.

    ``ledger`` là :class:`SkuLedger` của cả hệ, và ở mô hình này nó **bắt
    buộc trên thực tế** chứ không còn là thứ tô điểm: số nhận dạng dự án và số
    nhận dạng idea đều đếm xuyên bảng, mà một lượt chạy chỉ nhìn thấy đúng cái
    cụm của mình.  Không truyền sổ thì mọi cụm đều tự nhận là dự án số 1 và
    cùng mở màn ở ``_001``.

    Sổ có hiệu lực cả khi ``renumber=True``: đánh số lại một cụm là để nó tự
    nhất quán trở lại, không phải để thu hồi những số đã đi ra ngoài phần mềm
    — nên cụm ấy nhận một dãy liền mới nằm trên mốc, chứ không quay về ``001``.

    ``positions`` là chỗ đứng của thẻ trên bảng (:func:`column_positions`).
    Có thì mã mới cấp theo thứ tự từ trên xuống: thẻ trên cùng nhận số nhỏ
    nhất, thẻ không có trên bảng xếp sau.  Mã đã có vẫn giữ nguyên, nên mã
    mới luôn nằm trên mọi mã đang có.  Không có thì theo số task — thứ tự thẻ
    được tạo.

    ``categories`` là :class:`ProductCategoryBook` (danh mục sản phẩm ERP).
    Có thì mọi lượt tra bảng thử ``categories.lookup(card.product_type)``
    trước, khớp mới dùng; không khớp mới rơi xuống ``book`` như cũ.  ``None``
    hoặc rỗng thì hành vi y hệt trước khi có tham số này.
    """
    catalogue = book or ProductBook()
    counter = ledger if ledger is not None else SkuLedger()
    board_name = str(board_product or "").strip()
    by_id: Dict[str, SkuCard] = {card.task_id: card for card in cards if card.task_id}
    if not by_id:
        return SkuPlan()
    root = str(root_id or "").strip()
    if root not in by_id:
        # Gốc là thẻ duy nhất không có cha nằm trong tập này.
        roots = [card.task_id for card in cards if card.parent_id not in by_id]
        root = roots[0] if roots else next(iter(by_id))
    root_card = by_id[root]
    if not board_name:
        # Người gọi không nói thì hỏi chính cái thẻ: ERP trả ``project_name``
        # trong cùng payload, hỏi lại là đốt một lượt trong trần 60 lượt/phút
        # để biết một thứ đang nằm sẵn trong tay.
        board_name = root_card.board
    board = str(project_id or "").strip() or root_card.project

    def owner_of(card: SkuCard) -> Optional[SkuCard]:
        """Thẻ mà ``card`` đọc thuộc tính theo, khi nó tự khai ``fatheridea``.

        Có để nói đúng cái cây không nói được: một thẻ bị kéo ra khỏi idea cha
        của nó vẫn thuộc về idea ấy, và tên sản phẩm phải đi theo lời khai chứ
        không theo chỗ thẻ đang nằm.
        """
        declared = str(card.meta.father_idea or "").strip()
        if declared and declared in by_id and declared != card.task_id:
            return by_id[declared]
        return None

    def effective_product(card: SkuCard) -> str:
        """Sản phẩm của thẻ: của chính nó, không thì của thẻ trên nó."""
        seen: set[str] = set()
        node: Optional[SkuCard] = card
        while node is not None and node.task_id not in seen:
            seen.add(node.task_id)
            if node.meta.product:
                return node.meta.product
            node = owner_of(node) or by_id.get(node.parent_id)
        return board_name

    def resolve_prefix(product_type: str, fallback_product: str) -> Tuple[str, str]:
        """``(mã, nguồn)``: thử danh mục ERP theo ``product_type`` trước, hết
        mới rơi về ``catalogue`` (sheet/đoán) như hành vi cũ.  Không đi ngược
        lên thẻ cha — khác ``effective_product`` — vì đây là dữ liệu ERP thẻ
        tự khai trên chính nó, không phải thuộc tính gõ tay được kế thừa.
        """
        if categories and product_type:
            prefix, source = categories.lookup(product_type)
            if prefix:
                return prefix, source
        return catalogue.lookup(fallback_product)

    root_product = effective_product(root_card)
    root_prefix, root_source = resolve_prefix(root_card.product_type, root_product)
    if la_ma_doan(root_source):
        # Mã đoán không được nói ra ở đâu cả, kể cả trong báo cáo: người đọc
        # thấy ``PNO`` là tưởng bot sắp cấp ``PNO``.
        root_prefix = ""

    # Thứ tự cấp số: theo chỗ thẻ đứng trên bảng, từ trên xuống.  Thẻ không có
    # trên bảng xếp sau; không đưa bảng thì mọi thẻ cùng một chỗ và số task
    # quyết định như cũ.
    spots: Mapping[str, Tuple[int, int]] = positions or {}
    unplaced = (len(ORDER) + 1, 0)
    ordered = sorted(
        (card for card in by_id.values() if card.task_id != root),
        key=lambda item: (spots.get(item.task_id, unplaced), item.order),
    )

    # Vòng một: giữ lại mọi mã hợp lệ đang có, và ghi nhớ số nào đã bị chiếm.
    kept: Dict[str, Sku] = {}
    #: Thẻ đang mang một dòng ``sku:`` người ta gõ tay mà máy đọc không ra
    #: (``khantay_101`` chẳng hạn).  Nó *không* trống, nên phần ghi để nguyên
    #: cho người; nếu ở đây lại coi như trống mà cấp mã mới thì kế hoạch hứa
    #: một đằng, lượt ghi làm một nẻo, và lần chạy nào cũng báo còn một thẻ
    #: chưa ghi cho đến hết đời.
    hand_written: Dict[str, str] = {}
    #: Số nhận dạng idea đã dùng, gom theo *tên SKU*.  Theo tên SKU chứ không
    #: theo bảng: đuôi mã là số đếm duy nhất của cả sản phẩm, xuyên mọi dự án.
    used_ideas: Dict[str, set[int]] = {}
    for card in ordered:
        parsed = Sku.parse(card.meta.sku)
        if renumber and parsed is not None:
            # Đánh số lại: mã cũ đọc được thì bỏ hẳn, không giữ chỗ cho số của
            # nó — giữ chỗ thì cả cụm phải nhảy qua những số ấy và kết quả
            # không còn là một dãy liền, tức là không sửa được gì.
            continue
        if parsed is None:
            code = str(card.meta.sku or "").strip()
            if code:
                hand_written[card.task_id] = code
            continue
        kept[card.task_id] = parsed
        used_ideas.setdefault(parsed.prefix, set()).add(parsed.idea)
        # Mã đang nằm trên thẻ nói ra dự án này mang số mấy — chắc hơn cả sổ,
        # vì mã thì đã in ra ngoài rồi.  Khai lại ngay ở đây để một cái sổ bị
        # mất không kéo theo việc cùng cái bảng ấy nhận một số dự án khác.
        counter.observe_sku(parsed.text, card.project or board)

    # Thẻ gốc không bao giờ được *cấp* mã, nhưng nếu ai gõ tay một mã đọc được
    # lên nó thì con số ấy đã bị chiếm ngoài đời thật.  Không khai ở đây thì
    # thẻ con ngay bên dưới được cấp đúng con số đó — hai thẻ một mã.  Khai cả
    # trong lượt ``renumber``: mã trên gốc không bao giờ bị ghi đè nên nó giữ
    # chỗ vĩnh viễn, khác hẳn mã trên thẻ con (thứ mà đánh lại sẽ xoá đi).
    root_parsed = Sku.parse(root_card.meta.sku)
    if root_parsed is not None:
        used_ideas.setdefault(root_parsed.prefix, set()).add(root_parsed.idea)
        counter.observe_sku(root_parsed.text, root_card.project or board)

    assignments: List[SkuAssignment] = []
    skipped: List[Tuple[str, str]] = []
    unlisted: List[str] = []

    for card in ordered:
        code = hand_written.get(card.task_id)
        if code:
            skipped.append(
                (card.task_id, f"đang mang mã tự gõ {code!r}, không đúng dạng {{TÊN}}_{{dự án}}_{{idea}}")
            )
            continue

        existing = kept.get(card.task_id)
        if existing is not None:
            # Thẻ đã cầm được mã thì chỗ giữ chỗ cho nó hết việc.  Không dọn
            # thì file sổ phình ra bằng đúng số lần ERP chập.
            if counter.reserved_for(card.task_id) == existing.text:
                counter.release(card.task_id)
            assignments.append(
                SkuAssignment(
                    task_id=card.task_id,
                    sku=existing.text,
                    role="idea",
                    project=existing.project,
                    idea=existing.idea,
                    kept=True,
                    prefix_source=resolve_prefix(card.product_type, effective_product(card))[1] or root_source,
                    subject=card.subject,
                    old_name=str(card.meta.get("ten_cu") or ""),
                    status=card.status,
                )
            )
            continue

        if not card_is_ready(card):
            skipped.append((card.task_id, f"chưa sang cột {column_name(COL_DOING)}"))
            continue

        product_name = effective_product(card)
        prefix, source = resolve_prefix(card.product_type, product_name)
        if not prefix:
            skipped.append((card.task_id, "chưa có product để tra bảng SKU"))
            continue
        if la_ma_doan(source):
            # Bảng chưa có dòng thì để trống mã, không đoán.  Mã đoán theo chữ
            # cái đầu từng ra PNO cho "Punch Needle Ornament", trong khi xưởng
            # gọi món ấy là OL.  Mã đã in ra ngoài thì không thu lại được.
            skipped.append((card.task_id, f"chưa có mã trong bảng SKU cho {product_name}"))
            if product_name not in unlisted:
                unlisted.append(product_name)
            continue

        project_no = counter.project_number(prefix, card.project or board)
        slot = used_ideas.setdefault(prefix, set())
        # Số sổ đang giữ chỗ cho đúng thẻ này thì trả lại cho nó, thay vì cấp
        # số kế tiếp và để số cũ nằm không.  Chỉ nhận khi cùng đầu mã: sản
        # phẩm của thẻ đổi rồi thì mã cũ không còn nói đúng nữa.
        held = Sku.parse(counter.reserved_for(card.task_id))
        if held is not None and held.prefix == prefix and held.idea not in slot:
            slot.add(held.idea)
            assignments.append(
                SkuAssignment(
                    task_id=card.task_id,
                    sku=held.text,
                    role="idea",
                    project=held.project,
                    idea=held.idea,
                    kept=False,
                    prefix_source=source or root_source,
                    subject=card.subject,
                    old_name=str(card.meta.get("ten_cu") or ""),
                    status=card.status,
                )
            )
            continue
        idea_no = _next_free(slot, counter.floor_idea(prefix) + 1)
        slot.add(idea_no)
        assignments.append(
            SkuAssignment(
                task_id=card.task_id,
                sku=Sku(prefix, project_no, idea_no).text,
                role="idea",
                project=project_no,
                idea=idea_no,
                kept=False,
                prefix_source=source or root_source,
                subject=card.subject,
                old_name=str(card.meta.get("ten_cu") or ""),
                status=card.status,
            )
        )

    assignments.sort(key=lambda item: task_number(item.task_id))
    return SkuPlan(
        root_id=root_card.task_id,
        product=root_product,
        prefix=root_prefix,
        prefix_source=root_source,
        project=board,
        assignments=tuple(assignments),
        skipped=tuple(sorted(skipped)),
        unlisted=tuple(unlisted),
    )


#: Hạng cột khi xếp chỗ đứng: cột xa hơn trong quy trình đứng trước, vì thẻ
#: đã đi xa hơn là thẻ được chốt sớm hơn.  Cột lạ xếp sau cùng.
_POSITION_COLUMNS: Tuple[str, ...] = tuple(reversed(ORDER))


def column_positions(board: Any) -> Dict[str, Tuple[int, int]]:
    """Chỗ đứng của từng thẻ trên bảng: ``{thẻ: (hạng cột, thứ tự trong cột)}``.

    ``taskBoard`` không trả khoá nào nói vị trí.  Thứ tự mảng ``tasks`` của
    mỗi cột chính là thứ tự trên màn hình, phần tử đầu là thẻ trên cùng —
    nên đọc thẳng từ đó.  Số nhỏ đứng trước.

    Giữa các cột: *Hoàn thành* trước *Đang review* trước *Đang làm* trước
    *Cần làm*, cột lạ sau cùng.  Payload hỏng thì trả rỗng, không đoán.
    """
    source: Mapping[str, Any] = board if isinstance(board, Mapping) else {}
    columns = source.get("columns")
    found: Dict[str, Tuple[int, int]] = {}
    if not isinstance(columns, list):
        return found
    for column in columns:
        if not isinstance(column, Mapping) or not isinstance(column.get("tasks"), list):
            continue
        status = normalize_status(column.get("status"))
        rank = _POSITION_COLUMNS.index(status) if status in _POSITION_COLUMNS else len(_POSITION_COLUMNS)
        for index, row in enumerate(column["tasks"]):
            name = str(row.get("name") or "").strip() if isinstance(row, Mapping) else ""
            if name and name not in found:
                found[name] = (rank, index)
    return found


def plan_tree(
    root: Optional[Mapping[str, Any]],
    book: Optional[ProductBook] = None,
    *,
    ledger: Optional[SkuLedger] = None,
    board_product: str = "",
    project_id: str = "",
) -> SkuPlan:
    """:func:`plan_skus` đọc thẳng từ payload ``taskFull``.

    ``ledger`` đi thẳng qua chứ không bị nuốt: một lối vào bỏ quên sổ là một
    lối vào cấp lại số đã cấp, và cái đó chỉ lộ ra khi mã đã nằm trên nhãn.
    """
    source: Mapping[str, Any] = root if isinstance(root, Mapping) else {}
    node = source.get("root") if isinstance(source.get("root"), Mapping) else source
    cards = flatten_tree(node)
    return plan_skus(
        cards,
        book,
        root_id=cards[0].task_id if cards else "",
        ledger=ledger,
        board_product=board_product,
        project_id=project_id,
    )


# ── Mỗi lúc một lượt đánh số ──────────────────────────────────────────────
#
# Hai lượt ``fill_task_skus`` chạy cùng lúc thì cùng đọc sổ và cây trước khi
# lượt nào kịp ghi, và cả hai cùng thấy thẻ còn trống.  Ca thật: 05463 nhận
# OL_1_045 rồi OL_1_046.  Khoá nằm ở đây chứ không trong ``service.py``, để
# mọi đường — bot quét, người bấm, làn nhanh — dùng chung đúng một cái.

_SKU_PASS_LOCK = threading.RLock()
_SKU_PASS_CONDITION = threading.Condition()
_SKU_PASS_PRIORITY_WAITERS = 0
_SKU_PASS_LOCAL = threading.local()


def _sku_pass_depth() -> int:
    return int(getattr(_SKU_PASS_LOCAL, "depth", 0) or 0)


def sku_pass_priority_waiting() -> bool:
    """Có làn nhanh đang chờ lượt đánh số không."""
    with _SKU_PASS_CONDITION:
        return _SKU_PASS_PRIORITY_WAITERS > 0


def sku_pass_is_priority() -> bool:
    """Luồng đang cầm khoá này là làn nhanh ưu tiên."""
    return bool(getattr(_SKU_PASS_LOCAL, "priority_depth", 0) or 0)


def sku_pass_yield_to_priority() -> bool:
    """Nhường một mốc an toàn cho làn nhanh đang chờ.

    Người gọi phải đang giữ đúng một lớp ``sku_pass`` thường.  Làn nhanh đã
    ghi tên mình vào hàng trước khi chờ khoá, nên lượt nền không thể nhả rồi
    tự lấy lại trước nó.
    """
    if _sku_pass_depth() != 1 or sku_pass_is_priority():
        return False
    with _SKU_PASS_CONDITION:
        if _SKU_PASS_PRIORITY_WAITERS <= 0:
            return False
    _SKU_PASS_LOCK.release()
    try:
        with _SKU_PASS_CONDITION:
            while _SKU_PASS_PRIORITY_WAITERS > 0:
                _SKU_PASS_CONDITION.wait()
    finally:
        _SKU_PASS_LOCK.acquire()
    return True


@contextlib.contextmanager
def sku_pass(
    *, wait: bool = True, timeout: Optional[float] = None, priority: bool = False
) -> Iterator[bool]:
    """Giữ lượt đánh số.  ``wait=False``: có lượt khác đang chạy thì trả ``False`` ngay.

    Là ``RLock``: một luồng đi qua hai lớp khoá (làn nhanh → ``fill_task_skus``)
    không tự chặn chính mình.

    Làn nhanh ghi tên vào hàng ưu tiên trước khi chờ có hạn.  Lượt quét nền
    nhường ở giữa các thẻ, sau khi đã giữ chỗ mọi mã còn lại trong sổ.  Khoá
    vẫn là hàng rào duy nhất cho mọi đường cấp mã.
    """
    global _SKU_PASS_PRIORITY_WAITERS
    nested = _sku_pass_depth() > 0
    registered = False
    if priority and wait and not nested:
        with _SKU_PASS_CONDITION:
            _SKU_PASS_PRIORITY_WAITERS += 1
            registered = True
            _SKU_PASS_CONDITION.notify_all()
    elif wait and not nested:
        # Một lượt nền mới không được chen vào trước làn nhanh đã chờ.
        with _SKU_PASS_CONDITION:
            while _SKU_PASS_PRIORITY_WAITERS > 0:
                _SKU_PASS_CONDITION.wait()
    if not wait:
        got = _SKU_PASS_LOCK.acquire(blocking=False)
    elif timeout is None:
        got = _SKU_PASS_LOCK.acquire(blocking=True)
    else:
        got = _SKU_PASS_LOCK.acquire(blocking=True, timeout=max(0.0, float(timeout)))
    if got:
        _SKU_PASS_LOCAL.depth = _sku_pass_depth() + 1
        if priority:
            _SKU_PASS_LOCAL.priority_depth = int(
                getattr(_SKU_PASS_LOCAL, "priority_depth", 0) or 0
            ) + 1
    try:
        yield got
    finally:
        if got:
            if priority:
                _SKU_PASS_LOCAL.priority_depth = max(
                    0, int(getattr(_SKU_PASS_LOCAL, "priority_depth", 0) or 0) - 1
                )
            _SKU_PASS_LOCAL.depth = max(0, _sku_pass_depth() - 1)
            _SKU_PASS_LOCK.release()
        if registered:
            with _SKU_PASS_CONDITION:
                _SKU_PASS_PRIORITY_WAITERS = max(0, _SKU_PASS_PRIORITY_WAITERS - 1)
                _SKU_PASS_CONDITION.notify_all()


def fill_cost(cards: int, cut_new: int = 0, wrong: int = 0) -> int:
    """Số request ước cho một lượt đánh số ``cards`` thẻ.

    Ba cho phần nền: hai lượt đọc cây, một lượt đọc bảng.  Bảng đọc cả khi
    cây bị cắt, để biết thẻ nằm ngoài cây, chứ không chỉ để xếp mã từ trên
    xuống.  Năm cho mỗi thẻ: đọc lại, ghi, đọc kiểm, có khi đọc kiểm lần nữa,
    đổi tên.

    * ``cut_new``: thẻ mới cần mã nằm ngoài cây, mỗi thẻ một ``taskFull``.
    * ``wrong``: thẻ có mã mà tên khác mã, mỗi thẻ một ``taskFull`` và một
      lần chữa tên.  Thẻ bị cắt tên đúng bằng mã thì không tốn gì: lượt đánh
      số lấy nó từ dòng bảng.

    Lượt dài quá 40 request thì bảng nhớ hết hạn, phải đọc lại bảng: cộng 2
    cho mỗi 40.  Ước dư còn hơn vượt trần.
    """
    base = 3 + 5 * max(0, int(cards)) + max(0, int(cut_new)) + 2 * max(0, int(wrong))
    return base + 2 * (base // 40)


#: Chỗ để dành cho một lượt đánh số một thẻ, kèm lượt đọc cây trước nó.  Bảng
#: nguội chỉ được đọc khi ngân sách còn dư chừng này.
_LANE_RESERVE = 1 + fill_cost(1)
#: Chỗ phải chừa trước khi ngó thêm một bảng **chỉ vì nó ấm**: đủ cho trọn một
#: lượt đánh số cụm ba thẻ — cụm thường gặp nhất.  Lượt ngó định kỳ là bắt
#: buộc, lượt ngó thêm vì ấm là xa xỉ, nên nó phải nhường.  Hệ quả: trần hẹp
#: thì nhịp ấm tự tắt và hành vi quay về như cũ, không bao giờ có chuyện ngó
#: nhanh hơn mà lại ghi mã chậm đi.
_LANE_WARM_RESERVE = 1 + fill_cost(3)
#: Dưới mức này thì không đủ một lượt đọc bảng cộng một lượt đánh số.
_LANE_MIN_BUDGET = _LANE_RESERVE + 2
#: Chuỗi cha lồng sâu hơn thế này là dữ liệu hỏng, không phải cây thật.
_LANE_MAX_DEPTH = 12
#: Một chuỗi, dùng ở cả hai chỗ bỏ qua cụm chưa tới lượt — hàng rào đầu nhịp
#: và nhánh kết quả.  Hai lý do khác nhau thay phiên nhau là ``_note_skip``
#: hết dedup: 12 dòng mỗi phút cho một cụm đứng yên.
NOT_DUE_DETAIL = "cụm chưa tới lượt, để lượt quét chính"


class RequestBudget:
    """Cửa sổ trượt 60 giây, chia chung cho mọi worker của làn nhanh.

    Không chặn như ``_RateLimiter`` của bot: hết chỗ thì trả ``False`` và
    nhịp sau thử lại.  Làn nhanh đứng chờ ở đây là chiếm luồng vô ích.
    """

    def __init__(
        self,
        per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        window_s: float = 60.0,
    ) -> None:
        self._limit = max(1, int(per_minute))
        self._window_s = float(window_s)
        self._clock = clock
        self._hits: deque = deque()
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        """Số request tối đa trong một cửa sổ."""
        return self._limit

    @property
    def window_s(self) -> float:
        """Độ dài cửa sổ, tính bằng giây."""
        return self._window_s

    def take(self, count: int = 1, *, keep: int = 0) -> bool:
        """Lấy ``count`` chỗ, nếu sau đó vẫn còn ít nhất ``keep`` chỗ."""
        count = max(0, int(count))
        with self._lock:
            now = self._clock()
            while self._hits and now - self._hits[0] >= self._window_s:
                self._hits.popleft()
            if len(self._hits) + count + max(0, int(keep)) > self._limit:
                return False
            self._hits.extend([now] * count)
            return True


def _env_number(env: Mapping[str, str], name: str, default: float, low: float, high: float) -> float:
    raw = str(env.get(name, "") or "").strip()
    try:
        value = float(raw) if raw else float(default)
    except ValueError:
        value = float(default)
    return min(max(value, low), high)


@dataclass(frozen=True)
class SkuFastLaneConfig:
    """Làn nhanh đánh số: đọc bảng mỗi 15 giây thay vì chờ lượt quét 120 giây.

    Mặc định **tắt**.  Hai máy dùng chung token bot nhưng mỗi máy một sổ SKU;
    bật cả hai là hai máy cùng đánh số một cụm từ hai quyển sổ.
    """

    enabled: bool = False
    #: Nhịp đọc lại một bảng đang có thẻ chờ mã.
    interval_s: float = 15.0
    #: Trần request mỗi phút cho cả làn, chia chung cho mọi worker.  Token bot
    #: có 60/phút; phần còn lại là của lượt quét chính và lister.
    budget_per_minute: int = 20
    #: Gặp 429 thì nghỉ hẳn chừng này giây.
    rest_s: float = 60.0
    #: Bảng không có thẻ nào chờ mã, cũng không ai vừa động vào, thì bao lâu
    #: mới nhìn lại.
    rediscover_s: float = 300.0
    #: Bảng vừa có người động vào thì đọc lại theo nhịp này.  Nhịp nóng chỉ
    #: giúp khi làn *đã biết* có thẻ chờ; nhịp này là để **phát hiện** thẻ mới.
    warm_s: float = 10.0
    #: Một lần bảng đổi thì giữ ấm chừng này giây.  Người ta kéo thẻ theo đợt.
    warm_for_s: float = 900.0
    #: Nhiều nhất bao nhiêu bảng được hưởng nhịp ấm cùng lúc; 0 là tắt hẳn.
    #: Đây là hàng rào chi phí: ``warm_boards × (60 / warm_s)`` request mỗi phút.
    warm_boards: int = 2
    #: Số luồng đọc bảng song song.  Để 2, đừng nâng: đo trên ERP thật ngày
    #: 13/09/2026, cùng nhịp đọc 216 request/phút, 4 luồng ra 3,8 lỗi
    #: ``QueryDeadlockError`` mỗi phút còn 2 luồng ra 2,1 (mẫu 33 phút).  Chỗ
    #: nghẽn của ERP là số truy vấn *đồng thời*, không phải số request mỗi
    #: phút — nâng trần token lên 500 không chữa được chỗ này.
    workers: int = 2
    #: Chờ khoá lượt nền tối đa chừng này giây.  Đủ để lượt nền bàn giao ở
    #: cuối một thẻ, nhưng không treo cả nhịp làn nhanh.
    lock_wait_s: float = 1.0

    @property
    def tick_s(self) -> float:
        """Nhịp ngủ của vòng lặp: nhỏ nhất trong các nhịp đang dùng.

        Ngó bảng mỗi ``warm_s`` giây thì vòng lặp phải thức mỗi ``warm_s``
        giây — nhịp tick là trần dưới của mọi nhịp đọc.
        """
        if self.warm_boards > 0:
            return min(self.interval_s, self.warm_s)
        return self.interval_s

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "SkuFastLaneConfig":
        source = os.environ if env is None else env
        flag = str(source.get("ERP_SKU_FAST_LANE", "0") or "").strip().lower()
        return cls(
            enabled=flag in {"1", "true", "yes", "on"},
            interval_s=_env_number(source, "ERP_SKU_FAST_LANE_SECONDS", 15, 5, 120),
            budget_per_minute=int(
                _env_number(source, "ERP_SKU_FAST_LANE_BUDGET", 20, _LANE_MIN_BUDGET, 500)
            ),
            rest_s=_env_number(source, "ERP_SKU_FAST_LANE_REST", 60, 60, 900),
            rediscover_s=_env_number(source, "ERP_SKU_FAST_LANE_REDISCOVER", 300, 5, 3600),
            warm_s=_env_number(source, "ERP_SKU_FAST_LANE_WARM", 10, 5, 120),
            warm_for_s=_env_number(source, "ERP_SKU_FAST_LANE_WARM_FOR", 900, 60, 7200),
            warm_boards=int(_env_number(source, "ERP_SKU_FAST_LANE_WARM_BOARDS", 2, 0, 50)),
            workers=int(_env_number(source, "ERP_SKU_FAST_LANE_WORKERS", 2, 1, 8)),
            lock_wait_s=_env_number(source, "ERP_SKU_FAST_LANE_LOCK_WAIT", 1, 0.1, 5),
        )


def _row_agents(row: Mapping[str, Any]) -> set:
    users = set()
    for item in row.get("agents") or ():
        user = item.get("bot_user") if isinstance(item, Mapping) else item
        user = str(user or "").strip()
        if user:
            users.add(user)
    return users


def _row_parent(row: Optional[Mapping[str, Any]]) -> str:
    return str((row or {}).get("parent_task") or "").strip()


def _rows_by_name(rows: Iterable[Any]) -> Dict[str, Mapping[str, Any]]:
    found: Dict[str, Mapping[str, Any]] = {}
    for row in rows or ():
        if isinstance(row, Mapping):
            name = str(row.get("name") or "").strip()
            if name:
                found[name] = row
    return found


def _ancestors(name: str, by_name: Mapping[str, Mapping[str, Any]]) -> List[str]:
    """Tổ tiên của một thẻ, gần trước xa sau.  Dừng ở vòng lặp hay hết dòng."""
    chain: List[str] = []
    seen = {name}
    parent = _row_parent(by_name.get(name))
    while parent and parent not in seen and len(chain) < _LANE_MAX_DEPTH:
        chain.append(parent)
        seen.add(parent)
        parent = _row_parent(by_name.get(parent))
    return chain


def _waiting_clusters(rows: Iterable[Any], bot_user: str, columns: set) -> Dict[str, List[str]]:
    by_name = _rows_by_name(rows)
    user = str(bot_user or "").strip()
    found: Dict[str, List[str]] = {}
    if not user:
        return found
    for name, row in by_name.items():
        if not _row_parent(row) or str(row.get("custom_sku") or "").strip():
            continue
        if normalize_status(row.get("status")) not in columns:
            continue
        chain = _ancestors(name, by_name)
        # Gắn bot ở thẻ cha là lan xuống cả thẻ con.
        if user not in _row_agents(row) and not any(
            user in _row_agents(by_name.get(item) or {}) for item in chain
        ):
            continue
        root = chain[-1] if chain else _row_parent(row)
        found.setdefault(root, []).append(name)
    return found


def hot_clusters(rows: Iterable[Any], bot_user: str) -> Dict[str, List[str]]:
    """Cụm có thẻ con đang ở *Đang làm*, chưa có mã, gắn bot: ``{gốc: [thẻ]}``.

    Đọc từ dòng ``taskBoard`` chứ không từ cây: một request thấy cả board,
    còn cây thì mỗi cụm một request.  Gốc là tổ tiên cao nhất tìm thấy trên
    bảng — đúng thẻ ``fill_task_skus`` cần.
    """
    return _waiting_clusters(rows, bot_user, {COL_DOING})


def _name_fix_clusters(rows: Iterable[Any], bot_user: str, *, restore: bool) -> Dict[str, List[str]]:
    """Cụm có thẻ mang mã mà tên đang lệch với cột nó đứng: ``{gốc: [thẻ]}``.

    Dòng ``taskBoard`` **không có** ``ten_cu``, nên đây chỉ là cái cổng thô:
    nó chọn cụm đáng bỏ một lượt đọc cây ra xem.  Luật thật —
    :func:`name_fix_for` — chạy sau, khi đã có khối thuộc tính trong tay.

    Không có cổng này thì luật kia viết xong vẫn nằm im: :func:`hot_clusters`
    chỉ nhặt cụm có thẻ **chưa có mã**, mà thẻ vừa bị kéo về *Cần làm* thì đã
    mang mã rồi.
    """
    by_name = _rows_by_name(rows)
    user = str(bot_user or "").strip()
    found: Dict[str, List[str]] = {}
    if not user:
        return found
    for name, row in by_name.items():
        code = str(row.get("custom_sku") or "").strip()
        subject = str(row.get("subject") or "").strip()
        # Dòng thiếu ``subject`` là *không biết*, không phải "tên sai": đoán ở
        # đây là đổi tên một thẻ chỉ vì ERP trả thiếu một khoá.
        if not _row_parent(row) or not code or not subject:
            continue
        column = normalize_status(row.get("status"))
        if restore:
            if column != COL_TODO or subject != code:
                continue
        elif column != COL_DOING or subject == code:
            continue
        chain = _ancestors(name, by_name)
        if user not in _row_agents(row) and not any(
            user in _row_agents(by_name.get(item) or {}) for item in chain
        ):
            continue
        root = chain[-1] if chain else _row_parent(row)
        found.setdefault(root, []).append(name)
    return found


def restore_clusters(rows: Iterable[Any], bot_user: str) -> Dict[str, List[str]]:
    """Cụm có thẻ ở *Cần làm* còn mang tên là mã — chờ trả lại tên cũ."""
    return _name_fix_clusters(rows, bot_user, restore=True)


def repair_clusters(rows: Iterable[Any], bot_user: str) -> Dict[str, List[str]]:
    """Cụm có thẻ ở *Đang làm* mang tên không phải mã — chờ đổi lại thành mã."""
    return _name_fix_clusters(rows, bot_user, restore=False)


def board_is_hot(rows: Iterable[Any], bot_user: str) -> bool:
    """Bảng còn thẻ gắn bot chưa có mã, ở *Cần làm* hay *Đang làm*.

    Thẻ ở *Cần làm* là thẻ sắp được kéo sang, nên bảng ấy phải đọc theo nhịp
    nhanh, không phải năm phút một lần.
    """
    return bool(_waiting_clusters(rows, bot_user, {COL_TODO, COL_DOING}))


def board_stamp(rows: Iterable[Any]) -> str:
    """Dấu một bảng: ``modified`` muộn nhất, kèm số dòng.

    So dấu của hai lần đọc liên tiếp là biết có ai vừa động vào bảng, mà không
    phải so ``modified`` với đồng hồ máy: ERP trả giờ máy chủ, máy trung tâm
    lệch múi giờ, so thẳng là sai cả hai chiều.  Đếm cả số dòng vì thẻ bị xoá
    không làm ``modified`` muộn nhất đổi.
    """
    latest = ""
    count = 0
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        count += 1
        when = str(row.get("modified") or "")
        if when > latest:
            latest = when
    return "%d|%s" % (count, latest)


def _is_rate_limited(error: Any) -> bool:
    return "429" in str(error or "")


def _is_deadlock(error: Any) -> bool:
    """ERP 500 ``QueryDeadlockError``: lỗi thoáng qua, đọc lại thường được."""
    return "QueryDeadlockError" in str(error or "")


def _row_stamp(row: Optional[Mapping[str, Any]]) -> Tuple[str, ...]:
    if not row:
        return ()
    return tuple(
        str(row.get(key) or "") for key in ("name", "status", "custom_sku", "modified")
    )


def _tree_nodes(root: Any) -> Iterator[Mapping[str, Any]]:
    """Mọi nút dưới ``root``, kể cả nó, đi theo ``subtasks``."""
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, Mapping):
            yield node
            stack.extend(node.get("subtasks") or ())


def _tree_names(payload: Optional[Mapping[str, Any]]) -> set:
    """Tên mọi thẻ có trong cây ``taskFull`` vừa đọc, gốc lẫn con cháu."""
    source: Mapping[str, Any] = payload if isinstance(payload, Mapping) else {}
    root = source.get("root") if isinstance(source.get("root"), Mapping) else source
    return {str(node.get("name") or "").strip() for node in _tree_nodes(root)} - {""}


def _tree_is_cut(payload: Optional[Mapping[str, Any]]) -> bool:
    """Cây ``taskFull`` này có bị ERP cắt không.

    Cùng luật với ``agent_bot.tree_is_cut``.  Chép lại chứ không import:
    ``agent_bot`` import ``sku``, import ngược là vòng.  Bài kiểm trong
    ``test_lan_nhanh_cay_cat`` giữ hai bản khỏi lệch nhau.
    """
    source: Mapping[str, Any] = payload if isinstance(payload, Mapping) else {}
    if source.get("truncated"):
        return True
    try:
        if int(source.get("node_count") or 0) >= int(source.get("max_nodes") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    for node in _tree_nodes(source.get("root") or {}):
        try:
            total = int(node.get("child_total") or 0)
        except (TypeError, ValueError):
            continue
        if total > len(node.get("subtasks") or []):
            return True
    return False


class SkuFastLane:
    """Kéo thẻ sang *Đang làm* thì thẻ có mã trong 30 giây.

    Lượt quét chính của bot đi qua mọi board mỗi 120 giây, nên một thẻ vừa
    kéo sang có thể chờ gần hai phút.  Làn này chỉ làm một việc: đọc lại theo
    nhịp nhanh những bảng đang có thẻ chờ mã, và gọi đúng lượt đánh số của app
    cho cụm ấy.

    Ba nhịp đọc, nhanh dần theo việc đang có trên bảng:

    * bảng **nóng** — còn thẻ gắn bot chưa có mã — đọc lại sau ``interval_s``;
    * bảng **ấm** — vừa có người động vào, thấy qua :func:`board_stamp` — đọc
      lại sau ``warm_s``.  Nhịp nóng chỉ giúp khi làn *đã biết* có thẻ chờ;
      nhịp ấm là để **phát hiện** thẻ mới trên một bảng đang sạch;
    * bảng còn lại đọc lại sau ``rediscover_s``.

    Ba hàng rào giữ nó khỏi ăn hạn mức của bot chính:

    * một ngân sách request chung cho mọi worker (:class:`RequestBudget`);
    * bảng không nóng chỉ được đọc khi còn dư chỗ cho một lượt đánh số, và
      nhiều nhất ``warm_boards`` bảng được hưởng nhịp ấm cùng lúc;
    * gặp 429 thì nghỉ hẳn ``rest_s``.

    Mỗi nhịp đánh số **một** cụm, và đi qua :func:`sku_pass`: không bao giờ
    hai lượt cấp mã cùng lúc.  Cụm cần nhiều request hơn cả trần một phút
    thì làn bỏ qua, để lượt quét chính lo.
    """

    def __init__(
        self,
        config: SkuFastLaneConfig,
        *,
        projects: Callable[[], Iterable[str]],
        board: Callable[[str], List[Mapping[str, Any]]],
        bot_user: Any,
        fill: Callable[[str], Mapping[str, Any]],
        tree: Optional[Callable[[str], Mapping[str, Any]]] = None,
        is_due: Optional[Callable[[Mapping[str, Any], Sequence[str]], bool]] = None,
        paused: Optional[Callable[[str], bool]] = None,
        token_limit: Optional[int] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._projects = projects
        self._board = board
        self._bot_user = bot_user if callable(bot_user) else (lambda: bot_user)
        self._fill = fill
        self._tree = tree
        self._is_due = is_due
        self._paused = paused
        # Làn dựng trực tiếp trong test không có client ERP nên không biết trần
        # token. Đường chạy thật truyền đúng limiter chung vào đây.
        self._token_limit = max(1, int(token_limit)) if token_limit is not None else None
        self._clock = clock
        self.budget = RequestBudget(config.budget_per_minute, clock=clock)
        self._rows: Dict[str, List[Mapping[str, Any]]] = {}
        self._next_read: Dict[str, float] = {}
        # Cụm đã gọi đánh số kể từ lượt đọc bảng gần nhất: dòng cũ còn ghi
        # "chưa có mã", đọc theo nó là đánh số lại cái vừa đánh.
        self._handled: set = set()
        # Cụm gọi rồi mà không ghi được gì: (dấu dòng, lúc đánh dấu).
        self._stuck: Dict[Tuple[str, str], Tuple[Tuple[Tuple[str, ...], ...], float]] = {}
        # Nhãn lý do cho ``_stuck``: cụm đứng chờ vì chưa tới lượt, không phải
        # vì ghi hỏng.  Chỉ giữ dấu dòng — thời hạn chờ vẫn của ``_stuck``.
        self._not_due: Dict[Tuple[str, str], Tuple[Tuple[str, ...], ...]] = {}
        # Thẻ ngoài cây bị cắt đã hỏi cây riêng mà chưa tới lượt: (dấu dòng, tên).
        self._probed: Dict[Tuple[str, str], Tuple[Tuple[Tuple[str, ...], ...], frozenset]] = {}
        # Cụm không bao giờ lọt trần, để lượt quét chính lo: dấu dòng lúc xét.
        self._too_big: Dict[Tuple[str, str], Tuple[Tuple[str, ...], ...]] = {}
        # Cụm đang chờ ngân sách: (dấu dòng, lúc bắt đầu chờ).
        self._waiting_since: Dict[Tuple[str, str], Tuple[Tuple[Tuple[str, ...], ...], float]] = {}
        # Lý do lần gần nhất cụm bị bỏ: chỉ nói lại khi lý do đổi, hoặc sau
        # một phút.  Nhịp là 5 giây nên ghi mọi lần sẽ che mất log hữu ích.
        self._skip_log: Dict[Tuple[str, str], Tuple[str, float]] = {}
        # Bảng vừa gặp deadlock, đã hẹn đọc lại ở nhịp kế.  Lần đọc lại cũng
        # lỗi thì dời như lỗi thường.  Đọc được thì xoá dấu.
        self._deadlock_retry: set = set()
        # Dấu bảng ở lần đọc trước; dấu đổi nghĩa là có người vừa động vào.
        self._stamp: Dict[str, str] = {}
        # Bảng ấm tới lúc nào: tới đó còn được hưởng nhịp ``warm_s``.
        self._warm_until: Dict[str, float] = {}
        self._rest_until = 0.0

    # ── một nhịp ───────────────────────────────────────────────────────

    def tick(self) -> Dict[str, Any]:
        now = self._clock()
        if now < self._rest_until:
            return {"resting": True}
        user = str(self._bot_user() or "").strip()
        read = self._read_boards(now, user)
        if now < self._rest_until:
            return {"resting": True, "read": read}
        outcome = self._fill_one(now, user)
        outcome["read"] = read
        return outcome

    async def run_forever(self) -> None:
        if not self.config.enabled:
            return
        log.info(
            "Làn nhanh SKU bật: nhịp %ss, bảng ấm %ss × %s bảng, "
            "trần %s request/phút, %s worker.",
            self.config.interval_s,
            self.config.warm_s,
            self.config.warm_boards,
            self.config.budget_per_minute,
            self.config.workers,
        )
        try:
            self._log_read_rate_guard()
        except Exception as exc:  # pragma: no cover - chỉ là dòng chẩn đoán
            # Một dòng log không được phép giết cả làn nhanh.
            log.warning("Làn nhanh SKU không tự kiểm được nhịp đọc: %s", exc)
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception as exc:
                log.exception("Làn nhanh SKU hỏng một nhịp: %s", exc)
            await asyncio.sleep(self.config.tick_s)

    def _log_read_rate_guard(self) -> None:
        """Nói rõ nhịp đọc nền trước khi làn nhanh gửi request đầu tiên."""
        projects = [str(item).strip() for item in (self._projects() or ()) if str(item).strip()]
        total = len(projects)
        warm = min(total, max(0, int(self.config.warm_boards)))
        cold = total - warm
        reads_per_minute = (
            warm * (60.0 / self.config.warm_s)
            + cold * (60.0 / self.config.rediscover_s)
        )
        if self._token_limit is None:
            log.info(
                "Làn nhanh SKU tự kiểm: %d bảng (%d ấm, %d còn lại), đọc ước %.1f/phút; "
                "chưa có trần token để so.",
                total,
                warm,
                cold,
                reads_per_minute,
            )
        elif reads_per_minute > self._token_limit:
            # Không kẹp ngầm: người vận hành phải thấy cấu hình sai ngay từ
            # lúc mở log. Limiter token chung vẫn là chốt cuối chống bão 429.
            log.warning(
                "Làn nhanh SKU tự kiểm: %d bảng (%d ấm, %d còn lại), đọc ước %.1f/phút "
                "VƯỢT trần token %d/phút.",
                total,
                warm,
                cold,
                reads_per_minute,
                self._token_limit,
            )
        else:
            log.info(
                "Làn nhanh SKU tự kiểm: %d bảng (%d ấm, %d còn lại), đọc ước %.1f/phút "
                "trong trần token %d/phút.",
                total,
                warm,
                cold,
                reads_per_minute,
                self._token_limit,
            )

    # ── đọc bảng ───────────────────────────────────────────────────────

    def _is_hot(self, project: str, user: str) -> bool:
        rows = self._rows.get(project)
        return rows is not None and board_is_hot(rows, user)

    def _read_one(self, project: str) -> Tuple[Optional[List[Mapping[str, Any]]], Optional[Exception]]:
        try:
            return list(self._board(project) or []), None
        except Exception as exc:
            return None, exc

    def _warm_projects(self, now: float) -> set:
        """Bảng được hưởng nhịp ấm lúc này, nhiều nhất ``warm_boards`` cái.

        Quá số ấy thì giữ những bảng có hạn ấm còn lại dài nhất — tức bảng vừa
        có người động vào gần đây nhất.
        """
        limit = max(0, int(self.config.warm_boards))
        if limit <= 0:
            return set()
        live = sorted(
            ((until, item) for item, until in self._warm_until.items() if until > now),
            reverse=True,
        )
        return {item for _, item in live[:limit]}

    def _read_boards(self, now: float, user: str) -> List[str]:
        projects = [str(item).strip() for item in (self._projects() or ()) if str(item).strip()]
        for gone in [item for item in self._rows if item not in projects]:
            self._rows.pop(gone, None)
            self._next_read.pop(gone, None)
        for gone in [item for item in self._warm_until if item not in projects]:
            self._warm_until.pop(gone, None)
        for gone in [item for item in self._stamp if item not in projects]:
            self._stamp.pop(gone, None)
        # Bảng lỗi ngay lần đọc đầu không có trong ``_rows``: dọn riêng.
        self._deadlock_retry.intersection_update(projects)
        due = [item for item in projects if self._next_read.get(item, 0.0) <= now]
        # Bảng nóng đi trước — đó là chỗ có người vừa kéo thẻ; rồi tới bảng ấm.
        warm = self._warm_projects(now)
        due.sort(
            key=lambda item: 0 if self._is_hot(item, user) else (1 if item in warm else 2)
        )
        picked: List[str] = []
        for project in due:
            if self._is_hot(project, user):
                keep = 0
            elif project in warm and self._next_read.get(project, 0.0) > now - self.config.rediscover_s:
                # Lượt ngó thêm vì bảng ấm: chỉ khi còn dư chỗ cho trọn một
                # lượt đánh số.  Tới hạn 300 giây thì đọc như bảng thường.
                keep = _LANE_WARM_RESERVE
            else:
                keep = _LANE_RESERVE
            if self.budget.take(1, keep=keep):
                picked.append(project)
        if not picked:
            return []
        with ThreadPoolExecutor(max_workers=max(1, min(self.config.workers, len(picked)))) as pool:
            results = list(pool.map(self._read_one, picked))
        # Bảng đọc được lượt này: chỉ chúng mới hẹn lại theo nhịp nóng/ấm/nguội,
        # bảng lỗi đã tự hẹn ở nhánh lỗi.
        done: List[str] = []
        for project, (rows, error) in zip(picked, results):
            if error is not None:
                if _is_rate_limited(error):
                    self._rest(now)
                    self._next_read[project] = now + self.config.rest_s
                elif _is_deadlock(error) and project not in self._deadlock_retry:
                    # Đang nghỉ 429 thì lần đọc lại chờ hết nghỉ.
                    self._deadlock_retry.add(project)
                    log.warning(
                        "Làn nhanh SKU không đọc được bảng %s: %s (đọc lại ở nhịp kế)", project, error
                    )
                    self._next_read[project] = now + self.config.interval_s
                else:
                    # Hết lượt đọc lại: lần deadlock sau lại được một lượt.
                    self._deadlock_retry.discard(project)
                    log.warning(
                        "Làn nhanh SKU không đọc được bảng %s: %s (dời %d giây)",
                        project,
                        error,
                        int(self.config.rediscover_s),
                    )
                    self._next_read[project] = now + self.config.rediscover_s
                continue
            self._deadlock_retry.discard(project)
            self._rows[project] = rows or []
            self._handled = {key for key in self._handled if key[0] != project}
            stamp = board_stamp(self._rows[project])
            before = self._stamp.get(project)
            self._stamp[project] = stamp
            if before is not None and before != stamp:
                # Có người vừa động vào bảng: giữ ấm để bắt kịp thẻ kế tiếp.
                self._warm_until[project] = now + self.config.warm_for_s
            done.append(project)
        # Hạn ấm vừa đổi ở trên: chọn lại rồi mới hẹn lượt đọc sau.
        warm = self._warm_projects(now)
        for project in done:
            hot = board_is_hot(self._rows[project], user)
            delay = self.config.interval_s if hot else self.config.rediscover_s
            if project in warm:
                # Bảng nóng mà cũng ấm thì lấy nhịp nhanh hơn: thẻ đang chờ mã
                # không được ngó thưa hơn bảng chỉ vừa động đậy.
                delay = min(delay, self.config.warm_s)
            self._next_read[project] = now + delay
        return picked

    # ── đánh số ────────────────────────────────────────────────────────

    def _note_skip(self, now: float, key: Tuple[str, str], reason: str, detail: str) -> None:
        previous = self._skip_log.get(key)
        if previous is None or previous[0] != reason or now - previous[1] >= 60.0:
            log.info("Làn nhanh SKU chưa đánh số cụm %s (%s): %s.", key[1], key[0], detail)
            self._skip_log[key] = (reason, now)

    def _clear_skip(self, key: Tuple[str, str]) -> None:
        self._skip_log.pop(key, None)

    def _park(
        self,
        key: Tuple[str, str],
        stamp: Tuple[Tuple[str, ...], ...],
        now: float,
        *,
        not_due: bool = False,
    ) -> None:
        """Cho cụm đứng chờ tới khi dòng bảng đổi hoặc hết ``rediscover_s``.

        ``not_due`` chỉ đổi **lý do** ghi log, không đổi thời hạn chờ: hàng rào
        đầu nhịp phải nói đúng một chuỗi với nhánh kết quả.  Hai lý do thay
        phiên nhau là ``_note_skip`` hết dedup, log ngập cả chục dòng mỗi phút
        cho một cụm nằm yên.
        """
        self._stuck[key] = (stamp, now)
        if not_due:
            self._not_due[key] = stamp
        else:
            self._not_due.pop(key, None)

    def _unpark(self, key: Tuple[str, str]) -> None:
        self._stuck.pop(key, None)
        self._not_due.pop(key, None)

    def _candidates(
        self, user: str
    ) -> Iterator[Tuple[str, str, List[str], Tuple[Tuple[str, ...], ...], int, List[str]]]:
        for project, rows in self._rows.items():
            by_name = _rows_by_name(rows)
            clusters: Dict[str, List[str]] = {
                root: list(ids) for root, ids in hot_clusters(rows, user).items()
            }
            # Cụm không còn thẻ nào chờ mã vẫn có thể còn một cái tên lệch: thẻ
            # vừa bị kéo về *Cần làm* đang lấy mã làm tên.  ``hot_clusters``
            # không thấy nó — nó đã có mã — nên phải hỏi riêng, không thì luật
            # trả tên viết xong vẫn nằm im.
            fixes: Dict[str, List[str]] = {}
            for source in (restore_clusters(rows, user), repair_clusters(rows, user)):
                for root, names in source.items():
                    clusters.setdefault(root, [])
                    fixes.setdefault(root, []).extend(names)
            for root, ids in clusters.items():
                names = fixes.get(root, [])
                stamp = tuple(_row_stamp(by_name.get(name)) for name in (root, *ids, *names))
                # Thẻ trong cụm có mã mà tên khác mã: lượt đánh số phải đọc cây
                # của nó và chữa tên.  Đếm từ dòng bảng, không tốn request.
                wrong = 0
                for name, row in by_name.items():
                    code = str(row.get("custom_sku") or "").strip()
                    if (
                        code
                        and str(row.get("subject") or "").strip() != code
                        and root in _ancestors(name, by_name)
                    ):
                        wrong += 1
                # Thẻ chờ trả tên chưa nằm trong ``wrong``: tên nó đang *đúng
                # bằng* mã.  Giá thì vẫn thế — một lượt đọc thẻ, một lượt đổi tên.
                wrong += sum(
                    1
                    for name in names
                    if str((by_name.get(name) or {}).get("subject") or "").strip()
                    == str((by_name.get(name) or {}).get("custom_sku") or "").strip()
                )
                yield project, root, ids, stamp, wrong, names

    def _is_paused(self, root: str, ids: Sequence[str]) -> bool:
        if self._paused is None:
            return False
        return any(self._paused(task) for task in (root, *ids))

    def _fill_one(self, now: float, user: str) -> Dict[str, Any]:
        trees = 1 if self._tree is not None and self._is_due is not None else 0
        candidates = list(self._candidates(user))
        live = {(project, root) for project, root, *_ in candidates}
        for gone in [key for key in self._waiting_since if key not in live]:
            # Cụm không còn chờ mã: đã có người đánh số, hoặc thẻ bị kéo đi.
            self._waiting_since.pop(gone, None)
        for gone in [key for key in self._skip_log if key not in live]:
            self._skip_log.pop(gone, None)
        for gone in [key for key in self._not_due if key not in live]:
            self._not_due.pop(gone, None)
        # Lý do gần nhất khiến một cụm không được đánh số.  Nhịp đi tiếp qua
        # cụm kế, nhưng báo cáo của nhịp vẫn phải nói ra điều gì đã xảy ra —
        # ``{}`` đọc y hệt "không có cụm nào chờ mã".
        skipped: Dict[str, Any] = {}
        for project, root, ids, stamp, wrong, fixes in candidates:
            key = (project, root)
            if key in self._handled:
                self._clear_skip(key)
                continue
            if self._too_big.get(key) == stamp:
                self._note_skip(now, key, "too_big", "cụm quá lớn so với trần request")
                continue
            stuck = self._stuck.get(key)
            if stuck is not None:
                if stuck[0] == stamp and now - stuck[1] < self.config.rediscover_s:
                    if self._not_due.get(key) == stamp:
                        self._note_skip(now, key, "not_due", NOT_DUE_DETAIL)
                    else:
                        self._note_skip(now, key, "stuck", "cụm chưa đổi sau lượt không ghi được")
                    continue
                self._unpark(key)
            if self._is_paused(root, [*ids, *fixes]):
                continue
            if self._never_fits(key, ids, stamp, trees, wrong=wrong):
                self._note_skip(now, key, "too_big", "cụm quá lớn so với trần request")
                continue
            outcome = self._fill_cluster(now, key, ids, stamp, wrong=wrong, fixes=fixes)
            if "too_big" in outcome:
                # Cây gốc bị cắt: đọc xong mới biết cụm cần thêm một cây.
                self._note_skip(now, key, "too_big", "cụm quá lớn so với trần request")
                continue
            if "busy" in outcome:
                self._note_skip(now, key, "busy", "khoá lượt đánh số đang bận")
                return outcome
            # Ba nhánh dưới là "cụm **này** không có việc", không phải "cả làn
            # hết việc".  Dừng nhịp ở đây là để một cụm nghỉ dài hạn — cụm bị
            # 👎 hết ảnh nằm đó hàng ngày — chắn mọi cụm đứng sau nó,
            # vĩnh viễn và không một dòng log.  Tối 13/09/2026 trên hvg-pc đúng
            # như thế: ``TASK-2026-00202`` giữ cả 6/6 nhịp đo được, thẻ vừa kéo
            # ở PROJ-0087 không bao giờ tới lượt.  Xét cụm kế; ngân sách vẫn là
            # thứ chặn, vì mỗi lượt đọc cây đều phải xin chỗ trước.
            if "not_due" in outcome:
                self._note_skip(now, key, "not_due", NOT_DUE_DETAIL)
                skipped = outcome
                continue
            if "probing" in outcome:
                self._note_skip(now, key, "probing", "đang dò thẻ nằm ngoài cây bị cắt")
                skipped = outcome
                continue
            if "error" in outcome:
                # Gặp 429 thì ``_failed`` đã cho cả làn nghỉ: xét tiếp là bắn
                # thêm request vào đúng lúc ERP vừa bảo thôi.  Lỗi khác — như
                # ``QueryDeadlockError`` của một cụm — là việc của cụm ấy.
                if now < self._rest_until:
                    return outcome
                skipped = outcome
                continue
            if "waiting" not in outcome:
                self._waiting_since.pop(key, None)
                self._clear_skip(key)
                return outcome
            self._note_skip(now, key, "waiting", "đang chờ ngân sách request")
            # Chờ ngân sách trọn một cửa sổ mà dấu dòng không đổi: phút nào
            # cũng thiếu chỗ, chờ tiếp là chắn mọi cụm phía sau.  Nhường lượt
            # quét chính như cụm quá lớn, rồi xét cụm kế.
            since = self._waiting_since.get(key)
            if since is None or since[0] != stamp:
                since = (stamp, now)
                self._waiting_since[key] = since
            if now - since[1] < self.budget.window_s:
                return outcome
            self._waiting_since.pop(key, None)
            self._too_big[key] = stamp
            log.info(
                "Làn nhanh SKU nhường cụm %s (%s) cho lượt quét chính: chờ ngân sách %.0f giây vẫn thiếu chỗ, trần %s/phút.",
                root,
                project,
                now - since[1],
                self.budget.limit,
            )
        return skipped

    def _never_fits(
        self,
        key: Tuple[str, str],
        ids: Sequence[str],
        stamp: Tuple[Tuple[str, ...], ...],
        trees: int,
        wrong: int = 0,
        cut_new: int = 0,
    ) -> bool:
        """Cụm cần nhiều request hơn trần một phút: chờ bao lâu cũng không lọt.

        Tính cả lượt đọc bảng: bảng có cụm chờ mã là bảng nóng, nhịp nào cũng
        đọc lại trước khi đánh số.  Đứng chờ cụm ấy là chắn mọi cụm phía sau
        cho tới khi lượt quét chính đánh số nó.  Ghi log một lần mỗi dấu
        dòng; dòng đổi thì xét lại.
        """
        need = 1 + trees + fill_cost(len(ids), cut_new, wrong)
        if need <= self.budget.limit:
            return False
        self._too_big[key] = stamp
        log.info(
            "Làn nhanh SKU để lượt quét chính đánh số cụm %s (%s): cần ít nhất %s request, trần %s/phút.",
            key[1],
            key[0],
            need,
            self.budget.limit,
        )
        return True

    def _fill_cluster(
        self,
        now: float,
        key: Tuple[str, str],
        ids: List[str],
        stamp: Tuple[Tuple[str, ...], ...],
        wrong: int = 0,
        fixes: Sequence[str] = (),
    ) -> Dict[str, Any]:
        project, root = key
        # Chưa đọc cây thì chưa biết thẻ nào nằm ngoài cây: tính như cây trọn.
        cost = fill_cost(len(ids), 0, wrong)
        with sku_pass(wait=True, timeout=self.config.lock_wait_s, priority=True) as got:
            if not got:
                # Lượt nền chưa tới mốc bàn giao.  Nhịp sau thử lại.
                return {"busy": True}
            if self._tree is not None and self._is_due is not None:
                if not self.budget.take(1, keep=cost):
                    return {"waiting": root}
                try:
                    payload = self._tree(root)
                except Exception as exc:
                    return self._failed(now, key, stamp, exc)
                # Hỏi cả thẻ chờ chữa tên: cụm chỉ có mỗi việc ấy thì không thẻ
                # nào "chờ mã", và cổng sẽ lắc đúng cái cụm vừa mở ra cho nó.
                due = self._is_due(payload, [*ids, *fixes])
                outside: List[str] = []
                if _tree_is_cut(payload):
                    seen = _tree_names(payload)
                    outside = [name for name in ids if name not in seen]
                if outside:
                    # Thẻ mới ngoài cây: lượt đánh số đọc ``taskFull`` từng thẻ,
                    # kể cả khi cụm đã tới lượt.  Tính lại giá.  Giá mới không
                    # bao giờ lọt trần thì nhường lượt quét chính: đứng chờ ngân
                    # sách là chắn mọi cụm phía sau.
                    cost = fill_cost(len(ids), len(outside), wrong)
                    if self._never_fits(key, ids, stamp, trees=1, wrong=wrong, cut_new=len(outside)):
                        return {"too_big": root}
                if outside and not due:
                    # ERP cắt ``taskFull`` ở 60 nút.  Thẻ vừa kéo sang nằm ngoài
                    # phần nhận được thì cây gốc không bao giờ nói nó tới lượt —
                    # cụm 04628 chưa bao giờ được làn này đánh số.  Đọc cây của
                    # chính thẻ ấy, một thẻ mỗi nhịp, để cụm cả trăm thẻ không
                    # ăn hết trần của token.  Cây không bị cắt thì thẻ vắng mặt
                    # là dòng bảng lệch, đọc thêm cũng không biết gì hơn.
                    probed = self._probed.get(key)
                    tried = probed[1] if probed is not None and probed[0] == stamp else frozenset()
                    left = [name for name in outside if name not in tried]
                    if left:
                        if self._never_fits(key, ids, stamp, trees=2, wrong=wrong, cut_new=len(outside)):
                            return {"too_big": root}
                        if not self.budget.take(1, keep=cost):
                            return {"waiting": root}
                        try:
                            payload = self._tree(left[0])
                        except Exception as exc:
                            if _is_rate_limited(exc):
                                return self._failed(now, key, stamp, exc)
                            log.warning(
                                "Làn nhanh SKU không đọc được cây thẻ %s (cụm %s): %s", left[0], root, exc
                            )
                            payload = None
                        due = payload is not None and self._is_due(payload, left[:1])
                        if not due:
                            # Thẻ này chưa tới lượt chưa phải cả cụm chưa tới lượt:
                            # nhịp sau hỏi thẻ kế tiếp.  Dòng bảng đổi thì dấu đổi,
                            # sổ này tự bỏ, hỏi lại từ đầu.
                            self._probed[key] = (stamp, tried | {left[0]})
                            if len(left) > 1:
                                return {"probing": root}
                if not due:
                    # Cụm chưa có gì để đánh số — không ảnh, hoặc 👎 hết, hoặc
                    # mọi thẻ đã có mã: việc của lượt quét chính.
                    self._probed.pop(key, None)
                    self._park(key, stamp, now, not_due=True)
                    return {"not_due": root}
            if not self.budget.take(cost):
                return {"waiting": root}
            self._handled.add(key)
            self._probed.pop(key, None)
            log.info(
                "Làn nhanh SKU đánh số cụm %s (%s): %s.",
                root,
                project,
                ", ".join([*ids, *fixes]) or "chữa tên",
            )
            try:
                result = self._fill(root)
            except Exception as exc:
                return self._failed(now, key, stamp, exc)
        result = result if isinstance(result, Mapping) else {}
        written = list(result.get("written") or [])
        failed = list(result.get("failed") or [])
        # Chữa tên cũng là ghi.  Cụm chỉ có mỗi việc ấy thì ``written`` rỗng mà
        # thẻ đã mang tên mới thật: coi là "chưa ghi được" là nói sai trong log
        # rồi cho cụm nghỉ oan tới khi dòng bảng đổi.
        renamed = list(result.get("renamed") or [])
        if any(
            _is_rate_limited(item.get("error") if isinstance(item, Mapping) else item)
            for item in failed
        ):
            self._rest(now)
        elif not written and not renamed:
            self._park(key, stamp, now)
            self._note_skip(now, key, "stuck", "cụm chưa ghi được, chờ dòng đổi")
        else:
            self._clear_skip(key)
        return {"filled": root, "written": len(written), "failed": len(failed)}

    def _failed(
        self,
        now: float,
        key: Tuple[str, str],
        stamp: Tuple[Tuple[str, ...], ...],
        error: Exception,
    ) -> Dict[str, Any]:
        if _is_rate_limited(error):
            self._rest(now)
        else:
            log.warning("Làn nhanh SKU không đánh số được cụm %s: %s", key[1], error)
            self._park(key, stamp, now)
        return {"error": str(error), "filled": ""}

    def _rest(self, now: float) -> None:
        """Gặp 429: nghỉ hẳn ``rest_s``.  Một dòng log mỗi lần vào nghỉ.

        Nhiều bảng cùng 429 trong một nhịp vẫn là một lần nghỉ.
        """
        resting = now < self._rest_until
        self._rest_until = max(self._rest_until, now + self.config.rest_s)
        if not resting:
            # Đồng hồ của làn là ``monotonic``: đổi ra giờ máy cho người đọc log.
            until = time.localtime(time.time() + self._rest_until - now)
            log.warning("Làn nhanh SKU bị 429, nghỉ tới %s.", time.strftime("%H:%M:%S", until))
