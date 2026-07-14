"""Append-only, machine-verified errata over the immutable M3B report (R10).

The committed run-001 report's "Honest reading" says the cost scenarios "shrink
net return monotonically in the modeled frictions". That reads as a universal,
cell-by-cell claim, but monotonic decline in friction
(``compatibility_v1`` ≥ ``causal_proxy_base`` ≥ ``causal_proxy_stressed``) holds
only of the per-(strategy, scenario) **fold medians** shown in Section 4 — not of
every one of the 75 cells. Exactly one cell violates it (defect R10).

The report bytes are single-use immutable history and are never edited. The
correction is recorded out of band here, mirroring the M3A errata layer:

- a :class:`FractionalReportErratum` document (``research/m3b/errata/<id>.json``)
  binding the target report + results by SHA-256, the exact overbroad statement
  (and a domain-separated hash of its bytes), the corrected statement, and the
  full-precision cell-wise counterexamples; and
- an append-only, hash-chained registry (``research/m3b/artifact_errata.jsonl``).

:func:`verify_fractional_report_errata` re-derives the *complete* set of
monotonicity violations from the committed results model, proves the declared
counterexamples are exactly that set at full precision, that the overbroad
statement is present verbatim in the target report, that the target bytes still
hash to the run's ``completed`` registry event, that the rendered Markdown matches
the model, that no financial scalar changed, and that both sealed ledgers stay
byte-empty. It mutates nothing and evaluates no sealed partition.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.provenance import (
    require_bool,
    require_hex64,
    require_int,
    require_nonempty_str,
    sha256_bytes,
)
from eth_research.fractional.protocol import RUN_001_EXPERIMENT_ID
from eth_research.fractional.registry import (
    EVENT_COMPLETED,
    M3B_REGISTRY_RELPATH,
    read_registry,
)
from eth_research.fractional.results import load_fractional_results
from eth_research.fractional.validation import require_safe_relative_path
from eth_research.publication import durable_write_bytes

FRACTIONAL_ERRATA_SCHEMA_VERSION: int = 1
FRACTIONAL_ERRATA_REGISTRY_RELPATH: str = "research/m3b/artifact_errata.jsonl"
FRACTIONAL_ERRATA_DIR_RELPATH: str = "research/m3b/errata"
ERROR_CLASS_OVERBROAD_MONOTONICITY: str = "overbroad_cost_monotonicity_claim"
GENESIS_SHA256: str = "0" * 64
_M3B_PREFIX: str = "research/m3b/"

# Friction increases along this order; the report claims net return declines with it.
_FRICTION_ORDER: tuple[str, ...] = (
    "compatibility_v1",
    "causal_proxy_base",
    "causal_proxy_stressed",
)

# Domain separation so the statement hash can never collide with a hash over some
# other artifact's bytes.
_STATEMENT_HASH_DOMAIN: bytes = b"eth_research.fractional.report_erratum.overbroad_statement.v1\n"

_GATE_LEDGER_RELPATH: str = "research/m3a/development_gate_access.jsonl"
_HOLDOUT_LEDGER_RELPATH: str = "research/m2b/test_evaluations.jsonl"

RUN001_MONOTONICITY_ERRATUM_ID: str = "m3b-run001-report-cost-monotonicity-v1"
_ERRATUM_JSON_RELPATH: str = (
    f"{FRACTIONAL_ERRATA_DIR_RELPATH}/{RUN001_MONOTONICITY_ERRATUM_ID}.json"
)
_ERRATUM_MD_RELPATH: str = f"{FRACTIONAL_ERRATA_DIR_RELPATH}/{RUN001_MONOTONICITY_ERRATUM_ID}.md"

#: Every committed file the errata layer contributes, for hygiene allowlisting.
FRACTIONAL_ERRATA_TRACKED: tuple[str, ...] = (
    FRACTIONAL_ERRATA_REGISTRY_RELPATH,
    _ERRATUM_JSON_RELPATH,
    _ERRATUM_MD_RELPATH,
)
RUN001_OVERBROAD_STATEMENT: str = (
    "The cost scenarios shrink net return monotonically in the modeled frictions"
)
RUN001_CORRECTED_STATEMENT: str = (
    "Monotonic decline in the modeled frictions "
    "(compatibility_v1 >= causal_proxy_base >= causal_proxy_stressed) holds for the "
    "per-(strategy, cost-scenario) fold-median marked returns shown in Section 4, "
    "but NOT for every one of the 75 individual cells. Exactly one cell violates "
    "it: donchian_55_20 fold 1, whose causal_proxy_base marked return is below its "
    "causal_proxy_stressed marked return (a higher-friction scenario returned more "
    "in that single fold). The unqualified 'shrink net return monotonically' "
    "phrasing is therefore overbroad; it is correct only of the fold medians. No "
    "financial value changes and the immutable report bytes are preserved verbatim."
)


class FractionalReportErrataError(RuntimeError):
    """A malformed erratum, broken chain, or failed verification."""


def statement_domain_sha256(statement: str) -> str:
    """Domain-separated SHA-256 of a statement's exact UTF-8 bytes."""
    return sha256_bytes(_STATEMENT_HASH_DOMAIN + statement.encode("utf-8"))


