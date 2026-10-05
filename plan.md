# Research Plan (v2, FROZEN 2026-09-27)

**Empirical evaluation of prompt-injection defenses for CPU-run 3–4B tool-calling agents**

Supersedes plan v1 (git history; original file `plan(6).md` kept unchanged). The authority for scope and claims is `literature/final_novelty_verification.md`. Where v1 and this file differ, this file applies.

## 0. What kind of study this is

An **empirical evaluation study**, not a new-framework paper. The contribution is a controlled measurement of security, competence-conditioned security, utility, CPU time and memory for 3–4B tool-calling agents under three established defense families plus a no-defense baseline and a tool-filter baseline. The deterministic runtime-policy gate (B4) is one experimental condition representing the runtime-enforcement family. It is **not** claimed as a new security paradigm.

## 1. Research question (single, frozen)

> For two 3–4B open-weight tool-calling agents from different model families running on a CPU-only laptop, how much do a prompt-level defense (spotlighting), a small classifier detector (PromptGuard-2-22M), and a deterministic runtime-policy gate reduce attack success on AgentDojo? The reduction is measured both raw and restricted to tasks each agent completes without attack. And what end-to-end latency, memory and benign-utility costs do these defenses add?

Removed from v1: "1–4B"; comparison of rankings with frontier models; cross-benchmark ranking; signal ablation as a research question; any claim that the trust/risk gate is a new paradigm; MELON as a default condition.

## 2. Hypotheses (to test, not to assume)

- **H1.** Undefended raw ASR understates vulnerability on tasks the agent can perform: ASR_C(B0) ≥ raw ASR(B0) for each model.
- **H2.** At least one defense reduces ASR_C relative to B0 (paired, Holm-corrected; EXPERIMENT_MATRIX.md §6).
- **H3.** Defenses that do not add LLM calls (B2, B3, B4) add less median latency than B1, which adds one call.
- **H4.** The provenance rule of B4 costs benign utility on tasks whose parameters legitimately come from tool outputs (FPR_task(B4) > 0).

Any hypothesis may be refuted. Null or negative outcomes, including B4 not outperforming B2 or B3, are reported as found.

## 3. Design summary (details in the linked files)

| Element | Decision | Specified in |
|---|---|---|
| Models | M1 = Qwen3-4B-Instruct-2507; M2 = see DECISIONS.md §Model Selection (two different families) | DECISIONS.md |
| Execution | CPU-only, in-process llama.cpp, Q4_K_M GGUF, greedy decoding | EXPERIMENT_MATRIX.md §5 |
| Benchmark | AgentDojo 0.1.35 / suites v1.2.2; banking + slack; TEST = 32 user tasks, 96 injection pairs; DEV = 5 banking tasks | BENCHMARK_PROTOCOL.md |
| Defenses | B0 none · B1 tool filter · B2 spotlighting · B3 PromptGuard-2-22M · B4 deterministic runtime-policy gate | DEFENSE_SPEC.md |
| Attacks | A0 benign · A1 AgentDojo `important_instructions` · A2 one defense-aware template (B2–B4) | EXPERIMENT_MATRIX.md §3 |
| Measurements | raw ASR, ASR_C (task-level competence-conditioned), VR (P58 formulation), BTSR, ATSR, FPR/FNR, p50/p95 latency, peak RSS, model calls, input/output/total tokens, successful/blocked/incorrect tool calls | metrics.md |
| Statistics | cluster bootstrap over user tasks; paired permutation tests with Holm correction for 16 security/utility contrasts | EXPERIMENT_MATRIX.md §6 |
| Pilot | P0 with a pre-registered competence threshold and replacement rule | EXPERIMENT_MATRIX.md §7 |
| Supporting analysis | ≤ 3 internal-validity ablations of B4 (M1 only); not an RQ | DEFENSE_SPEC.md |
| Budget | ≈ 2,260 episodes, ≈ 35–44 CPU-hours | EXPERIMENT_MATRIX.md §8 |

## 4. Contribution claims permitted (from final_novelty_verification.md §8)

