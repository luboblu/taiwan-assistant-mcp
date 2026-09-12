# Lane C — Operational Flow Review

Scope: zero-to-working path, MCP client registration, GitHub Pages + Render deploy path, CI
workflow, whether broad `except` handlers in `server.py` produce actionable errors, and the
known `tests/test_web_contract.py` cwd mutation. Read-only; no code changed. Repo at
`C:/Users/lubob/Desktop/taiwan-assistant-mcp`, branch `main` @ `a777c4a`.
`python -m unittest discover -s tests -p "test*.py"` → **38 tests, OK** (re-verified).

Already fixed and merged — not re-proposed here: Gradio removal, calendar-delete confirmation,
bus stop disambiguation, structured error envelope (`{status, error_code, source, fetched_at}`).

---

## 1. Zero-to-working path (new user, MCP client)

| # | Step | Friction |
|---|---|---|
| 1 | `pip install -r requirements.txt` | none |
| 2 | `cp .env.example .env` | none |
| 3 | Register CWA account, generate an "授權碼" (authorization code) | separate account #1 |
| 4 | Register TDX account, create an application, get Client ID/Secret | separate account #2 |
| 5 | Create a Google Cloud project, enable Calendar API, create a Desktop OAuth client, download `google_credentials.json` | separate account #3, most steps of the three |
| 6 | Edit `claude_desktop_config.json` by hand, pasting all five values into a JSON `env` block | manual JSON editing, no validation until first tool call |
| 7 | Restart Claude Desktop | — |
| 8 | First calendar tool call opens a browser for OAuth consent and writes `google_token.json` | **blocks the server process** — see §3.1 |
| 9 | If nothing was filled in correctly, the failure surfaces only when a tool is actually called, as a chat message from the LLM | no upfront config check — see §3.2 |

None of these steps is individually hard — README.md documents all three key registrations
clearly (290 lines, in Chinese, as numbered step lists) — but there is no single command
that confirms "you are ready" before a user starts asking the assistant questions.

---

## 2. Numbered improvements

1. **WHAT — Add a `--check-config` / `python -m server --check-config` doctor command that
   reports, per integration (CWA / TDX / Google), whether the required env vars or credential
   files are present, and for Google whether `google_token.json` exists and is not expired.**
   **WHY — Three independent registrations must all succeed before any tool fully works, and
   today the first signal of a misconfiguration is a tool-call error surfaced through the LLM
   conversation rather than a direct, actionable message at setup time.** Effort: S.
   File: `server.py` (new `if __name__ == "__main__":` branch, ~line 2230-end).

2. **WHAT — Run the Google OAuth `flow.run_local_server(port=0)` off the event loop (e.g.
   `asyncio.to_thread`), or fail fast with a clear message when no `google_token.json` exists
   yet, instead of blocking synchronously inside an `async def` MCP/HTTP handler.**
   **WHY — `_build_google_calendar_service` (server.py:958-983) is called directly, without
   an executor, from every calendar tool. On the very first calendar call (including via
   `web_app.py`'s `/api/overview?include_calendar=true`, `web_app.py:191-230`), it opens a
   local HTTP listener and a browser window and blocks until the user completes login in a
   separate window — during which the single-process FastAPI server cannot serve *any* other
   request, `/health` included.** Effort: S/M. File: `server.py:958-983`.

3. **WHAT — Give calendar tool errors the same structured `error_code` as CWA/TDX ones,
   instead of `INVALID_REQUEST` by default.** **WHY — `classify_result` (server.py:94-126)
   only recognizes the fixed CWA/TDX message table and two literal HTTP-status prefixes
   (`"Error: API 請求失敗"`, `"Error: 發生未預期的錯誤"`); every Google Calendar error message
   (server.py:1063-1064, 1164-1165, 1999-2000, 2043-2044, 2095-2096 — each its own inline
   `f"Error: ...：{e}"`) falls through to the generic `INVALID_REQUEST` code, so a dashboard
   or LLM cannot tell "you typed a bad event_id" apart from "Google's API is down" or "your
   OAuth scope is stale", even though the underlying `googleapiclient.errors.HttpError`
   carries a real status code.** Effort: S. Files: `server.py:94-126`, `server.py:1063,1164,1999,2043,2095`.

4. **WHAT — Stop swallowing failures in `get_weekly_town_list` — return a sentinel or raise,
   don't silently return `[]`.** **WHY — `server.py:1558-1583` has a bare
   `except Exception: return []` around the CWA weekly-dataset fetch used to populate the
   town-list dropdown for `weekly_forecast`; a CWA outage, bad API key, or malformed payload
   is indistinguishable from "this county genuinely has no towns in the dataset" — the one
   handler in the file with zero diagnostic trace.** Effort: S. File: `server.py:1558-1583`.

5. **WHAT — Add `tests/__init__.py`.** **WHY — CI's
   `python -m unittest discover -s tests -p "test*.py"` (`.github/workflows/ci.yml:20-21`)
   passes without it, but the two documented alternatives fail: plain `pytest` (no package
   root) and `python -m unittest tests.test_web_contract` (`tests` isn't an importable
   package). Anyone running tests the way most Python tooling defaults to gets a confusing
   collection error instead of the 38 passing tests.** Effort: S. File: new `tests/__init__.py`.

6. **WHAT — Isolate `tests/test_web_contract.py`'s process-wide `os.chdir` (server.py:958,
   test file lines 34-45) into a subprocess, or replace it with an explicit-path assertion
   instead of an actual directory change.** **WHY — `test_home_and_static_paths_are_independent_of_cwd`
   changes the process's current working directory for the whole Python process while it runs,
   restoring it in a `finally`. It is safe under the current sequential
   `unittest discover` run, but it is one `-j`/pytest-xdist flag or one future test-runner
   change away from corrupting a sibling test that resolves any relative path mid-run — a
   silent, hard-to-reproduce flake rather than a clean failure.** Effort: S.
   File: `tests/test_web_contract.py:34-45`.

