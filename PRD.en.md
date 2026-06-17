# GomokuBattle — Product Requirements Document (PRD)

> Version: v1.0 · In sync with the codebase

## 1. Background & Pain Points

| # | Pain Point | Solution |
|---|------------|----------|
| 1 | **Ad spam** — Pop-up ads interrupt play and cause losses | Zero-ads promise, pure gameplay |
| 2 | **Poor control** — Misaligned drop positions and accidental clicks | Precise Canvas hit-testing, clear grid clicks |
| 3 | **Unfair matching** — Newbies get matched against experts | Rank system + invite-only room codes |
| 4 | **Limited features** — No friends, no spectating | Room matches, 6-char room codes, link sharing |
| 5 | **Frequent bugs** — Forbidden-move errors, flicker, lag | Backend unit tests + frontend Canvas optimization |
| 6 | **No undo** | AI mode: instant undo · Room mode: requires opponent's 30s consent |
| 7 | **No win-line highlight** | Red highlight line on the winning 5 stones |

## 2. User Personas

- **Target users**: Office workers, students, casual players
- **Use cases**: Break-time relaxation, playing with friends, online matching
- **Core needs**: Quick start, smooth play, no ad distractions

## 3. Core Feature Architecture

```
┌──────────────────────────────────────────────────────────┐
│                       GomokuBattle                       │
├──────────────────────────────────────────────────────────┤
│  [Home]      │  [AI Match]   │  [Room Match] │  [Rank]   │
│  /           │  /game        │  /room        │  /rankings│
│              │               │               │           │
│  - Quick entries│  - Start match  │  - Create/Join    │  - Top 3 podium   │
│  - User panel│  - Undo/Restart│  - 6-char code    │  - Full leaderboard│
│  - Mode cards│  - Recent games│  - History (paged)│  - My rank highlight│
│  - Login/Reg │  - Win line    │  - WebSocket play │  - Auto-refresh    │
└──────────────────────────────────────────────────────────┘
```

## 4. Page Routes

| Route | Template | Description |
|-------|----------|-------------|
| `/` | `index.html` | Home (dashboard): user panel + mode cards + login entry |
| `/game` | `game.html` | AI match: Canvas board + controls + recent matches |
| `/room` | `room.html` | Room match: lobby (create/join/list/history) + battle view (with timer) |
| `/rankings` | `rankings.html` | Leaderboard: podium + full table + my rank + 30s auto-refresh |

All templates extend `templates/base.html` and inject via `{% block content %}`.

## 5. Detailed Feature Requirements

### P0 — Core (Implemented)

| # | Feature | Description |
|---|---------|-------------|
| 1 | Canvas board rendering | Standard 15×15 board, CSS variable theme (`--ink-dark` / `--gold` / `--jade`) |
| 2 | Move interaction | Hover hint + precise coordinate pick |
| 3 | Win detection | Horizontal/vertical/diagonal five-in-a-row, returns `winning_line` array |
| 4 | Win line | Red highlight line drawn on Canvas for the winning 5 stones |
| 5 | AI match | Heuristic scoring AI (`GomokuGame.get_ai_move`), auto-responds to player moves |
| 6 | Room matching | 6-char uppercase alphanumeric room code · 5-min auto-expiry |
| 7 | Real-time play | WebSocket (`/api/room/ws/{room_id}?token=...`), precise host/guest addressing |
| 8 | Room resume | `/api/room/current` + URL `?code=` query, refresh/reconnect doesn't lose state |

### P1 — Enhancements (Implemented)

| # | Feature | Description |
|---|---------|-------------|
| 1 | AI mode undo | `POST /api/game/ai/undo`, roll back two stones at once (player + AI) |
| 2 | Room mode undo | 3-phase protocol: request → 30s countdown → accept/decline/timeout |
| 3 | Move countdown | 60s per move in room mode, auto-loss on timeout (WS `timeout` message) |
| 4 | Rank system | `User.rank` field, default `新手` (auto promotion/demotion not implemented) |
| 5 | Leaderboard | `GET /api/rankings?limit=N`, sorted by `-wins, -win_rate` |
| 6 | Podium + full table | Top 3 cards + full table + my rank highlight + 30s auto-refresh |
| 7 | Thread-safe room push | `RoomConnectionManager.push_to_host` uses `run_coroutine_threadsafe` to push WS messages from HTTP sync thread |

