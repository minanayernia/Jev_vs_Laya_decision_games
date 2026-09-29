import json

from experiments.run_tournament import run_match
from games.prisoners_dilemma import COOPERATE as C, DEFECT as D, PrisonersDilemma
from players.base import FixedPlayer, ModelOutput, Player


class ScriptedPlayer(Player):
    """Returns the given answers in order; an Exception entry is raised instead."""

    def __init__(self, name, answers):
        self.name, self.answers = name, list(answers)

    def _query(self, request):
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return ModelOutput(action=a)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_full_match_scores_and_logs(tmp_path):
    summary = run_match(PrisonersDilemma(), [FixedPlayer(C), FixedPlayer(D)], 4, 1, tmp_path, "t")
    assert summary["players"]["always_cooperate"]["points"] == 0
    assert summary["players"]["always_defect"]["points"] == 20
    assert summary["players"]["always_defect"]["actions"] == {"action": {D: 4}}
    assert len(read_jsonl(tmp_path / "decisions.jsonl")) == 8
    assert len(read_jsonl(tmp_path / "rounds.jsonl")) == 4


def test_invalid_answer_voids_round_and_is_not_converted(tmp_path):
    bad = ScriptedPlayer("bad", ["cooperate", C])  # lowercase is invalid
    summary = run_match(PrisonersDilemma(), [bad, FixedPlayer(D)], 2, 1, tmp_path, "t")
    rounds = read_jsonl(tmp_path / "rounds.jsonl")
    assert rounds[0]["void"] and rounds[0]["points"] is None
    assert rounds[0]["decisions"][0]["action"] == "cooperate"  # raw answer kept, not normalized
    assert not rounds[1]["void"]
    assert summary["players"]["bad"]["invalid_decisions"] == 1
    assert summary["players"]["bad"]["actions"] == {"action": {C: 1}}
    assert summary["void_rounds"] == 1


def test_void_round_is_hidden_from_history(tmp_path):
    bad = ScriptedPlayer("bad", ["??", C, C])
    run_match(PrisonersDilemma(), [bad, FixedPlayer(D)], 3, 1, tmp_path, "t")
    last = [d for d in read_jsonl(tmp_path / "decisions.jsonl") if d["round"] == 3][0]
    assert [h["round"] for h in last["state"]["previous_rounds"]] == [2]


def test_retry_logs_every_attempt(tmp_path):
    flaky = ScriptedPlayer("flaky", [RuntimeError("timeout"), "NOPE", D])
    summary = run_match(PrisonersDilemma(), [flaky, FixedPlayer(C)], 1, 3, tmp_path, "t")
    attempts = [d for d in read_jsonl(tmp_path / "decisions.jsonl") if d["player"] == "flaky"]
    assert [(a["attempt"], a["valid"]) for a in attempts] == [(1, False), (2, False), (3, True)]
    assert attempts[0]["error"] == "RuntimeError: timeout"
    s = summary["players"]["flaky"]
    assert (s["invalid_attempts"], s["invalid_decisions"], s["errors"]) == (2, 0, 1)
    assert s["points"] == 5


def test_missing_confidence_is_recorded_as_null(tmp_path):
    run_match(PrisonersDilemma(), [FixedPlayer(C), FixedPlayer(C)], 1, 1, tmp_path, "t")
    for d in read_jsonl(tmp_path / "decisions.jsonl"):
        assert d["confidence"] is None and d["probabilities"] is None


class BilledPlayer(Player):
    """Pretends to be a paid API: every call uses 100 input tokens."""

    billed = True

    def __init__(self, name="paid"):
        self.name = name

    def _query(self, request):
        return ModelOutput(action=C, usage={"input_tokens": 100, "output_tokens": 0})


def test_token_budget_stops_the_match_early(tmp_path):
    summary = run_match(PrisonersDilemma(), [BilledPlayer(), FixedPlayer(D)], 10, 1, tmp_path, "t",
                        max_billed_tokens=250, price_per_mtok=1.0)
    # 100 tokens per round: the budget is crossed during round 3, so that round finishes and we stop
    assert summary["rounds"] == 3 and summary["rounds_requested"] == 10
    assert "budget" in summary["stopped_early"]
    assert summary["billed_input_tokens"] == 300
    assert summary["estimated_cost_usd"] == 300 / 1e6
    assert len(read_jsonl(tmp_path / "rounds.jsonl")) == 3


def test_unbilled_tokens_do_not_count_toward_budget(tmp_path):
    unbilled = BilledPlayer("local")
    unbilled.billed = False
    summary = run_match(PrisonersDilemma(), [unbilled, FixedPlayer(D)], 5, 1, tmp_path, "t",
                        max_billed_tokens=100)
    assert summary["rounds"] == 5 and summary["stopped_early"] is None
    assert summary["players"]["local"]["input_tokens"] == 500
    assert summary["billed_input_tokens"] == 0


def test_no_budget_means_no_limit(tmp_path):
    summary = run_match(PrisonersDilemma(), [BilledPlayer(), FixedPlayer(D)], 5, 1, tmp_path, "t",
                        max_billed_tokens=None)
    assert summary["rounds"] == 5 and summary["billed_input_tokens"] == 500


def test_self_play_names_are_made_unique(tmp_path):
    summary = run_match(PrisonersDilemma(), [FixedPlayer(C), FixedPlayer(C)], 1, 1, tmp_path, "t")
    assert list(summary["players"]) == ["always_cooperate_1", "always_cooperate_2"]


def test_wrong_player_count_is_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        run_match(PrisonersDilemma(), [FixedPlayer(C)], 1, 1, tmp_path, "t")


def test_context_limit_is_flagged(tmp_path):
    class Truncated(Player):
        name = "long"

        def _query(self, request):
            return ModelOutput(action=C, usage={"input_tokens": 512, "context_limit": 512})

    summary = run_match(PrisonersDilemma(), [Truncated(), FixedPlayer(C)], 2, 1, tmp_path, "t")
    assert summary["players"]["long"]["at_context_limit"] == 2
