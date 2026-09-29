"""Descriptive statistics for saved experiments.

    python experiments/analyze.py results/rps/<experiment_id>          # full report for one experiment
    python experiments/analyze.py results --match plan_20260928-1329   # overview + position bias for many
    python experiments/analyze.py results --match plan_ --full         # full report for every experiment

Each analyzed experiment also gets an `analysis.json` next to its other files.
`--csv FILE` writes the overview table (one row per model player per experiment).

A note on the statistics: Jev and Laya give the same answer to the same input. Repeated
decisions on identical inputs are therefore not independent samples, so tests against
theory are only run when (almost) every decision had a different input. Decisions within
one history match also share overlapping history, so p-values there are optimistic.
Treat all tests as descriptive guides, not proof.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

from scipy import stats

ROOT = Path(__file__).resolve().parents[1]

# Mixed-strategy equilibria we can test against (game -> step -> distribution).
THEORY = {
    "matching_pennies": {"action": {"HEADS": 0.5, "TAILS": 0.5}},
    "rps": {"action": {"ROCK": 1 / 3, "PAPER": 1 / 3, "SCISSORS": 1 / 3}},
}
MIN_DISTINCT_SHARE = 0.8  # share of decisions with a unique input needed before running a test
BEATS = {"ROCK": "SCISSORS", "SCISSORS": "PAPER", "PAPER": "ROCK"}
MODEL_PREFIXES = ("jev", "laya")


# --- loading -------------------------------------------------------------------------------------

def load_experiment(path: Path) -> dict:
    read = lambda name: [json.loads(line) for line in (path / name).read_text().splitlines() if line.strip()]
    attempts = read("decisions.jsonl")
    # the last attempt for each (round, player, step) is the decision that counted
    final = {}
    for d in attempts:
        final[(d["round"], d["player"], d["step"])] = d
    return {"path": path, "config": json.loads((path / "config.json").read_text()),
            "summary": json.loads((path / "summary.json").read_text()),
            "attempts": attempts, "decisions": list(final.values()), "rounds": read("rounds.jsonl")}


def find_experiments(paths: list[str], match: str | None) -> list[Path]:
    found = []
    for p in map(Path, paths):
        dirs = [p] if (p / "summary.json").exists() else sorted(x.parent for x in p.rglob("summary.json"))
        found += [d for d in dirs if not match or match in d.name]
    return found


# --- small statistics helpers --------------------------------------------------------------------

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a proportion k/n (better than p ± 2se for small n or p near 0/1)."""
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def frequencies(actions: list[str], options: list[str]) -> dict:
    n = len(actions)
    counts = Counter(actions)
    return {a: {"count": counts[a], "share": counts[a] / n if n else None, "ci95": wilson(counts[a], n)}
            for a in options}


def overlap(p: dict[str, float], q: dict[str, float]) -> float:
    """Distribution overlap in [0, 1]: 1 = identical, 0 = no common mass."""
    return sum(min(p.get(k, 0), q.get(k, 0)) for k in set(p) | set(q))


def longest_streak(seq: list) -> int:
    best = cur = 0
    for i, x in enumerate(seq):
        cur = cur + 1 if i and x == seq[i - 1] else 1
        best = max(best, cur)
    return best


def reasoning_level(x: float, ratio: float, level0_mean: float = 50) -> float | None:
    """Beauty Contest level-k: a level-k player picks level0_mean * ratio**k, so k = log(x/50)/log(ratio)."""
    if x <= 0 or ratio <= 0 or ratio >= 1:
        return None
    return math.log(x / level0_mean) / math.log(ratio)


# --- per-experiment analysis ---------------------------------------------------------------------

