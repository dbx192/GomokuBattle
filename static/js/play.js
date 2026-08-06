const APP = document.getElementById('playApp');
const GAME = APP.dataset.gameCode;
const canvas = document.getElementById('boardCanvas');
const ctx = canvas.getContext('2d');
let sessionId = null, room = null, socket = null, state = null, playerColor = null, selected = null;
let catalog = {};
let mode = 'ai';
let aiPollTimer = null;

const names = {gomoku: '五子棋', go: '围棋', xiangqi: '中国象棋', chess: '国际象棋'};

$(function () {
    document.getElementById('gameTitle').textContent = names[GAME];
    document.getElementById('gameMark').textContent = {gomoku: '五', go: '围', xiangqi: '象', chess: '♞'}[GAME];
    document.getElementById('boardLabel').textContent = names[GAME];
    API.get('/api/games')
        .done(response => { catalog = Object.fromEntries(response.data.map(item => [item.code, item])); })
        .fail(() => { catalog = {}; toastr.warning('棋种目录暂时不可用，仍可开始对局'); });
    $('#startBtn').on('click', start);
    $('#joinBtn').on('click', join);
    $('#passBtn').on('click', () => sendAction('pass'));
    $('#resignBtn').on('click', () => sendAction('resign'));
    $('.mode-choice').on('click', function () { mode = this.dataset.mode; $('.mode-choice').removeClass('is-active'); $(this).addClass('is-active'); updateMode(); });
    canvas.addEventListener('click', clickBoard);
    updateMode(); draw();
});

function updateMode() {
    const roomMode = mode === 'room';
    $('#roomControls').toggleClass('d-none', !roomMode);
    $('#difficultyControl').toggleClass('d-none', roomMode);
    $('#startBtn').html(roomMode ? '<i class="bi bi-plus-lg"></i> 创建房间' : '<i class="bi bi-play-fill"></i> 开始对局');
}

function authHeaders() { return localStorage.getItem('access_token') ? {} : null; }
function needAuth() { if (!authHeaders()) { showLoginModal(); return false; } return true; }

function start() {
    if (!needAuth()) return;
    if (mode === 'room') {
        API.post('/api/match-rooms', {game_code: GAME}).done(res => { room = res.data; playerColor = colors()[0]; activateRoom(); }).fail(showError);
        return;
    }
    API.post(`/api/games/${GAME}/sessions`, {difficulty: $('#difficultySelect').val()}).done(res => {
        clearAiPolling(); sessionId = res.data.game_id; playerColor = res.data.player_color; state = res.data.state; active(); monitorAiTurn();
    }).fail(showError);
}

function join() {
    if (!needAuth()) return;
    const code = $('#roomCodeInput').val().trim().toUpperCase(); if (!code) return;
    API.post(`/api/match-rooms/${code}/join`, {}).done(res => { room = res.data; playerColor = room.host_id === currentUserId() ? colors()[0] : colors()[1]; activateRoom(); }).fail(showError);
}

function currentUserId() { try { return JSON.parse(localStorage.getItem('user') || '{}').id; } catch (_) { return null; } }
function colors() { return GAME === 'xiangqi' ? ['red','black'] : ['black','white']; }
function active() {
    const isTurn = state && state.current_player === playerColor && !state.result;
    $('#gameStatus').text(state?.ai_error ? state.ai_error : (state?.result ? `对局结束 · ${state.result.reason}` : (isTurn ? '轮到你落子' : 'AI 正在思考')));
    $('#turnPill').text(state?.result ? '已结束' : (isTurn ? '你的回合' : '对手回合')).toggleClass('is-your-turn', !!isTurn);
    $('#playerSide').text(playerColor || '等待开始');
    $('#resignBtn').prop('disabled', !state || !!state.result);
    $('#passBtn').toggleClass('d-none', GAME !== 'go');
    draw();
}
function clearAiPolling() { if (aiPollTimer) { clearTimeout(aiPollTimer); aiPollTimer = null; } }
function monitorAiTurn() {
    clearAiPolling();
    if (room || !sessionId || !state || state.result || state.ai_error || state.current_player === playerColor) return;
    aiPollTimer = setTimeout(() => API.get(`/api/games/${GAME}/sessions/${sessionId}`).done(res => {
        state = res.data.state; active(); monitorAiTurn();
    }).fail(showError), 300);
}
function activateRoom() {
    state = room.state; active(); $('#roomInfo').removeClass('d-none').html(`<span>房间码</span><strong>${room.room_code}</strong><small>分享给好友加入</small>`);
    const token = localStorage.getItem('access_token'); const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(`${proto}//${location.host}/api/match-rooms/${room.room_id}/ws?token=${encodeURIComponent(token)}`);
    socket.onmessage = event => { const data = JSON.parse(event.data); if (data.type === 'error') return toastr.error(data.message); if (data.type === 'role') playerColor = data.color; if (data.state) { room = data; state = data.state; active(); renderClock(); } };
    socket.onclose = () => { if (room && room.status === 'playing') $('#gameStatus').text('连接已关闭，请刷新重连'); };
}

