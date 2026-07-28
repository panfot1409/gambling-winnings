# V2C Terminal Audit

A read-only, item-by-item terminal audit of the Milestone V2C candidate-free offline operational
qualification (OQ). Every item is a verifiable assertion about the committed state of the branch
`claude/v2c-prospective-operations-qualification`. All items were verified PASS. Nothing in this
audit modifies the repository.

**Scope:** the committed OQ run `v2c_offline_operational_qualification_run_001`, its governance
sequence (OQ-E2 freeze → OQ-E2A activation → OQ-R/P/Q), the post-run test isolation, the
post-qualification red team, the terminal documentation, and CI.

**Authorized terminal verdict:**
> V2C COMPLETE — PROSPECTIVE-EVIDENCE AND OFFLINE-OPERATIONS QUALIFICATION READY, NOT ACTIVE;
> NO STRATEGY EVALUATED; ALL SEALED PARTITIONS UNTOUCHED; V2 NOT SELL-READY.

---

## A. Repository & branch state (1–12)

1. Branch under audit is `claude/v2c-prospective-operations-qualification`. PASS
2. Package version is `2.0.0.dev2` in `pyproject.toml`. PASS
3. Package version is `2.0.0.dev2` in `src/eth_research/__init__.py`. PASS
4. `V2C_DEV_VERSION = "2.0.0.dev2"` in the SBOM module matches. PASS
5. No version-drift test fails (`tests/test_version.py`, `tests/test_v2c_commercial.py`). PASS
6. The repository is private (`pyproject.toml` classifier `Private :: Do Not Upload`). PASS
   > **Erratum, 2026-07-28 (V2F-R).** This item conflated two different things and its PASS is
   > withdrawn. The classifier was present, but it is a PyPI upload guard and is not evidence of
   > GitHub repository visibility; the repository was public. What the item *did* verify —
   > the classifier is in `pyproject.toml` — remains true. See
   > `docs/V2_PUBLIC_EXPOSURE_INCIDENT.md`.
7. No public index publication artifact was created for this dev version. PASS
8. The working tree is clean at each committed checkpoint. PASS
9. The branch base (`merge-base` with `origin/main`) is `6e0d60e` (M2). PASS
10. All committer/author identities on new commits are `Claude <noreply@anthropic.com>`. PASS
11. Commit `2a9e528` (pre-freeze red-team hardening) is unchanged and an ancestor of HEAD. PASS
12. No new commit amended/rebased/rewrote `2a9e528`, `cea86a5`, `f30e284`, or `f4a7097`. PASS

## B. OQ-E2 source freeze (13–30)

13. `governance/v2c/oq_source_freeze.json` exists and is schema version 2. PASS
14. The frozen source surface is exactly 57 relpaths. PASS
15. Every frozen relpath under `src/` (55 of them) exists and hashes to the recorded digest. PASS
16. The two frozen evidence artifacts (`docs/V2C_PLAN.md`, the inactive probe template) are bound. PASS
17. `verify_oq_source_freeze(repo_root)` reproduces on the committed tree. PASS
18. `verify_oq_source_freeze` reproduces on an independent `git archive` export of HEAD. PASS
19. The freeze's `frozen_source_sha256` aggregate re-derives from the frozen bytes. PASS
20. The freeze's `frozen_artifact_sha256` aggregate re-derives from the evidence bytes. PASS
21. The freeze binds the runtime contract `research/m2b/runtime_contract.json`. PASS
22. The freeze binds the supersession record that retired the premature freeze. PASS
23. The freeze hardcodes a pristine-registry expectation (does not read the live registry). PASS
24. The freeze's `source_fingerprint_sha256` is a stable domain-separated digest. PASS
25. The OQ import closure (42 modules) is a subset of the frozen surface. PASS
26. The AST import-closure drift test passes (`tests/test_v2c_oq_freeze.py`). PASS
27. No frozen source file was modified after the freeze commit `cea86a5`. PASS
28. The run commit `530f182` touched no frozen-surface file. PASS
29. The freeze is unmodifiable post-freeze (the one-shot re-freeze is consumed). PASS
30. `tests/test_v2c_oq_freeze.py` (21 tests) is green. PASS

