import asyncio
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
import server
import web_app


class SecurityContractTests(unittest.TestCase):
    def test_odata_literals_are_escaped(self) -> None:
        self.assertEqual(web_app._escape_odata_string("O'Brien"), "O''Brien")

    def test_calendar_delete_requires_confirmation_in_gradio_adapter(self) -> None:
        with patch.object(app, "gcal_delete_event") as delete:
            result = asyncio.run(app.do_gcal_delete("event-1", "primary", False))

        self.assertIn("確認", result)
        delete.assert_not_called()

    def test_calendar_delete_fails_closed_when_preflight_fails(self) -> None:
        service = Mock()
        events = Mock()
        service.events.return_value = events
        events.get.return_value.execute.side_effect = RuntimeError("lookup failed")

        with patch.object(server, "_build_google_calendar_service", return_value=service):
            result = asyncio.run(
                server.gcal_delete_event(
                    server.GcalDeleteEventInput(event_id="event-1")
                )
            )

        self.assertIn("預檢", result)
        events.delete.assert_not_called()

    def test_frontend_contains_output_safety_guards(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("function escapeHtml", html)
        self.assertIn("function sanitizeMarkdown", html)
        self.assertIn("escapeHtml(r.route)", html)


if __name__ == "__main__":
    unittest.main()
