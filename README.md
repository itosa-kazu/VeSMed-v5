# VeSMed 动态临床状态架构研究

这个仓库回答的不是“该用向量还是知识图谱”，而是更基础的问题：

> 当病历事实异步到达、观察会被治疗掩盖、证据会冲突或撤回、患者状态不可直接观测、诊断与干预又需要不同数学时，哪些语义必须永远固定，哪些内容应该允许持续扩展？

## 结论先行

本研究操作性去重并调查了 **13 个候选家族**，实现了 **3 个原子原型**（TEL、dynamic causal/state、typed rewrite/open），另实现 K0 kernel 与 public-model subkernel 两个判别仪器，并在 58 个机器 workload 上运行。结论是：**没有一个原子候选足以单独成为完整固定核心；2026-07-14 的 bridge 反证又使固定核心选择重新开放，目前没有通过全部声明门禁的赢家。**

2026-07-13 的 pre-bridge 最强研究基线是一个小的可信控制面 `K0`，加上语义分家的能力子内核：

```text
K0：ledger port / identity / cut / query / result / invariant 合同（不另存事实）
└── 完整参考联邦
    ├── 唯一 TEL/TMS evidence authority：事实、来源、撤回、重放
    ├── state/dynamics：隐藏状态、过滤、平滑、预测
    ├── causal：conditioning、do、同患者反事实
    └── typed rewrite/open safety：动作生命周期、可达性、组件连接
```

该基线不规定唯一 `PatientState`，也不与 TEL 各保存一套事实。它要求对象角色、identity/scope、ledger port、多角色时间与 cut、证据 witness 合同、封闭查询、正交失败和不可绕过的不变量；TEL/TMS 是该参考 profile 中唯一的权威 evidence store。这些要求仍保留，但 `K0 + 当前 bridge` 不再是已冻结赢家。

完整 profile 要求上述四组子内核能力齐备。受限用途可以降级，但必须显式：缺 state/dynamics 时 filter/smooth/forecast 为 `unsupported`；缺 causal 时 `do`/counterfactual 为 `unsupported`；缺 rewrite/open 时不得声称 action effect、reachability、组合或相应 safety 已执行；缺 evidence authority 时只可离线验证合同，不构成临床事实运行时。

bridge 运行前更准确的称呼是：

> **在 2026-07-13 的 T/E 面板范围内，最有支持的研究基线是“类型化可信控制面 + 显式异构能力子内核”的受控联邦；2026-07-14 后该选择已重开。**

这不是数学全局最优证明，也不是临床准确性或产品安全认证。

### 2026-07-14 bridge holdout 更新

后续冻结双实现 bridge 运行没有巩固上述选择，而是产生了两个同时成立的裁决：

- **`HYPOTHESIS_FAIL`（冻结 A/B 实现层）**：A/B 都没有通过非补偿 bridge 门禁；
- **`HARNESS_INCOMPLETE`（sealed 41-case corpus 层）**：H01–H30 是原预注册集，H31–H41 是源码封存后、执行前加入的静态审计 addendum；冻结 corpus 并非 41 个完整可执行 hidden fixture。

因此 K0 的 root/scope/time/cut/version/query/result 等要求仍保留，但“当前 bridge 已证明稳定”的固定核心选择已撤回，Checkpoint 3/7 重开。不能把 public 数值 panel 的成功、post-seal probe 或 synthetic mutation judge 写成完整 hidden holdout 通过。详见 [`results/bridge-holdout/REPORT.md`](results/bridge-holdout/REPORT.md)。

## 为什么不能只用一个向量或一张图

至少有三种不能混为一谈的“状态”：

1. **真实患者状态**：现实中存在但通常不可直接观测的生理路径；
2. **系统信念**：某个证据/模型版本下的 posterior、轨迹或诊断假说；
3. **权威记录**：真正收到的观察、陈述、动作、来源、更正和撤回。

向量、图或 posterior 都可成为有用计算视图，但通常不能同时无损回答：

- 这条结论来自哪一次测量？
- 当时医生有资格看到什么？
- 删除错误来源后哪些推断应失效？
- 正常血压是在升压药下还是自然状态？
- `P(Y|T)`、`P(Y|do(T))` 和这个患者的替代历史为何不同？
- 求解器没有收敛、模型不覆盖和证据不足分别意味着什么？

因此，本研究没有用一个“万能图节点”或 `payload:any` 假装统一。

## 10 分钟演示

要求：Python 3.11+；核心演示只使用标准库。

```powershell
python -m prototype.demo
```

