"""V2B cumulative research-memory + anti-relabel verifier.

Verifies the five committed research-memory artifacts reproduce byte-for-byte, the exposure ledger
is a sound append-only hash chain, and the fail-closed anti-relabel verifier refuses every way a
previously-evaluated family could be disguised as "new" (rename, alias, module move, parameter
shift, overlay relocation, benchmark relabel, aliased split) while accepting a genuinely new
cross-asset family.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from eth_research.v2b import research_memory as rm

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _by_id(prefix: str) -> rm.ResearchFamilyIdentity:
    for family in rm.RESEARCH_FAMILY_CATALOG:
        if family.family_id.startswith(prefix):
            return family.identity
    raise AssertionError(f"no cataloged family with id prefix {prefix!r}")


# --------------------------------------------------------------------------- #
# artifacts reproduce + verify                                                 #
# --------------------------------------------------------------------------- #
def test_research_memory_verifies_clean_on_committed_tree() -> None:
    assert rm.verify_research_memory(_REPO_ROOT) == []


def test_all_five_artifacts_reproduce_byte_for_byte() -> None:
    builders = {
        rm.FAMILY_CATALOG_RELPATH: rm.build_family_catalog_bytes,
        rm.SIMILARITY_POLICY_RELPATH: rm.build_similarity_policy_bytes,
        rm.REJECTED_INDEX_RELPATH: rm.build_rejected_family_index_bytes,
        rm.EXPOSURE_LEDGER_RELPATH: rm.build_exposure_ledger_bytes,
        rm.MEMORY_STATE_RELPATH: rm.build_memory_state_bytes,
    }
    for relpath, builder in builders.items():
        assert (_REPO_ROOT / relpath).read_bytes() == builder(), relpath


def test_catalog_families_have_distinct_semantic_fingerprints() -> None:
    fps = [f.identity.fingerprint() for f in rm.RESEARCH_FAMILY_CATALOG]
    assert len(set(fps)) == len(fps) == 10


def test_exposure_ledger_is_a_sound_hash_chain() -> None:
    from eth_research.m3d.chain import load_and_verify_chain

    raw, records = load_and_verify_chain(_REPO_ROOT, rm.EXPOSURE_LEDGER_RELPATH)
    assert raw != b""
    assert records[0]["kind"] == "research_exposure_genesis"
    assert all(
        r["kind"] in {"research_exposure_genesis", "research_family_exposure"} for r in records
    )


def test_historical_candidate_family_count_is_eight() -> None:
    # M3A sma+donchian (2), M3B vol_target x2 (2), M3C dual (1), V2A x3 (3) = 8; benchmarks omitted.
    # (benchmark families do not count against the cumulative candidate/alpha budget)
    assert rm.historical_candidate_family_count() == 8
    assert all(f.role == "benchmark" or f.is_rejected() for f in rm.RESEARCH_FAMILY_CATALOG)


# --------------------------------------------------------------------------- #
# anti-relabel adversarial matrix (each must fail closed)                       #
# --------------------------------------------------------------------------- #
def test_renamed_or_module_moved_family_is_rejected() -> None:
    # A cosmetic rename / module move / new experiment id changes nothing in the semantic identity.
    identity = _by_id("v2a_meanrev")
    with pytest.raises(rm.ResearchMemoryError, match="relabels"):
        rm.assert_family_is_new(identity)


def test_m3c_dual_horizon_wrapped_in_alias_is_rejected() -> None:
    aliased = dataclasses.replace(_by_id("m3c_dual"), signal_family="twin_horizon_trend")
    with pytest.raises(rm.ResearchMemoryError, match="relabels"):
        rm.assert_family_is_new(aliased)


def test_sma_represented_as_weighted_thresholds_is_rejected() -> None:
    aliased = dataclasses.replace(
        _by_id("m3a_sma"), signal_family="weighted_threshold_moving_average"
    )
    with pytest.raises(rm.ResearchMemoryError, match="relabels"):
        rm.assert_family_is_new(aliased)


def test_donchian_as_rolling_extrema_alias_is_rejected() -> None:
    aliased = dataclasses.replace(_by_id("m3a_donchian"), signal_family="rolling_extrema_breakout")
    with pytest.raises(rm.ResearchMemoryError, match="relabels"):
        rm.assert_family_is_new(aliased)


def test_volatility_overlay_moved_into_engine_is_rejected() -> None:
    # Whether the vol overlay lives in a RiskConfig or inside the engine, the identity flag is the
    # same, so re-declaring M3B's vol-target buy-and-hold collides.
    identity = _by_id("m3b_vol_target_buy_and_hold")
    assert identity.volatility_overlay is True
    with pytest.raises(rm.ResearchMemoryError, match="relabels"):
        rm.assert_family_is_new(identity)


def test_parameter_shifted_by_one_day_is_rejected() -> None:
    # The identity is value-free: a horizon shifted by an immaterial amount is the same family.
    # Reconstructing M3C's identity (structure only, no 63/252 values) still collides.
    identity = rm.ResearchFamilyIdentity(
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
    assert identity.fingerprint() == _by_id("m3c_dual").fingerprint()
    with pytest.raises(rm.ResearchMemoryError, match="relabels"):
        rm.assert_family_is_new(identity)


def test_unknown_signal_family_fails_closed_at_construction() -> None:
    with pytest.raises(rm.ResearchMemoryError, match="neither canonical nor a known alias"):
        rm.ResearchFamilyIdentity(
            signal_family="totally_new_secret_mechanism",
            signal_source="own_close_price",
            input_instruments=("eth",),
            executed_instruments=("eth",),
            horizon_structure="single_horizon",
            threshold_structure="sma_sign_gate",
            allocation_structure="binary_long_or_cash",
            risk_overlay="none",
            volatility_overlay=False,
            drawdown_overlay=False,
            cost_model_family="causal_proxy",
            context_requirement="own_price_only",
            benchmark="buy_and_hold",
            primary_endpoint="paired_log_excess_return",
            partition="research_train",
        )


def test_benchmark_relabeled_as_candidate_is_rejected() -> None:
    # The passive ETH buy-and-hold benchmark's semantic identity cannot be smuggled back in.
    identity = _by_id("passive_eth_buy_and_hold")
    with pytest.raises(rm.ResearchMemoryError, match="relabels"):
        rm.assert_family_is_new(identity)


def test_candidate_split_into_aliases_is_rejected() -> None:
    # One real family declared twice (once canonical, once aliased) collapses to one identity.
    canonical = _by_id("m3a_donchian")
    aliased = dataclasses.replace(canonical, signal_family="rolling_max_min_channel")
    with pytest.raises(rm.ResearchMemoryError, match="aliased split"):
        rm.assert_declared_families_distinct((canonical, aliased))


def test_reviving_a_rejected_family_is_rejected() -> None:
    with pytest.raises(rm.ResearchMemoryError, match="rejected"):
        rm.assert_not_reviving_rejected(_by_id("m3c_dual"))


def test_a_genuinely_new_cross_asset_family_is_accepted() -> None:
    # BTC-input, cross-asset-required family: no prior family reads BTC, so it is genuinely new.
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
    returned = rm.assert_family_is_new(new)
    assert returned.fingerprint() == new.fingerprint()
    assert new.fingerprint() not in rm.cataloged_fingerprints()


# --------------------------------------------------------------------------- #
# similarity policy + tamper                                                    #
# --------------------------------------------------------------------------- #
def test_similarity_policy_excludes_every_cosmetic_attribute() -> None:
    excluded = set(rm.FAMILY_SIMILARITY_POLICY.identity_excluded_attributes)
    for attr in ("display_name", "class_name", "module_path", "experiment_id", "package_version"):
        assert attr in excluded


def test_a_tampered_catalog_file_is_rejected(tmp_path: Path) -> None:
    for relpath, builder in (
        (rm.FAMILY_CATALOG_RELPATH, rm.build_family_catalog_bytes),
        (rm.SIMILARITY_POLICY_RELPATH, rm.build_similarity_policy_bytes),
        (rm.REJECTED_INDEX_RELPATH, rm.build_rejected_family_index_bytes),
        (rm.EXPOSURE_LEDGER_RELPATH, rm.build_exposure_ledger_bytes),
        (rm.MEMORY_STATE_RELPATH, rm.build_memory_state_bytes),
    ):
        dest = tmp_path / relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(builder())
    assert rm.verify_research_memory(tmp_path) == []
    # Flip one byte of the catalog: verification must flag it.
    catalog = tmp_path / rm.FAMILY_CATALOG_RELPATH
    catalog.write_bytes(catalog.read_bytes().replace(b"research_train", b"final_holdout", 1))
    problems = rm.verify_research_memory(tmp_path)
    assert any("research_family_catalog" in p for p in problems)
