"""Independent family-catalog enumeration audit and anti-relabel semantic tests.

Confirms the independent enumeration reconciles to ten candidate families (eight historical, three
of them V2A, plus two V2B) with two benchmarks excluded, and proves -- semantically -- a rejected
family cannot be resurrected by renaming, wrapping, moving logic, reserializing, shifting a horizon,
relocating a risk overlay, changing an experiment id or package version, rewriting benchmark prose,
or rescaling output.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from eth_research.v2ab import family_catalog_audit as fca
from eth_research.v2b import research_memory as rm

_REPO_ROOT = Path(__file__).resolve().parents[1]

_HISTORICAL_CANDIDATE_IDS = frozenset(
    {
        "m3a_sma_crossover",
        "m3a_donchian_breakout",
        "m3b_vol_target_buy_and_hold_30d_50pct",
        "m3b_vol_target_donchian_55_20_30d_50pct",
        "m3c_dual_horizon_trend_63_252_vol_target_30d_50pct",
        "v2a_meanrev_zscore_accumulation",
        "v2a_trend_regime_single_horizon",
        "v2a_vol_scaled_hold_drawdown_guard",
    }
)


def _identity(prefix: str) -> rm.ResearchFamilyIdentity:
    for family in rm.RESEARCH_FAMILY_CATALOG:
        if family.family_id.startswith(prefix):
            return family.identity
    raise AssertionError(f"no cataloged family with id prefix {prefix!r}")


# --------------------------------------------------------------------------- #
# enumeration + reconciliation                                                 #
# --------------------------------------------------------------------------- #
def test_verify_family_catalog_is_clean_on_committed_tree() -> None:
    assert fca.verify_family_catalog(_REPO_ROOT) == []


def test_independent_enumeration_finds_twelve_families() -> None:
    records = fca.enumerate_historical_families(_REPO_ROOT)
    assert len(records) == 12
    assert all(r.classification in fca.FAMILY_CLASSIFICATIONS for r in records)


def test_cumulative_count_reconciles_to_ten_candidates() -> None:
    counts = fca.reconcile_cumulative_count(_REPO_ROOT)
    assert counts == {
        "candidate_families": 10,
        "historical_candidate_families": 8,
        "v2a_candidate_families": 3,
        "v2b_candidate_families": 2,
        "benchmark_families": 2,
    }


def test_historical_candidate_set_matches_the_required_families() -> None:
    records = fca.enumerate_historical_families(_REPO_ROOT)
    historical = {
        r.family_id
        for r in records
        if r.classification == "candidate_family" and r.milestone in {"m3a", "m3b", "m3c", "v2a"}
    }
    assert historical == _HISTORICAL_CANDIDATE_IDS
    candidates = {r.family_id for r in records if r.classification == "candidate_family"}
    assert candidates >= fca.REQUIRED_CANDIDATE_FAMILY_IDS


def test_required_families_include_sma_donchian_vol_and_drawdown_and_dual_horizon() -> None:
    signals = {r.signal_family for r in fca.enumerate_historical_families(_REPO_ROOT)}
    for signal in (
        "moving_average_crossover",
        "donchian_breakout",
        "dual_horizon_trend",
        "mean_reversion_zscore",
        "single_horizon_sma_gate",
    ):
        assert signal in signals


def test_benchmarks_do_not_count_against_the_budget() -> None:
    for record in fca.enumerate_historical_families(_REPO_ROOT):
        assert record.counts_against_budget == (record.classification == "candidate_family")
    benchmarks = [
        r for r in fca.enumerate_historical_families(_REPO_ROOT) if r.classification == "benchmark"
    ]
    assert {r.family_id for r in benchmarks} == {
        "cash_benchmark",
        "passive_eth_buy_and_hold_benchmark",
    }


def test_observed_labels_are_all_classified() -> None:
    labels = fca.observed_strategy_labels(_REPO_ROOT)
    assert labels <= set(fca.STRATEGY_CLASSIFIER)
    assert "sma_20_50" in labels
    assert "cross_asset_btc_confirmed_eth_trend" in labels


def test_unknown_strategy_label_fails_closed(tmp_path: Path) -> None:
    research = tmp_path / "research"
    for sub in ("m3a", "m3b", "m3c", "v2a", "v2b"):
        (research / sub).mkdir(parents=True)
    (research / "m3a" / "experiment_registry.jsonl").write_text(
        '{"strategies":["cash","totally_unknown_strat"]}\n'
    )
    (research / "m3b" / "experiment_registry.jsonl").write_text('{"strategies":["cash"]}\n')
    (research / "m3c" / "experiment_registry.jsonl").write_text('{"strategies":["cash"]}\n')
    (research / "v2a" / "results.json").write_text('{"decision":{"outcomes":[]}}')
    (research / "v2b" / "v2b_results.json").write_text('{"result":{"candidates":[]}}')
    with pytest.raises(fca.CatalogAuditError, match="not classified"):
        fca.enumerate_historical_families(tmp_path)


def test_tampered_multiplicity_total_is_flagged(tmp_path: Path) -> None:
    import shutil

    shutil.copytree(_REPO_ROOT / "research", tmp_path / "research")
    state = tmp_path / "research" / "v2b" / "research_multiplicity_state.json"
    state.write_bytes(
        state.read_bytes().replace(b'"total_family_count": 10', b'"total_family_count": 11')
    )
    problems = fca.verify_family_catalog(tmp_path)
    assert any("reconcile to 10" in p or "total_family_count" in p for p in problems)


# --------------------------------------------------------------------------- #
# anti-relabel semantic control (a rejected family cannot be resurrected)       #
# --------------------------------------------------------------------------- #
def test_semantic_fingerprint_matches_the_shared_identity() -> None:
    identity = _identity("m3c_dual")
    assert fca.semantic_family_fingerprint(identity) == identity.fingerprint()


def test_cosmetic_attributes_can_never_change_identity() -> None:
    # Rename, wrap, move logic, reserialize, change experiment id / package version, rewrite
    # benchmark prose, or rescale output: every such attribute is identity-excluded, so the M3C
    # dual-horizon family stays a relabel of an evaluated family.
    excluded = set(rm.FAMILY_SIMILARITY_POLICY.identity_excluded_attributes)
    for attr in (
        "display_name",
        "class_name",
        "module_path",
        "wrapper_function",
        "serialization_order",
        "experiment_id",
        "package_version",
        "candidate_description",
        "output_scaling",
        "horizon_value",
    ):
        assert attr in excluded
    assert fca.is_relabel_of_evaluated_family(_identity("m3c_dual"))


def test_alias_rename_is_still_a_relabel() -> None:
    aliased = dataclasses.replace(_identity("m3c_dual"), signal_family="twin_horizon_trend")
    assert fca.is_relabel_of_evaluated_family(aliased)
    with pytest.raises(fca.CatalogAuditError, match="relabels"):
        fca.assert_not_resurrected_by_relabel(aliased)


def test_trivial_horizon_shift_is_the_same_family() -> None:
    # The identity is value-free: rebuilding M3C's structure (no 63/252 values) collides.
    rebuilt = rm.ResearchFamilyIdentity(
        signal_family="dual_horizon_trend",
        signal_source="own_close_price",
        input_instruments=("eth",),
        executed_instruments=("eth",),
        horizon_structure="dual_horizon",
        threshold_structure="dual_trend_agreement",
        allocation_structure="continuous_unit_interval",
        risk_overlay="volatility_target",
        volatility_overlay=True,
        drawdown_overlay=False,
        cost_model_family="causal_proxy",
        context_requirement="own_price_only",
        benchmark="buy_and_hold",
        primary_endpoint="paired_log_excess_return",
        partition="research_train",
    )
    assert rebuilt.fingerprint() == _identity("m3c_dual").fingerprint()
    assert fca.is_relabel_of_evaluated_family(rebuilt)


def test_risk_overlay_relocation_signal_to_engine_is_the_same_family() -> None:
    equivalences = dict(rm.FAMILY_SIMILARITY_POLICY.structural_equivalences)
    assert equivalences["engine_internal_volatility_target"] == "volatility_target"
    assert equivalences["riskconfig_volatility_target"] == "volatility_target"
    identity = _identity("m3b_vol_target_buy_and_hold")
    assert identity.volatility_overlay is True
    assert fca.is_relabel_of_evaluated_family(identity)


def test_moved_or_renamed_candidate_is_rejected() -> None:
    for prefix in ("v2a_meanrev", "m3a_sma", "m3a_donchian"):
        with pytest.raises(fca.CatalogAuditError, match="relabels"):
            fca.assert_not_resurrected_by_relabel(_identity(prefix))


def test_genuinely_new_cross_asset_family_is_not_a_relabel() -> None:
    new = rm.ResearchFamilyIdentity(
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
    assert not fca.is_relabel_of_evaluated_family(new)
    fca.assert_not_resurrected_by_relabel(new)  # must not raise
