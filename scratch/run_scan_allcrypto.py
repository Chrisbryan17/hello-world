#!/usr/bin/env python3
from pathlib import Path
import re

source_path = Path(__file__).with_name("scan_copyable_wallets.py")
source = source_path.read_text(encoding="utf-8")

# Expand from BTC-only to the actively listed short-duration crypto families.
source, n_regex = re.subn(
    r'BTC_RE = re\.compile\(r"btc-updown-\(5m\|15m\)-\\d\{10\}\$"\)',
    'BTC_RE = re.compile(r"(?:btc|eth|sol|xrp)-updown-(5m|15m)-(\\\\d{10})$")',
    source,
)
if n_regex != 1:
    # Direct literal fallback for the current scanner source.
    source = source.replace(
        'BTC_RE = re.compile(r"btc-updown-(5m|15m)-(\\d{10})$")',
        'BTC_RE = re.compile(r"(?:btc|eth|sol|xrp)-updown-(5m|15m)-(\\d{10})$")',
    )

replacement = r'''def fetch_market_map() -> dict[str, dict[str, Any]]:
    session = new_session()
    result: dict[str, dict[str, Any]] = {}
    cursor = START - 3600
    final = NOW + 3600
    slice_seconds = 6 * 3600
    while cursor <= final:
        slice_end = min(final, cursor + slice_seconds - 1)
        start_iso = datetime.fromtimestamp(cursor, UTC).isoformat().replace("+00:00", "Z")
        end_iso = datetime.fromtimestamp(slice_end, UTC).isoformat().replace("+00:00", "Z")
        offset = 0
        while True:
            page = get_json(
                session,
                f"{GAMMA}/markets",
                {
                    "closed": "true",
                    "tag_id": 21,
                    "end_date_min": start_iso,
                    "end_date_max": end_iso,
                    "order": "endDate",
                    "ascending": "true",
                    "limit": 100,
                    "offset": offset,
                },
            )
            if not isinstance(page, list):
                raise TypeError("Unexpected Gamma markets response")
            for m in page:
                slug = str(m.get("slug", ""))
                parsed = parse_slug(slug)
                if not parsed:
                    continue
                st, en, duration = parsed
                winner = winner_from_market(m)
                if winner and START <= en <= NOW:
                    result[str(m.get("conditionId", ""))] = {
                        "slug": slug,
                        "title": m.get("question") or m.get("title") or slug,
                        "start": st,
                        "end": en,
                        "duration": duration,
                        "winner": winner,
                        "order_min_size": float(m.get("orderMinSize") or 5),
                    }
            print("MARKETS", start_iso, offset, len(page), "CRYPTO_RESOLVED", len(result), flush=True)
            offset += len(page)
            if len(page) < 100:
                break
            if offset > 2000:
                raise RuntimeError(f"Six-hour market slice exceeded safety cap: {start_iso}")
        cursor = slice_end + 1
    return result


def fetch_leaderboards'''

source, count = re.subn(
    r'def fetch_market_map\(\) -> dict\[str, dict\[str, Any\]\]:.*?\n\ndef fetch_leaderboards',
    replacement,
    source,
    flags=re.S,
)
if count != 1:
    raise RuntimeError(f"Expected one fetch_market_map replacement, got {count}")
namespace = {"__name__": "__main__", "__file__": str(source_path)}
exec(compile(source, str(source_path), "exec"), namespace)
