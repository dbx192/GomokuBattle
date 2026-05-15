from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import timedelta
from database import get_db
from models.user import User
from schemas.user import UserCreate, UserLogin, UserResponse
from schemas.common import ResponseModel
from utils.auth import verify_password, get_password_hash, create_access_token, get_current_user
from config import ACCESS_TOKEN_EXPIRE_MINUTES

router = APIRouter(prefix="/api/auth", tags=["认证"])

@router.post("/register", response_model=ResponseModel[UserResponse])
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    hashed_password = get_password_hash(user_data.password)
    user = User(
        username=user_data.username,
        password_hash=hashed_password,
        rank="新手",
        wins=0,
        losses=0
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return ResponseModel(
        code=201,
        message="注册成功",
        data=UserResponse.model_validate(user)
    )

@router.post("/login", response_model=ResponseModel[dict])
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == user_data.username).first()
    if not user or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    return ResponseModel(
        message="登录成功",
        data={
            "access_token": access_token,
            "token_type": "bearer",
            "user": UserResponse.model_validate(user).model_dump()
        }
    )

@router.get("/me", response_model=ResponseModel[UserResponse])
def get_me(current_user: User = Depends(get_current_user)):
    return ResponseModel(
        data=UserResponse.model_validate(current_user)
    )

@router.get("/stats", response_model=ResponseModel[dict])
def get_stats(current_user: User = Depends(get_current_user)):
    total = current_user.wins + current_user.losses
    win_rate = (current_user.wins / total * 100) if total > 0 else 0
    
    return ResponseModel(
        data={
            "wins": current_user.wins,
            "losses": current_user.losses,
            "total": total,
            "win_rate": round(win_rate, 1)
        }
    )
