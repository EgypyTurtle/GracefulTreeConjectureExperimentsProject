#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
checkpoint="${1:?usage: bash run_checkpoint.sh CHECKPOINT [THREADS] [SECONDS]}"
threads="${2:-8}"
seconds="${3:-0}"
read -r version k depth limit audit < "$checkpoint/tasks.txt"
if [[ "$version" != eg-v2.1 ]]; then
  echo "Unsupported checkpoint version: $version" >&2
  exit 2
fi
make out/eg_search
mkdir -p logs
args=(--k "$k" --threads "$threads" --split-depth "$depth"
      --task-limit "$limit" --checkpoint "$checkpoint" --time-limit "$seconds" --progress 10)
if [[ "$audit" == 1 ]]; then args+=(--audit); fi
log="logs/k${k}_refined_$(date +%Y%m%d_%H%M%S)_$$.log"
echo "log=$log checkpoint=$checkpoint threads=$threads time_limit=$seconds"
/usr/bin/time -v ./out/eg_search "${args[@]}" 2>&1 | tee "$log"