def player_step_stats(exp: dict, player: str, step: str) -> dict:
    ds = [d for d in exp["decisions"] if d["player"] == player and d["step"] == step]
    valid = [d for d in ds if d["valid"]]
    options = ds[0]["available_actions"] if ds else []
    labels = sorted({a for d in ds for a in d["available_actions"]}, key=lambda a: (not a.isdigit(), int(a) if a.isdigit() else 0, a))
    actions = [d["decision"] for d in valid]
    inputs = {json.dumps([d["state"], d["question"], d["available_actions"]], sort_keys=True) for d in ds}
    out = {"decisions": len(ds), "valid": len(valid), "distinct_inputs": len(inputs),
           "frequencies": frequencies(actions, labels if len(labels) <= 12 else sorted(set(actions)))}

    # Mean of the model's own reported probabilities = its implied mixed strategy
    probs = [d["probabilities"] for d in valid if d["probabilities"]]
    if probs:
        out["mean_reported_probability"] = {a: statistics.fmean(p.get(a, 0) for p in probs) for a in labels} \
            if len(labels) <= 12 else None
        out["mean_probability_of_chosen"] = statistics.fmean(p[d["decision"]] for p, d in zip(probs, valid))
    confs = [d["confidence"] for d in valid if d["confidence"] is not None]
    out["mean_confidence"] = statistics.fmean(confs) if confs else None  # None = not reported

    # Position of the chosen option in the list as shown (0 = first, 1 = last)
    pos = [d["available_actions"].index(d["decision"]) / (len(d["available_actions"]) - 1)
           for d in valid if len(d["available_actions"]) > 1]
    out["mean_position"] = statistics.fmean(pos) if pos else None

    if actions and len(set(actions)) <= 12:
        out["longest_streak"] = longest_streak(actions)
        half = len(actions) // 2
        if half >= 5 and exp["config"]["game_config"].get("show_history"):
            out["first_half"] = dict(Counter(actions[:half]))
            out["second_half"] = dict(Counter(actions[half:]))

    # Test against the mixed equilibrium, only when inputs really varied
    theory = THEORY.get(exp["summary"]["game"], {}).get(step)
    if theory and actions:
        observed = [actions.count(a) for a in theory]
        expected = [theory[a] * len(actions) for a in theory]
        share_distinct = len(inputs) / len(ds)
        if share_distinct < MIN_DISTINCT_SHARE:
            out["test_vs_equilibrium"] = {"skipped": f"only {len(inputs)} distinct inputs for {len(ds)} decisions; "
                                                     "repeated identical inputs are not independent samples"}
        elif min(expected) < 5:
            out["test_vs_equilibrium"] = {"skipped": "expected counts below 5"}
        else:
            chi2, p = stats.chisquare(observed, expected)
            out["test_vs_equilibrium"] = {"test": "chi-square goodness of fit", "theory": theory,
                                          "chi2": chi2, "p_value": p}
    return out


def response_stats(exp: dict) -> dict:
    """For 2-player simultaneous games: how each player reacts to the previous round."""
    if exp["summary"]["game"] not in ("prisoners_dilemma", "matching_pennies", "rps"):
        return {}
    rounds = [r for r in exp["rounds"] if not r["void"]]
    names = exp["rounds"][0]["players"] if exp["rounds"] else []
    out = {}
    for i, name in enumerate(names):
        j = 1 - i
        mine = [r["decisions"][i]["action"] for r in rounds]
        theirs = [r["decisions"][j]["action"] for r in rounds]
        pts = [r["points"][i] - r["points"][j] for r in rounds]
        if len(rounds) < 2:
            continue
        after_opp = defaultdict(Counter)
        for t in range(1, len(rounds)):
            after_opp[theirs[t - 1]][mine[t]] += 1
        repeats = sum(mine[t] == mine[t - 1] for t in range(1, len(mine)))
        s = {"repeat_rate": repeats / (len(mine) - 1),
             "after_opponent_action": {k: dict(v) for k, v in after_opp.items()}}
        # win-stay / lose-shift: a classic simple learning rule
        ws = [(mine[t] == mine[t - 1]) for t in range(1, len(mine)) if pts[t - 1] > 0]
        ls = [(mine[t] != mine[t - 1]) for t in range(1, len(mine)) if pts[t - 1] < 0]
        s["win_stay_rate"] = sum(ws) / len(ws) if ws else None
        s["lose_shift_rate"] = sum(ls) / len(ls) if ls else None
        if exp["summary"]["game"] == "rps":
            # best response to the opponent's previous move (what exploiting a habit looks like)
            br = [BEATS[mine[t]] == theirs[t - 1] for t in range(1, len(mine))]
            s["plays_best_response_to_last_move"] = sum(br) / len(br)
        out[name] = s
    return out


