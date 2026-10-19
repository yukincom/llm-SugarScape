"""Exercise explicit generation controls through the actual decision request path."""

import json
from pathlib import Path
import tempfile
import unittest

from llm_api import chat_completion_request
from main import Simulation, check_connection, main
from test_simulation import Session, completion


class RequestControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_sampling_controls_are_independent_and_omit_keys(self):
        for temperature in (False, True):
            for top_p in (False, True):
                with self.subTest(temperature=temperature, top_p=top_p):
                    sim = Simulation(num_agents=1, spawn_energy_count=0, model="future-model",
                                     temperature=0.8, top_p=0.9,
                                     send_temperature=temperature, send_top_p=top_p)
                    session = Session(body=completion())
                    event = (await sim.step(session))["events"][0]
                    self.assertEqual(event["decision_status"], "ok")
                    payload = session.requests[0][1]["json"]
                    self.assertEqual("temperature" in payload, temperature)
                    self.assertEqual("top_p" in payload, top_p)
                    if temperature:
                        self.assertEqual(payload["temperature"], 0.8)
                    if top_p:
                        self.assertEqual(payload["top_p"], 0.9)
                    self.assertEqual(payload["model"], "future-model")
                    self.assertNotIn("reasoning_effort", payload)
                    self.assertNotIn("chat_template_kwargs", payload)

    async def test_probe_and_experiment_use_identical_reasoning_and_token_controls(self):
        cases = [("default", "openai", "medium", {}),
                 ("default", "chat_template", "medium", {}),
                 ("off", "openai", "high", {"reasoning_effort": "none"}),
                 ("off", "chat_template", "high", {"chat_template_kwargs": {"enable_thinking": False}})]
        cases += [("on", "openai", effort, {"reasoning_effort": effort})
                  for effort in ("minimal", "low", "medium", "high", "xhigh", "max")]
        cases += [("on", "chat_template", effort,
                   {"chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": effort}})
                  for effort in ("low", "medium", "xhigh")]
        for mode, protocol, effort, expected in cases:
            with self.subTest(mode=mode, protocol=protocol, effort=effort):
                config = {"model": "future-model", "send_temperature": False, "send_top_p": False,
                          "reasoning_mode": mode, "reasoning_format": protocol, "reasoning_effort": effort,
                          "max_tokens_parameter": "max_completion_tokens", "max_tokens": 1234}
                probe, run = Session(body=completion()), Session(body=completion())
                self.assertEqual((await check_connection(config, session=probe))["decision_status"], "ok")
                await Simulation(num_agents=1, spawn_energy_count=0, **config).step(run)
                for session in (probe, run):
                    self.assertEqual(len(session.requests), 1)
                    payload = session.requests[0][1]["json"]
                    self.assertEqual(payload["max_completion_tokens"], 1234)
                    for absent in ("max_tokens", "temperature", "top_p"):
                        self.assertNotIn(absent, payload)
                    self.assertEqual({key: payload[key] for key in ("reasoning_effort", "chat_template_kwargs")
                                      if key in payload}, expected)

    async def test_rejected_options_are_not_silently_retried_or_changed(self):
        session = Session(400, "unsupported parameter")
        result = await check_connection({"send_temperature": True, "reasoning_mode": "on"}, session=session)
        self.assertEqual(result["http_status"], 400)
        self.assertEqual(result["decision_source"], "fallback")
        self.assertEqual(len(session.requests), 1)
        self.assertIn("temperature", session.requests[0][1]["json"])
        self.assertEqual(session.requests[0][1]["json"]["reasoning_effort"], "medium")

    def test_invalid_controls_fail_before_http(self):
        for name, value in (("send_temperature", "false"), ("send_top_p", 0),
                            ("reasoning_mode", "auto"), ("reasoning_format", "unknown"),
                            ("reasoning_effort", "none"), ("max_tokens_parameter", "unknown")):
            with self.subTest(name=name):
                session = Session()
                with self.assertRaises(ValueError):
                    chat_completion_request(session, base_url="http://localhost/v1", model="any",
                                            messages=[], **{name: value})
                self.assertEqual(session.requests, [])

    async def test_saved_manifest_retains_selected_controls(self):
        options = {"send_temperature": False, "send_top_p": False, "reasoning_mode": "on",
                   "reasoning_format": "chat_template", "reasoning_effort": "xhigh",
                   "max_tokens_parameter": "max_completion_tokens"}
        with tempfile.TemporaryDirectory() as directory:
            result = await main(params={"output_dir": directory, "num_steps": 0, "mock_mode": True, **options})
            manifest = json.loads((Path(result["output_dir"]) / "manifest.json").read_text())
            for config in (manifest["config"], result["config"]):
                self.assertEqual({key: config[key] for key in options}, options)
