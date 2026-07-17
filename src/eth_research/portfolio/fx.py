"""Currency and FX evidence: causal, as-of conversion between a base and a quote currency.

An :class:`FxObservation` records that at ``observed_time`` one unit of ``base_currency`` was worth
``rate`` units of ``quote_currency`` (so ``value_in_quote = amount_in_base * rate``). An
:class:`FxEvidence` is the immutable, fingerprinted collection of those observations across one or
more directed pairs, from which :meth:`FxEvidence.rate_as_of` reads the most recent rate whose
``observed_time`` is at or before a decision time ``tau`` — never a future rate.

The conversion model is deliberately conservative. A same-currency conversion is ``1.0``; a directed
pair uses its own most-recent observation; the *explicit* inverse ``(quote, base)`` is used as
``1 / rate`` when the direct pair is absent. Any other path is rejected: this module never silently
triangulates through a third currency, because an unbounded search over pivots would make a rate
depend on an arbitrary, unstated choice of intermediary. Triangulation is available only when the
caller *predeclares* a single pivot for a specific pair. There is no external FX API, no implicit
``1:1`` fallback except same-currency, and instantaneous base-currency settlement at the as-of rate
is a research abstraction, not a claim about real-world execution.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from eth_research.api.serialization import (
    CanonicalError,
    require_finite_float,
    require_list,
    require_mapping,
    require_str,
)
from eth_research.portfolio._time import iso_utc, require_utc_timestamp
from eth_research.portfolio.currencies import require_currency_code
from eth_research.portfolio.validation import (
    domain_hash,
    exact_keys,
    require_positive_finite_float,
    require_safe_token,
)

__all__ = ["FxEvidence", "FxObservation"]

_OBSERVATION_FIELDS = {"base_currency", "quote_currency", "observed_time", "rate", "source"}
_TRIANGULATION_FIELDS = {"base", "quote", "pivot"}
_EVIDENCE_FIELDS = {"observations", "triangulation"}


def _require_ts(value: Any, field_name: str) -> pd.Timestamp:
    """A timezone-aware :class:`Timestamp`, normalized to UTC (rejects naive or non-Timestamp)."""
    if not isinstance(value, pd.Timestamp):
        raise CanonicalError(f"{field_name}: expected a pandas Timestamp")
    if value.tz is None:
        raise CanonicalError(f"{field_name}: timestamp must be timezone-aware UTC")
    return value.tz_convert("UTC")


@dataclass(frozen=True)
class FxObservation:
    """One directed FX rate: ``rate`` units of quote per one unit of base currency."""

    base_currency: str
    quote_currency: str
    observed_time: pd.Timestamp
    rate: float
    source: str

    def __post_init__(self) -> None:
        base = require_currency_code(self.base_currency, "fx_observation.base_currency")
        quote = require_currency_code(self.quote_currency, "fx_observation.quote_currency")
        if base == quote:
            raise CanonicalError(
                f"fx_observation.base_currency: must differ from quote_currency (both {base})"
            )
        require_positive_finite_float(self.rate, "fx_observation.rate")
        require_safe_token(self.source, "fx_observation.source")
        object.__setattr__(
            self, "observed_time", _require_ts(self.observed_time, "fx_observation.observed_time")
        )

    @property
    def pair(self) -> tuple[str, str]:
        """The directed ``(base_currency, quote_currency)`` pair this observation prices."""
        return (self.base_currency, self.quote_currency)

    def canonical(self) -> dict[str, Any]:
        """The canonical field mapping (observed_time as a canonical UTC ISO-8601 string)."""
        return {
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "observed_time": iso_utc(self.observed_time),
            "rate": self.rate,
            "source": self.source,
        }

    @classmethod
    def from_mapping(cls, data: Any, *, field: str = "fx_observation") -> FxObservation:
        """Construct from an untrusted mapping, rejecting unknown or missing keys."""
        mapping = require_mapping(data, field)
        exact_keys(mapping, _OBSERVATION_FIELDS, field)
        return cls(
            base_currency=require_str(mapping["base_currency"], f"{field}.base_currency"),
            quote_currency=require_str(mapping["quote_currency"], f"{field}.quote_currency"),
            observed_time=require_utc_timestamp(mapping["observed_time"], f"{field}.observed_time"),
            rate=require_finite_float(mapping["rate"], f"{field}.rate"),
            source=require_str(mapping["source"], f"{field}.source"),
        )


@dataclass(frozen=True)
class FxEvidence:
    """Immutable, fingerprinted FX observations with optional predeclared triangulation pivots.

    Observations are canonically ordered by ``(base, quote, observed_time)`` on construction;
    per directed pair they must be strictly ascending in time (no duplicate timestamps).
    ``triangulation`` maps a directed ``(base, quote)`` pair to a single pivot currency; when
    present it authorizes :meth:`rate_as_of` to compute ``base -> pivot -> quote`` from causal
    legs, and nothing else is ever triangulated.
    """

    observations: tuple[FxObservation, ...]
    triangulation: Mapping[tuple[str, str], str] | None = field(default=None)

    def __post_init__(self) -> None:
        observations = list(self.observations)
        for index, observation in enumerate(observations):
            if not isinstance(observation, FxObservation):
                raise CanonicalError(
                    f"fx_evidence.observations[{index}]: expected an FxObservation"
                )
        ordered = sorted(
            observations,
            key=lambda obs: (obs.base_currency, obs.quote_currency, iso_utc(obs.observed_time)),
        )
        for index in range(1, len(ordered)):
            previous = ordered[index - 1]
            current = ordered[index]
            same_pair = previous.pair == current.pair
            if same_pair and not previous.observed_time < current.observed_time:
                raise CanonicalError(
                    f"fx_evidence: observations for pair {current.pair} must be strictly "
                    "ascending by observed_time (no duplicate timestamps)"
                )
        object.__setattr__(self, "observations", tuple(ordered))
        object.__setattr__(self, "triangulation", self._normalize_triangulation(self.triangulation))

    @staticmethod
    def _normalize_triangulation(
        declared: Mapping[tuple[str, str], str] | None,
    ) -> dict[tuple[str, str], str]:
        if declared is None:
            return {}
        if not isinstance(declared, Mapping):
            raise CanonicalError("fx_evidence.triangulation: expected a mapping")
        normalized: dict[tuple[str, str], str] = {}
        for pair, pivot_value in declared.items():
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise CanonicalError(
                    "fx_evidence.triangulation: each key must be a (base, quote) pair"
                )
            base = require_currency_code(pair[0], "fx_evidence.triangulation.base")
            quote = require_currency_code(pair[1], "fx_evidence.triangulation.quote")
            pivot = require_currency_code(pivot_value, "fx_evidence.triangulation.pivot")
            if base == quote:
                raise CanonicalError(
                    "fx_evidence.triangulation: a pair's base must differ from its quote"
                )
            if pivot in (base, quote):
                raise CanonicalError(
                    "fx_evidence.triangulation: the pivot must differ from both base and quote"
                )
            normalized[(base, quote)] = pivot
        return normalized

    def __hash__(self) -> int:
        pivots = tuple(sorted((self.triangulation or {}).items()))
        return hash((self.observations, pivots))

    def _direct_rate_as_of(self, base: str, quote: str, moment: pd.Timestamp) -> float | None:
        """The most recent rate for the directed pair ``(base, quote)`` at or before ``moment``."""
        best: FxObservation | None = None
        for observation in self.observations:
            if observation.base_currency != base or observation.quote_currency != quote:
                continue
            if observation.observed_time > moment:
                continue
            if best is None or observation.observed_time > best.observed_time:
                best = observation
        return None if best is None else best.rate

    def _direct_or_inverse(self, base: str, quote: str, moment: pd.Timestamp) -> float | None:
        """The direct rate, else ``1 / inverse`` of an explicit ``(quote, base)`` pair."""
        direct = self._direct_rate_as_of(base, quote, moment)
        if direct is not None:
            return direct
        inverse = self._direct_rate_as_of(quote, base, moment)
        if inverse is not None:
            return 1.0 / inverse
        return None

    def rate_as_of(self, base: str, quote: str, tau: pd.Timestamp) -> float:
        """The causal ``quote``-per-``base`` rate usable at ``tau`` (never a future observation).

        Returns ``1.0`` for a same-currency conversion. Otherwise uses the direct pair, then the
        explicit inverse pair, then — only if the caller predeclared a pivot for ``(base, quote)`` —
        the ``base -> pivot -> quote`` product of causal legs. Raises :class:`CanonicalError` if no
        such rate exists at or before ``tau``.
        """
        base_code = require_currency_code(base, "fx_evidence.rate_as_of.base")
        quote_code = require_currency_code(quote, "fx_evidence.rate_as_of.quote")
        moment = _require_ts(tau, "fx_evidence.rate_as_of.tau")
        if base_code == quote_code:
            return 1.0
        direct = self._direct_or_inverse(base_code, quote_code, moment)
        if direct is not None:
            return direct
        pivot = (self.triangulation or {}).get((base_code, quote_code))
        if pivot is not None:
            first = self._direct_or_inverse(base_code, pivot, moment)
            second = self._direct_or_inverse(pivot, quote_code, moment)
            if first is None or second is None:
                raise CanonicalError(
                    f"fx_evidence.rate_as_of: predeclared triangulation {base_code}->{pivot}->"
                    f"{quote_code} has no causal rate as of {iso_utc(moment)}"
                )
            return first * second
        raise CanonicalError(
            f"fx_evidence.rate_as_of: no rate for ({base_code}, {quote_code}) as of "
            f"{iso_utc(moment)} (direct and explicit-inverse absent; no predeclared triangulation)"
        )

    def canonical(self) -> dict[str, Any]:
        """The canonical mapping: ordered observations and a sorted list of triangulation pivots."""
        pivots = sorted((self.triangulation or {}).items())
        return {
            "observations": [observation.canonical() for observation in self.observations],
            "triangulation": [
                {"base": base, "quote": quote, "pivot": pivot} for (base, quote), pivot in pivots
            ],
        }

    @property
    def fingerprint(self) -> str:
        """The domain-separated content hash of this evidence (stable across runtimes)."""
        return domain_hash("fx_evidence", self.canonical())

    @classmethod
    def from_mapping(cls, data: Any, *, field: str = "fx_evidence") -> FxEvidence:
        """Construct from an untrusted mapping, rejecting unknown or missing keys."""
        mapping = require_mapping(data, field)
        exact_keys(mapping, _EVIDENCE_FIELDS, field)
        raw_observations = require_list(mapping["observations"], f"{field}.observations")
        observations = tuple(
            FxObservation.from_mapping(item, field=f"{field}.observations[{index}]")
            for index, item in enumerate(raw_observations)
        )
        raw_triangulation = require_list(mapping["triangulation"], f"{field}.triangulation")
        triangulation: dict[tuple[str, str], str] = {}
        for index, entry in enumerate(raw_triangulation):
            row = require_mapping(entry, f"{field}.triangulation[{index}]")
            exact_keys(row, _TRIANGULATION_FIELDS, f"{field}.triangulation[{index}]")
            base = require_str(row["base"], f"{field}.triangulation[{index}].base")
            quote = require_str(row["quote"], f"{field}.triangulation[{index}].quote")
            pivot = require_str(row["pivot"], f"{field}.triangulation[{index}].pivot")
            if (base, quote) in triangulation:
                raise CanonicalError(f"{field}.triangulation: duplicate pair ({base}, {quote})")
            triangulation[(base, quote)] = pivot
        return cls(observations=observations, triangulation=triangulation)
