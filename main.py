from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
import mimetypes
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from database import init_db
from routers import auth, game, room, ranking
from routers.room import notify_room_expired
import asyncio
import traceback
from datetime import datetime, timedelta
from database import SessionLocal
from models.room import Room

app = FastAPI(title="GomokuBattle", version="1.0.0")

# ── 注册常见静态资源 MIME（避免 woff2/woff 字体被当 text/plain 发送，浏览器会拒收） ──
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("font/eot", ".eot")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/wasm", ".wasm")

app.mount("/static", StaticFiles(directory="static"), name="static")

# 模板引擎：所有页面复用 templates/base.html，通过 {% block %} 注入内容
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def render(request: Request, template_name: str, **ctx) -> HTMLResponse:
    """统一渲染入口：自动注入 request，方便模板里 {{ request.path }} 等使用"""
    return templates.TemplateResponse(template_name, {"request": request, **ctx})


# ── 全局异常兜底：500 时打印完整堆栈到控制台，避免页面静默失败 ──
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal Server Error: {type(exc).__name__}: {exc}"},
    )


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return render(request, "index.html", active="home")


@app.get("/game", response_class=HTMLResponse)
async def game_page(request: Request):
    return render(request, "game.html", active="game", title="人机对战 — GomokuBattle")


@app.get("/room", response_class=HTMLResponse)
async def room_page(request: Request):
    return render(request, "room.html", active="room", title="房间对战 — GomokuBattle")


@app.get("/rankings", response_class=HTMLResponse)
async def rankings_page(request: Request):
    return render(request, "rankings.html", active="rankings", title="排行榜 — GomokuBattle")


app.include_router(auth.router)
app.include_router(game.router)
app.include_router(room.router)
app.include_router(ranking.router)


@app.on_event("startup")
async def startup():
    init_db()
    # 把主事件循环注入 room 路由器，让 HTTP 同步端点能安全推送 WebSocket 消息
    from routers.room import manager

    manager.set_main_loop(asyncio.get_running_loop())
    asyncio.create_task(cleanup_expired_rooms())


async def cleanup_expired_rooms():
    while True:
        await asyncio.sleep(10)
        try:
            db = SessionLocal()
            threshold = datetime.utcnow() - timedelta(minutes=5)
            expired = (
                db.query(Room)
                .filter(Room.status == "waiting", Room.created_at < threshold)
                .all()
            )
            for room in expired:
                room.status = "expired"
                # 通知 WebSocket 房间内的玩家
                try:
                    notify_room_expired(room.id)
                except Exception:
                    pass
            if expired:
                db.commit()
            db.close()
        except Exception as e:
            print(f"Cleanup error: {e}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
