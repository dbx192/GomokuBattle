# GomokuBattle — Online Gomoku Battle Platform

A FastAPI-based online Gomoku (Five-in-a-Row) battle platform that supports both AI matches and real-time two-player room matches. Zero ads, pure gameplay.

## Features

- **AI Match** — Heuristic scoring AI, Canvas board, undo/restart
- **Room Match** — 6-character room code, link sharing, 5-minute auto-expiry
- **Real-time Communication** — WebSocket, host/guest precise addressing, auto-reconnect
- **Room Resume** — Page refresh doesn't lose state; board is restored from `game_records.moves`
- **Undo Protocol** — AI: instant rollback; Room: 3-phase (request → 30s accept/decline → timeout)
- **Move Timer** — Room mode: 60s per move; timeout = loss
- **Rankings** — Top 3 podium + full leaderboard + your rank highlight + 30s auto-refresh
- **Match History** — Paginated lists for both AI and Room modes
- **Unified Auth** — JWT (HS256, 7-day expiry), frontend auto-redirects to login on 401
- **Zero Ads** — Distraction-free play
- **PC Responsive** — Bootstrap 5 Grid, auto-adapts to 1080P/2K/4K

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend Framework | FastAPI 0.115 + Uvicorn 0.34 |
| ORM | SQLAlchemy 2.0 |
| Database | SQLite (`./gomoku.db`) |
| Auth | JWT (`python-jose`, HS256) |
| Password | bcrypt 4.x (auto-truncated to 72 bytes) |
| Real-time | WebSocket (`fastapi.WebSocket`) |
| Template | Jinja2 3.1 |
| Frontend UI | Bootstrap 5.3 + Bootstrap Icons 1.11 (localized) |
| Frontend Interactivity | jQuery 3.7 + Toastr 2.1 |
| Board Rendering | HTML5 Canvas |

## Project Structure

```
GomokuBattle/
├── main.py                  # App entry: register routers + startup cleanup task + global exception handler
├── config.py                # Config: DATABASE_URL / SECRET_KEY / expiry time
├── database.py              # SQLAlchemy engine + SessionLocal + Base + get_db + init_db
├── seed_users.py            # One-click seed of 5 test accounts
│
├── models/                  # SQLAlchemy ORM models
│   ├── user.py              #   User: users table
│   ├── room.py              #   Room: rooms table
│   └── game.py              #   GameRecord: match records table
│
├── routers/                 # FastAPI routers
│   ├── auth.py              #   /api/auth/*     register/login/me/stats
│   ├── game.py              #   /api/game/*     AI match (start/move/undo/history)
│   ├── room.py              #   /api/room/*     rooms + WebSocket
│   └── ranking.py           #   /api/rankings   leaderboard
│
├── schemas/                 # Pydantic models
│   ├── common.py            #   ResponseModel[T] / ListData[T]
│   ├── user.py              #   UserCreate / UserLogin / UserResponse / UserStats
│   └── game.py              #   MoveRequest / MoveResponse / GameStartResponse / ...
│
├── services/
│   └── game_service.py      #   GomokuGame: board logic + AI scoring + win detection
│
├── utils/
│   └── auth.py              #   bcrypt + JWT + get_current_user + decode_token
│
├── templates/               # Jinja2 templates
│   ├── base.html            #   Base layout: navbar + auth modals + script slot
│   ├── index.html           #   /          Home
│   ├── game.html            #   /game      AI match
│   ├── room.html            #   /room      Room match
│   ├── rankings.html        #   /rankings  Leaderboard
│   └── partials/
│       ├── _navbar.html     #     Shared navbar
│       └── _auth_modals.html#     Login/Register modals
│
├── static/
│   ├── css/main.css         #   Global styles (CSS variable theme)
│   ├── js/
│   │   ├── main.js          #     API wrapper + global 401 handler
│   │   ├── game.js          #     /game page logic
│   │   ├── room.js          #     /room page logic (WebSocket + timer + undo protocol)
│   │   └── rankings.js      #     /rankings page logic
│   └── lib/                 #   Localized third-party libs (bootstrap / jquery / toastr / fonts)
│
├── PRD.md                   # PRD document (Chinese)
├── README.md                # This file
├── requirements.txt         # Python dependencies
└── .gitignore
```

## Quick Start

### 1. Install Dependencies

```bash
cd GomokuBattle
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Start the Service

```bash
# Option A: direct run
python main.py

# Option B: uvicorn (recommended for development)
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Default port `8000`, listening on `0.0.0.0` (`main.py:118`).

### 3. Seed Test Accounts (Optional)

```bash
# Make sure the service is running, then open another terminal
python seed_users.py
```

Creates 5 test accounts: `alice / alice123`, `bob / bob123`, `charlie / charlie123`, `diana / diana123`, `evan / evan123`.

### 4. Access

| Page | URL |
|------|-----|
| Home | <http://127.0.0.1:8000/> |
| AI Match | <http://127.0.0.1:8000/game> |
| Room Match | <http://127.0.0.1:8000/room> |
| Rankings | <http://127.0.0.1:8000/rankings> |
| API Docs | <http://127.0.0.1:8000/docs> |

## Configuration

