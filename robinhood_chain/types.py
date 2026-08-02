"""Typed response shapes for the Robinhood Chain API (EVM-native, chain id 4663).

These mirror the fields documented in the Robinhood Chain OpenAPI spec. They are
``TypedDict``s with ``total=False`` — the API may omit nullable fields, and tiers
gate some fields (BASIC/PRO/ULTRA), so treat every key as optional at runtime.

All addresses are lowercase ``0x`` EVM strings. Amounts are ETH-denominated
(``eth_amount``, ``net_flow_eth``); on-chain references are ``tx_hash`` /
``block_number``. There are NO Solana field names here.
"""

from __future__ import annotations

from typing import Any, List, Optional

try:  # TypedDict is in typing from 3.8, but Optional-key semantics are cleanest here
    from typing import TypedDict
except ImportError:  # pragma: no cover - py<3.8 not supported anyway
    from typing_extensions import TypedDict  # type: ignore


# ── /rhc/kol/feed ──


class KolFeedTrade(TypedDict, total=False):
    evm_address: str
    kol_name: Optional[str]
    kol_twitter: Optional[str]
    token_address: str
    token_symbol: Optional[str]
    token_name: Optional[str]
    launchpad: Optional[str]
    is_graduated: Optional[bool]
    deployer_tier: Optional[str]
    token_age_minutes: Optional[int]
    action: str
    eth_amount: Optional[float]
    token_amount: Optional[float]
    price_usd_at_trade: Optional[float]
    market_cap_usd_at_trade: Optional[float]
    current_mc_usd: Optional[float]
    peak_mc_usd: Optional[float]
    liquidity_usd: Optional[float]
    mc_multiple_since_trade: Optional[float]
    dex: str
    pool: Optional[str]
    tx_hash: str
    block_number: int
    traded_at: str


class KolFeedResponse(TypedDict, total=False):
    chain: str
    trades: List[KolFeedTrade]
    count: int
    data_age_seconds: Optional[int]
    next_before: Optional[str]


# ── /rhc/kol/leaderboard ──


class KolLeaderboardRow(TypedDict, total=False):
    kol_name: Optional[str]
    kol_twitter: Optional[str]
    trades: int
    buys: int
    sells: int
    buy_eth: float
    sell_eth: float
    net_eth: float
    tokens_traded: int
    last_trade_at: str


class KolLeaderboardResponse(TypedDict, total=False):
    chain: str
    period: str
    leaderboard: List[KolLeaderboardRow]
    count: int


# ── /rhc/kol/hot-tokens ──


class HotToken(TypedDict, total=False):
    token_address: str
    token_symbol: Optional[str]
    token_name: Optional[str]
    launchpad: Optional[str]
    is_graduated: Optional[bool]
    deployer_tier: Optional[str]
    kols_buying: int
    buys: int
    sells: int
    buy_eth: float
    net_eth: float
    market_cap_usd: Optional[float]
    last_trade_at: str


class HotTokensResponse(TypedDict, total=False):
    chain: str
    window: str
    tokens: List[HotToken]
    count: int


# ── /rhc/kol/{wallet} ──


class KolProfileStats(TypedDict, total=False):
    trades: int
    buys: int
    sells: int
    buy_eth: float
    sell_eth: float
    net_eth: float
    tokens_traded: int
    window: str


class KolProfileResponse(TypedDict, total=False):
    chain: str
    evm_address: str
    kol_name: Optional[str]
    kol_twitter: Optional[str]
    stats: KolProfileStats
    trades: List[dict]


# ── /rhc/trades ──


class DexTrade(TypedDict, total=False):
    block_number: int
    block_time: str
    tx_hash: str
    log_index: int
    dex: str
    pool: str
    trader: Optional[str]
    trader_eoa: Optional[str]  # effective trading account: tx.from, or the ERC-4337 userOp sender when bundled
    router: Optional[str]
    token_address: Optional[str]
    action: Optional[str]
    eth_amount: Optional[float]
    price_native: Optional[float]
    price_usd: Optional[float]
    mc_usd_at_trade: Optional[float]
    gas_price: Optional[float]
    tx_index: Optional[int]
    method_selector: Optional[str]
    liquidity: Optional[float]
    launchpad: Optional[str]
    is_kol: bool
    kol_name: Optional[str]
    deployer_tier: Optional[str]


