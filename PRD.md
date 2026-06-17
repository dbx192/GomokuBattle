# GomokuBattle 五子棋对战平台 PRD 文档

> 状态：v1.0 · 与代码同步

## 一、产品背景与解决的痛点

| 排名 | 痛点 | 解决方案 |
|------|------|----------|
| 1 | **广告骚扰** — 对弈中弹出广告导致游戏中断判负 | 零广告承诺，纯游戏体验 |
| 2 | **操控差** — 落子位置偏移，误触频发 | Canvas 精确拾取，清晰网格点击 |
| 3 | **匹配不公平** — 新手匹配到高手 | 段位系统 + 房间码邀请 |
| 4 | **功能单一** — 无好友、无法观战 | 房间对战、6 位房间码、链接分享 |
| 5 | **Bug 频发** — 禁手判定错误、闪屏卡顿 | 后端单测 + 前端 Canvas 优化 |
| 6 | **无法悔棋** | AI 模式即时悔棋 · 房间模式需对方 30s 内同意 |
| 7 | **获胜连线不显示** | 醒目红线标注获胜五子 |

## 二、用户画像

- **目标用户**：办公室白领、学生、休闲玩家
- **使用场景**：工作间隙放松、朋友对战、在线匹配
- **核心需求**：快速开始、流畅对战、无广告干扰

## 三、核心功能架构

```
┌──────────────────────────────────────────────────────────┐
│                       GomokuBattle                       │
├──────────────────────────────────────────────────────────┤
│  [首页]     │  [人机对战]  │  [房间对战]  │  [排行榜]    │
│  /          │  /game       │  /room       │  /rankings   │
│             │              │              │              │
│  - 快速入口     │  - 开始对局     │  - 创建/加入房间   │  - 领奖台 Top 3   │
│  - 用户面板     │  - 悔棋/重来    │  - 6位房间码      │  - 完整榜单       │
│  - 模式卡      │  - 最近对局     │  - 历史房间分页    │  - 我的排名高亮   │
│  - 登录注册     │  - 胜负连线     │  - WebSocket 对弈  │  - 自动刷新       │
└──────────────────────────────────────────────────────────┘
```

## 四、页面路由清单

| 路由 | 模板 | 说明 |
|------|------|------|
| `/` | `index.html` | 首页（仪表盘）：用户面板 + 模式卡 + 登录入口 |
| `/game` | `game.html` | 人机对战：Canvas 棋盘 + 控制栏 + 最近对局 |
| `/room` | `room.html` | 房间对战：大厅（创建/加入/列表/历史）+ 对局视图（带倒计时） |
| `/rankings` | `rankings.html` | 排行榜：领奖台 + 完整榜单 + 我的排名 + 30s 自动刷新 |

模板全部继承 `templates/base.html`，通过 `{% block content %}` 注入。

## 五、详细功能需求

### P0 核心功能（已实现）

| # | 功能 | 说明 |
|---|------|------|
| 1 | Canvas 棋盘绘制 | 15×15 标准棋盘，CSS 变量主题（`--ink-dark` / `--gold` / `--jade`） |
| 2 | 落子交互 | 鼠标 hover 提示 + 精确坐标拾取 |
| 3 | 胜负判定 | 横/竖/斜五子连珠，返回 `winning_line` 坐标数组 |
| 4 | 获胜连线 | Canvas 上画红色高亮线，标注获胜五子 |
| 5 | AI 对战 | 评分策略 AI（`GomokuGame.get_ai_move`），自动回应玩家落子 |
| 6 | 房间匹配 | 6 位大写字母+数字房间码 · 5 分钟自动过期 |
| 7 | 实时对战 | WebSocket（`/api/room/ws/{room_id}?token=...`），支持 host/guest 精确寻址 |
| 8 | 房间续接 | `/api/room/current` + URL `?code=` 参数，刷新/重连不丢局 |

### P1 增强功能（已实现）

| # | 功能 | 说明 |
|---|------|------|
| 1 | AI 模式悔棋 | `POST /api/game/ai/undo`，一次性撤销两子（玩家 + AI） |
| 2 | 房间模式悔棋 | 三阶段协议：请求 → 30s 倒计时 → 同意/拒绝/超时 |
| 3 | 落子倒计时 | 房间对局 60s/步，超时自动判负（WebSocket `timeout` 消息） |
| 4 | 段位系统 | `User.rank` 字段，默认 `新手`（未实现自动升降） |
| 5 | 排行榜 | `GET /api/rankings?limit=N`，按 `-wins, -win_rate` 排序 |
| 6 | 领奖台 + 完整榜单 | Top 3 卡片 + 完整表格 + 我的排名高亮 + 30s 自动刷新 |
| 7 | 房间推送线程安全 | `RoomConnectionManager.push_to_host` 通过 `run_coroutine_threadsafe` 从 HTTP 同步线程推送 WS 消息 |

