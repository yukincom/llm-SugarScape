import asyncio
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from app_presets import FOOD_PRESETS, STARTER, connection_feedback
from main import DEFAULT_PARAMS, check_connection
from run_data import read_run, saved_runs, rename_run, locate_run_directory
from test_simulation import Session, completion
from tools.build_release import build_release

ROOT = Path(__file__).resolve().parents[1]


class ProductTests(unittest.TestCase):
    def test_rename_preserves_data_and_finds_run_after_old_name_is_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "元の名前"
            shutil.copytree(ROOT / "examples/first-look", original)
            result = read_run(original / "run.json")
            before = {path.name: path.read_bytes() for path in original.iterdir() if path.is_file()}
            renamed = rename_run(original / "run.json", "変更した名前")
            self.assertFalse(original.exists())
            self.assertEqual({name: (renamed.parent / name).read_bytes() for name in before}, before)
            self.assertEqual(saved_runs(renamed.parent), [(renamed, renamed.parent.name)])
            original.mkdir()
            (original / "manifest.json").write_text(json.dumps({"run_id": "different-experiment"}))
            self.assertEqual(locate_run_directory(result), renamed.parent)

    def test_rename_rejects_invalid_existing_running_and_translating_targets(self):
        import fcntl
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            saved = root / "元の名前"
            shutil.copytree(ROOT / "examples/first-look", saved)
            path = saved / "run.json"
            for invalid in ("", ".", "..", "../outside", "folder/name", "bad:name", "bad\\name"):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    rename_run(path, invalid)
            (root / "使用済み").mkdir()
            (root / "使用済み" / "keep.txt").write_text("keep")
            with self.assertRaises(ValueError):
                rename_run(path, "使用済み")
            self.assertEqual((root / "使用済み" / "keep.txt").read_text(), "keep")
            with (saved / ".translations.ja.lock").open("a") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(ValueError):
                    rename_run(path, "翻訳中")
            manifest_path = saved / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["status"] = "running"
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                rename_run(path, "実験中")
            self.assertTrue(path.exists())

    def test_rename_does_not_replace_target_created_after_validation(self):
        from run_data import _rename_directory_exclusive
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            saved = root / "元の名前"
            shutil.copytree(ROOT / "examples/first-look", saved)
            destination = root / "競合した名前"
            def concurrent_create(source, target):
                target.mkdir()
                _rename_directory_exclusive(source, target)
            with patch("run_data._rename_directory_exclusive", side_effect=concurrent_create):
                with self.assertRaises(ValueError):
                    rename_run(saved / "run.json", destination.name)
            self.assertTrue((saved / "run.json").is_file())
            self.assertTrue(destination.is_dir())
            self.assertEqual(list(destination.iterdir()), [])

    def test_presets_change_only_food_and_keep_world_defaults(self):
        baseline = STARTER
        for preset in FOOD_PRESETS.values():
            self.assertEqual(set(preset["params"]), {"spawn_energy_count"})
        self.assertEqual(FOOD_PRESETS["標準"]["params"]["spawn_energy_count"], baseline["spawn_energy_count"])
        for key, value in (("initial_energy", 100), ("child_initial_energy", 100), ("population_cap", 60)):
            self.assertEqual(baseline[key], value)
            self.assertEqual(DEFAULT_PARAMS[key], value)
        self.assertIs(baseline["use_mbti"], False)
        self.assertIs(DEFAULT_PARAMS["use_mbti"], False)

    def test_read_only_replay_ignores_embedded_output_path_and_deduplicates_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy = root / "copied"
            shutil.copytree(ROOT / "examples/first-look", copy)
            path = copy / "run.json"
            data = json.loads(path.read_text())
            data["output_dir"] = "/some/other/private/folder"
            path.write_text(json.dumps(data))
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in copy.iterdir()}
            loaded = read_run(path)
            self.assertEqual(loaded["output_dir"], str(copy.resolve()))
            self.assertEqual(loaded["logs"], data["logs"])
            after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in copy.iterdir()}
            self.assertEqual(before, after)
            (root / "alias").symlink_to(copy, target_is_directory=True)
            self.assertEqual(len(saved_runs(root)), 1)
            data["logs"][1]["step"] = 9
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                read_run(path)
            data["logs"][1]["step"] = 1
            del data["logs"][1]["summary"]["step"]
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                read_run(path)

    def test_connection_probe_uses_existing_parser_without_recording(self):
        session = Session(body=completion())
        with patch("main.RunRecorder", side_effect=AssertionError("Probe must not create a run")):
            event = asyncio.run(check_connection({"base_url": "http://localhost:1234/v1", "model": "demo",
                                                  "api_key": "test-secret"}, session=session))
        self.assertTrue(connection_feedback(event)[0])
        self.assertEqual(len(session.requests), 1)
        url, request = session.requests[0]
        self.assertEqual(url, "http://localhost:1234/v1/chat/completions")
        self.assertEqual(request["json"]["model"], "demo")
        self.assertEqual(request["headers"]["Authorization"], "Bearer test-secret")
        for status, phrase in ((401, "APIキー"), (404, "モデル"), (429, "利用上限")):
            failed = asyncio.run(check_connection({}, session=Session(status, "private error")))
            ok, message = connection_feedback(failed)
            self.assertFalse(ok)
            self.assertIn(phrase, message)
            self.assertNotIn("private error", message)

    @unittest.skipUnless(sys.platform == "darwin", "Mac archive format uses ditto")
    def test_release_archives_app_without_workspace_and_rejects_aliases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "LLM SugarScape.app"
            contents = app / "Contents"
            (contents / "Frameworks").mkdir(parents=True)
            (contents / "Frameworks/libpython3.11.dylib").write_bytes(b"runtime fixture")
            info = contents / "Info.plist"
            info.write_bytes(plistlib.dumps({"PythonInfoDict": {"py2app": {"alias": False}}}))
            (root / "private-experiment.json").write_text("must not be packaged")
            run = subprocess.run
            def run_with_fixture_signature(command, **kwargs):
                if command[0] == "/usr/bin/codesign":
                    return subprocess.CompletedProcess(command, 0)
                return run(command, **kwargs)
            with patch("tools.build_release.subprocess.run", side_effect=run_with_fixture_signature):
                archive = build_release(app=app, destination=root / "release")
            with zipfile.ZipFile(archive) as bundle:
                self.assertIn("LLM SugarScape.app/Contents/Frameworks/libpython3.11.dylib", bundle.namelist())
                self.assertFalse(any("private-experiment" in name for name in bundle.namelist()))
            digest = archive.with_suffix(".zip.sha256").read_text().split()[0]
            self.assertEqual(digest, hashlib.sha256(archive.read_bytes()).hexdigest())
            with patch("tools.build_release.subprocess.run", side_effect=run_with_fixture_signature):
                with self.assertRaises(FileExistsError):
                    build_release(app=app, destination=root / "release")
            info.write_bytes(plistlib.dumps({"PythonInfoDict": {"py2app": {"alias": True}}}))
            with self.assertRaises(ValueError):
                build_release(app=app, destination=root / "other-release")


if __name__ == "__main__":
    unittest.main()
