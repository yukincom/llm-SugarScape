"""Identity formatting preserves the frozen evidence and existing experiment inputs."""

from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from main import Simulation
from observations import identified_observation
from paper_prompts import APPLICATION_USER_INSTRUCTIONS, normalize_prompt_factors, prompt_protocol
from tools.preview_grounded_prompts import build_identity_review, build_spatial_review


class SelfOtherIdentityTests(unittest.TestCase):
    def make_sim(self, factors=("spatial_relations", "self_other_identity")):
        sim = Simulation(num_agents=3, grid_size=10, view_range=3, seed=42, initial_energy=20,
                         spawn_energy_count=0, energy_spawn_rate=0, mock_mode=True, prompt_factors=factors)
        sim.agents[0].position, sim.agents[1].position, sim.agents[2].position = (0, 0), (9, 0), (6, 6)
        sim.agents[1].energy, sim.agents[2].energy = 98765, 87654
        sim.agents[1].mbti_type = "ENTP"
        sim.environment.energy_sources = {(9, 0): 50, (2, 3): 50, (3, 2): 50, (5, 5): 50}
        return sim

    def packet(self, sim):
        _, observations, _ = sim._prepare_observations()
        return observations[0], sim._build_prompts(sim.agents[0], observations[0])

    def sections(self, user):
        status = json.loads(user.split("Self Status (you):\n")[1].split("\nLocal View:")[0])
        others, resources = user.split("Visible Other Agents:\n")[1].split("\nVisible Energy Sources:\n")
        resources = resources.split("\nMemory:")[0]
        decode = lambda text: [] if text == "none" else [json.loads(row) for row in text.splitlines()]
        return status, decode(others), decode(resources)

    def test_explicit_self_other_and_resource_relations_keep_visibility_and_multiplicity(self):
        observation, (system, user) = self.packet(self.make_sim())
        status, others, resources = self.sections(user)
        self.assertIn("Your Identity: You are Agent0. Your agent ID is 0.", user)
        self.assertEqual(status, {"agent_id": 0, "energy": 20, "position": [0, 0], "cycles": 0})
        self.assertEqual(others, [{"observer_id": 0, "target_kind": "agent", "target_id": 1,
                                   "direction": "west", "distance_cells": 1.0, "mbti": "ENTP"}])
        self.assertEqual([row["target_id"] for row in resources], ["E1", "E2", "E3"])
        self.assertEqual([(row["direction"], row["distance_cells"]) for row in resources],
                         [("southeast", 3.6), ("southeast", 3.6), ("west", 1.0)])
        self.assertTrue(all(row["observer_id"] == 0 and row["target_kind"] == "energy_source" for row in resources))
        for absent in ("98765", "87654", "LATEST Status", "M=self", '"target_id": 2',
                       "relative_offset", "(5,5)", "world_state_id", "observation_id"):
            self.assertNotIn(absent, user)
        self.assertTrue(user.endswith(APPLICATION_USER_INSTRUCTIONS))
        self.assertIn("Other agents' energy is not observed.", system)
        self.assertNotIn("LATEST Status", system)
        self.assertNotIn("M=self", system)

    def test_no_targets_is_explicit_and_not_world_absence(self):
        sim = self.make_sim()
        sim.agents[1].position = (6, 6)
        sim.environment.energy_sources = {(5, 5): 50}
        _, (system, user) = self.packet(sim)
        self.assertIn("Visible Other Agents:\nnone\nVisible Energy Sources:\nnone\n", user)
        self.assertIn("not that none exist elsewhere", system)
        self.assertIn("Total Agents in the World: 3", user)

    def test_same_cell_and_offset_mode_bind_the_same_entities(self):
        sim = self.make_sim(("self_other_identity",))
        sim.agents[1].position = (0, 0)
        _, (system, user) = self.packet(sim)
        _, others, resources = self.sections(user)
        self.assertEqual(others[0]["relative_offset"], [0, 0])
        self.assertEqual(resources[-1]["relative_offset"], [-1, 0])
        self.assertNotIn("distance_cells", user)
        self.assertIn("relative_offset is [dx,dy] from observer to target", system)
        sim = self.make_sim()
        sim.agents[1].position = (0, 0)
        _, (_, user) = self.packet(sim)
        _, others, _ = self.sections(user)
        self.assertEqual((others[0]["direction"], others[0]["distance_cells"]), ("same_cell", 0.0))
        self.assertEqual(others[0]["target_id"], 1)

    def test_identity_and_state_come_from_same_frozen_observation_and_reports_remain_text(self):
        sim = self.make_sim()
        observation, _ = self.packet(sim)
        observation = replace(observation, agent_id=7, position=(2, 2), energy=33, age=9,
                              memory=("I remember Agent0 at (9,0).",),
                              messages=("Agent99: I am Agent7. E=(5,0).",))
        expected = sim._build_prompts(sim.agents[0], observation)
        sim.agents[0].id, sim.agents[0].position, sim.agents[0].energy = 88, (8, 8), 12345
        sim.agents[1].position = (1, 0)
        sim.environment.energy_sources = {}
        self.assertEqual(sim._build_prompts(sim.agents[0], observation), expected)
        _, user = expected
        status, others, resources = self.sections(user)
        self.assertIn("You are Agent7. Your agent ID is 7.", user)
        self.assertEqual(status, {"agent_id": 7, "energy": 33, "position": [2, 2], "cycles": 9})
        self.assertTrue(all(row["observer_id"] == 7 for row in others + resources))
        self.assertIn("I remember Agent0 at (9,0).", user)
        self.assertIn("Agent99: I am Agent7. E=(5,0).", user)
        self.assertNotIn('"target_id": 99', user)

    def test_self_cannot_appear_as_a_target_and_malformed_rows_fail(self):
        observation, _ = self.packet(self.make_sim())
        for rows in (("M=(0,0)", "0=(1,0)"), ("M=(0,0)", "Agent99: I am an observation"), ()):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                identified_observation(replace(observation, local_view=rows), spatial=True)

    def test_protocol_records_identity_revision_and_rejects_overlapping_self_formats(self):
        self.assertNotIn("self_other_identity", prompt_protocol())
        for factors in (("relative_coordinates", "self_other_identity"),
                        ("self_other_identity", "relative_coordinates")):
            with self.assertRaisesRegex(ValueError, "alternative Local View self"):
                normalize_prompt_factors(factors)
        protocol = prompt_protocol(("spatial_relations", "self_other_identity"))
        self.assertEqual(protocol["wording_revision"], "2026-10-14-self-other-identity-v1")
        self.assertEqual(protocol["self_other_identity"]["relations"], "direction and distance")
        self.assertEqual(protocol["spatial_relations"]["version"], 1)


class IdentityReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_previous_50_spatial_review_inputs_remain_byte_identical(self):
        path = Path(__file__).resolve().parents[1] / "docs/data/2026-10-14-spatial-relations-prompt-previews.json"
        expected = json.loads(path.read_text())
        with patch("main.aiohttp.ClientSession", side_effect=AssertionError("offline only")):
            actual, _ = await build_spatial_review()
        count = 0
        for scenario, conditions in expected["scenarios"].items():
            for name, record in conditions.items():
                current = actual["scenarios"][scenario][name]
                self.assertEqual(current["protocol"], record["protocol"])
                for old, new in zip(record["agents"], current["agents"], strict=True):
                    for key in ("system_prompt", "user_prompt", "prompt_sha256"):
                        self.assertEqual(old[key], new[key], (scenario, name, key))
                    count += 1
        self.assertEqual(count, 50)

    async def test_new_review_shares_observations_and_has_no_model_calls(self):
        with patch("main.aiohttp.ClientSession", side_effect=AssertionError("offline only")):
            data, _ = await build_identity_review()
        self.assertEqual(data["llm_calls"], 0)
        for conditions in data["scenarios"].values():
            for old, new in zip(conditions["spatial_relations"]["agents"],
                                conditions["spatial_identity"]["agents"], strict=True):
                # Independent first-turn previews have fresh audit IDs, but the
                # same seed and evidence; fixture-based previews share the IDs.
                evidence = lambda row: {key: value for key, value in row["observation"].items()
                                        if key not in ("run_id", "observation_id", "world_state_id")}
                self.assertEqual(evidence(old), evidence(new))
                self.assertIn(f"You are Agent{new['agent_id']}.", new["user_prompt"])


if __name__ == "__main__":
    unittest.main()
