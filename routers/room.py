from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import Dict, List
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

room_games: Dict[int, GomokuGame] = {}
room_connections: Dict[int, List[WebSocket]] = {}


def generate_room_code() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


@router.get("/list", response_model=ResponseModel[List[dict]])
def get_room_list(db: Session = Depends(get_db)):
    rooms = db.query(Room).filter(Room.status == "waiting").all()
    room_list = []
    for room in rooms:
        room_list.append(
            {
                "id": room.id,
                "room_code": room.room_code,
                "host_id": room.host_id,
                "host_name": room.host.username,
                "status": room.status,
                "created_at": room.created_at.isoformat(),
            }
        )
    return ResponseModel(data=room_list)


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
        message="房间创建成功", data={"id": room.id, "room_code": room.room_code}
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

    if room.host_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能加入自己的房间")

    if room.guest_id == current_user.id:
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

    game = GomokuGame()
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

    room_games[room.id] = game

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

        if room.host_id != user_id and room.guest_id != user_id:
            await websocket.close(code=4003)
            return

        await websocket.accept()

        if room_id not in room_connections:
            room_connections[room_id] = []
        room_connections[room_id].append(websocket)

        if (
            room_id not in room_games
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
                room_games[room_id] = game

        if room.host_id == user_id:
            await websocket.send_json({"type": "player_color", "color": "black"})
        else:
            await websocket.send_json({"type": "player_color", "color": "white"})

        await websocket.send_json(
            {
                "type": "game_state",
                "game": (
                    room_games[room_id].to_dict() if room_id in room_games else None
                ),
                "status": room.status,
            }
        )

        if len(room_connections[room_id]) >= 2:
            host_conn = room_connections[room_id][0]
            await host_conn.send_json({"type": "opponent_joined"})

            for conn in room_connections[room_id]:
                await conn.send_json(
                    {
                        "type": "game_state",
                        "game": (
                            room_games[room_id].to_dict()
                            if room_id in room_games
                            else None
                        ),
                        "status": "playing",
                    }
                )

        while True:
            data = await websocket.receive_json()

            if data["type"] == "move":
                if room_id not in room_games:
                    continue

                game = room_games[room_id]
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

                for conn in room_connections[room_id]:
                    await conn.send_json(move_data)

            elif data["type"] == "undo":
                if room_id not in room_games or len(room_games[room_id].moves) < 1:
                    continue

                game = room_games[room_id]
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

                for conn in room_connections[room_id]:
                    await conn.send_json(
                        {"type": "undo", "row": row, "col": col, "player": player_str}
                    )

            elif data["type"] == "timeout":
                if room_id not in room_games:
                    continue

                player_color = "black" if room.host_id == user_id else "white"
                winner_color = "white" if player_color == "black" else "black"
                winner_stone = GomokuGame.WHITE if player_color == "black" else GomokuGame.BLACK

                game_record = (
                    db.query(GameRecord)
                    .filter(GameRecord.id == room.game_record_id)
                    .first()
                )
                if game_record:
                    game_record.winner_id = (
                        room.host_id if winner_stone == GomokuGame.BLACK else room.guest_id
                    )
                    game_record.status = "completed"
                    room.status = "completed"

                    winner_user = db.query(User).filter(User.id == game_record.winner_id).first()
                    loser_user = db.query(User).filter(
                        User.id == (room.guest_id if winner_stone == GomokuGame.BLACK else room.host_id)
                    ).first()
                    if winner_user:
                        winner_user.wins += 1
                    if loser_user:
                        loser_user.losses += 1
                    db.commit()

                for conn in room_connections[room_id]:
                    await conn.send_json({
                        "type": "move",
                        "row": -1,
                        "col": -1,
                        "player": winner_color,
                        "game_over": True,
                        "winning_line": None,
                    })

    except WebSocketDisconnect:
        if room_id in room_connections:
            room_connections[room_id] = [
                c for c in room_connections[room_id] if c != websocket
            ]
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        db.close()
