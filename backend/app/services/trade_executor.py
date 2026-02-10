from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from app.models.entities import ApiMode, BotStats, Direction, MarketSnapshot, Signal, Trade


class TradeExecutor:
    def __init__(self) -> None:
        self.stats = BotStats()
        self.open_trades: dict[str, Trade] = {}
        self.closed_trades: list[Trade] = []

    def open_trade(
        self,
        snapshot: MarketSnapshot,
        signal: Signal,
        api_mode: ApiMode,
        duration_seconds: int,
    ) -> Trade:
        trade = Trade(
            id=str(uuid4())[:8],
            asset=snapshot.asset,
            direction=signal.direction,
            entry_price=snapshot.spot_price,
            confidence=signal.confidence,
            api_mode=api_mode,
            closes_at=datetime.utcnow() + timedelta(seconds=duration_seconds),
        )
        self.open_trades[trade.id] = trade
        return trade

    def settle_due_trades(self, latest_prices: dict[str, MarketSnapshot]) -> list[Trade]:
        now = datetime.utcnow()
        settled: list[Trade] = []
        for trade_id, trade in list(self.open_trades.items()):
            if now < trade.closes_at:
                continue
            snapshot = latest_prices[trade.asset]
            trade.exit_price = snapshot.spot_price
            trade.closed_at = now
            delta = trade.exit_price - trade.entry_price
            trade.pnl = delta if trade.direction == Direction.UP else -delta
            trade.status = "WIN" if trade.pnl > 0 else "LOSS"
            self.stats.trades += 1
            self.stats.all_time_pnl += trade.pnl
            self.stats.today_pnl += trade.pnl
            self.stats.balance += trade.pnl
            if trade.status == "WIN":
                self.stats.wins += 1
            self.closed_trades.insert(0, trade)
            self.open_trades.pop(trade_id)
            settled.append(trade)
        self.closed_trades = self.closed_trades[:50]
        return settled