## C. OQ-E2A activation anchor (31–40)

31. `governance/v2c/oq_e2_activation.json` exists. PASS
32. It binds `source_freeze_commit = cea86a5fb93802fcb6d32977f8cdabef222bcf3d`. PASS
33. Its `source_freeze_artifact_sha256` equals the sha256 of the live freeze artifact. PASS
34. `verify_oq_e2_activation(repo_root)` reproduces on the committed tree. PASS
35. Re-derivation is non-circular for freeze content (rebuilds from live frozen bytes). PASS
36. The anchor was created in a follow-on commit (`f30e284`) binding `cea86a5`'s SHA. PASS
37. The anchor's statement discloses it records (not attests) the commit-to-freeze link. PASS
38. Git history independently confirms `cea86a5` authored the freeze artifact. PASS
39. The CLI replay verifies the anchor when present (`oq_e2_activation_anchor_reproduces`). PASS
40. The anchor is absent from a pristine tree before it is written (pristine posture). PASS

## D. Supersession ledger (41–50)

41. `governance/v2c/oq_source_freeze_supersession.jsonl` exists and is append-only. PASS
42. `verify_supersession` returns no problems on the committed ledger. PASS
43. The premature freeze `e4b3cc3` is present in `superseded_commits`. PASS
44. `assert_freeze_superseded` confirms `e4b3cc3` is recorded superseded. PASS
45. `assert_freeze_not_superseded` refuses `e4b3cc3` from authorizing a run. PASS
46. The supersession record attests `registry_byte_count == 0` at supersession time. PASS
47. The supersession record attests `registry_sha256 == EMPTY_SHA256`. PASS
48. The supersession record attests `registry_event_count == 0`. PASS
49. `e4b3cc3` remains superseded and incapable of authorizing registration/execution. PASS
50. `tests/test_v2c_oq_supersession.py` is green (incl. the record-pristine assertion). PASS

## E. Run identity binding (51–63)

51. The registered identity binds `qualification_id` = the protocol's qualification id. PASS
52. It binds `methodology_id` = the protocol's methodology id. PASS
53. `protocol_sha256` = committed byte hash of `oq_protocol.json`. PASS
54. `source_freeze_sha256` = committed byte hash of `oq_source_freeze.json`. PASS
55. `fixture_sha256` = committed byte hash of `oq_fixture_manifest.json`. PASS
56. `fault_schedule_sha256` = committed byte hash of `oq_fault_schedule.json`. PASS
57. `slo_contract_sha256` = committed byte hash of `oq_slo_contract.json`. PASS
58. `cash_control_identity` = committed byte hash of `oq_cash_control_identity.json`. PASS
59. `runtime_contract_sha256` = committed byte hash of the runtime contract. PASS
60. `package_version` in the identity = `2.0.0.dev2`. PASS
61. `source_freeze_id` = the OQ-E2 freeze id. PASS
62. No candidate reference appears in the identity (candidate screen passes). PASS
63. The 11 identity-bound artifacts are byte-identical between the real tree and the copy. PASS

## F. Registry & lifecycle (64–76)

64. `governance/v2c/oq_registry.jsonl` records exactly 3 events. PASS
65. The events are `registered → started → completed` in order. PASS
66. Each event's `entry_hash = canonical_sha256(body)`. PASS
67. Each event chains onto the prior event's `entry_hash`. PASS
68. The `completed` event carries verdict `qualified`. PASS
69. `registry_state` reports `completed`. PASS
70. The registered event exists before the started event (calc-before-start ordering). PASS
71. No `StartedToken` can exist before the durable `started` event. PASS
72. The registry is not a symlink. PASS
73. The registry was byte-empty before OQ-R (per the supersession attestation). PASS
74. The one-shot budget is consumed (no re-register possible over the archive). PASS
75. `tests/test_v2c_oq_orchestrator.py` is green (gate order + fail-closed gates). PASS
76. The fail-closed preflight refuses a superseded freeze, misbind, candidate ref, etc. PASS

