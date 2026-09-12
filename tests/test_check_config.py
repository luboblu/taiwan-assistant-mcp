"""--check-config 設定檢查契約：只回報有/沒有/是否可用，絕不印出金鑰或權杖內容。"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import httpx  # noqa: E402

import server  # noqa: E402


class _FakeAsyncClient:
    """最小可用的 httpx.AsyncClient 替身，只支援 GET，回傳固定 status_code。"""

    def __init__(self, status_code=None, exc=None):
        self._status_code = status_code
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        return False

    async def get(self, url, params=None, timeout=None):
        if self._exc is not None:
            raise self._exc
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(self._status_code, request=request)


class CwaCredentialCheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_env_var_is_reported_as_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CWA_API_KEY", None)
            status, detail = await server._check_cwa_credential()
        self.assertEqual(status, "missing")
        self.assertIn("CWA_API_KEY", detail)

    async def test_valid_key_reports_ok(self) -> None:
        with patch.dict(os.environ, {"CWA_API_KEY": "secret-key"}):
            with patch.object(server.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(200)):
                status, detail = await server._check_cwa_credential()
        self.assertEqual(status, "ok")
        self.assertNotIn("secret-key", detail)

    async def test_401_reports_invalid_without_leaking_the_key(self) -> None:
        with patch.dict(os.environ, {"CWA_API_KEY": "secret-key"}):
            with patch.object(server.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(401)):
                status, detail = await server._check_cwa_credential()
        self.assertEqual(status, "invalid")
        self.assertNotIn("secret-key", detail)

    async def test_network_error_reports_unknown_not_invalid(self) -> None:
        with patch.dict(os.environ, {"CWA_API_KEY": "secret-key"}):
            exc = httpx.ConnectError("boom")
            with patch.object(server.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(exc=exc)):
                status, _detail = await server._check_cwa_credential()
        self.assertEqual(status, "unknown")


class TdxCredentialCheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_env_vars_are_named_individually(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TDX_CLIENT_ID", None)
            os.environ.pop("TDX_CLIENT_SECRET", None)
            status, detail = await server._check_tdx_credential()
        self.assertEqual(status, "missing")
        self.assertIn("TDX_CLIENT_ID", detail)
        self.assertIn("TDX_CLIENT_SECRET", detail)

    async def test_token_fetch_success_reports_ok(self) -> None:
        with patch.dict(os.environ, {"TDX_CLIENT_ID": "id", "TDX_CLIENT_SECRET": "secret"}):
            with patch.object(server, "_get_tdx_token", new=AsyncMock(return_value="tok")):
                status, detail = await server._check_tdx_credential()
        self.assertEqual(status, "ok")
        self.assertNotIn("secret", detail)

    async def test_401_reports_invalid_without_leaking_the_secret(self) -> None:
        request = httpx.Request("POST", server.TDX_AUTH_URL)
        error = httpx.HTTPStatusError(
            "unauthorized", request=request, response=httpx.Response(401, request=request)
        )
        with patch.dict(os.environ, {"TDX_CLIENT_ID": "id", "TDX_CLIENT_SECRET": "secret"}):
            with patch.object(server, "_get_tdx_token", new=AsyncMock(side_effect=error)):
                status, detail = await server._check_tdx_credential()
        self.assertEqual(status, "invalid")
        self.assertNotIn("secret", detail)

    async def test_network_error_reports_unknown(self) -> None:
        with patch.dict(os.environ, {"TDX_CLIENT_ID": "id", "TDX_CLIENT_SECRET": "secret"}):
            with patch.object(
                server, "_get_tdx_token", new=AsyncMock(side_effect=httpx.ConnectError("boom"))
            ):
                status, _detail = await server._check_tdx_credential()
        self.assertEqual(status, "unknown")


class GoogleCredentialCheckTests(unittest.TestCase):
    def test_missing_credentials_file_is_reported_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            creds = os.path.join(tmp, "no_creds.json")
            token = os.path.join(tmp, "no_token.json")
            with patch.dict(
                os.environ, {"GOOGLE_CREDENTIALS_FILE": creds, "GOOGLE_TOKEN_FILE": token}
            ):
                status, _detail = server._check_google_credential()
        self.assertEqual(status, "missing")

    def test_credentials_without_token_is_pending_not_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            creds = os.path.join(tmp, "creds.json")
            token = os.path.join(tmp, "no_token.json")
            Path(creds).write_text("{}", encoding="utf-8")
            with patch.dict(
                os.environ, {"GOOGLE_CREDENTIALS_FILE": creds, "GOOGLE_TOKEN_FILE": token}
            ):
                status, _detail = server._check_google_credential()
        self.assertEqual(status, "pending")

    def test_both_files_present_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            creds = os.path.join(tmp, "creds.json")
            token = os.path.join(tmp, "token.json")
            Path(creds).write_text("{}", encoding="utf-8")
            Path(token).write_text("{}", encoding="utf-8")
            with patch.dict(
                os.environ, {"GOOGLE_CREDENTIALS_FILE": creds, "GOOGLE_TOKEN_FILE": token}
            ):
                status, _detail = server._check_google_credential()
        self.assertEqual(status, "ok")

    def test_never_reads_or_reports_file_contents(self) -> None:
        """檢查函式必須只看檔案存不存在，不能讀取/回報其內容（哪怕內容看起來像洩漏的憑證）。"""
        with tempfile.TemporaryDirectory() as tmp:
            creds = os.path.join(tmp, "creds.json")
            token = os.path.join(tmp, "token.json")
            Path(creds).write_text('{"secret": "do-not-print-me"}', encoding="utf-8")
            Path(token).write_text('{"refresh_token": "do-not-print-me-either"}', encoding="utf-8")
            with patch.dict(
                os.environ, {"GOOGLE_CREDENTIALS_FILE": creds, "GOOGLE_TOKEN_FILE": token}
            ):
                _status, detail = server._check_google_credential()
        self.assertNotIn("do-not-print-me", detail)
        self.assertNotIn("do-not-print-me-either", detail)


class RunCheckConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_ok_is_ready_and_never_prints_the_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            creds = os.path.join(tmp, "creds.json")
            token = os.path.join(tmp, "token.json")
            Path(creds).write_text("{}", encoding="utf-8")
            Path(token).write_text("{}", encoding="utf-8")
            env = {
                "CWA_API_KEY": "top-secret-cwa-key",
                "TDX_CLIENT_ID": "top-secret-tdx-id",
                "TDX_CLIENT_SECRET": "top-secret-tdx-secret",
                "GOOGLE_CREDENTIALS_FILE": creds,
                "GOOGLE_TOKEN_FILE": token,
            }
            with patch.dict(os.environ, env):
                with patch.object(server.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(200)):
                    with patch.object(
                        server, "_get_tdx_token", new=AsyncMock(return_value="tok-should-not-appear")
                    ):
                        buf = io.StringIO()
                        with redirect_stdout(buf):
                            ready = await server._run_check_config()
        output = buf.getvalue()
        self.assertTrue(ready)
        for secret in (
            "top-secret-cwa-key",
            "top-secret-tdx-id",
            "top-secret-tdx-secret",
            "tok-should-not-appear",
        ):
            self.assertNotIn(secret, output)

    async def test_missing_google_credentials_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_creds = os.path.join(tmp, "nope.json")
            env = {
                "CWA_API_KEY": "key",
                "TDX_CLIENT_ID": "id",
                "TDX_CLIENT_SECRET": "secret",
                "GOOGLE_CREDENTIALS_FILE": missing_creds,
                "GOOGLE_TOKEN_FILE": os.path.join(tmp, "token.json"),
            }
            with patch.dict(os.environ, env):
                with patch.object(server.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(200)):
                    with patch.object(server, "_get_tdx_token", new=AsyncMock(return_value="tok")):
                        buf = io.StringIO()
                        with redirect_stdout(buf):
                            ready = await server._run_check_config()
        self.assertFalse(ready)

    async def test_pending_google_auth_still_counts_as_ready(self) -> None:
        """憑證檔案已就緒但尚未跑過 OAuth，不應視為失敗——首次使用時才會觸發授權。"""
        with tempfile.TemporaryDirectory() as tmp:
            creds = os.path.join(tmp, "creds.json")
            Path(creds).write_text("{}", encoding="utf-8")
            env = {
                "CWA_API_KEY": "key",
                "TDX_CLIENT_ID": "id",
                "TDX_CLIENT_SECRET": "secret",
                "GOOGLE_CREDENTIALS_FILE": creds,
                "GOOGLE_TOKEN_FILE": os.path.join(tmp, "no_token_yet.json"),
            }
            with patch.dict(os.environ, env):
                with patch.object(server.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(200)):
                    with patch.object(server, "_get_tdx_token", new=AsyncMock(return_value="tok")):
                        buf = io.StringIO()
                        with redirect_stdout(buf):
                            ready = await server._run_check_config()
        self.assertTrue(ready)


if __name__ == "__main__":
    unittest.main()
