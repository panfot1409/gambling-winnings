"""Deterministic R-phase registration for the Milestone 4B portfolio research simulator.

Five source-derived artifacts pin the additive v1.1 portfolio layer under ``research/m4b/`` without
committing a single binary or contacting a network: the synthetic reference universe's identity, the
reference protocol's identity, the expected results of the reference run (``result_id`` and the
headline scalars, so a fresh clone can prove byte-exact reproduction), the portfolio subpackage's
distribution manifest (its shipped members and their content hashes), and a source-freeze that binds
every committed M4B artifact, the accepted M4A v1.0 artifacts (proving additivity/no-drift), and the
three sealed governance ledgers (proving they stay byte-empty). Every artifact is canonical JSON
keyed by a schema version, and ``--check`` fails closed on drift so a freeze that silently perturbs
the layer is caught in review — the freeze identity stays recoverable.

This module is pure, offline, and stdlib-plus-package only: it regenerates the synthetic reference
universe from code, reads the committed artifact bytes and the sealed ledgers, and never builds,
uploads, mutates a tracked file, or reaches the network. It mirrors the accepted
:mod:`eth_research.m4a.release` exactly, scoped to the additive portfolio layer. The public-API
snapshot is registered separately by :mod:`eth_research.portfolio.public_api`
(``research/m4b/public_api.json``); this module binds that snapshot by content hash rather than
reproducing it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from eth_research.api.serialization import canonical_json_bytes, sha256_hex, strict_load_canonical
from eth_research.portfolio import M4B_PACKAGE_VERSION
from eth_research.portfolio.cli_reference import REFERENCE_RELPATH as CLI_REFERENCE_RELPATH
from eth_research.portfolio.engine import run_portfolio_simulation
from eth_research.portfolio.metrics import compute_portfolio_metrics
from eth_research.portfolio.protocol import PortfolioProtocol
from eth_research.portfolio.public_api import M4B_API_VERSION
from eth_research.portfolio.public_api import SNAPSHOT_RELPATH as PUBLIC_API_RELPATH
from eth_research.portfolio.reference import (
    ReferenceUniverse,
    build_reference_universe,
    reference_protocol,
)
from eth_research.portfolio.result import (
    RESULT_SCHEMA_VERSION,
    PortfolioResult,
    build_portfolio_result,
)
from eth_research.portfolio.streaming import CHECKPOINT_SCHEMA_VERSION
from eth_research.portfolio.trace import TRACE_SCHEMA_VERSION
from eth_research.portfolio.universe import UNIVERSE_SCHEMA_VERSION

REGISTRATION_SCHEMA_VERSION = 1

_SECONDS_PER_YEAR = 365.25 * 24.0 * 3600.0

REFERENCE_UNIVERSE_RELPATH = "research/m4b/reference_universe.json"
REFERENCE_PROTOCOL_RELPATH = "research/m4b/reference_protocol.json"
REFERENCE_RESULTS_RELPATH = "research/m4b/reference_expected_results.json"
DISTRIBUTION_MANIFEST_RELPATH = "research/m4b/distribution_manifest.json"
SOURCE_FREEZE_RELPATH = "research/m4b/source_freeze.json"

#: The three sealed governance ledgers that must stay byte-empty across the freeze.
SEALED_LEDGERS = (
    "research/m3a/development_gate_access.jsonl",
    "research/m2b/test_evaluations.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)
#: sha256 of the empty byte string — the required digest of every sealed ledger.
EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

#: The accepted M4A v1.0 artifacts. The freeze binds each by content hash, proving the additive M4B
#: layer leaves every accepted artifact byte-for-byte unchanged.
M4A_ACCEPTED_ARTIFACTS = (
    "research/m4a/public_api.json",
    "research/m4a/cli_reference.txt",
    "research/m4a/distribution_manifest.json",
    "research/m4a/distribution_dependencies.json",
    "research/m4a/release_candidate_state.json",
    "research/m4a/distribution_proof.json",
)

#: The committed M4B artifacts the source-freeze binds (every governed research/m4b/ file except the
#: freeze itself, which cannot hash its own bytes).
_M4B_FROZEN_ARTIFACTS = (
    PUBLIC_API_RELPATH,
    CLI_REFERENCE_RELPATH,
    REFERENCE_UNIVERSE_RELPATH,
    REFERENCE_PROTOCOL_RELPATH,
    REFERENCE_RESULTS_RELPATH,
    DISTRIBUTION_MANIFEST_RELPATH,
)


class RegistrationDriftError(RuntimeError):
    """A committed M4B registration artifact no longer matches the running source."""


# --------------------------------------------------------------------------- #
# the reference run (a pure function of the package source)                    #
# --------------------------------------------------------------------------- #
def _reference_run_result(
    reference: ReferenceUniverse, protocol: PortfolioProtocol
) -> PortfolioResult:
    run = run_portfolio_simulation(
        protocol,
        reference.panel,
        reference.membership,
        reference.fx,
        reference.run_schedule,
        calendars=reference.calendars,
        corporate_actions=reference.corporate_actions,
    )
    periods_per_year = _SECONDS_PER_YEAR / reference.universe_spec.bar_interval_seconds
    metrics = compute_portfolio_metrics(run, periods_per_year=periods_per_year)
    return build_portfolio_result(run, metrics, reference.universe_spec)


# --------------------------------------------------------------------------- #
# builders (each is a pure function of the source tree)                        #
# --------------------------------------------------------------------------- #
def build_reference_universe_registration(repo_root: Path) -> dict[str, Any]:
    reference = build_reference_universe()
    spec = reference.universe_spec
    return {
        "registration_schema_version": REGISTRATION_SCHEMA_VERSION,
        "package_version": M4B_PACKAGE_VERSION,
        "universe_schema_version": UNIVERSE_SCHEMA_VERSION,
        "universe_fingerprint": spec.fingerprint,
        "panel_fingerprint": reference.panel.fingerprint,
        "membership_fingerprint": reference.membership.fingerprint,
        "fx_fingerprint": reference.fx.fingerprint,
        "corporate_action_fingerprint": reference.corporate_actions.fingerprint,
        "rebalance_schedule_fingerprint": reference.run_schedule.fingerprint,
        "calendar_fingerprints": [
            {
                "calendar_id": calendar_id,
                "fingerprint": reference.calendars[calendar_id].fingerprint,
            }
            for calendar_id in sorted(reference.calendars)
        ],
        "universe_spec": spec.canonical(),
    }


def build_reference_protocol_registration(repo_root: Path) -> dict[str, Any]:
    protocol = reference_protocol()
    return {
        "registration_schema_version": REGISTRATION_SCHEMA_VERSION,
        "package_version": M4B_PACKAGE_VERSION,
        "protocol_fingerprint": protocol.fingerprint,
        "protocol": protocol.canonical(),
    }


def build_reference_expected_results(repo_root: Path) -> dict[str, Any]:
    reference = build_reference_universe()
    result = _reference_run_result(reference, reference_protocol())
    return {
        "registration_schema_version": REGISTRATION_SCHEMA_VERSION,
        "package_version": M4B_PACKAGE_VERSION,
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "universe_fingerprint": result.universe_fingerprint,
        "protocol_fingerprint": result.protocol_fingerprint,
        "run_result_fingerprint": result.run_result_fingerprint,
        "final_state_fingerprint": result.final_state_fingerprint,
        "trace_commitment_id": result.trace_commitment.commitment_id,
        "result_id": result.result_id,
        "base_currency": result.base_currency,
        "initial_equity": result.initial_equity,
        "terminal_equity": result.terminal_equity,
        "num_fills": result.num_fills,
        "cost_total": result.cost_total,
        "event_count": result.trace_commitment.event_count,
    }


def _portfolio_members(repo_root: Path) -> list[dict[str, Any]]:
    """The pure-Python files of the additive portfolio subpackage, sorted, with content hashes."""
    pkg = repo_root / "src" / "eth_research"
    portfolio = pkg / "portfolio"
    members: list[dict[str, Any]] = []
    for path in sorted(portfolio.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if not (path.suffix in (".py", ".pyi") or path.name == "py.typed"):
            continue
        data = path.read_bytes()
        members.append(
            {
                "path": path.relative_to(pkg.parent).as_posix(),
                "sha256": sha256_hex(data),
                "size": len(data),
            }
        )
    return members


def build_distribution_manifest(repo_root: Path) -> dict[str, Any]:
    members = _portfolio_members(repo_root)
    return {
        "registration_schema_version": REGISTRATION_SCHEMA_VERSION,
        "package": "eth-research",
        "version": M4B_PACKAGE_VERSION,
        "layer": "portfolio",
        "member_count": len(members),
        "portfolio_members": members,
        "portfolio_tree_sha256": sha256_hex(canonical_json_bytes(members)),
    }


def _bound_sha256(repo_root: Path, rel: str) -> str:
    """The sha256 of a bound artifact, failing closed as drift if it is missing/unreadable.

    ``build_source_freeze`` binds artifacts beyond the five it also builds (the public-API snapshot,
    the CLI reference, the accepted M4A artifacts, the sealed ledgers), so a raw ``OSError`` here
    must surface as :class:`RegistrationDriftError`: a missing bound artifact is drift, not a crash.
    """
    try:
        return sha256_hex((repo_root / rel).read_bytes())
    except OSError as exc:
        raise RegistrationDriftError(f"bound artifact missing/unreadable: {rel}: {exc}") from exc


def build_source_freeze(repo_root: Path) -> dict[str, Any]:
    ledgers = {rel: _bound_sha256(repo_root, rel) for rel in SEALED_LEDGERS}
    m4b_hashes = {rel: _bound_sha256(repo_root, rel) for rel in _M4B_FROZEN_ARTIFACTS}
    m4a_hashes = {rel: _bound_sha256(repo_root, rel) for rel in M4A_ACCEPTED_ARTIFACTS}
    return {
        "registration_schema_version": REGISTRATION_SCHEMA_VERSION,
        "package": "eth-research",
        "package_version": M4B_PACKAGE_VERSION,
        "api_version": M4B_API_VERSION,
        "schema_versions": {
            "universe": UNIVERSE_SCHEMA_VERSION,
            "result": RESULT_SCHEMA_VERSION,
            "checkpoint": CHECKPOINT_SCHEMA_VERSION,
            "trace": TRACE_SCHEMA_VERSION,
        },
        "sealed_ledgers": ledgers,
        "m4b_frozen_artifacts": m4b_hashes,
        "m4a_accepted_artifacts": m4a_hashes,
        "forbidden_capabilities_absent": True,
    }


_BUILDERS = {
    REFERENCE_UNIVERSE_RELPATH: build_reference_universe_registration,
    REFERENCE_PROTOCOL_RELPATH: build_reference_protocol_registration,
    REFERENCE_RESULTS_RELPATH: build_reference_expected_results,
    DISTRIBUTION_MANIFEST_RELPATH: build_distribution_manifest,
    # source_freeze is written last: it binds the byte-hashes of the artifacts above.
    SOURCE_FREEZE_RELPATH: build_source_freeze,
}


# --------------------------------------------------------------------------- #
# write / verify                                                              #
# --------------------------------------------------------------------------- #
def write(repo_root: str | Path) -> list[str]:
    root = Path(repo_root)
    written: list[str] = []
    for relpath, builder in _BUILDERS.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes(builder(root)))
        written.append(relpath)
    return written


def verify(repo_root: str | Path) -> None:
    """Raise :class:`RegistrationDriftError` unless every committed M4B artifact matches source."""
    root = Path(repo_root)
    for relpath, builder in _BUILDERS.items():
        path = root / relpath
        try:
            committed = path.read_bytes()
        except OSError as exc:
            raise RegistrationDriftError(
                f"M4B registration artifact missing: {relpath}: {exc}"
            ) from exc
        fresh = canonical_json_bytes(builder(root))
        recanonical = canonical_json_bytes(strict_load_canonical(committed, relpath))
        if recanonical != fresh:
            raise RegistrationDriftError(
                f"{relpath} is stale; regenerate with "
                f"`python -m eth_research.portfolio.registration --write`"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M4B registration artifacts: --check or --write.")
    parser.add_argument("--repo-root", default=".")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="verify the committed artifacts")
    group.add_argument("--write", action="store_true", help="(re)write the committed artifacts")
    args = parser.parse_args(argv)
    if args.write:
        for relpath in write(args.repo_root):
            sys.stdout.write(f"wrote {relpath}\n")
        return 0
    try:
        verify(args.repo_root)
    except RegistrationDriftError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    sys.stdout.write("M4B registration artifacts are current\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
