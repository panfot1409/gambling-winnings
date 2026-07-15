"""Workflow-security invariants for the M3E update automation (commit 15)."""

from __future__ import annotations

from pathlib import Path

import pytest

import eth_research
from eth_research.m3e.validation import M3EValidationError
from eth_research.m3e.verify_m3e_program import _no_unsafe_workflow

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github/workflows"
UPDATE = WORKFLOWS / "m3e-prospective-update.yml"
PR_CHECK = WORKFLOWS / "m3e-update-pr-check.yml"


def test_both_m3e_workflows_exist() -> None:
    assert UPDATE.is_file()
    assert PR_CHECK.is_file()


def test_the_update_workflow_is_read_only_and_scheduled() -> None:
    text = UPDATE.read_text()
    assert "permissions:\n  contents: read" in text
    assert "contents: write" not in text
    assert 'cron: "17 2 * * 1"' in text  # Mondays 02:17 UTC
    assert "workflow_dispatch:" in text
    # Two isolated runner jobs on two isolated runners.
    assert "runner: [a, b]" in text


def test_the_update_workflow_never_pushes_or_opens_a_pr() -> None:
    text = UPDATE.read_text()
    assert "git push" not in text
    assert "create_pull_request" not in text
    assert "gh pr create" not in text
    assert "peter-evans/create-pull-request" not in text
    # No literal exchange *host* URL (the endpoint is read from the committed plan);
    # the runner attempt-id string may legitimately mention the venue by name.
    import re

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


def test_no_workflow_at_head_is_unsafe() -> None:
    # The whole .github/workflows tree passes the strict M3E scan.
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
