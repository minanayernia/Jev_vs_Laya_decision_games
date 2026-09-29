"""Build a self-contained HTML viewer for saved experiments.

    python experiments/viewer.py                          # all experiments -> results/viewer.html
    python experiments/viewer.py --match plan_20260928    # only matching experiment folders
    open results/viewer.html

One tab per game; each match is shown as a conversation between the players, round by round.
The same page is served with a "Run a game" tab by experiments/app.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from games import GAMES  # noqa: E402

RESULTS = ROOT / "results"
HIDDEN_ARGS = {"results_dir", "jev_price_per_mtok", "experiment_id", "players"}

# Rough Jev tokens per decision (measured in the first plan) and Jev decisions per round,
# used only for the cost estimate in the run form.
TOKENS_PER_DECISION = {"prisoners_dilemma": 700, "matching_pennies": 700, "rps": 650,
                       "ultimatum": 650, "beauty_contest": 1100, "monty_hall": 600}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # a line still being written during a live run
    return out


def compact_probs(d: dict) -> dict | None:
    """Keep probabilities small: all options (in the order shown) when there are few, else the top 3."""
    p = d.get("probabilities")
    if not p:
        return None
    if len(p) <= 6:
        return {a: round(p.get(a, 0), 3) for a in d["available_actions"]}
    return {a: round(v, 3) for a, v in sorted(p.items(), key=lambda kv: -kv[1])[:3]}


def read_json(path: Path) -> dict | None:
    """None if the file is missing or still being written (a live run can be caught mid-write)."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load_compact(path: Path) -> dict | None:
    """One experiment folder -> the compact dict the page renders. Works on unfinished runs too."""
    cfg = read_json(path / "config.json")
    if cfg is None:
        return None
    summary = read_json(path / "summary.json")
    decisions = read_jsonl(path / "decisions.jsonl")
    rounds = read_jsonl(path / "rounds.jsonl")
    game = cfg["args"]["game"]

    if rounds:
        names = rounds[0]["players"]
    elif decisions:
        seats = {d["seat"]: d["player"] for d in decisions}
        names = [seats[s] for s in sorted(seats)]
    else:
        names = cfg["players"]
    seat_of = {n: i for i, n in enumerate(names)}

    moves_by_round: dict[int, list] = {}
    for d in decisions:
        moves_by_round.setdefault(d["round"], []).append({
            # "step" is missing in files from before the multi-game runner (Stage 1): one step, "action"
            "p": seat_of.get(d["player"], d.get("seat", 0)), "step": d.get("step", "action"), "a": d["decision"],
            "ok": d["valid"], "err": d["error"], "pr": compact_probs(d), "c": d["confidence"],
            "ms": round(d["latency_ms"]), "try": d["attempt"]})
    out_rounds = [{"n": r["round"], "roles": r.get("roles") or [None] * len(names), "points": r["points"],
                   "void": r["void"], "info": r.get("info") or {}, "moves": moves_by_round.get(r["round"], [])}
                  for r in rounds]
    done_rounds = {r["round"] for r in rounds}
    pending = [{"n": n, "moves": m} for n, m in sorted(moves_by_round.items()) if n not in done_rounds]

    exp = {"id": path.name, "game": game, "title": GAMES[game].title,
           "condition": cfg["args"].get("condition"), "created": cfg.get("created"),
           "args": {k: v for k, v in cfg["args"].items() if k not in HIDDEN_ARGS},
           "players": names, "done": summary is not None, "rounds": out_rounds, "pending": pending}
    if summary:
        exp["summary"] = {
            "rounds": summary["rounds"], "rounds_requested": summary.get("rounds_requested"),
            "void": summary["void_rounds"], "stopped_early": summary.get("stopped_early"),
            "cost": summary.get("estimated_cost_usd", 0),
            "points": {n: s["points"] for n, s in summary["players"].items()},
            "invalid": {n: s["invalid_decisions"] for n, s in summary["players"].items()},
            "latency": {n: (s["latency_ms"] or {}).get("median") for n, s in summary["players"].items()},
            "game_stats": summary.get("game_stats", {})}
    return exp


def find_experiment_dirs(match: str | None = None) -> list[Path]:
    dirs = sorted(p.parent for p in RESULTS.rglob("config.json"))
    return [d for d in dirs if (d / "summary.json").exists() and (not match or match in d.name)]


def meta() -> dict:
    """What the run form needs to know about each game."""
    return {"games": {name: {"title": g.title, "min_players": getattr(g, "min_players", 2),
                             "max_players": getattr(g, "max_players", 2),
                             "tokens_per_decision": TOKENS_PER_DECISION[name],
                             "strategic_hint": g.strategic_hint}
                      for name, g in GAMES.items()}}


def build_html(experiments: list[dict], serve_token: str | None = None) -> str:
    data = {"experiments": experiments, "serve": serve_token is not None, "token": serve_token, "meta": meta()}
    # "</" is escaped so no string in the data can close the <script> tag early
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", payload)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--match", help="only experiment folders whose name contains this text")
    ap.add_argument("--out", default=str(RESULTS / "viewer.html"))
    args = ap.parse_args(argv)
    exps = [e for d in find_experiment_dirs(args.match) if (e := load_compact(d))]
    out = Path(args.out)
    out.write_text(build_html(exps))
    print(f"Wrote {out} ({len(exps)} experiments, {out.stat().st_size / 1e6:.1f} MB). Open it in a browser.")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jev vs Laya</title>
<style>
:root {
  --bg: #f6f6f3; --panel: #ffffff; --text: #1d1d1f; --muted: #6b6b70; --border: #e2e2de;
  --jev: #0f766e; --jev-bg: #e3f3f0; --laya: #6d28d9; --laya-bg: #efe8fd;
  --other: #52525b; --other-bg: #eeeef0; --win: #15803d; --lose: #b91c1c; --accent: #2563eb;
  --bad-bg: #fdecec; --human: #c2410c; --human-bg: #fdeee3;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #131315; --panel: #1b1b1e; --text: #ececef; --muted: #9b9ba2; --border: #2d2d32;
    --jev: #5eead4; --jev-bg: #10302c; --laya: #c4b5fd; --laya-bg: #271d42;
    --other: #c4c4cc; --other-bg: #26262b; --win: #4ade80; --lose: #f87171; --accent: #60a5fa;
    --bad-bg: #3a1c1c; --human: #fdba74; --human-bg: #3a2415;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
header { padding: 18px 20px 0; max-width: 1200px; margin: 0 auto; }
header h1 { margin: 0 0 12px; font-size: 22px; }
header p { margin: 4px 0 12px; color: var(--muted); }
nav { display: flex; gap: 4px; flex-wrap: wrap; border-bottom: 1px solid var(--border); }
nav button { border: 0; background: none; color: var(--muted); padding: 9px 12px; font: inherit;
  cursor: pointer; border-bottom: 2px solid transparent; }
nav button.active { color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }
nav button .n { font-size: 12px; opacity: .7; }
main { max-width: 1200px; margin: 0 auto; padding: 16px 20px 60px; display: grid;
  grid-template-columns: 290px 1fr; gap: 20px; }
main.single { grid-template-columns: minmax(0, 1fr); }
main > * { min-width: 0; }
aside { position: sticky; top: 10px; align-self: start; max-height: calc(100vh - 20px); overflow: auto; }
aside h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); margin: 14px 0 6px; }
.exp { display: block; width: 100%; text-align: left; border: 1px solid transparent; background: none;
  color: inherit; font: inherit; padding: 7px 9px; border-radius: 8px; cursor: pointer; }
