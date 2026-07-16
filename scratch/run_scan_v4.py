#!/usr/bin/env python3
from pathlib import Path
import re

source_path = Path(__file__).with_name("scan_copyable_wallets.py")
source = source_path.read_text(encoding="utf-8")

replacement = r'''def fetch_market_map() -> dict[str, dict[str, Any]]:
    session = new_session()
    result: dict[str, dict[str, Any]] = {}
    cursor = datetime.fromtimestamp(START - 3600, UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    final = datetime.fromtimestamp(NOW + 3600, UTC)
    while cursor <= final:
        day_start = max(START - 3600, int(cursor.timestamp()))
        day_end = min(NOW + 3600, int((cursor + timedelta(days=1)).timestamp()) - 1)
        start_iso = datetime.fromtimestamp(day_start, UTC).isoformat().replace("+00:00", "Z")
        end_iso = datetime.fromtimestamp(day_end, UTC).isoformat().replace("+00:00", "Z")
        offset = 0
        while True:
            page = get_json(
                session,
                f"{GAMMA}/markets",
                {
                    "closed": "true",
                    "tag_id": 21,
                    "related_tags": "true",
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
            print("MARKETS", cursor.date(), offset, len(page), "BTC_RESOLVED", len(result), flush=True)
            offset += len(page)
            if len(page) < 100:
                break
            if offset > 2000:
                raise RuntimeError(f"Daily market pagination exceeded safety cap for {cursor.date()}")
        cursor += timedelta(days=1)
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