### P2 优化功能（已实现）

| # | 功能 | 说明 |
|---|------|------|
| 1 | 历史对局 | `GET /api/game/history`（AI 模式），`GET /api/room/history`（房间模式，最近 50 条） |
| 2 | 最后落子标记 | Canvas 上画小红圈标记对方最后落子位置 |
| 3 | 房间分享 | 点击房间码 → 复制 `${origin}/room?code=XXXXXX` 链接 |
| 4 | Toastr 通知 | 所有错误/成功操作通过 Toastr 弹出 |
| 5 | 全局 401 处理 | Token 失效自动跳登录 |
| 6 | 静态资源本地化 | bootstrap / jquery / toastr / 字体全部本地化，无 CDN 依赖 |

## 六、技术架构

### 后端

| 组件 | 选型 |
|------|------|
| 框架 | FastAPI 0.115 + Uvicorn 0.34 |
| 实时通信 | WebSocket（`fastapi.WebSocket`） |
| 数据库 | SQLite（`./gomoku.db`） |
| ORM | SQLAlchemy 2.0 |
| 鉴权 | JWT（`python-jose`，HS256，7 天过期） |
| 密码 | bcrypt 4.x（自动截断 72 字节） |
| 模板 | Jinja2 3.1 |
| 配置 | 环境变量（`DATABASE_URL` / `SECRET_KEY`） |

### 前端

| 组件 | 选型 |
|------|------|
| UI 框架 | Bootstrap 5.3（本地化，不再走 CDN） |
| 图标 | Bootstrap Icons 1.11 |
| 交互 | jQuery 3.7 |
| 通知 | Toastr 2.1 |
| 绘图 | HTML5 Canvas |
| 实时 | 原生 WebSocket（带重连） |
| 字体 | 思源宋体/黑体（本地 woff2） |

所有静态资源放在 `static/lib/`、`static/css/`、`static/js/`，模板通过 `{% block scripts %}` 注入页面级 JS。

## 七、API 设计

> 统一响应格式：`{ code: int, message: str, data: T }`
> 统一鉴权：`Authorization: Bearer <jwt>`（除登录/注册外）

### 认证 `/api/auth`

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| POST | `/register` | 否 | 注册（用户名 + 密码）→ 201 + 用户信息 |
| POST | `/login` | 否 | 登录返回 `{ access_token, token_type: "bearer", user }` |
| GET  | `/me` | 是 | 获取当前用户信息 |
| GET  | `/stats` | 是 | 获取当前用户胜/负/总/胜率 |

### 人机对战 `/api/game`

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| POST | `/ai/start` | 是 | 开始新对局，返回 `game_id` + 15×15 + 先手黑 |
| POST | `/ai/move` | 是 | 提交落子 `{ game_id, row, col }`，返回玩家 + AI 落子 |
| POST | `/ai/undo` | 是 | 悔棋（一次性撤销两子） |
| GET  | `/history?page=N&page_size=10` | 是 | 最近对局列表（分页） |

### 房间 `/api/room`

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET  | `/list` | 否 | 等待中的房间列表（公开） |
| GET  | `/history` | 是 | 我参与过的历史房间（最近 50 条） |
| GET  | `/current` | 是 | 当前进行中的房间（用于刷新续接） |
| POST | `/create` | 是 | 创建房间，返回 6 位 `room_code` |
| POST | `/join/{room_code}` | 是 | 加入房间，返回 `room_id` + 棋子颜色 + `game_id` |
| GET  | `/info/{room_id}` | 是 | 房间详情 |
| WS   | `/ws/{room_id}?token=...` | token query | 实时对弈通信 |

### WebSocket 消息协议

