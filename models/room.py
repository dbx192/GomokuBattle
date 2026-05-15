from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    room_code = Column(String(10), unique=True, nullable=False, index=True)
    host_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    guest_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(20), default="waiting")
    game_record_id = Column(Integer, ForeignKey("game_records.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    host = relationship("User", foreign_keys=[host_id])
    guest = relationship("User", foreign_keys=[guest_id])
