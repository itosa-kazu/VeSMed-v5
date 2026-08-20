# Model Card — Adult ICU Acute Hemodynamic Collapse Generic Pack

## Outcome

`model_pack.json` 是一个严格 case-blind、面向 Runtime v2/v2.1 的通用结构模型。它把成人
ICU 急性血流动力学崩溃表示为 **13 个可并发 processes + process-local coordinates +
local hybrid modes + typed signed emissions + directed couplings + action lifecycle + active
topology + epistemic residuals**。它不是临床诊断器、概率模型或治疗推荐器。

当前模型身份：

- `model_id`: `adult-icu-acute-hemodynamic-collapse-generic-v1`
- `model_version`: `generic-model/1.0.0`
- `architecture_version`: `NCF-ARCH-1.0.0`
- 参数状态：`expert_elicited_ordinal_toy_not_calibrated`

## Key Evidence Machinery

### 1. 非互斥 factorial processes

每个 `Z_i` 独立存在且可共同激活；系统同时保存 exact joint hypotheses、process marginals
和 `U`（unmodelled process）。pump failure、respiratory failure、AKI、arrhythmia 等可以是
并发状态，不会因另一个候选存在而被迫归零。

### 2. 器官局部坐标与 modes

局部 coordinates 只在对应 process/domain 内有意义。13 个 process 分别持有自己的 mode
posterior；不使用一个全局 mode。`mode_couplings` 表达诸如 pump decompensation 增加
respiratory decompensation tendency 的方向性连接；每个 process 还声明 executable
enter/exit thresholds 不同的 mode guard/hysteresis。`process_couplings` 表达坐标到坐标的
directed drift。所有阈值和转移质量仍是 toy structure。

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

本 pack 已在 final runtime v2.1 freeze 后执行：

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

全部项目通过；`model_validation.json` 保存机器可读数值、state/model digest、runtime seal、
structural harness 与 artifact hash。独立 case-blind F1–F5 复审全部 PASS。结构测试通过只允许
标记 `STRUCTURALLY_VALIDATED_CASE_BLIND`，不允许升级为临床有效。

## Known Limitations

- exact factorial 仅适用于这个小型冻结 scope，13 known processes 已到声明上限；final
  benchmark 的 16,384 hypotheses 初始化约 4.03 秒、tracemalloc peak 28.858 MiB、canonical
  state wire 约 5.70 MB，不能外推到更大 registry；
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
