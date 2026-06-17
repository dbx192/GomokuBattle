# GomokuBattle — 五子棋对战平台

一个基于 FastAPI 的在线五子棋对战平台，支持人机对战和双人实时房间对战，零广告、纯游戏体验。

## 功能特性

- **人机对战** — 评分策略 AI，Canvas 棋盘，悔棋/重来
- **房间对战** — 6 位房间码、链接分享、5 分钟自动过期
- **实时通信** — WebSocket，host/guest 精确寻址，自动重连
- **房间续接** — 页面刷新不丢局，进度从 `game_records.moves` 恢复
- **悔棋协议** — AI 即时撤销，房间模式三阶段（请求/同意/拒绝，30s 超时）
- **落子倒计时** — 房间模式 60s/步，超时判负
- **排行榜** — Top 3 领奖台 + 完整榜单 + 我的排名高亮 + 30s 自动刷新
- **历史对局** — AI 模式分页列表 + 房间模式分页列表
- **统一鉴权** — JWT（HS256，7 天过期），前端 401 自动跳登录
- **零广告** — 纯净对弈体验
- **PC 响应式** — Bootstrap 5 Grid，1080P/2K/4K 自适应

## 技术栈

| 层 | 技术 |
|----|------|
| 后端框架 | FastAPI 0.115 + Uvicorn 0.34 |
| ORM | SQLAlchemy 2.0 |
| 数据库 | SQLite（`./gomoku.db`） |
| 鉴权 | JWT（`python-jose`，HS256） |
| 密码 | bcrypt 4.x（自动截断 72 字节） |
| 实时通信 | WebSocket（`fastapi.WebSocket`） |
| 模板 | Jinja2 3.1 |
| 前端 UI | Bootstrap 5.3 + Bootstrap Icons 1.11（本地化） |
| 前端交互 | jQuery 3.7 + Toastr 2.1 |
| 棋盘绘图 | HTML5 Canvas |

## 项目结构

```
GomokuBattle/
├── main.py                  # 应用入口：注册路由 + 启动清理任务 + 全局异常兜底
├── config.py                # 配置：DATABASE_URL / SECRET_KEY / 过期时间
├── database.py              # SQLAlchemy 引擎 + SessionLocal + Base + get_db + init_db
├── seed_users.py            # 一键生成 5 个测试账号
│
├── models/                  # SQLAlchemy ORM 模型
│   ├── user.py              #   User: 用户表
│   ├── room.py              #   Room: 房间表
│   └── game.py              #   GameRecord: 对局记录表
│
├── routers/                 # FastAPI 路由
│   ├── auth.py              #   /api/auth/*     注册/登录/me/stats
│   ├── game.py              #   /api/game/*     AI 对战（start/move/undo/history）
│   ├── room.py              #   /api/room/*     房间 + WebSocket
│   └── ranking.py           #   /api/rankings   排行榜
│
├── schemas/                 # Pydantic 模型
│   ├── common.py            #   ResponseModel[T] / ListData[T]
│   ├── user.py              #   UserCreate / UserLogin / UserResponse / UserStats
│   └── game.py              #   MoveRequest / MoveResponse / GameStartResponse / ...
│
├── services/
│   └── game_service.py      #   GomokuGame：棋盘逻辑 + AI 评分 + 胜负判定
│
├── utils/
│   └── auth.py              #   bcrypt + JWT + get_current_user + decode_token
│
├── templates/               # Jinja2 模板
│   ├── base.html            #   基础布局：navbar + 登录弹窗 + 脚本插槽
│   ├── index.html           #   /  首页
│   ├── game.html            #   /game  人机对战
│   ├── room.html            #   /room  房间对战
│   ├── rankings.html        #   /rankings  排行榜
│   └── partials/
│       ├── _navbar.html     #     共用导航栏
│       └── _auth_modals.html#     登录/注册弹窗
│
├── static/
│   ├── css/main.css         #   全局样式（CSS 变量主题）
│   ├── js/
│   │   ├── main.js          #     API 封装 + 全局 401 处理
│   │   ├── game.js          #     /game 页面逻辑
│   │   ├── room.js          #     /room 页面逻辑（WebSocket + 倒计时 + 悔棋协议）
│   │   └── rankings.js      #     /rankings 页面逻辑
│   └── lib/                 #   本地化的第三方库（bootstrap / jquery / toastr / 字体）
│
├── PRD.md                   # 产品需求文档（中文）
├── README.md                # 本文件
├── requirements.txt         # Python 依赖
└── .gitignore
```

