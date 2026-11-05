# Palette's Journal - Critical Learnings Only

## 2026-11-02 - Actionable Empty State & Live Region for Filtered Grids
**Learning:** In multi-filter catalog grids with text search, dropdowns, and checkboxes, reaching 0 results without a reset action causes user disorientation and tedious manual backtracking across controls. Additionally, dynamic result count updates are silent to screen readers unless marked with polite live announcements.
**Action:** Always accompany zero-result empty states with an actionable reset button ("Réinitialiser les filtres") that restores default states and refocuses search, and attach `aria-live="polite"` to the dynamic results counter for accessible announcements.

## 2026-11-03 - Focus Restoration, Escape Dismissal and Scrollable Diff Previews
**Learning:** Collapsible preview sections or slide-over overlays (such as the OpenCode unified diff preview) leave keyboard and screen reader users disoriented when opened without focus transfer, cannot be dismissed via standard `Escape`, drop focus position into `body` upon closure, and prevent keyboard-only users from scrolling preformatted diff blocks. Furthermore, API/network errors posted into banners with static `role="status"` fail to trigger assertive assistive announcements.
**Action:** When expanding inspection panels, transfer focus to the close button, enable an `Escape` listener that hides the panel and returns focus to the invoking trigger button, endow scrollable `<pre>` viewports with `tabindex="0" role="region" aria-label="..."`, and toggle banner semantics between `role="status"` (polite) and `role="alert"` (assertive) based on operation success.

## 2026-11-05 - Focus Preservation & Live Feedback in Dynamic Orderable Lists
**Learning:** Reordering items in interactive rank/priority panels using icon-only buttons triggers full DOM re-renders that reset document focus to `body`, forcing keyboard-only and screen reader users to repeatedly Tab back into the list after every single move. Additionally, users receive no audible feedback about new rankings or list boundaries.
**Action:** In orderable lists, track the moved item's identity across re-renders, immediately restore focus to the item's corresponding movement control (falling back to the reverse direction button when reaching list boundaries), enrich reorder buttons with current-rank context in `aria-label`, and announce changes through an `aria-live="polite"` status region.
