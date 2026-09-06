# Changelog

All notable changes to this project are documented here.

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
