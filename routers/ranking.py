from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models.user import User
from schemas.common import ResponseModel
from schemas.user import UserStats

router = APIRouter(prefix="/api/rankings", tags=["排行榜"])

@router.get("", response_model=ResponseModel[list])
def get_rankings(db: Session = Depends(get_db), limit: int = 20):
    users = db.query(User).all()
    
    rankings = []
    for user in users:
        total = user.wins + user.losses
        win_rate = (user.wins / total * 100) if total > 0 else 0
        rankings.append(UserStats(
            id=user.id,
            username=user.username,
            rank=user.rank,
            wins=user.wins,
            losses=user.losses,
            win_rate=round(win_rate, 1)
        ))
    
    rankings.sort(key=lambda x: (-x.wins, -x.win_rate))
    rankings = rankings[:limit]
    
    return ResponseModel(data=rankings)
