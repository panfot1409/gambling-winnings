"""Adversarial workflow-evasion matrix for the one authorized private-release artifact channel.

``.github/workflows/private-release-build.yml`` is the SOLE workflow permitted to upload an
artifact (the closed, access-controlled ``dist_private/`` payload) to this PRIVATE repository's
own Actions artifact store. The narrow exception lives in
``eth_research.m3f.workflow_inventory.check_inventory`` and is CONDITIONAL: it holds only while
that same workflow keeps ``contents: read``, references no secret, and stays fully SHA-pinned.

This module proves two things:

* the real ``private-release-build.yml`` does NONE of the classic exfiltration/publication
  evasions (workflow_dispatch-only, ``contents: read``, no OIDC token, no secret, no public
  release/tag/push, no piped installer, a closed upload path with explicit retention); and
* NO OTHER workflow can — the fail-closed package scanner catches a renamed copy, a ``.yaml``
  twin, a flow-mapping / anchored / job-level write escalation, an unpinned action, a push, a
  ``gh release``/``git tag`` verb, a piped installer, a market-host contact, and a missing
  permissions block; and the on-disk workflow set is a closed, enumerated allowlist so an
  unreviewed new workflow (or a nested-directory clone) fails this standing guard.

HONESTY — lexical-scan limits. These checks are text/regex based (no YAML parser, by repo
convention). Two limits are disclosed rather than hidden:

1. ``check_inventory``'s upload exception is keyed on the file *basename* and is
   trigger-agnostic. A hypothetical file that *reused* the allowlisted basename but added a
   ``pull_request_target``/``schedule`` trigger would not be caught by the lexical upload
   exception alone. That surface is closed by (a) the enumerated closed-workflow-set assertion
   below — no second ``private-release-build.yml`` and no nested-directory workflow may exist —
   and (b) the workflow's own first-step runtime refusal of any non-``workflow_dispatch`` event.
2. ``build_inventory`` globs only the top level of ``.github/workflows`` (GitHub Actions never
   executes a nested-directory workflow), so a nested clone is inert and outside the scan
   surface; the closed-set assertion pins that no such file exists.

This module is one layer, paired with ``tests/test_workflow_security.py`` (no write / no secret
/ no id-token / SHA-pin / host-allowlist), ``tests/test_public_publication_killswitch.py``, the
``private_distribution_policy.json`` closed posture, the wheel ``Private :: Do Not Upload``
guard, and mandatory human review.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import eth_research
from eth_research.m3f.workflow_inventory import (
    build_and_check,
    build_inventory,
    workflow_grants_write,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
PRIVATE = WORKFLOWS / "private-release-build.yml"
PRIVATE_BASENAME = "private-release-build.yml"

# The closed, enumerated set of workflow files that may exist. A new workflow (or a nested clone,
# or a .yaml twin) fails this standing guard on purpose and forces a conscious security review.
KNOWN_WORKFLOW_FILES = frozenset(
    {
        "ci.yml",
        "m2b-replay.yml",
        "m3a-replay.yml",
        "m3b-replay.yml",
        "m3c-replay.yml",
        "m3d-replay.yml",
        "m3e-prospective-update.yml",
        "m3e-replay.yml",
        "m3e-update-pr-check.yml",
        "m3f-replay.yml",
        "m4b-replay.yml",
        "v2a-replay.yml",
        "v2b-replay.yml",
        "v2ab-replay.yml",
        "v2c-replay.yml",
        "v2-fable5-replay.yml",
        "release-dry-run.yml",
        "private-release-build.yml",
    }
)

PINNED_UPLOAD = "actions/upload-artifact@b4b15b8c7c6ac21ea08fcf65892d2ee8f75cf882"


def _private_text() -> str:
    return PRIVATE.read_text(encoding="utf-8")


def _trigger_keys(text: str) -> set[str]:
    """The top-level trigger keys under a block-style ``on:`` mapping."""
    keys: set[str] = set()
    in_on = False
    for line in text.splitlines():
        if re.match(r"^on:\s*(#.*)?$", line):
            in_on = True
            continue
        if in_on:
            if re.match(r"^\S", line):  # the next top-level key ends the on: block
                break
            m = re.match(r"^  ([A-Za-z_][\w-]*):", line)
            if m:
                keys.add(m.group(1))
    return keys


def _write_workflow(
    tmp_path: Path, filename: str, content: str
) -> tuple[dict[str, Any], list[str]]:
    """Write one crafted workflow into a throwaway repo, then run the package scanner over it."""
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    target = wf / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    inventory, failures = build_and_check(tmp_path)
    return inventory, failures


# --------------------------------------------------------------------------- #
# the real private-release workflow does NONE of the evasions                  #
# --------------------------------------------------------------------------- #
class TestPrivateReleaseWorkflowIsLeastPrivilege:
    def test_exists(self) -> None:
        assert PRIVATE.is_file()

    def test_workflow_dispatch_is_the_only_trigger(self) -> None:
        text = _private_text()
        assert _trigger_keys(text) == {"workflow_dispatch"}
        # Belt-and-suspenders: none of the auto/remote-reachable triggers appear at all.
        assert "pull_request" not in text  # covers pull_request and pull_request_target
        assert "schedule:" not in text
        assert "cron:" not in text
        assert "workflow_run:" not in text
        assert re.search(r"^\s*release:\s*$", text, re.MULTILINE) is None
        assert re.search(r"^\s*push:\s*$", text, re.MULTILINE) is None

    def test_runtime_guard_refuses_non_dispatch_events(self) -> None:
        # The lexical upload exception is trigger-agnostic; the workflow's own first step refuses
        # any non-workflow_dispatch event, closing the trigger surface at run time.
        text = _private_text()
        assert 'if [ "$EVENT_NAME" != "workflow_dispatch" ]' in text
        assert 'if [ "$REPO_PRIVATE" != "true" ]' in text
        assert 'if [ "$REPO_FULL_NAME" != "panfot1409/gambling-winnings" ]' in text

    def test_permissions_are_contents_read_only(self) -> None:
        text = _private_text()
        assert re.search(r"^permissions:\n\s+contents:\s*read\b", text, re.MULTILINE)
        assert not workflow_grants_write(text)
        assert "contents: write" not in text
        assert "write-all" not in text
        assert "permissions: {" not in text  # no flow-mapping permissions
        assert "packages:" not in text
        assert "id-token" not in text  # no OIDC token requested (bare token absent entirely)

    def test_no_secret_reference(self) -> None:
        text = _private_text()
        assert "secrets." not in text
        assert "secrets:" not in text

    def test_every_action_is_sha_pinned(self) -> None:
        entry = _scan_private()
        assert entry["uses_all_sha_pinned"] is True
        assert entry["uses_targets"], "the workflow must pin at least one action"
        for ref in entry["uses_targets"]:
            assert re.search(r"@[0-9a-f]{40}$", ref), ref

    def test_no_publish_release_tag_or_push(self) -> None:
        entry = _scan_private()
        assert entry["can_merge_or_release_or_tag"] is False
        assert entry["can_push"] is False
        text = _private_text()
        assert "gh release create" not in text
        assert "softprops/action-gh-release" not in text
        assert "gh-action-pypi-publish" not in text
        assert "git tag" not in text
        assert "git push" not in text

    def test_no_piped_installer_or_market_host(self) -> None:
        entry = _scan_private()
        assert entry["piped_installer"] is False
        assert entry["contacts_market_host"] is False

    def test_no_public_index_or_http_client_or_obfuscation(self) -> None:
        text = _private_text()
        for token in (
            "twine",
            "pypi.org",
            "upload.pypi.org",
            "test.pypi.org",
            "urllib",
            "http.client",
            "requests.",
            "base64",
            "curl ",
            "wget ",
        ):
            assert token not in text, f"{token!r} must not appear in the private-release workflow"

    def test_upload_is_a_closed_path_with_retention_and_no_broad_glob(self) -> None:
        text = _private_text()
        assert PINNED_UPLOAD in text
        assert "path: dist_private/" in text  # the closed, tool-guarded output dir only
        assert "retention-days: 30" in text  # retention is NOT omitted
        assert "if-no-files-found: error" in text
        # No broad workspace glob that could sweep up hidden/stray files.
        assert not re.search(r"^\s*path:\s*['\"]?[.*]['\"]?\s*$", text, re.MULTILINE)
        assert "github.workspace" not in text
        assert "path: ." not in text

    def test_installs_uv_from_the_hash_pinned_wheel(self) -> None:
        text = _private_text()
        assert "ci/uv-requirements.txt" in text
        assert "--require-hashes" in text


def _scan_private() -> dict[str, Any]:
    inv = build_inventory(REPO_ROOT)
    return next(e for e in inv["workflows"] if Path(e["path"]).name == PRIVATE_BASENAME)


# --------------------------------------------------------------------------- #
# the on-disk workflow set is closed, and the live scanner is clean            #
# --------------------------------------------------------------------------- #
class TestClosedWorkflowSet:
    def test_on_disk_set_matches_the_known_allowlist(self) -> None:
        # Recursive walk: any nested-directory workflow, .yaml twin, or unreviewed new file makes
        # the set differ and fails this standing guard.
        on_disk = {p.name for p in WORKFLOWS.rglob("*") if p.is_file()}
        assert on_disk == KNOWN_WORKFLOW_FILES

    def test_no_nested_workflow_directories(self) -> None:
        nested = [p for p in WORKFLOWS.rglob("*") if p.is_dir()]
        assert nested == []

    def test_all_workflows_are_dot_yml_top_level(self) -> None:
        for p in WORKFLOWS.iterdir():
            assert p.is_file()
            assert p.suffix == ".yml", f"{p.name}: only top-level .yml workflows are allowed"

    def test_exactly_one_uploader_and_it_is_the_private_builder(self) -> None:
        uploaders = {
            p.name
            for p in WORKFLOWS.glob("*.yml")
            if "upload-artifact" in p.read_text(encoding="utf-8")
        }
        # The V2D update workflow moves the two isolated runner bundles between
        # its own jobs as private artifacts (authorized by the committed anchor).
        assert uploaders == {PRIVATE_BASENAME, "m3e-prospective-update.yml"}

    def test_live_supply_chain_scan_is_clean(self) -> None:
        _inv, failures = build_and_check(REPO_ROOT)
        assert failures == []

    def test_v2d_grants_do_not_generalize_to_other_basenames(self) -> None:
        # The V2D exemption is keyed to the ONE authorized basename. The same
        # entry properties under any other name must still fail closed in the
        # shared scanner (and therefore in every suite built on it).
        from eth_research.m3f.workflow_inventory import check_inventory

        inv = build_inventory(REPO_ROOT)
        update = next(
            e
            for e in inv["workflows"]
            if Path(e["path"]).name == "m3e-prospective-update.yml"
        )
        assert check_inventory({"workflows": [update]}) == []
        impostor = {**update, "path": ".github/workflows/impostor-update.yml"}
        failures = check_inventory({"workflows": [impostor]})
        assert any("write contents" in f for f in failures)
        assert any("git push" in f for f in failures)

    def test_every_live_workflow_is_least_privilege(self) -> None:
        # The V2D-anchored update workflow is the ONLY workflow allowed to write
        # contents (job-scoped bot-branch push), push, or move artifacts besides
        # the private builder. Its YAML carries no market-host literal (the
        # endpoint comes from the offline-emitted plan), but it IS the single
        # authorized market-data egress workflow at runtime — documented here and
        # in tests/test_workflow_security.py, authorized by the committed anchor.
        update = "m3e-prospective-update.yml"
        inv = build_inventory(REPO_ROOT)
        for e in inv["workflows"]:
            name = Path(e["path"]).name
            if name == update:
                assert e["can_write_contents"] is True, name
                assert e["can_push"] is True, name
            else:
                assert e["can_write_contents"] is False, name
                assert e["can_push"] is False, name
            assert e["can_merge_or_release_or_tag"] is False, name
            assert e["contacts_market_host"] is False, name
            assert e["piped_installer"] is False, name
            assert e["uses_all_sha_pinned"] is True, name
            assert e["has_real_permissions_block"] is True, name
            if e["uploads_artifact"]:
                assert name in {PRIVATE_BASENAME, update}, f"{name} uploads unexpectedly"


# --------------------------------------------------------------------------- #
# no OTHER workflow can evade the fail-closed scanner                          #
# --------------------------------------------------------------------------- #
_UPLOAD_STEP = (
    "jobs:\n"
    "  x:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    f"      - uses: {PINNED_UPLOAD}\n"
    "        with:\n"
    "          name: leak\n"
    "          path: .\n"
)


def _wf(header: str, body: str = _UPLOAD_STEP) -> str:
    return f"name: crafted\non:\n  workflow_dispatch:\n{header}{body}"


class TestEvasionsAreCaught:
    def test_renamed_uploader_is_rejected(self, tmp_path: Path) -> None:
        _inv, failures = _write_workflow(
            tmp_path, "evil.yml", _wf("permissions:\n  contents: read\n")
        )
        assert any("uploads an artifact" in f for f in failures)

    def test_yaml_twin_uploader_is_rejected(self, tmp_path: Path) -> None:
        _inv, failures = _write_workflow(
            tmp_path, "private-release-build.yaml", _wf("permissions:\n  contents: read\n")
        )
        assert any("uploads an artifact" in f for f in failures)

    def test_allowlisted_basename_with_secret_loses_the_exemption(self, tmp_path: Path) -> None:
        # A file reusing the allowlisted basename but referencing a secret is NOT exempt.
        body = _UPLOAD_STEP.replace("name: leak", "name: ${{ secrets.TOKEN }}")
        _inv, failures = _write_workflow(
            tmp_path, PRIVATE_BASENAME, _wf("permissions:\n  contents: read\n", body)
        )
        assert any("uploads an artifact" in f for f in failures)

    def test_allowlisted_basename_with_job_write_loses_the_exemption(self, tmp_path: Path) -> None:
        header = "permissions:\n  contents: read\n"
        body = _UPLOAD_STEP.replace(
            "  x:\n    runs-on: ubuntu-latest\n",
            "  x:\n    runs-on: ubuntu-latest\n    permissions:\n      contents: write\n",
        )
        _inv, failures = _write_workflow(tmp_path, PRIVATE_BASENAME, _wf(header, body))
        assert any("uploads an artifact" in f for f in failures)
        assert any("grants write contents" in f for f in failures)

    def test_flow_mapping_write_is_rejected(self, tmp_path: Path) -> None:
        _inv, failures = _write_workflow(
            tmp_path, "flow.yml", _wf("permissions: { contents: write }\n")
        )
        assert any("grants write contents" in f for f in failures)

    def test_yaml_anchor_write_is_rejected(self, tmp_path: Path) -> None:
        header = "env:\n  w: &wr write\npermissions:\n  contents: *wr\n"
        _inv, failures = _write_workflow(tmp_path, "anchor.yml", _wf(header))
        assert any("grants write contents" in f for f in failures)

    def test_id_token_write_is_rejected_as_a_write_grant(self, tmp_path: Path) -> None:
        # `id-token: write` is a `: write` grant and is caught by the write detector.
        _inv, failures = _write_workflow(
            tmp_path, "oidc.yml", _wf("permissions:\n  contents: read\n  id-token: write\n")
        )
        assert any("grants write contents" in f for f in failures)

    def test_packages_write_is_rejected(self, tmp_path: Path) -> None:
        _inv, failures = _write_workflow(
            tmp_path, "pkg.yml", _wf("permissions:\n  contents: read\n  packages: write\n")
        )
        assert any("grants write contents" in f for f in failures)

    def test_unpinned_action_is_rejected(self, tmp_path: Path) -> None:
        body = (
            "jobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - uses: actions/checkout@v4\n"
        )
        _inv, failures = _write_workflow(
            tmp_path, "unpinned.yml", _wf("permissions:\n  contents: read\n", body)
        )
        assert any("not pinned to a full commit SHA" in f for f in failures)

    def test_git_push_is_rejected(self, tmp_path: Path) -> None:
        body = (
            "jobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: git push origin HEAD\n"
        )
        _inv, failures = _write_workflow(
            tmp_path, "push.yml", _wf("permissions:\n  contents: read\n", body)
        )
        assert any("git push" in f for f in failures)

    def test_gh_release_create_is_rejected(self, tmp_path: Path) -> None:
        body = (
            "jobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: gh release create v1 dist/*\n"
        )
        _inv, failures = _write_workflow(
            tmp_path, "ghrel.yml", _wf("permissions:\n  contents: read\n", body)
        )
        assert any("merge/release/tag verb" in f for f in failures)

    def test_git_tag_is_rejected(self, tmp_path: Path) -> None:
        body = "jobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n      - run: git tag v1.1.0\n"
        _inv, failures = _write_workflow(
            tmp_path, "tag.yml", _wf("permissions:\n  contents: read\n", body)
        )
        assert any("merge/release/tag verb" in f for f in failures)

    def test_piped_installer_is_rejected(self, tmp_path: Path) -> None:
        body = (
            "jobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: curl -sSf https://example.test/install.sh | sh\n"
        )
        _inv, failures = _write_workflow(
            tmp_path, "curl.yml", _wf("permissions:\n  contents: read\n", body)
        )
        assert any("piped installer" in f for f in failures)

    def test_market_host_contact_is_rejected(self, tmp_path: Path) -> None:
        body = (
            "jobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: curl https://api.coinbase.com/v2/price\n"
        )
        _inv, failures = _write_workflow(
            tmp_path, "market.yml", _wf("permissions:\n  contents: read\n", body)
        )
        assert any("market host" in f for f in failures)

    def test_missing_permissions_block_is_rejected(self, tmp_path: Path) -> None:
        content = f"name: crafted\non:\n  workflow_dispatch:\n{_UPLOAD_STEP}"
        _inv, failures = _write_workflow(tmp_path, "noperm.yml", content)
        assert any("no explicit permissions block" in f for f in failures)

    def test_pr_triggered_uploader_is_rejected(self, tmp_path: Path) -> None:
        # A non-allowlisted workflow that produces an artifact on pull_request_target is caught by
        # the upload ban (the trigger itself is not the hook; the artifact upload is).
        content = (
            "name: crafted\non:\n  pull_request_target:\n"
            "permissions:\n  contents: read\n" + _UPLOAD_STEP
        )
        _inv, failures = _write_workflow(tmp_path, "pr-evil.yml", content)
        assert any("uploads an artifact" in f for f in failures)

    def test_nested_directory_workflow_is_outside_the_scan_surface(self, tmp_path: Path) -> None:
        # GitHub Actions never runs a nested-directory workflow, and the top-level glob does not
        # inventory it; the closed-set assertion (above) pins that no such file exists on disk.
        inv, _failures = _write_workflow(
            tmp_path,
            "sub/private-release-build.yml",
            _wf("permissions:\n  contents: read\n"),
        )
        assert inv["workflow_count"] == 0
