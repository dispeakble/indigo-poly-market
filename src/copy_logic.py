from __future__ import annotations

from dataclasses import dataclass

from .alert_manager import AlertManager
from .config import IndigoConfig
from .data_api import PolymarketDataAPI
from .polymarket_client import PolymarketClient
from .state_manager import PositionSnapshot, StateManager
from .utils import now_utc_ts, position_key


@dataclass(slots=True)
class CopyEvent:
    action: str
    market_slug: str
    outcome: str
    amount_usdc: float


class CopyTrader:
    def __init__(
        self,
        config: IndigoConfig,
        state: StateManager,
        data_api: PolymarketDataAPI,
        trader: PolymarketClient,
        alerts: AlertManager,
    ) -> None:
        self.config = config
        self.state = state
        self.data_api = data_api
        self.trader = trader
        self.alerts = alerts

    def compute_bet_amount(self) -> float:
        balance = self.trader.get_usdc_balance()
        if self.config.bet_mode == "fixed":
            desired = self.config.bet_value
        else:
            desired = balance * (self.config.bet_value / 100)
        return float(min(desired, self.config.max_bet_usdc, balance))

    def poll_and_copy(self) -> list[CopyEvent]:
        wallets = self.data_api.fetch_top_wallets(self.config.auto_top_n)
        aggregate: dict[str, float] = {}

        for wallet in wallets:
            positions = self.data_api.fetch_wallet_positions(wallet)
            for pos in positions:
                key = position_key(pos.market_slug, pos.outcome)
                aggregate[key] = aggregate.get(key, 0.0) + pos.size_usdc

        current_state = self.state.get_state()
        previous = current_state.source_positions

        events: list[CopyEvent] = []

        # New / increase / reduce handling by delta
        all_keys = set(previous.keys()) | set(aggregate.keys())
        for key in all_keys:
            prev_size = float(previous.get(key, {}).get("size_usdc", 0.0))
            new_size = float(aggregate.get(key, 0.0))
            delta = new_size - prev_size
            if abs(delta) < 1e-9:
                continue

            market_slug, outcome = key.split(":", maxsplit=1)
            amount = min(abs(delta), self.compute_bet_amount())
            if amount <= 0:
                continue

            if delta > 0:
                self.trader.place_buy(market_slug, outcome, amount)
                action = "buy" if prev_size == 0 else "increase"
            else:
                if new_size <= 0:
                    self.trader.exit_position(market_slug, outcome)
                    action = "exit"
                else:
                    self.trader.place_sell(market_slug, outcome, amount)
                    action = "reduce"

            price = self.trader.get_market_price(market_slug, outcome)
            pos_key = position_key(market_slug, outcome)
            if action == "exit":
                self.state.remove_position(pos_key)
            else:
                snapshot = current_state.copied_positions.get(pos_key)
                prev_copied = snapshot.size_usdc if snapshot else 0.0
                signed = amount if action in {"buy", "increase"} else -amount
                next_size = max(prev_copied + signed, 0.0)
                avg_entry = snapshot.avg_entry_price if snapshot else price
                if action in {"buy", "increase"} and next_size > 0:
                    avg_entry = (
                        ((prev_copied * avg_entry) + (amount * price)) / next_size
                        if prev_copied > 0
                        else price
                    )
                pnl = (price - avg_entry) * next_size
                self.state.upsert_position(
                    pos_key,
                    PositionSnapshot(
                        market_slug=market_slug,
                        outcome=outcome,
                        size_usdc=next_size,
                        avg_entry_price=avg_entry,
                        current_price=price,
                        unrealized_pnl=pnl,
                    ),
                )

            event = CopyEvent(action=action, market_slug=market_slug, outcome=outcome, amount_usdc=amount)
            events.append(event)
            self.alerts.send(
                f"copy_{action}",
                {
                    "market": market_slug,
                    "outcome": outcome,
                    "amount_usdc": f"{amount:.2f}",
                    "dry_run": self.config.dry_run,
                },
            )

        snapshot_positions = {k: {"size_usdc": v} for k, v in aggregate.items()}
        self.state.update(
            last_poll_ts=now_utc_ts(),
            copied_wallets=wallets,
            source_positions=snapshot_positions,
        )
        return events

    def manual_trade(self, action: str, market_slug: str, outcome: str, amount_usdc: float) -> dict:
        if action == "buy":
            res = self.trader.place_buy(market_slug, outcome, amount_usdc)
            price = self.trader.get_market_price(market_slug, outcome)
            pos_key = position_key(market_slug, outcome)
            st = self.state.get_state()
            snap = st.copied_positions.get(pos_key)
            prev_size = snap.size_usdc if snap else 0.0
            next_size = prev_size + amount_usdc
            avg_entry = (
                ((prev_size * snap.avg_entry_price) + (amount_usdc * price)) / next_size
                if snap and next_size > 0
                else price
            )
            pnl = (price - avg_entry) * next_size
            self.state.upsert_position(
                pos_key,
                PositionSnapshot(
                    market_slug=market_slug,
                    outcome=outcome,
                    size_usdc=next_size,
                    avg_entry_price=avg_entry,
                    current_price=price,
                    unrealized_pnl=pnl,
                ),
            )
        elif action == "sell":
            res = self.trader.place_sell(market_slug, outcome, amount_usdc)
            pos_key = position_key(market_slug, outcome)
            st = self.state.get_state()
            snap = st.copied_positions.get(pos_key)
            if snap:
                next_size = max(snap.size_usdc - amount_usdc, 0.0)
                if next_size <= 0:
                    self.state.remove_position(pos_key)
                else:
                    price = self.trader.get_market_price(market_slug, outcome)
                    self.state.upsert_position(
                        pos_key,
                        PositionSnapshot(
                            market_slug=market_slug,
                            outcome=outcome,
                            size_usdc=next_size,
                            avg_entry_price=snap.avg_entry_price,
                            current_price=price,
                            unrealized_pnl=(price - snap.avg_entry_price) * next_size,
                        ),
                    )
        elif action == "exit":
            res = self.trader.exit_position(market_slug, outcome)
            self.state.remove_position(position_key(market_slug, outcome))
        else:
            raise ValueError(f"Unsupported action: {action}")

        self.alerts.send(
            "manual_trade",
            {
                "action": action,
                "market": market_slug,
                "outcome": outcome,
                "amount_usdc": amount_usdc,
                "dry_run": self.config.dry_run,
            },
        )
        return res
