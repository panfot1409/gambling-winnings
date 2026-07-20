"""V2C section 28: the inactive offline-operations deployment blueprint.

Documents *how the offline operational-qualification system is organized* -- the shadow
platform, the virtual-time qualification harness, the process-isolated buyer boundary, the
offline prospective governance, and the candidate-free execution firewall -- as a **blueprint
only**. Nothing here is activated: ``status`` is fixed to ``inactive``, ``activated`` is
``False``, network egress and order routing are ``False``, and every activation precondition is
an unmet external human gate. The blueprint is a fixed definition pinned by fingerprint (a
drifted blueprint is rejected), so it cannot silently acquire an active capability.
"""

from __future__ import annotations

from dataclasses import dataclass

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

DEPLOYMENT_SCHEMA_VERSION: int = 1

#: The blueprint may only ever describe the inactive posture.
DEPLOYMENT_STATUS_INACTIVE: str = "inactive"

_COMPONENT_KEYS = frozenset({"component_id", "role", "offline", "non_routing"})
_PRECONDITION_KEYS = frozenset({"precondition_id", "description", "met"})
_BLUEPRINT_KEYS = frozenset(
    {
        "schema_version",
        "blueprint_id",
        "status",
        "activated",
        "network_egress_enabled",
        "order_routing_enabled",
        "components",
        "prohibited_capabilities",
        "activation_preconditions",
        "honest_limitation",
    }
)


class DeploymentBlueprintError(V2ValidationError):
    """A deployment blueprint violated the inactive-only contract."""


@dataclass(frozen=True, slots=True)
class DeploymentComponent:
    """One offline, non-routing component in the blueprint."""

    component_id: str
    role: str
    offline: bool
    non_routing: bool

    @staticmethod
    def parse(label: str, value: object) -> DeploymentComponent:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _COMPONENT_KEYS)
        offline = require_bool(f"{label}.offline", obj["offline"])
        non_routing = require_bool(f"{label}.non_routing", obj["non_routing"])
        if not offline:
            raise DeploymentBlueprintError(f"{label}.offline must be true in an inactive blueprint")
        if not non_routing:
            raise DeploymentBlueprintError(f"{label}.non_routing must be true")
        return DeploymentComponent(
            component_id=require_slug(f"{label}.component_id", obj["component_id"]),
            role=require_nonempty_str(f"{label}.role", obj["role"]),
            offline=offline,
            non_routing=non_routing,
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "component_id": self.component_id,
            "role": self.role,
            "offline": self.offline,
            "non_routing": self.non_routing,
        }


@dataclass(frozen=True, slots=True)
class ActivationPrecondition:
    """One external human gate that would be required before any activation; always unmet here."""

    precondition_id: str
    description: str
    met: bool

    @staticmethod
    def parse(label: str, value: object) -> ActivationPrecondition:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _PRECONDITION_KEYS)
        met = require_bool(f"{label}.met", obj["met"])
        if met:
            raise DeploymentBlueprintError(
                f"{label}.met must be false; the blueprint is inactive and no gate is satisfied"
            )
        return ActivationPrecondition(
            precondition_id=require_slug(f"{label}.precondition_id", obj["precondition_id"]),
            description=require_nonempty_str(f"{label}.description", obj["description"]),
            met=met,
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "precondition_id": self.precondition_id,
            "description": self.description,
            "met": self.met,
        }


