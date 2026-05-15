from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    rank = Column(String(20), default="新手")
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    games_as_player1 = relationship("GameRecord", foreign_keys="GameRecord.player1_id", back_populates="player1")
    games_as_player2 = relationship("GameRecord", foreign_keys="GameRecord.player2_id", back_populates="player2")
    games_won = relationship("GameRecord", foreign_keys="GameRecord.winner_id", back_populates="winner")
