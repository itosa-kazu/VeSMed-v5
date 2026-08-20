# 验收条件

## R1 事件账本

- 两例均来自 PMC/PubMed 原始病例。
- observation、action、hypothesis、result availability、outcome 分离。
- 未报告精确日期只保留偏序，不伪造钟表时间。
- 较早 cut 不得包含未来结果。

## R2 共享状态实体

- 状态显式包含 branch posterior、branch-local coordinates、mode posterior、
  history summary、action exposure 和 lineage。
- diagnosis、forecast、plan 的输入 state hash 必须相同。
- update 必须产生可审计 parent hash，禁止三个任务各自重编码病例。

## R3 因子图

- 每个 rankable observation 必须连接到至少一个隐藏机制/模式或显式背景
  因子。
- 共享父机制的多个观察在条件于隐藏状态后处理，不能再手工重复加分。
- 因子图删除消融应产生可测的校准/过度自信差异。

## R4 混合受控动力学

- 连续坐标有 branch/mode/action 条件化 transition。
- mode 支持 compensated/strained/decompensated/recovering 的离散转移。
- 同一连续坐标、不同 mode 可产生不同未来；无-mode 消融必须暴露该错误。

## R5 分支/分层几何

- 分支有显式父子/共享机制拓扑和局部坐标。
- 距离必须区分“表面相似”与“机制/动作响应相似”。
- flat-Euclidean 消融必须至少在一个病例关键 cut 产生错误邻居或错误动作。

## R6 全程病例回放

- 每个 cut 执行 update、诊断后验、下一段受控预测和动作可行性评估。
- 记录论文后续观察与预测的差异；不得只汇报最终 top-1。
- 能表示既存过程持续、新过程激活、假说退出和恢复模式。

## R7 历史与动作反例

- 构造相同最新观测但不同早期轨迹的 twin；完整状态必须不同，
  snapshot-only baseline 必须碰撞。
- 构造相同表面输出但支持强度不同的 twin；action-aware state 必须不同。

## R8 局部细化

- 新治疗 pack 在旧状态中产生同状态/同动作/反向响应碰撞。
- 未发现区分信息前系统必须拒绝个体化方向结论或输出范围。
- 加入新检查/变量后只拆相关局部 branch；旧病例输出与旧范围能力不得
  无故改变。

## R9 结论边界

- 区分 `STRUCTURALLY_SUPPORTED`、`CASE-CONSISTENT`、`FAILED`、
  `UNIDENTIFIABLE`。
- 两个病例不能证明总体临床有效、参数校准或真实个体反事实。
- 完成必须包含可重复命令、自动测试、机器结果和独立审计。

