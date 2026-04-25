from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Any

import requests

from .config import IndigoConfig
from .copy_logic import CopyTrader
from .polymarket_client import PolymarketClient
from .runtime_control import mask_key, save_private_key_to_env, set_dry_run_mode
from .state_manager import StateManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ParsedCommand:
    name: str
    args: list[str]


def parse_command_text(text: str) -> ParsedCommand | None:
    if not text:
        return None
    text = text.strip()
    if not text.startswith('/'):
        return None
    parts = text.split()
    name = parts[0][1:].split('@')[0].lower()
    args = parts[1:]

    # Backward compatibility aliases
    aliases = {
        'help': 'indigo_help',
        'start': 'indigo_start',
        'status': 'indigo_status',
        'dryrun': 'indigo_dryrun',
        'bets': 'indigo_bets',
        'buy': 'indigo_buy',
        'sell': 'indigo_sell',
        'exit': 'indigo_exit',
        'setkey': 'indigo_setkey',
        'service': 'indigo_service',
    }
    name = aliases.get(name, name)

    return ParsedCommand(name=name, args=args)


class TelegramController:
    def __init__(
        self,
        config: IndigoConfig,
        state: StateManager,
        copy_trader: CopyTrader,
        trader: PolymarketClient,
        config_path: str = 'config.yaml',
        env_path: str = '.env',
    ) -> None:
        self.config = config
        self.state = state
        self.copy_trader = copy_trader
        self.trader = trader
        self.config_path = config_path
        self.env_path = env_path
        self.enabled = bool(config.telegram_enabled and config.telegram_bot_token and config.telegram_chat_id)
        self._offset: int | None = None
        self._commands_registered = False

    def poll_once(self) -> None:
        if not self.enabled:
            return
        if not self._commands_registered:
            self._register_commands()
            self._commands_registered = True
        updates = self._get_updates()
        for upd in updates:
            self._offset = upd['update_id'] + 1
            msg = upd.get('message') or {}
            text = msg.get('text', '')
            chat_id = str(msg.get('chat', {}).get('id', ''))
            if str(self.config.telegram_chat_id) != chat_id:
                continue
            parsed = parse_command_text(text)
            if not parsed:
                continue
            response = self._handle_command(parsed)
            self._send_message(response)

    def _register_commands(self) -> None:
        commands = [
            {'command': 'indigo_help', 'description': 'List Indigo commands'},
            {'command': 'indigo_status', 'description': 'Show Indigo bot status'},
            {'command': 'indigo_dryrun', 'description': 'Toggle dry-run: on/off'},
            {'command': 'indigo_bets', 'description': 'Show active bets'},
            {'command': 'indigo_buy', 'description': 'Buy: slug outcome amount'},
            {'command': 'indigo_sell', 'description': 'Sell: slug outcome amount'},
            {'command': 'indigo_exit', 'description': 'Exit: slug [outcome]'},
            {'command': 'indigo_setkey', 'description': 'Set Polymarket key and restart'},
            {'command': 'indigo_service', 'description': 'Service: start/stop/restart/status'},
        ]
        try:
            requests.post(
                self._api_url('setMyCommands'),
                json={'commands': commands},
                timeout=20,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning('Telegram setMyCommands failed: %s', exc)

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.config.telegram_bot_token}/{method}"

    def _get_updates(self) -> list[dict[str, Any]]:
        params: dict[str, Any] = {'timeout': 0}
        if self._offset is not None:
            params['offset'] = self._offset
        try:
            resp = requests.get(self._api_url('getUpdates'), params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            return data.get('result', [])
        except Exception as exc:  # noqa: BLE001
            logger.warning('Telegram getUpdates failed: %s', exc)
            return []

    def _send_message(self, text: str) -> None:
        try:
            requests.post(
                self._api_url('sendMessage'),
                json={'chat_id': self.config.telegram_chat_id, 'text': text},
                timeout=20,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning('Telegram sendMessage failed: %s', exc)

    def _handle_command(self, cmd: ParsedCommand) -> str:
        try:
            if cmd.name in {'indigo_help', 'indigo_start'}:
                return self._help_text()
            if cmd.name == 'indigo_status':
                st = self.state.get_state()
                return (
                    f"Indigo status\n"
                    f"dry_run={self.config.dry_run}\n"
                    f"wallets={len(st.copied_wallets)}\n"
                    f"positions={len(st.copied_positions)}"
                )
            if cmd.name == 'indigo_dryrun':
                return self._cmd_dryrun(cmd.args)
            if cmd.name == 'indigo_bets':
                return self._cmd_bets()
            if cmd.name == 'indigo_buy':
                return self._cmd_trade('buy', cmd.args)
            if cmd.name == 'indigo_sell':
                return self._cmd_trade('sell', cmd.args)
            if cmd.name == 'indigo_exit':
                return self._cmd_exit(cmd.args)
            if cmd.name == 'indigo_setkey':
                return self._cmd_setkey(cmd.args)
            if cmd.name == 'indigo_service':
                return self._cmd_service(cmd.args)
            return 'Unknown command. Use /indigo_help'
        except Exception as exc:  # noqa: BLE001
            logger.exception('Command failed: %s', exc)
            return f'Command error: {exc}'

    def _help_text(self) -> str:
        return (
            'Indigo commands:\n'
            '/indigo_help\n'
            '/indigo_status\n'
            '/indigo_dryrun on|off\n'
            '/indigo_bets\n'
            '/indigo_buy <market_slug> <Yes|No> <amount_usdc>\n'
            '/indigo_sell <market_slug> <Yes|No> <amount_usdc>\n'
            '/indigo_exit <market_slug> [Yes|No]\n'
            '/indigo_setkey <0xPRIVATEKEY>\n'
            '/indigo_service start|stop|restart|status'
        )

    def _cmd_dryrun(self, args: list[str]) -> str:
        if not args or args[0].lower() not in {'on', 'off'}:
            return 'Usage: /indigo_dryrun on|off'
        value = args[0].lower() == 'on'
        self.trader.set_dry_run(value)
        self.copy_trader.config.dry_run = value
        set_dry_run_mode(self.config, value, self.config_path)
        return f'dry_run set to {value}'

    def _cmd_bets(self) -> str:
        st = self.state.get_state()
        if not st.copied_positions:
            return 'No active bets.'
        lines = ['Active bets:']
        for p in st.copied_positions.values():
            lines.append(
                f"- {p.market_slug} {p.outcome} size={p.size_usdc:.2f} entry={p.avg_entry_price:.4f} now={p.current_price:.4f} pnl={p.unrealized_pnl:.4f}"
            )
        return '\n'.join(lines)

    def _cmd_trade(self, action: str, args: list[str]) -> str:
        if len(args) < 3:
            return f'Usage: /indigo_{action} <market_slug> <Yes|No> <amount_usdc>'
        market_slug = args[0]
        outcome = args[1]
        amount = float(args[2])
        res = self.copy_trader.manual_trade(action, market_slug, outcome, amount)
        return f"ok {action}: {res.get('status', 'submitted')}"

    def _cmd_exit(self, args: list[str]) -> str:
        if len(args) < 1:
            return 'Usage: /indigo_exit <market_slug> [Yes|No]'
        market_slug = args[0]
        outcome = args[1] if len(args) > 1 else 'Yes'
        res = self.copy_trader.manual_trade('exit', market_slug, outcome, 0.0)
        return f"ok exit: {res.get('status', 'submitted')}"

    def _cmd_setkey(self, args: list[str]) -> str:
        if len(args) != 1 or not args[0].startswith('0x'):
            return 'Usage: /indigo_setkey <0xPRIVATEKEY>'
        key = args[0].strip()
        save_private_key_to_env(key, self.env_path)
        self.trader.set_private_key(key)
        self.config.polymarket_private_key = key
        # Auto-restart so whole process (including schedulers) picks up env/config cleanly.
        self._service_control('restart')
        return f'private key updated: {mask_key(key)}; service restarting...'

    def _cmd_service(self, args: list[str]) -> str:
        if not args:
            return 'Usage: /indigo_service start|stop|restart|status'
        action = args[0].lower()
        if action not in {'start', 'stop', 'restart', 'status'}:
            return 'Usage: /indigo_service start|stop|restart|status'
        return self._service_control(action)

    def _service_control(self, action: str) -> str:
        if action == 'status':
            res = subprocess.run(
                ['systemctl', '--user', 'is-active', 'indigo-poly-market.service'],
                capture_output=True,
                text=True,
                check=False,
            )
            status = (res.stdout or res.stderr).strip() or 'unknown'
            return f'service status: {status}'

        res = subprocess.run(
            ['systemctl', '--user', action, 'indigo-poly-market.service'],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return f'service {action}: ok'
        err = (res.stderr or res.stdout).strip()
        return f'service {action}: failed - {err}'
