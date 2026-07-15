# Milestone 3C — terminal audit

A read-only sign-off on the completed milestone: the adaptive-research governance
layer and one preregistered, executed experiment. It states what to check and what
the checks return.

## What M3C is

A governance layer that lets **one** adaptively-motivated candidate be declared in
full, executed exactly once on the research-train partition, and decided
mechanically — without ever touching the sealed development gate or final holdout,
and without the freedom to change a parameter after seeing a number.

- **Candidate (fixed, never replaced):** `dual_horizon_trend_63_252_vol_target_30d_50pct`
- **Experiment id (single-use):** `m3c-dual-horizon-trend-v1-run-001`
- **Outcome:** `rejected_for_development_gate_promotion`
- **Version:** 0.6.0 · **Base:** main `a7640e3` · **Branch:** `claude/m3c-adaptive-research-governance`

## Lifecycle — three green checkpoints, then execution

| checkpoint | commit | state | CI |
| --- | --- | --- | --- |
| code-freeze E | `59cdece` | pristine (protocol + empty registry) | green (checks 3.12/3.13 + all replays) |
| registration R | `00fe212` | registered (registry-only) | green (7/7 checks) |
| execute / publish P | `71aea1f` | completed (4 immutable artifacts) | see §CI |

Execution happened **only after** R was pushed and CI-green, through the fail-closed
orchestrator, which re-proved a clean tree, running-source == committed HEAD, both
sealed ledgers byte-empty, and the protocol's binding of the committed inputs before
appending `started`. The single-use id is now spent.

## Verification surface (all read-only, reproducible)

```
python -m eth_research.m3c.replay --repo-root . --check         -> completed
python -m eth_research.m3c.verify_archive --repo-root . --deep  -> 15 checks
python -m eth_research.m3c.recovery --repo-root . --status      -> no-intent
```

- The registry is a tamper-evident hash chain `registered → started → completed`;
  the `completed` event's `promotion_status` equals the mechanical decision.
- `verify_archive --deep` (15 checks) re-derives the decision mechanically from the
  committed results, re-renders the report byte-for-byte, re-binds all five committed
  inputs (protocol / lineage / budget / partition / dossier) to the registered
  digests, **validates the budget and lineage as the one canonical governance pair**
  (not by hash alone), checks the manifest/bundle chain, and reproduces the whole run
  from the raw committed data — every financial field byte-for-byte, the named secondary
  statistical scalars within the bounded-ULP contract (`<= 8` ULPs), and the mechanical
  verdict identical (see §Reproducibility).
- **Both sealed access ledgers are byte-empty** (`research/m3a/development_gate_access.jsonl`,
  `research/m2b/test_evaluations.jsonl`): the development gate and final holdout were
  never accessed.
- Determinism is enforced two ways: the orchestrator's own independent second rebuild
  (the mechanical P6 gate) and the `m3c-replay` CI on CPython 3.12 **and** 3.13.

## Adversarial review

- **Pre-registration red team** — three independent auditors (statistics/causality,
  decision/results/report, provenance/lifecycle) reviewed the frozen code before
  execution. No CRITICAL or HIGH defect. One decision-layer hardening (self-defending
  report render) and three provenance-checkpoint bindings (M1/M2/M3) were fixed;
  everything else is documented, pre-registered methodology or the accepted
  git-anchored threat model. See `docs/M3C_BUG_LOG.md`.
- **Post-run red team** — independent adversarial validation of the *published*
  artifacts (integrity, decision re-derivation, internal consistency, report honesty
  in both directions, provenance binding). Verdict: **CLEAN** — no integrity,
  decision-re-derivation, internal-consistency, report-honesty, or provenance-binding
  defect in the published run; the mechanical rejection is faithful to the numbers and
  not overstated. (Separately, the completed-checkpoint CI surfaced a cross-machine
  transcendental reproducibility issue in the *replay verifier*, not the artifacts;
  see §Reproducibility and `docs/M3C_BUG_LOG.md`.)
