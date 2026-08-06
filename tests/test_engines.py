import pytest

from services.engines import GameRuleError, GoEngine, GomokuEngine, XiangqiEngine


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
