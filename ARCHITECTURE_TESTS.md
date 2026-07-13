# 候选无关的架构压力测试

> 这些测试先于原型实现定义。任何候选都通过同一输入契约运行；候选专属适配或额外规则计入 special-case count。

## 1. 判定规则

- **HARD**：安全或语义不变量。失败不能被准确率、速度或其他测试通过抵消。
- **TRADEOFF**：可接受权衡，但必须显式记录损失、成本和失败方式。
- **PASS**：不变量满足，trace 可核查。
- **EXPLICIT-UNSUPPORTED**：架构在输入边界处明确拒绝；HARD 用例若要求可表达则仍算失败，否则优于静默近似。
- **SILENT-FAIL**：无报错地合并、丢弃、泄漏或错误推断，始终是最坏结果。

公共 contract/runner 会验证每次调用都返回合法的 typed result envelope，但**不是每个
workload 都逐字段重新检查全部 envelope 字段**。每项机器 oracle 只检查与该反例有关的
最小判别面：例如 T12 检查 knowledge cut 与 root 可见性，T35 检查数值求解 trace，
T50 检查 masked 与 absent 的区分。证据根、规则/模型版本、valid-time、known-time、
冲突/未知和 trace 的总体覆盖来自多项 workload 与 contract 单元测试的并集，不能把某一
项 PASS 解读成这些性质已在该项中全部独立验证。

## 2. 共同最小词汇

测试只使用同一组基础概念，避免某候选获得额外医学内容：

- 观察：MAP/血压、SpO2、体温、心率、培养、CRP、WBC、肌酐、症状；
- 干预：去甲肾上腺素、氧疗、退热药、β 阻滞剂、固定频率起搏、抗菌药；
- 潜在机制：灌注不足、低氧机制、炎症活动、病原负荷、肾滤过功能；
- 信息状态：present、absent、not-asked、not-tested、unable-to-assess、insufficient、conflicting、not-applicable、out-of-model；
- 任务：诊断解释、危重程度、治疗安全。

这不是医学知识库，只是具有区分力的架构夹具。

## 3. 核心 30 项测试

