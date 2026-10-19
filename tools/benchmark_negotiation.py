"""Run the existing fog preset against the two prepared local runtimes, sequentially.

No simulation or prompt replacement: main.main owns decisions and RunRecorder.
The existing model manager owns switching; its shared lock protects each arm.
"""

import argparse
import asyncio
from contextlib import asynccontextmanager, redirect_stdout
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".mplconfig"))
import main as engine
from app_presets import BUILTIN_PRESETS, apply_parameters
from run_data import provenance, utc_now, write_json

SETUP = Path("/Users/yukin_co/Documents/ChatGPT/Hermes改造/moe-on-a-desk-local")
SEEDS = (42, 43, 44)
ARMS = ("125b", "gemma")
ORIGINAL_REQUEST = engine.chat_completion_request


def command(args, required=True, timeout=30):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if required and result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr or result.stdout}")
    return result.stdout.strip()


def server(*args):
    value = command([sys.executable, "-B", str(SETUP / "server.py"), *args], timeout=150)
    return json.loads(value) if value.startswith("{") else value


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def process_identity(pid):
    return command(["ps", "-ww", "-p", str(pid), "-o", "lstart=,command="], required=False)


def environment():
    java = command(["pgrep", "-x", "java"], required=False).split()
    minecraft = [pid for pid in java if any(token in command(
        ["ps", "-ww", "-p", pid, "-o", "command="], required=False)
        for token in ("net.minecraft.client", "net.fabricmc.loader.impl.launch.knot.KnotClient"))]
    return {"at": utc_now(), "minecraft_pids": minecraft,
            "dogido_listener": command(["lsof", "-nP", "-iTCP:5055", "-sTCP:LISTEN"], required=False),
            "download_process": command(["pgrep", "-fl", "download_models.py"], required=False),
            "pressure_level": int(command(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"])),
            "swap": command(["sysctl", "vm.swapusage"]), "vm_stat": command(["vm_stat"])}


def check_environment(state):
    assert not state["minecraft_pids"], "Minecraft is active"
    assert not state["dogido_listener"], "Dogido is active"
    assert not state["download_process"], "Model download is active"
    assert state["pressure_level"] < 4, "Critical memory pressure"


def parameters(seed, output):
    preset = next(p for p in BUILTIN_PRESETS if p["id"] == "builtin:negotiation")
    return {**engine.DEFAULT_PARAMS, **apply_parameters(preset, engine.DEFAULT_PARAMS),
            "seed": seed, "output_dir": str(output), "api_key": "", "mock_mode": False,
            "reasoning_mode": "off", "reasoning_format": "chat_template"}


class WireRecorder:
    """Observe the exact payload built by llm_api without adding an endpoint."""

    def __init__(self, path):
        self.path, self.phase, self.seed, self.count = Path(path), "warmup", None, 0

    def request(self, session, **options):
        recorder = self

        class SessionProxy:
            @staticmethod
            @asynccontextmanager
            async def post(url, **kwargs):
                recorder.count += 1
                record = {"sequence": recorder.count, "phase": recorder.phase,
                          "seed": recorder.seed, "started_at": utc_now(),
                          "url": url, "request": kwargs["json"]}
                started = time.perf_counter()
                try:
                    async with session.post(url, **kwargs) as response:
                        body = await response.text()
                        record.update(http_status=response.status, response_body=body,
                                      response_seconds=time.perf_counter() - started)
                        yield response
                except BaseException as error:
                    record["exception_type"] = type(error).__name__
                    raise
                finally:
                    record["total_seconds"] = time.perf_counter() - started
                    with recorder.path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

        return ORIGINAL_REQUEST(SessionProxy(), **options)


def verify_sources(manifest):
    for name, digest in manifest["provenance"]["source_sha256"].items():
        assert sha(ROOT / name) == digest, f"Source changed: {name}"
    assert sha(__file__) == manifest["runner_sha256"], "Benchmark runner changed"


def runtime_identity(arm, record):
    state = server("status")
    assert state["running"] and state["pid"] == record["pid"], "8080 identity changed"
    assert process_identity(record["pid"]) == record["identity"], "Process identity changed"
    if arm == "125b":
        assert state["managed_125b"], "Unexpected llama runtime"
        assert "build-12a/bin/llama-server" in state["command"]
    else:
        assert state["trusted"] and "lmstudio-community/gemma-4-26B-A4B-it-QAT-MLX-4bit" in state["active_model"]
        template = template_arguments(state["command"])
        assert template.get("enable_thinking") is False, "Thinking is not disabled"
    return {"server": state, "process_identity": record["identity"],
            "cwd": command(["lsof", "-a", "-p", str(record["pid"]), "-d", "cwd", "-Fn"])}


def template_arguments(command_line):
    # ps prints the JSON argument without shell quoting; shlex would remove the
    # JSON's double quotes and turn a valid launch option into invalid JSON.
    match = re.search(r"--chat-template-args\s+(\{[^\n]+?\})(?=\s|$)", command_line)
    if not match:
        raise ValueError("Cannot verify template arguments in process command")
    return json.loads(match[1])


def wait_ready(record):
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        assert process_identity(record["pid"]) == record["identity"], "Model exited while loading"
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/v1/models", timeout=3) as response:
                models = json.load(response)
            if models.get("data"):
                return models
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(2)
    raise RuntimeError("Model did not become ready within 300 seconds")


async def measure_arm(arm, output, manifest, record):
    wire = WireRecorder(output / "wire.jsonl")
    engine.chat_completion_request = wire.request
    try:
        config = parameters(SEEDS[0], output / "runs")
        started = time.perf_counter()
        warmup = await engine.check_connection(config)
        write_json(output / "warmup.json", {"event": warmup, "seconds": time.perf_counter() - started,
                                           "excluded_from_results": True})
        assert warmup["decision_status"] == "ok", "Warmup failed; inspect before more requests"
        rows = []
        for seed in SEEDS:
            verify_sources(manifest)
            runtime_identity(arm, record)
            before = environment()
            check_environment(before)
            wire.phase, wire.seed = "measurement", seed
            failed_request = False
            samples = []

            def decision(step, event):
                nonlocal failed_request
                if event.get("error_kind") in ("http_error", "transport_error", "protocol_error"):
                    failed_request = True

            def snapshot(value):
                state = environment()
                samples.append({"step": value["step"], **state})
                check_environment(state)
                runtime_identity(arm, record)
                print(json.dumps({"arm": arm, "seed": seed, "step": value["step"],
                                  "alive": value["summary"]["alive"],
                                  "attacks": value["summary"]["attacks"],
                                  "shares": value["summary"]["shares"]}), file=sys.__stdout__, flush=True)

            started = time.perf_counter()
            with (output / f"seed-{seed}.log").open("w") as log, redirect_stdout(log):
                result = await engine.main(seed, parameters(seed, output / "runs"), on_decision=decision,
                                           on_snapshot=snapshot, stop_requested=lambda: failed_request)
            row = {"arm": arm, "seed": seed, "wall_seconds": time.perf_counter() - started,
                   "run_dir": str(Path(result["output_dir"]).relative_to(output)),
                   "status": result["status"], "summary": result["summary"]}
            rows.append(row)
            write_json(output / "results.json", rows)
            write_json(output / f"environment-{seed}.json", {"before": before, "samples": samples,
                                                           "after": environment()})
            if result["status"] != "completed":
                raise RuntimeError(f"Run ended with {result['status']}; inspect before continuing")
        return rows
    finally:
        engine.chat_completion_request = ORIGINAL_REQUEST


def run(output):
    assert not output.exists(), "Refuse to overwrite an experiment"
    state, env = server("status"), environment()
    assert not state["running"], "8080 is no longer stopped; inspect before switching"
    check_environment(env)
    build = json.loads((SETUP / "evidence/update-12a/build-manifest.json").read_text())
    binary = SETUP / "runtime/llama.cpp/build-12a/bin/llama-server"
    assert sha(binary) == build["binaries"]["llama-server"] and build["patch_count"] == 51
    assert command(["git", "-C", str(SETUP / "runtime/llama.cpp"), "rev-parse", "HEAD"]) == build["runtime_commit"]
    output.mkdir(parents=True)
    manifest = {"started_at": utc_now(), "preset": "builtin:negotiation", "arms": ARMS, "seeds": SEEDS,
                "parameters": parameters(42, "ARM/runs"), "provenance": provenance(),
                "runner_sha256": sha(__file__), "initial_server": state, "initial_environment": env,
                "build": build, "warmup": "One existing check_connection call per model, excluded",
                "seed_policy": "World RNG only; no inference seed sent; temperature=0 and top_p=1",
                "timing_policy": "Request latency excludes model loading and model-identity hashing; run wall includes hashing and environment checks",
                "cache_policy": "Fresh process per arm, no per-seed cache clearing; runtime cache policies differ",
                "identity_policy": "125b externally verified by managed PID/start/cwd/argv/build; builtin MLX identity unavailable for llama.cpp",
                "weight_policy": "125b previous full SHA verification plus current signatures; Gemma full SHA recorded by each run",
                "switch_coordination": "Existing model setup switch.lock shared during each arm",
                "restore_policy": "Initially stopped; stop only the process started by this runner"}
    sources = output / "frozen-source"
    sources.mkdir()
    for name in manifest["provenance"]["source_sha256"]:
        path = sources / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, path)
    shutil.copy2(__file__, output / Path(__file__).name)
    for source in ("models-manifest.json", "evidence/download-verified.json", "evidence/update-12a/build-manifest.json"):
        shutil.copy2(SETUP / source, output / Path(source).name)
    weights = json.loads((SETUP / "evidence/download-verified.json").read_text())
    for item in weights:
        stat = Path(item["path"]).stat()
        assert stat.st_size == item["bytes"] and item["verified_sha256"] == item["sha256"]
        item["current_signature"] = [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    manifest["weights"] = weights
    write_json(output / "manifest.json", manifest)
    measure_models(output, manifest, ARMS, [])


def measure_models(output, manifest, arms, all_rows):
    for arm in arms:
        arm_dir = output / arm
        arm_dir.mkdir(exist_ok=True)
        assert not (arm_dir / "wire.jsonl").exists(), "Do not overwrite measured requests"
        record = None
        model_log = SETUP / "logs/llama-server.log"
        log_offset = model_log.stat().st_size
        started = time.perf_counter()
        try:
            assert not server("status")["running"], "8080 was started by another process"
            server("switch", arm)
            record = json.loads((SETUP / "evidence/managed-server.json").read_text())
            api_models = wait_ready(record)
            write_json(arm_dir / "runtime.json", {**runtime_identity(arm, record), "api_models": api_models,
                                                  "load_seconds": time.perf_counter() - started})
            print(json.dumps({"arm": arm, "event": "ready", "pid": record["pid"]}), flush=True)
            with (SETUP / "evidence/switch.lock").open("r") as lock:
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
                all_rows.extend(asyncio.run(measure_arm(arm, arm_dir, manifest, record)))
                verify_sources(manifest)
                runtime_identity(arm, record)
        finally:
            if arm == "125b":
                with model_log.open("rb") as handle:
                    handle.seek(log_offset)
                    (arm_dir / "model-activity.log").write_bytes(handle.read())
            if record is not None:
                state = server("status")
                live = process_identity(record["pid"])
                if state["running"]:
                    assert state["pid"] == record["pid"] and live == record["identity"], "Identity changed; leave other process untouched"
                if live:
                    assert live == record["identity"], "PID reused; leave other process untouched"
                    server("stop")
                state = server("status")
                assert not state["running"] and not process_identity(record["pid"]), "Model did not stop"
                write_json(arm_dir / "after-stop.json", {"at": utc_now(), "server": state, "environment": environment()})
                print(json.dumps({"arm": arm, "event": "stopped"}), flush=True)
    write_json(output / "results.json", all_rows)
    write_json(output / "completion.json", {"completed_at": utc_now(), "runs": len(all_rows),
                                            "server": server("status"), "environment": environment()})


def resume_gemma(output):
    """Continue only the documented failure before Gemma's first request."""
    assert not (output / "completion.json").exists(), "Experiment already completed"
    assert not (output / "continuation.json").exists(), "Continuation already attempted"
    assert not (output / "gemma/wire.jsonl").exists(), "Gemma has already sent requests"
    state = server("status")
    assert not state["running"], "8080 must still be stopped"
    check_environment(environment())
    manifest = json.loads((output / "manifest.json").read_text())
    assert sha(output / "benchmark_negotiation.py") == manifest["runner_sha256"]
    rows = json.loads((output / "125b/results.json").read_text())
    assert [row["seed"] for row in rows] == list(SEEDS)
    assert all(row["status"] == "completed" for row in rows)
    for row in rows:
        saved = json.loads((output / "125b" / row["run_dir"] / "run.json").read_text())
        assert saved["status"] == "completed" and saved["summary"] == row["summary"]
    manifest = {**manifest, "runner_sha256": sha(__file__)}
    verify_sources(manifest)
    shutil.copy2(__file__, output / "benchmark_negotiation-continuation.py")
    shutil.copy2(output / "gemma/after-stop.json", output / "gemma/premeasurement-failure-after-stop.json")
    write_json(output / "continuation.json", {"at": utc_now(), "runner_sha256": sha(__file__),
               "reason": "Gemma process command JSON was incorrectly shell-parsed; failed before warmup or measurement",
               "change_scope": "Process metadata verification and continuation only; application source, prompts and generation controls unchanged",
               "preserved_runs": rows, "server": state})
    measure_models(output, manifest, ("gemma",), rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resume-gemma", action="store_true")
    args = parser.parse_args()
    (resume_gemma if args.resume_gemma else run)(args.output.resolve())
