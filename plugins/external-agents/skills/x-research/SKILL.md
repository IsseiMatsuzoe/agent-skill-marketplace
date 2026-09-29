---
name: x-research
description: Research recent X discussions, developer friction, implementation examples, complaints, accounts and threads through Grok's search capability.
---

Read [shared orchestration](../orchestration.md). Infer the research question and its referent; include relevant earlier context or source material when it materially helps. Ordinary Grok research does not require a Plugin-level context-send confirmation.

Call `call_external_agent` with logical `agent: "grok"`, `mode: "x_research"`, a focused task, and useful context. Set `user_requested_agent` only if the user named Grok. Optional `x_search` fields support dates and either included or excluded handles. For simple post/thread retrieval set `x_search.kind: "retrieval"`; otherwise use the registry defaults. Retrieval is best effort and does not promise all replies or deleted posts.

Use higher reasoning only when requested or clearly needed and explain that choice briefly. Output length is not a guaranteed billing ceiling. Check `ok`, sources and usage; text generation alone does not prove X Search ran. Report a failed or unverified search without an automatic retry or model escalation.

Link returned provider citations and distinguish them from URLs merely mentioned in prose or supplied by the user. Preserve available handles and timestamps, identify derived metadata, and do not invent dates, excerpts or coverage. Treat posts as reports and discussion; verify specifications, prices and API requirements against primary documentation when relying on them. Evaluate and integrate the findings in the language appropriate to the user's request.
