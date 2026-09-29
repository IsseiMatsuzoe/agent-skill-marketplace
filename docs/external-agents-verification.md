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
- Codex installed as `external-agents@personal` 0.2.0 from GitHub branch `feat/external-agents`. CLI `0.158.0-alpha.2.1` exercised all four Skills and the common tool; see results below. Desktop fresh-chat invocation remains separate.
- ChatGPT / Work: local and skills-only archives prepared; `--app-id` packaging is implemented and tested with an isolated synthetic mapping. A final mapped archive awaits the real registered app ID. Official Windows tunnel-client 0.0.15 is downloaded and its help tested; no tunnel/account/app association or Chat/Work call verified.
- Chat -> MCP -> Claude attachment: unverified. A local fixture or provider smoke test does not prove this route.
- The 0.2.0 local package replaces the unauthenticated HTTP manifest with a stdio relay. Client-managed bearer authentication is kept outside the package. Root portable and Codex compatibility manifests are both retained.

See [host runbook](external-agents-hosts.md) for exact installation, paid enablement, tunnel and file-origin steps. No provider smoke retest is needed.

## Actual Codex host results

All four used `mcp__external_agents__call_external_agent` loaded from the installed Plugin, after reading the corresponding installed Skills. The owner explicitly enabled the existing paid gate for this qualification. These are **new host integration calls**, not provider smoke retests.

| Installed Skill / case | Result | Gateway request ID | Usage / policy |
| --- | --- | --- | --- |
| ask-claude / text | PASS | `b565f33d-6e86-4cae-a04b-e43d1650c310` | Claude Sonnet 5.5; input 115, output 89 |
| x-research / native X Search | PASS | `932f814e-958c-4874-aa2b-62c317d0ecb0` | Grok 4.7; low reasoning; input 26,006, output 1,461, reasoning 953, cached 18,560; x_search_calls 8, x_posts_fetched 16, x_users_fetched 0 |
| ask-external-agent / Gemini | PASS | `141994da-4e35-45ce-a133-79a6d4b0616b` | Gemini 3.1 Flash Lite; deny_collection/data_collection=deny; input 57, output 74; reported cost USD 0.00012525 |
| design-review / attached image | PASS after local upload permission correction | `4c29d794-d06d-4e72-aeac-3d511d3d0beb` | Claude Sonnet 5.5; input 354, output 213; one actual PNG 480x320 |

Claude's image response correctly identified a red circle on the left, a blue rectangle in the upper right and a green triangle below it. The normalized image SHA-256 was `8a83d5cc60f117a174ddd21c5b322284d91c777e9bdd98555caa644a19e84bad`, matching the independent fixture check. The exact image was attached to Codex with `--image`; the installed Plugin upload helper transferred its bytes before the common MCP call. No visual description was inserted into the outbound task or context.

The first upload attempt failed with sandbox `EPERM` before any image inference. The remaining image case succeeded using scoped automatic approval for the same installed helper. There were four provider calls in total and **zero inference retries**. The three ordinary MCP calls did not add confirmation prompts. A separate no-cost preflight reached `PAID_CALLS_DISABLED`, request `3cb81329-d93b-46f8-b05f-ff84a3efce8b`.

Grok source metadata contained two `x.com/SpaceXAI/status/...` URLs, handles derived from those URLs and null timestamps. The requested filter was `allowed_handles: ["xai"]`; account alias/rename equivalence and factual claim accuracy were not independently verified. Native search execution is established, but strict account-filter interpretation and claims are not certified. No follow-up search was made.

The test backend was stopped and `EXTERNAL_AGENTS_ENABLE_PAID=false` restored. The Plugin remains installed/enabled. Source files and installed files match after Git CRLF normalization. All 28 files in the existing installed Portable Agent Skills snapshot are byte-for-byte unchanged, and its enabled state remains true. The repository's Portable subtree is unchanged from the audited baseline.

## Host / packaging issues discovered

- A portable HTTP declaration alone could not supply the local bearer credential. The installed 0.2.0 package now uses a stdio-only transport relay; provider implementations remain shared.
- Changing an existing Personal marketplace ref requires source remove/add in this CLI. Its GitHub source currently points to `feat/external-agents`, pending review/merge. No duplicate marketplace was created.
- Windows sandbox shell access to the private connection file is denied. The image helper needs scoped host approval; text/search MCP calls work without that shell operation.
- CLI startup logged a cache auto-refresh access-denied warning. Explicit install succeeded and all installed-code comparisons and calls passed. General automatic refresh reliability remains a host concern; the unrelated built-in plugin warnings were not altered.
- Portable stdio is a local-host transport. Hosted ChatGPT requires a tunnel or authenticated HTTPS connection, plus the real app mapping. The tunnel command interface is checked; authenticated discovery and workspace association still require the owner.
- The tested retrieval completed within the host's default tool timeout. Longer calls and hosted transport timeouts remain unqualified; uncertain outcomes must never trigger an automatic retry.
- **Chat -> MCP -> Claude image transfer is not verified.** No Chat/Work attachment was substituted with the Codex result. Remote image origins remain empty until a real authorized host file flow identifies them.

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
