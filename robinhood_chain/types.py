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
    trader_eoa: Optional[str]
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


# Loose alias for callers who just want the raw dict.
JSON = Any
