# External Agents verification

Date: 2026-09-29. Audited base: `07565230180468846c08f6c47c56e62d87648238` (`main`). Local runtime: Windows, Node v22.15.0, npm 10.9.2, Python 3.12.3. No existing test framework, backend or repository `AGENTS.md` was present. Work is on `feat/external-agents` in a separate clean clone; no installed plugin configuration was changed.

## Executed

| Check | Result | Evidence / limit |
| --- | --- | --- |
| Unit/mock and local MCP suite | passed | `npm test`: 25 tests, 25 passed, 0 failed. Only loopback networking; provider calls replaced with mocks. |
| Routing and selection | passed | All seven enabled aliases; auto_allowed and explicit_only; disabled/invalid aliases; forbidden raw provider overrides. |
| Privacy and budget | passed | Every OpenRouter request injects deny, optional ZDR; incompatible endpoint errors; no fallback/retry; output ceilings; premium configuration validation; concurrency. |
| Images | passed | Decode, MIME, actual base64 request bytes and dimensions; local upload and file-object normalization; absent/expired/failed/partial image rejection. |
| Download boundary | passed | Origin/scheme/userinfo/IP restrictions; DNS mixed-answer rejection at connect time; redirects rejected; byte overflow rejected. |
| X Search | passed (mock) | Native tool and filters present; citations, handles, timestamps and fetched counts normalized; unconfirmed search rejected; known usage retained on verification failure. |
| Error/logging boundary | passed | Missing keys, paid gate, HTTP auth/rate/provider errors, invalid JSON/output/model, timeout, prompt/key/image exclusion from logs. |
| MCP protocol | passed (local) | Official SDK client initialize, tools/list, one tool only, fileParams shape, call success/error, structuredContent/outputSchema, authenticated upload. |
| Authentication | passed (local) | Missing/wrong token rejected before inference, cross-origin requests rejected. |
| Production entry startup | passed (local) | Starts with all provider keys absent and paid gate false, authenticated health succeeds, test-owned process stopped. |
| Portable manifest and MCP schemas | passed | Validated against official Agent Plugins 1.0.0 schemas fetched that day using Python jsonschema. |
| Plugin/Skill validators | passed | Bundled plugin validator: both plugins; bundled Skill validator: all four new Skills. |
| Package boundary | passed | `python scripts/validate_package.py`; allowlist ZIP of 8 files (6 for skills-only), credential-bearing endpoint URL rejection, no backend or secrets packaged. |
| Dependency audit | passed | `npm audit --omit=dev --audit-level=high`: 0 known vulnerabilities at check time. |
| Public OpenRouter catalog | passed | `npm run check-models`, 2026-09-29T08:51:13Z: Gemini, Muse, Kimi, Qwen, DeepSeek configured IDs exist. No key or inference used. |
| Existing plugin boundary | passed | `git diff --exit-code 0756523 -- plugins/portable-agent-skills` empty; catalog's existing entry preserved. |
| Whitespace | passed | `git diff --check`. |

## Not executed / owner setup

| Test | Status | Required next condition |
| --- | --- | --- |
| Claude text | not_run | Owner enters Anthropic key and explicitly enables paid testing. |
| Claude actual image review | not_run | Same, plus harmless selected image and independent comparison of its visible content. Mock transfer does not prove live understanding. |
| Grok native X Search | not_run | Owner enters xAI key and approves one bounded search. |
| Inexpensive OpenRouter inference | not_run | Owner creates/enters OpenRouter key and enables paid testing; required privacy policy must remain in force. |
| Privacy-compatible model endpoint availability | not_run | Live inference under deny / optional ZDR. Catalog existence is insufficient. |
| Actual Codex/Work plugin pickup and invocation | not_run | Owner connects authenticated client and installs this reviewed plugin snapshot. SDK tests do not establish app pickup. |
| ChatGPT Web/tunnel/app mapping | blocked: setup | Owner connection, tunnel permissions/credential/workspace association or authenticated HTTPS hosting. Confirm local bearer forwarding; no authentication bypass. |
| Real ChatGPT attachment origins | blocked: setup | Observe an authorized attachment flow, allowlist its exact origin, then test transfer end-to-end. Defaults allow no remote download origin. |
| iOS | not_run | Owner's actual device after successful ChatGPT connection. |

All provider keys are **missing in the newly prepared local secret file**, MCP token is present, and paid calls are **disabled**. No search for existing private key values was performed. No inference charges were incurred by this implementation run. Only the owner should enter keys in `services/external-agents/.local/secrets.env`; report `doctor` statuses, never the values.

## Known limits

- `user_requested_agent` is an authenticated caller assertion; the server cannot independently reconstruct the user's conversation. Host authorization must prevent forged explicit intent.
- Direct-provider retention depends on account terms; it is not asserted to be ZDR. OpenRouter deny/ZDR constraints fail closed, which may make some aliases unavailable.
- `depth` requests answer detail, not a provider reasoning-effort setting. No automatic premium escalation exists.
- No automatic retry or cross-model fallback. A timeout can have an unknown billable outcome. Separate repeated client requests are not deduplicated and no persistent daily budget is implemented; use provider spending limits.
- Local assets are usable for 15 minutes, pruned on next access or service exit. No persisted images, native video, arbitrary binary documents or remote filesystem access.
- The portable HTTP declaration cannot itself carry a secret reference. Client-managed authentication and live product configuration remain required. ChatGPT connection is not claimed complete.

## Changed file groups

- `.agents/plugins/marketplace.json`: append External Agents; preserve existing Portable Agent Skills entry.
- `plugins/external-agents/{plugin.json,mcp.json,.mcp.json,.codex-plugin/plugin.json}` and four `skills/*/SKILL.md`: independent portable/compatible package.
- `services/external-agents/{package.json,package-lock.json,.env.example,registry.json}`: reproducible dependencies and central configuration.
- `services/external-agents/src/{contracts,adapters,images,gateway,config,server,cli}.js`: one tool, adapters, policy, image and local setup boundaries.
- `services/external-agents/test/{gateway,mcp}.test.js`: offline/mock and loopback protocol checks.
- `services/external-agents/scripts/{package_plugin,validate_package}.py`: safe packaging and checks.
- `.github/workflows/external-agents.yml`, `.gitignore`, `README.md`, and these two `docs/external-agents*.md`: CI, exclusions, architecture/setup and verification.

The generated `.local` directory and `dist/external-agents.zip` remain ignored. `plugins/portable-agent-skills` is unchanged.
