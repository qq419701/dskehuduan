# -*- coding: utf-8 -*-
"""
内置帮助/文档页（v2.1）
使用 QTextBrowser 展示 Markdown 格式的接入说明、API 文档和常见问题。
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextBrowser

HELP_HTML = """
<html><body style="font-family:微软雅黑,Arial,sans-serif;font-size:13px;color:#222;background-color:#ffffff;padding:16px;">

<h2>📖 爱客服采集客户端 v2.1 帮助文档</h2>

<h3>1. 系统架构</h3>
<pre style="background:#f4f6f8;padding:10px;border-radius:4px;">
┌────────────────────────────────────────────────────────────┐
│                  aikefu 服务端（Flask）                      │
│   - 接收买家消息 → AI处理 → 下发任务                         │
│   - 管理店铺、插件、任务队列                                  │
│   - 地址：http://8.145.43.255:5000                          │
└───────────────────┬────────────────────────────────────────┘
                    │ HTTP REST API
┌───────────────────▼────────────────────────────────────────┐
│            dskehuduan 客户端（本程序）v2.1                    │
│   - 账号登录 → 同步店铺 → 注册插件 → 轮询任务                 │
│   - 每家店铺独立运行 AikefuTaskRunner                         │
│   - 执行换号/退款/转人工/回复买家等自动化操作                   │
└────────────────────────────────────────────────────────────┘
</pre>

<h3>2. 快速开始</h3>
<ol>
  <li><b>登录</b>：使用 aikefu 后台账号密码登录客户端</li>
  <li><b>同步店铺</b>：在「设置」→「拼多多店铺管理」→「🔄 同步店铺列表」</li>
  <li><b>激活店铺</b>：勾选需要启用任务执行器的店铺，点击「保存设置」</li>
  <li><b>启用轮询</b>：在「设置」→「任务执行器全局设置」→ 勾选「启用任务自动轮询」</li>
  <li><b>查看状态</b>：在「🔌 插件状态」页面查看每个店铺的插件运行情况</li>
  <li><b>（v2.1新增）配置发音规则</b>：在「拼多多设置」→「🔊 转人工发音规则配置」填写触发关键词</li>
</ol>

<h3>3. 插件接入 API 文档</h3>
<table border="1" cellspacing="0" cellpadding="6"
       style="border-collapse:collapse;width:100%;font-size:12px;">
  <tr style="background:#f0f4ff;">
    <th>接口</th><th>方法</th><th>路径</th><th>说明</th>
  </tr>
  <tr><td>客户端登录</td><td>POST</td><td>/api/client/login</td>
      <td>Body: {username, password} → {success, client_token, username}</td></tr>
  <tr><td>同步店铺</td><td>GET</td><td>/api/client/shops</td>
      <td>Header: X-Client-Token → [{id, name, shop_token, platform}]</td></tr>
  <tr><td>注册插件</td><td>POST</td><td>/api/plugin/register</td>
      <td>Header: X-Shop-Token; Body: {plugin_id, name, action_codes, client_version}</td></tr>
  <tr><td>心跳保活</td><td>POST</td><td>/api/plugin/heartbeat</td>
      <td>Header: X-Shop-Token; Body: {plugin_id}</td></tr>
  <tr><td>轮询任务</td><td>GET</td><td>/api/plugin/tasks</td>
      <td>Header: X-Shop-Token → [{id, action_code, payload}]</td></tr>
  <tr><td>领取任务</td><td>POST</td><td>/api/plugin/tasks/{id}/claim</td>
      <td>防并发领取；404则忽略直接执行</td></tr>
  <tr><td>上报完成</td><td>POST</td><td>/api/plugin/tasks/{id}/done</td>
      <td>Body: {result: {...}}</td></tr>
  <tr><td>上报失败</td><td>POST</td><td>/api/plugin/tasks/{id}/fail</td>
      <td>Body: {error: "..."}</td></tr>
  <tr style="background:#fffbe6;"><td>回复买家 (v2.1)</td><td>POST</td><td>/api/plugin/reply_to_buyer</td>
      <td>Header: X-Shop-Token; Body: {buyer_id, reply, task_id}</td></tr>
  <tr><td>健康检查</td><td>GET</td><td>/api/health</td>
      <td>返回 200 即服务可达</td></tr>
</table>

