"""Auditor B finding A-5: the closed set must be derived independently of the manifest.

A-5 was demonstrated by adding one file to the accepted proposal directory **and**
adding its pin to the manifest — all three readers passed, because all three
compared the live directory against the attacker-supplied pin map.

Every test below builds a *throwaway* git repository in ``tmp_path`` (never the
real repo), lands a lawful proposal on it, then applies exactly one attack and
asserts a specific refusal. The 18 attacks are:

===  ============================  ============================================
 #   attack                         refused by
===  ============================  ============================================
 1   extra JSON                     unknown file in the proposal directory
 2   extra Markdown                 disallowed extension
 3   extra receipt                  unknown file in a runner directory
 4   extra raw response             not declared by the update plan or receipt
 5   ``.env``                       hidden/dotfile path
 6   PEM / key-shaped file          secret/key-shaped file
 7   Python source                  source/script file
 8   workflow file                  workflow/YAML file
 9   executable shell script        executable file (mode 100755)
10   nested hidden file             hidden/dotfile path
11   similarly-named sibling        belongs to a different proposal
12   Unicode-confusable filename    path is not ASCII
13   symlink                        symlink (mode 120000)
14   submodule                      submodule/gitlink (mode 160000)
15   Git-LFS pointer                Git-LFS pointer, not committed content
16   file in the manifest AND pins  declaring a file does NOT make it legal
17   traversal outside the root     outside the allowed roots / traversal segment
18   case-only difference           case-fold path collision
===  ============================  ============================================

Plus a clean control that PASSES (proving the policy is not simply rejecting
everything) and a control against the real repository's ground-truth range.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from eth_research.m3e.proposal_file_policy import (
    ALLOWED_ROOTS,
    ProposalFilePolicyError,
    derive_closed_set,
    is_permitted_path,
    require_lawful_relpath,
    require_no_path_collisions,
    verify_proposal_file_policy,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# Ground truth, verified with `git diff --name-status ba2dcc1d 779df6bb` (19 files).
REAL_PARENT = "ba2dcc1d63f29a009d3660be2d960388a9615da0"
REAL_HEAD = "779df6bb6c7ab4ac312e9d8fe7028392581db237"
REAL_PROPOSAL_ID = "20260715-20260724-315846f9ec5196b4"

PROPOSAL_ID = "20260715-20260724-315846f9ec5196b4"
BUNDLE = "coinbase-eth-usd-prospective-update-20260715-20260723-315846f9ec5196b4"
RAW_NAME = "coinbase-eth-usd-1d-update_0000_20260715_20260724.json"

PROPOSAL_DIR = f"research/m3e/proposals/{PROPOSAL_ID}"
BUNDLE_DIR = f"research/m3d/raw/coinbase/{BUNDLE}"

TRANSITIONED = (
    "research/m3d/prospective_manifest.json",
    "research/m3d/prospective_quality.json",
    "research/m3d/prospective_segments.jsonl",
    "research/m3d/publication_manifest.json",
    "research/m3e/accepted_base.json",
    "research/m3e/proposal_registry.jsonl",
)

ADDED = (
    f"{BUNDLE_DIR}/acquisition_plan.json",
    f"{BUNDLE_DIR}/acquisition_receipt.json",
    f"{BUNDLE_DIR}/{RAW_NAME}",
    "research/m3d/update_attempts.jsonl",
    f"{PROPOSAL_DIR}/acquisition_comparison.json",
    f"{PROPOSAL_DIR}/proposal_manifest.json",
    f"{PROPOSAL_DIR}/runner_a/acquisition_receipt.json",
    f"{PROPOSAL_DIR}/runner_a/{RAW_NAME}",
    f"{PROPOSAL_DIR}/runner_a/update_plan.json",
    f"{PROPOSAL_DIR}/runner_b/acquisition_receipt.json",
    f"{PROPOSAL_DIR}/runner_b/{RAW_NAME}",
    f"{PROPOSAL_DIR}/runner_b/update_plan.json",
    f"{PROPOSAL_DIR}/update_transition.json",
)

EXPECTED_CLOSED_SET = tuple(sorted((*TRANSITIONED, *ADDED)))

_PLAN_BODY = json.dumps(
    {"kind": "prospective_update_plan", "windows": [{"ordinal": 0, "raw_filename": RAW_NAME}]},
    sort_keys=True,
)
_RECEIPT_BODY = json.dumps(
    {
        "kind": "prospective_attempt_receipt",
        "responses": [{"ordinal": 0, "raw_filename": RAW_NAME}],
    },
    sort_keys=True,
)

Mutator = Callable[[Path, Callable[[Sequence[str]], None]], None]


# ---------------------------------------------------------------------------
# Throwaway repository fixture (never the real repo)
# ---------------------------------------------------------------------------


def _write(repo: Path, relpath: str, body: str) -> None:
    target = repo / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def build_repo(
    tmp_path: Path,
    mutate: Mutator | None = None,
    index_mutate: Mutator | None = None,
) -> tuple[Path, str, str]:
    """Build a throwaway repo: a trusted parent commit, then one proposal commit.

    ``mutate`` runs on the worktree after the lawful proposal files are written and
    before they are staged; ``index_mutate`` runs on the index after staging (for
    attacks that exist only in the index, such as a gitlink). Either way the attack
    lands inside the pinned parent..head range.
    """
    repo = tmp_path / "clone"
    repo.mkdir(parents=True)

    def git(argv: Sequence[str]) -> None:
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=policy-test",
                "-c",
                "user.email=policy-test@example.invalid",
                "-c",
                "commit.gpgsign=false",
                *argv,
            ],
            check=True,
            capture_output=True,
        )

    def rev_parse() -> str:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()

    git(["init", "-q", "-b", "main", "."])
    _write(repo, "README.md", "throwaway\n")
    _write(repo, "src/eth_research/__init__.py", "")
    for path in TRANSITIONED:
        _write(repo, path, '{"state": "parent"}\n')
    git(["add", "-A"])
    git(["commit", "-q", "-m", "trusted parent"])
    parent = rev_parse()

    for path in TRANSITIONED:
        _write(repo, path, '{"state": "proposed"}\n')
    _write(repo, "research/m3d/update_attempts.jsonl", '{"entry_kind":"genesis"}\n')
    for prefix in (f"{PROPOSAL_DIR}/runner_a", f"{PROPOSAL_DIR}/runner_b"):
        _write(repo, f"{prefix}/update_plan.json", _PLAN_BODY)
        _write(repo, f"{prefix}/acquisition_receipt.json", _RECEIPT_BODY)
        _write(repo, f"{prefix}/{RAW_NAME}", "[]\n")
    _write(repo, f"{BUNDLE_DIR}/acquisition_plan.json", _PLAN_BODY)
    _write(repo, f"{BUNDLE_DIR}/acquisition_receipt.json", _RECEIPT_BODY)
    _write(repo, f"{BUNDLE_DIR}/{RAW_NAME}", "[]\n")
    for name in ("acquisition_comparison.json", "proposal_manifest.json", "update_transition.json"):
        _write(repo, f"{PROPOSAL_DIR}/{name}", "{}\n")

    if mutate is not None:
        mutate(repo, git)

    git(["add", "-A"])
    if index_mutate is not None:
        index_mutate(repo, git)
    git(["commit", "-q", "-m", "M3E: draft prospective-cohort update proposal"])
    return repo, parent, rev_parse()


def refuse(
    tmp_path: Path,
    mutate: Mutator | None = None,
    index_mutate: Mutator | None = None,
) -> str:
    """Apply one attack, assert the policy refuses it, and return the message."""
    repo, parent, head = build_repo(tmp_path, mutate, index_mutate)
    with pytest.raises(ProposalFilePolicyError) as excinfo:
        derive_closed_set(repo, proposal_id=PROPOSAL_ID, parent_commit=parent, head_commit=head)
    return str(excinfo.value)


# ---------------------------------------------------------------------------
# CONTROL: the policy is not simply rejecting everything
# ---------------------------------------------------------------------------


def test_control_clean_proposal_passes(tmp_path: Path) -> None:
    repo, parent, head = build_repo(tmp_path)
    verified = derive_closed_set(
        repo, proposal_id=PROPOSAL_ID, parent_commit=parent, head_commit=head
    )
    assert verified.closed_set == EXPECTED_CLOSED_SET
    assert len(verified.files) == 19
    assert sorted(verified.added) == sorted(ADDED)
    assert sorted(verified.modified) == sorted(TRANSITIONED)
    assert dict(verified.name_status_map) == {
        **dict.fromkeys(TRANSITIONED, "M"),
        **dict.fromkeys(ADDED, "A"),
    }
    assert verified.name_status[0] == ("M", "research/m3d/prospective_manifest.json")
    assert {entry.mode for entry in verified.files} == {"100644"}
    binding = verified.as_binding()
    assert binding["file_count"] == 19
    assert binding["added_count"] == 13
    assert binding["modified_count"] == 6
    assert binding["parent_commit"] == parent
    assert binding["head_commit"] == head
    assert len(binding["policy_digest"]) == 64


def test_control_clean_proposal_passes_with_full_declarations(tmp_path: Path) -> None:
    """Honest declarations that exactly cover the closed set are accepted."""
    repo, parent, head = build_repo(tmp_path)
    verified = verify_proposal_file_policy(
        repo,
        proposal_id=PROPOSAL_ID,
        parent_commit=parent,
        head_commit=head,
        declared_paths={"created_pins": ADDED, "state_pins": TRANSITIONED},
    )
    assert verified.closed_set == EXPECTED_CLOSED_SET


def test_control_real_repository_ground_truth() -> None:
    """The real ba2dcc1d -> 779df6bb range is exactly 19 files: 13 added, 6 modified."""
    probe = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{REAL_HEAD}^{{commit}}"],
        check=False,
        capture_output=True,
    )
    if probe.returncode != 0:  # pragma: no cover - only when history is unavailable
        pytest.skip("the pinned proposal commits are not present in this checkout")
    verified = derive_closed_set(
        REPO_ROOT,
        proposal_id=REAL_PROPOSAL_ID,
        parent_commit=REAL_PARENT,
        head_commit=REAL_HEAD,
    )
    assert len(verified.closed_set) == 19
    assert len(verified.added) == 13
    assert len(verified.modified) == 6
    assert set(verified.modified) == set(TRANSITIONED)
    assert verified.closed_set == EXPECTED_CLOSED_SET


# ---------------------------------------------------------------------------
# The 18 attacks
# ---------------------------------------------------------------------------


def test_attack_01_extra_json(tmp_path: Path) -> None:
    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        _write(repo, f"{PROPOSAL_DIR}/extra_notes.json", '{"smuggled": true}\n')

    message = refuse(tmp_path, mutate)
    assert "unknown file in the proposal directory" in message
    assert "extra_notes.json" in message


def test_attack_02_extra_markdown(tmp_path: Path) -> None:
    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        _write(repo, f"{PROPOSAL_DIR}/NOTES.md", "# smuggled\n")

    message = refuse(tmp_path, mutate)
    assert "disallowed extension" in message
    assert "NOTES.md" in message


def test_attack_03_extra_receipt(tmp_path: Path) -> None:
    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        _write(repo, f"{PROPOSAL_DIR}/runner_a/acquisition_receipt_2.json", _RECEIPT_BODY)

    message = refuse(tmp_path, mutate)
    assert "unknown file in a runner directory" in message
    assert "acquisition_receipt_2.json" in message


def test_attack_04_extra_raw_response(tmp_path: Path) -> None:
    """A well-named raw body that the plan and the receipt do not declare."""
    extra = "coinbase-eth-usd-1d-update_0001_20260724_20260725.json"

    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        _write(repo, f"{PROPOSAL_DIR}/runner_a/{extra}", "[]\n")

    message = refuse(tmp_path, mutate)
    assert "raw response not declared by the update plan or receipt" in message
    assert extra in message


def test_attack_05_dotenv(tmp_path: Path) -> None:
    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        _write(repo, f"{PROPOSAL_DIR}/.env", "COINBASE_TOKEN=abc\n")

    message = refuse(tmp_path, mutate)
    assert "hidden/dotfile path" in message
    assert "/.env" in message


def test_attack_06_pem_key_shaped_file(tmp_path: Path) -> None:
    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        # Assembled at runtime rather than written as a literal: a committed PEM
        # header in this file is a real hit for tools/scan_secrets.py, and a
        # fixture must not force the repo-wide scan to carry a false positive.
        dashes = "-" * 5
        body = f"{dashes}BEGIN PRIVATE KEY{dashes}\nAAAA\n{dashes}END PRIVATE KEY{dashes}\n"
        _write(repo, f"{PROPOSAL_DIR}/runner_a/signing_key.pem", body)

    message = refuse(tmp_path, mutate)
    assert "secret/key-shaped file" in message
    assert "signing_key.pem" in message


def test_attack_07_python_source(tmp_path: Path) -> None:
    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        _write(repo, f"{PROPOSAL_DIR}/helper.py", "import os\n")

    message = refuse(tmp_path, mutate)
    assert "source/script file" in message
    assert "helper.py" in message


def test_attack_08_workflow_file(tmp_path: Path) -> None:
    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        _write(repo, ".github/workflows/m3e-extra.yml", "on: push\n")

    message = refuse(tmp_path, mutate)
    assert "workflow/YAML file" in message
    assert "m3e-extra.yml" in message

    # The alternate .yaml spelling, inside the allowed root, is refused identically.
    def mutate_yaml(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        _write(repo, f"{PROPOSAL_DIR}/config.yaml", "on: push\n")

    alternate = refuse(tmp_path / "alt", mutate_yaml)
    assert "workflow/YAML file" in alternate
    assert "config.yaml" in alternate


def test_attack_09_executable_shell_script(tmp_path: Path) -> None:
    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        script = repo / PROPOSAL_DIR / "run.sh"
        script.write_text("#!/bin/sh\ncurl https://example.invalid\n", encoding="utf-8")
        script.chmod(0o755)

    message = refuse(tmp_path, mutate)
    assert "executable file (mode 100755)" in message
    assert "run.sh" in message


def test_attack_10_nested_hidden_file(tmp_path: Path) -> None:
    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        _write(repo, f"{PROPOSAL_DIR}/.hidden/payload.json", "{}\n")

    message = refuse(tmp_path, mutate)
    assert "hidden/dotfile path" in message
    assert ".hidden/payload.json" in message


def test_attack_11_similarly_named_sibling(tmp_path: Path) -> None:
    sibling = PROPOSAL_ID[:-1] + "5"  # one hex digit apart from the real proposal id
    assert sibling != PROPOSAL_ID

    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        _write(repo, f"research/m3e/proposals/{sibling}/proposal_manifest.json", "{}\n")

    message = refuse(tmp_path, mutate)
    assert "belongs to a different proposal" in message
    assert sibling in message


def test_attack_12_unicode_confusable_filename(tmp_path: Path) -> None:
    confusable = "runner_\u0430"  # CYRILLIC SMALL LETTER A, not ASCII 'a'
    assert confusable != "runner_a"

    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        _write(repo, f"{PROPOSAL_DIR}/{confusable}/update_plan.json", _PLAN_BODY)

    message = refuse(tmp_path, mutate)
    assert "not ASCII (Unicode-confusable filename refused)" in message


def test_attack_13_symlink(tmp_path: Path) -> None:
    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        link = repo / PROPOSAL_DIR / "shortcut.json"
        os.symlink("../../../../src/eth_research/__init__.py", link)

    message = refuse(tmp_path, mutate)
    assert "symlink (mode 120000)" in message
    assert "shortcut.json" in message


def test_attack_14_submodule_gitlink(tmp_path: Path) -> None:
    def index_mutate(_repo: Path, git: Callable[[Sequence[str]], None]) -> None:
        gitlink = "0" * 39 + "1"
        git(
            [
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{gitlink},{PROPOSAL_DIR}/vendor",
            ]
        )

    message = refuse(tmp_path, index_mutate=index_mutate)
    assert "submodule/gitlink (mode 160000)" in message
    assert "vendor" in message


def test_attack_15_git_lfs_pointer(tmp_path: Path) -> None:
    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        _write(
            repo,
            f"{PROPOSAL_DIR}/runner_b/{RAW_NAME}",
            "version https://git-lfs.github.com/spec/v1\noid sha256:" + "0" * 64 + "\nsize 533\n",
        )

    message = refuse(tmp_path, mutate)
    assert "Git-LFS pointer, not committed content" in message
    assert RAW_NAME in message


def test_attack_16_file_added_to_both_the_manifest_and_the_pins(tmp_path: Path) -> None:
    """THE A-5 attack: the file plus its pin. Declaring it must change nothing."""
    smuggled = f"{PROPOSAL_DIR}/bonus.json"

    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        _write(repo, smuggled, '{"bonus": true}\n')

    repo, parent, head = build_repo(tmp_path, mutate)

    # (a) The derivation refuses it, and it has no channel to hear about a pin.
    with pytest.raises(ProposalFilePolicyError) as bare:
        derive_closed_set(repo, proposal_id=PROPOSAL_ID, parent_commit=parent, head_commit=head)
    assert "unknown file in the proposal directory" in str(bare.value)
    assert "bonus.json" in str(bare.value)

    # (b) Adding it to the manifest AND to the pin map refuses identically.
    with pytest.raises(ProposalFilePolicyError) as declared:
        verify_proposal_file_policy(
            repo,
            proposal_id=PROPOSAL_ID,
            parent_commit=parent,
            head_commit=head,
            declared_paths={
                "manifest": [*ADDED, smuggled],
                "created_pins": [*ADDED, smuggled],
                "state_pins": TRANSITIONED,
            },
        )
    assert str(declared.value) == str(bare.value)

    # (c) Policy alone never admits it, whatever any document says.
    assert is_permitted_path(smuggled, PROPOSAL_ID) is False

    # (d) On an otherwise CLEAN proposal, a pin for a file that is not in the
    #     git-derived closed set is itself the refusal.
    clean_repo, clean_parent, clean_head = build_repo(tmp_path / "clean")
    with pytest.raises(ProposalFilePolicyError) as pinned:
        verify_proposal_file_policy(
            clean_repo,
            proposal_id=PROPOSAL_ID,
            parent_commit=clean_parent,
            head_commit=clean_head,
            declared_paths={
                "created_pins": [*ADDED, smuggled],
                "state_pins": TRANSITIONED,
            },
        )
    assert "declaring a file does NOT make it legal" in str(pinned.value)
    assert smuggled in str(pinned.value)


def test_attack_17_path_traversal_outside_the_allowed_root(tmp_path: Path) -> None:
    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        # git normalises the traversal when it stages the path, so the payload
        # lands outside research/m3e/ — which the roots gate refuses.
        _write(repo, f"{PROPOSAL_DIR}/../../../evil.json", '{"escaped": true}\n')

    message = refuse(tmp_path, mutate)
    assert "outside the allowed roots" in message
    assert "research/evil.json" in message
    assert list(ALLOWED_ROOTS) == ["research/m3d/", "research/m3e/"]

    # And the traversal guard itself refuses an un-normalised path directly.
    with pytest.raises(ProposalFilePolicyError, match="traversal segment"):
        require_lawful_relpath(f"{PROPOSAL_DIR}/../../../../etc/passwd")


def test_attack_18_case_only_difference(tmp_path: Path) -> None:
    def mutate(repo: Path, _git: Callable[[Sequence[str]], None]) -> None:
        _write(repo, "research/m3e/Accepted_Base.json", '{"twin": true}\n')

    message = refuse(tmp_path, mutate)
    assert "case-fold path collision" in message
    assert "research/m3e/Accepted_Base.json" in message
    assert "research/m3e/accepted_base.json" in message


# ---------------------------------------------------------------------------
# Supporting unit checks for the collision and traversal guards
# ---------------------------------------------------------------------------


def test_normalization_collision_is_refused() -> None:
    nfc = "research/m3e/caf\u00e9.json"  # e-acute as a single codepoint
    nfd = "research/m3e/cafe\u0301.json"  # e + combining acute accent
    assert nfc != nfd
    with pytest.raises(ProposalFilePolicyError, match=r"NF[CKD]+ path collision"):
        require_no_path_collisions([nfc], {nfc, nfd})


def test_duplicate_normalized_path_is_refused() -> None:
    with pytest.raises(ProposalFilePolicyError, match="case-fold path collision"):
        require_no_path_collisions(
            ["research/m3d/Update_Attempts.jsonl"],
            {"research/m3d/update_attempts.jsonl", "research/m3d/Update_Attempts.jsonl"},
        )


def test_preexisting_collision_the_proposal_did_not_introduce_is_not_charged_to_it() -> None:
    require_no_path_collisions(
        ["research/m3e/accepted_base.json"],
        {"docs/A.md", "docs/a.md", "research/m3e/accepted_base.json"},
    )


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "research/m3e/../../../etc/passwd",
        "research\\m3e\\x.json",
        "research/m3e//x.json",
        "research/m3e/./x.json",
        "research/m3e/x.json ",
        "research/m3e/x.json\n",
        "research/m3e/\u0440unner_a/x.json",  # CYRILLIC SMALL LETTER ER
    ],
)
def test_unlawful_relpaths_are_refused(path: str) -> None:
    with pytest.raises(ProposalFilePolicyError):
        require_lawful_relpath(path)


def test_policy_admits_only_the_lawful_shapes() -> None:
    for path in EXPECTED_CLOSED_SET:
        assert is_permitted_path(path, PROPOSAL_ID) is True
    for path in (
        "src/eth_research/m3e/acceptance.py",
        "tests/test_m3e_file_policy.py",
        "tools/m3f_independent_verify.py",
        "pyproject.toml",
        ".github/workflows/m3e-replay.yml",
        "research/m3e/proposals/",
        f"{PROPOSAL_DIR}/runner_c/update_plan.json",
        f"{PROPOSAL_DIR}/runner_a/nested/deep.json",
        "research/m3d/raw/coinbase/some-other-bundle/acquisition_plan.json",
    ):
        assert is_permitted_path(path, PROPOSAL_ID) is False


def test_a_delete_is_never_a_lawful_proposal_change(tmp_path: Path) -> None:
    def mutate(repo: Path, git: Callable[[Sequence[str]], None]) -> None:
        git(["rm", "-q", "-f", "research/m3e/proposal_registry.jsonl"])

    message = refuse(tmp_path, mutate)
    assert "unlawful change status 'D'" in message


def test_untracked_payload_under_the_allowed_roots_is_refused(tmp_path: Path) -> None:
    repo, parent, head = build_repo(tmp_path)
    (repo / PROPOSAL_DIR / "dropped_after_the_fact.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ProposalFilePolicyError, match="untracked or uncommitted payload"):
        derive_closed_set(repo, proposal_id=PROPOSAL_ID, parent_commit=parent, head_commit=head)


def test_a_missing_member_is_refused(tmp_path: Path) -> None:
    def mutate(repo: Path, git: Callable[[Sequence[str]], None]) -> None:
        (repo / PROPOSAL_DIR / "runner_b" / "acquisition_receipt.json").unlink()

    message = refuse(tmp_path, mutate)
    assert "missing required members" in message
    assert "runner_b/acquisition_receipt.json" in message
