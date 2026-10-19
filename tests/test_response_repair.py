"""Response repair changes execution, so cover ambiguity and saved evidence."""

import csv
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from main import DEFAULT_PARAMS, Simulation, parse_response
from run_data import RunRecorder, collect_runs, export_run, read_run
from test_simulation import Session, completion, reply

ROOT = Path(__file__).resolve().parents[1]


class ResponseRepairTests(unittest.TestCase):
    def test_restored_three_field_actions_include_sharing_and_attacking(self):
        for action, kind, normalized in (("Move to (0,-1)", "move", "y-1"),
                                         ("Share: 2-30", "share", "share: 2-30"),
                                         ("Attack: 3", "attack", "attack: 3")):
            with self.subTest(action=action):
                parsed = parse_response(f"Action: [{action}]\nMessage: [Hello]\nThought: [A reason]")
                self.assertEqual(parsed["kind"], kind)
                self.assertEqual(parsed["normalized_action"], normalized)
                self.assertEqual(parsed["message"], "Hello")
                self.assertEqual(parsed["thought"], "A reason")
                self.assertEqual(parsed["response_repairs"], [])
        self.assertEqual(parse_response("Share: 2-30")["amount"], 30)
        self.assertEqual(parse_response("Attack: 3")["target_id"], 3)
        self.assertEqual(parse_response("Action: Share: 2-30; Move to (1,0)")["kind"], "share")
        self.assertEqual(parse_response("Action: Move to (1,0); Attack: 2")["kind"], "move")

    def test_exact_commands_keep_their_original_values_without_repairs(self):
        for action in ("x+1", "x-1", "y+1", "y-1", "stay", "Reproduce"):
            with self.subTest(action=action):
                parsed = parse_response(reply(action))
                self.assertEqual(parsed["requested_action"], action)
                self.assertEqual(parsed["normalized_action"], action.lower())
                self.assertEqual(parsed["response_repairs"], [])

    def test_notation_changes_are_explicit_and_do_not_invent_movement(self):
        for raw, expected in (("x + 1", "x+1"), ("Ｘ ＋ １", "x+1"), ("y − 1", "y-1"),
                              ("**`x + 1`**", "x+1"), ('"stay".', "stay"), ("reproduce。", "reproduce")):
            with self.subTest(raw=raw):
                parsed = parse_response(reply(raw))
                self.assertEqual(parsed["requested_action"], raw)
                self.assertEqual(parsed["normalized_action"], expected)
                self.assertEqual(parsed["response_repairs"], [
                    {"field": "Next Action", "rule": "notation", "original": [raw], "normalized": expected}])

    def test_recorded_agent02_choices_are_all_usable(self):
        fixture = json.loads((ROOT / "tests/fixtures/agent02-action-repair.json").read_text())
        for case in fixture["cases"]:
            with self.subTest(step=case["step"]):
                raw = "Summary: Food nearby\n" + case["action_block"] + "\nMessage: Heading east"
                parsed = parse_response(raw)
                self.assertEqual(parsed["normalized_action"], "x+1")
                self.assertEqual(parsed["message"], "Heading east")

    def test_explanations_alternatives_and_last_fields_are_accepted(self):
        for raw, expected in (("y-1 (Move south to the energy source)", "y-1"),
                              ("x+1, y-1", "x+1"), ("x+1 or y-1", "x+1"),
                              ("Search for food (y-1|x-1|y+1|x+1)", "y-1"),
                              ("x+1\nNext Action: y-1", "y-1"),
                              ("I will move x+1.", "x+1"),
                              ("Move to (-1,0)", "x-1"), ("x+10", "stay"),
                              ("Move to (1,0); then stay", "x+1"),
                              ("stay; Move to (1,0)", "stay"),
                              ("I will move x+1.5", "stay"), ("unclear plan", "stay")):
            with self.subTest(raw=raw):
                self.assertEqual(parse_response(reply(raw))["normalized_action"], expected)

    def test_duplicate_fields_use_last_value_even_after_other_fields(self):
        raw = reply("x+1", message="First", memory="Earlier") + (
            "\nNext Action: y-1\nMessage: Final\nMemory: Latest\nShare: Agent1-50")
        parsed = parse_response(raw)
        self.assertEqual(parsed["normalized_action"], "y-1")
        self.assertEqual(parsed["message"], "Final")
        self.assertEqual(parsed["memory"], "Latest")
        self.assertEqual(parsed["share"], {"target_id": 1, "amount": 50})
        self.assertIn("last_field", [entry["rule"] for entry in parsed["response_repairs"]])

    def test_missing_fields_old_labels_and_markdown_are_accepted(self):
        for raw in ("x+1", "Action: x+1", "**Next Action**: x+1", "- Next Action：x + 1"):
            with self.subTest(raw=raw):
                parsed = parse_response(raw)
                self.assertEqual(parsed["normalized_action"], "x+1")
                self.assertEqual(parsed["message"], "")
        parsed = parse_response("Thought: Still thinking\nMessage: Hello")
        self.assertEqual(parsed["normalized_action"], "stay")
        self.assertEqual(parsed["thought"], "Still thinking")
        self.assertEqual(parsed["message"], "Hello")
        self.assertEqual(parsed["response_repairs"][0]["rule"], "default_stay")

    def test_unreadable_optional_operation_does_not_discard_other_fields(self):
        parsed = parse_response(reply("x+1", share="some energy", attack="Agent2 (nearby)", message="Hello"))
        self.assertIsNone(parsed["share"])
        self.assertEqual(parsed["attack"], {"target_id": 2})
        self.assertEqual(parsed["message"], "Hello")
        self.assertEqual(parsed["normalized_action"], "x+1")

    def test_action_is_not_extracted_from_thoughts_or_message(self):
        parsed = parse_response("Thoughts: I might move x+1.\nMessage: Move y-1!")
        self.assertEqual(parsed["normalized_action"], "stay")

    def test_adjacent_absolute_destinations_are_repaired_with_observed_context(self):
        for target, normalized, delta in (((14, 9), "y+1", (0, 1)), ((14, 7), "y-1", (0, -1)),
                                           ((13, 8), "x-1", (-1, 0)), ((0, 8), "x+1", (1, 0))):
            with self.subTest(target=target):
                action = f"Move to ({target[0]},{target[1]})"
                parsed = parse_response(reply(action, message="Exploring", thoughts="Looking for food"),
                                        position=(14, 8), grid_size=15)
                self.assertEqual((parsed["kind"], parsed["dx"], parsed["dy"]), ("move", *delta))
                self.assertEqual(parsed["requested_action"], action)
                self.assertEqual(parsed["normalized_action"], normalized)
                self.assertEqual(parsed["message"], "Exploring")
                self.assertEqual(parsed["thought"], "Looking for food")
                self.assertEqual(parsed["response_repairs"], [{
                    "field": "Next Action", "rule": "absolute_target_to_delta", "original": [action],
                    "normalized": normalized, "observed_position": [14, 8],
                    "target_position": list(target), "delta": list(delta), "grid_size": 15}])

    def test_absolute_destinations_wrap_in_all_four_directions(self):
        cases = [((14, 8), (0, 8), "x+1"), ((0, 8), (14, 8), "x-1"),
                 ((8, 14), (8, 0), "y+1"), ((8, 0), (8, 14), "y-1"),
                 ((0, 1), (0, 0), "y-1")]
        for position, target, expected in cases:
            with self.subTest(position=position, target=target):
                parsed = parse_response(f"Action: Move to {target}", position=position, grid_size=15)
                self.assertEqual(parsed["normalized_action"], expected)

    def test_relative_moves_keep_priority_and_unsupported_targets_are_not_paths(self):
        for action, expected in (("Move to (1,0)", "x+1"), ("Move to (0,1)", "y+1"),
                                 ("Move to (-1,0)", "x-1"), ("Move to (0,-1)", "y-1")):
            parsed = parse_response(reply(action), position=(1, 1), grid_size=15)
            self.assertEqual(parsed["normalized_action"], expected)
            self.assertEqual(parsed["response_repairs"], [])
        for action in ("Move to (14,6)", "Move to (13,7)", "Move to (14,8)",
                       "Move to (15,8)", "Move to (14,-1)", "Move to (14,9.5)",
                       "Move to (0,0)", "(14,9)", f"Move to ({'9' * 5000},8)"):
            with self.subTest(action=action[:40]):
                parsed = parse_response(reply(action, message="Preserve this"), position=(14, 8), grid_size=15)
                self.assertEqual(parsed["normalized_action"], "stay")
                self.assertEqual(parsed["message"], "Preserve this")
                self.assertNotIn("absolute_target_to_delta", [r["rule"] for r in parsed["response_repairs"]])
        self.assertEqual(parse_response(reply("Move to (14,9)"))["normalized_action"], "stay")
        for position, target, size in (((0, 0), (0, 0), 1), ((0, 1), (1, 1), 2)):
            self.assertEqual(parse_response(f"Action: Move to {target}", position=position,
                                            grid_size=size)["normalized_action"], "stay")

    def test_absolute_repairs_follow_existing_first_command_and_last_field_rules(self):
        cases = [("Move to (14,9); Stay", "y+1"), ("Stay; Move to (14,9)", "stay"),
                 ("Move to (14,9)\nNext Action: Stay", "stay"),
                 ("Stay\nNext Action: Move to (14,9)", "y+1"),
                 ("Move to (14,9); Attack: 1", "y+1"), ("Attack: 1; Move to (14,9)", "attack: 1")]
        for action, expected in cases:
            with self.subTest(action=action):
                parsed = parse_response(reply(action), position=(14, 8), grid_size=15)
                self.assertEqual(parsed["normalized_action"], expected)
                repairs = [r["rule"] for r in parsed["response_repairs"]]
                self.assertEqual("absolute_target_to_delta" in repairs, expected == "y+1")
                if "\n" in action:
                    self.assertIn("last_field", repairs)
        parsed = parse_response("Action: unclear\nThought: Move to (14,9)\nMessage: Move to (14,7)",
                                position=(14, 8), grid_size=15)
        self.assertEqual(parsed["normalized_action"], "stay")

    def test_unreadable_integer_only_skips_its_own_operation(self):
        oversized = "9" * 5000
        for share, attack in ((f"{oversized}-10", "none"), (f"1-{oversized}", oversized)):
            with self.subTest(share_length=len(share), attack_length=len(attack)):
                parsed = parse_response(reply("x+1", share=share, attack=attack, message="Hello"))
                self.assertEqual(parsed["normalized_action"], "x+1")
                self.assertEqual(parsed["message"], "Hello")
                self.assertIsNone(parsed["share"])
                self.assertIsNone(parsed["attack"])


class RepairedExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_absolute_move_executes_once_per_reply_and_survives_recording(self):
        raw = ("Action: Move to (14,9)\nMessage: None\nThought: "
               "I am at (14,8) with 20 energy. I will move south to explore.")
        sim = Simulation(num_agents=1, grid_size=15, initial_energy=20,
                         spawn_energy_count=0, energy_spawn_rate=0)
        sim.agents[0].position = (14, 8)
        session = Session(body=completion(raw))
        with tempfile.TemporaryDirectory() as directory:
            recorder = RunRecorder(directory, {**DEFAULT_PARAMS, "num_agents": 1, "grid_size": 15,
                                               "initial_energy": 20, "spawn_energy_count": 0})
            recorder.record(sim.snapshot())
            first = await sim.step(session)
            recorder.record(first)
            self.assertEqual(len(session.requests), 1)
            self.assertEqual((sim.agents[0].position, sim.agents[0].energy), ((14, 9), 18))
            self.assertEqual(first["events"][0]["raw_response"], raw)
            self.assertEqual(first["events"][0]["executed_action"], "Move to (0,1)")
            self.assertEqual(first["events"][0]["total_energy_cost"], 2)
            self.assertIn("Move to (0,1)", sim.agents[0].memory[-1])
            second = await sim.step(Session(body=completion("Action: Move to (14,10)")))
            recorder.record(second)
            self.assertEqual((sim.agents[0].position, sim.agents[0].energy), ((14, 10), 16))
            self.assertEqual(second["events"][0]["response_repairs"][0]["observed_position"], [14, 9])
            result = recorder.finish("completed", "max_steps")
            self.assertEqual(read_run(recorder.directory / "run.json")["logs"], result["logs"])
            self.assertEqual(result["summary"]["repaired_decisions"], 2)
            with (recorder.directory / "events.csv").open() as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["requested_action"], "Move to (14,9)")
            self.assertEqual(json.loads(row["response_repairs"])[0]["delta"], [0, 1])

    async def test_repaired_decision_moves_sends_and_remembers_with_one_request_per_agent(self):
        raw = reply("x+1, y-1 (Note: I must choose one.)\nNext Action: x+1", message="Heading east.",
                    thoughts="I can collect food.", memory="Look east again.")
        sim = Simulation(num_agents=2, spawn_energy_count=0, energy_spawn_rate=0)
        sim.agents[0].position, sim.agents[1].position = (0, 0), (1, 0)
        session = Session(body=completion(raw))
        snapshot = await sim.step(session)
        self.assertEqual(len(session.requests), 2)
        self.assertEqual([a.position for a in sim.agents], [(1, 0), (2, 0)])
        self.assertEqual([a.energy for a in sim.agents], [98, 98])
        self.assertEqual(snapshot["summary"]["valid_decisions"], 2)
        self.assertEqual(snapshot["summary"]["repaired_decisions"], 2)
        self.assertEqual(snapshot["step_stats"]["repaired_decisions"], 2)
        self.assertEqual(snapshot["summary"]["parse_errors"], 0)
        for agent, event in zip(sim.agents, snapshot["events"]):
            self.assertEqual(event["decision_source"], "llm")
            self.assertEqual(event["decision_status"], "ok")
            self.assertEqual(event["action_status"], "executed")
            self.assertEqual(event["message_status"], "sent")
            self.assertEqual(event["error_kind"], "")
            self.assertEqual(event["raw_response"], raw)
            self.assertEqual(event["response_repairs"][0]["normalized"], "x+1")
            self.assertEqual(agent.next_messages, [f"Agent{1-agent.id}: Heading east."])
            self.assertEqual(agent.memory, ["Step 1: Move to (1,0); I can collect food."])
            self.assertEqual(event["response_memory"], "Look east again.")

    async def test_partial_reply_and_bad_optional_field_keep_usable_action(self):
        for raw, finish in ((reply("x+1, y-1"), "stop"),
                            (reply("x + 1", share="bad share"), "stop"),
                            (reply("x + 1", message="Heading east."), "length")):
            with self.subTest(finish=finish, raw=raw):
                sim = Simulation(num_agents=1, spawn_energy_count=0, energy_spawn_rate=0)
                position = sim.agents[0].position
                event = (await sim.step(Session(body=completion(raw, finish))))["events"][0]
                self.assertEqual(sim.agents[0].position, ((position[0] + 1) % sim.grid_size, position[1]))
                self.assertEqual(event["error_kind"], "")
                self.assertEqual(event["decision_source"], "llm")
                self.assertEqual(event["finish_reason"], finish)
                self.assertEqual(event["raw_response"], raw)
                self.assertEqual(sim.stats["repaired_decisions"], 1)
                if finish == "length":
                    self.assertIn("partial_response", [r["rule"] for r in event["response_repairs"]])

    async def test_long_partial_reply_keeps_all_available_text_without_an_action(self):
        thoughts = "考え中です。" * 50
        raw = f"Summary: Food nearby\nThoughts: {thoughts}"
        sim = Simulation(num_agents=1, spawn_energy_count=0, energy_spawn_rate=0)
        event = (await sim.step(Session(body=completion(raw, "length"))))["events"][0]
        self.assertEqual(event["decision_source"], "llm")
        self.assertEqual(event["decision_status"], "ok")
        self.assertEqual(event["executed_action"], "Stay")
        self.assertEqual(event["thought"], thoughts)
        self.assertEqual(event["raw_response"], raw)
        self.assertEqual(event["message"], "")
        self.assertEqual(sim.stats["llm_errors"], 0)

    async def test_unusable_usage_does_not_discard_reply_or_break_recording(self):
        for usage in ([1], {"prompt_tokens": float("nan"), "completion_tokens": {"unexpected": True}},
                      {"prompt_tokens": "20", "completion_tokens": float("inf")}):
            with self.subTest(usage=usage), tempfile.TemporaryDirectory() as directory:
                body = json.loads(completion(reply("x+1", message="Hello")))
                body["usage"] = usage
                sim = Simulation(num_agents=1, spawn_energy_count=0, energy_spawn_rate=0)
                recorder = RunRecorder(directory, {**DEFAULT_PARAMS, "num_agents": 1, "num_steps": 1})
                recorder.record(sim.snapshot())
                snapshot = await sim.step(Session(body=json.dumps(body)))
                recorder.record(snapshot)
                result = recorder.finish("completed", "max_steps")
                event = result["logs"][1]["events"][0]
                self.assertEqual(event["decision_source"], "llm")
                self.assertEqual(event["normalized_action"], "x+1")
                self.assertEqual(event["message"], "Hello")
                self.assertIsNone(event["prompt_tokens"])
                self.assertIsNone(event["completion_tokens"])

    async def test_repairs_round_trip_through_journal_csv_and_aggregate(self):
        raw = reply("x+1, y-1\nx+1", message="Heading east.")
        sim = Simulation(num_agents=1, spawn_energy_count=0, energy_spawn_rate=0)
        with tempfile.TemporaryDirectory() as directory:
            recorder = RunRecorder(directory, {**DEFAULT_PARAMS, "num_agents": 1, "num_steps": 1})
            recorder.record(sim.snapshot())
            recorder.record(await sim.step(Session(body=completion(raw))))
            result = recorder.finish("completed", "max_steps")
            self.assertEqual(read_run(recorder.directory / "run.json")["logs"], result["logs"])
            self.assertEqual(result["schema_version"], 7)
            self.assertEqual(result["engine_version"], "5.4")
            self.assertEqual(result["protocol"]["response_handling"]["version"], 5)
            event = result["logs"][1]["events"][0]
            self.assertEqual(event["raw_response"], raw)
            with (recorder.directory / "events.csv").open() as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["normalized_action"], "x+1")
            self.assertEqual(json.loads(row["response_repairs"]), event["response_repairs"])
            self.assertEqual(row["requested_action"], "x+1, y-1\nx+1")
            with (recorder.directory / "steps.csv").open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([r["repaired_decisions"] for r in rows], ["0", "1"])
            self.assertEqual(rows[1]["repaired_decisions_this_step"], "1")
            path, count = collect_runs(directory)
            self.assertEqual(count, 1)
            with path.open() as handle:
                self.assertEqual(next(csv.DictReader(handle))["repaired_decisions"], "1")

    def test_old_runs_keep_old_execution_and_csv_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "old-run"
            shutil.copytree(ROOT / "examples/first-look", copied)
            before = read_run(copied / "run.json")
            with (copied / "events.csv").open() as handle:
                old_event_columns = next(csv.reader(handle))
            with (copied / "steps.csv").open() as handle:
                old_step_columns = next(csv.reader(handle))
            after = export_run(copied)
            self.assertEqual(after["logs"], before["logs"])
            self.assertNotIn("repaired_decisions", after["summary"])
            self.assertEqual(after["engine_version"], before["engine_version"])
            with (copied / "events.csv").open() as handle:
                self.assertEqual(next(csv.reader(handle)), old_event_columns)
            with (copied / "steps.csv").open() as handle:
                self.assertEqual(next(csv.reader(handle)), old_step_columns)

    def test_schema_four_preserves_repairs_without_adding_turn_cost_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "v4-run"
            shutil.copytree(ROOT / "examples/first-look", copied)
            manifest = json.loads((copied / "manifest.json").read_text())
            manifest.update(schema_version=4, engine_version="4.0")
            (copied / "manifest.json").write_text(json.dumps(manifest))
            snapshots = [json.loads(line) for line in (copied / "steps.jsonl").read_text().splitlines()]
            repair = {"field": "Action", "rule": "default_stay", "original": ["unclear"], "normalized": "stay"}
            for snap in snapshots:
                snap["schema_version"] = 4
                for event in snap["events"]:
                    event.update(normalized_action="stay", response_repairs=[repair])
            (copied / "steps.jsonl").write_text("".join(json.dumps(snap) + "\n" for snap in snapshots))
            result = export_run(copied)
            self.assertEqual(read_run(copied / "run.json")["logs"], result["logs"])
            self.assertEqual(result["engine_version"], "4.0")
            with (copied / "events.csv").open() as handle:
                reader = csv.DictReader(handle)
                self.assertIn("response_repairs", reader.fieldnames)
                self.assertIn("normalized_action", reader.fieldnames)
                self.assertFalse(any(name.startswith("turn_energy_") for name in reader.fieldnames))
                self.assertNotIn("total_energy_cost", reader.fieldnames)
                self.assertEqual(json.loads(next(reader)["response_repairs"]), [repair])


if __name__ == "__main__":
    unittest.main()
