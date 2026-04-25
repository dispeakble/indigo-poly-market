from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .alert_manager import AlertManager
from .config import IndigoConfig, load_config
from .copy_logic import CopyTrader
from .data_api import PolymarketDataAPI
from .polymarket_client import PolymarketClient
from .state_manager import StateManager


class ManualTradeRequest(BaseModel):
    action: Literal["buy", "sell", "exit"]
    market_slug: str
    outcome: str = Field(default="Yes")
    amount_usdc: float = Field(default=0, ge=0)


def create_app(config: IndigoConfig, copy_trader: CopyTrader, state: StateManager) -> FastAPI:
    app = FastAPI(title="Indigo Poly Market API", version="1.0.0")

    def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
        if not x_api_key or x_api_key != config.api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")

    @app.get("/status", dependencies=[Depends(require_api_key)])
    def get_status() -> dict:
        st = state.get_state()
        return {
            "service": "indigo-poly-market",
            "dry_run": config.dry_run,
            "last_poll_ts": st.last_poll_ts,
            "last_poll_iso": datetime.fromtimestamp(st.last_poll_ts, tz=timezone.utc).isoformat()
            if st.last_poll_ts
            else None,
            "copied_wallets_count": len(st.copied_wallets),
            "copied_wallets": st.copied_wallets,
            "positions_count": len(st.copied_positions),
            "poll_interval_minutes": config.poll_interval_minutes,
            "auto_top_n": config.auto_top_n,
        }

    @app.get("/positions", dependencies=[Depends(require_api_key)])
    def get_positions() -> list[dict]:
        st = state.get_state()
        output: list[dict] = []
        for pos in st.copied_positions.values():
            current_value = pos.size_usdc * pos.current_price
            output.append(
                {
                    "market": pos.market_slug,
                    "outcome": pos.outcome,
                    "size": pos.size_usdc,
                    "entry_price": pos.avg_entry_price,
                    "current_price": pos.current_price,
                    "current_value": current_value,
                    "unrealized_pnl": pos.unrealized_pnl,
                }
            )
        return output

    @app.post("/manual_trade", dependencies=[Depends(require_api_key)])
    def manual_trade(req: ManualTradeRequest) -> dict:
        if req.action != "exit" and req.amount_usdc <= 0:
            raise HTTPException(status_code=400, detail="amount_usdc must be > 0 for buy/sell")
        return copy_trader.manual_trade(
            action=req.action,
            market_slug=req.market_slug,
            outcome=req.outcome,
            amount_usdc=req.amount_usdc,
        )

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        st = state.get_state()
        rows = []
        for pos in st.copied_positions.values():
            rows.append(
                f"<tr><td>{pos.market_slug}</td><td>{pos.outcome}</td><td>{pos.size_usdc:.2f}</td>"
                f"<td>{pos.avg_entry_price:.4f}</td><td>{pos.current_price:.4f}</td><td>{pos.unrealized_pnl:.4f}</td></tr>"
            )

        table_rows = "".join(rows) if rows else "<tr><td colspan='6'>No copied positions yet</td></tr>"
        return f"""
<!doctype html>
<html>
<head>
  <meta charset='utf-8'/>
  <title>Indigo Poly Market</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; background: #0f172a; color: #e2e8f0; }}
    h1 {{ margin-bottom: 4px; }}
    .meta {{ color: #94a3b8; margin-bottom: 18px; }}
    table {{ border-collapse: collapse; width: 100%; background: #111827; }}
    th, td {{ border: 1px solid #334155; padding: 8px; text-align: left; }}
    th {{ background: #1e293b; }}
  </style>
</head>
<body>
  <h1>Indigo Poly Market</h1>
  <div class='meta'>Dry-run: {config.dry_run} • Wallets mirrored: {len(st.copied_wallets)} • Positions: {len(st.copied_positions)}</div>
  <table>
    <thead><tr><th>Market</th><th>Outcome</th><th>Size (USDC)</th><th>Entry</th><th>Current</th><th>Unrealized PnL</th></tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
</body>
</html>
"""

    return app


# Uvicorn factory support: uvicorn src.api:app --reload
_cfg = load_config("config.yaml")
_state = StateManager("state.json")
_alerts = AlertManager(_cfg)
_data = PolymarketDataAPI()
_pm_client = PolymarketClient(private_key=_cfg.polymarket_private_key, dry_run=_cfg.dry_run)
_copy = CopyTrader(_cfg, _state, _data, _pm_client, _alerts)
app = create_app(_cfg, _copy, _state)
