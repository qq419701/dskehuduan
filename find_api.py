import requests, json

cookies_path = None
import os, glob
paths = glob.glob(os.path.join(os.path.expanduser("~"), ".aikefu-client", "browser_data", "shop_*", "aikefu_cookies.json"))
if paths:
    cookies_path = paths[0]
    print("找到cookies:", cookies_path)
    cookies = json.load(open(cookies_path, encoding="utf-8"))
else:
    print("未找到cookies文件，请先登录")
    exit()

sess = requests.Session()
sess.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://mms.pinduoduo.com/",
    "Origin": "https://mms.pinduoduo.com",
})
for k, v in cookies.items():
    sess.cookies.set(k, v, domain=".pinduoduo.com")

# 测试所有可能的接口
apis = [
    ("GET",  "https://mms.pinduoduo.com/assistant/staff/getOnlineStaffList", {}),
    ("POST", "https://mms.pinduoduo.com/assistant/staff/getOnlineStaffList", {}),
    ("GET",  "https://mms.pinduoduo.com/im/getOnlineStaffList", {}),
    ("POST", "https://mms.pinduoduo.com/im/getOnlineStaffList", {}),
    ("GET",  "https://mms.pinduoduo.com/mms/staff/getOnlineList", {}),
    ("POST", "https://mms.pinduoduo.com/mms/staff/getOnlineList", {}),
    ("GET",  "https://mms.pinduoduo.com/assistant/chat/getTransferStaffList", {}),
    ("POST", "https://mms.pinduoduo.com/assistant/chat/getTransferStaffList", {}),
    ("POST", "https://mms.pinduoduo.com/chats/getStaffList", {}),
    ("GET",  "https://mms.pinduoduo.com/chats/getStaffList", {}),
]

for method, url, data in apis:
    try:
        if method == "GET":
            r = sess.get(url, timeout=8)
        else:
            r = sess.post(url, json=data, timeout=8)
        print(f"\n[{method}] {url}")
        print(f"  状态码: {r.status_code}")
        print(f"  响应: {r.text[:200]}")
    except Exception as e:
        print(f"[{method}] {url} 失败: {e}")
