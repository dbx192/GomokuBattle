import base64
import html
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from schemas.user import UserCreate, UserLogin, UserResponse
from schemas.common import ResponseModel
from utils.auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    get_current_user,
)
from config import (
    ACCESS_TOKEN_EXPIRE_MINUTES, LOGIN_IP_RATE_LIMIT_MAX_ATTEMPTS,
    LOGIN_IP_RATE_LIMIT_WINDOW_SECONDS, LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
    LOGIN_RATE_LIMIT_WINDOW_SECONDS, REGISTER_IP_RATE_LIMIT_MAX_ATTEMPTS,
    REGISTER_IP_RATE_LIMIT_WINDOW_SECONDS, TRUST_PROXY_HEADERS,
)
from services.state_store import state_store

router = APIRouter(prefix="/api/auth", tags=["认证"])


def _client_ip(request: Request) -> str:
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _verify_captcha(captcha_id: str, captcha_answer: str):
    expected = state_store.consume_captcha(captcha_id)
    if not expected or not secrets.compare_digest(expected, captcha_answer.strip().upper()):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")


def _token_response(user: User, message: str, code: int = 200) -> ResponseModel:
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return ResponseModel(code=code, message=message, data={
        "access_token": access_token, "token_type": "bearer",
        "user": UserResponse.model_validate(user).model_dump(),
    })


@router.get("/captcha", response_model=ResponseModel[dict])
def captcha(request: Request):
    client_ip = _client_ip(request)
    allowed, ttl = state_store.check_rate_limit("captcha_ip", client_ip, 30, 60)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"验证码请求过于频繁，请在 {ttl} 秒后重试")
    answer = "".join(secrets.choice("23456789ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5))
    captcha_id = secrets.token_urlsafe(24)
    state_store.save_captcha(captcha_id, answer)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="140" height="42" viewBox="0 0 140 42"><rect width="140" height="42" fill="#201d1b"/><path d="M0 12 L140 30 M0 34 L140 8" stroke="#8b6914" opacity=".45"/><text x="12" y="29" fill="#f0c27a" font-family="monospace" font-size="25" letter-spacing="5">{html.escape(answer)}</text></svg>'''
    image = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    return ResponseModel(data={"captcha_id": captcha_id, "image": image})


@router.post("/register", response_model=ResponseModel[dict])
def register(user_data: UserCreate, request: Request, db: Session = Depends(get_db)):
    client_ip = _client_ip(request)
    allowed, ttl = state_store.check_rate_limit(
        "register_ip", client_ip, REGISTER_IP_RATE_LIMIT_MAX_ATTEMPTS, REGISTER_IP_RATE_LIMIT_WINDOW_SECONDS
    )
    if not allowed:
        raise HTTPException(status_code=429, detail=f"该 IP 注册过于频繁，请在 {ttl} 秒后重试")
    _verify_captcha(user_data.captcha_id, user_data.captcha_answer)
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="用户名已存在")

    hashed_password = get_password_hash(user_data.password)
    user = User(
        username=user_data.username,
        password_hash=hashed_password,
        rank="新手",
        wins=0,
        losses=0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return _token_response(user, "注册成功", 201)


@router.post("/login", response_model=ResponseModel[dict])
def login(user_data: UserLogin, request: Request, db: Session = Depends(get_db)):
    client_ip = _client_ip(request)
    account_key = user_data.username.strip().lower()
    ip_allowed, ip_ttl = state_store.check_rate_limit(
        "login_ip", client_ip, LOGIN_IP_RATE_LIMIT_MAX_ATTEMPTS, LOGIN_IP_RATE_LIMIT_WINDOW_SECONDS
    )
    account_allowed, account_ttl = state_store.check_rate_limit(
        "login_account", account_key, LOGIN_RATE_LIMIT_MAX_ATTEMPTS, LOGIN_RATE_LIMIT_WINDOW_SECONDS
    )
    if not ip_allowed or not account_allowed:
        ttl = max(ip_ttl, account_ttl)
        raise HTTPException(
            status_code=429, detail=f"登录过于频繁，请在 {ttl} 秒后重试"
        )

    _verify_captcha(user_data.captcha_id, user_data.captcha_answer)

    user = db.query(User).filter(User.username == user_data.username).first()
    if not user or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    state_store.reset_rate_limit("login_account", account_key)
    return _token_response(user, "登录成功")


@router.get("/me", response_model=ResponseModel[UserResponse])
def get_me(current_user: User = Depends(get_current_user)):
    return ResponseModel(data=UserResponse.model_validate(current_user))


@router.get("/stats", response_model=ResponseModel[dict])
def get_stats(current_user: User = Depends(get_current_user)):
    total = current_user.wins + current_user.losses
    win_rate = (current_user.wins / total * 100) if total > 0 else 0

    return ResponseModel(
        data={
            "wins": current_user.wins,
            "losses": current_user.losses,
            "total": total,
            "win_rate": round(win_rate, 1),
        }
    )
