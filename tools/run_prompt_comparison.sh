#!/usr/bin/env bash
# Orchestrate the existing CLI only. No server start, stop, switch, or polling.
set -euo pipefail

task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"

mode="${1:-preview}"
case "$mode" in
  preview|mock|full)
    conditions=(baseline provenance relative_coordinates action_outcomes action_last grounded_thought spatial_relations combined spatial_combined)
    seeds=(42 43 44)
    steps=30
    ;;
  smoke|pilot)
    conditions=(baseline spatial_relations)
    seeds=(42)
    steps=30
    ;;
  *)
    printf 'Usage: bash tools/run_prompt_comparison.sh [preview|mock|smoke|pilot|full] [NEW_OUTPUT_DIRECTORY]\n' >&2
    exit 2
    ;;
esac
if [[ "$#" -gt 2 ]]; then
  printf 'Expected a mode and optional new output directory.\n' >&2
  exit 2
fi
[[ "$mode" != smoke ]] || steps=1
[[ "$mode" != mock ]] || steps=2

output="${2:-outputs/prompt-comparison/$(date -u +%Y%m%dT%H%M%SZ)-${mode}-$$}"
mkdir -p -- "$(dirname -- "$output")"
mkdir -- "$output"  # Refuse to overwrite any previous preparation or run.
output="$(cd -- "$output" && pwd)"
mkdir -- "$output/logs" "$output/previews"
printf 'sequence\tcondition\tseed\tsteps\tmode\n' > "$output/plan.tsv"
git rev-parse HEAD > "$output/source-commit.txt"
shasum -a 256 main.py paper_prompts.py observations.py response_fields.py llm_api.py \
  run_data.py model_identity.py app_presets.py tools/run_prompt_comparison.sh > "$output/source-sha256.txt"

common=(run --base-url http://127.0.0.1:8080/v1 --model "${SUGARSCAPE_MODEL:-default_model}"
  --agents 4 --steps "$steps" --runs 1 --grid-size 15 --no-mbti --world-prompt ""
  --initial-energy 20 --child-initial-energy 20 --reproduce-cost 70 --population-cap 4
  --spawn-energy-count 2 --num-clusters 2 --cluster-radius 0 --energy-spawn-rate 0
  --view-range 3 --message-range 7 --temperature 0 --top-p 1 --max-tokens 5000 --timeout 120
  --send-temperature --send-top-p --reasoning-mode off --reasoning-format chat_template
  --max-tokens-parameter max_tokens --output "$output/runs")
sequence=0
for seed in "${seeds[@]}"; do
  for condition in "${conditions[@]}"; do
    factors=()
    case "$condition" in
      baseline) ;;
      combined)
        factors=(provenance relative_coordinates action_outcomes action_last grounded_thought)
        ;;
      spatial_combined)
        factors=(provenance action_outcomes action_last grounded_thought spatial_relations)
        ;;
      *) factors=("$condition") ;;
    esac
    args=("${common[@]}" --seed "$seed")
    for factor in "${factors[@]}"; do
      args+=(--prompt-factor "$factor")
    done
    if [[ "$mode" == preview ]]; then
      args+=(--preview-prompts "$output/previews/${seed}-${condition}.json")
    elif [[ "$mode" == mock ]]; then
      args+=(--mock)
    fi
    sequence=$((sequence + 1))
    printf '%s\t%s\t%s\t%s\t%s\n' "$sequence" "$condition" "$seed" "$steps" "$mode" >> "$output/plan.tsv"
    shasum -a 256 -c "$output/source-sha256.txt" > /dev/null
    printf '[%s] %s / seed %s / %s\n' "$sequence" "$condition" "$seed" "$mode"
    MPLCONFIGDIR="$task_root/.mplconfig" "$task_root/.venv/bin/python" main.py "${args[@]}" \
      2>&1 | tee "$output/logs/${seed}-${condition}.log"
  done
done
if [[ "$mode" != preview ]]; then
  MPLCONFIGDIR="$task_root/.mplconfig" "$task_root/.venv/bin/python" main.py aggregate --input "$output/runs"
fi
printf 'Finished %s: %s\n' "$mode" "$output"
