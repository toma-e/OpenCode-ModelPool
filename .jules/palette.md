# Palette's Journal - Critical Learnings Only

## 2026-11-02 - Actionable Empty State & Live Region for Filtered Grids
**Learning:** In multi-filter catalog grids with text search, dropdowns, and checkboxes, reaching 0 results without a reset action causes user disorientation and tedious manual backtracking across controls. Additionally, dynamic result count updates are silent to screen readers unless marked with polite live announcements.
**Action:** Always accompany zero-result empty states with an actionable reset button ("Réinitialiser les filtres") that restores default states and refocuses search, and attach `aria-live="polite"` to the dynamic results counter for accessible announcements.

## 2026-11-03 - Focus Restoration, Escape Dismissal and Scrollable Diff Previews
**Learning:** Collapsible preview sections or slide-over overlays (such as the OpenCode unified diff preview) leave keyboard and screen reader users disoriented when opened without focus transfer, cannot be dismissed via standard `Escape`, drop focus position into `body` upon closure, and prevent keyboard-only users from scrolling preformatted diff blocks. Furthermore, API/network errors posted into banners with static `role="status"` fail to trigger assertive assistive announcements.
**Action:** When expanding inspection panels, transfer focus to the close button, enable an `Escape` listener that hides the panel and returns focus to the invoking trigger button, endow scrollable `<pre>` viewports with `tabindex="0" role="region" aria-label="..."`, and toggle banner semantics between `role="status"` (polite) and `role="alert"` (assertive) based on operation success.

## 2026-11-04 - Accessible Notification Banner Dismissal and Transient Timers
**Learning:** Persistent notification banners at the top of web interfaces quickly clutter the screen and create repetitive friction for keyboard and screen reader users when they cannot be dismissed. Additionally, auto-dismissing error alerts prematurely can prevent assistive tech users from perceiving critical failures.
**Action:** Always provide an explicit accessible dismiss button (`aria-label="Fermer la notification"`) and keyboard `Escape` handler on notification banners, and differentiate dismissal behavior by automatically clearing success feedback after a short duration while keeping errors persistent until user dismissal.

## 2026-11-04 - Accessible Reordering: Focus Preservation & Live Position Announcements
**Learning:** In interactive re-orderable lists (like execution channel priority), re-rendering the list DOM after an item move resets active keyboard focus to the `body`, breaking the user's sequential workflow and requiring repetitive tabbing. Screen reader users also receive no feedback about the new item order unless polite live status regions announce the positional shift.
**Action:** Whenever re-rendering a dynamically reordered list, explicitly maintain focus on the moved item's action button (or swap to its enabled sibling button when hitting the top/bottom boundary), and emit polite live region announcements (e.g. "[Item] déplacé en position X sur Y").

## 2026-11-11 - Dynamic Form Re-rendering & Explicit Label Association
**Learning:** Submitting asynchronous form updates that cause complete DOM re-renders of list items (such as agent configuration cards) resets keyboard focus back to the `document.body`, disorienting keyboard users who then lose their place in the hierarchy. Furthermore, wrapping checkboxes in `<label>` without explicit `for`/`id` pairing impairs accessibility tree inspection and assistive technology hit-testing in complex grid cards.
**Action:** Always maintain explicit `for` and `id` bindings on all form inputs and checkboxes, and systematically refocus the invoked form's action button upon completing re-rendering using escaped identifier selectors (`CSS.escape`).
