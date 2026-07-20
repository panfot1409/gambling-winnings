"""V2B §29 — the immutable results record and its transactional publication."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from eth_research.v2.strict import canonical_json_bytes
from eth_research.v2b import orchestrator as orch
from eth_research.v2b import publication as pub
from eth_research.v2b import results as res
from eth_research.v2b.folds import EXPECTED_ROWS, build_oos_folds
from eth_research.v2b.scenarios import COST_SCENARIOS, PRIMARY_COST, STRESSED_COST

FP = "a" * 64


@pytest.fixture(scope="module")
def frozen() -> res.FrozenV2BResults:
    rng = np.random.default_rng(20260726)
    n = EXPECTED_ROWS
    idx = pd.date_range("2016-05-23", periods=n, freq="D", tz="UTC")
    eth = 10.0 * np.cumprod(1.0 + rng.normal(0.0008, 0.03, n))
    btc = 450.0 * np.cumprod(1.0 + rng.normal(0.0006, 0.025, n))
    frame: dict[str, np.ndarray] = {}
    for name, close in (("eth", eth), ("btc", btc)):
        frame[f"{name}_open"] = close * 0.999
        frame[f"{name}_high"] = close * 1.02
        frame[f"{name}_low"] = close * 0.98
        frame[f"{name}_close"] = close
        frame[f"{name}_volume"] = np.full(n, 1_000.0)
    panel = pd.DataFrame(frame, index=idx)
    folds = build_oos_folds(pd.DatetimeIndex(panel.index))
    result = orch.evaluate_program(
        panel,
        folds,
        primary_cost=COST_SCENARIOS[PRIMARY_COST],
        stressed_cost=COST_SCENARIOS[STRESSED_COST],
        corrected_alpha=0.005,
    )
    outcome = orch.OneShotOutcome(protocol_fingerprint=FP, result=result)
    return res.build_results(outcome, run_id="v2b_run_001", package_version="2.0.0.dev1")


def test_build_results_binds_the_run_identity(frozen: res.FrozenV2BResults) -> None:
    assert frozen.run_id == "v2b_run_001"
    assert frozen.protocol_fingerprint == FP
    assert frozen.verdict == frozen.result.verdict
    assert frozen.nominated_candidate_id == frozen.result.decision.nominated_candidate_id


def test_summarize_committed_matches_the_frozen_record(frozen: res.FrozenV2BResults) -> None:
    raw = canonical_json_bytes(frozen.to_canonical())
    summary = res.summarize_committed(raw)
    # The committed document re-canonicalises to exactly the frozen record's fingerprint.
    assert summary.fingerprint == frozen.fingerprint()
    assert summary.run_id == frozen.run_id
    assert summary.protocol_fingerprint == frozen.protocol_fingerprint
    assert summary.verdict == frozen.verdict
    assert summary.nominated_candidate_id == frozen.nominated_candidate_id


def test_publish_results_writes_and_verifies(tmp_path: Path, frozen: res.FrozenV2BResults) -> None:
    receipt = pub.publish_results(tmp_path, frozen)
    assert (tmp_path / "research/v2b/v2b_results.json").exists()
    assert (tmp_path / "research/v2b/v2b_results_manifest.json").exists()
    assert pub.verify_publication(tmp_path) == []
    assert receipt.results_fingerprint == frozen.fingerprint()


def test_tampering_the_published_results_is_detected(
    tmp_path: Path, frozen: res.FrozenV2BResults
) -> None:
    pub.publish_results(tmp_path, frozen)
    results_path = tmp_path / "research/v2b/v2b_results.json"
    tampered = results_path.read_bytes().replace(b'"v2b_run_001"', b'"v2b_run_999"')
    results_path.write_bytes(tampered)
    assert pub.verify_publication(tmp_path)  # non-empty: sha/manifest disagree with the bytes


def test_missing_publication_is_reported(tmp_path: Path) -> None:
    assert pub.verify_publication(tmp_path)  # nothing published under research/v2b
