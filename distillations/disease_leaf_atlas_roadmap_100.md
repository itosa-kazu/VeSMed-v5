# VeSMed V5 Disease Leaf Atlas Roadmap to 100

This roadmap is the source for the UI candidate dropdown. The first-layer
distillation unit is a clinically stable disease leaf. Do not use broad umbrella
diagnoses when the clinical course, axes, treatment, or mimic structure differs.

## Selection Rule

Prioritize diseases that are either common, critical, or both.

- Common: high clinical frequency in fever/acute-care workflows, or frequent
  near-neighbor mimic of already distilled diseases.
- Critical: time-sensitive, high mortality/morbidity, ICU/source-control,
  immunocompromised-host, or treatment-toxic disease where early ranking matters.
- Prefer leaves that add reusable axes for future diseases: pneumonia imaging,
  source-control, neurologic infection, immunocompromised infection, shock,
  coagulopathy, organ failure, and medication/toxicologic mimics.

## Already Distilled Active Atlas

| disease_id | disease leaf |
| --- | --- |
| D137 | Adult-onset Still's disease |
| D-SEPSIS-GN | Bacterial sepsis |
| D-TTP | Thrombotic thrombocytopenic purpura |
| D-HLH-MAS | Hemophagocytic lymphohistiocytosis / macrophage activation syndrome |
| D-SLE-FLARE | Systemic lupus erythematosus flare |
| D-TB-DISSEMINATED | Disseminated tuberculosis |
| D-INFECTIVE-ENDOCARDITIS | Infective endocarditis |
| D-MPA | Microscopic polyangiitis |
| D-GPA | Granulomatosis with polyangiitis |
| D-EGPA | Eosinophilic granulomatosis with polyangiitis |
| D-DRUG-FEVER-DRESS | Drug reaction with eosinophilia and systemic symptoms |
| D-INFECTIOUS-MONONUCLEOSIS | Infectious mononucleosis |
| D-MIS-A | Multisystem inflammatory syndrome in adults |
| D-LEPTOSPIROSIS | Leptospirosis |
| D-HODGKIN-LYMPHOMA | Hodgkin lymphoma |
| D-DLBCL | Diffuse large B-cell lymphoma |
| D-ALCL | Anaplastic large-cell lymphoma |
| D-IVLBCL | Intravascular large B-cell lymphoma |
| D-COVID19-ACUTE | Acute COVID-19 |
| D-INFLUENZA | Influenza |
| D-MYCOPLASMA-PNEUMONIA | Mycoplasma pneumoniae pneumonia |
| D-PNEUMOCOCCAL-PNEUMONIA | Pneumococcal pneumonia |
| D-LEGIONELLA-PNEUMONIA | Legionella pneumonia |
| D-PYELONEPHRITIS | Pyelonephritis |
| D-ACUTE-CHOLANGITIS | Acute cholangitis |
| D-BACTERIAL-MENINGITIS | Acute bacterial meningitis |
| D-IGG4-RELATED-DISEASE | IgG4-related disease |
| D-SARCOIDOSIS | Sarcoidosis |
| D-SJOGREN-SYSTEMIC | Systemic Sjogren disease |
| D-MENINGOCOCCEMIA | Meningococcemia |
| D-TOXIC-SHOCK-SYNDROME | Toxic shock syndrome |
| D-NECROTIZING-FASCIITIS | Necrotizing fasciitis |
| D-TAKAYASU-ARTERITIS | Takayasu arteritis |
| D-BEHCET-DISEASE | Behcet disease |
| D-PYOGENIC-LIVER-ABSCESS | Pyogenic liver abscess |
| D-PJP-PNEUMONIA | Pneumocystis jirovecii pneumonia |
| D-CANDIDEMIA | Candidemia |
| D-INVASIVE-ASPERGILLOSIS | Invasive aspergillosis |
| D-ACUTE-HIV | Acute HIV retroviral syndrome |
| D-CMV-MONO | Cytomegalovirus mononucleosis-like illness |
| D-BRUCELLOSIS | Brucellosis |
| D-Q-FEVER | Q fever |
| D-RICKETTSIOSIS-SCRUB-TYPHUS | Scrub typhus / rickettsiosis |
| D-MALARIA-FALCIPARUM | Plasmodium falciparum malaria |
| D-AML | Acute myeloid leukemia |
| D-APL | Acute promyelocytic leukemia |
| D-STAPH-AUREUS-BACTEREMIA | Staphylococcus aureus bacteremia |
| D-NOCARDIOSIS | Nocardiosis |
| D-BARTONELLA-ENDOCARDITIS | Bartonella infective endocarditis |
| D-HISTOPLASMOSIS-DISSEMINATED | Disseminated histoplasmosis |
| D-CRYPTOCOCCOSIS-DISSEMINATED | Disseminated cryptococcosis |
| D-TYPHOID-FEVER | Typhoid fever |
| D-CLOSTRIDIOIDES-DIFFICILE-SEVERE | Severe Clostridioides difficile infection |
| D-SEPTIC-ARTHRITIS | Septic arthritis |
| D-VERTEBRAL-OSTEOMYELITIS | Vertebral osteomyelitis |
| D-HSV-ENCEPHALITIS | HSV encephalitis |
| D-PAN | Polyarteritis nodosa |
| D-GCA | Giant cell arteritis |
| D-CATASTROPHIC-APS | Catastrophic antiphospholipid syndrome |
| D-DIC | Disseminated intravascular coagulation |
| D-FEBRILE-NEUTROPENIA | Febrile neutropenia |
| D-CLL-TRANSFORMATION-RICHTER | Richter transformation |
| D-CML-BLAST-CRISIS | Chronic myeloid leukemia blast crisis |
| D-CAEBV | Chronic active EBV disease |
| D-ADENOVIRUS-INFECTION | Adenovirus infection |
| D-BABESIOSIS | Babesiosis |
| D-TOXOPLASMOSIS | Toxoplasmosis |
| D-COCCIDIOIDOMYCOSIS | Coccidioidomycosis |
| D-LEISHMANIASIS-VISCERAL | Visceral leishmaniasis |
| D-NONTYPHOID-SALMONELLA-BACTEREMIA | Nontyphoidal Salmonella bacteremia |
| D-ALL | Acute lymphoblastic leukemia |
| D-DISSEMINATED-GONOCOCCAL-INFECTION | Disseminated gonococcal infection |
| D-LYME-DISEASE | Lyme disease |
| D-SECONDARY-SYPHILIS | Secondary syphilis |
| D-RELAPSING-POLYCHONDRITIS | Relapsing polychondritis |
| D-CAR-T-CRS | CAR-T cytokine release syndrome |
| D-HEAT-STROKE | Heat stroke |
| D-NEUROLEPTIC-MALIGNANT-SYNDROME | Neuroleptic malignant syndrome |
| D-SEROTONIN-SYNDROME | Serotonin syndrome |