def game_specific(exp: dict) -> dict:
    game, cfg = exp["summary"]["game"], exp["config"]["game_config"]
    rounds, names = exp["rounds"], exp["summary"]["players"]
    out = {}
    if game == "monty_hall":
        doors = cfg["doors"]
        theory = {"STAY": 1 / doors, "SWITCH": (doors - 1) / doors}
        for i, n in enumerate(names):
            s = {}
            for choice, p0 in theory.items():
                wins = [r["points"][i] for r in rounds if r["info"]["final"][i] == choice]
                if wins:
                    k = int(sum(wins))
                    s[choice] = {"trials": len(wins), "win_rate": k / len(wins), "ci95": wilson(k, len(wins)),
                                 "theory": p0, "binomial_p_value": float(stats.binomtest(k, len(wins), p0).pvalue)}
            out[n] = s
    elif game == "beauty_contest":
        ratio = float(Fraction(cfg["ratio"]))  # stored as "2/3"
        for i, n in enumerate(names):
            xs = [r["info"]["numbers"][i] for r in rounds if not r["void"]]
            levels = [lv for x in xs if (lv := reasoning_level(x, ratio)) is not None]
            out[n] = {"equilibrium_choices": sum(x == cfg["low"] for x in xs), "choices": len(xs),
                      "mean_reasoning_level": statistics.fmean(levels) if levels else None}
        scored = [r for r in rounds if not r["void"]]
        if scored:
            out["target_first_round"] = scored[0]["info"]["target"]
            out["target_last_round"] = scored[-1]["info"]["target"]
    elif game == "prisoners_dilemma":
        out = exp["summary"]["game_stats"]
    elif game == "ultimatum":
        out = exp["summary"]["game_stats"]
    return out


def analyze(exp: dict) -> dict:
    s, attempts = exp["summary"], exp["attempts"]
    lat = [d["latency_ms"] for d in attempts]
    general = {"rounds": s["rounds"], "scored_rounds": s["scored_rounds"], "void_rounds": s["void_rounds"],
               "decisions": len(exp["decisions"]), "attempts": len(attempts),
               "invalid_attempts": sum(not d["valid"] for d in attempts),
               "errors": sum(d["error"] is not None for d in attempts),
               "estimated_cost_usd": s["estimated_cost_usd"]}
    players = {}
    for name in s["players"]:
        pl = [d["latency_ms"] for d in attempts if d["player"] == name]
        steps = sorted({d["step"] for d in exp["decisions"] if d["player"] == name})
        players[name] = {
            "points": s["players"][name]["points"],
            "latency_ms": {"mean": statistics.fmean(pl), "median": statistics.median(pl),
                           "p95": statistics.quantiles(pl, n=20)[-1] if len(pl) >= 2 else pl[0]} if pl else None,
            "steps": {step: player_step_stats(exp, name, step) for step in steps},
        }
    return {"experiment_id": s["experiment_id"], "game": s["game"], "condition": exp["config"]["args"]["condition"],
            "config": exp["config"]["args"], "general": general, "players": players,
            "responses": response_stats(exp), "game_specific": game_specific(exp),
            "latency_all_ms": {"mean": statistics.fmean(lat), "median": statistics.median(lat)} if lat else None}


# --- cross-experiment: position bias ---------------------------------------------------------------

def pair_key(exp: dict) -> str:
    """Experiments that differ only in option order (and round count / id / label) share a key."""
    a = {k: v for k, v in exp["config"]["args"].items()
         if k not in ("option_order", "rounds", "experiment_id", "condition", "results_dir", "max_jev_tokens")}
    return json.dumps(a, sort_keys=True)


