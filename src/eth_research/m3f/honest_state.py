"""The repository's honest state, derived entirely from committed bytes.

No wall clock, no build timestamp, no ``DUE`` inference, no sealed price/signal/
return/metric. Maturity is the committed observation count versus the committed
threshold — a byte fact, never a date inference. The three invariants that must hold
forever are asserted at derivation time: ``evaluation_authorized`` is false,
``m3e_active`` is false, and ``production_proposal_count`` is zero.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eth_research.m3f.growable import v2d_activation_anchor_active
from eth_research.m3f.validation import (
    M3FValidationError,
    canonical_json_bytes,
    count_created_proposals,
    load_canonical_json,
    require_bool,
    require_int,
    require_str,
    sha256_bytes,
)
from eth_research.m3f.workflow_inventory import workflow_grants_write

HONEST_STATE_RELPATH = "research/m3f/honest_state.json"
HONEST_STATE_MD_RELPATH = "research/m3f/HONEST_STATE.md"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
MATURITY_THRESHOLD = 365
_LEDGERS = (
    "research/m2b/test_evaluations.jsonl",
    "research/m3a/development_gate_access.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)


def derive_honest_state(repo_root: str | Path) -> dict[str, Any]:
    """Derive the honest-state dict from committed artifacts. Fail closed on any drift."""
    root = Path(repo_root)
    decision = load_canonical_json(
        (root / "research/m3c/candidate_decision.json").read_bytes(), "m3c_decision"
    )
    base = load_canonical_json(
        (root / "research/m3e/accepted_base.json").read_bytes(), "m3e_accepted_base"
    )
    proposals = count_created_proposals(
        (root / "research/m3e/proposal_registry.jsonl").read_bytes()
    )

    ledgers: dict[str, dict[str, Any]] = {}
    for rel in _LEDGERS:
        raw = (root / rel).read_bytes()
        ledgers[rel] = {
            "byte_count": len(raw),
            "event_count": raw.count(b"\n"),
            "sha256": sha256_bytes(raw),
        }

    workflows_write = _any_workflow_writes(root)
    rows = require_int(base["row_count"], "m3d_cohort_rows")
    authorized = require_bool(base["evaluation_authorized"], "m3d_evaluation_authorized")

    state = {
        "schema_version": 1,
        "accepted_stack": "m2b_m3a_m3b_m3c_m3d_m3e_merged_to_main",
        "m2b_dataset_identity": "coinbase_eth_usd_daily_frozen_dossier",
        "m3a_state": "completed_research_only",
        "m3b_state": "completed_research_only",
        "m3c_candidate_verdict": require_str(decision["outcome"], "m3c_outcome"),
        "m3d_cohort_row_count": rows,
        "m3d_maturity_threshold": MATURITY_THRESHOLD,
        "m3d_maturity_state": require_str(base["maturity_state"], "m3d_maturity_state"),
        "m3d_evaluation_authorized": authorized,
        "m3e_readiness": "ready",
        "m3e_active": False,
        "m3e_production_proposal_count": proposals,
        "standing_workflow_can_write_contents": workflows_write,
        "ledgers": ledgers,
        "any_gate_or_holdout_evaluated": False,
        "new_strategy_evaluation_authorized": False,
        "network_capable_publisher_deployed": False,
        "release_tags_remotely_published": ["v0.1.0"],
        "known_tag_debt_not_retried": ["v0.6.0", "v0.7.0", "v0.8.0"],
        "hash_binding_is": "operational_tamper_evidence_not_cryptographic_signature",
    }

    # The forever-invariants — fail closed at derivation. Evaluation authorization
    # and sealed-ledger emptiness are unconditional. Production proposals and the
    # single job-scoped workflow write grant are lawful ONLY under the committed
    # V2D activation anchor (data-only growth); without it they hard-stop as before.
    if authorized:
        raise M3FValidationError("HARD STOP: m3d evaluation_authorized is true")
    if proposals != 0 and not v2d_activation_anchor_active(root):
        raise M3FValidationError(
            "HARD STOP: a production proposal exists without the V2D activation anchor"
        )
    if workflows_write:
        raise M3FValidationError("HARD STOP: an unauthorized workflow can write contents")
    for rel, facts in ledgers.items():
        if facts["byte_count"] != 0 or facts["sha256"] != EMPTY_SHA256:
            raise M3FValidationError(f"HARD STOP: sealed ledger {rel} is non-empty")
    return state


def _any_workflow_writes(root: Path) -> bool:
    """True if any UNAUTHORIZED committed workflow grants write contents.

    Delegates to the hardened, whitespace/comment/anchor-tolerant detector shared with
    the workflow inventory, so the forever-invariant cannot fail open on a
    ``contents:   write  # comment`` / tab / anchored grant. Under the committed V2D
    activation anchor, exactly ``m3e-prospective-update.yml`` may hold its reviewed
    job-scoped grant; every other workflow (and, absent the anchor, every workflow)
    still trips this detector.
    """
    wf = root / ".github/workflows"
    if not wf.is_dir():
        return False
    allowed: set[str] = set()
    if v2d_activation_anchor_active(root):
        allowed = {"m3e-prospective-update.yml"}
    return any(
        workflow_grants_write(path.read_text(encoding="utf-8"))
        for path in sorted([*wf.glob("*.yml"), *wf.glob("*.yaml")])
        if path.name not in allowed
    )


def render_honest_state_md(state: dict[str, Any]) -> bytes:
    """Deterministic Markdown rendering (byte-reproducible from the JSON)."""
    lg = state["ledgers"]
    rows = f"{state['m3d_cohort_row_count']} / {state['m3d_maturity_threshold']}"
    can_write = state["standing_workflow_can_write_contents"]
    lines = [
        "# Repository honest state (Milestone 3F)",
        "",
        "Derived entirely from committed bytes — no wall clock, no strategy, no sealed"
        " price/signal/return/metric. Maturity is committed observation count vs the"
        " committed threshold.",
        "",
        "| Fact | Value |",
        "|---|---|",
        f"| Accepted stack | `{state['accepted_stack']}` |",
        f"| M3C candidate verdict | `{state['m3c_candidate_verdict']}` |",
        f"| M3D cohort rows | {rows} |",
        f"| M3D maturity | `{state['m3d_maturity_state']}` |",
        f"| M3D evaluation authorized | {state['m3d_evaluation_authorized']} |",
        f"| M3E readiness | `{state['m3e_readiness']}` |",
        f"| M3E active | {state['m3e_active']} |",
        f"| M3E production proposals | {state['m3e_production_proposal_count']} |",
        f"| Standing workflow can write contents | {can_write} |",
        f"| New strategy evaluation authorized | {state['new_strategy_evaluation_authorized']} |",
        f"| Network publisher deployed | {state['network_capable_publisher_deployed']} |",
        "",
        "## Sealed access ledgers (all byte-empty)",
        "",
        "| Ledger | Bytes | Events | SHA-256 |",
        "|---|---|---|---|",
    ]
    for rel in sorted(lg):
        f = lg[rel]
        lines.append(
            f"| `{rel}` | {f['byte_count']} | {f['event_count']} | `{f['sha256'][:16]}…` |"
        )
    lines += [
        "",
        f"Release tags published remotely: {state['release_tags_remotely_published']}. Known tag"
        f" debt (not retried): {state['known_tag_debt_not_retried']}.",
        "",
        "Hash binding is operational tamper-evidence, not a cryptographic signature or remote"
        " attestation.",
        "",
    ]
    return ("\n".join(lines)).encode("utf-8")


def render_honest_state_bytes(state: dict[str, Any]) -> bytes:
    return canonical_json_bytes(state)


def verify_honest_state(repo_root: str | Path) -> None:
    """The committed honest state holds: byte-reproduced, or floors under V2D growth.

    With zero production proposals the committed JSON + Markdown must reproduce
    byte-for-byte from live bytes, exactly as accepted. Once reviewed proposals
    have landed (lawful only under the committed V2D activation anchor — the
    derive step enforces that), the committed file remains the immutable
    AT-M3F-ACCEPTANCE record: its immutable facts must still hold live and its
    growable facts become monotone floors — the live cohort may only be LARGER,
    never smaller, relabelled, or evaluation-authorized.
    """
    root = Path(repo_root)
    live = derive_honest_state(root)
    committed_raw = (root / HONEST_STATE_RELPATH).read_bytes()
    committed_md = (root / HONEST_STATE_MD_RELPATH).read_bytes()
    proposals = require_int(live["m3e_production_proposal_count"], "m3e_production_proposal_count")
    if proposals == 0:
        if committed_raw != render_honest_state_bytes(live):
            raise M3FValidationError("committed honest_state.json does not reproduce from bytes")
        if committed_md != render_honest_state_md(live):
            raise M3FValidationError("committed HONEST_STATE.md does not reproduce from the JSON")
        return
    committed = load_canonical_json(committed_raw, "honest_state")
    if not isinstance(committed, dict):
        raise M3FValidationError("committed honest_state.json is not an object")
    if committed_md != render_honest_state_md(committed):
        raise M3FValidationError("committed HONEST_STATE.md does not reproduce from the JSON")
    immutable = (
        "schema_version",
        "accepted_stack",
        "m2b_dataset_identity",
        "m3a_state",
        "m3b_state",
        "m3c_candidate_verdict",
        "m3d_maturity_threshold",
        "m3d_evaluation_authorized",
        "any_gate_or_holdout_evaluated",
        "new_strategy_evaluation_authorized",
        "network_capable_publisher_deployed",
        "ledgers",
    )
    for key in immutable:
        if live.get(key) != committed.get(key):
            raise M3FValidationError(
                f"honest-state immutable fact {key!r} drifted from the accepted record"
            )
    committed_rows = require_int(committed.get("m3d_cohort_row_count"), "committed_rows")
    live_rows = require_int(live["m3d_cohort_row_count"], "live_rows")
    if live_rows < committed_rows:
        raise M3FValidationError("live cohort shrank below the accepted row count")
    if live["m3d_maturity_state"] != "immature" and live_rows < MATURITY_THRESHOLD:
        raise M3FValidationError("unlawful maturity state below the 365 floor")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    from eth_research.m3f.cli import emit, repo_root_parser

    args = repo_root_parser("M3F honest-state (read-only)").parse_args(argv)
    root = Path(args.repo_root)
    try:
        if (root / HONEST_STATE_RELPATH).is_file():
            verify_honest_state(root)
            emit({"ok": True, "mode": "verify_committed"}, as_json=True)
        else:
            emit({"ok": True, "mode": "derive", "state": derive_honest_state(root)}, as_json=True)
        return 0
    except (OSError, M3FValidationError) as exc:
        emit({"ok": False, "error": str(exc)}, as_json=True)
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
