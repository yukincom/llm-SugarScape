import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from tools.benchmark_negotiation import WireRecorder, parameters, template_arguments
from llm_api import chat_completion_request


class FakeResponse:
    status = 200

    async def text(self):
        return '{"choices":[{"message":{"content":"Action: [Stay]"}}]}'

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class Session:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


class BenchmarkTests(unittest.TestCase):
    def test_reads_json_from_actual_ps_command_without_removing_quotes(self):
        command = 'python server.py --model example --chat-template-args {"enable_thinking":false,"preserve_thinking":false}'
        self.assertEqual(template_arguments(command), {"enable_thinking": False, "preserve_thinking": False})
        self.assertTrue(template_arguments(command.replace('"enable_thinking":false', '"enable_thinking":true'))["enable_thinking"])
        with self.assertRaises(ValueError):
            template_arguments('python server.py --model example')

    def test_capture_preserves_actual_payload_and_response(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wire.jsonl"
            wire = WireRecorder(path)
            baseline, captured = Session(), Session()
            options = dict(base_url="http://127.0.0.1:8080/v1", model="default_model",
                           messages=[{"role": "user", "content": "原文"}], temperature=0,
                           top_p=1, max_tokens=5000, reasoning_mode="off", reasoning_format="chat_template")
            async def exercise():
                async with chat_completion_request(baseline, **options) as response:
                    expected = await response.text()
                async with wire.request(captured, **options) as response:
                    self.assertEqual(await response.text(), expected)
            asyncio.run(exercise())
            self.assertEqual(captured.calls, baseline.calls)
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["request"], captured.calls[0][1]["json"])
            self.assertEqual(rows[0]["http_status"], 200)
            self.assertIn("Action: [Stay]", rows[0]["response_body"])
            self.assertNotIn("headers", rows[0])

    def test_preserves_fog_preset_and_generation_settings(self):
        config = parameters(43, Path("outputs/example"))
        self.assertEqual([config[k] for k in ("num_agents", "num_steps", "grid_size", "initial_energy",
                                             "spawn_energy_count", "view_range", "message_range")],
                         [4, 30, 15, 20, 2, 3, 7])
        self.assertEqual(config["seed"], 43)
        self.assertFalse(config["use_mbti"])
        self.assertEqual(config["custom_world_prompt"], "")
        self.assertEqual(config["temperature"], 0)
        self.assertEqual(config["top_p"], 1)
        self.assertEqual(config["max_tokens"], 5000)


if __name__ == "__main__":
    unittest.main()
