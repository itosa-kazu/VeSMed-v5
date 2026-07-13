# Checkpoint 1 独立第一原理与要求红队

> 日期：2026-07-13  
> 范围：只定义问题和筛选架构所需的要求；**不选择 SDE、向量、图、概率程序、事件系统或任何混合架构**。  
> 结论强度：这里提出的是候选架构必须接受的可反驳合同，不是“某种实现已经正确”的证明。

## 0. 先给结论

用户原列的 15 项方向大体正确，但还不能直接成为硬约束清单，原因有四类：

1. 有些条目把一个**必要的语义区分**写成了某种实现形式。例如“证据守恒”不应理解成数值不变，而应改为“血缘、依赖和根来源不可伪造”；“同一个底层患者状态”也不能预设真的存在一个任务无关、可完整识别的唯一状态对象。
2. 有些条目把“必须能表达”与“运行时必须执行/阻止”混在一起。临床安全不变量若只存在于文档或 prompt 中，而执行器可以绕过，就不算满足。
3. 有些条目过强。新知识不可能保证永远只改一个文件；任意非线性交互也不可能在有限系统中自动获知。真正的硬要求应是**保守扩展、显式依赖、版本化和遇到未建模交互时可见失败**。
4. 有关键遗漏：实体与标本身份、单位和测量学类型、观察机会/选择过程、纠错与撤回、知识/术语/模型版本、因果主张的可识别性、事实与价值/目标的分离、矛盾不爆炸、静默丢失禁止、幂等摄取，以及受权限遮蔽的信息不能被当作阴性。

因此，当前证据支持的不是某一种数据结构，而是以下最低结论：

- 患者现实、关于现实的观察/陈述、由证据产生的推断、计划/医嘱、实际行为、以及任务目标必须**可区分且不可静默互换**。
- 至少需要同时处理患者过程时间、信息可用时间和记录/版本时间；单一 timestamp 不够。
- 任何结论必须绑定输入证据、依赖结构、知识/模型/术语版本和任务；provenance 不能被“可解释文本”替代。
- “未见、未问、未做、做了但无法评价、权限遮蔽、冲突、超出模型”不是同一种 unknown，更不是 false。
- 诊断概率或状态估计不能直接推出治疗动作；事实、因果效应、目标/偏好、授权和已实施动作是不同问题。
- 固定内核只能保证语义合同和失败可见性，不能单独保证医学知识正确、因果效应可识别、模型校准或临床净获益。

最强反对意见是：上述要求本身容易把答案偷偷推成“事件日志 + 类型系统 + provenance 图 + 因果/概率模型”。为避免这一偏差，本笔记只把它们写成**外部可观察的不变量**；候选可以用表、图、项重写、逻辑、进程、张量加类型侧车或其他形式实现，只要同一测试能证明不变量。

---

## 1. “固定核心架构”在本研究中的可检验定义

固定核心不是具体医学词表，也不是存储产品。它是一个对所有合法实现都成立的**语义与执行合同**：

1. 哪些临床上不同的东西不能压成同一个状态；
2. 哪些转换是合法的，转换需要哪些输入与版本；
3. 某一时点哪些信息有资格进入计算；
4. 派生、修订、撤回和冲突如何传播；
5. 观察、干预、计划、判断和建议分别意味着什么；
6. 不知道、无法表示、超出适用域时必须怎样失败；
7. 新医学内容加入时，旧内容与旧运行结果如何保持可解释。

### 1.1 三种“满足”不能混用

对每项要求，后续候选评审必须分别回答：

- **R（Representable）可表示**：数据结构能否写进去；
- **E（Enforceable）可强制**：非法状态/操作能否被类型、验证器或运行时阻止；
- **D（Demonstrated）已实证**：原型和统一测试是否真的通过。

只证明 R 不等于满足硬约束。例如，一个万能 JSON 字段当然可以“写下 provenance”，但如果推断器可以在没有 provenance 时继续运行，就没有满足 E；如果从未跑过删除根证据的测试，就没有满足 D。

### 1.2 硬约束、软约束和反目标

- **硬约束 H**：失败会造成至少一种不可接受情形——临床意义不同的历史被碰撞、未来信息泄漏、证据被凭空制造、行为与计划混淆、无法审计、或系统在不支持时静默给出结论。候选若不能在其宣称的适用范围内强制该约束，应淘汰。
- **软约束 S**：可比较的工程质量/研究目标，如原语数量、作者负担、性能、扩展 blast radius。应进入 Pareto 比较，不应任意阈值一票否决。
- **混合 M**：条目中一部分是 H，另一部分是 S；必须拆开。
- **反目标 A**：不能以它为优化目标，或不能把它冒充正确性。例如“所有患者都强制映射到一个已知病”“用最少 class 数量赢得最小性”。

### 1.3 何谓最小临床反例

本笔记使用的反例只要求两个世界：输入在表面上很像，但正确下游行为不同。若某架构把二者压成同一个内部状态，且下游无法恢复差异，即产生 **collision**，证明其表示或语义不足。反例不是完整病例，也不用于证明某个疾病模型。

---

## 2. 从第一原理出发的前提，而不是从候选技术出发

以下前提来自研究对象本身；拒绝任一前提都需要缩小系统目标，而不是换一种实现名词。

| 前提 | 普通中文 | 直接推出的约束 |
|---|---|---|
| P1 部分可观察 | 患者在病历之外仍有真实过程；记录只能提供有误差、有选择的窗口 | 观察不能等于状态；未知必须保留 |
| P2 测量是过程 | 数值由对象、时间、标本、方法、设备、支持治疗及采集行为共同产生 | 值必须带适用上下文；测量模型可被干预改变 |
| P3 记录可错且可改 | 陈述、结果和编码会延迟、复制、冲突、纠正、撤回 | 血缘、版本、冲突、失效传播与回放是必要的 |
| P4 患者时间与信息时间不同 | 事情可能早已发生，但系统后来才知道；后来还能知道“过去写错了” | 有效/发生时间、可用时间、事务/版本时间不可压成一个时钟 |
| P5 行为有生命周期 | “想做、建议做、下医嘱、开始做、做完、没做、做了多少”对患者影响不同 | 计划/请求/授权/实施/结果必须可区分 |
| P6 生成关系多对多 | 同一机制可生出多个所见；同一所见可由多个机制产生 | 不能把一项所见唯一绑定一病，也不能把相关所见当独立投票 |
| P7 知识开放且可修订 | 新病、新检查、新机制会出现，旧理论也会被纠正 | 开放世界、保守扩展、知识版本和重新解释旧证据 |
| P8 任务不同 | 诊断、危险度、用药安全和预后使用不同目标、时间窗和损失 | 不存在预设的唯一万能距离；投影需显式任务合同 |
| P9 计算会生成新信息产品 | 正规化、规则、模型、LLM 都会把输入变成派生产物 | 派生产物不是新独立证据；需绑定算法与输入版本 |
| P10 决策含价值判断 | 即使疾病概率相同，不同目标、偏好、禁忌和资源会导致不同动作 | “是什么”不能自动变成“应该做什么” |
| P11 有限系统必有边界 | 任何有限词表和模型都有未覆盖概念、交互和人群 | 显式 unsupported/OOD/abstain，不得静默近似 |
| P12 临床使用要求问责 | 结论可能改变真实行为，错误不只是排序损失 | 关键路径必须可审计、可重放、可阻止非法消费 |

这些前提**不推出**状态必须是连续向量、图、概率分布或事件集合。它们只推出候选必须保存哪些区别、允许哪些修订、在什么情况下拒答。

---

## 3. 对原 15 项要求逐条红队

### R1 认识论分离 — **H，保留但重写**

**原条目的问题**

- “患者可能存在的真实状态”不能被误写成系统已经拥有的真值；系统最多保存关于它的假说、集合或估计。
- “观察”内部也要区分测量结果、观察行为、患者自述内容、转述者和断言者。
- 物理上同一行为可具有多个角色：抽血既是测量过程，也是对患者发生的程序。硬要求不是所有对象必须互斥，而是各语义角色不可融合后丢失。

**最小反例**

CT 写“不能排除肺栓塞”；问题清单加入 provisional PE；模型输出 PE 概率 0.18；患者尚未接受抗凝。若四者都变成 `PE=present`，系统会把假说、评估和行为前提当事实。

**可检验不变量**

