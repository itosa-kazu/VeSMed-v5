"""
V5 joint SDE case ranking test.

This is the first full-vector runtime for current V5 distillations:
  - state x is a joint vector over observed axes
  - per-disease vector fields are superposed for comorbidity candidates
  - axis_couplings become a correlated diffusion / covariance matrix
  - risk_factors modulate prior, axis response, sigma, and coupling strength

For case ranking we score a presentation snapshot by marginalizing over latent
disease day(s). The endpoint likelihood uses the Gaussian marginal of a
mean-reverting joint SDE in transformed axis space.
"""
import itertools
import json
import math
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.special import logsumexp

import v5_background

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ROOT = Path(__file__).parent.resolve()
DISTILL_DIR = ROOT / "distillations"
CASE_DIR = Path(os.environ.get("VESMED_CASE_DIR", DISTILL_DIR / "cases"))
RESULT_PATH = Path(os.environ.get("VESMED_RESULT_PATH", DISTILL_DIR / "joint_sde_case_test_result.txt"))

MANIFOLD_ORDER_HINTS = ("D137", "D-SEPSIS-GN", "D-TTP")


def env_int(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_csv(name):
    raw = os.environ.get(name, "")
    return [part.strip() for part in raw.split(",") if part.strip()]


MANIFOLD_FILTER = env_csv("VESMED_MANIFOLD_FILTER")
MANIFOLD_EXCLUDE = env_csv("VESMED_MANIFOLD_EXCLUDE")


def distillation_disease_id(path, data):
    disease = (data.get("disease") or "").strip()
    if disease:
        return disease
    stem = path.stem
    if stem.startswith("v5_"):
        return stem[3:]
    return stem


def is_manifold_distillation(data):
    if not isinstance(data, dict):
        return False
    if data.get("case_id"):
        return False
    if not (data.get("disease") or isinstance(data.get("axes"), list)):
        return False
    axes = data.get("axes")
    return isinstance(axes, list) and any(isinstance(axis, dict) and axis.get("axis_id") for axis in axes)


def manifold_order_key(item):
    label, _ = item
    try:
        return (MANIFOLD_ORDER_HINTS.index(label), "")
    except ValueError:
        return (len(MANIFOLD_ORDER_HINTS), label)


def discover_manifold_paths(distill_dir=DISTILL_DIR):
    """Discover current V5 disease manifolds from distillations/.

    Case JSON and archived files are not loaded: this scans only root
    distillations/v5_*.json and requires a disease distillation shape.
    """
    paths = {}
    for path in sorted(distill_dir.glob("v5_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not is_manifold_distillation(data):
            continue
        disease_id = distillation_disease_id(path, data)
        if not disease_id:
            continue
        if MANIFOLD_FILTER and not any(token in disease_id or token in path.name for token in MANIFOLD_FILTER):
            continue
        if MANIFOLD_EXCLUDE and any(token in disease_id or token in path.name for token in MANIFOLD_EXCLUDE):
            continue
        if disease_id in paths:
            raise ValueError(f"Duplicate disease distillation id {disease_id!r}: {paths[disease_id]} and {path}")
        paths[disease_id] = path
    if not paths:
        raise RuntimeError(f"No V5 disease distillations found in {distill_dir}")
    return dict(sorted(paths.items(), key=manifold_order_key))


MANIFOLD_PATHS = discover_manifold_paths()

BACKGROUND_MODIFIERS = v5_background.load_background_modifiers()
CONDITION_SCOPE = v5_background.load_condition_scope()

T_MAX_BY_DISEASE = {
    "D137": 90.0,
    "D-SEPSIS-GN": 30.0,
    "D-TTP": 30.0,
}

N_MC = env_int("VESMED_N_MC", 2500)
SEED = 20260430
COMBO_LOG_PENALTY = -2.0
MAX_COMBO_SIZE = env_int("VESMED_MAX_COMBO_SIZE", 2)
CASE_FILTER = env_csv("VESMED_CASE_FILTER")
ONLY_COMBO_CASES = env_bool("VESMED_ONLY_COMBO_CASES", False)
SCORE_MODE = os.environ.get("VESMED_SCORE_MODE", "mc").strip().lower()
TIME_GRID_N = max(env_int("VESMED_TIME_GRID_N", 31), 1)
REPORT_MODE = os.environ.get("VESMED_REPORT_MODE", "full").strip().lower()
RANKING_TOP_N = env_int("VESMED_RANKING_TOP_N", 0)
EARLY_GRID_TIME_DAYS = (0.02, 0.1, 0.5, 1.0, 3.0, 7.0)
COMBO_ANCHOR_THRESHOLD = 2.0
COMBO_MISSING_ANCHOR_PENALTY = -60.0
SINGLE_ANCHOR_THRESHOLD = 1.0
SINGLE_MISSING_ANCHOR_PENALTY = -120.0
EXPLICIT_REQUIRED_MISSING_ANCHOR_EXTRA_PENALTY = -9000.0
NO_FORMAL_SUPPORT_LOG_PENALTY = -120.0
PARENT_FINDING_PRESENT_THRESHOLD = 0.5
GENERIC_ANCHOR_MAX_AXIS_FRACTION = 0.12
GENERIC_ANCHOR_SCORE_CAP = 4.0
DURATION_CONDITION_SAMPLE_FACTORS = (0.5, 0.75, 1.0, 1.33, 2.0)
DURATION_CONDITION_LOG_SIGMA = 0.35
DURATION_COMPATIBILITY_GRACE_FACTOR = 1.5
DURATION_COMPATIBILITY_PENALTY_SCALE = 18.0
DURATION_COMPATIBILITY_AXIS_CAP = 60.0
DURATION_COMPATIBILITY_TOTAL_CAP = 420.0
ANATOMIC_IMPOSSIBILITY_LOG_PENALTY = -600.0

FEMALE_REPRODUCTIVE_DISEASE_IDS = {
    "D-AMNIOTIC-FLUID-EMBOLISM",
    "D-CHORIOAMNIONITIS",
    "D-ECTOPIC-PREGNANCY",
    "D-FITZ-HUGH-CURTIS-SYNDROME",
    "D-HELLP-SYNDROME",
    "D-OVARIAN-TORSION",
    "D-PELVIC-INFLAMMATORY-DISEASE",
    "D-PERIPARTUM-CARDIOMYOPATHY",
    "D-PLACENTA-PREVIA",
    "D-PLACENTAL-ABRUPTION",
    "D-POSTPARTUM-ENDOMETRITIS",
    "D-POSTPARTUM-HEMORRHAGE-UTERINE-ATONY",
    "D-PREECLAMPSIA-ECLAMPSIA",
    "D-SEPTIC-ABORTION",
    "D-THREATENED-PRETERM-LABOR",
    "D-TUBO-OVARIAN-ABSCESS",
    "D-UTERINE-RUPTURE",
}

MALE_REPRODUCTIVE_DISEASE_IDS = {
    "D-ACUTE-PROSTATITIS",
    "D-BPH-URINARY-RETENTION",
    "D-EPIDIDYMO-ORCHITIS",
    "D-TESTICULAR-TORSION",
}

ACUTE_VIRAL_HEPATITIS_DISEASE_IDS = {
    "D-ACUTE-HEPATITIS-A",
    "D-ACUTE-HEPATITIS-B",
    "D-ACUTE-HEPATITIS-E",
}

TOXIDROME_EXPLICIT_ANCHOR_DISEASE_IDS = {
    "D-BETA-BLOCKER-TOXICITY",
    "D-CALCIUM-CHANNEL-BLOCKER-TOXICITY",
    "D-CARBON-MONOXIDE-POISONING",
    "D-CYANIDE-POISONING",
    "D-DIGOXIN-TOXICITY",
    "D-ETHYLENE-GLYCOL-POISONING",
    "D-IRON-POISONING",
    "D-LITHIUM-TOXICITY",
    "D-METFORMIN-ASSOCIATED-LACTIC-ACIDOSIS",
    "D-METHANOL-POISONING",
    "D-OPIOID-INTOXICATION",
    "D-ORGANOPHOSPHATE-POISONING",
    "D-SALICYLATE-TOXICITY",
    "D-THEOPHYLLINE-TOXICITY",
    "D-TRICYCLIC-ANTIDEPRESSANT-TOXICITY",
}

TOXIDROME_ANCHOR_TOKENS = {
    "D-BETA-BLOCKER-TOXICITY": ("beta_blocker", "propranolol", "atenolol", "metoprolol"),
    "D-CALCIUM-CHANNEL-BLOCKER-TOXICITY": ("calcium_channel_blocker", "amlodipine", "verapamil", "diltiazem", "nifedipine"),
    "D-CARBON-MONOXIDE-POISONING": ("carbon_monoxide", "carboxyhemoglobin", "co_exposure"),
    "D-CYANIDE-POISONING": ("cyanide", "thiocyanate", "cyanogenic"),
    "D-DIGOXIN-TOXICITY": ("digoxin",),
    "D-ETHYLENE-GLYCOL-POISONING": ("ethylene_glycol", "glycolate", "oxalate"),
    "D-IRON-POISONING": ("iron", "ferrous", "ferric"),
    "D-LITHIUM-TOXICITY": ("lithium",),
    "D-METFORMIN-ASSOCIATED-LACTIC-ACIDOSIS": ("metformin",),
    "D-METHANOL-POISONING": ("methanol", "formate"),
    "D-OPIOID-INTOXICATION": ("opioid", "opiate", "naloxone", "fentanyl", "morphine", "oxycodone", "heroin"),
    "D-ORGANOPHOSPHATE-POISONING": ("organophosphate", "cholinesterase", "atropine", "pralidoxime"),
    "D-SALICYLATE-TOXICITY": ("salicylate", "aspirin"),
    "D-THEOPHYLLINE-TOXICITY": ("theophylline", "aminophylline"),
    "D-TRICYCLIC-ANTIDEPRESSANT-TOXICITY": ("tricyclic", "amitriptyline", "nortriptyline", "imipramine"),
}

SPECIFIC_CONTEXT_EXPLICIT_ANCHOR_DISEASE_IDS = {
    "D-ACUTE-EPIGLOTTITIS",
    "D-ACUTE-CHOLECYSTITIS",
    "D-ACUTE-INTERMITTENT-PORPHYRIA",
    "D-ACUTE-HIV",
    "D-ACUTE-KIDNEY-INJURY",
    "D-ACUTE-LIMB-ISCHEMIA",
    "D-ACUTE-LIVER-FAILURE",
    "D-ACUTE-MESENTERIC-ISCHEMIA",
    "D-ACUTE-MYOCARDIAL-INFARCTION",
    "D-ACUTE-MYOCARDITIS",
    "D-ACUTE-SYMPTOMATIC-HYPONATREMIA",
    "D-ACUTE-SYMPTOMATIC-HYPERNATREMIA",
    "D-ALCOHOL-WITHDRAWAL-DELIRIUM",
    "D-ALCOHOLIC-HEPATITIS",
    "D-AMNIOTIC-FLUID-EMBOLISM",
    "D-ANAPHYLAXIS",
    "D-AORTIC-DISSECTION",
    "D-ASTHMA-EXACERBATION",
    "D-BABESIOSIS",
    "D-BURN-INJURY",
    "D-CARDIOGENIC-SHOCK",
    "D-CAR-T-CRS",
    "D-COMPLETE-ATRIOVENTRICULAR-BLOCK",
    "D-CIRRHOSIS-ACUTE-DECOMPENSATION",
    "D-DIABETIC-KETOACIDOSIS",
    "D-DIFFUSE-ALVEOLAR-HEMORRHAGE",
    "D-FAT-EMBOLISM-SYNDROME",
    "D-HEMOTHORAX",
    "D-HEPATIC-ENCEPHALOPATHY",
    "D-HYPOTHERMIA",
    "D-HYPEROSMOLAR-HYPERGLYCEMIC-STATE",
    "D-INVASIVE-ASPERGILLOSIS",
    "D-PERIPARTUM-CARDIOMYOPATHY",
    "D-PHEOCHROMOCYTOMA-CRISIS",
    "D-PELVIC-FRACTURE",
    "D-PEDIATRIC-DEHYDRATION",
    "D-LUNG-ABSCESS",
    "D-MALIGNANT-HYPERTHERMIA",
    "D-MALARIA-FALCIPARUM",
    "D-MYXEDEMA-COMA",
    "D-NEUROLEPTIC-MALIGNANT-SYNDROME",
    "D-PULMONARY-EMBOLISM",
    "D-SEROTONIN-SYNDROME",
    "D-SEVERE-HYPERCALCEMIA",
    "D-SEVERE-HYPOKALEMIA",
    "D-SEVERE-HYPOGLYCEMIA",
    "D-SICKLE-CELL-ACUTE-CHEST",
    "D-STATUS-EPILEPTICUS",
    "D-SYSTEMIC-SCLEROSIS-RENAL-CRISIS",
    "D-TETANUS",
    "D-TB-DISSEMINATED",
    "D-THYROID-STORM",
    "D-TRICHINELLOSIS",
    "D-TRAPS",
    "D-ULCERATIVE-COLITIS-SEVERE-FLARE",
    "D-ATRIAL-FIBRILLATION",
    "D-BRONCHIOLITIS",
    "D-BOWEL-OBSTRUCTION",
    "D-BUDD-CHIARI-SYNDROME",
    "D-CATHETER-ASSOCIATED-UTI",
    "D-CHRONIC-SUBDURAL-HEMATOMA",
    "D-CROHN-DISEASE-FLARE",
    "D-CROUP",
    "D-ADENOVIRUS-INFECTION",
    "D-ENTEROCOCCAL-BACTEREMIA",
    "D-HISTOPLASMOSIS-DISSEMINATED",
    "D-INTUSSUSCEPTION",
    "D-IGA-VASCULITIS",
    "D-NOCARDIOSIS",
    "D-NONTYPHOID-SALMONELLA-BACTEREMIA",
    "D-OBSTRUCTIVE-PYELONEPHRITIS",
    "D-PERINEPHRIC-ABSCESS",
    "D-PSEUDOMONAS-BACTEREMIA",
    "D-PYELONEPHRITIS",
    "D-REFEEDING-SYNDROME",
    "D-SICK-SINUS-SYNDROME",
    "D-STRANGULATED-BOWEL-OBSTRUCTION",
    "D-STRONGYLOIDES-HYPERINFECTION",
    "D-SUPERIOR-VENA-CAVA-SYNDROME",
    "D-TAKOTSUBO-CARDIOMYOPATHY",
    "D-TOXOPLASMOSIS",
    "D-VENTRICULAR-FIBRILLATION",
    "D-VENTRICULAR-TACHYCARDIA",
}

SPECIFIC_CONTEXT_ANCHOR_TOKENS = {
    "D-ACUTE-CHOLECYSTITIS": ("gallbladder", "murphy", "cholecystic", "cystic_duct"),
    "D-ACUTE-EPIGLOTTITIS": ("epiglottitis", "epiglottic", "stridor", "drooling", "sore_throat"),
    "D-ACUTE-HIV": ("hiv", "seroconversion", "p24", "cd4", "sexual_exposure"),
    "D-ACUTE-INTERMITTENT-PORPHYRIA": ("porphobilinogen", "aminolevulinic", "porphyria", "dark_urine"),
    "D-ACUTE-KIDNEY-INJURY": ("creatinine", "anuria", "oliguria", "rhabdomyolysis", "myoglobin", "creatine_kinase", "urea"),
    "D-ACUTE-LIMB-ISCHEMIA": ("limb_ischemia", "arterial_occlusion", "pulse_deficit", "ankle_brachial", "limb_paresthesia", "limb_skin_coolness"),
    "D-ACUTE-LIVER-FAILURE": ("prothrombin_time_inr", "hepatic_encephalopathy", "jaundice", "bilirubin", "ammonia", "meld"),
    "D-ACUTE-MESENTERIC-ISCHEMIA": ("mesenteric", "bowel_ischemia", "bowel_wall_hypoenhancement", "pneumatosis", "portal_vein_thrombosis"),
    "D-ACUTE-MYOCARDIAL-INFARCTION": ("coronary", "troponin", "st_segment", "myocardial_infarction"),
    "D-ACUTE-MYOCARDITIS": ("myocarditis", "troponin", "cardiac_mri", "left_ventricular", "myocardial", "bradycardia", "atrioventricular_block"),
    "D-ALCOHOLIC-HEPATITIS": ("alcohol", "ethanol", "drinking", "alcoholic"),
    "D-AMNIOTIC-FLUID-EMBOLISM": ("pregnancy", "pregnant", "labor", "delivery", "postpartum", "amniotic"),
    "D-ANAPHYLAXIS": ("anaphylaxis", "allergen", "urticaria", "angioedema", "wheeze", "epinephrine"),
    "D-AORTIC-DISSECTION": ("aortic_dissection", "aortic_intimal_flap", "aortic_false_lumen", "renal_artery_malperfusion", "branch_vessel_involvement"),
    "D-ASTHMA-EXACERBATION": ("asthma", "wheezing", "bronchospasm", "bronchodilator"),
    "D-BABESIOSIS": ("babesia", "babesiosis", "parasitemia", "intraerythrocytic", "tick_exposure", "hemolysis"),
    "D-BURN-INJURY": ("burn", "scald", "thermal_injury", "burn_surface_area"),
    "D-CARDIOGENIC-SHOCK": ("cardiogenic", "left_ventricular", "ejection_fraction", "bnp", "cardiac_index", "myocardial_infarction"),
    "D-CAR-T-CRS": ("car_t", "chimeric_antigen", "tocilizumab", "cytokine_release", "serum_il6"),
    "D-CIRRHOSIS-ACUTE-DECOMPENSATION": ("cirrhosis", "variceal", "varices", "portal_hypertension", "chronic_liver"),
    "D-COMPLETE-ATRIOVENTRICULAR-BLOCK": ("complete_atrioventricular_block", "complete_av_block", "third_degree_av_block", "av_block"),
    "D-DIFFUSE-ALVEOLAR-HEMORRHAGE": ("alveolar_hemorrhage", "hemoptysis", "bloody_bronchoalveolar", "hemosiderin", "capillaritis"),
    "D-FAT-EMBOLISM-SYNDROME": ("fat_embolism", "long_bone_fracture", "orthopedic", "petechial_rash"),
    "D-HEPATIC-ENCEPHALOPATHY": ("hepatic", "ammonia", "cirrhosis", "asterixis", "jaundice", "liver_failure"),
    "D-HEMOTHORAX": ("hemothorax", "pleural_blood", "thoracic_trauma", "chest_trauma"),
    "D-HYPOTHERMIA": ("hypothermia", "cold_exposure", "rewarming"),
    "D-INVASIVE-ASPERGILLOSIS": ("aspergillus", "galactomannan", "halo_sign", "neutropenia", "immunosuppression"),
    "D-LUNG-ABSCESS": ("lung_abscess", "cavitary", "air_fluid_level"),
    "D-MALIGNANT-HYPERTHERMIA": ("malignant_hyperthermia", "volatile_anesthetic", "succinylcholine", "anesthesia_trigger", "ryanodine"),
    "D-MALARIA-FALCIPARUM": ("malaria", "plasmodium", "falciparum", "parasitemia", "thick_smear", "thin_smear", "travel"),
    "D-MYXEDEMA-COMA": ("myxedema", "hypothyroidism", "tsh", "free_t4", "hypothermia"),
    "D-NEUROLEPTIC-MALIGNANT-SYNDROME": ("neuroleptic", "antipsychotic", "dopamine_antagonist", "lead_pipe_rigidity", "creatine_kinase"),
    "D-PERIPARTUM-CARDIOMYOPATHY": ("pregnancy", "pregnant", "peripartum", "postpartum", "delivery", "cesarean"),
    "D-PHEOCHROMOCYTOMA-CRISIS": ("pheochromocytoma", "catecholamine", "metanephrine", "adrenal_mass", "paroxysmal_hypertension"),
    "D-PELVIC-FRACTURE": ("pelvic_fracture", "pelvis_fracture", "acetabular_fracture", "trauma", "fall"),
    "D-PEDIATRIC-DEHYDRATION": ("pediatric", "infant", "child", "dehydration"),
    "D-PULMONARY-EMBOLISM": ("pulmonary_embolism", "pulmonary_artery_filling_defect", "d_dimer", "deep_vein_thrombosis"),
    "D-SEROTONIN-SYNDROME": ("serotonergic", "serotonin", "ssri", "maoi", "clonus", "hyperreflexia"),
    "D-SEVERE-HYPERCALCEMIA": ("calcium", "hypercalcemia", "corrected_serum_calcium", "ionized_calcium"),
    "D-SICKLE-CELL-ACUTE-CHEST": ("sickle", "hemoglobin_s", "acute_chest_syndrome"),
    "D-STATUS-EPILEPTICUS": ("seizure", "status_epilepticus", "convulsion", "epileptiform"),
    "D-SYSTEMIC-SCLEROSIS-RENAL-CRISIS": ("systemic_sclerosis", "scleroderma", "rna_polymerase", "sclerodactyly", "raynaud"),
    "D-TB-DISSEMINATED": ("tuberculosis", "mycobacterium", "afb", "miliary", "caseating_granuloma", "tb_exposure"),
    "D-TETANUS": ("tetanus", "trismus", "lockjaw", "muscle_spasm", "wound"),
    "D-THYROID-STORM": ("thyroid", "tsh", "free_t4", "goiter", "graves"),
    "D-TRICHINELLOSIS": ("trichinella", "raw_pork", "undercooked_meat", "eosinophil", "myalgia", "periorbital_edema"),
    "D-TRAPS": ("traps", "tnfrsf1a", "periodic_fever", "recurrent_fever", "autoinflammatory"),
    "D-ULCERATIVE-COLITIS-SEVERE-FLARE": ("ulcerative_colitis", "bloody_diarrhea", "hematochezia", "rectal_bleeding", "tenesmus", "colitis"),
    "D-ATRIAL-FIBRILLATION": ("atrial_fibrillation", "irregularly_irregular"),
    "D-BRONCHIOLITIS": ("bronchiolitis", "rsv", "infant"),
    "D-BOWEL-OBSTRUCTION": ("bowel_obstruction", "intestinal_obstruction", "transition_point", "air_fluid_level", "bowel_dilation", "obstipation", "feculent"),
    "D-BUDD-CHIARI-SYNDROME": ("budd_chiari", "hepatic_vein", "portal_vein_thrombosis", "caudate_lobe", "ascites", "hepatomegaly"),
    "D-CATHETER-ASSOCIATED-UTI": ("urinary_catheter", "foley", "catheter", "bacteriuria", "urine_culture", "pyuria"),
    "D-CHRONIC-SUBDURAL-HEMATOMA": ("subdural", "hematoma", "head_trauma", "fall", "ct_subdural"),
    "D-CROHN-DISEASE-FLARE": ("crohn", "ileitis", "terminal_ileum", "skip_lesion", "fistula", "perianal", "bloody_diarrhea", "chronic_diarrhea"),
    "D-CROUP": ("croup", "barking_cough", "steeple_sign", "stridor"),
    "D-ADENOVIRUS-INFECTION": ("adenovirus", "adenoviral", "conjunctivitis", "pharyngoconjunctival", "hemorrhagic_cystitis", "viral_pneumonia"),
    "D-ENTEROCOCCAL-BACTEREMIA": ("enterococcus", "enterococcal", "e_faecalis", "e_faecium", "blood_culture", "endocarditis", "catheter"),
    "D-HISTOPLASMOSIS-DISSEMINATED": ("histoplasma", "histoplasmosis", "intracellular_yeast", "fungal_antigen", "endemic_mycosis", "adrenal_involvement", "bone_marrow"),
    "D-INTUSSUSCEPTION": ("intussusception", "target_sign", "sausage_mass", "currant_jelly", "bowel_telescoping", "lead_point"),
    "D-IGA-VASCULITIS": ("iga_vasculitis", "palpable_purpura", "lower_limb_purpura", "iga_nephritis", "hematuria", "arthralgia"),
    "D-NOCARDIOSIS": ("nocardia", "nocardiosis", "branching_filamentous", "acid_fast_filament", "brain_abscess", "skin_abscess"),
    "D-NONTYPHOID-SALMONELLA-BACTEREMIA": ("salmonella", "nontyphoid_salmonella", "blood_culture", "gastroenteritis", "bacteremia"),
    "D-OBSTRUCTIVE-PYELONEPHRITIS": ("hydronephrosis", "ureteral_obstruction", "obstructing_stone", "obstructive_uropathy", "pyelonephritis", "costovertebral_angle", "cva_tenderness"),
    "D-PERINEPHRIC-ABSCESS": ("perinephric_abscess", "renal_abscess", "perirenal_abscess", "flank_mass", "flank_pain", "cva_tenderness"),
    "D-PSEUDOMONAS-BACTEREMIA": ("pseudomonas", "p_aeruginosa", "pseudomonas_aeruginosa", "ecthyma_gangrenosum", "blood_culture", "central_line"),
    "D-PYELONEPHRITIS": ("pyelonephritis", "flank_pain", "costovertebral_angle", "cva_tenderness", "pyuria", "bacteriuria", "urine_culture"),
    "D-REFEEDING-SYNDROME": ("refeeding", "hypophosphatemia", "phosphate", "malnutrition", "starvation", "nutrition_restart", "thiamine"),
    "D-SICK-SINUS-SYNDROME": ("sick_sinus", "sinus_pause", "sinus_arrest", "tachy_brady"),
    "D-STRANGULATED-BOWEL-OBSTRUCTION": ("strangulated_bowel", "closed_loop", "bowel_ischemia", "bowel_obstruction", "transition_point", "pneumatosis", "peritonitis"),
    "D-STRONGYLOIDES-HYPERINFECTION": ("strongyloides", "larvae", "larva", "rhabditiform", "filariform", "htlv", "eosinophil"),
    "D-SUPERIOR-VENA-CAVA-SYNDROME": ("superior_vena_cava", "svc_obstruction", "venous_distension", "upper_extremity_edema", "facial_neck_swelling", "mediastinal_mass"),
    "D-TAKOTSUBO-CARDIOMYOPATHY": ("takotsubo", "apical_ballooning", "wall_motion_beyond_single_coronary", "emotional_stress"),
    "D-TOXOPLASMOSIS": ("toxoplasma", "toxoplasmosis", "ring_enhancing", "brain_lesion", "hiv", "cd4", "cat_exposure"),
    "D-VENTRICULAR-FIBRILLATION": ("ventricular_fibrillation",),
    "D-VENTRICULAR-TACHYCARDIA": ("ventricular_tachycardia", "wide_complex_tachycardia"),
}

EXPLICIT_ANCHOR_REQUIRED_DISEASE_IDS = ACUTE_VIRAL_HEPATITIS_DISEASE_IDS | {
    "D-ACETAMINOPHEN-TOXICITY",
    "D-ACUTE-RESPIRATORY-DISTRESS-SYNDROME",
    "D-DENGUE",
    "D-INCARCERATED-GROIN-HERNIA",
} | TOXIDROME_EXPLICIT_ANCHOR_DISEASE_IDS | SPECIFIC_CONTEXT_EXPLICIT_ANCHOR_DISEASE_IDS

NOISE_COUPLING_TYPES = {"", "noise_correlation", "mixed"}
DRIFT_COUPLING_TYPES = {"drift", "hazard_drift", "event_transition", "mixed"}
LATENT_MECHANISM_CATEGORY = "latent_mechanism"
_CANDIDATE_AXIS_SET_CACHE = {}
_CANDIDATE_FORMAL_AXIS_SET_CACHE = {}


GENERIC_ANCHOR_EXCLUDED_CATEGORIES = {
    "derived_hazard",
    LATENT_MECHANISM_CATEGORY,
    "vital",
}

GENERIC_ANCHOR_LOW_SPECIFICITY_AXES = {
    "body_temperature",
    "heart_rate",
    "respiratory_rate",
    "systolic_blood_pressure",
    "diastolic_blood_pressure",
    "mean_arterial_pressure",
    "oxygen_saturation",
    "white_blood_cell_count",
    "absolute_neutrophil_count",
    "neutrophil_fraction",
    "lymphocyte_fraction",
    "serum_crp",
    "erythrocyte_sedimentation_rate",
    "serum_ldh",
    "serum_albumin",
    "serum_creatinine",
    "blood_urea_nitrogen",
    "serum_sodium",
    "serum_potassium",
    "serum_chloride",
}

_AXIS_MANIFOLD_FREQUENCY_CACHE = {}


HEALTHY_OVERRIDES = {
    "body_temperature": {"unit": "°C", "baseline_range": (36.5, 37.5), "log_scale": False},
    "heart_rate": {"unit": "beats_per_min", "baseline_range": (60.0, 90.0), "log_scale": False},
    "respiratory_rate": {"unit": "breaths_per_min", "baseline_range": (12.0, 20.0), "log_scale": False},
    "systolic_blood_pressure": {"unit": "mmHg", "baseline_range": (100.0, 140.0), "log_scale": False},
    "mean_arterial_pressure": {"unit": "mmHg", "baseline_range": (70.0, 100.0), "log_scale": False},
    "oxygen_saturation": {"unit": "%", "baseline_range": (95.0, 100.0), "log_scale": False},
    "urine_output": {"unit": "mL/kg/hr", "baseline_range": (0.5, 1.5), "log_scale": False},
    "white_blood_cell_count": {"unit": "10^9/L", "baseline_range": (4.0, 10.0), "log_scale": False},
    "absolute_neutrophil_count": {"unit": "10^9/L", "baseline_range": (2.0, 7.0), "log_scale": False},
    "neutrophil_fraction": {"unit": "percent", "baseline_range": (40.0, 75.0), "log_scale": False},
    "lymphocyte_fraction": {"unit": "percent", "baseline_range": (20.0, 45.0), "log_scale": False},
    "monocyte_fraction": {"unit": "percent", "baseline_range": (2.0, 10.0), "log_scale": False},
    "eosinophil_fraction": {"unit": "percent", "baseline_range": (0.0, 6.0), "log_scale": False},
    "basophil_fraction": {"unit": "percent", "baseline_range": (0.0, 2.0), "log_scale": False},
    "hemoglobin": {"unit": "g/dL", "baseline_range": (12.0, 17.0), "log_scale": False},
    "hematocrit": {"unit": "percent", "baseline_range": (36.0, 50.0), "log_scale": False},
    "platelet_count": {"unit": "10^9/L", "baseline_range": (150.0, 350.0), "log_scale": False},
    "serum_crp": {"unit": "mg/L", "baseline_range": (0.2, 5.0), "log_scale": True},
    "erythrocyte_sedimentation_rate": {"unit": "mm_per_hr", "baseline_range": (0.0, 20.0), "log_scale": False},
    "serum_procalcitonin": {"unit": "ng/mL", "baseline_range": (0.02, 0.1), "log_scale": True},
    "serum_lactate": {"unit": "mmol/L", "baseline_range": (0.5, 2.0), "log_scale": False},
    "serum_creatinine": {"unit": "mg/dL", "baseline_range": (0.6, 1.2), "log_scale": False},
    "blood_urea_nitrogen": {"unit": "mg/dL", "baseline_range": (7.0, 20.0), "log_scale": False},
    "serum_sodium": {"unit": "mmol/L", "baseline_range": (135.0, 145.0), "log_scale": False},
    "serum_potassium": {"unit": "mmol/L", "baseline_range": (3.5, 5.0), "log_scale": False},
    "serum_chloride": {"unit": "mmol/L", "baseline_range": (98.0, 107.0), "log_scale": False},
    "serum_bicarbonate": {"unit": "mmol/L", "baseline_range": (22.0, 29.0), "log_scale": False},
    "serum_calcium": {"unit": "mg/dL", "baseline_range": (8.5, 10.5), "log_scale": False},
    "serum_magnesium": {"unit": "mg/dL", "baseline_range": (1.7, 2.4), "log_scale": False},
    "serum_phosphate": {"unit": "mg/dL", "baseline_range": (2.5, 4.5), "log_scale": False},
    "thyroid_stimulating_hormone": {"unit": "mIU/L", "baseline_range": (0.4, 4.5), "log_scale": False},
    "left_ventricular_ejection_fraction": {"unit": "percent", "baseline_range": (55.0, 70.0), "log_scale": False},
    "serum_ferritin": {"unit": "ng/mL", "baseline_range": (20.0, 250.0), "log_scale": True},
    "serum_ldh": {"unit": "U/L", "baseline_range": (120.0, 240.0), "log_scale": True},
    "serum_ast": {"unit": "U/L", "baseline_range": (10.0, 40.0), "log_scale": False},
    "serum_alt": {"unit": "U/L", "baseline_range": (7.0, 56.0), "log_scale": False},
    "serum_albumin": {"unit": "g/dL", "baseline_range": (3.5, 5.0), "log_scale": False},
    "serum_bilirubin_total": {"unit": "mg/dL", "baseline_range": (0.3, 1.2), "log_scale": True},
    "serum_bilirubin_indirect": {"unit": "mg/dL", "baseline_range": (0.1, 1.0), "log_scale": True},
    "serum_haptoglobin": {"unit": "mg/dL", "baseline_range": (30.0, 200.0), "log_scale": False},
    "reticulocyte_count": {"unit": "10^9/L", "baseline_range": (25.0, 100.0), "log_scale": False},
    "schistocyte_fraction": {"unit": "percent_red_cells", "baseline_range": (0.0, 0.5), "log_scale": False},
    "adamts13_activity": {"unit": "percent_of_normal", "baseline_range": (50.0, 150.0), "log_scale": False},
    "anti_adamts13_igg_inhibitor_titer": {"unit": "BU", "baseline_range": (0.0, 0.4), "log_scale": False},
    "ultra_large_vwf_multimer_activity": {"unit": "relative_activity_0_1", "baseline_range": (0.0, 0.1), "log_scale": False},
    "serum_fibrinogen": {"unit": "mg/dL", "baseline_range": (200.0, 400.0), "log_scale": False},
    "d_dimer": {"unit": "µg/mL_FEU", "baseline_range": (0.05, 0.5), "log_scale": True},
    "prothrombin_time_inr": {"unit": "INR", "baseline_range": (0.9, 1.2), "log_scale": False},
    "activated_partial_thromboplastin_time": {"unit": "seconds", "baseline_range": (25.0, 40.0), "log_scale": False},
    "blood_culture_positivity_probability": {"unit": "probability_0_1", "baseline_range": (0.0, 0.02), "log_scale": False},
    "blood_culture_bacterial_load": {"unit": "CFU_per_mL", "baseline_range": (1e-9, 1e-6), "log_scale": True},
}


def parse_interval(value):
    if value is None:
        return None
    if isinstance(value, list) and len(value) >= 2:
        lo = float(value[0])
        hi = float(value[1])
        if math.isfinite(lo) and math.isfinite(hi):
            return (min(lo, hi), max(lo, hi))
    if isinstance(value, tuple) and len(value) == 2:
        return (float(min(value)), float(max(value)))
    return None


def midpoint(interval, default=1.0):
    interval = parse_interval(interval)
    if interval is None:
        return default
    return 0.5 * (interval[0] + interval[1])


@lru_cache(maxsize=4096)
def norm_unit(unit):
    if unit is None:
        return ""
    return (
        str(unit)
        .replace("µ", "u")
        .replace("μ", "u")
        .replace("^", "")
        .replace(" ", "")
        .replace("_", "")
        .lower()
    )


def convert_value(value, from_unit, to_unit, axis_id):
    src = norm_unit(from_unit)
    dst = norm_unit(to_unit)
    if not src or not dst or src == dst:
        return value

    if src in ("mg/dl", "mgperdl") and dst in ("mg/l", "mgperl"):
        return value * 10.0
    if src in ("mg/l", "mgperl") and dst in ("mg/dl", "mgperdl"):
        return value / 10.0
    if src in ("ng/ml", "ngperml") and dst in ("ng/l", "ngperl"):
        return value * 1000.0
    if src in ("ng/l", "ngperl") and dst in ("ng/ml", "ngperml"):
        return value / 1000.0
    if src in ("g/l", "gperl") and dst in ("g/dl", "gperdl"):
        return value / 10.0
    if src in ("g/dl", "gperdl") and dst in ("g/l", "gperl"):
        return value * 10.0
    if src in ("fraction", "ratio") and dst in ("percent", "%", "percentage"):
        return value * 100.0
    if src in ("percent", "%", "percentage") and dst in ("fraction", "ratio"):
        return value / 100.0
    if src in ("percentleukocytes", "percentofleukocytes") and dst in ("fraction", "ratio"):
        return value / 100.0
    if src in ("fraction", "ratio") and dst in ("percentleukocytes", "percentofleukocytes"):
        return value * 100.0
    if src in ("103/ul", "103perul", "10e3/ul", "10e3perul") and dst in ("109/l", "109perl"):
        return value
    if src in ("109/l", "109perl") and dst in ("103/ul", "103perul", "10e3/ul", "10e3perul"):
        return value
    if axis_id in ("white_blood_cell_count", "absolute_neutrophil_count", "lymphocyte_count", "platelet_count", "reticulocyte_count") and src in (
        "/ul",
        "perul",
        "cells/ul",
        "cellsperul",
    ) and dst in ("109/l", "109perl"):
        return value / 1000.0
    if axis_id in ("white_blood_cell_count", "absolute_neutrophil_count", "lymphocyte_count", "platelet_count", "reticulocyte_count") and src in (
        "109/l",
        "109perl",
    ) and dst in ("/ul", "perul", "cells/ul", "cellsperul"):
        return value * 1000.0
    if src in ("kgpermonth", "kg/month") and dst in ("kgperweek", "kg/week"):
        return value / 4.345
    if src in ("kgperweek", "kg/week") and dst in ("kgpermonth", "kg/month"):
        return value * 4.345

    if axis_id == "oxygen_requirement_level" and src in ("l/min", "lpermin", "lpm") and dst in ("ordinal05", "ordinal0to5"):
        if value <= 0.0:
            return 0.0
        if value <= 2.0:
            return 1.0
        if value <= 6.0:
            return 2.0
        if value <= 15.0:
            return 3.0
        if value <= 30.0:
            return 4.0
        return 5.0

    if axis_id == "serum_creatinine" and src in ("umol/l", "umolperl") and dst in ("mg/dl", "mgperdl"):
        return value / 88.4
    if axis_id == "serum_creatinine" and src in ("mg/dl", "mgperdl") and dst in ("umol/l", "umolperl"):
        return value * 88.4
    if axis_id == "serum_creatinine" and src in ("mg/l", "mgperl") and dst in ("mg/dl", "mgperdl"):
        return value / 10.0

    if axis_id == "urine_output" and src in ("ml/h", "mlperh", "ml/hr", "mlperhr") and dst in ("ml/kg/hr", "ml/kg/h", "mlperkgperhr", "mlperkgperh"):
        # Case reports often omit weight when reporting ICU oliguria as mL/h.
        # Use a conservative adult-normalized default so "<10 mL/h" is not
        # misread as 10 mL/kg/hr.
        return value / 70.0
    if axis_id == "urine_output" and src in ("ml/kg/hr", "ml/kg/h", "mlperkgperhr", "mlperkgperh") and dst in ("ml/h", "mlperh", "ml/hr", "mlperhr"):
        return value * 70.0

    if axis_id == "blood_urea_nitrogen" and src in ("mmol/l", "mmolperl") and dst in ("mg/dl", "mgperdl"):
        return value * 2.801
    if axis_id == "blood_urea_nitrogen" and src in ("g/l", "gperl") and dst in ("mg/dl", "mgperdl"):
        return value * 46.7
    if axis_id in ("serum_calcium", "corrected_serum_calcium") and src in ("mmol/l", "mmolperl") and dst in ("mg/dl", "mgperdl"):
        return value * 4.008
    if axis_id in ("serum_calcium", "corrected_serum_calcium") and src in ("mg/dl", "mgperdl") and dst in ("mmol/l", "mmolperl"):
        return value / 4.008
    if axis_id == "serum_magnesium" and src in ("mmol/l", "mmolperl") and dst in ("mg/dl", "mgperdl"):
        return value * 2.43
    if axis_id == "serum_magnesium" and src in ("mg/dl", "mgperdl") and dst in ("mmol/l", "mmolperl"):
        return value / 2.43
    if axis_id == "serum_phosphate" and src in ("mmol/l", "mmolperl") and dst in ("mg/dl", "mgperdl"):
        return value * 3.10
    if axis_id == "serum_phosphate" and src in ("mg/dl", "mgperdl") and dst in ("mmol/l", "mmolperl"):
        return value / 3.10

    if axis_id == "free_thyroxine" and src in ("pmol/l", "pmolperl") and dst in ("ng/dl", "ngperdl"):
        return value / 12.87
    if axis_id == "free_thyroxine" and src in ("ng/dl", "ngperdl") and dst in ("pmol/l", "pmolperl"):
        return value * 12.87
    if axis_id == "free_triiodothyronine" and src in ("pmol/l", "pmolperl") and dst in ("pg/ml", "pgperml"):
        return value / 1.536
    if axis_id == "free_triiodothyronine" and src in ("pg/ml", "pgperml") and dst in ("pmol/l", "pmolperl"):
        return value * 1.536

    if src in ("k/ul", "103/ul", "109/l") and dst in ("109/l", "k/ul", "103/ul"):
        return value
    if src in ("mm/hr", "mmperhr", "mm/hour", "mmperhour") and dst in ("mmperhr", "mm/hr", "mm/hour", "mmperhour"):
        return value
    if src in ("ug/mlfeu", "ug/ml", "mg/lfeu", "mg/l") and dst in ("ug/mlfeu", "ug/ml", "mg/lfeu", "mg/l"):
        return value
    return value


def duration_value_to_days(value, unit, axis_id=None):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None

    unit_norm = norm_unit(unit)
    axis_id = str(axis_id or "")
    if unit_norm in ("hours", "hour", "hr", "hrs", "h"):
        return value / 24.0
    if unit_norm in ("days", "day", "d"):
        return value
    if unit_norm in ("weeks", "week", "wk", "wks"):
        return value * 7.0
    if unit_norm in ("months", "month", "mo", "mos"):
        return value * 30.44
    if unit_norm in ("years", "year", "yr", "yrs"):
        return value * 365.25

    if axis_id.endswith("_hours") or axis_id.endswith("_duration_hours") or "_onset_hours" in axis_id:
        return value / 24.0
    if axis_id.endswith("_days") or axis_id.endswith("_duration_days") or "_onset_days" in axis_id:
        return value
    if axis_id.endswith("_months") or axis_id.endswith("_duration_months"):
        return value * 30.44
    if axis_id.endswith("_years") or axis_id.endswith("_duration_years"):
        return value * 365.25
    return None


def observation_is_duration_axis(axis_id):
    axis_id = str(axis_id or "")
    if axis_id in {
        "symptom_duration_months",
        "time_from_symptom_onset_days",
        "time_since_limb_symptom_onset_hours",
        "time_from_pain_onset_to_care_hours",
        "time_from_pain_onset_to_presentation_hours",
        "neurologic_symptom_duration_hours",
    }:
        return True
    return (
        axis_id.endswith("_duration_days")
        or axis_id.endswith("_duration_hours")
        or axis_id.endswith("_duration_months")
        or axis_id.startswith("time_from_symptom_onset")
        or axis_id.startswith("time_since_limb_symptom_onset")
    )


def case_presentation_duration_days(case):
    """Return observed duration of the presenting illness, if structured.

    This is not an unknown-disease threshold. It conditions the latent disease
    age used in likelihood scoring when the case explicitly says how long the
    current presentation has been present.
    """
    if not isinstance(case, dict):
        return None

    durations = []
    for key in (
        "presentation_duration_days",
        "symptom_duration_days",
        "history_duration_days",
        "illness_duration_days",
    ):
        duration = duration_value_to_days(case.get(key), "days", key)
        if duration is not None:
            durations.append(duration)
    for key in ("presentation_duration_months", "symptom_duration_months"):
        duration = duration_value_to_days(case.get(key), "months", key)
        if duration is not None:
            durations.append(duration)

    for axis_id, obs in case.get("observations_by_axis", {}).items():
        if obs.get("use_in_time_conditioning") is False:
            continue
        if not observation_is_duration_axis(axis_id):
            continue
        duration = duration_value_to_days(obs.get("value"), obs.get("unit"), axis_id)
        if duration is not None:
            durations.append(duration)

    if not durations:
        return None
    # If multiple duration snippets are present, the longest general presenting
    # duration is the safest anchor. Acute sub-event durations should be kept on
    # specific event axes and can opt out with use_in_time_conditioning:false.
    return max(durations)


def observation_value_for_axis(obs, axis, axis_id):
    """Convert a case observation into the axis unit without inventing precision.

    Some PMC reports only state that a lab was normal. Encoding that as numeric
    zero is wrong for log-scale measurements such as CRP, where 0 mg/L becomes a
    mathematical extreme rather than "within the reference range".
    """
    value = obs.get("value")
    cache_key = (
        axis_id,
        axis.get("unit"),
        tuple(axis.get("baseline_range") or ()),
        tuple(axis.get("peak_value_range") or ()),
        bool(axis.get("log_scale")),
        obs.get("unit"),
        value,
    )
    value_cache = obs.setdefault("_axis_value_cache", {})
    if cache_key in value_cache:
        return value_cache[cache_key]
    src = norm_unit(obs.get("unit"))
    if src in ("qualitativenegative", "negative", "negativeflag"):
        dst = norm_unit(axis.get("unit"))
        if dst in ("probability01", "relativeactivity01", "severityscore01", "presentabsent01"):
            value_cache[cache_key] = 0.0
            return 0.0
        if axis.get("log_scale"):
            value_cache[cache_key] = 1.0
            return 1.0
        baseline = parse_interval(axis.get("baseline_range"))
        out = baseline[0] if baseline else 0.0
        value_cache[cache_key] = out
        return out
    if src in ("qualitativepositive", "positive", "positiveflag"):
        dst = norm_unit(axis.get("unit"))
        if dst in ("probability01", "relativeactivity01", "severityscore01", "presentabsent01"):
            value_cache[cache_key] = 1.0
            return 1.0
        peak = parse_interval(axis.get("peak_value_range"))
        if peak is not None:
            out = midpoint(peak)
            value_cache[cache_key] = out
            return out
        baseline = parse_interval(axis.get("baseline_range"))
        out = baseline[1] if baseline else 1.0
        value_cache[cache_key] = out
        return out
    if src == "normalflagonly":
        baseline = parse_interval(axis.get("baseline_range"))
        if baseline is None:
            out = 0.0 if float(value) <= 0.5 else 1.0
            value_cache[cache_key] = out
            return out
        if float(value) <= 0.5:
            out = midpoint(baseline)
            value_cache[cache_key] = out
            return out
        peak = parse_interval(axis.get("peak_value_range"))
        out = midpoint(peak, midpoint(baseline))
        value_cache[cache_key] = out
        return out
    out = convert_value(value, obs.get("unit"), axis.get("unit"), axis_id)
    value_cache[cache_key] = out
    return out


def raw_axis_records(data):
    for raw in data.get("axes", []) or []:
        yield raw

    for raw in data.get("latent_mechanisms", []) or []:
        axis = dict(raw)
        axis_id = axis.get("mechanism_id") or axis.get("axis_id") or axis.get("id")
        if not axis_id:
            continue
        axis["axis_id"] = axis_id
        axis["category"] = LATENT_MECHANISM_CATEGORY
        axis.setdefault("unit", "relative_activity_0_1")
        axis.setdefault("log_scale", False)
        axis.setdefault("baseline_range", axis.get("inactive_range") or [0.0, 0.05])
        axis.setdefault("peak_value_range", axis.get("active_range") or [0.6, 1.0])
        axis.setdefault("peak_day_range", None)
        axis.setdefault("plateau_duration_days", None)
        axis.setdefault("decline_half_life_days", None)
        axis.setdefault(
            "shape_free_text",
            axis.get("description") or axis.get("clinical_meaning") or "Latent pathophysiologic mechanism activity.",
        )
        yield axis


def normalize_effect_on_target(value):
    text = str(value or "").strip().lower()
    if text in ("increase", "increases", "up", "higher", "raises", "source_up_increases_target"):
        return "increase"
    if text in ("decrease", "decreases", "down", "lower", "lowers", "source_up_decreases_target"):
        return "decrease"
    if text == "source_down_increases_target":
        return "decrease"
    if text == "source_down_decreases_target":
        return "increase"
    return None


def normalize_mechanism_edge(raw):
    if raw.get("use_in_scoring") is False:
        return None
    if str(raw.get("scoring_role") or "").strip().lower() == "audit_only":
        return None
    if raw.get("mechanism_audit_origin") and raw.get("use_in_scoring") is not True:
        return None
    edge = dict(raw)
    source = (
        edge.get("source_id")
        or edge.get("source")
        or edge.get("source_axis_id")
        or edge.get("source_mechanism_id")
    )
    target = (
        edge.get("target_id")
        or edge.get("target")
        or edge.get("target_axis_id")
        or edge.get("target_mechanism_id")
    )
    effect = normalize_effect_on_target(
        edge.get("effect_on_target")
        or edge.get("direction")
        or edge.get("effect_direction")
    )
    if not source or not target or effect is None:
        return None
    edge["source_axis_id"] = source
    edge["target_axis_id"] = target
    edge["effect_on_target"] = effect
    edge.setdefault("edge_type", "pathophysiology")
    return edge


def apply_treatment_modifier_context_defaults(axis):
    if axis.get("category") != "treatment_modifier":
        return axis
    if axis.get("peak_value_range") is None or axis.get("peak_day_range") is not None:
        return axis
    axis = dict(axis)
    axis["peak_day_range"] = [-365.0, 0.0]
    axis["plateau_duration_days"] = axis.get("plateau_duration_days") or [30.0, 3650.0]
    axis["decline_half_life_days"] = axis.get("decline_half_life_days") or [30.0, 365.0]
    return axis


def load_manifold(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    axes = {}
    for raw in raw_axis_records(data):
        if not raw.get("axis_id"):
            continue
        axis = dict(raw)
        for key in [
            "baseline_range",
            "peak_day_range",
            "peak_value_range",
            "plateau_duration_days",
            "decline_half_life_days",
        ]:
            axis[key] = parse_interval(axis.get(key))
        if axis["baseline_range"] is None:
            continue
        axis = apply_treatment_modifier_context_defaults(axis)
        axes[axis["axis_id"]] = axis
    mechanism_edges = []
    for raw in (data.get("mechanism_edges") or []) + (data.get("causal_edges") or []):
        edge = normalize_mechanism_edge(raw)
        if edge is not None:
            mechanism_edges.append(edge)
    mechanism_edges_by_target = {}
    for edge in mechanism_edges:
        mechanism_edges_by_target.setdefault(edge.get("target_axis_id"), []).append(edge)
    return {
        "disease": data.get("disease", path.stem),
        "distillation_scope": data.get("distillation_scope") or {},
        "axes": axes,
        "latent_mechanisms": data.get("latent_mechanisms") or [],
        "mechanism_edges": mechanism_edges,
        "mechanism_edges_by_target": mechanism_edges_by_target,
        "axis_couplings": data.get("axis_couplings") or [],
        "risk_factors": data.get("risk_factors") or [],
        "treatments": data.get("treatments") or [],
    }


def load_master_axes(path=ROOT / "master_axes.json"):
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {a["axis_id"]: a for a in data.get("axes", []) if a.get("axis_id")}


def generic_healthy_background_override(axis_id, entry):
    axis_key = axis_id.lower()
    unit = entry.get("unit")
    unit_norm = norm_unit(unit)
    is_antibody_axis = any(token in axis_key for token in (
        "antibody",
        "autoantibody",
        "coombs",
        "antinuclear",
        "antiphospholipid",
    ))
    if not is_antibody_axis:
        return None
    if unit_norm in ("probability01", "relativeactivity01", "presentabsent01"):
        return {"unit": unit, "baseline_range": (0.0, 0.05), "log_scale": False}
    if unit_norm in ("assayunits", "assayindex", "assayunitsorindex"):
        low = 0.1 if entry.get("log_scale", False) else 0.0
        return {"unit": unit, "baseline_range": (low, 0.9), "log_scale": bool(entry.get("log_scale", False))}
    if unit_norm in ("iu/ml", "u/ml", "uml", "miu/ml"):
        low = 0.1 if entry.get("log_scale", False) else 0.0
        return {"unit": unit, "baseline_range": (low, 10.0), "log_scale": bool(entry.get("log_scale", False))}
    if axis_id == "antinuclear_antibody_titer_reciprocal":
        low = 1.0 if entry.get("log_scale", False) else 0.0
        return {"unit": unit, "baseline_range": (low, 80.0), "log_scale": bool(entry.get("log_scale", False))}
    return None


def build_background_axes(manifolds, master_axes):
    by_axis = {}
    for manifold in manifolds.values():
        for axis_id, axis in manifold["axes"].items():
            if axis.get("category") == "derived_hazard":
                continue
            entry = by_axis.setdefault(axis_id, {
                "axis_id": axis_id,
                "category": axis.get("category"),
                "unit": axis.get("unit"),
                "log_scale": bool(axis.get("log_scale", False)),
                "axis_role": axis.get("axis_role"),
                "parent_axis_id": axis.get("parent_axis_id"),
                "ranges": [],
            })
            for meta_key in ("axis_role", "parent_axis_id"):
                if not entry.get(meta_key) and axis.get(meta_key):
                    entry[meta_key] = axis.get(meta_key)
            unit = entry.get("unit") or axis.get("unit")
            lo, hi = axis["baseline_range"]
            entry["ranges"].append((
                convert_value(lo, axis.get("unit"), unit, axis_id),
                convert_value(hi, axis.get("unit"), unit, axis_id),
            ))

    for axis_id, meta in master_axes.items():
        by_axis.setdefault(axis_id, {
            "axis_id": axis_id,
            "category": meta.get("category"),
            "unit": meta.get("unit") or meta.get("unit_canonical"),
            "log_scale": bool(meta.get("log_scale", False)),
            "axis_role": meta.get("axis_role"),
            "parent_axis_id": meta.get("parent_axis_id"),
            "ranges": [],
        })

    for axis_id, meta in HEALTHY_OVERRIDES.items():
        by_axis.setdefault(axis_id, {
            "axis_id": axis_id,
            "category": "background_measurement",
            "unit": meta.get("unit"),
            "log_scale": bool(meta.get("log_scale", False)),
            "axis_role": "measurement",
            "parent_axis_id": None,
            "ranges": [],
        })

    background = {}
    for axis_id, entry in by_axis.items():
        override = (
            HEALTHY_OVERRIDES.get(axis_id)
            or v5_background.BASE_MEASURE_OVERRIDES.get(axis_id)
            or generic_healthy_background_override(axis_id, entry)
        )
        if override:
            baseline = override["baseline_range"]
            unit = override["unit"]
            log_scale = override["log_scale"]
        elif entry.get("category") == LATENT_MECHANISM_CATEGORY:
            baseline = (0.0, 0.05)
            unit = entry.get("unit") or "relative_activity_0_1"
            log_scale = False
        elif entry["ranges"]:
            lows = [r[0] for r in entry["ranges"]]
            highs = [r[1] for r in entry["ranges"]]
            baseline = (min(lows), max(highs))
            unit = entry.get("unit")
            log_scale = entry.get("log_scale", False)
        else:
            unit = entry.get("unit")
            category = entry.get("category")
            if category in ("physical_finding", "qualitative") or norm_unit(unit) in (
                "severityscore01",
                "probability01",
                "relativeactivity01",
            ):
                baseline = (0.0, 0.05)
                log_scale = False
            else:
                continue
        background[axis_id] = {
            "axis_id": axis_id,
            "category": entry.get("category"),
            "unit": unit,
            "log_scale": log_scale,
            "axis_role": entry.get("axis_role"),
            "parent_axis_id": entry.get("parent_axis_id"),
            "baseline_range": baseline,
            "peak_day_range": None,
            "peak_value_range": None,
            "plateau_duration_days": None,
            "decline_half_life_days": None,
            "_source": "base_measure_background",
        }
    return background


def fallback_axis_from_observation(axis_id, obs):
    unit = obs.get("unit")
    if norm_unit(unit) not in ("severityscore01", "probability01", "relativeactivity01", "presentabsent01"):
        return None
    return {
        "axis_id": axis_id,
        "category": obs.get("category") or "qualitative",
        "unit": unit,
        "log_scale": False,
        "axis_role": obs.get("axis_role"),
        "parent_axis_id": obs.get("parent_axis_id"),
        "baseline_range": [0.0, 0.05],
        "peak_day_range": None,
        "peak_value_range": None,
        "plateau_duration_days": None,
        "decline_half_life_days": None,
        "_source": "case_observation_background_fallback",
    }


MAPPED_EVIDENCE_SECTIONS = (
    "imaging",
    "pathology",
    "procedures",
    "diagnostics",
    "physical_exam",
    "microbiology",
    "clinical_course_events",
)
DIRECT_AXIS_SECTION_SKIP = {
    "demographics",
    "risk_context",
    "lab_trajectories",
    "observations",
    "course_observations",
    *MAPPED_EVIDENCE_SECTIONS,
}
NON_RANKING_SECTION_PREFIXES = (
    "confirmatory",
    "actual_treatment",
    "outcome",
    "follow_up",
    "treatment",
    "supportive",
)


def mapped_axis_ids(item):
    ids = []
    if item.get("axis_id"):
        ids.append(item.get("axis_id"))
    if item.get("mapped_axis_id"):
        ids.append(item.get("mapped_axis_id"))
    raw_ids = item.get("mapped_axis_ids")
    if isinstance(raw_ids, list):
        ids.extend(raw_ids)
    out = []
    for axis_id in ids:
        if axis_id and axis_id not in out:
            out.append(axis_id)
    return out


def mapped_axis_items(item):
    for axis_id in mapped_axis_ids(item):
        yield axis_id, item

    raw_axes = item.get("mapped_axes")
    if not isinstance(raw_axes, list):
        return
    for axis_item in raw_axes:
        if not isinstance(axis_item, dict):
            continue
        axis_id = axis_item.get("axis_id") or axis_item.get("mapped_axis_id")
        if axis_id:
            yield axis_id, axis_item


def can_infer_qualitative_mapped_axis(axis_id):
    qualitative_markers = (
        "_activity",
        "_presence",
        "_probability",
        "_severity",
        "_extent",
        "_need",
        "presence_in_",
        "activity_in_",
        "hazard_in_",
    )
    measurement_markers = (
        "_size_",
        "_diameter_",
        "_gradient_",
        "_count",
        "_days",
        "_mmhg",
        "_cm",
        "_mm",
    )
    if any(marker in axis_id for marker in measurement_markers):
        return False
    if axis_id.endswith("_hazard") or "_hazard_" in axis_id:
        return False
    return any(marker in axis_id for marker in qualitative_markers)


def mapped_item_is_negative(item):
    text = " ".join(
        str(item.get(key, ""))
        for key in ("finding", "result", "source_text_value")
    ).lower()
    negative_patterns = (
        r"\bnegative\b",
        r"\bnormal\b",
        r"\bno\b",
        r"no_",
        r"\bwithout\b",
        r"\babsent\b",
        r"\bresolved\b",
        r"\bdisappeared\b",
        r"\bclear\b",
        r"not\s+found",
        r"not\s+noted",
    )
    return any(re.search(pattern, text) for pattern in negative_patterns)


def infer_mapped_observation(item, axis_id, axis_item=None):
    if item.get("use_in_ranking") is False:
        return None
    axis_item = axis_item or item
    if axis_item.get("use_in_ranking") is False:
        return None
    value = axis_item.get("value")
    if value is not None:
        return value, axis_item.get("unit") or item.get("unit") or "severity_score_0_1"
    if not can_infer_qualitative_mapped_axis(axis_id):
        return None
    merged_item = {**item, **axis_item}
    if mapped_item_is_negative(merged_item):
        return 0.0, "severity_score_0_1"
    return 1.0, "severity_score_0_1"


def infer_direct_observation(axis_id, value, unit, qualitative_value=None):
    if value is not None:
        return value, unit
    if qualitative_value is None:
        return None

    q = str(qualitative_value).strip().lower()
    if not q:
        return None
    normalized_unit = norm_unit(unit)
    if axis_id == "body_temperature":
        if any(token in q for token in ("afebrile", "denied_fever", "no_fever")):
            return 36.8, unit or "degC"
        if any(token in q for token in ("high_grade_fever", "hyperpyrexia")):
            return 39.0, unit or "degC"
        if "fever" in q or "febrile" in q:
            return 38.5, unit or "degC"

    if normalized_unit in ("presentabsent01", "probability01", "relativeactivity01", "severityscore01"):
        if mapped_item_is_negative({"source_text_value": q}):
            return 0.0, unit
        return 1.0, unit

    if q in ("normal", "within_normal_limits", "within_reference_range"):
        override = HEALTHY_OVERRIDES.get(axis_id) or v5_background.BASE_MEASURE_OVERRIDES.get(axis_id)
        if override:
            return midpoint(override.get("baseline_range")), unit or override.get("unit")
    return None


def iter_direct_axis_section_items(data):
    for section, records in data.items():
        if section in DIRECT_AXIS_SECTION_SKIP:
            continue
        if any(section.startswith(prefix) for prefix in NON_RANKING_SECTION_PREFIXES):
            continue
        if not isinstance(records, list):
            continue
        for item in records:
            if isinstance(item, dict) and item.get("axis_id"):
                yield section, item


def background_axes_for_case(background_axes, case, candidate):
    """Return risk-adjusted background axes needed by this case/candidate.

    The full master/background ontology is now thousands of axes. Case ranking
    only needs observed axes, so adjusting the entire ontology for every
    candidate turns the regression into mostly repeated background bookkeeping.
    """
    candidate = tuple(candidate)
    cache = case.setdefault("_background_axes_cache", {})
    if candidate in cache:
        return cache[candidate]

    context = case.get("_background_context")
    if context is None:
        context = v5_background.background_context_for_case(case)
        case["_background_context"] = context
    adjusted = {}
    for axis_id, obs in case.get("observations_by_axis", {}).items():
        axis = background_axes.get(axis_id)
        if axis is not None:
            adjusted[axis_id] = v5_background.apply_background_modifiers_to_axis(
                axis,
                context,
                candidate,
                BACKGROUND_MODIFIERS,
                CONDITION_SCOPE,
                convert_value,
            )
            continue
        fallback = fallback_axis_from_observation(axis_id, obs)
        if fallback is not None:
            adjusted[axis_id] = fallback
    cache[candidate] = adjusted
    return adjusted


def case_item_rankable(item):
    return item.get("use_in_ranking") is not False


LEGACY_MANUAL_AXIS_BRIDGES = {
    "fever_history_activity": ("fever_history_presence",),
    "fever_activity": ("fever_history_presence",),
    "fatigue_activity": ("fatigue_presence",),
    "malaise_fatigue_activity": ("fatigue_presence", "malaise_presence"),
    "fatigue_malaise_activity": ("fatigue_presence", "malaise_presence"),
    "malaise_activity": ("malaise_presence",),
    "chills_rigors_activity": ("chills_presence", "rigors_presence"),
    "rigor_activity": ("rigors_presence",),
    "anorexia_activity": ("appetite_loss_presence",),
    "anorexia_poor_appetite_activity": ("appetite_loss_presence",),
    "weight_loss_activity": ("unintentional_weight_loss_presence",),
    "night_sweats_activity": ("night_sweats_presence",),
    "pruritus_activity": ("pruritus_presence",),
    "diarrhea_activity": ("diarrhea_presence", "watery_stool_presence"),
    "bloody_diarrhea_activity": ("bloody_diarrhea_presence",),
    "vomiting_activity": ("vomiting_presence", "gastric_fluid_vomitus_presence"),
    "nausea_vomiting_activity": ("nausea_presence", "vomiting_presence"),
    "cholelithiasis_sludge_context_probability": ("gallstone_or_biliary_sludge_context_probability",),
    "gallstone_or_biliary_sludge_context_probability": ("cholelithiasis_sludge_context_probability",),
    "gastrointestinal_bleeding_activity": ("gastrointestinal_bleeding_presence",),
    "hematochezia_activity": ("hematochezia_presence",),
    "iga_vasculitis_hematemesis_activity_in_D-IGA-VASCULITIS": ("hematemesis_presence",),
    "cough_activity": ("cough_presence",),
    "dyspnea_activity": ("dyspnea_presence",),
    "sore_throat_activity": ("sore_throat_presence",),
    "abdominal_pain_activity": ("abdominal_pain_presence",),
    "headache_activity": ("headache_presence",),
    "myalgia_activity": ("myalgia_presence",),
    "arthralgia_activity": ("arthralgia_presence",),
    "arthritis_activity": ("arthritis_presence",),
    "chest_pain_activity": ("chest_pain_presence",),
    "mental_status_abnormality_activity": ("mental_status_abnormality_presence",),
    "altered_mental_status_activity": ("mental_status_abnormality_presence",),
    "seizure_activity": ("seizure_presence",),
    "neurologic_deficit_activity": ("neurologic_deficit_presence",),
    "focal_neurologic_deficit_activity": ("focal_neurologic_deficit_presence",),
    "neck_stiffness_activity": ("neck_stiffness_presence",),
    "nuchal_rigidity_activity": ("neck_stiffness_presence",),
    "meningismus_activity": ("meningismus_presence",),
    "meningeal_signs_activity": ("meningeal_signs_presence",),
    "photophobia_activity": ("photophobia_presence",),
    "hemoptysis_activity": ("hemoptysis_presence",),
    "hemoptysis_activity_in_D-NOCARDIOSIS": ("hemoptysis_presence",),
    "pleural_effusion_activity": ("pleural_effusion_presence",),
    "pneumonia_infiltrate_extent": ("pulmonary_infiltrate_presence",),
    "pulmonary_infiltrate_extent_egpa": ("pulmonary_infiltrate_presence",),
    "pulmonary_consolidation_activity": ("pulmonary_consolidation_presence",),
    "pulmonary_edema_activity": ("pulmonary_edema_presence",),
    "respiratory_failure_activity": ("respiratory_failure_presence",),
    "dyspnea_respiratory_distress_activity": ("respiratory_distress_presence",),
    "crackles_activity": ("crackles_presence",),
    "crackles_activity_in_D-PNEUMOCOCCAL-PNEUMONIA": ("crackles_presence",),
    "bibasal_crackles_activity": ("bibasal_crackles_presence",),
    "diffuse_crackles_activity_in_D-PJP-PNEUMONIA": ("diffuse_crackles_presence",),
    "decreased_breath_sounds_activity": ("decreased_breath_sounds_presence",),
    "dullness_to_percussion_activity": ("percussion_dullness_presence",),
    "dullness_to_percussion_activity_in_D-PNEUMOCOCCAL-PNEUMONIA": ("percussion_dullness_presence",),
    "bronchial_breath_sounds_activity_in_D-PNEUMOCOCCAL-PNEUMONIA": ("bronchial_breath_sounds_presence",),
    "dysuria_activity": ("dysuria_presence",),
    "dysuria_activity_in_D-PYELONEPHRITIS": ("dysuria_presence",),
    "urinary_symptom_activity": ("lower_urinary_tract_symptom_presence",),
    "urinary_frequency_activity": ("urinary_frequency_presence",),
    "urinary_frequency_urgency_activity": ("urinary_frequency_urgency_presence",),
    "urinary_frequency_urgency_activity_in_D-PYELONEPHRITIS": ("urinary_frequency_urgency_presence",),
    "urinary_retention_activity": ("urinary_retention_presence",),
    "urinary_obstruction_activity": ("urinary_obstruction_presence",),
    "flank_pain_activity": ("flank_pain_presence",),
    "flank_pain_activity_in_D-PERINEPHRIC-ABSCESS": ("flank_pain_presence",),
    "flank_pain_activity_in_D-PYELONEPHRITIS": ("flank_pain_presence",),
    "flank_pain_activity_in_D-RENAL-ABSCESS": ("flank_pain_presence",),
    "back_flank_pain_activity_in_D-IGG4-RELATED-DISEASE": ("flank_pain_presence",),
    "cva_tenderness_activity_in_D-PERINEPHRIC-ABSCESS": ("costovertebral_angle_tenderness_presence",),
    "cva_tenderness_activity_in_D-PYELONEPHRITIS": ("costovertebral_angle_tenderness_presence",),
    "cva_tenderness_activity_in_D-RENAL-ABSCESS": ("costovertebral_angle_tenderness_presence",),
    "upper_urinary_tract_pain_tenderness_activity": ("upper_urinary_tract_pain_or_tenderness_presence",),
    "suprapubic_pain_activity": ("suprapubic_pain_presence",),
    "suprapubic_tenderness_activity": ("suprapubic_tenderness_presence",),
    "hematuria_activity": ("hematuria_presence",),
    "gross_hematuria_activity": ("gross_hematuria_presence",),
    "pyuria_activity": ("pyuria_presence",),
    "urinary_pyuria_activity": ("pyuria_presence",),
    "sterile_pyuria_activity": ("sterile_pyuria_presence",),
    "bacteriuria_activity": ("bacteriuria_presence",),
    "bacteriuria_activity_in_D-RENAL-ABSCESS": ("bacteriuria_presence",),
    "proteinuria_activity": ("proteinuria_presence",),
    "glomerular_proteinuria_activity_sjogren": ("glomerular_proteinuria_presence",),
    "active_urinary_sediment_activity": ("active_urinary_sediment_presence",),
    "granular_casts_activity": ("granular_casts_presence",),
    "urine_white_blood_cell_casts_presence_in_D-PYELONEPHRITIS": ("urine_white_blood_cell_casts_presence",),
    "nephrotic_syndrome_activity": ("nephrotic_syndrome_presence",),
    "foamy_urine_activity": ("foamy_urine_presence",),
    "pericardial_effusion_activity": ("pericardial_effusion_presence",),
    "serositis_activity": ("serositis_presence",),
    "pericarditis_activity_in_D-FAMILIAL-MEDITERRANEAN-FEVER": ("pericarditis_presence",),
    "pericarditis_activity_in_D-TRAPS": ("pericarditis_presence",),
    "jugular_venous_distension_activity": ("jugular_venous_distension_presence",),
    "distant_heart_sounds_activity": ("distant_heart_sounds_presence",),
    "pulsus_paradoxus_activity": ("pulsus_paradoxus_presence",),
    "ascites_activity": ("ascites_presence",),
    "peripheral_edema_activity": ("peripheral_edema_presence",),
    "capillary_leak_third_spacing_activity": ("capillary_leak_third_spacing_presence",),
    "abdominal_distension_activity": ("abdominal_distension_presence",),
    "dehydration_activity": ("dehydration_presence",),
    "polydipsia_activity": ("polydipsia_presence",),
    "polyuria_activity": ("polyuria_presence",),
    "dehydration_volume_depletion_activity": ("volume_depletion_presence", "dehydration_presence"),
    "orthostatic_hypotension_activity": ("orthostatic_hypotension_presence",),
    "ecg_hyperkalemia_activity": ("hyperkalemia_ecg_change_presence",),
    "rhabdomyolysis_activity": ("rhabdomyolysis_presence",),
    "allograft_dysfunction_activity": ("allograft_dysfunction_presence",),
    "kidney_allograft_dysfunction_activity": ("kidney_allograft_dysfunction_presence",),
    "heart_allograft_dysfunction_activity": ("heart_allograft_dysfunction_presence",),
    "liver_allograft_dysfunction_activity": ("liver_allograft_dysfunction_presence",),
    "lung_allograft_dysfunction_activity": ("lung_allograft_dysfunction_presence",),
    "allograft_tenderness_activity": ("kidney_allograft_tenderness_presence",),
    "lower_extremity_edema_activity": ("lower_extremity_edema_presence",),
    "facial_edema_activity": ("facial_edema_presence",),
    "fluid_retention_weight_gain_activity_in_D-APL": ("fluid_retention_presence",),
    "flank_swelling_activity_in_D-PERINEPHRIC-ABSCESS": ("flank_swelling_presence",),
    "renal_inflammation_activity_in_D-RELAPSING-POLYCHONDRITIS": ("renal_inflammation_presence",),
    "renal_tubulointerstitial_nephritis_activity_in_D-CAEBV": ("tubulointerstitial_nephritis_presence",),
    "new_onset_diabetes_activity_in_D-IGG4-RELATED-DISEASE": ("new_onset_diabetes_presence",),
    "heat_intolerance_activity": ("heat_intolerance_presence",),
    "oliguria_activity": ("oliguria_presence",),
    "cardiac_murmur_activity": ("cardiac_murmur_presence",),
    "ie_new_heart_murmur_activity": ("new_or_changed_cardiac_murmur_presence",),
    "syncope_presyncope_activity": ("syncope_presence", "presyncope_presence"),
    "syncope_activity": ("syncope_presence",),
    "palpitations_activity": ("palpitations_presence",),
    "diaphoresis_sweats_activity": ("diaphoresis_presence",),
    "peritonitis_activity": ("peritoneal_irritation_presence",),
    "bile_peritonitis_activity": ("bile_peritonitis_presence",),
    "pelvic_pain_activity": ("pelvic_pain_presence",),
    "lower_abdominal_pain_activity": ("lower_abdominal_pain_presence",),
    "cervical_motion_tenderness_activity": ("cervical_motion_tenderness_presence",),
    "adnexal_tenderness_activity": ("adnexal_tenderness_presence",),
    "uterine_tenderness_activity": ("uterine_tenderness_presence",),
    "vaginal_discharge_activity": ("vaginal_discharge_presence",),
    "mucopurulent_cervical_discharge_activity": ("mucopurulent_cervical_discharge_presence",),
    "malodorous_vaginal_discharge_activity": ("malodorous_vaginal_discharge_presence",),
    "abnormal_lochia_activity": ("abnormal_lochia_presence",),
    "malodorous_lochia_activity": ("malodorous_lochia_presence",),
    "purulent_lochia_activity": ("purulent_lochia_presence",),
    "uterine_subinvolution_activity": ("uterine_subinvolution_presence",),
    "retained_products_of_conception_activity": ("retained_products_of_conception_presence",),
    "pallor_activity": ("pallor_presence",),
    "dark_urine_activity": ("dark_urine_presence",),
    "hemoglobinuria_dark_urine_activity": ("dark_urine_presence", "pigmenturia_presence"),
    "proximal_muscle_weakness_activity": ("proximal_muscle_weakness_presence",),
    "generalized_weakness_activity": ("generalized_weakness_presence",),
    "limb_weakness_paralysis_activity": ("limb_weakness_or_paralysis_presence",),
    "neck_flexor_weakness_activity": ("neck_flexor_weakness_presence",),
    "respiratory_muscle_weakness_activity": ("respiratory_muscle_weakness_presence",),
    "generalized_muscle_rigidity_activity": ("generalized_muscle_rigidity_presence",),
    "muscle_rigidity_activity": ("muscle_rigidity_presence",),
    "masseter_spasm_activity": ("masseter_spasm_presence",),
    "tremor_activity": ("tremor_presence",),
    "anterior_uveitis_activity": ("anterior_uveitis_presence",),
    "posterior_uveitis_activity": ("posterior_uveitis_presence",),
    "uveitis_activity": ("uveitis_presence",),
    "scleritis_episcleritis_activity": ("scleritis_episcleritis_presence",),
    "conjunctivitis_activity": ("conjunctivitis_presence",),
    "conjunctivitis_activity_in_D-URTICARIAL-VASCULITIS": ("conjunctivitis_presence",),
    "conjunctival_suffusion_activity": ("conjunctival_suffusion_presence",),
    "diplopia_activity": ("diplopia_presence",),
    "diplopia_activity_in_D-GCA": ("diplopia_presence",),
    "papilledema_activity": ("papilledema_presence",),
    "periorbital_edema_activity": ("periorbital_edema_presence",),
    "proptosis_activity": ("proptosis_presence",),
    "restricted_extraocular_movement_activity_in_D-ORBITAL-CELLULITIS": ("restricted_extraocular_movement_presence",),
    "eyelid_erythema_activity_in_D-ORBITAL-CELLULITIS": ("eyelid_erythema_presence",),
    "ocular_pain_activity_in_D-ORBITAL-CELLULITIS": ("ocular_pain_presence",),
    "purulent_periocular_discharge_activity_in_D-ORBITAL-CELLULITIS": ("purulent_periocular_discharge_presence",),
    "blurred_vision_activity": ("blurred_vision_presence",),
    "chemosis_activity_in_D-ORBITAL-CELLULITIS": ("chemosis_presence",),
    "choroidal_tubercles_activity": ("choroidal_tubercles_presence",),
    "conjunctival_hyperemia_activity_in_D-ORBITAL-CELLULITIS": ("conjunctival_hyperemia_presence",),
    "keratitis_activity": ("keratitis_presence",),
    "lacrimal_gland_enlargement_activity": ("lacrimal_gland_enlargement_presence",),
    "lacrimal_gland_enlargement_activity_in_D-SARCOIDOSIS": ("lacrimal_gland_enlargement_presence",),
    "ocular_myositis_activity_in_D-CAEBV": ("ocular_myositis_presence",),
    "orbital_apex_syndrome_activity_in_D-INVASIVE-ASPERGILLOSIS": ("orbital_apex_syndrome_presence",),
    "pain_with_eye_movement_activity_in_D-ORBITAL-CELLULITIS": ("pain_with_eye_movement_presence",),
    "photophobia_activity_in_D-INVASIVE-ASPERGILLOSIS": ("photophobia_presence",),
    "ptosis_activity_in_D-ORBITAL-CELLULITIS": ("ptosis_presence",),
    "ptosis_activity_in_D-INVASIVE-ASPERGILLOSIS": ("ptosis_presence",),
    "retro_orbital_pain_activity": ("retro_orbital_pain_presence",),
    "subconjunctival_hemorrhage_activity_in_D-TRICHINELLOSIS": ("subconjunctival_hemorrhage_presence",),
    "ie_roth_spot_activity": ("roth_spot_presence",),
    "vision_loss_activity_in_D-INVASIVE-ASPERGILLOSIS": ("vision_loss_presence",),
    "acrodermatitis_chronica_atrophicans_activity_in_D-LYME-DISEASE": ("acrodermatitis_chronica_atrophicans_presence",),
    "angioedema_activity": ("angioedema_presence",),
    "caebv_vascular_lesion_activity": ("cutaneous_vascular_lesion_presence",),
    "condyloma_lata_activity_in_D-SECONDARY-SYPHILIS": ("condyloma_lata_presence",),
    "cutaneous_vasculitis_purpura_activity_sjogren": ("cutaneous_vasculitis_purpura_presence",),
    "erythema_nodosum_activity": ("erythema_nodosum_presence",),
    "evanescent_rash_activity": ("evanescent_rash_presence",),
    "hydroa_vacciniforme_like_skin_lesion_activity": ("hydroa_vacciniforme_like_skin_lesion_presence",),
    "hyperpigmentation_activity": ("hyperpigmentation_presence",),
    "ie_oslers_node_activity": ("osler_node_presence",),
    "leukemia_cutis_activity_in_D-ALL": ("leukemia_cutis_presence",),
    "leukemia_cutis_activity_in_D-AML": ("leukemia_cutis_presence",),
    "migratory_erythematous_rash_activity_in_D-TRAPS": ("migratory_erythematous_rash_presence",),
    "morbilliform_rash_activity_DRESS": ("morbilliform_rash_presence",),
    "mucous_patch_activity_in_D-SECONDARY-SYPHILIS": ("mucous_patch_presence",),
    "palatal_petechiae_activity": ("palatal_petechiae_presence",),
    "papulopustular_skin_lesion_activity": ("papulopustular_skin_lesion_presence",),
    "pustular_or_petechial_acral_rash_activity_in_D-DISSEMINATED-GONOCOCCAL-INFECTION": ("acral_rash_presence",),
    "severe_mosquito_bite_allergy_activity": ("severe_mosquito_bite_allergy_presence",),
    "soft_tissue_bleeding_activity": ("soft_tissue_bleeding_presence",),
    "subcutaneous_nodule_activity_in_D-CAEBV": ("subcutaneous_nodule_presence",),
    "subcutaneous_nodule_activity_in_D-PAN": ("subcutaneous_nodule_presence",),
    "subcutaneous_nodule_activity_in_D-RHEUMATIC-FEVER": ("subcutaneous_nodule_presence",),
    "superficial_thrombophlebitis_activity_behcet": ("superficial_thrombophlebitis_presence",),
    "frontal_bossing_activity_in_D-CAPS": ("frontal_bossing_presence",),
    "nasal_polyposis_activity_egpa": ("nasal_polyposis_presence",),
    "parotid_gland_enlargement_activity": ("parotid_gland_enlargement_presence",),
    "parotid_gland_enlargement_activity_in_D-SARCOIDOSIS": ("parotid_gland_enlargement_presence",),
    "parotid_swelling_activity_sjogren": ("parotid_gland_enlargement_presence",),
    "parotitis_activity": ("parotitis_presence",),
    "submandibular_gland_enlargement_activity": ("submandibular_gland_enlargement_presence",),
    "submandibular_swelling_activity_sjogren": ("submandibular_gland_enlargement_presence",),
    "xerostomia_activity": ("oral_dryness_presence",),
    "regional_lymphadenopathy_activity": ("regional_lymphadenopathy_presence",),
    "perianal_infection_activity": ("perianal_soft_tissue_infection_presence",),
    "thyroid_riedel_fibrosis_activity": ("thyroid_fibrosis_presence",),
    "carotidynia_neck_pain_activity_in_D-TAKAYASU-ARTERITIS": ("carotidynia_presence",),
    "localized_pain_activity": ("localized_pain_presence",),
    "neck_pain_activity": ("neck_pain_presence",),
    "scalp_tenderness_activity": ("scalp_tenderness_presence",),
    "hiccup_activity": ("hiccup_presence",),
    "sleep_disturbance_activity": ("sleep_disturbance_presence",),
    "irritability_activity": ("irritability_presence",),
    "failure_to_thrive_activity": ("failure_to_thrive_presence",),
    "prolonged_fever_activity": ("prolonged_fever_presence",),
    "fever_without_localizing_symptom_activity_in_D-DRUG-FEVER": ("fever_without_localizing_symptom_presence",),
    "chills_or_discomfort_activity_in_D-DRUG-FEVER": ("systemic_discomfort_presence",),
    "fnhtr_fever_chills_cluster_activity_in_D-TRANSFUSION-REACTION-FNHTR": ("fever_history_presence", "chills_presence"),
    "shivering_activity": ("shivering_presence",),
    "transfusion_associated_malaise_discomfort_activity_in_D-TRANSFUSION-REACTION-FNHTR": ("malaise_presence",),
    "caps_continuous_inflammation_activity_in_D-CAPS": ("continuous_systemic_inflammation_course_presence",),
    "caps_recurrent_systemic_inflammatory_episode_activity_in_D-CAPS": ("recurrent_systemic_inflammatory_episode_presence",),
    "uv_relapsing_course_activity_in_D-URTICARIAL-VASCULITIS": ("relapsing_course_presence",),
    "bradycardia_activity_in_D-ACUTE-MYOCARDITIS": ("bradycardia_presence",),
    "bradycardia_activity_in_D-CHIKUNGUNYA": ("bradycardia_presence",),
    "bradycardia_activity_in_D-LYME-DISEASE": ("bradycardia_presence",),
    "bradycardia_activity_in_D-RHEUMATIC-FEVER": ("bradycardia_presence",),
    "relative_bradycardia_activity_in_D-DRUG-FEVER": ("relative_bradycardia_presence",),
    "faget_sign_relative_bradycardia_activity": ("faget_sign_presence",),
    "pericardial_friction_rub_activity": ("pericardial_friction_rub_presence",),
    "acute_systemic_reaction_after_heparin_activity": ("acute_systemic_reaction_after_heparin_presence",),
    "organ_dysfunction_activity_in_D-DRUG-FEVER": ("organ_dysfunction_presence",),
    "peripheral_skin_soft_tissue_infection_activity": ("skin_soft_tissue_infection_presence",),
    "cellulitis_or_wound_infection_activity": ("skin_soft_tissue_infection_presence", "wound_infection_presence"),
    "cellulitis_involved_skin_area_activity_in_D-CELLULITIS": ("cellulitis_presence",),
    "cellulitis_erythema_extent_in_D-CELLULITIS": ("cellulitis_presence",),
    "cellulitis_warmth_activity_in_D-CELLULITIS": ("cutaneous_warmth_presence",),
    "cellulitis_edema_activity_in_D-CELLULITIS": ("localized_skin_edema_presence",),
    "cellulitis_tenderness_activity_in_D-CELLULITIS": ("localized_skin_pain_presence",),
    "cellulitis_lymphangitis_activity_in_D-CELLULITIS": ("lymphangitis_presence",),
    "cellulitis_purulent_drainage_activity_in_D-CELLULITIS": ("purulent_skin_drainage_presence",),
    "cellulitis_bullae_or_pustular_exudate_activity_in_D-CELLULITIS": ("bullous_skin_lesion_presence",),
    "cellulitis_purpura_activity_in_D-CELLULITIS": ("petechiae_purpura_presence",),
    "cellulitis_subcutaneous_edema_imaging_activity_in_D-CELLULITIS": ("subcutaneous_edema_imaging_presence",),
    "diabetic_foot_wound_infection_activity_in_D-DIABETIC-FOOT-INFECTION": ("diabetic_foot_wound_infection_presence",),
    "diabetic_foot_edema_activity_in_D-DIABETIC-FOOT-INFECTION": ("localized_skin_edema_presence",),
    "diabetic_foot_warmth_activity_in_D-DIABETIC-FOOT-INFECTION": ("cutaneous_warmth_presence",),
    "diabetic_foot_pain_tenderness_activity_in_D-DIABETIC-FOOT-INFECTION": ("localized_skin_pain_presence",),
    "diabetic_foot_blister_bullae_activity_in_D-DIABETIC-FOOT-INFECTION": ("bullous_skin_lesion_presence",),
    "soft_tissue_gas_imaging_activity_in_D-DIABETIC-FOOT-INFECTION": ("soft_tissue_gas_imaging_presence",),
    "wound_dehiscence_activity_in_D-PROSTHETIC-JOINT-INFECTION": ("wound_dehiscence_presence",),
    "skin_ulcer_or_necrosis_activity": ("skin_breakdown_presence", "skin_ulcer_presence", "skin_necrosis_presence"),
    "skin_necrosis_activity": ("skin_necrosis_presence",),
    "skin_necrosis_activity_in_D-CHIKUNGUNYA": ("skin_necrosis_presence",),
    "localized_skin_or_mucosal_necrosis_activity": ("tissue_necrosis_presence", "mucosal_necrosis_presence"),
    "erysipelas_bullous_lesion_activity_in_D-ERYSIPELAS": ("bullous_skin_lesion_presence",),
    "erysipelas_edema_activity_in_D-ERYSIPELAS": ("localized_skin_edema_presence",),
    "erysipelas_erythema_extent_in_D-ERYSIPELAS": ("erysipelas_presence",),
    "erysipelas_exudation_erosion_activity_in_D-ERYSIPELAS": ("skin_erosion_or_exudation_presence",),
    "erysipelas_hemorrhagic_bullae_purpura_activity_in_D-ERYSIPELAS": ("hemorrhagic_bullous_skin_lesion_presence",),
    "erysipelas_like_erythema_activity_in_D-FAMILIAL-MEDITERRANEAN-FEVER": ("erysipelas_like_erythema_presence",),
    "erysipelas_lymphangitis_activity_in_D-ERYSIPELAS": ("lymphangitis_presence",),
    "erysipelas_sharply_demarcated_raised_border_activity_in_D-ERYSIPELAS": ("sharply_demarcated_erythema_presence",),
    "erysipelas_superficial_induration_activity_in_D-ERYSIPELAS": ("skin_induration_presence",),
    "erysipelas_superficial_skin_necrosis_activity_in_D-ERYSIPELAS": ("skin_necrosis_presence",),
    "erysipelas_tenderness_pain_activity_in_D-ERYSIPELAS": ("localized_skin_pain_presence",),
    "erysipelas_warmth_activity_in_D-ERYSIPELAS": ("cutaneous_warmth_presence",),
    "deep_venous_thrombosis_activity": ("deep_venous_thrombosis_presence",),
    "deep_venous_thrombosis_activity_behcet": ("deep_venous_thrombosis_presence",),
    "limb_ischemia_activity": ("limb_ischemia_presence",),
    "limb_ischemia_or_necrotic_ulcer_activity": ("limb_ischemia_presence", "skin_necrosis_presence"),
    "digital_gangrene_activity": ("digital_gangrene_presence",),
    "digital_ulcer_activity": ("digital_ulcer_presence",),
    "penile_ischemia_activity_in_D-PAN": ("penile_ischemia_presence",),
    "raynaud_phenomenon_activity": ("raynaud_phenomenon_presence",),
    "livedo_reticularis_activity": ("livedo_reticularis_presence",),
    "ie_janeway_lesion_activity": ("janeway_lesion_presence",),
    "splinter_hemorrhage_activity": ("splinter_hemorrhage_presence",),
    "jaw_claudication_activity": ("jaw_claudication_presence",),
    "tongue_claudication_activity": ("tongue_claudication_presence",),
    "temporal_artery_tenderness_activity_in_D-GCA": ("temporal_artery_tenderness_presence",),
    "upper_extremity_claudication_activity_in_D-GCA": ("upper_extremity_claudication_presence",),
    "upper_extremity_claudication_activity_in_D-TAKAYASU-ARTERITIS": ("upper_extremity_claudication_presence",),
    "lower_extremity_claudication_activity_in_D-GCA": ("lower_extremity_claudication_presence",),
    "lower_extremity_claudication_activity_in_D-TAKAYASU-ARTERITIS": ("lower_extremity_claudication_presence",),
    "visual_disturbance_activity_in_D-GCA": ("visual_disturbance_presence",),
    "visual_disturbance_activity_in_D-TAKAYASU-ARTERITIS": ("visual_disturbance_presence",),
    "acute_vision_loss_activity_in_D-GCA": ("acute_vision_loss_presence",),
    "transient_monocular_visual_loss_activity_in_D-GCA": ("transient_monocular_visual_loss_presence",),
    "transient_vision_loss_activity": ("visual_disturbance_presence", "transient_vision_loss_presence"),
    "ocular_ischemia_activity_in_D-GCA": ("ocular_ischemia_presence",),
    "retinal_vasculitis_activity": ("retinal_vasculitis_presence",),
    "retinal_hemorrhage_activity": ("retinal_hemorrhage_presence",),
    "mucosal_barrier_injury_activity": ("mucosal_barrier_injury_presence",),
    "mucosal_erosion_activity": ("mucosal_erosion_presence",),
    "genital_mucosal_erosion_activity_in_D-SJS-TEN": ("genital_mucosal_erosion_presence",),
    "oral_mucosal_ulcer_activity": ("oral_mucosal_ulcer_presence",),
    "oral_ulcer_activity": ("oral_mucosal_ulcer_presence",),
    "oral_aphthous_ulcer_activity": ("aphthous_oral_ulcer_presence",),
    "genital_ulcer_activity": ("genital_ulcer_presence",),
    "genital_ulcer_scarring_activity": ("genital_ulcer_scarring_presence",),
    "genital_ulcer_vesicle_activity": ("genital_vesicle_presence",),
    "mpp_mucositis_activity": ("oral_mucositis_presence",),
    "oral_mucosal_changes_activity": ("oral_mucosal_lesion_presence",),
    "oral_gingival_necrosis_activity": ("oral_gingival_necrosis_presence",),
    "oral_hemorrhagic_bullae_activity": ("oral_hemorrhagic_bullae_presence",),
    "mucosal_hyperemia_extent_in_D-TOXIC-SHOCK-SYNDROME": ("mucosal_hyperemia_presence",),
    "strawberry_tongue_activity_in_D-TOXIC-SHOCK-SYNDROME": ("strawberry_tongue_presence",),
    "koplik_spots_activity": ("koplik_spots_presence",),
    "coated_tongue_activity_in_D-TYPHOID-FEVER": ("coated_tongue_presence",),
    "gingival_infiltration_activity_in_D-AML": ("gingival_infiltration_presence",),
    "oral_candidiasis_activity_sjogren": ("oral_candidiasis_presence",),
    "oral_dryness_severity_sjogren": ("oral_dryness_presence",),
    "oral_maxillofacial_cellulitis_activity": ("oral_maxillofacial_cellulitis_presence",),
    "periodontal_or_oral_mucosal_source_activity": ("periodontal_or_oral_mucosal_source_presence",),
    "poor_oral_hygiene_activity": ("poor_oral_hygiene_presence",),
    "pharyngitis_activity_in_D-DISSEMINATED-GONOCOCCAL-INFECTION": ("pharyngitis_presence",),
    "pharyngitis_or_upper_respiratory_source_activity": ("pharyngitis_presence", "upper_respiratory_source_presence"),
    "recent_streptococcal_pharyngitis_activity": ("recent_streptococcal_pharyngitis_presence",),
    "pharyngotonsillar_exudate_activity": ("pharyngotonsillar_exudate_presence",),
    "dysphagia_activity": ("dysphagia_presence",),
    "esophageal_dysmotility_or_dysphagia_activity": ("dysphagia_presence", "esophageal_dysmotility_presence"),
    "poor_oral_intake_activity_in_D-MEASLES": ("poor_oral_intake_presence",),
    "back_pain_activity": ("back_pain_presence",),
    "back_pain_activity_in_D-BARTONELLA-ENDOCARDITIS": ("back_pain_presence",),
    "back_pain_activity_in_D-Q-FEVER": ("back_pain_presence",),
    "low_back_pain_activity_in_D-BRUCELLOSIS": ("low_back_pain_presence",),
    "retroperitoneal_back_pain_activity_in_D-PERINEPHRIC-ABSCESS": ("retroperitoneal_back_pain_presence",),
    "retroperitoneal_back_pain_activity_in_D-RENAL-ABSCESS": ("retroperitoneal_back_pain_presence",),
    "bone_pain_limb_pain_activity": ("bone_pain_presence", "limb_pain_presence"),
    "focal_bone_pain_activity": ("focal_bone_pain_presence",),
    "limb_swelling_pain_activity": ("limb_pain_presence", "limb_swelling_presence"),
    "prosthetic_joint_pain_activity_in_D-PROSTHETIC-JOINT-INFECTION": ("prosthetic_joint_pain_presence",),
    "synovial_fluid_purulence_activity_in_D-PROSTHETIC-JOINT-INFECTION": ("synovial_fluid_purulence_presence",),
    "tenosynovitis_activity_in_D-DISSEMINATED-GONOCOCCAL-INFECTION": ("tenosynovitis_presence",),
    "migratory_polyarthralgia_activity_in_D-DISSEMINATED-GONOCOCCAL-INFECTION": ("migratory_polyarthralgia_presence",),
    "muscle_tenderness_swelling_activity_in_D-TRICHINELLOSIS": ("muscle_tenderness_presence", "muscle_swelling_presence"),
    "scrotal_swelling_activity": ("scrotal_swelling_presence",),
    "testicular_pain_activity": ("testicular_pain_presence",),
    "testicular_enlargement_activity": ("testicular_enlargement_presence",),
    "epididymal_enlargement_activity": ("epididymal_enlargement_presence",),
    "epididymal_tenderness_activity": ("epididymal_tenderness_presence",),
    "epididymitis_activity_behcet": ("epididymitis_presence",),
    "scrotal_erythema_activity": ("scrotal_erythema_presence",),
    "scrotal_induration_activity": ("scrotal_induration_presence",),
    "perineal_pain_activity": ("perineal_pain_presence",),
    "prostate_enlargement_on_exam_activity": ("prostate_enlargement_on_exam_presence",),
    "prostate_tenderness_on_dre_activity": ("prostate_tenderness_on_dre_presence",),
    "urethral_discharge_activity": ("urethral_discharge_presence",),
    "urethritis_or_cervicitis_activity_in_D-DISSEMINATED-GONOCOCCAL-INFECTION": ("urogenital_mucosal_inflammation_presence", "urethritis_presence", "cervicitis_presence"),
    "dyspareunia_activity": ("dyspareunia_presence",),
    "dermatomyositis_rash_activity": ("dermatomyositis_rash_presence",),
    "gottron_papules_or_sign_activity": ("gottron_papules_or_sign_presence",),
    "heliotrope_rash_activity": ("heliotrope_rash_presence",),
    "mechanic_hands_activity": ("mechanic_hands_presence",),
    "v_shawl_sign_rash_activity": ("shawl_sign_rash_presence",),
    "sclerodactyly_activity": ("sclerodactyly_presence",),
    "puffy_hands_activity": ("puffy_hands_presence",),
    "telangiectasia_activity": ("telangiectasia_presence",),
    "malar_rash_activity": ("malar_rash_presence",),
    "discoid_rash_activity": ("discoid_rash_presence",),
    "mctd_lupus_like_rash_activity": ("lupus_like_rash_presence",),
    "alopecia_activity": ("alopecia_presence",),
    "patchy_alopecia_activity_in_D-SECONDARY-SYPHILIS": ("patchy_alopecia_presence",),
    "annular_erythema_activity_sjogren": ("annular_erythema_presence",),
    "ocular_dryness_severity_sjogren": ("ocular_dryness_presence",),
    "xerophthalmia_activity": ("xerophthalmia_presence",),
    "auricular_chondritis_activity": ("auricular_chondritis_presence",),
    "nasal_chondritis_activity": ("nasal_chondritis_presence",),
    "chest_wall_costochondritis_activity": ("chest_wall_costochondritis_presence",),
    "polymyalgia_rheumatica_activity_in_D-GCA": ("polymyalgia_rheumatica_presence",),
    "hip_girdle_pain_stiffness_activity": ("hip_girdle_pain_stiffness_presence",),
    "shoulder_girdle_pain_stiffness_activity": ("shoulder_girdle_pain_stiffness_presence",),
    "peripheral_neuropathy_activity": ("peripheral_neuropathy_presence",),
    "mononeuritis_multiplex_activity": ("mononeuritis_multiplex_presence",),
    "mononeuritis_multiplex_activity_egpa": ("mononeuritis_multiplex_presence",),
    "mononeuritis_multiplex_activity_sjogren": ("mononeuritis_multiplex_presence",),
    "sensory_ataxic_neuropathy_activity_sjogren": ("sensory_ataxic_neuropathy_presence", "ataxia_presence"),
    "burning_pain_dysautonomia_activity_sjogren": ("dysautonomic_neuropathic_pain_presence",),
    "foot_drop_activity": ("foot_drop_presence",),
    "cranial_neuropathy_activity_in_D-IGG4-RELATED-DISEASE": ("cranial_neuropathy_presence",),
    "myelitis_demyelination_activity_sjogren": ("myelitis_presence",),
    "myelitis_radiculitis_activity_in_D-VZV-ENCEPHALITIS": ("myelitis_or_radiculitis_presence",),
    "myelitis_radiculitis_activity_in_D-WEST-NILE-NEUROINVASIVE-DISEASE": ("myelitis_or_radiculitis_presence",),
    "radicular_pain_activity_in_D-LYME-DISEASE": ("radicular_pain_presence",),
    "ataxia_activity_in_D-RICKETTSIOSIS-SCRUB-TYPHUS": ("ataxia_presence",),
    "stroke_like_deficit_activity": ("stroke_like_deficit_presence",),
    "neurobehavioral_change_activity": ("neurobehavioral_change_presence",),
    "neuropsychiatric_sle_manifestation_activity": ("neuropsychiatric_manifestation_presence",),
    "dizziness_activity": ("dizziness_presence",),
    "vertigo_activity": ("vertigo_presence",),
    "vestibular_dysfunction_activity": ("vestibular_dysfunction_presence",),
    "anisocoria_activity": ("anisocoria_presence",),
    "pupillary_light_response_abnormality_activity": ("pupillary_light_response_abnormality_presence",),
    "cushing_reflex_activity": ("cushing_reflex_presence",),
    "jolt_accentuation_activity": ("jolt_accentuation_presence",),
    "meningismus_activity_in_D-RICKETTSIOSIS-SCRUB-TYPHUS": ("meningismus_presence",),
    "aseptic_meningitis_activity_behcet": ("aseptic_meningitis_presence",),
    "aseptic_meningitis_activity_in_D-SARCOIDOSIS": ("aseptic_meningitis_presence",),
    "urinary_incontinence_activity": ("urinary_incontinence_presence",),
    "nonproductive_cough_activity_in_D-PJP-PNEUMONIA": ("nonproductive_cough_presence",),
    "rust_colored_sputum_activity_in_D-PNEUMOCOCCAL-PNEUMONIA": ("rust_colored_sputum_presence",),
    "hemoptysis_activity_in_D-INVASIVE-ASPERGILLOSIS": ("hemoptysis_presence",),
    "pleuritic_chest_pain_activity_in_D-INVASIVE-ASPERGILLOSIS": ("pleuritic_chest_pain_presence",),
    "pulmonary_crackles_activity": ("crackles_presence",),
    "exertional_desaturation_activity_in_D-PJP-PNEUMONIA": ("exertional_desaturation_presence",),
    "wheeze_activity_mpp": ("wheezing_presence",),
    "wheezing_activity": ("wheezing_presence",),
    "wheezing_activity_in_D-INVASIVE-ASPERGILLOSIS": ("wheezing_presence",),
    "stridor_activity": ("stridor_presence",),
    "eosinophilic_asthma_activity_egpa": ("eosinophilic_asthma_presence",),
    "pulmonary_involvement_activity_in_D-URTICARIAL-VASCULITIS": ("pulmonary_involvement_presence",),
    "clubbing_activity": ("digital_clubbing_presence",),
    "coryza_rhinitis_activity_in_D-MEASLES": ("coryza_rhinitis_presence",),
    "anosmia_activity": ("anosmia_presence",),
    "ageusia_activity": ("ageusia_presence",),
    "abdominal_distension_activity_in_D-CLOSTRIDIOIDES-DIFFICILE-SEVERE": ("abdominal_distension_presence",),
    "diffuse_abdominal_tenderness_activity": ("diffuse_abdominal_tenderness_presence",),
    "constipation_activity": ("constipation_presence",),
    "ileus_activity": ("ileus_presence",),
    "intestinal_obstruction_activity": ("intestinal_obstruction_presence",),
    "nausea_vomiting_activity_in_D-PYELONEPHRITIS": ("nausea_presence", "vomiting_presence"),
    "right_upper_quadrant_pain_activity_in_D-PYOGENIC-LIVER-ABSCESS": ("right_upper_quadrant_pain_presence",),
    "hepatic_tenderness_activity": ("hepatic_tenderness_presence",),
    "acholic_stool_activity": ("acholic_stool_presence",),
    "early_satiety_activity": ("early_satiety_presence",),
    "intestinal_ulcer_activity_in_D-CAEBV": ("intestinal_ulcer_presence",),
    "pelvic_mass_activity": ("pelvic_mass_presence",),
    "pelvic_tenderness_activity": ("pelvic_tenderness_presence",),
    "vaginal_bleeding_activity": ("vaginal_bleeding_presence",),
    "abnormal_pregnancy_tissue_passage_history_activity": ("pregnancy_tissue_passage_history_presence",),
    "rash_activity": ("rash_presence",),
    "jaundice_activity": ("jaundice_presence",),
    "hepatomegaly_activity": ("hepatomegaly_presence",),
    "splenomegaly_activity": ("splenomegaly_presence",),
    "lymphadenopathy_activity": ("pathologic_lymphadenopathy_presence",),
    "bleeding_activity": ("bleeding_presence",),
    "clinical_bleeding_activity": ("bleeding_presence",),
    "mucosal_bleeding_activity": ("mucosal_bleeding_presence",),
    "petechiae_purpura_activity": ("petechiae_purpura_presence",),
    "petechial_purpuric_rash_activity": ("petechiae_purpura_presence",),
    "palpable_purpura_activity": ("palpable_purpura_presence",),
    "purpura_fulminans_activity": ("purpura_fulminans_presence",),
}

EXACT_AXIS_ALIASES = {
    "abdominal_pain_presence": ("abdominal_pain_activity",),
    "abdominal_tenderness_presence": ("abdominal_pain_activity",),
    "activated_partial_thromboplastin_time": ("partial_thromboplastin_time",),
    "alanine_aminotransferase": ("serum_alt",),
    "alanine_aminotransferase_u_L": ("serum_alt",),
    "alkaline_phosphatase": ("serum_alkaline_phosphatase",),
    "alkaline_phosphatase_normal_presence": ("serum_alkaline_phosphatase_normal_presence",),
    "anti_hav_antibody_positive": ("hav_igm_positivity",),
    "anti_hev_igm_positive": ("hev_igm_positivity",),
    "arterial_pH": ("arterial_ph",),
    "adenovirus_immunohistochemistry_positive": ("adenovirus_tissue_immunohistochemistry_positive",),
    "altered_mental_status_presence": ("mental_status_abnormality_presence", "mental_status_abnormality_activity"),
    "aspartate_aminotransferase": ("serum_ast",),
    "aspartate_aminotransferase_u_L": ("serum_ast",),
    "aortic_flap_or_membrane_presence": ("aortic_dissection_presence", "aortic_intimal_flap_presence"),
    "aorto_right_renal_artery_pressure_gradient_maximum": ("renal_artery_dynamic_stenosis_pressure_gradient_mmHg",),
    "asymmetric_renal_ct_enhancement_presence": ("renal_artery_malperfusion_presence",),
    "bilateral_lower_leg_intermuscular_venous_thrombosis_presence": ("deep_venous_thrombosis_activity", "venous_thrombosis_activity"),
    "bilateral_pulmonary_infiltrate_extent": ("bilateral_pulmonary_opacity_extent",),
    "bilious_vomiting_presence": ("vomiting_activity",),
    "blood_glucose": ("serum_glucose",),
    "blood_gas_oxygen_saturation": ("oxygen_saturation",),
    "blood_urea": ("blood_urea_nitrogen",),
    "bee_pollen_ingestion_presence": ("allergen_exposure_temporal_association_probability",),
    "body_temperature_celsius": ("body_temperature",),
    "chronic_heavy_alcohol_use_presence": ("alcohol_pancreatic_toxicity_context_probability", "chronic_heavy_beer_intake_presence"),
    "coagulation_inr": ("prothrombin_time_inr",),
    "coma_presence": ("coma_activity",),
    "complete_atrioventricular_block_presence": ("atrioventricular_block_degree",),
    "confusion_presence": ("mental_status_abnormality_presence", "mental_status_abnormality_activity"),
    "coronary_occlusion_presence": ("culprit_coronary_obstruction_presence",),
    "coronary_thrombus_presence": ("coronary_occlusion_presence", "culprit_coronary_obstruction_presence"),
    "decreased_oral_intake_presence": ("water_intake_impairment_presence",),
    "deep_venous_thrombosis_presence": ("deep_venous_thrombosis_activity", "venous_thrombosis_activity"),
    "descending_aortic_dissection_flap_presence": ("aortic_dissection_presence", "aortic_intimal_flap_presence"),
    "direct_bilirubin": ("serum_bilirubin_direct",),
    "direct_bilirubin_elevated_presence": ("direct_hyperbilirubinemia_presence",),
    "direct_antiglobulin_test_positive": ("direct_antiglobulin_test_activity",),
    "ecg_anterior_wall_acute_ischemic_pattern_presence": ("st_segment_elevation_presence",),
    "facial_edema_presence": ("angioedema_presence", "facial_lip_tongue_angioedema_presence"),
    "facial_weakness_severity": ("facial_droop_severity",),
    "false_aortic_lumen_presence": ("aortic_false_lumen_patency",),
    "false_lumen_prolapse_into_right_renal_artery_presence": ("renal_artery_malperfusion_presence",),
    "gamma_glutamyl_transferase": ("serum_gamma_glutamyl_transferase",),
    "gamma_glutamyltransferase": ("serum_gamma_glutamyl_transferase",),
    "fever_presence": ("fever_history_presence",),
    "glasgow_coma_scale": ("glasgow_coma_scale_score",),
    "ground_glass_opacity_extent": ("diffuse_ground_glass_opacity_extent",),
    "generalized_urticaria_presence": ("urticaria_presence",),
    "heart_rate_bpm": ("heart_rate",),
    "hemoglobin_g_dL": ("hemoglobin",),
    "hepatitis_a_igm_positive": ("hav_igm_positivity",),
    "hepatitis_a_igm_antibody_positive": ("hav_igm_positivity",),
    "hepatitis_e_igm_positive": ("hev_igm_positivity",),
    "hepatitis_e_antibody_positive": ("hev_igm_positivity",),
    "hepatic_encephalopathy_presence": ("mental_status_abnormality_activity",),
    "hiv1_rna_copies_per_mL": ("hiv_plasma_rna_viral_load",),
    "hiv_positive_sexual_partner_presence": ("known_hiv_positive_source_partner_presence",),
    "human_adenovirus_hexon_gene_typing_result": ("adenovirus_hexon_typing_positive_presence",),
    "hypoxemia_presence": ("supplemental_oxygen_requirement_presence",),
    "inability_to_follow_commands_presence": ("mental_status_abnormality_presence", "mental_status_abnormality_severity"),
    "incomprehensible_speech_presence": ("mental_status_abnormality_presence", "mental_status_abnormality_severity"),
    "inferior_vena_cava_collapse_presence": ("dehydration_presence",),
    "inferior_wall_akinesia_presence": ("regional_wall_motion_abnormality_presence",),
    "international_normalized_ratio": ("prothrombin_time_inr",),
    "jaundice_presence": ("jaundice_activity",),
    "jaundice_or_icterus_presence": ("jaundice_activity",),
    "kussmaul_respiration_presence": ("kussmaul_breathing_activity",),
    "lactate_dehydrogenase": ("serum_ldh",),
    "limb_weakness_presence": ("limb_weakness_or_paralysis_presence",),
    "left_anterior_descending_territory_wall_motion_abnormality_presence": ("regional_wall_motion_abnormality_presence",),
    "left_main_coronary_artery_occlusion_presence": ("coronary_occlusion_presence", "culprit_coronary_obstruction_presence"),
    "low_solute_intake_context_presence": ("beer_potomania_context_presence",),
    "leukocyte_count": ("white_blood_cell_count",),
    "leukocyte_count_per_uL": ("white_blood_cell_count",),
    "main_and_bilateral_branch_pulmonary_arterial_filling_defect_presence": (
        "ctpa_pulmonary_arterial_filling_defect_activity",
        "pulmonary_embolic_burden_activity",
        "central_pulmonary_embolus_activity",
    ),
    "mental_status_abnormality_presence": ("mental_status_abnormality_activity",),
    "motor_neuropathy_pattern_presence": ("motor_neuropathy_presence",),
    "nausea_presence": ("nausea_vomiting_activity",),
    "nih_stroke_scale": ("nihss_score",),
    "oxygen_desaturation_presence": ("supplemental_oxygen_requirement_presence",),
    "oxygen_flow_rate_l_per_min": ("oxygen_requirement_level",),
    "palpitations_presence": ("palpitations_activity",),
    "partial_thromboplastin_time_seconds": ("partial_thromboplastin_time",),
    "perinephric_stranding_progression_presence": ("perinephric_stranding_presence",),
    "point_of_care_glucose": ("serum_glucose",),
    "prothrombin_time": ("prothrombin_time_seconds",),
    "pulmonary_infiltrate_presence": ("pulmonary_opacity_presence", "bilateral_pulmonary_opacity_presence"),
    "pulmonary_arterial_filling_defect_presence": ("ctpa_pulmonary_arterial_filling_defect_activity",),
    "pulmonary_hypertension_presence": ("pulmonary_hypertension_activity",),
    "renal_allograft_tenderness_presence": ("allograft_tenderness_activity",),
    "renal_allograft_tenderness_severity": ("allograft_tenderness_activity",),
    "renal_allograft_tenderness_worsening_presence": ("allograft_tenderness_activity",),
    "serum_human_adenovirus_pcr_viral_load": ("adenovirus_viral_load",),
    "right_renal_artery_involvement_by_aortic_flap_presence": ("renal_artery_malperfusion_presence",),
    "right_renal_artery_ostial_stenosis_presence": ("renal_artery_malperfusion_presence",),
    "right_kidney_hypoperfusion_presence": ("renal_artery_malperfusion_presence",),
    "right_ankle_brachial_index": ("ankle_brachial_index",),
    "right_calf_pain_presence": ("limb_pain_presence", "lower_limb_pain_presence"),
    "right_dorsalis_pedis_pulse_weak_presence": ("pulse_deficit_presence",),
    "right_foot_cold_skin_presence": ("limb_skin_coolness_presence",),
    "right_foot_mottled_skin_presence": ("limb_ischemia_presence", "peripheral_ischemia_presence"),
    "right_lower_limb_paresthesia_presence": ("limb_paresthesia_presence", "limb_sensory_abnormality_presence"),
    "right_popliteal_artery_occlusion_on_ct_angiography_presence": (
        "peripheral_arterial_occlusion_presence",
        "lower_extremity_arterial_occlusion_presence",
        "cta_arterial_occlusion_presence",
    ),
    "right_popliteal_artery_total_occlusion_on_arteriography_presence": (
        "peripheral_arterial_occlusion_presence",
        "lower_extremity_arterial_occlusion_presence",
        "arterial_occlusion_complete_presence",
    ),
    "right_popliteal_pulse_weak_presence": ("pulse_deficit_presence",),
    "seizure_presence": ("seizure_activity",),
    "serum_creatinine_mg_dL": ("serum_creatinine",),
    "serum_ferritin_ng_mL": ("serum_ferritin",),
    "shock_presence": ("shock_activity",),
    "scleral_icterus_presence": ("jaundice_activity",),
    "somnolence_presence": ("mental_status_abnormality_activity",),
    "superior_mesenteric_vein_thrombotic_occlusion_presence": ("mesenteric_vascular_occlusion_presence", "superior_mesenteric_vein_thrombosis_presence"),
    "acute_small_bowel_ischemia_ct_presence": ("mesenteric_bowel_ischemia_presence", "bowel_ischemia_imaging_presence"),
    "long_segment_venous_thrombus_presence": ("superior_mesenteric_vein_thrombosis_presence",),
    "portal_vein_thrombus_extension_presence": ("portal_vein_thrombosis_presence",),
    "prior_liver_disease_history_presence": ("cirrhosis_context_presence",),
    "troponin_i": ("serum_troponin",),
    "total_bilirubin": ("serum_bilirubin_total",),
    "total_bilirubin_mg_dL": ("serum_bilirubin_total",),
    "total_leukocyte_count": ("white_blood_cell_count",),
    "supplemental_oxygen_flow_rate": ("oxygen_requirement_level",),
    "syncope_presence": ("syncope_activity", "syncope_presyncope_activity"),
    "recent_alcohol_escalation_or_binge_activity": ("alcohol_pancreatic_toxicity_context_probability",),
    "speech_abnormality_presence": ("mental_status_abnormality_presence", "mental_status_abnormality_severity"),
    "unable_to_provide_history_presence": ("mental_status_abnormality_presence", "mental_status_abnormality_severity"),
    "unprotected_anal_intercourse_presence": ("recent_unprotected_sexual_exposure_probability",),
    "urine_rbc_presence": ("hematuria_activity",),
    "urine_wbc_presence": ("pyuria_activity",),
    "venous_access_difficulty_presence": ("dehydration_presence", "dehydration_severity"),
    "vomiting_presence": ("vomiting_activity",),
    "warm_dry_skin_presence": ("dehydration_presence",),
    "weak_peripheral_pulse_presence": ("dehydration_presence", "dehydration_severity"),
    "withdrawal_from_pain_presence": ("mental_status_abnormality_presence", "mental_status_abnormality_severity"),
    "white_blood_cell_count_per_uL": ("white_blood_cell_count",),
}

SUPPRESSION_ONLY_AXIS_ALIASES = {
    "leukocytosis_presence": ("white_blood_cell_count",),
    "tachycardia_presence": ("heart_rate",),
    "tachypnea_presence": ("respiratory_rate",),
}


EVENT_HAZARD_AXIS_PROXIES = {
    "acute_respiratory_failure_hazard": {
        "respiratory_distress_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.03],
            "peak_value_range": [0.2, 1.0],
            "category": "physical_finding",
        },
        "oxygen_desaturation_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.03],
            "peak_value_range": [0.2, 1.0],
            "category": "physiology",
        },
        "increased_work_of_breathing_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.03],
            "peak_value_range": [0.2, 1.0],
            "category": "physical_finding",
        },
        "invasive_mechanical_ventilation_requirement_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.02],
            "peak_value_range": [0.2, 1.0],
            "category": "support_requirement",
        },
        "mechanical_ventilation_difficulty_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.01],
            "peak_value_range": [0.1, 1.0],
            "category": "support_requirement",
        },
        "pulmonary_compliance_reduction_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.02],
            "peak_value_range": [0.2, 1.0],
            "category": "physiology",
        },
        "fio2_requirement_fraction": {
            "unit": "fraction_0_1",
            "baseline_range": [0.21, 0.3],
            "peak_value_range": [0.4, 1.0],
            "category": "support_requirement",
        },
        "arterial_pao2": {
            "unit": "mmHg",
            "baseline_range": [80.0, 105.0],
            "peak_value_range": [40.0, 90.0],
            "category": "blood_gas",
        },
        "pao2_fio2_ratio": {
            "unit": "mmHg",
            "baseline_range": [400.0, 500.0],
            "peak_value_range": [50.0, 300.0],
            "category": "blood_gas",
        },
        "arterial_pco2": {
            "unit": "mmHg",
            "baseline_range": [35.0, 45.0],
            "peak_value_range": [45.0, 120.0],
            "category": "blood_gas",
        },
        "peep_cm_h2o": {
            "unit": "cmH2O",
            "baseline_range": [0.0, 5.0],
            "peak_value_range": [5.0, 20.0],
            "category": "ventilator_setting",
        },
        "driving_pressure_cm_h2o": {
            "unit": "cmH2O",
            "baseline_range": [0.0, 8.0],
            "peak_value_range": [8.0, 30.0],
            "category": "ventilator_setting",
        },
        "tidal_volume_ml": {
            "unit": "mL",
            "baseline_range": [350.0, 600.0],
            "peak_value_range": [100.0, 400.0],
            "category": "ventilator_setting",
        },
        "pulmonary_edema_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.03],
            "peak_value_range": [0.1, 0.8],
            "category": "imaging_finding",
        },
        "atelectasis_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.05],
            "peak_value_range": [0.1, 0.8],
            "category": "imaging_finding",
        },
    },
    "acute_kidney_injury_hazard": {
        "acute_kidney_injury_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.02],
            "peak_value_range": [0.2, 1.0],
            "category": "diagnostic_finding",
        },
        "oliguria_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.03],
            "peak_value_range": [0.2, 1.0],
            "category": "renal_finding",
        },
        "urine_output": {
            "unit": "mL/kg/hr",
            "baseline_range": [0.5, 1.5],
            "peak_value_range": [0.0, 0.5],
            "category": "renal_measurement",
        },
        "serum_potassium": {
            "unit": "mmol/L",
            "baseline_range": [3.5, 5.0],
            "peak_value_range": [4.5, 7.0],
            "category": "lab_value",
        },
    },
    "circulatory_collapse_shock_hazard": {
        "shock_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.01],
            "peak_value_range": [0.2, 1.0],
            "category": "physical_finding",
        },
        "hypotension_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.03],
            "peak_value_range": [0.2, 1.0],
            "category": "physical_finding",
        },
        "systolic_blood_pressure": {
            "unit": "mmHg",
            "baseline_range": [100.0, 140.0],
            "peak_value_range": [40.0, 95.0],
            "category": "vital_sign",
        },
        "mean_arterial_pressure": {
            "unit": "mmHg",
            "baseline_range": [70.0, 100.0],
            "peak_value_range": [30.0, 65.0],
            "category": "vital_sign",
        },
        "vasopressor_requirement_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.02],
            "peak_value_range": [0.2, 1.0],
            "category": "support_requirement",
        },
        "skin_pallor_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.03],
            "peak_value_range": [0.1, 0.8],
            "category": "physical_finding",
        },
        "diaphoresis_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.05],
            "peak_value_range": [0.2, 1.0],
            "category": "physical_finding",
        },
        "serum_lactate": {
            "unit": "mmol/L",
            "baseline_range": [0.5, 2.0],
            "peak_value_range": [2.0, 8.0],
            "category": "lab_value",
        },
    },
    "obstructive_shock_hazard_in_D-PULMONARY-EMBOLISM": {
        "shock_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.01],
            "peak_value_range": [0.2, 1.0],
            "category": "physical_finding",
        },
        "hypotension_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.03],
            "peak_value_range": [0.2, 1.0],
            "category": "physical_finding",
        },
        "systolic_blood_pressure": {
            "unit": "mmHg",
            "baseline_range": [100.0, 140.0],
            "peak_value_range": [40.0, 95.0],
            "category": "vital_sign",
        },
        "mean_arterial_pressure": {
            "unit": "mmHg",
            "baseline_range": [70.0, 100.0],
            "peak_value_range": [30.0, 65.0],
            "category": "vital_sign",
        },
    },
    "abdominal_compartment_syndrome_hazard": {
        "intra_abdominal_pressure": {
            "unit": "mmHg",
            "baseline_range": [0.0, 12.0],
            "peak_value_range": [12.0, 35.0],
            "category": "physical_measurement",
        },
        "abdominal_distension_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.05],
            "peak_value_range": [0.2, 1.0],
            "category": "physical_finding",
        },
        "vasopressor_requirement_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.02],
            "peak_value_range": [0.2, 1.0],
            "category": "support_requirement",
        },
        "oliguria_presence": {
            "unit": "present_absent_0_1",
            "baseline_range": [0.0, 0.03],
            "peak_value_range": [0.2, 1.0],
            "category": "renal_finding",
        },
        "urine_output": {
            "unit": "mL/kg/hr",
            "baseline_range": [0.5, 1.5],
            "peak_value_range": [0.0, 0.5],
            "category": "renal_measurement",
        },
    },
}


