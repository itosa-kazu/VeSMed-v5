# 新临床动态地图：两个复杂真实病例全流程实验结论

## Outcome

本实验严格独立于 VeSMed V5。两个真实病例共 16 个信息切片均可由同一份
递归、可序列化共享状态完成回放；时间可见性、查询状态一致性和 fresh-process
递归闭包全部通过。但是，当前最小实现的**临床读出失败**：疾病机制定位、模式
切换、并发过程表达、开放世界不确定性和动作选择均未达到病例所要求的能力。

机器终态：

```text
STRUCTURALLY_CASE_CONSISTENT_BUT_CLINICAL_READOUT_FAILED
```

因此：

- 聊天提出的架构作为候选架构没有被逻辑推翻；
- “当前最小实现已经实现该架构，并能处理复杂病例”这一主张被推翻；
- 当前证据不支持存在一个已知、唯一、有限、永久封闭的全医学理想模型；
- 在冻结的动作、检查、时间范围、结局和容差内，仍可抽象定义任务相对的理想
  行为等价状态。

## Key Evidence

### 1. 结构合同

- 两病例事件账本：109 个原始事件，16 个顺序信息切片。
- 每个切片的 diagnosis、自然 rollout、全部动作 rollout、plan 均消费完全相同的
  `state_hash`。
- 每次增量更新在 fresh process 中由序列化父状态恢复后，得到完全相同的子状态。
- 冷启动全量重放与递归增量更新在语义状态上相同。
- 未来才可用的结果不会改变早期状态。
- 自动测试 19/19 通过；其中 12 项为共享状态/时间/消融合同，7 项为独立
  synthetic shadow-world 局部细化实验。

这些结果只证明工程骨架可运行，不证明临床推断正确。

### 2. PMC10448002：TMA 诊断反转病例

映射进入模型的 rankable observations 为 23/39（59.0%）。最终切片：

```text
B_TTP             47.57%
B_COMPLEMENT_TMA  34.04%
B_ANTI_GBM         6.55%
B_HIT              5.00%
```

病例后续证据支持 complement-mediated TMA，但模型直到出院仍把 TTP 排第一。
入院时还把模式判为 `recovering`。六个切片的计划动作始终是
`A_CONTINUE_EXISTING_SUPPORT`。

决定性原因不是“参数稍微不准”，而是当前推断只会把 observations 变成正向
severity 分数：保留的 ADAMTS13 活性不能作为反驳 TTP 的负 likelihood；共同的
溶血/血小板证据反而持续给 TTP 加分。活检后血肿、TMA、HIT 待排等并发过程也
被强制压进一个互斥 branch simplex，而不是同时保持多个 active processes。

### 3. PMC7005653：HAV 肝衰竭并发 Takotsubo/休克

映射进入模型的 rankable observations 为 21/52（40.4%）。到心脏检查切片：

```text
acute_coronary_syndrome  21.08%
acute_myocarditis        21.08%
takotsubo_syndrome       21.08%
```

到休克后，三者仍完全并列，各 25.94%。模型无法利用正常冠脉、特定室壁运动模式
和后续快速可逆性把 Takotsubo 从 ACS/myocarditis 中分开。拔管和转普通病房后，
模式仍是 `strained`；十个切片的计划动作始终是 `CirculatorySupport`。

该病例同时存在肝衰竭、心肌功能障碍和休克，且各器官可处于不同模式。当前实现
只有一个互斥 branch posterior 和一个全局 mode，因而从状态类型上就不能完整
表示病例。

### 4. 开放世界与动作失败

- TMA 病例 record-only/unmapped 比例 41.0%；HAV 病例为 59.6%。
- 两病例 `unknown_mass` 却始终固定为 0.05，显示当前 unknown/OOD 机制没有把
  模型覆盖缺口转成不确定性。
- 动作选择在 6/6 和 10/10 个切片中分别完全不变。
- 当前动作转移是固定 mode drift 加文本关键词常数，不是真正的 branch/mode/
  action-conditioned dynamics；不能由病例识别个体治疗反事实。

### 5. 局部细化 shadow world

在独立有限合成世界里：旧动作集合下两个亚型可安全合并；加入新治疗后，同一旧
状态出现 `+6` 与 `-10` 的相反响应，形成精确状态碰撞。新检查可用后只拆相关
局部状态，平均 oracle regret 从 3.0 降到 0.0，旧查询和无关分层不退化。若新
亚型无任何可观察区分信息，系统返回 `SCOPE_INSUFFICIENT_UNIDENTIFIABLE`。

这证明局部细化原则在有限世界里可执行；它不证明真实临床状态总能找到可观察
拆分轴。

## Verification

复现：

```powershell
$env:PYTHONPATH=(Resolve-Path research\new_clinical_framework_case_study)
python research\new_clinical_framework_case_study\run_experiments.py
python -m unittest discover -s research\new_clinical_framework_case_study\tests -v
```

实际结果：

```text
overall_status = STRUCTURALLY_CASE_CONSISTENT_BUT_CLINICAL_READOUT_FAILED
19 tests passed
```

关键证据：

- `evidence/real_case_results.json`
- `evidence/refinement_results.json`
- `runtime_concept_map.json`
- `REAL_CASE_REPORT_CN.md`
- `AUDIT_FRAMEWORK.md`

## Next Step

下一轮不能靠微调 branch 权重来修。必须先补齐以下结构：

1. 把互斥 branch simplex 改成可并发的 active-process set/factorial posterior；
2. 把单一 global mode 改为 branch/organ-local mode，并实现 guard 与 hysteresis；
3. 用声明式、带方向的 emission likelihood 取代 severity 加分，使可靠阴性证据
   能反驳 branch；
4. 将分支几何真正接入 posterior、邻近检索或 planning，而不是只保留独立距离
   函数；
5. 实现动作的 start/continue/stop、剂量、持续、洗脱、支持掩盖和 branch-specific
   transition；
6. 让 record-only/unmapped 与模型失配进入可审计的 OOD/unknown posterior；
7. 将 shadow-world 的 local refinement 流程接入同一个 runtime，包含 state
   migration、new-check factor、child posterior 和旧查询 non-regression。

修复后的两个病例只能作为开发回归；为了防止迎合病例，还必须再找独立 holdout
复杂病例进行盲回放。
