import pytest
from types import SimpleNamespace

from services.engines import GameRuleError, GoEngine, GomokuEngine, XiangqiEngine
from services.game_records import apply_result
from services.external_ai import choose_go, choose_xiangqi, difficulty_profile
from services.pikafish import board_to_fen


def test_gomoku_win_and_illegal_move():
    engine = GomokuEngine()
    state = engine.new_state()
    for col in range(5):
        state = engine.apply_move(state, {"row": 7, "col": col}, "black")
        if col < 4:
            state = engine.apply_move(state, {"row": 0, "col": col}, "white")
    assert state["result"]["winner"] == "black"
    with pytest.raises(GameRuleError):
        engine.apply_move(state, {"row": 7, "col": 0}, "black")


def test_go_capture_and_superko():
    engine = GoEngine()
    state = engine.new_state()
    # A basic placement sequence should preserve turn and history.
    state = engine.apply_move(state, {"row": 0, "col": 0}, "black")
    assert state["current_player"] == "white"
    assert len(state["history"]) == 1
    with pytest.raises(GameRuleError):
        engine.apply_move(state, {"row": 0, "col": 0}, "white")


def test_xiangqi_pawn_move_and_turn_validation():
    engine = XiangqiEngine()
    state = engine.new_state()
    state = engine.apply_move(state, {"from_row": 6, "from_col": 0, "to_row": 5, "to_col": 0}, "red")
    assert state["current_player"] == "black"
    with pytest.raises(GameRuleError):
        engine.apply_move(state, {"from_row": 6, "from_col": 2, "to_row": 5, "to_col": 2}, "red")


def test_xiangqi_cannon_can_move_along_an_empty_line():
    engine = XiangqiEngine()
    state = engine.new_state()
    state = engine.apply_move(state, {"from_row": 7, "from_col": 1, "to_row": 7, "to_col": 4}, "red")
    assert state["board"][7][4] == "C"
    assert state["board"][7][1] == "0"


def test_terminal_game_initializes_new_game_stats_before_incrementing():
    class Query:
        def filter_by(self, **kwargs):
            return self

        def first(self):
            return None

    class Database:
        def __init__(self):
            self.added = []

        def query(self, model):
            return Query()

        def add(self, value):
            self.added.append(value)

    db = Database()
    record = SimpleNamespace(status="in_progress", game_code="xiangqi")
    apply_result(db, record, {"result": {"winner": "red", "reason": "checkmate"}}, {"red": 1})
    assert db.added[0].wins == 1


def test_pikafish_fen_uses_red_side_to_move():
    state = XiangqiEngine().new_state()
    fen = board_to_fen(state["board"], state["current_player"])
    assert fen.endswith(" w - - 0 1")
    assert fen.startswith("rnbakabnr/9/1c5c1/p1p1p1p1p")


def test_external_pikafish_move_is_converted_and_rules_checked(monkeypatch):
    monkeypatch.setattr("services.external_ai.resolve_path", lambda code: "/tmp/pikafish")
    monkeypatch.setattr("services.external_ai._run", lambda *args, **kwargs: "bestmove b2e2\n")
    state = XiangqiEngine().new_state()
    move = choose_xiangqi(state, "normal")
    assert move == {"from_row": 7, "from_col": 1, "to_row": 7, "to_col": 4}
    assert XiangqiEngine().apply_move(state, move, "red")["board"][7][4] == "C"


def test_ai_difficulty_profiles_increase_search_budget():
    assert difficulty_profile("easy")["move_time_ms"] < difficulty_profile("normal")["move_time_ms"]
    assert difficulty_profile("normal")["move_time_ms"] < difficulty_profile("hard")["move_time_ms"]


def test_katago_reads_only_the_numbered_genmove_response(monkeypatch):
    seen = {}
    monkeypatch.setattr("services.external_ai.resolve_path", lambda code: "/tmp/katago")
    monkeypatch.setattr("services.external_ai.go_resources", lambda: ("/tmp/gtp.cfg", "/tmp/model.bin.gz"))
    def fake_run(command, commands, timeout, **kwargs):
        seen["commands"] = commands
        return "=1\n\n=2\n\n=3\n\n=4 D4\n\n"
    monkeypatch.setattr("services.external_ai._run", fake_run)
    state = GoEngine().new_state()
    assert choose_go(state, "normal") == {"row": 15, "col": 3}
    assert seen["commands"][-1] == "4 genmove B"
