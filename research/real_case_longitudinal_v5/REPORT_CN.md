# V5 两个复杂真实病例的全程压力测试

## 结论先行

这轮实验没有推翻聊天中提出的抽象架构；它推翻的是一个更强、但此前没有被证明的说法：

> **当前 V5 runtime 已经实现了那套“共享动态患者状态”，并且足以端到端处理复杂病程与治疗。**

实际结论是：

1. **当前的静态、单病几何有局部价值。** 在补体介导 TMA 病例中，它能随新增血象/病程证据把单病首位从 anti-GBM 转到 complement-mediated TMA，后来出现的病理/溶血证据继续维持该排序；在 HAV 病例入院早期，也能把 acute hepatitis A 排首位。
2. **当前 runtime 不是纵向共享状态模型。** 每个时间切片独立重算；同一 axis 的旧值会被 nearest/latest 值覆盖；action history 不进入诊断 ranking；没有把上一时刻 posterior 递推到下一时刻。
3. **复杂多过程病程会击穿当前几何。** HAV-ALF 病例 day 2 新发 Takotsubo/cardiogenic shock 后，系统被 troponin 等心脏证据拖向不合理的 systemic sclerosis renal crisis；即使穷举全部 17,020 个单病和双病候选，也没有恢复正确病程组合。
4. **当前治疗模拟器不能用于行动选择。** 它没有承接诊断 posterior，而是直接读取病例预设的 expected manifold；同时没有可靠执行互斥、适应证和禁忌证约束，产生了临床不可接受的组合。
5. **因此不存在一张已经验证完成、永远不变的“理想地图”。** 固定行动集合和时间范围后，可以抽象定义理想的行为/反事实等价状态；但它可能不可有限压缩、不可识别，并会被新检查和新治疗继续拆分。聊天中的结构更适合作为研究规格，而不是已经验证的最终模型。

总判定：**当前 V5 = 有用的静态几何 PoC，但尚未达到聊天所定义的动态统一临床地图。**

---

## 实验对象与边界

### 病例 A：最初按 anti-GBM 治疗，随后转向 complement-mediated TMA

