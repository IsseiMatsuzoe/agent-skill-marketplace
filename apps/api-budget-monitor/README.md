# API Budget Monitor

A small Windows system-tray companion for the **External Agents** project. It is deliberately **not** part of the ChatGPT plugin package: `plugins/external-agents/` stays thin, while this app observes provider budget state and manages the local backend and Secure MCP Tunnel processes.

## Budget behavior

Each provider card answers one question: **how much usable credit remains relative to my own monthly reference budget?**

- Set a `reference_budget_usd` per provider. `$10` means that amount is displayed as `100%`.
- `$4` remaining against a `$10` reference displays `40%`.
- Balances above the reference are valid: `$15 / $10` displays `150%`; the bar stays full and an overflow badge shows `+50%`.
- Missing/unsupported balance data displays `Unavailable`, never `$0`.
- Under the gauge the app shows `Key active`, `Key invalid`, `Key not configured`, or `Key status unknown`, plus a configured/native expiry date when available.
- No history, forecasting, charts, or spend analytics.

## Provider data sources

### OpenRouter

- Balance: `GET https://openrouter.ai/api/v1/credits` with `OPENROUTER_MANAGEMENT_KEY`. The app calculates `total_credits - total_usage`.
- Key status / native expiry: `GET https://openrouter.ai/api/v1/key` with `OPENROUTER_API_KEY`.

### xAI / Grok

- Balance: `GET https://management-api.x.ai/v1/billing/teams/{team_id}/prepaid/balance` with `XAI_MANAGEMENT_API_KEY` and `XAI_TEAM_ID`.
- Key status: `GET https://api.x.ai/v1/models` with `XAI_API_KEY`.
- Optional native disabled/expiry state: set `XAI_API_KEY_ID`; the app reads the matching key from the Management API.
- xAI's documented prepaid examples represent available credit as a negative accounting value; the app converts only that negative credit balance into positive USD remaining.

### Anthropic / Claude

Anthropic documents organization Usage/Cost APIs, but no individual-account prepaid-credit balance endpoint. The MVP therefore accepts `manual_remaining_usd` for Claude while still validating `ANTHROPIC_API_KEY` through `GET https://api.anthropic.com/v1/models?limit=1`.

This distinction is intentional: the UI does not fabricate a live Claude balance.

## Install on Windows

From the repository root:

```powershell
Set-Location apps/api-budget-monitor
.\scripts\install.ps1 -EnableStartup
```

Omit `-EnableStartup` if you do not want the monitor to start with Windows. The script creates a local `.venv`, installs PySide6, and writes `start-api-budget.cmd`.

You can also run it manually:

```powershell
.\start-api-budget.cmd
```

On first start, the app creates local files under `%LOCALAPPDATA%\ApiBudgetMonitor`:

- `settings.json` — reference budgets, optional manual Claude balance, rotation/expiry metadata.
- `secrets.env` — API and management credentials. **Never commit this file.**

The tray icon opens the compact runtime and budget popup. Right-click it to refresh, open Settings, or open the local config folder.

## External Agents runtime

After the one-time setup below, Windows login can start the monitor, backend, and tunnel through the existing API Budget startup shortcut:

1. Run `install.ps1 -EnableStartup` from this folder.
2. In **Settings**, enable **Start External Agents with API Budget**. The service folder is discovered from the repository layout by default; set an override only if the checkout moves.
3. Select **Set up tunnel auth** in the popup and enter the Secure MCP Tunnel runtime key. It is saved to the current Windows user's Credential Manager. It is never written to `settings.json`, a repository file, a process argument, or a log.

When enabled, the monitor checks the authenticated backend `/health` endpoint, starts the backend if needed, waits up to 45 seconds for readiness, then starts the configured `tunnel-client` profile. A running but unverified tunnel is shown as an error; process existence alone never means **Connected**. Missing tunnel credentials leave the backend available and show **Needs authentication/configuration**. The runtime card also shows the backend's read-only paid-call gate state.

