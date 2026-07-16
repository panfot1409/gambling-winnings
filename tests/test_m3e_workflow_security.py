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


# --------------------------------------------------------------------------- #
# hardened scanner: the substring-evasion matrix must all fail closed         #
# --------------------------------------------------------------------------- #
_SAFE = (
    "name: x\non: push\npermissions:\n  contents: read\n"
    "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n"
)


def _scan_body(tmp_path: Path, body: str) -> None:
    wf = tmp_path / ".github/workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "hostile.yml").write_text(body)
    _no_unsafe_workflow(tmp_path)


def test_a_clean_read_only_workflow_passes_the_scanner(tmp_path: Path) -> None:
    _scan_body(tmp_path, _SAFE)  # control: the baseline is accepted


@pytest.mark.parametrize(
    ("label", "body"),
    [
        (
            "write-all",
            "name: x\non: push\npermissions: write-all\njobs:\n  j:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
        ),
        (
            "quoted-contents-write",
            "name: x\non: push\npermissions:\n  contents: 'write'\njobs:\n  j:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
        ),
        (
            "spaced-contents-write",
            "name: x\non: push\npermissions:\n  contents:  write\njobs:\n  j:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
        ),
        ("secrets-index", _SAFE + "      - run: echo ${{ secrets['PAT'] }}\n"),
        ("secrets-inherit", _SAFE + "    secrets: inherit\n"),
        ("upload-artifact", _SAFE + "      - uses: actions/upload-artifact@abc\n"),
        ("upload-pages-artifact", _SAFE + "      - uses: actions/upload-pages-artifact@abc\n"),
        ("force-push-f", _SAFE + "      - run: git push -f origin main\n"),
        ("force-push-refspec", _SAFE + "      - run: git push origin +HEAD:main\n"),
        ("automerge-auto-eq", _SAFE + "      - run: gh pr merge --auto=true 1\n"),
        (
            "automerge-graphql",
            _SAFE + "      - run: gh api graphql -f q=enablePullRequestAutoMerge\n",
        ),
        (
            "automerge-action",
            _SAFE + "      - uses: peter-evans/enable-pull-request-automerge@abc\n",
        ),
        ("coinbase-no-scheme", _SAFE + "      - run: curl api.exchange.coinbase.com/x -o o\n"),
        (
            "no-permissions-block",
            "name: x\non: push\njobs:\n  j:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - run: echo hi\n",
        ),
        (
            "anchor-alias-write",
            "name: x\non: push\n_w: &w write\npermissions:\n  contents: *w\njobs:\n  j:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
        ),
        (
            "anchor-alias-write-all",
            "name: x\non: push\n_w: &w write-all\npermissions: *w\njobs:\n  j:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
        ),
        (
            "block-anchor-literal-write",
            "name: x\non: push\n_p: &p\n  contents: write\npermissions: *p\njobs:\n  j:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
        ),
        ("pull-requests-write", _SAFE + "permissions:\n  pull-requests: write\n"),
        ("id-token-write", _SAFE + "permissions:\n  id-token: write\n"),
        ("packages-write", _SAFE + "permissions:\n  packages: write\n"),
        ("deployments-write", _SAFE + "permissions:\n  deployments: write\n"),
        ("checks-write", _SAFE + "permissions:\n  checks: write\n"),
        (
            "multiline-run-force-push",
            _SAFE + "      - run: |\n          set -e\n          git push -f origin main\n",
        ),
        (
            "job-level-write-all",
            "name: x\non: push\npermissions:\n  contents: read\njobs:\n  j:\n"
            "    permissions: write-all\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - run: echo hi\n",
        ),
        # audit §17 (Auditor B finding 1): a write permission in YAML *flow* style,
        # which the line-anchored block scanner does not see.
        (
            "flow-write-mapping",
            "name: x\non: push\npermissions: { contents: write }\njobs:\n  j:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
        ),
        (
            "flow-write-mapping-2-spaces",
            "name: x\non: push\npermissions: {contents:  write}\njobs:\n  j:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
        ),
        (
            "flow-write-mapping-tab",
            "name: x\non: push\npermissions: {contents:\twrite}\njobs:\n  j:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
        ),
        # audit §17 (Auditor B finding 1): the presence gate must require a REAL,
        # non-comment permissions declaration — a decoy ``# permissions:`` comment
        # must not satisfy it (the job would inherit the default token otherwise).
        (
            "comment-only-permissions-no-real-block",
            "name: x\non: push\n# permissions: contents read (decoy)\njobs:\n  j:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
        ),
        # audit §17 (Auditor B finding 2): write verbs the force/auto-merge scanner
        # misses — a plain push to an accepted ref, a non-``--auto`` merge, undraft,
        # a REST merge, a retarget.
        (
            "plain-push-to-accepted-branch",
            _SAFE + "      - run: git push origin HEAD:claude/m3d-cohort\n",
        ),
        ("plain-push-to-main", _SAFE + "      - run: git push origin main\n"),
        ("gh-pr-merge-squash-admin", _SAFE + "      - run: gh pr merge --squash --admin 1\n"),
        ("gh-pr-merge-plain", _SAFE + "      - run: gh pr merge 1 --merge\n"),
        ("gh-pr-ready-undraft", _SAFE + "      - run: gh pr ready 1\n"),
        ("rest-api-merge", _SAFE + "      - run: gh api -X PUT repos/o/r/pulls/1/merge\n"),
        ("gh-pr-edit-retarget", _SAFE + "      - run: gh pr edit 1 --base main\n"),
    ],
)
def test_hardened_scanner_rejects_each_evasion(label: str, body: str, tmp_path: Path) -> None:
    with pytest.raises(M3EValidationError):
        _scan_body(tmp_path, body)


def test_scanner_covers_the_yaml_extension_too(tmp_path: Path) -> None:
    # A hostile workflow using the .yaml (not .yml) extension is still scanned.
    wf = tmp_path / ".github/workflows"
    wf.mkdir(parents=True)
    (wf / "hostile.yaml").write_text(
        "name: x\non: push\npermissions:\n  contents: write\njobs:\n  j:\n"
        "    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n"
    )
    with pytest.raises(M3EValidationError):
        _no_unsafe_workflow(tmp_path)


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
