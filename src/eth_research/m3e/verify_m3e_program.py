"""Whole-proposal graph verifier for Milestone 3E.

``verify_update_proposal`` always runs the complete review-only update-proposal
chain — no parameter can skip a check. It re-derives every artifact from committed
bytes and proves, in one un-skippable 35-check graph:

* the accepted base rebuilds, the three ledgers are byte-empty, the M3C candidate is
  still rejected, the cohort is immature/unauthorized, and the **entire accepted
  M3D program is intact** (via the reviewed M3D verifier);
* the isolated ``m3e`` package imports only its allow-listed strategy-free
  utilities and no network/wallet client (relative imports resolved), and **no**
  workflow at HEAD grants a write permission (including ``write-all`` or an omitted
  permissions block), contacts a Coinbase host, references a secret, force-pushes,
  uploads an artifact, uses ``pull_request_target``, or enables auto-merge;
* both runner artifacts verify against the *same* update plan, are isolated, and
  produce **byte-identical canonical content** (the two-runner attestation);
* the committed comparison and transition rebuild byte-for-byte and their hashes are
  bound in the manifest;
* the transition is a strict append whose old fingerprint is the accepted base and
  whose proposed cohort = old + new;
* the proposal branch is a publishable bot branch matching the idempotency key;
* the review policy is draft-only / human-required / no-auto-merge / no-retarget /
  no-accepted-mutation, every governance flag is false, and **no** smuggled
  strategy/performance field or evaluation-output artifact exists in the proposal.

It computes no strategy quantity and moves no money.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from eth_research.m3d import _upstream as up
from eth_research.m3d.verify_m3d_program import (
    _scan_forbidden_fields,
    verify_m3d_program,
)
from eth_research.m3e.accepted_base import verify_accepted_base
from eth_research.m3e.comparison import compare_runners
from eth_research.m3e.lease import assert_publishable_proposal_branch, proposal_branch_name
from eth_research.m3e.proposal import (
    COMPARISON_NAME,
    GOVERNANCE_FLAGS,
    PROPOSAL_MANIFEST_NAME,
    REVIEW_POLICY,
    RUNNER_A_DIR,
    RUNNER_B_DIR,
    TRANSITION_NAME,
    assemble_proposal,
    load_proposal_manifest,
)
from eth_research.m3e.runner_boundary import load_and_verify_runner
from eth_research.m3e.transition import build_update_transition
from eth_research.m3e.validation import (
    M3EValidationError,
    canonical_json_bytes,
    require_bool,
    require_mapping,
    require_str,
)

EXPECTED_BASE_FINGERPRINT = "bb6dd3921fa31915496806349ca21254e05070c94a97b30982030673b7966507"

# The isolated m3e package may import only these strategy-free eth_research modules
# (plus eth_research.m3e.* internals and any stdlib/third-party). Mirrors
# tests/test_m3e_architecture.py — an ALLOW-list, the robust dual of a deny-list.
_ALLOWED_ETH_RESEARCH_IMPORTS = frozenset(
    {
        "eth_research",
        "eth_research._json",
        "eth_research._atomic",
        "eth_research.data",
        "eth_research.data.provenance",
        "eth_research.data.validation",
        "eth_research.data.coinbase",
        "eth_research.data.schema",
        "eth_research.data.quality",
        "eth_research.m3d",
        "eth_research.m3d.validation",
        "eth_research.m3d._upstream",
        "eth_research.m3d.chain",
        "eth_research.m3d.acquisition_plan",
        "eth_research.m3d.receipt",
        "eth_research.m3d.raw_bundle",
        "eth_research.m3d.segment",
        "eth_research.m3d.cohort",
        "eth_research.m3d.protocol",
        "eth_research.m3d.quality",
        "eth_research.m3d.publication",
        "eth_research.m3d.reacquisition_audit",
        "eth_research.m3d.maturity",
        "eth_research.m3d.verify_m3d_program",
    }
)
# Network / wallet client prefixes the isolated m3e SOURCE must never import (it
# opens no socket and holds no key). Checked statically here — mirrors the
# ``_PROHIBITED_NETWORK_MODULES`` list in tests/test_m3e_architecture.py.
_PROHIBITED_NETWORK_PREFIXES = (
    "urllib",
    "urllib.request",
    "http",
    "http.client",
    "socket",
    "ssl",
    "requests",
    "aiohttp",
    "httpx",
    "websocket",
    "websockets",
    "web3",
    "eth_account",
    "ccxt",
)
# Coinbase host reference, scheme-agnostic (a bare ``exchange.coinbase.com`` in a
# ``curl`` argument connects just as well as an ``https://`` URL).
_COINBASE_HOST_RE = re.compile(r"(?:https?://[^\s\"']*)?coinbase\.(?:com|pro)\b", re.IGNORECASE)
# A workflow permission scope explicitly set to a write value (any scope, quoted or
# not, any surrounding whitespace) — e.g. ``contents: write`` / ``permissions: write-all``.
_WRITE_PERM_RE = re.compile(
    r"^\s*[A-Za-z_-]+\s*:\s*['\"]?write(?:-all)?['\"]?\s*(?:#.*)?$", re.MULTILINE
)
# A YAML anchor bound directly to a write value (``&w write``) — aliased later
# (``contents: *w``) to dodge the literal ``: write`` match. A read-only workflow has
# no legitimate reason to anchor a write scalar. (A block-level anchor still exposes a
# literal ``contents: write`` line, which ``_WRITE_PERM_RE`` catches; this closes the
# scalar-alias vector. A regex scan cannot fully parse arbitrary YAML or recurse into a
# remote reusable workflow — that irreducible residual is documented in the threat model
# and backstopped by branch protection + mandatory human review.)
_ANCHOR_WRITE_RE = re.compile(r"&[\w-]+\s+['\"]?write(?:-all)?\b", re.IGNORECASE)
# A repository secret reference in either dotted (``secrets.X``) or index
# (``secrets['X']``) form, or a wholesale ``secrets: inherit`` hand-off.
_SECRETS_RE = re.compile(r"secrets\s*[.\[]|secrets\s*:\s*inherit", re.IGNORECASE)
# A force-push written with the ``-f`` alias or a leading ``+`` refspec.
_FORCE_PUSH_RE = re.compile(r"git\s+push\b[^\n]*?(?:\s-\S*f\b|\s\+\S)", re.IGNORECASE)
# Auto-merge in any spelling: the MCP tool name, the GraphQL mutation, the
# community action, or ``gh pr merge --auto``.
_AUTO_MERGE_RE = re.compile(
    r"enable_pr_auto_merge|enablepullrequestautomerge|enable-pull-request-automerge|--auto\b",
    re.IGNORECASE,
)
# Filenames inside a proposal that would betray a smuggled evaluation output. This
# is the comprehensive strategy/performance vocabulary — the proposal directory is
# additionally restricted to an exact expected file set (see ``_no_forbidden_artifact``).
_FORBIDDEN_ARTIFACT_MARKERS = (
    "results",
    "result",
    "decision",
    "candidate",
    "metric",
    "promotion",
    "promote",
    "ranking",
    "evaluation",
    "evaluate",
    "backtest",
    "pnl",
    "sharpe",
    "sortino",
    "calmar",
    "alpha",
    "drawdown",
    "turnover",
    "return",
    "profit",
    "signal",
    "weight",
    "position",
    "exposure",
    "leverage",
    "performance",
    "equity",
    "strategy",
)
# The exact top-level entries a verified proposal directory may contain — anything
# else (a dropped ``weights.json`` / ``returns.json`` / a stray directory) is refused.
_EXPECTED_PROPOSAL_ENTRIES = frozenset(
    {PROPOSAL_MANIFEST_NAME, COMPARISON_NAME, TRANSITION_NAME, RUNNER_A_DIR, RUNNER_B_DIR}
)
_LEDGERS = {
    "development_gate": up.SEALED_LEDGERS["development_gate"],
    "final_holdout": up.SEALED_LEDGERS["final_holdout"],
    "prospective_evaluation": up.PROSPECTIVE_EVALUATION_LEDGER,
}


def _module_targets(path: Path, src_root: Path) -> list[str]:
    """Absolute dotted module names imported by ``path`` (relative imports resolved)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    self_pkg = ".".join(path.relative_to(src_root).with_suffix("").parts[:-1])
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import — resolve against the module's package
                base_parts = self_pkg.split(".")
                if node.level > 1:
                    base_parts = base_parts[: -(node.level - 1)]
                base = ".".join(base_parts)
                module = f"{base}.{node.module}" if node.module else base
            else:
                module = node.module or ""
            if module:
                modules.append(module)
    return modules


