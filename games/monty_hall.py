"""Monty Hall: pick a door, the host opens empty doors, then stay or switch.

N-door version: after the first pick the host (who knows where the prize is) opens every
door except the player's and one other, so exactly two stay closed.
    P(win | stay) = 1/N        P(win | switch) = (N-1)/N

It's a one-player decision problem, so each player plays its own trial every round. In a
given round every player faces the same prize location (a paired comparison).
"""

from __future__ import annotations

import random

from games.base import Game

STAY = "STAY"
SWITCH = "SWITCH"


class MontyHall(Game):
    name = "monty_hall"
    title = "Monty Hall"
    min_players = 1
    max_players = 8
    strategic_hint = "Think about the probabilities before choosing."

    def __init__(self, doors: int = 3, initial_choice: str = "model", seed: int | None = None, **kwargs):
        super().__init__(**kwargs)
        if doors < 3:
            raise ValueError("need at least 3 doors")
        if initial_choice not in ("model", "random"):
            raise ValueError(f"unknown initial_choice {initial_choice!r}")
        self.doors = doors
        self.initial_choice = initial_choice
        self.rng = random.Random(seed)
        self.rules = (f"There are {doors} closed doors. One hides a prize; the others are empty. "
                      "You pick a door. The host, who knows where the prize is, then opens "
                      f"{doors - 2} of the other doors, always empty ones, leaving two doors closed: "
                      "yours and one other. You then choose to STAY with your door or SWITCH to the other closed door.")

    @staticmethod
    def label(i: int) -> str:
        return f"DOOR_{i + 1}"

    def history_rows(self, history, me):
        return [{"trial": h["round"], "your_decision": h["info"]["final"][me],
                 "won": bool(h["points"][me])}
                for h in self.recent(history) if h["points"][me] is not None]

    def base_state(self, me, history, round_number, total_rounds):
        state = {"game": self.title, "rules": self.rules}
        if self.show_history:
            state["trial"] = f"{round_number} of {total_rounds}"
            state["previous_trials"] = self.history_rows(history, me)
        return state

    def host_opens(self, prize: int, pick: int) -> tuple[list[int], int]:
        """Return (opened doors, the other closed door)."""
        if pick == prize:
            other = self.rng.choice([d for d in range(self.doors) if d != pick])
        else:
            other = prize
        opened = [d for d in range(self.doors) if d not in (pick, other)]
        return opened, other

    def play_round(self, round_number, total_rounds, history, order, ask):
        n = len(order)
        prize = self.rng.randrange(self.doors)  # same prize location for every player this round
        decisions = [{} for _ in range(n)]
        points: list[float | None] = [None] * n
        picks, finals, opened_all = [None] * n, [None] * n, [None] * n

        for p in range(n):
            state = self.base_state(p, history, round_number, total_rounds)
            if self.initial_choice == "model":
                options = {self.label(i): f"Door {i + 1}" for i in range(self.doors)}
                answer, ok = ask(p, "first_pick", self.request(state, "You are playing Monty Hall. Pick one door.", options))
                decisions[p]["first_pick"] = answer
                if not ok:
                    continue
                pick = int(answer.split("_")[1]) - 1
            else:
                pick = self.rng.randrange(self.doors)
            opened, other = self.host_opens(prize, pick)
            picks[p], opened_all[p] = pick, opened

            state = dict(state)
            state["your_pick"] = f"Door {pick + 1}"
            state["host_opened"] = "all empty: " + ", ".join(f"Door {d + 1}" for d in opened)
            state["closed_doors"] = f"Door {pick + 1} (your pick) and Door {other + 1}"
            answer, ok = ask(p, "stay_or_switch", self.request(
                state, "Do you stay with your door or switch to the other closed door?",
                {STAY: f"Stay with Door {pick + 1}.", SWITCH: f"Switch to Door {other + 1}."}))
            decisions[p]["stay_or_switch"] = answer
            if not ok:
                continue
            final_door = pick if answer == STAY else other
            finals[p] = answer
            points[p] = 1.0 if final_door == prize else 0.0

        info = {"prize": prize, "picks": picks, "opened": opened_all, "final": finals}
        return {"decisions": decisions, "roles": [None] * n, "points": points,
                "void": all(x is None for x in points), "info": info}

    def summarize(self, rounds, names):
        out = {}
        for i, n in enumerate(names):
            stay = [r["points"][i] for r in rounds if r["info"]["final"][i] == STAY]
            switch = [r["points"][i] for r in rounds if r["info"]["final"][i] == SWITCH]
            done = len(stay) + len(switch)
            out[n] = {"trials": done,
                      "switch_rate": len(switch) / done if done else None,
                      "wins": sum(stay) + sum(switch),
                      "win_rate_when_staying": sum(stay) / len(stay) if stay else None,
                      "win_rate_when_switching": sum(switch) / len(switch) if switch else None}
        out["theory"] = {"win_rate_stay": 1 / self.doors, "win_rate_switch": (self.doors - 1) / self.doors}
        return out

    def config(self):
        return super().config() | {"doors": self.doors, "initial_choice": self.initial_choice, "rules": self.rules}
