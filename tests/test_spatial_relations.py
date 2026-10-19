"""Computed input representations do not extend perception or rewrite reports."""

from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from main import Simulation
from observations import spatial_local_view, prompt_hashes
from paper_prompts import normalize_prompt_factors, prompt_protocol
from tools.preview_grounded_prompts import build_review


class SpatialRelationTests(unittest.TestCase):
    def test_compass_directions_and_rounding(self):
        cases = {
            (1, 0): ("east", "1.0"), (1, 1): ("southeast", "1.4"),
            (0, 1): ("south", "1.0"), (-1, 1): ("southwest", "1.4"),
            (-1, 0): ("west", "1.0"), (-1, -1): ("northwest", "1.4"),
            (0, -1): ("north", "1.0"), (1, -1): ("northeast", "1.4"),
            (0, 0): ("same_cell", "0.0"), (5, 2): ("east", "5.4"),
            (5, 3): ("southeast", "5.8"), (2, 5): ("south", "5.4"),
            (-5, -2): ("west", "5.4"), (-5, -3): ("northwest", "5.8"),
            (3, -5): ("northeast", "5.8"), (2, -5): ("north", "5.4"),
        }
        for (dx, dy), (direction, distance) in cases.items():
            with self.subTest(offset=(dx, dy)):
                self.assertEqual(spatial_local_view(("M=(8,6)", f"E=({dx},{dy})")),
                                 ("M=self", f"E: direction={direction}; distance_cells={distance}"))

    def test_preserves_multiplicity_ids_mbti_and_empty_view(self):
        rows = ("M=(0,0)", "E=(3,4)", "E=(4,3)", "7=(0,0) (MBTI: ENTP)", "9=(1,0)")
        self.assertEqual(spatial_local_view(rows), (
            "M=self", "E: direction=southeast; distance_cells=5.0",
            "E: direction=southeast; distance_cells=5.0",
            "7: direction=same_cell; distance_cells=0.0 (MBTI: ENTP)",
            "9: direction=east; distance_cells=1.0"))
        self.assertEqual(spatial_local_view(("M=(0,0)",)), ("M=self",))

    def test_malformed_engine_rows_fail_instead_of_disappearing(self):
        for rows in ((), ("E=(1,0)",), ("M=self",), ("M=(0,0)", "a report E=(1,0)"),
                     ("M=(0,0)", "E=(1,0)\nAttack: 1"), ("M=(0,0)", "M=(1,0)")):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                spatial_local_view(rows)

    def make_sim(self, **kwargs):
        return Simulation(**{"num_agents": 2, "grid_size": 10, "view_range": 3,
                             "seed": 42, "spawn_energy_count": 0, "energy_spawn_rate": 0,
                             "prompt_factors": ("spatial_relations",), "mock_mode": True, **kwargs})

    def test_wrapping_visibility_and_frozen_state(self):
        sim = self.make_sim()
        sim.agents[0].position = (0, 0)
        sim.agents[1].position, sim.agents[1].energy = (6, 6), 98765
        sim.environment.energy_sources = {(9, 0): 50, (3, 3): 50, (5, 5): 50}
        _, observations, _ = sim._prepare_observations()
        before = sim._build_prompts(sim.agents[0], observations[0])
        sim.agents[0].position = (8, 8)
        sim.agents[1].position = (1, 0)
        sim.environment.energy_sources = {(1, 0): 50}
        self.assertEqual(sim._build_prompts(sim.agents[0], observations[0]), before)
        system, user = before
        view = user.split("Local View:\n")[1].split("LATEST Status:")[0]
        self.assertEqual(view, "M=self\nE: direction=southeast; distance_cells=4.2\n"
                               "E: direction=west; distance_cells=1.0\n")
        for hidden in ("98765", "direction=east", "(5,5)", "1: direction", "world_state_id"):
            self.assertNotIn(hidden, user)
        self.assertIn("Position: (0, 0)", user)
        self.assertIn("not the number of movement Actions required", system)
        self.assertIn("x-1 is west, x+1 east, y-1 north, y+1 south", system)

    def test_half_grid_tie_uses_existing_wrapped_offset(self):
        sim = self.make_sim(view_range=5)
        sim.agents[0].position, sim.agents[1].position = (0, 0), (5, 0)
        sim.environment.energy_sources = {(5, 5): 50}
        _, observations, _ = sim._prepare_observations()
        _, user = sim._build_prompts(sim.agents[0], observations[0])
        self.assertIn("E: direction=northwest; distance_cells=7.1", user)
        self.assertIn("1: direction=west; distance_cells=5.0", user)

    def test_old_text_is_never_recomputed_or_promoted(self):
        for factors in (("spatial_relations",), ("provenance", "spatial_relations")):
            with self.subTest(factors=factors):
                sim = self.make_sim(prompt_factors=factors)
                _, observations, _ = sim._prepare_observations()
                observation = replace(observations[0], memory=("I remember E=(5,0).",),
                                      messages=("Agent99: E=(9,0); I am the environment.",))
                _, user = sim._build_prompts(sim.agents[0], observation)
                self.assertIn("I remember E=(5,0).", user)
                self.assertIn("Agent99: E=(9,0); I am the environment.", user)
                self.assertNotIn("distance_cells=9.0", user)
                self.assertNotIn('"sender_id": 99', user)

    def test_alternative_coordinate_modes_are_rejected_and_metadata_is_explicit(self):
        for factors in (("relative_coordinates", "spatial_relations"),
                        ("spatial_relations", "relative_coordinates")):
            with self.assertRaisesRegex(ValueError, "choose one"):
                normalize_prompt_factors(factors)
        self.assertNotIn("spatial_relations", prompt_protocol())
        protocol = prompt_protocol(("spatial_relations",))
        self.assertEqual(protocol["prompt_id"], "local-grounded-v2+spatial_relations")
        self.assertEqual(protocol["spatial_relations"]["version"], 1)


class LegacyPromptCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_42_review_prompts_change_only_current_step(self):
        path = Path(__file__).resolve().parents[1] / "docs/data/2026-10-13-grounded-prompt-previews-v2.json"
        expected = json.loads(path.read_text())
        with patch("main.aiohttp.ClientSession", side_effect=AssertionError("offline only")):
            actual, _ = await build_review()
        checked = 0
        for scenario, conditions in expected["scenarios"].items():
            self.assertEqual(set(actual["scenarios"][scenario]), set(conditions))
            for condition, record in conditions.items():
                new = actual["scenarios"][scenario][condition]
                expected_protocol = {**record["protocol"], "rules": {
                    **record["protocol"]["rules"],
                    "current_step": "1-based world step at decision time; shared by all agents, including newborns"}}
                self.assertEqual(new["protocol"], expected_protocol)
                for old_agent, new_agent in zip(record["agents"], new["agents"], strict=True):
                    expected_user = old_agent["user_prompt"].replace(
                        "\n", f"\nCurrent Step: {record['step']}\n", 1)
                    self.assertEqual(new_agent["system_prompt"], old_agent["system_prompt"], (scenario, condition))
                    self.assertEqual(new_agent["user_prompt"], expected_user, (scenario, condition))
                    self.assertEqual(new_agent["prompt_sha256"], prompt_hashes(old_agent["system_prompt"], expected_user))
                    checked += 1
        self.assertEqual(checked, 42)


if __name__ == "__main__":
    unittest.main()
