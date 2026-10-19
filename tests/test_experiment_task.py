import asyncio
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from experiment_task import ExperimentTask
from main import DEFAULT_PARAMS, main, Simulation
from run_data import read_run


class ExperimentTaskTests(unittest.TestCase):
    def test_live_dialogue_appends_immediately_then_updates_only_its_final_faces(self):
        task = ExperimentTask(main, {**DEFAULT_PARAMS, "mock_mode": True})
        initial = {"step": 0, "events": [], "agents": [
            {"id": 0, "energy": 60, "alive": True},
            {"id": 1, "energy": 100, "alive": True},
            {"id": 2, "energy": 1, "alive": True}]}
        task._on_snapshot(initial)
        for agent_id in range(3):
            task._on_decision(1, {"agent_id": agent_id, "message": "Pending"})
        state = task.state()
        self.assertEqual(state["snapshot"], initial)
        self.assertEqual(len(state["recent"]), 3)
        self.assertEqual([text.splitlines()[0] for text in state["recent"]],
                         ["Step 1 · 🙂 エージェント 00", "Step 1 · 🙂 エージェント 01", "Step 1 · 😱 エージェント 02"])
        self.assertTrue(all("（行動前）" not in text and "💬 Pending" in text for text in state["recent"]))
        self.assertEqual(state["decision_progress"], (1, 3, 3))
        completed = {"step": 1, "agents": [
            {"id": 0, "energy": 40, "alive": True},
            {"id": 1, "energy": 150, "alive": True},
            {"id": 2, "energy": 0, "alive": False}], "events": [
                {"agent_id": 0, "share_status": "executed", "message": "Shared"},
                {"agent_id": 1, "attack_status": "executed", "executed_attack": "2", "message": "Attacked"},
                {"agent_id": 2, "message": "Last message"}]}
        before = deepcopy(completed)
        task._on_snapshot(completed)
        state = task.state()
        self.assertIsNone(state["decision_progress"])
        self.assertEqual([line.splitlines()[0] for line in state["recent"]],
                         ["Step 1 · 😘 エージェント 00", "Step 1 · 😡 エージェント 01", "Step 1 · 😇😭 エージェント 02"])
        task._on_decision(2, {"agent_id": 0, "message": "New pending"})
        self.assertEqual(task.state()["recent"][:-1], state["recent"])
        self.assertIn("Step 2 · 😱 エージェント 00\n💬 New pending", task.state()["recent"][-1])
        self.assertEqual(task.state()["snapshot"], completed)
        self.assertEqual(task.state()["decision_progress"], (2, 1, 2))
        following = deepcopy(completed)
        following["step"] = 2
        following["agents"][0]["energy"] = 39
        following["events"] = [{"agent_id": 0, "message": "New pending"}]
        task._on_snapshot(following)
        self.assertEqual(task.state()["recent"][:-1], state["recent"])
        self.assertEqual(task.state()["recent"][-1], "Step 2 · 😱 エージェント 00\n💬 New pending\n💭 （記録なし）")
        self.assertEqual(completed, before)

    def test_finalizing_a_large_turn_keeps_the_last_ten_responses_in_order(self):
        task = ExperimentTask(main, {**DEFAULT_PARAMS, "mock_mode": True})
        initial = {"step": 0, "events": [], "agents": [
            {"id": i, "energy": 100, "alive": True} for i in range(15)]}
        task._on_snapshot(initial)
        events = [{"agent_id": i, "message": f"Message {i}"} for i in range(15)]
        for event in events:
            task._on_decision(1, event)
        self.assertEqual(len(task.state()["recent"]), 10)
        task._on_snapshot({**initial, "step": 1, "events": events})
        self.assertEqual([text.splitlines()[1] for text in task.state()["recent"]],
                         [f"💬 Message {i}" for i in range(5, 15)])
        self.assertFalse(any("行動前" in text for text in task.state()["recent"]))
        task._on_decision(2, {"agent_id": 0, "message": "Next turn"})
        self.assertEqual(len(task.state()["recent"]), 10)
        self.assertIn("Step 2 · 🙂 エージェント 00", task.state()["recent"][-1])

    def start_task(self, directory, **params):
        task = ExperimentTask(main, {**DEFAULT_PARAMS, "output_dir": directory, "mock_mode": True,
                                     "num_agents": 1, "num_steps": 3, **params})
        self.addCleanup(lambda: (task.stop(), task.done.wait(5)))
        task.start()
        return task

    def test_stop_before_start_creates_no_record(self):
        with tempfile.TemporaryDirectory() as directory:
            task = ExperimentTask(main, {**DEFAULT_PARAMS, "output_dir": directory, "mock_mode": True})
            task.stop()
            task.start()
            self.assertTrue(task.done.wait(5))
            self.assertIsNone(task.state()["result"])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_stop_cancels_waiting_request_and_keeps_only_completed_turns(self):
        waiting = threading.Event()
        cancelled = threading.Event()
        original = Simulation._request_decision
        async def delayed(sim, *args):
            if sim.step_count == 2:
                waiting.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return await original(sim, *args)

        with tempfile.TemporaryDirectory() as directory, patch.object(Simulation, "_request_decision", delayed):
            task = self.start_task(directory)
            self.assertTrue(waiting.wait(5))
            task.stop()
            task.stop()
            self.assertTrue(task.done.wait(5))
            self.assertTrue(cancelled.is_set())
            result = task.state()["result"]
            self.assertEqual(result["status"], "interrupted")
            self.assertEqual([snap["step"] for snap in result["logs"]], [0, 1])
            reread = read_run(Path(result["output_dir"]) / "run.json")
            self.assertEqual(reread["summary"], result["logs"][1]["summary"])
            self.assertEqual(reread["termination_reason"], "user_stop")

    def test_synchronous_mock_honors_stop_flag_after_completed_turn(self):
        stopped = threading.Event()
        def on_snapshot(snapshot):
            if snapshot["step"] == 1:
                stopped.set()
        with tempfile.TemporaryDirectory() as directory:
            result = asyncio.run(main(params={"output_dir": directory, "mock_mode": True, "num_steps": 20},
                                      on_snapshot=on_snapshot, stop_requested=stopped.is_set))
            self.assertEqual(result["status"], "interrupted")
            self.assertEqual(result["logs"][-1]["step"], 1)

    def test_translation_stop_preserves_completed_experiment(self):
        translating = threading.Event()
        async def run_mock(**kwargs):
            kwargs["params"] = {**kwargs["params"], "mock_mode": True}
            result = await main(**kwargs)
            return result
        async def delayed_translation(*args, **kwargs):
            translating.set()
            await asyncio.Event().wait()
        with tempfile.TemporaryDirectory() as directory, \
                patch("experiment_task.translate_result", side_effect=delayed_translation):
            task = ExperimentTask(run_mock, {**DEFAULT_PARAMS, "output_dir": directory, "num_steps": 1})
            self.addCleanup(lambda: (task.stop(), task.done.wait(5)))
            task.start()
            self.assertTrue(translating.wait(5))
            result = task.state()["result"]
            original = (Path(result["output_dir"]) / "run.json").read_bytes()
            task.stop()
            self.assertTrue(task.done.wait(5))
            self.assertEqual(task.state()["result"]["status"], "completed")
            self.assertIn("翻訳を停止", task.state()["notice"])
            self.assertEqual((Path(result["output_dir"]) / "run.json").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
