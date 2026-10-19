"""Read model provenance through the existing local MLX manager; never load a model."""

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from urllib.parse import urlsplit

import aiohttp

MANAGER_STATUS_URL = "http://127.0.0.1:8766/api/status"


async def read_server(session):
    # The manager response also contains a UI token and logs. Keep neither.
    async with session.get(MANAGER_STATUS_URL, timeout=aiohttp.ClientTimeout(total=3),
                           allow_redirects=False) as response:
        if response.status != 200:
            raise ValueError("manager_unavailable")
        data = await response.json()
    if not isinstance(data, dict) or not isinstance(data.get("server"), dict):
        raise ValueError("server_unavailable")
    server = data["server"]
    if (data.get("app") != "mlx-server-manager" or not server.get("running")
            or not server.get("trusted") or type(server.get("pid")) is not int
            or server["pid"] <= 0 or not isinstance(server.get("command"), str) or not server["command"]
            or not isinstance(server.get("active_model"), str) or not server["active_model"]):
        raise ValueError("server_unavailable")
    return {key: server[key] for key in ("pid", "command", "active_model")}


def process_started_at(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="],
                            capture_output=True, text=True, check=True, timeout=3,
                            env={**os.environ, "LC_ALL": "C", "TZ": "UTC"})
    return datetime.strptime(result.stdout.strip(), "%a %b %d %H:%M:%S %Y").replace(
        tzinfo=timezone.utc).timestamp()


def cache_root():
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"]).expanduser()
    if os.environ.get("HF_HOME"):
        return Path(os.environ["HF_HOME"]).expanduser() / "hub"
    return Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))).expanduser() / "huggingface/hub"


def resolve_snapshot(reference):
    path = Path(reference).expanduser()
    watched = []
    if not path.is_absolute():
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", reference):
            raise ValueError("snapshot_unavailable")
        repository = cache_root() / ("models--" + reference.replace("/", "--"))
        main = repository / "refs/main"
        if not main.is_file():
            raise ValueError("snapshot_unavailable")
        revision = main.read_text().strip()
        if not re.fullmatch(r"[0-9a-fA-F]{7,64}", revision):
            raise ValueError("snapshot_unavailable")
        path = repository / "snapshots" / revision
        watched.append(main)
    if not (path / "config.json").is_file():
        raise ValueError("snapshot_unavailable")
    revision = path.name if path.parent.name == "snapshots" and re.fullmatch(r"[0-9a-fA-F]{7,64}", path.name) else None
    return path, revision, watched


def signature(path):
    value = path.stat()
    link = path.lstat()
    return (str(path.resolve()), value.st_dev, value.st_ino, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns, link.st_mtime_ns, link.st_ctime_ns)


def weight_paths(directory):
    # Match the existing mlx-lm loader, including any extra model shards.
    paths = sorted(directory.glob("model*.safetensors"))
    index = directory / "model.safetensors.index.json"
    if index.is_file():
        data = json.loads(index.read_text())
        weight_map = data.get("weight_map") if isinstance(data, dict) else None
        if not isinstance(weight_map, dict) or not weight_map:
            raise ValueError("invalid_weight_index")
        if any(not isinstance(name, str) or Path(name).name != name
               or not name.startswith("model") or not name.endswith(".safetensors")
               for name in weight_map.values()):
            raise ValueError("invalid_weight_index")
        if not set(weight_map.values()).issubset(path.name for path in paths):
            raise ValueError("weights_unavailable")
    if not paths or any(not path.is_file() or path.stat().st_size == 0 for path in paths):
        raise ValueError("weights_unavailable")
    return paths


def hash_weights(paths):
    result = []
    for path in paths:
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        result.append({"file": path.name, "bytes": path.stat().st_size, "sha256": digest})
    return result


def launch_argument(command, flag):
    args = shlex.split(command)
    # The private priority wrapper separates its arguments from mlx-lm with --.
    if "--" in args:
        args = args[args.index("--") + 1:]
    for index, arg in enumerate(args):
        if arg == flag:
            if index + 1 == len(args):
                raise ValueError("invalid_launch_arguments")
            return args[index + 1]
        if arg.startswith(flag + "="):
            return arg.split("=", 1)[1]
    return None