RECORD_ONLY_UNLESS_FORMAL_SUPPORT_AXES = {
    "gastric_fluid_vomitus_presence",
}


def prepare_case_data(data):
    data = dict(data)
    observations = {}
    snapshot_day = float(data.get("snapshot_day", 0.0) or 0.0)

    def item_day(item, default=snapshot_day):
        value = item.get("day")
        if value is None:
            value = item.get("relative_day")
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def add_observation(axis_id, value, unit, day=None, meta=None):
        if not axis_id or value is None:
            return
        value = float(value)
        obs_day = snapshot_day if day is None else float(day)
        obs_distance = abs(obs_day - snapshot_day)
        incoming = {
            "value": value,
            "unit": unit,
            "day": obs_day,
            "_snapshot_distance": obs_distance,
        }
        if isinstance(meta, dict):
            for key in ("category", "axis_role", "parent_axis_id", "legacy_axis_id", "source_text_value"):
                if meta.get(key):
                    incoming[key] = meta.get(key)
            if meta.get("_risk_context_observation"):
                incoming["_risk_context_observation"] = True
            if "use_in_time_conditioning" in meta:
                incoming["use_in_time_conditioning"] = bool(meta.get("use_in_time_conditioning"))
        if axis_id in observations:
            old = observations[axis_id]
            normalized_unit = norm_unit(unit or old.get("unit"))
            old_distance = float(old.get("_snapshot_distance", 0.0))
            if obs_distance < old_distance:
                observations[axis_id] = incoming
                return
            if obs_distance > old_distance:
                return
            if normalized_unit in ("presentabsent01", "probability01", "relativeactivity01", "severityscore01") or axis_id.endswith("_hazard") or "_hazard_" in axis_id:
                if value > float(old.get("value", 0.0)):
                    observations[axis_id] = incoming
                return
            if obs_day >= float(old.get("day", snapshot_day)):
                observations[axis_id] = incoming
            return
        observations[axis_id] = incoming

    for obs in data.get("observations", []):
        if not case_item_rankable(obs):
            continue
        inferred = infer_direct_observation(obs.get("axis_id"), obs.get("value"), obs.get("unit"), obs.get("qualitative_value"))
        if inferred is not None:
            value, unit = inferred
            add_observation(obs.get("axis_id"), value, unit, item_day(obs), obs)

    for obs in data.get("risk_context", []):
        if not case_item_rankable(obs):
            continue
        inferred = infer_direct_observation(obs.get("axis_id"), obs.get("value"), obs.get("unit"), obs.get("qualitative_value"))
        if inferred is not None:
            value, unit = inferred
            meta = dict(obs)
            meta["_risk_context_observation"] = True
            add_observation(obs.get("axis_id"), value, unit, item_day(obs), meta)

    for obs in data.get("course_observations", []):
        if not case_item_rankable(obs):
            continue
        inferred = infer_direct_observation(obs.get("axis_id"), obs.get("value"), obs.get("unit"), obs.get("qualitative_value"))
        if inferred is not None:
            value, unit = inferred
            add_observation(obs.get("axis_id"), value, unit, item_day(obs), obs)

    for traj in data.get("lab_trajectories", []):
        if not case_item_rankable(traj):
            continue
        axis_id = traj.get("axis_id")
        inferred = infer_direct_observation(axis_id, traj.get("value"), traj.get("unit"), traj.get("qualitative_value"))
        if inferred is not None:
            value, unit = inferred
            add_observation(axis_id, value, unit, item_day(traj), traj)
        numeric = [
            o
            for o in (
                (traj.get("observations") or [])
                + (traj.get("time_series") or [])
                + (traj.get("timepoints") or [])
            )
            if o.get("value") is not None and case_item_rankable(o)
        ]
        if not axis_id or not numeric:
            continue
        closest = min(numeric, key=lambda o: abs(item_day(o) - snapshot_day))
        add_observation(
            axis_id,
            float(closest["value"]),
            closest.get("unit") or traj.get("unit"),
            item_day(closest),
            traj,
        )

    for section in MAPPED_EVIDENCE_SECTIONS:
        records = data.get(section)
        if not isinstance(records, list):
            continue
        for item in records:
            if not isinstance(item, dict):
                continue
            for axis_id, axis_item in mapped_axis_items(item):
                inferred = infer_mapped_observation(item, axis_id, axis_item)
                if inferred is None:
                    continue
                value, unit = inferred
                add_observation(axis_id, value, unit, item_day(axis_item, item_day(item)), axis_item)

    for _section, item in iter_direct_axis_section_items(data):
        if not case_item_rankable(item):
            continue
        inferred = infer_direct_observation(item.get("axis_id"), item.get("value"), item.get("unit"), item.get("qualitative_value"))
        if inferred is None:
            continue
        value, unit = inferred
        add_observation(item.get("axis_id"), value, unit, item_day(item), item)

    for child_axis_id, child in list(observations.items()):
        parent_axis_id = child.get("parent_axis_id")
        if not parent_axis_id or parent_axis_id in observations:
            continue
        if norm_unit(child.get("unit")) not in ("presentabsent01", "probability01", "relativeactivity01", "severityscore01"):
            continue
        try:
            child_value = float(child.get("value", 0.0))
        except (TypeError, ValueError):
            continue
        if child_value < PARENT_FINDING_PRESENT_THRESHOLD:
            continue
        observations[parent_axis_id] = {
            "value": 1.0,
            "unit": "present_absent_0_1",
            "day": float(child.get("day", snapshot_day)),
            "_snapshot_distance": float(child.get("_snapshot_distance", 0.0)),
            "category": child.get("category") or "symptom",
            "axis_role": "finding",
            "source_text_value": f"inferred parent finding from {child_axis_id}",
            "_inferred_parent": True,
        }

    systolic = observations.get("systolic_blood_pressure")
    diastolic = observations.get("diastolic_blood_pressure")
    map_value = None
    if systolic is not None and diastolic is not None:
        try:
            systolic_value = float(systolic.get("value"))
            diastolic_value = float(diastolic.get("value"))
            map_value = (systolic_value + 2.0 * diastolic_value) / 3.0
            if "mean_arterial_pressure" not in observations:
                add_observation(
                    "mean_arterial_pressure",
                    map_value,
                    "mmHg",
                    max(float(systolic.get("day", snapshot_day)), float(diastolic.get("day", snapshot_day))),
                    {
                        "category": "vital_sign",
                        "axis_role": "measurement",
                        "source_text_value": "derived from systolic_blood_pressure and diastolic_blood_pressure",
                    },
                )
        except (TypeError, ValueError):
            map_value = None

    if "hypotension_presence" not in observations:
        hypotension = False
        if systolic is not None:
            try:
                hypotension = hypotension or float(systolic.get("value")) < 90.0
            except (TypeError, ValueError):
                pass
        if map_value is not None:
            hypotension = hypotension or map_value < 65.0
        if hypotension:
            add_observation(
                "hypotension_presence",
                1.0,
                "present_absent_0_1",
                snapshot_day,
                {
                    "category": "hemodynamic_finding",
                    "axis_role": "finding",
                    "source_text_value": "derived from low systolic_blood_pressure or mean_arterial_pressure",
                },
            )

    for source_axis_id, alias_axis_ids in EXACT_AXIS_ALIASES.items():
        source = observations.get(source_axis_id)
        if source is None:
            continue
        for alias_axis_id in alias_axis_ids:
            if alias_axis_id not in observations:
                observations[alias_axis_id] = {
                    **source,
                    "_legacy_proxy": True,
                    "_canonical_proxy_for_background": True,
                    "_derived_from_axes": [source_axis_id],
                    "source_text_value": f"exact alias proxy from {source_axis_id}",
                }
            proxy_axis_ids = source.setdefault("_legacy_proxy_axis_ids", [])
            if alias_axis_id not in proxy_axis_ids:
                proxy_axis_ids.append(alias_axis_id)
            source["_legacy_proxy_axis_id"] = alias_axis_id

    for source_axis_id, alias_axis_ids in SUPPRESSION_ONLY_AXIS_ALIASES.items():
        source = observations.get(source_axis_id)
        if source is None:
            continue
        matched_proxy_axis_ids = [alias_axis_id for alias_axis_id in alias_axis_ids if alias_axis_id in observations]
        if not matched_proxy_axis_ids:
            continue
        proxy_axis_ids = source.setdefault("_legacy_proxy_axis_ids", [])
        for alias_axis_id in matched_proxy_axis_ids:
            if alias_axis_id not in proxy_axis_ids:
                proxy_axis_ids.append(alias_axis_id)
        source["_legacy_proxy_axis_id"] = matched_proxy_axis_ids[0]
        source["_suppress_if_proxy_observed"] = True

    for legacy_axis_id, source_axis_ids in LEGACY_MANUAL_AXIS_BRIDGES.items():
        sources = [
            (source_axis_id, observations[source_axis_id])
            for source_axis_id in source_axis_ids
            if source_axis_id in observations
        ]
        if not sources:
            continue
        best_source_id, best_source = max(sources, key=lambda item: float(item[1].get("value", 0.0)))
        if legacy_axis_id not in observations:
            observations[legacy_axis_id] = {
                "value": float(best_source.get("value", 0.0)),
                "unit": "severity_score_0_1",
                "day": float(best_source.get("day", snapshot_day)),
                "_snapshot_distance": float(best_source.get("_snapshot_distance", 0.0)),
                "_legacy_proxy": True,
                "_derived_from_axes": [axis_id for axis_id, _obs in sources],
                "source_text_value": f"legacy proxy from {best_source_id}",
            }
        for source_axis_id, source in sources:
            source["_suppress_in_scoring"] = True
            source["_legacy_proxy_axis_id"] = legacy_axis_id
            proxy_axis_ids = source.setdefault("_legacy_proxy_axis_ids", [])
            if legacy_axis_id not in proxy_axis_ids:
                proxy_axis_ids.append(legacy_axis_id)

    data["observations_by_axis"] = observations
    return data


