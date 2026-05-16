# PMC8752403 Blind Extraction Notes

Source: https://pmc.ncbi.nlm.nih.gov/articles/PMC8752403/

Metadata captured:
- PMCID: PMC8752403
- PMID: 35036223
- DOI: 10.7759/cureus.20393
- Article title: Adult Idiopathic Ileocolonic Intussusception: A Case Report
- Journal/date: Cureus, 2021-12-13, 13(12):e20393

Blinding boundary:
- Did not encode expected disease fields or paper-label fields.
- Rankable observations are limited to demographics, preoperative history, presentation, exam, lab summary, and ED CT findings stated in the Case presentation.
- Operative findings, treatment, pathology, postoperative course, and Discussion interpretation are `record_only` and `use_in_ranking: false`.

Extraction caveats:
- The paper does not provide numeric lab values; WBC elevation, stable hemoglobin/hematocrit, normal lactate, and normal electrolyte/hepatic panels are represented as qualitative present/absent axes.
- CT finding wording was normalized to reusable morphology axes such as `bowel_invagination_on_ct_presence`, `bowel_pneumatosis_presence`, `pericolonic_fat_stranding_presence`, and `ascites_presence`.
- The article does not report vital signs or medication list.
