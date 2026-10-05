"""Main-run analysis per EXPERIMENT_MATRIX.md §6 and metrics.md (plan fixed before data).

Usage: PYTHONPATH=. .venv/bin/python experiments/main_report.py MAIN-20260927 P0-20260927T110335
Reads only raw logs (cells named __INCOMPLETE_* are excluded). Writes results/processed/<run id>/main_report.{json,md}.
"""
import json
import sys
from pathlib import Path

import numpy as np

from evaluation.metrics import (BOOTSTRAP_SEED, N_BOOT, _by_task, _pair, _resample_keys, _strata, cell_metrics,
                                competence_set, defense_intervened, holm, load_cell, paired_diff, task_key)

ROOT = Path(__file__).resolve().parents[1]
MODELS = ("qwen3-4b", "granite4-micro")
DEFENSES = ("B1", "B2", "B3", "B4")


def _rate(num, den):
    return num / den if den else None


def cell_stats(competence):
    """Statistics bootstrapped per cell; each maps a list of episodes to a number or None."""
    def sec(eps):
        return [bool(e["security"]) for e in eps]
    return {
        "util_rate": lambda eps: _rate(sum(e["utility"] for e in eps), len(eps)),
        "ASR": lambda eps: _rate(sum(sec(eps)), len(eps)),
        "ASR_C": lambda eps: _rate(sum(sec([e for e in eps if task_key(e) in competence])),
                                   sum(task_key(e) in competence for e in eps)),
        "VR": lambda eps: _rate(sum(sec(eps)),
                                len(eps) - sum((not bool(e["security"])) and not e["utility"] for e in eps)),
        "FPR_task": lambda eps: _rate(sum(defense_intervened(e) for e in eps), len(eps)),
        "latency_p50_s": lambda eps: float(np.percentile([e["wall_s"] for e in eps], 50)),
        "latency_p95_s": lambda eps: float(np.percentile([e["wall_s"] for e in eps], 95)),
    }


def multi_bootstrap(eps, stats, n_boot=N_BOOT, seed=BOOTSTRAP_SEED):
    """Same stratified cluster bootstrap as evaluation.metrics.bootstrap_ci, all statistics on each resample."""
    groups = _by_task(eps)
    strata = _strata(groups)
    rng = np.random.default_rng(seed)
    vals = {k: [] for k in stats}
    for _ in range(n_boot):
        sample = [e for k in _resample_keys(strata, rng) for e in groups[k]]
        for k, f in stats.items():
            v = f(sample)
            if v is not None:
                vals[k].append(v)
    out = {}
    for k, f in stats.items():
        lo, hi = (np.percentile(vals[k], [2.5, 97.5]) if vals[k] else (None, None))
        out[k] = {"point": f(list(eps)), "lo": None if lo is None else float(lo),
                  "hi": None if hi is None else float(hi)}
    return out


def latency_ratio(eps_b0, eps_d, n_boot=N_BOOT, seed=BOOTSTRAP_SEED):
    """p50(d)/p50(B0) with a paired cluster bootstrap (same resampled user tasks for both conditions)."""
    groups = _pair(eps_b0, eps_d)
    strata = _strata(groups)
    rng = np.random.default_rng(seed)

    def ratio(keys):
        a = [p[0]["wall_s"] for k in keys for p in groups[k]]
        b = [p[1]["wall_s"] for k in keys for p in groups[k]]
        return float(np.median(b) / np.median(a))
    boots = [ratio(_resample_keys(strata, rng)) for _ in range(n_boot)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"ratio": ratio(list(groups)), "lo": float(lo), "hi": float(hi)}


