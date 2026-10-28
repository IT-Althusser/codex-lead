---
name: codex-lead
description: 仅当用户明确要求“调用 Codex 写代码”“让 Codex 实现/修改”“你指挥 Codex”等委派实施需求时使用。普通写代码请求没有指定 Codex 时不触发。必须在 Codex 桌面可见专用会话执行；不得修改 Codex 原有模型选择和权限设置。发送任务后立即停止，不轮询，等待用户明确发送“继续”后再继续；只有明确授权且验收通过才提交或推送。不用于单纯讨论 Codex 用法或工具比较。
argument-hint: "<需求、项目绝对路径、已确认计划或继续说明>"
---

# Codex 桌面 mentor

本次需求：

$ARGUMENTS

先读取本 skill 目录的 `WORKFLOW.md`，完整遵循其中流程。调度细节按需读取 `references/desktop.md`，任务消息使用 `references/prompts.md`。

执行流程：确认需求 → 调用 Codex 桌面实施并立即停止 → 等待用户明确发送“继续” → mentor 独立审查 → 必要时发送返工并再次停止等待 → 验收交付。提交或推送仅按用户要求执行。
