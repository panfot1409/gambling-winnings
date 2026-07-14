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

import math
from dataclasses import dataclass

from eth_research.fractional.risk import DEFAULT_MAX_ABS_WEIGHT_CHANGE, RiskError
from eth_research.strategies.base import Strategy
from eth_research.strategies.buy_and_hold import BuyAndHold
from eth_research.strategies.cash import Cash
from eth_research.strategies.donchian import DonchianChannel


def _finite(label: str, value: float) -> float:
    """Reject a ``bool``, non-real, or non-finite (NaN/inf) risk-config value."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise RiskError(f"{label} must be a finite number, got {value!r}")
    return float(value)


@dataclass(frozen=True)
class RiskConfig:
    """Which causal overlays a strategy applies, in the frozen policy order."""

    max_exposure: float = 1.0
    volatility_target: bool = False
    turnover_limit: float | None = None
    drawdown_breaker: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= _finite("max_exposure", self.max_exposure) <= 1.0:
            raise RiskError(f"max_exposure must be in [0, 1], got {self.max_exposure!r}")
        if not isinstance(self.volatility_target, bool):
            raise RiskError(f"volatility_target must be a bool, got {self.volatility_target!r}")
        if not isinstance(self.drawdown_breaker, bool):
            raise RiskError(f"drawdown_breaker must be a bool, got {self.drawdown_breaker!r}")
        if self.turnover_limit is not None and _finite("turnover_limit", self.turnover_limit) < 0.0:
            raise RiskError(f"turnover_limit must be >= 0 or None, got {self.turnover_limit!r}")


@dataclass(frozen=True)
class FractionalStrategy:
    """A named signal source plus its risk configuration and warm-up need."""

    name: str
    signal: Strategy
    risk: RiskConfig
    warmup_bars: int

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError(f"name must be a non-empty string, got {self.name!r}")
        if not isinstance(self.signal, Strategy):
            raise TypeError(f"signal must be a Strategy, got {type(self.signal).__name__}")
        if not isinstance(self.risk, RiskConfig):
            raise TypeError(f"risk must be a RiskConfig, got {type(self.risk).__name__}")
        if isinstance(self.warmup_bars, bool) or not isinstance(self.warmup_bars, int):
            raise TypeError(f"warmup_bars must be an int, got {self.warmup_bars!r}")
        if self.warmup_bars < 0:
            raise ValueError(f"warmup_bars must be >= 0, got {self.warmup_bars!r}")


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
