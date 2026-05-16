# PMC5572045 Blind Source Notes

Source used: NCBI EFetch PMC XML for `PMC5572045`, plus PMC ID Converter metadata.

Article metadata:
- Title: Guillain-Barre Syndrome After Revision Lumbar Surgery: A Case Report
- Journal: Cureus
- Publication date: 2017-06-26
- PMID: 28845372
- DOI: 10.7759/cureus.1393
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC5572045/

Blinding note:
- I did not inspect local `distillations/`, `master_axes.json`, `tmp_blind_eval/cases_for_ranking/`, previous result files, or disease JSON files.
- The extraction intentionally omits expected diagnosis/manifold fields.
- Axis IDs are ordinary diagnosis-neutral clinical observations; no local atlas axis registry was consulted.

Rankable extraction basis:
- Demographics: 62-year-old female.
- Risk context: chronic headaches; prior lumbar decompression and fusion at L3-4 for degenerative lumbar stenosis; low back pain; L2-3 adjacent segment disease; recurrent L3-4 stenosis; revision lumbar decompression with anterior/posterior spinal instrumentation; incidental durotomy repair.
- Timing: discharged home 9 days after surgery; neurologic event occurred 24-36 hours after discharge. The JSON includes a derived 10-10.5 day postoperative interval with the derivation explicitly marked.
- Presentation: fall due to leg weakness; progressive bilateral lower-extremity weakness, numbness, and areflexia; ascending paralysis.
- Negative infection evidence: denied fever, chills, and infection symptoms; initial laboratory workup negative for infection.
- Imaging/electrodiagnostics: MRI only postsurgical changes; EMG with diminished upper-extremity motor/sensory amplitudes and conduction velocity, plus absent lower-extremity amplitudes and conduction velocities.

Record-only / not used for ranking:
- The paper's final diagnostic label is kept only under `record_only.final_diagnosis`.
- IVIG, intubation, tracheostomy, decannulation, rehabilitation, discharge strength, and 12-month recovery are record-only.
- CSF sampling was not performed because neurology did not recommend it after recent surgery; this is noted as diagnostic process only.

Caveats:
- The article gives no vital signs, detailed numeric laboratory values, CSF values, or exact EMG numeric measurements.
- Respiratory failure developed after admission and treatment initiation, so it was treated as late course rather than a rankable presenting observation.
- The title contains an accented character in the article XML; the JSON preserves it with a Unicode escape.
