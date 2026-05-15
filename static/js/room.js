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

$(function() {
    canvas = document.getElementById('gameCanvas');
    ctx = canvas.getContext('2d');
    
    canvas.width = BOARD_SIZE * CELL_SIZE + PADDING * 2;
    canvas.height = BOARD_SIZE * CELL_SIZE + PADDING * 2;
    
    canvas.addEventListener('click', handleClick);
    
    $('#createRoomBtn').on('click', createRoom);
    $('#joinRoomBtn').on('click', joinRoom);
    $('#undoBtn').on('click', requestUndo);
    $('#logoutBtn').on('click', () => location.href = '/');
    
    drawBoard();
    loadRoomList();
    roomListInterval = setInterval(loadRoomList, 5000);

    checkAuth();
});

function checkAuth() {
    const token = localStorage.getItem('access_token');
    if (!token) {
        toastr.error('请先登录');
        setTimeout(() => location.href = '/', 1500);
        return;
    }

    API.get('/api/auth/me')
        .done(res => {
            if (res.code === 200) {
                const user = res.data;
                $('#authNav').html(`
                    <li class="nav-item dropdown">
                        <a class="nav-link dropdown-toggle" href="#" data-bs-toggle="dropdown">
                            <i class="bi bi-person-circle"></i> ${user.username}
                        </a>
                        <ul class="dropdown-menu dropdown-menu-end">
                            <li><a class="dropdown-item" href="#" id="logoutBtn"><i class="bi bi-box-arrow-right"></i> 退出</a></li>
                        </ul>
                    </li>
                `);
                $('#logoutBtn').on('click', () => {
                    localStorage.removeItem('access_token');
                    localStorage.removeItem('user');
                    location.href = '/';
                });

                const urlParams = new URLSearchParams(window.location.search);
                const roomCode = urlParams.get('code');
                if (roomCode) {
                    $('#joinRoomCode').val(roomCode.toUpperCase());
                    joinRoom();
                }
            }
        })
        .fail(() => {
            toastr.error('请先登录');
            setTimeout(() => location.href = '/', 1500);
        });
}

function stopRoomListPolling() {
    if (roomListInterval) {
        clearInterval(roomListInterval);
        roomListInterval = null;
    }
}

function startRoomExpiryCheck() {
    roomExpireTime = Date.now() + 5 * 60 * 1000;
    
    if (roomCountdownInterval) clearInterval(roomCountdownInterval);
    roomCountdownInterval = setInterval(() => {
        if (!roomExpireTime || gameStarted) {
            clearInterval(roomCountdownInterval);
            roomCountdownInterval = null;
            return;
        }
        const remaining = Math.max(0, roomExpireTime - Date.now());
        const mins = Math.floor(remaining / 60000);
        const secs = Math.floor((remaining % 60000) / 1000);
        $('#roomStatus').text(`等待对手加入... ${mins}:${secs.toString().padStart(2, '0')}`);
        
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
                if (res.code === 200) {
                    if (res.data.status === 'expired' || res.data.status === 'completed') {
                        clearInterval(roomCheckInterval);
                        clearInterval(roomCountdownInterval);
                        roomCheckInterval = null;
                        roomCountdownInterval = null;
                        toastr.warning('房间已过期，请重新创建');
                        backToLobby();
                    }
                }
            });
    }, 5000);
}

function backToLobby() {
    if (ws) { ws.close(); ws = null; }
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
    roomListInterval = setInterval(loadRoomList, 5000);
    loadRoomList();
}