7. **WHAT — Make the "offline" test run actually offline in CI, or mark it explicitly
   network-dependent.** **WHY — `import gradio` was removed from the app in 1.3.0, but if any
   test module (directly or via a transitive import) still pulls in a package that phones
   home on import, CI silently depends on network reachability it never declares. Re-verify
   this is fully gone post-Gradio-removal and, if a similar case appears again, gate it
   behind an explicit `RUN_NETWORK_TESTS` env flag.** Effort: S (verification) — confirmed
   clean in this pass; kept as a checklist item so it doesn't regress. File: `tests/`.

8. **WHAT — Reference `render.yaml`'s Google Calendar env vars (or their absence) explicitly
   in the Render deploy instructions, and add a one-line note that `GOOGLE_TOKEN_FILE` written
   to Render's ephemeral filesystem will not survive a redeploy.** **WHY — README.md:124-156
   already correctly disables Calendar for the public deployment, but `render.yaml` has no
   `GOOGLE_CREDENTIALS_FILE`/`GOOGLE_TOKEN_FILE` entries at all, so a user who ignores that
   guidance and sets Google credentials on Render would hit the interactive
   `flow.run_local_server(port=0)` browser flow (see #2) on a headless container with no way
   to open a browser — worth one explicit sentence to head off a confusing hang.** Effort: S.
   File: `README.md:124-140`, `render.yaml`.

---

## 3. Failure modes that give a bad error message today

3.1. **Server hangs, not errors, on first calendar call without a completed OAuth consent.**
     No error text at all — the request (and the whole process) just blocks until the user
     finds the browser window, or forever in a headless environment. See item 2.

3.2. **Missing/invalid `CWA_API_KEY` or TDX credentials surface only per-tool-call**, as
     whatever the upstream API returns mapped through `_handle_api_error` (server.py:129-146).
     This part *is* actionable (401 → "認證失敗，請確認 API 金鑰..."), just late — the user
     only discovers it after already asking the assistant a real question. See item 1.

3.3. **Every Google Calendar tool error looks like "INVALID_REQUEST" to a machine reader**
     even when it is actually an auth/scope/not-found problem from Google — see item 3.
     The *human-readable* text is fine (e.g. "請刪除 google_token.json 重新授權" appears in
     the docstrings), but nothing in the returned string or `classify_result` output lets a
     caller branch on it programmatically the way CWA/TDX errors already allow.

3.4. **A bad county/town combination in `weekly_forecast`'s town list returns an empty
     dropdown with no explanation** whether that's "this town isn't in the dataset" or
     "CWA is down right now" — see item 4.

3.5. **`tests/` cannot be run with `pytest` or `python -m unittest tests.<module>`** despite
     both being reasonable defaults a contributor would try first — see item 5. Not a runtime
     failure, but a real first-contribution friction point with a misleading error
     (`ModuleNotFoundError` / 0 tests collected) rather than a hint to use the documented command.

---

## 4. Top 3 highest leverage

1. **Don't block the whole server on first-run Google OAuth (item 2, S/M effort).** This is
   the one failure mode that isn't even an error — it's a silent hang affecting every other
   in-flight request, and it's one `asyncio.to_thread` call away from being fixed.
2. **Add a `--check-config` doctor command (item 1, S effort).** Directly shortens the
   three-registration onboarding path called out in the review brief; turns "call a tool and
   see what breaks" into "run one command and see what's missing" before the user starts.
3. **Extend structured error codes to Google Calendar tool failures (item 3, S effort).**
   Same shape of fix that already shipped for CWA/TDX (T-016); closes the one remaining gap
   in the error-envelope work so *all* five integrations are equally machine-readable.
