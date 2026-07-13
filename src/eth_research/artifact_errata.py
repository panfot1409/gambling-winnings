"""Append-only, machine-verified errata over immutable M3A artifacts.

An experiment's published report is single-use immutable history — its bytes are
never edited. When a *prose* statement in a committed report is later found to be
false while the underlying numbers are correct, the correction is recorded
**out of band** here rather than by rewriting the artifact or appending a fake
experiment.

The layer has two parts, mirroring the experiment archive/registry split:

- an :class:`ArtifactErratum` document (``research/m3a/errata/<id>.json``) that
  binds the target artifact + results by SHA-256, the exact erroneous statement
  (and a domain-separated hash of its bytes), the corrected statement, the
  machine-readable affected cells with their full-precision bounds and
  zero-inclusion predicate, and a set of "nothing changed" declarations; and
- an append-only, hash-chained registry
  (``research/m3a/artifact_errata.jsonl``) whose each line binds the prior
  line's bytes, the erratum JSON bytes, its rendered Markdown bytes, and the
  target artifact hash.

:func:`verify_artifact_errata` re-derives the affected cells from the committed
results model and proves — independently of any human prose — that the target
bytes still hash to the completed registry event, the erroneous statement is
present verbatim, the three cash primary intervals exclude zero while the SMA/
Donchian primary and every sensitivity interval contain it, no financial scalar
changed, and both sealed ledgers stay byte-empty. Nothing here evaluates a
sealed partition, mutates a committed artifact, or appends an experiment event.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
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
from eth_research.data.validation import require_evaluation_id

ERRATA_SCHEMA_VERSION: int = 1
ERRATA_REGISTRY_RELPATH: str = "research/m3a/artifact_errata.jsonl"
ERRATA_DIR_RELPATH: str = "research/m3a/errata"
ERROR_CLASS_INCORRECT_SUMMARY: str = "incorrect_statistical_summary"
_SUPPORTED_ERROR_CLASSES: frozenset[str] = frozenset({ERROR_CLASS_INCORRECT_SUMMARY})
GENESIS_SHA256: str = "0" * 64
_INTERVAL_KINDS: frozenset[str] = frozenset({"primary", "sensitivity"})
_M3A_PREFIX: str = "research/m3a/"
_SAFE_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")

# Domain separation so the erroneous-statement hash can never collide with a
# hash taken over some other artifact's bytes.
_STATEMENT_HASH_DOMAIN: bytes = b"eth_research.artifact_errata.erroneous_statement.v1\n"

_GATE_LEDGER_RELPATH: str = "research/m3a/development_gate_access.jsonl"
_HOLDOUT_LEDGER_RELPATH: str = "research/m2b/test_evaluations.jsonl"


class ArtifactErrataError(RuntimeError):
    """Raised on any malformed erratum, broken chain, or failed verification."""


def interval_contains_zero(lower: float, upper: float) -> bool:
    """True iff the closed interval ``[lower, upper]`` contains zero.

    Evaluated at full floating-point precision — never from a rounded display
    string. Rejects an inverted interval so a caller cannot smuggle a
    lower > upper pair past the predicate.
    """
    if lower > upper:
        raise ValueError(f"interval lower {lower!r} exceeds upper {upper!r}")
    return lower <= 0.0 <= upper


def statement_domain_sha256(statement: str) -> str:
    """Domain-separated SHA-256 of a statement's exact UTF-8 bytes."""
    return sha256_bytes(_STATEMENT_HASH_DOMAIN + statement.encode("utf-8"))


def _require_float(label: str, value: object) -> float:
    """The value must be exactly a float — bool and int are rejected."""
    if isinstance(value, bool) or not isinstance(value, float):
        raise ValueError(f"{label} must be a float, got {type(value).__name__}")
    return value


def _require_false(label: str, value: object) -> bool:
    """A declaration that must be present and exactly ``False``."""
    flag = require_bool(label, value)
    if flag:
        raise ValueError(f"{label} must be false for a report-summary erratum")
    return flag


