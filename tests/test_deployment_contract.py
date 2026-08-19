import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.middleware.cors import CORSMiddleware

PROJECT_ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(PROJECT_ROOT))

import web_app  # noqa: E402


class DeploymentContractTests(unittest.TestCase):
    def test_cors_defaults_to_local_origins_without_credentials(self) -> None:
        cors = next(
            middleware
            for middleware in web_app.app.user_middleware
            if middleware.cls is CORSMiddleware
        )

        self.assertEqual(cors.kwargs["allow_origins"], web_app.CORS_ORIGINS)
        self.assertFalse(cors.kwargs["allow_credentials"])
        self.assertNotIn("*", cors.kwargs["allow_origins"])
        with patch.dict(os.environ, {"CORS_ORIGINS": ""}):
            self.assertEqual(
                web_app._load_cors_origins(), list(web_app.DEFAULT_CORS_ORIGINS)
            )
            self.assertTrue(
                all(
                    origin.startswith(("http://localhost", "http://127.0.0.1"))
                    for origin in web_app._load_cors_origins()
                )
            )

    def test_cors_origins_are_read_from_environment_and_wildcard_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"CORS_ORIGINS": "https://example.github.io, http://localhost:8000/"},
        ):
            self.assertEqual(
                web_app._load_cors_origins(),
                ["https://example.github.io", "http://localhost:8000"],
            )

        with patch.dict(os.environ, {"CORS_ORIGINS": "*"}):
            with self.assertRaises(ValueError):
                web_app._load_cors_origins()

    def test_render_blueprint_contains_free_web_service_settings(self) -> None:
        render_file = PROJECT_ROOT / "render.yaml"
        content = render_file.read_text(encoding="utf-8")

        for marker in (
            "runtime: python",
            "plan: free",
            "buildCommand: pip install -r requirements.txt",
            "--host 0.0.0.0",
            "--port $PORT",
            "healthCheckPath: /health",
        ):
            self.assertIn(marker, content)

        self.assertNotRegex(
            content,
            r"(?i)(api[_-]?key|client[_-]?secret|access[_-]?token|private[_-]?key)\s*:",
        )
        self.assertNotIn("CWA_API_KEY:", content)
        self.assertNotIn("TDX_CLIENT_SECRET:", content)
        self.assertNotIn("GOOGLE_CREDENTIALS_FILE:", content)

    def test_pages_workflow_injects_the_public_api_base(self) -> None:
        pages_file = PROJECT_ROOT / ".github" / "workflows" / "pages.yml"
        content = pages_file.read_text(encoding="utf-8")

        for marker in (
            "RENDER_API_BASE_URL",
            "window.PAGES_API_BASE",
            "upload-pages-artifact@v4",
            "path: ./site",
        ):
            self.assertIn(marker, content)


if __name__ == "__main__":
    unittest.main()
