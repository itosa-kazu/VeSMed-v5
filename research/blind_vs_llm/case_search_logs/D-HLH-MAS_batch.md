# Case search log: batch starting D-HLH-MAS

Leaves in order: D-HLH-MAS, D-WEST-NILE-NEUROINVASIVE-DISEASE, D-SEPSIS-GN, D-DIC, D-SALICYLATE-TOXICITY, D-TOXIC-SHOCK-SYNDROME.

Search method: Europe PMC REST search (OPEN_ACCESS:y, FIRST_PDATE 2025-01-01 to 2026-12-31), up to 300 hits per query, re-sorted by firstPublicationDate descending; candidates screened newest-first; PMCIDs checked against frozen/known_pmcids.txt; full text via fullTextXML.

## 1. D-HLH-MAS (Hemophagocytic lymphohistiocytosis / macrophage activation syndrome)

Queries:
- `("hemophagocytic lymphohistiocytosis" OR "macrophage activation syndrome" OR "haemophagocytic lymphohistiocytosis") AND "case report" AND OPEN_ACCESS:y AND FIRST_PDATE:[2025-01-01 TO 2026-12-31]` (1110 hits)
- cross-check for the newest weeks: `(hemophagocytic OR haemophagocytic OR hemophagocytosis OR "macrophage activation syndrome" OR HLH) AND OPEN_ACCESS:y AND FIRST_PDATE:[2026-09-10 TO 2026-12-31]` (45 hits; no additional HLH case report found)

Candidates examined (newest first):
1. PMC13594791 (2026-10-01) Fulminant secondary HLH after EBV reactivation post-teplizumab, trisomy 21. REJECTED: brief report; the only quantitative values (Hb 8.0, plt 89, ferritin 10478, sIL-2R 15420, TG 539, fibrinogen 141) are HLH-criteria values without a presentation time point (serial labs only in a supplementary figure), no vital signs reported; lymph-node pathology of EBV-associated lymphoproliferation adds an overlapping lymphoproliferative framing. Condition 4 (presentation labs/vitals) not verifiably met.
2. PMC13600804 (2026-09-25) Concurrent catastrophic APS, HLH and myocarditis in SLE/APS. REJECTED: multiple concurrent primary diagnoses; CAPS, myocarditis and SLE have their own leaves.
3. PMC13603065 (2026-09-24) Mosaic TLR8 gain-of-function treated with JAK inhibitor. REJECTED (title/abstract screen): not an HLH/MAS primary diagnosis.
4. PMC13600130 (2026-09-20) Lung-predominant hyperinflammatory syndrome in therapy-related MDS. REJECTED: diagnosis is an MDS-associated autoinflammatory lung syndrome, not HLH/MAS.
5. PMC13604061 (2026-09-17) Review. REJECTED: not a case report.
6. PMC13578911 (2026-09-15) Delayed recognition of HLH in a child with refractory fever (Pakistan). ACCEPTED.

ACCEPTED: case_id `HLH_PEDIATRIC_REFRACTORY_FEVER_PMC13578911`, PMCID PMC13578911, PMID 42750833, published 2026-09-15.
- Paper diagnosis: HLH, clinical diagnosis by 5/8 HLH-2004 criteria, trigger not identified; not SLE/AOSD/sJIA/EBV-IM/lymphoma/leishmaniasis (none of those diagnosed).
- Presentation evidence: hospital-day-1 lab table (>20 quantitative labs) + temperature 104 F.
- Files: cases/v5_case_HLH_PEDIATRIC_REFRACTORY_FEVER_PMC13578911.json; vignettes/HLH_PEDIATRIC_REFRACTORY_FEVER_PMC13578911.txt
- validate_case.py: loads; 78 consumed axes (including loader alias expansions; 51 structured observations in the file).
- Pending (not in registry) axes created: absolute_monocyte_count, liver_edge_below_costal_margin_cm, spleen_tip_below_costal_margin_cm, mean_corpuscular_hemoglobin, mean_corpuscular_hemoglobin_concentration, red_cell_distribution_width; loader-derived pending satellites: antibiotic_nonresponse_severity, pallor_severity, pericholecystic_fluid_severity.
- Notes: fever_presence is expanded by the loader to infection_trigger_activity (runtime alias behavior, recorded in quality_warnings). Spleen length 15.9 cm kept record-only (timing not stated). Exclusion serologies, blood culture, and HLH-criteria adjudication are non-ranking.

