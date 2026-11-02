# Palette's Journal - Critical Learnings Only

## 2026-11-02 - Actionable Empty State & Live Region for Filtered Grids
**Learning:** In multi-filter catalog grids with text search, dropdowns, and checkboxes, reaching 0 results without a reset action causes user disorientation and tedious manual backtracking across controls. Additionally, dynamic result count updates are silent to screen readers unless marked with polite live announcements.
**Action:** Always accompany zero-result empty states with an actionable reset button ("Réinitialiser les filtres") that restores default states and refocuses search, and attach `aria-live="polite"` to the dynamic results counter for accessible announcements.
