# Changelog

All notable changes to this project are documented here.

## [1.4.0] - 2026-09-12

### Fixed

- Bus arrival no longer answers with the wrong stop. `stop_name` was matched as a substring across
  both directions, so asking for 中山 on a route serving 中山國小 and 中山國中 returned both as
  though either were the stop meant. Added a stable `stop_id` and a `direction` filter, made an
  exact name match win over a substring one, and made an ambiguous name return the candidate stops
  with their ids instead of picking one. Every result line now carries its `stop_id`.
- A single Google Calendar request no longer freezes the whole server. The OAuth flow and all
  thirteen `googleapiclient` `.execute()` calls ran directly on the event loop, so on first use the
  service stopped answering any request — health, weather, transit — until the browser sign-in
  completed, or indefinitely if nobody was there. They now run on a worker thread.

### Added

- Responses carry `status`, `error_code`, `source` and `fetched_at` alongside `result`, so a caller
  can tell a provider outage from real content. `status` is `ok`, `empty` for a query that matched
  nothing, or `error` with a specific code. `result` is unchanged, so existing callers are
  unaffected.
- Google Calendar failures have their own codes rather than a generic one:
  `CALENDAR_CREDENTIALS_MISSING`, `CALENDAR_AUTH_REQUIRED`, `CALENDAR_FORBIDDEN`,
  `CALENDAR_NOT_FOUND`, `CALENDAR_ERROR`, and `CALENDAR_PREFLIGHT_FAILED` for the fail-closed
  delete path where nothing was deleted.
- `ruff.toml`, with the rules this project wants and a written reason for each one that is off.
  Ruff is enforced in CI at a pinned version.
- `docs/review/` — feature, interface and workflow reviews of the project.
- `tests/__init__.py`, so `python -m unittest tests.<module>` works and not only discovery.

### Changed

- Test suite grew from 20 to 48 tests, covering stop disambiguation, response classification,
  calendar error codes and the event-loop guarantee.

## [1.3.0] - 2026-09-06

### Removed

- Removed the legacy Gradio interface (`app.py`) and the `gradio` dependency. The FastAPI
  dashboard is now the only browser entry point; it already exposed a superset of the Gradio
  tools, including bus stop search and stop arrival.

### Security

- Moved the calendar delete confirmation gate out of the Gradio adapter and into the web API.
  `POST /api/calendar/delete` now requires `confirm_delete: true` and fails closed without it,
  so the guard no longer depends on the removed interface.

### Added

- Added dark mode to the dashboard, following the system setting with a manual toggle persisted
  in `localStorage`.
- Added Subresource Integrity to the marked.js CDN script.
- Added loading skeletons, a visible keyboard focus ring, `aria-controls`/`role="region"`
  wiring between the sidebar and panels, and `prefers-reduced-motion` support.

### Changed

- Rebuilt the dashboard stylesheet as a token-based design system with four responsive
  breakpoints. Markup and API wiring are unchanged.

### Fixed

- Fixed the sidebar active state not syncing when switching tools from the mobile dropdown.
- Fixed the quick-action buttons rendering their title and subtitle on a single line.

## [1.2.0] - 2026-08-19

### Added

- Added a FastAPI dashboard with overview, weather, transport, calendar, holiday, and exchange-rate views.
- Added `/health` and `/api/overview` endpoints, with resilient partial-failure handling for summary cards.
- Added offline contract, security, overview, and deployment tests plus continuous integration.
- Added Spec-Driven Development documentation in `SPEC.md` and `UI_SPEC.md`.
- Added free deployment configuration for Render and GitHub Pages, including API URL injection and deployment documentation.

### Changed

- Made startup paths portable when launched outside the repository root.
- Made requirements installation compatible with Windows environments.
- Standardized request validation and preserved the `{"result": "..."}` response contract.

### Security

- Escaped user input used in TDX OData filters.
- Kept health checks free of external API calls and secret contents.
- Added frontend output escaping and explicit safeguards around calendar deletion and OAuth usage.

## [1.1.0]

Initial tracked feature release. See the repository history for the original MCP weather, transport, calendar, holiday, and exchange-rate integrations.
