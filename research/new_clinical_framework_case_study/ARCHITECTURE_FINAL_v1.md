# 新临床动态地图架构定稿 v1

状态：**架构合同冻结（architecture contract freeze）**  
版本：`NCF-ARCH-1.0.0`  
边界：本文件定义一类可证伪的临床状态架构，不声称参数已经校准、个体反事实已经识别，
也不声称存在唯一、有限、永久不变的全医学模型。本架构独立成立，不依赖任何其他
VeSMed 架构或实现。

## 1. 定稿结论

患者在时刻 `t` 的真实状态不是一个病名，也不是一根全局扁平向量。系统维护的是基于
当时可得历史形成的共享后验状态：

```text
患者共享状态 =
    并发 active-process / factorial branches 的联合不确定性
  + 每个 process / organ 的局部连续坐标后验
  + 每个 process / organ 的局部 hybrid mode 后验及相互耦合
  + 足以支持当前动作集合的动作生命周期与历史摘要
  + OOD / 未建模信息 / 因果不可识别的 epistemic residual
```

围绕这份状态：

```text
typed factor graph          内部状态、动作、背景怎样生成症状和检查
controlled hybrid dynamics  时间和动作怎样改变连续状态、模式与过程激活
branch/stratified geometry  哪些状态在当前任务中真正相近
single shared state         诊断、自然预测、动作预测读取完全相同的状态字节
local refinement            新动作暴露危险状态碰撞后，只细化有关局部
```

## 2. 一切“相同”必须绑定范围

任何模型、距离、充分性或“理想状态”声明必须绑定冻结范围：

\[
\Omega=(\mathcal P,\mathcal O,\mathcal A,\Pi,H,\mathcal Y,U,\epsilon)
\]

- `P`：适用人群与场景；
- `O`：可用观察和检查；
- `A`：允许动作；
- `Π`：允许的动作序列/策略；
- `H`：预测时间范围；
- `Y`：重要结局；
- `U`：效用和患者价值；
- `ε`：允许的预测/决策误差。

不声明 `Ω`，就不能声称两个患者相同，也不能声称某状态表示充分。

## 3. 数学语义

### 3.1 世界状态与公开历史

真实但通常不可完全观察的世界状态写作：

\[
X_t=(Z_t,\{x_{p,o,t},m_{p,o,t}\},\Theta_t,L^A_t,R_t)
\]

- `Z_t`：多个 active processes 的联合激活状态，不是互斥单标签；
- `x_{p,o,t}`：process `p` / organ `o` 内的局部连续状态；
- `m_{p,o,t}`：该局部当前运行模式；
- `Θ_t`：会改变动力学或观察生成的个体背景；
- `L^A_t`：动作生命周期、累计暴露和残余作用；
- `R_t`：未建模、映射缺口和不可识别残余。

系统在 cut `t` 只能读取当时已可用的公开历史：

\[
H_t=\{e_i:t_i^{available}\le t\}
\]

发生时间、采样时间、结果可用时间、记录时间必须分开；未报告精确时间时只保存偏序，
不得伪造钟表时间。

### 3.2 共享后验状态

程序持有的 `SharedPatientStateV1` 是：

\[
B_t=P(X_t,M\mid H_t,\Omega)
\]

其中 `M` 允许表示多个仍与资料相容的世界模型。真实患者可能是一条隐藏路径；状态中的
“云”是认知不确定性，不是患者本体。

## 4. 并发 active processes

疾病、并发症、器官失效和治疗相关过程可以同时活跃。因此：

- `P(process_i active)` 与 `P(process_j active)` 不要求相加为 1；
- 系统必须保存关键 process 之间的依赖或联合假说；
- “原假说退出”与“新过程激活”是不同事件；
- 互斥关系只有在医学定义或生成模型明确要求时才能声明；
- 一个过程不得仅因另一个过程存在而被迫归零。

实现可使用 factorial posterior、结构化粒子或联合因子后验，但 wire state 必须同时提供
过程边缘概率和必要的依赖/联合摘要。把所有候选强制压进单一 simplex 不符合 v1。

## 5. 局部连续坐标

每个 process / organ 使用自己的合法局部坐标。坐标必须：

1. 有类型、单位、支持域和不确定性；
2. 能被观察、动作响应或机制约束；
3. 具有明确适用 stratum；
4. 不把疾病身份藏进普通观察；
5. 不要求跨不相容 strata 做欧氏平均或直线插值。

