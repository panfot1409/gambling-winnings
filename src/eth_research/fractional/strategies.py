"""Fractional strategy adapters + the five real-experiment configurations.

Signal generation (concern 1) is deliberately delegated to the existing binary
``Strategy`` classes, so the three binary-equivalent strategies (``cash``,
``buy_and_hold``, ``donchian_55_20``) emit byte-identical signals to the binary
engine and the compatibility oracle (Phase 12) can prove parity. Each adapter
attaches a causal :class:`RiskConfig` describing which overlays apply.

For the real experiment: maximum exposure is ``1.0`` everywhere; the two
``vol_target_*`` strategies additionally enable the 30-day / 50%-annual
volatility target and the 0.25 turnover limiter; the drawdown breaker is off.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.fractional.risk import DEFAULT_MAX_ABS_WEIGHT_CHANGE
from eth_research.strategies.base import Strategy
from eth_research.strategies.buy_and_hold import BuyAndHold
from eth_research.strategies.cash import Cash
from eth_research.strategies.donchian import DonchianChannel


@dataclass(frozen=True)
class RiskConfig:
    """Which causal overlays a strategy applies, in the frozen policy order."""

    max_exposure: float = 1.0
    volatility_target: bool = False
    turnover_limit: float | None = None
    drawdown_breaker: bool = False


@dataclass(frozen=True)
class FractionalStrategy:
    """A named signal source plus its risk configuration and warm-up need."""

    name: str
    signal: Strategy
    risk: RiskConfig
    warmup_bars: int


STRATEGY_NAMES: tuple[str, ...] = (
    "cash",
    "buy_and_hold",
    "donchian_55_20",
    "vol_target_buy_and_hold_30d_50pct",
    "vol_target_donchian_55_20_30d_50pct",
)


def build_strategies() -> tuple[FractionalStrategy, ...]:
    """The five pinned real-experiment strategy configurations, in order."""
    plain = RiskConfig(max_exposure=1.0)
    vol = RiskConfig(
        max_exposure=1.0,
        volatility_target=True,
        turnover_limit=DEFAULT_MAX_ABS_WEIGHT_CHANGE,
    )
    return (
        FractionalStrategy("cash", Cash(), plain, warmup_bars=0),
        FractionalStrategy("buy_and_hold", BuyAndHold(), plain, warmup_bars=0),
        FractionalStrategy(
            "donchian_55_20",
            DonchianChannel(entry_window=55, exit_window=20),
            plain,
            warmup_bars=55,
        ),
        FractionalStrategy("vol_target_buy_and_hold_30d_50pct", BuyAndHold(), vol, warmup_bars=31),
        FractionalStrategy(
            "vol_target_donchian_55_20_30d_50pct",
            DonchianChannel(entry_window=55, exit_window=20),
            vol,
            warmup_bars=55,
        ),
    )


STRATEGIES_BY_NAME: dict[str, FractionalStrategy] = {s.name: s for s in build_strategies()}
