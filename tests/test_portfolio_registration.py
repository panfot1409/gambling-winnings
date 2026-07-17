"""The committed M4B registration artifacts are current, bind the frozen identities, fail closed.

The R-phase artifacts under ``research/m4b/`` pin the additive portfolio layer: the reference
universe / protocol identities, the reference run's expected results (``result_id`` and headline
scalars), the portfolio subpackage's distribution manifest, and a source-freeze that binds every
committed M4B artifact, the accepted M4A v1.0 artifacts, and the three sealed ledgers. These tests
prove the committed bytes match the running source, reproduce the frozen reference identity from a
fresh run, and confirm the drift guard fails closed.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from eth_research.portfolio import registration
from eth_research.portfolio.engine import run_portfolio_simulation
from eth_research.portfolio.metrics import compute_portfolio_metrics
from eth_research.portfolio.reference import build_reference_universe, reference_protocol
from eth_research.portfolio.result import build_portfolio_result, verify_portfolio_result

REPO = Path(__file__).resolve().parents[1]
_SECONDS_PER_YEAR = 365.25 * 24.0 * 3600.0


def test_registration_artifacts_are_current() -> None:
    # Fails closed if any committed R-phase artifact drifted from the running source.
    registration.verify(REPO)


def test_source_freeze_ledgers_are_byte_empty() -> None:
    freeze = json.loads((REPO / registration.SOURCE_FREEZE_RELPATH).read_bytes())
    assert set(freeze["sealed_ledgers"]) == set(registration.SEALED_LEDGERS)
    for rel, digest in freeze["sealed_ledgers"].items():
        assert digest == registration.EMPTY_SHA, rel


def test_source_freeze_binds_accepted_m4a_artifacts_unchanged() -> None:
    from eth_research.api.serialization import sha256_hex

    freeze = json.loads((REPO / registration.SOURCE_FREEZE_RELPATH).read_bytes())
    assert set(freeze["m4a_accepted_artifacts"]) == set(registration.M4A_ACCEPTED_ARTIFACTS)
    for rel, digest in freeze["m4a_accepted_artifacts"].items():
        # The bound hash must equal the accepted M4A artifact as it stands on disk (additive: M4B
        # leaves every accepted artifact byte-for-byte unchanged).
        assert digest == sha256_hex((REPO / rel).read_bytes()), rel


def test_source_freeze_pins_version_and_api() -> None:
    freeze = json.loads((REPO / registration.SOURCE_FREEZE_RELPATH).read_bytes())
    assert freeze["package_version"] == "1.1.0"
    assert freeze["api_version"] == "1.1"
    assert freeze["forbidden_capabilities_absent"] is True


def test_reference_expected_results_match_a_fresh_run() -> None:
    # The pinned expected results must reproduce byte-exactly from a fresh reference run.
    pinned = json.loads((REPO / registration.REFERENCE_RESULTS_RELPATH).read_bytes())
    reference = build_reference_universe()
    run = run_portfolio_simulation(
        reference_protocol(),
        reference.panel,
        reference.membership,
        reference.fx,
        reference.run_schedule,
        calendars=reference.calendars,
        corporate_actions=reference.corporate_actions,
    )
    ppy = _SECONDS_PER_YEAR / reference.universe_spec.bar_interval_seconds
    metrics = compute_portfolio_metrics(run, periods_per_year=ppy)
    result = build_portfolio_result(run, metrics, reference.universe_spec)
    verify_portfolio_result(result, reference.universe_spec, run)
    assert result.result_id == pinned["result_id"]
    assert result.universe_fingerprint == pinned["universe_fingerprint"]
    assert result.run_result_fingerprint == pinned["run_result_fingerprint"]
    assert result.trace_commitment.commitment_id == pinned["trace_commitment_id"]
    assert result.terminal_equity == pinned["terminal_equity"]
    assert result.num_fills == pinned["num_fills"]


def test_distribution_manifest_lists_every_portfolio_member() -> None:
    manifest = json.loads((REPO / registration.DISTRIBUTION_MANIFEST_RELPATH).read_bytes())
    on_disk = {
        p.relative_to(REPO / "src").as_posix()
        for p in (REPO / "src" / "eth_research" / "portfolio").rglob("*.py")
        if "__pycache__" not in p.parts
    }
    listed = {member["path"] for member in manifest["portfolio_members"]}
    assert listed == on_disk
    assert manifest["member_count"] == len(on_disk)
    assert manifest["version"] == "1.1.0"


def _mirror(root: Path) -> Path:
    """A minimal repo mirror carrying everything ``registration.verify`` reads."""
    for rel in ("src/eth_research/portfolio", "research/m4a", "research/m4b"):
        shutil.copytree(REPO / rel, root / rel)
    for ledger in registration.SEALED_LEDGERS:
        (root / ledger).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / ledger, root / ledger)
    return root


def test_registration_current_against_a_mirror(tmp_path: Path) -> None:
    registration.verify(_mirror(tmp_path))  # sanity: the mirror itself is current


def test_registration_drift_is_detected(tmp_path: Path) -> None:
    from eth_research.api.serialization import canonical_json_bytes

    root = _mirror(tmp_path)
    target = root / registration.REFERENCE_RESULTS_RELPATH
    payload = json.loads(target.read_bytes())
    payload["terminal_equity"] = payload["terminal_equity"] + 1.0  # a lie about the pinned identity
    # Write it back canonically (trailing newline, sorted keys) so the drift is the *value*,
    # exercising the drift comparison rather than the strict-parse guard.
    target.write_bytes(canonical_json_bytes(payload))
    with pytest.raises(registration.RegistrationDriftError):
        registration.verify(root)


def test_registration_missing_artifact_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(registration.RegistrationDriftError):
        registration.verify(tmp_path)
