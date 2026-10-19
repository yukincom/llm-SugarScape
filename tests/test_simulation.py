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
from agent_view import format_live_decision
from response_fields import reading_fields


def reply(action="stay", share="none", attack="none", message="", summary="Current situation",
          thoughts="Thoughts and feelings", memory="Remember this turn"):
    return (f"Summary: {summary}\nThoughts: {thoughts}\nNext Action: {action}\n"
            f"Share: {share}\nAttack: {attack}\nMessage: {message}\nMemory: {memory}")


def scripted(sim, actions, message=""):
    async def decide(session, agent, system_prompt, user_prompt):
        choice = actions.get((sim.step_count, agent.id), "stay")
        fields = {"action": choice} if isinstance(choice, str) else choice
        fields = dict(fields)
        if "action" not in fields:
            if fields.get("share", "none") != "none":
                fields["action"] = f"Share: {fields['share']}"
            elif fields.get("attack", "none") != "none":
                fields["action"] = f"Attack: {fields['attack']}"
        raw = reply(**{"message": message.format(id=agent.id), **fields})
        return {"agent_id": agent.id, "decision_source": "mock", "decision_status": "ok",
                "error_kind": "", "reason": "", "raw_response": raw,
                "system_prompt": system_prompt, "user_prompt": user_prompt, **parse_response(raw)}
    sim._request_decision = decide
    return sim


