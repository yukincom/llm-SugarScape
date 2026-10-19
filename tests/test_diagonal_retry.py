"""Same-turn replacement must not execute or remember a rejected reply."""

import asyncio
import csv
import json
import tempfile
import unittest

from main import DEFAULT_PARAMS, Simulation, parse_response
from paper_prompts import diagonal_move_feedback
from response_fields import cardinal_destinations
from run_data import RunRecorder, export_run, read_run
from test_simulation import Response, completion


BAD = "Action: [Move to (1,1)]\nMessage: [Rejected message]\nThought: [Rejected thought]"
GOOD = "Action: [(0,10)]\nMessage: [Chosen message]\nThought: [Chosen thought]"


class SequenceSession:
    def __init__(self, responses, inspect=None):
        self.responses = list(responses)
        self.requests = []
        self.inspect = inspect

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if self.inspect:
            self.inspect(len(self.requests), kwargs["json"])
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def response(raw):
    return Response(200, completion(raw))


class DiagonalRetryTests(unittest.IsolatedAsyncioTestCase):
    def simulation(self, **params):
        sim = Simulation(num_agents=2, grid_size=15, initial_energy=20, spawn_energy_count=0,
                         energy_spawn_rate=0, **params)
        sim.agents[0].position = (14, 10)
        sim.agents[1].position = (1, 10)
        return sim

    async def test_replacement_executes_once_and_only_final_prose_is_used(self):
        sim = self.simulation()
        def inspect(count, body):
            self.assertEqual(sim.step_count, 1)
            self.assertIn("\nCurrent Step: 1\n", body["messages"][1]["content"])
            self.assertEqual(sim.agents[0].position, (14, 10))
            self.assertEqual(sim.agents[0].energy, 20)
            self.assertEqual(sim.agents[0].age, 0)
            self.assertEqual(sim.agents[0].memory, [])
            self.assertEqual(sim.agents[1].next_messages, [])
            if count == 2:
                self.assertEqual([m["role"] for m in body["messages"]], ["system", "user", "assistant", "user"])
                self.assertEqual(body["messages"][2]["content"], BAD)
                self.assertIn("- (0,10)\n- (14,11)", body["messages"][3]["content"])
                self.assertNotIn("(13,10)", body["messages"][3]["content"])
                self.assertNotIn("(14,9)", body["messages"][3]["content"])
        session = SequenceSession([response(BAD), response(GOOD), response("Action: Stay")], inspect)
        snapshot = await sim.step(session)
        event = snapshot["events"][0]
        self.assertEqual(len(session.requests), 3)
        self.assertEqual(session.requests[0][1]["json"]["messages"], session.requests[1][1]["json"]["messages"][:2])
        self.assertEqual(sim.agents[0].position, (0, 10))
        self.assertEqual((sim.agents[0].energy, sim.agents[0].age), (18, 1))
        self.assertEqual(sim.agents[0].memory, ["Step 1: Move to (1,0); Chosen thought"])
        self.assertEqual(sim.agents[1].next_messages, ["Agent0: Chosen message"])
        self.assertEqual((snapshot["summary"]["total_actions"], event["total_energy_cost"]), (2, 2))
        self.assertEqual((event["retry_count"], event["llm_request_count"], event["retry_status"]), (1, 2, "corrected"))
        self.assertEqual((event["prompt_tokens"], event["completion_tokens"]), (40, 20))
        self.assertEqual([a["raw_response"] for a in event["decision_attempts"]], [BAD, GOOD])
        self.assertEqual([a["validation_status"] for a in event["decision_attempts"]], ["rejected", "accepted"])

    async def test_invalid_retry_and_transport_errors_do_not_loop_or_send_prose(self):
        for failed in (response(BAD), response("Action: (2,2)\nMessage: no"),
                       response("Action: Stay\nMessage: no"), Response(503, "unavailable"),
                       asyncio.TimeoutError()):
            with self.subTest(failed=type(failed).__name__):
                sim = self.simulation()
                session = SequenceSession([response(BAD), failed, response("Action: Stay")])
                snapshot = await sim.step(session)
                event = snapshot["events"][0]
                self.assertEqual(len(session.requests), 3)
                self.assertEqual((sim.agents[0].position, sim.agents[0].energy), ((14, 10), 19))
                self.assertEqual((event["retry_status"], event["decision_source"], event["executed_action"]),
                                 ("failed", "fallback", "Stay"))
                self.assertEqual(sim.agents[1].next_messages, [])
                self.assertEqual(sim.agents[0].memory, ["Step 1: Stay; "])
                self.assertEqual(event["message"], "")
                if event["error_kind"] == "invalid_action":
                    self.assertEqual(snapshot["summary"]["rejected_actions"], 1)
                    self.assertEqual(snapshot["summary"]["llm_errors"], 0)

    async def test_cancel_during_retry_propagates_without_executing(self):
        sim = self.simulation()
        with self.assertRaises(asyncio.CancelledError):
            await sim.step(SequenceSession([response(BAD), asyncio.CancelledError()]))
        self.assertEqual((sim.agents[0].position, sim.agents[0].energy, sim.agents[0].age), ((14, 10), 20, 0))
        self.assertEqual(sim.logs, [])

    async def test_ordinary_legal_absolute_or_unreadable_responses_do_not_retry(self):
        for action in ("Move to (0,1)", "Move to (14,11)", "Stay", "unknown",
                       "Move to (1,1); Move to (1,0)"):
            sim = self.simulation()
            session = SequenceSession([response(f"Action: {action}"), response("Action: Stay")])
            event = (await sim.step(session))["events"][0]
            self.assertEqual((len(session.requests), event["retry_count"]), (2, 0))
        parsed = parse_response(BAD, position=(1, 0), grid_size=15)
        self.assertEqual(parsed["normalized_action"], "y+1")
        self.assertNotIn("diagonal_move_rejected", [r["rule"] for r in parsed["response_repairs"]])

    def test_retry_coordinates_are_absolute_even_when_they_look_relative(self):
        choices = cardinal_destinations((1, 1), 15, toward_delta=(-1, -1))
        parsed = parse_response("Action: [(1,0)]", position=(1, 1), grid_size=15, destination_choices=choices)
        self.assertEqual((parsed["dx"], parsed["dy"]), (0, -1))
        for raw in ("(5,5)", "(1,0); (0,1)", "(1,1)", "x+1", "Stay"):
            parsed = parse_response(f"Action: {raw}", position=(1, 1), grid_size=15, destination_choices=choices)
            self.assertEqual(parsed["response_repairs"][0]["rule"], "invalid_destination_selection")

    def test_every_offered_destination_maps_to_one_legal_step_on_wrapped_small_grids(self):
        for size in (1, 2, 3, 15):
            for position in ((0, 0), (size-1, size-1)):
                choices = cardinal_destinations(position, size)
                self.assertEqual(len(choices), len({tuple(c["position"]) for c in choices}))
                for choice in choices:
                    x, y = choice["position"]
                    parsed = parse_response(f"Action: ({x},{y})", position=position,
                                            grid_size=size, destination_choices=choices)
                    self.assertEqual(abs(parsed["dx"]) + abs(parsed["dy"]), 1)
                    self.assertEqual([(position[0]+parsed["dx"]) % size, (position[1]+parsed["dy"]) % size], [x,y])

    def test_feedback_preserves_field_order_and_uses_only_calculated_coordinates(self):
        choices = cardinal_destinations((14, 10), 15, toward_delta=(1, 1))
        feedback = diagonal_move_feedback((14, 10), choices, ("action_last", "grounded_thought"))
        self.assertLess(feedback.index("Thought: ["), feedback.index("Message: ["))
        self.assertLess(feedback.index("Message: ["), feedback.index("Action: ["))
        self.assertIn("Choose exactly one coordinate pair from this list.", feedback)
        self.assertNotIn("east =", feedback)

    def test_only_the_two_requested_axis_directions_are_offered(self):
        for position in ((7, 7), (0, 0), (14, 14)):
            for dx, dy in ((1,1), (-1,1), (-1,-1), (1,-1)):
                raw = f"Action: Move to ({dx},{dy})"
                parsed = parse_response(raw, position=position, grid_size=15)
                rejection = next(r for r in parsed["response_repairs"] if r["rule"] == "diagonal_move_rejected")
                choices = cardinal_destinations(position, 15, toward_delta=rejection["requested_delta"])
                self.assertEqual([c["position"] for c in choices],
                                 [[(position[0]+dx)%15,position[1]], [position[0],(position[1]+dy)%15]])
                self.assertEqual(len(choices), 2)
        # A two-cell axis wraps both ways; filter before deduplicating.
        self.assertEqual(cardinal_destinations((0,0), 2, toward_delta=(-1,-1)),
                         [{"position":[1,0], "delta":[-1,0]}, {"position":[0,1], "delta":[0,-1]}])

    async def test_attempt_evidence_survives_json_csv_and_legacy_export(self):
        sim = self.simulation()
        with tempfile.TemporaryDirectory() as root:
            recorder = RunRecorder(root, {**DEFAULT_PARAMS, "num_agents": 2, "grid_size": 15})
            recorder.record(sim.snapshot())
            recorder.record(await sim.step(SequenceSession([response(BAD), response(GOOD), response("Action: Stay")])))
            result = recorder.finish("completed", "max_steps")
            self.assertEqual(read_run(recorder.directory / "run.json")["logs"], result["logs"])
            self.assertEqual(result["protocol"]["response_handling"]["retries"], 1)
            with (recorder.directory / "events.csv").open() as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(json.loads(row["decision_attempts"]), result["logs"][1]["events"][0]["decision_attempts"])
            self.assertEqual((row["retry_count"], row["llm_request_count"]), ("1", "2"))
            # Version 6 keeps its original CSV layout when exported again.
            manifest_path = recorder.directory / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["schema_version"] = 6
            manifest_path.write_text(json.dumps(manifest))
            journal = recorder.directory / "steps.jsonl"
            snapshots = [json.loads(line) for line in journal.read_text().splitlines()]
            for snapshot in snapshots:
                snapshot["schema_version"] = 6
            journal.write_text("\n".join(json.dumps(s) for s in snapshots)+"\n")
            export_run(recorder.directory)
            with (recorder.directory / "events.csv").open() as handle:
                self.assertNotIn("decision_attempts", csv.DictReader(handle).fieldnames)


if __name__ == "__main__":
    unittest.main()
