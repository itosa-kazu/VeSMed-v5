# VeSMed V5 Disease Leaf Atlas Roadmap to 200

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
| D-THYROID-STORM | Thyroid storm |
| D-ACUTE-LIVER-FAILURE | Acute liver failure |
| D-ADRENAL-CRISIS | Adrenal crisis |
| D-ACUTE-PANCREATITIS | Acute pancreatitis |
| D-SJS-TEN | Stevens-Johnson syndrome / toxic epidermal necrolysis |
| D-MALIGNANT-HYPERTHERMIA | Malignant hyperthermia |
| D-AIHA | Autoimmune hemolytic anemia |
| D-STEC-HUS | Shiga toxin-associated hemolytic uremic syndrome |
| D-COMPLEMENT-MEDIATED-TMA | Complement-mediated thrombotic microangiopathy |
| D-DERMATOMYOSITIS | Dermatomyositis |
| D-EVANS-SYNDROME | Evans syndrome |
| D-HEPARIN-INDUCED-THROMBOCYTOPENIA | Heparin-induced thrombocytopenia |
| D-ANTISYNTHETASE-SYNDROME | Antisynthetase syndrome |
| D-KAWASAKI-DISEASE | Kawasaki disease |
| D-ANTI-GBM-DISEASE | Anti-glomerular basement membrane disease |
| D-RA-FLARE | Rheumatoid arthritis systemic flare |
| D-SICKLE-CELL-ACUTE-CHEST | Sickle cell acute chest syndrome |
| D-SPINAL-EPIDURAL-ABSCESS | Spinal epidural abscess |
| D-RHEUMATIC-FEVER | Acute rheumatic fever |
| D-DIABETIC-KETOACIDOSIS | Diabetic ketoacidosis |
| D-ACUTE-MYOCARDITIS | Acute myocarditis |
| D-FAMILIAL-MEDITERRANEAN-FEVER | Familial Mediterranean fever |
| D-TRANSFUSION-REACTION-HEMOLYTIC | Acute hemolytic transfusion reaction |
| D-TRANSPLANT-REJECTION-ACUTE | Acute transplant rejection |
| D-POLYMYOSITIS | Polymyositis |
| D-DRUG-FEVER | Simple drug fever |
| D-ALCOHOLIC-HEPATITIS | Alcoholic hepatitis |
| D-TRANSFUSION-REACTION-FNHTR | Febrile non-hemolytic transfusion reaction |
| D-STREP-PYOGENES-BACTEREMIA | Streptococcus pyogenes bacteremia |
| D-PSEUDOMONAS-BACTEREMIA | Pseudomonas aeruginosa bacteremia |
| D-ITP | Immune thrombocytopenia |
| D-CELLULITIS | Cellulitis |
| D-SPONTANEOUS-BACTERIAL-PERITONITIS | Spontaneous bacterial peritonitis |
| D-ASPIRATION-PNEUMONIA | Aspiration pneumonia |
| D-APPENDICITIS | Acute appendicitis |
| D-DIVERTICULITIS | Acute diverticulitis |
| D-PELVIC-INFLAMMATORY-DISEASE | Pelvic inflammatory disease |
| D-ACUTE-PROSTATITIS | Acute bacterial prostatitis |
| D-ENTEROCOCCAL-BACTEREMIA | Enterococcal bacteremia |
| D-ESBL-ENTEROBACTERALES-BACTEREMIA | ESBL Enterobacterales bacteremia |
| D-CENTRAL-LINE-ASSOCIATED-BLOODSTREAM-INFECTION | Central line-associated bloodstream infection |
| D-HYPEROSMOLAR-HYPERGLYCEMIC-STATE | Hyperosmolar hyperglycemic state |
| D-TRAPS | TNF receptor-associated periodic syndrome |
| D-CAPS | Cryopyrin-associated periodic syndrome |
| D-APLASTIC-ANEMIA | Aplastic anemia |
| D-PULMONARY-EMBOLISM | Pulmonary embolism |
| D-PERICARDITIS | Acute pericarditis |
| D-ACUTE-CHOLECYSTITIS | Acute cholecystitis |
| D-BRAIN-ABSCESS | Brain abscess |
| D-EMPYEMA | Pleural empyema |
| D-LUNG-ABSCESS | Lung abscess |
| D-ORBITAL-CELLULITIS | Orbital cellulitis |
| D-DIABETIC-FOOT-INFECTION | Diabetic foot infection |
| D-CATHETER-ASSOCIATED-UTI | Catheter-associated urinary tract infection |
| D-RENAL-ABSCESS | Renal abscess |
| D-TUBO-OVARIAN-ABSCESS | Tubo-ovarian abscess |
| D-EPIDIDYMO-ORCHITIS | Epididymo-orchitis |

