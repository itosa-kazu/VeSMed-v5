# PMC6388855 Blind Source Notes

## Source Identifiers

- PMCID: PMC6388855
- PMID: 30820375
- DOI: 10.7759/cureus.3755
- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC6388855/
- PDF URL from PMC metadata: https://pmc.ncbi.nlm.nih.gov/articles/PMC6388855/pdf/cureus-0010-00000003755.pdf
- Citation metadata: Cureus. 2018;10(12):e3755

## Access Notes

- The PMC article HTML and OA metadata were accessible by direct request from the source URL.
- The browser-facing open attempt showed a PMC access-protection page, so extraction used the source page content returned by direct machine request and the PMC OA metadata endpoint.
- I did not read local distillations, local cases, ranking result files, or previous blind extraction JSON files.

## Rankable Case Chronology Paraphrase

- Single case, 25-year-old male patient.
- Remote history: successfully treated primary syphilis.
- Presented after several days of acute illness with back pain, headache, diarrhea, and vomiting; symptoms had not improved with ibuprofen.
- Initial examination: fever 38.5 C, heart rate 123/min, blood pressure 130/78 mmHg, moderate distress, no motor weakness or sensory deficit, normal abdominal exam without organomegaly or tenderness, normal precordial and lung examinations.
- Initial labs: leukocytes 3,900/uL, hemoglobin 17.6 g/dL, creatinine 1.76 mg/dL, AST 49 U/L, ALT 30 U/L, total bilirubin 0.31 mg/dL.
- Relevant risk context from case history: monogamous relationship with an HIV-positive male partner, unprotected anal intercourse, prior PrEP declined.
- Initial fourth-generation HIV antigen/antibody screen was negative.
- Hospital course before final diagnostic framing: recurrent fever with reported peak 39.3 C on hospital day 3; day 2 labs showed AST 200 U/L, ALT 137 U/L, INR 1.45, PTT 62.4 seconds; bilirubin and alkaline phosphatase remained normal; text reports transaminases continued rising through the first five hospitalization days.
- Infectious workup was negative for HAV IgM, HBsAg, HBeAg, HBc IgM, anti-HCV antibody, HCV RNA PCR, HEV IgM, HSV 1/2 DNA PCR, EBV IgM, and CMV IgM.
- Liver ultrasound was normal.
- Noninfectious workup was negative/normal for ANA, anti-smooth-muscle antibody, anti-mitochondrial antibody, anti-LKM-1, alpha-1 antitrypsin 159 mg/dL, ceruloplasmin 226 mg/L, and C282Y genotype; ferritin was >7,500 ng/mL.
- Virologic and lymphocyte subset testing in the case chronology showed HIV-1 RNA >10,000,000 copies/mL, CD4 count 689/uL, CD8 count 506/uL, CD4 28%, and CD8 21%.

## Record-Only Exclusions

- Blood cultures were obtained, but the case text did not provide a result.
- A single dose of vancomycin, cefepime, and metronidazole was given; this was recorded as treatment only.
- Antibiotics were discontinued on hospital day 2; this was treated as a management decision, not rankable evidence.
- Resolution of diarrhea and back pain during admission was excluded from ranking to avoid course/treatment leakage.
- Antiviral combination therapy with emtricitabine, tenofovir alafenamide, and dolutegravir was started after diagnostic virology and is record-only.
- Discharge, follow-up plans, one-week and one-month lab improvement, CD4 recovery, viral-load decline, final diagnostic wording, and discussion-level causal interpretation were kept out of ranking.

## Axis Naming Notes

- I used diagnosis-neutral observed axes only; no `*_in_D-*` ordinary observation axes were created.
- Potential registry-alignment uncertainty: local master axis names were intentionally not read. The axes `hiv_4th_generation_antigen_antibody_test_positive`, `hiv1_rna_copies_per_mL`, `hiv_positive_sexual_partner_presence`, and several viral/autoimmune serology booleans may need later normalization against `master_axes.json`.
- The transaminase figure was not numerically digitized; the JSON includes the exact text-reported AST/ALT values and a qualitative rising-trend observation from the case text.
