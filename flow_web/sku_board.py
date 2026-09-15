"""SKU & thuộc tính: bot ghi số, bảng điều khiển vẽ.

Hai nửa, chạy ở hai tiến trình khác nhau:

* Bên bot — :func:`snapshot` và :func:`write_status`. Mỗi lượt quét,
  ``AgentBot.run_once`` đã có sẵn các cây ``taskFull`` trong tay. Hai hàm này
  chỉ đọc lại đúng những cây ấy rồi ghi ``sku_status.json``. Không thêm
  request nào: ERP chỉ cho 60 request/phút, và bot đang dùng chung trần đó.
  Thẻ nằm ngoài cây bị cắt thì đọc từ dòng ``taskBoard`` bot đã có trong
  lượt quét (``rows``): dòng bảng có cột và ``custom_sku``.
* Bên bảng — :func:`build_sku`. Máy chủ bảng đọc tệp qua bản Listing
  (``/files/downloads/sku_status.json``), cùng lối với
  ``review_lister_status.json``. Máy chủ bảng không gọi ERP.

Vì sao cần: ngày 12/09 có 37 thẻ nằm ở Đang làm mà chưa có SKU, seller chờ
hơn một giờ, không ai nhìn thấy. ERP còn cắt ``taskFull`` ở 60 node: cụm
159 thẻ con thì bot chỉ thấy 60, phần còn lại im lặng. Bảng này nói ra hai
chuyện đó.

Tệp nằm cạnh ``review_lister_status.json``: đặt ``ERP_SKU_STATUS_FILE`` cho
bot, hoặc để bot dùng ``ERP_LISTING_FILES_DIR`` như review_lister.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .erp_meta import ACCOUNT_KEYS, COPY_SKU_KEYS, TaskMeta, account_from_labels, task_meta
from .image_board import ERP_TASK_URL
from .listing_board import VN, _int, _iso, _minutes, _seconds, parse_time
from .listing_watch import mask
from .pipeline import COL_CANCELLED, COL_DOING, ORDER, column_name, normalize_status
from .sku import _ancestors, _rows_by_name, card_from_node, card_is_ready, la_ma_doan, strip_accents

log = logging.getLogger(__name__)

SKU_STATUS_FILE = "sku_status.json"
#: Giây một lượt quét khi tệp không ghi — bằng ``DEFAULT_POLL_SECONDS`` của bot.
DEFAULT_EVERY = 120
#: Bốn thuộc tính người khai trên thẻ cha. ``content`` hiện kèm nhưng không bắt buộc.
ATTRIBUTES = ("product_type", "product_group", "fulfillment", "sales_channel")
#: Dấu ``service.py`` gắn vào lời nhắc "bảng SKU chưa có dòng" trên thẻ cha.
SKU_NOTE_MARK = "[AGENT_BOT_SKU]"
SKU_NOTE_PREFIX = "Chưa có mã trong bảng SKU cho"

#: Vì sao một thẻ chưa có SKU. Thứ tự này cũng là thứ tự xếp: nặng đứng trước.
REASONS = ("cut", "product", "book", "wait", "images", "todo")

_warned_no_path = False


# ── bên bot: đọc cây, ghi tệp ─────────────────────────────────────────


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _key(value: Any) -> str:
    """So tên sản phẩm sau khi bỏ dấu: người gõ ``khan tay`` lẫn ``khăn tay``."""
    return " ".join(strip_accents(_text(value)).lower().split())


def _root_of(tree: Any) -> Mapping[str, Any]:
    if not isinstance(tree, Mapping):
        return {}
    root = tree.get("root")
    return root if isinstance(root, Mapping) else tree


def _full_nodes(root: Mapping[str, Any]) -> List[Tuple[Mapping[str, Any], str]]:
    """Mọi thẻ đầy đủ trong ``subtasks``, lồng bao nhiêu tầng cũng đi hết.

    Trả ``(node, mã thẻ cha)``. ``children`` không dùng ở đây: nó chỉ có tên
    và tiêu đề, không có ``meta``.
    """
    out: List[Tuple[Mapping[str, Any], str]] = []
    seen = {_text(root.get("name"))}

    def walk(node: Mapping[str, Any]) -> None:
        for child in node.get("subtasks") or []:
            if not isinstance(child, Mapping):
                continue
            name = _text(child.get("name"))
            if not name or name in seen:
                continue
            seen.add(name)
            out.append((child, _text(node.get("name"))))
            walk(child)

    walk(root)
    return out


def _thin_nodes(root: Mapping[str, Any], full: Iterable[Tuple[Mapping[str, Any], str]]) -> List[Tuple[Mapping[str, Any], str]]:
    """Thẻ có tên trong ``children`` mà không có trong ``subtasks``: ERP cắt mất.

    ``children`` có thể đủ (81) trong khi ``subtasks`` bị cắt (59). Những thẻ
    rơi vào khe đó bot không đọc được ``meta``, nên không bao giờ được cấp mã.
    """
    seen = {_text(root.get("name"))} | {_text(node.get("name")) for node, _ in full}
    out: List[Tuple[Mapping[str, Any], str]] = []
    for parent in [root] + [node for node, _ in full]:
        for child in parent.get("children") or []:
            if not isinstance(child, Mapping):
                continue
            name = _text(child.get("name"))
            if name and name not in seen:
                seen.add(name)
                out.append((child, _text(parent.get("name"))))
    return out


def _unlisted(root: Mapping[str, Any]) -> Dict[str, Tuple[str, Optional[datetime]]]:
    """Sản phẩm mà ``service.py`` đã nhắc "bảng SKU chưa có dòng" trên thẻ cha, kèm giờ nhắc.

    Service không gỡ lời nhắc khi bảng có dòng, nên lời nhắc cũ đi được. Giờ
    lấy ở ``creation`` của bình luận, không có thì ``modified``. Nhiều lời
    nhắc cùng sản phẩm thì lấy lời mới nhất. ERP trả giờ không đuôi múi, đọc
    theo giờ VN. Không có giờ thì để ``None``, không đoán.
    """
    found: Dict[str, Tuple[str, Optional[datetime]]] = {}
    for comment in root.get("comments") or []:
        if not isinstance(comment, Mapping):
            continue
        content = _text(comment.get("content"))
        if SKU_NOTE_MARK not in _text(comment.get("meta")) and not content.startswith(SKU_NOTE_PREFIX):
            continue
        name = content.split("“", 1)[1].split("”", 1)[0] if "“" in content else ""
        at = parse_time(comment.get("creation") or comment.get("modified"), naive=VN)
        _, known = found.get(_key(name), ("", None))
        if known and (at is None or at < known):
            continue
        found[_key(name)] = (name, at)
    return found


def _clock(at: datetime, now: datetime) -> str:
    """Giờ VN: ``10:29`` nếu cùng ngày với lượt quét, không thì ``11/09 10:29``."""
    local = at.astimezone(VN)
    return local.strftime("%H:%M") if local.date() == now.astimezone(VN).date() else local.strftime("%d/%m %H:%M")


def _declared(own: str, parent: str) -> Tuple[str, str]:
    """``ok``: thẻ con có. ``inherit``: thẻ cha có, bot sẽ chép xuống. ``missing``: không ai có."""
    if own:
        return "ok", own
    if parent:
        return "inherit", parent
    return "missing", ""


def _account(meta: TaskMeta) -> str:
    return _text(meta.get(*ACCOUNT_KEYS)) or _text(account_from_labels(meta.labels))


def _attributes(meta: TaskMeta) -> Dict[str, str]:
    values = {name: _text(meta.get(name)) for name in ATTRIBUTES}
    # Việc đánh số đọc sản phẩm qua mọi tên gọi của nó (``product``, ``san_pham``…).
    values["product_type"] = values["product_type"] or _text(meta.product)
    return values


def _columns(statuses: Iterable[str]) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for status in statuses:
        canonical = normalize_status(status) or _text(status)
        counts[canonical] = counts.get(canonical, 0) + 1
    known = list(ORDER) + [COL_CANCELLED]
    order = [s for s in known if s in counts] + [s for s in counts if s not in known]
    return [{"status": s, "name": column_name(s) if s else "chưa rõ cột", "n": counts[s]} for s in order]


def _book_missing(book: Any, product: str) -> bool:
    if book is None or not product:
        return False
    try:
        _code, source = book.lookup(product)
    except Exception:  # bảng hỏng thì thôi, lời nhắc của service vẫn còn
        return False
    return la_ma_doan(source)


def _book_has(book: Any, product: str) -> bool:
    """Bảng mã tra ra dòng thật cho ``product``, không phải mã đoán."""
    if book is None or not product:
        return False
    try:
        _code, source = book.lookup(product)
    except Exception:  # bảng hỏng thì không gỡ gì
        return False
    return not la_ma_doan(source)


def _card(node: Mapping[str, Any], parent: str, cluster: str, root_meta: TaskMeta,
          unlisted: Mapping[str, Tuple[str, Optional[datetime]]], book: Any, pending_images: Any,
          now: datetime) -> Dict[str, Any]:
    card = card_from_node(node)
    meta = card.meta
    canonical = normalize_status(card.status)
    cancelled = canonical == COL_CANCELLED
    sku = _text(meta.sku)
    product = _text(meta.product) or _text(root_meta.product)
    reason, why, note_at = "", "", None
    if not sku and not cancelled:
        # Xét từ chắc tới đoán, cùng thứ tự với kế hoạch đánh mã trong sku.py:
        # cột trước, product sau, bảng SKU sau cùng. Lời nhắc "bảng SKU chưa
        # có dòng" nằm mãi trên thẻ gốc nên cũ đi được: 04628 có lời nhắc lúc
        # 10:29, mà 10:29:14 bảng đã có dòng. Vì vậy nó xét cuối, kèm giờ ghi.
        # Cây bị cắt không chặn thẻ bot thấy: hook đánh mã cả cụm từ gốc.
        # ``cut`` chỉ dành cho thẻ ngoài cây (``_cut_card``).
        if not card_is_ready(card):
            # Ảnh chờ phiếu chỉ giữ thẻ ở Cần làm: ``card_is_ready`` chỉ đọc cột.
            pending = pending_images(node)
            if pending:
                reason, why = "images", f"còn {pending} ảnh chờ duyệt"
            else:
                reason, why = "todo", f"chưa sang Đang làm (đang ở {column_name(card.status) or 'cột chưa rõ'})"
        elif not product:
            reason, why = "product", "chưa khai sản phẩm, chưa tra được bảng SKU"
        elif _key(product) in unlisted or _book_missing(book, product):
            note_at = unlisted.get(_key(product), ("", None))[1]
            reason = "book"
            why = f"bảng SKU chưa có dòng cho “{product}”" + (f" (bot ghi {_clock(note_at, now)})" if note_at else "")
        else:
            reason, why = "wait", "đã tới lúc, chờ bot đánh mã"

    account_state, account = _declared(_account(meta), _account(root_meta))
    copysku_state, copysku = _declared(_text(meta.get(*COPY_SKU_KEYS)), _text(root_meta.get(*COPY_SKU_KEYS)))
    # Chỉ thẻ đi đăng Etsy mới cần account/copysku. Thẻ không khai việc gì thì
    # bot coi là thẻ đăng, như ``is_listing`` của nó.
    listing = root_meta.is_listing or meta.is_listing or not (root_meta.declares_actions or meta.declares_actions)
    if cancelled or not listing:
        account_state = "" if account_state == "missing" else account_state
        copysku_state = "" if copysku_state == "missing" else copysku_state

    return {
        "task": card.task_id,
        "subject": card.subject,
        "cluster": cluster,
        "parent": parent,
        "status": card.status,
        "column": column_name(card.status),
        "seen": True,
        # Mã và cột đọc từ đâu: ``tree`` là cây ``taskFull``, ``board`` là dòng ``taskBoard``.
        "source": "tree",
        "sku": sku,
        "product": product,
        "reason": reason,
        "why": why,
        # Giờ bot ghi lời nhắc "bảng SKU chưa có dòng", để người xem tự so.
        "note_at": _iso(note_at),
        # Đã tới lúc cấp mã (Đang làm hoặc cột sau) mà vẫn chưa có.
        "working_no_sku": not sku and canonical in ORDER[1:],
        "account": account,
        "account_state": account_state,
        "copysku": copysku,
        "copysku_state": copysku_state,
        "done": "done" in meta.labels,
    }


def _cut_card(node: Mapping[str, Any], parent: str, cluster: str) -> Dict[str, Any]:
    status = _text(node.get("status"))
    return {
        "task": _text(node.get("name")),
        "subject": _text(node.get("subject")),
        "cluster": cluster,
        "parent": parent,
        "status": status,
        "column": column_name(status) if status else "",
        "seen": False,
        "source": "",
        "sku": "",
        "product": "",
        # Không phải "thiếu mã": bot không có nguồn nào để biết thẻ có mã chưa.
        "reason": "cut",
        "why": "chưa đọc được (cây bị cắt)",
        "note_at": "",
        "working_no_sku": False,
        "account": "",
        "account_state": "",
        "copysku": "",
        "copysku_state": "",
        "done": False,
    }


def _row_card(node: Mapping[str, Any], row: Mapping[str, Any], parent: str, cluster: str, root_meta: TaskMeta,
              unlisted: Mapping[str, Tuple[str, Optional[datetime]]], book: Any, now: datetime) -> Dict[str, Any]:
    """Thẻ ngoài cây bị cắt, đọc từ dòng ``taskBoard`` bot đã có trong lượt quét.

    Dòng bảng có cột và ``custom_sku`` (ô ERP giữ mã), không có bình luận hay
    khối Thuộc tính. Có mã thì thẻ có mã. Không có mã thì xét lý do như thẻ
    trong cây: Đang làm mà trống ``custom_sku`` là thiếu mã thật. Account và
    copysku thì dòng không nói, nên để trống chứ không báo "thiếu".
    """
    merged = {**node, **row}
    out = _card(merged, parent, cluster, root_meta, unlisted, book, lambda _node: 0, now)
    sku = out["sku"] or _text(row.get("custom_sku")).upper()
    if sku:
        out.update({"sku": sku, "reason": "", "why": "", "note_at": "", "working_no_sku": False})
    if "meta" not in merged:
        out.update({"account": "", "account_state": "", "copysku": "", "copysku_state": ""})
    out.update({"seen": False, "source": "board"})
    return out


def _sort_key(card: Mapping[str, Any]) -> Tuple[Any, ...]:
    reason = card.get("reason") or ""
    if reason:
        rank = REASONS.index(reason) if reason in REASONS else len(REASONS)
    elif card.get("account_state") == "missing" or card.get("copysku_state") == "missing":
        rank = len(REASONS)
    else:
        rank = len(REASONS) + 1
    task = _text(card.get("task"))
    number = _int(task.rsplit("-", 1)[-1]) or 0
    return (not card.get("working_no_sku"), rank, _text(card.get("cluster")), number, task)


def totals(clusters: List[Mapping[str, Any]], cards: List[Mapping[str, Any]]) -> Dict[str, int]:
    """Số tổng cho ô KPI. Bot ghi, bảng tính lại từ đúng danh sách nó vẽ."""
    return {
        "clusters": len(clusters),
        "cards": len(cards),
        "working_no_sku": sum(1 for c in cards if c.get("working_no_sku")),
        "truncated": sum(1 for c in clusters if c.get("truncated")),
        "unseen": sum(_int(c.get("unseen")) or 0 for c in clusters),
        "missing_attrs": sum(1 for c in clusters if c.get("missing")),
        "missing_account": sum(1 for c in cards if c.get("account_state") == "missing"),
        "missing_copysku": sum(1 for c in cards if c.get("copysku_state") == "missing"),
        "done": sum(1 for c in cards if c.get("done")),
        # Thẻ ngoài cây không có dòng bảng: chưa đọc được, không phải thiếu mã.
        "unread": sum(1 for c in cards if c.get("reason") == "cut"),
        "from_board": sum(1 for c in cards if c.get("source") == "board"),
    }


# ── sổ bot giữ bên ERP ────────────────────────────────────────────────
# Bot giữ tám sổ trên đĩa; bảng trước đây chỉ dùng hai. Phần dưới đây gom
# phần còn lại lại thành một khối để bảng vẽ. Hàm thuần: nhận sổ, trả dict.

#: Cửa sổ của ``SharedRateLimiter`` — sổ nhịp chỉ giữ mốc trong ngần này giây.
RATE_WINDOW_S = 60.0


def _chup(lay: Any, rong: Any) -> Any:
    """Bản sao của một sổ bot đang giữ. Chạm nhau một nhịp thì thử lại.

    Gom sổ chạy trong thread, làn nhanh có thể đang sửa đúng sổ ấy: Python ném
    ``RuntimeError`` giữa chừng. Bỏ một sổ còn hơn bỏ cả khối.
    """
    for _ in range(3):
        try:
            return lay()
        except RuntimeError:
            continue
    return rong


def _names(value: Any) -> List[str]:
    """Danh sách tên bảng, bỏ rỗng, giữ nguyên thứ tự bot ghi."""
    if not isinstance(value, (list, tuple)):
        return []
    items = _chup(lambda: list(value), [])
    return [name for name in (_text(item).upper() for item in items) if name]


def _stamp(value: Any, now: datetime) -> Dict[str, Any]:
    """Một mốc giờ trong sổ: giờ ISO và đã bao lâu. Giờ hỏng thì rỗng, không ném."""
    at = parse_time(value)
    return {"at": _iso(at), "age_s": _seconds(at, now)}


def _tasks(book: Any, now: datetime, field: str) -> List[Dict[str, Any]]:
    """Sổ ``{thẻ: giá trị}`` thành danh sách dòng có link sang ERP."""
    if not isinstance(book, Mapping):
        return []
    rows: List[Dict[str, Any]] = []
    for task, value in _chup(lambda: list(book.items()), []):
        name = _text(task)
        if not name:
            continue
        row = {"task": name, "link": ERP_TASK_URL + name}
        if field == "at":
            row.update(_stamp(value, now))
        else:
            row[field] = _text(value)
        rows.append(row)
    return rows


def bot_brain(state: Any, *, now: Optional[datetime] = None, ledger: Any = None,
              categories: Any = None, book_rows: Any = None,
              rate_calls: Iterable[Any] = (), limits: Any = None) -> Dict[str, Any]:
    """Mọi thứ bot đang nắm bên ERP, gói lại cho bảng. Hàm thuần: không đọc đĩa.

    ``state`` là ``AgentBotState`` (chỉ đọc thuộc tính, không import bot).
    ``rate_calls`` là sổ ``erp-agent-nhip.json`` — danh sách mốc epoch.
    ``limits`` là **cả hai** trần ERP: ``agent`` (bot + làn nhanh) và
    ``graphql`` (mọi lượt của service, gồm tách thẻ con). Hai limiter không
    biết nhau, nên bảng phải nói cả hai chứ không gộp thành một số.

    Sổ nào hỏng thì phần ấy rỗng: bảng mất một khối còn hơn bot ngừng quét.
    """
    now = now or datetime.now(timezone.utc)

    projects = _names(getattr(state, "projects", None))
    fast_lane = _names(getattr(state, "fast_lane_projects", None))
    in_lane = set(fast_lane)
    outside = [name for name in projects if name not in in_lane]

    # Dừng lâu nhất lên đầu: sổ này không tự hết hạn, thẻ nằm dưới đáy là thẻ
    # dễ bị quên nhất.
    paused = _tasks(getattr(state, "paused", None), now, "at")
    paused.sort(key=lambda row: (row["age_s"] is None, -(row["age_s"] or 0.0), row["task"]))
    warned = _tasks(getattr(state, "warned_columns", None), now, "column")
    warned.sort(key=lambda row: row["task"])

    runs = _tasks(getattr(state, "runs", None), now, "at")
    newest = min((r for r in runs if r["age_s"] is not None),
                 key=lambda r: r["age_s"], default=None)
    last_run = ({"task": newest["task"], "link": newest["link"], "at": newest["at"],
                 "age_s": newest["age_s"]}
                if newest else {"task": "", "link": "", "at": "", "age_s": None})

    handled = getattr(state, "handled", None)
    listed = getattr(state, "listed", None)
    brain_calls = getattr(state, "brain_calls", None)
    book = _book(book_rows)

    return {
        "bot_user": _text(getattr(state, "bot_user", "")),
        "projects": projects,
        "fast_lane": fast_lane,
        "outside_fast_lane": outside,
        "paused": paused,
        "warned_columns": warned,
        "last_run": last_run,
        "counts": {
            "projects": len(projects),
            "fast_lane": len(fast_lane),
            "outside_fast_lane": len(outside),
            "paused": len(paused),
            "warned_columns": len(warned),
            "handled": len(handled) if isinstance(handled, Mapping) else 0,
            "listed": len(listed) if isinstance(listed, Mapping) else 0,
            "runs": len(runs),
            "brain_calls": len(brain_calls) if isinstance(brain_calls, (list, tuple)) else 0,
        },
        "rate": _rate(rate_calls, limits, now),
        "ledger": _ledger(ledger),
        "categories": _categories(categories),
        "book": book,
        "counts_extra": {
            "categories_no_prefix": _no_prefix(categories),
            "book_rows": _book_size(book_rows),
            "book_multi": sum(1 for row in book if row["alternates"]),
        },
    }


def _load_json(path: Path) -> Any:
    """Đọc một sổ. Thiếu tệp hay tệp hỏng đều trả ``None``, không ném."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _limit(env: Mapping[str, str], key: str) -> Optional[float]:
    """Trần đọc từ môi trường. Chưa đặt thì ``None`` — bảng không đoán hộ."""
    raw = _text(env.get(key))
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def brain_from_disk(state: Any, *, data_dir: Any = None, env: Optional[Mapping[str, str]] = None,
                    now: Optional[datetime] = None, book_rows: Any = None) -> Dict[str, Any]:
    """Gom ba sổ trên đĩa + hai trần trong môi trường rồi gọi ``bot_brain``.

    Tách khỏi ``bot_brain`` để phần thuần vẫn test được mà không cần đĩa.
    """
    env = os.environ if env is None else env
    if data_dir is None:
        from .paths import DATA_DIR
        data_dir = DATA_DIR
    folder = Path(data_dir)

    raw_nhip = _text(env.get("ERP_AGENT_RATE_FILE"))
    nhip = Path(raw_nhip) if raw_nhip else folder / "erp-agent-nhip.json"
    calls = _load_json(nhip)

    return bot_brain(
        state,
        now=now,
        ledger=_load_json(folder / "sku_ledger.json"),
        categories=_load_json(folder / "product_categories.json"),
        book_rows=book_rows if book_rows is not None else _load_json(folder / "sku_book.json"),
        rate_calls=calls if isinstance(calls, list) else (),
        limits={
            "agent": _limit(env, "ERP_AGENT_RATE_PER_MINUTE"),
            "graphql": _limit(env, "ERP_GRAPHQL_PER_MINUTE"),
        },
    )


