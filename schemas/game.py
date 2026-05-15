from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class MoveRequest(BaseModel):
    row: int
    col: int
    game_id: Optional[int] = None

class UndoRequest(BaseModel):
    game_id: Optional[int] = None

class MoveResponse(BaseModel):
    row: int
    col: int
    player: str
    game_over: bool = False
    winner: Optional[str] = None
    winning_line: Optional[List[List[int]]] = None

class AiMoveResponse(BaseModel):
    player_move: MoveResponse
    ai_move: Optional[MoveResponse] = None

class GameStartResponse(BaseModel):
    game_id: int
    board_size: int = 15
    first_player: str = "black"

class UndoResponse(BaseModel):
    success: bool
    message: str

class GameRecordResponse(BaseModel):
    id: int
    player1_id: int
    player2_id: Optional[int]
    winner_id: Optional[int]
    game_type: str
    status: str
    moves: List
    created_at: datetime

    class Config:
        from_attributes = True
