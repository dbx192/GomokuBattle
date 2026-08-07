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


class RoomCreate(BaseModel):
    game_code: str


def _code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def _state(room: Room, record: GameRecord):
    return state_store.load_state("match", room.id) or record.game_state


def _clock_state(code: str):
    tc = GAME_CATALOG[code]["time_control"]
    if tc["mode"] == "per_move":
        return {"mode": "per_move", "seconds": tc["seconds"]}
    first, second = COLORS[code]
    return {"mode": "fischer", first: tc["initial_seconds"], second: tc["initial_seconds"], "increment_seconds": tc["increment_seconds"], "started_at": time.time()}


def _serialize(room, record, state):
    return {"room_id": room.id, "room_code": room.room_code, "status": room.status, "game_code": room.game_code, "state": state, "clocks": record.clocks, "time_control": room.time_control, "host_id": room.host_id, "guest_id": room.guest_id}


async def _broadcast(room_id: int, payload: dict):
    stale = []
    for ws in connections.get(room_id, set()).copy():
        try: await ws.send_json(payload)
        except Exception: stale.append(ws)
    for ws in stale: connections.get(room_id, set()).discard(ws)


def _persist(db, room, record, state):
    record.moves = state.get("history", [])
    record.game_state = state
    players = {COLORS[room.game_code][0]: room.host_id, COLORS[room.game_code][1]: room.guest_id}
    apply_result(db, record, state, players)
    if state.get("result"):
        room.status = "completed"
    db.commit()
    state_store.save_state("match", room.id, state, state_store.ROOM_TTL_SECONDS)


def _consume_clock(record, state):
    clocks = record.clocks or {}
    if clocks.get("mode") != "fischer": return None
    player = state["current_player"]
    elapsed = max(0, time.time() - clocks.get("started_at", time.time()))
    clocks[player] = max(0, clocks[player] - elapsed)
    if clocks[player] <= 0:
        return player
    clocks[player] += clocks["increment_seconds"]
    clocks["started_at"] = time.time()
    record.clocks = clocks
    return None


@router.get("", response_model=ResponseModel[list])
def list_rooms(db: Session = Depends(get_db)):
    rooms = db.query(Room).filter(Room.status.in_(["waiting", "playing"])).order_by(Room.created_at.desc()).all()
    return ResponseModel(data=[{"room_code": r.room_code, "game_code": r.game_code, "status": r.status, "host": r.host.username if r.host else None, "time_control": r.time_control} for r in rooms])


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


@router.websocket("/{room_id}/ws")
async def ws_room(websocket: WebSocket, room_id: int, token: str = ""):
    payload = decode_token(token)
    if not payload: await websocket.close(code=4001); return
    user_id = int(payload["sub"]); db = SessionLocal()
    try:
        room = db.query(Room).filter_by(id=room_id).first()
        if not room or user_id not in {room.host_id, room.guest_id}: await websocket.close(code=4003); return
        record = db.query(GameRecord).filter_by(id=room.game_record_id).first()
        await websocket.accept(); connections.setdefault(room_id, set()).add(websocket)
        color = COLORS[room.game_code][0] if user_id == room.host_id else COLORS[room.game_code][1]
        await websocket.send_json({"type": "role", "color": color, **_serialize(room, record, _state(room, record))})
        # A guest connection is the first event the host can observe after the
        # room leaves the waiting state, so synchronize both browsers now.
        if room.status == "playing":
            await _broadcast(room_id, {"type": "state", **_serialize(room, record, _state(room, record))})
        while True:
            message = await websocket.receive_json(); action = message.get("type")
            # This is a long-lived session.  The guest joins through a separate
            # database session, so expire cached rows before checking its status.
            db.expire_all()
            room = db.query(Room).filter_by(id=room_id).first(); record = db.query(GameRecord).filter_by(id=room.game_record_id).first(); state = _state(room, record)
            if action == "ping": await websocket.send_json({"type": "pong"}); continue
            if room.status != "playing": continue
            if action == "resign":
                other = COLORS[room.game_code][1] if color == COLORS[room.game_code][0] else COLORS[room.game_code][0]
                state["result"] = {"winner": other, "reason": "resignation"}
            elif action == "move":
                timed_out = _consume_clock(record, state)
                if timed_out:
                    other = COLORS[room.game_code][1] if timed_out == COLORS[room.game_code][0] else COLORS[room.game_code][0]
                    state["result"] = {"winner": other, "reason": "timeout"}
                else:
                    try: state = get_engine(room.game_code).apply_move(state, message.get("move", {}), color)
                    except GameRuleError as exc: await websocket.send_json({"type": "error", "message": str(exc)}); continue
            elif action == "pass" and room.game_code == "go":
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
                if not pending or pending.get("requester_id") == user_id:
                    continue
                try: state = get_engine(room.game_code).undo(state)
                except GameRuleError as exc: await websocket.send_json({"type": "error", "message": str(exc)}); continue
                state_store.clear_pending_undo(room.id)
                await _broadcast(room.id, {"type": "undo_accepted"})
            elif action == "undo_decline":
                if state_store.get_pending_undo(room.id):
                    state_store.clear_pending_undo(room.id)
                    await _broadcast(room.id, {"type": "undo_declined"})
                continue
            else: continue
            _persist(db, room, record, state)
            await _broadcast(room_id, {"type": "state", **_serialize(room, record, state)})
    except WebSocketDisconnect: pass
    finally:
        connections.get(room_id, set()).discard(websocket); db.close()
