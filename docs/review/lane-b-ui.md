# UI / frontend review (Lane B)

## Assessment

`static/index.html` presents a coherent Taiwan-assistant dashboard: a sticky header, grouped desktop navigation, a mobile selector, an overview dashboard, and task-oriented cards/forms. The visual tokens, responsive breakpoints, `:focus-visible`, reduced-motion handling, dark-mode variables, skeleton-like overview loading state, and explicit empty/error placeholders are good foundations. `web_app.py` serves the same static entry point at `/`, mounts `/static`, and exposes an aggregate `/api/overview` endpoint, so the shell has a clear single-page data boundary.

The main usability debt is consistency across the many feature panels. The document is a 2,300-line single HTML file with an approximately 820-line inline script; repeated inline handlers and hand-built HTML make changes risky and make it difficult to test states independently. Several labels are visual-only, status/error changes are not uniformly announced, and the mobile/desktop navigation duplicates the same feature taxonomy. Empty states are present for some dashboard lists, but there is no common state model for every result panel, and long-running requests do not visibly disable the initiating action or prevent duplicate submissions.

## Concrete improvements

1. **WHAT:** Give every form control a programmatic label (`for`/`id` pairing or an explicit accessible name), including the repeated city, station, route, date, calendar, and result-limit controls. **WHY:** Several labels at lines 807, 838, 851, 875, etc. are `<label>` elements without `for`, so screen readers may not associate them with their controls; placeholders should not be the label. **Effort:** S. **Touches:** `static/index.html` form panels around lines 801–1484.

2. **WHAT:** Add a consistent page/panel state contract: idle, loading, success, empty, error, and retry, with `aria-busy`, `role="status"`/`role="alert"`, and a retry action where appropriate. **WHY:** The overview has `aria-live`/`aria-busy` at lines 767–776, but ordinary result boxes and the inline loading/error replacements around lines 1568–1681 and 1901–1910 are not uniformly announced. Users can miss updates, especially with slow APIs. **Effort:** M. **Touches:** result boxes around lines 824–1484 and `setLoading`, `setResult`, `loadTowns`, `query` around lines 1568–1910.

3. **WHAT:** Disable the initiating button while its request is pending, preserve its label, and restore focus or announce completion/error when it finishes. **WHY:** `query()` and related handlers show a spinner but do not establish a shared duplicate-submit policy; repeated clicks can create concurrent requests and confusing result order. **Effort:** M. **Touches:** query buttons around lines 820–1484; `query`, `refreshOverview`, `searchStops`, and `queryStop` around lines 1901–2224.

4. **WHAT:** Replace the duplicated desktop `<nav>` and mobile `<select>` definitions with one data-driven navigation model that renders both views. **WHY:** The same 18 tools are maintained twice (lines 655–674 and 677–740), which invites ordering, label, and destination drift. A single source also makes adding a feature safer. **Effort:** M. **Touches:** navigation markup lines 655–740 and `switchPanel` lines 1488–1510.

5. **WHAT:** Improve responsive navigation ergonomics: make the mobile selector sticky or keep the current tool visible near the panel heading, and add a skip link to `<main>`. **WHY:** At widths ≤860px the sidebar disappears (lines 548–553), while the selector is at the top of the container; after scrolling a long result, changing tools requires returning to the top. A skip link reduces keyboard traversal through repeated navigation. **Effort:** S. **Touches:** responsive CSS lines 543–574, navigation lines 655–742, and `<main>` at line 743.

6. **WHAT:** Persist and restore the selected panel (and synchronize `aria-current` on navigation buttons and the mobile selector). **WHY:** `switchPanel` toggles classes and desktop active state (lines 1488–1510), but a refresh resets the user to overview and the mobile select is not visibly synchronized when navigation happens through quick actions. This creates orientation loss. **Effort:** S. **Touches:** `switchPanel` lines 1488–1510 and quick-entry buttons lines 779–796.

7. **WHAT:** Add a common request timeout/cancellation strategy and stale-response guard for fetches. **WHY:** `apiFetch` is a thin `fetch` wrapper (lines 1711–1725); slow or abandoned requests can leave perpetual loading UI or allow an older response to overwrite a newer query. **Effort:** M. **Touches:** `apiFetch`/`callApi` lines 1711–1872 and all request callers.

8. **WHAT:** Move inline event attributes and feature rendering into modules/components, with one renderer per panel and a small shared API/state layer. **WHY:** The inline script spans lines 1486–2306 and mixes routing, storage, network calls, sanitization, rendering, timers, and event wiring. This makes unit testing and code review difficult and increases regression risk. **Effort:** L. **Touches:** the entire inline script and repeated `onclick`/`oninput` attributes throughout the document.

9. **WHAT:** Add a visible, non-color-only connection state and distinguish “configured,” “offline,” “request failed,” and “no data.” **WHY:** The header status at lines 648 and 2099–2104 communicates only short text; its green dot is CSS-only and the server health response includes configuration information that is not surfaced in the UI. Clearer states improve diagnosis without requiring console access. **Effort:** M. **Touches:** header status lines 648–650 and `refreshOverview` lines 2072–2111; optionally `/health` integration in `web_app.py` lines 123–139.

10. **WHAT:** Add automated accessibility and interaction checks for keyboard navigation, contrast in both themes, mobile breakpoints, and each panel’s idle/loading/empty/error states. **WHY:** The single-file surface has many repeated controls and conditional render paths; manual inspection will miss regressions. The current CSS has dark mode and focus rules (lines 72–89 and 575–636), but no visible test harness or invariant checks. **Effort:** M. **Touches:** new frontend test setup plus representative selectors in `static/index.html`.

## Quick wins (under 30 minutes each)

- Add `id`/`for` pairs to every visible form label and add `aria-label` to any remaining icon-only action.
- Add `<a class="skip-link" href="#main">跳至主要內容</a>` and `id="main"` to `<main>`.
- Mark the active navigation item with `aria-current="page"` in `switchPanel`, and update `#mobile-tool.value` there.
- Add `aria-live="polite"` to ordinary result boxes and `role="alert"` only for error containers; keep `aria-busy` true until the request settles.
- Disable each submit button during `query()` and restore it in `finally`; include a request timeout via `AbortSignal.timeout` with a fallback for unsupported browsers.
- Use `button` text plus a visually hidden status rather than relying on the spinner alone; respect the existing reduced-motion media rule.
- Add explicit `autocomplete="off"`/appropriate autocomplete values where browser autofill would be misleading, and `type="button"` to every non-submit action.

## Top 3 highest leverage

1. **Establish shared async state and accessibility announcements** (loading/empty/error/retry, busy/status, duplicate-submit prevention). This improves every tool without changing the visual design.
2. **Create one data-driven navigation and panel registry.** It removes the desktop/mobile duplication and gives routing, active state, recent queries, and quick actions one source of truth.
3. **Split the inline script into tested feature modules.** This is the largest maintainability investment and makes the first two improvements safer to extend across all 18 tools.