def _rate(calls: Iterable[Any], limits: Any, now: datetime) -> Dict[str, Any]:
    """Lượt ERP thật trong một phút, so với cả hai trần."""
    moc = now.timestamp()
    trong_cua_so = 0
    for item in calls if isinstance(calls, (list, tuple)) else ():
        try:
            khi = float(item)
        except (TypeError, ValueError):
            continue
        if 0 <= moc - khi <= RATE_WINDOW_S:
            trong_cua_so += 1

    tran: Dict[str, Optional[float]] = {"agent": None, "graphql": None}
    if isinstance(limits, Mapping):
        for key in ("agent", "graphql"):
            try:
                tran[key] = float(limits[key]) if limits.get(key) is not None else None
            except (TypeError, ValueError, KeyError):
                tran[key] = None

    # Bot và làn nhanh đi qua trần ``agent``: đó là trần để so biên dư.
    moc_tran = tran["agent"]
    bien_du = round(moc_tran - trong_cua_so, 2) if moc_tran else None
    if bien_du is None:
        tone = "ok"
    elif bien_du <= 0:
        tone = "bad"
    elif moc_tran and trong_cua_so >= 0.9 * moc_tran:
        tone = "bad"
    elif moc_tran and trong_cua_so >= 0.7 * moc_tran:
        tone = "warn"
    else:
        tone = "ok"
    return {
        "calls": trong_cua_so,
        "window_s": RATE_WINDOW_S,
        "per_minute": round(trong_cua_so * 60.0 / RATE_WINDOW_S, 2),
        "limits": tran,
        "headroom": bien_du,
        "tone": tone,
    }


