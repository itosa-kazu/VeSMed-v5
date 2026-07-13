# 架构测试公平性独立审查

> 日期：2026-07-13  
> 范围：只审查当前 `REQUIREMENTS.md`、`CANDIDATES.md`、`ARCHITECTURE_TESTS.md` 的比较公平性；不替主研究选赢家，也不修改主文档。  
> 重点：检查测试是否把“时间—证据账本”预先写成答案，并提出候选无关的机器接口、动态/因果/组合判别实验，以及可复查的计数协议。

## 0. 结论先行

当前三份文档已经比普通“架构打分表”严格得多：它们明确禁止未来泄漏、同源重复计数、未知当阴性、计划当实施，以及测试后给赢家补规则。这些不是事件溯源的私人偏好，而是由临床反例推出的真实语义要求，不能为了“公平”删掉。

但**测试的实现口径存在明显的结构性偏置**：

1. 要求层把若干正确的**行为结果**写成了事件溯源/真值维护的**实现动作**，例如“递归失效”“truth maintenance”“主执行分支”“核心文件数”。重算、重新条件化、持久快照、证明对象或函数式历史只要产生相同语义结果，也应通过。
2. 候选预判表的列几乎都是时间、血缘、开放世界、投影和扩展；没有单列 forward dynamics、partial-observation filtering、`observe` 与 `do`、个体反事实、反馈良定性、组合律。于是 C10 的强项占了多列，其“不自带状态生成/因果”的缺口只压缩成一两个 `P`。
3. 40 项测试中有大量高质量的账本/回放/证据测试，却没有一个带数值或集合 oracle 的前向轨迹测试，没有真正的混杂反转 `P(Y|T)` vs `P(Y|do(T))` 测试，也没有检验模块组合的结合/置换不变性。现状可以选出“最好的可审计账本”，还不能选出“最好的动态临床计算内核”。
4. 当前 trace JSON 强制了类似依赖 DAG 的外形。证明项、lineage polynomial、因子子图、程序执行证书、可验证哈希或可重复计算 capsule 都可能满足血缘，不应先被迫伪装成同一种图。
5. `core primitive count`、`special-case count`、按文件计的 blast radius 尚未定义防作弊规则。一个候选可以把全部语义藏进 `eval(program)` 后声称只有一个原语；另一候选可以因代码拆分良好而在“修改文件数”上吃亏；规则候选还可能把正常领域知识误计成“特例”，而同一知识在 SDE 中叫参数就不计。

因此，当前结果最多支持：**时间—证据—版本层已经得到强测试覆盖；前三候选的动态、因果与组合能力仍未被公平区分。** 在补齐下述实验前，不宜根据现有 PASS 数或 `H/P/F` 表确定赢家。

---

## 1. 审查方法：区分三种“偏置”

本审查不把任何对候选不利的要求都叫偏置，而用三个判准：

1. **需求偏置（不成立）**：若反例独立于实现存在，例如 09:00 判断不能使用 12:00 才可见的结果，那么即使事件溯源天然擅长，它仍是合法硬约束。
2. **实现偏置（需要修）**：如果要求的是“撤回后结果正确”，测试却只接受“递归 invalidation 消息”，就把一种实现误当成语义。
3. **覆盖偏置（需要补）**：所有候选都接受账本测试，但测试集主要攻击 C10 的强项、没有攻击其已知弱项，最终 PASS 数就会系统性偏向它。

测试公平性的目标不是让所有候选通过相同数量，而是让每个候选都面对其核心主张的最强可证伪实验，并让等价实现有同等通过机会。

---

## 2. 对 `REQUIREMENTS.md` 的具体审查

### 2.1 应保留的硬约束

以下内容虽然和事件溯源/类型化规则相容，但有独立临床理由，不构成不当偏置：

- 角色分离、计划不等于实施（`REQUIREMENTS.md:16`、`:28-29`）；
- valid/event time 与 knowledge/available time 分离（`:18-20`）；
- 治疗作用于状态和观察通道的分离（`:21-22`、`:29`）；
- 未知、冲突、不适用、模型外可区分（`:23-24`）；
- 同源改写不得增加支持、未来资料不得倒流（`:25-27`、`:34`）；
- 没有组合律时显式 unresolved，而不是偷用相加（`:30-32`）；
- 关键安全约束不能依赖检索是否想起（`:36`）。

这些要求的公平修法是把 oracle 改成表示无关，而不是降低要求。

### 2.2 存在实现方言的条目