- 来源：[PMC10448002](https://pmc.ncbi.nlm.nih.gov/articles/PMC10448002/)
- 文献过程：30 岁女性，有 APS；anti-GBM 抗体阳性，入院按 anti-GBM 治疗；肾活检不支持 anti-GBM、而显示 TMA，之后补体/溶血证据支持 complement-mediated TMA，最终使用 rituximab 与 eculizumab，住院第 15 天出院。
- 注意：这里的 complement-mediated TMA 是论文支持的临床解释；文献同时说明遗传检测安排在门诊，因此本实验不把它夸大为遗传学金标准真值。

用户可见病名：

- 補体介在性血栓性微小血管症 / Complement-mediated thrombotic microangiopathy / `D-COMPLEMENT-MEDIATED-TMA`
- 抗糸球体基底膜病 / Anti-glomerular basement membrane disease / `D-ANTI-GBM-DISEASE`

### 病例 B：HAV 急性肝衰竭，day 2 突发 Takotsubo 与心源性休克

- 来源：[PMC7005653](https://pmc.ncbi.nlm.nih.gov/articles/PMC7005653/)
- 文献过程：61 岁女性，入院时急性肝衰竭但血流动力学稳定、无脑病，EF 52%；day 2 发展为 IV 级肝性脑病并插管，troponin I 11.19 ng/mL、EF 32%、冠脉正常，发生 Takotsubo/cardiogenic shock；接受血浆置换，day 9 拔管，day 14 转普通病房。

用户可见病名：

- 急性A型肝炎 / Acute hepatitis A / `D-ACUTE-HEPATITIS-A`
- 急性肝不全 / Acute liver failure / `D-ACUTE-LIVER-FAILURE`
- たこつぼ症候群 / Takotsubo syndrome / `D-TAKOTSUBO-CARDIOMYOPATHY`（当前 active atlas 缺失）

### 重放方法

- 对两篇病例制作 11 个累计时间切片。
- 严禁未来资料倒灌到较早 cut。
- day 0.5 与 day 6.5 只表示论文可确定的先后顺序，不声称真实事件精确发生在半天；runtime 仍把它们当作数值时间，因此相应时间 likelihood 只算近似。
- 不修改 active disease distillation 或 active case 文件，不根据这两例修 atlas。
- 默认全 atlas 单病评分；关键 day 2 另行穷举所有单病与双病组合。

---

## 关键证据

### 1. 病例 A：单病排序的方向是对的，但它不是共享纵向推理

| 时间切片 | 单病首位 | 论文支持的 TMA 排名 | 聚焦双病首位 |
|---|---|---:|---|
| 入院 day 0 | 抗糸球体基底膜病 / Anti-GBM disease / `D-ANTI-GBM-DISEASE` | #2 | 補体介在性血栓性微小血管症 / Complement-mediated TMA / `D-COMPLEMENT-MEDIATED-TMA` + 抗糸球体基底膜病 / Anti-GBM disease / `D-ANTI-GBM-DISEASE` |
| 活检后 day 4 | 補体介在性血栓性微小血管症 / Complement-mediated TMA / `D-COMPLEMENT-MEDIATED-TMA` | #1 | 補体介在性血栓性微小血管症 / Complement-mediated TMA / `D-COMPLEMENT-MEDIATED-TMA` + 抗糸球体基底膜病 / Anti-GBM disease / `D-ANTI-GBM-DISEASE` |
| 血象早期改善 day 6 | 補体介在性血栓性微小血管症 / Complement-mediated TMA / `D-COMPLEMENT-MEDIATED-TMA` | #1 | 補体介在性血栓性微小血管症 / Complement-mediated TMA / `D-COMPLEMENT-MEDIATED-TMA` + 抗糸球体基底膜病 / Anti-GBM disease / `D-ANTI-GBM-DISEASE` |
| TMA workup ordering cut day 6.5 | 補体介在性血栓性微小血管症 / Complement-mediated TMA / `D-COMPLEMENT-MEDIATED-TMA` | #1 | 補体介在性血栓性微小血管症 / Complement-mediated TMA / `D-COMPLEMENT-MEDIATED-TMA` + 抗糸球体基底膜病 / Anti-GBM disease / `D-ANTI-GBM-DISEASE` |
| 出院 day 15 | 補体介在性血栓性微小血管症 / Complement-mediated TMA / `D-COMPLEMENT-MEDIATED-TMA` | #1 | 補体介在性血栓性微小血管症 / Complement-mediated TMA / `D-COMPLEMENT-MEDIATED-TMA` + 抗糸球体基底膜病 / Anti-GBM disease / `D-ANTI-GBM-DISEASE` |

这说明疾病 manifold 会随累计可见证据改变排序，属于**局部成功**；但 day 4 的切换发生在 TMA 病理/补体/裂红细胞结果可见之前，不能把切换因果归给那些后续证据。

但它没有证明“系统记住了病程”：

- 把既往 admission platelet 从 92 人为改成 250、保持后来 platelet 不变，4 个适用 cut 的 prepared observation map 与全部聚焦单病分数都完全不变。
- 删除 action history，5 个适用 cut 的聚焦诊断分数全部完全不变。
- 系统逐 cut 独立重算，没有把 day 0 的 posterior 作为 day 4 的 prior。
- TMA + anti-GBM 组合直到出院仍为聚焦首位，说明“先前假说经过反证后退出”并未作为状态转移被建模。

所以这个病例支持的是：**静态 evidence geometry 会随累计可见证据改变。** 它不支持：**当前已经存在递归更新的共享患者状态。**

### 2. 病例 B：新模式出现后，当前几何发生临床性失败

| 时间切片 | 单病首位 | HAV 排名 | ALF 排名 |
|---|---|---:|---:|
| 入院 day 0 | 急性A型肝炎 / Acute hepatitis A / `D-ACUTE-HEPATITIS-A` | #1 | #4 |
| 早期 workup day 0.5 | 急性A型肝炎 / Acute hepatitis A / `D-ACUTE-HEPATITIS-A` | #1 | #5 |
| 心脏崩溃 day 2 | 全身性強皮症腎クリーゼ / Systemic sclerosis renal crisis / `D-SYSTEMIC-SCLEROSIS-RENAL-CRISIS` | #3 | #4 |
| day 5 | 全身性強皮症腎クリーゼ / Systemic sclerosis renal crisis / `D-SYSTEMIC-SCLEROSIS-RENAL-CRISIS` | #3 | #4 |
| day 9 | 全身性強皮症腎クリーゼ / Systemic sclerosis renal crisis / `D-SYSTEMIC-SCLEROSIS-RENAL-CRISIS` | #3 | #4 |
| day 14 | 全身性強皮症腎クリーゼ / Systemic sclerosis renal crisis / `D-SYSTEMIC-SCLEROSIS-RENAL-CRISIS` | #3 | #4 |

这是明确失败，而不是“正确答案还在 top 10 所以算通过”。原因有三层：

#### 2.1 Atlas 缺少真正新出现的分支

active atlas 有 HAV 与 ALF，但没有：

- たこつぼ症候群 / Takotsubo syndrome / `D-TAKOTSUBO-CARDIOMYOPATHY`

因此它无法形成“原有 HAV/ALF 病程 + day 2 新发可逆性心肌病/心源性休克”这条真实组合轨迹。

#### 2.2 诊断中存在 axis alias/统一计分集合的几何断裂

HAV 与 ALF manifolds 使用 `serum_ast`、`serum_alt`、`prothrombin_time_inr`；病例原始中性轴使用 `aspartate_aminotransferase`、`alanine_aminotransferase`、`coagulation_inr`。准备层确实生成了精确 alias proxy，但全 atlas 固定 rankable-axis 集合最终让 AST/ALT 的 source axes 对 HAV/ALF 按 background 付费，而不是由它们自己的 disease trajectories 解释。

day 2 的最大残差显示：

- HAV 与 ALF 都把 troponin I 11.19 ng/mL 按健康背景计算，`|z| = 139.625`；
- HAV/ALF 的 ALT 3,922 U/L 仍显示为 background residual，`|z| = 13.805`；
- Systemic sclerosis renal crisis 恰有宽泛 troponin axis，因此在没有任何 systemic-sclerosis 主干证据时被推到首位。

这不是“模型发现了罕见强皮症”，而是**一个未被正确组合解释的心肌损伤坐标劫持了疾病排序**。

#### 2.3 开启全部双病组合反而放大错误

对 day 2 穷举：

- 184 个 active manifolds；
- 17,020 个单病/双病候选。

结果：

1. 急性A型肝炎 / Acute hepatitis A / `D-ACUTE-HEPATITIS-A` + 全身性強皮症腎クリーゼ / Systemic sclerosis renal crisis / `D-SYSTEMIC-SCLEROSIS-RENAL-CRISIS`
2. 急性肝不全 / Acute liver failure / `D-ACUTE-LIVER-FAILURE` + 全身性強皮症腎クリーゼ / Systemic sclerosis renal crisis / `D-SYSTEMIC-SCLEROSIS-RENAL-CRISIS`
3. アルコール性肝炎 / Alcoholic hepatitis / `D-ALCOHOLIC-HEPATITIS` + 全身性強皮症腎クリーゼ / Systemic sclerosis renal crisis / `D-SYSTEMIC-SCLEROSIS-RENAL-CRISIS`

而原病程组合及 atlas 内最近心肌损伤 proxy 的排名是：

- 急性A型肝炎 / Acute hepatitis A / `D-ACUTE-HEPATITIS-A` + 急性肝不全 / Acute liver failure / `D-ACUTE-LIVER-FAILURE`：#371
- 急性A型肝炎 / Acute hepatitis A / `D-ACUTE-HEPATITIS-A` + 急性心筋炎 / Acute myocarditis / `D-ACUTE-MYOCARDITIS`：#368
- 急性肝不全 / Acute liver failure / `D-ACUTE-LIVER-FAILURE` + 急性心筋炎 / Acute myocarditis / `D-ACUTE-MYOCARDITIS`：#374

这里的 acute myocarditis 只是当前 atlas 中可用的心肌损伤代理，不是论文诊断；论文支持的是 Takotsubo syndrome。

因此“多开 pair candidates”不是解决方案。当前组合操作只是在相加多个静态 manifold，并没有表达**某个时间点新机制激活、原机制继续存在、恢复后新机制退出**。

### 3. 历史和治疗动作没有进入同一个诊断状态

机器可验证探针：

- 8 个适用 repeated-axis history probes：改变旧值、保持最新值不变，prepared observation maps 与聚焦分数全部相同。
- 9 个有 action history 的 cuts：删除所有既往动作，prepared observation maps 与聚焦分数全部相同。

正确解释不是“runtime 完全不看时间”。当前评分仍会读取每个保留下来的 observation day，并保留每个 axis 的 nearest/latest 观测。真正被证明的是：

1. 同一 axis 的更早轨迹被覆盖；
2. action history 不参与诊断状态；
3. 没有跨 cut shared posterior；
4. 因此“EF 52% → 32%”与“EF 15% → 32%”在当前 cut 可以变成同一 prepared observation map，尽管动力学含义不同。

### 4. 治疗模拟器产生不可接受策略

为了让 treatment runtime 真正运行，修复了一处通用 API drift：`build_corr(...)` 调用缺少 `background_axes`。修复后得到的失败是 live runtime 行为，不是静态代码猜测。

#### TMA 病例

首位策略：

```text
 renal_replacement_therapy
+ eculizumab
+ ravulizumab
+ blood_pressure_control
```

问题：

- eculizumab 与 ravulizumab 是同一治疗通路的替代性 C5 抑制剂，不应作为并行联合方案；
- 病例未报告透析指征；
- simulator 从 expected `D-COMPLEMENT-MEDIATED-TMA` manifold 起跑，而不是从实际诊断 posterior 起跑。

#### ALF 病例

首位策略：

```text
 urgent_liver_transplantation_or_transplant_pathway
+ acyclovir_for_herpesvirus_context
+ pregnancy_context_delivery_or_obstetric_source_control
+ therapeutic_plasma_exchange
```

问题：

- 患者为 61 岁女性，病例没有任何妊娠或产科病因证据；
- 已证实 HAV，不是 herpesvirus ALF；
- 文献中 cardiogenic shock 正是肝移植禁忌背景；
- 各策略 RMST 几乎都饱和到 30 天，首位只比 untreated 多 0.01 天，区分没有可信决策意义；
- 首位策略 day 7 的模拟 mortality hazard 甚至高于 untreated。

血浆置换与论文实际治疗方向一致，但这只能说明 schema 中存在该动作，不能证明个体因果效果已经识别。

---

## “硬门禁”到底是什么

这里的门禁不是行政手续，也不是“必须准确率达到某个拍脑袋数字”。它们是让“我们已经做出了聊天里的系统”这句话成立所必需的可证伪条件。

| 门禁 | 通过标准 | 本轮结果 |
|---|---|---|
| G1 时间与来源完整性 | 较早 cut 没有未来 evidence/action；不确定时间显式标为 ordering coordinate | **PASS**：11 cuts；数值未来泄漏 0 |
| G2 诊断几何公平 | 同一中性事实跨病使用一致 axis；alias 不让应解释的疾病按背景付费 | **FAILED**：HAV/ALF AST/ALT alias 断裂 |
| G3 真实纵向共享状态 | 上一 cut posterior/状态递推；重复轴历史与动作响应在该相关时改变状态 | **FAILED**：8/8 history probes、9/9 action ablations 不改变聚焦分数 |
| G4 分支/模式与多过程病程 | 新过程可在正确时间激活、组合、退出，而非用不相干疾病吸收残差 | **FAILED**：Takotsubo 缺 leaf；day 2 被 SRC 劫持；全 pair 仍错误 |
| G5 未知/OOD 诚实性 | atlas 缺新过程时显式保留 representational gap，而非给不合理候选高置信解释 | **FAILED/PARTIAL**：coverage audit 能发现缺 leaf，但 live ranking 仍强配错误 manifold；health delta 只说明“有病”，不能指出缺的是哪个过程 |
| G6 观察—动作—状态分离 | 支持治疗不被当自然恢复；动作进入状态更新但不被当作病名标签 | **FAILED**：诊断不消费 action history |
| G7 治疗决策有效性 | 承接诊断 posterior；满足适应证、禁忌证、互斥与组合约束；因果边界明确 | **FAILED**：出现双 C5 抑制剂、妊娠处置、无关 acyclovir 等 |
| G8 防过拟合与独立验证 | 盲真实病例暴露失败，不改 active atlas/cases 迎合病例 | **PASS**：active atlas/cases 变更数 0 |

所以“尚未通过硬门禁”的精确含义是：**不是理论不够漂亮，而是当前实现仍会在已知真实病例上产生可复现的状态碰撞、错误组合和不安全治疗策略。**

---

## 聊天结论有没有被推翻

聊天中的候选架构是：

```text
患者状态 =
    机制／拓扑分支的不确定分布
  + 分支内局部连续坐标
  + 代偿／失代偿等离散运行模式
  + 足以支持当前动作集合的历史摘要

因子图：内部状态如何生成观察
混合受控动力学：时间和治疗如何改变状态/模式
分支/分层几何：哪些局部状态可比较、哪些必须通过分支转换
共享状态：诊断、预测、治疗读取同一 posterior
```

这里两个容易误解的词，落到本病例就是：

- **分支/分层几何**：不是把患者塞进一张永远平坦的向量表，而是允许不同病理区域使用局部坐标，并规定它们怎样共存或切换。本例中 HAV/ALF 的肝脏过程持续存在，day 2 又激活 Takotsubo 心脏过程；恢复后心脏过程应退出，而不是把整名患者永久改判为另一个无关疾病。
- **因子图**：不是“多列几个指标”，而是显式记录隐藏机制怎样共同生成观察。例如 HAV hepatocyte injury 同时生成 AST/ALT、INR 和 encephalopathy；Takotsubo cardiac dysfunction 生成 EF 下降、troponin 和 shock。这样多个同源观察不会被当作互相独立的票，也能区分哪个机制解释哪个 residual。

当前 V5 有 disease manifolds、latent mechanisms 和 mechanism edges，但 live diagnosis 中这些 edges 主要作为 trajectory gate；它还不是维护联合 posterior、执行消息传递的完整因子图，也没有显式的离散 mode-switch state。

### 没被推翻的部分

这两个真实病例反而说明这些结构**为什么需要**：

- HAV → ALF → day 2 Takotsubo/cardiogenic shock 需要时间性分支激活；
- EF 的先前值和治疗支持需要进入历史摘要；
- troponin、ALT、INR 不能作为彼此独立、无机制来源的“票数”相加；
- 诊断与治疗必须共享同一个不确定状态，而不能治疗端偷读 expected diagnosis。

### 被推翻的部分

如果此前把这段话理解为下列任一强主张，本轮已经推翻：

1. **“当前 V5 已经完整实现它。”** —— 没有。
2. **“只要疾病 manifold 和 axis 足够多，复杂病例自然就会正确。”** —— 不会；184 个 manifolds 和 17,020 个候选仍可系统性失败。
3. **“静态 top-1 随时间变化就等于动态状态模型。”** —— 不等于。
4. **“把 vector fields 相加就自动得到合理共病。”** —— 当前组合几何会放大错误 residual ownership。
5. **“有 treatment vector field 就等于有反事实治疗决策。”** —— 不等于。

因此准确表述是：

> **聊天结论仍是一套合理的目标架构假说；当前 V5 是其中若干部件的 PoC，不是该架构的完成体。**

---

## 是否存在一个“理想模型”

要区分抽象存在与工程可得。

### 在固定范围内，抽象理想状态可以定义

固定：

- 可观察集合；
- 可执行检查/治疗集合；
- 关注结局；
- 时间范围；
- 容许误差。

若两段患者历史对所有允许的未来行动都产生相同的未来结果分布，就把它们归入同一状态。这个等价类按定义是该范围内的“理想充分状态”。

### 但不存在已证明的、唯一且永恒的有限模型

原因是：

1. 这个等价类可能需要无限历史或无限维分布，未必能压成有限坐标；
2. 不同隐藏因果世界可能与所有现有数据相容，个体反事实仍不可识别；
3. 新检查或新治疗会让过去无关的差异变得可行动，旧状态必须继续拆分；
4. 医疗环境、患者目标与可用行动变化时，“相同状态”的定义也变化；
5. 本轮真实病例已经展示：即使抽象结构合理，ontology、alias、atlas coverage、更新算法和治疗约束任何一层出错，整体仍会失败。

所以最佳结论不是“不存在理想”，而是：

> **存在一个相对于任务范围定义的理想标准；不存在一张已经知道、一次建成、永久封闭的全医学有限地图。**

---

## Verification

- Active manifolds：184
- Staged cuts：11
- 数值未来 evidence/action 违规：0
- History-collision probes：8，全部显示旧同轴值被覆盖且聚焦评分不变
- Action-history ablations：9，全部聚焦评分不变
- Day-2 exhaustive candidates：17,020
- Takotsubo active manifold：不存在
- Active `distillations/v5_*.json` 与 `distillations/cases/` 变更：0
- Fail-closed verifier：`PASS`
- `git diff --check`：无 whitespace error

机器可读验证：`verification.json`、`longitudinal_results.json`、`critical_day2_full_pairs.json`。

---

## 下一步

下一步不应立刻给这两个病例补病或调权重。应先修**通用执行内核**，再用原病例盲复跑：

1. 修复中性 axis/alias 的唯一 canonical scoring 语义，禁止同一事实因 source/proxy 选择而被错算 background。
2. 把 cut-by-cut ranking 改成显式 posterior/state 递推；状态必须包含 action history 与同轴轨迹摘要。
3. 增加时间性 mechanism activation/deactivation，而不是只穷举静态 pair。
4. 让 treatment runtime 接收诊断 posterior，并建立通用 eligibility、contraindication、alternative-lane、mutual-exclusion 与 support-context 约束。
5. 修完后重跑这 11 cuts，并加入未参与修复的第三个复杂盲病例。只有通过上述门禁，才能把“目标架构”升级为“已有证据支持的模型”。
