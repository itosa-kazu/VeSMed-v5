# 红队记录与修订账本

> 目的：保留首轮实现被推翻的证据，不删除失败轨迹，不把修复后的结果冒充预注册首轮结果。  
> 首轮冻结结果：`results/20260713T200000Z-panel-v1/`（pre-red-team baseline；不能用于候选排名）。  
> 最终可裁决结果：`results/20260713T120910Z-panel-v3/`（isolated JSON bundle；58 workloads × 8 配置，0 harness errors）。

## 1. 判定原则与威胁模型

- 红队攻击成功优先于 manifest、注释和旧 PASS 数；
- 修复必须是通用合同/不变量，不得按 Txx/Exx 或 expected answer 分支；
- 修复后增加最小回归，并全量重跑；
- 原 fixture/oracle 若错误，保留变更理由和旧结果，不能静默覆盖；
- `HONEST_UNSUPPORTED` 只证明边界，不计 required behavior；
- 当前工作只验证架构语义，不把 synthetic test 叫临床验证。

隔离 runner 的安全声明被有意限制为：**经审计、只使用 Python 的候选代码**。protocol `vesmed-isolated-candidate/3` 使用 fresh `python -I -S`、最小复制 allowlist、candidate-view-only stdin 和 CPython audit hook。它不是 OS sandbox，也不承诺约束任意恶意本机代码、CPython 漏洞、内核攻击或已在解释器内执行的原生机器码。红队退出条件只要求上述有范围的 pure-Python 边界成立；原生码逃逸风险作为 accepted open risk 保留，不能被 `0 harness errors` 洗白。

## 2. Harness 攻击

| ID | 攻击与 live 结果 | 严重度 | 通用修复与自动回归 | 最终状态 |
|---|---|---:|---|---|
| H-01 | 候选用 Python stack inspection 读取同进程 `workload.oracle_view`，无账本也让 T12 PASS | P0 | fresh 独立子进程；worker 仅收 candidate view；judge/reference 不复制进 sandbox/import path；恶意 StackCheat 回归不得 semantic PASS | **已修复** |
| H-02 | `unsupported` 结果携带正确/垃圾 `value`，E01 可被算 semantic PASS | P0 | 所有非 boundary oracle 先做 semantic-eligibility gate；拒绝 payload 不贡献 behavior/numerical PASS | **已修复** |
| H-03 | E04 只返回一个正确轨迹坐标或重复坐标仍 PASS | P0 | 要求 expected coordinates 全覆盖、无重复，记录 coverage/RMSE 后才判定 | **已修复** |
| H-04 | universal refusal 有 15/58 被分类 PASS；空 OK/QueryEcho 也通过大量 hard test | P0/P1 | eligibility gate、正向 liveness/control、schema-aware semantics、外部 fresh replay；对应 malicious fixtures 全部有回归 | **已修复** |
| H-05 | runner 把 `query_kind` 写入候选 diagnostics，替拒绝结果制造 actionable reason | P1 | request metadata 只进 parent `CallRecord`，不改 raw candidate result；回归断言 diagnostics 未被注入 | **已修复** |
| H-06 | CLI 可覆盖旧 JSON；记录缺 run/environment/hash | P1 | 唯一 run directory、`exist_ok=False`；保存 runner/protocol、commit/dirty digest、环境、代码/workload/candidate/oracle hashes 和逐候选 JSON | **已修复**；v1/v2/v3 均保留 |
| H-07 | 即使 import path 隔离，知道宿主绝对路径的候选仍可能直接 `open()` oracle 文件 | P0 | protocol/3 在候选 import 前安装不可移除 audit hook；sandbox 外直接 read 返回 `PermissionError`；同时阻断 subprocess/spawn、network/socket、native loader/`ctypes` 路径和 sandbox 外 mutation；绝对路径 probe 有自动回归 | **范围内已修复**；非 OS sandbox/原生码逃逸仍 accepted open |