同一患者可以同时具有肝、心、循环等不同局部状态。局部坐标是计算工具，不是全局患者
本体。若坐标无法被任何允许观察或安全探针约束，它只能保留为不确定变量，不能伪装成
精确数值。

## 6. 局部 hybrid modes 与耦合

mode 表示局部系统当前服从哪套动力规律，而不只是严重度标签。允许的通用 mode registry
至少能表达 `compensated`、`strained`、`decompensated`、`recovering`、`failed`；
具体领域可版本化扩展。

同一连续位置在不同 mode 下必须允许具有不同 drift、噪声和动作响应：

\[
dx_{p,o}=f_{p,o,m}(x,Z,\Theta,L^A,t)dt
            +\sigma_{p,o,m}(\cdot)dW
\]

mode 跳变由显式 guard、事件或概率 hazard 驱动，并支持 hysteresis：进入失代偿的边界与
恢复边界不必相同。禁止把一个全局 mode 无差别复制给所有器官/过程。

局部系统可通过类型化耦合相互影响，例如：

- `dynamic`：一个局部状态改变另一个的 drift；
- `mode_guard`：一个过程改变另一个模式跳变概率；
- `shared_latent`：多个观察共享上游机制；
- `constraint`：组合状态的生理可行性约束。

耦合必须有方向、适用条件、时滞、置信/来源和版本；不得用隐含的重复加分替代。

## 7. Typed factor graph：观察生成

观察不等于状态。typed factor graph 明确区分：

- `latent_process`、`local_coordinate`、`local_mode`；
- `background_context`；
- `action_exposure`；
- `measurement_condition`；
- `observation`；
- `outcome`。

因子至少包括：

- `emission`：内部状态到观察分布；
- `common_cause`：相关观察共享上游原因；
- `measurement`：方法、采样、治疗掩盖和误差；
- `interaction`：多个过程共同生成观察；
- `constraint`：不合法组合或条件依赖。

可靠阳性和可靠阴性都必须通过 likelihood 改变后验。未检查、未知、阴性、治疗后阴性
和低敏感度阴性不是同一状态。同一来源结果复制多次不能增加信息。禁止用“每项异常独立
加分再归一化”冒充联合因子推断。

## 8. 动作生命周期与受控混合动力学

动作不是布尔标签。每个动作实例至少保存：

```text
planned → started → active/held → stopped/completed → residual/washout
```

以及开始/停止 cut、剂量/强度轨迹、累计暴露、依从/执行、残余作用、可观测响应和来源事件。
planned 动作不能改变生理状态；performed 动作必须按 exact-once 语义进入更新。

统一转移核为：

\[
P(B_{t+\Delta},O_{t+\Delta}\mid B_t,do(\pi),\Omega)
\]

自然预测是显式 `no_new_action/continue_current` 策略，不是遗漏动作字段。`start`、
`continue`、`hold`、`stop`、剂量改变和洗脱必须能产生不同转移。治疗可改变过程活动、局部
drift、mode guard、观察生成或噪声，但不得作为疾病身份快捷标签。

从观察性数据得到的条件预测不自动等于 `do()` 反事实。缺少识别条件时必须输出范围或
`UNIDENTIFIABLE`。

## 9. 分支/分层的行为几何

全局状态空间允许分支、汇合、不同局部维数和模式边界；不要求是单一光滑流形。几何不是
装饰性可视化，它必须实际影响邻近检索、后验传播或规划。

在范围 `Ω` 下，行为距离原则上由未来与动作响应定义，例如：

