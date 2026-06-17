from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from typing import Dict, List, Optional, Tuple
from database import get_db, SessionLocal
from models.user import User
from models.room import Room
from models.game import GameRecord
from utils.auth import decode_token, get_current_user
from schemas.common import ResponseModel
from services.game_service import GomokuGame
from services.state_store import state_store
import asyncio
import json
import random
import string
import time
from datetime import datetime, timedelta, timezone

router = APIRouter(prefix="/api/room", tags=["房间"])


class RoomConnectionManager:
    """房间连接管理器：精确追踪 host / guest 的连接"""

    def __init__(self):
        self.host_conns: Dict[int, WebSocket] = {}
        self.guest_conns: Dict[int, WebSocket] = {}
        self.main_loop = None  # 启动时由 set_main_loop 注入
        # 单次悔棋请求的有效秒数
        self.UNDO_REQUEST_TIMEOUT = 30

    def set_main_loop(self, loop):
        self.main_loop = loop

    def attach(self, room_id: int, user_id: int, ws: WebSocket) -> str:
        """根据 user_id 归类到 host 或 guest 连接。返回角色 'host' | 'guest'"""
        role = "observer"
        if user_id is None:
            return role

        db = SessionLocal()
        try:
            room = db.query(Room).filter(Room.id == room_id).first()
            if not room:
                return role

            if room.host_id == user_id:
                self.host_conns[room_id] = ws
                role = "host"
            elif room.guest_id == user_id:
                self.guest_conns[room_id] = ws
                role = "guest"
            return role
        finally:
            db.close()

    def detach(self, room_id: int, ws: WebSocket):
        if self.host_conns.get(room_id) is ws:
            del self.host_conns[room_id]
        if self.guest_conns.get(room_id) is ws:
            del self.guest_conns[room_id]

    def both_connected(self, room_id: int) -> bool:
        return room_id in self.host_conns and room_id in self.guest_conns

    def guest_conn(self, room_id: int) -> Optional[WebSocket]:
        return self.guest_conns.get(room_id)

    def host_conn(self, room_id: int) -> Optional[WebSocket]:
        return self.host_conns.get(room_id)

    def all_conns(self, room_id: int) -> List[WebSocket]:
        conns = []
        if self.host_conns.get(room_id):
            conns.append(self.host_conns[room_id])
        if self.guest_conns.get(room_id):
            conns.append(self.guest_conns[room_id])
        return conns

    def drop_game(self, room_id: int):
        state_store.delete_game("room", room_id)

    def clear_pending_undo(self, room_id: int):
        state_store.clear_pending_undo(room_id)

    async def _undo_timeout(self, room_id: int, requester_id: int):
        """30s 后还没收到对方的回应 → 自动撤回请求并通知请求方"""
        try:
            await asyncio.sleep(self.UNDO_REQUEST_TIMEOUT)
        except asyncio.CancelledError:
            return
        # 期间已被处理则跳过
        pending = state_store.get_pending_undo(room_id)
        if not pending or pending.get("requester_id") != requester_id:
            return
        self.clear_pending_undo(room_id)
        # 找到请求方的连接推送超时消息
        room = None
        # 通过角色反推连接
        # requester_id 是 host 还是 guest 取决于谁连的房间，这里用 all_conns 都查一遍
        for conn in self.all_conns(room_id):
            try:
                await conn.send_json(
                    {
                        "type": "undo_timeout",
                        "message": "对方未响应，悔棋请求已超时",
                    }
                )
            except Exception:
                pass

    def start_undo_request(
        self, room_id: int, requester_id: int
    ) -> Optional[asyncio.Task]:
        if not state_store.create_pending_undo(room_id, requester_id):
            return None
        if self.main_loop is None:
            return None
        task = self.main_loop.create_task(self._undo_timeout(room_id, requester_id))
        return task

    def push_to_host(self, room_id: int, payload: dict):
        """从同步上下文（HTTP 端点所在线程池）安全推送消息到 host 的 WebSocket"""
        host_c = self.host_conns.get(room_id)
        if host_c is None:
            return False
        if self.main_loop is None:
            return False
        try:
            import asyncio

            asyncio.run_coroutine_threadsafe(host_c.send_json(payload), self.main_loop)
            return True
        except Exception:
            return False


manager = RoomConnectionManager()


def generate_room_code() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def load_room_game(room_id: int) -> Optional[GomokuGame]:
    return state_store.load_game("room", room_id)


def save_room_game(room_id: int, game: GomokuGame):
    state_store.save_game("room", room_id, game, state_store.ROOM_TTL_SECONDS)


