from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_PROVIDERS = {
    "anthropic": {
        "display_name": "Claude",
        "reference_budget_usd": 10.0,
        "manual_remaining_usd": None,
        "key_valid_until": None,
    },
    "xai": {
        "display_name": "Grok",
        "reference_budget_usd": 10.0,
        "manual_remaining_usd": None,
        "key_valid_until": None,
    },
    "openrouter": {
        "display_name": "OpenRouter",
        "reference_budget_usd": 10.0,
        "manual_remaining_usd": None,
        "key_valid_until": None,
    },
}


@dataclass
class AppConfig:
    refresh_minutes: int = 10
    providers: dict[str, dict] = field(default_factory=lambda: json.loads(json.dumps(DEFAULT_PROVIDERS)))


def default_config_dir() -> Path:
    if os.name == "nt" and os.getenv("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "ApiBudgetMonitor"
    return Path.home() / ".config" / "api-budget-monitor"


def ensure_config(config_dir: Path) -> tuple[AppConfig, dict[str, str]]:
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "settings.json"
    secrets_path = config_dir / "secrets.env"

    if not config_path.exists():
        save_config(config_path, AppConfig())
    if not secrets_path.exists():
        secrets_path.write_text(
            "# API Budget Monitor secrets. Never commit this file.\n"
            "ANTHROPIC_API_KEY=\n"
            "OPENROUTER_API_KEY=\n"
            "OPENROUTER_MANAGEMENT_KEY=\n"
            "XAI_API_KEY=\n"
            "XAI_MANAGEMENT_API_KEY=\n"
            "XAI_TEAM_ID=\n",
            encoding="utf-8",
        )

    return load_config(config_path), load_env_file(secrets_path)


def load_config(path: Path) -> AppConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    providers = json.loads(json.dumps(DEFAULT_PROVIDERS))
    for provider_id, values in raw.get("providers", {}).items():
        providers.setdefault(provider_id, {}).update(values)
    return AppConfig(refresh_minutes=int(raw.get("refresh_minutes", 10)), providers=providers)


def save_config(path: Path, config: AppConfig) -> None:
    path.write_text(
        json.dumps(
            {"refresh_minutes": config.refresh_minutes, "providers": config.providers},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    for key in (
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENROUTER_MANAGEMENT_KEY",
        "XAI_API_KEY",
        "XAI_MANAGEMENT_API_KEY",
        "XAI_TEAM_ID",
    ):
        if os.getenv(key):
            values[key] = os.environ[key]
    return values
