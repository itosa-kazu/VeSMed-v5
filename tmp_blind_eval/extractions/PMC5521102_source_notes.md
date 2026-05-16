# PMC5521102 Blind Source Notes

Source used: PMC OAI/JATS full text for PMCID PMC5521102, plus PMC ID converter and PubMed ESummary for identifiers and citation metadata.

Blindness constraints followed:
- No local distillation files, local case files, or ranking outputs were read.
- No expected disease label was added.
- The article title, final diagnostic wording, discussion, literature-review summary, treatment response, discharge/follow-up, and causal interpretation were not used as rankable evidence.
- Rankable observations were limited to demographics, pre-existing risk context, and presentation/pre-diagnostic chronology in the Case presentation section.

## Rankable Chronology Paraphrase

A 53-year-old Indigenous Australian male presented to a remote regional hospital in northern Australia with acute urinary retention. His background included type 2 diabetes mellitus, chronic hepatitis B infection, recurrent skin and soft tissue infections, and long-term kava use.

At the first visit, a urinary catheter was placed and a urine specimen was cultured. The patient left the same day after declining further care. The urine culture later grew methicillin-resistant Staphylococcus aureus, prompting recall and admission.

On recall, urinary symptoms and suprapubic pain persisted. He also had left thigh pain severe enough to impair walking. Digital rectal examination found a firm, normal-sized, non-tender prostate. Examination also found tender diffuse swelling in the medial left thigh. Bedside ultrasound of the thigh showed a large hypoechoic lesion measuring 74 x 52 x 61 mm, with an estimated volume of 123 mL.

Admission labs at the receiving institution showed leukocytosis with total leukocyte count 12.7 x 10^9/L, neutrophils 8.7 x 10^9/L, and CRP 65 mg/L. Testing for Burkholderia pseudomallei was negative by serology and by throat/rectal cultures.

Repeat urine culture again showed pure MRSA growth, clindamycin susceptible and trimethoprim resistant. A right great toe ulcer was present and its swab culture also grew nmMRSA with the same antibiogram. Skin scrapings were positive for Sarcoptes scabiei.

Pre-drainage CT abdomen/pelvis showed multiple prostate fluid collections, including a prominent left-base collection and loculated apical collections. This was represented as neutral imaging findings, not as a final diagnosis label. Blood cultures reported after transfer grew nmMRSA matching the urine isolate, with vancomycin MIC 1.5 ug/mL.

## Record-Only Exclusions

The urinary catheter placement, initial self-discharge, treatment refusal, air-ambulance transfer, IV vancomycin start, surgical thigh drainage, trans-rectal ultrasound guided prostate drainage, purulent aspirate, operative/aspirate cultures, post-drainage imaging, negative surveillance blood cultures after therapy, transthoracic echocardiogram, oral clindamycin addition, declined further drainage, clinical improvement, four-week antibiotic course, residual collection at end of IV therapy, and complete radiologic resolution at five months were stored as record-only with `use_in_ranking=false`.

The article title and diagnostic wording in the case text identify the final condition, but those words were not used as rankable evidence. Discussion and literature-review sections were also excluded from ranking evidence because they contain retrospective causal interpretation, aggregate frequencies, and treatment recommendations.

## Axis Naming Uncertainties

- CRP axis may need normalization from `serum_c_reactive_protein` to the registry-preferred CRP axis.
- Acute urinary retention may need a parent lower-urinary-tract obstruction or urinary retention axis.
- Persistent urinary symptoms were not decomposed into dysuria/frequency/hesitancy because the source did not specify them at recall.
- DRE findings may need parent/satellite normalization for prostate texture, size, and tenderness.
- Thigh hypoechoic lesion may later normalize under a generic soft-tissue fluid collection axis.
- Prostate CT findings were named as neutral fluid-collection axes to avoid using final diagnosis wording.
- MRSA culture axes may need decomposition into organism-positive and methicillin-resistance axes.
- Vancomycin MIC may belong in a microbiology/treatment-context namespace rather than a primary diagnostic axis.
