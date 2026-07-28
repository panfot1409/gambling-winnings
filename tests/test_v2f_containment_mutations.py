"""The containment mutations, each proven by execution.

A guard that has never refused anything is a comment. Every case below performs the
attack against real bytes and asserts the specific refusal, and each family is paired
with a control that passes, so a guard stuck permanently shut cannot pass for a guard
that works.

Two implementation notes, both learned by getting them wrong first:

* The workflow mutations drive ``containment_violations()`` directly rather than
  re-running the workflow-security test file in a mutated copy of the tree. That
  indirection does not work here: those tests resolve the repository root from the
  *installed* package, so a scratch copy is never the file under test and the mutation
  silently tests the pristine workflow.
* The visibility mutations build their trees from ``tmp_path`` rather than from
  ``git archive HEAD``. An archive of HEAD omits anything not yet committed, which
  would have quietly excluded the very containment files under test.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from eth_research.v2.fable5.paper_readiness import derive_paper_readiness

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path) -> ModuleType:
    """Load a sibling test module by file location.

    ``tests/`` is deliberately not a package, so ``from tests.x import y`` fails
    both ruff's import resolution and mypy's module mapping. This mirrors how the
    suite already loads ``tools/`` scripts.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_WORKFLOW_SECURITY = _load(
    "m3e_workflow_security", Path(__file__).with_name("test_m3e_workflow_security.py")
)
GATE_STEP: str = _WORKFLOW_SECURITY.GATE_STEP
containment_violations = _WORKFLOW_SECURITY.containment_violations

WORKFLOW = REPO_ROOT / ".github/workflows/m3e-prospective-update.yml"
VISIBILITY_REL = "governance/v2f/repository_visibility.json"

RUNNER_A_GATE = (
    "      - name: V2F-R containment gate (fail-closed, before this job's fetch)\n"
    f"        {GATE_STEP}\n"
)
RUNNER_A_FETCH = (
    '          bash tools/m3e_fetch_window.sh "$RUNNER_TEMP/plan" "$RUNNER_TEMP/staging" a\n'
)


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _violations(text: str) -> str:
    return " | ".join(containment_violations(text))


# --- workflow containment --------------------------------------------------


def test_control_the_committed_workflow_is_contained() -> None:
    """Without this, every refusal below could be a guard stuck shut."""
    assert containment_violations(_workflow()) == []


def test_restoring_the_cron_fails() -> None:
    mutated = _workflow().replace(
        "on:\n  workflow_dispatch:",
        'on:\n  schedule:\n    - cron: "17 2 * * 1"\n  workflow_dispatch:',
    )
    assert mutated != _workflow(), "mutation did not apply"
    found = _violations(mutated)
    assert "an active cron: directive is present" in found
    assert "an active schedule: trigger is present" in found


def test_commenting_the_cron_out_is_not_containment() -> None:
    """A commented cron reads as absent to a naive scan but is one edit from live.

    The check reads directives, so a comment is correctly NOT a violation — this
    pins that the *comment* form is what gets tolerated, never a live directive
    hiding behind indentation.
    """
    mutated = _workflow().replace(
        "on:\n  workflow_dispatch:",
        'on:\n  # schedule:\n  #   - cron: "17 2 * * 1"\n  workflow_dispatch:',
    )
    assert containment_violations(mutated) == []
    live = mutated.replace('  #   - cron: "17 2 * * 1"', '    - cron: "17 2 * * 1"')
    assert "an active cron: directive is present" in _violations(live)


def test_removing_one_jobs_gate_fails() -> None:
    mutated = _workflow().replace(RUNNER_A_GATE, "", 1)
    assert mutated != _workflow(), "mutation did not apply"
    found = _violations(mutated)
    assert "expected 4 gate steps, found 3" in found
    assert "runner_a has no containment gate" in found


def test_moving_a_gate_after_the_network_step_fails() -> None:
    """Order matters: a gate that runs after the fetch has contained nothing."""
    text = _workflow()
    assert RUNNER_A_GATE in text
    assert RUNNER_A_FETCH in text
    mutated = text.replace(RUNNER_A_GATE, "", 1).replace(
        RUNNER_A_FETCH, RUNNER_A_FETCH + RUNNER_A_GATE, 1
    )
    found = _violations(mutated)
    # The gate count is still 4 — this is purely an ordering defect, which is
    # exactly the failure a count-only check would miss.
    assert "expected 4 gate steps" not in found
    assert "runner_a reaches 'tools/m3e_fetch_window.sh' before the gate" in found