| ID | 等级 | 情形 / 被攻击的隐含假设 | 预期不变量 | 失败意味着什么 |
|---|---|---|---|---|
| T01 | HARD | MAP 70，但依赖大剂量升压药；攻击“正常观察=内部正常” | 保留 MAP 观察、给药事件和支持条件；危重投影不得与无升压药 MAP 70 碰撞；不得仅由正常 MAP 推断灌注机制正常 | 状态与观察通道混同 |
| T02 | HARD | SpO2 98%，高流量氧疗；攻击无上下文数值 | 氧疗方法/流量与观察同一时点可追踪；室内空气 98% 与该状态不等价 | 测量条件丢失或治疗遮蔽未表示 |
| T03 | HARD | 使用退热药后体温正常；攻击把治疗后表现当自然状态 | 无发热观察不自动产生“无炎症/无发热机制”结论；退热药可作用于观察表现 | 治疗对 observation channel 的作用缺失 |
| T04 | HARD | β 阻滞剂或固定频率起搏器下无心动过速 | 两种修饰上下文可区分；正常 HR 不自动否定潜在应激 | 个体/设备/治疗修饰被压扁 |
| T05 | HARD | 采样前已使用抗菌药，培养阴性 | 阴性培养仍是原始观察；其敏感性/观察模型被先前抗菌药修饰；不得直接推出无感染 | 观察过程与状态生成混同 |
| T06 | HARD | 同一体温记录生成“高温/发热/高热” | 三个派生断言共享同一原始 evidence root；复制派生词不改变独立证据数或支持质量 | 同源证据重复投票 |
| T07 | HARD | 发热、CRP、WBC 共享炎症来源 | 可表示共同潜在来源或相关依赖；不得默认三项条件独立 | 共享来源导致证据夸大 |
| T08 | HARD | 相同表型可由感染或非感染炎症产生 | 同一观察可支持多个假说；不得强制唯一因果身份 | 单因单果或封闭分类偏差 |
| T09 | HARD | 同一疾病在免疫抑制者与普通患者表现不同 | 个体上下文可局部调制状态→观察关系；疾病 identity 不需复制成两个核心类型 | 无上下文表现模型或 schema 爆炸 |
| T10 | HARD | 两次记录对同一时段的用氧状态互相冲突 | 两条来源都保留，输出 `conflicting` 与各自可靠度；不得 last-write-wins 静默覆盖 | 冲突被伪装成确定事实 |
| T11 | HARD | 病历未提皮疹 | 结果为 not-asked/not-recorded，而不是 absent；不产生阴性 likelihood | 未知自动视为阴性 |
| T12 | HARD | 08:00 采血，12:00 结果可得 | 09:00 `as_known_at` 回放不包含结果；13:00 可包含且 valid-time 指回 08:00 | 未来信息倒流 |
| T13 | HARD | 住院后最终诊断，回放首诊 | 最终诊断及其派生物在首诊 known-time cutoff 后不可见 | 标签/后验泄漏 |
| T14 | HARD | 肌酐 1.8 mg/dL，个人基线分别 0.7 与 1.7 | 原始值相同但基线上下文不同；肾损害读出不得碰撞 | 个体基线丢失 |
| T15 | HARD | 同一患者生成诊断与用药安全视图 | 两个 task projection 可选择不同坐标/规则；投影只读且共同回指事实层 | 假设唯一万能距离或投影污染事实 |
| T16 | HARD | CKD 与肾清除药物产生非线性交互 | 支持门控/饱和/交互规则；若无已知组合律，显式 unresolved，不默认相加 | 共病/药物只会线性叠加 |
| T17 | HARD | 治疗既改变内部状态又改变观察方式 | 两条效应可分别声明、启动/停止、追踪；trace 区分两者 | 干预语义单通道化 |
| T18 | HARD | 症状改善可能自然病程，也可能治疗作用 | 保留多个解释；除非有识别假设/证据，不把时间先后当唯一因果 | 后此谬误、无依据归因 |
| T19 | HARD | 旧 SpO2 已过期 | 当前投影不消费过期值；历史回放仍能看到；过期不是删除 | 当前/历史语义混乱 |
| T20 | HARD | 输入表现不属于任何已知疾病模块 | 输出 out-of-model/insufficient 可合法出现；不得强塞最近候选 | 封闭世界强分类 |
| T21 | HARD | 新增药物及其局部 state/observation effects | 不修改固定核心类型/主分支；只添加版本化模块；既有测试不变 | 核心随词汇增长 |
| T22 | HARD | 新增新测量方法 | 不修改核心；方法作为类型化上下文/模块加入；未知方法先隔离而非伪装旧方法 | 输入扩展破坏核心或静默归一 |
| T23 | HARD | 新医学理论重释旧证据 | 可选择“当时规则”与“新规则”两种回放；原始事实不被改写 | 知识与证据版本混同 |
| T24 | HARD | 删除一条原始体温证据 | 仅依赖它的发热/高热递归失效；有其他独立体温支持的结论保留 | 无真值维护或过度删除 |
| T25 | HARD | 任意历史点重放 | trace 所有输入 `known_from <= cutoff`，结果确定且不受当前缓存污染 | 回放错误/未来泄漏 |
| T26 | HARD | 罕见关键禁忌规则未被语义检索召回 | 适用域内 deterministic invariant 仍执行；检索只可优化候选发现 | 优化层决定安全语义 |
| T27 | HARD | 两个独立温度计各测一次 vs 一次测量三种改写 | 前者有两个 evidence roots，后者只有一个；support 组合不同 | 文本数量替代证据独立性 |
| T28 | HARD | 感染与自身炎症两个候选均未排除 | 两个假说并存，含各自支持/反对/未知；不得强制单标签 | 无法保留多模型 posterior/假说集 |
| T29 | HARD | 输入全新、无法表达的设备状态 | 显式 typed error/quarantine，保留原始载荷；不得丢字段或映射到“其他=正常” | 静默近似与数据损失 |
| T30 | HARD | 同一病例换等价自然语言表达 | 经输入适配后的核心记录语义同构，原文与适配 provenance 仍不同 | 核心被表面措辞控制 |

## 4. 补充判别测试

