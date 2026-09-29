# External Agents host integration

The local Plugin uses a stdio transport relay to the same authenticated loopback backend that ChatGPT can reach through a Secure MCP Tunnel. The relay contains no registry, provider keys or inference implementation. Both routes retain `Skill -> call_external_agent -> registry -> adapter`.

## Local Codex installation

Prerequisites: Node 22.15+ on PATH; the prepared backend and its dependencies. From `services/external-agents`:

```powershell
npm test
npm run doctor
npm run connect-host
npm start
```

`connect-host` writes only the loopback URL and independent MCP bearer token to `~/.config/external-agents/connection.json`. Do not print or share that file. Provider keys stay in the backend's ignored `.local/secrets.env`. The setup does not enable paid calls. On Windows, keep both locations in a private user profile; POSIX mode bits do not set Windows ACLs.

In another terminal, use the existing GitHub Personal marketplace. Before merge, select the feature branch explicitly; do not create a second local marketplace:

```powershell
codex plugin marketplace add https://github.com/IsseiMatsuzoe/agent-skill-marketplace.git --ref feat/external-agents --json
codex plugin marketplace upgrade personal --json
codex plugin add external-agents@personal --json
```

Codex 0.158 rejects changing an existing source's ref via `add`: first run `codex plugin marketplace remove personal --json`, then the `add` above. This removes the source registration, not the installed Portable Agent Skills. After merge, switch the same source back to `--ref main` using that remove/add sequence and refresh/reinstall. Installed copies are snapshots. Start a fresh Codex session to load the Plugin. An already running conversation does not gain tools merely because the source was updated.

The root `mcp.json` uses portable `${PLUGIN_ROOT}` expansion. Compatibility `.mcp.json` uses `cwd: "."` (resolved against the plugin root by Codex) and `scripts/relay.mjs`. Node must be available to the host. No bearer value belongs in either manifest.

Local image path: the design-review Skill calls the installed `scripts/relay.mjs --upload <selected-image>` helper, then passes the returned `asset_id` to `call_external_agent`. Upload is an authenticated byte transfer, not an inference. It expires after 15 minutes and must reach the same running backend instance.

On the tested Windows setup, shell tools inside Codex's sandbox cannot read the private connection file (`EPERM`), while the Plugin MCP process can. For the image upload helper, use the host's scoped approval for that exact command; do not copy the connection secret into the sandbox or grant broad filesystem access. `codex exec --approve-for-me` routes that command through automatic review and already selects workspace-write; it cannot be combined with `--sandbox`. The actual image test succeeded this way. Ordinary MCP text/search calls needed no additional confirmation.

## Enabling the actual host tests

Provider smoke tests are already complete; do not repeat them for confidence. For a new host qualification, change only this line in the existing backend `.local/secrets.env`:

```text
EXTERNAL_AGENTS_ENABLE_PAID=true
```

Restart the backend, then run `npm run doctor`: it must say `paid_calls: enabled`; all three keys should say `present_unverified` without displaying values. This is a session-level owner setting, not a per-call approval prompt. After qualification restore `false` and restart if paid operation should stop.

Test the installed Skills, one request per case, no retries or model substitutions:

1. `ask-claude`: request a brief architectural second opinion on a harmless example.
2. `x-research`: retrieve one known public post/thread with `x_search.kind: retrieval`; verify native-search usage and sources. Ordinary research defaults to medium; retrieval defaults to low.
3. `ask-external-agent`: explicitly request Gemini for a short response; inspect the returned `data_collection: deny` policy.
4. `design-review`: attach a harmless image in the host, upload that selected file through the installed helper, and verify the common tool returns matching `images_sent` metadata and a response describing its actual content.

Record host/version, installed plugin version, tool name, request IDs, actual model, usage and image evidence. A disabled-gate result proves the host reaches the gateway but does not verify inference. A CLI test does not automatically qualify a desktop conversation or hosted ChatGPT.

## ChatGPT / hosted Work connection

Hosted ChatGPT cannot reach this PC's localhost or run its stdio Plugin. Use [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) with the **same relay**, or an owner-operated authenticated HTTPS gateway. No tunnel, OAuth service or public endpoint is implicitly created by the Plugin ZIP.