| 位置 | 当前方言/潜在偏置 | 公平的行为 oracle |
|---|---|---|
| `R-EPI-02` 与 `T31` | “依赖图不得有闭环”容易把生理反馈、循环 SCM、递归逻辑与 epistemic 自证混为一谈 | 允许有良定义解的动力学/因果反馈；只禁止**没有独立根证据却增加支持质量**的认识论循环。用根证据消融和固定点结果测试，而不是只看图有无环 |
| `R-TIME-03`、`R-REP-01` | “确定性重放”若解释为逐浮点/逐样本完全相同，会偏向符号系统 | 确定性部分须 bitwise/结构等价；随机系统须固定模型、数据、算法版本和 seed policy 后可重复，或在预注册容差内得到同一目标分布 |
| `R-PROV-01` | “每个中间依赖”若要求枚举每个粒子/浮点操作，会把可审计与自然语言逐步解释混同 | 必须覆盖原始输入、知识/模型版本、查询、假设、近似和可验证计算证书；内部可用证明项、lineage expression、factor subgraph、程序 trace 或 reproducible capsule |
| `R-PROV-02` | “独立来源计数/支持质量”暗示所有系统都做离散投票 | oracle 应是**别名复制不改变结果**、独立新测量可以改变结果；联合概率模型可通过共享 latent/factor 实现，不必输出“票数” |
| `R-PROV-03` | “递归失效”“truth maintenance”是 TMS 的实现术语 | 删除根证据后的查询结果必须等价于从剩余输入 clean rebuild；增量失效还是全量重算只影响成本指标，不影响正确性 |
| `R-COMP-01` | “核心文件/主执行分支修改数为 0”偏向解释型插件架构，也被单文件/多文件布局操纵 | HARD 只要求核心形式签名和语义不改变；schema 自动生成、重新编译、重训练/重索引分别作为 soft blast-radius 分量记录 |
| `R-UNC-01` | 列举状态若被解释为必须有九个 ADT 构造子，会偏向类型/规则系统 | 只要求查询可判别这些法律状态，内部可为 ADT、四值/多值逻辑、带标签测度、约束集或其他无碰撞表示 |
| `R-SAFE-02` | “deterministic invariant 规则”听起来要求 rule engine | 要求适用域内必执行且可验证；可以由 refinement、model checker、constraint monitor、shield 或规则引擎实现。若是外加安全监视器，必须计入该架构组件 |
| `R-MIN-01` | “不可约性论证”没有统一粒度，任意程序/万能图可伪装成一个原语 | 使用第 7 节的正式签名、宏展开和 semantic escape-hatch 协议；报告下界/上界而不是假精确总数 |

### 2.3 当前缺少的要求轴

当前 `REQUIREMENTS.md:76-89` 的“最小合法核心能力”几乎都是 epistemic/time/provenance 能力。若系统目标确实包含“状态怎样产生、随时间变化、被干预、组合”，还需在下一版讨论（不是由本审查直接宣判 HARD）：

- **R-DYN 候选**：给定不规则历史和干预，能输出对潜在状态/可观察量的未来集合、区间或分布；不能只返回最后一条事实。
- **R-CAUS 候选**：`observe(T=t)`、`do(T=t)`、计划 `T=t`、已实施 `T=t` 是不同查询/状态；无法识别时明确列假设或拒绝点估计。
- **R-CF 候选**：个体反事实要说明是否共享事实世界的外生背景，不能把新的未治疗人群模拟冒充“这个患者若未治疗”。
- **R-WELL 候选**：反馈/递归模型必须有明示的解语义；无解、多解、非终止或策略依赖不得静默取一个结果。
- **R-COMPOSE 候选**：同一 wiring 在模块注册顺序或括号改变后应语义等价；若组合非结合/非交换，必须由接口契约显式声明。

---

## 3. 对 `CANDIDATES.md` 的具体审查

### 3.1 统一问卷把问题框成了“怎样存一份可审计记录”

`CANDIDATES.md:9-18` 的十问中，双时间、角色、信息状态、血缘、扩展、投影占绝大部分。只问了“状态在哪里”和“交互怎样组合”，但没有要求候选回答：

- 潜在状态如何从异步观测被过滤/平滑；
- 怎样从历史产生未来轨迹，而不只是重放历史；
- conditioning、intervention、counterfactual 的操作差异；
- 反馈系统何时存在唯一解；
- 预测分布如何校准、近似误差怎样报告；
- 模块组合是否保持行为、是否依赖规则触发/注册顺序。

这会让“记录骨架”与“诊疗计算内核”在问卷中占用不同宽度。

### 3.2 `H/P/F` 表的列选择偏向 C10/C09

`CANDIDATES.md:44-61` 的八列为角色、双时、血缘/撤回、干预、开放、交互、投影、扩展。C10 的核心强项至少直接命中前 3、投影和扩展；它最重要的缺口——不自带状态转移、观察生成、概率过滤、因果反事实——没有独立列，所以只在“干预/交互”中各得到一个 `P`。这不是 C10 分数作假，而是评价轴不平衡。

建议将预判表改成**两个不可互相抵消的面板**：

1. `Epistemic/Audit panel`：角色、多时间、血缘、撤回、版本、开放世界；
2. `World/Computation panel`：潜在动力学、观测模型、过滤、干预、反事实、反馈良定性、非线性交互、组合律、任务读出。

只有两个面板都过硬线的**完整架构实例**才进入端到端决赛；不能用面板 A 的多个 H 抵消面板 B 的空白。

### 3.3 候选“家族宽度”不一致