## G. Immutable archive & terminal digests (77–90)

77. The archive dir holds exactly 3 artifacts. PASS
78. The artifacts are `oq_result.json`, `oq_report.md`, `oq_archive_manifest.json`. PASS
79. `result_sha256 = 739cec5d…945b897` (committed registry). PASS
80. `result_bundle_sha256 = e52308a0…9dcb525` (committed registry). PASS
81. Each artifact's bytes hash to the manifest's recorded digest. PASS
82. The manifest's recorded digests equal the registry terminal digests. PASS
83. The manifest verdict is `qualified`. PASS
84. Publication is write-once (immutable paths never overwritten). PASS
85. `evidence_sha256` re-derives. PASS
86. `manifest_digest` re-derives and binds the artifacts. PASS
87. `result_bundle` re-derives independently. PASS
88. `oq_report.md` re-renders byte-for-byte from the result. PASS
89. No pending completion intent exists (finalize consumed it). PASS
90. `tests/test_v2c_oq_archive.py` is green (archive + intent + finalizer). PASS

## H. Verification model (91–104)

91. `replay --repo-root .` returns exactly the 16-check completed-run certificate. PASS
92. Check `source_freeze_reproduces` present. PASS
93. Check `oq_e2_activation_anchor_reproduces` present. PASS
94. Check `protocol_bundle_reproduces` present. PASS
95. Check `premature_freeze_recorded_superseded` present. PASS
96. Check `sealed_ledgers_byte_empty` present. PASS
97. Check `registry_lifecycle_registered_started_completed` present. PASS
98. Check `terminal_hashes_match_published_bytes` present. PASS
99. Check `result_rescans_clean_and_zero_exposure` present. PASS
100. Check `oq_q_oracle_independently_accepts` present. PASS
101. `verify --repo-root .` returns the 10-check deep archive verifier set. PASS
102. The OQ-Q oracle independently derives the `qualified` verdict from run measurements. PASS
103. The oracle's floor check (`accepted_count >= 3500`) is satisfied (3757). PASS
104. `tests/test_v2c_oq_verify_archive.py` + `tests/test_v2c_oq_oracle.py` green. PASS

## I. From-source reproducibility (105–114)

105. Re-executing the frozen source at `slots = 3800` reproduces `result_sha256`. PASS
106. Re-executing the frozen source reproduces `result_bundle_sha256`. PASS
107. Two independent honest re-executions produce byte-identical digests. PASS
108. Virtual time uses the fixed `OQ_FIXTURE_COHORT_START` (no wall clock). PASS
109. No RNG without a fixed derivation reaches the result. PASS
110. Canonical JSON sorts keys (no dict-order leakage). PASS
111. Registry `event_time_utc` never enters the result body. PASS
112. The recovery workdir non-determinism never enters the result. PASS
113. `test_committed_digests_re_derive_from_the_frozen_source` passes on 3.12. PASS
114. A self-consistent result forgery fails the from-source re-derivation test. PASS

## J. No-strategy / candidate-free invariant (115–130)

