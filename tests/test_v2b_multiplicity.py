"""V2B cumulative multiplicity / alpha-spending policy + new-information requirement."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from eth_research.v2b import multiplicity as mp
from eth_research.v2b import research_memory as rm

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_multiplicity_state_reproduces_and_verifies() -> None:
    assert mp.verify_multiplicity(_REPO_ROOT) == []
    committed = (_REPO_ROOT / mp.MULTIPLICITY_STATE_RELPATH).read_bytes()
    assert committed == mp.build_multiplicity_state_bytes()


def test_cumulative_correction_counts_all_history_plus_v2b() -> None:
    state = mp.ResearchMultiplicityState.current()
    assert state.historical_family_count == rm.historical_candidate_family_count() == 8
    assert state.v2a_family_count == 3
    assert state.v2b_max_family_count == 2
    assert state.total_family_count() == 10
    # 0.05 family-wise budget over 10 families → 0.005 per-family, 99.5% one-sided confidence.
    assert state.corrected_per_family_alpha() == pytest.approx(0.005)
    assert state.corrected_one_sided_confidence() == pytest.approx(0.995)


def test_correction_is_stricter_than_the_uncorrected_five_percent() -> None:
    state = mp.ResearchMultiplicityState.current()
    assert state.corrected_per_family_alpha() < mp.HISTORICAL_NOMINAL_ALPHA
    assert state.corrected_one_sided_confidence() > 0.95


def test_policy_declares_no_reset_and_documents_limitations() -> None:
    canonical = mp.ResearchMultiplicityState.current().to_canonical()
    assert canonical["no_reset"] is True
    limitations = canonical["limitations"]
    assert isinstance(limitations, list)
    assert len(limitations) >= 3
    joined = " ".join(str(x) for x in limitations).lower()
    assert "researcher degrees of freedom" in joined
    assert "never reset" in joined or "does not refresh" in joined


def test_reset_attempt_is_rejected() -> None:
    with pytest.raises(mp.MultiplicityError, match="no_reset"):
        dataclasses.replace(mp.ResearchMultiplicityState.current(), no_reset=False)


def test_parse_rejects_a_drifted_multiplicity_state() -> None:
    good = mp.ResearchMultiplicityState.current().to_canonical()
    mp.ResearchMultiplicityState.parse(good)  # round-trips
    drifted = {**good, "cumulative_alpha_budget": 0.5}
    with pytest.raises(mp.MultiplicityError, match="drifted"):
        mp.ResearchMultiplicityState.parse(drifted)


# --------------------------------------------------------------------------- #
# §6 new-information requirement                                                #
# --------------------------------------------------------------------------- #
def _cross_asset_identity() -> rm.ResearchFamilyIdentity:
    return rm.ResearchFamilyIdentity(
        signal_family="cross_asset_trend_confirmation",
        signal_source="cross_asset_close_price",
        input_instruments=("btc", "eth"),
        executed_instruments=("eth",),
        horizon_structure="single_horizon",
        threshold_structure="cross_asset_confirmation_gate",
        allocation_structure="binary_long_or_cash",
        risk_overlay="none",
        volatility_overlay=False,
        drawdown_overlay=False,
        cost_model_family="causal_proxy",
        context_requirement="cross_asset_required",
        benchmark="buy_and_hold",
        primary_endpoint="paired_log_excess_return",
        partition="research_train",
    )


def test_new_information_requirement_accepts_a_btc_reading_candidate() -> None:
    mp.assert_uses_new_information(_cross_asset_identity())  # no raise


def test_new_information_requirement_rejects_an_eth_only_candidate() -> None:
    eth_only = _by_id("v2a_trend")
    with pytest.raises(mp.MultiplicityError, match="does not use the new information"):
        mp.assert_uses_new_information(eth_only)


def test_new_information_requirement_rejects_a_btc_reading_but_eth_only_context() -> None:
    # Reads BTC but declares own_price_only context: a missing-BTC ETH-only fallback is forbidden.
    sneaky = dataclasses.replace(_cross_asset_identity(), context_requirement="own_price_only")
    with pytest.raises(mp.MultiplicityError, match="ETH-only fallback"):
        mp.assert_uses_new_information(sneaky)


def _by_id(prefix: str) -> rm.ResearchFamilyIdentity:
    for family in rm.RESEARCH_FAMILY_CATALOG:
        if family.family_id.startswith(prefix):
            return family.identity
    raise AssertionError(f"no cataloged family with id prefix {prefix!r}")
