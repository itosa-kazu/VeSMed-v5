# Case search log: batch starting at D-DISSEMINATED-GONOCOCCAL-INFECTION

Leaves (in order): 13 D-DISSEMINATED-GONOCOCCAL-INFECTION, 14 D-CAEBV, 15 D-MALARIA-FALCIPARUM, 16 D-ANTI-GBM-DISEASE, 17 D-PROSTHETIC-JOINT-INFECTION, 18 D-VZV-ENCEPHALITIS

Method: Europe PMC REST search, `OPEN_ACCESS:y AND FIRST_PDATE:[2025-01-01 TO 2026-12-31]`, sort `P_PDATE_D desc`.
Note on ordering: `P_PDATE` sorts by the journal print/issue date (month or even year granularity; continuous-publication
journals such as Frontiers/BMC get a year-only date and sink in the list, and e.g. an article e-published 2025-10 with a
2026-06 issue date floats up). Because the goal is the MOST RECENTLY PUBLISHED case and the date filter itself uses
FIRST_PDATE, candidates were examined in order of Europe PMC `firstPublicationDate` (newest first); the API list was
re-sorted locally on that field. For leaf 13 both orderings give the same accepted case.
Known PMCIDs checked against `frozen/known_pmcids.txt` for every candidate (none of the examined candidates was known).

## 13. D-DISSEMINATED-GONOCOCCAL-INFECTION — ACCEPTED

Queries: `"disseminated gonococcal" AND "case report"` (32 hits); supplementary `("gonococcal" OR "gonococcemia" OR "gonorrhoeae bacteremia") AND "case report"` restricted to FIRST_PDATE >= 2025-12-01 (114 hits) to make sure no newer DGI case was missed.

| # | PMCID | e-pub | Title (short) | Decision |
|---|---|---|---|---|
| 1 | PMC13494393 | 2026-05-22 | Gonococcal pulmonary valve endocarditis | Rejected: paper concludes DGI with PV endocarditis, but presentation gives only 3 quantitative values (CRP 106, WBC 14.8, ANC 12.6); vitals and LFTs only qualitative (<5). |
| 2 | PMC13428636 | 2026-07-02 | AOSD presenting as FUO | Rejected: not DGI. |
| 3 | PMC13422632 | 2026-07-11 | Gonococcal mitral valve IE case series | Rejected: case series; endocarditis. |
| 4 | PMC13385518 | 2026-07-20 | Gonococcal peritonitis with abscess and empyema (cirrhosis) | Rejected: final diagnosis is gonococcal peritonitis (SBP-like), not labelled/diagnosed as DGI. |
| 5 | PMC13324233 | 2026-07-01 | Complement inhibition review | Rejected: review. |
| 6 | PMC13248566 | 2026-06-01 | Surgical management of gonococcal septic arthritis | Rejected: case series + literature review. |
| 7 | PMC13086860 | 2026-03-18 | Gonococcal infective endocarditis | Rejected: final diagnosis framed as culture-negative gonococcal IE (D-INFECTIVE-ENDOCARDITIS) with VF arrest/STEMI presentation; not presented as DGI. |
| 8 | PMC13061578 | 2026-03-09 | DGI presenting as septic wrist arthritis and endocarditis | Rejected: no quantitative presentation labs/vitals ("afebrile and hemodynamically stable", "labs unrevealing"). |
| 9 | PMC13017467 | 2026-03-01 | DGI vs uncomplicated gonorrhea case-control | Rejected: not a case report. |
| 10 | PMC12990507 | 2026-02-10 | DGI with pleuritis and pericarditis | Rejected: only 3 quantitative presentation values (CRP 213, Hb 4.5 mmol/L, MCV 89); vitals "normal" without numbers; PID also present. |
| 11 | PMC13525836 | 2026-08-27 | Genital herpes mimicking secondary syphilis | Rejected: not DGI. |
| 12 | PMC13181147 | 2026-05-17 | Rat-bite fever | Rejected: not DGI. |
| (suppl.) | PMC13012776 | 2026-02-03 | Gonococcal dacryoadenitis | Rejected: local ocular gonococcal infection, not disseminated. |
| (suppl.) | PMC12885519, PMC13149363, PMC13265607 | 2026 | Gonococcal keratoconjunctivitis / recurrent gonorrhoea / conjunctivitis | Rejected: mucosal/local gonorrhoea, not DGI. |
| 13 | PMC12778888 | 2025-12-07 | Gonococcal septic arthritis of the hip (Cureus) | Not taken: older (first published 2025-12-07) than #14; both have print date 2025-12. |
| 14 | **PMC12751404** | **2025-12-29** | Acute hepatitis secondary to DGI without Fitz-Hugh-Curtis syndrome (J Med Case Rep) | **ACCEPTED** |

