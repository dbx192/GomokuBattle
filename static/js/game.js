const BOARD_SIZE = 15;
const CELL_SIZE = 40;
const PADDING = 20;
const PIECE_RADIUS = 16;

let canvas, ctx;
let gameId = null;
let board = Array(BOARD_SIZE).fill(null).map(() => Array(BOARD_SIZE).fill(null));
let currentPlayer = 'black';
let isMyTurn = true;
let gameOver = false;
let winningLine = null;
let lastMove = null;
// 落子历史：按真实落子顺序记录 [{row, col, player}, ...]
// 用于悔棋时精确定位要清除的棋子，避免按坐标扫描误清
let movesHistory = [];

$(function() {
    canvas = document.getElementById('gameCanvas');
    ctx = canvas.getContext('2d');
    
    canvas.width = BOARD_SIZE * CELL_SIZE + PADDING * 2;
    canvas.height = BOARD_SIZE * CELL_SIZE + PADDING * 2;
    
    canvas.addEventListener('click', handleClick);
    
    $('#startGameBtn').on('click', startGame);
    $('#undoBtn').on('click', undoMove);
    $('#restartBtn').on('click', restartGame);
    
    drawBoard();
    
    checkAuth();
});

function checkAuth() {
    const token = localStorage.getItem('access_token');
    if (!token) {
        // 不跳转、不弹红 toast —— 直接弹登录框让用户登录
        showLoginModal();
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
            } else {
                // 业务码非 200：清 token + 弹登录框
                localStorage.removeItem('access_token');
                showLoginModal();
            }
        });
        // 401 由全局 ajaxError 兜底（清 token + 弹登录框），不在这里重复处理
}

function startGame() {
    API.post('/api/game/ai/start')
        .done(res => {
            if (res.code === 200) {
                gameId = res.data.game_id;
                board = Array(BOARD_SIZE).fill(null).map(() => Array(BOARD_SIZE).fill(null));
                currentPlayer = 'black';
                isMyTurn = true;
                gameOver = false;
                winningLine = null;
                lastMove = null;
                movesHistory = [];
                
                $('#startGameBtn').hide();
                $('#undoBtn').prop('disabled', true);
                $('#gameStatus').html('<span class="badge bg-success">进行中 - 你的回合</span>');
                $('#turnIndicator').html(`
                    <div class="text-center">
                        <i class="bi bi-circle-fill text-dark" style="font-size: 1.5rem;"></i>
                        <div><small>你</small></div>
                    </div>
                    <div class="text-center mx-3">
                        <span class="badge bg-primary">VS</span>
                    </div>
                    <div class="text-center">
                        <i class="bi bi-circle text-white border border-dark" style="font-size: 1.5rem;"></i>
                        <div><small>AI</small></div>
                    </div>
                `);
                
                $('#historyCard').show();
                drawBoard();
                loadHistory();
            } else {
                toastr.error(res.message || '开始对局失败');
            }
        })
        .fail(xhr => {
            // 401 由全局 ajaxError 处理弹登录框；这里只处理其他错误
            if (xhr.status !== 401) {
                toastr.error('开始对局失败，请稍后重试');
            }
        });
}

function handleClick(e) {
    if (gameOver || !isMyTurn || !gameId) return;
    
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    
    const x = (e.clientX - rect.left) * scaleX;
    const y = (e.clientY - rect.top) * scaleY;
    
    const col = Math.round((x - PADDING) / CELL_SIZE);
    const row = Math.round((y - PADDING) / CELL_SIZE);
    
    if (row < 0 || row >= BOARD_SIZE || col < 0 || col >= BOARD_SIZE) return;
    if (board[row][col] !== null) return;
    
    makeMove(row, col);
}

function makeMove(row, col) {
    API.post('/api/game/ai/move', { game_id: gameId, row, col })
        .done(res => {
            if (res.code === 200) {
                const playerMove = res.data.player_move;
                board[playerMove.row][playerMove.col] = 'black';
                lastMove = { row: playerMove.row, col: playerMove.col, player: 'black' };
                movesHistory.push({ row: playerMove.row, col: playerMove.col, player: 'black' });

                drawBoard();

                if (playerMove.game_over) {
                    endGame(playerMove.winner, res.data.ai_move?.winning_line || playerMove.winning_line);
                    return;
                }

                isMyTurn = false;
                $('#undoBtn').prop('disabled', true);
                $('#gameStatus').html('<span class="badge bg-warning">进行中 - AI思考中...</span>');

                setTimeout(() => {
                    const aiMove = res.data.ai_move;
                    if (aiMove) {
                        board[aiMove.row][aiMove.col] = 'white';
                        lastMove = { row: aiMove.row, col: aiMove.col, player: 'white' };
                        movesHistory.push({ row: aiMove.row, col: aiMove.col, player: 'white' });
                        drawBoard();

                        if (aiMove.game_over) {
                            endGame(aiMove.winner, aiMove.winning_line);
                            return;
                        }

                        isMyTurn = true;
                        $('#undoBtn').prop('disabled', false);
                        $('#gameStatus').html('<span class="badge bg-success">进行中 - 你的回合</span>');
                    }
                }, 500);
            }
        })
        .fail(xhr => {
            if (xhr.status === 401) return;  // 全局 401 处理会弹登录框
            toastr.error(xhr.responseJSON?.detail || '落子失败');
        });
}

