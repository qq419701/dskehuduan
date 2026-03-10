# 爱客服采集客户端 v2.0

`qq419701/aikefu`（爱客服AI客服系统）配套的 **Windows桌面采集客户端**。

> v2.0 重构亮点：去掉 MySQL 直连，改为纯 API 模式；新增账号登录体系；全面接入插件化架构。

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
- 🤖 **AI回复自动发送**：调用 aikefu API 获取 AI 回复并通过 Playwright 发送
- 🎮 **U号租专区**：账号管理、自动换号、自动选号（预留）、自动下单（预留）
- 📖 **内置帮助文档**：API 接入说明、常见问题，随时可查
- 🔔 **桌面通知提醒**：新消息和需人工介入时发送系统通知
- 📦 **Windows安装包**：支持 PyInstaller 打包 + Inno Setup 生成安装程序

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
│   └── help_ui.py              # 内置帮助文档（新增）
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

| 动作码 | 说明 |
|--------|------|
| `auto_exchange` | 自动换号（调用 U号租接口） |
| `handle_refund` | 退款处理（记录模式，提示人工处理） |
| `auto_order` | 自动下单（🚧 开发中） |

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