## Next 20 High-Priority Leaves

| priority | disease_id | disease leaf | why now |
| --- | --- | --- | --- |
| 1 | D-POSTPARTUM-ENDOMETRITIS | Postpartum endometritis | common postpartum fever/pelvic pain mimic near PID, TOA, UTI, and sepsis |
| 2 | D-PERINEPHRIC-ABSCESS | Perinephric abscess | critical fever/flank pain source-control mimic near pyelonephritis and renal abscess |
| 3 | D-SEPTIC-ABORTION | Septic abortion | critical pelvic fever/sepsis mimic near PID, postpartum endometritis, and TOA |
| 4 | D-PROSTHETIC-JOINT-INFECTION | Prosthetic joint infection | common hardware-associated fever/pain source-control disease near septic arthritis and bacteremia |
| 5 | D-VIRAL-MENINGITIS | Viral meningitis | common fever/headache/meningitis mimic near bacterial meningitis, HSV encephalitis, and systemic viral syndromes |
| 6 | D-CARBAPENEM-RESISTANT-ENTEROBACTERALES-INFECTION | Carbapenem-resistant Enterobacterales infection | critical resistant infection and sepsis treatment-coverage mimic after ESBL |
| 7 | D-ERYSIPELAS | Erysipelas | common superficial cellulitis mimic with fever, sharp erythema, and bacteremia/TSS near-neighbor risk |
| 8 | D-AUTOIMMUNE-ENCEPHALITIS | Autoimmune encephalitis | critical encephalitis mimic near viral meningitis/HSV encephalitis, seizures, psychiatric symptoms, and fever |
| 9 | D-VZV-ENCEPHALITIS | Varicella-zoster virus encephalitis | critical encephalitis/meningitis mimic near HSV, autoimmune encephalitis, and stroke |
| 10 | D-WEST-NILE-NEUROINVASIVE-DISEASE | West Nile neuroinvasive disease | fever with meningitis/encephalitis/acute flaccid paralysis mimic |
| 11 | D-DENGUE | Dengue | common global fever/thrombocytopenia/shock mimic near sepsis, malaria, rickettsiosis, and viral syndromes |
| 12 | D-CHIKUNGUNYA | Chikungunya | common global fever, rash, and severe arthralgia mimic near dengue, rickettsiosis, and viral syndromes |
| 13 | D-MEASLES | Measles | public-health-critical fever, cough, conjunctivitis, and rash mimic near viral exanthems and Kawasaki-like illness |
| 14 | D-ACUTE-HEPATITIS-A | Acute hepatitis A | common fever, jaundice, and transaminitis mimic near cholangitis, leptospirosis, EBV/CMV, and acute liver injury |
| 15 | D-ACUTE-HEPATITIS-B | Acute hepatitis B | fever, jaundice, transaminitis, rash/arthralgia, and acute liver injury mimic |
| 16 | D-ACUTE-HEPATITIS-E | Acute hepatitis E | fever, jaundice, pregnancy-risk liver failure, and cholangitis/leptospirosis mimic |
| 17 | D-AMOEBIC-LIVER-ABSCESS | Amoebic liver abscess | fever/right-upper-quadrant pain source-control mimic near pyogenic liver abscess and travel infections |
| 18 | D-STRONGYLOIDES-HYPERINFECTION | Strongyloides hyperinfection | critical fever/sepsis/ARDS mimic in steroid or immunosuppressed hosts |
| 19 | D-TRICHINELLOSIS | Trichinellosis | fever, myalgia, facial edema, eosinophilia mimic near rheum and parasitic infection |
| 20 | D-IGA-VASCULITIS | IgA vasculitis | common vasculitic fever/rash/abdominal pain/renal mimic near infection and systemic rheum |

