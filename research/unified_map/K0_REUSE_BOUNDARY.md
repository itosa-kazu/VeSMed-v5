# K0 与 UCM 的复用边界

> 结论：UCM 只复用旧轨道的实验基础设施**模式**，不 import 旧 API，不继承旧患者语义，也不把旧测试结果当 UCM 动力学证据。

## 1. 为什么必须隔离

旧 K0 研究回答的是证据、时间切片、能力边界、执行隔离、回放和 bridge 合同问题。它没有定义本轮要求的单一共享患者状态 `Z_t`，也没有证明同一状态能够同时支持诊断、自然病程和治疗反事实。

因此以下推理无效：

```text
K0 能安全路由多个模型
=> 多个模型拥有同一患者状态
=> 已有统一临床地图
```

K0-only 会作为明确的 negative-control baseline：它应能守住输入/时间边界，但对 W01–W20 的临床动力学 query 返回 `unsupported` 或无信息输出。若它得到非平凡分数，应优先调查 evaluator 泄漏或隐藏模型。

## 2. 允许重新实现的基础设施模式

以下能力可在 `prototype/unified_map/` 内以独立 schema、独立模块重新实现：

1. canonical JSON 与 path+bytes SHA-256；
2. 唯一 `run_id`、exclusive create、同级临时目录和原子 rename；
3. candidate-view 与 judge-only oracle 的物理分离；
4. fresh subprocess、最小候选包、只读模型制品和访问审计；
5. exact-byte manifest、sidecar、输出 inventory 和 clean replay；
6. AST anti-dispatch scan 与真实 malicious-candidate mutation gate；
7. 外部 public journal 驱动的 incremental-vs-clean-replay 检查。

“重新实现”而不是直接 import，是因为旧 runner、contract 和 workload 顶层已经绑定 K0/TEL/SCM/rewrite/bridge 语义。

## 3. 禁止 import 或复制为 UCM 答案的内容

UCM 生产代码不得 import：

```text
prototype.contract
prototype.kernel
prototype.benchmark
prototype.workloads
prototype.reference_models
prototype.model_subkernel
prototype.experiment
prototype.isolated_benchmark
prototype.isolated_worker
prototype.candidates.*
prototype.bridge_holdout.*
tests.workloads.*
tests.bridge_holdout.*
```

也不得把以下内容复制后改名成 UCM oracle：

- T01–T50 / E01–E08 workloads；
- bridge hidden corpus、A/B runners、gates、reports；
- TEL/causal-state/rewrite 的内部 state；
- 旧 K0 candidate manifest 或 `ingest/query/retract` 合同；
- 旧 panel 每次接收完整 model/query 的执行路径。

旧代码只允许通过单向、隔离、明确标记 `eligibility=negative_control` 的 K0-only adapter 运行；其输出不能写入 W01–W20 oracle，也不能进入共享候选训练。

## 4. 冻结资产

权威清单：`research/unified_map/K0_FROZEN_INVENTORY.json`。

清单固定：

- 基线 commit `0795bc49c4aadb1d5d7cb8951044d9601ecb51a3`；
- `results/20260713T120910Z-panel-v3/` 的 10 个文件、字节数和 SHA-256；
- 根目录 K0 历史决策文档的 Git blob、字节数和 SHA-256。

UCM 测试必须逐字节核验。若任何文件需要合法修订，必须先解释为何不再属于冻结历史，并创建新的显式 inventory 版本；不得为了通过 UCM 测试静默更新 hash。

## 5. 旧 holdout 的教训，只能作为 harness 要求

旧 bridge corpus 曾出现 descriptor-only 和 dangling fixture。因此 UCM freeze gate 必须自动断言：

```text
W01–W20 均有可执行生成器与 oracle
每个 split/seed 可独立执行
所有引用可解析
每个允许动作有反事实真值
零 descriptor-only
零 dangling reference
candidate-visible projection 不含 judge-only 字段
```

这条教训只支持新的完整性门，不支持任何 UCM 候选或架构结论。

## 6. 声明上限

边界测试通过只能证明：UCM 工作没有误改或直接导入冻结 K0 资产。它不能证明：

- benchmark v1 已完整；
- 候选真正共享状态；
- UCM 存在；
- 任何临床有效性或生产安全性。