def _scan_m3e_imports(repo_root: str | Path) -> None:
    src_root = Path(repo_root) / "src"
    package = src_root / "eth_research/m3e"
    offenders: list[str] = []
    for path in sorted(package.rglob("*.py")):
        for module in _module_targets(path, src_root):
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in _PROHIBITED_NETWORK_PREFIXES
            ):
                offenders.append(f"{path.name}: {module} (network/wallet)")
                continue
            if not module.startswith("eth_research"):
                continue
            if module == "eth_research.m3e" or module.startswith("eth_research.m3e."):
                continue
            if module not in _ALLOWED_ETH_RESEARCH_IMPORTS:
                offenders.append(f"{path.name}: {module}")
    if offenders:
        raise M3EValidationError(f"m3e imports non-allowlisted or network modules: {offenders}")


def _no_unsafe_workflow(repo_root: str | Path) -> None:
    workflows = Path(repo_root) / ".github/workflows"
    files = sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")])
    for path in files:
        text = path.read_text(encoding="utf-8")
        if "permissions:" not in text:
            raise M3EValidationError(
                f"{path.name} declares no explicit (read-only) permissions block"
            )
        if "write-all" in text:
            raise M3EValidationError(f"{path.name} grants write-all permissions at HEAD")
        if _WRITE_PERM_RE.search(text):
            raise M3EValidationError(f"{path.name} grants a write permission at HEAD")
        if _ANCHOR_WRITE_RE.search(text):
            raise M3EValidationError(f"{path.name} anchors a write permission value at HEAD")
        if _COINBASE_HOST_RE.search(text):
            raise M3EValidationError(f"{path.name} contacts a Coinbase host at HEAD")
        if _SECRETS_RE.search(text):
            raise M3EValidationError(f"{path.name} references a repository secret")
        if "--force" in text or "--force-with-lease" in text or _FORCE_PUSH_RE.search(text):
            raise M3EValidationError(f"{path.name} force-pushes")
        if "pull_request_target" in text:
            raise M3EValidationError(f"{path.name} uses pull_request_target")
        if _AUTO_MERGE_RE.search(text):
            raise M3EValidationError(f"{path.name} enables auto-merge")
        if "upload-artifact" in text or "upload-pages-artifact" in text:
            raise M3EValidationError(f"{path.name} uploads a workflow artifact")


