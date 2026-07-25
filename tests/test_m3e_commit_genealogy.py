"""Adversarial matrix for the commit-genealogy model (auditor B, finding A-4).

Every probe asserts the STABLE CODE that refused it, not merely that something
raised. A probe that fails on the wrong code has not exercised the invariant it
claims to — that is the mistake recorded as process defect P-2 in the bug log,
and asserting codes is the mechanical guard against repeating it.

All mutation happens in disposable clones or by patching module constants inside
the test process. The shared worktree is never modified (see CONTRIBUTING,
"Audit and review boundaries").
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from eth_research.m3e import commit_genealogy as cg
from eth_research.m3e.commit_genealogy import (
    CHECK_IDS,
    CommitGenealogyError,
    verify_commit_genealogy,
)
from eth_research.m3e.proposal_authority import (
    EXPECTED_PROPOSAL_HEAD,
    TRUSTED_BASELINE_COMMIT,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / ".git").exists(), reason="genealogy needs a git repository"
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture(scope="module")
def clone(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A full disposable clone, shared by the read-only probes."""
    dest = tmp_path_factory.mktemp("genealogy") / "repo"
    subprocess.run(["git", "clone", "--quiet", "--shared", str(REPO_ROOT), str(dest)], check=True)
    return dest


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Repoint the module's source pins, as a forged pin set would."""
    return monkeypatch


# --------------------------------------------------------------------------
# Control
# --------------------------------------------------------------------------


def test_control_the_real_repository_passes_all_fifteen() -> None:
    """Without this, every 'CAUGHT' below could just mean the model never passes."""
    passed = verify_commit_genealogy(REPO_ROOT)
    assert [c.code for c in passed] == [code for code, _ in CHECK_IDS]


def test_every_declared_check_id_is_unique_and_ordered() -> None:
    codes = [code for code, _ in CHECK_IDS]
    assert codes == sorted(codes)
    assert len(set(codes)) == len(codes) == 15


# --------------------------------------------------------------------------
# Malformed and misdirecting identities (GEN-05 / GEN-08)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attack", "forged"),
    [
        ("uppercase id", TRUSTED_BASELINE_COMMIT.upper()),
        ("abbreviated id", TRUSTED_BASELINE_COMMIT[:12]),
        ("caret revision syntax", TRUSTED_BASELINE_COMMIT + "^"),
        ("tilde revision syntax", TRUSTED_BASELINE_COMMIT + "~1"),
        ("path revision syntax", TRUSTED_BASELINE_COMMIT + ":research"),
        ("reflog revision syntax", TRUSTED_BASELINE_COMMIT + "@{0}"),
        ("branch name instead of an id", "main"),
    ],
)
def test_baseline_id_must_be_a_literal_full_object_id(
    attack: str, forged: str, patched: pytest.MonkeyPatch
) -> None:
    """git resolves `<sha>^`, `<sha>:path` and `<sha>@{0}` to *different* objects,
    so accepting revision syntax would let a pin designate something it does not
    name."""
    patched.setattr(cg, "TRUSTED_BASELINE_COMMIT", forged)
    with pytest.raises(CommitGenealogyError) as excinfo:
        verify_commit_genealogy(REPO_ROOT)
    assert excinfo.value.code == "GEN-05", attack


def test_proposal_head_id_must_be_a_literal_full_object_id(patched: pytest.MonkeyPatch) -> None:
    patched.setattr(cg, "EXPECTED_PROPOSAL_HEAD", EXPECTED_PROPOSAL_HEAD + "^")
    with pytest.raises(CommitGenealogyError) as excinfo:
        verify_commit_genealogy(REPO_ROOT)
    assert excinfo.value.code == "GEN-08"


# --------------------------------------------------------------------------
# Absent and wrong-typed objects (GEN-06 / GEN-09)
# --------------------------------------------------------------------------


def test_nonexistent_baseline_object_is_refused(patched: pytest.MonkeyPatch) -> None:
    """A well-formed id that names nothing used to pass a format-only check."""
    patched.setattr(cg, "TRUSTED_BASELINE_COMMIT", "f" * 40)
    with pytest.raises(CommitGenealogyError) as excinfo:
        verify_commit_genealogy(REPO_ROOT)
    assert excinfo.value.code == "GEN-06"
    assert "fetch" in str(excinfo.value)


@pytest.mark.parametrize("kind", ["tree", "blob"])
def test_baseline_pointing_at_a_non_commit_object_is_refused(
    kind: str, patched: pytest.MonkeyPatch
) -> None:
    if kind == "tree":
        oid = _git(REPO_ROOT, "rev-parse", f"{TRUSTED_BASELINE_COMMIT}^{{tree}}")
    else:
        oid = _git(REPO_ROOT, "rev-parse", f"{TRUSTED_BASELINE_COMMIT}:pyproject.toml")
    patched.setattr(cg, "TRUSTED_BASELINE_COMMIT", oid)
    with pytest.raises(CommitGenealogyError) as excinfo:
        verify_commit_genealogy(REPO_ROOT)
    assert excinfo.value.code == "GEN-06"
    assert kind in str(excinfo.value)


