"""Clean REST API for standalone multi-game sessions and replays."""
from copy import deepcopy
from datetime import timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from models.game import GameRecord
from models.game_stats import UserGameStats
from models.user import User
from schemas.common import ResponseModel
from services.engines import GAME_CATALOG, GameRuleError, get_engine
from services.game_records import apply_result
from services.external_ai import AIEngineError, DIFFICULTIES, choose_move as choose_external_move, engine_status, require_engine
from services.state_store import state_store
from utils.auth import get_current_user

router = APIRouter(prefix="/api/games", tags=["游戏"])


class StartBody(BaseModel):
    player_color: str | None = None
    difficulty: str = "normal"


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
    record = db.query(GameRecord).filter(
        GameRecord.id == game_id,
        or_(GameRecord.player1_id == user_id, GameRecord.player2_id == user_id),
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="对局不存在")
    return record


def _persist(db: Session, record: GameRecord, state: dict, player_color: str):
    record.moves = state.get("history", [])
    record.game_state = state
    apply_result(db, record, state, {player_color: record.player1_id})
    db.commit()
    state_store.save_state("session", record.id, state, state_store.AI_TTL_SECONDS)


def _reopen_record(db: Session, record: GameRecord, previous_state: dict) -> None:
    """Reverse terminal AI-game accounting before persisting an undone state."""
    if record.status != "completed":
        return
    stats = db.query(UserGameStats).filter_by(user_id=record.player1_id, game_code=record.game_code).first()
    if stats:
        winner = previous_state.get("result", {}).get("winner")
        if winner == _player_color(record.game_code):
            stats.wins = max(0, (stats.wins or 0) - 1)
        elif winner is None:
            stats.draws = max(0, (stats.draws or 0) - 1)
        else:
            stats.losses = max(0, (stats.losses or 0) - 1)
    record.status = "in_progress"
    record.winner_id = None
    record.result_reason = None
    record.ended_at = None


def _ai_move(game_code: str, engine, state: dict, difficulty: str) -> dict:
    try:
        move = choose_external_move(game_code, state, difficulty)
        # External engines propose moves; the server rules engine remains final authority.
        try:
            # Some engines (notably GomokuGame) mutate the board they receive.
            # Validate against an isolated state so the actual move is applied once.
            engine.apply_move(deepcopy(state), move, state["current_player"])
        except GameRuleError as exc:
            raise AIEngineError(f"{game_code} 引擎返回了非法着法") from exc
        return move
    except AIEngineError as exc:
        raise GameRuleError(str(exc)) from exc


def _complete_ai_turn(game_code: str, game_id: int, player_color: str) -> None:
    """Compute an AI move after the player's state is already visible to them."""
    db = SessionLocal()
    try:
        record = db.get(GameRecord, game_id)
        if not record or record.status != "in_progress" or record.game_code != game_code:
            return
        state = state_store.load_state("session", record.id) or record.game_state
        if not state or state.get("result") or state.get("phase", "playing") != "playing":
            return
        ai_color = state.get("current_player")
        if ai_color == player_color:
            return
        try:
            engine = get_engine(game_code)
            move = _ai_move(game_code, engine, state, state.get("ai_difficulty", "normal"))
            state = engine.apply_move(state, move, ai_color)
        except GameRuleError as exc:
            # Preserve the player's move and expose a useful error instead of
            # reverting the board or leaving the browser waiting indefinitely.
            state["ai_error"] = str(exc)
        _persist(db, record, state, player_color)
    finally:
        db.close()


@router.get("", response_model=ResponseModel[list])
def catalog():
    statuses = engine_status()
    return ResponseModel(data=[{"code": code, **item, "ai_engine": statuses.get(code, {"configured": False}), "difficulties": DIFFICULTIES} for code, item in GAME_CATALOG.items()])


