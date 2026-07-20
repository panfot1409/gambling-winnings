"""The evaluation gateway: the only door a buyer knocks on; it opens onto redacted artifacts only.

The gateway is an interface with one reference, in-memory, no-network implementation. Opening it
re-runs the redaction scan over the bundle (defense in depth) and refuses to open on any violation.
Once open, it serves only the bundle's redacted artifacts by name, and it *explicitly refuses* any
item the contract withholds — source, sealed partitions, credentials, live access, the ability to
run the governed experiment. There is no code path that reaches beyond the bundle: withheld items
are not present to serve, and asking for one returns a refusal, not data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from eth_research.buyer.contract import EvaluationContract
from eth_research.buyer.diligence import DiligenceBundle, assemble_diligence_bundle
from eth_research.buyer.redaction import RedactionPolicy
from eth_research.v2.strict import V2ValidationError, require_slug


class GatewayError(V2ValidationError):
    """A gateway could not open, or an item was refused/unknown."""


class EvaluationGateway(ABC):
    """The abstract buyer door: enumerate and serve redacted artifacts; refuse withheld items."""

    @abstractmethod
    def available(self) -> tuple[str, ...]:
        """The names of the redacted artifacts a buyer may fetch."""

    @abstractmethod
    def serve(self, artifact_name: str) -> str:
        """Return one redacted artifact's canonical text, or raise if it is not available."""

    @abstractmethod
    def request(self, item: str) -> str:
        """Serve an available artifact, or refuse an item withheld by the contract."""


@dataclass(slots=True)
class ReferenceEvaluationGateway(EvaluationGateway):
    """In-memory reference gateway over a redaction-scanned diligence bundle (no network)."""

    _contract: EvaluationContract
    _texts: dict[str, str]

    @staticmethod
    def open(
        bundle: DiligenceBundle | None = None, contract: EvaluationContract | None = None
    ) -> ReferenceEvaluationGateway:
        served = bundle if bundle is not None else assemble_diligence_bundle()
        # Defense in depth: re-scan even a bundle that assemble already scanned.
        violations = served.scan(RedactionPolicy.current())
        if violations:
            raise GatewayError(f"gateway refused to open on {len(violations)} redaction violations")
        # A supplied contract must match the fixed definition — an injected empty-withheld contract
        # cannot be used to weaken the withheld refusal (C3). The real guarantee is still that
        # ``_texts`` holds only the scanned artifacts; this is defense in depth on the withheld set.
        if (
            contract is not None
            and contract.fingerprint() != EvaluationContract.current().fingerprint()
        ):
            raise GatewayError("gateway refused: the supplied contract drifted from the fixed one")
        texts = {name: text for name, _kind, text in served.artifact_texts()}
        return ReferenceEvaluationGateway(
            _contract=contract if contract is not None else EvaluationContract.current(),
            _texts=texts,
        )

    def contract(self) -> EvaluationContract:
        return self._contract

    def available(self) -> tuple[str, ...]:
        return tuple(sorted(self._texts))

    def serve(self, artifact_name: str) -> str:
        name = require_slug("artifact_name", artifact_name)
        if name not in self._texts:
            raise GatewayError(f"no such available artifact: {name!r}")
        return self._texts[name]

    def request(self, item: str) -> str:
        name = require_slug("item", item)
        if name in self._contract.withheld:
            raise GatewayError(
                f"{name!r} is withheld by the evaluation contract and is never served"
            )
        return self.serve(name)