\[
d_\Omega(b,b')=
\sup_{\pi\in\Pi}D\left(
P(Y_{0:H}\mid b,do(\pi)),
P(Y_{0:H}\mid b',do(\pi))
\right)
\]

其中 `D` 是预先声明的分布距离/效用差异。表型接近但动作响应相反的状态必须远；跨分支
路径必须尊重合法转换和共享父机制。关闭 topology 后若所有查询完全不变，就说明几何未
真正接入 runtime。

## 10. OOD 与 epistemic residual

开放世界不确定性是状态的一等组成，不得固定成装饰性常数。至少拆分：

- `mapping_gap`：公开事实没有安全映射；
- `model_misfit`：已知因子无法解释观察；
- `unmodeled_process`：可能存在 atlas 外过程；
- `measurement_uncertainty`：数据质量/方法不确定；
- `causal_nonidentifiability`：动作反事实不可识别；
- `scope_gap`：所问问题超出 `Ω`。

系统必须列出未解释观察和缺失的区分信息。大量未映射事实不得与固定的低 unknown mass
并存。OOD 可以触发拒答、范围输出、新检查建议或候选过程扩展，但不能强制归到“最近病”。

## 11. 单一共享状态合同

诊断、自然预测和动作预测必须读取**同一份 canonical serialized state bytes**：

```text
diagnose(state_bytes)
rollout(state_bytes, no_new_action_policy)
rollout(state_bytes, do(policy))
plan(state_bytes, candidate_policies)
```

- query 必须纯函数式，不得修改状态；
- query 不得私自重读病例、构造新的任务专用表示或读取未来事件；
- 所有 query 输出必须记录相同 `input_state_hash`；
- update 由父状态和新可用事件递归产生子状态，并记录 parent hash；
- fresh-process 反序列化更新必须与同样事件的冷启动重放语义等价；
- canonical JSON 禁止 NaN/Infinity，数组顺序和数值编码必须确定。

诊断是 active-process、mode 和局部状态的后验摘要，不必输出唯一病名。预测是后验传播。
治疗查询是在识别边界内比较动作后的结局分布和 regret；三者不是三个独立编码器。

## 12. 状态碰撞与局部细化

在旧范围 `Ω` 中，若两个世界历史被编码为同一状态且所有旧策略的响应在 `ε` 内等价，
合并可以合法。新动作、检查或结局加入后，若存在：

\[
\phi(H_1)=\phi(H_2),\quad
|V^{\pi^*}(H_1)-V^{\pi^*}(H_2)|>\epsilon
\]

且两者最优安全动作不相容，则构成**危险状态碰撞**。

合法细化流程固定为：

```text
冻结碰撞 witness
→ 排除时间泄漏、动作混杂和标签错误
→ 寻找治疗前可用、可复现、有区分力的观察/安全探针
→ 若存在，新增 typed factor/coordinate 并只拆相关 stratum
→ 提供旧 state → 新 state 的显式迁移
→ 验证旧范围查询和无关 strata non-regression
→ 若不存在可观察区分信息，保持合并并输出 UNIDENTIFIABLE
```

新动作扩展在相同人群、结局和容差下只可保持或细化旧行为等价划分，不能无证据全局重写。
局部拆分后必须能回溯 lineage，旧状态不得仅因 model digest 变化而被静默丢弃。

## 13. 范围相对的理想状态

在固定 `Ω` 下定义行为等价：

\[
H\sim_\Omega H'
\iff
\forall\pi\in\Pi,
P(Y_{0:H}\mid H,do(\pi))
\approx_\epsilon
P(Y_{0:H}\mid H',do(\pi))
\]

其商空间 `H / ~Ω` 是抽象的最小充分行为状态：响应不同必须分开，响应等价可以合并。
但这只给出定义，不保证该状态：

- 有限维；
- 能从现有观察识别；
- 有唯一可解释坐标；
- 能由有限数据学习；
- 在新增动作、结局或更长 horizon 后保持不变。

因此 v1 冻结的是**构造和检验原则**，不是永恒的疾病地图。

## 14. 不可识别边界

若多个世界模型对所有可获得观察和允许安全实验给出相同分布，却对目标反事实给出不同
答案，则目标不可识别。系统必须保存相容世界/范围与所需新增信息，不得以模型复杂度、
LLM 断言或伪精确概率填补。

标准输出状态：

- `IDENTIFIED_WITHIN_SCOPE`：声明假设下可识别；
- `PARTIALLY_IDENTIFIED`：只能给上下界/集合；
- `UNIDENTIFIABLE`：相容世界给出冲突答案；
- `OUT_OF_SCOPE`：问题不在冻结 `Ω` 内。

单个病例的实际治疗与结果原则上不能唯一恢复该患者未实施治疗的结果。

## 15. 版本、迁移与 lineage

三种版本必须分开：

1. `architecture_version`：本合同版本；
2. `model_version/model_digest`：因子、动力学和几何参数版本；
3. `scope_version/scope_digest`：`Ω` 版本。

任何 schema、process registry、mode registry、factor、action或 scope 变更必须产生新 digest。
局部细化必须提供确定性、可测试的 migration：

- 保存 parent state hash 和 parent model digest；
- 未获得新区分证据时，将旧父 posterior 合法分配到 children，而不是伪造确定分型；
- 保持旧 query 的可比性；
- 记录新增检查何时可用，禁止用迁移把未来证据写进过去状态；
- 迁移失败必须显式报错或保持旧版本，不得静默重编码。

## 16. v1 硬门禁

硬门禁是可被一个决定性反例击穿的能力合同，不是随意选择的 AUROC 阈值。任何临床有效性
主张前，至少必须通过：

| ID | 门禁 |
|---|---|
| G01 | cut 只能消费当时已可用事件；未来结果不能改变旧状态 |
| G02 | planned 与 performed 分开；动作 start/continue/hold/stop/washout 可区分 |
| G03 | 事件 exact-once；fresh-process 递归更新与冷启动重放语义闭包 |
| G04 | diagnosis、自然 rollout、动作 rollout、plan 使用相同 state bytes/hash |
| G05 | query 纯度、顺序无关、无病例旁路和无未来 side channel |
| G06 | 同来源复制不增证据；可靠阴性可产生方向正确的 likelihood |
| G07 | 多 active processes 可并发；非互斥边缘概率不被强制 simplex 化 |
| G08 | branch/organ-local mode；同坐标不同 mode 可产生不同方向，并有 guard/hysteresis |
| G09 | 支持掩盖可表示；相同输出、不同支持生命周期得到不同状态/未来 |
| G10 | topology/geometry 接入推断或规划；禁用后应在预注册反例上暴露错误 |
| G11 | no-op/continue/start/stop/dose/washout 有语义不同的受控转移 |
| G12 | unmapped/misfit 进入 epistemic residual；未知不被固定低估 |
| G13 | 动作响应到来后，同一 state 更新必须联动所有后续查询 |
| G14 | 危险碰撞可检测；无可观察拆分轴时必须 abstain |
| G15 | 新检查/新动作只局部细化，并有迁移与旧范围 non-regression 证据 |
| G16 | schema、model、scope、lineage、hash 可重现；旧状态不可静默失效 |
| G17 | 反事实输出携带识别状态、假设和范围；不可识别不得输出唯一答案 |
| G18 | 真实病例回放不仅验证接口，还必须审计临床定位、模式、预测、动作和 OOD |

结构测试通过不等于临床 readout 通过；真实病例相容不等于参数校准、总体有效或治疗因果
有效。报告必须分别标记 `STRUCTURALLY_SUPPORTED`、`CASE_CONSISTENT`、`FAILED`、
`UNIDENTIFIABLE`。

## 17. Wire schema

`architecture_final_v1.schema.json` 是 `SharedPatientStateV1` 的规范 wire schema。
它定义最小可交换状态，不规定具体推断算法。实现可在内部使用粒子、变分后验、精确枚举或
其他方法，但序列化输出必须满足 schema，并满足本文件中无法由 JSON Schema 单独表达的
运行时不变量：

- 所有概率有限且在 `[0,1]`；每个局部 mode posterior 归一；process marginals 不要求总和为 1；
- `state_hash = SHA-256(canonical payload excluding integrity.state_hash)`；
- `processed_event_ids` 唯一且 exact-once；
- 所有 factor message 的 `source_result_ids` 可追溯；
- 所有 query 记录相同输入 hash；
- 所有迁移记录 parent/child model 与 state lineage；
- epistemic residual 与未解释观察一致，而不是固定常数。

## 18. 冻结后的改变规则

以下属于 v1 breaking change：重新引入互斥单 branch、全局单 mode、任务专用重编码、把
unknown 固定成常数、让几何脱离 runtime、删除动作生命周期或不可识别输出。

新医学 process、坐标、factor、动作和局部 mode 通常是 model/registry 更新；新增 wire
必填字段或改变上述语义才升级 architecture/schema major version。

最终一句话：

> **v1 把患者表示为一份范围相对、开放世界、并发过程、局部混合动力学的共享后验；
> 诊断、预测和动作比较只是对同一状态的不同查询，新能力通过碰撞证据局部细化地图，
> 无信息时明确保留不可识别。**
