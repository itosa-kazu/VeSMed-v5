# 新临床动态地图：真实复杂病例红队实验草案

> 状态：设计草案，尚未执行；本文只规定怎样真正攻击**新框架**，不评价 V5，也不把 V5 的结果转移为本框架证据。

## 0. 要攻击的对象

本轮候选架构固定为：

```text
患者状态 =
    机制／拓扑分支的不确定分布
  + 分支内局部连续坐标
  + 代偿／失代偿等离散运行模式
  + 足以支持当前动作集合的历史摘要

因子图：内部状态怎样生成检查和症状
混合受控动力学：时间和治疗怎样改变状态与模式
分支／分层几何：什么患者在临床上真正接近
共享状态：诊断、自然预测、治疗预测的唯一共同输入

新动作揭示旧状态碰撞时：
  检测碰撞 -> 寻找新检查／新变量 -> 局部拆分或明确 scope_insufficient
```

本实验不问“它听起来是否合理”，而问以下八项可以失败的主张：

| 编号 | 被检验主张 | 可以推翻它的证据 |
|---|---|---|
| C1 | 单一共享状态足以支持诊断、自然预测、治疗预测和增量更新 | 任一任务需重读原始历史、私有患者 cache 或任务专属持久状态 |
| C2 | 分支 posterior 能保留真正重要的机制不确定性 | 把仍可导致相反行动的机制压成一个点或一个 argmax 标签 |
| C3 | 分支内局部坐标足以描述连续演化 | 同一分支同一局部坐标在可见信息充分时仍产生不可解释的相反未来 |
| C4 | 离散模式能表达代偿、失代偿和规律切换 | 代偿／失代偿同点被合并，导致运动方向或最佳行动相反 |
| C5 | 因子依赖能避免证据重复并解释 observation generation | 复制同一标本、同一上游机制的派生指标后置信度被重复放大 |
| C6 | 历史摘要保留所有当前行动相关信息 | 删除动作、先后次序或响应历史后状态不变，但未来／行动应不同 |
| C7 | 分支几何中的“近”对应受控未来相似 | 地图近邻比诊断中性的强基线更差，且频繁跨越相反治疗效应边界 |
| C8 | 新动作可触发安全的局部细化 | 对新动作强行外推、静默映射旧动作，或在没有信息时伪造患者分型 |

## 1. 两个真实复杂病例

两个病例只提供**事实轨迹与可用时间**。它们不能提供同一患者未发生治疗分支的唯一真值；精确反事实另由有明确真值的 shadow worlds 检验，见第 3 节。

### Case A：急性 A 型肝炎—急性肝衰竭—Takotsubo—心源性休克—恢复