## 2. D-WEST-NILE-NEUROINVASIVE-DISEASE (West Nile neuroinvasive disease)

Queries:
- `("West Nile") AND ("case report" OR "case presentation") AND OPEN_ACCESS:y AND FIRST_PDATE:[2025-01-01 TO 2026-12-31]` (309 hits)
- cross-check: `("West Nile" OR WNV) AND OPEN_ACCESS:y AND FIRST_PDATE:[2026-08-27 TO 2026-12-31]` (107 hits; only surveillance/basic-science/review papers plus one conference abstract)

Candidates examined (newest first):
1. PMC13599793 (2026-09-19) Atypical vasculitis phenotype. REJECTED (title screen): not West Nile disease.
2. PMC13451099 (firstPublicationDate 2026-09-09; issue 2026-07-31) Research-symposium abstract "Delirium tremens or a deadlier delirium?" (WNV meningoencephalitis). REJECTED: conference abstract, not a full case report; no quantitative labs or vitals.
3. PMC13597404 (2026-09-09) Spinal glioblastoma ctDNA. REJECTED: not WNV.
4. PMC13543667 (2026-09-04) Spinal cord sarcoidosis. REJECTED: not WNV.
5. PMC13611556 (2026-09-03) Review (WNV in HIV). REJECTED: review.
6. PMC13613778 (2026-09-01) Equine neuroborreliosis. REJECTED: veterinary, not WNV.
7. PMC13615839 (2026-08-27) A multisystem presentation of West Nile neuroinvasive disease. ACCEPTED.

ACCEPTED: case_id `WNND_MENINGOENCEPHALITIS_MULTISYSTEM_PMC13615839`, PMCID PMC13615839, PMID 42801153, published 2026-08-27.
- Paper diagnosis: acute West Nile neuroinvasive disease (meningoencephalitis), CSF WNV IgM positive / IgG negative.
- Presentation evidence (snapshot day 0): admission labs Na 126, K 4, Cr 0.76, BUN 7, glucose 165, Ca 8.2, albumin 3.1, AST 140, ALT 73, WBC 4.4, TSH 0.25; day -4 Na 130; fever/chills/melena/diarrhea/confusion/lower abdominal pain; orthostatic hypotension; head CT no acute change. No quantitative vitals reported.
- Brain MRI (day ~2), EEG (day 3) and CSF (day 4) kept as non-ranking post-presentation work-up (snapshot = presentation; the loader also drops observations dated after snapshot_day). Hospital-course complications and WNV serology non-ranking.
- Files: cases/v5_case_WNND_MENINGOENCEPHALITIS_MULTISYSTEM_PMC13615839.json; vignettes/WNND_MENINGOENCEPHALITIS_MULTISYSTEM_PMC13615839.txt
- validate_case.py: loads; 44 consumed axes (including loader alias expansions; 25 structured observations).
- Pending axes: brain_ct_acute_abnormality_presence (created); loader-derived nausea_vomiting_severity.

## 3. D-SEPSIS-GN (Bacterial sepsis)

Queries:
- `(TITLE:"sepsis" OR TITLE:"septic shock" OR TITLE:"bacteremia" OR TITLE:"bacteraemia" OR TITLE:"septicemia") AND ("case report" OR "case presentation") AND OPEN_ACCESS:y AND FIRST_PDATE:[2025-01-01 TO 2026-12-31]` (879 hits; newest 400 screened by title)
- supplementary (to catch titles without the word sepsis): `("septic shock" OR sepsis OR bacteremia OR bacteraemia) AND ("blood culture" OR "blood cultures") AND ("case report" OR "case presentation") AND OPEN_ACCESS:y AND FIRST_PDATE:[2026-09-01 TO 2026-12-31]` (113 hits)

