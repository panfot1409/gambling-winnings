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
    """N10 (was R7): uv is installed from the hash-pinned PyPI wheel — no
    downloaded byte is piped to a shell, and the artifact digests are verified
    against ``ci/uv-requirements.txt`` before use."""

    def test_no_secrets_are_referenced(self) -> None:
        for path in _all_workflow_files():
            assert "secrets." not in path.read_text(encoding="utf-8"), f"{path.name} uses a secret"

    def test_no_artifact_upload(self) -> None:
        # No workflow may upload artifacts (which could exfiltrate market data).
        for path in _all_workflow_files():
            assert "upload-artifact" not in path.read_text(encoding="utf-8")

    def test_no_curl_or_wget_pipes_into_a_shell(self) -> None:
        # N10: no surviving workflow may pipe a downloaded installer into a shell.
        for path in _all_workflow_files():
            text = path.read_text(encoding="utf-8")
            assert "install.sh | sh" not in text
            assert "install.sh|sh" not in text
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if ("curl" in stripped or "wget" in stripped) and "|" in stripped:
                    raise AssertionError(f"{path.name}: a download is piped into a shell")

    def test_uv_is_installed_from_the_hash_pinned_pypi_wheel(self) -> None:
        pin = REPO_ROOT / "ci/uv-requirements.txt"
        text = pin.read_text(encoding="utf-8")
        assert "uv==0.8.17" in text
        assert "--hash=sha256:" in text
        # Every workflow that installs uv references the pinned, hash-checked file.
        for path in _all_workflow_files():
            wf = path.read_text(encoding="utf-8")
            if "Install uv" in wf:
                assert "ci/uv-requirements.txt" in wf, f"{path.name} does not use the uv pin"
                assert "--require-hashes" in wf, f"{path.name} does not require hashes"

    def test_m3a_replay_asserts_both_ledgers_byte_empty(self) -> None:
        text = (WORKFLOWS / "m3a-replay.yml").read_text(encoding="utf-8")
        assert "development_gate_access.jsonl" in text or "GATE_LEDGER" in text
        assert "test_evaluations.jsonl" in text or "HOLDOUT_LEDGER" in text
        assert text.count("byte-empty") >= 2  # before and after
