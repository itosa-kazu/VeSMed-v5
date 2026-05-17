# PMC12098416 Source Notes

Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC12098416/

Access note: Full text was available through NCBI PMC EFetch XML on 2026-05-17.

Rankable extraction boundary:
- Included presentation history, admission vital signs, physical findings, initial metabolic/cardiac/endocrine labs, autoantibodies, and imaging before final diagnostic labels.
- Prior endocrine and autoimmune diagnoses were retained as risk/context facts because they were part of the patient's presentation history.

Record-only boundary:
- The article's final diagnosis list, acute management, steroid/mineralocorticoid treatment, symptom response, and follow-up course were kept in `record_only`.

Caveat:
- The paper has a table-level inconsistency around insulin autoantibody positivity; the extraction keeps the numeric Anti-GAD and ANA findings and avoids over-weighting insulin autoantibody as a separate positive observation.