def load_case(path):
    return prepare_case_data(json.loads(path.read_text(encoding="utf-8-sig")))


def sample_uniform(rng, interval):
    lo, hi = interval
    if lo == hi:
        return lo
    if rng is None:
        return 0.5 * (lo + hi)
    return float(rng.uniform(lo, hi))


def inferred_t_max(manifold):
    horizons = []
    for axis in manifold.get("axes", {}).values():
        if axis.get("category") in ("derived_hazard", "treatment_modifier"):
            continue
        if "parent/satellite split avoids mixing" in str(axis.get("clinical_interpretation") or ""):
            continue
        peak = parse_interval(axis.get("peak_day_range"))
        plateau = parse_interval(axis.get("plateau_duration_days"))
        if peak is None:
            continue
        horizon = peak[1]
        if plateau is not None:
            horizon += 0.5 * plateau[1]
        horizons.append(horizon)
    if not horizons:
        return 90.0
    return float(np.clip(np.percentile(horizons, 75), 14.0, 365.0))


def disease_t_max(disease, manifold):
    override = T_MAX_BY_DISEASE.get(disease)
    if override is not None:
        return override
    if "_t_max" not in manifold:
        manifold["_t_max"] = inferred_t_max(manifold)
    return manifold["_t_max"]


def sample_mu_and_baseline(axis, t, rng):
    baseline = sample_uniform(rng, axis["baseline_range"])
    peak_day_range = axis.get("peak_day_range")
    peak_value_range = axis.get("peak_value_range")
    if t < 0 or peak_day_range is None or peak_value_range is None:
        return baseline, baseline

    peak_day = max(sample_uniform(rng, peak_day_range), 1e-6)
    peak_value = sample_uniform(rng, peak_value_range)
    plateau = 0.0 if axis.get("plateau_duration_days") is None else sample_uniform(rng, axis["plateau_duration_days"])
    plateau_end = peak_day + max(plateau, 0.0)

    if t <= 0:
        mu = baseline
    elif t < peak_day:
        mu = baseline + (peak_value - baseline) * (t / peak_day)
    elif t < plateau_end:
        mu = peak_value
    else:
        hl_range = axis.get("decline_half_life_days")
        if hl_range is None:
            mu = peak_value
        else:
            hl = max(sample_uniform(rng, hl_range), 1e-6)
            decay = 0.5 ** ((t - plateau_end) / hl)
            mu = baseline + (peak_value - baseline) * decay
    return mu, baseline


