# 研究日志

## 2026-07-13 — 启动与去锚定

1. 读取任务与仓库级约束。
2. 明确旧 VeSMed V5/SDE 只作为历史候选和失败证据，不作为默认答案。
3. 建立硬约束优先、Pareto 次之、辅助评分最后的评价顺序。
4. 创建 `PLAN.md`、`FIRST_PRINCIPLES.md`、`REQUIREMENTS.md` 初稿。
5. 并行启动第一原理红队与跨领域候选调查。
6. 根据既有仓库审计，记录旧 runtime 存在静态 Gaussian 近似、候选间 logP 不完全可比、benchmark 泄漏、registry 漂移和 treatment API mismatch；这些只能作为旧候选的待复核风险，不能直接替代本研究实验。

### 路线决定

- 在第一轮候选地图和统一测试协议完成前不写候选原型。
- 先保留 Requirement ID 稳定；后续只增补或明确修订，不静默改义。
- 来源表将逐条记录“原文支持的有限命题”，避免用权威名称替代论证。

## 2026-07-13 — Checkpoint 1 红队与要求修订

1. 对用户给出的 15 项要求逐条找反例，不把原清单直接当结论。
2. 新增主体/就诊/标本/设备作用域，避免同名概念跨患者或跨标本串线。
3. 将时间扩为 occurrence/effective、collected、available/known、recorded/transaction、expiry，并允许显式偏序；一个时间戳不能替代这些角色。
4. 将信息状态、数值概率、模型覆盖、可识别性与求解器状态拆为正交字段。
5. 将 provenance 与统计独立性拆开；来源可追踪不证明两条证据独立。
6. 增加动作完整生命周期、患者目标/效用、安全 invariant、在线学习反馈、检测限、观察机会和原值可逆保留。
7. 将“最小性”从 HARD 改为 SOFT/Pareto：否则 `Node(payload)` 会用一个表面原语隐藏全部复杂度。

### 检查点结论

- 不选候选；冻结 Requirement ID 与硬失败定义。
- 架构测试必须同时有审计面板和动态/因果/组合面板。
- 通过核心测试不等于医学有效、概率校准或可部署；这些边界单列。

## 2026-07-13 — Checkpoint 2 候选调查与去重

1. 并行调查状态/因子/控制、SCM/PPL、Event Calculus/TEL、Petri/反应/进程、类型/重写/Datalog、operad/open systems/sheaf、图/超图、world model/digital twin/Transformer。
2. 采用“状态对象 + 演化算子 + 查询语义”去重：factor graph 是推断 IR，普通 PPL 是建模语言，类型系统是安全元层，ECS/黑板是运行组织方式，不能单独算动态核心。
3. 将 Petri 与反应网络视为同一多重集/stoichiometric 骨架的不同执行语义；将 operad/wiring/cospan 视为一个组合外壳；SCM 与 DBN 保持分开，因为前者的边可被 `do()` 替换。
4. 测试公平性红队指出 T01–T50 结构性偏爱事件账本；补 E01–E08，覆盖 treatment masking、see/do 符号反转、同一患者反事实、不规则非线性动力学、选择性干预、三模块交互、组合律和反馈良定性。
5. 预注册 Native 与 Companion 两赛道、ablation、semantic special-case ledger 和 blast-radius vector；禁止用统一 audit wrapper 替候选制造原本没有的语义。

### 当前路线

- 文献阶段保留多个 Pareto 子内核，不把“万能图”或“全部拼接”称为统一答案。
- 下一步先冻结候选无关 API 和机器工作负载，再从 Pareto 子内核选至少三个原型。

## 2026-07-13 — Checkpoint 3 形式化与不可统一边界

