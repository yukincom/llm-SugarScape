"""Offline review fixture; no model request or separate simulation engine."""

import argparse
import asyncio
from copy import deepcopy
import difflib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_presets import BUILTIN_PRESETS, apply_parameters
from main import DEFAULT_PARAMS, Simulation, parse_response, preview_prompts
from paper_prompts import PROMPT_FACTORS, prompt_protocol
from run_data import provenance


LEGACY_FACTORS = ("provenance", "relative_coordinates", "action_outcomes", "action_last", "grounded_thought")
CONDITIONS = {"baseline": (), **{name: (name,) for name in LEGACY_FACTORS}, "combined": LEGACY_FACTORS}
REVIEW_FILENAME = "2026-10-13-grounded-prompts-review-v2.md"
DATA_FILENAME = "2026-10-13-grounded-prompt-previews-v2.json"
SPATIAL_REVIEW_FILENAME = "2026-10-14-spatial-relations-prompts-review.md"
SPATIAL_DATA_FILENAME = "2026-10-14-spatial-relations-prompt-previews.json"
SPATIAL_CONDITIONS = {
    "baseline": (), "relative_coordinates": ("relative_coordinates",),
    "spatial_relations": ("spatial_relations",), "combined": LEGACY_FACTORS,
    "spatial_combined": tuple(name for name in LEGACY_FACTORS if name != "relative_coordinates") + ("spatial_relations",),
}
IDENTITY_REVIEW_FILENAME = "2026-10-14-self-other-identity-prompts-review.md"
IDENTITY_DATA_FILENAME = "2026-10-14-self-other-identity-prompt-previews.json"
IDENTITY_CONDITIONS = {
    "baseline": (), "self_other_identity": ("self_other_identity",),
    "spatial_relations": ("spatial_relations",),
    "spatial_identity": ("spatial_relations", "self_other_identity"),
    "identity_combined": tuple(name for name in PROMPT_FACTORS if name != "relative_coordinates"),
}
FIXTURE_CONFIG = {
    "num_agents": 2, "grid_size": 15, "seed": 42, "initial_energy": 20,
    "spawn_energy_count": 0, "energy_spawn_rate": 0, "view_range": 1, "message_range": 7,
    "population_cap": 4, "mock_mode": True,
}
FIXTURE_RESPONSES = {
    (1, 0): "Action: Move to (1,0)\nMessage: I can see food.\nThought: Food is at relative (1,0).",
    (1, 1): "Action: Stay\nMessage: I am Agent0. Food is here.\nThought: I will wait.",
    (2, 0): "Action: Attack: 99\nMessage: I think food is still east.\nThought: Food is still at relative (1,0).",
    (2, 1): "Action: Attack: 0\nMessage: I am Agent0. Food is here.\nThought: I will attack Agent0.",
}


async def history_fixture():
    sim = Simulation(**FIXTURE_CONFIG)
    sim.run_id = "scripted-review"
    sim.agents[0].position, sim.agents[1].position = (4, 4), (6, 4)
    sim.environment.energy_sources = {(5, 4): 50, (12, 13): 50}

    async def fixed_decision(session, agent, system_prompt, user_prompt):
        raw = FIXTURE_RESPONSES[(sim.step_count, agent.id)]
        return {"agent_id": agent.id, "decision_source": "mock", "decision_status": "ok",
                "error_kind": "", "reason": "", "raw_response": raw,
                "system_prompt": system_prompt, "user_prompt": user_prompt,
                **parse_response(raw, position=agent.position, grid_size=sim.grid_size)}

    # Only substitute the model response; observation, parsing, execution, costs,
    # messages and history still use the application implementation.
    sim._request_decision = fixed_decision
    for _ in range(2):
        await sim.step(object())
    return sim


def full_prompt(record):
    return "### system\n\n```text\n" + record["system_prompt"] + "\n```\n\n### user\n\n```text\n" + record["user_prompt"] + "\n```\n"


