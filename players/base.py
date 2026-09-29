"""The common player interface.

Every player (Jev, Laya, or a simple baseline) receives the same `DecisionRequest`
and returns a `Decision`. The game engine never sees SDK-specific objects.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DecisionRequest:
    """One decision problem, identical for every player.

    `state` is the JSON-serializable information shown to the player.
    `question` + `options` describe the choice. Both Jev and Laya take exactly
    this shape (a state plus a typed "choice" question), so no model gets a
    different framing from the other.
    """

    game: str
    state: dict[str, Any]
    question: str
    options: dict[str, str]  # action name -> neutral description


@dataclass
class Decision:
    """What a player returned. `action` is the raw answer and is NOT validated here."""

    action: str | None
    latency_ms: float
    probabilities: dict[str, float] | None = None  # only if the model reports them
    confidence: float | None = None  # only if the model reports it
    model: str | None = None  # model/checkpoint that actually answered
    usage: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class ModelOutput:
    """What a concrete player's `_query` returns before timing is attached."""

    action: str | None
    probabilities: dict[str, float] | None = None
    confidence: float | None = None
    model: str | None = None
    usage: dict[str, Any] | None = field(default=None)


class Player:
    """Base class. Subclasses implement `_query`; `decide` adds timing and error capture."""

    name = "player"
    billed = False  # True if calls cost money; the runner's token budget applies to these

    def _query(self, request: DecisionRequest) -> ModelOutput:
        raise NotImplementedError

    def decide(self, request: DecisionRequest) -> Decision:
        start = time.perf_counter()
        try:
            out = self._query(request)
        except Exception as exc:  # an API/model failure is data, not a crash
            return Decision(
                action=None,
                latency_ms=(time.perf_counter() - start) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
        return Decision(
            action=out.action,
            latency_ms=(time.perf_counter() - start) * 1000,
            probabilities=out.probabilities,
            confidence=out.confidence,
            model=out.model,
            usage=out.usage,
        )


class FixedPlayer(Player):
    """Always plays the same action. Useful as a baseline and for testing without APIs."""

    def __init__(self, action: str, name: str | None = None):
        self.action = action
        self.name = name or f"always_{action.lower()}"

    def _query(self, request: DecisionRequest) -> ModelOutput:
        return ModelOutput(action=self.action, model="fixed")


class RandomPlayer(Player):
    """Picks uniformly at random among the options (seeded for reproducibility)."""

    def __init__(self, seed: int | None = None, name: str = "random"):
        self.rng = random.Random(seed)
        self.name = name

    def _query(self, request: DecisionRequest) -> ModelOutput:
        options = sorted(request.options)
        p = 1 / len(options)
        return ModelOutput(
            action=self.rng.choice(options),
            probabilities={o: p for o in options},
            model="uniform_random",
        )