1. 独立形式红队否决“统一 `PatientState/update/compose`”方案：TEL 的知识投影、causal/state 的 posterior/trajectory、rewrite/open 的 configuration/residual behavior 不是同一种状态。
2. 冻结候选无关 `K0`：类型化 artifact/scope、时间/版本 cut、grounded proof、封闭 query sum type、正交 Outcome、capability 与 invariant enforcement。
3. 证据代数只把同一 root 的复制路径做幂等 union；不把 provenance 冒充统计独立或 probability。
4. 历史查询拆为 as-then、用当前理论重释旧 evidence prefix、允许后来证据的 retrospective smoothing 三类。
5. query 拆为 evidence view、filter、smooth、forecast、condition、intervene、same-patient counterfactual、task projection、policy evaluation、reachability 与 invariant check。
6. 禁止通过模块边界注入 callback、SQL、prompt、bytecode 或自由 `Any`；冻结 IR opcode、解释器、solver 和依赖，能力归因给最深语义提供者。
7. 输出改为正交结果乘积；`conflict + out_of_model + not_identified + solver_ok` 可同时成立，单一 `status=ok` 不能洗掉它们。

### 检查点结论

- 进入实现的是三个并列 profile：TEL、dynamic causal/state、typed rewrite/open；共同 API 只负责资格、版本、审计和失败，不替候选实现其缺失语义。
- 原型必须接受 alpha-renaming、乱序、future append、clean rebuild、companion ablation 与 hidden holdout 攻击。

## 2026-07-13 — Checkpoint 4 fixture 冻结与判别力修订

1. 将用户要求与派生反例编译为 T01–T50，并另建 E01–E08，避免只用 ledger-friendly 的审计题评价 dynamics/causal/composition。
2. 每个 workload 同时保存可交给候选的 `candidate_view` 与只留在父进程 judge 的 `oracle_view`；候选 manifest 只定义可询问边界，不可自报 PASS。
3. 红队发现原 fixture 允许“返回正确 payload 但状态不合格”、稀疏 trajectory、万能拒绝和无正向 control。修订后加入 semantic eligibility、完整坐标/重复坐标检查、liveness、typed boundary reason、外部 clean rebuild。
4. T35 最终使用封闭 `linear_recurrence` oracle，强制 24 小时 horizon 的 25 个坐标、coverage 与 RMSE；稀疏轨迹和固定垃圾均失败。
5. 58 个 JSON 与 workload builder 做逐项一致性检查；`HONEST_UNSUPPORTED` 与 behavior PASS 分开计账。

### 路线决定

- PASS 总数不是跨候选总分，因为原生适用域和 `not_applicable` 不同。
- Fixture 已公开，因此最终结论仍需隐藏参数/同构词汇/模块顺序 holdout；当前面板只能作为可复查的公开证据。

## 2026-07-13 — Checkpoint 5 三个原子原型与两个判别仪器

1. 实现 `prototype/candidates/temporal_ledger.py`：多时钟 knowledge cut、root provenance、versioned replay、撤回/重算和只读 projection。
2. 实现 `prototype/candidates/causal_state.py`：finite DBN filter/forecast 与 finite SCM 的 conditioning、population `do`、同患者 shared-exogenous AAP；不假装提供 ledger 语义。
3. 实现 `prototype/candidates/rewrite_open.py`：typed configuration、封闭规则、动作 typestate、冲突、reachability 与 open-machine composition；不把 rule order 当医学知识。
4. 实现 `prototype/kernel.py` 作为 K0/联邦路由与显式 evidence→model bridge；实现 `prototype/model_subkernel.py` 作为 E01–E08 公共模型判别仪器。后两者不是额外候选家族，结果不能反记给某个原子原型。
5. 实现统一 demo：同一 raw fact 的 evidence/rewrite/causal 三坐标、diagnosis/medication-safety 两个只读投影、迟到证据 cut、局部扩展与 typed refusal。

### 原型化后的反证

- TEL 的 replay/withdrawal 不能推出 latent trajectory 或 `do`；
- causal/state 的 posterior/AAP 不能替代权威 occurrence/root 历史；
- rewrite/open 的 configuration/residual behavior 不能替代概率 belief；
- K0 只能守住资格、路由、witness 与失败，不能从接口凭空补齐任何缺失语义。

