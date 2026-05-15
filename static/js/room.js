const BOARD_SIZE = 15;
const CELL_SIZE = 40;
const PADDING = 20;
const PIECE_RADIUS = 16;

let canvas, ctx;
let roomId = null;
let gameId = null;
let playerColor = null;
let board = [];
let currentPlayer = 'black';
let isMyTurn = false;
let gameOver = false;
let winningLine = null;
let lastMove = null;
let ws = null;
let gameStarted = false;

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
            }
        })
        .fail(() => {
            toastr.error('请先登录');
            setTimeout(() => location.href = '/', 1500);
        });
}

function createRoom() {
    API.post('/api/room/create')
        .done(res => {
            if (res.code === 200) {
                roomId = res.data.id;
                $('#roomCodeDisplay').show();
                $('#roomCode').text(res.data.room_code);
                $('#createRoomBtn').prop('disabled', true).html('<i class="bi bi-check"></i> 房间已创建');
                $('#waitingOverlay').show();
                $('#roomStatus').text('等待对手加入...').removeClass('bg-success').addClass('bg-warning');
                
                connectWebSocket();
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
                roomId = res.data.room_id;
                gameId = res.data.game_id;
                playerColor = res.data.player_color;
                
                board = Array(BOARD_SIZE).fill(null).map(() => Array(BOARD_SIZE).fill(null));
                
                $('#lobbyView').hide();
                $('#gameView').show();
                $('#yourColorInfo').show();
                $('#yourColor').text(playerColor === 'black' ? '黑棋' : '白棋').addClass(playerColor === 'black' ? 'text-dark' : 'text-white');
                
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
    
    setInterval(loadRoomList, 5000);
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
            }
            break;
            
        case 'game_state':
            if (data.game) {
                board = data.game.board;
                const moves = data.game.moves || [];
                if (moves.length > 0) {
                    lastMove = { row: moves[moves.length - 1][0], col: moves[moves.length - 1][1], player: moves[moves.length - 1][2] === 1 ? 'black' : 'white' };
                }
                currentPlayer = data.game.current_player === 1 ? 'black' : 'white';
                
                if (playerColor === currentPlayer) {
                    isMyTurn = true;
                } else {
                    isMyTurn = false;
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
            board[data.row][data.col] = data.player;
            lastMove = { row: data.row, col: data.col, player: data.player };
            drawBoard();
            
            if (data.player === currentPlayer) {
                isMyTurn = true;
            } else {
                isMyTurn = false;
            }
            
            if (data.game_over) {
                endGame(data.player, data.winning_line);
            }
            break;
            
        case 'undo':
            const moves = Object.values(board).flat().filter(x => x !== null);
            if (moves.length > 0) {
                const lastMovePos = findLastMove();
                if (lastMovePos) {
                    board[lastMovePos.row][lastMovePos.col] = null;
                    lastMove = findLastMove();
                }
            }
            drawBoard();
            toastr.info('对方请求悔棋，已撤销一步');
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
    
    if (winningLine) {
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
