#!/usr/bin/env python3
"""Chạy agent bot đứng riêng, không cần mở giao diện Flow v2.

Bình thường bot chạy sẵn bên trong app (``flow_web/main.py`` khởi động nó
trong lifespan). Script này dành cho hai việc mà app không làm được:

* **Kiểm tra nhanh** một lượt quét rồi thoát — ``--once``, và nên đi kèm
  ``--dry-run`` ở lần đầu cắm bot vào một dự án lạ.
* **Chạy bot ở một máy khác** với máy chạy Flow. Lúc đó phần dọn phiếu
  (👍 giữ / 👎 xoá) chỉ cần token ERP nên chạy được ngay, còn mọi việc phải
  *ghi* lên ERP bằng danh nghĩa app — tạo ảnh, đẩy cột, sửa thuộc tính theo
  lời người dùng — đều chuyển tiếp qua HTTP tới máy có Flow
  (``--flow-web-url``).

Sáu thứ bot làm được, bốn trong số đó cần ``--flow-web-url``:

===============================  ==================================  ==========
Việc                             Đường đi                            Cần URL?
===============================  ==================================  ==========
Dọn phiếu 👍/👎                   token ERP của chính bot             không
Trả lời / sửa thẻ khi được gọi   ``POST /api/erp/task/meta-edit``    có (để ghi)
Tạo ảnh cho thẻ Idea             ``POST /api/erp/idea-batch``        có
Đẩy thẻ sang cột kế              ``POST /api/erp/pipeline/advance``  có
Đánh số SKU cả cụm khi được bảo  ``POST /api/erp/sku/sync``          có
Đoán ý câu nói ngoài từ khoá     ``claude`` / ``codex`` trên máy này  không
===============================  ==================================  ==========

Thiếu URL thì bot vẫn *hiểu* lệnh và vẫn trả lời, nhưng nói thẳng ra là nó
chưa nối được đường ghi — chứ không im lặng gật đầu.

Dòng cuối bảng không cần URL vì nó chỉ *đọc* một câu tiếng Việt rồi trả về
"ghi ô nào thành gì"; phần ghi vẫn là dòng thứ hai. Bật bằng
``FLOW_AGENT_BRAIN=1``, và cần **một** CLI model đã đăng nhập trên máy đang
chạy bot: ``claude`` (mặc định) hoặc ``codex`` — chỉ tên lệnh khác nhau, chọn
bằng ``FLOW_AGENT_BRAIN_CMD``.  Máy trung tâm đang đi đường ``codex`` vì ở đó
``codex`` đăng nhập sẵn còn ``claude`` thì chưa cài.  Mặc định tắt.

Thẻ ``action_1: listing`` đi sang bản Listing qua ``ERP_LISTING_API_URL`` trong
``.env.local``; chưa đặt biến đó thì bot nhận diện rồi để yên, không chạy gì.

Ví dụ::

    python scripts/run_agent_bot.py --once --dry-run
    python scripts/run_agent_bot.py --flow-web-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from flow_web.account_book import AccountBook  # noqa: E402
from flow_web.agent_bot import AgentBotConfig, AgentBotError, build_agent_bot  # noqa: E402
from flow_web.agent_brain import BrainConfig, build_brain_hook  # noqa: E402
from flow_web.listing_bridge import (  # noqa: E402
    ListingBridge,
    ListingBridgeConfig,
    build_listing_confirm_hook,
    build_listing_hook,
)
from flow_web.main import load_local_env  # noqa: E402

log = logging.getLogger("agent_bot")


def _call_flow_web(
    base: str,
    path: str,
    payload: Optional[Dict[str, Any]],
    *,
    timeout_s: int,
    what: str,
) -> Dict[str, Any]:
    """Một lần gọi sang app, và một chỗ duy nhất dịch lỗi mạng ra tiếng người.

    Bot đọc lỗi ra thành câu trả lời trên thẻ, nên thông báo ở đây là thứ
    người dùng sẽ thấy — phải nói rõ *việc gì* hỏng, không chỉ mã HTTP.
    """
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(
        f"{base}{path}",
        data=data,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AgentBotError(f"Flow v2 từ chối {what}: HTTP {exc.code} {detail}") from exc
    except URLError as exc:
        raise AgentBotError(f"Không gọi được Flow v2 tại {base} để {what}: {exc.reason}") from exc


def _forward_autorun(flow_web_url: str, timeout_s: int = 30):
    """Hook chạy việc: đẩy thẻ cha sang cho Flow v2 tạo ảnh.

    Bot cố ý không tự chạy Flow: cả app chỉ có một phiên trình duyệt, nên việc
    xếp hàng phải nằm ở đúng một chỗ — ``enqueue_erp_idea_jobs`` của app.
    """

    base = flow_web_url.rstrip("/")

    async def hook(parent_task_id: str) -> Dict[str, Any]:
        return await asyncio.to_thread(
            _call_flow_web,
            base,
            "/api/erp/idea-batch",
            {"task_id": parent_task_id},
            timeout_s=timeout_s,
            what=f"chạy {parent_task_id}",
        )

    return hook


def _forward_pipeline(flow_web_url: str, timeout_s: int = 60):
    """Hook luật cột: nhờ app đẩy thẻ sang cột kế.

    Đi qua app chứ không qua client của bot vì đường ghi trạng thái duy nhất
    phải là đường có hàng rào kiểm dự án — và vì chặng *Đang làm* còn phải
    điền SKU, việc chỉ app mới làm được (nó giữ bảng tra mã và sổ số SKU).
    """

    base = flow_web_url.rstrip("/")

    async def hook(task_id: str) -> Dict[str, Any]:
        return await asyncio.to_thread(
            _call_flow_web,
            base,
            "/api/erp/pipeline/advance",
            {"task_id": task_id},
            timeout_s=timeout_s,
            what=f"đẩy {task_id} sang cột kế",
        )

    return hook


def _forward_edit(flow_web_url: str, timeout_s: int = 30):
    """Hook sửa thẻ: người dùng nói ``@bot acc: acc32``, app ghi xuống.

    **Đồng bộ**, không ``async`` như hai hook trên: ``chat_pass`` gọi nó từ
    trong ``asyncio.to_thread`` nên ở đó không có vòng lặp sự kiện để ``await``.
    """

    base = flow_web_url.rstrip("/")

    def hook(task_id: str, edits: Sequence[Tuple[str, str]]) -> Dict[str, Any]:
        return _call_flow_web(
            base,
            "/api/erp/task/meta-edit",
            {"task_id": task_id, "edits": [[str(name), str(value)] for name, value in edits]},
            timeout_s=timeout_s,
            what=f"sửa thuộc tính thẻ {task_id}",
        )

    return hook


def _forward_sku(flow_web_url: str, timeout_s: int = 120):
    """Hook đánh số: người dùng nói ``@bot điền sku đi``, app cấp mã cả cụm.

    Bắt buộc đi qua app: bảng tra mã (tên sản phẩm → phần tên SKU) đọc từ
    file hoặc Google Sheet của app, và sổ số — thứ nhớ dự án nào mang số mấy,
    idea đã đếm tới đâu — cũng nằm bên đó; máy chạy bot không có và không nên có.

    **Đồng bộ** như ``_forward_edit``, cùng lý do — ``chat_pass`` gọi nó từ
    trong ``asyncio.to_thread``.  Hạn giờ rộng hơn hẳn mấy hook kia: một cụm
    ba mươi thẻ là ba mươi lượt đọc rồi ghi ERP nối đuôi nhau, và bỏ dở giữa
    chừng thì cụm mang một nửa số mã mới — cảnh khó dọn nhất.
    """

    base = flow_web_url.rstrip("/")

    def hook(task_id: str, renumber: bool) -> Dict[str, Any]:
        return _call_flow_web(
            base,
            "/api/erp/sku/sync",
            {"task_id": task_id, "dry_run": False, "renumber": bool(renumber)},
            timeout_s=timeout_s,
            what=("đánh số lại cụm " if renumber else "cấp mã SKU cho cụm ") + task_id,
        )

    return hook


def _fetch_account_book(flow_web_url: str, timeout_s: int = 15) -> Optional[AccountBook]:
    """Xin app quyển sổ tài khoản đã gộp (biến môi trường + file + sheet).

    Lấy qua app chứ không tự đọc lại: máy chạy bot có thể không có file sổ,
    không có sheet, và không được phép có — nhưng nó vẫn phải trả lời đúng câu
    "thẻ này lên shop nào". Sổ hỏng thì bot chạy với sổ rỗng chứ không chết:
    nó vẫn đọc được nhãn ``acc32`` theo quy ước, chỉ là không biết tên shop.
    """
    try:
        payload = _call_flow_web(
            flow_web_url.rstrip("/"),
            "/api/erp/account/book",
            None,
            timeout_s=timeout_s,
            what="đọc sổ tài khoản",
        )
    except AgentBotError as exc:
        log.warning("Chạy không có sổ tài khoản: %s", exc)
        return None
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        log.warning("Sổ tài khoản trả về không đúng dạng, bỏ qua.")
        return None
    book = AccountBook.from_mapping(entries)
    log.info("Sổ tài khoản: %s dòng.", len(book.entries))
    return book


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agent bot của Flow v2 trên ERP HaviGroup.")
    parser.add_argument("--once", action="store_true", help="Quét đúng một lượt rồi thoát.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ghi log quyết định nhưng không xoá và không chạy gì.",
    )
    parser.add_argument(
        "--flow-web-url",
        default="",
        help="Địa chỉ Flow v2 để chuyển tiếp việc ghi (tạo ảnh, đẩy cột, sửa thẻ). "
        "Bỏ trống là chỉ dọn phiếu và trả lời.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=0,
        help="Ghi đè ERP_AGENT_POLL_SECONDS.",
    )
    parser.add_argument(
        "--state",
        default="",
        help="File nhớ riêng cho lượt chạy này. Bắt buộc khi thử một bot khác trên "
        "cùng máy: file mặc định bị *ghi đè* chứ không gộp, nên hai bot dùng chung "
        "sẽ xoá mất phạm vi dự án của nhau.",
    )
    parser.add_argument("--verbose", action="store_true", help="Log mức DEBUG.")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    load_local_env()

    config = AgentBotConfig.from_env()
    if args.dry_run:
        config = replace(config, dry_run=True)
    if args.poll_seconds:
        config = replace(config, poll_seconds=args.poll_seconds)
    if not args.flow_web_url:
        # Không có nơi chuyển tiếp thì tắt hẳn phần chạy việc, thay vì để nó
        # âm thầm không làm gì và trông như bot đang hỏng.
        config = replace(config, autorun=False)

    if not config.enabled:
        log.error("Chưa đặt ERP_AGENT_TOKEN trong .env.local nên không có gì để chạy.")
        return 2

    # Một agent, hai loại thẻ — giống hệt lúc bot chạy trong app (xem
    # ``FlowService.agent_bot``). Quên nối cầu Listing ở đây thì bot vẫn sống và
    # vẫn dọn phiếu, chỉ mỗi thẻ ``action_1: listing`` là nhận "chưa cấu hình
    # ERP_LISTING_API_URL" — kể cả khi biến ấy đã có trong ``.env.local``.
    # Hai hàm dựng hook bên ``listing_bridge`` đều trả None khi chưa đặt biến,
    # nên máy chưa dựng bản Listing vẫn giữ nguyên hành vi cũ.
    book = _fetch_account_book(args.flow_web_url) if args.flow_web_url else None
    listing = ListingBridge(ListingBridgeConfig.from_env(), book=book)
    brain = BrainConfig.from_env()
    bot = build_agent_bot(
        config,
        autorun_hook=_forward_autorun(args.flow_web_url) if args.flow_web_url else None,
        listing_hook=build_listing_hook(listing),
        # Và hook hỏi lại, cùng điều kiện bật/tắt với hook giao thẻ. Thiếu nó
        # thì ``_listing_confirm`` lặng lẽ trả None: thẻ giao sang Etsy rồi
        # không bao giờ được xác nhận, luật cột không bao giờ mở cổng sang
        # Hoàn thành — và không có dòng log nào kêu.
        listing_confirm_hook=build_listing_confirm_hook(listing),
        # Bốn hook dưới đây phải có mặt ở bản chạy rời đúng như ở bản trong app.
        # Thiếu chúng thì bot trông vẫn sống — vẫn quét, vẫn dọn phiếu — mà thẻ
        # thì đứng nguyên một cột mãi mãi và mọi câu "sửa hộ tôi" đều nhận lời
        # từ chối. Đó là kiểu hỏng khó thấy nhất, nên nối sẵn ở đây.
        pipeline_hook=_forward_pipeline(args.flow_web_url) if args.flow_web_url else None,
        book=book,
        edit_hook=_forward_edit(args.flow_web_url) if args.flow_web_url else None,
        sku_hook=_forward_sku(args.flow_web_url) if args.flow_web_url else None,
        # Hook thứ năm không cần ``--flow-web-url``: nó gọi thẳng CLI model
        # trên chính máy này. Máy nào chưa đăng nhập CLI nào thì
        # FLOW_AGENT_BRAIN cứ để tắt, bot trả lời y như trước chứ không hỏng.
        brain_hook=build_brain_hook(brain),
        brain_max_calls=brain.max_calls,
        state_path=Path(args.state).expanduser() if args.state else None,
    )
    if bot is None:
        log.error("Không dựng được agent bot.")
        return 2

    if args.once:
        summary = await bot.run_once()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    log.info(
        "Agent bot chạy mỗi %ss (dọn phiếu%s). Ctrl+C để dừng.",
        config.poll_seconds,
        (" + chạy việc + luật cột + sửa thẻ + đánh số" if args.flow_web_url else "")
        + (f" + đoán ý bằng {brain.resolved_provider()}" if brain.enabled else ""),
    )
    await bot.run_forever(immediate=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
