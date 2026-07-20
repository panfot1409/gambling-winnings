# V2B Post-Run Red Team — five independent auditors of the executed one-shot

This document records the §32 post-run red team of Milestone V2B's single governed cross-asset one-shot
(`v2b_run_001`, published at commit `00e75b7`). Five independent, strictly read-only auditors reviewed the
committed post-run state from distinct adversarial lenses. Each was instructed to try hard to falsify the
run and to classify any finding as Class D (catastrophic — firewall/sealed/one-shot breach), Class A
(invalidating — a bug making the NULL untrustworthy), Class B (material, non-invalidating), or Class C
(minor/cosmetic).

**Result: no Class A, no Class D, and no Class B *defect* across all five lenses.** The committed NULL is
trustworthy, reproducible bit-for-bit, firewall-clean, consumed exactly once, in-scope, and honest. Every
surviving item is Class C (cosmetic, correct-by-construction, parity-with-accepted-V2A, or pre-existing
frozen infrastructure). Because the pre-registration, protocol identity, and published results are
immutable and the evaluation source is frozen at the P commit, the Class C items are **documented, not
applied retroactively**.

## Method

- **Read-only.** No auditor ran the experiment drivers (`experiment --register/--execute`,
  `orchestrator.run_one_shot`, `governance.append_event`, `publication.publish_results`) against the real
  repo, mutated any file, ran any git write, or fetched market data. `pytest` (hermetic, tmp-dir /
  monkeypatched), the read-only verifiers (`v2b.replay --check`, `v2b.governance`), and read-only git were
  the only tools. Each auditor confirmed `git status --porcelain` empty and HEAD unchanged at `00e75b7`
  afterward.
- **Independent reproduction.** Auditors recomputed fingerprints from raw bytes (including a stdlib-only
  recompute with no `eth_research` import), re-derived every gate boolean, brute-forced the Monte-Carlo
  estimator, and scanned the raw candle bytes directly rather than trusting the parser.

## Per-auditor verdicts

| Lens | Verdict | Class A | Class D | Class B | Class C |
|---|---|:---:|:---:|:---:|:---:|
| A — firewall & data integrity | no D, no A | 0 | 0 | 0 | 1 (A-C1) |
| B — statistical & decision integrity | no D, no A | 0 | 0 | 0 | 2 |
| C — governance / registry / one-shot | CLEAN | 0 | 0 | 0 | 4 |
| D — publication / results / reproducibility | CLEAN | 0 | 0 | 0 | 3 |
| E — scope / commercial honesty / firewall | CLEAN | 0 | 0 | 0 | 2 |

### A — firewall & data integrity (no Class A, no Class D)

Independently re-derived the joint partition from committed bytes: 2221 rows, first `2016-05-23T00:00:00Z`,
last open `2022-06-21T00:00:00Z` == cutoff, strictly increasing unique 1-day steps; greatest
engine-visible timestamp = last close = open+23h = `2022-06-21T23:00:00Z`, strictly `<` seal
`2022-06-22T00:00:00Z`. Scanned the **raw BTC candle bytes** directly for both acquisitions
(genesis + audit): max epoch `1655769600` = `2022-06-21T00:00:00Z`, **0** rows at/after cutoff, 0
pre-window; genesis↔audit canonical equality holds with distinct `workflow_run_id` and `source_commit`
(independent). Verified the 1-bar causal execution shift (`executed[t] == raw[t-1]`, `executed[0] == 0`);
an interior-causality probe and an extreme final-bar metamorphic perturbation left the executed path
byte-identical — the last signal can never reach an executed weight. Confirmed both candidates traded
actively (Cand A: 1068 ETH / 1003 cash days; Cand B: 834 ETH / 605 BTC / 632 cash), so the NULL is not a
silent data flattening. Sealed ledgers all byte-empty.

### B — statistical & decision integrity (no Class A, no Class D)

Recomputed every gate boolean from the committed CI bounds and p-values — all match for both candidates.
Directly exercised `mc_sign_flip_p_value`: row 0 of the sign matrix is all `+1`, so the observed statistic
is produced by the **same** `.sum(axis=1)/count` reduction as every permuted row (the §26 ULP-dropout
regression is genuinely closed); blocks are summed per-fold then concatenated (never crossing a fold seam);
`block_length = floor(n**(1/3))` matches the accepted M3C bootstrap. Brute-forced the exact permutation
distribution (2^18 configurations) against the estimator: agreement to sampling noise
(`null 0.601/0.602`, `weak-pos 0.00077/0.00075`), confirming the block-level sign-flip is the conservative,
autocorrelation-respecting choice and cannot manufacture a false pass; the resolution floor
`1/20001 ≈ 5e-5 < 0.005` keeps the gate crossable. Confirmed the corrected bootstrap reconciles bit-for-bit
with the primary endpoint and `corrected_alpha = 0.05/10 = 0.005` (8 historical candidate families + 2 V2B;
benchmarks correctly excluded). Crucially: the NULL does **not** depend on the MC or the correction — both
candidates fail the primary uncorrected 95% gate and even the most lenient uncorrected one-sided 5% test;
the paired point estimates are positive, the opposite of a suppressed edge; no cost double-count and no
fold misalignment (an alignment mismatch raises rather than silently mispairs).

