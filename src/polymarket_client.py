from __future__ import annotations

import json
import logging
from typing import Any

import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams, MarketOrderArgs, OrderType
from web3 import Web3

logger = logging.getLogger(__name__)


class PolymarketClient:
    def __init__(self, private_key: str, dry_run: bool = True, chain_id: int = 137) -> None:
        self.private_key = private_key
        self.dry_run = dry_run
        self.chain_id = chain_id
        self.client = ClobClient("https://clob.polymarket.com", key=private_key, chain_id=chain_id)
        self.address = Web3().eth.account.from_key(private_key).address

        # Level-2 auth required for balances + posting orders.
        if not self.dry_run:
            creds = self.client.create_or_derive_api_creds()
            self.client.set_api_creds(creds)

    def _lookup_token_id(self, market_slug: str, outcome: str) -> str:
        market_resp = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={"slug": market_slug},
            timeout=15,
        )
        market_resp.raise_for_status()
        rows = market_resp.json()
        if not rows:
            raise ValueError(f"Market slug not found: {market_slug}")

        market = rows[0]
        token_ids = json.loads(market.get("clobTokenIds", "[]"))
        outcomes = json.loads(market.get("outcomes", "[]"))
        if not token_ids:
            raise ValueError(f"No token ids found for market: {market_slug}")

        outcome_idx = 0
        for idx, name in enumerate(outcomes):
            if str(name).lower() == outcome.lower():
                outcome_idx = idx
                break
        return token_ids[outcome_idx]

    def get_usdc_balance(self) -> float:
        """Best-effort available collateral balance from CLOB balance endpoint."""
        if self.dry_run:
            return 1000.0
        try:
            bal = self.client.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            if isinstance(bal, dict):
                for key in ("balance", "available", "usdc"):
                    if key in bal:
                        return float(bal[key])
            return 0.0
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch USDC balance: %s", exc)
            return 0.0

    def get_market_price(self, market_slug: str, outcome: str) -> float:
        """Lookup market/outcome midpoint via gamma + clob endpoints."""
        try:
            token_id = self._lookup_token_id(market_slug, outcome)
            mid = self.client.get_midpoint(token_id)
            if isinstance(mid, dict):
                return float(mid.get("mid", 0.5))
            return float(mid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Price lookup failed for %s/%s: %s", market_slug, outcome, exc)
            return 0.5

    def _post_market_order(self, token_id: str, side: str, amount_usdc: float) -> dict[str, Any]:
        order = self.client.create_market_order(
            MarketOrderArgs(
                token_id=token_id,
                amount=float(amount_usdc),
                side=side,
                order_type=OrderType.FOK,
            )
        )
        return self.client.post_order(order, OrderType.FOK)

    def place_buy(self, market_slug: str, outcome: str, amount_usdc: float) -> dict[str, Any]:
        if self.dry_run:
            return {
                "status": "dry_run",
                "action": "buy",
                "market_slug": market_slug,
                "outcome": outcome,
                "amount_usdc": amount_usdc,
            }
        token_id = self._lookup_token_id(market_slug, outcome)
        response = self._post_market_order(token_id=token_id, side="BUY", amount_usdc=amount_usdc)
        return {
            "status": "submitted",
            "action": "buy",
            "market_slug": market_slug,
            "outcome": outcome,
            "amount_usdc": amount_usdc,
            "response": response,
        }

    def place_sell(self, market_slug: str, outcome: str, amount_usdc: float) -> dict[str, Any]:
        if self.dry_run:
            return {
                "status": "dry_run",
                "action": "sell",
                "market_slug": market_slug,
                "outcome": outcome,
                "amount_usdc": amount_usdc,
            }
        token_id = self._lookup_token_id(market_slug, outcome)
        response = self._post_market_order(token_id=token_id, side="SELL", amount_usdc=amount_usdc)
        return {
            "status": "submitted",
            "action": "sell",
            "market_slug": market_slug,
            "outcome": outcome,
            "amount_usdc": amount_usdc,
            "response": response,
        }

    def exit_position(self, market_slug: str, outcome: str) -> dict[str, Any]:
        if self.dry_run:
            return {
                "status": "dry_run",
                "action": "exit",
                "market_slug": market_slug,
                "outcome": outcome,
            }
        token_id = self._lookup_token_id(market_slug, outcome)
        # Best-effort: sell a conservative notional; operators should prefer explicit sell amount when live.
        response = self._post_market_order(token_id=token_id, side="SELL", amount_usdc=10.0)
        return {
            "status": "submitted",
            "action": "exit",
            "market_slug": market_slug,
            "outcome": outcome,
            "response": response,
        }
