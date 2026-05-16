# PMC8716199 Blind Source Notes

## Source And Scope

- Source used: PMC full-text XML for PMCID `PMC8716199`, plus PMC OA metadata for archive/PDF availability.
- Citation metadata is preserved in the JSON, including the title, but the title was not used as rankable evidence.
- Rankable extraction was limited to the presentation and pre-diagnostic chronology in the Case Report section, with admission values from Table 1.
- The abstract, author-stated final diagnosis, treatment course, response, discharge plan, follow-up labs, and Discussion interpretation were kept out of rankable observations.
- No local distillation, local case, ranking-output, or expected-label files were read for this extraction.

## Rankable Chronology Paraphrase

A 37-year-old male presented after waking from sleep with acute generalized weakness and inability to move his limbs. He had experienced milder similar weakness after prolonged rest in the past. He reported no recent medication or drug use and no recent diarrhea, infection, or trauma, and the case report states no significant past medical history.

On ED arrival, blood pressure was 98/50 mmHg and heart rate was 84/min. Weakness had partly improved during transport, but exam still showed weakness in all four limbs and inability to walk. Sensation was intact, and there was no fecal or urinary incontinence.

During the initial ED history and lab draw, the patient had cardiac arrest. ECG before arrest showed sinus rhythm with PR prolongation and QRS widening. Admission labs before arrest showed severe hyperkalemia, hyponatremia, and elevated creatinine. Table 1 also provides admission BUN, glucose, chloride, CPK, serum osmolality, urine osmolality, urine sodium, urine potassium, direct renin, ACTH, cortisol, aldosterone, and TSH.

Pre-diagnostic workup included unremarkable brain and cervical spine MRI, negative respiratory pathogen panel including enteroviruses, negative HIV and CMV serologies, normal TSH with negative thyroid peroxidase antibody, negative urine toxicology screen, and negative vasculitis/autoimmune serologies listed in the case report. Urinary retention was not seen on imaging, and a Foley catheter was draining. CPK and myoglobin were described as not supporting rhabdomyolysis. Endocrine/renal workup found very low cortisol, elevated ACTH, elevated renin, low aldosterone, TTKG below 5, bilateral adrenal gland atrophy on imaging, and adrenal antibodies.

## Record-Only Exclusions

- Intubation, resuscitation, emergent renal replacement therapy, ICU transfer, continuous renal replacement therapy, and discharge steroid prescriptions were recorded only and marked `use_in_ranking=false`.
- Post-treatment improvement, potassium normalization, extubation, resolution of weakness, discharge instructions, and day 3/day 5/discharge/6-month lab trends were excluded from ranking.
- Author-stated final diagnosis wording was placed in `record_only` and not used as an expected label or rankable observation.
- Discussion-only causal interpretation, including proposed mechanism for kidney injury and general disease epidemiology/management comments, was excluded from ranking.
- The paper title and abstract contain diagnostic framing; they were preserved or summarized only as metadata/record-only context and were not used for rankable extraction.

## Axis Naming Uncertainties

- `prior_rest_related_weakness_episodes_presence`: may need parent `episodic_weakness_presence` plus a rest-trigger satellite.
- `weakness_improvement_en_route_to_ed_presence`: may need a symptom-course satellite rather than a standalone axis.
- `serum_creatine_phosphokinase`: may normalize to `serum_creatine_kinase` or `serum_cpk`.
- `direct_renin_concentration`: table wording should be reconciled with any existing renin activity/concentration axis.
- `plasma_acth`: may normalize to `plasma_adrenocorticotropic_hormone`.
- `transtubular_potassium_gradient`: may need a renal potassium handling axis if no TTKG axis exists.
- `foley_catheter_drainage_presence`: may be workup context rather than a rankable disease observation.
- `bilateral_adrenal_gland_atrophy_presence`: may need parent/satellite normalization for adrenal atrophy and bilateral distribution.
- `adrenal_autoantibody_positive_presence`: may normalize to a more specific adrenal cortex antibody axis.
