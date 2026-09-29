import pytest

from games.prisoners_dilemma import COOPERATE as C, DEFECT as D, Payoffs, PrisonersDilemma


def test_default_payoff_matrix():
    g = PrisonersDilemma()
    assert g.score(C, C) == (3, 3)
    assert g.score(C, D) == (0, 5)
    assert g.score(D, C) == (5, 0)
    assert g.score(D, D) == (1, 1)


def test_scores_are_symmetric():
    g = PrisonersDilemma()
    for a in g.actions:
        for b in g.actions:
            pa, pb = g.score(a, b)
            assert g.score(b, a) == (pb, pa)


def test_defect_is_dominant_but_mutual_cooperation_beats_mutual_defection():
    g = PrisonersDilemma()
    for opponent in g.actions:
        assert g.score(D, opponent)[0] > g.score(C, opponent)[0]
    assert g.score(C, C)[0] > g.score(D, D)[0]


def test_custom_payoffs():
    g = PrisonersDilemma(payoffs=Payoffs.parse("4,-1,6,0"))
    assert g.score(C, C) == (4, 4)
    assert g.score(C, D) == (-1, 6)
    assert g.score(D, D) == (0, 0)


@pytest.mark.parametrize("text,expected", [("3,0,5,1", True), ("5,0,3,1", False), ("3,0,7,1", False)])
def test_is_dilemma(text, expected):
    assert Payoffs.parse(text).is_dilemma is expected


@pytest.mark.parametrize("action", [C, D])
def test_valid_actions(action):
    assert PrisonersDilemma().is_valid(action)


@pytest.mark.parametrize("action", [None, "", "cooperate", "MAYBE", "COOPERATE "])
def test_invalid_actions_are_not_normalized(action):
    assert not PrisonersDilemma().is_valid(action)


def past(r, a, b, pa, pb):
    return {"round": r, "decisions": [{"action": a}, {"action": b}], "points": [pa, pb],
            "roles": [None, None], "void": False, "info": {}}


HISTORY = [past(1, C, D, 0, 5), past(2, D, D, 1, 1)]


def test_request_is_from_each_players_point_of_view():
    g = PrisonersDilemma()
    s0 = g.request_for(0, HISTORY, 3, 10).state
    s1 = g.request_for(1, HISTORY, 3, 10).state
    assert s0["previous_rounds"][0] == {"round": 1, "you": C, "opponent": D, "your_points": 0, "opponent_points": 5}
    assert s1["previous_rounds"][0] == {"round": 1, "you": D, "opponent": C, "your_points": 5, "opponent_points": 0}
    assert (s0["your_total_points"], s0["opponent_total_points"]) == (1, 6)
    assert (s1["your_total_points"], s1["opponent_total_points"]) == (6, 1)


def test_both_seats_get_identical_question_and_options():
    g = PrisonersDilemma()
    r0, r1 = g.request_for(0, HISTORY, 3, 10), g.request_for(1, HISTORY, 3, 10)
    assert r0.question == r1.question
    assert r0.options == r1.options
    assert set(r0.state) == set(r1.state)


def test_one_shot_mode_hides_history_and_round():
    state = PrisonersDilemma(show_history=False).request_for(0, HISTORY, 3, 10).state
    assert "previous_rounds" not in state and "round" not in state


def test_history_window_limits_rounds_shown():
    history = [past(i, C, C, 3, 3) for i in range(1, 21)]
    state = PrisonersDilemma(history_window=5).request_for(0, history, 21, 30).state
    assert [h["round"] for h in state["previous_rounds"]] == [16, 17, 18, 19, 20]
    assert state["your_total_points"] == 60  # totals still cover all rounds


def test_strategic_prompt_adds_hint_for_both_seats():
    g = PrisonersDilemma(prompt="strategic")
    q0, q1 = g.request_for(0, [], 1, 1).question, g.request_for(1, [], 1, 1).question
    assert q0 == q1 and q0.endswith(g.strategic_hint)
    assert PrisonersDilemma().request_for(0, [], 1, 1).question == PrisonersDilemma.question_text


def test_reversed_option_order_only_changes_order():
    given = PrisonersDilemma().request_for(0, HISTORY, 3, 10)
    rev = PrisonersDilemma(option_order="reversed").request_for(0, HISTORY, 3, 10)
    assert list(given.options) == [C, D] and list(rev.options) == [D, C]
    assert rev.options == given.options  # same options and descriptions (dict equality ignores order)
    assert rev.state == given.state and rev.question == given.question
