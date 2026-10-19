"""Exercise the real Streamlit entry point without a browser or an LLM server."""

import asyncio
import base64
import json
import shutil
import threading
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import aiohttp
from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parents[1] / "main.py"


def finish_experiment(app):
    task = app.session_state["experiment_task"] if "experiment_task" in app.session_state else None
    if task is not None:
        if not task.done.wait(20):
            task.stop()
            task.done.wait(5)
            raise AssertionError("Experiment did not finish")
        app.run(timeout=20)
    return app


def widget(elements, label):
    return next(element for element in elements if element.label == label)


def event_example(directory):
    """Script real events on both sides of a timeline page boundary."""
    from main import DEFAULT_PARAMS, Simulation
    from run_data import RunRecorder
    from test_simulation import scripted

    config = {**DEFAULT_PARAMS, "mock_mode": True, "num_agents": 3, "num_steps": 12,
              "grid_size": 11, "initial_energy": 200, "spawn_energy_count": 0,
              "energy_spawn_rate": 0, "output_dir": directory}
    sim = scripted(Simulation(num_agents=3, grid_size=11, initial_energy=200,
                              spawn_energy_count=0, energy_spawn_rate=0, mock_mode=True),
                   {(2, 2): "Reproduce", (11, 0): {"attack": "1"}, (12, 0): "Reproduce"})
    for agent in sim.agents:
        agent.position = (agent.id, 0)
    # Ten waits leave 1 energy; the zero-transfer attack still marks the victim,
    # which then dies from the common cost at the end of step 11.
    sim.agents[1].energy = 11
    recorder = RunRecorder(directory, config, model_info={"status": "mock"})
    recorder.manifest["demo_notice"] = "画面確認用の作例です。LLMの判断結果ではありません。"
    recorder.record(sim.snapshot())
    async def simulate():
        for _ in range(12):
            recorder.record(await sim.step(session=object()))
    asyncio.run(simulate())
    return recorder.finish("completed", "ui_example")


