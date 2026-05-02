# Cursor 规则示例（任务完成时上报）

在 **Cursor Settings → Rules**（或项目 `.cursor/rules`）中加入一条规则，让 Agent 在**每次任务自然结束**时调用本目录下的脚本（作为 Hook 的补充，或在未配置 `stop` Hook 时使用）。

## 推荐：使用 `stop` Hook（见 README）

优先使用 `hooks.json` 的 `stop` 事件，可在无模型配合的情况下仍触发上报。

## 规则文案示例（中文）

将路径改为你本机的绝对路径：

```text
在本轮对话/任务已完全结束、且你已向用户交付最终答复后，必须执行一次（放在回复末尾，且不要再发起新工具调用）：

在终端运行（PowerShell）：
powershell -NoProfile -ExecutionPolicy Bypass -File "D:/claude/cursor_notification/hook_report.ps1" -Session "<用简短会话标识或 workspace 名>" -Task "<本轮任务稳定ID，可为 chat 标题的 slug>" -Status FINISHED -Title "<一句话概括任务>" -Message "<可选：一行摘要>"

若任务因错误终止，将 -Status 改为 ERROR。
```

说明：

- **`-Task`**：同一逻辑任务应使用**相同**字符串，便于面板合并为一条记录；若省略，每次会生成新 UUID，面板会出现多条。
- **`-Session`**：不同窗口/项目可用不同前缀区分。

## 与 Hook 的关系

- `stop` Hook：由 Cursor 在 Agent 停止时调用 `report_task.py --hook`，从 stdin JSON 尽力解析字段。
- **规则 + `hook_report.ps1`**：依赖模型执行命令，但更可控（可传 `-Title` / `-Message`）。

两者可同时启用；重复 `FINISHED` 上报时，通知会去重（同一 `session::task::FINISHED` 只弹一次）。