def require_safe_m3a_relpath(label: str, value: object) -> str:
    """A clean repo-relative path strictly under ``research/m3a/``."""
    text = require_nonempty_str(label, value)
    if text != text.strip() or text.startswith("/") or "\\" in text or "\x00" in text:
        raise ValueError(f"{label} must be a clean relative path, got {text!r}")
    parts = text.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"{label} must have no empty or dot components, got {text!r}")
    if any(not _SAFE_PATH_COMPONENT.match(part) for part in parts):
        raise ValueError(f"{label} has an unsafe path component, got {text!r}")
    if not text.startswith(_M3A_PREFIX):
        raise ValueError(f"{label} must live under {_M3A_PREFIX!r}, got {text!r}")
    return text


def _strict_object(raw: bytes, keys: frozenset[str], label: str) -> dict[str, Any]:
    try:
        payload: Any = strict_json_loads(raw)
    except StrictJSONError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object")
    present = set(payload)
    if present != keys:
        unknown = sorted(present - keys)
        missing = sorted(keys - present)
        raise ValueError(f"{label} keys do not match schema: unknown={unknown}, missing={missing}")
    return payload


_CELL_KEYS: frozenset[str] = frozenset(
    {"strategy", "cost_scenario", "interval_kind", "ci_lower", "ci_upper", "zero_included"}
)


@dataclass(frozen=True)
class AffectedCell:
    """One bootstrap cell the erroneous statement misdescribes.

    ``zero_included`` must agree with the recorded full-precision bounds, so the
    document cannot claim an interval excludes zero while its own numbers say it
    contains zero (or vice versa).
    """

    strategy: str
    cost_scenario: str
    interval_kind: str
    ci_lower: float
    ci_upper: float
    zero_included: bool

    def __post_init__(self) -> None:
        require_nonempty_str("strategy", self.strategy)
        require_nonempty_str("cost_scenario", self.cost_scenario)
        if self.interval_kind not in _INTERVAL_KINDS:
            raise ValueError(f"interval_kind must be one of {sorted(_INTERVAL_KINDS)}")
        _require_float("ci_lower", self.ci_lower)
        _require_float("ci_upper", self.ci_upper)
        require_bool("zero_included", self.zero_included)
        if self.ci_lower > self.ci_upper:
            raise ValueError(f"ci_lower {self.ci_lower!r} exceeds ci_upper {self.ci_upper!r}")
        if self.zero_included != interval_contains_zero(self.ci_lower, self.ci_upper):
            raise ValueError("zero_included is inconsistent with the recorded bounds")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "cost_scenario": self.cost_scenario,
            "interval_kind": self.interval_kind,
            "ci_lower": self.ci_lower,
            "ci_upper": self.ci_upper,
            "zero_included": self.zero_included,
        }

    @classmethod
    def from_json_dict(cls, payload: Any) -> AffectedCell:
        if not isinstance(payload, dict) or set(payload) != _CELL_KEYS:
            raise ValueError("affected cell keys do not match schema")
        return cls(
            strategy=payload["strategy"],
            cost_scenario=payload["cost_scenario"],
            interval_kind=payload["interval_kind"],
            ci_lower=_require_float("ci_lower", payload["ci_lower"]),
            ci_upper=_require_float("ci_upper", payload["ci_upper"]),
            zero_included=require_bool("zero_included", payload["zero_included"]),
        )