function sendAction(type, move) {
    if (room) { if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({type, move})); return; }
    if (!sessionId) return;
    if (type === 'move') API.post(`/api/games/${GAME}/sessions/move`, {game_id: sessionId, move}).done(res => { state = res.data.state; active(); monitorAiTurn(); }).fail(showError);
    else if (type === 'pass') API.post(`/api/games/go/sessions/pass`, {game_id: sessionId}).done(res => { state = res.data.state; active(); monitorAiTurn(); }).fail(showError);
    else if (type === 'resign') API.post(`/api/games/${GAME}/sessions/resign`, {game_id: sessionId}).done(res => { clearAiPolling(); state = res.data.state; active(); }).fail(showError);
}

function showError(xhr) { toastr.error(xhr.responseJSON?.detail || '操作失败'); }
function clickBoard(event) {
    if (!state || state.result || state.current_player !== playerColor) return;
    const rect = canvas.getBoundingClientRect(), x = (event.clientX - rect.left) * canvas.width / rect.width, y = (event.clientY - rect.top) * canvas.height / rect.height;
    if (GAME === 'gomoku' || GAME === 'go') { const n = GAME === 'go' ? 19 : 15, p = GAME === 'go' ? 32 : 42, cell = (canvas.width - p * 2) / (n - 1); const row = Math.round((y-p)/cell), col = Math.round((x-p)/cell); if (row>=0&&row<n&&col>=0&&col<n) sendAction('move',{row,col}); return; }
    if (GAME === 'xiangqi') {
        const p=48, cellX=(canvas.width-p*2)/8, cellY=(canvas.height-p*2)/9, row=Math.round((y-p)/cellY), col=Math.round((x-p)/cellX);
        if(row<0||row>9||col<0||col>8)return;
        const piece = state.board[row][col];
        const isOwnPiece = piece !== '0' && (playerColor === 'red' ? piece === piece.toUpperCase() : piece === piece.toLowerCase());
        if (!selected) {
            if (!isOwnPiece) { toastr.info('请先选择自己的棋子'); return; }
            selected={row,col}; draw(); return;
        }
        if (isOwnPiece) { selected={row,col}; draw(); return; }
        sendAction('move',{from_row:selected.row,from_col:selected.col,to_row:row,to_col:col}); selected=null;
        return;
    }
    const p=40, cell=(canvas.width-p*2)/8, row=Math.floor((y-p)/cell), col=Math.floor((x-p)/cell); if(row<0||row>7||col<0||col>7)return; const square=String.fromCharCode(97+col)+(8-row); if(!selected){selected=square;draw();}else{let uci=selected+square; const piece=state.board[selected]; if(piece?.toLowerCase()==='p'&&(square.endsWith('8')||square.endsWith('1'))) uci+=prompt('升变棋子：q/r/b/n','q')||'q'; sendAction('move',{uci});selected=null;} 
}

