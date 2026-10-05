# Model screening protocol (written 2026-09-27, BEFORE the screening runs)

Purpose: decide which 3–4B candidates can reliably tool-call inside AgentDojo (PART 3, item 8).
This is not P0 and not an experiment. Results are used only for model selection.

- Tasks: AgentDojo v1.2.2 banking user_task_0 … user_task_4, benign (no injection), defense B0.
  These five tasks become the DEVELOPMENT split. They are excluded from the P0 competence
  assessment and from the main test set, because they were used for selection.
- Harness: agents/native_llm.py, native tool format per model, greedy, seed 0, n_ctx 16384, 4 threads.
- Candidates: Qwen3-4B-Instruct-2507, Phi-4-mini-instruct (already run in Stage 2; reused),
  Granite-4.0-micro, SmolLM3-3B. Ministral-3-3B was rejected before screening (fails to load in
  llama-cpp-python 0.3.35). Gemma-3-4b-it and Llama-3.2-3B were not screened (gated; license
  acceptance is the PI's decision).
- **Tool-calling reliability rule (fixed now):** a candidate PASSES screening if
  (a) in ≥ 4 of 5 tasks it issues at least one parseable tool call, and
  (b) parse errors are < 10% of its model calls.
  Benign utility on these 5 tasks is recorded but is NOT a screening criterion
  (the competence threshold is applied later, in P0, on different tasks).
- Phi-4-mini diagnostic (not a selection criterion): re-run user_task_0 with a minimal system
  message to test whether the long AgentDojo system prompt suppresses its tool use. The main
  protocol will never change the system message per model.
