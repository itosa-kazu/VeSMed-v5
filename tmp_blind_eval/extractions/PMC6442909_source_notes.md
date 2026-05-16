# PMC6442909 Blind Extraction Source Notes

## Source

- PMCID: PMC6442909
- PMID: 30956583
- DOI: 10.1080/08998280.2018.1526571
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC6442909/
- Title: Total body necrotizing fasciitis
- Journal: Proceedings (Baylor University. Medical Center)
- Publication: epub 2019-01-11; collection 2019-01

## Blinding And Scope

- This extraction used the public PMC article HTML and NCBI metadata only.
- I did not inspect local distillations, master axis registry, existing ranking cases, disease JSON files, or previous result files.
- The JSON does not include expected disease, expected manifold, expected disease id, or disease label fields.
- Ordinary observations use diagnosis-neutral axes only; no observation axis contains a disease-id suffix.

## Rankable Clinical Facts Extracted

- Patient: 64-year-old woman.
- Risk context: controlled type 2 diabetes mellitus and multiple chronic medical problems, with no further chronic diagnoses specified in the case text.
- Presentation: altered mental status after being found confused; reported baseline 1 day earlier.
- Vital signs: temperature 101.2 F, heart rate 114/min, blood pressure 78/52 mm Hg, respiratory rate 16/min, oxygen saturation 78% on room air.
- Physical exam: somnolence, oriented to person only, moderate distress, left middle/lower lung crackles, abdominal distension and tenderness, diminished bowel sounds, extremity edema, warm skin, difficult pulses, and a 4 cm plantar right-foot blister.
- Labs: glucose 245 mg/dL, platelets 85,000/uL, white cell count 12,400/uL, granulocytes 83%.
- Imaging: extensive right-foot subcutaneous emphysema; bilateral lower-extremity subcutaneous air; intravascular gas in multiple arteries and the aorta; intraosseous air in spine/hips/knees; portal venous gas; retroperitoneal and psoas gas; perivesical gas with possible bladder-wall gas; pelvic free air; diffuse subcutaneous air in axilla/neck/flanks; right parieto-occipital intraparenchymal gas with subtle adjacent vasogenic edema.

## Record-Only Items

- LRINEC score 7 is kept record-only because it is a diagnosis-specific score; the underlying lab observations are rankable separately.
- Intubation, fluids, broad-spectrum antibiotics, vasopressors, deterioration, death, and surgical-candidacy statement are record-only with use_in_ranking false.
- The article title, abstract, and discussion framing are preserved in metadata/record-only notes, not as rankable disease labels.

## Caveats

- The article states "multiple chronic medical problems" but does not enumerate them beyond controlled type 2 diabetes mellitus.
- Bladder-wall gas is uncertain in the article wording and is marked as possible rather than definite.
- Some article units use symbols in the web rendering; the JSON normalizes them to ASCII units such as degF and per_uL.
