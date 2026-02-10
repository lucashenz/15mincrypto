import time
import asyncio
from datetime import datetime, timedelta, timezone

from app.models.entities import ApiMode
from app.services.polymarket_service import PolymarketService


def test_fetch_odds_resolves_market_by_timestamp_search():
    svc = PolymarketService()

    async def fake_fetch_gamma_market(_market_ref):
        return None

    async def fake_fetch_gamma_markets_query(_term):
        end = datetime.now(timezone.utc) + timedelta(minutes=14)
        return [
            {
                "id": "resolved-market-id",
                "slug": "btc-updown-15m-some-window",
                "question": "Bitcoin Up or Down 15m",
                "endDate": end.isoformat(),
                "outcomePrices": ["0.63", "0.37"],
            }
        ]

    async def fake_fetch_clob_yes_from_market(_market):
        return None

    svc._fetch_gamma_market = fake_fetch_gamma_market
    svc._fetch_gamma_markets_query = fake_fetch_gamma_markets_query
    svc._fetch_clob_yes_from_market = fake_fetch_clob_yes_from_market

    yes, no, source, live = asyncio.run(svc.fetch_odds("btc-updown-15m", ApiMode.CLOB))

    assert yes == 0.63
    assert no == 0.37
    assert live is True
    assert "TIMESTAMP_SEARCH" in source

    asyncio.run(svc.close())


def test_pick_best_time_window_market_returns_none_for_stale_end_date():
    old_end = datetime.now(timezone.utc) - timedelta(minutes=5)
    payload = [
        {
            "id": "stale",
            "slug": "btc-updown-15m-old",
            "question": "Bitcoin Up or Down 15m",
            "endDate": old_end.isoformat(),
        }
    ]

    market = PolymarketService._pick_best_time_window_market(payload, "btc-updown-15m")
    assert market is None


def test_extract_yes_from_clob_book_prefers_mid_price():
    payload = {
        "bids": [["0.44", "100"]],
        "asks": [["0.46", "120"]],
    }
    yes = PolymarketService._extract_yes_from_clob_book(payload)
    assert yes == 0.45


def test_extract_yes_from_gamma_payload_parses_stringified_outcome_prices():
    payload = {"outcomePrices": '["0.61", "0.39"]'}
    yes = PolymarketService._extract_yes_from_gamma_payload(payload)
    assert yes == 0.61


def test_should_refresh_cache_when_market_is_closing():
    svc = PolymarketService()
    now_ts = int(datetime.now(timezone.utc).timestamp())
    market = {"endTimestamp": now_ts + 3}
    assert svc._should_refresh_cache(market, time.time(), now_ts) is True


def test_direct_market_is_rejected_if_not_in_current_window():
    now_ts = int(datetime.now(timezone.utc).timestamp())
    stale = {"endTimestamp": now_ts - 60}
    assert PolymarketService._is_candidate_for_current_window(stale, now_ts) is False
