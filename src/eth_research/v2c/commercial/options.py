"""V2C section 31: the honest commercial-options record (not sell-ready).

Enumerates the *possible* commercial paths -- a private evaluation license, a managed evaluation
service, a research collaboration, an outright source acquisition -- and marks every one
``available_now = False`` with its unmet prerequisites. ``sell_ready`` is derived from the
constitution's standing posture (``not_sell_ready``) and is fixed to ``False``; the record cannot
assert otherwise. It also states honestly the only thing that *can* be offered today -- the redacted
evaluation surface, for diligence and not as a sale -- and what cannot: forward or live performance,
source, a license, or any sell-ready product.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.v2.constitution import STANDING_POSTURE
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_bool,
    require_choice,
    require_exact_keys,
    require_list,
    require_mapping,
    require_nonempty_str,
    require_slug,
)

COMMERCIAL_OPTIONS_SCHEMA_VERSION: int = 1

#: sell_ready is derived from the standing posture; it is only ever False here.
SELL_READY: bool = STANDING_POSTURE != "not_sell_ready"


class CommercialOptionsError(V2ValidationError):
    """A commercial option or the options record violated its not-sell-ready contract."""


@dataclass(frozen=True, slots=True)
class CommercialOption:
    """One possible commercial path, unavailable now, with its unmet prerequisites."""

    option_id: str
    description: str
    available_now: bool
    prerequisites_unmet: tuple[str, ...]

    @staticmethod
    def parse(label: str, value: object) -> CommercialOption:
        obj = require_mapping(label, value)
        require_exact_keys(
            label, obj, {"option_id", "description", "available_now", "prerequisites_unmet"}
        )
        available = require_bool(f"{label}.available_now", obj["available_now"])
        if available:
            raise CommercialOptionsError(
                f"{label}.available_now must be false; the programme is not sell-ready"
            )
        prerequisites = tuple(
            require_nonempty_str(f"{label}.prerequisites_unmet[{i}]", item)
            for i, item in enumerate(
                require_list(
                    f"{label}.prerequisites_unmet", obj["prerequisites_unmet"], lambda _l, v: v
                )
            )
        )
        if not prerequisites:
            raise CommercialOptionsError(f"{label} must list at least one unmet prerequisite")
        return CommercialOption(
            option_id=require_slug(f"{label}.option_id", obj["option_id"]),
            description=require_nonempty_str(f"{label}.description", obj["description"]),
            available_now=available,
            prerequisites_unmet=prerequisites,
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "option_id": self.option_id,
            "description": self.description,
            "available_now": self.available_now,
            "prerequisites_unmet": list(self.prerequisites_unmet),
        }


@dataclass(frozen=True, slots=True)
class CommercialOptions:
    """The fixed commercial-options record: paths, what can/cannot be offered, standing posture."""

    options: tuple[CommercialOption, ...]
    offerable_now: tuple[str, ...]
    not_offerable: tuple[str, ...]
    honest_limitation: str

    @staticmethod
    def current() -> CommercialOptions:
        return CommercialOptions(
            options=(
                CommercialOption(
                    option_id="private_evaluation_license",
                    description=(
                        "A private, time-boxed license to evaluate the redacted surface under a "
                        "signed agreement."
                    ),
                    available_now=False,
                    prerequisites_unmet=(
                        "explicit_human_authorization",
                        "license_decision",
                        "legal_review",
                    ),
                ),
                CommercialOption(
                    option_id="managed_evaluation_service",
                    description=(
                        "A vendor-run, process-isolated evaluation service that serves only "
                        "redacted diligence artifacts."
                    ),
                    available_now=False,
                    prerequisites_unmet=(
                        "explicit_human_authorization",
                        "operations_and_security_review",
                        "forward_evidence",
                    ),
                ),
                CommercialOption(
                    option_id="research_collaboration",
                    description=(
                        "A collaboration in which a partner contributes new information under a "
                        "governance agreement; no strategy is transferred."
                    ),
                    available_now=False,
                    prerequisites_unmet=(
                        "explicit_human_authorization",
                        "collaboration_agreement",
                    ),
                ),
                CommercialOption(
                    option_id="source_acquisition",
                    description=(
                        "An outright acquisition of the private implementation and its IP under a "
                        "negotiated agreement."
                    ),
                    available_now=False,
                    prerequisites_unmet=(
                        "explicit_human_authorization",
                        "valuation_and_diligence",
                        "legal_review",
                        "forward_evidence",
                    ),
                ),
            ),
            offerable_now=(
                "the_redacted_evaluation_surface_for_diligence_only",
                "the_readiness_scorecard_and_claims_catalog",
                "the_evaluation_contract_and_factsheet",
            ),
            not_offerable=(
                "forward_or_live_performance_evidence",
                "the_private_source_or_candidate_logic",
                "a_license_or_sell_ready_product",
                "any_routed_or_live_trading_capability",
            ),
            honest_limitation=(
                "Nothing here is for sale. Every path is unavailable now and gated on external "
                "human decisions. The only thing offerable today is the redacted evaluation "
                "surface for diligence, which is not a product and carries no forward evidence."
            ),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": COMMERCIAL_OPTIONS_SCHEMA_VERSION,
            "options_id": "v2c_commercial_options",
            "sell_ready": SELL_READY,
            "overall_posture": STANDING_POSTURE,
            "options": [o.to_canonical() for o in self.options],
            "offerable_now": list(self.offerable_now),
            "not_offerable": list(self.not_offerable),
            "honest_limitation": self.honest_limitation,
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())

    @staticmethod
    def parse(raw: object) -> CommercialOptions:
        obj = require_mapping("commercial_options", raw)
        require_exact_keys(
            "commercial_options",
            obj,
            {
                "schema_version",
                "options_id",
                "sell_ready",
                "overall_posture",
                "options",
                "offerable_now",
                "not_offerable",
                "honest_limitation",
            },
        )
        sell_ready = require_bool("commercial_options.sell_ready", obj["sell_ready"])
        if sell_ready:
            raise CommercialOptionsError("commercial_options.sell_ready must be false")
        require_choice(
            "commercial_options.overall_posture",
            obj["overall_posture"],
            frozenset({STANDING_POSTURE}),
        )
        options = tuple(
            require_list("commercial_options.options", obj["options"], CommercialOption.parse)
        )
        if not options:
            raise CommercialOptionsError("commercial_options must have at least one option")
        offerable = tuple(
            require_nonempty_str(f"commercial_options.offerable_now[{i}]", item)
            for i, item in enumerate(
                require_list(
                    "commercial_options.offerable_now", obj["offerable_now"], lambda _l, v: v
                )
            )
        )
        not_offerable = tuple(
            require_nonempty_str(f"commercial_options.not_offerable[{i}]", item)
            for i, item in enumerate(
                require_list(
                    "commercial_options.not_offerable", obj["not_offerable"], lambda _l, v: v
                )
            )
        )
        record = CommercialOptions(
            options=options,
            offerable_now=offerable,
            not_offerable=not_offerable,
            honest_limitation=require_nonempty_str(
                "commercial_options.honest_limitation", obj["honest_limitation"]
            ),
        )
        if record.fingerprint() != CommercialOptions.current().fingerprint():
            raise CommercialOptionsError("commercial options drifted from the fixed definition")
        return record


__all__ = [
    "COMMERCIAL_OPTIONS_SCHEMA_VERSION",
    "SELL_READY",
    "CommercialOption",
    "CommercialOptions",
    "CommercialOptionsError",
]