function undoMove() {
    API.post('/api/game/ai/undo', { game_id: gameId })
        .done(res => {
            if (res.code === 200 && res.data.success) {
                // 服务端悔棋会同时撤销玩家和 AI 的最后一步（共 2 手）
                // 必须按真实落子顺序从历史里 pop，而不是扫描棋盘找"最后"某色棋子
                // （扫描法会把坐标靠下/靠右的早期棋子误当成"最后"清掉，导致本地和服务端脱钩）
                if (movesHistory.length >= 2) {
                    const aiLast = movesHistory.pop();  // AI 的最后一手
                    const playerLast = movesHistory.pop();  // 玩家的最后一手
                    if (aiLast) board[aiLast.row][aiLast.col] = null;
                    if (playerLast) board[playerLast.row][playerLast.col] = null;
                    // 更新"最后一手"标记：玩家悔的是玩家那手，所以最后落子显示回到玩家那手之前；
                    // 这里取 movesHistory 的最后一个元素（即再上一手玩家棋）
                    lastMove = movesHistory.length > 0
                        ? movesHistory[movesHistory.length - 1]
                        : null;
                }
                drawBoard();
                toastr.success('已撤销');
            }
        });
}

function findLastMove(player) {
    for (let i = board.length - 1; i >= 0; i--) {
        for (let j = board[i].length - 1; j >= 0; j--) {
            if (board[i][j] === player) {
                return { row: i, col: j };
            }
        }
    }
    return null;
}

function endGame(winner, line) {
    gameOver = true;
    winningLine = line;
    
    $('#undoBtn').prop('disabled', true);
    
    if (winner === 'black') {
        $('#resultIcon').removeClass('bi-emoji-frown').addClass('bi-trophy-fill');
        $('#resultText').text('你赢了!');
        $('#resultDetail').text('恭喜你战胜了AI');
        $('#resultModal .modal-header').removeClass('bg-danger').addClass('bg-success');
        $('#gameStatus').html('<span class="badge bg-success">你赢了!</span>');
    } else {
        $('#resultIcon').removeClass('bi-trophy-fill').addClass('bi-emoji-frown');
        $('#resultText').text('AI获胜');
        $('#resultDetail').text('再接再厉');
        $('#resultModal .modal-header').removeClass('bg-success').addClass('bg-danger');
        $('#gameStatus').html('<span class="badge bg-danger">AI获胜</span>');
    }
    
    drawBoard();
    $('#resultModal').modal('show');
}

function restartGame() {
    gameId = null;
    board = Array(BOARD_SIZE).fill(null).map(() => Array(BOARD_SIZE).fill(null));
    currentPlayer = 'black';
    isMyTurn = true;
    gameOver = false;
    winningLine = null;
    lastMove = null;
    movesHistory = [];
    
    $('#startGameBtn').show();
    $('#undoBtn').prop('disabled', true);
    $('#gameStatus').html('<span class="badge bg-secondary">等待开始</span>');
    $('#turnIndicator').html(`
        <div class="text-center">
            <i class="bi bi-circle-fill text-dark" style="font-size: 1.5rem;"></i>
            <div><small>你</small></div>
        </div>
        <div class="text-center mx-3">
            <span class="badge bg-primary">VS</span>
        </div>
        <div class="text-center">
            <i class="bi bi-circle text-white border border-dark" style="font-size: 1.5rem;"></i>
            <div><small>AI</small></div>
        </div>
    `);
    
    drawBoard();
}

function loadHistory() {
    API.get('/api/game/history?page=1&page_size=5')
        .done(res => {
            if (res.code === 200) {
                renderHistory(res.data.items);
            }
        });
}

function renderHistory(games) {
    const container = $('#gameHistory');
    container.empty();
    
    if (!games || games.length === 0) {
        container.append('<div class="list-group-item text-center text-muted py-3">暂无对局记录</div>');
        return;
    }
    
    games.forEach(game => {
        const result = game.winner_id ? '胜' : '负';
        const resultClass = game.winner_id ? 'text-success' : 'text-danger';
        const typeText = game.game_type === 'ai' ? '人机' : '房间';
        
        container.append(`
            <div class="list-group-item">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <i class="bi bi-calendar3"></i> ${new Date(game.created_at).toLocaleDateString()}
                        <span class="badge bg-secondary ms-2">${typeText}</span>
                    </div>
                    <span class="${resultClass} fw-bold">${result}</span>
                </div>
            </div>
        `);
    });
}

function drawBoard() {
    // Rich warm wood background
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
        // Glow
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

        // Core line
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

    // Shadow under piece
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