Accepted: case_id `DGI_ACUTE_HEPATITIS_BACTEREMIA_PMC12751404`, PMID 41462327, published 2025-12-29.
Paper diagnosis: disseminated gonococcal infection (N. gonorrhoeae bacteremia, 1 of 2 blood-culture sets) with acute hepatitis, no Fitz-Hugh-Curtis syndrome.
Presentation quantitative data: T 38.5 C (pre-ED max), total/conjugated bilirubin, AST, ALT, ALP, total protein, albumin, Na, creatinine, venous pH, lactate.
validate_case.py: 62 consumed axes (loader alias expansion included). Pending (not in registry): bilirubinuria_presence, white_blood_cell_cast_presence, perivesical_fat_stranding_activity (+ loader-generated severity aliases: hepatic_steatosis_imaging_severity, nausea_vomiting_severity, periappendiceal_fat_stranding_severity, perivesical_fat_stranding_severity, urethral_discharge_severity).
Notes: NAAT, blood culture, exclusion serologies, day-1 MRCP, treatment and outcome are non-ranking. Loader maps tachycardia/tachypnea to qualitative_positive heart_rate/respiratory_rate and fever to infection_trigger_activity (generic loader behaviour).

## 14. D-CAEBV — ACCEPTED

Queries: `("chronic active Epstein-Barr" OR "chronic active EBV" OR CAEBV) AND "case report"` (71 hits, re-sorted by first publication date); supplementary `(CAEBVD OR "chronic active EBV disease" OR "chronic active Epstein-Barr virus disease" OR "chronic active Epstein Barr") AND ("case report" OR "case presentation")`, 2026 only (17 hits, no additional candidates).

| # | PMCID | first pub | Title (short) | Decision |
|---|---|---|---|---|
| 1 | PMC13610580 | 2026-09-19 | Thymosin alpha 1 scoping review | Rejected: review. |
| 2 | PMC13581744 | 2026-09-03 | EBV-associated inflammatory tracheal polyp | Rejected: localized reactive EBV+ polyp, not CAEBV. |
| 3 | PMC13547516 | 2026-08-24 | CD20-negative EBV+ DLBCL | Rejected: lymphoma (other leaf). |
| 4 | PMC13526991 | 2026-08-17 | Aspergillus AFOP | Rejected: not CAEBV. |
| 5 | PMC13506766 | 2026-08-12 | Fever-diarrhea-hematochezia in EBV DNA+ diseases | Rejected: case series. |
| 6 | PMC13444489 | 2026-07-24 | CNS EBV+ T-cell lymphoma after allo-HSCT | Rejected: lymphoma. |
| 7 | PMC13472967 | 2026-07-22 | Cevostamab phase 1 trial | Rejected: trial. |
| 8 | PMC13398406 | 2026-07-20 | HV-like LPD in the elderly | Rejected: paper diagnosis is hydroa vacciniforme LPD (cutaneous EBV+ T/NK LPD), not labelled CAEBV. |
| 9 | PMC13332131 | 2026-07-03 | MDS after kidney transplant | Rejected: not CAEBV. |
| 10 | PMC13363270 | 2026-07-01 | Lymphomatous transformation of CAEBV enteritis | Rejected: final diagnosis includes peripheral T-cell lymphoma (two diseases / lymphoma leaf). |
| 11 | PMC13341571 | 2026-06-24 | EBV-negative ENKTL (pediatric) | Rejected: lymphoma. |
| 12 | PMC13333671 | 2026-06-22 | Acalculous cholecystitis due to EBV/CMV | Rejected: acute infection. |
| 13 | PMC13258593 | 2026-06-01 | CD137 deficiency lymphoproliferative disease | Rejected: inborn error of immunity with lymphoma; review. |
| 14 | PMC13219206 | 2026-05-28 | GI CAEBV clinicopathological series | Rejected: research series. |
| 15 | PMC13144155 | 2026-04-22 | Severe mosquito bite allergy in an elderly patient | Rejected: paper diagnosis is EBV+ NK-cell LPD manifesting as SMBA (cutaneous form), not stated as CAEBV. |
| 16-23 | PMC13147194, PMC13139867, PMC13087428, PMC13106456, PMC13051856, PMC13195545, PMC13071793, PMC13030932 | 2026-04 to 2026-02-25 | RAG1 hypogammaglobulinemia; Talaromyces to EBV+ lymphoma; irAE enterocolitis; emapalumab review; ANKL; nodal T/NK lymphoma with HLH; EBV genome review; ENKTL | Rejected: not CAEBV / reviews / lymphoma or leukemia. |
| 24 | **PMC12963054** | **2026-02-20** | Pediatric CAEBV complicated by pulmonary arterial hypertension (Front Cardiovasc Med) | **ACCEPTED** |

