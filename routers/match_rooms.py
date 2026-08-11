"""Realtime rooms for every ruleset. State and clocks are server-authoritative."""
import asyncio
import random
import string
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from models.game import GameRecord
from models.game_stats import UserGameStats, UserGameRating
from models.room import Room
from models.user import User
from schemas.common import ResponseModel
from services.engines import GAME_CATALOG, GameRuleError, get_engine
from services.game_records import apply_result
from services.state_store import state_store
from utils.auth import decode_token, get_current_user

router = APIRouter(prefix="/api/match-rooms", tags=["实时房间"])
COLORS = {"gomoku": ("black", "white"), "go": ("black", "white"), "xiangqi": ("red", "black"), "chess": ("white", "black")}
connections: dict[int, set[WebSocket]] = {}
timeout_tasks: dict[int, asyncio.Task] = {}


class RoomCreate(BaseModel):
    game_code: str


def _code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def _state(room: Room, record: GameRecord):
    return state_store.load_state("match", room.id) or record.game_state


def _clock_state(code: str):
    tc = GAME_CATALOG[code]["time_control"]
    if tc["mode"] == "per_move":
        return {"mode": "per_move", "seconds": tc["seconds"], "deadline": time.time() + tc["seconds"]}
    first, second = COLORS[code]
    return {"mode": "fischer", first: tc["initial_seconds"], second: tc["initial_seconds"], "increment_seconds": tc["increment_seconds"], "started_at": time.time()}


def _serialize(room, record, state):
    return {"room_id": room.id, "room_code": room.room_code, "status": room.status, "game_code": room.game_code, "state": state, "clocks": state.get("_clocks", record.clocks), "time_control": room.time_control, "host_id": room.host_id, "host_name": room.host.username if room.host else None, "guest_id": room.guest_id, "guest_name": room.guest.username if room.guest else None}


async def _broadcast(room_id: int, payload: dict):
    stale = []
    for ws in connections.get(room_id, set()).copy():
        try: await ws.send_json(payload)
        except Exception: stale.append(ws)
    for ws in stale: connections.get(room_id, set()).discard(ws)


def _persist(db, room, record, state):
    state_store.save_state("match", room.id, state, state_store.ROOM_TTL_SECONDS)
    if not state.get("result"):
        return
    record.moves = state.get("history", [])
    record.game_state = state
    record.clocks = state.get("_clocks", record.clocks)
    players = {COLORS[room.game_code][0]: room.host_id, COLORS[room.game_code][1]: room.guest_id}
    apply_result(db, record, state, players)
    room.status = "completed"
    db.commit()


def _reset_turn_clock(state: dict, record: GameRecord) -> None:
    clocks = dict(state.get("_clocks") or record.clocks or {})
    if clocks.get("mode") == "per_move":
        clocks["deadline"] = time.time() + clocks["seconds"]
        state["_clocks"] = clocks


def _ensure_per_move_clock(state: dict, record: GameRecord, game_code: str) -> dict:
    clocks = dict(state.get("_clocks") or record.clocks or {})
    if clocks.get("mode") == "per_move" and clocks.get("deadline"):
        return clocks
    clocks = _clock_state(game_code)
    state["_clocks"] = clocks
    record.clocks = clocks
    return clocks


