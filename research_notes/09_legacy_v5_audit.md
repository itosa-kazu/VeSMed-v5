# 现有 VeSMed V5/SDE 作为 C05 具体实现的被动审计

> **审计日期**：2026-07-13  
> **仓库根目录**：`C:\Users\wangw\Documents\vesmed`  
> **Git 快照**：`13c31d22f14904b2cd50a9e913dedbf60a1138c2`  
> **范围**：把当前 V5 当作候选 C05（状态空间模型 / POMDP / SDE）的一个既有实现，按 `REQUIREMENTS.md` 与 `ARCHITECTURE_TESTS.md` 审核其**当前真实执行路径、表示原语、病例输入和治疗 runtime**。  
> **操作边界**：只读；没有运行会在启动时改写 `master_axes.json` 的 `start_ui.py`，没有修改任何既有代码或数据，也没有把旧 result 文件当作当前行为证明。

## 0. Outcome：结论先行

### 0.1 对当前实例的结论

**当前 VeSMed V5 不能作为本研究所要求的“固定核心架构”进入决赛。** 它至少硬失败于：角色/认识论分离、双时间、观察过程、证据身份与血缘、冲突和撤回、干预生命周期、显式 unsupported、历史重放、方法学/单位安全，以及开放世界拒绝。

这不是说 C05 家族没有价值。相反，标准状态空间/POMDP 原语天然适合表达隐藏状态、转移、观察模型、动作和 belief；当前 V5 也已有一些可保留的数值资产：疾病轨迹、latent mechanism、risk modulation、coupling、health reference 和一个 Euler-Maruyama 风格的治疗模拟循环。**较有根据的定位是：把 C05/SDE 保留为“生理动力学与预测计算模块”，而不是让它独自承担事实账本、证据语义和固定核心。**

### 0.2 三种缺口必须分开

- **`M`（model-family implementable）**：SSM/POMDP/SDE 理论上可自然支持，但当前 V5 没有实现，例如显式 `p(y_t | x_t,u_t,method)`、序贯 filtering、动作条件转移、非线性交互核。
- **`C`（current-representation conflict）**：当前 V5 的基本表示本身与不变量冲突；不是补一个参数即可，例如把病例压成 `axis_id -> 一个浮点观察`、把未观察的 required context 合成 `0.0`、让 disease-specific hazard 出现在观察证据里。
- **`X`（requires companion semantic core）**：裸 C05 不原生提供，必须由类型化双时间事件/证据账本、truth maintenance、知识版本和安全规则层承担。补完后候选身份应诚实记作混合架构，而不能仍把全部能力记给 SDE。
- **`B`（blocked runtime）**：当前实现链条存在可确定的运行阻塞。

## 1. 审计快照和活跃执行路径

### 1.1 输入规范哈希

| 文件 | SHA-256 |
|---|---|
| `REQUIREMENTS.md` | `A9A944A876781E30C98243B6D68E6820B8C97C5F0A83286F094566A55108ABE9` |
| `ARCHITECTURE_TESTS.md` | `619220A30421ECFA77A590B60B56E3456F0CE7E5E675926CCCC8FE6ACB1B8B93` |
| `start_ui.py` | `FDC20878216D09B658F792A9B28617345C6A28518DC92F45C653E827A6636DB3` |
| `v5_joint_sde_case_test.py` | `43F69BA5C2AC8CAD14D255FE72701B192DB867612CE159EAA2D4440F628BB23C` |
| `v5_joint_sde_treatment_sim.py` | `4ED50CA482FD24BD0983F683B63F21D6D1561A8DEFD099F192C30B0847368ED7` |
| `master_axes.json` | `B2784210D665D850198532CFD0786094D545B543E132FC0BA266D549C60F938C` |

### 1.2 当前真正连到 UI 的诊断路径

```text
start_ui.bat
  -> python start_ui.py
      -> 启动时 build_master_axes() 并重写 master_axes.json
      -> POST /run_case_test
          -> subprocess: v5_joint_sde_case_test.py
              -> load distillations/v5_*.json
              -> load master_axes.json + health_reference + background modifiers
              -> flatten each case to observations_by_axis
              -> score every candidate with endpoint Gaussian likelihood
              -> write distillations/joint_sde_case_test_result.txt
```

证据：

- 批处理入口直接执行 `python start_ui.py`：`start_ui.bat:1-4`。
- UI 的 `/run_case_test` 用当前解释器启动 `v5_joint_sde_case_test.py`：`start_ui.py:288-331`。
- UI server 启动前无条件调用 `build_master_axes()`：`start_ui.py:519-523`。
- 诊断 main 加载 active manifolds、master registry、病例，然后构造候选：`v5_joint_sde_case_test.py:11651-11663`。

因此，`v5_current_schema_case_test.py`、`v5_sde_forward_v*.py` 和大量旧 result 文本不是 UI 当前主执行路径。治疗模拟 `v5_joint_sde_treatment_sim.py` 是另一个手动入口，没有被 `/run_case_test` 串成诊断后动作选择。

### 1.3 当前数据规模（只读重算）

