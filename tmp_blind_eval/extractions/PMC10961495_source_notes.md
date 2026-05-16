# PMC10961495 Blind Extraction Source Notes

## Source Access

- Source URL used: https://pmc.ncbi.nlm.nih.gov/articles/PMC10961495/
- PMCID: PMC10961495
- PMID: 38521515
- DOI: 10.1136/bcr-2023-257234
- Journal: BMJ Case Reports
- Publication date from metadata: 2024-03-22
- PMC XML front metadata was accessible through NCBI EFetch. Full-text XML was not available from the publisher, so the extraction used the PMC HTML full text.
- The article title was not used for diagnostic evidence because it is diagnosis-revealing.

## Extraction Boundary

- Used for ranking: demographics, pregnancy context, past history, initial symptoms/signs, initial vitals, admission labs, day-3 deterioration, day-3 labs/imaging, and raw diagnostic workup tests.
- Kept record-only: treatment/procedures, delivery as intervention, transfusions, antimicrobial therapy, tracheostomy, treatment response, late recovery, discharge/follow-up outcome, and authors' final diagnostic framing.
- Post-intubation culture results were retained as record-only because they are late ICU course data and could conflate hospital-acquired complications with the index presentation.

## Numeric And Axis Notes

- Table 1 and narrative text conflict for blood counts. The JSON uses Table 1 as the structured numeric source and preserves the conflict in `uncertainty` fields.
- Admission platelet count: table reports 150 x10^9/L; narrative appears to report 15 x10^3/uL.
- Day-3 total leukocyte count: table reports 27.7 x10^9/L; narrative reports 12 x10^3/uL.
- Day-3 platelet count: table reports 30 x10^9/L; narrative appears to report 8000/uL.
- The table lists SGOT/SGPT reference units as mg/dL, while the narrative uses IU/L. The JSON normalizes aminotransferases to U/L.
- Axis names were created as diagnosis-neutral generic observed axes. No ordinary observed axis uses a `*_in_D-*` form.

## Label Leakage Controls

- I did not read local distillations, local case files, ranking result files, or existing blind extraction files.
- The JSON does not include expected manifold fields, paper-title diagnostic evidence, or an explicit final diagnosis label.