115. The runner takes no candidate parameter. PASS
116. The harness hard-wires `target_weight = 0.0` on every step. PASS
117. `max_target_weight = 0.0` and `max_weight_step = 0.0` are pinned. PASS
118. The firewall admits only `cash_control_operation`. PASS
119. `resolve_operational_target` resolves only the `cash_control` target. PASS
120. The firewall refuses `market_data`, strategy kinds, candidate ids, callables, modules. PASS
121. The firewall normalizes inputs (strips zero-width) before matching. PASS
122. Requested exposure = 0.0 for every instrument. PASS
123. Approved exposure = 0.0 for every instrument. PASS
124. Turnover = 0.0 for every instrument. PASS
125. Risky fills = 0 for every instrument. PASS
126. Final book units = 0.0; final cash = starting cash. PASS
127. Prices are a deterministic synthetic triangular wave (`source = oq_synthetic`). PASS
128. No network / socket / HTTP / file-read of market data in the execution path. PASS
129. The committed result/report contain no forbidden-vocabulary term (scanner clean). PASS
130. The oracle + deep verifier re-derive the zero-exposure invariant independently. PASS

## K. Sealed partitions (131–138)

131. `research/m2b/test_evaluations.jsonl` is committed as a 0-byte blob. PASS
132. `research/m3a/development_gate_access.jsonl` is committed as a 0-byte blob. PASS
133. `research/m3d/prospective_evaluations.jsonl` is committed as a 0-byte blob. PASS
134. All three hash to the empty-sha256 `e3b0c442…`. PASS
135. The orchestrator gate asserts sealed ledgers byte-empty before a run. PASS
136. The replay CLI asserts sealed ledgers byte-empty (twice). PASS
137. The committed-run certification asserts the real sealed ledgers byte-empty. PASS
138. The run commit did not modify any sealed ledger. PASS

## L. Recovery model (139–147)

139. The completion-intent handshake binds the terminal digests before finalize. PASS
140. Finalize appends `completed` only when archive present + registry `registered→started`. PASS
141. Finalize is fail-closed on an incomplete archive (`not_finalizable`). PASS
142. Finalize is fail-closed on a mismatched started-chain (`not_finalizable`). PASS
143. Recovery never re-executes the runner or recomputes a digest. PASS
144. Recovery never resets the one-shot budget (archive trips the prior-run gate). PASS
145. The committed tree has no pending intent; `recover` reports `no_intent`. PASS
146. A crash-after-publish finalizes without recomputation (tested). PASS
147. `test_recover_is_a_noop_no_pending_intent` passes. PASS

## M. Test isolation (148–160)

148. `pristine_oq_repo` copies `src/` byte-for-byte. PASS
149. It copies `governance/` byte-for-byte (minus the removed qualifications dir). PASS
150. It copies `docs/` (the frozen `docs/V2C_PLAN.md` evidence). PASS
151. It copies the runtime contract. PASS
152. It empties the registry to byte-empty. PASS
153. It writes the three sealed ledgers byte-empty. PASS
154. It removes the published archive dir. PASS
155. The copy drives the full pre-publish lifecycle (register/start/execute). PASS
156. Every consumer treats the copy as read-only (no mutation of the shared session copy). PASS
157. The six run-producing fixtures use the isolated copy as `repo_root`. PASS
158. The four orchestrator lifecycle tests use the isolated copy. PASS
159. The four pristine CLI tests use the isolated copy. PASS
160. Coverage is strictly added, never reduced; real-tree verification retained. PASS

## N. Post-qualification red team (161–176)

161. Five independent read-only auditors examined the committed run. PASS
162. Auditor A: determinism/reproducibility/digest-integrity sound. PASS
163. Auditor A Finding 1 (no from-source re-derivation) fixed in `a7dee93`. PASS
164. Auditor A Finding 2 (orphaned-archive CLI asymmetry) — low, by-design, frozen CLI. PASS
165. Auditor B: test-isolation claim upheld; coverage added not reduced. PASS
166. Auditor B item 4 (digest read-back tautology) fixed by the from-source test. PASS
167. Auditor C: no strategy evaluated; sealed ledgers byte-empty (claim holds). PASS
168. Auditor C LOW (narration regex) — non-exploitable, frozen, document-only. PASS
169. Auditor D: frozen surface untouched; freeze/activation/supersession consistent. PASS
170. Auditor D confirmed `2a9e528` and the version untouched. PASS
171. Auditor E: CI green both legs; v2c-replay re-verifies State B; no drift. PASS
172. No Critical/High/Medium defect survived verification. PASS
173. No Class-A (scientific) defect was found. PASS
174. No Class-D (sealed-state / irreversible-governance) defect was found. PASS
175. All document-only findings recorded in `docs/V2C_FINDINGS.md`. PASS
176. The C-001 provenance defect + fix recorded in `docs/V2C_BUG_LOG.md`. PASS

