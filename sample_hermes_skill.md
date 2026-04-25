# Hermes Skill: Indigo Poly Market Controller

## Purpose
Control Indigo Poly Market via secure FastAPI endpoints from Hermes Agent.

## Required environment variables

```bash
INDIGO_BASE_URL=http://127.0.0.1:8000
INDIGO_API_KEY=replace_with_real_key
```

## Commands

### 1) Indigo status

User phrase examples:
- "Indigo status"
- "Show Indigo health"

Action:

```bash
curl -s "$INDIGO_BASE_URL/status" \
  -H "X-API-Key: $INDIGO_API_KEY"
```

### 2) Indigo positions / bets

User phrase examples:
- "Indigo positions"
- "Show current copied bets"
- "Indigo bets"

Action:

```bash
curl -s "$INDIGO_BASE_URL/positions" \
  -H "X-API-Key: $INDIGO_API_KEY"
```

### 3) Indigo buy

User phrase examples:
- "Indigo buy 50 Yes on will-trump-win-2028"
- "Indigo enter 25 No on [slug]"

Action template:

```bash
curl -s -X POST "$INDIGO_BASE_URL/manual_trade" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $INDIGO_API_KEY" \
  -d '{
    "action": "buy",
    "market_slug": "<slug>",
    "outcome": "<Yes|No>",
    "amount_usdc": <amount>
  }'
```

### 4) Indigo sell

User phrase examples:
- "Indigo sell 40 Yes on [slug]"

Action template:

```bash
curl -s -X POST "$INDIGO_BASE_URL/manual_trade" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $INDIGO_API_KEY" \
  -d '{
    "action": "sell",
    "market_slug": "<slug>",
    "outcome": "<Yes|No>",
    "amount_usdc": <amount>
  }'
```

### 5) Indigo exit

User phrase examples:
- "Indigo exit Trump market"
- "Indigo close Yes on [slug]"

Action template:

```bash
curl -s -X POST "$INDIGO_BASE_URL/manual_trade" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $INDIGO_API_KEY" \
  -d '{
    "action": "exit",
    "market_slug": "<slug>",
    "outcome": "<Yes>",
    "amount_usdc": 0
  }'
```

## Parsing logic for Hermes

- Detect keyword `indigo` then route to this skill.
- Extract:
  - action (`buy|sell|exit|status|positions`)
  - amount (float) for buy/sell
  - outcome (`Yes|No`, default `Yes`)
  - market slug after `on`
- For ambiguous market names (e.g. “Trump market”), query `/positions`, fuzzy-match slugs, ask user to confirm if multiple.

## Safety rules

- Require explicit amount for buy/sell.
- Reject non-positive amount for buy/sell.
- Confirm `exit` if no matching open position.
- Never log API key or private key.

## Success response format

Return concise JSON summary to user:

```json
{
  "ok": true,
  "action": "buy",
  "market_slug": "will-trump-win-2028",
  "outcome": "Yes",
  "amount_usdc": 50.0,
  "broker_response": {"status": "dry_run"}
}
```
