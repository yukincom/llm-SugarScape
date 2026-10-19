from copy import deepcopy
import json
from pathlib import Path
import unittest

from agent_view import agent_states, attack_victims, display_message, event_steps, format_live_decision, page_numbers, step_pages
from grid_view import draw_grid, icon_pixels
from response_fields import decision_notice, reading_fields


class GridViewTests(unittest.TestCase):
    def test_event_steps_use_executions_and_death_turn_not_display_priority(self):
        logs = [
            {"step": 0, "agents": [{"id": 0, "alive": True}, {"id": 1, "alive": True}], "events": []},
            {"step": 1, "agents": [{"id": 0, "alive": False, "death_step": 1}, {"id": 1, "alive": True}],
             "events": [{"agent_id": 0, "executed_action": "Reproduce", "action_status": "rejected",
                         "attack_status": "rejected"},
                        {"agent_id": 1, "attack_status": "executed", "executed_attack": "0",
                         "action_status": "rejected", "share_status": "rejected"}]},
            {"step": 2, "agents": [{"id": 0, "alive": False, "death_step": 1}, {"id": 1, "alive": True}],
             "events": [{"agent_id": 1, "selected_action": "Reproduce", "executed_action": "Stay",
                         "attack_status": "rejected"}]},
            {"step": 10, "agents": [{"id": 0, "alive": False, "death_step": 1}, {"id": 1, "alive": True}],
             "events": [{"agent_id": 1, "kind": "attack", "action_status": "executed", "target_id": 2},
                        {"agent_id": 3, "kind": "attack", "action_status": "executed", "target_id": 4}]},
            {"step": 11, "agents": [{"id": 0, "alive": False, "death_step": 1}, {"id": 1, "alive": False}],
             "events": [{"agent_id": 1, "kind": "attack", "action_status": "skipped_dead"},
                        {"agent_id": 4, "decision_source": "fallback", "executed_action": "Stay"}]},
        ]
        before = deepcopy(logs)
        self.assertEqual(event_steps(list(reversed(logs))),
                         {"dead": [1, 11], "attack": [1, 10], "hurt": [1, 10], "share": [], "reproduce": [1]})
        self.assertEqual(logs, before)

    def test_event_steps_read_legacy_sample_without_repeating_death_afterimage(self):
        data = json.loads((Path(__file__).resolve().parents[1] / "examples/first-look/run.json").read_text())
        self.assertEqual(event_steps(data["logs"]),
                         {"dead": [1], "attack": [], "hurt": [], "share": [1, 3], "reproduce": [1, 2]})

    def test_share_face_requires_executed_transfer_and_is_only_on_that_turn(self):
        agent = {"id": 1, "alive": True, "energy": 20}
        share = {"agent_id": 1, "kind": "share", "action_status": "executed",
                 "share_status": "executed", "shared_amount": 10}
        self.assertEqual(agent_states(agent, share), ("share",))
        self.assertTrue(format_live_decision(share, agent).startswith("😘 エージェント 01"))
        for status in ("not_requested", "rejected", "skipped_dead"):
            self.assertEqual(agent_states(agent, {**share, "share_status": status}), ("hungry",))
        self.assertEqual(agent_states(agent, {"kind": "share", "action_status": "executed"}), ("share",))
        self.assertEqual(agent_states(agent, share, {1}), ("share",))
        self.assertEqual(agent_states(agent, {**share, "attack_status": "executed"}), ("share",))
        self.assertEqual(agent_states({**agent, "alive": False}, share), ("dead",))
        snapshot = self.snapshot()
        snapshot["events"] = [share]
        fig = draw_grid(snapshot, 11, 150)
        marker = next(item for item in fig.axes[0].artists if item.get_gid() == "agent-1")
        self.assertTrue((marker.offsetbox.get_data() == icon_pixels("share")).all())
        fig.clear()
        following = deepcopy(snapshot)
        following["step"] += 1
        following["events"] = [{"agent_id": 1, "kind": "stay", "share_status": "not_requested"}]
        self.assertEqual(event_steps([snapshot, following])["share"], [3])

    def snapshot(self, step=3):
        return {"step": step, "summary": {"alive": 4},
                "environment": {"resources": [{"x": 4, "y": 8, "energy": 50}]},
                "events": [],
                "agents": [
                    {"id": 0, "position": [1, 2], "energy": 49, "alive": True, "death_step": None},
                    {"id": 1, "position": [2, 3], "energy": 50, "alive": True, "death_step": None},
                    {"id": 2, "position": [3, 4], "energy": 149, "alive": True, "death_step": None},
                    {"id": 3, "position": [3, 4], "energy": 150, "alive": True, "death_step": None},
                    {"id": 4, "position": [5, 6], "energy": 0, "alive": False, "death_step": 2}]}

    def test_fixed_health_boundaries_and_actual_events(self):
        agent = {"id": 1, "alive": True}
        for energy, state in ((49, "hungry"), (50, "normal"), (149, "normal"), (150, "comfortable")):
            self.assertEqual(agent_states({**agent, "energy": energy}), (state,))
        self.assertEqual(agent_states(agent, {"attack_status": "executed"}), ("attack",))
        self.assertEqual(agent_states(agent, {"attack_status": "rejected"}), ("normal",))
        self.assertEqual(agent_states(agent, {"executed_action": "Reproduce"}), ("reproduce",))
        self.assertEqual(agent_states(agent, {"selected_action": "Reproduce", "executed_action": "Stay"}), ("normal",))
        victims = attack_victims([{"attack_status": "executed", "executed_attack": 1},
                                  {"attack_status": "rejected", "executed_attack": 2},
                                  {"kind": "attack", "action_status": "executed", "target_id": 4}])
        self.assertEqual(victims, {1, 4})
        self.assertEqual(agent_states(agent, {}, victims), ("hurt",))
        self.assertEqual(agent_states({**agent, "alive": False}, {}, victims), ("dead", "hurt"))

    def test_board_draws_resources_and_agents_at_recorded_cells_without_mutation(self):
        snapshot = self.snapshot()
        snapshot["events"] = [{"agent_id": 2, "finish_reason": "length",
                                "response_repairs": [{"field": "Next Action", "rule": "default_stay"}]}]
        before = deepcopy(snapshot)
        for cost in (30, 150):
            fig = draw_grid(snapshot, 11, cost)
            artists = {item.get_gid(): item for item in fig.axes[0].artists}
            self.assertEqual(artists["food-0"].xy, (4, 8))
            self.assertEqual(artists["agent-0"].xy, (1, 2))
            for name, state in (("food-0", "resource"), ("agent-0", "hungry"),
                                ("agent-1", "normal"), ("agent-2", "panic"), ("agent-3", "comfortable")):
                self.assertTrue((artists[name].offsetbox.get_data() == icon_pixels(state)).all())
            points = [artists[key].xy for key in ("agent-2", "agent-3")]
            self.assertNotEqual(points[0], points[1])
            for x, y in points:
                self.assertTrue(2.5 < x < 3.5 and 3.5 < y < 4.5)
            self.assertEqual(snapshot, before)
            fig.clear()

    def test_death_is_visible_immediately_and_next_turn_with_damage_on_attack_turn(self):
        for step, expected in ((2, True), (3, True), (4, False)):
            snapshot = self.snapshot(step)
            if step == 2:
                snapshot["events"] = [{"agent_id": 0, "attack_status": "executed", "executed_attack": 4}]
            fig = draw_grid(snapshot, 11, 150)
            names = {item.get_gid() for item in fig.axes[0].artists}
            self.assertEqual("death-4" in names, expected)
            self.assertEqual("damage-4" in names, step == 2)
            self.assertNotIn("agent-4", names)
            fig.clear()

    def test_live_text_has_only_name_message_and_thought(self):
        text = format_live_decision({"agent_id": 1, "message": "None", "thought": "Looking for food",
                                     "selected_action": "Reproduce", "summary": "Hidden summary"},
                                    {"id": 1, "energy": 100, "alive": True})
        self.assertEqual(text, "🙂 エージェント 01\n💬 (無言)\n💭 Looking for food")

    def test_panic_marks_only_exhausted_undecided_replies_and_preserves_text(self):
        event = {"agent_id": 1, "finish_reason": "length", "message": "Wait for me.",
                 "thought": "Still considering the grid.",
                 "response_repairs": [{"field": "Next Action", "rule": "default_stay"}]}
        agent = {"id": 1, "energy": 100, "alive": True}
        before = deepcopy(event)
        self.assertEqual(agent_states(agent, event), ("panic",))
        self.assertEqual(format_live_decision(event, agent),
                         "😵‍💫 エージェント 01　パニック\n💬 Wait for me.\n💭 Still considering the grid.")
        self.assertEqual(event, before)
        self.assertEqual(agent_states(agent, {**event, "finish_reason": "stop"}), ("normal",))
        self.assertEqual(agent_states(agent, {**event, "response_repairs": []}), ("normal",))
        self.assertEqual(agent_states(agent, {"error_kind": "transport_error"}), ("normal",))
        self.assertEqual(agent_states(agent, event, {1}), ("hurt",))
        self.assertEqual(agent_states({**agent, "alive": False}, event), ("dead",))
        for value in (None, "", "None", " NONE ", "null", "no message"):
            self.assertEqual(display_message(value), "(無言)")
        self.assertEqual(display_message("Hello!"), "Hello!")

    def test_timeline_is_ascending_ten_steps_per_page_with_bounded_navigation(self):
        logs = [{"step": step} for step in reversed(range(24))]
        pages = step_pages(logs)
        self.assertEqual([[item["step"] for item in page] for page in pages],
                         [list(range(1, 11)), list(range(11, 21)), [21, 22, 23]])
        self.assertEqual(page_numbers(3, 1), [1, 2, 3])
        self.assertEqual(page_numbers(20, 1), [1, 2, 3, 4, 5])
        self.assertEqual(page_numbers(20, 10), [8, 9, 10, 11, 12])
        self.assertEqual(page_numbers(20, 20), [16, 17, 18, 19, 20])

    def test_reading_rejects_ambiguous_prose_and_non_parse_error_bodies(self):
        raw = ("Thoughts: first thought\nThoughts: conflicting thought\n"
               "Next Action: x+1, y-1\nMessage: A clear message\nMemory: none")
        event = {"agent_id": 2, "decision_source": "fallback", "error_kind": "parse_error",
                 "message": "", "thought": "", "raw_response": raw}
        before = deepcopy(event)
        fields = reading_fields(event)
        self.assertEqual(fields["message"], "A clear message")
        self.assertEqual(fields["thought"], "")
        self.assertEqual(event, before)
        for kind in ("http_error", "protocol_error", "truncated_response", "transport_error"):
            self.assertEqual(reading_fields({**event, "error_kind": kind}), {"message": "", "thought": ""})
        notice = decision_notice({**event, "action_status": "skipped_dead"})
        self.assertIn("死亡で未実行", notice)
        self.assertNotIn("待機に置換", notice)


if __name__ == "__main__":
    unittest.main()