Profile discovery follows the installed client's behavior: `TUNNEL_CLIENT_PROFILE_DIR`, then `XDG_CONFIG_HOME/tunnel-client`, then `HOME/.config/tunnel-client` when `HOME` is set. On Windows without those overrides, it uses `%APPDATA%\tunnel-client\external-agents.yaml`. These rules were checked against Windows tunnel-client 0.0.15; its help text only describes the Unix default. The monitor passes the resolved file using `--profile-file`, avoiding a named-profile `statat ... too many levels of symbolic links` failure observed on this Windows machine. It does not copy or create another profile.

If startup stops at **Needs authentication/configuration** without a `tunnel.log`, verify backend readiness first, then the client executable, resolved profile file, Credential Manager target `ApiBudgetMonitor/ExternalAgentsTunnel`, and the profile's loopback health address. The tunnel worker is created only after those checks pass. Runtime auto-start is disabled by default; use **Start runtime** or enable the startup setting. A running monitor must be restarted after updating its Python source.

Start and Restart run asynchronously. Restart stops only detached worker processes whose PID, executable, and creation time match the monitor's owner record. Those workers own their child process groups, so the runtime continues if the tray UI exits. Logs are kept under `%LOCALAPPDATA%\ApiBudgetMonitor\runtime`, with a 1 MB file and two rotated backups per component. **Open External Agents folder** opens the service's `.local` configuration directory when it exists.

The tunnel worker passes an empty `--log.file` to stream client output into its bounded log. With the tested Windows client, the literal value `stdout` creates a file named `stdout` in the service directory instead.

For manual recovery, start the backend from `services/external-agents` with `npm start`. For the default Windows profile without directory overrides, start the tunnel in a separate PowerShell window with the secure local prompt below; the key is not passed as a command-line argument. With a directory override, use the resolved profile file described above:

```powershell
$tunnelSecret = Read-Host 'Tunnel runtime key (local input only)' -AsSecureString
$env:CONTROL_PLANE_API_KEY = [System.Net.NetworkCredential]::new('', $tunnelSecret).Password
$tunnelProfileFile = Join-Path $env:APPDATA 'tunnel-client\external-agents.yaml'
& .local/tunnel-client/tunnel-client.exe doctor --profile-file $tunnelProfileFile --explain
& .local/tunnel-client/tunnel-client.exe run --profile-file $tunnelProfileFile
```

The monitor does not create a second Windows startup entry. Windows startup remains controlled by the existing `install.ps1 -EnableStartup` shortcut.

## Local configuration

Example `settings.json`:

```json
{
  "refresh_minutes": 10,
  "providers": {
    "anthropic": {
      "display_name": "Claude",
      "reference_budget_usd": 10.0,
      "manual_remaining_usd": 4.0,
      "key_valid_until": "2026-10-29T00:00:00+09:00"
    },
    "xai": {
      "display_name": "Grok",
      "reference_budget_usd": 10.0,
      "manual_remaining_usd": null,
      "key_valid_until": "2026-10-29T00:00:00+09:00"
    },
    "openrouter": {
      "display_name": "OpenRouter",
      "reference_budget_usd": 10.0,
      "manual_remaining_usd": null,
      "key_valid_until": null
    }
  }
}
```

`secrets.env`:

```text
ANTHROPIC_API_KEY=
OPENROUTER_API_KEY=
OPENROUTER_MANAGEMENT_KEY=
XAI_API_KEY=
XAI_MANAGEMENT_API_KEY=
XAI_TEAM_ID=
XAI_API_KEY_ID=
```

Management credentials remain local to this app and are not sent to the External Agents gateway or packaged in the ChatGPT plugin.

## Tests

The unit tests do not call paid/provider APIs or model inference:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q app.py api_budget_monitor
```

Provider references:

- <https://openrouter.ai/docs/api/api-reference/credits/get-credits>
- <https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key>
- <https://docs.x.ai/developers/rest-api-reference/management/billing>
- <https://docs.x.ai/developers/rest-api-reference/management/auth>
- <https://platform.claude.com/docs/en/manage-claude/usage-cost-api>
