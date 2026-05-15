# GomokuBattle - 五子棋对战平台

一个基于 FastAPI 的在线五子棋对战平台，支持人机对战和双人在线对战。

## 功能特性

- 用户注册与登录（JWT 认证）
- 人机对战（智能 AI 对手）
- 房间对战（双人实时对战）
- 实时排行榜
- 悔棋功能
- 响应式设计，支持多设备访问
- WebSocket 实时通信
- 精美的 UI 界面

## 技术栈

### 后端
- FastAPI - 现代化的 Python Web 框架
- SQLAlchemy - ORM 数据库操作
- SQLite - 轻量级数据库
- WebSocket - 实时双向通信
- JWT - 用户身份验证
- Passlib - 密码加密

### 前端
- Bootstrap 5 - 响应式 UI 框架
- jQuery - JavaScript 库
- HTML5 Canvas - 棋盘绘制
- FontAwesome - 图标库
- Toastr - 消息提示

## 项目结构

```
GomokuBattle/
├── models/              # 数据模型
│   ├── user.py         # 用户模型
│   ├── game.py         # 游戏记录模型
│   └── room.py         # 房间模型
├── routers/            # 路由处理
│   ├── auth.py         # 认证路由
│   ├── game.py         # 游戏路由
│   ├── room.py         # 房间路由
│   └── ranking.py      # 排行榜路由
├── schemas/            # Pydantic 模型
│   ├── common.py       # 通用模型
│   ├── game.py         # 游戏模型
│   └── user.py         # 用户模型
├── services/           # 业务逻辑
│   └── game_service.py # 五子棋游戏逻辑
├── utils/              # 工具函数
│   └── auth.py         # 认证工具
├── static/             # 静态资源
│   ├── css/            # 样式文件
│   ├── html/           # HTML 页面
│   └── js/             # JavaScript 文件
├── main.py             # 应用入口
├── database.py         # 数据库配置
├── config.py           # 配置文件
├── requirements.txt    # 依赖包
└── README.md           # 项目文档
```

## 安装步骤

### 1. 克隆项目

```bash
git clone <repository-url>
cd GomokuBattle
```

### 2. 创建虚拟环境

```bash
python -m venv venv
```

### 3. 激活虚拟环境

Windows:
```bash
venv\Scripts\activate
```

Linux/Mac:
```bash
source venv/bin/activate
```

### 4. 安装依赖

```bash
pip install -r requirements.txt
```

## 运行方法

### 启动服务器

```bash
python main.py
```

或使用 uvicorn：

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### 访问应用

- 首页: http://127.0.0.1:8000
- 人机对战: http://127.0.0.1:8000/game
- 房间对战: http://127.0.0.1:8000/room
- API 文档: http://127.0.0.1:8000/docs

## 使用说明

### 用户注册与登录

1. 访问首页，点击"注册"按钮
2. 填写用户名、密码和邮箱
3. 注册成功后使用用户名和密码登录

### 人机对战

1. 登录后进入"人机对战"页面
2. 点击棋盘交叉点落子（黑棋先手）
3. AI 会自动回应
4. 可点击"请求悔棋"撤销上一步

### 房间对战

1. 进入"房间对战"页面
2. 创建房间或加入已有房间
3. 复制房间链接分享给好友
4. 好友点击链接自动加入房间
5. 双方都进入后游戏开始

### 排行榜

- 查看所有用户的胜场数和败场数
- 按胜场数排序

## API 接口

### 认证接口

- `POST /api/auth/register` - 用户注册
- `POST /api/auth/login` - 用户登录
- `GET /api/auth/me` - 获取当前用户信息

### 游戏接口

- `POST /api/game/ai/move` - AI 落子
- `POST /api/game/ai/undo` - AI 悔棋

### 房间接口

- `POST /api/room/create` - 创建房间
- `POST /api/room/join/{room_code}` - 加入房间
- `GET /api/room/info/{room_id}` - 获取房间信息
- `GET /api/room/list` - 获取房间列表
- `WS /api/room/ws/{room_id}` - WebSocket 连接

### 排行榜接口

- `GET /api/ranking` - 获取排行榜

## WebSocket 消息格式

### 客户端发送

```json
{
  "type": "move",
  "row": 7,
  "col": 7
}
```

```json
{
  "type": "undo"
}
```

### 服务器发送

```json
{
  "type": "player_color",
  "color": "black"
}
```

```json
{
  "type": "opponent_joined"
}
```

```json
{
  "type": "game_state",
  "game": {
    "board": [[...]],
    "moves": [...],
    "current_player": 1
  },
  "status": "playing"
}
```

```json
{
  "type": "move",
  "row": 7,
  "col": 7,
  "player": "black",
  "game_over": false
}
```

```json
{
  "type": "undo",
  "row": 7,
  "col": 7,
  "player": "black"
}
```

## 开发说明

### 数据库初始化

数据库会在首次运行时自动创建，包含以下表：

- users - 用户表
- game_records - 游戏记录表
- rooms - 房间表

### 添加新功能

1. 在 `models/` 中定义数据模型
2. 在 `schemas/` 中定义 Pydantic 模型
3. 在 `routers/` 中实现路由
4. 在 `services/` 中实现业务逻辑
5. 在 `static/` 中添加前端页面和资源

### 代码规范

- 遵循 PEP 8 代码规范
- 使用类型注解
- 编写清晰的注释
- 保持函数简洁

## 常见问题

### Q: 如何修改服务器端口？

A: 修改 `main.py` 中的 `uvicorn.run(app, host="0.0.0.0", port=8000)` 或使用命令行参数 `--port`。

### Q: 如何更换数据库？

A: 修改 `database.py` 中的 `SQLALCHEMY_DATABASE_URL` 配置。

### Q: AI 难度可以调整吗？

A: 可以在 `services/game_service.py` 中调整 AI 的评估函数参数。

## 贡献指南

欢迎提交 Issue 和 Pull Request！

## 许可证

MIT License

## 联系方式

如有问题，请提交 Issue 或联系开发者。

---

祝您游戏愉快！