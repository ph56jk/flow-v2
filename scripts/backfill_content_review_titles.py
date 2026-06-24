from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flow_web.main import load_local_env
from flow_web.schemas import utc_now
from flow_web.service import FlowWebService
from flow_web.store import StateStore


def _ascii_log(text: str) -> str:
    return str(text or "").encode("ascii", errors="backslashreplace").decode("ascii")


def _remove_ai_title_block(service: FlowWebService, description: str) -> str:
    text = str(description or "")
    pattern = re.compile(
        r"\s*" + re.escape(service.TRELLO_AI_TITLE_BEGIN_MARKER) + r".*?" + re.escape(service.TRELLO_AI_TITLE_END_MARKER) + r"\s*",
        re.DOTALL,
    )
    return re.sub(r"\n{3,}", "\n\n", pattern.sub("\n\n", text)).strip()


def _log_event(log_path: Path, event: Dict[str, Any]) -> None:
    event.setdefault("at", utc_now())
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _content_review_cards(
    service: FlowWebService,
    *,
    key: str,
    token: str,
    board_id: str,
    review_list_id: str,
) -> List[Dict[str, Any]]:
    payload = service._trello_get_json(
        f"boards/{quote(board_id, safe='')}/cards",
        key,
        token,
        fields={
            "fields": "id,name,desc,shortLink,url,idList,closed",
            "filter": "open",
            "attachments": "true",
            "attachment_fields": "id,name,url,mimeType,bytes,date",
        },
    )
    cards = payload if isinstance(payload, list) else []
    normalized_review_id = service._normalize_trello_id(review_list_id)
    return [
        card
        for card in cards
        if isinstance(card, dict)
        and not card.get("closed")
        and service._normalize_trello_id(str(card.get("idList") or "")) == normalized_review_id
    ]


def _source_attachment(
    service: FlowWebService,
    *,
    key: str,
    token: str,
    card: Dict[str, Any],
) -> Dict[str, Any]:
    card_id = service._normalize_trello_card_id(str(card.get("id") or card.get("shortLink") or ""))
    attachments = service._trello_card_attachments_or_fetch(card, key, token, card_id)
    image_attachments = [
        item for item in attachments if isinstance(item, dict) and service._trello_attachment_is_image(item)
    ]
    source_attachments, _flow_outputs = service._trello_source_and_flow_output_attachments(image_attachments)
    return source_attachments[0] if source_attachments else {}


def _title_payload_for_card(
    service: FlowWebService,
    *,
    key: str,
    token: str,
    card: Dict[str, Any],
    attachment: Dict[str, Any],
    sleep_after_gemini_s: float,
    allow_fallback: bool,
    retries: int,
) -> tuple[Dict[str, str], str]:
    card_id = service._normalize_trello_card_id(str(card.get("id") or card.get("shortLink") or ""))
    card_name = str(card.get("name") or "")
    attachment_name = str(attachment.get("name") or "")
    card_description = service._flow_operator_trello_card_description_note(card)
    product_rule_key = service._flow_operator_product_rule_key_from_text(
        " ".join([card_name, attachment_name, card_description])
    )

    image_bytes, mime = service._trello_download_attachment_bytes(key, token, card_id, attachment)
    last_exc: Exception | None = None
    attempts = max(1, int(retries or 0) + 1)
    for attempt in range(1, attempts + 1):
        try:
            payload = service._gemini_suggest_trello_product_title(
                image_bytes=image_bytes,
                mime_type=mime,
                card_name=card_name,
                attachment_name=attachment_name,
                card_description=card_description,
                product_rule_key=product_rule_key,
                visible_product="",
            )
            if sleep_after_gemini_s > 0:
                time.sleep(sleep_after_gemini_s)
            return payload, "gemini"
        except Exception as exc:
            last_exc = exc
            if attempt < attempts:
                time.sleep(min(20.0, 3.0 * attempt))
                continue
    if last_exc is not None:
        if not allow_fallback:
            raise RuntimeError(f"Gemini title failed after {attempts} attempt(s) and fallback is disabled: {last_exc}") from last_exc
        payload = service._fallback_trello_product_title(
            card_name=card_name,
            attachment_name=attachment_name,
            product_rule_key=product_rule_key,
            visible_product="",
        )
        payload["reason"] = f"{payload.get('reason', '').strip()} Gemini title failed: {last_exc}".strip()
        return payload, "fallback"
    raise RuntimeError("Gemini title failed without an exception.")


