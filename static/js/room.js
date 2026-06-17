const BOARD_SIZE = 15;
const CELL_SIZE = 40;
const PADDING = 20;
const PIECE_RADIUS = 16;

let canvas, ctx;
let roomId = null;
let playerColor = null;
let board = Array(BOARD_SIZE).fill(null).map(() => Array(BOARD_SIZE).fill(null));
let currentPlayer = 'black';
let isMyTurn = false;
let gameOver = false;
let winningLine = null;
let lastMove = null;
let ws = null;
let wsReconnectAttempts = 0;
let wsReconnectTimer = null;
let gameStarted = false;

let roomListInterval = null;
let roomCheckInterval = null;
let roomExpireTime = null;
let roomCountdownInterval = null;
let turnTimerInterval = null;
let turnTimeLeft = 60;
const TURN_TIME_LIMIT = 60;
const ROOM_EXPIRY_MS = 5 * 60 * 1000;
const UNDO_TIMEOUT_SEC = 30;

// 悔棋请求流程：
//   requesting  = 我方刚发了请求，正在等对家回应（此时再点悔棋按钮无效）
//   incoming   = 我方收到了对家的请求，弹窗等待我操作
let undoFlow = null;             // 'requesting' | 'incoming' | null
let undoCountdownTimer = null;   // 悔棋弹窗的倒计时 interval
let undoRequestFallbackTimer = null;
let roomRestoreAttempted = false;

// 历史房间分页
const HISTORY_PAGE_SIZE = 15;
let historyAll = [];      // 全量历史
let historyPage = 1;      // 当前页 (1-based)
let historyAuthed = false; // 是否已登录（区分"未登录"和"暂无历史"）

// 等待遮罩有 d-flex !important，jQuery .hide() 会被覆盖；用 d-none !important 才能正确隐藏
function showWaiting() { $('#waitingOverlay').removeClass('d-none'); }
function hideWaiting() { $('#waitingOverlay').addClass('d-none'); }

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

    // 悔棋弹窗按钮
    $('#undoAcceptBtn').on('click', () => sendUndoResponse('accept'));
    $('#undoDeclineBtn').on('click', () => sendUndoResponse('decline'));
    $('#undoCancelBtn').on('click', () => cancelUndoRequest());

    // 历史房间分页控制
    $('#hp-prev').on('click', e => {
        e.preventDefault();
        if (historyPage > 1) {
            historyPage--;
            renderHistoryPage();
        }
    });
    $('#hp-next').on('click', e => {
        e.preventDefault();
        const totalPages = Math.max(1, Math.ceil(historyAll.length / HISTORY_PAGE_SIZE));
        if (historyPage < totalPages) {
            historyPage++;
            renderHistoryPage();
        }
    });

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
        // 不弹 toast，直接弹登录框让用户登录
        showLoginModal();
        return;
    }

    API.get('/api/auth/me')
        .done(res => {
            if (res.code === 200) {
                const user = res.data;
                showAuthNav(user);

                // 重新拉取历史（可能初次未登录态下是空数据）
                loadHistoryList();

                restoreCurrentRoom();

                const urlParams = new URLSearchParams(window.location.search);
                const roomCode = urlParams.get('code');
                if (roomCode && !roomId) {
                    $('#joinRoomCode').val(roomCode.toUpperCase());
                    joinRoom();
                }
            } else {
                showAuthNav(null);
                localStorage.removeItem('access_token');
                showLoginModal();
            }
        });
        // 401 由全局 ajaxError 兜底（清 token + 弹登录框）
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
        if (!roomId || gameOver) {
            clearInterval(roomCheckInterval);
            roomCheckInterval = null;
            return;
        }
        API.get('/api/room/info/' + roomId)
            .done(res => {
                if (res.code !== 200) return;
                const status = res.data.status;
                if (status === 'expired' || status === 'completed') {
                    handleRoomExpired();
                } else if (status === 'playing' && !gameStarted) {
                    // 对手已加入但我们没收到 opponent_joined 事件（WebSocket 短暂断开过）
                    // 强制重连一次 WS，服务器会重发完整状态
                    console.log('[room] status=playing detected, forcing WS reconnect');
                    if (ws) {
                        try { ws.close(); } catch (e) {}
                        ws = null;
                    }
                    connectWebSocket();
                }
            });
    }, 3000);
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
    if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
    }
    wsReconnectAttempts = 0;
    if (ws) {
        try { ws.close(1000, 'expired'); } catch (e) {}
        ws = null;
    }
    gameOver = true;
    clearRoomSession();
    toastr.warning('房间已过期（5分钟未匹配）', '房间关闭', { timeOut: 5000 });
    setTimeout(backToLobby, 800);
}

