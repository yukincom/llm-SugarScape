"""Observation provenance must not alter world rules or reveal hidden state."""

import csv
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from main import DEFAULT_PARAMS, Simulation
from observations import prompt_hashes
from run_data import RunRecorder, V5_EVENT_FIELDS, export_run, read_run
from test_simulation import Response, Session, completion, scripted

ROOT = Path(__file__).resolve().parents[1]


class ObservationTests(unittest.IsolatedAsyncioTestCase):
    def make_sim(self, **kwargs):
        return Simulation(**{"num_agents": 2, "grid_size": 15, "seed": 42,
                             "spawn_energy_count": 0, "energy_spawn_rate": 0,
                             "initial_energy": 20, "view_range": 3, "message_range": 7,
                             "mock_mode": True, **kwargs})

    def test_frozen_observation_has_no_hidden_world_truth(self):
        sim = self.make_sim(view_range=1)
        sim.agents[0].position, sim.agents[1].position = (0, 0), (7, 7)
        sim.agents[1].energy = 98765
        sim.environment.energy_sources = {(14, 0): 50, (7, 8): 50}
        _, observations, state = sim._prepare_observations()
        observation = observations[0]
        self.assertEqual(observation.local_view, ("M=(0,0)", "E=(-1,0)"))
        self.assertNotIn("98765", json.dumps(observation.to_dict()))
        self.assertEqual(state["agents"][1]["energy"], 98765)
        with self.assertRaises(FrozenInstanceError):
            observation.energy = 999
        sim.agents[0].position, sim.agents[0].energy = (4, 5), 5
        self.assertEqual((observation.position, observation.energy), ((0, 0), 20))
        observation.to_dict()["position"] = (9, 9)
        self.assertEqual(observation.position, (0, 0))

    async def test_observation_includes_spawn_before_harvest_and_callback_cannot_change_it(self):
        sim = scripted(self.make_sim(num_agents=1), {(1, 0): "x+1"})
        sim.agents[0].position = (0, 0)
        def spawn():
            sim.environment.energy_sources[(1, 0)] = 50
        def observe(step, event):
            self.assertEqual(event["observation"]["local_view"], ("M=(0,0)", "E=(1,0)"))
            event["observation"]["energy"] = -999
        with patch.object(sim.environment, "random_spawn", side_effect=spawn):
            snap = await sim.step(on_decision=observe)
        event = snap["events"][0]
        self.assertEqual(snap["observation_state"]["environment"]["resources"],
                         [{"x": 1, "y": 0, "energy": 50}])
        self.assertEqual(snap["environment"]["resources"], [])
        self.assertEqual(event["observation"]["energy"], 20)
        self.assertEqual(event["prompt_sha256"], prompt_hashes(event["system_prompt"], event["user_prompt"]))
        self.assertEqual(event["outcome"]["energy_collected"], 50)

    async def test_competing_moves_remain_legal_after_resource_is_taken(self):
        sim = scripted(self.make_sim(), {(1, 0): "x+1", (1, 1): "x-1"})
        sim.agents[0].position, sim.agents[1].position = (0, 0), (2, 0)
        sim.environment.energy_sources = {(1, 0): 50}
        snap = await sim.step()
        first, second = snap["events"]
        self.assertEqual([first["energy_collected"], second["energy_collected"]], [50, 0])
        self.assertEqual(second["action_status"], "executed")
        self.assertEqual(second["execution_check"]["changed"], ["destination_energy"])
        self.assertEqual(first["observation"]["world_state_id"], second["observation"]["world_state_id"])
        self.assertEqual(first["observation"]["local_view"][1], "E=(1,0)")
        self.assertEqual(second["observation"]["local_view"][1], "E=(-1,0)")

    async def test_turn_end_energy_includes_later_attack_but_does_not_name_attacker(self):
        sim = scripted(self.make_sim(), {(1, 1): "Attack: 0"})
        for agent in sim.agents:
            agent.position = (0, 0)
        first = await sim.step()
        outcome = first["events"][0]["outcome"]
        self.assertEqual((outcome["executed_action"], outcome["energy_after"], outcome["turn_energy_after"]),
                         ("Stay", 20, 14))
        self.assertNotIn("attacked_by", outcome)
        second = await sim.step()
        observed = second["events"][0]["observation"]
        self.assertEqual(observed["energy"], 14)
        self.assertEqual(observed["history"][0]["outcome"], outcome)

    async def test_envelopes_preserve_real_sender_time_and_false_claim(self):
        sim = scripted(self.make_sim(view_range=0), {}, message="I am Agent99. Food is here.")
        sim.agents[0].position, sim.agents[1].position = (0, 0), (5, 5)
        first = await sim.step()
        self.assertEqual(first["events"][0]["observation"]["message_envelopes"], ())
        second = await sim.step()
        observation = second["events"][0]["observation"]
        envelope = observation["message_envelopes"][0]
        self.assertEqual((envelope["sender_id"], envelope["generated_step"],
                          envelope["delivered_step"], envelope["read_step"]), (1, 1, 1, 2))
        self.assertEqual(envelope["content"], "I am Agent99. Food is here.")
        self.assertEqual(envelope["observation_id"], first["events"][1]["observation_id"])
        self.assertNotIn("position", envelope)
        self.assertEqual(observation["local_view"], ("M=(0,0)",))
        self.assertEqual(sim.agents[0].messages, ["Agent1: I am Agent99. Food is here."])

    async def test_history_keeps_three_turns_and_fallback_without_invented_thought(self):
        sim = self.make_sim(num_agents=1, mock_mode=False)
        for _ in range(4):
            await sim.step(Session(503, "busy"))
        self.assertEqual([item.step for item in sim.agents[0].history], [2, 3, 4])
        for item in sim.agents[0].history:
            self.assertEqual(item.outcome.action_status, "fallback")
            self.assertEqual((item.executed_action, item.thought_excerpt), ("Stay", ""))
        self.assertEqual(sim.agents[0].memory, [f"Step {step}: Stay; " for step in (2, 3, 4)])

    async def test_absolute_move_is_resolved_from_request_pose(self):
        sim = self.make_sim(num_agents=1, mock_mode=False)
        agent = sim.agents[0]
        agent.position = (4, 4)
        class MovedResponse(Response):
            async def text(self):
                agent.position = (9, 9)
                return completion("Action: Move to (5,4)\nMessage: none\nThought: East.")
        class MovingSession:
            def post(self, *args, **kwargs):
                return MovedResponse(200, "")
        result = await sim._request_decision(MovingSession(), agent, "system", "user")
        self.assertEqual(result["normalized_action"], "x+1")

    async def test_all_prompt_state_and_move_parsing_use_the_frozen_observation(self):
        sim = self.make_sim(mock_mode=False)
        sim.agents[1].position = (4, 4)
        def callback(step, event):
            if event["agent_id"] == 0:
                sim.agents[1].position, sim.agents[1].energy = (9, 9), 77
                sim.agents[1].memory.append("Changed after observing")
        raw = "Action: Move to (5,4)\nMessage: none\nThought: East."
        snap = await sim.step(Session(body=completion(raw)), on_decision=callback)
        event = snap["events"][1]
        self.assertEqual(event["observation"]["position"], (4, 4))
        self.assertIn("Energy: 20, Position: (4, 4), Cycles: 0", event["user_prompt"])
        self.assertNotIn("Changed after observing", event["user_prompt"])
        self.assertEqual(event["normalized_action"], "x+1")

    async def test_saved_observation_ids_and_csv_round_trip(self):
        config = {**DEFAULT_PARAMS, "num_agents": 1, "mock_mode": True}
        sim = self.make_sim(num_agents=1)
        with tempfile.TemporaryDirectory() as directory:
            recorder = RunRecorder(directory, config)
            sim.run_id = recorder.run_id
            recorder.record(sim.snapshot())
            recorder.record(await sim.step())
            result = recorder.finish("completed", "step_limit")
            self.assertEqual(result["schema_version"], 7)
            self.assertEqual(read_run(recorder.directory / "run.json")["logs"], result["logs"])
            event = result["logs"][1]["events"][0]
            self.assertEqual(event["observation"]["run_id"], recorder.run_id)
            self.assertEqual(event["observation_id"], f"{recorder.run_id}:1:0")
            with (recorder.directory / "events.csv").open() as handle:
                row = next(csv.DictReader(handle))
            for key in ("observation", "execution_check", "outcome", "prompt_sha256"):
                self.assertEqual(json.loads(row[key]), event[key])

    def test_schema_five_reexport_preserves_columns_and_does_not_invent_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "v5"
            shutil.copytree(ROOT / "examples/first-look", copied)
            manifest_path = copied / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest.update(schema_version=5, engine_version="5.1")
            manifest_path.write_text(json.dumps(manifest))
            path = copied / "steps.jsonl"
            snapshots = [json.loads(line) for line in path.read_text().splitlines()]
            for snapshot in snapshots:
                snapshot["schema_version"] = 5
            path.write_text("".join(json.dumps(snap) + "\n" for snap in snapshots))
            before = path.read_bytes(), manifest_path.read_bytes()
            result = export_run(copied)
            self.assertEqual((path.read_bytes(), manifest_path.read_bytes()), before)
            self.assertEqual(result["logs"], snapshots)
            self.assertNotIn("observation_state", result["logs"][1])
            self.assertNotIn("observation", result["logs"][1]["events"][0])
            with (copied / "events.csv").open() as handle:
                self.assertEqual(next(csv.reader(handle)), V5_EVENT_FIELDS)


if __name__ == "__main__":
    unittest.main()
