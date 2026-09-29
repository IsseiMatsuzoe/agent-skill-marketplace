---
name: ask-claude
description: Ask Claude for architecture, design, difficult reasoning or a second opinion. Use when the user requests Claude or an external specialist opinion would help an authorized task.
---

Read [shared orchestration](../orchestration.md) for adaptive context selection, language preservation, ordinary-call behavior and result integration.

Call `call_external_agent` with logical `agent: "claude"`, a focused `task`, and any context that materially helps. This normal Claude alias uses Sonnet. Use `agent: "claude-opus"` only when the user explicitly requests Opus or the premium profile; set `user_requested_agent: true` for that request. Never escalate from Sonnet to Opus automatically. Choose `design`, `review` or `general` to match the goal. Ordinary Claude calls do not require a Plugin-level context-send confirmation.

Ask for useful reasoning, actionable tradeoffs or a second opinion, not private chain-of-thought. Evaluate the advice before applying it; Claude does not receive repository access or execution tools through this workflow.
