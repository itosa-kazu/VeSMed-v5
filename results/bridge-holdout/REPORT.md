# Evidence → model bridge 双实现 holdout 最终报告

> 裁决日期：2026-07-14
> 冻结实现层：**`HYPOTHESIS_FAIL`**
> Sealed 41-case corpus 层：**`HARNESS_INCOMPLETE`**（H01–H30 preregistered；H31–H41 post-seal/pre-execution addendum）
> 架构状态：**重新打开 Checkpoint 3/7**
> 机器摘要：[`final-report.json`](final-report.json)

## Outcome

本轮**没有证明** `K0-v0.1 + 分家子内核` 已拥有稳定、无损、可复用的
evidence→model bridge。两个冻结实现都存在不能由数值 solver 成功补偿的 hard failure：

- **Implementation A** 无法在允许的机械投影内同时保持 portable raw digest、SCM 每记录角色和
  smooth 的 effective-time cut；机械结果为
  `0 PASS / 0 CANDIDATE_FAIL / 4 ADAPTER_UNREPRESENTABLE / 37 HARNESS_INCOMPLETE`。
- **Implementation B** 的基础数值查询成立，但完整 executable-model round trip 未被 runner 审计；
  机械结果为 `0 PASS / 0 CANDIDATE_FAIL / 0 ADAPTER_UNREPRESENTABLE / 41 HARNESS_INCOMPLETE`。
  更重要的是，破坏性 M01 probe 证明 native semantics 改变后 recovery tape 仍可回显旧 canonical
  对象，形成执行与审计分裂。
- 42 个确定性 post-seal probe 合计 `15 pass / 26 fail / 1 partial`。A/B 都出现 target、cut、
  root/dependence、版本或更正语义失败；A 的三类不确定性 typed result 不完整，B 的 bridge 与
  evidence/record uncertainty sidecar 存在语义不活跃路径。

因此，本轮只能得出两层同时成立的结论：

1. **冻结实现层假说失败**：当前 A/B 不能作为稳定 bridge 的支持证据。
2. **完整 sealed 41-case hidden 实验未完成**：H01–H30 是原预注册集，H31–H41 是源码 seal 后、执行前加入的静态审计 addendum；冻结 corpus 的大量条目只是描述符，不是可执行 fixture；
   这不是候选通过，也不能把 post-seal probe 冒充 preregistered hidden case。

这不是“所有 K0-family 架构不可能”的定理。仍然保留 single evidence authority、typed
root/scope/time/cut/version、closed query、typed outcome 等需求；撤回的是“当前 bridge 边界已经被
双实现证明稳定”的说法。

## Key Evidence

### 1. 冻结与揭示顺序

两个 bridge candidate 与两个 public-panel source 先冻结，再生成 seed 和 hidden corpus：

| 对象 | SHA-256 |
|---|---|
| freeze manifest | `1eeddf4db162ae5c255e79d621785f912aa783382c794707cc46d8996b4ad6cb` |
| hidden corpus | `9ed638f0f6d5b5db688f40581b4bb659bb1b6df29e377048fa628b970944f309` |
| fixture manifest | `84d2a1feb7904414a7a5e905c4f49090b4dce16d4d8db0caf2c38015c2e96243` |
| Implementation A | `9acd79c967d05ca1dbeaf11e4238b3185d9e3e7e44c2fa478cb47a30ee554fff` |
| Implementation B | `dea8ad3d88fc1f626fe7121357da2278ae8095aff37847502a97e114db6d1cb0` |
| Panel A | `793e3cf8b9c1a851e7f45627f33880459b425d79fd3bd5aa0f24d62a537cab17` |
| Panel B | `da03a5333accb195202289af68a5269d7707137a90f99efbb8ba3aaaacd27ca1` |

静态 closure 审计显示四个冻结 source 都只 import Python 标准库，A/B/Panel A/Panel B 之间跨
import 为 0。它只支持同一环境中的 static source-distinct/no-cross-import lower bound，不是独立团队、第二机器或第二语言复现，也不证明动态语言不存在所有隐藏耦合。

