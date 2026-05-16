# PMC3383153 Blind Source Notes

## Access

- Source requested: https://pmc.ncbi.nlm.nih.gov/articles/PMC3383153/
- Direct PMC HTML access showed a browser verification page in this environment.
- Full text was accessed via NCBI BioC for the same PMCID:
  `https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_xml/PMC3383153/unicode`
- OA metadata was checked via:
  `https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC3383153`

## Source Identifiers

- PMCID: PMC3383153
- PMID: 22745881
- DOI: 10.4082/kjfm.2011.32.7.423
- Journal/source: Korean J Fam Med. 2011;32(7):423-427
- License in OA metadata: CC BY-NC

## Blindness / Exclusion Decisions

- I did not read local distillation files, local case labels, ranking cases, or prior blind-eval result files.
- I did not use the article title, keyword metadata, abstract diagnostic summary, or discussion-level causal interpretation for rankable extraction.
- The JSON contains no expected manifold field and no final diagnosis field.
- Treatment/procedure, post-treatment response, late prevention management, and final causal framing were moved to `record_only` with `use_in_ranking=false`.

## Case Presentation Passages Used

- Case paragraph offset 2677: demographics and initial symptoms.
- Case paragraph offset 3011: past history, negative histories, family history.
- Case paragraph offset 3320: vitals and physical examination.
- Case paragraph offset 3743: labs, coagulation studies, chest radiograph, initial ECG, echocardiography.
- Case paragraph offset 4686: ABI, vascular imaging, arteriography, post-intervention record-only items, and later objective rhythm testing.

## Rankable Observation Summary

- Demographics: 69-year-old female.
- Risk context: long-standing diabetes with retinopathy; long-standing hypertension; no recorded smoking, peripheral vascular disease, intermittent claudication, valvular heart disease, prior atrial fibrillation, known hypercoagulable disorder, or remarkable family history.
- Initial symptoms: sudden right calf pain and right lower-limb paresthesia for 6 days; single dizziness/brief visual blackout episode; low back pain; bilateral knee pain.
- Vitals/body metrics: BP 130/90 mmHg, pulse 76/min, temperature 36.8 degC, respiratory rate 20/min, weight 57.2 kg, BMI 25.4 kg/m2.
- Physical exam: normal heart sounds without murmur; weak right popliteal and dorsalis pedis pulses; cold and mottled right foot; smaller right calf circumference than left.
- Labs: normal CBC; lipid profile and blood chemistry reported normal except blood sugar; normal thyroid function; HbA1c 7.3%; D-dimer 0.55 ug/mL with mild elevation; antithrombin III activity 32.7%; protein S activity 54%; lupus anticoagulant and anticardiolipin IgM/IgG negative.
- Imaging/cardiac/vascular testing: mild cardiomegaly without active lung lesion; initial sinus bradycardia with ECG heart rate 56/min; echocardiographic dimensions and EF 69% with normal valves; ABI right 0.56 and left 1.1; CT angiography and arteriography showing right popliteal artery occlusion; myocardial thallium SPECT within normal range; later symptomatic ECG/Holter rhythm abnormality and later normal sinus rhythm.

## Axis Naming Uncertainty

- `routine_blood_chemistry_abnormality_presence=false` and `blood_glucose_elevated_presence=true` reflect the source statement that chemistry was normal except blood sugar, but the source did not provide the glucose value.
- `atrial_fibrillation_pattern_on_ecg_or_holter_presence` is retained as a raw rhythm-test observation; it is not used as a final diagnosis field.
- Vascular findings are encoded as generic occlusion axes, not as disease-specific or candidate-specific observations.