## 2026-07-13 — Checkpoint 6 红队：v1 → v2 → v3

### v1：保留但降级为无效诊断基线

- 路径：`results/20260713T200000Z-panel-v1/`。
- 发现：候选与 oracle 同进程/同文件系统；unsupported eligibility、trajectory 覆盖、rebuild 和部分 negative oracle 可被投机；候选还能从共享模块或运行状态获得不应看到的信息。
- 决定：结果只用于说明为什么要重修 harness，不能用于候选选择。

### v2：进程隔离过渡版

- 路径：`results/20260713T115159Z-panel-v2/`。
- 修订：每 workload fresh `python -I -S`，stdin 只交付 `candidate_view`，oracle/reference 留在父进程；同步 eligibility、外部 fresh replay、PASS gating 与分轴裁决。
- 剩余缺口：pure-Python 候选仍可探测更广文件系统或启动外部路径；因此 v2 仍只作过渡诊断。

### v3：panel 谱系的 decision-grade 证据版

- 路径：`results/20260713T120910Z-panel-v3/`。
- 新增：CPython audit hook + sandbox/runtime 最小读 allowlist；阻断 subprocess、network 与 native loader；记录 candidate/workload/oracle/benchmark hash、环境、dirty digest 与 timeout。
- 边界：这是对**已审计 pure-Python 候选**的 Python-level confinement，不是 OS sandbox，也不覆盖解释器/原生代码/操作系统漏洞。
- 原生分类：TEL `36 PASS / 20 HONEST_UNSUPPORTED / 2 FAIL`；rewrite `31/23/4`；causal `3/53/2`；kernel instrument `36/20/2`；model instrument `13/44/1`。Native/Companion 的三个原子候选计数未变化，说明当前 companion 没有凭 adapter 获得免费能力；也说明其没有补齐缺失语义。

### 同步修复

- 合同：exact-builtin JSON 图、深度/节点/字节预算、循环/对象子类/callback/非有限浮点拒绝；
- TEL：masked raw 全路径脱敏、semantic claim identity 与 proof root 分离；
- causal：effective/end/expiry future cut、unit/conflict/coverage、query 控制消费或拒绝；
- rewrite：全历史 rebuild、predating/动作顺序/数值冲突/half-open expiry、STOP/CANCEL 约束；
- runner：候选不能修改 diagnostics、不能自证 clean rebuild、不能覆盖已有结果目录。

## 2026-07-13 — Checkpoint 7 Pareto 收敛与条件性决策

1. 13 家族文献地图和三个原型都没有给出一个原子完整核心；所有原子候选作为“唯一完整核心”硬淘汰，但其原生能力保留。
2. 冻结 `K0` 七类控制面承诺：artifact role、identity/scope、time/cut、derivation/provenance、closed query、product failure、invariant enforcement。
3. 最终参考 profile 采用唯一 TEL/TMS evidence authority，并显式分家 state/dynamics、causal 与 rewrite/open safety；模型输出始终是版本化派生产物，不是第二权威事实源。
4. 最强反对意见仍成立：K0 可能只是接口治理，bridge 可能把被隐藏的医学语义、维护和失败面全部转移到适配层。
5. 当时文档只使用“在 13 家族、3 原型、58 workload 和 v3 威胁模型下最有支持”；不使用全局最优、唯一、形式不可约或临床已验证。bridge 反证后该措辞只保留为历史基线。

### 下一判别实验

原计划由独立团队对冻结 evidence cut 做 DBN/SSM 与 SCM 双编译 round-trip holdout，检查 root/clock/version/uncertainty、`filter != smooth`、`condition != do != AAP`、删除/更正后 clean rebuild，并量化 bridge LOC、人工承诺、错误和 blast radius。实际执行只达到 source-distinct/no-cross-import，不构成独立团队复现。

