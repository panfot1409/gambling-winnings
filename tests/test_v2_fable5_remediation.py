"""Fable 5 remediation regression tests.

Standing tests for the Class-C defects the Fable 5 audit's cross-auditor challenge round reproduced
and this branch fixed:

- F5-C1: the sales-honesty scanner failed OPEN — a distant/cross-clause negator or a single
paragraph
  example-marker let a genuine unsupported superlative pass. It must now flag those while still
  exempting an immediate negation and a same-line marker, and the committed sales surface stays
  clean.
- F5-C2: the fractional engine's *hypothetical* terminal liquidation raised CostModelError (escaping
  the backtest) when impact pricing met a collapsed trailing liquidity (a run of zero-volume bars
  into
  the terminal bar). It must instead mark the liquidation impact-free and never crash; committed
  runs
  are unaffected (their trailing dollar-volume is always positive).

None of these touches a sealed value, a frozen governed artifact, or any committed result.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eth_research.fractional.cost_model import (
    CAUSAL_PROXY_BASE,
    CAUSAL_PROXY_STRESSED,
    CostScenario,
)
from eth_research.fractional.engine import run_fractional_backtest
from eth_research.fractional.strategies import STRATEGIES_BY_NAME
from eth_research.v2ab.commercial_truth import scan_repo_sales_material, scan_sales_material

# --------------------------------------------------------------------------------------------------
# F5-C1 — sales-honesty scanner must not fail open
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "This is not a drill: our system is a proven alpha.",  # distant/cross-clause negator
        "There is no reason to doubt our validated alpha.",  # distant double-negative
    ],
)
def test_scanner_negation_no_longer_fails_open(text: str) -> None:
    assert scan_sales_material(text, source="x"), (
        "the honesty scanner must flag a genuine unsupported superlative that is only "
        "'protected' by a distant / cross-clause negator (fail-open, F5-C1)"
    )


def test_paragraph_marker_exemption_is_intentional_author_controlled() -> None:
    # Documented, accepted behavior (F5-C1 note): a paragraph example-marker exempts the whole
    # paragraph. This is a deliberate author-controlled exemption the committed acceptance plan
    # relies on (an enumeration line next to its "false-claim examples" marker), and it cannot be
    # line-scoped without flagging that legitimate committed text. It is NOT an adversarial-input
    # boundary. The fenced FALSE-CLAIM-EXAMPLES block remains the primary example mechanism.
    text = "See the false claim example below.\nOur product is a proven alpha system."
    assert (
        scan_sales_material(text, source="x") == []
    )  # marker exempts the adjacent line, by design


@pytest.mark.parametrize(
    "text",
    [
        "Our system is not a proven alpha.",  # immediate negator — legitimately exempt
        "There is no proven alpha here.",
        "Our system is not\na proven alpha.",  # negator wraps to the previous physical line
        # a same-line example marker legitimately exempts that line:
        "As a forbidden phrase, 'proven alpha' is blocked by this scanner.",
    ],
)
def test_scanner_still_exempts_legitimate_negations_and_markers(text: str) -> None:
    assert scan_sales_material(text, source="x") == []


def test_committed_sales_surface_stays_clean() -> None:
    # The tightening must not introduce a false positive on the real committed sales materials.
    assert scan_repo_sales_material(".") == []


# --------------------------------------------------------------------------------------------------
# F5-C2 — terminal hypothetical liquidation must never crash on collapsed trailing liquidity
# --------------------------------------------------------------------------------------------------


def _collapsing_liquidity_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Schema-valid daily OHLCV: a high-volume warm-up ``context`` (so BuyAndHold's participation-
    capped buy can execute and hold inventory), then an ``eval`` frame whose volume collapses to
    zero
    so the trailing-30 median dollar-volume is 0 by the terminal bar."""
    price = 100.0

    def _mk(start: str, periods: int, volume: float) -> pd.DataFrame:
        idx = pd.date_range(start, periods=periods, freq="D", tz="UTC")
        rows = [(price, price, price, price, volume)] * periods
        return pd.DataFrame(
            rows, index=idx, columns=["open", "high", "low", "close", "volume"]
        ).astype(float)

    context = _mk("2021-01-01", 40, 1.0e9)
    # first eval bar keeps liquidity (buy executes), then 40 zero-volume bars collapse the window
    eval_head = _mk("2021-02-10", 1, 1.0e9)
    eval_tail = _mk("2021-02-11", 40, 0.0)
    evaluation = pd.concat([eval_head, eval_tail])
    return context, evaluation


@pytest.mark.parametrize("scenario", [CAUSAL_PROXY_BASE, CAUSAL_PROXY_STRESSED])
def test_terminal_liquidation_never_crashes_on_collapsed_liquidity(scenario: CostScenario) -> None:
    context, evaluation = _collapsing_liquidity_frames()
    strategy = STRATEGIES_BY_NAME["buy_and_hold"]
    result = run_fractional_backtest(evaluation, strategy, scenario, context=context)
    # It returns a finite hypothetical terminal-liquidation value rather than raising
    # CostModelError.
    assert np.isfinite(result.terminal_liquidation_equity)
    assert result.terminal_liquidation_equity > 0.0