Accepted: case_id `CAEBV_PEDIATRIC_PULMONARY_HYPERTENSION_PMC12963054`, PMID 41798623, published 2026-02-20.
Paper diagnosis: CAEBV complicated by PAH (and grade II heart failure) in an 11-year-old girl; CAEBV confirmed by EBV serology, EBV DNA load and EBER+ skin biopsy (all non-ranking).
Presentation quantitative data: T, HR, RR, BP, WBC, platelets, Hb, CRP, ESR, NT-proBNP, AST, ALT, bilirubin, albumin, echo PASP, RHC pressures.
validate_case.py: 49 consumed axes. Pending (not in registry): eczematous_rash_presence, loud_pulmonic_second_heart_sound_presence, right_atrial_enlargement_presence, right_ventricular_dilation_presence (+ loader-generated aliases ctpa_pulmonary_arterial_filling_defect_severity, pulmonary_hypertension_severity, tricuspid_regurgitation_activity).
Notes: next older candidates would have been PMC12916533 (2026-02-19) and PMC12955430 (2026-02-09, CAEBV+HLH+NK/T lymphoma, would be rejected). Under the raw P_PDATE order PMC13294587 (Internal Medicine, e-published 2025-10-23, issue 2026-06) would have come earlier; it is older by publication date.

## 15. D-MALARIA-FALCIPARUM — ACCEPTED

Queries: `("falciparum malaria" OR "Plasmodium falciparum") AND "case report"`, FIRST_PDATE 2026 (128 hits, re-sorted by first publication date); supplementary `malaria AND ("case report" OR "case presentation")` with FIRST_PDATE >= 2026-08-27 (32 hits) to confirm nothing newer qualifies.

| # | PMCID | first pub | Title (short) | Decision |
|---|---|---|---|---|
| 1-6 | PMC13604310, PMC13612534, PMC13601711, PMC13599970, PMC13491101, PMC13577489 | 2026-09-25 to 2026-09-08 | mefloquine review; RNA therapeutics review; Burkitt lymphoma; supplement trial protocol; malaria-sepsis cohort; actinomycetoma qPCR | Rejected: not falciparum malaria case reports. |
| 7 | PMC13613134 | 2026-08-31 | Quinine-induced torsade de pointes unmasking KCNH2 variant | Rejected: paper's primary diagnosis is drug-induced TdP / latent LQT2 during treatment; malaria is background (two diagnoses). |
| 8 | (preprint, no PMCID) | 2026-08-31 | AL vs DHA-PQ effectiveness | Rejected: not a case report, not PMC. |
| 9 | PMC13527393 | 2026-08-30 | Malaria-associated secondary HLH | Rejected: primary diagnosis secondary HLH (D-HLH-MAS leaf) triggered by malaria; two diseases. |
| 10 | PMC13561912 | 2026-08-28 | Balamuthia encephalitis | Rejected: not malaria. |
| 11 | **PMC13521499** | **2026-08-27** | Immunomodulation therapy for severe malaria with multiple organ failure (Crit Care Explor) | **ACCEPTED** |

Accepted: case_id `MALARIA_FALCIPARUM_PEDIATRIC_SEVERE_MOF_PMC13521499`, PMID 42644869, published 2026-08-27.
Paper diagnosis: severe Plasmodium falciparum malaria complicated by shock and multiple organ dysfunction (5-year-old girl returning from DR Congo, parasitemia 10.9%).
Presentation quantitative data: T 103.5 F, WBC, Hb, platelets, BUN, creatinine, K, bilirubin, AST, ALT, lactate.
validate_case.py: 50 consumed axes, no pending axes.
Notes: smear parasitemia/species, negative blood cultures, unquantified "hemolysis and inflammation" on repeat labs, and the later course (TMA, cytokines, arrest) are non-ranking. Vignette words the travel history neutrally ("did not take any chemoprophylaxis for the trip").