def _require_float(label: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, float):
        raise FractionalReportErrataError(f"{label} must be a float, got {type(value).__name__}")
    return value


def _require_false(label: str, value: object) -> bool:
    flag = require_bool(label, value)
    if flag:
        raise FractionalReportErrataError(f"{label} must be false for a report-summary erratum")
    return flag


def _strict_object(raw: bytes, keys: frozenset[str], label: str) -> dict[str, Any]:
    try:
        payload: Any = strict_json_loads(raw)
    except StrictJSONError as exc:
        raise FractionalReportErrataError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != keys:
        raise FractionalReportErrataError(f"{label} keys do not match schema")
    return payload


_COUNTEREXAMPLE_KEYS: frozenset[str] = frozenset(
    {
        "strategy",
        "fold_index",
        "lower_friction_scenario",
        "higher_friction_scenario",
        "lower_friction_marked_return",
        "higher_friction_marked_return",
    }
)


@dataclass(frozen=True)
class MonotonicityCounterexample:
    """One (strategy, fold) adjacent-scenario pair that breaks monotonic decline.

    ``higher_friction_marked_return`` strictly exceeds
    ``lower_friction_marked_return`` — i.e. the *more* frictional scenario returned
    *more* in this cell — which is exactly the violation the overbroad claim hides.
    """

    strategy: str
    fold_index: int
    lower_friction_scenario: str
    higher_friction_scenario: str
    lower_friction_marked_return: float
    higher_friction_marked_return: float

    def __post_init__(self) -> None:
        require_nonempty_str("strategy", self.strategy)
        if isinstance(self.fold_index, bool) or not isinstance(self.fold_index, int):
            raise FractionalReportErrataError("fold_index must be an int")
        if self.lower_friction_scenario not in _FRICTION_ORDER:
            raise FractionalReportErrataError("lower_friction_scenario is not a known scenario")
        if self.higher_friction_scenario not in _FRICTION_ORDER:
            raise FractionalReportErrataError("higher_friction_scenario is not a known scenario")
        if _FRICTION_ORDER.index(self.higher_friction_scenario) != (
            _FRICTION_ORDER.index(self.lower_friction_scenario) + 1
        ):
            raise FractionalReportErrataError("counterexample scenarios must be friction-adjacent")
        _require_float("lower_friction_marked_return", self.lower_friction_marked_return)
        _require_float("higher_friction_marked_return", self.higher_friction_marked_return)
        if not self.higher_friction_marked_return > self.lower_friction_marked_return:
            raise FractionalReportErrataError(
                "a counterexample requires higher-friction return > lower-friction return"
            )

    def key(self) -> tuple[str, int, str, str]:
        return (
            self.strategy,
            self.fold_index,
            self.lower_friction_scenario,
            self.higher_friction_scenario,
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "fold_index": self.fold_index,
            "lower_friction_scenario": self.lower_friction_scenario,
            "higher_friction_scenario": self.higher_friction_scenario,
            "lower_friction_marked_return": self.lower_friction_marked_return,
            "higher_friction_marked_return": self.higher_friction_marked_return,
        }

    @classmethod
    def from_json_dict(cls, payload: Any) -> MonotonicityCounterexample:
        if not isinstance(payload, dict) or set(payload) != _COUNTEREXAMPLE_KEYS:
            raise FractionalReportErrataError("counterexample keys do not match schema")
        return cls(
            strategy=payload["strategy"],
            fold_index=payload["fold_index"],
            lower_friction_scenario=payload["lower_friction_scenario"],
            higher_friction_scenario=payload["higher_friction_scenario"],
            lower_friction_marked_return=_require_float(
                "lower_friction_marked_return", payload["lower_friction_marked_return"]
            ),
            higher_friction_marked_return=_require_float(
                "higher_friction_marked_return", payload["higher_friction_marked_return"]
            ),
        )