function startTurnTimer() {
    stopTurnTimer();
    turnTimeLeft = TURN_TIME_LIMIT;
    $('#turnTimer').show();
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
            gameOver = true;
            const winner = playerColor === 'black' ? 'white' : 'black';
            endGame(winner, null);
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

function createRoom() {
    API.post('/api/room/create')
        .done(res => {
            if (res.code === 200) {
                stopRoomListPolling();
                roomId = res.data.id;
                playerColor = 'black';
                board = Array(BOARD_SIZE).fill(null).map(() => Array(BOARD_SIZE).fill(null));
                
                $('#lobbyView').hide();
                $('#gameView').show();
                $('#yourColorInfo').show();
                $('#yourColor').text('黑棋').addClass('text-dark');
                $('#blackPlayer').text('你');
                $('#whitePlayer').text('等待中...');
                
                $('#gameRoomCodeCard').show();
                $('#gameRoomCode').text(res.data.room_code);
                $('#createRoomBtn').prop('disabled', true).html('<i class="bi bi-check"></i> 房间已创建');
                $('#waitingOverlay').show();
                $('#roomStatus').text('等待对手加入...').removeClass('bg-success').addClass('bg-warning');
                
                $('#shareHint2').on('click', function() {
                    const roomCode = $('#gameRoomCode').text();
                    const joinUrl = `${window.location.origin}/room?code=${roomCode}`;
                    const shareText = `来一局五子棋吧！我已经准备好棋盘了，等你来挑战 🎯\n\n加入链接：${joinUrl}\n房间代码：${roomCode}`;
                    
                    navigator.clipboard.writeText(shareText).then(() => {
                        toastr.success('分享链接已复制到剪贴板！');
                    }).catch(() => {
                        toastr.error('复制失败，请手动复制');
                    });
                });
                
                connectWebSocket();
                startRoomExpiryCheck();
            }
        })
        .fail(xhr => {
            toastr.error(xhr.responseJSON?.detail || '创建房间失败');
        });
}

function joinRoom() {
    const code = $('#joinRoomCode').val().trim().toUpperCase();
    if (!code || code.length !== 6) {
        toastr.error('请输入6位房间代码');
        return;
    }
    
    API.post('/api/room/join/' + code)
        .done(res => {
            if (res.code === 200) {
                stopRoomListPolling();
                roomId = res.data.room_id;
                gameId = res.data.game_id;
                playerColor = res.data.player_color;
                
                board = Array(BOARD_SIZE).fill(null).map(() => Array(BOARD_SIZE).fill(null));
                
                $('#lobbyView').hide();
                $('#gameView').show();
                $('#yourColorInfo').show();
                $('#yourColor').text(playerColor === 'black' ? '黑棋' : '白棋').addClass(playerColor === 'black' ? 'text-dark' : 'text-white');
                
                $('#gameRoomCodeCard').show();
                $('#gameRoomCode').text(code);
                $('#waitingOverlay').hide();
                $('#roomStatus').text('游戏进行中').removeClass('bg-warning').addClass('bg-success');
                gameStarted = true;
                
                if (playerColor === 'white') {
                    $('#whitePlayer').text('你');
                    $('#blackPlayer').text('对手');
                    isMyTurn = false;
                }
                
                connectWebSocket();
                loadRoomInfo();
            }
        })
        .fail(xhr => {
            toastr.error(xhr.responseJSON?.detail || '加入房间失败');
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

function renderRoomList(rooms) {
    const container = $('#roomList');
    
    if (!rooms || rooms.length === 0) {
        container.html('<div class="list-group-item text-center text-muted py-4"><i class="bi bi-hourglass-split"></i> 暂无等待中的房间</div>');
        return;
    }
    
    container.empty();
    
    rooms.forEach(room => {
        container.append(`
            <a href="#" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center room-item" data-code="${room.room_code}">
                <div>
                    <strong>${room.room_code}</strong>
                    <small class="text-muted ms-2">${room.host_name}</small>
                </div>
                <span class="badge bg-success">等待中</span>
            </a>
        `);
    });
    
    $('.room-item').on('click', function(e) {
        e.preventDefault();
        const code = $(this).data('code');
        $('#joinRoomCode').val(code);
        joinRoom();
    });
}

function loadRoomInfo() {
    if (!roomId) return;
    
    API.get('/api/room/info/' + roomId)
        .done(res => {
            if (res.code === 200) {
                $('#blackPlayer').text(res.data.is_host ? '你' : '等待中...');
                if (!res.data.is_host && res.data.guest_id) {
                    $('#whitePlayer').text('你');
                }
            }
        });
}

function connectWebSocket() {
    const token = localStorage.getItem('access_token');
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/room/ws/${roomId}?token=${token}`;
    
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        console.log('WebSocket connected');
    };
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleWSMessage(data);
    };
    
    ws.onclose = () => {
        console.log('WebSocket disconnected');
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
            toastr.success('对手已加入，游戏开始!');
            
            if (playerColor === 'black') {
                isMyTurn = true;
                startTurnTimer();
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
                
                if (playerColor === currentPlayer) {
                    isMyTurn = true;
                    startTurnTimer();
                } else {
                    isMyTurn = false;
                    stopTurnTimer();
                }
            }
            
            if (data.status === 'playing') {
                $('#roomStatus').text('游戏进行中').addClass('bg-success');
                gameStarted = true;
                $('#waitingOverlay').hide();
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
    }
}

function handleClick(e) {
    if (!gameStarted || gameOver || !isMyTurn) return;
    if (playerColor !== currentPlayer) return;
    
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    
    const x = (e.clientX - rect.left) * scaleX;
    const y = (e.clientY - rect.top) * scaleY;
    
    const col = Math.round((x - PADDING) / CELL_SIZE);
    const row = Math.round((y - PADDING) / CELL_SIZE);
    
    if (row < 0 || row >= BOARD_SIZE || col < 0 || col >= BOARD_SIZE) return;
    if (board[row][col] !== null) return;
    
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'move', row, col }));
        board[row][col] = playerColor;
        lastMove = { row, col, player: playerColor };
        isMyTurn = false;
        stopTurnTimer();
        drawBoard();
    }
}

function requestUndo() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'undo' }));
        toastr.info('已发送悔棋请求');
    }
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
        $('#resultIcon').removeClass('bi-emoji-frown').addClass('bi-trophy-fill');
        $('#resultText').text('你赢了!');
        $('#resultModal .modal-header').removeClass('bg-danger').addClass('bg-success');
    } else {
        $('#resultIcon').removeClass('bi-trophy-fill').addClass('bi-emoji-frown');
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