## Candidate Pool Toward 200

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
| D-POLYMYOSITIS | Polymyositis |
| D-RA-FLARE | Rheumatoid arthritis systemic flare |
| D-SJOGREN-SYSTEMIC | Systemic Sjogren disease |
| D-CATASTROPHIC-APS | Catastrophic antiphospholipid syndrome |
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
| D-STEC-HUS | Shiga toxin-associated hemolytic uremic syndrome |
| D-COMPLEMENT-MEDIATED-TMA | Complement-mediated thrombotic microangiopathy |
| D-DIC | Disseminated intravascular coagulation |
| D-SICKLE-CELL-ACUTE-CHEST | Sickle cell acute chest syndrome |

### Drug / Toxicology / Endocrine / Critical Mimics

| disease_id | disease leaf |
| --- | --- |
| D-DRUG-FEVER | Simple drug fever |
| D-DRUG-FEVER-DRESS | Drug reaction with eosinophilia and systemic symptoms |
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

### Infection Expansion

| disease_id | disease leaf |
| --- | --- |
| D-STREP-PYOGENES-BACTEREMIA | Streptococcus pyogenes bacteremia |
| D-PSEUDOMONAS-BACTEREMIA | Pseudomonas aeruginosa bacteremia |
| D-ENTEROCOCCAL-BACTEREMIA | Enterococcal bacteremia |
| D-ESBL-ENTEROBACTERALES-BACTEREMIA | ESBL Enterobacterales bacteremia |
| D-CARBAPENEM-RESISTANT-ENTEROBACTERALES-INFECTION | Carbapenem-resistant Enterobacterales infection |
| D-CENTRAL-LINE-ASSOCIATED-BLOODSTREAM-INFECTION | Central line-associated bloodstream infection |
| D-CATHETER-ASSOCIATED-UTI | Catheter-associated urinary tract infection |
| D-RENAL-ABSCESS | Renal abscess |
| D-PERINEPHRIC-ABSCESS | Perinephric abscess |
| D-ACUTE-PROSTATITIS | Acute bacterial prostatitis |
| D-EPIDIDYMO-ORCHITIS | Epididymo-orchitis |
| D-PELVIC-INFLAMMATORY-DISEASE | Pelvic inflammatory disease |
| D-TUBO-OVARIAN-ABSCESS | Tubo-ovarian abscess |
| D-SEPTIC-ABORTION | Septic abortion |
| D-POSTPARTUM-ENDOMETRITIS | Postpartum endometritis |
| D-CELLULITIS | Cellulitis |
| D-ERYSIPELAS | Erysipelas |
| D-ORBITAL-CELLULITIS | Orbital cellulitis |
| D-DIABETIC-FOOT-INFECTION | Diabetic foot infection |
| D-PROSTHETIC-JOINT-INFECTION | Prosthetic joint infection |
| D-SPINAL-EPIDURAL-ABSCESS | Spinal epidural abscess |
| D-BRAIN-ABSCESS | Brain abscess |
| D-LUNG-ABSCESS | Lung abscess |
| D-EMPYEMA | Pleural empyema |
| D-ASPIRATION-PNEUMONIA | Aspiration pneumonia |
| D-VIRAL-MENINGITIS | Viral meningitis |
| D-AUTOIMMUNE-ENCEPHALITIS | Autoimmune encephalitis |
| D-VZV-ENCEPHALITIS | Varicella-zoster virus encephalitis |
| D-WEST-NILE-NEUROINVASIVE-DISEASE | West Nile neuroinvasive disease |
| D-DENGUE | Dengue |
| D-CHIKUNGUNYA | Chikungunya |
| D-MEASLES | Measles |
| D-ACUTE-HEPATITIS-A | Acute hepatitis A |
| D-ACUTE-HEPATITIS-B | Acute hepatitis B |
| D-ACUTE-HEPATITIS-E | Acute hepatitis E |
| D-AMOEBIC-LIVER-ABSCESS | Amoebic liver abscess |
| D-STRONGYLOIDES-HYPERINFECTION | Strongyloides hyperinfection |
| D-TRICHINELLOSIS | Trichinellosis |

