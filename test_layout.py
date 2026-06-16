"""通过 Chrome DevTools Protocol 检查首页布局"""
import os
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(k, None)
import json
import requests
import websocket
import time

NO_PROXY = {"http": None, "https": None}

# 1. 创建一个新 tab，导航到目标页
r = requests.put("http://127.0.0.1:9222/json/new?http://127.0.0.1:8765/", proxies=NO_PROXY, timeout=5)
print(f"new tab: {r.status_code}")
tab = r.json()
ws_url = tab["webSocketDebuggerUrl"]

ws = websocket.create_connection(ws_url, timeout=10)
msg_id = 1
def call(method, params=None):
    global msg_id
    ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    msg_id += 1
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == msg_id - 1:
            return msg

# 2. 页面已经在导航中，启用 Page / Runtime 并等待
call("Page.enable")
call("Runtime.enable")
time.sleep(4)  # 等资源全部加载完

# 3. 拿 .row 元素的 display 和 width
expr = """
JSON.stringify({
    bodyBg: getComputedStyle(document.body).background.substring(0, 200),
    bodyColor: getComputedStyle(document.body).color,
    bodyFont: getComputedStyle(document.body).fontFamily,
    // 查找所有 stylesheet，统计规则数
    sheets: (function() {
        return Array.from(document.styleSheets).map(s => ({
            href: s.href,
            ok: 'good',
            ruleCount: (function(){ try { return s.cssRules.length } catch(e) { return 'BLOCKED: ' + e.message } })()
        }));
    })(),
    // 用匹配选择器的方式验证 .row 规则是否存在
    rowMatches: (function() {
        try {
            const matches = [];
            for (const s of document.styleSheets) {
                if (!s.cssRules) continue;
                for (const r of s.cssRules) {
                    if (r.selectorText === '.row') matches.push({sheet: s.href, text: r.cssText.substring(0, 100)});
                }
            }
            return matches;
        } catch (e) { return e.message; }
    })(),
    // 实际检查 viewport
    viewport: {w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio}
})
"""
r = call("Runtime.evaluate", {"expression": expr})
print(json.dumps(json.loads(r["result"]["result"]["value"]), indent=2, ensure_ascii=False))

# 4. 顺便看看哪些资源失败了
r = call("Runtime.evaluate", {"expression": "JSON.stringify(performance.getEntriesByType('resource').filter(r => r.transferSize === 0 || r.responseStatus >= 400).map(r => ({name: r.name, status: r.responseStatus, type: r.initiatorType})))"})
print("\n失败资源:")
print(r["result"]["result"]["value"])
