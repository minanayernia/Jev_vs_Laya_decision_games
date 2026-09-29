"""Local web app: browse results and run games from the browser.

    python experiments/app.py            # then open http://127.0.0.1:8765
    python experiments/app.py --port 9000 --no-browser

Only reachable from this computer (binds to 127.0.0.1). Starting a run requires a secret token
that is embedded in the page, so other websites open in your browser can't start runs
(and spend Jev credit) behind your back. One run at a time; each run is a normal
`run_tournament.py` process, so its results land in results/ like any other run.
"""

from __future__ import annotations

import argparse
import errno
import json
import re
import secrets
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.run_tournament import SHORT_NAMES  # noqa: E402
from experiments.viewer import RESULTS, build_html, find_experiment_dirs, load_compact, read_json  # noqa: E402
from games import GAMES  # noqa: E402
from players.human import write_atomic  # noqa: E402

LOG_DIR = RESULTS / "_app_logs"
TOKEN = secrets.token_urlsafe(16)
RUNS: dict[str, dict] = {}
LOCK = threading.Lock()

CHOICES = {"mode": {"repeated", "one-shot"}, "prompt": {"baseline", "strategic"},
           "option_order": {"given", "reversed"}, "ultimatum_mode": {"play", "sweep"},
           "initial_choice": {"model", "random"}}
INTS = {"rounds": (1, 500), "seed": (0, 10**6), "max_jev_tokens": (0, 50_000_000), "pie": (1, 100),
        "grid_step": (1, 50), "doors": (3, 100)}
PATTERNS = {"payoffs": r"-?\d+(\.\d+)?(,-?\d+(\.\d+)?){3}", "ratio": r"\d+(/\d+)?", "condition": r"[A-Za-z0-9_-]{1,40}"}
GAME_ARGS = {"prisoners_dilemma": ["payoffs"], "ultimatum": ["pie", "ultimatum_mode"],
             "beauty_contest": ["ratio", "grid_step"], "monty_hall": ["doors", "initial_choice"]}


def build_argv(body: dict) -> tuple[list[str], str]:
    """Validate a run request from the page and turn it into run_tournament.py arguments.

    Every value is checked against a whitelist or pattern, and the result is an argument list
    (no shell), so nothing from the page can inject extra commands.
    """
    game = body.get("game")
    if game not in GAMES:
        raise ValueError(f"unknown game {game!r}")
    players = body.get("players") or []
    for p in players:
        if p not in ("jev", "laya", "random", "human") and not re.fullmatch(r"fixed:[A-Za-z0-9_]{1,20}", str(p)):
            raise ValueError(f"invalid player {p!r}")
    if players.count("human") > 1:
        raise ValueError("only one human player")
    probe = GAMES[game](**({"mode": body.get("ultimatum_mode", "play")} if game == "ultimatum" else {}))
    if not probe.min_players <= len(players) <= probe.max_players:
        raise ValueError(f"{probe.title} needs {probe.min_players}-{probe.max_players} players")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # random suffix: two runs started in the same second must not share (and overwrite) a folder
    exp_id = f"app_{SHORT_NAMES[game]}_{stamp}_{secrets.token_hex(2)}"
    argv = ["--game", game, "--players", *players, "--experiment-id", exp_id]
    if "human" in players:
        argv += ["--human-channel", str(LOG_DIR / exp_id)]
    for key in ["rounds", "mode", "prompt", "option_order", "seed", "max_jev_tokens", "condition",
                *GAME_ARGS.get(game, [])]:
        if key not in body or body[key] in ("", None):
            continue
        value = str(body[key]).strip()
        if key in CHOICES and value not in CHOICES[key]:
            raise ValueError(f"invalid {key}")
        if key in INTS:
            lo, hi = INTS[key]
            if not re.fullmatch(r"\d+", value) or not lo <= int(value) <= hi:
                raise ValueError(f"{key} must be a whole number from {lo} to {hi}")
        if key in PATTERNS and not re.fullmatch(PATTERNS[key], value):
            raise ValueError(f"invalid {key}")
        argv += [f"--{key.replace('_', '-')}", value]
    return argv, exp_id