| 项目 | 当前值 | 解释 |
|---|---:|---|
| root active manifold JSON | 184 | `distillations/v5_*.json`，且符合当前 loader 的 manifold shape |
| active case JSON | 458 | `distillations/cases/v5_case_*.json` |
| 含 expected label 的病例 | 457 | `expected_manifold(s)` |
| 含 paper disease label 的病例 | 454 | `disease_label_per_paper` |
| committed registry axes | 10,662 | 当前 `master_axes.json.axes` |
| 按 `build_master_axes()` 逻辑只读重建应有 axes | 5,958 | 不写文件的等价扫描 |
| 仅 committed registry 存在 | 4,968 | 启动 UI 后会消失 |
| 仅 active rebuild 存在 | 264 | 启动 UI 后会新增 |
| 含 `applies_to` 的病例 | 78 | 共 216 个 occurrence |
| 含 disease-specific axis id 的病例 | 222 | 共 1,180 个 occurrence，含被 loader 清洗或排除者 |
| 含原始 evidence identity 字段的病例 | 0 | 扫描 `evidence_id/source_id/record_id/observation_id` |
| 含独立 known/report time 字段的病例 | 0 | 扫描 `known_from/known_time/recorded_at/available_at/result_day/reported_day/report_day/available_at_day` |

这些计数不是用旧报告推断，而是对当前 JSON 的 Python 标准库只读扫描。`day`/`snapshot_day` 存在，但那不是独立的知识可见时间。

## 2. Key Evidence：当前 runtime 实际上做了什么

### E01 — 诊断不是序贯 particle filter；是“时间索引 endpoint 的静态高斯混合”

当前文件头也明确说 endpoint 使用 transformed axis space 中的 Gaussian marginal：`v5_joint_sde_case_test.py:10-15`。真实代码路径为：

1. 每条 disease axis 用手写的 baseline→线性上升→plateau→半衰期下降函数生成均值；`sample_mu_and_baseline()` 见 `v5_joint_sde_case_test.py:4575-4601`。
2. sigma 由 baseline/peak 范围跨度启发式产生，而不是由一条已传播的 filtering covariance 得到：`v5_joint_sde_case_test.py:4604-4637`。
3. 默认 `SCORE_MODE="grid"`，不是 particle mode：`v5_joint_sde_case_test.py:168-180`。
4. 病例 time series 会先选距 `snapshot_day` 最近的一点，压成单个观察：`v5_joint_sde_case_test.py:3804-3831`。
5. 对每个假设 disease day 重新拼 `x, mu, sigmas, corr`，调用 multivariate normal logpdf，再对 time grid 做 `logsumexp`：`v5_joint_sde_case_test.py:11078-11148`；高斯公式见 `v5_joint_sde_case_test.py:10721-10762`。

没有看到 `p(x_t|y_{≤t}) -> predict -> update` 的序贯递推，也没有把前一时点 posterior 作为下一时点 prior。这里的“latent time marginalization”不等于 particle filter。准确描述应是：**对 presentation snapshot 的 time/parameter mixture of endpoint Gaussian likelihoods**。

正面保留项：`axis_couplings` 会构造 covariance，risk factors 可调 axis/coupling，latent mechanism 可 gate downstream axes；这说明 V5 有 SSM 风格的医学生成参数，但尚未形成可回放的临床 filtering runtime。

### E02 — 隐状态与观察通道在当前基本表示中碰撞

当前文件把 state `x` 定义为“joint vector over observed axes”：`v5_joint_sde_case_test.py:4-15`。病例观察也直接被转成这个 axis 的浮点值；`observation_value_for_axis()` 只处理数值、单位和少数 qualitative flag：`v5_joint_sde_case_test.py:1161-1223`。

更关键的是，`prepare_case_data()` 只保留少量 axis metadata；method、measurement condition、device、support therapy、reliability、subject/body site、evidence id 都不在复制列表中：`v5_joint_sde_case_test.py:3701-3748`。治疗端的 `push_targets` 又直接对 axis 值加减，`sigma_modulation` 直接改 axis sigma：`v5_joint_sde_treatment_sim.py:588-666`。当前 schema/runtime 没有一个独立的 emission/observation-channel effect 原语。

所以 T01–T05/T17 的问题不是“参数还不准”，而是当前 `x`/`y` 没有分开：高流量氧下 SpO2、升压药下 MAP、退热药下体温、抗菌药后的培养灵敏度都没有统一的观察过程对象。标准 C05 可以加 `y_t ~ g(x_t,u_t,method,condition)`，故这是 **`C`（当前表示冲突）+ `M`（家族可修）**，不是整个 C05 家族的理论淘汰证据。

### E03 — 病例被压成每个 axis 一个值；冲突、独立来源和撤回都丢失

`prepare_case_data()` 的核心容器是 `observations = {}`：`v5_joint_sde_case_test.py:3684-3688`。同一 axis 再出现时：

- 更接近 snapshot 的覆盖旧值；
- 同距离的 bounded/hazard 取更大的值；
- 其他值取日期更晚者。

见 `v5_joint_sde_case_test.py:3749-3764`。这不是 conflict set，也不是 evidence multiset，而是带启发式覆盖的 map。派生项最多记录 `_derived_from_axes`，没有原始 evidence root 身份：`v5_joint_sde_case_test.py:3716-3748, 4515-4526`。

