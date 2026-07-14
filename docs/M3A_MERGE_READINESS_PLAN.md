# Milestone 3A — Merge-Readiness Audit, Append-Only Report Erratum, Standing E2E, and PR Truthfulness

This is a **development-only, research-only** closure milestone. It adds **no**
strategy, optimization, candidate, or sealed-partition evaluation. Its goal is
to make the existing M3A history, artifacts, tests, documentation, and PR #4
**truthful, standing, independently verifiable, and ready for human review**.

This is **not** Milestone 3B.

## 0. Starting facts (independently verified — Phase 0)

| Fact | Value |
| --- | --- |
| Repository | `/home/user/gambling-winnings` |
| Branch | `claude/m3a-development-research-lab` |
| Local == remote HEAD | `dcf65f259a482d14648853494f4ad5eb40cfc58a` |
| `origin/main` == merge-base | `ed53eb23d951b5b4726dfae1bad22ccd93e3f153` |
| Tags | `v0.1.0 v0.2.0 v0.3.0` (no `v0.4.0`) |
| Working tree | clean |
| PR #4 | open · draft · not merged · mergeable_state clean · base `main` · head `dcf65f2` · 104 files · 66 commits · **0 reviews · 0 review threads** |
| CI @ HEAD | 17 check-runs, **all success** (CI ×2, M3A Replay ×2, M2B Replay ×1) |
| Gate ledger | `research/m3a/development_gate_access.jsonl` = **0 bytes** `e3b0c442…` |
| Holdout ledger | `research/m2b/test_evaluations.jsonl` = **0 bytes** `e3b0c442…` |
| Registry | **9 non-empty lines**; six-line v1 prefix `7920d9fd…e9af67` **== pin** |
| Registry lifecycle | run-001 / run-002 / run-003, each `registered → started → completed` |
| E (execution source) | `b27f5d9c84d378d69ab31b0fcfda388af6b3698e` |
| R (registration) | `082b452123ee2a728ceb612aa08bb1599af621ff` |
| run_head | `cd868e8c1cfee3b92aa67db12e71b131dca4bba3` |
| P (publication) | `e83c048c89dad45590850382b9cc952d268469e8` |
| `src/eth_research` tree | `e0d3c487…` **byte-identical at E, R, run_head, P, HEAD** |
| E→R registry delta | exactly **one** line (run-003 v2 `registered`); E=6 lines, R=7 |
| run-003 report hash | `d6e920760fd4217cbac00cf6126b0da2afc1f0a9e673aacfc9aee5fc6baa3bfd` (== expected) |
| run-003 results hash | `5f6377b6eb0eb8c2a5ba126c37b29de5095670f7ed27c064f44e18c9c91ea8ae` |
| run-003 evidence hash | `b593a03cbdd4edd4ceb09b035312713df555cd71a5662c757dd8f0e13b1c6f71` |
| run-003 manifest hash | `1ea0ade8ed291762a6571c352550b24697137235305163579dda6a76739f4e24` |

## 1. Known discrepancies (reproduce before fixing — Phase 1)

- **K1 — PR #4 body is materially stale.** It still calls run-002 terminal,
  claims "every bootstrap interval … straddles zero", and says the review found
  no statistics defects. It omits run-003, bootstrap v2, hierarchical
  sensitivity, the nine-line registry, three archives, and the cash
  negative-side exception. *Documentation-only; class A.*
- **K2 — the immutable run-003 report contains a false universal summary.**
  Line 56: *"…every fold-aware bootstrap interval … straddles zero."* At full
  precision the three **cash primary** intervals have `ci_upper < 0`:

  | cell | ci_lower | ci_upper | contains 0? |
  | --- | --- | --- | --- |
  | cash / base | `-0.005063937422795938` | `-1.220168774754618e-05` | **no** |
  | cash / stressed | `-0.005063904789164851` | `-1.1503664325654388e-05` | **no** |
  | cash / severe | `-0.005062567013459328` | `-1.0358783751154005e-05` | **no** |

  SMA and Donchian primary intervals, and **all** hierarchical-sensitivity
  intervals (incl. cash), do contain zero. Financial numbers are correct; only
  the prose is false. *Immutable-report prose defect; class B → append-only
  erratum. Never edit the archived bytes.*
- **K3 — the successful E2E lifecycle test disappears after completion.**
  `tests/test_m3a_orchestrator_e2e.py`'s `_REHEARSABLE` skips both classes once
  real run-003 is `completed`, so CI no longer exercises the
  `registered → started → publish → readback → completed → replay → single-use
  refusal` path. *Governance/test defect; class C → make standing.*
