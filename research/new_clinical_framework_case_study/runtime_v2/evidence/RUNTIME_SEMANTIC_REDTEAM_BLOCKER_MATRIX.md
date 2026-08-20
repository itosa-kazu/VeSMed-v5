# Runtime v2 semantic red-team blocker matrix

状态：**repair-in-progress / final rerun pending**  
审计边界：只审 `runtime_v2` 对冻结 `NCF-ARCH-1.0.0` 的普通软件正确性与语义闭包；不读取真实病例，不审 V5，不判断临床参数是否正确。

冻结合同：

- `ARCHITECTURE_FINAL_v1.md` SHA-256: `d83b910f3cd32c777f126b245c2652e88fccb31aaa125b455f4c5af90cc4575c`
- `architecture_final_v1.schema.json` SHA-256: `9804d21e8032f571b6cfd414c08b31891eab8856bc0502e0000df4b7d53f80d1`

本文件不在并发修复未结束时下最终 verdict。最终证据应由：

```powershell
cd C:\Users\wangw\Documents\vesmed\research\new_clinical_framework_case_study
python -m unittest discover -s runtime_v2/tests -v
python runtime_v2/evidence/semantic_redteam_probe.py `
  --output runtime_v2/evidence/semantic_redteam_results.json
```

共同产生。

## 0. 2026-07-21 repair snapshot 后新增的待复核反例

以下均已给出最小复现，但代码仍在并发修复，故只登记为 **final rerun
candidate**：

| ID | 最小反例 | repair snapshot 结果 |
|---|---|---|
| W01 | factor posterior 的 wire list 与 replay list 以 `configuration_id` 对齐后完全相同，但 validator 逐位置比较不同排序 | 误报 `architecture joint posterior is inconsistent...`；按 id 比较 max diff = 0 |
| W02 | action event 的 `event_id != provenance.source_result_id` | `action_memory.source_event_ids` 错填 source-result id，和 processed event lineage 不一致 |
| W03 | 合法 `RecordOnly` public event | `_factor_messages` 读取 trace 中不存在的 `event_digest`，公开路径 `KeyError` |
| W04 | 冻结 schema 禁止的 nested field 加入 `as_of` 后重算 hash | `SharedPatientState.from_dict` 与 query 接受；runtime 未执行 frozen nested schema |
| I05 | partial action 的 identified set 是 coordinate-effect range | effect bounds 被直接冒充 outcome/utility bounds；实测 total objective `0.60018`，却输出 `[-0.26,-0.16]` 并据此选 action |
| I06 | 多 process 高 burden 的 natural forecast | total objective `1.7229`，但硬编码 no-action set `[0,1]` 不含 declared-model point |
| I07 | 已有 active exposure 的 action causal status 为 `UNIDENTIFIABLE` | `forecast(no_new_action)` 仍只报 `PARTIALLY_IDENTIFIED`，未继承现有暴露边界 |

这里最重要的区分是：W01-W04 是普通软件/序列化缺陷；I05-I07 是识别
区间没有合法传播到 outcome 的决策语义缺陷。二者都不能用“以后填临床参数”解释。

## A. 必须闭合的普通软件语义

| ID | 合同问题 | 决定性反例 / 验收条件 | 当前处置 |
|---|---|---|---|
| T01 | 空时钟推进必须运行自然动力学 | `update(state, [], advance_to=t+k)` 的局部坐标/mode 应与同一 no-new-action kernel 一致 | repair agent处理中；最终重跑 |
| T02 | query horizon 必须有限、正、绑定 scope | `0/-1/NaN/Inf` 不得被当一步；超过 `Ω.H` 不得实际执行；最好返回 typed `OUT_OF_SCOPE` | repair agent处理中；最终重跑 |
| T03 | 小数 horizon 不能静默向上取整为完整步 | `horizon=0.1` 不得产生与 `1.0` 完全相同的暴露/成本/漂移；应限制整数或积分 fractional step | 待决定 |
| T04 | stale public event 递归更新必须等价于 replay，或 fail closed | `initialize([e@available1], cut=5)` vs `initialize([],cut=5)→update(e,5)`；不能把旧事件悄悄当 t=5 新事实 | probe 已写，待最终重跑 |
| T05 | 延迟结果必须按 sample/occurred time 约束过去状态再前推 | sample@0/result available@5 与 sample@5/result available@5 不应在非零 drift 模型中成为同一 current state | 结构性 blocker；需 smoothing/replay 或显式限制/OOD |
| T06 | 不确定时间区间不能被伪造全序 | ActionStarted `[0,2]` 与 observation `[1,1]` 的先后未知，不能生成确定 post-action response attribution | 结构性 blocker；probe 已写 |
| A01 | 动作累计暴露从实际发生开始，不从可见时间开始 | start occurred=1/available=5/cut=10/dose=1 → exposure=9（精确时刻场景） | repair agent处理中；最终重跑 |
| A02 | lifecycle identity 与合法 partial order | plan→start 链接；terminal exposure ID 不可复用；hold/resume/stop/complete/washout 不覆盖历史 | repair agent处理中；最终重跑 |
| A03 | policy/event dose 与 unit fail closed | negative/NaN/Inf dose、unit mismatch、未知 key/exposure/action 不得进入轨迹或负成本 | repair agent处理中；最终重跑 |
| A04 | ongoing unidentifiable exposure 不能由 “no new action” 洗成可识别 | active action 的 causal status 为 `UNIDENTIFIABLE` 时，continue-current forecast 必须继承该边界 | repair agent处理中；probe 已写 |
| S01 | runtime spec 必须 immutable / digest-bound | caller 或 runtime registry 的后构造 mutation 不能改变旧 state 行为而保留旧 digest | repair agent处理中；已有测试 |
| S02 | model loader 必须拒绝非法数值域 | negative mode priors、NaN horizon、Inf sd、非 finite drift/cost/effect/coupling 等在构造期失败 | 需补统一 finite/domain validator；probe 覆盖两个原子反例 |
| M01 | migration 不能丢 canonical history/evidence/epistemic | identity migration 保留 factor messages、source dedup、trajectory features、mode/action windows、unexplained/missing info、learned strata | migration/history agents处理中；最终重跑 |
| M02 | source spec 和映射必须明确 | source model digest 必须匹配 state；many-to-one process/coordinate map 无显式 merge 规则时拒绝 | migration agent处理中；最终重跑 |

## B. Typed factor / observation semantics

| ID | 合同问题 | 决定性反例 / 验收条件 | 当前判断 |
|---|---|---|---|
| F01 | reliability 必须实际调制 likelihood/state update | 同一阳性因子 reliability=1 与 0.01 对 posterior/coordinate/mode 的改变量不能相同 | 现实现只把 reliability 写 trace；**blocker** |
| F02 | common-parent 去重不能变成 arbitrary first-event-wins | 同一 source 含 A/B 两个不同事实，交换 transport event IDs 后患者 posterior 必须不变，或明确拒绝并要求 joint factor | 现实现按第一个 source event 丢弃其余；**blocker** |
| F03 | semantic source fingerprint 必须含所有 operative 字段 | 同 source/concept/numeric value 但 unit 或 sample time 更正，不能当等价 rendering 静默忽略 | 现 fingerprint 仅 concept/value；**blocker** |
| F04 | mapped-but-impossible observation 必须有可追踪 residual | 极端 mapped value 提高 `model_misfit` 时，source 必须出现在 `unexplained_observations` | 当前只列 unmapped/冲突；**blocker** |
| F05 | support/measurement condition 必须进入 observation model | 活跃支持下“正常值”与无支持正常值不应把 latent burden 更新成相同状态 | 当前 emission/update 不读取 action exposure/measurement condition；**G09 blocker** |
| F06 | 同时活跃过程共同解释一个 observation 时必须有 joint/common-cause 语义 | 单个 factor 有多 process emissions 时，不得把同一观察按每个 active process 独立 LLR 机械相加，从而偏爱多重激活 | runtime 仅 log-linear additive emissions；需声明限制或实现 joint factor |

## C. Controlled dynamics 与 geometry 的覆盖缺口

| ID | 合同问题 | 决定性反例 / 验收条件 | 当前判断 |
|---|---|---|---|
| D01 | process activation 必须能随时间/动作变化 | rollout 不应永远冻结 active-process marginals；需要 process activation/exit/complication transition kernel | 当前 marginals 在 rollout 固定；**架构能力未实现** |
| D02 | action effect 类型不能只有 coordinate delta | 冻结架构允许动作改 process activity、mode guard、emission/support masking、noise；至少 scope 内必需类型应有 executable path | 当前主要只有 local coordinate delta/间接 guard；需限制 scope 或扩展 |
| D03 | posterior uncertainty 必须随 horizon/dynamics 传播 | predictive scale 不应仅复制 initial coordinate uncertainty；mode/process/unknown uncertainty应进入未来分布 | 当前 deterministic mean propagation + fixed scale；属于明确建模缺口 |
| G01 | refined response-opposite strata 必须在行为几何中被拉开 | split 后两个 child strata 不得仍只有同一 process node、零 geometry distance | 当前 topology keyed by process，stratum split 主要落 action modifier；**geometry未闭合** |
| G02 | typed coupling metadata/lag/conditions 必须 operative | coupling 的方向、条件、时滞、来源/版本不能只在 wire materialized view 中存在 | 需结合 final repair复核 |

## D. OOD 与 identifiability 必须影响决策，而不只是显示

| ID | 合同问题 | 决定性反例 / 验收条件 | 当前判断 |
|---|---|---|---|
| I01 | 高 OOD residual 必须使未知世界进入 action comparison | 大量 unmapped facts、unknown mass 高且未知世界 action response 无界时，不能仍按已知模型点值唯一选 action | 当前 `abstention_status` 不约束 plan；**blocker** |
| I02 | partial identification 不能按单一世界点值优化 | action identified set `[-1,+1]` 与 no-op 重叠时，没有 robust dominance 不得唯一选该 action | 当前 plan 主要用 point `expected_objective`；**blocker** |
| I03 | typed `OUT_OF_SCOPE` 应是 query 结果 | horizon > scope 或 action不在scope时，应返回 scope/assumptions 且不执行轨迹；非法 numeric input才是 ValueError | 需最终决定 API；冻结 §14 明列该状态 |
| I04 | multiple compatible world models 必须 operative | wire 中 world hypotheses 不能只是展示；它们需形成 prediction/action identified set 或促使 abstain | 当前主要单 declared model + residual 标签；架构能力未实现 |

## E. Local refinement

下列问题已在并发修复中看到实质代码推进，最终只能以 clean rerun 为准：

1. collision 不能只检测 opposite sign；必须检测 disjoint optimal-safe actions + value gap；
2. truly new action 必须以显式 action spec 扩展 action/scope registry；
3. non-regression 只能排除 affected process 的新 stratum，不得隐藏所有 unrelated strata；
4. migration 必须保存 source state/model/action/evidence lineage；
5. refinement 后 child strata 仍需接入真正的 behavioral geometry（见 G01）。

## F. 不应混淆的结论

这些反例若成立，证明的是：

```text
当前 runtime 尚未完整实现冻结架构合同
```

而不是：

```text
NCF 架构思想被推翻
```

反过来，即使全部结构 probes 通过，也只证明：

```text
软件能一致地表示/更新/查询这类状态
```

仍不证明：

- 真实临床参数已填好；
- 隐状态可由真实资料识别；
- 对复杂真实病例定位正确；
- 个体治疗反事实已识别；
- 存在一张有限、唯一、永久不变的“理想全医学地图”。

冻结架构给出的是**范围相对的理想状态判据与可细化机制**，不是一份永远完成的具体模型。
