# PMC6411205 Blind Source Notes

## Source Metadata

- PMCID: PMC6411205
- PMID: 30882008
- DOI: 10.1093/ofid/ofy354
- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC6411205/
- Full text used because the PMC page was inaccessible through the browser challenge: https://academic.oup.com/ofid/article/6/3/ofy354/5261207
- OA PDF URL from NCBI OA utility: ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_pdf/3d/37/ofy354.PMC6411205.pdf
- Citation: Pettengill MA, Babu TM, Prasad P, Chuang S, Drage MG, Menegus M, Lamson DM, Lu X, Erdman D, Pecora N. Open Forum Infectious Diseases. 2019;6(3):ofy354.

## Blindness Handling

- Selected case: Patient 1 only.
- The article title, abstract-level diagnostic framing, final diagnosis wording, and discussion causal interpretation were not used as rankable evidence.
- No expected disease label or expected disease ID was included.
- No local distillation, local case, local expected-label, or ranking-output contents were used for extraction.
- The article also describes Patient 2 and donor context. Those facts were kept as record-only related context, not as Patient 1 ranking evidence.

## Rankable Chronology Paraphrase

Patient 1 was a 36-year-old male kidney transplant recipient with end-stage renal disease attributed to sclerosing glomerulonephritis. He had received a deceased donor kidney transplant about 1 month earlier, with antithymocyte globulin induction and ongoing tacrolimus, mycophenolate mofetil, prednisone, and anti-infective prophylaxis.

He presented after 3 days of urinary and graft-localizing symptoms: allograft tenderness, hematuria, fever, dysuria, and urinary retention. On admission he had low-grade fever but was hemodynamically stable, with marked tenderness over the allograft.

Admission labs showed WBC 5.9 x 10^3/uL with lymphopenia, hemoglobin 10.7 g/dL, platelets 166 x 10^3/uL, and creatinine 1.69 mg/dL compared with a recent post-transplant low of 1.15 mg/dL. Liver function tests were normal. Urine microscopy showed many RBCs and WBCs, but the article did not state the denominator.

Admission abdominal CT showed perinephric stranding. By hospital day 3, allograft tenderness worsened and fever rose as high as 40 C. Repeat abdominal CT showed progression of perinephric stranding and allograft edema. Blood and urine cultures were negative.

During the diagnostic work-up, serum adenovirus nucleic acid testing was positive at about 6.0 x 10^6 genome copies/mL, and molecular typing identified HAdV-34. Kidney allograft biopsy showed tubular necrosis in a pauci-inflammatory background, smudge chromatin in residual tubular epithelium, intraluminal necrotic debris, and positive adenovirus immunohistochemistry. These were treated as observed test/pathology facts, not as an expected label.

## Record-Only Exclusions

- Empiric antibiotics, initial improvement, cidofovir/probenecid, decreased immunosuppression, viral clearance, creatinine at treatment completion, symptom resolution, and renal recovery were excluded from ranking because they are treatment/response or follow-up facts.
- The source's interpretive wording that the biopsy findings were characteristic of adenovirus infection was not used as rankable evidence; only the raw biopsy and test observations were extracted.
- Retrospective serology used to reason about timing and donor-derived transmission was kept record-only.
- Donor findings and other-organ recipient monitoring were kept record-only because they are epidemiologic/source context rather than Patient 1 presentation facts.
- Patient 2's clinical course was kept record-only because this extraction is for Patient 1.
- Discussion statements about rarity, latency, environmental acquisition, and screening recommendations were excluded from ranking.

## Axis Naming Uncertainties

- `renal_allograft_tenderness_presence` may need normalization to `transplant_kidney_tenderness_presence` or `graft_tenderness_presence`.
- Urine RBC/WBC counts lack an article-specified denominator, so downstream code should avoid assuming per high-power field unless normalized elsewhere.
- CT findings such as `perinephric_stranding_presence` and `renal_allograft_edema_presence` may be satellites under a broader renal allograft inflammatory imaging axis.
- Pathogen-specific axes such as `serum_human_adenovirus_pcr_viral_load`, `human_adenovirus_hexon_gene_typing_result`, and `adenovirus_immunohistochemistry_positive` may be better represented as generic pathogen-test axes with organism metadata.
- The normal liver function statement is broad; the source does not provide AST, ALT, alkaline phosphatase, bilirubin, or other individual values.
