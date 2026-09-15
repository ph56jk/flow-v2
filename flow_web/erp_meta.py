"""Reading the "Metadata cho agent" block off a HaviGroup ERP Task.

An ERP Task carries two YAML blocks, both returned by ``taskDetail`` and by
nothing else (``taskBoard`` does not include them):

``meta``
    What a person typed in the *Thuộc tính* panel::

        action_1: listing
        acc: acc32

``meta_auto``
    What ERP keeps in sync by itself — ``_task``, ``_title``, ``_status``,
    ``_priority``, ``_due``, ``_labels``, ``_assignees``, ``_agents``.  Read
    only; writing a key with a leading underscore is refused by ERP.

The agent reads ``meta`` to learn two things the Task alone cannot say: **what
work this Task is** (``action_*``) and **which Etsy account it belongs to**
(``acc``).  Before this, the account was pinned per runner process by the
``LISTING2_ERP_MACHINE_ID`` env var, so one runner could serve exactly one
account and a Task could not say where it wanted to go.

The parser is deliberately a small YAML subset, not a YAML library: the panel
writes one ``key: value`` per line and nothing else, and Listing 2 has no YAML
dependency.  Anything it cannot read is skipped rather than raised — a typo in
a metadata line must never take down a listing sweep.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# ERP's own hint under the panel: "tên khoá chỉ gồm chữ thường không dấu, chữ
# số và gạch dưới, bắt đầu bằng chữ cái".  The system keys it generates add a
# leading underscore, so both shapes are accepted here.
_KEY_RE = re.compile(r"^_?[a-z][a-z0-9_]*$")
# Nhãn nào trên thẻ là tên một tài khoản Etsy.  Người vận hành gắn ``acc32``
# lên thẻ giống hệt cách họ gõ ``acc: acc32`` vào panel, nên hai đường phải ra
# cùng một chỗ.  Buộc đúng dạng ``acc`` + số để một cái nhãn "gấp" hay
# "chờ ảnh" không bị đọc nhầm thành tài khoản.
_ACCOUNT_LABEL_RE = re.compile(r"^acc[-_]?\d+$")
_ACTION_RE = re.compile(r"^action(?:_?(\d+))?$")
_DIGITS_RE = re.compile(r"(\d+)$")

# Keys that name the Etsy account, in the order they are trusted.
ACCOUNT_KEYS: Tuple[str, ...] = ("acc", "account", "etsy_acc", "etsy_account", "shop", "acc_id")
# Keys that pin one specific listing machine, overriding whatever the account
# would resolve to.
MACHINE_KEYS: Tuple[str, ...] = ("machine", "machine_id", "may", "pc", "vps")
# Keys that name a Google Flow browser profile.  Listing 2 does not route on
# this, but the image-generation half of the family (``erptrello``) picks its
# Flow account by profile label (``FLOW_CHROME_PROFILE_DIRS``), so the two
# repos read the same word for it when they are merged.
PROFILE_KEYS: Tuple[str, ...] = ("profile", "flow_profile", "flow_acc", "flow_account", "profile_label")
# Where ``taskDetail`` may name the Task above this one.  ERP's ``createTask``
# takes ``parentTask``, but the shape of the field it reads back has not been
# pinned down, so every plausible spelling is accepted and a Task with none of
# them simply has no parent as far as this module is concerned.
PARENT_KEYS: Tuple[str, ...] = ("parent_task", "parentTask", "parent", "parent_task_id", "parent_id")

# Keys that name the product a card belongs to.  This is the word a person
# types in the panel (``product: khan tay``); the SKU book turns it into the
# short name-part a SKU starts with.
#
# ``product_type`` đứng cuối là có chủ ý.  Trên bảng thật người ta khai kiểu
# hàng bằng chữ đó, nên phải đọc; nhưng ``product`` là chữ gõ có chủ đích cho
# đúng thẻ này, còn kiểu hàng chỉ là chỗ dựa khi không có nó — thẻ mang cả hai
# thì ``product`` thắng.
PRODUCT_KEYS: Tuple[str, ...] = (
    "product",
    "san_pham",
    "sanpham",
    "product_name",
    "productname",
    "product_type",
    "producttype",
    "loai_san_pham",
    "loaisanpham",
)
# Keys that hold the card's own SKU.  ``ma_sku``/``masku`` are what the panel
# gets typed into when the person is writing Vietnamese without the English
# word to hand.
SKU_KEYS: Tuple[str, ...] = ("sku", "ma_sku", "masku", "sku_code", "product_key", "productkey")
# Keys naming the Idea a card hangs under when the tree alone does not say it.
# ``dadidea`` is on the board already, typed by hand before this existed.
FATHER_IDEA_KEYS: Tuple[str, ...] = ("fatheridea", "father_idea", "dadidea", "dad_idea", "idea", "idea_id")
# Mã SKU của listing mẫu mà Review Lister chép ra listing mới.
COPY_SKU_KEYS: Tuple[str, ...] = ("copysku", "copy_sku", "template_sku", "templatesku", "template")

# Ô chỉ đúng cho **một** thẻ, nên không bao giờ chép từ thẻ cha xuống thẻ con.
# Mỗi thẻ một mã: chép ``sku`` xuống là cả cụm trùng mã.  ``ten_cu`` là tên
# cũ của chính thẻ, cất đi trước lượt đổi tên.  Liên kết lên thẻ trên cũng vậy:
# thẻ trên của thẻ con là thẻ cha, không phải thẻ trên của thẻ cha.  Các ô
# ``action_*`` bị chặn riêng bằng ``_ACTION_RE``: ``action_1: idea`` chép xuống
# là biến mỗi thẻ con thành một thẻ Idea tự đẻ con.  ``content`` do seller khai
# trên thẻ cha, cổng ảnh content cũng chỉ đọc thẻ cha: bot không ghi ô này.
# ``master_sku`` cũng là mã: chép xuống là thẻ con mang mã của thẻ cha.
NOT_INHERITED_KEYS = frozenset(
    SKU_KEYS
    + FATHER_IDEA_KEYS
    + tuple(key.lower() for key in PARENT_KEYS)
    + ("ten_cu", "content", "master_sku", "mastersku")
)
# Những cách viết khác nhau của cùng một ô.  Thẻ con khai ``account`` thì
# không nhận ``acc`` của thẻ cha: ``acc`` được tin trước, chép xuống là để
# thẻ cha thắng thẻ con.
_SAME_FIELD: Tuple[frozenset, ...] = (
    frozenset(ACCOUNT_KEYS),
    frozenset(MACHINE_KEYS),
    frozenset(PROFILE_KEYS),
    frozenset(PRODUCT_KEYS),
    frozenset(COPY_SKU_KEYS),
)

# Every spelling of "this Task is an Etsy listing job" seen in the panel.
LISTING_ACTIONS = frozenset(
    {
        "listing",
        "listings",
        "list",
        "etsy",
        "etsy_listing",
        "listing_etsy",
        "dang_listing",
        "len_listing",
    }
)


def normalize_action(value: Any) -> str:
    """``"Listing Etsy"``, ``"listing-etsy"`` và ``"Listing (Etsy)"`` là một action.

    Bỏ dấu tiếng Việt trước khi so.  ``LISTING_ACTIONS`` ghi ``dang_listing``,
    ``len_listing`` ở dạng không dấu, còn trên panel người ta gõ ``đăng
    listing`` — không bỏ dấu thì hai dòng ấy là mã chết, thẻ gõ đúng chính tả
    đứng im mà không có lỗi nào.

    ``đ`` đổi thành ``d`` *trước* khi bỏ dấu, vì ``unicodedata`` không tách
    được nó — nó là một chữ cái riêng chứ không phải ``d`` cộng dấu.  Thiếu
    bước ấy thì ``"đăng listing"`` thành ``"ang_listing"``.

    Mọi ký tự ngoài ``[a-z0-9]`` — khoảng trắng, gạch, ngoặc — gộp thành một
    ``_``.  Bỏ được cả dấu ngoặc là vì hàm này chỉ dùng để so với
    ``LISTING_ACTIONS``, mà tám chữ trong đó không có dấu câu nào: một chuỗi
    mất dấu câu chỉ khớp thêm khi phần chữ của nó vốn đã là listing.  Dấu
    ``,``/``;`` ngăn nhiều action được ``actions`` tách ra *trước* khi tới đây.
    Khoá của khối Thuộc tính đi đường ``_KEY_RE``, không qua đây.
    """
    text = str(value or "").strip().lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if ch.isascii())
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def normalize_token(value: Any) -> str:
    """Same slug rule the service uses for account and machine ids."""
    text = str(value or "").strip().lower()
    text = "".join(ch if (ch.isalnum() or ch in "_-") else "-" for ch in text).strip("-")
    return "" if text in ("", "default", "auto", "any", "none", "null") else text


def _scalar(raw: str) -> str:
    """One YAML scalar as the panel writes it, flattened to text.

    Lists become a comma-joined string because every consumer here wants text;
    ``null`` and an empty list both become ``""`` so callers test one thing.
    """
    text = str(raw or "").strip()
    if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
        return text[1:-1].strip()
    if text.startswith("[") and text.endswith("]"):
        items = [item.strip().strip("\"'") for item in text[1:-1].split(",")]
        return ", ".join(item for item in items if item)
    if text.startswith("{") and text.endswith("}"):
        return ""
    if text.lower() in {"null", "~", "none"}:
        return ""
    return text


def parse_meta_block(text: Any) -> Dict[str, str]:
    """Parse one metadata block into ``{key: value}``.

    Blank lines, comments, list items and anything without a ``:`` are skipped,
    as is any key ERP itself would refuse.  A repeated key keeps the last
    value, the way the panel's own save does.
    """
    values: Dict[str, str] = {}
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-") or ":" not in stripped:
            continue
        raw_key, _, raw_value = stripped.partition(":")
        key = raw_key.strip().strip("\"'").lower()
        if not _KEY_RE.match(key):
            continue
        values[key] = _scalar(raw_value)
    return values


def agent_users(detail: Optional[Mapping[str, Any]]) -> Tuple[str, ...]:
    """Bots ERP has assigned to a Task, in the order ERP returns them.

    The real assignment lives in ``taskDetail`` as ``agents[].bot_user`` — the
    same field the *Người phụ trách* box writes and ``addTaskAgent`` sets.  The
    ``meta_auto`` block only carries a rendered ``_agents`` line, used here as
    the fallback.  Reading it belongs next to the rest of "what this Task says
    about itself": the image half of the family already routes work by it.
    """
    source: Mapping[str, Any] = detail if isinstance(detail, Mapping) else {}
    users: List[str] = []
    for item in source.get("agents") or ():
        name = str((item or {}).get("bot_user") or "").strip() if isinstance(item, Mapping) else str(item or "").strip()
        if name and name not in users:
            users.append(name)
    return tuple(users)


def parent_task_id(detail: Optional[Mapping[str, Any]]) -> str:
    """The Task above this one, or ``""``.

    ERP does not push a parent's attributes down to its children — its
    ``createTask`` mutation takes no ``meta`` at all, and the image half of the
    family has to re-attach the parent's agents to every child by hand.  So
    inheritance, where we want it, is something this app does when it reads.
    """
    source: Mapping[str, Any] = detail if isinstance(detail, Mapping) else {}
    for key in PARENT_KEYS:
        value = source.get(key)
        if isinstance(value, Mapping):
            value = value.get("name") or value.get("id")
        text = str(value or "").strip()
        if text and text.lower() not in {"none", "null"}:
            return text
    return ""


@dataclass(frozen=True)
class TaskMeta:
    """The two metadata blocks of one ERP Task, parsed."""

    attributes: Dict[str, str] = field(default_factory=dict)
    auto: Dict[str, str] = field(default_factory=dict)
    raw: str = ""
    raw_auto: str = ""
    agents: Tuple[str, ...] = ()

    def get(self, *names: str) -> str:
        """First non-empty value among ``names``, user block before auto block."""
        for name in names:
            value = str(self.attributes.get(name) or "").strip()
            if value:
                return value
        for name in names:
            value = str(self.auto.get(name) or "").strip()
            if value:
                return value
        return ""

    @property
    def actions(self) -> List[str]:
        """Declared actions in panel order: ``action`` first, then ``action_1``…

        A single key may hold several actions (``action_1: listing, review``),
        which is why each value is split before it is normalized.
        """
        numbered: List[Tuple[int, str]] = []
        for key, value in self.attributes.items():
            match = _ACTION_RE.match(key)
            if not match or not str(value or "").strip():
                continue
            order = int(match.group(1)) if match.group(1) else 0
            numbered.append((order, str(value)))
        ordered: List[str] = []
        for _, value in sorted(numbered, key=lambda item: item[0]):
            for piece in re.split(r"[,;]", value):
                action = normalize_action(piece)
                if action and action not in ordered:
                    ordered.append(action)
        return ordered

    @property
    def declares_actions(self) -> bool:
        return bool(self.actions)

    def wants(self, wanted: Iterable[str]) -> bool:
        """Does the Task ask for one of ``wanted``?

        A Task with no ``action_*`` at all answers ``False``; callers decide
        whether "said nothing" means skip or means "carry on as before".
        """
        allowed = {normalize_action(item) for item in wanted}
        return any(action in allowed for action in self.actions)

    @property
    def is_listing(self) -> bool:
        return self.wants(LISTING_ACTIONS)

    @property
    def account_id(self) -> str:
        return normalize_token(self.get(*ACCOUNT_KEYS))

    @property
    def machine_id(self) -> str:
        return normalize_token(self.get(*MACHINE_KEYS))

    @property
    def flow_profile(self) -> str:
        """Flow browser profile label, kept as written.

        Profile labels are matched against ``FLOW_CHROME_PROFILE_DIRS`` by
        their text, and one of them may legitimately be called ``default``, so
        this one is not slugged the way an account id is.
        """
        return self.get(*PROFILE_KEYS)

    @property
    def product(self) -> str:
        """The product this card is about, as the person wrote it.

        Kept verbatim rather than slugged: it is a display name (``khan tay``,
        ``bờm``) that a person will read back in the panel, and the SKU book
        does its own accent-insensitive matching on it.
        """
        return self.get(*PRODUCT_KEYS)

    @property
    def sku(self) -> str:
        """The card's own SKU, upper-cased.

        A SKU is a code, and a code typed as ``kt_2_009`` means the same thing
        as ``KT_2_009``; folding here is what stops the generator from handing
        out a number a lower-cased sibling already holds.
        """
        return self.get(*SKU_KEYS).upper()

    @property
    def father_idea(self) -> str:
        """The Idea card this one hangs under, when the panel names it.

        The parent link in ERP is the normal answer; this is the override for
        a card that was moved, or created outside the tree, and still belongs
        to an Idea for numbering purposes.
        """
        return self.get(*FATHER_IDEA_KEYS)

    @property
    def labels(self) -> Tuple[str, ...]:
        """Nhãn ERP đang gắn trên thẻ, đã chuẩn hoá thành slug.

        ERP tự đồng bộ chúng xuống dòng ``_labels`` của khối ``meta_auto``
        (``_labels: [acc32, gap]``), và ``_scalar`` đã ép danh sách ấy thành
        chuỗi nối bằng dấu phẩy trước khi tới đây.
        """
        rendered = str(self.auto.get("_labels") or "").strip()
        if not rendered:
            return ()
        found: List[str] = []
        for part in re.split(r"[,;]", rendered):
            slug = normalize_token(part)
            if slug and slug not in found:
                found.append(slug)
        return tuple(found)

    @property
    def agent_users(self) -> Tuple[str, ...]:
        """Assigned bots: the ERP field first, the ``_agents`` line as fallback."""
        if self.agents:
            return self.agents
        rendered = str(self.auto.get("_agents") or "").strip()
        if not rendered:
            return ()
        return tuple(part.strip() for part in re.split(r"[,;]", rendered) if part.strip())

    def assigned_to(self, bot_user: Any) -> bool:
        """Is ``bot_user`` one of the bots on this Task?"""
        wanted = str(bot_user or "").strip().lower()
        return bool(wanted) and any(wanted == item.lower() for item in self.agent_users)


def _user_block(detail: Mapping[str, Any]) -> str:
    """The person-typed block, whichever name the ERP call gave it.

    ``taskDetail`` and ``taskFull`` return it as ``meta``; the ``taskMeta``
    query returns the same text as ``meta_custom``.  Reading only ``meta``
    made every card look blank when it was fetched the second way.
    """
    for key in ("meta", "meta_custom"):
        text = str(detail.get(key) or "")
        if text.strip():
            return text
    return ""


def render_meta_block(values: Mapping[str, Any], original: Any = "") -> str:
    """Write ``{key: value}`` back out the way the *Thuộc tính* panel does.

    ``updateTaskMeta`` replaces the whole block, so anything not rendered here
    is deleted from the card.  That makes the rules strict:

    * every line of ``original`` keeps its place and its spelling, including
      keys this app knows nothing about and keys left deliberately blank —
      an empty ``acc:`` is a person's note that the account is still to come,
      and silently dropping it edits their card;
    * a key ``values`` changes is rewritten in place, not appended, so the
      panel does not reorder itself under the person every time a bot writes;
    * a duplicated key (the panel does allow typing ``sku:`` twice) collapses
      to one line at the first position, matching what the parser already
      reads — last value wins;
    * keys ERP itself maintains (leading underscore) are never written back.
    """
    updates = {
        str(key).strip().lower(): ("" if value is None else str(value).strip())
        for key, value in (values or {}).items()
        if _KEY_RE.match(str(key).strip().lower()) and not str(key).strip().startswith("_")
    }
    lines: List[str] = []
    seen: set[str] = set()
    for line in str(original or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        raw_key, sep, raw_value = stripped.partition(":")
        key = raw_key.strip().strip("\"'").lower()
        if not sep or not _KEY_RE.match(key) or key.startswith("_"):
            # A comment, a list item, or something the parser skips: it is not
            # ours to interpret, so it is carried through untouched.
            lines.append(stripped)
            continue
        if key in seen:
            continue
        seen.add(key)
        value = updates.get(key, _scalar(raw_value)) if key in updates else raw_value.strip()
        lines.append(f"{key}: {value}".rstrip())
    for key, value in updates.items():
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"{key}: {value}".rstrip())
    return "\n".join(lines)


def task_meta(source: Optional[Mapping[str, Any]]) -> TaskMeta:
    """Build :class:`TaskMeta` from a ``taskDetail`` payload or a normalized card.

    Accepts either shape so callers do not have to remember which one they
    hold: the raw ERP detail (``meta`` / ``meta_auto``) and the card the ERP
    adapter builds from it (same keys, plus ``_erp_raw``) both work.
    """
    detail: Mapping[str, Any] = source if isinstance(source, Mapping) else {}
    nested = detail.get("_erp_raw")
    if not str(_user_block(detail) or detail.get("meta_auto") or "").strip() and isinstance(nested, Mapping):
        detail = nested
    raw = _user_block(detail)
    raw_auto = str(detail.get("meta_auto") or "")
    return TaskMeta(
        attributes=parse_meta_block(raw),
        auto=parse_meta_block(raw_auto),
        raw=raw,
        raw_auto=raw_auto,
        agents=agent_users(detail),
    )


def inherit(child: TaskMeta, parent: Optional[TaskMeta]) -> TaskMeta:
    """The child Task, with the parent filling in only what the child left out.

    A line the child wrote always wins — inheriting must never be able to move
    a Task somewhere its own metadata did not ask for.  ``meta_auto`` is never
    inherited: it describes one Task and nothing else.  Agents are inherited
    only when the child has none, which mirrors how children are created with
    the parent's agents in the first place.
    """
    if parent is None or not (parent.attributes or parent.agents):
        return child
    merged = dict(parent.attributes)
    merged.update(child.attributes)
    return TaskMeta(
        attributes=merged,
        auto=dict(child.auto),
        raw=child.raw,
        raw_auto=child.raw_auto,
        agents=child.agents or parent.agents,
    )


def missing_from_parent(child: Mapping[str, Any], parent: Mapping[str, Any]) -> Dict[str, str]:
    """Những ô của thẻ cha cần **ghi** xuống thẻ con.

    Khác ``inherit``: ``inherit`` chỉ ghép lúc đọc, còn Review Lister và bảng
    ERP đọc đúng khối của thẻ con.  Thẻ cha khai một lần mà thẻ con vẫn trống
    trơn thì mọi thẻ con đều "thiếu".

    Chỉ điền ô còn trống.  Ô thẻ con đã gõ — kể cả gõ bằng một cách viết khác
    của cùng ô — là của thẻ con.  Ô thẻ cha để trống không được chép: ``acc:``
    trống là "chưa có", không phải "xoá đi".  Ô của riêng từng thẻ
    (``NOT_INHERITED_KEYS``, ``action_*``) và ô hệ thống (``_…``) không bao giờ
    xuống.
    """
    own = {str(key).strip().lower(): str(value or "").strip() for key, value in (child or {}).items()}
    filled = {key for key, value in own.items() if value}
    wanted: Dict[str, str] = {}
    for raw_key, raw_value in (parent or {}).items():
        key = str(raw_key).strip().lower()
        value = str(raw_value or "").strip()
        if not value or not _KEY_RE.match(key) or key.startswith("_"):
            continue
        if key in NOT_INHERITED_KEYS or _ACTION_RE.match(key):
            continue
        family = next((group for group in _SAME_FIELD if key in group), frozenset((key,)))
        if family & filled:
            continue
        wanted[key] = value
    return wanted


@dataclass(frozen=True)
class AccountRouting:
    """Where a Task should run, worked out from its metadata."""

    account_id: str = ""
    machine_id: str = ""
    account_source: str = ""
    machine_source: str = ""
    known_account: bool = False

    @property
    def resolved(self) -> bool:
        return bool(self.account_id or self.machine_id)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "account_id": self.account_id,
            "machine_id": self.machine_id,
            "account_source": self.account_source,
            "machine_source": self.machine_source,
            "known_account": self.known_account,
        }


def machine_for_account(account_id: str, machine_ids: Sequence[str]) -> str:
    """Convention fallback: ``acc32`` runs on the machine numbered 32.

    The fleet is named ``etsy-vn32``, ``etsy-16``, ``capa-hinh``…  Matching on
    the trailing number is what an operator means by "acc32", and it is only
    used when nothing explicit said otherwise.  An ambiguous number (two
    machines ending in 32) resolves to nothing rather than to a guess.
    """
    account = normalize_token(account_id)
    if not account:
        return ""
    known = [normalize_token(item) for item in machine_ids]
    known = [item for item in known if item]
    if account in known:
        return account
    digits = _DIGITS_RE.search(account)
    if not digits:
        return ""
    number = str(int(digits.group(1)))
    matches = []
    for machine in known:
        found = _DIGITS_RE.search(machine)
        if found and str(int(found.group(1))) == number:
            matches.append(machine)
    return matches[0] if len(matches) == 1 else ""


def account_from_labels(labels: Sequence[str], known_accounts: Sequence[str] = ()) -> str:
    """Tài khoản mà mấy cái nhãn trên thẻ đang nói tới, hoặc ``""``.

    Một nhãn được coi là tên tài khoản khi nó nằm trong danh sách tài khoản đã
    biết, hoặc khi nó viết đúng quy ước ``acc`` + số.  Danh sách đã biết được
    xét trước, vì một shop tên ``havi-home`` sẽ không bao giờ khớp quy ước.

    Hai nhãn cùng chỉ tài khoản thì trả về rỗng chứ không đoán bừa — cùng lẽ
    với :func:`machine_for_account`.  Thẻ đó sẽ đi tiếp như thẻ không tag, và
    người dán nhãn còn thấy được là mình vừa dán hai cái chỏi nhau.
    """
    known = {normalize_token(item) for item in known_accounts}
    known.discard("")
    slugs = [normalize_token(item) for item in labels]
    hits = [slug for slug in slugs if slug and (slug in known or _ACCOUNT_LABEL_RE.match(slug))]
    unique = list(dict.fromkeys(hits))
    return unique[0] if len(unique) == 1 else ""


def resolve_routing(
    meta: TaskMeta,
    *,
    known_accounts: Sequence[str] = (),
    known_machines: Sequence[str] = (),
    account_machines: Optional[Mapping[str, str]] = None,
) -> AccountRouting:
    """Turn ``acc: acc32`` into "which account, which machine".

    Order for the machine, most explicit first:

    1. ``machine:`` written on the Task itself,
    2. the machine configured for that account (``EtsyAccount.etsy_machine_id``
       or the ``FLOW_ERP_ACC_MACHINES`` map),
    3. the fleet-naming convention (``acc32`` → ``etsy-vn32``).

    Nothing is invented: an account with no machine anywhere returns an empty
    ``machine_id``, which leaves the queued task claimable by any machine of
    that account — the behaviour before metadata existed.
    """
    account_id = meta.account_id
    account_source = "meta_acc" if account_id else ""
    known_account_slugs = {normalize_token(item) for item in known_accounts}
    known_account_slugs.discard("")
    if not account_id:
        # Người làm listing viết bài bằng tay rồi chỉ gắn nhãn lên thẻ; dòng
        # ``acc:`` là thứ họ không phải gõ nữa.  Nhãn đứng *sau* dòng gõ tay
        # vì dòng gõ tay cụ thể hơn: dán nhầm nhãn không được phép kéo một thẻ
        # đã ghi rõ tài khoản đi shop khác.
        account_id = account_from_labels(meta.labels, known_accounts)
        account_source = "label" if account_id else ""
    configured = {normalize_token(key): normalize_token(value) for key, value in (account_machines or {}).items()}

    machine_id = meta.machine_id
    machine_source = "meta_machine" if machine_id else ""
    if not machine_id and account_id:
        machine_id = configured.get(account_id, "")
        machine_source = "account_config" if machine_id else ""
    if not machine_id and account_id:
        machine_id = machine_for_account(account_id, known_machines)
        machine_source = "fleet_number" if machine_id else ""

    return AccountRouting(
        account_id=account_id,
        machine_id=machine_id,
        account_source=account_source,
        machine_source=machine_source,
        known_account=bool(account_id and account_id in known_account_slugs),
    )
