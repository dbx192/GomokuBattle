const BOARD_SIZE = 15;
const CELL_SIZE = 40;
const PADDING = 20;
const PIECE_RADIUS = 16;

let canvas, ctx;
let roomId = null;
let gameId = null;
let playerColor = null;
let board = Array(BOARD_SIZE).fill(null).map(() => Array(BOARD_SIZE).fill(null));
let currentPlayer = 'black';
let isMyTurn = false;
let gameOver = false;
let winningLine = null;
let lastMove = null;
let ws = null;
let gameStarted = false;

let roomListInterval = null;
let roomCheckInterval = null;
let roomExpireTime = null;
let roomCountdownInterval = null;
let turnTimerInterval = null;
let turnTimeLeft = 60;
const TURN_TIME_LIMIT = 60;
const ROOM_EXPIRY_MS = 5 * 60 * 1000;

$(function() {
    canvas = document.getElementById('gameCanvas');
    ctx = canvas.getContext('2d');

    canvas.width = BOARD_SIZE * CELL_SIZE + PADDING * 2;
    canvas.height = BOARD_SIZE * CELL_SIZE + PADDING * 2;

    canvas.addEventListener('click', handleClick);

    $('#createRoomBtn').on('click', createRoom);
    $('#joinRoomBtn').on('click', joinRoom);
    $('#undoBtn').on('click', requestUndo);
    $('#leaveRoomBtn').on('click', leaveRoom);
    $('#shareHint').on('click', shareRoom);
    $('#shareHint2').on('click', shareRoom);
    $('#tab-history-btn').on('shown.bs.tab', loadHistoryList);

    drawBoard();
    loadRoomList();
    loadHistoryList();
    roomListInterval = setInterval(loadRoomList, 5000);

    checkAuth();
});

function checkAuth() {
    const token = localStorage.getItem('access_token');
    if (!token) {
        showAuthNav(null);
        toastr.warning('请先登录后再加入房间');
        return;
    }

    API.get('/api/auth/me')
        .done(res => {
            if (res.code === 200) {
                const user = res.data;
                showAuthNav(user);

                const urlParams = new URLSearchParams(window.location.search);
                const roomCode = urlParams.get('code');
                if (roomCode) {
                    $('#joinRoomCode').val(roomCode.toUpperCase());
                    joinRoom();
                }
            } else {
                showAuthNav(null);
            }
        })
        .fail(xhr => {
            showAuthNav(null);
            const status = xhr.status;
            if (status === 401 || status === 403) {
                localStorage.removeItem('access_token');
                localStorage.removeItem('user');
                toastr.error('登录已失效，请重新登录');
            }
        });
}

function showAuthNav(user) {
    const $nav = $('#authNav');
    if (!$nav.length) return;
    if (user && user.username) {
        $nav.html(`
            <li class="nav-item dropdown">
                <a class="nav-link dropdown-toggle" href="#" data-bs-toggle="dropdown">
                    <i class="bi bi-person-circle"></i> ${user.username}
                </a>
                <ul class="dropdown-menu dropdown-menu-end">
                    <li><a class="dropdown-item" href="/"><i class="bi bi-house"></i> 首页</a></li>
                    <li><hr class="dropdown-divider"></li>
                    <li><a class="dropdown-item" href="#" id="logoutBtn"><i class="bi bi-box-arrow-right"></i> 退出</a></li>
                </ul>
            </li>
        `);
        $('#logoutBtn').on('click', e => {
            e.preventDefault();
            localStorage.removeItem('access_token');
            localStorage.removeItem('user');
            location.href = '/';
        });
    } else {
        $nav.html(`
            <li class="nav-item">
                <a class="nav-link" href="/">
                    <i class="bi bi-box-arrow-in-right"></i> 前往登录
                </a>
            </li>
        `);
    }
}

function stopRoomListPolling() {
    if (roomListInterval) {
        clearInterval(roomListInterval);
        roomListInterval = null;
    }
}