def axis_sigma(axis):
    cached = axis.get("_axis_sigma")
    if cached is not None:
        return cached
    ranges = [axis.get("baseline_range"), axis.get("peak_value_range")]
    values = []
    for interval in ranges:
        if interval is not None:
            values.extend([interval[0], interval[1]])
    if not values:
        return 1.0

    if axis.get("log_scale"):
        if zero_inclusive_log_axis(axis):
            logs = [math.log10(max(v, 0.0) + 1.0) for v in values]
        else:
            logs = [math.log10(max(v, 1e-12)) for v in values if v > 0]
        if not logs:
            return 0.5
        sigma = max((max(logs) - min(logs)) / 6.0, 0.15)
        axis["_axis_sigma"] = sigma
        return sigma

    spread = max(values) - min(values)
    ordered = sorted(float(v) for v in values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        median = ordered[mid]
    else:
        median = 0.5 * (ordered[mid - 1] + ordered[mid])
    typical = max(abs(median), 1.0)
    sigma = max(spread / 6.0, 0.08 * typical, 1e-6)
    axis["_axis_sigma"] = sigma
    return sigma


def axis_sigma_in_eval_space(source_axis, eval_axis, axis_id):
    """Return sigma in the same transformed coordinate used for likelihood.

    `combo_axis_endpoint` evaluates observations and means with `eval_axis`.
    If the background axis is linear but the disease axis is log-scale (or the
    reverse), reusing the source axis sigma mixes coordinates and can make
    normal labs almost unpenalized.
    """
    if source_axis is eval_axis:
        return axis_sigma(source_axis)
    cache_key = (
        "_axis_sigma_eval",
        eval_axis.get("unit"),
        bool(eval_axis.get("log_scale", False)),
        tuple(eval_axis.get("baseline_range") or ()),
        tuple(eval_axis.get("peak_value_range") or ()),
    )
    cached = source_axis.get(cache_key)
    if cached is not None:
        return cached

    values = []
    for interval in (source_axis.get("baseline_range"), source_axis.get("peak_value_range")):
        if interval is None:
            continue
        for value in interval:
            converted = convert_value(value, source_axis.get("unit"), eval_axis.get("unit"), axis_id)
            values.append(transform(eval_axis, converted))
    if not values:
        return axis_sigma(source_axis)

    spread = max(values) - min(values)
    sigma = max(spread / 6.0, 1e-6)
    source_axis[cache_key] = sigma
    return sigma


def zero_inclusive_log_axis(axis):
    if not axis.get("log_scale"):
        return False
    axis_id = axis.get("axis_id", "")
    if axis.get("category") != "csf" and not axis_id.startswith("csf_"):
        return False
    for interval in (axis.get("baseline_range"), axis.get("peak_value_range")):
        if interval is not None and min(interval) <= 0:
            return True
    return False


def transform(axis, value):
    if axis.get("log_scale"):
        if zero_inclusive_log_axis(axis):
            return math.log10(max(value, 0.0) + 1.0)
        return math.log10(max(value, 1e-12))
    return float(value)


def inverse_transform(axis, z):
    if axis.get("log_scale"):
        if zero_inclusive_log_axis(axis):
            return max((10.0 ** z) - 1.0, 0.0)
        return 10.0 ** z
    return float(z)


def deterministic_seed(parts):
    s = SEED
    for part in parts:
        for ch in str(part):
            s = (s * 131 + ord(ch)) % (2**32 - 1)
    return s


def case_reported_sex(case):
    demo = case.get("demographics") or {}
    sex = str(demo.get("sex", "")).upper()
    if sex in ("F", "FEMALE"):
        return "female"
    if sex in ("M", "MALE"):
        return "male"
    return None


def auto_demographic_context(case, disease):
    out = []
    demo = case.get("demographics") or {}
    age = demo.get("age")
    sex = case_reported_sex(case)

    if sex == "female":
        out.append({"factor": "sex", "category": "female", "source": "demographics"})
    elif sex == "male":
        out.append({"factor": "sex", "category": "male", "source": "demographics"})

    if isinstance(age, (int, float)):
        if disease == "D-SEPSIS-GN":
            category = "age_18_49" if age < 50 else "age_50_64" if age < 65 else "age_65_79" if age < 80 else "age_ge80"
        elif disease == "D137":
            category = "young_adult_16_to_35_years" if age <= 35 else "middle_adult_36_to_60_years" if age <= 60 else "older_adult_over_60_years"
        elif disease == "D-TTP":
            category = "younger_adult_18_40" if age <= 40 else "middle_age_40_65" if age <= 65 else "older_adult_over_65"
        else:
            category = None
        if category:
            out.append({"factor": "age", "category": category, "source": "demographics"})
    return out


def case_risk_context(case, disease):
    ctx = []
    for item in case.get("risk_context", []):
        if not case_item_rankable(item):
            continue
        applies = item.get("applies_to")
        if applies is None or disease in applies or "*" in applies:
            ctx.append(item)
    ctx.extend(auto_demographic_context(case, disease))
    return ctx


def anatomic_feasibility_prior(case, candidate):
    """Apply hard anatomic feasibility as a prior, not as a diagnosis label.

    This prevents anatomically impossible reproductive leaves from ranking high
    on shared nonspecific axes such as abdominal pain, fever, or free fluid.
    Unknown sex receives no penalty.
    """
    sex = case_reported_sex(case)
    if sex is None:
        return 0.0, []

    penalty = 0.0
    reasons = []
    for disease in candidate:
        if sex == "male" and disease in FEMALE_REPRODUCTIVE_DISEASE_IDS:
            penalty += ANATOMIC_IMPOSSIBILITY_LOG_PENALTY
            reasons.append(f"{disease}:female_reproductive_anatomy_absent_for_reported_male")
        elif sex == "female" and disease in MALE_REPRODUCTIVE_DISEASE_IDS:
            penalty += ANATOMIC_IMPOSSIBILITY_LOG_PENALTY
            reasons.append(f"{disease}:male_reproductive_anatomy_absent_for_reported_female")
    return penalty, reasons


def matched_risk_payload(manifold, context):
    by_key = {(c.get("factor"), c.get("category")) for c in context}
    by_factor = {}
    for item in context:
        by_factor.setdefault(item.get("factor"), []).append(item)
    axis_mods = {}
    coupling_mods = []
    log_prior = 0.0

    for rf in manifold["risk_factors"]:
        factor = rf.get("factor")
        for category, mod in iter_risk_factor_modulations(rf):
            if (
                (factor, category) not in by_key
                and not risk_factor_present_match(factor, category, by_factor)
            ):
                continue
            p_ratio = midpoint(mod.get("P_disease_ratio"), 1.0)
            if p_ratio > 0:
                log_prior += math.log(min(max(p_ratio, 0.05), 50.0))
            for item in iter_axis_response_modulation_items(mod.get("axis_response_modulation")):
                axis_mods.setdefault(item.get("axis_id"), []).append(item)
            for item in iter_risk_modulation_items(mod.get("coupling_modulation")):
                coupling_mods.append(item)
    return axis_mods, coupling_mods, log_prior


def iter_risk_factor_modulations(rf):
    raw = rf.get("modulation") or {}
    if isinstance(raw, dict):
        for category, mod in raw.items():
            if isinstance(mod, dict):
                yield category, mod
        return
    if isinstance(raw, list):
        category = "present"
        for mod in raw:
            if isinstance(mod, dict):
                yield category, mod


def iter_axis_response_modulation_items(raw):
    if raw is None:
        return
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(raw, dict):
        for axis_id, value in raw.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("axis_id", axis_id)
                yield item
            elif isinstance(value, str):
                yield {"axis_id": axis_id, "effect": value}


def iter_risk_modulation_items(raw):
    if raw is None:
        return
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("coupling_id", key)
                yield item


def risk_context_item_is_positive(item):
    value = item.get("value")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value <= 0:
        return False

    category = str(item.get("category", "")).lower()
    negative_markers = (
        "absent",
        "denied",
        "negative",
        "not_reported",
        "not_identified",
        "not_known",
        "none",
        "no_",
        "without",
        "ruled_out",
    )
    return not any(marker in category for marker in negative_markers)


def risk_factor_present_match(factor, category, by_factor):
    """Match factor-level positive context to generic ``present`` modulation.

    New distillations commonly write risk-factor modulation as
    ``factor -> present`` while real case JSON stores the factor with a
    contextual category such as ``immunosuppression`` or ``comorbidity``.
    Exact category matches remain authoritative; this fallback only bridges
    positive evidence for the same factor to the generic ``present`` bucket.
    """
    if category != "present":
        return False
    return any(risk_context_item_is_positive(item) for item in by_factor.get(factor, []))


def observed_value(case, axis_id):
    obs = case["observations_by_axis"].get(axis_id)
    if not obs:
        return None
    return obs["value"]


def observed_absent(case, axis_id):
    obs = case["observations_by_axis"].get(axis_id)
    if not obs:
        return False
    unit = norm_unit(obs.get("unit"))
    if unit not in ("presentabsent01", "probability01", "relativeactivity01", "severityscore01"):
        return False
    return float(obs["value"]) < PARENT_FINDING_PRESENT_THRESHOLD


def event_proxy_axis_ids_for_manifold(manifold):
    cached = manifold.get("_event_proxy_axis_id_set")
    if cached is not None:
        return cached

    axes = manifold["axes"]
    proxy_axis_ids = set()
    for hazard_axis_id, proxy_specs in EVENT_HAZARD_AXIS_PROXIES.items():
        if hazard_axis_id in axes:
            proxy_axis_ids.update(proxy_specs)
    manifold["_event_proxy_axis_id_set"] = proxy_axis_ids
    return proxy_axis_ids


def event_proxy_axis_for(manifold, axis_id):
    cache = manifold.setdefault("_event_proxy_axes", {})
    if axis_id in cache:
        return cache[axis_id]

    axes = manifold["axes"]
    for hazard_axis_id, proxy_specs in EVENT_HAZARD_AXIS_PROXIES.items():
        hazard_axis = axes.get(hazard_axis_id)
        spec = proxy_specs.get(axis_id)
        if hazard_axis is None or spec is None:
            continue

        axis = {
            "axis_id": axis_id,
            "category": spec.get("category", "event_manifestation"),
            "unit": spec["unit"],
            "axis_role": spec.get("axis_role", "measurement"),
            "parent_axis_id": spec.get("parent_axis_id"),
            "log_scale": bool(spec.get("log_scale", False)),
            "baseline_range": tuple(spec["baseline_range"]),
            "peak_day_range": hazard_axis.get("peak_day_range"),
            "peak_value_range": tuple(spec["peak_value_range"]),
            "plateau_duration_days": hazard_axis.get("plateau_duration_days"),
            "decline_half_life_days": hazard_axis.get("decline_half_life_days"),
            "_event_proxy_hazard_axis_id": hazard_axis_id,
        }
        cache[axis_id] = axis
        return axis

    cache[axis_id] = None
    return None


def manifold_axis_set(manifold, include_derived=True):
    key = "_axis_id_set" if include_derived else "_formal_axis_id_set"
    cached = manifold.get(key)
    if cached is not None:
        return cached
    if include_derived:
        cached = set(manifold["axes"])
    else:
        cached = {
            axis_id
            for axis_id, axis in manifold["axes"].items()
            if axis.get("category") != "derived_hazard"
        }
    cached.update(event_proxy_axis_ids_for_manifold(manifold))
    manifold[key] = cached
    return cached


def candidate_axis_set(candidate, manifolds, include_derived=True):
    if not candidate or not manifolds:
        return set()
    cache = _CANDIDATE_AXIS_SET_CACHE if include_derived else _CANDIDATE_FORMAL_AXIS_SET_CACHE
    cached = cache.get(candidate)
    if cached is not None:
        return cached
    out = set()
    for disease in candidate:
        out.update(manifold_axis_set(manifolds[disease], include_derived=include_derived))
    cache[candidate] = out
    return out


def axis_has_formal_support(axis_id, candidate, manifolds, background_axes):
    return axis_id in candidate_axis_set(candidate, manifolds, include_derived=True)


def candidate_formal_axis_ids(axis_ids, candidate, manifolds):
    formal = candidate_axis_set(candidate, manifolds, include_derived=False)
    return [axis_id for axis_id in axis_ids if axis_id in formal]


def conditional_axis_ids(case, candidate, manifolds, background_axes):
    """Observed axes eligible for likelihood under finding/measurement/satellite ontology.

    Satellite and measurement axes with a parent finding are conditional on the
    parent not being explicitly absent. This preserves the old V3 principle:
    first ask whether the finding exists; only then score its distribution,
    size, or other satellite attributes.
    """
    obs = case["observations_by_axis"]

    eligible = set()
    formal_by_axis = {}
    children_by_parent = {}
    for axis_id, item in obs.items():
        formal_axis = axis_has_formal_support(axis_id, candidate, manifolds, background_axes)
        if item.get("_legacy_proxy"):
            sources = item.get("_derived_from_axes") or []
            source_formal = any(
                axis_has_formal_support(source_axis_id, candidate, manifolds, background_axes)
                for source_axis_id in sources
            )
            sibling_proxy_formal = False
            for source_axis_id in sources:
                source_item = obs.get(source_axis_id) or {}
                for proxy_axis_id in source_item.get("_legacy_proxy_axis_ids", []):
                    if proxy_axis_id == axis_id:
                        continue
                    if axis_has_formal_support(proxy_axis_id, candidate, manifolds, background_axes) or eval_axis(
                        proxy_axis_id, candidate, manifolds, background_axes
                    ) is not None:
                        sibling_proxy_formal = True
                        break
                if sibling_proxy_formal:
                    break
            if sibling_proxy_formal and not formal_axis:
                continue
            if source_formal or (not formal_axis and not item.get("_canonical_proxy_for_background")):
                continue
        else:
            proxy_axis_ids = item.get("_legacy_proxy_axis_ids") or []
            legacy_axis_id = item.get("_legacy_proxy_axis_id")
            if legacy_axis_id and legacy_axis_id not in proxy_axis_ids:
                proxy_axis_ids.append(legacy_axis_id)
            proxy_formal = any(
                axis_has_formal_support(proxy_axis_id, candidate, manifolds, background_axes)
                for proxy_axis_id in proxy_axis_ids
            )
            proxy_usable = any(
                eval_axis(proxy_axis_id, candidate, manifolds, background_axes) is not None
                for proxy_axis_id in proxy_axis_ids
            )
            if observation_is_duration_axis(axis_id) and not formal_axis:
                continue
            if axis_id in RECORD_ONLY_UNLESS_FORMAL_SUPPORT_AXES and not formal_axis:
                continue
            if item.get("_risk_context_observation") and not formal_axis:
                continue
            if item.get("_suppress_if_proxy_observed") and not formal_axis:
                continue
            if (proxy_formal or proxy_usable) and not formal_axis:
                continue
        axis = eval_axis(axis_id, candidate, manifolds, background_axes)
        if axis is None:
            continue
        parent_axis_id = axis.get("parent_axis_id")
        if parent_axis_id and observed_absent(case, parent_axis_id):
            continue
        eligible.add(axis_id)
        formal_by_axis[axis_id] = formal_axis
        if parent_axis_id:
            children_by_parent.setdefault(parent_axis_id, set()).add(axis_id)

    axis_ids = []
    for axis_id in eligible:
        # Suppress a parent when observed child axes already represent the
        # same fact, except for the migration case where this candidate knows
        # the parent finding but does not yet have any of the observed child
        # satellites. Background-only parents should not be added just because
        # a child was observed.
        if (
            axis_id in children_by_parent
            and observed_value(case, axis_id) is not None
            and not observed_absent(case, axis_id)
            and (
                any(formal_by_axis.get(child_axis_id) for child_axis_id in children_by_parent[axis_id])
                or not formal_by_axis.get(axis_id)
            )
        ):
            continue
        axis_ids.append(axis_id)
    return sorted(axis_ids)


def axis_manifold_frequency(manifolds):
    cache_key = tuple(manifolds)
    cached = _AXIS_MANIFOLD_FREQUENCY_CACHE.get(cache_key)
    if cached is not None:
        return cached
    freq = {}
    for manifold in manifolds.values():
        for axis_id, axis in manifold["axes"].items():
            if axis.get("category") == "derived_hazard":
                continue
            freq[axis_id] = freq.get(axis_id, 0) + 1
    _AXIS_MANIFOLD_FREQUENCY_CACHE[cache_key] = freq
    return freq


def observed_axis_activity_against_disease(axis_id, axis, obs, background_axis):
    peak = parse_interval(axis.get("peak_value_range"))
    baseline = parse_interval(axis.get("baseline_range"))
    if peak is None or baseline is None:
        return 0.0
    try:
        obs_value = observation_value_for_axis(obs, axis, axis_id)
        baseline_mid = midpoint(baseline)
        peak_mid = midpoint(peak, baseline_mid)
        z_obs = transform(axis, obs_value)
        z_base = transform(axis, baseline_mid)
        z_peak = transform(axis, peak_mid)
    except Exception:
        return 0.0

    span = z_peak - z_base
    if abs(span) < 1e-6:
        return 0.0
    progress = (z_obs - z_base) / span
    if progress <= 0.0:
        return 0.0

    bg_axis = background_axis or axis
    try:
        bg_mid = midpoint(parse_interval(bg_axis.get("baseline_range")) or baseline, baseline_mid)
        z_bg = transform(axis, convert_value(bg_mid, bg_axis.get("unit"), axis.get("unit"), axis_id))
    except Exception:
        z_bg = z_base
    bg_span = abs(z_obs - z_bg) / max(abs(span), 1e-6)
    return clamp01(min(progress, bg_span))


def axis_active_duration_window_days(axis):
    """Approximate how long a positive axis can plausibly remain disease-active."""
    category = str(axis.get("category") or "").strip().lower()
    if category in ("derived_hazard", "event_hazard", LATENT_MECHANISM_CATEGORY, "treatment_modifier"):
        return None
    peak = parse_interval(axis.get("peak_day_range"))
    if peak is None:
        return None
    plateau = parse_interval(axis.get("plateau_duration_days")) or (0.0, 0.0)
    half_life = parse_interval(axis.get("decline_half_life_days"))
    tail = 0.0 if half_life is None else 3.0 * max(half_life[1], 0.0)
    return max(peak[1] + max(plateau[1], 0.0) + tail, 1e-6)


def duration_compatible_axis_category(axis):
    category = str(axis.get("category") or "").strip().lower()
    return (
        "symptom" in category
        or "physical" in category
        or "qualitative" in category
        or "functional" in category
        or "neurologic" in category
    )


def duration_compatibility_penalty(case, candidate, manifolds, background_axes):
    duration_days = case_presentation_duration_days(case)
    if duration_days is None:
        return 0.0

    penalties_by_axis = {}
    for disease in candidate:
        manifold = manifolds[disease]
        for axis_id, obs in case["observations_by_axis"].items():
            if observation_is_duration_axis(axis_id):
                continue
            axis = manifold["axes"].get(axis_id)
            if axis is None or not duration_compatible_axis_category(axis):
                continue
            window_days = axis_active_duration_window_days(axis)
            if window_days is None:
                continue
            if duration_days <= window_days * DURATION_COMPATIBILITY_GRACE_FACTOR:
                continue

            activity = observed_axis_activity_against_disease(
                axis_id,
                axis,
                obs,
                background_axes.get(axis_id),
            )
            if activity < 0.25:
                continue

            ratio = duration_days / max(window_days * DURATION_COMPATIBILITY_GRACE_FACTOR, 1e-6)
            penalty = min(
                DURATION_COMPATIBILITY_AXIS_CAP,
                DURATION_COMPATIBILITY_PENALTY_SCALE * math.log(max(ratio, 1.0)) * activity,
            )
            if penalty <= 0:
                continue
            penalties_by_axis[(disease, axis_id)] = max(penalties_by_axis.get((disease, axis_id), 0.0), penalty)

    if not penalties_by_axis:
        return 0.0
    total = min(sum(penalties_by_axis.values()), DURATION_COMPATIBILITY_TOTAL_CAP)
    return -float(total)


def generic_component_anchor_support(case, disease, manifolds, background_axes):
    """Use disease-owned, high-specificity observed axes as combo anchors.

    This is intentionally conservative. It does not say "this disease should
    win"; it only asks whether adding this vector field has independent evidence
    beyond generic fever/inflammation/vital-sign noise.
    """
    manifold = manifolds[disease]
    freq = axis_manifold_frequency(manifolds)
    max_freq = max(3, int(math.ceil(len(manifolds) * GENERIC_ANCHOR_MAX_AXIS_FRACTION)))
    score = 0.0

    for axis_id, obs in case["observations_by_axis"].items():
        axis = manifold["axes"].get(axis_id)
        if axis is None:
            continue
        category = str(axis.get("category") or "").strip().lower()
        if category in GENERIC_ANCHOR_EXCLUDED_CATEGORIES:
            continue
        if axis_id in GENERIC_ANCHOR_LOW_SPECIFICITY_AXES:
            continue
        axis_freq = freq.get(axis_id, 0)
        if axis_freq > max_freq:
            continue
        activity = observed_axis_activity_against_disease(axis_id, axis, obs, background_axes.get(axis_id))
        if activity < 0.45:
            continue

        if axis_freq <= 2:
            specificity = 1.25
        elif axis_freq <= 5:
            specificity = 1.0
        else:
            specificity = 0.7

        if "imaging" in category or "pathology" in category or "microbiology" in category:
            category_weight = 1.25
        elif category == "treatment_modifier":
            category_weight = 0.65
        elif "lab" in category:
            category_weight = 0.85
        else:
            category_weight = 0.75

        score += min(activity * specificity * category_weight, 1.5)
        if score >= GENERIC_ANCHOR_SCORE_CAP:
            return GENERIC_ANCHOR_SCORE_CAP
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def positive_observed_axis_score(case, axis_ids, threshold=0.5, score=1.0):
    best = 0.0
    for axis_id in axis_ids:
        value = observed_value(case, axis_id)
        if value is not None and float(value) >= threshold:
            best = max(best, score)
    return best


def aminotransferase_anchor_score(case):
    values = []
    for axis_id, upper_ref in (("serum_ast", 40.0), ("serum_alt", 56.0)):
        value = observed_value(case, axis_id)
        if value is None:
            continue
        value = float(value)
        values.append(value)
        ratio = value / upper_ref
        if value >= 1000 or ratio >= 20:
            return 3.0
        if value >= 500 or ratio >= 10:
            return 2.5
        if value >= 200 or ratio >= 5:
            return 2.0
        if value >= 100 or ratio >= 2.5:
            return 1.2
        if value >= 70 or ratio >= 1.8:
            return 0.6
    return 0.0


def acute_viral_hepatitis_anchor_support(case, disease):
    serology_axes_by_disease = {
        "D-ACUTE-HEPATITIS-A": (
            "hav_igm_positivity",
            "hav_rna_blood_positivity",
            "hav_rna_stool_positivity",
        ),
        "D-ACUTE-HEPATITIS-B": (
            "hepatitis_b_core_igm_positivity",
            "hepatitis_b_surface_antigen_positivity",
            "hbv_dna_positivity",
        ),
        "D-ACUTE-HEPATITIS-E": (
            "hev_igm_positivity",
            "hev_rna_blood_positivity",
            "hev_rna_stool_positivity",
        ),
    }
    score = 0.0
    score += positive_observed_axis_score(case, serology_axes_by_disease.get(disease, ()), score=3.0)
    score += aminotransferase_anchor_score(case)

    bilirubin = observed_value(case, "serum_bilirubin_total")
    if bilirubin is not None:
        bilirubin = float(bilirubin)
        if bilirubin >= 5.0:
            score += 1.5
        elif bilirubin >= 2.0:
            score += 1.0

    score += positive_observed_axis_score(
        case,
        (
            "jaundice_presence",
            "scleral_icterus_presence",
            "dark_urine_presence",
            "hepatic_encephalopathy_presence",
        ),
        score=0.8,
    )
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def dengue_anchor_support(case):
    score = 0.0
    score += positive_observed_axis_score(
        case,
        (
            "dengue_ns1_antigen_positivity",
            "dengue_igm_positivity",
            "dengue_pcr_positivity",
            "dengue_rna_positivity",
        ),
        score=3.0,
    )

    fever = observed_value(case, "fever_history_presence")
    fever_activity = observed_value(case, "fever_history_activity")
    temperature = observed_value(case, "body_temperature")
    if (fever is not None and float(fever) >= 0.5) or (fever_activity is not None and float(fever_activity) >= 0.4):
        score += 1.0
    elif temperature is not None and float(temperature) >= 38.0:
        score += 1.0

    platelet = observed_value(case, "platelet_count")
    if platelet is not None:
        platelet = float(platelet)
        if platelet <= 50.0:
            score += 2.0
        elif platelet <= 100.0:
            score += 1.5
        elif platelet <= 140.0:
            score += 0.6

    wbc = observed_value(case, "white_blood_cell_count")
    if wbc is not None:
        wbc = float(wbc)
        if wbc <= 3.0:
            score += 1.2
        elif wbc <= 4.0:
            score += 0.8

    score += positive_observed_axis_score(
        case,
        (
            "rash_presence",
            "petechiae_purpura_activity",
            "retro_orbital_pain_presence",
            "tourniquet_test_positive",
        ),
        score=0.5,
    )
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def acetaminophen_toxicity_anchor_support(case):
    score = 0.0
    score += positive_observed_axis_score(
        case,
        (
            "acetaminophen_exposure_probability",
            "staggered_or_repeated_supratherapeutic_ingestion_probability",
        ),
        score=3.0,
    )
    score += positive_observed_axis_score(
        case,
        ("hepatotoxic_drug_or_toxin_exposure_probability", "toxic_ingestion_presence"),
        score=1.2,
    )

    concentration = observed_value(case, "acetaminophen_serum_concentration")
    if concentration is not None:
        concentration = float(concentration)
        if concentration >= 150.0:
            score += 3.0
        elif concentration >= 30.0:
            score += 2.0
        elif concentration >= 10.0:
            score += 1.0

    dose = observed_value(case, "reported_acetaminophen_dose_mg_per_kg")
    if dose is not None:
        dose = float(dose)
        if dose >= 150.0:
            score += 3.0
        elif dose >= 100.0:
            score += 1.5

    score += aminotransferase_anchor_score(case)

    inr = observed_value(case, "prothrombin_time_inr")
    if inr is not None and float(inr) >= 1.5:
        score += 1.2

    ph = observed_value(case, "arterial_ph")
    lactate = observed_value(case, "serum_lactate")
    if ph is not None and float(ph) <= 7.30:
        score += 0.8
    if lactate is not None and float(lactate) >= 3.0:
        score += 0.8

    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def token_context_anchor_support(case, disease, manifolds, token_map):
    tokens = token_map.get(disease, ())
    if not tokens:
        return 0.0

    formal_axes = manifold_axis_set(manifolds[disease], include_derived=True)
    score = 0.0
    for axis_id, obs in case["observations_by_axis"].items():
        if axis_id not in formal_axes:
            continue
        if not any(token in axis_id for token in tokens):
            continue

        value = observed_value(case, axis_id)
        if value is None:
            continue
        unit = norm_unit(obs.get("unit"))
        if unit in ("presentabsent01", "probability01", "relativeactivity01", "severityscore01"):
            if float(value) >= 0.5:
                score += 3.0
        elif any(marker in axis_id for marker in ("concentration", "level", "dose", "ingestion", "exposure", "carboxyhemoglobin")):
            if float(value) > 0.0:
                score += 3.0

    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def toxidrome_anchor_support(case, disease, manifolds):
    return token_context_anchor_support(case, disease, manifolds, TOXIDROME_ANCHOR_TOKENS)


def specific_context_anchor_support(case, disease, manifolds):
    return token_context_anchor_support(case, disease, manifolds, SPECIFIC_CONTEXT_ANCHOR_TOKENS)


def key_lab_anchor_support(case, disease):
    if disease == "D-DIABETIC-KETOACIDOSIS":
        glucose = observed_value(case, "serum_glucose") or observed_value(case, "blood_glucose")
        score = 0.0
        if glucose is not None and float(glucose) >= 250.0:
            score += 2.0
            score += positive_observed_axis_score(
                case,
                ("ketonemia_presence", "urine_ketones_presence", "ketosis_presence", "serum_beta_hydroxybutyrate"),
                score=2.0,
            )
        ph = observed_value(case, "arterial_ph") or observed_value(case, "arterial_pH")
        if ph is not None and float(ph) <= 7.30:
            score += 1.5
        bicarbonate = observed_value(case, "serum_bicarbonate")
        if bicarbonate is not None and float(bicarbonate) <= 18.0:
            score += 1.5
        score += positive_observed_axis_score(
            case,
            ("kussmaul_respiration_presence", "kussmaul_breathing_activity", "metabolic_acidosis_presence"),
            score=1.0,
        )
        return min(score, GENERIC_ANCHOR_SCORE_CAP)

    if disease == "D-HYPEROSMOLAR-HYPERGLYCEMIC-STATE":
        glucose = observed_value(case, "serum_glucose") or observed_value(case, "blood_glucose")
        osmolality = observed_value(case, "serum_osmolality")
        score = 0.0
        if glucose is not None and float(glucose) >= 600.0:
            score += 3.0
        if osmolality is not None and float(osmolality) >= 320.0:
            score += 2.0
        return min(score, GENERIC_ANCHOR_SCORE_CAP)

    if disease == "D-ACUTE-SYMPTOMATIC-HYPERNATREMIA":
        sodium = observed_value(case, "serum_sodium")
        if sodium is not None and float(sodium) >= 150.0:
            return 3.0
        return 0.0

    if disease == "D-ACUTE-SYMPTOMATIC-HYPONATREMIA":
        sodium = observed_value(case, "serum_sodium")
        score = 0.0
        if sodium is not None:
            sodium = float(sodium)
            if sodium <= 120.0:
                score += 3.0
            elif sodium <= 125.0:
                score += 2.0
            elif sodium <= 130.0:
                score += 1.0
        osmolality = observed_value(case, "serum_osmolality")
        if osmolality is not None and float(osmolality) <= 275.0:
            score += 0.8
        urine_osmolality = observed_value(case, "urine_osmolality")
        if urine_osmolality is not None and float(urine_osmolality) <= 100.0:
            score += 0.6
        urine_sodium = observed_value(case, "urine_sodium")
        if urine_sodium is not None and float(urine_sodium) <= 30.0:
            score += 0.4
        score += positive_observed_axis_score(
            case,
            (
                "seizure_presence",
                "coma_presence",
                "mental_status_abnormality_presence",
                "confusion_presence",
            ),
            score=1.0,
        )
        score += positive_observed_axis_score(
            case,
            (
                "beer_potomania_context_presence",
                "low_solute_intake_context_presence",
                "chronic_heavy_beer_intake_presence",
            ),
            score=1.0,
        )
        beer_cans = observed_value(case, "daily_beer_intake_cans")
        if beer_cans is not None and float(beer_cans) >= 4.0:
            score += 0.8
        return min(score, GENERIC_ANCHOR_SCORE_CAP)

    if disease == "D-HYPOTHERMIA":
        temperature = observed_value(case, "body_temperature")
        score = 0.0
        if temperature is not None:
            temperature = float(temperature)
            if temperature <= 32.0:
                score += 3.0
            elif temperature <= 35.0:
                score += 2.0
        score += positive_observed_axis_score(
            case,
            ("hypothermia_presence", "cold_exposure_presence", "rewarming_therapy_presence"),
            score=2.0,
        )
        return min(score, GENERIC_ANCHOR_SCORE_CAP)

    if disease == "D-SEVERE-HYPOGLYCEMIA":
        glucose = observed_value(case, "serum_glucose") or observed_value(case, "blood_glucose")
        if glucose is not None and float(glucose) <= 55.0:
            return 3.0
        return 0.0

    if disease == "D-SEVERE-HYPOKALEMIA":
        potassium = observed_value(case, "serum_potassium")
        if potassium is not None and float(potassium) <= 3.0:
            return 3.0
        return 0.0

    if disease == "D-SEVERE-HYPERCALCEMIA":
        score = 0.0
        calcium = observed_value(case, "corrected_serum_calcium") or observed_value(case, "serum_calcium")
        ionized = observed_value(case, "ionized_calcium")
        if calcium is not None:
            calcium = float(calcium)
            if calcium >= 14.0:
                score += 3.0
            elif calcium >= 12.0:
                score += 2.0
        if ionized is not None:
            ionized = float(ionized)
            if ionized >= 1.75:
                score += 3.0
            elif ionized >= 1.5:
                score += 2.0
        return min(score, GENERIC_ANCHOR_SCORE_CAP)

    return 0.0


def alcohol_withdrawal_delirium_anchor_support(case):
    """Alcohol dependence alone is not enough to activate withdrawal delirium."""
    score = 0.0
    has_dependence = any(
        observed_value(case, axis_id) is not None and observed_value(case, axis_id) >= 0.5
        for axis_id in (
            "chronic_heavy_alcohol_use_presence",
            "harmful_alcohol_use_context_activity",
        )
    )
    has_trigger = any(
        observed_value(case, axis_id) is not None and observed_value(case, axis_id) >= 0.5
        for axis_id in (
            "recent_alcohol_reduction_or_cessation_presence",
            "alcohol_withdrawal_risk_activity",
            "prior_severe_alcohol_withdrawal_presence",
        )
    )
    hours_since_last = observed_value(case, "time_since_last_alcohol_intake_hours")
    if hours_since_last is not None and 6.0 <= float(hours_since_last) <= 120.0:
        has_trigger = True
        score += 1.0
    if has_dependence and has_trigger:
        score += 2.0
    elif has_trigger:
        score += 1.0
    else:
        return 0.0

    score += positive_observed_axis_score(
        case,
        (
            "autonomic_hyperactivity_presence",
            "tremor_presence",
            "withdrawal_hypertension_presence",
            "sweating_presence",
            "hallucination_presence",
            "visual_hallucination_presence",
            "tactile_hallucination_presence",
            "auditory_hallucination_presence",
            "agitation_presence",
            "insomnia_presence",
        ),
        score=0.8,
    )
    score += 0.5 * positive_observed_axis_score(
        case,
        ("seizure_presence", "generalized_tonic_clonic_seizure_presence", "delirium_presence"),
        score=1.0,
    )
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def ards_anchor_support(case):
    if observed_absent(case, "acute_respiratory_distress_syndrome_presence"):
        return 0.0

    score = 0.0
    score += positive_observed_axis_score(
        case,
        ("acute_respiratory_distress_syndrome_presence",),
        score=3.0,
    )
    score += positive_observed_axis_score(
        case,
        (
            "noncardiogenic_pulmonary_edema_presence",
            "bilateral_pulmonary_opacities_presence",
            "diffuse_bilateral_pulmonary_infiltrates_presence",
            "pulmonary_opacity_presence",
            "bilateral_pulmonary_opacity_presence",
            "pulmonary_infiltrate_presence",
            "ground_glass_opacity_presence",
            "pulmonary_consolidation_presence",
        ),
        score=2.0,
    )

    score += positive_observed_axis_score(
        case,
        (
            "supplemental_oxygen_requirement_presence",
            "hypoxemia_presence",
            "oxygen_desaturation_presence",
            "respiratory_distress_presence",
        ),
        score=1.2,
    )

    pf_ratio = observed_value(case, "pao2_fio2_ratio")
    if pf_ratio is not None:
        pf_ratio = float(pf_ratio)
        if pf_ratio <= 100.0:
            score += 2.0
        elif pf_ratio <= 200.0:
            score += 1.5
        elif pf_ratio <= 300.0:
            score += 1.0

    pao2 = observed_value(case, "arterial_pao2")
    if pao2 is not None and float(pao2) <= 60.0:
        score += 1.0
    spo2 = observed_value(case, "oxygen_saturation")
    if spo2 is not None and float(spo2) <= 90.0:
        score += 1.0
    oxygen_flow = observed_value(case, "oxygen_flow_rate_l_per_min") or observed_value(case, "supplemental_oxygen_flow_rate")
    if oxygen_flow is not None and float(oxygen_flow) >= 6.0:
        score += 0.8
    ggo_extent = observed_value(case, "diffuse_ground_glass_opacity_extent") or observed_value(case, "ground_glass_opacity_extent")
    if ggo_extent is not None and float(ggo_extent) >= 0.3:
        score += 0.8
    bilateral_extent = observed_value(case, "bilateral_pulmonary_opacity_extent") or observed_value(case, "bilateral_pulmonary_infiltrate_extent")
    if bilateral_extent is not None and float(bilateral_extent) >= 0.3:
        score += 0.8
    score += positive_observed_axis_score(
        case,
        ("chemical_inhalation_exposure_presence", "chlorine_gas_exposure_probability"),
        score=0.8,
    )

    peep = observed_value(case, "peep_cm_h2o")
    if peep is not None and float(peep) >= 5.0:
        score += 0.5

    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def pulmonary_embolism_anchor_support(case):
    score = 0.0
    score += positive_observed_axis_score(
        case,
        (
            "ctpa_pulmonary_arterial_filling_defect_activity",
            "pulmonary_arterial_filling_defect_presence",
            "main_and_bilateral_branch_pulmonary_arterial_filling_defect_presence",
        ),
        score=3.0,
    )
    score += positive_observed_axis_score(
        case,
        (
            "deep_venous_thrombosis_activity",
            "deep_venous_thrombosis_presence",
            "venous_thrombosis_activity",
            "bilateral_lower_leg_intermuscular_venous_thrombosis_presence",
        ),
        score=1.5,
    )
    d_dimer = observed_value(case, "d_dimer")
    if d_dimer is not None and float(d_dimer) >= 0.5:
        score += 1.0
    score += positive_observed_axis_score(
        case,
        (
            "pulmonary_hypertension_activity",
            "pulmonary_hypertension_presence",
            "right_ventricular_strain_activity_in_D-PULMONARY-EMBOLISM",
            "right_ventricular_dilation_activity_in_D-PULMONARY-EMBOLISM",
        ),
        score=0.8,
    )
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def aortic_dissection_anchor_support(case):
    score = 0.0
    score += positive_observed_axis_score(
        case,
        (
            "aortic_dissection_presence",
            "aortic_intimal_flap_presence",
            "aortic_flap_or_membrane_presence",
            "descending_aortic_dissection_flap_presence",
        ),
        score=3.0,
    )
    score += positive_observed_axis_score(
        case,
        (
            "aortic_false_lumen_patency",
            "false_aortic_lumen_presence",
            "false_lumen_prolapse_into_right_renal_artery_presence",
        ),
        score=1.4,
    )
    score += positive_observed_axis_score(
        case,
        (
            "renal_artery_malperfusion_presence",
            "right_renal_artery_involvement_by_aortic_flap_presence",
            "right_renal_artery_ostial_stenosis_presence",
            "right_kidney_hypoperfusion_presence",
            "asymmetric_renal_ct_enhancement_presence",
        ),
        score=1.2,
    )
    gradient = observed_value(case, "renal_artery_dynamic_stenosis_pressure_gradient_mmHg")
    if gradient is None:
        gradient = observed_value(case, "aorto_right_renal_artery_pressure_gradient_maximum")
    if gradient is not None and float(gradient) >= 5.0:
        score += 0.8
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def acute_intermittent_porphyria_anchor_support(case):
    score = 0.0
    score += positive_observed_axis_score(
        case,
        (
            "urine_porphobilinogen_screen_positive_presence",
            "porphobilinogen_screen_positive_presence",
        ),
        score=3.0,
    )
    pbg = observed_value(case, "urine_porphobilinogen")
    if pbg is not None and float(pbg) >= 10.0:
        score += 3.0
    ala = observed_value(case, "urine_delta_aminolevulinic_acid")
    if ala is not None and float(ala) >= 10.0:
        score += 1.5

    score += positive_observed_axis_score(
        case,
        (
            "recurrent_abdominal_pain_presence",
            "abdominal_pain_presence",
        ),
        score=0.8,
    )
    score += positive_observed_axis_score(
        case,
        (
            "motor_neuropathy_presence",
            "motor_neuropathy_pattern_presence",
            "limb_weakness_or_paralysis_presence",
            "limb_weakness_presence",
        ),
        score=0.8,
    )
    sodium = observed_value(case, "serum_sodium")
    if sodium is not None and float(sodium) <= 130.0:
        score += 0.8
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def acute_myocarditis_anchor_support(case):
    score = 0.0
    troponin = observed_value(case, "serum_troponin")
    if troponin is not None and float(troponin) > 50.0:
        score += 1.5
    score += positive_observed_axis_score(
        case,
        ("troponin_elevation_presence", "troponin_i_elevated_presence", "troponin_t_elevated_presence"),
        score=1.0,
    )
    score += positive_observed_axis_score(
        case,
        (
            "complete_atrioventricular_block_presence",
            "bradycardia_presence",
            "bradycardia_activity",
        ),
        score=1.2,
    )
    av_degree = observed_value(case, "atrioventricular_block_degree")
    if av_degree is not None and float(av_degree) >= 1.0:
        score += 1.0
    score += positive_observed_axis_score(
        case,
        (
            "regional_wall_motion_abnormality_presence",
            "inferior_wall_akinesia_presence",
            "acute_coronary_syndrome_mimic_activity",
        ),
        score=0.8,
    )
    coronary_stenosis = observed_value(case, "coronary_artery_stenosis_presence")
    if coronary_stenosis is not None and float(coronary_stenosis) <= 0.2 and score >= 1.5:
        score += 0.7
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def acute_mesenteric_ischemia_anchor_support(case):
    score = 0.0
    score += positive_observed_axis_score(
        case,
        (
            "mesenteric_vascular_occlusion_presence",
            "superior_mesenteric_artery_occlusion_presence",
            "superior_mesenteric_vein_thrombosis_presence",
            "superior_mesenteric_vein_thrombotic_occlusion_presence",
        ),
        score=3.0,
    )
    score += positive_observed_axis_score(
        case,
        (
            "bowel_ischemia_imaging_presence",
            "mesenteric_bowel_ischemia_presence",
            "acute_small_bowel_ischemia_ct_presence",
            "bowel_wall_hypoenhancement_presence",
            "pneumatosis_intestinalis_presence",
        ),
        score=2.0,
    )
    score += positive_observed_axis_score(
        case,
        ("portal_vein_thrombosis_presence", "portal_vein_thrombus_extension_presence"),
        score=0.8,
    )
    lactate = observed_value(case, "serum_lactate")
    if lactate is not None and float(lactate) >= 2.0:
        score += 0.8
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def incarcerated_groin_hernia_anchor_support(case):
    score = 0.0
    score += positive_observed_axis_score(
        case,
        (
            "irreducible_groin_hernia_presence",
            "strangulated_hernia_presence",
            "bowel_in_hernia_sac_imaging_presence",
            "transition_point_at_groin_hernia_presence",
        ),
        score=3.0,
    )
    score += positive_observed_axis_score(
        case,
        (
            "inguinal_hernia_presence",
            "femoral_hernia_presence",
            "inguinoscrotal_hernia_presence",
            "appendix_in_groin_hernia_sac_presence",
            "bladder_in_inguinal_hernia_sac_presence",
        ),
        score=2.2,
    )
    score += positive_observed_axis_score(
        case,
        ("groin_mass_presence", "hernia_sac_fat_stranding_presence"),
        score=1.2,
    )
    score += positive_observed_axis_score(
        case,
        ("groin_mass_tenderness_presence", "groin_pain_presence", "groin_skin_erythema_presence"),
        score=0.6,
    )
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def obstructive_pyelonephritis_anchor_support(case):
    obstruction = positive_observed_axis_score(
        case,
        (
            "hydronephrosis_presence",
            "ureteral_obstruction_presence",
            "obstructing_ureteral_stone_presence",
            "obstructive_uropathy_presence",
            "urinary_tract_obstruction_presence",
            "pyonephrosis_presence",
        ),
        score=3.0,
    )
    if obstruction <= 0.0:
        return 0.0

    score = obstruction
    score += positive_observed_axis_score(
        case,
        (
            "pyuria_presence",
            "bacteriuria_presence",
            "urine_nitrite_positive_presence",
            "urine_culture_positive_presence",
            "costovertebral_angle_tenderness_presence",
            "flank_pain_presence",
        ),
        score=0.8,
    )
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def catheter_associated_uti_anchor_support(case):
    catheter = positive_observed_axis_score(
        case,
        (
            "urinary_catheter_presence",
            "indwelling_urinary_catheter_presence",
            "foley_catheter_presence",
            "recent_urinary_catheterization_presence",
        ),
        score=3.0,
    )
    if catheter <= 0.0:
        return 0.0

    score = catheter
    score += positive_observed_axis_score(
        case,
        (
            "pyuria_presence",
            "bacteriuria_presence",
            "urine_nitrite_positive_presence",
            "urine_culture_positive_presence",
        ),
        score=0.8,
    )
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def perinephric_abscess_anchor_support(case):
    score = positive_observed_axis_score(
        case,
        (
            "perinephric_abscess_presence",
            "renal_abscess_presence",
            "perirenal_abscess_presence",
            "perinephric_fluid_collection_presence",
        ),
        score=3.0,
    )
    if score <= 0.0:
        return 0.0
    score += positive_observed_axis_score(
        case,
        ("flank_pain_presence", "costovertebral_angle_tenderness_presence", "pyuria_presence"),
        score=0.8,
    )
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def acute_mi_anchor_support(case):
    score = 0.0
    score += positive_observed_axis_score(
        case,
        (
            "coronary_occlusion_presence",
            "left_main_coronary_artery_occlusion_presence",
            "coronary_thrombus_presence",
        ),
        score=3.0,
    )
    score += positive_observed_axis_score(
        case,
        (
            "st_segment_elevation_presence",
            "ecg_anterior_wall_acute_ischemic_pattern_presence",
        ),
        score=1.4,
    )
    score += positive_observed_axis_score(
        case,
        ("troponin_t_elevated_presence", "troponin_i_elevated_presence"),
        score=1.0,
    )
    troponin = observed_value(case, "serum_troponin")
    if troponin is not None and float(troponin) > 20.0:
        score += 1.0
    score += positive_observed_axis_score(
        case,
        (
            "chest_pain_presence",
            "regional_wall_motion_abnormality_presence",
            "left_anterior_descending_territory_wall_motion_abnormality_presence",
        ),
        score=0.8,
    )
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def anaphylaxis_anchor_support(case):
    score = 0.0
    score += positive_observed_axis_score(
        case,
        (
            "allergen_exposure_temporal_association_probability",
            "bee_pollen_ingestion_presence",
            "food_allergen_exposure_presence",
            "drug_allergen_exposure_presence",
        ),
        score=1.6,
    )
    onset_hours = observed_value(case, "post_exposure_symptom_onset_hours")
    if onset_hours is not None and float(onset_hours) <= 4.0:
        score += 0.8
    score += positive_observed_axis_score(
        case,
        (
            "urticaria_presence",
            "generalized_urticaria_presence",
            "angioedema_presence",
            "facial_edema_presence",
            "facial_lip_tongue_angioedema_presence",
        ),
        score=1.4,
    )
    score += positive_observed_axis_score(
        case,
        (
            "wheezing_presence",
            "dyspnea_presence",
            "oxygen_desaturation_presence",
            "hypoxemia_presence",
            "vomiting_presence",
            "diarrhea_presence",
            "abdominal_pain_presence",
        ),
        score=1.0,
    )
    score += positive_observed_axis_score(case, ("hypotension_presence", "shock_presence"), score=0.8)
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def takotsubo_anchor_support(case):
    if positive_observed_axis_score(
        case,
        (
            "coronary_occlusion_presence",
            "left_main_coronary_artery_occlusion_presence",
            "coronary_thrombus_presence",
        ),
        score=1.0,
    ):
        return 0.0
    score = 0.0
    score += positive_observed_axis_score(
        case,
        (
            "takotsubo_ballooning_pattern_presence",
            "apical_ballooning_presence",
            "apical_ballooning_activity_in_D-TAKOTSUBO-CARDIOMYOPATHY",
        ),
        score=2.5,
    )
    score += positive_observed_axis_score(
        case,
        ("wall_motion_beyond_single_coronary_territory_presence",),
        score=1.5,
    )
    score += positive_observed_axis_score(
        case,
        ("emotional_stress_trigger_presence", "physical_stress_trigger_presence"),
        score=0.8,
    )
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def diffuse_alveolar_hemorrhage_anchor_support(case):
    direct_score = positive_observed_axis_score(
        case,
        (
            "diffuse_alveolar_hemorrhage_presence",
            "alveolar_hemorrhage_presence",
            "bloody_bronchoalveolar_lavage_presence",
            "bronchoscopy_progressively_bloody_return_presence",
            "hemosiderin_laden_macrophage_presence",
            "pulmonary_capillaritis_presence",
        ),
        score=4.0,
    )
    if direct_score:
        return direct_score

    chemical_inhalation = positive_observed_axis_score(
        case,
        ("chemical_inhalation_exposure_presence", "chlorine_gas_exposure_probability"),
        score=1.0,
    )
    immune_renal_context = positive_observed_axis_score(
        case,
        (
            "glomerulonephritis_presence",
            "hematuria_presence",
            "anti_gbm_antibody_positivity",
            "anca_positivity_probability",
            "systemic_vasculitis_context_presence",
        ),
        score=1.0,
    )
    hemoglobin = observed_value(case, "hemoglobin")
    anemia = hemoglobin is not None and float(hemoglobin) <= 10.0

    if chemical_inhalation and not anemia and not immune_renal_context:
        return 0.0

    score = 0.0
    score += positive_observed_axis_score(case, ("hemoptysis_presence",), score=0.7)
    score += positive_observed_axis_score(
        case,
        (
            "ground_glass_opacity_presence",
            "diffuse_ground_glass_opacity_extent",
            "bilateral_pulmonary_opacity_presence",
            "pulmonary_infiltrate_presence",
        ),
        score=0.7,
    )
    if anemia:
        score += 1.2
    score += immune_renal_context
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def acute_kidney_injury_anchor_support(case):
    score = 0.0
    creatinine = observed_value(case, "serum_creatinine")
    if creatinine is not None:
        creatinine = float(creatinine)
        if creatinine >= 4.0:
            score += 3.0
        elif creatinine >= 2.0:
            score += 2.0
        elif creatinine >= 1.5:
            score += 1.0
    score += positive_observed_axis_score(case, ("anuria_presence", "oliguria_presence"), score=1.5)
    score += positive_observed_axis_score(case, ("rhabdomyolysis_presence", "rhabdomyolysis_severity"), score=1.2)
    ck = observed_value(case, "serum_creatine_kinase")
    if ck is not None:
        ck = float(ck)
        if ck >= 5000:
            score += 1.5
        elif ck >= 1000:
            score += 0.8
    myoglobin = observed_value(case, "serum_myoglobin")
    if myoglobin is not None and float(myoglobin) >= 1000:
        score += 1.0
    bun = observed_value(case, "blood_urea_nitrogen")
    if bun is not None and float(bun) >= 40:
        score += 0.6
    score += positive_observed_axis_score(case, ("metabolic_acidosis_presence",), score=0.5)
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def acute_limb_ischemia_anchor_support(case):
    score = 0.0
    score += positive_observed_axis_score(
        case,
        (
            "peripheral_arterial_occlusion_presence",
            "lower_extremity_arterial_occlusion_presence",
            "cta_arterial_occlusion_presence",
            "arterial_occlusion_complete_presence",
        ),
        score=3.0,
    )
    score += positive_observed_axis_score(
        case,
        ("limb_ischemia_presence", "peripheral_ischemia_presence", "limb_ischemia_activity"),
        score=2.0,
    )
    score += positive_observed_axis_score(
        case,
        ("pulse_deficit_presence", "distal_limb_pulse_absence_presence"),
        score=1.2,
    )
    score += positive_observed_axis_score(
        case,
        ("limb_skin_coolness_presence", "limb_paresthesia_presence", "limb_sensory_abnormality_presence"),
        score=0.8,
    )
    abi = observed_value(case, "ankle_brachial_index")
    if abi is not None and float(abi) < 0.9:
        score += 1.0
    score += positive_observed_axis_score(case, ("sudden_onset_pain_presence",), score=0.5)
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def acute_hiv_anchor_support(case):
    score = 0.0
    viral_load = observed_value(case, "hiv_plasma_rna_viral_load")
    if viral_load is not None:
        viral_load = float(viral_load)
        if viral_load >= 100000:
            score += 4.0
        elif viral_load >= 10000:
            score += 3.0
    score += positive_observed_axis_score(
        case,
        ("hiv_p24_antigen_positivity", "hiv_antibody_seroconversion_activity"),
        score=2.0,
    )
    score += positive_observed_axis_score(
        case,
        (
            "hiv_positive_sexual_partner_presence",
            "known_hiv_positive_source_partner_presence",
            "unprotected_anal_intercourse_presence",
            "recent_unprotected_sexual_exposure_probability",
        ),
        score=1.0,
    )
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def acute_liver_failure_anchor_support(case):
    score = 0.0
    inr = observed_value(case, "prothrombin_time_inr")
    if inr is not None:
        inr = float(inr)
        if inr >= 2.0:
            score += 2.5
        elif inr >= 1.5:
            score += 2.0
    score += positive_observed_axis_score(
        case,
        ("hepatic_encephalopathy_presence", "mental_status_abnormality_activity", "somnolence_presence"),
        score=1.2,
    )
    bilirubin = observed_value(case, "serum_bilirubin_total")
    if bilirubin is not None and float(bilirubin) >= 5.0:
        score += 0.8
    meld = observed_value(case, "meld_score")
    if meld is not None and float(meld) >= 20:
        score += 1.0
    score += positive_observed_axis_score(case, ("jaundice_activity", "jaundice_presence", "scleral_icterus_presence"), score=0.5)
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def adenovirus_anchor_support(case):
    score = 0.0
    viral_load = observed_value(case, "adenovirus_viral_load")
    if viral_load is not None:
        viral_load = float(viral_load)
        if viral_load >= 100000.0:
            score += 3.0
        elif viral_load >= 1000.0:
            score += 2.5
        elif viral_load > 0.0:
            score += 1.5
    score += positive_observed_axis_score(
        case,
        (
            "adenovirus_tissue_immunohistochemistry_positive",
            "adenovirus_immunohistochemistry_positive",
            "adenovirus_hexon_typing_positive_presence",
            "human_adenovirus_hexon_gene_typing_result",
        ),
        score=2.0,
    )
    urinary_support = 0.0
    urinary_support += positive_observed_axis_score(case, ("hematuria_activity", "hematuria_presence", "urine_rbc_presence"), score=0.4)
    urinary_support += positive_observed_axis_score(case, ("dysuria_activity", "dysuria_presence"), score=0.4)
    urinary_support += positive_observed_axis_score(case, ("pyuria_activity", "urine_wbc_presence"), score=0.3)
    urinary_support += positive_observed_axis_score(
        case,
        (
            "allograft_tenderness_activity",
            "renal_allograft_tenderness_presence",
            "renal_allograft_tenderness_severity",
            "renal_allograft_tenderness_worsening_presence",
        ),
        score=0.6,
    )
    score += min(urinary_support, 1.2)
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def component_anchor_support(case, disease, manifolds, background_axes):
    """Require disease-specific evidence before allowing a combo to turn on.

    Without this, a broad second manifold can overfit generic fever/CRP/WBC axes.
    The anchors are not diagnostic labels; they are high-specificity observed axes
    that justify adding another vector field to the state equation.
    """
    score = 0.0
    obs = case["observations_by_axis"]

    if disease == "D137":
        ferritin = observed_value(case, "serum_ferritin")
        if ferritin is not None and ferritin >= 1000:
            score += 2.0
        glyco = observed_value(case, "glycosylated_ferritin_fraction")
        if glyco is not None and glyco <= 20:
            score += 2.0
        for axis_id in ("evanescent_rash_activity", "sore_throat_activity", "arthritis_activity"):
            value = observed_value(case, axis_id)
            if value is not None and value >= 0.4:
                score += 1.0

    elif disease == "D-SEPSIS-GN":
        pct = observed_value(case, "serum_procalcitonin")
        if pct is not None and pct >= 2.0:
            score += 2.0
        culture = observed_value(case, "blood_culture_positivity_probability")
        if culture is not None and culture >= 0.5:
            score += 2.0
        if "blood_culture_bacterial_load" in obs:
            score += 1.5
        lactate = observed_value(case, "serum_lactate")
        map_value = observed_value(case, "mean_arterial_pressure")
        if lactate is not None and lactate >= 2.5:
            score += 1.0
            if map_value is not None and map_value < 65:
                score += 1.0

    elif disease == "D-TTP":
        adam = observed_value(case, "adamts13_activity")
        if adam is not None and adam <= 10:
            score += 3.0
        inhibitor = observed_value(case, "anti_adamts13_igg_inhibitor_titer")
        if inhibitor is not None and inhibitor >= 0.5:
            score += 2.0
        platelet = observed_value(case, "platelet_count")
        if platelet is not None:
            if platelet <= 30:
                score += 2.0
            elif platelet <= 50:
                score += 1.5
            elif platelet <= 80:
                score += 0.5
        schisto = observed_value(case, "schistocyte_fraction")
        if schisto is not None and schisto >= 1.0:
            score += 2.0
        hapto = observed_value(case, "serum_haptoglobin")
        if hapto is not None and hapto <= 20:
            score += 1.5
        ldh = observed_value(case, "serum_ldh")
        hb = observed_value(case, "hemoglobin")
        if ldh is not None and hb is not None and ldh >= 500 and hb <= 10:
            score += 1.0

    elif disease == "D-APPENDICITIS":
        appendicolith = observed_value(case, "appendicolith_presence")
        if appendicolith is not None and appendicolith >= 0.5:
            score += 2.5
        diameter = observed_value(case, "appendiceal_diameter_mm")
        if diameter is not None:
            if diameter >= 15:
                score += 2.5
            elif diameter >= 10:
                score += 1.8
            elif diameter >= 6:
                score += 1.0
        for axis_id in ("appendiceal_dilation_activity", "appendiceal_wall_thickening_activity"):
            value = observed_value(case, axis_id)
            if value is not None and value >= 0.5:
                score += 1.4
        for axis_id in (
            "periappendiceal_fat_stranding_activity",
            "periappendiceal_free_fluid_activity",
            "cecal_wall_thickening_activity",
            "right_lower_quadrant_pain_activity",
        ):
            value = observed_value(case, axis_id)
            if value is not None and value >= 0.4:
                score += 0.6

    elif disease in ACUTE_VIRAL_HEPATITIS_DISEASE_IDS:
        score += acute_viral_hepatitis_anchor_support(case, disease)

    elif disease == "D-DENGUE":
        score += dengue_anchor_support(case)

    elif disease == "D-ACETAMINOPHEN-TOXICITY":
        score += acetaminophen_toxicity_anchor_support(case)

    elif disease == "D-PULMONARY-EMBOLISM":
        score += pulmonary_embolism_anchor_support(case)

    elif disease == "D-AORTIC-DISSECTION":
        score += aortic_dissection_anchor_support(case)

    elif disease == "D-ACUTE-INTERMITTENT-PORPHYRIA":
        score += acute_intermittent_porphyria_anchor_support(case)

    elif disease == "D-ACUTE-KIDNEY-INJURY":
        score += acute_kidney_injury_anchor_support(case)

    elif disease == "D-ACUTE-LIMB-ISCHEMIA":
        score += acute_limb_ischemia_anchor_support(case)

    elif disease == "D-ACUTE-HIV":
        score += acute_hiv_anchor_support(case)

    elif disease == "D-ACUTE-LIVER-FAILURE":
        score += acute_liver_failure_anchor_support(case)

    elif disease == "D-ADENOVIRUS-INFECTION":
        score += adenovirus_anchor_support(case)

    elif disease == "D-ACUTE-MESENTERIC-ISCHEMIA":
        score += acute_mesenteric_ischemia_anchor_support(case)

    elif disease == "D-INCARCERATED-GROIN-HERNIA":
        score += incarcerated_groin_hernia_anchor_support(case)

    elif disease == "D-ACUTE-MYOCARDITIS":
        score += acute_myocarditis_anchor_support(case)

    elif disease == "D-OBSTRUCTIVE-PYELONEPHRITIS":
        score += obstructive_pyelonephritis_anchor_support(case)

    elif disease == "D-CATHETER-ASSOCIATED-UTI":
        score += catheter_associated_uti_anchor_support(case)

    elif disease == "D-PERINEPHRIC-ABSCESS":
        score += perinephric_abscess_anchor_support(case)

    elif disease == "D-ACUTE-MYOCARDIAL-INFARCTION":
        score += acute_mi_anchor_support(case)

    elif disease == "D-ANAPHYLAXIS":
        score += anaphylaxis_anchor_support(case)

    elif disease == "D-TAKOTSUBO-CARDIOMYOPATHY":
        score += takotsubo_anchor_support(case)

    elif disease == "D-DIFFUSE-ALVEOLAR-HEMORRHAGE":
        score += diffuse_alveolar_hemorrhage_anchor_support(case)

    elif disease in TOXIDROME_EXPLICIT_ANCHOR_DISEASE_IDS:
        score += toxidrome_anchor_support(case, disease, manifolds)

    elif disease in {
        "D-ACUTE-SYMPTOMATIC-HYPONATREMIA",
        "D-ACUTE-SYMPTOMATIC-HYPERNATREMIA",
        "D-DIABETIC-KETOACIDOSIS",
        "D-HYPOTHERMIA",
        "D-HYPEROSMOLAR-HYPERGLYCEMIC-STATE",
        "D-SEVERE-HYPERCALCEMIA",
        "D-SEVERE-HYPOKALEMIA",
        "D-SEVERE-HYPOGLYCEMIA",
    }:
        score += key_lab_anchor_support(case, disease)

    elif disease == "D-ALCOHOL-WITHDRAWAL-DELIRIUM":
        score += alcohol_withdrawal_delirium_anchor_support(case)

    elif disease in SPECIFIC_CONTEXT_ANCHOR_TOKENS:
        score += specific_context_anchor_support(case, disease, manifolds)

    elif disease == "D-ACUTE-RESPIRATORY-DISTRESS-SYNDROME":
        score += ards_anchor_support(case)

    if disease in EXPLICIT_ANCHOR_REQUIRED_DISEASE_IDS:
        return min(score, GENERIC_ANCHOR_SCORE_CAP)
    return max(score, generic_component_anchor_support(case, disease, manifolds, background_axes))


def explicit_required_missing_anchor_penalty(case):
    n_axes = len(case.get("observations_by_axis", {}))
    dense_case_extra = 250.0 * min(max(n_axes - 20, 0), 100)
    return EXPLICIT_REQUIRED_MISSING_ANCHOR_EXTRA_PENALTY - dense_case_extra


def combo_anchor_penalty(case, candidate, manifolds, background_axes):
    support = {
        disease: component_anchor_support(case, disease, manifolds, background_axes)
        for disease in candidate
    }
    if len(candidate) <= 1:
        disease = next(iter(support.keys()), None)
        value = next(iter(support.values()), 0.0)
        if value >= SINGLE_ANCHOR_THRESHOLD:
            return 0.0, support
        penalty = SINGLE_MISSING_ANCHOR_PENALTY * (SINGLE_ANCHOR_THRESHOLD - value)
        if disease in EXPLICIT_ANCHOR_REQUIRED_DISEASE_IDS and value <= 0.0:
            penalty += explicit_required_missing_anchor_penalty(case)
        return penalty, support

    penalty = 0.0
    for disease, value in support.items():
        if value < COMBO_ANCHOR_THRESHOLD:
            penalty += COMBO_MISSING_ANCHOR_PENALTY * (COMBO_ANCHOR_THRESHOLD - value)
            if disease in EXPLICIT_ANCHOR_REQUIRED_DISEASE_IDS and value <= 0.0:
                penalty += explicit_required_missing_anchor_penalty(case)
    return penalty, support


def is_bounded_0_1_axis(axis):
    return norm_unit(axis.get("unit")) in (
        "presentabsent01",
        "probability01",
        "relativeactivity01",
        "severityscore01",
    )


def apply_axis_modulations(axis_id, axis, mu, baseline, sigma, mods, rng):
    for mod in mods:
        effect = mod.get("effect")
        direction = str(mod.get("direction") or mod.get("effect_direction") or "").strip().lower()
        factor = midpoint(mod.get("magnitude_factor_range") or mod.get("factor_range"), 1.0)
        if effect in ("blunted_response", "lower_peak"):
            mu = baseline + factor * (mu - baseline)
        elif effect == "higher_peak":
            mu = baseline + factor * (mu - baseline)
        elif effect == "higher_baseline":
            mu = mu * factor
            baseline = baseline * factor
        elif effect == "lower_baseline":
            mu = mu * factor
            baseline = baseline * factor
        elif effect == "more_variable":
            sigma *= max(factor, 1.0)
        elif effect == "less_variable":
            sigma *= min(max(factor, 0.1), 1.0)
        elif effect == "delayed_peak":
            pass
        elif direction in ("up", "increase", "increased", "higher", "raise", "raises"):
            mu = baseline + max(factor, 1.0) * (mu - baseline)
        elif direction in ("down", "decrease", "decreased", "lower", "lowers", "blunted", "attenuated"):
            if factor > 1.0:
                factor = 1.0 / factor
            mu = baseline + min(max(factor, 0.05), 1.0) * (mu - baseline)
    if is_bounded_0_1_axis(axis):
        mu = clamp01(mu)
        baseline = clamp01(baseline)
    elif axis.get("log_scale"):
        mu = max(mu, 1e-12)
    elif axis_id not in ("body_temperature",):
        mu = max(mu, 0.0)
    return mu, baseline, sigma


def eval_axis(axis_id, candidate, manifolds, background_axes):
    for disease in candidate:
        axis = manifolds[disease]["axes"].get(axis_id)
        if axis and axis.get("category") != "derived_hazard":
            return axis
        proxy_axis = event_proxy_axis_for(manifolds[disease], axis_id)
        if proxy_axis is not None:
            return proxy_axis
    return background_axes.get(axis_id)


def mechanism_edges_to(manifold, target_axis_id):
    indexed = manifold.get("mechanism_edges_by_target")
    if indexed is not None:
        return indexed.get(target_axis_id, [])
    return [
        edge
        for edge in manifold.get("mechanism_edges", [])
        if edge.get("target_axis_id") == target_axis_id
    ]


def clamp01(value):
    return max(min(float(value), 1.0), 0.0)


def axis_activity(axis, value, background_axis=None):
    """Map a hidden mechanism/source value to 0..1 activity.

    Mechanism nodes are intentionally unit-light: relative 0..1 axes use their
    value directly; other axes are normalized between inactive/background and
    disease-active ranges.
    """
    unit = norm_unit(axis.get("unit"))
    if unit in ("relativeactivity01", "probability01", "severityscore01"):
        return clamp01(value)

    inactive = parse_interval((background_axis or {}).get("baseline_range")) or parse_interval(axis.get("baseline_range"))
    active = parse_interval(axis.get("peak_value_range")) or parse_interval(axis.get("baseline_range"))
    inactive_mid = midpoint(inactive, 0.0)
    active_mid = midpoint(active, inactive_mid)
    denom = active_mid - inactive_mid
    if abs(denom) < 1e-9:
        return 0.0
    return clamp01((value - inactive_mid) / denom)


def edge_adjusted_delta(raw_delta, edge):
    effect = edge.get("effect_on_target")
    if effect == "increase":
        return abs(raw_delta)
    if effect == "decrease":
        return -abs(raw_delta)
    return raw_delta


def mechanism_activity_for_axis(
    disease,
    source_axis_id,
    t_by_disease,
    manifolds,
    background_axes,
    risk_payloads,
    rng,
    seen=None,
    cache=None,
):
    """Return effective 0..1 mechanism activity, including upstream mechanism gates."""
    cache = cache if cache is not None else {}
    if source_axis_id in cache:
        return cache[source_axis_id]

    manifold = manifolds[disease]
    source_axis = manifold["axes"].get(source_axis_id)
    if source_axis is None:
        return 0.0

    source_mu, source_baseline = sample_mu_and_baseline(source_axis, t_by_disease[disease], rng)
    sigma = axis_sigma(source_axis)
    mods = risk_payloads[disease]["axis_mods"].get(source_axis_id, [])
    source_mu, _, _ = apply_axis_modulations(source_axis_id, source_axis, source_mu, source_baseline, sigma, mods, rng)
    activity = axis_activity(source_axis, source_mu, background_axes.get(source_axis_id))

    seen = set(seen or ())
    if source_axis_id in seen:
        cache[source_axis_id] = clamp01(activity)
        return cache[source_axis_id]
    seen.add(source_axis_id)

    parent_signals = []
    for edge in mechanism_edges_to(manifold, source_axis_id):
        parent_axis_id = edge.get("source_axis_id")
        parent_axis = manifold["axes"].get(parent_axis_id)
        if parent_axis is None or parent_axis.get("category") != LATENT_MECHANISM_CATEGORY:
            continue
        parent_activity = mechanism_activity_for_axis(
            disease,
            parent_axis_id,
            t_by_disease,
            manifolds,
            background_axes,
            risk_payloads,
            rng,
            seen,
            cache,
        )
        if edge.get("effect_on_target") == "decrease":
            parent_activity = 1.0 - parent_activity
        parent_signals.append(clamp01(parent_activity))

    if parent_signals:
        activity = min(activity, max(parent_signals))

    cache[source_axis_id] = clamp01(activity)
    return cache[source_axis_id]


def mechanism_gate_for_target(
    disease,
    target_axis_id,
    t_by_disease,
    manifolds,
    background_axes,
    risk_payloads,
    rng,
    mechanism_activity_cache=None,
):
    """Return dominant latent-mechanism activity for a target axis, if modeled."""
    manifold = manifolds[disease]
    candidates = []
    cache = None
    if mechanism_activity_cache is not None:
        cache = mechanism_activity_cache.setdefault(disease, {})
    for edge in mechanism_edges_to(manifold, target_axis_id):
        source_axis_id = edge.get("source_axis_id")
        source_axis = manifold["axes"].get(source_axis_id)
        if source_axis is None:
            continue
        activity = mechanism_activity_for_axis(
            disease,
            source_axis_id,
            t_by_disease,
            manifolds,
            background_axes,
            risk_payloads,
            rng,
            cache=cache,
        )
        candidates.append((activity, edge))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])


