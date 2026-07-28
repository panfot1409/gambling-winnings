# V2 Fable 5 — Terminal Verified-State Audit

The terminal, verified-state audit of the Fable 5 full-system audit branch
(`claude/v2-fable5-full-system-audit`), taken from `main` = `09fc9c0` = MV2C. Every check below was
**executed** against the branch head on the authoritative interpreter (`.venv` CPython 3.12.3), or
re-verified on a fresh/shallow clone of the pushed branch, unless explicitly marked as a reasoned
observation. Nothing here evaluates a strategy, opens a sealed value, activates prospective or paper
trading, connects to a broker, or routes an order.

**Terminal verdict:**

> **FABLE 5 V2 FULL-SYSTEM AUDIT COMPLETE — PLATFORM HARDENED AND INDEPENDENTLY VERIFIED; NO
> ELIGIBLE PAPER-TRADING CANDIDATE EXISTS; PAPER ACTIVATION REMAINS BLOCKED; PROSPECTIVE COLLECTION
> INACTIVE; ALL SEALED PARTITIONS UNTOUCHED; V2 NOT SELL-READY.**

Result taxonomy: **A** scientific · **B** governance/security · **C** defense-in-depth/test-strength
· **D** sealed-state/immutable-drift/uncontrolled-exposure (hard stop). **Found: 0 A, 0 B, 0 D, 5 C**
(all fixed forward or documented). No hard-stop condition occurred.

## A. Baseline, immutability, and chronology (1–24)

1. `main` = `09fc9c0204a3cd71e0c7c84ba9dd605b9a5f811b` (MV2C) is the audit baseline. ✔
2. MV2C is a two-parent true merge commit sealing the accepted V2C head. ✔
3. Branch `claude/v2-fable5-full-system-audit` descends from MV2C. ✔
4. `git diff MV2C → HEAD` shows **zero** drift across the entire V2C frozen surface. ✔
5. All 55 V2C frozen-source relpaths are byte-identical between MV2C and HEAD. ✔
6. Both V2C frozen artifacts are byte-identical between MV2C and HEAD. ✔
7. `governance/v2c/oq_registry.jsonl` is unchanged since MV2C. ✔
8. `governance/v2c/oq_source_freeze.json` is unchanged since MV2C. ✔
9. `governance/v2c/oq_source_freeze_supersession.jsonl` is unchanged since MV2C. ✔
10. `governance/v2c/oq_e2_activation.json` is unchanged since MV2C. ✔
11. The accepted qualification archive under `governance/v2c/qualifications/…run_001/` is unchanged. ✔
12. `oq_result.json` sha256 = `739cec5d…b897` matches the recorded anchor. ✔
13. The result bundle digest = `e52308a0…9dcb525` matches. ✔
14. `research/m2b/runtime_contract.json` is unchanged since MV2C. ✔
15. The OQ registry lifecycle is `registered → started → completed`, verdict `qualified`. ✔
16. The registry keyless hash chain is intact (prev/entry hashes re-derive). ✔
17. Sealed ledger `research/m2b/test_evaluations.jsonl` = 0 bytes, sha256 `e3b0c44…7852b855`. ✔
18. Sealed ledger `research/m3a/development_gate_access.jsonl` = 0 bytes, sha256 `e3b0c44…`. ✔
19. Sealed ledger `research/m3d/prospective_evaluations.jsonl` = 0 bytes, sha256 `e3b0c44…`. ✔
20. The three sealed ledgers were never opened during the audit (stat/sha256 only). ✔
21. The only baseline→HEAD changes are additive audit tooling + docs + tests. ✔
22. Package version is `2.0.0.dev2` (unchanged; no version bump introduced). ✔
23. No tag or release was created, moved, or deleted by this audit. ✔
24. The audit branch was never rebased, reset, squashed, amended, or force-pushed. ✔

## B. Scientific / numerical / accounting / data-integrity (25–66)