## 2026-07-13 — Checkpoint 8 交付与 QA 路线

1. 交付两张一页图、形式规范、决策/威胁/红队文档、可运行 demo、机器 fixture、raw isolated result 与指标快照。
2. 增加四类真实 checked-in typed extension：AKI architecture toy dynamic module、norepinephrine finite-SCM intervention、renal-safety task projection、cystatin-C method-qualified derivation；它们是架构扩展示例，不是临床校准模型。
3. `results/metrics-final.json` 冻结 primitive/LOC/复杂度/test-dispatch 下界；`metrics-current.json` 已含前三个扩展，最终差分额外记录 test-method extension 新增 1、fixed-core file blast radius 为 0、harness 修改 5。五个候选/仪器实现的 literal T/E ID 与 oracle/reference dispatch 静态计数均为 0；这只是反迎合证据，不是无特例证明。
4. 当时全量回归为 `119 passed, 7 subtests passed`；`python -m prototype.demo` 生成 `examples/demo_output.json`；decision-grade 全面板由 `python -m prototype.experiment --run-id <unique-id>` 运行。
5. 最终验证顺序固定：全量 pytest → demo → v3 isolated panel/metadata/hash 检查 → metrics/extension comparison → JSON parse → `git diff --check`。任一步失败都不得把 Checkpoint 8 标为完成。

## 2026-07-14 — Checkpoint 9 bridge 双实现执行轮

1. 先冻结 A/B 与 public panel 源码，再抽取/reveal seed，并生成、冻结 portable authority/model/cut/query corpus 与 hidden oracle；各 runner 在 reveal 后才生成 per-candidate projection，并非 seal 时已经冻结 candidate-view/oracle-view 文件。H01–H30 是原预注册集，H31–H41 是 post-seal/pre-execution addendum。freeze、fixture、corpus、source、runner 和 report hash 均进入可机读证据包。
2. A mechanical 为 `0 PASS / 4 ADAPTER_UNREPRESENTABLE / 37 HARNESS_INCOMPLETE`；B corrected run-03 为 `0 PASS / 41 HARNESS_INCOMPLETE`。corpus 审计只找到 4 个 concrete base、35 个 descriptor-only case；H09/H20/H21 含 dangling refs，H09 与 descriptor-only 重叠。
3. external 数值证明 A 的 filter/smooth、B 的 condition/do/AAP solver 和 B model-level aleatoric/epistemic/measurement 参数扰动路径可运行；但 A 的三通道 typed result 缺失、B 的 evidence/record uncertainty sidecar 不活跃，以及 root/cut/version、scope、correction/retraction 与 B recovery-tape split-brain 产生不可补偿 hard failure。
4. 42 个 post-seal probe 为 `15 pass / 26 fail / 1 partial`，只能作为 external evidence；candidate runner 只执行 M01 且 A/B 均未杀死，synthetic 12/12 只测试 report judge。
5. 裁决必须分账：sealed corpus 的 candidate verdict 没有 `CANDIDATE_FAIL`，只支持 `HARNESS_INCOMPLETE`；单独记账的 deterministic external hard counterexamples 才支持冻结实现层 `HYPOTHESIS_FAIL`。冻结 A/B 被淘汰为合规 bridge，K0 family 不被宣告不可能；Checkpoint 3/7 重开。
6. 专项回归为 `16 passed`，全量为 `135 passed, 7 subtests passed`；最终人读/机读报告位于 `results/bridge-holdout/REPORT.md` 与 `final-report.json`。
7. Git 逻辑实验工件 checkpoint 为 `abac08786f642c28ba76d8940c60fe1906ab9945`；`d08a8e5b12377890499703b6de6bed1f90c4aa98` 只加入 exact-byte packaging，不改变实验语义。机器报告从后者直接复核 26 个决策依赖 Git blobs。
