from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, HttpUrl, field_validator

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


class IndigoConfig(BaseModel):
    polymarket_private_key: str = Field(min_length=1)
    auto_top_n: int = Field(default=10, ge=1, le=100)
    bet_mode: Literal["fixed", "percentage"] = "fixed"
    bet_value: float = Field(default=25.0, gt=0)
    max_bet_usdc: float = Field(default=200.0, gt=0)
    poll_interval_minutes: int = Field(default=3, ge=1)
    dry_run: bool = True

    telegram_enabled: bool = False
    telegram_bot_token: str | None = ""
    telegram_chat_id: str | None = ""
    hermes_webhook_url: HttpUrl | None = None

    api_enabled: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    api_key: str = Field(min_length=16)

    @field_validator("telegram_bot_token", "telegram_chat_id", mode="before")
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("hermes_webhook_url", mode="before")
    @classmethod
    def normalize_webhook(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        return value


def _expand_env_refs(raw: str) -> str:
    def replace(match: re.Match[str]) -> str:
        env_key = match.group(1)
        return os.getenv(env_key, "")

    return _ENV_VAR_PATTERN.sub(replace, raw)


def load_config(config_path: str | Path = "config.yaml") -> IndigoConfig:
    load_dotenv()
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    raw = path.read_text(encoding="utf-8")
    expanded = _expand_env_refs(raw)
    data = yaml.safe_load(expanded) or {}

    cfg = IndigoConfig(**data)

    if cfg.telegram_enabled and (not cfg.telegram_bot_token or not cfg.telegram_chat_id):
        raise ValueError(
            "telegram_enabled=true requires telegram_bot_token and telegram_chat_id"
        )

    return cfg
