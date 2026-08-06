from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

class GameRecord(Base):
    __tablename__ = "game_records"

    id = Column(Integer, primary_key=True, index=True)
    player1_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    player2_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    winner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    moves = Column(JSON, default=[])
    game_type = Column(String(20), default="ai")
    # `game_type` keeps the legacy ai/room value; game_code identifies the ruleset.
    game_code = Column(String(20), default="gomoku", nullable=False, index=True)
    rules_version = Column(String(20), default="v1", nullable=False)
    initial_state = Column(JSON, nullable=True)
    game_state = Column(JSON, nullable=True)
    result_reason = Column(String(40), nullable=True)
    time_control = Column(JSON, nullable=True)
    clocks = Column(JSON, nullable=True)
    status = Column(String(20), default="in_progress")
    created_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)

    player1 = relationship("User", foreign_keys=[player1_id], back_populates="games_as_player1")
    player2 = relationship("User", foreign_keys=[player2_id], back_populates="games_as_player2")
    winner = relationship("User", foreign_keys=[winner_id], back_populates="games_won")
