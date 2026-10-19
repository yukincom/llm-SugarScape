import csv
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from main import main
from model_identity import ModelIdentity
from run_data import collect_runs, experiment_date, export_run


class ManagerResponse:
    status = 200

    def __init__(self, data):
        self.data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        return self.data


class ManagerSession:
    def __init__(self, server):
        self.server = server
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append(url)
        return ManagerResponse({"app": "mlx-server-manager", "token": "private-manager-token",
                                "log": ["private-log-entry"], "server": self.server})


class IdentityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.revision = "a" * 40
        repo = self.root / "models--example--tiny"
        self.snapshot = repo / "snapshots" / self.revision
        self.snapshot.mkdir(parents=True)
        self.ref = repo / "refs/main"
        self.ref.parent.mkdir()
        self.ref.write_text(self.revision)
        (self.snapshot / "config.json").write_text(json.dumps({"quantization": {"bits": 6, "group_size": 64}}))
        (self.snapshot / "tokenizer.json").write_text('{}')
        (self.snapshot / "model-1.safetensors").write_bytes(b"first shard")
        (self.snapshot / "model-2.safetensors").write_bytes(b"second shard")
        (self.snapshot / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {
            "layer.0": "model-1.safetensors", "layer.1": "model-2.safetensors"}}))
        self.server = {"running": True, "trusted": True, "pid": 1234, "active_model": "example/tiny",
                       "command": "python -m mlx_lm.server --model example/tiny --port 8080"}
        self.session = ManagerSession(self.server)
        self.config = {"base_url": "http://127.0.0.1:8080/v1", "model": "default_model", "mock_mode": False}
        self.started = time.time() + 10
        for target, value in (("model_identity.cache_root", self.root),
                              ("model_identity.process_started_at", self.started)):
            patched = patch(target, return_value=value)
            patched.start()
            self.addCleanup(patched.stop)

    async def test_real_name_revision_all_shard_hashes_and_no_manager_secrets(self):
        identity = await ModelIdentity.capture(self.config, self.session)
        info = await identity.finish(self.session)
        self.assertEqual(info["status"], "recorded")
        self.assertEqual(info["id"], "example/tiny")
        self.assertEqual(info["revision"], self.revision)
        self.assertEqual(info["quantization"]["bits"], 6)
        self.assertEqual({w["file"]: w["sha256"] for w in info["weights"]}, {
            "model-1.safetensors": hashlib.sha256(b"first shard").hexdigest(),
            "model-2.safetensors": hashlib.sha256(b"second shard").hexdigest()})
        encoded = json.dumps(info)
        for value in ("private-manager-token", "private-log-entry", "command", "mlx-lm"):
            self.assertNotIn(value, encoded)

    async def test_snapshot_modified_after_server_launch_is_not_attributed(self):
        with patch("model_identity.process_started_at", return_value=1):
            identity = await ModelIdentity.capture(self.config, self.session)
        self.assertEqual(identity.info["status"], "unavailable")
        self.assertEqual(identity.info["reason"], "files_changed_since_server_start")
        self.assertNotIn("weights", identity.info)

    async def test_model_or_files_change_marks_run_unusable(self):
        identity = await ModelIdentity.capture(self.config, self.session)
        self.session.server = {**self.server, "pid": 5678}
        self.assertEqual((await identity.finish(self.session))["reason"], "server_changed")
        self.session.server = self.server
        identity = await ModelIdentity.capture(self.config, self.session)
        (self.snapshot / "model-1.safetensors").write_bytes(b"changed weights")
        self.assertEqual((await identity.finish(self.session))["reason"], "model_files_changed")

    async def test_adapter_and_draft_are_not_assumed_from_launch_flags(self):
        for flag, reason in (("--adapter-path", "adapter_application_unverified"),
                             ("--draft-model", "draft_model_unverified")):
            with self.subTest(flag=flag):
                self.session.server = {**self.server, "command": self.server["command"] + f" {flag} /model"}
                info = (await ModelIdentity.capture(self.config, self.session)).info
                self.assertEqual(info["status"], "unavailable")
                self.assertEqual(info["reason"], reason)
                self.assertIsNone(info["id"])

    async def test_extra_loader_shard_is_hashed_but_unrelated_tensor_is_not(self):
        (self.snapshot / "model-extra.safetensors").write_bytes(b"extra weights")
        (self.snapshot / "adapters.safetensors").write_bytes(b"unused adapter")
        info = (await ModelIdentity.capture(self.config, self.session)).info
        self.assertEqual({w["file"] for w in info["weights"]}, {
            "model-1.safetensors", "model-2.safetensors", "model-extra.safetensors"})

    async def test_unresolved_revision_or_malformed_local_metadata_is_unavailable(self):
        self.ref.unlink()
        identity = await ModelIdentity.capture(self.config, self.session)
        self.assertEqual(identity.info["reason"], "snapshot_unavailable")
        self.ref.write_text(self.revision)
        (self.snapshot / "model.safetensors.index.json").write_text('{"weight_map": []}')
        identity = await ModelIdentity.capture(self.config, self.session)
        self.assertEqual(identity.info["reason"], "invalid_weight_index")

    async def test_mock_and_remote_never_contact_local_manager(self):
        mock = await ModelIdentity.capture({**self.config, "mock_mode": True}, self.session)
        remote = await ModelIdentity.capture({**self.config, "base_url": "https://example.com/v1"}, self.session)
        self.assertEqual(mock.info["status"], "mock")
        self.assertEqual(remote.info["status"], "unavailable")
        self.assertEqual(self.session.requests, [])

    async def test_different_requested_model_is_not_mislabeled(self):
        identity = await ModelIdentity.capture({**self.config, "model": "example/another"}, self.session)
        self.assertEqual(identity.info["reason"], "request_differs_from_launch_model")
        self.assertIsNone(identity.info["id"])

    async def test_incomplete_snapshot_is_not_recorded(self):
        (self.snapshot / "model-2.safetensors").unlink()
        identity = await ModelIdentity.capture(self.config, self.session)
        self.assertEqual(identity.info["reason"], "weights_unavailable")

    async def test_unavailable_manager_and_malformed_payload_do_not_leak_or_crash(self):
        with patch.object(self.session, "get", side_effect=OSError("private-manager-token")):
            identity = await ModelIdentity.capture(self.config, self.session)
        self.assertEqual(identity.info["reason"], "OSError")
        self.assertNotIn("private-manager-token", json.dumps(identity.info))
        with patch.object(self.session, "get", return_value=ManagerResponse(["malformed"])):
            identity = await ModelIdentity.capture(self.config, self.session)
        self.assertEqual(identity.info["reason"], "server_unavailable")


