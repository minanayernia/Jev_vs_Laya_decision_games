import json

import pytest

from experiments.analyze import (analyze, load_experiment, longest_streak, overlap, position_bias,
                                 reasoning_level, wilson)
from experiments.run_tournament import run_match
from games.prisoners_dilemma import COOPERATE as C, DEFECT as D, PrisonersDilemma
from games.rps import PAPER, ROCK, RockPaperScissors
from players.base import FixedPlayer, ModelOutput, Player, RandomPlayer


def test_wilson_interval():
    lo, hi = wilson(50, 100)
    assert lo == pytest.approx(0.404, abs=0.001) and hi == pytest.approx(0.596, abs=0.001)
    assert wilson(0, 10)[0] == 0 and wilson(10, 10)[1] == 1
    assert wilson(0, 0) is None


def test_overlap():
    assert overlap({"A": 1}, {"A": 1}) == 1
    assert overlap({"A": 1}, {"B": 1}) == 0
    assert overlap({"A": 0.5, "B": 0.5}, {"A": 1}) == 0.5


def test_longest_streak():
    assert longest_streak(["A", "A", "B", "B", "B", "A"]) == 3
    assert longest_streak([]) == 0


def test_reasoning_level():
    assert reasoning_level(50, 2 / 3) == pytest.approx(0)
    assert reasoning_level(50 * (2 / 3) ** 2, 2 / 3) == pytest.approx(2)
    assert reasoning_level(0, 2 / 3) is None  # equilibrium choice: infinite depth


def save_match(tmp_path, game, players, rounds, name="t", **config):
    out = tmp_path / name
    run_match(game, players, rounds, 1, out, name)
    args = {"condition": "test", "option_order": game.option_order, "rounds": rounds, "game": game.name,
            "players": [p.name for p in players], **config}
    (out / "config.json").write_text(json.dumps({"args": args, "game_config": game.config()}))
    return load_experiment(out)


def test_repeated_identical_inputs_are_not_tested(tmp_path):
    # one-shot: every round has the same input, so a chi-square test would be meaningless
    exp = save_match(tmp_path, RockPaperScissors(show_history=False), [FixedPlayer(ROCK), FixedPlayer(PAPER)], 20)
    s = analyze(exp)["players"]["always_rock"]["steps"]["action"]
    assert s["distinct_inputs"] == 1
    assert "skipped" in s["test_vs_equilibrium"]


def test_varied_inputs_are_tested_against_equilibrium(tmp_path):
    exp = save_match(tmp_path, RockPaperScissors(), [FixedPlayer(ROCK), RandomPlayer(seed=1)], 60)
    s = analyze(exp)["players"]["always_rock"]["steps"]["action"]
    assert s["distinct_inputs"] == 60
    assert s["test_vs_equilibrium"]["p_value"] < 1e-10  # 100% ROCK is far from 1/3 each
    assert s["frequencies"][ROCK]["share"] == 1 and s["mean_position"] == 0


def test_response_stats(tmp_path):
    class TitForTat(Player):
        name = "tft"

        def _query(self, request):
            prev = request.state["previous_rounds"]
            return ModelOutput(action=prev[-1]["opponent"] if prev else C)

    class Alternator(Player):
        name = "alt"
        n = 0

        def _query(self, request):
            self.n += 1
            return ModelOutput(action=C if self.n % 2 else D)

    exp = save_match(tmp_path, PrisonersDilemma(), [TitForTat(), Alternator()], 20)
    r = analyze(exp)["responses"]["tft"]
    assert r["after_opponent_action"] == {C: {C: 10}, D: {D: 9}}  # copies the opponent's last move
    # TFT opens with C and copies the opponent's round-1 C in round 2 (one repeat); after that it alternates
    assert r["repeat_rate"] == pytest.approx(1 / 19)


def test_position_bias_detects_first_option_habit(tmp_path):
    class FirstOption(Player):
        name = "laya"

        def _query(self, request):
            return ModelOutput(action=list(request.options)[0])

    given = save_match(tmp_path, PrisonersDilemma(show_history=False), [FirstOption(), FixedPlayer(D)], 5, "g")
    rev = save_match(tmp_path, PrisonersDilemma(show_history=False, option_order="reversed"),
                     [FirstOption(), FixedPlayer(D)], 5, "r")
    (pair,) = position_bias([given, rev])["pairs"]
    assert (pair["top_given"], pair["top_reversed"]) == (C, D)
    assert pair["verdict"] == "position bias (same slot)"


def test_position_bias_detects_real_preference(tmp_path):
    class Stubborn(Player):
        name = "jev"

        def _query(self, request):
            return ModelOutput(action=D)

    given = save_match(tmp_path, PrisonersDilemma(show_history=False), [Stubborn(), FixedPlayer(D)], 5, "g")
    rev = save_match(tmp_path, PrisonersDilemma(show_history=False, option_order="reversed"),
                     [Stubborn(), FixedPlayer(D)], 5, "r")
    (pair,) = position_bias([given, rev])["pairs"]
    assert pair["verdict"] == "preference (same choice)"