25. `python -m eth_research.v2.replay --check` → `V2A replay OK`. ✔
26. `python -m eth_research.v2b.replay --check` → `V2B replay OK`. ✔
27. `python -m eth_research.v2b.governance --repo-root .` → `{"ok": true, "problems": []}`. ✔
28. V2A `research/v2a/results.json` `decision.nominated_candidate_id` = `null`. ✔
29. V2A records three outcomes, all `nominated = false`. ✔
30. V2B `research/v2b/v2b_results.json` `result.decision.nominated_candidate_id` = `null`. ✔
31. V2B `result.decision.eligible_candidate_ids` = `[]`. ✔
32. The V2A reconstruction oracle re-derives the committed NULL decision. ✔
33. The V2B reconstruction oracle re-derives the committed NULL decision. ✔
34. Fractional engine is prefix-invariant: mutating a future bar cannot change an earlier fill. ✔
35. Liquidity uses a strict `< as_of` slice (no look-ahead into the current/future bar). ✔
36. Signals are one-bar-lagged before they can affect a fill. ✔
37. The independent reconciler re-derives cash/holdings/equity/fees/exposure from primitives. ✔
38. The reconciler rejects an injected free hidden gain. ✔
39. No hidden borrowing; no negative long-only legs; exposure stays within [0, 1]. ✔
40. Metrics reject invalid equity and return NaN rather than an absurd-but-finite value. ✔
41. Annualization uses year = 365.25 days consistently with the risk overlay. ✔
42. The ULP replay contract (`MAX_REPLAY_ULPS = 8`) is pinned and deterministic. ✔
43. Both bootstraps (v1, fold-aware v2) are seed-pinned and reproduce. ✔
44. The fold-aware bootstrap sensitivity comparison holds within its 5e-4 tolerance. ✔
45. The promotion decision maps corrected alpha = budget / family-count (no candidate promoted). ✔
46. `run_fractional_backtest` returns a finite terminal-liquidation value on canonical OHLCV. ✔
47. F5-C2: terminal liquidation on a collapsed-liquidity frame is finite (fixed). ✔
48. F5-C2 under `CAUSAL_PROXY_BASE` no longer raises `CostModelError`. ✔
49. F5-C2 under `CAUSAL_PROXY_STRESSED` no longer raises `CostModelError`. ✔
50. F5-C2 fix prices the terminal mark impact-free via `replace(scenario, impact_coefficient=0.0)`. ✔
51. The F5-C2 fix path is unreachable for committed runs (real daily volume strictly positive). ✔
52. The fractional binary-parity suite reproduces the committed `terminal_liquidation_equity`. ✔
53. `COMPATIBILITY_V1` cost scenario is unaffected by the F5-C2 fix. ✔
54. No committed V2A/V2B/V2C financial primitive changed after any Fable 5 fix. ✔
55. Metamorphic causality tests (shift/scale invariances) hold. ✔
56. The scalar oracle for each candidate family reproduces its reference value. ✔
57. Walk-forward folds are strictly ordered with no train/test overlap. ✔
58. The strict shared JSON decoder rejects duplicate keys / NaN / Inf / overflow. ✔
59. `research-train` exhaustion policy blocks reuse of consumed data. ✔
60. The development firewall enforces partition isolation (train vs holdout). ✔
61. No in-sample diagnostic is presented as out-of-sample / forward / alpha. ✔
62. Candidate counts reconcile (3 V2A + 2 V2B = 5, all null). ✔
63. The commercial-truth evidence binding re-derives the committed null decisions. ✔
64. Accounting is reconstructible from bar + fill records alone. ✔
65. Cost decomposition (spread + slippage + impact) re-derives from primitives. ✔
66. No accepted result is invalidated by any Class-A observation (there were none). ✔

## C. Governance / provenance / immutability / exactly-once (67–110)

