"""``tools/m3f_independent_verify.py`` must confine every path component, not just the last.

The tool's own docstring promises it is a *separate code path* from the packaged verifiers, so
that "if the two verifiers ever disagree, that disagreement is itself the finding". A backstop
that is weaker than the thing it backstops cannot deliver on that. Two ways it was weaker:

* ``_read_bytes`` checked ``path.is_symlink()``, which tests the **final component only**. Its
  companion resolved-inside-root check caught symlinks pointing *outside* the repository, so the
  surviving gap was narrow and easy to miss: an intermediate directory symlink whose target was
  *inside* the root passed silently, and the tool read and certified the redirected bytes.
* ``_v2d_anchor_active`` did not call ``_read_bytes`` at all, so it had **neither** guard. That
  read is the more dangerous of the two, because an active V2D anchor is a *relaxation* — it
  disables the zero-proposal check, whitelists a workflow write permission, and loosens the
  freeze-catalog check from exact-hash to append-only.

Every group has a passing control. A confinement helper that refuses everything would satisfy
each negative assertion below while making the tool useless, and the pristine repository check
at the end is what rules that out.

Loaded by path, not imported: ``tools/`` is not a package, and the tool must not be importable
as one — its independence rests on importing nothing of ours.
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "m3f_independent_verify.py"


def _load_tool() -> Any:
    spec = importlib.util.spec_from_file_location("m3f_independent_verify_under_test", TOOL_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOOL = _load_tool()


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    """A scratch tree with a real file and a shadow file holding distinguishable bytes."""
    root = tmp_path / "root"
    (root / "real").mkdir(parents=True)
    (root / "real" / "data.json").write_text('{"v": "REAL"}\n', encoding="utf-8")
    (root / "shadow").mkdir()
    (root / "shadow" / "data.json").write_text('{"v": "SHADOW"}\n', encoding="utf-8")
    return root


# --- controls: the legitimate path must still work ------------------------------------------


def test_control_a_plain_file_still_reads(fixture_root: Path) -> None:
    assert TOOL._read_bytes(fixture_root, "real/data.json").decode().strip() == '{"v": "REAL"}'


def test_control_the_real_repository_still_verifies() -> None:
    """The strongest control: the tool must still pass on the actual tree.

    Without this, a confinement helper that refused every path would pass every test below.
    """
    result = TOOL.verify(REPO_ROOT)
    assert result["ok"] is True, result.get("failures")
    assert result["failures"] == []
    assert len(result["checks"]) >= 8


# --- the final-component gap that already worked --------------------------------------------


def test_a_final_component_symlink_is_refused(fixture_root: Path) -> None:
    (fixture_root / "real" / "link.json").symlink_to(fixture_root / "shadow" / "data.json")
    with pytest.raises(TOOL.IndependentVerifyError, match="symlink component"):
        TOOL._read_bytes(fixture_root, "real/link.json")


# --- the gap that did not: an intermediate symlink whose target is INSIDE the root -----------


def test_an_intermediate_directory_symlink_inside_the_root_is_refused(fixture_root: Path) -> None:
    """The exact reproduction. Pre-fix this returned the shadow bytes and reported ok.

    In-root is the load-bearing detail: an intermediate symlink pointing *outside* was already
    caught by the resolved-inside-root check, so testing only that variant would have passed
    against the defective code and proved nothing.
    """
    (fixture_root / "real").rename(fixture_root / "real_actual")
    (fixture_root / "real").symlink_to(fixture_root / "shadow")

    # Guard the guard: prove the redirect is real, so a refusal below is not a missing file.
    assert (fixture_root / "real" / "data.json").read_text().strip() == '{"v": "SHADOW"}'

    with pytest.raises(TOOL.IndependentVerifyError, match="symlink component"):
        TOOL._read_bytes(fixture_root, "real/data.json")


def test_an_intermediate_directory_symlink_outside_the_root_is_refused(
    fixture_root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "data.json").write_text('{"v": "OUTSIDE"}\n', encoding="utf-8")
    (fixture_root / "real").rename(fixture_root / "real_actual")
    (fixture_root / "real").symlink_to(outside)
    with pytest.raises(TOOL.IndependentVerifyError):
        TOOL._read_bytes(fixture_root, "real/data.json")


@pytest.mark.parametrize(
    "relpath",
    ["/etc/passwd", "../escape.json", "real/../shadow/data.json", "real/./data.json", "", ".."],
    ids=["absolute", "parent-first", "parent-mid", "dot-mid", "empty", "bare-parent"],
)
def test_traversal_shaped_relpaths_are_refused(fixture_root: Path, relpath: str) -> None:
    with pytest.raises(TOOL.IndependentVerifyError):
        TOOL._read_bytes(fixture_root, relpath)


# --- the V2D anchor, which had no confinement at all ----------------------------------------


def _anchor_root(tmp_path: Path) -> Path:
    root = tmp_path / "anchor_root"
    (root / "governance").mkdir(parents=True)
    return root


def test_control_an_absent_anchor_is_inactive_not_an_error(tmp_path: Path) -> None:
    """Absent must mean inactive, quietly. If this raised, the refusals below prove nothing."""
    root = _anchor_root(tmp_path)
    (root / "governance" / "v2d").mkdir()
    assert TOOL._v2d_anchor_active(root) is False


def test_the_anchor_directory_cannot_be_a_symlink_out_of_the_repository(tmp_path: Path) -> None:
    """An active anchor grants three relaxations, so its path must be the governed one.

    Asserts the *reason*: pre-fix this raised "v2d anchor kind/schema is unexpected" — a
    complaint about the outside file's **contents**, which is itself the proof that the tool had
    already read bytes from outside the repository. Matching on "symlink component" is what
    distinguishes a path refusal from a content refusal.
    """
    root = _anchor_root(tmp_path)
    outside = tmp_path / "outside_v2d"
    outside.mkdir()
    (outside / "prospective_activation.json").write_text('{"kind": "forged"}\n', encoding="utf-8")
    (root / "governance" / "v2d").symlink_to(outside)

    with pytest.raises(TOOL.IndependentVerifyError, match="symlink component"):
        TOOL._v2d_anchor_active(root)


def test_the_anchor_file_itself_cannot_be_a_symlink(tmp_path: Path) -> None:
    root = _anchor_root(tmp_path)
    (root / "governance" / "v2d").mkdir()
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text('{"kind": "forged"}\n', encoding="utf-8")
    (root / "governance" / "v2d" / "prospective_activation.json").symlink_to(elsewhere)

    with pytest.raises(TOOL.IndependentVerifyError, match="symlink component"):
        TOOL._v2d_anchor_active(root)


# --- parity with the packaged guard the tool deliberately does not import -------------------


@pytest.mark.parametrize(
    "make_attack",
    [
        pytest.param("final_symlink", id="final-component-symlink"),
        pytest.param("mid_symlink_inside", id="intermediate-symlink-in-root"),
        pytest.param("mid_symlink_outside", id="intermediate-symlink-out-of-root"),
    ],
)
def test_the_two_verifiers_agree_on_every_attack(
    fixture_root: Path, tmp_path: Path, make_attack: str
) -> None:
    """Both must refuse. Disagreement is the finding the tool's docstring promises to surface.

    The tool reimplements confinement rather than importing ``safe_repo_path`` — importing it
    would make a common-mode defect invisible, which is the whole reason this tool exists. The
    cost of reimplementing is drift, and this test is what pays it.
    """
    from eth_research.m3f.validation import M3FValidationError, safe_repo_path

    if make_attack == "final_symlink":
        (fixture_root / "real" / "target.json").symlink_to(fixture_root / "shadow" / "data.json")
        relpath = "real/target.json"
    else:
        target = fixture_root / "shadow"
        if make_attack == "mid_symlink_outside":
            target = tmp_path / "outside_parity"
            target.mkdir()
            (target / "data.json").write_text("{}\n", encoding="utf-8")
        (fixture_root / "real").rename(fixture_root / "real_actual")
        (fixture_root / "real").symlink_to(target)
        relpath = "real/data.json"

    with pytest.raises(TOOL.IndependentVerifyError):
        TOOL._read_bytes(fixture_root, relpath)
    with pytest.raises(M3FValidationError):
        safe_repo_path(fixture_root, relpath, "parity")


def test_control_both_verifiers_accept_the_same_clean_path(fixture_root: Path) -> None:
    """The parity control: they must agree on yes as well as on no."""
    from eth_research.m3f.validation import safe_repo_path

    assert TOOL._read_bytes(fixture_root, "real/data.json")
    assert safe_repo_path(fixture_root, "real/data.json", "parity")


# --- end to end: the whole tool, not just the helper ----------------------------------------


def test_the_whole_tool_refuses_a_repository_with_a_redirected_governed_directory(
    tmp_path: Path,
) -> None:
    """A helper-level refusal is not proof the tool is wired to it.

    Copies the real governed inputs into a scratch tree, confirms the tool passes there, then
    redirects one governed directory through an in-root symlink and confirms it stops passing.
    """
    scratch = tmp_path / "repo"
    for relpath in ("research", "governance", ".github"):
        src = REPO_ROOT / relpath
        if src.exists():
            shutil.copytree(src, scratch / relpath, symlinks=False)

    baseline = TOOL.verify(scratch)
    assert baseline["ok"] is True, f"scratch copy must pass first: {baseline.get('failures')}"

    shadow = scratch / "shadow_m2b"
    shadow.mkdir()
    (shadow / "test_evaluations.jsonl").write_text("not empty\n", encoding="utf-8")
    shutil.rmtree(scratch / "research" / "m2b")
    (scratch / "research" / "m2b").symlink_to(shadow)

    redirected = TOOL.verify(scratch)
    assert redirected["ok"] is False, "the tool certified bytes reached through a symlink"
    assert any("symlink component" in str(f) for f in redirected["failures"]), (
        f"refused, but not for the path reason: {redirected['failures']}"
    )