_ERRATUM_KEYS: frozenset[str] = frozenset(
    {
        "errata_schema_version",
        "erratum_id",
        "error_class",
        "target_experiment_id",
        "target_report_relpath",
        "target_report_sha256",
        "target_results_relpath",
        "target_results_sha256",
        "erroneous_statement",
        "erroneous_statement_sha256",
        "corrected_statement",
        "counterexamples",
        "financial_values_changed",
        "methodology_changed",
        "strategy_parameters_changed",
        "development_gate_accessed",
        "final_holdout_accessed",
        "new_experiment_run",
        "previous_erratum_sha256",
    }
)


@dataclass(frozen=True)
class FractionalReportErratum:
    """A strict, immutable correction document over the committed report."""

    errata_schema_version: int
    erratum_id: str
    error_class: str
    target_experiment_id: str
    target_report_relpath: str
    target_report_sha256: str
    target_results_relpath: str
    target_results_sha256: str
    erroneous_statement: str
    erroneous_statement_sha256: str
    corrected_statement: str
    counterexamples: tuple[MonotonicityCounterexample, ...]
    financial_values_changed: bool
    methodology_changed: bool
    strategy_parameters_changed: bool
    development_gate_accessed: bool
    final_holdout_accessed: bool
    new_experiment_run: bool
    previous_erratum_sha256: str

    def __post_init__(self) -> None:
        if require_int("errata_schema_version", self.errata_schema_version) != (
            FRACTIONAL_ERRATA_SCHEMA_VERSION
        ):
            raise FractionalReportErrataError("unsupported errata schema version")
        require_nonempty_str("erratum_id", self.erratum_id)
        if self.error_class != ERROR_CLASS_OVERBROAD_MONOTONICITY:
            raise FractionalReportErrataError(f"unsupported error_class {self.error_class!r}")
        require_nonempty_str("target_experiment_id", self.target_experiment_id)
        require_safe_relative_path(
            "target_report_relpath", self.target_report_relpath, prefix=_M3B_PREFIX
        )
        require_hex64("target_report_sha256", self.target_report_sha256)
        require_safe_relative_path(
            "target_results_relpath", self.target_results_relpath, prefix=_M3B_PREFIX
        )
        require_hex64("target_results_sha256", self.target_results_sha256)
        require_nonempty_str("erroneous_statement", self.erroneous_statement)
        require_hex64("erroneous_statement_sha256", self.erroneous_statement_sha256)
        if self.erroneous_statement_sha256 != statement_domain_sha256(self.erroneous_statement):
            raise FractionalReportErrataError("erroneous_statement_sha256 does not match the bytes")
        require_nonempty_str("corrected_statement", self.corrected_statement)
        if not self.counterexamples:
            raise FractionalReportErrataError("counterexamples must be non-empty")
        keys = [c.key() for c in self.counterexamples]
        if len(set(keys)) != len(keys):
            raise FractionalReportErrataError("counterexamples must be unique")
        if list(self.counterexamples) != sorted(self.counterexamples, key=lambda c: c.key()):
            raise FractionalReportErrataError("counterexamples must be sorted by key")
        _require_false("financial_values_changed", self.financial_values_changed)
        _require_false("methodology_changed", self.methodology_changed)
        _require_false("strategy_parameters_changed", self.strategy_parameters_changed)
        _require_false("development_gate_accessed", self.development_gate_accessed)
        _require_false("final_holdout_accessed", self.final_holdout_accessed)
        _require_false("new_experiment_run", self.new_experiment_run)
        require_hex64("previous_erratum_sha256", self.previous_erratum_sha256)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "errata_schema_version": self.errata_schema_version,
            "erratum_id": self.erratum_id,
            "error_class": self.error_class,
            "target_experiment_id": self.target_experiment_id,
            "target_report_relpath": self.target_report_relpath,
            "target_report_sha256": self.target_report_sha256,
            "target_results_relpath": self.target_results_relpath,
            "target_results_sha256": self.target_results_sha256,
            "erroneous_statement": self.erroneous_statement,
            "erroneous_statement_sha256": self.erroneous_statement_sha256,
            "corrected_statement": self.corrected_statement,
            "counterexamples": [c.to_json_dict() for c in self.counterexamples],
            "financial_values_changed": self.financial_values_changed,
            "methodology_changed": self.methodology_changed,
            "strategy_parameters_changed": self.strategy_parameters_changed,
            "development_gate_accessed": self.development_gate_accessed,
            "final_holdout_accessed": self.final_holdout_accessed,
            "new_experiment_run": self.new_experiment_run,
            "previous_erratum_sha256": self.previous_erratum_sha256,
        }

    def to_canonical_bytes(self) -> bytes:
        text = json.dumps(
            self.to_json_dict(), sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
        )
        return (text + "\n").encode("utf-8")

    def canonical_sha256(self) -> str:
        return sha256_bytes(self.to_canonical_bytes())

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> FractionalReportErratum:
        payload = _strict_object(raw, _ERRATUM_KEYS, "fractional report erratum")
        cx_raw = payload["counterexamples"]
        if not isinstance(cx_raw, list):
            raise FractionalReportErrataError("counterexamples must be a list")
        return cls(
            errata_schema_version=payload["errata_schema_version"],
            erratum_id=payload["erratum_id"],
            error_class=payload["error_class"],
            target_experiment_id=payload["target_experiment_id"],
            target_report_relpath=payload["target_report_relpath"],
            target_report_sha256=payload["target_report_sha256"],
            target_results_relpath=payload["target_results_relpath"],
            target_results_sha256=payload["target_results_sha256"],
            erroneous_statement=payload["erroneous_statement"],
            erroneous_statement_sha256=payload["erroneous_statement_sha256"],
            corrected_statement=payload["corrected_statement"],
            counterexamples=tuple(MonotonicityCounterexample.from_json_dict(c) for c in cx_raw),
            financial_values_changed=require_bool(
                "financial_values_changed", payload["financial_values_changed"]
            ),
            methodology_changed=require_bool("methodology_changed", payload["methodology_changed"]),
            strategy_parameters_changed=require_bool(
                "strategy_parameters_changed", payload["strategy_parameters_changed"]
            ),
            development_gate_accessed=require_bool(
                "development_gate_accessed", payload["development_gate_accessed"]
            ),
            final_holdout_accessed=require_bool(
                "final_holdout_accessed", payload["final_holdout_accessed"]
            ),
            new_experiment_run=require_bool("new_experiment_run", payload["new_experiment_run"]),
            previous_erratum_sha256=payload["previous_erratum_sha256"],
        )


