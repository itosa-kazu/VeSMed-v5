# PMC12074618 Blind Source Notes

## Source identifiers

- PMCID: PMC12074618
- PMID: 40365554
- DOI: 10.1159/000544927
- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC12074618/
- PubMed/PMC metadata: Case Rep Gastroenterol. 2025;19(1):340-351, epub 2025-05-13.

## Access notes

- The normal PMC web page returned a reCAPTCHA page in the browser tool, so I used NLM/NCBI source endpoints for the same PMCID:
  - PMC OAI-PMH JATS XML for full text.
  - NCBI PMC BioC JSON for sectioned passage/table extraction.
  - PubMed esummary for PMID/DOI/source metadata.
- I did not read local distillations, local case labels, cases_for_ranking, tmp_blind_eval results, or existing blind extraction files.
- I did not use the article title or diagnosis-bearing headings as diagnostic evidence.

## Extraction boundary

- Ranking-eligible: demographics, risk context, presenting symptoms, review-of-systems negatives, admission exam, admission/early labs, raw serology/autoimmune tests, raw copper-related tests, early imaging, upper endoscopy findings, and day-3 renal ultrasound.
- Record-only / excluded from ranking: final diagnostic wording, treatment/procedures, transplant logistics, post-treatment improvement, discharge medications, late follow-up, late genetic result, and discussion/literature-review interpretation.

## Key source evidence used

- Presentation: 32-year-old female; jaundice, nausea, bilious vomiting, low-grade/unrecorded fever, fatigue, somnolence, and one black-stool episode.
- Risk context: previously healthy, 7 months postpartum, no prior liver disease, no recent travel, no heavy alcohol use, no IV drug use, no new/herbal medications, therapeutic-dose acetaminophen exposure, no smoking/alcohol history, and no significant GI/hematologic family history.
- Admission exam: hemodynamically stable by narrative, right-upper-quadrant tenderness, hepatomegaly with 14 cm liver span and 4 cm below right costal margin, abdominal distension, and flank dullness.
- Admission labs: hemoglobin 3.9 g/dL, WBC 18.4 x10^9/L, platelets 198 x10^9/L, total bilirubin 270 in source table unit, ALP <24 U/L, AST 144 U/L, ALT 22 U/L, albumin 27.5 g/L, INR 3.0, BUN 31.4 mg/dL, sodium 136 mEq/L.
- Additional labs/tests: LDH 776 U/L, reticulocytes 12.9%, fibrinogen 251 mg/dL, ceruloplasmin 0.19 g/L, serum copper 138 ug/dL, 24-hour urine copper 12,943 ug/24h, low C3/C4, PT 13.5 s, PTT 33.2 s, negative acute viral hepatitis markers, negative autoimmune markers, negative direct Coombs test, and blood smear with spherocytes/echinocytes/polychromasia.
- Imaging/procedures before final framing: clinic ultrasound showed hepatomegaly and gallbladder edema/sludge; MRCP showed mild-moderate hepatomegaly, gallbladder distension/edema, no stones, and no bile-duct dilation; Doppler ultrasound was normal; triphasic CT showed no cholecystitis or thrombosis; upper endoscopy showed no mucosal bleeding lesions or varices; day-3 ultrasound showed nephromegaly.

## Axis naming uncertainties

- The source table labels total bilirubin with `U/L`, which is not a usual bilirubin concentration unit. I preserved the source value and flagged the unit uncertainty in JSON.
- The source table gives day-1 creatinine as `10.0 umol/L`, while the narrative describes initial creatinine as elevated. I preserved the printed table value and flagged the contradiction.
- I used `slit_lamp_corneal_ring_presence` instead of a diagnosis-specific axis name.
- Disease-specific prognostic index names/values were not encoded as rankable observations; raw labs and the generic MELD score were retained.
