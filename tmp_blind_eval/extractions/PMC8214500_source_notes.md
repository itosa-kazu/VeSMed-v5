# PMC8214500 Blind Source Notes

## Source

- PMCID: PMC8214500
- PMID: 34164250
- DOI: 10.7759/cureus.15754
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC8214500/
- Access method: NCBI PMC BioC JSON endpoint, because the normal PMC/PubMed pages triggered browser verification in this environment.
- Article title: Occult Perforated Gangrenous Gallbladder Found on Magnetic Resonance Cholangiopancreatography

## Blindness Boundary

- I did not inspect local distillations, disease JSON files, local case JSONs, prior ranking outputs, held-out labels, or local axis registries.
- The article title and abstract reveal diagnostic wording, so they are preserved only as source metadata or `record_only`.
- Rankable observations stop at the imaging-based diagnostic snapshot: admission through day-2 MRCP, before operative confirmation and postoperative course.
- Treatment, operative findings, histopathology confirmation, response, follow-up, and discussion-only interpretation were excluded from ranking.

## Rankable Case Facts Extracted

- Demographics and background: 69-year-old male; histories of hypertension, hyperlipidemia, type 2 diabetes, and recent right pontine infarct/CVA.
- Presentation: left-sided weakness, reported loss of consciousness, mechanical fall onto the right side, bystander-reported altered mental status, alert and oriented on presentation, right-sided/right upper quadrant abdominal pain.
- Pain details: initial severity 3/10, about 4 weeks duration, exertion as the only noted trigger; day-2 severity 4/10 with inability to tolerate food.
- Admission status and exam: hemodynamically stable, SIRS criteria not met, mild right upper quadrant tenderness.
- Labs: WBC 11.8 thousand/mL, alkaline phosphatase 259 U/L, AST 259 U/L, lipase 721 U/L, CRP 18 mg/dL, hepatitis panel negative; mild leukocytosis resolved by day 2.
- Workup: syncope and stroke workups were reported as unremarkable.
- Ultrasound: gallbladder wall thickening, pericholecystic fluid, and gallbladder inflammation.
- CT abdomen/pelvis with contrast: gallbladder dilation/inflammation, wall thickening, fluid communication with the liver, and no abscess on that CT.
- MRCP/MR before surgery: fundal wall discontinuity, right upper quadrant/subcapsular abscess, and right upper quadrant phlegmonous change.

## Record-Only Items

- Diagnostic wording in the title, abstract, and MRCP interpretation.
- Conservative management and elective operation recommendation.
- Emergent operation after MRCP.
- Intraoperative and histopathology confirmation.
- Difficult operative anatomy with indistinct cystic duct and artery.
- JP drain, two-week follow-up drain removal, and absence of postoperative complications.
- Discussion-only comments about atypical presentations, diabetes risk, and imaging modality performance.

## Extraction Notes

- Imaging labels such as acute or gangrenous cholecystitis were not used as rankable axes.
- Rankable imaging entries were decomposed into neutral findings, for example wall thickening, pericholecystic fluid, wall discontinuity, and abscess/phlegmon.
- No disease-specific disease-id suffix ordinary observation axes were created.
