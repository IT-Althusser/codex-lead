---
name: codex-lead
description: 当用户要求“调用 Codex 写代码”“让 Codex 实现/修改”“你指挥 Codex、审查并返工”等委派实施需求时使用，无需用户输入斜杠命令。必须在 Codex 桌面可见专用会话执行，由 mentor 独立审查和安排返工；只有明确授权且验收通过才提交或推送。不用于单纯讨论 Codex 用法或工具比较。
argument-hint: "<需求、项目绝对路径、已确认计划或继续说明>"
---

# Codex 桌面 mentor

本次需求：

$ARGUMENTS

先读取本 skill 目录的 `WORKFLOW.md`，完整遵循其中流程。调度细节按需读取 `references/desktop.md`，任务消息使用 `references/prompts.md`。

执行流程：确认需求 → 调用 Codex 桌面实施 → mentor 独立审查 → 不合格返工 → 验收交付。提交或推送仅按用户要求执行。
