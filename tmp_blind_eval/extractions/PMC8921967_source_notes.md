# PMC8921967 Blind Extraction Notes

## Access

- Requested source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC8921967/
- The interactive PMC HTML page triggered a browser check in this environment, so the full text was read through NCBI's PMC BioC JSON endpoint for the same PMCID.
- Metadata was checked through the PMC ID Converter API.
- PMCID: PMC8921967
- PMID: 35350677
- DOI: 10.1159/000522060

## Snapshot Boundary

I used the 34-week gestation emergency department presentation before antibiotics and percutaneous cholecystostomy tube placement as the diagnostic snapshot.

Rankable observations include only diagnosis-neutral facts available before or at that point: demographics, pregnancy context, medical history/risk context, symptoms, abdominal exam, Table 1 labs, and ultrasound findings. The earlier 6-week pregnancy workup was retained as prior observed history because it occurred before the snapshot.

## Evidence Used

- Case Presentation paragraph 1: age, gravida/para, gestational age, twin gestation, history, symptoms, exam, 6-week ultrasound findings, 34-week ultrasound findings, and the diagnostic decision boundary.
- Table 1: 6-week and 34-week pre-PCCT labs.
- Fig. 1 caption: ultrasound confirmation of the 6-week gallstone/CBD dilation and 34-week gallbladder sludge/nonmobile neck stone.

## Excluded From Ranking

- Article-title diagnostic wording was kept only as source metadata/record_only.
- The paper's diagnosis sentence was placed in record_only and not used as a rankable axis.
- ERCP/sphincterotomy, antibiotics, PCT placement, LC, intraoperative cholangiogram, treatment response, postpartum course, and follow-up were placed in record_only.
- Biliary fluid Gram stain and Candida dubliniensis culture were excluded from ranking because they were obtained after PCT rather than before/at the diagnostic snapshot.

## Access/Content Limitations

- No pre-snapshot vital signs were reported.
- BMI was not numeric; only class III obesity was reported.
- The 34-week pre-PCCT direct bilirubin value was blank in the table text.
- No local distillations, local case JSONs, prior ranking outputs, held-out labels, or disease files were inspected.
