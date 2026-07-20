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

from pathlib import Path
from typing import Any

from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    canonical_sha256,
    sha256_bytes,
)

#: The committed location of the OQ source-freeze manifest (governance, not a frozen root).
OQ_SOURCE_FREEZE_RELPATH: str = "governance/v2c/oq_source_freeze.json"
OQ_SOURCE_FREEZE_SCHEMA_VERSION: int = 1

#: The exact source that defines the offline operational qualification. Curated (not a glob) so the
#: freeze scope is auditable and stable, and so the OQ-R/OQ-P/OQ-Q tooling that *uses* the freeze is
#: deliberately excluded -- the freeze pins what the qualification *is*, not how it is orchestrated.
_FROZEN_SOURCE_RELPATHS: tuple[str, ...] = (
    # First-gate candidate-free firewall.
    "src/eth_research/v2c/firewall.py",
    # Synthetic event stream + fault schedule, harness, resources, recovery, SLO contract, registry.
    "src/eth_research/v2c/oq/events.py",
    "src/eth_research/v2c/oq/harness.py",
    "src/eth_research/v2c/oq/resources.py",
    "src/eth_research/v2c/oq/recovery.py",
    "src/eth_research/v2c/oq/slo.py",
    "src/eth_research/v2c/oq/registry.py",
    # Offline prospective-proposal governance + inactive activation template.
    "src/eth_research/v2c/prospective.py",
    "src/eth_research/v2c/proposal.py",
    "src/eth_research/v2c/proposal_generator.py",
    "src/eth_research/v2c/maturity.py",
    "src/eth_research/v2c/activation_template.py",
    # Process-isolated buyer boundary + source-free harness.
    "src/eth_research/v2c/buyer/framing.py",
    "src/eth_research/v2c/buyer/boundary.py",
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
    "The source that defines the V2C offline operational qualification -- the candidate-free "
    "firewall, the synthetic event stream and fault schedule, the virtual-time harness, the "
    "resource and crash/recovery campaigns, the SLO contract, the OQ registry, the prospective "
    "governance, the inactive activation template, the process-isolated buyer boundary, and the "
    "readiness derivation -- was fixed on a green tree before the qualification was registered "
    "(OQ-R) and executed (OQ-P). It evaluates no strategy and computes no market performance."
)


class OQSourceFreezeError(V2ValidationError):
    """The committed OQ source freeze drifted from the live qualification source."""


def _read_bytes(repo_root: Path, relpath: str) -> bytes:
    raw = repo_root / relpath
    if raw.is_symlink():
        raise OQSourceFreezeError(f"{relpath} is a symlink")
    path = raw.resolve()
    if not path.is_relative_to(repo_root.resolve()):
        raise OQSourceFreezeError(f"{relpath} escapes the repository root")
    if not path.is_file():
        raise OQSourceFreezeError(f"{relpath} is missing from the qualification source")
    return path.read_bytes()


def build_oq_source_freeze(repo_root: str | Path) -> dict[str, Any]:
    """Derive the OQ source-freeze dict from the live qualification source (pure hash of bytes)."""
    root = Path(repo_root)
    source = {rel: sha256_bytes(_read_bytes(root, rel)) for rel in sorted(_FROZEN_SOURCE_RELPATHS)}
    artifacts = {
        rel: sha256_bytes(_read_bytes(root, rel)) for rel in sorted(_FROZEN_ARTIFACT_RELPATHS)
    }
    return {
        "schema_version": OQ_SOURCE_FREEZE_SCHEMA_VERSION,
        "freeze_id": "v2c_oq_source_freeze",
        "statement": _FREEZE_STATEMENT,
        "frozen_source_sha256": source,
        "frozen_artifact_sha256": artifacts,
        "source_freeze_digest": canonical_sha256({**source, **artifacts}),
    }


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


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse
    import json

    parser = argparse.ArgumentParser(description="V2C OQ source freeze (OQ-E, read-only verify)")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--emit", action="store_true", help="print the derived freeze JSON")
    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    if args.emit:
        print(render_oq_source_freeze_bytes(build_oq_source_freeze(root)).decode())
        return 0
    try:
        verify_oq_source_freeze(root)
    except (OSError, V2ValidationError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "OQ_SOURCE_FREEZE_RELPATH",
    "OQ_SOURCE_FREEZE_SCHEMA_VERSION",
    "OQSourceFreezeError",
    "build_oq_source_freeze",
    "oq_source_freeze_digest",
    "render_oq_source_freeze_bytes",
    "verify_oq_source_freeze",
    "write_oq_source_freeze",
]
