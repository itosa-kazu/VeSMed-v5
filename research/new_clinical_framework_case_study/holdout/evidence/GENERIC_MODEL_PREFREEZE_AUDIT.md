# Generic Model Pack 独立审计（case-blind，临时证据）

审计时间：`2026-07-20T17:57:05+09:00`  
审计对象：`adult-icu-acute-hemodynamic-collapse-generic-v1`  
对象快照：`model_pack.json sha256=17ee2d86173d2b8a99dfa3f3897abae67459fb3fa0b545fce8167810be48331b`  
结论：**`NOT_READY_FOR_GENERIC_MODEL_FREEZE`**

## 1. Outcome

这个 pack 已经证明了若干重要的**结构可执行性**：当前 case-blind RuntimeV2 能加载 12 个
非互斥 process，枚举 `2^13 = 8192` 个 known-process + `U` 联合假说；可靠阴性会产生反向
更新；同源复制不重复改变后验；topology ablation 会改变推断；unmapped observation 会提高
mapping gap 和 unmodelled-process posterior。

但它尚不能进入 pre-primary holdout freeze。阻断原因不是“没有临床校准”——临床校准本来
就在本实验范围外——而是：**冻结架构要求的若干结构仍未由 model pack 明确承载，且当前
machine validation 本身仍标记为 pending/draft。** 具体为：

1. model 中没有显式的 mode-transition guard / hysteresis 合同；
2. broad observation scope 与实际 typed observation catalog 不相称，缺 numeric measurement、
   measurement/method condition、support/treatment masking 等生成因子；
3. 已声明感染证据和 infectious-source-control action，却没有独立的 infectious burden/source
   active process，导致上游驱动与下游 vasoplegia 被折叠；
4. 少量 observation concept 仍是复合化验 pattern 或过度泛化的 assay 占位符，不满足最严格
   的 diagnosis-neutral 原子事实要求；
5. `model_validation.json` 明确为 `PENDING_RUNTIME_V2_1_FREEZE / DRAFT_NOT_SEALED`。

因此，当前正确结论是：

```text
STRUCTURAL_RUNTIME_COMPATIBILITY = PASS_ON_NONFINAL_RUNTIME
NON_SIMPLEX_FACTORIAL_STATE      = PASS
SIGNED_FACTOR_BEHAVIOR           = PASS
TOPOLOGY_CONNECTED_TO_RUNTIME    = PASS
OOD_RESIDUAL_RESPONSE             = PASS
FULL_FROZEN_SCOPE_COVERAGE        = FAIL
MODE_GUARD_HYSTERESIS_COMPLETENESS = FAIL
MODEL_FREEZE_READINESS            = FAIL
CLINICAL_VALIDITY                 = NOT_CLAIMED / NOT_TESTED
```

## 2. Blindness boundary

本审计只读取：

- `ARCHITECTURE_FINAL_v1.md`；
- Runtime v2 的 public README/DESIGN/API/schema contract；
- `holdout/generic_model` 的 `MODEL_SCOPE.md`、`MODEL_CARD.md`、`model_pack.json`、
  `model_validation.json`；
- `PERFECT_LANDING_GATES.md/.json`。

没有读取 `CASE_SELECTION`、任何 `cases/`、文章、event ledger、病例 concept map、replay 或旧病例
输出。所有运行验证使用人工构造的 neutral structural probes；没有医学 holdout 内容。

## 3. Artifact snapshot

| artifact | sha256 |
|---|---|
| `ARCHITECTURE_FINAL_v1.md` | `d83b910f3cd32c777f126b245c2652e88fccb31aaa125b455f4c5af90cc4575c` |
| `runtime_v2/README.md` | `50febf192adb38c52e63150f86921d724ccb27f581b8a12153e15f4b9a25c8bf` |
| `runtime_v2/DESIGN.md` | `04b989e0decbefde60b8e6a948b60110446a00babb4c6780910c2e93691953e3` |
| `generic_model/MODEL_SCOPE.md` | `4b8bfd2769741cafe18ad30024ae8647280ff94b986b153cd360bc8dcc52deab` |
| `generic_model/MODEL_CARD.md` | `568eb59184e2f05d837bc8990fe37c9c65910aaca0e8b15ff8821207d4920ffb` |
| `generic_model/model_pack.json` | `17ee2d86173d2b8a99dfa3f3897abae67459fb3fa0b545fce8167810be48331b` |
| `generic_model/model_validation.json` | `89f6292a6acdd470be1b430f788c94b93333813651cbafb5479a175355180eb3` |
| `PERFECT_LANDING_GATES.md` | `8d32096bd12b5e11b850776cff152d0acd54304e430a4dfd258eda6aeea84935` |
| `PERFECT_LANDING_GATES.json` | `a00b963fd090d4accb304b343075661a5bfd6ecf2fc8371843a0a974e9fe3798` |

本文件只适用于上述 model pack 快照；model pack 改动后必须重新审计，不能把本结论沿用到新
digest。

## 4. 结构清点

模型静态引用完整性检查没有发现 dangling reference：

