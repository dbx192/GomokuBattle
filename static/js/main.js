const API_BASE = '';

const API = {
    get: (url, params) => $.ajax({
        url: API_BASE + url,
        type: 'GET',
        data: params,
        beforeSend: (xhr) => {
            const token = localStorage.getItem('access_token');
            if (token) {
                xhr.setRequestHeader('Authorization', 'Bearer ' + token);
            }
        }
    }),
    post: (url, data) => $.ajax({
        url: API_BASE + url,
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(data),
        beforeSend: (xhr) => {
            const token = localStorage.getItem('access_token');
            if (token) {
                xhr.setRequestHeader('Authorization', 'Bearer ' + token);
            }
        }
    }),
    delete: (url) => $.ajax({
        url: API_BASE + url,
        type: 'DELETE',
        beforeSend: (xhr) => {
            const token = localStorage.getItem('access_token');
            if (token) {
                xhr.setRequestHeader('Authorization', 'Bearer ' + token);
            }
        }
    })
};

function handleResponse(res, onSuccess, onError) {
    if (res.code === 200 || res.code === 201) {
        if (onSuccess) onSuccess(res.data);
        if (res.message && res.message !== 'success') toastr.success(res.message);
    } else {
        toastr.error(res.message || '操作失败');
        if (onError) onError(res);
    }
}

function checkAuth() {
    const token = localStorage.getItem('access_token');
    if (token) {
        API.get('/api/auth/me')
            .done(res => {
                if (res.code === 200) {
                    showUserInfo(res.data);
                } else {
                    logout();
                }
            })
            .fail(() => logout());
    }
}

function showUserInfo(user) {
    localStorage.setItem('user', JSON.stringify(user));
    $('#userInfo').show();
    $('#loginPrompt').hide();
    $('#loginPromptCard').hide();
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
    $('#userName').text(user.username);
    $('#userRank').text(user.rank);
    $('#userWins').text(user.wins);
    $('#userLosses').text(user.losses);
    const total = user.wins + user.losses;
    const winRate = total > 0 ? ((user.wins / total) * 100).toFixed(1) : 0;
    $('#userWinRate').text(winRate + '%');
    $('#userAvatar').text(user.username.charAt(0).toUpperCase());

    $('#logoutBtn').off('click').on('click', logout);
}

function logout() {
    localStorage.removeItem('access_token');
    localStorage.removeItem('user');
    location.reload();
}

$(function() {
    toastr.options = {
        closeButton: true,
        progressBar: true,
        positionClass: "toast-top-right",
        timeOut: 3000
    };
    
    checkAuth();
    
    $('#loginForm').on('submit', function(e) {
        e.preventDefault();
        const formData = $(this).serializeArray();
        const data = {};
        formData.forEach(item => data[item.name] = item.value);
        
        API.post('/api/auth/login', data)
            .done(res => {
                if (res.code === 200) {
                    localStorage.setItem('access_token', res.data.access_token);
                    $('#loginModal').modal('hide');
                    toastr.success('登录成功');
                    showUserInfo(res.data.user);
                }
            })
            .fail(xhr => {
                const res = xhr.responseJSON;
                toastr.error(res.detail || '登录失败');
            });
    });
    
    $('#registerForm').on('submit', function(e) {
        e.preventDefault();
        const formData = $(this).serializeArray();
        const data = {};
        formData.forEach(item => data[item.name] = item.value);
        
        API.post('/api/auth/register', data)
            .done(res => {
                if (res.code === 201) {
                    $('#registerModal').modal('hide');
                    toastr.success('注册成功，请登录');
                    $('#loginModal').modal('show');
                    $('#registerForm')[0].reset();
                }
            })
            .fail(xhr => {
                const res = xhr.responseJSON;
                toastr.error(res.detail || '注册失败');
            });
    });
    
    $('[data-page="rankings"]').on('click', function(e) {
        e.preventDefault();
        loadRankings();
    });
    
    function loadRankings() {
        API.get('/api/rankings')
            .done(res => {
                if (res.code === 200) {
                    $('#homePage').hide();
                    $('#rankingsPage').show();
                    renderRankings(res.data);
                }
            });
    }
    
    function renderRankings(data) {
        const tbody = $('#rankingsTable');
        tbody.empty();
        
        data.forEach((user, index) => {
            const rankClass = index < 3 ? 'text-warning' : '';
            const medal = index === 0 ? '🥇' : index === 1 ? '🥈' : index === 2 ? '🥉' : (index + 1);
            
            tbody.append(`
                <tr>
                    <td><span class="${rankClass}">${medal}</span></td>
                    <td><strong>${user.username}</strong></td>
                    <td><span class="badge bg-secondary">${user.rank}</span></td>
                    <td class="text-success fw-bold">${user.wins}</td>
                    <td class="text-danger">${user.losses}</td>
                    <td>
                        <div class="progress mt-1" style="height: 6px; width: 80px;">
                            <div class="progress-bar bg-success" style="width: ${user.win_rate}%"></div>
                        </div>
                        <small>${user.win_rate}%</small>
                    </td>
                </tr>
            `);
        });
    }
    
    $('[data-page="home"]').on('click', function(e) {
        e.preventDefault();
        $('#homePage').show();
        $('#rankingsPage').hide();
    });
});
