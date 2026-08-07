const gameNames = {gomoku: '五子棋', go: '围棋', xiangqi: '中国象棋', chess: '国际象棋'};
const outcomeNames = {win: '胜', loss: '负', draw: '和'};
let historyItems = new Map();

$(function () {
    loadHistory();
    $('#refreshHistoryBtn').on('click', loadHistory);
    $(document).on('click', '.open-replay', function () { openReplay(Number(this.dataset.id)); });
});

function loadHistory() {
    const $table = $('#historyTable');
    $table.html('<tr><td colspan="6" class="text-center text-muted py-4"><div class="spinner-border spinner-border-sm"></div></td></tr>');
    $('#historyEmpty').addClass('d-none');
    API.get('/api/games/history').done(res => {
        const items = res.data || [];
        historyItems = new Map(items.map(item => [item.id, item]));
        renderHistory(items);
    }).fail(xhr => {
        if (xhr.status === 401) return;
        $table.html('<tr><td colspan="6" class="text-center text-muted py-4">加载历史对局失败</td></tr>');
    });
}

function renderHistory(items) {
    const $table = $('#historyTable');
    $table.empty();
    if (!items.length) { $('#historyEmpty').removeClass('d-none'); return; }
    items.forEach(item => {
        const outcome = item.outcome || 'draw';
        $table.append(`<tr>
            <td><span class="badge bg-secondary">${escapeHtml(gameNames[item.game_code] || item.game_code)}</span></td>
            <td>${escapeHtml(item.opponent || 'AI')}</td>
            <td><span class="history-outcome history-outcome-${outcome}">${outcomeNames[outcome]}</span></td>
            <td>${formatDuration(item.duration_seconds)}</td>
            <td class="text-muted">${formatDate(item.ended_at || item.created_at)}</td>
            <td class="text-end"><button class="btn btn-sm btn-outline-light open-replay" data-id="${item.id}"><i class="bi bi-eye"></i> 查看棋局</button></td>
        </tr>`);
    });
}

function openReplay(recordId) {
    const item = historyItems.get(recordId);
    API.get(`/api/games/replays/${recordId}`).done(res => {
        const replay = res.data;
        if (!replay.state) { toastr.warning('该旧记录未保存终局棋盘'); return; }
        $('#replayTitle').text(`${gameNames[replay.game_code] || replay.game_code} - 终局棋盘`);
        $('#replayMeta').text(`${item?.opponent || 'AI'} · ${outcomeNames[item?.outcome] || '和'} · ${formatDuration(item?.duration_seconds)}`);
        drawReplay(replay.game_code, replay.state);
        bootstrap.Modal.getOrCreateInstance(document.getElementById('replayModal')).show();
    }).fail(xhr => toastr.error(xhr.responseJSON?.detail || '加载棋局失败'));
}

function drawReplay(game, state) {
    const canvas = document.getElementById('replayCanvas');
    canvas.width = 720;
    canvas.height = game === 'xiangqi' ? 798 : 720;
    const ctx = canvas.getContext('2d');
    if (game === 'chess') drawChess(ctx, state);
    else if (game === 'xiangqi') drawXiangqi(ctx, state);
    else drawGrid(ctx, state, game);
}