Candidates examined (newest first; non-infection titles such as adrenal hemorrhage, Meckel diverticulum, research articles, reviews were title-screened out):
1. PMC13601292 (2026-09-25) CRAB bloodstream infection in a child after failed allogeneic HSCT with persistent severe neutropenia. REJECTED: neutropenic-host bloodstream infection (corresponds to D-FEBRILE-NEUTROPENIA context); therapy-focused report.
2. PMC13615361 (2026-09-25) Necrotizing fasciitis with polyarteritis nodosa. REJECTED: own leaves (D-NECROTIZING-FASCIITIS, D-PAN).
3. PMC13602975 (2026-09-24) Culture-negative infective endocarditis presumed Brucella. REJECTED: D-INFECTIVE-ENDOCARDITIS / D-BRUCELLOSIS.
4. PMC13589855 (2026-09-20) Melioidosis-associated abdominal aortic pseudoaneurysm. REJECTED: primary diagnosis is a focal infected aortic pseudoaneurysm (hemodynamically stable), not a sepsis syndrome.
5. PMC13588602 (2026-09-20) Salmonella aortitis / mycotic aneurysm. REJECTED: focal vascular infection; Salmonella has its own bacteremia leaf.
6. PMC13592732 (2026-09-20) Fulminant necrotizing fasciitis of the upper extremity. REJECTED: D-NECROTIZING-FASCIITIS.
7. PMC13599596 (2026-09-19) Campylobacter CIED pocket infection. REJECTED: localized device-pocket infection, not sepsis.
8. PMC13589352 (2026-09-18) Helcococcus kunzii spondylodiscitis. REJECTED: D-VERTEBRAL-OSTEOMYELITIS.
9. PMC13583047 (2026-09-16) Lemierre's syndrome with skull-base osteomyelitis (Arcanobacterium). REJECTED: two focal diagnoses (septic thrombophlebitis + osteomyelitis), not a primary sepsis diagnosis.
10. PMC13610265 (2026-09-14) ESBL Klebsiella pneumoniae bacteraemia with renal micro-abscesses in neutropenia. REJECTED: D-ESBL-ENTEROBACTERALES-BACTEREMIA (and renal abscess / febrile neutropenia).
11. PMC13588114 (2026-09-14) Myroides odoratimimus (blaMOC-1) bloodstream infection with septic shock. ACCEPTED.

(Older candidates already screened before the supplementary search, kept for the record: PMC13570409 2026-09-12 neonatal K. pneumoniae urosepsis; PMC13562913 2026-09-10 polymicrobial pneumonia incl. S. pneumoniae in XLA = pneumonia leaf; PMC13560501 2026-09-10 murine typhus = rickettsial disease; PMC13554959 meningococcal bacteremia = D-MENINGOCOCCEMIA; PMC13587629 E. coli bacteremia from intravascular double-J stent = only WBC/Hb reported, afebrile on admission; PMC13574480 2026-09-01 Streptococcus suis septic shock with DIC, would qualify but is older.)

ACCEPTED: case_id `SEPSIS_MYROIDES_PEMPHIGUS_SKIN_PMC13588114`, PMCID PMC13588114, PMID 42761903, published 2026-09-14 (epub).
- Paper diagnosis: septic shock and bloodstream infection, Gram-negative bacillus septicemia (metallo-beta-lactamase-producing Myroides odoratimimus) secondary to skin breakdown in pemphigus. Myroides has no organism leaf; no cellulitis or other source leaf described.
- Presentation evidence: admission vitals (T 36.4 C, pulse 50, RR 16, BP 142/112) + Day-1 labs (WBC 2.5, CRP 185.1, PCT 6.14, IL-6 >5000, plt 90, albumin 24.3 g/L, Cr 123.9 umol/L, Hb 104 g/L, D-dimer 2.1, fibrinogen 6.5 g/L); coma, urinary incontinence, intubation, generalized pustules and blisters.
- Files: cases/v5_case_SEPSIS_MYROIDES_PEMPHIGUS_SKIN_PMC13588114.json; vignettes/SEPSIS_MYROIDES_PEMPHIGUS_SKIN_PMC13588114.txt
- validate_case.py: loads; 30 consumed axes (21 structured observations).
- Pending axes: cutaneous_blister_presence.
- Notes: microbiology-focused report with brief clinical data; admission BP not hypotensive despite the "septic shock" label (kept as reported); organism ID/susceptibility non-ranking; days 2-3 labs non-ranking.

## 4. D-DIC (Disseminated intravascular coagulation)

Queries:
- `(TITLE:"disseminated intravascular coagulation" OR TITLE:"DIC" OR TITLE:"consumptive coagulopathy" OR TITLE:"consumption coagulopathy") AND ("case report" OR "case presentation") AND OPEN_ACCESS:y AND FIRST_PDATE:[2025-01-01 TO 2026-12-31]` (57 hits)
- supplementary: `(ABSTRACT:"disseminated intravascular coagulation" OR ABSTRACT:"consumptive coagulopathy" OR TITLE:"purpura fulminans" OR TITLE:"coagulopathy") AND ("case report" OR "case presentation") AND OPEN_ACCESS:y AND FIRST_PDATE:[2026-08-18 TO 2026-12-31]` (9 hits)