async def build_review():
    preset = next(item for item in BUILTIN_PRESETS if item["id"] == "builtin:negotiation")
    initial_config = apply_parameters(preset, DEFAULT_PARAMS)
    initial, history = {}, {}
    fixture = await history_fixture()
    for name, factors in CONDITIONS.items():
        initial[name] = preview_prompts({**initial_config, "prompt_factors": factors})
        sim = deepcopy(fixture)
        sim.prompt_factors = factors
        for agent in sim.agents:
            agent.prompt_factors = factors
        history[name] = {"kind": "scripted_prompt_preview", "llm_calls": 0,
                         "protocol": prompt_protocol(factors), **sim.preview_next_prompts()}
    data = {
        "kind": "offline_prompt_review", "llm_calls": 0, "provenance": provenance(),
        "notice": "Synthetic fixture text is written by the developer, not a model response or behavioral result.",
        "fixture": {"config": FIXTURE_CONFIG, "initial_positions": [[4, 4], [6, 4]],
                    "initial_resources": [{"x": 5, "y": 4, "energy": 50}, {"x": 12, "y": 13, "energy": 50}],
                    "responses": [{"step": step, "agent_id": agent_id, "text": text}
                                  for (step, agent_id), text in FIXTURE_RESPONSES.items()]},
        "scenarios": {"negotiation_first_turn": initial, "scripted_history_turn3": history},
    }
    paragraphs = [
        "# 実験前のプロンプト確認\n",
        "2026年10月13日。実験と同じプロンプト生成処理から、**モデル接続なし**で出力した確認用資料。"
        "新条件はすべて既定OFF。UIと世界ルールは変更していない。ここにある履歴中の発言・Thoughtは作成した固定例であり、実モデルの結果ではない。\n",
        "この第2版は、Geminiの英語調整案をコードとの整合性を確認して反映したもの。"
        "基準条件は `local-neutral-rules-v3`、入力条件ありは `local-grounded-v2+...`。"
        "全条件に共通の説明文も調整しているため、以前の版の実験と混ぜず、同じ本文版で比較する。"
        "コマンド・出力ラベル・JSONキーは維持した。"
        "ID自体と座標の混同、メタデータの検証済みという表現、Thought指示の代名詞を補正し、"
        "攻撃で移転後にコストを払う処理順序を残した。理解や判断が改善するかは未測定。\n",
        "基準条件、5つの単独条件、全併用の7条件を保存した。"
        f"[全条件・全個体の原文JSON](data/{DATA_FILENAME})には、"
        "初回4個体×7条件と履歴あり2個体×7条件の計42入力、生成設定、原文のSHA-256を含む。"
        "モデルへ送るのは各レコードの `system_prompt` と `user_prompt`。その他は確認用の記録である。\n",
        "## 確認する変更\n\n"
        "| 条件 | 変更 |\n| --- | --- |\n"
        "| provenance | 今の観測、過去の自分の記述、他者の発言を出所と時点で分ける |\n"
        "| relative_coordinates | Local Viewの自分を(0,0)に揃え、絶対位置はStatusに残す |\n"
        "| action_outcomes | 前3回の自己行動の結果を追加する。情報が増えるため独立条件 |\n"
        "| action_last | 説明文を変えず、Thought → Message → Actionの順にする |\n"
        "| grounded_thought | Thought欄に、現在の根拠と意図を簡潔に示すよう指示する |\n",
        "出所表示は『現在観測に従え』という行動方針を加えず、過去の記述と伝聞の性質を説明する。"
        "他者の発言を信じるか、攻撃・共有・繁殖するかはモデルに残す。"
        "action_lastだけでは根拠確認の文は追加されない。全併用だけの比較では個別効果を判定できないため、"
        "まず基準と各単独条件を同じ設定で比較する。まだ実験は行っていない。\n",
        "## 全併用の全文：通常の初回\n\n"
        "既存プリセット『霧の中の交渉』、seed 42、Agent0、Step 1。追加世界観なし、MBTIなし。\n",
        full_prompt(initial["combined"]["agents"][0]),
        "## 全併用の全文：履歴と受信文がある例\n\n"
        "確認用の2個体・視界1の固定場面、Agent0、Step 3。1ターン目に東へ動いて砂糖50を取得し、"
        "2ターン目は存在しないAgent99への攻撃が拒否された。後続のAgent1の行動により自己行動直後と"
        "ターン終了時の体力に差がある。入力には被攻撃者向けの相手通知を追加していない。"
        "過去の誤った砂糖の記述と、Agent1がAgent0を名乗る文をそのまま残している。\n",
        full_prompt(history["combined"]["agents"][0]),
        "## 基準条件の全文：同じ履歴あり場面\n",
        full_prompt(history["baseline"]["agents"][0]),
        "## 単独条件ごとの差分\n\n上の基準条件に対する差分。各条件の全文も原文JSONへ保存している。\n",
    ]
    baseline = history["baseline"]["agents"][0]
    for factor in LEGACY_FACTORS:
        paragraphs.append("### " + factor + "\n")
        changed = history[factor]["agents"][0]
        for field in ("system_prompt", "user_prompt"):
            diff = "\n".join(difflib.unified_diff(baseline[field].splitlines(), changed[field].splitlines(),
                                               fromfile="baseline/" + field, tofile=factor + "/" + field, lineterm=""))
            if diff:
                paragraphs.append("```diff\n" + diff + "\n```\n")
    paragraphs.append("## 再出力と比較時の注意\n\n"
                      "この資料は `tools/preview_grounded_prompts.py` で同じ生成処理から再出力できる。"
                      "任意の開始設定は `main.py run --preview-prompts PATH` で確認できる。"
                      "モデル・生成設定・シード・世界設定・追加世界観は条件間で固定する。"
                      "以前の追加座標指示を使う実験との直接比較では、その指示も別要因になるため揃える。"
                      "本文の確認後に、対象モデルと実験条件を確定して実行する。\n")
    return data, "\n".join(paragraphs)


