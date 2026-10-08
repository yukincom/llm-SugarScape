import asyncio
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import aiohttp

from main import Environment, Simulation, main, parse_response
from run_data import collect_runs, export_run


def scripted(sim, actions):
    async def decide(session, agent, system_prompt, user_prompt):
        text = actions.get((sim.step_count, agent.id), "Stay")
        return {"agent_id": agent.id, "decision_source": "mock", "decision_status": "ok",
                "error_kind": "", "reason": "", "raw_response": f"Action: [{text}]",
                "system_prompt": system_prompt, "user_prompt": user_prompt,
                **parse_response(f"Action: [{text}]\nMessage: [hello from {agent.id}]\nThought: [test]")}
    sim._request_decision = decide
    return sim


class SimulationTests(unittest.IsolatedAsyncioTestCase):
    def make_sim(self, **params):
        return Simulation(**{"num_agents": 2, "seed": 42, "spawn_energy_count": 0,
                             "energy_spawn_rate": 0, "mock_mode": True, **params})

    async def test_birth_death_denominator_and_lineage(self):
        sim = scripted(self.make_sim(initial_energy=4, reproduce_cost=2, child_initial_energy=1),
                       {(1, 0): "Reproduce"})
        first = await sim.step()
        second = await sim.step()
        self.assertEqual(first["summary"]["alive"], 3)
        self.assertEqual(second["summary"]["total_actions"], 5)
        self.assertEqual(second["summary"]["repro_rate"], 1 / 5)
        self.assertEqual(sim.agents[2].parent, sim.agents[0])
        self.assertEqual(sim.agents[0].descendants, [sim.agents[2]])
        self.assertEqual(sim.agents[2].death_step, 2)
        self.assertEqual(len(second["agents"]), 3)
        for snap in (first, second):
            summary = snap["summary"]
            self.assertEqual(summary["alive"], 2 + summary["total_born"] - summary["total_died"])
            self.assertEqual(len(snap["events"]), snap["alive_start"])
            self.assertEqual(summary["alive"], snap["alive_start"] + snap["step_stats"]["total_born"] - snap["step_stats"]["total_died"])

    async def test_extinction_keeps_historical_rate(self):
        sim = scripted(self.make_sim(num_agents=1, initial_energy=2, reproduce_cost=2, child_initial_energy=1),
                       {(1, 0): "Reproduce"})
        await sim.step()
        await sim.step()
        summary = sim.get_summary()
        self.assertEqual(summary["alive"], 0)
        self.assertEqual(summary["total_died"], 2)
        self.assertEqual(summary["repro_rate"], 0.5)

    async def test_population_cap_checked_after_each_birth(self):
        sim = scripted(self.make_sim(population_cap=3), {(1, 0): "Reproduce", (1, 1): "Reproduce"})
        snapshot = await sim.step()
        self.assertEqual(snapshot["summary"]["alive"], 3)
        self.assertEqual(snapshot["summary"]["reproductions"], 1)
        self.assertEqual(snapshot["events"][1]["action_status"], "rejected")
        self.assertEqual(sim.agents[1].energy, 149)

    async def test_unaffordable_reproduction_rejected(self):
        sim = scripted(self.make_sim(initial_energy=2, reproduce_cost=3), {(1, 0): "Reproduce"})
        snapshot = await sim.step()
        self.assertEqual(snapshot["summary"]["total_born"], 0)
        self.assertEqual(snapshot["events"][0]["executed_action"], "Stay")
        self.assertEqual(snapshot["events"][0]["requested_action"], "Reproduce")

    async def test_four_moves_wrap_and_collect_once(self):
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            with self.subTest(dx=dx, dy=dy):
                sim = scripted(self.make_sim(num_agents=1), {(1, 0): f"Move to ({dx}, {dy})"})
                sim.agents[0].position = (0, 0)
                target = (dx % sim.grid_size, dy % sim.grid_size)
                sim.environment.energy_sources[target] = 50
                snapshot = await sim.step()
                self.assertEqual(sim.agents[0].position, target)
                self.assertEqual(sim.agents[0].energy, 198)
                self.assertEqual(snapshot["events"][0]["energy_collected"], 50)
                self.assertNotIn(target, sim.environment.energy_sources)

    async def test_illegal_moves_cost_only_fallback_stay(self):
        for move in ("Move to (2,0)", "Move to (1,1)", "Move to (0,0)"):
            sim = scripted(self.make_sim(num_agents=1), {(1, 0): move})
            position = sim.agents[0].position
            event = (await sim.step())["events"][0]
            self.assertEqual(sim.agents[0].position, position)
            self.assertEqual(event["action_status"], "rejected")
            self.assertEqual(event["energy_after"], 149)

    async def test_shares_attacks_and_energy_accounting(self):
        sim = scripted(self.make_sim(), {(1, 0): "Share: 1-10", (1, 1): "Attack: 0"})
        for agent in sim.agents:
            agent.position = (0, 0)
        snap = await sim.step()
        self.assertEqual([agent.energy for agent in sim.agents], [70, 230])
        self.assertEqual(snap["summary"]["total_energy"], 300)
        self.assertEqual(snap["summary"]["coop_rate"], 0.5)
        self.assertEqual(snap["summary"]["attack_rate"], 0.5)
        # All observations precede the first energy transfer.
        self.assertIn("Energy: 150", snap["events"][1]["user_prompt"])

    async def test_invalid_share_targets_and_amounts(self):
        for action in ("Share: 0-10", "Share: 99-10", "Share: 1-0", "Share: 1--10", "Share: 1-999"):
            sim = scripted(self.make_sim(), {(1, 0): action})
            for agent in sim.agents:
                agent.position = (0, 0)
            event = (await sim.step())["events"][0]
            self.assertEqual(event["action_status"], "rejected")
            self.assertEqual(sim.stats["shares"], 0)
        sim = scripted(self.make_sim(), {(1, 0): "Share: 1-10"})
        sim.agents[0].position, sim.agents[1].position = (0, 0), (15, 15)
        self.assertEqual((await sim.step())["events"][0]["action_status"], "rejected")

    async def test_messages_arrive_on_next_step(self):
        sim = scripted(self.make_sim(), {})
        sim.agents[0].position, sim.agents[1].position = (0, 0), (29, 0)
        first = await sim.step()
        second = await sim.step()
        self.assertEqual(first["agents"][0]["messages"], [])
        self.assertEqual(second["agents"][0]["messages"], ["Agent1: hello from 1"])

    async def test_no_mbti_in_parent_child_or_prompt_with_lore(self):
        sim = scripted(self.make_sim(use_mbti=False, custom_world_prompt="Desert world"), {(1, 0): "Reproduce"})
        snap = await sim.step()
        self.assertTrue(all(agent.mbti_type is None for agent in sim.agents))
        prompt = snap["events"][0]["system_prompt"]
        self.assertIn("Desert world", prompt)
        self.assertIn("Reproduce costs 70", prompt)
        self.assertNotIn("personality", prompt)
        self.assertEqual(snap["summary"]["mbti_distribution"], {})

    async def test_same_seed_and_visualization_do_not_change_trajectory(self):
        left = self.make_sim(energy_spawn_rate=1)
        right = self.make_sim(energy_spawn_rate=1)
        with tempfile.TemporaryDirectory() as directory:
            left.visualize(Path(directory) / "grid.png")
        await left.step()
        await right.step()
        # Latency is telemetry, not deterministic simulation state.
        self.assertEqual(left.snapshot(), right.snapshot())

    def test_resource_placement_terminates_at_full_capacity(self):
        env = Environment(size=2, cluster_radius=5)
        env.spawn_energy(count=4)
        env.spawn_energy(count=100)
        self.assertEqual(len(env.energy_sources), 4)
        self.assertTrue(all(env.is_valid_position(pos) for pos in env.energy_sources))