Candidates examined (newest first):
1. PMC13544422 (2026-09-04) Fulminant Brucella melitensis infection with cholestatic hepatitis, AKI and DIC. REJECTED: main diagnosis brucellosis (D-BRUCELLOSIS).
2. PMC13582455 (2026-09-03) Pelvic kaposiform hemangioendothelioma with Kasabach-Merritt phenomenon. REJECTED: main diagnosis is a vascular tumor with Kasabach-Merritt phenomenon (localized consumptive coagulopathy), therapy-focused; not DIC as the primary diagnosis.
3. PMC13574480 (2026-09-01) S. suis septic shock with DIC and ischemic limb necrosis. REJECTED for D-DIC: primary diagnosis septic shock (D-SEPSIS-GN).
4. PMC13593930 (2026-08-22) Snakebite envenomation with compartment syndrome. REJECTED: primary diagnosis envenomation/compartment syndrome.
5. PMC13513553 (2026-08-20) Fulminant thromboinflammatory syndrome after influenza-like illness. REJECTED: presenting diagnosis was iliofemoral DVT with bilateral PE (D-PULMONARY-EMBOLISM); overt DIC documented ~2 weeks later with unresolved HIT overlap (anti-PF4 positive); labs reported only as period ranges.
6. PMC13519953 (2026-08-27) Eclamptic ICH with RCVS; PMC13498755 (2026-08-21) alcoholic ketoacidosis. REJECTED (title/abstract screen): not DIC primary.
7. PMC13522237 (2026-08-18) Catastrophic systemic reaction and fatal DIC after high-pressure intrapelvic povidone-iodine instillation. ACCEPTED.

ACCEPTED: case_id `DIC_INTRAPELVIC_POVIDONE_IODINE_PMC13522237`, PMCID PMC13522237, PMID 42666565, published 2026-08-18.
- Paper diagnosis: fulminant (fatal) DIC after an acute systemic reaction to high-pressure antegrade intrapelvic povidone-iodine instillation during augmentation cystoplasty; sepsis not diagnosed (no blood cultures).
- Presentation evidence (day 0, intra/early post-operative): rigors, diffuse operative-field oozing, wound/drain-site bleeding, extensive ecchymoses, abdominal distension, vasopressor-requiring hypotension; initial post-op labs Hb 6.6, plt 91, INR 2.46, aPTT 60.6, Cr 1.57 (exactly 5 quantitative labs; no numeric vitals); US no intra-abdominal collection.
- Files: cases/v5_case_DIC_INTRAPELVIC_POVIDONE_IODINE_PMC13522237.json; vignettes/DIC_INTRAPELVIC_POVIDONE_IODINE_PMC13522237.txt
- validate_case.py: loads; 21 consumed axes (14 structured observations).
- Pending axes: intra_abdominal_fluid_collection_presence (created); loader-derived partial_thromboplastin_time, shock_activity.
- Notes: fibrinogen/D-dimer not measured (clinical DIC); preoperative baseline labs and re-exploration labs non-ranking.

## 5. D-SALICYLATE-TOXICITY (Salicylate toxicity)

Queries:
- broad `(salicylate OR aspirin OR ...) AND (toxicity OR poisoning OR overdose ...) AND "case report" ...` (1062 hits, dominated by unrelated aspirin-therapy papers; discarded)
- `(TITLE:salicylate OR TITLE:salicylates OR TITLE:aspirin OR TITLE:salicylism OR TITLE:"salicylic acid" OR TITLE:wintergreen OR TITLE:subsalicylate OR ABSTRACT:"salicylate toxicity" OR ABSTRACT:"salicylate poisoning" OR ABSTRACT:"salicylate overdose" OR ABSTRACT:"salicylate intoxication" OR ABSTRACT:"aspirin overdose" OR ABSTRACT:"aspirin toxicity" OR ABSTRACT:"aspirin poisoning" OR ABSTRACT:"serum salicylate" OR ABSTRACT:"salicylate level" OR ABSTRACT:"salicylate concentration") AND ("case report" OR ...) AND OPEN_ACCESS:y AND FIRST_PDATE:[2025-01-01 TO 2026-12-31]` (newest ~400 screened; plant-biology/aspirin-therapy papers title-screened out)
- cross-check: `(salicylate OR salicylates OR aspirin OR "acetylsalicylic") AND (ingestion OR overdose OR toxicity OR poisoning OR intoxication) AND (hemodialysis OR "anion gap" OR "respiratory alkalosis" OR tinnitus OR "sodium bicarbonate" OR "urinary alkalinization") AND ("case report" OR "case presentation") AND OPEN_ACCESS:y AND FIRST_PDATE:[2026-06-01 TO 2026-12-31]` (39 hits; no newer salicylate case)

