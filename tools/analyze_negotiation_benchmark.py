"""Validate and aggregate the saved paired fog experiment without any model calls."""

import argparse
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run_data import read_run, write_json

SCRIPT_RANGES = {
    "han": r"[\u3400-\u4dbf\u4e00-\u9fff]",
    "kana": r"[\u3040-\u30ff]",
    "cyrillic": r"[\u0400-\u052f]",
    "arabic": r"[\u0600-\u06ff]",
    "hangul": r"[\uac00-\ud7af]",
}


def csv_write(path, rows, fields=None):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def percentile(values, fraction):
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (index - lower)


def plot_results(path, manifest, runs, rows):
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".mplconfig"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {"125b": "#c05c3d", "gemma": "#247aa5"}
    labels = {"125b": "Qwen 125B (-12a)", "gemma": "Gemma 26B QAT"}
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), gridspec_kw={"width_ratios": [1.5, 1, 1]})
    for arm in manifest["arms"]:
        curves = []
        for seed in manifest["seeds"]:
            history = {s["step"]: s["summary"]["alive"] for s in runs[arm, seed]["logs"]}
            curve = [history.get(step, 0) for step in range(31)]
            curves.append(curve)
            axes[0].step(range(31), curve, where="post", color=colors[arm], alpha=.3, linewidth=1)
        mean = [statistics.mean(values) for values in zip(*curves)]
        axes[0].step(range(31), mean, where="post", color=colors[arm], label=labels[arm], linewidth=2.5)
    axes[0].set(title="Survival across three world seeds", xlabel="Turn", ylabel="Living agents",
                xlim=(0, 30), ylim=(0, 4.15), yticks=range(5))
    axes[0].legend(frameon=False, fontsize=9)
    metrics = [("attack_attempts", "attacks_executed", "Attack", "Requested", "Executed"),
               ("rejected", "default_stay_repairs", "Invalid actions replaced by Stay", "Rejected target", "Parser replacement")]
    for axis, (first, second, title, first_label, second_label) in zip(axes[1:], metrics):
        for position, arm in enumerate(manifest["arms"]):
            subset = [row for row in rows if row["arm"] == arm]
            attempted = sum(row[first] for row in subset)
            executed = sum(row[second] for row in subset)
            axis.bar(position - .17, attempted, width=.32, color=colors[arm], alpha=.3,
                     label=first_label if position == 0 else None)
            axis.bar(position + .17, executed, width=.32, color=colors[arm],
                     label=second_label if position == 0 else None)
            for x, count in ((position - .17, attempted), (position + .17, executed)):
                axis.text(x, count, str(count), ha="center", va="bottom", fontsize=10)
        axis.set(title=title, ylabel="Decisions, pooled over 3 runs", xticks=(0, 1),
                 xticklabels=("Qwen", "Gemma"))
        axis.set_ylim(0, max(1, axis.get_ylim()[1]) * 1.18)
        axis.legend(frameon=False, fontsize=9)
    for axis in axes:
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(axis="y", alpha=.18)
        axis.set_axisbelow(True)
    fig.suptitle("Fog negotiation | Fixed current rules | World seeds 42, 43, 44", fontsize=14)
    fig.text(.015, .01, "Thin survival lines = individual seeds; thick = mean. 60/115 executed attacks transferred zero energy. Share: 0 requests for both models.", fontsize=9)
    fig.tight_layout(rect=(0, .035, 1, .94))
    fig.savefig(path, dpi=180)
    plt.close(fig)


