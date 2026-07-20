# V2A–V2B Stack — Independent Acceptance Audit

**Program:** independent, read-only, result-neutral acceptance of the stacked V2A→V2B
research results, proving two valid governed **null** results (zero nominated candidates) are
correct and merge-ready, and establishing the permanent legacy-research moratorium.

**Verdict (see §Terminal):** `V2A–V2B STACK ACCEPTED FOR HUMAN MERGE REVIEW — TWO VALID
GOVERNED NULL RESULTS; ZERO NOMINATED CANDIDATES; LEGACY RESEARCH PARTITIONS CLOSED; ALL
SEALED PARTITIONS UNTOUCHED; V2 NOT SELL-READY`.

**Nature of this document:** an append-only acceptance record. It changes no accepted result.
It reflects the acceptance tooling under `src/eth_research/v2ab/` and the generated evidence
under `research/v2/` + `research/v2ab/`, all of which are verifier-side (deliberately excluded
from the frozen artifact table).

## Accepted anchors

| Anchor | Value |
|---|---|
| Accepted `main` base | `30e119933feb3d30cf3a890b177ea24b14ffc0da` |
| Accepted V2A terminal HEAD | `d437dafd67047470eae2c88fb14f0d8db6bf7091` |
| Accepted V2B terminal HEAD | `5798610389af0905331fc5da20f54f4b8f7930fb` |
| Empty sealed-ledger SHA-256 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| Accepted BTC dataset fingerprint | `6896e6146d747d3b24295e07371eb8a1b8db4f7d8dbe991f2a797a720c1a39ce` |

## Method

Twelve chained offline verifiers (`eth_research.v2ab.acceptance --check --deep`) re-derive every
acceptance claim from committed bytes; two independent result-reconstruction oracles rebuild the
V2A and V2B nulls without importing any audited decision; five independent acceptance auditors
(V2A null, V2B null, BTC acquisition + provenance, governance/security/operations/buyer +
moratorium/commercial-truth, merge mechanics + historical neutrality) reproduced every finding
on throwaway copies without mutating the real repository. A disposable merge simulation checked
tree and patch identity. No candidate was evaluated, no sealed partition read, no network call
made, no artifact mutated.

---

## 1. Identity, ancestry, and change discipline

1. The accepted `main` base is `30e119933feb3d30cf3a890b177ea24b14ffc0da`. ✓
2. The accepted V2A terminal HEAD is `d437dafd67047470eae2c88fb14f0d8db6bf7091`. ✓
3. The accepted V2B terminal HEAD is `5798610389af0905331fc5da20f54f4b8f7930fb`. ✓
4. The V2B branch is a linear, single-parent descendant chain over the V2A terminal (no rebase,
   squash, reset, or history rewrite). ✓
5. All acceptance commits are append-only descendants of the accepted V2B terminal HEAD. ✓
6. No accepted financial or scientific artifact is modified by the acceptance work. ✓
7. The V2A branch is not modified by the acceptance work. ✓
8. Post-run corrections use only new verifiers, generated summaries, append-only annotations,
   hash-bound errata, or forward docstring fixes to verifier source — never in-place edits of an
   immutable result. ✓
9. Package version remains `2.0.0.dev1`; no version bump was used to claim freshness. ✓
10. The acceptance tooling lives in an isolated package `eth_research.v2ab`, importing no audited
    decision or nomination module. ✓

## 2. Immutable freeze table (drift detection)

11. `research/v2ab/stack_freeze_table.json` enumerates 191 committed accepted-stack artifacts
    with per-file byte hash, length, mode, role, and milestone. ✓
12. `verify_freeze_table` re-derives every hash from the working tree and the domain-separated
    aggregate digest binds. ✓
13. The table detects missing, unlisted, symlinked, path-traversing, duplicated, byte-changed,
    role-changed, and milestone-changed entries (adversarially exercised). ✓
14. The freeze table deliberately excludes the verifier side (`research/v2ab/`, `research/v2/`):
    those carry their own drift checks, not the frozen table. ✓
15. Sealed ledgers listed in the table are asserted byte-empty by classification. ✓
16. The older M3C–M3E aid table (`docs/M3C_M3E_STACK_FREEZE_TABLE.json`) still binds every hash
    it lists; its coverage test now excludes the strictly-later `research/v2/` + `research/v2ab/`
    acceptance layer on the same basis as `research/v2a/` + `research/v2b/`. ✓
