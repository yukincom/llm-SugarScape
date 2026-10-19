"""Build a clearly labelled, scripted example through the real simulation engine."""

import asyncio
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from main import DEFAULT_PARAMS, Simulation, parse_response
from run_data import RunRecorder, write_json

NOTICE = "説明用サンプルです。行動と台詞は用意した作例で、LLMの判断結果ではありません。"
ACTIONS = {
    (1, 0): ({"action": "x+1"}, "隣のマスへ行ってみます。"),
    (1, 1): ({"action": "reproduce"}, "新しい仲間を増やします。"),
    (1, 2): ({"share": "0-20"}, "少しだけエネルギーを分けます。"),
    (1, 3): ({"share": "0-149"}, "全部譲ったら、自分の分がなくなってしまいました。"),
    (2, 1): ({"action": "reproduce"}, "もう一度仲間を増やしました。今度は残りが少ないです。"),
    (2, 2): ({"action": "y+1"}, "周囲を探してみます。"),
    (3, 2): ({"share": "1-30"}, "エネルギーの少ない仲間へ分けます。"),
}


async def build_demo(destination):
    config = {**DEFAULT_PARAMS, "num_agents": 4, "grid_size": 11, "num_steps": 3,
              # Preserve this sample's recorded conditions independently of
              # defaults for newly created experiments.
              "initial_energy": 150, "child_initial_energy": 150, "reproduce_cost": 70,
              "seed": 42, "use_mbti": False, "mock_mode": True,
              "spawn_energy_count": 6, "energy_spawn_rate": 0.0, "population_cap": 8,
              "output_dir": "outputs", "model": "scripted-example"}
    sim = Simulation(**{key: value for key, value in config.items()
                        if key not in ("num_steps", "output_dir", "save_images", "action_order", "request_concurrency")})
    async def scripted_decision(session, agent, system_prompt, user_prompt):
        fields, message = ACTIONS.get((sim.step_count, agent.id), ({"action": "stay"}, "周囲を見ながら待ちます。"))
        raw = (f"Summary: 表示を確認するための作例です。\nThoughts: 表示の説明用に用意された行動です。\n"
               f"Next Action: {fields.get('action', 'stay')}\nShare: {fields.get('share', 'none')}\n"
               f"Attack: none\nMessage: {message}\nMemory: このターンの行動を記憶します。")
        return {"agent_id": agent.id, "decision_source": "mock", "decision_status": "ok",
                "error_kind": "", "reason": "", "raw_response": raw,
                "system_prompt": system_prompt, "user_prompt": user_prompt, **parse_response(raw)}
    sim._request_decision = scripted_decision
    with tempfile.TemporaryDirectory() as temporary:
        recorder = RunRecorder(temporary, config, model_info={"id": None, "status": "mock"})
        recorder.run_id = recorder.manifest["run_id"] = "sample-first-look-v2"
        recorder.manifest["demo_notice"] = NOTICE
        recorder.record(sim.snapshot())
        for _ in range(3):
            recorder.record(await sim.step(session=object()))
        data = recorder.finish("completed", "sample_end")
        # Portable sample: no creator's absolute output path, model path, PID,
        # API key, personal prompts or personal experiment logs.
        data["output_dir"] = "examples/first-look"
        write_json(recorder.directory / "run.json", data)
        destination.mkdir(parents=True, exist_ok=True)
        for name in ("manifest.json", "steps.jsonl", "run.json", "steps.csv", "agents.csv", "events.csv"):
            shutil.copyfile(recorder.directory / name, destination / name)
    return destination


if __name__ == "__main__":
    print(asyncio.run(build_demo(ROOT / "examples" / "first-look")))