Candidates examined (newest first):
1. Newer poisoning/toxicity case reports surfaced by the queries (e.g. PMC13600828 ibuprofen bronchial ulcers 2026-09-25, PMC13553892 venlafaxine 2026-08-26, PMC13534099 brodifacoum 2026-08-19, PMC13398124 ibuprofen 2026-07-16, PMC13453063 poisoning-induced rhabdomyolysis two cases 2026-07-10, PMC13436904 spinal anesthesia on chronic aspirin 2026-07-02). REJECTED: not salicylate toxicity.
2. PMC13264415 (2026-06-13) Systemic salicylate toxicity from topical emollient use in an infant with suspected ichthyosis. ACCEPTED.
(Older qualifying candidates not needed: PMC13055402 2026-04-02 chronic salicylate intoxication from incense fumes; PMC12414438 2025-08-08 delayed-diagnosis salicylate toxicity.)

ACCEPTED: case_id `SALICYLATE_TOPICAL_INFANT_PMC13264415`, PMCID PMC13264415, PMID 42292717, published 2026-06-13.
- Paper diagnosis: systemic salicylate toxicity from chronic topical 2% salicylic acid cream (serum salicylate 31 mg/dL).
- Presentation evidence: HR 204, BP 69/25; venous pH 6.98, HCO3 5.7, pCO2 22, lactate 12.15, K 6.2 with peaked T waves, albumin 2.6, PT 86.8, INR >9.36; afebrile, lethargy, irritability, vomiting, poor feeding, dehydration signs, diffuse dry scaly pruritic rash; head CT unremarkable; exposure history (topical 2% salicylic acid for months, herbal teething drops, calendula/vitamin E).
- Files: cases/v5_case_SALICYLATE_TOPICAL_INFANT_PMC13264415.json; vignettes/SALICYLATE_TOPICAL_INFANT_PMC13264415.txt
- validate_case.py: loads; 50 consumed axes (31 structured observations).
- Pending axes: herbal_product_exposure_presence, scaly_rash_presence, brain_ct_acute_abnormality_presence, cutaneous_blister_presence.
- Notes: serum salicylate level, drug screen, viral tests and dermatology/genetics are non-ranking. Tachypnea kept record-only because load_case expands tachypnea_presence=1 into respiratory_rate=1.0 (loader alias issue; same pattern seen for tachycardia_presence -> heart_rate=1.0). Venous pCO2 is loader-aliased to arterial_pco2. PT/INR timing taken from the Table 1 caption ("initial presentation unless otherwise specified").

## 6. D-TOXIC-SHOCK-SYNDROME (Toxic shock syndrome)

Query:
- `("toxic shock syndrome" OR "toxic shock" OR "streptococcal toxic shock" OR "staphylococcal toxic shock" OR STSS) AND ("case report" OR "case presentation") AND OPEN_ACCESS:y AND FIRST_PDATE:[2025-01-01 TO 2026-12-31]` (345 hits)

Candidates examined (newest first):
1. PMC13583520 (2026-09-11) Subarachnoid haemorrhage with septic cavernous sinus thrombosis from odontogenic sinusitis. REJECTED: not TSS.
2. PMC13552624 (2026-09-07) Monomicrobial Staphylococcus aureus necrotizing soft tissue infection. REJECTED: primary diagnosis NSTI (D-NECROTIZING-FASCIITIS).
3. PMC13543668 (2026-09-04) Vasopressor-associated limb ischemia in suspected septic shock. REJECTED: not TSS (complication-focused; HLH keyword).
4. PMC13581938 (2026-09-03) Fulminant group A streptococcal necrotizing fasciitis after pharyngitis. REJECTED: D-NECROTIZING-FASCIITIS.
5. PMC13527185 (2026-08-30) Streptococcal toxic shock syndrome: persistent diagnostic and therapeutic challenges. ACCEPTED.
(Older qualifying candidate not needed: PMC13455039 2026-08-10 staphylococcal TSS from insulin infusion site.)