| ID | 等级 | 情形 / 被攻击的隐含假设 | 预期不变量 | 失败意味着什么 |
|---|---|---|---|---|
| T31 | HARD | 同一推断通过两条规则形成循环；攻击“规则路径本身可生成 support” | 无根循环不得增加 support；有生理反馈则需良定义 fixed point，否则 typed illegal-cycle/unsolved | 推断可自证，证据守恒失效 |
| T32 | HARD | 晚到记录修正过去值；攻击“当前数据库行就是全部历史” | 新 transaction/known-time 版本不篡改旧快照；新重放递归更新下游，同时 control root 仍可见 | 无法重建当时所知，或修正产生过删/漏删 |
| T33 | HARD | 单位不兼容或方法不可比；攻击“数值字段可直接合并” | raw ingest 无损保存；canonical adaptation 只能经版本化转换并带 trace，否则 typed quarantine/refusal | 单位错误被静默正规化，原始数据不可往返 |
| T34 | HARD | 同一证据经两模块 fan-out 再 fan-in；攻击“推导路径数等于独立证据数” | lineage union 幂等，独立 root 数不随路径数增加 | 同源证据通过模块路径重复投票 |
| T35 | HARD(trace) / TRADEOFF(accuracy) | 近似 posterior；攻击“只要给一个数字即可” | `computation` 必须 typed；近似/失败 trace 含 seed 及 error、error-bound、tolerance 或 residual；规定容差内的精度继续作 TRADEOFF | 无法区分收敛、近似、非收敛与数值故障，数字不可审计 |
| T36 | HARD | 删除/停用知识规则；攻击“知识更新等于重写患者事实” | as-then 仍按旧版本复现；reinterpret-now 撤回旧规则派生物；raw evidence 不变 | 知识史与患者史混同，旧结论无法重放 |
| T37 | HARD | 动作有计划、下单、执行、拒绝、停止；攻击“出现动作名就有生理 effect” | 只有 performed 的半开有效区间产生 effect；生命周期合法且有 trace | 计划/拒绝被当成已治疗，或停止后仍持续施效 |
| T38 | HARD | 交互模块端口/单位不匹配；攻击“组合器可忽略不兼容的一侧” | 加载或执行前 typed interface failure；不得丢端口、偷转换或继续运行 | 组合结果看似成功但遗漏机制 |
| T39 | HARD(no silent merge) / TRADEOFF(arbitration) | 两概率模块互不兼容；攻击“平均就是中立” | 无已声明仲裁时保留 model disagreement；仲裁策略必须显式、版本化、可回放 | 模型冲突被无记录平均成虚假共识；选择哪种仲裁本身是 TRADEOFF |
| T40 | HARD | 热缓存含未来结果；攻击“缓存只影响性能” | cache key 覆盖 valid/known cut 与知识版本；warm/cold replay 语义相同且早期 root 不可见 | 优化层造成未来泄漏或版本串用 |
| T41 | HARD | 多患者/就诊/标本有同名 analyte；攻击“concept 名足以确定身份” | subject、encounter、specimen、source scope 全部参与合法连接；错 scope typed fail | 患者或标本串线，属于不可接受的数据完整性错误 |
| T42 | HARD | `<0.01`、超量程、不同 detection limit；攻击“所有测量都是点值” | censoring、检测限、assay/method 与 raw root 保留；不可拍成 0/0.01 或直接等价比较 | 似然和比较建立在伪造点值上 |
| T43 | HARD | 时段无观察机会；攻击“未记录可作为阴性” | 仅声明 ascertainment scope 后才能建缺失模型；无机会保持 unknown/not-observed，另有 control root 证明查询非空 | 系统把工作流缺失当生物学不存在 |
| T44 | HARD | `rash` 与 `not rash` 冲突后查 `fracture`；攻击爆炸逻辑和 last-write-wins | rash 局部 conflicting；无关事实继续可查询；矛盾不得推出任意命题 | 冲突污染全局，或一条记录被静默覆盖 |
| T45 | HARD | 原文/原单位多次规范化；攻击“canonical 值足以审计” | canonical 值可一路回到 raw value、raw unit、source span、mapping version 与 evidence root；旧 mapping 可重放 | 适配层成为不可逆第二事实源 |
| T46 | HARD(scope) / TRADEOFF(utility choice) | 生存、出血、偏好权衡；攻击“预测分数天然定义唯一治疗” | 无显式目标、效用和约束时不得声称唯一最优；prediction 与 policy 分开 | 隐藏价值判断被伪装成医学事实；效用选择本身是 TRADEOFF |
| T47 | HARD(scope) | 推荐后将策略诱导数据在线回灌；攻击“观测仍是自然史 iid 样本” | 暴露政策、模型版本、更新时间可追踪和回滚；旧/新版本真实不同且不回写过去 | performative feedback 未被标记，验证与自然史估计被污染 |
| T48 | HARD | 同一 delivery key 重试、部分实施、后续取消；攻击“消息次数=剂量次数” | 重试幂等；effect 仅覆盖实际执行区间；取消后 root 与 effect 均不继续 | 重试造成重复给药语义，或取消未终止作用 |
| T49 | HARD | 通用知识“药 A 可降温”与事实“已给药 A”混合；攻击“知识节点可直接成为患者事实” | knowledge、patient evidence、model output、task policy 分 scope；只有显式合法 bridge 可生成患者派生物，且 control patient root 存活 | 本体知识越权制造病例事实或形成自证 |
| T50 | HARD | 权限/隐私 masked；攻击“看不到等于没有” | 输出 masked/unauthorized；不泄露原 payload/value，也不映射 absent、negative 或 unknown | 权限边界泄密，或遮蔽信息被错误当临床阴性 |