评分 trace 只保存 `(axis_id, observed_value, unit, mu, source)`，不含 source record id、valid/known time、rule/model version 或独立根集合：`v5_joint_sde_case_test.py:11128-11146`。因此 R-PROV-01/02/03、T06/T10/T24/T27/T34 不能由当前实现满足。

### E04 — 未观察 required context 被合成为 candidate-specific `0.0`

当某候选 manifold 有 required context 而病例未提供支持时，runtime 会构造：

```json
{
  "value": 0.0,
  "source_text_value": "required context/source/substrate not observed in the case stage",
  "_virtual_required_context_support": true
}
```

见 `v5_joint_sde_case_test.py:5906-5947`。然后它复制病例、把这些虚拟 observation 并入 `observations_by_axis`：`v5_joint_sde_case_test.py:5951-5960`；`score_candidate()` 在选 axis 前首先做这一步：`v5_joint_sde_case_test.py:10926-10936`。

这直接把 “not observed” 变成数值 0/negative evidence，违反 R-UNC-01、A-06 和 T11。它还造成 E07 所述候选维度变化。若业务希望 required context 缺失降低 posterior，正确原语应是显式 missingness/selection/prior factor，而不是伪造一条患者观察。

### E05 — presentation 边界存在，但不是双时间，且当前病例仍有未来信息流入

值得肯定的是，runtime 有 presentation/post-workup 过滤器：`v5_joint_sde_case_test.py:428-447, 1899-1974, 2278-2297`。但它主要依赖：

- 可选的 `result_day/reported_day/...`；
- section 名；
- 对 `culture/pathology/PCR/...` 的字符串 token 猜测。

当前 458 个病例的只读扫描没有找到一条独立 known/report time 字段，因此多数项目只能靠 section/token 猜。反例已经在 active case 中：

- `snapshot_day` 是 0：`distillations/cases/v5_case_ADENOVIRUS_INFECTION_IMMUNOCOMPETENT_PNEUMONIA_PMC7101838.json:20`。
- 同一 case 的 initial imaging 正常、未来 72h 才出现 consolidation/effusion：该文件 `:13-18`。
- 但 later hemorrhagic conjunctivitis、later bilateral consolidation、later CT pleural effusion 被放在无 `day`/`result_day` 的直接 `observations`：该文件 `:91-109`。
- 直接 observations 默认进入评分：`v5_joint_sde_case_test.py:3767-3773`；token filter 不把单词 `later` 识别成 post-workup。

这已经足以判定 T12/T13/T25 的未来隔离不成立。`snapshot_day` 是有效/病程时间近似，不是 known-time cutoff。

### E06 — benchmark 中仍存在 candidate label 通道和派生/结局证据

需要准确区分三种情况：

1. `expected_manifold(s)` 在**诊断评分函数**中主要用于 validation，不直接传入每个候选 log likelihood；对应读取位于 `v5_joint_sde_case_test.py:11278-11283, 11414-11440`。因此不能笼统声称 expected label 本身总是直接加分。
2. 但是 `risk_context[*].applies_to` 会按正在评分的 disease 选择 context，直接进入 risk payload：`v5_joint_sde_case_test.py:4820-4832, 10968-10978`。例如 AOSD/TTP case 把 context 明写为 `applies_to: ["D137"]` 或 `["D-TTP"]`：`distillations/cases/v5_case_AOSD_TTP_CONCURRENT_PMC7523203.json:27-58`。当前有 78 个病例、216 个此类 occurrence。
3. disease-specific event/mortality hazard 被允许保留为 observation id：`v5_joint_sde_case_test.py:1860-1887`。例如 active HAV case 直接观察 `acalculous_cholecystitis_hazard_in_D-ACUTE-HEPATITIS-A`，并用“recovered and discharged”构造 `mortality_hazard_in_D-ACUTE-HEPATITIS-A`：`distillations/cases/v5_case_ACUTE_HEPATITIS_A_ACALCULOUS_CHOLECYSTITIS_PMC3784234.json:77-79`。

按当前 direct-observation 默认过滤逻辑做只读下界扫描，至少有 **74 个病例中的 93 条 rankable disease-specific hazard observation**，其中 10 条是 disease-specific mortality hazard。它们是推断/结局或疾病定义的变量，不是 diagnosis-neutral 原始 presentation observation，会造成 R-EPI-02、R-PROV-02、T13 和 A-05 型污染。

治疗 runtime 更直接：它不读取诊断 runtime 的 posterior，而是把每个 case 的 expected manifold(s) 当 candidate：`v5_joint_sde_treatment_sim.py:1182-1193`。所以现有治疗结果不能算“诊断→治疗”的端到端盲流程。

### E07 — 基础 scored-axis 集合试图固定，但 candidate-specific virtual axes 又破坏可比性

`case_rankable_axis_ids()` 的设计目标是让所有疾病为相同 observed facts 付 likelihood rent：`v5_joint_sde_case_test.py:6141-6157`，这是正确方向。