def test_removing_workflow_dispatch_is_also_reported() -> None:
    """Containment suspends the schedule; it does not delete the mechanism."""
    mutated = _workflow().replace("on:\n  workflow_dispatch:", "on:\n  push:\n    branches: [x]")
    assert "workflow_dispatch: was removed" in _violations(mutated)


# --- visibility surface ----------------------------------------------------


def _write_observation(root: Path, payload: dict[str, Any] | None) -> None:
    path = root / VISIBILITY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    if payload is None:
        if path.exists():
            path.unlink()
        return
    path.write_text(json.dumps(payload), encoding="utf-8")


def _base_observation() -> dict[str, Any]:
    return {
        "kind": "v2f_repository_visibility",
        "schema_version": 1,
        "repository": "panfot1409/gambling-winnings",
        "observed_private": True,
        "observed_visibility": "private",
        "observed_at": "2026-07-28T11:33:55Z",
        "observed_by": "test",
        "observed_via": "test",
    }


def test_control_a_private_observation_satisfies_the_visibility_gate(tmp_path: Path) -> None:
    _write_observation(tmp_path, _base_observation())
    assert derive_paper_readiness(tmp_path).gates["repository_private"] is True


def test_the_committed_observation_matches_the_committed_gate() -> None:
    observed = json.loads((REPO_ROOT / VISIBILITY_REL).read_text())
    expected = observed["observed_private"] is True and observed["observed_visibility"] == "private"
    assert derive_paper_readiness(REPO_ROOT).gates["repository_private"] is expected


def test_a_public_observation_keeps_readiness_false(tmp_path: Path) -> None:
    _write_observation(
        tmp_path,
        _base_observation() | {"observed_private": False, "observed_visibility": "public"},
    )
    state = derive_paper_readiness(tmp_path)
    assert state.gates["repository_private"] is False
    assert state.paper_activation_authorized is False


def test_unknown_or_malformed_visibility_keeps_readiness_false(tmp_path: Path) -> None:
    base = _base_observation()
    for label, broken in (
        ("unknown string", base | {"observed_visibility": "unknown"}),
        ("empty string", base | {"observed_visibility": ""}),
        ("visibility absent", {k: v for k, v in base.items() if k != "observed_visibility"}),
        ("private flag absent", {k: v for k, v in base.items() if k != "observed_private"}),
        ("truthy string not bool", base | {"observed_private": "true"}),
        ("half-updated record", base | {"observed_visibility": "public"}),
        ("wrong kind", base | {"kind": "something_else"}),
        ("other repository", base | {"repository": "someone-else/other-repo"}),
        ("unattributed", {k: v for k, v in base.items() if k != "observed_by"}),
    ):
        _write_observation(tmp_path, broken)
        assert derive_paper_readiness(tmp_path).gates["repository_private"] is False, label


def test_a_missing_observation_keeps_readiness_false(tmp_path: Path) -> None:
    _write_observation(tmp_path, None)
    assert derive_paper_readiness(tmp_path).gates["repository_private"] is False


def test_a_classifier_only_tree_is_not_private(tmp_path: Path) -> None:
    """The STOP-1 regression: the PyPI classifier must never imply visibility.

    ``Private :: Do Not Upload`` governs whether PyPI rejects an upload. It is retained
    as the packaging kill-switch (tests/test_public_publication_killswitch.py,
    tests/test_ga_metadata.py) and must stay there — but it says nothing about GitHub
    repository visibility, and the gate that keeps paper trading off a public
    repository must not consult it.
    """
    _write_observation(tmp_path, None)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nclassifiers = ["Private :: Do Not Upload"]\n', encoding="utf-8"
    )
    assert derive_paper_readiness(tmp_path).gates["repository_private"] is False


def test_the_classifier_remains_the_packaging_kill_switch() -> None:
    """Separation in both directions: packaging prohibition survives the fix."""
    assert "Private :: Do Not Upload" in (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