## Next 20 High-Priority Leaves

| priority | disease_id | disease leaf | why now |
| --- | --- | --- | --- |
| 1 | D-THYROID-STORM | Thyroid storm | critical endocrine fever, tachyarrhythmia, and shock mimic |
| 2 | D-ACUTE-LIVER-FAILURE | Acute liver failure | critical coagulopathy/encephalopathy fever mimic |
| 3 | D-ADRENAL-CRISIS | Adrenal crisis | critical endocrine shock and infection mimic |
| 4 | D-ACUTE-PANCREATITIS | Acute pancreatitis | common abdominal fever/SIRS/sepsis mimic |
| 5 | D-SJS-TEN | Stevens-Johnson syndrome / toxic epidermal necrolysis | critical drug fever/rash/mucosal failure mimic |
| 6 | D-MALIGNANT-HYPERTHERMIA | Malignant hyperthermia | critical hyperthermia, rigidity, acidosis, and rhabdomyolysis mimic |
| 7 | D-AIHA | Autoimmune hemolytic anemia | common hemolysis/jaundice/cytopenia mimic near TMA and babesiosis |
| 8 | D-STEC-HUS | Shiga toxin-associated hemolytic uremic syndrome | critical diarrhea-associated TMA mimic |
| 9 | D-COMPLEMENT-MEDIATED-TMA | Complement-mediated thrombotic microangiopathy | critical TMA mimic of TTP, HUS, sepsis-DIC, and malignant hypertension |
| 10 | D-EVANS-SYNDROME | Evans syndrome | immune cytopenia fever mimic near SLE, AIHA, TTP, and lymphoma |
| 11 | D-ANTISYNTHETASE-SYNDROME | Antisynthetase syndrome | fever, ILD, myositis, arthritis, and mechanic-hand mimic of infection/rheumatology disease |
| 12 | D-DERMATOMYOSITIS | Dermatomyositis | common fever/rash/myositis/ILD mimic of infection, AOSD, and malignancy |
| 13 | D-RA-FLARE | Rheumatoid arthritis systemic flare | common inflammatory fever/polyarthritis mimic of infection and vasculitis |
| 14 | D-KAWASAKI-DISEASE | Kawasaki disease | fever/rash/mucocutaneous pediatric mimic of MIS, sepsis, and vasculitis |
| 15 | D-RHEUMATIC-FEVER | Acute rheumatic fever | fever, migratory arthritis, carditis, rash, and post-streptococcal mimic |
| 16 | D-FAMILIAL-MEDITERRANEAN-FEVER | Familial Mediterranean fever | recurrent fever and serositis mimic of infection, AOSD, and autoinflammation |
| 17 | D-HEPARIN-INDUCED-THROMBOCYTOPENIA | Heparin-induced thrombocytopenia | critical thrombocytopenia/thrombosis mimic near TMA, DIC, and APS |
| 18 | D-SICKLE-CELL-ACUTE-CHEST | Sickle cell acute chest syndrome | critical fever, hypoxemia, chest pain, and infection/PE mimic |
| 19 | D-TRANSFUSION-REACTION-HEMOLYTIC | Acute hemolytic transfusion reaction | critical fever, hemolysis, shock, DIC, and sepsis mimic |
| 20 | D-TRANSPLANT-REJECTION-ACUTE | Acute transplant rejection | common/critical post-transplant fever and organ dysfunction mimic |