## O. CI & workflow security (177–190)

177. The canonical run commit `530f182` is CI-green (CI + V2C Replay). PASS
178. The hardening commit `a7dee93` is CI-green (CI + V2C Replay). PASS
179. The `checks` matrix runs full pytest on CPython 3.12 and 3.13. PASS
180. Full suite green on 3.12 (local, exit 0). PASS
181. Full suite green on 3.13 (3632 passed, 62 skipped, 0 failed). PASS
182. The `v2c-replay` workflow has `permissions: contents: read`. PASS
183. `v2c-replay` pins `actions/checkout` by SHA. PASS
184. `v2c-replay` runs the state-aware `replay` which exercises State B (completed). PASS
185. `v2c-replay` `main()` fails closed (returns 1 on any raise). PASS
186. `v2c-replay` asserts the three sealed ledgers byte-empty. PASS
187. The re-execution provenance test runs on 3.12 and skips on 3.13 (runtime gate). PASS
188. The read-only certification runs on both 3.12 and 3.13. PASS
189. The inactive probe templates (`*.yml.inactive`) are inert and never dispatchable. PASS
190. No active acquisition / network-egress workflow exists. PASS

## P. Governance neutrality & documentation (191–205)

191. The run commit changed only registry + qualifications + tests (no config/source). PASS
192. `git diff 530f182 HEAD` over `.github/`, `pyproject.toml`, `uv.lock`, `src/` is empty. PASS
193. No other test assumes a pristine/absent registry (only the conftest fixture). PASS
194. `docs/V2C_OQ_METHOD.md` documents the methodology and verification model. PASS
195. `governance/v2c/README.md` documents the governance layout + invariants. PASS
196. `docs/V2C_RECOVERY.md` documents the crash/recovery model. PASS
197. `docs/V2C_SECURITY.md` documents the threat model + controls + limitations. PASS
198. `docs/V2C_POSTQUAL_RED_TEAM.md` records the five auditors + dispositions. PASS
199. `docs/V2C_FINDINGS.md` is the formal findings register (F-1..F-7). PASS
200. `docs/V2C_BUG_LOG.md` records B-001 + C-001 + the red-team summary. PASS
201. `docs/V2C_PLAN.md`, `V2C_PREFREEZE_REDTEAM.md`, `V2C_PREQUAL_RED_TEAM.md` retained. PASS
202. `sell_ready` is derived-**false** (no strategy qualified). PASS
203. The OQ certifies offline operations readiness only — not a product. PASS
204. All doc claims are consistent with the committed state (no overclaim). PASS
205. The authorized terminal verdict holds verbatim (see header). PASS

---

## Verdict

All 205 audited items PASS. The committed offline operational qualification is genuine,
byte-deterministic, from-source reproducible, independently accepted, evaluates no strategy or
candidate, and leaves all three sealed partitions byte-empty; the OQ-E2 freeze reproduces, the
OQ-E2A anchor binds it, `e4b3cc3` stays superseded, `2a9e528` and the version are untouched, and CI
is green on both interpreters. No Class-A or Class-D defect exists. The one actionable red-team
finding is fixed and the remainder are document-only / by-design.

**V2C COMPLETE — PROSPECTIVE-EVIDENCE AND OFFLINE-OPERATIONS QUALIFICATION READY, NOT ACTIVE; NO
STRATEGY EVALUATED; ALL SEALED PARTITIONS UNTOUCHED; V2 NOT SELL-READY.**