- **K4 — terminal audit names a stale "Final HEAD."**
  `docs/M3A_RUN003_TERMINAL_AUDIT.md:13` says `Final HEAD: b4e9072…`, a
  pre-documentation commit (the doc itself was committed later at `dcf65f2`).
  *Documentation semantics; class A → distinguish audited checkpoint vs
  doc-commit vs externally-reported branch head; never claim a file contains its
  own commit SHA.*

## 2. Append-only, machine-verified report erratum (Phase 2)

The run-003 report is immutable history; its bytes are preserved exactly. A
first-class errata layer records the correction out-of-band.

- **Module** `src/eth_research/artifact_errata.py`.
- **Tracked paths** `research/m3a/artifact_errata.jsonl` (hash-chained,
  append-only index) and `research/m3a/errata/` (one strict JSON + one rendered
  Markdown per erratum).
- **Strict model** `ArtifactErratum` — frozen dataclass parsed through the
  shared strict JSON decoder (`_json.strict_json_loads`); rejects
  duplicate/unknown/missing keys, bool-as-int, non-finite numbers, unsafe paths,
  invalid hashes, naive times, and inconsistent declarations. Binds: schema
  version, erratum id, target experiment id, target artifact/results relpaths and
  SHA-256, domain-separated hash of the exact erroneous statement bytes, error
  class `incorrect_statistical_summary`, corrected statement, machine-readable
  affected cells (each strategy/scenario with exact `ci_lower`/`ci_upper` and
  `zero_included` predicate), the five "changed?" booleans (all false), gate/
  holdout accessed (both false), `previous_erratum_sha256` (or genesis), and the
  canonical erratum SHA-256. Affected cells are **built from the validated
  committed results model** then frozen — never hand-typed.
- **Registry** `research/m3a/artifact_errata.jsonl` — append-only, single-use
  ids, each line binds prior-line hash + erratum JSON bytes + target artifact
  hash; rejects reorder/delete/truncate/duplicate/replace; no silent repair. It
  is **not** an experiment-lifecycle event — the experiment registry is untouched.
- **Verification** `verify_artifact_errata(repo_root)` (mirrors
  `verify_experiment_archive`), wired into: experiment-archive verification,
  `verify_m3a_registry.py`, `develop_m3a --check` (prints
  `reproducible (v2 …, 1 verified bound erratum)`), M3A Replay CI, and hygiene.
  It independently proves the ten predicates in the milestone (target bytes still
  hash to the completed event, the erroneous statement exists verbatim, the three
  cash `ci_upper < 0`, hierarchical cash includes zero, SMA/Donchian primary
  include zero, no financial scalar changed, both ledgers byte-empty, model ==
  rendered Markdown).
- **Adversarial tests** `tests/test_artifact_errata.py` — the full milestone
  matrix (changed hashes/paths, missing statement, wrong id, fabricated cell,
  sign-flip, `ci_upper == 0`, omitted scenario, false SMA/Donchian exclusion,
  false "financials changed"/gate-access claims, reorder/delete/dupe-id/broken
  chain/edited Markdown/symlink/traversal/dup-keys/NaN/bool-as-int/unknown keys).

## 3. Standing end-to-end orchestrator (Phase 3)

Remove the terminal-state skip **without** touching the real registry or
rerunning the real experiment. The disposable-clone lifecycle test becomes:

1. resolve E from the real run-003 `registered` event's
   `execution_code_commit_sha`; assert E is an ancestor of HEAD and the current
   `src/eth_research` tree is byte-identical to E's;
