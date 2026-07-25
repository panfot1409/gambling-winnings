"""Cross-checks for the three independent derivations of the closed file set.

The acceptance record's ``file_set_binding`` is derived once by
``eth_research.m3e.proposal_file_policy`` (the writer and production verifier),
and re-derived twice — by ``eth_research.m3f.acceptance_file_set`` and by
``tools/m3f_independent_verify.py`` — from separately written code.

Three implementations of the same rules is implementation diversity, not three
trust anchors: all three read the same repository. What these tests enforce is
that a divergence between them is loud. Without them the two shadow
implementations would drift silently and their agreement would mean nothing.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from eth_research.m3e.acceptance import ACCEPTANCES_ROOT, load_acceptance_chain
from eth_research.m3e.proposal_file_policy import (
    ProposalFilePolicyError,
    _classify_path,
    build_record_binding,
    verify_proposal_file_policy,
)
from eth_research.m3f.acceptance_file_set import (
    _classify,
    derive_binding,
    verify_record_file_set,
)
from eth_research.m3f.validation import M3FValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEPENDENT_TOOL = REPO_ROOT / "tools/m3f_independent_verify.py"


def _load_tool() -> Any:
    """Import the stdlib-only tool as a module so its internals can be called."""
    spec = importlib.util.spec_from_file_location("m3f_independent_verify", INDEPENDENT_TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool() -> Any:
    return _load_tool()


@pytest.fixture(scope="module")
def accepted() -> list[tuple[str, dict[str, Any]]]:
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("git history is required to re-derive a file-set binding")
    chain = load_acceptance_chain(REPO_ROOT, require_completion=True)
    if not chain:
        pytest.skip("no acceptance to cross-check")
    return [(entry.proposal_id, entry.record) for entry in chain]


def test_all_three_implementations_derive_the_same_binding(
    accepted: list[tuple[str, dict[str, Any]]], tool: Any
) -> None:
    for proposal_id, record in accepted:
        parent = record["expected_parent_commit"]
        head = record["proposal_head_commit"]
        m3e = build_record_binding(
            REPO_ROOT,
            verify_proposal_file_policy(
                REPO_ROOT, proposal_id=proposal_id, parent_commit=parent, head_commit=head
            ),
        )
        m3f = derive_binding(REPO_ROOT, proposal_id=proposal_id, parent=parent, head=head)
        independent = tool._rederive_file_set_binding(REPO_ROOT, proposal_id, parent, head)
        assert m3f == m3e, "m3f re-derivation diverged from the m3e policy"
        assert independent == m3e, "the stdlib tool diverged from the m3e policy"
        # …and the committed record equals what all three derive.
        assert record["file_set_binding"] == m3e


def test_the_three_classifiers_agree_on_every_real_member(
    accepted: list[tuple[str, dict[str, Any]]], tool: Any
) -> None:
    for proposal_id, record in accepted:
        verified = verify_proposal_file_policy(
            REPO_ROOT,
            proposal_id=proposal_id,
            parent_commit=record["expected_parent_commit"],
            head_commit=record["proposal_head_commit"],
        )
        assert verified.files, "the proposal has no members to compare"
        for entry in verified.files:
            assert _classify(entry.path, proposal_id) == entry.role
            assert tool._proposal_role(entry.path, proposal_id) == entry.role


@pytest.mark.parametrize(
    "path",
    [
        "src/eth_research/m3e/acceptance.py",
        ".github/workflows/evil.yml",
        "research/m3e/proposals/OTHER/proposal_manifest.json",
        "research/m3d/raw/coinbase/not-this-proposal/acquisition_plan.json",
        "research/m3e/proposals/{pid}/runner_c/update_plan.json",
        "research/m3e/proposals/{pid}/runner_a/unknown.json",
        "research/m3e/proposals/{pid}/unknown.json",
        "research/m3e/proposals/{pid}/runner_a/nested/deep.json",
        "research/m3e/.hidden/file.json",
        "research/m3e/proposals/{pid}/proposal_manifest.txt",
        "docs/README.md",
        "../escape.json",
    ],
)
def test_all_three_classifiers_refuse_the_same_unlawful_paths(
    path: str, accepted: list[tuple[str, dict[str, Any]]], tool: Any
) -> None:
    """A path no rule admits must be refused by every implementation.

    Agreement on the happy path is cheap; agreement on refusals is what stops one
    implementation from quietly admitting something the others reject."""
    proposal_id = accepted[0][0]
    candidate = path.format(pid=proposal_id)
    with pytest.raises(ProposalFilePolicyError):
        _classify_path(candidate, proposal_id)
    with pytest.raises(M3FValidationError):
        _classify(candidate, proposal_id)
    with pytest.raises(tool.IndependentVerifyError):
        tool._proposal_role(candidate, proposal_id)


def test_binding_is_not_read_as_its_own_allowlist(
    accepted: list[tuple[str, dict[str, Any]]], tool: Any
) -> None:
    """Declaring an extra member cannot admit it, in any of the three paths.

    The record is mutated in memory only — the shared worktree is never touched
    (see CONTRIBUTING, audit boundaries). Each verifier is handed the forged
    record directly, so this exercises the comparison itself rather than the
    surrounding chain checks."""
    proposal_id, record = accepted[0]
    forged = json.loads(json.dumps(record))
    forged["file_set_binding"]["allowed_member_count"] += 1

    with pytest.raises(M3FValidationError, match="allowed_member_count"):
        verify_record_file_set(REPO_ROOT, forged, proposal_id=proposal_id)
    with pytest.raises(tool.IndependentVerifyError, match="allowed_member_count"):
        tool._check_file_set_binding(REPO_ROOT, forged, proposal_id)


def test_binding_with_an_unknown_field_is_refused(
    accepted: list[tuple[str, dict[str, Any]]], tool: Any
) -> None:
    """An unrecognised binding field must not ride along unverified."""
    proposal_id, record = accepted[0]
    forged = json.loads(json.dumps(record))
    forged["file_set_binding"]["extra_authority"] = "trust me"

    with pytest.raises(M3FValidationError, match="unknown field"):
        verify_record_file_set(REPO_ROOT, forged, proposal_id=proposal_id)
    with pytest.raises(tool.IndependentVerifyError, match="unknown field"):
        tool._check_file_set_binding(REPO_ROOT, forged, proposal_id)


def test_binding_must_certify_the_record_s_own_commits(
    accepted: list[tuple[str, dict[str, Any]]], tool: Any
) -> None:
    """A binding for some other commit pair cannot vouch for this acceptance."""
    proposal_id, record = accepted[0]
    forged = json.loads(json.dumps(record))
    forged["proposal_head_commit"] = "0" * 40

    with pytest.raises(M3FValidationError, match="different commit"):
        verify_record_file_set(REPO_ROOT, forged, proposal_id=proposal_id)
    with pytest.raises(tool.IndependentVerifyError, match="different commits"):
        tool._check_file_set_binding(REPO_ROOT, forged, proposal_id)


def test_independent_tool_still_imports_only_the_standard_library() -> None:
    """The new derivation must not have smuggled an eth_research import into the
    stdlib-only tool — that would collapse it into the package it shadows."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib.util, sys, json;"
            f"spec = importlib.util.spec_from_file_location('t', {str(INDEPENDENT_TOOL)!r});"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
            "print(json.dumps([n for n in sys.modules if n.split('.')[0] == 'eth_research']))",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    assert json.loads(proc.stdout.strip()) == []


def test_acceptance_directory_layout_is_unchanged_by_this_module() -> None:
    """Guards the constant this module's callers depend on."""
    assert ACCEPTANCES_ROOT == "research/m3e/acceptances"
