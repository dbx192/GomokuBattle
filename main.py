from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from database import init_db
from routers import auth, game, room, ranking
from routers.room import notify_room_expired
import asyncio
from datetime import datetime, timedelta
from database import SessionLocal
from models.room import Room

app = FastAPI(title="GomokuBattle", version="1.0.0")

app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return FileResponse("static/html/index.html")


@app.get("/game")
async def game_page():
    return FileResponse("static/html/game.html")


@app.get("/room")
async def room_page():
    return FileResponse("static/html/room.html")


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