class TradesResponse(TypedDict, total=False):
    chain: str
    trades: List[DexTrade]
    count: int
    next_before: Optional[str]


# ── /rhc/tokens ──


class TokenRow(TypedDict, total=False):
    token_address: str
    symbol: Optional[str]
    name: Optional[str]
    launchpad: Optional[str]
    is_graduated: Optional[bool]
    deployer_address: Optional[str]
    deployer_tier: Optional[str]
    price_usd: Optional[float]
    market_cap_usd: Optional[float]
    fdv_usd: Optional[float]
    peak_mc_usd: Optional[float]
    peak_mc_at: Optional[str]
    drawdown_from_peak_pct: Optional[int]
    liquidity_usd: Optional[float]
    primary_dex: Optional[str]
    primary_pool: Optional[str]
    last_trade_time: Optional[str]


class TokensResponse(TypedDict, total=False):
    chain: str
    tokens: List[TokenRow]
    count: int
    sort: str


# ── /rhc/tokens/{address} ──


class TokenDeployer(TypedDict, total=False):
    address: str
    tier: str
    tokens_deployed: int
    graduation_rate: Optional[float]
    runner_rate: Optional[float]
    runners: int
    best_peak_mc_usd: Optional[float]
    launchpads: List[str]


class TokenKolActivity(TypedDict, total=False):
    distinct_kols: int
    names: List[str]
    buys: int
    sells: int
    net_eth: float


class TokenDetail(TypedDict, total=False):
    chain: str
    token_address: str
    symbol: Optional[str]
    name: Optional[str]
    decimals: Optional[int]
    launchpad: Optional[str]
    is_graduated: Optional[bool]
    graduated_pool: Optional[str]
    graduated_at: Optional[str]
    deployer_address: Optional[str]
    first_seen_at: Optional[str]
    token_age_minutes: Optional[int]
    price_usd: Optional[float]
    price_native: Optional[float]
    market_cap_usd: Optional[float]
    fdv_usd: Optional[float]
    peak_mc_usd: Optional[float]
    peak_mc_at: Optional[str]
    drawdown_from_peak_pct: Optional[int]
    total_supply_raw: Optional[str]
    liquidity_usd: Optional[float]
    primary_dex: Optional[str]
    primary_pool: Optional[str]
    last_trade_time: Optional[str]
    deployer: Optional[TokenDeployer]
    deployer_other_tokens: List[str]
    kol_activity: TokenKolActivity
    pools: List[dict]


# ── /rhc/tokens/{address}/candles ──


class Candle(TypedDict, total=False):
    bucket_start: str
    open_price_usd: float
    high_price_usd: float
    low_price_usd: float
    close_price_usd: float
    open_mc_usd: Optional[float]
    high_mc_usd: Optional[float]
    low_mc_usd: Optional[float]
    close_mc_usd: Optional[float]
    close_liquidity_usd: Optional[float]
    close_supply: Optional[float]
    volume_usd: float
    volume_buy_usd: Optional[float]
    volume_sell_usd: Optional[float]
    trades: int
    buy_count: Optional[int]
    sell_count: Optional[int]
    dex: Optional[str]
    pool_address: Optional[str]


class CandlesResponse(TypedDict, total=False):
    chain: str
    token_address: str
    timeframe: str
    candles: List[Candle]
    count: int


# ── /rhc/tokens/{address}/kol-consensus ──


class KolConsensus(TypedDict, total=False):
    total_kol_buyers: int
    total_kol_sellers: int
    kol_exit_rate: float
    net_flow_eth: float
    total_buy_eth: float
    total_sell_eth: float
    first_kol_buy_at: Optional[str]
    last_kol_buy_at: Optional[str]
    first_touch_wallet: Optional[str]
    first_touch_at: Optional[str]
    median_entry_mc_usd: Optional[float]
    entry_mc_samples: int
    total_trades: int
    buyers: List[str]
    exited: List[str]