- **Independent-acceptance red team** — three further independent auditors
  (numerical/statistical, causality/firewall/governance, provenance/parsing/publication)
  re-audited the corrected numerical contract and the whole surface. No
  financial/scientific-integrity (Class A) or sealed-access/budget-drift (Class D) defect.
  Their real findings were reproduced and fixed — the exact bounded-ULP contract, the
  governance-document semantic validation, strict UTC timestamps, ascending fold order,
  the ledger symlink guard, and the honest `pow`-envelope scoping. See
  `docs/M3C_INDEPENDENT_ACCEPTANCE_AUDIT.md` and `docs/M3C_BUG_LOG.md`.

## Scientific honesty

- One **in-sample research-train** measurement of **one adaptively motivated**
  candidate. A result here is at most eligibility for an *independent* development-gate
  review — never "validated", "significant", "alpha", or approval to trade. The
  outcome was rejection, stated plainly and not softened. See `docs/M3C_FINDINGS.md`
  and `docs/M3C_STATISTICAL_METHOD_NOTE.md` (estimator, fold-seam-aware bootstrap,
  deliberate DSR/PBO omission).
- No parameter was changed to make the candidate pass; every losing fold is retained;
  the report uses no overclaiming language.

## What a reviewer should independently confirm

1. `git log a7640e3..HEAD` — the milestone commits, each a logical step.
2. The three CLIs above reproduce `completed` / 15 checks / `no-intent`.
3. `wc -c` on both sealed ledgers is `0`.
4. The full gate set is green: `ruff check .`, `ruff format --check .`,
   `mypy src tests examples`, `pytest`, and the `m3c-replay` CI on 3.12 + 3.13.
5. `candidate_decision.json` re-derives from `candidate_results.json` under the frozen
   P1–P7 rule and equals the committed bytes.

## Reproducibility (bounded-ULP contract)

The `m3c-replay` workflow reconstructs the research-train partition offline from the
committed raw Coinbase bytes and reproduces the published run on independent runners
(CPython 3.12.3 authoritative + 3.12 / 3.13 compat), under four separated contracts:

- **A** — every financial, structural, provenance, and cost field reproduces
  **byte-for-byte**;
- **B** — a *structurally-exact* allowlist of secondary statistical scalars (the
  fold-seam-aware bootstrap interval, the five per-fold paired log-excess means, the PSR
  block) may differ only by a bounded **integer ULP distance `<= 8`**, with exact
  path/type/finite/sign/zero guards, because each is derived from a non-correctly-rounded
  transcendental (`log1p`/`erf`). On CI the observed drift is exactly two leaves at 1–2
  ULPs. This is *bounded ULP variation*, not "last-ULP identical";
- **C** — the committed decision re-derives and the committed report re-renders
  byte-for-byte;
- **D** — the report rendered from the *reproduced* results matches the committed report
  byte-for-byte **modulo** its avalanching results-digest line.

The reproduction must additionally re-derive the **identical mechanical verdict**. Any
other difference fails closed with the offending fields listed as a CI annotation. The
byte-for-byte financial claim is scoped to this supported Linux/x86_64 glibc envelope;
some engine fields use a fractional `pow` and would need bounded-ULP treatment to widen
it (see `docs/M3C_STATISTICAL_METHOD_NOTE.md` §8). The execution host's own P6 gate
(independent second rebuild) still requires bit-identical output.

## CI

The freeze and registration checkpoints were confirmed green before advancing. The
completed checkpoint first published with `m3c-replay` red (the replay then demanded
byte-for-byte equality of the transcendental statistics, which cross-machine floating
point cannot guarantee); the numerical contract was subsequently corrected to the exact
bounded-ULP form above — committed on this branch, after the spent single-use run and
touching **no** published artifact, registry line, or computed number — and CI is green,
with the mechanical verdict proven unchanged. Final CI status is recorded at PR time. The
workflow also runs the numerical-contract acceptance tests on both interpreters and
asserts both sealed ledgers stay byte-empty in every state.