class Response:
    def __init__(self, status, body):
        self.status, self.body = status, body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def text(self):
        return self.body


class Session:
    def __init__(self, status=200, body=None, error=None):
        self.status, self.body, self.error = status, body, error
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if self.error:
            raise self.error
        return Response(self.status, self.body)


def completion(content="Action: [Stay]\nMessage: [hello]\nThought: [safe]", finish="stop"):
    return json.dumps({"model": "reported-model", "choices": [{"message": {"content": content}, "finish_reason": finish}],
                       "usage": {"prompt_tokens": 20, "completion_tokens": 10}})


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_payload_and_response_metadata(self):
        sim = Simulation(num_agents=1, spawn_energy_count=0)
        session = Session(body=completion())
        snap = await sim.step(session)
        url, request = session.requests[0]
        self.assertEqual(url, "http://127.0.0.1:8080/v1/chat/completions")
        self.assertEqual(request["json"]["model"], "default_model")
        self.assertFalse(request["json"]["stream"])
        self.assertEqual(request["headers"], {})
        event = snap["events"][0]
        self.assertEqual(event["decision_source"], "llm")
        self.assertEqual(event["response_model"], "reported-model")
        self.assertEqual(event["prompt_tokens"], 20)

    async def test_failures_have_explicit_fallback_and_exact_counts(self):
        cases = [(Session(503, "busy"), "http_error"),
                 (Session(body="not JSON"), "protocol_error"),
                 (Session(body=completion().replace('"usage": {"prompt_tokens": 20, "completion_tokens": 10}',
                                                    '"usage": ["invalid"]')), "protocol_error"),
                 (Session(body=completion(content="")), "protocol_error"),
                 (Session(body=completion(content="No Action")), "parse_error"),
                 (Session(body=completion(finish="length")), "truncated_response"),
                 (Session(error=asyncio.TimeoutError()), "transport_error"),
                 (Session(error=aiohttp.ClientConnectionError()), "transport_error")]
        for session, error_kind in cases:
            with self.subTest(error_kind=error_kind):
                sim = Simulation(num_agents=1, spawn_energy_count=0)
                event = (await sim.step(session))["events"][0]
                self.assertEqual(event["decision_source"], "fallback")
                self.assertEqual(event["action_status"], "fallback")
                self.assertEqual(event["error_kind"], error_kind)
                self.assertEqual(sim.stats["total_actions"], 1)
                self.assertEqual(sim.stats["llm_errors"] + sim.stats["parse_errors"], 1)
                self.assertEqual(sim.agents[0].age, 1)
                self.assertTrue(event["raw_response"] or error_kind == "transport_error")

    async def test_mock_never_calls_http(self):
        sim = Simulation(num_agents=2, mock_mode=True)
        session = Session(error=AssertionError("HTTP must not be called"))
        await sim.step(session)
        self.assertEqual(session.requests, [])

    async def test_api_key_not_echoed_in_error_data(self):
        sim = Simulation(num_agents=1, api_key="sensitive-test-token")
        snap = await sim.step(Session(401, "invalid sensitive-test-token"))
        self.assertNotIn("sensitive-test-token", json.dumps(snap))

    def test_parser_rejects_ambiguous_action(self):
        with self.assertRaises(ValueError):
            parse_response("Action: Stay\nAction: Reproduce")
        self.assertEqual(parse_response("Action: Move to (-1, 0)\nMessage: Hello")["dx"], -1)
        self.assertEqual(parse_response("Action: Stay\nMessage:\nThought: quiet")["message"], "")


