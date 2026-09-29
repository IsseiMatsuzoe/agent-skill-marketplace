from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .core import KeyState, ProviderSnapshot


@dataclass(frozen=True)
class HttpResult:
    status: int
    payload: dict | list | None
    error: str | None = None


def _get_json(url: str, headers: dict[str, str], timeout: float = 8.0) -> HttpResult:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return HttpResult(response.status, json.loads(body) if body else None)
    except HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
            payload = json.loads(body) if body else None
        except Exception:
            payload = None
        return HttpResult(exc.code, payload, f"HTTP {exc.code}")
    except (URLError, TimeoutError, OSError) as exc:
        return HttpResult(0, None, str(exc))


def _fallback_until(provider_cfg: dict, native_until: str | None = None) -> str | None:
    return native_until or provider_cfg.get("key_valid_until") or None


def _manual_balance(provider_cfg: dict) -> float | None:
    value = provider_cfg.get("manual_remaining_usd")
    if value in (None, ""):
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def fetch_openrouter(provider_cfg: dict, secrets: dict[str, str]) -> ProviderSnapshot:
    api_key = secrets.get("OPENROUTER_API_KEY", "")
    management_key = secrets.get("OPENROUTER_MANAGEMENT_KEY", "")
    remaining: float | None = None
    balance_source = "unavailable"
    detail: str | None = None

    if management_key:
        credits = _get_json(
            "https://openrouter.ai/api/v1/credits",
            {"Authorization": f"Bearer {management_key}"},
        )
        if credits.status == 200 and isinstance(credits.payload, dict):
            data = credits.payload.get("data", {})
            try:
                remaining = max(0.0, float(data["total_credits"]) - float(data["total_usage"]))
                balance_source = "auto"
            except (KeyError, TypeError, ValueError):
                detail = "Credits response missing totals"
        else:
            detail = credits.error or "Credits unavailable"
    else:
        remaining = _manual_balance(provider_cfg)
        if remaining is not None:
            balance_source = "manual"
        else:
            detail = "Management key not configured"

    state = KeyState.MISSING
    native_until = None
    if api_key:
        key_info = _get_json(
            "https://openrouter.ai/api/v1/key",
            {"Authorization": f"Bearer {api_key}"},
        )
        if key_info.status == 200 and isinstance(key_info.payload, dict):
            state = KeyState.ACTIVE
            data = key_info.payload.get("data", {})
            native_until = data.get("expires_at") if isinstance(data, dict) else None
        elif key_info.status in (401, 403):
            state = KeyState.INVALID
        else:
            state = KeyState.UNKNOWN

    return ProviderSnapshot(
        provider_id="openrouter",
        display_name=provider_cfg.get("display_name", "OpenRouter"),
        remaining_usd=remaining,
        reference_budget_usd=float(provider_cfg.get("reference_budget_usd", 10.0)),
        key_state=state,
        key_valid_until=_fallback_until(provider_cfg, native_until),
        balance_source=balance_source,
        detail=detail,
    )


def fetch_xai(provider_cfg: dict, secrets: dict[str, str]) -> ProviderSnapshot:
    api_key = secrets.get("XAI_API_KEY", "")
    management_key = secrets.get("XAI_MANAGEMENT_API_KEY", "")
    team_id = secrets.get("XAI_TEAM_ID", "")
    remaining: float | None = None
    balance_source = "unavailable"
    detail: str | None = None

    if management_key and team_id:
        balance = _get_json(
            f"https://management-api.x.ai/v1/billing/teams/{quote(team_id)}/prepaid/balance",
            {"Authorization": f"Bearer {management_key}"},
        )
        if balance.status == 200 and isinstance(balance.payload, dict):
            try:
                # xAI's documented examples represent prepaid credit as a negative accounting value.
                cents = float(balance.payload["total"]["val"])
                remaining = abs(cents) / 100.0
                balance_source = "auto"
            except (KeyError, TypeError, ValueError):
                detail = "Balance response missing total.val"
        else:
            detail = balance.error or "Prepaid balance unavailable"
    else:
        remaining = _manual_balance(provider_cfg)
        if remaining is not None:
            balance_source = "manual"
        else:
            detail = "Management key/team ID not configured"

    state = KeyState.MISSING
    if api_key:
        models = _get_json(
            "https://api.x.ai/v1/models",
            {"Authorization": f"Bearer {api_key}"},
        )
        if models.status == 200:
            state = KeyState.ACTIVE
        elif models.status in (401, 403):
            state = KeyState.INVALID
        else:
            state = KeyState.UNKNOWN

    return ProviderSnapshot(
        provider_id="xai",
        display_name=provider_cfg.get("display_name", "Grok"),
        remaining_usd=remaining,
        reference_budget_usd=float(provider_cfg.get("reference_budget_usd", 10.0)),
        key_state=state,
        key_valid_until=_fallback_until(provider_cfg),
        balance_source=balance_source,
        detail=detail,
    )


def fetch_anthropic(provider_cfg: dict, secrets: dict[str, str]) -> ProviderSnapshot:
    api_key = secrets.get("ANTHROPIC_API_KEY", "")
    # Anthropic exposes usage/cost reporting for organizations but no documented individual
    # prepaid-credit balance endpoint. MVP therefore uses an explicit manual fallback.
    remaining = _manual_balance(provider_cfg)
    balance_source = "manual" if remaining is not None else "unavailable"
    detail = None if remaining is not None else "No official individual credit-balance API"

    state = KeyState.MISSING
    if api_key:
        models = _get_json(
            "https://api.anthropic.com/v1/models?limit=1",
            {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        )
        if models.status == 200:
            state = KeyState.ACTIVE
        elif models.status in (401, 403):
            state = KeyState.INVALID
        else:
            state = KeyState.UNKNOWN

    return ProviderSnapshot(
        provider_id="anthropic",
        display_name=provider_cfg.get("display_name", "Claude"),
        remaining_usd=remaining,
        reference_budget_usd=float(provider_cfg.get("reference_budget_usd", 10.0)),
        key_state=state,
        key_valid_until=_fallback_until(provider_cfg),
        balance_source=balance_source,
        detail=detail,
    )


def fetch_all(providers_cfg: dict[str, dict], secrets: dict[str, str]) -> list[ProviderSnapshot]:
    fetchers = {
        "anthropic": fetch_anthropic,
        "xai": fetch_xai,
        "openrouter": fetch_openrouter,
    }
    snapshots: list[ProviderSnapshot] = []
    for provider_id in ("anthropic", "xai", "openrouter"):
        cfg = providers_cfg.get(provider_id, {})
        snapshots.append(fetchers[provider_id](cfg, secrets))
    return snapshots
