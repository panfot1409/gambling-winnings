"""Strict receipts for the one-shot prospective acquisition.

A ``ProspectiveAttemptReceipt`` records exactly what a single acquisition run
retrieved: the plan hash it replayed, the source commit, the workflow run id and
runner identity, the HTTP client identity, and one ``ProspectiveResponseReceipt``
per window (raw filename, canonical request params, HTTP status, content type,
response byte length, response SHA-256, retrieval timestamps, attempt count). It
records body **hashes and lengths**, never candle values. Parsing is strict:
duplicate keys, repaired types, non-UTC timestamps, malformed content types,
non-200 statuses, duplicate ordinals, and unsafe filenames are all rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research.m3d.acquisition_plan import require_safe_json_filename
from eth_research.m3d.validation import (
    M3DValidationError,
    canonical_json_bytes,
    canonical_sha256,
    load_canonical_json_bytes,
    require_commit_sha,
    require_exact,
    require_list,
    require_mapping,
    require_nonnegative_int,
    require_positive_int,
    require_sha256_hex,
    require_str,
    require_utc_timestamp,
)

RECEIPT_SCHEMA_VERSION = 1
RECEIPT_KIND = "prospective_attempt_receipt"
_ALLOWED_CONTENT_TYPE = "application/json"
_OK_STATUS = 200

_RESPONSE_KEYS = {
    "ordinal",
    "raw_filename",
    "start_param",
    "end_param",
    "http_status",
    "content_type",
    "response_byte_length",
    "response_sha256",
    "retrieved_at",
}


def _require_content_type(label: str, value: object) -> str:
    text = require_str(label, value)
    # Exact media-type token (optional ``;``-parameters stripped); a prefix test would
    # admit ``application/jsonx`` and other look-alikes.
    if text.split(";")[0].strip().lower() != _ALLOWED_CONTENT_TYPE:
        raise M3DValidationError(f"{label} must be application/json, got {text!r}")
    return text


def _require_utc(label: str, value: object) -> str:
    text = require_str(label, value)
    require_utc_timestamp(label, pd.Timestamp(text))
    return text


@dataclass(frozen=True)
class ProspectiveResponseReceipt:
    document: dict[str, Any]

    @classmethod
    def from_mapping(cls, doc: object) -> ProspectiveResponseReceipt:
        mapping = require_mapping("response_receipt", doc)
        if set(mapping) != _RESPONSE_KEYS:
            raise M3DValidationError(f"response receipt keys must be {sorted(_RESPONSE_KEYS)}")
        document = {
            "ordinal": require_nonnegative_int("ordinal", mapping["ordinal"]),
            "raw_filename": require_safe_json_filename("raw_filename", mapping["raw_filename"]),
            "start_param": require_str("start_param", mapping["start_param"]),
            "end_param": require_str("end_param", mapping["end_param"]),
            "http_status": require_exact(
                "http_status",
                require_positive_int("http_status", mapping["http_status"]),
                _OK_STATUS,
            ),
            "content_type": _require_content_type("content_type", mapping["content_type"]),
            "response_byte_length": require_nonnegative_int(
                "response_byte_length", mapping["response_byte_length"]
            ),
            "response_sha256": require_sha256_hex("response_sha256", mapping["response_sha256"]),
            "retrieved_at": _require_utc("retrieved_at", mapping["retrieved_at"]),
        }
        return cls(document=document)

    @property
    def ordinal(self) -> int:
        return int(self.document["ordinal"])

    def to_dict(self) -> dict[str, Any]:
        return dict(self.document)


@dataclass(frozen=True)
class ProspectiveAttemptReceipt:
    document: dict[str, Any]

    @classmethod
    def from_mapping(cls, doc: object) -> ProspectiveAttemptReceipt:
        mapping = require_mapping("attempt_receipt", doc)
        _require_exact_keys(
            "attempt_receipt",
            mapping,
            {
                "schema_version",
                "kind",
                "package_version",
                "attempt_id",
                "plan_sha256",
                "endpoint",
                "user_agent",
                "source_commit",
                "workflow_run_id",
                "runner_identity",
                "client_identity",
                "created_at_utc",
                "responses",
            },
        )
        require_exact(
            "schema_version",
            require_positive_int("schema_version", mapping["schema_version"]),
            RECEIPT_SCHEMA_VERSION,
        )
        require_exact("kind", require_str("kind", mapping["kind"]), RECEIPT_KIND)
        responses = [
            ProspectiveResponseReceipt.from_mapping(r)
            for r in require_list("responses", mapping["responses"])
        ]
        ordinals = [r.ordinal for r in responses]
        if ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
            raise M3DValidationError("response ordinals must be unique and ascending")
        document = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "kind": RECEIPT_KIND,
            "package_version": require_str("package_version", mapping["package_version"]),
            "attempt_id": require_str("attempt_id", mapping["attempt_id"]),
            "plan_sha256": require_sha256_hex("plan_sha256", mapping["plan_sha256"]),
            "endpoint": require_str("endpoint", mapping["endpoint"]),
            "user_agent": require_str("user_agent", mapping["user_agent"]),
            "source_commit": require_commit_sha("source_commit", mapping["source_commit"]),
            "workflow_run_id": require_str("workflow_run_id", mapping["workflow_run_id"]),
            "runner_identity": require_str("runner_identity", mapping["runner_identity"]),
            "client_identity": require_str("client_identity", mapping["client_identity"]),
            "created_at_utc": _require_utc("created_at_utc", mapping["created_at_utc"]),
            "responses": [r.to_dict() for r in responses],
        }
        return cls(document=document)

    @property
    def attempt_id(self) -> str:
        return str(self.document["attempt_id"])

    @property
    def plan_sha256(self) -> str:
        return str(self.document["plan_sha256"])

    @property
    def responses(self) -> list[dict[str, Any]]:
        return list(self.document["responses"])

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


def load_prospective_attempt_receipt(path: str | Path) -> ProspectiveAttemptReceipt:
    _raw, doc = load_canonical_json_bytes(Path(path), "prospective_attempt_receipt")
    return ProspectiveAttemptReceipt.from_mapping(doc)
