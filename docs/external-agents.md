# External Agents

The new plugin is independent of `portable-agent-skills`. It exposes four thin workflow skills and one MCP tool:

```text
ChatGPT / Work / Codex
  -> workflow Skill
  -> call_external_agent
  -> validated internal registry + selection/privacy/cost checks
  -> Anthropic | xAI | OpenRouter adapter
  -> normalized structuredContent + matching outputSchema
```

The implementation uses Node 22+, the official MCP SDK, Zod for boundary validation, Sharp for image decoding, and ipaddr.js for IP classification. Native `fetch`, HTTP, crypto and the Node test runner handle the rest. There is no build step or provider SDK with hidden retries. Install dependencies only inside `services/external-agents`.

## Local setup (Windows first)

From the repository root:

```powershell
Set-Location services/external-agents
npm ci --ignore-scripts --no-audit --no-fund
npm test
npm run setup
npm run doctor
notepad .local/secrets.env
```

Only the owner enters the values for these variables in `services/external-agents/.local/secrets.env`:

- `ANTHROPIC_API_KEY`: your existing Anthropic inference key.
- `XAI_API_KEY`: your existing xAI inference key.
- `OPENROUTER_API_KEY`: create a key at [OpenRouter API keys](https://openrouter.ai/settings/keys), set an account/key spending limit, and enter it locally.

Never paste keys into chat. `.env.example` contains names and empty assignments only. `setup` prepares the ignored `.local` directory, creates an independent random MCP bearer token, copies the registry for owner customization, and sets `EXTERNAL_AGENTS_ENABLE_PAID=false`. It never overwrites existing files or prints secrets. Keep this directory in your private user profile, out of shared/synced folders. On Windows, POSIX mode flags are not an ACL: use a private Windows account folder and verify its inherited permissions before entering secrets. Restrict access through Properties > Security if needed.

`doctor` is offline and prints `present_unverified` or `missing`, never values. Key presence does not prove authentication, credits, model access, or privacy-compatible endpoints. The service can start with missing provider keys; inference then returns `CONFIG_REQUIRED`.

After mock checks and deliberate approval of paid use, change **only locally**:

```text
EXTERNAL_AGENTS_ENABLE_PAID=true
```

Run `npm start` in a terminal. It binds only to `127.0.0.1:47831`; stop with Ctrl+C. Restart after settings, registry or secret changes. To disable paid calls, restore `false` and restart. No system service, firewall change, tunnel, cloud deployment or automatic startup is installed.

## Client connection and installation

See [host installation and qualification](external-agents-hosts.md) for the exact Personal marketplace, local relay, paid gate, ChatGPT tunnel and attachment steps. The local package contains a stdio transport relay; the backend remains separate. Root `plugin.json`/`mcp.json` are portable, with Codex compatibility manifests. No credentials are packaged. Hosted ChatGPT needs a real remote connection and app association; installing a ZIP alone does not establish that connection.

## Registry and request contract

`services/external-agents/registry.json` contains the shipped defaults. After `setup`, edit `.local/registry.json` for owner configuration. Only backend adapters know endpoints and request formats. Registry v2 rejects invalid privacy/backend combinations, duplicate aliases, unsupported capabilities, malformed endpoint allowlists and model routing variants. Premium profiles always require explicit selection. Changing a backend to a supported replacement does not require a Skill edit; a new provider API needs only an adapter plus backend validation/key mapping.

| Alias | Backend | Default model | Selection |
| --- | --- | --- | --- |
| claude | Anthropic direct | claude-sonnet-5-5 | auto_allowed |
| claude-opus | Anthropic direct | claude-opus-5-5 | explicit_only, premium |
| grok | xAI direct | grok-4.7 | auto_allowed |
| gemini | OpenRouter | google/gemini-3.1-flash-lite | auto_allowed |
| muse | OpenRouter | meta/muse-spark-1.3 | auto_allowed |
| kimi | OpenRouter | moonshotai/kimi-k2.5 | explicit_only |
| qwen | OpenRouter | qwen/qwen3.6-flash | explicit_only |
| deepseek | OpenRouter | deepseek/deepseek-v4.1-flash | explicit_only |
| experimental | OpenRouter | unset, disabled | explicit_only |

Normal Claude use routes to Sonnet through `claude`. `claude-opus` is the enabled premium Opus profile and is explicit-only; the gateway does not escalate from Sonnet. The active Anthropic API model IDs are `claude-sonnet-5-5` and `claude-opus-5-5` ([Anthropic model lifecycle](https://docs.anthropic.com/en/docs/about-claude/model-deprecations)). Gemini uses an inexpensive Flash Lite, and the regular Muse variant is configured rather than a contributor variant. Catalog existence does not establish key access, privacy compatibility or model quality. There is no fallback, automatic generation retry, model escalation or multi-agent loop.

### Provider trust and endpoint controls

Trust is configured once under `routing`, independently of each agent's fixed `model` and capabilities. There is no per-agent `selection_policy` in v2:

- `routing.direct` assigns Anthropic and xAI the `auto_allowed` tier by default. Either can be set to `explicit_only`.
- `routing.openrouter.approved_model_providers` is the configurable model-publisher allowlist: initially `google` and `meta`. The publisher is the namespace before `/` in a fixed OpenRouter model ID, not the logical alias or a particular model release. Unlisted publishers default to `explicit_only`.
- `routing.openrouter.approved_providers` independently limits actual inference hosts for automatic calls: initially `google-vertex`, `google-ai-studio`, and `meta`. Approving a model author does not approve arbitrary hosting companies.
- `routing.openrouter.explicit_providers` pins optional family-specific hosts used only after explicit model/family selection. Initial routes are `moonshotai: ["novita"]`, `qwen: ["alibaba"]`, and `deepseek: ["deepseek"]`. These hosts are not promoted to automatic use. Their published endpoint IDs were checked on 2026-09-29; compatibility with `deny` is still determined by OpenRouter per request. An explicit family without a configured route remains restricted to the approved serving hosts.

Promotion is an owner registry change after review: add the publisher and any reviewed serving host to the respective allowlists. Removing a publisher immediately restores explicit-only selection; removing a serving host prevents automatic use of that host. Changing a model within the same publisher does not change its trust tier. An empty applicable endpoint list returns `POLICY_OR_MODEL_UNAVAILABLE` before any transmission. An unavailable compatible endpoint returns a normal policy/availability error, with no consent loop, weaker privacy policy or substitute route.

Automatic OpenRouter requests set `provider.only` to the approved serving hosts; explicitly named requests use the configured family route when present. Every route still sets `data_collection: "deny"`, `allow_fallbacks: false`, and `require_parameters: true`, plus ZDR when configured. Endpoint base slugs include their variants/regions under OpenRouter's documented matching rules; configure a full endpoint slug if regional scope must be narrower. Model routing suffixes such as `:free` are rejected; the model must remain fixed.

For an existing v1 `.local/registry.json`, preserve the file before migrating: retain each agent's model, capabilities, limits, privacy and enabled state; remove per-agent `selection_policy`; add the reviewed `routing` block and set `version: 2`. Map any owner-specific selection restrictions into provider tiers/allowlists before restarting. Do not overwrite a customized registry with defaults. A v1 registry fails closed rather than silently inheriting automatic trust.

This change keeps registry schema v2; no schema migration is required, and setup still never overwrites `.local/registry.json`. A local v2 registry remains the sole routing source. The existing local `claude` entry already uses `claude-sonnet-5-5`, so no Sonnet model edit is needed. To enable Opus in a customized local registry, manually add a v2 agent entry with these values: `alias: "claude-opus"`, `backend: "anthropic"`, `model: "claude-opus-5-5"`, `capabilities: ["general", "design", "review", "rewrite", "image"]`, `privacy_profile: "direct"`, `default_depth: "standard"`, `default_max_output_tokens: 2048`, `max_output_tokens: 8192`, `enabled: true`, and `premium: true`. Keep the existing `routing` block and other custom agents unchanged. Missing Opus configuration fails with `INVALID_AGENT`; an Opus model without the premium flag fails registry validation with `CONFIG_REQUIRED`. Neither case falls back to Sonnet or changes routing. The local registry is not edited by this PR.

### Host orchestration

All four Skills load the packaged `skills/orchestration.md`. Instructions are primarily English; source material stays in its original language and form, and the host requests the response language appropriate to the user. The host interprets the current referent and selects useful context: relevant conversation excerpts, documents or connected resources are valid alongside code, equations and screenshots. There is no mandatory context template. The gateway does not infer context, retrieve files or translate material.

Ordinary calls to trusted routes, including Claude and Grok, have no Plugin-level preflight or context-send confirmation. Existing platform consent still applies. Secrets and unrelated private material are excluded without prompting. The paid-use switch is an owner runtime setting, not a per-call consent requirement. Explicit-only errors are availability/policy results, not invitations to repeatedly ask for consent.

`call_external_agent` accepts:

- `agent`, `task`; optional `mode`, `context`, `depth`, `max_output_tokens`, `reasoning_effort`.
- `user_requested_agent`: defaults false; true only when the user explicitly requests the agent or its provider family. The gateway enforces this for `explicit_only`; this is a **trusted caller attestation**, not cryptographic proof of the original conversation. Host approvals remain responsible for truthful user-intent provenance.
- `attachments`: selected text files as `{name, text}`; no arbitrary filesystem reading. Binary documents are not supported.
- `image_files`: host-provided OpenAI file objects; `asset_ids`: opaque local upload references. `visual_review: true` requires real images.
- Optional `x_search.kind` (`discussion` or `retrieval`) and date/handle filters for `x_research` only.

Five modes are `general`, `design`, `review`, `x_research`, `rewrite`. `depth` (`brief`, `standard`, `deep`) controls requested answer detail. For Anthropic, depth defaults to effort `low`, `medium`, and `high`, respectively; a supplied supported `reasoning_effort` overrides that mapping. Anthropic sends `thinking: {type: "adaptive"}` and `output_config.effort`; it does not send legacy `budget_tokens`. xAI retains its own reasoning defaults and explicit override behavior rather than sharing Anthropic's depth mapping.

The public `max_output_tokens` remains for compatibility and is returned internally as `answer_target_tokens`. Its provider semantics differ: Anthropic asks for approximately that much visible answer text while sending `max_tokens: 128000` as a final generation safety ceiling; xAI includes it only as an answer-length preference in the prompt; OpenRouter continues to send it as the provider's hard `max_tokens` limit. The OpenRouter path remains non-streaming in this change. The registry's existing `output_limit_policy` controls whether a requested target is limited by the local registry; `policy.provider_output_policy` and `policy.provider_generation_ceiling` describe the provider behavior. These values are not dollar ceilings. Anthropic's 128,000-token maximum is not an expected usage amount; billing remains based on actual generated tokens. `policy.guaranteed_cost_ceiling` is always false.

Anthropic Messages and xAI Responses calls aggregate provider streams into the existing final MCP result; the tool does not expose token-by-token output. The direct-provider transport has a 30-second connection/header timeout, a 5-minute idle/no-event timeout reset by keepalives and meaningful reasoning, text, search or tool events, and an absolute limit of 10 minutes for brief/standard calls or 30 minutes for deep and X-research calls. The local stdio relay and smoke client allow 31 minutes so they do not cut off the gateway's 30-minute maximum. OpenRouter remains synchronous with its existing 90-second timeout; its policy metadata labels this `openrouter_sync_90s`, separate from the direct-provider timeout profiles.

There is no automatic retry for provider errors, timeouts, interrupted streams or uncertain outcomes. An Anthropic `max_tokens` stop with no visible text returns `OUTPUT_BUDGET_EXHAUSTED` and keeps normalized usage; a partial visible answer returns successfully with `OUTPUT_TRUNCATED`. Errors distinguish connection, idle and absolute timeouts, plus `STREAM_INTERRUPTED` after provider acceptance. Messages explain that processing or billing may already have occurred. Clients must not retry such outcomes automatically.

If a stream fails after reporting usage, the error result preserves those normalized partial usage values. Unreported token fields remain null and cost remains unknown; the gateway does not estimate missing final usage or cost.

## Privacy, image handling and normalized output

Every OpenRouter request injects its registry-selected `provider.only` allowlist, `provider.data_collection="deny"`, `allow_fallbacks=false`, and `require_parameters=true`. Enforcement is silent and centralized; callers cannot override provider fields. The optional `zdr` registry profile additionally injects `provider.zdr=true`. A named request for Kimi, Qwen or DeepSeek never changes those conditions. Privacy/availability errors terminate the request. Strict model mismatch checking also rejects unexpected models (Anthropic dated snapshots of the configured family are accepted).

Direct provider retention is governed by your provider account terms; `direct` does not claim ZDR. xAI requests use `store:false`. Claude gets no execution or repository tools. X content is treated as reports, not authoritative specifications. Native search is confirmed only by an output item with `status: "completed"` or successful terminal usage metadata; a generic item-done event or generated text alone is not reported as a search.

For local image review:

```powershell
npm run upload -- 'C:\path\to\selected-screenshot.png'
```

This authenticates to `/assets`, returns an opaque `asset_id`, and stores the decoded image in memory for up to 15 minutes of usability. Expired bytes are pruned on subsequent store access or service exit. Stop the service to release all assets immediately. It does not call a model. Pass the returned ID to the tool. At most 3 images, 5 MiB each, 12 MiB combined, 20 million pixels each; single-frame PNG/JPEG/WebP only. Metadata is removed and EXIF orientation applied; no intentional crop, resize or color redesign. All selected images must validate before inference. The response records sent IDs, dimensions and SHA-256; this is transfer evidence, not a claim about model comprehension. Static frames cannot verify continuous motion.

For Chat file inputs, `_meta["openai/fileParams"]` advertises top-level `image_files`. Each item declares all four supported properties and requires only `download_url` and `file_id`. OpenAI file IDs are never treated as Anthropic file IDs. Download origins default to **none** in `.local/settings.json`. After an authorized real attachment flow identifies the origin, the owner may add its exact HTTPS origin. Downloads reject userinfo, private/reserved IPs, invalid MIME/decoding and all redirects. DNS is validated at socket connection time, avoiding a second unvalidated resolution. No raw paths, arbitrary network URLs or signed URLs are logged.

Results contain request ID, logical agent, actual backend/model, text response, structured source metadata, normalized usage, safe diagnostics, applied policy (including the answer target, provider generation ceiling, effort and timeout profile), image evidence, warnings and typed error. Safe Anthropic diagnostics include returned model, stop reason, content-block type counts, visible-text block/character counts, thinking-block count/presence, input/output/reasoning tokens and cache usage. xAI diagnostics include final status, incomplete reason/code, text/reasoning usage, completed X Search/tool counts and elapsed time; timeout errors identify the timeout layer. Missing usage is null; missing individual metrics are null, not zero. Cost is `provider_reported` or `unknown`; the gateway does not fabricate estimates. Provider payloads, internal chain-of-thought and raw error bodies are not exposed. Thinking deltas are discarded and are never returned or logged. Logs allow only request ID, alias/backend/model, mode, timing, normalized usage, safe diagnostics and result class. Prompt, response body, key, images and signed URLs are not logged by default. Host, tunnel and provider logging policies are separate.

## Development checks and paid smoke plan

```powershell
npm test
python scripts/validate_package.py
npm run check-models
```

Tests use in-process provider mocks and real loopback MCP protocol connections only. `check-models` separately reads the public OpenRouter catalog without a key or inference; it is not run during generation and does not claim privacy endpoint availability.

After explicit paid-use approval, configure keys, enable the paid gate and start the server. Run each test **separately**, exactly once, without an automatic retry:

```powershell
npm run smoke -- claude-text --allow-paid
npm run smoke -- claude-opus-text --allow-paid
npm run upload -- 'C:\path\to\synthetic-fixture.png'
npm run smoke -- claude-image RETURNED_ASSET_ID --allow-paid
npm run smoke -- grok-x --allow-paid
npm run smoke -- openrouter --allow-paid
```

Before running, review the registry models and current provider prices. The script prints the test, selected model, output preference and call count; `--allow-paid` is an additional explicit gate, not a price estimate. Use a harmless image with content not stated in its filename or prompt; manually compare the answer with the image. Each test is an independent paid request. `claude-opus-text` explicitly selects the premium profile and is an optional, separate call. No test automatically escalates to Opus, performs deep search or retries. Successful local HTTP and mocks do not prove provider access or product integration.

## Sources and scope decisions

The user's current request supersedes the attached `01_REQUIREMENTS.md` wherever they conflict: new independent plugin, a single shared tool, and OpenRouter agents are included. The attachment's three-tool/Claude-only architecture, modifications inside Portable Agent Skills, extra stage schemas and daily quota ledger are not adopted. Compatible ideas such as authenticated HTTP, file-parameter handling and explicit image failures are retained.

Official references checked on 2026-09-29 and 2026-09-30:

- [OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins) and [file inputs](https://developers.openai.com/plugins/reference).
- [Agent Plugins MCP format and client-managed authentication](https://agent-plugins.org/plugin-authors/mcp-servers).
- [Codex MCP client configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
- [Anthropic current model IDs](https://docs.anthropic.com/en/docs/about-claude/model-deprecations) and [vision](https://platform.claude.com/docs/en/build-with-claude/vision).
- [Anthropic adaptive thinking](https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking), [effort](https://platform.claude.com/docs/en/build-with-claude/effort) and [Messages streaming](https://platform.claude.com/docs/en/build-with-claude/streaming).
- [xAI Responses streaming](https://docs.x.ai/developers/tools/streaming-and-sync) and [X Search usage/citations](https://docs.x.ai/developers/tools/x-search).
- [xAI reasoning effort](https://docs.x.ai/developers/model-capabilities/text/reasoning), [X Search](https://docs.x.ai/developers/tools/x-search), [citations](https://docs.x.ai/developers/tools/citations), [usage details](https://docs.x.ai/developers/tools/tool-usage-details).
- [OpenRouter provider privacy routing](https://openrouter.ai/docs/guides/routing/provider-selection) and [public model catalog](https://openrouter.ai/api/v1/models).
