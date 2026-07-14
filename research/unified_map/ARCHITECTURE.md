# UCM Architecture

> 状态：**PRE-FREEZE / 尚无最强候选。** 本文件不能把 benchmark harness、K0、统一接口或同名 payload 误写成患者地图。

## 当前可确认的边界

运行时合同只有一个患者特异状态 `Z_t`：

```text
initialize(public_history) -> Z_t
diagnose(Z_t)               -> mechanism distribution
rollout(Z_t, no_new_action) -> natural future distribution
rollout(Z_t, do(A/B/C))     -> interventional future distributions
update(Z_t, visible_delta)  -> Z_t+1
```

这里的 schema、state hash、fresh worker 和 append-only result 只负责**检查候选是否遵守实验边界**，不是 UCM 架构答案。真正的 architecture section 只有在 benchmark v1 冻结、至少三个不同 family 完成 W01–W20、碰撞/OOD/扩展/新读出证据可复现后才能填写。

## 候选搜索空间

正式家族为 `CANDIDATES.md` 的 F01–F12。当前没有实现、赢家或 Pareto 前沿。任何候选至少要同时说明：

1. `Z_t` 的数学对象和有限/动态容量；
2. observation/action-conditioned update；
3. 同一 controlled transition core 如何生成自然与治疗未来；
4. diagnosis/readout 如何只读 `Z_t`；
5. OOD 与 `scope_insufficient` 的表示；
6. 为什么不是完整历史、三个 task latent 的拼接或 query-time history reread；
7. 新检查、新治疗和新任务加入时需要保留/扩展什么。

## 当前结论

`NO_ARCHITECTURE_SELECTED`。目前只有研究合同和 harness primitives；它们不构成有限共享患者状态存在的证据。
