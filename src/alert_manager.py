from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
import requests
from rich.console import Console

from .config import IndigoConfig

logger = logging.getLogger(__name__)
console = Console()


class AlertManager:
    def __init__(self, config: IndigoConfig) -> None:
        self.config = config

    def _format_message(self, title: str, payload: dict[str, Any]) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        lines = [f"🚨 <b>{title}</b>", f"<i>{ts}</i>"]
        for key, value in payload.items():
            lines.append(f"<b>{key}</b>: {value}")
        return "\n".join(lines)

    def send(self, title: str, payload: dict[str, Any]) -> None:
        console.print(f"[bold cyan]ALERT[/bold cyan] {title} {payload}")
        self._send_telegram(title, payload)
        self._send_webhook(title, payload)

    def _send_telegram(self, title: str, payload: dict[str, Any]) -> None:
        if not self.config.telegram_enabled:
            return
        if not self.config.telegram_bot_token or not self.config.telegram_chat_id:
            return

        url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
        msg = self._format_message(title=title, payload=payload)
        body = {
            "chat_id": self.config.telegram_chat_id,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(url, json=body, timeout=20)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram alert failed: %s", exc)

    def _send_webhook(self, title: str, payload: dict[str, Any]) -> None:
        if not self.config.hermes_webhook_url:
            return
        event = {
            "source": "indigo-poly-market",
            "event": title,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with httpx.Client(timeout=20) as client:
                client.post(str(self.config.hermes_webhook_url), json=event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Webhook alert failed: %s", exc)
