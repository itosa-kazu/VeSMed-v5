# 实验结果证据索引

本目录采用**保留旧证据、以新 run 纠正旧 run**的方式管理结果。不同版本不能混用：`PASS`、`HONEST_UNSUPPORTED`、`FAIL` 只对该次冻结的 workload、runner、候选代码和执行边界成立，不能直接解释为临床有效性或候选的全局优劣。

## 1. 各产物的证据地位

| 产物 | 证据地位 | 可以支持 | 不能支持 |
|---|---|---|---|
| [`20260713T200000Z-panel-v1/`](20260713T200000Z-panel-v1/) | **pre-red-team 失败基线；不得用于排名** | 记录首轮 runner 如何产生结果，并作为红队问题的可追溯复现材料 | 任何候选胜负、Pareto 次序或核心架构选择；其 oracle 隔离、semantic eligibility、轨迹覆盖与若干 fixture 区分力均不足 |
| [`20260713T115159Z-panel-v2/`](20260713T115159Z-panel-v2/) | **中间诊断证据；不得作为最终决策面板** | 证明大部分首轮 harness 修复已进入隔离运行，并暴露剩余缺口 | 最终候选比较；`T35` 当时只有数值 diagnostics 门，缺少独立的递推值/完整时域 hard oracle；此外，已知宿主绝对路径仍可能绕过临时目录隔离读取 oracle（direct-path confinement 缺口） |
| [`20260713T120910Z-panel-v3/`](20260713T120910Z-panel-v3/) | **decision-grade，但仅限已声明范围的隔离面板** | 在冻结的 50 个 T workload、8 个 E workload、5 个实现及 native/companion 矩阵内，比较行为完成度、诚实拒绝和失败边界；支持本研究的有范围架构决策 | 未测语义、敌意 native code、OS 级安全、临床准确性、患者获益、监管合规或真实部署安全 |
| [`metrics-current.json`](metrics-current.json) | **v3 最终加固前的静态计量基线** | 为差分提供固定 core、harness、前三个扩展包、LOC/AST、manifest 原语和反测试分派扫描快照 | 前三个扩展从零写入时的 authoring diff、运行时正确性、可维护性总分、临床正确性 |
| [`metrics-final.json`](metrics-final.json) | **最终静态计量快照** | 审计最终源码规模、显式原语、自报边界、文件哈希和静态反特例扫描 | 证明不存在所有硬编码、证明原语最小、证明临床或形式正确 |
| [`metrics-final-vs-current.json`](metrics-final-vs-current.json) | **最终相对基线的差分证据** | 显示 fixed-core added/modified/removed 均为 `0`、harness 修改 `5` 个文件、第四个 test-method extension 新增 `1` 个文件 | 前三个扩展的 authoring diff、泛化到未纳入指纹的文件，或证明任何候选是全局最优 |

三个 metrics 报告内置的 `report_sha256` 分别为：

- `metrics-current.json`: `07299afbe93212f05ea3a5b4b9bf077cdb45c40b8295abc68fbdbbdadf4bbe57`
- `metrics-final.json`: `8ff17a7aebd57cbcd060d3262318ace02c7b70273db7b1101bcc0ae1e64165cf`
- `metrics-final-vs-current.json`: `701bf2048bd02d2199997c2b005b8a9e0b2cb5f5fd1c6c9965f0f03c3720de09`

## 2. v3 冻结结果

v3 共运行 8 个 candidate-track 面板，每个面板 58 个 workload（`T01–T50` + `E01–E08`），合计 **464 个隔离 workload 执行**。所有原始 run 的 `harness_errors` 都为空：**0 / 464 harness errors**。

下表中的顺序均为 `PASS / HONEST_UNSUPPORTED / FAIL`。`HONEST_UNSUPPORTED` 表示边界表达合格但未完成该 workload，**不等同于 PASS**。

| candidate-track | 总计（58） | T 分面（50） | E 分面（8） |
|---|---:|---:|---:|
| `tel-native` | `36 / 20 / 2` | `36 / 12 / 2` | `0 / 8 / 0` |
| `tel-companion` | `36 / 20 / 2` | `36 / 12 / 2` | `0 / 8 / 0` |
| `causal-native` | `3 / 53 / 2` | `3 / 45 / 2` | `0 / 8 / 0` |
| `causal-companion` | `3 / 53 / 2` | `3 / 45 / 2` | `0 / 8 / 0` |
| `rewrite-native` | `31 / 23 / 4` | `31 / 15 / 4` | `0 / 8 / 0` |
| `rewrite-companion` | `31 / 23 / 4` | `31 / 15 / 4` | `0 / 8 / 0` |
| `kernel-native` | `36 / 20 / 2` | `36 / 12 / 2` | `0 / 8 / 0` |
| `model-native` | `13 / 44 / 1` | `5 / 44 / 1` | `8 / 0 / 0` |