演示会输出三段 JSON：

1. 一条带时间和来源的体温记录，生成 evidence、rewrite、causal-state 三种不同坐标及各自血缘；
2. 注册一个新医学规则模块，不修改 K0 源码；
3. DBN 无法回答同患者反事实时明确返回 `unsupported`，而不是把 forecast 冒充 counterfactual。

## 完整自动测试

需要 `pytest`：

```powershell
python -m pytest -q
```

仓库通过 `pytest.ini` 只收集 `tests/test_*.py`。2026-07-14 的当前全量 QA 结果为 **`135 passed, 7 subtests passed`**；bridge 专项为 **`16 passed`**。旧 `v5_*_test.py` 是历史研究脚本，依赖可选 SciPy，不属于 K0 自动测试。

## 运行统一架构面板

### Decision-grade 全面板

候选比较证据必须由默认隔离、不可覆盖、带环境与哈希的实验入口生成；`run-id` 必须唯一：

```powershell
python -m prototype.experiment --run-id my-unique-panel-run
```

该命令运行 3 个原子候选的 Native/Companion，以及 kernel/model 两个 Native instrument，共 8 个 panel × 58 workloads。单候选复查可用：

```powershell
python -m prototype.isolated_benchmark --candidate tel --panel all
python -m prototype.isolated_benchmark --candidate causal --panel all
python -m prototype.isolated_benchmark --candidate rewrite --panel all
python -m prototype.isolated_benchmark --candidate kernel --panel all
python -m prototype.isolated_benchmark --candidate model --panel all
```

`python -m prototype.benchmark ...` 是同进程开发诊断命令，**不能**产出候选比较证据。

### 冻结 v3 结果

pre-bridge 的 decision-grade panel 位于 [`results/20260713T120910Z-panel-v3/`](results/20260713T120910Z-panel-v3/)；当前选择还必须同时读取 [`results/bridge-holdout/REPORT.md`](results/bridge-holdout/REPORT.md) 的反证：

| 面板 | PASS | HONEST_UNSUPPORTED | FAIL |
|---|---:|---:|---:|
| TEL Native / Companion | 36 / 36 | 20 / 20 | 2 / 2 |
| causal/state Native / Companion | 3 / 3 | 53 / 53 | 2 / 2 |
| rewrite/open Native / Companion | 31 / 31 | 23 / 23 | 4 / 4 |
| K0 kernel instrument Native | 36 | 20 | 2 |
| public-model instrument Native | 13 | 44 | 1 |

不能把这张表当排行榜：不同候选面对的原生适用项不同；`HONEST_UNSUPPORTED` 只证明边界诚实，不代表能力完成；kernel/model 是判别仪器，PASS 不能反记给任一原子家族。

### 为什么 v1/v2 不能承担最终裁决

- [`results/20260713T200000Z-panel-v1/`](results/20260713T200000Z-panel-v1/)：红队前同进程诊断基线；oracle 隔离、semantic eligibility、轨迹覆盖、rebuild 与部分 fixture 区分力不足。
- [`results/20260713T115159Z-panel-v2/`](results/20260713T115159Z-panel-v2/)：已有 fresh `python -I -S` 和 stdin-only candidate view，但 pure-Python 候选仍可探测更广文件系统/外部路径；只作过渡诊断。
- **v3**：增加 CPython audit hook、最小读 allowlist，阻断 subprocess、network、native loader，并记录 candidate/workload/oracle/benchmark hash 与环境。

v3 是针对**已审计 pure-Python 候选**的 Python-level confinement，**不是 OS sandbox**。它不覆盖恶意 native code、解释器漏洞或操作系统侧信道；若候选来自不可信第三方，应改用独立 OS/container/VM 再复现。

## 目录导览

### 先读这五份

| 文件 | 内容 |
|---|---|
| [`FIRST_PRINCIPLES.md`](FIRST_PRINCIPLES.md) | 不依赖数学背景的问题推导 |
| [`REQUIREMENTS.md`](REQUIREMENTS.md) | HARD/SOFT 要求、反目标和反例 |
| [`DECISION.md`](DECISION.md) | 当前重开裁决、历史 Pareto、反对意见和再冻结条件 |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | K0 研究基线的可读目标合同和两张一页图 |
| [`FORMAL_SPEC.md`](FORMAL_SPEC.md) | 待重证控制面基线的类型、操作、时间、proof、query、Outcome 与不变量 |

### 研究证据