| object | count / result |
|---|---:|
| concurrent known processes | 12 |
| process-local coordinates | 25 |
| typed observation concepts | 46 |
| action classes | 13 |
| process-coordinate couplings | 20 |
| mode couplings | 9 |
| coactivation interactions | 10 |
| directed topology edges | 23 |
| planning bridges | 11 |
| per-process mode priors sum to 1 | PASS (12/12) |
| mode drift covers every local coordinate | PASS (12/12) |
| observation/process/coordinate/action references valid | PASS |
| categorical likelihood vectors normalize | PASS |

### 4.1 非互斥 factorial state：PASS

12 个 activation prior 的和为 `1.4`，本身就不是 disease simplex。当前 RuntimeV2 初始化得到：

```text
joint hypotheses = 8192 = 2^(12 known processes + U)
local state blocks = 12
```

在同时输入 hypotension、severe ventricular dysfunction、pulmonary edema、AKI、
tachyarrhythmia 五项 neutral synthetic evidence 后：

```text
sum(12 known-process marginals) = 5.828359524852098
P_PUMP_FAILURE = 0.984539
P_ARRHYTHMIA   = 0.809177
P_AKI          = 0.674038
P_VASOPLEGIA   = 0.538548
P_RESP_FAILURE = 0.458503
```

多个 process 可以同时处于高后验，未被归一到和为 1，符合 concurrent/factorial contract。

### 4.2 signed negative evidence：PASS

neutral probe 中：

```text
P(P_PUMP_FAILURE | no evidence)                         = 0.2092844408
P(P_PUMP_FAILURE | normal left filling pressure=true)  = 0.0491348277
P(P_PUMP_FAILURE | elevated left filling pressure=true)= 0.5322459768
```

可靠正常结果能反向更新，而不是“所有 observation 只能加分”。

### 4.3 same-source deduplication：PASS（posterior semantics）

同一 `source_result_id` 的 pulmonary-edema factor 投递一次与通过不同 event id 复制投递两次，
process marginals 最大差为 `0.0`，factor message 仍只有一个 source result。两份 state hash 不同是
因为 event lineage 正确记录了第二次递送，而不是后验被重复增强；这不构成重复计分。

### 4.4 topology runtime connection：PASS（integration only）

对 regional-wall-motion neutral probe，将 topology 的 inference/planning coupling 置零后，最大
known-process marginal 变化为 `0.0172372272`。这证明 topology 不是纯可视化字段；不证明边长
或传播强度医学正确。

### 4.5 OOD residual response：PASS（structural only）

加入一个未映射 neutral observation 后：

```text
mapping_gap:                0.50 -> 0.6666666667
unmodeled_process posterior:0.24 -> 0.3934866712
unexplained_observations:   []   -> explicit unmapped record
```

unknown 不是固定低常数。它仍是 toy posterior，不是临床 OOD 概率。

## 5. Blocking findings

### F1 — HIGH — 没有显式 mode guard / hysteresis

`ARCHITECTURE_FINAL_v1.md` §6 与 G08 要求 mode jump 由显式 guard、事件或 hazard 驱动，并支持
hysteresis。当前 process mode 只声明：

```text
mode_id + prior + coordinate_drift
```

`mode_couplings` 只给 target mode 一个方向性的 log potential。模型没有 `enter_guard`、
`exit_guard`、guard evidence、进入/退出不同阈值、transition hazard 或可审计 hysteresis 参数。
所以 mode 已经不是单纯一列全局严重度——每个 process 确有独立 posterior 和不同 drift——但
**mode transition contract 不完整**。不能用“runtime 可能在别处默认处理”替代 model 层的冻结
语义。

影响：`PL-MODE-002` 的 same-coordinate/different-mode + guard/hysteresis 不能仅靠当前 pack
得到决定性证明。

### F2 — HIGH — 冻结 observation scope 大于实际 typed catalog

`MODEL_SCOPE.md` 把 `O` 描述为床旁血流动力学、心电、超声/影像、常规/定向实验室、动态探针、
器官功能和序列趋势。但 pack 的 46 个 observation 全部是 boolean/categorical；没有：

- 数值测量及单位/参考域（如 blood pressure、heart rate、LVEF、creatinine、oxygenation）；
- measurement method / reliability / sensitivity / sampling condition；
- oxygen/ventilator/vasopressor/mechanical-support 条件下的 emission；
- treatment masking、censoring 或 MNAR factor；
- observation-level lag/availability validity window。

这不是“参数还没校准”，而是当前 model contract 没有保存这些生成条件。若 mapper 把所有原始
数值预先压成 `marked/moderate/normal` 或 boolean，必须冻结并审计该 mapping；否则 clinically
consequential magnitudes 会被静默有损压缩。未覆盖事实当然可以进入 OOD，但那只证明开放世界
诚实，不能证明 model 已“覆盖 broad scope”。

影响：`PL-FACT-001`、`PL-SUPPORT-001`、`PL-CASE-001` 在 real replay 中可能因模型内容而失败。

### F3 — HIGH — infectious driver 被折叠进 downstream vasoplegia

模型包含：