def _ledger(raw: Any) -> List[Dict[str, Any]]:
    """Sổ cấp số: số **kế tiếp** mỗi tiền tố, tức số cuối đã phát cộng một."""
    if not isinstance(raw, Mapping):
        return []
    seq = raw.get("project_seq")
    if not isinstance(seq, Mapping):
        return []
    rows = []
    for prefix, last in seq.items():
        name = _text(prefix)
        so = _int(last)
        if not name or so is None:
            continue
        rows.append({"prefix": name, "next": so + 1})
    rows.sort(key=lambda row: row["prefix"])
    return rows


def _entries(raw: Any) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        inner = raw.get("entries")
        if isinstance(inner, Mapping):
            return inner
        return raw
    return {}


def _categories(raw: Any) -> List[Dict[str, str]]:
    """Danh mục ERP có ``sku_prefix``. Không có tiền tố thì bot không đoán."""
    rows = []
    for name, body in _entries(raw).items():
        ten = _text(name)
        prefix = _text(body.get("sku_prefix")) if isinstance(body, Mapping) else _text(body)
        if ten and prefix:
            rows.append({"name": ten, "prefix": prefix})
    rows.sort(key=lambda row: row["name"])
    return rows


def _no_prefix(raw: Any) -> int:
    return sum(
        1 for _, body in _entries(raw).items()
        if not (_text(body.get("sku_prefix")) if isinstance(body, Mapping) else _text(body))
    )


