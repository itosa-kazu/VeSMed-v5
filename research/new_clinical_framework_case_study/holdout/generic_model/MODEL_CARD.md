# Model Card — Adult ICU Acute Hemodynamic Collapse Generic Pack

## Outcome

`model_pack.json` 是一个严格 case-blind、面向 Runtime v2 的通用结构模型。它把成人 ICU
急性血流动力学崩溃表示为 **13 个可并发 processes 的 active-process factorial joint +
process-active 条件下的局部 coordinates/modes + typed common-source observation factors +
受控 activation/local hybrid dynamics + active topology + epistemic residuals**。它不是临床
诊断器、校准概率模型或治疗推荐器。

当前模型身份：

- `model_id`: `adult-icu-acute-hemodynamic-collapse-generic-v1`
- `model_version`: `generic-model/1.1.0`
- `architecture_version`: `NCF-ARCH-1.0.0`
- 参数状态：`expert_elicited_ordinal_toy_not_calibrated`

## Key Evidence Machinery

### 1. 非互斥 factorial processes

每个 `Z_i` 都是一个可并发的 activation bit；系统保存所有 known-process bits 与 `U`
（unmodelled process）上的 exact finite factorial joint，以及由它计算出的 process marginals。
pump failure、respiratory failure、AKI、arrhythmia 等可以并发，不会因另一个候选存在而被迫
归零。

这里的 **joint 只指 active-process bits 的 joint**。运行时并不保存
`q(Z, X_1,M_1,...,X_n,M_n)` 的 full-state joint；每个局部 posterior 的解释是
`q(X_i,M_i | Z_i=active)`。实现使用 architecture §17 允许的 variational closure，在所有
包含 `Z_i=active` 的配置中复用同一份局部 conditional。若病例或动作需要配置特异的
`Z↔local/mode` 相关性，当前 pack 必须报 `MODEL_CONTENT_OR_ARCHITECTURE_REFINEMENT`，不能
把 active-process joint 冒充 full-state joint。

### 2. 器官局部坐标与 modes

局部 coordinates 只在对应 process/domain 且该 process active 时有意义。13 个 process 分别
持有自己的条件 mode posterior；不使用一个全局 mode。`mode_couplings` 表达诸如 pump
decompensation 增加 respiratory decompensation tendency 的方向性连接；每个 process 还声明
executable enter/exit thresholds 不同的 mode guard/hysteresis。`process_couplings` 表达坐标到
坐标的 directed drift。所有阈值和转移质量仍是 toy structure。

v1.1 给每个 process 增加 enter/withdraw hazard，并给已有跨 process 机制连接增加 activation
coupling。active-process joint 因而能在无新增 observation 的 forecast/action rollout 中移动，
而不是把初诊 posterior 永久冻结。进入过程按声明 prior 初始化 local/mode；partial exit 只减少
active mass，surviving active conditional 不被重置；接近全退出时保存的 local 值不是 active
patient fact，未来 re-entry 仍按 prior 初始化。模型不声称保存 dormant disease memory。

`P_INFECTIOUS_BURDEN` 是独立上游 process，不等同于下游 vasoplegia；source control 直接作用
于 infectious load/source persistence。低激素支持与 hyperadrenergic/hypermetabolic drive
也是两个独立 process，各自拥有 exact activation bit、coordinates、mode posterior、emissions
和 action targets；模型不依赖 runtime 未授权消费的装饰性 strata。

### 3. Typed signed emissions

49 个 observation concepts 使用 Bernoulli、categorical 或 Gaussian family。active 与 inactive 分布都
显式存在，所以：

- 阳性可以支持或反驳某个 process；
- 可靠阴性可以产生负 LLR；
- `normal_left_sided_cardiac_filling_pressure_presence=true` 对 pump-failure emission 是反向证据；
- `dynamic_preload_responsiveness_presence=true` 支持 volume loss、同时可反驳 congestion-led
  pump failure；
- normal/low/high 等 categorical 结果按同一 typed family 比较；
- MAP、LVEF、P/F ratio、lactate、cortisol、TSH、free T4 和 metanephrine xULN 以带单位
  Gaussian toy likelihood 表达；
- serial trend factors 主要更新 process-local mode，而不伪装成新的病名证据。