def _write_title_block(
    service: FlowWebService,
    *,
    key: str,
    token: str,
    card: Dict[str, Any],
    title_payload: Dict[str, str],
    source: str,
    force: bool,
) -> Dict[str, str]:
    old_description = str(card.get("desc") or "")
    if service._trello_description_has_ai_title_block(old_description):
        if not force:
            return {"status": "exists", "title": "", "backup_path": ""}
        base_description = _remove_ai_title_block(service, old_description)
    else:
        base_description = old_description

    title = service._sanitize_ai_product_title(str(title_payload.get("title") or ""))
    product_type = service._sanitize_ai_product_title(str(title_payload.get("product_type") or ""), max_length=80)
    embroidery_design = service._sanitize_ai_product_title(
        str(title_payload.get("embroidery_design") or ""),
        max_length=80,
    )
    new_description = service._trello_description_with_ai_title(
        base_description,
        title=title,
        product_type=product_type,
        embroidery_design=embroidery_design,
        model=service._gemini_model() if source == "gemini" else "local-fallback",
    )
    card_id = service._normalize_trello_card_id(str(card.get("id") or card.get("shortLink") or ""))
    backup_path = service._write_trello_ai_title_description_backup(
        card_id=card_id,
        card_name=str(card.get("name") or ""),
        card_url=str(card.get("url") or ""),
        old_description=old_description,
        new_description=new_description,
        title=title,
        product_type=product_type,
        embroidery_design=embroidery_design,
    )
    service._trello_put_json(
        f"cards/{quote(card_id, safe='')}",
        key,
        token,
        fields={"desc": new_description},
    )
    return {"status": "updated", "title": title, "backup_path": backup_path}


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill AI Etsy titles for all Trello Content Review cards.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of cards to process. 0 means all.")
    parser.add_argument("--sleep", type=float, default=3.2, help="Seconds to sleep after each successful Gemini call.")
    parser.add_argument("--retries", type=int, default=2, help="Gemini retries per card before failing or fallback.")
    parser.add_argument("--only-missing", action="store_true", help="Skip cards that already have a FLOW AI title block.")
    parser.add_argument("--allow-fallback", action="store_true", help="Write a local fallback title when Gemini title generation fails.")
    parser.add_argument("--from-failed-log", default="", help="Retry only cards with failed events from a previous JSONL log.")
    parser.add_argument("--log", default="", help="Optional JSONL log path.")
    args = parser.parse_args()

    load_local_env()
    service = FlowWebService(StateStore())
    key, token = service._trello_credentials()
    if not key or not token:
        raise SystemExit("Trello credentials are not configured.")

    config = service.store.snapshot().trello_config
    board_id = service._normalize_trello_board_id(
        config.board_id or os.getenv("TRELLO_BOARD_ID", "") or service.DEFAULT_TRELLO_BOARD_URL
    )
    if not board_id:
        raise SystemExit("Trello board id is not configured.")

    review_name = service._default_trello_review_list_name()
    review_list_id = service._trello_content_review_list_id(key, token, board_id, review_name)
    if not review_list_id:
        raise SystemExit(f"Could not find Trello list: {review_name}")

    log_path = Path(args.log) if args.log else ROOT / "logs" / f"content-review-title-backfill-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    cards = _content_review_cards(service, key=key, token=token, board_id=board_id, review_list_id=review_list_id)
    if args.from_failed_log:
        failed_path = Path(args.from_failed_log)
        failed_ids: List[str] = []
        if failed_path.is_file():
            for line in failed_path.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("event") == "failed":
                    card_id = service._normalize_trello_card_id(str(event.get("card_id") or ""))
                    if card_id and card_id not in failed_ids:
                        failed_ids.append(card_id)
        failed_set = set(failed_ids)
        cards = [
            card
            for card in cards
            if service._normalize_trello_card_id(str(card.get("id") or card.get("shortLink") or "")) in failed_set
        ]
    if args.limit and args.limit > 0:
        cards = cards[: args.limit]

    total = len(cards)
    counts = {"updated": 0, "skipped": 0, "failed": 0, "fallback": 0, "gemini": 0}
    _log_event(log_path, {"event": "start", "board_id": board_id, "review_list_id": review_list_id, "total": total})
    print(_ascii_log(f"START total={total} log={log_path}"), flush=True)

    for index, card in enumerate(cards, 1):
        card_id = service._normalize_trello_card_id(str(card.get("id") or card.get("shortLink") or ""))
        card_url = str(card.get("url") or "")
        try:
            has_block = service._trello_description_has_ai_title_block(str(card.get("desc") or ""))
            if args.only_missing and has_block:
                counts["skipped"] += 1
                _log_event(log_path, {"event": "skip_existing", "index": index, "total": total, "card_id": card_id, "card_url": card_url})
                print(_ascii_log(f"[{index}/{total}] SKIP existing {card_url}"), flush=True)
                continue

            attachment = _source_attachment(service, key=key, token=token, card=card)
            if not attachment:
                counts["skipped"] += 1
                _log_event(log_path, {"event": "skip_no_source", "index": index, "total": total, "card_id": card_id, "card_url": card_url})
                print(_ascii_log(f"[{index}/{total}] SKIP no source {card_url}"), flush=True)
                continue

            title_payload, source = _title_payload_for_card(
                service,
                key=key,
                token=token,
                card=card,
                attachment=attachment,
                sleep_after_gemini_s=max(0.0, float(args.sleep or 0.0)),
                allow_fallback=bool(args.allow_fallback),
                retries=max(0, int(args.retries or 0)),
            )
            counts[source] = counts.get(source, 0) + 1
            result = _write_title_block(
                service,
                key=key,
                token=token,
                card=card,
                title_payload=title_payload,
                source=source,
                force=not args.only_missing,
            )
            counts["updated"] += 1
            _log_event(
                log_path,
                {
                    "event": "updated",
                    "index": index,
                    "total": total,
                    "card_id": card_id,
                    "card_url": card_url,
                    "source": source,
                    "title": result.get("title") or "",
                    "embroidery_design": title_payload.get("embroidery_design") or "",
                    "backup_path": result.get("backup_path") or "",
                },
            )
            print(_ascii_log(f"[{index}/{total}] UPDATED {source} {card_url} :: {result.get('title') or ''}"), flush=True)
        except Exception as exc:
            counts["failed"] += 1
            _log_event(
                log_path,
                {
                    "event": "failed",
                    "index": index,
                    "total": total,
                    "card_id": card_id,
                    "card_url": card_url,
                    "error": str(exc),
                },
            )
            print(_ascii_log(f"[{index}/{total}] FAILED {card_url} :: {exc}"), flush=True)

    _log_event(log_path, {"event": "done", "counts": counts})
    print(_ascii_log(f"DONE {counts}"), flush=True)
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