function startRoomExpiryCheck(expiresAt) {
    stopRoomExpiryCheck();
    if (expiresAt) {
        roomExpireTime = expiresAt;
    } else {
        roomExpireTime = Date.now() + ROOM_EXPIRY_MS;
    }

    $('#expiryCountdown').show();

    if (roomCountdownInterval) clearInterval(roomCountdownInterval);
    roomCountdownInterval = setInterval(() => {
        if (!roomExpireTime || gameStarted) {
            clearInterval(roomCountdownInterval);
            roomCountdownInterval = null;
            $('#expiryCountdown').hide();
            return;
        }
        const remaining = Math.max(0, roomExpireTime - Date.now());
        const mins = Math.floor(remaining / 60000);
        const secs = Math.floor((remaining % 60000) / 1000);
        $('#expiryTimeLeft').text(`${mins}:${secs.toString().padStart(2, '0')}`);

        if (remaining <= 30000) {
            $('#expiryCountdown').removeClass('bg-secondary bg-warning').addClass('bg-danger');
        } else if (remaining <= 60000) {
            $('#expiryCountdown').removeClass('bg-secondary bg-danger').addClass('bg-warning');
        } else {
            $('#expiryCountdown').removeClass('bg-warning bg-danger').addClass('bg-secondary');
        }

        if (remaining <= 0) {
            clearInterval(roomCountdownInterval);
            roomCountdownInterval = null;
        }
    }, 1000);

    if (roomCheckInterval) clearInterval(roomCheckInterval);
    roomCheckInterval = setInterval(() => {
        if (!roomId || gameStarted) {
            clearInterval(roomCheckInterval);
            roomCheckInterval = null;
            return;
        }
        API.get('/api/room/info/' + roomId)
            .done(res => {
                if (res.code === 200 && (res.data.status === 'expired' || res.data.status === 'completed')) {
                    handleRoomExpired();
                }
            });
    }, 5000);
}

function stopRoomExpiryCheck() {
    if (roomCountdownInterval) {
        clearInterval(roomCountdownInterval);
        roomCountdownInterval = null;
    }
    if (roomCheckInterval) {
        clearInterval(roomCheckInterval);
        roomCheckInterval = null;
    }
    roomExpireTime = null;
    $('#expiryCountdown').hide();
}

function handleRoomExpired() {
    stopRoomExpiryCheck();
    stopTurnTimer();
    if (ws) {
        try { ws.close(); } catch (e) {}
        ws = null;
    }
    gameOver = true;
    toastr.warning('房间已过期（5分钟未匹配）', '房间关闭', { timeOut: 5000 });
    setTimeout(backToLobby, 800);
}

function backToLobby() {
    stopRoomExpiryCheck();
    stopTurnTimer();
    if (ws) {
        try { ws.close(); } catch (e) {}
        ws = null;
    }
    roomId = null;
    gameId = null;
    playerColor = null;
    gameStarted = false;
    gameOver = false;
    isMyTurn = false;
    winningLine = null;
    lastMove = null;
    currentPlayer = 'black';
    board = Array(BOARD_SIZE).fill(null).map(() => Array(BOARD_SIZE).fill(null));

    $('#gameView').hide();
    $('#lobbyView').show();
    $('#createRoomBtn').prop('disabled', false).html('<i class="bi bi-plus-circle"></i> 创建房间');
    $('#createRoomBtn').show();
    $('#roomCodeDisplay').hide();
    $('#waitingOverlay').hide();
    $('#undoBtn').prop('disabled', false).html('<i class="bi bi-arrow-counterclockwise"></i> 请求悔棋');
    $('#leaveRoomBtn').prop('disabled', false).html('<i class="bi bi-box-arrow-left"></i> 离开房间');
    $('#turnTimer').hide();
    $('#yourColorInfo').hide();
    roomListInterval = setInterval(loadRoomList, 5000);
    loadRoomList();
    loadHistoryList();
    drawBoard();
}

function leaveRoom() {
    if (!confirm('确定要离开当前房间吗？')) return;
    backToLobby();
    toastr.info('已离开房间');
}

