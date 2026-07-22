"""V2C section 35 (OQ-E): the operational-qualification SOURCE FREEZE.

Fixes the SHA-256 of the exact source that *defines* the offline operational qualification --
the candidate-free execution firewall, the synthetic event stream and fault schedule, the
virtual-time harness, the resource and crash/recovery campaigns, the SLO contract, the append-only
OQ registry, the prospective-proposal governance, the inactive activation template, the
process-isolated buyer boundary, and the readiness derivation -- **before** the qualification is
registered (OQ-R) and executed (OQ-P).

The freeze is a pure function of the committed source: :func:`verify_oq_source_freeze` re-derives it
from the live tree and refuses any drift, so a reader can prove the qualification source was fixed
on a green tree and did not change between the freeze and the run. The manifest lives under
``governance/v2c/`` -- outside the frozen ``research/`` and ``release/`` roots pinned by the V2A-V2B
freeze table -- so the freeze adds evidence without touching the frozen stack. Nothing here
evaluates a strategy; it hashes source bytes only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.environment import CANONICAL_RUNTIME_CONTRACT_RELPATH
from eth_research.m3d.validation import M3DValidationError
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    canonical_sha256,
    require_mapping,
    sha256_bytes,
    strict_json_loads,
)
from eth_research.v2c.oq.registry import OQ_REGISTRY_PATH
from eth_research.v2c.oq.supersession import (
    OQ_SUPERSESSION_PATH,
    SEALED_LEDGER_RELPATHS,
    read_supersession,
)

#: The committed location of the OQ source-freeze manifest (governance, not a frozen root).
OQ_SOURCE_FREEZE_RELPATH: str = "governance/v2c/oq_source_freeze.json"
#: Schema 2 == the OQ-E2 replacement freeze (schema 1 was the premature, incomplete OQ-E).
OQ_SOURCE_FREEZE_SCHEMA_VERSION: int = 2
#: The replacement freeze id, and the incomplete OQ-E freeze it replaces.
OQ_E2_FREEZE_ID: str = "v2c_oq_source_freeze_e2"
SUPERSEDED_FREEZE_ID: str = "v2c_oq_source_freeze"
#: The premature OQ-E freeze commit (e4b3cc3) the supersession ledger retires; it can never
#: authorize registration or execution. Bound here so the replacement freeze names what it replaces.
PREMATURE_OQ_FREEZE_COMMIT: str = "e4b3cc3d6ecfa0d58dd4c71c01f06b2e252ba6ee"
#: The SHA-256 of zero bytes -- the pristine registry and every sealed ledger hash to this.
EMPTY_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

#: The committed location of the OQ-E2 activation-anchor artifact (written in the follow-on
#: governance-only commit binding the exact OQ-E2 source-freeze commit; see build_oq_e2_activation).
OQ_E2_ACTIVATION_RELPATH: str = "governance/v2c/oq_e2_activation.json"
OQ_E2_ACTIVATION_SCHEMA_VERSION: int = 1
OQ_E2_ACTIVATION_ID: str = "v2c_oq_e2_activation_001"

#: Domain tag for the source fingerprint, so the frozen-source and frozen-artifact members live
#: under distinct labelled keys and a source file cannot be swapped with an artifact of equal hash.
_FINGERPRINT_DOMAIN: str = "v2c/oq/source-freeze/e2/fingerprint/v1"

_ACTIVATION_STATEMENT = (
    "OQ-E2A activation anchor. This governance-only artifact binds the exact git commit that "
    "carries the reproduced OQ-E2 source freeze (its full 40-hex sha, the frozen manifest's byte "
    "hash and aggregate digest, and the supersession record that retired the premature OQ-E "
    "freeze), written in the follow-on commit after the freeze commit exists so the anchor names a "
    "real, already-committed freeze rather than itself. It authorizes no registration or execution "
    "on its own -- the fail-closed orchestrator gates remain the sole authority -- evaluates no "
    "strategy, and makes no cryptographic attestation (there is no signing key; the commit-to-"
    "freeze link that only git history can prove is recorded honestly, not attested here)."
)

_GIT_SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z")

#: The exact source that defines AND executes the offline operational qualification. OQ-E2 (the
#: replacement freeze) pins the whole transitive qualification-defining surface -- not just the
#: top-level entry points but every project-owned module that can alter a qualification result or a
#: lifecycle decision: the candidate-free firewall, the synthetic event/fault/instrument/clock/SLO
#: definitions, the cash-control execution platform (the shadow runner/paper/risk/adapter/journal/
#: checkpoint/kill-switch/monitoring), the registry + supersession governance, the orchestrator,
#: publisher, completion intent, recovery/finalizer, immutable archive, independent oracle, the
#: replay/status/verification CLIs, the process-isolated buyer boundary, the prospective governance,
#: the readiness derivation, and the shared strict validation / canonical serialization / durable-io
#: / runtime-contract helpers they depend on. Curated (not a glob) so the scope is auditable, and
#: cross-checked by a drift test against the live OQ import closure so no qualification-defining
#: module can silently drop out and no unrelated module can silently enter. ``freeze.py`` itself is
#: excluded (it computes the freeze; a self-reference would be circular).
_FROZEN_SOURCE_RELPATHS: tuple[str, ...] = (
    # Shared strict validation, canonical serialization, durable IO, runtime contract, error trees.
    "src/eth_research/_atomic.py",
    "src/eth_research/_json.py",
    "src/eth_research/data/provenance.py",
    "src/eth_research/data/schema.py",
    "src/eth_research/data/validation.py",
    "src/eth_research/environment.py",
    "src/eth_research/fractional/validation.py",
    "src/eth_research/m3d/validation.py",
    "src/eth_research/publication.py",
    "src/eth_research/v2/strict.py",
    # First-gate candidate-free firewall.
    "src/eth_research/v2c/firewall.py",
    # Cash-control execution platform (what the qualification actually runs).
    "src/eth_research/shadow/adapter.py",
    "src/eth_research/shadow/checkpoint.py",
    "src/eth_research/shadow/clock.py",
    "src/eth_research/shadow/domain.py",
    "src/eth_research/shadow/journal.py",
    "src/eth_research/shadow/kill_switch.py",
    "src/eth_research/shadow/market_data.py",
    "src/eth_research/shadow/monitoring.py",
    "src/eth_research/shadow/paper.py",
    "src/eth_research/shadow/risk.py",
    "src/eth_research/shadow/runner.py",
    "src/eth_research/shadow/signal.py",
    # OQ definition + orchestration + acceptance surface (freeze.py excluded: it is the freezer).
    "src/eth_research/v2c/oq/archive.py",
    "src/eth_research/v2c/oq/cli.py",
    "src/eth_research/v2c/oq/completion.py",
    "src/eth_research/v2c/oq/events.py",
    "src/eth_research/v2c/oq/finalize.py",
    "src/eth_research/v2c/oq/harness.py",
    "src/eth_research/v2c/oq/oracle.py",
    "src/eth_research/v2c/oq/orchestrator.py",
    "src/eth_research/v2c/oq/protocol.py",
    "src/eth_research/v2c/oq/recovery.py",
    "src/eth_research/v2c/oq/registry.py",
    "src/eth_research/v2c/oq/resources.py",
    "src/eth_research/v2c/oq/result.py",
    "src/eth_research/v2c/oq/run.py",
    "src/eth_research/v2c/oq/slo.py",
    "src/eth_research/v2c/oq/supersession.py",
    "src/eth_research/v2c/oq/verify_archive.py",
    # Offline prospective-proposal governance + inactive activation template.
    "src/eth_research/v2c/prospective.py",
    "src/eth_research/v2c/proposal.py",
    "src/eth_research/v2c/proposal_generator.py",
    "src/eth_research/v2c/maturity.py",
    "src/eth_research/v2c/activation_template.py",
    # Process-isolated buyer boundary + source-free harness + the V2A buyer artifacts it drives.
    "src/eth_research/buyer/claims.py",
    "src/eth_research/buyer/contract.py",
    "src/eth_research/buyer/diligence.py",
    "src/eth_research/buyer/factsheet.py",
    "src/eth_research/buyer/gateway.py",
    "src/eth_research/buyer/redaction.py",
    "src/eth_research/buyer/scorecard.py",
    "src/eth_research/v2c/buyer/boundary.py",
    "src/eth_research/v2c/buyer/framing.py",
    "src/eth_research/v2c/buyer/harness.py",
    "src/eth_research/v2c/buyer/isolation.py",
    # Readiness derivation (sell_ready is derived false).
    "src/eth_research/v2c/readiness.py",
)

#: Non-source artifacts also pinned by the freeze: the milestone plan and the inactive template.
_FROZEN_ARTIFACT_RELPATHS: tuple[str, ...] = (
    "docs/V2C_PLAN.md",
    "governance/v2c/inactive_workflow_templates/v2c-prospective-update-probe.yml.inactive",
)

_FREEZE_STATEMENT = (
    "OQ-E2 replacement freeze. The complete transitive source that defines AND executes the V2C "
    "offline operational qualification -- the candidate-free firewall, the synthetic event/fault/"
    "instrument/clock/SLO definitions, the cash-control execution platform, the registry and "
    "supersession governance, the orchestrator, publisher, completion intent, recovery/finalizer, "
    "immutable archive, independent oracle, the replay/status/verification CLIs, the "
    "process-isolated buyer boundary, the prospective governance, the readiness derivation, and "
    "the shared strict-validation / canonical-serialization / durable-io / runtime-contract "
    "helpers -- was fixed on a green tree, superseding the incomplete OQ-E freeze, before the "
    "qualification was registered (OQ-R) and executed (OQ-P). The OQ registry and all three sealed "
    "access ledgers were byte-empty at the freeze. It evaluates no strategy, computes no market "
    "performance, and authorizes no financial evaluation. These are operational hash-bound "
    "controls over committed bytes, not a cryptographic attestation (no signing key exists)."
)


class OQSourceFreezeError(V2ValidationError):
    """The committed OQ source freeze drifted from the live qualification source."""


def _read_bytes(repo_root: Path, relpath: str) -> bytes:
    """Read a frozen member's bytes, refusing a symlink, a traversal/absolute escape, or a miss.

    ``relpath`` is joined under ``repo_root`` and its real path must stay inside the resolved root,
    so an absolute path, a ``..`` traversal, or a symlink out of the tree is refused fail-closed.
    """
    raw = repo_root / relpath
    if raw.is_symlink():
        raise OQSourceFreezeError(f"{relpath} is a symlink")
    path = raw.resolve()
    if not path.is_relative_to(repo_root.resolve()):
        raise OQSourceFreezeError(f"{relpath} escapes the repository root")
    if not path.is_file():
        raise OQSourceFreezeError(f"{relpath} is missing from the qualification source")
    return path.read_bytes()


def _require_git_sha(label: str, value: object) -> str:
    if not isinstance(value, str) or not _GIT_SHA_RE.match(value):
        raise OQSourceFreezeError(f"{label} must be a 40-hex lowercase git commit sha")
    return value


def _distinct(relpaths: tuple[str, ...]) -> tuple[str, ...]:
    """Refuse a duplicated frozen relpath (a dict comprehension would silently collapse it)."""
    if len(set(relpaths)) != len(relpaths):
        raise OQSourceFreezeError("the frozen relpath list contains a duplicate")
    return relpaths


def _superseding_record(root: Path) -> Any:
    """The fully verified supersession record that retired the premature OQ-E freeze.

    Reading the ledger through :func:`read_supersession` verifies its whole hash chain, so the
    freeze binds a *validated* supersession event, not a raw line. Refuses if the premature freeze
    is not recorded superseded (the replacement freeze cannot honestly name what it replaces).
    """
    records = read_supersession(root / OQ_SUPERSESSION_PATH)
    for record in records:
        if record.superseded_commit == PREMATURE_OQ_FREEZE_COMMIT:
            return record
    raise OQSourceFreezeError(
        "the premature OQ-E freeze is not recorded superseded; OQ-E2 cannot bind its supersession"
    )


def build_oq_source_freeze(repo_root: str | Path) -> dict[str, Any]:
    """Derive the OQ-E2 source-freeze dict from the live qualification source + governance state.

    A pure, deterministic function of committed bytes (no wall clock): it hashes the whole
    transitive qualification-defining source and the two pinned artifacts, binds the runtime
    contract identity, the validated supersession record that retired the premature OQ-E freeze,
    and the pristine registry / sealed-ledger preconditions the freeze was created under, and closes
    with a domain-separated source fingerprint and a whole-body aggregate digest. It reads no live
    registry (the registry legitimately becomes non-empty after OQ-R, so the freeze declares the
    *expected* pristine state rather than measuring the current one) and evaluates no strategy.
    """
    root = Path(repo_root)
    source = {
        rel: sha256_bytes(_read_bytes(root, rel))
        for rel in sorted(_distinct(_FROZEN_SOURCE_RELPATHS))
    }
    artifacts = {
        rel: sha256_bytes(_read_bytes(root, rel))
        for rel in sorted(_distinct(_FROZEN_ARTIFACT_RELPATHS))
    }
    runtime_contract_sha256 = sha256_bytes(_read_bytes(root, CANONICAL_RUNTIME_CONTRACT_RELPATH))
    record = _superseding_record(root)
    source_fingerprint = canonical_sha256(
        {
            "domain": _FINGERPRINT_DOMAIN,
            "frozen_source_sha256": source,
            "frozen_artifact_sha256": artifacts,
        }
    )
    body: dict[str, Any] = {
        "schema_version": OQ_SOURCE_FREEZE_SCHEMA_VERSION,
        "freeze_id": OQ_E2_FREEZE_ID,
        "replaces_freeze_id": SUPERSEDED_FREEZE_ID,
        "superseded_freeze_commit": PREMATURE_OQ_FREEZE_COMMIT,
        "superseded_freeze_relpath": record.superseded_freeze_relpath,
        "superseded_freeze_artifact_sha256": record.superseded_freeze_artifact_sha256,
        "supersession_record_sha256": record.entry_hash,
        "package_version": PACKAGE_VERSION,
        "runtime_contract_relpath": CANONICAL_RUNTIME_CONTRACT_RELPATH,
        "runtime_contract_sha256": runtime_contract_sha256,
        "expected_registry": {
            "relpath": OQ_REGISTRY_PATH,
            "sha256": EMPTY_SHA256,
            "byte_count": 0,
            "event_count": 0,
        },
        "expected_sealed_ledgers": {
            rel: {"sha256": EMPTY_SHA256, "byte_count": 0} for rel in sorted(SEALED_LEDGER_RELPATHS)
        },
        "statement": _FREEZE_STATEMENT,
        "frozen_source_sha256": source,
        "frozen_artifact_sha256": artifacts,
        "source_fingerprint_sha256": source_fingerprint,
    }
    body["source_freeze_digest"] = canonical_sha256(body)
    return body


def render_oq_source_freeze_bytes(freeze: dict[str, Any]) -> bytes:
    """Serialize the freeze dict to canonical JSON bytes (sorted keys, trailing newline)."""
    return canonical_json_bytes(freeze)


def oq_source_freeze_digest(repo_root: str | Path) -> str:
    """The aggregate freeze digest derived from the live source (bound by OQ-R at registration)."""
    freeze = build_oq_source_freeze(repo_root)
    digest = freeze["source_freeze_digest"]
    assert isinstance(digest, str)
    return digest


def verify_oq_source_freeze(repo_root: str | Path) -> None:
    """The committed manifest must reproduce byte-for-byte from the live qualification source."""
    root = Path(repo_root)
    committed = (root / OQ_SOURCE_FREEZE_RELPATH).read_bytes()
    fresh = render_oq_source_freeze_bytes(build_oq_source_freeze(root))
    if committed != fresh:
        raise OQSourceFreezeError(
            "committed oq_source_freeze.json does not reproduce from the live source "
            "(qualification source changed after the OQ-E freeze)"
        )


def write_oq_source_freeze(repo_root: str | Path) -> Path:
    """(Re)write the committed freeze manifest from the live source; return its path."""
    root = Path(repo_root)
    path = root / OQ_SOURCE_FREEZE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_oq_source_freeze_bytes(build_oq_source_freeze(root)))
    return path


# --------------------------------------------------------------------------- #
# OQ-E2A: the governance-only activation anchor (§9C non-circular pattern)     #
# --------------------------------------------------------------------------- #
def build_oq_e2_activation(repo_root: str | Path, *, source_freeze_commit: str) -> dict[str, Any]:
    """Derive the OQ-E2A activation anchor binding the named OQ-E2 source-freeze commit.

    Written in the follow-on commit *after* the OQ-E2 freeze commit exists (a commit cannot embed
    its own hash). It re-verifies the committed freeze reproduces from live source, then binds that
    freeze's byte hash + aggregate digest + supersession-record hash to the named 40-hex commit. A
    pure function of committed bytes: no wall clock, no strategy, and no cryptographic attestation.
    """
    root = Path(repo_root)
    commit = _require_git_sha("source_freeze_commit", source_freeze_commit)
    verify_oq_source_freeze(root)
    freeze_bytes = (root / OQ_SOURCE_FREEZE_RELPATH).read_bytes()
    freeze = build_oq_source_freeze(root)
    body: dict[str, Any] = {
        "schema_version": OQ_E2_ACTIVATION_SCHEMA_VERSION,
        "activation_id": OQ_E2_ACTIVATION_ID,
        "freeze_id": OQ_E2_FREEZE_ID,
        "source_freeze_commit": commit,
        "source_freeze_relpath": OQ_SOURCE_FREEZE_RELPATH,
        "source_freeze_artifact_sha256": sha256_bytes(freeze_bytes),
        "source_freeze_digest": freeze["source_freeze_digest"],
        "supersession_record_sha256": freeze["supersession_record_sha256"],
        "superseded_freeze_commit": PREMATURE_OQ_FREEZE_COMMIT,
        "statement": _ACTIVATION_STATEMENT,
    }
    body["activation_digest"] = canonical_sha256(body)
    return body


def render_oq_e2_activation_bytes(activation: dict[str, Any]) -> bytes:
    """Serialize the activation anchor to canonical JSON bytes (sorted keys, trailing newline)."""
    return canonical_json_bytes(activation)


def verify_oq_e2_activation(repo_root: str | Path) -> None:
    """The committed activation anchor must reproduce from the live OQ-E2 freeze it names.

    Re-derives the anchor from the live freeze and the commit recorded inside the committed anchor,
    then byte-compares. This proves the anchor binds the current, reproducing freeze; the one fact
    only git history can settle -- that the named commit is genuinely the freeze commit -- is
    recorded honestly, not attested here.
    """
    root = Path(repo_root)
    path = root / OQ_E2_ACTIVATION_RELPATH
    if path.is_symlink():
        raise OQSourceFreezeError("the OQ-E2 activation anchor must not be a symlink")
    if not path.is_file():
        raise OQSourceFreezeError("the OQ-E2 activation anchor is missing")
    committed = path.read_bytes()
    try:
        obj = require_mapping("oq_e2_activation", strict_json_loads(committed))
    except (V2ValidationError, M3DValidationError) as exc:
        raise OQSourceFreezeError(f"the OQ-E2 activation anchor is not valid JSON: {exc}") from exc
    commit = _require_git_sha(
        "oq_e2_activation.source_freeze_commit", obj.get("source_freeze_commit")
    )
    fresh = render_oq_e2_activation_bytes(build_oq_e2_activation(root, source_freeze_commit=commit))
    if committed != fresh:
        raise OQSourceFreezeError(
            "committed oq_e2_activation.json does not reproduce from the live OQ-E2 freeze "
            "(the activation anchor drifted from the frozen source it names)"
        )


def write_oq_e2_activation(repo_root: str | Path, *, source_freeze_commit: str) -> Path:
    """(Re)write the committed activation anchor for the named freeze commit; return its path."""
    root = Path(repo_root)
    path = root / OQ_E2_ACTIVATION_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        render_oq_e2_activation_bytes(
            build_oq_e2_activation(root, source_freeze_commit=source_freeze_commit)
        )
    )
    return path


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse
    import json

    parser = argparse.ArgumentParser(description="V2C OQ source freeze (OQ-E2, read-only verify)")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--emit", action="store_true", help="print the derived freeze JSON")
    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    if args.emit:
        print(render_oq_source_freeze_bytes(build_oq_source_freeze(root)).decode())
        return 0
    try:
        verify_oq_source_freeze(root)
        # Verify the activation anchor too once it exists (it is written in the follow-on commit).
        if (root / OQ_E2_ACTIVATION_RELPATH).exists():
            verify_oq_e2_activation(root)
    except (OSError, V2ValidationError, M3DValidationError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "OQ_E2_ACTIVATION_ID",
    "OQ_E2_ACTIVATION_RELPATH",
    "OQ_E2_ACTIVATION_SCHEMA_VERSION",
    "OQ_E2_FREEZE_ID",
    "OQ_SOURCE_FREEZE_RELPATH",
    "OQ_SOURCE_FREEZE_SCHEMA_VERSION",
    "PREMATURE_OQ_FREEZE_COMMIT",
    "SUPERSEDED_FREEZE_ID",
    "OQSourceFreezeError",
    "build_oq_e2_activation",
    "build_oq_source_freeze",
    "oq_source_freeze_digest",
    "render_oq_e2_activation_bytes",
    "render_oq_source_freeze_bytes",
    "verify_oq_e2_activation",
    "verify_oq_source_freeze",
    "write_oq_e2_activation",
    "write_oq_source_freeze",
]