class RecordTests(unittest.IsolatedAsyncioTestCase):
    def test_date_uses_japan_midnight_and_saved_instant(self):
        self.assertEqual(experiment_date("2026-10-09T14:59:59+00:00"), "2026-10-09")
        self.assertEqual(experiment_date("2026-10-09T15:00:00+00:00"), "2026-10-10")
        self.assertIsNone(experiment_date(None))
        self.assertIsNone(experiment_date("2026-10-09T15:00:00"))

    async def test_metadata_survives_manifest_export_and_aggregate(self):
        info = {"id": "example/tiny", "revision": "b" * 40, "status": "recorded",
                "weights": [{"file": "model.safetensors", "sha256": "c" * 64}],
                "quantization": {"bits": 6}}
        identity = ModelIdentity(info)
        with tempfile.TemporaryDirectory() as directory, patch(
                "main.ModelIdentity.capture", new=AsyncMock(return_value=identity)), patch(
                "run_data.utc_now", return_value="2026-10-09T15:00:00+00:00"):
            run = await main(params={"output_dir": directory, "mock_mode": True, "num_agents": 1, "num_steps": 1})
            path = Path(run["output_dir"])
            manifest = json.loads((path / "manifest.json").read_text())
            self.assertEqual(manifest["execution_date"], "2026-10-10")
            self.assertEqual(manifest["timezone"], "Asia/Tokyo")
            self.assertEqual(manifest["model"], info)
            self.assertEqual(export_run(path)["model"], info)
            self.assertNotIn("response_model", (path / "events.csv").read_text().splitlines()[0])
            self.assertNotIn("response_model", json.dumps(run["logs"]))
            destination, _ = collect_runs(directory)
            with destination.open() as source:
                row = next(csv.DictReader(source))
            self.assertEqual(row["model"], "example/tiny")
            self.assertEqual(row["execution_date"], "2026-10-10")
            self.assertEqual(row["model_revision"], "b" * 40)
            self.assertEqual(json.loads(row["model_weights_sha256"]), {"model.safetensors": "c" * 64})
            self.assertNotIn("response_models", row)

    async def test_old_schema_keeps_original_metadata_and_response_column(self):
        with tempfile.TemporaryDirectory() as directory:
            run = await main(params={"output_dir": directory, "mock_mode": True, "num_steps": 1})
            path = Path(run["output_dir"])
            manifest = json.loads((path / "manifest.json").read_text())
            manifest.update(schema_version=1, started_at="2025-01-01T18:00:00+00:00")
            for field in ("model", "execution_date", "timezone"):
                manifest.pop(field)
            (path / "manifest.json").write_text(json.dumps(manifest))
            lines = []
            for raw in (path / "steps.jsonl").read_text().splitlines():
                row = json.loads(raw)
                row["schema_version"] = 1
                for event in row["events"]:
                    event["response_model"] = "old-alias"
                lines.append(json.dumps(row))
            (path / "steps.jsonl").write_text("\n".join(lines) + "\n")
            before = (path / "manifest.json").read_bytes()
            exported = export_run(path)
            self.assertEqual(exported["execution_date"], "2025-01-02")
            self.assertEqual(exported["model"]["status"], "legacy_unrecorded")
            self.assertIn("response_model", (path / "events.csv").read_text().splitlines()[0])
            destination, _ = collect_runs(directory)
            with destination.open() as source:
                row = next(csv.DictReader(source))
            self.assertEqual(row["model"], "")
            self.assertEqual(row["model_status"], "legacy_unrecorded")
            self.assertEqual((path / "manifest.json").read_bytes(), before)

    async def test_changed_identity_never_reports_successful_comparison(self):
        identity = ModelIdentity({"id": "example/tiny", "status": "recorded"})
        with tempfile.TemporaryDirectory() as directory, patch(
                "main.ModelIdentity.capture", new=AsyncMock(return_value=identity)), patch.object(
                identity, "finish", new=AsyncMock(return_value={"id": "example/tiny", "status": "changed_during_run"})):
            run = await main(params={"output_dir": directory, "mock_mode": True, "num_steps": 1})
        self.assertEqual(run["status"], "completed_with_errors")
        self.assertEqual(run["model"]["status"], "changed_during_run")


if __name__ == "__main__":
    unittest.main()