class StreamlitTests(unittest.TestCase):
    def setUp(self):
        # AppTest inherits the test runner's argv; match `streamlit run main.py`.
        argv = patch.object(sys, "argv", [str(APP_PATH)])
        argv.start()
        self.addCleanup(argv.stop)
        presets = tempfile.TemporaryDirectory()
        self.addCleanup(presets.cleanup)
        self.preset_directory = Path(presets.name)
        environment = patch.dict(os.environ, {"SUGARSCAPE_DATA_DIR": presets.name})
        environment.start()
        self.addCleanup(environment.stop)

    def test_library_language_precedes_summary_and_event_links_jump_across_pages(self):
        from agent_view import icon_path
        from app_ui import step_anchor
        with tempfile.TemporaryDirectory() as directory, patch.object(
                aiohttp.ClientSession, "_request", side_effect=AssertionError("No network in replay")):
            result = event_example(directory)
            path = Path(result["output_dir"]) / "run.json"
            original = path.read_bytes()
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            widget(app.text_input, "保存先").set_value(directory)
            widget(app.radio, "表示").set_value("保存した実験").run()
            widget(app.button, "この実験を開く").click().run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            nodes = list(app.main)
            positions = {name: next(i for i, node in enumerate(nodes) if node.type == kind and
                                    getattr(node, field, None) == value)
                         for name, kind, field, value in (
                             ("offline", "caption", "value", "通信は発生しません"),
                             ("language", "radio", "label", "表示する言語"),
                             ("counts", "metric", "label", "生存"),
                             ("statistics", "subheader", "value", "統計データ"),
                             ("timeline", "subheader", "value", "エージェントたちの記録"))}
            self.assertEqual(list(positions.values()), sorted(positions.values()))
            self.assertEqual(sum(radio.label == "表示する言語" for radio in app.radio), 1)
            self.assertEqual(len(app.success), 0)
            self.assertFalse(any(item.label == "人口の推移・数値の詳細" for item in app.expander))
            candy = base64.b64encode(icon_path("resource").read_bytes()).decode("ascii")
            self.assertTrue(any(candy in item.proto.body and 'alt="砂糖"' in item.proto.body
                                for item in app.get("html")))
            run_id = result["run_id"]
            for state, expected in (("dead", [11]), ("attack", [11]), ("hurt", [11]), ("reproduce", [2, 12])):
                prefix = f"timeline_events_{run_id}_{state}_"
                links = [button for button in app.button if (button.key or "").startswith(prefix)]
                self.assertEqual([button.label for button in links], [f"Step {step}" for step in expected])
            widget(app.selectbox, "表示するエージェント").set_value(2).run()
            app.button(key=f"timeline_events_{run_id}_attack_11").click().run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state[f"timeline_page_{run_id}"], 2)
            self.assertIsNone(widget(app.selectbox, "表示するエージェント").value)
            self.assertEqual([item.value for item in app.subheader if item.value.startswith("Step ")], ["Step 11", "Step 12"])
            self.assertTrue(any(step_anchor(run_id, 11) in item.proto.body and item.proto.unsafe_allow_javascript
                                for item in app.get("html")))
            self.assertFalse(app.session_state[f"timeline_events_{run_id}_attack"])
            app.button(key=f"timeline_events_{run_id}_reproduce_2").click().run(timeout=20)
            self.assertEqual(app.session_state[f"timeline_page_{run_id}"], 1)
            self.assertEqual(path.read_bytes(), original)

    def test_stop_controls_keep_completed_turn_and_allow_next_run(self):
        from experiment_task import ExperimentTask
        from main import main, Simulation
        from grid_view import draw_grid

        waiting = threading.Event()
        original = Simulation._request_decision
        async def delayed(sim, session, agent, *args):
            if sim.step_count == 2 and agent.id == 1:
                waiting.set()
                await asyncio.Event().wait()
            return await original(sim, session, agent, *args)
        def task_factory(runner, params):
            return ExperimentTask(main, params)

        with tempfile.TemporaryDirectory() as directory, \
                patch("app_ui.ExperimentTask", side_effect=task_factory), \
                patch("app_ui.draw_grid", wraps=draw_grid) as render_board, \
                patch.object(Simulation, "_request_decision", delayed), \
                patch.object(aiohttp.ClientSession, "_request", side_effect=AssertionError("No network in Mock")):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            widget(app.selectbox, "動作モード").select("Mock（待機のみ・通信なし）").run()
            widget(app.text_input, "保存先").set_value(directory)
            widget(app.button, "実験をはじめる").click().run(timeout=20)
            task = app.session_state["experiment_task"]
            try:
                self.assertTrue(waiting.wait(5))
                app.run(timeout=20)
                self.assertEqual(len(app.exception), 0)
                self.assertIn("Step 2 の応答 1 / 3 個体", app.get("progress")[0].proto.text)
                self.assertFalse(any("盤面と会話:" in item.value for item in app.caption))
                self.assertEqual(sum(item.value.count("💬 Hello world") for item in app.text), 4)
                live = next(item.value for item in app.text if "💬 Hello world" in item.value)
                self.assertLess(live.index("Step 1 ·"), live.index("Step 2 ·"))
                self.assertIn("Step 2 · 🙂 エージェント 00", live)
                self.assertNotIn("（行動前）", live)
                rendered = render_board.call_count
                before_image = app.get("image")[-1].proto.SerializeToString()
                for _ in range(3):
                    app.run(timeout=20)
                self.assertEqual(render_board.call_count, rendered)
                self.assertEqual(app.get("image")[-1].proto.SerializeToString(), before_image)
                self.assertFalse(widget(app.button, "停止").disabled)
                self.assertTrue(widget(app.button, "結果をクリア").disabled)
                self.assertTrue(widget(app.radio, "表示").disabled)
                self.assertFalse(any(button.label in ("停止", "実験をはじめる", "結果をクリア")
                                     for button in app.sidebar.button))
                widget(app.button, "停止").click().run(timeout=20)
                finish_experiment(app)
                self.assertEqual(len(app.exception), 0)
                result = app.session_state["result"]
                self.assertEqual(result["status"], "interrupted")
                self.assertEqual(result["termination_reason"], "user_stop")
                self.assertEqual([snap["step"] for snap in result["logs"]], [0, 1])
                self.assertFalse(widget(app.button, "結果をクリア").disabled)
                self.assertFalse(widget(app.button, "実験をはじめる").disabled)
                self.assertFalse(widget(app.radio, "表示").disabled)
                saved = (Path(result["output_dir"]) / "run.json").read_bytes()
                widget(app.button, "結果をクリア").click().run()
                self.assertNotIn("result", app.session_state)
                self.assertEqual((Path(result["output_dir"]) / "run.json").read_bytes(), saved)
                widget(app.number_input, "ターン数").set_value(1)
                widget(app.button, "実験をはじめる").click().run(timeout=20)
                finish_experiment(app)
                self.assertEqual(app.session_state["result"]["status"], "completed")
            finally:
                task.stop()
                task.done.wait(5)

    def test_saved_experiment_full_name_and_rename_keep_record_open(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
                aiohttp.ClientSession, "_request", side_effect=AssertionError("No network in replay")):
            name = "2026-10-11_00-02-29_ee0ef6023621cff504d758262d4e04895a5af4a2_1"
            saved = Path(directory) / name
            shutil.copytree(APP_PATH.parent / "examples/first-look", saved)
            original = (saved / "run.json").read_bytes()
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            widget(app.text_input, "保存先").set_value(directory)
            widget(app.radio, "表示").set_value("保存した実験").run()
            self.assertEqual(widget(app.selectbox, "開く実験").options, [name])
            self.assertTrue(any(item.value == name for item in app.text))
            self.assertTrue(any(item.value == "通信は発生しません" for item in app.caption))
            widget(app.button, "この実験を開く").click().run()
            widget(app.text_input, "実験名").set_value("砂糖が少ない実験")
            widget(app.button, "名前を保存").click().run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            renamed = Path(directory) / "砂糖が少ない実験"
            self.assertEqual(widget(app.selectbox, "開く実験").options, [renamed.name])
            self.assertEqual(app.session_state["history_result"]["output_dir"], str(renamed.resolve()))
            self.assertEqual((renamed / "run.json").read_bytes(), original)
            self.assertFalse(saved.exists())

    def test_real_folder_component_receives_trigger_without_overwriting_later_edits(self):
        from streamlit.components.v2.bidi_component.main import _make_trigger_id
        from streamlit.proto.WidgetStates_pb2 import WidgetStates

        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"SUGARSCAPE_DESKTOP": "1", "SUGARSCAPE_OUTPUT_DIR": directory}):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            chosen = str(Path(directory) / "選んだ保存先")
            # AppTest has no v2 component interaction helper yet. Deliver the
            # same trigger payload as the native dialog's JavaScript callback.
            state = WidgetStates()
            event = state.widgets.add()
            event.id = _make_trigger_id(app.get("bidi_component")[0].proto.id, "events")
            event.json_trigger_value = json.dumps([{"event": "selected", "value": chosen}])
            app._run(state, timeout=20)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(widget(app.text_input, "保存先").value, chosen)
            self.assertEqual(json.loads(app.get("bidi_component")[0].proto.json)["directory"], chosen)
            manual = str(Path(directory) / "後から入力した保存先")
            widget(app.text_input, "保存先").set_value(manual).run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(widget(app.text_input, "保存先").value, manual)

    def test_folder_selection_and_image_preference_survive_page_changes_and_cancel(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            chosen = root / "選んだ保存先"
            chosen.mkdir()
            picker = Mock(return_value=None)
            with patch.dict(os.environ, {"SUGARSCAPE_DESKTOP": "1", "SUGARSCAPE_OUTPUT_DIR": str(root)}), \
                    patch.dict(sys.modules, {"folder_picker": SimpleNamespace(choose_folder=picker, open_folder=Mock())}), \
                    patch.object(aiohttp.ClientSession, "_request", side_effect=AssertionError("No network in Mock")):
                app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
                widget(app.selectbox, "動作モード").set_value("Mock（待機のみ・通信なし）").run()
                self.assertTrue(widget(app.checkbox, "盤面画像も保存する").value)
                picker.return_value = str(chosen)
                app.run()
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(widget(app.text_input, "保存先").value, str(chosen))
                picker.return_value = None
                widget(app.radio, "表示").set_value("保存した実験").run()
                widget(app.radio, "表示").set_value("実験をつくる").run()
                self.assertEqual(widget(app.text_input, "保存先").value, str(chosen))
                self.assertTrue(widget(app.checkbox, "盤面画像も保存する").value)
                widget(app.number_input, "ターン数").set_value(1)
                widget(app.button, "実験をはじめる").click().run(timeout=20)
                finish_experiment(app)
                self.assertEqual(len(app.exception), 0)
                result = app.session_state["result"]
                self.assertEqual(Path(result["output_dir"]).parent, chosen)
                self.assertTrue(result["config"]["save_images"])
                self.assertEqual(sorted(path.name for path in (Path(result["output_dir"]) / "img").glob("*.png")),
                                 ["step000.png", "step001.png"])

    def test_repaired_action_runs_normally_and_retains_details(self):
        from test_simulation import Response, completion, reply

        raw = reply("x+1, y-1\nNext Action: x+1", message="Heading east.", memory="Look east again.")
        def repaired_response(session, url, **kwargs):
            return Response(200, completion(raw))

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(aiohttp.ClientSession, "post", new=repaired_response), \
                patch.object(aiohttp.ClientSession, "head", return_value=Response(405, "")), \
                patch("experiment_task.translate_result", return_value={"entries": {}}), \
                patch("model_identity.read_server", side_effect=OSError("offline test")), \
                patch.object(aiohttp.ClientSession, "_request", side_effect=aiohttp.ClientConnectionError("offline test")):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            widget(app.number_input, "ターン数").set_value(1)
            widget(app.text_input, "保存先").set_value(directory)
            widget(app.button, "実験をはじめる").click().run(timeout=20)
            finish_experiment(app)
            self.assertEqual(len(app.exception), 0)
            result = app.session_state["result"]
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["summary"]["repaired_decisions"], 3)
            self.assertEqual(result["summary"]["parse_errors"], 0)
            self.assertTrue(any(text.value == "💬 Heading east." for text in app.text))
            captions = [caption.value for caption in app.caption]
            self.assertTrue(any("補完した判断: 3件" in text for text in captions))
            self.assertIn("応答を補完: x+1", captions)
            self.assertIn("応答の原文（補完前）", captions)
            self.assertFalse(any("待機に置換" in text for text in captions))
            for before, event in zip(result["logs"][0]["agents"], result["logs"][1]["events"]):
                self.assertEqual(tuple(event["position_after"]), ((before["position"][0] + 1) % 30, before["position"][1]))
                self.assertEqual(event["raw_response"], raw)

    def test_diagonal_retry_feedback_and_both_replies_are_visible(self):
        from test_simulation import Response, completion
        import re

        def choose_response(session, url, **kwargs):
            messages = kwargs["json"]["messages"]
            if len(messages) == 2:
                raw = "Action: Move to (-1,-1)\nMessage: Rejected message\nThought: Rejected thought"
            else:
                target = re.search(r"^- (\([0-9]+,[0-9]+\))$", messages[-1]["content"], re.M)[1]
                raw = f"Action: [{target}]\nMessage: Chosen message\nThought: Chosen thought"
            return Response(200, completion(raw))

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(aiohttp.ClientSession, "post", new=choose_response), \
                patch.object(aiohttp.ClientSession, "head", return_value=Response(405, "")), \
                patch("experiment_task.translate_result", return_value={"entries": {}}), \
                patch("model_identity.read_server", side_effect=OSError("offline test")), \
                patch.object(aiohttp.ClientSession, "_request", side_effect=aiohttp.ClientConnectionError("offline test")):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            widget(app.number_input, "ターン数").set_value(1)
            widget(app.text_input, "保存先").set_value(directory)
            widget(app.button, "実験をはじめる").click().run(timeout=20)
            finish_experiment(app)
            self.assertEqual(len(app.exception), 0)
            events = app.session_state["result"]["logs"][1]["events"]
            self.assertTrue(all(e["retry_status"] == "corrected" for e in events))
            captions = [caption.value for caption in app.caption]
            self.assertIn("コードから伝えたNG理由と移動先の候補", captions)
            self.assertIn("1回目の応答（原文）", captions)
            self.assertIn("2回目の応答（原文）", captions)
            texts = [text.value for text in app.text]
            self.assertIn("💬 Chosen message", texts)
            self.assertNotIn("💬 Rejected message", texts)
            self.assertTrue(any("Choose exactly one coordinate pair from this list." in text for text in texts))

    def test_loose_response_prose_is_shown_live_and_in_saved_result(self):
        from copy import deepcopy
        from test_simulation import Response, completion, reply
        import re

        def loose_response(session, url, **kwargs):
            # Use the real response reader while keeping this UI test offline.
            user_prompt = kwargs["json"]["messages"][1]["content"]
            name = re.search(r"^Your Identity: You are (Agent\d+)\.", user_prompt, re.M)[1]
            return Response(200, completion(content=reply(
                "x+1, y-1", message=f"From {name}", thoughts=f"Thought from {name}",
                memory="Keep this memory.")))

        translating, finish_translation = threading.Event(), threading.Event()
        async def held_translation(*args, **kwargs):
            translating.set()
            while not finish_translation.is_set():
                await asyncio.sleep(0.01)
            return {"entries": {}}
        self.addCleanup(finish_translation.set)

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(aiohttp.ClientSession, "post", new=loose_response), \
                patch.object(aiohttp.ClientSession, "head", return_value=Response(405, "")), \
                patch("experiment_task.translate_result", side_effect=held_translation), \
                patch("model_identity.read_server", side_effect=OSError("offline test")), \
                patch.object(aiohttp.ClientSession, "_request", side_effect=aiohttp.ClientConnectionError("offline test")):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            widget(app.number_input, "ターン数").set_value(1)
            widget(app.text_input, "保存先").set_value(directory)
            widget(app.button, "実験をはじめる").click().run(timeout=20)
            self.assertTrue(translating.wait(5))
            app.run(timeout=20)
            live = [item.value for item in app.text]
            finish_translation.set()
            finish_experiment(app)
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("💬 From Agent2" in text and "💭 Thought from Agent2" in text for text in live))
            result = app.session_state["result"]
            self.assertEqual(result["summary"]["parse_errors"], 0)
            self.assertTrue(any(text.value == "💬 From Agent2" for text in app.text))
            self.assertFalse(any("行動は待機に置換" in caption.value for caption in app.caption))
            self.assertFalse(any(caption.value == "出力された記憶（次回には未採用）" for caption in app.caption))
            original = deepcopy(result)
            path = Path(result["output_dir"]) / "run.json"
            original_bytes = path.read_bytes()
            widget(app.radio, "表示する言語").set_value("原文").run()
            self.assertTrue(any(text.value == "💭 Thought from Agent2" for text in app.text))
            self.assertEqual(path.read_bytes(), original_bytes)
            self.assertEqual(app.session_state["result"], original)


    def test_unreachable_server_does_not_start_or_save_an_experiment(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(aiohttp.ClientSession, "head", side_effect=aiohttp.ClientConnectionError("offline")) as head, \
                patch.object(aiohttp.ClientSession, "post") as generation, \
                patch("experiment_task.translate_result") as translation:
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            widget(app.text_input, "保存先").set_value(directory)
            widget(app.button, "実験をはじめる").click().run(timeout=20)
            finish_experiment(app)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual([item.value for item in app.error], ["接続できません"])
            self.assertNotIn("result", app.session_state)
            self.assertNotIn("experiment_task", app.session_state)
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertFalse(widget(app.button, "実験をはじめる").disabled)
            head.assert_called_once()
            generation.assert_not_called()
            translation.assert_not_called()

    def test_mock_run_exports_and_survives_widget_rerun(self):
        from test_simulation import Response, completion

        with tempfile.TemporaryDirectory() as directory, patch.object(aiohttp.ClientSession, "_request") as request:
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(widget(app.selectbox, "動作モード").value, "LLM / APIに接続")
            self.assertEqual(widget(app.text_input, "モデルID").value, "default_model")
            self.assertFalse(widget(app.text_input, "モデルID").disabled)
            self.assertEqual(widget(app.number_input, "エージェントの体力（初期値）").value, 100)
            self.assertEqual(widget(app.number_input, "出生時のエージェントの体力").value, 100)
            self.assertEqual(widget(app.number_input, "人口の上限").value, 60)
            self.assertEqual(widget(app.number_input, "世界の広さ").value, 30)
            self.assertEqual(widget(app.number_input, "各ターンの砂糖の追加確率").value, 0.2)
            self.assertFalse(widget(app.checkbox, "性格設定（MBTI）を使う").value)
            llm_settings = widget(app.expander, "LLM設定")
            self.assertFalse(llm_settings.proto.expanded)
            self.assertFalse(widget(llm_settings.button, "接続テスト").disabled)
            self.assertEqual(widget(llm_settings.text_input, "モデルID").value, "default_model")
            self.assertIn("実験設定", [heading.value for heading in app.subheader])
            with patch.object(aiohttp.ClientSession, "post", return_value=Response(200, completion())) as probe:
                widget(app.button, "接続テスト").click().run(timeout=20)
            probe.assert_called_once()
            self.assertEqual(len(app.exception), 0)
            self.assertIn("接続テストに成功", widget(app.expander, "LLM設定").success[0].value)
            widget(app.selectbox, "動作モード").select("Mock（待機のみ・通信なし）").run()
            self.assertTrue(widget(app.button, "接続テスト").disabled)
            widget(app.slider, "最初の個体数").set_value(3)
            widget(app.number_input, "ターン数").set_value(2)
            widget(app.text_input, "保存先").set_value(directory)
            widget(app.button, "実験をはじめる").click().run(timeout=20)
            finish_experiment(app)
            self.assertEqual(len(app.exception), 0)
            result = app.session_state["result"]
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["summary"]["total_actions"], 6)
            self.assertEqual(result["logs"][0]["agents"][0]["energy"], 100)
            self.assertFalse(result["config"]["use_mbti"])
            factors = ["spatial_relations", "self_other_identity"]
            self.assertEqual(result["config"]["prompt_factors"], factors)
            manifest = json.loads((Path(result["output_dir"]) / "manifest.json").read_text())
            self.assertEqual(manifest["config"]["prompt_factors"], factors)
            self.assertEqual(manifest["protocol"]["prompt_factors"]["enabled"], factors)
            for event in result["logs"][1]["events"]:
                self.assertIn(f"Your Identity: You are Agent{event['agent_id']}.", event["user_prompt"])
                self.assertIn("Self Status (you):", event["user_prompt"])
                self.assertIn("Visible Other Agents:", event["user_prompt"])
            self.assertNotIn("personality", result["logs"][1]["events"][0]["system_prompt"])
            self.assertEqual(len(app.success), 0)
            self.assertTrue(any(f"実施日: {result['execution_date']}" in caption.value
                                and "モデル: Mock" in caption.value for caption in app.caption))
            for filename in ("steps.csv", "agents.csv", "events.csv", "run.json", "manifest.json"):
                self.assertTrue((Path(result["output_dir"]) / filename).is_file())
            self.assertEqual(len(app.get("image")), 4)
            self.assertEqual(sum("エージェント 0" in item.value for item in app.markdown), 6)
            self.assertTrue(any("😱 空腹（50未満）" in item.value for item in app.markdown))
            self.assertTrue(any('alt="砂糖"' in item.proto.body for item in app.get("html")))
            self.assertTrue(any("体力 99 → 98" in caption.value for caption in app.caption))
            self.assertTrue(any(text.value == "💬 Hello world" for text in app.text))
            self.assertTrue(any(text.value == "💭 Mock decision" for text in app.text))
            widget(app.selectbox, "表示するエージェント").set_value(1).run()
            self.assertEqual(sum("エージェント 01" in item.value for item in app.markdown), 2)
            self.assertFalse(any("エージェント 00" in item.value for item in app.markdown))
            self.assertTrue(any("行動: Stay" in caption.value for caption in app.caption))
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.get("image")), 4)
            old_directory = Path(result["output_dir"])
            renamed_directory = old_directory.with_name(old_directory.name + "_renamed")
            old_directory.rename(renamed_directory)
            widget(app.checkbox, "性格設定（MBTI）を使う").uncheck().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state["result"]["run_id"], result["run_id"])
            self.assertEqual(app.session_state["result"]["output_dir"], str(renamed_directory))
            self.assertEqual(len(app.success), 0)
            # A hot reload can retain an old result without the new metadata.
            app.session_state["result"] = {key: value for key, value in result.items()
                                           if key not in ("model", "execution_date", "timezone")}
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("モデル: 未確認" in caption.value for caption in app.caption))

            # Starting again in this session must replace the previous result,
            # reset its reading controls, and preserve settings and saved files.
            original_bytes = (renamed_directory / "run.json").read_bytes()
            widget(app.radio, "表示する言語").set_value("原文").run()
            widget(app.number_input, "ターン数").set_value(1)
            widget(app.button, "実験をはじめる").click().run(timeout=20)
            finish_experiment(app)
            self.assertEqual(len(app.exception), 0)
            second = app.session_state["result"]
            self.assertNotEqual(second["run_id"], result["run_id"])
            self.assertNotEqual(second["output_dir"], str(renamed_directory))
            self.assertEqual(second["summary"]["total_actions"], 3)
            self.assertEqual(second["logs"][0]["agents"][0]["energy"], 100)
            self.assertEqual(widget(app.radio, "表示する言語").value, "日本語")
            self.assertIsNone(widget(app.selectbox, "表示するエージェント").value)
            self.assertEqual([item.value for item in app.subheader if item.value.startswith("Step ")], ["Step 1"])
            self.assertEqual(len(app.success), 0)
            self.assertEqual(len(app.get("status")), 0)
            self.assertEqual(widget(app.text_input, "保存先").value, directory)
            self.assertEqual((renamed_directory / "run.json").read_bytes(), original_bytes)
            widget(app.button, "結果をクリア").click().run()
            self.assertNotIn("result", app.session_state)
            self.assertEqual(len(app.success), 0)
            self.assertEqual(len(app.get("image")), 1)
            self.assertEqual(widget(app.number_input, "ターン数").value, 1)
            self.assertTrue((Path(second["output_dir"]) / "run.json").is_file())
            request.assert_not_called()

    def test_start_failure_clears_old_result_and_next_start_recovers(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
                aiohttp.ClientSession, "_request", side_effect=AssertionError("No network in Mock")):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            widget(app.selectbox, "動作モード").select("Mock（待機のみ・通信なし）").run()
            widget(app.number_input, "ターン数").set_value(1)
            widget(app.text_input, "保存先").set_value(directory)
            widget(app.button, "実験をはじめる").click().run(timeout=20)
            finish_experiment(app)
            self.assertIn("result", app.session_state)
            with patch("run_data.RunRecorder.__init__", side_effect=OSError("test write failure")):
                widget(app.button, "実験をはじめる").click().run(timeout=20)
                finish_experiment(app)
            self.assertEqual(len(app.exception), 0)
            self.assertNotIn("result", app.session_state)
            self.assertTrue(any("OSError" in item.value for item in app.error))
            self.assertEqual(len(app.get("status")), 0)
            self.assertFalse(any(item.value.startswith("Step ") for item in app.subheader))
            widget(app.button, "実験をはじめる").click().run(timeout=20)
            finish_experiment(app)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.error), 0)
            self.assertEqual(app.session_state["result"]["status"], "completed")

    def test_connection_lost_after_start_is_not_shown_as_success(self):
        from test_simulation import Response

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(aiohttp.ClientSession, "head", return_value=Response(405, "")), \
                patch.object(aiohttp.ClientSession, "_request", side_effect=aiohttp.ClientConnectionError("test failure")):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            widget(app.slider, "最初の個体数").set_value(2)
            widget(app.number_input, "ターン数").set_value(1)
            widget(app.text_input, "保存先").set_value(directory)
            widget(app.button, "実験をはじめる").click().run(timeout=20)
            finish_experiment(app)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.success), 0)
            self.assertIn("completed_with_errors", app.warning[0].value)
            self.assertEqual(app.session_state["result"]["summary"]["llm_errors"], 2)

    def test_request_controls_probe_persistence_and_translation_settings(self):
        from app_ui import translation_connection
        from main import DEFAULT_PARAMS
        from test_simulation import Response, completion
        sent = []
        def post(session, url, **kwargs):
            sent.append(kwargs["json"])
            return Response(200, completion())
        with patch.object(aiohttp.ClientSession, "post", post):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            self.assertTrue(widget(app.selectbox, "推論の強さ").disabled)
            self.assertTrue(widget(app.selectbox, "推論の送信方式").disabled)
            widget(app.number_input, "応答のゆらぎ（Temperature）").set_value(0.8)
            widget(app.number_input, "Top-p").set_value(0.9).run()
            widget(app.toggle, "Temperatureを送信").set_value(False)
            widget(app.toggle, "Top-pを送信").set_value(False)
            widget(app.selectbox, "推論").set_value("on").run()
            self.assertTrue(widget(app.number_input, "応答のゆらぎ（Temperature）").disabled)
            self.assertTrue(widget(app.number_input, "Top-p").disabled)
            self.assertFalse(widget(app.selectbox, "推論の強さ").disabled)
            widget(app.selectbox, "推論の強さ").set_value("high")
            widget(app.selectbox, "出力上限の送信形式").set_value("max_completion_tokens")
            widget(app.button, "接続テスト").click().run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0]["reasoning_effort"], "high")
            self.assertNotIn("temperature", sent[0])
            self.assertNotIn("top_p", sent[0])
            self.assertNotIn("max_tokens", sent[0])
            self.assertIn("max_completion_tokens", sent[0])
            self.assertTrue(any("接続テストに成功" in item.value for item in app.success))
            widget(app.selectbox, "推論").set_value("off").run()
            self.assertTrue(widget(app.selectbox, "推論の強さ").disabled)
            self.assertFalse(any("接続テストに成功" in item.value for item in app.success))
            widget(app.toggle, "Temperatureを送信").set_value(True).run()
            self.assertEqual(widget(app.number_input, "応答のゆらぎ（Temperature）").value, 0.8)
            self.assertEqual(widget(app.number_input, "Top-p").value, 0.9)
            widget(app.toggle, "Temperatureを送信").set_value(False).run()
            widget(app.selectbox, "推論の送信方式").set_value("chat_template").run()
            widget(app.selectbox, "プリセット").set_value("builtin:negotiation").run()
            self.assertEqual(widget(app.selectbox, "推論").value, "off")
            self.assertEqual(widget(app.selectbox, "推論の送信方式").value, "chat_template")
            self.assertFalse(widget(app.toggle, "Temperatureを送信").value)
            widget(app.radio, "表示").set_value("保存した実験").run()
            state = {key: app.session_state[key] for key in ("connection_settings", "experiment_settings")}
            connection = translation_connection(SimpleNamespace(session_state=state), DEFAULT_PARAMS)
            self.assertEqual(connection["reasoning_mode"], "off")
            self.assertEqual(connection["reasoning_format"], "chat_template")
            self.assertFalse(connection["send_temperature"])
            self.assertFalse(connection["send_top_p"])
            self.assertEqual(connection["max_tokens_parameter"], "max_completion_tokens")
            widget(app.radio, "表示").set_value("実験をつくる").run()
            widget(app.toggle, "Temperatureを送信").set_value(True).run()
            self.assertFalse(widget(app.number_input, "応答のゆらぎ（Temperature）").disabled)
            self.assertEqual(widget(app.selectbox, "推論の強さ").value, "high")
            self.assertEqual(len(app.exception), 0)

    def test_library_opens_saved_record_without_sample_button_or_network(self):
        from run_data import read_run
        with patch.object(aiohttp.ClientSession, "_request", side_effect=AssertionError("No network in replay")):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            self.assertFalse(any("サンプル" in button.label for button in app.button))
            sample = read_run(APP_PATH.parent / "examples/first-look/run.json")
            reopened = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            widget(reopened.text_input, "保存先").set_value(str(Path(sample["output_dir"]).parent))
            widget(reopened.radio, "表示").set_value("保存した実験").run()
            self.assertFalse(any("サンプル" in button.label for button in reopened.button))
            widget(reopened.button, "この実験を開く").click().run()
            self.assertEqual(len(reopened.exception), 0)
            self.assertEqual(reopened.session_state["history_result"]["run_id"], sample["run_id"])
            self.assertIn("LLMの判断結果ではありません", reopened.info[0].value)
            initial_board = widget(reopened.expander, "開始時の盤面（Step 0）")
            self.assertTrue(initial_board.proto.expanded)
            self.assertEqual(len(initial_board.get("image")), 1)
            self.assertEqual(initial_board.caption[0].value,
                             "行動前の初期状態です。Step 1以降は、そのターンの行動後を表示します。")
            self.assertEqual(len(reopened.get("image")), min(10, len(sample["logs"]) - 1) + 2)
            self.assertTrue(any("仲間" in text.value for text in reopened.text))
            self.assertEqual(len(reopened.get("download_button")), 0)
            self.assertTrue(any(expander.label == "保存されたファイル" for expander in reopened.expander))
            self.assertEqual(sum(button.label == "Finderで開く" for button in reopened.button), 1)
            self.assertTrue(any("steps.csv" in item.value and "ターンごとの" in item.value for item in reopened.markdown))
            widget(reopened.radio, "表示").set_value("実験をつくる").run()
            self.assertEqual(len(reopened.exception), 0)

    def test_page_navigation_keeps_ascending_steps_and_does_not_rerun_experiment(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
                aiohttp.ClientSession, "_request", side_effect=AssertionError("No network in Mock")):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            widget(app.selectbox, "動作モード").select("Mock（待機のみ・通信なし）").run()
            widget(app.slider, "最初の個体数").set_value(1)
            widget(app.number_input, "ターン数").set_value(12)
            widget(app.text_input, "保存先").set_value(directory)
            widget(app.button, "実験をはじめる").click().run(timeout=30)
            finish_experiment(app)
            self.assertEqual(len(app.exception), 0)
            run_id = app.session_state["result"]["run_id"]
            saved_run = Path(app.session_state["result"]["output_dir"]) / "run.json"
            saved_bytes = saved_run.read_bytes()
            self.assertEqual([item.value for item in app.subheader if item.value.startswith("Step ")],
                             [f"Step {step}" for step in range(1, 11)])
            widget(app.button, "〉").click().run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual([item.value for item in app.subheader if item.value.startswith("Step ")],
                             ["Step 11", "Step 12"])
            self.assertEqual(app.session_state["result"]["run_id"], run_id)
            self.assertFalse(any("scrollTo({top:0" in item.proto.body for item in app.get("html")))
            widget(app.button, "≪").click().run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len([item for item in app.subheader if item.value.startswith("Step ")]), 10)
            widget(app.selectbox, "表示するエージェント").set_value(0).run(timeout=20)
            for label, expected in (("〉", ["Step 11", "Step 12"]),
                                    ("〈", [f"Step {step}" for step in range(1, 11)]),
                                    ("2", ["Step 11", "Step 12"]),
                                    ("≪", [f"Step {step}" for step in range(1, 11)]),
                                    ("≫", ["Step 11", "Step 12"])):
                bottom = next(button for button in app.button
                              if button.label == label and "_bottom_" in (button.key or ""))
                bottom.click().run(timeout=20)
                self.assertEqual(len(app.exception), 0)
                self.assertEqual([item.value for item in app.subheader if item.value.startswith("Step ")], expected)
                self.assertTrue(any("scrollTo({top:0" in item.proto.body and item.proto.unsafe_allow_javascript
                                    for item in app.get("html")))
                self.assertEqual(widget(app.selectbox, "表示するエージェント").value, 0)
                self.assertEqual(app.session_state["result"]["run_id"], run_id)
            app.run(timeout=20)
            self.assertFalse(any("scrollTo({top:0" in item.proto.body for item in app.get("html")))
            self.assertEqual(saved_run.read_bytes(), saved_bytes)

    def test_saved_japanese_is_read_without_network_and_original_remains_available(self):
        from run_data import read_run
        from translations import FILENAME, source_fields, source_hash
        result = read_run(APP_PATH.parent / "examples/first-look/run.json")
        result.pop("demo_notice", None)
        result["config"]["mock_mode"] = False
        with tempfile.TemporaryDirectory() as directory, patch.object(
                aiohttp.ClientSession, "_request", side_effect=AssertionError("No network for reading")):
            result["output_dir"] = directory
            cache = {"version": 1, "run_id": result["run_id"], "entries": {}}
            for snapshot in result["logs"]:
                for event in snapshot["events"]:
                    fields = source_fields(event)
                    cache["entries"][f"{snapshot['step']}:{event['agent_id']}"] = {
                        "status": "completed", "source_sha256": source_hash(fields),
                        "fields": {key: "保存済みの日本語訳" for key in fields}}
            (Path(directory) / "run.json").write_text(json.dumps(result), encoding="utf-8")
            (Path(directory) / FILENAME).write_text(json.dumps(cache), encoding="utf-8")
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            app.session_state["result"] = result
            app.run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("保存済みの日本語訳" in item.value for item in app.text))
            self.assertFalse(any(button.label == "未翻訳分を日本語にする" for button in app.button))
            widget(app.radio, "表示する言語").set_value("原文").run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            self.assertFalse(any("保存済みの日本語訳" in item.value for item in app.text))
            self.assertTrue(any("仲間" in item.value for item in app.text))

    def test_builtin_presets_apply_once_and_allow_independent_adjustment(self):
        app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
        self.assertEqual(widget(app.selectbox, "プリセット").value, "builtin:standard")
        self.assertTrue(widget(app.button, "プリセットを削除").disabled)
        widget(app.text_input, "APIのベースURL").set_value("http://localhost:1234/v1")
        widget(app.text_input, "モデルID").set_value("keep-model")
        widget(app.text_input, "APIキー（必要な場合）").set_value("keep-secret")
        widget(app.text_input, "保存先").set_value(str(self.preset_directory / "runs"))
        widget(app.checkbox, "盤面画像も保存する").check()
        widget(app.selectbox, "プリセット").set_value("builtin:village").run()
        self.assertTrue(app.session_state["experiment_settings"]["custom_world_prompt"])
        widget(app.selectbox, "プリセット").set_value("builtin:negotiation").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(widget(app.number_input, "ターン数").value, 30)
        self.assertEqual(widget(app.number_input, "視界の範囲（マス）").value, 3)
        self.assertEqual(widget(app.number_input, "通信の範囲（マス）").value, 7)
        self.assertEqual(widget(app.selectbox, "砂糖の量").value, "指定する")
        settings = app.session_state["experiment_settings"]
        self.assertEqual(settings["spawn_energy_count"], 2)
        self.assertEqual(settings["num_agents"], settings["population_cap"])
        self.assertEqual(settings["initial_energy"], settings["child_initial_energy"])
        self.assertEqual(settings["custom_world_prompt"], "")
        self.assertFalse(settings["use_mbti"])
        widget(app.number_input, "初期の砂糖の数").set_value(17).run()
        widget(app.radio, "表示").set_value("保存した実験").run()
        widget(app.radio, "表示").set_value("実験をつくる").run()
        self.assertEqual(widget(app.number_input, "初期の砂糖の数").value, 17)
        self.assertEqual(app.session_state["experiment_settings"]["spawn_energy_count"], 17)
        widget(app.selectbox, "プリセット").set_value("builtin:oasis").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(widget(app.number_input, "世界の広さ").value, 15)
        self.assertEqual(widget(app.number_input, "視界の範囲（マス）").value, 7)
        self.assertEqual(widget(app.number_input, "通信の範囲（マス）").value, 7)
        self.assertEqual(widget(app.selectbox, "砂糖の量").value, "少ない")
        self.assertEqual(widget(app.number_input, "砂糖のまとまりの数").value, 1)
        self.assertEqual(widget(app.number_input, "砂糖のまとまりの半径").value, 1)
        self.assertEqual(app.session_state["experiment_settings"]["initial_energy"], 100)
        self.assertEqual(app.session_state["experiment_settings"]["child_initial_energy"], 100)
        self.assertEqual(app.session_state["experiment_settings"]["population_cap"], 60)
        self.assertTrue(widget(app.button, "プリセットを削除").disabled)
        widget(app.number_input, "ターン数").set_value(8)
        widget(app.number_input, "視界の範囲（マス）").set_value(4)
        widget(app.selectbox, "砂糖の量").set_value("多い").run()
        widget(app.radio, "表示").set_value("保存した実験").run()
        widget(app.radio, "表示").set_value("実験をつくる").run()
        self.assertEqual(widget(app.selectbox, "プリセット").value, "builtin:oasis")
        self.assertEqual(widget(app.number_input, "ターン数").value, 8)
        self.assertEqual(widget(app.number_input, "視界の範囲（マス）").value, 4)
        self.assertEqual(app.session_state["experiment_settings"]["spawn_energy_count"], 40)
        self.assertEqual(widget(app.text_input, "APIのベースURL").value, "http://localhost:1234/v1")
        self.assertEqual(widget(app.text_input, "モデルID").value, "keep-model")
        self.assertEqual(widget(app.text_input, "APIキー（必要な場合）").value, "keep-secret")
        self.assertEqual(widget(app.text_input, "保存先").value, str(self.preset_directory / "runs"))
        self.assertTrue(widget(app.checkbox, "盤面画像も保存する").value)
        widget(app.selectbox, "砂糖の量").set_value("指定する").run()
        self.assertEqual(widget(app.number_input, "初期の砂糖の数").value, 40)
        self.assertEqual(app.session_state["experiment_settings"]["spawn_energy_count"], 40)

    def test_register_displayed_run_newest_first_reload_and_delete(self):
        from app_presets import load_user_presets
        with tempfile.TemporaryDirectory() as directory, patch.object(
                aiohttp.ClientSession, "_request", side_effect=AssertionError("No network in presets")):
            source = Path(directory).resolve() / "お気に入りの実験"
            other = Path(directory).resolve() / "別の実験"
            shutil.copytree(APP_PATH.parent / "examples/first-look", source)
            shutil.copytree(APP_PATH.parent / "examples/first-look", other)
            other_manifest = json.loads((other / "manifest.json").read_text())
            other_manifest["config"]["spawn_energy_count"] = 12
            (other / "manifest.json").write_text(json.dumps(other_manifest))
            original = {path.name: path.read_bytes() for path in source.iterdir() if path.is_file()}
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            widget(app.text_input, "保存先").set_value(directory)
            widget(app.radio, "表示").set_value("保存した実験").run()
            widget(app.selectbox, "開く実験").set_value(str(source / "run.json")).run()
            widget(app.button, "この実験を開く").click().run(timeout=20)
            # Changing the chooser does not change the already displayed result.
            widget(app.selectbox, "開く実験").set_value(str(other / "run.json")).run()
            files = widget(app.expander, "保存されたファイル")
            self.assertTrue(any(button.label == "この設定をプリセットに登録" for button in files.button))
            widget(app.text_input, "プリセット名").set_value("最初の登録")
            widget(app.button, "この設定をプリセットに登録").click().run()
            first = load_user_presets()[0]
            self.assertEqual(first["params"]["spawn_energy_count"], 6)
            long_name = "砂糖と視界と通信範囲を少しずつ調整して気に入った長い名前のプリセット"
            widget(app.text_input, "プリセット名").set_value(long_name)
            widget(app.button, "この設定をプリセットに登録").click().run()
            second = load_user_presets()[0]
            self.assertEqual([item["name"] for item in load_user_presets()], [long_name, "最初の登録"])
            self.assertEqual({path.name: path.read_bytes() for path in source.iterdir() if path.is_file()}, original)
            # A new app session loads persistent entries without applying them.
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            choices = widget(app.selectbox, "プリセット")
            self.assertEqual(choices.options[:2], [long_name, "最初の登録"])
            self.assertEqual(choices.value, "builtin:standard")
            choices.set_value(second["id"]).run()
            self.assertEqual(widget(app.selectbox, "砂糖の量").value, "指定する")
            self.assertEqual(widget(app.number_input, "初期の砂糖の数").value, 6)
            self.assertEqual(widget(app.number_input, "繁殖コスト").value, 70)
            self.assertFalse(widget(app.button, "プリセットを削除").disabled)
            widget(app.number_input, "初期の砂糖の数").set_value(17).run()
            widget(app.number_input, "ターン数").set_value(1)
            widget(app.selectbox, "動作モード").set_value("Mock（待機のみ・通信なし）").run()
            widget(app.text_input, "保存先").set_value(str(Path(directory) / "new-runs"))
            widget(app.button, "実験をはじめる").click().run(timeout=20)
            finish_experiment(app)
            self.assertEqual(app.session_state["result"]["config"]["spawn_energy_count"], 17)
            widget(app.button, "プリセットを削除").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual([item["id"] for item in load_user_presets()], [first["id"]])
            self.assertIsNone(widget(app.selectbox, "プリセット").value)
            self.assertTrue(widget(app.button, "プリセットを削除").disabled)
            self.assertEqual(widget(app.number_input, "初期の砂糖の数").value, 17)
            self.assertEqual(widget(app.number_input, "繁殖コスト").value, 70)
            widget(app.selectbox, "プリセット").set_value("builtin:standard").run()
            self.assertTrue(widget(app.button, "プリセットを削除").disabled)
            self.assertEqual(widget(app.selectbox, "砂糖の量").value, "標準")
            self.assertEqual(widget(app.number_input, "繁殖コスト").value, 70)
            self.assertEqual(widget(app.number_input, "各ターンの砂糖の追加確率").value, 0.2)

    def test_range_controls_change_observation_and_delivery_in_saved_runs(self):
        from experiment_task import ExperimentTask
        from main import main, Simulation

        original_init = Simulation.__init__
        def fixed_positions(sim, *args, **kwargs):
            original_init(sim, *args, **kwargs)
            for agent, position in zip(sim.agents, ((0, 0), (15, 15), (29, 29))):
                agent.position = position
            sim.environment.energy_sources = {(15, 15): 50, (29, 29): 50}
        def task_factory(runner, params):
            return ExperimentTask(main, params)

        with tempfile.TemporaryDirectory() as directory, \
                patch("app_ui.ExperimentTask", side_effect=task_factory), \
                patch.object(Simulation, "__init__", fixed_positions), \
                patch.object(aiohttp.ClientSession, "_request", side_effect=AssertionError("No network in Mock")):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            world = widget(app.expander, "世界設定")
            self.assertEqual(widget(world.number_input, "視界の範囲（マス）").value, 5)
            self.assertEqual(widget(world.number_input, "通信の範囲（マス）").value, 5)
            self.assertIn("視界：11 × 11マス", [item.value for item in world.caption])
            self.assertIn("通信：11 × 11マス", [item.value for item in world.caption])
            widget(app.selectbox, "動作モード").select("Mock（待機のみ・通信なし）").run()
            widget(app.text_input, "保存先").set_value(directory)
            widget(app.number_input, "ターン数").set_value(2)
            # Independent controls, both endpoints, and wrapping at the edge.
            for view_range, message_range in ((0, 15), (15, 0), (1, 1), (50, 50)):
                with self.subTest(view_range=view_range, message_range=message_range):
                    widget(app.number_input, "視界の範囲（マス）").set_value(view_range)
                    widget(app.number_input, "通信の範囲（マス）").set_value(message_range)
                    widget(app.button, "実験をはじめる").click().run(timeout=20)
                    finish_experiment(app)
                    self.assertEqual(len(app.exception), 0)
                    result = app.session_state["result"]
                    self.assertEqual(result["status"], "completed")
                    saved = json.loads((Path(result["output_dir"]) / "run.json").read_text())
                    for record in (result, saved):
                        self.assertEqual(record["config"]["view_range"], view_range)
                        self.assertEqual(record["config"]["message_range"], message_range)
                    event = saved["logs"][1]["events"][0]
                    prompt = event["user_prompt"]
                    other_text, resource_text = prompt.split("Visible Other Agents:\n")[1].split(
                        "\nVisible Energy Sources:\n")
                    resource_text = resource_text.split("\nMemory:")[0]
                    others = [] if other_text == "none" else [json.loads(row) for row in other_text.splitlines()]
                    resources = [] if resource_text == "none" else [json.loads(row) for row in resource_text.splitlines()]
                    visible_ids = [1, 2] if view_range >= 15 else [2] if view_range >= 1 else []
                    distances = [21.2, 1.4] if view_range >= 15 else [1.4] if view_range >= 1 else []
                    self.assertEqual([row["target_id"] for row in others], visible_ids)
                    self.assertEqual([row["distance_cells"] for row in resources], distances)
                    self.assertEqual([row["distance_cells"] for row in others], distances)
                    for row in [*others, *resources]:
                        self.assertEqual(row["observer_id"], 0)
                        self.assertEqual(row["direction"], "northwest")
                    expected = [1, 2] if message_range >= 15 else [2] if message_range >= 1 else []
                    self.assertEqual(event["message_recipient_ids"], expected)
                    for agent in saved["logs"][2]["agents"][1:]:
                        self.assertEqual("Agent0: Hello world" in agent["messages"], agent["id"] in expected)

    def test_ranges_survive_page_and_world_size_changes(self):
        app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
        widget(app.number_input, "視界の範囲（マス）").set_value(15)
        widget(app.number_input, "通信の範囲（マス）").set_value(50).run()
        widget(app.radio, "表示").set_value("保存した実験").run()
        widget(app.radio, "表示").set_value("実験をつくる").run()
        self.assertEqual(widget(app.number_input, "視界の範囲（マス）").value, 15)
        self.assertEqual(widget(app.number_input, "通信の範囲（マス）").value, 50)
        widget(app.number_input, "世界の広さ").set_value(11).run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("視界：11 × 11マス（世界全体）", [item.value for item in app.caption])
        self.assertIn("通信：11 × 11マス（世界全体）", [item.value for item in app.caption])
        widget(app.number_input, "世界の広さ").set_value(100).run()
        self.assertIn("視界：31 × 31マス", [item.value for item in app.caption])
        self.assertIn("通信：100 × 100マス（世界全体）", [item.value for item in app.caption])
        widget(app.number_input, "視界の範囲（マス）").set_value(0)
        widget(app.number_input, "通信の範囲（マス）").set_value(0).run()
        self.assertIn("視界：1 × 1マス", [item.value for item in app.caption])
        self.assertIn("通信：1 × 1マス", [item.value for item in app.caption])

    def test_food_choice_is_used_by_next_run_and_keeps_other_settings(self):
        app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
        widget(app.text_input, "APIのベースURL").set_value("http://localhost:1234/v1")
        widget(app.text_input, "モデルID").set_value("test-model")
        self.assertEqual(widget(app.selectbox, "砂糖の量").value, "標準")
        widget(app.number_input, "エージェントの体力（初期値）").set_value(120)
        widget(app.checkbox, "性格設定（MBTI）を使う").check()
        widget(app.selectbox, "砂糖の量").set_value("少ない").run()
        self.assertNotIn("result", app.session_state)
        self.assertFalse(any(button.label == "適用" for button in app.button))
        self.assertEqual(app.session_state["experiment_settings"]["spawn_energy_count"], 4)
        self.assertEqual(widget(app.number_input, "エージェントの体力（初期値）").value, 120)
        self.assertTrue(widget(app.checkbox, "性格設定（MBTI）を使う").value)
        self.assertEqual(widget(app.text_input, "モデルID").value, "test-model")
        self.assertEqual(widget(app.text_input, "APIのベースURL").value, "http://localhost:1234/v1")
        widget(app.text_input, "APIキー（必要な場合）").set_value("session-only-test-key").run()
        widget(app.checkbox, "性格設定（MBTI）を使う").check().run()
        widget(app.selectbox, "動作モード").set_value("Mock（待機のみ・通信なし）").run()
        widget(app.radio, "表示").set_value("保存した実験").run()
        widget(app.radio, "表示").set_value("実験をつくる").run()
        self.assertEqual(widget(app.selectbox, "動作モード").value, "Mock（待機のみ・通信なし）")
        self.assertEqual(widget(app.text_input, "モデルID").value, "test-model")
        self.assertEqual(widget(app.text_input, "APIキー（必要な場合）").value, "session-only-test-key")
        self.assertEqual(app.session_state["experiment_settings"]["spawn_energy_count"], 4)
        self.assertTrue(widget(app.checkbox, "性格設定（MBTI）を使う").value)
        with tempfile.TemporaryDirectory() as directory, patch.object(
                aiohttp.ClientSession, "_request", side_effect=AssertionError("No network in Mock")):
            widget(app.text_input, "保存先").set_value(directory)
            widget(app.number_input, "ターン数").set_value(1)
            widget(app.button, "実験をはじめる").click().run(timeout=20)
            finish_experiment(app)
            self.assertEqual(len(app.exception), 0)
            result = app.session_state["result"]
            self.assertEqual(result["config"]["spawn_energy_count"], 4)
            self.assertEqual(len(result["logs"][0]["environment"]["resources"]), 4)
            self.assertEqual(result["config"]["initial_energy"], 120)
            self.assertTrue(result["config"]["use_mbti"])
        widget(app.number_input, "人口の上限").set_value(1).run()
        self.assertTrue(widget(app.button, "実験をはじめる").disabled)


if __name__ == "__main__":
    unittest.main()
