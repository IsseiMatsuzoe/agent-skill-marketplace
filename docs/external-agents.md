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

The repository marketplace lists **Portable Agent Skills** and **External Agents** independently. Refresh `personal` only after the reviewed branch is merged to its configured ref. Existing installed copies are snapshots; a push alone does not update them.

The root `mcp.json` declares a local Streamable HTTP endpoint; `.mcp.json` and `.codex-plugin/plugin.json` support older clients. Root `plugin.json` is canonical and its `extensions.com.openai` presentation matches the compatibility overlay. No provider key is in either manifest. The backend is separate and is not packaged into the skill ZIP.

**Authentication is client-managed.** Portable MCP 1.0 does not provide portable credential-reference fields; HTTP headers are literal data and must not contain secrets. Do not put `${API_KEY}` strings or actual bearer tokens into `mcp.json`. A host that cannot supply authentication to the bundled entry will see an authentication error until configured.

For a local Codex client, a documented way to use client-managed credentials is to disable the plugin's bundled connection and create exactly one authenticated connection in your user `config.toml`:

```toml
[plugins."external-agents@personal".mcp_servers.external_agents]
enabled = false

[mcp_servers.external_agents]
url = "http://127.0.0.1:47831/mcp"
bearer_token_env_var = "EXTERNAL_AGENTS_MCP_TOKEN"
tool_timeout_sec = 115
default_tools_approval_mode = "prompt"
```

Use the plugin identifier reported by your installed marketplace if it differs. Do not add this second entry while leaving the bundled entry active. The Skill still calls the same logical tool; no provider logic changes. From the service directory, load only the generated MCP token into the local client's environment without printing it:

```powershell
$localTokenLine = Get-Content -LiteralPath .local/secrets.env | Where-Object { $_ -match '^EXTERNAL_AGENTS_MCP_TOKEN=' }
$env:EXTERNAL_AGENTS_MCP_TOKEN = ($localTokenLine -split '=', 2)[1]
codex
```

This affects the launched CLI process, not an already running desktop app. For the desktop app, set that variable through your private user environment settings and fully restart the app, or use its supported client credential configuration. Do not export provider keys to the host: only the service needs them. Work on another host needs a route to this same service; its `localhost` is not this PC. Real product pickup remains a separate manual test.

For ChatGPT Web, `localhost` is not reachable. Connect the running service through an owner-configured [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) or an authenticated HTTPS deployment. A tunnel requires its own runtime credential, permissions and workspace association. **Tunnel-to-local bearer forwarding must be confirmed before connecting; never remove local authentication to make discovery work.** The current repository does not deploy a tunnel, OAuth server or public service. If the tunnel client cannot forward the local credential, connection is blocked pending a supported authenticated transport.

Register the real connection in ChatGPT developer mode and obtain the real app mapping if the surface requires one. Do not fabricate `plugin_asdk_app...` IDs. This is a user-owned setup step, not a verified integration. The exact mapping and file download origins cannot be finalized without that connection. No public publication is requested.

Build a local archive with `npm run package-plugin`. For a gateway connected separately, use `npm run package-plugin -- --skills-only`. For an already configured HTTPS gateway, use `npm run package-plugin -- --url https://YOUR-OWN-HOST/mcp`. Archives are allowlisted into ignored `dist/`; the source plugin is not rewritten. Uploading a ZIP does not provision the backend, credentials, registered app mapping or authentication.

## Registry and request contract

`services/external-agents/registry.json` contains the shipped defaults. After `setup`, edit `.local/registry.json` for owner configuration. Only backend adapters know endpoints and request formats. Registry validation rejects invalid privacy/backend combinations, duplicate aliases, unsupported capabilities and premium auto-selection. Changing a backend to a supported replacement does not require a Skill edit; a new provider API needs only an adapter plus backend validation/key mapping.

| Alias | Backend | Default model | Selection |
| --- | --- | --- | --- |
| claude | Anthropic direct | claude-sonnet-5-5 | auto_allowed |
| grok | xAI direct | grok-4.7 | auto_allowed |
| gemini | OpenRouter | google/gemini-3.1-flash-lite | auto_allowed |
| muse | OpenRouter | meta/muse-spark-1.3 | auto_allowed |
| kimi | OpenRouter | moonshotai/kimi-k2.5 | explicit_only |
| qwen | OpenRouter | qwen/qwen3.6-flash | explicit_only |
| deepseek | OpenRouter | deepseek/deepseek-v4.1-flash | explicit_only |
| experimental | OpenRouter | unset, disabled | explicit_only |

Defaults were selected on 2026-09-29. Claude uses Sonnet rather than a premium profile; Gemini uses an inexpensive Flash Lite. The regular Muse variant is configured, not a contributor variant. Catalog existence does not establish key access, privacy compatibility or model quality. There is no fallback, automatic generation retry, model escalation or multi-agent loop. A future premium profile must be configured by the owner, enabled and marked `premium: true` with `explicit_only`.

`call_external_agent` accepts:

- `agent`, `task`; optional `mode`, `context`, `depth`, `max_output_tokens`.
- `user_requested_agent`: defaults false; true only when the user explicitly names the agent. The gateway enforces this for `explicit_only`; this is a **trusted caller attestation**, not cryptographic proof of the original conversation. Host approvals remain responsible for truthful user-intent provenance.
- `attachments`: selected text files as `{name, text}`; no arbitrary filesystem reading. Binary documents are not supported.
- `image_files`: host-provided OpenAI file objects; `asset_ids`: opaque local upload references. `visual_review: true` requires real images.
- Optional `x_search` date/handle filters for `x_research` only.

