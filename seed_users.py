"""生成几个测试账号"""
import os
os.environ['NO_PROXY'] = '*'
import requests

BASE = "http://127.0.0.1:8000"

# 测试账号列表: (用户名, 密码)
ACCOUNTS = [
    ("alice",   "alice123"),
    ("bob",     "bob123"),
    ("charlie", "charlie123"),
    ("diana",   "diana123"),
    ("evan",    "evan123"),
]

for username, password in ACCOUNTS:
    s = requests.Session(); s.trust_env = False
    r = s.post(f"{BASE}/api/auth/register", json={"username": username, "password": password})
    if r.status_code == 200 and r.json().get("code") == 201:
        print(f"  [新建] {username} / {password}")
    elif r.status_code == 400 and "已存在" in r.json().get("detail", ""):
        print(f"  [已存] {username} / {password}")
    else:
        print(f"  [失败] {username}: {r.status_code} {r.text[:120]}")