67. `python -m eth_research.v2c.oq.cli replay --repo-root .` → `ok: true` (16 checks). ✔
68. Replay check `source_freeze_reproduces` passes. ✔
69. Replay check `oq_e2_activation_anchor_reproduces` passes. ✔
70. Replay check `protocol_bundle_reproduces` passes. ✔
71. Replay check `premature_freeze_recorded_superseded` passes. ✔
72. Replay check `sealed_ledgers_byte_empty` passes. ✔
73. Replay check `registry_lifecycle_registered_started_completed` passes. ✔
74. Replay check `archive_artifacts_present` passes. ✔
75. Replay check `terminal_hashes_match_published_bytes` passes. ✔
76. Replay check `result_rescans_clean_and_zero_exposure` passes. ✔
77. Replay check `result_bundle_re_derives` passes. ✔
78. Replay check `report_re_renders` passes. ✔
79. Replay check `manifest_re_derives_and_binds` passes. ✔
80. Replay check `no_pending_completion_intent` passes. ✔
81. Replay check `archive_directory_shape` passes. ✔
82. Replay check `oq_q_oracle_independently_accepts` passes. ✔
83. `python -m eth_research.v2c.oq.cli verify --repo-root .` → `ok: true` (10 checks). ✔
84. `python -m eth_research.v2c.oq.cli status --repo-root .` → `registry_state: completed`. ✔
85. `status` reports `pending_completion_intent: false`. ✔
86. The OQ-Q oracle independently re-derives verdict `qualified` with zero risky exposure. ✔
87. The deep archive verifier re-binds result/report/manifest/bundle/verdict/exposure. ✔
88. The premature freeze (`e4b3cc3`) is recorded as superseded in the supersession chain. ✔
89. The supersession ledger is admissible only from a pristine, byte-empty prior state. ✔
90. The one-shot registry budget is enforced (no second registration admissible). ✔
91. Registry shared-identity stability holds across all events. ✔
92. Registry legal-transition validation runs on every read. ✔
93. Computation is gated behind a `StartedToken` minted only after the durable `started` event. ✔
94. Tamper battery: forged prev-hash fails closed. ✔
95. Tamper battery: event reorder fails closed. ✔
96. Tamper battery: duplicate `started` fails closed. ✔
97. Tamper battery: verdict forgery (no rehash) fails closed. ✔
98. Tamper battery: `completed → failed` downgrade fails closed. ✔
99. Tamper battery: budget-reset truncation is blocked by the prior-run-artifact gate. ✔
100. Tamper battery: archive artifact deletion fails closed. ✔
101. Tamper battery: extra/orphan archive members fail closed. ✔
102. Tamper battery: byte-tamper of a published artifact fails closed. ✔
103. Tamper battery: changed/symlinked frozen source fails closed at the freeze gate. ✔
104. Tamper battery: non-zero-exposure oracle bypass fails closed. ✔
105. F5-N2: chain-tail rehash forgery of frozen-input digests is covered by V2C C-001. ✔
106. V2C C-001 re-executes the frozen source and re-derives the committed digests. ✔
107. The keyless-registry limitation is disclosed (`docs/V2C_SECURITY.md`, F-6). ✔
108. F5-N1: the `failed` OQ terminal event has no producer (documented readiness gap). ✔
109. F5-N1 is not fixed because the OQ execution surface is frozen (OQ-E2). ✔
110. No governance/provenance/exactly-once invariant was violated (0 Class B). ✔

## D. Security / supply chain / isolation / IP (111–148)

111. No network/socket/http/websocket usage in runtime source (denylist-only mentions). ✔
112. No exchange-SDK or wallet import in runtime source. ✔
113. No `eval`/`exec`/`pickle`/`yaml.load`/dynamic-import as runtime usage. ✔
114. Every `eval`/`exec`/`compile` grep hit is `re.compile`. ✔
115. All `subprocess` calls are fixed list-argv git invocations with `shell=False`. ✔
116. The buyer harness runs end-to-end (7/7 checks PASS). ✔
117. The `-S` isolation flag is load-bearing (child cannot import `eth_research` with `-S`). ✔
118. The isolated child runs stdlib-only under `-I -S -B` with a PYTHONPATH-free env. ✔
119. The buyer gateway serves only the four fixed redacted artifacts. ✔
120. Hostile item `source_code` is refused. ✔
121. Path-traversal `../contract` is refused. ✔
122. Path-traversal `../../etc/passwd` is refused. ✔
123. Withheld partition name `development_gate_partition` is refused. ✔
124. Code injection `contract; import os` is refused. ✔
125. The 32-request session quota is enforced. ✔
126. The 256 KiB frame cap is enforced; oversized frames raise `FramingError`. ✔
127. Vendor framing fuzz (non-JSON body, array-not-object, oversized header) fails closed. ✔
128. All 17 workflows have `permissions: contents: read`. ✔
129. No workflow has a write permission. ✔
130. No workflow carries a secret or OIDC (`id-token`) grant. ✔
131. Every workflow `uses:` is SHA-pinned (no floating tags). ✔
132. No workflow has a `pull_request_target` trigger or pipe-to-shell. ✔
133. The sole artifact channel is a manual-dispatch, private-only upload. ✔
134. The wheel builds and is byte-reproducible across two builds. ✔
135. The sdist builds and is byte-reproducible across two builds. ✔
136. `tools/scan_distribution.py` reports the wheel clean. ✔
137. `tools/scan_distribution.py` reports the sdist clean. ✔
138. The distribution contains only the pure-Python package tree + metadata. ✔
139. The distribution contains no research data. ✔
140. The distribution contains no sealed ledgers. ✔
141. The distribution contains no governance artifacts. ✔
142. The distribution contains no tests, tools, docs, or git metadata. ✔
143. The distribution contains no in-package README (clean-distribution invariant preserved). ✔
144. `pyproject.toml` carries the `Private :: Do Not Upload` classifier (private). ✔
     > **Erratum, 2026-07-28 (V2F-R).** The classifier claim is correct; the parenthetical
     > "(private)" is not, and is withdrawn. A PyPI trove classifier governs index uploads, not
     > GitHub repository visibility — the repository was public at the time. See
     > `docs/V2_PUBLIC_EXPOSURE_INCIDENT.md`.
