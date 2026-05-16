# PMC9771788 Blind Extraction Notes

## Source

- PMCID: PMC9771788
- PMID: 36567688
- DOI: 10.1002/ccr3.6783
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC9771788/
- Title: Hyperkalemia mimicking de Winter T waves: A case report
- Journal: Clinical Case Reports
- Published: 2022-12-21

## Blind Scope

- Only the public article page was used for clinical facts and metadata.
- Local atlas files, disease JSON files, master axis registry, prior case files, and ranking result files were not inspected.
- No label or manifold fields were written.
- Ordinary observations use diagnosis-neutral reusable axes.

## Rankable Extraction Boundary

Rankable items were limited to facts available before disease-directed response assessment:

- Demographics: 86-year-old male.
- Background context: hypertension, antihypertensive nonadherence, prescribed antihypertensive agents, chronic kidney disease context, proteinuria, oliguria history, furosemide use history, recent cold symptoms.
- Symptoms before admission: chest pain, weakness, dyspnea, nausea, vomiting, symptom duration, rest onset, severe chest pain.
- Admission findings: heart rate, blood pressure, respiratory rate, room-air oxygen saturation, bilateral moist rales.
- Admission ECG: sinus rhythm, P-R interval, upsloping ST depression, magnitude greater than 1 mm, peaked T waves, de Winter ECG pattern.
- Admission labs before hemodialysis: potassium, bicarbonate, creatinine, and bedside cTnI relative to the upper limit of normal.

## Record-Only Items

The following are preserved only under `record_only` with `use_in_ranking=false`:

- Emergency coronary angiography planning.
- Urgent hemodialysis.
- Post-hemodialysis symptom, potassium, cTnI, P-R interval, and ECG changes.
- Coronary angiography result during hospitalization.
- Persistent renal dysfunction and regular hemodialysis recommendation.
- Article discussion framing about CKD, heart failure, respiratory tract infection, acute kidney injury, medication context, and pseudo-infarction ECG interpretation.

## Caveats

- The article reports cTnI only as greater than three times the upper limit of normal, not as an absolute concentration.
- Respiratory tract infection is described colloquially as a cold; no pathogen or formal infectious workup is provided.
- Chronic kidney disease is stated by the article, with prior creatinine and proteinuria supporting the context, but the report does not give an eGFR stage.
- The source notes preserve the article's stated sequence; post-treatment findings are not rankable for blind regression.
