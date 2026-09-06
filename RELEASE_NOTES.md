# Taiwan Assistant MCP 1.2.0

Released 2026-08-19.

This release turns the project into a deployable, verifiable web application while retaining the existing MCP and Gradio workflows.

Highlights:

- Responsive FastAPI dashboard for weather, transport, calendar, holidays, and exchange rates.
- New overview and health endpoints for frontend integration and operational checks.
- GitHub Pages + Render deployment path with documented configuration.
- CI and offline contract/security tests for repeatable validation.
- Portable startup and Windows-compatible dependency installation.
- Stronger request validation and OData input escaping.

Upgrade notes:

- The reported service version is now `1.2.0`.
- Existing MCP tool names and primary workflows remain compatible.
- Public GitHub Pages deployments should set `RENDER_API_BASE_URL` when the Render URL differs from the documented default.
- Google Calendar remains disabled in the public frontend because the current OAuth flow is local-only.

Validation: run `python -m unittest discover -s tests -p "test*.py" -v`.