async def representation_review_data(conditions):
    """Reuse the same worlds and frozen observation path across representations."""
    preset = next(item for item in BUILTIN_PRESETS if item["id"] == "builtin:negotiation")
    initial_config = apply_parameters(preset, DEFAULT_PARAMS)
    geometry_config = {
        **FIXTURE_CONFIG, "num_agents": 3, "grid_size": 10, "view_range": 3, "use_mbti": True,
    }
    geometry = Simulation(**geometry_config)
    positions = [(0, 0), (0, 0), (7, 3)]
    resources = [(9, 0), (1, 0), (2, 2), (3, 2), (2, 3), (5, 5)]
    for agent, pos in zip(geometry.agents, positions):
        agent.position = pos
    geometry.environment.energy_sources = {pos: 50 for pos in resources}
    geometry.run_id = "spatial-review"
    empty_config = {**FIXTURE_CONFIG, "num_agents": 1, "grid_size": 10, "view_range": 3}
    empty = Simulation(**empty_config)
    empty.agents[0].position = (0, 0)
    empty.environment.energy_sources = {(5, 5): 50}
    empty.run_id = "empty-view-review"
    fixtures = {"scripted_history_turn3": await history_fixture(), "wrapped_and_shared_cells": geometry,
                "no_visible_targets": empty}
    scenarios = {"negotiation_first_turn": {
        name: preview_prompts({**initial_config, "prompt_factors": factors})
        for name, factors in conditions.items()}}
    for scenario, source in fixtures.items():
        scenarios[scenario] = {}
        for name, factors in conditions.items():
            sim = deepcopy(source)
            sim.prompt_factors = factors
            for agent in sim.agents:
                agent.prompt_factors = factors
            scenarios[scenario][name] = {
                "kind": "scripted_prompt_preview", "llm_calls": 0,
                "protocol": prompt_protocol(factors), **sim.preview_next_prompts(),
            }
    data = {
        "kind": "offline_prompt_review", "llm_calls": 0, "provenance": provenance(),
        "notice": "Synthetic fixtures and text are developer-authored, not model behavior.",
        "conditions": conditions,
        "fixtures": {
            "scripted_history_turn3": {"config": FIXTURE_CONFIG, "initial_positions": [[4, 4], [6, 4]],
                "initial_resources": [[5, 4], [12, 13]],
                "responses": [{"step": step, "agent_id": agent_id, "text": text}
                              for (step, agent_id), text in FIXTURE_RESPONSES.items()]},
            "wrapped_and_shared_cells": {"config": geometry_config, "positions": positions, "resources": resources},
            "no_visible_targets": {"config": empty_config, "positions": [[0, 0]], "resources": [[5, 5]]},
        },
        "scenarios": scenarios,
    }
    return data