function backToLobby() {
    stopRoomExpiryCheck();
    stopTurnTimer();
    closeUndoModals();  // 顺手把悔棋弹窗也关掉
    if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
    }
    wsReconnectAttempts = 0;
    if (ws) {
        try { ws.close(1000, 'leave'); } catch (e) {}
        ws = null;
    }
    roomId = null;
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
    hideWaiting();
    $('#undoBtn').prop('disabled', false).html('<i class="bi bi-arrow-counterclockwise"></i> 请求悔棋');
    $('#leaveRoomBtn').prop('disabled', false).html('<i class="bi bi-box-arrow-left"></i> 离开房间');
    $('#turnTimer').hide();
    $('#yourColorInfo').hide();
    roomListInterval = setInterval(loadRoomList, 5000);
    loadRoomList();
    loadHistoryList();
    drawBoard();
    clearRoomSession();
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
    if (!isLoggedIn()) {
        showLoginModal();
        return;
    }
    API.post('/api/room/create')
        .done(res => {
            if (res.code === 200) {
                stopRoomListPolling();
                roomId = res.data.id;
                playerColor = 'black';
                persistRoomSession(res.data);
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
                showWaiting();
                $('#roomStatus').text('等待对手加入...').removeClass('bg-success').addClass('bg-warning');

                connectWebSocket();
                startRoomExpiryCheck(res.data.expires_at);
            } else {
                toastr.error(res.message || '创建房间失败');
            }
        })
        .fail(xhr => {
            // 401 由全局 ajaxError 弹登录框
            if (xhr.status !== 401) {
                toastr.error(xhr.responseJSON?.detail || '创建房间失败');
            }
        });
}