- C10 已是“事件溯源 + bitemporal + 增量视图”的组合实例；
- C09 是“类型系统 + ADT + 重写”的宽组合；
- C05 把 SSM/POMDP/SDE 合在一行，但通常按不带证据外壳的裸模型受审；
- C14 把多种组合数学放在一行；
- C15 又允许任意混合。

因此 `H/P/F` 必须针对**冻结的 architecture instance manifest**，而不是宽窄不一的家族名。manifest 至少列出：核心对象/操作、伴随层、外部 solver、存储层、安全监视器、adapter 中的语义逻辑。任何“外壳补齐”都必须计入该实例，但不能因此说原家族原生具有该能力。

### 3.4 当前前三方向会被现有测试退化成“谁的账本更好”

`CANDIDATES.md:69-72` 的前三方向可暂称：

- **P1**：双时间事件/证据账本 + 类型化增量规则/TMS；
- **P2**：双时间证据外壳 + 动态因子/状态空间模型；
- **P3**：类型化时态超图 + 局部重写/因果机制模块。

P1、P2 都显式带证据外壳，P3 也很容易用图承载 trace。若只跑现有测试，主要差别会落在外壳的工程细节，而不是规则演化、动态过滤和因果重写的本质差异。后续必须用第 6 节实验正面攻击：

- P1 的连续/随机动力学、概率依赖和规则次序；
- P2 的 `do`/反事实语义、局部组合与撤回成本；
- P3 的执行策略、循环良定性、概率/轨迹精度和组合一致性。

这只是攻击面，不是预判谁会失败。

---

## 4. 对 `ARCHITECTURE_TESTS.md` 的具体审查

### 4.1 覆盖不平衡

现有 T01-T40 很适合淘汰“病历字段表 + last-write-wins + 普通向量”这类静默错误系统。问题是：

- T06、T10-T13、T19、T23-T25、T27、T31-T34、T36、T40 的主要 oracle 都在证据身份、认识论状态、多时间、撤回、版本或缓存一侧；
- T01-T05、T07-T09、T16-T18、T35 涉及状态/观察/因果，但多数只要求“能表示”或“不犯明显错误”，没有轨迹或概率 oracle；
- 真正直接测试组合执行的主要是 T16、T38，T39 测模型不一致；T21/T22 测局部添加，却没有检查组合后的行为是否保持；
- 没有 forward forecast、filter/smoother 区分、混杂反转、abduction-action-prediction、反馈唯一解、组合结合性/顺序不变性测试。

所以现有测试应继续保留为 **Audit/Epistemic suite**，另增一个规模相近、独立报告的 **Dynamics/Causality/Composition suite**。不要把两套 PASS 数相加成单一分数。

### 4.2 当前接口本身带有事件/TMS 外形

`ARCHITECTURE_TESTS.md:13` 和 `:94-115` 要求所有候选输出“有效断言集合、source roots、justifications 节点、known_from”。这些信息有合理语义，但固定 JSON 外形会造成三类问题：

1. 事件日志/TMS 只需直出内部结构，PPL/因子/证明系统要先重写成假 DAG；
2. `source_roots` 集合表达不了“两个根通过 AND/OR/重复路径如何组合”，也不能单独表示概率依赖；
3. 要求完整列出中间节点会让粒子/采样/数值 solver 产生巨大 trace，却不一定增加可审计性。

应将 trace 拆成：

- **统一 audit envelope（强制）**：输入根身份、知识/模型/查询版本、时间 cutoff、假设、近似、随机性政策、结果状态；
- **candidate-native dependency witness（开放）**：DAG、proof term、semiring polynomial、factor slice、program trace、Merkle/replay capsule 等；
- **统一 verifier 行为（强制）**：别名复制、根证据消融、知识版本切换和 clean rebuild 等 metamorphic 检查。

