# 客户端插件开发指南

> 本文档说明如何在 dskehuduan 中开发新的插件动作处理器。

## 插件系统概述

```
aikefu 服务端（意图规则触发）
    ↓ 创建 PluginTask
dskehuduan 客户端（轮询获取任务）
    ↓ 根据 action_code 调用对应处理器
AikefuTaskRunner._handle_xxx()
    ↓ 执行业务逻辑
POST /api/plugin/tasks/<id>/done
```

## 开发步骤

### 1. 注册动作码

在 `core/task_runner.py` 的 `ACTION_HANDLERS` 字典中注册新的动作码与处理方法的映射关系：

```python
ACTION_HANDLERS = {
    "auto_exchange": "_handle_auto_exchange",
    "handle_refund": "_handle_refund",
    "transfer_human": "_handle_transfer_human",
    "your_new_action": "_handle_your_new_action",  # 新增
}
```

### 2. 实现处理方法

在 `AikefuTaskRunner` 类中实现对应的异步处理方法：

```python
async def _handle_your_new_action(self, payload: dict) -> dict:
    """
    处理自定义动作。
    :param payload: 来自 aikefu 服务端下发的任务数据
    :return: 包含 success 字段的结果字典
    """
    try:
        # 1. 从 payload 中获取参数
        param = payload.get("some_param", "")

        # 2. 执行业务逻辑
        result = await self._do_something(param)

        # 3. 返回成功结果
        return {
            "success": True,
            "message": "执行成功",
            "data": result,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"执行失败：{e}",
        }
```

### 3. （可选）通知服务端回复已发送

服务端 `/api/plugin/tasks/<id>/done` 响应中的 `reply_to_buyer` 非空时，
客户端在通过 Playwright 或平台接口将回复发送给买家后，
可在上报的 payload 中增加 `reply_sent: true` 标志，
服务端会在下次任务轮询时确认已发送状态（用于统计和学习）。

```python
# 示例：发送成功后上报 reply_sent 标志
done_payload = {
    "success": True,
    "message": "已发送",
    "reply_sent": True,  # 可选，表示 reply_to_buyer 已成功发给买家
}
await self.api.complete_task(task_id, done_payload)
```

### 4. 配置意图规则触发条件

在 aikefu 后台「意图规则」页面（`/intent-rules/`）新增规则：

| 字段 | 说明 | 示例 |
|------|------|------|
| 意图标识 | 唯一标识，建议与 `action_code` 一致 | `your_new_action` |
| 触发关键词 | 买家消息命中时触发，多个用逗号分隔 | `关键词1,关键词2` |
| 插件动作码 | 填写与 `ACTION_HANDLERS` 一致的键 | `your_new_action` |
| 立即回复话术 | 任务下发后立即发给买家（`auto_reply_tpl`） | `正在为您处理，请稍候～` |
| 完成回复话术 | 任务完成后发给买家（`done_reply_tpl`），支持 `{变量}` 占位符 | `已为您完成，结果：{result}` |

## 已有插件参考

### auto_exchange（自动换号）

- 文件：`core/task_runner.py` → `_handle_auto_exchange`
- 调用 U号租接口完成换号，将新号码通过 `reply_to_buyer` 返回给买家

### handle_refund（退款处理）

- 文件：`core/task_runner.py` → `_handle_refund`
- 记录退款请求，在本地 UI 高亮提示人工处理，不自动操作退款

### transfer_human（转人工）

- 文件：`core/task_runner.py` → `_handle_transfer_human`
- 标记消息 `needs_human=True`，发送桌面通知，提示人工介入
- 详见：[转人工插件说明文档](plugin_transfer_human.md)

## 调试技巧

- 查看任务轮询日志：`~/.aikefu-client/logs/aikefu-client.log`
- 在 aikefu 后台「插件管理」页面（`/plugins/`）查看插件在线状态和最近任务记录
- 心跳检测：每30秒一次，超过5分钟无心跳视为离线

## 注意事项

- `action_code` 区分大小写，须与「意图规则」中配置的完全一致
- 处理方法必须为 `async` 函数，耗时操作请使用 `await`
- 返回的 `reply_to_buyer` 字段（如有）会由服务端自动记录为消息历史，无需客户端额外操作
- v2.1 起，服务端规则引擎已删除，所有触发均通过「意图规则」配置