def _no_forbidden_artifact(proposal_dir: Path) -> None:
    # 1. The proposal directory's top level is an exact, closed set: manifest +
    #    comparison + transition + the two runner directories, nothing else. A
    #    dropped evaluation output (weights.json, returns.json, …) is refused here
    #    even if its name carries no strategy marker.
    entries = {p.name for p in proposal_dir.iterdir()}
    unexpected = sorted(entries - _EXPECTED_PROPOSAL_ENTRIES)
    if unexpected:
        raise M3EValidationError(f"proposal contains unexpected entries: {unexpected}")
    # 2. Belt-and-suspenders: no file anywhere in the tree carries a strategy /
    #    performance / evaluation marker in its name.
    for path in sorted(proposal_dir.rglob("*")):
        if not path.is_file():
            continue
        lowered = path.name.lower()
        for marker in _FORBIDDEN_ARTIFACT_MARKERS:
            if marker in lowered:
                raise M3EValidationError(
                    f"proposal contains a forbidden evaluation artifact: {path.name}"
                )


def _require_committed_matches(directory: Path, name: str, rebuilt: bytes) -> None:
    from eth_research.m3e.validation import load_canonical_json_bytes

    raw, _doc = load_canonical_json_bytes(directory / name, name)
    if raw != rebuilt:
        raise M3EValidationError(f"committed {name} does not match the rebuild")