@dataclass(frozen=True, slots=True)
class DeploymentBlueprint:
    """The fixed, inactive offline-operations deployment blueprint."""

    components: tuple[DeploymentComponent, ...]
    prohibited_capabilities: tuple[str, ...]
    activation_preconditions: tuple[ActivationPrecondition, ...]
    honest_limitation: str

    @staticmethod
    def current() -> DeploymentBlueprint:
        return DeploymentBlueprint(
            components=(
                DeploymentComponent(
                    component_id="execution_firewall",
                    role=(
                        "First-gate candidate-free firewall: rejects every strategy/candidate id "
                        "and admits only the all-zero cash_control target."
                    ),
                    offline=True,
                    non_routing=True,
                ),
                DeploymentComponent(
                    component_id="shadow_platform",
                    role=(
                        "Signal-only shadow operations: passive as-of clock, hash-chained journal, "
                        "latching kill switch, paper accounting; imports no candidate or engine."
                    ),
                    offline=True,
                    non_routing=True,
                ),
                DeploymentComponent(
                    component_id="operational_qualification",
                    role=(
                        "Virtual-time qualification harness over a synthetic event stream with a "
                        "fault schedule; measures offline SLOs, never a strategy."
                    ),
                    offline=True,
                    non_routing=True,
                ),
                DeploymentComponent(
                    component_id="prospective_governance",
                    role=(
                        "Offline prospective-proposal lifecycle (prepared, not activated); fetches "
                        "no new candles and installs no standing write workflow."
                    ),
                    offline=True,
                    non_routing=True,
                ),
                DeploymentComponent(
                    component_id="buyer_boundary",
                    role=(
                        "Process-isolated buyer evaluation that serves only redacted artifacts "
                        "over a length-prefixed protocol; the vendor keeps the implementation."
                    ),
                    offline=True,
                    non_routing=True,
                ),
            ),
            prohibited_capabilities=(
                "live_trading",
                "paper_trading_connectivity",
                "order_routing",
                "broker_or_exchange_integration",
                "credentials_or_wallets",
                "leverage_borrow_margin_shorts_or_derivatives",
                "new_real_market_data_acquisition",
                "standing_write_capable_workflow",
                "public_deployment_or_publication",
            ),
            activation_preconditions=(
                ActivationPrecondition(
                    precondition_id="explicit_human_authorization",
                    description=(
                        "A human owner must explicitly authorize any activation; this blueprint "
                        "grants none and is prepared for review only."
                    ),
                    met=False,
                ),
                ActivationPrecondition(
                    precondition_id="forward_evidence_qualification",
                    description=(
                        "Out-of-sample or forward performance evidence would be required; none "
                        "exists, and V2C evaluates no strategy to create any."
                    ),
                    met=False,
                ),
                ActivationPrecondition(
                    precondition_id="broker_or_exchange_review",
                    description=(
                        "Any connectivity would require a separate, out-of-scope broker/exchange "
                        "integration and its own security review."
                    ),
                    met=False,
                ),
                ActivationPrecondition(
                    precondition_id="license_and_commercial_decision",
                    description=(
                        "A licensing and commercial decision is an external human gate; the "
                        "programme's standing posture is not_sell_ready."
                    ),
                    met=False,
                ),
                ActivationPrecondition(
                    precondition_id="security_and_legal_review",
                    description=(
                        "A full security and legal review would be required before activation; it "
                        "has not been performed."
                    ),
                    met=False,
                ),
            ),
            honest_limitation=(
                "This is a blueprint, not a deployment. It documents how the offline components "
                "are organized; it activates nothing, routes no orders, opens no network egress, "
                "and grants no capability. Every activation precondition is an unmet human gate."
            ),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": DEPLOYMENT_SCHEMA_VERSION,
            "blueprint_id": "v2c_offline_operational_deployment",
            "status": DEPLOYMENT_STATUS_INACTIVE,
            "activated": False,
            "network_egress_enabled": False,
            "order_routing_enabled": False,
            "components": [c.to_canonical() for c in self.components],
            "prohibited_capabilities": list(self.prohibited_capabilities),
            "activation_preconditions": [p.to_canonical() for p in self.activation_preconditions],
            "honest_limitation": self.honest_limitation,
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())

    @staticmethod
    def parse(raw: object) -> DeploymentBlueprint:
        obj = require_mapping("deployment_blueprint", raw)
        require_exact_keys("deployment_blueprint", obj, _BLUEPRINT_KEYS)
        require_choice(
            "deployment_blueprint.status", obj["status"], frozenset({DEPLOYMENT_STATUS_INACTIVE})
        )
        activated = require_bool("deployment_blueprint.activated", obj["activated"])
        egress = require_bool(
            "deployment_blueprint.network_egress_enabled", obj["network_egress_enabled"]
        )
        routing = require_bool(
            "deployment_blueprint.order_routing_enabled", obj["order_routing_enabled"]
        )
        if activated or egress or routing:
            raise DeploymentBlueprintError(
                "deployment_blueprint must be inactive with no egress and no routing"
            )
        components = tuple(
            require_list(
                "deployment_blueprint.components", obj["components"], DeploymentComponent.parse
            )
        )
        preconditions = tuple(
            require_list(
                "deployment_blueprint.activation_preconditions",
                obj["activation_preconditions"],
                ActivationPrecondition.parse,
            )
        )
        prohibited = tuple(
            require_nonempty_str(f"deployment_blueprint.prohibited_capabilities[{i}]", item)
            for i, item in enumerate(
                require_list(
                    "deployment_blueprint.prohibited_capabilities",
                    obj["prohibited_capabilities"],
                    lambda _label, value: value,
                )
            )
        )
        if not components or not preconditions:
            raise DeploymentBlueprintError("blueprint needs components and preconditions")
        blueprint = DeploymentBlueprint(
            components=components,
            prohibited_capabilities=prohibited,
            activation_preconditions=preconditions,
            honest_limitation=require_nonempty_str(
                "deployment_blueprint.honest_limitation", obj["honest_limitation"]
            ),
        )
        # Pin to the fixed definition: a drifted blueprint is rejected (defense in depth).
        # ``status`` is already constrained to ``inactive`` by ``require_choice`` above.
        if blueprint.fingerprint() != DeploymentBlueprint.current().fingerprint():
            raise DeploymentBlueprintError("deployment blueprint drifted from the fixed definition")
        return blueprint


__all__ = [
    "DEPLOYMENT_SCHEMA_VERSION",
    "DEPLOYMENT_STATUS_INACTIVE",
    "ActivationPrecondition",
    "DeploymentBlueprint",
    "DeploymentBlueprintError",
    "DeploymentComponent",
]
