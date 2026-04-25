# Indigo Poly Market

Indigo Poly Market is a production-oriented Python copy-trading bot for Polymarket.
It mirrors top wallets in near real time, tracks deltas (new buy, increase, reduce, full exit), and exposes a secure FastAPI control surface for Hermes Agent orchestration.

## Features

- Auto-fetches top `N` wallets from Polymarket Data API leaderboard
- Delta-based exact copy logic using persisted `state.json`
- Bet sizing modes:
  - `fixed`: fixed USDC amount per mirrored delta
  - `percentage`: % of your live USDC balance
- Risk controls:
  - `max_bet_usdc`
  - `dry_run` default enabled
- Alerts for every event to:
  - Telegram
  - Hermes webhook (`hermes_webhook_url`)
- Built-in FastAPI server (same process as scheduler)
  - `GET /status`
  - `GET /positions`
  - `POST /manual_trade`
  - HTML dashboard at `GET /`
- Rich terminal output and optional `--live` table
- Graceful shutdown on SIGINT/SIGTERM

---

## ⚠️ Security & Trading Warnings

1. **Private key safety**
   - Never commit `.env`
   - Use a dedicated low-balance trading wallet
   - Rotate compromised keys immediately
2. **API key safety**
   - Control API uses `X-API-Key`
   - Use a long random key (32+ chars)
3. **Network safety**
   - Do not expose port `8000` publicly without TLS + firewall + reverse-proxy auth
4. **Execution safety**
   - Start with `dry_run: true`
   - Validate behavior for multiple cycles before setting `dry_run: false`
5. **Live trading implementation note**
   - Live order methods are wired to `py-clob-client` market orders (`BUY`/`SELL`, FOK).
   - Validate this in small size first: order semantics can differ by market liquidity and token precision.

---

## Project Structure

```text
indigo-poly-market/
├── main.py
├── config.yaml
├── .env.example
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── polymarket_client.py
│   ├── data_api.py
│   ├── copy_logic.py
│   ├── alert_manager.py
│   ├── state_manager.py
│   ├── api.py
│   └── utils.py
├── sample_hermes_skill.md
└── README.md
```

---

## Requirements

- Python 3.11+
- A Polymarket-compatible private key
- (Optional) Telegram bot token + chat id
- (Optional) Hermes webhook endpoint

Install:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Configuration

### 1) Environment variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Populate:

- `POLYMARKET_PRIVATE_KEY`
- `INDIGO_API_KEY`
- Optional Telegram values

### 2) YAML config

Edit `config.yaml`:

- `auto_top_n`: number of leader wallets to mirror
- `bet_mode`: `fixed` or `percentage`
- `bet_value`: amount or percent
- `max_bet_usdc`: hard cap per mirrored action
- `poll_interval_minutes`: polling cadence
- `dry_run`: keep `true` until verified
- `api_*`: embedded API bind/auth settings

---

## Run

### Standard mode

```bash
python main.py
```

### Live table mode

```bash
python main.py --live
```

### Custom config path

```bash
python main.py --config /path/to/config.yaml --live
```

---

## API Usage

Set API key header:

```bash
export INDIGO_KEY="your_api_key"
```

### Health/status

```bash
curl -s http://127.0.0.1:8000/status \
  -H "X-API-Key: $INDIGO_KEY"
```

### Positions

```bash
curl -s http://127.0.0.1:8000/positions \
  -H "X-API-Key: $INDIGO_KEY"
```

### Manual trade

```bash
curl -s -X POST http://127.0.0.1:8000/manual_trade \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $INDIGO_KEY" \
  -d '{
    "action": "buy",
    "market_slug": "will-example-happen",
    "outcome": "Yes",
    "amount_usdc": 50.0
  }'
```

### HTML dashboard

Open in browser:

- `http://127.0.0.1:8000/`

---

## How copy logic works

1. Fetch top wallets from leaderboard
2. Fetch each wallet’s open positions
3. Aggregate source sizes by `(market_slug, outcome)`
4. Compare against prior snapshot in `state.json`
5. For each key delta:
   - positive delta → `buy` / `increase`
   - negative delta but still open → `reduce`
   - drops to zero → `exit`
6. Emit alerts (Telegram + webhook)
7. Persist new snapshot

---

## Running with uvicorn directly

This project embeds uvicorn in `main.py` so scheduler + API run together.
If you only need API routes for testing:

```bash
uvicorn src.api:app --reload --host 0.0.0.0 --port 8000
```

(For production copy-trading, use `python main.py` so polling scheduler is active.)

---

## Telegram bot commands

Enable Telegram in `config.yaml`:

```yaml
telegram_enabled: true
telegram_bot_token: "${TELEGRAM_BOT_TOKEN}"
telegram_chat_id: "${TELEGRAM_CHAT_ID}"
```

Then restart service:

```bash
systemctl --user restart indigo-poly-market.service
```

Supported commands (from your configured `telegram_chat_id` only):

- `/indigo_help` or `/indigo_start` → list commands
- `/indigo_status` → dry-run, wallets count, positions count
- `/indigo_dryrun on` or `/indigo_dryrun off` → toggle dry-run and persist in `config.yaml`
- `/indigo_bets` → show all active bets
- `/indigo_buy <market_slug> <Yes|No> <amount_usdc>` → place buy
- `/indigo_sell <market_slug> <Yes|No> <amount_usdc>` → place sell/reduce
- `/indigo_exit <market_slug> [Yes|No]` → exit position
- `/indigo_setkey <0xPRIVATEKEY>` → save private key in `.env`, then auto-restart service
- `/indigo_service start|stop|restart|status` → control service lifecycle

Example:

```text
/indigo_dryrun on
/indigo_bets
/indigo_buy will-trump-win-2028 Yes 25
/indigo_sell will-trump-win-2028 Yes 10
/indigo_exit will-trump-win-2028 Yes
/indigo_setkey 0xabc123...
/indigo_service status
```

Security notes:

- Keep bot in a private chat.
- Only messages from configured `telegram_chat_id` are accepted.
- `/setkey` updates `.env`; keep `.env` private and never commit it.

---

## Hermes integration

Use `sample_hermes_skill.md` to add Indigo controls into Hermes Agent.
It includes natural-language command mappings:

- “Indigo status”
- “Indigo exit Trump market”
- “Indigo buy 50 Yes on [slug]”

---

## Operational checklist

- [ ] `dry_run` verified over several cycles
- [ ] API key rotated and strong
- [ ] Firewall restricts API source IPs
- [ ] Telegram + webhook alerts validated
- [ ] Wallet funded conservatively
- [ ] Backups for `state.json`
