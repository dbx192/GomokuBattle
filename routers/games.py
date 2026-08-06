"""Clean REST API for standalone multi-game sessions and replays."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.game import GameRecord
from models.user import User
from schemas.common import ResponseModel
from services.engines import GAME_CATALOG, GameRuleError, GoEngine, GomokuEngine, XiangqiEngine, get_engine
from services.game_records import apply_result
from services.ai_adapters import engine_status
from services.state_store import state_store
from utils.auth import get_current_user

router = APIRouter(prefix="/api/games", tags=["游戏"])


class StartBody(BaseModel):
    player_color: str | None = None


class MoveBody(BaseModel):
    game_id: int
    move: dict[str, Any]


class GameIdBody(BaseModel):
    game_id: int


class DeadStonesBody(GameIdBody):
    points: list[list[int]]


COLORS = {
    "gomoku": ("black", "white"), "go": ("black", "white"),
    "xiangqi": ("red", "black"), "chess": ("white", "black"),
}


def _player_color(code: str) -> str:
    return COLORS[code][0]


def _get_record(db: Session, game_id: int, user_id: int) -> GameRecord:
    record = db.query(GameRecord).filter(GameRecord.id == game_id, GameRecord.player1_id == user_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="对局不存在")
    return record


def _persist(db: Session, record: GameRecord, state: dict, player_color: str):
    record.moves = state.get("history", [])
    record.game_state = state
    apply_result(db, record, state, {player_color: record.player1_id})
    db.commit()
    state_store.save_state("session", record.id, state, state_store.AI_TTL_SECONDS)


def _basic_ai_move(engine, state: dict, color: str) -> dict:
    """Deterministic legal fallback; external engine integration can replace this adapter."""
    if isinstance(engine, GomokuEngine):
        from services.game_service import GomokuGame
        game_state = dict(state)
        game_state["current_player"] = GomokuGame.BLACK if state["current_player"] == "black" else GomokuGame.WHITE
        game = GomokuGame.from_dict(game_state)
        row, col = game.get_ai_move()
        return {"row": row, "col": col}
    if isinstance(engine, GoEngine):
        for row, values in enumerate(state["board"]):
            for col, value in enumerate(values):
                if value:
                    continue
                move = {"row": row, "col": col}
                try:
                    engine.apply_move(state, move, color)
                    return move
                except GameRuleError:
                    continue
        return {"pass": True}
    if isinstance(engine, XiangqiEngine):
        moves = engine._legal(state["board"], color)
        if moves:
            fr, fc, tr, tc = moves[0]
            return {"from_row": fr, "from_col": fc, "to_row": tr, "to_col": tc}
    if hasattr(engine, "_chess"):
        chess = engine._chess()
        board = chess.Board(state["fen"])
        move = next(iter(board.legal_moves), None)
        if move:
            return {"uci": move.uci()}
    raise GameRuleError("AI 没有可用着法")


@router.get("", response_model=ResponseModel[list])
def catalog():
    statuses = engine_status()
    return ResponseModel(data=[{"code": code, **item, "ai_engine": statuses.get(code, {"configured": False})} for code, item in GAME_CATALOG.items()])


@router.post("/{game_code}/sessions", response_model=ResponseModel[dict])
def create_session(game_code: str, body: StartBody, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if game_code not in GAME_CATALOG:
        raise HTTPException(status_code=404, detail="不支持的棋种")
    try:
        engine = get_engine(game_code)
        state = engine.new_state()
    except GameRuleError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    player_color = body.player_color or _player_color(game_code)
    if player_color not in COLORS[game_code]:
        raise HTTPException(status_code=400, detail="该棋种不支持此执子方")
    record = GameRecord(
        player1_id=current_user.id,
        game_type="ai",
        game_code=game_code,
        moves=[],
        initial_state=state,
        game_state=state,
        time_control=GAME_CATALOG[game_code]["time_control"],
        status="in_progress",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    state_store.save_state("session", record.id, state, state_store.AI_TTL_SECONDS)
    if state["current_player"] != player_color:
        state = engine.apply_move(state, _basic_ai_move(engine, state, state["current_player"]), state["current_player"])
        _persist(db, record, state, player_color)
    return ResponseModel(data={"game_id": record.id, "player_color": player_color, "state": state, "rules": GAME_CATALOG[game_code]})


@router.post("/{game_code}/sessions/move", response_model=ResponseModel[dict])
def move(game_code: str, body: MoveBody, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    record = _get_record(db, body.game_id, current_user.id)
    if record.game_code != game_code or record.status != "in_progress":
        raise HTTPException(status_code=409, detail="对局已结束或棋种不匹配")
    state = state_store.load_state("session", record.id) or record.game_state
    engine = get_engine(game_code)
    player_color = _player_color(game_code)
    try:
        state = engine.apply_move(state, body.move, player_color)
        if not state.get("result") and state.get("phase", "playing") == "playing":
            ai_color = state["current_player"]
            state = engine.apply_move(state, _basic_ai_move(engine, state, ai_color), ai_color)
    except GameRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _persist(db, record, state, player_color)
    return ResponseModel(data={"state": state})


@router.post("/{game_code}/sessions/pass", response_model=ResponseModel[dict])
def pass_turn(game_code: str, body: GameIdBody, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if game_code != "go":
        raise HTTPException(status_code=404, detail="仅围棋支持停一手")
    record = _get_record(db, body.game_id, current_user.id)
    state = state_store.load_state("session", record.id) or record.game_state
    try:
        state = get_engine("go").apply_move(state, {"pass": True}, "black")
        if state.get("phase") == "playing":
            state = get_engine("go").apply_move(state, {"pass": True}, "white")
    except GameRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _persist(db, record, state, "black")
    return ResponseModel(data={"state": state})


@router.post("/{game_code}/sessions/dead-stones", response_model=ResponseModel[dict])
def dead_stones(game_code: str, body: DeadStonesBody, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if game_code != "go":
        raise HTTPException(status_code=404, detail="仅围棋支持数子")
    record = _get_record(db, body.game_id, current_user.id)
    state = state_store.load_state("session", record.id) or record.game_state
    try:
        state = get_engine("go").mark_dead(state, "black", body.points)
        # A single-player game accepts the same declaration on behalf of the bot.
        state = get_engine("go").mark_dead(state, "white", body.points)
    except GameRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _persist(db, record, state, "black")
    return ResponseModel(data={"state": state})


@router.post("/{game_code}/sessions/resign", response_model=ResponseModel[dict])
def resign(game_code: str, body: GameIdBody, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    record = _get_record(db, body.game_id, current_user.id)
    state = state_store.load_state("session", record.id) or record.game_state
    color = _player_color(game_code)
    opponent = COLORS[game_code][1]
    state["result"] = {"winner": opponent, "reason": "resignation"}
    _persist(db, record, state, color)
    return ResponseModel(data={"state": state})


@router.get("/history", response_model=ResponseModel[list])
def history(game_code: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(GameRecord).filter(GameRecord.player1_id == current_user.id)
    if game_code:
        query = query.filter(GameRecord.game_code == game_code)
    records = query.order_by(GameRecord.created_at.desc()).limit(100).all()
    return ResponseModel(data=[{"id": item.id, "game_code": item.game_code, "status": item.status, "winner_id": item.winner_id, "reason": item.result_reason, "created_at": item.created_at, "ended_at": item.ended_at} for item in records])


@router.get("/replays/{record_id}", response_model=ResponseModel[dict])
def replay(record_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    record = _get_record(db, record_id, current_user.id)
    return ResponseModel(data={"id": record.id, "game_code": record.game_code, "initial_state": record.initial_state, "moves": record.moves, "state": record.game_state})
