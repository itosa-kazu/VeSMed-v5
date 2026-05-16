# PMC3089931 Blind Source Notes

Source: https://pmc.ncbi.nlm.nih.gov/articles/PMC3089931/

Article: "An unusual cause of spontaneous pneumothorax", BMJ Case Reports, 2011-05-03.

Identifiers preserved:
- PMCID: PMC3089931
- PMID: 22696702
- DOI: 10.1136/bcr.08.2010.3209

Blind extraction boundary:
- No local atlas, distillation, disease JSON, ranking case, or prior result files were inspected.
- The JSON avoids fields for target labels or manifolds.
- Ordinary observations use neutral reusable axes, without disease-specific suffixes.
- Final diagnosis, treatment, response, follow-up, and discussion framing are stored only under `record_only` with `use_in_ranking: false`.

Rankable clinical facts extracted:
- 31-year-old male presenting on 2010-05-29.
- Acute left-sided chest pain, dyspnea, fever, productive cough, and myalgias.
- Non-smoker; no illegal drug use, recent travel abroad, or regular medication use reported.
- Prior inconclusive CT-based report of a pulmonary cyst after a car accident 5 years earlier.
- Initial chest x-ray showed left pneumothorax; figure caption also described lower-field pleural thickening.
- Patient was described as hemodynamically stable.
- Fever to 38.5C for 2 days after admission.
- WBC 15000/mm3, neutrophils 92%, CRP 42 mg/dL, procalcitonin 2.8 ug/L.
- Sputum culture reported multiple microorganisms, Streptococcus pneumonia, and mixed anaerobes without predominance.
- Later CT showed a posterior basal left lower lobe opacity/solid lesion with focal calcifications and a small eccentric cavity.
- Lesion was adjacent to the descending aorta.
- Aortography showed two feeding arteries from the descending aorta, located below the tracheal carina.
- No apical subpleural blebs were reported.

Record-only facts:
- Chest tube placement, intravenous ampicillin/sulbactam, chest tube suction plan, post-tube pleural air-fluid level, persistent post-tube pleural air/air leak, full expansion, and tube removal timing.
- Article-stated final diagnosis.
- Author hypothesis about infection, inflammation, rupture, and communication with normal lung parenchyma.
- Follow-up choice and discussion framing.

Caveats:
- The article did not provide oxygen saturation, respiratory rate, heart rate, blood pressure, arterial blood gas, or detailed CT dimensions.
- The organism text is preserved as written in the article in `source_text_value`; the axis uses the clinically standard spelling.
- The no-recurrent-lower-respiratory-infection and no-haemoptysis statement appears in the follow-up section, so it was kept record-only rather than rankable.
