import json

import pytest

from experiments.app import build_argv
from experiments.run_tournament import run_match
from experiments.viewer import build_html, load_compact
from games.monty_hall import MontyHall
from games.prisoners_dilemma import COOPERATE as C, DEFECT as D, PrisonersDilemma
from players.base import FixedPlayer, ModelOutput, Player

# --- app: request validation -------------------------------------------------------------------------


def test_build_argv_valid_request():
    argv, exp_id = build_argv({"game": "rps", "players": ["jev", "laya"], "rounds": "30", "mode": "one-shot",
                               "prompt": "strategic", "condition": "my_test", "payoffs": "9,9,9,9"})
    assert exp_id.startswith("app_rps_")
    assert argv[:5] == ["--game", "rps", "--players", "jev", "laya"]
    assert ["--rounds", "30"] == argv[argv.index("--rounds"):argv.index("--rounds") + 2]
    assert "--payoffs" not in argv  # only the selected game's own options are passed on


@pytest.mark.parametrize("body", [
    {"game": "chess", "players": ["jev", "laya"]},
    {"game": "rps", "players": ["jev"]},                                    # too few players
    {"game": "rps", "players": ["jev", "laya; rm -rf /"]},                  # not a known player
    {"game": "rps", "players": ["jev", "fixed:ROCK --rounds 99999"]},       # fixed: must be a simple name
    {"game": "rps", "players": ["jev", "laya"], "rounds": "5000"},          # out of range
    {"game": "rps", "players": ["jev", "laya"], "rounds": "10; ls"},
    {"game": "rps", "players": ["jev", "laya"], "mode": "sometimes"},
    {"game": "rps", "players": ["jev", "laya"], "condition": "../../etc"},
    {"game": "prisoners_dilemma", "players": ["jev", "laya"], "payoffs": "3,0,5"},
])
def test_build_argv_rejects_bad_requests(body):
    with pytest.raises(ValueError):
        build_argv(body)


def test_run_ids_are_unique_within_a_second():
    body = {"game": "rps", "players": ["random", "random"]}
    assert len({build_argv(body)[1] for _ in range(20)}) == 20


def test_ultimatum_sweep_allows_more_players():
    build_argv({"game": "ultimatum", "ultimatum_mode": "sweep", "players": ["jev", "laya", "random"]})
    with pytest.raises(ValueError):
        build_argv({"game": "ultimatum", "ultimatum_mode": "play", "players": ["jev", "laya", "random"]})

# --- viewer: loading and embedding -------------------------------------------------------------------


def write_experiment(tmp_path, game, players, rounds, name="exp1"):
    out = tmp_path / name
    run_match(game, players, rounds, 1, out, name)
    (out / "config.json").write_text(json.dumps({"args": {"game": game.name, "condition": "t", "doors": 3},
                                                 "players": [p.name for p in players], "created": "now"}))
    return out


def test_load_compact_finished_run(tmp_path):
    class Chatty(Player):
        name = "jev"

        def _query(self, request):
            return ModelOutput(action=D, probabilities={C: 0.2, D: 0.8}, confidence=0.6)

    exp = load_compact(write_experiment(tmp_path, PrisonersDilemma(), [Chatty(), FixedPlayer(C)], 3))
    assert exp["done"] and exp["players"] == ["jev", "always_cooperate"]
    assert len(exp["rounds"]) == 3 and exp["pending"] == []
    move = exp["rounds"][0]["moves"][0]
    assert (move["p"], move["a"], move["ok"], move["pr"]) == (0, D, True, {C: 0.2, D: 0.8})
    assert exp["summary"]["points"] == {"jev": 15, "always_cooperate": 0}


def test_load_compact_live_run_with_partial_lines(tmp_path):
    path = write_experiment(tmp_path, MontyHall(seed=1), [FixedPlayer("DOOR_1", name="a")], 2)
    (path / "summary.json").unlink()  # still running
    rounds = (path / "rounds.jsonl").read_text().splitlines()
    (path / "rounds.jsonl").write_text(rounds[0] + "\n" + rounds[1][:20])  # half-written last line
    exp = load_compact(path)
    assert not exp["done"] and len(exp["rounds"]) == 1
    assert [p["n"] for p in exp["pending"]] == [2]  # round 2's decisions exist, its outcome doesn't yet


def test_build_html_embeds_data_safely():
    exp = {"id": "x</script><script>alert(1)</script>", "game": "rps", "players": [], "rounds": []}
    html = build_html([exp])
    assert "</script><script>alert(1)" not in html
    assert '"serve":false' in html and "Play or watch a game" in html  # the run tab code exists but is disabled

# --- human player --------------------------------------------------------------------------------------


def test_human_terminal_retries_typos_and_accepts_numbers(monkeypatch, capsys):
    from players.human import HumanPlayer
    from games.beauty_contest import BeautyContest
    req = PrisonersDilemma().request_for(0, [], 1, 1)
    answers = iter(["maybe", "2"])  # a typo, then option number 2
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert HumanPlayer().decide(req).action == D
    # in the Beauty Contest "3" is a valid option itself, so it means the number 3, not the 3rd option
    monkeypatch.setattr("builtins.input", lambda _: "3")
    assert HumanPlayer().decide(BeautyContest().request_for(0, 2, [], 1, 1)).action == "3"


def test_human_browser_channel_round_trip(tmp_path):
    import threading
    from players.human import HumanPlayer, write_atomic
    req = PrisonersDilemma().request_for(0, [], 1, 1)
    player = HumanPlayer(channel=tmp_path, poll_s=0.01)
    result = {}
    t = threading.Thread(target=lambda: result.update(d=player.decide(req)))
    t.start()
    q = tmp_path / "question.json"
    for _ in range(500):
        if q.exists():
            break
        threading.Event().wait(0.01)
    question = json.loads(q.read_text())
    assert question["options"] == req.options and question["state"] == req.state
    write_atomic(tmp_path / "answer.json", {"id": "wrong-id", "action": C})   # stale answer is ignored
    threading.Event().wait(0.05)
    write_atomic(tmp_path / "answer.json", {"id": question["id"], "action": C})
    t.join(timeout=5)
    assert result["d"].action == C and result["d"].error is None
    assert not q.exists() and not (tmp_path / "answer.json").exists()


def test_human_browser_timeout_is_an_error_not_a_crash(tmp_path):
    from players.human import HumanPlayer
    d = HumanPlayer(channel=tmp_path, timeout_s=0.05, poll_s=0.01).decide(PrisonersDilemma().request_for(0, [], 1, 1))
    assert d.action is None and d.error.startswith("TimeoutError")


def test_build_argv_human_gets_a_channel_and_only_one_human():
    argv, exp_id = build_argv({"game": "rps", "players": ["human", "jev"]})
    assert argv[argv.index("--human-channel") + 1].endswith(exp_id)
    with pytest.raises(ValueError):
        build_argv({"game": "beauty_contest", "players": ["human", "human", "jev"]})
