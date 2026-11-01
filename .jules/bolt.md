# Bolt's Performance Journal

Critical performance learnings, architectural bottlenecks, and optimization discoveries in OpenCode-ModelPool.

## 2026-11-01 - Redundant Regex Evaluation in Multi-Agent Model Selection

**Learning:** During fleet assignment and validation (`ApplicationService.build_report`), compatibility checks (`common_constraint_violations`) run across all $N$ models for all $M$ agents in multiple passes (exact match, fallback, fallback-chain candidates). Calling regexes and substring checks on each evaluation without caching in `is_non_llm_model` created ~28,000 regex executions per build and accounted for ~30% of total CPU time.

**Action:** Separate pure, immutable string ID checks from dynamic dictionary/list arguments (`architecture`, `output_modalities`) and memoize the string ID evaluations with `@functools.lru_cache(maxsize=2048)`. This reduces evaluation from $O(N \times M)$ redundant executions down to $O(N)$ once per model, dropping fleet report execution time by ~43%.
