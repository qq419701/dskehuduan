// 爱客服拼多多采集插件 - content.js
// 监听拼多多商家后台DOM变化，采集买家消息并推送到aikefu服务器
// 版本：2.0

(function () {
  'use strict';

  // ────────────── 配置默认值 ──────────────
  const DEFAULT_SERVER = 'http://39.103.98.34:8000'; // 默认服务器地址
  const PUSH_INTERVAL_MS = 500;           // 消息推送间隔（毫秒）
  const MAX_FINGERPRINT_SIZE = 2000;      // 去重集合最大条数
  const REVIEW_BANNER_TIMEOUT_MS = 5000;  // 审核模式提示横幅自动消失时长（毫秒）
  const BUYER_PROFILE_DISPLAY_MS = 3000;  // 买家画像浮窗自动消失时长（毫秒）

  // ────────────── 状态 ──────────────
  let shopToken = '';          // 商家令牌
  let isEnabled = false;       // 是否启用采集
  let serverUrl = DEFAULT_SERVER; // 当前服务器地址（从用户配置读取）
  let reviewMode = false;      // 审核模式：true时AI回复只填入输入框不自动发送
  const seenFingerprints = new Set(); // 消息去重集合
  const messageQueue = [];     // 待推送消息队列
  let processingQueue = false; // 队列是否正在处理中

  // ────────────── 动态构建 WEBHOOK_URL ──────────────
  // 根据 serverUrl 动态拼接，确保用户配置的服务器地址被使用
  function getWebhookUrl() {
    return `${serverUrl}/api/webhook/pdd`;
  }

  // ────────────── 初始化：读取用户全部配置 ──────────────
  chrome.storage.sync.get(['shopToken', 'isEnabled', 'serverUrl', 'reviewMode'], (result) => {
    shopToken   = result.shopToken   || '';
    isEnabled   = result.isEnabled   !== false;
    serverUrl   = result.serverUrl   || DEFAULT_SERVER;
    reviewMode  = result.reviewMode  === true;
    console.log('[爱客服] 配置已加载，服务器地址：', serverUrl, '审核模式：', reviewMode);
    if (isEnabled && shopToken) {
      startObserver();
      // 如果当前在订单管理页，启动订单同步
      if (isOrdersPage()) {
        startOrderPageSync();
      }
    }
  });

  // 监听配置变更，实时同步到内存
  chrome.storage.onChanged.addListener((changes) => {
    if (changes.shopToken)  shopToken  = changes.shopToken.newValue  || '';
    if (changes.isEnabled)  isEnabled  = changes.isEnabled.newValue  !== false;
    if (changes.serverUrl)  serverUrl  = changes.serverUrl.newValue  || DEFAULT_SERVER;
    if (changes.reviewMode) reviewMode = changes.reviewMode.newValue === true;
    console.log('[爱客服] 配置已更新，服务器地址：', serverUrl, '审核模式：', reviewMode);
    if (isEnabled && shopToken) startObserver();
  });

  // ────────────── 判断当前是否为订单管理页 ──────────────
  function isOrdersPage() {
    // 使用精确的 hostname 匹配，避免被恶意子域名绕过
    return (location.hostname === 'mms.pinduoduo.com'
      || location.hostname.endsWith('.mms.pinduoduo.com'))
      && location.pathname.includes('/orders');
  }

  // ────────────── DOM 选择器（适配拼多多2026年版本）──────────────
  // 来源商品卡片选择器（从当前聊天上下文中寻找，适配多版本拼多多）
  const GOODS_CARD_SELECTORS = [
    '[class*="goodsCard"]',
    '[class*="sourceGoods"]',
    '[class*="goods-card"]',
    '[class*="product-card"]',
    '[data-type="goods"]',
  ];

  const CHAT_CONTAINER_SELECTORS = [
    '.message-list',
    '.chat-message-list',
    '[class*="MessageList"]',
    '[class*="messageList"]',
    '[class*="chatList"]',
    '.im-chat-content',
  ];

  const BUYER_MESSAGE_SELECTORS = [
    '.message-item.message-left',
    '.chat-item[data-direction="left"]',
    '[class*="MessageItem"][class*="left"]',
    '[class*="buyerMessage"]',
    '[class*="receiveMessage"]',
  ];

  const INPUT_BOX_SELECTORS = [
    'div[contenteditable="true"][class*="input"]',
    'div[contenteditable="true"][class*="editor"]',
    'div[contenteditable="true"][class*="chat"]',
    'div[contenteditable="true"]',
    'textarea[class*="input"]',
  ];

  const SEND_BTN_SELECTORS = [
    'button:contains("发送")',
    '[class*="sendBtn"]',
    '[class*="send-btn"]',
    'button[class*="send"]',
  ];

  // ────────────── MutationObserver ──────────────
  let observer = null;

  function startObserver() {
    if (observer) return;

    observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType === Node.ELEMENT_NODE) {
            scanForMessages(node);
          }
        }
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
    });

    // 初始扫描已有消息
    scanForMessages(document.body);
    console.log('[爱客服] 消息监听已启动');
  }

  // ────────────── 消息扫描 ──────────────
  function scanForMessages(root) {
    for (const selector of BUYER_MESSAGE_SELECTORS) {
      const items = root.querySelectorAll ? root.querySelectorAll(selector) : [];
      for (const item of items) {
        processMessageElement(item);
      }
    }
  }

  function processMessageElement(el) {
    try {
      const data = extractMessageData(el);
      if (!data) return;

      const fingerprint = makeFingerprint(data);
      if (seenFingerprints.has(fingerprint)) return;

      // 去重集合大小控制：超出限制时批量清除20%最旧条目
      if (seenFingerprints.size >= MAX_FINGERPRINT_SIZE) {
        const removeCount = Math.ceil(MAX_FINGERPRINT_SIZE * 0.2);
        const iter = seenFingerprints.values();
        for (let i = 0; i < removeCount; i++) {
          const next = iter.next();
          if (next.done) break;
          seenFingerprints.delete(next.value);
        }
      }
      seenFingerprints.add(fingerprint);

      messageQueue.push(data);
      if (!processingQueue) {
        processQueue();
      }
    } catch (e) {
      console.debug('[爱客服] 处理消息元素失败:', e);
    }
  }

  // ────────────── 数据提取 ──────────────
  function extractMessageData(el) {
    // 提取买家ID
    const buyerId = extractBuyerId(el);
    // 提取消息内容
    const content = extractContent(el);
    // 提取消息类型
    const msgType = extractMsgType(el);
    // 提取订单信息
    const orderInfo = extractOrderInfo(el);
    // 提取买家昵称
    const buyerName = extractBuyerName(el);

    if (!content && !orderInfo) return null;

    return {
      buyer_id: buyerId,
      buyer_name: buyerName,
      content: content || '',
      msg_type: msgType,
      order_id: orderInfo ? (orderInfo.order_sn || '') : '',
      order_info: orderInfo || {},
      timestamp: Date.now(),
    };
  }

  function extractBuyerId(el) {
    // 尝试从 data 属性提取
    const candidates = [
      el.dataset.buyerId,
      el.dataset.uid,
      el.dataset.userId,
      el.closest('[data-buyer-id]')?.dataset.buyerId,
      el.closest('[data-uid]')?.dataset.uid,
    ];
    for (const c of candidates) {
      if (c) return String(c);
    }

    // 尝试从 URL 提取当前会话买家ID
    const match = location.href.match(/[?&]uid=([^&]+)/);
    if (match) return match[1];

    return '';
  }

  function extractBuyerName(el) {
    const nameEl = el.querySelector('[class*="nickname"], [class*="userName"], [class*="buyerName"]');
    return nameEl ? nameEl.textContent.trim() : '';
  }

  function extractContent(el) {
    // 文字内容
    const textEl = el.querySelector(
      '[class*="textContent"], [class*="msgText"], [class*="content"] span, p'
    );
    if (textEl) return textEl.textContent.trim();

    // 图片消息
    const imgEl = el.querySelector('img[src*="pinduoduo"], img[class*="msgImg"]');
    if (imgEl) return '[图片]';

    // 直接取文本（去掉时间戳等）
    const text = el.textContent.trim();
    if (text && text.length < 500) return text;

    return '';
  }

  function extractMsgType(el) {
    if (el.querySelector('img[class*="msgImg"], [class*="imageMsg"]')) return 'image';
    if (el.querySelector('[class*="goodsCard"], [class*="goodsMsg"]')) return 'goods';
    if (el.querySelector('[class*="orderCard"], [class*="orderMsg"]')) return 'order';
    return 'text';
  }

  function extractOrderInfo(el) {
    const orderEl = el.querySelector('[class*="orderCard"], [class*="orderMsg"]');
    if (!orderEl) return null;

    const orderSn = orderEl.dataset.orderSn
      || orderEl.querySelector('[class*="orderSn"]')?.textContent?.trim()
      || '';
    const goodsName = orderEl.querySelector('[class*="goodsName"]')?.textContent?.trim() || '';

    return { order_sn: orderSn, goods_name: goodsName };
  }

  // ────────────── 浏览足迹：提取当前聊天关联的来源商品 ──────────────
  // 从聊天窗口周边 DOM 中提取买家当前浏览的商品卡片信息
  function extractCurrentGoods() {
    // 遍历多个备选选择器，适配拼多多商家后台多版本
    for (const selector of GOODS_CARD_SELECTORS) {
      const card = document.querySelector(selector);
      if (!card) continue;

      const goodsId = card.dataset.goodsId
        || card.dataset.itemId
        || card.dataset.id
        || '';

      const goodsName = (
        card.querySelector('[class*="goodsName"], [class*="itemName"], [class*="productName"]')
          ?.textContent?.trim()
        || ''
      );

      const goodsImg = card.querySelector('img')?.src || '';

      const goodsSpec = (
        card.querySelector('[class*="spec"], [class*="sku"], [class*="goodsSku"]')
          ?.textContent?.trim()
        || ''
      );

      const goodsPrice = (
        card.querySelector('[class*="price"], [class*="goodsPrice"]')
          ?.textContent?.trim()
        || ''
      );

      // 只要找到任意一个商品卡片就返回，避免空结果
      if (goodsId || goodsName || goodsImg) {
        return { goods_id: goodsId, goods_name: goodsName, goods_img: goodsImg, goods_spec: goodsSpec, goods_price: goodsPrice };
      }
    }

    // 尝试从 URL 参数提取商品ID（部分版本URL带 goods_id 参数）
    const urlMatch = location.href.match(/[?&]goods_id=([^&]+)/);
    if (urlMatch) {
      return { goods_id: urlMatch[1], goods_name: '', goods_img: '', goods_spec: '', goods_price: '' };
    }

    // 提取不到，返回空对象（不传 null，保证兼容性）
    return {};
  }

  function makeFingerprint(data) {
    return `${data.buyer_id}|${data.content}|${data.timestamp}`;
  }

  // ────────────── 消息队列处理 ──────────────
  async function processQueue() {
    if (processingQueue) return;
    processingQueue = true;

    while (messageQueue.length > 0) {
      const msg = messageQueue.shift();
      await sendToServer(msg);
      await sleep(PUSH_INTERVAL_MS);
    }

    processingQueue = false;
  }

  // 推送消息到服务端，携带浏览足迹字段 current_goods
  async function sendToServer(data) {
    if (!shopToken || !isEnabled) return;

    // 采集当前买家浏览的来源商品（浏览足迹）
    const currentGoods = extractCurrentGoods();

    try {
      const resp = await fetch(getWebhookUrl(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          shop_token: shopToken,
          buyer_id: data.buyer_id,
          buyer_name: data.buyer_name,
          content: data.content,
          msg_type: data.msg_type,
          order_id: data.order_id,
          order_info: data.order_info,
          current_goods: currentGoods, // 浏览足迹：当前商品卡片信息
        }),
      });

      if (!resp.ok) {
        console.warn('[爱客服] 推送消息失败，HTTP状态码：', resp.status);
        return;
      }

      const result = await resp.json();
      if (result.success && result.reply && !result.needs_human) {
        await injectReply(result.reply);
      } else if (result.needs_human) {
        showHumanBanner();
      }
      // 如果服务端返回买家画像，展示浮窗
      if (result.buyer_profile) {
        showBuyerProfile(result.buyer_profile);
      }
    } catch (e) {
      console.debug('[爱客服] 推送消息异常:', e);
    }
  }

  // ────────────── 注入AI回复（支持审核模式）──────────────
  async function injectReply(replyText) {
    const inputBox = findInputBox();
    if (!inputBox) {
      console.warn('[爱客服] 找不到输入框，无法注入回复');
      return;
    }

    inputBox.focus();

    if (inputBox.tagName === 'TEXTAREA' || inputBox.tagName === 'INPUT') {
      inputBox.value = replyText;
      inputBox.dispatchEvent(new Event('input', { bubbles: true }));
    } else {
      // contenteditable 元素
      inputBox.innerText = replyText;
      inputBox.dispatchEvent(new InputEvent('input', { bubbles: true }));
    }

    if (reviewMode) {
      // 审核模式：只填入输入框，不自动发送，显示橙色提示横幅
      console.log('[爱客服] 审核模式已开启，AI回复已填入输入框，等待人工确认后发送');
      showReviewBanner('🔍 AI已准备好回复，请检查后手动发送');
      return;
    }

    // 非审核模式：短暂延迟后尝试自动发送
    await sleep(300);
    const sent = clickSendButton();
    if (!sent) {
      // 找不到发送按钮时，按回车发送
      inputBox.dispatchEvent(new KeyboardEvent('keydown', {
        key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true,
      }));
    }
  }

  function findInputBox() {
    for (const selector of INPUT_BOX_SELECTORS) {
      const el = document.querySelector(selector);
      if (el && isVisible(el)) return el;
    }
    return null;
  }

  function clickSendButton() {
    const buttons = document.querySelectorAll('button');
    for (const btn of buttons) {
      if (btn.textContent.includes('发送') && isVisible(btn)) {
        btn.click();
        return true;
      }
    }
    return false;
  }

  // ────────────── 审核模式提示横幅（橙色）──────────────
  // 显示提示横幅，告知操作人员AI已填写回复，需手动确认发送
  function showReviewBanner(text) {
    // 移除已有横幅，避免重叠
    const existing = document.getElementById('aikefu-review-banner');
    if (existing) existing.remove();

    const banner = document.createElement('div');
    banner.id = 'aikefu-review-banner';
    banner.style.cssText = `
      position: fixed; top: 0; left: 0; right: 0; z-index: 99999;
      background: #fa8c16; color: white; text-align: center;
      padding: 10px; font-size: 14px; font-weight: bold;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    `;
    banner.innerHTML = `
      ${text}
      <button onclick="this.parentElement.remove()" style="
        margin-left: 16px; background: white; color: #fa8c16;
        border: none; padding: 2px 10px; border-radius: 4px; cursor: pointer;
      ">关闭</button>
    `;
    document.body.prepend(banner);

    // 5秒后自动消失
    setTimeout(() => banner.remove(), REVIEW_BANNER_TIMEOUT_MS);
  }

  // ────────────── 人工介入提示横幅（红色）──────────────
  function showHumanBanner() {
    const existing = document.getElementById('aikefu-human-banner');
    if (existing) return;

    const banner = document.createElement('div');
    banner.id = 'aikefu-human-banner';
    banner.style.cssText = `
      position: fixed; top: 0; left: 0; right: 0; z-index: 99999;
      background: #ff4d4f; color: white; text-align: center;
      padding: 10px; font-size: 14px; font-weight: bold;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    `;
    banner.innerHTML = `
      ⚠️ 需要人工客服介入！
      <button onclick="this.parentElement.remove()" style="
        margin-left: 16px; background: white; color: #ff4d4f;
        border: none; padding: 2px 10px; border-radius: 4px; cursor: pointer;
      ">关闭</button>
    `;
    document.body.prepend(banner);

    // 10秒后自动关闭
    setTimeout(() => banner.remove(), 10000);
  }

  // ────────────── 买家画像浮窗（服务端返回 buyer_profile 时展示）──────────────
  // 在聊天窗口左上角悬浮显示买家画像卡片，3秒后自动消失
  function showBuyerProfile(profile) {
    // 移除已有浮窗
    const existing = document.getElementById('aikefu-buyer-profile');
    if (existing) existing.remove();

    const card = document.createElement('div');
    card.id = 'aikefu-buyer-profile';
    card.style.cssText = `
      position: fixed; top: 60px; left: 16px; z-index: 99998;
      background: white; border: 1px solid #d9d9d9; border-radius: 8px;
      padding: 12px 16px; font-size: 13px; color: #333; max-width: 260px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15); line-height: 1.6;
    `;

    // 当前商品信息（如果有）
    const goodsLine = profile.current_goods_name
      ? `<div>🛍️ 浏览商品：${profile.current_goods_name}</div>`
      : '';

    card.innerHTML = `
      <div style="font-weight:bold;margin-bottom:6px;">👤 买家画像</div>
      <div>昵称：${profile.buyer_name || '未知'}</div>
      <div>历史订单：${profile.order_count ?? '-'} 单</div>
      <div>总消费：￥${profile.total_amount ?? '-'}</div>
      <div>情绪状态：${profile.emotion || '正常'}</div>
      ${goodsLine}
      <button onclick="this.parentElement.remove()" style="
        margin-top:8px; background:#1890ff; color:white;
        border:none; padding:2px 10px; border-radius:4px; cursor:pointer; font-size:12px;
      ">关闭</button>
    `;
    document.body.appendChild(card);

    // 3秒后自动消失
    setTimeout(() => card.remove(), BUYER_PROFILE_DISPLAY_MS);
  }

  // ────────────── 订单管理页 XHR/fetch 拦截（主动同步）──────────────
  // 检测到订单管理页后拦截网络请求，捕获拼多多订单列表接口数据并同步到服务端

  // 判断 URL 是否为拼多多订单列表接口
  function isOrderListUrl(url) {
    return url && (
      url.includes('/order/list')
      || url.includes('/trade/order')
      || url.includes('/mms/order')
      || url.includes('orderList')
    );
  }

  // 启动订单管理页同步（仅在订单管理页调用）
  function startOrderPageSync() {
    console.log('[爱客服] 订单管理页已检测，启动XHR/fetch拦截');

    // ── 拦截 window.fetch ──
    const originalFetch = window.fetch;
    window.fetch = function (input, init) {
      const url = typeof input === 'string' ? input : (input?.url || '');
      return originalFetch.apply(this, arguments).then((response) => {
        if (isOrderListUrl(url)) {
          // 克隆响应避免消耗原始流
          response.clone().json().then((data) => {
            syncOrdersToServer(data);
          }).catch(() => {});
        }
        return response;
      });
    };

    // ── 拦截 XMLHttpRequest ──
    const OrigXHR = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (method, url) {
      this._aikefuUrl = url;
      this.addEventListener('load', function () {
        if (isOrderListUrl(this._aikefuUrl)) {
          try {
            const data = JSON.parse(this.responseText);
            syncOrdersToServer(data);
          } catch (e) {
            console.debug('[爱客服] 解析订单XHR响应失败:', e);
          }
        }
      });
      return OrigXHR.apply(this, arguments);
    };
  }

  // 从拼多多API响应中智能解析订单数组，兼容多种响应结构
  function extractOrdersFromPddAPI(apiData) {
    if (!apiData) return [];

    // 尝试常见响应路径
    const candidates = [
      apiData?.result?.list,
      apiData?.data?.list,
      apiData?.list,
      apiData?.result?.orders,
      apiData?.data?.orders,
      apiData?.orders,
    ];

    for (const arr of candidates) {
      if (Array.isArray(arr) && arr.length > 0) {
        return arr;
      }
    }

    return [];
  }

  // 批量同步订单数据到服务端 /api/orders/push
  async function syncOrdersToServer(apiData) {
    if (!shopToken || !isEnabled) return;

    const rawOrders = extractOrdersFromPddAPI(apiData);
    if (!rawOrders.length) return;

    // 规范化订单字段
    const orders = rawOrders.map((o) => ({
      order_id:       o.order_sn      || o.orderId      || o.order_id      || '',
      buyer_id:       o.buyer_id      || o.buyerId      || '',
      buyer_name:     o.buyer_name    || o.buyerName    || o.nickname       || '',
      goods_name:     o.goods_name    || o.goodsName    || o.item_name      || '',
      goods_img:      o.goods_img     || o.goodsImg     || o.item_img       || '',
      amount:         o.order_amount  || o.amount       || o.price          || '',
      quantity:       o.goods_num     || o.quantity     || o.num            || '',
      status:         o.order_status  || o.status       || '',
      refund_status:  o.refund_status || o.refundStatus || '',
      created_at:     o.create_time   || o.createdAt    || o.created_at     || '',
    }));

    try {
      const resp = await fetch(`${serverUrl}/api/orders/push`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Shop-Token': shopToken, // 商家令牌鉴权
        },
        body: JSON.stringify({ orders, source: 'browser_plugin' }),
      });
      if (resp.ok) {
        console.log('[爱客服] 订单批量同步成功，共', orders.length, '条');
      } else {
        console.warn('[爱客服] 订单批量同步失败，HTTP状态码：', resp.status);
      }
    } catch (e) {
      console.debug('[爱客服] 订单批量同步异常:', e);
    }
  }

  // ────────────── 工具函数 ──────────────
  function isVisible(el) {
    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  }

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

})();
