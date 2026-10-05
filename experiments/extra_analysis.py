"""Supplementary (post-hoc, exploratory) statistics and matplotlib figures for the main run.

These analyses were added after the pre-registered analysis (experiments/main_report.py) and do not change any
pre-registered result. They read the same raw logs and the same competence sets.

Usage: PYTHONPATH=. <python with numpy, scipy, statsmodels, matplotlib> experiments/extra_analysis.py \
           MAIN-20260927 P0-20260927T110335 <figure output dir>
Writes results/processed/<run id>/extra_analysis.{json,md} and Fig3-Fig5 (PDF) into the figure directory.
"""
import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats

from evaluation.metrics import competence_set, holm, load_cell, task_key

ROOT = Path(__file__).resolve().parents[1]
MODELS = ("qwen3-4b", "granite4-micro")
LABEL = {"qwen3-4b": "Qwen3-4B", "granite4-micro": "Granite-4.0-Micro"}
DEFS = ("B0", "B1", "B2", "B3", "B4")
DNAME = {"B0": "B0 none", "B1": "B1 tool filter", "B2": "B2 spotlighting", "B3": "B3 PromptGuard",
         "B4": "B4 runtime gate"}
N_CONTRASTS = 16          # pre-registered family size used for Holm in the primary analysis
ALPHA = 0.05