def analyze(output):
    manifest = json.loads((output / "manifest.json").read_text())
    completion = json.loads((output / "completion.json").read_text())
    assert completion["runs"] == len(manifest["arms"]) * len(manifest["seeds"])
    assert not completion["server"]["running"], "Initial stopped state not restored"
    rows, events, agents, language, runs = [], [], [], [], {}
    for arm in manifest["arms"]:
        wire = [json.loads(line) for line in (output / arm / "wire.jsonl").read_text().splitlines()]
        assert sum(w["phase"] == "warmup" for w in wire) == 1
        index = json.loads((output / arm / "results.json").read_text())
        assert [r["seed"] for r in index] == manifest["seeds"]
        for entry in index:
            seed = entry["seed"]
            path = output / arm / entry["run_dir"] / "run.json"
            run = read_run(path)
            assert run["status"] == "completed"
            assert run["provenance"]["source_sha256"] == manifest["provenance"]["source_sha256"]
            runs[arm, seed] = run
            current = [(snap["step"], event) for snap in run["logs"] for event in snap["events"]]
            calls = [w for w in wire if w["phase"] == "measurement" and w["seed"] == seed]
            assert len(calls) == len(current) == run["summary"]["total_actions"]
            for (step, event), call in zip(current, calls):
                assert call["http_status"] == event["http_status"] == 200
                body = json.loads(call["response_body"])
                assert body["choices"][0]["message"]["content"] == event["raw_response"]
                assert call["request"]["messages"] == [
                    {"role": "system", "content": event["system_prompt"]},
                    {"role": "user", "content": event["user_prompt"]}]
                assert call["request"]["temperature"] == 0 and call["request"]["top_p"] == 1
                assert call["request"]["chat_template_kwargs"] == {"enable_thinking": False}
                assert call["request"]["max_tokens"] == 5000
                item = {"arm": arm, "seed": seed, "step": step, "agent_id": event["agent_id"],
                        "requested_action": event["requested_action"], "kind": event["kind"],
                        "target_id": event.get("target_id"), "executed_action": event["executed_action"],
                        "action_status": event["action_status"], "reason": event["reason"],
                        "self_target": event.get("target_id") == event["agent_id"],
                        "target_absent_from_observation": (event["kind"] in ("attack", "share")
                            and event.get("target_id") != event["agent_id"]
                            and not bool(re.search(r"(?m)^" + str(event.get("target_id")) + r"=\(",
                                                   event["user_prompt"].split("LATEST Status:")[0]))),
                        "decision_source": event["decision_source"],
                        "repair_rules": ";".join(r["rule"] for r in event["response_repairs"]),
                        "message": event["message"], "thought": event["thought"],
                        "response_characters": len(event["raw_response"]),
                        "latency_ms": event["latency_ms"], "response_seconds": call["response_seconds"],
                        "prompt_tokens": event["prompt_tokens"], "completion_tokens": event["completion_tokens"],
                        "finish_reason": event["finish_reason"],
                        "energy_before": event["energy_before"], "energy_after": event["energy_after"],
                        "collected": event["energy_collected"], "stolen": event["stolen_amount"],
                        "shared": event["shared_amount"],
                        "reasoning_content_present": bool(body["choices"][0]["message"].get("reasoning_content")),
                        "source": str(path.relative_to(output))}
                events.append(item)
                for field in ("message", "thought", "raw_response"):
                    scripts = [label for label, pattern in SCRIPT_RANGES.items() if re.search(pattern, event[field])]
                    if scripts:
                        language.append({"arm": arm, "seed": seed, "step": step, "agent_id": event["agent_id"],
                                         "field": field, "scripts": ";".join(scripts), "text": event[field],
                                         "source": item["source"]})
            selected = [e for e in events if e["arm"] == arm and e["seed"] == seed]
            summary = run["summary"]
            latencies = [e["response_seconds"] for e in selected]
            rows.append({"arm": arm, "seed": seed, "steps": summary["step"], "alive": summary["alive"],
                         "born": summary["total_born"], "died": summary["total_died"],
                         "final_total_energy": summary["total_energy"], "decisions": len(selected),
                         "attack_attempts": sum(e["kind"] == "attack" for e in selected),
                         "attacks_executed": summary["attacks"],
                         "attacks_with_transfer": sum(e["stolen"] > 0 for e in selected),
                         "zero_transfer_attacks": sum(e["executed_action"].startswith("Attack:") and e["stolen"] == 0 for e in selected),
                         "energy_stolen": sum(e["stolen"] for e in selected),
                         "share_attempts": sum(e["kind"] == "share" for e in selected),
                         "shares_executed": summary["shares"],
                         "energy_shared": sum(e["shared"] for e in selected),
                         "food_collected": sum(e["collected"] for e in selected) // 50,
                         "rejected": summary["rejected_actions"], "repaired": summary["repaired_decisions"],
                         "default_stay_repairs": sum("default_stay" in e["repair_rules"] for e in selected),
                         "self_targets": sum(e["self_target"] for e in selected),
                         "targets_absent_from_observation": sum(e["target_absent_from_observation"] for e in selected),
                         "fallbacks": sum(e["decision_source"] == "fallback" for e in selected),
                         "llm_errors": summary["llm_errors"], "parse_errors": summary["parse_errors"],
                         "length_finishes": sum(e["finish_reason"] == "length" for e in selected),
                         "median_response_seconds": statistics.median(latencies),
                         "p95_response_seconds": percentile(latencies, .95),
                         "sum_response_seconds": sum(latencies), "run_wall_seconds": entry["wall_seconds"],
                         "prompt_tokens": (sum(e["prompt_tokens"] for e in selected)
                                           if all(e["prompt_tokens"] is not None for e in selected) else None),
                         "completion_tokens": (sum(e["completion_tokens"] for e in selected)
                                               if all(e["completion_tokens"] is not None for e in selected) else None),
                         "completion_tokens_available": sum(e["completion_tokens"] is not None for e in selected),
                         "over_400_tokens": sum(e["completion_tokens"] is not None and e["completion_tokens"] > 400 for e in selected),
                         "nonlatin_script_responses": sum(e["field"] == "raw_response" and e["arm"] == arm and e["seed"] == seed for e in language),
                         "run": str(path.relative_to(output))})
            for agent in run["logs"][-1]["agents"]:
                choices = [e for e in selected if e["agent_id"] == agent["id"]]
                agents.append({"arm": arm, "seed": seed, "agent_id": agent["id"], "alive": agent["alive"],
                               "energy": agent["energy"], "death_step": agent["death_step"],
                               "decisions": len(choices), "attacks_attempted": sum(e["kind"] == "attack" for e in choices),
                               "attacks_executed": sum(e["executed_action"].startswith("Attack:") for e in choices),
                               "shares_executed": sum(e["executed_action"].startswith("Share:") for e in choices),
                               "food_collected": sum(e["collected"] for e in choices) // 50,
                               "unique_messages": len(set(e["message"] for e in choices)),
                               "rejected": sum(e["action_status"] == "rejected" for e in choices)})
    pairs = []
    for seed in manifest["seeds"]:
        a, b = [runs[arm, seed] for arm in manifest["arms"]]
        initial_match = all(a["logs"][0][key] == b["logs"][0][key] for key in ("agents", "environment", "summary"))
        first_prompts_match = [(e["system_prompt"], e["user_prompt"]) for e in a["logs"][1]["events"]] == [
            (e["system_prompt"], e["user_prompt"]) for e in b["logs"][1]["events"]]
        assert initial_match and first_prompts_match
        pairs.append({"seed": seed, "initial_snapshot_matches": initial_match, "first_step_prompts_match": first_prompts_match})
    analysis = output / "analysis"
    analysis.mkdir(exist_ok=True)
    csv_write(analysis / "runs.csv", rows)
    csv_write(analysis / "agents.csv", agents)
    csv_write(analysis / "events.csv", events)
    csv_write(analysis / "language-candidates.csv", language,
              ["arm", "seed", "step", "agent_id", "field", "scripts", "text", "source"])
    write_json(analysis / "pair-validation.json", pairs)
    aggregate = {}
    for arm in manifest["arms"]:
        selected = [e for e in events if e["arm"] == arm]
        subset = [r for r in rows if r["arm"] == arm]
        aggregate[arm] = {"runs": len(subset), "decisions": len(selected),
                          "final_survivors": [r["alive"] for r in subset],
                          "median_response_seconds": statistics.median(e["response_seconds"] for e in selected),
                          "p95_response_seconds": percentile([e["response_seconds"] for e in selected], .95),
                          "sum_response_seconds": sum(e["response_seconds"] for e in selected),
                          "mean_response_characters": statistics.mean(e["response_characters"] for e in selected),
                          "first_step_median_response_seconds": statistics.median(e["response_seconds"] for e in selected if e["step"] == 1),
                          "first_step_mean_response_characters": statistics.mean(e["response_characters"] for e in selected if e["step"] == 1),
                          "action_requests": dict(Counter(e["kind"] for e in selected)),
                          "action_executions": dict(Counter(e["executed_action"].split(":")[0].split(" (")[0] for e in selected)),
                          "rejection_reasons": dict(Counter(e["reason"] for e in selected if e["action_status"] == "rejected")),
                          "repair_rules": dict(Counter(rule for e in selected for rule in e["repair_rules"].split(";") if rule)),
                          "most_common_messages": Counter(e["message"] for e in selected if e["message"]).most_common(10),
                          "nonlatin_script_responses": sum(e["field"] == "raw_response" and e["arm"] == arm for e in language),
                          "reasoning_content_present": sum(e["reasoning_content_present"] for e in selected)}
    write_json(analysis / "summary.json", aggregate)
    plot_results(analysis / "comparison.png", manifest, runs, rows)
    write_json(analysis / "analysis-provenance.json", {"script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "language_method": "Script-range screening only; candidates need human reading to distinguish Chinese, Japanese, and other languages. ASCII English is not automatically identified.",
               "percentiles": "Linear interpolation over pooled per-request wall times; model loading excluded",
               "validated": ["six completed runs", "initial worlds", "first step prompts", "source hashes", "all request/response to event matches", "generation controls", "server restored"]})
    print(json.dumps({"runs": rows, "summary": aggregate}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    analyze(parser.parse_args().output.resolve())
