# Blind TMA Differential Model Card

**Model:** `blind-tma-differential-v0`  
**Artifact:** `tma_generic_model.json`  
**Status:** `EXPERIMENTAL_UNCALIBRATED`  
**Purpose:** 新临床动态地图的独立、可审计盲模型包；不是 VeSMed V5 资产。

## 1. 盲边界

本模型只使用以下输入：

1. 候选活动过程名称；
2. 背景名称 APS；
3. 一般医学知识与新框架的抽象运行合同。

建模时没有读取、搜索或推断任何目标病例的文章、病例文件、结构化事件、具体数值、
时间线、已实施动作、预期诊断或结局；也没有读取 VeSMed V5 的 distillation、病例、
trajectory、ranking 或输出。模型中的拓扑、共享 latent、宽序数 likelihood 和动作边
均在目标病例回放前建立。

这条边界意味着：本包可以作为**病例外预注册模型假设**，但不能被描述为来源于病例
或已经被病例验证。若在目标病例回放后修改任何拓扑、参数或动作边，必须生成新版本，
不得继续称为原盲模型。

## 2. 表示范围

候选活动过程为：

| 日本語病名 | English disease/process name | model branch id |
|---|---|---|
| 補体介在性血栓性微小血管症 | Complement-mediated thrombotic microangiopathy | `B_COMPLEMENT_TMA` |
| 血栓性血小板減少性紫斑病 | Thrombotic thrombocytopenic purpura | `B_TTP` |
| 抗糸球体基底膜病 | Anti-GBM disease | `B_ANTI_GBM` |
| 医原性生検後出血 | Iatrogenic biopsy bleeding | `B_BIOPSY_BLEEDING` |
| ヘパリン起因性血小板減少症 | Heparin-induced thrombocytopenia | `B_HIT` |

背景 **抗リン脂質抗体症候群 / antiphospholipid syndrome / `theta_aps_activity`**
是慢变 modifier，不是必须与活动过程竞争的单一诊断 branch。`B_UNKNOWN` 保留给未表示
过程、交互、测量失败或模型错配。

本包明确允许多个活动过程并存。它不强制把 TMA、出血、HIT 或其他过程归一化成唯一
标签；procedure/drug exposure 也不能单独证明并发症。

## 3. 核心结构假设

### 3.1 拓扑与局部坐标

- `B_COMPLEMENT_TMA` 与 `B_TTP` 共享 non-rankable 的
  `B_MICROANGIOPATHIC_PROCESS` 父节点，因此共用内皮损伤、微血管血小板消耗、
  微血管病性红细胞破坏和器官缺血 latent。
- 其他分支从生理 reference 通过各自的机制或事件 gate 激活。
- 每个分支只在自己的 local chart 内使用连续距离；跨分支比较必须沿共享父节点和合法
  bridge 计算，禁止把不兼容坐标平铺后做欧氏距离。
- APS 只调制血栓和可能的补体 permissiveness；同一事实不能再作为独立 APS 票重复加入。

### 3.2 四种运行模式

所有活动分支支持：

- `compensated`：机制可活动，但 reserve/support 掩盖部分表面输出；
- `strained`：reserve 被消耗或支持需求增加；
- `decompensated`：器官后果加速，允许事件跳变；
- `recovering`：机制或事件源下降，但残余损伤/动作记忆可持续。

进入和退出模式使用不同 guard，并依赖恢复动量和 action memory。相同局部坐标在不同
mode 可以有不同甚至相反 drift；mode 不是普通严重度标签。

### 3.3 共享 latent 与防双计数

模型不把 Hb、LDH、haptoglobin、indirect bilirubin、schistocytes 和 reticulocyte
当作六张独立选票。它们由 `L_MICROANGIOPATHIC_RBC_DESTRUCTION` 等共同 latent
生成，并通过 `F_HEMOLYSIS_PANEL_JOINT` 一次性计入联合 likelihood。

同样的约束用于：

