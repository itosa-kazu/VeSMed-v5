# 盲 holdout 真实病例选择

## Outcome

**入选病例：**

> **A rare pheochromocytoma complicated by cardiogenic shock and posterior reversible encephalopathy syndrome: case report**

- PubMed Central: [PMC7873792](https://pmc.ncbi.nlm.nih.gov/articles/PMC7873792/)
- PubMed: [PMID 33598609](https://pubmed.ncbi.nlm.nih.gov/33598609/)
- DOI: [10.1093/ehjcr/ytaa513](https://doi.org/10.1093/ehjcr/ytaa513)
- 期刊：*European Heart Journal - Case Reports*（2021）
- 全文状态：开放全文；PMC 页面标注 CC BY-NC 4.0

这是本轮候选中最适合作为新架构**盲 holdout**的病例。它有作者提供的、从入院前线索一直延伸到住院第 30 天结局的明确时间表，同时包含多个器官域、多个相继出现的病理过程、可核对的延迟检查，以及多种支持装置和药物的开始、撤除与 definitive intervention。不同器官的恢复时间并不同步，正好可以区分“一个全身 mode”和“organ-local modes”。

本文件只完成**病例发现和选择**，不提供最终事件流、病例 JSON、切片答案或预期 ranking。搜索期间未读取模型实现，也未读取 holdout 评价协议。

## Key Evidence：为什么它最适合

### 1. 能检验并发 active-process，而不是单病分类

公开病例叙述包含一个持续存在的上游驱动过程，以及心血管、呼吸、肾脏和神经系统中并发或相继出现的临床过程。它们不能合理地压缩为一个互斥诊断标签；在住院过程中，某些过程已开始恢复，另一些仍需支持或尚待确证。

### 2. 能检验 organ-local modes

原文同时提供：

- 循环和心功能的客观恶化及恢复证据；
- 呼吸支持状态及撤机证据；
- 肾脏支持的持续与停止；
- 神经系统新事件、影像确认及最终查体结局。

这些域的变化不同步，足以检验模型能否同时表达例如“心脏已恢复、肾脏仍依赖支持、神经过程仍在确认”这类局部 mode 组合，而不是给全身贴一个统一的 `decompensated` 或 `recovering` 标签。

### 3. 能检验 action lifecycle

全文明确记录了多种动作类别：气道/通气、两种机械循环支持、肾脏替代治疗、抗心律失常与血压控制药物、镇静方案以及最终手术。多项动作有明确的启动、持续、减量/停用或移除节点，因此可以检验：

```text
start -> continue/change -> stop/remove -> residual/recovery
```

而不只是“某治疗曾经使用过”的静态布尔值。

### 4. 能检验延迟检查与 posterior update

病因性检查和神经影像并非在首次观察时同时可得；原文还明确说明，一种常用确认路径因正在进行的器官支持而不可行，团队改用另一种检测。这提供了真实的：

```text
早期不完整证据 -> 新器官事件 -> 延迟检查 -> 改变解释 -> definitive intervention
```

但本文件刻意不把这些内容拆成模型可直接消费的顺序切片。

### 5. 能检验 OOD / 未建模残差

病例核心上游过程罕见，早期表现又会落入多个更常见的心血管和休克类候选。若 atlas 缺少该过程，合理行为应是保留明显的未解释质量，而不是把全部证据强行压进一个常见心脏分支。即使 atlas 已含该过程，神经、肾脏和器械支持相关的新信息仍可检验 unexplained residual 是否随时间变化。

### 6. 时间证据完整度高

原文有作者制作的逐日 timeline，并在正文中补充了：

- 入院时生命体征、血气/乳酸、心功能与影像；
- 新出现的实验室及神经观察；
- 检查何时获得以及为何延迟/替代；
- 机械支持分别何时移除；
- 肾脏、呼吸、神经和心功能的恢复/结局证据。

这使 staged replay 可以依赖已发表时间戳，而不是由研究者凭空猜测顺序。

## 候选核对

评分为病例发现阶段的相对适用度（0–5），不代表模型成绩。

| 候选 | 时间证据 | 多过程/多器官 | 动作生命周期 | 延迟检查/更新 | OOD 压力 | 选择结论 |
|---|---:|---:|---:|---:|---:|---|
| **[PMC7873792](https://pmc.ncbi.nlm.nih.gov/articles/PMC7873792/)** — *A rare pheochromocytoma complicated by cardiogenic shock and posterior reversible encephalopathy syndrome: case report* | 5 | 5 | 5 | 5 | 5 | **入选**；作者有明确逐日表，器官恢复不同步，检测受当时治疗状态限制，动作 start/stop 最完整 |
| [PMC7183660](https://pmc.ncbi.nlm.nih.gov/articles/PMC7183660/) — *Leptospirosis as an important differential of pulmonary haemorrhage on the intensive care unit: a case managed with VV-ECMO* | 4 | 5 | 5 | 5 | 5 | 强备选；感染、肺出血/呼吸衰竭、肾损伤、气压伤、抗凝与再次出血都很丰富，但“入院日”和“ECMO 中心日”的两套计时需人工对齐，盲回放更容易产生时间歧义 |
| [PMC6424242](https://pmc.ncbi.nlm.nih.gov/articles/PMC6424242/) — *Plasmapheresis and corticosteroids in infective endocarditis-related crescentic glomerulonephritis* | 5 | 4 | 4 | 5 | 4 | 强诊断更新备选；门诊、首次住院、出院、再入院、活检、透析、免疫治疗、血浆置换及手术顺序清楚，但局部 mode 主要集中在感染/心脏/肾脏，器官跨度略小 |
| [PMC7793176](https://pmc.ncbi.nlm.nih.gov/articles/PMC7793176/) — *A challenging case report of acute sinus of Valsalva aneurysm rupture in cardiogenic shock and multi-organ failure with an emphasis on rapid recognition and ‘never giving up’ in face of futility* | 5 | 5 | 5 | 3 | 4 | 救治过程极丰富且持续 62 天，但核心结构性病因在早期已被识别；更适合测治疗/恢复，不如入选病例适合测延迟病因更新 |

## Verification

1. 四篇候选均核对到 PMC 开放全文，而不是只看二手摘要。
2. 入选文献的 PubMed 元数据确认其为 2021 年病例报告，PMID、PMCID 与 DOI 相互一致。
3. 在当前 `vesmed` 工作区按四个 PMCID 和完整/关键标题做精确全文检索，均为 **0 命中**；未发现这些病例此前被本项目使用。
4. 未生成任何 staged observation、答案标签或 diagnosis target，保持后续结构化与模型执行之间的隔离。

## 已知局限

1. **题名严重泄露终点。** 后续给模型的输入不得包含题名、PMCID、DOI、摘要、关键词或期刊链接；这些只留在 source-control 层。
2. **这是回顾性单病例叙述，不是原始 EHR。** 若原文未给出某项连续剂量、每日化验或精确停止时刻，不能补猜。
3. **早期已是极重症。** 它很适合测试多过程、支持依赖和异步恢复，但对“轻症逐步恶化”的覆盖较弱。
4. **镇静、通气及机械支持会遮蔽自然生理状态。** 结构化时必须把测得值与支持强度共同保留，不能把支持下正常值解释为自然稳定。
5. **神经影像措辞存在作者解释层。** 直接观察、影像描述和作者诊断必须分层，不应把诊断标签当普通观察轴。
6. **病例报告无法证明治疗因果。** 动作后的改善只能作为时间顺序与状态转移证据，不能直接标注为该动作的确定疗效。

## Next Step（留给独立 case builder）

由一个未参与模型实现的独立人员从全文建立去标识化、按信息实际可得时间排序的 observation slices；source-control 文件保留题名和答案，model-facing 文件只保留当时可见事实。最终答案、病理/术后确认和远期结局必须在对应时点才释放，且不得把作者的诊断性措辞改写为 observation axis。

