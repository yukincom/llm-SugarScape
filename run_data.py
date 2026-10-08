"""Versioned run journal and tabular exports, independent of the UI/LLM."""

import csv
import hashlib
import importlib.metadata
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

SCHEMA_VERSION = 1
ENGINE_VERSION = "2.0"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


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
    for filename in ("main.py", "run_data.py", "requirements.txt"):
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

    def __init__(self, output_dir, config, run_number=0):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.run_id = f"{stamp}_{run_number}_{uuid4().hex[:8]}"
        self.directory = Path(output_dir).resolve() / self.run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.manifest = {
            "schema_version": SCHEMA_VERSION, "engine_version": ENGINE_VERSION,
            "run_id": self.run_id, "status": "running", "started_at": utc_now(),
            "completed_steps": 0,
            "config": {k: v for k, v in config.items() if k != "api_key"},
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

    def finish(self, status, reason, error=None):
        self.manifest.update(status=status, termination_reason=reason, finished_at=utc_now())
        if error:
            self.manifest["error"] = error
        write_json(self.directory / "manifest.json", self.manifest)
        return export_run(self.directory)


STEP_FIELDS = ["run_id", "step", "alive", "total_born", "total_died", "total_energy",
               "avg_energy", "avg_age", "energy_sources", "total_actions", "valid_decisions",
               "llm_errors", "parse_errors", "rejected_actions", "attacks", "shares",
               "reproductions", "coop_rate", "attack_rate", "repro_rate"]
STEP_DELTA_FIELDS = ["alive_start", "births_this_step", "deaths_this_step", "decisions_this_step",
                     "shares_this_step", "attacks_this_step", "reproductions_this_step",
                     "llm_errors_this_step", "parse_errors_this_step", "rejected_actions_this_step"]
AGENT_FIELDS = ["run_id", "step", "id", "x", "y", "energy", "age", "alive", "mbti_type",
                "parent", "born_step", "death_step", "death_cause", "action"]
EVENT_FIELDS = ["run_id", "step", "agent_id", "decision_source", "decision_status",
                "requested_action", "kind", "dx", "dy", "amount", "executed_action", "action_status", "reason", "error_kind",
                "http_status", "response_model", "finish_reason", "latency_ms", "prompt_tokens",
                "completion_tokens", "energy_before", "energy_after", "energy_collected",
                "energy_transferred", "energy_cost", "target_id", "child_id",
                "x_before", "y_before", "x_after", "y_after", "message", "thought"]


def export_run(directory):
    """Regenerate CSV and run.json from a journal (also useful after interruption)."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
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
        if (snapshot.get("schema_version") != SCHEMA_VERSION or snapshot.get("run_id") != manifest["run_id"]
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
                                  ("rejected_actions", "rejected_actions")):
            step_row[f"{column}_this_step"] = deltas.get(statistic, 0)
        steps.append(step_row)
        for agent in snapshot["agents"]:
            agents.append({**identity, **agent, "x": agent["position"][0], "y": agent["position"][1]})
        for event in snapshot["events"]:
            events.append({**identity, **event,
                           "x_before": event["position_before"][0], "y_before": event["position_before"][1],
                           "x_after": event["position_after"][0], "y_after": event["position_after"][1]})
    write_csv(directory / "steps.csv", steps, [*STEP_FIELDS, *STEP_DELTA_FIELDS])
    write_csv(directory / "agents.csv", agents, AGENT_FIELDS)
    write_csv(directory / "events.csv", events, EVENT_FIELDS)
    data = {**manifest, "summary": snapshots[-1]["summary"] if snapshots else {},
            "completed_steps": snapshots[-1]["step"] if snapshots else 0,
            "logs": snapshots, "output_dir": str(directory.resolve()),
            "recovered_truncated_tail": truncated_tail}
    write_json(directory / "run.json", data)
    return data


def collect_runs(root, output=None):
    """One row per run; statuses remain explicit so failed runs can be excluded."""
    root = Path(root)
    rows = []
    for path in sorted(root.glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema: {path}")
        data = export_run(path.parent)
        config = data["config"]
        models = sorted({event["response_model"] for snap in data["logs"] for event in snap["events"]
                         if event.get("response_model")})
        rows.append({"run_id": data["run_id"], "status": data["status"],
                     "engine_version": data["engine_version"], "schema_version": data["schema_version"],
                     "termination_reason": data.get("termination_reason", ""),
                     "seed": config["seed"], "mode": "mock" if config["mock_mode"] else "llm",
                     "model": config["model"], "response_models": ";".join(models),
                     "base_url": config["base_url"], "use_mbti": config["use_mbti"],
                     "initial_agents": config["num_agents"], "requested_steps": config["num_steps"],
                     "source_sha256": json.dumps(data["provenance"]["source_sha256"], sort_keys=True),
                     "config_json": json.dumps(config, sort_keys=True, ensure_ascii=False),
                     **data["summary"]})
    fields = ["run_id", "status", "engine_version", "schema_version", "termination_reason",
              "seed", "mode", "model", "response_models", "base_url", "use_mbti", "initial_agents",
              "requested_steps", "source_sha256", "config_json", *STEP_FIELDS[1:]]
    destination = Path(output) if output else root / "runs.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_csv(destination, rows, fields)
    return destination, len(rows)
