# 服务器运行说明

新版独立放在 `~/math-search/erdos-gyarfas-v2`，旧仓库和旧日志保留原位。
原程序 k=3～13 已复现，k=13 为 12小时53分23.63秒，无需再跑原程序。

## 上传

把本机的 `erdos-gyarfas-v2.zip` 上传至服务器 `~/math-search/`。
可用平时的 SFTP 工具，也可在本机 PowerShell 执行下面的命令，
其中 `服务器IP` 要替换为实际地址：

```powershell
scp "C:\Users\56257\Documents\GracefulTree\erdos-gyarfas-v2.zip" dell@服务器IP:~/math-search/
```

## 编译和检查

在服务器执行：

```bash
cd ~/math-search
unzip erdos-gyarfas-v2.zip
cd erdos-gyarfas-v2
sha256sum -c SHA256SUMS
make -j4
make test
```

`make test` 包括原程序与新版的完整有效状态数、图摘要交叉检查，
以及真正杀死进程后恢复的测试。应全部显示 PASS。
这里的摘要是回归检查证据，不代替搜索覆盖性的论证。

## 先运行新版 k=13

```bash
tmux new -s eg-v2
```

在新会话执行：

```bash
cd ~/math-search/erdos-gyarfas-v2
bash run.sh 13 32 3
```

参数依次是 k、线程数、实际任务拆分深度。按 Ctrl+B 后松开，再按 D，
即可断开终端；之后用 `tmux attach -t eg-v2` 查看。
日志每 10 秒输出一行已完成任务数、活动任务数和本次耗时，并立即刷新。

## 重启或中断后继续

重新进入 tmux，然后执行完全相同的命令：

```bash
cd ~/math-search/erdos-gyarfas-v2
bash run.sh 13 32 3
```

程序会读取 `checkpoints/k13-d3/`，启动行中的 `reused` 是复用的已完成任务。
只有尚未完成的任务需要重跑；正在运行的单个任务内部没有逐节点断点。
任务清单生成途中若中断，清单生成需要重做。
不要删除检查点目录，也不要同时启动两个进程使用同一个检查点目录。
更改线程数可以继续，更改 k、拆分深度、任务上限或 audit 设置需要换新目录。

## k=14 的一小时试跑

先看新版 k=13 的完成日志和资源使用情况，再执行：

```bash
cd ~/math-search/erdos-gyarfas-v2
set -o pipefail
./out/eg_search --k 14 --threads 32 --split-depth 3 \
  --checkpoint checkpoints/k14-d3 --time-limit 3600 --progress 10 \
  2>&1 | tee "logs/k14_pilot_$(date +%Y%m%d_%H%M%S).log"
```

超时会显示 `incomplete`，已完成任务仍保存。重复同一命令可再给一小时；
去掉 `--time-limit 3600` 则继续不限时搜索。k≥14 是否终止没有保证，
不能把未结束或超时当成反例或验证完成。

## 如何判断结束

- `complete:` 且退出码 0：本次 k 的所有任务已搜索完成。
- `incomplete:`：尚未搜完，可以继续。
- `candidate_found:` 或退出码 100：保存了候选图，需要独立复核。
- 退出码 2：错误，应查看错误信息；不会当作搜索完成。
- 退出码 3：达到时间限制；130：收到中断信号。

最终统计保存在检查点目录的 `summary.txt`。恢复后的状态数包含以往已完成任务；
`seconds_this_run` 仅为当前进程耗时。总时间需要合计各次运行日志。
旧版 `guided` 仅调整分支顺序，未能帮助无反例的完整搜索，因此新版没有沿用。

如出现候选图，执行：

```bash
python3 tools/verify_candidate.py checkpoints/k14-d3/candidate.txt --pk 14
```

## 本机测试的边界

交付前已用 Windows/MinGW 编译执行，并与原实现核对小规模完整搜索。
服务器的 Linux 文件锁、fsync 和编译器仍以服务器上的 `make test` 为准。
本机测速记录在 `tests/local_benchmark.json`，不能直接当作你的 Xeon 服务器速度。

## 已有长任务的细分

一小时内只完成很少几个任务时，不要不断以一小时为限重复启动。
可以将尚未完成的任务再拆一层，保留此前已完成工作的统计贡献：

```bash
make out/eg_refine
python3 tests/test_refine.py
./out/eg_refine --from checkpoints/k14-d4 \
  --to checkpoints/k14-d5-refined --task-limit 200000
```

源检查点目录保留，目标目录必须是一个尚不存在的新目录。
`completed_preserved=6269` 之类的输出表示原有已完成任务的贡献已转入新清单。
目标中的任务单位变了，因此启动时可能显示 `reused=0`，不代表旧工作丢失。
细分的来历记录在目标目录的 `refinement.txt`。

在 tmux 的 shell 中继续，不设置一小时截断：

```bash
bash run_checkpoint.sh checkpoints/k14-d5-refined 8
```

重启后执行相同命令即可恢复目标检查点已完成的任务。
`run_checkpoint.sh` 自动读取目标清单里的拆分深度和任务上限，
避免手工参数与新清单不一致。

细分仍是任务级断点，不能恢复上次未完成任务内部已经消耗的一小时。
也不能保证所有新任务都在一小时内结束。
达到任务上限时，部分父任务会保留；查看输出的 `expanded` 和 `retained`。

本轮服务器报告的已完成任务从6266增长到6269，剩余10426个。
这些任务工作量相差很大，不能按“每小时3个”线性估算总耗时。