The owner must create a tunnel in [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels), associate the target ChatGPT workspace, and have Tunnels Read + Manage for creation and Read + Use for operation. Obtain `tunnel-client` from the link in Platform or the [official release page](https://github.com/openai/tunnel-client/releases/latest). Its runtime credential is separate from Anthropic, xAI and OpenRouter keys. Enter it locally, never in chat. Do not reuse a provider key as the tunnel credential.

For this Windows checkout, the official v0.0.15 amd64 executable is already prepared at `services/external-agents/.local/tunnel-client/tunnel-client.exe`; its published SHA-256 was verified and its help interface was exercised. It is not added to PATH or packaged in the Plugin. No tunnel profile or remote tunnel has been created. For another checkout, download the current official release before the following steps.

In PowerShell, load the tunnel runtime credential without echoing it (paste only into the secure terminal prompt):

```powershell
$tunnelSecret = Read-Host 'Tunnel runtime key (local input only)' -AsSecureString
$env:CONTROL_PLANE_API_KEY = [System.Net.NetworkCredential]::new('', $tunnelSecret).Password
$tunnelId = Read-Host 'Tunnel ID'
$tunnelClient = (Resolve-Path .local/tunnel-client/tunnel-client.exe).Path
$relayPath = (Resolve-Path ../../plugins/external-agents/scripts/relay.mjs).Path
& $tunnelClient init --sample sample_mcp_stdio_local --profile external-agents --tunnel-id $tunnelId --mcp-command ('node "' + $relayPath + '"')
& $tunnelClient doctor --profile external-agents --explain
& $tunnelClient run --profile external-agents
```

Run from `services/external-agents`; keep the backend and tunnel running. The local stdio relay supplies the backend bearer credential, so no special tunnel HTTP header forwarding or authentication bypass is needed. This profile still requires qualification with the actual installed tunnel client and account; the commands follow the official documented interface.

Enable ChatGPT developer mode in Settings > Security and login if available for the account/workspace. In Plugins, create a developer-mode connection, choose **Tunnel**, select the real tunnel, and inspect the discovered `call_external_agent` schema. Follow the host's connection approval flow once. Plugin Skills do not add confirmations for ordinary research; host-enforced consent remains under host control.

After connection creation, obtain its actual registered app ID from the host's connection details/export. Build `npm run package-plugin -- --app-id ACTUAL_REGISTERED_APP_ID` to create `dist/external-agents-chatgpt.zip`. The packager writes `.app.json` and points both OpenAI manifest forms to it; local stdio and upload scripts are excluded. Import the archive using the host's private Plugin workflow. Never invent an app ID. If the host does not expose a usable registered app ID or cannot associate imported Skills with the connection, record that packaging limitation.

`npm run package-plugin -- --skills-only` prepares `dist/external-agents-skills.zip` for a surface where the gateway is connected separately. That archive alone is not a connected External Agents Plugin. The mapped archive cannot be finalized before real connection registration.

The `--url https://YOUR-HOST/mcp` package option is only for an already deployed authenticated HTTPS endpoint. It replaces the local stdio declaration; it does not deploy a backend or embed credentials.

## Chat attachment qualification

`call_external_agent` advertises top-level `image_files` through `openai/fileParams`. The backend's `.local/settings.json` deliberately starts with `file_download_origins: []`.

1. Attach a harmless image in the actual Chat conversation and invoke `design-review`/Claude.
2. Confirm the host supplies actual `file_id` and `download_url` values. A textual path, a URL invented by the model, or a locally uploaded substitute does not qualify this flow.
3. Identify only the exact HTTPS **origin** of the host-supplied signed URL, without publishing the URL or its query. Add that origin to `file_download_origins` and restart the backend. Do not broadly allow arbitrary hosts.
4. Exercise the actual Chat attachment request. Record successful tool output, its request ID and `images_sent` dimensions/hash; independently compare the answer with the image.

Until step 4 succeeds, **Chat -> MCP -> Claude image transfer is unverified**. No text-only fallback is allowed. Local mock tests, provider smoke tests and a Codex local-file upload cannot establish it.

Local Work on this PC may use the same installed stdio Plugin if that surface exposes it; hosted Work requires the remote connection above. Verify the actual surface separately instead of assuming Codex qualification applies to Work.

## This machine's exercised commands

Checkout: `C:/Users/Issei/Documents/AI Agent's Workspace/external-agents-work`. CLI: `C:/Users/Issei/AppData/Local/OpenAI/Codex/bin/faa963e871dd422c/codex.exe`, version `0.158.0-alpha.2.1`. Installed Plugin: `C:/Users/Issei/.codex/plugins/cache/personal/external-agents/0.2.0`.

The owner ran the local paid-gate change, then the test operator restarted `node src/server.js`. From the checkout root, text/search cases used the installed Skills in a fresh CLI session:

```powershell
$hostTestPrompt | codex exec --ephemeral --sandbox workspace-write --json --image services/external-agents/.local/smoke-fixture-01.png --output-last-message services/external-agents/.local/codex-host-final.txt - > services/external-agents/.local/codex-host.jsonl
```

`$hostTestPrompt` specified the four cases above, exact harmless task texts, at most one provider call per case, no retry, and no secret/config reading. The initial image upload failed locally with `EPERM`, so a second fresh CLI session ran **only** that still-unexecuted image case using `--approve-for-me` in place of `--sandbox workspace-write`. Its authorized shell command was:

```powershell
node 'C:/Users/Issei/.codex/plugins/cache/personal/external-agents/0.2.0/scripts/relay.mjs' --upload "C:/Users/Issei/Documents/AI Agent's Workspace/external-agents-work/services/external-agents/.local/smoke-fixture-01.png"
```

Both sessions called `mcp__external_agents__call_external_agent`. The image session received the fixture through `--image` and transferred its actual file through the installed helper; the outbound task did not contain its visual contents. The ignored `.local/host-results.json` preserves exact MCP arguments, normalized results and upload commands. The public verification record lists request IDs and usage. Four provider calls total, no inference retries. The backend was stopped and the test paid gate restored to `false` afterward.
