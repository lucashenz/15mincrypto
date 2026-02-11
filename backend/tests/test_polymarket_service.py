import asyncio

from app.models.entities import Direction
from app.services.polymarket_service import MarketData, PolymarketService


def test_window_helpers_are_deterministic():
    assert PolymarketService.get_current_window_ts(1700000123) == 1700000100
    assert PolymarketService.get_next_window_ts(1700000123) == 1700001000


def test_build_window_slug_uses_15m_timestamp():
    slug = PolymarketService.build_window_slug("BTC", 1700000100)
    assert slug == "btc-updown-15m-1700000100"


def test_extract_yes_from_gamma_payload_parses_stringified_outcome_prices():
    payload = {"outcomePrices": '["0.61", "0.39"]'}
    yes = PolymarketService._extract_yes_from_gamma_payload(payload)
    assert yes == 0.61


def test_place_clob_order_requires_wallet_and_token():
    svc = PolymarketService()
    data = MarketData(
        asset="BTC",
        window_ts=1700000100,
        market_id="id",
        market_slug="slug",
        yes_odds=0.6,
        no_odds=0.4,
        odds_source="GAMMA_API",
        odds_live=True,
        resolver_source="DIRECT",
        yes_token_id="yes-token",
        no_token_id="no-token",
    )
    ok, msg = asyncio.run(svc.place_clob_order(data, Direction.UP, 20.0, ""))
    assert ok is False
    assert msg == "WALLET_NOT_CONFIGURED"
    asyncio.run(svc.close())