### C — governance / registry / one-shot integrity (CLEAN)

With a stdlib-only script (no library import) recomputed: the protocol fingerprint `2bdf606e…` from the
four artifact SHAs + fold/nomination constants (`v2b_research_protocol.json` reproduces byte-for-byte); all
three chain `entry_hash`es; and the results fingerprint `d0b668f4…` = manifest fingerprint = manifest
sha256 = `completed` payload. The chain is a sound append-only SHA-256 hash chain
(`registered → started → completed`, `prev_entry_hash` links verified, `seq` = index). Tamper-injection on
scratch copies: a single-char payload edit without rehash → REJECTED; a 2nd `started` → REJECTED
("exceed the one-shot budget of 1"); `started` without `registered` → REJECTED; a 2nd `registered` →
REJECTED. Grep-confirmed **no** `reset()`/`--force`/`repair`/`rollback` exists in `v2b`/`v2.registry`/
`v2.budget`; `register()` refuses on a non-empty registry and `execute()` refuses a second `started`.
Two acknowledged-by-design trust boundaries (L1, L2 below) are documented in-code and non-invalidating.

### D — publication / results / reproducibility (CLEAN)

Independently recomputed `sha256(v2b_results.json) = d0b668f4…` and confirmed it equals the canonical
fingerprint, both manifest hashes, and the registry `completed` fingerprint (six cross-checks true). The
file is byte-canonical (idempotent under `strict_json_loads → canonical_json_bytes`, no wall-clock; keys
exactly the 5-key results schema). Independently re-derived `all(gates)` → `eligible = false` for both
candidates, matching the recorded gates; confirmed `decide_nomination` returns `null` for an empty eligible
set and that no path could mark an all-gates-true candidate ineligible here. Tamper of the published file is
detected (sha/fingerprint mismatch), and `publish_results` re-runs `verify_publication` and converts any
publish failure into a `failed` terminal, so a committed `completed` bundle is guaranteed consistent. No
over-claiming: the bundle is exactly two files with fixed key sets; no deployment/release/PyPI content.

### E — scope / commercial honesty / firewall (CLEAN)

