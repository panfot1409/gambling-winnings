"""Static workflow-security scan for the M3D acquisition supply chain.

Enforced for every workflow, and specifically for the one-shot acquisition
workflow while it exists. After the acquisition workflow is retired (deleted),
the "only acquire may write / touch Coinbase" invariants hold vacuously, so the
same tests assert the retired state too.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_WORKFLOWS = _REPO / ".github" / "workflows"
_ACQUIRE = _WORKFLOWS / "m3d-acquire.yml"
_COINBASE_HOST = "api.exchange.coinbase.com"
_BRANCH = "claude/m3d-prospective-evidence-governance"


def _workflows() -> list[Path]:
    files = sorted(_WORKFLOWS.glob("*.yml")) + sorted(_WORKFLOWS.glob("*.yaml"))
    assert files, "no workflows found"
    return files


def _uses_refs(text: str) -> list[str]:
    refs: list[str] = []
    for line in text.splitlines():
        match = re.search(r"\buses:\s*(\S+)", line)
        if match:
            refs.append(match.group(1))
    return refs


def test_every_action_use_is_pinned_by_full_sha() -> None:
    offenders: list[str] = []
    for workflow in _workflows():
        for ref in _uses_refs(workflow.read_text()):
            if "@" in ref and not re.search(r"@[0-9a-f]{40}$", ref):
                offenders.append(f"{workflow.name}: {ref}")
    assert not offenders, "unpinned action refs: " + ", ".join(offenders)


def test_no_workflow_uses_a_piped_installer() -> None:
    for workflow in _workflows():
        text = workflow.read_text()
        assert "curl" not in text or "| sh" not in text, f"{workflow.name}: curl|sh"
        assert "| bash" not in text, f"{workflow.name}: piped bash"
        assert "| sh" not in text or "uv" not in text, f"{workflow.name}: piped installer"


def test_only_acquire_workflow_may_write_or_reach_coinbase() -> None:
    for workflow in _workflows():
        if workflow.name == _ACQUIRE.name:
            continue
        text = workflow.read_text()
        assert "contents: write" not in text, f"{workflow.name} grants contents: write"
        assert _COINBASE_HOST not in text, f"{workflow.name} references Coinbase"
        assert "--force" not in text, f"{workflow.name} force-pushes"


def test_acquire_workflow_is_hardened_when_present() -> None:
    if not _ACQUIRE.exists():
        pytest.skip("acquisition workflow retired at this HEAD")
    text = _ACQUIRE.read_text()
    # Trigger surface: manual dispatch plus a branch+path-scoped committed
    # trigger, and never a pull_request. Because the workflow file lives only on
    # the stacked feature branch (never on the default branch), workflow_dispatch
    # is not dispatchable here; the operative trigger is a push that touches the
    # single committed sentinel. That push must be scoped to this branch and to
    # the sentinel path only, so no unrelated push can fire an acquisition.
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert re.search(r"^\s*push:", text, re.MULTILINE) is not None
    assert "research/m3d/acquire.trigger" in text
    push_block = text.split("push:", 1)[1].split("jobs:", 1)[0]
    assert _BRANCH in push_block, "push trigger is not scoped to the stacked branch"
    assert "research/m3d/acquire.trigger" in push_block, "push trigger is not path-scoped"
    # Write permission is scoped to the acquire job, not the workflow default.
    assert "permissions:\n  contents: read" in text
    assert "contents: write" in text
    # Exact repository + stacked-branch guard.
    assert "github.repository == 'panfot1409/gambling-winnings'" in text
    assert _BRANCH in text
    # Supply chain: pinned checkout, hash-pinned uv, no secrets, no force push.
    assert "ci/uv-requirements.txt" in text
    assert "--require-hashes" in text
    assert "secrets." not in text
    assert "--force" not in text
    assert "force-push" not in text
    # It does not embed the Coinbase URL (the runner owns the pinned endpoint).
    assert _COINBASE_HOST not in text


def test_no_workflow_references_repository_secrets() -> None:
    for workflow in _workflows():
        assert "${{ secrets." not in workflow.read_text(), f"{workflow.name} uses a secret"


def test_acquire_workflow_and_trigger_are_retired() -> None:
    # Section 25: the one-shot acquisition workflow and its committed push sentinel
    # are deleted at the final HEAD; no dormant data-overwrite machine remains.
    assert not _ACQUIRE.exists()
    assert not (_REPO / "research/m3d/acquire.trigger").exists()
