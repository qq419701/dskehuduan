# 爱客服采集客户端 v2.1

`qq419701/aikefu`（爱客服AI客服系统）配套的 **Windows桌面采集客户端**。

> v2.1 更新亮点：新增AI回复反馈上报；服务端已删除规则引擎，意图规则支持纯文字回复；
> 客户端新增消息气泡视图支持；健康状态API对接。

## 系统架构

```
┌────────────────────────────────────────────────────────────┐
│                  aikefu 服务端（Flask）                      │
│   - 接收买家消息 → AI处理 → 下发任务                         │
│   - 管理店铺、插件、任务队列                                  │
│   - 地址：http://8.145.43.255:5000                          │
└───────────────────┬────────────────────────────────────────┘
                    │ HTTP REST API（无 MySQL 直连）
┌───────────────────▼────────────────────────────────────────┐
│            dskehuduan 客户端（本程序）                        │
│   - 账号登录 → 同步店铺 → 注册插件 → 轮询任务                 │
│   - 每家拼多多店铺独立运行 AikefuTaskRunner                    │
│   - 执行换号/退款等自动化操作并回报结果                        │
└────────────────────────────────────────────────────────────┘
```

## 功能特性

- 🔐 **账号登录体系**：用 aikefu 后台账号登录，无需单独配置数据库
- 🏪 **多店铺管理**：同步 aikefu 后台的拼多多店铺列表，一键激活/停用
- 🔌 **插件化架构**：每个激活店铺独立运行任务执行器，并发处理任务
- 💬 **实时消息采集**：WebSocket 直连 `wss://m-ws.pinduoduo.com/`
- 🤖 **AI回复自动发送**：意图规则命中后，服务端直接返回 `reply_to_buyer`，客户端通过 Playwright 自动发送给买家
- 🎮 **U号租专区**：账号管理、自动换号、自动选号（预留）、自动下单（预留）
- 📖 **内置帮助文档**：API 接入说明、常见问题，随时可查
- 🔔 **桌面通知提醒**：新消息和需人工介入时发送系统通知
- 📦 **Windows安装包**：支持 PyInstaller 打包 + Inno Setup 生成安装程序
- 📤 **AI回复状态反馈**：任务完成后，`reply_to_buyer` 发送成功后可回调通知服务端（v2.1新增）
- 🫧 **消息气泡视图支持**：客户端发送的AI回复通过服务端API记录，可在服务端后台查看完整对话（v2.1新增）
- ❓ **页面帮助说明**：各功能页面新增帮助按钮，点击展示使用说明（v2.1新增）

## 技术栈

| 组件 | 技术 |
|------|------|
| UI框架 | PyQt6 + PyQt6-Fluent-Widgets (qfluentwidgets) |
| 消息采集 | WebSocket (`websockets`) 直连拼多多 |
| 浏览器自动化 | Playwright（登录 + 自动发送消息） |
| 服务器通信 | HTTP REST API（`requests`，无 MySQL） |
| 加密 | PyCryptodome（AES-CBC，用于本地 token 缓存） |
| 打包 | PyInstaller + Inno Setup |

## 项目结构

```
dskehuduan/
├── app.py                      # 主入口
├── config.py                   # 配置管理（纯API模式，无MySQL）
├── requirements.txt            # pip依赖清单
├── build.py                    # PyInstaller打包脚本
│
├── core/
│   ├── server_api.py           # aikefu REST API客户端（含客户端认证接口）
│   ├── task_runner.py          # 任务轮询执行器（单店铺 + 多店铺管理器）
│   └── encrypt.py              # AES加密工具
│
├── channel/
│   ├── base_channel.py         # 渠道基类（含自动重连）
│   └── pinduoduo/
│       ├── pdd_login.py        # Playwright登录
│       ├── pdd_channel.py      # WebSocket直连采集
│       ├── pdd_message.py      # 消息格式解析
│       ├── pdd_order.py        # 订单采集
│       ├── pdd_product.py      # 商品信息采集
│       └── pdd_sender.py       # 通过Playwright发送AI回复
│
├── ui/
│   ├── main_window.py          # FluentWindow主窗口（v2.0启动流程）
│   ├── login_ui.py             # 账号密码登录弹窗（替代旧MySQL向导）
│   ├── shop_ui.py              # 拼多多店铺管理（从API读取）
│   ├── dashboard_ui.py         # 数据统计面板
│   ├── message_ui.py           # 实时消息监控
│   ├── setting_ui.py           # 设置界面（含店铺同步管理）
│   ├── plugin_status_ui.py     # 插件状态页（新增）
│   ├── uhaozu_ui.py            # U号租专区（全新重写）
│   ├── help_ui.py              # 内置帮助文档（新增）
│   ├── message_bubble_ui.py    # 消息气泡对话视图（v2.1新增）
│   └── help_widget.py          # 页面帮助悬浮组件（v2.1新增）
│
├── docs/
│   ├── plugin_transfer_human.md  # 转人工插件说明（已有）
│   ├── plugin_development.md     # 插件开发指南（v2.1新增）
│   └── api_changelog.md          # 服务端API变更记录（v2.1新增）
│
└── utils/
    ├── logger.py               # 日志工具
    └── notifier.py             # 桌面通知
```

