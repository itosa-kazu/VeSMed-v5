# PMC8916920 Blind Source Notes

## Source Access

- Primary source URL requested: `https://pmc.ncbi.nlm.nih.gov/articles/PMC8916920/`
- PMC browser page required a browser check, so the same PMC article full text was accessed through NCBI E-utilities JATS XML:
  `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=8916920&retmode=xml`
- Source identifiers found in the XML metadata:
  - PMCID: `PMC8916920`
  - PMCID version: `PMC8916920.1`
  - PMID: `35295364`
  - DOI: `10.7759/cureus.22055`
  - Journal: `Cureus`
  - Article type: `case-report`
  - Publication date: `2022-02-09`

## Blind Extraction Boundary

- Used for rankable extraction: case presentation, Table 1 admission laboratory data, and raw objective inpatient diagnostic tests/course values.
- Not used as rankable disease evidence: article title, abstract, discussion interpretation, conclusion framing, treatments/procedures, treatment response, and late recovery outcome.
- A known named childhood-onset muscle disease appears in the case presentation as past history. In the JSON this was generalized to `known_metabolic_muscle_disease_history` so the rankable field does not repeat a disease label from the article title or final framing.
- No expected-label field or final diagnosis field was written.

## Extracted Rankable Clinical Evidence

- Demographics: 21-year-old woman.
- Baseline risk context: known metabolic muscle disease history, exercise intolerance, fatigue, recurrent myalgias, recurrent rhabdomyolysis, no prior renal impairment, allergic history, bronchial hyperreactivity, depression, current fluoxetine, newly started clonazepam and agomelatine, long-term combined oral contraceptive, recent prior rhabdomyolysis episode with full recovery.
- Initial presentation: five loss-of-consciousness episodes preceded by nausea, dizziness, and palpitations; one episode with lower-limb clonic movements; no sphincter incontinence; no post-event confusion; several weeks of myalgias without associated trauma or physical effort.
- Vitals at ED presentation: BP 98/54 mmHg, HR 70 bpm, oxygen saturation 99%, temperature 36.5 C, afebrile.
- Admission labs: creatinine 1.76 mg/dL, CK >40000 U/L, myoglobin >4144 ng/mL, AST 1216 IU/L, ALT 288 U/L, LDH 5343 U/L, hemoglobin 17.3 g/dL, leukocytes 11540/uL, platelets 144000/uL, sodium 137 mmol/L, potassium 4.8 mmol/L, chloride 102 mmol/L, calcium 3.8 mEq/L, phosphorus 6.1 mg/dL, magnesium 2.6 mg/dL, urea 45 mg/dL, glucose 116 mg/dL, bilirubin 0.6 mg/dL, GGT 9 IU/L, alkaline phosphatase 55 IU/L, CRP 17.5 mg/L.
- Urinalysis and tests: hemoglobinuria present; leukocyturia and nitrituria absent; SARS-CoV-2 screen negative; ECG normal sinus rhythm; cranial CT and renal ultrasound without abnormalities.
- Early course: anuria and metabolic acidosis with pH 7.31, pCO2 32 mmHg, bicarbonate 16 mmol/L, lactate 0.5 mmol/L; creatinine rose to 4.73 mg/dL at 24 hours and 5.71 mg/dL at 48 hours; CK 93692 U/L at 48 hours; myoglobin remained >4144 ng/mL; AST 818 U/L, ALT 253 U/L, LDH 2163 U/L; severe hypervolemia; later peak creatinine 8.93 mg/dL.
- Additional diagnostic screening: ANA, anti-dsDNA, anti-ENA, ANCA, and anti-GBM negative; no complement consumption; serum protein electrophoresis normal.

## Record-Only Exclusions

- Intensive IV fluids, suspension of recent medications, aggressive diuretic stimulation, central venous catheter placement, and hemodialysis were stored as `record_only` and `use_in_ranking=false`.
- No response to diuretic stimulation, recovery of diuresis on day six, discharge labs, asymptomatic discharge status, and two-week post-discharge creatinine were stored as late course/outcome record-only information.
- Discussion-level causal claims and final diagnostic framing were not converted into observations.

## Axis Naming Uncertainty

- I did not read `master_axes.json` or existing blind extraction files, so axis IDs are conservative generic names and may need mapping to the project registry later.
- Potential registry aliases to check later: `serum_creatine_kinase` versus `creatine_kinase`, `blood_urea` versus `blood_urea_nitrogen`, `oxygen_saturation` versus `peripheral_oxygen_saturation`, and `known_metabolic_muscle_disease_history` versus a broader prior neuromuscular disease risk axis.
