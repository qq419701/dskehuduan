# === 修复1: pdd_transfer.py goto ===
t = open('channel/pinduoduo/pdd_transfer.py', encoding='utf-8').read()
old = 'page.goto(url, wait_until="networkidle", timeout=30000)'
new = 'page.goto(url, wait_until="domcontentloaded", timeout=60000)'
if old in t:
    t = t.replace(old, new)
    open('channel/pinduoduo/pdd_transfer.py', 'w', encoding='utf-8').write(t)
    print('OK: pdd_transfer.py goto已修复')
else:
    print('SKIP: pdd_transfer.py goto已是新版')

# === 检查2: pdd_login.py ===
l = open('channel/pinduoduo/pdd_login.py', encoding='utf-8').read()
if 'aikefu_cookies.json' in l:
    print('OK: pdd_login.py已有json保存')
else:
    print('WARNING: pdd_login.py没有json保存')
    idx = l.find('self.cookies = {c')
    print('附近:', repr(l[idx:idx+200]))
