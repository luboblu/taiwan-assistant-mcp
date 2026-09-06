# taiwan-assistant-mcp — 優化總結 (god synthesis, 2026-09-06)

Sources: `lane-a-features.md` (MinYuhDay, 11 proposals), god's own inspection of
`static/index.html`, `README.md`, `.github/workflows/ci.yml`, and a live test run.

## Verified health baseline
- `python -m unittest discover -s tests -p "test*.py"` → **20 tests, OK**. This retro-validates
  the 1.2.0 release that was prepared without a test run.
- Secrets hygiene is **correct**: `google_credentials.json`, `google_token.json`, `.env` are all
  gitignored and untracked; only `.env.example` is committed.
- Frontend XSS handling is **good**: `escapeHtml()` is applied consistently at interpolation
  sites, and `sanitizeMarkdown()` runs marked.js output through a tag/attribute/URL allowlist.

## Priority 1 — correctness & trust
1. **Structured error envelope** `{status, result, error_code, source, fetched_at}` (Lane A #6, M).
   Today tool errors are plain strings and web endpoints always wrap them in `{"result": ...}`,
   so a provider outage is indistinguishable from real content. The frontend confirms the
   damage: every failure collapses to `HTTP ${res.status}` or 「無法連接後端伺服器」.
2. **Bus arrival needs a stable stop ID + direction** (Lane A #3, M). `stop_name` is optional and
   substring-filtered after an all-route fetch — duplicate stop names and both directions can
   return a plausible but wrong answer. This is the worst failure mode: silently incorrect.
3. **Validate dates at the input boundary** (Lane A #8, S) — `start < end`, ISO-8601 tz rules,
   bounded horizon. Cheapest item with real payoff.
4. **`confirm_delete` on the MCP calendar-delete tool** (Lane A #9, S). Gradio has a confirmation
   gate; the MCP contract relies on prose. An LLM can delete an event with no machine-enforced check.

## Priority 2 — capability
5. **Expose bus-stop search/arrival as MCP tools** (Lane A #1, M) — the useful stop-ID workflow
   exists in `web_app.py` but MCP clients cannot reach it.
6. **Caching + retry/backoff for CWA and TDX reads** (Lane A #7, M) — only OAuth tokens, holidays
   and FX are cached; forecasts and timetables refetch every call.
7. **Severe-weather / typhoon alert tool** (Lane A #5, M) — the highest-value Taiwan question
   ("is it safe to travel now?") is the one gap.
8. **Unified journey planner** (Lane A #2, L) — turns isolated lookups into the actual outcome.
9. **Geocoding / nearest-stop input** (Lane A #4, L) — visitors know where they are, not canonical
   provider station names.

## Priority 3 — UI (`static/index.html`, 1942 lines, one inline script)
10. **Accessibility floor (S, quick win).** `role=` 0 occurrences, `tabindex` 0, `alt=` 0 across
    44 buttons and 46 inputs. 58 `<label>`s and 14 `aria-` uses are a good start — add roles on
    the tab/panel structure, `alt` on icons, and a visible focus ring.
11. **Dark mode (S, quick win).** No `prefers-color-scheme` block at all, but the palette is
    already CSS custom properties on `:root` — this is a ~20-line change.
12. **Responsive coverage is thin (M).** Only 2 media queries for a 46-input dashboard.
13. **Pin the CDN dependency (S, quick win).** `marked@12.0.2` loads from jsdelivr with
    `crossorigin` but **no `integrity` hash** — add SRI, or vendor it locally.
14. **Split the inline script (L).** One 1942-line file holds all markup, CSS and JS.

## Priority 4 — flow & tooling
15. **Onboarding is 3 separate key registrations** (CWA, TDX, Google OAuth) before anything works.
    README covers them well across 294 lines, but a `python -m server --check-config` doctor
    command that reports which of the three are present/valid would cut the drop-off.
16. **`tests/` has no `__init__.py`.** CI's `unittest discover -s tests` works, but the documented
    `python -m unittest tests.test_x` and plain `pytest` both fail. Add the file or fix the docs.
17. **The "offline unit tests" are not offline** — gradio phones home to `api.gradio.app` on
    import during the run. Flaky/slow in a sandboxed CI.
18. **Deduplicate `_escape_odata_string`** — identical in `server.py` and `web_app.py` (Pam).
19. **Test depth is thin** — 20 contract tests for ~5,300 lines, no provider-failure simulation.
