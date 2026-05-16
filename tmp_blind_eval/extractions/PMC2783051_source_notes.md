# PMC2783051 Blind Source Notes

Source read: PMC full text at https://pmc.ncbi.nlm.nih.gov/articles/PMC2783051/ and PMC OAI/JATS XML.

Identifiers:
- PMCID: PMC2783051
- PMID: 19946588
- DOI: 10.1186/1752-1947-3-110
- Journal: Journal of Medical Case Reports
- Publication date: 2009-11-09

Blind boundary:
- I did not inspect local distillations, local case JSONs, prior ranking outputs, held-out labels, disease files, or local axis registries.
- Rankable extraction uses only diagnosis-neutral observed facts from the case presentation and Table 1.
- The article title and author diagnostic wording reveal disease framing, so they are preserved only as metadata or `record_only`.
- Treatment, death, autopsy, later viral sequencing/genotype interpretation, and discussion interpretation are `record_only` with `use_in_ranking: false`.

Rankable evidence used:
- Demographics: 26-year-old Caucasian man.
- Symptoms at referral/admission: jaundice, general fatigue, anorexia.
- Exposure history: patient denied intravenous drug use, surgery, tattoos, and piercing.
- Admission labs: platelet count 139 x 10^9/L, prothrombin time 34.4 seconds, CD4 12 cells/uL, CD8 323 cells/uL, CD4/CD8 ratio 0.04, total bilirubin 1.56 mg/dL, direct bilirubin 0.60 mg/dL, AST 2037 IU/L, ALT 2317 IU/L, LDH 1395 IU/L, alkaline phosphatase 180 IU/L.
- Admission imaging: abdominal sonography showed hepatomegaly, heterogeneous liver structure, and normal biliary tree.
- Admission microbiology/serology: HBsAg positive, HBeAg positive, anti-HBc IgM weakly positive, anti-HBeAb negative, HBsAb negative, HBV-DNA 1.5 x 10^9 copies/mL, acute HAV/HDV/CMV/EBV markers negative, anti-HCV antibody negative, HCV RNA negative, HIV antibody positive, HIV Western blot positive, HIV-RNA 3.6 x 10^5 copies/mL.
- Pre-treatment deterioration before/at author diagnostic snapshot: total bilirubin 12 mg/dL, ALT 3378 IU/L, AST 4235 IU/L, deteriorated consciousness, and prolonged coagulation time.

Data-quality notes:
- The article does not report vital signs.
- Later coagulation prolongation is qualitative only; the only numeric coagulation value is admission prothrombin time 34.4 seconds.
- The anti-HBc IgG admission result is inconsistent: narrative says weakly positive, while Table 1 lists admission HBcAb IgG as negative. I kept this conflict in `record_only` and did not make it rankable.
- The PMC-rendered Table 1 has duplicated HBsAg/HBsAb labels. I used the narrative case text to disambiguate HBeAg positivity and anti-HBeAb negativity.
