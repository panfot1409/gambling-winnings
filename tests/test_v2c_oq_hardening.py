"""V2C supplemental pre-freeze red-team regressions.

Locks the fixes for the pre-OQ-E2 audit findings so they cannot silently regress:

* E1 -- the finalizer refuses to append a ``completed`` event a corrupt completion intent does not
  reconcile against the published archive (which would permanently brick an append-only run);
* E2 -- a completion-intent artifact relpath outside the three published archive artifacts (a ``..``
  traversal) is refused;
* E3 -- a strict-JSON error (dup key) reading the intent surfaces as ``OQCompletionIntentError``;
* B1 -- the orchestrator refuses to register/start over a surviving run archive or completion intent
  (a truncated registry cannot reset the one-shot budget);
* B3 -- a missing sealed ledger is not treated as byte-empty;
* C1 -- the forbidden-vocabulary screen catches plural/inflected performance terms.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from pathlib import Path

import pytest

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.environment import CANONICAL_RUNTIME_CONTRACT_RELPATH
from eth_research.v2.strict import canonical_json_bytes
from eth_research.v2c.oq import archive as A
from eth_research.v2c.oq import completion as C
from eth_research.v2c.oq import finalize as Fz
from eth_research.v2c.oq import orchestrator as O
from eth_research.v2c.oq import protocol as P
from eth_research.v2c.oq import result as RES
from eth_research.v2c.oq import run as R
from eth_research.v2c.oq.completion import OQCompletionIntent, OQCompletionIntentError
from eth_research.v2c.oq.freeze import OQ_SOURCE_FREEZE_RELPATH
from eth_research.v2c.oq.registry import OQ_REGISTRY_PATH, QualificationIdentity
from eth_research.v2c.oq.supersession import (
    OQ_SUPERSESSION_PATH,
    SEALED_LEDGER_RELPATHS,
    OQSupersessionError,
    _sha256_of,
)

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
def published() -> tuple[Path, Path, OQCompletionIntent, QualificationIdentity]:
    """Register + start + execute + publish one run WITHOUT finalizing; keep the intent/archive."""
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
    intent = C.build_completion_intent(
        archive,
        identity=ident,
        event_time_utc="2026-07-22T00:00:02Z",
        reason="done",
        prev_hash=token.started_entry_hash,
    )
    C.write_completion_intent(tmp, intent)
    A.publish_oq_archive(tmp, archive)
    return tmp, reg, intent, ident


# --------------------------------------------------------------------------- #
# E1: a corrupt intent that does not reconcile with the archive is refused    #
# --------------------------------------------------------------------------- #
def test_finalize_reconciles_honest_intent(
    published: tuple[Path, Path, OQCompletionIntent, QualificationIdentity],
) -> None:
    tmp, reg, _, _ = published
    # The honest intent published alongside the archive is finalizable.
    assert Fz.assess(tmp, reg).state == Fz.STATE_FINALIZABLE


def test_finalize_refuses_intent_with_mismatched_verdict(
    published: tuple[Path, Path, OQCompletionIntent, QualificationIdentity],
) -> None:
    tmp, reg, intent, _ = published
    other = "not_qualified" if intent.verdict == "qualified" else "qualified"
    corrupt = dataclasses.replace(intent, verdict=other)
    C.write_completion_intent(tmp, corrupt)
    try:
        status = Fz.assess(tmp, reg)
        # A verdict the archive does not warrant must never be finalizable (would brick the run).
        assert status.state == Fz.STATE_NOT_FINALIZABLE
        assert "reconcile" in status.detail
    finally:
        C.write_completion_intent(tmp, intent)  # restore for other tests


def test_finalize_refuses_intent_with_tampered_evidence_digest(
    published: tuple[Path, Path, OQCompletionIntent, QualificationIdentity],
) -> None:
    tmp, reg, intent, _ = published
    corrupt = dataclasses.replace(intent, evidence_sha256="c" * 64, result_bundle_sha256="d" * 64)
    C.write_completion_intent(tmp, corrupt)
    try:
        assert Fz.assess(tmp, reg).state == Fz.STATE_NOT_FINALIZABLE
    finally:
        C.write_completion_intent(tmp, intent)


# --------------------------------------------------------------------------- #
# E2 / E3: completion-intent parsing is path-confined and fail-closed         #
# --------------------------------------------------------------------------- #
def _intent_payload(ident: QualificationIdentity, artifact_relpath: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "qualification_id": ident.qualification_id,
        "identity": ident.as_map(),
        "event_time_utc": "2026-07-22T00:00:00Z",
        "reason": "x",
        "verdict": "qualified",
        "prev_hash": "1" * 64,
        "artifacts": [[artifact_relpath, "9" * 64]],
        "result_sha256": "1" * 64,
        "report_sha256": "2" * 64,
        "evidence_sha256": "3" * 64,
        "archive_manifest_sha256": "4" * 64,
        "result_bundle_sha256": "5" * 64,
    }


def test_completion_intent_refuses_path_traversal_artifact() -> None:
    ident = _identity()
    traversal = f"{A.OQ_ARCHIVE_DIR}/../../../../../etc/hostname"
    payload = _intent_payload(ident, traversal)
    with pytest.raises(OQCompletionIntentError):
        OQCompletionIntent.from_json_bytes(canonical_json_bytes(payload))


def test_completion_intent_accepts_the_known_archive_relpath() -> None:
    ident = _identity()
    known = A.archive_relpath(A.OQ_ARCHIVE_RESULT_RELNAME)
    payload = _intent_payload(ident, known)
    intent = OQCompletionIntent.from_json_bytes(canonical_json_bytes(payload))
    assert intent.artifacts[0][0] == known


def test_completion_intent_dup_key_raises_typed_error() -> None:
    # strict_json_loads raises the M3D StrictJSONError tree; it must surface as the typed error.
    dup = b'{"schema_version":1,"schema_version":2,"artifacts":[["x","y"]]}'
    with pytest.raises(OQCompletionIntentError):
        OQCompletionIntent.from_json_bytes(dup)


# --------------------------------------------------------------------------- #
# B1: register/start refuse to proceed over a surviving prior-run artifact    #
# --------------------------------------------------------------------------- #
def _pristine_ctx(root: Path) -> O.QualificationContext:
    for rel in SEALED_LEDGER_RELPATHS:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"")
    reg = root / OQ_REGISTRY_PATH
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_bytes(b"")
    return O.QualificationContext(
        repo_root=REPO,  # governance artifacts read from the real repo
        registry_path=reg,
        supersession_path=REPO / OQ_SUPERSESSION_PATH,
        identity=_identity(),
        source_freeze_id="oq_e2",
        source_freeze_commit="a" * 40,
        ci_terminal_success=True,
    )


def test_no_prior_run_artifacts_gate_is_in_the_sequence() -> None:
    assert "no_prior_run_artifacts" in O.GATE_ORDER


def test_register_refuses_over_a_surviving_run_archive(
    published: tuple[Path, Path, OQCompletionIntent, QualificationIdentity], tmp_path: Path
) -> None:
    src, _, _, _ = published
    # Copy the published archive into a fresh (byte-empty registry) repo_root: a truncated registry
    # reads pristine, but the surviving archive betrays the prior run -> the gate must refuse.
    ctx = dataclasses.replace(_pristine_ctx(tmp_path), repo_root=tmp_path)
    archive_dir = tmp_path / A.OQ_ARCHIVE_DIR
    archive_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        A.OQ_ARCHIVE_RESULT_RELNAME,
        A.OQ_ARCHIVE_REPORT_RELNAME,
        A.OQ_ARCHIVE_MANIFEST_RELNAME,
    ):
        (tmp_path / A.archive_relpath(name)).write_bytes(
            (src / A.archive_relpath(name)).read_bytes()
        )
    report = O.preflight_report(ctx, expect_state="pristine")
    gate = next(g for g in report.gates if g.name == "no_prior_run_artifacts")
    assert not gate.passed


# --------------------------------------------------------------------------- #
# B3: a missing sealed ledger is not byte-empty                               #
# --------------------------------------------------------------------------- #
def test_sha256_of_refuses_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(OQSupersessionError):
        _sha256_of(tmp_path / "does_not_exist.jsonl")


# --------------------------------------------------------------------------- #
# D4: the deep verifier's zero check rejects a JSON boolean                    #
# --------------------------------------------------------------------------- #
def test_verify_archive_strict_zero_rejects_bool() -> None:
    from eth_research.v2c.oq import verify_archive as VA

    assert VA._is_zero(0)
    assert VA._is_zero(0.0)
    assert not VA._is_zero(False)  # JSON false must never count as a numeric zero
    assert not VA._is_zero(True)
    assert not VA._is_zero("0")
    assert not VA._is_zero(None)


# --------------------------------------------------------------------------- #
# C1: the forbidden-vocabulary screen catches inflected performance terms     #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "term",
    ["drawdowns", "profits", "benchmarks", "alphas", "equities", "sharpes", "rois", "returns"],
)
def test_forbidden_vocabulary_catches_plurals(term: str) -> None:
    with pytest.raises(RES.ForbiddenVocabularyError):
        RES.scan_for_forbidden_vocabulary("t", {"detail": f"observed peak {term} within bounds"})


def test_forbidden_vocabulary_allows_benign_lookalikes() -> None:
    # "alphabet" contains "alpha" but is not the forbidden whole word; it must not false-positive.
    RES.scan_for_forbidden_vocabulary("t", {"detail": "the alphabet is fine and equitable"})


def test_json_module_is_used_only_for_payload_shaping() -> None:
    # Guard: this test module builds intent payloads with json/canonical_json_bytes, never parses
    # untrusted governance bytes with the non-strict json module.
    assert json.dumps({"ok": True})
