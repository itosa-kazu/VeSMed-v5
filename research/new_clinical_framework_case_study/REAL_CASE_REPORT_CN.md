# 新临床框架：真实病例回放初步报告

> 本报告只评估新框架的事件回放与共享状态合同，不使用 VeSMed V5。
> 数值内核为未校准序数模型；动作模拟不是临床治疗建议。

## 结果摘要

### PMC10448002

- cuts: `6`
- shared-state exact hash: `True`
- recursive closure: `True`
- mapped rankable ratio: `0.590`
- record-only/unmapped ratio: `0.410`
- ordinal next-cut direction proxy: `0/5` (not a clinical metric)
- status: `CASE-CONSISTENT`
- post-replay clinical readout audit: `FAILED`

### PMC7005653

- cuts: `10`
- shared-state exact hash: `True`
- recursive closure: `True`
- mapped rankable ratio: `0.404`
- record-only/unmapped ratio: `0.596`
- ordinal next-cut direction proxy: `1/9` (not a clinical metric)
- status: `CASE-CONSISTENT`
- post-replay clinical readout audit: `FAILED`

## 能说明什么

- 同一个递归、可序列化患者状态确实能同时供诊断、自然预测和动作模拟读取。
- 两个不同病例 schema 能按真实可见性 cut 回放，未来结果不会进入较早状态。
- 映射覆盖、未知/record-only 信息和动作暴露均可审计。

## 不能说明什么

- 不能证明分支 posterior 是真实患病概率。
- 不能把病例后续结局当成未实施治疗的反事实真值。
- 不能证明总体临床有效，也不能证明这是唯一或最终理想模型。
- `next_event_consistency` 只是异质序数观察的弱结构代理，不是医学准确率。

## 两个病例暴露的具体失败

- **PMC10448002**：最终 top branch 仍是 `B_TTP`，而不是病例后续证据支持的 `B_COMPLEMENT_TMA`；首次就诊还被标成 `recovering`。
- **PMC7005653**：到心脏检查 cut，Takotsubo、myocarditis、ACS 三支仍完全并列；到拔管和转普通病房后，mode 仍停在 `strained`。
- 两例的动作选择几乎不随 cut 改变，说明当前动作转移只是占位序数规则，不是有效的病例条件化规划。
- 两例 unknown mass 都固定在最小值 `0.05`，但 record-only/unmapped 比例分别约为 41% 与 60%；当前骨架尚不会把模型外信息正确转成开放世界不确定性。
- 这些失败推翻的是当前最小实现已经足够的说法，不是推翻聊天中的候选架构。