plt.rcParams.update({"font.family": "serif", "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
                     "legend.fontsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7, "pdf.fonttype": 42})


def load(run_id, p0_id):
    raw = ROOT / "results/raw"
    cells = {}
    for d in sorted((raw / run_id).iterdir()):
        if d.is_dir() and "__INCOMPLETE_" not in d.name:
            cells[d.name] = load_cell(d)[1]
    for m in MODELS:
        cells[f"{m}__B0__A0__test"] = load_cell(raw / p0_id / f"{m}__B0__A0__test")[1]
    return cells


def pair_key(e):
    return e["suite"], e["user_task"], e.get("injection_task")


def exact_mcnemar(b, c):
    """Two-sided exact McNemar test; b = attacked at B0 only, c = attacked under the defense only."""
    n = b + c
    p = 1.0 if n == 0 else min(1.0, 2 * stats.binom.cdf(min(b, c), n, 0.5))
    # conditional odds ratio c/b with exact (Clopper-Pearson) interval transformed from c/(b+c)
    if n == 0:
        return p, None, None, None          # no discordant pairs: odds ratio undefined
    lo, hi = stats.beta.ppf([0.025, 0.975], [c, c + 1], [n - c + 1, n - c]) if 0 < c < n else (
        (0.0, stats.beta.ppf(0.975, 1, n)) if c == 0 else (stats.beta.ppf(0.025, n, 1), 1.0))
    to_or = (lambda q: q / (1 - q) if q < 1 else math.inf)
    return p, (c / b if b else math.inf), to_or(lo), to_or(hi)


def main(run_id, p0_id, figdir):
    figdir = Path(figdir)
    figdir.mkdir(parents=True, exist_ok=True)
    cells = load(run_id, p0_id)
    get = lambda m, d, a: cells[f"{m}__{d}__{a}__test"]
    comp = {m: competence_set(get(m, "B0", "A0")) for m in MODELS}
    out = {"note": "post-hoc exploratory analyses; pre-registered results unchanged", "mcnemar": {}, "gee": {},
           "latency": {}, "mde": {}}

    # ---- (1) Exact McNemar tests on paired attacked episodes (competent tasks, A1) -------------------------
    pv = {}
    for m in MODELS:
        b0 = {pair_key(e): bool(e["security"]) for e in get(m, "B0", "A1") if task_key(e) in comp[m]}
        for d in DEFS[1:]:
            dd = {pair_key(e): bool(e["security"]) for e in get(m, d, "A1") if task_key(e) in comp[m]}
            keys = sorted(set(b0) & set(dd))
            b = sum(b0[k] and not dd[k] for k in keys)
            c = sum(dd[k] and not b0[k] for k in keys)
            p, orr, lo, hi = exact_mcnemar(b, c)
            asr0 = np.mean([b0[k] for k in keys])
            asr1 = np.mean([dd[k] for k in keys])
            h = 2 * math.asin(math.sqrt(asr1)) - 2 * math.asin(math.sqrt(asr0))   # Cohen's h
            out["mcnemar"][f"{m}/{d}"] = {"n_pairs": len(keys), "b_B0_only": b, "c_def_only": c, "p": p,
                                         "cond_OR": orr, "OR_lo": lo, "OR_hi": hi, "cohens_h": h}
            pv[f"{m}/{d}"] = p
    for k, v in holm(pv).items():
        out["mcnemar"][k]["p_holm"] = v

    # ---- (2) Cluster-robust logistic regression (GEE, exchangeable, clusters = model x user task) -----------
    rows = []
    for m in MODELS:
        for d in ("B0", "B2", "B3", "B4"):          # B1 excluded: zero successes (complete separation)
            for e in get(m, d, "A1"):
                if task_key(e) in comp[m]:
                    rows.append({"y": int(bool(e["security"])), "defense": d, "model": m,
                                 "cluster": f"{m}|{e['suite']}|{e['user_task']}"})
    df = pd.DataFrame(rows)
    df["defense"] = pd.Categorical(df["defense"], ["B0", "B2", "B3", "B4"])
    df["model"] = pd.Categorical(df["model"], list(MODELS))
    gee = smf.gee("y ~ C(defense) + C(model)", groups="cluster", data=df, family=sm.families.Binomial(),
                  cov_struct=sm.cov_struct.Exchangeable()).fit()
    ci = gee.conf_int()
    for term in gee.params.index:
        out["gee"][term] = {"OR": float(np.exp(gee.params[term])), "lo": float(np.exp(ci.loc[term, 0])),
                            "hi": float(np.exp(ci.loc[term, 1])), "p": float(gee.pvalues[term])}
    out["gee_n"] = {"episodes": len(df), "clusters": int(df["cluster"].nunique())}
    # interaction test: does the B4 effect differ between models?
    gee_i = smf.gee("y ~ C(defense) * C(model)", groups="cluster", data=df[df.defense.isin(["B0", "B4"])],
                    family=sm.families.Binomial(), cov_struct=sm.cov_struct.Exchangeable()).fit()
    term = [t for t in gee_i.params.index if ":" in t and "B4" in t][0]
    out["gee_interaction_B4xmodel"] = {"OR_ratio": float(np.exp(gee_i.params[term])),
                                       "p": float(gee_i.pvalues[term])}

    # ---- (3) Latency: paired Wilcoxon signed-rank and Hodges-Lehmann shift (A1) ------------------------------
    lp = {}
    for m in MODELS:
        b0 = {pair_key(e): e["wall_s"] for e in get(m, "B0", "A1")}
        for d in DEFS[1:]:
            dd = {pair_key(e): e["wall_s"] for e in get(m, d, "A1")}
            keys = sorted(set(b0) & set(dd))
            diff = np.array([dd[k] - b0[k] for k in keys])
            w = stats.wilcoxon(diff, zero_method="wilcox")
            walsh = (diff[:, None] + diff[None, :])[np.triu_indices(len(diff))] / 2
            out["latency"][f"{m}/{d}"] = {"n": len(keys), "median_diff_s": float(np.median(diff)),
                                         "hodges_lehmann_s": float(np.median(walsh)), "p": float(w.pvalue)}
            lp[f"{m}/{d}"] = float(w.pvalue)
    for k, v in holm(lp).items():
        out["latency"][k]["p_holm"] = v

    # ---- (4) Minimum detectable effect of the pre-registered sign-flip permutation test ---------------------
    # With k informative clusters all moving in one direction, the smallest two-sided p is 2 * 2^-k.
    k_min = next(k for k in range(1, 40) if 2 * 2.0 ** -k <= ALPHA / N_CONTRASTS)
    out["mde"] = {"k_min_informative_tasks_for_holm_rank1": k_min,
                  "competent_tasks": {m: len(comp[m]) for m in MODELS}}

    # ---- Figures ---------------------------------------------------------------------------------------------
    fig3_latency(get, figdir)
    fig4_heatmap(get, comp, figdir)
    fig5_tradeoff(run_id, figdir)

    proc = ROOT / "results/processed" / run_id
    (proc / "extra_analysis.json").write_text(json.dumps(out, indent=2, default=float))
    (proc / "extra_analysis.md").write_text(render(out))
    print(render(out))


def fig3_latency(get, figdir):
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.4), sharey=True)
    for ax, m in zip(axes, MODELS):
        data = [[e["wall_s"] for e in get(m, d, "A1")] for d in DEFS]
        ax.boxplot(data, widths=0.55, showfliers=True, medianprops={"color": "black"},
                   flierprops={"marker": ".", "markersize": 3, "alpha": 0.5},
                   boxprops={"facecolor": "#d9e6f2"}, patch_artist=True)
        ax.set_xticks(range(1, 6), [DNAME[d].replace(" ", "\n", 1) for d in DEFS], fontsize=6)
        ax.set_yscale("log")
        ax.set_yticks([20, 30, 50, 100, 200, 300], ["20", "30", "50", "100", "200", "300"])
        ax.minorticks_off()
        ax.set_title(LABEL[m])
        ax.grid(axis="y", alpha=0.3, linewidth=0.5)
    axes[0].set_ylabel("Episode wall-clock time (s, log scale)")
    fig.tight_layout()
    fig.savefig(figdir / "Fig3.pdf")
    plt.close(fig)


