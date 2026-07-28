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

import hashlib
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
    assert "the on: block is not exactly" in found


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
    assert "the on: block is not exactly" in _violations(live)


def test_removing_one_jobs_gate_fails() -> None:
    mutated = _workflow().replace(RUNNER_A_GATE, "", 1)
    assert mutated != _workflow(), "mutation did not apply"
    found = _violations(mutated)
    assert "expected at least 5 active gate steps, found 4" in found
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
    assert "active gate steps" not in found
    assert "runner_a reaches 'tools/m3e_fetch_window.sh' before the gate" in found


def test_removing_workflow_dispatch_is_also_reported() -> None:
    """Containment suspends the schedule; it does not delete the mechanism."""
    mutated = _workflow().replace("on:\n  workflow_dispatch:", "on:\n  push:\n    branches: [x]")
    assert "the on: block is not exactly" in _violations(mutated)


NEW_UNGATED_JOB = """
  runner_c:
    needs: [gate_and_plan]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
      - name: Fetch the window on a third runner
        run: bash tools/m3e_fetch_window.sh "$RUNNER_TEMP/plan" "$RUNNER_TEMP/staging" c
"""


def test_adding_a_new_ungated_job_fails() -> None:
    """The bypass a fixed job list cannot see.

    Checking only the four (now five) jobs named in ``GUARDED_JOBS`` is a blacklist:
    a reviewer reading the diff sees a new job that looks like its gated siblings,
    and every existing assertion still passes. The rule is therefore stated over
    *every* job that obtains the repository.
    """
    mutated = _workflow() + NEW_UNGATED_JOB
    found = _violations(mutated)
    assert "job runner_c checks out the repository but has no containment gate" in found


def test_a_new_job_that_gates_is_accepted() -> None:
    """The paired control: the rule bans ungated jobs, not new jobs."""
    gated = NEW_UNGATED_JOB.replace(
        "      - name: Fetch the window on a third runner",
        f"      - name: V2F-R containment gate (fail-closed)\n        {GATE_STEP}\n"
        "      - name: Fetch the window on a third runner",
    )
    assert containment_violations(_workflow() + gated) == []


def test_a_new_job_whose_gate_is_inert_fails() -> None:
    """Satisfying the checkout rule with a gate that cannot refuse is not gating.

    Pairs with the accepted-new-job control above: the checkout rule alone would be
    satisfied by any job containing the gate *text*, so step integrity has to apply to
    jobs that did not exist when the rule was written.
    """
    inert = NEW_UNGATED_JOB.replace(
        "      - name: Fetch the window on a third runner",
        "      - name: V2F-R containment gate (fail-closed)\n"
        "        continue-on-error: true\n"
        f"        {GATE_STEP}\n"
        "      - name: Fetch the window on a third runner",
    )
    found = _violations(_workflow() + inert)
    assert "runner_c gate step carries ['continue-on-error: true']" in found
    assert "an error tolerance is not a gate" in found


def test_removing_the_pr_opening_gate_fails() -> None:
    """The job that opens the PR holds ``pull-requests: write`` and must gate too."""
    text = _workflow()
    pr_gate = (
        "      - name: V2F-R containment gate (fail-closed, before any PR is opened)\n"
        f"        {GATE_STEP}\n"
    )
    assert pr_gate in text, "the open_draft_pr gate is missing from the committed workflow"
    found = _violations(text.replace(pr_gate, "", 1))
    assert "open_draft_pr has no containment gate" in found
    assert "job open_draft_pr checks out the repository but has no containment gate" in found


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


def test_a_duplicate_key_does_not_open_the_visibility_gate(tmp_path: Path) -> None:
    """The exact bypass that opened the containment gate, re-run against this reader.

    ``json.loads`` keeps the *last* of duplicate keys, so a record that reads
    ``"observed_private": false`` on the line a human reviews parses as ``true``.
    """
    path = tmp_path / VISIBILITY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    honest = json.dumps(_base_observation())
    attack = honest.replace(
        '"observed_private": true',
        '"observed_private": false, "observed_private": true',
    )
    assert attack != honest, "mutation did not apply"
    path.write_text(attack, encoding="utf-8")
    assert derive_paper_readiness(tmp_path).gates["repository_private"] is False


def test_a_symlinked_observation_is_not_a_committed_record(tmp_path: Path) -> None:
    """A governed artifact is bytes in the tree, not a pointer to bytes elsewhere."""
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(json.dumps(_base_observation()), encoding="utf-8")

    tree = tmp_path / "tree"
    (tree / VISIBILITY_REL).parent.mkdir(parents=True, exist_ok=True)
    (tree / VISIBILITY_REL).symlink_to(elsewhere)

    assert (tree / VISIBILITY_REL).is_file(), "control: the symlink resolves to a real file"
    assert derive_paper_readiness(tree).gates["repository_private"] is False


def test_an_unparseable_observed_at_keeps_readiness_false(tmp_path: Path) -> None:
    """``observed_at`` is the freshness claim, so it must be an instant, not a word."""
    for stamp in ("soon", "", "2026-13-45T99:99:99Z", "yesterday"):
        _write_observation(tmp_path, _base_observation() | {"observed_at": stamp})
        assert derive_paper_readiness(tmp_path).gates["repository_private"] is False, stamp


def test_a_wrong_schema_version_keeps_readiness_false(tmp_path: Path) -> None:
    for version in (2, 0, "1", None):
        _write_observation(tmp_path, _base_observation() | {"schema_version": version})
        assert derive_paper_readiness(tmp_path).gates["repository_private"] is False, version


def test_a_corrupt_paper_trading_record_still_reads_as_trading(tmp_path: Path) -> None:
    """The one gate whose safe direction is inverted, so its reader is deliberately weaker.

    Presence of a paper-trading record makes ``paper_trading_active`` true. Reading it
    strictly would mean a malformed or symlinked record derived *false* — corrupting
    the ledger would be a way to report "not trading". Presence alone therefore counts.
    """
    record = tmp_path / "governance/v2/paper_trading_record.json"
    record.parent.mkdir(parents=True, exist_ok=True)

    record.write_text("{not json at all", encoding="utf-8")
    assert derive_paper_readiness(tmp_path).paper_trading_active is True

    record.unlink()
    record.symlink_to(tmp_path / "nowhere.json")
    assert not record.exists(), "control: a broken symlink resolves to nothing"
    assert derive_paper_readiness(tmp_path).paper_trading_active is True

    record.unlink()
    assert derive_paper_readiness(tmp_path).paper_trading_active is False


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


# --- enforcement scripts are pinned ----------------------------------------


def test_the_enforcement_scripts_are_hash_pinned() -> None:
    """The scripts that enforce containment must not be silently editable.

    The governed inventory walks only ``governance/`` and ``release/``, so nothing
    under ``tools/`` carries a hash — an auditor showed that inserting a
    context-keyed escape hatch into the gate script passes the gate's own test
    suite and trips no governance check. The scripts are therefore pinned inside
    the containment record, which is itself in ``governed_artifacts``: editing a
    script fails this test, and updating the pin changes the record's hash and
    fails ``fable5 verify`` until the inventory is rebuilt.
    """
    record = json.loads((REPO_ROOT / "governance/v2f/containment.json").read_text())
    pinned = record["enforcement_scripts_sha256"]
    assert set(pinned) == {"tools/v2f_containment_gate.py", "tools/m3e_fetch_window.sh"}
    for relpath, expected in pinned.items():
        live = hashlib.sha256((REPO_ROOT / relpath).read_bytes()).hexdigest()
        assert live == expected, f"{relpath} drifted from its pin in the containment record"