## 16. D-ANTI-GBM-DISEASE — ACCEPTED

Queries: the unrestricted full-text query with "anti-GBM" returned 14,326 mostly irrelevant hits (hyphen tokenisation), so it was replaced by
`(TITLE/ABSTRACT:"anti-glomerular basement membrane" OR TITLE/ABSTRACT:Goodpasture OR TITLE/ABSTRACT:"anti-GBM") AND ("case report" OR "case presentation")`, FIRST_PDATE >= 2025-06-01 (49 hits, re-sorted by first publication date), plus a full-text check `("anti-glomerular basement membrane disease" OR "anti-GBM disease" OR "anti-GBM antibody disease" OR "Goodpasture syndrome" OR "Goodpasture disease" OR "anti-GBM glomerulonephritis" OR "anti-GBM nephritis")` with FIRST_PDATE >= 2026-07-01 (14 hits; nothing newer than the accepted case).

| # | PMCID | first pub | Title (short) | Decision |
|---|---|---|---|---|
| (full-text check) | PMC13575755, PMC13567810, PMC13541764, PMC13606325, PMC13530900 | 2026-09-16 to 2026-08-18 | AE review; TPE cohort; COPA syndrome; SRP myopathy; MPA | Rejected: not anti-GBM disease case reports. |
| 1 | **PMC13474007** | **2026-07-31** | Elderly anti-GBM antibody disease with diffuse non-hereditary GBM thinning (Front Med) | **ACCEPTED** |
| next (not needed) | PMC13496380 (2026-07-22, anti-GBM + IgA nephropathy), PMC13551696 (IgAN then anti-GBM), PMC13236267 (anti-GBM + p-ANCA) | | | Would be rejected as two combined diseases. |

Accepted: case_id `ANTI_GBM_ELDERLY_FEVER_CRESCENTIC_GN_PMC13474007`, PMID 42602475, published 2026-07-31.
Paper diagnosis: anti-GBM antibody disease (serum anti-GBM 208 U/mL, ANCA negative) with RPGN/crescentic GN, atypical absence of linear IgG, and diffuse non-hereditary GBM thinning (histologic finding, not a separate leaf).
Presentation: reconstructed from the pre-treatment timeline; day 0 = 2025-08-05 renal labs (creatinine 293 umol/L, urine RBC 2,424/uL, protein +, 24-h protein 0.321 g); day -6 first visit (T max 38.7 C, WBC 10.53, CRP 218.4; fever, pharyngeal discomfort, cough, low back pain, dysuria). The paper's formal admission (2025-08-30) was post-treatment and is non-ranking.
validate_case.py: 24 consumed axes. Pending (not in registry): urine_rbc_per_ul.
Notes: the loader drops observations with day > snapshot_day, so time zero was anchored at the latest pre-treatment evaluation (2025-08-05) and earlier findings carry negative days.

## 17. D-PROSTHETIC-JOINT-INFECTION — ACCEPTED

Queries: `("prosthetic joint infection" OR "periprosthetic joint infection" OR "periprosthetic infection") AND ("case report" OR "case presentation")`, FIRST_PDATE >= 2026-05-01 (107 hits, re-sorted by first publication date); supplementary `("infected total knee" OR "infected total hip" OR "infected arthroplasty" OR "infected prosthesis" OR ... OR PJI OR periprosthetic)` with FIRST_PDATE >= 2026-08-28 (25 hits; no additional qualifying case).

