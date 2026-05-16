# PMC4896173 Blind Extraction Source Notes

## Access

- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC4896173/
- PMCID: PMC4896173
- PMID: 27303519
- DOI: 10.2484/rcr.v3i2.157
- Browser access to the interactive PMC page was blocked by a reCAPTCHA interstitial in the browser tool.
- Full text was retrieved as JATS XML through NCBI EFetch:
  `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=PMC4896173&retmode=xml`

## Extraction Boundary

- Included for ranking: Case Report paragraphs 1-5 only.
- Ranking evidence includes acute ED neurologic presentation, rapid early deterioration, six-week antecedent transient neurologic symptoms, vascular risk context, pre-intervention CT/CTA/perfusion findings, and normal routine labs/chest x-ray/ECG.
- Kept record-only: prehospital aspirin, intubation as airway management, IV/IA treatment decisions, catheter angiography procedural details, thrombolysis/angioplasty/stenting, post-treatment MRI/MRA, neurologic recovery, later functional outcome, aspiration pneumonitis after admission, and discussion causal framing.
- Article title, abstract wording, final diagnosis phrasing, treatment response, and discussion interpretation were not used as rankable observations.
- Existing local `distillations/cases` files were intentionally not read.
- No expected diagnosis/manifold field or final diagnosis field was added.

## Evidence Pointers

- Case Report paragraph 1: demographics; sudden onset; right hand numbness; speech/facial/limb symptoms; nausea/vomiting; GCS and NIHSS; impaired orientation/commands; dysarthria; absent gag; shivering; hemiparesis; hyperreflexia; extensor plantar responses; posturing; early decline with quadriparesis, dyspnea, tachypnea, falling oxygen saturation, and vomiting.
- Case Report paragraph 2: six weeks of brief recurrent vertigo, visual blurring, disequilibrium, and gait instability; negative vascular risk history; no prior cardiac/cerebrovascular history; no smoking, hypertension, diabetes, hyperlipidemia, peripheral vascular disease, or family history of stroke; no home medications; remote prostate cancer; otherwise good baseline health.
- Case Report paragraph 3: unenhanced head CT without hemorrhage or early infarction; ASPECTS 10; hyperdense basilar artery; motion-limited CT perfusion with posterior territory time-to-peak delay; CTA unopacified basilar segment; posterior communicating collateral filling; cervical vertebral arteries without disease.
- Case Report paragraph 4: coma at 2.5 hours and airway/therapy decision; coma was rankable, airway and therapy decisions were record-only.
- Case Report paragraph 5: routine labs, chest x-ray, and ECG reported normal.
- Case Report paragraphs 6-9 and Discussion: retained only as record-only context.

## Registry Notes

- Reused registry axis IDs where exact or close diagnosis-neutral matches existed, including `neurologic_deficit_presence`, `focal_neurologic_deficit_presence`, `mental_status_abnormality_presence`, `glasgow_coma_scale`, `nih_stroke_scale`, `dysarthria_presence`, `facial_droop_presence`, `limb_sensory_abnormality_presence`, `hemiparesis_presence`, `quadriparesis_presence`, `hyperreflexia_presence`, `babinski_sign_presence`, `weak_gag_reflex_presence`, `vertigo_presence`, `blurred_vision_presence`, `gait_disturbance_presence`, `nausea_presence`, `vomiting_presence`, `respiratory_distress_presence`, `dyspnea_presence`, `tachypnea_presence`, `coma_presence`, `intracerebral_hemorrhage_ct_presence`, `brain_ischemic_infarct_presence`, `aspects_score`, `hyperdense_artery_sign_presence`, `intracranial_arterial_occlusion_presence`, `large_vessel_occlusion_presence`, `basilar_artery_occlusion_activity`, and `collateral_flow_adequacy`.
- Suggested generic axis IDs were used where the registry lacked exact neutral IDs: `time_since_neurologic_symptom_onset_hours`, `sudden_onset_neurologic_deficit_presence`, `subacute_recurrent_transient_neurologic_episodes_presence`, `transient_neurologic_episode_duration_seconds`, `prior_cardiac_disease_history_presence`, `prior_cerebrovascular_disease_history_presence`, `peripheral_vascular_disease_history_presence`, `family_history_of_stroke_presence`, `active_home_medication_use_presence`, `remote_prostate_cancer_history_presence`, `good_baseline_health_context_presence`, `command_following_impairment_presence`, `verbal_output_impairment_presence`, `decerebrate_posturing_presence`, `oxygen_saturation_decline_presence`, `routine_laboratory_abnormality_presence`, `ecg_abnormality_presence`, `posterior_cerebral_artery_territory_perfusion_delay_presence`, `basilar_artery_unopacified_segment_length_cm`, `posterior_communicating_artery_collateral_flow_presence`, `cervical_vertebral_artery_disease_presence`, and `chest_xray_acute_cardiopulmonary_abnormality_presence`.

## Boundary Doubts

- The CTA basilar occlusion and hyperdense basilar sign are diagnosis-defining imaging observations, but they were retained as rankable because they are objective pre-treatment imaging findings from the Case Report body, not title/abstract/final diagnosis text.
- The catheter angiogram in paragraph 6 also confirmed the occlusion before intra-arterial therapy, but it was excluded from ranking because it is embedded in the procedural treatment sequence and duplicates the pre-intervention CTA observation.
- Normal routine laboratory studies were kept as a broad negative observation because no individual lab values were provided.
- Intubation was record-only as an intervention; the preceding dyspnea, tachypnea, oxygen saturation decline, and coma were kept as rankable clinical severity observations.
