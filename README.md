# robinhood-chain

[![PyPI](https://img.shields.io/pypi/v/robinhood-chain?style=flat-square)](https://pypi.org/project/robinhood-chain/)
[![Python](https://img.shields.io/pypi/pyversions/robinhood-chain?style=flat-square)](https://pypi.org/project/robinhood-chain/)
[![Downloads](https://img.shields.io/pypi/dm/robinhood-chain?style=flat-square)](https://pypi.org/project/robinhood-chain/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)

> ⭐ **[Star on GitHub](https://github.com/madeonsol/robinhood-chain-python)** · 📂 **[Examples](./examples/)** · 📚 **[API docs](https://madeonsol.com/api-docs)** · 🏦 **[Robinhood Chain hub](https://madeonsol.com/robinhood)**

**Robinhood Chain SDK for Python — EVM-native trading intelligence, chain id 4663.**

Live KOL trades and consensus clustering, token discovery, launch-bundle detection, early-buyer quality, holders and live on-chain risk, deployer reputation with alerts and trajectory, the Uniswap v2/v3/v4 trade tape, OHLC candles, batch token lookups, smart-money wallet ranking, and four push rule engines (copy-trade, price alerts, KOL coordination, first touches) — for [Robinhood Chain](https://madeonsol.com/robinhood) (an Arbitrum Orbit L2, chain id **4663**), served from our self-hosted node. Everything is EVM-native: lowercase `0x` addresses (`token_address`), `eth_amount`, `tx_hash`, `block_number`, `net_flow_eth`. No Solana field names.

Robinhood Chain coverage is bundled into **every** MadeOnSol tier at no extra cost — the same `msk_` API key and the same base URL. Free tier: 200 requests/day, no card. Get a key at [madeonsol.com/pricing](https://madeonsol.com/pricing).

> **New in 0.8.0 — `holder_growth`: who arrived and who left.** `client.token_holders(address)` (`HolderGrowth` / `HolderGrowthWindow` TypedDicts) now returns `holder_growth` on `GET /rhc/tokens/{address}/holders`: `{ "1h", "24h", "7d" }` × `{ cutoff_block, entered, entered_still_holding, exited, net }`. *entered* = addresses whose first `Transfer` of the token landed at-or-after the window's cutoff block (any current balance); *entered_still_holding* = those still non-zero; *exited* = pre-existing holders whose last movement in the window left them at zero; *net* ≈ the change in `holder_count`. Pools and burn addresses are excluded from every count. This exists because RHC balances are folded from ERC-20 Transfer logs on our own node — the fold keeps first-seen and last-moved blocks per address and retains zero-balance rows — so it is a direct read, not an estimate; the Solana census is a point-in-time ledger scan with no history and cannot answer this. A window is `null` (never 0) only when the chain had no ingested trades in it; the whole block is `null` only if the growth read failed. Sanity check from ship day: a token launched that morning showed 593 entered / 560 still holding over 24h, and `holder_count` was exactly 560.

> **New in 0.6.0 — wallet intelligence.** Ten new operations covering the Robinhood Chain wallet surface, which had no SDK binding at all until now: `wallet()`, `wallet_pnl()`, `wallet_positions()`, `wallet_trades()`, plus the watchlist — `wallet_tracker_list()`, `wallet_tracker_add()`, `wallet_tracker_remove()`, `wallet_tracker_relabel()`, `wallet_tracker_trades()` and `wallet_tracker_summary()`. Everything is **ETH**-denominated, and cost basis is FIFO over a rolling 90-day window — `cost_basis_observable_from` names the date the window opens, so a position opened before it reads as a sell with no matching buy. The profile / PnL / positions trio shares ONE snapshot cache server-side, so calling all three on an address costs roughly one computation rather than three; `cache_hit` says which call paid for it. Watchlist quotas are **per chain** (PRO 50 / ULTRA 100 / BUSINESS 500 RHC wallets), independent of your Solana list.

> **New in 0.7.0 — keyless x402 mode.** `RobinhoodClient(private_key="0x…")`: any EVM wallet holding **USDG on Robinhood Chain** can call the 10 keyless endpoints (`kol_feed`, `kol_hot_tokens`, `kol_leaderboard`, `token`, `token_buyer_quality`, `token_kol_consensus`, `token_risk`, `token_holders`, `wallet_pnl`, `deployer_alerts`) with no API key — the client handles the 402 → sign EIP-3009 `transferWithAuthorization` (EIP-712 domain `{Global Dollar, 1, 4663}`) → retry flow, one payment per call, from $0.04. The wallet needs USDG but no ETH (our facilitator relays gas). `client.last_payment` carries the on-chain settlement (`transaction`, `payer`). Needs the extra `pip install "robinhood-chain[x402]"` (eth-account). Any other method on a keyless client raises `KeylessNotAvailableError` — it names the rail, it never silently downgrades. Sync + async both supported.

> **New in 0.5.0 — real-time WebSocket streaming.** A managed stream client (`client.stream()`) over `wss://madeonsol.com/ws/v1/stream` with auto-reconnect, 24h-token refresh and typed callbacks, covering all six RHC channels — the KOL tape, the full DEX firehose, and the four rule-engine push channels. Channel names are the **canonical** server registry (`rhc:dex_trades`, not the `rhc:trades` spelling some 0.4.0 SDKs used — the server still accepts that as a deprecated alias). Needs the `stream` extra: `pip install "robinhood-chain[stream]"`. See [Real-time streaming](#real-time-streaming-new-in-050).

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

`GET https://madeonsol.com/api/v1/rhc/kol/feed` → every buy/sell from tracked KOLs' verified EVM wallets on Robinhood Chain, attributed to the effective trading account (`tx.from`, or the ERC-4337 userOp sender when the trade was bundled), sub-second from execution, enriched with live MC and `mc_multiple_since_trade` ("did the call run").

## Authentication

Two modes. **Key mode** — Bearer `msk_` API key, the same key and base URL as the Solana MadeOnSol API, all 52 operations. **Keyless x402 mode** (0.7.0) — `private_key=` of an EVM wallet holding USDG on Robinhood Chain pays per call on the 10-endpoint rail documented at [madeonsol.com/robinhood/x402](https://madeonsol.com/robinhood/x402); needs `pip install "robinhood-chain[x402]"`.

```python
import os
from robinhood_chain import RobinhoodClient

# Keyless: USDG wallet on chain 4663, no signup. Read the key from the environment.
agent = RobinhoodClient(private_key=os.environ["RHC_PAYER_KEY"])
risk = agent.token_risk("0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec")   # NVDA, $0.02
print(risk["score"], agent.last_payment["transaction"])              # settlement tx on Robinhood Chain
```

```python
import os
from robinhood_chain import RobinhoodClient

client = RobinhoodClient(api_key=os.environ["MADEONSOL_API_KEY"])
```

## Endpoints — the 52 Robinhood Chain operations

Base URL `https://madeonsol.com/api/v1`. All addresses are lowercase `0x` (40 hex). Everything is a GET except the two batch POSTs and the four rule engines, which are full CRUD.

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
| `client.token_top_traders(address, limit=, offset=)` | `GET /api/v1/rhc/tokens/{address}/top-traders` | PRO+ |
| `client.token_flow(address, window=)` | `GET /api/v1/rhc/tokens/{address}/flow` | PRO+ |
| `client.token_peak_history(address, window=, curve=)` | `GET /api/v1/rhc/tokens/{address}/peak-history` | PRO+ |
| `client.token_risk(address)` | `GET /api/v1/rhc/tokens/{address}/risk` | PRO+ |
| `client.token_holders(address, limit=, offset=)` — exact holders + concentration from `Transfer` logs (check `verified`), plus `holder_growth` (`"1h"` / `"24h"` / `"7d"`: `entered`, `entered_still_holding`, `exited`, `net` ≈ Δ `holder_count`; pools/burns excluded, a window is `None` only when the chain had no ingested trades in it) | `GET /api/v1/rhc/tokens/{address}/holders` | PRO+ |

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

### Rule engines — push, not polling

Four server-side rule engines that watch the RHC tape for you and deliver over webhook or WebSocket. **Every quota is per chain** — configuring RHC rules never consumes your Solana budget. `webhook_secret` is returned exactly once on create; payloads are signed HMAC-SHA256 over `<timestamp>.<body>` in the `X-MadeOnSol-Signature` header.

| Method | Route | Tier |
|---|---|---|
| `client.copytrade_subscriptions_list()` | `GET /api/v1/rhc/copytrade/subscriptions` | PRO+ |
| `client.copytrade_subscriptions_create(source_wallets=, sizing_amount=, name=, min_trade_eth=, only_action=, sizing_mode=, delivery_mode=, webhook_url=)` | `POST /api/v1/rhc/copytrade/subscriptions` | PRO+ |
| `client.copytrade_subscriptions_get(subscription_id)` | `GET /api/v1/rhc/copytrade/subscriptions/{id}` | PRO+ |
| `client.copytrade_subscriptions_update(subscription_id, **fields)` | `PATCH /api/v1/rhc/copytrade/subscriptions/{id}` | PRO+ |
| `client.copytrade_subscriptions_delete(subscription_id)` | `DELETE /api/v1/rhc/copytrade/subscriptions/{id}` | PRO+ |
| `client.copytrade_signals(subscription_id=, since=, limit=)` | `GET /api/v1/rhc/copytrade/signals` | PRO+ |
| `client.price_alerts_list()` | `GET /api/v1/rhc/price-alerts` | PRO+ |
| `client.price_alerts_create(token_address=, drop_pct=, name=, recovery_pct=, delivery_mode=, webhook_url=)` | `POST /api/v1/rhc/price-alerts` | PRO+ |
| `client.price_alerts_get(alert_id)` | `GET /api/v1/rhc/price-alerts/{id}` | PRO+ |
| `client.price_alerts_update(alert_id, **fields)` | `PATCH /api/v1/rhc/price-alerts/{id}` | PRO+ |
| `client.price_alerts_delete(alert_id)` | `DELETE /api/v1/rhc/price-alerts/{id}` | PRO+ |
| `client.price_alerts_events(alert_id=, event_type=, since=, limit=)` | `GET /api/v1/rhc/price-alerts/events` | PRO+ |
| `client.coordination_alerts_list()` | `GET /api/v1/rhc/kol/coordination/alerts` | PRO+ |
| `client.coordination_alerts_create(min_kols=, window_minutes=, min_score=, cooldown_min=, score_jump_break=, min_mc_usd=, max_mc_usd=, delivery_mode=, webhook_url=)` | `POST /api/v1/rhc/kol/coordination/alerts` | PRO+ |
| `client.coordination_alerts_get(rule_id)` | `GET /api/v1/rhc/kol/coordination/alerts/{id}` | PRO+ |
| `client.coordination_alerts_update(rule_id, **fields)` | `PATCH /api/v1/rhc/kol/coordination/alerts/{id}` | PRO+ |
| `client.coordination_alerts_delete(rule_id)` | `DELETE /api/v1/rhc/kol/coordination/alerts/{id}` | PRO+ |
| `client.first_touch_subscriptions_list()` | `GET /api/v1/rhc/kol/first-touches/subscriptions` | ULTRA+ |
| `client.first_touch_subscriptions_create(name=, filters=, delivery_mode=, webhook_url=)` | `POST /api/v1/rhc/kol/first-touches/subscriptions` | ULTRA+ |
| `client.first_touch_subscriptions_get(subscription_id)` | `GET /api/v1/rhc/kol/first-touches/subscriptions/{id}` | ULTRA+ |
| `client.first_touch_subscriptions_update(subscription_id, **fields)` | `PATCH /api/v1/rhc/kol/first-touches/subscriptions/{id}` | ULTRA+ |
| `client.first_touch_subscriptions_delete(subscription_id)` | `DELETE /api/v1/rhc/kol/first-touches/subscriptions/{id}` | ULTRA+ |

Copy-trade rules are **ETH**-denominated and carry no MC band — the RHC notify payload has no market cap, so a band could only be a per-event DB lookup in the hot path of a ~3.3M trades/day chain, or a filter that silently never matches.

**RHC price alerts are polled (~15s), not live.** `rhc_token_prices` is written by the RHC ingester on a separate box and emits no `pg_notify`, so there is nothing to react to. Effective latency is that interval plus the token's own price-update cadence — do **not** assume parity with the Solana alerts, which are sub-second. The create response says so in its `evaluation` block. `token_address`, `drop_pct` and `recovery_pct` are immutable once set; delete and recreate to retune.

**Coordination scoring is comparable to Solana, not identical.** The shared v1 scorer runs and `quality` is a real KOL win-rate, but `earliness` is **defaulted** — RHC has no early-entry equivalent. Every fired signal records which components were real in `score_inputs`.

**First-touch filters are not the Solana set.** RHC has no scout score, so `min_scout_tier` and `min_n_touches` do not exist here rather than silently matching nothing; `min_kol_winrate` and `strategy` are the quality gates. Unknown filter keys are rejected with a 400. On update, `filters` is a whole-object **replace**, not a merge.

#### Clearing a field: `NULL` vs omitting it

Omitting a keyword leaves the field untouched; passing `NULL` sets it to JSON `null`. Python's `None` cannot mean both, and the routes validate with strict schemas that reject an explicit `null` on non-nullable fields. Only `name`, `webhook_url`, `min_mc_usd` and `max_mc_usd` are nullable on the wire.

```python
from robinhood_chain import RobinhoodClient, NULL

client = RobinhoodClient(api_key="msk_...")

# Follow three wallets, 0.05 ETH per copy, pushed over WebSocket
sub = client.copytrade_subscriptions_create(
    name="degen desk",
    source_wallets=["0xaaa...", "0xbbb...", "0xccc..."],
    min_trade_eth=0.01,
    sizing_mode="fixed",
    sizing_amount=0.05,
    delivery_mode="websocket",
)

# Catch up on anything the webhook missed
sigs = client.copytrade_signals(subscription_id=sub["subscription"]["id"], limit=100)

# Pause the rule and drop its label — is_active is untouched by the NULL
client.copytrade_subscriptions_update(sub["subscription"]["id"], name=NULL, is_active=False)

# Alert me if this token drops 30% from where it is right now
client.price_alerts_create(
    token_address="0xToken...", drop_pct=30, recovery_pct=15,
    webhook_url="https://example.com/hook",
)
```

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
# Every Uniswap v2/v3/v4 swap — trader_eoa is the effective trading account
# (tx.from, or the ERC-4337 userOp sender when bundled), never the router or the bundler
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

    # So do the rule-engine writes (POST / PATCH / DELETE)
    rules = await a.coordination_alerts_list()
    print(len(rules["rules"]), "coordination rules")

asyncio.run(main())
```

## Real-time streaming *(new in 0.5.0)*

Managed WebSocket stream — auto-reconnect with backoff, 24h-token auto-refresh (`POST /api/v1/stream/token` under the hood), heartbeat liveness, and typed callbacks. Needs the `stream` extra:

```bash
pip install "robinhood-chain[stream]"
```

```python
import asyncio
from robinhood_chain import RobinhoodClient

client = RobinhoodClient(api_key="msk_...")

async def main():
    stream = client.stream()

    @stream.on("rhc:kol_trade")
    async def on_kol_trade(data, evt):
        print(data["kol_name"], data["action"], data["token_address"], data["eth_amount"], "ETH")

    @stream.on("rhc:kol:first_touch")
    async def on_first_touch(data):
        print("FIRST TOUCH", data["token_address"])

    @stream.on("warning")
    async def on_warning(msg):
        # e.g. code == "channels_rejected": you asked for a channel that does
        # not exist or that your tier cannot hold — msg["rejected"] carries a
        # per-channel reason, msg["valid_channels"] the full list.
        print("stream warning:", msg)

    stream.subscribe(["rhc:kol_trades", "rhc:kol:first_touches"])
    await stream.run()   # blocks; manages connection + reconnects

asyncio.run(main())
```

All six RHC channels ride the main stream endpoint (`wss://madeonsol.com/ws/v1/stream`). Unlike Solana, the RHC DEX firehose has **no separate endpoint** — it is the `rhc:dex_trades` channel here. The stream token itself is PRO+.

| Channel | What it delivers (event names) | Tier |
|---|---|---|
| `rhc:kol_trades` | Every tracked-KOL trade on chain 4663 (`rhc:kol_trade`) | PRO+ |
| `rhc:dex_trades` | The full DEX firehose — every attributed Uniswap v2/v3/v4 swap, ~40–55/s at tip (`rhc:dex_trade`) | **ULTRA+** |
| `rhc:copytrade:signals` | Your copy-trade rule fires, user-scoped (`rhc:copytrade:signal`) | PRO+ |
| `rhc:price_alert:events` | Your price-alert dips/recoveries, user-scoped (`rhc:price_alert:dip` / `rhc:price_alert:recovery`) — ~15s polled server-side, **not** sub-second | PRO+ |
| `rhc:kol:coordination` | Coordination-alert fires (`rhc:kol:coordination`) | PRO+ |
| `rhc:kol:first_touches` | Broadcast first-touch feed (`rhc:kol:first_touch`) — the **channel** is PRO+; ULTRA gates the first-touch *subscription* CRUD endpoints, not this broadcast | PRO+ |

Lifecycle events: `open`, `close`, `reconnect`, `subscribed`, `heartbeat`, `warning`, `error`, plus `"*"` for every data event. Deprecated spelling: the server accepts `rhc:trades` as an alias of `rhc:dex_trades` (some 0.4.0 SDKs shipped it); this SDK uses only canonical names.

**Invalid channels are never silent.** If a subscribe names an unknown or tier-gated channel, the server answers with a `{type: "warning", code: "channels_rejected", rejected, valid_channels}` frame. The stream client delivers it to your `on("warning")` handler — and if you registered none, surfaces it via Python's `warnings.warn` so a rejected channel can't masquerade as a quiet market.

If you'd rather hand-roll the WebSocket, `client.stream_token()` (sync) / `client.aclient().stream_token()` (async) returns `{"token", "expires_at", "next_refresh_at", "ws_url", "channels", ...}` — connect to `{ws_url}?token={token}` and send `{"type": "subscribe", "channels": [...]}`.

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
| PRO+ | + DEX trade tape, token discovery, candles, KOL consensus, top-traders, flow, peak-history, risk, holders, deployer-hunter history, alpha-wallets, and the copy-trade / price-alert / coordination rule engines |
| ULTRA | + full alert pagination (`limit` above 50), KOL `evm_address` on first-touches, full bundle cohort + consensus wallet lists, first-touch push subscriptions |

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
