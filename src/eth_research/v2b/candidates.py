"""The (at most) two genuinely-new V2B cross-asset candidate families.

Both families read a **joint ETH/BTC** close panel and are long-only, unlevered, and gross ≤ 1. They
are eligible only because they consume a genuinely new input (BTC): each depends causally on lagged
BTC state, and neither has a silent ETH-only fallback — a missing/absent BTC observation makes the
candidate **refuse** (raise), never quietly run an ETH-only rule.

* **Candidate A — cross-asset trend confirmation** (``cross_asset_btc_confirmed_eth_trend``): hold
  ETH only when its own single-horizon trend is up **and** BTC's single-horizon trend confirms it
  up; otherwise cash. Long-only ETH exposure in {0, 1}.
* **Candidate B — cross-sectional relative-strength rotation**
  (``cross_asset_eth_btc_relative_strength_rotation``): compare ETH and BTC single-lookback
  relative-strength (momentum) scores; allocate the whole book to the stronger risky asset if its
  score is positive, else hold cash. At most one risky asset; gross ≤ 1; no shorting.

Every signal is decided from closes up to and including bar ``t`` (the reused engines execute the
resulting target at ``open[t+1]``), and each ships a **scalar oracle** — a pure ``*_weights_at``
function over trailing windows — so a causality test can prove the vectorized weights at ``t``
depend only on closes ≤ ``t``. Primary parameters are fixed here, before any real BTC data is
acquired.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from eth_research.v2.strict import V2ValidationError, canonical_sha256
from eth_research.v2b.multiplicity import assert_uses_new_information
from eth_research.v2b.research_memory import (
    ResearchFamilyIdentity,
    assert_declared_families_distinct,
    assert_family_is_new,
)

CANDIDATES_SCHEMA_VERSION: int = 1

ETH_CLOSE: str = "eth_close"
BTC_CLOSE: str = "btc_close"
WEIGHT_ETH: str = "weight_eth"
WEIGHT_BTC: str = "weight_btc"


class V2BCandidateError(V2ValidationError):
    """A V2B candidate specification/signal was malformed, or refused for missing BTC evidence."""


# --------------------------------------------------------------------------- #
# joint-panel validation (fail closed on missing/absent BTC)                   #
# --------------------------------------------------------------------------- #
def _require_joint_panel(panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Return finite (eth_close, btc_close) arrays, refusing any missing/absent BTC evidence."""
    for col in (ETH_CLOSE, BTC_CLOSE):
        if col not in panel.columns:
            raise V2BCandidateError(f"joint panel is missing the {col!r} column")
    eth = panel[ETH_CLOSE].to_numpy(dtype=float)
    btc = panel[BTC_CLOSE].to_numpy(dtype=float)
    if eth.shape[0] != btc.shape[0]:
        raise V2BCandidateError("eth/btc close arrays are misaligned")
    if not np.all(np.isfinite(eth)):
        raise V2BCandidateError("eth_close contains a non-finite value")
    # The new-information contract: BTC evidence must be present and finite for every bar, or the
    # candidate refuses — never a silent ETH-only fallback.
    if not np.all(np.isfinite(btc)):
        raise V2BCandidateError(
            "btc_close contains a non-finite / missing value; the candidate refuses (no signal) "
            "rather than fall back to an ETH-only rule"
        )
    return eth, btc


def _sma_at(window: np.ndarray) -> float:
    return float(window.mean())


# --------------------------------------------------------------------------- #
# Candidate A — cross-asset BTC-confirmed ETH trend                            #
# --------------------------------------------------------------------------- #
def cross_asset_confirmation_weights_at(
    eth_closes: np.ndarray, btc_closes: np.ndarray, *, eth_horizon: int, btc_horizon: int
) -> dict[str, float]:
    """Scalar oracle: Candidate A target weights for the last bar (causal over trailing closes)."""
    need = max(eth_horizon, btc_horizon)
    if eth_closes.shape[0] < need or btc_closes.shape[0] < need:
        return {
            WEIGHT_ETH: 0.0,
            WEIGHT_BTC: 0.0,
        }  # warm-up: flat (a valid no-position, not refusal)
    eth_up = float(eth_closes[-1]) > _sma_at(eth_closes[-eth_horizon:])
    btc_up = float(btc_closes[-1]) > _sma_at(btc_closes[-btc_horizon:])
    return {WEIGHT_ETH: 1.0 if (eth_up and btc_up) else 0.0, WEIGHT_BTC: 0.0}


def cross_asset_confirmation_weights(
    panel: pd.DataFrame, *, eth_horizon: int, btc_horizon: int
) -> pd.DataFrame:
    """Vectorized Candidate A target weights over a joint panel (ETH exposure in {0, 1})."""
    eth, btc = _require_joint_panel(panel)
    eth_series = pd.Series(eth, index=panel.index)
    btc_series = pd.Series(btc, index=panel.index)
    eth_up = eth_series > eth_series.rolling(eth_horizon).mean()
    btc_up = btc_series > btc_series.rolling(btc_horizon).mean()
    weight_eth = (eth_up & btc_up).fillna(False).astype(float)
    out = pd.DataFrame(index=panel.index)
    out[WEIGHT_ETH] = weight_eth
    out[WEIGHT_BTC] = 0.0
    return out


