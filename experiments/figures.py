"""Figures from saved results: one chart per game, Theory vs Jev vs Laya as stacked share bars.

    python experiments/figures.py                              # latest plan -> figures/<game>.png
    python experiments/figures.py --plan plan_20260928-1329 --out figures

Each bar shows how often a player chose each option (100% = all its decisions). Which runs
feed each game is set in SOURCES below; the caption under each chart says what was pooled.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no window; we only write files
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.analyze import comparison_decisions, load_experiment  # noqa: E402

RESULTS = ROOT / "results"

# Colours: validated reference palette (light mode). Categorical for unordered options,
# one-hue ramp (light -> dark) for ordered ones such as offers or number ranges.
SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
CATEGORICAL = ["#1baf7a", "#4a3aa7", "#eda100"]
RAMP = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281", "#0d366b"]
FONT = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]

BC_BINS = [(0, 0, "0"), (1, 20, "1–20"), (21, 40, "21–40"), (41, 60, "41–60"), (61, 80, "61–80"), (81, 100, "81–100")]
SEEDS = (1, 2, 3)

# game -> list of panels: (title, step, {model: [experiment names]}, option order, theory shares, caption)
SOURCES = {
    "matching_pennies": [
        ("Matching Pennies", "action", {m: [f"p2x_mp_{m}_s{s}" for s in SEEDS] for m in ("jev", "laya")},
         ["HEADS", "TAILS"], {"HEADS": 0.5, "TAILS": 0.5},
         "Each model vs a random opponent, 3 matches × 50 rounds, with history. Theory: 50/50 mixed equilibrium."),
    ],
    "rps": [
        ("Rock Paper Scissors", "action", {m: [f"p2x_rps_{m}_s{s}" for s in SEEDS] for m in ("jev", "laya")},
         ["ROCK", "PAPER", "SCISSORS"], {"ROCK": 1 / 3, "PAPER": 1 / 3, "SCISSORS": 1 / 3},
         "Each model vs a random opponent, 3 matches × 50 rounds, with history. Theory: 1/3 each (mixed equilibrium)."),
    ],
    "prisoners_dilemma": [
        ("Prisoner's Dilemma", "action", {m: ["p2_pd"] for m in ("jev", "laya")},
         ["COOPERATE", "DEFECT"], {"DEFECT": 1.0},
         "Jev vs Laya, 50 rounds with history, payoffs 3,0,5,1. Theory: always defect (the Nash equilibrium)."),
    ],
    "ultimatum": [
        ("Ultimatum Game: offers", "offer", {m: ["p2_ug_play"] for m in ("jev", "laya")},
         [str(k) for k in range(11)], None,
         "Points offered to the responder (out of 10). Jev vs Laya, 30 rounds with history, roles swap each round."),
        ("Ultimatum Game: responses", "response", {m: ["p2_ug_play"] for m in ("jev", "laya")},
         ["ACCEPT", "REJECT"], None,
         "Responses to the other model's offers in the same match. No theory row: a points-maximiser accepts "
         "any offer above 0, while people often reject low offers."),
    ],
    "beauty_contest": [
        ("Beauty Contest", "number", {m: [f"p2_bc_s{s}" for s in SEEDS] for m in ("jev", "laya")},
         [label for *_, label in BC_BINS], {"0": 1.0},
         "Numbers chosen, grouped into ranges. Jev + Laya + 2 random players, 3 matches × 20 rounds, with history. "
         "Theory: everyone picks 0 (the Nash equilibrium)."),
    ],
    "monty_hall": [
        ("Monty Hall", "stay_or_switch", {m: ["p1_mh3"] for m in ("jev", "laya")},
         ["STAY", "SWITCH"], {"SWITCH": 1.0},
         "200 games with 3 doors, no history. Theory: always switch (wins 2/3 of the time; staying wins 1/3)."),
    ],
}


def latest_plan() -> str:
    plans = sorted({"_".join(p.name.split("_")[:2]) for p in RESULTS.glob("*/plan_*")})
    if not plans:
        sys.exit("no plan results found (run experiments/run_plan.sh first)")
    return plans[-1]


def load(plan: str, name: str) -> dict:
    matches = list(RESULTS.glob(f"*/{plan}_{name}"))
    if not matches:
        raise FileNotFoundError(f"missing experiment {plan}_{name}")
    return load_experiment(matches[0])


def bin_label(value: str) -> str:
    x = int(value)
    return next(label for lo, hi, label in BC_BINS if lo <= x <= hi)


def shares(plan: str, names: list[str], model: str, step: str, game: str) -> tuple[dict[str, float], int]:
    """Share of each option among `model`'s valid decisions for `step`, pooled over the experiments."""
    counts = Counter()
    for name in names:
        for d in comparison_decisions(load(plan, name)):
            if d["player"].startswith(model) and d["step"] == step and d["valid"]:
                counts[bin_label(d["decision"]) if game == "beauty_contest" else d["decision"]] += 1
    n = sum(counts.values())
    return {a: c / n for a, c in counts.items()}, n


