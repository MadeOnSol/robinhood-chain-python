# robinhood-chain

[![PyPI](https://img.shields.io/pypi/v/robinhood-chain?style=flat-square)](https://pypi.org/project/robinhood-chain/)
[![Python](https://img.shields.io/pypi/pyversions/robinhood-chain?style=flat-square)](https://pypi.org/project/robinhood-chain/)
[![Downloads](https://img.shields.io/pypi/dm/robinhood-chain?style=flat-square)](https://pypi.org/project/robinhood-chain/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)

> ⭐ **[Star on GitHub](https://github.com/madeonsol/robinhood-chain-python)** · 📂 **[Examples](./examples/)** · 📚 **[API docs](https://madeonsol.com/api-docs)** · 🏦 **[Robinhood Chain hub](https://madeonsol.com/robinhood)**

**Robinhood Chain SDK for Python — EVM-native trading intelligence, chain id 4663.**

Live KOL trades, token discovery, launch-bundle detection, early-buyer quality, deployer reputation, the Uniswap v2/v3/v4 trade tape, OHLC candles, and smart-money wallet ranking — for [Robinhood Chain](https://madeonsol.com/robinhood) (an Arbitrum Orbit L2, chain id **4663**), served from our self-hosted node. Everything is EVM-native: lowercase `0x` addresses (`token_address`), `eth_amount`, `tx_hash`, `block_number`, `net_flow_eth`. No Solana field names.

Robinhood Chain coverage is bundled into **every** MadeOnSol tier at no extra cost — the same `msk_` API key and the same base URL. Free tier: 200 requests/day, no card. Get a key at [madeonsol.com/pricing](https://madeonsol.com/pricing).

New customers get a **5-day free trial** of Pro or Ultra when you pay by card — full access, nothing charged during the trial, cancel anytime. Start at [madeonsol.com/pricing](https://madeonsol.com/pricing).

## Quick start (10 seconds)

```bash
pip install robinhood-chain
```

```python
from robinhood_chain import RobinhoodClient

client = RobinhoodClient(api_key="msk_...")  # free key at https://madeonsol.com/pricing

# Real-time KOL trades on Robinhood Chain (chain id 4663)
feed = client.kol_feed(limit=5, action="buy")
for t in feed["trades"]:
    print(t["kol_name"], t["action"], t["token_address"], t["eth_amount"], "ETH", t["tx_hash"])
```

`GET https://madeonsol.com/api/v1/rhc/kol/feed` → every buy/sell from tracked KOLs' verified EVM wallets on Robinhood Chain, attributed via `tx.from`, sub-second from execution, enriched with live MC and `mc_multiple_since_trade` ("did the call run").

## Authentication

Bearer `msk_` API key — the same key and base URL as the Solana MadeOnSol API. This package also serves the **x402-Py key-mode** surface: Bearer auth only (the Solana-native pay-per-call x402 rail is not ported to Robinhood Chain).

```python
import os
from robinhood_chain import RobinhoodClient

client = RobinhoodClient(api_key=os.environ["MADEONSOL_API_KEY"])
```

## Endpoints — the 14 Robinhood Chain routes

Base URL `https://madeonsol.com/api/v1`. All addresses are lowercase `0x` (40 hex).

### KOL intelligence

| Method | Route | Tier |
|---|---|---|
| `client.kol_feed(limit=, before=, action=, kol=, min_eth=)` | `GET /api/v1/rhc/kol/feed` | BASIC |
| `client.kol_leaderboard(period=, limit=)` | `GET /api/v1/rhc/kol/leaderboard` | BASIC |
| `client.kol_hot_tokens(window=)` | `GET /api/v1/rhc/kol/hot-tokens` | BASIC |
| `client.kol_wallet(wallet)` | `GET /api/v1/rhc/kol/{wallet}` | BASIC |

### Trades & tokens

| Method | Route | Tier |
|---|---|---|
| `client.trades(limit=, token=, dex=, action=, min_eth=, before=)` | `GET /api/v1/rhc/trades` | PRO+ |
| `client.tokens(limit=, sort=, min_mc_usd=, min_liquidity_usd=, launchpad=)` | `GET /api/v1/rhc/tokens` | PRO+ |
| `client.token(address)` | `GET /api/v1/rhc/tokens/{address}` | BASIC |
| `client.token_candles(address, limit=, from_=, to=)` | `GET /api/v1/rhc/tokens/{address}/candles` | PRO+ |
| `client.token_kol_consensus(address)` | `GET /api/v1/rhc/tokens/{address}/kol-consensus` | PRO+ |
| `client.token_buyer_quality(address)` | `GET /api/v1/rhc/tokens/{address}/buyer-quality` | BASIC |
| `client.token_bundle(address)` | `GET /api/v1/rhc/tokens/{address}/bundle` | BASIC |

### Deployer hunter & alpha wallets

| Method | Route | Tier |
|---|---|---|
| `client.deployer_hunter_leaderboard(sort=, tier=, min_tokens=, limit=, offset=)` | `GET /api/v1/rhc/deployer-hunter/leaderboard` | BASIC |
| `client.deployer_hunter_profile(address)` | `GET /api/v1/rhc/deployer-hunter/{address}` | BASIC |
| `client.alpha_wallets(classification=, identity=, min_memecoin_share=, sort=, limit=, offset=, ...)` | `GET /api/v1/rhc/alpha-wallets` | PRO+ |

## Examples

### KOL leaderboard & consensus

```python
# KOLs ranked by trade count then net ETH flow (net_eth = buy − sell, not PnL)
lb = client.kol_leaderboard(period="24h", limit=20)   # '24h' | '7d' | '30d'
for row in lb["leaderboard"]:
    print(row["kol_name"], row["trades"], "trades", row["net_eth"], "ETH net")

# Tokens bought by 2+ distinct KOLs in the window (consensus signal)
hot = client.kol_hot_tokens(window="1h")              # '5m'|'15m'|'1h'|'6h'|'24h'
for tok in hot["tokens"]:
    print(tok["token_symbol"], tok["kols_buying"], "KOLs", tok["buy_eth"], "ETH")

# One KOL's profile: last-200-trade stats + 50 most recent trades
me = client.kol_wallet("0x1234567890abcdef1234567890abcdef12345678")
print(me["stats"]["net_eth"], me["stats"]["tokens_traded"])
```

### Token bundle + early-buyer quality

```python
addr = "0xabcdef1234567890abcdef1234567890abcdef12"

# Launch-bundle detection — RHC is an Arbitrum Orbit L2, so bundle_kind is
# 'same_block' or 'none' (there is NO atomic_tx on EVM).
b = client.token_bundle(addr)
print(b["bundle"]["bundle_kind"], b["bundle"]["held_ratio"], b["bundle"]["fully_exited"])

# 0–100 early-buyer quality — win-rate, KOL-presence, bundle + dump-cluster legs
q = client.token_buyer_quality(addr)
print(q["quality"]["score"], q["quality"]["signal"], q["quality"]["breakdown"])

# KOL consensus (PRO+): net_flow_eth, exit rate, median entry MC; ULTRA adds wallet lists
c = client.token_kol_consensus(addr)
if c["consensus"]:
    print(c["consensus"]["net_flow_eth"], c["consensus"]["kol_exit_rate"])
```

### DEX trade tape & candles (PRO+)

```python
# Every Uniswap v2/v3/v4 swap — trader_eoa is the real wallet (tx.from), not the router
tape = client.trades(dex="uniswap-v3", min_eth=0.1, limit=50)
for s in tape["trades"]:
    print(s["trader_eoa"], s["action"], s["eth_amount"], "ETH", s["tx_hash"], s["block_number"])

# 1-minute OHLC candles (oldest → newest)
candles = client.token_candles(addr, limit=240)
for k in candles["candles"]:
    print(k["bucket_start"], k["close_price_usd"], k["volume_usd"])
```

### Deployer reputation & smart money

```python
# Deployer reputation leaderboard — graduation_rate = share reaching $40K+ peak MC,
# runner_rate = share reaching $100K+ (most RHC launchpads are direct-to-DEX)
lb = client.deployer_hunter_leaderboard(sort="runner_rate", tier="elite", min_tokens=3, limit=20)
for d in lb["deployers"]:
    print(d["deployer_address"], d["tier"], d["graduation_rate"], d["runner_rate"])

# One deployer — unknown wallets return is_deployer: false (not a 404)
prof = client.deployer_hunter_profile("0x1111111111111111111111111111111111111111")
print(prof["is_deployer"], prof.get("recent_tokens_count"))

# Smart-money wallet ranking — net_eth is realized net flow (sell − buy)
sm = client.alpha_wallets(classification="smart_money", min_memecoin_share=0.7, sort="net_eth", limit=25)
for w in sm["wallets"]:
    print(w["wallet"], w["classification"], w["net_eth"], "ETH", w["win_rate"])
```

## Async

Every endpoint has an async twin via `client.aclient()` — same signature, returns a coroutine:

```python
import asyncio
from robinhood_chain import RobinhoodClient

client = RobinhoodClient(api_key="msk_...")

async def main():
    feed = await client.aclient().kol_feed(limit=10)
    print(feed["count"])

asyncio.run(main())
```

## Errors & rate limits

Non-2xx responses raise a typed error carrying the API's `error` message and `_rid` request id:

```python
from robinhood_chain import RobinhoodClient, AuthError, TierError, NotFoundError, RateLimitError

client = RobinhoodClient(api_key="msk_...")
try:
    client.trades(limit=50)               # PRO+
except TierError as e:
    print("upgrade needed:", e.message, e.request_id)
except RateLimitError as e:
    print("slow down; resets at", e.reset)
except NotFoundError as e:
    print("no RHC data:", e.message)

# Rate-limit headers from the most recent call:
print(client.last_rate_limit)
# {'limit': 100, 'remaining': 92, 'used': 8, 'reset': 1714000000, 'request_id': 'rid_abc'}
```

`AuthError` (401), `TierError` (403), `NotFoundError` (404), `RateLimitError` (429) all subclass `RobinhoodAPIError` → `RobinhoodError`. Transient failures (429/5xx) are retried automatically with exponential backoff (`max_retries`, default 2).

## Tiers

| Tier | Robinhood Chain endpoints |
|---|---|
| BASIC (free) | KOL feed/leaderboard/hot-tokens/profile, token snapshot, buyer-quality, bundle, deployer-hunter leaderboard/profile |
| PRO+ | + DEX trade tape, token discovery, candles, KOL consensus, alpha-wallets |

Robinhood Chain is bundled into every tier at no extra cost. Get a key at [madeonsol.com/pricing](https://madeonsol.com/pricing).

## Also available for Robinhood Chain

| Platform | Package |
|---|---|
| TypeScript SDK | `robinhood-chain-sdk` (npm) |
| Rust SDK | `robinhood-chain` (crates.io) |
| MCP server | `mcp-server-robinhood-chain` (npm) |

## Links

- Robinhood Chain hub — https://madeonsol.com/robinhood
- Pricing & free key — https://madeonsol.com/pricing
- API docs — https://madeonsol.com/api-docs

## License

MIT