17. Every frozen artifact still matches its recorded hash and byte length. ✓

## 3. V2A scientific null (Auditor 1 lens — CLEAN)

18. The V2A run tested exactly three pre-registered ETH candidate families. ✓
19. Zero ETH families were nominated (all `research_stage_rejected`). ✓
20. The independent V2A oracle reconstructs the accepted null from committed evidence without
    importing the audited decision. ✓
21. The pre-registration binding (git HEAD + committed bytes) is intact and reproduces. ✓
22. The V2A results fingerprint matches the accepted anchor. ✓
23. The nomination gates fail as recorded for each family (fold win-rate, CI, cost survival,
    robustness). ✓
24. No family's failed criterion is reinterpreted as a pass. ✓
25. No rejected family is relabelled as untested. ✓
26. The walk-forward protocol pins rows = 2221 and folds = 5; structure is reconstructible. ✓
27. Auditor 1 verdict: no Class A (integrity) and no Class D (governance/sealed) defect. ✓
28. The single Class C item (display rounding at `docs/V2A_FINDINGS.md:40`) is cosmetic and
    non-pivotal; recorded in the erratum, not corrected in place. ✓
29. Observational items (transitive WF binding, aggregate-Sharpe fold seam, cosmetic assert,
    unused `walk_forward_protocol_v2.json`) are non-invalidating and recorded. ✓

## 4. V2B scientific null under multiplicity (Auditor 2 lens — CLEAN)

30. The V2B run tested exactly two pre-registered cross-asset candidate families. ✓
31. Zero cross-asset families were nominated. ✓
32. The independent V2B oracle reconstructs the accepted null from committed evidence. ✓
33. The cumulative multiplicity / alpha-spending correction is applied across the full program
    family count, not just V2B in isolation. ✓
34. The V2B result fingerprint matches the accepted anchor. ✓
35. The V2B protocol fingerprint matches the accepted anchor. ✓
36. The BTC information source is genuinely new (not a re-label of ETH-only evidence). ✓
37. The null is over-determined: it holds under the pre-registered rule and under independent
    reconstruction. ✓
38. Neither candidate crosses the nomination threshold under the cumulative correction. ✓
39. Auditor 2 verdict: no Class A, B, C, or D defect. ✓
40. The cumulative family count is not reduced and no rejected family is relabelled. ✓

## 5. BTC acquisition + raw-to-result provenance (Auditor 3 lens — CLEAN)

41. Both BTC acquisitions parse to exactly 2221 canonical daily rows. ✓
42. The series spans `2016-05-23 .. 2022-06-21` with strict 86400-second daily steps. ✓
43. Zero candle lands at or after the research-cutoff seal `2022-06-22T00:00:00Z`. ✓
44. No missing or duplicate daily open; no forming candle. ✓
45. The genesis and audit acquisitions have distinct `workflow_run_id` and distinct
    `source_commit` (genuinely independent). ✓
46. The two acquisitions reproduce byte/fingerprint-identical canonical candles. ✓
47. The shared canonical fingerprint equals the committed `btc_dataset_fingerprint` in
    `joint_partition_identity.json`. ✓
48. It also equals the hard-coded accepted anchor (a fully self-consistent raw replacement is
    still caught). ✓
49. Every committed receipt's response counts, byte lengths, and SHA-256 values are
    self-consistent with the raw candle files present. ✓
50. The deep provenance graph re-derives raw→result and binds. ✓
51. The one-shot acquisition workflow is retired: no committed workflow contacts the Coinbase
    endpoint. ✓
52. No committed workflow grants `contents: write`, an id-token write, `packages: write`, or
    `write-all`. ✓
53. The single-use acquisition sentinel is consumed (absent). ✓
54. The governance amendment honestly distinguishes final-tree state from historical state (it
    does not claim the workflow never existed). ✓
55. Auditor 3 verdict: no Class A, B, or D defect. ✓
56. Two Class C items (`docs/V2B_ACQUISITION.md` un-filled run-evidence template at 113-125;
    stale test reference at 54) are cosmetic; recorded in the erratum, not corrected in place. ✓