def test_proposal_head_pointing_at_a_tree_is_refused(patched: pytest.MonkeyPatch) -> None:
    oid = _git(REPO_ROOT, "rev-parse", f"{EXPECTED_PROPOSAL_HEAD}^{{tree}}")
    patched.setattr(cg, "EXPECTED_PROPOSAL_HEAD", oid)
    with pytest.raises(CommitGenealogyError) as excinfo:
        verify_commit_genealogy(REPO_ROOT)
    assert excinfo.value.code == "GEN-09"


# --------------------------------------------------------------------------
# Right id, wrong content (GEN-07 / GEN-10)
# --------------------------------------------------------------------------


def test_baseline_with_the_wrong_pinned_tree_is_refused(patched: pytest.MonkeyPatch) -> None:
    patched.setattr(cg, "TRUSTED_BASELINE_TREE", "0" * 40)
    with pytest.raises(CommitGenealogyError) as excinfo:
        verify_commit_genealogy(REPO_ROOT)
    assert excinfo.value.code == "GEN-07"


def test_proposal_head_with_the_wrong_pinned_tree_is_refused(patched: pytest.MonkeyPatch) -> None:
    patched.setattr(cg, "EXPECTED_PROPOSAL_TREE", "0" * 40)
    with pytest.raises(CommitGenealogyError) as excinfo:
        verify_commit_genealogy(REPO_ROOT)
    assert excinfo.value.code == "GEN-10"


# --------------------------------------------------------------------------
# Parentage (GEN-13 / GEN-14)
# --------------------------------------------------------------------------


def test_a_merge_commit_as_the_proposal_head_is_refused(clone: Path) -> None:
    """A second parent would carry unrelated history into the accepted set."""
    merge = _git(clone, "rev-list", "--merges", "-n", "1", "HEAD")
    if not merge:
        pytest.skip("no merge commit reachable in this clone")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cg, "EXPECTED_PROPOSAL_HEAD", merge)
        mp.setattr(cg, "EXPECTED_PROPOSAL_TREE", _git(clone, "rev-parse", f"{merge}^{{tree}}"))
        with pytest.raises(CommitGenealogyError) as excinfo:
            verify_commit_genealogy(clone)
    assert excinfo.value.code == "GEN-13"


def test_a_root_commit_as_the_proposal_head_is_refused(clone: Path) -> None:
    """Measured: refused at GEN-11, not GEN-13.

    A root commit has no parents, so it cannot be a descendant of the baseline
    and the direction check fires first. The zero-parent branch of GEN-13 is
    therefore unreachable in practice — recorded here rather than dressed up as
    a GEN-13 catch it is not."""
    root_commit = _git(clone, "rev-list", "--max-parents=0", "-n", "1", "HEAD")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cg, "EXPECTED_PROPOSAL_HEAD", root_commit)
        mp.setattr(
            cg, "EXPECTED_PROPOSAL_TREE", _git(clone, "rev-parse", f"{root_commit}^{{tree}}")
        )
        with pytest.raises(CommitGenealogyError) as excinfo:
            verify_commit_genealogy(clone)
    assert excinfo.value.code == "GEN-11"


def test_a_different_single_parent_is_refused(patched: pytest.MonkeyPatch) -> None:
    grandparent = _git(REPO_ROOT, "rev-parse", f"{TRUSTED_BASELINE_COMMIT}^")
    patched.setattr(cg, "EXPECTED_PROPOSAL_PARENT", grandparent)
    with pytest.raises(CommitGenealogyError) as excinfo:
        verify_commit_genealogy(REPO_ROOT)
    assert excinfo.value.code == "GEN-14"


# --------------------------------------------------------------------------
# Direction (GEN-11 / GEN-12)
# --------------------------------------------------------------------------


def test_swapping_baseline_and_head_is_refused(patched: pytest.MonkeyPatch) -> None:
    """An audit passed a descendant where an ancestor was required and it went
    unnoticed, so the direction is asserted rather than assumed.

    With the direction checks evaluated first, the swap is refused by GEN-11
    itself: the forged "baseline" is not an ancestor of the forged "head"."""
    patched.setattr(cg, "TRUSTED_BASELINE_COMMIT", EXPECTED_PROPOSAL_HEAD)
    patched.setattr(
        cg,
        "TRUSTED_BASELINE_TREE",
        _git(REPO_ROOT, "rev-parse", f"{EXPECTED_PROPOSAL_HEAD}^{{tree}}"),
    )
    patched.setattr(cg, "EXPECTED_PROPOSAL_HEAD", TRUSTED_BASELINE_COMMIT)
    patched.setattr(
        cg,
        "EXPECTED_PROPOSAL_TREE",
        _git(REPO_ROOT, "rev-parse", f"{TRUSTED_BASELINE_COMMIT}^{{tree}}"),
    )
    with pytest.raises(CommitGenealogyError) as excinfo:
        verify_commit_genealogy(REPO_ROOT)
    assert excinfo.value.code == "GEN-11"


