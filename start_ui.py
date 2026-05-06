"""
V5 蒸馏 UI 本地 server (双击 start_ui.bat 启动)

  http://localhost:8765/  -> v5_layer3_prompt_ui.html
  POST /save              -> 写到 distillations/v5_<ID>.json
  GET  /master_axes.json  -> 给 UI 注入 (没文件返回空)
  GET  /list_distillations -> 已蒸列表
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser

ROOT = Path(__file__).parent.resolve()
DISTILL_DIR = ROOT / "distillations"
DISTILL_DIR.mkdir(exist_ok=True)
CASE_DIR = DISTILL_DIR / "cases"
CASE_DIR.mkdir(exist_ok=True)
MASTER_PATH = ROOT / "master_axes.json"
ROADMAP_PATH = DISTILL_DIR / "disease_leaf_atlas_roadmap_200.md"
PORT = 8765


DISEASE_NAME_OVERRIDES = {
    "D137": "Adult-onset Still's disease",
    "D-SEPSIS-GN": "Bacterial sepsis",
    "D-TTP": "Thrombotic thrombocytopenic purpura",
    "D-HLH-MAS": "Hemophagocytic lymphohistiocytosis / macrophage activation syndrome",
    "D-SLE-FLARE": "Systemic lupus erythematosus flare",
    "D-TB-DISSEMINATED": "Disseminated tuberculosis",
    "D-INFECTIVE-ENDOCARDITIS": "Infective endocarditis",
    "D-MPA": "Microscopic polyangiitis",
    "D-GPA": "Granulomatosis with polyangiitis",
    "D-EGPA": "Eosinophilic granulomatosis with polyangiitis",
    "D-DRUG-FEVER-DRESS": "Drug reaction with eosinophilia and systemic symptoms",
    "D-INFECTIOUS-MONONUCLEOSIS": "Infectious mononucleosis",
    "D-MIS-A": "Multisystem inflammatory syndrome in adults",
    "D-LEPTOSPIROSIS": "Leptospirosis",
    "D-HODGKIN-LYMPHOMA": "Hodgkin lymphoma",
    "D-DLBCL": "Diffuse large B-cell lymphoma",
    "D-ALCL": "Anaplastic large-cell lymphoma",
    "D-IVLBCL": "Intravascular large B-cell lymphoma",
    "D-COVID19-ACUTE": "Acute COVID-19",
    "D-INFLUENZA": "Influenza",
    "D-MYCOPLASMA-PNEUMONIA": "Mycoplasma pneumoniae pneumonia",
    "D-PNEUMOCOCCAL-PNEUMONIA": "Pneumococcal pneumonia",
    "D-LEGIONELLA-PNEUMONIA": "Legionella pneumonia",
    "D-PYELONEPHRITIS": "Pyelonephritis",
    "D-ACUTE-CHOLANGITIS": "Acute cholangitis",
    "D-BACTERIAL-MENINGITIS": "Acute bacterial meningitis",
    "D-IGG4-RELATED-DISEASE": "IgG4-related disease",
    "D-SARCOIDOSIS": "Sarcoidosis",
    "D-SJOGREN-SYSTEMIC": "Systemic Sjogren disease",
    "D-TOXIC-SHOCK-SYNDROME": "Toxic shock syndrome",
    "D-MENINGOCOCCEMIA": "Meningococcemia",
    "D-NECROTIZING-FASCIITIS": "Necrotizing fasciitis",
    "D-TAKAYASU-ARTERITIS": "Takayasu arteritis",
    "D-BEHCET-DISEASE": "Behcet disease",
    "D-PYOGENIC-LIVER-ABSCESS": "Pyogenic liver abscess",
    "D-PJP-PNEUMONIA": "Pneumocystis jirovecii pneumonia",
    "D-CANDIDEMIA": "Candidemia",
    "D-INVASIVE-ASPERGILLOSIS": "Invasive aspergillosis",
    "D-ACUTE-HIV": "Acute HIV retroviral syndrome",
    "D-CMV-MONO": "Cytomegalovirus mononucleosis-like illness",
    "D-BRUCELLOSIS": "Brucellosis",
    "D-Q-FEVER": "Q fever",
    "D-RICKETTSIOSIS-SCRUB-TYPHUS": "Scrub typhus / rickettsiosis",
    "D-MALARIA-FALCIPARUM": "Plasmodium falciparum malaria",
    "D-AML": "Acute myeloid leukemia",
    "D-APL": "Acute promyelocytic leukemia",
    "D-STAPH-AUREUS-BACTEREMIA": "Staphylococcus aureus bacteremia",
    "D-NOCARDIOSIS": "Nocardiosis",
    "D-BARTONELLA-ENDOCARDITIS": "Bartonella infective endocarditis",
}


TOP_LEVEL_ARRAYS = [
    "latent_mechanisms",
    "mechanism_edges",
    "axes",
    "axis_couplings",
    "treatments",
    "risk_factors",
    "supportive_care",
]


def normalize_distillation(obj):
    for key in TOP_LEVEL_ARRAYS:
        if not isinstance(obj.get(key), list):
            obj[key] = []
    return obj


def build_master_axes():
    """扫 distillations/ 累积所有 axes (含 disease-specific hazard 也保留作记录),
    写到 master_axes.json. 蒸下一个病时 UI fetch 这个文件注入 prompt."""
    all_axes = {}
    for jp in sorted(DISTILL_DIR.glob("v5_*.json")):
        try:
            d = json.loads(jp.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [warn] skip {jp.name}: {e}")
            continue
        disease_id = (d.get("disease") or jp.stem).strip()
        axes = list(d.get("axes", []) or [])
        for m in d.get("latent_mechanisms", []) or []:
            axis_id = m.get("mechanism_id") or m.get("axis_id") or m.get("id")
            if not axis_id:
                continue
            axis = dict(m)
            axis["axis_id"] = axis_id
            axis["category"] = "latent_mechanism"
            axis.setdefault("unit", "relative_activity_0_1")
            axis.setdefault("log_scale", False)
            axes.append(axis)
        for a in axes:
            aid = a.get("axis_id")
            if not aid:
                continue
            cat = a.get("category")
            # disease-specific hazard 不进 master (mortality_hazard_in_X 是 per-disease)
            if cat == "derived_hazard":
                continue
            entry = all_axes.setdefault(aid, {
                "axis_id": aid,
                "category": cat,
                "unit": a.get("unit"),
                "log_scale": a.get("log_scale"),
                "axis_role": a.get("axis_role"),
                "parent_axis_id": a.get("parent_axis_id"),
                "synonyms": [],
                "seen_in": [],
            })
            for meta_key in ("axis_role", "parent_axis_id"):
                if not entry.get(meta_key) and a.get(meta_key):
                    entry[meta_key] = a.get(meta_key)
            if disease_id not in entry["seen_in"]:
                entry["seen_in"].append(disease_id)
    master = {
        "version": 0,
        "note": "Auto-extracted from distillations/. Reuse axis_id; propose new only for novel concepts.",
        "axes": sorted(all_axes.values(), key=lambda x: x["axis_id"]),
    }
    MASTER_PATH.write_text(json.dumps(master, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [master_axes] {len(master['axes'])} axes -> {MASTER_PATH.name}")
    return master


def _roadmap_key(disease_id):
    key = disease_id.lower()
    if key.startswith("d-"):
        key = key[2:]
    key = re.sub(r"[^a-z0-9]+", "_", key).strip("_")
    return f"roadmap_{key}"


def _distilled_key(disease_id):
    return _roadmap_key(disease_id).replace("roadmap_", "distilled_", 1)


def disease_display_name(disease_id, data=None):
    data = data or {}
    for key in ("disease_name", "diseaseName", "display_name", "name"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return DISEASE_NAME_OVERRIDES.get(disease_id, disease_id)


def list_distilled_presets():
    items = []
    for jp in sorted(DISTILL_DIR.glob("v5_*.json")):
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        disease_id = (data.get("disease") or jp.stem.replace("v5_", "", 1)).strip()
        if not disease_id:
            continue
        items.append({
            "key": _distilled_key(disease_id),
            "diseaseId": disease_id,
            "diseaseName": disease_display_name(disease_id, data),
            "group": "Already distilled",
            "file": jp.name,
            "axes": len(data.get("axes") or []),
            "latentMechanisms": len(data.get("latent_mechanisms") or []),
            "treatments": len(data.get("treatments") or []),
        })
    return items


def expected_manifolds_for_case(case):
    expected = case.get("expected_manifolds")
    if isinstance(expected, list):
        return [str(x) for x in expected if x]
    expected = case.get("expected_manifold")
    if expected:
        return [str(expected)]
    return []


def case_summary_from_file(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    observations = data.get("observations") or []
    trajectories = data.get("lab_trajectories") or []
    summary = data.get("presentation_summary") or data.get("presenting_symptoms") or []
    if isinstance(summary, str):
        summary = [summary]
    confirmatory = data.get("confirmatory_findings") or []
    risk_context = data.get("risk_context") or []
    case_id = data.get("case_id") or path.stem.replace("v5_case_", "", 1)
    return {
        "case_id": case_id,
        "file": path.name,
        "expected_manifolds": expected_manifolds_for_case(data),
        "source_pmid": data.get("source_pmid"),
        "source_pmcid": data.get("source_pmcid"),
        "source_url": data.get("source_url"),
        "disease_label_per_paper": data.get("disease_label_per_paper"),
        "demographics": data.get("demographics") or {},
        "observation_count": len(observations),
        "trajectory_count": len(trajectories),
        "risk_context_count": len(risk_context),
        "confirmatory_count": len(confirmatory),
        "summary_preview": " ".join(str(x) for x in summary[:2])[:300],
    }


def list_case_summaries():
    items = []
    for path in sorted(CASE_DIR.glob("v5_case_*.json")):
        try:
            items.append(case_summary_from_file(path))
        except Exception as e:
            items.append({"case_id": path.stem, "file": path.name, "error": str(e)})
    return items


def find_case_path(case_id):
    safe_id = sanitize_case_id(case_id)
    exact = CASE_DIR / f"v5_case_{safe_id}.json"
    if exact.exists():
        return exact
    for path in CASE_DIR.glob("v5_case_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("case_id") == case_id:
            return path
    return None


def sanitize_case_id(case_id):
    case_id = (case_id or "").strip()
    if not case_id:
        raise ValueError("case_id is required")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", case_id).strip("_")
    if not safe:
        raise ValueError(f"invalid case_id: {case_id!r}")
    return safe


def save_case_json(case_obj):
    if not isinstance(case_obj, dict):
        raise ValueError("case JSON must be an object")
    case_id = case_obj.get("case_id")
    safe_id = sanitize_case_id(case_id)
    if not expected_manifolds_for_case(case_obj):
        raise ValueError("case JSON needs expected_manifold or expected_manifolds")
    if not case_obj.get("source_pmid") and not case_obj.get("source_pmcid") and not case_obj.get("source_url"):
        raise ValueError("case JSON needs PMID, PMCID, or source_url")
    if not isinstance(case_obj.get("observations"), list) and not isinstance(case_obj.get("lab_trajectories"), list):
        raise ValueError("case JSON needs observations or lab_trajectories")
    outpath = CASE_DIR / f"v5_case_{safe_id}.json"
    outpath.write_text(json.dumps(case_obj, indent=2, ensure_ascii=False), encoding="utf-8")
    return outpath


def run_case_test(payload):
    payload = payload or {}
    max_combo_size = int(payload.get("maxComboSize", 1))
    max_combo_size = 2 if max_combo_size >= 2 else 1
    n_mc = int(payload.get("nMc", 80))
    n_mc = max(1, min(n_mc, 5000))
    case_filter = str(payload.get("caseFilter", "") or "").strip()
    only_combo = bool(payload.get("onlyComboCases", False))

    env = dict(**os.environ)
    env["VESMED_MAX_COMBO_SIZE"] = str(max_combo_size)
    env["VESMED_N_MC"] = str(n_mc)
    if case_filter:
        env["VESMED_CASE_FILTER"] = case_filter
    else:
        env.pop("VESMED_CASE_FILTER", None)
    if only_combo:
        env["VESMED_ONLY_COMBO_CASES"] = "1"
    else:
        env.pop("VESMED_ONLY_COMBO_CASES", None)

    result = subprocess.run(
        [sys.executable, "v5_joint_sde_case_test.py"],
        cwd=str(ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=900,
    )
    text = (result.stdout or "") + (("\n[stderr]\n" + result.stderr) if result.stderr else "")
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "output": text,
        "result_path": "distillations/joint_sde_case_test_result.txt",
        "settings": {
            "maxComboSize": max_combo_size,
            "nMc": n_mc,
            "caseFilter": case_filter,
            "onlyComboCases": only_combo,
        },
    }


def parse_roadmap_presets():
    """Read the roadmap markdown and expose disease-leaf candidates to the UI.

    The current atlas audit table is intentionally ignored; only the "Next 20"
    and candidate-pool sections are selectable roadmap presets.
    """
    if not ROADMAP_PATH.exists():
        return []

    section_group = None
    items = []
    seen = set()
    candidate_sections = {
        "Infection",
        "Rheumatology / Autoinflammatory",
        "Hematology / Oncology / TMA",
        "Drug / Toxicology / Endocrine / Critical Mimics",
    }

    for raw_line in ROADMAP_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            section_group = "Next 20 high-priority" if line.startswith("## Next 20") else None
            continue
        if line.startswith("### "):
            title = line[4:].strip()
            section_group = title if title in candidate_sections else None
            continue
        if not section_group or not line.startswith("|"):
            continue

        cells = [c.strip() for c in line.strip("|").split("|")]
        disease_id = disease_name = None
        if len(cells) >= 3 and cells[0].isdigit():
            disease_id, disease_name = cells[1], cells[2]
        elif len(cells) >= 2:
            disease_id, disease_name = cells[0], cells[1]
        if not disease_id or not disease_name:
            continue
        if not (disease_id.startswith("D-") or disease_id == "D137"):
            continue
        if disease_id in seen:
            continue
        seen.add(disease_id)
        items.append({
            "key": _roadmap_key(disease_id),
            "diseaseId": disease_id,
            "diseaseName": disease_name,
            "group": section_group,
        })
    return items


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(200, "text/plain", "")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/ui", "/ui.html"):
            ui = ROOT / "v5_layer3_prompt_ui.html"
            self._send(200, "text/html; charset=utf-8", ui.read_bytes())
        elif path in ("/case_test_ui.html", "/case_test", "/cases"):
            ui = ROOT / "case_test_ui.html"
            if ui.exists():
                self._send(200, "text/html; charset=utf-8", ui.read_bytes())
            else:
                self._send(404, "text/plain", "case_test_ui.html not found")
        elif path == "/ping":
            self._send(200, "application/json; charset=utf-8", '{"ok":true}')
        elif path == "/master_axes.json":
            mp = ROOT / "master_axes.json"
            if mp.exists():
                self._send(200, "application/json; charset=utf-8", mp.read_bytes())
            else:
                self._send(200, "application/json; charset=utf-8", '{"axes": []}')
        elif path == "/list_distillations":
            files = sorted(p.name for p in DISTILL_DIR.glob("v5_*.json"))
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(files, ensure_ascii=False))
        elif path == "/distilled_presets":
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(list_distilled_presets(), ensure_ascii=False))
        elif path == "/roadmap_presets":
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(parse_roadmap_presets(), ensure_ascii=False))
        elif path == "/case_cases":
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(list_case_summaries(), ensure_ascii=False))
        elif path == "/case_detail":
            query = parse_qs(parsed.query)
            case_id = (query.get("case_id") or [""])[0]
            path_obj = find_case_path(case_id)
            if not path_obj:
                self._send(404, "application/json; charset=utf-8",
                           json.dumps({"ok": False, "error": "case not found"}, ensure_ascii=False))
                return
            self._send(200, "application/json; charset=utf-8", path_obj.read_bytes())
        else:
            self._send(404, "text/plain", "not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path not in ("/save", "/save_case", "/run_case_test"):
            self._send(404, "text/plain", "not found")
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        if path == "/save_case":
            try:
                obj = json.loads(raw)
                outpath = save_case_json(obj)
                rel = outpath.relative_to(ROOT).as_posix()
                print(f"  [save case] {rel}  ({len(raw)} bytes)")
                self._send(200, "application/json; charset=utf-8",
                           json.dumps({"ok": True, "path": rel}, ensure_ascii=False))
            except Exception as e:
                self._send(400, "application/json; charset=utf-8",
                           json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                print(f"  [save case ERROR] {e}")
            return
        if path == "/run_case_test":
            try:
                payload = json.loads(raw or "{}")
                result = run_case_test(payload)
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(result, ensure_ascii=False))
            except Exception as e:
                self._send(500, "application/json; charset=utf-8",
                           json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                print(f"  [case test ERROR] {e}")
            return
        try:
            obj = json.loads(raw)
            obj = normalize_distillation(obj)
            disease_id = (obj.get("disease") or "").strip()
            if not disease_id:
                raise ValueError("缺 'disease' 字段")
            safe = all(c.isalnum() or c in "-_" for c in disease_id)
            if not safe:
                raise ValueError(f"非法 disease id: {disease_id!r}")
            outpath = DISTILL_DIR / f"v5_{disease_id}.json"
            outpath.write_text(json.dumps(obj, indent=2, ensure_ascii=False),
                               encoding="utf-8")
            rel = outpath.relative_to(ROOT).as_posix()
            print(f"  [save] {rel}  ({len(raw)} bytes)")
            # 自动 update master_axes registry
            master = build_master_axes()
            self._send(200, "application/json; charset=utf-8",
                       json.dumps({"ok": True, "path": rel,
                                   "master_axes_count": len(master["axes"])},
                                  ensure_ascii=False))
        except Exception as e:
            self._send(400, "application/json; charset=utf-8",
                       json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            print(f"  [save ERROR] {e}")

    def log_message(self, fmt, *args):
        return  # 静音 GET log


def main():
    # 启动时 build 一次 master_axes (扫已有 distillations/)
    print("=" * 60)
    build_master_axes()
    server = ThreadingHTTPServer(("localhost", PORT), Handler)
    url = f"http://localhost:{PORT}/"
    print(f"V5 蒸馏 UI  ->  {url}")
    print(f"保存目录    ->  {DISTILL_DIR}")
    print("Ctrl+C 退出")
    print("=" * 60)
    threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[exit]")


if __name__ == "__main__":
    main()
