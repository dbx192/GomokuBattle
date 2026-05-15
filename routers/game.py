from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models.user import User
from models.game import GameRecord
from schemas.game import (
    GameStartResponse,
    MoveRequest,
    MoveResponse,
    AiMoveResponse,
    UndoRequest,
    UndoResponse,
    GameRecordResponse,
)
from schemas.common import ResponseModel, ListData
from schemas.user import UserStats
from utils.auth import get_current_user
from services.game_service import GomokuGame
import json

router = APIRouter(prefix="/api/game", tags=["游戏"])

ai_games = {}


@router.post("/ai/start", response_model=ResponseModel[GameStartResponse])
async def start_ai_game(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    game = GomokuGame()
    game_record = GameRecord(
        player1_id=current_user.id,
        player2_id=None,
        game_type="ai",
        moves=[],
        status="in_progress",
    )
    db.add(game_record)
    db.commit()
    db.refresh(game_record)

    ai_games[game_record.id] = game

    return ResponseModel(
        message="游戏开始",
        data=GameStartResponse(
            game_id=game_record.id, board_size=15, first_player="black"
        ),
    )


@router.post("/ai/move", response_model=ResponseModel[AiMoveResponse])
async def make_ai_move(
    move_data: MoveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if move_data.game_id not in ai_games:
        raise HTTPException(status_code=404, detail="游戏不存在或已结束")

    game = ai_games[move_data.game_id]

    if not game.add_move(move_data.row, move_data.col, GomokuGame.BLACK):
        raise HTTPException(status_code=400, detail="该位置已有棋子")

    game_record = (
        db.query(GameRecord).filter(GameRecord.id == move_data.game_id).first()
    )
    if game_record:
        game_record.moves = game.moves

    winner, winning_line = game.check_winner()
    if winner:
        game_record.winner_id = current_user.id if winner == GomokuGame.BLACK else None
        game_record.status = "completed"
        current_user.wins += 1
        db.commit()

        return ResponseModel(
            data=AiMoveResponse(
                player_move=MoveResponse(
                    row=move_data.row,
                    col=move_data.col,
                    player="black",
                    game_over=True,
                    winner="black",
                    winning_line=winning_line,
                )
            )
        )

    ai_row, ai_col = game.get_ai_move()
    game.add_move(ai_row, ai_col, GomokuGame.WHITE)

    if game_record:
        game_record.moves = game.moves

    winner, winning_line = game.check_winner()
    if winner:
        game_record.winner_id = None
        game_record.status = "completed"
        current_user.losses += 1
        db.commit()

        return ResponseModel(
            data=AiMoveResponse(
                player_move=MoveResponse(
                    row=move_data.row, col=move_data.col, player="black"
                ),
                ai_move=MoveResponse(
                    row=ai_row,
                    col=ai_col,
                    player="white",
                    game_over=True,
                    winner="white",
                    winning_line=winning_line,
                ),
            )
        )

    db.commit()

    return ResponseModel(
        data=AiMoveResponse(
            player_move=MoveResponse(
                row=move_data.row, col=move_data.col, player="black"
            ),
            ai_move=MoveResponse(row=ai_row, col=ai_col, player="white"),
        )
    )


@router.post("/ai/undo", response_model=ResponseModel[UndoResponse])
async def undo_ai_move(
    move_data: UndoRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if move_data.game_id not in ai_games:
        raise HTTPException(status_code=404, detail="游戏不存在")

    game = ai_games[move_data.game_id]

    if len(game.moves) < 2:
        return ResponseModel(
            data=UndoResponse(success=False, message="没有可撤销的步数")
        )

    game.undo_move()
    game.undo_move()

    game_record = (
        db.query(GameRecord).filter(GameRecord.id == move_data.game_id).first()
    )
    if game_record:
        game_record.moves = game.moves
        db.commit()

    return ResponseModel(data=UndoResponse(success=True, message="撤销成功"))


@router.get("/history", response_model=ResponseModel[ListData[GameRecordResponse]])
def get_game_history(
    page: int = 1,
    page_size: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    total = (
        db.query(GameRecord)
        .filter(
            (GameRecord.player1_id == current_user.id)
            | (GameRecord.player2_id == current_user.id)
        )
        .count()
    )

    games = (
        db.query(GameRecord)
        .filter(
            (GameRecord.player1_id == current_user.id)
            | (GameRecord.player2_id == current_user.id)
        )
        .order_by(GameRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return ResponseModel(
        data=ListData(
            total=total,
            items=[GameRecordResponse.model_validate(g) for g in games],
            page=page,
            page_size=page_size,
        )
    )