### P2 — Optimizations (Implemented)

| # | Feature | Description |
|---|---------|-------------|
| 1 | Match history | `GET /api/game/history` (AI), `GET /api/room/history` (room, most recent 50) |
| 2 | Last-move marker | Small red circle on Canvas marking opponent's last move |
| 3 | Room sharing | Click room code → copy `${origin}/room?code=XXXXXX` link |
| 4 | Toastr notifications | All errors/successes use Toastr |
| 5 | Global 401 handler | Invalid token auto-redirects to login |
| 6 | Localized static assets | bootstrap / jquery / toastr / fonts all local, no CDN dependency |

## 6. Technical Architecture

### Backend

| Component | Choice |
|-----------|--------|
| Framework | FastAPI 0.115 + Uvicorn 0.34 |
| Real-time | WebSocket (`fastapi.WebSocket`) |
| Database | SQLite (`./gomoku.db`) |
| ORM | SQLAlchemy 2.0 |
| Auth | JWT (`python-jose`, HS256, 7-day expiry) |
| Password | bcrypt 4.x (auto-truncated to 72 bytes) |
| Template | Jinja2 3.1 |
| Config | Env vars (`DATABASE_URL` / `SECRET_KEY`) |

### Frontend

| Component | Choice |
|-----------|--------|
| UI Framework | Bootstrap 5.3 (localized, no CDN) |
| Icons | Bootstrap Icons 1.11 |
| Interactivity | jQuery 3.7 |
| Notifications | Toastr 2.1 |
| Rendering | HTML5 Canvas |
| Real-time | Native WebSocket (with reconnect) |
| Fonts | Source Han Serif/Sans (local woff2) |

All static assets live in `static/lib/`, `static/css/`, `static/js/`; templates inject page-level JS via `{% block scripts %}`.

## 7. API Design

> Unified response: `{ code: int, message: str, data: T }`
> Unified auth: `Authorization: Bearer <jwt>` (except login/register)

### Auth `/api/auth`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/register` | No | Register (username + password) → 201 + user info |
| POST | `/login` | No | Returns `{ access_token, token_type: "bearer", user }` |
| GET  | `/me` | Yes | Get current user info |
| GET  | `/stats` | Yes | Get current user wins/losses/total/win-rate |

### AI Match `/api/game`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/ai/start` | Yes | Start a new match, returns `game_id` + 15×15 + black first |
| POST | `/ai/move` | Yes | Submit move `{ game_id, row, col }`, returns player + AI moves |
| POST | `/ai/undo` | Yes | Undo (rolls back two stones at once) |
| GET  | `/history?page=N&page_size=10` | Yes | Recent matches (paginated) |

### Room `/api/room`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET  | `/list` | No | Waiting room list (public) |
| GET  | `/history` | Yes | Rooms I joined (most recent 50) |
| GET  | `/current` | Yes | My active room (for refresh-resume) |
| POST | `/create` | Yes | Create room, returns 6-char `room_code` |
| POST | `/join/{room_code}` | Yes | Join room, returns `room_id` + piece color + `game_id` |
| GET  | `/info/{room_id}` | Yes | Room details |
| WS   | `/ws/{room_id}?token=...` | token query | Real-time play |

### WebSocket Message Protocol

| Type | Direction | Payload |
|------|-----------|---------|
| `player_color` | S→C | `{ color: "black" \| "white" }` |
| `game_state` | S→C | `{ game: {board, moves, current_player}, status }` |
| `opponent_joined` | S→C | `{}` or `{ guest_id }` |
| `move` | C→S / S→C | `{ row, col, player, game_over?, winning_line? }` |
| `undo` | C→S | Send undo request |
| `undo_sent` | S→C | `{ timeout_sec }` (notify requester) |
| `undo_request` | S→C | `{ from }` (notify opponent) |
| `undo_accept` | C→S | Accept |
| `undo_decline` | C→S | Decline |
| `undo_declined` | S→C | `{ message }` (notify requester) |
| `undo_timeout` | S→C | `{ message }` (no response within 30s) |
| `undo` | S→C | `{ row, col, player }` (real rollback broadcast) |
| `room_expired` | S→C | `{}` (5 min without match) |
| `timeout` | C→S / S→C | Move timeout = loss |
| `ping` / `pong` | both | Heartbeat |

