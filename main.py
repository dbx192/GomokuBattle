from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from database import init_db
from routers import auth, game, room, ranking

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
