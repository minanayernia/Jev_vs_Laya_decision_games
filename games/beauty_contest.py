"""Beauty Contest (guess 2/3 of the average).

Everyone picks a number; the target is `ratio` x the average; closest wins. With ratio < 1
the only Nash equilibrium is everyone choosing the lowest number (0), reached by
iterated reasoning: 100 -> 67 -> 44 -> ... Real players (and models) usually stop early.
"""

from __future__ import annotations

from fractions import Fraction
from statistics import median

from games.base import Game


class BeautyContest(Game):
    name = "beauty_contest"
    title = "Beauty Contest"
    min_players = 2
    max_players = 10
    strategic_hint = "Consider how the other players are likely to choose."

    def __init__(self, ratio: Fraction = Fraction(2, 3), low: int = 0, high: int = 100, step: int = 1, **kwargs):
        super().__init__(**kwargs)
        self.ratio, self.low, self.high, self.step = Fraction(ratio), low, high, step
        self.numbers = list(range(low, high + 1, step))

    def rules(self, n_players: int) -> str:
        grid = "whole number" if self.step == 1 else f"multiple of {self.step}"
        return (f"Each of the {n_players} players chooses a {grid} from {self.low} to {self.high} at the same time. "
                f"The target is {self.ratio} of the average of all chosen numbers. "
                "The player whose number is closest to the target wins 1 point; on a tie the point is shared.")

    def target(self, numbers: list[int]) -> Fraction:
        return self.ratio * Fraction(sum(numbers), len(numbers))

    def winners(self, numbers: list[int]) -> list[int]:
        t = self.target(numbers)
        dist = [abs(x - t) for x in numbers]  # exact Fractions, so ties are exact
        best = min(dist)
        return [i for i, d in enumerate(dist) if d == best]

    def request_for(self, me: int, n: int, history, round_number, total_rounds):
        state = {"game": self.title, "rules": self.rules(n), "number_of_players": n}
        if self.show_history:
            state["round"] = f"{round_number} of {total_rounds}"
            state["previous_rounds"] = [
                {"round": h["round"], "your_number": h["info"]["numbers"][me],
                 "all_numbers": sorted(h["info"]["numbers"]), "average": round(h["info"]["average"], 2),
                 "target": round(h["info"]["target"], 2), "your_points": round(h["points"][me], 3)}
                for h in self.recent(history)
            ]
        options = {str(x): f"Choose {x}." for x in self.numbers}
        return self.request(state, "You are playing the Beauty Contest. Choose exactly one number.", options)

    def play_round(self, round_number, total_rounds, history, order, ask):
        n = len(order)
        requests = [self.request_for(p, n, history, round_number, total_rounds) for p in range(n)]
        answers = [ask(p, "number", requests[p]) for p in range(n)]
        decisions = [{"number": a} for a, _ in answers]
        if not all(ok for _, ok in answers):
            return {"decisions": decisions, "roles": [None] * n, "points": None, "void": True, "info": {}}
        numbers = [int(a) for a, _ in answers]
        win = self.winners(numbers)
        points = [1 / len(win) if i in win else 0.0 for i in range(n)]
        info = {"numbers": numbers, "average": sum(numbers) / n, "target": float(self.target(numbers)),
                "winners": win}
        return {"decisions": decisions, "roles": [None] * n, "points": points, "void": False, "info": info}

    def summarize(self, rounds, names):
        scored = [r for r in rounds if not r["void"]]
        out = {}
        for i, n in enumerate(names):
            xs = [r["info"]["numbers"][i] for r in scored]
            if xs:
                out[n] = {"mean_number": sum(xs) / len(xs), "median_number": median(xs),
                          "mean_distance_to_target": sum(abs(r["info"]["numbers"][i] - r["info"]["target"])
                                                         for r in scored) / len(xs),
                          "rounds_won": sum(i in r["info"]["winners"] for r in scored)}
        if scored:
            out["overall"] = {"mean_target": sum(r["info"]["target"] for r in scored) / len(scored),
                              "nash_equilibrium": self.low if self.ratio < 1 else "not unique"}
        return out

    def config(self):
        return super().config() | {"ratio": str(self.ratio), "low": self.low, "high": self.high, "step": self.step}
