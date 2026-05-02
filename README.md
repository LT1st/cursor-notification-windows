# Cursor 本机任务通知与状态面板（Windows）

在 Windows 上实现：

1. **任务完成（或失败）时**弹出系统通知（Toast / Plyer 回退）。
2. **常驻桌面窗口**列出所有已上报任务的状态，并自动刷新。

## 依赖

- Python 3.8+（建议 3.10+；`win11toast` 在较低版本解释器上可能无法导入，将自动使用 `plyer`）
- Tkinter（多数 Windows Python 安装自带；若缺失请用官方安装器勾选 *tcl/tk* 或安装 `python-tk` 对应包）

安装 Python 包：

```powershell
cd D:\claude\cursor_notification
pip install -r requirements.txt
```

## 状态文件位置

默认：`%LOCALAPPDATA%\cursor_notification\data\state.json`

可通过环境变量覆盖：

```powershell
$env:CURSOR_NOTIFICATION_STATE = "D:\data\cursor_state.json"
```

`status_panel.py` 与 `report_task.py` 会读取同一路径（或使用各自的 `--state` 参数保持一致）。

## 启动状态面板

```powershell
python D:\claude\cursor_notification\status_panel.py
```

可选：

```powershell
python status_panel.py --poll 500 --state "%LOCALAPPDATA%\cursor_notification\data\state.json"
```

窗口内 **「清空已完成」** 会删除状态里所有 `FINISHED` / `ERROR` / `FAILED` 记录。

## 方式 A：Cursor `stop` Hook（推荐）

1. 复制 [hooks.json.example](hooks.json.example) 中内容到：

   - **项目级**：仓库根目录 `.cursor/hooks.json`，或  
   - **用户级**：`%USERPROFILE%\.cursor\hooks.json`

2. 把示例里的 `python "D:/claude/cursor_notification/report_task.py"` 改成你机器上的**绝对路径**（`python` 需在 PATH 中，或使用 `py` 启动器自行改写 `command`）。

3. 保存后可在 Cursor **Hooks** 设置/输出通道确认是否加载；必要时重启 Cursor。

4. Hook 使用 **`stop`** 事件：Agent 结束时 Cursor 会把 JSON 写到子进程 stdin，由 `report_task.py --hook` 解析并更新状态、在到达终态时弹通知。

若 stdin 的 JSON 字段与当前 Cursor 版本不一致，脚本会尽量用默认值（详见 `report_task.py` 中 `_extract_from_hook`）。

### 可选：PowerShell 包装脚本

若必须用脚本包装（例如统一指定 `py` 路径），可将 `command` 设为：

```json
"command": "powershell -NoProfile -ExecutionPolicy Bypass -File \"D:/claude/cursor_notification/hooks/cursor_agent_stop.ps1\""
```

## 方式 B：规则或手动调用 `hook_report.ps1`

在未配置 Hook 或需自定义标题时，可在任务结束后执行：

```powershell
.\hook_report.ps1 -Session "projA" -Task "refactor-auth" -Status FINISHED -Title "Auth 重构完成"
```

参数说明见 [CURSOR_RULE_EXAMPLE.md](CURSOR_RULE_EXAMPLE.md)。

## 手动测试（不上 Cursor）

```powershell
python report_task.py --session test --task t1 --status RUNNING --title "演示"
python report_task.py --session test --task t1 --status FINISHED --title "演示"
```

第二次应出现**一次**完成通知（若 Toast 环境可用）。再执行一次相同 `FINISHED` 不应再弹。

## 参考仓库

- [hgbdev/cursor-agent-notifier](https://github.com/hgbdev/cursor-agent-notifier) — 完成时触发脚本思路（macOS）。
- [leo07/agents-control-tower](https://github.com/leo07/agents-control-tower) — 多任务集中展示。
- [len5ky/CursorRemote](https://github.com/len5ky/CursorRemote) — 多窗口状态聚合架构参考。

## 文件说明

| 文件 | 作用 |
|------|------|
| `state_store.py` | `state.json` 读写、合并、锁、清空已完成 |
| `notifier.py` | Toast（win11toast → plyer 回退） |
| `report_task.py` | `--hook` / 命令行上报入口 |
| `status_panel.py` | 常驻 Tk 面板 |
| `hook_report.ps1` | PowerShell 手动上报 |
| `hooks/cursor_agent_stop.ps1` | 可选：从 stdin 转给 `report_task.py --hook` |
| `hooks.json.example` | 复制到 `.cursor/hooks.json` 的模板 |

## 故障排除

- **无通知**：查看终端/stderr；确认 `plyer` 已安装；部分环境需聚焦前台才显示通知。
- **Hook 未执行**：检查 `hooks.json` 路径、`command` 中引号转义、Python 是否在 PATH。
- **面板无数据**：确认 `report_task.py` 与面板使用同一 `--state` / 默认路径。
