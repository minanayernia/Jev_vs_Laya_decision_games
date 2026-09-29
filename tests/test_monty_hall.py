import pytest

from games.monty_hall import STAY, SWITCH, MontyHall
from tests.helpers import always, make_ask


def win_rate(decision, doors, trials=3000):
    g = MontyHall(doors=doors, initial_choice="random", seed=42)
    wins = sum(g.play_round(t, trials, [], [0], make_ask(always(decision)))["points"][0] for t in range(trials))
    return wins / trials


@pytest.mark.parametrize("doors", [3, 10])
def test_stay_wins_one_in_n(doors):
    assert win_rate(STAY, doors) == pytest.approx(1 / doors, abs=0.03)


@pytest.mark.parametrize("doors", [3, 10])
def test_switch_wins_n_minus_one_in_n(doors):
    assert win_rate(SWITCH, doors) == pytest.approx((doors - 1) / doors, abs=0.03)


@pytest.mark.parametrize("doors", [3, 5, 100])
def test_host_never_opens_pick_or_prize(doors):
    g = MontyHall(doors=doors, seed=1)
    for _ in range(300):
        prize, pick = g.rng.randrange(doors), g.rng.randrange(doors)
        opened, other = g.host_opens(prize, pick)
        assert len(opened) == doors - 2
        assert pick not in opened and prize not in opened and other != pick
        assert (prize == pick) or (other == prize)


def test_model_picks_first_door_and_sees_host_result():
    log = []
    g = MontyHall(doors=5, seed=0)
    r = g.play_round(1, 1, [], [0], make_ask(lambda step, req: "DOOR_2" if step == "first_pick" else STAY, log=log))
    assert [step for _, step, _, _ in log] == ["first_pick", "stay_or_switch"]
    second = log[1][2]
    assert second.state["your_pick"] == "Door 2" and set(second.options) == {STAY, SWITCH}
    assert r["points"][0] == (1.0 if r["info"]["prize"] == 1 else 0.0)


def test_invalid_player_does_not_void_others():
    g = MontyHall(seed=0)
    r = g.play_round(1, 1, [], [0, 1], make_ask(always("DOOR_9"), lambda s, req: "DOOR_1" if s == "first_pick" else SWITCH))
    assert r["points"][0] is None and r["points"][1] in (0.0, 1.0) and not r["void"]


def test_same_prize_for_all_players_in_a_round():
    g = MontyHall(seed=3)
    r = g.play_round(1, 1, [], [0, 1], make_ask(always("DOOR_1"), always("DOOR_1")))
    # both invalid at step 2 (DOOR_1 isn't STAY/SWITCH) -> void, but one prize location was drawn
    assert isinstance(r["info"]["prize"], int) and r["void"]


def test_reversed_order_applies_to_both_steps():
    log = []
    MontyHall(doors=3, seed=0, option_order="reversed").play_round(
        1, 1, [], [0], make_ask(lambda s, req: "DOOR_1" if s == "first_pick" else STAY, log=log))
    assert list(log[0][2].options) == ["DOOR_3", "DOOR_2", "DOOR_1"]
    assert list(log[1][2].options) == [SWITCH, STAY]