Override defaults via environment variables ([config.py](file:///d:/ProjectsPython/GomokuBattle/config.py)):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./gomoku.db` | SQLAlchemy connection string |
| `SECRET_KEY` | `gomoku-battle-secret-key-change-in-production` | JWT signing key (**MUST change in production**) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `10080` (7 days) | JWT expiry |

## API Quick Reference

> Unified response: `{ code: 200, message: "success", data: T }`
> Auth: `Authorization: Bearer <jwt>` (except login/register)

### Auth `/api/auth`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/register` | — | `{ username, password }` → 201 + user info |
| POST | `/login` | — | `{ username, password }` → `{ access_token, token_type, user }` |
| GET  | `/me` | ✓ | Current user info |
| GET  | `/stats` | ✓ | `{ wins, losses, total, win_rate }` |

### AI Match `/api/game`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/ai/start` | ✓ | Returns `{ game_id, board_size: 15, first_player: "black" }` |
| POST | `/ai/move` | ✓ | `{ game_id, row, col }` → `{ player_move, ai_move, game_over? }` |
| POST | `/ai/undo` | ✓ | `{ game_id }` roll back two stones at once |
| GET  | `/history?page=1&page_size=10` | ✓ | My match history (paginated) |

### Room `/api/room`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET  | `/list` | — | Waiting rooms |
| GET  | `/history` | ✓ | Rooms I joined (most recent 50) |
| GET  | `/current` | ✓ | My active room (for refresh-resume) |
| POST | `/create` | ✓ | Returns `{ id, room_code, expires_at }` |
| POST | `/join/{room_code}` | ✓ | Returns `{ room_id, game_id, player_color, ... }` |
| GET  | `/info/{room_id}` | ✓ | Room details |
| WS   | `/ws/{room_id}?token=...` | query | Real-time play (see protocol below) |

### Rankings `/api/rankings`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET  | `/?limit=20` | — | Top N (sorted by `-wins, -win_rate`) |

## WebSocket Protocol

Connection: `/api/room/ws/{room_id}?token=<jwt>`

| Type | Direction | Description |
|------|-----------|-------------|
| `player_color` | S→C | `{ color: "black" \| "white" }` |
| `game_state` | S→C | `{ game: {board, moves, current_player}, status }` |
| `opponent_joined` | S→C | `{}` / `{ guest_id }` |
| `move` | C→S / S→C | `{ row, col, player, game_over?, winning_line? }` |
| `undo` | C→S | Send undo request |
| `undo_sent` | S→C | `{ timeout_sec }` (notify requester) |
| `undo_request` | S→C | `{ from }` (notify opponent, 30s countdown) |
| `undo_accept` / `undo_decline` | C→S | Accept / decline |
| `undo_declined` | S→C | `{ message }` |
| `undo_timeout` | S→C | `{ message }` (auto-decline after 30s) |
| `undo` | S→C | `{ row, col, player }` (real rollback broadcast) |
| `room_expired` | S→C | 5 min without match |
| `timeout` | C→S / S→C | 60s move timeout = loss |
| `ping` / `pong` | both | heartbeat |

## Business Rules

1. **Room Expiry** — If no guest joins within 5 min → status `expired`, push `room_expired` (startup `cleanup_expired_rooms` task scans every 10s)
2. **Undo Protocol** — Sender emits `undo` → opponent replies `undo_accept` / `undo_decline` within 30s; timeout = auto-decline
3. **Move Timeout** — If no move within 60s → client auto-emits `timeout` → server declares loss
4. **Page Refresh Resume** — `/api/room/current` + URL `?code=...` re-binds WebSocket; state is rebuilt from `game_records.moves`
5. **Disconnect Cancels Undo** — When requester disconnects, `clear_pending_undo` is called automatically
6. **AI Instant Undo** — No opponent protocol; rolls back the last two stones (player + AI)
7. **Rankings** — Frontend optional 30s auto-refresh
8. **Thread-safe Room Push** — `join_room` sync endpoint uses `push_to_host` to safely push WS messages from HTTP thread

## Database

SQLite tables auto-created on startup (`database.init_db`):

- `users` — users
- `rooms` — rooms (unique index on 6-char `room_code`)
- `game_records` — match records (JSON `moves`)

## FAQ

### Q: Switch database?

Override `DATABASE_URL`, e.g. PostgreSQL:

```bash
export DATABASE_URL="postgresql://user:pass@localhost/gomoku"
```

`database.py` auto-detects (only `sqlite` passes `check_same_thread=False`).

### Q: Adjust JWT expiry?

```bash
export ACCESS_TOKEN_EXPIRE_MINUTES=1440   # 24 hours
```

### Q: AI difficulty?

Tune the weights in [services/game_service.py](file:///d:/ProjectsPython/GomokuBattle/services/game_service.py) `evaluate_position`, or change the search strategy in `get_ai_move` (currently scoring + argmax, no minimax).

### Q: Production deployment?

1. Set a strong `SECRET_KEY` (**required**)
2. Replace SQLite with PostgreSQL
3. `uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4` (note: WebSocket state lives in memory; with workers > 1 you need sticky session or Redis)

## Development Conventions

- Routes in `routers/`, split by business domain
- Models in `models/`, Pydantic in `schemas/`
- Business logic in `services/`
- Common helpers in `utils/`
- Frontend JS split by page into `static/js/*.js`
- All backend responses use `ResponseModel[T]` (`schemas/common.py`)

## License

MIT

## Contact

Open an Issue or PR.
