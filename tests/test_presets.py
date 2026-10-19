import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app_presets import (BUILTIN_PRESETS, PRESET_FIELDS, apply_parameters, delete_preset,
                         load_user_presets, preset_store_path, register_preset)
from main import DEFAULT_PARAMS
from run_data import read_run

ROOT = Path(__file__).resolve().parents[1]


class PresetTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.run = self.root / "experiment"
        shutil.copytree(ROOT / "examples/first-look", self.run)
        self.result = read_run(self.run / "run.json")
        self.store = self.root / "settings/presets.json"

    def test_registration_uses_manifest_omits_connection_and_preserves_experiment(self):
        manifest = json.loads((self.run / "manifest.json").read_text())
        manifest["config"].update(spawn_energy_count=17, api_key="private-key", model="saved-model",
                                  base_url="http://private-server/v1", output_dir="/private/saved-place")
        (self.run / "manifest.json").write_text(json.dumps(manifest))
        before = {path.name: path.read_bytes() for path in self.run.iterdir() if path.is_file()}
        preset = register_preset(self.result, "お気に入り", self.store)
        self.assertEqual(preset["params"]["spawn_energy_count"], 17)
        self.assertEqual(preset["source_run_id"], self.result["run_id"])
        self.assertTrue(set(preset["params"]).issubset(PRESET_FIELDS))
        for value in ("private-key", "saved-model", "private-server", "/private/saved-place"):
            self.assertNotIn(value, self.store.read_text())
        self.assertEqual({path.name: path.read_bytes() for path in self.run.iterdir() if path.is_file()}, before)
        self.assertEqual(load_user_presets(self.store), [preset])
        values = apply_parameters(preset, DEFAULT_PARAMS)
        self.assertEqual(values["view_range"], 5)
        self.assertEqual(values["message_range"], 5)
        self.assertEqual(values["top_p"], 1.0)

    def test_newest_first_delete_only_one_and_protect_builtins(self):
        first = register_preset(self.result, "一番目", self.store)
        second = register_preset(self.result, "二番目", self.store)
        self.assertEqual([item["id"] for item in load_user_presets(self.store)], [second["id"], first["id"]])
        for builtin in BUILTIN_PRESETS:
            with self.assertRaisesRegex(ValueError, "同梱"):
                delete_preset(builtin["id"], self.store)
        delete_preset(second["id"], self.store)
        self.assertEqual(load_user_presets(self.store), [first])
        with self.assertRaisesRegex(ValueError, "すでに削除"):
            delete_preset(second["id"], self.store)

    def test_request_controls_round_trip_and_legacy_defaults(self):
        options = {"send_temperature": False, "send_top_p": False, "reasoning_mode": "on",
                   "reasoning_format": "openai", "reasoning_effort": "high",
                   "max_tokens_parameter": "max_completion_tokens"}
        legacy = register_preset(self.result, "旧データ", self.store)
        restored = apply_parameters(legacy, DEFAULT_PARAMS)
        self.assertEqual({key: restored[key] for key in options},
                         {key: DEFAULT_PARAMS[key] for key in options})
        manifest = json.loads((self.run / "manifest.json").read_text())
        manifest["config"].update(options)
        (self.run / "manifest.json").write_text(json.dumps(manifest))
        register_preset(self.result, "推論あり", self.store)
        restored = apply_parameters(load_user_presets(self.store)[0], DEFAULT_PARAMS)
        self.assertEqual({key: restored[key] for key in options}, options)

    def test_names_validation_does_not_overwrite_existing_presets(self):
        register_preset(self.result, "一番目", self.store)
        before = self.store.read_bytes()
        for name in ("", "\n", "名前\n改行", "長" * 121, "一番目", "最後のオアシス"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                register_preset(self.result, name, self.store)
            self.assertEqual(self.store.read_bytes(), before)
        name = "長いプリセット名・砂糖と視界を調整した実験" * 4
        self.assertEqual(register_preset(self.result, name, self.store)["name"], name)

    def test_corrupt_store_is_not_replaced_by_registration_or_deletion(self):
        self.store.parent.mkdir()
        self.store.write_text('{"broken":true}')
        before = self.store.read_bytes()
        for operation in (lambda: register_preset(self.result, "新しい", self.store),
                          lambda: delete_preset("user:unknown", self.store)):
            with self.assertRaises(ValueError):
                operation()
            self.assertEqual(self.store.read_bytes(), before)

    def test_invalid_saved_settings_are_rejected_without_silent_clamping(self):
        manifest_path = self.run / "manifest.json"
        original = json.loads(manifest_path.read_text())
        for name, value in (("view_range", -1), ("message_range", 51), ("grid_size", 8),
                            ("num_agents", 100), ("use_mbti", "false"), ("temperature", float("nan")),
                            ("spawn_energy_count", 122), ("custom_world_prompt", ["bad type"]),
                            ("send_temperature", "false"), ("send_top_p", 0), ("reasoning_mode", "auto"),
                            ("reasoning_format", "unknown"), ("reasoning_effort", "invalid"),
                            ("max_tokens_parameter", "unknown")):
            with self.subTest(name=name):
                manifest = {**original, "config": {**original["config"], name: value}}
                manifest_path.write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    register_preset(self.result, "登録できない", self.store)
                self.assertFalse(self.store.exists())

    def test_shared_store_keeps_concurrent_registrations(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            entries = list(pool.map(lambda index: register_preset(self.result, f"実験{index}", self.store), range(8)))
        self.assertEqual({item["id"] for item in load_user_presets(self.store)}, {item["id"] for item in entries})
        self.assertFalse(self.store.with_suffix(".json.tmp").exists())

    def test_presets_share_existing_data_directory_independent_of_output_folder(self):
        with patch.dict("os.environ", {"SUGARSCAPE_DATA_DIR": str(self.root / "app-data"),
                                       "SUGARSCAPE_OUTPUT_DIR": str(self.root / "runs")}):
            self.assertEqual(preset_store_path(), self.root / "app-data/presets.json")


if __name__ == "__main__":
    unittest.main()