@router.post("/{game_code}/sessions", response_model=ResponseModel[dict])
def create_session(game_code: str, body: StartBody, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if game_code not in GAME_CATALOG:
        raise HTTPException(status_code=404, detail="不支持的棋种")
    if body.difficulty not in DIFFICULTIES:
        raise HTTPException(status_code=400, detail="不支持的 AI 难度")
    try:
        require_engine(game_code)
    except AIEngineError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        engine = get_engine(game_code)
        state = engine.new_state()
    except GameRuleError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    player_color = body.player_color or _player_color(game_code)
    state["ai_difficulty"] = body.difficulty
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
        state = engine.apply_move(state, _ai_move(game_code, engine, state, body.difficulty), state["current_player"])
        _persist(db, record, state, player_color)
    return ResponseModel(data={"game_id": record.id, "player_color": player_color, "state": state, "rules": GAME_CATALOG[game_code]})


@router.post("/{game_code}/sessions/move", response_model=ResponseModel[dict])
def move(game_code: str, body: MoveBody, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    record = _get_record(db, body.game_id, current_user.id)
    if record.game_code != game_code or record.status != "in_progress":
        raise HTTPException(status_code=409, detail="对局已结束或棋种不匹配")
    state = state_store.load_state("session", record.id) or record.game_state
    engine = get_engine(game_code)
    player_color = _player_color(game_code)
    try:
        state = engine.apply_move(state, body.move, player_color)
    except GameRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _persist(db, record, state, player_color)
    if not state.get("result") and state.get("phase", "playing") == "playing":
        background_tasks.add_task(_complete_ai_turn, game_code, record.id, player_color)
    return ResponseModel(data={"state": state})


@router.post("/{game_code}/sessions/undo", response_model=ResponseModel[dict])
def undo_session(game_code: str, body: GameIdBody, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Undo the latest player/AI exchange and return control to the player."""
    record = _get_record(db, body.game_id, current_user.id)
    if record.game_code != game_code or record.game_type != "ai":
        raise HTTPException(status_code=409, detail="只能悔人机对局")
    previous_state = state_store.load_state("session", record.id) or record.game_state
    if not previous_state or len(previous_state.get("history", [])) < 2:
        raise HTTPException(status_code=400, detail="至少完成一轮后才能悔棋")
    try:
        engine = get_engine(game_code)
        state = engine.undo(engine.undo(previous_state))
    except GameRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _reopen_record(db, record, previous_state)
    _persist(db, record, state, _player_color(game_code))
    return ResponseModel(data={"state": state})


@router.get("/{game_code}/sessions/{game_id}", response_model=ResponseModel[dict])
def session_state(game_code: str, game_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    record = _get_record(db, game_id, current_user.id)
    if record.game_code != game_code:
        raise HTTPException(status_code=404, detail="对局不存在")
    return ResponseModel(data={"state": state_store.load_state("session", record.id) or record.game_state})


@router.post("/{game_code}/sessions/pass", response_model=ResponseModel[dict])
def pass_turn(game_code: str, body: GameIdBody, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if game_code != "go":
        raise HTTPException(status_code=404, detail="仅围棋支持停一手")
    record = _get_record(db, body.game_id, current_user.id)
    state = state_store.load_state("session", record.id) or record.game_state
    try:
        state = get_engine("go").apply_move(state, {"pass": True}, "black")
    except GameRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _persist(db, record, state, "black")
    if state.get("phase") == "playing" and not state.get("result"):
        background_tasks.add_task(_complete_ai_turn, "go", record.id, "black")
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
    query = db.query(GameRecord).filter(
        or_(GameRecord.player1_id == current_user.id, GameRecord.player2_id == current_user.id),
        GameRecord.status == "completed",
    )
    if game_code:
        query = query.filter(GameRecord.game_code == game_code)
    records = query.order_by(GameRecord.created_at.desc()).limit(100).all()
    def serialize(item: GameRecord) -> dict:
        opponent = "AI" if item.game_type == "ai" else (
            item.player2.username if item.player1_id == current_user.id and item.player2 else
            item.player1.username if item.player1 else "未知对手"
        )
        started, ended = item.created_at, item.ended_at
        if started and ended:
            if started.tzinfo is None and ended.tzinfo is not None:
                ended = ended.astimezone(timezone.utc).replace(tzinfo=None)
            elif started.tzinfo is not None and ended.tzinfo is None:
                started = started.astimezone(timezone.utc).replace(tzinfo=None)
            duration_seconds = max(0, int((ended - started).total_seconds()))
        else:
            duration_seconds = None
        if item.game_type == "ai":
            winner_color = (item.game_state or {}).get("result", {}).get("winner")
            outcome = "draw" if winner_color is None else (
                "win" if winner_color == _player_color(item.game_code) else "loss"
            )
        else:
            outcome = "draw" if item.winner_id is None else "win" if item.winner_id == current_user.id else "loss"
        return {
            "id": item.id, "game_code": item.game_code, "game_type": item.game_type,
            "opponent": opponent, "outcome": outcome, "reason": item.result_reason,
            "duration_seconds": duration_seconds, "created_at": item.created_at,
            "ended_at": item.ended_at,
        }
    return ResponseModel(data=[serialize(item) for item in records])


@router.get("/replays/{record_id}", response_model=ResponseModel[dict])
def replay(record_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    record = _get_record(db, record_id, current_user.id)
    if record.status != "completed":
        raise HTTPException(status_code=409, detail="对局尚未结束")
    return ResponseModel(data={"id": record.id, "game_code": record.game_code, "initial_state": record.initial_state, "moves": record.moves, "state": record.game_state})