血缘因此由“必须长得像某种图”改成“必须能被统一实验验证”。数据库 provenance 已有不只 DAG 一种表示，例如 provenance semiring；这正说明 trace 外形不应预设。[Green, Karvounarakis & Tannen, PODS 2007](https://doi.org/10.1145/1265530.1265535)

### 4.3 “相同输入事件”应改成“相同语义工作负载”

`ARCHITECTURE_TESTS.md:119` 的意图正确，但“输入事件”这个词会把事件流当成唯一原生输入。公平协议应提供：

- 初始 `CaseSnapshot`（带身份和多时间的输入项集合）；
- 一组 `CaseDelta`（新增、修订、撤回、知识版本切换）；
- 每一步应回答的 `QuerySpec`。

候选可把 delta 追加为事件、持久化新快照、重新构图、重新条件化程序或全量重算。正确性轨只比较结果；增量成本轨再区分算法。

---

## 5. 候选无关的机器测试接口

### 5.1 原则

1. **接口描述操作语义，不规定内部存储。** `Revision` 只是“某一输入/知识版本的可查询状态句柄”，不意味着事件日志。
2. **一个统一 `query` 支持多种查询模式。** 不强迫候选一定有 `simulate()`、`do()` 这样的内部方法名。
3. **正确性与增量性分开。** `apply_delta` 可由候选全量重建；只要与 clean rebuild 等价就通过正确性，耗时/重算范围另记。
4. **允许多种不确定性输出，但能力等级分开。** 精确值、可达集合、区间、分布/样本均合法；不能把宽到无用的集合等同于校准概率。
5. **adapter 只能做语法转换。** 单位换算、因果边、缺失解释、去重、规则执行等任何语义若写在 adapter，计入该候选实例。

### 5.2 建议的 Python `Protocol`

```python
from typing import Protocol

class ArchitectureUnderTest(Protocol):
    def manifest(self) -> "ArchitectureManifest": ...

    def build(
        self,
        knowledge: "KnowledgePackage",
        build_policy: "BuildPolicy",
    ) -> "BuildResult": ...

    def load_snapshot(
        self,
        build: "BuildHandle",
        snapshot: "CaseSnapshot",
    ) -> "RevisionResult": ...

    def apply_delta(
        self,
        revision: "RevisionHandle",
        delta: "CaseDelta",
    ) -> "RevisionResult": ...

    def query(
        self,
        revision: "RevisionHandle",
        query: "QuerySpec",
    ) -> "QueryResult": ...

    def extend(
        self,
        build: "BuildHandle",
        patch: "KnowledgePatch",
    ) -> "ExtensionResult": ...

    def verify_witness(
        self,
        result: "QueryResult",
        witness: "NativeWitness",
    ) -> "WitnessCheck": ...
```

`query.mode` 建议是：

```text
STATE_ESTIMATE       给定当时可见历史，估计当前/过去潜在状态
FORECAST             在无额外动作或指定 policy 下预测未来
OBSERVATIONAL        P/query(... | observed treatment/value)
INTERVENTIONAL       P/query(... | do(action/value))
COUNTERFACTUAL       对同一病例做 abduction-action-prediction
TASK_PROJECTION      诊断/严重度/安全等临时读出
```

候选若不支持某模式返回：

```json
{
  "status": "unsupported",
  "boundary": "counterfactual_not_defined",
  "reason": "..."
}
```

显式 unsupported 优于静默近似，但若该模式属于决赛硬要求，仍是未通过，不得把“诚实”误记成 PASS。

### 5.3 传输对象不是候选核心原语

```json
{
  "input_id": "obs-17",
  "semantic_role": "observation",
  "subject": "patient-1",
  "concept": "MAP",
  "value": {"number": 70, "unit": "mmHg"},
  "times": {
    "occurs": "t1",
    "collected": "t1",
    "available": "t1+2h",
    "recorded": "t1+3h",
    "valid": ["t1", "t1+30m"]
  },
  "context": {"support": ["norepinephrine@0.4"]},
  "source_identity": "device-A/run-882",
  "reliability": {"kind": "declared", "value": 0.98}
}
```

该 JSON 只是 benchmark transport。候选可以把它编译成事件、关系、变量、token、项或程序 choice；不得因 transport 有字段就声称内部原生支持这些语义。

### 5.4 统一结果 envelope，开放内部证明形式

```json
{
  "status": "ok|unsupported|rejected|out_of_model|insufficient",
  "answer": {
    "form": "exact|interval|reachable_set|distribution|samples|ranked_hypotheses",
    "payload": {},
    "calibration_claim": "none|bounded|probabilistic"
  },
  "audit": {
    "input_root_ids": ["..."],
    "knowledge_ids": ["..."],
    "model_digest": "...",
    "query_digest": "...",
    "valid_cutoff": "...",
    "known_cutoff": "...",
    "assumptions": [],
    "approximations": [],
    "randomness_policy": {"algorithm": "...", "seed_or_stream": "..."}
  },
  "native_witness": {
    "media_type": "candidate-defined",
    "payload_or_digest": "..."
  }
}
```

统一 runner 不解释 candidate-native witness 的每个节点，而通过以下关系检查它：

- 删除未列入 roots 的输入，结果不应无故改变；
- 删除列入 roots 的输入后，结果变化或 witness 给出“仍有独立充分路径”；
- 将同一 `source_identity` 复制成别名，结果保持不变；
- 用相同 snapshot clean rebuild，与 delta 更新结果等价；
- 固定 manifest、输入、knowledge、query 和 randomness policy 后可重现。

这些属于 metamorphic/property-based testing：重点是多个运行之间必须保持的关系，而不是为每个候选硬写内部结构。[Claessen & Hughes, QuickCheck, ICFP 2000](https://doi.org/10.1145/357766.351266)；[Chan et al., Metamorphic Testing, 1998](https://researchportal.hkust.edu.hk/en/publications/application-of-metamorphic-testing-in-numerical-analysis/)

### 5.5 两条赛道，防止“共同外壳”偷换原生能力

应同时报告：

- **Track A：端到端架构实例。** 每个候选自己带齐证据、时间、动态、因果、组合和安全层；所有组件都计数。用于判断能否成为完整系统。
- **Track B：机制内核判别。** runner 提供同一只读 snapshot/query harness，只比较动态、因果、组合行为。harness 不算任何候选的原生能力，结果也不能用来声称某候选通过 Track A 的血缘/回放要求。

再做一次 **ablation**：移除候选声明的 companion layer，看哪些能力是本家族原生、哪些是借来的。这样既不会免费把事件外壳送给 P2，也不会因 P1 缺少数值模块而只测账本。

---

## 6. 八个有区分力的动态/因果/组合实验

以下全部使用**合成机制夹具**，只验证架构语义，不声称具有真实临床参数有效性。每个夹具公开概念和结构承诺，隐藏多组参数/seed 用作 holdout，防止按预期答案硬编码。`observe` 与 `do` 的不同是结构因果语义的基本要求，而不是某个候选的专用术语；干预分布与观察条件分布本来就需区分。[Pearl, 2010](https://pmc.ncbi.nlm.nih.gov/articles/PMC2836213/)

### E01. 支持治疗掩盖下的过滤、停药预测与反事实

**夹具。** 潜在灌注损害 `S(t)` 随时间演化；去甲肾上腺素 `U(t)` 一方面改变 `S` 的 drift，另一方面即时抬高 MAP 观察 `Y(t)`。不规则测量序列为：低 MAP → 开始 U → MAP 正常但 S 仍高 → 停 U。

**统一查询。** 

1. `STATE_ESTIMATE(S, t1 | history)`；
2. `FORECAST(Y, t2:t3 | stop U)`；
3. `COUNTERFACTUAL(Y, t1:t3 | do(U=0))`。

**oracle。** 正常 MAP 不能令 S 直接归零；停药后的风险/轨迹应与持续用药不同；同一时点“自然 MAP 正常”与“由 U 正常”不得碰撞。数值候选与隐藏 simulator 比较区间覆盖/Wasserstein 或轨迹误差；集合候选检查真轨迹是否在非平凡可达集内。

**区分点。** P1 是否只保存事件还是定义了真正演化；P2 是否正确分离 transition/observation；P3 的重写/图执行是否产生稳定、与顺序无关的轨迹。

### E02. 混杂导致的 `see`/`do` 符号反转

**夹具。** 隐藏严重度 `S` 同时增加接受治疗 `T` 的概率和坏结局 `Y`；治疗本身降低坏结局。由此可能出现：接受治疗者观察上更差，但干预治疗是有益的。

**统一查询。** 同时请求 `OBSERVATIONAL: P(Y|T=1)` 与 `INTERVENTIONAL: P(Y|do(T=1))`，再请求 `do(T=0)`。

**oracle。** 观察关联与干预效应方向按隐藏生成 SCM 明确不同；输出必须列出采用的因果/识别假设。把 conditioning 当 intervention 是 HARD fail；声明缺少因果语义是 explicit unsupported。

**区分点。** 直接攻击 P1 的规则相关性、P2 的普通状态模型是否冒充因果、P3 的“因果边”是否真的改变执行语义而不只是标签。

### E03. 个体反事实必须共享事实世界的外生背景

**夹具。** 患者对药物的个体反应 `R` 未直接观测；已经观察到该患者治疗后的轨迹。询问“同一患者若未治疗”，而不是抽一个新的未治疗患者。

**统一查询。** 

- `COUNTERFACTUAL(Y_no_treatment | factual history, same subject)`；
- `INTERVENTIONAL(Y | do(T=0), population)`。

**oracle。** 两者通常不相同；个体反事实必须先用事实证据更新 `R`，再在反事实世界共享相应外生背景。若候选只会新跑一条独立模拟，结果会与 population intervention 错误碰撞。

**区分点。** 检验真正的 abduction-action-prediction、world identity 和 uncertainty carry-over；这不是账本重放能单独回答的。

### E04. 不规则采样下的非线性反馈、滞后和脉冲干预

**夹具。** 病原负荷 `B(t)` 具 logistic growth，炎症 `I(t)` 对 B 饱和响应，CRP 观察有滞后；短时抗菌药 pulse 降低 B，但 I/CRP 可继续上升一段时间。隐藏参数生成多组稀疏、不规则 observation schedule。

**统一查询。** filtering、过去状态 smoothing、未来 24h forecast；并对“同一值、不同上升/下降相位”做成对输入。

**oracle。** filtering 不可偷看未来，smoothing 可使用查询时已知的后续观察；相同 CRP 绝对值但相位不同应有不同未来；短 pulse 后允许 CRP 滞后峰值。报告近似误差/seed policy。

**区分点。** P1 的离散规则是否需要大量时间桶特例；P2 的动态/观测模型是否原生；P3 是否有明确连续/混合时间执行语义。

### E05. 同表型、两机制、选择性干预后的解释分叉

**夹具。** 感染机制 `M_inf` 与无菌炎症机制 `M_auto` 都可产生发热/CRP；退热药只改变温度表现，抗菌药只改变 `M_inf/B`。初始观察让两解释并存，随后施加不同干预并观察轨迹。

**统一查询。** 每个时点输出 hypothesis set/weights、机制状态、未来观察；交换干预顺序再查询。

**oracle。** 退热后的体温正常不能选择性消灭任一病因；抗菌药后的机制特异性响应可以改变两解释相对支持；如果证据仍不足须保留二者。干预顺序只在模型声明的状态依赖处产生差别。

**区分点。** 同时检查多解释、机制身份、动态更新与 selective intervention，避免“图里画了两条边”但运行时仍按单标签规则更新。

### E06. 三模块非线性共病/药代组合

**夹具。** 三个独立发布的模块：感染负荷 A、CKD/清除 B、药物 PK/毒性 C；接口只暴露 `burden`、`renal_clearance`、`drug_concentration` 等 typed ports。额外 interaction module I 声明饱和清除和浓度—杀菌/毒性曲线。

**统一查询。** 分别构建 A、A+C、A+B+C、A+B+C+I，比较病原负荷、药物浓度和毒性 hazard；随后将 B 替换成同接口的新肾功能模块。

**oracle。** 没有 I 时不得静默假定临床上未知的组合律；有 I 时不能退化为三个独立贡献相加；替换 B 不修改 A/C/core，接口不匹配要在 build 时失败。

**区分点。** P1 是否需要疾病对专属规则；P2 是否能局部增广 state/factor 而不全图重写；P3 的 typed wiring/重写是否真的减少 blast radius。

### E07. 同一 wiring 的括号、注册顺序和并发顺序不变性

**夹具。** 用 E06 相同模块和显式 wiring，生成：`(A ⊗ B) ⊗ C`、`A ⊗ (B ⊗ C)`、随机 module registration order，以及两个语义独立更新的交换顺序。

**oracle。** 若 manifest 声明组合为结合/独立更新可交换，则结果在预注册容差内等价；若不满足这些律，必须在接口契约声明并给出受影响边。不能让文件加载顺序、hash iteration 或规则 agenda 偶然决定临床结果。

**区分点。** 直接暴露重写非合流、规则调度依赖、图合并冲突、状态向量索引/solver 顺序问题；也验证组合数学主张是否落到执行行为。

### E08. 合法生理反馈与非法认识论自证必须可区分

**夹具。** 两个拓扑相似的循环：

1. 有外部输入、收缩系数小于 1 的负反馈动力系统，存在唯一稳定固定点；
2. `A supported_by B`、`B supported_by A`，没有任何原始根证据。

再加入第三个版本：反馈方程无解或多解。

**oracle。** 第一个应被接受并收敛/给出明确解；第二个不得凭循环生成支持；第三个必须返回 non-unique/unsolved/strategy-dependent，不能静默选择一个。单纯“有环即拒绝”与“所有环都放行”都失败。

**区分点。** 同时攻击 P1 的递归规则语义、P2 的反馈良定性和 P3 的 typed edge/重写语义，且不会偏向无环账本。

### 6.1 覆盖矩阵：为何这八项不只是“再测一遍账本”

| 实验 | 动态/部分可观测 | 因果/反事实 | 组合/执行律 | 对 P1 的主要攻击 | 对 P2 的主要攻击 | 对 P3 的主要攻击 |
|---|---:|---:|---:|---|---|---|
| E01 掩盖、停药、预测 | 强 | 中 | 弱 | 事件存在不等于有演化 | transition/observation 分离 | 重写轨迹与执行顺序 |
| E02 `see`/`do` 反转 | 弱 | 强 | 弱 | 相关规则是否冒充因果 | conditioning 是否冒充 intervention | 因果标签是否有运行语义 |
| E03 个体反事实 | 中 | 强 | 弱 | 重放是否冒充反事实 | 是否共享个体外生背景 | 多世界身份/重写隔离 |
| E04 非线性反馈与滞后 | 强 | 中 | 中 | 时间桶/规则特例膨胀 | filtering/smoothing/forecast | 连续或混合时间语义 |
| E05 两机制选择性干预 | 强 | 强 | 中 | 单标签与规则竞争 | 多模型 belief 更新 | 机制边、干预边的类型与执行 |
| E06 三模块交互 | 中 | 中 | 强 | 疾病对专属规则数量 | state/factor 局部增广 | typed wiring 是否真局部 |
| E07 括号/顺序不变 | 中 | 弱 | 强 | agenda/规则次序 | 索引/solver/因子注册次序 | 合流性与组合律 |
| E08 合法反馈 vs 自证 | 强 | 中 | 中 | 固定点与无根增信 | 解存在/唯一性 | edge kind 与循环重写语义 |

这里的“攻击”不是给候选预扣分，而是说明每一项都有可能推翻其核心主张。任何候选都可用通用补充层通过，但补充层必须在 manifest、primitive profile 和 blast radius 中显式出现。

### 6.2 建议的判定维度（不压成总分）

每个 E-test 分别报告：

- **semantic correctness**：关系/符号/集合覆盖是否满足；
- **quantitative fidelity**：若声称概率/数值能力，误差、覆盖与校准；
- **identifiability honesty**：假设不足时是否拒绝点估计；
- **order robustness**：注册、调度、seed 与近似变化的稳定性；
- **trace/audit**：输入、模型、干预和假设是否可追；
- **extension cost**：完成夹具需增加哪些通用组件/领域承诺/特例。

一个只给宽可达集的候选可以满足安全包含，但不能因此获得“概率校准能力”；一个概率候选也不能用较好 RMSE 抵消未来泄漏或 `see=do` 的硬错误。

---

## 7. 公平的 `Core primitive count`

### 7.1 不报一个裸整数，先冻结架构边界

每个候选提交 `ArchitectureManifest`：

```text
core formal signature
core interpreter/execution semantics
required stores/solvers/runtimes
companion layers
semantic adapters
safety monitors
domain knowledge packages
generated artifacts and caches
```

没有 manifest，就无法判断“这个能力属于核心、模块、adapter 还是测试 harness”。

### 7.2 计数单位

核心原语是满足以下条件的**语义构造族**，不是字段、类、文件或实例：

1. 出现在固定核心的 grammar/signature 中；
2. 有独立 formation/typing/transition/query law；
3. 删除后，至少一个已声明能力无法用其余原语做语义保持的宏展开；
4. 对所有医学内容参数化，而不是某个疾病/药物实例。

报告向量而非一个可随意加权的总数：

```text
P = (
  object/value constructors,
  state/update operators,
  time/visibility operators,
  uncertainty/belief operators,
  composition/wiring operators,
  query/readout operators,
  built-in invariant/constraint forms,
  foreign semantic escape hatches
)
```

### 7.3 防止“万能原语”作弊

- `Graph(node, edge)` 若所有合法性、更新、概率和时间都由 edge callback 决定，不能只算“节点+边”。callback 是 **foreign semantic escape hatch**，其承担的不同语义族必须展开列示。
- `Program`、`Rule(body)`、`Factor(fn)`、`Component(update)` 同理。它们可各算一个高阶构造子，但还要报告其 unrestricted host-language surface、可验证边界和本轮实际使用的 semantic modes。
- 反过来，同一 `Observation<T, Context>` 的 100 个 analyte 实例只算一个核心构造族；疾病、药物、参数数量计入知识规模，不计核心原语。
- UUID、JSON、哈希、普通集合/映射、序列化等共同基础设施不计核心；若某候选赋予它们独有语义，再计入相应构造。

### 7.4 宏展开与争议

若候选声称原语 X 可由 Y/Z 派生，必须给出：

- 双向编码或至少行为保持映射；
- 对受影响测试的等价证明/性质测试；
- 编码引入的不变量和失败方式。

两名独立 reviewer 对计数分歧时报告 `[lower_bound, upper_bound]` 和争议项，不用会议强造一个精确数字。最小性只用于 Pareto 比较，不能抵消硬失败。

---

## 8. 公平的 `Special-case count`

### 8.1 先把四类东西分开

```text
K_shared   冻结的领域承诺：因果边、观测关系、转换律、单位转换等
K_extra    某候选额外引入的领域假设
G_general  候选的通用架构/算法规则
S_patch    为某测试/候选缺口新增且不可普遍复用的语义补丁
```

规则系统中的一条“抗菌药改变培养敏感性”与 SSM 中的一条 observation equation、因子图中的一个 factor，应都计为同一个 `K_shared` 领域承诺，**不能只把 rule 叫特例**。语法行数、参数数和专家填写负担另报。

### 8.2 `S_patch` 的可执行判定

冻结测试协议后新增的语义条款满足任一条件，即记一个 special case：

1. applicability predicate 引用了 case/test ID、期望答案、具体 fixture seed；
2. 引用了不在 `K_shared` 的具体医学 concept ID，且不能说明一般作用域；
3. 使用只为越过某个测试而设置、无独立依据的阈值/bonus/gate；
4. adapter 为该候选补做了本应由核心完成的去重、时间过滤、因果解释或组合；
5. 声称“通用”但在两个预注册的不同模块/隐藏参数 holdout 上不能原样复用。

一个补丁散落 5 个文件仍算一个语义特例；一张表里 20 个互不相干的 keyed exceptions 算 20 个，不能因只写一个 dispatch loop 算 1。

分别报告：

```text
S_case_id       直接面向测试/病例
S_concept       面向具体词汇且不在共享知识包
S_numeric       无依据阈值/bonus/gate
S_adapter       藏在适配层的语义
S_execution     为修正规则顺序/solver/图遍历而加的窄分支
```

### 8.3 防止测试后伪装成通用规则

- 保留隐藏参数、别名、模块注册顺序和第二组医学概念的 holdout；
- 补丁必须在不知道 holdout 期望值时提交；
- 若它通过至少两个结构相同、词汇不同的 holdout，可从 `S_patch` 重新分类为 `G_general`，但计一次 core revision，并重新跑全部回归；
- 任何删弱真实输入、把未知当阴性、给预期病因加分的行为直接 HARD fail，不只增加 special-case count。

---

## 9. 公平的 `Extension blast radius`

### 9.1 为什么文件数不能作为主指标

同一语义变更，在单体文件中可能只改 1 个文件，在良好模块化项目中可能更新 schema、生成器、文档和测试 4 个文件；按文件数会奖励糟糕布局。解释型系统可能源码 0 修改但重训练全部模型，成本也不能记为 0。

### 9.2 使用 blast-radius 向量

每次加入 `new_disease`、`new_drug`、`new_test_method`、`new_interaction` 后，报告 direct 与 transitive 两层：

```text
B = (
  core_signature_changes,
  core_semantics/algorithm_units_changed,
  semantic_adapter_units_changed,
  existing_knowledge_modules_changed / total,
  persistent_data_migrations,
  generated_schema/artifacts_invalidated / total,
  models_retrained_or_refit / total,
  historical_records_reprocessed / total,
  caches/indexes_rebuilt / total,
  existing_tests_modified,
  existing_tests_failed,
  wall_clock_and_peak_memory
)
```

其中：

- `core_signature_changes > 0` 是核心稳定性的主要警报；
- 自动 schema regeneration 与手工核心语义修改分开；
- 全图重新推断、全量重训练/重索引即使源码 0 diff，也计入 transitive blast；
- 新扩展自己的新测试不算“修改既有测试”，删改旧断言才算；
- `git diff --stat`、文件数、LOC 只放附录，不能作为主比较。

### 9.3 语义单元与依赖图

候选 manifest 为 artifact 标注稳定 ID 和类别：`core-contract`、`engine`、`adapter`、`knowledge-module`、`model-artifact`、`migration`、`cache/index`、`test`。扩展前后做结构 diff，并沿声明依赖图计算受影响闭包。这样单文件和多文件架构比较的是同一语义单位。

建议盲测：由未参与候选实现的人只拿公开扩展包和文档完成一次扩展，记录其触及的语义单元、时间和误用；这比作者自己声称“只需加一行配置”更可信。

---

## 10. 公平运行与裁决协议

1. **先冻结 requirements version、test version、domain commitment ledger 和候选 manifest。** 每次变更都新建 run ID，不覆盖旧结果。
2. **共享的是语义承诺，不是同样的规则行数。** 每个 candidate-native 编码须由独立 reviewer 做 commitment 对齐；额外假设进 `K_extra`。
3. **公开训练夹具，隐藏参数/顺序/同构词汇 holdout。** 避免规则 hardcode，也避免数值模型只拟合一个 seed。
4. **三种 oracle 并用：**确切预期、关系/metamorphic、参考 simulator 的数值/集合容差。测试必须声明是哪一种。
5. **随机候选跑多 seed。** 不用“大家 seed=42 的一条样本”判断；报告分布、置信区间和失败 seed。确定性候选照常只跑确定结果。
6. **能力分层，不把所有输出压成概率。** `qualitative relation`、`reachable/bounded set`、`calibrated distribution` 分栏。宽集合通过安全包含，不等于通过概率精度。
7. **显式 unsupported 不是静默失败，但也不是通过必需能力。** 单列 capability gap。
8. **补丁预算不按语法单位给。** 所有候选可使用相同 `K_shared`；任何 `K_extra/S_patch` 全量登记。不要规定“每家最多 10 条规则”，因为一条 rule、factor、ODE term 信息量不同。
9. **Track A/Track B/ablation 分开报告。** 不能把 harness 能力算成候选原生能力。
10. **不汇总成一个加权总分。** 先硬约束淘汰，再分别画 Audit/Epistemic 与 Dynamics/Causality/Composition 的 Pareto 前沿。

---

## 11. 建议给主研究的最小下一步

在不改动现有 40 项测试的前提下，最小且有区分力的下一步是：

1. 先实现第 5 节的 `ArchitectureUnderTest` runner 骨架和 `CapabilityResult`；
2. 把 T24（撤回）改写为“delta 结果 = clean rebuild”关系测试，证明接口不偏向 TMS；
3. 首先落地 E01、E02、E06、E07、E08 五项：分别覆盖动态过滤/预测、因果 `do`、非线性交互、组合律、反馈良定性；
4. 为 P1/P2/P3 各冻结一个 architecture manifest，明确所有 companion layer；
5. 运行前由独立 reviewer 对齐 `K_shared`，运行后按第 7-9 节给出 primitive profile、special-case ledger 和 blast-radius vector；
6. 只有当五项都产生机器结果后，才更新 `CANDIDATES.md` 的 `H/P/F`，并新增 World/Computation panel。

**当前可以下的审查结论：**现有文档没有不当弱化安全要求，但其机器化口径和覆盖结构会系统性高估事件溯源/规则型候选的完整性。修复方向不是减少账本测试，而是把账本测试改成实现无关的行为 oracle，并以同等强度新增动态、因果、反馈和组合判别实验。
