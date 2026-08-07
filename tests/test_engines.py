import pytest
import asyncio
import json
from types import SimpleNamespace
from pathlib import Path
from fastapi import BackgroundTasks

from services.engines import GameRuleError, GoEngine, GomokuEngine, XiangqiEngine
from services.game_records import apply_result
from services.external_ai import AIEngineError, _PersistentGtp, _is_current_platform_binary, choose_go, choose_xiangqi, difficulty_profile, warm_go_engine
from services.pikafish import board_to_fen
import routers.games as games_router
from routers.games import _ai_move
from services.state_store import RedisStateStore


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


def test_xiangqi_undo_restores_the_previous_position():
    engine = XiangqiEngine()
    state = engine.apply_move(engine.new_state(), {"from_row": 6, "from_col": 0, "to_row": 5, "to_col": 0}, "red")
    restored = engine.undo(state)
    assert restored["current_player"] == "red"
    assert restored["board"][6][0] == "P"
    assert restored["board"][5][0] == "0"
    assert restored["history"] == []


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
    def fake_run(command, commands, timeout, cwd, response):
        seen["commands"] = commands
        return "=1\n\n=2\n\n=3\n\n=4 D4\n\n"
    monkeypatch.setattr("services.external_ai._KATAGO_GTP.request", fake_run)
    state = GoEngine().new_state()
    assert choose_go(state, "normal") == {"row": 15, "col": 3}
    assert seen["commands"][-1] == "4 genmove B"


def test_human_katago_model_receives_required_profile(monkeypatch):
    seen = {}
    monkeypatch.setattr("services.external_ai.resolve_path", lambda code: "/tmp/katago")
    monkeypatch.setattr("services.external_ai.go_resources", lambda: ("/tmp/gtp.cfg", "/tmp/b18c384nbt-humanv0.bin.gz"))
    monkeypatch.setattr("services.external_ai._KATAGO_GTP.request", lambda command, *args, **kwargs: seen.setdefault("command", command) and "=4 D4\n")
    assert choose_go(GoEngine().new_state(), "normal") == {"row": 15, "col": 3}
    assert "humanSLProfile=rank_9d" in seen["command"]


def test_gomoku_ai_validation_does_not_apply_the_move_twice(monkeypatch):
    engine = GomokuEngine()
    state = engine.apply_move(engine.new_state(), {"row": 7, "col": 7}, "black")
    monkeypatch.setattr("routers.games.choose_external_move", lambda *args: {"row": 6, "col": 6})
    move = _ai_move("gomoku", engine, state, "normal")
    assert move == {"row": 6, "col": 6}
    assert state["board"][6][6] == 0
    assert engine.apply_move(state, move, "white")["board"][6][6] == 2


def test_warming_go_without_an_engine_is_a_noop(monkeypatch):
    monkeypatch.setattr("services.external_ai.resolve_path", lambda code: None)
    monkeypatch.setattr("services.external_ai.go_resources", lambda: (None, None))
    warm_go_engine()


def test_linux_runtime_rejects_windows_engine_binary(monkeypatch):
    monkeypatch.setattr("services.external_ai._is_windows_runtime", lambda: False)
    assert _is_current_platform_binary(Path("katago"))
    assert not _is_current_platform_binary(Path("katago.exe"))


def test_windows_runtime_rejects_linux_engine_binary(monkeypatch):
    monkeypatch.setattr("services.external_ai._is_windows_runtime", lambda: True)
    assert _is_current_platform_binary(Path("katago.exe"))
    assert not _is_current_platform_binary(Path("katago"))


def test_katago_exit_diagnostics_are_not_in_the_client_error():
    gtp = _PersistentGtp()
    gtp._process = SimpleNamespace(poll=lambda: None)
    gtp._stderr_tail.append("/srv/engines/katago: error while loading libzip.so.5")

    error = gtp._exit_error()

    assert str(error) == "AI 服务暂时不可用，请稍后重试"
    assert "libzip" not in str(error)