## 5. 动态、因果与组合判别实验

前 50 项偏重不可妥协的认识论与审计语义；为了不结构性偏袒事件账本/规则候选，另设同等权重的 World/Computation panel。共享的是**语义工作负载**，不强迫候选内部使用事件、DAG 或 TMS。

| ID | 等级 | 夹具 / 被攻击的隐含假设 | 预期不变量 | 失败意味着什么 |
|---|---|---|---|---|
| E01 | HARD(语义、规定容差与 trace) / TRADEOFF(容差内精度、成本) | 潜在灌注损害 `S(t)`，去甲肾上腺素 `U(t)` 同时改 drift 与即时 MAP；攻击“正常观察=正常潜态”及“forecast=counterfactual” | filter 不因支持下 MAP 正常而令 S 归零；停药与继续治疗轨迹不同；forecast 与同历史 `do(U=0)` 有不同语义；近似计算报告误差 | observation/state 再次碰撞，或三种动态查询只是换标签 |
| E02 | HARD | 隐藏严重度令 treated group 观察结局更差但治疗真实有益；攻击“conditioning 就是 intervention” | `P(Y|T=1)` 与 `P(Y|do(T=1))` 按 SCM 可符号反转；结果列出识别假设；无能力时 typed unsupported | 相关性被冒充治疗效应，决策语义根本错误 |
| E03 | HARD | 个体响应 `R` 未直接观察但已有该患者治疗轨迹；攻击“个体反事实=重新抽一个群体样本” | abduction 先用事实世界更新 R，替代世界共享该背景；same-patient AAP 与 population `do(T=0)` 不碰撞 | 丢失个体身份和跨世界一致性，个体反事实是伪命题 |
| E04 | HARD(未来隔离、相位、规定容差与 trace) / TRADEOFF(容差内精度、资源) | logistic 病原负荷、饱和炎症、CRP 滞后、脉冲抗菌药与不规则采样；攻击“同一绝对值足以预测”和“smoothing 可偷看未来” | filtering 只用当时可见资料；相位改变 forecast；允许 pulse 后滞后峰；轨迹坐标完整且近似有 seed/error | 时间相位和滞后被压扁，或未来信息进入过滤 |
| E05 | HARD | 感染/无菌炎症共享发热 CRP，退热药只改表现、抗菌药只改感染机制；攻击“表型改善唯一识别病因” | 退热响应不选择性消灭任一假说；机制特异响应才改变相对支持；不足时两假说并存 | treatment response 被当万能标签，机制选择性丢失 |
| E06 | HARD(组合/接口/规定容差) / TRADEOFF(容差内数值成本) | 感染 A、清除 B、药物 C 与显式 interaction I；攻击“模块天然可相加、同名端口天然兼容” | 缺 I 时显式 assumption/unsupported；有 I 时体现非线性交互；替换兼容 B 不改 A/C/core；错接口 build-time fail | 组合器静默相加或丢模块，扩展局部性是假的 |
| E07 | HARD | 同一 wiring 改括号、注册顺序和独立更新顺序；攻击“执行器偶然顺序就是语义” | 仅对 manifest 声明的结合/交换部分要求等价；不成立的律必须显式写入契约；所有 A/B/C 都被消费 | 文件加载/hash/agenda 顺序暗中决定临床输出 |
| E08 | HARD | 收缩生理反馈、无根 support cycle、无解和多解方程并列；攻击“所有环都拒绝”或“所有环都放行” | 收缩映射收敛唯一解；无根认识论环零 support；无解/多解分别 typed `no_solution`/`multiple_solutions` | 生理反馈被误杀，或推断自证，或求解失败被伪装成确定答案 |

