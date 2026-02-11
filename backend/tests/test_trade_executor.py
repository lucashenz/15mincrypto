from datetime import datetime, timedelta

from app.models.entities import ApiMode, Asset, Direction, MarketSnapshot, Signal
from app.services.trade_executor import TradeExecutor


def test_stop_loss_closes_trade_early_for_up_direction():
    executor = TradeExecutor()
    snapshot = MarketSnapshot(asset=Asset.BTC, spot_price=100)
    signal = Signal(asset=Asset.BTC, direction=Direction.UP, confidence=0.9, reason="test")

    trade = executor.open_trade(
        snapshot=snapshot,
        signal=signal,
        api_mode=ApiMode.CLOB,
        closes_at=datetime.utcnow() + timedelta(minutes=10),
        stop_loss_pct=0.2,
    )

    latest = {Asset.BTC: MarketSnapshot(asset=Asset.BTC, spot_price=79)}
    settled = executor.settle_due_trades(latest)

    assert len(settled) == 1
    assert settled[0].id == trade.id
    assert settled[0].status == "STOP_LOSS"


def test_settle_by_poly_result_marks_win_for_up():
    executor = TradeExecutor()
    snapshot = MarketSnapshot(asset=Asset.BTC, spot_price=100, price_to_beat=68000)
    signal = Signal(asset=Asset.BTC, direction=Direction.UP, confidence=0.9, reason="test")

    trade = executor.open_trade(
        snapshot=snapshot,
        signal=signal,
        api_mode=ApiMode.CLOB,
        closes_at=datetime.utcnow() - timedelta(seconds=1),
        stop_loss_pct=0.2,
    )

    latest = {
        Asset.BTC: MarketSnapshot(
            asset=Asset.BTC,
            spot_price=98,
            price_to_beat=68000,
            final_price=68100,
        )
    }
    settled = executor.settle_due_trades(latest)

    assert len(settled) == 1
    assert settled[0].id == trade.id
    assert settled[0].status == "WIN"