<h3>4. 支持的 action_codes（v2.1）</h3>
<table border="1" cellspacing="0" cellpadding="6"
       style="border-collapse:collapse;width:100%;font-size:12px;">
  <tr style="background:#f0f4ff;">
    <th>动作码</th><th>说明</th><th>状态</th>
  </tr>
  <tr><td><code>auto_exchange</code></td><td>自动换号（调用 U号租换号逻辑）</td><td>✅ 已上线</td></tr>
  <tr><td><code>handle_refund</code></td><td>退款处理（记录模式，提示人工处理）</td><td>✅ 已上线</td></tr>
  <tr><td><code>transfer_human</code></td><td>转人工（自动操作拼多多页面转移会话）</td><td>✅ 已上线</td></tr>
  <tr style="background:#f0fff4;"><td><code>reply_sent</code></td><td>AI回复已发送通知（v2.1新增，本地记录日志）</td><td>✅ v2.1新增</td></tr>
  <tr><td><code>auto_order</code></td><td>自动下单选号</td><td>🚧 开发中</td></tr>
</table>

<h3>5. v2.1 新增功能说明</h3>
<dl>
  <dt><b>🔊 发音规则配置（替代规则引擎）</b></dt>
  <dd>
    在「拼多多设置」→「转人工发音规则配置」中，直接填写触发转人工的关键词（每行一个）。
    客户端收到 transfer_human 任务时，优先按此配置判断，无需在 aikefu 后台规则引擎中单独添加规则。
  </dd>

  <dt><b>📨 reply_sent 动作码</b></dt>
  <dd>
    服务端 AI 回复买家后，会下发 reply_sent 任务通知客户端。客户端记录日志，便于追踪回复状态。
    通过「插件状态」页面可查看已处理的 reply_sent 任务数量。
  </dd>

  <dt><b>🔗 reply_to_buyer 接口</b></dt>
  <dd>
    新增 <code>POST /api/plugin/reply_to_buyer</code> 接口，支持客户端主动将 AI 回复内容推送给买家，
    用于插件开发场景下的自定义回复流程。
  </dd>
</dl>

<h3>6. 常见问题</h3>
<dl>
  <dt><b>Q: 登录失败？</b></dt>
  <dd>检查服务器地址是否正确（默认 http://8.145.43.255:5000）；确认账号密码与 aikefu 后台一致。</dd>

  <dt><b>Q: 同步店铺为空？</b></dt>
  <dd>确认 aikefu 后台已创建拼多多店铺，并且当前账号有权限访问。</dd>

  <dt><b>Q: 插件显示离线？</b></dt>
  <dd>检查「任务执行器全局设置」中是否已勾选「启用任务自动轮询」并保存，然后重启客户端。</dd>

  <dt><b>Q: Token 过期怎么办？</b></dt>
  <dd>在「设置」页点击「退出登录」，重新用账号密码登录即可获取新 token。</dd>

  <dt><b>Q: 任务不执行？</b></dt>
  <dd>
    1. 确认插件已注册（插件状态页显示🟢在线）<br>
    2. 确认 aikefu 服务端有待执行任务（后台插件管理 → 任务队列）<br>
    3. 检查日志文件：<code>~/.aikefu-client/logs/aikefu-client.log</code>
  </dd>

  <dt><b>Q: 发音规则配置后不生效？</b></dt>
  <dd>保存后需要等下一次轮询周期（约2秒）才会使用新规则，无需重启客户端。</dd>

  <dt><b>Q: 日志在哪里？</b></dt>
  <dd><code>~/.aikefu-client/logs/aikefu-client.log</code>（按天轮转，保留30天）</dd>

  <dt><b>Q: 配置文件在哪里？</b></dt>
  <dd><code>~/.aikefu-client/config.json</code></dd>
</dl>

<hr>
<p style="color:#888;font-size:11px;">
爱客服采集客户端 v2.1 · 如有问题请联系技术支持
</p>

</body></html>
"""


class HelpPage(QWidget):
    """内置帮助/文档页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel("📖 帮助文档")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #222;")
        layout.addWidget(title)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet(
            "QTextBrowser { background-color: #ffffff; color: #222222; border: 1px solid #e0e0e0; border-radius: 4px; }"
        )
        browser.setHtml(HELP_HTML)
        layout.addWidget(browser)
