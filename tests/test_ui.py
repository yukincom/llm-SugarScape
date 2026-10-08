"""Exercise the real Streamlit entry point without a browser or an LLM server."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import aiohttp
from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parents[1] / "main.py"


def widget(elements, label):
    return next(element for element in elements if element.label == label)


class StreamlitTests(unittest.TestCase):
    def setUp(self):
        # AppTest inherits the test runner's argv; match `streamlit run main.py`.
        argv = patch.object(sys, "argv", [str(APP_PATH)])
        argv.start()
        self.addCleanup(argv.stop)

    def test_mock_run_exports_and_survives_widget_rerun(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(aiohttp.ClientSession, "_request") as request:
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(widget(app.selectbox, "Connection").value, "Local LLM (8080)")
            self.assertEqual(widget(app.text_input, "Model").value, "default_model")
            self.assertTrue(widget(app.text_input, "Model").disabled)
            widget(app.selectbox, "Connection").select("Mock (no API)").run()
            widget(app.slider, "Num Agents").set_value(3)
            widget(app.number_input, "Num Steps").set_value(2)
            widget(app.text_input, "Output directory").set_value(directory)
            widget(app.button, "Run Simulation").click().run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            result = app.session_state["result"]
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["summary"]["total_actions"], 6)
            self.assertEqual(len(app.success), 1)
            for filename in ("steps.csv", "agents.csv", "events.csv", "run.json"):
                self.assertTrue((Path(result["output_dir"]) / filename).is_file())
            widget(app.checkbox, "Use MBTI").uncheck().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state["result"]["run_id"], result["run_id"])
            self.assertEqual(len(app.success), 1)
            request.assert_not_called()

    def test_connection_failure_is_not_shown_as_success(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
                aiohttp.ClientSession, "_request", side_effect=aiohttp.ClientConnectionError("test failure")):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            widget(app.slider, "Num Agents").set_value(2)
            widget(app.number_input, "Num Steps").set_value(1)
            widget(app.text_input, "Output directory").set_value(directory)
            widget(app.button, "Run Simulation").click().run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.success), 0)
            self.assertIn("completed_with_errors", app.warning[0].value)
            self.assertEqual(app.session_state["result"]["summary"]["llm_errors"], 2)


if __name__ == "__main__":
    unittest.main()
