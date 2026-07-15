"""Version-independent fresh-clone replay of the one M3C candidate run.

``check_replay`` accepts exactly four committed checkpoints, so the same CI is
green at each: **pristine**, **registered**, **failed**, and **completed**.

For the **completed** run the reproduced results are checked against the committed
results under four separated contracts (see ``docs/M3C_STATISTICAL_METHOD_NOTE.md``
§8 and :mod:`eth_research.m3c.numerics`):

* **Contract A — financial/structural raw replay.** From the committed raw Coinbase
  bytes alone the research-train partition is reconstructed offline, the 75-cell grid
  is re-run and reduced through the one shared pipeline, and **every** financial,
  accounting, cost, strategy, fold, timestamp, structural, provenance, registry, and
  identity field must reproduce **byte-for-byte**.
* **Contract B — bounded statistical replay.** Only a structurally-exact allowlist of
  secondary statistical scalars (the fold-seam-aware bootstrap interval, the per-fold
  paired daily log-excess, and the descriptive PSR) may differ, and only by a bounded
  number of representable binary64 steps (``MAX_REPLAY_ULPS``), with exact
  path/type/finite/sign/zero guards — because each is the output of a
  non-correctly-rounded transcendental (``numpy.log1p`` and/or ``math.erf``) whose last
  ULP is not identical across libm builds. This is **bounded ULP variation**, not
  "last-ULP identical". Any other difference fails closed.
* **Contract C — committed-artifact consistency.** :func:`verify_published_run`
  re-derives the decision and re-renders the report **byte-for-byte from the committed
  results** and re-checks the registry/manifest/bundle chain and the five bound inputs.
* **Contract D — reproduced-report rendering.** The report rendered from the
  *reproduced* results (not the committed ones) must equal the committed report
  byte-for-byte. The report prints statistics at ``.6g``, so a bounded-ULP drift cannot
  change a rendered byte; this is enforced on every supported runtime.

The reproduction must additionally re-derive the **identical mechanical promotion
verdict** (the full per-criterion pass/fail vector), so the tolerated drift is proven
decision-irrelevant, not merely small. Both sealed ledgers must be byte-empty in every
state. No networking; no sealed row is ever read.
"""

from __future__ import annotations