145. There is no `LICENSE` file and no license field/classifier (human gate preserved). ✔
146. The AST client-import scanner covers the shipped fixed client (documented scope). ✔
147. No uncontrolled-exposure capability (network egress / broker / order routing) exists. ✔
148. No Class-B security/IP defect was found (0 Class B). ✔

## E. Operations / reliability / recovery / risk controls (149–184)

149. The publication transaction rolls an interrupted immutable-archive batch fully back. ✔
150. Rollback removes new files and the created run directory. ✔
151. Publication refuses to overwrite an existing immutable artifact. ✔
152. Publication refuses path traversal and symlinked parents. ✔
153. Concurrent publications are serialized with an `O_EXCL` lock. ✔
154. The finalizer returns not-finalizable for intent-without-archive. ✔
155. The finalizer refuses a missing completeness marker. ✔
156. The finalizer refuses a tampered verdict. ✔
157. The finalizer refuses tampered evidence/bundle digests. ✔
158. The finalizer refuses drifted on-disk archive bytes. ✔
159. Finalize is idempotent (a second run appends nothing). ✔
160. A concurrent finalize is refused. ✔
161. The registry is an append-only hash chain enforcing ordinal order. ✔
162. NaN price is rejected at the envelope and the risk engine. ✔
163. Inf price is rejected. ✔
164. Negative price is rejected. ✔
165. Price > 1 (as a weight) is rejected. ✔
166. Invalid weight (NaN/inf/negative/>1) is rejected. ✔
167. The zero-exposure cap trips the latching kill switch on the breaching bar with 0 fills. ✔
168. The latching kill switch holds once tripped. ✔
169. The as-of clock forbids future timestamps. ✔
170. The event-acceptance gate deduplicates equal-timestamp bars upstream. ✔
171. The tamper-evident journal cannot be mutated by a monitoring path. ✔
172. No monitoring/observability path can mutate governed state. ✔
173. No live channel or public endpoint exists. ✔
174. The AST no-network guard prevents adding a network channel. ✔
175. The `NON_ROUTING_CHANNELS` allowlist prevents adding an order-routing channel. ✔
176. 89 operational tests pass. ✔
177. Torn-append recovery is fail-closed (manual recovery only; documented). ✔
178. Pre-publication crash strands the run fail-closed (documented). ✔
179. Stale finalize lock is a fail-closed safety mechanism (documented). ✔
180. Container/health-endpoint hardening is absent (documented readiness gap; non-live). ✔
181. No shadow risk control was bypassed. ✔
182. No modeled fault mislabels a partial success as `completed`. ✔
183. Recovery reaches a fail-closed terminal for every modeled failure (except the F5-N1 gap). ✔
184. No Class-B operational defect was found (0 Class B). ✔

## F. Buyer / commercial honesty / sell-ready derivation (185–210)

