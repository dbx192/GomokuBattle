// ── 排行榜页面逻辑 ──
// 数据源：GET /api/rankings?limit=N
// 响应结构：{ code, message, data: UserStats[] }

let refreshTimer = null;
let currentUserId = null;

$(function() {
    // 尝试从本地缓存里取当前用户 ID（用于"我的排名"高亮 + 卡片）
    try {
        const cached = JSON.parse(localStorage.getItem('user') || 'null');
        if (cached && cached.id) currentUserId = cached.id;
    } catch (e) { /* ignore */ }

    // 拉一次当前用户信息，确保 id 是最新的（页面刚登录后缓存可能未刷新）
    if (localStorage.getItem('access_token')) {
        API.get('/api/auth/me')
            .done(res => { if (res.code === 200 && res.data) currentUserId = res.data.id; })
            .always(() => loadRankings());
    } else {
        loadRankings();
    }

    // 顶部"刷新"按钮
    $('#refreshBtn').on('click', function() {
        const $icon = $(this).find('i');
        $icon.addClass('bi-spin');
        loadRankings().always(() => $icon.removeClass('bi-spin'));
    });

    // 范围切换
    $('#limitSelect').on('change', loadRankings);

    // 自动刷新开关
    $('#autoRefresh').on('change', function() {
        if (this.checked) {
            startAutoRefresh();
        } else {
            stopAutoRefresh();
        }
    });
});

// ── 拉取并渲染 ──
function loadRankings() {
    const limit = parseInt($('#limitSelect').val(), 10) || 20;
    return API.get('/api/rankings', { limit })
        .done(res => {
            if (res.code === 200) {
                renderAll(res.data || []);
            } else {
                toastr.error(res.message || '加载失败');
            }
        })
        .fail(xhr => {
            const msg = (xhr.responseJSON && xhr.responseJSON.detail) || '加载失败';
            toastr.error(msg);
        });
}

// ── 顶层调度 ──
function renderAll(data) {
    renderSummary(data);
    renderPodium(data.slice(0, 3));
    renderTable(data);
    renderMyRankInline(data);
    updateLastUpdateTime();
}

function renderSummary(data) {
    const totalPlayers = data.length;
    const totalGames = data.reduce((sum, u) => sum + (u.wins || 0) + (u.losses || 0), 0);
    const topWinRate = data.reduce((max, u) => {
        const total = (u.wins || 0) + (u.losses || 0);
        if (total === 0) return max;
        const rate = u.wins / total * 100;
        return rate > max ? rate : max;
    }, 0);

    $('#totalPlayers').text(totalPlayers);
    $('#totalGames').text(totalGames);
    $('#topWinRate').text(totalGames > 0 ? topWinRate.toFixed(1) + '%' : '—');
    $('#tableTotal').text(totalPlayers);
}

// ── 领奖台（Top 3） ──
function renderPodium(top3) {
    const $podium = $('#podium');
    $podium.empty();

    if (top3.length === 0) {
        $podium.html(`
            <div class="text-center text-muted py-3">
                <i class="bi bi-inbox" style="font-size:1.5rem;opacity:0.5;"></i>
                <p class="mt-2 mb-0 small">暂无领奖台数据</p>
            </div>
        `);
        return;
    }

    // 按名次排：1-2-3，便于中间高、两侧低
    const ordered = [top3[1], top3[0], top3[2]].filter(Boolean);
    const medals = ['🥈', '🥇', '🥉'];
    const heights = ['podium-slot-2', 'podium-slot-1', 'podium-slot-3'];

    const html = ordered.map((user, i) => {
        if (!user) return '';
        const total = (user.wins || 0) + (user.losses || 0);
        const winRate = total > 0 ? (user.wins / total * 100).toFixed(1) : '0.0';
        return `
            <div class="podium-slot ${heights[i]}">
                <div class="podium-medal">${medals[i]}</div>
                <div class="podium-name">${escapeHtml(user.username)}</div>
                <div class="podium-rate">${winRate}%</div>
                <div class="podium-stats">
                    <span class="text-success">${user.wins || 0}胜</span>
                    <span class="text-muted mx-1">/</span>
                    <span class="text-danger">${user.losses || 0}负</span>
                </div>
            </div>
        `;
    }).join('');

    $podium.html(html);
}

// ── 完整表格 ──
function renderTable(data) {
    const $tbody = $('#rankingsTable');
    const $empty = $('#emptyState');

    $tbody.empty();

    if (data.length === 0) {
        $empty.show();
        return;
    }
    $empty.hide();

    data.forEach((user, index) => {
        const rank = index + 1;
        const isTop3 = index < 3;
        const medal = index === 0 ? '🥇' : index === 1 ? '🥈' : index === 2 ? '🥉' : rank;
        const medalClass = isTop3 ? 'text-warning' : 'text-muted';
        const isMe = currentUserId && user.id === currentUserId;
        const trClass = isTop3 ? 'top-rank' : '';
        const meClass = isMe ? 'my-rank-row' : '';
        const winRate = (user.win_rate || 0).toFixed(1);
        const barWidth = Math.min(user.win_rate || 0, 100);

        $tbody.append(`
            <tr class="${trClass} ${meClass}">
                <td><span class="rank-medal ${medalClass}">${medal}</span></td>
                <td>
                    <strong>${escapeHtml(user.username)}</strong>
                    ${isMe ? '<span class="badge bg-primary ms-2" style="font-size:0.7rem;">我</span>' : ''}
                </td>
                <td><span class="badge bg-secondary">${escapeHtml(user.rank || '新手')}</span></td>
                <td class="text-end text-success fw-bold">${user.wins || 0}</td>
                <td class="text-end text-danger">${user.losses || 0}</td>
                <td>
                    <div class="winrate-cell">
                        <div class="progress flex-grow-1" style="height: 6px; min-width: 60px;">
                            <div class="progress-bar bg-success" style="width: ${barWidth}%"></div>
                        </div>
                        <span class="win-rate">${winRate}%</span>
                    </div>
                </td>
            </tr>
        `);
    });
}

// ── "我的排名"（mini stat 内联） ──
function renderMyRankInline(data) {
    if (!currentUserId) {
        $('#myRankMini').hide();
        return;
    }

    const idx = data.findIndex(u => u.id === currentUserId);
    if (idx === -1) {
        // 用户没在当前 limit 范围里 → 拉一次大范围
        API.get('/api/rankings', { limit: 100 })
            .done(res => {
                if (res.code === 200) renderMyRankInline(res.data || []);
            });
        return;
    }

    const rank = idx + 1;
    const total = data.length;
    const medal = rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : '#' + rank;

    $('#myRankMini').show();
    $('#myRankMedalMini').text(medal);
    $('#myRankTextMini').text(`第 ${rank}/${total}`);
}

// ── 工具 ──
function updateLastUpdateTime() {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    const ss = String(now.getSeconds()).padStart(2, '0');
    $('#lastUpdate').text(`更新于 ${hh}:${mm}:${ss}`);
}

function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function startAutoRefresh() {
    stopAutoRefresh();
    refreshTimer = setInterval(loadRankings, 30 * 1000);
}

function stopAutoRefresh() {
    if (refreshTimer) {
        clearInterval(refreshTimer);
        refreshTimer = null;
    }
}

// 离开页面时清理定时器
$(window).on('beforeunload', stopAutoRefresh);