Observed the three sealed access ledgers each 0 bytes / empty-string sha256 `e3b0c442…`, and `git log`
over `base..HEAD` touching them is empty (V2B never wrote them). The `base...HEAD` diff is 108 files,
+10947/−41, all in-scope: no `LICENSE`/`COPYING`, no new tag, no `main` change, no `research/v2a/**` and no
M-series artifact change. The three forbidden-token hits in `src/eth_research/v2b/` are benign prohibition
constants / economics prose (`no_credentials`, `no_leverage_or_shorting`, "300-candle limit", "marginal
cost"); no inert-but-present trading/order/wallet/signing capability exists. Both raw BTC acquisitions are
2221 rows spanning `2016-05-23 → 2022-06-21`, max open < seal, zero epochs ≥ seal. Governance: exactly one
run, one `started`, budget `max_research_executions:1, allow_repair_or_reset:false, consume_on_start:true`.
`buyer_evidence.json`: `posture: not_sell_ready, sell_ready: false`.

## The firewall Class-C item (A-C1) — full disposition

**Finding.** The frozen upstream loader `verify_dataset_integrity_only` (M2/M3A infrastructure, reached via
`v2/partitions.py` → `v2b/partition.py`) reconstructs and content-hashes the **whole** committed ETH
dataset — 3702 rows = 2221 research-train + 740 development-gate + 741 final-holdout — to recompute its
content fingerprint and re-derive the M3A split. The 740 + 741 development-gate/final-holdout rows are
sealed post-cutoff ETH observations, so their bytes *are* parsed and hashed during integrity verification.

**Why it is Class C, not Class D.** Independently reproduced: the loader returns **exactly 2221**
research-train rows (last open == cutoff, all opens ≤ cutoff), and `guard_research_train_frame` *rejects*
(does not truncate) any returned frame whose latest open exceeds the cutoff. Therefore:

1. **No leakage into the result.** The sealed rows influence only a SHA-256 tamper-detection digest and the
   partition-boundary derivation; **no sealed row's market value reaches any candidate, benchmark, context
   frame, engine, cost model, bootstrap, Monte-Carlo routine, renderer, or decision** — the operative
   Class-D condition. The result reproduces bit-for-bit from only the 2221 research-train rows.
2. **Pre-existing, accepted, and out of scope to change.** This reconstruct-and-verify design predates V2B
   and was used identically by accepted-V2A (whose null V2B builds on and which four auditors re-accepted).
   Modifying frozen accepted M2/M3A infrastructure is explicitly out of V2B scope.
3. **Enforcement intact.** The sealed *access* ledgers — the governed record of a gate/holdout/prospective
   evaluation — remain byte-empty; an integrity content-hash is not a governed evaluation access. BTC has
   no analogous exposure: its window is hard-capped at acquisition and contains zero sealed rows.

The honest disposition is to record this tension transparently (here and in `docs/V2B_FINDINGS.md` §3)
rather than to "fix" it by touching frozen accepted code. A future clean-room loader could hash the
research-train slice alone; that is separately-governed future work, not a V2B action.

## Acknowledged trust boundaries (by design — NOT defects)

- **L1 — unkeyed SHA-256.** A *wholesale* re-chain (editing the terminal payload **and** recomputing its
  `entry_hash`) is accepted by the chain-only reader — explicitly documented in `v2/registry.py`. It does
  not affect this run: git history is the anchor, and `replay._check_published_run` independently rebinds
  `completed.results_fingerprint` → published results → protocol, so a payload-only re-forge is caught
  unless the attacker also rewrites `v2b_results.json` + manifest consistently, i.e. a full repo rewrite
  detectable via git/branch protection.
- **L2 — out-of-band delete + rerun.** "Delete the registry + results and start over" is not blocked by a
  runtime code path (no file-based ledger can be), but it is not *eased* by one either: no
  reset/force/repair/rollback exists, and re-running requires destroying committed evidence out-of-band
  (`rm` + force-push), which git history and `allow_repair_or_reset:false` record and refuse. Not
  invalidating for this run.

## Class C register (all documented, none applied retroactively)

| ID | Auditor | Item | Disposition |
|---|---|---|---|
| A-C1 | A | Upstream ETH integrity-hash parses sealed *bytes* (not values) | Document; frozen accepted infra, no value leakage (see above) |
| B-C1 | B | Stressed/latency CI bounds not serialized (booleans only) | Document; determined by reproduction, monotone-consistent; results frozen |
| B-C2 | B | `decide_nomination` tie uses exact-float `==` | Document; conservative (tie→none), not exercised (0 eligible) |
| C-C1 | C | Registry timestamp validated as non-empty str, not strict UTC | Document; parity with accepted V2A reader; this run's stamps well-formed |
| C-C2 | C | `_from_line(line, seq)` parameter-name shadow | Document; no behavioral effect (`read_events` re-checks `seq`) |
| C-C3 | C | `started`/`completed` share one timestamp | Document; one `--timestamp` to both; no monotonicity invariant claimed |
| C-C4 | C | Redundant sealed-ledger emptiness check | Document; harmless belt-and-suspenders |
| D-C1 | D | Publication docstring says "atomic" for a staged-swap+verify mechanism | Document; mechanism is durable + self-verifying + fail-closed |
| D-C2 | D | `manifest.results_sha256 == results_fingerprint` | No action; correct-by-construction (canonical bytes); both checks kept |
| E-C1 | E | Descriptive in-sample Sharpe in bundle without inline caveat | Document; results frozen; all gates false, verdict frames it correctly |
| E-C2 | E | Pre-existing inert release machinery in tree | Document; not introduced/activated by V2B; out of scope |

## Fresh-clone reproduction (§33)

A clean `git clone` of the branch at `00e75b7` into an isolated directory reproduces the run end-to-end
against the fresh-clone source (`PYTHONPATH` = fresh `src`, repo-root = fresh clone):

- `python -m eth_research.v2b.replay --check` → **"V2B replay OK"** (exit 0).
- `python -m eth_research.v2b.governance --repo-root .` → **`{"ok": true, "problems": []}`**.
- Registry chain: `registered → started → completed`, exactly one of each, every `entry_hash` recomputes,
  `prev_entry_hash` links verified, `verify_registry_bound` clean.
- Fingerprint chain: results doc canonical fingerprint == manifest fingerprint == manifest sha256 == raw
  byte sha256 == registry `completed` payload == **`d0b668f4…`**.
- Decision: `nominated_candidate_id = None`, `eligible_candidate_ids = []`, verdict = the NULL string.
- `verify_publication` → `[]`; the three sealed ledgers each 0 bytes / `e3b0c442…`.
- Full fresh-clone V2B test suite: **164 passed**.

The authoritative fresh-clone reproduction is the read-only `v2b-replay.yml` workflow, which is **green**
on both the R (`21cdd11`) and P (`00e75b7`) tips under the pinned CPython 3.12.3; the main CI additionally
runs the suite on 3.12 and 3.13.