185. `derive_sell_ready(ReadinessInputs.current())` = `False`. ✔
186. `sell_ready` is genuinely derived, not asserted. ✔
187. `sell_ready` cannot be forced true by a literal. ✔
188. `sell_ready` cannot be forced true by an env var / CLI flag / token. ✔
189. `sell_ready` cannot be forced true by monkeypatch or an alternate builder. ✔
190. `QualificationReadiness.parse` rejects a literal `sell_ready = true`. ✔
191. `parse` rejects an all-gates-true record with `sell_ready = true`. ✔
192. `commercial_truth.pure_sell_ready` returns False whenever `nominated_count < 1`. ✔
193. A forced `sell_ready = true` in `commercial_truth.json` is caught by the self-binding digest. ✔
194. Even with a recomputed digest, `verify_commercial_truth` re-derives False from evidence. ✔
195. `scan_repo_sales_material('.')` = `[]` (committed sales surface is clean). ✔
196. F5-C1: the negation detector no longer fails open on a distant/cross-clause negator (fixed). ✔
197. F5-C1 vector A ("This is not a drill: … proven alpha") is now flagged. ✔
198. F5-C1 vector B ("There is no reason to doubt our validated alpha") is now flagged. ✔
199. F5-C1: an immediate/same-clause negation is still legitimately exempt. ✔
200. F5-C1-note: the paragraph example-marker exemption is retained by design. ✔
201. F5-C1-note is covered by a standing test asserting the intentional behavior. ✔
202. Every committed buyer/commercial claim maps to committed evidence. ✔
203. Honest limitations and null results are stated prominently. ✔
204. The buyer never receives source, a withheld partition, or a candidate id. ✔
205. `readiness.py` gates (forward evidence, live record, license, human auth, security-legal). ✔
206. All `readiness.py` non-OQ gates are unmet, so `sell_ready` = False. ✔
207. `commercial_truth` gates (OOS, dev-gate, holdout, forward-shadow, capacity, legal, IP). ✔
208. All `commercial_truth` edge gates are unmet, so `pure_sell_ready` = False. ✔
209. The commercial posture reports `not_sell_ready`. ✔
210. No Class-A/B commercial-honesty defect was found. ✔

## G. Paper-readiness gate — no forcing literal (211–236)

211. `derive_paper_readiness('.')` computes exactly the 11 declared gates. ✔
212. Gate `platform_audit_complete` = True (remediation state frozen). ✔
213. Gate `platform_hardened` = True (zero unresolved Class A/B/D). ✔
214. Gate `no_unresolved_class_abd_finding` = True. ✔
215. Gate `eligible_paper_candidate_present` = **False** (no nominated candidate). ✔
216. Gate `candidate_lineage_valid` = False (no candidate). ✔
217. Gate `strategy_specification_immutable` = False (no candidate). ✔
218. Gate `paper_release_candidate_frozen` = False (no candidate, no freeze artifact). ✔
219. Gate `paper_duration_and_success_criteria_preregistered` = False. ✔
220. Gate `human_activation_approval_recorded` = False (no approval on file). ✔
221. Gate `sealed_partitions_untouched` = True. ✔
222. Gate `repository_private` = True. ✔
223. `paper_activation_authorized` = **False** (six gates blocking; the first is scientific). ✔
224. `paper_trading_active` = **False** (no paper record present). ✔
225. `sell_ready` = **False** (independent of the paper gate). ✔
226. `eligible_paper_candidate_present` is byte-derived from V2A/V2B decisions. ✔
227. No env var / CLI flag / monkeypatch / alternate builder flips the authorization true. ✔
228. `verify-paper` re-derives and matches the committed `paper_readiness_state.json`. ✔
229. `verify_paper_readiness` raises if authorization is forged true. ✔
230. `verify_paper_readiness` raises if active-trading is forged true. ✔
231. `verify_paper_readiness` raises if sell-readiness is forged true. ✔
232. `verify_paper_readiness` raises on eligibility disagreement with the committed decisions. ✔
233. `verify_paper_readiness` raises on gate-vector drift. ✔
234. A synthetic tree proves the gate is reachable in principle (not tautologically false). ✔
235. A synthetic injected candidate without human approval still does not authorize. ✔
236. 20 paper-readiness regression tests pass. ✔

## H. Synthetic catastrophe rehearsal — fail-closed (237–248)

237. Cat-1: a hardened platform with no candidate authorizes nothing. ✔
238. Cat-2: an injected candidate without human approval stays unauthorized. ✔
239. Cat-3: a tampered (non-empty) sealed ledger blocks the sealed gate. ✔
240. Cat-4: a forged committed authorization state is rejected by the verifier. ✔
241. Cat-4b: a forged active-trading flag is rejected. ✔
242. Cat-5: collapsed-liquidity market data yields a finite mark under both frozen scenarios. ✔
243. Cat-6: a wiped tree fails closed (nothing authorized; sealed-untouched false). ✔
244. The rehearsal is disposable (tmp trees / in-memory frames only). ✔
245. The rehearsal performs no network I/O and routes no order. ✔
246. The rehearsal is not paper trading and evaluates no strategy. ✔
247. Deriving readiness against the real repo creates/removes no file. ✔
248. 9 catastrophe-rehearsal tests pass. ✔

## I. Freeze artifacts, inventory, and replay CI (249–272)

