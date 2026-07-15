"""Append-only data-use ledger and sealed-partition firewall.

``research/m3d/research_data_use.jsonl`` records every legitimate historical data
use — M2B train/validation benchmark research and the M3A/M3B/M3C research-train
development uses — and asserts, against the committed access ledgers, that the
development gate and final holdout had **zero** strategy access. Each entry states
whether strategy signals, P&L, and metrics were computed, and binds the source
artifacts that prove it.

The firewall is symmetric: a *sealed* partition (development gate, final holdout)
must declare ``sealed_untouched`` with no signals/P&L/metrics and its access ledger
must be byte-empty, while a *used* partition must declare a real use — so neither a
false "a sealed partition was used" claim nor a false "a used partition was unused"
claim can pass :func:`verify_research_data_use`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eth_research.m3d import _upstream as up
from eth_research.m3d.chain import chained_line_bytes, load_and_verify_chain, render_ledger_bytes
from eth_research.m3d.validation import (
    M3DValidationError,
    require_bool,
    require_mapping,
    require_str,
)

LEDGER_PATH = "research/m3d/research_data_use.jsonl"
LEDGER_SCHEMA_VERSION = 1
LEDGER_KIND = "research_data_use_ledger"

_USE_TYPES = (
    "integrity_only",
    "schema_quality",
    "research_development",
    "replay_only",
    "sealed_untouched",
)
_SEALED_PARTITIONS = {"development_gate", "final_holdout"}
_USED_PARTITIONS = {"m2b_train", "m2b_validation", "research_train"}


def _artifact_refs(repo_root: str | Path, paths: list[str]) -> list[dict[str, str]]:
    return [{"path": path, "sha256": up.hash_file(repo_root, path)} for path in paths]


def _entry(
    *,
    partition: str,
    milestone: str,
    experiment: str | None,
    use_type: str,
    fingerprint: str,
    first_open: str | None,
    last_open: str | None,
    row_count: int | None,
    signals: bool,
    pnl: bool,
    metrics: bool,
    access_ledger: str | None,
    access_events: int | None,
    source_artifacts: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "entry_kind": "data_use",
        "partition": partition,
        "milestone": milestone,
        "experiment": experiment,
        "use_type": use_type,
        "dataset_fingerprint": fingerprint,
        "first_open": first_open,
        "last_open": last_open,
        "row_count": row_count,
        "signals_computed": signals,
        "pnl_computed": pnl,
        "metrics_computed": metrics,
        "access_ledger_path": access_ledger,
        "access_ledger_event_count": access_events,
        "source_artifacts": source_artifacts,
    }


def _partition_facts(repo_root: str | Path) -> dict[str, dict[str, Any]]:
    """Boundaries/fingerprints for research_train, development_gate, final_holdout."""
    partition_doc = require_mapping(
        "development_partition", up.load_json(repo_root, "research/m3a/development_partition.json")
    )
    facts: dict[str, dict[str, Any]] = {}
    for item in partition_doc["partitions"]:
        mapping = require_mapping("partition", item)
        facts[require_str("partition name", mapping["name"])] = {
            "fingerprint": require_str("fingerprint", mapping["content_fingerprint"]),
            "first_open": require_str("first_open", mapping["first_open_time"]),
            "last_open": require_str("last_open", mapping["last_open_time"]),
            "row_count": mapping["row_count"],
        }
    return facts


def _build_records(repo_root: str | Path) -> list[dict[str, Any]]:
    from eth_research.m3d import M3D_PACKAGE_VERSION

    facts = _partition_facts(repo_root)
    train = facts["research_train"]
    gate = facts["development_gate"]
    holdout = facts["final_holdout"]

    gate_events = up.ledger_facts(repo_root, up.SEALED_LEDGERS["development_gate"])["event_count"]
    holdout_events = up.ledger_facts(repo_root, up.SEALED_LEDGERS["final_holdout"])["event_count"]

    genesis = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": LEDGER_KIND,
        "entry_kind": "genesis",
        "package_version": M3D_PACKAGE_VERSION,
        "note": "development gate and final holdout had zero strategy access",
    }

    records: list[dict[str, Any]] = [genesis]

    # M2B benchmark research used the train and validation windows.
    records.append(
        _entry(
            partition="m2b_train",
            milestone="m2b",
            experiment="m2b-train-validation-benchmark",
            use_type="research_development",
            fingerprint=train["fingerprint"],
            first_open=train["first_open"],
            last_open=train["last_open"],
            row_count=train["row_count"],
            signals=True,
            pnl=True,
            metrics=True,
            access_ledger=None,
            access_events=None,
            source_artifacts=_artifact_refs(
                repo_root,
                ["research/m2b/dataset_lock.json", "research/m2b/train_validation_results.json"],
            ),
        )
    )
    records.append(
        _entry(
            partition="m2b_validation",
            milestone="m2b",
            experiment="m2b-train-validation-benchmark",
            use_type="research_development",
            fingerprint=gate["fingerprint"],
            first_open=gate["first_open"],
            last_open=gate["last_open"],
            row_count=gate["row_count"],
            signals=True,
            pnl=True,
            metrics=True,
            access_ledger=None,
            access_events=None,
            source_artifacts=_artifact_refs(
                repo_root, ["research/m2b/train_validation_results.json"]
            ),
        )
    )

    # M3A/M3B/M3C development uses of the research-train partition.
    for milestone, experiment, sources in (
        (
            "m3a",
            None,
            ["research/m3a/development_partition.json", "research/m3a/development_results.json"],
        ),
        (
            "m3b",
            "m3b-fractional-execution-risk-v1-run-001",
            ["research/m3b/fractional_results.json"],
        ),
        ("m3c", "m3c-dual-horizon-trend-v1-run-001", ["research/m3c/candidate_results.json"]),
    ):
        records.append(
            _entry(
                partition="research_train",
                milestone=milestone,
                experiment=experiment,
                use_type="research_development",
                fingerprint=train["fingerprint"],
                first_open=train["first_open"],
                last_open=train["last_open"],
                row_count=train["row_count"],
                signals=True,
                pnl=True,
                metrics=True,
                access_ledger=None,
                access_events=None,
                source_artifacts=_artifact_refs(repo_root, sources),
            )
        )

    # Sealed partitions: zero strategy access, proven by the byte-empty ledgers.
    records.append(
        _entry(
            partition="development_gate",
            milestone="m3a",
            experiment=None,
            use_type="sealed_untouched",
            fingerprint=gate["fingerprint"],
            first_open=gate["first_open"],
            last_open=gate["last_open"],
            row_count=gate["row_count"],
            signals=False,
            pnl=False,
            metrics=False,
            access_ledger=up.SEALED_LEDGERS["development_gate"],
            access_events=gate_events,
            source_artifacts=_artifact_refs(repo_root, ["research/m3a/development_partition.json"]),
        )
    )
    records.append(
        _entry(
            partition="final_holdout",
            milestone="m2b",
            experiment=None,
            use_type="sealed_untouched",
            fingerprint=holdout["fingerprint"],
            first_open=holdout["first_open"],
            last_open=holdout["last_open"],
            row_count=holdout["row_count"],
            signals=False,
            pnl=False,
            metrics=False,
            access_ledger=up.SEALED_LEDGERS["final_holdout"],
            access_events=holdout_events,
            source_artifacts=_artifact_refs(
                repo_root,
                ["research/m2b/holdout_identity.json", "research/m3a/development_partition.json"],
            ),
        )
    )

    # The prospective M3D cohort is deliberately NOT recorded here: this ledger is
    # the frozen record of *historical* research data use (M2B/M3A/M3B/M3C) and the
    # sealed-partition firewall, whereas the future-only prospective cohort's
    # complete data-use record (schema/quality only, no signals/P&L/metrics) lives
    # in the cohort manifest. Keeping it out preserves this ledger's byte identity
    # and avoids a provenance cascade into the exhaustion anchor that binds it.
    return records


def build_data_use_ledger_bytes(repo_root: str | Path) -> bytes:
    """Deterministically render the full data-use ledger file bytes."""
    return render_ledger_bytes(chained_line_bytes(_build_records(repo_root)))


def verify_research_data_use(repo_root: str | Path) -> list[dict[str, Any]]:
    """Verify the committed data-use ledger reproduces and the firewall holds.

    Fails on chain breakage, on a non-exact rebuild, on any unknown use type, or on
    any false claim: a sealed partition that declares a real use (or whose access
    ledger is non-empty), or a used partition that declares no metrics.
    """
    _raw, records = load_and_verify_chain(repo_root, LEDGER_PATH)

    genesis = records[0]
    if genesis.get("entry_kind") != "genesis" or genesis.get("kind") != LEDGER_KIND:
        raise M3DValidationError("data-use ledger is missing its genesis sentinel")

    for entry in records[1:]:
        partition = require_str("partition", entry["partition"])
        use_type = require_str("use_type", entry["use_type"])
        if use_type not in _USE_TYPES:
            raise M3DValidationError(f"unknown data-use type {use_type!r}")
        signals = require_bool("signals_computed", entry["signals_computed"])
        pnl = require_bool("pnl_computed", entry["pnl_computed"])
        metrics = require_bool("metrics_computed", entry["metrics_computed"])

        if partition in _SEALED_PARTITIONS:
            if use_type != "sealed_untouched" or signals or pnl or metrics:
                raise M3DValidationError(f"sealed partition {partition} must not declare any use")
            ledger_path = require_str("access_ledger_path", entry["access_ledger_path"])
            facts = up.ledger_facts(repo_root, ledger_path)
            if facts["byte_count"] != 0 or facts["event_count"] != 0:
                raise M3DValidationError(f"sealed partition {partition} access ledger is not empty")
            if entry["access_ledger_event_count"] != 0:
                raise M3DValidationError(
                    f"sealed partition {partition} claims nonzero access events"
                )
        elif partition in _USED_PARTITIONS:
            if use_type != "research_development" or not metrics:
                raise M3DValidationError(f"used partition {partition} must declare a real use")

    if _raw != build_data_use_ledger_bytes(repo_root):
        raise M3DValidationError("committed data-use ledger does not match the rebuilt ledger")
    return records
