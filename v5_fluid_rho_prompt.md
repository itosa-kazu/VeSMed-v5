# v5 流体架構 PoC --- GMM density prompt

## 使用説明

**推奨 LLM**

GPT-5、Claude Opus 4、Gemini 1.5 Ultra を試す。同一疾患を 3-5 回独立実行して比較する:
- 選択された軸が一致するか? 一致率が高ければ臨床的根拠が強い
- K_axes と K_d の範囲が安定しているか? 毎回大きく変わる場合は亜型分類自体が不確実
- 成分の mu 区間が合理的か? 区間が過大なら文献確認が必要

**疾患の置換方法**

prompt 内の {DISEASE_NAME} と {DISEASE_ID} を目標疾患に置換する。例:
- {DISEASE_NAME} -> Adult-onset Stills disease (AOSD)
- {DISEASE_ID} -> D137

**実行後チェックリスト**

1. K_axes の妥当性: 軸数が臨床的に解釈可能か。15 超はまず冷僻指標混入を疑う
2. 相関行列の正定性: 第 4 節の higham_psd() で各成分の corr を検査する
3. LLM 横断安定性: 3 回出力の軸リストと区間を比較し、主要軸が安定して現れるか確認する

---

## 主体 Prompt

```text
ROLE
----
You are a senior clinical expert combining the expertise of a rheumatologist, general internist,
and Bayesian statistician. You are building a probabilistic disease model for VeSMed v5, which
represents diseases as Gaussian Mixture Models (GMMs) over a continuous clinical feature space.

TASK
----
For the disease {DISEASE_NAME} (ID: {DISEASE_ID}), produce a complete GMM specification with:
  1. A set of continuous clinical axes (you decide how many and which ones).
  2. rho_disease: a GMM over those axes for patients WITH {DISEASE_NAME}.
  3. rho_healthy: a GMM over the SAME axes for healthy adults.

Both distributions MUST share the exact same axes array (same order, same units).
This is required because the diagnostic likelihood ratio LR(x) = rho_disease(x) / rho_healthy(x)
requires both densities defined on the same domain.

STEP 1: CLINICAL REASONING (write approximately 250 words before the JSON)
-------------------------------------------------------------------------
Reason through the following before producing JSON:

(a) Phenotypic subgroups: Does {DISEASE_NAME} have recognized clinical subtypes or phenotypic
    clusters? Describe each briefly. Each major subtype corresponds to one GMM component in
    rho_disease.

(b) Axis selection: Which continuous or ordinal clinical measurements best distinguish
    {DISEASE_NAME} from healthy individuals and from key differential diagnoses? Consider labs,
    vital signs, scoring tools, quantitative imaging. For each axis you plan to include, state
    the diagnostic rationale and cite a PMID if available. Prefer axes routinely obtainable in
    standard clinical settings.

(c) Within-subtype correlations: Which axis pairs are expected to be strongly correlated within
    each subtype, and what is the clinical mechanism?

(d) Disease vs. healthy separation: Which axes separate {DISEASE_NAME} from healthy most clearly?
    Which overlap substantially with healthy adults?

After completing this reasoning, output the JSON in STEP 2.

STEP 2: JSON OUTPUT
-------------------
Output a single JSON object in a code block labeled with triple-backtick json.

Schema:
{
  "disease_id": string,
  "disease_name": string,
  "axes": [
    {
      "index": integer,
      "name": string,
      "unit": string,
      "type": "continuous | ordinal | log-scale",
      "diagnostic_value": string,
      "rationale_pmid": string
    }
  ],
  "rho_disease": {
    "type": "GMM",
    "components": [
      {
        "component_id": integer,
        "subtype_label": string,
        "weight": [lo, hi],
        "mu": [[lo, hi], ...],
        "sigma": [[lo, hi], ...],
        "corr": [[[lo, hi], ...], ...]
      }
    ]
  },
  "rho_healthy": {
    "type": "GMM",
    "components": [
      {
        "component_id": integer,
        "subtype_label": "healthy_adult",
        "weight": [lo, hi],
        "mu": [[lo, hi], ...],
        "sigma": [[lo, hi], ...],
        "corr": [[[lo, hi], ...], ...]
      }
    ]
  }
}

Array sizes:
- axes: K_axes entries (your choice of K_axes)
- mu, sigma: K_axes entries each, same ordering as axes array
- corr: K_axes x K_axes matrix of [lo, hi] intervals; diagonal must be [1.0, 1.0]
- rho_disease components: K_d entries (your choice; one per subtype)
- rho_healthy components: K_h entries (typically 1; your choice)

CONSTRAINTS
-----------
1. sigma_i > 0 for all axes i (both distributions)
2. -1.0 <= corr_ij_lo <= corr_ij_hi <= 1.0 for all off-diagonal pairs
3. Diagonal entries corr_ii = [1.0, 1.0]
4. Weight midpoints should sum to approximately 1.0 per distribution (post-processing normalizes)
5. Axes must be continuous or ordinal; avoid pure binary axes unless the measurement is an
   inherently graded clinical scale with no finer subdivision
6. rho_healthy MUST use exactly the same axes array as rho_disease (same K_axes, same order)
7. GMM components for rho_disease must cover both typical AND atypical presentations
8. When recalling a specific study or guideline, output its PMID in rationale_pmid;
   otherwise use the string "LLM_MEMORY"

OUTPUT FORMAT
-------------
1. The clinical reasoning (~250 words, plain prose, no JSON)
2. One triple-backtick json code block with the complete JSON object described above
3. Nothing else after the closing fence
```