## 快速开始

### 源码运行（开发模式）

```bash
# 1. 克隆仓库
git clone https://github.com/qq419701/dskehuduan.git
cd dskehuduan

# 2. 安装依赖
pip install -r requirements.txt

# 3. 安装 Playwright 浏览器
playwright install chromium

# 4. 启动客户端
python app.py
```

### Windows 安装包

```bash
python build.py
# 然后用 Inno Setup 编译 installer.iss
```

## 登录与店铺配置

1. **登录**：使用 aikefu 后台账号密码登录（首次启动自动弹出登录弹窗）
2. **同步店铺**：设置页 → 「拼多多店铺管理」→「🔄 同步店铺列表」
3. **激活店铺**：勾选需要启用任务执行器的店铺，点击「保存设置」
4. **启用轮询**：设置页 → 「任务执行器全局设置」→ 勾选「启用任务自动轮询」
5. **查看状态**：「🔌 插件状态」页面查看每个店铺的插件运行情况

配置文件：`~/.aikefu-client/config.json`（无需手动编辑）

## 插件化架构说明

每个激活的拼多多店铺对应一个独立的 `AikefuTaskRunner`，统一由 `MultiShopTaskRunner` 管理：

```
MultiShopTaskRunner
  ├── AikefuTaskRunner (shop_1, shop_token=xxx)
  │     ├── 心跳协程（每30秒）
  │     └── 轮询协程（每2秒）
  ├── AikefuTaskRunner (shop_2, shop_token=yyy)
  └── ...
```

支持的 action_codes：

| 动作码 | 说明 | 状态 |
|--------|------|------|
| `auto_exchange` | 自动换号（调用 U号租接口） | ✅ 可用 |
| `handle_refund` | 退款处理（记录模式，提示人工处理） | ✅ 可用 |
| `transfer_human` | 转人工（标记消息需人工介入） | ✅ 可用 |
| `auto_order` | 自动下单 | 🚧 开发中 |
| `order_sync` | 订单同步 | 🟡 预留 |
| 自定义 | 在 aikefu 后台「意图规则」配置，客户端注册时声明支持 | ✅ 支持 |

> **v2.1变更**：服务端规则引擎已删除，所有动作触发均通过「意图规则」配置。动作码不再与规则引擎挂钩，统一通过 `intent_rules` 表的 `action_code` 字段配置。

## U号租专区说明

| Tab | 状态 | 说明 |
|-----|------|------|
| 账号管理 | 🟡 预留 | 从 aikefu 服务端拉取账号列表 |
| 自动换号 | ✅ 可用 | 通过任务系统执行，支持手动测试 |
| 自动选号 | 🚧 开发中 | 骨架预留 |
| 自动下单 | 🚧 开发中 | 骨架预留 |
| 任务记录 | ✅ 可用 | 读取本地日志文件 |

## 开发指南：如何扩展新插件

1. 在 `core/task_runner.py` 的 `ACTION_HANDLERS` 字典中添加新的动作码：
   ```python
   ACTION_HANDLERS = {
       "auto_exchange": "_handle_auto_exchange",
       "your_new_action": "_handle_your_new_action",  # 新增
   }
   ```

2. 在 `AikefuTaskRunner` 类中实现对应的处理方法：
   ```python
   async def _handle_your_new_action(self, payload: dict) -> dict:
       # payload 来自 aikefu 服务端下发的任务
       ...
       return {"success": True, "message": "执行成功"}
   ```

3. 在 aikefu 后台「插件管理」中配置触发条件

4. **（可选）通知服务端回复已发送**

   客户端成功将 `reply_to_buyer` 发送给买家后，可通知服务端（用于统计和学习）：
   
   服务端 `/api/plugin/tasks/<id>/done` 响应中的 `reply_to_buyer` 非空时，
   客户端在通过 Playwright 或平台接口发送后，可在 payload 中增加 `reply_sent: true` 标志
   （服务端会在下次任务轮询时确认已发送状态）。

5. **配置意图规则触发条件**

   在 aikefu 后台「意图规则」页面（`/intent-rules/`）配置：
   - 触发关键词（如"换号","换个","换一个"）
   - 插件动作码（填写与 `ACTION_HANDLERS` 一致的键）
   - 立即回复话术（`auto_reply_tpl`，插件任务下发后立即发给买家）
   - 完成回复话术（`done_reply_tpl`，任务完成后发给买家，支持 `{变量}` 占位符）

