"""Verify launch selection and stopping without starting a server or model."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ComparisonLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="comparison launch ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "tools").mkdir()
        (self.root / ".venv/bin").mkdir(parents=True)
        (self.root / "bin").mkdir()
        shutil.copyfile(ROOT / "tools/run_prompt_comparison.sh", self.root / "tools/run_prompt_comparison.sh")
        for name in ("main.py", "paper_prompts.py", "observations.py", "response_fields.py", "llm_api.py",
                     "run_data.py", "model_identity.py", "app_presets.py"):
            (self.root / name).write_text("# offline fixture\n")
        git = self.root / "bin/git"
        git.write_text("#!/bin/sh\nprintf 'fixture-commit\\n'\n")
        git.chmod(0o755)
        python = self.root / ".venv/bin/python"
        python.write_text(f"#!{sys.executable}\n" + """
import json, os, sys
from pathlib import Path
with Path('calls.jsonl').open('a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
if os.environ.get('CHANGE_SOURCE'):
    Path('main.py').write_text('# changed during batch\\n')
if os.environ.get('FAIL_CLI'):
    sys.exit(2)
""")
        python.chmod(0o755)
        self.env = {**os.environ, "PATH": str(self.root / "bin") + os.pathsep + os.environ["PATH"],
                    "SUGARSCAPE_MODEL": "test-model"}

    def launch(self, *args, **env):
        return subprocess.run(["bash", "tools/run_prompt_comparison.sh", *args], cwd=self.root,
                              env={**self.env, **env}, capture_output=True, text=True, timeout=30)

    def calls(self):
        path = self.root / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_modes_select_expected_runs_and_preview_is_default(self):
        for mode, count, steps in (("preview", 27, 30), ("mock", 27, 2), ("smoke", 2, 1),
                                   ("pilot", 2, 30), ("full", 27, 30)):
            with self.subTest(mode=mode):
                before = len(self.calls())
                result = self.launch() if mode == "preview" else self.launch(mode, f"results {mode}")
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = self.calls()[before:]
                runs = [call for call in calls if call[1] == "run"]
                self.assertEqual(len(runs), count)
                self.assertEqual(len(calls), count + (mode != "preview"))
                for call in runs:
                    self.assertEqual(call[call.index("--steps") + 1], str(steps))
                    self.assertEqual(call[call.index("--model") + 1], "test-model")
                    self.assertEqual("--preview-prompts" in call, mode == "preview")
                    self.assertEqual("--mock" in call, mode == "mock")
                    factors = [call[i + 1] for i, token in enumerate(call) if token == "--prompt-factor"]
                    self.assertFalse({"relative_coordinates", "spatial_relations"} <= set(factors))
                self.assertEqual(sorted({call[call.index("--seed") + 1] for call in runs}),
                                 ["42"] if count == 2 else ["42", "43", "44"])
                self.assertNotIn("--prompt-factor", runs[0])
                if count == 2:
                    self.assertEqual(runs[1][-2:], ["--prompt-factor", "spatial_relations"])

    def test_cli_failure_stops_before_the_next_run(self):
        result = self.launch("full", "failed batch", FAIL_CLI="1")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(self.calls()), 1)

    def test_source_change_stops_before_the_next_run(self):
        result = self.launch("full", "changed batch", CHANGE_SOURCE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.calls()), 1)

    def test_invalid_mode_and_existing_output_do_not_launch(self):
        self.assertEqual(self.launch("unknown").returncode, 2)
        self.assertEqual(self.launch("preview", "new", "extra").returncode, 2)
        destination = self.root / "existing"
        destination.mkdir()
        (destination / "saved.txt").write_text("preserve this")
        self.assertNotEqual(self.launch("full", "existing").returncode, 0)
        self.assertEqual((destination / "saved.txt").read_text(), "preserve this")
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
