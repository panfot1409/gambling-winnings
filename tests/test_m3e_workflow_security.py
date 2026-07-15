"""Workflow-security invariants for the M3E update automation (commit 15).

The standing update workflow at HEAD is a strictly read-only "update-due probe": it
verifies the accepted base and reports whether a new completed day is due, but never
fetches, never uploads an artifact, never pushes, and never opens a PR — consistent
with this repository's accepted no-artifact-upload / no-write security posture. The
full acquisition + two-runner + assemble + draft-PR automation is the offline
``eth_research.m3e`` machinery, proven by ``tests/test_m3e_publisher_e2e.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import eth_research
from eth_research.m3e.validation import M3EValidationError
from eth_research.m3e.verify_m3e_program import _no_unsafe_workflow

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github/workflows"
PROBE = WORKFLOWS / "m3e-prospective-update.yml"
PR_CHECK = WORKFLOWS / "m3e-update-pr-check.yml"


def _all_workflows() -> list[Path]:
    return sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])


def test_both_m3e_workflows_exist() -> None:
    assert PROBE.is_file()
    assert PR_CHECK.is_file()


def test_the_probe_is_read_only_and_scheduled() -> None:
    text = PROBE.read_text()
    assert "permissions:\n  contents: read" in text
    assert "contents: write" not in text
    assert 'cron: "17 2 * * 1"' in text  # Mondays 02:17 UTC
    assert "workflow_dispatch:" in text
    assert "github.repository == 'panfot1409/gambling-winnings'" in text


def test_the_probe_neither_fetches_uploads_pushes_nor_opens_a_pr() -> None:
    text = PROBE.read_text()
    assert "curl" not in text  # the probe does not fetch
    assert "upload-artifact" not in text
    assert "git push" not in text
    assert "create_pull_request" not in text
    assert "gh pr create" not in text
    assert not re.search(r"https?://[^\s\"']*coinbase", text, re.IGNORECASE)
    assert "secrets." not in text
    assert "--force" not in text
    assert "pull_request_target" not in text
    assert "enable_pr_auto_merge" not in text


def test_the_pr_check_is_read_only_and_requires_a_draft() -> None:
    text = PR_CHECK.read_text()
    assert "on:\n  pull_request:\n" in text
    assert "pull_request_target" not in text
    assert "contents: read" in text
    assert "pull-requests: read" in text
    assert "contents: write" not in text
    assert "github.event.pull_request.draft" in text  # asserts a draft
    assert "git push" not in text
    assert "upload-artifact" not in text


def test_no_m3e_or_other_workflow_uploads_an_artifact() -> None:
    # Reinforces the accepted no-artifact-upload invariant across the whole tree.
    for path in _all_workflows():
        assert "upload-artifact" not in path.read_text(), f"{path.name} uploads an artifact"


def test_no_workflow_at_head_is_unsafe() -> None:
    _no_unsafe_workflow(REPO_ROOT)


@pytest.mark.parametrize(
    "bad",
    [
        "permissions:\n  contents: write\n",
        "run: curl https://api.exchange.coinbase.com/x\n",
        "env:\n  TOKEN: ${{ secrets.PAT }}\n",
        "run: git push --force origin main\n",
        "on:\n  pull_request_target:\n",
        "run: gh pr merge --auto\n",
    ],
)
def test_unsafe_workflow_patterns_are_caught(tmp_path: Path, bad: str) -> None:
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / ".github/workflows/evil.yml").write_text(bad)
    with pytest.raises(M3EValidationError):
        _no_unsafe_workflow(tmp_path)