57. The authoritative run evidence lives in the receipts / dataset lock / joint identity /
    acquisition audit, all reproduced green. ✓

## 6. Cumulative family catalog

58. `research/v2b/research_family_catalog.json` enumerates 10 pre-registered candidate families
    across the program. ✓
59. The three V2A ETH families and two V2B cross-asset families are among them. ✓
60. Every family's terminal status is recorded; none is nominated. ✓
61. The catalog is bound by SHA-256 into the moratorium closure. ✓
62. `verify_family_catalog` passes. ✓

## 7. Hash-chained negative-evidence index

63. `research/v2/negative_evidence_index.jsonl` is a 13-line hash-chained index. ✓
64. Every record marks `sealed_data_touched=false`. ✓
65. The hash chain verifies (each record binds the previous). ✓
66. The synthesis doc `docs/V2_NEGATIVE_EVIDENCE_SYNTHESIS.md` reflects the index without
    overclaiming. ✓
67. `verify_negative_evidence` passes. ✓
68. The index makes no out-of-sample claim about historical-partition results. ✓

## 8. Research-debt register

69. `research/v2/research_debt_state.json` records the program's research debt as
    `closed_to_further_research` on the legacy partitions. ✓
70. `verify_research_debt` passes. ✓
71. The register does not reduce or relabel any prior family count. ✓

## 9. Legacy-research moratorium (unbypassable)

72. `research/v2/research_partition_closure.json` declares status
    `closed_to_new_candidate_nomination_research`. ✓
73. The closure post-dates the accepted V2B terminal state and never claims to pre-exist it. ✓
74. The closure self-digest binds its body; a tampered body is rejected. ✓
75. `load_closure` re-binds live artifact SHAs (family catalog, multiplicity, negative evidence,
    aligned partition), catching same-fingerprint/other-path or drifted sources. ✓
76. An "open" status is unrepresentable (`require_choice` restricts to the closed status). ✓
77. Every one of the 11 forbidden operations is refused with **no** token. ✓
78. Forbidden operations are refused even with a validly-minted replay token. ✓
79. Forbidden operations are refused even with a **sentinel-forged** token. ✓
80. Replay authorization is refused for a new/changed experiment id
    (e.g. `v2c_new_candidate`). ✓
81. Replay authorization is refused for a copied/altered partition fingerprint. ✓
82. Replay authorization is refused for a new package version. ✓
83. Direct `HistoricalReplayAuthorization` construction raises without the sentinel. ✓
84. A valid replay of a committed historical experiment for an ALLOWED op succeeds. ✓
85. A token bound to a different experiment is refused at `guard_operation`. ✓
86. No code path evaluates a new candidate on the closed partition. ✓
87. The `_REPLAY_SENTINEL` overclaim (Auditor 4 Class C) is corrected forward in the docstrings;
    the sentinel is a pragmatic in-process guard, and forbidden ops are refused independent of
    any token. Not a bypass. ✓
88. `verify_closure` passes; historical experiments = `("v2a_run_001","v2b_run_001")`; accepted
    package version = `2.0.0.dev1`. ✓

## 10. Commercial truth — `sell_ready` is unforceable

89. `research/v2/commercial_truth.json` records the honest commercial posture. ✓
90. `sell_ready` is a pure derivation: `nominated_count >= 1` AND all readiness gates. ✓
91. `pure_sell_ready(all-gates-true, nominated=0)` returns False (verified). ✓
92. The real derivation yields `sell_ready = false` with zero nominations and 15 readiness gates
    false. ✓
93. A stale-digest forge of `sell_ready=true` is caught by the self-digest. ✓
94. A self-consistent-digest forge of `sell_ready=true` is still caught by the evidence-recompute
    and the fresh-rebuild catch-all. ✓
95. A forged V2A nomination leaves `sell_ready` False (readiness gates still false) while the
    evidence drift is flagged. ✓
96. `verify_commercial_truth` passes. ✓
97. The readiness gates enumerate the concrete unmet requirements (development gate, final
    holdout, out-of-sample, forward shadow, realistic costs, capacity, deployment controls,
    unattended operation, uncontrolled-exposure prevention, single-parameter independence, legal
    terms, IP clearance, license, buyer-deploy/evaluate without source/repository). ✓
