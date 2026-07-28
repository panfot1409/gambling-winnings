"""Workflow-security invariants for the M3E update automation.

Under the committed V2D activation anchor the standing update workflow is ACTIVE:
it gates fail-closed on the anchor, fetches the due window on two isolated
runners over one hardened curl (endpoint from the offline-emitted plan — no host
literal in YAML), pushes exactly one new bot branch (job-scoped contents: write),
and opens exactly one DRAFT PR (job-scoped pull-requests: write). It never
merges, undrafts, retargets, force-pushes, or references a repository secret,
and every other workflow keeps the full read-only posture — all pinned below and
by the shared fail-closed scanners.
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


def _uncommented(text: str) -> str:
    """Drop whole-line YAML comments, leaving only directives.

    Deliberately does not strip trailing comments: those sit on lines that already
    carry a directive, so removing them cannot turn an active trigger into an absent
    one, and naive trailing-comment stripping would corrupt any value containing '#'.
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _job_blocks(text: str) -> dict[str, str]:
    """Split a workflow into ``{job_name: body}``, each body ending at the next job.

    Ordering assertions are worthless if a job's "body" runs to end-of-file,
    because a later job's step then satisfies an earlier job's requirement.
    """
    headers = list(re.finditer(r"^  ([A-Za-z_][A-Za-z0-9_-]*):$", text, re.MULTILINE))
    blocks: dict[str, str] = {}
    for i, match in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        blocks[match.group(1)] = text[match.end() : end]
    return blocks


def test_both_m3e_workflows_exist() -> None:
    assert PROBE.is_file()
    assert PR_CHECK.is_file()


def test_the_update_workflow_defaults_read_only_and_is_schedule_suspended() -> None:
    # V2F-R containment supersedes the V2D schedule. This assertion used to pin
    # `cron: "17 2 * * 1"` in place; it now pins its ABSENCE, so restoring the
    # weekly trigger cannot pass CI silently — it has to come back through this
    # test, which is the point at which a human sees it.
    text = PROBE.read_text()
    assert "permissions:\n  contents: read" in text  # top-level default stays read
    # Check YAML, not raw text: the containment comment in this workflow explains what
    # was removed and necessarily names `schedule:`/`cron:`. A substring check over the
    # whole file cannot tell an active trigger from a comment describing its absence.
    directives = _uncommented(text)
    assert "cron:" not in directives  # V2F-R containment: no unattended egress
    assert "schedule:" not in directives  # removed, not commented out
    assert "workflow_dispatch:" in directives
    assert "github.repository == 'panfot1409/gambling-winnings'" in text
    assert "concurrency:" in text  # overlapping runs stay serialized


def test_every_job_that_can_reach_the_network_runs_the_containment_gate_first() -> None:
    """A dispatch must not be able to fetch while containment is active.

    Removing `schedule:` stops the timer, but `workflow_dispatch:` is still
    there, so the gate is what actually holds. It must run before the fetch in
    every job that performs or publishes one — not only in the job the others
    happen to depend on today.
    """
    text = PROBE.read_text()
    gate = "run: python3 tools/v2f_containment_gate.py --repo-root ."
    assert text.count(gate) == 4  # gate_and_plan, runner_a, runner_b, assemble_and_publish

    jobs = _job_blocks(text)
    for job, guarded_step in (
        ("gate_and_plan", "eth_research.v2d verify"),
        ("runner_a", "tools/m3e_fetch_window.sh"),
        ("runner_b", "tools/m3e_fetch_window.sh"),
        ("assemble_and_publish", "git push origin"),
    ):
        body = jobs[job]
        assert gate in body, f"{job} has no containment gate"
        assert guarded_step in body, f"{job} no longer contains {guarded_step!r}; update this test"
        assert body.index(gate) < body.index(guarded_step), (
            f"{job} reaches {guarded_step!r} before the containment gate"
        )


def test_the_active_update_workflow_has_exactly_the_authorized_shape() -> None:
    # V2D supersedes the read-only probe: under the committed activation anchor
    # the standing workflow now fetches on two isolated runners (endpoint from
    # the offline-emitted plan — still no host literal in YAML), moves runner
    # bundles as private artifacts, pushes ONE new bot branch (job-scoped
    # contents: write), and opens ONE draft PR (job-scoped pull-requests:
    # write). It still never merges/undrafts/retargets, never force-pushes,
    # never references a repository secret, and gates on the anchor first.
    text = PROBE.read_text()
    assert "eth_research.v2d verify" in text  # fail-closed gate before any fetch
    assert "tools/m3e_fetch_window.sh" in text  # the single hardened curl driver
    assert "upload-artifact" in text  # inter-job runner-bundle transport
    assert 'git push origin "HEAD:refs/heads/${{ steps.prepare.outputs.branch }}"' in text
    assert "bot/m3e-prospective-update/" in text  # push + PR guards pin the prefix
    assert "gh pr create --draft --base main" in text
    assert not re.search(r"https?://[^\s\"']*coinbase", text, re.IGNORECASE)
    assert "secrets." not in text  # the job token is github.token, never a secret
    assert "--force" not in text
    assert "pull_request_target" not in text
    assert "enable_pr_auto_merge" not in text
    assert "gh pr merge" not in text
    assert "gh pr ready" not in text
    assert text.count("contents: write") == 1
    assert text.count("pull-requests: write") == 1


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


# The single authorized private-repo release-artifact channel (basename only). Every other
# workflow must upload nothing; the exemption is enforced conditionally in
# eth_research.m3e.verify_m3e_program._no_unsafe_workflow and
# eth_research.m3f.workflow_inventory.check_inventory, and probed in
# tests/test_private_workflow_security.py.
_ARTIFACT_UPLOAD_ALLOWLIST = {"private-release-build.yml", "m3e-prospective-update.yml"}


def test_no_m3e_or_other_workflow_uploads_an_artifact() -> None:
    # Reinforces the accepted no-artifact-upload invariant across the whole tree, except the one
    # allowlisted private-release payload builder (a workflow_dispatch-only, contents:read job that
    # uploads only the closed dist_private/ directory to this PRIVATE repo's own artifact store).
    for path in _all_workflows():
        if path.name in _ARTIFACT_UPLOAD_ALLOWLIST:
            continue
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
