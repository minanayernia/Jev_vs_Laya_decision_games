"""Rock Paper Scissors: the equilibrium is to play each action with probability 1/3.

Experiments A/B/C from the plan map to runner flags:
    A (no history)            --mode one-shot
    B (history)               --mode repeated
    C (consider the opponent) --mode repeated --prompt strategic
"""

from __future__ import annotations

from games.base import SimultaneousGame

ROCK = "ROCK"
PAPER = "PAPER"
SCISSORS = "SCISSORS"
BEATS = {ROCK: SCISSORS, SCISSORS: PAPER, PAPER: ROCK}  # key beats value


class RockPaperScissors(SimultaneousGame):
    name = "rps"
    title = "Rock Paper Scissors"
    actions = (ROCK, PAPER, SCISSORS)
    question_text = "You are playing Rock Paper Scissors. Choose exactly one action."
    options = {ROCK: "Play rock.", PAPER: "Play paper.", SCISSORS: "Play scissors."}
    rules = ("Both players choose at the same time without seeing the other's choice. "
             "Rock beats scissors, scissors beats paper, paper beats rock. The same choice is a draw.")

    def score(self, a: str, b: str) -> tuple[float, float]:
        if a == b:
            return (0, 0)
        return (1, -1) if BEATS[a] == b else (-1, 1)

    def payoff_description(self) -> str:
        return "Win: +1 point. Loss: -1 point. Draw: 0 points."
