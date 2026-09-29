"""Shared game machinery.

A game plays one round at a time through `play_round`, asking players for decisions via
the runner's `ask(player, step, request) -> (action, valid)` callback. The runner handles
validation, retries, logging and budgets; the game handles rules, what players see, and scoring.

`play_round` returns a dict:
    decisions: list, one {step: action} per player (raw answers, even invalid ones)
    roles:     list, one role name per player (or None)
    points:    list, one number per player, or None where no outcome was reached
    void:      True if the round produced no usable outcome
    info:      game-specific public facts (e.g. the target number, where the prize was)
"""

from __future__ import annotations

from typing import Callable

from players.base import DecisionRequest

Ask = Callable[[int, str, DecisionRequest], tuple[str | None, bool]]


class Game:
    name = ""
    title = ""
    min_players = 2
    max_players = 2
    alternate_roles = False  # 2-player games with asymmetric roles swap seats every round
    strategic_hint = "Consider the opponent's previous behavior when choosing."

    def __init__(self, show_history: bool = True, history_window: int = 5, prompt: str = "baseline",
                 option_order: str = "given"):
        if prompt not in ("baseline", "strategic"):
            raise ValueError(f"unknown prompt variant {prompt!r}")
        if option_order not in ("given", "reversed"):
            raise ValueError(f"unknown option order {option_order!r}")
        self.show_history = show_history
        self.history_window = history_window
        self.prompt = prompt
        self.option_order = option_order

    def request(self, state: dict, question: str, options: dict[str, str]) -> DecisionRequest:
        """Every question goes through here, so a condition changes it for all players equally.

        option_order="reversed" lists the options last-to-first. It is a control for position
        bias: a model that prefers ROCK should still pick ROCK when ROCK is listed last.
        """
        if self.prompt == "strategic":
            question = f"{question} {self.strategic_hint}"
        if self.option_order == "reversed":
            options = dict(reversed(list(options.items())))
        return DecisionRequest(game=self.name, state=state, question=question, options=options)

    def recent(self, history: list[dict]) -> list[dict]:
        return history[-self.history_window:] if self.history_window > 0 else []

    def play_round(self, round_number: int, total_rounds: int, history: list[dict],
                   order: list[int], ask: Ask) -> dict:
        raise NotImplementedError

    def summarize(self, rounds: list[dict], names: list[str]) -> dict:
        """Game-specific statistics for the console summary and summary.json."""
        return {}

    def config(self) -> dict:
        return {"show_history": self.show_history, "history_window": self.history_window,
                "prompt": self.prompt, "strategic_hint": self.strategic_hint, "option_order": self.option_order}


class SimultaneousGame(Game):
    """Two players pick from the same action list at the same time (PD, Matching Pennies, RPS).

    Subclasses define `actions`, `options`, `question_text`, `rules`, `score(a, b)`, and
    optionally `role_names` + `role_description(role)` for asymmetric games.
    """

    actions: tuple[str, ...] = ()
    options: dict[str, str] = {}
    question_text = ""
    rules = ""
    role_names: tuple[str, str] | None = None

    def is_valid(self, action: str | None) -> bool:
        return action in self.actions

    def score(self, a: str, b: str) -> tuple[float, float]:
        """Points for (role 0, role 1)."""
        raise NotImplementedError

    def payoff_description(self) -> dict[str, str] | str:
        raise NotImplementedError

    def role_description(self, role: int) -> str:
        return ""

    def request_for(self, me: int, history: list[dict], round_number: int, total_rounds: int,
                    role: int = 0) -> DecisionRequest:
        """What player `me` sees, phrased as "you" / "opponent". The opponent's identity is never shown."""
        them = 1 - me
        state: dict = {"game": self.title, "rules": self.rules, "payoffs": self.payoff_description()}
        if self.role_names:
            state["your_role"] = self.role_description(role)
        if self.show_history:
            state["round"] = f"{round_number} of {total_rounds}"
            prev = []
            for h in self.recent(history):
                row = {"round": h["round"]}
                if self.role_names:
                    row["your_role"] = h["roles"][me]
                row |= {"you": h["decisions"][me]["action"], "opponent": h["decisions"][them]["action"],
                        "your_points": h["points"][me], "opponent_points": h["points"][them]}
                prev.append(row)
            state["previous_rounds"] = prev
            state["your_total_points"] = sum(h["points"][me] for h in history)
            state["opponent_total_points"] = sum(h["points"][them] for h in history)
        return self.request(state, self.question_text, dict(self.options))

    def play_round(self, round_number, total_rounds, history, order, ask):
        # Build both requests before anyone answers: neither player can see the other's choice.
        requests = {p: self.request_for(p, history, round_number, total_rounds, role)
                    for role, p in enumerate(order)}
        answers = {p: ask(p, "action", requests[p]) for p in order}
        decisions = [{"action": answers[p][0]} for p in range(2)]
        roles = [None, None]
        if self.role_names:
            for role, p in enumerate(order):
                roles[p] = self.role_names[role]
        if not all(ok for _, ok in answers.values()):
            return {"decisions": decisions, "roles": roles, "points": None, "void": True, "info": {}}
        by_role = self.score(answers[order[0]][0], answers[order[1]][0])
        points = [0.0, 0.0]
        for role, p in enumerate(order):
            points[p] = by_role[role]
        return {"decisions": decisions, "roles": roles, "points": points, "void": False, "info": {}}

    def summarize(self, rounds, names):
        """Win / draw / loss counts, from comparing the two players' points each round."""
        out = {n: {"wins": 0, "draws": 0, "losses": 0} for n in names}
        scored = [r for r in rounds if not r["void"]]
        for r in scored:
            a, b = r["points"]
            out[names[0]]["wins" if a > b else "draws" if a == b else "losses"] += 1
            out[names[1]]["wins" if b > a else "draws" if a == b else "losses"] += 1
        for n in names:
            out[n]["win_rate"] = out[n]["wins"] / len(scored) if scored else None
        return out

    def config(self):
        return super().config() | {"question": self.question_text, "options": self.options,
                                   "rules": self.rules, "payoffs": self.payoff_description()}