1. A controlled CPU-only evaluation of defense families on defended 3–4B tool-calling agents from two families on AgentDojo, extending the undefended 4B setting of P44.
2. An application of the P58-style competence-conditioned measure to a defense comparison (confound noted by P44 and P56).
3. End-to-end CPU cost (p50/p95, peak RSS, model calls, tokens) per defense, complementing GPU/API cost reports (P55, P59) and addressing what P18 did not measure.
4. A released reproducible harness (native-format in-process AgentDojo connector, pinned configs, raw logs).

**Not permitted:** "first", "novel framework/paradigm", "state of the art", "universally better", or any claim that a concept owned by P44/P52/P58 is ours.

## 5. Scope limits

**In scope:** indirect prompt injection via tool outputs in AgentDojo banking/slack; the five defense conditions; CPU cost.

**Out of scope:** direct user jailbreaks; memory poisoning; multi-agent settings; MCP servers; optimization attacks (TAP/GCG); model training or fine-tuning; additional benchmarks; more than two models; MELON (optional only, per DEFENSE_SPEC.md).

## 6. Workflow and gates

| Step | Content | Gate to proceed |
|---|---|---|
| S0 | Freeze design documents (this commit) | PI approval |
| S1 | Implement B1–B4 wrappers, A2 templates, episode runner and metrics code; unit tests; DEV-split checks only | Tests pass; B4 spec and A2 hashes recorded in DECISIONS.md |
| P0 | Pilot per EXPERIMENT_MATRIX.md §7 | Both models pass T1–T4, or the replacement rule is applied; PI approval |
| S2 | Main matrix (serial, overnight blocks) | Raw logs complete; no post-hoc changes |
| S3 | B4 ablations | — |
| S4 | Analysis from raw logs → tables/figures | Reproducible from `results/raw` by one command |
| S5 | Journal selection, then manuscript drafting | PI approval of results and claims |

## 7. Reproducibility requirements

- Every run is reproducible from a configuration file plus pinned artefacts.
- Save: model/GGUF hashes, experiment/run ID, configuration, seed, raw results (write-once), processed results, generated tables and figures, and environment records.
- Numerical results in any manuscript come only from generated tables. They are never edited by hand.

## 8. Statistical-integrity rules

- Report CIs with every estimate. Pair comparisons wherever the design supports it. Correct for multiple comparisons (Holm).
- Report effect sizes, and interpret them for security and utility, not only p-values.
- Do not select tests after seeing data. Do not re-run cells to change outcomes. Do not reduce repetitions or tasks after results are seen.

## 9. Academic integrity (unchanged from v1)

- No copied or sentence-by-sentence paraphrased text. Cite the original source for ideas, datasets, benchmarks, algorithms and claims. Keep notes in own words. Maintain a verified reference database.
- No fabricated references, results, experiments or DOIs. Do not report experiments that were not run. Do not alter results.
- AI-use disclosure follows the target journal's current policy.

## 10. Paper structure (to be written only after S4)

Title · Abstract · Keywords · Introduction · Background & Threat Model · Related Work (with the closest-work comparison table) · Study Design · Experimental Setup · Results · Supporting Analyses (B4 ablations, A2) · Discussion · Limitations · Reproducibility/Availability · Conclusion · Declarations · References. Use the target journal's template and author guidelines.

## 11. Quality gate before submission (all must be YES)

- [ ] RQ answered by the data
- [ ] Positioning supported by literature (final_novelty_verification.md re-run before submission)
- [ ] Threat model explicit
- [ ] Defense implementations faithful to their sources, with deviations documented
- [ ] Attacks reproducible; A2 templates frozen before test
- [ ] Benchmark and version cited
- [ ] Hyperparameters, seeds and hashes reported
- [ ] Raw results preserved
- [ ] Security and utility reported together; competence conditioning reported alongside raw ASR
- [ ] Statistics per the pre-registered plan
- [ ] Limitations honest, including CPU-specificity, static/adaptive attack limits and the 3–4B scope
- [ ] No fabricated results or citations; no copied text
- [ ] Figures and tables generated from reproducible data
- [ ] Journal template, declarations and AI-use disclosure complete

## 12. Final research principle

The paper answers: *under this defined threat model, on this benchmark subset and this hardware, how much does each defense reduce attack success on tasks the agent can actually perform, and what does it cost in utility, time and memory?* It does not try to show that any method is perfect or new.
