"""Version-independent fresh-clone replay of the one M3C candidate run.

``check_replay`` accepts exactly four committed checkpoints, so the same CI is
green at each:

* **pristine** — the registry carries no run-001 event and none of the four
  immutable artifacts exist. The only guarantees are the two byte-empty sealed
  ledgers and the absent outputs.
* **registered** — the registry carries exactly ``registered`` (the committed
  pre-registration) and no artifacts exist yet. Every one of the five recorded
  inputs — protocol, lineage, budget, development partition, and frozen dossier —
  must equal the committed file, so a registration cannot bind a stale or tampered
  input while staying green.
* **completed** — the registry carries ``registered`` → ``started`` →
  ``completed``. From the committed raw Coinbase bytes alone the research-train
  partition is reconstructed offline, the 75-cell grid is re-run and reduced
  through the one shared pipeline, and the reproduced results are compared to the
  committed results **field by field**: every financial, structural, provenance,
  and cost field must match **byte-for-byte**, while a small, named set of
  secondary *statistical* scalars — the fold-seam-aware bootstrap interval, the
  per-fold paired daily log-excess, and the descriptive PSR — is required to agree
  only to a tight relative tolerance, because each is the output of a
  non-correctly-rounded transcendental library function (``np.log1p``, integer
  powers, ``math.erf``) that legitimately differs in its last unit-in-the-last-place
  across libm builds and CPU microarchitectures (IEEE-754 mandates correct rounding
  for ``+ - * /`` and ``sqrt`` only). The reproduction must additionally yield the
  **identical
  mechanical promotion verdict**, so the tolerated drift is proven decision-
  irrelevant, not merely small. Then :func:`verify_published_run` re-derives the
  decision and re-renders the report **byte-for-byte from the committed results** and
  re-checks the whole registry/manifest/bundle chain and the five bound inputs. Any
  other divergence fails closed. See ``docs/M3C_STATISTICAL_METHOD_NOTE.md`` §8.
* **failed** — the registry carries ``registered`` → ``started`` → ``failed``: the
  single-use id was honestly consumed by a run that did not complete, with no
  artifacts published. This is a real committed state (not a mid-lifecycle
  inconsistency), so an honest failure does not brick CI.

Both sealed ledgers must be byte-empty in every state. No networking; no sealed row
is ever read (the loader returns research-train rows only).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

from eth_research.data.provenance import sha256_file
from eth_research.development import DEVELOPMENT_PARTITION_RELPATH, FROZEN_M2_DOSSIER_RELPATH
from eth_research.m3c.archive import M3C_MANIFEST_RELPATH, verify_published_run
from eth_research.m3c.decision import (
    M3C_DECISION_RELPATH,
    CandidateDecision,
    evaluate_candidate_decision,
)
from eth_research.m3c.pipeline import reproduce_results
from eth_research.m3c.registry import (
    EVENT_COMPLETED,
    EVENT_FAILED,
    EVENT_REGISTERED,
    EVENT_STARTED,
    M3C_REGISTRY_RELPATH,
    M3CRegistryEvent,
    read_registry,
)
from eth_research.m3c.results import (
    M3C_EXPERIMENT_ID,
    M3C_LINEAGE_RELPATH,
    M3C_PROTOCOL_RELPATH,
    M3C_REPORT_RELPATH,
    M3C_RESULTS_RELPATH,
    M3CResults,
    load_m3c_results,
)

_GATE_LEDGER_RELPATH: str = "research/m3a/development_gate_access.jsonl"
_HOLDOUT_LEDGER_RELPATH: str = "research/m2b/test_evaluations.jsonl"
_BUDGET_RELPATH: str = "research/m3c/research_budget.json"
_EMPTY_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_ARTIFACTS: tuple[str, ...] = (
    M3C_RESULTS_RELPATH,
    M3C_DECISION_RELPATH,
    M3C_REPORT_RELPATH,
    M3C_MANIFEST_RELPATH,
)

# ------------------------------------------------------------ reproduction tolerance
#
# IEEE-754 mandates correctly-rounded ``+ - * /`` and ``sqrt`` but NOT the
# transcendental library functions. Different libm builds / CPU microarchitectures
# therefore legitimately return last-unit-in-the-last-place-different values for
# ``log1p``, integer powers, and ``erf`` (the "table-maker's dilemma"). Every M3C
# financial number is produced by the M3B engine and reproduces byte-for-byte on CI
# (the green ``m3b-replay`` proves the shared engine is cross-machine stable), so the
# ONLY result leaves that can differ across the execution host and a fresh-clone
# verifier are the M3C-new statistical scalars listed below. They are permitted a
# tight relative tolerance ~6 orders of magnitude tighter than the P1 decision
# threshold (whose magnitude is ~2.3e-3); every other field must be exact, and the
# reproduction must still yield the identical mechanical verdict. See
# ``docs/M3C_STATISTICAL_METHOD_NOTE.md`` §8 and ``docs/M3C_BUG_LOG.md``.
_REPRO_REL_TOL: float = 1e-9
_REPRO_ABS_TOL: float = 1e-12

_TRANSCENDENTAL_LEAVES: frozenset[tuple[Any, ...]] = frozenset(
    {
        ("bootstrap", "point_estimate"),  # mean of np.log1p paired excess
        ("bootstrap", "ci_lower"),  # percentile of np.log1p-derived resample means
        ("bootstrap", "ci_upper"),
        ("psr_diagnostic", "observed_sharpe"),  # of the log1p paired-excess series
        ("psr_diagnostic", "skewness"),  # standardized integer-power moment
        ("psr_diagnostic", "kurtosis"),
        ("psr_diagnostic", "psr"),  # 0.5*(1+math.erf(...))
    }
)


class M3CReplayError(RuntimeError):
    """The M3C replay found the committed state inconsistent."""


def _is_transcendental_leaf(path: tuple[Any, ...]) -> bool:
    """True iff ``path`` names a secondary statistical scalar that may drift by ULPs."""
    if path in _TRANSCENDENTAL_LEAVES:
        return True
    # paired_comparisons[i].mean_daily_paired_log_excess (np.log1p) for any fold i.
    return (
        len(path) == 3
        and path[0] == "paired_comparisons"
        and path[2] == "mean_daily_paired_log_excess"
    )


def _walk_json_diffs(
    committed: Any, reproduced: Any, path: tuple[Any, ...] = ()
) -> list[tuple[tuple[Any, ...], Any, Any]]:
    """Every leaf path at which two canonical-JSON structures differ."""
    if isinstance(committed, dict) and isinstance(reproduced, dict):
        diffs: list[tuple[tuple[Any, ...], Any, Any]] = []
        for key in sorted(set(committed) | set(reproduced), key=str):
            here = (*path, key)
            if key not in committed or key not in reproduced:
                diffs.append(
                    (here, committed.get(key, "<absent>"), reproduced.get(key, "<absent>"))
                )
            else:
                diffs.extend(_walk_json_diffs(committed[key], reproduced[key], here))
        return diffs
    if isinstance(committed, list) and isinstance(reproduced, list):
        if len(committed) != len(reproduced):
            return [(path, f"<len {len(committed)}>", f"<len {len(reproduced)}>")]
        diffs = []
        for i, (a, b) in enumerate(zip(committed, reproduced, strict=True)):
            diffs.extend(_walk_json_diffs(a, b, (*path, i)))
        return diffs
    return [] if committed == reproduced else [(path, committed, reproduced)]


def _classify_json_reproduction(
    committed_json: Any, reproduced_json: Any
) -> tuple[list[tuple[tuple[Any, ...], Any, Any]], list[tuple[tuple[Any, ...], Any, Any]]]:
    """Partition committed-vs-reproduced leaf differences into ``(tolerated, hard)``.

    A difference is *tolerated* only when it is a named transcendental statistical
    leaf whose two float values agree to the tight relative tolerance (cross-machine
    last-ULP noise). Every other difference — any financial, structural, provenance,
    decision-relevant, non-float, or out-of-tolerance value — is *hard* and fails
    closed. Booleans and integers are never floats here, so they are always hard.
    """
    tolerated: list[tuple[tuple[Any, ...], Any, Any]] = []
    hard: list[tuple[tuple[Any, ...], Any, Any]] = []
    for path, committed_value, reproduced_value in _walk_json_diffs(
        committed_json, reproduced_json
    ):
        if (
            _is_transcendental_leaf(path)
            and type(committed_value) is float
            and type(reproduced_value) is float
            and math.isclose(
                committed_value,
                reproduced_value,
                rel_tol=_REPRO_REL_TOL,
                abs_tol=_REPRO_ABS_TOL,
            )
        ):
            tolerated.append((path, committed_value, reproduced_value))
        else:
            hard.append((path, committed_value, reproduced_value))
    return tolerated, hard


def _classify_reproduction(
    committed: M3CResults, reproduced: M3CResults
) -> tuple[list[tuple[tuple[Any, ...], Any, Any]], list[tuple[tuple[Any, ...], Any, Any]]]:
    """Classify a reproduced :class:`M3CResults` against the committed one."""
    return _classify_json_reproduction(
        json.loads(committed.to_json_bytes()), json.loads(reproduced.to_json_bytes())
    )


def _rel_delta(a: float, b: float) -> float:
    scale = max(abs(a), abs(b))
    return abs(a - b) / scale if scale else 0.0


def _format_diffs(diffs: list[tuple[tuple[Any, ...], Any, Any]]) -> str:
    lines: list[str] = []
    for path, committed_value, reproduced_value in diffs:
        location = ".".join(str(part) for part in path)
        if type(committed_value) is float and type(reproduced_value) is float:
            lines.append(
                f"  {location}: committed={committed_value!r} reproduced={reproduced_value!r} "
                f"abs={abs(committed_value - reproduced_value):.3e} "
                f"rel={_rel_delta(committed_value, reproduced_value):.3e}"
            )
        else:
            lines.append(
                f"  {location}: committed={committed_value!r} reproduced={reproduced_value!r}"
            )
    return "\n".join(lines)


def _criteria_vector(decision: CandidateDecision) -> tuple[tuple[str, bool], ...]:
    """The ordered (criterion id, pass/fail) vector — the mechanical verdict itself."""
    return tuple((criterion.criterion_id, criterion.passed) for criterion in decision.criteria)


def _emit_ci_annotation(level: str, title: str, message: str) -> None:
    """Emit a GitHub Actions annotation (retrievable via the check-runs REST API).

    Job-log blobs can be network-restricted for auditors, but ``::error::`` /
    ``::notice::`` workflow commands surface as check-run annotations the REST API
    returns, so the exact reproduction diff is always retrievable.
    """
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    encoded = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::{level} title={title}::{encoded}")


def _emit_tolerated_drift(tolerated: list[tuple[tuple[Any, ...], Any, Any]]) -> None:
    """Record any tolerated cross-machine transcendental drift in the audit trail."""
    if not tolerated:
        return
    body = (
        f"{len(tolerated)} secondary statistical leaf field(s) differ only in cross-machine "
        f"transcendental last-ULP noise (<= rel {_REPRO_REL_TOL:g}, abs {_REPRO_ABS_TOL:g}); "
        "every financial, structural, decision, and report byte reproduced exactly and the "
        "mechanical verdict is identical:\n" + _format_diffs(tolerated)
    )
    print("REPLAY NOTE (tolerated transcendental drift):\n" + body)
    _emit_ci_annotation("notice", "M3C tolerated transcendental drift", body)


def _require_ledgers_byte_empty(root: Path) -> None:
    for relpath in (_GATE_LEDGER_RELPATH, _HOLDOUT_LEDGER_RELPATH):
        path = root / relpath
        if not path.exists() or sha256_file(path) != _EMPTY_SHA256:
            raise M3CReplayError(f"sealed ledger {relpath} is not byte-empty")


def _require_registration_binds_inputs(root: Path, registered: M3CRegistryEvent) -> None:
    """Every committed input file must match the digest the run registered.

    Binds all five recorded inputs — protocol, lineage, budget, development
    partition, and frozen dossier — so a registered (or failed) checkpoint cannot
    silently carry a tampered or stale input while CI stays green.
    """
    for label, relpath, recorded in (
        ("protocol", M3C_PROTOCOL_RELPATH, registered.protocol_sha256),
        ("lineage", M3C_LINEAGE_RELPATH, registered.lineage_sha256),
        ("budget", _BUDGET_RELPATH, registered.research_budget_sha256),
        (
            "development partition",
            DEVELOPMENT_PARTITION_RELPATH,
            registered.development_partition_sha256,
        ),
        ("frozen dossier", FROZEN_M2_DOSSIER_RELPATH, registered.frozen_m2_dossier_sha256),
    ):
        if sha256_file(root / relpath) != recorded:
            raise M3CReplayError(
                f"registered {label} digest disagrees with the committed {relpath}"
            )


def check_replay(repo_root: str | Path) -> tuple[str, ...]:
    """Tri-state replay check; returns ``(state, *checks)``. Raises on any drift."""
    root = Path(repo_root)
    _require_ledgers_byte_empty(root)

    run_events = [
        e
        for e in read_registry(root / M3C_REGISTRY_RELPATH)
        if e.experiment_id == M3C_EXPERIMENT_ID
    ]
    lifecycle = [e.event for e in run_events]
    artifacts_present = [rel for rel in _ARTIFACTS if (root / rel).exists()]

    if not run_events:
        if artifacts_present:
            raise M3CReplayError(
                f"registry has no run-001 event but artifacts exist: {artifacts_present}"
            )
        return ("pristine", "ledgers_byte_empty", "no_run_no_artifacts")

    if lifecycle == [EVENT_REGISTERED]:
        if artifacts_present:
            raise M3CReplayError(
                f"run-001 is only registered but artifacts exist: {artifacts_present}"
            )
        registered = run_events[0]
        _require_registration_binds_inputs(root, registered)
        return (
            "registered",
            "ledgers_byte_empty",
            "preregistered_no_artifacts",
            "registration_binds_committed_inputs",
        )

    if lifecycle == [EVENT_REGISTERED, EVENT_STARTED, EVENT_FAILED]:
        # A legitimately recorded one-shot failure: the single-use id is spent and no
        # artifacts were published. This is a real committed checkpoint (CI must stay
        # green), not a mid-lifecycle inconsistency — the run honestly did not complete.
        if artifacts_present:
            raise M3CReplayError(
                f"failed run must not have published artifacts: {artifacts_present}"
            )
        _require_registration_binds_inputs(root, run_events[0])
        return ("failed", "ledgers_byte_empty", "run_failed_no_artifacts")

    if lifecycle != [EVENT_REGISTERED, EVENT_STARTED, EVENT_COMPLETED]:
        raise M3CReplayError(f"run-001 is mid-lifecycle {lifecycle!r}; not a committed state")
    missing = [rel for rel in _ARTIFACTS if rel not in artifacts_present]
    if missing:
        raise M3CReplayError(f"completed run is missing published artifacts: {missing}")

    registered = run_events[0]
    committed_results = load_m3c_results(root / M3C_RESULTS_RELPATH)
    reproduced = reproduce_results(root, registered)
    tolerated, hard = _classify_reproduction(committed_results, reproduced)
    if hard:
        raise M3CReplayError(
            "reproduced results diverge from the committed results beyond cross-machine "
            "transcendental last-ULP tolerance (a financial, structural, or out-of-tolerance "
            "statistical difference):\n" + _format_diffs(hard)
        )
    # The tolerated drift must not be able to move the mechanical verdict: re-derive the
    # decision from the raw-data reproduction and require an identical criterion vector.
    # This proves the drift is decision-irrelevant, not merely small.
    committed_decision = CandidateDecision.from_json_bytes(
        (root / M3C_DECISION_RELPATH).read_bytes()
    )
    reproduced_decision = evaluate_candidate_decision(
        reproduced, verification_passed=committed_decision.verification_passed
    )
    if _criteria_vector(reproduced_decision) != _criteria_vector(committed_decision):
        raise M3CReplayError(
            "cross-machine reproduction changes a mechanical promotion criterion; the "
            "tolerated statistical drift is not decision-irrelevant"
        )
    _emit_tolerated_drift(tolerated)
    # The committed decision and report re-derive byte-for-byte from the committed
    # results, and the whole registry/manifest/bundle chain binds.
    verify_published_run(root)
    return (
        "completed",
        "ledgers_byte_empty",
        "results_reproduced",
        "decision_reproduced",
        "report_reproduced",
        "archive_verified",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tri-state replay of the M3C candidate run.")
    parser.add_argument("--repo-root", default=".", help="repository root (default: .)")
    parser.add_argument("--check", action="store_true", help="verify committed state (default)")
    args = parser.parse_args(argv)
    try:
        state, *checks = check_replay(args.repo_root)
    except Exception as exc:  # CLI boundary: any failure is a non-zero exit
        message = f"{type(exc).__name__}: {exc}"
        print(f"REPLAY FAILED: {message}", file=sys.stderr)
        _emit_ci_annotation("error", "M3C replay failed", message)
        return 1
    print(f"replay OK [{state}]: {', '.join(checks)}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
