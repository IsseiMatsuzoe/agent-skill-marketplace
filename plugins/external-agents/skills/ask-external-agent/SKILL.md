---
name: ask-external-agent
description: Ask an external specialist for a useful second opinion, or fulfill a named request such as Gemini, Muse, Kimi, Qwen, DeepSeek, Claude or Grok through the common gateway.
---

Read [shared orchestration](../orchestration.md) before selecting the task's referent and useful context.

Honor a named specialist using its logical lowercase alias. For an automatic second opinion, choose a suitable configured specialist; the gateway determines whether its provider is approved. Clarify a genuinely ambiguous name. Never construct a provider endpoint or choose a model ID in this Skill.

Call `call_external_agent` with `agent`, `task`, relevant context, the appropriate `mode`, and truthful `user_requested_agent`. A request such as "Ask Kimi" is already an explicit choice; do not ask for another Plugin-level confirmation. Gateway policy still applies. For visual critique require actual supported images and `visual_review: true`.

Attribute and evaluate the response before integrating it. In rewrite tasks preserve scientific meaning and claim strength unless the user requested substantive revision. Treat policy or availability failures as normal errors; do not convert them into consent loops.