def _book(raw: Any) -> List[Dict[str, Any]]:
    """Bảng mã sheet: mặt hàng → mã. Một dòng có thể ghi nhiều mã.

    Bot đánh số lấy **mã đầu**; phần còn lại giữ nguyên ở ``alternates`` để
    bảng nói được "bảng có ba mã, bot lấy KT" thay vì im lặng chọn hộ.
    """
    from .sku import split_prefixes

    rows: List[Dict[str, Any]] = []
    for name, value in _entries(raw).items():
        ten = _text(name)
        codes = split_prefixes(value if isinstance(value, str) else _text(value))
        if not ten or not codes:
            continue
        rows.append({"name": ten, "prefix": codes[0], "alternates": list(codes[1:])})
    rows.sort(key=lambda row: row["name"])
    return rows


def _book_size(raw: Any) -> int:
    entries = _entries(raw)
    if entries:
        return len(entries)
    return len(raw) if isinstance(raw, (list, tuple)) else 0


def _clean_brain(raw: Any) -> Dict[str, Any]:
    """Brain đọc từ tệp. Bot cũ chưa ghi khoá này: trả khối rỗng, bảng vẫn mở."""
    data = raw if isinstance(raw, Mapping) else {}
    counts = data.get("counts") if isinstance(data.get("counts"), Mapping) else {}
    rate = data.get("rate") if isinstance(data.get("rate"), Mapping) else {}
    def rows(key):
        value = data.get(key)
        return [dict(r) for r in value if isinstance(r, Mapping)] if isinstance(value, list) else []
    return {
        "bot_user": _text(data.get("bot_user")),
        "projects": _names(data.get("projects")),
        "fast_lane": _names(data.get("fast_lane")),
        "outside_fast_lane": _names(data.get("outside_fast_lane")),
        "paused": rows("paused"),
        "warned_columns": rows("warned_columns"),
        "last_run": dict(data["last_run"]) if isinstance(data.get("last_run"), Mapping)
                    else {"task": "", "link": "", "at": "", "age_s": None},
        "counts": {key: _int(counts.get(key)) or 0 for key in (
            "projects", "fast_lane", "outside_fast_lane", "paused", "warned_columns",
            "handled", "listed", "runs", "brain_calls")},
        "rate": {
            "calls": _int(rate.get("calls")) or 0,
            "per_minute": rate.get("per_minute") if isinstance(rate.get("per_minute"), (int, float)) else 0,
            "limits": dict(rate["limits"]) if isinstance(rate.get("limits"), Mapping)
                      else {"agent": None, "graphql": None},
            "headroom": rate.get("headroom"),
            "tone": _text(rate.get("tone")) or "ok",
        },
        "ledger": rows("ledger"),
        "categories": rows("categories"),
        "book": rows("book"),
        "counts_extra": dict(data["counts_extra"]) if isinstance(data.get("counts_extra"), Mapping) else {},
    }