def _fmt_pct(value: float) -> str:
    return f"{value * 100.0:+.6f}%"


def render_erratum_markdown(erratum: FractionalReportErratum) -> bytes:
    """Deterministically render an erratum to Markdown bytes (re-checked on verify)."""
    lines: list[str] = []
    add = lines.append
    add(f"# Erratum {erratum.erratum_id}")
    add("")
    add(f"- **Error class:** `{erratum.error_class}`")
    add(f"- **Target experiment:** `{erratum.target_experiment_id}`")
    add(f"- **Target report:** `{erratum.target_report_relpath}`")
    add(f"- **Target report SHA-256:** `{erratum.target_report_sha256}`")
    add(f"- **Target results:** `{erratum.target_results_relpath}`")
    add(f"- **Target results SHA-256:** `{erratum.target_results_sha256}`")
    add(f"- **Previous erratum SHA-256:** `{erratum.previous_erratum_sha256}`")
    add("")
    add("## Overbroad statement (preserved verbatim in the immutable report)")
    add("")
    add(f"> {erratum.erroneous_statement}")
    add("")
    add(f"Statement byte hash (domain-separated): `{erratum.erroneous_statement_sha256}`")
    add("")
    add("## Correction")
    add("")
    add(erratum.corrected_statement)
    add("")
    add("## Cell-wise counterexamples (full precision, rederived from the committed results)")
    add("")
    add("| strategy | fold | lower-friction | return | higher-friction | return |")
    add("| --- | ---: | --- | ---: | --- | ---: |")
    for cx in erratum.counterexamples:
        add(
            f"| {cx.strategy} | {cx.fold_index} | {cx.lower_friction_scenario} | "
            f"{cx.lower_friction_marked_return!r} ({_fmt_pct(cx.lower_friction_marked_return)}) | "
            f"{cx.higher_friction_scenario} | "
            f"{cx.higher_friction_marked_return!r} ({_fmt_pct(cx.higher_friction_marked_return)}) |"
        )
    add("")
    add("## Declarations")
    add("")
    add(f"- Financial values changed: {str(erratum.financial_values_changed).lower()}")
    add(f"- Methodology changed: {str(erratum.methodology_changed).lower()}")
    add(f"- Strategy parameters changed: {str(erratum.strategy_parameters_changed).lower()}")
    add(f"- Development gate accessed: {str(erratum.development_gate_accessed).lower()}")
    add(f"- Final holdout accessed: {str(erratum.final_holdout_accessed).lower()}")
    add(f"- New experiment run: {str(erratum.new_experiment_run).lower()}")
    add("")
    return ("\n".join(lines) + "\n").encode("utf-8")


