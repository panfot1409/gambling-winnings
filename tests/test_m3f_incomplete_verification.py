"""A verifier must never report success for work it did not do (H3).

``tools/m3f_independent_verify.py`` ran the git-object half of its
acceptance-chain check only ``if (root / ".git").exists()``. On a tree without
``.git`` — an export, a tarball, a packaging artifact — it silently dropped that
half and still printed ``OK: 9 checks, 0 failures`` and exited 0.

That is the same defect class the whole M3E/M3F verification stack exists to
catch, turned on the verifier itself: ROOT-01..03, GIT-04, GIT-05, PROV-01 and
PROV-03 were not checked, and nothing in the output said so.

The tests below pin both halves of the fix. The load-bearing one is
``test_a_tree_without_git_is_incomplete_not_ok``: if it ever passes with
``ok=True``, the silent skip is back.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "tools/m3f_independent_verify.py"

#: Invariants that are verifiable only against git objects. If the tool cannot
#: reach them it must say which ones it skipped, by name.
_GIT_BOUND_INVARIANTS = ("ROOT-01..03", "GIT-04", "GIT-05", "PROV-01", "PROV-03")


def _run(root: Path) -> tuple[int, dict[str, object]]:
    result = subprocess.run(
        [sys.executable, str(TOOL), "--repo-root", str(root), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, json.loads(result.stdout)


@pytest.fixture(scope="module")
def exported_without_git(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A faithful copy of the committed tree with no ``.git`` directory."""
    target = tmp_path_factory.mktemp("export_no_git")
    archive = subprocess.run(
        ["git", "archive", "HEAD"], cwd=REPO_ROOT, capture_output=True, check=True
    )
    subprocess.run(["tar", "-x", "-C", str(target)], input=archive.stdout, check=True)
    assert not (target / ".git").exists()
    assert (target / "research/m3e/acceptance_registry.jsonl").is_file()
    return target


def test_the_real_repository_verifies_completely() -> None:
    """The control: with .git present nothing is skipped, so 'ok' means something."""
    code, payload = _run(REPO_ROOT)
    assert payload["failures"] == []
    assert payload["skipped"] == []
    assert payload["complete"] is True
    assert payload["ok"] is True
    assert code == 0


def test_a_tree_without_git_is_incomplete_not_ok(exported_without_git: Path) -> None:
    """The regression. Pre-fix this returned ok=True and exit 0."""
    code, payload = _run(exported_without_git)
    assert payload["failures"] == [], "the export should not FAIL, it should be INCOMPLETE"
    assert payload["complete"] is False
    assert payload["ok"] is False, (
        "a run that skipped its git-object binding reported ok=True — "
        "the H3 silent-skip defect has returned"
    )
    assert code == 1


def test_the_skips_name_the_invariants_that_went_unverified(
    exported_without_git: Path,
) -> None:
    """An incomplete verdict is only useful if it says what is missing."""
    _, payload = _run(exported_without_git)
    skipped = payload["skipped"]
    assert isinstance(skipped, list)
    assert skipped, "no skip was recorded despite .git being absent"
    joined = " ".join(str(s) for s in skipped)
    missing = [name for name in _GIT_BOUND_INVARIANTS if name not in joined]
    assert not missing, f"skips do not name the unverified invariants: {missing}"


def test_a_skip_is_never_counted_as_a_passed_check(exported_without_git: Path) -> None:
    """Skips must not leak into ``checks``, or they read as work completed."""
    _, payload = _run(exported_without_git)
    checks = payload["checks"]
    skipped = payload["skipped"]
    assert isinstance(checks, list)
    assert isinstance(skipped, list)
    skipped_names = {str(entry).split(":", 1)[0] for entry in skipped}
    assert not (skipped_names & set(map(str, checks)))
