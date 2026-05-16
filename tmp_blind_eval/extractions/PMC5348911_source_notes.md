# PMC5348911 Blind Source Notes

## Access

- Original requested PMC URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC5348911/
- Browser/page access limitation: the normal PMC page returned a browser-check page in this environment.
- Full text used: official NCBI BioC JSON endpoint for `PMC5348911`.
- Metadata cross-check: official NCBI/PMC OAI JATS endpoint for `oai:pubmedcentral.nih.gov:5348911`.
- Local scope: only `tmp_blind_eval/make_ranking_case.py` was checked for field aliases. No local distillations, existing case JSON, ranking outputs, disease files, or held-out labels were opened.

## Source Metadata

- PMCID: `PMC5348911`
- PMID: `28288603`
- DOI: `10.1186/s12886-017-0417-3`
- Journal: `BMC Ophthalmology`
- Article type: case report
- Publication date: 2017-03-14
- Title: `Acute angle closure attack after an intravitreal bevacizumab injection for branch retinal vein occlusion: a case report`

## Extraction Boundary

Rankable observations include only diagnosis-neutral presentation and early objective evidence:

- demographics
- symptoms
- ophthalmic examination and intraocular pressure
- fundus/OCT/fluorescein angiography findings
- early emergency presentation findings

The following were kept out of rankable evidence and placed in `record_only`:

- paper diagnosis and disease framing
- bevacizumab treatment history
- mannitol and laser iridotomy treatment
- response to treatment
- late follow-up course and late biometry
- discussion interpretation

## BioC Passage Map

- Passage 0: title and article identifiers.
- Passage 12: initial clinic presentation, demographics, history, visual acuity, intraocular pressure, slit-lamp findings, anterior chamber depth, gonioscopy, refractive error, fundus findings.
- Passage 13: OCT central retinal thickness and fluorescein angiography.
- Passage 14-15: bevacizumab treatment course; used only as `record_only`.
- Passage 17: next-day emergency presentation with ocular pain, headache, nausea, vomiting, visual acuity, pupil findings, corneal edema, anterior chamber depth, intraocular pressure, diagnosis and immediate treatment. Diagnosis and treatment were excluded from rankable observations.
- Passage 18: one-month follow-up and ocular biometry; used only as `record_only`.
- Passage 23-27: discussion framing; used only as `record_only`.

## Notable Rankable Facts Extracted

- 65-year-old woman.
- Initial right-eye decreased vision for 3 days.
- Initial best corrected visual acuity: right 0.15, left 1.0.
- Initial intraocular pressure: 19 mmHg in both eyes.
- Initial exam: no afferent pupillary defect, no conjunctival/scleral injection, no corneal edema, no ocular inflammation.
- Bilateral shallow anterior chambers and narrow angles over 180 degrees on gonioscopy.
- Hyperopic refractive error: +1.00 D sphere in both eyes.
- Right fundus/OCT/angiography: flame-shaped retinal hemorrhage, macular edema, intraretinal cystic spaces, subretinal fluid, central retinal thickness 677 micrometers, delayed filling of the involved superior retinal vein.
- Emergency presentation the day after the third injection: persistent ocular pain, headache, nausea, vomiting.
- Emergency exam: right visual acuity 0.08, left visual acuity 0.9, right fixed mid-dilated 6 mm pupil, diffuse right corneal epithelial edema.
- Emergency intraocular pressure: right 56 mmHg, left 15 mmHg.

## Limitations

- The article is ophthalmology-focused and reports no systemic vitals or laboratory studies.
- The acute emergency presentation occurred months after the initial retina-clinic presentation but one day after the third injection; this is represented in the observation `time` fields.
- The article's diagnostic terms were intentionally not copied into rankable observations.
