import pytest

from experiments.run_tournament import run_match
from games.matching_pennies import HEADS as H, TAILS as T, MatchingPennies
from players.base import FixedPlayer
from tests.helpers import always, make_ask


@pytest.mark.parametrize("a,b,expected", [(H, H, (1, -1)), (T, T, (1, -1)), (H, T, (-1, 1)), (T, H, (-1, 1))])
def test_matcher_wins_on_match(a, b, expected):
    assert MatchingPennies().score(a, b) == expected


def test_zero_sum():
    g = MatchingPennies()
    assert all(sum(g.score(a, b)) == 0 for a in g.actions for b in g.actions)


def test_role_is_shown_and_mapped_to_the_right_player():
    log = []
    g = MatchingPennies()
    result = g.play_round(1, 1, [], [1, 0], make_ask(always(H), always(T), log=log))
    assert result["roles"] == ["MISMATCHER", "MATCHER"]
    assert result["points"] == [1, -1]  # player 0 is the mismatcher and the coins differ
    shown = {i: req.state["your_role"] for i, _, req, _ in log}
    assert shown[0].startswith("MISMATCHER") and shown[1].startswith("MATCHER")


def test_roles_alternate_each_round(tmp_path):
    summary = run_match(MatchingPennies(), [FixedPlayer(H), FixedPlayer(H)], 4, 1, tmp_path, "t")
    stats = summary["game_stats"]
    for name in ("always_heads_1", "always_heads_2"):
        assert stats[name]["rounds_as_MATCHER"] == 2 and stats[name]["rounds_as_MISMATCHER"] == 2
        assert stats[name]["wins"] == 2  # always matching: whoever is the matcher wins
