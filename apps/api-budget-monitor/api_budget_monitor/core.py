from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class KeyState(str, Enum):
    ACTIVE = "active"
    INVALID = "invalid"
    MISSING = "missing"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProviderSnapshot:
    provider_id: str
    display_name: str
    remaining_usd: float | None
    reference_budget_usd: float
    key_state: KeyState = KeyState.UNKNOWN
    key_valid_until: str | None = None
    balance_source: str = "unavailable"
    detail: str | None = None

    @property
    def percent(self) -> float | None:
        if self.remaining_usd is None or self.reference_budget_usd <= 0:
            return None
        return max(0.0, self.remaining_usd / self.reference_budget_usd * 100.0)

    @property
    def bar_percent(self) -> int:
        value = self.percent
        if value is None:
            return 0
        return max(0, min(100, round(value)))

    @property
    def overflow_percent(self) -> float:
        value = self.percent
        if value is None:
            return 0.0
        return max(0.0, value - 100.0)


def format_money(value: float | None) -> str:
    if value is None:
        return "Unavailable"
    if value >= 100:
        return f"${value:,.0f}"
    return f"${value:,.2f}"


def format_percent(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 1000:
        return f"{value:,.0f}%"
    if abs(value - round(value)) < 0.05:
        return f"{value:.0f}%"
    return f"{value:.1f}%"


def compact_until(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local = parsed.astimezone()
    return f"{local.strftime('%b')} {local.day}"
