from datetime import datetime, timedelta

from app.models.entities import ApiMode, Asset
from app.services.bot_engine import BotEngine
from app.services.indicator_service import IndicatorService
from app.services.strategy_service import StrategyService


def test_strategy_only_returns_signal_at_90_confidence():
    indicator = IndicatorService()
    strategy = StrategyService(indicator, 0.9)

    for i in range(40):
        indicator.push_price(Asset.BTC, 100 + i)

    signal = strategy.generate_signal(Asset.BTC)
    assert signal is not None
    assert signal.confidence >= 0.9


def test_hybrid_switch_to_gamma_when_60_seconds_remaining():
    engine = BotEngine()
    closes_at = datetime.utcnow() + timedelta(seconds=55)
    assert engine.decide_api_mode(closes_at) == ApiMode.GAMMA_API
