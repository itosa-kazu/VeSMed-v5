# PMC4509665 Blind Extraction Source Notes

## Access

- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC4509665/
- PMCID: PMC4509665
- PMID: 25749764
- DOI: 10.4168/aair.2015.7.5.513
- Browser access to the interactive PMC page was blocked by a reCAPTCHA interstitial in the browser tool.
- Full text was retrieved as PMC JATS XML through NCBI/PMC OAI:
  `https://www.ncbi.nlm.nih.gov/pmc/oai/oai.cgi?verb=GetRecord&identifier=oai:pubmedcentral.nih.gov:4509665&metadataPrefix=pmc`

## Extraction Boundary

- Included for ranking: demographics, pre-existing allergy history, recent bee pollen ingestion exposure, exposure-to-symptom timing, emergency presentation symptoms, chest exam wheeze, initial vital signs, serum total IgE, screening allergen positives, and post-event clinical allergy test results with explicit timing.
- Kept record-only: article title and abstract diagnostic framing, acute treatment, treatment response, bee-pollen product microscopy, research ELISA binding/inhibition assays, SDS-PAGE/IgE-immunoblot findings, discussion-level causal interpretation, and the literature-review table.
- Existing local `distillations/cases` files were intentionally not read.
- No expected diagnosis/manifold field or final diagnosis field was added.
- No ordinary diagnosis-specific disease-suffixed observed axes were used.

## Evidence Pointers

- Case Report paragraph 1: age/sex, emergency department presentation, ingestion of one tablespoon of bee pollen from a local market, one-hour onset after ingestion, generalized urticaria, facial edema, dyspnea, nausea, vomiting, abdominal pain, diarrhea, wheezing on chest exam, oxygen saturation, blood pressure, pulse, respiratory rate, temperature, emergency medications, symptom resolution, no known food/drug allergy or hymenoptera sensitivity, seasonal allergic rhinitis in autumn, serum total IgE, and simultaneous multiple allergen test positives.
- Case Report paragraph 2: bee pollen product microscopy, one-month skin-prick test to bee-pollen extract, serum specific IgE to mugwort/ragweed/chrysanthemum/dandelion, and negative Japanese hop / honey-bee venom / yellow-jacket venom testing.
- Case Report paragraph 3 and Figures 2-3: research ELISA, ELISA inhibition, SDS-PAGE, and IgE-immunoblot results retained as record-only.
- Discussion paragraphs: cross-allergenicity and causal interpretation retained as record-only.

## Registry Notes

- Reused registry axis IDs where exact neutral matches existed, including `urticaria_presence`, `facial_edema_presence`, `dyspnea_presence`, `nausea_presence`, `vomiting_presence`, `abdominal_pain_presence`, `diarrhea_presence`, `wheezing_presence`, `oxygen_saturation`, `systolic_blood_pressure`, `diastolic_blood_pressure`, `mean_arterial_pressure`, `heart_rate`, `respiratory_rate`, `body_temperature`, and `serum_total_ige`.
- Suggested generic axis IDs were used for exposure and allergy-test concepts where exact neutral registry IDs were not found or not checked as clinical presentation axes: `bee_pollen_ingestion_presence`, `bee_pollen_ingestion_amount_tablespoons`, `post_exposure_symptom_onset_hours`, `generalized_urticaria_presence`, `seasonal_allergic_rhinitis_history_presence`, `known_food_allergy_history_presence`, `known_drug_allergy_history_presence`, `hymenoptera_sensitivity_history_presence`, allergen-screen positive axes, skin-prick axes, and specific-IgE axes.
- Disease-specific axis IDs such as `*_in_D-...` were deliberately avoided for ordinary observations.

## Ambiguities

- Serum total IgE and simultaneous multiple allergen testing are reported in the first Case Report paragraph, but the exact timing relative to emergency treatment is not stated.
- Skin-prick and specific-IgE testing are reported one month later; they were included as rankable diagnostic observations but marked as post-event workup, not initial emergency presentation.
- The bee-pollen microscopy, ELISA inhibition, and immunoblot data are patient/source-specific but were kept record-only because they are research-level causality workup rather than ordinary presentation facts.
- No tryptase, CBC, eosinophil count, lactate, arterial blood gas, chest imaging, or follow-up vital signs are reported.
- Generalized urticaria and facial edema may overlap clinically with broader angioedema/allergic-reaction constructs; they were kept as separate neutral observed axes because the case text lists them separately.
