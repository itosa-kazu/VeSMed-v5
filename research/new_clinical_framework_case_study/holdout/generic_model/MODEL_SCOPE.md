# Generic Model Scope — Adult ICU Acute Hemodynamic Collapse

状态：**CASE-BLIND GENERIC MODEL v1.1 — FINAL COMPONENT FREEZE**  
模型：`adult-icu-acute-hemodynamic-collapse-generic-v1`  
架构：`NCF-ARCH-1.0.0`
Runtime：`new-clinical-runtime/2.1` final source（exact manifest/seal 由 `model_validation.json` 绑定）

## 1. 构建隔离边界

本模型只依据冻结的 broad scope、`ARCHITECTURE_FINAL_v1.md` 和 `runtime_v2`
设计/代码/schema/tests 构建。构建过程中未读取 holdout 病例时间线、病例数值、结局、旧
cases、real-case results 或最终审计，也未搜索任何具体病例。

模型不能因后续 holdout 的期望答案改变；若后续发现缺口，只能按冻结架构执行
mapping/OOD/misfit 报告，或把变更登记为面向下一轮、重新冻结的通用模型版本。

## 2. 冻结范围 Ω

| 组成 | 冻结声明 |
|---|---|
| `P` 人群/场景 | 成人、ICU 级急性血流动力学崩溃；可并发严重心室功能异常、肺水肿/低氧性呼吸衰竭、AKI，病程可出现心律失常与神经状态改变 |
| `O` 可用观察 | 截止 cut 已可用的床旁血流动力学、心电、超声/影像、常规/定向实验室、动态安全探针、器官功能和序列趋势；不把未检查当阴性 |
| `A` 动作 | 通用支持或机制定向 action class；以 planned/started/active/held/stopped/residual-washout 生命周期记录 |
| `Π` 策略 | `NO_NEW_ACTION_CONTINUE_CURRENT`，或在当前 action ledger 上新增一个已声明 action class 的结构性 rollout |
| `H` 时间范围 | 0–24 个 ordinal runtime steps；step 不对应已校准临床小时数 |
| `Y` 结局 | process/organ 局部 coordinate burden、局部 mode、OOD/mapping/misfit；不声称死亡率、QALY 或患者级治疗获益 |
| `U` 效用 | toy coordinate burden + toy action cost，仅用于证明同一 shared state 上的规划接口 |
| `ε` 容差 | 临床容差未设定；wire 中的 `0.0` 只作 deterministic placeholder，不是临床等价、安全或决策误差保证 |

## 3. 并发 process 覆盖

模型使用 13 个可同时激活的机制过程；它们不是互斥病名，也不形成单一 simplex。runtime
保存的是 activation bits（外加 unmodelled bit）的 exact finite factorial joint，不是 activation、
local coordinates 与 local modes 的 full-state joint。

| process_id | 日本語 | English | 局部 domain |
|---|---|---|---|
| `P_VASOPLEGIA` | 全身性血管拡張・血管麻痺 | systemic vasoplegia | circulation/endothelium |
| `P_PUMP_FAILURE` | 心室ポンプ不全 | ventricular pump failure | heart/circulation |
| `P_MYOCARDIAL_ISCHEMIA` | 心筋虚血性障害 | myocardial ischemic injury | heart |
| `P_OBSTRUCTIVE_LOAD` | 閉塞性循環負荷 | obstructive circulatory load | heart/pulmonary vasculature/intrathoracic |
| `P_VOLUME_LOSS` | 血管内容量喪失 | intravascular volume loss | circulation |
| `P_RESP_FAILURE` | 急性低酸素性呼吸不全 | acute hypoxemic respiratory failure | lung |
| `P_AKI` | 急性腎障害 | acute kidney injury | kidney |
| `P_ARRHYTHMIA` | 不整脈性循環不安定 | arrhythmic instability | cardiac electrophysiology |
| `P_NEURO_DYSFUNCTION` | 急性神経機能障害 | acute neurologic dysfunction | brain |
| `P_HORMONAL_SUPPORT_FAILURE` | ホルモン性循環支持不全 | hormonal cardiovascular support failure | endocrine/circulation |
| `P_ADRENERGIC_DRIVE` | 過剰アドレナリン性・高代謝性ドライブ | hyperadrenergic and hypermetabolic cardiovascular drive | autonomic/endocrine/cardiovascular |
| `P_INFECTIOUS_BURDEN` | 感染源・病原体負荷 | infectious source and pathogen burden | infection/systemic |
| `P_TOXICOLOGIC_DRIVER` | 中毒性心血管ドライブ | toxicologic cardiovascular driver | toxicology/cardiovascular |

