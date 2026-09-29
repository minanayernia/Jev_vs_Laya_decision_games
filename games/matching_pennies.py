"""Matching Pennies: a zero-sum game whose only equilibrium is a 50/50 mixed strategy.

One player is the MATCHER (wins if the coins match), the other the MISMATCHER (wins if
they differ). Roles swap every round so each player spends half the match in each role.
"""

from __future__ import annotations

from games.base import SimultaneousGame

HEADS = "HEADS"
TAILS = "TAILS"


class MatchingPennies(SimultaneousGame):
    name = "matching_pennies"
    title = "Matching Pennies"
    actions = (HEADS, TAILS)
    question_text = "You are playing Matching Pennies. Choose exactly one side of the coin."
    options = {HEADS: "Show heads.", TAILS: "Show tails."}
    rules = ("Both players show a coin at the same time without seeing the other's choice. "
             "The MATCHER wins if both coins show the same side; the MISMATCHER wins if they differ.")
    role_names = ("MATCHER", "MISMATCHER")
    alternate_roles = True

    def score(self, a: str, b: str) -> tuple[float, float]:
        """(matcher, mismatcher). Winner +1, loser -1."""
        return (1, -1) if a == b else (-1, 1)

    def payoff_description(self) -> str:
        return "The winner gets 1 point and the loser loses 1 point."

    def role_description(self, role: int) -> str:
        return ["MATCHER: you win if both coins show the same side.",
                "MISMATCHER: you win if the coins show different sides."][role]

    def summarize(self, rounds, names):
        out = super().summarize(rounds, names)
        for n in names:
            out[n] |= {"wins_as_MATCHER": 0, "rounds_as_MATCHER": 0,
                       "wins_as_MISMATCHER": 0, "rounds_as_MISMATCHER": 0}
        for r in rounds:
            if r["void"]:
                continue
            for n, role, pts in zip(names, r["roles"], r["points"]):
                out[n][f"rounds_as_{role}"] += 1
                out[n][f"wins_as_{role}"] += pts > 0
        return out