def main(run_id, p0_id):
    raw = ROOT / "results/raw"
    cells = {}
    for d in sorted((raw / run_id).iterdir()):
        if d.is_dir() and "__INCOMPLETE_" not in d.name:
            assert (d / "cell_summary.json").exists(), d
            cells[d.name] = load_cell(d)[1]
    for m in MODELS:
        cells[f"{m}__B0__A0__test"] = load_cell(raw / p0_id / f"{m}__B0__A0__test")[1]

    def get(m, d, a):
        return cells[f"{m}__{d}__{a}__test"]

    comp = {m: competence_set(get(m, "B0", "A0")) for m in MODELS}
    report = {"run_id": run_id, "b0_a0_from": p0_id, "n_boot": N_BOOT, "seed": BOOTSTRAP_SEED,
              "competence": {m: {"n": len(c), "banking": sum(k[0] == "banking" for k in c),
                                 "slack": sum(k[0] == "slack" for k in c)} for m, c in comp.items()},
              "cells": {}, "primary": {}, "a2_vs_a1": {}, "ablations": {}, "per_suite": {}}

    # Per-cell estimates with CIs
    for name, eps in sorted(cells.items()):
        m = name.split("__")[0]
        a = eps[0]["attack"]
        stats = cell_stats(comp[m])
        keep = ["util_rate", "latency_p50_s", "latency_p95_s"]
        keep += ["FPR_task"] if a == "A0" and eps[0]["defense"] in ("B1", "B3", "B4") else []
        keep += ["ASR", "ASR_C", "VR"] if a != "A0" else []
        report["cells"][name] = {"counts": cell_metrics(eps, comp[m]),
                                 "ci": multi_bootstrap(eps, {k: stats[k] for k in keep})}
        print("cell", name, flush=True)

    # Primary contrasts: each defense vs B0 within model, paired
    pvals = {}
    for m in MODELS:
        for d in DEFENSES:
            b0a1 = [e for e in get(m, "B0", "A1") if task_key(e) in comp[m]]
            da1 = [e for e in get(m, d, "A1") if task_key(e) in comp[m]]
            sec = paired_diff(b0a1, da1, lambda e: float(bool(e["security"])))
            asr_b0 = np.mean([bool(e["security"]) for e in b0a1])
            sec["RRR"] = (1 - np.mean([bool(e["security"]) for e in da1]) / asr_b0) if asr_b0 else None
            util = paired_diff(get(m, "B0", "A0"), get(m, d, "A0"), lambda e: float(e["utility"]))
            lat = latency_ratio(get(m, "B0", "A1"), get(m, d, "A1"))
            report["primary"][f"{m}/{d}"] = {"dASR_C": sec, "dBTSR": util, "latency_ratio_A1": lat}
            pvals[f"{m}/{d}/dASR_C"], pvals[f"{m}/{d}/dBTSR"] = sec["p"], util["p"]
            print("primary", m, d, flush=True)
    adj = holm(pvals)
    for key, p in adj.items():
        m_d, metric = key.rsplit("/", 1)
        c = report["primary"][m_d][metric]
        c["p_holm"] = p
        c["reduction_claim"] = p < 0.05 and (c["hi"] < 0 or c["lo"] > 0)

    # Secondary: A2 vs A1 per defense (paired), raw ASR and ASR_C
    for m in MODELS:
        for d in ("B2", "B3", "B4"):
            a1, a2 = get(m, d, "A1"), get(m, d, "A2")
            r = paired_diff(a1, a2, lambda e: float(bool(e["security"])))
            rc = paired_diff([e for e in a1 if task_key(e) in comp[m]], [e for e in a2 if task_key(e) in comp[m]],
                             lambda e: float(bool(e["security"])))
            report["a2_vs_a1"][f"{m}/{d}"] = {"dASR": {k: r[k] for k in ("diff", "lo", "hi", "n_pairs")},
                                              "dASR_C": {k: rc[k] for k in ("diff", "lo", "hi", "n_pairs")}}

    # Secondary: B4 ablations vs full B4 (M1 only), CIs only
    m = "qwen3-4b"
    for v in ("noS1", "noS3", "noS4"):
        full1 = [e for e in get(m, "B4", "A1") if task_key(e) in comp[m]]
        abl1 = [e for e in get(m, f"B4-{v}", "A1") if task_key(e) in comp[m]]
        s = paired_diff(full1, abl1, lambda e: float(bool(e["security"])))
        f = paired_diff(get(m, "B4", "A0"), get(m, f"B4-{v}", "A0"), lambda e: float(defense_intervened(e)))
        report["ablations"][v] = {"dASR_C": {k: s[k] for k in ("diff", "lo", "hi", "n_pairs")},
                                  "dFPR_task": {k: f[k] for k in ("diff", "lo", "hi", "n_pairs")}}

    # Secondary: per-suite point estimates
    for name, eps in cells.items():
        m = name.split("__")[0]
        for suite in ("banking", "slack"):
            se = [e for e in eps if e["suite"] == suite]
            cm = cell_metrics(se, comp[m])
            report["per_suite"][f"{name}/{suite}"] = {k: cm[k] for k in ("BTSR", "ATSR", "ASR", "ASR_C", "FPR_task")
                                                      if k in cm}

    # Derived quantities quoted in the manuscript (plan.md §7: numbers only from generated output)
    derived = {}
    for m in MODELS:
        c = report["cells"][f"{m}__B0__A1__test"]["counts"]
        derived[f"{m}/B0_A1_ASR_C_minus_ASR_pp"] = 100 * (c["ASR_C"]["rate"] - c["ASR"]["rate"])
        u0 = {task_key(e): e["utility"] for e in get(m, "B0", "A0")}
        blocked = [e for e in get(m, "B4", "A0") if defense_intervened(e)]
        derived[f"{m}/B4_A0_blocked_episodes"] = len(blocked)
        derived[f"{m}/B4_A0_blocked_on_B0_solved_tasks"] = sum(u0[task_key(e)] for e in blocked)
        derived[f"{m}/B4_A0_blocked_still_solved"] = sum(e["utility"] for e in blocked)
        pairs = [p for v in _pair(get(m, "B0", "A1"), get(m, "B4", "A1")).values() for p in v]
        lost = [(a, b) for a, b in pairs if a["utility"] and not b["utility"]]
        derived[f"{m}/B4_A1_tasks_lost_vs_B0"] = len(lost)
        derived[f"{m}/B4_A1_tasks_lost_with_block"] = sum(defense_intervened(b) for _, b in lost)
        derived[f"{m}/B4_A1_tasks_lost_attacked_at_B0"] = sum(bool(a["security"]) for a, _ in lost)
        for d in ("B0",) + DEFENSES:
            k = report["cells"][f"{m}__{d}__A1__test"]["counts"]
            derived[f"{m}/{d}_A1_rss_peak_GiB"] = k["rss_peak_sampled_bytes_max"] / 2 ** 30
            derived[f"{m}/{d}_A1_total_tokens_mean"] = k["total_tokens_mean"]
            derived[f"{m}/{d}_A1_model_calls_mean"] = k["model_calls_mean"]
    report["derived"] = derived

    # Pre-registered hypotheses (plan.md §2), evaluated mechanically
    hyp = {}
    hyp["H1"] = {m: derived[f"{m}/B0_A1_ASR_C_minus_ASR_pp"] >= 0 for m in MODELS}
    hyp["H2"] = [k for k, c in report["primary"].items() if c["dASR_C"]["reduction_claim"]]
    hyp["H3"] = {m: {d: report["primary"][f"{m}/{d}"]["latency_ratio_A1"]["ratio"] for d in DEFENSES}
                 for m in MODELS}
    hyp["H3_supported"] = {m: all(hyp["H3"][m][d] < hyp["H3"][m]["B1"] for d in ("B2", "B3", "B4"))
                           for m in MODELS}
    hyp["H4"] = {m: report["cells"][f"{m}__B4__A0__test"]["counts"]["FPR_task"]["rate"] for m in MODELS}
    report["hypotheses"] = hyp

    out = ROOT / "results/processed" / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "main_report.json").write_text(json.dumps(report, indent=1, default=float))
    (out / "main_report.md").write_text(render(report, comp))
    print("wrote", out)


