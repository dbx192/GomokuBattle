from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from models.game_stats import UserGameRating
from schemas.common import ResponseModel
from schemas.user import UserStats
from services.engines import GAME_CATALOG

router = APIRouter(prefix="/api/rankings", tags=["排行榜"])

@router.get("", response_model=ResponseModel[list])
def get_rankings(db: Session = Depends(get_db), limit: int = 20, game_code: str = "gomoku"):
    if game_code not in GAME_CATALOG:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="不支持的棋种")
    limit = min(max(limit, 1), 100)
    rows = (
        db.query(User, UserGameRating)
        .join(UserGameRating, UserGameRating.user_id == User.id)
        .filter(UserGameRating.game_code == game_code)
        .all()
    )
    rankings = []
    for user, stats in rows:
        total = stats.wins + stats.losses
        win_rate = (stats.wins / total * 100) if total > 0 else 0
        rankings.append(UserStats(
            id=user.id,
            username=user.username,
            rank=user.rank,
            wins=stats.wins,
            losses=stats.losses,
            win_rate=round(win_rate, 1),
            rating=stats.rating,
        ))
    
    rankings.sort(key=lambda x: (-x.rating, -x.wins, -x.win_rate))
    rankings = rankings[:limit]
    
    return ResponseModel(data=rankings)