def _serialize_room(room: Room, host_name: str = None, guest_name: str = None) -> dict:
    return {
        "id": room.id,
        "room_code": room.room_code,
        "host_id": room.host_id,
        "host_name": host_name or (room.host.username if room.host else None),
        "guest_id": room.guest_id,
        "guest_name": guest_name or (room.guest.username if room.guest else None),
        "status": room.status,
        "created_at": room.created_at.isoformat() if room.created_at else None,
        "game_record_id": room.game_record_id,
    }


@router.get("/list", response_model=ResponseModel[List[dict]])
def get_room_list(db: Session = Depends(get_db)):
    """等待中的房间列表"""
    rooms = (
        db.query(Room)
        .filter(Room.status == "waiting")
        .order_by(Room.created_at.desc())
        .all()
    )
    room_list = [_serialize_room(r) for r in rooms]
    return ResponseModel(data=room_list)


@router.get("/history", response_model=ResponseModel[List[dict]])
def get_room_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """当前用户参与过的历史房间（含 playing / completed / expired）"""
    rooms = (
        db.query(Room)
        .filter(
            (Room.host_id == current_user.id) | (Room.guest_id == current_user.id),
            Room.status != "waiting",
        )
        .order_by(Room.created_at.desc())
        .limit(50)
        .all()
    )
    return ResponseModel(data=[_serialize_room(r) for r in rooms])


@router.get("/current", response_model=ResponseModel[Optional[dict]])
def get_current_room(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    waiting_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)
    room = (
        db.query(Room)
        .filter(
            (Room.host_id == current_user.id) | (Room.guest_id == current_user.id),
            (
                (Room.status == "playing")
                | ((Room.status == "waiting") & (Room.created_at >= waiting_threshold))
            ),
        )
        .order_by(Room.created_at.desc())
        .first()
    )

    if not room:
        return ResponseModel(data=None)

    return ResponseModel(
        data={
            "room_id": room.id,
            "room_code": room.room_code,
            "player_color": "black" if room.host_id == current_user.id else "white",
            "status": room.status,
            "is_host": room.host_id == current_user.id,
            "expires_at": (
                (room.created_at.timestamp() + 300) * 1000
                if room.status == "waiting"
                else None
            ),
        }
    )