def _reopen_after_undo(db: Session, room: Room, record: GameRecord) -> None:
    if record.status != "completed":
        return
    if record.winner_id:
        stats = db.query(UserGameStats).filter_by(user_id=record.winner_id, game_code=record.game_code).first()
        if stats:
            stats.wins = max(0, (stats.wins or 0) - 1)
    loser_id = room.guest_id if record.winner_id == room.host_id else room.host_id
    if loser_id:
        stats = db.query(UserGameStats).filter_by(user_id=loser_id, game_code=record.game_code).first()
        if stats:
            stats.losses = max(0, (stats.losses or 0) - 1)
    result = (record.game_state or {}).get("result", {})
    if record.winner_id and result.get("rating_delta") is not None:
        winner_rating = db.query(UserGameRating).filter_by(
            user_id=record.winner_id, game_code=record.game_code
        ).first()
        loser_rating = db.query(UserGameRating).filter_by(
            user_id=loser_id, game_code=record.game_code
        ).first()
        delta = int(result["rating_delta"])
        if winner_rating:
            winner_rating.rating -= delta
            winner_rating.wins = max(0, winner_rating.wins - 1)
        if loser_rating:
            loser_rating.rating += delta
            loser_rating.losses = max(0, loser_rating.losses - 1)
    elif record.winner_id is None and record.game_state:
        for user_id in (room.host_id, room.guest_id):
            rating = db.query(UserGameRating).filter_by(
                user_id=user_id, game_code=record.game_code
            ).first()
            if rating:
                rating.draws = max(0, rating.draws - 1)
    record.status = "in_progress"
    record.winner_id = None
    record.result_reason = None
    record.ended_at = None
    room.status = "playing"


async def _timeout_room(room_id: int) -> None:
    try:
        while True:
            db = SessionLocal()
            try:
                room = db.query(Room).filter_by(id=room_id).first()
                if not room or room.status != "playing":
                    return
                record = db.query(GameRecord).filter_by(id=room.game_record_id).first()
                state = _state(room, record)
                clocks = _ensure_per_move_clock(state, record, room.game_code)
                state_store.save_state("match", room.id, state, state_store.ROOM_TTL_SECONDS)
                db.commit()
                remaining = clocks.get("deadline", 0) - time.time()
                if remaining > 0:
                    pass
                else:
                    timed_out = state["current_player"]
                    first, second = COLORS[room.game_code]
                    state["result"] = {"winner": second if timed_out == first else first, "reason": "timeout"}
                    _persist(db, room, record, state)
                    await _broadcast(room_id, {"type": "state", **_serialize(room, record, state)})
                    return
            finally:
                db.close()
            await asyncio.sleep(max(0.05, remaining))
    finally:
        if timeout_tasks.get(room_id) is asyncio.current_task():
            timeout_tasks.pop(room_id, None)


def _schedule_timeout(room_id: int) -> None:
    task = timeout_tasks.pop(room_id, None)
    if task:
        task.cancel()
    timeout_tasks[room_id] = asyncio.create_task(_timeout_room(room_id))


def _consume_clock(record, state, game_code: str):
    clocks = _ensure_per_move_clock(state, record, game_code)
    return state["current_player"] if time.time() >= clocks["deadline"] else None