def start_run(body: dict) -> dict:
    argv, exp_id = build_argv(body)
    with LOCK:
        if any(r["proc"].poll() is None for r in RUNS.values()):
            raise ValueError("another run is still in progress")
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"{exp_id}.log"
        proc = subprocess.Popen([sys.executable, str(ROOT / "experiments" / "run_tournament.py"), *argv],
                                cwd=ROOT, stdout=open(log_path, "w"), stderr=subprocess.STDOUT)
        RUNS[exp_id] = {"proc": proc, "log": log_path, "dir": RESULTS / body["game"] / exp_id,
                        "game": body["game"], "stopped": False,
                        "channel": LOG_DIR / exp_id if "human" in body["players"] else None}
    return {"id": exp_id}


def run_status(exp_id: str) -> dict | None:
    run = RUNS.get(exp_id)
    if not run:
        return None
    code = run["proc"].poll()
    status = "running" if code is None else "stopped" if run["stopped"] else "done" if code == 0 else "failed"
    lines = [l for l in run["log"].read_text(errors="replace").splitlines()
             if not re.search(r"Warning|warn\(|return Agent|Fetching", l)] if run["log"].exists() else []
    question = None
    if run["channel"] and code is None and not (run["channel"] / "answer.json").exists():
        question = read_json(run["channel"] / "question.json")  # the human's turn
    return {"id": exp_id, "game": run["game"], "status": status, "returncode": code,
            "experiment": load_compact(run["dir"]), "question": question, "log_tail": "\n".join(lines[-40:])}


def answer_question(exp_id: str, body: dict) -> None:
    """Pass the human's choice from the page to the waiting HumanPlayer."""
    run = RUNS.get(exp_id)
    if not run or not run["channel"]:
        raise ValueError("this run has no human player")
    question = read_json(run["channel"] / "question.json")
    if not question or question["id"] != body.get("id"):
        raise ValueError("that question is no longer open")
    if body.get("action") not in question["options"]:
        raise ValueError("not one of the options")
    write_atomic(run["channel"] / "answer.json", {"id": question["id"], "action": body["action"]})


class Handler(BaseHTTPRequestHandler):
    def _allowed_host(self) -> bool:
        # blocks DNS-rebinding tricks: only accept requests addressed to this machine by name
        port = self.server.server_address[1]
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _send(self, code: int, body: str | dict, ctype: str = "application/json") -> None:
        data = (json.dumps(body) if isinstance(body, dict) else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._allowed_host():
            return self._send(403, {"error": "forbidden host"})
        if self.path in ("/", "/index.html"):
            exps = [e for d in find_experiment_dirs() if (e := load_compact(d))]
            return self._send(200, build_html(exps, serve_token=TOKEN), "text/html")
        m = re.fullmatch(r"/api/run/([A-Za-z0-9_-]+)", self.path)
        if m:
            try:
                st = run_status(m.group(1))
            except Exception as e:  # always answer in JSON so the page's polling keeps working
                return self._send(500, {"error": f"{type(e).__name__}: {e}"})
            return self._send(200, st) if st else self._send(404, {"error": "unknown run"})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._allowed_host() or self.headers.get("X-Run-Token") != TOKEN:
            return self._send(403, {"error": "forbidden"})
        if self.path == "/api/run":
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                return self._send(200, start_run(body))
            except (ValueError, json.JSONDecodeError) as e:
                return self._send(400, {"error": str(e)})
        m = re.fullmatch(r"/api/run/([A-Za-z0-9_-]+)/answer", self.path)
        if m:
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                answer_question(m.group(1), body)
                return self._send(200, {"ok": True})
            except (ValueError, json.JSONDecodeError) as e:
                return self._send(400, {"error": str(e)})
        m = re.fullmatch(r"/api/run/([A-Za-z0-9_-]+)/stop", self.path)
        if m and m.group(1) in RUNS:
            run = RUNS[m.group(1)]
            if run["proc"].poll() is None:
                run["stopped"] = True
                run["proc"].terminate()
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):  # keep the terminal quiet except for errors
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            raise
        sys.exit(f"Port {args.port} is already in use, probably by another copy of this app.\n"
                 f"  Stop it with Ctrl+C in its terminal, or find it with:  lsof -nP -iTCP:{args.port} -sTCP:LISTEN\n"
                 f"  Or use another port:  python experiments/app.py --port {args.port + 1}")
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Jev vs Laya app running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
        for run in RUNS.values():
            if run["proc"].poll() is None:
                run["proc"].terminate()


if __name__ == "__main__":
    main()