但实际调用顺序是先执行 `case_with_required_context_geometry(case, candidate, ...)`，为每个候选注入不同 virtual axes，再计算/缓存 axis set：`v5_joint_sde_case_test.py:10926-10936`。结果对象把 `n_axes=len(axis_ids)` 写出，并按 raw `log_marginal` 排序：`v5_joint_sde_case_test.py:11148-11167, 11432-11440`。只要候选 required-context group 不同，维度就不同，raw log density 不再是同一 observation space 上可直接比较的 Bayes factor。

此外，`eval_axis()` 取 candidate 中第一个拥有该 axis 的 disease schema：`v5_joint_sde_case_test.py:9842-9850`。当前只读扫描按 runtime canonical axis id 分组，发现 **202 个 axis id 有不止一种规范化 unit 或 `log_scale` 取值**（其中 143 个 unit conflict、81 个 log-scale conflict；二者有交集）。converter 对未知单位组合最终原样返回：`v5_joint_sde_case_test.py:895-1043`。因此不同候选还可能选择不同变换空间。

### E08 — bounded/binary/probability 轴统一按连续 Gaussian 打分

`is_bounded_0_1_axis()` 只用于 clamp mean：`v5_joint_sde_case_test.py:9783-9839`。真正 likelihood 无论 unit 是 `present_absent_0_1`、`probability_0_1`、severity 还是连续 lab，都进入同一个 MVN：`v5_joint_sde_case_test.py:10721-10762, 11128-11136`。

当前 atlas 有 5,955 条 bounded-axis records（2,984 个 raw unique ids，分布于 183/184 个 manifold）。对 0/1 observation 使用小 sigma 的 continuous normal 会把边界点当极强密度证据；这不是 Bernoulli/binomial/ordinal observation model。

对 log-scale axis，代码先 `log10(x)` 再代入 Gaussian：`v5_joint_sde_case_test.py:4689-4702`，但最终 likelihood 没有回到原测量空间的 Jacobian 项。若 candidate 选择的 `log_scale` 不同，density 甚至不在同一个 measure 上。这与 E07 的 schema conflict 叠加，削弱 health-vs-disease 和 disease-vs-disease logP 的可解释性。

### E09 — treatment 文件中确有粒子 SDE 循环，但当前入口被 arity mismatch 阻塞

正面证据：治疗 simulator 会构造 260 个 particles，用 correlated noise 和 mean-reverting Euler 更新：`v5_joint_sde_treatment_sim.py:31-43, 1045-1080`。这是真正比诊断 snapshot scorer 更接近 forward SDE 的代码。

阻塞证据：

- 当前 `build_corr` 定义要求 5 个位置参数，包括 `background_axes`：`v5_joint_sde_case_test.py:10680-10718`。
- treatment simulator 只传 4 个：`v5_joint_sde_treatment_sim.py:1028-1041`。
- Python AST 只读核验输出为：definition line 10680 positional args 5；call line 1040 positional args 4。

因此当前 treatment runtime 在第一个实际 simulation 进入 `build_corr` 时会抛 `TypeError`；旧 `joint_sde_treatment_result.txt` 来自旧 atlas/旧签名，不能证明当前代码可运行。按 T38，这至少是显式异常而非静默忽略，但没有 load-time interface validation，且当前端到端治疗链为 **`B`**。

即使修正 arity，当前 treatment schema/runtime 也只实现 trajectory modification、push target、sigma modulation 和 mechanism gating；active 1,735 个 treatment records 中没有独立 observation-channel effect 字段。文件自己也承认 timed stages 不会基于 follow-up response 分支：`v5_joint_sde_treatment_sim.py:1224-1233`。

### E10 — `master_axes.json` 是会被普通启动改写的 runtime 状态

`build_master_axes()` 扫描 root distillations 并直接写 `master_axes.json`：`start_ui.py:101-153`。它既在启动时运行：`start_ui.py:519-523`，又在每次保存 distillation 后运行：`start_ui.py:490-509`。

当前 committed registry 有 10,662 axes，而 active files 按同一算法重建只有 5,958；启动 UI 会删除 4,968 条、增加 264 条。诊断 runtime 又会读取这个 registry，并把其中 axis 加入 background universe：`v5_joint_sde_case_test.py:1396-1400, 1632-1666`。

所以“启动 UI”不是无副作用的查看动作，而会改变后续 runtime 的 background representation。registry 没有事务版本、knowledge version 或 replay snapshot；`version` 固定为 0：`start_ui.py:146-152`。这直接攻击 R-TIME-03、R-REP-01、T23/T25/T32/T36/T40。

### E11 — 不兼容输入多处静默近似，不满足 typed quarantine

- axis 没有 `axis_id`、没有 baseline 时被 loader `continue` 掉：`v5_joint_sde_case_test.py:1335-1361`。
- invalid/incomplete mechanism edge 返回 `None` 后被忽略：`v5_joint_sde_case_test.py:1265-1296, 1362-1369`。
- 单位转换表不认识的组合最终 `return value`，没有 error/quarantine：`v5_joint_sde_case_test.py:895-1043`。
- `normalize_distillation()` 只把缺失 top-level array 补成空数组，并不是 schema validation：`start_ui.py:83-98`。
- new measurement `method` 即使存在，也不进入 `observation_value_for_axis()` 的语义或 trace：`v5_joint_sde_case_test.py:1161-1223`。

