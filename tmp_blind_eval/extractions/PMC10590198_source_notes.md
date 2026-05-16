# PMC10590198 Blind Extraction Source Notes

## Access

- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC10590198/
- PMCID: PMC10590198
- PMID: 37868373
- Browser access to the interactive PMC page was blocked by a reCAPTCHA interstitial in the browser tool.
- Full text was retrieved as JATS XML through NCBI EFetch:
  `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=PMC10590198&retmode=xml`

## Extraction Boundary

- Included for ranking: ED presentation, pre-treatment symptoms, physical exam, vital signs, and preoperative CT findings.
- Kept record-only: paper diagnosis, admission plan, antibiotics/fluids, open appendectomy, intraoperative confirmation, ileocecal resection, and perioperative COVID testing.
- Existing local `distillations/cases` files were intentionally not read.
- No expected diagnosis/manifold field or final diagnosis field was added.

## Evidence Pointers

- Case presentation paragraph 1: demographics, RLQ pain course, fever/chills/body aches/anorexia/nausea, explicit no vomiting, regular bowel movement, anxiety history, nicotine and alcohol exposure.
- Case presentation paragraph 2: vital signs, pain score, RLQ tenderness, mild guarding, absent rebound tenderness.
- Case presentation paragraph 3 and Figure 1 caption: CT abdomen/pelvis with appendicolith, appendix enlargement/wall thickening, terminal ileal wall hyperenhancement, mild RLQ free fluid, and no loculated collection.
- Case presentation paragraph 4 and operative paragraph: admission/treatment/surgery evidence retained as record-only.

## Registry Notes

- Reused registry axis IDs where exact or close diagnosis-neutral matches existed, including `abdominal_pain_presence`, `right_lower_quadrant_pain_presence`, `vomiting_presence`, `appendicolith_presence`, `appendiceal_diameter_mm`, and `free_intraperitoneal_fluid_presence`.
- Suggested generic axis IDs were used where the registry lacked exact neutral IDs: `right_lower_quadrant_tenderness_presence`, `abdominal_guarding_presence`, `rebound_tenderness_presence`, `terminal_ileal_wall_hyperenhancement_presence`, `appendicolith_max_diameter_cm`, and `occasional_alcohol_use_context_presence`.
