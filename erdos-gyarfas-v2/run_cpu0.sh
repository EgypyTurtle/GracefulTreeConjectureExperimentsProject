#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
worker=0
if [[ "${1:-}" == --worker ]]; then worker=1; shift; fi
k="${1:-15}"
if [[ ! "$k" =~ ^[0-9]+$ ]] || (( k < 3 || k > 10000 )); then
  echo 'usage: bash run_cpu0.sh [K]' >&2
  exit 2
fi
command -v taskset >/dev/null
[[ -x out/eg_search ]] || { echo 'Build out/eg_search first.' >&2; exit 2; }
python3 - <<'PY'
import os
import subprocess
mapping = {}
for line in subprocess.check_output(['lscpu', '-p=CPU,SOCKET'], text=True).splitlines():
    if line and not line.startswith('#'):
        cpu, socket = map(int, line.split(','))
        mapping[cpu] = socket
required = set(range(16))
if any(mapping.get(cpu) != 0 for cpu in required):
    raise SystemExit('STOP: logical CPUs 0-15 are not all on socket 0.')
if not required.issubset(os.sched_getaffinity(0)):
    raise SystemExit('STOP: logical CPUs 0-15 are not all available.')
for cpu in required:
    path = '/sys/devices/system/cpu/cpu%d/online' % cpu
    if os.path.exists(path):
        with open(path) as stream:
            if stream.read().strip() != '1':
                raise SystemExit('STOP: CPU %d is offline.' % cpu)
PY
session="eg-k${k}-cpu0"
checkpoint="checkpoints/k${k}-d5-cpu0"
depth=5
limit=200000
audit=0
if [[ -f "$checkpoint/tasks.txt" ]]; then
  read -r version saved_k depth limit audit < "$checkpoint/tasks.txt"
  if [[ "$version" != eg-v2.1 || "$saved_k" != "$k" ]]; then
    echo 'STOP: incompatible existing checkpoint; no files overwritten.' >&2
    exit 2
  fi
fi
if (( worker == 0 )); then
  command -v tmux >/dev/null
  if tmux has-session -t "=$session" 2>/dev/null; then
    echo "Session already exists; inspect it: tmux attach -t $session"
    exit 0
  fi
  printf -v launch 'bash %q --worker %q' "$PWD/run_cpu0.sh" "$k"
  tmux new-session -d -s "$session" -c "$PWD" "$launch"
  echo "Started $session. Progress: tmux attach -t $session"
  exit 0
fi
mkdir -p logs
log="logs/k${k}_cpu0_$(date +%Y%m%d_%H%M%S)_$$.log"
args=(--k "$k" --threads 16 --split-depth "$depth" --task-limit "$limit"
      --checkpoint "$checkpoint" --progress 10)
if [[ "$audit" == 1 ]]; then args+=(--audit); fi
set +e
{
  echo "started_utc=$(date -u +%FT%TZ) cpus=0-15 threads=16 checkpoint=$checkpoint"
  sha256sum search.cpp out/eg_search
  taskset -c 0-15 bash -c 'grep "^Cpus_allowed_list:" /proc/self/status'
  taskset -c 0-15 /usr/bin/time -v ./out/eg_search "${args[@]}"
} 2>&1 | tee "$log"
status=${PIPESTATUS[0]}
set -e
echo "search_exit=$status log=$log"
if (( status == 0 )); then
  echo 'Completed this k only. Do not start the next k automatically.'
else
  echo 'Inspect the log. Only finished prefix tasks are saved; unfinished DFS work is not.'
fi
echo 'Press Enter to close this tmux session.'
read -r _ || true
exit "$status"