class SimulationTests(unittest.IsolatedAsyncioTestCase):
    def make_sim(self, **params):
        return Simulation(**{"num_agents": 2, "seed": 42, "spawn_energy_count": 0,
                             "initial_energy": 150, "child_initial_energy": 150,
                             "energy_spawn_rate": 0, "mock_mode": True, **params})

    async def test_default_health_for_initial_and_newborn_agents(self):
        sim = scripted(Simulation(num_agents=1, spawn_energy_count=0, energy_spawn_rate=0,
                                  mock_mode=True), {(1, 0): "Reproduce"})
        self.assertEqual(sim.agents[0].energy, 100)
        self.assertEqual(sim.population_cap, 60)
        self.assertFalse(sim.use_mbti)
        self.assertEqual((sim.reproduce_cost, sim.view_range, sim.message_range), (70, 5, 5))
        snapshot = await sim.step()
        self.assertEqual(snapshot["summary"]["total_born"], 1)
        self.assertEqual([agent.energy for agent in sim.agents], [30, 100])
        self.assertTrue(all(agent.alive for agent in sim.agents))
        self.assertTrue(all(agent.mbti_type is None for agent in sim.agents))
        sim.agents[0].energy = 1
        await sim.step()
        self.assertEqual(sim.agents[0].energy, 0)
        self.assertFalse(sim.agents[0].alive)

    def test_neutral_prompt_and_optional_personality_information(self):
        for enabled in (False, True):
            with self.subTest(use_mbti=enabled):
                sim = self.make_sim(use_mbti=enabled)
                for agent in sim.agents:
                    agent.position = (0, 0)
                agent = sim.agents[0]
                view, messages = agent.get_local_view(sim.environment, sim.agents)
                system, user = agent.build_prompt(view, messages, len(sim.agents),
                                                  sim.reproduce_cost, sim.population_cap)
                self.assertNotIn("Strive for survival and growth", system)
                self.assertNotIn("You are an independent Agent", system)
                self.assertIn("You can move one cell: Move to (1,0)", system)
                self.assertIn("If your energy drops to 0 or below, you die", system)
                self.assertIn("pays 1 energy after all Actions", system)
                self.assertIn("25% (rounded down, max 12 energy)", system)
                self.assertIn("costs 4 energy (5 in total", system)
                self.assertNotIn("takes half", system)
                self.assertEqual("Let this influence your decisions." in system, enabled)
                self.assertEqual("You have the personality" in system, enabled)
                self.assertEqual("MBTI:" in user, enabled)
                self.assertIn("Keep the entire response within 400 tokens, including all field labels.", user)
                self.assertNotIn("up to 250 characters", user)
                self.assertNotIn("up to 1000 characters", user)

    async def test_each_reply_is_visible_before_actions_without_changing_decisions(self):
        sim = scripted(self.make_sim(), {}, message="hello from {id}")
        replies = []
        def observe(step, event):
            replies.append((step, event["agent_id"], event["message"]))
            self.assertEqual(sim.stats["total_actions"], 0)
            event["kind"] = "reproduce"
        snapshot = await sim.step(on_decision=observe)
        self.assertEqual(replies, [(1, 0, "hello from 0"), (1, 1, "hello from 1")])
        self.assertEqual([event["executed_action"] for event in snapshot["events"]], ["Stay", "Stay"])

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
        sim = scripted(self.make_sim(population_cap=3, initial_energy=300), {(1, 0): "Reproduce", (1, 1): "Reproduce"})
        snapshot = await sim.step()
        self.assertEqual(snapshot["summary"]["alive"], 3)
        self.assertEqual(snapshot["summary"]["reproductions"], 1)
        self.assertEqual(snapshot["events"][1]["action_status"], "rejected")
        self.assertEqual(sim.agents[1].energy, 299)

    async def test_unaffordable_reproduction_rejected(self):
        sim = scripted(self.make_sim(initial_energy=2, reproduce_cost=3), {(1, 0): "Reproduce"})
        snapshot = await sim.step()
        self.assertEqual(snapshot["summary"]["total_born"], 0)
        self.assertEqual(snapshot["events"][0]["executed_action"], "Stay")
        self.assertEqual(snapshot["events"][0]["requested_action"], "Reproduce")

    async def test_four_moves_wrap_and_collect_once(self):
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            with self.subTest(dx=dx, dy=dy):
                sim = scripted(self.make_sim(num_agents=1), {(1, 0): {(-1, 0): "x-1", (1, 0): "x+1", (0, -1): "y-1", (0, 1): "y+1"}[dx, dy]})
                sim.agents[0].position = (0, 0)
                target = (dx % sim.grid_size, dy % sim.grid_size)
                sim.environment.energy_sources[target] = 50
                snapshot = await sim.step()
                self.assertEqual(sim.agents[0].position, target)
                self.assertEqual(sim.agents[0].energy, 198)
                self.assertEqual(snapshot["events"][0]["energy_collected"], 50)
                self.assertNotIn(target, sim.environment.energy_sources)

    async def test_non_diagonal_unreadable_moves_keep_existing_stay_behavior(self):
        for move in ("Move to (2,0)", "Move to (0,0)"):
            sim = self.make_sim(num_agents=1, mock_mode=False)
            position = sim.agents[0].position
            event = (await sim.step(Session(body=completion(reply(action=move)))))["events"][0]
            self.assertEqual(sim.agents[0].position, position)
            self.assertEqual(event["action_status"], "executed")
            self.assertEqual(event["error_kind"], "")
            self.assertEqual(event["energy_after"], 150)
            self.assertEqual(event["turn_energy_after"], 149)

    async def test_shares_attacks_and_energy_accounting(self):
        sim = scripted(self.make_sim(), {(1, 0): "Share: 1-10", (1, 1): "Attack: 0"})
        sim.agents[0].position, sim.agents[1].position = (0, 0), (1, 0)
        snap = await sim.step()
        self.assertEqual([agent.energy for agent in sim.agents], [127, 167])
        self.assertEqual(snap["summary"]["total_energy"], 294)
        self.assertEqual(snap["summary"]["coop_rate"], 0.5)
        self.assertEqual(snap["summary"]["attack_rate"], 0.5)
        self.assertEqual(snap["summary"]["total_died"], 0)
        self.assertEqual(sim.agents[0].attacked_by, [1])
        self.assertEqual(sim.agents[0].shared_energy, {1: 10})
        self.assertEqual(snap["events"][1]["stolen_amount"], 12)
        self.assertEqual([event["total_energy_cost"] for event in snap["events"]], [1, 5])
        self.assertEqual(snap["events"][1]["attack_status"], "executed")
        self.assertEqual(snap["events"][1]["executed_attack"], "0")
        self.assertIn("Energy: 150", snap["events"][1]["user_prompt"])

    async def test_invalid_share_targets_and_amounts(self):
        for action in ("0-10", "99-10", "1-0", "1--10", "1-999"):
            sim = scripted(self.make_sim(), {(1, 0): {"share": action}})
            for agent in sim.agents:
                agent.position = (0, 0)
            event = (await sim.step())["events"][0]
            self.assertEqual(event["action_status"], "rejected")
            self.assertEqual(sim.stats["shares"], 0)
        sim = scripted(self.make_sim(), {(1, 0): {"share": "1-10"}})
        sim.agents[0].position, sim.agents[1].position = (0, 0), (15, 15)
        self.assertEqual((await sim.step())["events"][0]["action_status"], "rejected")

    async def test_messages_arrive_on_next_step(self):
        sim = scripted(self.make_sim(), {}, message="hello from {id}")
        sim.agents[0].position, sim.agents[1].position = (0, 0), (29, 0)
        first = await sim.step()
        second = await sim.step()
        self.assertEqual(first["agents"][0]["messages"], [])
        self.assertEqual(second["agents"][0]["messages"], ["Agent1: hello from 1"])

    async def test_only_selected_action_executes_and_messages_are_free(self):
        sim = scripted(self.make_sim(num_agents=3, initial_energy=100), {
            (1, 0): {"action": "x-1", "share": "1-10", "attack": "2", "message": "hello"}})
        for agent, position in zip(sim.agents, ((0, 0), (1, 0), (0, 1))):
            agent.position = position
        snap = await sim.step()
        first = snap["events"][0]
        self.assertEqual([agent.energy for agent in sim.agents], [98, 99, 99])
        self.assertEqual(first["energy_cost"], 1)
        self.assertEqual(first["total_energy_cost"], 2)
        self.assertEqual(first["shared_amount"], 0)
        self.assertEqual(first["stolen_amount"], 0)
        self.assertEqual(first["message_recipient_ids"], [1, 2])
        self.assertEqual(first["message_cost"], 0)
        self.assertEqual((sim.stats["shares"], sim.stats["attacks"]), (0, 0))

    async def test_attack_uses_current_view_after_target_moves_and_rounds_down(self):
        sim = scripted(self.make_sim(view_range=1), {(1, 0): "x-1", (1, 1): "Attack: 0"})
        sim.agents[0].position, sim.agents[1].position = (0, 0), (1, 0)
        snap = await sim.step()
        self.assertEqual(sim.agents[0].position, (29, 0))
        self.assertEqual(snap["events"][1]["attack_status"], "rejected")
        for position in ((2, 0), (1, 1), (0, 0), (5, 5), (29, 29)):
            sim = scripted(self.make_sim(), {(1, 0): "Attack: 1"})
            sim.agents[0].position, sim.agents[1].position = (0, 0), position
            sim.agents[1].energy = 101
            event = (await sim.step())["events"][0]
            self.assertEqual(event["attack_status"], "executed")
            self.assertEqual(event["stolen_amount"], 12)
            self.assertEqual([a.energy for a in sim.agents], [157, 88])
            self.assertTrue(all(agent.alive for agent in sim.agents))
        sim = scripted(self.make_sim(), {(1, 0): "Attack: 1"})
        sim.agents[0].position, sim.agents[1].position = (0, 0), (6, 0)
        self.assertEqual((await sim.step())["events"][0]["attack_status"], "rejected")

    async def test_attack_fraction_rounding_cap_and_total_cost(self):
        for target_energy, stolen in ((3, 0), (7, 1), (47, 11), (48, 12), (49, 12), (1000, 12)):
            with self.subTest(target_energy=target_energy):
                sim = scripted(self.make_sim(), {(1, 0): "Attack: 1"})
                for agent in sim.agents:
                    agent.position = (0, 0)
                sim.agents[1].energy = target_energy
                event = (await sim.step())["events"][0]
                self.assertEqual(event["stolen_amount"], stolen)
                self.assertEqual((event["energy_cost"], event["turn_energy_cost"], event["total_energy_cost"]), (4, 1, 5))
                self.assertEqual([a.energy for a in sim.agents], [150 + stolen - 5, target_energy - stolen - 1])

    async def test_common_cost_is_after_all_actions_and_can_be_met_by_a_share(self):
        sim = scripted(self.make_sim(initial_energy=1), {(1, 1): "Share: 0-2"}, message="still alive")
        for agent in sim.agents:
            agent.position = (0, 0)
        sim.agents[1].energy = 4
        snap = await sim.step()
        self.assertEqual([a.energy for a in sim.agents], [2, 1])
        self.assertTrue(all(a.alive for a in sim.agents))
        event = snap["events"][0]
        self.assertEqual((event["energy_before"], event["energy_after"]), (1, 1))
        self.assertEqual((event["turn_energy_before"], event["turn_energy_after"]), (3, 2))
        self.assertEqual(event["message_recipient_ids"], [1])

    async def test_zero_transfer_attack_and_repeated_sharing_do_not_avoid_decay(self):
        sim = scripted(self.make_sim(initial_energy=1), {(1, 0): "Attack: 1"}, message="too late")
        for agent in sim.agents:
            agent.position = (0, 0)
        snap = await sim.step()
        self.assertEqual(snap["events"][0]["stolen_amount"], 0)
        self.assertEqual(snap["events"][0]["total_energy_cost"], 5)
        self.assertEqual([a.energy for a in sim.agents], [-4, 0])
        self.assertEqual(snap["summary"]["alive"], 0)
        self.assertTrue(all(e["message_status"] == "skipped_dead" for e in snap["events"]))

        sim = scripted(self.make_sim(initial_energy=3), {
            (step, actor): f"Share: {1 - actor}-1" for step in range(1, 5) for actor in (0, 1)})
        for agent in sim.agents:
            agent.position = (0, 0)
        await sim.step()
        self.assertEqual([a.energy for a in sim.agents], [2, 2])
        snap = await sim.step()
        self.assertEqual([a.energy for a in sim.agents], [1, 1])
        self.assertEqual(snap["summary"]["shares"], 4)
        self.assertEqual([e["turn_energy_cost"] for e in snap["events"]], [1, 1])
        await sim.step()
        self.assertEqual((await sim.step())["summary"]["alive"], 0)

    async def test_rejected_action_and_fallback_pay_common_cost_once(self):
        sim = scripted(self.make_sim(num_agents=1), {(1, 0): "Attack: 99"})
        event = (await sim.step())["events"][0]
        self.assertEqual((event["action_status"], event["energy_cost"], event["total_energy_cost"]), ("rejected", 0, 1))
        sim = self.make_sim(num_agents=1, mock_mode=False)
        event = (await sim.step(Session(503, "busy")))["events"][0]
        self.assertEqual((event["action_status"], event["energy_cost"], event["total_energy_cost"]), ("fallback", 0, 1))
        self.assertEqual(sim.agents[0].energy, 149)

    async def test_complete_energy_ledger_with_birth_and_all_action_types(self):
        sim = scripted(self.make_sim(num_agents=5, initial_energy=100), {
            (1, 0): "Move to (1,0)", (1, 1): "Share: 0-10",
            (1, 2): "Attack: 0", (1, 3): "Reproduce", (1, 4): "Stay"})
        for agent in sim.agents:
            agent.position = (0, 0)
        sim.environment.energy_sources[(1, 0)] = 50
        initial = sum(a.energy for a in sim.agents)
        snap = await sim.step()
        events = snap["events"]
        self.assertEqual([e["total_energy_cost"] for e in events], [2, 1, 5, 70, 1])
        self.assertEqual(sum(a.energy for a in sim.agents), initial + 50 + 150 - 79)
        for event in events:
            self.assertEqual(event["energy_after"], event["energy_before"] + event["energy_collected"]
                             + event["stolen_amount"] - event["shared_amount"] - event["energy_cost"])
            self.assertEqual(event["turn_energy_after"], event["turn_energy_before"] - 1)
        self.assertEqual(sim.agents[-1].energy, 150)
        self.assertEqual(sim.agents[-1].age, 0)

    async def test_two_turn_attack_and_negotiated_share_match_proposed_costs(self):
        cases = [
            ({(1, 0): "Attack: 1", (2, 0): "Attack: 1"}, [33, 35]),
            ({(1, 0): "Attack: 1", (2, 0): "Attack: 1", (2, 1): "Attack: 0"}, [25, 39]),
            ({(2, 1): "Share: 0-12"}, [30, 46]),
        ]
        for actions, expected in cases:
            with self.subTest(expected=expected):
                sim = scripted(self.make_sim(initial_energy=20), actions)
                for agent in sim.agents:
                    agent.position = (0, 0)
                sim.agents[1].energy = 60
                await sim.step()
                await sim.step()
                self.assertEqual([a.energy for a in sim.agents], expected)

    async def test_view_and_message_ranges_are_distinct_and_silence_is_free(self):
        sim = scripted(self.make_sim(view_range=2, message_range=3), {(1, 0): {"message": "hello"}})
        sim.agents[0].position, sim.agents[1].position = (0, 0), (3, 0)
        first = await sim.step()
        second = await sim.step()
        self.assertNotIn("1=(3,0)", first["events"][0]["user_prompt"])
        self.assertEqual(first["events"][0]["message_recipient_ids"], [1])
        self.assertEqual(first["events"][0]["message_cost"], 0)
        self.assertEqual(first["events"][1]["message_cost"], 0)
        self.assertEqual(second["agents"][1]["messages"], ["Agent0: hello"])

    async def test_memory_records_actual_actions_even_when_model_memory_is_none(self):
        thought = "Food was to the east. " * 10
        sim = scripted(self.make_sim(num_agents=1), {
            (step, 0): {"action": "x+1", "thoughts": thought, "memory": "none"}
            for step in range(1, 6)})
        for _ in range(5):
            snap = await sim.step()
        prompt = snap["events"][0]["user_prompt"]
        self.assertNotIn("Step 1:", prompt)
        for step in range(2, 5):
            self.assertIn(f"Step {step}: Move to (1,0); {thought[:100]}", prompt)
        self.assertEqual(sim.agents[0].memory, [f"Step {step}: Move to (1,0); {thought[:100]}"
                                               for step in range(3, 6)])
        self.assertEqual(snap["events"][0]["response_memory"], "none")
        self.assertEqual(snap["events"][0]["memory"], sim.agents[0].memory[-1])
        self.assertEqual(snap["events"][0]["memory_source"], "engine")
        sim = self.make_sim(num_agents=1, mock_mode=False)
        await sim.step(Session(body=completion(reply(thoughts="old thought"))))
        for _ in range(3):
            await sim.step(Session(503, "busy"))
        self.assertEqual(sim.agents[0].memory, [f"Step {step}: Stay; " for step in range(2, 5)])
        snap = await sim.step(Session(body=completion()))
        self.assertNotIn("old thought", snap["events"][0]["user_prompt"])
        self.assertIn("Step 4: Stay;", snap["events"][0]["user_prompt"])

    async def test_messages_use_final_positions_and_reach_newborns(self):
        for action, recipients in (("x+1", [1]), ("x-1", [])):
            sim = scripted(self.make_sim(message_range=3), {(1, 0): {"action": action, "message": "hello"}})
            sim.agents[0].position, sim.agents[1].position = (0, 0), (4, 0)
            event = (await sim.step())["events"][0]
            self.assertEqual(event["message_recipient_ids"], recipients)
            self.assertEqual(event["message_cost"], 0)
        sim = scripted(self.make_sim(num_agents=1, initial_energy=100, child_initial_energy=100),
                       {(1, 0): {"action": "Reproduce", "message": "hello child"}})
        event = (await sim.step())["events"][0]
        self.assertEqual(event["message_recipient_ids"], [1])
        self.assertEqual(sim.agents[1].next_messages, ["Agent0: hello child"])
        sim = scripted(self.make_sim(num_agents=2, initial_energy=1), {}, message="too late")
        snap = await sim.step()
        self.assertTrue(all(e["message_status"] == "skipped_dead" for e in snap["events"]))
        self.assertTrue(all(not a.next_messages for a in sim.agents))

    def test_absolute_position_and_configurable_rules_are_in_prompt(self):
        sim = self.make_sim(view_range=4, message_range=7)
        agent = sim.agents[0]
        agent.position = (9, 12)
        view, messages = agent.get_local_view(sim.environment, sim.agents, sim.view_range)
        system, user = agent.build_prompt(view, messages, 2, sim.reproduce_cost, sim.population_cap,
                                         sim.view_range, sim.message_range)
        self.assertIn("M=(9,12)", user)
        self.assertIn("Position: (9, 12)", user)
        self.assertIn("grid edges wrap", system)
        self.assertIn("Local view extends 4 cells", system)
        self.assertIn("messages reach 7 cells", system)
        self.assertIn("Thought: [Brief reasoning for your action]", user)

    async def test_no_mbti_in_parent_child_or_prompt_with_lore(self):
        sim = scripted(self.make_sim(use_mbti=False, custom_world_prompt="Desert world"), {(1, 0): "Reproduce"})
        snap = await sim.step()
        self.assertTrue(all(agent.mbti_type is None for agent in sim.agents))
        prompt = snap["events"][0]["system_prompt"]
        self.assertIn("Desert world", prompt)
        self.assertIn("Reproduce costs 70 energy", prompt)
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