## Candidate Pool Toward 100

### Infection

| disease_id | disease leaf |
| --- | --- |
| D-PNEUMOCOCCAL-PNEUMONIA | Pneumococcal pneumonia |
| D-LEGIONELLA-PNEUMONIA | Legionella pneumonia |
| D-PYELONEPHRITIS | Pyelonephritis |
| D-ACUTE-CHOLANGITIS | Acute cholangitis |
| D-BACTERIAL-MENINGITIS | Acute bacterial meningitis |
| D-MENINGOCOCCEMIA | Meningococcemia |
| D-TOXIC-SHOCK-SYNDROME | Toxic shock syndrome |
| D-NECROTIZING-FASCIITIS | Necrotizing fasciitis |
| D-PYOGENIC-LIVER-ABSCESS | Pyogenic liver abscess |
| D-PJP-PNEUMONIA | Pneumocystis jirovecii pneumonia |
| D-CANDIDEMIA | Candidemia |
| D-INVASIVE-ASPERGILLOSIS | Invasive aspergillosis |
| D-ACUTE-HIV | Acute HIV retroviral syndrome |
| D-CMV-MONO | Cytomegalovirus mononucleosis-like illness |
| D-CAEBV | Chronic active EBV disease |
| D-ADENOVIRUS-INFECTION | Adenovirus infection |
| D-STAPH-AUREUS-BACTEREMIA | Staphylococcus aureus bacteremia |
| D-NOCARDIOSIS | Nocardiosis |
| D-BRUCELLOSIS | Brucellosis |
| D-Q-FEVER | Q fever |
| D-BARTONELLA-ENDOCARDITIS | Bartonella infective endocarditis |
| D-RICKETTSIOSIS-SCRUB-TYPHUS | Scrub typhus / rickettsiosis |
| D-MALARIA-FALCIPARUM | Plasmodium falciparum malaria |
| D-BABESIOSIS | Babesiosis |
| D-TOXOPLASMOSIS | Toxoplasmosis |
| D-HISTOPLASMOSIS-DISSEMINATED | Disseminated histoplasmosis |
| D-COCCIDIOIDOMYCOSIS | Coccidioidomycosis |
| D-CRYPTOCOCCOSIS-DISSEMINATED | Disseminated cryptococcosis |
| D-LEISHMANIASIS-VISCERAL | Visceral leishmaniasis |
| D-TYPHOID-FEVER | Typhoid fever |
| D-NONTYPHOID-SALMONELLA-BACTEREMIA | Nontyphoidal Salmonella bacteremia |
| D-CLOSTRIDIOIDES-DIFFICILE-SEVERE | Severe Clostridioides difficile infection |
| D-VERTEBRAL-OSTEOMYELITIS | Vertebral osteomyelitis |
| D-SEPTIC-ARTHRITIS | Septic arthritis |
| D-HSV-ENCEPHALITIS | HSV encephalitis |
| D-LYME-DISEASE | Lyme disease |
| D-SECONDARY-SYPHILIS | Secondary syphilis |
| D-DISSEMINATED-GONOCOCCAL-INFECTION | Disseminated gonococcal infection |

