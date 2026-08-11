const LOBBY_GAME_NAMES = {gomoku: '五子棋', go: '围棋', xiangqi: '中国象棋', chess: '国际象棋'};

$(function () {
    loadPlayingRooms();
    loadLobbyHistory();
    window.setInterval(loadPlayingRooms, 15000);
});

function loadPlayingRooms() {
    API.get('/api/match-rooms/playing', {limit: 8})
        .done(response => renderPlayingRooms(response.data || []))
        .fail(() => {
            $('#playingRoomCount').text('加载失败');
            $('#playingRoomsTable').html('<tr><td colspan="3" class="text-center text-muted py-3">暂时无法加载实时对局</td></tr>');
        });
}

function loadLobbyHistory() {
    API.get('/api/match-rooms/history', {limit: 8})
        .done(response => renderLobbyHistory(response.data || []))
        .fail(() => $('#lobbyHistoryTable').html('<tr><td colspan="4" class="text-center text-muted py-3">暂时无法加载对战历史</td></tr>'));
}

function renderPlayingRooms(items) {
    const $table = $('#playingRoomsTable').empty();
    $('#playingRoomCount').text(items.length ? `${items.length} 局进行中` : '暂无对局');
    if (!items.length) {
        $table.html('<tr><td colspan="3" class="text-center text-muted py-3">暂无正在进行的公开对局</td></tr>');
        return;
    }
    items.forEach(item => {
        const game = encodeURIComponent(item.game_code);
        const room = encodeURIComponent(item.room_code);
        $table.append(`<tr>
            <td><span class="badge bg-secondary">${escapeLobbyHtml(LOBBY_GAME_NAMES[item.game_code] || item.game_code)}</span></td>
            <td>${escapeLobbyHtml(item.host_name || '玩家一')} <span class="text-muted">vs</span> ${escapeLobbyHtml(item.guest_name || '玩家二')}</td>
            <td class="text-end"><a class="btn btn-sm btn-outline-light" href="/play/${game}?room=${room}&watch=1"><i class="bi bi-eye"></i> 观战</a></td>
        </tr>`);
    });
}

function renderLobbyHistory(items) {
    const $table = $('#lobbyHistoryTable').empty();
    if (!items.length) {
        $table.html('<tr><td colspan="4" class="text-center text-muted py-3">暂无可展示的已结束对局</td></tr>');
        return;
    }
    items.forEach(item => {
        const endedAt = item.ended_at ? new Date(item.ended_at) : null;
        const time = endedAt && !Number.isNaN(endedAt.getTime())
            ? endedAt.toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'})
            : '—';
        $table.append(`<tr>
            <td><span class="badge bg-secondary">${escapeLobbyHtml(LOBBY_GAME_NAMES[item.game_code] || item.game_code)}</span></td>
            <td>${escapeLobbyHtml(item.host_name || '玩家一')} <span class="text-muted">vs</span> ${escapeLobbyHtml(item.guest_name || '玩家二')}</td>
            <td class="text-end">${Number(item.move_count) || 0}</td>
            <td class="text-end text-muted">${time}</td>
        </tr>`);
    });
}

function escapeLobbyHtml(value) {
    return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