### Rankings `/api/rankings`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET  | `/?limit=N` | No | Top N leaderboard (default 20) |

Sort: `(-wins, -win_rate)`

## 8. Database Design

### users

| Field | Type | Index | Description |
|-------|------|-------|-------------|
| id | Integer PK | idx | Auto-increment |
| username | String(50) | unique idx | Username |
| password_hash | String(255) | — | bcrypt hash |
| rank | String(20) | — | Rank (default `新手`) |
| wins | Integer | — | Wins |
| losses | Integer | — | Losses |
| created_at | DateTime | — | Registration time (UTC) |

### rooms

| Field | Type | Index | Description |
|-------|------|-------|-------------|
| id | Integer PK | idx | Auto-increment |
| room_code | String(10) | unique idx | 6-char room code (uppercase alphanumeric) |
| host_id | Integer FK→users.id | — | Host |
| guest_id | Integer FK→users.id NULL | — | Guest (NULL when waiting) |
| status | String(20) | — | `waiting` / `playing` / `completed` / `expired` |
| game_record_id | Integer FK→game_records.id NULL | — | Linked match |
| created_at | DateTime | — | Creation time (used for 5-min expiry check) |

### game_records

| Field | Type | Index | Description |
|-------|------|-------|-------------|
| id | Integer PK | idx | Auto-increment |
| player1_id | Integer FK→users.id | — | Black |
| player2_id | Integer FK→users.id NULL | — | White (NULL in AI mode) |
| winner_id | Integer FK→users.id NULL | — | Winner (AI mode: player wins → player.id, AI wins → NULL) |
| moves | JSON | — | `[[row, col, player], ...]` |
| game_type | String(20) | — | `ai` / `room` |
| status | String(20) | — | `in_progress` / `completed` |
| created_at | DateTime | — | Start time |
| ended_at | DateTime NULL | — | End time (currently unused) |

## 9. Key Business Rules

1. **Room expiry** — If no guest joins within 5 min → status `expired`, WS pushes `room_expired` (startup `cleanup_expired_rooms` task scans every 10s)
2. **Undo 3-phase** — Requester sends `undo` → opponent replies `undo_accept` / `undo_decline` within 30s; timeout = auto-decline
3. **Move timeout** — No move within 60s → client auto-emits `timeout` → server declares loss
4. **Page refresh resume** — Use `/api/room/current` + URL `?code=...` to re-bind WebSocket; state rebuilt from `game_records.moves`
5. **Disconnect cancels undo** — When requester disconnects, auto `clear_pending_undo` to avoid stuck opponent prompt
6. **AI instant undo** — No opponent protocol; rolls back the last two stones (player + AI)
7. **Live rankings** — Optional 30s auto-refresh (frontend toggle)
8. **Thread-safe room push** — `join_room` sync endpoint uses `run_coroutine_threadsafe` to push WS messages onto the main event loop

## 10. UI Specification

- **Palette**: Ink black base (`--ink-dark` / `#0f1419`) + gold accent (`--gold` / `#d4a574`) + jade (`--jade`) for emphasis
- **Fonts**: Headings use Source Han Serif (`--font-display`); numbers/code use monospace (`--font-mono`)
- **Board**: 640×640 Canvas with wood-grain gradient (CSS gradient simulation)
- **Responsive**: Bootstrap Grid, board max 800px, auto-adapts to 1080P/2K/4K
- **No Tailwind**: Pure Bootstrap 5 + hand-written CSS variables

## 11. Not Yet Implemented / Future Roadmap

- Auto rank promotion/demotion (based on win-rate thresholds)
- Spectator mode (observer role path is reserved in `attach`, not exposed publicly)
- AI difficulty selector (currently fixed heuristic)
- Real-time chat / emoji
- Mobile adaptation
