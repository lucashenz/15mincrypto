from __future__ import annotations

from collections import Counter

from app.models.entities import Direction, Indicator, Signal
from app.services.indicator_service import IndicatorService


class StrategyService:
    def __init__(
        self,
        indicator_service: IndicatorService,
        confidence_threshold: float,
        entry_threshold: float = 0.9,
        entry_window_seconds: int = 180,
    ) -> None:
        self.indicator_service = indicator_service
        self.confidence_threshold = confidence_threshold
        self.entry_threshold = entry_threshold
        self.entry_window_seconds = entry_window_seconds

    def generate_signal_90pct(
        self,
        asset: str,
        yes_odds: float,
        no_odds: float,
        seconds_remaining: int,
        use_macd_confirmation: bool,
    ) -> tuple[Signal | None, str]:
        """
        Entrada quando odds >= 90% e faltam 2-3 min.
        Alta assertividade: mercado já definido, entra do lado favorecido.
        """
        if seconds_remaining > self.entry_window_seconds or seconds_remaining <= 0:
            return None, f"WAIT_WINDOW::{seconds_remaining}s_remaining"

        if yes_odds >= self.entry_threshold:
            direction = Direction.UP
            conf = yes_odds
            reason = f"YES_90PCT({yes_odds:.0%})"
        elif no_odds >= self.entry_threshold:
            direction = Direction.DOWN
            conf = no_odds
            reason = f"NO_90PCT({no_odds:.0%})"
        else:
            return None, f"BELOW_THRESHOLD::yes={yes_odds:.0%}_no={no_odds:.0%}"

        if use_macd_confirmation:
            macd = self.indicator_service.macd_bias(asset)
            if macd is not None and macd != direction:
                return None, f"MACD_DISAGREES::{reason}"

        return (
            Signal(asset=asset, direction=direction, confidence=conf, reason=reason),
            f"ENTRY_90PCT::{reason}",
        )

    def generate_signal(
        self,
        asset: str,
        indicators: list[Indicator],
        poly_bias: Direction | None,
    ) -> tuple[Signal | None, str]:
        votes: list[Direction] = []
        reasons: list[str] = []

        if Indicator.MACD in indicators:
            macd = self.indicator_service.macd_bias(asset)
            if macd is None:
                return None, "WAITING_MACD_HISTORY"
            votes.append(macd)
            reasons.append(f"MACD={macd.value}")

        if Indicator.TREND in indicators:
            trend = self.indicator_service.trend_bias(asset)
            if trend is None:
                return None, "WAITING_TREND_HISTORY"
            votes.append(trend)
            reasons.append(f"TREND={trend.value}")

        if Indicator.POLY_PRICE in indicators:
            if poly_bias is None:
                return None, "WAITING_POLY"
            votes.append(poly_bias)
            reasons.append(f"POLY={poly_bias.value}")

        if not votes:
            return None, "NO_INDICATORS_SELECTED"

        counts = Counter(votes)
        direction, qty = counts.most_common(1)[0]

        # padrão usado em bots de consenso: quando 2 de 3 concordam já consideramos sinal forte
        if len(votes) == 3 and qty == 2:
            confidence = 0.9
        else:
            confidence = qty / len(votes)

        reason = " + ".join(reasons)
        if confidence < self.confidence_threshold:
            return None, f"LOW_CONFIDENCE({confidence:.2f})::{reason}"

        return Signal(asset=asset, direction=direction, confidence=confidence, reason=reason), f"SIGNAL({confidence:.2f})::{reason}"