以上覆盖常见危重血流动力学机制，以及产生相似表型的内分泌、毒理、儿茶酚胺/自主神经
驱动。它不宣称列举了所有疾病或机制。`U`（unmodelled-process）可与任意已知 process
并存。

## 4. Observation 与 mapping contract

- 每个公开事实只有在 `available_at <= cut` 时可消费。event 必须携带
  `occurred_time{lower,upper}`、`recorded_at`、`available_at` 与带 `source_result_id` 的
  provenance；Observation 另需 `sample_time{lower,upper}` 和 `result_at`。发生、采样、出结果、
  记录与可用时间不得混为一谈。
- observation 使用 `boolean`、`categorical` 或 `gaussian` typed emission；每个 emission 同时声明
  active 与 inactive likelihood-shaped toy weights，因此可靠阴性可以产生负 LLR。
- 同一个 observation 若连接多个 processes，必须由覆盖完整 active-set 的一张 typed
  `joint_likelihoods` 表形成一个 common-source factor；不得把其 process-level emissions 当成
  独立检查结果逐个相乘。v1.1 的表只是 case-blind conservative mixture，不是校准 joint model。
- `factor_id + source_result_id` 是证据身份；同一结果的复制不增加证据。
- `unknown`、`not_tested`、`negative`、`post-treatment-negative`、`low-sensitivity-negative`
  必须在 mapper 层保持不同；不能把缺失值映射为 `false`。
- `dynamic_preload_responsiveness_presence` 只有在已记录动态 preload probe 时可映射；序列
  trend 只有在严格按 availability 顺序的多个测量存在时可映射。
- 普通观察保持诊断中立，不把病名写进 observed concept。
- 多个概念若来自同一原始结果，必须共享 `source_result_id`，避免重复解释同一事实。
- MAP、LVEF、P/F ratio、lactate、cortisol、TSH、free T4 与 metanephrine xULN 是带单位的
  numeric factors；只有满足各自 method/provenance contract 时才能映射。
- action/support 可能掩盖 observation 且没有 conditioned factor 时，mapper 必须停止该 emission，
  提高 `measurement_uncertainty`，不得把支持后的正常值当 untreated negative evidence。
- 同一 source 落入一个 `alternative_representation_group_id` 时只消费一个表示，优先 method-valid
  numeric measurement；censoring/MNAR 不得硬转成 exact number/false。

## 5. 局部 coordinates、modes 与自然动力学

每个 process 有自己的 `[0,1]` ordinal burden coordinates，坐标不能跨 process 直接当成
同一轴。局部状态的严格解释是 `q(local coordinates, local mode | process active)`；每个
process 独立维护 `compensated / strained / decompensated / recovering / failed` 条件 mode
posterior。同一时刻一个 process 可 recovering，另一个可 decompensated。

当前 frozen wire 对 activation/local 使用显式 variational closure：保留 dependent activation
joint，但在所有包含同一 active process 的配置中复用一份 local conditional。它不表示
configuration-specific `Z↔local/mode` 相关性，也不保存 dormant-state conditional。若真实病例
或动作比较需要这类被省略的相关性，必须分类为 `MODEL_CONTENT_OR_ARCHITECTURE_REFINEMENT`，
不能以 scope/OOD 话术掩盖。

