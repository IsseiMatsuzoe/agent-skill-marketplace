# API Budget Monitor

A small Windows system-tray companion for the **External Agents** project. It is deliberately **not** part of the ChatGPT plugin package: `plugins/external-agents/` stays thin, while this app only observes provider billing/key state on the local PC.

## MVP behavior

Each provider card answers one question: **how much usable credit remains relative to my own monthly reference budget?**

- Set a `reference_budget_usd` per provider. `$10` means that amount is displayed as `100%`.
- `$4` remaining against a `$10` reference displays `40%`.
- Balances above the reference are valid: `$15 / $10` displays `150%`; the bar stays full and an overflow badge shows `+50%`.
- Missing/unsupported balance data displays `Unavailable`, never `$0`.
- Under the gauge the app shows `Key active`, `Key invalid`, `Key not configured`, or `Key status unknown`, plus a configured/native expiry date when available.
- No history, forecasting, charts, or spend analytics in the MVP.

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

The tray icon opens the compact budget popup. Right-click it to refresh, open Settings, or open the local config folder.

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

The unit tests do not call paid/provider APIs:

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
