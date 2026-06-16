from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import Dict, List, Optional
from database import get_db, SessionLocal
from models.user import User
from models.room import Room
from models.game import GameRecord
from utils.auth import decode_token, get_current_user
from schemas.common import ResponseModel
from services.game_service import GomokuGame
import json
import random
import string

router = APIRouter(prefix="/api/room", tags=["房间"])


class RoomConnectionManager:
    """房间连接管理器：精确追踪 host / guest 的连接"""

    def __init__(self):
        self.games: Dict[int, GomokuGame] = {}
        self.host_conns: Dict[int, WebSocket] = {}
        self.guest_conns: Dict[int, WebSocket] = {}

    def attach(self, room_id: int, user_id: int, ws: WebSocket) -> str:
        """根据 user_id 归类到 host 或 guest 连接。返回角色 'host' | 'guest'"""
        role = None
        if user_id not in (None,):
            # 简单做法：第一次连接视为 host，第二次视为 guest
            if room_id not in self.host_conns:
                self.host_conns[room_id] = ws
                role = "host"
            elif room_id not in self.guest_conns:
                self.guest_conns[room_id] = ws
                role = "guest"
            else:
                # 兜底：若两方都已存在，作为观察者
                role = "observer"
        return role

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
        self.games.pop(room_id, None)


manager = RoomConnectionManager()


def generate_room_code() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


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
    if room.status == "playing" and room.guest_id and room.guest_id != current_user.id:
        raise HTTPException(status_code=409, detail="房间已开始，请等待本局结束")

    if room.host_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能加入自己的房间")

    # 已是 guest，直接返回（用于重连）
    if room.guest_id == current_user.id and room.game_record_id:
        return ResponseModel(
            message="已加入房间",
            data={
                "room_id": room.id,
                "game_id": room.game_record_id,
                "player_color": "white",
            },
        )

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

    manager.games[room.id] = GomokuGame()

    return ResponseModel(
        message="加入成功",
        data={"room_id": room.id, "game_id": game_record.id, "player_color": "white"},
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
        if (
            room_id not in manager.games
            and room.status == "playing"
            and room.game_record_id
        ):
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
                manager.games[room_id] = game

        # 发送身份与初始状态
        if room.host_id == user_id:
            await websocket.send_json({"type": "player_color", "color": "black"})
        else:
            await websocket.send_json({"type": "player_color", "color": "white"})

        await websocket.send_json(
            {
                "type": "game_state",
                "game": (
                    manager.games[room_id].to_dict()
                    if room_id in manager.games
                    else None
                ),
                "status": room.status,
            }
        )

        # 双方都到位则通知对方
        if manager.both_connected(room_id):
            host_c = manager.host_conn(room_id)
            if host_c:
                try:
                    await host_c.send_json({"type": "opponent_joined"})
                except Exception:
                    pass

            for conn in manager.all_conns(room_id):
                try:
                    await conn.send_json(
                        {
                            "type": "game_state",
                            "game": (
                                manager.games[room_id].to_dict()
                                if room_id in manager.games
                                else None
                            ),
                            "status": "playing",
                        }
                    )
                except Exception:
                    pass

        # 主消息循环
        while True:
            data = await websocket.receive_json()
            t = data.get("type")

            if t == "move":
                if room_id not in manager.games:
                    continue

                game = manager.games[room_id]
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
                    if winner:
                        game_record.winner_id = (
                            room.host_id
                            if winner == GomokuGame.BLACK
                            else room.guest_id
                        )
                        game_record.status = "completed"
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
                if (
                    room_id not in manager.games
                    or len(manager.games[room_id].moves) < 1
                ):
                    continue

                game = manager.games[room_id]
                undone = game.undo_move()
                if not undone:
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
                    db.commit()

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

            elif t == "timeout":
                if room_id not in manager.games:
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
                    room.status = "completed"
                    db.commit()

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
