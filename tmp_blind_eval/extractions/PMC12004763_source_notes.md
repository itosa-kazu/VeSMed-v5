# PMC12004763 Source Notes

Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC12004763/

Access note: Full text was available through NCBI PMC EFetch XML on 2026-05-17.

Rankable extraction boundary:
- Included admission symptoms, negative symptom review, CBC/differential, bilirubin, liver enzymes, LDH, evolving hemoglobin/reticulocytes, smear morphology, EBV serology, DAT, and hepatosplenomegaly.
- The etiologic diagnostic label and treatment response were not included as rankable observations.

Record-only boundary:
- Final diagnostic statement, steroid/IVIG treatment, improvement, and discharge timing were placed in `record_only`.

Caveat:
- The article reports "undirect bilirubin"; this was normalized to `indirect_bilirubin` while preserving the value.