def snapshot(trees: Iterable[Any], now: Optional[datetime] = None, *, every: Optional[int] = None,
             book: Any = None, rows: Iterable[Any] = (), book_rows: Any = None,
             brain: Any = None) -> Dict[str, Any]:
    """Ảnh chụp SKU & thuộc tính từ các cây bot vừa đọc. Hàm thuần: không gọi ai.

    ``book`` (tuỳ chọn) là ``ProductBook`` bot đang giữ, để nói "bảng SKU chưa
    có dòng" cả khi service chưa kịp để lời nhắc trên thẻ cha.

    ``rows`` là dòng ``taskBoard`` bot đã đọc trong lượt quét. Cụm bị cắt lấy
    mã và cột của thẻ ngoài cây từ đây. Thẻ không có dòng nào thì là "chưa đọc
    được", không tính vào "chưa có SKU".

    ``book_rows`` là bảng mã trên đĩa. Nó chỉ dùng để gỡ lời nhắc cũ: tên đã
    tra ra dòng thật thì không còn là "bảng SKU chưa có dòng". Nó không tự
    thêm lý do ``book``, vì bảng trên đĩa có thể thiếu dòng mà sheet đang có.
    """
    # Nạp muộn: bảng điều khiển import module này mà không được kéo cả bot theo.
    from .agent_bot import count_decisions, tree_is_cut

    def pending_images(node: Mapping[str, Any]) -> int:
        try:
            return count_decisions(dict(node))[1]
        except Exception:
            return 0

    now = now or datetime.now(timezone.utc)
    by_name = _rows_by_name(rows)
    clusters: List[Dict[str, Any]] = []
    cards: List[Dict[str, Any]] = []
    seen_clusters: set[str] = set()
    seen_cards: set[str] = set()
    for tree in trees or []:
        root = _root_of(tree)
        task = _text(root.get("name"))
        if not task or task in seen_clusters:
            continue
        seen_clusters.add(task)
        meta = task_meta(root)
        attributes = _attributes(meta)
        # Lời nhắc nằm mãi trên thẻ gốc: bảng mã đã có dòng thì nó là lời nhắc cũ.
        unlisted = {key: value for key, value in _unlisted(root).items()
                    if not (_book_has(book, value[0]) or _book_has(book_rows, value[0]))}
        full = _full_nodes(root)
        thin = _thin_nodes(root, full)

        received = sum(1 for child in root.get("subtasks") or [] if isinstance(child, Mapping) and _text(child.get("name")))
        listed = sum(1 for child in root.get("children") or [] if isinstance(child, Mapping) and _text(child.get("name")))
        total = max(_int(root.get("child_total")) or 0, listed, received)
        unseen = total - received
        info = tree if isinstance(tree, Mapping) else {}
        # Gắn ``root`` đã gỡ: cây truyền vào có thể là thẻ gốc trần, không
        # bọc trong ``{"root": ...}``, mà ``tree_is_cut`` đi từ ``root``.
        truncated = unseen > 0 or tree_is_cut({**info, "root": root})

        # Cụm bị cắt: thẻ có dòng bảng mà cây không có, kể cả thẻ cháu.
        outside: List[Tuple[Mapping[str, Any], str]] = []
        if truncated and by_name:
            known = {task} | {_text(n.get("name")) for n, _ in full} | {_text(n.get("name")) for n, _ in thin}
            outside = [({"name": name}, _text(row.get("parent_task"))) for name, row in by_name.items()
                       if name not in known and task in _ancestors(name, by_name)]

        mine: List[Dict[str, Any]] = []
        for node, parent in full:
            mine.append(_card(node, parent, task, meta, unlisted, book, pending_images, now))
        for node, parent in thin + outside:
            row = by_name.get(_text(node.get("name")))
            mine.append(_row_card(node, row, parent, task, meta, unlisted, book, now) if row
                        else _cut_card(node, parent, task))
        mine = [c for c in mine if c["task"] and c["task"] not in seen_cards]
        seen_cards.update(c["task"] for c in mine)
        cards.extend(mine)

        clusters.append({
            "task": task,
            "subject": _text(root.get("subject")),
            "board": _text(root.get("project_name")),
            "project": _text(root.get("project")),
            "status": _text(root.get("status")),
            "column": column_name(root.get("status")) if _text(root.get("status")) else "",
            "attributes": attributes,
            "content": _text(meta.get("content")),
            "missing": [name for name in ATTRIBUTES if not attributes[name]],
            "columns": _columns(c["status"] for c in mine),
            "received": received,
            "total": total,
            "unseen": unseen,
            "truncated": truncated,
            "node_count": _int(info.get("node_count")) or 0,
            "max_nodes": _int(info.get("max_nodes")) or 0,
            "cards": len(mine),
            "no_sku": sum(1 for c in mine if c["reason"] and c["reason"] != "cut"),
            "unread": sum(1 for c in mine if c["reason"] == "cut"),
            "from_board": sum(1 for c in mine if c["source"] == "board"),
            "working_no_sku": sum(1 for c in mine if c["working_no_sku"]),
            "done": "done" in meta.labels,
            "unlisted": sorted(name for name, _ in unlisted.values()),
        })

    cards.sort(key=_sort_key)
    return {
        "at": _iso(now),
        "every": int(every) if every else DEFAULT_EVERY,
        "clusters": clusters,
        "cards": cards,
        "totals": totals(clusters, cards),
        # Sổ bot giữ bên ERP. Bot cũ không truyền thì để rỗng, không bỏ khoá:
        # bảng đọc được khoá rỗng, còn khoá thiếu thì phải đoán.
        "brain": brain if isinstance(brain, Mapping) else {},
    }


