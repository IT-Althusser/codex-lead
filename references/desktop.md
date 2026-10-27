# 桌面调度手册（仅mentor读取，不粘贴给Codex）

工具根目录是本 skill 的 `scripts/`。Python统一 `python -X utf8 -I -B`，使用本机已有 `websockets`，不自动安装。无需读取或复制Codex认证文件。工具只在Windows本机回环WebSocket工作，不提供独立CLI实施后备方案。

## 1. 先检查，后派单

```bash
python -X utf8 -I -B <skill>/scripts/desktop.py doctor
```

doctor同时检查initialize与实际TCP连接，桌面根进程（或其子进程）必须连到相同端口。仅app-server运行不通过。进程路径/版本随安装变动，禁止把上次exe哈希路径复制成固定配置。

这只能证明**共享后端**，不能证明GUI正在展示指定会话。首次任务启动记录threadId后，让用户在桌面打开对应任务，确认可以看到任务消息/工具过程；未确认前只说“共享会话已建立”，不能声称用户已经看见。必要时用桌面会话标题/记录ID定位，不选择“最近一条”代替任务映射。已有任务恢复只核对原ID，不每回合询问可见性。

桌面未连时：先确定是否已有任务在运行，不另起后端争抢。需要启动共享后端时核对当前桌面随附codex.exe路径和 `app-server --help`，经所需授权后：

```bash
python -X utf8 -I -B <skill>/scripts/desktop.py serve --codex <已核实的桌面codex.exe>
```

作为后台长驻进程执行，保留任务ID。仅监听127.0.0.1。桌面关闭后，经用户授权启动：

```bash
powershell.exe -NoProfile -File <skill>/scripts/launch_desktop.ps1
```

已经运行而需要重连时，先请用户保存工作，获准后才加 `-Restart`。脚本会识别托盘隐藏的进程；正常关闭不成功则请用户在托盘“退出”，不强杀、不反复重启。启动后再次doctor，不能以启动返回PID当作连接成功。

内存压力停止后台任务时不诊断为代码失败，不自动重启；用户要求恢复后检查资源、原turn和磁盘内容。不要为避免中断修改全局环境或关闭保护。不要把本手册的排障过程写进项目任务消息。

## 2. 发送：新任务与后续回合使用同一命令

先准备干净UTF-8 `request.md`，参照prompts.md。参数中的task是持久调度目录，不是项目仓库。每任务独立目录，同任务始终相同；文件不提交项目。

```bash
python -X utf8 -I -B <skill>/scripts/desktop.py send \
  --task D:/codex-content/<当天日期>/codex-lead/<任务标识> \
  --project <项目绝对路径> \
  --prompt <干净任务文件绝对路径> \
  --mode workspace-write
```

调查用read-only。send首次在同一连接thread/start+turn/start，避免未持久化rollout的resume错误；后续自动读取该task的准确threadId，先检查原状态，再resume订阅后发送。不改任务源码、不写固定threadId、不手动递增v2/v3文件名。

工具不会隐式把只读任务升为写权限：若用户批准实施后需切换模式，核实协议策略并建立关联的实施task/session，保留原调查记录，不修改现有task.json绕过检查。可继续在同一个桌面项目中显示两个明确名称的阶段会话。

发送后保存stdout中的run/threadId/turnId和外层后台任务ID。`task.json`记当前状态；每轮独立`turn-<uuid>/`保存request、state、result与简要event。它们不是Codex项目消息的一部分。

工具保留最后回合结果，不做GUI自动化，也不读取桌面应用内部凭据/数据库。历史日志可能含命令路径，按用户敏感信息规则处理；不要复制整个机器状态给Codex。

### 自动跟进

使用后台Bash执行send（完成通知是主信号），并启动Monitor监听该次run：

```bash
python -X utf8 -I -B <skill>/scripts/desktop.py watch --run <send输出的run目录> --seconds 1750
```

只读取首个turn_started用于取得run不属于轮询。watch在审批、结果、恢复结果或dispatch错误时发信号，未知/失败也能出现。Monitor期满而主任务仍运行时只续订监听，不重新派单。正常情况下不频繁read或发送“继续”。后台进程退出且无结果时检查stderr和recover，不把无通知当成功。

## 3. 审批：逐请求，不自动授权

工具已按本机0.164协议验证commandExecution和fileChange两类`decision`结构；桌面升级变更时先核对当前生成Schema，不猜新接口。其他请求（权限扩展、登录、用户输入工具等）默认不授予，报告不支持，不换执行者绕过。

每个待审批请求生成`approval-<digest>.json`，绑定thread、turn及完整请求。mentor读请求，向用户呈现准确command/cwd/原因或文件变更，取得**该请求的真实决定**后，才用Write写请求中指定的decisionFile：

```json
{
  "digest": "<请求文件中的完整摘要>",
  "threadId": "<目标threadId>",
  "source": "explicit-user-answer",
  "decision": "accept"
}
```

拒绝对应decline，停止该回合对应cancel；不能写acceptForSession/永久规则。`source`是调度记录约定，不是安全认证或OS隔离，不能伪填它来代替用户决定。工具无自动批准子命令，缺决定超时只cancel。优先使用桌面原生审批；本转交器不保证审批在桌面UI自动出现。

如果因用户等待导致连接问题，工具已禁客户端周期ping，但没有改变权限。断线仍先recover；旧请求答复文件不能作为新请求批准。未使用的决定文件和历史请求留在原回合，不挪作复用。

## 4. 断线恢复：读取，不重发

```bash
python -X utf8 -I -B <skill>/scripts/desktop.py recover --task <原task目录>
```

- completed：读原结果与真实产物，进入mentor审查。
- inProgress或unknown：不发新任务。读取原会话历史定位，不能猜测成功或已停止。
- interrupted/failed：核对磁盘后，在原task发送干净的剩余工作或返工单。
- turn/start应答丢失：可能根本没有拿到新turnId。工具不把历史最近一条强行认作目标；列出候选ID供核查。只能通过请求内容/发送时间/历史对应确认后补记录，不自动重发。
- 进程被强制停止留下dispatch.lock：先核对该PID是否仍为本任务及原回合状态；确认没有活进程后，只删除本任务遗留锁，不清理仓库、不删除任务历史。普通脚本正常退出会自行解除锁。

恢复时不重建分支、不重复git fetch、不回滚未提交内容，不把连接修复提示发进项目对话。工具结果失败只是调度失败，最终项目状态以原turn和真实产物为准。

## 5. 工具验证边界

```bash
python -X utf8 -I -B <skill>/scripts/test_desktop.py --tmp-root D:/codex-content/<当天日期>/codex-lead-validation
```

离线测试只验证状态机、消息不被技术前缀污染、按次审批、回合去重、参数和记录隔离，不发真实模型请求，不修改项目、不重启桌面。doctor是可另行执行的只读真实连接检查。模拟测试通过不等于所有GUI版本/审批/进程崩溃场景均端到端认证。

本机websockets或app-server不兼容时明确报告具体接口，不能承诺永不需适配。连接工具维护属于本skill的工作，不授权mentor代写业务项目代码。
