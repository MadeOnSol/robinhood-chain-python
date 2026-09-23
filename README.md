# robinhood-chain

[![PyPI](https://img.shields.io/pypi/v/robinhood-chain?style=flat-square)](https://pypi.org/project/robinhood-chain/)
[![Python](https://img.shields.io/pypi/pyversions/robinhood-chain?style=flat-square)](https://pypi.org/project/robinhood-chain/)
[![Downloads](https://img.shields.io/pypi/dm/robinhood-chain?style=flat-square)](https://pypi.org/project/robinhood-chain/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)

> ⭐ **[Star on GitHub](https://github.com/madeonsol/robinhood-chain-python)** · 📂 **[Examples](./examples/)** · 📚 **[API docs](https://madeonsol.com/api-docs)** · 🏦 **[Robinhood Chain hub](https://madeonsol.com/robinhood)**

**Robinhood Chain SDK for Python — EVM-native trading intelligence, chain id 4663.**

Live KOL trades and consensus clustering, token discovery, launch-bundle detection, early-buyer quality, holders and live on-chain risk, deployer reputation with alerts and trajectory, the Uniswap v2/v3/v4 trade tape, OHLC candles, batch token lookups, smart-money wallet ranking, and four push rule engines (copy-trade, price alerts, KOL coordination, first touches) — for [Robinhood Chain](https://madeonsol.com/robinhood) (an Arbitrum Orbit L2, chain id **4663**), served from our self-hosted node. Everything is EVM-native: lowercase `0x` addresses (`token_address`), `eth_amount`, `tx_hash`, `block_number`, `net_flow_eth`. No Solana field names.

Robinhood Chain coverage is bundled into **every** MadeOnSol tier at no extra cost — the same `msk_` API key and the same base URL. Free tier: 200 requests/day, no card (live feeds 5-min delayed; paid tiers are real-time). Get a key at [madeonsol.com/pricing](https://madeonsol.com/pricing).

> **New in 0.13.0 — named subscriptions: several independent subscriptions per socket.** `subscribe(channels, filters, sub_id="...")`, `update_subscription(sub_id, filters)`, `unsubscribe("sub-id")`, `get_subscriptions()` / `await list_subscriptions()`. Each named subscription has its own channels and filters (the server caps the total per connection, default included: PRO 5, ULTRA 10, BUSINESS 20); frames carry `evt["sub_id"]`; an event matching several subscriptions is delivered once per subscription (dedupe per `(sub_id, id)`). Resume is per subscription with one commit for the connection. The plain `subscribe(channels, filters)` API is unchanged. See "Named subscriptions" in the stream section.
> **Also in 0.13.0 — `rhc:token_prices` and enriched RHC trade payloads (WS Phase 2).** A tenth RHC channel, `rhc:token_prices` (PRO+, address-scoped): `stream.subscribe(["rhc:token_prices"], filters={"addresses": [...]})` (25 / 100 / 250 addresses per connection on PRO / ULTRA / BUSINESS, rejected above the cap) delivers one `snapshot: True` frame per address, then ticks derived from the RHC trade feed at most once per address per 250 ms, each with `quality` fresh | stale | unreliable and `quality_reason`; a stale or unreliable price is never delivered as fresh. `rhc:dex_trade` / `rhc:dex_trade_unattributed` frames now carry additive enrichment: exact `amount_in_raw` / `amount_out_raw` decimal strings (never floats — use `int()`), `token` + `quote` identity with decimals, `metadata_status`, `price_status` / `price_source` / `price_observed_at`, `mc_status` (why `mc_usd` is None) and `side` / `side_reason`. Every existing key keeps its name.

> **New in 0.12.0 — stream recovery: resume cursor, de-duplication, honest gaps.** The managed stream now tracks the cursor `{ instance, seq, ts }` of the last frame your handlers finished and resumes after it on every reconnect (the v1 `resume` request, with an automatic fallback to `replay_since_seq` / `replay_since_ts` on older servers). Delivery is at-least-once, de-duplicated by event `id`; new lifecycle events `cursor`, `replay`, `gap` (what could not be recovered — a `seq` gap is never loss) and `fatal`. Close codes are handled: 4001 re-fetches the token (bounded), 4002 waits ≥ 60 s instead of looping every second, 4003 stops, 4008 resumes; the backoff resets only after a `subscribed` ack. Every server `warning` frame is emitted (incl. `channels_rejected` / `channels_revoked`). `CHANNELS` now lists all nine RHC channels (adds `rhc:dex_trades_unattributed`, `rhc:new_tokens`, `rhc:token_locks`); `client.stream(**options)` passes `resume=`, `dedupe_size=`, `max_auth_retries=`, `connection_limit_backoff=` through; the handshake token is URL-encoded; `PriceAlertEvaluation` documents `mode: "event_driven"` plus `trigger` / `fallback_poll_seconds`. See the stream section's "Recovery" notes.

> **New in 0.11.0 — BREAKING for keyless (x402) mode only: an explicit payment policy is required (security fix, SDK-01).** Before, a keyless client signed whatever USDG amount and recipient a 402 challenge asked for. Now `RobinhoodClient(private_key=..., payment_policy=PaymentPolicy(pay_to=..., max_amount_atomic=..., max_total_amount_atomic=...))` is required (optional `timeout_seconds`, `authorization_ttl_seconds`, `before_payment`), and the client refuses before signing any challenge whose scheme, network (`eip155:4663`), asset (USDG), recipient or amount falls outside it. Use the canonical merchant address below and caps of at least `40000` (0.04 USDG) per call. The budget is per client instance (sync and its `aclient()` share it): it is not wallet-wide, not shared between processes, and resets when a new instance is created. A paid response that arrives after the payment deadline is still returned with its receipt. **API-key users: no change, no new config.** Keyless requires the default base URL `https://madeonsol.com`.

> **New in 0.10.0 — mutation calls are no longer retried automatically (security fix, SDK-02), plus token locks & vesting.** A lost response or transient network error after a `POST`/`PATCH`/`DELETE` (rule create, token rotation, watchlist change) used to retry automatically — which could duplicate a rule or rotate a token twice. Mutating calls (including the batch-read POST endpoints) now make exactly one attempt; `GET` retries/backoff and the keyless x402 flow are unchanged. If a mutating call fails, check current state before deciding whether to retry by hand. Also adds three RHC methods that were already live on the API but missing from this SDK: `client.token_locks(address)`, `client.token_lock_summary(address)`, `client.token_unlocks()` — the RHC twin of the Solana token-locks binding (PinkLock-compatible, HoodLock, Sablier v4, Team Finance-compatible, Titan, UNCX-compatible LP lockers; create-only, `withdrawn` always `None` since no RHC locker publishes a release/cancel event).
>
> **New in 0.9.1 — stream tokens never expire.** `POST /api/v1/stream/token` now returns the **same token on every call, forever** (server change of 2026-08-27). `expires_at` / `next_refresh_at` are **always `None`** now and kept only for wire compatibility; the response gained `rotated: bool` and `lifetime: str`. A token only stops working when the subscription lapses or you replace it with the new `client.stream_token(rotate=True)` (the previous value keeps working for 60 s). The server never rotates on its own and never sends `token_refresh` unless you rotated; a `4001` close means "mint again", never a timer. Preferred handshake auth is `Authorization: Bearer <token>` (`?token=` still works and is masked in access logs); RHC channels ride the same socket and token as Solana. `client.stream()` already fetched a token on every (re)connect and never read `expires_at`, so its behavior is unchanged — only its docs are.

> **New in 0.9.0 — tokenized equities + the rug signal.** Two endpoints that were live on the API but had no Python binding: `client.equities(sort=, limit=, symbol=, q=)` → `GET /rhc/equities` (**BASIC**, `EquitiesResponse` / `Equity` TypedDicts) lists every official Robinhood tokenized stock/ETF (NVDA, SPY, AAPL, …) with live price / MC / liquidity and 24h trades / ETH volume / buyer-seller split. **Identity is the issuer BEACON, never the name** — a token is listed only if its contract is an EIP-1967 beacon proxy on Robinhood's issuer beacon, read from our own node; on ship day there were 20 fake "GameStop • Robinhood Token" contracts and 8 fake NVDAs with the exact official suffix, and none appear here. `client.lp_events(limit=, token=, pool=, provider=, dex=, before=)` → `GET /rhc/lp-events` (**PRO+**, `LpEventsResponse` / `LpEvent`) is the liquidity **removals** feed — Uniswap v2/v3 `Burn` + v4 `ModifyLiquidity` with a negative delta on tracked pools, each row enriched with the token, the provider wallet, `provider_is_token_deployer` (the classic rug tell) and `provider_kol_name`. Removals ONLY: adds are not persisted, so an empty page means "no removals seen", never "no liquidity activity" — the `coverage` block says `adds_persisted: False`. Amounts are raw uint256 strings; v4 rows carry `liquidity` only. Cursor via `next_before`; the path alias `/rhc/tokens/{address}/lp-events` is the same feed with `token=` pinned. Data since 2026-08-05. Both are key-mode only (not on the keyless x402 rail).

> **New in 0.8.0 — `holder_growth`: who arrived and who left.** `client.token_holders(address)` (`HolderGrowth` / `HolderGrowthWindow` TypedDicts) now returns `holder_growth` on `GET /rhc/tokens/{address}/holders`: `{ "1h", "24h", "7d" }` × `{ cutoff_block, entered, entered_still_holding, exited, net }`. *entered* = addresses whose first `Transfer` of the token landed at-or-after the window's cutoff block (any current balance); *entered_still_holding* = those still non-zero; *exited* = pre-existing holders whose last movement in the window left them at zero; *net* ≈ the change in `holder_count`. Pools and burn addresses are excluded from every count. This exists because RHC balances are folded from ERC-20 Transfer logs on our own node — the fold keeps first-seen and last-moved blocks per address and retains zero-balance rows — so it is a direct read, not an estimate; the Solana census is a point-in-time ledger scan with no history and cannot answer this. A window is `null` (never 0) only when the chain had no ingested trades in it; the whole block is `null` only if the growth read failed. Sanity check from ship day: a token launched that morning showed 593 entered / 560 still holding over 24h, and `holder_count` was exactly 560.

> **New in 0.6.0 — wallet intelligence.** Ten new operations covering the Robinhood Chain wallet surface, which had no SDK binding at all until now: `wallet()`, `wallet_pnl()`, `wallet_positions()`, `wallet_trades()`, plus the watchlist — `wallet_tracker_list()`, `wallet_tracker_add()`, `wallet_tracker_remove()`, `wallet_tracker_relabel()`, `wallet_tracker_trades()` and `wallet_tracker_summary()`. Everything is **ETH**-denominated, and cost basis is FIFO over a rolling 90-day window — `cost_basis_observable_from` names the date the window opens, so a position opened before it reads as a sell with no matching buy. The profile / PnL / positions trio shares ONE snapshot cache server-side, so calling all three on an address costs roughly one computation rather than three; `cache_hit` says which call paid for it. Watchlist quotas are **per chain** (PRO 50 / ULTRA 100 / BUSINESS 500 RHC wallets), independent of your Solana list.

> **New in 0.7.0 — keyless x402 mode.** `RobinhoodClient(private_key="0x…", payment_policy=policy)`: any EVM wallet holding **USDG on Robinhood Chain** can call the 10 keyless endpoints (`kol_feed`, `kol_hot_tokens`, `kol_leaderboard`, `token`, `token_buyer_quality`, `token_kol_consensus`, `token_risk`, `token_holders`, `wallet_pnl`, `deployer_alerts`) with no API key — the client handles the 402 → sign EIP-3009 `transferWithAuthorization` (EIP-712 domain `{Global Dollar, 1, 4663}`) → retry flow, one payment per call, from $0.04. The wallet needs USDG but no ETH (our facilitator relays gas). `client.last_payment` carries the on-chain settlement (`transaction`, `payer`). Needs the extra `pip install "robinhood-chain[x402]"` (eth-account). Any other method on a keyless client raises `KeylessNotAvailableError` — it names the rail, it never silently downgrades. Sync + async both supported.

> **New in 0.5.0 — real-time WebSocket streaming.** A managed stream client (`client.stream()`) over `wss://madeonsol.com/ws/v1/stream` with auto-reconnect, token handling and typed callbacks, covering all six RHC channels — the KOL tape, the full DEX firehose, and the four rule-engine push channels. Channel names are the **canonical** server registry (`rhc:dex_trades`, not the `rhc:trades` spelling some 0.4.0 SDKs used — the server still accepts that as a deprecated alias). Needs the `stream` extra: `pip install "robinhood-chain[stream]"`. See [Real-time streaming](#real-time-streaming-new-in-050).

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

Two modes. **Key mode** — Bearer `msk_` API key, the same key and base URL as the Solana MadeOnSol API, all 54 operations. **Keyless x402 mode** (0.7.0) — `private_key=` of an EVM wallet holding USDG on Robinhood Chain pays per call on the 10-endpoint rail documented at [madeonsol.com/robinhood/x402](https://madeonsol.com/robinhood/x402); needs `pip install "robinhood-chain[x402]"`.

```python
import os
from robinhood_chain import RobinhoodClient, PaymentPolicy

# Keyless: USDG wallet on chain 4663, no signup. Read the key from the environment.
agent = RobinhoodClient(
    private_key=os.environ["RHC_PAYER_KEY"],
    payment_policy=PaymentPolicy(
        pay_to="0xb2Af9Ad9EE09dAc999ac5A6Db993739128b27F10",  # canonical MadeOnSol merchant (see below)
        max_amount_atomic=40_000,             # 0.04 USDG per authorization.
        max_total_amount_atomic=1_000_000,    # 1 USDG per client instance.
    ),
)
risk = agent.token_risk("0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec")   # NVDA; the USDG leg has a $0.04 floor
print(risk["score"], agent.last_payment["transaction"])              # settlement tx on Robinhood Chain
```

```python
import os
from robinhood_chain import RobinhoodClient

client = RobinhoodClient(api_key=os.environ["MADEONSOL_API_KEY"])
```

### Required payment policy (SDK-01 upgrade)

Keyless construction now requires a `PaymentPolicy`; API-key mode is unchanged. This is a
breaking keyless change. Configure the trusted `pay_to` independently of the HTTP challenge.

**Canonical MadeOnSol merchant address (USDG on Robinhood Chain, chain 4663):**
`0xb2Af9Ad9EE09dAc999ac5A6Db993739128b27F10`. It is pinned here (GitHub + registry
README) so you do not have to take it from a 402; https://madeonsol.com/api/x402/rhc
lists the same value as a second check. If a challenge names any other address the
client refuses to sign; that is the point of the policy. A rotation would ship as a
new package release with a changelog entry, never only in a 402.

The signer only accepts `exact` USDG on `eip155:4663`, contract
`0x5fc5360d0400a0fd4f2af552add042d716f1d168`. Both requests require HTTPS and
refuse redirects. Limits are positive Python integers or decimal strings in atomic units
(1 USDG = 1,000,000); floats/bools are rejected and challenge amounts must be strings.

`max_amount_atomic` caps a single authorization; `max_total_amount_atomic` caps the lifetime
of one client across sync threads and async calls. `authorized_amount_atomic` includes
reservations and signing attempts, including uncertain/failed outcomes once the signing
path was invoked. A denial/cancellation before signing releases only that unsigned reservation.
No automatic reset/refund exists. Budgets are per instance and not persistent or wallet-wide:
keep one long-lived client per allowance; separate processes need an external coordinator.

Optional `before_payment(proposal)` receives an immutable mapping; only literal `True`
approves. Async hooks are supported by async methods and refused by sync methods.
`timeout_seconds` defaults to 30; `authorization_ttl_seconds` defaults to 60 (1–300),
also bounded by the challenge. Authorizations start with 5 seconds of clock-skew tolerance.
A late signer result is never submitted. Async I/O has a whole-operation deadline;
synchronous HTTP uses per-phase timeouts capped by remaining time and checks the deadline
between steps. Synchronous hooks/signers cannot be forcibly interrupted. A timeout cannot
undo a submitted proof. Existing `timeout` still bounds each HTTP phase.

## Endpoints — the 54 Robinhood Chain operations

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
| `client.lp_events(limit=, token=, pool=, provider=, dex=, before=, action=)` — liquidity **removals** by default (v2/v3 `Burn` + v4 negative `ModifyLiquidity`); `action="add"\|"pool_created"\|"all"` opts into adds (kept 7 days) and pool creations (server 2026-09-23), rows carry `in_range` / `active_share` / `share_of_reserves` / `material`; raw uint256 string amounts, `provider_is_token_deployer` = rug tell | `GET /api/v1/rhc/lp-events` | PRO+ |
| `client.tokens(limit=, sort=, min_mc_usd=, min_liquidity_usd=, launchpad=)` | `GET /api/v1/rhc/tokens` | PRO+ |
| `client.equities(sort=, limit=, symbol=, q=)` — every official Robinhood tokenized stock/ETF; identity = issuer **beacon**, never the name; live price / MC / liquidity + 24h trades / ETH volume / buyers vs sellers; `sort` volume\|trades\|market_cap\|last_trade\|symbol, `limit` ≤ 300 | `GET /api/v1/rhc/equities` | BASIC |
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

**RHC price alerts are event-driven, but not sub-second.** Since 2026-09-15 alerts are evaluated as trades land on the `rhc:dex_trade` feed, with a price-table poll (every 5 s while the feed is degraded or a trade carried no market cap, every 60 s otherwise) and a trade-tape replay after a feed outage as safety nets. Latency is a few seconds (the chain trade flush is ~2 s) — do **not** assume parity with the Solana alerts, which are sub-second. The create response says so in its `evaluation` block (`mode: "event_driven"`, `trigger`, `fallback_poll_seconds`; `interval_seconds` kept for compatibility). `token_address`, `drop_pct` and `recovery_pct` are immutable once set; delete and recreate to retune.

**Coordination scoring is comparable to Solana, not identical.** The shared v1 scorer runs and `quality` is a real KOL win-rate, but `earliness` is **defaulted** — RHC has no early-entry equivalent. Every fired signal records which components were real in `score_inputs`.

**First-touch filters are not the Solana set.** RHC has no scout score, so `min_scout_tier` and `min_n_touches` do not exist here rather than silently matching nothing; `min_kol_winrate` and `strategy` are the quality gates. Unknown filter keys are rejected with a 400. On update, `filters` is a whole-object **replace**, not a merge.

#### Clearing a field: `NULL` vs omitting it

Omitting a keyword leaves the field untouched; passing `NULL` sets it to JSON `null`. Python's `None` cannot mean both, and the routes validate with strict schemas that reject an explicit `null` on non-nullable fields. Only `name`, `webhook_url`, `min_mc_usd` and `max_mc_usd` are nullable on the wire.

```python
from robinhood_chain import RobinhoodClient, NULL

client = RobinhoodClient(api_key="msk_...")

# Follow three TRACKED KOL wallets (the set behind /rhc/kol/wallets), 0.05 ETH
# per copy, pushed over WebSocket. Any 0x address is accepted, but only tracked
# wallets can ever fire: check sub["subscription"]["source_wallets_untracked"]
# and sub.get("warnings") (code "untracked_source_wallets") — added 2026-09-22.
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

### Tokenized equities & liquidity removals

```python
# Every beacon-verified Robinhood stock/ETF token, ranked by 24h ETH volume —
# identity is the issuer beacon, never the name, so the fake NVDA/GameStop contracts never show up
eq = client.equities(sort="volume", limit=20)
print(eq["identity"]["method"], eq["total_equities"])
for e in eq["equities"]:
    print(e["symbol"], e["name"], e["price_usd"], "MC", e["market_cap_usd"], e["trades_24h"], "trades", e["volume_eth_24h"], "ETH")
nvda = client.equities(symbol="NVDA")  # exact ticker, case-insensitive

# Rug watch — liquidity REMOVALS for one token (PRO+). Adds are never persisted:
# coverage["adds_persisted"] is False, so an empty page means "no removals seen".
lp = client.lp_events(token=addr, limit=50)
for ev in lp["events"]:
    if ev["provider_is_token_deployer"]:
        print("deployer pulled LP:", ev["tx_hash"], ev["dex"], ev["token_amount_raw"])  # raw uint256 string
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

Managed WebSocket stream — auto-reconnect with backoff, token fetch on every (re)connect (`POST /api/v1/stream/token` under the hood — stream tokens **never expire** since 2026-08-27, so there is no refresh timer), heartbeat liveness, and typed callbacks. Needs the `stream` extra:

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

All fourteen RHC channels ride the main stream endpoint (`wss://madeonsol.com/ws/v1/stream`). Unlike Solana, the RHC DEX firehose has **no separate endpoint** — it is the `rhc:dex_trades` channel here. The stream token itself is PRO+.

| Channel | What it delivers (event names) | Tier |
|---|---|---|
| `rhc:kol_trades` | Every tracked-KOL trade on chain 4663 (`rhc:kol_trade`) | PRO+ |
| `rhc:dex_trades` | The full DEX firehose — every attributed Uniswap v2/v3/v4 swap, ~40–55/s at tip (`rhc:dex_trade`) | **ULTRA+** |
| `rhc:dex_trades_unattributed` | Trades on pools with no single "token" side, e.g. WETH/USDG (`rhc:dex_trade_unattributed`) — subscribe with `rhc:dex_trades` for full chain coverage | **ULTRA+** |
| `rhc:new_tokens` | A token's symbol/name/decimals resolved for the first time (`rhc:new_token`) | **ULTRA+** |
| `rhc:copytrade:signals` | Your copy-trade rule fires, user-scoped (`rhc:copytrade:signal`) | PRO+ |
| `rhc:price_alert:events` | Your price-alert dips/recoveries, user-scoped (`rhc:price_alert:dip` / `rhc:price_alert:recovery`) — event-driven off each RHC trade (a few seconds), **not** sub-second | PRO+ |
| `rhc:kol:coordination` | Coordination-alert fires (`rhc:kol:coordination`) | PRO+ |
| `rhc:kol:first_touches` | Broadcast first-touch feed (`rhc:kol:first_touch`) — the **channel** is PRO+; ULTRA gates the first-touch *subscription* CRUD endpoints, not this broadcast | PRO+ |
| `rhc:token_locks` | A token lock / vesting contract created on chain (`rhc:token_lock`); with `filters={"lifecycle": True}` also the unlock schedule (`rhc:token_unlock_upcoming` / `rhc:token_unlock_available`) | PRO+ |
| `rhc:lp_events` | Liquidity `add` / `remove` / `pool_created` on tracked Uniswap v2/v3/v4 pools with `in_range`, `active_share`, `share_of_reserves`, `material` (`rhc:lp_event`, `types.RhcLpStreamEvent`); durable resume | **ULTRA+** |
| `rhc:token_candles` | Live 1-minute candles for `filters={"addresses": [...]}`: `rhc:candle_closed` / `rhc:candle_revised` (the stored row), with `"updates": True` also `rhc:candle_update` (in-progress minute); durable resume | PRO+ |
| `rhc:token_risk` | `rhc:risk_verdict_changed` for `filters={"addresses": [...]}` + an `rhc:risk_verdict` snapshot; score higher = safer | PRO+ |
| `rhc:wallet_scores` | `rhc:deployer_tier_changed` for `filters={"wallets": [...]}` (0x deployers) | PRO+ |
| `rhc:token_prices` | Per-token price ticks for the addresses you name (`rhc:token_price`) — **address-scoped**: subscribe with `filters={"addresses": [...]}` (25 / 100 / 250 per connection); one `snapshot: True` frame per address, then at most one tick per address per 250 ms, each with `quality` fresh / stale / unreliable and `quality_reason`; no `seq` / `id` | PRO+ |

Lifecycle events: `open`, `close`, `reconnect`, `subscribed`, `heartbeat`, `warning`, `cursor`, `replay`, `gap`, `fatal`, `error`, plus `"*"` for every data event. Deprecated spelling: the server accepts `rhc:trades` as an alias of `rhc:dex_trades` (some 0.4.0 SDKs shipped it); this SDK uses only canonical names.

**Invalid channels are never silent.** If a subscribe names an unknown or tier-gated channel, the server answers with a `{type: "warning", code: "channels_rejected", rejected, valid_channels}` frame. The stream client delivers it to your `on("warning")` handler — and if you registered none, surfaces it via Python's `warnings.warn` so a rejected channel can't masquerade as a quiet market.

If you'd rather hand-roll the WebSocket, `client.stream_token()` (sync) / `client.aclient().stream_token()` (async) returns `{"token", "expires_at", "next_refresh_at", "rotated", "lifetime", "ws_url", "channels", ...}` — connect to `{ws_url}` with an `Authorization: Bearer {token}` header (`?token={token}` still works and is masked in access logs) and send `{"type": "subscribe", "channels": [...]}`. The token never expires: `expires_at` / `next_refresh_at` are always `None`, the same token comes back on every call, and `client.stream_token(rotate=True)` is the only way to replace it (the old one keeps working for 60 s). A `4001` close means "mint again", never a timer.

### Recovery: cursor, resume, de-duplication *(new in 0.12.0)*

The stream keeps a **resume cursor** `{"instance", "seq", "ts"}` — the position of the last frame your handlers finished — and on every reconnect asks the server to resume after it (`subscribe {…, "resume": …}`).

- **"Processed"** means the handler returned (sync) or was awaited to completion (async). Handlers run one frame at a time, so the cursor never passes a frame still being handled. A handler that raises still counts as processed; the exception goes to `error`.
- **At-least-once, never exactly-once.** After a reconnect a frame can arrive again. The client drops ids it delivered recently (the last 10,000, `dedupe_size=`); anything you persist should still dedupe on `evt["id"]`. Replayed frames carry `evt["replayed"] is True`.
- **Persistence.** The cursor lives in memory. Save `stream.get_cursor()` (or on every `cursor` event) and pass it back as `client.stream(resume=saved)` to continue after a process restart. Persist the committed cursor, never `get_progress()`.
- **Committed cursor vs progress.** `get_cursor()` is the COMMITTED, safe cursor — persist and resume from this one. `get_progress()` is what has been received and handled (replayed frames included) and is not safe to resume from. Live frames commit as they are handled. Replayed frames never commit: the server replays channel by channel, so only a `replay_end` the server calls complete — or one whose gaps are all final — commits, at the server's `last_seq` / `last_ts`. If a recovery is incomplete, or the socket closes mid-replay, the committed cursor stays at the pre-resume point, and live frames after it are delivered but not committed until a later recovery completes (`is_recovery_incomplete()`). **Trade-off:** the next reconnect re-requests the unrecovered range from the old cursor, and what arrives twice is dropped by id. Call `accept_gap()` once you have backfilled the range the `gap` event named, or decided to skip it. A gap the server calls final is handled by `on_unrecoverable_gap` (below).
- **Gaps: what is known, and who decides.** A `gap` event says which channels the server could not rebuild, the **range that may be incomplete** (`skipped["from"]` → `skipped["to"]`, plus `from`), the server's `reason`, whether it is `permanent`, and the bounds the server reported (`limits`, and per-channel `time_basis` / `truncated_at_ts` / `retry_after_ms` under `channels`). Events in that range **may** be missing — the number cannot be known, so it is never stated. Backfill the range from REST if you need certainty.
  - **Transient** (`retryable: True` — `backpressure`, `closed`, `source_busy`, `source_error`, `late_ingest_possible`, `row_cap`): the committed cursor stays put, live frames do not commit, and the client resumes again after the server's `retry_after_ms` (for `row_cap`, from `resume_ts_hint`), then on every reconnect. `resume_ts_hint` is used only when every incomplete **retryable** channel is `row_cap` (a channel whose gap is final does not block it, and is still reported); otherwise the retry asks from the committed cursor again. The client asks again after the server’s `retry_after_ms` at most `max_resume_retries` times per connection (default 5; the budget resets on every reconnect); when that budget is spent the gap event says `exhausted: True`, the cursor stays where it is, and the next reconnect resumes again.
  - **Final** (`retryable: False` — `not_reconstructable`, `window_exceeded`, and an older server's `ring_truncated` / `instance_changed`): asking again can never fill it. **The SDK then decides to continue** — that is the client's decision, not your approval — and reports it on the same `gap` event with `advanced_past_gap: True`, `source: "auto"` and the range being skipped, *before* the cursor moves. Pass `on_unrecoverable_gap="stop"` to keep the cursor instead: the stream stops and emits `fatal` with the gap, and you decide (`accept_gap()` then `run()` again continues; `accept_gap()` reports the same gap with `source: "manual"`).
- **Older servers.** Against a server that does not understand `resume` yet, the client falls back to `replay_since_seq` (same server process) or `replay_since_ts` (the server restarted). That only covers the server's in-memory buffer (minutes), and a restart is reported as a `gap` with `instance_changed`.
- **Close codes.** `4001` → the token is re-fetched and the client reconnects (`max_auth_retries=`, default 3, then `fatal` and `run()` returns); `4002` connection limit → `error` (`StreamConnectionLimitError`) plus a wait of at least 60 s (`connection_limit_backoff=`); `4003` → `fatal`, `run()` returns; `4008` slow consumer → reconnect and resume. The backoff resets only when the server acks a subscribe. `stream.last_close` keeps the last `(code, reason)`, and the `close` event carries `{"code", "reason"}`.
- **Warnings.** `warning` fires for every server warning frame, including `channels_rejected` and `channels_revoked` (revoked channels are removed from the subscription so reconnects do not re-request them); with no handler registered they go through `warnings.warn`.

```python
stream = client.stream(resume=load_cursor())   # None on first run

@stream.on("*")
async def persist(data, evt):
    await store.upsert(evt["id"], data)        # the cursor advances after this returns

stream.on("cursor", save_cursor)               # {"instance", "seq", "ts"}
stream.on("gap", lambda g: print("may be missing:", g["reasons"], g["skipped"]))  # g["advanced_past_gap"]
stream.on("fatal", lambda f: print("stream stopped:", f["code"], f["reason"]))
```

### Named subscriptions *(new in 0.13.0)*

One socket can hold several independent subscriptions, each with its own channels and filters; the server caps the total per connection, the default one included (PRO 5, ULTRA 10, BUSINESS 20). `subscribe(channels, filters)` stays the connection's `"default"` subscription and its wire is unchanged; `subscribe(channels, filters, sub_id="...")` opens a named one (1-64 characters of `A-Z a-z 0-9 _ . -`). A frame delivered under a named subscription carries `evt["sub_id"]`. **An event that matches several subscriptions is delivered once per matching subscription**, each copy stamped with its `sub_id`: the client dedupes per `(sub_id, id)`, so the same event can legitimately reach a handler twice, under two sub_ids. Filters of one subscription never affect another. `update_subscription(sub_id, filters)` REPLACES that subscription's filters (`"default"` addresses the plain one), `unsubscribe("my-sub")` / `unsubscribe(sub_id="my-sub")` removes it, `get_subscriptions()` is the local view and `await stream.list_subscriptions()` asks the server (`list` / `subscriptions`). Server refusals arrive as `warning` frames carrying the `sub_id` and one of `invalid_sub_id`, `too_many_subscriptions`, `unknown_sub_id`, `invalid_filters`, `channels_rejected`, `channels_revoked`, `replay_in_progress`; a subscription refused as `too_many_subscriptions` or `invalid_sub_id` is dropped locally so reconnects stop re-requesting it. Lifecycle events `updated` and `unsubscribed` surface the server acks.

**Resume with several subscriptions** is per subscription: on every reconnect each subscription is re-sent with the same cursor, the server serves one replay per subscription, one after another (`replay_start` … `replay_end` each carry the `sub_id`; live frames are held until the last one ends), and the cursor commits once ALL of them have ended, at the smallest `last_seq` / `last_ts` across them. The `replay` event lists `subscriptions` and the raw `ends` per subscription; a gap's `channels` entries are keyed `sub_id/channel` for named subscriptions, and an incomplete retryable replay is retried for those subscriptions only. Against an older server that ignores `sub_id`, the client emits `warning` `named_subscriptions_unsupported` once.

```python
stream = client.stream()
stream.subscribe(["rhc:kol_trades"], {"action": "buy"}, sub_id="kol-buys")
stream.subscribe(["rhc:dex_trades"], {}, sub_id="firehose")

@stream.on("rhc:kol_trade")
def on_event(data, evt):
    print(evt.get("sub_id"), data)   # "kol-buys"

stream.update_subscription("kol-buys", {"action": "buy"})
stream.unsubscribe("firehose")
await stream.run()
```

### Liquidity events and the lock schedule *(server 2026-09-23)*

`rhc:lp_events` (ULTRA+) delivers every committed liquidity event on tracked pools: raw `amount0` / `amount1` strings (`None` on v4 — ModifyLiquidity reports none), the position range, and for v3/v4 `in_range` / `active_liquidity_delta` / `active_share` — a share of liquidity **at the current price**, not of TVL, so an out-of-range removal is `active_share == 0`. v2 carries `share_of_reserves`. `material` is `True` for a removal of ≥ 25 %. When the pool's tick was not known, `in_range` and the active fields are `None` with `active_share_reason == "pool_state_unknown"` — never guessed. `provider` is usually a router / position manager, not the beneficial owner. No USD field. Filters (all optional, AND): `addresses`, `pools`, `dexes`, `actions`, `material_only`, `min_share`; an invalid value rejects the channel instead of widening it.

On `rhc:token_locks`, `filters={"lifecycle": True}` adds `rhc:token_unlock_upcoming` (an unlock within 24 h) and `rhc:token_unlock_available` (passed within 30 min — **claimable per the schedule, not claimed**). Claims, extensions and cancels are not observable on Robinhood Chain; every frame says `withdrawals_tracked: False`. The REST feed matches: `client.lp_events(action="add" | "pool_created" | "all")` (default: removals only).

```python
stream = client.stream()
stream.subscribe(["rhc:lp_events"], {"actions": ["remove"], "material_only": True}, sub_id="rugs")
stream.subscribe(["rhc:token_locks"], {"lifecycle": True, "events": ["rhc:token_unlock_upcoming"]}, sub_id="unlocks")

@stream.on("rhc:lp_event")
def on_lp(data, evt):
    print(data["dex"], data["pool"], data["action"], data.get("active_share"), data.get("share_of_reserves"))

await stream.run()
```

### Candles, risk verdicts and deployer tiers *(server 2026-09-23)*

All three are PRO+ and **scoped** (per-connection cap PRO 25 / ULTRA 100 / BUSINESS 250 across named subscriptions; over the cap or without a scope the channel is rejected, never truncated). `rhc:token_candles` needs `"addresses"` (a budget separate from `rhc:token_prices`): `rhc:candle_closed` is the stored 1-minute row, `rhc:candle_revised` the same row rewritten (`revision` n > 0), both resumable; `"updates": True` adds `rhc:candle_update`, the in-progress minute (≤ 1 per address per second, a state stream, never replayed). `rhc:token_risk` needs `"addresses"`: `rhc:risk_verdict_changed` when a sweep recheck stores a different verdict (the change happened somewhere in `(previous_checked_at, checked_at]`) plus an `rhc:risk_verdict` snapshot per address unless `"risk_snapshot": False`; `score` is **higher = safer**, the opposite of Solana's `risk_score`. `rhc:wallet_scores` needs `"wallets"` (0x deployer addresses): `rhc:deployer_tier_changed` after each 5-min refresh ("recomputed at T", not "changed at T"). TypedDicts: `types.RhcCandleClosedEvent`, `types.RhcRiskVerdictChangedEvent`, `types.RhcDeployerTierChangedEvent`, ….

```python
stream = client.stream()
stream.subscribe(["rhc:token_candles"], {"addresses": [TOKEN], "updates": True}, sub_id="candles")
stream.subscribe(["rhc:token_risk"], {"addresses": [TOKEN]}, sub_id="risk")
stream.subscribe(["rhc:wallet_scores"], {"wallets": [DEPLOYER]}, sub_id="tiers")

@stream.on("rhc:candle_closed")
def on_candle(data, evt):
    print(data["bucket_start"], data["open_price_usd"], data["close_price_usd"], data["volume_usd"])

@stream.on("rhc:risk_verdict_changed")
def on_verdict(data, evt):
    print(data["token_address"], data["changed"], data["before"]["score"], "->", data["after"]["score"])

@stream.on("rhc:deployer_tier_changed")
def on_tier(data, evt):
    print(data["address"], data["tier_before"], "->", data["tier_after"])

await stream.run()
```

## Errors & rate limits

`max_retries` (default `2`) controls automatic retries for **API-key GETs only**, on network failures and HTTP 429/500/502/503/504. The existing exponential backoff is retained. Keyless x402 GETs do not automatically replay a failed paid attempt or create a fresh payment authorization.

POST, PATCH and DELETE requests have **no automatic retries**, in both sync and async transports. This includes creates, updates/deletion, stream-token retrieval/rotation, and POST-based batch reads. A network error or server failure can arrive **after a change was applied**. Check the current rule, watchlist or token state before deciding whether to submit another mutation; do not blindly retry creates or rotations. The client preserves typed HTTP errors, request IDs and rate-limit metadata. This policy prevents automatic replay; it does not add server-side idempotency or exactly-once execution.

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