def position_bias(exps: list[dict]) -> dict:
    """Compare each given-order experiment with its reversed-order twin.

    label_consistency:    overlap of choice distributions by option *name* (1 = same choices)
    position_consistency: overlap by *position in the list* (1 = same slots, e.g. always the first)
    mean_position:        average relative position of the chosen option (0 = first, 1 = last)
    Same choice in a different slot = a real preference; same slot with a different choice = position bias.
    A choice in the middle of the list keeps its slot when reversed, so there we can't tell.
    In one-shot games the inputs must be identical apart from order, or the pair isn't comparable
    (e.g. an Ultimatum responder who was offered a different amount).
    """
    by_key = defaultdict(dict)
    for e in exps:
        by_key[pair_key(e)][e["config"]["args"]["option_order"]] = e
    pairs = []
    for twins in by_key.values():
        if "given" not in twins or "reversed" not in twins:
            continue
        g, r = twins["given"], twins["reversed"]
        for d0 in {(d["player"], d["step"]) for d in g["decisions"]}:
            player, step = d0
            if not player.startswith(MODEL_PREFIXES):
                continue
            dist, mean_pos, states = {}, {}, {}
            for label, e in (("given", g), ("reversed", r)):
                ds = [d for d in e["decisions"] if d["player"] == player and d["step"] == step and d["valid"]]
                if not ds:
                    break
                n = len(ds)
                slots = [d["available_actions"].index(d["decision"]) for d in ds]
                dist[label] = ({a: c / n for a, c in Counter(d["decision"] for d in ds).items()},
                               {p: c / n for p, c in Counter(slots).items()})
                mean_pos[label] = statistics.fmean(s / (len(d["available_actions"]) - 1) for s, d in zip(slots, ds))
                states[label] = {json.dumps(d["state"], sort_keys=True) for d in ds}
            if len(dist) < 2:
                continue
            one_shot = not g["config"]["game_config"].get("show_history")
            lab = overlap(dist["given"][0], dist["reversed"][0])
            pos = overlap(dist["given"][1], dist["reversed"][1])
            same_slot = pos >= 0.8 or abs(mean_pos["given"] - mean_pos["reversed"]) <= 0.1
            if one_shot and states["given"] != states["reversed"]:
                verdict = "not comparable (different inputs)"
            elif lab >= 0.8 and same_slot:
                verdict = "can't tell (middle option)"
            elif lab >= 0.8:
                verdict = "preference (same choice)"
            elif same_slot:
                verdict = "position bias (same slot)"
            else:
                verdict = "mixed / unclear"
            top = lambda d: max(d, key=d.get)
            pairs.append({"experiments": [g["summary"]["experiment_id"], r["summary"]["experiment_id"]],
                          "game": g["summary"]["game"], "mode": "one-shot" if one_shot else "history",
                          "player": player, "step": step,
                          "top_given": top(dist["given"][0]), "top_reversed": top(dist["reversed"][0]),
                          "label_consistency": lab, "position_consistency": pos,
                          "mean_position_given": mean_pos["given"], "mean_position_reversed": mean_pos["reversed"],
                          "verdict": verdict})
    # overall first/last-option rates per model, across all experiments
    rates = {}
    for model in MODEL_PREFIXES:
        ds = [d for e in exps for d in e["decisions"]
              if d["player"].startswith(model) and d["valid"] and len(d["available_actions"]) > 1]
        if ds:
            rates[model] = {"decisions": len(ds),
                            "first_option_rate": statistics.fmean(d["available_actions"][0] == d["decision"] for d in ds),
                            "last_option_rate": statistics.fmean(d["available_actions"][-1] == d["decision"] for d in ds),
                            "chance_rate": statistics.fmean(1 / len(d["available_actions"]) for d in ds)}
    return {"pairs": pairs, "first_last_rates": rates}


# --- printing ---------------------------------------------------------------------------------------

def pct(x):
    return "n/a" if x is None else f"{100 * x:.0f}%"


def ci(c):
    return "" if not c else f" [{100 * c[0]:.0f}–{100 * c[1]:.0f}%]"


def num(x, d=3):
    return "n/a" if x is None else f"{x:.{d}f}"