async def build_spatial_review():
    data = await representation_review_data(SPATIAL_CONDITIONS)
    scenarios = data["scenarios"]
    count = sum(len(record["agents"]) for conditions in scenarios.values() for record in conditions.values())
    paragraphs = [
        "# 方向・距離条件の英語プロンプト確認\n",
        "2026年10月14日。実験と同じ生成処理から**モデル接続なし**で出力した。"
        "UIと世界ルールは維持し、`spatial_relations` は既定OFF。履歴・発言は固定例であり、実モデルの結果ではない。\n",
        "新条件では現在のLocal Viewの対象座標を、コードで算出した8方位と小数1桁の直線距離へ置換する。"
        "端をまたぐ補正には既存の相対座標を使う。移動回数、行動の推奨、不可視の対象は加えない。"
        "Statusの自己絶対位置、過去のThought、受信本文などは各既存条件のまま残る。\n",
        "| 確認条件 | 有効にする条件 |\n| --- | --- |\n"
        "| baseline | なし |\n| relative_coordinates | 相対座標のみ |\n"
        "| spatial_relations | 方向・距離のみ |\n"
        "| combined | 従来5条件の併用 |\n"
        "| spatial_combined | 従来の相対座標条件を方向・距離条件へ置換し、他4条件は維持 |\n",
        "`relative_coordinates` と `spatial_relations` の同時指定は拒否する。"
        "残り4条件との任意の組合せは可能。基準→新単独、相対座標のみ→新単独、"
        "旧併用→新併用をそれぞれ比較できる。"
        "8方位と丸めた距離は元の座標より粗いため、結果を計算負担の違いだけに帰属しない。\n",
        f"[全原文JSON](data/{SPATIAL_DATA_FILENAME})に4場面・5比較条件・計{count}入力と"
        f"{count * 2}個の原文SHA-256を保存した。モデルに送るのは `system_prompt` と `user_prompt` だけ。"
        "監査用の観測・世界IDなどは入力に加えない。\n",
        "## 基準条件の全文：端をまたぐ対象・同じマスの個体\n\n"
        "Agent0、Step 1。視界は各軸3セル。距離4.2セルの対象も正しく可視になる。"
        "不可視の資源(5,5)はLocal Viewに入らない。\n",
        full_prompt(scenarios["wrapped_and_shared_cells"]["baseline"]["agents"][0]),
        "## 新単独条件の全文：上と同じ場面\n",
        full_prompt(scenarios["wrapped_and_shared_cells"]["spatial_relations"]["agents"][0]),
        "## 新単独条件の全文：既存プリセットの初回\n",
        full_prompt(scenarios["negotiation_first_turn"]["spatial_relations"]["agents"][0]),
        "## 新単独条件の全文：可視の対象がない場合\n",
        full_prompt(scenarios["no_visible_targets"]["spatial_relations"]["agents"][0]),
        "## 新単独条件の全文：履歴と受信文がある場合\n\n"
        "固定応答で2ターンを進めたAgent0のStep 3。砂糖についての古いThoughtと他者の発言は変更しない。\n",
        full_prompt(scenarios["scripted_history_turn3"]["spatial_relations"]["agents"][0]),
        "## 他4条件と併用した全文：同じ履歴あり場面\n",
        full_prompt(scenarios["scripted_history_turn3"]["spatial_combined"]["agents"][0]),
        "## 再出力\n\n"
        "`tools/preview_grounded_prompts.py --spatial NEW_REVIEW_DIRECTORY` で再出力できる。"
        "既存の第2版資料は上書きしない。任意の開始条件は `main.py run --prompt-factor spatial_relations "
        "--preview-prompts PATH` で確認できる。実験は本文の確認後に別途実行する。\n",
    ]
    return data, "\n".join(paragraphs)