class KolConsensusResponse(TypedDict, total=False):
    chain: str
    token_address: str
    current_mc_usd: Optional[float]
    current_price_usd: Optional[float]
    consensus: Optional[KolConsensus]


# ── /rhc/tokens/{address}/buyer-quality ──


class BuyerQualityBreakdown(TypedDict, total=False):
    early_buyers_analyzed: int
    alpha_wallet_count: int
    kol_count: int
    bundle_buyer_count: int
    dump_cluster_count: int
    recycled_early_buyer_count: int
    avg_historical_win_rate: Optional[float]
    bot_dominated: bool


class BuyerQuality(TypedDict, total=False):
    score: int
    confidence: str
    signal: str
    breakdown: BuyerQualityBreakdown


class BuyerQualityResponse(TypedDict, total=False):
    chain: str
    token_address: str
    current_mc_usd: Optional[float]
    quality: BuyerQuality
    coverage: dict
    note: str


# ── /rhc/tokens/{address}/bundle ──


class BundleSummary(TypedDict, total=False):
    wallet_count: int
    bundle_kind: str  # "same_block" | "none"
    held_ratio: Optional[float]
    held_pct_of_supply: Optional[float]
    fully_exited: bool
    buy_volume: float
    tokens_held: float


class BundleWallet(TypedDict, total=False):
    rank: int
    wallet: str
    held_ratio: Optional[float]
    has_sold: bool
    is_kol: bool
    win_rate: Optional[float]
    likely_bot: bool
    tokens_held: float


class BundleResponse(TypedDict, total=False):
    chain: str
    token_address: str
    bundle: BundleSummary
    wallets: List[BundleWallet]


# ── /rhc/deployer-hunter/leaderboard ──


class DeployerRow(TypedDict, total=False):
    deployer_address: str
    tokens_deployed: int
    graduated: int
    graduation_rate: float
    runners: int
    runner_rate: float
    best_peak_mc_usd: Optional[float]
    launchpads: List[str]
    first_deploy_at: Optional[str]
    last_deploy_at: Optional[str]
    tier: str


class DeployerLeaderboardResponse(TypedDict, total=False):
    chain: str
    deployers: List[DeployerRow]
    total: int
    limit: int
    offset: int
    has_more: bool


# ── /rhc/deployer-hunter/{address} ──


class DeployerProfileRow(TypedDict, total=False):
    deployer_address: str
    tokens_deployed: int
    curve_tokens: int
    graduated: int
    bonding_rate: Optional[float]
    runners: int
    runner_rate: float
    best_peak_mc_usd: Optional[float]
    launchpads: List[str]
    first_deploy_at: Optional[str]
    last_deploy_at: Optional[str]
    tier: str


class DeployerRecentToken(TypedDict, total=False):
    address: str
    symbol: Optional[str]
    name: Optional[str]
    launchpad: Optional[str]
    is_graduated: Optional[bool]
    graduated_at: Optional[str]
    graduated_pool: Optional[str]
    first_seen_at: Optional[str]
    market_cap_usd: Optional[float]
    peak_mc_usd: Optional[float]
    peak_mc_at: Optional[str]


class DeployerProfileResponse(TypedDict, total=False):
    chain: str
    is_deployer: bool
    address: str
    deployer: Optional[DeployerProfileRow]
    recent_tokens: List[DeployerRecentToken]
    recent_tokens_count: int


# ── /rhc/deployer-hunter/{address}/trajectory ──


class TrajectoryStreak(TypedDict, total=False):
    type: str  # "bond" | "fail" | "none"
    count: int


class TrajectoryWindow(TypedDict, total=False):
    window_end: int
    bond_rate: float


class TrajectoryStretch(TypedDict, total=False):
    start_index: int
    end_index: int
    bond_rate: float


