"""Static repo-privacy contract (§15) for the PRIVATE ``eth-research`` v1.1.0 GA.

Asserts the *committed evidence* encodes the private posture — the distribution policy and
install contract pin every public switch off, no license is declared anywhere, and the one
authorized private-release workflow gates on ``github.event.repository.private`` at runtime and
requests no OIDC token.

This is a pure static contract over committed files. It deliberately does NOT call the GitHub
API and does NOT shell out to check the repository's live visibility — the release operator
verifies live privacy separately. A green run here means the repository's *own committed bytes*
declare and enforce privacy, which is the part that must never silently drift.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
PRIVATE_RELDIR = REPO / "release" / "private" / "v1.1.0"
POLICY_PATH = PRIVATE_RELDIR / "private_distribution_policy.json"
CONTRACT_PATH = PRIVATE_RELDIR / "private_install_contract.json"
WORKFLOW_PATH = REPO / ".github" / "workflows" / "private-release-build.yml"

# The public/openness switches that must all be false, and the closed-posture license flag.
PUBLIC_BOOLEANS = (
    "public_pypi_allowed",
    "test_pypi_allowed",
    "public_github_release_allowed",
    "public_package_registry_allowed",
    "open_source_claim_allowed",
)
LICENSE_FILENAMES = ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING", "COPYING.txt")
PRIVATE_GUARD_CLASSIFIER = "Private :: Do Not Upload"


def _load_json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_bytes())
    return data


# --------------------------------------------------------------------------- #
# distribution policy encodes the private, closed posture                      #
# --------------------------------------------------------------------------- #
def test_policy_declares_private_classification_and_visibility() -> None:
    policy = _load_json(POLICY_PATH)
    assert policy["distribution_classification"] == "private"
    assert policy["repository_visibility_required"] == "private"


def test_policy_pins_every_public_boolean_false() -> None:
    policy = _load_json(POLICY_PATH)
    for flag in PUBLIC_BOOLEANS:
        assert policy[flag] is False, f"policy {flag} must be false"
    assert policy["license_present"] is False


def test_policy_accepts_no_public_distribution_channel() -> None:
    policy = _load_json(POLICY_PATH)
    public_tokens = ("pypi", "public", "anonymous", "registry")
    for channel in policy["accepted_distribution_channels"]:
        assert not any(token in channel for token in public_tokens), (
            f"a public channel leaked into the policy: {channel}"
        )


# --------------------------------------------------------------------------- #
# install contract: not a public-index install, wheel is not standalone        #
# --------------------------------------------------------------------------- #
def test_install_contract_is_private_and_non_standalone() -> None:
    contract = _load_json(CONTRACT_PATH)
    assert contract["public_index_install"] is False
    assert contract["wheel_is_standalone"] is False


# --------------------------------------------------------------------------- #
# no license anywhere: repo root files + pyproject metadata                    #
# --------------------------------------------------------------------------- #
def test_no_license_file_at_repo_root() -> None:
    for name in LICENSE_FILENAMES:
        assert not (REPO / name).exists(), f"a license file appeared at the repo root: {name}"
    # Defense in depth: nothing that even looks like a license/copying file at the root.
    stray = sorted(
        p.name
        for p in REPO.iterdir()
        if p.is_file() and re.match(r"(?i)^(licen[cs]e|copying)\b", p.name)
    )
    assert stray == [], f"unexpected license-like root files: {stray}"


def test_pyproject_declares_no_license_and_keeps_the_private_guard() -> None:
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    # No [project].license (an SPDX string/table would authorize a public upload).
    assert "license" not in project or not project["license"]
    classifiers = project["classifiers"]
    assert PRIVATE_GUARD_CLASSIFIER in classifiers, "the Private :: Do Not Upload guard was removed"
    for classifier in classifiers:
        assert not classifier.startswith("License ::"), f"license classifier appeared: {classifier}"


# --------------------------------------------------------------------------- #
# the one private-release workflow gates on repo privacy, requests no id-token  #
# --------------------------------------------------------------------------- #
def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_private_release_workflow_asserts_repository_is_private_at_runtime() -> None:
    text = _workflow_text()
    # The runtime privacy signal is read from the event payload...
    assert re.search(r"REPO_PRIVATE:\s*\$\{\{\s*github\.event\.repository\.private\s*\}\}", text), (
        "workflow does not bind github.event.repository.private"
    )
    # ...and the build refuses to proceed unless it is exactly "true".
    assert re.search(r'"\$REPO_PRIVATE"\s*!=\s*"true"', text), "workflow has no private!=true guard"
    assert "exit 1" in text, "workflow privacy guard does not fail closed"


def test_private_release_workflow_requests_no_id_token() -> None:
    text = _workflow_text()
    assert "id-token" not in text, "workflow requests an OIDC id-token"
    # It runs read-only: the only declared permission is contents: read.
    assert re.search(r"permissions:\s*\n\s*contents:\s*read", text), "workflow is not contents:read"
