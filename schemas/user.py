from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class UserCreate(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    rank: str
    wins: int
    losses: int
    created_at: datetime

    class Config:
        from_attributes = True

class UserStats(BaseModel):
    id: int
    username: str
    rank: str
    wins: int
    losses: int
    win_rate: float

    class Config:
        from_attributes = True