来源：[Fulminant hepatitis A complicated by Takotsubo syndrome](https://pmc.ncbi.nlm.nih.gov/articles/PMC7005653/)。

关键公开事件：

1. 入 ICU：61 岁女性；AST/ALT、胆红素、INR、氨升高；血流动力学稳定，无肝性脑病；ECG、troponin 正常，LVEF 52%。
2. 病因工作：肝活检符合急性肝炎，HAV IgM 阳性。
3. ICU day 2：数小时内进展为 IV 级肝性脑病并插管；AST 下降但胆红素、氨及凝血功能仍异常。
4. 同日出现新心脏过程：troponin I 11.19 ng/ml、LVEF 32%、室壁运动异常；冠脉造影正常，符合 Takotsubo。
5. 随后低血压，给予 dobutamine 和低剂量 noradrenaline；心源性休克使肝移植禁忌。
6. 连续 3 日血浆置换后临床、心功能、肝功能和颅内高压代理改善；day 9 拔管，day 14 转普通病房。

它攻击的结构：

- 肝炎机制、肝衰竭状态和应激性心肌病是**可同时激活、相互影响且随后退出**的过程，不是互斥的病名投票；
- AST 下降不等于肝功能恢复，必须区分细胞损伤、合成功能、氨清除和脑病模式；
- “当前血压正常”必须连同 inotrope/vasopressor 支持解释；
- day 2 发生离散模式切换，并改变移植这一动作的可行性；
- 治疗后恢复不能反推血浆置换的个体因果效应。

### Case B：APS 背景—anti-GBM 假说—活检出血—TMA 证据—治疗重定向

来源：[Complement-Mediated TMA in a Patient With APS and Anti-GBM Antibodies](https://pmc.ncbi.nlm.nih.gov/articles/PMC10448002/)。

关键公开事件：

1. 入院：30 岁女性，APS、既往妊娠期高血压/HELLP 背景；肌酐 1.83、Hb 11.1、platelet 92k、LDH 335、anti-GBM antibody 升高；干咳和泡沫尿，胸 CT 无异常。
2. 按 presumed anti-GBM disease 开始 plasma exchange 与 IV steroid；apixaban 改为 heparin；计划肾活检。
3. day 3 肾活检；次日局部疼痛、Hb 7.6、platelet 40k，并发现肾周血肿。
4. 此时至少存在三条解释分支：活检出血/稀释，heparin-associated thrombocytopenia，或微血管病性溶血/TMA。
5. 随后 biopsy 显示 acute/chronic TMA、无 anti-GBM disease；C3/C4 与 haptoglobin 低、schistocytes、HIT 阴性、ADAMTS13 61%，使 TTP 和 HIT 分支下降、complement-mediated TMA 分支上升。
6. 住院后期以 warfarin 管理 APS，并加入 rituximab、eculizumab；day 15 稳定出院，creatinine 下降；遗传确认计划门诊完成，因此 complement-mediated TMA 仍不是遗传金标准确证。

它攻击的结构：

- anti-GBM antibody 是 observation，不应被直接当作 anti-GBM disease 隐状态；
- Hb/platelet 下降发生在活检之后，动作与先后顺序不可丢；
- schistocyte、LDH、haptoglobin、Hb 不是四张独立票，而是共享 hemolysis/TMA 上游因子；
- biopsy 同时改变观察信息并带来真实生理风险，检查不是纯读数；
- 多个治疗同时启动，病例无法单独识别 eculizumab、rituximab、steroid 或 PEX 的个体因果效应。

## 2. 事实回放协议

### 2.1 事件类型

所有输入都必须带四个时间：`occurred_at`、`measured_at`、`available_at`、`recorded_at`。最小事件类型：

```text
ObservationAvailable
TestOrdered
TestPerformed
PerformedTreatment
PlannedTreatment
TreatmentStopped
SupportChanged
ClinicalModeObserved
```

只有 `available_at <= cut` 的信息可更新状态。`PlannedTreatment` 不是生理干预，`TestPerformed` 也不等于结果已经可见。

### 2.2 固定 cuts

Case A 至少使用：admission、etiology available、day2 pre-cardiac-result、day2 post-cardiac-result、post-support/pre-PEX、after session 3、extubation、ward transfer。

Case B 至少使用：admission、after first PEX/steroid、post-biopsy pre-hematoma-result、hematoma available、TMA workup ordered、biopsy/TMA workup available、new-treatment initiation、discharge。

不得把论文叙述顺序伪装成精确时钟；论文未给出的结果时间使用 interval/partial order，而不是人为设 `day 6.5` 后当作真值。

### 2.3 候选运行接口

```text
Z0 = initialize(public_events_up_to_cut0)
Zt = update(Zt-1, newly_available_events, advance_to=t)

diagnose(M, Zt, query)
rollout(M, Zt, NoNewAction)
rollout(M, Zt, ContinueCurrent(schedule))
rollout(M, Zt, StopControllable(schedule))
rollout(M, Zt, Do(action_or_policy))
```

产生 `Zt` 的进程随后销毁。所有读出在 fresh process 中只能读取冻结模型 `M`、同一 exact `Zt` 和非患者 query。原始病例、case ID、论文标题、未来事件和 episode cache 一律不可见。

## 3. 两层 oracle：不要用病例结局伪造反事实真值

### 3.1 真实病例层

可验证：

- 下一批实际 observation 的预测分布；
- 下一模式/支持需求；
- 已知结果到达后的 posterior 更新方向；
- factual action 后的 observed response；
- 临床约束，例如 cardiogenic shock 时移植不可行。

不可验证：

- “若没有 PEX，该患者必然怎样”；
- “eculizumab 单独贡献多少”；
- 同一患者接受另一个治疗的唯一结局。

真实病例层对治疗只能用文献或专家预注册的**方向/安全/可行性约束**与部分识别范围，不能以事实结局当作该治疗的因果标签。

### 3.2 Shadow-world 层

以两个真实病例的可见事件形状为骨架，另建独立、已知生成机制的小世界。shadow world 必须明确标为 synthetic causal oracle，不得反过来称为临床验证。它提供：

- 所有允许动作的真实 transition 与 outcome；
- 可重置同患者实验；
- 精确 optimal action、regret 与 controlled-future distance；
- 同观察异机制、同连续点异模式、以及新治疗反向响应的构造对。

真实层回答“架构能否忠实处理真实复杂事件”；shadow 层回答“在反事实真值已知时，结构是否保留了行动相关区别”。两层都通过，仍只支持 bounded proof，不支持“全医学理想模型已证明”。

## 4. 实验矩阵

### E00：未来泄漏和病例身份负对照

攻击：把未来 biopsy/HAV/coronary 结果写入文件但设 `available_at > cut`；改变 case ID、疾病名、文章标题；插入 judge-only canary。

通过：cut 前 state hash 和所有输出不变；canary 不出现在 state/output。

硬失败：任何未来信息、expected diagnosis 或 case 名影响输出。

### E01：真实病例端到端事实回放

逐 cut 记录：分支 posterior、局部坐标分布、模式 posterior、预测未来 observation、动作可行性与不确定性。重点不是 top-1，而是状态演变是否满足预注册约束：

- Case A：HAV/ALF 过程不能因 Takotsubo 出现而消失；Takotsubo/心源性休克分支应在 day2 证据到达后激活，并在恢复阶段下降；支持剂量必须解释表面血流动力学。
- Case B：positive anti-GBM observation 先提高而非确定 anti-GBM 分支；biopsy/TMA workup 到达后 anti-GBM disease 降、TMA 升；post-biopsy anemia 不得只被 TMA 吸收。

这项只能检验更新合理性和预测校准，不能证明个体治疗因果。

### E02：共享状态 operational identity 与 closure

对同一 cut：

1. 持久化一次 exact state bytes；
2. 计算 hash；
3. 在互相隔离的进程中运行 diagnosis、natural rollout、每个 treatment rollout；
4. transcript 必须显示相同 `consumed_state_hash`；
5. 删除 episode 目录、raw history 和 producer process 后再读出、再 update。

通过只证明 operational shared state。要声称 semantic unity，还必须证明：无 task-exclusive state 槽、无 task-specific updater；自然和治疗 rollout 使用同一 transition core；任一 informative update 同时改变所有相关 readout。

硬失败：任何 head 重读病历或拥有患者私有 cache。仅把三份任务 latent 拼成一个 JSON 不算 semantic unity。

### E03：历史摘要和 action-aware 更新

构造仅在历史上不同但当前数值相同的成对轨迹：

- Case A：同 MAP/EF，一例无支持，一例依赖 dobutamine/noradrenaline；
- Case A：同 bilirubin/INR，一例刚完成 PEX，一例未接受；
- Case B：同 Hb/platelet，一例刚做肾活检且有血肿，一例无侵入操作但存在 hemolysis；
- Case B：heparin 仅 planned、已 started、已 stopped 三种版本。

删除、交换或伪造 `PerformedTreatment` 与 response 顺序；保持最后一帧 observations 相同。

通过：会改变未来或动作的历史区别必须改变 state/rollout；行为无关的旧文书措辞、重复记录和格式差异不得改变行为 state。

硬失败：当前快照相同就合并上述成对轨迹；或 planned action 被当作 performed physiological action。

### E04：NoNewAction / Continue / Stop / Do 的语义分离

从同一 `Zt` fork：

- `NoNewAction`：不新增动作，但既往药效/支持后效继续衰减；
- `ContinueCurrent`：按显式 schedule 继续；
- `StopControllable`：撤去可控支持，但不会抹掉已发生暴露；
- `Do(A)`：主动干预，不是条件化于历史上接受 A 的患者。

攻击：交换四种 policy 名、去掉 performed/planned 标记、将 `P(Y|A,Z)` 冒充 `P(Y|do(A),Z)`。

硬失败：四种 rollout 相同；停止治疗等于“从未治疗”；或观察到治疗与实施治疗使用同一条件概率。

### E05：离散模式、临界转变与滞后

真实层：在 Case A 的 encephalopathy/intubation、Takotsubo/cardiogenic shock；Case B 的 biopsy-hematoma 事件上测试 mode posterior 是否在新证据到达后切换，并允许恢复退出。

shadow 层构造两对同连续坐标：

1. 代偿患者受到小扰动后返回；失代偿患者同一点后继续偏离；
2. 从健康方向到达阈值与从失代偿恢复方向到达同一点，未来不同（hysteresis）。

消融：移除离散 mode，只保留连续坐标并做容量匹配。

通过：完整模型显著降低运动方向错误、mode transition log loss 与 treatment regret；不是仅靠增大参数量。

硬失败：完整模型仍将同点相反未来合并，或 mode 只是对输出的事后标签而不进入 transition。

### E06：机制／拓扑分支 posterior

Case A 必须允许“hepatitis cause -> liver failure state”与“Takotsubo/cardiogenic shock”并存；Case B 必须允许出血、HIT、TMA、anti-GBM 等解释在证据到达前并存，而非强制 one-hot。

消融：

- argmax-only branch；
- 单全局连续空间；
- 独立病名 softmax；
- 完整 branch posterior。

shadow 层使用 posterior 形状相同均值不同、均值相同形状不同的 pair，令不同尾部机制决定相反治疗风险。

硬失败：把 posterior 压成均值/argmax 后出现相反效应 collision；平均 top-1 指标不能抵消一次 catastrophic collision。

### E07：因子依赖与证据复制攻击

Case A：同一抽血/同一 liver injury 因子生成 AST、ALT 和派生“transaminases elevated”；同一 cardiac process 生成 troponin、EF、wall-motion pattern。Case B：hemolysis/TMA 因子生成 Hb、LDH、haptoglobin、schistocytes；单一 biopsy specimen 生成多段病理描述。

攻击：

1. 复制同一结果十次，改变 note 顺序、单位和同义词；
2. 添加一个确定性派生 bundle；
3. 同一标本拆成多个报告；
4. 删除上游因子边，仅保留 observation independence；
5. 加入真正独立的新标本/新模态作为正对照。

通过：重复/确定性派生信息不应获得十倍 Bayes evidence；真正独立的新观测应收缩 posterior。必须审计 effective evidence count 与 factor-message provenance。

硬失败：复制文字即可任意提高置信度，或所有观测被一个万能 latent 吸收而真正独立证据也不增加信息。

### E08：分支／分层几何是否有行为意义

距离不能由“病名一样”定义。冻结 scope 后定义 oracle controlled-future distance：

```text
d_S(h,h') = max over allowed policies and horizons
              distance(P(future | do(policy), h),
                       P(future | do(policy), h'))
```

比较：原始 observation 欧氏距离、诊断标签距离、学习 embedding、分支测地距离。评价近邻的自然轨迹误差、治疗效应方向错误与 cross-applied regret。

负对照：轴重命名、单位等价转换、局部坐标的可逆重参数化、医院模板变化，几何行为应近似不变。

硬失败：地图近邻频繁具有相反治疗效应，或几何只在原始坐标参数化下成立。只在两个病例上画得好看不是几何证据；精确检验主要依赖 shadow pairs 和后续病例队列。

### E09：状态碰撞与 false split

**危险碰撞**：两个 history 被映成同一点/极近，但存在以下任一项：最佳动作集合不相交、治疗效应方向相反、cross-applied regret 超过预注册 catastrophic margin、禁忌证被消掉。任何 exact dangerous collision 都是硬失败。

**False split**：两个 history 在冻结的所有检查、行动、时间范围和结局上等价，但候选因患者 ID、医院、文字顺序、重复计数而分开。这首先是压缩/最小性失败，不自动等同于安全失败。

归因顺序：

1. true-state oracle 是否也碰撞；
2. full-visible-history baseline 是否碰撞；
3. capacity-matched state-only probe；
4. fresh-process closure；
5. 才归因于表示、更新、head、不可识别或 OOD。

### E10：新治疗、新检查与局部细化

在 base state 和动作 catalog 完全封印之后 reveal 三种 extension：

1. **旧 state 已保留相关区别**：新治疗作用依赖旧机制坐标。只加新的非患者 transition/readout 参数，应可少样本接入，不需重放历史。
2. **历史曾可见但旧 state 丢失了区别**：新治疗使两个旧 state 相反响应。候选必须报告旧状态不充分；若要 split，须声明需要 history replay/migration，不能假装 replay-free local refinement。
3. **此前不可观察的新亚型**：新治疗对两类人反向作用，但旧 history 和所有旧检查完全相同。系统必须在新检查到来前保持不可识别/abstain；新 biomarker 到来后才局部拆分。

另加“没有任何安全检查、只有可能致命的治疗能揭示类型”的版本，验证系统不会把探索风险隐藏在信息增益里。

硬失败：静默将新治疗映射为旧治疗；没有证据却给个体强行分型；或声称任何新 action 都能在不 replay、不新观察的情况下局部细化。

### E11：分支退出、汇合和恢复

Case A 恢复后 Takotsubo、心源性休克、肝性脑病 active mass 应下降；Case B biopsy hematoma 稳定后急性出血 mode 应退出，但 APS 背景仍在。测试架构是否只会累加病名，还是能表达 branch activation、deactivation、汇合与遗留状态。

硬失败：一旦激活便永久保留为 active disease；恢复只能靠覆盖当前标签而丢失后效；或退出后把既往动作/损伤从历史摘要抹掉。

### E12：不可能性边界

构造两个因果世界，使它们对所有已观察数据和可安全实施实验完全相同，却对目标个体反事实给出相反答案。另构造完全无前兆的外源突发事件。

正确输出是：相容世界集合、反事实上下界、缺少的区分信息、robust/minimax-regret action 或拒答。以下不是失败：

- 无法唯一恢复个体未发生分支；
- 无法预测没有任何前兆的外源冲击；
- 新治疗前相关亚型不可观察。

真正失败是：把结构先验选中的一个世界冒充数据确定的真相，或者在不可识别处输出伪精确概率。

## 5. 必做消融和基线

为防止“复杂架构只是参数更多”，所有比较须容量/训练预算匹配：

| 组 | 内容 | 要隔离的贡献 |
|---|---|---|
| B0 | 最后快照模型 | 历史价值 |
| B1 | 全可见历史模型 | 信息上界与压缩代价；不是可部署共享状态证明 |
| B2 | 单全局连续 state | 分支和离散 mode 的增量 |
| B3 | branch argmax + local vector | posterior 分布的增量 |
| B4 | shared encoder + 三个独立 task state | operational sharing 与 semantic unity 的区别 |
| B5 | 完整候选但观测条件独立 | factor dependence 的增量 |
| B6 | 完整候选但无 action history | action-aware history 的增量 |
| B7 | 完整候选但无 discrete modes | mode switch/hysteresis 的增量 |
| B8 | true-state oracle | benchmark 的可达到上界 |

必须报告每项任务，而不能只报告平均总分：diagnostic calibration、next-event log score、mode transition、natural rollout、intervention regret、collision、false split、OOD/abstention、state bytes/update latency。

## 6. 预注册判定规则

### 6.1 任一即推翻当前实现的硬失败

1. 未来泄漏、case ID/label/test-ID 分支、oracle true-state access；
2. diagnosis/forecast/treatment 不是消费同一 exact state，或任一 head 重读 history/cache；
3. 任一 exact dangerous collision；
4. planned action 被当作 performed，或 conditioning 被冒充 intervention；
5. 复制同源证据可任意提高置信度；
6. 已知相反动力学 mode 被塌缩；
7. 新 action 被静默映射到旧 action；
8. 不可识别处伪造个体确定答案；
9. abstain/scope_insufficient 接口虽存在，但在危险 OOD 上仍强制 known action。

### 6.2 不构成推翻架构本身

- 某一具体参数模型在样本量不足时校准差；
- 对不可识别个体反事实输出区间或拒答；
- 对无前兆外源冲击无法提前预测；
- 新 action 证明旧 scope 不充分并要求新检查或 migration；
- false split 存在但不产生行动差异：这反驳“最小”，不自动反驳“充分”。

### 6.3 何时只能说“未决”

- 真实病例只有 factual trajectory，缺独立反事实证据；
- mode/branch 的人工 adjudication 没有盲评与 inter-rater agreement；
- 只在这两个病例或其同源变体上通过；
- shadow world 生成器与候选共享了机制代码；
- full-history baseline 也失败，且无法区分数据不可观察与 head underfit。

## 7. Shared state “同一性”的证据等级

| 等级 | 证据 | 能声称什么 |
|---|---|---|
| L0 | 一个对象名叫 shared state | 无证据 |
| L1 | 三个任务输入字段相同 | API 表面共享 |
| L2 | 同一 exact state bytes/hash，fresh process 读出 | operational identity |
| L3 | producer 销毁、raw history 删除后仍可读出并增量更新 | operational closure |
| L4 | 同一 transition core、task-neutral update、无 task-exclusive persistent slots | 审计支持 semantic unity |
| L5 | 删除/扰动任何 state component 对所有相关任务的影响与统一机制一致，且 novel post-seal readout 可由 sealed state 支持 | 更强但仍有限的 semantic evidence |

即使达到 L5，也不能数学证明 opaque state 中绝不存在任务复用编码；应写“在已审计范围内支持”，不能写“证明了唯一理想状态”。

## 8. 预期产物

```text
case_sources.json
public_events.jsonl
partial_order_constraints.json
cut_manifest.json
oracle_constraints.json
shadow_world_spec.json
model_seal.json
state_snapshots/<case>/<cut>.bin
query_transcripts.jsonl
prediction_rows.parquet
collision_pairs.jsonl
ablation_results.json
extension_commitment.json
extension_reveal.json
VERIFICATION.json
FINAL_REPORT_CN.md
```

`FINAL_REPORT_CN.md` 必须按“结果 -> 关键证据 -> 验证 -> 下一步”写，并把结论限定为：

- 当前实现通过/失败了哪些声明；
- 哪些是数据或不可识别边界；
- 哪些是两个真实病例支持的事实回放证据；
- 哪些仅由 synthetic shadow worlds 支持；
- 有没有 exact dangerous collision；
- 是否真的达到 shared-state closure/semantic unity；
- 新治疗是局部细化成功、诚实 scope failure，还是无依据强行外推。

## 9. 最核心的判词

这套实验最重要的不是“两个病例最后诊断对不对”，而是寻找以下反例：

```text
候选说两个患者／两段历史是同一状态，
但某个允许行动让它们走向相反未来。
```

找到一个可观察、可验证的 exact dangerous collision，就足以否定**当前状态定义/当前实现**；它不自动否定“受控未来行为等价”这一抽象定义。反过来，两个病例全部跑对，也不能证明存在一个永久、有限、覆盖未来所有检查和治疗的理想模型。最强合法结论只能是：

> 在预先冻结的检查、行动、时间范围、结局和误差容限内，当前共享状态没有在本轮红队中暴露危险碰撞，并比容量匹配基线更好地保留了动态、依赖和行动相关信息。