- creatinine/eGFR/urine output 的 renal joint block；
- PF4 immunoassay 与 functional assay 的 correlated assay block；
- pulmonary capillary bleed 的症状、氧合和影像；
- platelet count 的 TMA/TTP/HIT 多父机制；
- Hb 的 hemolysis、blood loss、production、dilution 和 red-cell support 多父机制。

若两个 block 共享观察，只能通过 declared shared marginal 或 junction separator 连接，
不得再次乘入该观察。缺失、未做、尚未可得、无法评价和阴性必须保持不同状态。

## 4. 观测似然

所有数值均为 normalized ordinal pseudo-likelihood，不是临床频率：

- hidden activity：`inactive_or_low / intermediate / high`；
- positive observation：`none_or_reference / mild / marked / extreme`；
- assay：`negative_or_unsupported / indeterminate / positive_or_supportive`；
- inverse markers 仅反转观测顺序，不引入病例阈值。

默认 kernel 保持高熵，并带 contaminated uniform component、宽 residual-correlation
范围和 likelihood temperature sensitivity range。其目的仅是测试：

1. 结构是否可以递推；
2. 共享 latent 是否减少伪独立造成的过度自信；
3. unknown branch 是否能吸收系统性错配；
4. mode/action memory 是否改变未来分布。

它们没有经过人群校准，不应解释为 posterior probability 的真实校准证据。任何
threshold、temperature 或 contamination 参数必须在目标病例结果出现前冻结。

同样，本包没有临床 prevalence prior。结构测试默认使用对 known candidate subsets 的
exchangeable sparse prior，并在预注册范围内改变 unknown initial mass；若排序或 rollout
随 prior ensemble 实质改变，必须标为 `PRIOR_SENSITIVE`，不能报告成稳定结论。

## 5. 动作条件动力学边界

`actions.catalog` 表示 simulator action class，不构成临床治疗建议、适应证、禁忌证、
剂量或时机说明。只有 `PerformedTreatment/PerformedProcedure` 能注入生理效应；
planned/considered/ordered-only 事件的生理效应严格为零。

模型区分：

- `A_NO_NEW_ACTION`；
- `A_CONTINUE_EXISTING_SUPPORT`；
- `A_STOP_EXISTING_SUPPORT`。

在已有残余暴露或持续支持时，三者不能合并。red-cell、platelet、renal、respiratory
support 会改变观测生成或 reserve expression，但不自动关闭上游机制。抗凝样 action
对 thrombotic 与 bleeding 分支可能有相反模型效应；该冲突只用于 state-collision 和
范围充分性实验，不能转化为患者级行动结论。

所有 mechanism-directed action edge 默认标为
`UNIDENTIFIED_PATIENT_LEVEL_EFFECT`。如果 action response 受多靶点、并行动作、
自然漂移或支持掩盖影响，response 不能被反演成确定的 branch identity。

## 6. 未识别因果边

下列内容在配置中被显式登记，不能悄悄升级为因果事实：

| 假设边 | 状态 | 主要原因 |
|---|---|---|
| APS activity → thrombin generation | `UNIDENTIFIED_CAUSAL_EDGE` | 背景关联不能识别个体贡献 |
| APS activity → complement amplification | `UNIDENTIFIED_CAUSAL_EDGE` | 交互强度和个体适用性未知 |
| mechanism-directed action → patient outcome | `UNIDENTIFIED_PATIENT_LEVEL_EFFECT` | 没有已识别的个体未实施反事实 |
| post-action response → branch identity | `CONFOUNDED_PROBE_EDGE` | 多动作、自然漂移、多靶点和支持掩盖 |
| Hb fall → hemolysis or bleeding | `NON_IDENTIFIED_WITHOUT_SHARED_PANEL_AND_TIMING` | 单一观察有多个 latent parent |
| platelet fall → TMA/TTP/HIT identity | `NON_IDENTIFIED_WITHOUT_MECHANISM_OR_CONTEXT_EVIDENCE` | 分支共享 observation |
| renal dysfunction → active renal mechanism | `NON_IDENTIFIED_WITHOUT_JOINT_EVIDENCE` | 受多种损伤与 baseline reserve 共同影响 |
| biopsy/heparin exposure → complication | `EXPOSURE_GATE_ONLY` | 暴露是 context gate，不是疾病身份 |

