"""
AOSD GMM 协方差矩阵 PSD 检查 + Higham 投影修复
"""
import json
import numpy as np

INPUT = r"C:\Users\wangw\Desktop\AOSD.txt"

with open(INPUT, encoding="utf-8") as f:
    data = json.load(f)


def midpoint(interval):
    return (interval[0] + interval[1]) / 2.0


def corr_midpoint_matrix(corr_intervals):
    n = len(corr_intervals)
    M = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            M[i, j] = midpoint(corr_intervals[i][j])
    return M


def higham_psd_projection(M, eps=1e-6):
    eigvals, eigvecs = np.linalg.eigh(M)
    eigvals_clipped = np.clip(eigvals, eps, None)
    M_proj = eigvecs @ np.diag(eigvals_clipped) @ eigvecs.T
    d = np.sqrt(np.diag(M_proj))
    M_proj = M_proj / np.outer(d, d)
    return M_proj


def check_component(component, group_name):
    label = component["subtype_label"]
    cid = component["component_id"]
    print(f"\n--- {group_name} | id={cid} | {label} ---")

    M = corr_midpoint_matrix(component["corr"])
    n = M.shape[0]

    sym_err = float(np.abs(M - M.T).max())
    diag_err = float(np.abs(np.diag(M) - 1.0).max())
    eigvals = np.linalg.eigvalsh(M)
    min_eig = float(eigvals.min())
    max_eig = float(eigvals.max())
    is_psd = min_eig >= -1e-8

    print(f"  shape: {n}x{n}")
    print(f"  symmetry error: {sym_err:.2e}  ({'OK' if sym_err < 1e-8 else 'FAIL'})")
    print(f"  diagonal error: {diag_err:.2e}  ({'OK' if diag_err < 1e-8 else 'FAIL'})")
    print(f"  eigenvalues: min={min_eig:+.6f}, max={max_eig:+.6f}")
    print(f"  >>> PSD: {'YES (合法)' if is_psd else 'NO -- 需要 Higham 投影'}")

    info = {
        "name": f"{group_name}#{cid}_{label}",
        "is_psd": is_psd,
        "min_eig": min_eig,
        "max_eig": max_eig,
        "n_neg_eig": int(np.sum(eigvals < -1e-8)),
    }

    if not is_psd:
        M_proj = higham_psd_projection(M)
        eig_proj = np.linalg.eigvalsh(M_proj)
        frob = float(np.linalg.norm(M - M_proj, "fro"))
        print(f"  Higham 投影后:")
        print(f"    min eigenvalue: {float(eig_proj.min()):+.6f}")
        print(f"    max eigenvalue: {float(eig_proj.max()):+.6f}")
        print(f"    |M - M_proj|_F: {frob:.6f}")
        print(f"    最大单元素改动: {float(np.abs(M - M_proj).max()):.6f}")
        info["higham_frobenius"] = frob
        info["higham_max_elem_change"] = float(np.abs(M - M_proj).max())

    return info


print("=" * 70)
print(" AOSD GMM 9x9 协方差矩阵正定性检查")
print("=" * 70)

results = []
for comp in data["rho_disease"]["components"]:
    results.append(check_component(comp, "rho_disease"))
for comp in data["rho_healthy"]["components"]:
    results.append(check_component(comp, "rho_healthy"))

print("\n" + "=" * 70)
print(" 总结")
print("=" * 70)

n_total = len(results)
n_psd = sum(1 for r in results if r["is_psd"])
print(f"  PSD: {n_psd} / {n_total}")
print()
for r in results:
    flag = "PSD" if r["is_psd"] else f"NOT PSD ({r['n_neg_eig']} 个负特征值)"
    print(f"  [{flag:30s}]  {r['name']}")
    print(f"      min eig = {r['min_eig']:+.4f}, max eig = {r['max_eig']:+.4f}")
    if not r["is_psd"]:
        print(
            f"      Higham 修复: |delta|_F = {r['higham_frobenius']:.4f}, "
            f"max elem change = {r['higham_max_elem_change']:.4f}"
        )

print()
if n_psd == n_total:
    print("  >>> 全部合法 - 你这把赢了一半。")
else:
    print(f"  >>> {n_total - n_psd} 个不正定 - Higham 投影可救。改动幅度看上面。")
