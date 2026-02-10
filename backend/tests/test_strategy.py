from datetime import datetime, timedelta

from app.models.entities import ApiMode, Asset, Direction, Indicator, StrategyConfig
from app.services.bot_engine import BotEngine
from app.services.indicator_service import IndicatorService
from app.services.strategy_service import StrategyService


def test_strategy_returns_signal_when_two_indicators_align():
    indicator = IndicatorService()
    strategy = StrategyService(indicator, 0.9)

    for i in range(45):
        indicator.push_price(Asset.BTC, 100 + i)

    signal, debug = strategy.generate_signal(Asset.BTC, [Indicator.MACD, Indicator.TREND], Direction.UP)
    assert signal is not None
    assert signal.confidence >= 0.9
    assert debug.startswith("SIGNAL")


def test_hybrid_switch_to_gamma_when_60_seconds_remaining():
    engine = BotEngine()
    closes_at = datetime.utcnow() + timedelta(seconds=55)
    assert engine.decide_api_mode(closes_at) == ApiMode.GAMMA_API


def test_config_rejects_empty_assets():
    engine = BotEngine()
    cfg = StrategyConfig(enabled_assets=[], enabled_indicators=[Indicator.MACD], confidence_threshold=0.9)
    try:
        engine.update_strategy_config(cfg)
        assert False, "expected ValueError"
    except ValueError:
        assert True
