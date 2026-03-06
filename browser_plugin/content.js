// 爱客服AI助手 - 拼多多商家后台内容脚本
// 功能：监听聊天消息、提取订单信息、推送到本地服务、注入AI回复
// 运行环境：https://mms.pinduoduo.com/*

'use strict';

// ── 已处理消息去重集合（用时间戳+内容哈希）────────────────────────────────
const processedMsgIds = new Set();

// ── 配置（从 chrome.storage.local 读取）──────────────────────────────────
let pluginConfig = {
    serverUrl: 'http://127.0.0.1:6000',
    shopToken: '',
    autoReply: true,
};

// 初始化时加载配置
chrome.storage.local.get(['serverUrl', 'shopToken', 'autoReply'], (result) => {
    if (result.serverUrl) pluginConfig.serverUrl = result.serverUrl;
    if (result.shopToken) pluginConfig.shopToken = result.shopToken;
    if (result.autoReply !== undefined) pluginConfig.autoReply = result.autoReply;
    console.log('[爱客服] 插件配置已加载', pluginConfig);
    startObserver();
});

// 监听配置变更（popup修改后实时生效）
chrome.storage.onChanged.addListener((changes) => {
    if (changes.serverUrl) pluginConfig.serverUrl = changes.serverUrl.newValue;
    if (changes.shopToken) pluginConfig.shopToken = changes.shopToken.newValue;
    if (changes.autoReply !== undefined) pluginConfig.autoReply = changes.autoReply.newValue;
});

// ── MutationObserver 监听聊天容器 ─────────────────────────────────────────
let observer = null;

function startObserver() {
    // 等待聊天容器加载（拼多多SPA异步渲染）
    const waitForChat = setInterval(() => {
        const chatContainer = findChatContainer();
        if (chatContainer) {
            clearInterval(waitForChat);
            attachObserver(chatContainer);
            console.log('[爱客服] 已找到聊天容器，开始监听');
        }
    }, 1500);
}

function findChatContainer() {
    // 尝试多个可能的选择器（拼多多页面结构可能变化）
    const selectors = [
        '.message-list',
        '.chat-content',
        '.im-chat-list',
        '[class*="messageList"]',
        '[class*="chatList"]',
        '[class*="msg-list"]',
    ];
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el) return el;
    }
    return null;
}

function attachObserver(container) {
    if (observer) observer.disconnect();
    observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            mutation.addedNodes.forEach((node) => {
                if (node.nodeType === Node.ELEMENT_NODE) {
                    // 检测是否是买家发来的新消息
                    const buyerMsg = extractBuyerMessage(node);
                    if (buyerMsg) {
                        handleNewMessage(buyerMsg);
                    }
                }
            });
        });
    });
    observer.observe(container, { childList: true, subtree: true });
}

// ── 提取买家消息 ─────────────────────────────────────────────────────────
function extractBuyerMessage(node) {
    // 拼多多聊天消息通常有方向标记（买家/商家）
    // 选择器根据实际DOM结构调整，此处为通用匹配逻辑
    const isBuyerNode = (
        node.classList && (
            node.classList.contains('buyer-msg') ||
            node.classList.contains('left-msg') ||
            node.querySelector('[class*="buyer"]') ||
            node.querySelector('[class*="left"]') ||
            node.getAttribute('data-type') === 'buyer'
        )
    );
    if (!isBuyerNode) return null;

    const textEl = node.querySelector('[class*="text"], [class*="content"], p, span');
    const imgEl = node.querySelector('img[src*="pinduoduo"]');
    const content = textEl ? textEl.textContent.trim() : '';
    const imageUrl = imgEl ? imgEl.src : '';

    if (!content && !imageUrl) return null;

    // 生成消息指纹用于去重
    const fingerprint = hashStr(content + imageUrl + Date.now().toString().slice(0, -3));
    // slice(0, -3) 去掉毫秒位，使同一秒内的相同消息被合并去重
    if (processedMsgIds.has(fingerprint)) return null;
    processedMsgIds.add(fingerprint);

    // 清理旧指纹（只保留最近200条）
    if (processedMsgIds.size > 200) {
        const first = processedMsgIds.values().next().value;
        processedMsgIds.delete(first);
    }

    return {
        content,
        imageUrl,
        msgType: imageUrl ? 'image' : 'text',
        fingerprint,
        buyer: extractBuyerInfo(),
        order: extractOrderInfo(),
    };
}

// ── 提取买家信息 ─────────────────────────────────────────────────────────
function extractBuyerInfo() {
    // 从聊天头部或会话列表中提取买家信息
    const nameEl = document.querySelector(
        '[class*="buyerName"], [class*="buyer-name"], [class*="username"], [class*="nickname"]'
    );
    const idEl = document.querySelector('[class*="buyerId"], [class*="buyer-id"]');
    return {
        id: idEl ? idEl.textContent.trim() : extractBuyerIdFromUrl(),
        name: nameEl ? nameEl.textContent.trim() : '买家',
    };
}

function extractBuyerIdFromUrl() {
    // 部分页面URL包含买家ID
    const match = window.location.href.match(/[?&]uid=([^&]+)/);
    return match ? match[1] : 'unknown_' + Date.now();
}