| # | PMCID | first pub | Title (short) | Decision |
|---|---|---|---|---|
| 1-4, 6 | PMC13583925, PMC13581489, PMC13596950, PMC13583874, PMC13604342 | 2026-09-17 to 2026-09-09 | bone-graft histology; CRP after TKA; SESAME guideline; trial protocol; editorial | Rejected: not PJI case reports. |
| (suppl.) | PMC13605510, PMC13575784, PMC13612564, PMC13609269 | 2026-09-17 to 2026-09-09 | scapular reconstruction; Takayasu; THA in fibrous dysplasia; port infection | Rejected: not PJI. |
| 5 | PMC13563194 | 2026-09-10 | Polymicrobial MDR post-traumatic chronic hip infection | Rejected: fracture-related infection after explantation; only 1 quantitative value (CRP 12.8). |
| 7 | PMC13555810 | 2026-09-09 | S. caprae PJI treated with bacteriophage | Rejected: chronic 7-year PJI; only CRP and ESR reported (<5). |
| 8 | PMC13561124 | 2026-09-06 | Total femoral replacement for periprosthetic fracture | Rejected: fracture, not infection. |
| (suppl.) | PMC13582182, PMC13535851, PMC13585330, PMC13552156, PMC13552051, PMC13552043, PMC13533197 | 2026-09-03 to 2026-09-01 | post-traumatic calcaneal osteomyelitis; peri-implant fracture; RTSA technique; Ewing sarcoma; vWD hematoma; metallosis; periprosthetic nonunion | Rejected: not PJI. |
| 9 | PMC13552059 | 2026-09-01 | Iliopsoas abscess as initial manifestation of hip PJI | Rejected: only CRP (~100 mg/L) quantitative at presentation (<5). |
| 10, 11 | PMC13533618, PMC13553559 | 2026-09-01, 2026-08-31 | recurrent dislocations; retained trial head | Rejected: not infection. |
| 12 | **PMC13522984** | **2026-08-28** | Haemophilus parainfluenzae PJI (Case Rep Infect Dis), Case #1 | **ACCEPTED** |

