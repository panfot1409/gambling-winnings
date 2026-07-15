"""Preregistered, immutable prospective-cohort protocol and empty evaluation ledger.

``research/m3d/prospective_protocol.json`` pins — before any acquisition — the
identity, source endpoint, interval, timestamp convention, fixed cohort start, its
strictly-after-M2B relationship, the acquisition rules (completed UTC days only,
no forming candle, no backfill/gap-fill/interpolation/sort/dedup/substitution
repair), the data-only prohibitions (no strategy/candidate identifiers, no
performance endpoints, no promotion rule, no optimization, no evaluation
authorization), and the hard maturity policy (>=365 consecutive completed daily
candles; maturity means data availability only and never authorizes evaluation).

``research/m3d/prospective_evaluations.jsonl`` is created and tracked at exactly
zero bytes. No M3D code appends it; only :func:`require_prospective_evaluation_ledger_empty`
reads it, and any event is a hard stop.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research.m3d import _upstream as up
from eth_research.m3d.validation import (
    M3DValidationError,
    canonical_json_bytes,
    canonical_sha256,
    load_canonical_json_bytes,
    require_bool,
    require_exact,
    require_mapping,
    require_positive_int,
    require_str,
    require_string_sequence,
    sha256_bytes,
)

PROTOCOL_PATH = "research/m3d/prospective_protocol.json"
PROTOCOL_SCHEMA_VERSION = 1
PROTOCOL_KIND = "prospective_cohort_protocol"

EVALUATION_LEDGER_PATH = up.PROSPECTIVE_EVALUATION_LEDGER

# Pinned identity + rules (immutable once committed).
COHORT_START = "2026-07-12T00:00:00Z"
NOMINAL_MATURITY_LAST_OPEN = "2027-07-11T00:00:00Z"
NOMINAL_MATURITY_EXCLUSIVE_END = "2027-07-12T00:00:00Z"
MINIMUM_MATURITY_ROWS = 365
COINBASE_ENDPOINT = "https://api.exchange.coinbase.com/products/ETH-USD/candles"
COINBASE_DOCUMENTATION_URL = (
    "https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles"
)

_IDENTITY = {
    "base_asset": "ETH",
    "quote_asset": "USD",
    "symbol": "ETH-USD",
    "venue": "coinbase-exchange",
    "market_type": "spot",
    "interval_iso8601": "P1DT0H0M0S",
    "interval_days": 1,
    "timestamp_convention": "candle_open_utc",
}
_ACQUISITION_RULES = {
    "completed_utc_days_only": True,
    "no_forming_candle": True,
    "no_backfill_before_start": True,
    "no_gap_filling": True,
    "no_interpolation": True,
    "no_sorting_repair": True,
    "no_duplicate_repair": True,
    "no_data_substitution": True,
}
_PROHIBITIONS = {
    "no_strategy_identifiers": True,
    "no_candidate_identifiers": True,
    "no_performance_endpoints": True,
    "no_promotion_rule": True,
    "no_optimization": True,
    "no_evaluation_authorization": True,
}
_FUTURE_EVALUATION_REQUIREMENTS = (
    "separate_human_authorized_milestone",
    "new_protocol",
    "candidate_declared_before_access",
    "new_single_use_evaluation_ledger",
)


def _z(timestamp: pd.Timestamp) -> str:
    return timestamp.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class ProspectiveCohortProtocol:
    document: dict[str, Any]

    @classmethod
    def from_mapping(cls, doc: object) -> ProspectiveCohortProtocol:
        mapping = require_mapping("protocol", doc)
        _require_exact_keys(
            "protocol",
            mapping,
            {
                "schema_version",
                "kind",
                "package_version",
                "identity",
                "source",
                "cohort_start",
                "relationship_to_m2b",
                "acquisition_rules",
                "prohibitions",
                "maturity",
                "future_evaluation_requirements",
                "evaluation_ledger",
                "immutable",
            },
        )
        schema_version = require_exact(
            "schema_version",
            require_positive_int("schema_version", mapping["schema_version"]),
            PROTOCOL_SCHEMA_VERSION,
        )
        kind = require_exact("kind", require_str("kind", mapping["kind"]), PROTOCOL_KIND)
        package_version = require_str("package_version", mapping["package_version"])

        identity = _require_exact_dict("identity", mapping["identity"], _IDENTITY)
        source = require_mapping("source", mapping["source"])
        _require_exact_keys("source", source, {"endpoint", "documentation_url"})
        source_out = {
            "endpoint": require_exact(
                "source.endpoint",
                require_str("source.endpoint", source["endpoint"]),
                COINBASE_ENDPOINT,
            ),
            "documentation_url": require_str(
                "source.documentation_url", source["documentation_url"]
            ),
        }

        cohort_start = require_exact(
            "cohort_start", require_str("cohort_start", mapping["cohort_start"]), COHORT_START
        )
        relationship = require_mapping("relationship_to_m2b", mapping["relationship_to_m2b"])
        _require_exact_keys(
            "relationship_to_m2b",
            relationship,
            {"final_m2b_candle_open", "strictly_after", "zero_overlap"},
        )
        relationship_out = {
            "final_m2b_candle_open": require_str(
                "relationship_to_m2b.final_m2b_candle_open", relationship["final_m2b_candle_open"]
            ),
            "strictly_after": require_exact(
                "relationship_to_m2b.strictly_after",
                require_bool("relationship_to_m2b.strictly_after", relationship["strictly_after"]),
                True,
            ),
            "zero_overlap": require_exact(
                "relationship_to_m2b.zero_overlap",
                require_bool("relationship_to_m2b.zero_overlap", relationship["zero_overlap"]),
                True,
            ),
        }
        acquisition_rules = _require_exact_dict(
            "acquisition_rules", mapping["acquisition_rules"], _ACQUISITION_RULES
        )
        prohibitions = _require_exact_dict("prohibitions", mapping["prohibitions"], _PROHIBITIONS)

        maturity = _validate_maturity("maturity", mapping["maturity"])
        future = require_string_sequence(
            "future_evaluation_requirements", mapping["future_evaluation_requirements"]
        )
        if tuple(future) != _FUTURE_EVALUATION_REQUIREMENTS:
            raise M3DValidationError("future_evaluation_requirements must match the pinned list")

        evaluation_ledger = require_mapping("evaluation_ledger", mapping["evaluation_ledger"])
        _require_exact_keys(
            "evaluation_ledger",
            evaluation_ledger,
            {"path", "must_be_byte_empty", "expected_sha256"},
        )
        evaluation_ledger_out = {
            "path": require_exact(
                "evaluation_ledger.path",
                require_str("evaluation_ledger.path", evaluation_ledger["path"]),
                EVALUATION_LEDGER_PATH,
            ),
            "must_be_byte_empty": require_exact(
                "evaluation_ledger.must_be_byte_empty",
                require_bool(
                    "evaluation_ledger.must_be_byte_empty", evaluation_ledger["must_be_byte_empty"]
                ),
                True,
            ),
            "expected_sha256": require_exact(
                "evaluation_ledger.expected_sha256",
                require_str(
                    "evaluation_ledger.expected_sha256", evaluation_ledger["expected_sha256"]
                ),
                up.EMPTY_SHA256,
            ),
        }
        immutable = require_exact(
            "immutable", require_bool("immutable", mapping["immutable"]), True
        )

        # Cohort start must be strictly after the final M2B candle (zero overlap).
        start_ts = pd.Timestamp(cohort_start)
        m2b_last = pd.Timestamp(relationship_out["final_m2b_candle_open"])
        if not start_ts > m2b_last:
            raise M3DValidationError("cohort_start must be strictly after the final M2B candle")
        if start_ts - m2b_last != pd.Timedelta(days=1):
            raise M3DValidationError(
                "cohort_start must be exactly one day after the final M2B candle"
            )

        # No strategy/candidate identifier may appear anywhere in the protocol.
        if up.M3C_CANDIDATE_ID in canonical_json_bytes(mapping).decode("utf-8"):
            raise M3DValidationError("prospective protocol must not name any strategy/candidate")

        document = {
            "schema_version": schema_version,
            "kind": kind,
            "package_version": package_version,
            "identity": identity,
            "source": source_out,
            "cohort_start": cohort_start,
            "relationship_to_m2b": relationship_out,
            "acquisition_rules": acquisition_rules,
            "prohibitions": prohibitions,
            "maturity": maturity,
            "future_evaluation_requirements": list(future),
            "evaluation_ledger": evaluation_ledger_out,
            "immutable": immutable,
        }
        return cls(document=document)

    @classmethod
    def build(cls, repo_root: str | Path) -> ProspectiveCohortProtocol:
        return cls.from_mapping(_derive_document(repo_root))

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.document)

    def sha256(self) -> str:
        return canonical_sha256(self.document)


def _require_exact_keys(label: str, mapping: dict[str, Any], keys: set[str]) -> None:
    present = set(mapping)
    if missing := keys - present:
        raise M3DValidationError(f"{label} missing keys: {sorted(missing)}")
    if unknown := present - keys:
        raise M3DValidationError(f"{label} has unknown keys: {sorted(unknown)}")


def _require_exact_dict(label: str, value: object, expected: dict[str, Any]) -> dict[str, Any]:
    mapping = require_mapping(label, value)
    _require_exact_keys(label, mapping, set(expected))
    for key, want in expected.items():
        require_exact(f"{label}.{key}", mapping[key], want)
    return dict(expected)


def _validate_maturity(label: str, value: object) -> dict[str, Any]:
    mapping = require_mapping(label, value)
    _require_exact_keys(
        label,
        mapping,
        {
            "minimum_consecutive_daily_candles",
            "minimum_maturity_row_count",
            "cohort_start_fixed",
            "nominal_maturity_last_open",
            "nominal_maturity_exclusive_end",
            "maturity_means_data_availability_only",
            "maturity_authorizes_evaluation",
        },
    )
    return {
        "minimum_consecutive_daily_candles": require_exact(
            f"{label}.minimum_consecutive_daily_candles",
            require_positive_int(
                f"{label}.minimum_consecutive_daily_candles",
                mapping["minimum_consecutive_daily_candles"],
            ),
            MINIMUM_MATURITY_ROWS,
        ),
        "minimum_maturity_row_count": require_exact(
            f"{label}.minimum_maturity_row_count",
            require_positive_int(
                f"{label}.minimum_maturity_row_count", mapping["minimum_maturity_row_count"]
            ),
            MINIMUM_MATURITY_ROWS,
        ),
        "cohort_start_fixed": require_exact(
            f"{label}.cohort_start_fixed",
            require_bool(f"{label}.cohort_start_fixed", mapping["cohort_start_fixed"]),
            True,
        ),
        "nominal_maturity_last_open": require_exact(
            f"{label}.nominal_maturity_last_open",
            require_str(
                f"{label}.nominal_maturity_last_open", mapping["nominal_maturity_last_open"]
            ),
            NOMINAL_MATURITY_LAST_OPEN,
        ),
        "nominal_maturity_exclusive_end": require_exact(
            f"{label}.nominal_maturity_exclusive_end",
            require_str(
                f"{label}.nominal_maturity_exclusive_end", mapping["nominal_maturity_exclusive_end"]
            ),
            NOMINAL_MATURITY_EXCLUSIVE_END,
        ),
        "maturity_means_data_availability_only": require_exact(
            f"{label}.maturity_means_data_availability_only",
            require_bool(
                f"{label}.maturity_means_data_availability_only",
                mapping["maturity_means_data_availability_only"],
            ),
            True,
        ),
        "maturity_authorizes_evaluation": require_exact(
            f"{label}.maturity_authorizes_evaluation",
            require_bool(
                f"{label}.maturity_authorizes_evaluation", mapping["maturity_authorizes_evaluation"]
            ),
            False,
        ),
    }


def _derive_document(repo_root: str | Path) -> dict[str, Any]:
    from eth_research.m3d import M3D_PACKAGE_VERSION

    lock = require_mapping(
        "dataset_lock", up.load_json(repo_root, "research/m2b/dataset_lock.json")
    )
    m2b_last = _z(pd.Timestamp(require_str("last_open_time", lock["last_open_time"])))
    return {
        "schema_version": PROTOCOL_SCHEMA_VERSION,
        "kind": PROTOCOL_KIND,
        "package_version": M3D_PACKAGE_VERSION,
        "identity": dict(_IDENTITY),
        "source": {"endpoint": COINBASE_ENDPOINT, "documentation_url": COINBASE_DOCUMENTATION_URL},
        "cohort_start": COHORT_START,
        "relationship_to_m2b": {
            "final_m2b_candle_open": m2b_last,
            "strictly_after": True,
            "zero_overlap": True,
        },
        "acquisition_rules": dict(_ACQUISITION_RULES),
        "prohibitions": dict(_PROHIBITIONS),
        "maturity": {
            "minimum_consecutive_daily_candles": MINIMUM_MATURITY_ROWS,
            "minimum_maturity_row_count": MINIMUM_MATURITY_ROWS,
            "cohort_start_fixed": True,
            "nominal_maturity_last_open": NOMINAL_MATURITY_LAST_OPEN,
            "nominal_maturity_exclusive_end": NOMINAL_MATURITY_EXCLUSIVE_END,
            "maturity_means_data_availability_only": True,
            "maturity_authorizes_evaluation": False,
        },
        "future_evaluation_requirements": list(_FUTURE_EVALUATION_REQUIREMENTS),
        "evaluation_ledger": {
            "path": EVALUATION_LEDGER_PATH,
            "must_be_byte_empty": True,
            "expected_sha256": up.EMPTY_SHA256,
        },
        "immutable": True,
    }


def build_prospective_protocol(repo_root: str | Path) -> ProspectiveCohortProtocol:
    """Derive the pinned prospective-cohort protocol (M2B binding from committed bytes)."""
    return ProspectiveCohortProtocol.build(repo_root)


def verify_prospective_protocol(repo_root: str | Path) -> ProspectiveCohortProtocol:
    """Verify the committed protocol reproduces byte-for-byte and stays immutable."""
    committed_raw, committed_doc = load_canonical_json_bytes(
        Path(repo_root) / PROTOCOL_PATH, "prospective_protocol"
    )
    committed = ProspectiveCohortProtocol.from_mapping(committed_doc)
    rebuilt = build_prospective_protocol(repo_root)
    if committed.to_json_bytes() != rebuilt.to_json_bytes():
        raise M3DValidationError(
            "committed prospective protocol does not match the rebuilt protocol"
        )
    if committed_raw != rebuilt.to_json_bytes():
        raise M3DValidationError("committed prospective protocol bytes are not canonical")
    return committed


def require_prospective_evaluation_ledger_empty(repo_root: str | Path) -> dict[str, Any]:
    """Read-only proof that the prospective evaluation ledger is byte-empty.

    Any nonzero byte / event is a hard stop: no strategy has been (or may be)
    evaluated on the prospective cohort in this milestone.
    """
    path = Path(repo_root) / EVALUATION_LEDGER_PATH
    if not path.is_file():
        raise M3DValidationError(f"{EVALUATION_LEDGER_PATH} must be a tracked regular file")
    raw = path.read_bytes()
    if raw != b"":
        raise M3DValidationError(
            f"{EVALUATION_LEDGER_PATH} must be byte-empty; found {len(raw)} bytes (HARD STOP)"
        )
    if sha256_bytes(raw) != up.EMPTY_SHA256:
        raise M3DValidationError("prospective evaluation ledger SHA-256 is not the empty digest")
    return {
        "path": EVALUATION_LEDGER_PATH,
        "byte_count": 0,
        "event_count": 0,
        "sha256": up.EMPTY_SHA256,
    }
