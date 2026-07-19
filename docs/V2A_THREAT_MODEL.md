# V2A Threat Model

Adversarial view of the V2A stack: what could go wrong, and the mechanical control that prevents it.
"Mechanical" means enforced by code/tests/CI, not by discipline alone.

| # | Threat | Control | Where |
| --- | --- | --- | --- |
| T1 | Look-ahead: a shadow run reads a bar or signal before its time | Monotonic as-of clock; `require_visible` rejects any timestamp after the frontier; the runner advances the clock per bar | `shadow/clock.py`, `shadow/runner.py` |
| T2 | Sealed-data leakage into a buyer bundle | Redaction scanner rejects raw/tabular data; diligence assembly + gateway open both fail closed on any violation | `buyer/redaction.py`, `buyer/diligence.py`, `buyer/gateway.py` |
| T3 | Source disclosure at the buyer boundary | Kind allowlist + embedded-source detector; the gateway serves only redacted artifacts and refuses `source_code` explicitly | `buyer/redaction.py`, `buyer/gateway.py` |
| T4 | Over-claiming (forward / live / sell-ready) | Every claim status is decoded through the constitution; reserved/non-emittable statuses are rejected; standing posture `not_sell_ready` | `v2/constitution.py`, `buyer/claims.py` |
| T5 | Running the governed experiment more than once | Append-only hash-chained registry; a single `started` consumes the one-shot budget forever, even on failure | `v2/registry.py`, `v2/orchestrator.py` |
| T6 | Silent tampering of a published result or journal | Manifest binds results by SHA-256; registry/journal are hash-chained; a changed byte breaks the chain at parse | `v2/publication.py`, `v2/registry.py`, `shadow/journal.py` |
| T7 | Network / exchange / wallet reach | AST no-import hygiene gate over source/tests/examples; workflow host allowlist (astral.sh only); mode boundary rejects live/production | `tests/test_repo_hygiene.py`, `tests/test_workflow_security.py`, `shadow/domain.py` |
| T8 | Order placement / money movement | The only execution adapter is `PaperExecutionAdapter` (records, never routes); there is no live adapter and one cannot be added without tripping the import gate | `shadow/adapter.py` |
| T9 | Uncontrolled risk in a shadow run | Pure risk-limit engine clamps exposure; a hard breach trips the latching kill switch, which blocks all further intents until an explicit reset | `shadow/risk.py`, `shadow/kill_switch.py` |
| T10 | A workflow gaining write / secrets / OIDC | Repository-wide workflow-security tests: no `contents: write`, no secrets, no `id-token`, SHA-pinned actions, no artifact upload (except the allowlisted private builder) | `tests/test_workflow_security.py` |
| T11 | A protocol/decision drift changing an outcome after the fact | Protocol, contract, and results are fingerprinted; the replay verifier re-asserts them and binds a published run to the current protocol | `v2/replay.py` |

## Residual risks (honest)

- Research-train evidence is **in-sample**: it is not out-of-sample, forward, or live. The whole
  stack is engineered to prevent *overstating* that, not to make it more than it is.
- The redaction scanner is heuristic; it is a fail-closed backstop over already source-free,
  strictly-typed artifacts, not a substitute for building the bundle correctly.
- Sealed-partition evaluation, live/paper connectivity, and any commercial step are explicitly out of
  scope and gated on separate human authorization.
