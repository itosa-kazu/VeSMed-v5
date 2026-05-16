# PMC3514212 Blind Extraction Notes

## Source

- PMCID: PMC3514212
- PMID: 23098331
- DOI: 10.1186/1471-2334-12-272
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC3514212/
- Title: Dengue hemorrhagic fever and severe thrombocytopenia in a patient on mandatory anticoagulation; balancing two life threatening conditions; a case report
- Journal: BMC Infectious Diseases
- Publication date: 2012-10-26 online; collection year 2012
- XML source used: NCBI PMC EFetch

## Extraction Boundaries

- No local atlas, distillation, ranking case, or disease JSON files were read.
- Author clinical framing, acute management, response, late follow-up, and discussion interpretation were kept in `record_only` with `use_in_ranking: false`.
- Rankable entries are ordinary reusable clinical observations: symptoms, examination findings, vital signs, serology, imaging finding, bleeding findings, blood culture, and numeric labs.
- Medication history and acute medication decisions were not used as rankable observations.

## Key Case Facts Captured As Rankable Observations

- Demographics: 51-year-old Sri Lankan woman.
- Presentation: 3 days of fever with arthralgia, myalgia, headache, and vomiting noted during early management.
- No urinary or respiratory infective focus was reported.
- Examination: pallor, dental caries, ankle edema, no peripheral stigmata of infective endocarditis, pulse 82/min, BP 110/60 mmHg, no postural hypotension, no narrowed pulse pressure, metallic first heart sound, loud pulmonary component of S2, and bilateral basal crackles.
- Test/imaging findings: positive IgM MAC-ELISA, small right pleural effusion, sterile blood culture.
- Bleeding findings: gum bleeding, petechiae, and hemorrhagic blebs up to 2 x 2 cm at venepuncture sites in both arms.
- Table 1 lab trajectory was extracted for platelet count, packed cell volume, hemoglobin, white cell count, AST, ALT, PT/INR, ESR, CRP, and blood culture.

## Caveats

- Table 1 uses dates in July 2011. Its footnote states the leakage/critical phase was from `12/7/2012 to 14/7/2012`, which conflicts with the table year. The JSON preserves source date strings from the table and does not use the conflicting footnote year as a rankable date.
- Hemoglobin and ESR units are not stated in Table 1, so their `unit` fields are `null`.
- The platelet value on 14/7/2011 has a footnote marker because platelet and red cell transfusions occurred on that date. The numeric value is captured as 5 x 10^3/uL, and the transfusion itself is record-only.
- The article title and author clinical framing identify the disease context, but those statements are kept out of rankable observations except for objective test results stated in the case narrative.