def status_path(env: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    """Chỗ ghi tệp: ``ERP_SKU_STATUS_FILE``, không thì cạnh tệp của review_lister."""
    env = os.environ if env is None else env
    explicit = _text(env.get("ERP_SKU_STATUS_FILE"))
    if explicit:
        return Path(explicit)
    folder = _text(env.get("ERP_LISTING_FILES_DIR"))
    return Path(folder) / SKU_STATUS_FILE if folder else None


def load_disk_book(path: Any = None) -> Any:
    """Bảng mã trên đĩa (``DATA_DIR/sku_book.json``), đọc như ``service.load_sku_book``.

    Chỉ để gỡ lời nhắc cũ trên bảng. Không có tệp hay tệp hỏng thì ``None``:
    bảng giữ lời nhắc như cũ.
    """
    from .sku import ProductBook

    if path is None:
        from .paths import DATA_DIR
        path = DATA_DIR / "sku_book.json"
    target = Path(path)
    if not target.exists():
        return None
    try:
        saved = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            entries = saved.get("entries") if isinstance(saved.get("entries"), dict) else saved
            return ProductBook.from_mapping(entries)
        if isinstance(saved, list):
            return ProductBook.from_rows(saved)
    except Exception as exc:
        log.warning("không đọc được bảng mã %s: %s", target, mask(exc)[:200])
        return None
    log.warning("bảng mã %s không phải object hay list", target)
    return None


def write_status(trees: Iterable[Any], path: Any = None, *, now: Optional[datetime] = None,
                 every: Optional[int] = None, book: Any = None, rows: Iterable[Any] = (),
                 book_rows: Any = None, brain: Any = None) -> bool:
    """Ghi ``sku_status.json`` rồi thay tệp cũ một lần (không ai đọc phải tệp dở).

    Hỏng thì ghi log rồi thôi, không ném: bảng mất một lượt số còn hơn bot
    ngừng quét.
    """
    global _warned_no_path
    target = Path(path) if path else status_path()
    if target is None:
        if not _warned_no_path:
            log.warning("chưa đặt ERP_SKU_STATUS_FILE hay ERP_LISTING_FILES_DIR: bảng SKU không có số")
            _warned_no_path = True
        return False
    tmp = target.with_name(target.name + ".tmp")
    try:
        data = snapshot(trees, now, every=every, book=book, rows=rows, book_rows=book_rows,
                        brain=brain)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, target)
    except Exception as exc:
        log.warning("không ghi được %s: %s", target, mask(exc)[:200])
        return False
    return True


