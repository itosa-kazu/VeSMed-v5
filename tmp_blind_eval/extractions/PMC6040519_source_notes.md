# PMC6040519 Blind Extraction Notes

## Source

- PMCID: PMC6040519
- PMID: 29960967
- DOI: 10.1136/bcr-2018-225344
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC6040519/
- Title: Just another case of bacterial meningitis... or... is it?
- Journal: BMJ Case Reports
- Publication date: 2018-06-29
- Article type: Case Report

## Blinding Boundary

- Did not inspect local `distillations/`, `master_axes.json`, ranking cases, disease JSON files, or previous result files.
- Did not add expected disease/manifold labels.
- Kept final diagnosis, treatments, response, histology, surgical course, follow-up, and discussion framing in `record_only` with `use_in_ranking: false`.
- Rankable axes use diagnosis-neutral clinical observations only.

## Case Fact Summary

- Patient: 62-year-old woman.
- Acute presentation: severe frontal headache, vomiting, progressive decreased consciousness, admission GCS 8-9/15, fever 37.9 C, tachycardia 108/min, mild neck stiffness, no rash or photophobia.
- Initial physiology: BP 140/85 mmHg, RR 17/min, room-air oxygen saturation 96%, capillary glucose 9.1 mmol/L.
- CT: pituitary fossa/skull base mass 25 x 18 x 19 mm with sellar bone erosion; no pneumocephalus.
- Blood and gas tests: neutrophilia, CRP 59 mg/L, normal kidney/liver function and calcium, normal venous pH, pCO2 5.35 kPa, lactate 2.7 mmol/L.
- CSF: cloudy/turbid, opening pressure 24.5 cmH2O, protein 4.59 g/L, glucose <0.6 mmol/L, WBC 12,480 x10^6/L with 95% polymorphs and 5% lymphocytes.
- Microbiology: CSF gram stain, CSF culture, and blood cultures negative; CSF and blood PCR positive for Streptococcus pneumoniae DNA; meningococcus and HSV PCR negative.
- Pre-admission symptoms elicited later: minor headaches for months and clear watery rhinorrhea for 3-4 months, worse on bending forward; no sneezing or itchiness.
- Later objective diagnostic workup: nasal fluid beta-2 transferrin positive, normal anterior pituitary function/prolactin, nonspecific upper-left nasal visual field defect, MRI showing enhancing central skull base mass with cavernous sinus/sphenoid sinus/clivus/pituitary stalk extension, carotid encasement, and optic chiasm abutment.

## Caveats

- The PMC browser page challenged direct page opening, so metadata was checked through NCBI E-utilities and the clinical text was extracted from the indexed PMC article content returned by search.
- MRI, beta-2 transferrin, and reviewed rhinorrhea history appear in the article's Treatment section after early stabilization, but they are objective or historical observations rather than treatment response; they were kept rankable with source section preserved.
- Histology confirming the lesion subtype was placed in `record_only` because it belongs to later surgical/diagnostic course and would unblind the final disease framing.