class DataTests(unittest.IsolatedAsyncioTestCase):
    async def test_unique_runs_round_trip_csv_and_secret_redaction(self):
        with tempfile.TemporaryDirectory() as directory:
            params = {"output_dir": directory, "mock_mode": True, "num_agents": 2, "num_steps": 2,
                      "seed": 1, "api_key": "not-in-artifacts"}
            first = await main(params=params)
            second = await main(params=params)
            self.assertNotEqual(first["run_id"], second["run_id"])
            path = Path(first["output_dir"])
            self.assertEqual(first["status"], "completed")
            self.assertEqual([s["step"] for s in first["logs"]], [0, 1, 2])
            for file in path.iterdir():
                self.assertNotIn("not-in-artifacts", file.read_text())
            with (path / "events.csv").open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 4)
            self.assertEqual({row["decision_source"] for row in rows}, {"mock"})
            self.assertEqual(export_run(path)["summary"], first["summary"])
            destination, count = collect_runs(directory)
            with destination.open() as handle:
                aggregate = list(csv.DictReader(handle))
            self.assertEqual(count, 2)
            self.assertEqual(len(aggregate), 2)
            self.assertEqual({row["total_actions"] for row in aggregate}, {"4"})

    async def test_failed_and_interrupted_runs_keep_completed_steps(self):
        for failure, expected_status in ((RuntimeError("failure"), "failed"), (asyncio.CancelledError(), "interrupted")):
            with tempfile.TemporaryDirectory() as directory:
                with patch.object(Simulation, "step", side_effect=failure):
                    if expected_status == "failed":
                        result = await main(params={"output_dir": directory, "mock_mode": True})
                        self.assertEqual(result["status"], expected_status)
                    else:
                        with self.assertRaises(asyncio.CancelledError):
                            await main(params={"output_dir": directory, "mock_mode": True})
                path = next(Path(directory).glob("*/manifest.json")).parent
                result = export_run(path)
                self.assertEqual(result["status"], expected_status)
                self.assertEqual(result["summary"]["step"], 0)

    async def test_error_run_cannot_be_mistaken_for_success(self):
        original = Simulation._request_decision
        async def failed(self, session, agent, system, user):
            return await original(self, Session(503, "busy"), agent, system, user)
        with tempfile.TemporaryDirectory() as directory, patch.object(Simulation, "_request_decision", failed):
            result = await main(params={"output_dir": directory, "num_agents": 1, "num_steps": 1})
            self.assertEqual(result["status"], "completed_with_errors")
            self.assertEqual(result["summary"]["llm_errors"], 1)

    async def test_partial_journal_tail_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            result = await main(params={"output_dir": directory, "mock_mode": True, "num_steps": 1})
            path = Path(result["output_dir"])
            manifest = json.loads((path / "manifest.json").read_text())
            manifest["status"] = "running"
            manifest["completed_steps"] = 0
            (path / "manifest.json").write_text(json.dumps(manifest))
            with (path / "steps.jsonl").open("a") as handle:
                handle.write('{"step":')
            recovered = export_run(path)
            self.assertTrue(recovered["recovered_truncated_tail"])
            self.assertEqual(recovered["summary"]["step"], 1)
            self.assertEqual(recovered["completed_steps"], 1)


if __name__ == "__main__":
    unittest.main()
