"""Luật cột: cái gì đẩy một thẻ từ *Cần làm* sang *Hoàn thành*.

Bảng có năm cột.  ERP lưu tên tiếng Anh, người dùng nhìn thấy tên tiếng Việt::

    Open            Cần làm       máy làm ảnh ở đây
    Working         Đang làm      người đã chốt bộ ảnh; máy điền mã SKU
    Pending Review  Đang review   ảnh và mã đã xong; tới lượt viết listing
    Completed       Hoàn thành    listing đã lên shop
    Cancelled       Đã huỷ        người bỏ thẻ

Trước đây phần mềm nhảy cóc: vừa đăng ảnh lên cho người duyệt là đẩy thẻ sang
*Đang review*, rồi ghi ảnh đã duyệt xong là đẩy thẳng sang *Hoàn thành*.  Hai
cột giữa vì thế không nói lên điều gì — *Đang review* hoá ra nghĩa là "đang
chờ người bấm 👍", còn *Đang làm* thì chẳng bao giờ có thẻ nào rơi vào.  Bảng
ấy đọc ngược hẳn với cách nhóm đang dùng nó.

Ở đây mỗi lần chuyển cột đánh dấu một việc **đã xong**, không phải một việc
vừa bắt đầu:

* *Cần làm* → *Đang làm*: người duyệt đã chốt bộ ảnh — không còn ảnh nào chờ
  👍/👎 và còn ít nhất một ảnh được giữ.
* *Đang làm* → *Đang review*: thẻ đã mang mã SKU.
* *Đang review* → *Hoàn thành*: listing đã lên shop.

Không luật nào kéo thẻ lùi lại, và hai cột đóng là điểm dừng: người đã đóng
thẻ thì máy không mở nó ra lần nữa.

Chỗ này cố ý không biết gì về ERP, về HTTP hay về bot.  Nó nhận một nắm sự
kiện đọc được trên thẻ và trả lời đúng một câu — nên luật cột kiểm chứng được
mà không cần bảng thật, và hai đường gọi nó (``service.py`` khi tự chạy ảnh,
``agent_bot.py`` khi quét bảng) không thể lệch luật của nhau.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple


COL_TODO = "Open"
COL_DOING = "Working"
COL_REVIEW = "Pending Review"
COL_DONE = "Completed"
COL_CANCELLED = "Cancelled"

#: Tên tiếng Việt của từng cột.  Bot nói chuyện trên thẻ bằng những tên này,
#: vì đó là chữ người đọc đang nhìn thấy trên bảng — trả lời "đã chuyển sang
#: Pending Review" bắt họ phải tự dịch.
COLUMN_NAMES: Dict[str, str] = {
    COL_TODO: "Cần làm",
    COL_DOING: "Đang làm",
    COL_REVIEW: "Đang review",
    COL_DONE: "Hoàn thành",
    COL_CANCELLED: "Đã huỷ",
}

#: Thứ tự các cột trên bảng.  Dùng để cấm đi lùi.
ORDER: Tuple[str, ...] = (COL_TODO, COL_DOING, COL_REVIEW, COL_DONE)

#: Cột mà máy không đụng vào nữa.
CLOSED: Tuple[str, ...] = (COL_DONE, COL_CANCELLED)


def _compact(value: Any) -> str:
    """Tên cột nén lại để so khớp: bỏ dấu, bỏ ký tự thừa, còn chữ thường.

    ``đ`` đổi thành ``d`` *trước* khi bỏ dấu, vì ``unicodedata`` không tách
    được nó — nó là một chữ cái riêng chứ không phải ``d`` cộng dấu.  Thiếu
    bước ấy thì ``"Đang làm"`` nén thành ``"anglam"``.
    """
    text = str(value or "").strip().lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in text if ch.isascii() and ch.isalnum())


_ALIASES: Dict[str, str] = {}
for _status, _label in COLUMN_NAMES.items():
    _ALIASES[_compact(_status)] = _status
    _ALIASES[_compact(_label)] = _status
# Vài cách gọi khác đã thấy trên bảng thật và trong lời người dùng.
_ALIASES.update(
    {
        "todo": COL_TODO,
        "canlam": COL_TODO,
        "danglam": COL_DOING,
        "inprogress": COL_DOING,
        "doing": COL_DOING,
        "review": COL_REVIEW,
        "dangreview": COL_REVIEW,
        "choduyet": COL_REVIEW,
        "done": COL_DONE,
        "hoanthanh": COL_DONE,
        "xong": COL_DONE,
        "dahuy": COL_CANCELLED,
        "huy": COL_CANCELLED,
    }
)


def normalize_status(value: Any) -> str:
    """Tên cột ERP chuẩn của một chuỗi bất kỳ, hoặc ``""`` nếu không nhận ra.

    Không nhận ra thì trả rỗng chứ không đoán: một cột lạ nghĩa là bảng này
    không phải bảng luật ở đây mô tả, và nước đi đúng khi ấy là đứng im.
    """
    return _ALIASES.get(_compact(value), "")


def column_name(status: Any) -> str:
    """Tên tiếng Việt để nói với người, ví dụ ``"Đang làm"``."""
    canonical = normalize_status(status)
    return COLUMN_NAMES.get(canonical, str(status or "").strip())


#: Cách gọi được chấp nhận cho từng cột, viết cho *người đọc* chứ không để so
#: khớp — bảng so khớp là :data:`_ALIASES`.  Hai chỗ này phải đi cùng nhau;
#: ``test_pipeline`` giữ chúng khỏi lệch nhau.
COLUMN_HINTS: Tuple[Tuple[str, str], ...] = (
    (COLUMN_NAMES[COL_TODO], "Open / To do / Cần làm"),
    (COLUMN_NAMES[COL_DOING], "Working / Doing / In progress / Đang làm"),
    (COLUMN_NAMES[COL_REVIEW], "Pending Review / Review / Chờ duyệt / Đang review"),
    (COLUMN_NAMES[COL_DONE], "Completed / Done / Xong / Hoàn thành"),
    (COLUMN_NAMES[COL_CANCELLED], "Cancelled / Huỷ / Đã huỷ"),
)


def unknown_columns(names: Iterable[Any]) -> Tuple[str, ...]:
    """Những tên cột luật ở đây không nhận ra, giữ **nguyên văn** như bảng đặt.

    Giữ nguyên văn chứ không nén lại: người đọc phải dò được chữ này trên bảng
    của họ, mà bản nén (``"1canlam"``) thì không có trên bảng nào cả.

    Cột trống tên bị bỏ qua — ERP thỉnh thoảng trả về một cột không tên, và
    than phiền về nó chỉ làm người đọc đi tìm một thứ không tồn tại.  Trùng
    tên gộp làm một, giữ thứ tự bảng đang bày.
    """
    found: List[str] = []
    for value in names:
        label = str(value or "").strip()
        if not label or normalize_status(label):
            continue
        if label not in found:
            found.append(label)
    return tuple(found)


def column_help(unknown: Sequence[Any] = ()) -> str:
    """Câu nói với người khi bảng đặt tên cột lạ.

    Đây là chỗ *duy nhất* soạn câu ấy: bot nói nó trên thẻ, log ghi lại nó, và
    hai bản không được phép khác nhau — người đọc log rồi mở thẻ ra mà thấy
    hai lời khuyên khác nhau thì không biết tin bên nào.
    """
    lines = [
        "Luật cột của Flow v2 không nhận ra tên cột {}, nên bot không tự đẩy "
        "thẻ đi đâu cả — ảnh vẫn được tạo và vẫn đăng lên chờ duyệt, nhưng thẻ "
        "sẽ nằm yên tại chỗ cho tới khi có người kéo tay.".format(
            ", ".join(f"“{name}”" for name in unknown) or "của bảng này"
        ),
        "Đổi tên cột về một trong các cách gọi sau là bot chạy tiếp ngay ở lượt quét sau:",
    ]
    lines.extend(f"• {label} — {aliases}" for label, aliases in COLUMN_HINTS)
    return "\n".join(lines)


def sku_missing_help(product: Any) -> str:
    """Câu nói với người khi bảng SKU chưa có dòng cho món hàng này.

    Cùng lý do với :func:`column_help`: soạn ở đúng một chỗ, để lời trên thẻ
    và lời trong log không bao giờ lệch nhau.

    Bot không đoán mã nữa.  Đoán theo chữ cái đầu từng ra ``PNO`` cho
    ``Punch Needle Ornament``, trong khi xưởng gọi món ấy là ``OL``.  Nên câu
    này chỉ nói thẻ đang trống mã vì sao, và sửa ở đâu.
    """
    ten = str(product or "").strip() or "(thẻ chưa khai product)"
    return "\n".join(
        [
            f"Chưa có mã trong bảng SKU cho “{ten}”, nên bot để trống mã các thẻ của món này.",
            "Ảnh vẫn chạy bình thường; chỉ phần mã SKU là chờ.",
            f"Sửa: thêm một dòng “{ten}” kèm mã đúng vào bảng SKU. Lượt quét sau "
            "bot đọc lại bảng và cấp mã, không phải khởi động lại gì cả.",
        ]
    )


@dataclass(frozen=True)
class CardStage:
    """Những gì đọc được trên một thẻ, đủ để biết nó nên đứng ở cột nào.

    Cố tình chỉ là số và cờ: người gọi đã đọc ERP rồi, chỗ này không đọc lại.
    """

    #: Cột thẻ đang đứng, nguyên văn như ERP trả về.
    status: str = ""
    #: Số ảnh đã đăng lên thẻ để chờ người duyệt.
    images_total: int = 0
    #: Trong đó còn bao nhiêu ảnh chưa ai bấm 👍 hay 👎.
    images_pending: int = 0
    #: Bao nhiêu ảnh được 👍 giữ lại.
    images_kept: int = 0
    #: Chính thẻ này đã mang mã SKU chưa.
    has_sku: bool = False
    #: Còn bao nhiêu thẻ trong cùng cụm *đã tới lượt* mà chưa có mã.
    #:
    #: Không còn là điều kiện chuyển cột — xem :func:`_leave_doing`.  Nó chỉ
    #: còn nói cho :func:`needs_sku_fill` biết trong cụm vẫn còn việc cho máy,
    #: để một lượt quét gọi đúng một lượt đánh số cho cả cụm thay vì bỏ sót
    #: những thẻ anh em cũng vừa được kéo sang.
    cards_missing_sku: int = 0
    #: Thẻ có khai ``action: listing`` không.
    is_listing: bool = False
    #: Listing đã lên shop chưa.
    listing_done: bool = False
    #: Thẻ sản phẩm: thẻ con không mang ảnh máy nào chờ 👍/👎.
    #:
    #: Ảnh của nó nằm ở tệp đính kèm (ảnh Trello) hay trong bình luận của
    #: người, và không ai bỏ phiếu cho chúng.  Người kéo nó sang *Đang làm* là
    #: đã chốt rồi, nên ở cột ấy chỉ còn việc của máy: điền mã.
    is_product: bool = False


@dataclass(frozen=True)
class Move:
    """Nước đi tiếp theo của thẻ.  ``status`` rỗng nghĩa là *ở yên*.

    ``reason`` luôn có chữ, kể cả khi đứng im: một thẻ không nhúc nhích mà
    không ai nói vì sao trông y hệt một thẻ hỏng, và đó chính là câu người
    dùng sẽ hỏi bot ngay trên thẻ.
    """

    status: str = ""
    reason: str = ""

    def __bool__(self) -> bool:
        """``if move:`` đọc là "có phải chuyển cột không"."""
        return bool(self.status)

    @property
    def column(self) -> str:
        """Tên tiếng Việt của cột đích."""
        return column_name(self.status) if self.status else ""


def decide(stage: CardStage) -> Move:
    """Thẻ này nên chuyển sang cột nào, hoặc ở yên vì lý do gì."""
    current = normalize_status(stage.status)
    if not current:
        # Cột lạ: có thể bảng được đổi tên, có thể ``taskDetail`` chưa kịp trả
        # về.  Cả hai trường hợp, đoán bừa đều tệ hơn đứng im.
        return Move("", f"không nhận ra cột “{str(stage.status or '').strip()}”")
    if current in CLOSED:
        return Move("", "thẻ đã đóng, máy không mở lại")
    if current == COL_TODO:
        return _leave_todo(stage)
    if current == COL_DOING:
        return _leave_doing(stage)
    return _leave_review(stage)


def _images_settled(stage: CardStage) -> str:
    """Bộ ảnh đã có người chốt chưa; trả về lý do khi *chưa*.

    Đây là điều kiện của **mọi** cột sau *Cần làm*, không riêng bước rời khỏi
    nó.  Luật cột không phải là chuỗi cửa mở một chiều: người ta kéo thẻ bằng
    tay bất cứ lúc nào, và một thẻ bị kéo thẳng vào *Đang làm* mà ảnh chưa ai
    xem sẽ được đẩy tiếp sang bàn của người viết listing — họ mở ra và không
    có gì để dùng.  Nên mỗi cột tự kiểm lại, chứ không tin cột trước.
    """
    if stage.images_total <= 0:
        return "chưa có ảnh nào để duyệt"
    return _votes_outstanding(stage)


def _sku_outstanding(stage: CardStage) -> str:
    """Điều kiện **cấp mã**, lỏng hơn điều kiện **chuyển cột**; lý do khi chưa.

    Hai câu hỏi khác nhau, và trước ngày 15/09/2026 chúng dùng chung một hàm.
    Chuyển cột là đẩy thẻ ra khỏi tay người đang giữ nó, nên phải chờ người
    chốt xong bộ ảnh.  Cấp mã thì không lấy đi của ai cái gì: nó chỉ đặt sẵn
    một con số lên thẻ đã được kéo sang *Đang làm*.  Người đặt việc chốt rằng
    thao tác kéo **chính là** cái chốt — không phải bấm thêm 👍/👎 tấm nào.

    Còn đúng hai thứ chặn.  Không ảnh: thẻ chưa có gì để bán, cấp mã là đốt
    số.  👎 hết: idea ấy tay trắng thật, để nó chạy lại ảnh đã.  Ảnh chưa ai
    bấm vẫn tính là dùng được.

    Gộp lại làm một với ``_images_settled`` là cái bẫy của bản 14/09: sửa
    ``_votes_outstanding`` cho cổng cấp mã thì ba cổng kia mở theo, và thẻ vừa
    nhận mã bay thẳng sang bàn người viết listing với cả chục tấm chưa ai nhìn.
    """
    if stage.images_total <= 0:
        return "chưa có ảnh nào để duyệt"
    if stage.images_kept + stage.images_pending <= 0:
        return "người duyệt bỏ hết ảnh, chưa có gì để đi tiếp"
    return ""


def _votes_outstanding(stage: CardStage) -> str:
    """Phần *đã có ảnh nhưng chưa chốt xong*, tách riêng khỏi phần *chưa có ảnh*.

    Tách ra vì *Đang review* cần đúng nửa này: ở đó một thẻ không có ảnh nào
    là chuyện bình thường (ảnh nằm ở thẻ sản phẩm khác), nên than "chưa có
    ảnh nào để duyệt" là nói sai; còn một thẻ có 15 tấm chưa ai bấm 👍/👎 thì
    vẫn phải nói ra, chứ không được gọi là "chờ người làm listing".
    """
    if stage.images_pending > 0:
        return f"còn {stage.images_pending} ảnh chờ 👍/👎"
    if stage.images_kept <= 0 < stage.images_total:
        # Bỏ hết ảnh nghĩa là idea này chưa ra được gì.  Thẻ ở lại để chạy
        # lại; đẩy nó đi thì nó nằm ở cột sau tay trắng, và cột ấy sẽ đầy
        # những thẻ chẳng có việc gì.
        return "người duyệt bỏ hết ảnh, chưa có gì để đi tiếp"
    return ""


def _leave_todo(stage: CardStage) -> Move:
    """*Cần làm* → *Đang làm*: người duyệt đã chốt bộ ảnh."""
    waiting = _images_settled(stage)
    if waiting:
        return Move("", waiting)
    return Move(COL_DOING, f"người duyệt đã chốt {stage.images_kept} ảnh")


def _leave_doing(stage: CardStage) -> Move:
    """*Đang làm* → *Đang review*: chính thẻ này đã có mã SKU.

    Chỉ hỏi về **chính nó**, không hỏi cả cụm.  Trước đây luật này giữ thẻ lại
    đến khi mọi thẻ trong cụm có mã, vì hồi ấy cả cụm mới hợp thành một sản
    phẩm.  Bây giờ mỗi thẻ idea con *là* một sản phẩm đi lên listing riêng, và
    mã chỉ phát cho thẻ đã được kéo sang cột này — nên anh chị em còn nằm ở
    *Cần làm* sẽ không bao giờ có mã, và điều kiện cũ biến thành một cái khoá
    không ai mở được: thẻ đầu tiên kéo sang đứng đó vĩnh viễn chờ những thẻ
    mà theo đúng thiết kế thì chưa tới lượt.

    Thẻ sản phẩm không có bộ ảnh nào để chờ, và có mã rồi cũng đứng yên:
    người trong team tự kéo tiếp.  Máy không đẩy thẻ đi khỏi tay người vừa
    kéo nó sang.
    """
    if stage.is_product:
        if not stage.has_sku:
            return Move("", "chưa điền được mã SKU")
        return Move("", "thẻ sản phẩm đã có mã SKU; người trong team tự kéo sang Đang review")
    waiting = _images_settled(stage)
    if waiting:
        return Move("", waiting)
    if not stage.has_sku:
        return Move("", "chưa điền được mã SKU")
    return Move(COL_REVIEW, "đã có mã SKU")


def _leave_review(stage: CardStage) -> Move:
    """*Đang review* → *Hoàn thành*: listing đã lên shop."""
    if stage.is_listing and stage.listing_done:
        # Bài đã lên shop thì thẻ xong, không xét lại bộ ảnh nữa: chuyện đã
        # xảy ra ngoài đời rồi, luật cột không có quyền phủ nhận nó.
        return Move(COL_DONE, "listing đã lên shop")
    waiting = _votes_outstanding(stage)
    if waiting:
        # Thẻ lọt được vào đây khi ảnh chưa ai chốt — người kéo tay, hoặc luật
        # cũ đẩy vào.  Nói đúng cái đang thiếu: bảo "chờ người làm listing"
        # thì họ mở thẻ ra và không có tấm nào đã duyệt để dùng.
        return Move("", waiting)
    if not stage.is_listing:
        # Thẻ không khai ``action: listing`` thì không có gì tự đóng nó, và
        # đó là đúng ý: *Đang review* là bàn làm việc của người viết listing,
        # máy không dọn thẻ đi khỏi bàn của họ.
        return Move("", "chờ người làm listing")
    return Move("", "chờ listing lên shop")


def needs_sku_fill(stage: CardStage) -> bool:
    """Thẻ này đang chờ **máy** điền mã, chứ không chờ người.

    Cột *Đang làm* là việc của máy: thẻ vừa được kéo sang là đã tới lượt.  Cái
    kéo tay ấy chính là cái chốt của người duyệt — họ không phải bấm thêm
    👍/👎 tấm nào nữa (luật chốt ngày 15/09/2026).

    Dùng :func:`_sku_outstanding` chứ **không** dùng :func:`_images_settled`:
    cổng cấp mã lỏng hơn cổng chuyển cột, và hai cái phải đi bằng hai hàm
    riêng.  Xem chú thích ở ``_sku_outstanding``.

    Thẻ sản phẩm thì không có bộ ảnh nào để hỏi: đứng ở *Đang làm* là đủ.
    """
    return (
        normalize_status(stage.status) == COL_DOING
        and (stage.is_product or not _sku_outstanding(stage))
        and (not stage.has_sku or stage.cards_missing_sku > 0)
    )


def is_forward(current: Any, target: Any) -> bool:
    """Nước đi này có tiến lên không.

    Hàng rào cuối trước khi ghi: mọi luật ở trên đều tiến, nhưng người gọi có
    thể tự dựng ``Move`` từ chỗ khác, và một lần ghi lùi sẽ kéo thẻ người ta
    vừa đẩy tay quay về cột cũ.  ``Cancelled`` không nằm trong :data:`ORDER`
    nên không bao giờ là đích tiến tới — huỷ thẻ là việc của người.
    """
    here = normalize_status(current)
    there = normalize_status(target)
    if not there or there not in ORDER:
        return False
    if not here:
        return False
    if here not in ORDER:
        # Đang ở ``Cancelled``: đã đóng, không đi đâu nữa.
        return False
    return ORDER.index(there) > ORDER.index(here)