```text
microbiologically_confirmed_infection_presence
anatomically_localized_infectious_source_presence
ACTION_INFECTIOUS_SOURCE_CONTROL
```

但 12 个 active process 中没有 infectious burden/source process。上述事实只更新
`P_VASOPLEGIA` / `P_RESP_FAILURE`，source control 只降低 vasoplegia 的
`inflammatory_endothelial_activation` coordinate。

因此，下列两个世界可能在 pack 中碰撞：

```text
A: infectious source/burden 仍活跃，但外部支持暂时纠正 vascular tone
B: 无持续 infectious driver，只有正在恢复的 downstream vasoplegia
```

两者对“继续/停止 source control 或针对病原驱动的动作”可能不同。把上游可持续过程和下游
失效模式合成一个 process，与 active-process 架构的可组合性不完全一致。`U` 可以诚实表示缺口，
但不能宣称已覆盖这一 common critical driver。

### F4 — MEDIUM — 少量 observation 仍不是最小诊断中立原子

多数 concept id 是诊断中立事实，未把疾病名写入普通 observation，这是明显优点。但以下项仍
需拆分或严格限定：

- `elevated_tsh_with_low_free_t4_presence`：两项实验室测量的复合 pattern；
- `suppressed_tsh_with_elevated_thyroid_hormone_presence`：同类复合 pattern；
- `specific_toxicologic_assay_positive`：未保存 assay/agent identity，无法支持不同毒物作用；
- `stress_distribution_wall_motion_pattern_presence`：解释性影像 pattern，若与原始 regional wall
  motion facts 同源，必须共享 source identity，且不应被当作独立票。

这并不等于它们带有疾病标签；问题是原子性、可追溯性与未来动作响应所需信息是否被保存。

### F5 — MEDIUM — action set 是明确的窄集合，不是 broad treatment coverage

13 个 action class 的 lifecycle/identifiability 字段完整，且所有患者级 action counterfactual 标为
`UNIDENTIFIABLE`，这一点正确。但 `P_MYOCARDIAL_ISCHEMIA` 和 `P_NEURO_DYSFUNCTION` 没有
direct action；没有 revascularization、neuro-specific rescue 等动作。只要 `A` 明确冻结为当前
13 类，这不是内部引用错误；但报告必须称为**窄 action scope**，不能称为“成人 ICU 急性
崩溃的完整动作集合”。

### F6 — HIGH — 当前 validation/seal 明确未完成

`model_validation.json` 当前写明：

```text
runtime_target          = runtime_v2.1_pending_freeze
status                  = PENDING_RUNTIME_V2_1_FREEZE
structural_claim_status = DRAFT_NOT_SEALED
tests                   = []
```

无论静态审计结果如何，这本身足以阻止进入 pre-primary holdout seal。

## 6. Parameter precision and identifiability

### 6.1 没有把 toy decimals 宣称成临床精度：PASS_WITH_CONDITION

activation priors、likelihood-shaped weights、mode drift、couplings、action deltas、objective、
thresholds 均带 `expert_elicited_ordinal_toy_not_calibrated` 或等价语义；MODEL_CARD 逐类禁止把
它们解释为患病率、敏感度/特异度、临床速率、因果效应或治疗推荐。action rollout/plan 默认
`UNIDENTIFIABLE`，自然史数值也明确不识别。

因此当前 pack 没有**未声明的**临床伪精确。但是 runtime 会产生很多长小数 posterior 和 toy
objective；任何 UI/报告如果不同时展示 `NOT_CALIBRATED / UNIDENTIFIABLE`，就会重新制造
伪精确。这个约束必须成为 query-output gate，而不能只藏在 model card。

### 6.2 不能把结构 posterior 称为临床概率

本审计中列出的 `0.98`、`0.67` 等仅证明非 simplex 和 signed-factor 运算，不证明某病理过程
在真实患者中的概率。禁止用这些数值作为临床 readout 成功证据。

## 7. Required disposition before freeze

在不读取任何 holdout 的前提下，model owner 至少应：

1. 明确新增 model-level guard/hysteresis 结构，或收窄 architecture/gate claim；冻结架构不能靠
   文档解释绕过；
2. 将 `O` 收窄为 46 个 typed concepts，或补齐可审计的 numeric/method/support-masking factor；
3. 为 infection/source burden 增加独立 process，或明确将其判为 `U`/scope gap 并删除“已覆盖
   common critical driver”的暗示；
4. 拆分复合 lab pattern，细化 assay identity，明确 echo pattern 的 source dedup；
5. 重新执行 12-process validation、all runtime tests、lifecycle/topology/OOD probes，写入 final
   `model_validation.json` 并 seal；
6. 由本审计路径针对新 digest 重新审计。旧审计不得自动转为 PASS。

## 8. Verification boundary

本审计没有运行任何 real case，也没有验证临床定位、预测或 action choice。即使上述 blocker
全部关闭，最多只可把 model pack 标为 `STRUCTURALLY_SUPPORTED / CASE-BLIND_FROZEN`；是否
能在新的真实病例上“完美落地”，仍必须由 seal 之后的 independent sequential replay 按 30 个
hard gates 判定。
