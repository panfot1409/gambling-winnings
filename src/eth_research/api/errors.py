"""Public, stable error taxonomy for the offline research platform.

Every failure a caller of :mod:`eth_research.api` or the ``eth-research`` CLI can
provoke by supplying bad input, an unsatisfiable configuration, a malformed dataset,
a misbehaving strategy, or a tampered artifact is one of the exceptions defined here.
Each carries a stable, machine-readable :attr:`~EthResearchError.code` and a
deterministic CLI :attr:`~EthResearchError.exit_code`, so a script can branch on the
*kind* of failure without parsing a human-readable message that may change.

Design contract (part of the public API surface, covered by tests):

* The hierarchy is closed and stable: ``EthResearchError`` is the single base; the
  concrete classes below are the only leaves. New kinds are additive, never renamed.
* ``code`` and ``exit_code`` are frozen per class. ``exit_code`` is grouped by family
  so shell callers can switch on a small set of numbers; ``code`` is unique per class
  for fine-grained machine handling.
* Every error distinguishes its :attr:`~EthResearchError.category` — ``input`` (the
  caller supplied something invalid), ``execution`` (a run-time invariant of the
  accepted engine was violated), ``verification`` (a committed artifact failed an
  integrity check), or ``output`` (a requested write would clobber or escape).
* An *unexpected* error — a genuine bug — is deliberately **not** in this taxonomy.
  The public functions never wrap an arbitrary ``Exception`` as an ``EthResearchError``;
  a bug propagates as itself so it is never silently reported as a user error. When one
  adapter translates a known internal exception into a public one it always does so with
  ``raise PublicError(...) from internal_exc`` so ``__cause__`` is preserved.
* A message must never embed private data or an absolute filesystem path into a
  *canonical artifact* (a result or a receipt). Error messages are for humans and the
  ``--json`` error envelope only; they are never serialized into the deterministic
  RunReceipt or ResearchResult bytes.
"""

from __future__ import annotations

from typing import Any, ClassVar

__all__ = [
    "AccountingError",
    "BacktestError",
    "CausalityError",
    "ConfigurationError",
    "DatasetError",
    "DatasetIntegrityError",
    "DatasetSchemaError",
    "EthResearchError",
    "OutputCollisionError",
    "ReceiptVerificationError",
    "ResultValidationError",
    "StrategyError",
]


class EthResearchError(Exception):
    """Base of every anticipated, caller-facing error in the public API.

    Catching this class catches exactly the set of failures the platform promises to
    raise for bad input, unsatisfiable configuration, or a failed integrity check.
    It does **not** catch programming bugs — those are left to propagate unchanged.
    """

    #: Stable machine-readable identifier, unique per concrete class.
    code: ClassVar[str] = "eth_research_error"
    #: Deterministic CLI process exit code, grouped by error family.
    exit_code: ClassVar[int] = 1
    #: One of ``"input"``, ``"execution"``, ``"verification"``, ``"output"``.
    category: ClassVar[str] = "error"

    def as_dict(self) -> dict[str, Any]:
        """The stable ``--json`` error envelope: code, category, and message.

        Used only for machine-readable CLI error output; never written into a
        canonical result or receipt artifact.
        """
        return {"error": self.code, "category": self.category, "message": str(self)}


class ConfigurationError(EthResearchError):
    """A configuration document is malformed, incomplete, or self-contradictory."""

    code = "configuration_error"
    exit_code = 3
    category = "input"


class DatasetError(EthResearchError):
    """A dataset could not be validated, loaded, or reconciled."""

    code = "dataset_error"
    exit_code = 4
    category = "input"


class DatasetSchemaError(DatasetError):
    """A dataset violates the OHLCV schema contract (columns, dtypes, index, ordering)."""

    code = "dataset_schema_error"
    exit_code = 4
    category = "input"


class DatasetIntegrityError(DatasetError):
    """A dataset's content fails an integrity check (fingerprint, gaps, duplicates)."""

    code = "dataset_integrity_error"
    exit_code = 4
    category = "input"


class StrategyError(EthResearchError):
    """A strategy is unknown, misconfigured, or produced an invalid target series."""

    code = "strategy_error"
    exit_code = 5
    category = "input"


class BacktestError(EthResearchError):
    """A backtest could not run to completion under the accepted execution contract."""

    code = "backtest_error"
    exit_code = 6
    category = "execution"


class AccountingError(BacktestError):
    """A backtest's cash/quantity/equity reconciliation invariant was violated."""

    code = "accounting_error"
    exit_code = 6
    category = "execution"


class CausalityError(BacktestError):
    """A backtest detected look-ahead: a decision depended on unavailable information.

    Reserved and exported so a caller can catch it: the accepted engines enforce causality
    *structurally* (a decision at bar *t* can only see data through *t*), so this is not
    raised on the built-in paths, but it remains part of the stable taxonomy for an
    engine-detected look-ahead violation.
    """

    code = "causality_error"
    exit_code = 6
    category = "execution"


class ResultValidationError(EthResearchError):
    """A research result failed structural validation or round-trip verification."""

    code = "result_validation_error"
    exit_code = 7
    category = "verification"


class ReceiptVerificationError(EthResearchError):
    """A run receipt does not match the artifacts it claims to bind."""

    code = "receipt_verification_error"
    exit_code = 8
    category = "verification"


class OutputCollisionError(EthResearchError):
    """A requested output path already exists, or would escape the output directory."""

    code = "output_collision_error"
    exit_code = 9
    category = "output"