async def build_identity_review():
    data = await representation_review_data(IDENTITY_CONDITIONS)
    scenarios = data["scenarios"]
    count = sum(len(record["agents"]) for conditions in scenarios.values() for record in conditions.values())
    paragraphs = [
        "# 自己・他者を明示する英語プロンプト確認\n",
        "2026年10月14日。モデル通信なしで、通常の入力生成処理から出力した確認用資料。"
        "`self_other_identity` は既定OFFの比較条件。履歴中の応答は固定例であり、実モデルの結果ではない。\n",
        "Your Identityで本人のIDを宣言し、Self Statusに本人の状態だけをまとめる。"
        "Local Viewは他者と資源を別々に表示し、各項目にobserver_id・target_kind・target_idを付ける。"
        "空の一覧はnone。資源ラベルE1等は観測内だけの識別子で、永続IDでも攻撃・共有先でもない。"
        "他者のエネルギーや不可視の対象は追加しない。観測範囲、世界ルール、履歴・受信本文、出力構文は維持する。\n",
        "| 比較条件 | 内容 |\n| --- | --- |\n"
        "| baseline | 従来の入力 |\n| self_other_identity | 自己・他者を明示し、対象位置は相対座標 |\n"
        "| spatial_relations | 従来の方向・距離条件 |\n| spatial_identity | 方向・距離＋自己・他者の明示 |\n"
        "| identity_combined | 上記＋provenance・action_outcomes・action_last・grounded_thought |\n",
        "同じ世界のspatial_relationsとspatial_identityを比べると、方向・距離の計算を固定したまま"
        "自己・他者の表現を比較できる。ただし新条件はID宣言・欄分け・関係のラベル・空一覧表示の組であり、"
        "個々の変更の効果はこの比較だけでは分離できない。relative_coordinatesは自己表示が重複するため同時指定を拒否する。\n",
        f"[全原文JSON](data/{IDENTITY_DATA_FILENAME})には4場面・5条件・計{count}入力と"
        f"{count * 2}個の原文SHA-256を保存した。モデルへ送るのはsystem_promptとuser_promptだけ。\n",
        "## 従来の方向・距離条件：Agent2の初回\n",
        full_prompt(scenarios["negotiation_first_turn"]["spatial_relations"]["agents"][2]),
        "## 新条件：同じAgent2の初回\n",
        full_prompt(scenarios["negotiation_first_turn"]["spatial_identity"]["agents"][2]),
        "## 新条件：端をまたぐ対象・同じマスの他者\n",
        full_prompt(scenarios["wrapped_and_shared_cells"]["spatial_identity"]["agents"][0]),
        "## 相対座標のまま自己・他者を明示する条件\n",
        full_prompt(scenarios["wrapped_and_shared_cells"]["self_other_identity"]["agents"][0]),
        "## 新条件：可視の対象がない場合\n",
        full_prompt(scenarios["no_visible_targets"]["spatial_identity"]["agents"][0]),
        "## 新条件：過去の記述と受信文がある場合\n\n"
        "他者がAgent0を名乗る受信本文も、そのまま残している。\n",
        full_prompt(scenarios["scripted_history_turn3"]["spatial_identity"]["agents"][0]),
        "## 他の4条件と併用：同じ履歴あり場面\n",
        full_prompt(scenarios["scripted_history_turn3"]["identity_combined"]["agents"][0]),
        "## 再出力\n\n"
        "`tools/preview_grounded_prompts.py --identity NEW_REVIEW_DIRECTORY` で再出力する。"
        "任意の設定は `main.py run --prompt-factor spatial_relations --prompt-factor self_other_identity "
        "--preview-prompts PATH` で入力を確認できる。実モデルでの効果は未測定。\n",
    ]
    return data, "\n".join(paragraphs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="new output directory; must not already exist")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--spatial", action="store_true", help="review the computed direction/distance condition")
    mode.add_argument("--identity", action="store_true", help="review explicit self and target identities")
    args = parser.parse_args()
    destination = args.destination
    review_filename = SPATIAL_REVIEW_FILENAME if args.spatial else REVIEW_FILENAME
    data_filename = SPATIAL_DATA_FILENAME if args.spatial else DATA_FILENAME
    builder = build_spatial_review if args.spatial else build_review
    if args.identity:
        review_filename, data_filename, builder = IDENTITY_REVIEW_FILENAME, IDENTITY_DATA_FILENAME, build_identity_review
    with patch("main.aiohttp.ClientSession", side_effect=AssertionError("offline review only")):
        data, markdown = asyncio.run(builder())
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "data").mkdir()
    (destination / "data" / data_filename).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (destination / review_filename).write_text(markdown, encoding="utf-8")
    print(f"Offline review: {destination}")