class DeployerTrajectory(TypedDict, total=False):
    current_streak: TrajectoryStreak
    longest_bond_streak: int
    longest_fail_streak: int
    rolling_bond_rates: List[TrajectoryWindow]
    trend: str  # "improving" | "declining" | "stable"
    avg_days_between_deploys: Optional[float]
    avg_recovery_tokens: Optional[float]
    best_stretch: Optional[TrajectoryStretch]
    worst_stretch: Optional[TrajectoryStretch]
    total_tokens_analyzed: int


class DeployerTrajectoryResponse(TypedDict, total=False):
    chain: str
    is_deployer: bool
    address: str
    deployer: Optional[DeployerRow]
    success_metric: str
    trajectory: Optional[DeployerTrajectory]
    truncated: bool


# ── /rhc/deployer-hunter/{address}/tokens ──


class DeployerTokenRow(TypedDict, total=False):
    address: str
    symbol: Optional[str]
    name: Optional[str]
    launchpad: Optional[str]
    deployer_source: Optional[str]
    is_graduated: Optional[bool]
    graduated_at: Optional[str]
    first_seen_at: Optional[str]
    market_cap_usd: Optional[float]
    peak_mc_usd: Optional[float]
    peak_mc_at: Optional[str]
    liquidity_usd: Optional[float]


class DeployerTokensResponse(TypedDict, total=False):
    chain: str
    is_deployer: bool
    address: str
    deployer: Optional[DeployerRow]
    tokens: List[DeployerTokenRow]
    total: int
    limit: int
    offset: int
    has_more: bool
    sort: str
    sort_scope: str  # only present when sort='peak_mc_usd' (page-scoped ordering)


# ── /rhc/deployer-hunter/best-tokens ──


class BestTokenDeployer(TypedDict, total=False):
    address: str
    tier: str
    graduation_rate: Optional[float]
    runner_rate: Optional[float]
    tokens_deployed: int


class BestToken(TypedDict, total=False):
    address: str
    symbol: Optional[str]
    name: Optional[str]
    launchpad: Optional[str]
    first_seen_at: Optional[str]
    is_graduated: Optional[bool]
    market_cap_usd: Optional[float]
    peak_mc_usd: Optional[float]
    peak_mc_at: Optional[str]
    liquidity_usd: Optional[float]
    deployer: Optional[BestTokenDeployer]


class BestTokensResponse(TypedDict, total=False):
    chain: str
    tokens: List[BestToken]
    period: str
    limit: int
    reputable_deployers: int
    candidates_scanned: int
    truncated: bool


# ── /rhc/deployer-hunter/stats ──


class DeployerTierCount(TypedDict, total=False):
    deployers: int
    tokens: int


class DeployerStatsResponse(TypedDict, total=False):
    chain: str
    total_deployers: int
    total_tokens: int
    reputable_deployers: int
    by_tier: dict  # tier -> DeployerTierCount
    spam_token_share: Optional[float]
    alerts_24h: int
    alerts_7d: int
    tier_rules: dict
    graduation_definition: str
    runner_definition: str


# ── /rhc/deployer-hunter/alerts ──


class DeployerAlert(TypedDict, total=False):
    id: str
    deployer_address: str
    token_address: Optional[str]
    token_symbol: Optional[str]
    token_name: Optional[str]
    alert_type: str  # "new_deploy" | "graduated"
    title: Optional[str]
    message: Optional[str]
    launchpad: Optional[str]
    tier: Optional[str]  # CURRENT tier, resolved at read time
    tier_at_alert: Optional[str]  # snapshot written when the alert fired
    tier_is_stale: bool
    mc_at_alert: Optional[float]
    current_mc_usd: Optional[float]
    liquidity_usd: Optional[float]
    priority: str  # "high" | "medium"
    is_active: bool
    created_at: str
    event_at: Optional[str]


