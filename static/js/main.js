const API_BASE = '';
let authMeRequest = null;

const API = {
    get: (url, params) => {
        // Several page-specific scripts also check the session on startup. Share
        // the in-flight request so one refresh can never fan out into duplicates.
        if (url === '/api/auth/me' && authMeRequest) return authMeRequest;
        const request = $.ajax({
            url: API_BASE + url,
            type: 'GET',
            data: params,
            beforeSend: (xhr) => {
                const token = localStorage.getItem('access_token');
                if (token) xhr.setRequestHeader('Authorization', 'Bearer ' + token);
            }
        });
        if (url === '/api/auth/me') {
            authMeRequest = request;
            request.always(() => {
                if (authMeRequest === request) authMeRequest = null;
            });
        }
        return request;
    },
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

function checkAuth() {
    const token = localStorage.getItem('access_token');
    if (token) {
        API.get('/api/auth/me')
            .done(res => {
                if (res.code === 200) {
                    showUserInfo(res.data);
                } else {
                    // 业务码非 200（不是 401）的情况：清掉本地 token，刷新页面
                    logout();
                }
            });
        // 401 由全局 ajaxError 兜底处理（清 token + 弹登录框），不在这里 logout() 防止 reload 把弹窗冲掉
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
                <li><a class="dropdown-item" href="/history"><i class="bi bi-clock-history"></i> 历史对局</a></li>
                <li><hr class="dropdown-divider"></li>
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

function isLoggedIn() {
    return !!localStorage.getItem('access_token');
}

// 全局显示登录弹窗（无 token 时被拦截后调用）
function showLoginModal() {
    const el = document.getElementById('loginModal');
    if (!el) {
        // 兜底：当前页没有登录弹窗，只能回首页
        location.href = '/';
        return;
    }
    bootstrap.Modal.getOrCreateInstance(el).show();
}

// 处理登录成功后的跳转：
//  1. 有 postLoginRedirect → 跳到原本要去的页面（从首页被拦截的情况）
//  2. 没有 redirect、且当前在受保护页 → 刷新当前页让页面脚本重新初始化
//  3. 其他（首页）→ 留在原页即可，showUserInfo 已经把用户信息刷出来了
function handlePostLogin() {
    const redirect = sessionStorage.getItem('postLoginRedirect');
    if (redirect) {
        sessionStorage.removeItem('postLoginRedirect');
        location.href = redirect;
        return;
    }
    const path = location.pathname;
    if (path.startsWith('/game') || path.startsWith('/play')) {
        location.reload();
    }
}

function refreshCaptcha(formId) {
    const $form = $('#' + formId);
    const imageId = formId === 'loginForm' ? '#loginCaptchaImage' : '#registerCaptchaImage';
    API.get('/api/auth/captcha')
        .done(res => {
            if (res.code !== 200) return;
            $form.find('[name="captcha_id"]').val(res.data.captcha_id);
            $form.find('[name="captcha_answer"]').val('');
            $(imageId).attr('src', res.data.image);
        })
        .fail(xhr => toastr.error(xhr.responseJSON?.detail || '验证码加载失败'));
}

function finishLogin(data, message) {
    localStorage.setItem('access_token', data.access_token);
    $('#loginModal, #registerModal').modal('hide');
    toastr.success(message);
    showUserInfo(data.user);
    setTimeout(handlePostLogin, 250);
}

$(function() {
    toastr.options = {
        closeButton: true,
        progressBar: true,
        positionClass: "toast-top-right",
        timeOut: 3000
    };

    // ── 全局拦截：未登录时进入需要参与对局的页面 → 弹登录框，不跳转 ──
    const PROTECTED_PREFIXES = ['/game', '/play'];
    function isProtectedPath(href) {
        if (!href) return false;
        return PROTECTED_PREFIXES.some(p =>
            href === p || href.startsWith(p + '/') || href.startsWith(p + '?')
        );
    }

    // 事件委托，避免绑定不到动态生成的链接
    $(document).on('click', 'a[href]', function(e) {
        const href = $(this).attr('href');
        if (!isProtectedPath(href)) return;
        if (isLoggedIn()) return;             // 已登录，正常跳转
        e.preventDefault();
        e.stopImmediatePropagation();
        sessionStorage.setItem('postLoginRedirect', href);
        showLoginModal();
    });

    // ── 全局 401 处理：任意 API 返回 401 → 清 token + 弹登录框 ──
    let showing401Modal = false;
    $(document).ajaxError(function(event, xhr) {
        if (xhr.status !== 401) return;
        if (showing401Modal) return;          // 已经在弹了，别重复
        if (!localStorage.getItem('access_token')) return;  // 本来就没 token 的话由各自页面处理
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
        showing401Modal = true;
        toastr.warning('登录已过期，请重新登录');
        showLoginModal();
        // modal 关闭后重置 flag
        $('#loginModal').one('hidden.bs.modal', () => { showing401Modal = false; });
    });

    checkAuth();

    $('.refresh-captcha').on('click', function() { refreshCaptcha(this.dataset.form); });
    $('#loginModal').on('shown.bs.modal', () => refreshCaptcha('loginForm'));
    $('#registerModal').on('shown.bs.modal', () => refreshCaptcha('registerForm'));

    $('#loginForm').on('submit', function(e) {
        e.preventDefault();
        const formData = $(this).serializeArray();
        const data = {};
        formData.forEach(item => data[item.name] = item.value);

        API.post('/api/auth/login', data)
            .done(res => {
                if (res.code === 200) {
                    finishLogin(res.data, '登录成功');
                }
            })
            .fail(xhr => {
                const res = xhr.responseJSON;
                toastr.error(res.detail || '登录失败');
                refreshCaptcha('loginForm');
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
                    finishLogin(res.data, '注册成功，已自动登录');
                    $('#registerForm')[0].reset();
                }
            })
            .fail(xhr => {
                const res = xhr.responseJSON;
                toastr.error(res.detail || '注册失败');
                refreshCaptcha('registerForm');
            });
    });

});