def combo_axis_endpoint(
    axis_id,
    candidate,
    t_by_disease,
    manifolds,
    background_axes,
    risk_payloads,
    rng,
    mechanism_activity_cache=None,
):
    axis_eval = eval_axis(axis_id, candidate, manifolds, background_axes)
    if axis_eval is None:
        return None
    bg_axis = background_axes.get(axis_id) or axis_eval
    bg_mu, _ = sample_mu_and_baseline(bg_axis, -1.0, rng)
    bg_mu = convert_value(bg_mu, bg_axis.get("unit"), axis_eval.get("unit"), axis_id)
    z_bg = transform(axis_eval, bg_mu)

    raw_deltas = []
    strengths = []
    sigmas = [axis_sigma_in_eval_space(bg_axis, axis_eval, axis_id)]
    sources = []

    for disease in candidate:
        axis = manifolds[disease]["axes"].get(axis_id)
        if axis is None:
            axis = event_proxy_axis_for(manifolds[disease], axis_id)
        if axis is None or axis.get("category") == "derived_hazard":
            continue
        mu, baseline = sample_mu_and_baseline(axis, t_by_disease[disease], rng)
        hazard_axis_id = axis.get("_event_proxy_hazard_axis_id")
        axis_mods = list(risk_payloads[disease]["axis_mods"].get(axis_id, []))
        if hazard_axis_id:
            axis_mods.extend(risk_payloads[disease]["axis_mods"].get(hazard_axis_id, []))
        source_sigma = axis_sigma(axis)
        mu, baseline, modulated_source_sigma = apply_axis_modulations(axis_id, axis, mu, baseline, source_sigma, axis_mods, rng)
        sigma = axis_sigma_in_eval_space(axis, axis_eval, axis_id)
        if source_sigma > 0 and modulated_source_sigma != source_sigma:
            sigma *= modulated_source_sigma / source_sigma
        mu = convert_value(mu, axis.get("unit"), axis_eval.get("unit"), axis_id)
        z_mu = transform(axis_eval, mu)
        raw_delta = z_mu - z_bg
        gate = mechanism_gate_for_target(
            disease,
            hazard_axis_id or axis_id,
            t_by_disease,
            manifolds,
            background_axes,
            risk_payloads,
            rng,
            mechanism_activity_cache,
        )
        if gate is not None:
            activity, edge = gate
            raw_delta = edge_adjusted_delta(raw_delta, edge) * activity
        raw_deltas.append(raw_delta)
        strengths.append(abs(raw_delta) / max(sigma, 1e-6))
        sigmas.append(sigma)
        sources.append(disease)

    if not raw_deltas:
        z = z_bg
        sigma = axis_sigma(bg_axis)
        source = bg_axis.get("_source", "base_measure_background")
    else:
        signs = {1 if d > 0 else -1 if d < 0 else 0 for d in raw_deltas}
        signs.discard(0)
        if len(signs) > 1 and len(raw_deltas) > 1:
            dominant = int(np.argmax(strengths))
            z_delta = raw_deltas[dominant] + 0.05 * sum(d for i, d in enumerate(raw_deltas) if i != dominant)
            source = sources[dominant] + "_dominant_vector"
        else:
            z_delta = sum(raw_deltas)
            source = "+".join(sources)
        z = z_bg + z_delta
        sigma = max(sigmas) * (1.15 if len(candidate) > 1 else 1.0)

    mu_out = inverse_transform(axis_eval, z)
    if not axis_eval.get("log_scale") and axis_id != "body_temperature":
        mu_out = max(mu_out, 0.0)
    return axis_eval, mu_out, max(sigma, 1e-6), source