| 文件 | 内容 |
|---|---|
| [`SOURCES.md`](SOURCES.md) | 第一手论文/规范/官方文档，以及每项实际支持和不支持什么 |
| [`CANDIDATES.md`](CANDIDATES.md) | 本研究操作性去重的 13 个家族统一问卷比较 |
| [`RESEARCH_LOG.md`](RESEARCH_LOG.md) | 搜索路径、路线改变与反证 |
| [`THREATS_TO_VALIDITY.md`](THREATS_TO_VALIDITY.md) | 偏差、证据不足、医学安全边界 |
| [`research_notes/`](research_notes/) | 分领域长版调查和旧 V5 运行审计 |

### 可执行部分

| 路径 | 内容 |
|---|---|
| [`prototype/contract.py`](prototype/contract.py) | 统一 Candidate API、artifact/query/result 类型 |
| [`prototype/ir.py`](prototype/ir.py) | 无 callback 的封闭表达式 IR |
| [`prototype/candidates/temporal_ledger.py`](prototype/candidates/temporal_ledger.py) | TEL 原型 |
| [`prototype/candidates/causal_state.py`](prototype/candidates/causal_state.py) | finite DBN + finite SCM 原型 |
| [`prototype/candidates/rewrite_open.py`](prototype/candidates/rewrite_open.py) | typed rewrite/open-machine 原型 |
| [`prototype/kernel.py`](prototype/kernel.py) | K0 编排、显式路由和 evidence→model bridge |
| [`prototype/model_subkernel.py`](prototype/model_subkernel.py) | E01–E08 的封闭公共实验模型解释器 |
| [`prototype/bridge_holdout/`](prototype/bridge_holdout/) | 已冻结、源码互异且无跨 import 的 A/B bridge 与 A/B public-panel 实现；作为反证证据保留，不是独立团队复现或合规赢家 |
| [`prototype/benchmark.py`](prototype/benchmark.py) | candidate-view/oracle-view runner |
| [`prototype/isolated_benchmark.py`](prototype/isolated_benchmark.py), [`prototype/isolated_worker.py`](prototype/isolated_worker.py) | fresh `python -I -S` oracle-free candidate 边界 |
| [`prototype/experiment.py`](prototype/experiment.py) | 默认隔离、不可覆盖、原子发布的全量运行记录 |
| [`prototype/metrics.py`](prototype/metrics.py), [`results/metrics-final.json`](results/metrics-final.json) | 原语/LOC/分支/test-dispatch 下界与最终指标快照 |
| [`results/metrics-final-vs-current.json`](results/metrics-final-vs-current.json) | 基线与最终快照的 core/harness/extension 分组比较；基线含前三个扩展，最终新增 test-method 扩展 |
| [`tests/workloads/`](tests/workloads/) | T01–T50 与 E01–E08 独立 JSON |
| [`tests/bridge_holdout/`](tests/bridge_holdout/) | preregistration、sealed corpus、executability audit、A/B runner 与 deterministic redteam probes |
| [`results/bridge-holdout/`](results/bridge-holdout/) | hash 绑定的 A/B 运行、redteam、机器摘要与最终裁决 |
| [`examples/`](examples/) | 三个演示的输入、输出和解释 |
| [`examples/extensions/`](examples/extensions/) | 新疾病/干预/任务投影/检查方法的内容扩展包 |

## 扩展与机械指标

四个 checked-in 扩展包均通过正常的封闭 typed module 注册，不使用 callback、字符串求值或 extension-id 分支：

| 扩展 | 执行能力 | 性质 |
|---|---|---|
| [`disease_acute_kidney_injury_architecture_toy.json`](examples/extensions/disease_acute_kidney_injury_architecture_toy.json) | finite dynamic module/filter | 新疾病/机制架构 toy，不是临床校准 |
| [`intervention_norepinephrine_architecture_toy.json`](examples/extensions/intervention_norepinephrine_architecture_toy.json) | finite SCM population `do` | 新药物/干预架构 toy，不证明疗效 |
| [`task_projection_renal_safety_review.json`](examples/extensions/task_projection_renal_safety_review.json) | TEL read-only task projection | 新任务/检查安全视图 |
| [`test_method_cystatin_c_architecture_toy.json`](examples/extensions/test_method_cystatin_c_architecture_toy.json) | TEL closed derivation rule | 新检查方法架构 toy；仅匹配指定 assay 并保留 value/unit/root |

`tests/test_extensions.py` 验证注册、执行、旧结果稳定和 extension ID 无 runtime 专属分支。最终 metrics 快照报告：