每项分别报告 semantic correctness、quantitative fidelity、identifiability honesty、order robustness、trace/audit 和 extension cost，不压成总分。集合/符号候选可用安全包含通过关系 oracle，但不得因此声称概率校准；概率候选也不能用较低 RMSE 抵消 HARD 语义失败。

## 6. 两条赛道与公平计数

- **Track A — native**：只计候选固定签名、执行语义与最小序列化；暴露其天然能力。
- **Track B — deployable companion**：允许通用时间、provenance、验证器或求解器伴随层；所有伴随层进入 primitive profile、LOC、特殊补丁和 blast radius。
- **Ablation**：逐层关闭伴随能力，证明每项通过来自哪里。

共享 `CapabilityResult` 信息，而非固定内部 trace 形状：status、value/范围/分布、假设、coverage、时间截断、evidence witness、native witness、diagnostics、版本。若候选原生证明不是 DAG，可提交 proof term、factor subgraph、event slice、rewrite trace、reachability witness 或程序地址；统一 audit envelope 不能偷偷替它完成语义。

核心原语用向量报告，而非裸整数：对象/值构造、更新、时间、belief/不确定、组合、读出、内建 invariant、foreign escape hatch。`Rule(fn)`、`Factor(fn)`、`Component(fn)` 或 `Node(payload)` 的宿主语言自由度必须展开，不能算一个“万能原语”。

special case 按语义补丁计，不按代码行：病例/测试 ID、无依据 concept branch、阈值/bonus、adapter 偷补语义、窄执行顺序修复分别登记。共享医学承诺在各候选中的等价编码不算只惩罚规则候选的“特例”。

## 7. 扩展爆炸半径实验

对每个候选依次加入相同的三个**预注册语义类**扩展包：

1. `new_disease_module`：含两个机制、三个观察关系和一个非线性交互；
2. `new_drug_module`：分别修改潜在状态转移与观察通道；
3. `new_test_method`：同一 analyte 的新方法、单位转换与可靠度模型。

交付实现另加入一个 `new_task_projection` 扩展包，专门验证只读任务视图的局部注册；
它不替代上述 `new_test_method`，因此最终 checked-in 示例共四个。

记录 blast-radius 向量，而不是把文件数当主指标：

- core signature / semantics unit changes；
- adapter unit changes；既有知识模块受影响比例；
- persistent migration、generated artifact/schema、模型重训、历史重处理、cache/index rebuild 比例；
- 既有测试修改数与失败数；
- wall time / peak memory；
- 不支持时是显式拒绝还是静默忽略。

## 8. trace 最小契约

每个派生输出至少包含：

```json
{
  "output_id": "...",
  "semantic_role": "inference|hypothesis|projection",
  "value": "...",
  "valid_time": ["start", "end"],
  "known_time": ["from", "to"],
  "source_roots": ["raw-evidence-id"],
  "justifications": [
    {"rule_or_model_id": "...", "version": "...", "inputs": ["..."]}
  ],
  "information_state": "present|absent|unknown|conflicting|out_of_model",
  "approximations": [],
  "unresolved": []
}
```

字段名可由候选适配，但信息不得缺失。`source_roots` 按原始证据身份去重，不按推导路径或文本节点计数。

## 9. 公平性规则

