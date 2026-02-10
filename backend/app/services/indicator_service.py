from __future__ import annotations

from collections import defaultdict

from app.models.entities import Direction


class IndicatorService:
    def __init__(self) -> None:
        self._history: dict[str, list[float]] = defaultdict(list)

    def push_price(self, asset: str, price: float) -> None:
        self._history[asset].append(price)
        self._history[asset] = self._history[asset][-300:]

    def history_len(self, asset: str) -> int:
        return len(self._history[asset])

    def warmup(self, asset: str, base_price: float, points: int = 40) -> None:
        """Pré-carrega histórico para evitar ficar minutos sem sinal na inicialização."""
        if self.history_len(asset) >= points:
            return
        drift = max(base_price * 0.0002, 0.01)
        for i in range(points):
            # pequena variação determinística para formar curva e habilitar MACD/TREND
            offset = ((i % 10) - 5) * drift * 0.12
            self.push_price(asset, base_price + offset)

    def macd_bias(self, asset: str) -> Direction | None:
        prices = self._history[asset]
        if len(prices) < 30:
            return None
        ema12 = self._ema(prices, 12)
        ema26 = self._ema(prices, 26)
        macd_line = ema12 - ema26
        macd_hist = [self._ema(prices[:i], 12) - self._ema(prices[:i], 26) for i in range(26, len(prices) + 1)]
        signal_line = self._ema(macd_hist, 9)
        return Direction.UP if macd_line >= signal_line else Direction.DOWN

    def trend_bias(self, asset: str) -> Direction | None:
        prices = self._history[asset]
        if len(prices) < 30:
            return None
        sma_short = sum(prices[-10:]) / 10
        sma_long = sum(prices[-30:]) / 30
        return Direction.UP if sma_short >= sma_long else Direction.DOWN

    def short_term_momentum(self, asset: str, lookback: int = 10) -> float | None:
        """
        Retorna momentum normalizado [-1, 1] baseado na variação dos últimos `lookback` preços.
        Usado para odds sintéticas que reagem em tempo real (ticks a cada ~3s).
        """
        prices = self._history[asset]
        if len(prices) < lookback + 1:
            return None
        p_now = prices[-1]
        p_old = prices[-lookback - 1]
        if p_old <= 0:
            return 0.0
        change_pct = (p_now - p_old) / p_old
        # Normaliza: ~0.1% = 0.1, 1% = 1.0 (cap em ±1)
        momentum = max(-1.0, min(1.0, change_pct * 100))
        return momentum

    @staticmethod
    def _ema(values: list[float], period: int) -> float:
        if not values:
            return 0.0
        k = 2 / (period + 1)
        ema = values[0]
        for v in values[1:]:
            ema = v * k + ema * (1 - k)
        return ema
