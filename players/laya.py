"""Laya player: Convai Innovations' open-weight decision model, run locally with the `laya` package.

Docs: https://github.com/NandhaKishorM/laya   Weights: https://huggingface.co/convaiinnovations/laya

Same idea as Jev (state + typed question -> probabilities), but the model runs on this
machine. Weights download from Hugging Face on first use. We load one fixed checkpoint
instead of `laya.Router`, so the router can't silently switch models between rounds.
"""

from __future__ import annotations

import os

from players.base import DecisionRequest, ModelOutput, Player


class LayaPlayer(Player):
    name = "laya"

    def __init__(self, repo: str | None = None, subfolder: str | None = None,
                 device: str | None = None, agent=None):
        self.repo = repo or os.getenv("LAYA_REPO", "convaiinnovations/laya")
        self.subfolder = subfolder or os.getenv("LAYA_SUBFOLDER") or None
        self.device = device or os.getenv("LAYA_DEVICE", "cpu")
        if agent is None:
            import laya

            agent = laya.load(self.repo, device=self.device, subfolder=self.subfolder)
        self.agent = agent

    def _query(self, request: DecisionRequest) -> ModelOutput:
        result = self.agent.predict(
            request.state,
            {"action": {"type": "choice", "instructions": request.question, "criteria": request.options}},
        )
        answer = result["answers"]["action"]
        checkpoint = self.repo + (f"/{self.subfolder}" if self.subfolder else "")
        usage = dict(result.get("usage") or {})
        # Laya silently truncates input beyond max_len; record the limit so the runner can flag it.
        usage["context_limit"] = getattr(self.agent, "cfg", {}).get("max_len")
        return ModelOutput(
            action=answer["choice"],
            probabilities=dict(answer["probabilities"]),
            confidence=answer["confidence"],
            model=checkpoint,
            usage=usage,
        )