因此 T22/T29/T33 是 silent approximation，而不是 `EXPLICIT-UNSUPPORTED`。

### E12 — 默认 geometry-first 已关闭 legacy anchors，但 active core 仍有 disease/drug 名称分支

为避免误报：默认 `RANKING_PHILOSOPHY="geometry_first"`，legacy anchor/bonus scaffold 只在显式 opt-in 时启用：`v5_joint_sde_case_test.py:174-176, 420-453, 10940-10952`。不能把所有 legacy anchor functions 都说成当前默认得分来源。

但 active default 仍有：

- `ENABLE_STRUCTURAL_PRIORS=True`：`v5_joint_sde_case_test.py:184-203`；anatomic prior 对 disease-id set 做硬编码：`v5_joint_sde_case_test.py:4868-4898`。
- demographic category 对 `D-SEPSIS-GN/D137/D-TTP/D-GCA` 分支：`v5_joint_sde_case_test.py:4723-4755`。
- 特定 disease `T_MAX_BY_DISEASE`：`v5_joint_sde_case_test.py:162-166, 4566-4572`。
- treatment drug-name/class token 表、特定药物 coverage map，以及 `if disease == "D-SEPSIS-GN"`：`v5_joint_sde_treatment_sim.py:53-67, 332-441, 461-483`。

所以新增疾病/药物的 blast radius 并非稳定保证为 0。root JSON discovery 是局部扩展优势，但核心仍夹带特殊词表和 disease-id 分支，R-COMP-01/A-05 只能判 partial/fail，不能凭 “glob 可发现 JSON” 判 pass。

## 3. REQUIREMENTS.md gap map

`HARD-FAIL` 表示当前实例已被反例击穿；不是说 C05 家族永远不能修。

| 要求 | 当前判定 | 归类 | 关键证据 |
|---|---|---|---|
| R-EPI-01 角色分离 | **HARD-FAIL** | C/X | case 被压成 numeric observations；无陈述、计算、推断、计划、实施动作 ADT（E02/E03）。 |
| R-EPI-02 禁止自证 | **HARD-FAIL** | C/X | diagnosis/outcome-derived hazard 作为 observation；无依赖图/支持守恒（E03/E06）。 |
| R-TIME-01 双时间 | **HARD-FAIL** | X | 只有 `day/snapshot_day`；active cases 无 known/report time（E05）。 |
| R-TIME-02 采集/记录/有效/过期 | **HARD-FAIL** | X | 无 expiry/recorded-at；nearest-to-snapshot 覆盖（E03/E05）。 |
| R-TIME-03 知识版本重放 | **HARD-FAIL** | X/C | registry 启动改写，version 恒 0（E10）。 |
| R-OBS-01 方法/条件/支持/可靠度 | **HARD-FAIL** | C/M | metadata 在 flatten 时丢弃，likelihood 只读 value/unit（E02/E11）。 |
| R-OBS-02 observation process 分离 | **HARD-FAIL** | C/M | state 明定为 observed-axis vector；无独立 emission channel（E02）。 |
| R-UNC-01 信息状态代数 | **HARD-FAIL** | C/X | conflict 覆盖；not observed 合成为 0.0（E03/E04）。 |
| R-UNC-02 多解释并存 | **PARTIAL** | M/X | 会保留全部 candidate scores，但无 typed hypothesis、未决条件、冲突/模型分歧对象。 |
| R-PROV-01 完整血缘 | **HARD-FAIL** | X | trace 无 evidence root、规则版本、known/valid time（E03）。 |
| R-PROV-02 同源去重 | **HARD-FAIL** | C/X | `_derived_from_axes` 不是 evidence-root identity；同轴覆盖而非根集合（E03）。 |
| R-PROV-03 递归撤回 | **HARD-FAIL** | X | 无 truth maintenance 或 retract API。 |
| R-INT-01 动作生命周期 | **HARD-FAIL** | X/M | policy 是模拟 tuple；病例里的计划/下单/执行/停止没有类型状态。 |
| R-INT-02 state/observation/parameter effects | **HARD-FAIL** | M/C/B | trajectory/push/sigma 有局部能力，但无 observation channel，且 treatment runtime 阻塞（E02/E09）。 |
| R-COMP-01 局部扩展 | **PARTIAL → HARD 未满足** | M/C | disease glob 是优势；active disease/drug 分支、全局 registry rebuild 破坏“核心修改数 0”保证（E10/E12）。 |
| R-COMP-02 非线性/门控/显式 unsupported | **HARD-FAIL** | M/C | 有 gate/saturation；但 combo 无声明时仍 sum，反向冲突取 dominant+5%，不返回 unresolved：`v5_joint_sde_case_test.py:10486-10496`。 |
| R-TASK-01 版本化只读投影 | **HARD-FAIL** | X/M | diagnosis/treatment 是两个脚本，不是同一事实账本上的 versioned projection；治疗直接用 expected label（E06/E09）。 |
| R-OPEN-01 开放世界拒绝 | **PARTIAL → HARD 未满足** | M/X | 有 health-reference delta；但仍总取 best disease，未输出 typed out-of-model/insufficient：`v5_joint_sde_case_test.py:11432-11444`。 |
| R-REP-01 历史确定性重放 | **HARD-FAIL** | X/C | 无 known cutoff/knowledge version，future case evidence 已进入 snapshot（E05/E10）。 |
| R-SAFE-01 typed error/quarantine | **HARD-FAIL** | X/C | invalid axis/edge 被跳过，未知单位原样返回（E11）。 |
| R-SAFE-02 安全 invariant 不靠检索 | **HARD-FAIL / UNSUPPORTED** | X | 没有安全规则引擎、适用域、确定执行 trace。 |
| R-ID-01 语义同构+原文保留 | **PARTIAL → HARD 未满足** | X/C | 有 axis alias/canonicalization bridge；但无版本化 adapter provenance，手工映射/字符串 token 控制语义。 |
| R-ID-02 临床关键状态不碰撞 | **HARD-FAIL** | C/M | oxygen/support、MAP/vasopressor、measurement method 没有绑定 observation（E02）。 |
| R-MIN-01 原语不可约性 | **HARD 未证明** | X | 当前没有 formal core spec 或逐原语不可约性；只有宽松 JSON 与大执行脚本。 |