```text
INV-R1.1  artifact 的 epistemic/operational role 必须可查询：
           observed | reported | deterministic-derived | inferred |
           hypothesized | requested/planned | authorized | performed。
INV-R1.2  复制、显示或序列化不得改变 role；提升为另一 role 必须有显式转换活动与来源。
INV-R1.3  latent/state estimate 不得被标成直接测量；诊断假说不得成为自己的直接或间接根证据。
```

**为什么必要**：否则只是换一种字段名制造“推断自证”和“计划即现实”。FHIR R5 也将 [Observation](https://hl7.org/fhir/R5/observation.html)、[Condition](https://hl7.org/fhir/R5/condition.html)、[ClinicalImpression](https://hl7.org/fhir/R5/clinicalimpression.html) 分开；Observation 规范明确说它用于测量/时点判断，不应用于记录临床诊断。FHIR 是佐证这种区别已在交换标准中独立出现，不是本研究必须采用 FHIR 的理由。

### R2 时间因果性 — **H，需增加多时钟、区间和版本语义**

**原条目的问题**

- 六个时间名有重叠但没有严格定义；真正的“不得偷看未来”以**信息可用时间**为准，不以事件发生时间为准。
- 时间可能是区间、模糊范围或部分顺序，而不总是精确时点。
- 更正结果会产生第二条时间轴：某事实何时被认为适用于患者，与数据库何时持有该版本不同。

**最小反例**

08:05 采血，11:00 培养初报，次日 09:00 最终鉴定；回放 10:00 决策时不能因 specimen time 是 08:05 就使用次日结果。

**可检验不变量**

```text
INV-R2.1  eligible(e, knowledge_cutoff) => e.available_at <= knowledge_cutoff。
INV-R2.2  所有支持边 parent -> child 满足 parent.available_at <= child.generated_at。
INV-R2.3  至少能分别表示：临床有效/发生区间、采集/执行时间、结果可用时间、记录/事务时间；未知精度必须保留。
INV-R2.4  同时提供 historical-as-known 与 retrospective-reinterpret 两种查询，且输出不可混标。
```

**为什么必要**：单时钟会造成标签泄漏和错误因果顺序。[FHIR Observation](https://hl7.org/fhir/R5/observation-definitions.html) 区分 `effective[x]` 与 `issued`；[Provenance](https://hl7.org/fhir/R5/provenance-definitions.html) 区分 `occurred[x]` 与 `recorded`。Snodgrass 与 Ahn 的[时间数据库分类](https://doi.org/10.1145/318898.318921)区分 valid time 与 transaction time，但双时态仍不足以替代临床采集、发布和实施时间。

### R3 上下文语义 — **H，但“每项必须填满全部上下文”过强**

**最小反例**

`SpO2=92%` 在室内空气与 `FiO2=0.80` 下意义不同；`creatinine=1.2` 在 mg/dL 与 mmol/L 下不是同一个量；“血压 105/65”在错误袖带尺寸下可靠度不同。

**修订**

核心必须允许每种观察声明其语义必需上下文，并将缺失上下文本身显式化；不能要求所有观察机械填同一字段清单。某些上下文缺失时可输出不确定判断，而不是必然拒绝整条记录。

```text
INV-R3.1  值的身份至少绑定 subject/focus、概念、时间、值类型/单位；概念合同可声明 method/specimen/device/support/baseline/applicability 等必要条件。
INV-R3.2  比较或归一化前必须验证必需上下文；缺失时返回 unknown/uncertain/unsupported，而非采用无标记默认值。
INV-R3.3  归一化不能删除原值、原单位、原方法和来源。
```

**为什么必要**：上下文丢失会把不同临床世界碰撞。[FHIR Observation definitions](https://hl7.org/fhir/R5/observation-definitions.html)说明 method 会影响可比性，提供 specimen/device/referenceRange/appliesTo/age；[UCUM 2.2](https://ucum.org/ucum)的目标正是数量与单位的无歧义机器通信。

### R4 观察与状态分离 — **H，与 R1 相关但应单独压测**

**最小反例**

两个患者当前 MAP 都是 70；一个无支持，另一个依赖 norepinephrine 0.5 µg/kg/min。若 `MAP=70` 自动令“循环状态正常”，后者被错误归为稳定。

```text
INV-R4.1  observation(value) 不得直接断言内部状态正常/异常；映射必须经过显式、版本化的观察/状态模型。
INV-R4.2  支持治疗既可改变状态，也可改变状态如何显现；两条作用不得合并成一个无来源修正值。
INV-R4.3  planned intervention 不改变状态；只有具有实际实施状态、时间和剂量的事件可进入干预更新。
```

**为什么必要**：否则正常读数会抹掉维持它所需的治疗。Åström 的[不完全状态信息控制论文](https://doi.org/10.1016/0022-247X%2865%2990154-X)证明“隐状态与可观测信号分开”有成熟形式传统，但不要求本研究选择 POMDP。

### R5 证据守恒与血缘 — **H，改名为“血缘与依赖不可伪造”**

**原条目的问题**

证据会复制、聚合、修正，并没有一个简单数值“守恒量”。需要守恒的是来源身份、转换链和依赖结构。provenance 也不自动证明两个来源统计独立。

**最小反例**

一次 39.2°C 测量生成 `temperature_high`、`fever`、`high_fever`，又被两篇进展记录 copy-forward。它仍只有一个测量根，而不是五票。

```text
INV-R5.1  root(derived) = union(root(direct_inputs))；格式转换和复制不得创建新的 primitive root token。
INV-R5.2  聚合必须使用显式 dependence/independence 模型；different record id 不等于独立证据。
INV-R5.3  任一结论可递归追到患者证据、一般医学知识、规则/模型、参数与版本。
INV-R5.4  根证据撤回后，所有依赖后代必须 stale/invalidated/recomputed，不能继续作为活跃证据。
```

**为什么必要**：否则系统会用同一句话自我放大。W3C [PROV-DM](https://www.w3.org/TR/prov-dm/)定义 Entity/Activity/Agent、generation/usage/derivation；[PROV-CONSTRAINTS](https://www.w3.org/TR/prov-constraints/)规定 generation 先于 usage 等顺序。Buneman 等区分 [why/where provenance](https://doi.org/10.1007/3-540-44503-X_20)，Green 等的[provenance semiring](https://doi.org/10.1145/1265530.1265535)可显露多条推导路径。它们均不自动给出临床证据独立性，故 dependence 仍是本研究的额外硬要求。

### R6 不确定性为一等对象 — **H，但不能压成一个长枚举**

**原条目的问题**

清单混合了至少五个正交维度：断言极性、采集状态、适用性、定量不确定性、冲突/模型覆盖。一个字段若只能选一个值，会丢失例如“检查已做但样本不合格，且目前模型不支持该方法”。

**最小反例**

“病历未提到胸痛”“患者明确否认胸痛”“患者插管无法评价”“问过但拒答”“问题被权限遮蔽”均不能编码成 `chest_pain=false`，彼此也不能合成同一个 unknown。

```text
INV-R6.1  absent field != explicit negative。
INV-R6.2  至少可正交表达 assertion polarity、acquisition/missingness reason、applicability、quantitative uncertainty、conflict 和 model-support status。
INV-R6.3  true/false/both/neither 或概率只处理其声明的维度，不得冒充完整不确定性语义。
INV-R6.4  冲突原断言均保留；解决冲突本身是有来源的派生行为。
```

**为什么必要**：不同缺失机制携带不同信息且需要不同下游动作。FHIR [DataAbsentReason](https://fhir.hl7.org/fhir/valueset-data-absent-reason.html)明确区分 unknown、not-asked、masked、not-applicable、unsupported、error、not-performed 等；Rubin 的[缺失数据论文](https://doi.org/10.1093/biomet/63.3.581)说明只有在特定缺失机制条件下才能忽略缺失过程。

### R7 局部可组合性 — **M：保守扩展为 H，最小 blast radius 为 S**

**原条目的问题**

新增一个药物可能真实地影响多个疾病、相互作用和检测方法，强制“只能改局部一处”反而会遗漏知识。硬要求不应是文件数为 1，而是影响范围显式、旧语义不被静默改变。

**最小反例**

新增 biotin：它既是暴露/补充剂，也可能干扰多种免疫测定。只加一条药物记录而不声明受影响检查，并不叫组合性好。

```text
INV-R7.1  新内容在同一核心版本下是保守扩展：旧 artifact 的身份和旧推断快照不被无声重解释。
INV-R7.2  跨模块影响必须通过声明的依赖/适用关系进入，并触发受影响测试；不得靠核心中的 disease-specific if。
INV-R7.3  需要改核心时必须提升核心版本、提供迁移/兼容说明并保留旧回放能力。
```

**为什么必要**：局部性是可维护性的手段，不是医学事实互不相干的假设。`extension blast radius`、修改文件数、重新编译范围属于 Pareto 指标，不是绝对正确性。

### R8 非线性交互 — **H（不强制线性），但“自动表达任意非线性”是 A**

**最小反例**

CKD 改变肌酐基线和药物清除；sepsis 又可触发 AKI；肾毒性药物的效应依赖两者与剂量。三者不能由三个互不知情的固定加分简单相加。

```text
INV-R8.1  组合算子不得预设所有共病/药物/机制效应相加或独立。
INV-R8.2  能声明带上下文和适用域的高阶交互；该交互仍需来源、版本和不确定性。
INV-R8.3  未建模交互应暴露 limitation/unknown，而不是默认交互为 0。
```

**为什么必要**：错误的零交互假设是静默错误。另一方面，任何有限知识库都不可能自动知道所有非线性；要求的是可表达和可见失败，不是全知。

### R9 多任务投影 — **H；“存在唯一底层完整状态”不是前提**

**最小反例**

creatinine 2.0 mg/dL 在诊断视图用于区分 AKI/CKD，在给药安全视图需与年龄、体重和药物联动，在科研视图还要保留测量方法和纳入时点。一个固定“相似度”不能同时充当三者目标。

```text
INV-R9.1  project(evidence_history, task_spec, model_spec, as_known_at) 的输出绑定任务、目标、时间窗和版本。
INV-R9.2  投影只产生派生视图，不回写或覆盖原始证据。
INV-R9.3  两个任务可合法保留不同坐标/距离/不确定性；任何共享量的语义仍可追溯。
```

**为什么必要**：任务决定充分统计量和损失。硬要求是共享证据与明确投影，不是预设一个全知 latent vector。

### R10 开放世界 — **H；开放世界不等于已经有可靠 OOD 检测**

**最小反例**

atlas 只有 sepsis 与 pneumonia，真实病例是肺栓塞。系统不能因 sepsis 得分略高就输出“已知 sepsis”，也不能因所有疾病都差就自动称患者健康。

```text
INV-R10.1  已知候选集合允许为空、并列或仅部分解释；不得强制总分类。
INV-R10.2  未召回/未记录/词表未知不得蕴含不存在或阴性。
INV-R10.3  OOD/unsupported/insufficient-evidence 必须是可输出状态，并保留未映射原文。
```

**为什么必要**：[OWL 2 Primer](https://www.w3.org/TR/owl2-primer/)明确说明开放世界下事实缺失可能只是未写。该语义只证明“没有记录不等于假”，不能替代统计 OOD 验证、阈值校准或缺失原因。

### R11 可重放与可审计 — **H；需定义两种回放并绑定计算环境**

**最小反例**

10:00 K=7.2 触发处置；12:00 实验室更正为“溶血、结果无效”。历史审计应能解释 10:05 为什么报警；当前复盘则不应继续把 7.2 当有效证据。

```text
INV-R11.1  historical_replay(t) 只使用 t 时已可用的数据版本、知识/规则/模型/术语版本和外部响应快照。
INV-R11.2  retrospective_reinterpret(t, current_snapshot) 可用当前知识重释旧证据，但必须明确标成另一模式。
INV-R11.3  同事件、同顺序、同快照、同随机源/捕获输出应产生语义等价结果；不要求跨平台 bitwise 相等。
INV-R11.4  缺失所需版本或外部响应时必须显式失败，不得拿 current/latest 近似历史。
```

**为什么必要**：FHIR [HTTP history/version](https://hl7.org/fhir/R5/http.html)支持 `versionId`、`vread`、history，但规范也允许服务器不支持版本；所以“兼容 FHIR”不等于严格回放。21 CFR 11.10(e) 的[官方条文](https://www.ecfr.gov/current/title-21/part-11/section-11.10)要求带时间戳审计轨迹且更改不遮蔽先前信息，说明审计与可变最新快照不能混为一谈。

### R12 安全不变量 — **H，且必须由执行路径强制**

原列七条全部保留，并补充：

```text
INV-R12.1  unknown/absent/masked/retrieval-miss 均不得自动转成 false。
INV-R12.2  派生结论的 provenance 依赖关系/证明对象不得形成让结论支持自身的环；不要求用图实现。
INV-R12.3  任何输入的 available_at 晚于 cutoff 时，过去判断必须拒绝消费。
INV-R12.4  同一根证据的多个改写不得获得多份独立权重。
INV-R12.5  requested/planned/not-done 不得产生 performed intervention 的生理效应。
INV-R12.6  指定为 mandatory 的罕见安全规则必须被确定性枚举执行；不能以检索是否召回代替。
INV-R12.7  输入身份、单位、必要上下文或模型适用性不足时允许并要求 abstain/error。
INV-R12.8  被纠正/撤回的根证据不得继续支撑当前结论。
INV-R12.9  重复摄取同一 source event 必须幂等，不得复制证据票数。
```

**为什么必要**：这些不是“模型表现不好”，而是语义违规。安全规则仅写进 prompt、文档或可选检索不算 E（可强制）。

### R13 核心稳定性 — **M，与 R7 合并评估**

**修订**

- H：医学内容与执行原语有版本化边界；新增普通疾病/药物/检查不需新增核心 opcode；核心变化必须迁移且旧结果可回放。
- S：多久改一次核心、改多少文件、重跑多少测试、扩展耗时。
- A：为了“永不改核心”把所有含义塞入无类型字符串或 Turing-complete 回调；这只是把核心复杂度藏起来。

**最小反例**：新增一种 troponin assay 竟需在执行器加入 `if assay_name == ...`，说明医学内容泄漏进核心；相反，如果新发现确实需要此前不存在的时间语义，提升核心版本可能是正确修订，不应被绝对稳定性禁止。

```text
INV-R13.1  普通内容扩展不得修改核心语义分支。
INV-R13.2  任意核心语义变化都有显式 version、migration、compatibility 和 replay 策略。
```

### R14 人工可理解与 LLM 可填写 — **M：可审计为 H，LLM 易填为 S**

**最小反例**

病历没提发热，LLM 补成 `fever=false`；若系统只保留 embedding 或最终 JSON，审核者无法知道它是从哪里推出来的。

```text
INV-R14.1  每个关键事实、转换和结论有机器可检验且人可查看的类型、来源、时间、版本与依赖摘要。
INV-R14.2  LLM 输出默认是 untrusted proposed artifact；通过 schema 只证明语法，不证明医学语义。
INV-R14.3  无 source span/结构化来源或明确人工输入的 LLM 提取不得伪装成原始观察。
INV-R14.4  opaque vector 可以用于检索/近似，但不能是关键事实身份、否定、行动状态或审计依据的唯一载体。
```

**为什么必要**：高维表示并非禁用；禁的是不可逆地丢掉审计所需语义。要求所有复杂数学由人手算同样过强，真正的硬要求是可检查合同和完整 trace。

### R15 最小性 — **S；“原语数最少者必胜”是 A**

**最小反例**

一个候选宣称只有一种原语 `Node(key, payload)`，但所有 Observation/Plan/Inference/Action 区分都藏在自由文本和解释器分支中。其 class count 是 1，语义复杂度并未减少，非法状态反而更容易出现。

```text
METRIC-R15.1  primitive count 同时统计核心类型、强制关系/操作、必需 metamodel 与特殊解释器分支。
METRIC-R15.2  若删除某原语仍能自然通过全部硬测试且不增加隐藏特例，它才可能冗余。
METRIC-R15.3  比较 description length / special-case count / illegal-state surface，而非只数 class 名。
```

**为什么必要**：最小性是 Pareto 维度，不存在与表示方式无关的唯一原语计数。它不能凌驾于安全不变量。

---

## 4. 原 15 项遗漏的硬要求

下面不是“越多越保险”的功能清单。每一项都有原 15 项无法覆盖的最小反例和独立不变量。

### N1 实体、患者、就诊、标本和部位的身份与作用域 — **H，优先级 P0**

**最小反例**：同名双胞胎的 CBC 标本被交换；或者左腿超声被误挂到右腿。即使后续概率模型完全正确，错误 subject/scope 会让全部推理针对错误对象。

```text
INV-N1.1  所有患者特异 artifact 都有稳定 subject/focus；需要时还有 encounter/specimen/body-site/device identity。
INV-N1.2  无显式合法关系时，不得跨 subject 或 specimen join。
INV-N1.3  patient merge/split/rekey 和 specimen relink 是有来源、可撤回、可重放的版本事件，不能原地改写历史。
```

**为什么是新要求**：上下文语义 R3 未明确身份完整性和跨对象 join 的禁止规则。FHIR Observation 的 `subject/focus/specimen/bodySite` 是可借鉴实例，但标识主索引本身仍需实现和验证。

### N2 量纲、尺度、检测限和术语身份/版本 — **H，P0**

**最小反例**：glucose `90 mg/dL` 与 `90 mmol/L`；D-dimer FEU 与 DDU；troponin I 与 troponin T。字符串相近不代表同一量，数字相同也不代表可比较。

```text
INV-N2.1  数值比较、转换和阈值判断前必须验证 concept、datatype/scale、dimension、unit、method/assay 与必要 reference frame。
INV-N2.2  非同量纲或映射歧义时 fail typed；不得取“最近单位/最近概念”。
INV-N2.3  术语身份绑定 system + version + code；映射声明方向、上下文和等价强度。
INV-N2.4  换算、截断、低于检测限和归一化均保留原始表示与变换 provenance。
```

**依据**：[UCUM](https://ucum.org/ucum)定义可机器验证的单位语义；FHIR [ConceptMap](https://hl7.org/fhir/R5/conceptmap.html)把映射方向、上下文和 unmapped 作为显式概念。两者不能证明医学概念映射正确，故仍需版本与人工/规则审查。

### N3 纠正、撤回、替代、过期与依赖真值维护 — **H，P0**

**最小反例**：实验室把 K=7.2 修订为“样本溶血，结果无效”。简单删除会毁掉历史解释；继续保留为 active 又会持续触发错误警报。

```text
INV-N3.1  correction/retraction/replacement 产生新版本或事件，不遮蔽旧历史。
INV-N3.2  当前视图中，被撤回根的依赖闭包自动失效或重算；历史 as-known 视图仍能看到当时版本和当时输出。
INV-N3.3  stale/expired 不是 delete：它可用于病程历史，但不得无标记代表当前状态。
```

**依据**：W3C PROV 有 revision/invalidation；FHIR Provenance 支持产生、修订、删除上下文；21 CFR 11.10(e) 要求修改不能遮蔽先前记录。上述规范不提供完整 truth-maintenance 执行器，因此级联失效必须单独测试。

### N4 观察机会、采样选择与缺失过程 — **H**

**最小反例**：未测 lactate 不等于 lactate 正常；重症患者因医生担心恶化而更频繁测 lactate，“是否测量/测量频率”本身携带流程信息。治疗还会改变后来是否再检查。

```text
INV-N4.1  observed value、test/order/collection process、not-observed reason 与 observation opportunity 可分开表示。
INV-N4.2  缺失默认不按 MCAR 处理；若模型忽略 observation process，必须声明假设和适用域。
INV-N4.3  明确阴性必须带 ascertainment scope（问了谁、何时、用何方法）；无观察机会不能生成 negative。
```

**依据**：Rubin 1976 给出何时可以忽略缺失机制的条件；Agniel、Kohane、Weber 的 [BMJ 2018 EHR 研究](https://doi.org/10.1136/bmj.k1479)显示医疗流程导致的记录存在/频率本身具有预测性。因此“missingness reason”不只是 UI 标签。

### N5 血缘不等于独立性；依赖关系必须显式或保守 — **H，P0**

**最小反例**：发热、CRP 和 WBC 来自不同记录但共享炎症机制；相反，同一实验室在不同时点的两次独立采样可能带来新信息。按 source 字符串去重和按 record 数相乘都可能错。

```text
INV-N5.1  聚合器声明其 dependence/conditional-independence 假设或给出保守界限。
INV-N5.2  clone/summary/copy-forward 不增独立证据质量；新的独立测量可以改变证据质量。
INV-N5.3  dependence unknown 不得静默当 independence；可输出范围、敏感性分析或 abstain。
```

**为什么是独立要求**：R5 保血缘只解决“从哪里来”，不能解决“统计上是否独立”。W3C PROV 也明确是 provenance 模型，不是概率依赖模型。

### N6 观察、干预、关联、因果效应与反事实的类型边界 — **H(scope)**

**最小反例**：抗菌药后发热下降，可能是药物作用、自然病程、并行补液或回归均值。`P(improved | antibiotic)` 不能无条件变成 `P(improved | do(antibiotic))`，更不能成为该患者“若未治疗会怎样”的事实。

```text
INV-N6.1  observe(X=x) 与 intervene/do(X=x) 是不同操作；planned intervention 又是第三种状态。
INV-N6.2  因果/反事实输出声明 estimand、目标人群、时间窗、假设、识别策略和未识别部分。
INV-N6.3  无识别依据时只能输出 association、bounds、多模型结果或 abstain，不得自动升级为 causal effect。
```

**依据**：Pearl 的 [A Causal Calculus for Statistical Research](https://proceedings.mlr.press/r0/pearl95a.html)明确区分普通条件化与外部干预条件化，并指出假设不足时因果量可能无法由观察数据识别。这约束接口语义，但不要求候选采用因果图作为唯一内核。

### N7 患者目标、偏好、效用、约束和授权与事实推断分离 — **H(scope)**

**最小反例**：两个生理状态相同的患者，一个接受输血，一个基于信仰明确拒绝；或者同一 AF 风险下，一人有活动性消化道出血。疾病后验相同不推出相同合法动作。

```text
INV-N7.1  诊断/预测输出本身不能满足 action/recommendation 类型。
INV-N7.2  治疗建议声明目标/效用、horizon、备选行动、禁忌、资源/可行性、患者偏好和授权状态。
INV-N7.3  关键目标或偏好未知时输出条件化方案或 defer；不得声称唯一最优。
INV-N7.4  recommendation/order/authorization/administration 不可静默互换。
```

**依据**：FHIR [Workflow](https://hl7.org/fhir/R5/workflow.html)将 definition、request、event 分开，并明确 request 不保证会被执行；决策分析也将概率模型与偏好/效用模型分开，例如 [Bielza 等 2010](https://doi.org/10.1016/j.dss.2010.04.003)。这只是“事实不足以决定行动”的证据，不预选 influence diagram。

### N8 知识、模型、规则、术语、配置、外部响应与适用范围版本 — **H，P0**

**最小反例**：医院更换 troponin assay 和 cutoff；指南又更新诊断标准。今天用 latest 解释去年的值会改变结果，却无法说明当时为何作出不同判断。

```text
INV-N8.1  每次计算绑定 knowledge/model/rule/terminology/config/code-build artifact、随机性记录及外部服务响应快照的稳定版本或内容 hash。
INV-N8.2  输出声明 intended use：目标人群、场景、预测时点、horizon、输入要求和验证范围。
INV-N8.3  超出 applicability 时输出 out-of-scope/conditional，不得作为普通已验证结论。
INV-N8.4  新知识生成新 interpretation version；不得改写旧决策记录。
```

**依据**：[PROBAST+AI 2025](https://doi.org/10.1136/bmj-2024-082505)把开发质量、性能评价风险和对目标用途的 applicability 分开；FHIR 版本机制只能帮助存储，不能证明模型在该人群有效。

### N9 规范化可逆、释义不变性和原始证据保留 — **H**

**最小反例**：“患者否认发热”换成等义表达后，一个解析成 `fever=false`，另一个解析成 `fever=unknown`；或“不排除”被 NLP 变为 confirmed positive。

```text
INV-N9.1  输入适配层输出有 source span/结构化来源、mapping version、候选集合和置信/歧义状态。
INV-N9.2  同一规范化主张的无医学意义释义变化不应改变核心状态；真正歧义必须保留多候选或 unknown。
INV-N9.3  原文/原结构与映射链保留；规范化不是有损覆盖。
```

**为什么是新要求**：R14 规定可审计，但没有明确 normalization 边界和 paraphrase invariance。这直接对应用户压力测试 30。

### N10 矛盾容忍和非爆炸推理 — **H**

**最小反例**：护士记录“皮疹存在”，皮肤科同一时段记录“未见皮疹”。last-write-wins 会丢证据；经典爆炸逻辑又可能从矛盾推出任意结论。

```text
INV-N10.1  p 与 not-p 的来源化断言均保留，系统生成 first-class conflict。
INV-N10.2  conflict(p) 不得蕴含无关 q；候选需给出其冲突传播语义。
INV-N10.3  冲突裁决/融合是派生结论，绑定规则、证据、时间和版本，且可撤回。
```

**依据**：Belnap 的 [A Useful Four-Valued Logic](https://doi.org/10.1007/978-94-010-1161-7_2)是面向不一致信息的原始形式方案之一。它证明非爆炸有成熟实现可能性，但四值逻辑并不能表达本项目全部缺失、概率和时间语义。

### N11 类型化失败、无损摄取和 fail-closed — **H，P0**

**最小反例**：输入 `norepinephrine 0.5 mg/kg/min`，系统发现剂量单位超出支持范围，却静默改成 µg/kg/min；或者遇到未建模 finding 后直接丢字段继续给药建议。

```text
INV-N11.1  malformed、dimension mismatch、unsupported concept/state、non-convergence、timeout、missing mandatory rule 均有类型化失败。
INV-N11.2  失败不能被普通正常值、空集合或低置信分数代替。
INV-N11.3  关键输入不可表达时保留原始 payload，阻止超出安全降级合同的结论/动作。
INV-N11.4  验证失败的输入进入 quarantine；只有显式修正/映射活动生成的新版本才能晋升为 active evidence，原失败记录保留。
```

**为什么必要**：开放世界只说未知可存在，未要求引擎在内部无法表达时停止。用户测试 29 必须由此条直接判定。

### N12 幂等摄取、并发与动作生命周期 — **H(scope)，P0**

**最小反例**：接口重试把同一化验消息摄取两次，诊断权重翻倍；更严重的是给药请求重试导致两次胰岛素实施。

```text
INV-N12.1  同一 source event/idempotency key 重放至多产生一个证据根或一个执行效果。
INV-N12.2  并发 correction/cancel/perform 有可定义的因果/事务顺序；不能仅以客户端最后到达覆盖。
INV-N12.3  partial dose、failed、not-done、cancelled 与 completed 保持不同；取消不能抹掉先前已实施部分。
```

**依据**：FHIR MedicationRequest/MedicationAdministration 和 Workflow 展示了请求与执行生命周期；具体幂等/并发保证仍是候选执行语义必须证明的部分。

### N13 决策反馈、治疗污染与在线学习边界 — **H(scope)**

**最小反例**：sepsis 警报触发早期抗菌药，随后培养转阴；若系统把“阴性培养”无标记用于在线重训，可能学出“被警报的患者不是感染”，形成政策反馈。

```text
INV-N13.1  系统输出、医生看到输出、后续行动和观察选择作为 policy exposure 保留。
INV-N13.2  后决策数据不得无调整地冒充未干预世界或未受模型影响的标签。
INV-N13.3  在线更新有新版本、离线/前瞻验证、监测、回滚和再现路径；不得直接自我强化当前结论。
```

**为什么必要**：原 15 项讨论治疗改变患者与表现，却未覆盖系统自身进入闭环后如何污染标签和测量过程。

### N14 临床有效性、校准、可迁移性和生命周期监测 — **部署硬边界 D-H，不是核心表达原语**

**最小反例**：一个成人单中心模型表达与 provenance 都完美，却未经验证用于新生儿；或 AUC 尚可但绝对风险严重失准。

```text
INV-N14.1  未达到声明 intended use 的验证标准时，组件不能被标成 decision-qualified。
INV-N14.2  输出绑定验证数据/版本、校准与亚组/场景适用信息；漂移可撤销部署资格。
INV-N14.3  表示测试通过不得被报告为临床净获益、安全或因果有效性证明。
```

**依据**：[IMDRF SaMD Clinical Evaluation N41](https://www.imdrf.org/documents/software-medical-device-samd-clinical-evaluation)区分 valid clinical association、analytical/technical validation 和 clinical validation；PROBAST+AI 区分开发质量、性能风险与适用性。它们是部署边界，不决定最小语义内核。

### N15 权限、同意、用途限制与“被遮蔽不等于不存在” — **部署 H，核心至少要保留状态**

**最小反例**：精神科记录因访问政策被 mask；授权视图中没有显示自杀风险史。若系统把视图缺失解释为“无风险史”，会生成危险的假阴性。

```text
INV-N15.1  masked/restricted/not-permitted 与 absent/negative 分开；检索结果需声明 completeness/visibility context。
INV-N15.2  推断与回放绑定当时 consent/policy/authorization version；每次访问和动作可审计。
INV-N15.3  权限不足时不得声称对全记录作出完整性结论。
```

**依据**：FHIR DataAbsentReason 有 `masked`；[FHIR AuditEvent](https://hl7.org/fhir/R5/auditevent.html)区分操作审计与资源如何产生的 Provenance；21 CFR 11.10 要求访问、权限和审计控制。安全部署还需要认证、可用性和运维控制，不能声称由语义数据模型单独解决。

### N16 一般医学知识、患者特异证据、任务政策和模型输出的作用域分离 — **H**

**最小反例**：RCT/指南说某药在某人群降低死亡率，并不表示这名患者已服药，也不表示该药对其必然有效；模型的疾病先验也不是患者观察。

```text
INV-N16.1  population/general-knowledge artifact 不得作为 patient event；只能经显式适用/推断活动影响患者结论。
INV-N16.2  patient observation 不得无聚合/同意与方法直接升级为人群规律。
INV-N16.3  policy/goal/utility、causal model 和 patient evidence 在 trace 中分别可见。
```

**为什么必要**：用户对 A（核心）与 B（医学内容）的划分还缺少运行时作用域规则；没有它，规则、先验和患者事实会互相伪装。

### N17 概率/置信、信息状态、断言状态与模型覆盖正交 — **H**

**最小反例**：`P(PE)=0.7` 可能来自完整但噪声较大的数据，也可能来自两条互相冲突的记录；“模型给 0.7”也不表示 PE 这个断言已 confirmed，更不表示模型在该人群内适用。

```text
INV-N17.1  probability/score 不得覆盖 assertion status、missingness、conflict、source quality、applicability 或 OOD status。
INV-N17.2  概率必须声明其事件/变量、条件信息集、模型版本、目标时间和 calibration domain；无法解释的 score 不得伪装成 probability。
INV-N17.3  deterministic computation 只表示给定输入后的运行确定性；它不抹除输入与模型不确定性。
```

**为什么必要**：R6 说“不确定性一等”，但如果实现只有一个 confidence 数字，仍会把多个正交问题碰撞。PROBAST+AI 对预测定义、测量、性能和适用性分别评估，也说明一个模型分数不能替代这些状态。

### N18 组合知识的存在、缺失、冲突与近似假设正交 — **H(scope)**

**最小反例**：知识库没有记录药 A 与病 B 的交互。可能是尚未建模、检索没找到、证据冲突、真正研究过且无重要交互，或系统只采用了加性近似；五者不能都变成 `interaction=0`。

```text
INV-N18.1  absent-interaction、not-retrieved、unsupported-composition、conflicting-evidence、assumed-independent/additive、evidence-of-no-material-interaction 可区分。
INV-N18.2  使用加性/独立/交换/结合近似时，输出 trace 必须列出假设、适用域和敏感性/误差状态。
INV-N18.3  组合超出声明闭包时返回 unresolved/unsupported；不得静默丢掉一个组件。
```

**为什么必要**：R8 只要求能表达非线性，未把“没有知识”与“知识为零”正式分开。这是开放世界在组合层面的对应物。

### N19 数值诊断、近似误差与计算失败不可隐形 — **H(scope)**

**最小反例**：概率归一化下溢后全为 0，代码用 uniform fallback 继续输出；协方差矩阵非半正定被偷偷 clip；粒子退化或优化器未收敛仍显示精确排名。

```text
INV-N19.1  每个数值算法声明必要诊断：收敛/残差、有效样本量或近似误差、overflow/underflow、constraint violation、随机性和 fallback。
INV-N19.2  未满足算法前置条件或诊断阈值时产生 typed numerical_failure/degraded，不能输出无标记正常结论。
INV-N19.3  fallback 是版本化、可审计的显式策略；不得改变问题定义后仍沿用原置信语义。
```

**为什么必要**：架构语义正确仍可能被数值近似破坏。原 15 项仅说“不确定性”和“无法表达”，没有覆盖“形式上可表达但计算过程失效”。候选若完全符号化、不做数值近似，可把此条标为不适用；若声称概率/优化/模拟能力则为硬约束。

### N20 并发事件需因果/部分顺序，不能强造唯一总序 — **H(scope)**

**最小反例**：两个医院几乎同时录入冲突药物史，网络延迟使后发生的消息先到；用 arrival timestamp 的 last-write-wins 会把传输顺序误当临床因果顺序。

```text
INV-N20.1  明确因果相关的事件有 happens-before/precedence；不可比较事件可保持 concurrent，而不是任意制造临床顺序。
INV-N20.2  arrival/recorded time 只表示系统事实，不能自动替代 occurrence/effective order。
INV-N20.3  并发冲突经显式 reconciliation 生成新版本；reconciliation 本身有 provenance。
```

**为什么必要**：R2 的多时钟仍可能误以为每个事件都有可靠总序。W3C PROV-CONSTRAINTS 提供 generation/use 等必要顺序，但不要求所有无关活动总排序。

---

## 5. 收敛后的要求分层

### 5.1 候选一旦失败就应淘汰的 H/P0

1. epistemic/operational role 不可静默替换；
2. subject/specimen/scope 身份完整；
3. 知识可用时间截断与多时钟；
4. 单位、类型、术语和必要上下文验证；
5. observation 与 state estimate 分开；plan/request 与 performed intervention 分开；
6. lineage、root identity、dependency、修订/撤回闭包；
7. typed missingness/conflict/OOD/unsupported；
8. 矛盾不爆炸；
9. 任务投影纯函数式地产生派生视图，不覆盖证据；
10. open-world abstention；
11. as-known 回放与 current-knowledge 重释分开；
12. 普通医学扩展不需 disease-specific core branch；核心变化版本化；
13. 类型化失败、无损原文/原值和 fail-closed；
14. 幂等摄取与关键安全规则全覆盖执行；
15. 关键结论有完整、可递归审计 trace。

### 5.2 只在候选声称相应能力时成为 H(scope)

- 若声称因果/反事实：必须声明 estimand、假设与识别状态；
- 若声称治疗推荐：必须纳入目标/效用/偏好/约束/授权；
- 若声称执行行为：必须提供幂等、并发、取消和部分实施语义；
- 若声称在线学习：必须标记政策暴露、版本化、验证、监测和回滚；
- 若声称精确回放：必须固定全部数据/知识/模型/术语/配置、随机性或输出快照。

### 5.3 部署硬边界 D-H（不能用原型通过来冒充）

- 临床关联、分析验证、目标场景临床验证；
- 校准、可迁移性、亚组公平性、漂移与撤销资格；
- 隐私、同意、访问、完整性、审计、可用性、灾备；
- 人员责任、审批、监管 intended use。

### 5.4 Pareto 软指标 S

- core primitive count（含隐藏 metamodel/解释器分支）；
- special-case count；
- extension blast radius；
- trace audit burden；
- LLM/人工 authoring burden 与验证反馈质量；
- 增量计算、存储与全量重放成本；
- 语义等价实现的代码/规范长度；
- 跨实现互操作和迁移成本；
- bitwise reproducibility（语义重放是 H，逐位一致通常是 S）。

---

## 6. 明确反目标 A

1. **唯一真状态反目标**：预设一个有限 latent state 对所有未来任务充分。
2. **强制闭集反目标**：所有患者必须映射到一个已知疾病，且已知候选概率被迫归一为 1。
3. **万能容器反目标**：用 untyped node/string/JSON/callback 隐藏全部语义，再宣称原语最少。
4. **确定性即真反目标**：确定性函数输出被当作确定事实；它仍继承输入与模型局限。
5. **provenance 即独立/真实反目标**：有来源不代表来源可靠，来源不同不代表统计独立。
6. **开放世界即 OOD 反目标**：开放世界逻辑不提供校准的模型外检测。
7. **相关即因果反目标**：从 `P(Y|X)`、治疗后变化或时间先后直接生成干预效应。
8. **概率即行动反目标**：诊断/风险最大者自动成为唯一最佳治疗，不声明目标与约束。
9. **检索即安全反目标**：关键禁忌依赖 top-k、向量相似度或 LLM 是否想起。
10. **新模型覆盖旧历史反目标**：用 latest 重新计算后静默冒充当时系统输出。
11. **零交互默认反目标**：未声明交互被解释为医学上已证明独立/加性。
12. **LLM 修补核心反目标**：核心无法表示或验证的语义交给 prompt 临时补救。
13. **删原文反目标**：标准化后删除原值、原单位、原句或映射版本。
14. **表示通过即临床有效反目标**：语义测试、单元测试或模拟结果冒充临床验证。
15. **单总分反目标**：把所有硬失败和软权衡压成可被权重掩盖的总分。

---

## 7. 建议直接进入统一测试接口的 Checkpoint 1 不变量

候选不需要共享内部结构，但必须能接受同一个外部测试合同：

```text
epistemic_non_substitutability
request_vs_performed
knowledge_cutoff
valid_time_vs_available_time
historical_vs_retrospective_replay
context_non_collision
subject_and_specimen_integrity
unit_commensurability
raw_value_roundtrip
support_masking
typed_missingness
ascertainment_scope
open_world_abstention
conflict_non_explosion
lineage_clone_invariance
dependency_not_provenance
retraction_cascade
acyclic_grounded_derivation
task_projection_purity
interaction_activation
unmodeled_interaction_visible
conservative_extension
artifact_version_pin
observation_vs_intervention_typecheck
causal_identifiability_gate
goal_sensitive_action
idempotent_ingest_and_action
mandatory_safety_rule_coverage
masked_not_negative
explicit_failure
paraphrase_normalization
feedback_contamination_guard
```

每个测试 fixture 必须包含：

1. 正例；
2. 只改变一个语义因素的最小反例；
3. 期望状态或期望错误类型；
4. cutoff、版本和任务合同；
5. 预期 root evidence 与依赖闭包；
6. H / H(scope) / D-H / S 分类；
7. 候选为通过该测试新增的 special case 数。

### 7.1 统一接口不能只问“能否编码”

建议候选原型至少暴露下列语义操作（名称可不同）：

```text
ingest(source_artifact) -> accepted | typed_error
derive(task, as_known_at, model_snapshot) -> result + trace
correct_or_retract(source_id, new_version) -> affected_dependents
replay(as_known_at, snapshot_mode) -> state/result + trace
project(task_contract) -> task_view + trace
plan(action) -> request/plan artifact
record_performed(action_event) -> performed artifact
validate(candidate_artifact) -> conformance report
```

这里列的是外部行为，不是预定面向对象 API。事件演算、项重写或数据库候选均可用自己的形式提供等价 oracle。

---

## 8. 已核实的第一手来源及其证据边界

> 下表中的来源用于证明某种区分在规范/形式研究/真实临床数据中有独立依据。**它们不证明采用该来源对应的技术就是最优架构**。

| 来源 | 本笔记使用的精确支持点 | 不能据此声称什么 |
|---|---|---|
| [HL7 FHIR R5 Observation](https://hl7.org/fhir/R5/observation.html) / [definitions](https://hl7.org/fhir/R5/observation-definitions.html) | Observation 是测量/时点判断而非临床诊断；有 effective、issued、method、specimen、device、referenceRange、derivedFrom、dataAbsentReason | FHIR 不是患者隐状态、诊断算法或因果模型；字段存在不保证填对 |
| [FHIR R5 Condition](https://hl7.org/fhir/R5/condition.html) | verificationStatus 区分 unconfirmed/provisional/differential/confirmed/refuted/entered-in-error | Condition 资源不能保证诊断真值或完整鉴别 |
| [FHIR R5 Workflow](https://hl7.org/fhir/R5/workflow.html)、[MedicationRequest](https://hl7.org/fhir/R5/medicationrequest.html)、[MedicationAdministration](https://hl7.org/fhir/R5/medicationadministration.html) | definition/request/event，以及 order 与实际 administration 生命周期不同；request 不保证执行 | 不证明 FHIR workflow 足以驱动安全执行或幂等并发 |
| [FHIR R5 DataAbsentReason](https://fhir.hl7.org/fhir/valueset-data-absent-reason.html) | unknown、asked-unknown、not-asked、masked、not-applicable、unsupported、error、not-performed 非等价 | 单个枚举不能覆盖概率、冲突、OOD、选择机制等全部不确定性 |
| [FHIR R5 Provenance](https://hl7.org/fhir/R5/provenance.html)、[AuditEvent](https://hl7.org/fhir/R5/auditevent.html) | Provenance 说明资源如何产生/转换；AuditEvent 说明谁在何时做了什么，两者用途不同 | 有 provenance 不代表事实真实或来源独立；有 audit log 不代表可重现推断 |
| [FHIR R5 HTTP version/history](https://hl7.org/fhir/R5/http.html) | versionId、vread、history；完整版本有助临床记录完整性 | FHIR 允许 no-version，故兼容 FHIR 不等于严格回放；也不保存模型/外部响应 |
| [W3C PROV-DM](https://www.w3.org/TR/prov-dm/) | W3C Recommendation；Entity/Activity/Agent、generation、usage、derivation、revision、invalidation、provenance of provenance | 不是统计独立性、临床真实性或完整 truth-maintenance 规范 |
| [W3C PROV-CONSTRAINTS](https://www.w3.org/TR/prov-constraints/) | generation 先于 usage、usage 先于 invalidation 等可验证顺序 | 不提供所有临床时间语义，也不要求无关事件总排序 |
| Snodgrass & Ahn, [A Taxonomy of Time in Databases](https://doi.org/10.1145/318898.318921)（作者公开 [PDF](https://www2.cs.arizona.edu/~rts/pubs/SIGMOD85.pdf)） | valid time 与 transaction time 的经典分类 | 双时态不足以覆盖 specimen、issued、action、uncertain interval 等全部临床时间 |
| Buneman, Khanna, Tan, [Why and Where Provenance](https://doi.org/10.1007/3-540-44503-X_20)（[论文 PDF](https://www.pure.ed.ac.uk/ws/files/16509989/Why_and_Where_A_Characterization_of_Data_Provenance.pdf)） | why-provenance 与 where-provenance 区分 | 不自动解决负信息、概率依赖和撤回级联 |
| Green, Karvounarakis, Tannen, [Provenance Semirings](https://doi.org/10.1145/1265530.1265535)（[作者 PDF](https://www.cs.ucdavis.edu/~green/papers/pods07.pdf)） | 可把来源 token 与多条查询推导路径保留下来，暴露重复使用 | 不能直接把多项式次数当临床独立证据票数 |
| [OWL 2 Primer](https://www.w3.org/TR/owl2-primer/) | W3C 明确对比 closed-world 与 open-world：未出现的事实可能只是缺失而非假 | 开放世界不等于缺失机制、冲突容忍、概率不确定性或 OOD 检测 |
| Rubin, [Inference and Missing Data](https://doi.org/10.1093/biomet/63.3.581)（[Harvard record](https://dash.harvard.edu/entities/publication/73120378-8764-6bd4-e053-0100007fdf3b)） | 只有在特定 missingness 条件和参数可分离条件下，忽略缺失过程才有一般正当性 | 不提供临床数据 schema，也不能把 MAR 当所有 EHR 缺失的已证事实 |
| Agniel, Kohane, Weber, [BMJ 2018](https://doi.org/10.1136/bmj.k1479) | 真实 EHR 中医疗流程造成的记录有无/频率携带系统性信息 | 观察过程有信息不等于可无偏地作为疾病因果证据 |
| Cheng et al., [Blood cultures before/after antimicrobials](https://pubmed.ncbi.nlm.nih.gov/31525774/) | 325 名严重 sepsis 表现患者的诊断研究中，抗菌药后血培养敏感度下降；支持“干预改变观察通道”的真实反例 | 单一研究不定义通用抗菌药观察模型或全部病原场景 |
| Pearl, [A Causal Calculus for Statistical Research](https://proceedings.mlr.press/r0/pearl95a.html) | 明确区分普通条件化与外部 intervention conditioning，并给出可识别规则 | 不要求系统只能用 DAG；假设不足时不能凭图自动得到因果效应 |
| Åström, [Optimal Control with Incomplete State Information](https://doi.org/10.1016/0022-247X%2865%2990154-X)（[Lund record/PDF](https://lup.lub.lu.se/record/8867084)） | 隐状态、观察信息和控制分离有正式控制理论传统 | 不证明临床核心应采用 POMDP 或 Markov 假设 |
| Belnap, [A Useful Four-Valued Logic](https://doi.org/10.1007/978-94-010-1161-7_2) | 不完整/不一致信息可以有非爆炸形式语义 | 四值不足以替代 typed missingness、时间、概率和 provenance |
| [UCUM 2.2](https://ucum.org/ucum) | 机器间无歧义单位通信、量纲语义和可计算等价 | 单位等价不等于 analyte、specimen 或 assay 语义等价 |
| [21 CFR 11.10](https://www.ecfr.gov/current/title-21/part-11/section-11.10) | 官方条文要求准确/可靠、可识别无效或篡改记录、带时间戳审计轨迹，修改不遮蔽先前记录 | 该法规适用范围有限，不是动态临床表示的形式规范 |
| [PROBAST+AI 2025](https://doi.org/10.1136/bmj-2024-082505) | 将模型开发质量、性能评价风险和 intended-use applicability 分开；强调外部验证、代表性与公平 | 报告/评估工具不决定架构，不证明某模型临床有效 |
| [IMDRF N41 SaMD Clinical Evaluation](https://www.imdrf.org/documents/software-medical-device-samd-clinical-evaluation) | valid clinical association、analytical/technical validation、clinical validation 以及持续评价是不同层 | 监管共识不能替代具体产品/场景的临床证据 |

### 8.1 来源交叉得出的限制性结论

1. FHIR、PROV、开放世界逻辑、双时态数据库、因果推理和不完全信息控制**各只覆盖部分不变量**；任何一个都不能单独成为本问题答案。
2. 标准字段只是表达能力 R，不是运行时强制 E；Checkpoint 4/5 必须用负例证明非法消费真的被拒绝。
3. provenance 与 audit 是必要但不充分：严格回放还需要规则、模型、术语、配置、随机性/外部响应版本。
4. 状态/观察分离是必要区别，但不推出状态的具体载体，更不推出 Markov、Gaussian、连续或有限维。
5. 开放世界是知识语义，OOD 是统计性能问题；架构只能保证能 abstain，不能保证何时应该 abstain 已经校准。

---

## 9. 对当前 `REQUIREMENTS.md` 的具体修订清单

以下建议基于本轮读取的 `REQUIREMENTS.md` 0.1。主 agent 可逐条落盘；本子任务不直接修改该文件。

### 9.1 必须改写的现有 HARD

1. **R-EPI-01**：把“真实/潜在状态”改成“患者现实的模型内表示/状态假说”，避免暗示系统持有真值；补 `reported content` 与 `reporting act`；说明语义 role 可作为 facet，不强制每个角色都是互斥 object type。
2. **R-EPI-02**：把“依赖图”改成实现中立的“依赖关系/证明对象”；允许派生主张合法供下游使用，禁止的是无根或直接/间接自支持以及与祖先重复计权。
3. **R-TIME-01**：从双时间提升为至少 `effective/occurrence`、`available/issued`、`recorded/transaction` 三类；明确 cutoff 以 available time 判定资格。
4. **R-TIME-02**：删掉“过期观察不进入当前读出”的绝对句；改为“过期不得无标记地代表当前状态，是否消费由版本化任务/模型声明；历史证据不删除”。补 interval、time precision、unknown time 和 partial order。
5. **R-TIME-03**：除规则/术语/模型外，加入 data version、config、code/build、random seed/recorded stochastic output、external service response snapshot。
6. **R-OBS-01**：原句“观察值必须绑定方法、条件、支持治疗、单位、可靠度……”对所有观察过强。改为“每种 observation contract 声明其必需字段；未提供的必要上下文显式 unknown/unsupported；不相关字段不强制填”。把“可靠度”拆成 measurement quality、source trust、applicability。
7. **R-OBS-02**：加入 observation opportunity、measurement selection/frequency；治疗可同时改变 state dynamics、observation channel 和 observation policy。
8. **R-UNC-01**：明确这些状态不是一个互斥枚举；拆为 assertion polarity、missingness/acquisition、quality、conflict、applicability、model coverage/OOD、probability/interval。
9. **R-PROV-01**：`100%` 只对进入关键结论的全部依赖强制；trace 包括患者输入、一般知识、规则/模型/术语/配置版本。若原始数据因权限不能内嵌，应保留稳定引用/hash 和 masked 状态，不能假装完整可见。
10. **R-PROV-02**：删掉把“独立来源计数”当通用 oracle；改为 clone 不增根证据，聚合器还必须声明 dependence/independence，来源不同不自动独立。
11. **R-PROV-03**：强调撤回后所有受影响输出均重算/失效；仍有其他支持的结论可以保留，但必须生成新依赖/结论版本，不能沿用旧 trace。
12. **R-INT-01/R-INT-02**：补 proposal/request/authorization/dispense/administer/partial/fail/cancel；把“干预可改状态”与“从观察识别因果效果”分开，不能因可表示干预就声称效应已知。
13. **R-COMP-01**：限定“核心修改数 0”适用于系统已声明支持的 ordinary medical content extension；真正新语义允许核心版本升级，但需不可表达 witness、migration 和旧 replay。
14. **R-COMP-02**：补 n-ary、time lag、threshold/saturation 和近似假设；`no interaction record` 不等于 interaction=0，需分 absent/not-retrieved/unknown/conflict/assumed-additive/evidence-of-none。
15. **R-TASK-01**：把“底层记录”明确为共享 evidence/event history，不承诺一个对全部任务充分的 patient state；任务合同加入 estimand/target、horizon、information cutoff、loss/utility、applicability。
16. **R-OPEN-01**：补 known + unknown 可共存、候选不强制归一为 1；强调架构支持 abstain 不代表 OOD 检测已验证。
17. **R-REP-01**：拆为 `historical_as_known` 与 `retrospective_with_current_knowledge`；硬要求是语义重放，跨平台 bitwise equality 降为 SOFT。
18. **R-SAFE-01**：补 invalid input quarantine、原 payload、失败原因、修正晋升事件；不得让 invalid artifact 进入 active evidence。
19. **R-SAFE-02**：要求 mandatory safety rule coverage report；每条规则 evaluated / not-applicable / not-evaluable，not-evaluable 必须触发声明的 fail-closed 策略。
20. **R-ID-01**：把“自然语言改写必同构”限定为“同一规范化主张与上下文”；适配器遇到真歧义可输出候选/unknown，不应为了同构强行单选。补 mapping/version/raw span。
21. **R-ID-02**：保留，但 collision oracle 必须声明任务；有些状态对诊断可等价、对治疗安全不等价。

### 9.2 必须从 HARD 降为 SOFT/ANTI 的条目

1. **R-MIN-01 整体从 HARD 移出。** 原语不可约性不是可一般判定的患者安全不变量，而且不同形式之间 primitive count 不可直接比较。改为：
   - `S-MIN-01`：统计核心类型 + 操作 + 内建关系 + 强制 metamodel + 隐藏解释器分支；
   - `S-MIN-WITNESS`：每个保留原语给出合并后会失败的 witness；
   - `ANTI`：万能 blob/node/callback 作弊压低原语数。
2. **“核心永不修改/所有扩展核心修改数必须 0”降为混合。** ordinary content extension 的 core modification=0 是 HARD；真正新语义的修改频率、迁移成本和 blast radius 是 SOFT。
3. **LLM 可填写、人工编写容易是 SOFT。** 临床关键 trace 可审计和契约强制是 HARD；LLM 成功率、字段负担、审核时间是 Pareto 指标。
4. **bitwise replay correctness 降为 SOFT。** 同快照语义等价、未来隔离和版本完整是 HARD。
5. **任意非线性交互“都能自动处理”不得列 HARD。** 声称支持的交互可表达/执行和未知组合显式是 HARD；覆盖率、发现能力与计算效率是 SOFT。
6. **“人类能理解全部内部数学”不应列 HARD。** 关键输入、假设、版本、依赖、失败和输出语义可审计是 HARD；人工审核节点数和数学负担是 SOFT。

### 9.3 当前文档需要新增的 HARD/H(scope)

建议新增至少：

```text
R-SCOPE-01  subject/encounter/specimen/body-site/device identity integrity
R-UNIT-01   dimension/unit/scale/method/assay validation + raw roundtrip
R-TERM-01   system+version+code and directional/contextual mappings
R-MISS-01   observation opportunity/selection/missingness process
R-INFO-01   probability/score orthogonal to assertion/missing/conflict/applicability/OOD
R-KNOW-01   knowledge/model/rule/terminology/config/external-response version pin
R-CORR-01   correction/retraction/replacement cascade and old-history retention
R-CONF-01   contradiction preservation and non-explosion
R-CAUS-01   association vs intervention/counterfactual + identifiability gate
R-DEC-01    inference vs goal/utility/preference/authorization/action
R-COMB-01   composition unknown/conflict/approximation status
R-NUM-01    numerical diagnostics and explicit degraded/failure status
R-QUAR-01   invalid input quarantine and explicit promotion after repair
R-IDEMP-01  idempotent ingest/action and duplicate root prevention
R-ORDER-01  causal/partial order and concurrent reconciliation
R-MASK-01   masked/restricted/not-permitted not equal absent/negative
R-FEED-01   decision exposure and feedback-contamination guard
```

### 9.4 软指标表需要修正的重复/冲突

- `S-PROV-01 Trace completeness` 与 HARD R-PROV-01 不冲突的写法：关键结论必须 100%；软指标只衡量非关键/辅助产物的覆盖率与 trace 成本。
- `S-REP-01 Replay correctness`：硬 fixture 必须 100%；软指标衡量性能、跨平台 bitwise 一致和非关键历史覆盖。
- `S-COLL-01`：硬 collision 用例不得失败；软指标统计扩展/模糊任务上的碰撞数。
- `S-EXP-01 表达完整性`：H 用例不是“比例”，任一失败即淘汰；比例只用于非硬扩展集。

---

## 10. Checkpoint 1 当前假说、最强反对意见与推翻条件

### 当前假说

可能存在一个小而稳定的固定内核，但“固定”的对象更可能是**语义角色、合法变换、版本/时间资格、依赖与失败合同**，而不是一套固定医学坐标或固定疾病动力学。这个假说尚未被原型证明。

### 最强反对意见

1. **不存在小内核**：母胎、多主体感染、连续波形、组织病理、基因组和行为健康可能需要不可统一的原语；所谓统一内核最终会退化成万能容器。
2. **要求过度工程化**：把所有时间、来源、权限、版本和不确定性都一等化可能使知识作者和运行成本不可接受，导致系统虽正确但不可用。
3. **语义区分仍可能带候选偏见**：依赖、版本和回放容易暗示事件溯源/图；必须允许非图实现用等价证明对象通过。
4. **临床真值与因果效应不可由架构保证**：即使所有不变量通过，医学知识可错、模型可失准、观察数据可混杂、决策效用可争议。
5. **局部组合与全局一致有根本张力**：新机制可能改变旧概念边界；“保守扩展”有时与科学修订冲突，只能靠版本并存而不是让旧语义永远正确。

### 会推翻或修改当前假说的证据

- 三个以上真正不同的候选都只能通过加入同等数量的全局 special cases 才满足硬测试，说明“小统一内核”可能不存在；
- 某个必要临床反例无法在不引入领域专属核心原语的情况下表达；
- provenance/版本/typed uncertainty 的审计负担在专家测试中高到使关键判断不可完成，且没有等价压缩；
- 同一最小原语在两个必须支持的任务中要求互相矛盾的组合律，不能靠显式 task semantics 隔离；
- 统一测试揭示某条所谓 HARD 对所有安全候选都不必要，或一个候选违反它仍能无碰撞、无泄漏、可审计地给出正确失败；该条应降级。

### Checkpoint 2 前的停手结论

现在不能选赢家。能够淘汰的只是那些**结构上无法强制上述区别**、只能靠 prompt/人为约定避免非法状态、或遇到未知时静默近似的候选版本。下一步应把本笔记的 H 压成一组最小、实现中立的 fixtures，再去广泛比较候选；不应因为现有仓库已有 SDE/向量/图代码而优待它。
