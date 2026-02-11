from __future__ import annotations

from datetime import datetime
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
        closes_at: datetime,
        stop_loss_pct: float,
    ) -> Trade:
        trade = Trade(
            id=str(uuid4())[:8],
            asset=snapshot.asset,
            direction=signal.direction,
            entry_price=snapshot.spot_price,
            confidence=signal.confidence,
            api_mode=api_mode,
            closes_at=closes_at,
            stop_loss_pct=stop_loss_pct,
            market_id=snapshot.market_id,
            window_ts=snapshot.window_ts,
            market_end_ts=snapshot.market_end_ts,
            price_to_beat=snapshot.price_to_beat,
        )
        self.open_trades[trade.id] = trade
        return trade

    def settle_due_trades(
        self,
        latest_prices: dict[str, MarketSnapshot],
        result_overrides: dict[str, tuple[float | None, float | None, str]] | None = None,
    ) -> list[Trade]:
        now = datetime.utcnow()
        settled: list[Trade] = []
        overrides = result_overrides or {}

        for trade_id, trade in list(self.open_trades.items()):
            snapshot = latest_prices.get(trade.asset)
            if snapshot is None:
                continue

            should_close = now >= trade.closes_at
            stop_hit = self._is_stop_hit(trade, snapshot.spot_price)
            if not should_close and not stop_hit:
                continue

            trade.exit_price = snapshot.spot_price
            trade.closed_at = now

            final_price, price_to_beat, _source = overrides.get(trade.id, (snapshot.final_price, snapshot.price_to_beat, "SNAPSHOT"))

            if should_close and final_price is not None and price_to_beat is not None:
                is_up_result = final_price > price_to_beat
                won = is_up_result if trade.direction == Direction.UP else not is_up_result
                trade.pnl = abs(trade.exit_price - trade.entry_price) if won else -abs(trade.exit_price - trade.entry_price)
                trade.status = "WIN" if won else "LOSS"
            else:
                delta = trade.exit_price - trade.entry_price
                trade.pnl = delta if trade.direction == Direction.UP else -delta
                if stop_hit:
                    trade.status = "STOP_LOSS"
                else:
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

        self.closed_trades = self.closed_trades[:200]
        return settled

    @staticmethod
    def _is_stop_hit(trade: Trade, price: float) -> bool:
        if trade.stop_loss_pct <= 0:
            return False
        if trade.direction == Direction.UP:
            return price <= trade.entry_price * (1 - trade.stop_loss_pct)
        return price >= trade.entry_price * (1 + trade.stop_loss_pct)
