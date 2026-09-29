# 结果：V5 vs 直接问 LLM（盲测，2026-09-29）

协议见 `PROTOCOL.md`（冻结指纹 `frozen/FREEZE_SHA256.txt`），偏离见 `DEVIATIONS.md`，病例审计见 `AUDIT.md`。

## 预注册结论（主分析 10 例）

**「只是更爱拒答，不算价值」**（PROTOCOL.md 第 8 节第 2 条）。

| 指标 | V5 原样（S0） | V5 + 拟合检查（S1） | LLM（L） |
|---|---|---|---|
| 名单有答案：排第一 | 2/10 | 同左 | 8/10 |
| 名单有答案：排前三 / 前十 | 2/10 / 3/10 | 同左 | 9/10 / 9/10 |
| 名单有答案却说「都不像」（误拒答） | 0/10 | 9/10 | 1/10 |
| 答案被拿掉时说「都不像」（正确拒答） | 0/10 | 9/10 | 5/10 |

S1 在两种情况下几乎全部拒答，因为在新病例上连正确疾病的拟合值也远超界线（τ=25.3）。它分不出「答案在名单里」和「答案不在名单里」。

## 附录与合计

| 指标 | 附录 8 例：V5 / LLM | 全部 18 例：V5 / LLM |
|---|---|---|
| 排第一 | 2/8 / 6/8 | 4/18 / 14/18 |
| 排前三 | 4/8 / 8/8 | 6/18 / 17/18 |
| 误拒答（S1 / L） | 8/8 / 0/8 | 17/18 / 1/18 |
| 正确拒答（S0 / S1 / L） | 0 / 8 / 6（共 8 例） | 0 / 17 / 11（共 18 例） |

## 主分析逐例

| 正确诊断 | V5 名次 | V5 第一名 | LLM 第一名 |
|---|---|---|---|
| 血球貪食性リンパ組織球症 / HLH-MAS / `D-HLH-MAS` | 17 | 内臓リーシュマニア症 / Visceral leishmaniasis / `D-LEISHMANIASIS-VISCERAL` | 正确 |
| 西ナイル神経侵襲性疾患 / West Nile neuroinvasive disease / `D-WEST-NILE-NEUROINVASIVE-DISEASE` | 112 | 急性A型肝炎 / Acute hepatitis A / `D-ACUTE-HEPATITIS-A` | Legionella 肺炎（错，且前十无正确答案） |
| 細菌性敗血症 / Bacterial sepsis / `D-SEPSIS-GN` | 30 | 再発性多発軟骨炎 / Relapsing polychondritis / `D-RELAPSING-POLYCHONDRITIS` | 细菌性脑膜炎（正确答案第 3） |
| 播種性血管内凝固 / DIC / `D-DIC` | 23 | 髄膜炎菌血症 / Meningococcemia / `D-MENINGOCOCCEMIA` | 正确 |
| サリチル酸中毒 / Salicylate toxicity / `D-SALICYLATE-TOXICITY` | **1** | 正确 | 正确 |
| 毒素性ショック症候群 / Toxic shock syndrome / `D-TOXIC-SHOCK-SYNDROME` | 31 | アメーバ性肝膿瘍 / Amoebic liver abscess / `D-AMOEBIC-LIVER-ABSCESS` | 正确 |
| Q熱 / Q fever / `D-Q-FEVER` | 60 | 播種性ヒストプラスマ症 / Disseminated histoplasmosis / `D-HISTOPLASMOSIS-DISSEMINATED` | 正确 |
| 志賀毒素関連溶血性尿毒症症候群 / STEC-HUS / `D-STEC-HUS` | **1** | 正确 | 正确 |
| 第2期梅毒 / Secondary syphilis / `D-SECONDARY-SYPHILIS` | 76 | 播種性ヒストプラスマ症 / Disseminated histoplasmosis / `D-HISTOPLASMOSIS-DISSEMINATED` | 正确 |
| IgG4関連疾患 / IgG4-related disease / `D-IGG4-RELATED-DISEASE` | 6 | 急性胆嚢炎 / Acute cholecystitis / `D-ACUTE-CHOLECYSTITIS` | 正确（但同时说「都不像」，倾向胰腺癌） |

LLM 在答案被拿掉时没有拒答的 5 例里，挑的多是临床近邻（HLH→内脏利什曼病并在自由文本里写了 HLH；TSS→化脓性链球菌菌血症；IgG4→急性胰腺炎），真正离谱的是西尼罗病例（两种情况都答 Legionella）。

## 探索性分析：V5 为什么在新病例上掉分（事后分析，不改变结论）

`diagnose_coverage.py`：只给正确疾病打分，看病例里参与打分的轴有多少是正确疾病自己的轴、多少退回背景。

| | 正确疾病自己解释的轴（中位比例） | 这些轴的平均偏差 z² | 退回背景的轴的平均偏差 z² |
|---|---|---|---|
| 旧病例 455 例 | 0.90 | 4.0 | 36.1 |
| 新病例 18 例 | 0.38 | 6.5 | 90.3 |

- 正确疾病自己的轴，在新病例上拟合得和旧病例差不多。
- 新病例的大部分观察（62%）不在正确疾病的轴名里，只能退回背景。一个「存在」的发现落到期望「不存在」的背景上，固定得到 z≈12.2，相当于每条约 74 个对数单位的罚分，几条就能压过全部正确证据。
- 这些「不认识」多数是同义命名：`*_presence` / `*_activity` / `*_severity` 等变体并存，注册表有 6341 个可观察轴。旧病例和疾病文件是在修地形时一起改出来的，说的是同一套方言，所以覆盖率 90%；独立结构化的新病例只有 38%。
- 因此，旧病例上的 94.5% 很大一部分来自「病例和地形一起长大」，不是几何在新病人身上的泛化能力。

## 这次实验没有测到的东西

- SDE / 病程 / 治疗部分完全没有被测到：失败发生在更前面，也就是把病例翻译成模型语言的那一步。
- n=10（主）/ 18（全部），只能看方向。
- LLM 与病例结构化 agent 是同一模型家族；LLM 可能见过部分 2025–2026 病例（已尽量选最新发表的病例来降低这种可能）。
- 拟合检查的界线来自旧病例，偏严（协议里已预先声明）。
