"""Nói chuyện với agent ngay trên thẻ ERP.

Từ trước tới nay bot chỉ *đọc* bình luận để lấy phiếu 👍/👎 — nghĩa là người
dùng chỉ nói được với nó đúng hai chữ. Module này mở đường thứ hai: viết một
câu vào thẻ, bot trả lời ngay trong thread đó.

Ở đây cố ý **không** có mạng, không có ERP, không có token — chỉ ngôn ngữ:
"câu này có phải nói với bot không", "câu này hỏi gì", "trả lời ra sao". Nhờ
vậy toàn bộ phần dễ sai nhất (hiểu tiếng Việt có dấu lẫn không dấu) kiểm thử
được bằng chuỗi thuần, còn ``agent_bot.chat_pass`` chỉ còn việc bưng câu trả
lời sang GraphQL.

Ba hàng rào được chọn có chủ ý, vì bot chạy trên board thật có đồng nghiệp
thật đang trao đổi công việc với nhau:

* Bot **chỉ** trả lời khi được gọi đích danh (``@bot``, mở đầu bằng "bot ...",
  hoặc được nhắc tên trong ``mentions``) — hoặc khi người ta trả lời thẳng vào
  một bình luận của chính bot. Bình luận hai người nói với nhau thì bot im.
* Trong thread của bot mà câu nói không khớp lệnh nào thì cũng im: "ok em",
  "đẹp đấy" không cần một bản hướng dẫn dội lại mỗi lần.
* Một bình luận chỉ được trả lời đúng một lần, ghi sổ theo id bình luận.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from .pipeline import COL_DOING, column_name
from .sku import SkuCard, card_is_ready

# ── Ý định ─────────────────────────────────────────────────────────────

INTENT_HELP = "help"
INTENT_STATUS = "status"
INTENT_SKU = "sku"
#: Hỏi mã và *bảo đánh số* là hai chuyện khác nhau, nên là hai ý định
#: khác nhau: "sku của thẻ này là gì" chỉ đọc, còn "điền sku đi" thì ghi
#: lên cả cụm.  Gộp làm một là mỗi lần ai đó hỏi thăm lại ghi đè một lượt.
INTENT_SKU_FILL = "sku_fill"
INTENT_SKU_RENUMBER = "sku_renumber"
INTENT_RUN = "run"
INTENT_PAUSE = "pause"
INTENT_RESUME = "resume"
INTENT_LISTING = "listing"
INTENT_ACCOUNT = "account"
INTENT_SET = "set"
INTENT_UNKNOWN = "unknown"

# Việc bot phải làm sau khi trả lời. Câu trả lời và hành động đi cùng nhau
# nhưng tách rời: phần ngôn ngữ ở đây quyết *nói gì*, còn ``chat_pass`` mới là
# chỗ duy nhất được đụng vào sổ ghi.
ACTION_NONE = ""
ACTION_RUN = "run"
ACTION_PAUSE = "pause"
ACTION_RESUME = "resume"
ACTION_SET = "set"
#: Đánh số cả cụm.  Tách làm hai vì hậu quả khác hẳn nhau: ``FILL`` chỉ
#: điền vào ô còn trống, còn ``RENUMBER`` ghi đè cả mã đã có.  Mã SKU đã đi
#: ra ngoài phần mềm — in lên tem, gõ vào shop — nên đổi nó phải là câu
#: người ta nói thẳng ra, không bao giờ là hiệu ứng phụ của "điền hộ tôi".
ACTION_SKU_FILL = "sku_fill"
ACTION_SKU_RENUMBER = "sku_renumber"

# Gọi bot bằng những chữ này. Chỉ tính khi đứng đầu câu (hoặc có "@" phía
# trước): "bot" nằm lọt giữa một câu tiếng Việt thường là đang nói *về* bot
# với người khác chứ không phải nói *với* bot.
TRIGGER_WORDS: Tuple[str, ...] = ("bot", "agent", "hvg")

# Bảng lệnh. Câu nào khớp cụm **dài nhất** thì thắng, nên "chạy lại" không bao
# giờ bị "chạy" nuốt mất, và thứ tự trong bảng chỉ dùng để phá hoà.
INTENT_PHRASES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (
        INTENT_PAUSE,
        ("dung lai", "tam dung", "ngung lai", "dung", "ngung", "stop", "pause", "khoan da"),
    ),
    (
        INTENT_RESUME,
        ("chay tiep", "lam tiep", "tiep tuc", "mo lai", "bat lai", "resume", "chay tiep di"),
    ),
    (
        INTENT_RUN,
        (
            "chay lai",
            "chay di",
            "chay thu",
            "chay",
            "lam anh",
            "tao anh",
            "len anh",
            "run",
            "retry",
            "thu lai",
        ),
    ),
    # Đứng trước ``INTENT_SKU`` cho dễ đọc; cụm dài nhất mới là cụm thắng,
    # nên "danh so lai" không bao giờ bị "danh so" hay "sku" nuốt mất.
    (
        INTENT_SKU_RENUMBER,
        (
            "danh so lai",
            "danh lai so",
            "danh lai ma",
            "cap lai ma",
            "doi ma sku",
            "sua lai sku",
            "sua lai ma",
            "renumber",
        ),
    ),
    (
        INTENT_SKU_FILL,
        (
            "dien sku",
            "dien ma",
            "cap ma sku",
            "cap ma",
            "danh so",
            "gan sku",
            "tao sku",
            "fill sku",
        ),
    ),
    (INTENT_SKU, ("ma sku", "sku", "ma the", "ma san pham")),
    # Đứng **trước** listing trong bảng chỉ để dễ đọc; cụm dài nhất mới thắng,
    # nên "dang listing acc nao" vẫn ra listing chứ không ra account.
    (
        INTENT_ACCOUNT,
        ("tai khoan nao", "shop nao", "acc nao", "tai khoan", "acc", "shop", "account"),
    ),
    (INTENT_LISTING, ("dang listing", "len listing", "listing", "dang shop")),
    (
        INTENT_STATUS,
        (
            "trang thai",
            "tinh hinh",
            "sao roi",
            "the nao roi",
            "den dau roi",
            "den dau",
            "bao cao",
            "status",
            "xong chua",
            "chay chua",
            "co gi moi",
            # Hỏi thẳng về nước đi kế tiếp.  Trả lời bằng đúng khối trạng
            # thái: dòng cuối của nó *là* câu trả lời, kèm luôn cái đang
            # chặn — tách thành một khối riêng chỉ để in lại ít hơn.
            "buoc ke",
            "buoc tiep theo",
            "buoc tiep",
            "buoc sau",
            "tiep theo la gi",
            "sang cot nao",
            "chuyen cot",
            "khi nao xong",
            "dang cho gi",
            "con thieu gi",
            "vuong gi",
        ),
    ),
    (
        INTENT_HELP,
        ("huong dan", "lam duoc gi", "biet lam gi", "cach dung", "giup", "help", "menu"),
    ),
)


def normalize(value: Any) -> str:
    """Bỏ dấu, bỏ ký tự thừa, còn chữ thường và khoảng trắng.

    ``"Chạy lại giúp mình"`` → ``"chay lai giup minh"``.

    ``đ`` đổi thành ``d`` *trước* khi bỏ dấu vì ``unicodedata`` không tách được
    nó — nó là một chữ cái riêng chứ không phải ``d`` cộng dấu. Thiếu bước này
    thì ``"đăng"`` nén thành ``"ang"`` và mọi lệnh có chữ ``đ`` trượt hết.
    """
    text = str(value or "").strip().lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if ch.isascii())
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


#: Ô nào trong khối *Thuộc tính* được sửa bằng lời nói, và người ta gọi nó
#: bằng những chữ gì.  Cố ý là danh sách **đóng**: cho phép gõ tên ô tuỳ ý
#: nghĩa là một câu chat lỡ tay đẻ ra một thuộc tính mới không ai đọc, hoặc
#: đè lên ``action_1`` và biến thẻ ảnh thành thẻ listing.
EDITABLE_FIELDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("acc", ("acc", "tai khoan", "account", "shop")),
    ("product", ("product", "san pham", "ten san pham", "mat hang")),
    ("sku", ("sku", "ma sku", "ma san pham", "ma the")),
    ("template", ("template", "mau", "khuon", "mau listing")),
)

#: Cách người ta nói "gán giá trị này vào ô kia".  Nhóm ``field`` là tên ô,
#: nhóm ``value`` là phần còn lại của **dòng** — dừng ở cuối dòng chứ không
#: nuốt sang dòng sau, để nhắn nhiều ô một lượt vẫn tách đúng.
_SET_PATTERNS: Tuple[str, ...] = (
    r"^\s*(?:dat|sua|doi|set|ghi)?\s*(?P<field>[a-zA-Z\u00c0-\u1ef9 ]{2,20}?)\s*[:=]\s*(?P<value>.*)$",
    r"^\s*(?:dat|đặt|sua|sửa|doi|đổi|set|ghi)\s+(?P<field>[a-zA-Z\u00c0-\u1ef9 ]{2,20}?)\s+(?:la|là|thanh|thành|=)\s+(?P<value>.+)$",
)

#: Xoá trắng một ô.  Tách khỏi bảng trên vì ở đây *không* có giá trị nào —
#: bắt nó khớp cùng một biểu thức thì "xoa acc" hiểu thành ô tên "xoa acc".
_CLEAR_PATTERN = r"^\s*(?:xoa|xóa|xoá|bo|bỏ|clear|go|gỡ)\s+(?P<field>[a-zA-Z\u00c0-\u1ef9 ]{2,20}?)\s*$"


#: Động từ mở đầu một lệnh sửa. Rút ra từ chính hai bảng trên để chỉ có **một**
#: chỗ định nghĩa "nghe như một mệnh lệnh", cộng thêm mấy từ người ta hay dùng
#: mà bảng kia không cần biết ("chuyển", "thay", "cập nhật").
#:
#: Dùng để nhận ra một câu *đòi sửa* mà bảng từ khoá không tách nổi ra ô nào —
#: khác hẳn một câu hỏi. Không có nó thì "đổi mẫu listing sang mockup-02" bị
#: chữ "listing" kéo về thành câu hỏi tình trạng listing, và người ta nhận một
#: bản báo cáo thay vì nhận việc đã làm.
_ORDER_VERBS: Tuple[str, ...] = (
    "dat", "sua", "doi", "set", "ghi", "xoa", "bo", "go",
    "chuyen", "thay", "cap nhat", "update", "dien",
    # "giúp/giùm" không phải động từ sai việc, nhưng người ta gần như chỉ gắn
    # nó vào lúc đang nhờ làm gì đó ("cho về acc32 giúp anh với"). Nhận nhầm
    # một câu hỏi ở đây chỉ tốn thêm một lượt đọc rồi trả về y như cũ; bỏ sót
    # thì người ta nhận bản hướng dẫn thay vì được sửa.
    "giup", "gium",
)


def sounds_like_an_order(content: str) -> bool:
    """Câu này có đang *sai bot làm gì đó* không (khác với đang hỏi)."""
    text = normalize(strip_trigger(content))
    if not text:
        return False
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(verb)}(?![a-z0-9])", text)
        for verb in _ORDER_VERBS
    )


def resolve_field(name: Any) -> str:
    """Chữ người ta gõ → tên ô trong khối *Thuộc tính*, hoặc ``""``.

    Nhận cả tiếng Việt có dấu lẫn không dấu, vì người ta gõ "sản phẩm" và
    "san pham" như nhau và không ai muốn nghe bot bảo "không có ô đó".
    """
    wanted = normalize(name)
    if not wanted:
        return ""
    for field_name, spellings in EDITABLE_FIELDS:
        if wanted in spellings:
            return field_name
    return ""


def parse_edits(content: str) -> Tuple[Tuple[str, str], ...]:
    """Câu nói → những ô cần sửa, theo đúng thứ tự người ta gõ.

    Đọc **chữ gốc còn dấu**, không đọc bản đã chuẩn hoá: giá trị mới là thứ sẽ
    nằm nguyên xi trên thẻ, mà ``normalize`` thì bóc sạch dấu — lưu bản đã bóc
    là biến "khăn tay" thành "khan tay" ngay trên bảng của người ta.

    Câu nào không phải lệnh gán thì trả về rỗng, và đó là cách ``understand``
    phân biệt "acc nào vậy" (câu hỏi) với "acc: acc32" (lệnh sửa).
    """
    text = strip_trigger_raw(content)
    edits: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip().rstrip(".;")
        if not line:
            continue
        cleared = re.match(_CLEAR_PATTERN, line, re.IGNORECASE)
        if cleared:
            field_name = resolve_field(cleared.group("field"))
            if field_name:
                edits[field_name] = ""
            continue
        for pattern in _SET_PATTERNS:
            found = re.match(pattern, line, re.IGNORECASE)
            if not found:
                continue
            field_name = resolve_field(found.group("field"))
            if not field_name:
                break
            value = found.group("value").strip().strip("\"'“”'")
            # Ô ``acc`` là một mã máy đọc, nên chốt về đúng dạng dùng chung
            # toàn app; các ô còn lại là chữ người đọc, giữ nguyên xi.
            edits[field_name] = normalize_account(value) if field_name == "acc" else value
            break
    return tuple(edits.items())


def normalize_account(value: Any) -> str:
    """Mã tài khoản viết sao cũng về một dạng: ``"ACC 32"`` → ``"acc-32"``.

    Dùng chung đúng luật với sổ tay tài khoản (``account_book.normalize_token``)
    — hai luật khác nhau thì gõ "acc 32" vào thẻ sẽ tra sổ không ra dòng nào.
    """
    from .account_book import normalize_token

    return normalize_token(value)


def _mentioned(mentions: Any, bot_user: str) -> bool:
    """``mentions`` của ERP có nhắc tới bot không.

    Chấp nhận cả danh sách chuỗi lẫn danh sách bản ghi: hai đường đọc thẻ khác
    nhau trả về hai hình dạng, và đoán sai hình dạng ở đây nghĩa là bot ngồi im
    đúng lúc người ta gọi tên nó.
    """
    wanted = str(bot_user or "").strip().lower()
    if not wanted:
        return False
    for item in mentions or []:
        if isinstance(item, Mapping):
            names = (item.get("user"), item.get("email"), item.get("name"), item.get("bot_user"))
        else:
            names = (item,)
        for name in names:
            if str(name or "").strip().lower() == wanted:
                return True
    return False


def has_trigger(content: str) -> bool:
    """Câu này có gọi đích danh bot không."""
    raw = str(content or "").lower()
    if any(f"@{word}" in raw for word in TRIGGER_WORDS):
        return True
    first = normalize(content).split(" ", 1)[0]
    return bool(first) and first in TRIGGER_WORDS


def strip_trigger(content: str) -> str:
    """Bỏ chữ gọi tên ở đầu câu, trả về phần **đã chuẩn hoá** còn lại.

    ``"@bot chạy lại"`` → ``"chay lai"``; ``"@bot"`` một mình → ``""``, và câu
    rỗng ấy chính là lời chào — nó thành ``INTENT_HELP``.
    """
    words = normalize(content).split(" ")
    while words and words[0] in TRIGGER_WORDS:
        words.pop(0)
    return " ".join(words).strip()


def strip_trigger_raw(content: str) -> str:
    """Như :func:`strip_trigger` nhưng **giữ nguyên dấu và chữ hoa**.

    Lệnh sửa mang theo giá trị sẽ nằm nguyên xi trên thẻ, nên đường đọc nó
    không được đi qua ``normalize``.  Vẫn phải gỡ chữ gọi tên ở đầu, nếu không
    "@bot product: khăn tay" hiểu thành ô tên "bot product".
    """
    text = str(content or "").strip()
    # Gỡ "@bot", "bot:", "bot" ở đầu — lặp vì người ta hay gõ "@bot bot ơi".
    while True:
        stripped = re.sub(
            r"^\s*@?(?:" + "|".join(TRIGGER_WORDS) + r")\b[\s:,]*",
            "",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
        if stripped == text:
            return text.strip()
        text = stripped


def addressed_to_bot(
    comment: Mapping[str, Any],
    bot_user: str = "",
    *,
    in_bot_thread: bool = False,
    allowed_authors: Iterable[str] = (),
) -> bool:
    """Bình luận này có phải người thật **được phép ra lệnh** đang nói với bot không.

    Loại trước hai nhóm không bao giờ được trả lời: bình luận của chính bot
    (``mine``) và bình luận của một bot khác (``is_bot``). Bỏ hàng rào ấy thì
    hai con bot đủ sức nói chuyện với nhau đến hết quota.

    Rồi tới hàng rào tác giả (C3): người ngoài ``allowed_authors`` gọi tên bot
    cũng **không** được coi là đang ra lệnh — trả về ``False`` ở đây nghĩa là
    bot im hẳn, không dựng câu trả lời nào, kể cả một câu từ chối.  Một câu từ
    chối là một cách xác nhận cho người lạ rằng bot có ở đây và đang nghe.
    Danh sách trống thì không khoá ai, xem ``author_is_allowed``.
    """
    if not isinstance(comment, Mapping):
        return False
    if int(comment.get("mine") or 0) == 1:
        return False
    if int(comment.get("is_bot") or 0) == 1:
        return False
    if not author_is_allowed(comment, allowed_authors):
        return False
    content = comment.get("content")
    if _mentioned(comment.get("mentions"), bot_user):
        return True
    if has_trigger(content):
        return True
    return bool(in_bot_thread) and bool(strip_trigger(content))


#: Những khoá ERP trả tên tác giả một bình luận về — tuỳ đường đọc thẻ mà nó
#: nằm ở khoá nào.  Đoán sai hình dạng ở đây nghĩa là hàng rào tác giả từ chối
#: đúng cả những người đang có trong danh sách, nên chấp nhận cả bốn như
#: ``_mentioned`` đã chấp nhận cả danh sách chuỗi lẫn danh sách bản ghi.
AUTHOR_FIELDS: Tuple[str, ...] = ("owner", "by_email", "email", "user")


def parse_allowed_authors(raw: str) -> Tuple[str, ...]:
    """``"a@x.vn, B@X.VN"`` → ``("a@x.vn", "b@x.vn")``.

    Chuẩn hoá về chữ thường ngay lúc đọc, để chỗ so sánh không phải nhớ luật
    này lần thứ hai.
    """
    text = str(raw or "").replace(";", ",")
    seen: List[str] = []
    for item in text.split(","):
        email = item.strip().lower()
        if email and email not in seen:
            seen.append(email)
    return tuple(seen)


def comment_author(comment: Mapping[str, Any]) -> str:
    """Email tác giả của bình luận, chữ thường; rỗng khi không đọc ra được."""
    if not isinstance(comment, Mapping):
        return ""
    for name in AUTHOR_FIELDS:
        value = comment.get(name)
        if isinstance(value, Mapping):
            value = value.get("email") or value.get("user") or value.get("name")
        text = str(value or "").strip().lower()
        if text:
            return text
    return ""


def author_is_allowed(comment: Mapping[str, Any], allowed: Iterable[str] = ()) -> bool:
    """Người này có được ra lệnh cho bot không.

    Hàm thuần tuý, tách khỏi bot để test được và để đọc được ở một chỗ (C3.4).

    Hai quyết định cố ý ngược nhau:

    * **Danh sách trống = không khoá** (C3.2).  Đóng mặc định là sai ở đây: bật
      hàng rào lên mà chưa ai kịp điền danh sách thì bot câm trên một bảng đang
      chạy, và không ai biết vì sao.
    * **Thiếu tác giả trong lúc đang khoá = từ chối** (C3.5).  Cho qua nghĩa là
      bỏ trống hàng rào đúng lúc cần nó nhất — một bình luận không rõ ai viết
      là lý do để dừng, không phải lý do để tin.
    """
    wanted = {str(item or "").strip().lower() for item in (allowed or ())}
    wanted.discard("")
    if not wanted:
        return True
    return comment_author(comment) in wanted


def understand(content: str) -> str:
    """Câu nói → ý định. Không khớp gì thì ``INTENT_UNKNOWN``."""
    text = strip_trigger(content)
    if not text:
        # Gọi tên bot rồi thôi: đó là "ê, mày làm được gì?".
        return INTENT_HELP
    if parse_edits(content):
        # Xét **trước** bảng lệnh: "acc" là câu hỏi còn "acc: acc32" là lệnh
        # sửa, mà cả hai đều chứa đúng chữ "acc".  Hình dạng gán giá trị thắng,
        # vì gõ ra một giá trị cụ thể thì không còn là đang hỏi nữa.
        return INTENT_SET
    best_intent = INTENT_UNKNOWN
    best_length = 0
    for intent, phrases in INTENT_PHRASES:
        for phrase in phrases:
            if len(phrase) <= best_length:
                continue
            if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text):
                best_intent = intent
                best_length = len(phrase)
    return best_intent


# ── Thẻ nói gọn lại ────────────────────────────────────────────────────


@dataclass(frozen=True)
class CardBrief:
    """Những gì bot biết về một thẻ, đủ để trả lời mà không hỏi ERP thêm lần nữa."""

    task: str = ""
    title: str = ""
    status: str = ""
    sku: str = ""
    product: str = ""
    #: Mẫu listing thẻ đang khai. Sửa được từ lâu nhưng trước nay không ai
    #: *đọc* ra; phần đoán ý cần nó để hiểu câu "đổi mẫu khác đi".
    template: str = ""
    is_listing: bool = False
    children: int = 0
    images_kept: int = 0
    images_pending: int = 0
    images_dropped: int = 0
    listing_ready: bool = False
    listing_missing: str = ""
    listed: bool = False
    paused: bool = False
    autorun: bool = True
    poll_seconds: int = 0
    last_run: str = ""
    root_task: str = ""
    #: Tài khoản thẻ này thuộc về, đã tra qua sổ tay.
    account: str = ""
    #: Tên shop trong sổ, để người đọc kiểm lại được mà không mở sổ.
    shop: str = ""
    #: Máy chạy listing của tài khoản ấy.
    machine: str = ""
    #: Máy đọc tài khoản ra từ đâu: ``meta_acc`` (gõ tay) hay ``label`` (dán nhãn).
    account_source: str = ""
    #: Sổ tay có dòng cho tài khoản này không.
    account_in_book: bool = False
    #: Mã tài khoản sổ tay đang biết. Cần cho lệnh sửa: người ta gõ một mã
    #: *mới*, mà ``account_in_book`` chỉ nói về mã thẻ **đang** mang.
    known_accounts: Tuple[str, ...] = field(default_factory=tuple)
    #: Cột kế thẻ sẽ sang, và điều nó đang chờ. Rỗng nghĩa là chưa tính.
    next_column: str = ""
    waiting: str = ""

    @property
    def images_total(self) -> int:
        return self.images_kept + self.images_pending + self.images_dropped


@dataclass(frozen=True)
class Reply:
    """Câu trả lời cùng việc phải làm sau khi trả lời."""

    intent: str
    lines: Tuple[str, ...] = field(default_factory=tuple)
    action: str = ACTION_NONE
    #: Ô cần ghi xuống thẻ, khi ``action`` là :data:`ACTION_SET`. Đi kèm câu
    #: trả lời chứ không nằm rời, để ``chat_pass`` không phải đọc lại câu nói
    #: một lần nữa và có cơ hội hiểu khác đi.
    edits: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def text(self) -> str:
        """Bản gửi lên ERP, và cũng là bản dùng cho log lẫn kiểm thử.

        Ô bình luận của ERP nhận **chữ thuần**, không nhận HTML: đo trên bảng
        thật, ``\n`` giữ nguyên còn ``<br>`` hiện ra thành đúng bốn chữ ``<br>``
        giữa câu.  Chính máy chủ đã escape phần HTML người ta gõ vào (``<script>``
        đọc ra thành ``&lt;script&gt;``), nên tiêu đề thẻ không cần escape lần
        nữa ở đây — escape hai lần thì một cái tên có dấu ``&`` hiện ra sai.
        """
        return "\n".join(self.lines)


HELP_LINES: Tuple[str, ...] = (
    "Nhắn cho tôi ngay trên thẻ này — mở đầu bằng @bot, hoặc trả lời thẳng vào một bình luận của tôi:",
    "• “trạng thái” — thẻ đang tới đâu, còn bao nhiêu ảnh chờ duyệt.",
    "• “bước kế” — thẻ sang cột nào tiếp, và đang vướng gì.",
    "• “SKU” — mã SKU thẻ đang mang, dạng {TÊN}_{dự án}_{idea} (thẻ idea cha không bao giờ có mã).",
    f"• “điền sku” — cấp mã cho những thẻ trong cụm đã được kéo sang cột {column_name(COL_DOING)} mà còn trống; thẻ chưa sang cột thì chưa tới lượt.",
    "• “đánh số lại” — đánh số lại cả cụm, ghi đè cả mã đã có "
    "(dùng khi vừa đổi tên sản phẩm — tên bảng, hay dòng product trên thẻ gốc).",
    "• “chạy” — xếp thẻ vào lượt quét kế tiếp.",
    "• “dừng” — tạm dừng thẻ này; nhắn “tiếp tục” để mở lại.",
    "• “listing” — bộ ảnh đã chốt chưa, đã giao sang bản Listing chưa.",
    "• “acc” — thẻ này lên shop nào, chạy ở máy nào (tra sổ tay tài khoản).",
    "• “acc: acc32” — sửa thẳng một ô trong khối Thuộc tính; "
    "sửa được acc, product, sku, template, và “xoá acc” thì xoá trắng ô đó.",
)


def _card_line(brief: CardBrief) -> str:
    title = brief.title or brief.task
    # Tên cột nói bằng tiếng Việt, vì đó là chữ người hỏi đang nhìn trên bảng.
    # Trả lời "cột Pending Review" là bắt họ tự dịch.
    where = f"cột {column_name(brief.status)}" if brief.status else "chưa rõ cột"
    return f"{brief.task} · {title} — {where}"


def _step_line(brief: CardBrief) -> str:
    """Thẻ đang chờ gì để đi tiếp — câu người ta thật sự muốn nghe."""
    if brief.next_column:
        return f"Bước kế: chuyển sang cột {brief.next_column} ({brief.waiting})."
    return f"Bước kế: ở lại cột này — {brief.waiting or 'chưa có gì để đi tiếp'}."


def _account_lines(brief: CardBrief) -> Tuple[str, ...]:
    """Sổ tay tài khoản trả lời câu "thẻ này lên shop nào"."""
    if not brief.account:
        return (
            "Thẻ chưa cho biết tài khoản nào: khối Thuộc tính không có dòng “acc:” "
            "và thẻ cũng chưa dán nhãn tài khoản. Dán nhãn (ví dụ acc32) hoặc gõ "
            "“acc: acc32” là tôi tra được sổ.",
        )
    where = {"meta_acc": "gõ trong khối Thuộc tính", "label": "đọc từ nhãn trên thẻ"}.get(
        brief.account_source, "đọc từ thẻ"
    )
    head = f"Tài khoản: {brief.account}"
    if brief.shop:
        head += f" — shop “{brief.shop}”"
    head += f" ({where})."
    lines = [head]
    if brief.machine:
        lines.append(f"Máy chạy listing: {brief.machine}.")
    if not brief.account_in_book:
        # Không có dòng trong sổ thì máy chỉ còn quy ước đặt tên để đoán, và
        # quy ước ấy chỉ ra được máy nếu máy đó có thật trong cấu hình. Nói
        # đúng cái đang thiếu, chứ không hứa một suy đoán không hề xảy ra.
        lines.append(
            "Sổ tay chưa có dòng cho tài khoản này"
            + (
                " nên tôi đoán máy theo quy ước đặt tên."
                if brief.machine
                else " nên tôi chưa biết nó chạy ở máy nào."
            )
            + " Thêm nó vào sổ để chắc chắn."
        )
    return tuple(lines)


def _image_line(brief: CardBrief) -> str:
    if not brief.images_total:
        return "Ảnh: thẻ chưa có ảnh nào chờ duyệt."
    parts = [f"{brief.images_kept} đã giữ 👍", f"{brief.images_pending} đang chờ"]
    if brief.images_dropped:
        parts.append(f"{brief.images_dropped} bị 👎 (sẽ gỡ)")
    return "Ảnh: " + ", ".join(parts) + "."


def _run_line(brief: CardBrief) -> str:
    if brief.paused:
        return "Tự chạy: đang tạm dừng theo yêu cầu trên thẻ."
    if not brief.autorun:
        return "Tự chạy: đang tắt ở cấu hình bot."
    when = f" Lượt gần nhất: {brief.last_run}." if brief.last_run else ""
    return f"Tự chạy: bật.{when}"


def _next_scan(brief: CardBrief) -> str:
    return (
        f" Lượt quét kế tiếp trong khoảng {brief.poll_seconds}s."
        if brief.poll_seconds > 0
        else ""
    )


def _listing_lines(brief: CardBrief) -> Tuple[str, ...]:
    if not brief.is_listing:
        return ("Thẻ này không khai action listing nên tôi chỉ lo phần ảnh.",)
    if brief.listed:
        return ("Listing: đã giao sang bản Listing rồi, tôi không giao lại nữa.",)
    if brief.listing_ready:
        return ("Listing: bộ ảnh đã chốt, thẻ đang chờ tới lượt giao.",)
    return (f"Listing: chưa giao được — {brief.listing_missing or 'ảnh chưa chốt'}.",)


#: Chữ hiện lên khi kể lại một ô vừa sửa. Tên ô trên thẻ là tiếng Anh vì đó
#: là thứ nằm trong khối *Thuộc tính*, nhưng câu kể thì nói tiếng Việt.
_FIELD_LABELS: Dict[str, str] = {
    "acc": "tài khoản",
    "product": "sản phẩm",
    "sku": "mã SKU",
    "template": "mẫu listing",
}


def _account_as_the_book_spells_it(value: str, known: Tuple[str, ...]) -> str:
    """Mã tài khoản người ta gõ → đúng dòng sổ tay đang có, nếu sổ có nó.

    Đo trên bảng thật: người ta gõ ``"ACC 32"``, luật chuẩn hoá cho ra
    ``"acc-32"``, còn sổ tay ghi ``"acc32"`` — ba chữ, hai mã khác nhau, và
    thẻ mang ``acc-32`` thì tra sổ không ra dòng nào nên chạy sai máy.  Sổ tay
    mới là nơi quyết cách viết: bỏ hết dấu nối rồi so, khớp thì lấy nguyên
    chữ trong sổ.  Không khớp dòng nào thì giữ bản chuẩn hoá và nói ra — đó
    là tài khoản sổ thật sự chưa có.
    """
    if not value or value in known:
        return value
    wanted = re.sub(r"[^a-z0-9]+", "", normalize(value))
    if not wanted:
        return value
    for entry in known:
        if re.sub(r"[^a-z0-9]+", "", normalize(entry)) == wanted:
            return entry
    return value


def _sku_looks_right(value: str) -> bool:
    """Mã này có đúng dạng ``{TÊN}_{dự án}_{idea}`` không.

    Cùng đòi hỏi với ``sku.SKU_RE``, kể cả chuyện phần tên phải có chữ cái:
    khen một mã toàn số là "đúng dạng" trong khi lượt đánh số đọc nó không
    ra là hứa hộ một điều máy sẽ không giữ lời.
    """
    return bool(
        re.fullmatch(r"[A-Za-z0-9-]*[A-Za-z][A-Za-z0-9-]*_\d+_\d+", str(value or "").strip())
    )


def _compose_set(brief: CardBrief, edits: Tuple[Tuple[str, str], ...]) -> Reply:
    """Trả lời cho một lệnh sửa: kể lại sẽ ghi gì, và cảnh báo chỗ đáng ngờ.

    Câu trả lời viết ở **thì tương lai** ("tôi ghi..."), vì lúc dựng câu thì
    chưa ghi gì cả — ``chat_pass`` mới là chỗ gọi ERP, và nó có quyền thất
    bại.  Hứa "đã ghi xong" ở đây là hứa hộ một việc chưa xảy ra.
    """
    if not edits:
        # Vào được đây nghĩa là ``understand`` nhận ra lệnh sửa nhưng
        # ``parse_edits`` lại không thấy gì — chỉ xảy ra khi người gọi tự
        # dựng intent bằng tay. Nói ra thay vì im lặng không làm gì.
        names = ", ".join(name for name, _ in EDITABLE_FIELDS)
        return Reply(
            INTENT_SET,
            (f"Tôi chưa thấy ô nào để sửa. Sửa được: {names}. Ví dụ: “acc: acc32”.",),
        )

    lines = []
    resolved: List[Tuple[str, str]] = []
    for field_name, value in edits:
        if field_name == "acc":
            value = _account_as_the_book_spells_it(value, brief.known_accounts)
        resolved.append((field_name, value))
        label = _FIELD_LABELS.get(field_name, field_name)
        if not value:
            lines.append(f"Tôi xoá trắng ô {field_name} ({label}) trên thẻ này.")
            continue
        lines.append(f"Tôi ghi {field_name} = “{value}” ({label}) vào khối Thuộc tính.")
        if field_name == "acc" and value not in brief.known_accounts:
            lines.append(
                f"Lưu ý: sổ tay tài khoản chưa có dòng “{value}” nên tôi vẫn "
                "chưa biết nó là shop nào, chạy ở máy nào."
            )
        if field_name == "sku" and not _sku_looks_right(value):
            lines.append(
                f"Lưu ý: “{value}” không đúng dạng {{TÊN}}_{{dự án}}_{{idea}}, "
                "nên lượt đánh số tự động sẽ bỏ qua thẻ này chứ không sửa đè."
            )
    return Reply(INTENT_SET, tuple(lines), ACTION_SET, tuple(resolved))


def compose(
    intent: str,
    brief: CardBrief,
    edits: Tuple[Tuple[str, str], ...] = (),
) -> Reply:
    """Ý định + thẻ → câu trả lời. Không bao giờ trả về câu rỗng."""
    if intent == INTENT_SET:
        return _compose_set(brief, edits)
    if intent == INTENT_STATUS:
        lines = [_card_line(brief)]
        if brief.sku or brief.product:
            lines.append(
                "SKU: " + (brief.sku or "chưa có")
                + (f" · sản phẩm: {brief.product}" if brief.product else "")
            )
        lines.append(_image_line(brief))
        if brief.children:
            lines.append(f"Thẻ con: {brief.children}.")
        lines.append(_run_line(brief))
        if brief.waiting or brief.next_column:
            lines.append(_step_line(brief))
        if brief.is_listing:
            lines.extend(_account_lines(brief))
            lines.extend(_listing_lines(brief))
        return Reply(intent, tuple(lines))

    if intent == INTENT_SKU:
        if brief.sku:
            line = f"SKU của thẻ này là {brief.sku}."
            if brief.product:
                line += f" Phần tên lấy theo sản phẩm “{brief.product}”."
            return Reply(intent, (line,))
        if brief.root_task and brief.task == brief.root_task:
            # Thẻ gốc của cụm là idea cha: theo thiết kế nó không bao giờ mang
            # mã — nó là chỗ khai ``product:`` và nhận ảnh, mã thuộc về những
            # thẻ idea con tách ra từ nó.  Hứa "lượt sau tôi điền" ở đây là
            # hứa một điều máy cố ý không làm.
            return Reply(
                intent,
                (
                    "Thẻ này là idea cha nên không bao giờ mang mã — nó là chỗ "
                    "khai “product” và nhận ảnh. Mã dạng {TÊN}_{dự án}_{idea} "
                    "cấp cho từng thẻ idea con, khi người duyệt kéo thẻ ấy sang "
                    f"cột {column_name(COL_DOING)}.",
                ),
            )
        # Cùng một luật với lượt cấp mã thật (``sku.card_is_ready``): câu nói
        # "chưa tới lượt" phải trùng với lý do máy thật sự chưa điền, không
        # được là một bản luật chép tay thứ hai.
        ready = card_is_ready(SkuCard(task_id=brief.task, status=brief.status))
        if brief.product:
            if ready:
                return Reply(
                    intent,
                    (
                        f"Thẻ chưa có SKU. Sản phẩm đang khai là “{brief.product}”, "
                        "tôi sẽ cấp mã ở lượt đánh số kế tiếp.",
                    ),
                )
            return Reply(
                intent,
                (
                    "Thẻ chưa có SKU vì chưa tới lượt: mã chỉ cấp khi người duyệt "
                    f"kéo thẻ sang cột {column_name(COL_DOING)}. Sản phẩm đã khai là "
                    f"“{brief.product}”, sang cột là tôi điền ngay lượt đánh số kế tiếp.",
                ),
            )
        lines = [
            "Thẻ chưa có SKU. Phần tên tôi tra theo dòng “product” trên thẻ idea "
            "cha — không thẻ nào khai thì tôi lấy tên bảng — còn thẻ idea cha "
            "thì không bao giờ mang mã."
        ]
        if not ready:
            lines.append(
                f"Mã chỉ cấp khi người duyệt kéo thẻ sang cột {column_name(COL_DOING)}; "
                "thẻ này chưa sang nên tôi chưa điền."
            )
        return Reply(intent, tuple(lines))

    if intent in (INTENT_SKU_FILL, INTENT_SKU_RENUMBER):
        renumber = intent == INTENT_SKU_RENUMBER
        # Đánh số luôn chạy từ thẻ gốc kể cả khi câu nói nằm trên một thẻ
        # con: dòng ``product:`` khai trên idea cha, và một lượt từ gốc phủ
        # luôn những thẻ anh em cũng vừa được kéo sang — mỗi nhánh một lệnh
        # thì người ta phải tự nhớ mình còn nhánh nào chưa gõ.
        target = brief.root_task or brief.task
        if renumber:
            return Reply(
                intent,
                (
                    f"Đánh số lại cả cụm {target}, ghi đè cả những mã đang có.",
                    "Mã cũ mất hẳn — nếu có thẻ nào đã in tem hay đã lên shop "
                    "thì mã trên đó không còn khớp nữa.",
                ),
                ACTION_SKU_RENUMBER,
            )
        return Reply(
            intent,
            (
                f"Cấp mã cho những thẻ trong cụm {target} đã sang cột "
                f"{column_name(COL_DOING)} mà còn trống; mã đã có giữ nguyên, "
                "thẻ chưa sang cột thì chờ người duyệt kéo rồi mới tới lượt.",
            ),
            ACTION_SKU_FILL,
        )

    if intent == INTENT_RUN:
        if brief.paused:
            return Reply(
                intent,
                (
                    "Thẻ này đang tạm dừng nên tôi chưa chạy. "
                    "Nhắn “tiếp tục” là tôi mở lại và chạy ngay lượt sau.",
                ),
            )
        if not brief.autorun:
            return Reply(
                intent,
                ("Tự chạy đang tắt ở cấu hình bot (ERP_AGENT_AUTORUN=0) nên tôi không nhận lượt chạy nào.",),
            )
        target = brief.root_task or brief.task
        return Reply(
            intent,
            (f"Đã nhận. Tôi xếp {target} vào lượt chạy kế tiếp." + _next_scan(brief),),
            ACTION_RUN,
        )

    if intent == INTENT_PAUSE:
        target = brief.root_task or brief.task
        if brief.paused:
            return Reply(intent, (f"{target} đang tạm dừng sẵn rồi — tôi không đụng vào.",), ACTION_PAUSE)
        return Reply(
            intent,
            (
                f"Đã tạm dừng {target}: tôi vẫn đọc phiếu 👍/👎 nhưng không tạo ảnh "
                "và không giao listing nữa. Nhắn “tiếp tục” để mở lại.",
            ),
            ACTION_PAUSE,
        )

    if intent == INTENT_RESUME:
        target = brief.root_task or brief.task
        if not brief.paused:
            return Reply(intent, (f"{target} có bị dừng đâu — tôi vẫn đang chạy bình thường.",), ACTION_RESUME)
        return Reply(
            intent,
            (f"Đã mở lại {target}. Tôi xếp thẻ vào lượt chạy kế tiếp." + _next_scan(brief),),
            ACTION_RESUME,
        )

    if intent == INTENT_ACCOUNT:
        return Reply(intent, _account_lines(brief))

    if intent == INTENT_LISTING:
        return Reply(intent, _listing_lines(brief) + _account_lines(brief))

    if intent == INTENT_HELP:
        return Reply(intent, HELP_LINES)

    return Reply(intent, ("Tôi chưa hiểu ý này.", *HELP_LINES))


def answer(content: str, brief: CardBrief) -> Reply:
    """Đường tắt: câu nói → câu trả lời."""
    return compose(understand(content), brief, parse_edits(content))


def as_record(comment: Mapping[str, Any], task: str, reply: Reply) -> Dict[str, Any]:
    """Một dòng kể lại lượt trả lời, cho tổng kết của ``run_once`` và cho log."""
    record = {
        "task": task,
        "comment": str(comment.get("name") or ""),
        "asked_by": str(comment.get("by_name") or comment.get("owner") or ""),
        "intent": reply.intent,
        "action": reply.action,
    }
    if reply.edits:
        # Kể ra cả lượt chạy khô: người bật ``dry_run`` muốn biết *sẽ* ghi gì
        # xuống thẻ, và đó chính là câu hỏi họ bật nó lên để hỏi.
        record["edits"] = dict(reply.edits)
    return record


__all__ = [
    "ACTION_NONE",
    "ACTION_PAUSE",
    "ACTION_RESUME",
    "ACTION_RUN",
    "ACTION_SET",
    "CardBrief",
    "ACTION_SKU_FILL",
    "ACTION_SKU_RENUMBER",
    "EDITABLE_FIELDS",
    "HELP_LINES",
    "INTENT_HELP",
    "INTENT_LISTING",
    "INTENT_PAUSE",
    "INTENT_RESUME",
    "INTENT_RUN",
    "INTENT_SET",
    "INTENT_SKU",
    "INTENT_STATUS",
    "INTENT_UNKNOWN",
    "Reply",
    "addressed_to_bot",
    "answer",
    "as_record",
    "compose",
    "has_trigger",
    "normalize",
    "normalize_account",
    "INTENT_SKU_FILL",
    "INTENT_SKU_RENUMBER",
    "parse_edits",
    "resolve_field",
    "sounds_like_an_order",
    "strip_trigger",
    "strip_trigger_raw",
    "understand",
]