function startTurnTimer() {
    stopTurnTimer();
    turnTimeLeft = TURN_TIME_LIMIT;
    $('#turnTimer').show().removeClass('bg-warning bg-danger').addClass('bg-info');
    $('#turnTimeLeft').text(turnTimeLeft);

    turnTimerInterval = setInterval(() => {
        turnTimeLeft--;
        $('#turnTimeLeft').text(turnTimeLeft);

        if (turnTimeLeft <= 10) {
            $('#turnTimer').removeClass('bg-info bg-warning').addClass('bg-danger');
        } else if (turnTimeLeft <= 20) {
            $('#turnTimer').removeClass('bg-info bg-danger').addClass('bg-warning');
        }

        if (turnTimeLeft <= 0) {
            stopTurnTimer();
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'timeout' }));
            }
            toastr.error('思考超时！');
        }
    }, 1000);
}

function stopTurnTimer() {
    if (turnTimerInterval) {
        clearInterval(turnTimerInterval);
        turnTimerInterval = null;
    }
    $('#turnTimer').removeClass('bg-warning bg-danger').addClass('bg-info');
    $('#turnTimer').hide();
}

function shareRoom() {
    const roomCode = $('#gameRoomCode').text() || $('#roomCode').text();
    if (!roomCode || roomCode === '------') return;
    const joinUrl = `${window.location.origin}/room?code=${roomCode}`;
    const shareText = `来一局五子棋吧！我已经准备好棋盘了，等你来挑战 🎯\n\n加入链接：${joinUrl}\n房间代码：${roomCode}`;

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(shareText)
            .then(() => toastr.success('分享链接已复制到剪贴板！'))
            .catch(() => fallbackCopy(shareText));
    } else {
        fallbackCopy(shareText);
    }
}

function fallbackCopy(text) {
    const $tmp = $('<textarea>').val(text).appendTo('body').select();
    try {
        document.execCommand('copy');
        toastr.success('分享链接已复制到剪贴板！');
    } catch (e) {
        toastr.error('复制失败，请手动复制');
    }
    $tmp.remove();
}

function createRoom() {
    const token = localStorage.getItem('access_token');
    if (!token) {
        toastr.error('请先登录');
        return;
    }
    API.post('/api/room/create')
        .done(res => {
            if (res.code === 200) {
                stopRoomListPolling();
                roomId = res.data.id;
                playerColor = 'black';
                gameStarted = false;
                gameOver = false;
                isMyTurn = false;
                winningLine = null;
                lastMove = null;
                currentPlayer = 'black';
                board = Array(BOARD_SIZE).fill(null).map(() => Array(BOARD_SIZE).fill(null));

                $('#lobbyView').hide();
                $('#gameView').show();
                $('#yourColorInfo').show();
                $('#yourColor').text('黑棋');
                $('#blackPlayer').text('你');
                $('#whitePlayer').text('等待中...');

                $('#roomCodeDisplay').show();
                $('#roomCode').text(res.data.room_code);
                $('#gameRoomCodeCard').show();
                $('#gameRoomCode').text(res.data.room_code);
                $('#createRoomBtn').prop('disabled', true).html('<i class="bi bi-check"></i> 房间已创建');
                $('#waitingOverlay').show();
                $('#roomStatus').text('等待对手加入...').removeClass('bg-success').addClass('bg-warning');

                connectWebSocket();
                startRoomExpiryCheck(res.data.expires_at);
            }
        })
        .fail(xhr => {
            const detail = xhr.responseJSON?.detail || '创建房间失败';
            if (xhr.status === 401 || xhr.status === 403) {
                localStorage.removeItem('access_token');
                localStorage.removeItem('user');
                toastr.error('登录已失效，请重新登录');
            } else {
                toastr.error(detail);
            }
        });
}