class DeployerAlertsResponse(TypedDict, total=False):
    chain: str
    alerts: List[DeployerAlert]
    limit: int
    offset: int
    tradability_filter: str
    next_event_at: Optional[str]
    next_before: Optional[str]
    data_age_seconds: Optional[int]


# ── /rhc/deployer-hunter/{address}/history ──


class DeployerHistoryToken(TypedDict, total=False):
    address: str
    symbol: Optional[str]
    name: Optional[str]
    launchpad: Optional[str]
    is_graduated: Optional[bool]
    graduated_at: Optional[str]
    graduated_pool: Optional[str]
    first_seen_at: Optional[str]
    market_cap_usd: Optional[float]
    peak_mc_usd: Optional[float]
    peak_mc_at: Optional[str]


class DeployerHistoryResponse(TypedDict, total=False):
    chain: str
    is_deployer: bool
    address: str
    deployer: Optional[DeployerRow]
    tokens: List[DeployerHistoryToken]
    total: int
    limit: int
    offset: int
    has_more: bool


# ── /rhc/deployer-hunter/recent-bonds ──


class RecentBondToken(TypedDict, total=False):
    address: str
    symbol: Optional[str]
    name: Optional[str]
    launchpad: Optional[str]
    is_graduated: Optional[bool]
    deployer_address: Optional[str]
    deployer_tier: Optional[str]
    first_seen_at: Optional[str]
    market_cap_usd: Optional[float]
    peak_mc_usd: Optional[float]
    peak_mc_at: Optional[str]


class RecentBondsResponse(TypedDict, total=False):
    chain: str
    graduation_mc: int
    tokens: List[RecentBondToken]
    limit: int
    next_peak_mc_at: Optional[str]


# ── POST /rhc/token/batch ──


class TokenBatchEntry(TypedDict, total=False):
    address: str
    found: bool
    symbol: Optional[str]
    name: Optional[str]
    decimals: Optional[int]
    launchpad: Optional[str]
    is_graduated: Optional[bool]
    graduated_at: Optional[str]
    first_seen_at: Optional[str]
    price_usd: Optional[float]
    market_cap_usd: Optional[float]
    fdv_usd: Optional[float]
    liquidity_usd: Optional[float]
    peak_mc_usd: Optional[float]
    peak_mc_at: Optional[str]
    primary_dex: Optional[str]
    last_trade_time: Optional[str]
    deployer: Optional[dict]


class TokenBatchResponse(TypedDict, total=False):
    chain: str
    tokens: List[TokenBatchEntry]
    requested: int
    found: int


# ── POST /rhc/tokens/batch/buyer-quality ──


class BatchBuyerQualityResponse(TypedDict, total=False):
    chain: str
    tokens: List[dict]  # BuyerQualityResponse-shaped, or {token_address, error}
    requested: int
    scored: int
    max_addresses: int
    coverage: dict


# ── /rhc/kol/coordination ──


class CoordinationKol(TypedDict, total=False):
    evm_address: str
    name: Optional[str]
    twitter_url: Optional[str]
    buy_eth: float
    sell_eth: float
    exited: bool


class CoordinationToken(TypedDict, total=False):
    token_address: str
    token_symbol: Optional[str]
    token_name: Optional[str]
    launchpad: Optional[str]
    is_graduated: Optional[bool]
    deployer_tier: Optional[str]
    token_age_minutes: Optional[int]
    kol_count: int
    total_buys: int
    buy_eth: float
    sell_eth: float
    net_eth: float
    signal: str  # "accumulating" | "distributing"
    exited_count: int
    holders_count: int
    first_buy_at: str
    last_buy_at: str
    time_to_consensus_sec: int
    market_cap_usd_at_first_buy: Optional[float]
    current_mc_usd: Optional[float]
    peak_mc_usd: Optional[float]
    liquidity_usd: Optional[float]
    kols: List[CoordinationKol]


class CoordinationResponse(TypedDict, total=False):
    chain: str
    coordination: List[CoordinationToken]
    count: int
    period: str
    min_kols: int


# ── /rhc/kol/first-touches ──