def short(v) -> str:
    """Compact one-line rendering of nested stats: floats to 3 decimals, (lo, hi) as intervals."""
    if isinstance(v, float):
        return num(v)
    if isinstance(v, (tuple, list)) and len(v) == 2 and all(isinstance(x, float) for x in v):
        return f"[{v[0]:.3f}, {v[1]:.3f}]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {short(x)}" for k, x in v.items()) + "}"
    return str(v)


def print_full(a: dict) -> None:
    g = a["general"]
    print(f"\n{'=' * 78}\n{a['experiment_id']}  ({a['game']}, condition: {a['condition']})")
    print(f"rounds {g['rounds']} (scored {g['scored_rounds']}, void {g['void_rounds']})  decisions {g['decisions']}  "
          f"attempts {g['attempts']}  invalid {g['invalid_attempts']}  errors {g['errors']}  cost ${g['estimated_cost_usd']:.4f}")
    for name, p in a["players"].items():
        lat = p["latency_ms"]
        print(f"\n  {name}: points {p['points']:g}" +
              (f", latency mean {lat['mean']:.0f} / median {lat['median']:.0f} / p95 {lat['p95']:.0f} ms" if lat else ""))
        for step, s in p["steps"].items():
            print(f"    [{step}] {s['valid']}/{s['decisions']} valid, {s['distinct_inputs']} distinct inputs")
            freq = s["frequencies"]
            if len(freq) <= 12:
                for act, f in freq.items():
                    rep = (s.get("mean_reported_probability") or {}).get(act)
                    print(f"      {act:<10} {pct(f['share']):>5}{ci(f['ci95']):<12}  model's mean P = {num(rep, 2)}")
            else:
                print(f"      {len(freq)} different values chosen; most common: "
                      + ", ".join(f"{k}×{v['count']}" for k, v in sorted(freq.items(), key=lambda kv: -kv[1]['count'])[:5]))
            print(f"      mean confidence {num(s.get('mean_confidence'), 2)}, mean position {num(s.get('mean_position'), 2)} "
                  f"(0 = first option, 1 = last), longest streak {s.get('longest_streak', 'n/a')}")
            if "first_half" in s:
                print(f"      first half {s['first_half']}  →  second half {s['second_half']}")
            t = s.get("test_vs_equilibrium")
            if t:
                print(f"      vs equilibrium: " + (f"skipped ({t['skipped']})" if "skipped" in t else
                                                  f"chi2 = {t['chi2']:.2f}, p = {t['p_value']:.3g}"))
    if a["responses"]:
        print("\n  Reaction to the previous round")
        for name, r in a["responses"].items():
            line = f"    {name}: repeats own last action {pct(r['repeat_rate'])}, win-stay {pct(r['win_stay_rate'])}, " \
                   f"lose-shift {pct(r['lose_shift_rate'])}"
            if "plays_best_response_to_last_move" in r:
                line += f", best response to opponent's last move {pct(r['plays_best_response_to_last_move'])}"
            print(line)
            for opp, counts in r["after_opponent_action"].items():
                print(f"      after opponent {opp}: {counts}")
    if a["game_specific"]:
        print("\n  Game-specific")
        for k, v in a["game_specific"].items():
            print(f"    {k}: {short(v)}")


def overview_rows(analyses: list[dict]) -> list[dict]:
    rows = []
    for a in analyses:
        for name, p in a["players"].items():
            if not name.startswith(MODEL_PREFIXES):
                continue
            for step, s in p["steps"].items():
                freq = {k: v["share"] for k, v in s["frequencies"].items() if v["share"]}
                top = sorted(freq.items(), key=lambda kv: -kv[1])[:3]
                t = s.get("test_vs_equilibrium") or {}
                rows.append({"experiment": a["experiment_id"], "game": a["game"], "condition": a["condition"],
                             "player": name, "step": step, "n": s["valid"], "distinct_inputs": s["distinct_inputs"],
                             "top_choices": ", ".join(f"{k} {100 * v:.0f}%" for k, v in top),
                             "mean_confidence": s.get("mean_confidence"), "mean_position": s.get("mean_position"),
                             "points": p["points"], "equilibrium_p": t.get("p_value"),
                             "median_latency_ms": p["latency_ms"]["median"] if p["latency_ms"] else None})
    return rows