function joinRoom() {
    const token = localStorage.getItem('access_token');
    if (!token) {
        toastr.error('请先登录');
        return;
    }
    const code = $('#joinRoomCode').val().trim().toUpperCase();
    if (!code) {
        toastr.error('请输入房间代码');
        return;
    }
    if (code.length !== 6) {
        toastr.error('房间代码为6位字符');
        return;
    }

    API.post('/api/room/join/' + code)
        .done(res => {
            if (res.code === 200) {
                stopRoomListPolling();
                stopRoomExpiryCheck();
                roomId = res.data.room_id;
                gameId = res.data.game_id;
                playerColor = res.data.player_color;
                gameStarted = false;
                gameOver = false;
                isMyTurn = false;
                winningLine = null;
                lastMove = null;
                currentPlayer = 'black';
                board = Array(BOARD_SIZE).fill(null).map(() => Array(BOARD_SIZE).fill(null));

                $('#lobbyView').hide();
                $('#gameView').show();
                $('#yourColorInfo').show();
                $('#yourColor').text(playerColor === 'black' ? '黑棋' : '白棋');

                $('#gameRoomCodeCard').show();
                $('#gameRoomCode').text(code);
                $('#waitingOverlay').hide();
                $('#roomStatus').text('对手已就位，游戏开始！').removeClass('bg-warning').addClass('bg-success');

                if (playerColor === 'white') {
                    $('#whitePlayer').text('你');
                    $('#blackPlayer').text('对手');
                } else {
                    $('#blackPlayer').text('你');
                    $('#whitePlayer').text('对手');
                }

                connectWebSocket();
                loadRoomInfo();
            }
        })
        .fail(xhr => {
            const detail = xhr.responseJSON?.detail || '加入房间失败';
            if (xhr.status === 401 || xhr.status === 403) {
                localStorage.removeItem('access_token');
                localStorage.removeItem('user');
                toastr.error('登录已失效，请重新登录');
            } else {
                toastr.error(detail);
            }
        });
}

function loadRoomList() {
    API.get('/api/room/list')
        .done(res => {
            if (res.code === 200) {
                renderRoomList(res.data);
            }
        });
}

function loadHistoryList() {
    const token = localStorage.getItem('access_token');
    if (!token) {
        $('#historyList').html('<div class="list-group-item text-center text-muted py-4"><i class="bi bi-info-circle"></i> 请先登录</div>');
        return;
    }
    API.get('/api/room/history')
        .done(res => {
            if (res.code === 200) {
                renderHistoryList(res.data);
            }
        })
        .fail(xhr => {
            if (xhr.status === 401 || xhr.status === 403) {
                $('#historyList').html('<div class="list-group-item text-center text-muted py-4"><i class="bi bi-info-circle"></i> 请先登录</div>');
            } else {
                $('#historyList').html('<div class="list-group-item text-center text-danger py-4">加载失败</div>');
            }
        });
}

function renderRoomList(rooms) {
    const container = $('#roomList');

    if (!rooms || rooms.length === 0) {
        container.html('<div class="list-group-item text-center text-muted py-4"><i class="bi bi-hourglass-split"></i> 暂无等待中的房间</div>');
        return;
    }

    container.empty();

    rooms.forEach(room => {
        const created = room.created_at ? new Date(room.created_at) : new Date();
        const timeStr = created.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        container.append(`
            <a href="#" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center room-item" data-code="${room.room_code}">
                <div>
                    <strong style="font-family:var(--font-mono);letter-spacing:0.15em;">${room.room_code}</strong>
                    <small class="text-muted ms-2"><i class="bi bi-person"></i> ${room.host_name || '匿名'}</small>
                    <small class="text-muted ms-2"><i class="bi bi-clock"></i> ${timeStr}</small>
                </div>
                <span class="badge bg-success">等待中</span>
            </a>
        `);
    });

    $('.room-item').off('click').on('click', function(e) {
        e.preventDefault();
        const code = $(this).data('code');
        $('#joinRoomCode').val(code);
        joinRoom();
    });
}

const STATUS_LABELS = {
    waiting: { text: '等待中', cls: 'bg-success' },
    playing: { text: '进行中', cls: 'bg-primary' },
    completed: { text: '已结束', cls: 'bg-secondary' },
    expired: { text: '已过期', cls: 'bg-warning' }
};