def background_axis_endpoint(axis_id, background_axes, rng):
    axis = background_axes.get(axis_id)
    if axis is None:
        return None
    mu_value, _ = sample_mu_and_baseline(axis, -1.0, rng)
    return axis, mu_value, axis_sigma(axis), axis.get("_source", "base_measure_background")


def coupling_to_corr(c):
    rel = c.get("relationship", "")
    corr = parse_interval(c.get("correlation_range"))
    if corr is not None:
        r = 0.5 * (corr[0] + corr[1])
    elif rel in ("negative_correlation", "opposite_direction"):
        r = -0.45
    else:
        r = 0.45
    if rel in ("negative_correlation", "opposite_direction"):
        r = -abs(r)
    elif rel in ("positive_correlation", "same_direction", "source_leads_target", "target_leads_source"):
        if corr is None:
            r = abs(r)
    return float(np.clip(r, -0.95, 0.95))


def coupling_type(c):
    return str(c.get("coupling_type") or "noise_correlation").strip().lower()


def is_noise_coupling(c):
    return coupling_type(c) in NOISE_COUPLING_TYPES


def is_drift_coupling(c):
    return coupling_type(c) in DRIFT_COUPLING_TYPES and bool(c.get("effect_direction"))


def apply_coupling_mod(r, mod):
    effect = mod.get("effect")
    factor = midpoint(mod.get("factor_range"), 1.0)
    if effect in ("weaken", "decouple"):
        r *= factor
    elif effect == "strengthen":
        r *= factor
    elif effect == "invert":
        r *= -factor
    elif effect == "delay":
        r *= min(factor, 0.8)
    return float(np.clip(r, -0.95, 0.95))


