"""Versioned run journal and tabular exports, independent of the UI/LLM."""

import csv
import ctypes
import errno
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo
from paper_prompts import prompt_protocol
from response_fields import ACTION_REPAIR_POLICY
from observations import OBSERVATION_PROTOCOL

SCHEMA_VERSION = 7
SUPPORTED_SCHEMA_VERSIONS = (1, 2, 3, 4, 5, 6, 7)
ENGINE_VERSION = "5.3"
EXPERIMENT_TIMEZONE = "Asia/Tokyo"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def experiment_date(started_at):
    """Use the recorded start instant, never today's date when exporting old runs."""
    if not started_at:
        return None
    instant = datetime.fromisoformat(started_at)
    if instant.tzinfo is None:
        return None
    return instant.astimezone(ZoneInfo(EXPERIMENT_TIMEZONE)).date().isoformat()


def run_folder_name(started_at, config, model_info=None):
    stamp = datetime.fromisoformat(started_at).astimezone(ZoneInfo(EXPERIMENT_TIMEZONE)).strftime("%Y-%m-%d_%H-%M-%S")
    model = "Mock" if config["mock_mode"] else (model_info or {}).get("id") or config["model"]
    label = re.sub(r"[^\w.-]+", "_", model.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1])
    label = label.strip("._-")[:80] or "LLM"
    return f"{stamp}_{label}"