def verify_update_proposal(
    repo_root: str | Path, proposal_dir: str | Path
) -> list[tuple[str, str]]:
    """Run the complete 35-check update-proposal chain; raise on the first failure."""
    root = Path(repo_root)
    directory = Path(proposal_dir)
    checks: list[tuple[str, str]] = []

    def record(name: str, detail: str = "ok") -> None:
        checks.append((name, detail))

    # 1-8. Accepted base + whole accepted program integrity.
    base = verify_accepted_base(root)
    record("01_accepted_base_rebuilds")
    if base.canonical_content_fingerprint != EXPECTED_BASE_FINGERPRINT:
        raise M3EValidationError("accepted base fingerprint is not the expected cohort")
    record("02_base_fingerprint", base.canonical_content_fingerprint[:16])
    for logical, path, label in (
        ("development_gate", _LEDGERS["development_gate"], "03_development_gate_ledger_empty"),
        ("final_holdout", _LEDGERS["final_holdout"], "04_final_holdout_ledger_empty"),
        (
            "prospective_evaluation",
            _LEDGERS["prospective_evaluation"],
            "05_prospective_ledger_empty",
        ),
    ):
        facts = up.ledger_facts(root, path)
        if facts["byte_count"] != 0 or facts["sha256"] != up.EMPTY_SHA256:
            raise M3EValidationError(f"ledger {logical} is non-empty (HARD STOP)")
        record(label)
    decision = up.load_json(root, up.ANCHORS["m3c"]["candidate_decision"])
    outcome = decision.get("outcome") if isinstance(decision, dict) else None
    if outcome != up.M3C_REJECTED_OUTCOME:
        raise M3EValidationError(f"M3C candidate outcome changed to {outcome!r} (HARD STOP)")
    record("06_m3c_still_rejected", str(outcome))
    if base.document["maturity_state"] != "immature" or base.document["evaluation_authorized"]:
        raise M3EValidationError("accepted base must be immature and unauthorized")
    record("07_base_immature_unauthorized")
    verify_m3d_program(root)
    record("08_accepted_m3d_program_intact")

    # 9-10. Package isolation + workflow safety at HEAD.
    _scan_m3e_imports(root)
    record("09_m3e_imports_allowlisted")
    _no_unsafe_workflow(root)
    record("10_no_write_or_coinbase_workflow")

    # 11-12. Proposal manifest + accepted-base binding.
    manifest = load_proposal_manifest(directory / PROPOSAL_MANIFEST_NAME)
    record("11_proposal_manifest_self_hash")
    if manifest["accepted_base_sha256"] != base.base_sha256:
        raise M3EValidationError("manifest does not bind the current accepted base")
    if manifest["accepted_base_fingerprint"] != base.canonical_content_fingerprint:
        raise M3EValidationError("manifest accepted-base fingerprint drifted")
    record("12_manifest_binds_accepted_base")

    # 13-17. Runners + two-runner attestation.
    runner_a = load_and_verify_runner(directory / RUNNER_A_DIR, runner_label="a")
    record("13_runner_a_verifies")
    runner_b = load_and_verify_runner(
        directory / RUNNER_B_DIR, runner_label="b", expected_plan_sha256=runner_a.plan_sha256
    )
    record("14_runner_b_verifies")
    if runner_a.plan_sha256 != runner_b.plan_sha256:
        raise M3EValidationError("runners replayed different plans")
    record("15_both_runners_same_plan")
    if runner_a.runner_identity == runner_b.runner_identity:
        raise M3EValidationError("runners are not isolated")
    record("16_runners_isolated")
    comparison = compare_runners(runner_a, runner_b)
    record("17_canonical_content_equal")

    # 18-19. Committed comparison rebuilds + hash bound in manifest.
    _require_committed_matches(
        directory, COMPARISON_NAME, canonical_json_bytes(comparison.to_dict())
    )
    record("18_comparison_matches_committed")
    if manifest["comparison"]["comparison_sha256"] != comparison.comparison_sha256:
        raise M3EValidationError("manifest comparison hash mismatch")
    record("19_comparison_hash_in_manifest")

    # 20-25. Transition.
    transition = build_update_transition(
        root,
        base,
        new_window_rows=runner_a.canonical_rows,
        new_window_fingerprint=comparison.new_window_fingerprint,
    )
    record("20_transition_rebuilds")
    if not transition.is_append_only:
        raise M3EValidationError("transition is not append-only")
    record("21_transition_is_append_only")
    if transition.old_fingerprint != base.canonical_content_fingerprint:
        raise M3EValidationError("transition old fingerprint is not the accepted base")
    record("22_transition_old_fingerprint_is_base")
    _require_committed_matches(
        directory, TRANSITION_NAME, canonical_json_bytes(transition.to_dict())
    )
    record("23_transition_matches_committed")
    if manifest["transition"]["transition_sha256"] != transition.transition_sha256:
        raise M3EValidationError("manifest transition hash mismatch")
    record("24_transition_hash_in_manifest")
    if (
        manifest["transition"]["proposed_cohort_fingerprint"]
        != transition.proposed_cohort_fingerprint
    ):
        raise M3EValidationError("manifest proposed-cohort fingerprint mismatch")
    record("25_proposed_cohort_fingerprint_in_manifest")

    # 26-27. Row accounting + idempotency.
    if transition.proposed_row_count != transition.old_row_count + transition.new_window_row_count:
        raise M3EValidationError("proposed row count is not old + new")
    record("26_proposed_row_count_old_plus_new")
    if not (comparison.idempotency_key == runner_a.idempotency_key == manifest["idempotency_key"]):
        raise M3EValidationError("idempotency key is inconsistent across the proposal")
    record("27_idempotency_consistent")

    # 28-29. Proposal branch.
    branch = require_str("proposal_branch", manifest["proposal_branch"])
    assert_publishable_proposal_branch(branch)
    record("28_proposal_branch_publishable")
    expected_branch = proposal_branch_name(
        idempotency_key=comparison.idempotency_key,
        first_missing_open=transition.new_window_first_open,
        completed_day_exclusive_end=_exclusive_end(transition),
    )
    if branch != expected_branch:
        raise M3EValidationError("proposal branch does not match the idempotency-derived name")
    record("29_proposal_branch_matches_idempotency")

    # 30-34. Review policy + governance flags.
    policy = require_mapping("review_policy", manifest["review_policy"])
    if not require_bool("draft_required", policy.get("draft_required")):
        raise M3EValidationError("review policy must require a draft")
    record("30_review_policy_draft_required")
    if not require_bool("human_review_required", policy.get("human_review_required")):
        raise M3EValidationError("review policy must require human review")
    record("31_review_policy_human_required")
    if not require_bool("auto_merge_forbidden", policy.get("auto_merge_forbidden")):
        raise M3EValidationError("review policy must forbid auto-merge")
    record("32_review_policy_no_auto_merge")
    if not require_bool("retarget_forbidden", policy.get("retarget_forbidden")):
        raise M3EValidationError("review policy must forbid retarget")
    if require_bool("modifies_accepted_branch", policy.get("modifies_accepted_branch")):
        raise M3EValidationError("review policy must not modify the accepted branch")
    if policy != REVIEW_POLICY:
        raise M3EValidationError("review policy drifted from the pinned policy")
    record("33_review_policy_no_retarget_no_accepted_mutation")
    flags = require_mapping("governance_flags", manifest["governance_flags"])
    if flags != GOVERNANCE_FLAGS or any(bool(v) for v in flags.values()):
        raise M3EValidationError("a governance flag is set — M3E evaluates nothing")
    record("34_governance_flags_all_false")

    # 35. No smuggled strategy/performance field or evaluation-output artifact.
    _scan_forbidden_fields(manifest, comparison.to_dict(), transition.to_dict())
    _no_forbidden_artifact(directory)
    record("35_no_smuggled_field_or_artifact")

    # Cross-check: the committed manifest reproduces the freshly-assembled one.
    assembled = assemble_proposal(root, directory)
    if canonical_json_bytes(assembled.manifest_document) != canonical_json_bytes(manifest):
        raise M3EValidationError("committed proposal manifest does not match the rebuild")

    return checks


def _exclusive_end(transition: Any) -> str:
    import pandas as pd

    return (pd.Timestamp(transition.proposed_last_open) + pd.Timedelta(days=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