## 4. ARCHITECTURE_TESTS.md 逐项预判

这是对当前代码/数据的**可执行前静态判定**，不是声称已经运行了冻结 test harness。由于共同 trace 契约完全缺失，即便某项数值能力存在，也只能记 `PARTIAL`，不能记端到端 `PASS`。

| Test | 当前判定 | 主要原因 |
|---|---|---|
| T01 MAP+vasopressor | FAIL (C/M) | MAP 观察与支持动作无绑定；无 observation channel（E02）。 |
| T02 SpO2+高流量氧 | FAIL (C/M) | method/support metadata 不进入 core observation（E02）。 |
| T03 退热药后正常体温 | FAIL (C/M) | treatment 只能 push/reshape axis，无外显 observation effect。 |
| T04 beta blocker/pacing | FAIL (C/M) | 没有设备/药物修饰后的 emission 对象；只能临时加 context axis。 |
| T05 抗菌药后培养阴性 | FAIL (C/M) | 无 treatment-modulated culture sensitivity；token filter 不是观察模型。 |
| T06 一次体温三种派生 | FAIL (C/X) | 无 evidence root；派生/代理 axis 只记 axis 依赖（E03）。 |
| T07 fever/CRP/WBC 共享来源 | PARTIAL | latent mechanism/covariance 可表达相关性，但没有根级独立性和完整 trace。 |
| T08 感染/非感染多解释 | PARTIAL | 所有 candidate 可并列评分；没有 typed hypothesis/unresolved object。 |
| T09 免疫抑制表现调制 | PARTIAL | risk axis/coupling modulation 已有；输入上下文/血缘/时间仍不合格。 |
| T10 冲突用氧记录 | FAIL (C/X) | 同 axis 选近者/最大者/较晚者，未保留 conflicting（E03）。 |
| T11 未提皮疹 | FAIL (C/X) | 普通未出现多半不打分，但 required context 明确从 missing 生成 0（E04）；无 not-asked 类型。 |
| T12 08:00采血/12:00可见 | FAIL (X) | 无 known-time；future example 已穿透（E05）。 |
| T13 最终诊断回放首诊 | FAIL (C/X) | applies_to、disease hazard、未来观察存在（E05/E06）。 |
| T14 相同肌酐不同个人 baseline | PARTIAL | background risk modifier 可调范围；没有 versioned individual baseline evidence 绑定。 |
| T15 诊断/用药安全视图 | FAIL (X/M) | 两脚本不是只读 task projection；治疗用 expected label。 |
| T16 CKD×肾清除药非线性 | FAIL (M/C) | 有局部 gate/saturation工具，但没有声明组合接口或 unknown-composition；默认组合启发式。 |
| T17 治疗双通道 effect | FAIL (M/C/B) | state/sigma 有，observation channel 无；treatment runtime 还 blocked。 |
| T18 自然病程 vs 治疗作用 | FAIL (X/M) | actual course 无 competing causal explanation；模拟模型选择被当既定。 |
| T19 旧 SpO2 过期 | FAIL (X) | 无 expires/valid interval。 |
| T20 模型外输入 | PARTIAL → HARD FAIL | health delta 存在，但总输出 best disease，无 typed refusal。 |
| T21 新药局部 effect | PARTIAL → HARD 未满足 | JSON treatment 可局部加入；drug token/lane/coverage 和 disease special-case 仍在 core（E12）。 |
| T22 新测量方法 | FAIL (C/X) | method 不进入 likelihood/trace；unknown unit/method 不 quarantine（E11）。 |
| T23 新理论重释旧证据 | FAIL (X/C) | 无 rule/ontology version；registry 会就地重建（E10）。 |
| T24 删除原始体温 | FAIL (X) | 无 evidence identity 和 truth maintenance。 |
| T25 任意历史点重放 | FAIL (X/C) | 无 known cutoff；cache/version 语义不全。 |
| T26 检索未召回禁忌 | FAIL/UNSUPPORTED (X) | 无 deterministic safety invariant engine。 |
| T27 两温度计 vs 三改写 | FAIL (C/X) | 0 个原始 evidence ids；axis map 无法表达根独立性。 |
| T28 两候选并存 | PARTIAL | score list 保留多候选；无 posterior calibration、反对/未知/未决条件 trace。 |
| T29 全新设备状态 | FAIL (C/X) | loader/normalizer 静默跳过或近似，不 typed quarantine（E11）。 |
| T30 等价自然语言 | PARTIAL → HARD 未满足 | 若 adapter 恰好给同 axis 可同构；adapter mapping/version/source 不在 core。 |
| T31 推断循环增信 | FAIL (X/C) | mechanism recursion 用 `seen` 截断并保留当前 activity，不报 illegal cycle/求 fixed point：`v5_joint_sde_case_test.py:9993-10038`。 |
| T32 晚到修订过去 | FAIL (X/C) | 没有 transaction/known-time version；同轴覆盖。 |
| T33 单位不兼容 | FAIL (C/X) | converter 未识别时原值通过（E11）。 |
| T34 两模块消费同证据 | FAIL (X) | 无 root-id union/idempotent lineage。 |
| T35 近似 posterior trace | FAIL (TRADEOFF contract) | header 有 seed/mode，但每个输出无 algorithm version、approximation/error boundary/source roots。 |
| T36 停用知识规则 | FAIL (X/C) | 规则无版本；旧知识 replay 不存在。 |
| T37 动作计划/下单/执行/拒绝/停止 | FAIL (X/M) | policy tuple/actual treatment narrative 不是 action-state machine。 |
| T38 模块接口不匹配 | FAIL/BLOCKED (B) | `build_corr` 5-vs-4 arity；只在执行时 TypeError，无 preflight validation（E09）。 |
| T39 不兼容概率模型 | FAIL (C/M) | `eval_axis` 先到先得；coupling 取绝对值较强者；无 model-disagreement record（E07）。 |
| T40 future cache 回放 | FAIL (X/C) | cache key 没有 known/valid cutoff 与 knowledge version；系统也无这些 cutoff。 |