- 所有候选使用相同输入事件、概念和医学关系。
- 共同适配器只负责格式转换；若适配器补了候选缺失语义，计入该候选原语/特例。
- 不以候选抛出异常本身算通过；只有契约允许显式 unsupported 的边界情形才可接受。
- 测试冻结后，新增用例可补盲点，但不得删除失败用例。
- 运行结果必须区分家族理论上可支持但本原型未实现，和家族基本原语导致的不自然/硬失败。

## 10. Fixture 版本史、冻结方式与隔离运行

这里的 **fixture v1/v2 是研究测试集修订标签**，不等于 JSON 里的 wire
`protocol_version`。当前 transport 仍为 `archbench/1.0`；改变测试 oracle 的判别力时
不能假装成“同一结果口径”。

| 修订 | 定位 | 可用于什么 | 不可用于什么 |
|---|---|---|---|
| fixture v1 / panel-v1 | 红队前的 58 项初始冻结集；首次把 `candidate_view` 与 `oracle_view` 分树 | 保存搜索路径和暴露 runner 缺陷的诊断基线 | 不能作为最终候选排名；存在 oracle 同进程可见、空/稀疏输出可真空通过、部分 fixture 未真正施加所述扰动等问题 |
| red-team fixture v2 | 修复 runner 语义资格、正向 liveness、轨迹覆盖、external clean rebuild 和下列 fixture；候选在 `python -I -S` fresh subprocess 中只接收 `candidate_view` | 当前可复查的判别测试与后续 panel 的输入口径 | 仍不是临床有效性验证，也不能由总 PASS 数证明单一架构最优 |

冻结 JSON 在 [`tests/workloads/T/`](tests/workloads/T/) 与
[`tests/workloads/E/`](tests/workloads/E/)；deterministic builder 在
[`prototype/workloads.py`](prototype/workloads.py)。二者必须结构相等，而不是只比较文件
数量或 hash。直接复核：

```powershell
python -m pytest tests/test_benchmark_contract.py::WorkloadContractTests::test_checked_in_workloads_equal_deterministic_builders -q
python -m pytest tests/test_workload_semantics.py -q
```

候选隔离运行示例（输出文件必须不存在；runner 拒绝覆盖）：

```powershell
python -m prototype.isolated_benchmark --candidate tel --track native --workload T12 --output results/manual-tel-native-T12.json
python -m prototype.isolated_benchmark --candidate model --track native --panel E --output results/manual-model-native-E.json
```

隔离测试确认 fresh `python -I -S` 工作目录不含 judge/oracle 文件，stdin transcript 只有
public candidate view digest；对应机械检查在
[`tests/test_isolated_benchmark.py`](tests/test_isolated_benchmark.py)。

### v1 → red-team v2 判别力勘误（2026-07-13）

冻结 JSON 与 builder 同步做了以下修正；这些是测试语义修复，不是候选特例：

- T18 只接受 `not_identified` 或带 typed reason 的 `insufficient`，不再把 `identified` 当成“诚实标注”即可通过。
- T20 改用开放 coverage registry 上的 `project` 查询，不再以 `check_invariant` 误测 OOD。
- T23/T36/T47 各提供两个真实的版本化 public module，并检查具体版本输出；不再只比较 query 中两个版本字符串的回显。
- T29/T33 分开测试 raw ingest/round-trip 与 canonical adaptation：账本可先无损接收未知设备/单位，而 canonical 化必须成功或 typed quarantine/refusal。
- T35 的 solver trace 是 HARD：`computation` 枚举、seed、error/error-bound/tolerance/residual 缺一不可；精度容差仍是 TRADEOFF。
- T39 实际注册两个冲突概率模块；fixture 未给仲裁策略，因此要求保留 disagreement，禁止静默平均。
- T45 检查 raw value、raw unit、source span、mapping version 与 evidence root 的同一链路，而不只检查 root 名称。
- T48 同一个 delivery/idempotency key 重试两次，并在晚于执行的有效时间写入 cancellation；分别检查执行期单一 effect root 与取消后零 effect root。
- 纯 negative/equivalence 用例 T03/T05/T24/T26/T30/T31/T32/T40/T49 增加正向 liveness/control，空结果或恒定结果不再可真空通过。
