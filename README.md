# codex-lead

在cc中让 Codex 在桌面专用会话中实施项目，由 mentor 下达任务、独立审查实际代码和测试证据；不合格就返工，达到要求后交付。只有用户明确要求且验收通过，才提交、推送或创建 PR。

不使用独立 `codex exec`、PTY 或未连接桌面的后端代替桌面实施。连接和权限诊断留在调度记录中，不混入项目任务消息。

## 环境要求

- Windows、PowerShell 5+，已安装并登录 Codex 桌面版。
- Python **3.10+**。
- 同一个 Python 解释器已安装 `websockets`，并支持同步客户端的 `proxy`、`ping_interval` 等连接参数；当前本机已验证版本为 **17.2**。工具会检查接口，不自动安装或升级。
- 本机共享后端默认地址为 `ws://127.0.0.1:18765`，不得转发到公网。

检查现有解释器与依赖：

```powershell
python -X utf8 -I -B -c "import sys, importlib.metadata; print(sys.version); print(importlib.metadata.version('websockets'))"
```

缺依赖时先使用已有合适解释器，或取得安装授权；不要把安装失败误报为桌面连接失败。

## 使用

自然语言提出“调用 Codex 写代码”“让 Codex 实现并由你审查”等需求即可触发，也可显式调用：

```text
/codex-lead <需求> <项目绝对路径> [约束和验收条件]
```

流程：**确认需求 → 连接预检 → 桌面实施 → mentor 独立审查 → 返工再审 → 可选提交**。

已确认的计划直接作为实施依据；用户要求先批准计划时，批准后才写代码。使用任务分支，保留已有修改。提交、推送和 PR 分别遵循用户授权，不自动串联。

## 连接准备

以下命令从本 skill 仓库根目录执行。

```powershell
python -X utf8 -I -B scripts/desktop.py doctor
```

doctor一次输出完整预检：依赖、桌面实际 TCP 连接和共享后端 initialize。仅`ready: true`表示这些连接条件全部满足；它不代表用户已经在桌面打开会话，也不代表项目网络和 Git 权限已通过。

未就绪时按[连接检查表](references/connection-checklist.md)处理具体原因。需要启动共享后端时，使用当前桌面对应的实际可执行文件路径：

```powershell
python -X utf8 -I -B scripts/desktop.py serve --codex '<已核实的桌面 codex.exe 完整路径>'
```

该命令长驻前台；保持此终端运行。由工具调度时使用后台任务并保留其任务标识，不自动反复启动。

在另一个终端，经授权启动桌面连接：

```powershell
powershell.exe -NoProfile -File scripts/launch_desktop.ps1
```

启动脚本先验证后端，再启动桌面并等待实际共享连接。应用已运行时不会擅自重启；保存工作并取得授权后才使用`-Restart`。关闭窗口仍留在托盘时应完全退出，不强杀。

详细的派单、审批与断线恢复见[调度手册](references/desktop.md)。所有命令中的项目、任务与提示词路径均由实际需求提供，不使用固定项目或旧会话。

## 工具与目录

```text
codex-lead/
├── SKILL.md
├── WORKFLOW.md
├── references/
│   ├── prompts.md                # 实施、审查返工、继续和交付模板
│   ├── desktop.md                # 调度、审批和恢复说明
│   └── connection-checklist.md   # 连接故障分类与执行前检查
└── scripts/
    ├── desktop.py                # doctor / backend / serve / send / recover / watch
    ├── launch_desktop.ps1        # 后端就绪检查、正常启动、实际连接等待
    ├── test_desktop.py           # 离线协议与调度回归
    └── test_launch_desktop.ps1   # 启动流程回归（模拟进程与连接）
```

`desktop.py`没有中断子命令。需要停止任务时使用桌面停止操作；mentor必须确认目标会话，不以关闭后端代替中断。工具也不自动管理登录或安装依赖。

## 运行记录

默认任务目录：`D:\codex-content\<当天日期>\codex-lead\<任务标识>\`。

- `task.json`：项目、会话和实际权限绑定。
- 每轮独立目录：`request.md`、`state.json`、`result.json`、简要事件及必要错误记录。
- 审批文件绑定对应请求，由用户逐条决定，不永久放行。

项目任务文件正文原样发送到桌面；调度证据不拼接进提示词。断线先核对原回合，不重复发送。mentor审查实际diff与验证结果，不以进程退出0代替完成。

## 离线测试

在仓库根目录的 PowerShell 中执行以下**完整命令**：

```powershell
$testRoot = Join-Path (Join-Path 'D:\codex-content' (Get-Date -Format 'yyyy-MM-dd')) 'codex-lead-validation'
python -X utf8 -I -B scripts/test_desktop.py --tmp-root $testRoot -v
powershell.exe -NoProfile -File scripts/test_launch_desktop.ps1 -TmpRoot $testRoot
```

`--tmp-root`是必填参数；不能省略。测试临时文件在指定D盘目录下创建并清理，不连接真实桌面、不发送模型任务、不执行项目命令。测试脚本同时禁用字节码缓存，`.gitignore`排除Python缓存。

真实只读连接检查使用`doctor`；`backend`只验证依赖和后端，不证明桌面已连接。模拟测试通过不代表真实模型审批、GUI展示、重启或仓库发布已经端到端通过。

## Skill 元数据

入口使用 Claude Code 支持的`name`、`description`及`argument-hint`，正文使用`$ARGUMENTS`。`argument-hint`是官方文档明确支持的补全提示字段，不是必填参数定义；面向通用 Agent Skills 的外部校验器可能采用更窄的字段集合。

参考：[Claude Code Skills 官方文档](https://code.claude.com/docs/en/skills#frontmatter-reference)。
