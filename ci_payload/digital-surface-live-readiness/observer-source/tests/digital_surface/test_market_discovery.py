import json

from research.digital_surface.market_discovery import discover_target_markets, parse_gamma_market


def market(slug, condition, token_ids, *, active=True, closed=False, enable=True):
    return {
        "conditionId": condition,
        "slug": slug,
        "question": "Bitcoin Up or Down",
        "active": active,
        "closed": closed,
        "enableOrderBook": enable,
        "clobTokenIds": json.dumps(token_ids),
        "outcomes": '["Up", "Down"]',
        "orderPriceMinTickSize": 0.01,
        "endDate": "2026-07-25T15:00:00Z",
    }


def test_parses_gamma_token_order_and_target_duration():
    record = parse_gamma_market(market("btc-updown-5m-1774450800", "c1", ["yes", "no"]))
    assert record.condition_id == "c1"
    assert record.yes_token_id == "yes"
    assert record.no_token_id == "no"
    assert record.duration_seconds == 300
    assert record.open_epoch_seconds == 1774450800


def test_discovery_filters_non_target_closed_and_duplicate_markets():
    pages = {
        0: [
            market("btc-updown-5m-1774450800", "c1", ["yes1", "no1"]),
            market("btc-updown-15m-1774450800", "c2", ["yes2", "no2"]),
            market("eth-updown-5m-1774450800", "c3", ["yes3", "no3"]),
            market("btc-updown-5m-1774451100", "c4", ["yes4", "no4"], closed=True),
        ],
        4: [market("btc-updown-5m-1774450800", "c1", ["yes1", "no1"])],
    }

    def fetch(params):
        return pages.get(params["offset"], [])

    found = discover_target_markets(fetch, page_size=4, max_pages=3)
    assert [row.condition_id for row in found] == ["c1", "c2"]
