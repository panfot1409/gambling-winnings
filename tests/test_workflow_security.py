"""Static security checks on the GitHub Actions workflows.

TEMPORARY POSTURE (closure section H): exactly one narrowly scoped,
write-capable workflow — the one-shot independent integrity reacquisition
``m2b-audit-reacquire.yml`` (attempt ``coinbase-eth-usd-audit-002``) — is
present alongside the read-only CI and replay workflows. While it exists,
these tests assert every hardening control it claims instead of the plain
"no write-capable workflow" rule; the moment it is retired again this
module is restored to the strict form (no exceptions, no dormant write
machine). The original acquisition workflow and its trigger remain
retired throughout. Text/regex based, so no YAML dependency is added.
"""

from __future__ import annotations

import re
from pathlib import Path

import eth_research

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
AUDIT_WF = WORKFLOWS / "m2b-audit-reacquire.yml"

# Hosts allowed to appear as URLs per workflow file. The temporary audit
# workflow may name the one public Coinbase candles endpoint and the
# hash-pinned uv wheel on PyPI's file host; nothing else, nowhere else.
GLOBAL_ALLOWED_HOSTS = {"astral.sh"}
AUDIT_ALLOWED_HOSTS = {"files.pythonhosted.org", "api.exchange.coinbase.com"}
_URL_RE = re.compile(r"https://([A-Za-z0-9.\-]+)")
_USES_RE = re.compile(r"uses:\s*([^\s#]+)")
_SHA_PIN_RE = re.compile(r"^[^@]+@[0-9a-f]{40}$")
# A Coinbase *host in a URL* (a network contact), not the word in a comment.
_COINBASE_HOST_RE = re.compile(r"https?://[^\s\"']*coinbase", re.IGNORECASE)


def _all_workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


class TestOriginalAcquisitionStaysRetired:
    def test_write_capable_acquisition_workflow_is_removed(self) -> None:
        assert not (WORKFLOWS / "m2b-acquire.yml").exists()

    def test_original_push_bootstrap_trigger_is_removed(self) -> None:
        assert not (REPO_ROOT / "research/m2b/acquire.trigger").exists()


class TestSingleTemporaryWriteException:
    def test_only_the_audit_workflow_can_write_contents(self) -> None:
        for path in _all_workflow_files():
            text = path.read_text(encoding="utf-8")
            if path == AUDIT_WF:
                continue
            assert "contents: write" not in text, f"{path.name} grants contents: write"
            assert "contents:write" not in text

    def test_only_the_audit_workflow_contacts_coinbase(self) -> None:
        for path in _all_workflow_files():
            if path == AUDIT_WF:
                continue
            assert not _COINBASE_HOST_RE.search(path.read_text(encoding="utf-8")), (
                f"{path.name} contacts a Coinbase host"
            )

    def test_audit_workflow_and_trigger_exist_together(self) -> None:
        # The temporary pair travels together; a dangling half is a defect.
        assert AUDIT_WF.exists() == (REPO_ROOT / "research/m2b/audit_acquire.trigger").exists()


class TestNetworkBoundary:
    def test_only_allowlisted_hosts_across_all_workflows(self) -> None:
        for path in _all_workflow_files():
            hosts = set(_URL_RE.findall(path.read_text(encoding="utf-8")))
            allowed = GLOBAL_ALLOWED_HOSTS | (AUDIT_ALLOWED_HOSTS if path == AUDIT_WF else set())
            unexpected = hosts - allowed
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
    def test_no_pull_request_reachable_write(self) -> None:
        for path in _all_workflow_files():
            text = path.read_text(encoding="utf-8")
            if "contents: write" in text:
                assert "pull_request" not in text

    def test_no_id_token_permission(self) -> None:
        for path in _all_workflow_files():
            assert "id-token" not in path.read_text(encoding="utf-8")


class TestAuditWorkflowControls:
    """Every control the temporary reacquisition workflow claims."""

    def _text(self) -> str:
        assert AUDIT_WF.exists(), "audit workflow expected while this module version is in force"
        return AUDIT_WF.read_text(encoding="utf-8")

    def test_triggers_only_on_the_committed_trigger_path(self) -> None:
        text = self._text()
        assert 'branches: ["claude/m2b-real-data-benchmarks"]' in text
        assert "research/m2b/audit_acquire.trigger" in text
        assert "workflow_dispatch" not in text
        assert "pull_request" not in text
        assert "schedule" not in text

    def test_repo_and_branch_guards(self) -> None:
        text = self._text()
        assert "github.repository == 'panfot1409/gambling-winnings'" in text
        assert "github.ref == 'refs/heads/claude/m2b-real-data-benchmarks'" in text

    def test_default_read_write_elevation_on_single_job_only(self) -> None:
        text = self._text()
        assert re.search(r"^permissions:\n\s+contents:\s*read\b", text, re.MULTILINE)
        assert text.count("contents: write") == 1

    def test_concurrency_group(self) -> None:
        assert "concurrency:" in self._text()
        assert "cancel-in-progress: false" in self._text()

    def test_checkout_pinned_and_head_asserted(self) -> None:
        text = self._text()
        assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in text
        assert 'test "$(git rev-parse HEAD)" = "${{ github.sha }}"' in text

    def test_uv_is_hash_verified_never_piped_to_shell(self) -> None:
        text = self._text()
        assert "install.sh" not in text
        # Nothing is ever piped into a shell ("| sha256sum" is fine).
        assert re.search(r"\|\s*(ba)?sh\b", text) is None
        assert "sha256sum --check --strict" in text
        assert "b6d30d02fb65193309fc12a20f9e1a9fab67f469d3e487a254ca1145fd06788f" in text

    def test_fresh_attempt_refusal_and_fixed_attempt_id(self) -> None:
        text = self._text()
        assert "AUDIT_ATTEMPT_ID: coinbase-eth-usd-audit-002" in text
        assert 'test ! -e "research/m2b/raw/coinbase/$AUDIT_ATTEMPT_ID"' in text

    def test_canonical_plan_is_the_unchanged_committed_one(self) -> None:
        assert "PLAN_PATH: research/m2b/acquisition_request_plan.json" in self._text()

    def test_staged_path_allowlist_before_the_bot_commit(self) -> None:
        text = self._text()
        assert "git diff --cached --name-only" in text
        assert "research/m2b/raw/coinbase/coinbase-eth-usd-audit-002/*.json" in text
        assert "unexpected staged path" in text

    def test_pre_push_branch_equality_and_no_force(self) -> None:
        text = self._text()
        assert (
            'test "$(git rev-parse origin/claude/m2b-real-data-benchmarks)" = "${{ github.sha }}"'
            in text
        )
        assert "--force" not in text
        assert "push origin HEAD:claude/m2b-real-data-benchmarks" in text

    def test_per_body_and_aggregate_caps(self) -> None:
        text = self._text()
        assert "--max-filesize 5000000" in text
        assert '"$SIZE" -gt 2000000' in text
        assert '"$TOTAL" -gt 10485760' in text

    def test_no_secrets_are_referenced(self) -> None:
        assert "secrets." not in self._text()


class TestSurvivingWorkflowsPinned:
    def test_ci_checkout_pinned(self) -> None:
        assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in CI.read_text(
            encoding="utf-8"
        )

    def test_ci_default_permissions_read(self) -> None:
        assert re.search(
            r"^permissions:\n\s+contents:\s*read\b", CI.read_text(encoding="utf-8"), re.MULTILINE
        )
