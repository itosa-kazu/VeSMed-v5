# PMC6075637 Source Notes

## Access

- PMC HTML page: https://pmc.ncbi.nlm.nih.gov/articles/PMC6075637/
- Normal PMC browsing returned a browser-check page in this environment.
- Official endpoint used for extraction: https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/PMC6075637/ascii
- Retrieved source metadata from BioC passage 0: PMCID `PMC6075637`, PMID `30087808`, DOI `10.7759/cureus.2732`, Cureus 2018, volume 10 issue 6, e2732.

## Blind Extraction Boundary

- Rankable observations use only presentation and early objective evidence from the abstract and Case presentation passages.
- Final diagnosis, treatment choices, treatment response, suspected trigger attribution, discontinuation, and one-week follow-up were placed in `record_only`.
- No local distillations, existing case JSON, ranking outputs, disease files, or held-out labels were inspected.
- No disease-specific observed axes were used.

## Passage Map

- BioC passage 1: abstract with age/sex, presenting headache and blurry vision, and outcome summary.
- BioC passage 5: presentation, symptom timing, symptom qualities, negative associated symptoms, recent normal eye exam, photophobia.
- BioC passage 6: oxybutynin start one week before presentation and home medication list.
- BioC passage 7: pupil exam and initial visual acuity.
- BioC passage 8: head CT negative for acute findings; ESR and CRP normal.
- BioC passage 9: slit-lamp findings, corneal edema, conjunctival injection, IOP measurements, posterior pole/optic nerve findings, initial treatment.
- BioC passage 10: post-treatment IOP/visual response and laser iridotomy.
- BioC passage 11: suspected oxybutynin trigger, discontinuation, and one-week follow-up.

## Data Limitations

- No numeric ESR or CRP values were provided; only normal-range status was extractable.
- No general vital signs were reported in the case text.
- Visual acuity was reported as counting-fingers distance at presentation; later visual acuity after treatment was excluded from rankable observations.
- IOP was reported by both Goldmann applanation and Tonopen before treatment; both were preserved as separate generic measurement axes.