`kernel` 与 `model` 没有 companion 行：companion ablation 只对三个 atomic candidates 定义；该非适用项已显式记录在 [`summary.json`](20260713T120910Z-panel-v3/summary.json) 的 `skipped_non_applicable` 中。不能把跨家族原始 PASS 数当成单一总分：T 与 E 有不同语义覆盖，原子候选的诚实拒绝也是架构边界证据。

### v3 相对 v2 的决定性修复

1. `T35` 增加独立 hard oracle `reference.closed_recurrence@1`，同时检查 25 个坐标、24 小时时域、目标轴与递推值；仅返回 seed/error diagnostics 已不能通过。
2. 隔离协议升级为 `vesmed-isolated-candidate/3`：每个 workload 使用 fresh `python -I -S`，候选 stdin 只有 `candidate_view`，oracle 只在父进程判断；CPython audit hook 将读取限制在临时 sandbox/runtime allowlist，并禁止 subprocess、network 和 native loader。
3. v3 的 `benchmark_code` 冻结哈希为 `sha256:8f09db4022bb1e2a74991c598d0a344aa7212ddcc2f61db1a2f45fe6dd8e7c4b`。所有候选代码、workload 文件、逐 workload candidate/oracle view、`FORMAL_SPEC.md` 与 `REQUIREMENTS.md` 的哈希都在 metadata 中逐项保存。

## 3. 从哪里复查

- [`20260713T120910Z-panel-v3/summary.json`](20260713T120910Z-panel-v3/summary.json)：8 个面板的聚合 classification 和五条 verdict axis 计数。
- [`20260713T120910Z-panel-v3/metadata.json`](20260713T120910Z-panel-v3/metadata.json)：执行协议、Python/平台、dirty Git 状态、选择矩阵、seed、超时，以及 benchmark/candidate/workload/candidate-view/oracle-view/spec/requirements 哈希。该 run 的 Git 工作树为 dirty，因此**不能只靠 commit id 重建**，必须同时核对这些文件级/集合级哈希。
- `20260713T120910Z-panel-v3/<candidate>-<track>.json`：每个 workload 的调用 transcript、输入 digest、捕获值、断言、oracle 诊断、manifest snapshot、verdict 与 `harness_errors`。
- [`metrics-final.json`](metrics-final.json)：最终静态快照；[`metrics-final-vs-current.json`](metrics-final-vs-current.json)：固定 core、harness 与新增第四个 extension 的差分。

## 4. 复现命令

在仓库根目录运行。必须使用新的 run id；不要试图覆盖已有冻结目录。

```powershell
$runId = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ") + "-panel-v3-repro"
python -m prototype.experiment --output-root results --run-id $runId
python -m pytest -q
```

重新生成静态计量时也使用新文件名；第二条命令以已冻结的加固前快照为 baseline：

```powershell
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
python -m prototype.metrics --output "results/metrics-$stamp.json"
python -m prototype.metrics --baseline results/metrics-current.json --output "results/metrics-$stamp-vs-current.json"
```

复现后应比较新 `metadata.json` 中的 `hashes`，而不是只比较汇总计数；源码或 workload 改变时，相同计数也不是同一证据。

## 5. 不可覆盖与边界说明

### 应用层 append-only

实验 writer 先写同盘 staging 目录，再原子 rename；目标 run id 已存在时拒绝发布。metrics writer 默认也拒绝覆盖现有文件。因此 v1、v2、v3 被并列保留，而不是用“修正后结果”回写历史。不要对冻结证据使用 `--force`。

这不是文件系统 WORM，也没有外部时间戳或数字签名：拥有写权限的人仍可手工修改文件。完整性依赖保存的 SHA-256、Git 状态摘要、审查流程和外部归档；因此任何移动/复制后的证据都应重新核对 hash。

### 不是 OS sandbox

v3 是针对**已审计、纯 Python 候选**的进程隔离与 CPython audit-hook confinement，不是容器、虚拟机或操作系统安全沙箱。它用于降低候选读取 oracle、测试文件、结果文件和宿主资源的机会；不能承诺抵抗 native extension、解释器漏洞、内核攻击或有宿主权限的恶意代码。

### 不是临床验证

这些 workload 是架构语义与计算契约测试，不是患者队列、真实世界外部验证、前瞻性试验或医疗器械验证。结果只能用于本仓库的架构选择与失败边界审计，不能据此声称诊断/治疗有效、安全或可临床部署。
