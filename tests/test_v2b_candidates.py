"""V2B cross-asset candidates: causality, future-inertness, BTC information-dependence, constraints.

Developed and tested on deterministic synthetic ETH/BTC panels only — no real BTC price is read.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from eth_research.v2b import candidates as c
from eth_research.v2b import research_memory as rm

_N = 400
_A = {"eth_horizon": 100, "btc_horizon": 100}
_B = {"lookback": 90}


def _closes(
    eth_drift: float = 0.001, btc_drift: float = 0.0012, seed: int = 3
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    eth = 100.0 * np.exp(np.cumsum(rng.normal(eth_drift, 0.03, _N)))
    btc = 100.0 * np.exp(np.cumsum(rng.normal(btc_drift, 0.03, _N)))
    return eth, btc


def _panel_from(eth: np.ndarray, btc: np.ndarray) -> pd.DataFrame:
    idx = pd.date_range("2016-05-23", periods=_N, freq="D", tz="UTC")
    return pd.DataFrame({c.ETH_CLOSE: eth, c.BTC_CLOSE: btc}, index=idx)


def _panel(eth_drift: float = 0.001, btc_drift: float = 0.0012, seed: int = 3) -> pd.DataFrame:
    eth, btc = _closes(eth_drift, btc_drift, seed)
    return _panel_from(eth, btc)


def _bars() -> tuple[int, ...]:
    return (110, 150, 220, 300, 399)


# --------------------------------------------------------------------------- #
# vectorized == scalar oracle (causality by construction)                      #
# --------------------------------------------------------------------------- #
def test_candidate_a_vectorized_matches_scalar_oracle() -> None:
    panel = _panel()
    eth = panel[c.ETH_CLOSE].to_numpy()
    btc = panel[c.BTC_CLOSE].to_numpy()
    w = c.cross_asset_confirmation_weights(panel, **_A)
    for t in _bars():
        oracle = c.cross_asset_confirmation_weights_at(eth[: t + 1], btc[: t + 1], **_A)
        assert w[c.WEIGHT_ETH].iloc[t] == oracle[c.WEIGHT_ETH]


def test_candidate_b_vectorized_matches_scalar_oracle() -> None:
    panel = _panel()
    eth = panel[c.ETH_CLOSE].to_numpy()
    btc = panel[c.BTC_CLOSE].to_numpy()
    w = c.relative_strength_weights(panel, **_B)
    for t in _bars():
        oracle = c.relative_strength_weights_at(eth[: t + 1], btc[: t + 1], **_B)
        assert w[c.WEIGHT_ETH].iloc[t] == oracle[c.WEIGHT_ETH]
        assert w[c.WEIGHT_BTC].iloc[t] == oracle[c.WEIGHT_BTC]


# --------------------------------------------------------------------------- #
# future-price inertness: no future value changes an earlier signal            #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("weights", ["a", "b"])
def test_no_future_price_changes_an_earlier_signal(weights: str) -> None:
    eth, btc = _closes()
    t_cut = 250
    eth2, btc2 = eth.copy(), btc.copy()
    eth2[t_cut + 1 :] *= 1.25  # perturb both instruments strictly AFTER t_cut
    btc2[t_cut + 1 :] *= 1.25
    fn = c.cross_asset_confirmation_weights if weights == "a" else c.relative_strength_weights
    kw = _A if weights == "a" else _B
    w0 = fn(_panel_from(eth, btc), **kw)
    w1 = fn(_panel_from(eth2, btc2), **kw)
    # Weights up to and including t_cut must be identical (no look-ahead).
    pd.testing.assert_frame_equal(w0.iloc[: t_cut + 1], w1.iloc[: t_cut + 1])


# --------------------------------------------------------------------------- #
# BTC prefix dependence: a causally-available BTC change can change the future #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("weights", ["a", "b"])
def test_a_btc_prefix_change_can_change_future_but_not_past(weights: str) -> None:
    eth, btc = _closes()
    j = 120
    btc2 = btc.copy()
    btc2[j:] *= 0.6  # change BTC from bar j onward (a causally-available prefix perturbation)
    fn = c.cross_asset_confirmation_weights if weights == "a" else c.relative_strength_weights
    kw = _A if weights == "a" else _B
    w0 = fn(_panel_from(eth, btc), **kw)
    w1 = fn(_panel_from(eth, btc2), **kw)
    # Past (t < j) unchanged; the future can change (BTC genuinely enters the decision).
    pd.testing.assert_frame_equal(w0.iloc[:j], w1.iloc[:j])
    assert not w0.equals(w1)


# --------------------------------------------------------------------------- #
# information dependence: BTC removed/constant changes decisions (not ETH-only)#
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("weights", ["a", "b"])
def test_replacing_btc_with_a_constant_changes_the_decisions(weights: str) -> None:
    eth, btc = _closes()
    fn = c.cross_asset_confirmation_weights if weights == "a" else c.relative_strength_weights
    kw = _A if weights == "a" else _B
    real = fn(_panel_from(eth, btc), **kw)
    flat = fn(_panel_from(eth, np.full(_N, 100.0)), **kw)  # constant BTC carries no information
    # If the candidate genuinely used BTC, removing BTC information changes the weight path.
    assert not real.equals(flat)


def test_missing_btc_evidence_forces_refusal_not_fallback() -> None:
    eth, btc = _closes()
    btc2 = btc.copy()
    btc2[200] = np.nan
    bad = _panel_from(eth, btc2)
    with pytest.raises(c.V2BCandidateError, match="refuses"):
        c.cross_asset_confirmation_weights(bad, **_A)
    with pytest.raises(c.V2BCandidateError, match="refuses"):
        c.relative_strength_weights(bad, **_B)


# --------------------------------------------------------------------------- #
# constraints: long-only, gross<=1, <=1 risky (B), warm-up, determinism        #
# --------------------------------------------------------------------------- #
def test_candidates_are_long_only_and_gross_le_one() -> None:
    panel = _panel()
    for fn, kw in ((c.cross_asset_confirmation_weights, _A), (c.relative_strength_weights, _B)):
        w = fn(panel, **kw)
        assert (w[c.WEIGHT_ETH] >= 0).all()
        assert (w[c.WEIGHT_BTC] >= 0).all()
        assert (w[c.WEIGHT_ETH] + w[c.WEIGHT_BTC] <= 1.0 + 1e-12).all()


def test_candidate_b_holds_at_most_one_risky_asset() -> None:
    w = c.relative_strength_weights(_panel(), **_B)
    assert int(((w[c.WEIGHT_ETH] > 0) & (w[c.WEIGHT_BTC] > 0)).sum()) == 0


def test_warmup_is_flat() -> None:
    panel = _panel()
    wa = c.cross_asset_confirmation_weights(panel, **_A)
    assert (wa.iloc[: _A["eth_horizon"] - 1] == 0.0).all().all()
    wb = c.relative_strength_weights(panel, **_B)
    assert (wb.iloc[: _B["lookback"]] == 0.0).all().all()


def test_candidates_are_deterministic() -> None:
    panel = _panel()
    pd.testing.assert_frame_equal(
        c.cross_asset_confirmation_weights(panel, **_A),
        c.cross_asset_confirmation_weights(panel, **_A),
    )


def test_misaligned_panel_is_rejected() -> None:
    panel = _panel()
    broken = panel.rename(columns={c.BTC_CLOSE: "not_btc"})
    with pytest.raises(c.V2BCandidateError, match="missing"):
        c.cross_asset_confirmation_weights(broken, **_A)


# --------------------------------------------------------------------------- #
# spec validity, novelty, distinctness matrix                                  #
# --------------------------------------------------------------------------- #
def test_v2b_candidate_set_is_valid_and_genuinely_new() -> None:
    c.assert_v2b_candidate_set_valid(c.V2B_CANDIDATES)
    assert len(c.V2B_CANDIDATES) == 2


def test_candidate_distinctness_matrix_vs_all_history_and_each_other() -> None:
    catalog_fps = rm.cataloged_fingerprints()
    v2b_fps = [s.identity.fingerprint() for s in c.V2B_CANDIDATES]
    # Distinct from every previously-evaluated family (M3A/M3B/M3C/V2A + benchmarks)...
    for fp in v2b_fps:
        assert fp not in catalog_fps
    # ...and from each other.
    assert len(set(v2b_fps)) == len(v2b_fps)
    # Both genuinely read BTC and require cross-asset context.
    for spec in c.V2B_CANDIDATES:
        assert "btc" in spec.identity.input_instruments
        assert spec.identity.context_requirement == "cross_asset_required"


def test_a_second_candidate_that_relabels_the_first_is_rejected() -> None:
    a_relabel = dataclasses.replace(
        c.CANDIDATE_A, candidate_id="sneaky_duplicate", fixed_parameters={"eth_horizon": 101}
    )
    with pytest.raises(c.V2BCandidateError, match="aliased split"):
        c.assert_v2b_candidate_set_valid((c.CANDIDATE_A, a_relabel))