98. `docs/V2_PROSPECTIVE_NEXT_PHASE_PLAN.md` describes what would be required next without
    asserting readiness. ✓

## 11. Sales-material scan

99. `scan_repo_sales_material` finds no committed material claiming a nominated candidate or a
    live/deployable/sell-ready strategy. ✓
100. No document asserts an out-of-sample or holdout result was completed. ✓
101. No document presents a rejected family as tradeable. ✓
102. The scan is clean across the repository. ✓

## 12. Sealed partitions

103. `research/m3a/development_gate_access.jsonl` is byte-empty (SHA-256 = empty anchor). ✓
104. `research/m2b/test_evaluations.jsonl` is byte-empty. ✓
105. `research/m3d/prospective_evaluations.jsonl` is byte-empty. ✓
106. No acceptance operation reads, writes, or opens any sealed ledger. ✓
107. The dev gate, final holdout, and prospective (M3D) values are never inspected. ✓
108. M3E prospective machinery stays accepted-but-inactive; no proposal is appended. ✓

## 13. Workflow security / publication / acquisition retirement

109. All committed workflows use `contents: read` (no `contents: write`). ✓
110. Zero workflow declares an id-token write permission. ✓
111. Zero workflow references `secrets.`. ✓
112. Every `uses:` is SHA-pinned (40-hex) or local. ✓
113. The only external host contacted by CI is `astral.sh` (uv); no exchange host. ✓
114. The public-publication kill switch finds no upload/publish vector across
     workflows/scripts/src/tools. ✓
115. The acquisition-audit module's defensive detector no longer trips the kill switch (the
     incidental docstring literal was removed without weakening the scanner). ✓
116. No workflow references the V2B acquisition runner or re-arms the acquire sentinel. ✓
117. The private-distribution posture is unchanged and closed (no public channel). ✓
118. The `Private :: Do Not Upload` guard and no-OSI-license posture are intact. ✓

## 14. Merge mechanics + historical neutrality (Auditor 5 lens — CLEAN)

119. The disposable merge simulation produces a clean `ort` merge with no conflicts. ✓
120. The merged tree matches the expected tree (tree identity). ✓
121. Patch identity holds under the retarget simulation (empty diff). ✓
122. All V2A→V2B ancestry is preserved and linear. ✓
123. No `refs/sim/*` simulation ref leaked into the live repository. ✓
124. The disposable clone was cleaned up; the real repo was untouched (0 dirty). ✓
125. Auditor 5 verdict: Class A / B / C / D all NONE. ✓
126. The `src/eth_research/v2/*` modifications are verifier-side and do not alter the accepted
     result tree. ✓
127. The three sealed ledgers stay byte-empty across the merge simulation. ✓
128. No merge simulation differs from the accepted branch tree. ✓

## 15. Operational (shadow) platform — signal-only

129. `tests/test_shadow_platform.py` passes. ✓
130. The only execution adapter is `PaperExecutionAdapter` (`NON_ROUTING_CHANNELS={"paper"}`);
     any other channel is rejected. ✓
131. The kill switch latches tripped until an explicit `reset(reason=)`. ✓
132. The journal is hash-chained (seq / prev_hash / entry_hash verified). ✓
133. Recovery is idempotent and fails closed unless the journal head hash matches. ✓
134. The runner gates all exposure behind the kill switch and uses an as-of clock (no
     wall-clock). ✓
135. `research/v2b/multi_asset_shadow.json` is `signal_only:true` with prohibitions
     (no network / no orders / no credentials / no money movement / no leverage or shorting). ✓
136. There is no live or forward data path. ✓

## 16. Buyer-evaluation boundary — source-free, not sell-ready

137. `tests/test_buyer_boundary.py` passes. ✓
138. `buyer/redaction.py` rejects secrets, embedded source, and raw-sealed data, and scans
     decoded JSON string values (anti-smuggling), fail-closed. ✓
139. `assemble_diligence_bundle` refuses on any violation and is source-free by construction. ✓
140. `buyer/contract.py` withholds source, all sealed partitions, credentials, live/paper
     access, and raw price data. ✓
141. The buyer posture is `not_sell_ready`. ✓
142. No buyer artifact exposes a nominated candidate (there is none). ✓

## 17. CI, replay, and reproducibility

