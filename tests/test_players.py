"""Adapter tests with stubbed clients: check we send and read the documented formats.

No API key or model download needed.
"""

from types import SimpleNamespace

from games.prisoners_dilemma import PrisonersDilemma
from players.jev import JevPlayer
from players.laya import LayaPlayer

REQUEST = PrisonersDilemma().request_for(0, [], 1, 1)


class StubTypeSafeClient:
    def system_one(self, state, questions):
        self.state, self.questions = state, questions
        answer = SimpleNamespace(choice="DEFECT", confidence=0.4,
                                 probabilities={"COOPERATE": 0.3, "DEFECT": 0.7})
        return SimpleNamespace(model="jev-1.13.0", choices={"action": answer},
                               usage=SimpleNamespace(input_tokens=120, output_tokens=0))


def test_jev_sends_choice_question_and_reads_answer():
    client = StubTypeSafeClient()
    d = JevPlayer(client=client).decide(REQUEST)
    q = client.questions["action"]
    assert q.instructions == REQUEST.question and dict(q.criteria) == REQUEST.options
    assert client.state == REQUEST.state
    assert (d.action, d.confidence, d.model, d.error) == ("DEFECT", 0.4, "jev-1.13.0", None)
    assert d.probabilities == {"COOPERATE": 0.3, "DEFECT": 0.7}


class StubLayaAgent:
    def predict(self, state, questions):
        self.state, self.questions = state, questions
        return {"answers": {"action": {"choice": "COOPERATE", "confidence": 0.9,
                                       "probabilities": {"COOPERATE": 0.95, "DEFECT": 0.05}}},
                "usage": {"input_tokens": 90, "output_tokens": 0}}


def test_laya_sends_choice_question_and_reads_answer():
    agent = StubLayaAgent()
    d = LayaPlayer(agent=agent).decide(REQUEST)
    assert agent.questions == {"action": {"type": "choice", "instructions": REQUEST.question,
                                          "criteria": REQUEST.options}}
    assert (d.action, d.confidence, d.error) == ("COOPERATE", 0.9, None)
    assert d.model == "convaiinnovations/laya"


def test_player_exception_becomes_error_not_crash():
    class Boom:
        def predict(self, state, questions):
            raise ConnectionError("down")

    d = LayaPlayer(agent=Boom()).decide(REQUEST)
    assert d.action is None and d.error == "ConnectionError: down"