40 个同时连接多个 processes 的 observation 使用一张覆盖完整 active-set 的 typed
`joint_likelihoods` 表，作为该原始 finding 的 **一个 common-source factor**；runtime 不再把
同一个 observation 对每个 process 的 emission 独立相乘。v1.1 的 joint table 是 case-blind
equal-weight active-process mixture（Gaussian 用 moment matching），故意不宣称 synergy 或
校准 common-cause magnitude。

这些“概率形状”只编码 evidence ordering 和符号，不是经验敏感度/特异度。
numeric factor 必须满足 method/unit/provenance contract。active support 可能掩盖结果且没有
conditioned factor 时，mapper 必须停止 emission 并提高 measurement uncertainty；同源 qualitative/
numeric alternative 只消费一个表示，censoring/MNAR 不得被强制转成 exact number。
Runtime event v2.1 还要求显式 provenance/source、发生时间区间、采样时间区间、结果时间、
记录时间和可用时间；任一缺失都必须 fail closed，不能由事件顺序暗推。

### 4. Action lifecycle 与 no-new-action

15 个 action classes 均携带 planned→started→active/held→stopped/completed→washout 语义；其中
cause-specific neurologic action 是无 effect 的 typed refusal class。
`NO_NEW_ACTION_CONTINUE_CURRENT` 不是空字段：它继续 local drift、process/mode couplings 与已执行
action 的 residual/washout，但不创建新 exposure。

每个 action 可同时有有利和不利方向，例如 fluid challenge 减少 preload deficit，同时可能
增加 congestion/gas-exchange burden。此结构只证明 runtime 能表达生命周期和方向性机制，不
证明哪种动作适合任何患者。
仅 7 个明确属于 cause/process-removing 的 action class 具有 activation hazard effect；单纯支持
类动作只改变 active-process conditional local state，不得伪装成病理过程已经消失。
myocardial ischemia 有 coronary reperfusion action class；generic neurologic dysfunction 因不能
识别 cause-specific safe intervention，被注册为无 effect 且 `causal_status=OUT_OF_SCOPE` 的
action class；runtime rollout/plan 因此返回 typed status，而不是未注册异常或泛化 action。

### 5. Topology 真正进入 runtime

`topology.edges` 为 directed process graph；它通过 `inference_coupling` 影响 evidence
propagation，通过 `planning_bridges` 与 `planning_coupling` 影响 action spillover。关闭
topology 应在预注册的 generic structural probes 中改变 posterior/rollout trace，而不是只改变
可视化。

### 6. 开放世界 residuals

已映射 observation 可通过 unknown/reference likelihood 更新 `U`；未映射 observation 通过
scope-declared log Bayes factor 更新 `U`。mapping residual、model misfit 和 evidence counts
分开保留。focal neurologic deficit 等较不特异于当前 process registry 的事实被设计为更强的
unknown signal，而不是强迫归入最近候选。

## Parameter Provenance

本 pack 没有临床训练、拟合或校准。所有参数遵循同一标签：

| 参数 | 真实语义 | 禁止解释 |
|---|---|---|
| activation priors | generic scope 内的 toy ordering weights | 患病率/先验流行率 |
| active/inactive likelihoods | ordinal signed evidence weights | 敏感度、特异度、条件概率 |
| coordinate priors | 初始 toy burden | 患者真实严重度 |
| mode priors/drifts | 结构性方向演示 | 临床转移概率/每小时变化率 |
| activation enter/withdraw hazards | case-blind turnover toy + 方向性持续/消退 | 发病率、恢复率、临床时钟 |
| multi-process joint likelihood tables | 单一 common-source factor 的保守组合 | 已验证 joint probability/synergy |
| process/mode couplings | 方向性机制连接 | 因果效应大小 |
| action deltas | 方向性 mechanism placeholders | 个体治疗获益/伤害大小 |
| objective weights/cost | planner 接口的 toy burden | 临床效用、QALY、安全偏好 |
| activation status thresholds | wire 展示用 toy status boundary | 诊断/治疗阈值或校准风险分层 |

小数位用于 deterministic runtime，不代表精度。

## Identifiability Boundary