### 2. H01–H41 机械结果及 corpus 缺口

| 实现 | PASS | CANDIDATE_FAIL | ADAPTER_UNREPRESENTABLE | HARNESS_INCOMPLETE | HARNESS_ERROR |
|---|---:|---:|---:|---:|---:|
| A audited run-01 | 0 | 0 | 4 | 37 | 0 |
| B corrected run-03 | 0 | 0 | 0 | 41 | 0 |

A/B 的分类向量有 `4/41 = 9.76%` 不同：A 将 H01/H02/H08/H16 判为 adapter 不可表示，B 将
它们与其余 case 一样保留为 harness incomplete。由于没有一个 hidden case 同时经由两边的无损、
允许投影并完成全量 round-trip audit，**A-vs-B hidden semantic disagreement rate 不可估计**。

[`EXECUTABILITY_AUDIT.md`](../../tests/bridge_holdout/EXECUTABILITY_AUDIT.md) 证明：

- 只有 H01/H02/H08/H16 指向具体 base 文档；
- 35 项是 mutation/oracle 描述符，没有 concrete mutated authority object；
- H09、H20、H21 还含 dangling query ref；
- H11 的 v2 registry、H13/H33/H37 的 delta graph、H27 的完整同构 copy、H29/H30 的组合
  fixture 均未物化。

冻结 corpus 保持不变，没有在看到候选结果后原地“修好”。未来完整运行必须采用新的 append-only
operational probe pack 和新 run ID。

### 3. 数值内核成立，但不能补偿 bridge hard failure

| 证据 | 查询 | observed | oracle | absolute error | 边界 |
|---|---|---:|---:|---:|---|
| A post-seal | DBN filter | 0.050186855352660854 | 0.050186855352660854 | 0 | 使用非许可 raw envelope/clock conversion，只是诊断 |
| A post-seal | DBN smooth | 0.13924855699357053 | 0.13924855699357053 | 0 | 同上 |
| B partial H01/H08 | DBN filter/smooth | 同上 | 同上 | 0 / 0 | full model round-trip audit 缺失 |
| B post-seal | condition(T=1) | 0.603448275862069 | 0.603448275862069 | 0 | external probe |
| B post-seal | condition(T=0) | 0.4222222222222222 | 0.4222222222222222 | 0 | external derived query |
| B post-seal | do(T=0) | 0.6310679611650486 | 0.6310679611650486 | 0 | external probe |
| B post-seal | do(T=1) | 0.4660194174757281 | 0.46601941747572817 | 5.55e-17 | external derived query |
| B post-seal | AAP | 0.8285714285714286 | 0.8285714285714286 | 0 | external probe |
| B post-seal | uncertainty control | 0.050186855352660854 | 0.050186855352660854 | 0 | external probe |
| B post-seal | aleatoric perturbation | 0.06335492081995274 | 0.06335492081995273 | 1.39e-17 | external probe |
| B post-seal | epistemic perturbation | 0.049525682855158015 | 0.049525682855158015 | 0 | external probe |
| B post-seal | measurement perturbation | 0.05867432043181066 | 0.05867432043181066 | 0 | external probe |

上述 B 四行 uncertainty 数值证明的是 **model-level** aleatoric/epistemic/measurement 参数扰动会改变 solver 输出；它不证明 evidence/record uncertainty sidecar 已进入执行路径。

两套 source-distinct、无跨 import 的 public panel 在 separate process 中均匹配 E01–E06 external reference，且 solver 对参数变化
有响应。Panel A 正确拒绝非法 `resample_exogenous` policy；Panel B 错误接受，所以 Panel B 的失败是
**policy fail-closed**，不是把其 E03 AAP 数值算法误称为 resampling。

### 4. 决定性 post-seal 反证

确定性红队报告为
[`redteam-external-probes.json`](redteam-external-probes.json)，SHA-256
`ebeab68e4bdda4abaf0e3f597f6cb32a08cce044109d2247f9ba1b62e6c8156a`。

**A：**