.exp:hover { background: var(--panel); }
.exp.active { background: var(--panel); border-color: var(--border); }
.exp .t { font-weight: 600; font-size: 14px; }
.exp .d { font-size: 12px; color: var(--muted); overflow-wrap: anywhere; }
.panel { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
.head h2 { margin: 0 0 4px; font-size: 19px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
.chip { font-size: 12px; padding: 2px 8px; border-radius: 999px; background: var(--other-bg); color: var(--muted); }
.board { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 190px), 1fr)); gap: 10px; margin-top: 12px; }
.card { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; }
.card .name { font-weight: 700; }
.card .pts { font-size: 24px; font-weight: 700; }
.jev .name, .jev .pts { color: var(--jev); }
.laya .name, .laya .pts { color: var(--laya); }
.bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; background: var(--other-bg); margin: 4px 0 2px; }
.bar span { height: 100%; }
.legend { font-size: 12px; color: var(--muted); }
.small { font-size: 12px; color: var(--muted); }
.stats { margin-top: 10px; font-size: 13px; color: var(--muted); overflow-wrap: anywhere; }
.controls { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 14px 0 6px; }
.controls select { font: inherit; padding: 5px 8px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--panel); color: var(--text); }
.controls button, .btn { font: inherit; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--panel); color: var(--text); cursor: pointer; }
.btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn:disabled { opacity: .5; cursor: default; }
.chat { margin-top: 8px; }
.round { margin: 14px 0; }
.round.hidden { display: none; }
.divider { text-align: center; font-size: 12px; color: var(--muted); margin: 10px 0 6px; }
.divider b { color: var(--text); }
.msg { display: flex; margin: 6px 0; }
.msg.right { justify-content: flex-end; }
.bubble { max-width: min(460px, 78%); padding: 8px 12px; border-radius: 14px; }
.msg.left .bubble { border-bottom-left-radius: 4px; }
.msg.right .bubble { border-bottom-right-radius: 4px; }
.bubble.jev { background: var(--jev-bg); }
.bubble.laya { background: var(--laya-bg); }
.bubble.other { background: var(--other-bg); }
.bubble.invalid { background: var(--bad-bg); }
.who { font-size: 12px; font-weight: 700; margin-bottom: 1px; }
.jev .who { color: var(--jev); } .laya .who { color: var(--laya); } .other .who { color: var(--other); }
.say { font-size: 16px; }
.meta { font-size: 11.5px; color: var(--muted); margin-top: 3px; }
.probs { display: none; margin-top: 5px; }
.show-probs .probs { display: block; }
.prow { display: grid; grid-template-columns: 80px 1fr 38px; gap: 6px; align-items: center; font-size: 11.5px; color: var(--muted); }
.prow .pb { height: 6px; background: var(--other-bg); border-radius: 3px; overflow: hidden; }
.prow .pb span { display: block; height: 100%; background: currentColor; opacity: .55; }
.sys { text-align: center; font-size: 13px; color: var(--muted); margin: 8px 0; }
.sys .w { color: var(--win); font-weight: 600; } .sys .l { color: var(--lose); font-weight: 600; }
.pending { opacity: .7; }
.empty { color: var(--muted); padding: 30px; text-align: center; }
form.run { display: grid; gap: 12px; max-width: 640px; }
form.run label { display: grid; gap: 4px; font-size: 13px; color: var(--muted); }
form.run input, form.run select { font: inherit; padding: 7px 9px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--bg); color: var(--text); }
.row { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.seat { display: flex; gap: 6px; align-items: center; }
.seat select, .seat input { flex: 1; }
.bubble.human { background: var(--human-bg); }
.human .who, .human .name, .human .pts { color: var(--human); }
details.about { grid-column: 1 / -1; padding: 0; }
details.about summary { cursor: pointer; padding: 12px 16px; font-weight: 600; list-style: none; }
details.about summary::-webkit-details-marker { display: none; }
details.about summary::before { content: "▸ "; color: var(--muted); }
details.about[open] summary::before { content: "▾ "; }
.about-body { display: grid; grid-template-columns: minmax(0, 380px) minmax(0, 1fr); gap: 18px; padding: 0 16px 16px; align-items: start; }
.about-body h4 { margin: 0 0 2px; font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
.about-body p { margin: 0 0 10px; }
svg.ill { width: 100%; height: auto; }
svg.ill text { fill: var(--text); font: 12px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
svg.ill .m { fill: var(--muted); } svg.ill .b { font-weight: 700; } svg.ill .big { font-size: 20px; font-weight: 700; }
svg.ill .w { fill: var(--win); } svg.ill .l { fill: var(--lose); } svg.ill .a { fill: var(--accent); }
svg.ill .cell { fill: var(--other-bg); stroke: var(--border); }
svg.ill .good { fill: var(--jev-bg); } svg.ill .eq { stroke: var(--accent); stroke-width: 2; }
svg.ill .ln { stroke: var(--muted); fill: none; stroke-width: 1.5; }
svg.ill .axis { stroke: var(--text); stroke-width: 1.5; }
svg.ill .coin { fill: #f5c542; stroke: #b98b0a; stroke-width: 2; }
svg.ill .coin-t { fill: #d9dde3; stroke: #8a929c; stroke-width: 2; }
svg.ill text.ct { fill: #3b2f00; font-weight: 700; font-size: 16px; }
svg.ill .door { fill: #a8672f; stroke: #6b3d15; stroke-width: 2; }
svg.ill .door-open { fill: var(--other-bg); stroke: var(--border); stroke-width: 2; }
svg.ill .pick { stroke: var(--accent); stroke-width: 3; }
svg.ill .p1 { fill: var(--accent); } svg.ill .p2 { fill: #f59e0b; }
.modes { display: inline-flex; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.modes button { border: 0; background: var(--panel); color: var(--muted); font: inherit; padding: 8px 14px; cursor: pointer; }
.modes button.on { background: var(--accent); color: #fff; }
.qcard { border: 2px solid var(--human); }
.qcard h3 { margin: 0 0 2px; color: var(--human); }
.state { display: grid; grid-template-columns: 150px minmax(0, 1fr); gap: 4px 12px; margin: 10px 0; font-size: 14px; }
.state .skey { color: var(--muted); }
.state ul { margin: 0; padding-left: 18px; }
table.hist { border-collapse: collapse; font-size: 12.5px; }
table.hist th, table.hist td { border-bottom: 1px solid var(--border); padding: 3px 8px; text-align: left; }
.qtext { font-size: 16px; font-weight: 600; margin: 10px 0; }
.qopts { display: flex; flex-wrap: wrap; gap: 8px; }
.qopts .opt { display: grid; text-align: left; min-width: 120px; }
.qopts.many .opt { min-width: 52px; text-align: center; }
.qopts .opt span { font-size: 12px; color: var(--muted); }
.fld { display: grid; gap: 4px; align-content: start; }
.hint { font-size: 12px; color: var(--muted); }
.hint.ok { color: var(--win); } .hint.warn { color: var(--lose); }
details.help summary { font-size: 12px; color: var(--accent); cursor: pointer; }
details.help > div { font-size: 12.5px; line-height: 1.5; margin-top: 4px; padding: 8px 10px; border-radius: 8px; background: var(--bg); }
pre.log { white-space: pre-wrap; font-size: 12px; background: var(--bg); padding: 10px; border-radius: 8px; max-height: 240px; overflow: auto; }
@media (max-width: 800px) {
  main { grid-template-columns: minmax(0, 1fr); padding: 12px 16px 50px; }
  aside { position: static; max-height: none; }
  header { padding: 14px 16px 0; }
  .bubble { max-width: 88%; }
  .about-body { grid-template-columns: minmax(0, 1fr); }
  .state { grid-template-columns: minmax(0, 1fr); }
}
</style>
</head>
<body>
<header>
  <h1>Jev vs Laya: Decision Games</h1>
  <nav id="tabs"></nav>
</header>
<main id="main"></main>
<script>
const DATA = __DATA__;
const GAMES = ["prisoners_dilemma", "matching_pennies", "rps", "ultimatum", "beauty_contest", "monty_hall"];
const TITLES = {prisoners_dilemma: "Prisoner's Dilemma", matching_pennies: "Matching Pennies", rps: "Rock Paper Scissors",
  ultimatum: "Ultimatum", beauty_contest: "Beauty Contest", monty_hall: "Monty Hall"};
const PALETTE = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4", "#84cc16", "#ec4899"];

// ---- tiny DOM helper: h("div", {class: "x"}, child, "text") -------------------------------------
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "style") e.style.cssText = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) e.append(c instanceof Node ? c : String(c));
  return e;
}
const kind = name => name.startsWith("jev") ? "jev" : name.startsWith("laya") ? "laya" : name === "you" ? "human" : "other";
const cap = s => s.charAt(0) + s.slice(1).toLowerCase();
const fmtPts = x => (x > 0 ? "+" : "") + (Math.round(x * 100) / 100);
const pct = x => Math.round(100 * x) + "%";
const doorName = i => "Door " + (i + 1);

// ---- what each player "says" ---------------------------------------------------------------------
function say(exp, r, m) {
  const a = m.a, g = exp.game;
  if (!m.ok) return `“${a ?? "(no answer)"}” (invalid${m.err ? ": " + m.err : ""})`;
  if (g === "prisoners_dilemma") return a === "COOPERATE" ? "I cooperate." : "I defect.";
  if (g === "matching_pennies") return cap(a) + ".";
  if (g === "rps") return cap(a) + "!";
  if (g === "ultimatum") {
    const pie = exp.args.pie ?? 10;
    if (m.step === "offer") return `I offer you ${a} of ${pie} and keep ${pie - a}.`;
    return a === "ACCEPT" ? "I accept." : "I reject.";
  }
  if (g === "beauty_contest") return `My number is ${a}.`;
  if (g === "monty_hall") {
    if (m.step === "first_pick") return `I pick Door ${a.split("_")[1]}.`;
    const pick = r.info?.picks?.[m.p], other = otherDoor(exp, r, m.p);
    if (pick == null) return a === "STAY" ? "I stay." : "I switch.";
    return a === "STAY" ? `I stay with ${doorName(pick)}.` : `I switch to ${doorName(other)}.`;
  }
  return a;
}
function otherDoor(exp, r, p) {
  const n = exp.args.doors ?? 3, opened = new Set(r.info?.opened?.[p] || []), pick = r.info?.picks?.[p];
  for (let d = 0; d < n; d++) if (d !== pick && !opened.has(d)) return d;
  return null;
}
function roleOf(r, p) { return r.roles && r.roles[p] ? r.roles[p] : null; }

// ---- the game narrating the outcome ---------------------------------------------------------------
function narrate(exp, r) {
  const P = exp.players, g = exp.game;
  if (r.void) return [h("span", {class: "l"}, "No outcome: a decision was invalid.")];
  const acts = P.map((_, i) => { const m = r.moves.filter(m => m.p === i && m.ok).pop(); return m && m.a; });
  const scoreLine = () => P.map((n, i) => r.points[i] == null ? null :
      h("span", {class: r.points[i] > 0 ? "w" : r.points[i] < 0 ? "l" : ""}, `${n} ${fmtPts(r.points[i])}`))
    .filter(Boolean).flatMap((x, i) => i ? [" · ", x] : [x]);
  if (g === "prisoners_dilemma") {
    const [a, b] = acts, label = a === b ? (a === "COOPERATE" ? "Mutual cooperation." : "Mutual defection.")
      : `${a === "DEFECT" ? P[0] : P[1]} exploits ${a === "DEFECT" ? P[1] : P[0]}.`;
    return [label + " ", ...scoreLine()];
  }
  if (g === "matching_pennies" || g === "rps") {
    const w = r.points[0] > r.points[1] ? 0 : r.points[1] > r.points[0] ? 1 : -1;
    if (w < 0) return [`${cap(acts[0])} vs ${cap(acts[1])}: draw.`];
    const why = g === "rps" ? `${cap(acts[w])} beats ${cap(acts[1 - w]).toLowerCase()}` :
      (acts[0] === acts[1] ? "Coins match" : "Coins differ");
    return [`${why} → `, h("span", {class: "w"}, `${P[w]} wins`), roleOf(r, w) ? ` (${roleOf(r, w)})` : "", "."];
  }
  if (g === "ultimatum") {
    if (exp.args.ultimatum_mode === "sweep") {
      return [`Offer of ${r.info.offer}: `, ...P.flatMap((n, i) => {
        const res = r.info.responses?.[i]; if (!res) return [];
        return [i ? " · " : "", h("span", {class: res === "ACCEPT" ? "w" : "l"}, `${n} ${res === "ACCEPT" ? "accepts" : "rejects"}`)];
      })];
    }
    return r.info.response === "ACCEPT" ? ["Deal! ", ...scoreLine()] : [h("span", {class: "l"}, "Rejected. Both get 0.")];
  }
  if (g === "beauty_contest") {
    const w = (r.info.winners || []).map(i => P[i]).join(" & ");
    return [`Average ${r.info.average.toFixed(1)} → target ${r.info.target.toFixed(1)} → `,
      h("span", {class: "w"}, `${w} ${r.info.winners.length > 1 ? "share the point" : "wins"}`), "."];
  }
  return scoreLine();
}

// ---- rendering one experiment as a chat ---------------------------------------------------------
function probsBlock(m) {
  if (!m.pr) return null;
  return h("div", {class: "probs"}, Object.entries(m.pr).map(([k, v]) =>
    h("div", {class: "prow"}, h("span", {}, k), h("div", {class: "pb"}, h("span", {style: `width:${v * 100}%`})), h("span", {}, pct(v)))));
}
function bubble(exp, r, m) {
  const name = exp.players[m.p], k = kind(name), side = m.p === 1 ? "right" : "left";
  const role = roleOf(r, m.p);
  const bits = [];
  if (m.c != null) bits.push(`confidence ${m.c.toFixed(2)}`);
  if (m.ms) bits.push(`${m.ms} ms`);
  if (m.try > 1) bits.push(`attempt ${m.try}`);
  return h("div", {class: `msg ${side}`},
    h("div", {class: `bubble ${m.ok ? k : "invalid"} ${k}`},
      h("div", {class: "who"}, name, role ? ` · ${role.toLowerCase()}` : ""),
      h("div", {class: "say"}, say(exp, r, m)),
      bits.length ? h("div", {class: "meta"}, bits.join(" · ")) : null,
      probsBlock(m)));
}
function roundBlock(exp, r, pending) {
  const kids = [h("div", {class: "divider"}, h("b", {}, `Round ${r.n}`), pending ? " · in progress…" : "")];
  if (exp.game === "monty_hall" && !pending) {
    for (const m of r.moves) {
      kids.push(bubble(exp, r, m));
      if (m.step === "first_pick" && m.ok && r.info.opened?.[m.p]) {
        const op = r.info.opened[m.p];
        const list = op.length <= 8 ? op.map(doorName).join(", ") : `${op.length} doors`;
        kids.push(h("div", {class: "sys"}, `Host opens ${list}: all empty. Still closed: ${doorName(r.info.picks[m.p])} and ${doorName(otherDoor(exp, r, m.p))}.`));
      }
      if (m.step === "stay_or_switch" && m.ok) {
        const won = r.points?.[m.p] === 1;
        kids.push(h("div", {class: "sys"}, `Prize behind ${doorName(r.info.prize)} → `,
          h("span", {class: won ? "w" : "l"}, `${exp.players[m.p]} ${won ? "wins" : "loses"}`), "."));
      }
    }
    if (exp.args.initial_choice === "random") kids.splice(1, 0, h("div", {class: "sys"}, "First doors were picked at random by the game."));
  } else {
    for (const m of r.moves) kids.push(bubble(exp, r, m));
    if (!pending) kids.push(h("div", {class: "sys"}, narrate(exp, r)));
  }
  return h("div", {class: "round" + (pending ? " pending" : "")}, kids);
}

function totals(exp) {
  const pts = exp.players.map(() => 0);
  for (const r of exp.rounds) if (r.points) r.points.forEach((x, i) => { if (x != null) pts[i] += x; });
  return pts;
}
function actionCounts(exp, i) {
  const by = {};
  for (const r of exp.rounds) for (const m of r.moves) if (m.p === i && m.ok) {
    by[m.step] = by[m.step] || {}; by[m.step][m.a] = (by[m.step][m.a] || 0) + 1;
  }
  return by;
}
function colorMap(exp) {
  // one colour per option name, shared by all players, so ROCK looks the same on every card
  const names = new Set();
  for (const r of exp.rounds) for (const m of r.moves) if (m.ok) names.add(m.a);
  const sorted = [...names].sort((a, b) => (+a - +b) || a.localeCompare(b));
  return Object.fromEntries(sorted.map((a, j) => [a, PALETTE[j % PALETTE.length]]));
}
function scoreCard(exp, i, pts, colors) {
  const name = exp.players[i], rows = [];
  for (const [step, counts] of Object.entries(actionCounts(exp, i))) {
    const total = Object.values(counts).reduce((a, b) => a + b, 0), keys = Object.keys(counts);
    if (keys.length > 6 && keys.every(k => /^\d+$/.test(k))) {
      const vals = keys.flatMap(k => Array(counts[k]).fill(+k));
      rows.push(h("div", {class: "legend"}, `${step}: mean ${(vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(1)}, n=${total}`));
      continue;
    }
    const sorted = keys.sort((a, b) => counts[b] - counts[a]);
    rows.push(h("div", {class: "small"}, step),
      h("div", {class: "bar"}, sorted.map(k => h("span", {style: `width:${100 * counts[k] / total}%;background:${colors[k]}`, title: `${k} ${counts[k]}`}))),
      h("div", {class: "legend"}, sorted.map(k => [h("span", {style: `color:${colors[k]}`}, "■ "), `${k} ${pct(counts[k] / total)}  `])));
  }
  const s = exp.summary, lat = s?.latency?.[name];
  return h("div", {class: `card ${kind(name)}`}, h("div", {class: "name"}, name), h("div", {class: "pts"}, fmtPts(pts[i])),
    h("div", {class: "small"}, "points"), rows,
    h("div", {class: "small", style: "margin-top:4px"},
      [lat != null ? `median ${Math.round(lat)} ms` : null, s ? `invalid ${s.invalid[name] ?? 0}` : null].filter(Boolean).join(" · ")));
}
function describe(exp) {
  const a = exp.args, parts = [`${exp.players.join(" vs ")}`, `${exp.done ? exp.summary.rounds : exp.rounds.length} rounds`,
    a.mode === "one-shot" ? "no history" : "with history"];
  if (a.prompt === "strategic") parts.push("strategic prompt");
  if (a.option_order === "reversed") parts.push("options reversed");
  if (exp.game === "prisoners_dilemma" && a.payoffs && a.payoffs !== "3,0,5,1") parts.push(`payoffs ${a.payoffs}`);
  if (exp.game === "ultimatum" && a.ultimatum_mode === "sweep") parts.push("sweep");
  if (exp.game === "monty_hall") parts.push(`${a.doors} doors`);
  if (exp.game === "beauty_contest" && a.grid_step > 1) parts.push(`step ${a.grid_step}`);
  if (a.seed) parts.push(`seed ${a.seed}`);
  return parts.join(" · ");
}
function gameStats(exp) {
  const gs = exp.summary?.game_stats; if (!gs) return null;
  const fmt = v => typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(3)) :
    v && typeof v === "object" ? Object.entries(v).map(([k, x]) => `${k}: ${fmt(x)}`).join(", ") : String(v);
  return h("div", {class: "stats"}, Object.entries(gs).map(([k, v]) => h("div", {}, h("b", {}, k + ": "), fmt(v))));
}

function renderExperiment(exp, target, opts = {}) {
  target.innerHTML = "";
  const pts = totals(exp);
  const chat = h("div", {class: "chat"});
  const head = h("div", {class: "head"},
    h("h2", {}, exp.title, opts.live ? "" : ""), h("div", {class: "small"}, exp.id),
    h("div", {class: "chips"}, [exp.condition, describe(exp), exp.summary?.cost ? `Jev cost $${exp.summary.cost.toFixed(4)}` : null,
      exp.summary?.stopped_early ? "stopped early: budget" : null].filter(Boolean).map(t => h("span", {class: "chip"}, t))));
  const colors = colorMap(exp);
  const board = h("div", {class: "board"}, exp.players.map((_, i) => scoreCard(exp, i, pts, colors)));
  let timer = null;
  const probsBox = h("input", {type: "checkbox", onchange: e => chat.classList.toggle("show-probs", e.target.checked)});
  const replay = h("button", {onclick: () => {
    clearInterval(timer);
    const rs = [...chat.querySelectorAll(".round")]; rs.forEach(x => x.classList.add("hidden"));
    let i = 0;
    timer = setInterval(() => {
      if (i >= rs.length) return clearInterval(timer);
      rs[i].classList.remove("hidden"); rs[i].scrollIntoView({block: "nearest", behavior: "smooth"}); i++;
    }, +speed.value);
  }}, "▶ Replay");
  const speed = h("select", {}, h("option", {value: 1200}, "slow"), h("option", {value: 600, selected: true}, "normal"), h("option", {value: 150}, "fast"));
  const all = h("button", {onclick: () => { clearInterval(timer); chat.querySelectorAll(".round").forEach(x => x.classList.remove("hidden")); }}, "Show all");
  const controls = opts.live ? h("div", {class: "controls"}, h("label", {}, probsBox, " show probabilities")) :
    h("div", {class: "controls"}, replay, speed, all, h("label", {}, probsBox, " show probabilities"));
  for (const r of exp.rounds) chat.append(roundBlock(exp, r, false));
  for (const r of exp.pending || []) chat.append(roundBlock(exp, r, true));
  if (!exp.rounds.length && !(exp.pending || []).length) chat.append(h("div", {class: "empty"}, opts.live ? "Starting… (loading models)" : "No rounds."));
  target.append(h("div", {class: "panel"}, head, board, gameStats(exp), controls, chat));
  if (opts.keepProbs) { probsBox.checked = true; chat.classList.add("show-probs"); }
  return {chat, probsBox};
}

// ---- tabs, sidebar, routing ------------------------------------------------------------------------
const byGame = {};
for (const e of DATA.experiments) (byGame[e.game] = byGame[e.game] || []).push(e);
function groupOf(e) {
  const m = e.id.match(/^plan_(\d{8})-(\d{4})_/);
  if (m) return `Plan ${m[1].slice(0, 4)}-${m[1].slice(4, 6)}-${m[1].slice(6)} ${m[2].slice(0, 2)}:${m[2].slice(2)}`;
  if (e.id.startsWith("app_")) return "Runs from the app";
  return "Other runs";
}
function shortName(e) { return e.id.replace(/^plan_\d{8}-\d{4}_/, "").replace(/^app_/, ""); }

function route() {
  const q = new URLSearchParams(location.hash.slice(1));
  return {tab: q.get("tab") || GAMES.find(g => byGame[g]) || (DATA.serve ? "run" : GAMES[0]), exp: q.get("exp")};
}
function go(tab, exp) { location.hash = new URLSearchParams(exp ? {tab, exp} : {tab}).toString(); }

function renderTabs(active) {
  const nav = document.getElementById("tabs"); nav.innerHTML = "";
  for (const g of GAMES) nav.append(h("button", {class: g === active ? "active" : "", onclick: () => go(g)},
    TITLES[g], " ", h("span", {class: "n"}, `(${(byGame[g] || []).length})`)));
  if (DATA.serve) nav.append(h("button", {class: active === "run" ? "active" : "", onclick: () => go("run")}, "▶ Play or watch a game"));
}

function renderGameTab(game, expId) {
  const main = document.getElementById("main"); main.className = ""; main.innerHTML = "";
  main.append(aboutCard(game));
  const exps = byGame[game] || [];
  if (!exps.length) {
    main.className = "single";
    main.append(h("div", {class: "panel empty"}, `No ${TITLES[game]} experiments yet.`,
      DATA.serve ? h("div", {}, h("button", {class: "btn", onclick: () => go("run")}, "Run one")) : " Run one with experiments/run_tournament.py or experiments/app.py."));
    return;
  }
  const groups = {};
  for (const e of exps) (groups[groupOf(e)] = groups[groupOf(e)] || []).push(e);
  const rank = g => g.startsWith("Plan") ? 0 : g.startsWith("Runs from") ? 1 : 2;
  const order = Object.keys(groups).sort((a, b) => rank(a) - rank(b) || b.localeCompare(a));
  for (const g of order) groups[g].sort((a, b) => a.id.localeCompare(b.id));
  const current = exps.find(e => e.id === expId) || groups[order[0]][0];
  const aside = h("aside");
  for (const g of order) {
    const list = groups[g];
    aside.append(h("h3", {}, g));
    for (const e of list)
      aside.append(h("button", {class: "exp" + (e === current ? " active" : ""), onclick: () => go(game, e.id)},
        h("div", {class: "t"}, shortName(e)), h("div", {class: "d"}, describe(e))));
  }
  const content = h("section");
  main.append(aside, content);
  renderExperiment(current, content);
}

// ---- "About this game" cards ------------------------------------------------------------------------
const ABOUT = {
  prisoners_dilemma: {
    how: "Both players secretly choose to <b>cooperate</b> or <b>defect</b>; then the choices are revealed and points are paid out according to the table.",
    theory: "Whatever the opponent does, defecting pays more (5 &gt; 3 and 1 &gt; 0), so a purely selfish player always defects. But if both reason that way, each gets 1 instead of 3. That is the dilemma. When the game is repeated, strategies such as <i>tit-for-tat</i> (copy the opponent's last move) can keep cooperation going.",
    look: "Does a model cooperate at all? Does it retaliate after being exploited, or forgive? Does seeing the history change anything?",
    svg: `<svg viewBox="0 0 380 200" class="ill" role="img" aria-label="Payoff table: both cooperate 3 and 3; cooperate against defect 0 and 5; both defect 1 and 1">
      <text x="245" y="16" class="b" text-anchor="middle">Opponent</text>
      <text x="185" y="40" class="m" text-anchor="middle">cooperates</text>
      <text x="305" y="40" class="m" text-anchor="middle">defects</text>
      <text x="18" y="122" class="b" text-anchor="middle" transform="rotate(-90 18 122)">You</text>
      <text x="80" y="89" class="m" text-anchor="middle">cooperate</text>
      <text x="80" y="159" class="m" text-anchor="middle">defect</text>
      <rect x="127" y="50" width="116" height="66" rx="8" class="cell good"/>
      <rect x="247" y="50" width="116" height="66" rx="8" class="cell"/>
      <rect x="127" y="120" width="116" height="66" rx="8" class="cell"/>
      <rect x="247" y="120" width="116" height="66" rx="8" class="cell eq"/>
      <text x="185" y="86" class="big" text-anchor="middle">3 / 3</text><text x="185" y="104" class="m" text-anchor="middle">best together</text>
      <text x="305" y="86" class="big" text-anchor="middle">0 / 5</text><text x="305" y="104" class="m" text-anchor="middle">you're exploited</text>
      <text x="185" y="156" class="big" text-anchor="middle">5 / 0</text><text x="185" y="174" class="m" text-anchor="middle">you exploit</text>
      <text x="305" y="156" class="big" text-anchor="middle">1 / 1</text><text x="305" y="174" class="a" text-anchor="middle">equilibrium</text>
      <text x="190" y="198" class="m" text-anchor="middle">(your points / opponent's points)</text>
    </svg>`},
  matching_pennies: {
    how: "Each player shows <b>heads</b> or <b>tails</b> at the same time. The <b>matcher</b> wins when the coins match, the <b>mismatcher</b> when they differ. Roles swap every round.",
    theory: "Any pattern can be exploited by the other side, so the only equilibrium is to be perfectly unpredictable: 50% heads, 50% tails.",
    look: "A favourite side (always heads?), long streaks, and whether a model reacts to what the opponent just did.",
    svg: `<svg viewBox="0 0 380 190" class="ill" role="img" aria-label="Same sides: matcher wins. Different sides: mismatcher wins.">
      <circle cx="65" cy="60" r="26" class="coin"/><text x="65" y="66" class="ct" text-anchor="middle">H</text>
      <circle cx="125" cy="60" r="26" class="coin"/><text x="125" y="66" class="ct" text-anchor="middle">H</text>
      <text x="95" y="112" text-anchor="middle">same side</text><text x="95" y="130" class="w b" text-anchor="middle">MATCHER wins</text>
      <circle cx="255" cy="60" r="26" class="coin"/><text x="255" y="66" class="ct" text-anchor="middle">H</text>
      <circle cx="315" cy="60" r="26" class="coin-t"/><text x="315" y="66" class="ct" text-anchor="middle">T</text>
      <text x="285" y="112" text-anchor="middle">different sides</text><text x="285" y="130" class="w b" text-anchor="middle">MISMATCHER wins</text>
      <rect x="90" y="152" width="100" height="12" class="p1"/><rect x="190" y="152" width="100" height="12" class="p2"/>
      <text x="190" y="184" class="m" text-anchor="middle">equilibrium: 50% heads · 50% tails</text>
    </svg>`},
  rps: {
    how: "Both players pick <b>rock</b>, <b>paper</b> or <b>scissors</b> at the same time. Rock beats scissors, scissors beats paper, paper beats rock; the same choice is a draw.",
    theory: "Equilibrium: play each move a third of the time. A player with a favourite move can be beaten by always playing the move that beats it.",
    look: "Favourite moves, and whether a model learns to beat an opponent's habit (for example answering ROCK with PAPER).",
    svg: `<svg viewBox="0 0 380 200" class="ill" role="img" aria-label="Rock beats scissors, scissors beats paper, paper beats rock">
      <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs>
      <g style="color: var(--muted)">
        <path d="M212,52 L292,132" class="ln" marker-end="url(#arr)"/>
        <path d="M262,160 L118,160" class="ln" marker-end="url(#arr)"/>
        <path d="M88,132 L168,52" class="ln" marker-end="url(#arr)"/>
      </g>
      <circle cx="190" cy="36" r="26" class="cell"/><text x="190" y="44" text-anchor="middle" style="font-size:24px">✊</text>
      <circle cx="310" cy="158" r="26" class="cell"/><text x="310" y="166" text-anchor="middle" style="font-size:24px">✌️</text>
      <circle cx="70" cy="158" r="26" class="cell"/><text x="70" y="166" text-anchor="middle" style="font-size:24px">✋</text>
      <text x="232" y="36" class="b">Rock</text><text x="296" y="198" class="b" text-anchor="middle">Scissors</text><text x="70" y="198" class="b" text-anchor="middle">Paper</text>
      <text x="262" y="86" class="m">beats</text><text x="190" y="152" class="m" text-anchor="middle">beats</text><text x="98" y="86" class="m" text-anchor="end">beats</text>
    </svg>`},
  ultimatum: {
    how: "The <b>proposer</b> splits 10 points by offering some to the <b>responder</b>. If the responder accepts, both get the split; if they reject, <b>both get nothing</b>.",
    theory: "A responder who only cares about points accepts anything above 0, so a purely rational proposer offers the minimum. People don't play like that: typical offers are 4–5, and offers below 2–3 are often rejected as unfair.",
    look: "What models offer, and the lowest offer they accept. <i>Sweep</i> mode puts every split from 0 to 10 to the responder to find that threshold.",
    svg: `<svg viewBox="0 0 380 190" class="ill" role="img" aria-label="Proposer keeps 7 and offers 3; accept gives 7 and 3, reject gives 0 and 0">
      <text x="30" y="24" class="b">Proposer offers 3 of 10</text>
      ${Array.from({length: 10}, (_, i) => `<rect x="${30 + i * 32}" y="36" width="30" height="30" rx="4" class="${i < 7 ? "p1" : "p2"}"/>`).join("")}
      <text x="140" y="84" class="m" text-anchor="middle">proposer keeps 7</text><text x="302" y="84" class="m" text-anchor="middle">responder gets 3</text>
      <path d="M190,96 L110,128" class="ln"/><path d="M190,96 L270,128" class="ln"/>
      <text x="110" y="148" class="w b" text-anchor="middle">ACCEPT</text><text x="110" y="166" text-anchor="middle">7 / 3</text>
      <text x="270" y="148" class="l b" text-anchor="middle">REJECT</text><text x="270" y="166" text-anchor="middle">0 / 0</text>
    </svg>`},
  beauty_contest: {
    how: "Every player picks a number from 0 to 100. The <b>target is 2/3 of the average</b> of all numbers; whoever is closest wins.",
    theory: "If others pick at random (average 50), you should pick 33. If they all think that, pick 22… Repeating this reasoning leads to 0, the only Nash equilibrium. Real people usually stop after one or two steps, choosing numbers around 20–35.",
    look: "How many reasoning steps a model takes (the analysis reports this as <i>level-k</i>), and whether picking 0 actually wins against players who are less “rational”.",
    svg: `<svg viewBox="0 0 380 200" class="ill" role="img" aria-label="Reasoning ladder: 50, 33, 22, 15, 10, down to 0">
      <text x="20" y="16" class="b">Each step of reasoning: × 2/3</text>
      ${[["level 0", 50, "(random)"], ["level 1", 33.3, ""], ["level 2", 22.2, ""], ["level 3", 14.8, ""], ["level 4", 9.9, ""]].map(([t, v, note], i) => {
        const y = 34 + i * 28, w = 4.0 * v;
        return `<text x="20" y="${y + 13}" class="m">${t}</text><rect x="80" y="${y}" width="${w}" height="18" rx="3" class="p1" opacity="${1 - i * 0.15}"/>` +
               `<text x="${86 + w}" y="${y + 13}" class="b">${Math.round(v)}</text>` + (note ? `<text x="${112 + w}" y="${y + 13}" class="m">${note}</text>` : "");
      }).join("")}
      <text x="20" y="${34 + 5 * 28 + 4}" class="m">…</text>
      <text x="20" y="${34 + 5 * 28 + 24}" class="a b">∞</text><circle cx="84" cy="${34 + 5 * 28 + 19}" r="5" class="p2"/>
      <text x="96" y="${34 + 5 * 28 + 24}" class="a b">0 = Nash equilibrium</text>
    </svg>`},
  monty_hall: {
    how: "A prize is behind one of three doors. You pick one. The host, <b>who knows where the prize is</b>, opens one of the other doors, which is always empty. Then you may <b>stay</b> or <b>switch</b>.",
    theory: "Switching wins 2/3 of the time. Your first pick is right only 1/3 of the time; in every other case the prize is behind the door the host left closed. With N doors, switching wins (N−1)/N.",
    look: "Does a model switch? Do its measured win rates match 1/3 (staying) and 2/3 (switching)?",
    svg: `<svg viewBox="0 0 380 200" class="ill" role="img" aria-label="Three doors: your pick, one closed door, one opened empty door">
      <rect x="40" y="36" width="80" height="116" rx="4" class="door pick"/><circle cx="108" cy="96" r="4" fill="#f5d27a"/>
      <text x="80" y="28" class="a b" text-anchor="middle">your pick</text><text x="80" y="100" class="big" text-anchor="middle" style="fill:#fff">1</text>
      <rect x="150" y="36" width="80" height="116" rx="4" class="door"/><circle cx="218" cy="96" r="4" fill="#f5d27a"/>
      <text x="190" y="100" class="big" text-anchor="middle" style="fill:#fff">2</text>
      <rect x="260" y="36" width="80" height="116" rx="4" class="door-open"/>
      <text x="300" y="98" class="m" text-anchor="middle">empty</text><text x="300" y="28" class="m" text-anchor="middle">host opens</text>
      <text x="80" y="176" text-anchor="middle">stay: wins <tspan class="l b">1/3</tspan></text>
      <text x="190" y="176" text-anchor="middle">switch: wins <tspan class="w b">2/3</tspan></text>
    </svg>`},
};

function aboutCard(game) {
  const a = ABOUT[game], key = "about-open-" + game;
  let open = true;
  try { open = localStorage.getItem(key) !== "0"; } catch (e) { /* storage may be blocked; default open */ }
  const body = h("div", {class: "about-body"}, h("div", {}),
    h("div", {}, h("h4", {}, "How it works"), h("p", {}), h("h4", {}, "What theory says"), h("p", {}), h("h4", {}, "What to look for"), h("p", {})));
  body.firstChild.innerHTML = a.svg;  // our own static SVG markup
  const ps = body.querySelectorAll("p");
  ps[0].innerHTML = a.how; ps[1].innerHTML = a.theory; ps[2].innerHTML = a.look;
  const d = h("details", {class: "panel about", open: open || null}, h("summary", {}, `About ${TITLES[game]}`), body);
  d.addEventListener("toggle", () => { try { localStorage.setItem(key, d.open ? "1" : "0"); } catch (e) {} });
  return d;
}

// ---- the human's turn: show exactly what the models see ------------------------------------------------
function stateView(state) {
  const rows = [];
  for (const [k, v] of Object.entries(state)) {
    if (k === "game") continue;
    const label = h("div", {class: "skey"}, k.replace(/_/g, " "));
    if (Array.isArray(v) && v.length && typeof v[0] === "object") {
      const cols = Object.keys(v[0]);
      rows.push(label, h("div", {style: "overflow-x:auto"}, h("table", {class: "hist"},
        h("tr", {}, cols.map(c => h("th", {}, c.replace(/_/g, " ")))),
        v.map(r => h("tr", {}, cols.map(c => h("td", {}, Array.isArray(r[c]) ? r[c].join(", ") : String(r[c]))))))));
    } else if (Array.isArray(v)) {
      rows.push(label, h("div", {}, v.length ? v.join(", ") : "none yet"));
    } else if (v && typeof v === "object") {
      rows.push(label, h("ul", {}, Object.entries(v).map(([a, b]) => h("li", {}, `${a}: ${b}`))));
    } else {
      rows.push(label, h("div", {}, String(v)));
    }
  }
  return h("div", {class: "state"}, rows);
}
function questionCard(q, onAnswer) {
  const opts = Object.entries(q.options), many = opts.length > 6;
  const card = h("div", {class: "panel qcard"},
    h("h3", {}, "Your move"),
    h("div", {class: "small"}, "This is exactly the information the models get for this decision."),
    stateView(q.state),
    h("div", {class: "qtext"}, q.question),
    h("div", {class: "qopts" + (many ? " many" : "")}, opts.map(([a, desc]) =>
      h("button", {class: "btn opt", type: "button", title: desc, onclick: () => {
        card.querySelectorAll("button").forEach(b => b.disabled = true);
        onAnswer(a);
      }}, h("b", {}, a), many ? null : h("span", {}, desc)))));
  return card;
}

// ---- run tab: watch the models, or play against them (only when served by experiments/app.py) ---------
let poll = null;
let runMode = "watch";
function renderRunTab() {
  const main = document.getElementById("main"); main.className = "single"; main.innerHTML = "";
  const meta = DATA.meta.games, play = runMode === "play";
  const f = {};
  const HELP = {
    payoffs: "Points each player gets, in standard game-theory notation: <b>R</b> (reward) both cooperate · <b>S</b> (sucker) you cooperate, the other defects · <b>T</b> (temptation) you defect, the other cooperates · <b>P</b> (punishment) both defect. The default 3,0,5,1 means: both cooperate → 3 each; you're exploited → 0 for you, 5 for them; both defect → 1 each.<br><br>It's a real dilemma only when <b>T &gt; R &gt; P &gt; S</b> (and 2R &gt; T + S): defecting is tempting, but mutual cooperation beats mutual defection. Try <b>3,0,4,1</b> (weak temptation), <b>3,0,10,1</b> (strong temptation) or <b>5,0,3,1</b> (no dilemma: cooperating is simply better) to see whether a model reacts to the incentives.",
    prompt: "Controls the wording of the question. <b>baseline</b> sends the game's plain question, e.g. “You are playing Rock Paper Scissors. Choose exactly one action.” <b>strategic</b> adds one sentence that nudges the model to think strategically; the sentence depends on the game (shown above when selected).<br><br>It tests whether <b>wording</b> changes behaviour, separately from the game itself, and it is always applied to every player equally.",
    option_order: "Controls the order in which the options are listed, e.g. COOPERATE, DEFECT versus DEFECT, COOPERATE. The options themselves don't change.<br><br>It's a control for <b>position bias</b>: a model that picks whatever is listed first (or last), regardless of what it means. If a model's choice flips when the order is reversed, it is following the position, not the game. In our experiments this happened for Laya in several games; Jev kept its choices.",
    seed: "The starting number for the <b>randomness in the game</b>, so a run can be repeated exactly. It affects the <b>random</b> player's choices and, in Monty Hall, where the prize is and which door the host opens.<br><br>It does <b>not</b> affect Jev or Laya: they always give the same answer to the same input. Same seed → the same random choices; different seeds → different random sequences, which is how you get real repetitions (e.g. Jev vs random with seeds 1, 2 and 3).",
  };
  const hints = {}, helps = {};
  for (const k of Object.keys(HELP)) {
    hints[k] = h("div", {class: "hint"});
    helps[k] = h("details", {class: "help"}, h("summary", {}, "What is this?"), h("div", {}));
    helps[k].lastChild.innerHTML = HELP[k];  // our own static text
  }
  // hint + help sit next to the <label>, not inside it: a click on "What is this?" must not activate the input
  const field = (label, input, key) => key
    ? h("div", {class: "fld"}, h("label", {}, label, input), hints[key], helps[key])
    : h("label", {}, label, input);
  function updateHints() {
    const g = f.game.value;
    const nums = f.payoffs.value.split(",").map(x => x.trim());
    if (nums.length !== 4 || nums.some(x => x === "" || isNaN(+x))) {
      hints.payoffs.className = "hint warn"; hints.payoffs.textContent = "Enter four numbers: R,S,T,P";
    } else {
      const [R, S, T, P] = nums.map(Number);
      const ok = T > R && R > P && P > S && 2 * R > T + S;
      hints.payoffs.className = "hint " + (ok ? "ok" : "warn");
      hints.payoffs.textContent = ok ? "✓ A real dilemma (T > R > P > S)"
        : "Not a Prisoner's Dilemma with these numbers (needs T > R > P > S and 2R > T + S)";
    }
    hints.prompt.textContent = f.prompt.value === "strategic"
      ? `Adds: “${meta[g].strategic_hint}”` : "The game's plain question, the same for every player.";
    hints.option_order.textContent = f.option_order.value === "reversed"
      ? "Options listed last to first (a control for position bias)." : "Options listed in their normal order.";
    const random = [];
    if (seatValues().includes("random")) random.push("the random player's choices");
    if (g === "monty_hall") random.push("the prize location and which door the host opens");
    hints.seed.textContent = random.length ? "Controls " + random.join(" and ") + "."
      : "No effect here: no random player and no randomness in this game.";
  }
  f.game = h("select", {}, GAMES.map(g => h("option", {value: g, selected: play && g === "rps"}, meta[g].title)));
  f.rounds = h("input", {type: "number", min: 1, max: 500, value: 10});
  f.mode = h("select", {}, h("option", {value: "repeated"}, "with history"), h("option", {value: "one-shot"}, "no history (one-shot)"));
  f.prompt = h("select", {}, h("option", {value: "baseline"}, "baseline"), h("option", {value: "strategic"}, "strategic"));
  f.option_order = h("select", {}, h("option", {value: "given"}, "given"), h("option", {value: "reversed"}, "reversed"));
  f.seed = h("input", {type: "number", value: 0});
  f.max_jev_tokens = h("input", {type: "number", min: 0, value: 2000000});
  f.condition = h("input", {value: play ? "human" : "app"});
  f.payoffs = h("input", {value: "3,0,5,1"});
  f.pie = h("input", {type: "number", min: 1, max: 100, value: 10});
  f.ultimatum_mode = h("select", {}, h("option", {value: "play"}, "play"), h("option", {value: "sweep"}, "sweep"));
  f.ratio = h("input", {value: "2/3"});
  f.grid_step = h("input", {type: "number", min: 1, max: 50, value: 5});
  f.doors = h("input", {type: "number", min: 3, max: 100, value: 3});
  f.initial_choice = h("select", {}, h("option", {value: "model"}, "players pick"), h("option", {value: "random"}, "random"));
  const seats = h("div", {style: "display:grid;gap:6px"});
  const addSeat = (val = "jev") => {
    const sel = h("select", {}, ["jev", "laya", "random", "fixed"].map(v => h("option", {value: v, selected: v === val}, v)));
    const fixed = h("input", {placeholder: "action, e.g. DEFECT", style: "display:none"});
    sel.onchange = () => { fixed.style.display = sel.value === "fixed" ? "" : "none"; update(); };
    const row = h("div", {class: "seat"}, sel, fixed, h("button", {class: "btn", type: "button", onclick: () => { row.remove(); update(); }}, "✕"));
    row.value = () => sel.value === "fixed" ? "fixed:" + fixed.value.trim() : sel.value;
    seats.append(row); update();
  };
  const seatValues = () => (play ? ["human"] : []).concat([...seats.children].map(r => r.value()));
  const addBtn = h("button", {class: "btn", type: "button", onclick: () => addSeat("random")}, play ? "+ add opponent" : "+ add player");
  const specific = h("div", {class: "row"});
  const estimate = h("div", {class: "small"});
  const start = h("button", {class: "btn primary", type: "submit"}, play ? "Start playing" : "Start the game");
  const stop = h("button", {class: "btn", type: "button", disabled: true}, "Stop");
  const status = h("div", {class: "small"});
  const qbox = h("div");
  const live = h("div");
  const log = h("pre", {class: "log", style: "display:none"});
  const about = h("div");

  function update() {
    const g = f.game.value, m = meta[g], n = seatValues().length;
    specific.innerHTML = "";
    const add = (l, i) => specific.append(field(l, i));
    if (g === "prisoners_dilemma") specific.append(field("Payoffs R,S,T,P", f.payoffs, "payoffs"));
    if (g === "ultimatum") { add("Mode", f.ultimatum_mode); add("Pie", f.pie); }
    if (g === "beauty_contest") { add("Target ratio", f.ratio); add("Number grid step", f.grid_step); }
    if (g === "monty_hall") { add("Doors", f.doors); add("First door", f.initial_choice); }
    const maxP = g === "ultimatum" && f.ultimatum_mode.value === "sweep" ? 8 : m.max_players;
    addBtn.disabled = n >= maxP;
    const jevSeats = seatValues().filter(v => v === "jev").length;
    const perRound = g === "monty_hall" && f.initial_choice.value === "model" ? 2 : 1;
    const tokens = jevSeats * (+f.rounds.value || 0) * perRound * m.tokens_per_decision * (g === "beauty_contest" && +f.grid_step.value === 1 ? 2 : 1);
    estimate.textContent = `Players: ${m.min_players}–${maxP}${play ? " including you" : ""}. Rough Jev estimate: ~${Math.round(tokens / 1000)}k tokens ≈ $${(tokens * 0.042 / 1e6).toFixed(4)}.`;
    about.innerHTML = ""; about.append(aboutCard(g));
    updateHints();
  }
  // these only change hint text; a full update() would re-render the fields and steal focus while typing
  for (const k of ["payoffs", "prompt", "option_order"]) f[k].addEventListener("input", updateHints);
  for (const k of ["game", "rounds", "initial_choice", "grid_step", "ultimatum_mode"]) f[k].addEventListener("input", update);
  f.game.addEventListener("change", () => {
    const g = f.game.value, m = meta[g];
    while (seatValues().length > m.max_players && seats.children.length) seats.lastChild.remove();
    if (g === "beauty_contest") while (seatValues().length < 4) addSeat(seatValues().includes("laya") ? "random" : "laya");
    if (g !== "monty_hall" && seatValues().length < m.min_players) addSeat("jev");
    update();
  });

  async function answer(runId, qid, action) {
    const res = await fetch(`api/run/${runId}/answer`, {method: "POST",
      headers: {"Content-Type": "application/json", "X-Run-Token": DATA.token}, body: JSON.stringify({id: qid, action})});
    qbox.innerHTML = "";
    qbox.append(h("div", {class: "small"}, res.ok ? "Waiting for the other players…" : "That answer was not accepted, please try again."));
  }

  const form = h("form", {class: "run", onsubmit: async e => {
    e.preventDefault();
    const body = {game: f.game.value, players: seatValues()};
    for (const k of ["rounds", "mode", "prompt", "option_order", "seed", "max_jev_tokens", "condition", "payoffs", "pie",
                     "ultimatum_mode", "ratio", "grid_step", "doors", "initial_choice"]) body[k] = f[k].value;
    start.disabled = true; status.textContent = "Starting…"; log.style.display = "none"; live.innerHTML = ""; qbox.innerHTML = "";
    const res = await fetch("api/run", {method: "POST", headers: {"Content-Type": "application/json", "X-Run-Token": DATA.token}, body: JSON.stringify(body)});
    const out = await res.json();
    if (!res.ok) { status.textContent = "Error: " + out.error; start.disabled = false; return; }
    stop.disabled = false;
    stop.onclick = () => fetch(`api/run/${out.id}/stop`, {method: "POST", headers: {"X-Run-Token": DATA.token}});
    let shown = -1, keepProbs = false, openQ = null;
    clearInterval(poll);
    poll = setInterval(async () => {
      const r = await (await fetch(`api/run/${out.id}`)).json();
      const n = r.experiment ? r.experiment.rounds.length * 1000 + r.experiment.pending.reduce((a, p) => a + p.moves.length, 0) : 0;
      if (r.experiment && n !== shown) {
        shown = n;
        const {chat, probsBox} = renderExperiment(r.experiment, live, {live: true, keepProbs});
        probsBox.addEventListener("change", () => { keepProbs = probsBox.checked; });
        if (!r.question) { const last = chat.lastElementChild; if (last) last.scrollIntoView({block: "nearest"}); }
      }
      if (r.question && r.question.id !== openQ) {
        openQ = r.question.id;
        qbox.innerHTML = "";
        qbox.append(questionCard(r.question, action => answer(out.id, r.question.id, action)));
        qbox.scrollIntoView({block: "start", behavior: "smooth"});
      }
      const done = r.experiment ? r.experiment.rounds.length : 0;
      status.textContent = r.status === "running" ? (r.question ? `Round ${done + 1}: your turn` : `Running… ${done} rounds done`) : `Finished: ${r.status}`;
      if (r.status !== "running") {
        clearInterval(poll); start.disabled = false; stop.disabled = true; qbox.innerHTML = "";
        if (r.status !== "done") { log.style.display = ""; log.textContent = r.log_tail; }
        else status.append(" ", h("button", {class: "btn", type: "button", onclick: () => { location.hash = new URLSearchParams({tab: r.game, exp: r.id}); location.reload(); }},
          `Open in the ${TITLES[r.game]} tab`));
      }
    }, play ? 400 : 1000);
  }},
    h("div", {class: "modes"},
      h("button", {type: "button", class: play ? "" : "on", onclick: () => { runMode = "watch"; renderRunTab(); }}, "Watch the models play"),
      h("button", {type: "button", class: play ? "on" : "", onclick: () => { runMode = "play"; renderRunTab(); }}, "Play against the models")),
    h("div", {class: "small"}, play
      ? "You take a seat in the game and see exactly what the models see. Your games are saved like any other experiment."
      : "Runs experiments/run_tournament.py on this computer. Jev calls cost money; the token budget below stops the run if it's exceeded."),
    h("div", {class: "row"}, field("Game", f.game), field("Rounds", f.rounds), field("History", f.mode)),
    h("div", {}, h("div", {class: "small", style: "margin-bottom:4px"},
      play ? "Your opponents (you sit on the left)" : "Players (seat 1 appears on the left, seat 2 on the right)"), seats, addBtn),
    specific,
    // one per row: their help texts need the full width
    field("Prompt", f.prompt, "prompt"), field("Option order", f.option_order, "option_order"), field("Seed", f.seed, "seed"),
    h("div", {class: "row"}, field("Max Jev tokens (0 = no limit)", f.max_jev_tokens), field("Condition label", f.condition)),
    estimate, h("div", {class: "controls"}, start, stop), status);
  main.append(h("div", {class: "panel"}, form), h("div", {style: "height:14px"}), qbox, h("div", {style: "height:14px"}), live, log,
    h("div", {style: "height:14px"}), about);
  if (play) addSeat("jev"); else { addSeat("jev"); addSeat("laya"); }
  update();
}

function render() {
  const {tab, exp} = route();
  renderTabs(tab);
  if (tab === "run" && DATA.serve) renderRunTab(); else renderGameTab(tab, exp);
}
window.addEventListener("hashchange", render);
render();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
