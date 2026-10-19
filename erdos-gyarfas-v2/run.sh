#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
k="${1:-13}"
threads="${2:-32}"
depth="${3:-3}"
checkpoint="${4:-checkpoints/k${k}-d${depth}}"
mkdir -p logs
make out/eg_search
log="logs/k${k}_$(date +%Y%m%d_%H%M%S)_$$.log"
echo "log=$log checkpoint=$checkpoint"
# Re-running the same command resumes completed prefix tasks automatically.
/usr/bin/time -v ./out/eg_search --k "$k" --threads "$threads" \
  --split-depth "$depth" --checkpoint "$checkpoint" --progress 10 \
  2>&1 | tee "$log"
