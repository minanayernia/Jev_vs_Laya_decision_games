"""Run a match between players in one game and save every decision.

Examples:
    python experiments/run_tournament.py --game prisoners_dilemma --rounds 10
    python experiments/run_tournament.py --game rps --rounds 30 --prompt strategic
    python experiments/run_tournament.py --game ultimatum --ultimatum-mode sweep --rounds 11
    python experiments/run_tournament.py --game beauty_contest --players jev laya random random
    python experiments/run_tournament.py --game monty_hall --doors 10 --rounds 50
    python experiments/run_tournament.py --players random fixed:DEFECT --rounds 100 --seed 1

Players: jev, laya, random, fixed:<ACTION> (e.g. fixed:DEFECT, fixed:ROCK, fixed:33),
         human (you answer in the terminal; at most one).

Output: results/<game>/<experiment_id>/{config.json, decisions.jsonl, rounds.jsonl, summary.json}
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import statistics
import sys
from datetime import datetime, timezone
from fractions import Fraction
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

# Allow `python experiments/run_tournament.py` from the project root without installing a package.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from games import GAMES  # noqa: E402
from games.base import Game  # noqa: E402
from games.prisoners_dilemma import Payoffs  # noqa: E402
from players.base import Decision, FixedPlayer, Player, RandomPlayer  # noqa: E402

# Published Jev price (USD per 1M input tokens; output is free). Check https://docs.typesafe.ai
JEV_PRICE_PER_MTOK = 0.042

SHORT_NAMES = {"prisoners_dilemma": "pd", "matching_pennies": "mp", "rps": "rps",
               "ultimatum": "ug", "beauty_contest": "bc", "monty_hall": "mh"}


def make_players(specs: list[str], seed: int, human_channel: str | None = None) -> list[Player]:
    if specs.count("human") > 1:
        raise ValueError("at most one human player")
    players, laya_agent = [], None
    for i, spec in enumerate(specs):
        if spec == "jev":
            from players.jev import JevPlayer
            players.append(JevPlayer())
        elif spec == "laya":
            from players.laya import LayaPlayer
            p = LayaPlayer(agent=laya_agent)  # load the weights once, share between seats
            laya_agent = p.agent
            players.append(p)
        elif spec == "random":
            players.append(RandomPlayer(seed=seed + i))
        elif spec == "human":
            from players.human import HumanPlayer
            players.append(HumanPlayer(channel=human_channel))
        elif spec.startswith("fixed:"):
            action = spec.split(":", 1)[1]
            players.append(FixedPlayer(action, name=f"fixed_{action.lower()}"))
        else:
            raise ValueError(f"unknown player {spec!r} (use jev, laya, random, fixed:<ACTION>, human)")
    return players


def make_game(args) -> Game:
    common = {"show_history": args.mode == "repeated", "history_window": args.history_window,
              "prompt": args.prompt, "option_order": args.option_order}
    if args.game == "prisoners_dilemma":
        return GAMES[args.game](payoffs=Payoffs.parse(args.payoffs), **common)
    if args.game == "ultimatum":
        return GAMES[args.game](pie=args.pie, mode=args.ultimatum_mode, **common)
    if args.game == "beauty_contest":
        return GAMES[args.game](ratio=Fraction(args.ratio), step=args.grid_step, **common)
    if args.game == "monty_hall":
        return GAMES[args.game](doors=args.doors, initial_choice=args.initial_choice, seed=args.seed, **common)
    return GAMES[args.game](**common)


def environment_metadata() -> dict:
    packages = {}
    for name in ("typesafe-sdk", "laya", "torch", "transformers", "scipy", "numpy"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                           stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True))
    except (OSError, subprocess.CalledProcessError):
        revision, dirty = None, None
    return {"python": platform.python_version(), "platform": platform.platform(),
            "packages": packages, "git_revision": revision, "git_dirty": dirty}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def get_decision(player: Player, request, max_attempts: int, log) -> tuple[Decision, bool]:
    """Ask `player` up to `max_attempts` times until it returns a legal action.

    A legal action is exactly one of the request's option keys. A decision is retried only
    if it is invalid (illegal action or error). Every attempt is logged, and an invalid
    answer is never mapped to a legal one. Returns (last decision, valid?).
    """
    for attempt in range(1, max_attempts + 1):
        decision = player.decide(request)
        valid = decision.error is None and decision.action in request.options
        log(attempt, decision, valid)
        if valid:
            return decision, True
    return decision, False


def unique_names(players: list[Player]) -> list[str]:
    """Self-play: give repeated names a suffix (laya_1, laya_2, ...) so seats stay distinguishable."""
    names = [p.name for p in players]
    seen: dict[str, int] = {}
    for p in players:
        if names.count(p.name) > 1:
            base = p.name
            seen[base] = seen.get(base, 0) + 1
            p.name = f"{base}_{seen[base]}"
    return [p.name for p in players]


def run_match(game: Game, players: list[Player], rounds: int, max_attempts: int,
              out_dir: Path, experiment_id: str, max_billed_tokens: int | None = None,
              price_per_mtok: float = JEV_PRICE_PER_MTOK) -> dict:
    """Play `rounds` rounds. If billed players' input tokens reach `max_billed_tokens`,
    stop after the current round (so the budget can be overshot by at most one round)."""
    if not game.min_players <= len(players) <= game.max_players:
        raise ValueError(f"{game.title} needs {game.min_players}-{game.max_players} players, got {len(players)}")
    if rounds < 1 or max_attempts < 1:
        raise ValueError("rounds and max_attempts must be positive")
    out_dir.mkdir(parents=True, exist_ok=True)
    if any((out_dir / name).exists() for name in ("decisions.jsonl", "rounds.jsonl", "summary.json")):
        raise FileExistsError(f"experiment outputs already exist: {out_dir}")
    # Exclusive creation protects direct callers as well as CLI runs.
    names = unique_names(players)
    history: list[dict] = []  # non-void rounds; games build what players see from this
    records: list[dict] = []
    stats = {
        n: {"actions": {}, "points": 0.0, "invalid_decisions": 0, "invalid_attempts": 0, "errors": 0,
            "latencies_ms": [], "confidence_reported": False, "input_tokens": 0, "billed": p.billed,
            "at_context_limit": 0}
        for n, p in zip(names, players)
    }
    void_rounds = 0
    rounds_played = 0
    stopped_early = None

    with open(out_dir / "decisions.jsonl", "x") as dec_f, open(out_dir / "rounds.jsonl", "x") as rnd_f:
        for r in range(1, rounds + 1):
            order = list(range(len(players)))  # order[role] = player index
            if game.alternate_roles and r % 2 == 0:
                order.reverse()

            def ask(i: int, step: str, request) -> tuple[str | None, bool]:
                player, s = players[i], stats[names[i]]

                def log(attempt, d: Decision, ok: bool):
                    usage = d.usage or {}
                    tokens = usage.get("input_tokens") or 0
                    limit = usage.get("context_limit")
                    s["latencies_ms"].append(d.latency_ms)
                    s["errors"] += d.error is not None
                    s["invalid_attempts"] += not ok
                    s["confidence_reported"] |= d.confidence is not None
                    s["input_tokens"] += tokens
                    s["at_context_limit"] += bool(limit and tokens >= limit)
                    dec_f.write(json.dumps({
                        "experiment_id": experiment_id, "game": game.name, "round": r,
                        "player": names[i], "seat": i, "step": step, "attempt": attempt,
                        "state": request.state, "question": request.question,
                        "available_actions": list(request.options), "options": request.options,
                        "decision": d.action, "valid": ok, "error": d.error,
                        # null = the model did not report it; never filled in by us
                        "probabilities": d.probabilities, "confidence": d.confidence,
                        "model": d.model, "usage": d.usage,
                        "latency_ms": round(d.latency_ms, 3), "timestamp": now(),
                    }) + "\n")
                    dec_f.flush()  # so the live viewer (experiments/app.py) sees each decision immediately

                d, ok = get_decision(player, request, max_attempts, log)
                if ok:
                    counts = s["actions"].setdefault(step, {})
                    counts[d.action] = counts.get(d.action, 0) + 1
                else:
                    s["invalid_decisions"] += 1
                return d.action, ok

            result = game.play_round(r, rounds, history, order, ask)
            record = {"experiment_id": experiment_id, "round": r, "players": names, **result}
            records.append(record)
            rnd_f.write(json.dumps(record) + "\n")
            rnd_f.flush()
            rounds_played = r
            if result["void"]:
                # No outcome: nobody scores and the round is left out of the history players see.
                void_rounds += 1
            else:
                history.append({"round": r, **result})
                for n, pts in zip(names, result["points"]):
                    if pts is not None:
                        stats[n]["points"] += pts

            billed_tokens = sum(s["input_tokens"] for s in stats.values() if s["billed"])
            if max_billed_tokens and billed_tokens >= max_billed_tokens and r < rounds:
                stopped_early = f"token budget reached: {billed_tokens} >= {max_billed_tokens} billed input tokens"
                break

    billed_tokens = sum(s["input_tokens"] for s in stats.values() if s["billed"])
    summary = {"experiment_id": experiment_id, "game": game.name, "title": game.title,
               "rounds_requested": rounds, "rounds": rounds_played,
               "scored_rounds": rounds_played - void_rounds, "void_rounds": void_rounds,
               "stopped_early": stopped_early, "billed_input_tokens": billed_tokens,
               "estimated_cost_usd": billed_tokens / 1e6 * price_per_mtok,
               "players": {}, "game_stats": game.summarize(records, names)}
    for n in names:
        s = stats[n]
        lat = s.pop("latencies_ms")
        s["latency_ms"] = {"mean": statistics.fmean(lat), "median": statistics.median(lat)} if lat else None
        summary["players"][n] = s
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".")
    if isinstance(v, dict):
        return ", ".join(f"{k}: {fmt(x)}" for k, x in v.items())
    return str(v)


def print_summary(summary: dict) -> None:
    names = list(summary["players"])
    print(f"\n{' vs '.join(names)}")
    print(f"Game: {summary['title']}")
    print(f"Rounds: {summary['rounds']}  (scored: {summary['scored_rounds']}, void: {summary['void_rounds']})")
    if summary["stopped_early"]:
        print(f"STOPPED EARLY after {summary['rounds']} of {summary['rounds_requested']} rounds: {summary['stopped_early']}")
    print()
    for name, s in summary["players"].items():
        print(name)
        for step, counts in s["actions"].items():
            total = sum(counts.values())
            if len(counts) > 6 and all(k.isdigit() for k in counts):
                values = [int(k) for k, c in counts.items() for _ in range(c)]
                print(f"  {step}: mean {statistics.fmean(values):.1f}, median {statistics.median(values):g}, "
                      f"most common {max(counts, key=counts.get)}  (n={total})")
            else:
                parts = [f"{a} {100 * c / total:.0f}% ({c})" for a, c in sorted(counts.items(), key=lambda kv: -kv[1])]
                print(f"  {step}: " + ", ".join(parts))
        print(f"  points: {s['points']:g}")
    if summary["game_stats"]:
        print("\nGame statistics")
        for key, value in summary["game_stats"].items():
            print(f"  {key}: {fmt(value)}")
    print("\nLatency (mean / median ms)")
    for name, s in summary["players"].items():
        lat = s["latency_ms"]
        print(f"  {name + ':':<18}{lat['mean']:.1f} / {lat['median']:.1f}" if lat else f"  {name}: n/a")
    print("\nInvalid decisions (attempts / final)")
    for name, s in summary["players"].items():
        print(f"  {name + ':':<18}{s['invalid_attempts']} / {s['invalid_decisions']}  (errors: {s['errors']})")
    print("\nInput tokens")
    for name, s in summary["players"].items():
        print(f"  {name + ':':<18}{s['input_tokens']}" + ("  (billed)" if s["billed"] else ""))
    print(f"  Estimated Jev cost: ${summary['estimated_cost_usd']:.4f}")
    for name, s in summary["players"].items():
        if s["at_context_limit"]:
            print(f"\nWARNING: {s['at_context_limit']} {name} decisions hit the model's context limit; "
                  "their input was probably truncated. Try a smaller --history-window.")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", default="prisoners_dilemma", choices=list(GAMES))
    ap.add_argument("--players", nargs="+", default=["jev", "laya"],
                    help="jev, laya, random, fixed:<ACTION>, human (default: jev laya)")
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--mode", choices=["repeated", "one-shot"], default="repeated",
                    help="repeated: players see round number and recent history; one-shot: each round is independent")
    ap.add_argument("--prompt", choices=["baseline", "strategic"], default="baseline",
                    help="strategic adds one sentence (e.g. consider the opponent) to every question, for all players")
    ap.add_argument("--option-order", choices=["given", "reversed"], default="given",
                    help="reversed lists every question's options last-to-first (position-bias control)")
    ap.add_argument("--history-window", type=int, default=5,
                    help="how many past rounds to show (Laya's English checkpoint reads at most 512 tokens)")
    ap.add_argument("--max-attempts", type=int, default=1, help="attempts per decision before it counts as invalid")
    ap.add_argument("--seed", type=int, default=0, help="seed for game randomness and the random player")
    ap.add_argument("--max-jev-tokens", type=int, default=2_000_000,
                    help="stop once Jev has used this many input tokens (default 2M ~ $0.08); 0 = no limit")
    ap.add_argument("--jev-price-per-mtok", type=float, default=JEV_PRICE_PER_MTOK,
                    help="USD per 1M input tokens, for the cost estimate only")
    ap.add_argument("--condition", default="baseline", help="label for the experimental condition")
    ap.add_argument("--experiment-id", default=None)
    ap.add_argument("--results-dir", default=str(ROOT / "results"))
    ap.add_argument("--human-channel", help=argparse.SUPPRESS)  # set by experiments/app.py for browser play
    g = ap.add_argument_group("game-specific")
    g.add_argument("--payoffs", default="3,0,5,1", help="prisoners_dilemma: R,S,T,P (default 3,0,5,1)")
    g.add_argument("--pie", type=int, default=10, help="ultimatum: points to split")
    g.add_argument("--ultimatum-mode", choices=["play", "sweep"], default="play",
                   help="ultimatum: play = model proposes; sweep = every offer 0..pie is put to each responder")
    g.add_argument("--ratio", default="2/3", help="beauty_contest: target = ratio x average")
    g.add_argument("--grid-step", type=int, default=1, help="beauty_contest: allowed numbers are 0, step, 2*step, ... 100")
    g.add_argument("--doors", type=int, default=3, help="monty_hall: number of doors")
    g.add_argument("--initial-choice", choices=["model", "random"], default="model",
                   help="monty_hall: who picks the first door")
    args = ap.parse_args(argv)

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    game = make_game(args)
    if not game.min_players <= len(args.players) <= game.max_players:
        ap.error(f"{game.title} needs {game.min_players}-{game.max_players} players, got {len(args.players)}")

    if args.rounds < 1 or args.max_attempts < 1:
        ap.error("rounds and max-attempts must be positive")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    experiment_id = args.experiment_id or f"{SHORT_NAMES[game.name]}_{args.condition}_{args.mode}_{stamp}"
    out_dir = Path(args.results_dir) / game.name / experiment_id
    try:
        out_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        ap.error(f"experiment directory already exists: {out_dir}; choose a new experiment ID")
    players = make_players(args.players, args.seed, args.human_channel)
    config = {"experiment_id": experiment_id, "created": now(), "args": vars(args),
              "players": args.players, "game_config": game.config(), "environment": environment_metadata(),
              "retry_policy": {"max_attempts": args.max_attempts,
                               "note": "retry only on invalid/error; typesafe-sdk also retries 429/5xx/timeouts internally"}}
    (out_dir / "config.json").write_text(json.dumps(config, indent=2))

    summary = run_match(game, players, args.rounds, args.max_attempts, out_dir, experiment_id,
                        max_billed_tokens=args.max_jev_tokens or None, price_per_mtok=args.jev_price_per_mtok)
    print_summary(summary)
    print(f"\nSaved to {out_dir.relative_to(ROOT) if out_dir.is_relative_to(ROOT) else out_dir}")


if __name__ == "__main__":
    main()