def nearest_corr_psd(corr):
    corr = 0.5 * (corr + corr.T)
    vals, vecs = np.linalg.eigh(corr)
    vals = np.clip(vals, 1e-6, None)
    psd = (vecs * vals) @ vecs.T
    d = np.sqrt(np.clip(np.diag(psd), 1e-12, None))
    psd = psd / np.outer(d, d)
    np.fill_diagonal(psd, 1.0)
    return psd


def build_corr(axis_ids, candidate, manifolds, risk_payloads, background_axes):
    idx = {a: i for i, a in enumerate(axis_ids)}
    corr = np.eye(len(axis_ids))

    for disease in candidate:
        for c in manifolds[disease]["axis_couplings"]:
            if not is_noise_coupling(c):
                continue
            src = c.get("source_axis_id")
            tgt = c.get("target_axis_id")
            if src not in idx or tgt not in idx:
                continue
            r = coupling_to_corr(c)
            i, j = idx[src], idx[tgt]
            if abs(r) > abs(corr[i, j]):
                corr[i, j] = corr[j, i] = r

    for disease in candidate:
        for mod in risk_payloads[disease]["coupling_mods"]:
            src = mod.get("source_axis_id")
            tgt = mod.get("target_axis_id")
            if src not in idx or tgt not in idx:
                continue
            i, j = idx[src], idx[tgt]
            corr[i, j] = corr[j, i] = apply_coupling_mod(corr[i, j], mod)

    return nearest_corr_psd(corr)