---

## JSON 示例 (ILLUSTRATIVE EXAMPLE --- do not trust numbers)

AOSD D137 の完全な JSON 例。数値は説明用で文献根拠なし。

```json
{
  "disease_id": "D137",
  "disease_name": "Adult-onset Stills disease (AOSD)",
  "axes": [
    {
      "index": 0,
      "name": "血清フェリチン (log10)",
      "unit": "log10(ng/mL)",
      "type": "log-scale",
      "diagnostic_value": "AOSD では著明高値 (>10000 ng/mL) が特徴的; Yamaguchi 基準の補助所見",
      "rationale_pmid": "10469584"
    },
    {
      "index": 1,
      "name": "白血球数",
      "unit": "1e9/L",
      "type": "continuous",
      "diagnostic_value": "好中球優位白血球増多は活動期 AOSD の主要所見",
      "rationale_pmid": "LLM_MEMORY"
    },
    {
      "index": 2,
      "name": "関節炎スコア",
      "unit": "none",
      "type": "ordinal",
      "diagnostic_value": "全身型 vs 関節型の亜型分類に直結",
      "rationale_pmid": "LLM_MEMORY"
    },
    {
      "index": 3,
      "name": "CRP",
      "unit": "mg/dL",
      "type": "continuous",
      "diagnostic_value": "炎症マーカー; フェリチンとの乖離が診断の手がかり",
      "rationale_pmid": "LLM_MEMORY"
    },
    {
      "index": 4,
      "name": "体温ピーク値",
      "unit": "degrees_C",
      "type": "continuous",
      "diagnostic_value": "毎日 1-2 回の弛張熱が典型; 39C 以上が多い",
      "rationale_pmid": "LLM_MEMORY"
    }
  ],
  "rho_disease": {
    "type": "GMM",
    "components": [
      {
        "component_id": 0,
        "subtype_label": "systemic_AOSD",
        "weight": [0.55, 0.70],
        "mu": [[3.8, 4.3], [14.0, 20.0], [0.5, 1.5], [8.0, 15.0], [39.2, 40.0]],
        "sigma": [[0.3, 0.6], [3.0, 6.0], [0.5, 1.0], [3.0, 6.0], [0.4, 0.7]],
        "corr": [
          [[1.0, 1.0], [0.3, 0.6], [-0.2, 0.1], [0.4, 0.7], [0.2, 0.5]],
          [[0.3, 0.6], [1.0, 1.0], [-0.3, 0.0], [0.3, 0.6], [0.1, 0.4]],
          [[-0.2, 0.1], [-0.3, 0.0], [1.0, 1.0], [-0.1, 0.2], [-0.1, 0.2]],
          [[0.4, 0.7], [0.3, 0.6], [-0.1, 0.2], [1.0, 1.0], [0.2, 0.5]],
          [[0.2, 0.5], [0.1, 0.4], [-0.1, 0.2], [0.2, 0.5], [1.0, 1.0]]
        ]
      },
      {
        "component_id": 1,
        "subtype_label": "articular_AOSD",
        "weight": [0.25, 0.40],
        "mu": [[2.8, 3.5], [10.0, 15.0], [2.5, 3.5], [5.0, 10.0], [38.2, 39.2]],
        "sigma": [[0.3, 0.6], [2.0, 5.0], [0.5, 1.0], [2.0, 5.0], [0.4, 0.7]],
        "corr": [
          [[1.0, 1.0], [0.2, 0.5], [0.2, 0.5], [0.3, 0.6], [0.1, 0.4]],
          [[0.2, 0.5], [1.0, 1.0], [0.1, 0.4], [0.3, 0.6], [0.1, 0.4]],
          [[0.2, 0.5], [0.1, 0.4], [1.0, 1.0], [0.1, 0.4], [0.0, 0.3]],
          [[0.3, 0.6], [0.3, 0.6], [0.1, 0.4], [1.0, 1.0], [0.2, 0.5]],
          [[0.1, 0.4], [0.1, 0.4], [0.0, 0.3], [0.2, 0.5], [1.0, 1.0]]
        ]
      }
    ]
  },
  "rho_healthy": {
    "type": "GMM",
    "components": [
      {
        "component_id": 0,
        "subtype_label": "healthy_adult",
        "weight": [1.0, 1.0],
        "mu": [[2.0, 2.3], [5.0, 8.0], [0.0, 0.2], [0.1, 0.5], [36.5, 37.0]],
        "sigma": [[0.1, 0.2], [1.0, 2.0], [0.1, 0.3], [0.05, 0.2], [0.2, 0.4]],
        "corr": [
          [[1.0, 1.0], [0.0, 0.2], [-0.1, 0.1], [0.1, 0.3], [0.0, 0.2]],
          [[0.0, 0.2], [1.0, 1.0], [-0.1, 0.1], [0.0, 0.2], [0.0, 0.2]],
          [[-0.1, 0.1], [-0.1, 0.1], [1.0, 1.0], [-0.1, 0.1], [-0.1, 0.1]],
          [[0.1, 0.3], [0.0, 0.2], [-0.1, 0.1], [1.0, 1.0], [0.0, 0.2]],
          [[0.0, 0.2], [0.0, 0.2], [-0.1, 0.1], [0.0, 0.2], [1.0, 1.0]]
        ]
      }
    ]
  }
}
```

