"""Ultimatum Game: a proposer splits a pie; the responder accepts or rejects (both get 0).

Two modes:
    play   One player proposes, the other responds. Roles swap every round.
    sweep  No model proposes. Each player independently responds to offers 0, 1, ..., pie
           in turn, which reveals its acceptance threshold (the "strategy method").
           Useful because the models give the same answer to the same input, so a
           model-made offer might never vary.
"""

from __future__ import annotations

from games.base import Game

ACCEPT = "ACCEPT"
REJECT = "REJECT"


class Ultimatum(Game):
    name = "ultimatum"
    title = "Ultimatum Game"
    alternate_roles = True
    role_names = ("PROPOSER", "RESPONDER")
    strategic_hint = "Consider how the other player is likely to react."

    def __init__(self, pie: int = 10, mode: str = "play", **kwargs):
        super().__init__(**kwargs)
        if mode not in ("play", "sweep"):
            raise ValueError(f"unknown ultimatum mode {mode!r}")
        self.pie = pie
        self.mode = mode
        self.min_players = 2
        self.max_players = 2 if mode == "play" else 8
        self.rules = (f"The PROPOSER splits {pie} points by offering some of them to the RESPONDER. "
                      "If the RESPONDER accepts, both get the proposed split. "
                      "If the RESPONDER rejects, both get 0 points.")

    def offer_options(self) -> dict[str, str]:
        return {str(k): f"Give {k} points to the responder and keep {self.pie - k}." for k in range(self.pie + 1)}

    def response_options(self) -> dict[str, str]:
        return {ACCEPT: "Accept the offer.", REJECT: "Reject the offer; both players get 0."}

    def base_state(self, role: str, round_number: int, total_rounds: int) -> dict:
        state = {"game": self.title, "rules": self.rules, "your_role": role}
        if self.show_history:
            state["round"] = f"{round_number} of {total_rounds}"
        return state

    def history_rows(self, history: list[dict], me: int) -> list[dict]:
        rows = []
        for h in self.recent(history):
            if h["points"][me] is None:
                continue
            row = {"round": h["round"]}
            if self.mode == "play":
                row["your_role"] = h["roles"][me]
            row |= {"offer_to_responder": h["info"]["offers"][me],
                    "response": h["info"]["responses"][me], "your_points": h["points"][me]}
            rows.append(row)
        return rows

    def responder_request(self, me: int, offer: int, history, round_number, total_rounds):
        state = self.base_state("RESPONDER", round_number, total_rounds)
        state["offer"] = f"The proposer offers you {offer} of {self.pie} points and keeps {self.pie - offer}."
        if self.show_history:
            state["previous_rounds"] = self.history_rows(history, me)
        return self.request(state, "You are the responder in the Ultimatum Game. Accept or reject the offer.",
                            self.response_options())

    def play_round(self, round_number, total_rounds, history, order, ask):
        if self.mode == "sweep":
            return self._sweep_round(round_number, total_rounds, history, len(order), ask)
        proposer, responder = order
        roles = [None, None]
        roles[proposer], roles[responder] = self.role_names
        decisions = [{}, {}]

        state = self.base_state("PROPOSER", round_number, total_rounds)
        if self.show_history:
            state["previous_rounds"] = self.history_rows(history, proposer)
        request = self.request(state, "You are the proposer in the Ultimatum Game. "
                                      f"Choose how many of the {self.pie} points to offer the responder.",
                               self.offer_options())
        offer, ok = ask(proposer, "offer", request)
        decisions[proposer]["offer"] = offer
        if not ok:
            return {"decisions": decisions, "roles": roles, "points": None, "void": True, "info": {}}

        k = int(offer)
        response, ok = ask(responder, "response",
                           self.responder_request(responder, k, history, round_number, total_rounds))
        decisions[responder]["response"] = response
        if not ok:
            return {"decisions": decisions, "roles": roles, "points": None, "void": True, "info": {"offer": k}}

        points = [0.0, 0.0]
        if response == ACCEPT:
            points[proposer], points[responder] = self.pie - k, k
        # offers/responses are stored per player so every player's history view uses the same code
        info = {"offer": k, "response": response, "offers": [k, k], "responses": [response, response]}
        return {"decisions": decisions, "roles": roles, "points": points, "void": False, "info": info}

    def _sweep_round(self, round_number, total_rounds, history, n, ask):
        k = (round_number - 1) % (self.pie + 1)
        decisions, points, responses = [], [], []
        for p in range(n):
            response, ok = ask(p, "response", self.responder_request(p, k, history, round_number, total_rounds))
            decisions.append({"response": response})
            responses.append(response if ok else None)
            points.append((k if response == ACCEPT else 0.0) if ok else None)
        return {"decisions": decisions, "roles": ["RESPONDER"] * n, "points": points,
                "void": all(p is None for p in points),
                "info": {"offer": k, "offers": [k] * n, "responses": responses}}

    def summarize(self, rounds, names):
        out = {}
        for i, n in enumerate(names):
            offers, by_offer = [], {}
            for r in rounds:
                d = r["decisions"][i]
                if "offer" in d and not r["void"]:
                    offers.append(int(d["offer"]))
                resp = r["info"].get("responses", [None] * len(names))[i] if r["info"] else None
                if "response" in d and resp is not None:
                    k = r["info"]["offer"]
                    acc, tot = by_offer.get(k, (0, 0))
                    by_offer[k] = (acc + (resp == ACCEPT), tot + 1)
            accepted = [k for k, (a, _) in by_offer.items() if a]
            rejected = [k for k, (a, t) in by_offer.items() if a < t]
            s = {}
            if offers:
                s |= {"offers_made": len(offers), "mean_offer": sum(offers) / len(offers)}
            if by_offer:
                total = sum(t for _, t in by_offer.values())
                s |= {"responses": total,
                      "acceptance_rate": sum(a for a, _ in by_offer.values()) / total,
                      "lowest_accepted_offer": min(accepted) if accepted else None,
                      "highest_rejected_offer": max(rejected) if rejected else None,
                      "accepted_by_offer": {str(k): f"{a}/{t}" for k, (a, t) in sorted(by_offer.items())}}
            out[n] = s
        return out

    def config(self):
        return super().config() | {"pie": self.pie, "mode": self.mode, "rules": self.rules}