_ENTRY_KEYS: frozenset[str] = frozenset(
    {
        "errata_schema_version",
        "erratum_id",
        "erratum_relpath",
        "erratum_sha256",
        "erratum_markdown_relpath",
        "erratum_markdown_sha256",
        "target_experiment_id",
        "target_report_relpath",
        "target_report_sha256",
        "previous_entry_sha256",
    }
)


@dataclass(frozen=True)
class ErrataRegistryEntry:
    """One append-only errata-registry line binding an erratum to the chain."""

    errata_schema_version: int
    erratum_id: str
    erratum_relpath: str
    erratum_sha256: str
    erratum_markdown_relpath: str
    erratum_markdown_sha256: str
    target_experiment_id: str
    target_report_relpath: str
    target_report_sha256: str
    previous_entry_sha256: str

    def __post_init__(self) -> None:
        if require_int("errata_schema_version", self.errata_schema_version) != (
            FRACTIONAL_ERRATA_SCHEMA_VERSION
        ):
            raise FractionalReportErrataError("unsupported errata schema version")
        require_nonempty_str("erratum_id", self.erratum_id)
        require_safe_relative_path("erratum_relpath", self.erratum_relpath, prefix=_M3B_PREFIX)
        require_hex64("erratum_sha256", self.erratum_sha256)
        require_safe_relative_path(
            "erratum_markdown_relpath", self.erratum_markdown_relpath, prefix=_M3B_PREFIX
        )
        require_hex64("erratum_markdown_sha256", self.erratum_markdown_sha256)
        require_nonempty_str("target_experiment_id", self.target_experiment_id)
        require_safe_relative_path(
            "target_report_relpath", self.target_report_relpath, prefix=_M3B_PREFIX
        )
        require_hex64("target_report_sha256", self.target_report_sha256)
        require_hex64("previous_entry_sha256", self.previous_entry_sha256)

    def to_json_line(self) -> bytes:
        payload = {
            "errata_schema_version": self.errata_schema_version,
            "erratum_id": self.erratum_id,
            "erratum_relpath": self.erratum_relpath,
            "erratum_sha256": self.erratum_sha256,
            "erratum_markdown_relpath": self.erratum_markdown_relpath,
            "erratum_markdown_sha256": self.erratum_markdown_sha256,
            "target_experiment_id": self.target_experiment_id,
            "target_report_relpath": self.target_report_relpath,
            "target_report_sha256": self.target_report_sha256,
            "previous_entry_sha256": self.previous_entry_sha256,
        }
        text = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_line(cls, line: bytes) -> ErrataRegistryEntry:
        payload = _strict_object(line, _ENTRY_KEYS, "errata registry line")
        return cls(
            errata_schema_version=payload["errata_schema_version"],
            erratum_id=payload["erratum_id"],
            erratum_relpath=payload["erratum_relpath"],
            erratum_sha256=payload["erratum_sha256"],
            erratum_markdown_relpath=payload["erratum_markdown_relpath"],
            erratum_markdown_sha256=payload["erratum_markdown_sha256"],
            target_experiment_id=payload["target_experiment_id"],
            target_report_relpath=payload["target_report_relpath"],
            target_report_sha256=payload["target_report_sha256"],
            previous_entry_sha256=payload["previous_entry_sha256"],
        )


