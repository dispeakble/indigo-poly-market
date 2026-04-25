from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from rich.console import Console
from rich.table import Table

from src.alert_manager import AlertManager
from src.api import create_app
from src.config import load_config
from src.copy_logic import CopyTrader
from src.data_api import PolymarketDataAPI
from src.polymarket_client import PolymarketClient
from src.state_manager import StateManager
from src.telegram_control import TelegramController

console = Console()


def build_live_table(copy_trader: CopyTrader, state: StateManager, dry_run: bool) -> Table:
    st = state.get_state()
    table = Table(title="Indigo Poly Market — Live Summary")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Mode", "DRY RUN" if dry_run else "LIVE")
    table.add_row("Wallets mirrored", str(len(st.copied_wallets)))
    table.add_row("Positions", str(len(st.copied_positions)))
    table.add_row(
        "Last poll",
        datetime.fromtimestamp(st.last_poll_ts, tz=timezone.utc).isoformat()
        if st.last_poll_ts
        else "never",
    )
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description="Indigo Poly Market copy-trading bot")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML")
    parser.add_argument("--live", action="store_true", help="Render periodic live rich table")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to env file for runtime key updates via Telegram commands",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    state = StateManager("state.json")
    alerts = AlertManager(config)
    data_api = PolymarketDataAPI()
    trader = PolymarketClient(private_key=config.polymarket_private_key, dry_run=config.dry_run)
    copy_trader = CopyTrader(config, state, data_api, trader, alerts)
    telegram_ctl = TelegramController(
        config=config,
        state=state,
        copy_trader=copy_trader,
        trader=trader,
        config_path=str(Path(args.config).resolve()),
        env_path=str(Path(args.env_file).resolve()),
    )

    scheduler = BackgroundScheduler()

    def poll_job() -> None:
        events = copy_trader.poll_and_copy()
        if events:
            console.print(f"[bold green]Poll completed[/bold green] with {len(events)} mirrored events")
        else:
            console.print("[yellow]Poll completed[/yellow] with no deltas")

    scheduler.add_job(poll_job, "interval", minutes=config.poll_interval_minutes, max_instances=1)

    def telegram_job() -> None:
        telegram_ctl.poll_once()

    scheduler.add_job(telegram_job, "interval", seconds=2, max_instances=1)
    scheduler.start()

    stop_event = threading.Event()

    def _shutdown(*_: object) -> None:
        console.print("[bold red]Shutdown signal received[/bold red]")
        stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Trigger immediate startup poll.
    poll_job()

    app = create_app(config=config, copy_trader=copy_trader, state=state)

    uvicorn_server = None
    api_thread = None

    if config.api_enabled:
        uv_config = uvicorn.Config(
            app,
            host=config.api_host,
            port=config.api_port,
            log_level="info",
            access_log=False,
        )
        uvicorn_server = uvicorn.Server(uv_config)
        api_thread = threading.Thread(target=uvicorn_server.run, daemon=True)
        api_thread.start()
        console.print(
            f"[bold blue]API running[/bold blue] on http://{config.api_host}:{config.api_port}"
        )

    try:
        while not stop_event.is_set():
            if args.live:
                console.clear()
                console.print(build_live_table(copy_trader, state, config.dry_run))
            time.sleep(2)
    finally:
        scheduler.shutdown(wait=False)
        if uvicorn_server is not None:
            uvicorn_server.should_exit = True
        if api_thread is not None:
            api_thread.join(timeout=5)
        console.print("[bold]Indigo Poly Market stopped cleanly[/bold]")
        sys.exit(0)


if __name__ == "__main__":
    main()