def fig4_heatmap(get, comp, figdir):
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 4.2), gridspec_kw={"width_ratios": [22, 10]})
    for ax, m in zip(axes, MODELS):
        tasks = sorted(comp[m], key=lambda k: (k[0], int(k[1].split("_")[-1])))
        mat = np.zeros((len(tasks), len(DEFS)))
        for j, d in enumerate(DEFS):
            eps = get(m, d, "A1")
            for i, t in enumerate(tasks):
                s = [bool(e["security"]) for e in eps if task_key(e) == t]
                mat[i, j] = np.mean(s)
        im = ax.imshow(mat, cmap="Greys", vmin=0, vmax=1, aspect="auto")
        ax.set_xticks(range(len(DEFS)), [d for d in DEFS])
        ax.set_yticks(range(len(tasks)), [f"{t[0].capitalize()} {t[1].split('_')[-1]}" for t in tasks])
        ax.set_title(f"{LABEL[m]} ({len(tasks)} competent tasks)")
        ax.tick_params(axis="y", labelsize=6)
    cb = fig.colorbar(im, ax=axes, fraction=0.025, pad=0.02)
    cb.set_label("Share of injection tasks that succeeded")
    fig.savefig(figdir / "Fig4.pdf", bbox_inches="tight")
    plt.close(fig)


def fig5_tradeoff(run_id, figdir):
    rep = json.loads((ROOT / "results/processed" / run_id / "main_report.json").read_text())
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.8), sharex=True, sharey=True)
    marks = {"B0": "o", "B1": "s", "B2": "^", "B3": "v", "B4": "D"}
    for ax, m in zip(axes, MODELS):
        for d in DEFS:
            a1 = rep["cells"][f"{m}__{d}__A1__test"]["ci"]["ASR_C"]
            a0 = rep["cells"][f"{m}__{d}__A0__test"]["ci"]["util_rate"]
            x, y = 100 * a0["point"], 100 * a1["point"]
            ax.errorbar(x, y, xerr=[[x - 100 * a0["lo"]], [100 * a0["hi"] - x]],
                        yerr=[[y - 100 * a1["lo"]], [100 * a1["hi"] - y]], fmt=marks[d], color="black",
                        mfc="white" if d in ("B0", "B1") else "black", ms=5, capsize=2, lw=0.7, label=DNAME[d])
        ax.set_title(LABEL[m])
        ax.set_xlabel("Benign task success, BTSR (%)")
        ax.grid(alpha=0.3, linewidth=0.5)
        ax.set_xlim(0, 100)
        ax.set_ylim(-5, 100)
    axes[0].set_ylabel("ASR$_C$ under A1 (%)")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=5, frameon=False, bbox_to_anchor=(0.5, -0.01))
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(figdir / "Fig5.pdf")
    plt.close(fig)


def render(o):
    f = lambda x: "n/a" if x is None else ("inf" if isinstance(x, float) and math.isinf(x) else f"{x:.3g}")
    L = ["# Supplementary analyses (post-hoc, exploratory)", "", "## Exact McNemar, A1, competent tasks", "",
         "| contrast | pairs | B0 only | defense only | cond. OR [95% CI] | Cohen's h | p | p Holm |",
         "|---|---|---|---|---|---|---|---|"]
    for k, v in o["mcnemar"].items():
        L.append(f"| {k} | {v['n_pairs']} | {v['b_B0_only']} | {v['c_def_only']} | {f(v['cond_OR'])} "
                 f"[{f(v['OR_lo'])}, {f(v['OR_hi'])}] | {v['cohens_h']:.2f} | {f(v['p'])} | {f(v['p_holm'])} |")
    L += ["", f"## GEE logistic regression (n = {o['gee_n']['episodes']} episodes, "
          f"{o['gee_n']['clusters']} clusters)", "", "| term | OR [95% CI] | p |", "|---|---|---|"]
    for k, v in o["gee"].items():
        L.append(f"| {k} | {f(v['OR'])} [{f(v['lo'])}, {f(v['hi'])}] | {f(v['p'])} |")
    gi = o["gee_interaction_B4xmodel"]
    L += ["", f"B4 x model interaction: ratio of ORs {f(gi['OR_ratio'])}, p = {f(gi['p'])}", "",
          "## Latency, paired Wilcoxon signed-rank (A1)", "",
          "| contrast | n | median diff (s) | Hodges-Lehmann (s) | p | p Holm |", "|---|---|---|---|---|---|"]
    for k, v in o["latency"].items():
        L.append(f"| {k} | {v['n']} | {v['median_diff_s']:.1f} | {v['hodges_lehmann_s']:.1f} | {f(v['p'])} | "
                 f"{f(v['p_holm'])} |")
    L += ["", f"Minimum informative tasks for significance at rank 1 of Holm (m = {N_CONTRASTS}): "
          f"{o['mde']['k_min_informative_tasks_for_holm_rank1']}; competent tasks: {o['mde']['competent_tasks']}"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main(*sys.argv[1:4])
