"""Robinhood Chain API client (EVM-native, chain id 4663).

``RobinhoodClient`` is a thin, typed wrapper over the 14 GET endpoints under
``https://madeonsol.com/api/v1/rhc/*``. Auth is a Bearer ``msk_`` API key — the
same key and base URL as the Solana MadeOnSol API; Robinhood Chain coverage is
bundled into every tier at no extra cost. This also serves the x402-Py key-mode
surface (Bearer auth only; the Solana-native pay-per-call rail is not ported).
"""

from __future__ import annotations

import asyncio
import time
from importlib.metadata import version as _pkg_version, PackageNotFoundError
from typing import Any, Dict, Optional

import httpx

from .errors import RobinhoodError, error_for_status
from . import types as t

# Derive the User-Agent version from the installed package metadata (the single
# source of truth is pyproject.toml) so it can never drift from the manifest.
try:
    _UA_VERSION = _pkg_version("robinhood-chain")
except PackageNotFoundError:  # running from source without an installed dist
    _UA_VERSION = "0.0.0"

BASE_URL = "https://madeonsol.com/api/v1"
CHAIN_ID = 4663

# HTTP statuses worth retrying (transient): rate-limit + 5xx.
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class RobinhoodClient:
    """Robinhood Chain (chain id 4663) API client.

    Args:
        api_key: MadeOnSol API key (``msk_...``). Required. Get one free — 200
            req/day, no card — at https://madeonsol.com/pricing. RHC endpoints
            are bundled into every tier.
        base_url: API base URL (default ``https://madeonsol.com/api/v1``).
        timeout: Per-request timeout in seconds (default 30).
        max_retries: Retries on 429/5xx with exponential backoff (default 2).

    The most recent response's rate-limit headers are exposed via
    ``last_rate_limit``:
        ``{'limit': int|None, 'remaining': int|None, 'used': int|None,
           'reset': int|None, 'request_id': str|None}``
    """

    chain = "robinhood"
    chain_id = CHAIN_ID

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        if not api_key:
            import sys

            sys.stderr.write(
                "\n[robinhood-chain] Missing api_key.\n"
                "  → Get a free API key (200 req/day, no card) at "
                "https://madeonsol.com/pricing\n"
                "  → Then: RobinhoodClient(api_key=os.environ['MADEONSOL_API_KEY'])\n\n"
            )
            raise ValueError(
                "Provide api_key. Get a free API key at https://madeonsol.com/pricing"
            )
        if not api_key.startswith("msk_"):
            raise ValueError(
                "api_key must start with 'msk_'. Get one at https://madeonsol.com/pricing"
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "User-Agent": f"robinhood-chain-python/{_UA_VERSION}",
            "Accept": "application/json",
        }
        self.last_rate_limit: Dict[str, Any] = {
            "limit": None,
            "remaining": None,
            "used": None,
            "reset": None,
            "request_id": None,
        }

    # ── transport ──────────────────────────────────────────────────────────

    @staticmethod
    def _clean(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Drop ``None`` values and coerce bools to the API's ``true``/``false``."""
        if not params:
            return None
        out: Dict[str, Any] = {}
        for key, val in params.items():
            if val is None:
                continue
            out[key] = "true" if val is True else "false" if val is False else val
        return out or None

    @staticmethod
    def _to_int(value: Optional[str]) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _capture_rate_limit(self, resp: httpx.Response) -> None:
        h = resp.headers
        self.last_rate_limit = {
            "limit": self._to_int(h.get("x-ratelimit-limit")),
            "remaining": self._to_int(h.get("x-ratelimit-remaining")),
            "used": self._to_int(h.get("x-ratelimit-used")),
            "reset": self._to_int(h.get("x-ratelimit-reset")),
            "request_id": h.get("x-request-id"),
        }

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.is_success:
            return
        message = f"HTTP {resp.status_code}"
        body: Any = None
        request_id: Optional[str] = None
        try:
            body = resp.json()
            if isinstance(body, dict):
                message = body.get("error") or message
                request_id = body.get("_rid")
        except Exception:  # noqa: BLE001 - non-JSON error body
            body = resp.text
        request_id = request_id or resp.headers.get("x-request-id")
        raise error_for_status(
            resp.status_code,
            message,
            request_id=request_id,
            body=body,
            reset=self.last_rate_limit.get("reset"),
        )

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Synchronous GET with retry on transient failures."""
        url = f"{self.base_url}{path}"
        clean = self._clean(params)
        attempt = 0
        while True:
            try:
                resp = httpx.get(
                    url, params=clean, headers=self._headers, timeout=self.timeout
                )
            except httpx.HTTPError as exc:
                if attempt >= self.max_retries:
                    raise RobinhoodError(f"Request to {path} failed: {exc}") from exc
                time.sleep(_backoff(attempt))
                attempt += 1
                continue
            self._capture_rate_limit(resp)
            if resp.status_code in _RETRY_STATUSES and attempt < self.max_retries:
                time.sleep(_backoff(attempt))
                attempt += 1
                continue
            self._raise_for_status(resp)
            return resp.json()

    async def _aget(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Asynchronous GET with retry on transient failures."""
        url = f"{self.base_url}{path}"
        clean = self._clean(params)
        attempt = 0
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            while True:
                try:
                    resp = await http.get(url, params=clean, headers=self._headers)
                except httpx.HTTPError as exc:
                    if attempt >= self.max_retries:
                        raise RobinhoodError(
                            f"Request to {path} failed: {exc}"
                        ) from exc
                    await asyncio.sleep(_backoff(attempt))
                    attempt += 1
                    continue
                self._capture_rate_limit(resp)
                if (
                    resp.status_code in _RETRY_STATUSES
                    and attempt < self.max_retries
                ):
                    await asyncio.sleep(_backoff(attempt))
                    attempt += 1
                    continue
                self._raise_for_status(resp)
                return resp.json()

    # ── KOL: feed / leaderboard / hot-tokens / profile ─────────────────────

    def kol_feed(
        self,
        *,
        limit: int = 50,
        before: Optional[str] = None,
        action: Optional[str] = None,
        kol: Optional[str] = None,
        min_eth: Optional[float] = None,
    ) -> t.KolFeedResponse:
        """Real-time KOL trade feed on Robinhood Chain (BASIC+).

        Every buy/sell from tracked KOLs' verified EVM wallets on chain 4663,
        attributed via ``tx.from``. Each row carries ``token_address``,
        ``eth_amount``, ``tx_hash``, ``block_number``, live MC enrichment and
        ``mc_multiple_since_trade`` (did the call run).

        Args:
            limit: Max trades (1–100, default 50).
            before: Cursor — ISO 8601 timestamp; returns trades strictly older.
                Pass ``next_before`` from the previous response to page back.
            action: Filter to ``'buy'`` or ``'sell'``.
            kol: Filter to one KOL by EVM wallet (``0x`` + 40 hex).
            min_eth: Minimum trade size in ETH.

        Route: ``GET /api/v1/rhc/kol/feed``. Tier: BASIC.
        """
        return self._get(
            "/rhc/kol/feed",
            {
                "limit": limit,
                "before": before,
                "action": action,
                "kol": kol,
                "min_eth": min_eth,
            },
        )

    def kol_leaderboard(
        self, *, period: str = "24h", limit: int = 50
    ) -> t.KolLeaderboardResponse:
        """KOL activity leaderboard on Robinhood Chain (BASIC+).

        KOLs ranked by trade count then net ETH flow over the window.
        ``net_eth`` is buy−sell flow, not realized PnL.

        Args:
            period: Rolling window — ``'24h'`` | ``'7d'`` | ``'30d'``.
            limit: Max KOLs (1–100, default 50).

        Route: ``GET /api/v1/rhc/kol/leaderboard``. Tier: BASIC.
        """
        return self._get(
            "/rhc/kol/leaderboard", {"period": period, "limit": limit}
        )

    def kol_hot_tokens(self, *, window: str = "1h") -> t.HotTokensResponse:
        """Consensus tokens bought by 2+ KOLs on Robinhood Chain (BASIC+).

        Tokens bought by 2+ distinct tracked KOLs inside the window, ranked by
        KOL-buyer count then buy volume, enriched with launchpad, deployer tier,
        graduation and current MC.

        Args:
            window: Rolling window — ``'5m'`` | ``'15m'`` | ``'1h'`` | ``'6h'``
                | ``'24h'`` (default ``'1h'``).

        Route: ``GET /api/v1/rhc/kol/hot-tokens``. Tier: BASIC.
        """
        return self._get("/rhc/kol/hot-tokens", {"window": window})

    def kol_wallet(self, wallet: str) -> t.KolProfileResponse:
        """Single KOL profile on Robinhood Chain (BASIC+).

        Aggregate stats over one KOL's last 200 RHC trades plus their 50 most
        recent trades.

        Args:
            wallet: KOL EVM wallet address (``0x`` + 40 hex).

        Route: ``GET /api/v1/rhc/kol/{wallet}``. Tier: BASIC. 404 if the wallet
        has no RHC activity.
        """
        return self._get(f"/rhc/kol/{wallet}")

    # ── DEX trade tape ─────────────────────────────────────────────────────

    def trades(
        self,
        *,
        limit: int = 50,
        token: Optional[str] = None,
        dex: Optional[str] = None,
        action: Optional[str] = None,
        min_eth: Optional[float] = None,
        before: Optional[str] = None,
    ) -> t.TradesResponse:
        """Robinhood Chain DEX trade tape (PRO+).

        Every Uniswap v2/v3/v4 swap on chain 4663. Each row carries the real
        trader wallet (``trader_eoa`` = ``tx.from``, not the router),
        gas/ordering for MEV analysis, pool state, and KOL/deployer flags.

        Args:
            limit: Max trades (1–100, default 50).
            token: Filter to one token address (``0x`` + 40 hex).
            dex: ``'uniswap-v2'`` | ``'uniswap-v3'`` | ``'uniswap-v4'``.
            action: ``'buy'`` or ``'sell'``.
            min_eth: Minimum trade size in ETH.
            before: Cursor — trades strictly older than this ``block_time``.
                Pass ``next_before`` from the previous response.

        Route: ``GET /api/v1/rhc/trades``. Tier: PRO+.
        """
        return self._get(
            "/rhc/trades",
            {
                "limit": limit,
                "token": token,
                "dex": dex,
                "action": action,
                "min_eth": min_eth,
                "before": before,
            },
        )

    # ── Tokens: list / detail / candles / consensus / quality / bundle ─────

    def tokens(
        self,
        *,
        limit: int = 50,
        sort: Optional[str] = None,
        min_mc_usd: Optional[float] = None,
        min_liquidity_usd: Optional[float] = None,
        launchpad: Optional[str] = None,
    ) -> t.TokensResponse:
        """Robinhood Chain token discovery (PRO+).

        Live-priced tokens with MC, liquidity, peak MC + drawdown, launchpad and
        deployer reputation tier. Sortable and filterable.

        Args:
            limit: Max tokens (1–100, default 50).
            sort: ``'last_trade'`` (default) | ``'market_cap'`` |
                ``'liquidity'`` | ``'peak_mc'`` (all descending).
            min_mc_usd: Minimum current market cap (USD).
            min_liquidity_usd: Minimum current liquidity (USD).
            launchpad: Filter by launchpad — pons, flap, clanker, hood.fun,
                noxa, virtuals.

        Route: ``GET /api/v1/rhc/tokens``. Tier: PRO+.
        """
        return self._get(
            "/rhc/tokens",
            {
                "limit": limit,
                "sort": sort,
                "min_mc_usd": min_mc_usd,
                "min_liquidity_usd": min_liquidity_usd,
                "launchpad": launchpad,
            },
        )

    def token(self, address: str) -> t.TokenDetail:
        """Robinhood Chain token bundle/snapshot (BASIC+).

        Full snapshot for one token: metadata, live price/MC/FDV, peak MC +
        drawdown, graduation, deployer reputation block (+ other tokens by the
        same deployer), KOL activity summary, and pool inventory with reserves.

        Args:
            address: Token address (``0x`` + 40 hex).

        Route: ``GET /api/v1/rhc/tokens/{address}``. Tier: BASIC. 404 if the
        token is not found on Robinhood Chain.
        """
        return self._get(f"/rhc/tokens/{address}")

    def token_candles(
        self,
        address: str,
        *,
        limit: int = 240,
        from_: Optional[str] = None,
        to: Optional[str] = None,
    ) -> t.CandlesResponse:
        """1-minute OHLC candles on Robinhood Chain (PRO+).

        Chronological 1-minute candles: price + market-cap OHLC, close
        liquidity, volume with buy/sell split, and trade/buy/sell counts.
        Returned oldest→newest.

        Args:
            address: Token address (``0x`` + 40 hex).
            limit: Number of candles (1–1000, default 240; most recent first).
            from_: Lower bound on ``bucket_start`` (ISO 8601). Maps to the
                ``from`` query param.
            to: Upper bound on ``bucket_start`` (ISO 8601).

        Route: ``GET /api/v1/rhc/tokens/{address}/candles``. Tier: PRO+.
        """
        return self._get(
            f"/rhc/tokens/{address}/candles",
            {"limit": limit, "from": from_, "to": to},
        )

    def token_kol_consensus(self, address: str) -> t.KolConsensusResponse:
        """KOL consensus on a Robinhood Chain token (PRO+).

        How the tracked-KOL cohort is positioned: distinct buyers vs sellers,
        exit rate, ``net_flow_eth``, median entry MC, and first-touch
        wallet/time. ULTRA additionally returns the ``buyers`` and ``exited``
        wallet lists. ``consensus`` is ``None`` when no tracked KOL has traded.

        Args:
            address: Token address (``0x`` + 40 hex).

        Route: ``GET /api/v1/rhc/tokens/{address}/kol-consensus``. Tier: PRO+.
        """
        return self._get(f"/rhc/tokens/{address}/kol-consensus")

    def token_buyer_quality(self, address: str) -> t.BuyerQualityResponse:
        """Early-buyer quality on a Robinhood Chain token (BASIC+).

        A 0–100 quality read on a token's earliest distinct buyer cohort (first
        20): win-rate, KOL-presence, bot-domination and bundle-buyer legs, plus
        the informational dump-cluster ensemble (``dump_cluster_count`` — flags
        the pattern but does not move the score).

        Args:
            address: Token address (``0x`` + 40 hex).

        Route: ``GET /api/v1/rhc/tokens/{address}/buyer-quality``. Tier: BASIC.
        """
        return self._get(f"/rhc/tokens/{address}/buyer-quality")

    def token_bundle(self, address: str) -> t.BundleResponse:
        """Launch-bundle detection on a Robinhood Chain token (BASIC+).

        Ranks the first 20 distinct buyers by on-chain order and flags a bundle
        when 3+ make their first buy in the same block, then reports the
        cohort's current-held %. RHC is an Arbitrum Orbit L2 with no atomic
        multi-signer tx, so a detected bundle is ``same_block`` (else ``none``);
        there is no ``atomic_tx`` kind. Field-gated by tier: BASIC gets the
        scalar ``bundle`` signal; PRO adds the top-10 wallets; ULTRA returns the
        full cohort with alpha-wallet identity.

        Args:
            address: Token address (``0x`` + 40 hex).

        Route: ``GET /api/v1/rhc/tokens/{address}/bundle``. Tier: BASIC.
        """
        return self._get(f"/rhc/tokens/{address}/bundle")

    # ── Deployer hunter: leaderboard / profile ─────────────────────────────

    def deployer_hunter_leaderboard(
        self,
        *,
        sort: str = "graduation_rate",
        tier: Optional[str] = None,
        min_tokens: int = 3,
        limit: int = 20,
        offset: int = 0,
    ) -> t.DeployerLeaderboardResponse:
        """Deployer reputation leaderboard on Robinhood Chain (BASIC+).

        Deployers ranked by reputation over every launchpad token indexed.
        Most RHC launchpads are direct-to-DEX, so ``graduation_rate`` = share of
        the deployer's tokens that reached a $40K+ peak MC; ``runner_rate`` =
        share that reached $100K+.

        Args:
            sort: ``'graduation_rate'`` (default) | ``'runner_rate'`` |
                ``'tokens_deployed'`` | ``'best_peak_mc_usd'`` |
                ``'last_deploy_at'`` (all descending, NULLs last).
            tier: Filter to one tier — ``'elite'`` | ``'good'`` | ``'neutral'``
                | ``'spammer'``.
            min_tokens: Minimum tokens deployed (1–100000, default 3).
            limit: Page size (1–50, default 20).
            offset: Page offset (0–10000, default 0).

        Route: ``GET /api/v1/rhc/deployer-hunter/leaderboard``. Tier: BASIC.
        """
        return self._get(
            "/rhc/deployer-hunter/leaderboard",
            {
                "sort": sort,
                "tier": tier,
                "min_tokens": min_tokens,
                "limit": limit,
                "offset": offset,
            },
        )

    def deployer_hunter_profile(self, address: str) -> t.DeployerProfileResponse:
        """Single deployer profile on Robinhood Chain (BASIC+).

        One deployer's full reputation row (tier, bonding_rate, runner_rate,
        best peak MC, launchpads, deploy timeline) plus their 50 most recent
        tokens enriched with live MC and peak MC. Unknown wallets return 200
        with ``is_deployer: false`` (not a 404).

        Args:
            address: Deployer EVM wallet address (``0x`` + 40 hex).

        Route: ``GET /api/v1/rhc/deployer-hunter/{address}``. Tier: BASIC.
        """
        return self._get(f"/rhc/deployer-hunter/{address}")

    # ── Alpha wallets ──────────────────────────────────────────────────────

    def alpha_wallets(
        self,
        *,
        classification: Optional[str] = None,
        identity: Optional[str] = None,
        min_memecoin_share: Optional[float] = None,
        max_avg_mc_usd: Optional[float] = None,
        min_net_eth: Optional[float] = None,
        min_win_rate: Optional[float] = None,
        max_win_rate: Optional[float] = None,
        min_trades: Optional[int] = None,
        min_tokens: Optional[int] = None,
        min_buy_eth: Optional[float] = None,
        active_hours: Optional[int] = None,
        sort: Optional[str] = None,
        order: Optional[str] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> t.AlphaWalletsResponse:
        """Smart-money wallet ranking on Robinhood Chain (PRO+).

        The reverse of KOL discovery: rank the trader wallets we already watch by
        realized on-chain performance. ``net_eth`` is realized net flow
        (sell − buy); ``win_rate`` is share of tokens taken out profitably;
        ``likely_bot`` (via ``classification``) flags atomic-arb/MM fleets.
        ``memecoin_share`` = launchpad-token trade share — filter with
        ``min_memecoin_share`` to isolate memecoin traders.

        Args:
            classification: ``'all'`` (default) | ``'human'`` | ``'bot'`` |
                ``'smart_money'``.
            identity: ``'all'`` (default) | ``'known_kol'`` | ``'unknown'``.
            min_memecoin_share: Minimum launchpad-memecoin trade share (0–1).
            max_avg_mc_usd: Maximum average market cap traded (low-cap filter).
            min_net_eth: Minimum realized net ETH.
            min_win_rate: Minimum win rate (0–1).
            max_win_rate: Maximum win rate (0–1).
            min_trades: Minimum trade count.
            min_tokens: Minimum distinct tokens traded.
            min_buy_eth: Minimum ETH deployed (whale/size filter).
            active_hours: Only wallets active within the last N hours (1–720).
            sort: ``'net_eth'`` (default) | ``'win_rate'`` | ``'trades'`` |
                ``'tokens'`` | ``'buy_eth'`` | ``'memecoin_share'`` |
                ``'last_trade_at'``.
            order: ``'desc'`` (default) | ``'asc'``.
            limit: Page size (1–100, default 25).
            offset: Page offset (0–10000, default 0).

        Route: ``GET /api/v1/rhc/alpha-wallets``. Tier: PRO+.
        """
        return self._get(
            "/rhc/alpha-wallets",
            {
                "classification": classification,
                "identity": identity,
                "min_memecoin_share": min_memecoin_share,
                "max_avg_mc_usd": max_avg_mc_usd,
                "min_net_eth": min_net_eth,
                "min_win_rate": min_win_rate,
                "max_win_rate": max_win_rate,
                "min_trades": min_trades,
                "min_tokens": min_tokens,
                "min_buy_eth": min_buy_eth,
                "active_hours": active_hours,
                "sort": sort,
                "order": order,
                "limit": limit,
                "offset": offset,
            },
        )

    # ── async ──────────────────────────────────────────────────────────────

    def aclient(self) -> "AsyncRobinhoodClient":
        """Return an async view of this client — every endpoint method is a
        coroutine with the identical signature. Shares this client's key,
        base URL, timeout, retry policy, and ``last_rate_limit``.

            rhc = RobinhoodClient(api_key="msk_...")
            feed = await rhc.aclient().kol_feed(limit=10)
        """
        return AsyncRobinhoodClient(self)


class AsyncRobinhoodClient:
    """Async wrapper around :class:`RobinhoodClient`.

    Each of the 14 endpoint methods is exposed as a coroutine with the same
    signature as its sync twin. The endpoint methods build their (path, params)
    on the shared sync instance and dispatch through the async transport, so the
    two paths can never drift.
    """

    def __init__(self, sync: RobinhoodClient) -> None:
        self._sync = sync

    def __getattr__(self, name: str):
        if name not in _ENDPOINTS:
            raise AttributeError(name)
        sync_method = getattr(self._sync, name)

        async def _call(*args: Any, **kwargs: Any) -> Any:
            path, params = _capture_request(self._sync, sync_method, args, kwargs)
            return await self._sync._aget(path, params)

        _call.__name__ = name
        _call.__doc__ = sync_method.__doc__
        return _call


# The 14 dispatch-only endpoint methods (each ends in a single ``self._get``).
_ENDPOINTS = frozenset(
    {
        "kol_feed",
        "kol_leaderboard",
        "kol_hot_tokens",
        "kol_wallet",
        "trades",
        "tokens",
        "token",
        "token_candles",
        "token_kol_consensus",
        "token_buyer_quality",
        "token_bundle",
        "deployer_hunter_leaderboard",
        "deployer_hunter_profile",
        "alpha_wallets",
    }
)


def _capture_request(client: RobinhoodClient, sync_method: Any, args: tuple, kwargs: dict):
    """Run a sync endpoint method with its ``_get`` stubbed out to record the
    (path, params) it would have requested — used to drive the async transport
    from the exact same argument-parsing code. Scoped to a fresh throwaway
    client copy so the live client's transport is never mutated."""
    recorder: Dict[str, Any] = {}

    def _stub(path: str, params: Optional[Dict[str, Any]] = None) -> None:
        recorder["path"] = path
        recorder["params"] = params
        return None

    # Bind the sync method to a shallow proxy whose only override is ``_get``,
    # leaving the real client untouched (thread-safe, no attribute mutation).
    proxy = _RecordingProxy(client, _stub)
    sync_method.__func__(proxy, *args, **kwargs)
    return recorder.get("path"), recorder.get("params")


class _RecordingProxy:
    """Delegates every attribute to the wrapped client except ``_get``, which is
    replaced by a recorder. Lets us reuse a sync method's body without touching
    the shared client instance."""

    def __init__(self, client: RobinhoodClient, get_stub: Any) -> None:
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_get", get_stub)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_client"), name)


def _backoff(attempt: int) -> float:
    """Exponential backoff: 0.5s, 1s, 2s, ... capped at 8s."""
    return min(0.5 * (2 ** attempt), 8.0)