@router.post("/create", response_model=ResponseModel[dict])
def create_room(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    room_code = generate_room_code()
    while db.query(Room).filter(Room.room_code == room_code).first():
        room_code = generate_room_code()

    room = Room(room_code=room_code, host_id=current_user.id, status="waiting")
    db.add(room)
    db.commit()
    db.refresh(room)

    return ResponseModel(
        message="房间创建成功",
        data={
            "id": room.id,
            "room_code": room.room_code,
            "expires_at": (room.created_at.timestamp() + 300) * 1000,
        },
    )


@router.post("/join/{room_code}", response_model=ResponseModel[dict])
def join_room(
    room_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    room = db.query(Room).filter(Room.room_code == room_code).first()
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")

    if room.status == "expired":
        raise HTTPException(status_code=410, detail="房间已过期")
    if room.status == "completed":
        raise HTTPException(status_code=410, detail="对局已结束")

    if room.host_id == current_user.id:
        return ResponseModel(
            message="已返回房间",
            data={
                "room_id": room.id,
                "game_id": room.game_record_id,
                "player_color": "black",
                "room_code": room.room_code,
                "status": room.status,
                "expires_at": (
                    (room.created_at.timestamp() + 300) * 1000
                    if room.status == "waiting"
                    else None
                ),
            },
        )

    if room.guest_id == current_user.id:
        return ResponseModel(
            message="已加入房间",
            data={
                "room_id": room.id,
                "game_id": room.game_record_id,
                "player_color": "white",
                "room_code": room.room_code,
                "status": room.status,
            },
        )

    if room.status == "playing":
        raise HTTPException(status_code=409, detail="房间已开始，请等待本局结束")

    if room.status != "waiting":
        raise HTTPException(status_code=404, detail="房间不存在或已开始")

    room.guest_id = current_user.id
    room.status = "playing"

    game_record = GameRecord(
        player1_id=room.host_id,
        player2_id=current_user.id,
        game_type="room",
        moves=[],
        status="in_progress",
    )
    db.add(game_record)
    db.flush()
    room.game_record_id = game_record.id
    db.commit()
    db.refresh(room)

    game = GomokuGame()
    save_room_game(room.id, game)

    # 立即推送 opponent_joined + 最新 game_state 给 host 的 WebSocket
    game_dict = game.to_dict()
    manager.push_to_host(
        room.id,
        {"type": "opponent_joined", "guest_id": current_user.id},
    )
    manager.push_to_host(
        room.id,
        {
            "type": "game_state",
            "game": game_dict,
            "status": "playing",
        },
    )

    return ResponseModel(
        message="加入成功",
        data={
            "room_id": room.id,
            "game_id": game_record.id,
            "player_color": "white",
            "room_code": room.room_code,
            "status": room.status,
        },
    )


@router.get("/info/{room_id}", response_model=ResponseModel[dict])
def get_room_info(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")

    return ResponseModel(
        data={
            "id": room.id,
            "room_code": room.room_code,
            "host_id": room.host_id,
            "guest_id": room.guest_id,
            "status": room.status,
            "is_host": room.host_id == current_user.id,
            "created_at": room.created_at.isoformat() if room.created_at else None,
        }
    )


@router.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: int, token: str = ""):
    db = SessionLocal()
    try:
        payload = decode_token(token)
        if not payload:
            await websocket.close(code=4001)
            return
        user_id = int(payload.get("sub"))

        room = db.query(Room).filter(Room.id == room_id).first()
        if not room:
            await websocket.close(code=4004)
            return

        if room.status == "expired":
            await websocket.close(code=4010)
            return

        if room.host_id != user_id and room.guest_id != user_id:
            await websocket.close(code=4003)
            return

        await websocket.accept()
        role = manager.attach(room_id, user_id, websocket)

        # 初始化 game 对象（如果还没有）
        game = load_room_game(room_id)
        if game is None and room.status == "playing" and room.game_record_id:
            game_record = (
                db.query(GameRecord)
                .filter(GameRecord.id == room.game_record_id)
                .first()
            )
            if game_record:
                game = GomokuGame()
                for move in game_record.moves or []:
                    if len(move) >= 3:
                        game.add_move(move[0], move[1], move[2])
                save_room_game(room_id, game)

        # 发送身份与初始状态
        if room.host_id == user_id:
            await websocket.send_json({"type": "player_color", "color": "black"})
        else:
            await websocket.send_json({"type": "player_color", "color": "white"})

        await websocket.send_json(
            {
                "type": "game_state",
                "game": (
                    load_room_game(room_id).to_dict()
                    if load_room_game(room_id)
                    else None
                ),
                "status": room.status,
            }
        )

        # 双方都到位则通知对方
        # 注意：opponent_joined 已在 join_room (HTTP) 时通过 push_to_host 推给 host
        # 这里只给本次刚连入的 client 发 opponent_joined；game_state 已在上面发过最新状态
        if manager.both_connected(room_id):
            try:
                await websocket.send_json({"type": "opponent_joined"})
            except Exception:
                pass

        # 主消息循环
        while True:
            data = await websocket.receive_json()
            t = data.get("type")

            if t == "move":
                game = load_room_game(room_id)
                if game is None:
                    continue
                player_color = "black" if room.host_id == user_id else "white"
                stone = (
                    GomokuGame.BLACK if player_color == "black" else GomokuGame.WHITE
                )

                if game.current_player != stone:
                    continue

                if not game.add_move(data["row"], data["col"], stone):
                    continue

                winner, winning_line = game.check_winner()

                game_record = (
                    db.query(GameRecord)
                    .filter(GameRecord.id == room.game_record_id)
                    .first()
                )
                if game_record:
                    game_record.moves = game.moves
                    flag_modified(game_record, "moves")
                    if winner:
                        game_record.winner_id = (
                            room.host_id
                            if winner == GomokuGame.BLACK
                            else room.guest_id
                        )
                        game_record.status = "completed"
                        game_record.ended_at = datetime.now(timezone.utc)
                        room.status = "completed"

                        winner_user = (
                            db.query(User)
                            .filter(User.id == game_record.winner_id)
                            .first()
                        )
                        loser_user = (
                            db.query(User)
                            .filter(
                                User.id
                                == (
                                    room.guest_id
                                    if winner == GomokuGame.BLACK
                                    else room.host_id
                                )
                            )
                            .first()
                        )
                        if winner_user:
                            winner_user.wins += 1
                        if loser_user:
                            loser_user.losses += 1

                    db.commit()

                if winner:
                    state_store.delete_game("room", room_id)
                else:
                    save_room_game(room_id, game)

                move_data = {
                    "type": "move",
                    "row": data["row"],
                    "col": data["col"],
                    "player": player_color,
                    "game_over": winner is not None,
                    "winning_line": winning_line,
                }

                for conn in manager.all_conns(room_id):
                    try:
                        await conn.send_json(move_data)
                    except Exception:
                        pass

            elif t == "undo":
                # ── 悔棋请求阶段：仅登记+通知对方，不直接撤销 ──
                game = load_room_game(room_id)
                if game is None or len(game.moves) < 1:
                    continue

                # 已有待处理请求则忽略（防止双击重复发）
                if state_store.get_pending_undo(room_id):
                    continue

                requester_id = user_id
                requester_color = "black" if room.host_id == user_id else "white"
                manager.start_undo_request(room_id, requester_id)

                # 通知双方：请求方收到"已发送"，对家收到"待确认"
                requester_conn = (
                    manager.host_conns.get(room_id)
                    if requester_color == "black"
                    else manager.guest_conns.get(room_id)
                )
                opponent_conn = (
                    manager.guest_conns.get(room_id)
                    if requester_color == "black"
                    else manager.host_conns.get(room_id)
                )

                request_msg = {
                    "type": "undo_sent",
                    "timeout_sec": manager.UNDO_REQUEST_TIMEOUT,
                }
                opponent_msg = {
                    "type": "undo_request",
                    "from": requester_color,
                }

                if requester_conn:
                    try:
                        await requester_conn.send_json(request_msg)
                    except Exception:
                        pass
                if opponent_conn:
                    try:
                        await opponent_conn.send_json(opponent_msg)
                    except Exception:
                        pass

            elif t == "undo_accept":
                # ── 对方同意：真正执行悔棋并广播 ──
                pending = state_store.get_pending_undo(room_id)
                if not pending:
                    continue
                requester_id = pending.get("requester_id")
                # 只允许"被请求方"接受（也就是 user_id != requester_id）
                if user_id == requester_id:
                    continue
                game = load_room_game(room_id)
                if game is None or len(game.moves) < 1:
                    manager.clear_pending_undo(room_id)
                    continue
                undone = game.undo_move()
                if not undone:
                    manager.clear_pending_undo(room_id)
                    continue
                row, col, player = undone
                player_str = "black" if player == GomokuGame.BLACK else "white"

                game_record = (
                    db.query(GameRecord)
                    .filter(GameRecord.id == room.game_record_id)
                    .first()
                )
                if game_record:
                    game_record.moves = game.moves
                    flag_modified(game_record, "moves")
                    db.commit()

                save_room_game(room_id, game)

                manager.clear_pending_undo(room_id)

                for conn in manager.all_conns(room_id):
                    try:
                        await conn.send_json(
                            {
                                "type": "undo",
                                "row": row,
                                "col": col,
                                "player": player_str,
                            }
                        )
                    except Exception:
                        pass

            elif t == "undo_decline":
                # ── 对方拒绝：通知请求方并清理 ──
                pending = state_store.get_pending_undo(room_id)
                if not pending:
                    continue
                requester_id = pending.get("requester_id")
                if user_id == requester_id:
                    continue
                manager.clear_pending_undo(room_id)

                requester_conn = (
                    manager.host_conns.get(room_id)
                    if room.host_id == requester_id
                    else manager.guest_conns.get(room_id)
                )
                if requester_conn:
                    try:
                        await requester_conn.send_json(
                            {
                                "type": "undo_declined",
                                "message": "对方拒绝了你的悔棋请求",
                            }
                        )
                    except Exception:
                        pass

            elif t == "timeout":
                if load_room_game(room_id) is None:
                    continue

                player_color = "black" if room.host_id == user_id else "white"
                winner_color = "white" if player_color == "black" else "black"
                winner_stone = (
                    GomokuGame.WHITE if player_color == "black" else GomokuGame.BLACK
                )

                game_record = (
                    db.query(GameRecord)
                    .filter(GameRecord.id == room.game_record_id)
                    .first()
                )
                if game_record:
                    game_record.winner_id = (
                        room.host_id
                        if winner_stone == GomokuGame.BLACK
                        else room.guest_id
                    )
                    game_record.status = "completed"
                    game_record.ended_at = datetime.now(timezone.utc)
                    room.status = "completed"

                    winner_user = (
                        db.query(User).filter(User.id == game_record.winner_id).first()
                    )
                    loser_user = db.query(User).filter(User.id == user_id).first()
                    if winner_user:
                        winner_user.wins += 1
                    if loser_user:
                        loser_user.losses += 1
                    db.commit()

                state_store.delete_game("room", room_id)

                for conn in manager.all_conns(room_id):
                    try:
                        await conn.send_json(
                            {
                                "type": "move",
                                "row": -1,
                                "col": -1,
                                "player": winner_color,
                                "game_over": True,
                                "winning_line": None,
                            }
                        )
                    except Exception:
                        pass

            elif t == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        try:
            manager.detach(room_id, websocket)
            # 断线方如果是悔棋请求方 → 自动取消待处理请求（避免对方弹窗干等）
            pending = state_store.get_pending_undo(room_id)
            if pending and pending.get("requester_id") == user_id:
                manager.clear_pending_undo(room_id)
        except Exception:
            pass
        db.close()


def notify_room_expired(room_id: int):
    """被 main.py 的清理任务调用，通知房间内所有 WebSocket 房间已过期"""
    import asyncio

    async def _send():
        for conn in manager.all_conns(room_id):
            try:
                await conn.send_json({"type": "room_expired"})
            except Exception:
                pass
        manager.drop_game(room_id)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_send())
        else:
            loop.run_until_complete(_send())
    except Exception:
        pass