- 4 个 knowledge-extension 文件；
- 在运行时注册四个 knowledge package 不需要修改 7 个 fixed-core 文件，旧结果语义 delta 为 **0**，且 runtime 中没有 extension-id 专属分支；
- 5 个候选/仪器实现的 literal T/E ID、test/oracle dispatch、benchmark/reference import 静态计数均为 **0**；
- harness 的红队修订单独记账，不伪装成知识扩展成本。

这些是机械可审计下界，不证明语义最小、没有全部领域特例或临床正确。`metrics-current.json` 已含前三个扩展，因此它们没有 authoring 前快照；但最终新增的 test-method 扩展有静态 before/after，差分为 knowledge-extension 新增 1、fixed-core added/modified/removed 均为 0，同时另记 harness 修改 5 个文件。完整解释见 [`examples/README.md`](examples/README.md) 和 metrics JSON 的 `limitations`。

## 统一测试在检查什么

T01–T50 覆盖：

- 支持治疗掩盖观察；
- 多时钟与未来信息隔离；
- unknown/conflict/masked/out-of-model；
- 同源证据、派生血缘和撤回；
- 计划/医嘱/执行/停止动作；
- 历史回放与当前理论重释；
- 局部扩展、单位/设备/作用域；
- 循环、无解、多解、数值失败和安全拒绝。

E01–E08 覆盖：

- 过滤、预测与治疗掩盖；
- observation 与 `do` 的反转；
- 同患者 AAP；
- 不规则非线性滞后；
- 相同表型的不同机制；
- 非线性模块组合；
- 组合律；
- 合法反馈、rootless 自证、无解与多解。

每个 workload 把 `candidate_view` 和 runner-only `oracle_view` 分开。证据运行把候选复制到最小 allowlist 临时包，以 fresh `python -I -S` 启动，并只从 stdin 接收序列化 `candidate_view`；judge/reference/oracle 留在父进程。v3 再用 CPython audit hook 限制文件读取并阻断 subprocess/network/native-loader；这是 Python-level confinement，不是 OS sandbox。原型不能凭 manifest 自报能力获得行为 PASS；明确拒绝与行为覆盖分别计账。

`prototype/contract.py` 是 `FORMAL_SPEC.md` 中明确列出的 **K0 可执行子集**，不是完整形式规范。它在复制/哈希/序列化前只接受 exact-builtin JSON-like 图，并以 depth=64、nodes=65,536、bytes=1,048,576 的有限预算拒绝对象子类、callback、循环和非有限浮点；其自由字符串结果轴和 `value: Any` 仍是已披露的 conformance 差距。

## 当前实现的诚实边界

这是一套研究参考实现，不是生产系统。当前明确不声称：

- 真实疾病诊断或治疗效果已经验证；
- 本次三个原子原型中有任何一个已被证明可独立覆盖全部 hard semantics；
- 任意医学模型可自动组合；
- 因果结构可从病历相关性自动识别；
- LLM 抽取永远正确；
- provenance/replay 已在目标临床规模证明性能；
- sealed corpus 的 H01–H30 与 H31–H41 addendum 已作为 41 个完整 executable hidden fixtures 运行或通过；
- post-seal external probe、public numerical panel 或 synthetic mutation self-test 等同于 preregistered hidden PASS；
- 权限、隐私、监管、部署、人因和临床工作流已经解决。

红队发现与修订是交付的一部分。任何未修复的失败都应保留为 typed limitation，而不是用“LLM 能处理”或“以后加一个规则”掩盖。

## 旧 V5/SDE 代码如何定位

仓库中原有 `v5_*` 文件没有被删除。运行审计证明当前 V5 的真实诊断路径主要是 endpoint Gaussian/MVN scoring，并非设计文档声称的完整 PF/SDE；还存在轴注册漂移、未来/适用域污染和 treatment simulator 接口错误。

因此：

- SDE/SSM 仍保留为有价值的 dynamics subkernel 候选；
- 旧 V5 结果不能证明 K0 或新架构正确；
- 新架构不把疾病专属 bonus、hard gate 或病例补丁带入固定核心。

## 什么会解决当前重开的选择

一种能收敛当前选择的直接证据是：存在一个更小的单 calculus，在没有 hidden K0、foreign callback、第二权威事实源或病例特例的条件下，通过全部 hard T/E 测试和新一轮完整 operational bridge holdout，且 extension blast radius、trace 和计算成本不差。本研究只调查了 13 个家族并实现 3 个原子原型；“最小”和“没有单一候选足够”都不是不可约性或全局不可能性证明。

其他推翻条件和下一项判别实验见 [`DECISION.md`](DECISION.md)。