## 3. Fixture / oracle 攻击

| ID | 问题 | 影响 | 修复与证据 | 最终状态 |
|---|---|---|---|---|
| F-01 | E01–E08 generic public envelope 未编译成三个原子候选 native IR | 三候选 E 全拒绝，不能据此评价 dynamics | 新建不读 oracle 的 closed `ExperimentalModelSubkernel`；对修订后 E01–E08 为 **8/8 PASS** | **部分修复**；三个原子 adapter 仍开放，不能把 subkernel 成绩归给它们 |
| F-02 | T29/T33 要求 raw ingest 失败 | 偏罚保留 raw/quarantine 的 ledger | 改为 raw round-trip 成功，同时 canonical adaptation/merge 必须 typed fail | **已修复** |
| F-03 | T23/T36/T47 没有真实两版规则，却要求结果不同 | 版本字符串 echo 可投机通过 | fixture 提供真实 v1/v2 模块与显式版本切片 | **已修复** |
| F-04 | T35 唯一 assertion 非 hard，且 unsupported diagnostics 可算 numerical pass | 测试不可 PASS/可假阳性 | hard diagnostics contract + 第二轮 parent-judge closed recurrence oracle；完整 horizon/target/coverage/RMSE | **已修复**（见 3.1） |
| F-05 | T18 允许 `identified` | 不能阻止 post-hoc ergo propter hoc | oracle 只接受 `not_identified`/typed insufficient | **已修复** |
| F-06 | T30 semantic comparator 漏掉 plural proof/claim IDs | TEL 同构语言 false negative | schema-aware identity alpha-normalization；仍保留版本与临床语义差异 | **已修复** |
| F-07 | E01/E04/E06/E07 参考问题仍弱、无参数化盲 holdout | 可能只验证固定输出/单体 ODE | 已补 wiring/trace/full trajectory 与 closed public model，但未由独立作者生成同构/参数 holdout | **开放** |

### 3.1 T35 第二轮修复记录

1. **第一轮**：把 numerical assertion 设为 hard，并要求 seed 与 error-control diagnostics；这堵住了“拒绝也算 numerical PASS”，但 generic trajectory oracle 仍没有把“公开模型输入”和“隐藏期望轨迹”彻底拆开，也不足以证明完整 horizon。
2. **第二轮**：candidate view 只携带公开的 closed linear recurrence IR（state、系数、输入、初值、步长、horizon）；parent judge 通过 `reference.closed_recurrence@1` 独立生成 0–24 小时 **25 个坐标**，检查 target/horizon、100% coverage、重复坐标和 RMSE。`_SparseTrajectory` 与固定数值垃圾均有回归并不能 PASS。
3. **最终解释**：`panel-v3` 中各配置在 T35 都是 `HONEST_UNSUPPORTED`，而不是 numerical PASS。这说明第二轮门禁阻止了伪成功；它**不证明**任何候选的数值 solver、收敛或规模性能。

## 4. 候选运行时攻击

| ID | live 反例 | 严重度 | 通用修复与自动回归 | 最终状态 |
|---|---|---:|---|---|
| C-01 | Rewrite 的 masked artifact 在 `evidence_witness.raw_roots` 泄露敏感 raw payload | P0 | witness 按 information state 脱敏，masked 内容不出 audit envelope | **已修复** |
| C-02 | 自定义 `__deepcopy__`、嵌套 callable、`Expr` 子类越过 closed-data 边界并执行 | P0 | copy/hash/asdict 前 exact-builtin validation；深度/节点/字节预算；exact Expr type | **已修复** |
| C-03 | Causal 在 `valid_at=None` 时消费 future-effective observation | P0 | 默认 target cut 不晚于 as-known；effective/expiry 采用半开资格 | **已修复** |
| C-04 | Rewrite `clean_rebuild` 只复制 survivors，丢失撤回前历史 | P0 | 重放完整 append-only roots+tombstones；任意 cut 与 fresh external replay 比较 | **已修复** |
| C-05 | 同时刻冲突 action 由投递顺序 last-write-wins | P0 | stable action identity；同 scope/time/target 的冲突返回 typed conflict | **已修复** |
| C-06 | later PLAN 可错误关闭 performed effect | P0 | 只有合法 STOP/CANCEL 可关闭；非法 typestate 影响所有相关 query | **已修复** |
| C-07 | 同 scope/time/unit 的 38/39 两值返回 OK、无 conflict | P0 | incompatible exact values 保留 localized conflict，不静默择一 | **已修复** |
| C-08 | knowledge/model/task/guarantees 可被静默忽略 | P0 | 显式消费并记录；不能满足则 typed unsupported/partial，不能伪 OK | **已修复** |
| C-09 | 错误 enum/string 或深 payload 触发未捕获异常 | P1 | 运行时类型验证、有限预算和 typed invalid | **已修复** |

