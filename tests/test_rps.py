import pytest

from games.rps import PAPER as P, ROCK as R, SCISSORS as S, RockPaperScissors


@pytest.mark.parametrize("winner,loser", [(R, S), (S, P), (P, R)])
def test_beats(winner, loser):
    g = RockPaperScissors()
    assert g.score(winner, loser) == (1, -1)
    assert g.score(loser, winner) == (-1, 1)


@pytest.mark.parametrize("a", [R, P, S])
def test_same_action_is_draw(a):
    assert RockPaperScissors().score(a, a) == (0, 0)


def test_every_action_beats_exactly_one_and_loses_to_exactly_one():
    g = RockPaperScissors()
    for a in g.actions:
        results = [g.score(a, b)[0] for b in g.actions]
        assert sorted(results) == [-1, 0, 1]


def test_invalid_actions():
    g = RockPaperScissors()
    assert not g.is_valid("rock") and not g.is_valid("LIZARD") and g.is_valid(R)