## 5. 哪些是 C05 可支持但未实现，哪些需要改掉当前基本表示

### 5.1 C05 家族可自然承担，但当前 V5 尚未实现（`M`）

| 能力 | 合理的 C05 形式 | 当前 V5 缺口 |
|---|---|---|
| 状态/观察分离 | `x_{t+1}~f(x_t,u_t)`, `y_t~g(x_t,u_t,m_t,c_t)` | `x` 直接由 observed axes 组成；无独立 `g`。 |
| 序贯 belief | filtering posterior `p(x_t,theta,M | y_{≤t})` | snapshot endpoint likelihood；time series 取最近点。 |
| treatment 对 observation 的作用 | action 同时参数化 `f` 与 `g` | 只有 trajectory/push/sigma；无 culture sensitivity/measurement masking channel。 |
| 非线性共病 | local transition kernels、gates、saturation、interaction module | combo 默认关闭；打开后同向 sum，反向 dominant+5%，无 unsupported。 |
| 多峰 posterior | particles/mixture over states/models | 目前只保留未归一化 candidate log scores；diagnosis particles 不存在。 |
| closed-loop policy | POMDP belief update + policy/action observation loop | treatment 是 open-loop timed policy；不按随访反应分支。 |
| OOD generative comparison | explicit model class/unknown component + calibrated evidence | 只有 health delta，仍选 best known disease。 |

这些修复不会淘汰 C05 家族，但会淘汰“当前文件就是完整 SDE/POMDP runtime”的说法。

### 5.2 当前 V5 基本表示必须改变（`C`）

1. `axis_id -> one float` 必须改为可保留多来源、多状态、多时间的 typed observation/event collection；不能继续在 map 里覆盖冲突。
2. observed axis 不能同时充当 hidden physiological state 与 measurement；至少需要 latent-state variable 和 observation assertion 两种不同对象。
3. missing/unknown/conflicting/not-applicable/out-of-model 不能编码为 0/absence/probability float。
4. disease-specific hazard、诊断结果和 outcome 不能作为普通 presentation observation 回流打分。
5. candidate-specific virtual observations 不能改变观察空间维度；required context 缺失要进入显式 missingness/prior factor。
6. unit/method 不兼容不能继续“原值通过”；必须在输入边界 typed reject/quarantine。
7. mutable global registry 不能由 UI startup 就地重建并作为未版本化 runtime state。

### 5.3 C05 不应独自领取的能力（`X`）

以下能力可以包在一个完整系统里，但不是普通 SSM/SDE 数学原语自然给出的：

- 不可变 evidence identity、派生依赖集合、同源去重和递归撤回；
- valid time + known time + recorded/acquired/expires 的双时间/多时间事件账本；
- statement/inference/hypothesis/plan/order/executed action 的强类型角色；
- knowledge/rule/terminology version 与 as-known replay；
- conflict/unknown/not-applicable/out-of-model 信息状态代数；
- deterministic safety invariants；
- versioned task projection 与只读事实层。