v1.1 为每个 process 声明 enter/withdraw hazard。entry 把新增 active mass 初始化到声明 prior；
partial exit 只减少 active mass，survivor 的 active conditional 不重置；process 接近完全 inactive
时 wire 中残留 local 仅是非事实 placeholder，未来 re-entry 仍从 prior 开始。自己的 local drift 与
action local effect 作用于 active conditional；activation mass 仅在 emission/outcome mixture 等需要
混合 active/inactive 世界时作为权重使用。
每个 process 均声明 mode guard：burden 进入阈值 `0.68`、退出阈值 `0.45`，形成显式
hysteresis band；这些阈值和 transition mass 都只是 executable toy structure。

`P_HORMONAL_SUPPORT_FAILURE` 与 `P_ADRENERGIC_DRIVE` 是两个独立 concurrent processes；
低激素支持和高肾上腺素驱动可单独或共同存在，拥有各自的 exact process bit、coordinates、
mode posterior、emissions 与 action targets。模型不依赖 runtime 未授权消费的装饰性 strata。

`P_INFECTIOUS_BURDEN` 是独立上游 process，保存 infectious load、source persistence 与
infection-driven inflammatory signal；它可在 support 暂时恢复血压时继续活跃，再通过
directed couplings 影响 vasoplegia、respiratory failure 与 AKI。

`NO_NEW_ACTION_CONTINUE_CURRENT` 明确执行：

1. exact active-process factorial joint 的 enter/withdraw propagation；
2. 每个 active-process conditional 的 local mode-weighted drift；
3. declared process-coordinate、mode 与 activation couplings；
4. 已执行 action 的 active/residual/washout local/activation effect；
5. 不启动任何新 action。

所有 drift、coupling 和 mode potentials 都是方向性 toy 参数，不是临床速率。

## 6. Action 边界

`model_pack.json` 声明 fluid challenge、vasoconstrictor/inotropic/ventilatory/renal replacement/
mechanical support、decongestion、rhythm stabilization，以及 infectious-source、hormonal、
adrenergic、toxicologic、coronary reperfusion、mechanical-obstruction 等 action classes。

这些 action 只提供机制方向和 action lifecycle 的结构演示：

- planned 不改变状态；
- started/continued/dose-changed/stopped/washout 有不同转移；
- 正向效果与可预期代价可同时作用于不同局部坐标；
- 仅 cause/process-removing action class 可改变 process enter/withdraw hazard；support-only action
  不得因为改善表面/局部 burden 就自动清除 active process；
- topology planning bridge 可把直接 effect 传播到声明的邻接过程；
- 所有患者级治疗反事实默认为 `UNIDENTIFIABLE`。

模型不得把 runtime 的 toy objective 最优 policy 当成临床推荐。
当前 generic neurologic process 不识别 cause-specific neurologic intervention；这类 query 必须
通过已注册但无 effect 的 action class 返回 architecture enum `OUT_OF_SCOPE`，不能抛成未注册异常，
也不能用一个泛化 action 假装补齐。

## 7. OOD 与拒答边界

模型必须分别输出：

- `unknown_process_probability`；
- `mapping_residual`；
- `model_misfit_residual`；
- mapped/unmapped/deduplicated evidence counts；
- 未解释观察与缺失区分信息。

未映射事实不能被丢弃或强行塞给最近 process。大量 unmapped/misfit 证据必须提高 epistemic
residual；不得用固定低 unknown mass 掩盖模型缺口。runtime 不设置临床二值阈值。

## 8. 明确不在范围内

- 儿科、孕产、慢性稳定门诊或术后专项人群；
- 完整感染病原、罕见遗传代谢病、结构性心脏病或所有毒物的穷尽 atlas；
- 药物级剂量/禁忌证、患者价值、安全约束、QALY、死亡率校准；
- 由单例观察性治疗结果识别未实施治疗的个体反事实；
- 临床概率、敏感度、特异度、患病率或疗效大小主张；
- 在无新增可观测区分信息时强行拆分危险状态碰撞。