### Rheumatology / Autoinflammatory

| disease_id | disease leaf |
| --- | --- |
| D-PAN | Polyarteritis nodosa |
| D-GCA | Giant cell arteritis |
| D-TAKAYASU-ARTERITIS | Takayasu arteritis |
| D-BEHCET-DISEASE | Behcet disease |
| D-IGG4-RELATED-DISEASE | IgG4-related disease |
| D-SARCOIDOSIS | Sarcoidosis |
| D-RELAPSING-POLYCHONDRITIS | Relapsing polychondritis |
| D-ANTISYNTHETASE-SYNDROME | Antisynthetase syndrome |
| D-DERMATOMYOSITIS | Dermatomyositis |
| D-POLYMYOSITIS | Polymyositis |
| D-RA-FLARE | Rheumatoid arthritis systemic flare |
| D-SJOGREN-SYSTEMIC | Systemic Sjogren disease |
| D-CATASTROPHIC-APS | Catastrophic antiphospholipid syndrome |
| D-KAWASAKI-DISEASE | Kawasaki disease |
| D-RHEUMATIC-FEVER | Acute rheumatic fever |
| D-FAMILIAL-MEDITERRANEAN-FEVER | Familial Mediterranean fever |
| D-TRAPS | TNF receptor-associated periodic syndrome |
| D-CAPS | Cryopyrin-associated periodic syndrome |

### Hematology / Oncology / TMA

| disease_id | disease leaf |
| --- | --- |
| D-AML | Acute myeloid leukemia |
| D-APL | Acute promyelocytic leukemia |
| D-ALL | Acute lymphoblastic leukemia |
| D-FEBRILE-NEUTROPENIA | Febrile neutropenia |
| D-CAR-T-CRS | CAR-T cytokine release syndrome |
| D-AIHA | Autoimmune hemolytic anemia |
| D-EVANS-SYNDROME | Evans syndrome |
| D-STEC-HUS | Shiga toxin-associated hemolytic uremic syndrome |
| D-COMPLEMENT-MEDIATED-TMA | Complement-mediated thrombotic microangiopathy |
| D-DIC | Disseminated intravascular coagulation |
| D-HEPARIN-INDUCED-THROMBOCYTOPENIA | Heparin-induced thrombocytopenia |
| D-SICKLE-CELL-ACUTE-CHEST | Sickle cell acute chest syndrome |

### Drug / Toxicology / Endocrine / Critical Mimics

| disease_id | disease leaf |
| --- | --- |
| D-DRUG-FEVER | Simple drug fever |
| D-DRESS | Drug reaction with eosinophilia and systemic symptoms |
| D-SJS-TEN | Stevens-Johnson syndrome / toxic epidermal necrolysis |
| D-NEUROLEPTIC-MALIGNANT-SYNDROME | Neuroleptic malignant syndrome |
| D-SEROTONIN-SYNDROME | Serotonin syndrome |
| D-MALIGNANT-HYPERTHERMIA | Malignant hyperthermia |
| D-THYROID-STORM | Thyroid storm |
| D-ADRENAL-CRISIS | Adrenal crisis |
| D-HEAT-STROKE | Heat stroke |
| D-ACUTE-PANCREATITIS | Acute pancreatitis |
| D-ALCOHOLIC-HEPATITIS | Alcoholic hepatitis |
| D-ACUTE-LIVER-FAILURE | Acute liver failure |
| D-TRANSFUSION-REACTION-FNHTR | Febrile non-hemolytic transfusion reaction |
| D-TRANSFUSION-REACTION-HEMOLYTIC | Acute hemolytic transfusion reaction |
| D-TRANSPLANT-REJECTION-ACUTE | Acute transplant rejection |

## Operational Batch Rule

- Distill 3-4 new disease leaves per batch.
- After each batch, add at least one PMC/PubMed positive real case per new disease.
- Run focused new-case ranking, then full single smoke, then combo smoke.
- If treatment ranking is abnormal, compact or complete the treatment vector field first;
  do not re-distill the whole disease unless the disease manifold itself is polluted.
