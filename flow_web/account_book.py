"""Sổ tay tài khoản: cái tag ``acc32`` trên thẻ nghĩa là shop nào, máy nào.

Người làm listing viết bài bằng tay.  Thứ duy nhất họ khai cho máy là **tài
khoản** — gõ ``acc: acc32`` vào khối Thuộc tính, hoặc dán cái nhãn ``acc32``
lên thẻ.  Từ chừng ấy chữ, máy phải biết bài này lên shop nào, chạy trên máy
nào, và tên shop viết ra sao để người đọc kiểm lại được.

Trước đây chỗ ấy chỉ có quy ước đặt tên: ``acc32`` chạy trên máy có số 32
(:func:`flow_web.erp_meta.machine_for_account`).  Quy ước đúng cho tới cái
tài khoản đầu tiên không theo nó — một shop tên ``havi-home``, hay hai tài
khoản dùng chung một máy — và lúc ấy không có chỗ nào để ghi sự thật xuống.
Quyển sổ này là chỗ đó.

Nó cố ý giống hệt bảng SKU (:class:`flow_web.sku.ProductBook`): cùng cách gộp
nhiều nguồn, cùng cách đọc một sheet do người vận hành tự đặt tên cột, cùng
kiểu "thiếu dòng thì đỡ tạm chứ không gãy".  Hai quyển sổ đứng cạnh nhau
trong cùng một màn hình cấu hình thì phải cư xử giống nhau.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from .erp_meta import normalize_token
# Cùng một hàm so tên cột với bảng SKU, không phải bản chép lại: hai quyển sổ
# đọc chung một sheet của cùng một người, nên "cột này tên là gì" phải là một
# câu hỏi có đúng một câu trả lời trong cả app.
from .sku import normalize_column


#: Tên cột sheet cho từng ô của quyển sổ.  Người vận hành đặt tên cột theo
#: thói quen của họ, không theo hằng số trong mã nguồn — nên mỗi ô nhận nhiều
#: cách gọi, và cách gọi nào đứng trước thì được tin trước.
BOOK_ACCOUNT_COLUMNS = ("acc", "account", "accountid", "acc_id", "taikhoan", "tk", "shopid")
BOOK_SHOP_COLUMNS = ("shop", "shopname", "tenshop", "store", "etsyshop", "ten")
BOOK_MACHINE_COLUMNS = ("machine", "machineid", "may", "pc", "vps", "maychay")
BOOK_NOTE_COLUMNS = ("note", "ghichu", "notes", "mota", "description")


@dataclass(frozen=True)
class Account:
    """Một dòng của quyển sổ."""

    account_id: str
    shop: str = ""
    machine: str = ""
    note: str = ""

    def as_dict(self) -> Dict[str, str]:
        return {
            "account_id": self.account_id,
            "shop": self.shop,
            "machine": self.machine,
            "note": self.note,
        }

    @property
    def label(self) -> str:
        """Cách gọi tài khoản này cho người đọc: ``acc32 (Havi Home)``."""
        return f"{self.account_id} ({self.shop})" if self.shop else self.account_id


@dataclass(frozen=True)
class AccountBook:
    """Cả quyển sổ, tra theo mã tài khoản đã chuẩn hoá."""

    entries: Dict[str, Account] = field(default_factory=dict)

    # ── dựng sổ ────────────────────────────────────────────────────────

    @classmethod
    def from_mapping(cls, values: Optional[Mapping[str, Any]]) -> "AccountBook":
        """``{"acc32": {"shop": …}}`` hoặc ``{"acc32": "etsy-vn32"}``.

        Dạng chuỗi được nhận vì đó là thứ ngắn nhất người ta gõ khi cả thông
        tin họ có chỉ là "tài khoản này chạy ở máy kia".
        """
        entries: Dict[str, Account] = {}
        for key, value in (values or {}).items():
            account_id = normalize_token(key)
            if not account_id:
                continue
            if isinstance(value, Mapping):
                fields = {normalize_column(name): item for name, item in value.items()}
                shop = _first(fields, BOOK_SHOP_COLUMNS)
                machine = normalize_token(_first(fields, BOOK_MACHINE_COLUMNS))
                note = _first(fields, BOOK_NOTE_COLUMNS)
            else:
                shop, machine, note = "", normalize_token(value), ""
            entries[account_id] = Account(account_id, shop=shop, machine=machine, note=note)
        return cls(entries=entries)

    @classmethod
    def from_rows(cls, rows: Optional[Iterable[Mapping[str, Any]]]) -> "AccountBook":
        """Đọc sổ từ các dòng sheet đã parse (``{cột: giá trị}``)."""
        entries: Dict[str, Account] = {}
        for row in rows or ():
            if not isinstance(row, Mapping):
                continue
            columns = {normalize_column(key): value for key, value in row.items()}
            account_id = normalize_token(_first(columns, BOOK_ACCOUNT_COLUMNS))
            if not account_id:
                continue
            entries[account_id] = Account(
                account_id,
                shop=_first(columns, BOOK_SHOP_COLUMNS),
                machine=normalize_token(_first(columns, BOOK_MACHINE_COLUMNS)),
                note=_first(columns, BOOK_NOTE_COLUMNS),
            )
        return cls(entries=entries)

    def merged(self, other: Optional["AccountBook"]) -> "AccountBook":
        """Sổ này chồng lên sổ kia; dòng của ``self`` thắng."""
        if other is None:
            return self
        entries = dict(other.entries)
        entries.update(self.entries)
        return AccountBook(entries=entries)

    # ── tra sổ ─────────────────────────────────────────────────────────

    def lookup(self, account_id: Any) -> Optional[Account]:
        """Dòng của một tài khoản, hoặc ``None`` khi sổ chưa có nó."""
        key = normalize_token(account_id)
        return self.entries.get(key) if key else None

    def machine_for(self, account_id: Any) -> str:
        """Máy đã ghi trong sổ cho tài khoản này, hoặc ``""``."""
        found = self.lookup(account_id)
        return found.machine if found else ""

    def knows(self, account_id: Any) -> bool:
        return self.lookup(account_id) is not None

    @property
    def account_ids(self) -> Tuple[str, ...]:
        """Mọi tài khoản sổ biết, để :func:`erp_meta.account_from_labels` đọc
        được cái nhãn ``havi-home`` vốn không theo quy ước ``acc`` + số."""
        return tuple(self.entries)

    @property
    def account_machines(self) -> Dict[str, str]:
        """Bảng ``{tài khoản: máy}`` đúng dạng :func:`erp_meta.resolve_routing`
        nhận, để quyển sổ cắm thẳng vào đường định tuyến sẵn có."""
        return {key: item.machine for key, item in self.entries.items() if item.machine}

    def __bool__(self) -> bool:
        return bool(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def as_dict(self) -> Dict[str, Dict[str, str]]:
        return {key: item.as_dict() for key, item in self.entries.items()}


def _first(columns: Mapping[str, Any], names: Iterable[str]) -> str:
    """Ô đầu tiên có chữ trong số những tên cột được chấp nhận."""
    for name in names:
        text = str(columns.get(name) or "").strip()
        if text:
            return text
    return ""
