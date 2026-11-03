# Palette's Journal - Critical Learnings Only

## 2026-11-02 - Actionable Empty State & Live Region for Filtered Grids
**Learning:** In multi-filter catalog grids with text search, dropdowns, and checkboxes, reaching 0 results without a reset action causes user disorientation and tedious manual backtracking across controls. Additionally, dynamic result count updates are silent to screen readers unless marked with polite live announcements.
**Action:** Always accompany zero-result empty states with an actionable reset button ("Réinitialiser les filtres") that restores default states and refocuses search, and attach `aria-live="polite"` to the dynamic results counter for accessible announcements.

## 2026-11-03 - Focus Restoration, Escape Dismissal and Scrollable Diff Previews
**Learning:** Collapsible preview sections or slide-over overlays (such as the OpenCode unified diff preview) leave keyboard and screen reader users disoriented when opened without focus transfer, cannot be dismissed via standard `Escape`, drop focus position into `body` upon closure, and prevent keyboard-only users from scrolling preformatted diff blocks. Furthermore, API/network errors posted into banners with static `role="status"` fail to trigger assertive assistive announcements.
**Action:** When expanding inspection panels, transfer focus to the close button, enable an `Escape` listener that hides the panel and returns focus to the invoking trigger button, endow scrollable `<pre>` viewports with `tabindex="0" role="region" aria-label="..."`, and toggle banner semantics between `role="status"` (polite) and `role="alert"` (assertive) based on operation success.