- target native model 对执行是 live，evidence derivation guard 生效；
- 但未执行的 other-kernel model 可改变 recovery/digest 而不影响当前 typed execution，M01 只能
  `PARTIAL / NOT_KILLED`；
- target binding、target window、same-root/dependence family、post-cut correction、
  self-supersedes、encounter scope、absent/censored、causal namespace、empty dependence family 和
  version behavior 均有失败；
- result 没有分别报告 aleatoric、epistemic、measurement 三个 typed channel。

**B：**

- native model mutation 会改变执行，但 recovery tape 仍恢复旧 canonical/digest，是 M01 决定性失败；
- bridge semantic liveness、rootless execution、root version、target/cut、same-root/dependence、
  post-cut correction、scope、causal namespace、empty dependence family、version binding 和
  **evidence/record uncertainty sidecar liveness** 均有失败；这与上一节 model-level 三通道参数扰动为 live 不矛盾；
- correction/retraction 的**数值** incremental 与 clean rebuild 相等，但 active-root authority 和
  executable audit 不相等：相关 probe 有 3 个 hard assertion 失败。

### 5. Mutation gate 的正确证据地位

`prototype/bridge_mutation_gate.py` 的 self-test 能拒绝 12 个合成的**报告变异**。这证明 report
predicate 对已知伪造敏感，不证明 A/B 已杀死 M01–M12。

- candidate runner 真正执行并裁决的 hard mutation 只有 M01；A/B 均 `NOT_KILLED`。
- M02–M12 在 A/B runner 的正式 mutation matrix 中都是 `NOT_EXECUTED_BY_CANDIDATE_RUNNER`。
- post-seal redteam 对其中若干语义给出额外反证或正向 control，但它们仍是 external evidence，不能
  改写为 hidden mutation kill rate。

### 6. 规模、承诺、延迟与 blast radius

| 范围 | bytes | physical lines | strict LOC |
|---|---:|---:|---:|
| 四个冻结实现/Panel 源码 | 244,694 | 5,609 | 4,768 |
| 两个外部 runner | 132,402 | 2,727 | 2,454 |
| 六文件合计 | 377,096 | 8,336 | 7,222 |

strict LOC 使用 tokenize 口径，排除 comment、空结构 token 与 module/class/function docstring；LOC
不是跨语义能力总分。

- A：1 个允许的 product-state 投影族；另有 2 个非许可、仅诊断 conversion（raw envelope、
  effective-time→availability-time）。
- B：4 个 closed transform family；3 个 likelihood instance、1 个 identification assumption、
  1 个 shared-world policy。不同计量单位不能压成一个“复杂度分数”。
- A 为保证结果逐字节 replay，主动不记录 runtime telemetry。
- B 的 4 compile、4 recover、7 run 样本给出约 0.80/0.93 ms compile p50/p95、
  0.48/0.54 ms recover、0.11/0.15 ms run；报告已标 `adequate_for_stable_p95=false`。
- `eca17d3..abac087` 共 14 commits、32 个实验专用新增文件、12,101 insertions、0 deletions；
  core runtime 修改 0、schema migration 0、候选 seal 后修改 0。

预注册 required report vector 也有明确缺项，不能用上述总 LOC 代替：A/B runner 都把 adapter、oracle
与 probes 交织在同一文件，且没有预冻结的 adapter-only 切片规则，所以 adapter non-comment LOC 均记
`null + reason`；B 的 `1745` 只作为 full-runner physical-line 诊断值。A 的 manual mapping/unit/clock/
likelihood/identification/shared-world 计数未单独仪器化，B 的 manual-mapping 数也不可从四个 transform
family 中无歧义拆出。A 为 exact-byte replay 未记录 compile/recover/run latency，且没有可计算完整
incremental-vs-clean mismatch count。上述缺口均在 `final-report.json` 逐字段表示为 `null + reason`，
所以本轮不能声称 required vector 已完整测量。

## Verification

### 可复查产物