function drawGrid(ctx, state, game) {
    const n = game === 'go' ? 19 : 15, p = game === 'go' ? 32 : 42, cell = (720 - p * 2) / (n - 1);
    const wood = ctx.createLinearGradient(0, 0, 720, 720); wood.addColorStop(0, '#dcb379'); wood.addColorStop(1, '#a97845');
    ctx.fillStyle = wood; ctx.fillRect(0, 0, 720, 720); ctx.strokeStyle = 'rgba(47,28,15,.68)'; ctx.lineWidth = 1.4;
    for (let i = 0; i < n; i++) { ctx.beginPath(); ctx.moveTo(p, p + i * cell); ctx.lineTo(720 - p, p + i * cell); ctx.moveTo(p + i * cell, p); ctx.lineTo(p + i * cell, 720 - p); ctx.stroke(); }
    const stars = n === 19 ? [3, 9, 15] : [3, 7, 11]; ctx.fillStyle = '#382212';
    stars.forEach(r => stars.forEach(c => { ctx.beginPath(); ctx.arc(p + c * cell, p + r * cell, 3.5, 0, Math.PI * 2); ctx.fill(); }));
    (state.board || []).forEach((row, r) => row.forEach((piece, c) => {
        if (!piece) return; const x = p + c * cell, y = p + r * cell;
        ctx.fillStyle = piece === 1 ? '#111' : '#f7f1e5'; ctx.strokeStyle = piece === 1 ? '#444' : '#8d867a'; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.arc(x, y, cell * .4, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    }));
}

function drawChess(ctx, state) {
    const p = 28, cell = 83, glyph = {k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟'};
    ctx.fillStyle = '#201a17'; ctx.fillRect(0, 0, 720, 720);
    for (let r = 0; r < 8; r++) for (let c = 0; c < 8; c++) { ctx.fillStyle = (r + c) % 2 ? '#88705d' : '#e9d9bd'; ctx.fillRect(p + c * cell, p + r * cell, cell, cell); }
    Object.entries(state.board || {}).forEach(([sq, piece]) => { const c = sq.charCodeAt(0) - 97, r = 8 - Number(sq[1]), x = p + c * cell + cell / 2, y = p + r * cell + cell / 2; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.font = '64px serif'; ctx.lineWidth = 3; ctx.strokeStyle = piece === piece.toUpperCase() ? '#3d3028' : '#efe4d2'; ctx.fillStyle = piece === piece.toUpperCase() ? '#fffaf1' : '#171313'; ctx.strokeText(glyph[piece.toLowerCase()], x, y + 2); ctx.fillText(glyph[piece.toLowerCase()], x, y + 2); });
}

function drawXiangqi(ctx, state) {
    const p = 48, cell = (720 - p * 2) / 8, height = 798, chars = {r: '车', h: '马', e: '相', a: '仕', k: '帅', c: '炮', p: '兵'};
    const wood = ctx.createLinearGradient(0, 0, 0, height); wood.addColorStop(0, '#e1bd82'); wood.addColorStop(1, '#b47c47'); ctx.fillStyle = wood; ctx.fillRect(0, 0, 720, height); ctx.strokeStyle = 'rgba(54,31,17,.78)'; ctx.lineWidth = 2;
    for (let r = 0; r < 10; r++) { ctx.beginPath(); ctx.moveTo(p, p + r * cell); ctx.lineTo(p + 8 * cell, p + r * cell); ctx.stroke(); }
    for (let c = 0; c < 9; c++) { ctx.beginPath(); ctx.moveTo(p + c * cell, p); ctx.lineTo(p + c * cell, p + 4 * cell); ctx.moveTo(p + c * cell, p + 5 * cell); ctx.lineTo(p + c * cell, p + 9 * cell); ctx.stroke(); }
    ctx.fillStyle = '#67401f'; ctx.font = '28px serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('楚 河', p + 2.5 * cell, p + 4.5 * cell); ctx.fillText('汉 界', p + 5.5 * cell, p + 4.5 * cell);
    ctx.beginPath(); ctx.moveTo(p + 3 * cell, p); ctx.lineTo(p + 5 * cell, p + 2 * cell); ctx.moveTo(p + 5 * cell, p); ctx.lineTo(p + 3 * cell, p + 2 * cell); ctx.moveTo(p + 3 * cell, p + 7 * cell); ctx.lineTo(p + 5 * cell, p + 9 * cell); ctx.moveTo(p + 5 * cell, p + 7 * cell); ctx.lineTo(p + 3 * cell, p + 9 * cell); ctx.stroke();
    (state.board || []).forEach((row, r) => row.forEach((piece, c) => { if (piece === '0') return; const x = p + c * cell, y = p + r * cell, red = piece === piece.toUpperCase(); ctx.fillStyle = red ? '#f4d4a4' : '#e8dfc9'; ctx.strokeStyle = red ? '#a52e2b' : '#29251f'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 30, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); ctx.fillStyle = ctx.strokeStyle; ctx.font = '30px serif'; ctx.fillText(chars[piece.toLowerCase()], x, y + 1); }));
}

function formatDuration(seconds) { if (seconds == null) return '-'; const m = Math.floor(seconds / 60), s = seconds % 60; return m ? `${m}分${s}秒` : `${s}秒`; }
function formatDate(value) { if (!value) return '-'; const date = new Date(value); return Number.isNaN(date.valueOf()) ? '-' : date.toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'}); }
function escapeHtml(value) { return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
