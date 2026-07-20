"""V2A-V2B section 10 -- the permanent legacy-research moratorium."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from eth_research.v2.strict import canonical_json_bytes, sha256_bytes, strict_json_loads
from eth_research.v2ab.moratorium import (
    CLOSED_STATUS,
    CLOSURE_RELPATH,
    HistoricalReplayAuthorization,
    MoratoriumError,
    authorize_historical_replay,
    build_closure,
    guard_operation,
    load_closure,
    parse_closure,
    verify_closure,
)

_ALIGNED_FP = "a" * 64
_ETH_FP = "b" * 64
_BTC_FP = "c" * 64


def _seed(root: Path) -> None:
    """A synthetic repo tree with the exact source artifacts the closure binds."""
    (root / "research/v2b").mkdir(parents=True)
    (root / "research/v2").mkdir(parents=True)
    (root / "research/v2b/joint_partition_identity.json").write_bytes(
        canonical_json_bytes(
            {
                "combined_partition_fingerprint": _ALIGNED_FP,
                "eth_content_fingerprint": _ETH_FP,
                "btc_content_fingerprint": _BTC_FP,
                "first_open": "2016-05-23T00:00:00Z",
                "last_open": "2022-06-21T00:00:00Z",
            }
        )
    )
    (root / "research/v2b/research_family_catalog.json").write_bytes(
        canonical_json_bytes({"families": 10})
    )
    (root / "research/v2b/research_multiplicity_state.json").write_bytes(
        canonical_json_bytes({"total_family_count": 10})
    )
    (root / "research/v2/negative_evidence_index.jsonl").write_bytes(b'{"family": "x"}\n')


def _write_closure(root: Path) -> dict[str, object]:
    closure = build_closure(root)
    (root / CLOSURE_RELPATH).write_bytes(canonical_json_bytes(closure))
    return closure


def test_build_and_verify_clean(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_closure(tmp_path)
    assert verify_closure(tmp_path) == []
    closure = load_closure(tmp_path)
    assert closure.closure_status == CLOSED_STATUS
    assert closure.aligned_partition_fingerprint == _ALIGNED_FP


def test_authorized_replay_of_committed_experiment_is_allowed(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_closure(tmp_path)
    auth = authorize_historical_replay(
        tmp_path,
        experiment_id="v2b_run_001",
        partition_fingerprint=_ALIGNED_FP,
        package_version="2.0.0.dev1",
    )
    # An allowed replay/verify operation with a matching token does not raise.
    guard_operation(
        tmp_path,
        "historical_replay",
        experiment_id="v2b_run_001",
        partition_fingerprint=_ALIGNED_FP,
        package_version="2.0.0.dev1",
        replay_authorization=auth,
    )


def test_new_candidate_evaluation_is_refused_unconditionally(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_closure(tmp_path)
    with pytest.raises(MoratoriumError):
        guard_operation(tmp_path, "evaluate_new_candidate")
    # Even a (nonsensical) attempt to pass a token cannot authorize a forbidden op.
    auth = authorize_historical_replay(
        tmp_path,
        experiment_id="v2a_run_001",
        partition_fingerprint=_ALIGNED_FP,
        package_version="2.0.0.dev1",
    )
    with pytest.raises(MoratoriumError):
        guard_operation(tmp_path, "run_new_experiment", replay_authorization=auth)


def test_direct_authorization_construction_is_forbidden(tmp_path: Path) -> None:
    with pytest.raises(MoratoriumError):
        HistoricalReplayAuthorization("v2b_run_001", _ALIGNED_FP, "2.0.0.dev1", _token=object())


def test_allowed_operation_without_token_is_refused(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_closure(tmp_path)
    with pytest.raises(MoratoriumError):
        guard_operation(
            tmp_path,
            "historical_replay",
            experiment_id="v2b_run_001",
            partition_fingerprint=_ALIGNED_FP,
            package_version="2.0.0.dev1",
        )


def test_changed_experiment_id_refuses(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_closure(tmp_path)
    with pytest.raises(MoratoriumError):
        authorize_historical_replay(
            tmp_path,
            experiment_id="v2c_run_001",  # not a committed historical experiment
            partition_fingerprint=_ALIGNED_FP,
            package_version="2.0.0.dev1",
        )


def test_copied_or_recombined_partition_refuses(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_closure(tmp_path)
    with pytest.raises(MoratoriumError):
        authorize_historical_replay(
            tmp_path,
            experiment_id="v2b_run_001",
            partition_fingerprint="d" * 64,  # different fingerprint
            package_version="2.0.0.dev1",
        )


def test_new_package_version_refuses(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_closure(tmp_path)
    with pytest.raises(MoratoriumError):
        authorize_historical_replay(
            tmp_path,
            experiment_id="v2b_run_001",
            partition_fingerprint=_ALIGNED_FP,
            package_version="2.0.0.dev2",  # freshness-via-new-version
        )


def test_token_does_not_authorize_a_different_requested_identity(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_closure(tmp_path)
    auth = authorize_historical_replay(
        tmp_path,
        experiment_id="v2a_run_001",
        partition_fingerprint=_ALIGNED_FP,
        package_version="2.0.0.dev1",
    )
    with pytest.raises(MoratoriumError):
        guard_operation(
            tmp_path,
            "historical_replay",
            experiment_id="v2b_run_001",  # mismatch vs the token's bound identity
            partition_fingerprint=_ALIGNED_FP,
            package_version="2.0.0.dev1",
            replay_authorization=auth,
        )


def test_deleted_closure_refuses(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_closure(tmp_path)
    (tmp_path / CLOSURE_RELPATH).unlink()
    assert verify_closure(tmp_path)  # non-empty problems
    with pytest.raises(MoratoriumError):
        load_closure(tmp_path)


def test_symlinked_closure_refuses(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_closure(tmp_path)
    real = tmp_path / CLOSURE_RELPATH
    moved = tmp_path / "research/v2/closure_real.json"
    real.rename(moved)
    os.symlink(moved, real)
    with pytest.raises(MoratoriumError):
        load_closure(tmp_path)


def test_forged_open_status_refuses(tmp_path: Path) -> None:
    _seed(tmp_path)
    closure = _write_closure(tmp_path)
    tampered = dict(closure)
    tampered["closure_status"] = "open"  # forge the status
    (tmp_path / CLOSURE_RELPATH).write_bytes(canonical_json_bytes(tampered))
    # Digest no longer binds -> parse rejects; even if it did, the status choice is constrained.
    with pytest.raises(MoratoriumError):
        parse_closure((tmp_path / CLOSURE_RELPATH).read_bytes())


def test_changed_effective_commit_refuses(tmp_path: Path) -> None:
    _seed(tmp_path)
    closure = _write_closure(tmp_path)
    tampered = dict(closure)
    tampered["effective_after_commit"] = "0" * 40
    (tmp_path / CLOSURE_RELPATH).write_bytes(canonical_json_bytes(tampered))
    with pytest.raises(MoratoriumError):
        parse_closure((tmp_path / CLOSURE_RELPATH).read_bytes())


def test_same_fingerprint_different_path_family_catalog_refuses(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_closure(tmp_path)
    # Substitute the live family catalog bytes (same closure, drifted source) -> rebind must fail.
    (tmp_path / "research/v2b/research_family_catalog.json").write_bytes(
        canonical_json_bytes({"families": 99})
    )
    with pytest.raises(MoratoriumError):
        load_closure(tmp_path)


def test_negative_evidence_index_substitution_refuses(tmp_path: Path) -> None:
    _seed(tmp_path)
    _write_closure(tmp_path)
    (tmp_path / "research/v2/negative_evidence_index.jsonl").write_bytes(b'{"family": "y"}\n')
    with pytest.raises(MoratoriumError):
        load_closure(tmp_path)


def test_build_without_negative_evidence_index_refuses(tmp_path: Path) -> None:
    _seed(tmp_path)
    (tmp_path / "research/v2/negative_evidence_index.jsonl").unlink()
    with pytest.raises(MoratoriumError):
        build_closure(tmp_path)


def test_closure_digest_binds_the_body(tmp_path: Path) -> None:
    _seed(tmp_path)
    closure = _write_closure(tmp_path)
    obj = strict_json_loads((tmp_path / CLOSURE_RELPATH).read_bytes())
    body = {k: obj[k] for k in obj if k != "closure_digest"}
    from eth_research.v2ab.moratorium import _digest_of_body

    assert sha256_bytes(b"") != obj["closure_digest"]
    assert _digest_of_body(body) == closure["closure_digest"]
