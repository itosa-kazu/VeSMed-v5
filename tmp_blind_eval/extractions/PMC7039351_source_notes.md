# PMC7039351 Source Notes

## Access

- Primary PMC URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC7039351/
- Normal PMC browsing returned a browser-checking page.
- Full text was accessed through the official NCBI PMC BioC JSON endpoint: https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/PMC7039351/unicode
- PMC OA utility endpoint tried: https://pmc.ncbi.nlm.nih.gov/utils/oa/oa.fcgi?id=PMC7039351 returned 404 in this environment.

## Metadata

- PMCID: PMC7039351
- PMID: 32140338
- DOI: 10.7759/cureus.6771
- Journal: Cureus
- Published: 2020-01-25
- Title: Airway Management for an Adult Epiglottic Abscess

## Blind Extraction Boundary

Only presentation and early objective evidence was used in `rankable_observations`: demographics, pregnancy/risk context, presenting symptoms, ED vitals, ED exam, WBC, CT neck findings, and early airway/laryngoscopy findings before drainage. Diagnostic labels, treatment choices, response to therapy, operative details, culture results after the acute course, discharge timing, and discussion framing were placed in `record_only`.

No disease-specific ordinary observation axes were used. No expected manifold, expected disease id, held-out label, or paper diagnosis field was added to the JSON.

## Rankable Evidence Summary

- Patient: 33-year-old female.
- Risk context: pregnancy at 12 weeks, tobacco dependence, cannabis history before pregnancy, prior tonsillectomy, carious/fractured tooth, recent throat trauma from a swallowed tooth fragment, and no prenatal care yet.
- Symptoms at ED presentation: odynophagia, sore throat/pharyngitis, hoarseness/dysphonia, dyspnea worsened by lying down, drooling, and generalized malaise.
- ED vitals: temperature 36.9 C, heart rate 110/min, blood pressure 115/61 mmHg, respiratory rate 22/min, oxygen saturation 99% on room air.
- ED exam: sitting upright, unable to swallow saliva, and no appreciated stridor.
- Laboratory: WBC 16670/uL.
- CT neck: marked epiglottic edema, 1.8 cm vallecular/epiglottic fluid collection, aryepiglottic fold edema, extension into the hypopharynx, and moderate upper-airway stenosis most prominent at the aryepiglottic folds.
- Preoperative/airway exam after initial medical therapy: anterior neck tenderness, cervical lymphadenopathy, frequent suctioning requirement, Mallampati II, thyromental distance greater than 6 cm, two missing teeth, and no limitation of neck movement.
- Laryngoscopy before drainage: severe epiglottic swelling and purulent upper-airway discharge.

## Record-Only Summary

- The paper's diagnostic framing was acute epiglottitis with developing epiglottic abscess; this was not used as ranking evidence.
- Management details included OMFS/OB consultation, intravenous clindamycin and dexamethasone, planned direct laryngoscopy/exploration, inhalational induction with video laryngoscopy, successful intubation, and drainage/biopsy.
- Treatment response and late course were kept out of ranking: overnight improvement, postoperative symptom improvement, discharge on postoperative day 2, and negative blood/intraoperative cultures.

