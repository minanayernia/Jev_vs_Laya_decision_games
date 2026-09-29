from experiments.run_tournament import run_match
from games.ultimatum import ACCEPT, REJECT, Ultimatum
from players.base import FixedPlayer
from tests.helpers import always, make_ask


def test_accepted_offer_splits_the_pie():
    r = Ultimatum(pie=10).play_round(1, 1, [], [0, 1], make_ask(always("3"), always(ACCEPT)))
    assert r["points"] == [7, 3] and r["roles"] == ["PROPOSER", "RESPONDER"] and not r["void"]


def test_rejected_offer_gives_both_zero():
    r = Ultimatum(pie=10).play_round(1, 1, [], [0, 1], make_ask(always("3"), always(REJECT)))
    assert r["points"] == [0, 0] and not r["void"]


def test_responder_sees_the_offer():
    log = []
    Ultimatum(pie=10).play_round(1, 1, [], [1, 0], make_ask(always(ACCEPT), always("2"), log=log))
    (_, step, req, _), = [e for e in log if e[1] == "response"]
    assert "offers you 2 of 10" in req.state["offer"] and set(req.options) == {ACCEPT, REJECT}


def test_invalid_offer_voids_round_and_responder_is_not_asked():
    log = []
    r = Ultimatum().play_round(1, 1, [], [0, 1], make_ask(always("11"), always(ACCEPT), log=log))
    assert r["void"] and r["points"] is None
    assert [step for _, step, _, _ in log] == ["offer"]


def test_offer_options_cover_whole_pie():
    assert list(Ultimatum(pie=4).offer_options()) == ["0", "1", "2", "3", "4"]


def test_roles_alternate(tmp_path):
    # both "players" answer "5" to an offer question and ACCEPT to a response question
    class Both(FixedPlayer):
        def _query(self, request):
            self.action = "5" if "5" in request.options else ACCEPT
            return super()._query(request)

    summary = run_match(Ultimatum(), [Both("x", name="a"), Both("x", name="b")], 4, 1, tmp_path, "t")
    assert summary["players"]["a"]["points"] == summary["players"]["b"]["points"] == 20  # 5 per round x 4
    assert summary["game_stats"]["a"]["offers_made"] == 2 and summary["game_stats"]["a"]["responses"] == 2


def test_sweep_cycles_offers_and_finds_threshold(tmp_path):
    class Threshold(FixedPlayer):
        """Accepts offers of at least 3."""

        def _query(self, request):
            offer = int(request.state["offer"].split("offers you ")[1].split(" ")[0])
            self.action = ACCEPT if offer >= 3 else REJECT
            return super()._query(request)

    g = Ultimatum(pie=10, mode="sweep")
    summary = run_match(g, [Threshold("x", name="t"), FixedPlayer(ACCEPT, name="yes")], 11, 1, tmp_path, "t")
    s = summary["game_stats"]["t"]
    assert s["lowest_accepted_offer"] == 3 and s["highest_rejected_offer"] == 2
    assert s["accepted_by_offer"]["0"] == "0/1" and s["accepted_by_offer"]["10"] == "1/1"
    assert summary["players"]["t"]["points"] == sum(range(3, 11))
    assert summary["players"]["yes"]["points"] == sum(range(0, 11))