def _pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}"


def _ci(c):
    return f"{_pct(c['point'])} [{_pct(c['lo'])}, {_pct(c['hi'])}]"


def render(r, comp):
    L = [f"# Main run {r['run_id']}: results (EXPERIMENT_MATRIX.md §6)", "",
         f"B0/A0 from {r['b0_a0_from']}. Cluster bootstrap over user tasks, {r['n_boot']} resamples, seed {r['seed']}.",
         "", "## Competence sets C(m)", ""]
    for m, c in r["competence"].items():
        L.append(f"- {m}: {c['n']}/32 (banking {c['banking']}, slack {c['slack']})")
    L += ["", "## Per-cell estimates (%, 95% CI)", "",
          "| Cell | n | Task success | ASR | ASR_C (n) | VR | FPR_task | p50 s | p95 s |", "|---|---:|---|---|---|---|---|---:|---:|"]
    for name, c in r["cells"].items():
        ci, k = c["ci"], c["counts"]
        asrc = f"{_ci(ci['ASR_C'])} ({k['ASR_C']['den']})" if "ASR_C" in ci else ""
        L.append(f"| {name.replace('__test', '')} | {k['n_episodes']} | {_ci(ci['util_rate'])} | "
                 f"{_ci(ci['ASR']) if 'ASR' in ci else ''} | {asrc} | {_ci(ci['VR']) if 'VR' in ci else ''} | "
                 f"{_ci(ci['FPR_task']) if 'FPR_task' in ci else ''} | {ci['latency_p50_s']['point']:.1f} | "
                 f"{ci['latency_p95_s']['point']:.1f} |")
    L += ["", "## Primary contrasts vs B0 (pp; paired; Holm over 16 tests)", "",
          "| Model/defense | ΔASR_C [CI] | p_holm | RRR | Reduction? | ΔBTSR [CI] | p_holm | Latency ratio [CI] |",
          "|---|---|---:|---:|---|---|---:|---|"]
    for k, c in r["primary"].items():
        s, u, lat = c["dASR_C"], c["dBTSR"], c["latency_ratio_A1"]
        L.append(f"| {k} | {_pct(s['diff'])} [{_pct(s['lo'])}, {_pct(s['hi'])}] | {s['p_holm']:.4f} | "
                 f"{_pct(s['RRR'])} | {'yes' if s['reduction_claim'] else 'not distinguishable from B0'} | "
                 f"{_pct(u['diff'])} [{_pct(u['lo'])}, {_pct(u['hi'])}] | {u['p_holm']:.4f} | "
                 f"{lat['ratio']:.2f} [{lat['lo']:.2f}, {lat['hi']:.2f}] |")
    L += ["", "## A2 vs A1 (pp, paired, descriptive)", "", "| Model/defense | ΔASR [CI] | ΔASR_C [CI] |", "|---|---|---|"]
    for k, c in r["a2_vs_a1"].items():
        a, b = c["dASR"], c["dASR_C"]
        L.append(f"| {k} | {_pct(a['diff'])} [{_pct(a['lo'])}, {_pct(a['hi'])}] | "
                 f"{_pct(b['diff'])} [{_pct(b['lo'])}, {_pct(b['hi'])}] |")
    L += ["", "## B4 ablations vs full B4, qwen3-4b (pp, paired, CIs only)", "",
          "| Variant | ΔASR_C [CI] | ΔFPR_task [CI] |", "|---|---|---|"]
    for k, c in r["ablations"].items():
        a, b = c["dASR_C"], c["dFPR_task"]
        L.append(f"| {k} | {_pct(a['diff'])} [{_pct(a['lo'])}, {_pct(a['hi'])}] | "
                 f"{_pct(b['diff'])} [{_pct(b['lo'])}, {_pct(b['hi'])}] |")
    L += ["", "## Per-suite point estimates (%; num/den)", "", "| Cell/suite | BTSR | ATSR | ASR | ASR_C | FPR_task |",
          "|---|---|---|---|---|---|"]
    for k, c in r["per_suite"].items():
        def f(x):
            return f"{_pct(c[x]['rate'])} ({c[x]['num']}/{c[x]['den']})" if x in c else ""
        L.append(f"| {k.replace('__test', '')} | {f('BTSR')} | {f('ATSR')} | {f('ASR')} | {f('ASR_C')} | {f('FPR_task')} |")
    L += ["", "## Pre-registered hypotheses (plan.md §2)", ""]
    h = r["hypotheses"]
    L.append(f"- H1 (ASR_C(B0) >= raw ASR(B0)): {h['H1']}")
    L.append(f"- H2 (>= 1 defense reduces ASR_C, Holm): contrasts meeting criterion = {h['H2']}")
    L.append(f"- H3 (B2-B4 add less p50 latency than B1): ratios = "
             f"{ {m: {d: round(v, 2) for d, v in x.items()} for m, x in h['H3'].items()} }; supported = {h['H3_supported']}")
    L.append(f"- H4 (FPR_task(B4) > 0): {h['H4']}")
    L += ["", "## Derived quantities quoted in the manuscript", ""]
    for k, v in r["derived"].items():
        L.append(f"- {k}: {round(v, 2) if isinstance(v, float) else v}")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main(*sys.argv[1:3])