def completion(content=None, finish="stop"):
    if content is None:
        content = reply(message="hello")
    return json.dumps({"model": "reported-model", "choices": [{"message": {"content": content}, "finish_reason": finish}],
                       "usage": {"prompt_tokens": 20, "completion_tokens": 10}})


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_unreadable_action_keeps_live_prose_message_and_memory(self):
        raw = reply("I have not chosen", share="unclear", attack="unclear", message="Hello!",
                    thoughts="I am focused.", memory="Remember food.")
        sim = Simulation(num_agents=3, spawn_energy_count=0, energy_spawn_rate=0)
        positions = [agent.position for agent in sim.agents]
        live = []
        def observe(step, event):
            live.append(format_live_decision(event, sim.agents[event["agent_id"]].to_dict()))
        snapshot = await sim.step(Session(body=completion(raw)), on_decision=observe)
        self.assertIn("💬 Hello!", live[-1])
        self.assertIn("💭 I am focused.", live[-1])
        self.assertNotIn("メッセージ未送信", live[-1])
        self.assertEqual(snapshot["summary"]["parse_errors"], 0)
        self.assertEqual([agent.position for agent in sim.agents], positions)
        self.assertEqual([agent.energy for agent in sim.agents], [99, 99, 99])
        for agent, event in zip(sim.agents, snapshot["events"]):
            self.assertEqual(event["executed_action"], "Stay")
            self.assertEqual(event["message_status"], "sent")
            self.assertEqual(event["raw_response"], raw)
            self.assertEqual(agent.memory, ["Step 1: Stay; I am focused."])
            self.assertEqual(event["response_memory"], "Remember food.")

    async def test_endpoint_payload_and_response_metadata(self):
        sim = Simulation(num_agents=1, spawn_energy_count=0)
        session = Session(body=completion())
        snap = await sim.step(session)
        url, request = session.requests[0]
        self.assertEqual(url, "http://127.0.0.1:8080/v1/chat/completions")
        self.assertEqual(request["json"]["model"], "default_model")
        self.assertFalse(request["json"]["stream"])
        self.assertEqual(request["json"]["temperature"], 0.0)
        self.assertEqual(request["json"]["max_tokens"], 5000)
        self.assertEqual(request["json"]["top_p"], 1.0)
        self.assertEqual(request["headers"], {})
        event = snap["events"][0]
        self.assertEqual(event["decision_source"], "llm")
        self.assertNotIn("response_model", event)
        self.assertEqual(event["prompt_tokens"], 20)

    async def test_failures_have_explicit_fallback_and_exact_counts(self):
        cases = [(Session(503, "busy"), "http_error"),
                 (Session(body="not JSON"), "protocol_error"),
                 (Session(body=completion(content="")), "protocol_error"),
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

    def test_parser_accepts_duplicate_and_missing_fields(self):
        self.assertEqual(parse_response(reply() + "\nNext Action: reproduce")["kind"], "reproduce")
        self.assertEqual(parse_response("Action: Stay\nMessage: hello\nThought: old format")["thought"], "old format")
        self.assertEqual(parse_response(reply("x-1"))["dx"], -1)
        self.assertEqual(parse_response(reply(message="None"))["message"], "")

    def test_parser_retains_all_seven_multiline_fields(self):
        memory = "昨日の出来事を忘れない。" * 30 + "\n次は隣へ移動する。"
        thoughts = "少し不安だ。\nでも仲間と話したい。"
        fields = parse_response(reply("x+1", "2-30", "3", "こんにちは\n元気？", "砂糖を発見", thoughts, memory))
        self.assertEqual(fields["summary"], "砂糖を発見")
        self.assertEqual(fields["thought"], thoughts)
        self.assertEqual(fields["memory"], memory)
        self.assertEqual(fields["message"], "こんにちは\n元気？")
        self.assertEqual(fields["share"], {"target_id": 2, "amount": 30})
        self.assertEqual(fields["attack"], {"target_id": 3})


class DataTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        manager = patch("model_identity.read_server", side_effect=OSError("test manager unavailable"))
        manager.start()
        self.addCleanup(manager.stop)

    async def test_live_board_receives_initial_and_each_saved_turn_without_mutating_run(self):
        seen = []
        def observe(snapshot):
            agent = snapshot["agents"][0]
            seen.append((snapshot["step"], agent["energy"], tuple(agent["position"])))
            snapshot["agents"][0]["energy"] = -999
            snapshot["agents"][0]["position"] = [-999, -999]
        def moving_simulation(**params):
            return scripted(Simulation(**params), {(1, 0): "x+1", (2, 0): "x+1"})
        with tempfile.TemporaryDirectory() as directory, patch("main.Simulation", side_effect=moving_simulation):
            result = await main(params={"output_dir": directory, "mock_mode": True,
                                        "num_agents": 1, "num_steps": 2, "initial_energy": 5,
                                        "spawn_energy_count": 0, "energy_spawn_rate": 0},
                                on_snapshot=observe)
        x, y = seen[0][2]
        self.assertEqual(seen, [(0, 5, (x, y)), (1, 3, ((x + 1) % 30, y)), (2, 1, ((x + 2) % 30, y))])
        saved = [(snap["step"], snap["agents"][0]["energy"], tuple(snap["agents"][0]["position"]))
                 for snap in result["logs"]]
        self.assertEqual(saved, seen)

    async def test_unique_runs_round_trip_csv_and_secret_redaction(self):
        with tempfile.TemporaryDirectory() as directory:
            params = {"output_dir": directory, "mock_mode": True, "num_agents": 2, "num_steps": 2,
                      "seed": 1, "api_key": "not-in-artifacts"}
            first = await main(params=params)
            second = await main(params=params)
            self.assertNotEqual(first["run_id"], second["run_id"])
            path = Path(first["output_dir"])
            self.assertEqual(first["status"], "completed")
            self.assertEqual(first["schema_version"], 7)
            self.assertEqual(first["engine_version"], "5.4")
            self.assertIn("paper_prompts.py", first["provenance"]["source_sha256"])
            self.assertIn("response_fields.py", first["provenance"]["source_sha256"])
            self.assertEqual([s["step"] for s in first["logs"]], [0, 1, 2])
            for file in path.rglob("*"):
                if file.is_file():
                    self.assertNotIn(b"not-in-artifacts", file.read_bytes())
            with (path / "events.csv").open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 4)
            self.assertEqual({row["decision_source"] for row in rows}, {"mock"})
            self.assertEqual(rows[0]["summary"], "")
            self.assertEqual(rows[0]["memory"], "Step 1: Stay; Mock decision")
            self.assertEqual(rows[0]["message_cost"], "0")
            self.assertEqual(rows[0]["energy_cost"], "0")
            self.assertEqual(rows[0]["turn_energy_cost"], "1")
            self.assertEqual(rows[0]["total_energy_cost"], "1")
            self.assertEqual(int(rows[0]["turn_energy_after"]), int(rows[0]["turn_energy_before"]) - 1)
            self.assertEqual(export_run(path)["summary"], first["summary"])
            destination, count = collect_runs(directory)
            with destination.open() as handle:
                aggregate = list(csv.DictReader(handle))
            self.assertEqual(count, 2)
            self.assertEqual(len(aggregate), 2)
            self.assertEqual({row["total_actions"] for row in aggregate}, {"4"})

    async def test_readable_folder_uses_japan_time_and_never_overwrites_same_second(self):
        with tempfile.TemporaryDirectory() as directory, patch(
                "run_data.utc_now", return_value="2026-10-09T15:04:05+00:00"):
            params = {"output_dir": directory, "mock_mode": True, "num_steps": 0}
            first = await main(params=params)
            first_bytes = (Path(first["output_dir"]) / "manifest.json").read_bytes()
            second = await main(params=params)
            self.assertEqual(Path(first["output_dir"]).name, "2026-10-10_00-04-05_Mock")
            self.assertEqual(Path(second["output_dir"]).name, "2026-10-10_00-04-05_Mock_02")
            self.assertNotEqual(first["run_id"], second["run_id"])
            self.assertEqual((Path(first["output_dir"]) / "manifest.json").read_bytes(), first_bytes)
            (Path(directory) / "old-folder-name").symlink_to(Path(first["output_dir"]).name, target_is_directory=True)
            self.assertEqual(collect_runs(directory)[1], 2)

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
        with tempfile.TemporaryDirectory() as directory, patch.object(Simulation, "_request_decision", failed), \
                patch.object(aiohttp.ClientSession, "head", return_value=Response(405, "")):
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
