"""V2C section 22: the independent OQ-Q acceptance oracle.

Proves the oracle's independent copies do not drift from the source of truth, that it accepts an
honest qualified result, and that it refuses every forgery -- a claimed-qualified result with
nonzero risky exposure, a flipped criterion, an injected performance term, a tampered digest, a
wrong criteria set, or a verdict that disagrees with the evidence. It never accepts an overclaim.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.environment import CANONICAL_RUNTIME_CONTRACT_RELPATH
from eth_research.v2c.oq import archive as A
from eth_research.v2c.oq import completion as C
from eth_research.v2c.oq import finalize as Fz
from eth_research.v2c.oq import oracle as OR
from eth_research.v2c.oq import orchestrator as O
from eth_research.v2c.oq import protocol as P
from eth_research.v2c.oq import run as R
from eth_research.v2c.oq.events import OQ_MIN_ACCEPTED_EVENTS
from eth_research.v2c.oq.freeze import OQ_SOURCE_FREEZE_RELPATH
from eth_research.v2c.oq.registry import (
    OQ_REGISTRY_PATH,
    OQ_VERDICT_QUALIFIED,
    QualificationIdentity,
)
from eth_research.v2c.oq.slo import QUALIFICATION_CRITERIA
from eth_research.v2c.oq.supersession import OQ_SUPERSESSION_PATH, SEALED_LEDGER_RELPATHS

REPO = Path(__file__).resolve().parents[1]
_SLOTS = 3650


def _identity() -> QualificationIdentity:
    def h(rel: str) -> str:
        return P.committed_artifact_sha256(REPO, rel)

    return QualificationIdentity(
        qualification_id=P.OQ_QUALIFICATION_ID,
        methodology_id=P.OQ_METHODOLOGY_ID,
        protocol_sha256=h(P.OQ_PROTOCOL_RELPATH),
        source_freeze_id="oq_e2",
        source_freeze_sha256=h(OQ_SOURCE_FREEZE_RELPATH),
        fixture_sha256=h(P.OQ_FIXTURE_MANIFEST_RELPATH),
        fault_schedule_sha256=h(P.OQ_FAULT_SCHEDULE_RELPATH),
        slo_contract_sha256=h(P.OQ_SLO_CONTRACT_RELPATH),
        cash_control_identity=h(P.OQ_CASH_CONTROL_IDENTITY_RELPATH),
        runtime_contract_sha256=h(CANONICAL_RUNTIME_CONTRACT_RELPATH),
        package_version=PACKAGE_VERSION,
    )


@pytest.fixture(scope="module")
def built() -> tuple[dict[str, Any], Path, Path]:
    """Publish + finalize one run; return (result dict, repo_root, registry_path)."""
    if sys.version_info[:2] != (3, 12):
        pytest.skip("the V2C OQ lifecycle requires CPython 3.12")
    ident = _identity()
    tmp = Path(tempfile.mkdtemp())
    for rel in SEALED_LEDGER_RELPATHS:
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_bytes(b"")
    reg = tmp / OQ_REGISTRY_PATH
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_bytes(b"")
    ctx = O.QualificationContext(
        repo_root=REPO,
        registry_path=reg,
        supersession_path=REPO / OQ_SUPERSESSION_PATH,
        identity=ident,
        source_freeze_id="oq_e2",
        source_freeze_commit="a" * 40,
        ci_terminal_success=True,
    )
    O.register_qualification(ctx, event_time_utc="2026-07-22T00:00:00Z", reason="OQ-R")
    token = O.start_qualification(ctx, event_time_utc="2026-07-22T00:00:01Z", reason="OQ-P")
    outcome = R.execute_qualification(token, workdir=tmp / "work", slots=_SLOTS)
    archive = A.build_oq_archive(outcome, identity=ident)
    C.write_completion_intent(
        tmp,
        C.build_completion_intent(
            archive,
            identity=ident,
            event_time_utc="2026-07-22T00:00:02Z",
            reason="done",
            prev_hash=token.started_entry_hash,
        ),
    )
    A.publish_oq_archive(tmp, archive)
    Fz.finalize(tmp, reg)
    result = json.loads(archive.result_bytes)
    return result, tmp, reg


# --------------------------------------------------------------------------- #
# Independence / drift                                                        #
# --------------------------------------------------------------------------- #
def test_oracle_copies_do_not_drift_from_source() -> None:
    from eth_research.v2c.oq import result as RES

    assert OR.OQ_ORACLE_CRITERIA == QUALIFICATION_CRITERIA
    # Exact equality, not <=: lowering the oracle floor below the source floor would silently open a
    # band of under-qualified runs the oracle would still accept.
    assert OR.OQ_ORACLE_MIN_ACCEPTED_EVENTS == OQ_MIN_ACCEPTED_EVENTS
    # The oracle's independent forbidden-vocab and field copies must not silently rot weaker than
    # the source: a term added to result.py without updating the oracle would blind the screen.
    assert OR._ORACLE_FORBIDDEN == RES.FORBIDDEN_PERFORMANCE_TERMS
    assert OR._ORACLE_ZERO_EXPOSURE_FIELDS == RES.ZERO_EXPOSURE_FIELDS
    assert OR._ORACLE_SUMMED_FIELDS == RES.SUMMED_COUNT_FIELDS


def test_oracle_shares_no_slo_or_result_import() -> None:
    import ast

    src = (REPO / "src/eth_research/v2c/oq/oracle.py").read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    # The oracle must re-derive everything itself, not lean on the runner's evaluation/result path.
    assert "eth_research.v2c.oq.slo" not in imported
    assert "eth_research.v2c.oq.result" not in imported
    assert "eth_research.v2c.oq.run" not in imported


# --------------------------------------------------------------------------- #
# Honest acceptance                                                           #
# --------------------------------------------------------------------------- #
def test_oracle_accepts_the_honest_qualified_result(
    built: tuple[dict[str, Any], Path, Path],
) -> None:
    result, _, _ = built
    verdict = OR.oq_oracle_verdict(result)
    assert verdict.accepted
    assert verdict.derived_verdict == OQ_VERDICT_QUALIFIED
    assert verdict.findings == ()


def test_independently_accept_archive_accepts_the_published_run(
    built: tuple[dict[str, Any], Path, Path],
) -> None:
    _, repo, reg = built
    verdict = OR.assert_independent_acceptance(repo, reg)
    assert verdict.accepted
    assert verdict.derived_verdict == OQ_VERDICT_QUALIFIED


# --------------------------------------------------------------------------- #
# Forgeries are always refused                                                #
# --------------------------------------------------------------------------- #
def test_forgery_nonzero_risky_fills_is_refused(built: tuple[dict[str, Any], Path, Path]) -> None:
    result, _, _ = built
    forged = copy.deepcopy(result)
    forged["operational_counts"]["risky_fill_count"] = 3
    assert not OR.oq_oracle_verdict(forged).accepted


def test_forgery_flipped_criterion_still_qualified_is_refused(
    built: tuple[dict[str, Any], Path, Path],
) -> None:
    result, _, _ = built
    forged = copy.deepcopy(result)
    forged["criteria"][4]["passed"] = False  # keep verdict "qualified"
    assert not OR.oq_oracle_verdict(forged).accepted


def test_forgery_injected_performance_term_is_refused(
    built: tuple[dict[str, Any], Path, Path],
) -> None:
    result, _, _ = built
    forged = copy.deepcopy(result)
    forged["statement"] = "we computed the sharpe ratio"
    assert not OR.oq_oracle_verdict(forged).accepted


def test_forgery_tampered_digest_is_refused(built: tuple[dict[str, Any], Path, Path]) -> None:
    result, _, _ = built
    forged = copy.deepcopy(result)
    forged["result_digest"] = "0" * 64
    assert not OR.oq_oracle_verdict(forged).accepted


def test_forgery_wrong_criteria_set_is_refused(built: tuple[dict[str, Any], Path, Path]) -> None:
    result, _, _ = built
    forged = copy.deepcopy(result)
    forged["criteria"] = forged["criteria"][:-1]  # drop a criterion
    assert not OR.oq_oracle_verdict(forged).accepted


def test_forgery_verdict_mismatch_is_refused(built: tuple[dict[str, Any], Path, Path]) -> None:
    result, _, _ = built
    forged = copy.deepcopy(result)
    forged["verdict"] = "not_qualified"  # everything passes, but claim failure
    verdict = OR.oq_oracle_verdict(forged)
    assert not verdict.accepted
    assert verdict.derived_verdict == OQ_VERDICT_QUALIFIED


def _reseal(body: dict[str, Any]) -> dict[str, Any]:
    from eth_research.v2.strict import canonical_sha256

    inner = {key: value for key, value in body.items() if key != "result_digest"}
    body["result_digest"] = canonical_sha256(inner)
    return body


def test_forgery_per_instrument_nonzero_hidden_by_zero_aggregate_is_refused(
    built: tuple[dict[str, Any], Path, Path],
) -> None:
    # A lied top-level aggregate (0) that hides nonzero per-instrument risky fills must be refused:
    # the oracle re-sums the per-instrument counts and requires the aggregate equals the sum.
    result, _, _ = built
    forged = copy.deepcopy(result)
    symbol = next(iter(forged["instruments"]))
    forged["instruments"][symbol]["risky_fill_count"] = 7
    forged["instruments"][symbol]["turnover"] = 12.5
    # operational_counts left at zero -- the aggregate now lies about the per-instrument evidence.
    _reseal(forged)
    assert not OR.oq_oracle_verdict(forged).accepted


def test_forgery_nonzero_approved_exposure_is_refused(
    built: tuple[dict[str, Any], Path, Path],
) -> None:
    # Nonzero approved risky exposure (aggregate == per-instrument sum, so the sum check passes)
    # must still be refused by the zero-exposure screen that now covers requested/approved exposure.
    result, _, _ = built
    forged = copy.deepcopy(result)
    symbol = next(iter(forged["instruments"]))
    forged["instruments"][symbol]["approved_risky_exposure"] = 5.0
    forged["operational_counts"]["approved_risky_exposure"] = 5.0
    _reseal(forged)
    assert not OR.oq_oracle_verdict(forged).accepted


def test_forgery_non_boolean_passed_flag_is_refused(
    built: tuple[dict[str, Any], Path, Path],
) -> None:
    # A criterion flag that is a truthy non-boolean ("false" the string, or 1) must be refused, not
    # coerced to a pass (fail-closed decode).
    result, _, _ = built
    forged = copy.deepcopy(result)
    forged["criteria"][0]["passed"] = "false"
    _reseal(forged)
    assert not OR.oq_oracle_verdict(forged).accepted
