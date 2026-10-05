---
name: i-have-adhd
description: "Use only when the user explicitly invokes i-have-adhd or asks for this formatting mode. Organize the answer around the conclusion, next action, and short numbered steps. This is an optional presentation preference, not a diagnosis or an automatic writing-skill choice."
license: MIT
---

# i-have-adhd

Read `upstream.md` in full and use it as formatting guidance only after explicit invocation. Apply it to the requested response or duration. Continue for the session only if the user requests a session-wide mode; stop when the user requests normal output. Never enable it globally or infer activation from a mention of ADHD, a health question, or an installation request.

The upstream statement that the reader has ADHD is not evidence about this user. Do not infer, diagnose, or store a diagnosis. This integration offers an optional way to organize output; its medical generalizations are not clinical guidance.

Preserve facts, uncertainty, qualifications, conditions, and safety-relevant detail. A short or action-first answer must not turn a possibility into a diagnosis, an unverified explanation into a fact, or a proposal into completed work. Give time estimates only when there is a reasonable basis and label uncertainty. Do the authorized work rather than assigning unnecessary steps back to the user. Do not invent an action when the request only needs an answer.

Follow the user's language, document format, and requested level of detail. This mode shapes assistant responses and does not automatically rewrite quoted text or deliverables. For Japanese writing tasks, keep the existing yomiyasu/natural-japanese routing; for non-Japanese editing, keep Humanizer routing. Do not apply another writing skill solely because this mode was invoked. When both formatting and editing are explicitly requested, preserve the editing skill's meaning rules and the requested artifact format.

Only instructions, explicit-invocation metadata, and the MIT license are included. Do not install upstream hooks, run SessionStart code, change host settings, install dependencies, or make external calls to activate this mode.
