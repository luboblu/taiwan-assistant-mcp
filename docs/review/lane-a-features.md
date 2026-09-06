# Lane A — Functional Feature Review

The current server exposes 16 MCP tools across weather (forecast, observation, weekly), transit (bus routes/arrivals, TRA and THSR schedules), Google Calendar (list, event CRUD, free-time), public holidays, and Bank of Taiwan exchange rates. `app.py` is a Gradio wrapper around that same server surface, while `web_app.py` adds a dashboard-oriented overview endpoint and two bus-stop endpoints that are *not* MCP tools. This broadly matches the intent in `SPEC.md` and the 1.2.0 feature list in `CHANGELOG.md`, but the experience is still collection-of-lookups rather than a coherent Taiwan day-planning assistant: location/date disambiguation, transit stop discovery, actionable calendar safety, and machine-readable failures need attention.

## Concrete proposals

1. **WHAT — Expose bus-stop search and stop-arrival as first-class MCP tools, or move the shared implementation into `server.py`.**
   **WHY — The web API already has the useful stop-ID/district workflow, but an MCP client can only query a route and optional ambiguous stop name; the assistant cannot reliably answer “what arrives at this stop?”.** **Effort: M.** Touch: `web_app.py:460-618`, `server.py:402-584`.

2. **WHAT — Add a single transit journey/planning tool accepting origin, destination, departure/arrival time, mode preference, and accessibility preference.**
   **WHY — Bus, TRA, and THSR are separate lookup tools, with no way to compare modes, select a departure, or plan the first/last mile—the core intent of a Taiwan assistant.** **Effort: L.** Touch: `server.py:402-780`, `app.py:76-123`, `web_app.py:297-332`.

3. **WHAT — Make `tdx_get_bus_arrival` require a direction plus a stable stop identifier (or return a structured stop-selection step).**
   **WHY — `stop_name` is optional and only does substring filtering after an all-route request, so duplicate stop names and both directions can yield a plausible but wrong answer.** **Effort: M.** Touch: `server.py:410-415`, `server.py:543-581`.

4. **WHAT — Add nearest-station/nearby-stop and geocoding inputs (latitude/longitude or address) for weather and transit.**
   **WHY — Current weather needs a city or station name and transit needs city/route/station labels; visitors generally know where they are, not canonical provider names.** **Effort: L.** Touch: `server.py:123-135`, `server.py:402-437`, `server.py:1363-1386`.

5. **WHAT — Add CWA severe-weather alert and rainfall/radar-summary tools, with county/town filtering and freshness timestamps.**
   **WHY — Forecast, observation, and weekly outlook cover routine planning but omit the high-value “is it safe to travel now?” case during typhoons and heavy rain.** **Effort: M.** Touch: `server.py:123-307`, `server.py:1389-1480`.

6. **WHAT — Replace string-only error signalling at the HTTP boundary with a consistent `{status, result, error_code, source, fetched_at}` envelope and non-2xx validation/upstream errors where appropriate.**
   **WHY — Tool functions encode errors as ordinary strings and the web endpoints always wrap them in `{"result": ...}`; dashboard consumers can treat a provider failure as successful content.** **Effort: M.** Touch: `server.py:63-80`, `web_app.py:160-210`, `web_app.py:283-445`.

7. **WHAT — Add bounded response caching, stale-on-error metadata, and retry/backoff for CWA and read-only TDX schedule/route calls.**
   **WHY — Only the TDX OAuth token, holidays, and exchange rates are cached; forecasts, observations, route catalogues, and timetable fallbacks open new clients and refetch on each request, increasing latency and rate-limit risk.** **Effort: M.** Touch: `server.py:162-227`, `server.py:359-399`, `server.py:597-681`, `server.py:1363-1446`, `server.py:998-1031`, `server.py:1494-1565`.

8. **WHAT — Validate and normalize all schedule/calendar dates at the input-model boundary, including `start < end`, ISO-8601 timezone rules, and a bounded date horizon.**
   **WHY — TRA/THSR dates and Calendar create/update times are unconstrained strings; invalid or timezone-less values reach providers, producing late, provider-specific errors rather than actionable assistant guidance.** **Effort: S.** Touch: `server.py:418-437`, `server.py:1637-1654`, `server.py:1675-1703`.

9. **WHAT — Require an explicit `confirm_delete` field for the MCP calendar-delete tool and provide a preview/selection tool returning event ID, calendar, title, and time.**
   **WHY — Gradio has a confirmation gate, but `gcal_delete_event` itself accepts only IDs and executes deletion; the MCP contract relies on prose rather than a machine-enforced confirmation.** **Effort: S.** Touch: `app.py:217-227`, `server.py:1706-1710`, `server.py:1827-1865`.

10. **WHAT — Add a calendar availability planner that can propose slots with travel buffers and optionally create only after confirmation.**
    **WHY — Free-time search identifies gaps, while calendar creation is separate; no tool turns a natural request such as “find an hour after my train arrives” into a safe, reviewable proposal.** **Effort: L.** Touch: `server.py:1713-1724`, `server.py:1750-1824`, `server.py:1873-1915`.

11. **WHAT — Tighten tool descriptions and parameter vocabulary with accepted city/station aliases, timezone/default-date behavior, provider coverage, and examples in every MCP-visible input field.**
    **WHY — Required labels such as `city`, `origin`, `destination`, `route_name`, and `station_name` have inconsistent canonicalization and sparse disambiguation, increasing avoidable LLM tool-call failures.** **Effort: S.** Touch: `server.py:123-135`, `server.py:402-437`, `server.py:839-849`, `server.py:1389-1395`, `server.py:1569-1574`.

## Top 3 highest leverage

1. **Expose stop search/arrival to MCP and use stable stop IDs/direction (M).** It closes the clearest capability mismatch and makes live bus answers dependable.
2. **Introduce structured HTTP/tool error status plus cache/retry behaviour (M).** It prevents silent-looking outages and improves responsiveness without adding a new provider.
3. **Build a unified journey planner (L).** It converts isolated transport lookups into the primary user outcome: choosing how to get somewhere in Taiwan.

## Evidence reviewed

- `SPEC.md` — stated weather, transport, calendar, holiday, and exchange-rate scope plus web/API requirements.
- `CHANGELOG.md` (1.2.0) — dashboard/API additions and existing security/validation work, deliberately not re-proposed here.
- `server.py`, `app.py`, and `web_app.py` — static source review only; Python execution was intentionally not attempted per task instructions.
