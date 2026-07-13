"""Static security checks on the GitHub Actions workflows.

Every write-capable, Coinbase-contacting workflow is **retired**: the
original acquisition workflow (which produced the frozen canonical
attempt) and the temporary one-shot audit reacquisition workflow (which
produced attempt ``coinbase-eth-usd-audit-002`` in run 29206830064 and
was removed immediately after its single successful run). The canonical
dataset is frozen, dossier-bound, independently reacquired with a
canonical content match, and replayable offline, so the frozen branch
must not retain any dormant data-overwrite machine. These tests prove
that at HEAD no workflow can write repository contents or contact
Coinbase, every action stays SHA-pinned, and the surviving read-only
workflows (CI and replay) keep least privilege. Any future acquisition
must arrive as a new, separately reviewed workflow commit. Text/regex
based, so no YAML dependency is added.
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


class TestAcquisitionWorkflowsRetired:
    def test_original_acquisition_workflow_is_removed(self) -> None:
        assert not (WORKFLOWS / "m2b-acquire.yml").exists()

    def test_original_push_bootstrap_trigger_is_removed(self) -> None:
        assert not (REPO_ROOT / "research/m2b/acquire.trigger").exists()

    def test_audit_reacquisition_workflow_is_removed(self) -> None:
        assert not (WORKFLOWS / "m2b-audit-reacquire.yml").exists()

    def test_audit_push_bootstrap_trigger_is_removed(self) -> None:
        assert not (REPO_ROOT / "research/m2b/audit_acquire.trigger").exists()

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


class TestSupplyChainHardening:
    """Closure R7: every supply-chain invariant achievable offline. The uv
    installer's SHA-256 cannot be pinned in this sandbox — outbound access to
    github.com and astral.sh is blocked by the environment egress policy (403),
    so a trusted SHA cannot be obtained and a guessed one must not be committed;
    that single residual is recorded as CI supply-chain debt in docs/M3A_BUG_LOG.md."""

    def test_no_secrets_are_referenced(self) -> None:
        for path in _all_workflow_files():
            assert "secrets." not in path.read_text(encoding="utf-8"), f"{path.name} uses a secret"

    def test_no_artifact_upload(self) -> None:
        # No workflow may upload artifacts (which could exfiltrate market data).
        for path in _all_workflow_files():
            assert "upload-artifact" not in path.read_text(encoding="utf-8")

    def test_uv_installer_is_version_pinned(self) -> None:
        # The one downloaded installer must target the exact pinned uv version,
        # never a floating "latest"/unversioned URL.
        for path in _all_workflow_files():
            text = path.read_text(encoding="utf-8")
            for match in re.findall(r"astral\.sh/uv/([^/\s]+)/install\.sh", text):
                assert match == "0.8.17", f"{path.name}: uv installer version {match} is not pinned"

    def test_m3a_replay_asserts_both_ledgers_byte_empty(self) -> None:
        text = (WORKFLOWS / "m3a-replay.yml").read_text(encoding="utf-8")
        assert "development_gate_access.jsonl" in text or "GATE_LEDGER" in text
        assert "test_evaluations.jsonl" in text or "HOLDOUT_LEDGER" in text
        assert text.count("byte-empty") >= 2  # before and after

    def test_only_the_pinned_uv_host_is_downloaded(self) -> None:
        # Downloads (curl/wget) may only target the allowlisted uv installer host.
        for path in _all_workflow_files():
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if "curl" in line or "wget" in line:
                    hosts = set(_URL_RE.findall(line))
                    bad = hosts - ALLOWED_HOSTS
                    assert not bad, f"{path.name}: download from disallowed host {bad}"