Accepted: case_id `PJI_KNEE_REVISION_ACUTE_PMC13522984`, PMID 42666548, published 2026-08-28.
Paper diagnosis: periprosthetic joint infection of a revision left TKA caused by H. parainfluenzae (Case #1 of a two-patient report; only Case #1 structured).
Presentation quantitative data: synovial WBC 107,500/uL, PMN 87%, synovial RBC 16,000/uL, leukocyte esterase 3+, ESR 25 mm/h, CRP 143.7 mg/L; afebrile.
validate_case.py: 18 consumed axes. Pending (not in registry): joint_pain_duration_days, synovial_fluid_rbc_count, synovial_fluid_leukocyte_esterase_grade.
Notes: intraoperative culture species and negative blood cultures are non-ranking. The prosthesis is encoded once, as observed context axes (prosthetic_joint_presence, total_knee_arthroplasty_presence, prosthetic_joint_age_days).

## 18. D-VZV-ENCEPHALITIS — ACCEPTED

Queries: `("varicella zoster" OR "varicella-zoster" OR VZV OR "herpes zoster" OR varicella) AND encephalitis AND ("case report" OR "case presentation")`, FIRST_PDATE >= 2026-04-01 (153 hits, re-sorted by first publication date); supplementary `(... VZV/zoster/varicella ...) AND (meningoencephalitis OR cerebellitis OR rhombencephalitis OR encephalomyelitis OR "CNS infection" OR "central nervous system infection" OR "VZV encephalitis")`, FIRST_PDATE >= 2026-08-06 (25 hits; nothing newer qualifies).

| # | PMCID | first pub | Title (short) | Decision |
|---|---|---|---|---|
| 1-4 | PMC13601674, PMC13596908, PMC13584348, PMC13563053 | 2026-09-23 to 2026-09-10 | MOGAD ADEM; HSV-1 mucocutaneous; congress abstracts; post-pump chorea | Rejected: not VZV encephalitis. |
| 5 | PMC13491082 | 2026-09-09 | Neonatal varicella | Rejected: neonatal varicella without encephalitis. |
| 6-12 | PMC13597404, PMC13547796, PMC13611556, PMC13581956, PMC13565770, PMC13616433, PMC13561995 | 2026-09-09 to 2026-08-28 | spinal GBM; calciphylaxis; WNV review; C. pneumoniae rash; HSV encephalitis; valproate encephalopathy; post-CMV brainstem encephalitis | Rejected: not VZV encephalitis. |
| 13 | PMC13522382 | 2026-08-27 | Bilateral facial palsy after childhood varicella | Rejected: cranial neuropathy, no encephalitis. |
| 14-24 | PMC13615839, PMC13519284, PMC13504668, PMC13504358, PMC13515163, PMC13541693, PMC13529704, PMC13524448, PMC13511364, PMC13478797, PMC13477451 | 2026-08-27 to 2026-08-15 | WNV; HHV-6 meningitis; catatonia; MOGAD; fungal review; MOG cortical encephalitis; mGluR1 encephalitis; disseminated zoster (pulmonary); Kaposi varicelliform eruption; Salmonella meningitis; NMOSD review | Rejected: not VZV encephalitis. |
| 25 | PMC13571562 | 2026-08-14 | VZV and EBV meningitis, two cases | Rejected: VZV meningitis with normal imaging, not encephalitis (D-VIRAL-MENINGITIS). |
| 26-27 | PMC13574258, PMC13549707 | 2026-08-12, 2026-08-08 | WNV AFP/GBS; small fibre neuropathy | Rejected: not VZV. |
| 28 | **PMC13560155** | **2026-08-06** | Rashless VZV encephalitis diagnosed by mNGS: two case reports (BMC Neurol), Case 1 | **ACCEPTED** |

Accepted: case_id `VZV_ENCEPHALITIS_RASHLESS_MULTIFOCAL_PMC13560155`, PMID 42723024, published 2026-08-06.
Paper diagnosis: rashless VZV encephalitis (CSF mNGS 252 VZV reads), later possible VZV vasculopathy (Case 1, 68-year-old man; Case 2 not structured).
Presentation quantitative data: CSF opening pressure 200 mmH2O, CSF WBC 400/uL, protein 2.05 g/L, glucose 3.9 mmol/L, chloride 108 mmol/L (no numeric vitals or blood tests reported).
validate_case.py: 36 consumed axes. Pending (not in registry): csf_chloride, eeg_background_abnormality_presence, mri_brainstem_lesion_presence (+ loader alias mri_temporal_lobe_hyperintensity_severity).
Notes: CSF mNGS, serum VZV IgG, CSF cytology (suspected atypical lymphocytes), weakly positive serum GABAB-R antibody and other exclusion tests are non-ranking. Absence of rash kept as rankable negative evidence.

## Summary

| Leaf | Status | case_id | PMCID | Published | Consumed axes | Pending axes |
|---|---|---|---|---|---|---|
| 13 D-DISSEMINATED-GONOCOCCAL-INFECTION | ACCEPTED | DGI_ACUTE_HEPATITIS_BACTEREMIA_PMC12751404 | PMC12751404 | 2025-12-29 | 62 | bilirubinuria_presence, white_blood_cell_cast_presence, perivesical_fat_stranding_activity (+5 loader severity aliases) |
| 14 D-CAEBV | ACCEPTED | CAEBV_PEDIATRIC_PULMONARY_HYPERTENSION_PMC12963054 | PMC12963054 | 2026-02-20 | 49 | eczematous_rash_presence, loud_pulmonic_second_heart_sound_presence, right_atrial_enlargement_presence, right_ventricular_dilation_presence (+3 loader aliases) |
| 15 D-MALARIA-FALCIPARUM | ACCEPTED | MALARIA_FALCIPARUM_PEDIATRIC_SEVERE_MOF_PMC13521499 | PMC13521499 | 2026-08-27 | 50 | none |
| 16 D-ANTI-GBM-DISEASE | ACCEPTED | ANTI_GBM_ELDERLY_FEVER_CRESCENTIC_GN_PMC13474007 | PMC13474007 | 2026-07-31 | 24 | urine_rbc_per_ul |
| 17 D-PROSTHETIC-JOINT-INFECTION | ACCEPTED | PJI_KNEE_REVISION_ACUTE_PMC13522984 | PMC13522984 | 2026-08-28 | 18 | joint_pain_duration_days, synovial_fluid_rbc_count, synovial_fluid_leukocyte_esterase_grade |
| 18 D-VZV-ENCEPHALITIS | ACCEPTED | VZV_ENCEPHALITIS_RASHLESS_MULTIFOCAL_PMC13560155 | PMC13560155 | 2026-08-06 | 36 | csf_chloride, eeg_background_abnormality_presence, mri_brainstem_lesion_presence (+1 loader alias) |

Files: research/blind_vs_llm/cases/v5_case_<case_id>.json and research/blind_vs_llm/vignettes/<case_id>.txt for each accepted case. No distillation file `distillations/v5_*.json` was opened; the only file read under distillations/ was the permitted format example `distillations/cases/v5_case_ITP_ADULT_MALE_PURPURA_GINGIVAL_PMC10628603.json`; nothing was written under distillations/; no ranking was run (only validate_case.py).
