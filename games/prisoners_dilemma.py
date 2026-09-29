"""Prisoner's Dilemma: cooperate or defect, with a configurable payoff matrix."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from games.base import SimultaneousGame

COOPERATE = "COOPERATE"
DEFECT = "DEFECT"
ACTIONS = (COOPERATE, DEFECT)


@dataclass(frozen=True)
class Payoffs:
    """Standard PD notation, points for *me* given (my action, their action).

    R: both cooperate (Reward)        S: I cooperate, they defect (Sucker)
    T: I defect, they cooperate (Temptation)   P: both defect (Punishment)
    """

    R: float = 3
    S: float = 0
    T: float = 5
    P: float = 1

    @property
    def is_dilemma(self) -> bool:
        # T > R > P > S makes DEFECT dominant; 2R > T + S makes mutual cooperation
        # better than taking turns exploiting each other in repeated play.
        return self.T > self.R > self.P > self.S and 2 * self.R > self.T + self.S

    @classmethod
    def parse(cls, text: str) -> "Payoffs":
        """Parse 'R,S,T,P', e.g. '3,0,5,1'."""
        r, s, t, p = (float(x) for x in text.split(","))
        return cls(R=r, S=s, T=t, P=p)


class PrisonersDilemma(SimultaneousGame):
    name = "prisoners_dilemma"
    title = "Prisoner's Dilemma"
    actions = ACTIONS
    question_text = "You are playing Prisoner's Dilemma. Choose exactly one action."
    options = {
        COOPERATE: "Cooperate with the opponent.",
        DEFECT: "Defect against the opponent.",
    }
    rules = "Both players choose at the same time without seeing the other's choice."

    def __init__(self, payoffs: Payoffs | None = None, **kwargs):
        super().__init__(**kwargs)
        self.payoffs = payoffs or Payoffs()

    def score(self, a: str, b: str) -> tuple[float, float]:
        p = self.payoffs
        table = {
            (COOPERATE, COOPERATE): (p.R, p.R),
            (COOPERATE, DEFECT): (p.S, p.T),
            (DEFECT, COOPERATE): (p.T, p.S),
            (DEFECT, DEFECT): (p.P, p.P),
        }
        return table[(a, b)]

    def payoff_description(self) -> dict[str, str]:
        p = self.payoffs
        return {
            "you COOPERATE, opponent COOPERATES": f"you get {p.R:g}, opponent gets {p.R:g}",
            "you COOPERATE, opponent DEFECTS": f"you get {p.S:g}, opponent gets {p.T:g}",
            "you DEFECT, opponent COOPERATES": f"you get {p.T:g}, opponent gets {p.S:g}",
            "you DEFECT, opponent DEFECTS": f"you get {p.P:g}, opponent gets {p.P:g}",
        }

    def summarize(self, rounds, names):
        out = {"outcomes": {"both_cooperate": 0, "both_defect": 0, "one_defects": 0}}
        for r in rounds:
            if r["void"]:
                continue
            acts = [d["action"] for d in r["decisions"]]
            key = ("both_cooperate" if acts == [COOPERATE] * 2 else
                   "both_defect" if acts == [DEFECT] * 2 else "one_defects")
            out["outcomes"][key] += 1
        return out

    def config(self):
        return super().config() | {"payoff_matrix": asdict(self.payoffs), "is_dilemma": self.payoffs.is_dilemma}