def print_overview(rows: list[dict]) -> None:
    print(f"\n{'experiment':<34}{'player':<8}{'step':<15}{'n':>4}{'inp':>5}  {'top choices':<34}{'conf':>5}{'pos':>5}{'eq p':>8}")
    for r in rows:
        exp = r["experiment"].split("_", 2)[-1] if r["experiment"].startswith("plan_") else r["experiment"]
        eq_p = "-" if r["equilibrium_p"] is None else f"{r['equilibrium_p']:.2g}"
        print(f"{exp[:33]:<34}{r['player'][:7]:<8}{r['step'][:14]:<15}{r['n']:>4}{r['distinct_inputs']:>5}  "
              f"{r['top_choices'][:33]:<34}{num(r['mean_confidence'], 2):>5}{num(r['mean_position'], 2):>5}{eq_p:>8}")
    print("\ninp = distinct inputs seen; conf = mean confidence; pos = mean position of the chosen option "
          "(0 first, 1 last); eq p = chi-square p-value vs the mixed equilibrium (only when inputs varied)")


def print_position_bias(pb: dict) -> None:
    if pb["first_last_rates"]:
        print("\nPosition of chosen options, all experiments")
        for model, r in pb["first_last_rates"].items():
            print(f"  {model:<5} first option {pct(r['first_option_rate'])}, last option {pct(r['last_option_rate'])} "
                  f"(chance ≈ {pct(r['chance_rate'])} each; {r['decisions']} decisions)")
    if pb["pairs"]:
        print("\nGiven vs reversed option order (same experiment otherwise)")
        print(f"  {'game':<18}{'mode':<9}{'player':<7}{'step':<15}{'top given':<10}{'top rev.':<9}"
              f"{'label':>6}{'slot':>6}{'pos g→r':>11}  verdict")
        for p in sorted(pb["pairs"], key=lambda p: (p["game"], p["mode"], p["player"], p["step"])):
            print(f"  {p['game']:<18}{p['mode']:<9}{p['player']:<7}{p['step'][:14]:<15}{p['top_given']:<10}{p['top_reversed']:<9}"
                  f"{p['label_consistency']:>6.2f}{p['position_consistency']:>6.2f}"
                  f"{p['mean_position_given']:>6.2f}→{p['mean_position_reversed']:.2f}  {p['verdict']}")
        print("  label/slot = overlap of choices by option name / by list position (1 = identical);\n"
              "  pos g→r = mean position of the choice (0 first, 1 last) with given → reversed order.\n"
              "  In history mode the two runs' histories diverge, so those comparisons are looser.")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="experiment folder(s), or a folder to search (e.g. results)")
    ap.add_argument("--match", help="only experiments whose folder name contains this text")
    ap.add_argument("--full", action="store_true", help="print the full report for every experiment")
    ap.add_argument("--csv", help="write the overview table to this CSV file")
    args = ap.parse_args(argv)

    dirs = find_experiments(args.paths, args.match)
    if not dirs:
        sys.exit("no experiments found (looked for folders containing summary.json)")
    exps = [load_experiment(d) for d in dirs]
    analyses = []
    for e in exps:
        a = analyze(e)
        (e["path"] / "analysis.json").write_text(json.dumps(a, indent=2))
        analyses.append(a)

    if len(analyses) == 1 or args.full:
        for a in analyses:
            print_full(a)
    rows = overview_rows(analyses)
    if len(analyses) > 1:
        print_overview(rows)
        pb = position_bias(exps)
        print_position_bias(pb)
        if args.match:
            out = ROOT / "results" / f"position_bias_{args.match.strip('_')}.json"
            out.write_text(json.dumps(pb, indent=2))
            print(f"\nPosition-bias details saved to {out.relative_to(ROOT)}")
    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"Overview table saved to {args.csv}")
    print(f"\nAnalyzed {len(analyses)} experiment(s); analysis.json written next to each.")


if __name__ == "__main__":
    main()
