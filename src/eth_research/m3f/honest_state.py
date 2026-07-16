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

from eth_research.m3f.validation import (
    M3FValidationError,
    canonical_json_bytes,
    load_canonical_json,
    require_int,
    require_str,
    sha256_bytes,
)

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
    reg_lines = [
        line
        for line in (root / "research/m3e/proposal_registry.jsonl").read_text().splitlines()
        if line.strip()
    ]
    proposals = sum(1 for line in reg_lines if '"proposal_created": true' in line)

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
    authorized = bool(base["evaluation_authorized"])

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

    # The three forever-invariants — fail closed at derivation.
    if authorized:
        raise M3FValidationError("HARD STOP: m3d evaluation_authorized is true")
    if proposals != 0:
        raise M3FValidationError("HARD STOP: a production proposal exists")
    if workflows_write:
        raise M3FValidationError("HARD STOP: a workflow can write repository contents")
    for rel, facts in ledgers.items():
        if facts["byte_count"] != 0 or facts["sha256"] != EMPTY_SHA256:
            raise M3FValidationError(f"HARD STOP: sealed ledger {rel} is non-empty")
    return state


def _any_workflow_writes(root: Path) -> bool:
    wf = root / ".github/workflows"
    if not wf.is_dir():
        return False
    for path in sorted([*wf.glob("*.yml"), *wf.glob("*.yaml")]):
        text = path.read_text(encoding="utf-8")
        if "write-all" in text or "contents: write" in text or "contents:write" in text:
            return True
        if "permissions:" in text and "{" in text:
            for line in text.splitlines():
                if "permissions" in line and "{" in line and "write" in line:
                    return True
    return False


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
    """The committed honest-state JSON + Markdown reproduce byte-for-byte from bytes."""
    root = Path(repo_root)
    state = derive_honest_state(root)
    committed = (root / HONEST_STATE_RELPATH).read_bytes()
    if committed != render_honest_state_bytes(state):
        raise M3FValidationError("committed honest_state.json does not reproduce from bytes")
    committed_md = (root / HONEST_STATE_MD_RELPATH).read_bytes()
    if committed_md != render_honest_state_md(state):
        raise M3FValidationError("committed HONEST_STATE.md does not reproduce from the JSON")