def inspect_files(server):
    started_at = process_started_at(server["pid"])
    model = server["active_model"]
    if launch_argument(server["command"], "--model") != model:
        raise ValueError("ambiguous_launch_model")
    # Launch flags alone do not prove that an adapter/draft was applied to
    # this request. Support those only after verifying the serving behavior.
    if launch_argument(server["command"], "--adapter-path"):
        raise ValueError("adapter_application_unverified")
    if launch_argument(server["command"], "--draft-model"):
        raise ValueError("draft_model_unverified")
    snapshot, revision, watched = resolve_snapshot(model)
    weights = weight_paths(snapshot)
    # Watch tokenizer/template/config as well: these can change behavior without
    # changing the tensor bytes. No tokenizer or config content is copied here.
    watched.extend([snapshot, *snapshot.iterdir()])
    before = {path: signature(path) for path in watched}
    # A cached revision edited/downloaded after process launch may differ from
    # the weights already in memory. Do not label that snapshot as the run model.
    if any(max(sig[4:]) / 1_000_000_000 >= started_at for sig in before.values()):
        raise ValueError("files_changed_since_server_start")
    config = json.loads((snapshot / "config.json").read_text())
    if not isinstance(config, dict):
        raise ValueError("invalid_model_config")
    quantization = config.get("quantization") or config.get("quantization_config")
    if isinstance(quantization, dict):
        quantization = {key: quantization[key] for key in ("bits", "group_size", "mode") if key in quantization}
    else:
        quantization = None
    info = {"id": model, "revision": revision, "snapshot": str(snapshot),
            "weights": hash_weights(weights), "quantization": quantization,
            "status": "recorded", "source": "local_server_launch_and_cache", "server_pid": server["pid"]}
    if any(signature(path) != sig for path, sig in before.items()):
        raise ValueError("files_changed_during_capture")
    return info, before


class ModelIdentity:
    def __init__(self, info):
        self.info = info
        self.server = None
        self.files = {}

    @classmethod
    async def capture(cls, config, session):
        if config["mock_mode"]:
            return cls({"id": None, "status": "mock"})
        result = cls({"id": None, "status": "unavailable"})
        url = urlsplit(config["base_url"])
        if (url.scheme != "http" or url.hostname not in ("localhost", "127.0.0.1")
                or url.port != 8080 or url.path.rstrip("/") != "/v1"):
            result.info["reason"] = "endpoint_not_managed_locally"
            return result
        try:
            server = await read_server(session)
            if config["model"] not in ("default_model", server["active_model"]):
                result.info["reason"] = "request_differs_from_launch_model"
                return result
            info, files = await asyncio.to_thread(inspect_files, server)
            if await read_server(session) != server:
                result.info["reason"] = "server_changed_during_capture"
                return result
            result.info, result.files, result.server = info, files, server
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError,
                KeyError, TypeError, subprocess.SubprocessError) as error:
            # Never persist response bodies, arbitrary errors, manager tokens or argv.
            known = {"manager_unavailable", "server_unavailable", "snapshot_unavailable",
                     "invalid_weight_index", "weights_unavailable", "invalid_model_config", "invalid_launch_arguments",
                     "ambiguous_launch_model", "adapter_application_unverified", "draft_model_unverified",
                     "files_changed_since_server_start", "files_changed_during_capture"}
            result.info["reason"] = str(error) if str(error) in known else type(error).__name__
        return result

    async def finish(self, session):
        if self.server is None:
            return self.info
        try:
            if await read_server(session) != self.server:
                self.info = {**self.info, "status": "changed_during_run", "reason": "server_changed"}
            elif any(signature(path) != sig for path, sig in self.files.items()):
                self.info = {**self.info, "status": "changed_during_run", "reason": "model_files_changed"}
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, KeyError, TypeError):
            self.info = {**self.info, "status": "unverified_after_run", "reason": "final_check_unavailable"}
        return self.info
