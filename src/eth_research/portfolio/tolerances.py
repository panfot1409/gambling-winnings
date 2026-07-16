"""Pinned numeric tolerances for the portfolio simulator.

These mirror the accepted single-asset engine's tolerances so the M4B accounting, solver, and
reconciliation invariants hold to the same binary64 precision. They are frozen constants, bound
into every result and checkpoint, so a run's numeric contract is explicit and reproducible rather
than an implicit property of the code that happened to run.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DEFAULT_TOLERANCES", "PortfolioTolerances"]


@dataclass(frozen=True)
class PortfolioTolerances:
    """The pinned absolute tolerances the portfolio invariants are checked against."""

    #: Base-currency cash may dip no further below zero than this (float rounding only).
    cash: float = 1e-6
    #: A holding quantity may dip no further below zero than this.
    quantity: float = 1e-12
    #: Target weights must sum to within this of their intended total.
    weight: float = 1e-9
    #: The shared-cash equity fixed point is solved to this absolute width.
    solver: float = 1e-12
    #: A desired trade whose base notional is at or below this fraction of equity is a no-op.
    no_trade: float = 1e-9
    #: Two base notionals within this absolute amount are treated as equal in reconciliation.
    notional: float = 1e-6
    #: The bounded bisection may take at most this many iterations before failing closed.
    max_iterations: int = 100

    def __post_init__(self) -> None:
        for name in ("cash", "quantity", "weight", "solver", "no_trade", "notional"):
            value = getattr(self, name)
            if not isinstance(value, float) or not value > 0.0:
                raise ValueError(f"tolerance {name!r} must be a positive float")
        if not isinstance(self.max_iterations, int) or self.max_iterations < 1:
            raise ValueError("max_iterations must be a positive integer")


#: The default tolerances every built-in path uses; a caller may pin a stricter set.
DEFAULT_TOLERANCES = PortfolioTolerances()