2. restore the clone's M3A artifact state **to E** (`git rm -rf research/m3a &&
   git checkout E -- research/m3a`): six-line v1 prefix, run-003 absent, aliases
   → run-002, no run-003 archive, both ledgers empty;
3. register run-003 with the production CLI; commit registry-only R′; assert
   E′→R′ changes exactly one registry line;
4. drive the full production lifecycle in a subprocess importing the clone's
   package; assert registered→started→completed, started precedes first
   strategy/engine/bootstrap call, immutable archive + alias migration +
   manifest-last publish, intent cleared, both ledgers still empty, financial
   equivalence to run-002 (60/12/12/12), replay + registry verify, and single-use
   rerun refusal; then destroy the clone.

The skip is **runtime-gated only** (skips off the frozen CPython 3.12.3 runtime,
never because run-003 is complete). A dedicated `authoritative-runtime` CI step
runs the exact node id and **fails if pytest reports it skipped/deselected/
xfailed**. Failure-path disposable-clone rehearsals cover unregistered refusal,
post-`started` crash, publication-verifier failure, completion-append failure,
calculation-free recovery, corrupted-intent refusal, and consumed-id rerun.

## 4. Independent merge-readiness red team (Phase 4)

Three READ-ONLY subagents; the primary agent reproduces every finding before
accepting it. Executable reproduction is required for each accepted finding.

| Agent | Dimensions |
| --- | --- |
| A | data firewall & chronology (4.1); walk-forward protocol (4.2); strategy causality (4.3) |
| B | accounting & costs (4.4); bootstrap/statistics v1+v2 & the `interval_contains_zero` predicate (4.5); strict models & JSON (4.6) |
| C | registry & immutable archives (4.7); publication & recovery (4.8); replay & fresh clones (4.9); CI & supply chain (4.10); documentation truthfulness (4.11) |

## 5. Defect classification (Phase 5)

- **A** documentation-only → correct forward + truthfulness test.
- **B** immutable-report prose, correct data → append-only erratum; never
  overwrite.
- **C** governance/test/recovery/CI, cannot affect run-003 financials → fix
  forward with failing test; note financials unchanged.
- **D** results-affecting (calculation, data access, accounting, causality,
  statistics beyond the known report wording) → **HARD STOP**: preserve the
  failing reproduction, do not alter run-003, do not run run-004, do not touch
  sealed data, leave PR draft, report and await authorization.

## 6. Documentation & terminal audit v2 (Phase 6)

Update forward: `research/m3a/README.md`, root `README.md`, `M3A_BUG_LOG.md`, a
clearly named merge-readiness terminal audit, bootstrap method note, closure
banners, errata docs, reproduction commands. The audit distinguishes
**audited implementation/artifact checkpoint** vs **code/test-correction
checkpoint** vs **docs/PR-only closure commit** vs **actual remote branch head
reported externally after push** — and never claims a Markdown file contains its
own commit SHA.

## 7. PR #4 body rewrite (Phase 7)

Required, after the branch is pushed and CI is green. Keep PR #4 open, draft,
base `main`, same branch, not merged, not ready. Body describes the true
terminal state: three experiments (run-001/002 historical v1, run-003 corrective
v2); the exact honest bootstrap conclusion (SMA & Donchian primary straddle
zero; cash primary excludes zero on the negative side; hierarchical straddles
zero for all; no alpha, no candidate); the preserved false report summary plus
the controlling erratum; the standing authoritative-CI E2E; both ledgers
byte-empty; no gate/holdout evaluation; the non-goals; current counts + CI links;
and the honest limitations (five folds, in-sample research-train diagnostics,
single venue/instrument/daily, operational not cryptographic sealing, unsigned
commits, release-tag debt). Stale "no statistical defects" and
"every interval straddles zero" claims are removed; the seam-crossing v1
bootstrap issue and the report erratum are disclosed. Re-fetch and verify.

## 8. Expected commit sequence (append-only; Phase 8)

1. this plan; 2. K1–K4 reproductions (failing-first where practical);
3. strict erratum model + append-only registry; 4. erratum verification
integration (archive/registry-verifier/`--check`/CI/hygiene); 5. standing E2E
lifecycle + failure rehearsals + CI skip-guard; 6. one commit per genuine
red-team fix; 7. CI/hygiene integration; 8. documentation + terminal audit v2;
9. PR body update (external metadata; no code commit). No amend/squash/rebase/
force-push; confirm local == remote after each push.

## 9. Test discipline

Focused test files during development; the **full suite at ≤ 2 checkpoints**
(after all code/test changes, and again at final HEAD if later non-doc changes
occur). If a single test command exceeds 15 min, stop and diagnose the exact
test. No blocking sleeps > 60 s. Every real defect follows reproduction →
failing regression → root cause → minimal fix → focused green.

## Hard stops

Any sealed-ledger byte change; any gate/holdout row reaching computation; any
change to the six-line prefix or any immutable experiment artifact; run-003
financial equivalence failure; an accounting/causal defect in committed results;
a bootstrap calculation defect beyond the known report wording; any fix needing
a run-003 rerun or run-004; an accidental `started` event in the real repo;
recovery needing calculation; PR becoming non-draft/merged; any tag created; CI
green only achievable by changing scientific output. A hard stop is never hidden
behind a documentation fix.

## Non-goals (explicit)

No development-gate evaluation; no final-holdout evaluation; no signals on either
sealed partition; no ledger append; no run-003 rerun/reuse; no run-004; no
mutation of any run-00x artifact; no in-place immutable correction; no new
experiment for prose; no strategy/cost/fold/seed/convention change; no
optimization/grid/ML/forbidden-price inspection; no live/paper trading, auth,
wallet, signing, leverage, shorting, or fractional exposure; no amend/squash/
rebase/force-push/prefix-rewrite/id-reuse; **no merge; no undraft; no v0.4.0 or
any tag; no branch delete; no M3B.** PR #4 stays open and draft for independent
human acceptance.