class FirstTouchKol(TypedDict, total=False):
    evm_address: str  # ULTRA/BUSINESS only
    name: Optional[str]
    twitter_url: Optional[str]


class FirstTouchEvent(TypedDict, total=False):
    token_address: str
    token_symbol: Optional[str]
    token_name: Optional[str]
    launchpad: Optional[str]
    is_graduated: Optional[bool]
    first_buy_at: str
    eth_amount: Optional[float]
    token_amount: Optional[float]
    tx_hash: str
    token_age_minutes: Optional[int]
    market_cap_usd_at_first_buy: Optional[float]
    price_usd_at_first_buy: Optional[float]
    current_mc_usd: Optional[float]
    peak_mc_usd: Optional[float]
    first_kol: FirstTouchKol


class FirstTouchesResponse(TypedDict, total=False):
    chain: str
    events: List[FirstTouchEvent]
    count: int
    next_before: Optional[str]
    data_age_seconds: Optional[int]


# ── /rhc/alpha-wallets ──


class AlphaWallet(TypedDict, total=False):
    wallet: str
    classification: str  # "bot" | "smart_money" | "trader"
    is_known_kol: bool
    trades: int
    tokens: int
    buy_eth: float
    sell_eth: float
    net_eth: float
    win_rate: Optional[float]
    memecoin_share: Optional[float]
    avg_trade_mc_usd: Optional[float]
    last_trade_at: Optional[str]


class AlphaWalletsResponse(TypedDict, total=False):
    chain: str
    wallets: List[AlphaWallet]
    total: int
    limit: int
    offset: int
    has_more: bool


# ── /rhc/copytrade/subscriptions ──


class CopyTradeSubscription(TypedDict, total=False):
    id: int
    name: Optional[str]
    source_wallets: List[str]  # lowercase 0x — the API lowercases on write
    min_trade_eth: float
    only_action: str  # "buy" | "sell" | "both"
    sizing_mode: str  # "fixed" | "proportional" | "percent_source"
    sizing_amount: float  # ETH when sizing_mode == "fixed", else a multiplier
    delivery_mode: str  # "webhook" | "websocket" | "both"
    webhook_url: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str


class CopyTradeListResponse(TypedDict, total=False):
    chain: str
    subscriptions: List[CopyTradeSubscription]


class CopyTradeCreateResponse(TypedDict, total=False):
    chain: str
    subscription: CopyTradeSubscription
    webhook_secret: Optional[str]  # shown ONCE; None for websocket delivery
    note: str


class CopyTradeGetResponse(TypedDict, total=False):
    chain: str
    subscription: CopyTradeSubscription


class DeletedResponse(TypedDict, total=False):
    """Every rule-engine DELETE returns this."""

    chain: str
    deleted: bool


# ── /rhc/copytrade/signals ──


class CopyTradeSignal(TypedDict, total=False):
    id: int
    subscription_id: int
    fired_at: str
    source_wallet: str  # the followed wallet whose trade fired the rule
    action: str  # "buy" | "sell"
    token_address: str
    token_symbol: Optional[str]
    token_name: Optional[str]
    source_eth_amount: Optional[float]  # size of the source trade
    suggested_eth_amount: Optional[float]  # size your sizing_mode implies
    price_usd: Optional[float]
    dex: Optional[str]
    tx_hash: str
    delivered: bool
    delivered_at: Optional[str]


class CopyTradeSignalsResponse(TypedDict, total=False):
    chain: str
    signals: List[CopyTradeSignal]
    count: int


# ── /rhc/price-alerts ──


class PriceAlert(TypedDict, total=False):
    id: int
    name: Optional[str]
    token_address: str
    token_symbol: Optional[str]
    baseline_mc_usd: float  # captured at creation — the alert is a delta from it
    drop_pct: float
    recovery_pct: Optional[float]  # None = dip-only, terminal alert
    status: str  # "watching" | "dipped" | "recovered" | "expired"
    dip_low_mc_usd: Optional[float]
    dip_fired_at: Optional[str]
    delivery_mode: str
    webhook_url: Optional[str]
    is_active: bool
    expires_at: str  # alerts self-expire 30 days after creation
    created_at: str
    updated_at: str