// ── 提取订单信息 ─────────────────────────────────────────────────────────
function extractOrderInfo() {
    // 从聊天侧边栏提取订单卡片信息
    const orderCard = document.querySelector(
        '[class*="orderCard"], [class*="order-card"], [class*="orderInfo"], [class*="order-info"]'
    );
    if (!orderCard) return null;

    const orderIdEl = orderCard.querySelector('[class*="orderId"], [class*="order-id"]');
    const goodsNameEl = orderCard.querySelector('[class*="goodsName"], [class*="goods-name"], [class*="itemName"]');
    const amountEl = orderCard.querySelector('[class*="amount"], [class*="price"], [class*="total"]');
    const statusEl = orderCard.querySelector('[class*="status"], [class*="orderStatus"]');

    const orderId = orderIdEl ? orderIdEl.textContent.replace(/[^0-9]/g, '') : '';

    return {
        order_id: orderId,
        goods_name: goodsNameEl ? goodsNameEl.textContent.trim() : '',
        amount: amountEl ? parseFloat(amountEl.textContent.replace(/[^0-9.]/g, '')) || 0 : 0,
        status: statusEl ? statusEl.textContent.trim() : '',
        create_time: new Date().toISOString().slice(0, 10),
    };
}

// ── 处理新消息：推送到本地服务 ────────────────────────────────────────────
async function handleNewMessage(msg) {
    if (!pluginConfig.shopToken) {
        console.warn('[爱客服] 未配置 shop_token，跳过');
        return;
    }

    const payload = {
        shop_token: pluginConfig.shopToken,
        buyer_id: msg.buyer.id,
        buyer_name: msg.buyer.name,
        content: msg.content,
        msg_type: msg.msgType,
        image_url: msg.imageUrl || '',
        order_id: msg.order ? msg.order.order_id : '',
        order_info: msg.order || {},
    };

    try {
        // 通过 background.js 中转，解决CORS问题
        const response = await chrome.runtime.sendMessage({
            action: 'sendToServer',
            url: `${pluginConfig.serverUrl}/api/webhook/pdd`,
            payload,
        });

        if (response && response.success) {
            console.log(`[爱客服] 消息处理成功，回复：${response.reply}`);
            if (response.reply) {
                injectReply(response.reply, response.needs_human);
            }
        } else {
            console.warn('[爱客服] 服务端处理失败', response);
        }
    } catch (err) {
        console.error('[爱客服] 消息推送异常', err);
    }
}

// ── 注入AI回复到输入框 ────────────────────────────────────────────────────
function injectReply(replyText, needsHuman) {
    if (!replyText) return;
    if (!pluginConfig.autoReply) return;

    const inputEl = findInputBox();
    if (!inputEl) {
        console.warn('[爱客服] 未找到输入框');
        return;
    }

    // 填入回复内容
    inputEl.focus();
    // contenteditable div
    if (inputEl.contentEditable === 'true') {
        inputEl.textContent = replyText;
        inputEl.dispatchEvent(new Event('input', { bubbles: true }));
    } else {
        // input / textarea
        const nativeSetter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value'
        ) || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
        if (nativeSetter) nativeSetter.set.call(inputEl, replyText);
        inputEl.dispatchEvent(new Event('input', { bubbles: true }));
    }

    if (needsHuman) {
        // 需人工处理：只填入，高亮提示，不自动发送
        showHumanAlert(inputEl, replyText);
        return;
    }

    // 自动发送
    setTimeout(() => {
        const sendBtn = findSendButton();
        if (sendBtn) {
            sendBtn.click();
        } else {
            // 模拟回车发送
            inputEl.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'Enter', keyCode: 13, bubbles: true
            }));
        }
    }, 300);
}

function findInputBox() {
    const selectors = [
        'textarea[class*="input"]',
        'div[contenteditable="true"][class*="input"]',
        'div[contenteditable="true"][class*="editor"]',
        '.chat-input textarea',
        '.message-input',
        '[placeholder*="输入"]',
        '[placeholder*="消息"]',
    ];
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el) return el;
    }
    return null;
}

function findSendButton() {
    const selectors = [
        'button[class*="send"]',
        'button[class*="Send"]',
        '[class*="sendBtn"]',
        '[class*="send-btn"]',
    ];
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el) return el;
    }
    return null;
}

// ── 人工处理提示 ──────────────────────────────────────────────────────────
function showHumanAlert(inputEl, suggestedReply) {
    // 在输入框上方显示提示横幅
    const existing = document.getElementById('aikefu-human-alert');
    if (existing) existing.remove();

    const banner = document.createElement('div');
    banner.id = 'aikefu-human-alert';
    banner.style.cssText = [
        'position:fixed', 'top:60px', 'right:20px', 'z-index:99999',
        'background:#fff3cd', 'border:2px solid #ffc107', 'border-radius:8px',
        'padding:12px 16px', 'max-width:320px', 'box-shadow:0 4px 12px rgba(0,0,0,0.15)',
        'font-family:Microsoft YaHei,sans-serif',
    ].join(';');
    banner.innerHTML = `
        <div style="font-weight:bold;color:#856404;margin-bottom:6px;">
            ⚠️ 需要人工处理
        </div>
        <div style="font-size:13px;color:#495057;margin-bottom:8px;">
            AI建议回复（已填入输入框，请确认后发送）：
        </div>
        <div style="font-size:12px;background:#fff;padding:6px;border-radius:4px;max-height:80px;overflow-y:auto;">
            ${suggestedReply}
        </div>
        <button onclick="this.parentElement.remove()"
            style="margin-top:8px;padding:2px 10px;border:1px solid #ffc107;border-radius:4px;background:transparent;cursor:pointer;font-size:12px;">
            关闭
        </button>
    `;
    document.body.appendChild(banner);
    setTimeout(() => banner.remove(), 30000);
}

// ── 工具函数 ──────────────────────────────────────────────────────────────
function hashStr(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        hash = ((hash << 5) - hash) + str.charCodeAt(i);
        hash |= 0;
    }
    return hash.toString(36);
}

console.log('[爱客服] 拼多多AI助手内容脚本已加载');
