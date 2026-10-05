"""Manuscript figures from generated results (plan.md §7: figures only from reproducible data).

Usage: .venv/bin/python experiments/make_figures.py MAIN-20260927
Reads results/processed/<run>/main_report.json; writes figs/fig_forest.tex (standalone pgfplots)
and compiles it to fig_forest.pdf with pdflatex. No plotting libraries needed.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = [("qwen3-4b", "Qwen3-4B", "seriesA", "*", 0.14), ("granite4-micro", "Granite-4.0-Micro", "seriesB", "square*", -0.14)]
DEFENSES = [("B1", "B1 tool filter", 4), ("B2", "B2 spotlighting", 3), ("B3", "B3 PromptGuard-2-22M", 2), ("B4", "B4 runtime gate", 1)]
PANELS = [("dASR_C", "$\\Delta$ASR$_C$ vs B0 (pp)"), ("dBTSR", "$\\Delta$BTSR vs B0 (pp)")]


def panel(primary, metric, xlabel, first):
    lines = [f"\\nextgroupplot[xlabel={{{xlabel}}}" + (", yticklabels from table={\\ylabels}{label}, ytick={1,2,3,4}"
                                                        if first else ", yticklabels={}") + "]",
             "\\addplot[gray!70, thin, forget plot] coordinates {(0,0.4) (0,4.6)};"]
    for key, _, color, mark, off in MODELS:
        for d, _, y in DEFENSES:
            c = primary[f"{key}/{d}"][metric]
            x, lo, hi = 100 * c["diff"], 100 * c["lo"], 100 * c["hi"]
            sig = c.get("reduction_claim", False)
            fill = color if sig else "white"
            lines.append(f"\\addplot[{color}, line width=0.9pt, forget plot] coordinates {{({lo:.1f},{y + off}) ({hi:.1f},{y + off})}};")
            lines.append(f"\\addplot[{color}, only marks, mark={mark.rstrip('*')}*, mark size=2.4pt, "
                         f"mark options={{fill={fill}, draw={color}, line width=0.9pt}}, forget plot] "
                         f"coordinates {{({x:.1f},{y + off})}};")
    return lines


def main(run_id):
    r = json.loads((ROOT / "results/processed" / run_id / "main_report.json").read_text())
    out = ROOT / "figs"
    out.mkdir(parents=True, exist_ok=True)
    tex = [
        "\\documentclass[border=2pt]{standalone}",
        "\\usepackage{pgfplots}\\usepgfplotslibrary{groupplots}\\pgfplotsset{compat=1.18}",
        "\\usepackage[T1]{fontenc}\\usepackage{helvet}\\renewcommand{\\familydefault}{\\sfdefault}",
        # categorical slots 1-2 of the reference palette; identity is also carried by marker shape
        "\\definecolor{seriesA}{HTML}{2A78D6}\\definecolor{seriesB}{HTML}{EB6834}",
        "\\pgfplotstableread[col sep=comma]{label\n" + "\n".join(
            n for n, _ in sorted(((lab, y) for _, lab, y in DEFENSES), key=lambda t: t[1])) + "\n}\\ylabels",
        "\\begin{document}\\footnotesize",
        "\\begin{tikzpicture}",
        "\\begin{groupplot}[group style={group size=2 by 1, horizontal sep=22pt}, width=6.4cm, height=5.2cm,",
        " xmin=-100, xmax=25, ymin=0.4, ymax=4.6, xtick={-100,-50,0}, minor xtick={-75,-25,25}, xminorgrids, minor grid style={gray!10},",
        " axis line style={gray!60}, tick style={gray!60}, xmajorgrids, grid style={gray!18},",
        " ytick style={draw=none}, tick label style={font=\\scriptsize}, label style={font=\\footnotesize}]",
    ]
    for i, (m, xl) in enumerate(PANELS):
        tex += panel(r["primary"], m, xl, i == 0)
    tex += ["\\end{groupplot}",
            "\\node[anchor=north] at ($(group c1r1.south)!0.5!(group c2r1.south)+(0,-0.9cm)$) {\\scriptsize",
            " \\tikz\\draw[seriesA, fill=seriesA, line width=0.9pt] (0,0) circle (2.4pt); Qwen3-4B\\quad",
            " \\tikz\\draw[seriesB, fill=seriesB, line width=0.9pt] (0,0) rectangle (4.8pt,4.8pt); Granite-4.0-Micro\\quad",
            " filled: meets pre-registered criterion \\quad open: not distinguishable from B0};",
            "\\end{tikzpicture}", "\\end{document}", ""]
    (out / "fig_forest.tex").write_text("\n".join(tex))
    subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "fig_forest.tex"], cwd=out,
                   check=True, stdout=subprocess.DEVNULL)
    print("wrote", out / "fig_forest.pdf")


if __name__ == "__main__":
    main(sys.argv[1])