def _read_registry_lines(path: Path) -> tuple[tuple[bytes, ErrataRegistryEntry], ...]:
    if not path.exists():
        return ()
    raw = path.read_bytes()
    if raw == b"":
        return ()
    if not raw.endswith(b"\n"):
        raise FractionalReportErrataError("errata registry must end with a newline")
    out: list[tuple[bytes, ErrataRegistryEntry]] = []
    for chunk in raw.split(b"\n")[:-1]:
        if chunk == b"":
            raise FractionalReportErrataError("errata registry must not contain a blank line")
        try:
            out.append((chunk, ErrataRegistryEntry.from_json_line(chunk)))
        except FractionalReportErrataError as exc:
            raise FractionalReportErrataError(f"invalid errata registry line: {exc}") from exc
    return tuple(out)


def read_errata_registry(repo_root: str | Path) -> tuple[ErrataRegistryEntry, ...]:
    """Strictly read the append-only, hash-chained errata registry (empty = none)."""
    lines = _read_registry_lines(Path(repo_root) / FRACTIONAL_ERRATA_REGISTRY_RELPATH)
    seen: set[str] = set()
    for position, (_raw, entry) in enumerate(lines):
        if entry.erratum_id in seen:
            raise FractionalReportErrataError(f"duplicate erratum id {entry.erratum_id!r}")
        seen.add(entry.erratum_id)
        expected = GENESIS_SHA256 if position == 0 else sha256_bytes(lines[position - 1][0])
        if entry.previous_entry_sha256 != expected:
            raise FractionalReportErrataError(
                f"errata line {position + 1}: broken chain "
                f"(expected {expected[:12]}, got {entry.previous_entry_sha256[:12]})"
            )
    return tuple(entry for _, entry in lines)


def _completed_run001_event(root: Path) -> Any:
    events = read_registry(root / M3B_REGISTRY_RELPATH)
    run_events = [e for e in events if e.experiment_id == RUN_001_EXPERIMENT_ID]
    if not run_events or run_events[-1].event != EVENT_COMPLETED:
        raise FractionalReportErrataError("run-001 has no terminal 'completed' event")
    return run_events[-1]


def derive_monotonicity_counterexamples(
    repo_root: str | Path,
) -> tuple[MonotonicityCounterexample, ...]:
    """The complete, sorted set of cell-wise monotonic-decline violations.

    Read from the committed results model: for each (strategy, fold), any adjacent
    friction pair whose higher-friction marked return strictly exceeds the
    lower-friction one. Full precision — never a rounded display value.
    """
    root = Path(repo_root)
    completed = _completed_run001_event(root)
    results = load_fractional_results(str(root / completed.immutable_results_path))
    by_key = {
        (c.strategy, c.cost_scenario, c.fold_index): c.marked_total_return
        for c in results.fold_cells
    }
    folds = sorted({c.fold_index for c in results.fold_cells})
    strategies = results.strategies
    found: list[MonotonicityCounterexample] = []
    for strategy in strategies:
        for fold in folds:
            for lower, higher in pairwise(_FRICTION_ORDER):
                r_lo = by_key[(strategy, lower, fold)]
                r_hi = by_key[(strategy, higher, fold)]
                if r_hi > r_lo:
                    found.append(
                        MonotonicityCounterexample(
                            strategy=strategy,
                            fold_index=fold,
                            lower_friction_scenario=lower,
                            higher_friction_scenario=higher,
                            lower_friction_marked_return=r_lo,
                            higher_friction_marked_return=r_hi,
                        )
                    )
    return tuple(sorted(found, key=lambda c: c.key()))