Five modes are `general`, `design`, `review`, `x_research`, `rewrite`. `depth` (`brief`, `standard`, `deep`) controls requested answer detail, not provider-specific hidden reasoning budgets. Defaults are 2,048 output tokens with a 4,096 ceiling for enabled agents. Limits do not guarantee a fixed dollar cost. X Search uses at most two assistant/tool turns by default; turns do not bound posts, users or individual tool calls. Use provider dashboard limits as well. The gateway allows one concurrent inference, and each call makes one generation request. It has no daily quota ledger or deduplication across separate client calls; callers must not automatically retry timeouts or uncertain outcomes.

## Privacy, image handling and normalized output

Every OpenRouter request injects `provider.data_collection="deny"`, `allow_fallbacks=false`, and `require_parameters=true`. The optional `zdr` registry profile additionally injects `provider.zdr=true`. A named request for Kimi, Qwen or DeepSeek never changes those conditions. Privacy/availability errors terminate the request. Strict model mismatch checking also rejects unexpected models (Anthropic dated snapshots of the configured family are accepted).

Direct provider retention is governed by your provider account terms; `direct` does not claim ZDR. xAI requests use `store:false`. Claude gets no execution or repository tools. X content is treated as reports, not authoritative specifications. Native search must be confirmed by completed search output or successful usage metadata; generation alone is not reported as a search.

For local image review:

```powershell
npm run upload -- 'C:\path\to\selected-screenshot.png'
```

This authenticates to `/assets`, returns an opaque `asset_id`, and stores the decoded image in memory for up to 15 minutes of usability. Expired bytes are pruned on subsequent store access or service exit. Stop the service to release all assets immediately. It does not call a model. Pass the returned ID to the tool. At most 3 images, 5 MiB each, 12 MiB combined, 20 million pixels each; single-frame PNG/JPEG/WebP only. Metadata is removed and EXIF orientation applied; no intentional crop, resize or color redesign. All selected images must validate before inference. The response records sent IDs, dimensions and SHA-256; this is transfer evidence, not a claim about model comprehension. Static frames cannot verify continuous motion.

For Chat file inputs, `_meta["openai/fileParams"]` advertises top-level `image_files`. Each item declares all four supported properties and requires only `download_url` and `file_id`. OpenAI file IDs are never treated as Anthropic file IDs. Download origins default to **none** in `.local/settings.json`. After an authorized real attachment flow identifies the origin, the owner may add its exact HTTPS origin. Downloads reject userinfo, private/reserved IPs, invalid MIME/decoding and all redirects. DNS is validated at socket connection time, avoiding a second unvalidated resolution. No raw paths, arbitrary network URLs or signed URLs are logged.

Results contain request ID, logical agent, actual backend/model, text response, structured source metadata, normalized usage, applied policy, image evidence, warnings and typed error. Missing usage is null; missing individual metrics are null, not zero. Cost is `provider_reported` or `unknown`; the gateway does not fabricate estimates. Provider payloads, internal chain-of-thought and raw error bodies are not exposed. Logs allow only request ID, alias/backend/model, mode, timing, numeric usage/cost and result class. Prompt, response body, key, images and signed URLs are not logged by default. Host, tunnel and provider logging policies are separate.

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
npm run upload -- 'C:\path\to\synthetic-fixture.png'
npm run smoke -- claude-image RETURNED_ASSET_ID --allow-paid
npm run smoke -- grok-x --allow-paid
npm run smoke -- openrouter --allow-paid
```

Before running, review the registry models and current provider prices. The script prints the test, selected model, output ceiling and call count; `--allow-paid` is an additional explicit gate, not a price estimate. Use a harmless image with content not stated in its filename or prompt; manually compare the answer with the image. These four tests have independent results. No premium model, deep search or retry is included. Successful local HTTP and mocks do not prove provider access or product integration.

## Sources and scope decisions

The user's current request supersedes the attached `01_REQUIREMENTS.md` wherever they conflict: new independent plugin, a single shared tool, and OpenRouter agents are included. The attachment's three-tool/Claude-only architecture, modifications inside Portable Agent Skills, extra stage schemas and daily quota ledger are not adopted. Compatible ideas such as authenticated HTTP, file-parameter handling and explicit image failures are retained.

Official references checked on 2026-09-29:

- [OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins) and [file inputs](https://developers.openai.com/plugins/reference).
- [Agent Plugins MCP format and client-managed authentication](https://agent-plugins.org/plugin-authors/mcp-servers).
- [Codex MCP client configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
- [Anthropic model IDs](https://platform.claude.com/docs/en/models/overview) and [vision](https://platform.claude.com/docs/en/build-with-claude/vision).
- [xAI X Search](https://docs.x.ai/developers/tools/x-search), [citations](https://docs.x.ai/developers/tools/citations), [usage details](https://docs.x.ai/developers/tools/tool-usage-details).
- [OpenRouter provider privacy routing](https://openrouter.ai/docs/guides/routing/provider-selection) and [public model catalog](https://openrouter.ai/api/v1/models).