function renderHistoryList(rooms) {
    const container = $('#historyList');

    if (!rooms || rooms.length === 0) {
        container.html('<div class="list-group-item text-center text-muted py-4"><i class="bi bi-inbox"></i> 暂无历史房间</div>');
        return;
    }

    container.empty();

    rooms.forEach(room => {
        const meta = STATUS_LABELS[room.status] || { text: room.status, cls: 'bg-secondary' };
        const created = room.created_at ? new Date(room.created_at) : new Date();
        const dateStr = created.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
        const players = `${room.host_name || '?'}  vs  ${room.guest_name || '?'}`;
        container.append(`
            <div class="list-group-item d-flex justify-content-between align-items-center history-item">
                <div>
                    <strong style="font-family:var(--font-mono);letter-spacing:0.15em;">${room.room_code}</strong>
                    <small class="text-muted ms-2">${players}</small>
                    <small class="text-muted ms-2"><i class="bi bi-calendar"></i> ${dateStr}</small>
                </div>
                <span class="badge ${meta.cls}">${meta.text}</span>
            </div>
        `);
    });
}

function loadRoomInfo() {
    if (!roomId) return;

    API.get('/api/room/info/' + roomId)
        .done(res => {
            if (res.code === 200) {
                if (res.data.is_host) {
                    $('#blackPlayer').text('你');
                } else if (res.data.guest_id) {
                    $('#whitePlayer').text('你');
                }
            }
        });
}

