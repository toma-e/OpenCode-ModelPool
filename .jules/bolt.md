# Bolt's Journal - OpenCode-ModelPool

Journal for recording critical performance learnings in this repository.

## 2026-10-30 - Memoizing model string normalization & classification
**Learning:** During multi-agent report calculation across 400+ models, string manipulation and regular expression evaluation in model classification (`is_non_llm_model`) and channel routing (`normalize_model_basename`) were executed hundreds of thousands of times per calculation run. Delegating string pattern detection to bounded LRU caches (`@functools.lru_cache(maxsize=2048)`) reduced overall `build_report` runtime by over 50% (2.06x speedup).
**Action:** Always check whether string normalization and regex identification routines called in model filtering loops are memoized with `@functools.lru_cache`.
