"""
V5 蒸馏 UI 本地 server (双击 start_ui.bat 启动)

  http://localhost:8765/  -> v5_layer3_prompt_ui.html
  POST /save              -> 写到 distillations/v5_<ID>.json
  GET  /master_axes.json  -> 给 UI 注入 (没文件返回空)
  GET  /list_distillations -> 已蒸列表
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import threading
import webbrowser

ROOT = Path(__file__).parent.resolve()
DISTILL_DIR = ROOT / "distillations"
DISTILL_DIR.mkdir(exist_ok=True)
MASTER_PATH = ROOT / "master_axes.json"
PORT = 8765


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
                "synonyms": [],
                "seen_in": [],
            })
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


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(200, "text/plain", "")

    def do_GET(self):
        if self.path in ("/", "/ui", "/ui.html"):
            ui = ROOT / "v5_layer3_prompt_ui.html"
            self._send(200, "text/html; charset=utf-8", ui.read_bytes())
        elif self.path == "/ping":
            self._send(200, "application/json; charset=utf-8", '{"ok":true}')
        elif self.path == "/master_axes.json":
            mp = ROOT / "master_axes.json"
            if mp.exists():
                self._send(200, "application/json; charset=utf-8", mp.read_bytes())
            else:
                self._send(200, "application/json; charset=utf-8", '{"axes": []}')
        elif self.path == "/list_distillations":
            files = sorted(p.name for p in DISTILL_DIR.glob("v5_*.json"))
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(files, ensure_ascii=False))
        else:
            self._send(404, "text/plain", "not found")

    def do_POST(self):
        if self.path != "/save":
            self._send(404, "text/plain", "not found")
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
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
