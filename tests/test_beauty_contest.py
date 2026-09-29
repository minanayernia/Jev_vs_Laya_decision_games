from fractions import Fraction

from games.beauty_contest import BeautyContest
from tests.helpers import always, make_ask


def test_target_is_ratio_times_average():
    assert BeautyContest().target([30, 60, 90]) == 40
    assert BeautyContest(ratio=Fraction(1, 2)).target([0, 100]) == 25


def test_closest_wins():
    g = BeautyContest()
    r = g.play_round(1, 1, [], [0, 1, 2], make_ask(always("20"), always("50"), always("80")))
    # average 50, target 33.33 -> 20 is 13.3 away, 50 is 16.7 away
    assert r["points"] == [1, 0, 0] and r["info"]["winners"] == [0]
    assert abs(r["info"]["target"] - 100 / 3) < 1e-9


def test_tie_splits_the_point_exactly():
    g = BeautyContest(ratio=Fraction(1))
    r = g.play_round(1, 1, [], [0, 1], make_ask(always("40"), always("60")))  # target 50, both 10 away
    assert r["points"] == [0.5, 0.5]


def test_equilibrium_everyone_zero_all_tie():
    r = BeautyContest().play_round(1, 1, [], [0, 1, 2], make_ask(always("0"), always("0"), always("0")))
    assert r["info"]["target"] == 0 and r["points"] == [1 / 3] * 3


def test_invalid_number_voids_round():
    r = BeautyContest().play_round(1, 1, [], [0, 1], make_ask(always("101"), always("50")))
    assert r["void"] and r["points"] is None


def test_options_and_grid():
    req = BeautyContest().request_for(0, 2, [], 1, 1)
    assert list(req.options)[:3] == ["0", "1", "2"] and len(req.options) == 101
    assert list(BeautyContest(step=25).request_for(0, 2, [], 1, 1).options) == ["0", "25", "50", "75", "100"]


def test_all_players_see_same_rules_and_options():
    g = BeautyContest()
    a, b = g.request_for(0, 3, [], 1, 1), g.request_for(2, 3, [], 1, 1)
    assert a.state == b.state and a.options == b.options and a.question == b.question


def test_reversed_option_order_for_many_options():
    req = BeautyContest(step=25, option_order="reversed").request_for(0, 2, [], 1, 1)
    assert list(req.options) == ["100", "75", "50", "25", "0"]