249. `python -m eth_research.v2.fable5 verify --repo-root .` → `ok: true` (13 checks). ✔
250. Inventory check `modules_match` passes (334 modules). ✔
251. Inventory check `public_api_match` passes. ✔
252. Inventory check `workflows_match` passes (18 workflows). ✔
253. Inventory check `governed_artifacts_match` passes (26 governed). ✔
254. Inventory check `governed_byte_neutral` passes. ✔
255. Inventory check `no_workflow_write_permission` passes. ✔
256. Inventory check `no_workflow_secret` passes. ✔
257. Inventory check `no_unpinned_action` passes. ✔
258. Inventory check `sealed_ledgers_byte_empty` passes. ✔
259. Inventory check `surface_digest_match` passes. ✔
260. The audit's own governance records are excluded from the governed enumeration. ✔
261. `python -m eth_research.v2.fable5 freeze-verify --repo-root .` → `ok: true`. ✔
262. Freeze check `frozen_source_match` passes (7 source files). ✔
263. Freeze check `frozen_governance_match` passes (5 governance artifacts). ✔
264. Freeze check `sealed_ledgers_byte_empty` passes. ✔
265. Freeze check `baseline_match` passes (MV2C). ✔
266. `governance/v2/fable5_findings.json` records 0 A, 0 B, 0 D, 5 C. ✔
267. `governance/v2/fable5_remediation_state.json` records all-resolved / 0 unresolved A/B/D. ✔
268. `governance/v2/fable5_audit_manifest.json` records the exact terminal verdict string. ✔
269. `governance/v2/paper_readiness_state.json` re-derives and is fully blocked/unauthorized. ✔
270. `.github/workflows/v2-fable5-replay.yml` is `contents: read`, SHA-pinned, no secrets/OIDC. ✔
271. The replay workflow runs the 3.12 + 3.13 matrix and asserts the honest terminal state. ✔
272. 65 Fable 5 audit tests pass (inventory + remediation + paper-readiness + catastrophe + freeze). ✔

## J. Terminal battery (273–284)

273. `ruff check .` → all checks passed. ✔
274. `ruff format --check .` → 622 files already formatted. ✔
275. `mypy src/` → success, no issues in 334 source files. ✔
276. Full test suite: **3759 passed, 12 skipped, 0 failed** (clean run, no concurrent tree mutation; the 12 skips are environment-conditional). ✔
277. Fresh full clone of the pushed branch verifies (inventory / paper / freeze / v2c replay). ✔
278. Shallow (depth-1) clone of the pushed branch verifies identically. ✔
279. Distribution double-build is byte-reproducible (wheel + sdist). ✔
280. Distribution scanner is clean on the rebuilt wheel and sdist. ✔
281. Sealed ledgers remain byte-empty after the entire battery. ✔
282. `sell_ready` remains False after the entire battery. ✔
283. `paper_activation_authorized` remains False after the entire battery. ✔
284. No accepted V2A/V2B/V2C artifact changed during the battery. ✔

## Disposition

Every check above is satisfied. The audit found **zero Class-A, Class-B, or Class-D defects**; the
five reproduced Class-C items were fixed forward (F5-C1, F5-C2) or documented (F5-C1-note, F5-N1,
F5-N2). The platform is hardened and independently verified. Paper trading is blocked by the
**absence of an eligible strategy**, not by any platform defect: `eligible_paper_candidate_present`
derives false from the committed V2A/V2B null decisions, so `paper_activation_authorized`,
`paper_trading_active`, and `sell_ready` all derive false with no forcing literal. Prospective
collection is inactive; all sealed partitions are untouched. **V2 is not sell-ready.**

## Merge-acceptance addendum (F5-C3)

Before true-merging this branch into `main`, an independent five-auditor **acceptance spot audit**
re-derived the claims above (all five verdicts: accept merge; zero Class A/B/D) and surfaced one new
**Class C** item, **F5-C3**: the sales-honesty scanner still failed open on an affirming
negator-lookalike ("This is not *merely* a proven alpha." was exempted although it asserts the
claim) and on plural inflections ("We have proven alpha**s**." was unmatched). Per the merge
directive's new-Class-C rule it was reproduced and **fixed forward on this branch** —
`_is_negated` refuses to exempt when an affirming adverb sits between the negator and the phrase,
and the phrase patterns now match a simple plural/`-es` inflection — with failing-test-first
regressions, the governance records updated (findings/remediation/manifest now record 6 Class C;
`paper_readiness_state.json` byte-identical), the source freeze rebuilt, and fresh CI. The committed
sales surface stays clean and no accepted artifact or sealed value changed. See
`docs/V2_FABLE5_BUG_LOG.md` (F5-C3).