| 类型 | 方向 | 负载 |
|------|------|------|
| `player_color` | S→C | `{ color: "black" \| "white" }` |
| `game_state` | S→C | `{ game: {board, moves, current_player}, status }` |
| `opponent_joined` | S→C | `{}` 或 `{ guest_id }` |
| `move` | C→S / S→C | `{ row, col, player, game_over?, winning_line? }` |
| `undo` | C→S | 发起悔棋请求 |
| `undo_sent` | S→C | `{ timeout_sec }`（通知请求方） |
| `undo_request` | S→C | `{ from }`（通知对家） |
| `undo_accept` | C→S | 同意 |
| `undo_decline` | C→S | 拒绝 |
| `undo_declined` | S→C | `{ message }`（通知请求方） |
| `undo_timeout` | S→C | `{ message }`（30s 未回应） |
| `undo` | S→C | `{ row, col, player }`（真正撤销广播） |
| `room_expired` | S→C | `{}`（5 分钟未匹配） |
| `timeout` | C→S / S→C | 落子超时判负 |
| `ping` / `pong` | 双向 | 心跳 |

### 排行榜 `/api/rankings`

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET  | `/?limit=N` | 否 | 排行榜前 N 名（默认 20） |

排序：`(-wins, -win_rate)`

## 八、数据库设计

### users

| 字段 | 类型 | 索引 | 说明 |
|------|------|------|------|
| id | Integer PK | idx | 自增 |
| username | String(50) | unique idx | 用户名 |
| password_hash | String(255) | — | bcrypt 哈希 |
| rank | String(20) | — | 段位（默认 `新手`） |
| wins | Integer | — | 胜场 |
| losses | Integer | — | 负场 |
| created_at | DateTime | — | 注册时间（UTC） |

### rooms

| 字段 | 类型 | 索引 | 说明 |
|------|------|------|------|
| id | Integer PK | idx | 自增 |
| room_code | String(10) | unique idx | 6 位房间码（大写字母+数字） |
| host_id | Integer FK→users.id | — | 房主 |
| guest_id | Integer FK→users.id NULL | — | 客人（waiting 时为空） |
| status | String(20) | — | `waiting` / `playing` / `completed` / `expired` |
| game_record_id | Integer FK→game_records.id NULL | — | 关联的对局 |
| created_at | DateTime | — | 创建时间（用于 5 分钟过期判断） |

### game_records

| 字段 | 类型 | 索引 | 说明 |
|------|------|------|------|
| id | Integer PK | idx | 自增 |
| player1_id | Integer FK→users.id | — | 黑棋 |
| player2_id | Integer FK→users.id NULL | — | 白棋（AI 模式为空） |
| winner_id | Integer FK→users.id NULL | — | 赢家（AI 模式赢时为玩家，AI 赢时为 NULL） |
| moves | JSON | — | `[[row, col, player], ...]` |
| game_type | String(20) | — | `ai` / `room` |
| status | String(20) | — | `in_progress` / `completed` |
| created_at | DateTime | — | 开始时间 |
| ended_at | DateTime NULL | — | 结束时间（暂未使用） |

## 九、关键业务规则

1. **房间过期**：创建后 5 分钟内无客人加入 → 状态置 `expired`，WebSocket 推送 `room_expired`（启动时 `cleanup_expired_rooms` 任务每 10s 扫描）
2. **悔棋三阶段**：发起方发 `undo` → 30s 内对家回 `undo_accept`/`undo_decline`，超时自动拒绝
3. **落子超时**：60s 内未落子 → 客户端自动发 `timeout` → 服务端判负
4. **页面刷新续接**：通过 `/api/room/current` + URL `?code=...` 重新绑定 WebSocket，状态从 `game_records.moves` 恢复
5. **断线取消悔棋**：请求方断线时自动 `clear_pending_undo`，避免对家弹窗干等
6. **AI 即时悔棋**：无对家协议，直接撤销最后两子（玩家 + AI）
7. **排行榜实时**：可选 30s 自动刷新（前端开关）
8. **房间推送线程安全**：`join_room` 同步端点用 `run_coroutine_threadsafe` 推送 WS 消息到主事件循环

## 十、UI 规范

- **配色**：墨黑底（`--ink-dark` / `#0f1419`）+ 金色点缀（`--gold` / `#d4a574`）+ 翡翠绿（`--jade`）强调
- **字体**：标题用思源宋体（`--font-display`），数字/代码用等宽（`--font-mono`）
- **棋盘**：640×640 Canvas，背景木纹渐变（CSS 渐变模拟）
- **响应式**：Bootstrap Grid，棋盘最大 800px，1080P/2K/4K 自适应
- **无 Tailwind**：纯 Bootstrap 5 + 手写 CSS 变量

## 十一、未实现 / 后续规划

- 段位自动升降（基于胜率阈值）
- 观战模式（observer 角色已预留 `attach` 路径，未对外开放）
- AI 难度选择（当前固定评分策略）
- 实时聊天 / 表情
- 移动端适配
