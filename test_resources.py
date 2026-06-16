"""检查首页所有静态资源是否都能加载"""
import os
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
import requests
import re

NO_PROXY = {"http": None, "https": None}
BASE = "http://127.0.0.1:8765"

# 抓首页
r = requests.get(BASE + "/", proxies=NO_PROXY, timeout=5)
print(f"Homepage: {r.status_code}")

# 提取所有静态资源 URL
html = r.text
css_links = re.findall(r'href="(/static/[^"]+)"', html)
js_links = re.findall(r'src="(/static/[^"]+)"', html)
all_links = list(set(css_links + js_links))
print(f"\nFound {len(all_links)} static resources")

# 逐个请求
for url in sorted(all_links):
    try:
        resp = requests.get(BASE + url, proxies=NO_PROXY, timeout=5)
        ct = resp.headers.get("Content-Type", "").split(";")[0]
        size = len(resp.content)
        flag = "✓" if resp.status_code == 200 else "✗"
        print(f"  {flag} {resp.status_code} {ct:20s} {size:8d}B  {url}")
    except Exception as e:
        print(f"  ✗ ERR  {url}  ({e})")
