// 爱客服采集插件 - popup.js
// 版本：2.0

const enableToggle    = document.getElementById('enableToggle');
const reviewModeToggle = document.getElementById('reviewModeToggle');
const shopTokenInput  = document.getElementById('shopTokenInput');
const serverUrlInput  = document.getElementById('serverUrlInput');
const saveBtn         = document.getElementById('saveBtn');
const testConnBtn     = document.getElementById('testConnBtn');
const statusMsg       = document.getElementById('statusMsg');
const connStatus      = document.getElementById('connStatus');

// 默认服务器地址
const DEFAULT_SERVER = 'http://39.103.98.34:8000';
// 状态提示自动消失时长（毫秒）
const STATUS_TIMEOUT_MS = 3000;

// 加载已保存的配置（包括 reviewMode 字段）
chrome.storage.sync.get(['shopToken', 'serverUrl', 'isEnabled', 'reviewMode'], (result) => {
  shopTokenInput.value    = result.shopToken   || '';
  serverUrlInput.value    = result.serverUrl   || DEFAULT_SERVER;
  enableToggle.checked    = result.isEnabled   !== false;
  reviewModeToggle.checked = result.reviewMode === true;
});

// 保存配置（同时保存 reviewMode 字段）
saveBtn.addEventListener('click', () => {
  const shopToken  = shopTokenInput.value.trim();
  const serverUrl  = serverUrlInput.value.trim() || DEFAULT_SERVER;
  const isEnabled  = enableToggle.checked;
  const reviewMode = reviewModeToggle.checked;

  if (!shopToken) {
    showStatus('请填写 Shop Token', 'error');
    return;
  }

  chrome.storage.sync.set({ shopToken, serverUrl, isEnabled, reviewMode }, () => {
    showStatus('✅ 设置已保存', 'success');
    setTimeout(() => hideStatus(), STATUS_TIMEOUT_MS);
  });
});

// 测试连接按钮：请求 /api/health 接口验证服务器是否可达
testConnBtn.addEventListener('click', async () => {
  const serverUrl = serverUrlInput.value.trim() || DEFAULT_SERVER;
  testConnBtn.disabled = true;
  testConnBtn.textContent = '连接中...';
  try {
    const resp = await fetch(`${serverUrl}/api/health`, { method: 'GET' });
    if (resp.ok) {
      showStatus('✅ 服务器连接正常', 'success');
      if (connStatus) connStatus.textContent = '● 已连接：' + serverUrl;
    } else {
      showStatus('❌ 服务器响应异常：' + resp.status, 'error');
      if (connStatus) connStatus.textContent = '● 连接异常';
    }
  } catch (e) {
    showStatus('❌ 无法连接服务器', 'error');
    if (connStatus) connStatus.textContent = '● 无法连接';
  } finally {
    testConnBtn.disabled = false;
    testConnBtn.textContent = '🔌 测试连接';
    setTimeout(() => hideStatus(), STATUS_TIMEOUT_MS);
  }
});

function showStatus(text, type) {
  statusMsg.textContent = text;
  statusMsg.className = `status ${type}`;
}

function hideStatus() {
  statusMsg.className = 'status hidden';
}
