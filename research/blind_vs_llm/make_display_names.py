"""English display names for the LLM candidate list.

126 leaves carry `disease_name` in their distillation file. The other 58 only
have an id; their names below are the plain expansion of that id, written once
before any test case was seen.
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

ID_EXPANSION = {
    "D137": "Adult-onset Still's disease",
    "D-SEPSIS-GN": "Bacterial sepsis",
    "D-TTP": "Thrombotic thrombocytopenic purpura",
    "D-ACUTE-CHOLANGITIS": "Acute cholangitis",
    "D-AIHA": "Autoimmune hemolytic anemia",
    "D-ALCL": "Anaplastic large cell lymphoma",
    "D-AML": "Acute myeloid leukemia",
    "D-APL": "Acute promyelocytic leukemia",
    "D-BACTERIAL-MENINGITIS": "Bacterial meningitis",
    "D-BEHCET-DISEASE": "Behcet disease",
    "D-CAEBV": "Chronic active Epstein-Barr virus infection",
    "D-CANDIDEMIA": "Candidemia",
    "D-CATASTROPHIC-APS": "Catastrophic antiphospholipid syndrome",
    "D-CLOSTRIDIOIDES-DIFFICILE-SEVERE": "Severe Clostridioides difficile infection",
    "D-CMV-MONO": "Cytomegalovirus mononucleosis",
    "D-COVID19-ACUTE": "Acute COVID-19",
    "D-DIC": "Disseminated intravascular coagulation",
    "D-DISSEMINATED-GONOCOCCAL-INFECTION": "Disseminated gonococcal infection",
    "D-DLBCL": "Diffuse large B-cell lymphoma",
    "D-DRUG-FEVER-DRESS": "Drug reaction with eosinophilia and systemic symptoms (DRESS)",
    "D-EGPA": "Eosinophilic granulomatosis with polyangiitis",
    "D-GCA": "Giant cell arteritis",
    "D-GPA": "Granulomatosis with polyangiitis",
    "D-HISTOPLASMOSIS-DISSEMINATED": "Disseminated histoplasmosis",
    "D-HLH-MAS": "Hemophagocytic lymphohistiocytosis / macrophage activation syndrome",
    "D-HODGKIN-LYMPHOMA": "Hodgkin lymphoma",
    "D-IGG4-RELATED-DISEASE": "IgG4-related disease",
    "D-INFECTIOUS-MONONUCLEOSIS": "Infectious mononucleosis",
    "D-INFECTIVE-ENDOCARDITIS": "Infective endocarditis",
    "D-INFLUENZA": "Influenza",
    "D-INVASIVE-ASPERGILLOSIS": "Invasive aspergillosis",
    "D-IVLBCL": "Intravascular large B-cell lymphoma",
    "D-LEGIONELLA-PNEUMONIA": "Legionella pneumonia",
    "D-LEPTOSPIROSIS": "Leptospirosis",
    "D-MALARIA-FALCIPARUM": "Plasmodium falciparum malaria",
    "D-MENINGOCOCCEMIA": "Meningococcemia",
    "D-MIS-A": "Multisystem inflammatory syndrome in adults",
    "D-MPA": "Microscopic polyangiitis",
    "D-MYCOPLASMA-PNEUMONIA": "Mycoplasma pneumonia",
    "D-NECROTIZING-FASCIITIS": "Necrotizing fasciitis",
    "D-NONTYPHOID-SALMONELLA-BACTEREMIA": "Nontyphoidal Salmonella bacteremia",
    "D-ORBITAL-CELLULITIS": "Orbital cellulitis",
    "D-PAN": "Polyarteritis nodosa",
    "D-PJP-PNEUMONIA": "Pneumocystis jirovecii pneumonia",
    "D-PLACENTAL-ABRUPTION": "Placental abruption",
    "D-PNEUMOCOCCAL-PNEUMONIA": "Pneumococcal pneumonia",
    "D-PYELONEPHRITIS": "Pyelonephritis",
    "D-PYOGENIC-LIVER-ABSCESS": "Pyogenic liver abscess",
    "D-RELAPSING-POLYCHONDRITIS": "Relapsing polychondritis",
    "D-RICKETTSIOSIS-SCRUB-TYPHUS": "Scrub typhus",
    "D-SARCOIDOSIS": "Sarcoidosis",
    "D-SEPTIC-ARTHRITIS": "Septic arthritis",
    "D-SJOGREN-SYSTEMIC": "Sjogren disease with systemic involvement",
    "D-SLE-FLARE": "Systemic lupus erythematosus flare",
    "D-STAPH-AUREUS-BACTEREMIA": "Staphylococcus aureus bacteremia",
    "D-TAKAYASU-ARTERITIS": "Takayasu arteritis",
    "D-TB-DISSEMINATED": "Disseminated tuberculosis",
    "D-TOXIC-SHOCK-SYNDROME": "Toxic shock syndrome",
    # disease_name is Japanese only
    "D-PREECLAMPSIA-ECLAMPSIA": "Preeclampsia / eclampsia",
}


def main():
    atlas = json.loads((HERE / "frozen" / "atlas.json").read_text(encoding="utf-8"))
    names = {}
    for r in atlas:
        name = r["disease_name_en"]
        if name == r["disease_id"] or r["disease_id"] in ID_EXPANSION:
            name = ID_EXPANSION[r["disease_id"]]
        if not name.isascii():
            ascii_parts = [part for part in name.split(" / ") if part.isascii()]
            name = ascii_parts[0] if ascii_parts else name
        names[r["disease_id"]] = name
    (HERE / "frozen" / "display_names_en.json").write_text(json.dumps(names, ensure_ascii=False, indent=1), encoding="utf-8")
    non_ascii = {k: v for k, v in names.items() if not v.isascii()}
    print(f"{len(names)} names; non-ascii left: {non_ascii}")


if __name__ == "__main__":
    main()