## 与服务端 API 对接变更（v2.1）

### 变更1：规则引擎删除（对客户端无影响）

服务端已删除规则引擎，但客户端无需任何修改。
所有动作触发逻辑已迁移至「意图规则」，API 接口不变。

### 变更2：任务完成回复记录

服务端现在会将 `reply_to_buyer` 自动保存为 `direction='out'` 的消息记录，
用于在服务端后台展示完整买卖双方对话。

客户端无需额外操作，只需正常调用 `/api/plugin/tasks/<id>/done` 上报结果即可。

### 变更3：意图规则纯文字回复（服务端新增，对客户端无影响）

服务端新增了 `process_by='intent_reply'` 处理路径（意图识别命中 + 无需插件时直接回复），
此路径不会产生插件任务，客户端轮询不会收到此类任务。

### 变更4：系统设置API（服务端新增）

服务端新增 `/settings/` 配置页面和相关API，客户端可通过以下接口查询服务端状态：

```json
GET /api/health
// 响应
{
  "status": "ok",
  "version": "2.1.0",
  "database": "ok",
  "redis": "ok"
}
```

### 变更5：消息管理新增AI回复视图

服务端消息管理页现在展示完整买卖双方对话（气泡视图）。
客户端通过正常的 `/done` 接口上报任务完成即可，服务端会自动记录 `reply_to_buyer`。

## 拼多多上下文采集接口

客户端通过以下拼多多内部 HTTP 接口采集买家上下文，均使用 cookies 鉴权（无需开放 API）。

### 1. 浏览足迹接口（主力）

| 项目 | 说明 |
|------|------|
| URL | `https://mms.pinduoduo.com/latitude/goods/singleRecommendGoods` |
| Method | POST JSON |
| 鉴权 | Cookie（PDDAccessToken 等） |

**请求参数：**
```json
{"type": 2, "uid": "<买家uid>", "pageNum": 1, "pageSize": 10}
```

**响应关键字段：**
- `result.headGoods`：买家最近浏览的主商品（优先使用）
- `result.goodsList`：买家浏览足迹列表（兜底使用第0条）
- 每条商品包含：`goodsId`、`goodsName`、`thumbUrl`、`goodsUrl`

### 2. 买家订单接口（首选）

| 项目 | 说明 |
|------|------|
| URL | `https://mms.pinduoduo.com/latitude/order/userAllOrder` |
| Method | POST JSON |

**请求参数：**
```json
{"uid": "<买家uid>", "pageSize": 10, "pageNum": 1, "startTime": <时间戳>, "endTime": <时间戳>}
```

### 3. 买家订单接口（兜底）

| 项目 | 说明 |
|------|------|
| URL | `https://mms.pinduoduo.com/mangkhut/mms/recentOrderList` |
| Method | POST JSON |

**请求参数：**
```json
{"buyerUid": "<买家uid>", "pageNumber": 1, "pageSize": 10, "orderType": 0, ...}
```

### 采集时机

1. 买家发来第一条消息时立即触发（`fetch_and_update`）
2. 每30秒冷却期，避免频繁请求
3. 优先级：HTTP singleRecommendGoods > WS推送 biz_context > 链接提取

## 常见问题

**Q: 登录失败？**
- 检查服务器地址是否正确（默认 `http://8.145.43.255:5000`）
- 确认账号密码与 aikefu 后台一致

**Q: 同步店铺为空？**
- 确认 aikefu 后台已创建拼多多店铺，且当前账号有权限访问

**Q: 插件显示离线？**
- 检查「设置」→「任务执行器全局设置」是否已勾选「启用任务自动轮询」并保存
- 重启客户端后再查看

**Q: token 过期？**
- 在「设置」→「账号信息」→「退出登录」，重新用账号密码登录

**Q: 日志在哪里？**
- `~/.aikefu-client/logs/aikefu-client.log`（按天轮转，保留30天）

**Q: 任务完成后买家没有收到换号结果？**
- 检查 aikefu 后台「意图规则」中对应规则是否配置了 `完成回复话术`（done_reply_tpl）
- 检查客户端 `/done` 接口调用是否成功，查看响应中是否有 `reply_to_buyer` 字段
- 确认 Playwright 发送功能正常，查看客户端日志

**Q: 服务端消息管理页看不到AI回复？**
- v2.1 新功能，需要服务端升级到 v2.1.0 后才支持
- 检查任务上报接口（`/done`）是否返回了 `reply_to_buyer`

**Q: 意图规则配置了但不触发插件任务？**
- 检查「意图规则」中 `action_code` 是否与客户端注册的 `action_codes` 一致（区分大小写）
- 检查插件在线状态（`/plugins/` 页面）是否显示「在线」
- 检查客户端心跳是否正常（每30秒一次，超过5分钟无心跳视为离线）
