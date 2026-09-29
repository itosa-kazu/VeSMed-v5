You are a case-collection agent in a pre-registered blind test of the VeSMed V5 diagnosis system (repo root: C:\Users\wangw\Documents\vesmed). Communicate your final report in Chinese. Work carefully; medical accuracy matters more than speed.

## Your assigned leaves (process in this exact order)
{LEAVES}

## Goal per leaf
Find the MOST RECENTLY PUBLISHED real case report that satisfies ALL of:
1. PMC open-access full text, a real patient case report (not a review, not a case series table, not synthetic), published on or after 2025-01-01.
2. Its PMC id is NOT listed in research/blind_vs_llm/frozen/known_pmcids.txt.
3. The paper's final diagnosis clearly corresponds to the leaf's disease name, and does NOT correspond more specifically to another leaf in research/blind_vs_llm/frozen/atlas.json (e.g. do not take an organism-specific bacteremia for a generic sepsis leaf if the organism has its own leaf). One primary diagnosis, not two diseases combined.
4. At presentation it reports at least 5 quantitative labs or vital signs.

Search suggestion: Europe PMC REST API, sorted newest first, e.g.
https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=%22<disease>%22%20AND%20%22case%20report%22%20AND%20OPEN_ACCESS:y%20AND%20FIRST_PDATE:[2025-01-01%20TO%202026-12-31]&sort=P_PDATE_D%20desc&format=json&pageSize=25
Full text: https://www.ebi.ac.uk/europepmc/webservices/rest/<PMCID>/fullTextXML
Go down the results newest-first and take the first one that satisfies all conditions. Log every candidate you examined and why you rejected it. If after a reasonable search (about 40 candidates) nothing qualifies, mark the leaf as SKIPPED with the reason.

## Hard rules (the test is invalid if you break them)
- Do NOT open, read, grep or list any disease distillation file `distillations/v5_*.json`. Do NOT run v5_joint_sde_case_test.py, run_system.py or any ranking. You may read: AGENTS.md (case rules: "测试真实病例的规则", "Axis Ontology", "Highest-Priority Observation Axis Rule"), research/blind_vs_llm/frozen/case_axis_registry.json (axis naming registry, not a checklist), and the format example distillations/cases/v5_case_ITP_ADULT_MALE_PURPURA_GINGIVAL_PMC10628603.json.
- Write ONLY inside research/blind_vs_llm/cases/, research/blind_vs_llm/vignettes/, research/blind_vs_llm/case_search_logs/. Never write to distillations/.
- Real data only. Keep original values and units; record every unit conversion. Never invent a value.

## Output per accepted case
1. `research/blind_vs_llm/cases/v5_case_<CASE_ID>.json` following the example file's schema. Top level must include: case_id, source_pmid, source_pmcid, source_url, publication_date, disease_label_per_paper, expected_manifold (= the leaf id), diagnostic_stage "presentation", plus structured presentation evidence (observations / lab_trajectories / risk_context as in the example). Every structured item keeps `source_text_value` (verbatim from the paper).
   - Structure all presentation-time symptoms, signs, vitals, labs, and presentation imaging into axes. Use axis ids from the registry; if a real finding has no registry axis, create a diagnosis-neutral generic axis id (never containing a disease name) — it will be flagged as pending, which is fine.
   - Parent/satellite rule: presence finding first, then satellites/measurements. No vague bundle axes (e.g. "flu-like symptoms"); split into concrete findings, or keep record-only with use_in_ranking false.
   - Confirmatory evidence (biopsy/pathology, culture species, pathogen PCR/antigen/serology that establishes the diagnosis, disease-defining antibodies, final diagnosis, treatment, response, outcome) goes in confirmatory/non-ranking sections with `use_in_ranking: false`.
   - Risk context available at presentation (age, sex, comorbidities, medications, exposures, travel) goes into risk_context as in the example.
2. Run `python research/blind_vs_llm/validate_case.py <case file>` and make sure it loads and that the consumed axes match what you intended. Fix your file until it does.
3. `research/blind_vs_llm/vignettes/<CASE_ID>.txt`: an English plain-text presentation for a physician, containing exactly the presentation-time facts that are rankable in your JSON (demographics, relevant history and exposures, symptoms with timing, exam, vitals, labs with units, presentation imaging). Use neutral wording close to the paper. It must NOT contain: the diagnosis or any wording that names or strongly hints it beyond what the presentation itself says, paper title, PMC/PMID, authors, confirmatory tests, treatment, course, outcome.

## Final report (return this as your last message, in Chinese)
For each assigned leaf in order: ACCEPTED (case_id, PMCID, publication date, paper diagnosis, number of consumed axes, pending axes) or SKIPPED (reason, how many candidates examined). Also write the same log to research/blind_vs_llm/case_search_logs/<first leaf id>_batch.md.