143. The whole-stack verifier `eth_research.v2ab.acceptance --check --deep` returns
     `{"ok": true, "problems": []}`. ✓
144. The full local pytest suite runs under the exact CI config (bare pytest, `testpaths=tests`,
     `-q --strict-markers`, `filterwarnings=error`). ✓
145. `ruff check .` passes. ✓
146. `ruff format --check .` passes. ✓
147. `mypy src tests examples` reports no issues (549 source files). ✓
148. `uv lock --check` confirms the lock matches `pyproject.toml`. ✓
149. `git diff --check` reports no whitespace/conflict damage. ✓
150. The read-only `v2ab-replay.yml` workflow re-runs the acceptance suite + deep verifier +
     byte-empty sealed-ledger check on a fresh clone (contents: read, SHA-pinned, CPython
     3.12.3). ✓
151. The acceptance verifiers are offline: no networking, no sealed partition, no wall clock. ✓
152. Every previously-red governance/security/release test is green after the result-neutral
     fixes: `test_public_publication_killswitch.py`, `test_stack_freeze_table.py`,
     `test_ga_release_artifacts.py`, and `test_private_release.py`. ✓

## 18. Class findings and dispositions

153. Across five independent auditors: **Class A — NONE**, **Class D — NONE**. ✓
154. Class B (CI-red, three result-neutral fixes): the public-publication kill-switch lexical
     collision on the acquisition-audit docstring; the M3C-M3E freeze-table coverage test
     exclusion; and the GA/private release-evidence governed-state exclusion
     (`tools/release_evidence.py`, shared by `tools/private_release.py`). All three are the same
     stale bookkeeping of the strictly-later verifier-side `research/v2/` + `research/v2ab/`
     layer. Excluding that layer, the governed-state digest reproduces the frozen merged-main
     (M3) baseline `b2077eaf…` exactly, proving no `research/` artifact changed — fixed forward,
     no immutable artifact touched. ✓
155. Class C (4 total: 1 V2A rounding, 2 V2B-acquisition doc staleness, 1 moratorium docstring):
     all non-invalidating; the three immutable-doc items recorded in the append-only erratum, the
     verifier-source item corrected forward. ✓
156. No Class A/B/C/D finding invalidates either governed null. ✓
157. No hard-stop condition is present (no sealed row reached a candidate/engine/metric/report;
     no sealed ledger changed; no V2A/V2B result or registry event changed; no dataset drift; no
     candidate re-executed or newly evaluated; no failed criterion reinterpreted; no cumulative
     family count reduced; no rejected family relabelled; no result presented as out-of-sample;
     no merge-sim divergence; no provenance forgery passed; no `sell_ready` truth; no public
     publication path). ✓

## 19. Terminal — what remains prohibited after acceptance

158. Both stacked PRs remain **open and draft**; none is merged, undrafted, or retargeted. ✓
159. No tag is created; `main` is not modified. ✓
160. No new market data is acquired; no acquisition workflow is activated. ✓
161. No dev gate / final holdout / M3D prospective value is accessed; M3E is not activated. ✓
162. No forward shadow strategy is run; no research-experiment event is appended. ✓
163. No V2C candidate code is created; no third candidate is evaluated. ✓
164. No new research budget, gate, or holdout is opened. ✓
165. No LICENSE is added; nothing is published publicly; no branch is deleted; no history is
     rewritten. ✓
166. `sell_ready` remains false; the V2 package is **not sell-ready**. ✓
167. Both nomination decisions remain unchanged: **no candidate nominated** in V2A or V2B. ✓

---

## Terminal verdict

**`V2A–V2B STACK ACCEPTED FOR HUMAN MERGE REVIEW — TWO VALID GOVERNED NULL RESULTS; ZERO
NOMINATED CANDIDATES; LEGACY RESEARCH PARTITIONS CLOSED; ALL SEALED PARTITIONS UNTOUCHED; V2 NOT
SELL-READY`**

The two stacked results are correct, independently reproducible, and merge-ready for human
review. There are no scientific (Class A) or sealed/governance (Class D) defects. The legacy
historical partitions are permanently closed to further candidate-nomination research, and the
moratorium is enforced unconditionally. Merge remains a human decision: both PRs stay open and
draft, and every post-acceptance action above remains prohibited.