# --------------------------------------------------------------------------- #
# Candidate B — cross-sectional ETH/BTC relative-strength rotation             #
# --------------------------------------------------------------------------- #
def relative_strength_weights_at(
    eth_closes: np.ndarray, btc_closes: np.ndarray, *, lookback: int
) -> dict[str, float]:
    """Scalar oracle: Candidate B target weights for the last bar (causal over trailing closes)."""
    if eth_closes.shape[0] <= lookback or btc_closes.shape[0] <= lookback:
        return {WEIGHT_ETH: 0.0, WEIGHT_BTC: 0.0}  # warm-up: cash
    eth_rs = float(eth_closes[-1]) / float(eth_closes[-1 - lookback]) - 1.0
    btc_rs = float(btc_closes[-1]) / float(btc_closes[-1 - lookback]) - 1.0
    if eth_rs > btc_rs and eth_rs > 0.0:
        return {WEIGHT_ETH: 1.0, WEIGHT_BTC: 0.0}
    if btc_rs > eth_rs and btc_rs > 0.0:
        return {WEIGHT_ETH: 0.0, WEIGHT_BTC: 1.0}
    return {WEIGHT_ETH: 0.0, WEIGHT_BTC: 0.0}  # non-positive or tied → cash


def relative_strength_weights(panel: pd.DataFrame, *, lookback: int) -> pd.DataFrame:
    """Vectorized Candidate B target weights over a joint panel (≤ 1 risky asset, gross ≤ 1)."""
    eth, btc = _require_joint_panel(panel)
    eth_series = pd.Series(eth, index=panel.index)
    btc_series = pd.Series(btc, index=panel.index)
    eth_rs = eth_series / eth_series.shift(lookback) - 1.0
    btc_rs = btc_series / btc_series.shift(lookback) - 1.0
    pick_eth = (eth_rs > btc_rs) & (eth_rs > 0.0)
    pick_btc = (btc_rs > eth_rs) & (btc_rs > 0.0)
    out = pd.DataFrame(index=panel.index)
    out[WEIGHT_ETH] = pick_eth.fillna(False).astype(float)
    out[WEIGHT_BTC] = pick_btc.fillna(False).astype(float)
    return out


# --------------------------------------------------------------------------- #
# candidate specifications + validation                                        #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class V2BCandidateSpec:
    """A pre-registered V2B cross-asset candidate: id, semantic identity, and fixed parameters."""

    candidate_id: str
    identity: ResearchFamilyIdentity
    fixed_parameters: dict[str, int]

    def to_canonical(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "identity": self.identity.to_canonical(),
            "identity_fingerprint": self.identity.fingerprint(),
            "fixed_parameters": dict(sorted(self.fixed_parameters.items())),
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())


def _identity(
    signal_family: str, threshold_structure: str, allocation: str
) -> ResearchFamilyIdentity:
    return ResearchFamilyIdentity(
        signal_family=signal_family,
        signal_source="cross_asset_close_price",
        input_instruments=("btc", "eth"),
        executed_instruments=("eth",)
        if allocation == "binary_long_or_cash"
        else ("btc", "cash", "eth"),
        horizon_structure="single_horizon",
        threshold_structure=threshold_structure,
        allocation_structure=allocation,
        risk_overlay="none",
        volatility_overlay=False,
        drawdown_overlay=False,
        cost_model_family="causal_proxy",
        context_requirement="cross_asset_required",
        benchmark="buy_and_hold",
        primary_endpoint="paired_log_excess_return",
        partition="research_train",
    )


# Fixed primary parameters — chosen before any real BTC data is acquired.
CANDIDATE_A = V2BCandidateSpec(
    candidate_id="cross_asset_btc_confirmed_eth_trend",
    identity=_identity(
        "cross_asset_trend_confirmation", "cross_asset_confirmation_gate", "binary_long_or_cash"
    ),
    fixed_parameters={"eth_horizon": 100, "btc_horizon": 100},
)

CANDIDATE_B = V2BCandidateSpec(
    candidate_id="cross_asset_eth_btc_relative_strength_rotation",
    identity=_identity(
        "cross_sectional_relative_strength",
        "relative_strength_rank",
        "single_risky_or_cash_rotation",
    ),
    fixed_parameters={"lookback": 90},
)

V2B_CANDIDATES: tuple[V2BCandidateSpec, ...] = (CANDIDATE_A, CANDIDATE_B)


def assert_v2b_candidate_set_valid(specs: tuple[V2BCandidateSpec, ...]) -> None:
    """Re-assert the V2B set: <=2, long-only by identity, genuinely new, BTC-using, distinct."""
    if not specs:
        raise V2BCandidateError("the V2B candidate set is empty")
    if len(specs) > 2:
        raise V2BCandidateError(f"{len(specs)} candidate families exceed the V2B budget of 2")
    ids = [s.candidate_id for s in specs]
    if len(set(ids)) != len(ids):
        raise V2BCandidateError("duplicate candidate ids in the V2B set")
    identities = tuple(s.identity for s in specs)
    # Delegated governance checks (distinctness / new-information / anti-relabel) raise their own
    # V2ValidationError subclasses; present them uniformly as a V2BCandidateError with the message.
    try:
        assert_declared_families_distinct(identities)
        for spec in specs:
            assert_uses_new_information(spec.identity)
            assert_family_is_new(spec.identity)
    except V2ValidationError as exc:
        raise V2BCandidateError(str(exc)) from exc
