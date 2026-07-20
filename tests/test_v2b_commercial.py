"""V2B §24-25 — the multi-asset shadow policy/vectors and the not-sell-ready buyer evidence."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd

import eth_research
from eth_research.v2b import buyer_evidence as be
from eth_research.v2b import shadow as sh
from eth_research.v2b.candidates import CANDIDATE_A, CANDIDATE_B

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def _panel(rows: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(20260724)
    index = pd.date_range("2016-05-23", periods=rows, freq="D", tz="UTC")
    eth = 10.0 * np.cumprod(1.0 + rng.normal(0.001, 0.03, rows))
    btc = 450.0 * np.cumprod(1.0 + rng.normal(0.001, 0.025, rows))
    frame = {}
    for name, close in (("eth", eth), ("btc", btc)):
        frame[f"{name}_open"] = close * 0.999
        frame[f"{name}_high"] = close * 1.02
        frame[f"{name}_low"] = close * 0.98
        frame[f"{name}_close"] = close
        frame[f"{name}_volume"] = np.full(rows, 1_000.0)
    return pd.DataFrame(frame, index=index)


# --------------------------------------------------------------------------- #
# §24 multi-asset shadow                                                       #
# --------------------------------------------------------------------------- #
def test_shadow_policy_reproduces_and_lists_prohibitions() -> None:
    sh.verify_shadow_policy(REPO_ROOT)
    policy = sh.build_shadow_policy()
    assert policy["instruments"] == ["eth_usd", "btc_usd"]
    assert set(policy["modes"]) == set(sh.SHADOW_MODES)
    assert policy["signal_only"] is True
    for banned in ("no_network", "no_orders", "no_credentials", "no_money_movement"):
        assert banned in policy["prohibitions"]


def test_shadow_vectors_are_long_only_gross_leq_one_and_causal() -> None:
    panel = _panel()
    vectors = sh.build_shadow_vectors(CANDIDATE_B, panel)
    assert len(vectors) == len(panel)
    # First bar is flat (a one-bar causal lag means no signal has formed yet).
    assert vectors[0].eth.target_weight == 0.0
    assert vectors[0].btc.target_weight == 0.0
    for v in vectors:
        we, wb = v.eth.target_weight, v.btc.target_weight
        assert we >= 0.0
        assert wb >= 0.0
        assert we + wb <= 1.0 + 1e-9
        assert v.cash_weight == max(0.0, 1.0 - we - wb)
        assert v.eth.candidate_id == CANDIDATE_B.candidate_id


def test_shadow_summary_counts_partition_the_bars() -> None:
    panel = _panel()
    summary = sh.build_shadow_summary(CANDIDATE_A, panel)
    assert summary.bar_count == len(panel)
    assert (
        summary.eth_active_bars + summary.btc_active_bars + summary.cash_bars == summary.bar_count
    )
    # Candidate A only ever holds ETH or cash (BTC is a confirmation gate, never allocated to).
    assert summary.btc_active_bars == 0
    assert summary.leg_transitions >= 0


def test_shadow_vector_as_of_is_the_bar_open_and_ordered() -> None:
    panel = _panel()
    vectors = sh.build_shadow_vectors(CANDIDATE_A, panel)
    stamps = [v.as_of for v in vectors]
    for a, b in pairwise(stamps):
        assert a < b  # strictly increasing, one envelope per bar


# --------------------------------------------------------------------------- #
# §25 buyer evidence                                                           #
# --------------------------------------------------------------------------- #
def test_buyer_evidence_reproduces_and_stays_not_sell_ready() -> None:
    be.verify_buyer_evidence(REPO_ROOT)
    doc = be.build_buyer_evidence()
    assert doc["sell_ready"] is False
    assert doc["posture"] == "not_sell_ready"
    assert doc["factsheet"]["posture"] == "not_sell_ready"
    for key in ("contract_fingerprint", "claims_fingerprint", "scorecard_fingerprint"):
        assert len(doc[key]) == 64


def test_buyer_evidence_preserves_prior_and_v2b_negatives() -> None:
    doc = be.build_buyer_evidence()
    limitations = " ".join(doc["v2b_limitations"]).lower()
    # V2A's negative is carried forward, and V2B's own limitations are stated.
    assert "v2a returned no nominated" in limitations
    assert "research-train" in limitations
    assert "independent development-gate review" in limitations
    assert "an offer to sell" in limitations
    assert "multiplicity correction" in limitations
    assert len(doc["v2b_limitations"]) == len(be.V2B_LIMITATIONS)
