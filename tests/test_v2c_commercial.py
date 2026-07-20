"""V2C sections 28-31: the private commercial-truth pack (data only, candidate-free).

Covers the inactive deployment blueprint, the private SBOM, the IP dossier, and the commercial-
options record: each is a fixed, fingerprint-pinned model that round-trips and rejects drift; the
committed artifacts under ``governance/v2c/commercial/`` reproduce byte-for-byte; ``sell_ready`` is
derived false; and no candidate id or strategy token leaks into a source module or committed file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import eth_research
from eth_research.v2.constitution import STANDING_POSTURE
from eth_research.v2.strict import V2ValidationError
from eth_research.v2c.commercial import evidence
from eth_research.v2c.commercial.deployment import DeploymentBlueprint, DeploymentBlueprintError
from eth_research.v2c.commercial.ip_dossier import IPDossier, IPDossierError
from eth_research.v2c.commercial.options import (
    SELL_READY,
    CommercialOptions,
    CommercialOptionsError,
)
from eth_research.v2c.commercial.sbom import V2C_DEV_VERSION, build_private_sbom
from eth_research.v2c.firewall import KNOWN_LEGACY_CANDIDATE_IDS

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
COMMERCIAL_SRC = Path(eth_research.__file__).resolve().parent / "v2c" / "commercial"


# --------------------------------------------------------------------------- #
# Section 28: inactive deployment blueprint                                   #
# --------------------------------------------------------------------------- #
def test_deployment_blueprint_is_inactive() -> None:
    blueprint: dict[str, Any] = DeploymentBlueprint.current().to_canonical()
    assert blueprint["status"] == "inactive"
    assert blueprint["activated"] is False
    assert blueprint["network_egress_enabled"] is False
    assert blueprint["order_routing_enabled"] is False
    for component in blueprint["components"]:
        assert component["offline"] is True
        assert component["non_routing"] is True
    for precondition in blueprint["activation_preconditions"]:
        assert precondition["met"] is False


def test_deployment_blueprint_roundtrips_and_rejects_drift() -> None:
    current = DeploymentBlueprint.current()
    assert DeploymentBlueprint.parse(current.to_canonical()).fingerprint() == current.fingerprint()
    tampered = current.to_canonical()
    tampered["activated"] = True
    with pytest.raises(DeploymentBlueprintError):
        DeploymentBlueprint.parse(tampered)


def test_deployment_blueprint_rejects_a_met_precondition() -> None:
    tampered: dict[str, Any] = DeploymentBlueprint.current().to_canonical()
    tampered["activation_preconditions"][0]["met"] = True
    with pytest.raises(DeploymentBlueprintError):
        DeploymentBlueprint.parse(tampered)


# --------------------------------------------------------------------------- #
# Section 29: private SBOM                                                     #
# --------------------------------------------------------------------------- #
def test_private_sbom_is_private_and_covers_runtime_deps() -> None:
    sbom: dict[str, Any] = build_private_sbom(REPO_ROOT)
    assert sbom["bomFormat"] == "CycloneDX"
    component = sbom["metadata"]["component"]
    assert component["name"] == "eth-research"
    assert component["version"] == V2C_DEV_VERSION
    props = {p["name"]: p["value"] for p in sbom["metadata"]["properties"]}
    assert props["distribution:classification"] == "private"
    assert props["distribution:public_publication"] == "forbidden"
    names = {c["name"] for c in sbom["components"]}
    for dep in ("numpy", "pandas", "pyarrow"):
        assert dep in names, dep
    assert "eth-research" not in names  # the subject is not double-listed as its own dependency


def test_sbom_version_is_the_frozen_v2c_dev_version() -> None:
    assert eth_research.__version__ == V2C_DEV_VERSION


# --------------------------------------------------------------------------- #
# Section 30: IP dossier                                                       #
# --------------------------------------------------------------------------- #
def test_ip_dossier_discloses_nothing_and_is_honest_about_exposure() -> None:
    dossier: dict[str, Any] = IPDossier.current().to_canonical()
    for category in dossier["categories"]:
        assert category["disclosed_publicly"] is False
        assert category["protection"] == "private_source_withheld"
    assert "no_patent" in dossier["not_protected_by"]
    assert "no_license_granted" in dossier["not_protected_by"]
    assert "reverse engineered" in dossier["reverse_engineering_exposure"]


def test_ip_dossier_roundtrips_and_rejects_drift() -> None:
    current = IPDossier.current()
    assert IPDossier.parse(current.to_canonical()).fingerprint() == current.fingerprint()
    tampered: dict[str, Any] = current.to_canonical()
    tampered["categories"][0]["disclosed_publicly"] = True
    with pytest.raises(IPDossierError):
        IPDossier.parse(tampered)


# --------------------------------------------------------------------------- #
# Section 31: commercial options                                              #
# --------------------------------------------------------------------------- #
def test_commercial_options_is_not_sell_ready() -> None:
    assert SELL_READY is False
    record: dict[str, Any] = CommercialOptions.current().to_canonical()
    assert record["sell_ready"] is False
    assert record["overall_posture"] == STANDING_POSTURE == "not_sell_ready"
    for option in record["options"]:
        assert option["available_now"] is False
        assert option["prerequisites_unmet"]


def test_commercial_options_roundtrips_and_rejects_a_sell_ready_claim() -> None:
    current = CommercialOptions.current()
    assert CommercialOptions.parse(current.to_canonical()).fingerprint() == current.fingerprint()
    tampered = current.to_canonical()
    tampered["sell_ready"] = True
    with pytest.raises(CommercialOptionsError):
        CommercialOptions.parse(tampered)


def test_commercial_option_rejects_available_now() -> None:
    tampered: dict[str, Any] = CommercialOptions.current().to_canonical()
    tampered["options"][0]["available_now"] = True
    with pytest.raises(V2ValidationError):
        CommercialOptions.parse(tampered)


# --------------------------------------------------------------------------- #
# Sections 28-31: committed evidence reproduces and leaks nothing             #
# --------------------------------------------------------------------------- #
def test_committed_evidence_reproduces_byte_for_byte() -> None:
    assert evidence.check(REPO_ROOT) == []


def test_evidence_build_is_deterministic() -> None:
    assert evidence.build_all(REPO_ROOT) == evidence.build_all(REPO_ROOT)


def test_committed_artifacts_are_valid_and_parse() -> None:
    outdir = REPO_ROOT / evidence.EVIDENCE_DIR
    blueprint = json.loads((outdir / evidence.DEPLOYMENT_ARTIFACT).read_bytes())
    DeploymentBlueprint.parse(blueprint)
    dossier = json.loads((outdir / evidence.IP_DOSSIER_ARTIFACT).read_bytes())
    IPDossier.parse(dossier)
    options = json.loads((outdir / evidence.COMMERCIAL_OPTIONS_ARTIFACT).read_bytes())
    CommercialOptions.parse(options)


def test_commercial_pack_leaks_no_candidate_or_strategy_token() -> None:
    # Scan every commercial source module and every committed artifact for a legacy candidate id or
    # a strategy/engine module token. The pack must be strictly candidate-free.
    forbidden = set(KNOWN_LEGACY_CANDIDATE_IDS) | {
        "eth_research.v2.candidates",
        "eth_research.portfolio.engine",
        "_signal_at",
    }
    scanned: list[Path] = sorted(COMMERCIAL_SRC.rglob("*.py"))
    scanned += sorted((REPO_ROOT / evidence.EVIDENCE_DIR).glob("*.json"))
    assert scanned, "expected commercial source and committed artifacts to scan"
    for path in scanned:
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path.name} leaks {token!r}"