病例一致的后续轨迹最多支持 `CASE-CONSISTENT`；不能把它升级为总体临床有效、参数
校准或真实因果证明。

## 7. Unknown branch

`B_UNKNOWN` 使用 heavy-tailed contaminated ordinal mixture，为未表示的 hematologic、
renal、pulmonary、bleeding 和 thrombotic 过程保留质量。它不是一个临床诊断，也不能
因某个已知 branch 是“最不差”而被强制归零。

当 known branches 需要严重冲突才能解释联合观察时，运行时应：

1. 保留或增加 unknown mass；
2. 输出冲突 factor IDs；
3. 根据 readout 返回 `ABSTAIN_UNREPRESENTED_PROCESS` 或带 unknown residual 的已知
   branch posterior；
4. 不使用从目标病例倒推的固定 likelihood cutoff。

## 8. 局限

1. **未校准。** 所有 likelihood、drift、noise、bridge cost 和 mode transition 都是结构
   假设或灵敏度范围。
2. **不完整。** 小候选集不能覆盖感染、药物毒性、DIC、骨髓过程、其他 TMA、其他肾炎、
   其他出血或血栓原因。
3. **因果未识别。** 因子取医学名字不等于证明因果身份；同一病例的先后顺序也不能识别
   未实施动作的反事实。
4. **背景压缩粗糙。** APS、器官 reserve、测量 context 只是慢变摘要，可能不足以覆盖实际
   人群异质性。
5. **局部 chart 是工程抽象。** normalized `[0,1]` 坐标不能解释为实验室单位或临床阈值。
6. **动作 catalog 不完备。** 未表示的治疗、剂量、药代、毒性和组合交互必须进入 unknown
   或 scope-insufficient，而不是静默外推。
7. **相关结构可能仍不足。** 联合 block 只能减少已知重复计票，不能保证所有 residual
   dependence 均被正确表示。
8. **分支共存的组合爆炸尚未解决。** 配置允许任意候选子集并存，但只给少量结构示例；
   高阶交互参数尚未建立，更复杂交互需要新 scope 和版本化扩展。
9. **不证明最小或充分。** 只有 collision search、twin histories、mode/action-memory
   ablation 和外部盲病例才能逐步证伪或缩小声明范围。

## 9. 预注册验证要求

目标病例进入前至少冻结：model digest、scope digest、branch topology、factor schedule、
ordinal kernels、mode/action edges、unknown behavior 和所有评价阈值。运行时必须记录：

- 同一 shared-state hash 被 diagnosis、no-new-action forecast 和 action rollout 消费；
- parent hash 与 consumed event digests；
- branch/concurrent-set 与 mode posterior；
- branch-local coordinate distribution；
- factor-block likelihood 与 shared-marginal deduplication log；
- action-memory distribution；
- unknown mass；
- unidentified-edge warning 与 sensitivity-range ID。

必须执行的消融包括：删除共享 latent、删除 mode、删除 action memory、强制单 branch、删除
unknown branch，以及把 topology distance 替换为 flat Euclidean。若删除结构后结果不变，
该结构可能只是重命名；若完整模型出现危险状态碰撞，应缩小 scope 或局部细化，不能用
病例 ID 或后验补丁记答案。

## 10. 允许的结论等级

- `STRUCTURALLY_SUPPORTED`：配置与运行合同满足预注册结构测试；
- `CASE-CONSISTENT`：冻结模型与某条公开病例轨迹不冲突；
- `FAILED`：出现 future leak、重复计票、非法动作、危险碰撞或其他硬失败；
- `UNIDENTIFIABLE`：现有观察和动作历史无法支持方向性或患者级因果结论。

本模型卡不允许输出“已证明某治疗有效”“已校准诊断概率”或“已识别个体真实反事实”。