import argparse
import json
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
from eth_research.m3c.numerics import (
    MAX_REPLAY_ULPS,
    classify_reproduction_json,
    feeds_promotion_criterion,
    format_path,
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
    load_m3c_results,
    render_m3c_report,
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


class M3CReplayError(RuntimeError):
    """The M3C replay found the committed state inconsistent."""


def _criteria_vector(decision: CandidateDecision) -> tuple[tuple[str, bool], ...]:
    """The ordered (criterion id, pass/fail) vector — the mechanical verdict itself."""
    return tuple((criterion.criterion_id, criterion.passed) for criterion in decision.criteria)


def _format_hard(hard: list[tuple[tuple[Any, ...], Any, Any, str]]) -> str:
    lines: list[str] = []
    for path, committed_value, reproduced_value, reason in hard:
        lines.append(
            f"  {format_path(path)}: committed={committed_value!r} "
            f"reproduced={reproduced_value!r} [{reason}]"
        )
    return "\n".join(lines)


def _format_tolerated(tolerated: list[tuple[tuple[Any, ...], float, float, int]]) -> str:
    lines: list[str] = []
    for path, committed_value, reproduced_value, ulps in tolerated:
        criterion = feeds_promotion_criterion(path)
        lines.append(
            f"  {format_path(path)}: committed={committed_value!r} "
            f"reproduced={reproduced_value!r} abs={abs(committed_value - reproduced_value):.3e} "
            f"ulps={ulps} cap={MAX_REPLAY_ULPS} feeds_criterion={criterion or '-'}"
        )
    return "\n".join(lines)


def _first_line_diff(committed: bytes, reproduced: bytes) -> str:
    a = committed.decode("utf-8", "replace").splitlines()
    b = reproduced.decode("utf-8", "replace").splitlines()
    for i in range(max(len(a), len(b))):
        av = a[i] if i < len(a) else "<absent>"
        bv = b[i] if i < len(b) else "<absent>"
        if av != bv:
            return f"  first differing line {i + 1}:\n    committed: {av!r}\n    reproduced: {bv!r}"
    return "  (no line-level difference found; trailing bytes differ)"


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


def _emit_tolerated_drift(tolerated: list[tuple[tuple[Any, ...], float, float, int]]) -> None:
    """Record any tolerated bounded-ULP statistical variation in the audit trail."""
    if not tolerated:
        return
    max_ulps = max(ulps for *_, ulps in tolerated)
    body = (
        f"{len(tolerated)} secondary statistical leaf field(s) differ by bounded ULP "
        f"variation (max {max_ulps} <= cap {MAX_REPLAY_ULPS}); every financial, structural, "
        "decision, and report byte reproduced exactly and the mechanical verdict is "
        "identical:\n" + _format_tolerated(tolerated)
    )
    print("REPLAY NOTE (bounded ULP variation):\n" + body)
    _emit_ci_annotation("notice", "M3C bounded ULP variation", body)


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


def _check_completed_run(root: Path, registered: M3CRegistryEvent) -> None:
    """Contracts A-D for the one published run (raises on any violation)."""
    committed_results = load_m3c_results(root / M3C_RESULTS_RELPATH)
    reproduced = reproduce_results(root, registered)

    # Contracts A + B: everything exact except allowlisted statistical leaves within
    # the bounded-ULP cap.
    tolerated, hard = classify_reproduction_json(
        json.loads(committed_results.to_json_bytes()), json.loads(reproduced.to_json_bytes())
    )
    if hard:
        raise M3CReplayError(
            "reproduced results diverge from the committed results (a financial, structural, "
            "sign, zero-crossing, or over-cap statistical difference):\n" + _format_hard(hard)
        )

    # The bounded drift must not move the mechanical verdict: re-derive the decision from
    # the raw-data reproduction and require the identical criterion vector (no tolerance
    # on decision booleans or the status string).
    committed_decision = CandidateDecision.from_json_bytes(
        (root / M3C_DECISION_RELPATH).read_bytes()
    )
    reproduced_decision = evaluate_candidate_decision(
        reproduced, verification_passed=committed_decision.verification_passed
    )
    if _criteria_vector(reproduced_decision) != _criteria_vector(committed_decision):
        raise M3CReplayError(
            "cross-machine reproduction changes a mechanical promotion criterion; the "
            "bounded statistical variation is not decision-irrelevant"
        )
    if reproduced_decision.outcome != committed_decision.outcome:
        raise M3CReplayError("reproduced decision outcome disagrees with the committed decision")

    # Contract D: the report rendered from the REPRODUCED results equals the committed
    # report byte-for-byte (statistics print at .6g, coarser than the ULP drift).
    reproduced_report = render_m3c_report(reproduced, reproduced_decision).encode("utf-8")
    committed_report = (root / M3C_REPORT_RELPATH).read_bytes()
    if reproduced_report != committed_report:
        raise M3CReplayError(
            "the report rendered from the reproduced results is not byte-identical to the "
            "committed report:\n" + _first_line_diff(committed_report, reproduced_report)
        )

    _emit_tolerated_drift(tolerated)

    # Contract C: committed decision re-derives, committed report re-renders, and the
    # registry/manifest/bundle chain and five inputs all bind.
    verify_published_run(root)


def check_replay(repo_root: str | Path) -> tuple[str, ...]:
    """Quad-state replay check; returns ``(state, *checks)``. Raises on any drift."""
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
        _require_registration_binds_inputs(root, run_events[0])
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

    _check_completed_run(root, run_events[0])
    return (
        "completed",
        "ledgers_byte_empty",
        "results_reproduced_financial_exact",  # Contract A
        "results_reproduced_statistical_bounded_ulp",  # Contract B
        "verdict_reproduced_identical",
        "report_reproduced_from_reproduced_results",  # Contract D
        "archive_verified",  # Contract C
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quad-state replay of the M3C candidate run.")
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
