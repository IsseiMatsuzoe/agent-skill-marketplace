# External Agents verification

Date: 2026-09-29. Audited base: `07565230180468846c08f6c47c56e62d87648238` (`main`). Local runtime: Windows, Node v22.15.0, npm 10.9.2, Python 3.12.3. No existing test framework, backend or repository `AGENTS.md` was present. Work is on `feat/external-agents` in a separate clean clone; host integration is tracked separately below.

## Executed

| Check | Result | Evidence / limit |
| --- | --- | --- |
| Unit/mock and local MCP suite | passed | `npm test`: 28 tests, 28 passed, 0 failed. Only loopback networking; provider calls replaced with mocks. |
| Routing and selection | passed | All seven enabled aliases; auto_allowed and explicit_only; disabled/invalid aliases; forbidden raw provider overrides. |
| Privacy and budget | passed | Every OpenRouter request injects deny, optional ZDR; incompatible endpoint errors; no fallback/retry; provider request limits and Grok advisory output policy; premium configuration validation; concurrency. |
| Images | passed | Decode, MIME, actual base64 request bytes and dimensions; local upload and file-object normalization; absent/expired/failed/partial image rejection. |
| Download boundary | passed | Origin/scheme/userinfo/IP restrictions; DNS mixed-answer rejection at connect time; redirects rejected; byte overflow rejected. |
| X Search | passed (mock) | Native tool and filters present; citations, handles, timestamps and fetched counts normalized; unconfirmed search rejected; known usage retained on verification failure. |
| Error/logging boundary | passed | Missing keys, paid gate, HTTP auth/rate/provider errors, invalid JSON/output/model, timeout, prompt/key/image exclusion from logs. |
| MCP protocol | passed (local) | Official SDK client initialize, tools/list, one tool only, fileParams shape, call success/error, structuredContent/outputSchema, authenticated upload. |
| Authentication | passed (local) | Missing/wrong token rejected before inference, cross-origin requests rejected. |
| Production entry startup | passed (local) | Starts with all provider keys absent and paid gate false, authenticated health succeeds, test-owned process stopped. |
| Portable manifest and MCP schemas | passed | Validated against official Agent Plugins 1.0.0 schemas fetched that day using Python jsonschema. |
| Plugin/Skill validators | passed | Bundled plugin validator: both plugins; bundled Skill validator: all four new Skills. |
| Package boundary | passed | `python scripts/validate_package.py`; allowlist ZIP of 9 local files (8 remote; 6 skills-only), credential-bearing endpoint URL rejection, no backend or secrets packaged. |
| Dependency audit | passed | `npm audit --omit=dev --audit-level=high`: 0 known vulnerabilities at check time. |
| Public OpenRouter catalog | passed | `npm run check-models`, 2026-09-29T08:51:13Z: Gemini, Muse, Kimi, Qwen, DeepSeek configured IDs exist. No key or inference used. |
| Existing plugin boundary | passed | `git diff --exit-code 0756523 -- plugins/portable-agent-skills` empty; catalog's existing entry preserved. |
| Whitespace | passed | `git diff --check`. |

## Provider qualification completed before this host phase

The owner accepted all four provider smoke tests as PASS. Each ran once through the common backend; none were rerun in the host phase.

| Case | Result | Recorded evidence |
| --- | --- | --- |
| Claude text | PASS | input 89 / output 13 tokens |
| Claude image | PASS | input 315 / output 261; actual image bytes delivered and visible shapes described |
| Grok native X Search | PASS | input 84,572 / output 3,662 / reasoning 3,009; 10 search calls, 44 posts, 0 users |
| OpenRouter Gemini with deny | PASS | input 52 / output 9; provider reported USD 0.0000265 |

The Grok run demonstrated that an output request value and search-turn limit were not billing ceilings. The owner explicitly accepted this and requested conservative reasoning defaults instead. The updated adapter uses medium/low reasoning defaults and an advisory answer-length preference, with no retries or escalation. The new defaults have passed mocks; they have not yet been exercised with paid inference.

## Host phase, current qualification

- 28 local/mock tests passed, including the packaged stdio relay, authenticated image upload, common-tool discovery/call and safe transport failure.
- Local production configuration: all three keys present_unverified; paid gate disabled; remote image origins empty. No secret values printed.
- Codex installation and actual host invocation: pending this phase's qualification.
- ChatGPT / Work: connection package and exact tunnel runbook prepared; no tunnel/account/app association or host call verified.
- Chat -> MCP -> Claude attachment: unverified. A local fixture or provider smoke test does not prove this route.
- The 0.2.0 local package replaces the unauthenticated HTTP manifest with a stdio relay. Client-managed bearer authentication is kept outside the package. Root portable and Codex compatibility manifests are both retained.

See [host runbook](external-agents-hosts.md) for exact installation, paid enablement, tunnel and file-origin steps. No provider smoke retest is needed.

## Known limits

- `user_requested_agent` is an authenticated caller assertion; the server cannot independently reconstruct the user's conversation. Host authorization must prevent forged explicit intent.
- Direct-provider retention depends on account terms; it is not asserted to be ZDR. OpenRouter deny/ZDR constraints fail closed, which may make some aliases unavailable.
- `depth` requests answer detail, not a provider reasoning-effort setting. No automatic premium escalation exists.
- No automatic retry or cross-model fallback. A timeout can have an unknown billable outcome. Separate repeated client requests are not deduplicated and no persistent daily budget is implemented; use provider spending limits.
- Local assets are usable for 15 minutes, pruned on next access or service exit. No persisted images, native video, arbitrary binary documents or remote filesystem access.
- Portable HTTP declarations cannot carry a portable secret reference. The local package now uses an authenticated transport relay; hosted ChatGPT still needs a real registered remote connection.

## Changed file groups

- `.agents/plugins/marketplace.json`: append External Agents; preserve existing Portable Agent Skills entry.
- `plugins/external-agents/{plugin.json,mcp.json,.mcp.json,.codex-plugin/plugin.json}` and four `skills/*/SKILL.md`: independent portable/compatible package.
- `services/external-agents/{package.json,package-lock.json,.env.example,registry.json}`: reproducible dependencies and central configuration.
- `services/external-agents/src/{contracts,adapters,images,gateway,config,server,cli}.js`: one tool, adapters, policy, image and local setup boundaries.
- `services/external-agents/test/{gateway,mcp}.test.js`: offline/mock and loopback protocol checks.
- `services/external-agents/scripts/{package_plugin,validate_package}.py`: safe packaging and checks.
- `.github/workflows/external-agents.yml`, `.gitignore`, `README.md`, and these two `docs/external-agents*.md`: CI, exclusions, architecture/setup and verification.

The generated `.local` directory and `dist/external-agents.zip` remain ignored. `plugins/portable-agent-skills` is unchanged.
