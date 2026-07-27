# robinhood-chain

[![PyPI](https://img.shields.io/pypi/v/robinhood-chain?style=flat-square)](https://pypi.org/project/robinhood-chain/)
[![Python](https://img.shields.io/pypi/pyversions/robinhood-chain?style=flat-square)](https://pypi.org/project/robinhood-chain/)
[![Downloads](https://img.shields.io/pypi/dm/robinhood-chain?style=flat-square)](https://pypi.org/project/robinhood-chain/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)

> ⭐ **[Star on GitHub](https://github.com/madeonsol/robinhood-chain-python)** · 📂 **[Examples](./examples/)** · 📚 **[API docs](https://madeonsol.com/api-docs)** · 🏦 **[Robinhood Chain hub](https://madeonsol.com/robinhood)**

**Robinhood Chain SDK for Python — EVM-native trading intelligence, chain id 4663.**

Live KOL trades and consensus clustering, token discovery, launch-bundle detection, early-buyer quality, deployer reputation with alerts and trajectory, the Uniswap v2/v3/v4 trade tape, OHLC candles, batch token lookups, and smart-money wallet ranking — for [Robinhood Chain](https://madeonsol.com/robinhood) (an Arbitrum Orbit L2, chain id **4663**), served from our self-hosted node. Everything is EVM-native: lowercase `0x` addresses (`token_address`), `eth_amount`, `tx_hash`, `block_number`, `net_flow_eth`. No Solana field names.

Robinhood Chain coverage is bundled into **every** MadeOnSol tier at no extra cost — the same `msk_` API key and the same base URL. Free tier: 200 requests/day, no card. Get a key at [madeonsol.com/pricing](https://madeonsol.com/pricing).

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

Bearer `msk_` API key — the same key and base URL as the Solana MadeOnSol API. This package also serves the **x402-Py key-mode** surface: Bearer auth only. Robinhood Chain does have a keyless x402 pay-per-call rail (a narrow 6-endpoint subset — see [madeonsol.com/robinhood/x402](https://madeonsol.com/robinhood/x402)), but its signing path is not ported to this SDK.

```python
import os
from robinhood_chain import RobinhoodClient

client = RobinhoodClient(api_key=os.environ["MADEONSOL_API_KEY"])
```

## Endpoints — the 25 Robinhood Chain routes

Base URL `https://madeonsol.com/api/v1`. All addresses are lowercase `0x` (40 hex).

### KOL intelligence

| Method | Route | Tier |
|---|---|---|
| `client.kol_feed(limit=, before=, action=, kol=, min_eth=)` | `GET /api/v1/rhc/kol/feed` | BASIC |
| `client.kol_leaderboard(period=, limit=)` | `GET /api/v1/rhc/kol/leaderboard` | BASIC |
| `client.kol_hot_tokens(window=)` | `GET /api/v1/rhc/kol/hot-tokens` | BASIC |
| `client.kol_coordination(period=, min_kols=, limit=, min_mc_usd=, max_mc_usd=)` | `GET /api/v1/rhc/kol/coordination` | BASIC |
| `client.kol_first_touches(limit=, since=, before=, min_eth=, token_age_max_min=, launchpad=, min_mc_usd=, max_mc_usd=)` | `GET /api/v1/rhc/kol/first-touches` | BASIC |
| `client.kol_wallet(wallet)` | `GET /api/v1/rhc/kol/{wallet}` | BASIC |

### Trades & tokens

| Method | Route | Tier |
|---|---|---|
| `client.trades(limit=, token=, dex=, action=, min_eth=, before=)` | `GET /api/v1/rhc/trades` | PRO+ |
| `client.tokens(limit=, sort=, min_mc_usd=, min_liquidity_usd=, launchpad=)` | `GET /api/v1/rhc/tokens` | PRO+ |
| `client.token(address)` | `GET /api/v1/rhc/tokens/{address}` | BASIC |
| `client.token_batch(addresses)` — max **50** | `POST /api/v1/rhc/token/batch` | BASIC |
| `client.token_candles(address, limit=, from_=, to=)` | `GET /api/v1/rhc/tokens/{address}/candles` | PRO+ |
| `client.token_kol_consensus(address)` | `GET /api/v1/rhc/tokens/{address}/kol-consensus` | PRO+ |
| `client.token_buyer_quality(address)` | `GET /api/v1/rhc/tokens/{address}/buyer-quality` | BASIC |
| `client.tokens_batch_buyer_quality(addresses)` — max **20** | `POST /api/v1/rhc/tokens/batch/buyer-quality` | BASIC |
| `client.token_bundle(address)` | `GET /api/v1/rhc/tokens/{address}/bundle` | BASIC |

### Deployer hunter

| Method | Route | Tier |
|---|---|---|
| `client.deployer_hunter_leaderboard(sort=, tier=, min_tokens=, limit=, offset=)` | `GET /api/v1/rhc/deployer-hunter/leaderboard` | BASIC |
| `client.deployer_hunter_alerts(deployer_tier=, priority=, alert_type=, launchpad=, min_mc=, include_untradeable=, since=, before=, limit=, offset=)` | `GET /api/v1/rhc/deployer-hunter/alerts` | BASIC |
| `client.deployer_hunter_best_tokens(period=, limit=)` | `GET /api/v1/rhc/deployer-hunter/best-tokens` | BASIC |
| `client.deployer_hunter_recent_bonds(deployer_tier=, min_peak=, limit=)` | `GET /api/v1/rhc/deployer-hunter/recent-bonds` | BASIC |
| `client.deployer_hunter_stats()` | `GET /api/v1/rhc/deployer-hunter/stats` | BASIC |
| `client.deployer_hunter_profile(address)` | `GET /api/v1/rhc/deployer-hunter/{address}` | BASIC |
| `client.deployer_hunter_trajectory(address)` | `GET /api/v1/rhc/deployer-hunter/{address}/trajectory` | BASIC |
| `client.deployer_hunter_tokens(address, limit=, offset=, sort=)` | `GET /api/v1/rhc/deployer-hunter/{address}/tokens` | BASIC |
| `client.deployer_hunter_history(address, limit=, offset=)` | `GET /api/v1/rhc/deployer-hunter/{address}/history` | PRO+ |

### Alpha wallets

| Method | Route | Tier |
|---|---|---|
| `client.alpha_wallets(classification=, identity=, min_memecoin_share=, sort=, limit=, offset=, ...)` | `GET /api/v1/rhc/alpha-wallets` | PRO+ |

### Deployer tiers — what `elite` actually means

`elite` / `good` are earned on the **$100K `runner_rate`** and require 24h of deployer history (migrations 267 + 269). The $40K bar proved farmable by operators mass-relaunching one ticker across rotating wallets, so `graduation_rate` — which still means "share of launches that reached a $40K+ peak MC", and is still returned everywhere — **no longer determines the tier**. `spammer` is the one exception and still keys off `graduation_rate`, because detecting trash is a different question from detecting quality.

`client.deployer_hunter_stats()` returns the live `tier_rules`, `graduation_definition` ($40K) and `runner_definition` ($100K), so you never have to guess what a label currently means.

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

### KOL coordination & first touches

```python
# Coordination — the cohort BEHIND a hot token: who bought, who already exited,
# how fast they piled in. signal is 'accumulating' or 'distributing'.
co = client.kol_coordination(period="6h", min_kols=3, limit=10, max_mc_usd=250_000)
for tok in co["coordination"]:
    print(tok["token_symbol"], tok["kol_count"], "KOLs",
          tok["signal"], tok["net_eth"], "ETH net",
          tok["holders_count"], "holding /", tok["exited_count"], "exited",
          tok["time_to_consensus_sec"], "s to consensus")
    for k in tok["kols"]:
        print("   ", k["name"], k["buy_eth"], "ETH in", "EXITED" if k["exited"] else "holding")

# First touches — the FIRST time any tracked KOL bought a token (discovery signal).
# token_age_max_min isolates genuinely early calls; poll forward with `since`.
ft = client.kol_first_touches(limit=25, token_age_max_min=30, min_eth=0.05)
for e in ft["events"]:
    print(e["token_symbol"], e["first_kol"]["name"],
          e["eth_amount"], "ETH at", e["market_cap_usd_at_first_buy"], "MC",
          "→ peak", e["peak_mc_usd"], e["tx_hash"])
# BASIC clamps limit to 20; first_kol['evm_address'] is ULTRA/BUSINESS only.
# Page back with ft["next_before"], or poll forward with since=<newest first_buy_at>.
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

### Batch lookups

```python
watchlist = ["0xaaa...", "0xbbb...", "0xccc..."]

# Up to 50 tokens in ONE call — metadata, live price/MC/FDV/liquidity, peak MC,
# and the deployer reputation block. Set-based server-side, not a fan-out.
batch = client.token_batch(watchlist)
for tok in batch["tokens"]:
    if not tok["found"]:          # every REQUESTED address is echoed back
        print(tok["address"], "not indexed on Robinhood Chain")
        continue
    print(tok["symbol"], tok["market_cap_usd"], tok["liquidity_usd"], tok["peak_mc_usd"])

# Early-buyer quality for up to 20 tokens. The cap is 20, NOT the Solana 50:
# RHC buyer-quality is a per-token cohort computation, not one set-based query.
# A token that fails to score comes back as an entry with an "error" key rather
# than failing the whole batch.
bq = client.tokens_batch_buyer_quality(watchlist[:20])
for r in bq["tokens"]:
    if "error" in r:
        print(r["token_address"], "score failed:", r["error"])
    else:
        print(r["token_address"], r["quality"]["score"], r["quality"]["signal"])
print(bq["scored"], "of", bq["requested"], "scored; cap is", bq["max_addresses"])
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
# runner_rate = share reaching $100K+ (most RHC launchpads are direct-to-DEX).
# The elite/good tier rides runner_rate + 24h of deployer history; graduation_rate
# is still returned but no longer sets the tier (only `spammer` still uses it).
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

### Deployer alerts, stats & the chain-wide picture

```python
# Live deployer signal feed. alert_type is 'new_deploy' | 'graduated',
# priority is 'high' | 'medium' (RHC has no bonded/kol_buy/low).
alerts = client.deployer_hunter_alerts(deployer_tier="elite", alert_type="new_deploy", limit=50)
print(alerts["tradability_filter"])   # e.g. 'liquidity_usd >= $100'
for a in alerts["alerts"]:
    print(a["token_symbol"], a["tier"], a["mc_at_alert"], "MC",
          a["liquidity_usd"], "liq", a["event_at"])
    if a["tier_is_stale"]:
        print("   was", a["tier_at_alert"], "when the alert fired, now", a["tier"])

# Poll forward: pass the newest event_at back as `since` to get only what's new.
new = client.deployer_hunter_alerts(since=alerts["next_event_at"])
```

Two behaviour changes worth knowing about this feed (2026-07-25):

- **A tradability filter is ON by default.** Alerts whose token has `liquidity_usd` under **$100** — or unknown liquidity, which on RHC usually means a drained pool — are dropped, because a $45K-MC alert on a token with $68 of liquidity is not a signal. Pass `include_untradeable=True` for the raw tape (archive/leaderboard tooling); the active setting is echoed as `tradability_filter`.
- **`tier` is resolved at read time.** It is the deployer's *current* tier, not the snapshot taken when the alert fired — that snapshot comes back as `tier_at_alert`, with `tier_is_stale` set when the two disagree. `deployer_tier=` filters on the resolved value, and `message` is restated in terms of the $100K runner rate that now sets the tier.

```python
# Chain-wide reputation summary — the denominator for "is this deployer rare?"
st = client.deployer_hunter_stats()
print(st["total_deployers"], "deployers,", st["reputable_deployers"], "reputable")
print(st["by_tier"], st["spam_token_share"], st["alerts_24h"], "alerts/24h")
print(st["tier_rules"])              # the ACTIVE thresholds — elite/good ride runner_rate
print(st["graduation_definition"])   # 'peak market cap >= $40,000'
print(st["runner_definition"])       # 'peak market cap >= $100,000'

# Best tokens from deployers worth tracking (elite/good only, ranked by peak MC)
best = client.deployer_hunter_best_tokens(period="7d", limit=10)
for tokn in best["tokens"]:
    print(tokn["symbol"], tokn["peak_mc_usd"], "peak", tokn["deployer"]["tier"])
if best.get("truncated"):
    print("top-N drawn from the 1000 most recent launches, not the whole period")

# Recent graduations — the $40K peak-MC milestone (NOT a bonding curve; RHC
# launchpads are direct-to-DEX). min_peak only raises that floor.
bonds = client.deployer_hunter_recent_bonds(deployer_tier="good", min_peak=75_000, limit=25)
for tokn in bonds["tokens"]:
    print(tokn["symbol"], tokn["peak_mc_usd"], tokn["peak_mc_at"], tokn["deployer_tier"])
```

### One deployer, in depth

```python
dep = "0x1111111111111111111111111111111111111111"

# Getting better or worse? Streaks, rolling 10-launch success rate, best/worst
# stretches, deploy cadence, and a trend of 'improving' | 'declining' | 'stable'.
# Success here is the $40K graduation milestone (echoed as success_metric) — NOT
# the $100K runner bar that sets tiers, because $100K is too rare to form a curve.
tj = client.deployer_hunter_trajectory(dep)
if tj["is_deployer"]:
    t = tj["trajectory"]
    print(tj["success_metric"], t["trend"], t["current_streak"],
          "longest hit streak", t["longest_bond_streak"],
          "avg", t["avg_days_between_deploys"], "days between deploys")

# Full paginated launch history with live + peak MC.
# ⚠️ sort='peak_mc_usd' sorts the REQUESTED PAGE only (sort_scope: 'page') —
# use deployer_hunter_best_tokens() for a real cross-deployer ranking.
page = client.deployer_hunter_tokens(dep, limit=100, offset=0, sort="first_seen_at")
for tokn in page["tokens"]:
    print(tokn["symbol"], tokn["first_seen_at"], tokn["peak_mc_usd"], tokn["liquidity_usd"])
print(page["total"], "total,", "more pages" if page["has_more"] else "end")

# PRO+: the same history with graduation detail and an exact total.
hist = client.deployer_hunter_history(dep, limit=500)
for tokn in hist["tokens"]:
    print(tokn["symbol"], tokn["is_graduated"], tokn["graduated_at"], tokn["graduated_pool"])
```

## Async

Every endpoint has an async twin via `client.aclient()` — same signature, returns a coroutine:

```python
import asyncio
from robinhood_chain import RobinhoodClient

client = RobinhoodClient(api_key="msk_...")

async def main():
    a = client.aclient()
    feed = await a.kol_feed(limit=10)
    print(feed["count"])

    # Batch POSTs have async twins too
    batch = await a.token_batch(["0xaaa...", "0xbbb..."])
    print(batch["found"], "of", batch["requested"], "found")

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
| BASIC (free) | KOL feed/leaderboard/hot-tokens/coordination/first-touches/profile, token snapshot + batch, buyer-quality (single + batch), bundle, deployer-hunter leaderboard/alerts/best-tokens/recent-bonds/stats/profile/trajectory/tokens |
| PRO+ | + DEX trade tape, token discovery, candles, KOL consensus, deployer-hunter history, alpha-wallets |
| ULTRA | + full alert pagination (`limit` above 50), KOL `evm_address` on first-touches, full bundle cohort + consensus wallet lists |

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
