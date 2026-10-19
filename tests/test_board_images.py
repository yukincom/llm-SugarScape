from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

from grid_view import draw_grid
from main import Simulation, main


class BoardImageTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_saves_initial_and_every_completed_board(self):
        with tempfile.TemporaryDirectory() as directory:
            result = await main(params={"output_dir": directory, "mock_mode": True,
                                        "num_agents": 2, "num_steps": 3})
            self.assertEqual(result["status"], "completed")
            images = Path(result["output_dir"]) / "img"
            self.assertEqual(sorted(path.name for path in images.iterdir()),
                             ["step000.png", "step001.png", "step002.png", "step003.png"])
            for snapshot in result["logs"]:
                with Image.open(images / f"step{snapshot['step']:03d}.png") as image:
                    self.assertEqual(image.format, "PNG")
                    self.assertEqual(image.size, (888, 888))
                    image.load()

    async def test_zero_steps_and_extinction_keep_the_final_numbered_board(self):
        for params, steps in (({"num_steps": 0}, [0]),
                              ({"num_steps": 8, "initial_energy": 1,
                                "spawn_energy_count": 0, "energy_spawn_rate": 0}, [0, 1])):
            with self.subTest(params=params), tempfile.TemporaryDirectory() as directory:
                result = await main(params={"output_dir": directory, "mock_mode": True,
                                            "num_agents": 1, **params})
                self.assertEqual([snapshot["step"] for snapshot in result["logs"]], steps)
                self.assertEqual(sorted(path.name for path in (Path(result["output_dir"]) / "img").iterdir()),
                                 [f"step{step:03d}.png" for step in steps])

    async def test_stop_and_callback_failure_keep_only_recorded_boards(self):
        for fail in (False, True):
            stopped = False
            def on_snapshot(snapshot):
                nonlocal stopped
                if snapshot["step"] == 1:
                    stopped = True
                    if fail:
                        raise RuntimeError("display failed")
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                result = await main(params={"output_dir": directory, "mock_mode": True,
                                            "num_agents": 1, "num_steps": 5},
                                    on_snapshot=on_snapshot, stop_requested=lambda: stopped)
                self.assertEqual(result["status"], "failed" if fail else "interrupted")
                self.assertEqual(sorted(path.name for path in (Path(result["output_dir"]) / "img").iterdir()),
                                 ["step000.png", "step001.png"])
                self.assertEqual([snapshot["step"] for snapshot in result["logs"]], [0, 1])

    async def test_explicit_opt_out_keeps_data_without_images(self):
        with tempfile.TemporaryDirectory() as directory:
            result = await main(params={"output_dir": directory, "mock_mode": True,
                                        "num_agents": 1, "num_steps": 1, "save_images": False})
            self.assertEqual(result["status"], "completed")
            self.assertFalse((Path(result["output_dir"]) / "img").exists())
            self.assertTrue((Path(result["output_dir"]) / "steps.jsonl").is_file())

    def test_image_uses_recorded_events_for_attack_and_damage_faces(self):
        sim = Simulation(num_agents=2, mock_mode=True, spawn_energy_count=0)
        snapshot = sim.snapshot(events=[{"agent_id": 0, "decision_status": "ok",
                                        "executed_action": "Attack", "attack_status": "executed",
                                        "executed_attack": "1"}])
        with tempfile.TemporaryDirectory() as directory:
            actual, expected = Path(directory) / "actual.png", Path(directory) / "expected.png"
            sim.visualize(actual, snapshot)
            fig = draw_grid(snapshot, sim.grid_size, sim.reproduce_cost)
            fig.savefig(expected, dpi=120)
            fig.clear()
            with Image.open(actual) as left, Image.open(expected) as right:
                self.assertEqual(left.tobytes(), right.tobytes())
            neutral = Path(directory) / "neutral.png"
            sim.visualize(neutral)
            with Image.open(actual) as left, Image.open(neutral) as right:
                self.assertNotEqual(left.tobytes(), right.tobytes())

    def test_cli_saves_by_default_and_supports_no_images(self):
        root = Path(__file__).resolve().parents[1]
        for options, expected in (([], True), (["--no-images"], False)):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run([sys.executable, str(root / "main.py"), "run", "--mock",
                                         "--agents", "1", "--steps", "1", "--output", directory, *options],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(bool(list(Path(directory).glob("*/img/step001.png"))), expected)


if __name__ == "__main__":
    unittest.main()
