from __future__ import annotations

import os
from pathlib import Path

from .config import IndigoConfig


def save_private_key_to_env(private_key: str, env_path: str | Path = '.env') -> None:
    path = Path(env_path)
    if path.exists():
        lines = path.read_text(encoding='utf-8').splitlines()
    else:
        lines = []

    found = False
    out: list[str] = []
    for line in lines:
        if line.startswith('POLYMARKET_PRIVATE_KEY='):
            out.append(f'POLYMARKET_PRIVATE_KEY={private_key}')
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f'POLYMARKET_PRIVATE_KEY={private_key}')

    path.write_text('\n'.join(out).rstrip() + '\n', encoding='utf-8')


def set_dry_run_mode(config: IndigoConfig, dry_run: bool, config_path: str | Path = 'config.yaml') -> None:
    config.dry_run = dry_run
    path = Path(config_path)
    text = path.read_text(encoding='utf-8')

    # Keep formatting stable and only mutate dry_run field.
    import re

    text = re.sub(r'^dry_run:\s*(true|false)\s*$', f"dry_run: {'true' if dry_run else 'false'}", text, flags=re.MULTILINE)
    path.write_text(text, encoding='utf-8')


def mask_key(key: str) -> str:
    if len(key) <= 12:
        return '***'
    return f"{key[:6]}...{key[-4:]}"