class PriceAlertListResponse(TypedDict, total=False):
    chain: str
    alerts: List[PriceAlert]


class PriceAlertEvaluation(TypedDict, total=False):
    """How RHC alerts are evaluated — polled, NOT a live price loop."""

    mode: str  # "polled"
    interval_seconds: int
    note: str


class PriceAlertCreateResponse(TypedDict, total=False):
    chain: str
    alert: PriceAlert
    webhook_secret: Optional[str]  # shown ONCE; None for websocket delivery
    evaluation: PriceAlertEvaluation
    note: str


class PriceAlertGetResponse(TypedDict, total=False):
    chain: str
    alert: PriceAlert


# ── /rhc/price-alerts/events ──


class PriceAlertEvent(TypedDict, total=False):
    id: int
    alert_id: int
    event_type: str  # "dip" | "recovery"
    fired_at: str
    token_address: str
    baseline_mc_usd: float
    current_mc_usd: float
    drop_pct_actual: Optional[float]
    dip_low_mc_usd: Optional[float]
    recovery_pct_actual: Optional[float]  # recovery events only
    delivered: bool
    delivered_at: Optional[str]


class PriceAlertEventsResponse(TypedDict, total=False):
    chain: str
    events: List[PriceAlertEvent]
    count: int


# ── /rhc/kol/coordination/alerts ──


class CoordinationAlertRule(TypedDict, total=False):
    id: str  # UUID
    name: Optional[str]
    min_kols: int
    window_minutes: int
    min_score: int
    cooldown_min: int
    score_jump_break: int
    min_mc_usd: Optional[float]
    max_mc_usd: Optional[float]
    delivery_mode: str
    webhook_url: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str


class CoordinationAlertListResponse(TypedDict, total=False):
    chain: str
    rules: List[CoordinationAlertRule]


class CoordinationAlertScoring(TypedDict, total=False):
    """Which scorer components are real on RHC — ``earliness`` is defaulted."""

    score_version: str
    quality: str
    earliness: str
    note: str


class CoordinationAlertCreateResponse(TypedDict, total=False):
    chain: str
    rule: CoordinationAlertRule
    webhook_secret: Optional[str]  # shown ONCE; None for websocket delivery
    scoring: CoordinationAlertScoring
    note: str


class CoordinationAlertGetResponse(TypedDict, total=False):
    chain: str
    rule: CoordinationAlertRule


# ── /rhc/kol/first-touches/subscriptions ──


class FirstTouchFilters(TypedDict, total=False):
    """Push filters. NOT the Solana set: RHC has no scout score, so
    ``min_scout_tier`` / ``min_n_touches`` do not exist here. Unknown keys are
    rejected with a 400, not ignored."""

    kol: str  # lowercase 0x EVM address
    min_first_buy_eth: float
    min_kol_winrate: float  # 0–1, on CLOSED positions; never-sold KOLs drop out
    strategy: str  # "scalper" | "day_trader" | "swing" | "inactive" | "unscored"
    min_mc_usd: float
    max_mc_usd: float


class FirstTouchSubscription(TypedDict, total=False):
    id: str  # UUID
    name: Optional[str]
    filters: FirstTouchFilters
    delivery_mode: str
    webhook_url: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str


class FirstTouchSubscriptionListResponse(TypedDict, total=False):
    chain: str
    subscriptions: List[FirstTouchSubscription]


class FirstTouchSubscriptionCreateResponse(TypedDict, total=False):
    chain: str
    subscription: FirstTouchSubscription
    webhook_secret: Optional[str]  # shown ONCE; None for websocket delivery
    note: str


class FirstTouchSubscriptionGetResponse(TypedDict, total=False):
    chain: str
    subscription: FirstTouchSubscription


# Loose alias for callers who just want the raw dict.
JSON = Any