def locate_run_directory(data):
    """Keep an open UI result usable after its completed folder is renamed."""
    directory = Path(data["output_dir"]).resolve()
    for path in (directory / "manifest.json", directory / "run.json", *directory.parent.glob("*/manifest.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(manifest, dict) and manifest.get("run_id") == data["run_id"]:
                return path.parent
        except (OSError, ValueError):
            continue
    if directory.exists():
        raise ValueError("The saved directory no longer belongs to this run")
    return directory


def read_run(path):
    """Load an existing export without rewriting it or trusting its saved path."""
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        if data["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError("Unsupported schema")
        if not isinstance(data["run_id"], str) or not data["run_id"]:
            raise ValueError("Missing run ID")
        grid = data["config"]["grid_size"]
        cost = data["config"]["reproduce_cost"]
        if type(grid) is not int or not 1 <= grid <= 1000 or type(cost) is not int or cost <= 0:
            raise ValueError("Invalid grid or reproduction cost")
        if not isinstance(data["status"], str) or not isinstance(data["summary"], dict):
            raise ValueError("Invalid result")
        if not isinstance(data["logs"], list) or not data["logs"]:
            raise ValueError("No completed snapshots")
        if "model" in data and not isinstance(data["model"], dict):
            raise ValueError("Invalid model information")
        for index, snapshot in enumerate(data["logs"]):
            if snapshot["step"] != index or snapshot.get("run_id", data["run_id"]) != data["run_id"]:
                raise ValueError("Inconsistent snapshots")
            if type(snapshot["summary"]["step"]) is not int or snapshot["summary"]["step"] != index:
                raise ValueError("Inconsistent summary step")
            for key in ("alive", "total_born", "total_died"):
                if type(snapshot["summary"][key]) is not int or snapshot["summary"][key] < 0:
                    raise ValueError("Invalid population")
            if not isinstance(snapshot["agents"], list) or not isinstance(snapshot["events"], list):
                raise ValueError("Invalid agents or events")
            for agent in snapshot["agents"]:
                if (type(agent["id"]) is not int or type(agent["alive"]) is not bool
                        or type(agent["energy"]) is not int or len(agent["position"]) != 2
                        or any(type(value) is not int or not 0 <= value < grid for value in agent["position"])):
                    raise ValueError("Invalid agent")
            for resource in snapshot["environment"].get("resources", []):
                if any(type(resource[axis]) is not int or not 0 <= resource[axis] < grid for axis in ("x", "y")):
                    raise ValueError("Invalid resource")
            for event in snapshot["events"]:
                if type(event["agent_id"]) is not int or not isinstance(event["decision_status"], str):
                    raise ValueError("Invalid event")
                for key in ("energy_before", "energy_after"):
                    if type(event[key]) is not int:
                        raise ValueError("Invalid event energy")
        # A moved/downloaded run always belongs to its actual directory. Never
        # follow output_dir embedded in a JSON file to read sibling downloads.
        data["output_dir"] = str(path.parent)
        data.setdefault("model", {"id": None, "status": "legacy_unrecorded"})
        data.setdefault("execution_date", experiment_date(data.get("started_at")))
        return data
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("保存データの必須項目が不足しているか、形式が異なります。") from error


def saved_runs(root):
    """List exports beneath the chosen output folder, including older subfolders."""
    root = Path(root).expanduser().resolve()
    found = {}
    if root.is_dir():
        for path in root.rglob("run.json"):
            resolved = path.resolve()
            if resolved.is_relative_to(root):
                relative = path.relative_to(root).parent
                found[resolved] = relative.as_posix() if relative.parts else root.name
    return sorted(found.items(), key=lambda item: item[1], reverse=True)


def _rename_directory_exclusive(source, destination):
    """Ask the OS to reject an existing target, including a competing rename."""
    if sys.platform == "win32":
        os.rename(source, destination)  # Windows rename already rejects existing targets.
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        arguments = (os.fsencode(source), os.fsencode(destination), 0x4)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        arguments = (-100, os.fsencode(source), -100, os.fsencode(destination), 1)  # AT_FDCWD, RENAME_NOREPLACE
    else:
        raise OSError(errno.ENOTSUP, "Exclusive directory rename is unavailable")
    rename.restype = ctypes.c_int
    if rename(*arguments) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def rename_run(path, name):
    """Rename a completed export's folder, preserving every recorded byte."""
    name = name.strip()
    if not name or name in (".", "..") or any(character in name for character in ("/", "\\", ":", "\0")):
        raise ValueError("実験名には空欄・スラッシュ・コロンを使えません。")
    path = Path(path).resolve()
    result = read_run(path)
    manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("run_id") != result["run_id"]:
        raise ValueError("実験の記録が一致しないため、名前を変更できません。")
    if manifest.get("status") == "running":
        raise ValueError("実験中は名前を変更できません。")
    destination = path.parent.with_name(name)
    if destination == path.parent:
        return path
    if destination.exists() or destination.is_symlink():
        raise ValueError("同じ名前のフォルダがあります。別の名前を入力してください。")
    # Coordinate with the existing translation lock used by other app windows.
    import fcntl
    with (path.parent / ".translations.ja.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("翻訳中は名前を変更できません。翻訳が終わってから変更してください。") from error
        try:
            _rename_directory_exclusive(path.parent, destination)
        except FileExistsError as error:
            raise ValueError("同じ名前のフォルダがあります。別の名前を入力してください。") from error
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return destination / path.name


def write_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def write_csv(path, rows, fields):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def provenance():
    root = Path(__file__).resolve().parent
    info = {"python": platform.python_version(), "source_sha256": {}, "packages": {}}
    for filename in ("main.py", "run_data.py", "model_identity.py", "grid_view.py", "app_ui.py", "app_presets.py",
                     "paper_prompts.py", "observations.py", "agent_view.py", "llm_api.py", "translations.py", "response_fields.py", "experiment_task.py",
                     "assets/emoji/sources.json", "requirements.txt"):
        info["source_sha256"][filename] = hashlib.sha256((root / filename).read_bytes()).hexdigest()
    for package in ("aiohttp", "numpy", "matplotlib", "pandas", "streamlit"):
        try:
            info["packages"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            info["packages"][package] = None
    try:
        info["git_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
        info["git_dirty"] = bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip())
    except (OSError, subprocess.CalledProcessError):
        info["git_commit"] = None
    return info


class RunRecorder:
    """Append a complete snapshot per step; finalize from that journal."""

    def __init__(self, output_dir, config, run_number=0, model_info=None):
        started_at = utc_now()
        stamp = datetime.fromisoformat(started_at).strftime("%Y%m%dT%H%M%S%fZ")
        self.run_id = f"{stamp}_{run_number}_{uuid4().hex[:8]}"
        root = Path(output_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        name = run_folder_name(started_at, config, model_info)
        sequence = 1
        while True:
            self.directory = root / (name if sequence == 1 else f"{name}_{sequence:02d}")
            try:
                self.directory.mkdir()
                break
            except FileExistsError:
                sequence += 1
        self.manifest = {
            "schema_version": SCHEMA_VERSION, "engine_version": ENGINE_VERSION,
            "run_id": self.run_id, "status": "running", "started_at": started_at,
            "execution_date": experiment_date(started_at), "timezone": EXPERIMENT_TIMEZONE,
            "model": model_info or {"id": None, "status": "unavailable"},
            "completed_steps": 0,
            "config": {k: v for k, v in config.items() if k != "api_key"},
            "protocol": {**prompt_protocol(config.get("prompt_factors", ())), "response_handling": ACTION_REPAIR_POLICY,
                         "observation_audit": OBSERVATION_PROTOCOL},
            "provenance": provenance(),
        }
        write_json(self.directory / "manifest.json", self.manifest)
        (self.directory / "steps.jsonl").touch()

    def record(self, snapshot):
        row = {"schema_version": SCHEMA_VERSION, "run_id": self.run_id, **snapshot}
        with (self.directory / "steps.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            handle.flush()
        self.manifest["completed_steps"] = snapshot["step"]
        write_json(self.directory / "manifest.json", self.manifest)

    def finish(self, status, reason, error=None, model_info=None):
        self.manifest.update(status=status, termination_reason=reason, finished_at=utc_now())
        if model_info is not None:
            self.manifest["model"] = model_info
        if error:
            self.manifest["error"] = error
        write_json(self.directory / "manifest.json", self.manifest)
        return export_run(self.directory)


V3_STEP_FIELDS = ["run_id", "step", "alive", "total_born", "total_died", "total_energy",
               "avg_energy", "avg_age", "energy_sources", "total_actions", "valid_decisions",
               "llm_errors", "parse_errors", "rejected_actions", "attacks", "shares",
               "reproductions", "coop_rate", "attack_rate", "repro_rate"]
STEP_FIELDS = [*V3_STEP_FIELDS, "repaired_decisions"]
V3_STEP_DELTA_FIELDS = ["alive_start", "births_this_step", "deaths_this_step", "decisions_this_step",
                     "shares_this_step", "attacks_this_step", "reproductions_this_step",
                     "llm_errors_this_step", "parse_errors_this_step", "rejected_actions_this_step"]
STEP_DELTA_FIELDS = [*V3_STEP_DELTA_FIELDS, "repaired_decisions_this_step"]
LEGACY_AGENT_FIELDS = ["run_id", "step", "id", "x", "y", "energy", "age", "alive", "mbti_type",
                "parent", "born_step", "death_step", "death_cause", "action"]
AGENT_FIELDS = [*LEGACY_AGENT_FIELDS, "summary", "thoughts", "message", "memory", "shared_energy", "attacked_by"]
V2_EVENT_FIELDS = ["run_id", "step", "agent_id", "decision_source", "decision_status",
                "requested_action", "kind", "dx", "dy", "amount", "executed_action", "action_status", "reason", "error_kind",
                "http_status", "finish_reason", "latency_ms", "prompt_tokens",
                "completion_tokens", "energy_before", "energy_after", "energy_collected",
                "energy_transferred", "energy_cost", "target_id", "child_id",
                "x_before", "y_before", "x_after", "y_after", "message", "thought"]
V3_EVENT_FIELDS = [*V2_EVENT_FIELDS, "summary", "memory", "requested_share", "requested_attack",
                "executed_share", "executed_attack", "next_action_status", "share_status", "attack_status",
                "message_status", "message_cost", "shared_amount", "stolen_amount", "message_recipient_ids"]
V4_EVENT_FIELDS = [*V3_EVENT_FIELDS, "normalized_action", "response_repairs"]
V5_EVENT_FIELDS = [*V4_EVENT_FIELDS, "turn_energy_before", "turn_energy_after", "turn_energy_cost", "total_energy_cost"]
V6_EVENT_FIELDS = [*V5_EVENT_FIELDS, "observation_id", "prompt_sha256", "observation", "execution_check", "outcome"]
EVENT_FIELDS = [*V6_EVENT_FIELDS, "decision_attempts", "retry_count", "llm_request_count", "retry_status", "retry_destinations"]
LEGACY_EVENT_FIELDS = V2_EVENT_FIELDS.copy()
LEGACY_EVENT_FIELDS.insert(LEGACY_EVENT_FIELDS.index("finish_reason"), "response_model")


def export_run(directory):
    """Regenerate CSV and run.json from a journal (also useful after interruption)."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(f"Unsupported schema: {directory}")
    snapshots = []
    lines = (directory / "steps.jsonl").read_text(encoding="utf-8").splitlines()
    truncated_tail = False
    for index, line in enumerate(lines):
        try:
            snapshots.append(json.loads(line))
        except json.JSONDecodeError:
            # Only a final incomplete write can be recovered; middle corruption is an error.
            if index != len(lines) - 1 or manifest["status"] not in ("running", "interrupted", "failed"):
                raise
            truncated_tail = True
    steps, agents, events = [], [], []
    for index, snapshot in enumerate(snapshots):
        if (snapshot.get("schema_version") != manifest["schema_version"] or snapshot.get("run_id") != manifest["run_id"]
                or snapshot.get("step") != index):
            raise ValueError(f"Inconsistent journal at step {index}: {directory}")
        identity = {"run_id": manifest["run_id"], "step": snapshot["step"]}
        deltas = snapshot.get("step_stats", {})
        step_row = {**identity, **snapshot["summary"],
                    "alive_start": snapshot.get("alive_start", snapshot["summary"]["alive"])}
        for column, statistic in (("births", "total_born"), ("deaths", "total_died"),
                                  ("decisions", "total_actions"), ("shares", "shares"),
                                  ("attacks", "attacks"), ("reproductions", "reproductions"),
                                  ("llm_errors", "llm_errors"), ("parse_errors", "parse_errors"),
                                  ("repaired_decisions", "repaired_decisions"),
                                  ("rejected_actions", "rejected_actions")):
            step_row[f"{column}_this_step"] = deltas.get(statistic, 0)
        steps.append(step_row)
        for agent in snapshot["agents"]:
            row = {**identity, **agent, "x": agent["position"][0], "y": agent["position"][1]}
            for field in ("memory", "shared_energy", "attacked_by"):
                if field in row:
                    row[field] = json.dumps(row[field], ensure_ascii=False)
            agents.append(row)
        for event in snapshot["events"]:
            events.append({**identity, **event,
                           "x_before": event["position_before"][0], "y_before": event["position_before"][1],
                           "x_after": event["position_after"][0], "y_after": event["position_after"][1],
                           "response_repairs": json.dumps(event.get("response_repairs", []), ensure_ascii=False),
                           "message_recipient_ids": json.dumps(event.get("message_recipient_ids", [])),
                           **{key: json.dumps(event.get(key), ensure_ascii=False)
                              for key in ("prompt_sha256", "observation", "execution_check", "outcome",
                                          "decision_attempts", "retry_destinations")}})
    step_fields = [*STEP_FIELDS, *STEP_DELTA_FIELDS] if manifest["schema_version"] >= 4 else [*V3_STEP_FIELDS, *V3_STEP_DELTA_FIELDS]
    write_csv(directory / "steps.csv", steps, step_fields)
    write_csv(directory / "agents.csv", agents, AGENT_FIELDS if manifest["schema_version"] >= 3 else LEGACY_AGENT_FIELDS)
    write_csv(directory / "events.csv", events,
              {1: LEGACY_EVENT_FIELDS, 2: V2_EVENT_FIELDS, 3: V3_EVENT_FIELDS,
               4: V4_EVENT_FIELDS, 5: V5_EVENT_FIELDS, 6: V6_EVENT_FIELDS, 7: EVENT_FIELDS}[manifest["schema_version"]])
    data = {**manifest, "summary": snapshots[-1]["summary"] if snapshots else {},
            "completed_steps": snapshots[-1]["step"] if snapshots else 0,
            "logs": snapshots, "output_dir": str(directory.resolve()),
            "recovered_truncated_tail": truncated_tail}
    data.setdefault("execution_date", experiment_date(manifest.get("started_at")))
    data.setdefault("timezone", EXPERIMENT_TIMEZONE)
    data.setdefault("model", {"id": None, "status": "legacy_unrecorded"})
    write_json(directory / "run.json", data)
    return data


def collect_runs(root, output=None):
    """One row per run; statuses remain explicit so failed runs can be excluded."""
    root = Path(root)
    rows = []
    seen = set()
    for path in sorted(root.glob("*/manifest.json")):
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"Unsupported schema: {path}")
        data = export_run(path.parent)
        config = data["config"]
        model = data["model"]
        weights = model.get("weights", [])
        rows.append({"run_id": data["run_id"], "status": data["status"],
                     "execution_date": data["execution_date"], "timezone": data["timezone"],
                     "started_at": data["started_at"], "finished_at": data.get("finished_at"),
                     "engine_version": data["engine_version"], "schema_version": data["schema_version"],
                     "termination_reason": data.get("termination_reason", ""),
                     "seed": config["seed"], "mode": "mock" if config["mock_mode"] else "llm",
                     "model": model.get("id"), "model_status": model["status"],
                     "model_revision": model.get("revision"),
                     "model_weights_sha256": json.dumps({w["file"]: w["sha256"] for w in weights}, sort_keys=True),
                     "model_quantization": json.dumps(model.get("quantization"), sort_keys=True),
                     "base_url": config["base_url"], "use_mbti": config["use_mbti"],
                     "initial_agents": config["num_agents"], "requested_steps": config["num_steps"],
                     "source_sha256": json.dumps(data["provenance"]["source_sha256"], sort_keys=True),
                     "config_json": json.dumps(config, sort_keys=True, ensure_ascii=False),
                     **data["summary"]})
    fields = ["run_id", "status", "execution_date", "timezone", "started_at", "finished_at",
              "engine_version", "schema_version", "termination_reason",
              "seed", "mode", "model", "model_status", "model_revision", "model_weights_sha256",
              "model_quantization", "base_url", "use_mbti", "initial_agents",
              "requested_steps", "source_sha256", "config_json", *STEP_FIELDS[1:]]
    destination = Path(output) if output else root / "runs.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_csv(destination, rows, fields)
    return destination, len(rows)
