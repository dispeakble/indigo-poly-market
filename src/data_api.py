from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WalletPosition:
    market_slug: str
    outcome: str
    size_usdc: float


class PolymarketDataAPI:
    BASE_URL = "https://data-api.polymarket.com"

    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout

    def fetch_top_wallets(self, top_n: int) -> list[str]:
        """Fetches top wallets by PnL from leaderboard endpoint.

        Endpoint coverage can vary; graceful fallback returns empty list.
        """
        candidates = [
            f"{self.BASE_URL}/leaderboard?limit={top_n}",
            f"{self.BASE_URL}/users/leaderboard?limit={top_n}",
        ]
        for url in candidates:
            try:
                resp = requests.get(url, timeout=self.timeout)
                if resp.status_code >= 400:
                    continue
                data = resp.json()
                rows = data if isinstance(data, list) else data.get("data", [])
                wallets: list[str] = []
                for row in rows:
                    wallet = row.get("wallet") or row.get("address") or row.get("user")
                    if wallet:
                        wallets.append(wallet)
                if wallets:
                    return wallets[:top_n]
            except Exception as exc:  # noqa: BLE001
                logger.warning("Leaderboard fetch failed from %s: %s", url, exc)
        return []

    def fetch_wallet_positions(self, wallet: str) -> list[WalletPosition]:
        """Best-effort wallet positions fetch from data-api variants."""
        candidates = [
            f"{self.BASE_URL}/positions?user={wallet}",
            f"{self.BASE_URL}/users/{wallet}/positions",
            f"{self.BASE_URL}/portfolio?address={wallet}",
        ]
        for url in candidates:
            try:
                resp = requests.get(url, timeout=self.timeout)
                if resp.status_code >= 400:
                    continue
                data = resp.json()
                rows = data if isinstance(data, list) else data.get("data", [])
                positions: list[WalletPosition] = []
                for row in rows:
                    size = float(row.get("size") or row.get("size_usdc") or row.get("amount") or 0)
                    if size <= 0:
                        continue
                    slug = (
                        row.get("market_slug")
                        or row.get("slug")
                        or row.get("market", {}).get("slug")
                        or "unknown-market"
                    )
                    outcome = row.get("outcome") or row.get("side") or "Yes"
                    positions.append(WalletPosition(market_slug=slug, outcome=outcome, size_usdc=size))
                return positions
            except Exception as exc:  # noqa: BLE001
                logger.warning("Positions fetch failed for %s via %s: %s", wallet, url, exc)
        return []