function draw() { ctx.clearRect(0,0,720,720); if (GAME === 'chess') drawChess(); else if (GAME === 'xiangqi') drawXiangqi(); else drawGrid(); }
function recentMove() { const history = state?.history || []; return history.length ? history[history.length - 1] : null; }
function markRecentPoint(x, y, radius) {
    ctx.save();
    ctx.fillStyle = 'rgba(49, 196, 157, .22)';
    ctx.strokeStyle = '#35c9a0';
    ctx.lineWidth = 4;
    ctx.shadowColor = 'rgba(20, 220, 170, .65)';
    ctx.shadowBlur = 12;
    ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    ctx.shadowBlur = 0; ctx.fillStyle = '#eafff8';
    ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
}
function markRecentSquare(c, r, cell, p) {
    ctx.save();
    ctx.fillStyle = 'rgba(49, 196, 157, .18)';
    ctx.strokeStyle = '#35c9a0';
    ctx.lineWidth = 4;
    ctx.shadowColor = 'rgba(20, 220, 170, .55)'; ctx.shadowBlur = 10;
    ctx.fillRect(p + c * cell + 3, p + r * cell + 3, cell - 6, cell - 6);
    ctx.strokeRect(p + c * cell + 3, p + r * cell + 3, cell - 6, cell - 6);
    ctx.restore();
}
function drawGrid() {
    const n = GAME === 'go' ? 19 : 15, p = GAME === 'go' ? 32 : 42, cell = (720 - p * 2) / (n - 1);
    const wood = ctx.createLinearGradient(0, 0, 720, 720); wood.addColorStop(0, '#dcb379'); wood.addColorStop(.5, '#c4935c'); wood.addColorStop(1, '#a97845');
    ctx.fillStyle = wood; ctx.fillRect(0, 0, 720, 720);
    ctx.strokeStyle = 'rgba(47, 28, 15, .68)'; ctx.lineWidth = GAME === 'go' ? 1.25 : 1.5;
    for (let i=0;i<n;i++) { ctx.beginPath(); ctx.moveTo(p, i*cell+p); ctx.lineTo(720-p, i*cell+p); ctx.moveTo(i*cell+p,p); ctx.lineTo(i*cell+p,720-p); ctx.stroke(); }
    const stars = n === 19 ? [3,9,15] : [3,7,11]; ctx.fillStyle = 'rgba(49,30,16,.8)'; stars.forEach(r => stars.forEach(c => { ctx.beginPath(); ctx.arc(p+c*cell,p+r*cell, n===19?4:3.5,0,Math.PI*2);ctx.fill(); }));
    if (!state) return;
    state.board.forEach((row,r)=>row.forEach((piece,c)=>{ if(!piece)return; const x=p+c*cell,y=p+r*cell; ctx.save(); ctx.shadowColor='rgba(25,15,5,.42)';ctx.shadowBlur=8;ctx.shadowOffsetY=3;const g=ctx.createRadialGradient(x-cell*.14,y-cell*.16,cell*.04,x,y,cell*.43);if(piece===1){g.addColorStop(0,'#4b4b4b');g.addColorStop(.3,'#191919');g.addColorStop(1,'#050505');}else{g.addColorStop(0,'#fffdf6');g.addColorStop(.72,'#e8e3d5');g.addColorStop(1,'#bdb8aa');}ctx.fillStyle=g;ctx.beginPath();ctx.arc(x,y,cell*.405,0,Math.PI*2);ctx.fill();ctx.restore(); }));
    const last = recentMove();
    if (last && Number.isInteger(last.row) && Number.isInteger(last.col)) markRecentPoint(p + last.col * cell, p + last.row * cell, Math.max(10, cell * .24));
}
function drawChess() {
    const p=28, cell=83; ctx.fillStyle='#201a17';ctx.fillRect(0,0,720,720);
    for(let r=0;r<8;r++)for(let c=0;c<8;c++){ctx.fillStyle=(r+c)%2?'#88705d':'#e9d9bd';ctx.fillRect(p+c*cell,p+r*cell,cell,cell);}
    if(!state)return; const glyph={k:'♚',q:'♛',r:'♜',b:'♝',n:'♞',p:'♟'};
    const last = recentMove();
    if (last?.uci?.length >= 4) {
        const fromCol = last.uci.charCodeAt(0) - 97, fromRow = 8 - Number(last.uci[1]);
        const toCol = last.uci.charCodeAt(2) - 97, toRow = 8 - Number(last.uci[3]);
        if (fromCol >= 0 && fromCol < 8 && toCol >= 0 && toCol < 8) { markRecentSquare(fromCol, fromRow, cell, p); markRecentSquare(toCol, toRow, cell, p); }
    }
    for(const [sq,piece] of Object.entries(state.board)){const c=sq.charCodeAt(0)-97,r=8-Number(sq[1]),x=p+c*cell+cell/2,y=p+r*cell+cell/2;ctx.save();ctx.textAlign='center';ctx.textBaseline='middle';ctx.font='64px "DejaVu Sans", serif';ctx.lineWidth=3;ctx.strokeStyle=piece===piece.toUpperCase()?'#3d3028':'#efe4d2';ctx.fillStyle=piece===piece.toUpperCase()?'#fffaf1':'#171313';ctx.strokeText(glyph[piece.toLowerCase()],x,y+2);ctx.fillText(glyph[piece.toLowerCase()],x,y+2);ctx.restore();}
    if(selected){const c=selected.charCodeAt(0)-97,r=8-Number(selected[1]);ctx.strokeStyle='#d9a85f';ctx.lineWidth=5;ctx.strokeRect(p+c*cell+3,p+r*cell+3,cell-6,cell-6);}
}
function drawXiangqi() {
    const p=48, cellX=(720-p*2)/8, cellY=(720-p*2)/9;
    const wood=ctx.createLinearGradient(0,0,0,720);wood.addColorStop(0,'#e1bd82');wood.addColorStop(1,'#b47c47');ctx.fillStyle=wood;ctx.fillRect(0,0,720,720);ctx.strokeStyle='rgba(54,31,17,.78)';ctx.lineWidth=2;
    for(let r=0;r<10;r++){ctx.beginPath();ctx.moveTo(p,p+r*cellY);ctx.lineTo(p+8*cellX,p+r*cellY);ctx.stroke();}
    for(let c=0;c<9;c++){ctx.beginPath();ctx.moveTo(p+c*cellX,p);ctx.lineTo(p+c*cellX,p+4*cellY);ctx.moveTo(p+c*cellX,p+5*cellY);ctx.lineTo(p+c*cellX,p+9*cellY);ctx.stroke();}
    ctx.fillStyle='rgba(85,49,25,.72)';ctx.font='28px "Noto Serif SC",serif';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText('楚 河',p+2*cellX+cellX/2,p+4.5*cellY);ctx.fillText('汉 界',p+5*cellX+cellX/2,p+4.5*cellY);
    ctx.beginPath();ctx.moveTo(p+3*cellX,p);ctx.lineTo(p+5*cellX,p+2*cellY);ctx.moveTo(p+5*cellX,p);ctx.lineTo(p+3*cellX,p+2*cellY);ctx.moveTo(p+3*cellX,p+7*cellY);ctx.lineTo(p+5*cellX,p+9*cellY);ctx.moveTo(p+5*cellX,p+7*cellY);ctx.lineTo(p+3*cellX,p+9*cellY);ctx.stroke();
    if(!state)return;const chars={r:'车',h:'马',e:'相',a:'仕',k:'帅',c:'炮',p:'兵'};const last=recentMove();if(last&&Number.isInteger(last.from_row)&&Number.isInteger(last.to_row)){markRecentPoint(p+last.from_col*cellX,p+last.from_row*cellY,34);markRecentPoint(p+last.to_col*cellX,p+last.to_row*cellY,34);}state.board.forEach((row,r)=>row.forEach((piece,c)=>{if(piece==='0')return;const x=p+c*cellX,y=p+r*cellY;ctx.save();ctx.shadowColor='rgba(39,20,8,.4)';ctx.shadowBlur=6;ctx.shadowOffsetY=3;const g=ctx.createRadialGradient(x-9,y-10,3,x,y,29);if(piece===piece.toUpperCase()){g.addColorStop(0,'#ffe7bd');g.addColorStop(1,'#c8864f');}else{g.addColorStop(0,'#fbf0d9');g.addColorStop(1,'#bca789');}ctx.fillStyle=g;ctx.beginPath();ctx.arc(x,y,30,0,Math.PI*2);ctx.fill();ctx.strokeStyle=piece===piece.toUpperCase()?'#a52e2b':'#29251f';ctx.lineWidth=2;ctx.stroke();ctx.fillStyle=piece===piece.toUpperCase()?'#a52e2b':'#29251f';ctx.font='30px "Noto Serif SC",serif';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(chars[piece.toLowerCase()],x,y+1);ctx.restore();}));
    if(selected){ctx.strokeStyle='#f0bf70';ctx.lineWidth=4;ctx.strokeRect(p+selected.col*cellX-35,p+selected.row*cellY-35,70,70);}
}
function renderClock(){if(!room?.clocks)return;const c=room.clocks;$('#clock').text(c.mode==='fischer'?`${Math.ceil(c[colors()[0]]||0)}s / ${Math.ceil(c[colors()[1]]||0)}s`:`每步 ${c.seconds}s`)}