H-01–H-06、F-02–F-06、C-01–C-09 的首轮修复后回归记录为 `117 passed, 7 subtests passed`；加入 H-07 absolute-path probe 后曾为 `118 passed, 7 subtests passed`；加入 test-method extension 后曾为 `119 passed, 7 subtests passed`；再加入 bridge freeze/runner/report 完整性与 B normalized semantic replay 回归后，当前全量结果为 **`135 passed, 7 subtests passed`**。这些数字证明回归集合当前通过，不等于已穷尽攻击空间。

## 5. 阴性证据与不能推出的结论

静态与动态审计未发现：

- 候选源码含 T01–T50/E01–E08、workload ID 或 oracle 分支；
- `eval`、`exec`、`compile`、pickle 或动态 import 作为医学语义；
- 按 fixture concept 增加 expected-answer bonus；
- 三原型的基本区分被推翻：TEL 的时间/撤回、causal 的 see/do/AAP、rewrite 的 grounded roots/typed ports 仍各自成立。

机械扫描对五个实现均报告 test/oracle dispatch sites = 0、static special-case indicators = 0。它只能证明“按扫描定义未发现”，不能证明不存在领域硬编码、共同 oracle 错误、CPython/原生逃逸或未来未知攻击。

## 6. 最终退出条件与实值

Checkpoint 6 按以下**有范围**的条件关闭：

1. H-01–H-07 的 pure-Python threat-model 内攻击均有自动回归；
2. C-01–C-09 已通用修复；F-02–F-06 已修复；F-01 的 model subkernel 路径与原子 adapter 缺口分账；F-07 明确保持开放；
3. 58 个 checked-in workload JSON 与 deterministic builder 一致；
4. 全量测试为 `135 passed, 7 subtests passed`，其中 bridge 专项为 `16 passed`；
5. protocol/3 的 StackCheat 与 absolute-read probe 不能取得 oracle；candidate stdin 不含 runner-only key；
6. `ExperimentalModelSubkernel` 在修订后的 E01–E08 为 8/8 PASS；
7. 最终不可覆盖证据包为 `results/20260713T120910Z-panel-v3/`，共 464 个隔离 run，**0 harness errors**；v1 baseline 与 v2 中间结果仍保留；
8. 最终决策只把 v3 解释为本仓库 synthetic architecture-semantics 证据，不把原子候选的拒绝、model subkernel 的 8/8 或 audit hook 升级成临床/部署/任意恶意代码安全证明。

因此“红队退出”准确含义是：**panel-v3 的五个 audited pure-Python 原型/仪器及其原 panel harness，在冻结攻击/工作负载范围内达到可复查的 L2 证据门槛**。它不覆盖随后已判 `HYPOTHESIS_FAIL` 的 bridge A/B；bridge 轮虽已 seal/reveal，但完整 41-case operational holdout 仍为 `HARNESS_INCOMPLETE`。第二 oracle、独立团队/第二机器、性能曲线、OS 级 sandbox、原生码对抗与临床验证仍未完成。