# ── bên bảng: đọc tệp, dựng phần SKU ──────────────────────────────────


def _clean_cluster(raw: Mapping[str, Any]) -> Dict[str, Any]:
    attributes = raw.get("attributes") if isinstance(raw.get("attributes"), Mapping) else {}
    columns = raw.get("columns") if isinstance(raw.get("columns"), list) else []
    task = _text(raw.get("task"))
    return {
        "task": task,
        "url": ERP_TASK_URL + task if task else "",
        "subject": _text(raw.get("subject")),
        "board": _text(raw.get("board")),
        "project": _text(raw.get("project")),
        "column": _text(raw.get("column")),
        "attributes": {_text(k): _text(v) for k, v in attributes.items()},
        "content": _text(raw.get("content")),
        "missing": [_text(x) for x in raw.get("missing") or [] if _text(x)] if isinstance(raw.get("missing"), list) else [],
        "columns": [{"status": _text(c.get("status")), "name": _text(c.get("name")), "n": _int(c.get("n")) or 0}
                    for c in columns if isinstance(c, Mapping)],
        "received": _int(raw.get("received")) or 0,
        "total": _int(raw.get("total")) or 0,
        "unseen": max(_int(raw.get("unseen")) or 0, 0),
        "truncated": bool(raw.get("truncated")),
        "node_count": _int(raw.get("node_count")) or 0,
        "max_nodes": _int(raw.get("max_nodes")) or 0,
        "cards": _int(raw.get("cards")) or 0,
        "no_sku": _int(raw.get("no_sku")) or 0,
        "unread": _int(raw.get("unread")) or 0,
        "from_board": _int(raw.get("from_board")) or 0,
        "working_no_sku": _int(raw.get("working_no_sku")) or 0,
        "done": bool(raw.get("done")),
    }


def _clean_card(raw: Mapping[str, Any]) -> Dict[str, Any]:
    task = _text(raw.get("task"))
    card = {key: _text(raw.get(key)) for key in (
        "task", "subject", "cluster", "status", "column", "source", "sku", "product", "reason", "why", "note_at",
        "account", "account_state", "copysku", "copysku_state")}
    card.update({
        "url": ERP_TASK_URL + task if task else "",
        "seen": bool(raw.get("seen", True)),
        "working_no_sku": bool(raw.get("working_no_sku")),
        "done": bool(raw.get("done")),
    })
    return card


