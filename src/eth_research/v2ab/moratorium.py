"""The permanent legacy-research moratorium (section 10).

This is the mandatory scientific decision of the stacked acceptance: the historical research
partitions used by M3/V2A/V2B (aligned ETH/BTC daily history through 2022-06-21) are CLOSED to
further candidate-nomination research. V2A tested three pre-registered ETH families and nominated
none; V2B added a genuinely new BTC information source, tested two pre-registered cross-asset
families under a cumulative multiplicity correction, and nominated none. Inventing more
candidates on the same interval would convert disciplined research into strategy mining;
this module prevents that.

The closure is enforced through an unforgeable ``HistoricalReplayAuthorization`` that only the
approved factory (:func:`authorize_historical_replay`) can mint, and only for an EXACT committed
historical experiment on the EXACT committed partition and package version. A new or disguised
evaluation (a changed experiment id, protocol, candidate label, partition fingerprint, or package
version) is refused before any candidate calculation, engine invocation, registry ``started``
append, or result publication. No ordinary caller can set a ``replay=True`` flag; the token is the
only signal, and it cannot be forged.

This is a POST-RUN governance addition. The closure artifact records that it post-dates the accepted
V2B terminal state and never claims to have existed before the V2A/V2B executions.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    require_choice,
    require_exact_keys,
    require_list,
    require_mapping,
    require_nonempty_str,
    require_sha256_fingerprint,
    sha256_bytes,
    strict_json_loads,
)

CLOSURE_SCHEMA_VERSION: int = 1
CLOSURE_RELPATH: str = "research/v2/research_partition_closure.json"

#: The accepted V2B terminal state this post-run closure descends from (documentation only).
EFFECTIVE_AFTER_COMMIT: str = "5798610389af0905331fc5da20f54f4b8f7930fb"

CLOSED_STATUS: str = "closed_to_new_candidate_nomination_research"

_DIGEST_DOMAIN: bytes = b"eth_research.v2ab.research_partition_closure.v1\n"
_REPLAY_SENTINEL: object = object()

#: Bound source artifacts (path + committed identity) whose bytes the closure freezes.
_ALIGNED_PARTITION_RELPATH: str = "research/v2b/joint_partition_identity.json"
_FAMILY_CATALOG_RELPATH: str = "research/v2b/research_family_catalog.json"
_MULTIPLICITY_RELPATH: str = "research/v2b/research_multiplicity_state.json"
_NEGATIVE_EVIDENCE_RELPATH: str = "research/v2/negative_evidence_index.jsonl"

#: The exact committed historical experiments the closure permits EXACT replay of.
_HISTORICAL_EXPERIMENTS: tuple[str, ...] = ("v2a_run_001", "v2b_run_001")

#: The package version the accepted results were produced under (a replay must match it).
_ACCEPTED_PACKAGE_VERSION: str = "2.0.0.dev1"

ALLOWED_OPERATIONS: frozenset[str] = frozenset(
    {
        "byte_verification",
        "historical_replay",
        "regression_test",
        "independent_result_reconstruction",
        "documentation",
        "integrity_hashing",
        "compatibility_test",
        "accepted_result_rendering",
        "calculation_free_recovery",
    }
)

FORBIDDEN_OPERATIONS: frozenset[str] = frozenset(
    {
        "evaluate_new_candidate",
        "evaluate_modified_candidate",
        "add_primary_configuration",
        "change_nomination_threshold",
        "run_new_experiment",
        "open_new_research_budget",
        "claim_freshness_via_new_version",
        "claim_freshness_via_new_benchmark",
        "recombine_and_claim_new_trial",
        "promote_sensitivity_output_to_candidate",
        "read_sealed_to_choose_family",
    }
)

_CLOSURE_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "closure_id",
        "closure_reason",
        "effective_after_commit",
        "post_run_addition",
        "eth_content_fingerprint",
        "btc_content_fingerprint",
        "aligned_partition_fingerprint",
        "first_open",
        "last_open",
        "historical_experiments",
        "cumulative_family_catalog_sha256",
        "multiplicity_state_sha256",
        "negative_evidence_index_sha256",
        "accepted_package_version",
        "closure_status",
        "allowed_operations",
        "forbidden_operations",
        "supersession_policy",
        "closure_digest",
    }
)


class MoratoriumError(V2ValidationError):
    """The closure was malformed/tampered, or a forbidden operation was attempted."""


@dataclass(frozen=True, slots=True)
class PartitionClosure:
    """The parsed, verified legacy-research partition closure."""

    closure_id: str
    aligned_partition_fingerprint: str
    eth_content_fingerprint: str
    btc_content_fingerprint: str
    first_open: str
    last_open: str
    historical_experiments: tuple[str, ...]
    cumulative_family_catalog_sha256: str
    negative_evidence_index_sha256: str
    accepted_package_version: str
    closure_status: str
    closure_digest: str


class HistoricalReplayAuthorization:
    """An unforgeable authorization for the EXACT replay of one committed historical experiment.

    It can only be minted by :func:`authorize_historical_replay`; direct construction raises. It
    binds the exact experiment id, partition fingerprint, and package version, so a disguised new
    evaluation cannot reuse it.
    """

    __slots__ = ("experiment_id", "package_version", "partition_fingerprint")

    def __init__(
        self,
        experiment_id: str,
        partition_fingerprint: str,
        package_version: str,
        *,
        _token: object,
    ) -> None:
        if _token is not _REPLAY_SENTINEL:
            raise MoratoriumError(
                "HistoricalReplayAuthorization cannot be constructed directly; "
                "use authorize_historical_replay()"
            )
        self.experiment_id = experiment_id
        self.partition_fingerprint = partition_fingerprint
        self.package_version = package_version


def _closure_body(
    *,
    aligned_fp: str,
    eth_fp: str,
    btc_fp: str,
    first_open: str,
    last_open: str,
    catalog_sha: str,
    multiplicity_sha: str,
    negative_evidence_sha: str,
) -> dict[str, object]:
    return {
        "schema_version": CLOSURE_SCHEMA_VERSION,
        "closure_id": "legacy_research_partition_closure_v1",
        "closure_reason": (
            "V2A nominated no ETH candidate (3 families) and V2B no cross-asset candidate "
            "(2 families) under cumulative multiplicity; the historical partitions are closed to "
            "further candidate-nomination research to prevent strategy mining."
        ),
        "effective_after_commit": EFFECTIVE_AFTER_COMMIT,
        "post_run_addition": True,
        "eth_content_fingerprint": eth_fp,
        "btc_content_fingerprint": btc_fp,
        "aligned_partition_fingerprint": aligned_fp,
        "first_open": first_open,
        "last_open": last_open,
        "historical_experiments": list(_HISTORICAL_EXPERIMENTS),
        "cumulative_family_catalog_sha256": catalog_sha,
        "multiplicity_state_sha256": multiplicity_sha,
        "negative_evidence_index_sha256": negative_evidence_sha,
        "accepted_package_version": _ACCEPTED_PACKAGE_VERSION,
        "closure_status": CLOSED_STATUS,
        "allowed_operations": sorted(ALLOWED_OPERATIONS),
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "supersession_policy": (
            "This closure is permanent for the legacy partitions. Future research requires a "
            "separately-authorized, new prospective dataset or domain under its own governance; "
            "it does not reopen these partitions."
        ),
    }


def _digest_of_body(body: dict[str, object]) -> str:
    return sha256_bytes(_DIGEST_DOMAIN + canonical_json_bytes(body))


def _read_sha(repo_root: Path, relpath: str) -> str:
    return sha256_bytes((repo_root / relpath).read_bytes())


def build_closure(repo_root: str | Path) -> dict[str, object]:
    """Compute the canonical closure from the live committed artifacts (never mutates anything)."""
    root = Path(repo_root)
    joint = strict_json_loads((root / _ALIGNED_PARTITION_RELPATH).read_bytes())
    aligned_fp = require_sha256_fingerprint(
        "joint.combined_partition_fingerprint", joint["combined_partition_fingerprint"]
    )
    eth_fp = require_sha256_fingerprint(
        "joint.eth_content_fingerprint", joint["eth_content_fingerprint"]
    )
    btc_fp = require_sha256_fingerprint(
        "joint.btc_content_fingerprint", joint["btc_content_fingerprint"]
    )
    first_open = require_nonempty_str("joint.first_open", joint["first_open"])
    last_open = require_nonempty_str("joint.last_open", joint["last_open"])
    neg_index = root / _NEGATIVE_EVIDENCE_RELPATH
    if not neg_index.exists():
        raise MoratoriumError(
            f"cannot build the closure: {_NEGATIVE_EVIDENCE_RELPATH} does not exist yet"
        )
    body = _closure_body(
        aligned_fp=aligned_fp,
        eth_fp=eth_fp,
        btc_fp=btc_fp,
        first_open=first_open,
        last_open=last_open,
        catalog_sha=_read_sha(root, _FAMILY_CATALOG_RELPATH),
        multiplicity_sha=_read_sha(root, _MULTIPLICITY_RELPATH),
        negative_evidence_sha=_read_sha(root, _NEGATIVE_EVIDENCE_RELPATH),
    )
    closure = dict(body)
    closure["closure_digest"] = _digest_of_body(body)
    return closure


def parse_closure(raw_bytes: bytes) -> PartitionClosure:
    """Strictly parse committed closure bytes and re-verify the self-binding digest."""
    obj = require_mapping("closure", strict_json_loads(raw_bytes))
    require_exact_keys("closure", obj, _CLOSURE_KEYS)
    if obj["schema_version"] != CLOSURE_SCHEMA_VERSION:
        raise MoratoriumError("unexpected closure schema_version")
    body = {k: obj[k] for k in obj if k != "closure_digest"}
    recomputed = _digest_of_body(body)
    committed = require_sha256_fingerprint("closure.closure_digest", obj["closure_digest"])
    if recomputed != committed:
        raise MoratoriumError("closure self digest does not bind the committed body")
    experiments = require_list(
        "closure.historical_experiments",
        obj["historical_experiments"],
        require_nonempty_str,
    )
    return PartitionClosure(
        closure_id=require_nonempty_str("closure.closure_id", obj["closure_id"]),
        aligned_partition_fingerprint=require_sha256_fingerprint(
            "closure.aligned_partition_fingerprint", obj["aligned_partition_fingerprint"]
        ),
        eth_content_fingerprint=require_sha256_fingerprint(
            "closure.eth_content_fingerprint", obj["eth_content_fingerprint"]
        ),
        btc_content_fingerprint=require_sha256_fingerprint(
            "closure.btc_content_fingerprint", obj["btc_content_fingerprint"]
        ),
        first_open=require_nonempty_str("closure.first_open", obj["first_open"]),
        last_open=require_nonempty_str("closure.last_open", obj["last_open"]),
        historical_experiments=tuple(experiments),
        cumulative_family_catalog_sha256=require_sha256_fingerprint(
            "closure.cumulative_family_catalog_sha256", obj["cumulative_family_catalog_sha256"]
        ),
        negative_evidence_index_sha256=require_sha256_fingerprint(
            "closure.negative_evidence_index_sha256", obj["negative_evidence_index_sha256"]
        ),
        accepted_package_version=require_nonempty_str(
            "closure.accepted_package_version", obj["accepted_package_version"]
        ),
        closure_status=require_choice(
            "closure.closure_status", obj["closure_status"], frozenset({CLOSED_STATUS})
        ),
        closure_digest=committed,
    )


def load_closure(repo_root: str | Path) -> PartitionClosure:
    """Load + verify the committed closure, and re-bind it to the live source artifacts.

    Rejects a symlinked or missing closure, a broken self digest, a forged (non-closed) status,
    and a closure whose bound artifact SHAs no longer match the live tree (a same-fingerprint/
    other-path or drifted source).
    """
    root = Path(repo_root).resolve()
    path = root / CLOSURE_RELPATH
    if path.is_symlink():
        raise MoratoriumError("closure artifact must not be a symlink")
    if not path.exists():
        raise MoratoriumError(f"closure artifact missing at {CLOSURE_RELPATH}")
    closure = parse_closure(path.read_bytes())
    # Re-bind: bound SHAs must equal the live artifacts' SHAs (no path/byte substitution).
    if closure.cumulative_family_catalog_sha256 != _read_sha(root, _FAMILY_CATALOG_RELPATH):
        raise MoratoriumError("closure family-catalog SHA does not match the live catalog")
    if closure.negative_evidence_index_sha256 != _read_sha(root, _NEGATIVE_EVIDENCE_RELPATH):
        raise MoratoriumError("closure negative-evidence-index SHA does not match the live index")
    joint = strict_json_loads((root / _ALIGNED_PARTITION_RELPATH).read_bytes())
    if closure.aligned_partition_fingerprint != joint["combined_partition_fingerprint"]:
        raise MoratoriumError(
            "closure aligned-partition fingerprint does not match the committed partition"
        )
    return closure


def authorize_historical_replay(
    repo_root: str | Path,
    *,
    experiment_id: str,
    partition_fingerprint: str,
    package_version: str,
) -> HistoricalReplayAuthorization:
    """Mint an authorization for EXACT replay of a committed historical experiment.

    Refuses an unknown/changed experiment id, a partition fingerprint that is not the committed
    aligned fingerprint (a copied/re-combined partition), and a package version other than accepted.
    """
    closure = load_closure(repo_root)
    if experiment_id not in closure.historical_experiments:
        raise MoratoriumError(
            f"replay refused: {experiment_id!r} is not a committed historical experiment"
        )
    if partition_fingerprint != closure.aligned_partition_fingerprint:
        raise MoratoriumError(
            "replay refused: partition fingerprint is not the committed aligned partition"
        )
    if package_version != closure.accepted_package_version:
        raise MoratoriumError("replay refused: package version differs from the accepted version")
    return HistoricalReplayAuthorization(
        experiment_id, partition_fingerprint, package_version, _token=_REPLAY_SENTINEL
    )


def guard_operation(
    repo_root: str | Path,
    operation: str,
    *,
    experiment_id: str | None = None,
    partition_fingerprint: str | None = None,
    package_version: str | None = None,
    replay_authorization: HistoricalReplayAuthorization | None = None,
) -> None:
    """Enforce the moratorium BEFORE candidate calc / engine / registry-started / publication.

    A forbidden new-research operation is refused unconditionally (no token can authorize it). An
    allowed replay/verify operation requires an unforgeable HistoricalReplayAuthorization whose
    bound identity exactly matches the requested experiment id, partition fingerprint, and version.
    """
    closure = load_closure(repo_root)
    if closure.closure_status != CLOSED_STATUS:
        raise MoratoriumError("closure status is not the closed status")
    if operation in FORBIDDEN_OPERATIONS:
        raise MoratoriumError(
            f"legacy partitions are closed to new candidate research; refused: {operation!r}"
        )
    if operation not in ALLOWED_OPERATIONS:
        raise MoratoriumError(f"unknown operation {operation!r}")
    # Allowed replay/verify operations still require a valid, matching authorization token.
    if replay_authorization is None:
        raise MoratoriumError(f"operation {operation!r} requires a HistoricalReplayAuthorization")
    if not isinstance(replay_authorization, HistoricalReplayAuthorization):
        raise MoratoriumError("replay_authorization is not a HistoricalReplayAuthorization")
    if (
        replay_authorization.experiment_id != experiment_id
        or replay_authorization.partition_fingerprint != partition_fingerprint
        or replay_authorization.package_version != package_version
    ):
        raise MoratoriumError("replay_authorization does not match the requested identity")
    if experiment_id not in closure.historical_experiments:
        raise MoratoriumError("requested experiment is not a committed historical experiment")


def verify_closure(repo_root: str | Path) -> list[str]:
    """Verify the closure loads, re-binds, and declares the closed status (problems empty=OK)."""
    try:
        closure = load_closure(repo_root)
    except V2ValidationError as exc:
        return [f"closure failed to load/verify: {exc}"]
    problems: list[str] = []
    if closure.closure_status != CLOSED_STATUS:
        problems.append("closure status is not the closed status")
    if tuple(closure.historical_experiments) != _HISTORICAL_EXPERIMENTS:
        problems.append("closure historical experiments differ from the accepted set")
    if closure.accepted_package_version != _ACCEPTED_PACKAGE_VERSION:
        problems.append("closure accepted package version drifted")
    return problems


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse

    parser = argparse.ArgumentParser(
        description="Build or verify the legacy-research partition closure."
    )
    parser.add_argument("--repo-root", default=".")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--build", action="store_true", help="Print the canonical closure to stdout."
    )
    group.add_argument("--check", action="store_true", help="Verify the committed closure.")
    args = parser.parse_args(argv)
    if args.build:
        os.write(1, canonical_json_bytes(build_closure(args.repo_root)))
        return 0
    problems = verify_closure(args.repo_root)
    print(json.dumps({"ok": not problems, "problems": problems}))
    return 0 if not problems else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ALLOWED_OPERATIONS",
    "CLOSED_STATUS",
    "CLOSURE_RELPATH",
    "FORBIDDEN_OPERATIONS",
    "HistoricalReplayAuthorization",
    "MoratoriumError",
    "PartitionClosure",
    "authorize_historical_replay",
    "build_closure",
    "guard_operation",
    "load_closure",
    "parse_closure",
    "verify_closure",
]
