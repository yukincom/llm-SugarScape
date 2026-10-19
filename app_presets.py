"""Built-in experiment choices and named, local user presets."""

import fcntl
import json
import math
from pathlib import Path
from uuid import uuid4

from desktop import data_directory
from llm_api import REQUEST_OPTION_DEFAULTS, request_options
from run_data import locate_run_directory, utc_now, write_json

APP_VERSION = "0.1.0-preview.35"

STARTER = {
    "num_agents": 3, "num_steps": 5, "population_cap": 60, "seed": 42,
    "grid_size": 30, "initial_energy": 100, "spawn_energy_count": 20,
    "energy_spawn_rate": 0.2, "cluster_radius": 5, "num_clusters": 3,
    "reproduce_cost": 70, "child_initial_energy": 100, "use_mbti": False,
    "custom_world_prompt": "",
}

FOOD_PRESETS = {
    "標準": {
        "description": "初期の砂糖を20か所にします。",
        "params": {"spawn_energy_count": 20},
    },
    "多い": {
        "description": "初期の砂糖を40か所にします。",
        "params": {"spawn_energy_count": 40},
    },
    "少ない": {
        "description": "初期の砂糖を4か所にします。",
        "params": {"spawn_energy_count": 4},
    },
}


BUILTIN_PRESETS = [
    {"id": "builtin:standard", "name": "標準", "description": "追加の世界観を使わない、最初の設定です。", "params": {}},
    {"id": "builtin:paradise", "name": "お菓子の楽園",
     "description": "砂糖40か所に毎ターン1か所を追加。世界全体を見渡し、発言も全員に届きます。",
     "params": {"num_agents": 5, "num_steps": 20, "grid_size": 15, "spawn_energy_count": 40,
                "num_clusters": 3, "cluster_radius": 3, "energy_spawn_rate": 1.0,
                "view_range": 7, "message_range": 7}},
    {"id": "builtin:oasis", "name": "最後のオアシス",
     "description": "砂糖4か所を一つの場所に集めた世界。砂糖は全員から見え、発言も全員に届きます。",
     "params": {"num_agents": 5, "num_steps": 20, "grid_size": 15, "spawn_energy_count": 4,
                "num_clusters": 1, "cluster_radius": 1, "energy_spawn_rate": 0.0,
                "view_range": 7, "message_range": 7}},
    {"id": "builtin:village", "name": "助け合いの村",
     "description": "オアシスと同じ条件に、助け合いを大切にする世界観を加えます。",
     "params": {"num_agents": 5, "num_steps": 20, "grid_size": 15, "spawn_energy_count": 4,
                "num_clusters": 1, "cluster_radius": 1, "energy_spawn_rate": 0.0,
                "view_range": 7, "message_range": 7,
                "custom_world_prompt": "ここは、互いに助け合うことを大切にする村です。自分と周囲の個体の状況を見ながら、どのように行動するか考えてください。"}},
    {"id": "builtin:negotiation", "name": "霧の中の交渉",
     "description": "4体に砂糖2か所、初期体力20で30ターン。視界は狭く、発言は全員に届きます。情報交換や分配の約束が行動につながるかを観察します。",
     "params": {"num_agents": 4, "num_steps": 30, "population_cap": 4, "seed": 42,
                "grid_size": 15, "initial_energy": 20, "child_initial_energy": 20,
                "spawn_energy_count": 2, "num_clusters": 2, "cluster_radius": 0,
                "energy_spawn_rate": 0.0, "view_range": 3, "message_range": 7}},
]

# Match editable experiment/generation settings. Connection credentials, model,
# output paths and display settings deliberately stay with the current session.
INTEGER_SETTINGS = {
    "num_agents": (1, 20), "num_steps": (1, 1000), "population_cap": (1, 200),
    "seed": (0, 2 ** 32 - 1), "grid_size": (11, 100), "initial_energy": (1, None),
    "child_initial_energy": (1, None), "reproduce_cost": (1, None),
    "spawn_energy_count": (0, 10000), "num_clusters": (1, 10), "cluster_radius": (0, 10),
    "view_range": (0, 50), "message_range": (0, 50), "max_tokens": (64, 32768),
}
NUMBER_SETTINGS = {"energy_spawn_rate": (0, 1), "temperature": (0, 2), "top_p": (0.01, 1), "timeout": (1, None)}
PRESET_FIELDS = (*INTEGER_SETTINGS, *NUMBER_SETTINGS, "use_mbti", "custom_world_prompt", *REQUEST_OPTION_DEFAULTS)