def test_a_self_referential_pin_cannot_satisfy_the_direction_check(
    patched: pytest.MonkeyPatch,
) -> None:
    """baseline == head makes 'is an ancestor of' trivially true in both
    directions. GEN-12 exists precisely so that symmetry is a failure — and it
    only gets the chance to fire because the direction checks run before
    parentage (which would otherwise reject the self-reference first, leaving
    GEN-12 unreachable and therefore vacuous)."""
    patched.setattr(cg, "TRUSTED_BASELINE_COMMIT", EXPECTED_PROPOSAL_HEAD)
    patched.setattr(cg, "EXPECTED_PROPOSAL_PARENT", EXPECTED_PROPOSAL_HEAD)
    patched.setattr(
        cg,
        "TRUSTED_BASELINE_TREE",
        _git(REPO_ROOT, "rev-parse", f"{EXPECTED_PROPOSAL_HEAD}^{{tree}}"),
    )
    with pytest.raises(CommitGenealogyError) as excinfo:
        verify_commit_genealogy(REPO_ROOT)
    assert excinfo.value.code == "GEN-12"


# --------------------------------------------------------------------------
# Verification target (GEN-15)
# --------------------------------------------------------------------------


def test_a_verification_commit_that_predates_the_proposal_is_refused() -> None:
    with pytest.raises(CommitGenealogyError) as excinfo:
        verify_commit_genealogy(REPO_ROOT, verification_commit=TRUSTED_BASELINE_COMMIT)
    assert excinfo.value.code == "GEN-15"


def test_a_verification_commit_naming_a_tree_is_refused() -> None:
    tree = _git(REPO_ROOT, "rev-parse", "HEAD^{tree}")
    with pytest.raises(CommitGenealogyError) as excinfo:
        verify_commit_genealogy(REPO_ROOT, verification_commit=tree)
    assert excinfo.value.code == "GEN-15"


# --------------------------------------------------------------------------
# Object substitution (GEN-03 / GEN-04) and truncated history (GEN-02)
# --------------------------------------------------------------------------


def test_a_graft_file_is_refused(clone: Path, tmp_path: Path) -> None:
    """Grafts fabricate parentage, so ancestry answers stop meaning anything."""
    work = tmp_path / "grafted"
    shutil.copytree(clone, work)
    grafts = work / ".git" / "info" / "grafts"
    grafts.parent.mkdir(parents=True, exist_ok=True)
    grafts.write_text(f"{EXPECTED_PROPOSAL_HEAD}\n")
    with pytest.raises(CommitGenealogyError) as excinfo:
        verify_commit_genealogy(work)
    assert excinfo.value.code == "GEN-03"


def test_a_replace_ref_over_a_pinned_object_is_refused(clone: Path, tmp_path: Path) -> None:
    """`git replace` substitutes object content wholesale for the same id — the
    one mechanism that would defeat every hash check below it."""
    work = tmp_path / "replaced"
    shutil.copytree(clone, work)
    other = _git(work, "rev-parse", f"{EXPECTED_PROPOSAL_HEAD}^")
    subprocess.run(
        ["git", "-C", str(work), "replace", "-f", EXPECTED_PROPOSAL_HEAD, other], check=True
    )
    with pytest.raises(CommitGenealogyError) as excinfo:
        verify_commit_genealogy(work)
    assert excinfo.value.code == "GEN-04"


def test_shallow_clone_fails_then_fetches_then_verifies(tmp_path: Path) -> None:
    """The three-step sequence the directive requires, in order.

    A shallow clone must not silently pass by having nothing to check: it fails
    closed, the operator fetches the missing history, and only then does the
    genealogy verify. This is the difference between "no evidence of tampering"
    and "evidence of no tampering"."""
    work = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", "--no-local", f"file://{REPO_ROOT}", str(work)],
        check=True,
    )

    # 1. shallow: refused, with the code that names truncated history.
    assert _git(work, "rev-parse", "--is-shallow-repository") == "true"
    with pytest.raises(CommitGenealogyError) as excinfo:
        verify_commit_genealogy(work)
    assert excinfo.value.code == "GEN-02"
    assert "unshallow" in str(excinfo.value)

    # 2. fetch the missing history.
    subprocess.run(["git", "-C", str(work), "fetch", "--quiet", "--unshallow"], check=True)
    assert _git(work, "rev-parse", "--is-shallow-repository") == "false"

    # 3. now it verifies, and every check actually ran.
    passed = verify_commit_genealogy(work)
    assert [c.code for c in passed] == [code for code, _ in CHECK_IDS]


def test_error_codes_are_stable_identifiers_not_free_text() -> None:
    """Codes are the contract these tests and any runbook depend on."""
    with pytest.raises(ValueError, match="unknown genealogy check code"):
        CommitGenealogyError("GEN-99", "not a real code")
    err = CommitGenealogyError("GEN-11", "example")
    assert err.code == "GEN-11"
    assert str(err).startswith("GEN-11: ")
