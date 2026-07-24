# V2E Paper-Activation State Machine

States: `disabled → eligible → frozen → approved → active → paused → stopped`.
Edges (only these): disabled→eligible; eligible→frozen|disabled; frozen→approved|disabled;
approved→active|disabled; active→paused|stopped; paused→active|stopped; stopped→(none).

Seventeen requirements (all must be True to mint an activation token), each derived
fail-closed from committed evidence (`eth_research.v2e.paper.derive_requirements`):
eligible_nominated_candidate, immutable_candidate_fingerprint, valid_lineage,
candidate_not_previously_rejected, paper_protocol_preregistered, risk_parameters_frozen,
data_feed_configuration_frozen, cost_model_frozen, execution_simulator_frozen,
fable5_acceptance, no_unresolved_class_abd_defect, paper_release_source_freeze,
human_approval_artifact, kill_switch_qualified, monitoring_qualified,
sealed_ledgers_intact, repository_private. The first thirteen consume the accepted
fable5 paper-readiness gates (never re-derived here); kill-switch/monitoring demand
dedicated `governance/v2e/*_qualification.json` artifacts that do not exist yet.

Mechanics: resting state derivation can NEVER return `active`; stage entry re-checks its
prerequisite subset; entering `active` requires (a) a legal edge from `approved`,
(b) every requirement still True at transition time, and (c) an `ActivationToken` that
only `request_activation_token` can mint (module-private sentinel; exact-type check
defeats subclasses; stale tokens fail the re-check). There is no CLI flag, API
parameter, environment variable, subclass, alternate builder, or direct constructor
that skips any of this — bypass attempts are regression-tested. Current state:
**disabled** (no eligible nominated candidate exists).