@router.post("", response_model=ResponseModel[dict])
def create_room(body: RoomCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if body.game_code not in GAME_CATALOG: raise HTTPException(status_code=400, detail="不支持的棋种")
    try: state = get_engine(body.game_code).new_state()
    except GameRuleError as exc: raise HTTPException(status_code=503, detail=str(exc))
    room_code = _code()
    while db.query(Room).filter_by(room_code=room_code).first(): room_code = _code()
    record = GameRecord(player1_id=current_user.id, game_type="room", game_code=body.game_code, moves=[], initial_state=state, game_state=state, time_control=GAME_CATALOG[body.game_code]["time_control"])
    db.add(record); db.flush()
    room = Room(room_code=room_code, host_id=current_user.id, game_record_id=record.id, status="waiting", game_code=body.game_code, time_control=GAME_CATALOG[body.game_code]["time_control"])
    db.add(room); db.commit(); db.refresh(room)
    state_store.save_state("match", room.id, state, state_store.ROOM_TTL_SECONDS)
    return ResponseModel(data=_serialize(room, record, state))


@router.get("/history", response_model=ResponseModel[list])
def history(db: Session = Depends(get_db), limit: int = 50):
    """Public lobby history; ultra-short wins are omitted."""
    rows = (
        db.query(Room, GameRecord)
        .join(GameRecord, GameRecord.id == Room.game_record_id)
        .filter(Room.status == "completed")
        .order_by(Room.created_at.desc())
        .limit(200)
        .all()
    )
    result = []
    for room, record in rows:
        if len(record.moves or []) <= 3:
            continue
        result.append({
            "room_id": room.id,
            "room_code": room.room_code,
            "status": room.status,
            "game_code": room.game_code,
            "host_id": room.host_id,
            "host_name": room.host.username if room.host else None,
            "guest_id": room.guest_id,
            "guest_name": room.guest.username if room.guest else None,
            "winner_id": record.winner_id,
            "move_count": len(record.moves or []),
            "created_at": room.created_at,
            "ended_at": record.ended_at,
        })
        if len(result) >= min(max(limit, 1), 100):
            break
    return ResponseModel(data=result)


@router.get("/playing", response_model=ResponseModel[list])
def playing_rooms(db: Session = Depends(get_db), limit: int = 50):
    """Public list of active rooms available for spectating."""
    rooms = (
        db.query(Room)
        .filter(Room.status == "playing", Room.guest_id.isnot(None))
        .order_by(Room.created_at.desc())
        .limit(min(max(limit, 1), 100))
        .all()
    )
    return ResponseModel(data=[{
        "room_id": room.id,
        "room_code": room.room_code,
        "game_code": room.game_code,
        "host_name": room.host.username if room.host else None,
        "guest_name": room.guest.username if room.guest else None,
        "created_at": room.created_at,
    } for room in rooms])


@router.post("/{room_code}/join", response_model=ResponseModel[dict])
def join_room(room_code: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    room = db.query(Room).filter_by(room_code=room_code.upper()).first()
    if not room or room.status not in {"waiting", "playing"}: raise HTTPException(status_code=404, detail="房间不可用")
    record = db.query(GameRecord).filter_by(id=room.game_record_id).first()
    if room.host_id == current_user.id or room.guest_id == current_user.id:
        return ResponseModel(data=_serialize(room, record, _state(room, record)))
    if room.status != "waiting": raise HTTPException(status_code=409, detail="房间已满")
    room.guest_id = current_user.id; room.status = "playing"; record.player2_id = current_user.id; record.clocks = _clock_state(room.game_code)
    db.commit()
    return ResponseModel(data=_serialize(room, record, _state(room, record)))


@router.get("/{room_code}/watch", response_model=ResponseModel[dict])
def watch_room(room_code: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    room = db.query(Room).filter_by(room_code=room_code.upper()).first()
    if not room or room.status != "playing":
        raise HTTPException(status_code=404, detail="房间不可观看")
    return ResponseModel(data={"room_id": room.id, "room_code": room.room_code, "status": room.status, "game_code": room.game_code, "host_id": room.host_id, "host_name": room.host.username if room.host else None, "guest_id": room.guest_id, "guest_name": room.guest.username if room.guest else None, "role": "observer"})


@router.websocket("/{room_id}/ws")
async def ws_room(websocket: WebSocket, room_id: int, token: str = ""):
    payload = decode_token(token)
    if not payload: await websocket.close(code=4001); return
    user_id = int(payload["sub"])
    try:
        db = SessionLocal()
        try:
            room = db.query(Room).filter_by(id=room_id).first()
            if not room or (room.status != "playing" and user_id not in {room.host_id, room.guest_id}):
                await websocket.close(code=4003)
                return
            record = db.query(GameRecord).filter_by(id=room.game_record_id).first()
            observer = user_id not in {room.host_id, room.guest_id}
            color = None if observer else COLORS[room.game_code][0] if user_id == room.host_id else COLORS[room.game_code][1]
            state = _state(room, record)
            if room.status == "playing":
                _ensure_per_move_clock(state, record, room.game_code)
                state_store.save_state("match", room.id, state, state_store.ROOM_TTL_SECONDS)
                db.commit()
            initial_payload = _serialize(room, record, state)
        finally:
            db.close()
        await websocket.accept(); connections.setdefault(room_id, set()).add(websocket)
        await websocket.send_json({"type": "role", "role": "observer" if observer else "player", "color": color, **initial_payload})
        # A guest connection is the first event the host can observe after the
        # room leaves the waiting state, so synchronize both browsers now.
        if initial_payload["status"] == "playing":
            _schedule_timeout(room_id)
            await _broadcast(room_id, {"type": "state", **initial_payload})
        while True:
            message = await websocket.receive_json(); action = message.get("type")
            if action == "ping": await websocket.send_json({"type": "pong"}); continue
            if observer:
                await websocket.send_json({"type": "read_only"})
                continue
            db = SessionLocal()
            try:
                room = db.query(Room).filter_by(id=room_id).first()
                record = db.query(GameRecord).filter_by(id=room.game_record_id).first()
                state = _state(room, record)
                if room.status != "playing" and action not in {"undo", "undo_accept", "undo_decline"}: continue
                if action == "resign":
                    other = COLORS[room.game_code][1] if color == COLORS[room.game_code][0] else COLORS[room.game_code][0]
                    state["result"] = {"winner": other, "reason": "resignation"}
                elif action == "move":
                    timed_out = _consume_clock(record, state, room.game_code)
                    if timed_out:
                        other = COLORS[room.game_code][1] if timed_out == COLORS[room.game_code][0] else COLORS[room.game_code][0]
                        state["result"] = {"winner": other, "reason": "timeout"}
                    else:
                        try: state = get_engine(room.game_code).apply_move(state, message.get("move", {}), color)
                        except GameRuleError as exc: await websocket.send_json({"type": "error", "message": str(exc)}); continue
                elif action == "pass" and room.game_code == "go":
                    timed_out = _consume_clock(record, state, room.game_code)
                    if timed_out:
                        other = COLORS[room.game_code][1] if timed_out == COLORS[room.game_code][0] else COLORS[room.game_code][0]
                        state["result"] = {"winner": other, "reason": "timeout"}
                    else:
                        try: state = get_engine("go").apply_move(state, {"pass": True}, color)
                        except GameRuleError as exc: await websocket.send_json({"type": "error", "message": str(exc)}); continue
                elif action == "dead_stones" and room.game_code == "go":
                    try: state = get_engine("go").mark_dead(state, color, message.get("points", []))
                    except GameRuleError as exc: await websocket.send_json({"type": "error", "message": str(exc)}); continue
                elif action == "undo":
                    if state.get("phase") == "scoring" or not state.get("history"):
                        await websocket.send_json({"type": "error", "message": "当前不能悔棋"}); continue
                    if not state_store.create_pending_undo(room.id, user_id):
                        await websocket.send_json({"type": "error", "message": "已有悔棋请求"}); continue
                    await _broadcast(room.id, {"type": "undo_request", "from": color, "timeout_sec": 30}); continue
                elif action == "undo_accept":
                    pending = state_store.get_pending_undo(room.id)
                    if not pending or pending.get("requester_id") == user_id: continue
                    try: state = get_engine(room.game_code).undo(state)
                    except GameRuleError as exc: await websocket.send_json({"type": "error", "message": str(exc)}); continue
                    state_store.clear_pending_undo(room.id)
                    _reopen_after_undo(db, room, record)
                    await _broadcast(room.id, {"type": "undo_accepted"})
                elif action == "undo_decline":
                    if state_store.get_pending_undo(room.id):
                        state_store.clear_pending_undo(room.id)
                        await _broadcast(room.id, {"type": "undo_declined"})
                    continue
                else: continue
                if not state.get("result"):
                    _reset_turn_clock(state, record)
                _persist(db, room, record, state)
                if not state.get("result"):
                    db.commit()
                await _broadcast(room_id, {"type": "state", **_serialize(room, record, state)})
                if room.status == "playing": _schedule_timeout(room.id)
            finally:
                db.close()
    except WebSocketDisconnect: pass
    finally:
        connections.get(room_id, set()).discard(websocket)
