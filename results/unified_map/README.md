# UCM result custody and transport

Each directory under `runs/` is append-only and identified by a unique run ID.
Its canonical `manifest.json` binds the **uncompressed** evidence bytes, including
`raw-episodes.jsonl` and `raw-pairs.jsonl`.

To keep the Codex desktop Git panel from indexing hundreds of thousands of JSONL
lines, new raw rows are transported as deterministic sidecars:

```text
raw-episodes.jsonl.gz
raw-pairs.jsonl.gz
```

The expanded `.jsonl` files remain available in the producing worktree but are
Git-ignored. `verify_run_bundle` first uses an expanded member when present; in
a clean clone it decompresses `<manifest-name>.gz` and validates the resulting
byte length and SHA-256 against the original canonical manifest. The gzip header
or compression ratio has no evidentiary authority; only the decompressed bytes
do.

Example verification:

```powershell
$py = 'C:\Users\wangw\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
@'
from pathlib import Path
from prototype.unified_map.benchmark_v1_runner import verify_run_bundle
verify_run_bundle(Path("results/unified_map/runs/20260719T063049Z-EXP-035-c28452cba8"))
print("verified")
'@ | & $py -
```

`redteam/`, `reproduction/` and `demo/` are small canonical JSON bundles and do
not use the gzip transport fallback.
