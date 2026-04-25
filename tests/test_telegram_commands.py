from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtime_control import mask_key
from src.telegram_control import parse_command_text


def test_parse_dryrun_on() -> None:
    cmd = parse_command_text('/dryrun on')
    assert cmd is not None
    assert cmd.name == 'dryrun'
    assert cmd.args == ['on']


def test_parse_buy_command() -> None:
    cmd = parse_command_text('/buy will-trump-win-2028 Yes 50')
    assert cmd is not None
    assert cmd.name == 'buy'
    assert cmd.args == ['will-trump-win-2028', 'Yes', '50']


def test_parse_exit_command() -> None:
    cmd = parse_command_text('/exit will-trump-win-2028 No')
    assert cmd is not None
    assert cmd.name == 'exit'
    assert cmd.args == ['will-trump-win-2028', 'No']


def test_parse_non_command_returns_none() -> None:
    assert parse_command_text('hello world') is None


def test_mask_key() -> None:
    assert mask_key('0x' + '1' * 64).startswith('0x1111')
    assert mask_key('short') == '***'