---

## 後処理 Python コード

```python
import json
import numpy as np
from typing import Any


def extract_midpoints(interval_list: list) -> np.ndarray:
    '''Convert nested list of [lo, hi] intervals to midpoint array.'''
    arr = np.array(interval_list, dtype=float)
    return (arr[..., 0] + arr[..., 1]) / 2.0


def higham_psd(corr: np.ndarray, n_iter: int = 200, tol: float = 1e-8) -> np.ndarray:
    '''Nearest positive semi-definite correlation matrix via Higham 2002
    alternating projections with Dykstra correction.'''
    Y = corr.copy()
    delta_S = np.zeros_like(corr)
    for _ in range(n_iter):
        R = Y - delta_S
        eigvals, eigvecs = np.linalg.eigh(R)
        eigvals_clipped = np.maximum(eigvals, 0.0)
        X = eigvecs @ np.diag(eigvals_clipped) @ eigvecs.T
        delta_S = X - R
        prev_Y = Y.copy()
        Y = X.copy()
        np.fill_diagonal(Y, 1.0)
        if np.linalg.norm(Y - prev_Y, "fro") < tol:
            break
    Y = (Y + Y.T) / 2.0
    np.fill_diagonal(Y, 1.0)
    return Y


def normalize_weights(raw_weight_mids: list) -> list:
    '''Normalize a list of weight midpoints to sum to 1.'''
    arr = np.array(raw_weight_mids, dtype=float)
    total = arr.sum()
    if total == 0:
        return (np.ones_like(arr) / len(arr)).tolist()
    return (arr / total).tolist()


def process_component(comp: dict) -> dict:
    '''Extract midpoints and apply PSD projection to a single GMM component.'''
    mu = extract_midpoints(comp["mu"]).tolist()
    sigma = extract_midpoints(comp["sigma"]).tolist()
    corr_mid = extract_midpoints(comp["corr"])
    corr_psd = higham_psd(corr_mid)
    return {
        "component_id": comp["component_id"],
        "subtype_label": comp["subtype_label"],
        "weight_mid": float(extract_midpoints(comp["weight"])),
        "mu": mu,
        "sigma": sigma,
        "corr": corr_psd.tolist(),
    }


def process_gmm(gmm: dict) -> dict:
    '''Process all components; returns cleaned GMM with normalized weights.'''
    components = [process_component(c) for c in gmm["components"]]
    weight_mids = [c["weight_mid"] for c in components]
    normalized = normalize_weights(weight_mids)
    for c, nw in zip(components, normalized):
        c["weight_normalized"] = float(nw)
    return {"type": "GMM", "components": components}


def main():
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "output.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    name = data["disease_name"]
    did = data["disease_id"]
    print(f"Disease: {name} ({did})")
    axes = data["axes"]
    print(f"Axes ({len(axes)}):")
    for ax in axes:
        idx = ax["index"]
        aname = ax["name"]
        unit = ax["unit"]
        atype = ax["type"]
        print(f"  [{idx}] {aname} ({unit}) type={atype}")
    rho_d = process_gmm(data["rho_disease"])
    rho_h = process_gmm(data["rho_healthy"])
    comps_d = rho_d["components"]
    comps_h = rho_h["components"]
    print(f"rho_disease: {len(comps_d)} component(s)")
    for c in comps_d:
        label = c["subtype_label"]
        w = c["weight_normalized"]
        print(f"  {label}: weight={w:.3f}")
    print(f"rho_healthy: {len(comps_h)} component(s)")
    for c in comps_h:
        label = c["subtype_label"]
        w = c["weight_normalized"]
        print(f"  {label}: weight={w:.3f}")


if __name__ == "__main__":
    main()
```
