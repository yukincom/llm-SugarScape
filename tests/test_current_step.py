"""Global step is present at every decision without changing history or messages."""

from dataclasses import replace
import unittest

from main import Simulation
from paper_prompts import prompt_protocol
from test_simulation import scripted


class CurrentStepTests(unittest.IsolatedAsyncioTestCase):
    def simulation(self, factors=()):
        return Simulation(num_agents=1, seed=42, initial_energy=200,
                          spawn_energy_count=0, energy_spawn_rate=0,
                          mock_mode=True, prompt_factors=factors)

    def test_world_step_comes_from_frozen_observation_not_age_or_live_state(self):
        for factors in ((), ("spatial_relations", "self_other_identity"),
                        ("provenance", "spatial_relations", "self_other_identity")):
            with self.subTest(factors=factors):
                sim = self.simulation(factors)
                sim.step_count = 19
                sim.agents[0].age = 4
                _, observations, _ = sim._prepare_observations()
                observation = replace(observations[0],
                                      memory=("Step 19: Stay; Meet soon.",),
                                      messages=("Agent1: See you at the meetup.",))
                sim.step_count = 999
                sim.agents[0].age = 999
                _, user = sim._build_prompts(sim.agents[0], observation)
                self.assertEqual(user.splitlines()[1], "Current Step: 20")
                self.assertEqual(user.count("Current Step: "), 1)
                self.assertNotIn("Current Step: 999", user)
                if "provenance" in factors:
                    self.assertIn("Current Observation (Step 20; source: environment):", user)
                    self.assertIn("Past Records (engine actions and Past Self Reports):", user)
                    self.assertIn("Received Reports (unverified content):", user)
                else:
                    self.assertIn("Memory:\nStep 19: Stay; Meet soon.\n", user)
                    self.assertIn("Messages:\nAgent1: See you at the meetup.\n", user)
                    self.assertNotIn("Past Records", user)
                    self.assertNotIn("Received Reports", user)

    async def test_each_turn_and_newborn_use_same_world_step(self):
        for factors in ((), ("spatial_relations", "self_other_identity")):
            with self.subTest(factors=factors):
                sim = scripted(self.simulation(factors), {(2, 0): "Reproduce"},
                               message="Hello from {id}")
                for step in range(1, 5):
                    snapshot = await sim.step()
                    for event in snapshot["events"]:
                        self.assertEqual(event["observation"]["step"], step)
                        self.assertIn(f"\nCurrent Step: {step}\n", event["user_prompt"])
                    if step == 3:
                        child = next(event for event in snapshot["events"] if event["agent_id"] == 1)
                        self.assertEqual(child["observation"]["age"], 0)
                        self.assertIn("\nCurrent Step: 3\n", child["user_prompt"])
                self.assertEqual(sim.step_count, 4)

    def test_recorded_protocol_identifies_global_step_for_all_prompt_modes(self):
        for factors in ((), ("spatial_relations", "self_other_identity"), ("provenance",)):
            self.assertEqual(prompt_protocol(factors)["rules"]["current_step"],
                             "1-based world step at decision time; shared by all agents, including newborns")


if __name__ == "__main__":
    unittest.main()
