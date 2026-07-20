"""The V2A one-shot research orchestrator: the single governed sequence, start to finish.

``run_one_shot`` is the only entry point that touches the real research-train partition to evaluate
strategies, and it does so exactly once, mediated by the append-only registry:

1. load the firewalled research-train (sealed partitions are unreachable);
2. append ``started`` — this consumes the one-shot budget *before* any evaluation, so a crash cannot
   be retried;
3. evaluate every candidate, apply the pre-registered decision rule, assemble the results;
4. publish the results into the immutable archive;
5. append ``completed`` binding the results fingerprint.

If anything between steps 3 and 4 raises, ``failed`` is appended and the exception re-raised — the
budget stays consumed, there is no repair or reset. The evaluation itself
(:func:`execute_evaluation`) is deterministic, so a rehearsal on a synthetic frame exercises the
full engine path without peeking
at the real prices.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from eth_research.v2 import V2A_PACKAGE_VERSION
from eth_research.v2.decision import ProgramDecision, decide
from eth_research.v2.evaluator import ProgramEvaluation, evaluate_program
from eth_research.v2.partitions import load_research_train_only
from eth_research.v2.protocol import ResearchProtocol
from eth_research.v2.publication import publish_results
from eth_research.v2.registry import COMPLETED, FAILED, STARTED, append_event
from eth_research.v2.results import FrozenResearchResults, build_results
from eth_research.v2.strict import V2ValidationError
from eth_research.walkforward import WalkForwardProtocol, load_walk_forward_protocol

REGISTRY_RELPATH: str = "research/v2a/research_registry.jsonl"
WALK_FORWARD_RELPATH: str = "research/m3a/walk_forward_protocol.json"


class OrchestratorError(V2ValidationError):
    """The one-shot orchestration could not proceed."""


def execute_evaluation(
    research_train: pd.DataFrame, wf_protocol: WalkForwardProtocol, protocol: ResearchProtocol
) -> tuple[ProgramEvaluation, ProgramDecision]:
    """Run the full deterministic evaluation and apply the decision rule (no side effects)."""
    evaluation = evaluate_program(research_train, wf_protocol, protocol)
    decision = decide(evaluation, protocol)
    return evaluation, decision


def run_one_shot(
    repo_root: str | Path,
    run_id: str,
    *,
    started_at: str,
    completed_at: str,
    registry_path: str | Path | None = None,
    wf_protocol: WalkForwardProtocol | None = None,
) -> FrozenResearchResults:
    """Execute the single governed research run and publish its results (registry-mediated)."""
    root = Path(repo_root)
    protocol = ResearchProtocol.current()
    fp = protocol.fingerprint()
    registry = Path(registry_path) if registry_path is not None else root / REGISTRY_RELPATH

    view = load_research_train_only(root)
    wf = (
        wf_protocol
        if wf_protocol is not None
        else load_walk_forward_protocol(root / WALK_FORWARD_RELPATH)
    )

    append_event(registry, STARTED, run_id, protocol_fingerprint=fp, timestamp=started_at)
    try:
        evaluation, decision = execute_evaluation(view.frame, wf, protocol)
        results = build_results(
            run_id,
            evaluation,
            decision,
            research_train_fingerprint=view.content_fingerprint,
            package_version=V2A_PACKAGE_VERSION,
        )
        publish_results(root, results)
    except Exception as exc:
        append_event(
            registry,
            FAILED,
            run_id,
            protocol_fingerprint=fp,
            timestamp=completed_at,
            payload={"reason": type(exc).__name__},
        )
        raise
    append_event(
        registry,
        COMPLETED,
        run_id,
        protocol_fingerprint=fp,
        timestamp=completed_at,
        payload={"results_fingerprint": results.fingerprint()},
    )
    return results