### Rheumatology / Nephrology Expansion

| disease_id | disease leaf |
| --- | --- |
| D-IGA-VASCULITIS | IgA vasculitis |
| D-CRYOGLOBULINEMIC-VASCULITIS | Cryoglobulinemic vasculitis |
| D-URTICARIAL-VASCULITIS | Urticarial vasculitis |
| D-MIXED-CONNECTIVE-TISSUE-DISEASE | Mixed connective tissue disease |
| D-SYSTEMIC-SCLEROSIS-RENAL-CRISIS | Systemic sclerosis renal crisis |
| D-POLYMYALGIA-RHEUMATICA | Polymyalgia rheumatica |
| D-GOUT-FLARE | Gout flare |
| D-CALCIUM-PYROPHOSPHATE-ARTHRITIS | Calcium pyrophosphate crystal arthritis |
| D-REACTIVE-ARTHRITIS | Reactive arthritis |
| D-PSORIATIC-ARTHRITIS-FLARE | Psoriatic arthritis flare |
| D-ANKYLOSING-SPONDYLITIS-FLARE | Ankylosing spondylitis flare |
| D-ULCERATIVE-COLITIS-SEVERE-FLARE | Severe ulcerative colitis flare |
| D-CROHN-DISEASE-FLARE | Crohn disease flare |
| D-MYOSITIS-ASSOCIATED-RAPIDLY-PROGRESSIVE-ILD | Myositis-associated rapidly progressive interstitial lung disease |
| D-PRIMARY-CNS-VASCULITIS | Primary central nervous system vasculitis |

### Hematology / Oncology Expansion

| disease_id | disease leaf |
| --- | --- |
| D-ITP | Immune thrombocytopenia |
| D-APLASTIC-ANEMIA | Aplastic anemia |
| D-PNH | Paroxysmal nocturnal hemoglobinuria |
| D-G6PD-HEMOLYSIS | Glucose-6-phosphate dehydrogenase hemolysis |
| D-COLD-AGGLUTININ-DISEASE | Cold agglutinin disease |
| D-DRUG-INDUCED-IMMUNE-HEMOLYTIC-ANEMIA | Drug-induced immune hemolytic anemia |
| D-HELLP-SYNDROME | HELLP syndrome |
| D-PREECLAMPSIA-SEVERE | Severe preeclampsia |
| D-HYPERTENSIVE-EMERGENCY-TMA | Hypertensive emergency-associated TMA |
| D-DRUG-INDUCED-TMA | Drug-induced thrombotic microangiopathy |
| D-SOLID-TUMOR-MARROW-INFILTRATION | Solid tumor marrow infiltration |
| D-MULTIPLE-MYELOMA | Multiple myeloma |
| D-PLASMA-CELL-LEUKEMIA | Plasma cell leukemia |
| D-BURKITT-LYMPHOMA | Burkitt lymphoma |
| D-ANGIOIMMUNOBLASTIC-T-CELL-LYMPHOMA | Angioimmunoblastic T-cell lymphoma |
| D-EXTRANODAL-NK-T-CELL-LYMPHOMA | Extranodal NK/T-cell lymphoma |
| D-PRIMARY-CNS-LYMPHOMA | Primary central nervous system lymphoma |
| D-CASTLEMAN-DISEASE | Castleman disease |
| D-TUMOR-LYSIS-SYNDROME | Tumor lysis syndrome |
| D-GVHD-ACUTE | Acute graft-versus-host disease |
| D-POST-TRANSPLANT-LYMPHOPROLIFERATIVE-DISORDER | Post-transplant lymphoproliferative disorder |

