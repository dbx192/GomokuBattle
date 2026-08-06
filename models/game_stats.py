from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint

from database import Base


class UserGameStats(Base):
    __tablename__ = "user_game_stats"
    __table_args__ = (UniqueConstraint("user_id", "game_code", name="uq_user_game_stats"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    game_code = Column(String(20), nullable=False, index=True)
    wins = Column(Integer, default=0, nullable=False)
    losses = Column(Integer, default=0, nullable=False)
    draws = Column(Integer, default=0, nullable=False)
