# Taiwan Assistant MCP 1.4.0

Released 2026-09-12.

This release is mostly about correctness: two bugs that produced confidently wrong or unavailable
behaviour, and a response format that lets callers tell failure from success.

Highlights:

- Bus arrival no longer returns the wrong stop for an ambiguous name. It now takes a stable
  `stop_id` and a `direction`, and returns candidate stops instead of guessing.
- One Google Calendar request no longer freezes the entire server. The OAuth flow and all Google
  API calls moved off the event loop.
- Responses carry `status`, `error_code`, `source` and `fetched_at` alongside `result`. A provider
  outage is now distinguishable from real content, and from a query that simply matched nothing.
- Google Calendar failures report a specific cause — missing credentials, authorisation needed,
  forbidden, not found — instead of one generic error.
- Ruff is enforced in CI at a pinned version, with every disabled rule justified in `ruff.toml`.

Upgrade notes:

- The response format is additive. `result` keeps its exact meaning, so existing callers and the
  bundled dashboard need no change.
- `tdx_get_bus_arrival` gained optional `stop_id` and `direction` parameters. Existing calls still
  work, but a `stop_name` that matches several stops now returns a candidate list rather than an
  answer — which is the point.
- The Gradio interface was removed in 1.3.0. The FastAPI dashboard is the only browser entry point.
