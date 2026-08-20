# PMC7005653 source notes

## Source

- Primary article: [Caballol et al., *Fulminant hepatitis A complicated by Takotsubo syndrome successfully treated with standard volume plasma exchange*](https://pmc.ncbi.nlm.nih.gov/articles/PMC7005653/)
- PMCID: `PMC7005653`
- PMID: `32039396`
- DOI: `10.1016/j.jhepr.2019.10.004`
- Published in *JHEP Reports* (2019), open access under CC BY-NC-ND.
- Extraction date: `2026-07-20`
- Extraction basis: the PMC article and NCBI BioC rendering. The decisive case text is in BioC `CASE` passages beginning at offsets `2102` and `3924`; Figure 1/2 captions begin at offsets `1671` and `3683`. The post-hoc causal interpretation is in the `DISCUSS` passage beginning at offset `8740`.

This folder is an independent source extraction for the **new clinical framework**. No V5 ranking result, V5 expected diagnosis, or V5 case JSON was treated as fact.

## What the article actually supports

### Before transfer and ICU admission

- A previously healthy 61-year-old woman had fatigue and nausea during the preceding week.
- At the referring institution, AST/ALT were `12,760/11,864 IU/L`, total bilirubin `5.3 mg/dL`, and INR `3.5`.
- She was transferred immediately to the reporting hospital's liver ICU.
- On ICU admission she was hemodynamically stable, had no hepatic encephalopathy, and had jaundice without another reported examination abnormality.
- Admission measurements were AST `5,206`, ALT `7,829`, GGT `256`, ALP `164 IU/L`, bilirubin `6.9 mg/dL`, INR `3.9`, and ammonia `86 umol/L`.
- Initial abdominal ultrasound and ECG were reported normal. Initial LVEF was `52%`, and troponin I was normal, but no numerical initial troponin value was supplied.

### Early diagnostic workup

- A transjugular liver biopsy demonstrated cholestatic and necroinflammatory injury with periportal necrosis. The figure caption additionally mentions mild portal inflammation and plasma cells.
- HAV IgM was positive; HCV, HBV, HEV, and HIV studies were reported negative.
- The treating team diagnosed severe acute hepatitis A after these results.

**Timing limit:** the article narrates these findings in the initial-workup paragraph before the day-2 paragraph, but does not report specimen collection, test completion, or result-release timestamps. `C2_early_workup_results` is therefore an **ordinal evidence cut**, not “day 0.5” or another invented clock coordinate. The JSON deliberately withholds these results from the admission cut.

### ICU day 2: hepatic and neurologic deterioration

- Encephalopathy progressed to grade IV within a few hours.
- Endotracheal intubation, sedation, and analgesia were initiated.
- Measurements at that time were AST `893`, ALT `3,922 IU/L`, bilirubin `14.1 mg/dL`, INR `2.7`, and ammonia `132 umol/L`.
- Transcranial Doppler pulsatility indices were diffusely elevated to `1.5-1.8`; the authors interpreted this as suggestive of intracranial hypertension.
- Emergent liver transplantation was considered under the Hospital Clinic and King's College criteria.

The falling aminotransferases are retained as measurements, not mislabeled as hepatic recovery: encephalopathy, bilirubin, ammonia, and coagulopathy still documented severe failure.

### ICU day 2: newly revealed cardiac process

The article gives a useful within-day order:

1. Transplant evaluation triggered clinical re-evaluation.
2. A new ECG showed mild ST depression across V1-V6 and troponin I was `11.19 ng/mL`.
3. A new echocardiogram showed mid-basal hypokinesia and LVEF `32%`, described as compatible with Takotsubo syndrome.
4. Coronary angiography/ventriculography then showed normal coronary arteries and severe mid-ventricular dysfunction; the article calls this confirmation.
5. Within the following hours, hypotension developed.
6. Dobutamine and low-dose noradrenaline were initiated.
7. Cardiogenic shock with severe cardiac dysfunction was used to contraindicate liver transplantation.
8. Plasma exchange was started as salvage therapy.

No clock times, numeric blood pressure, dobutamine dose, or noradrenaline dose were reported. The JSON keeps only these relational constraints.

### Plasma-exchange course and recovery

- Three consecutive standard-volume plasma-exchange sessions were performed during the next three days.
- Each session used `1.5 plasma volumes` (reported as `6.5%` of ideal body weight), with methylene-blue-inactivated fresh frozen plasma as replacement.
- The article does **not** identify the three individual session calendar days. The event stream therefore represents one bounded course rather than fabricating day-2/day-3/day-4 sessions.
- The article reports progressive improvement with rapid cardiac normalization; sustained declines in aminotransferases, ammonia, and INR; and normalization of the Doppler pulsatility index. Intermediate numeric values and their exact days are absent from the prose.
- Bilirubin transiently increased after plasma exchange stopped and later normalized. The exact peak and exact date are not reported.
- The patient was extubated on ICU day 9.
- On ICU day 14, acute liver failure was reported resolved and cardiac function normalized, and she was transferred to a regular ward.

The last point is **ICU-to-ward transfer**, not documented hospital discharge.

## Separation of epistemic layers

`case_event_stream.json` deliberately keeps five classes distinct:

| Layer | Examples | What it must not be confused with |
|---|---|---|
| Observation | AST, ammonia, EF, normal coronaries | A diagnosis or causal explanation |
| Action | intubation, catheterization, pressors, plasma exchange | Evidence that the action was effective |
| Clinical hypothesis | acute hepatitis A, suspected intracranial hypertension, Takotsubo syndrome | A raw measured axis |
| Decision | transplant considered, later contraindicated | A treatment actually delivered |
| Outcome | extubation, liver/cardiac recovery, ward transfer | Proof of the counterfactual without treatment |

The discussion's suggestion that plasma exchange may have accelerated cardiac recovery is stored as `E035_author_plasma_exchange_interpretation`, marked publication-only and excluded from real-time replay. A single temporally associated recovery cannot identify that patient's untreated counterfactual.

## Diagnosis-neutral observation policy

- Observation IDs describe measurements or findings rather than embedding the final diagnosis.
- Disease names occur only in `clinical_hypothesis` records, never as ordinary observations.
- A pathogen-specific assay such as HAV IgM remains a legitimate observed test result; it is not replaced with a disease-probability score.
- “Normal” findings are scoped to what the paper states. For example, `other_physical_exam_abnormality_reported=0` means the article reported no other abnormality; it is not an exhaustive negative review of systems.
- Missing numeric values remain missing. No blood pressure, initial troponin value, drug dose, intermediate recovery value, or discharge date was imputed.

## No-future-evidence replay cuts

The intended sequential reveal is:

1. `C0_external_presentation`: preceding-week history and referring-hospital labs.
2. `C1_icu_admission`: admission bedside, laboratory, ultrasound, ECG, EF, and qualitative normal troponin facts only.
3. `C2_early_workup_results`: biopsy and serology results, followed by the documented hepatitis-A hypothesis. Its clock time is unknown.
4. `C3_day2_neurologic_deterioration`: grade-IV encephalopathy, intubation, day-2 liver/ammonia measurements, Doppler finding, and transplant consideration. No cardiac re-evaluation yet.
5. `C4_day2_cardiac_workup`: ECG/troponin, echo, catheterization/ventriculography, and the Takotsubo hypothesis. No later shock facts yet.
6. `C5_day2_shock_pre_plasma_exchange`: hypotension, inotrope/vasopressor support, cardiogenic-shock hypothesis, and transplant contraindication. Plasma exchange has not yet been exposed.
7. `C6_day2_plasma_exchange_initiation`: plasma exchange starts only after the contraindication decision.
8. `C7_after_three_session_course`: completed three-session course and only then the reported progressive-response summary.
9. `C8_day9_extubation`: extubation and liberation from invasive ventilation.
10. `C9_day14_ward_transfer`: reported resolution/normalization and ICU-to-ward disposition.

These cuts are for testing a sequential state estimator. They do not assert that the article recorded every clinical action or that unreported events did not occur.

## Deliberately excluded or downgraded claims

- No exact time was assigned to biopsy, serology collection, or their result availability.
- No exact individual days were assigned to the three plasma-exchange sessions.
- No unreported medication, transplant action, ventilation setting, laboratory value, or hospital discharge was added.
- “Intracranial hypertension” remains a suggested hypothesis because the source uses a suggestive Doppler pattern rather than direct intracranial-pressure measurement.
- Plasma exchange is not encoded as the proven cause of either liver or cardiac recovery.
- The paper's final diagnoses are not back-propagated into earlier observations.

## Extraction limitations

This is a short case report, not a timestamped electronic health record. The chronology is strong at the major anchors (admission, day 2, day 9, day 14) and at several within-day order relations, but weak for early workup availability and the exact recovery trajectory. A new-framework implementation should therefore propagate interval/ordinal uncertainty rather than silently converting this source into a dense daily time series.
