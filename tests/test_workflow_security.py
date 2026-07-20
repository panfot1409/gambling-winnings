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

# The single authorized private-repo release-artifact channel (basename only). Every other
# workflow must upload nothing; the exception is enforced conditionally in
# eth_research.m3f.workflow_inventory.check_inventory and exhaustively probed in
# tests/test_private_workflow_security.py.
ARTIFACT_UPLOAD_ALLOWLIST = {"private-release-build.yml"}

# Only the uv installer host may appear, and only in read-only workflows.
ALLOWED_HOSTS = {"astral.sh"}
_URL_RE = re.compile(r"https://([A-Za-z0-9.\-]+)")
_USES_RE = re.compile(r"uses:\s*([^\s#]+)")
_SHA_PIN_RE = re.compile(r"^[^@]+@[0-9a-f]{40}$")
# A Coinbase *host in a URL* (a network contact), not the word in a comment.
_COINBASE_HOST_RE = re.compile(r"https?://[^\s\"']*coinbase", re.IGNORECASE)


def _all_workflow_files() -> list[Path]:
    # GitHub executes both extensions; scan both so a write-capable *.yaml cannot
    # hide from the host-allowlist / id-token / artifact-upload controls.
    return sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])


class TestAcquisitionWorkflowsRetired:
    def test_original_acquisition_workflow_is_removed(self) -> None:
        assert not (WORKFLOWS / "m2b-acquire.yml").exists()

    def test_original_push_bootstrap_trigger_is_removed(self) -> None:
        assert not (REPO_ROOT / "research/m2b/acquire.trigger").exists()

    def test_audit_reacquisition_workflow_is_removed(self) -> None:
        assert not (WORKFLOWS / "m2b-audit-reacquire.yml").exists()

    def test_audit_push_bootstrap_trigger_is_removed(self) -> None:
        assert not (REPO_ROOT / "research/m2b/audit_acquire.trigger").exists()

    def test_m3d_acquisition_workflow_is_removed(self) -> None:
        assert not (WORKFLOWS / "m3d-acquire.yml").exists()

    def test_m3d_acquire_trigger_is_removed(self) -> None:
        assert not (REPO_ROOT / "research/m3d/acquire.trigger").exists()

    def test_v2b_acquisition_workflow_is_removed(self) -> None:
        assert not (WORKFLOWS / "v2b-acquire.yml").exists()

    def test_v2b_acquire_trigger_is_removed(self) -> None:
        assert not (REPO_ROOT / "research/v2b/acquire.trigger").exists()

    def test_no_workflow_can_write_contents(self) -> None:
        # At the final HEAD no workflow may write repository contents — the temporary V2B BTC
        # acquisition workflow is retired (section 13).
        for path in _all_workflow_files():
            text = path.read_text(encoding="utf-8")
            assert "contents: write" not in text, f"{path.name} still grants contents: write"
            assert "contents:write" not in text

    def test_no_workflow_contacts_coinbase(self) -> None:
        # The acquisition endpoint is never a literal in any workflow YAML (it is emitted at run
        # time from the hard-coded package constant), so even the transient acquire workflow
        # carries no Coinbase host string. This assertion stays unconditional.
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
        # No workflow may upload artifacts (which could exfiltrate market data) EXCEPT the single
        # allowlisted private-release payload builder, which uploads only the closed, access-
        # controlled dist_private/ directory to this PRIVATE repo's own Actions artifact store
        # (see src/eth_research/m3f/workflow_inventory.py::check_inventory and
        # tests/test_private_workflow_security.py). Every OTHER workflow still uploads nothing.
        for path in _all_workflow_files():
            if path.name in ARTIFACT_UPLOAD_ALLOWLIST:
                continue
            assert "upload-artifact" not in path.read_text(encoding="utf-8"), (
                f"{path.name} uploads an artifact but is not the allowlisted builder"
            )

    def test_exactly_one_workflow_uploads_and_it_is_the_allowlisted_one(self) -> None:
        uploaders = {
            path.name
            for path in _all_workflow_files()
            if "upload-artifact" in path.read_text(encoding="utf-8")
        }
        assert uploaders == ARTIFACT_UPLOAD_ALLOWLIST

    def test_allowlisted_uploader_keeps_every_other_protection(self) -> None:
        # The check_inventory exception is CONDITIONAL: the allowlisted workflow must remain
        # contents:read, request no OIDC token, reference no secret, and stay fully SHA-pinned.
        path = WORKFLOWS / "private-release-build.yml"
        text = path.read_text(encoding="utf-8")
        assert "contents: write" not in text
        assert "write-all" not in text
        assert "id-token" not in text
        assert "secrets." not in text
        assert "secrets:" not in text
        assert re.search(r"^permissions:\n\s+contents:\s*read\b", text, re.MULTILINE)
        refs = _USES_RE.findall(text)
        assert refs, "the private-release builder must pin at least one action"
        for ref in refs:
            assert _SHA_PIN_RE.match(ref), f"{ref} is not pinned to a 40-hex SHA"

    def test_check_inventory_rejects_renamed_or_regressed_uploader(self) -> None:
        # A copy under any other basename (evil.yml, a .yaml twin) or the allowlisted basename with
        # any protection regressed is STILL rejected by the package's fail-closed scanner.
        from eth_research.m3f.workflow_inventory import check_inventory

        def _entry(path: str, **overrides: object) -> dict[str, object]:
            base: dict[str, object] = {
                "path": path,
                "has_real_permissions_block": True,
                "can_write_contents": False,
                "references_secrets": False,
                "contacts_market_host": False,
                "uploads_artifact": True,
                "piped_installer": False,
                "can_push": False,
                "can_merge_or_release_or_tag": False,
                "uses_all_sha_pinned": True,
            }
            base.update(overrides)
            return base

        canonical = ".github/workflows/private-release-build.yml"
        assert check_inventory({"workflows": [_entry(canonical)]}) == []
        rejected = [
            _entry(".github/workflows/evil.yml"),
            _entry(".github/workflows/private-release-build.yaml"),
            _entry(canonical, can_write_contents=True),
            _entry(canonical, references_secrets=True),
            _entry(canonical, uses_all_sha_pinned=False),
        ]
        for bad in rejected:
            failures = check_inventory({"workflows": [bad]})
            assert any("uploads an artifact" in f for f in failures), bad["path"]

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