def text_color(hex_color: str) -> str:
    """White or ink, by the fill's luminance, so labels inside bars stay readable."""
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return INK if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45 else "#ffffff"


def colors_for(options: list[str], ordered: bool) -> dict[str, str]:
    if not ordered:
        return dict(zip(options, CATEGORICAL))
    # ordered options share one hue, light -> dark, spread over the ramp
    step = (len(RAMP) - 1) / max(len(options) - 1, 1)
    return {o: RAMP[round(i * step)] for i, o in enumerate(options)}


# Layout in inches, so spacing is identical whatever the number of panels
FIG_W, TOP, BOTTOM, TITLE_H, ROW_H, CAPTION_LINE, GAP = 10.5, 0.3, 0.2, 0.75, 0.55, 0.24, 0.45
LEFT, BAR_W = 0.2, 0.72  # bars span this part of the width (figure fractions)


def draw_panel(fig, y_top, title, rows, options, colors, caption):
    """Draw one panel whose top edge is `y_top` inches from the top of the figure."""
    H = fig.get_figheight()
    frac = lambda inches_from_top: 1 - inches_from_top / H
    fig.text(0.04, frac(y_top + 0.42), title, size=16, weight="bold", va="center")
    # legend on the title line: swatch + ink text, only for options somebody chose
    x = 0.46
    for o in [o for o in options if any(s.get(o) for _, s, _ in rows)]:
        fig.patches.append(plt.Rectangle((x, frac(y_top + 0.42) - 0.075 / H * 1.2), 0.018, 0.18 / H,
                                         transform=fig.transFigure, color=colors[o]))
        label = o.title() if o.isalpha() else o
        fig.text(x + 0.025, frac(y_top + 0.42), label, size=12, va="center")
        x += 0.025 + 0.0095 * len(label) + 0.045

    ax = fig.add_axes([LEFT, frac(y_top + TITLE_H + len(rows) * ROW_H), BAR_W, len(rows) * ROW_H / H])
    for y, (label, s, n) in enumerate(reversed(rows)):
        left = 0.0
        for o in options:
            w = s.get(o, 0)
            if w <= 0:
                continue
            ax.barh(y, w - 0.004, left=left + 0.002, height=0.62, color=colors[o], edgecolor="none")
            if w >= 0.07:  # label only where it fits; the legend and n= carry the rest
                ax.text(left + w / 2, y, f"{w * 100:.0f}%", ha="center", va="center", size=12,
                        weight="bold", color=text_color(colors[o]))
            left += w
        theory = label == "Theory"
        ax.text(-0.025, y, label, ha="right", va="center", size=14, color=INK2 if theory else INK,
                weight="normal" if theory else "bold")
        if n:
            ax.text(1.01, y, f"n={n}", ha="left", va="center", size=10.5, color=MUTED)
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.5, len(rows) - 0.5)
    ax.axis("off")
    fig.text(0.04, frac(y_top + TITLE_H + len(rows) * ROW_H + 0.12), "\n".join(textwrap.wrap(caption, 118)),
             size=10.5, color=MUTED, va="top", linespacing=1.4)


def panel_rows(plan, game, step, sources, theory):
    rows = [("Theory", theory, 0)] if theory else []
    for model in ("jev", "laya"):
        s, n = shares(plan, sources[model], model, step, game)
        rows.append(("Jev" if model == "jev" else "Laya", s, n))
    return rows


def make_figure(plan: str, game: str, panels: list) -> plt.Figure:
    prepared, heights = [], []
    for title, step, sources, options, theory, caption in panels:
        caption += " Rounds hitting a reported context limit are excluded; missing telemetry remains unknown."
        rows = panel_rows(plan, game, step, sources, theory)
        if game == "ultimatum" and step == "offer":  # 11 possible offers: keep only those chosen
            options = [o for o in options if any(r[1].get(o) for r in rows)]
        ordered = game in ("ultimatum", "beauty_contest") and step != "response"
        prepared.append((title, rows, options, colors_for(options, ordered), caption))
        heights.append(TITLE_H + len(rows) * ROW_H + 0.12 + len(textwrap.wrap(caption, 118)) * CAPTION_LINE)
    fig = plt.figure(figsize=(FIG_W, TOP + sum(heights) + GAP * (len(heights) - 1) + BOTTOM), dpi=100)
    fig.patch.set_facecolor(SURFACE)
    y = TOP
    for args, h in zip(prepared, heights):
        draw_panel(fig, y, *args)
        y += h + GAP
    return fig


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", help="plan id, e.g. plan_20260928-1329 (default: the latest)")
    ap.add_argument("--out", default=str(ROOT / "figures"))
    args = ap.parse_args(argv)
    plt.rcParams.update({"font.family": FONT, "text.color": INK})
    plan = args.plan or latest_plan()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for game, panels in SOURCES.items():
        try:
            fig = make_figure(plan, game, panels)
        except FileNotFoundError as e:
            print(f"skipped {game}: {e}")
            continue
        path = out / f"{game}.png"
        fig.savefig(path, dpi=200, facecolor=SURFACE)
        plt.close(fig)
        print(f"wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")


if __name__ == "__main__":
    main()
