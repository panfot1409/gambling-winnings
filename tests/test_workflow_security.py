"""Static security checks on the GitHub Actions workflows.

These assert the acquisition clean-room stays tightly scoped: no PR/fork
execution, least-privilege permissions, a single fixed public market-data
host, SHA-pinned actions, no secrets, no curl-into-parser mutation
pipeline, confined output paths, and no force-push. Text/regex based so no
YAML dependency is added.
"""

from __future__ import annotations

import re
from pathlib import Path

import eth_research

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ACQUIRE = WORKFLOWS / "m2b-acquire.yml"
CI = WORKFLOWS / "ci.yml"

ALLOWED_HOSTS = {"astral.sh", "api.exchange.coinbase.com"}
_URL_RE = re.compile(r"https://([A-Za-z0-9.\-]+)")
_USES_RE = re.compile(r"uses:\s*([^\s#]+)")
_SHA_PIN_RE = re.compile(r"^[^@]+@[0-9a-f]{40}$")


def _all_workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


class TestAcquireWorkflowScope:
    def test_workflow_exists(self) -> None:
        assert ACQUIRE.is_file()

    def test_not_triggered_by_pull_request(self) -> None:
        assert "pull_request" not in ACQUIRE.read_text(encoding="utf-8")

    def test_scoped_to_exact_repo_and_branch(self) -> None:
        text = ACQUIRE.read_text(encoding="utf-8")
        assert "github.repository == 'panfot1409/gambling-winnings'" in text
        assert "refs/heads/claude/m2b-real-data-benchmarks" in text

    def test_default_permissions_read_only(self) -> None:
        text = ACQUIRE.read_text(encoding="utf-8")
        # top-level default must be read; write is granted only on the job.
        assert re.search(r"^permissions:\n\s+contents:\s*read\b", text, re.MULTILINE)

    def test_no_id_token_or_packages_permission(self) -> None:
        text = ACQUIRE.read_text(encoding="utf-8")
        assert "id-token" not in text
        assert "packages:" not in text

    def test_concurrency_serializes_runs(self) -> None:
        assert "concurrency:" in ACQUIRE.read_text(encoding="utf-8")


class TestNetworkBoundary:
    def test_only_allowlisted_hosts_across_all_workflows(self) -> None:
        for path in _all_workflow_files():
            hosts = set(_URL_RE.findall(path.read_text(encoding="utf-8")))
            unexpected = hosts - ALLOWED_HOSTS
            assert not unexpected, f"{path.name} references unexpected hosts: {unexpected}"

    def test_market_data_host_is_exactly_coinbase(self) -> None:
        text = ACQUIRE.read_text(encoding="utf-8")
        assert "https://api.exchange.coinbase.com/products/ETH-USD/candles" in text
        # no private/sandbox/advanced-trade endpoints
        for forbidden in (
            "api-public.sandbox",
            "advanced-trade",
            "coinbase.com/api/v3",
            "Authorization",
        ):
            assert forbidden not in text

    def test_no_secrets_referenced(self) -> None:
        # GITHUB_TOKEN is provided implicitly via persist-credentials; the
        # workflow must never reference a configured secret or an exchange key.
        assert "secrets." not in ACQUIRE.read_text(encoding="utf-8")

    def test_no_curl_pipe_into_parser(self) -> None:
        # Response bodies go to a file (--output); they are never piped into a
        # parser that could mutate them before hashing.
        text = ACQUIRE.read_text(encoding="utf-8")
        assert "--output" in text
        assert not re.search(r"curl[^\n]*\|\s*(jq|python|json)", text)


class TestActionPinning:
    def test_every_action_is_pinned_by_full_sha(self) -> None:
        for path in _all_workflow_files():
            for ref in _USES_RE.findall(path.read_text(encoding="utf-8")):
                assert _SHA_PIN_RE.match(ref), f"{path.name}: {ref} is not pinned to a 40-hex SHA"

    def test_no_floating_tags(self) -> None:
        for path in _all_workflow_files():
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"uses:\s*\S+@(v?\d+(\.\d+)*|main|master)\s*$", text, re.MULTILINE)


class TestPublicationSafety:
    def test_no_force_push(self) -> None:
        text = ACQUIRE.read_text(encoding="utf-8")
        assert "--force" not in text
        assert "force-with-lease" not in text
        assert not re.search(r"push\s+-f\b", text)

    def test_output_confined_to_raw_dir(self) -> None:
        text = ACQUIRE.read_text(encoding="utf-8")
        assert "research/m2b/raw/coinbase/" in text
        # the committed path is only ever under the raw coinbase tree
        assert re.search(r'git add "?\$\{\{ steps\.publish\.outputs\.out \}\}"?', text)

    def test_pr_write_workflows_do_not_run_on_pull_request(self) -> None:
        # Any workflow that can write contents must not be reachable from a PR.
        for path in _all_workflow_files():
            text = path.read_text(encoding="utf-8")
            if "contents: write" in text:
                assert "pull_request" not in text, f"{path.name} has write perms and a PR trigger"


class TestCiWorkflowStillPinned:
    def test_ci_checkout_pinned(self) -> None:
        text = CI.read_text(encoding="utf-8")
        assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in text

    def test_ci_default_permissions_read(self) -> None:
        assert re.search(
            r"^permissions:\n\s+contents:\s*read\b", CI.read_text(encoding="utf-8"), re.MULTILINE
        )