function connectWebSocket() {
    const token = localStorage.getItem('access_token');
    if (!token || !roomId) {
        toastr.error('无法建立连接，缺少房间或登录信息');
        return;
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/room/ws/${roomId}?token=${encodeURIComponent(token)}`;

    try {
        ws = new WebSocket(wsUrl);
    } catch (e) {
        toastr.error('WebSocket 创建失败：' + e.message);
        return;
    }

    ws.onopen = () => {
        console.log('WebSocket connected, roomId=' + roomId);
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleWSMessage(data);
        } catch (e) {
            console.error('WS parse error', e);
        }
    };

    ws.onclose = (ev) => {
        console.log('WebSocket closed, code=' + ev.code);
        if (ev.code === 4001) {
            toastr.error('登录已失效，请重新登录');
            localStorage.removeItem('access_token');
            localStorage.removeItem('user');
        } else if (ev.code === 4010) {
            handleRoomExpired();
        } else if (ev.code === 4003) {
            toastr.error('无权加入此房间');
            backToLobby();
        } else if (ev.code === 4004) {
            toastr.error('房间不存在');
            backToLobby();
        } else if (ev.code !== 1000 && ev.code !== 1001 && gameStarted) {
            // 异常关闭且已开始游戏
            toastr.warning('与服务器的连接已断开');
        }
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
}

function handleWSMessage(data) {
    switch (data.type) {
        case 'player_color':
            if (!playerColor) {
                playerColor = data.color;
                $('#yourColorInfo').show();
                $('#yourColor').text(playerColor === 'black' ? '黑棋' : '白棋');
            }
            break;

        case 'opponent_joined':
            $('#waitingOverlay').hide();
            $('#roomStatus').text('游戏开始').removeClass('bg-warning').addClass('bg-success');
            gameStarted = true;
            stopRoomExpiryCheck();
            toastr.success('对手已加入，游戏开始!');

            if (playerColor === 'black') {
                $('#blackPlayer').text('你');
                isMyTurn = true;
                startTurnTimer();
            } else {
                $('#whitePlayer').text('你');
                isMyTurn = false;
                stopTurnTimer();
            }
            break;

        case 'game_state':
            if (data.game && data.game.board && Array.isArray(data.game.board)) {
                for (let r = 0; r < Math.min(BOARD_SIZE, data.game.board.length); r++) {
                    if (!Array.isArray(data.game.board[r])) continue;
                    for (let c = 0; c < Math.min(BOARD_SIZE, data.game.board[r].length); c++) {
                        const val = data.game.board[r][c];
                        board[r][c] = val === 1 ? 'black' : (val === 2 ? 'white' : null);
                    }
                }
                const moves = data.game.moves || [];
                if (moves.length > 0 && Array.isArray(moves[moves.length - 1])) {
                    const last = moves[moves.length - 1];
                    lastMove = { row: last[0], col: last[1], player: last[2] === 1 ? 'black' : 'white' };
                }
                currentPlayer = data.game.current_player === 1 ? 'black' : 'white';
            }

            if (data.status === 'playing') {
                $('#roomStatus').text('游戏进行中').removeClass('bg-warning').addClass('bg-success');
                gameStarted = true;
                stopRoomExpiryCheck();
                $('#waitingOverlay').hide();
                if (playerColor === currentPlayer) {
                    isMyTurn = true;
                    startTurnTimer();
                } else {
                    isMyTurn = false;
                    stopTurnTimer();
                }
            }

            drawBoard();
            break;

        case 'move':
            if (data.row != null && data.col != null && data.row >= 0 && data.col >= 0) {
                board[data.row][data.col] = data.player;
                lastMove = { row: data.row, col: data.col, player: data.player };
            }
            currentPlayer = currentPlayer === 'black' ? 'white' : 'black';
            isMyTurn = (playerColor === currentPlayer);
            if (isMyTurn) { startTurnTimer(); } else { stopTurnTimer(); }
            drawBoard();

            if (data.game_over) {
                stopTurnTimer();
                endGame(data.player, data.winning_line);
            }
            break;

        case 'undo':
            if (data.row !== undefined && data.col !== undefined) {
                board[data.row][data.col] = null;
                currentPlayer = data.player === 'black' ? 'white' : 'black';
                isMyTurn = (playerColor === currentPlayer);
                if (isMyTurn) { startTurnTimer(); } else { stopTurnTimer(); }
                lastMove = findLastMove();
            }
            drawBoard();
            toastr.info('悔棋成功');
            break;

        case 'room_expired':
            handleRoomExpired();
            break;

        case 'pong':
            break;
    }
}

function handleClick(e) {
    if (!gameStarted || gameOver || !isMyTurn) return;
    if (playerColor !== currentPlayer) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        toastr.warning('连接尚未就绪');
        return;
    }

    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;

    const x = (e.clientX - rect.left) * scaleX;
    const y = (e.clientY - rect.top) * scaleY;

    const col = Math.round((x - PADDING) / CELL_SIZE);
    const row = Math.round((y - PADDING) / CELL_SIZE);

    if (row < 0 || row >= BOARD_SIZE || col < 0 || col >= BOARD_SIZE) return;
    if (board[row][col] !== null) return;

    ws.send(JSON.stringify({ type: 'move', row, col }));
    board[row][col] = playerColor;
    lastMove = { row, col, player: playerColor };
    isMyTurn = false;
    stopTurnTimer();
    drawBoard();
}

function requestUndo() {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        toastr.warning('连接尚未就绪');
        return;
    }
    if (!gameStarted || gameOver) {
        toastr.warning('当前没有进行中的对局');
        return;
    }
    ws.send(JSON.stringify({ type: 'undo' }));
    toastr.info('已发送悔棋请求');
}

function findLastMove() {
    for (let i = board.length - 1; i >= 0; i--) {
        for (let j = board[i].length - 1; j >= 0; j--) {
            if (board[i][j]) {
                return { row: i, col: j };
            }
        }
    }
    return null;
}

function endGame(winner, line) {
    gameOver = true;
    winningLine = line;
    stopTurnTimer();

    if (winner === playerColor) {
        $('#resultIcon').removeClass().addClass('bi-trophy-fill');
        $('#resultText').text('你赢了!');
        $('#resultModal .modal-header').removeClass('bg-danger').addClass('bg-success');
    } else {
        $('#resultIcon').removeClass().addClass('bi-emoji-frown');
        $('#resultText').text('你输了');
        $('#resultModal .modal-header').removeClass('bg-success').addClass('bg-danger');
    }

    drawBoard();
    $('#resultModal').modal('show');
}

function drawBoard() {
    if (!ctx || !canvas) return;
    if (!board || !Array.isArray(board) || board.length < BOARD_SIZE) {
        board = Array(BOARD_SIZE).fill(null).map(() => Array(BOARD_SIZE).fill(null));
    }

    const bgGrad = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
    bgGrad.addColorStop(0, '#d4a574');
    bgGrad.addColorStop(0.3, '#c4956a');
    bgGrad.addColorStop(0.7, '#c4956a');
    bgGrad.addColorStop(1, '#b8875a');
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.strokeStyle = '#5a3a20';
    ctx.lineWidth = 1;

    for (let i = 0; i < BOARD_SIZE; i++) {
        ctx.beginPath();
        ctx.moveTo(PADDING + i * CELL_SIZE, PADDING);
        ctx.lineTo(PADDING + i * CELL_SIZE, PADDING + (BOARD_SIZE - 1) * CELL_SIZE);
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(PADDING, PADDING + i * CELL_SIZE);
        ctx.lineTo(PADDING + (BOARD_SIZE - 1) * CELL_SIZE, PADDING + i * CELL_SIZE);
        ctx.stroke();
    }

    const starPoints = [[3, 3], [3, 11], [7, 7], [11, 3], [11, 11]];
    ctx.fillStyle = '#3d2010';
    starPoints.forEach(([r, c]) => {
        ctx.beginPath();
        ctx.arc(PADDING + c * CELL_SIZE, PADDING + r * CELL_SIZE, 3.5, 0, Math.PI * 2);
        ctx.fill();
    });

    for (let r = 0; r < BOARD_SIZE; r++) {
        if (!board[r] || !Array.isArray(board[r])) continue;
        for (let c = 0; c < BOARD_SIZE; c++) {
            if (board[r][c]) {
                drawPiece(r, c, board[r][c]);
            }
        }
    }

    if (lastMove) {
        ctx.strokeStyle = lastMove.player === 'black' ? '#fff' : '#000';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(
            PADDING + lastMove.col * CELL_SIZE,
            PADDING + lastMove.row * CELL_SIZE,
            PIECE_RADIUS - 4,
            0, Math.PI * 2
        );
        ctx.stroke();
    }

    if (winningLine && Array.isArray(winningLine) && winningLine.length >= 5
        && Array.isArray(winningLine[0]) && Array.isArray(winningLine[4])) {
        ctx.save();
        ctx.strokeStyle = 'rgba(220, 50, 30, 0.5)';
        ctx.lineWidth = 8;
        ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.moveTo(
            PADDING + winningLine[0][1] * CELL_SIZE,
            PADDING + winningLine[0][0] * CELL_SIZE
        );
        ctx.lineTo(
            PADDING + winningLine[4][1] * CELL_SIZE,
            PADDING + winningLine[4][0] * CELL_SIZE
        );
        ctx.stroke();

        ctx.strokeStyle = '#e83020';
        ctx.lineWidth = 3.5;
        ctx.beginPath();
        ctx.moveTo(
            PADDING + winningLine[0][1] * CELL_SIZE,
            PADDING + winningLine[0][0] * CELL_SIZE
        );
        ctx.lineTo(
            PADDING + winningLine[4][1] * CELL_SIZE,
            PADDING + winningLine[4][0] * CELL_SIZE
        );
        ctx.stroke();
        ctx.restore();
    }
}

function drawPiece(row, col, color) {
    const x = PADDING + col * CELL_SIZE;
    const y = PADDING + row * CELL_SIZE;

    ctx.beginPath();
    ctx.arc(x + 1.5, y + 2, PIECE_RADIUS, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(0,0,0,0.25)';
    ctx.fill();

    const gradient = ctx.createRadialGradient(x - 4, y - 4, 1, x, y, PIECE_RADIUS);

    if (color === 'black') {
        gradient.addColorStop(0, '#6a6a6a');
        gradient.addColorStop(0.4, '#3a3a3a');
        gradient.addColorStop(1, '#0a0a0a');
    } else {
        gradient.addColorStop(0, '#ffffff');
        gradient.addColorStop(0.4, '#f0f0f0');
        gradient.addColorStop(1, '#c8c8c8');
    }

    ctx.beginPath();
    ctx.arc(x, y, PIECE_RADIUS, 0, Math.PI * 2);
    ctx.fillStyle = gradient;
    ctx.fill();

    ctx.strokeStyle = color === 'black' ? 'rgba(0,0,0,0.5)' : 'rgba(0,0,0,0.18)';
    ctx.lineWidth = 1;
    ctx.stroke();
}