def build_run001_monotonicity_erratum(
    repo_root: str | Path, *, previous_erratum_sha256: str = GENESIS_SHA256
) -> FractionalReportErratum:
    """Construct the run-001 report cost-monotonicity erratum from committed bytes."""
    root = Path(repo_root)
    completed = _completed_run001_event(root)
    if completed.report_markdown_sha256 is None or completed.results_json_sha256 is None:
        raise FractionalReportErrataError("run-001 completed event is missing result hashes")
    counterexamples = derive_monotonicity_counterexamples(root)
    if not counterexamples:
        raise FractionalReportErrataError(
            "no cell-wise monotonicity violation; erratum unwarranted"
        )
    return FractionalReportErratum(
        errata_schema_version=FRACTIONAL_ERRATA_SCHEMA_VERSION,
        erratum_id=RUN001_MONOTONICITY_ERRATUM_ID,
        error_class=ERROR_CLASS_OVERBROAD_MONOTONICITY,
        target_experiment_id=RUN_001_EXPERIMENT_ID,
        target_report_relpath=completed.immutable_report_path,
        target_report_sha256=completed.report_markdown_sha256,
        target_results_relpath=completed.immutable_results_path,
        target_results_sha256=completed.results_json_sha256,
        erroneous_statement=RUN001_OVERBROAD_STATEMENT,
        erroneous_statement_sha256=statement_domain_sha256(RUN001_OVERBROAD_STATEMENT),
        corrected_statement=RUN001_CORRECTED_STATEMENT,
        counterexamples=counterexamples,
        financial_values_changed=False,
        methodology_changed=False,
        strategy_parameters_changed=False,
        development_gate_accessed=False,
        final_holdout_accessed=False,
        new_experiment_run=False,
        previous_erratum_sha256=previous_erratum_sha256,
    )


def _read_under_root(root: Path, relpath: str) -> bytes:
    require_safe_relative_path("relpath", relpath, prefix=_M3B_PREFIX)
    target = root / relpath
    if target.is_symlink() or not target.is_file():
        raise FractionalReportErrataError(f"errata artifact missing or not a file: {relpath}")
    return target.read_bytes()


def verify_fractional_report_errata(repo_root: str | Path) -> tuple[str, ...]:
    """Verify every M3B report erratum against the registry, target, and results.

    Read-only. For each erratum proves: the erratum/markdown bytes hash to the
    registry entry and the erratum is canonically serialized; the target report +
    results bytes still hash to the run's ``completed`` registry event; the
    overbroad statement is present verbatim in the report; the declared
    counterexamples are exactly the complete set of monotonic-decline violations
    rederived from the committed results at full precision; every "nothing changed"
    declaration is false; and both sealed ledgers stay byte-empty. No orphan file
    may sit under the errata directory.
    """
    root = Path(repo_root)
    entries = read_errata_registry(root)
    for ledger_rel in (_GATE_LEDGER_RELPATH, _HOLDOUT_LEDGER_RELPATH):
        if (root / ledger_rel).read_bytes() != b"":
            raise FractionalReportErrataError(f"sealed ledger is not byte-empty: {ledger_rel}")

    completed = _completed_run001_event(root)
    verified: list[str] = []
    for entry in entries:
        erratum_bytes = _read_under_root(root, entry.erratum_relpath)
        if sha256_bytes(erratum_bytes) != entry.erratum_sha256:
            raise FractionalReportErrataError(f"{entry.erratum_id}: erratum bytes hash != registry")
        erratum = FractionalReportErratum.from_json_bytes(erratum_bytes)
        if erratum.erratum_id != entry.erratum_id:
            raise FractionalReportErrataError(f"{entry.erratum_id}: erratum id != registry entry")
        if erratum.canonical_sha256() != entry.erratum_sha256:
            raise FractionalReportErrataError(f"{entry.erratum_id}: erratum not canonical")

        md_bytes = _read_under_root(root, entry.erratum_markdown_relpath)
        if sha256_bytes(md_bytes) != entry.erratum_markdown_sha256:
            raise FractionalReportErrataError(f"{entry.erratum_id}: markdown hash != registry")
        if md_bytes != render_erratum_markdown(erratum):
            raise FractionalReportErrataError(f"{entry.erratum_id}: markdown != rendered model")

        if erratum.target_experiment_id != RUN_001_EXPERIMENT_ID:
            raise FractionalReportErrataError(f"{entry.erratum_id}: target is not run-001")
        if (
            erratum.target_report_relpath != completed.immutable_report_path
            or erratum.target_report_sha256 != completed.report_markdown_sha256
            or entry.target_report_sha256 != completed.report_markdown_sha256
        ):
            raise FractionalReportErrataError(f"{entry.erratum_id}: report binding != completed")
        if (
            erratum.target_results_relpath != completed.immutable_results_path
            or erratum.target_results_sha256 != completed.results_json_sha256
        ):
            raise FractionalReportErrataError(f"{entry.erratum_id}: results binding != completed")

        report_bytes = _read_under_root(root, erratum.target_report_relpath)
        if sha256_bytes(report_bytes) != erratum.target_report_sha256:
            raise FractionalReportErrataError(f"{entry.erratum_id}: report bytes hash mismatch")
        results_bytes = _read_under_root(root, erratum.target_results_relpath)
        if sha256_bytes(results_bytes) != erratum.target_results_sha256:
            raise FractionalReportErrataError(f"{entry.erratum_id}: results bytes hash mismatch")
        if erratum.erroneous_statement not in report_bytes.decode("utf-8"):
            raise FractionalReportErrataError(
                f"{entry.erratum_id}: overbroad statement not present verbatim in the report"
            )

        derived = derive_monotonicity_counterexamples(root)
        if erratum.counterexamples != derived:
            raise FractionalReportErrataError(
                f"{entry.erratum_id}: counterexamples are not exactly the complete violation set"
            )
        verified.append(erratum.erratum_id)

    referenced = {e.erratum_relpath for e in entries} | {
        e.erratum_markdown_relpath for e in entries
    }
    errata_dir = root / FRACTIONAL_ERRATA_DIR_RELPATH
    if errata_dir.is_dir():
        for path in sorted(errata_dir.rglob("*")):
            if path.is_file():
                rel = path.relative_to(root).as_posix()
                if rel not in referenced:
                    raise FractionalReportErrataError(
                        f"orphan errata file not in the registry: {rel}"
                    )
    return tuple(verified)