_ERRATUM_KEYS: frozenset[str] = frozenset(
    {
        "errata_schema_version",
        "erratum_id",
        "error_class",
        "target_experiment_id",
        "target_artifact_relpath",
        "target_artifact_sha256",
        "target_results_relpath",
        "target_results_sha256",
        "erroneous_statement",
        "erroneous_statement_sha256",
        "corrected_statement",
        "affected_cells",
        "affected_strategies",
        "affected_cost_scenarios",
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
class ArtifactErratum:
    """A strict, immutable correction document over one committed artifact."""

    errata_schema_version: int
    erratum_id: str
    error_class: str
    target_experiment_id: str
    target_artifact_relpath: str
    target_artifact_sha256: str
    target_results_relpath: str
    target_results_sha256: str
    erroneous_statement: str
    erroneous_statement_sha256: str
    corrected_statement: str
    affected_cells: tuple[AffectedCell, ...]
    affected_strategies: tuple[str, ...]
    affected_cost_scenarios: tuple[str, ...]
    financial_values_changed: bool
    methodology_changed: bool
    strategy_parameters_changed: bool
    development_gate_accessed: bool
    final_holdout_accessed: bool
    new_experiment_run: bool
    previous_erratum_sha256: str

    def __post_init__(self) -> None:
        if (
            require_int("errata_schema_version", self.errata_schema_version)
            != ERRATA_SCHEMA_VERSION
        ):
            raise ValueError(f"unsupported errata schema version {self.errata_schema_version!r}")
        require_evaluation_id("erratum_id", self.erratum_id)
        if self.error_class not in _SUPPORTED_ERROR_CLASSES:
            raise ValueError(f"unsupported error_class {self.error_class!r}")
        require_evaluation_id("target_experiment_id", self.target_experiment_id)
        require_safe_m3a_relpath("target_artifact_relpath", self.target_artifact_relpath)
        require_hex64("target_artifact_sha256", self.target_artifact_sha256)
        require_safe_m3a_relpath("target_results_relpath", self.target_results_relpath)
        require_hex64("target_results_sha256", self.target_results_sha256)
        require_nonempty_str("erroneous_statement", self.erroneous_statement)
        require_hex64("erroneous_statement_sha256", self.erroneous_statement_sha256)
        if self.erroneous_statement_sha256 != statement_domain_sha256(self.erroneous_statement):
            raise ValueError("erroneous_statement_sha256 does not match the statement bytes")
        require_nonempty_str("corrected_statement", self.corrected_statement)
        if not self.affected_cells:
            raise ValueError("affected_cells must be non-empty")
        # affected_strategies / _cost_scenarios must be exactly the sorted unique
        # values drawn from the cells — no undeclared or spurious entries.
        derived_strategies = tuple(sorted({c.strategy for c in self.affected_cells}))
        derived_scenarios = tuple(sorted({c.cost_scenario for c in self.affected_cells}))
        if tuple(self.affected_strategies) != derived_strategies:
            raise ValueError("affected_strategies must be the sorted unique cell strategies")
        if tuple(self.affected_cost_scenarios) != derived_scenarios:
            raise ValueError("affected_cost_scenarios must be the sorted unique cell scenarios")
        # A report-summary erratum changes no numbers, methodology, parameters,
        # sealed data, or experiment history: every such declaration is False.
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
            "target_artifact_relpath": self.target_artifact_relpath,
            "target_artifact_sha256": self.target_artifact_sha256,
            "target_results_relpath": self.target_results_relpath,
            "target_results_sha256": self.target_results_sha256,
            "erroneous_statement": self.erroneous_statement,
            "erroneous_statement_sha256": self.erroneous_statement_sha256,
            "corrected_statement": self.corrected_statement,
            "affected_cells": [c.to_json_dict() for c in self.affected_cells],
            "affected_strategies": list(self.affected_strategies),
            "affected_cost_scenarios": list(self.affected_cost_scenarios),
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
    def from_json_bytes(cls, raw: bytes) -> ArtifactErratum:
        payload = _strict_object(raw, _ERRATUM_KEYS, "artifact erratum")
        cells_raw = payload["affected_cells"]
        if not isinstance(cells_raw, list):
            raise ValueError("affected_cells must be a list")
        strategies_raw = payload["affected_strategies"]
        scenarios_raw = payload["affected_cost_scenarios"]
        if not isinstance(strategies_raw, list) or not isinstance(scenarios_raw, list):
            raise ValueError("affected_strategies/affected_cost_scenarios must be lists")
        return cls(
            errata_schema_version=payload["errata_schema_version"],
            erratum_id=payload["erratum_id"],
            error_class=payload["error_class"],
            target_experiment_id=payload["target_experiment_id"],
            target_artifact_relpath=payload["target_artifact_relpath"],
            target_artifact_sha256=payload["target_artifact_sha256"],
            target_results_relpath=payload["target_results_relpath"],
            target_results_sha256=payload["target_results_sha256"],
            erroneous_statement=payload["erroneous_statement"],
            erroneous_statement_sha256=payload["erroneous_statement_sha256"],
            corrected_statement=payload["corrected_statement"],
            affected_cells=tuple(AffectedCell.from_json_dict(c) for c in cells_raw),
            affected_strategies=tuple(require_nonempty_str("strategy", s) for s in strategies_raw),
            affected_cost_scenarios=tuple(
                require_nonempty_str("cost_scenario", s) for s in scenarios_raw
            ),
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
    """Percentage rendering used only for human display in the Markdown."""
    return f"{value * 100.0:+.6f}%"


def render_erratum_markdown(erratum: ArtifactErratum) -> bytes:
    """Deterministically render an erratum to Markdown bytes.

    The verifier re-renders and byte-compares, so the committed Markdown and the
    JSON model can never drift apart.
    """
    lines: list[str] = []
    add = lines.append
    add(f"# Erratum {erratum.erratum_id}")
    add("")
    add(f"- **Error class:** `{erratum.error_class}`")
    add(f"- **Target experiment:** `{erratum.target_experiment_id}`")
    add(f"- **Target artifact:** `{erratum.target_artifact_relpath}`")
    add(f"- **Target artifact SHA-256:** `{erratum.target_artifact_sha256}`")
    add(f"- **Target results:** `{erratum.target_results_relpath}`")
    add(f"- **Target results SHA-256:** `{erratum.target_results_sha256}`")
    add(f"- **Previous erratum SHA-256:** `{erratum.previous_erratum_sha256}`")
    add("")
    add("## Erroneous statement (preserved verbatim in the immutable artifact)")
    add("")
    add(f"> {erratum.erroneous_statement}")
    add("")
    add(f"Statement byte hash (domain-separated): `{erratum.erroneous_statement_sha256}`")
    add("")
    add("## Corrected statement")
    add("")
    add(erratum.corrected_statement)
    add("")
    add("## Affected cells (full precision, rederived from the committed results)")
    add("")
    add("| strategy | scenario | interval | ci_lower | ci_upper | contains zero |")
    add("| --- | --- | --- | --- | --- | --- |")
    for cell in erratum.affected_cells:
        add(
            f"| {cell.strategy} | {cell.cost_scenario} | {cell.interval_kind} | "
            f"{cell.ci_lower!r} ({_fmt_pct(cell.ci_lower)}) | "
            f"{cell.ci_upper!r} ({_fmt_pct(cell.ci_upper)}) | "
            f"{'yes' if cell.zero_included else 'no'} |"
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
        "target_artifact_relpath",
        "target_artifact_sha256",
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
    target_artifact_relpath: str
    target_artifact_sha256: str
    previous_entry_sha256: str

    def __post_init__(self) -> None:
        if (
            require_int("errata_schema_version", self.errata_schema_version)
            != ERRATA_SCHEMA_VERSION
        ):
            raise ValueError(f"unsupported errata schema version {self.errata_schema_version!r}")
        require_evaluation_id("erratum_id", self.erratum_id)
        require_safe_m3a_relpath("erratum_relpath", self.erratum_relpath)
        require_hex64("erratum_sha256", self.erratum_sha256)
        require_safe_m3a_relpath("erratum_markdown_relpath", self.erratum_markdown_relpath)
        require_hex64("erratum_markdown_sha256", self.erratum_markdown_sha256)
        require_evaluation_id("target_experiment_id", self.target_experiment_id)
        require_safe_m3a_relpath("target_artifact_relpath", self.target_artifact_relpath)
        require_hex64("target_artifact_sha256", self.target_artifact_sha256)
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
            "target_artifact_relpath": self.target_artifact_relpath,
            "target_artifact_sha256": self.target_artifact_sha256,
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
            target_artifact_relpath=payload["target_artifact_relpath"],
            target_artifact_sha256=payload["target_artifact_sha256"],
            previous_entry_sha256=payload["previous_entry_sha256"],
        )


def _read_registry_lines(path: Path) -> tuple[tuple[bytes, ErrataRegistryEntry], ...]:
    if not path.exists():
        return ()
    raw = path.read_bytes()
    if raw == b"":
        return ()
    if not raw.endswith(b"\n"):
        raise ArtifactErrataError("errata registry must end with a newline")
    out: list[tuple[bytes, ErrataRegistryEntry]] = []
    for chunk in raw.split(b"\n")[:-1]:
        if chunk == b"":
            raise ArtifactErrataError("errata registry must not contain a blank line")
        try:
            out.append((chunk, ErrataRegistryEntry.from_json_line(chunk)))
        except ValueError as exc:
            raise ArtifactErrataError(f"invalid errata registry line: {exc}") from exc
    return tuple(out)


def read_errata_registry(path: str | Path) -> tuple[ErrataRegistryEntry, ...]:
    """Strictly read the append-only, hash-chained errata registry.

    Enforces single-use erratum ids and the append-chain: each line's
    ``previous_entry_sha256`` equals the SHA-256 of the preceding line's exact
    bytes (genesis for the first line), so a line cannot be reordered, deleted,
    duplicated, or replaced without detection.
    """
    lines = _read_registry_lines(Path(path))
    seen: set[str] = set()
    for position, (_raw_line, entry) in enumerate(lines):
        if entry.erratum_id in seen:
            raise ArtifactErrataError(f"duplicate erratum id {entry.erratum_id!r}")
        seen.add(entry.erratum_id)
        expected_prev = GENESIS_SHA256 if position == 0 else sha256_bytes(lines[position - 1][0])
        if entry.previous_entry_sha256 != expected_prev:
            raise ArtifactErrataError(
                f"errata line {position + 1}: previous_entry_sha256 "
                f"{entry.previous_entry_sha256[:12]} != {expected_prev[:12]}"
            )
    return tuple(entry for _, entry in lines)


RUN003_REPORT_ZERO_INCLUSION_ERRATUM_ID: str = "m3a-run003-report-zero-inclusion-v1"

# The exact false universal clause in the immutable run-003 report (Section 5).
RUN003_ERRONEOUS_STATEMENT: str = (
    "every fold-aware bootstrap interval of mean daily paired excess return "
    "versus buy-and-hold straddles zero"
)

RUN003_CORRECTED_STATEMENT: str = (
    "The primary fold-stratified bootstrap intervals for sma_20_50 and "
    "donchian_55_20 straddle zero. The primary cash intervals are strictly below "
    "zero and therefore exclude zero on the underperformance (negative) side. The "
    "hierarchical sensitivity intervals straddle zero for every strategy, "
    "including cash. This is in-sample research-train evidence, not alpha, and "
    "promotes no candidate. The original report's rounded -0.00% display of the "
    "cash primary upper bound does not make zero part of the interval. All "
    "financial results remain unchanged from run-002."
)


def build_report_zero_inclusion_erratum(
    repo_root: str | Path,
    *,
    target_experiment_id: str = "m3a-fixed-baseline-comparison-v2-run-003",
    previous_erratum_sha256: str = GENESIS_SHA256,
) -> ArtifactErratum:
    """Construct the run-003 report zero-inclusion erratum from committed bytes.

    The affected cells are *derived* from the committed results model — every
    non-buy-and-hold primary cell whose interval excludes zero — never
    hand-typed, so the frozen document cannot silently disagree with the numbers.
    """
    from eth_research.development_results_v2 import load_development_results_v2
    from eth_research.experiment_registry import (
        EXPERIMENT_REGISTRY_RELPATH,
        ExperimentEventV2,
        read_registry,
    )

    root = Path(repo_root)
    events = read_registry(root / EXPERIMENT_REGISTRY_RELPATH)
    completed = next(
        (
            e
            for e in events
            if isinstance(e, ExperimentEventV2)
            and e.event == "completed"
            and e.experiment_id == target_experiment_id
        ),
        None,
    )
    if completed is None:
        raise ArtifactErrataError(f"{target_experiment_id} is not a completed v2 experiment")
    if completed.report_markdown_sha256 is None or completed.results_json_sha256 is None:
        raise ArtifactErrataError(
            f"{target_experiment_id} completed event is missing result hashes"
        )

    results = load_development_results_v2(root / completed.immutable_results_path)
    affected = tuple(
        AffectedCell(
            strategy=c.strategy,
            cost_scenario=c.cost_scenario,
            interval_kind="primary",
            ci_lower=c.primary.ci_lower,
            ci_upper=c.primary.ci_upper,
            zero_included=False,
        )
        for c in results.bootstrap_cells
        if not interval_contains_zero(c.primary.ci_lower, c.primary.ci_upper)
    )
    if not affected:
        raise ArtifactErrataError("no primary interval excludes zero; erratum is unwarranted")

    return ArtifactErratum(
        errata_schema_version=ERRATA_SCHEMA_VERSION,
        erratum_id=RUN003_REPORT_ZERO_INCLUSION_ERRATUM_ID,
        error_class=ERROR_CLASS_INCORRECT_SUMMARY,
        target_experiment_id=target_experiment_id,
        target_artifact_relpath=completed.immutable_report_path,
        target_artifact_sha256=completed.report_markdown_sha256,
        target_results_relpath=completed.immutable_results_path,
        target_results_sha256=completed.results_json_sha256,
        erroneous_statement=RUN003_ERRONEOUS_STATEMENT,
        erroneous_statement_sha256=statement_domain_sha256(RUN003_ERRONEOUS_STATEMENT),
        corrected_statement=RUN003_CORRECTED_STATEMENT,
        affected_cells=affected,
        affected_strategies=tuple(sorted({c.strategy for c in affected})),
        affected_cost_scenarios=tuple(sorted({c.cost_scenario for c in affected})),
        financial_values_changed=False,
        methodology_changed=False,
        strategy_parameters_changed=False,
        development_gate_accessed=False,
        final_holdout_accessed=False,
        new_experiment_run=False,
        previous_erratum_sha256=previous_erratum_sha256,
    )


def _read_under_root(repo_root: Path, relpath: str) -> bytes:
    """Read a repo-relative file, refusing symlinks and escapes."""
    require_safe_m3a_relpath("relpath", relpath)
    target = repo_root / relpath
    if target.is_symlink():
        raise ArtifactErrataError(f"errata artifact is a symlink: {relpath}")
    resolved = target.resolve()
    if repo_root.resolve() not in resolved.parents:
        raise ArtifactErrataError(f"errata artifact escapes the repository: {relpath}")
    if not target.is_file():
        raise ArtifactErrataError(f"errata artifact missing: {relpath}")
    return target.read_bytes()


def verify_artifact_errata(repo_root: str | Path) -> tuple[str, ...]:
    """Verify every erratum against the registry, the target, and the results.

    Independently proves, for each erratum, that: the target report/results
    bytes still hash to the target experiment's completed registry event; the
    erroneous statement is present verbatim in the target report; the affected
    cells rederive from the committed results model at full precision with the
    recorded zero-inclusion predicate; the cash primary cells exclude zero while
    the SMA/Donchian primary and every sensitivity interval contain it; no
    financial scalar changed; the rendered Markdown matches the model
    byte-for-byte; and both sealed access ledgers remain byte-empty.

    Returns the verified erratum ids. Raises :class:`ArtifactErrataError` on any
    mismatch. Read-only; never evaluates a sealed partition.
    """
    from eth_research.development_results_v2 import load_development_results_v2
    from eth_research.experiment_registry import (
        EXPERIMENT_REGISTRY_RELPATH,
        ExperimentEventV2,
        read_registry,
    )

    root = Path(repo_root)
    entries = read_errata_registry(root / ERRATA_REGISTRY_RELPATH)

    # Both sealed ledgers must be byte-empty whenever errata are verified.
    for ledger_rel in (_GATE_LEDGER_RELPATH, _HOLDOUT_LEDGER_RELPATH):
        if (root / ledger_rel).read_bytes() != b"":
            raise ArtifactErrataError(f"sealed ledger is not byte-empty: {ledger_rel}")

    events = read_registry(root / EXPERIMENT_REGISTRY_RELPATH)
    completed_v2 = {
        e.experiment_id: e
        for e in events
        if isinstance(e, ExperimentEventV2) and e.event == "completed"
    }

    verified: list[str] = []
    for entry in entries:
        erratum_bytes = _read_under_root(root, entry.erratum_relpath)
        if sha256_bytes(erratum_bytes) != entry.erratum_sha256:
            raise ArtifactErrataError(f"{entry.erratum_id}: erratum bytes hash != registry entry")
        try:
            erratum = ArtifactErratum.from_json_bytes(erratum_bytes)
        except ValueError as exc:
            raise ArtifactErrataError(f"{entry.erratum_id}: invalid erratum: {exc}") from exc
        if erratum.erratum_id != entry.erratum_id:
            raise ArtifactErrataError(f"{entry.erratum_id}: erratum id != registry entry id")
        if erratum.canonical_sha256() != entry.erratum_sha256:
            raise ArtifactErrataError(f"{entry.erratum_id}: erratum is not canonically serialized")

        # The rendered Markdown must match the model byte-for-byte.
        md_bytes = _read_under_root(root, entry.erratum_markdown_relpath)
        if sha256_bytes(md_bytes) != entry.erratum_markdown_sha256:
            raise ArtifactErrataError(f"{entry.erratum_id}: markdown bytes hash != registry entry")
        if md_bytes != render_erratum_markdown(erratum):
            raise ArtifactErrataError(
                f"{entry.erratum_id}: rendered markdown != committed markdown"
            )

        # Bind to the target experiment's completed registry event.
        if entry.target_experiment_id != erratum.target_experiment_id:
            raise ArtifactErrataError(f"{entry.erratum_id}: registry/erratum target id disagree")
        completed = completed_v2.get(erratum.target_experiment_id)
        if completed is None:
            raise ArtifactErrataError(
                f"{entry.erratum_id}: target {erratum.target_experiment_id} is not a completed v2 "
                "experiment"
            )
        if (
            erratum.target_artifact_relpath != completed.immutable_report_path
            or entry.target_artifact_relpath != completed.immutable_report_path
        ):
            raise ArtifactErrataError(
                f"{entry.erratum_id}: target artifact path != completed event"
            )
        if erratum.target_results_relpath != completed.immutable_results_path:
            raise ArtifactErrataError(f"{entry.erratum_id}: target results path != completed event")
        if (
            erratum.target_artifact_sha256 != completed.report_markdown_sha256
            or entry.target_artifact_sha256 != completed.report_markdown_sha256
        ):
            raise ArtifactErrataError(
                f"{entry.erratum_id}: target artifact hash != completed event"
            )
        if erratum.target_results_sha256 != completed.results_json_sha256:
            raise ArtifactErrataError(f"{entry.erratum_id}: target results hash != completed event")

        # The target bytes must still hash to those values (immutable, intact).
        report_bytes = _read_under_root(root, erratum.target_artifact_relpath)
        if sha256_bytes(report_bytes) != erratum.target_artifact_sha256:
            raise ArtifactErrataError(f"{entry.erratum_id}: target report bytes hash mismatch")
        results_bytes = _read_under_root(root, erratum.target_results_relpath)
        if sha256_bytes(results_bytes) != erratum.target_results_sha256:
            raise ArtifactErrataError(f"{entry.erratum_id}: target results bytes hash mismatch")

        # The erroneous statement must be present verbatim in the target report.
        report_text = report_bytes.decode("utf-8")
        if erratum.erroneous_statement not in report_text:
            raise ArtifactErrataError(
                f"{entry.erratum_id}: erroneous statement not found in target"
            )

        # Rederive every affected cell from the committed results model.
        results = load_development_results_v2(root / erratum.target_results_relpath)
        by_key = {(c.strategy, c.cost_scenario): c for c in results.bootstrap_cells}
        for cell in erratum.affected_cells:
            source = by_key.get((cell.strategy, cell.cost_scenario))
            if source is None:
                raise ArtifactErrataError(
                    f"{entry.erratum_id}: affected cell {cell.strategy}/{cell.cost_scenario} "
                    "is not in the results"
                )
            interval = source.primary if cell.interval_kind == "primary" else source.sensitivity
            if cell.ci_lower != interval.ci_lower or cell.ci_upper != interval.ci_upper:
                raise ArtifactErrataError(
                    f"{entry.erratum_id}: affected cell bounds != committed results"
                )
            if cell.zero_included != interval_contains_zero(interval.ci_lower, interval.ci_upper):
                raise ArtifactErrataError(
                    f"{entry.erratum_id}: affected cell zero-inclusion != committed results"
                )

        # The controlling scientific predicates, proven from the results model:
        # the three cash primary cells exclude zero; SMA/Donchian primary and
        # every sensitivity interval include it.
        for source in results.bootstrap_cells:
            primary_zero = interval_contains_zero(source.primary.ci_lower, source.primary.ci_upper)
            sens_zero = interval_contains_zero(
                source.sensitivity.ci_lower, source.sensitivity.ci_upper
            )
            if not sens_zero:
                raise ArtifactErrataError(
                    f"{entry.erratum_id}: sensitivity interval for {source.strategy}/"
                    f"{source.cost_scenario} unexpectedly excludes zero"
                )
            if source.strategy == "cash":
                if primary_zero:
                    raise ArtifactErrataError(
                        f"{entry.erratum_id}: cash primary {source.cost_scenario} unexpectedly "
                        "includes zero"
                    )
            elif not primary_zero:
                raise ArtifactErrataError(
                    f"{entry.erratum_id}: {source.strategy} primary {source.cost_scenario} "
                    "unexpectedly excludes zero"
                )
        verified.append(erratum.erratum_id)
    return tuple(verified)
