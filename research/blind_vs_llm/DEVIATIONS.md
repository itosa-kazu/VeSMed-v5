# 偏离记录

冻结后发生的、与 PROTOCOL.md 字面不完全一致的事项。每条写明影响范围。

1. **「最新发表」的排序字段**（批次 C，leaf 13–18）：agent 按 Europe PMC `firstPublicationDate` 从新到旧审查，而不是 prompt 示例里的 `P_PDATE_D`（期刊卷期日期，只精确到月或年，会让连续出版期刊的新文排在后面）。与协议「找最新发表」的本意一致。影响：D-CAEBV 选了 PMC12963054（2026-02-20），按卷期日期会先遇到 PMC13294587（2025-10-23 电子发表）。
2. **抗 GBM 病例的就诊时点**（ANTI_GBM_ELDERLY_FEVER_CRESCENTIC_GN_PMC13474007）：正式入院时已接受激素、血浆置换和透析，agent 把 day 0 定在治疗前的肾功能检查，初诊发热和 CRP 记为 day -6。符合「首诊、治疗前证据」原则。
3. **共享临时目录的文件覆盖**：批次 C agent 曾把检索脚本 `epmc.py` 写进会话临时目录根部，可能覆盖了其他批次的同名临时脚本。只涉及检索辅助脚本，不涉及病例文件。
5. **LLM 提示词的送达方式**：协议写「禁止使用任何工具」。实际做法是：把 36 份提示词逐字复制到会话临时目录 `llm_in/`，文件名只用打乱后的标签（M01–M20 主分析，A01–A16 附录，对照表见 `llm/assignment.json`）；每个全新 agent 只被告知读这一个文件，然后不用任何工具直接作答。验证规则：该 agent 的工具调用次数必须恰好为 1（读这个文件），否则作废重跑并记录。提示词正文逐字不变。另外，subagent 会自动带上仓库的项目说明（AGENTS.md），其中有 atlas 病名清单，但没有任何测试病例的信息。
6. **LLM 使用的模型**：默认继承主会话模型（Claude Fable 5.1）。

4. **V5 病例读取程序的已知缺陷（不修，照原样测）**：批次 A、C 都报告，`tachypnea_presence` / `tachycardia_presence` 会被展开成 `respiratory_rate` / `heart_rate` 的数值或定性值，`fever_presence` 会附带展开成 `infection_trigger_activity`，`pulmonary_infiltrate_presence` 会自动展开出额外的影像轴。按协议，实验期间不改 runtime。各 agent 在结构化时尽量避开了前两个轴，这可能让 V5 少用了一部分定性生命体征信息。
