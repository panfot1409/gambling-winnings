"""Static security checks on the GitHub Actions workflows.

The write-capable, Coinbase-contacting acquisition workflow is **retired**:
the canonical dataset is frozen, provenance-bound, and independently
replayable, so the frozen branch must not retain a dormant data-overwrite
machine. These tests prove that at HEAD no workflow can write repository
contents or contact Coinbase, every action stays SHA-pinned, and the
surviving read-only workflows (CI and replay) keep least privilege. Any
future acquisition must arrive as a new, separately reviewed workflow
commit. Text/regex based, so no YAML dependency is added.
"""

from __future__ import annotations

import re
from pathlib import Path

import eth_research

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"

# Only the uv installer host may appear, and only in read-only workflows.
ALLOWED_HOSTS = {"astral.sh"}
_URL_RE = re.compile(r"https://([A-Za-z0-9.\-]+)")
_USES_RE = re.compile(r"uses:\s*([^\s#]+)")
_SHA_PIN_RE = re.compile(r"^[^@]+@[0-9a-f]{40}$")
# A Coinbase *host in a URL* (a network contact), not the word in a comment.
_COINBASE_HOST_RE = re.compile(r"https?://[^\s\"']*coinbase", re.IGNORECASE)


def _all_workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


class TestAcquisitionWorkflowRetired:
    def test_write_capable_acquisition_workflow_is_removed(self) -> None:
        assert not (WORKFLOWS / "m2b-acquire.yml").exists()

    def test_push_bootstrap_trigger_is_removed(self) -> None:
        assert not (REPO_ROOT / "research/m2b/acquire.trigger").exists()

    def test_no_workflow_can_write_contents(self) -> None:
        for path in _all_workflow_files():
            text = path.read_text(encoding="utf-8")
            assert "contents: write" not in text, f"{path.name} still grants contents: write"
            assert "contents:write" not in text

    def test_no_workflow_contacts_coinbase(self) -> None:
        for path in _all_workflow_files():
            assert not _COINBASE_HOST_RE.search(path.read_text(encoding="utf-8")), (
                f"{path.name} still contacts a Coinbase host"
            )


class TestNetworkBoundary:
    def test_only_allowlisted_hosts_across_all_workflows(self) -> None:
        for path in _all_workflow_files():
            hosts = set(_URL_RE.findall(path.read_text(encoding="utf-8")))
            unexpected = hosts - ALLOWED_HOSTS
            assert not unexpected, f"{path.name} references unexpected hosts: {unexpected}"


class TestActionPinning:
    def test_every_action_is_pinned_by_full_sha(self) -> None:
        for path in _all_workflow_files():
            for ref in _USES_RE.findall(path.read_text(encoding="utf-8")):
                assert _SHA_PIN_RE.match(ref), f"{path.name}: {ref} is not pinned to a 40-hex SHA"

    def test_no_floating_tags(self) -> None:
        for path in _all_workflow_files():
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"uses:\s*\S+@(v?\d+(\.\d+)*|main|master)\s*$", text, re.MULTILINE)


class TestLeastPrivilege:
    def test_no_pull_request_write_workflows(self) -> None:
        # Redundant with the no-write proof, but explicit: no PR-reachable write.
        for path in _all_workflow_files():
            text = path.read_text(encoding="utf-8")
            if "contents: write" in text:
                assert "pull_request" not in text

    def test_no_id_token_permission(self) -> None:
        for path in _all_workflow_files():
            assert "id-token" not in path.read_text(encoding="utf-8")


class TestSurvivingWorkflowsPinned:
    def test_ci_checkout_pinned(self) -> None:
        assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in CI.read_text(
            encoding="utf-8"
        )

    def test_ci_default_permissions_read(self) -> None:
        assert re.search(
            r"^permissions:\n\s+contents:\s*read\b", CI.read_text(encoding="utf-8"), re.MULTILINE
        )
