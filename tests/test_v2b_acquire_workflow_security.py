"""Static hardening checks for the TEMPORARY one-shot V2B BTC acquisition workflow.

``.github/workflows/v2b-acquire.yml`` is the single, transient, write-capable
acquisition workflow (Milestone V2B sections 11-12). It is the ONLY workflow on this
branch permitted ``contents: write`` — and only on its ``acquire`` job — and it is
removed together with its sentinel after the genesis + audit acquisitions are verified
(section 13). While it exists, the accepted M3F governance verifiers (honest_state,
workflow_inventory, the independent verifier) correctly and loudly flag a write-capable
workflow; that is the honest transient state, not a regression, and it clears the moment
the workflow is retired. These checks prove that WHILE present the workflow is locked down
to exactly the reviewed least-privilege shape. Text/regex based (no YAML dependency).

If this file or the workflow it guards is absent, the checks are skipped: post-retirement
the standing assertions in ``tests/test_workflow_security.py`` prove the workflow is gone.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import eth_research

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "v2b-acquire.yml"
BRANCH = "claude/v2b-cross-asset-research-reset"
SENTINEL = "research/v2b/acquire.trigger"

pytestmark = pytest.mark.skipif(
    not WORKFLOW.is_file(),
    reason="v2b-acquire.yml is retired (section 13); nothing to harden-check",
)


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_top_level_permissions_are_contents_read() -> None:
    assert re.search(r"^permissions:\n\s+contents:\s*read\b", _text(), re.MULTILINE)


def test_write_is_confined_to_the_single_acquire_job() -> None:
    text = _text()
    # Exactly one *effective* contents: write (comment mentions do not count), and it is
    # the acquire job's job-level grant.
    grants = [
        ln for ln in text.splitlines() if "contents: write" in ln and not ln.strip().startswith("#")
    ]
    assert len(grants) == 1
    assert re.search(r"jobs:\n\s+acquire:", text)
    assert re.search(r"permissions:\n\s+contents:\s*write\b", text)


def test_no_id_token_no_secrets_no_packages() -> None:
    text = _text()
    assert "id-token" not in text
    assert "secrets." not in text
    assert "secrets:" not in text
    assert "packages:" not in text
    assert "write-all" not in text


def test_triggers_are_branch_and_sentinel_scoped() -> None:
    text = _text()
    assert f'branches: ["{BRANCH}"]' in text
    assert SENTINEL in text
    # No auto/remote-reachable trigger.
    assert "pull_request" not in text
    assert "schedule:" not in text
    assert "cron:" not in text
    # workflow_dispatch offers only the two whitelisted attempt ids.
    assert "coinbase-btc-usd-research-genesis-001" in text
    assert "coinbase-btc-usd-research-audit-002" in text


def test_job_is_repo_and_ref_guarded() -> None:
    text = _text()
    assert "github.repository == 'panfot1409/gambling-winnings'" in text
    assert f"github.ref == 'refs/heads/{BRANCH}'" in text


def test_attempt_id_is_whitelisted_by_a_case_guard() -> None:
    text = _text()
    assert "coinbase-btc-usd-research-genesis-001) ;;" in text
    assert "coinbase-btc-usd-research-audit-002) ;;" in text
    assert "refusing: unexpected attempt id" in text


def test_actions_are_full_sha_pinned() -> None:
    for ref in re.findall(r"uses:\s*([^\s#]+)", _text()):
        assert re.match(r"^[^@]+@[0-9a-f]{40}$", ref), f"{ref} is not pinned to a 40-hex SHA"


def test_uv_installed_from_hash_pinned_wheel() -> None:
    text = _text()
    assert "ci/uv-requirements.txt" in text
    assert "--require-hashes" in text


def test_curl_is_hardened() -> None:
    text = _text()
    assert "--proto '=https'" in text
    assert "--tlsv1.2" in text
    assert "--max-redirs 0" in text
    assert "--fail" in text
    assert "--max-filesize" in text


def test_no_piped_installer_and_body_is_written_to_file_not_logged() -> None:
    text = _text()
    # A genuine piped installer (curl/wget of a payload piped into a shell) is forbidden;
    # a benign `curl --version | head` is not a download and is allowed.
    assert not re.search(r"(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba)?sh\b", text)
    assert "install.sh | sh" not in text
    # The candle body is written to a file (-o) and only status/content-type is printed.
    assert re.search(r"-o \"\$\{RAW_DIR\}/\$\{FN\}\"", text)
    assert "%{http_code}" in text


def test_push_is_fast_forward_only_and_scope_checked() -> None:
    text = _text()
    assert "--force" not in text
    assert "push origin HEAD:claude/v2b-cross-asset-research-reset" in text
    assert "remote head moved" in text  # before/after remote-head verification
    assert "changes outside" in text  # bot-commit scope confinement to the raw dir
    # The scope check must enumerate individual untracked files: research/v2b/raw/ is a
    # brand-new directory, so a plain `git status --porcelain` collapses it to one line that
    # would not match the attempt-dir path (regression: genesis run 29703684302 step 11).
    assert "--untracked-files=all" in text


def test_runner_is_the_offline_module_and_no_dynamic_endpoint() -> None:
    text = _text()
    assert "python -m eth_research.v2b.acquire_runner emit-plan" in text
    assert "python -m eth_research.v2b.acquire_runner verify" in text
    # No caller-supplied endpoint/host literal in the YAML (the endpoint comes from the
    # runner-emitted plan, which is derived from the hard-coded package constant).
    assert "api.exchange.coinbase.com" not in text