## 快速开始

### 1. 安装依赖

```bash
cd GomokuBattle
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

### 2. 启动服务

```bash
# 方式 A：直接运行
python main.py

# 方式 B：uvicorn（推荐用于开发）
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

默认端口 `8000`，监听 `0.0.0.0`（`main.py:118`）。

### 3. 一键生成测试账号（可选）

```bash
# 确保服务已启动，再开一个终端
python seed_users.py
```

会创建 5 个测试账号：`alice / alice123`、`bob / bob123`、`charlie / charlie123`、`diana / diana123`、`evan / evan123`。

### 4. 访问

| 页面 | URL |
|------|-----|
| 首页 | <http://127.0.0.1:8000/> |
| 人机对战 | <http://127.0.0.1:8000/game> |
| 房间对战 | <http://127.0.0.1:8000/room> |
| 排行榜 | <http://127.0.0.1:8000/rankings> |
| API 文档 | <http://127.0.0.1:8000/docs> |

## 配置

通过环境变量覆盖默认值（[config.py](file:///d:/ProjectsPython/GomokuBattle/config.py)）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | `sqlite:///./gomoku.db` | SQLAlchemy 连接串 |
| `DB_POOL_MIN` | `5` | 预留给生产环境的最小连接池参数占位 |
| `DB_POOL_MAX` | `100` | PostgreSQL 连接池大小 |
| `DB_POOL_TIMEOUT` | `30` | 获取数据库连接的超时时间（秒） |
| `DB_COMMAND_TIMEOUT` | `30` | PostgreSQL 单条语句超时（秒） |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 连接串 |
| `REDIS_ENABLED` | `false` | 是否启用 Redis 状态存储 |
| `LOGIN_RATE_LIMIT_MAX_ATTEMPTS` | `5` | 登录失败最大尝试次数 |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `300` | 登录失败限流窗口（秒） |
| `SECRET_KEY` | `gomoku-battle-secret-key-change-in-production` | JWT 签名密钥（**生产必须改**） |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `10080`（7 天） | JWT 过期时间 |

## API 速查

> 统一响应：`{ code: 200, message: "success", data: T }`
> 鉴权：`Authorization: Bearer <jwt>`（除登录/注册外）

### 认证 `/api/auth`

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| POST | `/register` | — | `{ username, password }` → 201 + 用户信息 |
| POST | `/login` | — | `{ username, password }` → `{ access_token, token_type, user }` |
| GET  | `/me` | ✓ | 当前用户信息 |
| GET  | `/stats` | ✓ | `{ wins, losses, total, win_rate }` |

### 人机对战 `/api/game`

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| POST | `/ai/start` | ✓ | 返回 `{ game_id, board_size: 15, first_player: "black" }` |
| POST | `/ai/move` | ✓ | `{ game_id, row, col }` → `{ player_move, ai_move, game_over? }` |
| POST | `/ai/undo` | ✓ | `{ game_id }` 一次性撤销两子 |
| GET  | `/history?page=1&page_size=10` | ✓ | 我的对局记录（分页） |

### 房间 `/api/room`

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET  | `/list` | — | 等待中的房间 |
| GET  | `/history` | ✓ | 我参与过的历史房间（最近 50 条） |
| GET  | `/current` | ✓ | 当前进行中的房间（用于刷新续接） |
| POST | `/create` | ✓ | 返回 `{ id, room_code, expires_at }` |
| POST | `/join/{room_code}` | ✓ | 返回 `{ room_id, game_id, player_color, ... }` |
| GET  | `/info/{room_id}` | ✓ | 房间详情 |
| WS   | `/ws/{room_id}?token=...` | query | 实时对弈（见下方协议） |

### 排行榜 `/api/rankings`

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET  | `/?limit=20` | — | 前 N 名（按 `-wins, -win_rate` 排序） |

## WebSocket 协议

连接：`/api/room/ws/{room_id}?token=<jwt>`

| 类型 | 方向 | 说明 |
|------|------|------|
| `player_color` | S→C | `{ color: "black" \| "white" }` |
| `game_state` | S→C | `{ game: {board, moves, current_player}, status }` |
| `opponent_joined` | S→C | `{}` / `{ guest_id }` |
| `move` | C→S / S→C | `{ row, col, player, game_over?, winning_line? }` |
| `undo` | C→S | 发起悔棋请求 |
| `undo_sent` | S→C | `{ timeout_sec }`（通知请求方） |
| `undo_request` | S→C | `{ from }`（通知对家，30s 倒计时） |
| `undo_accept` / `undo_decline` | C→S | 同意 / 拒绝 |
| `undo_declined` | S→C | `{ message }` |
| `undo_timeout` | S→C | `{ message }`（30s 自动撤回） |
| `undo` | S→C | `{ row, col, player }`（真正撤销广播） |
| `room_expired` | S→C | 5 分钟未匹配 |
| `timeout` | C→S / S→C | 60s 落子超时判负 |
| `ping` / `pong` | 双向 | 心跳 |

## 业务规则

1. **房间过期** — 创建后 5 分钟内无客人 → 状态 `expired`，推 `room_expired`（启动时 `cleanup_expired_rooms` 任务每 10s 扫描）
2. **悔棋协议** — 发起方发 `undo` → 30s 内对家 `undo_accept` / `undo_decline`，超时自动拒绝
3. **落子超时** — 60s 内未落子 → 客户端自动发 `timeout` → 服务端判负
4. **页面刷新续接** — `/api/room/current` + URL `?code=...` 重新绑定 WebSocket，从 `game_records.moves` 恢复
5. **断线取消悔棋** — 请求方断线时自动 `clear_pending_undo`
6. **AI 即时悔棋** — 无对家协议，直接撤销最后两子
7. **排行榜** — 前端可选 30s 自动刷新
8. **房间推送** — `join_room` 同步端点用 `push_to_host` 线程安全推送 `opponent_joined` + `game_state`

## 数据库

启动时自动创建数据库表（`database.init_db`），推荐生产使用 PostgreSQL：

- `users` — 用户
- `rooms` — 房间（带 6 位 `room_code` 唯一索引）
- `game_records` — 对局记录（`moves` 为 JSON）

## 常见问题

### Q: 切换数据库？

修改 `DATABASE_URL` 环境变量，例如 PostgreSQL：

```bash
export DATABASE_URL="postgresql://user:pass@localhost/gomoku"
```

`database.py` 会自动识别数据库类型：`sqlite` 才传 `check_same_thread=False`，`postgresql` 会启用连接池和 `statement_timeout`。

### Q: Redis 现在做什么？

- `AI` 对局状态存 Redis，服务重启后只要 Redis 还在，未结束棋局不会丢
- 房间实时对局状态存 Redis，避免多进程/单实例重启时直接丢盘面
- 房间悔棋请求也存 Redis，避免请求状态只留在单个 worker 内存里
- 登录限流也走 Redis，默认同一 `用户名 + IP` 在 `300s` 内最多失败 `5` 次

### Q: 调整 JWT 过期？

```bash
export ACCESS_TOKEN_EXPIRE_MINUTES=1440   # 24 小时
```

### Q: AI 难度？

修改 [services/game_service.py](file:///d:/ProjectsPython/GomokuBattle/services/game_service.py) 中的 `evaluate_position` 评分函数权重，或调整 `get_ai_move` 的搜索策略（目前是评分 + 取最大，未做 minimax 搜索）。

### Q: 部署到生产？

1. 设置强 `SECRET_KEY`（**必须**）
2. 配置 `DATABASE_URL` 指向 PostgreSQL
3. 配置 `REDIS_URL` 并开启 `REDIS_ENABLED=true`
4. 运行 `uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4`
5. WebSocket 连接本身仍是单连接绑定单 worker，但棋局状态已经迁到 Redis，不会因 worker 切换或进程重启直接丢失

## 开发规范

- 路由放 `routers/`，按业务拆分
- 模型放 `models/`，Pydantic 放 `schemas/`
- 业务逻辑放 `services/`
- 通用工具放 `utils/`
- 前端 JS 按页面拆分到 `static/js/*.js`
- 后端响应统一用 `ResponseModel[T]`（`schemas/common.py`）

## 许可证

MIT

## 联系方式

提 Issue 或 PR。
