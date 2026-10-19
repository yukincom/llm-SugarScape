"""Offline review uses the exact next-turn input path and never contacts a model."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from main import Simulation, cli, main, preview_prompts
from paper_prompts import PROMPT_FACTORS
from test_simulation import scripted


class PromptPreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_is_pure_and_matches_next_turn_with_spawn_and_history(self):
        representations = [tuple(name for name in PROMPT_FACTORS if name not in excluded)
                           for excluded in (("spatial_relations", "self_other_identity"),
                                            ("relative_coordinates",))]
        for spawn, factors in itertools.product((0, 1), representations):
            with self.subTest(spawn=spawn, factors=factors):
                sim = scripted(Simulation(num_agents=2, seed=42, energy_spawn_rate=spawn,
                                          spawn_energy_count=0, mock_mode=True,
                                          prompt_factors=factors), {}, message="prior report")
                await sim.step(object())
                before = deepcopy(sim.snapshot())
                rng, np_rng = sim.rng.getstate(), deepcopy(sim.np_rng.bit_generator.state)
                histories = [tuple(agent.history) for agent in sim.agents]
                envelopes = [tuple(agent.next_message_envelopes) for agent in sim.agents]
                with patch("main.aiohttp.ClientSession", side_effect=AssertionError("HTTP not allowed")):
                    preview = sim.preview_next_prompts()
                self.assertEqual(sim.snapshot(), before)
                self.assertEqual(sim.rng.getstate(), rng)
                self.assertEqual(sim.np_rng.bit_generator.state, np_rng)
                self.assertEqual([tuple(agent.history) for agent in sim.agents], histories)
                self.assertEqual([tuple(agent.next_message_envelopes) for agent in sim.agents], envelopes)
                self.assertEqual(sim.preview_next_prompts(), preview)
                actual = await sim.step(object())
                self.assertEqual(preview["step"], actual["step"])
                for packet, event in zip(preview["agents"], actual["events"]):
                    for field in ("system_prompt", "user_prompt", "observation", "prompt_sha256"):
                        self.assertEqual(packet[field], event[field])

    def test_first_preview_never_initializes_http_identity_or_recorder(self):
        with ExitStack() as stack:
            for name in ("aiohttp.ClientSession", "ModelIdentity.capture", "ensure_server_reachable", "RunRecorder"):
                stack.enter_context(patch("main." + name, side_effect=AssertionError("offline only")))
            result = preview_prompts({"api_key": "secret-preview-key", "prompt_factors": ["action_last"],
                                      "seed": 42, "num_agents": 2, "custom_world_prompt": "Review world."})
        self.assertEqual((result["kind"], result["llm_calls"], result["step"]), ("prompt_preview", 0, 1))
        self.assertEqual(len(result["agents"]), 2)
        self.assertNotIn("secret-preview-key", json.dumps(result))
        self.assertEqual(result["protocol"]["prompt_factors"]["enabled"], ["action_last"])
        self.assertTrue(result["agents"][0]["system_prompt"].startswith("Review world."))

    def test_cli_saves_preview_without_running_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            arguments = ["main.py", "run", "--preview-prompts", str(path), "--seed", "42",
                         "--agents", "2", "--view-range", "3", "--message-range", "7",
                         "--prompt-factor", "grounded_thought", "--prompt-factor", "action_last",
                         "--prompt-factor", "spatial_relations", "--prompt-factor", "self_other_identity"]
            with patch("sys.argv", arguments), patch("main.main", side_effect=AssertionError("no run")), \
                    patch("main.aiohttp.ClientSession", side_effect=AssertionError("no HTTP")), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(cli(), 0)
                saved = path.read_bytes()
                with self.assertRaises(SystemExit) as raised:
                    cli()
                self.assertEqual(raised.exception.code, 2)
                self.assertEqual(path.read_bytes(), saved)
            config = json.loads(saved)["config"]
            self.assertEqual(config["prompt_factors"], ["action_last", "grounded_thought", "spatial_relations", "self_other_identity"])
            self.assertEqual((config["view_range"], config["message_range"]), (3, 7))
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_invalid_configuration_is_rejected_offline(self):
        with patch("main.aiohttp.ClientSession", side_effect=AssertionError("no HTTP")):
            for params in ({"prompt_factors": ["unknown"]}, {"seed": -1}, {"num_steps": -1},
                           {"prompt_factors": ["relative_coordinates", "spatial_relations"]},
                           {"prompt_factors": ["relative_coordinates", "self_other_identity"]},
                           {"unknown": True}):
                with self.subTest(params=params), self.assertRaises(ValueError):
                    preview_prompts(params)

    async def test_main_records_selected_factors_and_matches_first_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {"output_dir": directory, "num_agents": 1, "num_steps": 1, "seed": 42,
                      "mock_mode": True, "prompt_factors": ["provenance", "action_last", "spatial_relations", "self_other_identity"]}
            preview = preview_prompts(config)
            with redirect_stdout(io.StringIO()):
                result = await main(params=config)
            run = Path(result["output_dir"])
            manifest = json.loads((run / "manifest.json").read_text())
            records = [json.loads(line) for line in (run / "steps.jsonl").read_text().splitlines()]
            self.assertEqual(manifest["protocol"]["prompt_factors"]["enabled"], config["prompt_factors"])
            self.assertEqual(manifest["config"]["prompt_factors"], config["prompt_factors"])
            self.assertEqual(manifest["protocol"]["spatial_relations"], preview["protocol"]["spatial_relations"])
            self.assertEqual(manifest["protocol"]["self_other_identity"], preview["protocol"]["self_other_identity"])
            for field in ("system_prompt", "user_prompt", "prompt_sha256"):
                self.assertEqual(records[-1]["events"][0][field], preview["agents"][0][field])


if __name__ == "__main__":
    unittest.main()
