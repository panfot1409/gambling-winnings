"""Size-bounded execution-trace commitment for the M4B portfolio simulator (Milestone 4B, §35).

A whole simulation records one event per rebalance. Inlining every event into the result artifact
would make the artifact grow without bound on long runs, so M4B commits to the event trace with a
*size-bounded* structure instead: a domain-separated hash **chain** folded over every event in
order (so dropping, reordering, or editing any event changes the aggregate), the exact event count,
the first and last event identity, and a bounded, deterministic set of sampled event digests. The
chain is O(1) in size yet binds the full ordered sequence; the samples are capped at a constant.

The hash chain is the integrity mechanism; the samples are only a human-readable window into the
trace, so their exact selection is not security-critical. :func:`build_trace_commitment` derives
the commitment from a run; :func:`verify_trace_commitment` re-derives every digest from the run and
fails closed unless the chain, count, endpoints, and every retained sample match exactly.
:meth:`TraceCommitment.from_mapping` is the strict symmetric parser: it rejects unknown/missing
keys, non-finite numbers, booleans-as-ints, a mis-ordered or out-of-range sample, or a count that
disagrees with the endpoints it carries.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from eth_research.api.serialization import (
    CanonicalError,
    require_finite_float,
    require_int,
    require_list,
    require_mapping,
    require_sha256_hex,
    require_str,
)
from eth_research.portfolio._time import iso_utc
from eth_research.portfolio.engine import PortfolioRunResult
from eth_research.portfolio.validation import domain_hash, exact_keys

__all__ = [
    "TRACE_SCHEMA_VERSION",
    "EventDigest",
    "TraceCommitment",
    "build_trace_commitment",
    "verify_trace_commitment",
]

TRACE_SCHEMA_VERSION = 1

#: The maximum number of sampled event digests retained inline. The full sequence is always bound by
#: the O(1) hash chain regardless of this cap; the samples are a bounded, deterministic window.
DEFAULT_MAX_SAMPLES = 64

_DIGEST_FIELDS = {"index", "tau", "equity", "cash", "state_fingerprint"}
_COMMITMENT_FIELDS = {
    "schema_version",
    "event_count",
    "chain_hash",
    "first",
    "last",
    "samples",
}


@dataclass(frozen=True)
class EventDigest:
    """A minimal, order-aware digest of one recorded event, folded into the trace hash chain."""

    index: int
    tau: str
    equity: float
    cash: float
    state_fingerprint: str

    def canonical(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "tau": self.tau,
            "equity": self.equity,
            "cash": self.cash,
            "state_fingerprint": self.state_fingerprint,
        }

    @property
    def digest_hash(self) -> str:
        """The domain-separated hash of this digest — its identity within the chain."""
        return domain_hash("portfolio_event_digest", self.canonical())

    @classmethod
    def from_mapping(cls, data: Any, field: str) -> EventDigest:
        mapping = require_mapping(data, field)
        exact_keys(mapping, _DIGEST_FIELDS, field)
        index = require_int(mapping["index"], f"{field}.index")
        if index < 0:
            raise CanonicalError(f"{field}.index: must be non-negative")
        return cls(
            index=index,
            tau=require_str(mapping["tau"], f"{field}.tau"),
            equity=require_finite_float(mapping["equity"], f"{field}.equity"),
            cash=require_finite_float(mapping["cash"], f"{field}.cash"),
            state_fingerprint=require_sha256_hex(
                mapping["state_fingerprint"], f"{field}.state_fingerprint"
            ),
        )


def _chain_hash(digests: Iterable[EventDigest]) -> str:
    """Fold every digest into an order-sensitive hash chain.

    The accumulator starts at a fixed domain-separated seed and, for each event in order, becomes
    the hash of ``(previous accumulator, this digest's hash)``. Dropping, reordering, editing, or
    appending any event changes the final value; the result is O(1) in size.
    """
    acc = domain_hash("portfolio_trace_chain_init", {"schema_version": TRACE_SCHEMA_VERSION})
    for digest in digests:
        acc = domain_hash("portfolio_trace_chain_step", {"prev": acc, "digest": digest.digest_hash})
    return acc


def _sample_indices(n: int, max_samples: int) -> list[int]:
    """Deterministic, evenly spaced sample indices across ``[0, n)`` (endpoints included).

    Returns every index when ``n <= max_samples``; otherwise a distinct, ascending subset of size
    at most ``max_samples`` spread evenly across the range so the samples are representative of the
    whole trace, not just its head.
    """
    if n <= 0:
        return []
    if n <= max_samples:
        return list(range(n))
    if max_samples <= 1:
        return [0]
    picked = {round(i * (n - 1) / (max_samples - 1)) for i in range(max_samples)}
    return sorted(picked)


def _digests(run_result: PortfolioRunResult) -> tuple[EventDigest, ...]:
    return tuple(
        EventDigest(
            index=index,
            tau=iso_utc(event.tau),
            equity=event.equity,
            cash=event.cash,
            state_fingerprint=event.state_fingerprint,
        )
        for index, event in enumerate(run_result.events)
    )


@dataclass(frozen=True)
class TraceCommitment:
    """A size-bounded commitment to a whole event trace: a hash chain, count, endpoints, samples."""

    schema_version: int
    event_count: int
    chain_hash: str
    first: EventDigest | None
    last: EventDigest | None
    samples: tuple[EventDigest, ...]

    def canonical(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_count": self.event_count,
            "chain_hash": self.chain_hash,
            "first": None if self.first is None else self.first.canonical(),
            "last": None if self.last is None else self.last.canonical(),
            "samples": [sample.canonical() for sample in self.samples],
        }

    @property
    def commitment_id(self) -> str:
        """The domain-separated content hash over the whole commitment."""
        return domain_hash("portfolio_trace_commitment", self.canonical())

    @classmethod
    def from_mapping(cls, data: Any, field: str = "trace_commitment") -> TraceCommitment:
        mapping = require_mapping(data, field)
        exact_keys(mapping, _COMMITMENT_FIELDS, field)
        schema_version = require_int(mapping["schema_version"], f"{field}.schema_version")
        if schema_version != TRACE_SCHEMA_VERSION:
            raise CanonicalError(f"{field}.schema_version: unsupported")
        event_count = require_int(mapping["event_count"], f"{field}.event_count")
        if event_count < 0:
            raise CanonicalError(f"{field}.event_count: must be non-negative")
        chain_hash = require_sha256_hex(mapping["chain_hash"], f"{field}.chain_hash")

        first = _optional_digest(mapping["first"], f"{field}.first")
        last = _optional_digest(mapping["last"], f"{field}.last")
        # An empty trace has no endpoints; a non-empty one must carry both.
        if (event_count == 0) != (first is None) or (event_count == 0) != (last is None):
            raise CanonicalError(f"{field}: endpoints must be present iff event_count > 0")
        if first is not None and first.index != 0:
            raise CanonicalError(f"{field}.first: index must be 0")
        if last is not None and last.index != event_count - 1:
            raise CanonicalError(f"{field}.last: index must be event_count - 1")

        samples = tuple(
            EventDigest.from_mapping(row, f"{field}.samples[{i}]")
            for i, row in enumerate(require_list(mapping["samples"], f"{field}.samples"))
        )
        _check_sample_shape(samples, event_count, field)
        return cls(
            schema_version=schema_version,
            event_count=event_count,
            chain_hash=chain_hash,
            first=first,
            last=last,
            samples=samples,
        )


def _optional_digest(value: Any, field: str) -> EventDigest | None:
    return None if value is None else EventDigest.from_mapping(value, field)


def _check_sample_shape(samples: Sequence[EventDigest], event_count: int, field: str) -> None:
    if len(samples) > event_count:
        raise CanonicalError(f"{field}.samples: more samples than events")
    previous = -1
    for i, sample in enumerate(samples):
        if not 0 <= sample.index < event_count:
            raise CanonicalError(f"{field}.samples[{i}].index: out of range")
        if sample.index <= previous:
            raise CanonicalError(f"{field}.samples: indices must be strictly increasing")
        previous = sample.index


def build_trace_commitment(
    run_result: PortfolioRunResult, *, max_samples: int = DEFAULT_MAX_SAMPLES
) -> TraceCommitment:
    """Derive the size-bounded trace commitment for a run (deterministic; no wall clock)."""
    if max_samples < 1:
        raise CanonicalError("build_trace_commitment: max_samples must be >= 1")
    digests = _digests(run_result)
    n = len(digests)
    chosen = _sample_indices(n, max_samples)
    return TraceCommitment(
        schema_version=TRACE_SCHEMA_VERSION,
        event_count=n,
        chain_hash=_chain_hash(digests),
        first=digests[0] if n else None,
        last=digests[-1] if n else None,
        samples=tuple(digests[i] for i in chosen),
    )


def verify_trace_commitment(commitment: TraceCommitment, run_result: PortfolioRunResult) -> None:
    """Re-derive the trace from the run and fail closed unless the commitment matches it exactly.

    The hash chain proves the full ordered event sequence; the endpoints and every retained sample
    must additionally be authentic digests of the real events at their stated positions. Raises
    :class:`CanonicalError` on the first disagreement.
    """
    digests = _digests(run_result)
    n = len(digests)
    if commitment.event_count != n:
        raise CanonicalError("verify_trace: event_count does not match the run")
    if commitment.chain_hash != _chain_hash(digests):
        raise CanonicalError("verify_trace: chain hash does not match the run")
    expected_first = digests[0] if n else None
    expected_last = digests[-1] if n else None
    if commitment.first != expected_first:
        raise CanonicalError("verify_trace: first event does not match the run")
    if commitment.last != expected_last:
        raise CanonicalError("verify_trace: last event does not match the run")
    for i, sample in enumerate(commitment.samples):
        if not 0 <= sample.index < n:
            raise CanonicalError(f"verify_trace: sample {i} index out of range")
        if sample != digests[sample.index]:
            raise CanonicalError(f"verify_trace: sample {i} does not match the run")
