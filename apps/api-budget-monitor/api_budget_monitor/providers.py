from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from math import isfinite
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
    return _request_json(request, timeout)


def _post_json(url: str, headers: dict[str, str], payload: dict, timeout: float = 8.0) -> HttpResult:
    request = Request(url, headers={**headers, "Content-Type": "application/json"},
                      data=json.dumps(payload).encode("utf-8"), method="POST")
    return _request_json(request, timeout)


def _request_json(request: Request, timeout: float) -> HttpResult:
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
    except (ValueError, UnicodeError):
        return HttpResult(0, None, "Invalid JSON response")


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


def _is_expired(value: str | None) -> bool:
    if not value:
        return False
    text = value.strip().replace("Z", "+00:00")
    if len(text) == 10:
        text += "T23:59:59+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed <= datetime.now(timezone.utc)


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

    if remaining is None:
        manual = _manual_balance(provider_cfg)
        if manual is not None:
            remaining = manual
            balance_source = "manual"
        elif not management_key:
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


def _billing_number(value: object, *, cents: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("Invalid billing amount")
    number = Decimal(str(value))
    if not number.is_finite() or (cents and number != number.to_integral_value()):
        raise ValueError("Invalid billing amount")
    return number


def _xai_credit_estimate(base: str, headers: dict[str, str]) -> tuple[float | None, str]:
    # The public schema does not promise a live usable-credit total. Only derive
    # an estimate for a reconciled, successful purchase-only ledger; never deduct
    # historical usage again from a ledger containing settled SPEND entries.
    balance = _get_json(base + "/prepaid/balance", headers)
    if balance.status != 200:
        return None, f"Prepaid balance unavailable (HTTP {balance.status})"
    now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        payload = balance.payload
        if not isinstance(payload, dict) or set(payload) - {"total", "changes"}:
            raise ValueError
        total = _billing_number(payload["total"]["val"], cents=True)
        changes = payload["changes"]
        if not isinstance(changes, list) or not changes:
            raise ValueError
        purchases = Decimal(0)
        times = []
        documented_fields = {
            "teamId", "changeOrigin", "topupStatus", "amount", "invoiceId", "invoiceNumber",
            "createTime", "createTs", "spendBpKeyYear", "spendBpKeyMonth", "paymentProcessor",
        }
        for change in changes:
            if not isinstance(change, dict) or set(change) - documented_fields:
                raise ValueError
            if change["changeOrigin"] not in ("PURCHASE", "AUTO_PURCHASE") or change["topupStatus"] != "SUCCEEDED":
                raise ValueError
            amount = _billing_number(change["amount"]["val"], cents=True)
            when = datetime.fromisoformat(change["createTime"].replace("Z", "+00:00"))
            if amount >= 0 or when.tzinfo is None or when >= now:
                raise ValueError
            purchases += amount
            times.append(when.astimezone(timezone.utc))
        if purchases != total:
            raise ValueError
        start = min(times).replace(microsecond=0)
        # A local conservative support ceiling, not an assertion of xAI's expiry
        # policy: the public billing schema cannot establish old-credit validity.
        if (now - start).days >= 365:
            return None, "Old credit validity/expiry cannot be established"
    except (KeyError, TypeError, ValueError, AttributeError, InvalidOperation):
        return None, "Unsupported or incomplete prepaid ledger (adjustments, refunds, expiry or settled spend)"

    preview = _get_json(base + "/postpaid/invoice/preview", headers)
    if preview.status != 200:
        return None, f"Billing preview unavailable (HTTP {preview.status})"
    try:
        data = preview.payload
        invoice = data["coreInvoice"]
        cycle = data["billingCycle"]
        if cycle != {"year": now.year, "month": now.month}:
            raise ValueError
        # Do not mix a gross usage total with postpaid allowance, promotional
        # credits or invoice corrections whose credit allocation is unspecified.
        zeros = [data["effectiveSpendingLimit"], data["defaultCredits"],
                 invoice["autoCreditsIssued"], invoice["defaultCreditsIssued"],
                 invoice["totalWithCorr"]["val"]]
        if any(_billing_number(value, cents=True) != 0 for value in zeros):
            raise ValueError
        if _billing_number(invoice["prepaidCredits"]["val"], cents=True) != total:
            raise ValueError
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None, "Postpaid, promotional, adjusted or inconsistent billing cannot be reconstructed"

    query = {"analyticsRequest": {
        "timeRange": {"startTime": start.strftime("%Y-%m-%d %H:%M:%S"),
                      "endTime": now.strftime("%Y-%m-%d %H:%M:%S"), "timezone": "Etc/GMT"},
        "timeUnit": "TIME_UNIT_NONE",
        "values": [{"name": "usd", "aggregation": "AGGREGATION_SUM"}],
        "groupBy": [], "filters": [],
    }}
    usage = _post_json(base + "/usage", headers, query)
    if usage.status != 200:
        return None, f"Usage unavailable (HTTP {usage.status})"
    try:
        data = usage.payload
        if data["limitReached"] is not False or len(data["timeSeries"]) != 1:
            raise ValueError
        series = data["timeSeries"][0]
        if series.get("group") != [] or len(series["dataPoints"]) != 1:
            raise ValueError
        values = series["dataPoints"][0]["values"]
        if len(values) != 1:
            raise ValueError
        spent = _billing_number(values[0])
        if spent < 0:
            raise ValueError
        remaining = float(max(Decimal(0), -total / 100 - spent))
        if not isfinite(remaining):
            raise ValueError
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None, "Usage response missing, malformed or incomplete"
    return remaining, (
        f"Estimated: successful purchases minus reported USD usage, {start.isoformat()} to {now.isoformat()}. "
        "Reporting delay, historical postpaid/promotional allocation and undisclosed expiry may differ from Console."
    )


def fetch_xai(provider_cfg: dict, secrets: dict[str, str]) -> ProviderSnapshot:
    api_key = secrets.get("XAI_API_KEY", "")
    management_key = secrets.get("XAI_MANAGEMENT_API_KEY", "")
    team_id = secrets.get("XAI_TEAM_ID", "")
    api_key_id = secrets.get("XAI_API_KEY_ID", "")
    remaining: float | None = None
    balance_source = "unavailable"
    detail: str | None = None

    if management_key and team_id:
        remaining, detail = _xai_credit_estimate(
            f"https://management-api.x.ai/v1/billing/teams/{quote(team_id, safe='')}",
            {"Authorization": f"Bearer {management_key}"},
        )
        if remaining is not None:
            balance_source = "estimated"

    if remaining is None:
        manual = _manual_balance(provider_cfg)
        if manual is not None:
            remaining = manual
            balance_source = "manual"
        elif not (management_key and team_id):
            detail = "Management key/team ID not configured"

    state = KeyState.MISSING
    native_until = None
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

    # When the owner supplies the API-key ID, management metadata gives us the
    # authoritative disabled/expiry state without sending any inference request.
    if management_key and team_id and api_key_id:
        key_list = _get_json(
            f"https://management-api.x.ai/auth/teams/{quote(team_id)}/api-keys?pageSize=100&activeOnly=false",
            {"Authorization": f"Bearer {management_key}"},
        )
        if key_list.status == 200 and isinstance(key_list.payload, dict):
            for item in key_list.payload.get("apiKeys", []):
                if str(item.get("apiKeyId") or "") != api_key_id:
                    continue
                native_until = item.get("expireTime") or None
                disabled = item.get("disabled", False)
                if isinstance(disabled, str):
                    disabled = disabled.lower() == "true"
                state = KeyState.INVALID if disabled or _is_expired(native_until) else KeyState.ACTIVE
                break

    return ProviderSnapshot(
        provider_id="xai",
        display_name=provider_cfg.get("display_name", "Grok"),
        remaining_usd=remaining,
        reference_budget_usd=float(provider_cfg.get("reference_budget_usd", 10.0)),
        key_state=state,
        key_valid_until=_fallback_until(provider_cfg, native_until),
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
        try:
            snapshots.append(fetchers[provider_id](cfg, secrets))
        except Exception as exc:
            snapshots.append(
                ProviderSnapshot(
                    provider_id=provider_id,
                    display_name=cfg.get("display_name", provider_id),
                    remaining_usd=_manual_balance(cfg),
                    reference_budget_usd=float(cfg.get("reference_budget_usd", 10.0)),
                    key_state=KeyState.UNKNOWN,
                    key_valid_until=_fallback_until(cfg),
                    balance_source="manual" if _manual_balance(cfg) is not None else "unavailable",
                    detail=f"Unexpected {type(exc).__name__}",
                )
            )
    return snapshots
