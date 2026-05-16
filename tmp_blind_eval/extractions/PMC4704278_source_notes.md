# PMC4704278 Blind Source Notes

## Source Metadata

- PMCID: PMC4704278
- PMID: 26766978
- DOI: 10.1111/1759-7714.12007
- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC4704278/
- PDF URL reported by PMC metadata: https://pmc.ncbi.nlm.nih.gov/articles/PMC4704278/pdf/tca0005-0082.pdf
- Article: Thoracic Cancer, volume 5, issue 1, pages 82-84, published online 2014-01-02.

## Blindness Boundary

The extraction used only source-article case-report chronology for clinical observations. The title, abstract diagnosis summary, pathology/final diagnosis wording, discussion interpretation, treatment response, discharge, and follow-up were not used as rankable evidence.

No expected disease label or expected disease ID was included. No local distillation files, local case files, local ranking outputs, or local expected-label files were read for this extraction.

## Rankable Chronology Paraphrase

A 49-year-old woman was admitted in February 2004 after more than 20 days of fatigue and dark/discolored urine. Examination mainly noted jaundice. Initial blood and chemistry testing showed anemia with low RBC count and hemoglobin, elevated reticulocytes, mild leukopenia, mildly low platelets, positive urine urobilinogen, hyperbilirubinemia dominated by indirect bilirubin, and elevated LDH. Immunologic and hemolysis workup included ANA 1:100, no other detected autoantibody, negative congenital hemolysis tests, normal CD55/CD59, positive IgG and C3 Coombs-related measures, negative cold agglutinin test, and normal chest X-ray.

In November 2004 she had a recurrence presentation with cough and throat pain. Examination noted icteric sclera and mild splenomegaly, with the spleen described as 3 cm below the rib. Blood and liver tests at that time included hemoglobin 118 g/L, reticulocytes 4.78%, total bilirubin 34 umol/L, indirect bilirubin 27.4 umol/L, LDH 300 U/L, and Coombs IgG 1:2048.

In June 2006, after overwork, she again presented with fatigue and black urine. Reported labs included RBC 2.34 x 10^12/L, hemoglobin 79 g/L, reticulocytes 11.21%, absolute reticulocytes 0.262 x 10^12/L, WBC 3.21 x 10^12/L as printed, ALT 62 U/L, GGT 64 U/L, total bilirubin 41.5 umol/L, direct bilirubin 13.6 umol/L, and Coombs IgG 1:1024.

During later pre-operative longitudinal workup, bone marrow aspiration showed hyperplastic anemia with erythroid cells accounting for 35%-65% of nucleated cells. B-cell subpopulation values were reported within normal range. T-cell subpopulation testing showed normal CD4/CD8 ratio but elevated CD3, CD3/CD4, and CD3/CD8 percentages. Later Coombs testing, immunologic antibody testing, and chest X-ray were reported negative or normal before the late thoracic diagnosis.

Seven years after the initial diagnosis, she returned with urinary infection. Examination found moist rales in the right lower lung. Chest CT showed patchy enhancement in the right lower lung. Neuron-specific enolase was 33.01 ug/L with an upper normal limit of 16.3 ug/L.

## Record-Only Exclusions

The early diagnostic wording for warm-type autoimmune hemolytic anemia was placed in record_only. Initial IVIG, prednisone, cyclosporine, later cyclophosphamide/vincristine, later methylprednisolone, antibacterial/antifungal therapy, cyclosporine discontinuation, lobectomy, and post-operative chemotherapy were all record-only treatment facts.

Treatment responses were also excluded from ranking: initial blood improvement, controlled relapses, lack of CT improvement after antimicrobials, post-operative normalization of hemolysis markers, stopping prednisone, and normal 14-month follow-up CT/hemolysis parameters.

Final or near-final diagnostic wording was excluded from rankable evidence, including surgeon wording of right lower lung cancer, pathology wording of papillary adenocarcinoma, and the article's retrospective paraneoplastic interpretation.

## Axis Naming Uncertainties

- Dark/discolored urine and black urine may need one shared parent axis with color qualifiers.
- Pharyngalgia was normalized as sore_throat_presence; a registry may prefer pharyngeal_pain_presence.
- Urine urobilinogen was qualitative positive; a registry may split qualitative and quantitative urine urobilinogen.
- Coombs IgG/C3 titers and scores may need parent/satellite direct-antiglobulin axes.
- Jointly normal CD55/CD59 may need separate CD55 and CD59 axes.
- Bone marrow "hyperplastic anemia" may be better normalized as erythroid_hyperplasia_presence plus anemia.
- The second recurrence WBC unit was preserved as printed, but may be a source unit typo.
- Right lower lung moist rales may normalize to pulmonary_crackles_presence with a location qualifier.
- CT patchy enhancement was kept diagnosis-neutral; final registry mapping may prefer pulmonary infiltrate, opacity, or lesion axes.
- Neuron-specific enolase was kept as a generic marker axis, not a diagnosis label.
