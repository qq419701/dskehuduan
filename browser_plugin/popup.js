// 爱客服AI助手 - 弹窗逻辑
// 功能：读写 chrome.storage.local，测试连接，显示状态

'use strict';

// ── 页面初始化：加载已保存的配置 ─────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    chrome.storage.local.get(['serverUrl', 'shopToken', 'autoReply'], (result) => {
        document.getElementById('serverUrl').value =
            result.serverUrl || 'http://127.0.0.1:6000';
        document.getElementById('shopToken').value = result.shopToken || '';
        document.getElementById('autoReply').checked =
            result.autoReply !== false; // 默认开启
    });

    // 加载后自动测试连接
    setTimeout(testConnection, 300);
});

// ── 保存设置 ──────────────────────────────────────────────────────────────
function saveSettings() {
    const serverUrl = document.getElementById('serverUrl').value.trim().replace(/\/$/, '');
    const shopToken = document.getElementById('shopToken').value.trim();
    const autoReply = document.getElementById('autoReply').checked;

    if (!serverUrl) {
        alert('请填写服务器地址');
        return;
    }

    chrome.storage.local.set({ serverUrl, shopToken, autoReply }, () => {
        // 短暂显示保存成功提示
        const btn = document.querySelector('button.btn-primary');
        const orig = btn.textContent;
        btn.textContent = '✅ 已保存';
        btn.disabled = true;
        setTimeout(() => {
            btn.textContent = orig;
            btn.disabled = false;
        }, 1500);
        // 保存后重新测试连接
        testConnection();
    });
}

// ── 测试与服务器的连接 ────────────────────────────────────────────────────
function testConnection() {
    const serverUrl = document.getElementById('serverUrl').value.trim().replace(/\/$/, '') ||
        'http://127.0.0.1:6000';

    setStatus('checking', '检测中...');

    chrome.runtime.sendMessage(
        { action: 'testConnection', serverUrl },
        (response) => {
            if (chrome.runtime.lastError) {
                setStatus('disconnected', '插件通信错误');
                return;
            }
            if (response && response.connected) {
                const label = response.system
                    ? `已连接 · ${response.system} ${response.version || ''}`
                    : '已连接';
                setStatus('connected', label);
            } else {
                const err = response && response.error ? response.error : '无法连接';
                setStatus('disconnected', `未连接 · ${err}`);
            }
        }
    );
}

// ── 设置状态指示器 ────────────────────────────────────────────────────────
function setStatus(type, text) {
    const dot = document.getElementById('statusDot');
    const label = document.getElementById('statusText');

    dot.className = 'status-dot';
    if (type === 'connected') dot.classList.add('status-connected');
    else if (type === 'disconnected') dot.classList.add('status-disconnected');
    else dot.classList.add('status-checking');

    label.textContent = text;
}

// ── Token 显示/隐藏切换 ───────────────────────────────────────────────────
function toggleTokenVisibility() {
    const input = document.getElementById('shopToken');
    input.type = input.type === 'password' ? 'text' : 'password';
}

// ── 打开管理后台 ──────────────────────────────────────────────────────────
function openDashboard() {
    chrome.storage.local.get(['serverUrl'], (result) => {
        const url = (result.serverUrl || 'http://127.0.0.1:6000').replace(/\/$/, '');
        chrome.tabs.create({ url });
    });
}
