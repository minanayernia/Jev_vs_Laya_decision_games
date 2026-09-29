"""A human player: you answer the same DecisionRequest the models get.

Two ways to answer:
    terminal  `python experiments/run_tournament.py --players human jev`  (typed input)
    browser   experiments/app.py passes a channel folder; the question is written to
              question.json and the page's answer is read from answer.json

Invalid input is simply asked again here (it's a typing slip, not a decision), so a human
never produces an "invalid decision" in the results.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from players.base import DecisionRequest, ModelOutput, Player


def write_atomic(path: Path, data: dict) -> None:
    """Write via a temporary file + rename, so a reader never sees a half-written file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


class HumanPlayer(Player):
    name = "you"

    def __init__(self, channel: Path | None = None, timeout_s: float = 1800, poll_s: float = 0.2):
        self.channel = Path(channel) if channel else None
        self.timeout_s = timeout_s
        self.poll_s = poll_s

    def _query(self, request: DecisionRequest) -> ModelOutput:
        action = self._ask_browser(request) if self.channel else self._ask_terminal(request)
        return ModelOutput(action=action, model="human")

    def _ask_terminal(self, request: DecisionRequest) -> str:
        options = list(request.options)
        print("\n" + "-" * 60)
        print(json.dumps(request.state, indent=2))
        print(f"\n{request.question}")
        for i, (a, desc) in enumerate(request.options.items(), 1):
            print(f"  {i}. {a}  ({desc})")
        while True:
            raw = input("Your choice (name, or its number in the list): ").strip()
            if raw in options:  # names first: in the Beauty Contest "3" means the number 3
                return raw
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return options[int(raw) - 1]
            print("  Not one of the options, try again.")

    def _ask_browser(self, request: DecisionRequest) -> str:
        self.channel.mkdir(parents=True, exist_ok=True)
        question_path, answer_path = self.channel / "question.json", self.channel / "answer.json"
        qid = uuid.uuid4().hex
        answer_path.unlink(missing_ok=True)
        write_atomic(question_path, {"id": qid, "state": request.state, "question": request.question,
                                     "options": request.options})
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            if answer_path.exists():
                answer = json.loads(answer_path.read_text())
                if answer.get("id") == qid and answer.get("action") in request.options:
                    answer_path.unlink(missing_ok=True)
                    question_path.unlink(missing_ok=True)
                    return answer["action"]
            time.sleep(self.poll_s)
        question_path.unlink(missing_ok=True)
        raise TimeoutError(f"no answer within {self.timeout_s:.0f} s")