ACCEPTED: case_id `TSS_STREPTOCOCCAL_CHEST_WALL_PHLEGMON_PMC13527185`, PMCID PMC13527185, PMID 42676585, published 2026-08-30.
- Paper diagnosis: CDC-confirmed streptococcal toxic shock syndrome (S. pyogenes emm1 bacteremia) with left chest/abdominal wall phlegmon; death within 12 h. STSS is the primary diagnosis; NF was only a differential (autopsy: phlegmon). Postmortem polymicrobial meningitis attributed to terminal translocation and autopsy-found lymphoproliferative disorder are non-ranking.
- Presentation evidence: HR 124, BP 65/44, SpO2 90% RA, GCS 13-14; CRP 453, PCT 19.38, urea 10.84 mmol/L, Cr 240 umol/L, CK 10.34 ukat/L, WBC 2.39 with differential, INR 1.44, plt 113, bilirubin 9.28 umol/L, PaO2/FiO2 208.5; phlegmon with bullae, diffuse abdominal tenderness; US colitis; CT at 2 h (left infiltrate, bilateral effusions, axillary nodes, wall phlegmon, visceral ischemic changes).
- Files: cases/v5_case_TSS_STREPTOCOCCAL_CHEST_WALL_PHLEGMON_PMC13527185.json; vignettes/TSS_STREPTOCOCCAL_CHEST_WALL_PHLEGMON_PMC13527185.txt
- validate_case.py: loads; 73 consumed axes (45 structured observations).
- Pending axes: absolute_monocyte_count, cutaneous_blister_presence, visceral_organ_ischemia_imaging_presence (created); loader-derived ocular_pain_photophobia_severity.
- Notes: explicit bilateral_pulmonary_opacity_presence=0 and pneumonia_infiltrate_extent=0.5 added because the loader alias otherwise sets bilateral opacity=1 and extent=1.0 for a left-only infiltrate; pulmonary_infiltrate_extent_egpa=1.0 from the loader alias remains (disease-named axis not overridden). Admission CXR (no infiltrate) record-only.

## Runtime loader observations (for the maintainers; no files outside the allowed folders were changed)
- `tachypnea_presence=1` is expanded by load_case into `respiratory_rate=1.0`, and `tachycardia_presence=1` into `heart_rate=1.0` (impossible numeric vitals). Avoided in these cases (tachypnea kept record-only in the salicylate case).
- `pulmonary_infiltrate_presence=1` is expanded into `bilateral_pulmonary_opacity_presence=1`, `pneumonia_infiltrate_extent=1.0`, `pulmonary_infiltrate_extent_egpa=1.0`; explicit values override.
- `fever_presence` is expanded into `infection_trigger_activity`; `venous_pco2` into `arterial_pco2`; `orthostatic_hypotension_presence` into `hypotension_presence`.
- Observations dated after `snapshot_day` are dropped by load_case; for one axis only the value closest to the snapshot is kept.

## Summary
| # | Leaf | Result | case_id | PMCID | Published | Consumed axes |
|---|------|--------|---------|-------|-----------|---------------|
| 1 | D-HLH-MAS | ACCEPTED | HLH_PEDIATRIC_REFRACTORY_FEVER_PMC13578911 | PMC13578911 | 2026-09-15 | 78 |
| 2 | D-WEST-NILE-NEUROINVASIVE-DISEASE | ACCEPTED | WNND_MENINGOENCEPHALITIS_MULTISYSTEM_PMC13615839 | PMC13615839 | 2026-08-27 | 44 |
| 3 | D-SEPSIS-GN | ACCEPTED | SEPSIS_MYROIDES_PEMPHIGUS_SKIN_PMC13588114 | PMC13588114 | 2026-09-14 | 30 |
| 4 | D-DIC | ACCEPTED | DIC_INTRAPELVIC_POVIDONE_IODINE_PMC13522237 | PMC13522237 | 2026-08-18 | 21 |
| 5 | D-SALICYLATE-TOXICITY | ACCEPTED | SALICYLATE_TOPICAL_INFANT_PMC13264415 | PMC13264415 | 2026-06-13 | 50 |
| 6 | D-TOXIC-SHOCK-SYNDROME | ACCEPTED | TSS_STREPTOCOCCAL_CHEST_WALL_PHLEGMON_PMC13527185 | PMC13527185 | 2026-08-30 | 73 |