def mvn_logpdf(x, mu, sigmas, corr):
    sigmas = np.maximum(np.asarray(sigmas, dtype=float), 1e-6)
    cov = corr * np.outer(sigmas, sigmas)
    jitter = 1e-6
    for _ in range(5):
        try:
            chol = np.linalg.cholesky(cov + np.eye(len(x)) * jitter)
            diff = x - mu
            sol = np.linalg.solve(chol, diff)
            quad = float(sol @ sol)
            logdet = 2.0 * float(np.sum(np.log(np.diag(chol))))
            return -0.5 * (quad + logdet + len(x) * math.log(2.0 * math.pi))
        except np.linalg.LinAlgError:
            jitter *= 10.0
    return float("-inf")


def mvn_logpdf_cached(x, mu, sigmas, corr, factor_cache):
    sigmas = np.maximum(np.asarray(sigmas, dtype=float), 1e-6)
    key = tuple(float(s) for s in sigmas)
    cached = factor_cache.get(key)
    if cached is None:
        cov = corr * np.outer(sigmas, sigmas)
        jitter = 1e-6
        cached = False
        for _ in range(5):
            try:
                chol = np.linalg.cholesky(cov + np.eye(len(x)) * jitter)
                logdet = 2.0 * float(np.sum(np.log(np.diag(chol))))
                cached = (chol, logdet)
                break
            except np.linalg.LinAlgError:
                jitter *= 10.0
        factor_cache[key] = cached
    if cached is False:
        return float("-inf")

    chol, logdet = cached
    diff = x - mu
    sol = np.linalg.solve(chol, diff)
    quad = float(sol @ sol)
    return -0.5 * (quad + logdet + len(x) * math.log(2.0 * math.pi))


def use_grid_scoring():
    return SCORE_MODE in {"grid", "fast", "deterministic"}


def duration_conditioned_time_values(duration_days, rng):
    duration_days = max(float(duration_days), 1e-6)
    if use_grid_scoring():
        seen = set()
        for factor in DURATION_CONDITION_SAMPLE_FACTORS:
            value = max(duration_days * factor, 1e-6)
            key = round(value, 6)
            if key in seen:
                continue
            seen.add(key)
            yield value
        return

    for _ in range(N_MC):
        yield float(rng.lognormal(mean=math.log(duration_days), sigma=DURATION_CONDITION_LOG_SIGMA))


def iter_candidate_time_samples(candidate, manifolds, rng, case=None):
    duration_days = case_presentation_duration_days(case) if case is not None else None
    if duration_days is not None:
        for t in duration_conditioned_time_values(duration_days, rng):
            yield {disease: t for disease in candidate}, None if use_grid_scoring() else rng
        return

    if use_grid_scoring():
        # Midpoint-only grids can miss short acute windows when a disease also
        # has long context/risk axes that inflate t_max. Always include a few
        # early absolute times so transient presentations remain testable.
        seen = set()
        for t in EARLY_GRID_TIME_DAYS:
            key = ("abs", round(float(t), 6))
            if key in seen:
                continue
            seen.add(key)
            yield {
                disease: min(float(t), disease_t_max(disease, manifolds[disease]))
                for disease in candidate
            }, None
        for i in range(TIME_GRID_N):
            q = (i + 0.5) / TIME_GRID_N
            key = ("q", round(float(q), 6))
            if key in seen:
                continue
            seen.add(key)
            yield {
                disease: float(q * disease_t_max(disease, manifolds[disease]))
                for disease in candidate
            }, None
        return

    for _ in range(N_MC):
        yield {
            disease: float(rng.uniform(0.0, disease_t_max(disease, manifolds[disease])))
            for disease in candidate
        }, rng


def iter_background_samples(rng):
    if use_grid_scoring():
        yield None
        return
    for _ in range(N_MC):
        yield rng


def score_candidate(case, candidate, manifolds, background_axes):
    background_axes = background_axes_for_case(background_axes, case, candidate)
    rng = np.random.default_rng(deterministic_seed(candidate + (case.get("case_id"),)))
    obs = case["observations_by_axis"]
    axis_ids = conditional_axis_ids(case, candidate, manifolds, background_axes)
    if not axis_ids:
        return None

    risk_payloads = {}
    anchor_penalty, anchor_support = combo_anchor_penalty(case, candidate, manifolds, background_axes)
    duration_penalty = duration_compatibility_penalty(case, candidate, manifolds, background_axes)
    feasibility_penalty, feasibility_reasons = anatomic_feasibility_prior(case, candidate)
    log_prior = COMBO_LOG_PENALTY * (len(candidate) - 1) + anchor_penalty + duration_penalty + feasibility_penalty
    for disease in candidate:
        axis_mods, coupling_mods, lp = matched_risk_payload(
            manifolds[disease],
            case_risk_context(case, disease),
        )
        risk_payloads[disease] = {
            "axis_mods": axis_mods,
            "coupling_mods": coupling_mods,
            "log_prior": lp,
        }
        log_prior += lp

    corr = build_corr(axis_ids, candidate, manifolds, risk_payloads, background_axes)
    formal_axis_ids = candidate_formal_axis_ids(axis_ids, candidate, manifolds)
    formal_axis_id_set = set(formal_axis_ids)
    if not formal_axis_ids:
        log_prior += NO_FORMAL_SUPPORT_LOG_PENALTY
        log_joint = []
        best = None
        best_lp = float("-inf")
        factor_cache = {}
        for sample_rng in iter_background_samples(rng):
            x = []
            mu = []
            sigmas = []
            contrib_meta = []
            for axis_id in axis_ids:
                endpoint = background_axis_endpoint(axis_id, background_axes, sample_rng)
                if endpoint is None:
                    continue
                axis, mu_value, sigma, source = endpoint
                obs_value = observation_value_for_axis(obs[axis_id], axis, axis_id)
                x.append(transform(axis, obs_value))
                mu.append(transform(axis, mu_value))
                sigmas.append(sigma)
                contrib_meta.append((axis_id, obs_value, axis.get("unit"), mu_value, source))

            lp = mvn_logpdf_cached(np.asarray(x), np.asarray(mu), np.asarray(sigmas), corr, factor_cache) + log_prior
            log_joint.append(lp)
            if lp > best_lp:
                best_lp = lp
                best = {
                    "t_by_disease": {disease: 0.0 for disease in candidate},
                    "mu": mu,
                    "x": x,
                    "sigmas": sigmas,
                    "meta": contrib_meta,
                }

        log_marginal = float(logsumexp(log_joint) - math.log(len(log_joint)))
        return {
            "candidate": "+".join(candidate),
            "candidate_tuple": candidate,
            "log_marginal": log_marginal,
            "mean_log_per_axis": log_marginal / len(axis_ids),
            "n_axes": len(axis_ids),
            "axis_ids": axis_ids,
            "log_prior": log_prior,
            "duration_penalty": duration_penalty,
            "feasibility_penalty": feasibility_penalty,
            "feasibility_reasons": feasibility_reasons,
            "anchor_support": anchor_support,
            "best": best,
        }

    log_joint = []
    best = None
    best_lp = float("-inf")
    factor_cache = {}
    static_background_contrib = {}
    if use_grid_scoring():
        for axis_id in axis_ids:
            if axis_id in formal_axis_id_set:
                continue
            endpoint = background_axis_endpoint(axis_id, background_axes, None)
            if endpoint is None:
                continue
            axis, mu_value, sigma, source = endpoint
            obs_value = observation_value_for_axis(obs[axis_id], axis, axis_id)
            static_background_contrib[axis_id] = (
                axis,
                transform(axis, obs_value),
                transform(axis, mu_value),
                sigma,
                (axis_id, obs_value, axis.get("unit"), mu_value, source),
            )

    for t_by_disease, sample_rng in iter_candidate_time_samples(candidate, manifolds, rng, case):
        mechanism_activity_cache = {} if sample_rng is None else None
        x = []
        mu = []
        sigmas = []
        contrib_meta = []
        for axis_id in axis_ids:
            if axis_id not in formal_axis_id_set:
                cached = static_background_contrib.get(axis_id)
                if cached is None:
                    endpoint = background_axis_endpoint(axis_id, background_axes, sample_rng)
                    if endpoint is None:
                        continue
                    axis, mu_value, sigma, source = endpoint
                    obs_value = observation_value_for_axis(obs[axis_id], axis, axis_id)
                    cached = (
                        axis,
                        transform(axis, obs_value),
                        transform(axis, mu_value),
                        sigma,
                        (axis_id, obs_value, axis.get("unit"), mu_value, source),
                    )
                _axis, x_value, mu_value, sigma, meta = cached
                x.append(x_value)
                mu.append(mu_value)
                sigmas.append(sigma)
                contrib_meta.append(meta)
            else:
                endpoint = combo_axis_endpoint(
                    axis_id,
                    candidate,
                    t_by_disease,
                    manifolds,
                    background_axes,
                    risk_payloads,
                    sample_rng,
                    mechanism_activity_cache,
                )
                if endpoint is None:
                    continue
                axis, mu_value, sigma, source = endpoint
                obs_value = observation_value_for_axis(obs[axis_id], axis, axis_id)
                x.append(transform(axis, obs_value))
                mu.append(transform(axis, mu_value))
                sigmas.append(sigma)
                contrib_meta.append((axis_id, obs_value, axis.get("unit"), mu_value, source))

        lp = mvn_logpdf_cached(np.asarray(x), np.asarray(mu), np.asarray(sigmas), corr, factor_cache) + log_prior
        log_joint.append(lp)
        if lp > best_lp:
            best_lp = lp
            best = {
                "t_by_disease": t_by_disease,
                "mu": mu,
                "x": x,
                "sigmas": sigmas,
                "meta": contrib_meta,
            }

    log_marginal = float(logsumexp(log_joint) - math.log(len(log_joint)))
    return {
        "candidate": "+".join(candidate),
        "candidate_tuple": candidate,
        "log_marginal": log_marginal,
        "mean_log_per_axis": log_marginal / len(axis_ids),
        "n_axes": len(axis_ids),
        "axis_ids": axis_ids,
        "log_prior": log_prior,
        "duration_penalty": duration_penalty,
        "feasibility_penalty": feasibility_penalty,
        "feasibility_reasons": feasibility_reasons,
        "anchor_support": anchor_support,
        "best": best,
    }


def score_background_null(case, background_axes):
    """Score the case under a pure risk-adjusted background model.

    This is the OOD/null comparison: no disease vector field, no disease prior,
    and no disease couplings. The runtime returns the delta; downstream decides
    how much Bayes-factor evidence is enough for an in-atlas call.
    """
    background_axes = background_axes_for_case(background_axes, case, ())
    rng = np.random.default_rng(deterministic_seed(("background_null", case.get("case_id"))))
    obs = case["observations_by_axis"]
    axis_ids = conditional_axis_ids(case, tuple(), {}, background_axes)
    if not axis_ids:
        return None

    corr = build_corr(axis_ids, tuple(), {}, {}, background_axes)
    log_joint = []
    best = None
    best_lp = float("-inf")
    factor_cache = {}

    for sample_rng in iter_background_samples(rng):
        x = []
        mu = []
        sigmas = []
        contrib_meta = []
        for axis_id in axis_ids:
            axis = background_axes[axis_id]
            mu_value, _ = sample_mu_and_baseline(axis, -1.0, sample_rng)
            obs_value = observation_value_for_axis(obs[axis_id], axis, axis_id)
            x.append(transform(axis, obs_value))
            mu.append(transform(axis, mu_value))
            sigmas.append(axis_sigma(axis))
            contrib_meta.append((axis_id, obs_value, axis.get("unit"), mu_value, axis.get("_source", "base_measure_background")))

        lp = mvn_logpdf_cached(np.asarray(x), np.asarray(mu), np.asarray(sigmas), corr, factor_cache)
        log_joint.append(lp)
        if lp > best_lp:
            best_lp = lp
            best = {
                "mu": mu,
                "x": x,
                "sigmas": sigmas,
                "meta": contrib_meta,
            }

    log_marginal = float(logsumexp(log_joint) - math.log(len(log_joint)))
    return {
        "candidate": "background_only",
        "candidate_tuple": tuple(),
        "log_marginal": log_marginal,
        "mean_log_per_axis": log_marginal / len(axis_ids),
        "n_axes": len(axis_ids),
        "axis_ids": axis_ids,
        "log_prior": 0.0,
        "anchor_support": {},
        "best": best,
    }


def expected_tuple(case):
    if case.get("expected_manifolds"):
        return tuple(case["expected_manifolds"])
    if case.get("expected_manifold"):
        return (case["expected_manifold"],)
    return tuple()


def candidate_tuples(labels):
    singles = [(label,) for label in labels]
    pairs = list(itertools.combinations(labels, 2)) if MAX_COMBO_SIZE >= 2 else []
    return singles + pairs


def candidate_allowed_for_case(case, candidate, manifolds):
    """Apply case-stage eligibility for leaves that require post-workup evidence."""
    case_stage = case.get("diagnostic_stage")
    for disease in candidate:
        scope = manifolds[disease].get("distillation_scope") or {}
        if not isinstance(scope, dict):
            continue
        required_stage = scope.get("candidate_requires_diagnostic_stage")
        if required_stage and case_stage != required_stage:
            return False
    return True


def main():
    manifolds = {label: load_manifold(path) for label, path in MANIFOLD_PATHS.items()}
    background_axes = build_background_axes(manifolds, load_master_axes())
    cases = [load_case(path) for path in sorted(CASE_DIR.glob("v5_case_*.json"))]
    if CASE_FILTER:
        cases = [
            case for case in cases
            if any(token in case.get("case_id", "") or token in str(case.get("source_pmcid", "")) for token in CASE_FILTER)
        ]
    if ONLY_COMBO_CASES:
        cases = [case for case in cases if len(expected_tuple(case)) > 1]
    candidates = candidate_tuples(tuple(MANIFOLD_PATHS))

    lines = []
    lines.append("=" * 100)
    lines.append("V5 joint SDE PMC case ranking test")
    lines.append("=" * 100)
    lines.append(
        f"N_MC={N_MC}, seed={SEED}, combo_penalty={COMBO_LOG_PENALTY}, "
        f"combo_anchor_threshold={COMBO_ANCHOR_THRESHOLD}"
    )
    if use_grid_scoring():
        lines.append(
            f"Score mode: {SCORE_MODE} time_grid_n={TIME_GRID_N} "
            f"(deterministic midpoint sampling + early anchors {EARLY_GRID_TIME_DAYS})"
        )
    else:
        lines.append(f"Score mode: {SCORE_MODE} monte_carlo_samples={N_MC}")
    lines.append("Runtime features: joint covariance from axis_couplings; risk-factor axis/coupling modulation; vector-field superposition for 2-disease candidates.")
    lines.append(f"Manifold discovery: {len(MANIFOLD_PATHS)} root distillation files from {DISTILL_DIR / 'v5_*.json'}")
    lines.append(f"Candidate sets: singles={len(manifolds)}, total_ranked={len(candidates)}, max_combo_size={MAX_COMBO_SIZE}")
    if CASE_FILTER:
        lines.append(f"Case filter: {', '.join(CASE_FILTER)}")
    if ONLY_COMBO_CASES:
        lines.append("Case filter: expected_manifolds length > 1")
    lines.append(f"Cases loaded for this run: {len(cases)}")
    lines.append("")
    lines.append("Manifolds:")
    for label, manifold in manifolds.items():
        nonhaz = sum(1 for a in manifold["axes"].values() if a.get("category") != "derived_hazard")
        mechanisms = sum(1 for a in manifold["axes"].values() if a.get("category") == LATENT_MECHANISM_CATEGORY)
        lines.append(
            f"  {label:12s}: axes={nonhaz:2d}, mechanisms={mechanisms:2d}, "
            f"mech_edges={len(manifold.get('mechanism_edges', [])):2d}, "
            f"couplings={len(manifold['axis_couplings']):2d}, risk_factors={len(manifold['risk_factors']):2d}"
        )
    lines.append(f"Base-measure/background axes: {len(background_axes)}")
    lines.append("")

    total_single = total_combo = pass_single = pass_combo = 0
    for case in cases:
        expected = expected_tuple(case)
        if not expected or not set(expected).issubset(set(MANIFOLD_PATHS)):
            continue

        lines.append("-" * 100)
        lines.append(f"{case['case_id']}  expected={'+'.join(expected)}")
        lines.append(f"source: PMID {case.get('source_pmid')} / {case.get('source_pmcid')} / {case.get('source_url')}")
        lines.append(f"paper diagnosis: {case.get('disease_label_per_paper')}")
        lines.append(f"observed axes: {len(case['observations_by_axis'])}")
        if case.get("risk_context"):
            ctx = "; ".join(f"{r.get('factor')}={r.get('category')}" for r in case["risk_context"])
            lines.append(f"risk context: {ctx}")

        scores = []
        for cand in candidates:
            if not candidate_allowed_for_case(case, cand, manifolds):
                continue
            score = score_candidate(case, cand, manifolds, background_axes)
            if score is not None:
                scores.append(score)
        scores.sort(key=lambda s: -s["log_marginal"])
        best_overall = scores[0]
        single_scores = [s for s in scores if len(s["candidate_tuple"]) == 1]
        best_single = max(single_scores, key=lambda s: s["log_marginal"])
        background_null = score_background_null(case, background_axes)

        lines.append("")
        lines.append("[joint SDE ranking: all candidates]")
        for score in scores:
            marker = "*" if score is best_overall else " "
            anchor = ""
            if score["anchor_support"]:
                anchor = " anchors=" + ",".join(f"{k}:{v:.1f}" for k, v in score["anchor_support"].items())
            feasibility = ""
            if score.get("feasibility_reasons"):
                feasibility = " feasibility=" + "|".join(score["feasibility_reasons"])
            lines.append(
                f"{marker} {score['candidate']:23s} logP={score['log_marginal']:+10.2f} "
                f"mean={score['mean_log_per_axis']:+8.3f} n={score['n_axes']:2d} prior={score['log_prior']:+6.2f}{anchor}{feasibility}"
            )

        lines.append("")
        lines.append("[best single-manifold diagnostic]")
        for score in sorted(single_scores, key=lambda s: -s["log_marginal"]):
            marker = "*" if score is best_single else " "
            feasibility = ""
            if score.get("feasibility_reasons"):
                feasibility = " feasibility=" + "|".join(score["feasibility_reasons"])
            lines.append(
                f"{marker} {score['candidate']:12s} logP={score['log_marginal']:+10.2f} "
                f"mean={score['mean_log_per_axis']:+8.3f} prior={score['log_prior']:+6.2f}{feasibility}"
            )

        lines.append("")
        lines.append("[OOD/null-model check: known manifold(s) vs pure background]")
        if background_null is None:
            lines.append("  background_only: no scorable observed axes")
        else:
            delta_best = best_overall["log_marginal"] - background_null["log_marginal"]
            delta_single = best_single["log_marginal"] - background_null["log_marginal"]
            lines.append(
                f"  logP_best_known={best_overall['log_marginal']:+10.2f} "
                f"candidate={best_overall['candidate']}"
            )
            lines.append(
                f"  logP_best_single={best_single['log_marginal']:+10.2f} "
                f"candidate={best_single['candidate']}"
            )
            lines.append(
                f"  logP_background_only={background_null['log_marginal']:+10.2f} "
                f"mean={background_null['mean_log_per_axis']:+8.3f} n={background_null['n_axes']:2d}"
            )
            lines.append(f"  delta_to_null_best_known={delta_best:+10.2f}")
            lines.append(f"  delta_to_null_best_single={delta_single:+10.2f}")
            lines.append("  interpretation: runtime outputs deltas only; no hard unknown-disease threshold is applied.")

        if len(expected) == 1:
            total_single += 1
            ok = best_single["candidate_tuple"] == expected
            pass_single += int(ok)
            lines.append(f"single validation: best_single={best_single['candidate']}  {'PASS' if ok else 'FAIL'}")
        else:
            total_combo += 1
            ok = set(best_overall["candidate_tuple"]) == set(expected)
            pass_combo += int(ok)
            lines.append(f"combo validation: best_overall={best_overall['candidate']}  {'PASS' if ok else 'FAIL'}")

        best = best_overall["best"]
        if best:
            t_text = ", ".join(f"{k}=day{v:.1f}" for k, v in best["t_by_disease"].items())
            lines.append(f"best latent times: {t_text}")
            residuals = []
            for (axis_id, obs_value, unit, mu_value, source), x, m, sigma in zip(best["meta"], best["x"], best["mu"], best["sigmas"]):
                z = abs((x - m) / max(sigma, 1e-6))
                residuals.append((z, axis_id, obs_value, unit, mu_value, source))
            worst = sorted(residuals, reverse=True)[:5]
            lines.append("largest standardized residuals: " + "; ".join(
                f"{axis_id} obs={obs_value:g} {unit} mu={mu_value:g} via={source} z={z:.1f}"
                for z, axis_id, obs_value, unit, mu_value, source in worst
            ))
        lines.append("")

    lines.append("=" * 100)
    lines.append(f"Single-manifold validation: {pass_single}/{total_single} PASS")
    lines.append(f"Combo-manifold validation:  {pass_combo}/{total_combo} PASS")
    lines.append("")
    lines.append("Notes:")
    lines.append("  - This runtime consumes latent_mechanisms, scoring mechanism_edges, axis_couplings, and risk-factor modulation fields.")
    lines.append("  - mechanism_audit_origin edges are registry/audit evidence only and are not used as scoring gates.")
    lines.append("  - Pair candidates are two-disease vector-field superpositions, not labels emitted by the LLM.")
    lines.append("  - Opposing disease forces are combined in standardized axis space so a strong TTP platelet-consumption field is not canceled by weak AOSD reactive thrombocytosis.")
    lines.append("  - OOD/null-model check reports logP_best_known - logP_background_only; it deliberately does not apply a hard unknown-disease threshold.")
    lines.append("  - Culture/ADAMTS13-confirmatory axes are allowed if present in the case JSON; remove them from case evidence if testing presentation-only diagnosis.")
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)

    text = "\n".join(lines)
    RESULT_PATH.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n[done] wrote {RESULT_PATH}")


if __name__ == "__main__":
    main()