def _alerts(bot: Mapping[str, Any], clusters: List[Dict[str, Any]], cards: List[Dict[str, Any]],
            brain: Optional[Mapping[str, Any]] = None) -> List[Dict[str, str]]:
    alerts: List[Dict[str, str]] = []
    error = bot["error"]
    if error == "HTTP 404":
        alerts.append({"tone": "bad", "text": "Bot chưa ghi số SKU: chưa có tệp sku_status.json. Bot chưa quét xong "
                                              "lượt nào, hoặc app 8000 chưa đặt ERP_LISTING_FILES_DIR "
                                              "(hay ERP_SKU_STATUS_FILE).", "link": ""})
    elif error:
        alerts.append({"tone": "bad", "text": f"Không đọc được sku_status.json: {error}.", "link": ""})
    elif bot["stale"]:
        age = bot["age_s"]
        text = (f"Bot chưa ghi mới: lượt cuối cách đây {_minutes(age)}, bot quét mỗi {bot['every']} giây."
                if age is not None else "Bot chưa ghi mới: tệp không ghi giờ.")
        alerts.append({"tone": "bad", "text": text, "link": ""})

    for c in clusters:
        if not c["truncated"]:
            continue
        tone = "bad"
        if c["unseen"]:
            text = f"Cụm {c['task']}: bot chỉ đọc được {c['received']}/{c['total']} thẻ"
            if c["from_board"]:
                # Dòng bảng bù được phần cây thiếu: nói ra, để seller khỏi tưởng bot bỏ sót.
                text += f"; {c['from_board']} thẻ đọc mã từ dòng bảng"
                text += f", {c['unread']} thẻ chưa đọc được" if c["unread"] else ""
                tone = "warn" if not c["unread"] and c["from_board"] >= c["unseen"] else "bad"
            text += "."
        elif c["max_nodes"] and c["node_count"] >= c["max_nodes"]:
            text = f"Cụm {c['task']}: ERP cắt cây ở {c['max_nodes']} node, có thể thiếu thẻ cháu."
        else:
            text = f"Cụm {c['task']}: ERP cắt cây ở tầng dưới, có thể thiếu thẻ cháu."
        alerts.append({"tone": tone, "text": text, "link": c["url"]})

    stuck = [c for c in cards if c["working_no_sku"]]
    if stuck:
        later = sum(1 for c in stuck if normalize_status(c["status"]) != COL_DOING)
        where = {c["cluster"] for c in stuck}
        text = f"{len(stuck)} thẻ ở Đang làm chưa có SKU" + (f" (tính cả {later} thẻ đã sang cột sau)" if later else "") + "."
        link = next((c["url"] for c in clusters if c["task"] in where), "") if len(where) == 1 else ""
        alerts.append({"tone": "bad", "text": text, "link": link})

    lacking = [c for c in clusters if c["missing"]]
    if lacking:
        named = "; ".join(f"{c['task']} ({', '.join(c['missing'])})" for c in lacking[:3])
        more = f" và {len(lacking) - 3} cụm nữa" if len(lacking) > 3 else ""
        alerts.append({"tone": "warn", "text": f"{len(lacking)} cụm thiếu thuộc tính: {named}{more}.",
                       "link": lacking[0]["url"] if len(lacking) == 1 else ""})
    for key, label in (("account_state", "account"), ("copysku_state", "copysku")):
        n = sum(1 for c in cards if c[key] == "missing")
        if n:
            alerts.append({"tone": "warn", "text": f"{n} thẻ thiếu {label}: thẻ con và thẻ cha đều chưa khai.", "link": ""})

    # Chạm trần ERP thì mọi thứ khác chậm theo. Bot cũ không ghi nhịp: im lặng,
    # đừng bịa ra một cảnh báo từ số không có.
    rate = brain.get("rate") if isinstance(brain, Mapping) else None
    tran = (rate or {}).get("limits", {}).get("agent") if isinstance(rate, Mapping) else None
    if isinstance(rate, Mapping) and tran and rate.get("tone") in ("warn", "bad"):
        con = rate.get("headroom")
        du = isinstance(con, (int, float)) and con > 0
        alerts.append({
            "tone": "bad" if rate["tone"] == "bad" else "warn",
            "text": f"Bot đã dùng {rate.get('calls')}/{_int(tran)} lượt trần ERP trong một phút"
                    + (f", còn {con} lượt. Chạm trần thì lượt quét và việc điền SKU chậm theo."
                       if du else ". Hết biên dư: lượt sau bị ERP chặn, lượt quét và việc điền SKU chậm theo.")
                    + " Trần này không chạm việc tách thẻ con.",
            "link": "",
        })

    alerts.sort(key=lambda a: a["tone"] != "bad")
    return alerts


def build_sku(api: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Phần SKU của bảng, dựng từ tệp bot ghi. Không gọi ERP.

    Tệp hỏng hay chưa có thì trả cấu trúc rỗng kèm lỗi: cả bảng vẫn mở được.
    """
    now = now or datetime.now(timezone.utc)
    error = ""
    try:
        status = api.lister_status(SKU_STATUS_FILE)
    except urllib.error.HTTPError as exc:
        status, error = {}, f"HTTP {exc.code}"
    except (OSError, ValueError) as exc:
        status, error = {}, mask(exc)[:200]
    if not error and not isinstance(status, dict):
        status, error = {}, "tệp trạng thái không phải JSON object"

    at = parse_time(status.get("at"))
    every = _int(status.get("every")) or 0
    every = every if every > 0 else DEFAULT_EVERY
    stale_after = 2 * every + 120
    age = _seconds(at, now)
    stale = not error and (age is None or age > stale_after)
    bot = {
        "at": _iso(at),
        "age_s": age,
        "every": every,
        "stale_after_s": stale_after,
        "error": error,
        "stale": stale,
        "tone": "bad" if error or stale else "ok",
    }

    raw_clusters = status.get("clusters") if isinstance(status.get("clusters"), list) else []
    raw_cards = status.get("cards") if isinstance(status.get("cards"), list) else []
    clusters = [_clean_cluster(c) for c in raw_clusters if isinstance(c, Mapping)]
    cards = [_clean_card(c) for c in raw_cards if isinstance(c, Mapping)]
    cards.sort(key=_sort_key)
    brain = _clean_brain(status.get("brain"))
    return {
        "at": _iso(now),
        "base": getattr(api, "base", ""),
        "sources": {"sku": error},
        "bot": bot,
        "kpi": totals(clusters, cards),
        "alerts": _alerts(bot, clusters, cards, brain),
        "clusters": clusters,
        "cards": cards,
        "brain": brain,
    }