def test_ai_move_does_not_expose_engine_diagnostics(monkeypatch):
    monkeypatch.setattr(
        games_router,
        "choose_external_move",
        lambda *args: (_ for _ in ()).throw(AIEngineError("/srv/engines/katago: libzip.so.5 missing")),
    )

    with pytest.raises(GameRuleError, match="AI 服务暂时不可用，请稍后重试") as exc_info:
        _ai_move("gomoku", GomokuEngine(), GomokuEngine().new_state(), "normal")

    assert "libzip" not in str(exc_info.value)


def test_unhandled_error_response_does_not_expose_exception_details():
    from main import INTERNAL_ERROR_MESSAGE, unhandled_exception_handler

    response = asyncio.run(
        unhandled_exception_handler(SimpleNamespace(url=SimpleNamespace(path="/test")), RuntimeError("database password=secret"))
    )

    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": INTERNAL_ERROR_MESSAGE}


def test_ai_session_returns_player_move_before_ai_thinks(monkeypatch):
    state = GomokuEngine().new_state() | {"ai_difficulty": "normal"}
    record = SimpleNamespace(id=999, game_code="gomoku", status="in_progress", player1_id=1, game_state=state)
    monkeypatch.setattr(games_router, "_get_record", lambda *args: record)
    monkeypatch.setattr(games_router.state_store, "load_state", lambda *args: None)
    monkeypatch.setattr(games_router, "_persist", lambda *args: None)
    tasks = BackgroundTasks()
    response = games_router.move("gomoku", games_router.MoveBody(game_id=999, move={"row": 7, "col": 7}), tasks, None, SimpleNamespace(id=1))
    assert response.data["state"]["history"] == [{"row": 7, "col": 7, "player": "black"}]
    assert len(tasks.tasks) == 1


def test_ai_session_undo_removes_a_complete_player_ai_exchange(monkeypatch):
    engine = GomokuEngine()
    state = engine.apply_move(engine.new_state(), {"row": 7, "col": 7}, "black")
    state = engine.apply_move(state, {"row": 7, "col": 8}, "white")
    record = SimpleNamespace(id=999, game_code="gomoku", game_type="ai", status="in_progress", player1_id=1, game_state=state)

    class Database:
        def commit(self):
            pass

    monkeypatch.setattr(games_router, "_get_record", lambda *args: record)
    monkeypatch.setattr(games_router.state_store, "load_state", lambda *args: None)
    monkeypatch.setattr(games_router.state_store, "save_state", lambda *args: None)
    response = games_router.undo_session("gomoku", games_router.GameIdBody(game_id=999), Database(), SimpleNamespace(id=1))
    assert response.data["state"]["history"] == []
    assert response.data["state"]["current_player"] == "black"


def test_captcha_is_one_time_and_rate_limit_expires_in_local_store():
    store = RedisStateStore()
    store.enabled = False
    store.client = None
    store.save_captcha("test-captcha", "ABCDE")
    assert store.consume_captcha("test-captcha") == "ABCDE"
    assert store.consume_captcha("test-captcha") is None
    assert store.check_rate_limit("test", "127.0.0.1", 1, 60)[0]
    assert not store.check_rate_limit("test", "127.0.0.1", 1, 60)[0]


def test_active_ai_state_is_not_committed_until_the_game_finishes(monkeypatch):
    state = GomokuEngine().new_state()
    record = SimpleNamespace(id=42, moves=None, game_state=None, player1_id=1)
    saved = []

    class Database:
        committed = 0
        def commit(self): self.committed += 1

    db = Database()
    monkeypatch.setattr(games_router.state_store, "save_state", lambda *args: saved.append(args))
    games_router._persist(db, record, state, "black")
    assert db.committed == 0
    assert record.moves is None
    assert saved[0][2] == state