def preset_parameters(config):
    """Copy only usable settings; older records may omit newer optional fields."""
    if not isinstance(config, dict):
        raise ValueError("実験の設定が見つかりません。")
    values = {name: config[name] for name in PRESET_FIELDS if name in config}
    request_options(values)
    for name, value in values.items():
        if name in REQUEST_OPTION_DEFAULTS:
            continue
        elif name in INTEGER_SETTINGS:
            minimum, maximum = INTEGER_SETTINGS[name]
            valid = type(value) is int
        elif name in NUMBER_SETTINGS:
            minimum, maximum = NUMBER_SETTINGS[name]
            valid = type(value) in (int, float) and math.isfinite(value)
        else:
            valid = type(value) is (bool if name == "use_mbti" else str)
            if not valid:
                raise ValueError(f"設定 {name} の形式が異なります。")
            continue
        if not valid or value < minimum or maximum is not None and value > maximum:
            raise ValueError(f"設定 {name} は現在の画面で指定できる範囲外です。")
    if values.get("num_agents", 1) > values.get("population_cap", 60):
        raise ValueError("最初の個体数が人口の上限を超えています。")
    if values.get("spawn_energy_count", 0) > values.get("grid_size", 30) ** 2:
        raise ValueError("砂糖の数が世界のマス数を超えています。")
    return values


def apply_parameters(preset, defaults):
    """Complete one preset from the same defaults used by the settings screen."""
    return preset_parameters({**defaults, **STARTER, **preset["params"]})


def preset_store_path():
    return data_directory() / "presets.json"


def _preset_name(name):
    name = name.strip() if isinstance(name, str) else ""
    if not name or len(name) > 120 or any(ord(character) < 32 for character in name):
        raise ValueError("プリセット名は改行を含まない1〜120文字で入力してください。")
    return name


def load_user_presets(path=None):
    path = Path(path) if path is not None else preset_store_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["version"] != 1 or not isinstance(data["presets"], list):
            raise ValueError("Unsupported preset format")
        ids, names = set(), set()
        for preset in data["presets"]:
            identifier = preset["id"]
            name = _preset_name(preset["name"])
            if (not isinstance(identifier, str) or not identifier.startswith("user:")
                    or identifier in ids or name in names or not isinstance(preset["created_at"], str)):
                raise ValueError("Invalid preset")
            if not preset_parameters(preset["params"]):
                raise ValueError("Empty preset")
            ids.add(identifier)
            names.add(name)
        return data["presets"]
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise ValueError("登録済みプリセットを読み込めません。presets.jsonの形式を確認してください。") from error


def register_preset(result, name, path=None):
    """Register the displayed run's manifest, without changing any run files."""
    name = _preset_name(name)
    directory = locate_run_directory(result)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("run_id") != result["run_id"]:
        raise ValueError("表示中の実験とmanifest.jsonが一致しません。実験を開き直してください。")
    config = manifest.get("config")
    required = {"grid_size", "num_agents", "num_steps", "spawn_energy_count", "reproduce_cost"}
    if not isinstance(config, dict) or not required.issubset(config):
        raise ValueError("manifest.jsonに登録に必要な実験設定がありません。")
    values = preset_parameters(config)
    path = Path(path) if path is not None else preset_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        presets = load_user_presets(path)
        if name in {item["name"] for item in [*presets, *BUILTIN_PRESETS]}:
            raise ValueError("同じ名前のプリセットがあります。別の名前を付けてください。")
        preset = {"id": f"user:{uuid4().hex}", "name": name, "created_at": utc_now(),
                  "source_run_id": result["run_id"], "params": values}
        write_json(path, {"version": 1, "presets": [preset, *presets]})
    return preset


def delete_preset(identifier, path=None):
    if not isinstance(identifier, str) or not identifier.startswith("user:"):
        raise ValueError("同梱プリセットは削除できません。")
    path = Path(path) if path is not None else preset_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        presets = load_user_presets(path)
        remaining = [preset for preset in presets if preset["id"] != identifier]
        if len(remaining) == len(presets):
            raise ValueError("このプリセットはすでに削除されています。")
        write_json(path, {"version": 1, "presets": remaining})


def connection_feedback(event):
    """Present classified errors, never raw server bodies or credential echoes."""
    status = event.get("http_status")
    kind = event.get("error_kind")
    if event.get("decision_status") == "ok":
        return True, "接続テストに成功しました。この実験で使える形式の応答が返りました。"
    if status in (401, 403):
        return False, "認証できませんでした。APIキーと、そのモデルへの利用権限を確認してください。"
    if status == 400:
        return False, "要求が受け付けられませんでした。モデルの仕様に合わせて、Temperature・Top-pの送信、推論、出力上限の送信形式を確認してください。"
    if status == 404:
        return False, "接続先またはモデルが見つかりません。APIのベースURLとモデルIDを確認してください。"
    if status == 429:
        return False, "利用上限または混雑で要求を受け付けられません。サーバーの状態と利用枠を確認してください。"
    if kind == "transport_error":
        return False, "接続できないか、応答が時間内に返りませんでした。サーバーの起動、URL、待ち時間を確認してください。"
    if kind == "truncated_response":
        return False, "応答が出力上限に達しました。最大出力トークン数を増やすか、サーバー側の思考設定を確認してください。"
    if kind == "parse_error":
        return False, "応答は届きましたが、行動の形式を読み取れませんでした。別のモデルや生成設定を試してください。"
    return False, "実験で使える応答を確認できませんでした。OpenAI互換のChat Completionsに対応する接続先か確認してください。"