### Cardio-Pulmonary / Critical Care Expansion

| disease_id | disease leaf |
| --- | --- |
| D-PULMONARY-EMBOLISM | Pulmonary embolism |
| D-MYOCARDITIS | Myocarditis |
| D-PERICARDITIS | Acute pericarditis |
| D-ACUTE-DECOMPENSATED-HEART-FAILURE | Acute decompensated heart failure |
| D-CARDIOGENIC-SHOCK | Cardiogenic shock |
| D-AORTIC-DISSECTION | Aortic dissection |
| D-TAKOTSUBO-CARDIOMYOPATHY | Takotsubo cardiomyopathy |
| D-ACUTE-EOSINOPHILIC-PNEUMONIA | Acute eosinophilic pneumonia |
| D-ORGANIZING-PNEUMONIA | Organizing pneumonia |
| D-DIFFUSE-ALVEOLAR-HEMORRHAGE | Diffuse alveolar hemorrhage |
| D-FAT-EMBOLISM-SYNDROME | Fat embolism syndrome |

### Gastrointestinal / Hepatobiliary / Surgical Expansion

| disease_id | disease leaf |
| --- | --- |
| D-ACUTE-CHOLECYSTITIS | Acute cholecystitis |
| D-APPENDICITIS | Acute appendicitis |
| D-DIVERTICULITIS | Acute diverticulitis |
| D-BOWEL-ISCHEMIA | Acute mesenteric ischemia |
| D-PERFORATED-VISCUS | Perforated viscus |
| D-SPONTANEOUS-BACTERIAL-PERITONITIS | Spontaneous bacterial peritonitis |
| D-CIRRHOSIS-ACUTE-DECOMPENSATION | Acute decompensated cirrhosis |
| D-ACETAMINOPHEN-TOXICITY | Acetaminophen toxicity |
| D-BUDD-CHIARI-SYNDROME | Budd-Chiari syndrome |
| D-WILSON-DISEASE-ACUTE-HEPATIC | Acute hepatic Wilson disease |

### Endocrine / Metabolic / Toxicology Expansion

| disease_id | disease leaf |
| --- | --- |
| D-DIABETIC-KETOACIDOSIS | Diabetic ketoacidosis |
| D-HYPEROSMOLAR-HYPERGLYCEMIC-STATE | Hyperosmolar hyperglycemic state |
| D-MYXEDEMA-COMA | Myxedema coma |
| D-PHEOCHROMOCYTOMA-CRISIS | Pheochromocytoma crisis |
| D-SALICYLATE-TOXICITY | Salicylate toxicity |
| D-METFORMIN-ASSOCIATED-LACTIC-ACIDOSIS | Metformin-associated lactic acidosis |
| D-ALCOHOL-WITHDRAWAL-DELIRIUM | Alcohol withdrawal delirium |
| D-OPIOID-WITHDRAWAL | Opioid withdrawal |
| D-SYMPATHOMIMETIC-TOXIDROME | Sympathomimetic toxidrome |
| D-ANTICHOLINERGIC-TOXIDROME | Anticholinergic toxidrome |
| D-CARBON-MONOXIDE-POISONING | Carbon monoxide poisoning |
| D-CYANIDE-POISONING | Cyanide poisoning |

## Operational Batch Rule

- Distill 3-4 new disease leaves per batch.
- After each batch, add at least one PMC/PubMed positive real case per new disease.
- Run focused new-case ranking, then full single smoke, then combo smoke.
- If treatment ranking is abnormal, compact or complete the treatment vector field first;
  do not re-distill the whole disease unless the disease manifold itself is polluted.
