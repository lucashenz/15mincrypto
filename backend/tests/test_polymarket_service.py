import asyncio
import time
from datetime import datetime, timedelta, timezone

from app.models.entities import Direction
from app.services.polymarket_service import PolymarketService


def test_fetch_market_data_resolves_by_timestamp_and_reads_gamma_prices():
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
                "priceToBeat": "68000",
                "finalPrice": "68100",
                "clobTokenIds": '["yes-token","no-token"]',
            }
        ]

    svc._fetch_gamma_market = fake_fetch_gamma_market
    svc._fetch_gamma_markets_query = fake_fetch_gamma_markets_query

    data = asyncio.run(svc.fetch_market_data("btc-updown-15m"))

    assert data.yes_odds == 0.63
    assert data.no_odds == 0.37
    assert data.odds_live is True
    assert data.resolver_source == "TIMESTAMP_SEARCH"
    assert data.price_to_beat == 68000.0
    assert data.final_price == 68100.0
    assert data.yes_token_id == "yes-token"

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


def test_place_clob_order_requires_wallet_and_token():
    svc = PolymarketService()
    data = asyncio.run(svc.fetch_market_data("btc-updown-15m"))
    ok, msg = asyncio.run(svc.place_clob_order(data, Direction.UP, 20.0, ""))
    assert ok is False
    assert msg == "WALLET_NOT_CONFIGURED"
    asyncio.run(svc.close())