| 产物 | SHA-256 |
|---|---|
| A runner | `8b78e17f16fcd84b561d83cffc09cbe7c2835d53874f06415818f25317130c82` |
| A audited report | `e6a2fe0db7dfbeaf38ac04b08fc116c66aa0a8ef40df0808d52ac035f8e89d4b` |
| B runner | `1993bd1bc3051057763adaec21f8c946fae1a8a469be52c78ec026c313ceeb78` |
| B corrected run-03 | `211c0fd0b499c61de05c71b66b7756a726ef955b541c4986330eaee23d288b2c` |
| redteam runner | `bd4e20f735d6f29952988490fad340ffed62f08f993468ce28a3370b560eaef7` |
| final machine report | 见 [`final-report.json.sha256`](final-report.json.sha256) |

B 的运行历史不是完整 WORM：run-02 和 run-03 已保留并由 parent hash 相连；最早未提交的 dry-run
artifact 已丢失，只保留 SHA
`d92cd05b2e9c0ef68380c691c1d64dfb439747dc5d8b3bc9e7664ea592e5412a`。不能把它写成完整
append-only 历史。

Git 中的逻辑实验工件检查点是 `abac08786f642c28ba76d8940c60fe1906ab9945`。随后
`d08a8e5b12377890499703b6de6bed1f90c4aa98` 只加入 `.gitattributes` 与证据 blob 的 exact-byte
packaging，不改变实验语义；`final-report.json` 中声明的 26 个决策依赖工件均已从该 packaging
checkpoint 通过 Git blob 字节数与 SHA-256 复核。最终报告、claim-boundary 测试与决策文档在这两个
检查点之后提交。

### 重放命令

```powershell
python tests/bridge_holdout/runner_a_external.py `
  --output "$env:TEMP/implementation-a-audited-replay.json"

python tests/bridge_holdout/runner_b_external.py `
  --output "$env:TEMP/implementation-b-audited-replay.json"

python tests/bridge_holdout/redteam_external_probes.py `
  --output "$env:TEMP/redteam-external-probes.json"

python -m pytest -q `
  tests/test_bridge_public_panels.py `
  tests/test_bridge_mutation_gate.py `
  tests/test_bridge_holdout_fixture.py `
  tests/test_bridge_holdout_runs.py
```

A report 与 redteam report 支持 exact-byte replay；B 因保存 timing telemetry，不支持逐字节重放，但
自动测试会递归剔除 `*_ns`/latency 与派生 report-byte 字段后比较完整结构，验证其余语义字段完全一致。

2026-07-14 在当前工作树执行上述四个 bridge 测试文件，最终复跑结果为 `16 passed in 25.13s`；随后执行
`python -m pytest -q`，最终复跑结果为 `135 passed, 7 subtests passed in 44.63s`。测试通过只证明工件完整性、
回放与 claim-boundary 断言成立，不会把 `HARNESS_INCOMPLETE` 改写成 holdout 完成。

## Next Step

1. **保留本轮证据，不修冻结候选。** 任何 A/B 修复都必须成为新 candidate seal 和新 run。
2. **重新打开 Checkpoint 3/7。** K0 的 invariant requirements 保留；“稳定 bridge 已建立”的架构
   选择撤回。
3. **先冻结 operational probe pack，再写新实现。** 新一轮每项必须包含完整 portable input、
   concrete mutation、machine predicate、独立 oracle、允许 lowering 和 negative typed outcome。
4. **把本轮暴露的语义升级为候选级一等对象。** 至少包括 raw-byte identity、per-record role、
   effective/availability/transaction clocks、per-kernel model/version binding、query inverse、三类
   uncertainty product 和 materialized/consumed source mapping。
5. **并行比较三个架构方向，而不是只补当前 adapter：** richer typed bridge calculus、统一的 typed
   event/probabilistic/causal calculus、以及只承诺 evidence authority 而不承诺跨核 round-trip 的更窄
   control plane。

只有新的、完整物化的双实现 holdout 同时通过 hard gates，才可以再次冻结固定核心选择；即使通过，
仍只增加本 context-of-use 的架构支持，不构成临床认证。
