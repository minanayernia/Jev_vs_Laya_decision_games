"""Jev player: TypeSafe AI's hosted System One model, via the official `typesafe-sdk`.

Docs: https://docs.typesafe.ai  (API: POST https://api.typesafe.ai/v1/systemone)

Jev does not generate text. We send a `state` and one typed `Choice` question; Jev returns
the highest-probability option plus a probability for every option and a confidence value.
"""

from __future__ import annotations

import os

from players.base import DecisionRequest, ModelOutput, Player


class JevPlayer(Player):
    name = "jev"
    billed = True  # $ per input token; see --max-jev-tokens in run_tournament.py

    def __init__(self, model: str | None = None, client=None):
        if client is None:
            from typesafe_sdk import RetryPolicy, TypeSafeClient

            # The SDK reads TYPESAFE_API_KEY itself. It retries transient failures
            # (429/5xx/timeouts) on its own; we keep its default policy and say so in the config.
            client = TypeSafeClient(
                model=model or os.getenv("JEV_MODEL", "jev-latest"),
                retry=RetryPolicy(),
            )
        self.client = client

    def _query(self, request: DecisionRequest) -> ModelOutput:
        from typesafe_sdk import Choice

        response = self.client.system_one(
            state=request.state,
            questions={"action": Choice(instructions=request.question, criteria=request.options)},
        )
        answer = response.choices["action"]
        return ModelOutput(
            action=answer.choice,
            probabilities=dict(answer.probabilities),
            confidence=answer.confidence,
            model=response.model,  # resolved version, e.g. "jev-1.13.0" even when asking for jev-latest
            usage={"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
        )