| Query | 默认状态 | 可输出 | 不可输出 |
|---|---|---|---|
| diagnosis/process summary | `STRUCTURALLY_SUPPORTED_NOT_CALIBRATED` | concurrent process marginals、local modes/coordinates、residuals | 校准疾病概率、唯一病名 |
| no-new-action forecast | `UNIDENTIFIABLE_FOR_CLINICAL_MAGNITUDES` | toy directional trajectory、trace | 真实自然病程数值、死亡率 |
| action rollout | `UNIDENTIFIABLE` | 声明机制下的方向/结构或兼容范围 | 患者级唯一反事实、疗效大小 |
| plan | `UNIDENTIFIABLE` | toy objective 下的接口结果 | 临床推荐、最优治疗 |

单个病例的实际动作和结局不能唯一恢复未实施动作的结果。若多个相容世界给出冲突反事实，
输出必须保持 `UNIDENTIFIABLE` 或范围；不得让 LLM 或 toy dynamics 填补。

## Validation

本 pack 已在最终 conditional-active Runtime 2.1 source tree 上完成下列 case-blind
验证，并已通过 `model_validation.json` 原子绑定该 runtime 的最终 manifest/seal：

1. JSON Schema + `validate_model_spec`；
2. 13-process exact factorial initialization（含 `U` 共 `2^14 = 16384` hypotheses）与性能记录；
3. signed positive/negative emission probes；
4. concurrent-process posterior probe；
5. process-local opposite-mode probe；
6. mode guard enter/hold/exit hysteresis ablation，以及 hormonal-support 与 adrenergic-drive 独立性 probe；
7. independent infectious-burden vs downstream vasoplegia probe；
8. action planned/start/continue/stop/washout 与 `NO_NEW_ACTION` 差异；
9. topology on/off inference 和 planning ablation；
10. unmapped/misfit/unknown residual probe；
11. shared-state hash/query purity 与 measurement/masking contract static audit；
12. runtime v2.1 全量 unit tests。

- content audit：9/9 PASS；
- v1.1 synthetic runtime probes：11/11 PASS；
- Runtime 2.1 full suite：132/132 PASS；
- mapper/oracle sanitized registry compiler：8/8 PASS；
- 13 known processes + `U`：16,384 个 activation hypotheses；
- 本机本轮中位 wall time：construct 0.0453 s、empty initialize 0.5832 s、diagnose
  1.7179 s、horizon-1 forecast 3.2503 s；construct+initialize+forecast 的 tracemalloc peak
  56,835,288 bytes。

上述是冻结 source 上的结构验证，只支持 generic component 的 `FINAL_PASS`，不允许升级为
临床有效。mapper
runtime interface 已证明 reliability 与 `rankable=false` support masking 可执行；真实 primary
mapper 是否正确赋值仍须在隔离角色执行时单独通过 hard gate。

## Known Limitations

- exact activation factorial 仅适用于这个小型冻结 scope，13 known processes 已到声明上限；
  上述 wall/peak-memory 只是冻结机器上的边界测量，不是 latency SLA，也不得外推到更大 atlas；
- local coordinate/mode posterior 是 `process active` 条件分布；runtime 不保存 activation
  configuration-specific local/mode posterior，也不保存可恢复 dormant memory；
- activation-local closure 只有 numeric invariant tolerance，没有经临床校准的近似容差；若
  omitted dependence 改变当前决策，必须视为 model-content/architecture-refinement failure；
- observation factors 仍是 log-linear approximation；method/support-masking/censoring/MNAR
  contract 由 mapper/harness 执行，runtime 尚未拟合完整 joint residual 或 device model；
- mode guard/hysteresis 已显式接入，但阈值、transition mass 与 hazard 未校准；
- 一个 broad mechanism process 不能替代疾病级 atlas；
- 药物/操作级适应证、禁忌证、剂量、执行质量和安全约束未建模；
- topology edge lengths、couplings、action effects 与 objective 未校准；
- 任何 holdout 相容结果都只能说明 case consistency，不能证明泛化或因果有效性。

## Change Policy

在读取 holdout 后不得原地修改本模型来迎合答案。发现 mapping gap/misfit 时：

1. 保留当前 model/hash 与失败证据；
2. 分类为 mapping、model misfit、unmodelled process、measurement uncertainty、scope gap 或
   causal nonidentifiability；
3. 如需扩展，创建新的 generic model version，并以独立病例/通用证据重新冻结；
4. 提供 migration 与旧范围 non-regression，不把未来证据迁入过去 state。