若这些由 typed bitemporal event ledger + incremental truth maintenance/rewrite layer 提供，再把 C05 作为某个 projection 的连续概率动力学模块，这应记作 **C15 混合候选**；不能把 companion core 的贡献记为 C05 原生 pass。

## 6. Verification：可复查方法

### 6.1 核心 source checks

```powershell
git rev-parse HEAD
Get-FileHash REQUIREMENTS.md,ARCHITECTURE_TESTS.md,start_ui.py,\
  v5_joint_sde_case_test.py,v5_joint_sde_treatment_sim.py,master_axes.json -Algorithm SHA256

Select-String v5_joint_sde_case_test.py -Pattern '^def score_candidate|^def build_corr|^def mvn_logpdf|^def prepare_case_data'
Select-String v5_joint_sde_treatment_sim.py -Pattern 'joint.build_corr|^def simulate_policy'
Select-String start_ui.py -Pattern 'build_master_axes\(\)|def run_case_test'
```

### 6.2 treatment arity 的无依赖 AST 核验

```powershell
@'
import ast
from pathlib import Path
j = ast.parse(Path('v5_joint_sde_case_test.py').read_text(encoding='utf-8'))
t = ast.parse(Path('v5_joint_sde_treatment_sim.py').read_text(encoding='utf-8'))
for n in ast.walk(j):
    if isinstance(n, ast.FunctionDef) and n.name == 'build_corr':
        print(n.lineno, len(n.args.args), [a.arg for a in n.args.args])
for n in ast.walk(t):
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'build_corr':
        print(n.lineno, len(n.args))
'@ | py -3.10 -
```

当前输出：definition `10680 5 [...]`；call `1040 4`。

### 6.3 registry 只读等价重建原则

计数脚本严格复刻 `start_ui.py:101-150`：扫描 root `distillations/v5_*.json`，把 `latent_mechanisms` 规范为 axes，排除 `category == derived_hazard`，按 raw `axis_id` 去重；**不调用 `build_master_axes()`，不写文件**。得到 committed `10,662` vs rebuild `5,958`。

### 6.4 为什么没有执行现有 UI/全量 regression

- `start_ui.py` 启动必写 registry（E10），违反本子任务只读边界。
- 诊断 main 会写 `distillations/joint_sde_case_test_result.txt`：`v5_joint_sde_case_test.py:11749-11754`。
- treatment main 会写 `distillations/joint_sde_treatment_result.txt`：`v5_joint_sde_treatment_sim.py:1235-1238`，且在到达写出前已可由 AST 确定 arity failure。
- 仓库现存 result 文本自报的旧绝对路径、manifold/case count 与当前 184/458 不一致；按 `REQUIREMENTS.md` A-08，不用它们证明当前正确性。

## 7. Next Step：对主研究的建议

1. **淘汰当前 V5 作为“固定核心”的资格，但不要淘汰 C05 作为数值模块。** 在 CANDIDATES 评分中应记：隐藏状态/动态/干预 `H/P`，双时间/血缘/撤回/角色/安全需要 companion core。
2. **把现有 V5 atlas 和病例库降级为 untrusted fixtures。** 在参与架构原型评分前，至少隔离 `expected_*`、`applies_to`、disease-specific observation hazards、结局/治疗反应；为每条 evidence 增加 identity、valid time、known time、method/context/reliability。
3. **冻结一个最小 C05 adapter，而不是修大脚本排名。** Adapter 输入应是经过 typed evidence core 截断后的 observation events；输出必须满足 `ARCHITECTURE_TESTS.md:94-115` 的 trace contract。
4. **用最有判别力的测试先打 C05 原型**：T01/T02/T05（observation channel）、T12/T13（known time）、T16/T38/T39（composition/interface）、T20（OOD）、T24/T27/T34（evidence conservation）、T33（typed units）。
5. **若保留 SDE forward module，先做三项最低修复再谈数值结果**：修 `build_corr` 接口；统一所有 policy 的 state space 与 measure；把 observation channel 从 state transition 中拆出。之后再做可复现 smoke test和 frozen regression。
6. **不要用单病例 top-1 或旧 PASS 文本抵消上述 HARD failure。** 当前实例即使 ranking 准确率很高，也仍不满足固定核心资格；这是 `REQUIREMENTS.md:3-9, 61-74` 明确规定的判定逻辑。

## 8. 最终处置摘要

| 处置对象 | 建议 |
|---|---|
| 当前 `v5_joint_sde_case_test.py` | 作为 legacy snapshot Gaussian diagnostic baseline 保存；不得称 particle-filter/SDE fixed core。 |
| 当前 `v5_joint_sde_treatment_sim.py` | 标记 blocked；接口修复前不解释结果。修后仍仅算 forward dynamics prototype。 |
| disease/axis/risk/treatment JSON | 可作为待清洗医学参数资产；不能充当事实层或架构验证。 |
| `master_axes.json` | 视为未版本化 mutable derived registry；从固定核心中移出，启动不得隐式重建。 |
| C05 家族 | 保留为候选的连续动力学/不确定性计算组件；必须与 typed bitemporal evidence core 明确分层。 |
| 当前 V5 作为最终固定核心 | **淘汰当前实例**。 |

