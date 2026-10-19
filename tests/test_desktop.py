import os
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from desktop import (WindowServer, launch, output_directory, select_output_directory,
                     open_experiment_directory, serve_window, server_command)


class DesktopTests(unittest.TestCase):
    def test_finder_opens_renamed_experiment_folder_and_rejects_other_run(self):
        with tempfile.TemporaryDirectory() as temporary, patch("desktop.subprocess.run") as opened:
            root = Path(temporary)
            old = root / "前の名前"
            saved = root / "現在の名前"
            saved.mkdir()
            (saved / "manifest.json").write_text(json.dumps({"run_id": "this-experiment"}))
            open_experiment_directory(str(old), "this-experiment")
            opened.assert_called_once_with(["/usr/bin/open", "-a", "Finder", str(saved.resolve())], check=True)
            opened.reset_mock()
            with self.assertRaises(ValueError):
                open_experiment_directory(str(saved), "different-experiment")
            with self.assertRaises(ValueError):
                open_experiment_directory(str(root / "missing"), "missing-experiment")
            opened.assert_not_called()

    def test_first_dialog_starts_beside_app_then_uses_selected_folder(self):
        window = MagicMock()
        server = Mock()
        server.closed.is_set.return_value = False

        def exercise_dialog(*args, **kwargs):
            choose = window.expose.call_args.args[0]
            self.assertIsNone(choose("/app-folder/outputs"))
            self.assertEqual(choose("/app-folder/outputs"), "/selected-folder")
            self.assertIsNone(choose("/selected-folder"))

        with patch("webview.create_window", return_value=window), \
                patch("webview.start", side_effect=exercise_dialog), \
                patch("desktop.WindowServer", return_value=server), \
                patch("desktop.application_directory", return_value=Path("/app-folder")), \
                patch("desktop.select_output_directory", side_effect=[None, "/selected-folder", None]) as choose:
            launch()
        self.assertEqual([call.args[1] for call in choose.call_args_list],
                         ["/app-folder", "/app-folder", "/selected-folder"])

    def test_folder_dialog_returns_selected_folder_and_starts_at_existing_parent(self):
        from webview import FileDialog

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            chosen = root / "新しい実験フォルダ"
            chosen.mkdir()
            window = Mock()
            window.create_file_dialog.return_value = (str(chosen),)
            self.assertEqual(select_output_directory(window, str(root / "not-created/outputs")), str(chosen))
            window.create_file_dialog.assert_called_once_with(
                FileDialog.FOLDER, directory=str(root), allow_multiple=False)

    def test_folder_dialog_cancel_keeps_current_location_and_rejects_a_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            window = Mock()
            window.create_file_dialog.return_value = None
            self.assertIsNone(select_output_directory(window, temporary))
            file = Path(temporary) / "record.txt"
            file.write_text("keep this record", encoding="utf-8")
            window.create_file_dialog.return_value = (str(file),)
            with self.assertRaises(ValueError):
                select_output_directory(window, temporary)
            self.assertEqual(file.read_text(encoding="utf-8"), "keep this record")

    def test_experiments_are_saved_beside_app_or_source_with_optional_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            resources = parent / "SugarScape.app/Contents/Resources"
            with patch.dict(os.environ, {"SUGARSCAPE_OUTPUT_DIR": ""}), \
                    patch("desktop.ROOT", resources), patch("desktop.sys.frozen", True, create=True):
                self.assertEqual(output_directory(), parent / "outputs")
            with patch.dict(os.environ, {"SUGARSCAPE_OUTPUT_DIR": ""}), \
                    patch("desktop.ROOT", parent), patch("desktop.sys.frozen", False, create=True):
                self.assertEqual(output_directory(), parent / "outputs")
            with patch.dict(os.environ, {"SUGARSCAPE_OUTPUT_DIR": str(parent / "chosen")}), \
                    patch("desktop.ROOT", resources), patch("desktop.sys.frozen", True, create=True):
                self.assertEqual(output_directory(), parent / "chosen")

    def test_child_bootstrap_disables_browser_and_frozen_path_development_detection(self):
        with patch.dict("sys.modules", {"AppKit": Mock()}), patch("desktop.threading.Thread"), \
                patch("streamlit.web.bootstrap.load_config_options") as configure, \
                patch("streamlit.web.bootstrap.run") as run:
            serve_window(50123, "instance-path", os.getpid())
        options = configure.call_args.args[0]
        self.assertIs(options["global.developmentMode"], False)
        self.assertIs(options["server.headless"], True)
        self.assertEqual(options["server.address"], "127.0.0.1")
        self.assertEqual(options["server.port"], 50123)
        self.assertEqual(options["server.baseUrlPath"], "instance-path")
        self.assertEqual(run.call_args.args[3], options)

    def test_frozen_child_uses_own_bundle_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            contents = Path(temporary) / "SugarScape.app/Contents"
            resources = contents / "Resources"
            resources.mkdir(parents=True)
            (contents / "Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "LLM SugarScape"}))
            with patch("desktop.ROOT", resources), patch("desktop.sys.frozen", True, create=True):
                command = server_command(50123, "instance-path")
            self.assertEqual(command, [str(contents / "MacOS/LLM SugarScape"), "--serve-window",
                                       "50123", "instance-path", str(os.getpid())])

    def test_local_start_sets_storage_and_close_stops_only_owned_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            child = Mock()
            child.poll.return_value = None
            response = Mock(status=200)
            response.read.return_value = b"ok"
            with patch("desktop.subprocess.Popen", return_value=child) as spawn, patch("desktop.urlopen") as health, \
                    patch("desktop.socket.socket") as socket, \
                    patch("desktop.output_directory", return_value=Path(temporary) / "outputs"):
                socket.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 50123)
                health.return_value.__enter__.return_value = response
                server = WindowServer(temporary)
                url = server.start()
                self.assertTrue(url.startswith("http://127.0.0.1:"))
                command = spawn.call_args.args[0]
                self.assertIn("--serve-window", command)
                self.assertEqual(spawn.call_args.kwargs["env"]["SUGARSCAPE_OUTPUT_DIR"],
                                 str(Path(temporary) / "outputs"))
                server.close()
                self.assertTrue(server.closed.is_set())
                child.terminate.assert_called_once()
                child.kill.assert_not_called()
                self.assertIsNone(server.log)

    def test_unresponsive_child_is_killed_without_process_lookup(self):
        child = Mock()
        child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired("own-child", 5), 0]
        server = WindowServer("unused")
        server.process = child
        server.close()
        child.terminate.assert_called_once()
        child.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