function joinRoom() {
    if (!isLoggedIn()) {
        showLoginModal();
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
                enterRoomSession({
                    ...res.data,
                    room_code: res.data.room_code || code,
                });
            } else {
                toastr.error(res.message || '加入房间失败');
            }
        })
        .fail(xhr => {
            // 401 由全局 ajaxError 弹登录框
            if (xhr.status !== 401) {
                toastr.error(xhr.responseJSON?.detail || '加入房间失败');
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
        historyAll = [];
        historyAuthed = false;
        renderHistoryPage();
        return;
    }
    API.get('/api/room/history')
        .done(res => {
            if (res.code === 200) {
                historyAll = Array.isArray(res.data) ? res.data : [];
                historyAuthed = true;
                // 切回 tab 时回到第 1 页
                historyPage = 1;
                renderHistoryPage();
            }
        })
        .fail(xhr => {
            if (xhr.status === 401 || xhr.status === 403) {
                historyAll = [];
                historyAuthed = false;
                renderHistoryPage();
            } else {
                $('#historyList').html(
                    '<div class="room-list-empty text-danger">' +
                    '<i class="bi bi-exclamation-triangle"></i>' +
                    '<span class="small">加载失败</span></div>'
                );
                $('#historyRoomCount').text('0');
                $('#historyPagination').addClass('is-hidden');
            }
        });
}

function formatTime(value, withSeconds) {
    const d = value ? new Date(value) : new Date();
    if (isNaN(d.getTime())) return '—';
    const pad = n => String(n).padStart(2, '0');
    const date = `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    const time = withSeconds
        ? `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
        : `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    return `${date} ${time}`;
}

function renderHistoryPage() {
    const container = $('#historyList');
    const total = historyAll.length;
    $('#historyRoomCount').text(total);

    if (total === 0) {
        const icon = historyAuthed ? 'bi-inbox' : 'bi-person-lock';
        const text = historyAuthed ? '暂无历史房间' : '登录后查看历史对局';
        container.html(
            '<div class="room-list-empty">' +
            `<i class="bi ${icon}"></i>` +
            `<span class="small">${text}</span></div>`
        );
        $('#historyPagination').addClass('is-hidden');
        return;
    }

    const totalPages = Math.max(1, Math.ceil(total / HISTORY_PAGE_SIZE));
    if (historyPage > totalPages) historyPage = totalPages;
    if (historyPage < 1) historyPage = 1;

    const start = (historyPage - 1) * HISTORY_PAGE_SIZE;
    const slice = historyAll.slice(start, start + HISTORY_PAGE_SIZE);

    container.empty();
    slice.forEach(room => {
        container.append(buildHistoryRow(room));
    });

    // 更新分页 UI
    const $pagination = $('#historyPagination');
    const $prev = $('#hp-prev');
    const $next = $('#hp-next');
    const $info = $('#hp-info');

    if (totalPages > 1) {
        $pagination.removeClass('is-hidden');
        $prev.prop('disabled', historyPage === 1);
        $next.prop('disabled', historyPage === totalPages);
        const startIdx = (historyPage - 1) * HISTORY_PAGE_SIZE + 1;
        const endIdx = Math.min(historyPage * HISTORY_PAGE_SIZE, total);
        $info.text(`${startIdx}-${endIdx} / ${total}`);
    } else {
        $pagination.addClass('is-hidden');
    }
}

function buildHistoryRow(room) {
    const meta = STATUS_LABELS[room.status] || { text: room.status || '—', cls: 'bg-secondary' };
    const created = formatTime(room.created_at, false);
    const host = room.host_name || '匿名';
    const guest = room.guest_name || '匿名';

    let resultCls = '';
    let resultHtml = '';
    if (room.status === 'completed' && room.winner_id != null && room.my_id != null) {
        if (room.winner_id === room.my_id) {
            resultCls = 'history-win';
            resultHtml = '<span class="room-row-result win"><i class="bi bi-trophy-fill"></i> 胜</span>';
        } else {
            resultCls = 'history-loss';
            resultHtml = '<span class="room-row-result loss"><i class="bi bi-x-circle"></i> 负</span>';
        }
    }

    return `
        <div class="room-row history-row ${resultCls}">
            <div class="room-row-main">
                <div class="room-row-code">${room.room_code || '------'}</div>
                <div class="room-row-meta">
                    <span class="meta-item"><i class="bi bi-person"></i>${host}</span>
                    <span class="meta-item text-muted" style="opacity:0.5;">vs</span>
                    <span class="meta-item"><i class="bi bi-person"></i>${guest}</span>
                    <span class="meta-item"><i class="bi bi-calendar3"></i>${created}</span>
                </div>
            </div>
            <div class="room-row-side">
                ${resultHtml}
                <span class="badge ${meta.cls}">${meta.text}</span>
            </div>
        </div>
    `;
}

function renderRoomList(rooms) {
    const container = $('#roomList');
    const list = Array.isArray(rooms) ? rooms : [];

    $('#activeRoomCount').text(list.length);

    if (list.length === 0) {
        container.html(
            '<div class="room-list-empty">' +
            '<i class="bi bi-broadcast"></i>' +
            '<span class="small">暂无等待中的房间</span></div>'
        );
        return;
    }

    container.empty();

    list.forEach(room => {
        const created = formatTime(room.created_at, true);
        const host = room.host_name || '匿名';
        container.append(`
            <a href="#" class="room-row is-clickable room-item" data-code="${room.room_code}">
                <div class="room-row-main">
                    <div class="room-row-code">${room.room_code}</div>
                    <div class="room-row-meta">
                        <span class="meta-item"><i class="bi bi-person"></i>${host}</span>
                        <span class="meta-item"><i class="bi bi-clock"></i>${created}</span>
                    </div>
                </div>
                <div class="room-row-side">
                    <span class="badge bg-success"><i class="bi bi-broadcast"></i> 等待中</span>
                </div>
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
    if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
        return;  // 已连接
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/room/ws/${roomId}?token=${encodeURIComponent(token)}`;

    try {
        ws = new WebSocket(wsUrl);
    } catch (e) {
        toastr.error('WebSocket 创建失败：' + e.message);
        scheduleWSReconnect();
        return;
    }

    ws.onopen = () => {
        console.log('WebSocket connected, roomId=' + roomId);
        wsReconnectAttempts = 0;
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
            // WebSocket 鉴权失败：清 token 并弹登录框
            localStorage.removeItem('access_token');
            localStorage.removeItem('user');
            showLoginModal();
        } else if (ev.code === 4010) {
            handleRoomExpired();
        } else if (ev.code === 4003) {
            toastr.error('无权加入此房间');
            backToLobby();
        } else if (ev.code === 4004) {
            toastr.error('房间不存在');
            backToLobby();
        } else if (ev.code === 1000 || ev.code === 1001) {
            // 主动关闭，不重连
        } else if (roomId && !gameOver) {
            // 异常关闭且还没离开房间 → 尝试重连
            scheduleWSReconnect();
        }
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
}

function scheduleWSReconnect() {
    if (wsReconnectTimer) return;
    if (!roomId) return;
    if (gameOver) return;
    wsReconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, wsReconnectAttempts - 1), 8000);
    console.log(`[ws] reconnect attempt ${wsReconnectAttempts} in ${delay}ms`);
    wsReconnectTimer = setTimeout(() => {
        wsReconnectTimer = null;
        if (!roomId || gameOver) return;
        connectWebSocket();
    }, delay);
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
            hideWaiting();
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
                hideWaiting();
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
            // 真正的悔棋执行：服务器在双方同意后才广播这条
            closeUndoModals();
            if (data.row !== undefined && data.col !== undefined) {
                board[data.row][data.col] = null;
                // 悔棋后应该由被悔棋方重下，所以当前玩家就是被悔棋的玩家
                currentPlayer = data.player;
                isMyTurn = (playerColor === currentPlayer);
                if (isMyTurn) { startTurnTimer(); } else { stopTurnTimer(); }
                lastMove = findLastMove();
            }
            drawBoard();
            toastr.success('悔棋成功');
            break;

        case 'undo_request':
            // 收到对家的悔棋请求 → 弹窗让玩家选择
            if (undoFlow) break;  // 已有流程在进行（理论上不会到这里）
            showUndoIncomingModal();
            break;

        case 'undo_sent':
            // 我方刚发的请求服务器已确认收到 → 弹出"等待对方确认"弹窗
            showUndoWaitingModal(data.timeout_sec || UNDO_TIMEOUT_SEC);
            break;

        case 'undo_declined':
            // 对家拒绝了
            closeUndoModals();
            toastr.warning(data.message || '对方拒绝了你的悔棋请求');
            break;

        case 'undo_timeout':
            // 超时未回应
            closeUndoModals();
            toastr.warning(data.message || '悔棋请求已超时');
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
    if (undoFlow) {
        toastr.info(undoFlow === 'requesting' ? '已发送过悔棋请求，请等待对方确认' : '请先处理对方的悔棋请求');
        return;
    }
    undoFlow = 'requesting';
    $('#undoBtn').prop('disabled', true);
    ws.send(JSON.stringify({ type: 'undo' }));
    // undo_sent 到达时会真正弹出等待弹窗（依赖服务器回执确定超时时间）
    // 但先给一个兜底超时：万一服务器没回（断线等），10s 后强制解锁按钮
    stopUndoRequestFallbackTimer();
    undoRequestFallbackTimer = setTimeout(() => {
        if (undoFlow === 'requesting') {
            closeUndoModals();
            toastr.warning('悔棋请求未送达，请稍后再试');
        }
    }, 10000);
}

function sendUndoResponse(action) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        closeUndoModals();
        toastr.warning('连接已断开');
        return;
    }
    ws.send(JSON.stringify({ type: action === 'accept' ? 'undo_accept' : 'undo_decline' }));
    closeUndoModals();
    if (action === 'decline') {
        toastr.info('已拒绝悔棋请求');
    }
}

function cancelUndoRequest() {
    // 主动撤回已发送的悔棋请求：通知服务器"我不要了"
    // （服务器目前没有显式 cancel 消息，但断线会被自动清理；这里只关弹窗）
    closeUndoModals();
    toastr.info('已撤回悔棋请求');
}

function showUndoWaitingModal(timeoutSec) {
    undoFlow = 'requesting';
    $('#undoWaitingCountdown').text(timeoutSec);
    const el = document.getElementById('undoWaitingModal');
    bootstrap.Modal.getOrCreateInstance(el).show();
    startUndoCountdown('undoWaitingCountdown', timeoutSec, () => {
        // 倒计时归零：弹窗还没被服务器回执关闭 → 强制清理
        if (undoFlow === 'requesting') {
            closeUndoModals();
            toastr.warning('悔棋请求已超时');
        }
    });
}

function showUndoIncomingModal() {
    undoFlow = 'incoming';
    $('#undoRequestCountdown').text(UNDO_TIMEOUT_SEC);
    const el = document.getElementById('undoRequestModal');
    bootstrap.Modal.getOrCreateInstance(el).show();
    startUndoCountdown('undoRequestCountdown', UNDO_TIMEOUT_SEC, () => {
        // 超时未操作 → 自动拒绝（不弹框，避免再弹一个 confirm）
        if (undoFlow === 'incoming') {
            sendUndoResponse('decline');
        }
    });
}

function startUndoCountdown(elemId, seconds, onTimeout) {
    stopUndoCountdown();
    let left = seconds;
    const el = document.getElementById(elemId);
    if (el) el.textContent = left;
    undoCountdownTimer = setInterval(() => {
        left -= 1;
        if (el) el.textContent = left;
        if (left <= 0) {
            stopUndoCountdown();
            if (onTimeout) onTimeout();
        }
    }, 1000);
}

function stopUndoCountdown() {
    if (undoCountdownTimer) {
        clearInterval(undoCountdownTimer);
        undoCountdownTimer = null;
    }
}

function stopUndoRequestFallbackTimer() {
    if (undoRequestFallbackTimer) {
        clearTimeout(undoRequestFallbackTimer);
        undoRequestFallbackTimer = null;
    }
}

function enterRoomSession(roomData) {
    stopRoomListPolling();
    stopRoomExpiryCheck();
    roomId = roomData.room_id;
    playerColor = roomData.player_color;
    persistRoomSession(roomData);
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
    $('#gameRoomCode').text(roomData.room_code || '------');

    if (playerColor === 'white') {
        $('#whitePlayer').text('你');
        $('#blackPlayer').text('对手');
    } else {
        $('#blackPlayer').text('你');
        $('#whitePlayer').text(roomData.status === 'waiting' ? '等待中...' : '对手');
    }

    if (roomData.status === 'waiting') {
        showWaiting();
        $('#roomStatus').text('等待对手加入...').removeClass('bg-success').addClass('bg-warning');
        if (roomData.expires_at) {
            startRoomExpiryCheck(roomData.expires_at);
        }
    } else {
        hideWaiting();
        $('#roomStatus').text('正在恢复对局...').removeClass('bg-warning').addClass('bg-success');
    }

    connectWebSocket();
    loadRoomInfo();
}

function persistRoomSession(roomData) {
    if (!roomData) return;
    localStorage.setItem('room_session', JSON.stringify(roomData));
}

function clearRoomSession() {
    localStorage.removeItem('room_session');
}

function restoreRoomView(roomData) {
    if (!roomData || !roomData.room_id || !roomData.player_color) return;
    enterRoomSession(roomData);
}

function restoreCurrentRoom() {
    if (roomRestoreAttempted) return;
    roomRestoreAttempted = true;

    const cached = localStorage.getItem('room_session');
    if (cached) {
        try {
            const roomData = JSON.parse(cached);
            if (roomData && roomData.room_id && roomData.room_code) {
                restoreRoomView(roomData);
                return;
            }
        } catch (e) {}
    }

    API.get('/api/room/current')
        .done(res => {
            if (res.code === 200 && res.data && res.data.room_id) {
                persistRoomSession(res.data);
                restoreRoomView(res.data);
            }
        });
}

function closeUndoModals() {
    stopUndoCountdown();
    stopUndoRequestFallbackTimer();
    undoFlow = null;
    $('#undoBtn').prop('disabled', false);
    ['undoRequestModal', 'undoWaitingModal'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        const inst = bootstrap.Modal.getInstance(el);
        if (inst) inst.hide();
    });
}

function findLastMove() {
    for (let i = board.length - 1; i >= 0; i--) {
        for (let j = board[i].length - 1; j >= 0; j--) {
            if (board[i][j]) {
                return { row: i, col: j, player: board[i][j] };
            }
        }
    }
    return null;
}

function endGame(winner, line) {
    gameOver = true;
    winningLine = line;
    stopTurnTimer();
    closeUndoModals();  // 终局了，悔棋弹窗没意义，顺手关掉

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