def materialize_run001_monotonicity_erratum(repo_root: str | Path) -> tuple[str, ...]:
    """Write the erratum JSON + Markdown and append the registry line; verify.

    The erratum + its rendered Markdown are written durably under the errata
    directory, then one hash-chained registry line (chaining onto the current tail)
    is appended. Returns the verifier's confirmed erratum ids.
    """
    root = Path(repo_root)
    lines = _read_registry_lines(root / FRACTIONAL_ERRATA_REGISTRY_RELPATH)
    previous_entry = GENESIS_SHA256 if not lines else sha256_bytes(lines[-1][0])
    erratum = build_run001_monotonicity_erratum(root)
    erratum_relpath = f"{FRACTIONAL_ERRATA_DIR_RELPATH}/{erratum.erratum_id}.json"
    markdown_relpath = f"{FRACTIONAL_ERRATA_DIR_RELPATH}/{erratum.erratum_id}.md"
    erratum_bytes = erratum.to_canonical_bytes()
    markdown_bytes = render_erratum_markdown(erratum)
    (root / FRACTIONAL_ERRATA_DIR_RELPATH).mkdir(parents=True, exist_ok=True)
    durable_write_bytes(root / erratum_relpath, erratum_bytes)
    durable_write_bytes(root / markdown_relpath, markdown_bytes)
    entry = ErrataRegistryEntry(
        errata_schema_version=FRACTIONAL_ERRATA_SCHEMA_VERSION,
        erratum_id=erratum.erratum_id,
        erratum_relpath=erratum_relpath,
        erratum_sha256=sha256_bytes(erratum_bytes),
        erratum_markdown_relpath=markdown_relpath,
        erratum_markdown_sha256=sha256_bytes(markdown_bytes),
        target_experiment_id=erratum.target_experiment_id,
        target_report_relpath=erratum.target_report_relpath,
        target_report_sha256=erratum.target_report_sha256,
        previous_entry_sha256=previous_entry,
    )
    registry_path = root / FRACTIONAL_ERRATA_REGISTRY_RELPATH
    if not registry_path.exists():
        registry_path.write_bytes(b"")
    new_line = entry.to_json_line()
    descriptor = os.open(str(registry_path), os.O_WRONLY | os.O_APPEND)
    try:
        if os.write(descriptor, new_line) != len(new_line):
            raise FractionalReportErrataError("short write appending the errata registry line")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return verify_fractional_report_errata(root)
