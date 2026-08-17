"""Robinhood Chain API client (EVM-native, chain id 4663).

``RobinhoodClient`` is a thin, typed wrapper over the 54 operations (40 GET,
6 POST, 4 PATCH, 4 DELETE) under
``https://madeonsol.com/api/v1/rhc/*``, plus the shared WebSocket streaming
surface (``POST /stream/token`` and the managed :meth:`RobinhoodClient.stream`
client). Auth is a Bearer ``msk_`` API key — the
same key and base URL as the Solana MadeOnSol API; Robinhood Chain coverage is
bundled into every tier at no extra cost. This also serves the x402-Py key-mode
surface (Bearer auth only; the Solana-native pay-per-call rail is not ported).
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import secrets
import time
from importlib.metadata import version as _pkg_version, PackageNotFoundError
from typing import Any, Dict, Optional, Sequence

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

# ── Keyless x402 rail (USDG on Robinhood Chain) — since 0.7.0 ───────────────
# The 10 endpoints callable without an API key. Kept in sync with the server's
# X402_PRICES; GET https://madeonsol.com/api/x402/rhc is the source of truth.
X402_BASE_URL = "https://madeonsol.com/api/x402"
KEYLESS_ENDPOINTS = (
    "/rhc/kol/feed",
    "/rhc/kol/hot-tokens",
    "/rhc/kol/leaderboard",
    "/rhc/tokens/{address}",
    "/rhc/tokens/{address}/buyer-quality",
    "/rhc/tokens/{address}/kol-consensus",
    "/rhc/tokens/{address}/risk",
    "/rhc/tokens/{address}/holders",
    "/rhc/wallet/{address}/pnl",
    "/rhc/deployer-hunter/alerts",
)
_KEYLESS_SET = frozenset(KEYLESS_ENDPOINTS)
_RHC_NETWORK = "eip155:4663"
_USDG_DOMAIN = {
    "name": "Global Dollar",
    "version": "1",
    "chainId": CHAIN_ID,
    "verifyingContract": "0x5fc5360d0400a0fd4f2af552add042d716f1d168",
}
_TRANSFER_WITH_AUTHORIZATION_TYPES = {
    "TransferWithAuthorization": [
        {"name": "from", "type": "address"},
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"},
        {"name": "nonce", "type": "bytes32"},
    ]
}
_AUTH_TTL_SECONDS = 300
_EVM_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _keyless_template(path: str) -> str:
    """Collapse a concrete /rhc/... path to its template for the keyless lookup."""
    return "/".join("{address}" if _EVM_ADDR_RE.match(seg) else seg for seg in path.split("?")[0].split("/"))


class KeylessNotAvailableError(RobinhoodError):
    """Raised when a key-mode-only method is called on a keyless (x402) client."""

    def __init__(self, path: str) -> None:
        super().__init__(
            f"{path} is not on the keyless x402 rail. Keyless endpoints: {', '.join(KEYLESS_ENDPOINTS)}. "
            "For everything else pass api_key (free at https://madeonsol.com/pricing)."
        )

# HTTP statuses worth retrying (transient): rate-limit + 5xx.
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class _Null:
    """Sentinel type for :data:`NULL`."""

    _instance: Optional["_Null"] = None

    def __new__(cls) -> "_Null":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "robinhood_chain.NULL"

    def __bool__(self) -> bool:
        return False


#: Explicit JSON ``null`` for the rule-engine update methods.
#:
#: Omitting a keyword leaves the field untouched; passing ``NULL`` clears it.
#: Python's ``None`` cannot mean both, and the routes validate with strict
#: schemas that reject an explicit ``null`` on non-nullable fields — so
#: "unset" and "set to null" have to be different values::
#:
#:     client.copytrade_subscriptions_update(7, name=NULL)  # clears the label
#:     client.copytrade_subscriptions_update(7, is_active=False)  # name untouched
#:
#: Only ``name``, ``webhook_url``, ``min_mc_usd`` and ``max_mc_usd`` are
#: nullable on the wire.
NULL = _Null()


class RobinhoodClient:
    """Robinhood Chain (chain id 4663) API client.

    Args:
        api_key: MadeOnSol API key (``msk_...``). Get one free — 200
            req/day, no card — at https://madeonsol.com/pricing. RHC endpoints
            are bundled into every tier. Key mode: all methods.
        private_key: Keyless x402 mode (since 0.7.0) — hex private key
            (``0x...``) of an EVM wallet holding USDG on Robinhood Chain. Pays
            per call in USDG on the 10 keyless endpoints (``KEYLESS_ENDPOINTS``);
            every other method raises ``KeylessNotAvailableError``. Needs the
            optional extra ``robinhood-chain[x402]`` (eth-account). Ignored when
            ``api_key`` is also given. Read it from the environment — never
            hard-code it.
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
        private_key: Optional[str] = None,
        base_url: str = BASE_URL,
        x402_base_url: str = X402_BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self.auth_mode = "key" if api_key else ("x402" if private_key else None)
        self._account = None
        self._private_key: Optional[str] = None
        #: Decoded PAYMENT-RESPONSE of the last paid call (keyless mode).
        self.last_payment: Optional[Dict[str, Any]] = None
        if self.auth_mode is None:
            import sys

            sys.stderr.write(
                "\n[robinhood-chain] Missing api_key (or private_key for keyless x402 mode).\n"
                "  → Get a free API key (200 req/day, no card) at "
                "https://madeonsol.com/pricing\n"
                "  → Then: RobinhoodClient(api_key=os.environ['MADEONSOL_API_KEY'])\n"
                "  → Or keyless: RobinhoodClient(private_key=os.environ['RHC_PAYER_KEY'])  # USDG wallet\n\n"
            )
            raise ValueError(
                "Provide api_key or private_key. Get a free API key at https://madeonsol.com/pricing"
            )
        if self.auth_mode == "key":
            assert api_key is not None
            if not api_key.startswith("msk_"):
                raise ValueError(
                    "api_key must start with 'msk_'. Get one at https://madeonsol.com/pricing"
                )
            self._headers = {
                "Authorization": f"Bearer {api_key}",
                "User-Agent": f"robinhood-chain-python/{_UA_VERSION}",
                "Accept": "application/json",
            }
        else:
            assert private_key is not None
            if not re.match(r"^0x[0-9a-fA-F]{64}$", private_key):
                raise ValueError(
                    "private_key must be a 0x-prefixed 32-byte hex EVM private key "
                    "(the wallet that holds USDG on Robinhood Chain)."
                )
            self._private_key = private_key
            self._headers = {
                "User-Agent": f"robinhood-chain-python/{_UA_VERSION}",
                "Accept": "application/json",
            }
        self.base_url = base_url.rstrip("/")
        self.x402_base_url = x402_base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
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

    # ── keyless x402 transport ─────────────────────────────────────────────

    def _signer(self):
        if self._account is not None:
            return self._account
        try:
            from eth_account import Account  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on the extra
            raise RobinhoodError(
                "Keyless x402 mode needs the optional extra: pip install 'robinhood-chain[x402]' (eth-account)"
            ) from exc
        self._account = Account.from_key(self._private_key)
        return self._account

    def _payment_header(self, leg: Dict[str, Any]) -> str:
        """Sign an EIP-3009 transferWithAuthorization for the USDG-on-RHC leg."""
        from eth_account.messages import encode_typed_data  # type: ignore

        account = self._signer()
        now = int(time.time())
        nonce = "0x" + secrets.token_hex(32)
        to = leg["payTo"]
        message = {
            "from": account.address,
            "to": to,
            "value": int(leg["amount"]),
            "validAfter": 0,
            "validBefore": now + _AUTH_TTL_SECONDS,
            "nonce": bytes.fromhex(nonce[2:]),
        }
        signable = encode_typed_data(
            domain_data=_USDG_DOMAIN,
            message_types=_TRANSFER_WITH_AUTHORIZATION_TYPES,
            message_data=message,
        )
        signature = account.sign_message(signable).signature.hex()
        if not signature.startswith("0x"):
            signature = "0x" + signature
        payload = {
            "x402Version": 2,
            "scheme": "exact",
            "network": _RHC_NETWORK,
            "payload": {
                "signature": signature,
                "authorization": {
                    "from": account.address,
                    "to": to,
                    "value": str(leg["amount"]),
                    "validAfter": "0",
                    "validBefore": str(now + _AUTH_TTL_SECONDS),
                    "nonce": nonce,
                },
            },
        }
        return base64.b64encode(json.dumps(payload).encode()).decode()

    def _capture_payment(self, resp: httpx.Response) -> None:
        raw = resp.headers.get("payment-response")
        if not raw:
            return
        try:
            self.last_payment = json.loads(base64.b64decode(raw).decode())
        except Exception:  # noqa: BLE001
            self.last_payment = None

    def _get_x402(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Keyless GET: 402 challenge → sign USDG leg → retry with PAYMENT-SIGNATURE."""
        if _keyless_template(path) not in _KEYLESS_SET:
            raise KeylessNotAvailableError(path)
        url = f"{self.x402_base_url}{path}"
        clean = self._clean(params)
        first = httpx.get(url, params=clean, headers=self._headers, timeout=self.timeout)
        if first.status_code != 402:
            self._capture_rate_limit(first)
            self._raise_for_status(first)
            return first.json()
        try:
            challenge = first.json()
        except Exception:  # noqa: BLE001
            challenge = {}
        leg = next((a for a in challenge.get("accepts", []) if a.get("network") == _RHC_NETWORK), None)
        if leg is None:
            raise RobinhoodError(f"x402 challenge for {path} has no USDG-on-Robinhood-Chain leg")
        headers = dict(self._headers)
        headers["PAYMENT-SIGNATURE"] = self._payment_header(leg)
        resp = httpx.get(url, params=clean, headers=headers, timeout=self.timeout)
        self._capture_payment(resp)
        self._capture_rate_limit(resp)
        if not resp.is_success:
            raise RobinhoodError(
                f"x402 payment for {path} rejected (HTTP {resp.status_code}): {resp.text[:400]}"
            )
        return resp.json()

    async def _aget_x402(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if _keyless_template(path) not in _KEYLESS_SET:
            raise KeylessNotAvailableError(path)
        url = f"{self.x402_base_url}{path}"
        clean = self._clean(params)
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            first = await http.get(url, params=clean, headers=self._headers)
            if first.status_code != 402:
                self._capture_rate_limit(first)
                self._raise_for_status(first)
                return first.json()
            try:
                challenge = first.json()
            except Exception:  # noqa: BLE001
                challenge = {}
            leg = next((a for a in challenge.get("accepts", []) if a.get("network") == _RHC_NETWORK), None)
            if leg is None:
                raise RobinhoodError(f"x402 challenge for {path} has no USDG-on-Robinhood-Chain leg")
            headers = dict(self._headers)
            headers["PAYMENT-SIGNATURE"] = self._payment_header(leg)
            resp = await http.get(url, params=clean, headers=headers)
            self._capture_payment(resp)
            self._capture_rate_limit(resp)
            if not resp.is_success:
                raise RobinhoodError(
                    f"x402 payment for {path} rejected (HTTP {resp.status_code}): {resp.text[:400]}"
                )
            return resp.json()

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Synchronous GET with retry on transient failures."""
        if self.auth_mode == "x402":
            return self._get_x402(path, params)
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
        if self.auth_mode == "x402":
            return await self._aget_x402(path, params)
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

    def _post(self, path: str, json_body: Optional[Dict[str, Any]] = None) -> Any:
        """Synchronous POST (JSON body) with retry on transient failures."""
        if self.auth_mode == "x402":
            raise KeylessNotAvailableError(path)
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            try:
                resp = httpx.post(
                    url, json=json_body, headers=self._headers, timeout=self.timeout
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

    async def _apost(
        self, path: str, json_body: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Asynchronous POST (JSON body) with retry on transient failures."""
        if self.auth_mode == "x402":
            raise KeylessNotAvailableError(path)
        url = f"{self.base_url}{path}"
        attempt = 0
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            while True:
                try:
                    resp = await http.post(url, json=json_body, headers=self._headers)
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

    def _patch(self, path: str, json_body: Optional[Dict[str, Any]] = None) -> Any:
        """Synchronous PATCH (JSON body) with retry on transient failures."""
        if self.auth_mode == "x402":
            raise KeylessNotAvailableError(path)
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            try:
                resp = httpx.patch(
                    url, json=json_body, headers=self._headers, timeout=self.timeout
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

    async def _apatch(
        self, path: str, json_body: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Asynchronous PATCH (JSON body) with retry on transient failures."""
        if self.auth_mode == "x402":
            raise KeylessNotAvailableError(path)
        url = f"{self.base_url}{path}"
        attempt = 0
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            while True:
                try:
                    resp = await http.patch(url, json=json_body, headers=self._headers)
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

    def _delete(self, path: str) -> Any:
        """Synchronous DELETE (no body) with retry on transient failures.

        Safe to retry: every rule-engine DELETE is scoped by ``id`` AND
        ``user_id`` and returns 404 once the row is gone, so a retried delete
        can never remove someone else's rule.
        """
        if self.auth_mode == "x402":
            raise KeylessNotAvailableError(path)
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            try:
                resp = httpx.delete(url, headers=self._headers, timeout=self.timeout)
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

    async def _adelete(self, path: str) -> Any:
        """Asynchronous DELETE (no body) with retry on transient failures."""
        if self.auth_mode == "x402":
            raise KeylessNotAvailableError(path)
        url = f"{self.base_url}{path}"
        attempt = 0
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            while True:
                try:
                    resp = await http.delete(url, headers=self._headers)
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

    @staticmethod
    def _body(fields: Dict[str, Any]) -> Dict[str, Any]:
        """Drop ``None`` values from a write body.

        The routes use strict Zod schemas, so an explicit ``None`` for an
        omitted keyword would be rejected rather than treated as "unset". Fields
        that are genuinely nullable on the wire (``name``, ``webhook_url``,
        ``min_mc_usd``, ``max_mc_usd``) are passed through a ``_NULL`` sentinel
        instead — see :data:`NULL`.
        """
        out: Dict[str, Any] = {}
        for key, val in fields.items():
            if val is None:
                continue
            out[key] = None if val is NULL else val
        return out

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
        attributed to the effective trading account (``tx.from``, or the
        ERC-4337 userOp sender when the trade was bundled). Each row carries
        ``token_address``, ``eth_amount``, ``tx_hash``, ``block_number``, live
        MC enrichment and ``mc_multiple_since_trade`` (did the call run).

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

    def kol_coordination(
        self,
        *,
        period: str = "24h",
        min_kols: int = 2,
        limit: int = 20,
        min_mc_usd: Optional[float] = None,
        max_mc_usd: Optional[float] = None,
    ) -> t.CoordinationResponse:
        """KOL clustering / consensus on Robinhood Chain (BASIC+).

        Tokens bought by N+ DISTINCT tracked KOLs inside the window, ranked by
        KOL count then buy volume. Each row carries the per-KOL breakdown,
        ``net_eth`` (buys − sells in-window), a ``signal`` of ``'accumulating'``
        vs ``'distributing'``, ``exited_count`` / ``holders_count``, and
        ``time_to_consensus_sec`` (how fast the cohort piled in).

        Deeper than ``kol_hot_tokens``: that returns the ranked token list, this
        returns the cohort composition and exit state behind it. RHC has no KOL
        winrate/strategy MVs, so the Solana ``avg_winrate_7d`` /
        ``coordination_score`` fields are intentionally absent.

        Args:
            period: ``'1h'`` | ``'6h'`` | ``'24h'`` (default) | ``'7d'``.
            min_kols: Minimum distinct KOL buyers to qualify (2–50, default 2).
            limit: Max tokens (1–50, default 20).
            min_mc_usd: Minimum market cap at the FIRST KOL buy (USD). Tokens
                with an unknown entry MC are excluded when a band is set.
            max_mc_usd: Maximum market cap at the first KOL buy (USD).

        Route: ``GET /api/v1/rhc/kol/coordination``. Tier: BASIC.
        """
        return self._get(
            "/rhc/kol/coordination",
            {
                "period": period,
                "min_kols": min_kols,
                "limit": limit,
                "min_mc_usd": min_mc_usd,
                "max_mc_usd": max_mc_usd,
            },
        )

    def kol_first_touches(
        self,
        *,
        limit: int = 50,
        since: Optional[str] = None,
        before: Optional[str] = None,
        min_eth: Optional[float] = None,
        token_age_max_min: Optional[int] = None,
        launchpad: Optional[str] = None,
        min_mc_usd: Optional[float] = None,
        max_mc_usd: Optional[float] = None,
    ) -> t.FirstTouchesResponse:
        """Earliest KOL entry per token on Robinhood Chain (BASIC+).

        The first time ANY tracked KOL bought a given token — the early-entry /
        discovery signal. Each event carries the entry size in ETH, ``tx_hash``,
        ``token_age_minutes`` at first touch, the MC at entry and the current +
        peak MC (so you can score how the call aged).

        Tier depth: BASIC clamps ``limit`` to 20; the KOL's ``evm_address``
        inside ``first_kol`` is revealed only to ULTRA/BUSINESS (``name`` and
        ``twitter_url`` are always returned).

        Args:
            limit: Max events (1–100, default 50; clamped to 20 below PRO).
            since: ISO 8601 — only first-touches strictly newer. The polling
                idiom: pass back ``next_before``/the newest timestamp you saw.
            before: ISO 8601 cursor — only first-touches strictly older. Pass
                ``next_before`` from the previous response to page back.
            min_eth: Minimum first-buy size in ETH (0–100000).
            token_age_max_min: Only tokens younger than N minutes at first touch
                (1–43200) — isolates genuinely early calls.
            launchpad: Filter by launchpad (pons, flap, clanker, hood.fun,
                noxa, virtuals).
            min_mc_usd: Minimum market cap at first buy (USD).
            max_mc_usd: Maximum market cap at first buy (USD).

        Route: ``GET /api/v1/rhc/kol/first-touches``. Tier: BASIC.
        """
        return self._get(
            "/rhc/kol/first-touches",
            {
                "limit": limit,
                "since": since,
                "before": before,
                "min_eth": min_eth,
                "token_age_max_min": token_age_max_min,
                "launchpad": launchpad,
                "min_mc_usd": min_mc_usd,
                "max_mc_usd": max_mc_usd,
            },
        )

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

        Every Uniswap v2/v3/v4 swap on chain 4663. Each row carries the
        effective trading account (``trader_eoa`` — ``tx.from`` normally, or
        the ERC-4337 userOp sender when the trade was bundled; never the
        router or the bundler), gas/ordering for MEV analysis, pool state,
        and KOL/deployer flags.

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

    def lp_events(
        self,
        *,
        limit: int = 50,
        token: Optional[str] = None,
        pool: Optional[str] = None,
        provider: Optional[str] = None,
        dex: Optional[str] = None,
        before: Optional[str] = None,
    ) -> t.LpEventsResponse:
        """Liquidity REMOVALS feed — the rug signal (PRO+).

        Uniswap v2/v3 ``Burn`` and v4 ``ModifyLiquidity`` with a negative
        delta on tracked pools, from our own node's log subscription. Each row
        is enriched with the token, the wallet that pulled (``provider``),
        ``provider_is_token_deployer`` (the classic rug shape), deployer tier
        and KOL name.

        **Removals only** — adds are not persisted (v4 adds share the topic and
        are dropped at decode; v2/v3 ``Mint`` is not subscribed), so every row
        is ``event == "remove"`` and an empty page means "no removals seen",
        never "no liquidity activity" — the ``coverage`` block says
        ``adds_persisted: False``. Amounts are raw uint256 integers as decimal
        **strings** (``liquidity``, ``amount0`` / ``amount1``, pre-resolved
        ``token_amount_raw`` / ``quote_token`` / ``quote_amount_raw``); v4 rows
        carry ``liquidity`` only. Data since 2026-08-05.

        Args:
            limit: Max events (1–200, default 50).
            token: Filter to one token address (``0x`` + 40 hex).
            pool: Pool address (v2/v3) or bytes32 poolId (v4).
            provider: Filter to one liquidity provider (``0x`` + 40 hex).
            dex: ``'uniswap-v2'`` | ``'uniswap-v3'`` | ``'uniswap-v4'``.
            before: Opaque cursor — pass ``next_before`` from the previous
                response (same (block_time, id) keyset as :meth:`trades`).

        Route: ``GET /api/v1/rhc/lp-events``. Tier: PRO+. Alias
        ``GET /rhc/tokens/{address}/lp-events`` is the same feed with
        ``token`` pinned — use ``lp_events(token=address)``.
        """
        return self._get(
            "/rhc/lp-events",
            {
                "limit": limit,
                "token": token,
                "pool": pool,
                "provider": provider,
                "dex": dex,
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

    def equities(
        self,
        *,
        sort: Optional[str] = None,
        limit: int = 100,
        symbol: Optional[str] = None,
        q: Optional[str] = None,
    ) -> t.EquitiesResponse:
        """Tokenized stocks & ETFs on Robinhood Chain (BASIC+).

        Every official Robinhood tokenized equity (NVDA, SPY, AAPL, …) with
        live price / MC / liquidity and 24h trades / ETH volume / buyer-seller
        split. **Identity is the issuer BEACON, never the name**: a token is
        listed only if its contract is an EIP-1967 beacon proxy on Robinhood's
        issuer beacon, read from our own node — the 20 fake "GameStop •
        Robinhood Token" contracts and 8 fake NVDAs never appear here.
        ``verified`` is ``True`` by construction; ``name`` has the "• Robinhood
        Token" suffix stripped, ``onchain_name`` is the raw ERC-20 name. 24h
        stats are cached 60 s (``stats_as_of``).

        Args:
            sort: ``'volume'`` (default, 24h ETH volume) | ``'trades'`` |
                ``'market_cap'`` | ``'last_trade'`` | ``'symbol'``.
            limit: Max equities (1–300, default 100).
            symbol: Exact ticker, case-insensitive (``'NVDA'``).
            q: Substring of symbol or name.

        Route: ``GET /api/v1/rhc/equities``. Tier: BASIC.
        """
        return self._get(
            "/rhc/equities",
            {"sort": sort, "limit": limit, "symbol": symbol, "q": q},
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

    def token_top_traders(
        self, address: str, *, limit: int | None = None, offset: int | None = None
    ) -> dict:
        """Top traders of a Robinhood Chain token, ranked by realized ETH (PRO+).

        Lifetime per-trader performance on one token, enriched with wallet
        reputation (win-rate, bot heuristic, KOL identity), dump-cluster
        membership and early-buyer rank.

        ``net_eth`` is REALIZED flow (``sell − buy``) and is **not PnL**: it does
        not value a trader's remaining bag, so a wallet that bought and still
        holds ranks last. Use :meth:`wallet_pnl` for FIFO cost-basis PnL.

        Args:
            address: Token address (``0x`` + 40 hex).
            limit: Rows to return. Capped at 50 on PRO, 200 on ULTRA/BUSINESS.
            offset: Page offset.

        Route: ``GET /api/v1/rhc/tokens/{address}/top-traders``. Tier: PRO+.
        """
        return self._get(
            f"/rhc/tokens/{address}/top-traders",
            params={"limit": limit, "offset": offset},
        )

    def token_flow(self, address: str, *, window: str | None = None) -> dict:
        """Net buy/sell flow by trader cohort on a Robinhood Chain token (PRO+).

        Splits the token's flow into mutually-exclusive cohorts so you can see
        who is accumulating and who is distributing.

        Sign convention: ``net_eth = sell − buy``, so a POSITIVE value means the
        cohort **distributed** (took ETH out) and negative means it accumulated.
        Cohorts are assigned by a priority ladder: ``kol`` → ``bot`` →
        ``dump_cluster`` → ``early_buyer`` → ``unprofiled`` → ``smart_money`` →
        ``retail``. ``smart_money`` is derived (win-rate >= 0.5 and net
        positive), and ``unprofiled`` is a real answer — that trader has not met
        the reputation thresholds. There is no ``fresh_wallet`` cohort because
        Robinhood Chain stores no wallet-level first-seen.

        Args:
            address: Token address (``0x`` + 40 hex).
            window: One of ``1h``, ``6h``, ``24h``, ``7d``. Default ``24h``.

        Route: ``GET /api/v1/rhc/tokens/{address}/flow``. Tier: PRO+.
        """
        return self._get(f"/rhc/tokens/{address}/flow", params={"window": window})

    def token_peak_history(
        self, address: str, *, window: str | None = None, curve: str | None = None
    ) -> dict:
        """Peak market cap, drawdown and high-water curve (PRO+).

        Returns **two peaks, because they disagree**.
        ``peak_mc_usd_recorded`` is the stored high-water mark that every other
        Robinhood Chain surface keys off (deployer runner-rate, the $40K
        graduation bar); it is sampled from write batches so it can undercount an
        intra-batch spike. ``peak_mc_usd_observed`` is the max of 1-minute candle
        highs — trade-level truth, and always >= recorded.

        Candle history begins 2026-07-15, so check
        ``observed_covers_full_history`` before treating the observed figure as a
        lifetime maximum.

        Args:
            address: Token address (``0x`` + 40 hex).
            window: One of ``24h``, ``7d``, ``30d``, ``all``. Default ``7d``.
            curve: ``"false"`` to skip the series and return the summary only.

        Route: ``GET /api/v1/rhc/tokens/{address}/peak-history``. Tier: PRO+.
        """
        return self._get(
            f"/rhc/tokens/{address}/peak-history",
            params={"window": window, "curve": curve},
        )

    def token_risk(self, address: str) -> dict:
        """EVM-native risk assessment, computed LIVE on-chain (PRO+).

        **Not a port of the Solana risk model.** EVM has no mint or freeze
        authority: across 300 random Robinhood Chain tokens only 2.3% even expose
        an owner function and 0% expose ``mint`` in their own bytecode, so an
        absent capability flag is the norm rather than a safety signal.

        The signals that discriminate here are proxy upgradeability, LP custody
        and above all **sellability**, which is simulated at the chain head via a
        router call with state overrides and is never cached — whether a token can
        be sold changes the moment an owner flips a setting.

        Note ``owner.model == "none"`` (no owner function exists) is a different
        answer from ``"renounced"``. ``lp_custody`` is read only for uniswap-v2
        pools; v3/v4 liquidity sits in an LP NFT and reports ``"unknown"`` rather
        than being guessed.

        Args:
            address: Token address (``0x`` + 40 hex).

        Route: ``GET /api/v1/rhc/tokens/{address}/risk``. Tier: PRO+.
        """
        return self._get(f"/rhc/tokens/{address}/risk")

    def token_holders(
        self, address: str, *, limit: int | None = None, offset: int | None = None
    ) -> dict:
        """Exact holder set and concentration for a Robinhood Chain token (PRO+).

        Balances are folded from ERC-20 ``Transfer`` logs — **not** derived from
        trades — and reconciled against on-chain ``totalSupply()`` at a pinned
        block.

        **Check ``verified`` first.** ``False`` means the reconstruction is
        incomplete for that token, and ``unverified_reason`` says why (a token
        that only recently became liquid legitimately has partial history).

        Concentration **excludes liquidity pools and burn addresses** from the
        circulating denominator — the largest holder of a token is otherwise its
        own pool — and reports them separately as ``pool_held_pct`` /
        ``burned_pct``. ``balance`` is a raw uint256 returned as a decimal
        **string**; do not coerce it to a float. Holder addresses may be
        ERC-4337 smart accounts, so ``holder_count`` is not a headcount of people.

        ``holder_growth`` (:class:`~robinhood_chain.types.HolderGrowth`, keys
        ``"1h"`` / ``"24h"`` / ``"7d"`` + ``note``) reports per window:
        ``entered`` (addresses whose first ``Transfer`` of the token landed
        at-or-after ``cutoff_block``, any current balance),
        ``entered_still_holding`` (those still non-zero), ``exited``
        (pre-existing holders whose last ``Transfer`` in the window left them at
        zero) and ``net = entered_still_holding - exited`` ≈ Δ ``holder_count``.
        Pools and burns are excluded. A window is ``None`` only when the chain
        had no ingested trades in it; the whole object is ``None`` only if the
        growth read failed. Possible because the fold retains history — the
        Solana census cannot answer this.

        Args:
            address: Token address (``0x`` + 40 hex).
            limit: Rows to return. Capped at 50 on PRO, 200 on ULTRA/BUSINESS.
            offset: Page offset.

        Route: ``GET /api/v1/rhc/tokens/{address}/holders``. Tier: PRO+.
        """
        return self._get(
            f"/rhc/tokens/{address}/holders",
            params={"limit": limit, "offset": offset},
        )

    def token_batch(self, addresses: Sequence[str]) -> t.TokenBatchResponse:
        """Up to 50 Robinhood Chain tokens in ONE call (BASIC+).

        Set-based — three queries server-side regardless of batch size, not a
        fan-out of the single-token route. Each entry returns metadata, live
        price/MC/FDV/liquidity, peak MC, primary DEX and the deployer reputation
        block. Every REQUESTED address is echoed back, unknown ones as
        ``{'address': ..., 'found': False}``, so positions line up with what you
        sent.

        Narrower than :meth:`token` on purpose: it does NOT bundle buyer-quality
        (a per-token cohort computation) — use
        :meth:`tokens_batch_buyer_quality` for that.

        Args:
            addresses: 1–50 token addresses (``0x`` + 40 hex). Duplicates are
                de-duplicated server-side.

        Route: ``POST /api/v1/rhc/token/batch``. Tier: BASIC. 400 if the list is
        empty, over 50, or contains a non-EVM address.
        """
        return self._post("/rhc/token/batch", {"addresses": list(addresses)})

    def tokens_batch_buyer_quality(
        self, addresses: Sequence[str]
    ) -> t.BatchBuyerQualityResponse:
        """Early-buyer quality for up to 20 Robinhood Chain tokens (BASIC+).

        Batched :meth:`token_buyer_quality`: the 0–100 read on each token's
        earliest distinct buyer cohort. Per-token failures degrade to an entry
        carrying ``error`` rather than failing the whole batch, so one unpriced
        token never costs you the other 19 results.

        ⚠️ The cap is **20**, deliberately lower than the Solana batch cap of 50:
        RHC buyer-quality is a per-token cohort computation (ordered early-buyer
        scan + bundle detection + alpha/cluster joins), not one set-based query,
        so 50 would mean ~200 round-trips behind a single request. The cap is
        echoed back as ``max_addresses``.

        Args:
            addresses: 1–20 token addresses (``0x`` + 40 hex).

        Route: ``POST /api/v1/rhc/tokens/batch/buyer-quality``. Tier: BASIC.
        400 (with ``max_addresses``) if the list is empty, over 20, or contains
        a non-EVM address.
        """
        return self._post(
            "/rhc/tokens/batch/buyer-quality", {"addresses": list(addresses)}
        )

    # ── Deployer hunter: leaderboard / profile / alerts / history / stats ──

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

        ⚠️ TIER SEMANTICS (migrations 267 + 269): ``elite`` / ``good`` are earned
        on the $100K ``runner_rate`` and require 24h of deployer history — the
        $40K bar proved farmable by operators mass-relaunching one ticker across
        rotating wallets. ``graduation_rate`` is still returned and still means
        the $40K bar, but it NO LONGER determines the tier (``spammer`` is the
        one exception — detecting trash is a different question from detecting
        quality). Call :meth:`deployer_hunter_stats` for the live thresholds.

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

    def deployer_hunter_alerts(
        self,
        *,
        deployer_tier: Optional[str] = None,
        priority: Optional[str] = None,
        alert_type: Optional[str] = None,
        launchpad: Optional[str] = None,
        min_mc: Optional[float] = None,
        include_untradeable: Optional[bool] = None,
        since: Optional[str] = None,
        before: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> t.DeployerAlertsResponse:
        """Deployer signal feed on Robinhood Chain (BASIC+).

        Live alerts when a tracked deployer ships a new token or one of their
        tokens graduates ($40K+ peak MC). RHC domain values are narrower than
        Solana's: ``alert_type`` is ``new_deploy`` | ``graduated`` (no
        bonded/kol_buy), ``priority`` is ``high`` | ``medium`` (no low), and
        alerts carry no KOL join.

        ⚠️ TRADABILITY FILTER IS ON BY DEFAULT (2026-07-25): alerts whose token
        has ``liquidity_usd`` below $100 — or unknown liquidity, which on RHC
        usually means a drained pool — are dropped, because a $45K-MC alert on a
        token with $68 of liquidity is not a signal. Pass
        ``include_untradeable=True`` for the raw tape (archive/leaderboard
        tooling). The active setting is echoed as ``tradability_filter``.

        ⚠️ TIER IS RESOLVED AT READ TIME (2026-07-25): ``tier`` is the deployer's
        CURRENT tier from the reputation view, not the snapshot taken when the
        alert fired — the snapshot is returned alongside as ``tier_at_alert``,
        with ``tier_is_stale`` set when the two disagree. ``deployer_tier``
        filters on the RESOLVED value so the filter and the payload always
        agree. Tiers now ride the $100K ``runner_rate`` (migrations 267 + 269),
        so ``message`` is restated in those terms; ``graduation_rate`` still
        means the $40K bar but no longer sets the tier.

        Args:
            deployer_tier: ``'elite'`` | ``'good'`` | ``'neutral'`` |
                ``'spammer'`` — matched against the read-time tier.
            priority: ``'high'`` | ``'medium'``.
            alert_type: ``'new_deploy'`` | ``'graduated'``.
            launchpad: Filter by launchpad (1–32 chars).
            min_mc: Minimum market cap at alert time (USD).
            include_untradeable: ``True`` disables the $100 liquidity floor.
            since: ISO 8601 — only alerts with ``event_at`` strictly newer. The
                incremental-polling idiom: pass back ``next_event_at``.
            before: ISO 8601 cursor — only alerts strictly older. Pass
                ``next_before`` to page back. Takes precedence over ``offset``.
            limit: Max alerts (1–500, default 50). BASIC/PRO are capped at 50;
                only ULTRA gets the full requested limit.
            offset: Page offset (0–10000, default 0). Ignored when ``before``
                is set.

        Route: ``GET /api/v1/rhc/deployer-hunter/alerts``. Tier: BASIC.
        """
        return self._get(
            "/rhc/deployer-hunter/alerts",
            {
                "deployer_tier": deployer_tier,
                "priority": priority,
                "alert_type": alert_type,
                "launchpad": launchpad,
                "min_mc": min_mc,
                "include_untradeable": include_untradeable,
                "since": since,
                "before": before,
                "limit": limit,
                "offset": offset,
            },
        )

    def deployer_hunter_best_tokens(
        self, *, period: str = "7d", limit: int = 10
    ) -> t.BestTokensResponse:
        """Best tokens from reputable Robinhood Chain deployers (BASIC+).

        The highest-peaking tokens launched in the window by deployers that are
        currently ``elite`` or ``good`` — "what did the deployers worth tracking
        actually produce". Gated on reputation, not raw peak MC; the unfiltered
        version is ``tokens(sort='peak_mc')``.

        Reputation here means the $100K ``runner_rate`` tier (migrations 267 +
        269), not the $40K ``graduation_rate`` — the latter is still returned on
        each token's ``deployer`` block but no longer sets the tier.

        ``candidates_scanned`` reports how many launches were considered before
        ranking; if ``truncated`` is ``True`` the top-N was drawn from the 1000
        most RECENT launches in the period rather than the whole period.

        Args:
            period: ``'24h'`` | ``'7d'`` (default) | ``'30d'`` | ``'all'``.
            limit: Max tokens (1–50, default 10).

        Route: ``GET /api/v1/rhc/deployer-hunter/best-tokens``. Tier: BASIC.
        """
        return self._get(
            "/rhc/deployer-hunter/best-tokens", {"period": period, "limit": limit}
        )

    def deployer_hunter_recent_bonds(
        self,
        *,
        deployer_tier: Optional[str] = None,
        min_peak: Optional[float] = None,
        limit: int = 50,
    ) -> t.RecentBondsResponse:
        """Recent graduations on Robinhood Chain (BASIC+).

        Tokens that crossed the $40K peak-MC graduation milestone, newest peak
        first, with token metadata and the deployer's tier. On RHC a
        "graduation" is that MC milestone, NOT a bonding-curve completion —
        noxa/pons/clanker launch direct-to-DEX with no curve — so the set is
        defined purely by ``peak_mc_usd >= 40000``.

        Args:
            deployer_tier: Filter to ``'elite'`` | ``'good'`` | ``'neutral'`` |
                ``'spammer'``. Tiers ride the $100K runner rate (migrations 267
                + 269), not the $40K graduation bar this feed is keyed on.
            min_peak: Raise the peak-MC floor (USD). Never lowers it below the
                $40K graduation milestone.
            limit: Max tokens (1–200, default 50).

        Route: ``GET /api/v1/rhc/deployer-hunter/recent-bonds``. Tier: BASIC.
        """
        return self._get(
            "/rhc/deployer-hunter/recent-bonds",
            {
                "deployer_tier": deployer_tier,
                "min_peak": min_peak,
                "limit": limit,
            },
        )

    def deployer_hunter_stats(self) -> t.DeployerStatsResponse:
        """Chain-wide deployer reputation summary for Robinhood Chain (BASIC+).

        Population per tier (deployers + tokens), the reputable-deployer count,
        ``spam_token_share``, and 24h/7d alert volume — the denominator for any
        "is this deployer rare?" question.

        Also returns ``tier_rules``, the ACTIVE tier thresholds, so you can see
        what ``elite`` currently means instead of guessing from the label:
        ``elite`` / ``good`` are earned on the $100K ``runner_rate`` and require
        24h of deployer history (migrations 267 + 269), while ``spammer`` still
        keys off ``graduation_rate``. ``graduation_definition`` ($40K) and
        ``runner_definition`` ($100K) spell out both bars.

        Route: ``GET /api/v1/rhc/deployer-hunter/stats``. Tier: BASIC.
        """
        return self._get("/rhc/deployer-hunter/stats")

    def deployer_hunter_trajectory(self, address: str) -> t.DeployerTrajectoryResponse:
        """Is this Robinhood Chain deployer getting better or worse? (BASIC+)

        A shape-over-time read on one deployer's launch history: current and
        longest hit/miss streaks, a rolling 10-launch success rate, the best and
        worst 10-launch stretches, average days between deploys, and average
        launches burned between a miss and the next hit — plus a ``trend`` of
        ``'improving'`` | ``'declining'`` | ``'stable'``.

        The per-token success event is the $40K peak-MC GRADUATION milestone
        (echoed as ``success_metric``), NOT the $100K runner bar that migrations
        267 + 269 moved TIERS onto — $100K is rare enough that most deployers
        would return an all-zero curve, and a trajectory needs enough events to
        have a shape. Field names keep the Solana ``bond`` wording so the two
        chains' responses stay drop-in compatible.

        Analysis is capped at the 500 oldest→newest launches; ``truncated``
        tells you whether the curve is the whole story. Unknown wallets return
        200 with ``is_deployer: False`` (not a 404).

        Args:
            address: Deployer EVM wallet address (``0x`` + 40 hex).

        Route: ``GET /api/v1/rhc/deployer-hunter/{address}/trajectory``.
        Tier: BASIC.
        """
        return self._get(f"/rhc/deployer-hunter/{address}/trajectory")

    def deployer_hunter_tokens(
        self,
        address: str,
        *,
        limit: int = 50,
        offset: int = 0,
        sort: str = "first_seen_at",
    ) -> t.DeployerTokensResponse:
        """One deployer's full paginated launch history (BASIC+).

        Every token this deployer shipped, enriched with live MC, peak MC and
        liquidity. Distinct from :meth:`deployer_hunter_profile`, which caps
        ``recent_tokens`` at 50 and is a point-in-time profile read — this is the
        enumerable history with ``limit``/``offset`` and ``has_more``.

        Args:
            address: Deployer EVM wallet address (``0x`` + 40 hex).
            limit: Page size (1–100, default 50).
            offset: Page offset (0–10000, default 0).
            sort: ``'first_seen_at'`` (default, newest first — ordered in
                Postgres) | ``'peak_mc_usd'``. ⚠️ ``peak_mc_usd`` is a
                PAGE-SCOPED sort — peak MC lives in another table and is applied
                after enrichment of the requested page only, so it is NOT a
                global "top tokens by peak MC" ranking. The response echoes
                ``sort_scope: 'page'`` when it is in effect; use
                :meth:`deployer_hunter_best_tokens` for a real ranking.

        Route: ``GET /api/v1/rhc/deployer-hunter/{address}/tokens``. Tier: BASIC.
        Unknown wallets return 200 with ``is_deployer: False``.
        """
        return self._get(
            f"/rhc/deployer-hunter/{address}/tokens",
            {"limit": limit, "offset": offset, "sort": sort},
        )

    def deployer_hunter_history(
        self, address: str, *, limit: int = 100, offset: int = 0
    ) -> t.DeployerHistoryResponse:
        """One deployer's deploy history with graduation detail (PRO+).

        The reputation row plus every token deployed — newest first, with a
        stable tiebreaker so paginated pages never overlap or skip — enriched
        with live and peak MC and the ``graduated_pool``. ``total`` is an exact
        count.

        RHC has no per-day reputation snapshot table (that is Solana-only), so
        unlike the Solana ``/history`` this is a token-deploy history, not a
        daily tier/rate time-series. For the shape-over-time read use
        :meth:`deployer_hunter_trajectory`.

        Args:
            address: Deployer EVM wallet address (``0x`` + 40 hex).
            limit: Page size (1–1000, default 100).
            offset: Page offset (0–100000, default 0).

        Route: ``GET /api/v1/rhc/deployer-hunter/{address}/history``. Tier: PRO+
        (the point-in-time :meth:`deployer_hunter_profile` stays BASIC). Unknown
        wallets return 200 with ``is_deployer: False``.
        """
        return self._get(
            f"/rhc/deployer-hunter/{address}/history",
            {"limit": limit, "offset": offset},
        )

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

    # ── Wallet intelligence ────────────────────────────────────────────────
    #
    # ``wallet``, ``wallet_pnl`` and ``wallet_positions`` read from ONE shared
    # 90-day snapshot cache, so calling all three on the same address costs
    # roughly one computation, not three — ``cache_hit`` says which call paid
    # for it. Everything is ETH-denominated.

    def wallet(self, address: str) -> t.WalletProfileResponse:
        """Any Robinhood Chain wallet's 90-day trading profile (PRO+).

        FIFO cost-basis PnL, per-token breakdown, recent trades, and a
        reputation block: tracked KOL, known deployer + tier, alpha-ranked,
        dump-cluster membership, early-buyer count.

        ``stats.unattributed_trades`` counts pre-2026-07-18 rows whose
        ``trader_eoa`` is NULL — unattributable by design, not a gap you can
        backfill. ``stats_unavailable`` is True when the snapshot timed out;
        ``flags`` still resolve in that case.

        Args:
            address: Wallet EVM address (``0x`` + 40 hex). Case-insensitive.

        Route: ``GET /api/v1/rhc/wallet/{address}``. Tier: PRO+.
        """
        return self._get(f"/rhc/wallet/{address}")

    def wallet_pnl(self, address: str) -> t.WalletPnlResponse:
        """Full FIFO cost-basis PnL for one RHC wallet over 90 days (PRO+).

        Realized/unrealized split, a daily realized curve, every closed
        position with ROI and hold time, and every open position marked to the
        current price. This is the *same* FIFO implementation as the Solana
        ``/wallet/{address}/pnl``, so the two chains are directly comparable.

        ``notes.cost_basis_observable_from`` is the date the window opens: buys
        before it are invisible, which is why a long-held position can show as
        a sell with no matching buy.

        Args:
            address: Wallet EVM address (``0x`` + 40 hex).

        Route: ``GET /api/v1/rhc/wallet/{address}/pnl``. Tier: PRO+.
        """
        return self._get(f"/rhc/wallet/{address}/pnl")

    def wallet_positions(self, address: str) -> t.WalletPositionsResponse:
        """Only what the wallet still holds, marked to market (PRO+).

        The same FIFO pass as :meth:`wallet_pnl` without the curve and closed
        positions — for clients polling "what is this wallet in right now".

        Check ``positions[].liquidity_basis``: ``'v4_virtual_ceiling'`` means
        ``liquidity_usd`` is a bonding-curve ceiling, NOT withdrawable TVL, so
        do not size an exit against it.

        Args:
            address: Wallet EVM address (``0x`` + 40 hex).

        Route: ``GET /api/v1/rhc/wallet/{address}/positions``. Tier: PRO+.
        """
        return self._get(f"/rhc/wallet/{address}/positions")

    def wallet_trades(
        self,
        address: str,
        *,
        limit: int = 50,
        before: Optional[str] = None,
        since: Optional[str] = None,
        action: Optional[str] = None,
        token: Optional[str] = None,
    ) -> t.WalletTradesResponse:
        """One wallet's swaps, newest first, cursor-paginated (PRO+).

        Distinct from ``trades(token=...)``: that filters the global tape by
        TOKEN, this filters by WALLET — a different index path.

        Poll forward by passing the previous response's ``next_before`` back as
        ``before``; the cursor is an opaque keyset, not an offset.

        Args:
            address: Wallet EVM address (``0x`` + 40 hex).
            limit: Page size (1–200, default 50).
            before: Opaque cursor from a prior response's ``next_before``.
            since: ISO-8601 timestamp with offset.
            action: ``'buy'`` | ``'sell'``.
            token: Restrict to one token address (``0x`` + 40 hex).

        Route: ``GET /api/v1/rhc/wallet/{address}/trades``. Tier: PRO+.
        """
        return self._get(
            f"/rhc/wallet/{address}/trades",
            {
                "limit": limit,
                "before": before,
                "since": since,
                "action": action,
                "token": token,
            },
        )

    # ── Wallet tracker (watchlist) ─────────────────────────────────────────

    def wallet_tracker_list(self) -> t.WalletTrackerWatchlistResponse:
        """Your Robinhood Chain watchlist (PRO+).

        Quotas are **per chain** — PRO 50 / ULTRA 100 / BUSINESS 500 RHC
        wallets, independent of your Solana watchlist, so adopting RHC never
        shrinks an existing Solana list.

        Route: ``GET /api/v1/rhc/wallet-tracker/watchlist``. Tier: PRO+.
        """
        return self._get("/rhc/wallet-tracker/watchlist")

    def wallet_tracker_add(
        self, wallet_address: str, *, label: Optional[str] = None
    ) -> t.WalletTrackerWalletResponse:
        """Add a wallet to your RHC watchlist (PRO+).

        The address is stored lowercase so it matches ``rhc_trades.trader_eoa``
        — a checksummed ``0xAbC…`` would join to nothing and look like a
        permanently silent wallet. Returns 409 if already tracked.

        Args:
            wallet_address: Wallet EVM address (``0x`` + 40 hex).
            label: Optional human label.

        Route: ``POST /api/v1/rhc/wallet-tracker/watchlist``. Tier: PRO+.
        """
        return self._post(
            "/rhc/wallet-tracker/watchlist",
            self._body({"wallet_address": wallet_address, "label": label}),
        )

    def wallet_tracker_remove(self, address: str) -> t.WalletTrackerRemovedResponse:
        """Remove a wallet from your RHC watchlist (PRO+).

        Args:
            address: Tracked wallet EVM address.

        Route: ``DELETE /api/v1/rhc/wallet-tracker/watchlist/{address}``.
        Tier: PRO+.
        """
        return self._delete(f"/rhc/wallet-tracker/watchlist/{address}")

    def wallet_tracker_relabel(
        self, address: str, label: Optional[str]
    ) -> t.WalletTrackerWalletResponse:
        """Relabel a tracked wallet (PRO+).

        Args:
            address: Tracked wallet EVM address.
            label: New label, or ``None`` to clear it.

        Route: ``PATCH /api/v1/rhc/wallet-tracker/watchlist/{address}``.
        Tier: PRO+.
        """
        return self._patch(
            f"/rhc/wallet-tracker/watchlist/{address}", {"label": label}
        )

    def wallet_tracker_trades(
        self,
        *,
        limit: int = 50,
        before: Optional[str] = None,
        wallet: Optional[str] = None,
        action: Optional[str] = None,
        token: Optional[str] = None,
    ) -> t.WalletTrackerTradesResponse:
        """Merged trade feed across your tracked RHC wallets (PRO+).

        Every trade by every wallet on your watchlist, newest first, each row
        labelled with its watchlist label. The cursor (``next_before``) is an
        opaque keyset matching the rest of the RHC tree, not the Solana
        tracker's integer epoch.

        Args:
            limit: Page size (1–200, default 50).
            before: Opaque cursor from a prior response's ``next_before``.
            wallet: Restrict to one wallet — must already be tracked.
            action: ``'buy'`` | ``'sell'``.
            token: Restrict to one token address.

        Route: ``GET /api/v1/rhc/wallet-tracker/trades``. Tier: PRO+.
        """
        return self._get(
            "/rhc/wallet-tracker/trades",
            {
                "limit": limit,
                "before": before,
                "wallet": wallet,
                "action": action,
                "token": token,
            },
        )

    def wallet_tracker_summary(
        self, *, period: str = "7d", wallet: Optional[str] = None
    ) -> t.WalletTrackerSummaryResponse:
        """Per-wallet buy/sell/volume rollup across your tracked wallets (PRO+).

        Sourced from ``rhc_trades`` directly, not from a per-subscriber capture
        log: on RHC every swap is already recorded, so adding a wallet gives
        you its history immediately rather than only from the moment you
        started tracking it. (The Solana tracker cannot do this — there, trades
        are only captured for wallets somebody asked for.)

        Args:
            period: Lookback window, default ``'7d'``.
            wallet: Restrict the rollup to one tracked wallet.

        Route: ``GET /api/v1/rhc/wallet-tracker/summary``. Tier: PRO+.
        """
        return self._get(
            "/rhc/wallet-tracker/summary", {"period": period, "wallet": wallet}
        )

    # ── Rule engine: copy-trade ────────────────────────────────────────────

    def copytrade_subscriptions_list(self) -> t.CopyTradeListResponse:
        """Your Robinhood Chain copy-trade rules (PRO+).

        Quotas are PER CHAIN — PRO 3 rules x 5 wallets / ULTRA 20 x 50 /
        BUSINESS 100 x 250, independent of your Solana copy-trade rules.

        Route: ``GET /api/v1/rhc/copytrade/subscriptions``. Tier: PRO.
        """
        return self._get("/rhc/copytrade/subscriptions")

    def copytrade_subscriptions_create(
        self,
        *,
        source_wallets: Sequence[str],
        sizing_amount: float,
        name: Optional[str] = None,
        min_trade_eth: Optional[float] = None,
        only_action: Optional[str] = None,
        sizing_mode: Optional[str] = None,
        delivery_mode: Optional[str] = None,
        webhook_url: Optional[str] = None,
    ) -> t.CopyTradeCreateResponse:
        """Create a copy-trade rule on Robinhood Chain (PRO+).

        Fires when one of ``source_wallets`` trades on chain 4663. Two
        deliberate differences from the Solana engine, both forced by what the
        producer emits: amounts are **ETH**, not SOL, and there is no
        ``min_mc_usd``/``max_mc_usd`` band — the RHC notify payload carries no
        market cap, so a band could only be a per-event DB lookup in the hot
        path of a ~3.3M trades/day chain, or a filter that silently never
        matches.

        ``webhook_secret`` is returned **once**. Payloads are signed HMAC-SHA256
        over ``<timestamp>.<body>`` in the ``X-MadeOnSol-Signature`` header.

        Args:
            source_wallets: 1–250 EVM addresses (``0x`` + 40 hex). Lowercased on
                write; the per-tier cap is enforced server-side (400 if over).
            sizing_amount: ETH when ``sizing_mode='fixed'``, else a multiplier
                of the source trade. Must be > 0.
            name: Optional label (1–64 chars).
            min_trade_eth: Minimum source-trade size in ETH (default 0).
            only_action: ``'buy'`` (default) | ``'sell'`` | ``'both'``.
            sizing_mode: ``'fixed'`` (default) | ``'proportional'`` |
                ``'percent_source'``.
            delivery_mode: ``'webhook'`` (default) | ``'websocket'`` |
                ``'both'``.
            webhook_url: HTTPS only. Required unless
                ``delivery_mode='websocket'``.

        Route: ``POST /api/v1/rhc/copytrade/subscriptions``. Tier: PRO. 409 when
        the tier's rule limit is already reached.
        """
        return self._post(
            "/rhc/copytrade/subscriptions",
            self._body(
                {
                    "name": name,
                    "source_wallets": list(source_wallets),
                    "min_trade_eth": min_trade_eth,
                    "only_action": only_action,
                    "sizing_mode": sizing_mode,
                    "sizing_amount": sizing_amount,
                    "delivery_mode": delivery_mode,
                    "webhook_url": webhook_url,
                }
            ),
        )

    def copytrade_subscriptions_get(
        self, subscription_id: int
    ) -> t.CopyTradeGetResponse:
        """Fetch one Robinhood Chain copy-trade rule (PRO+).

        Args:
            subscription_id: Numeric rule id.

        Route: ``GET /api/v1/rhc/copytrade/subscriptions/{id}``. Tier: PRO.
        404 if the rule is not yours.
        """
        return self._get(f"/rhc/copytrade/subscriptions/{subscription_id}")

    def copytrade_subscriptions_update(
        self,
        subscription_id: int,
        *,
        name: Optional[Any] = None,
        source_wallets: Optional[Sequence[str]] = None,
        min_trade_eth: Optional[float] = None,
        only_action: Optional[str] = None,
        sizing_mode: Optional[str] = None,
        sizing_amount: Optional[float] = None,
        delivery_mode: Optional[str] = None,
        webhook_url: Optional[Any] = None,
        is_active: Optional[bool] = None,
    ) -> t.CopyTradeGetResponse:
        """Partially update a Robinhood Chain copy-trade rule (PRO+).

        Only the fields you pass are changed. The per-tier wallet cap is
        re-checked, so a PRO rule created at 5 wallets cannot be PATCHed to 250.

        Args:
            subscription_id: Numeric rule id.
            name: New label, or :data:`NULL` to clear it.
            source_wallets: Replacement wallet list (whole-list replace).
            min_trade_eth: Minimum source-trade size in ETH.
            only_action: ``'buy'`` | ``'sell'`` | ``'both'``.
            sizing_mode: ``'fixed'`` | ``'proportional'`` | ``'percent_source'``.
            sizing_amount: ETH or multiplier, per ``sizing_mode``.
            delivery_mode: ``'webhook'`` | ``'websocket'`` | ``'both'``.
            webhook_url: New HTTPS URL, or :data:`NULL` to clear it.
            is_active: Pause (``False``) or resume (``True``) the rule.

        Route: ``PATCH /api/v1/rhc/copytrade/subscriptions/{id}``. Tier: PRO.
        400 when no fields are supplied.
        """
        return self._patch(
            f"/rhc/copytrade/subscriptions/{subscription_id}",
            self._body(
                {
                    "name": name,
                    "source_wallets": list(source_wallets) if source_wallets else None,
                    "min_trade_eth": min_trade_eth,
                    "only_action": only_action,
                    "sizing_mode": sizing_mode,
                    "sizing_amount": sizing_amount,
                    "delivery_mode": delivery_mode,
                    "webhook_url": webhook_url,
                    "is_active": is_active,
                }
            ),
        )

    def copytrade_subscriptions_delete(
        self, subscription_id: int
    ) -> t.DeletedResponse:
        """Delete a Robinhood Chain copy-trade rule (PRO+).

        Its recorded signals cascade with it.

        Args:
            subscription_id: Numeric rule id.

        Route: ``DELETE /api/v1/rhc/copytrade/subscriptions/{id}``. Tier: PRO.
        """
        return self._delete(f"/rhc/copytrade/subscriptions/{subscription_id}")

    def copytrade_signals(
        self,
        *,
        subscription_id: Optional[int] = None,
        since: Optional[str] = None,
        limit: int = 50,
    ) -> t.CopyTradeSignalsResponse:
        """Fire history for your RHC copy-trade rules (PRO+).

        The catch-up path for a consumer that missed a webhook or was
        disconnected from the ``rhc:copytrade:signals`` channel. Retained 7 days.

        Args:
            subscription_id: Scope to one of your rules. 404 if you do not own
                it. Omit for every rule you have.
            since: ISO 8601 lower bound on ``fired_at``.
            limit: Max signals (1–500, default 50).

        Route: ``GET /api/v1/rhc/copytrade/signals``. Tier: PRO.
        """
        return self._get(
            "/rhc/copytrade/signals",
            {
                "subscription_id": subscription_id,
                "since": since,
                "limit": limit,
            },
        )

    # ── Rule engine: price alerts ──────────────────────────────────────────

    def price_alerts_list(self) -> t.PriceAlertListResponse:
        """Your Robinhood Chain price alerts (PRO+).

        Quota is per chain — RHC alerts do not consume the Solana budget.

        Route: ``GET /api/v1/rhc/price-alerts``. Tier: PRO.
        """
        return self._get("/rhc/price-alerts")

    def price_alerts_create(
        self,
        *,
        token_address: str,
        drop_pct: float,
        name: Optional[str] = None,
        recovery_pct: Optional[float] = None,
        delivery_mode: Optional[str] = None,
        webhook_url: Optional[str] = None,
    ) -> t.PriceAlertCreateResponse:
        """Create a Robinhood Chain price alert (PRO+).

        The baseline market cap is captured **at creation**, so the alert is a
        delta from the moment you set it — the token must already be tracked on
        RHC with a market cap, else 400.

        ⚠️ RHC alerts are POLLED (~15s off ``rhc_token_prices``), not evaluated
        inside a live price loop: the RHC price writer runs on a separate box
        and emits no ``pg_notify``, so there is nothing to react to. Effective
        latency is that interval plus the token's own price-update cadence — do
        NOT assume parity with the Solana alerts, which are sub-second. The
        response spells this out in its ``evaluation`` block.

        Args:
            token_address: Token address (``0x`` + 40 hex), lowercased on write.
            drop_pct: Drop from baseline that fires the dip (0.01–99.99).
            name: Optional label (1–64 chars).
            recovery_pct: Bounce off the dip low that fires a recovery
                (0.01–1000). Omit for a dip-only, terminal alert.
            delivery_mode: ``'webhook'`` (default) | ``'websocket'`` |
                ``'both'``.
            webhook_url: HTTPS only. Required unless
                ``delivery_mode='websocket'``.

        Route: ``POST /api/v1/rhc/price-alerts``. Tier: PRO. 409 when the tier's
        alert limit is already reached.
        """
        return self._post(
            "/rhc/price-alerts",
            self._body(
                {
                    "name": name,
                    "token_address": token_address,
                    "drop_pct": drop_pct,
                    "recovery_pct": recovery_pct,
                    "delivery_mode": delivery_mode,
                    "webhook_url": webhook_url,
                }
            ),
        )

    def price_alerts_get(self, alert_id: int) -> t.PriceAlertGetResponse:
        """Fetch one Robinhood Chain price alert (PRO+).

        Args:
            alert_id: Numeric alert id.

        Route: ``GET /api/v1/rhc/price-alerts/{id}``. Tier: PRO. 404 if the
        alert is not yours.
        """
        return self._get(f"/rhc/price-alerts/{alert_id}")

    def price_alerts_update(
        self,
        alert_id: int,
        *,
        name: Optional[Any] = None,
        delivery_mode: Optional[str] = None,
        webhook_url: Optional[Any] = None,
        is_active: Optional[bool] = None,
    ) -> t.PriceAlertGetResponse:
        """Update a Robinhood Chain price alert (PRO+).

        ``token_address``, ``drop_pct`` and ``recovery_pct`` are immutable —
        retuning the threshold of an already-dipped alert would make its
        recorded events uninterpretable. Delete and recreate instead.

        Args:
            alert_id: Numeric alert id.
            name: New label, or :data:`NULL` to clear it.
            delivery_mode: ``'webhook'`` | ``'websocket'`` | ``'both'``.
            webhook_url: New HTTPS URL, or :data:`NULL` to clear it.
            is_active: Pause (``False``) or resume (``True``) the alert.

        Route: ``PATCH /api/v1/rhc/price-alerts/{id}``. Tier: PRO. 400 when no
        fields are supplied.
        """
        return self._patch(
            f"/rhc/price-alerts/{alert_id}",
            self._body(
                {
                    "name": name,
                    "delivery_mode": delivery_mode,
                    "webhook_url": webhook_url,
                    "is_active": is_active,
                }
            ),
        )

    def price_alerts_delete(self, alert_id: int) -> t.DeletedResponse:
        """Delete a Robinhood Chain price alert (PRO+).

        Its recorded dip/recovery events cascade with it.

        Args:
            alert_id: Numeric alert id.

        Route: ``DELETE /api/v1/rhc/price-alerts/{id}``. Tier: PRO.
        """
        return self._delete(f"/rhc/price-alerts/{alert_id}")

    def price_alerts_events(
        self,
        *,
        alert_id: Optional[int] = None,
        event_type: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 50,
    ) -> t.PriceAlertEventsResponse:
        """Dip and recovery fire history for your RHC alerts (PRO+).

        The catch-up path when a webhook was missed or the
        ``rhc:price_alert:events`` channel was disconnected. Retained 30 days.

        Args:
            alert_id: Scope to one of your alerts. 404 if you do not own it.
            event_type: ``'dip'`` or ``'recovery'``.
            since: ISO 8601 lower bound on ``fired_at``.
            limit: Max events (1–500, default 50).

        Route: ``GET /api/v1/rhc/price-alerts/events``. Tier: PRO.
        """
        return self._get(
            "/rhc/price-alerts/events",
            {
                "alert_id": alert_id,
                "event_type": event_type,
                "since": since,
                "limit": limit,
            },
        )

    # ── Rule engine: KOL coordination ──────────────────────────────────────

    def coordination_alerts_list(self) -> t.CoordinationAlertListResponse:
        """Your Robinhood Chain coordination alert rules (PRO+).

        Quota is per chain. See :meth:`kol_coordination` for the read-only feed
        of what is coordinating right now.

        Route: ``GET /api/v1/rhc/kol/coordination/alerts``. Tier: PRO.
        """
        return self._get("/rhc/kol/coordination/alerts")

    def coordination_alerts_create(
        self,
        *,
        name: Optional[str] = None,
        min_kols: Optional[int] = None,
        window_minutes: Optional[int] = None,
        min_score: Optional[int] = None,
        cooldown_min: Optional[int] = None,
        score_jump_break: Optional[int] = None,
        min_mc_usd: Optional[float] = None,
        max_mc_usd: Optional[float] = None,
        delivery_mode: Optional[str] = None,
        webhook_url: Optional[str] = None,
    ) -> t.CoordinationAlertCreateResponse:
        """Create a Robinhood Chain coordination alert rule (PRO+).

        Fires when N+ tracked KOLs buy the same RHC token inside a rolling
        window.

        Scoring is the shared v1 scorer, so the number is comparable to Solana,
        but the ``earliness`` component is **defaulted** on RHC (no early-entry
        equivalent exists) while ``quality`` is a real KOL win-rate. Every fired
        signal records which components were real in its ``score_inputs``, and
        the create response returns the same breakdown as ``scoring``.

        Args:
            name: Optional label (1–64 chars).
            min_kols: Distinct KOL buyers needed to fire (2–50, default 3).
            window_minutes: Rolling window they must land inside (1–60,
                default 15).
            min_score: Minimum coordination score to deliver (0–100, default 0).
            cooldown_min: Minutes before the same token can fire again (1–1440,
                default 30).
            score_jump_break: Score jump that breaks the cooldown early (0–100,
                default 20).
            min_mc_usd: Lower bound on market cap (USD).
            max_mc_usd: Upper bound on market cap (USD). Must be >=
                ``min_mc_usd``.
            delivery_mode: ``'websocket'`` (default) | ``'webhook'`` |
                ``'both'``.
            webhook_url: HTTPS only. Required unless
                ``delivery_mode='websocket'``.

        Route: ``POST /api/v1/rhc/kol/coordination/alerts``. Tier: PRO. 409 when
        the tier's rule limit is already reached.
        """
        return self._post(
            "/rhc/kol/coordination/alerts",
            self._body(
                {
                    "name": name,
                    "min_kols": min_kols,
                    "window_minutes": window_minutes,
                    "min_score": min_score,
                    "cooldown_min": cooldown_min,
                    "score_jump_break": score_jump_break,
                    "min_mc_usd": min_mc_usd,
                    "max_mc_usd": max_mc_usd,
                    "delivery_mode": delivery_mode,
                    "webhook_url": webhook_url,
                }
            ),
        )

    def coordination_alerts_get(self, rule_id: str) -> t.CoordinationAlertGetResponse:
        """Fetch one Robinhood Chain coordination rule (PRO+).

        Args:
            rule_id: Rule UUID.

        Route: ``GET /api/v1/rhc/kol/coordination/alerts/{id}``. Tier: PRO.
        400 on a malformed UUID, 404 if the rule is not yours.
        """
        return self._get(f"/rhc/kol/coordination/alerts/{rule_id}")

    def coordination_alerts_update(
        self,
        rule_id: str,
        *,
        name: Optional[Any] = None,
        min_kols: Optional[int] = None,
        window_minutes: Optional[int] = None,
        min_score: Optional[int] = None,
        cooldown_min: Optional[int] = None,
        score_jump_break: Optional[int] = None,
        min_mc_usd: Optional[Any] = None,
        max_mc_usd: Optional[Any] = None,
        delivery_mode: Optional[str] = None,
        webhook_url: Optional[Any] = None,
        is_active: Optional[bool] = None,
    ) -> t.CoordinationAlertGetResponse:
        """Partially update a Robinhood Chain coordination rule (PRO+).

        The MC band is only cross-checked when BOTH bounds arrive in the same
        call; the table CHECK is the real backstop.

        Args:
            rule_id: Rule UUID.
            name: New label, or :data:`NULL` to clear it.
            min_kols: Distinct KOL buyers needed to fire (2–50).
            window_minutes: Rolling window (1–60).
            min_score: Minimum coordination score (0–100).
            cooldown_min: Per-token cooldown in minutes (1–1440).
            score_jump_break: Score jump that breaks the cooldown (0–100).
            min_mc_usd: Lower MC bound, or :data:`NULL` to remove it.
            max_mc_usd: Upper MC bound, or :data:`NULL` to remove it.
            delivery_mode: ``'websocket'`` | ``'webhook'`` | ``'both'``.
            webhook_url: New HTTPS URL, or :data:`NULL` to clear it.
            is_active: Pause (``False``) or resume (``True``) the rule.

        Route: ``PATCH /api/v1/rhc/kol/coordination/alerts/{id}``. Tier: PRO.
        400 when no fields are supplied.
        """
        return self._patch(
            f"/rhc/kol/coordination/alerts/{rule_id}",
            self._body(
                {
                    "name": name,
                    "min_kols": min_kols,
                    "window_minutes": window_minutes,
                    "min_score": min_score,
                    "cooldown_min": cooldown_min,
                    "score_jump_break": score_jump_break,
                    "min_mc_usd": min_mc_usd,
                    "max_mc_usd": max_mc_usd,
                    "delivery_mode": delivery_mode,
                    "webhook_url": webhook_url,
                    "is_active": is_active,
                }
            ),
        )

    def coordination_alerts_delete(self, rule_id: str) -> t.DeletedResponse:
        """Delete a Robinhood Chain coordination rule (PRO+).

        Its per-token cooldown state and fired signals cascade with it.

        Args:
            rule_id: Rule UUID.

        Route: ``DELETE /api/v1/rhc/kol/coordination/alerts/{id}``. Tier: PRO.
        """
        return self._delete(f"/rhc/kol/coordination/alerts/{rule_id}")

    # ── Rule engine: KOL first touches ─────────────────────────────────────

    def first_touch_subscriptions_list(
        self,
    ) -> t.FirstTouchSubscriptionListResponse:
        """Your Robinhood Chain first-touch subscriptions (ULTRA+).

        Quota is per chain. See :meth:`kol_first_touches` for the read-only feed
        of first touches that already happened.

        Route: ``GET /api/v1/rhc/kol/first-touches/subscriptions``. Tier: ULTRA.
        """
        return self._get("/rhc/kol/first-touches/subscriptions")

    def first_touch_subscriptions_create(
        self,
        *,
        name: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        delivery_mode: Optional[str] = None,
        webhook_url: Optional[str] = None,
    ) -> t.FirstTouchSubscriptionCreateResponse:
        """Create a Robinhood Chain first-touch subscription (ULTRA+).

        Pushes when a token gets its FIRST tracked-KOL buy — the discovery
        signal, not a second trade feed.

        The filter set is deliberately NOT the Solana one. RHC has no
        ``mv_kol_scout_score``, so ``min_scout_tier`` and ``min_n_touches`` are
        not offered at all rather than silently matching nothing; what RHC does
        have is a KOL win-rate, so ``min_kol_winrate`` and ``strategy`` are the
        quality gates. Unknown filter keys are REJECTED with a 400.

        Args:
            name: Optional label (1–64 chars).
            filters: Any of ``kol`` (``0x`` + 40 hex), ``min_first_buy_eth``
                (0–100000), ``min_kol_winrate`` (0–1, measured on CLOSED
                positions — a KOL who has never sold is unscored and drops out
                rather than counting as a loser), ``strategy``
                (``'scalper'`` | ``'day_trader'`` | ``'swing'`` | ``'inactive'``
                | ``'unscored'``), ``min_mc_usd``, ``max_mc_usd``. Default
                ``{}`` = every first touch.
            delivery_mode: ``'websocket'`` (default) | ``'webhook'`` |
                ``'both'``.
            webhook_url: HTTPS only. Required unless
                ``delivery_mode='websocket'``.

        Route: ``POST /api/v1/rhc/kol/first-touches/subscriptions``.
        Tier: ULTRA. 409 when the tier's subscription limit is already reached.
        """
        return self._post(
            "/rhc/kol/first-touches/subscriptions",
            self._body(
                {
                    "name": name,
                    "filters": filters,
                    "delivery_mode": delivery_mode,
                    "webhook_url": webhook_url,
                }
            ),
        )

    def first_touch_subscriptions_get(
        self, subscription_id: str
    ) -> t.FirstTouchSubscriptionGetResponse:
        """Fetch one Robinhood Chain first-touch subscription (ULTRA+).

        Args:
            subscription_id: Subscription UUID.

        Route: ``GET /api/v1/rhc/kol/first-touches/subscriptions/{id}``.
        Tier: ULTRA. 400 on a malformed UUID, 404 if it is not yours.
        """
        return self._get(f"/rhc/kol/first-touches/subscriptions/{subscription_id}")

    def first_touch_subscriptions_update(
        self,
        subscription_id: str,
        *,
        name: Optional[Any] = None,
        filters: Optional[Dict[str, Any]] = None,
        delivery_mode: Optional[str] = None,
        webhook_url: Optional[Any] = None,
        is_active: Optional[bool] = None,
    ) -> t.FirstTouchSubscriptionGetResponse:
        """Update a Robinhood Chain first-touch subscription (ULTRA+).

        ``filters`` is a whole-object **replace**, not a merge — merging would
        make "remove this filter" impossible to express. Send the complete
        filter set you want, or ``{}`` to clear every filter.

        Args:
            subscription_id: Subscription UUID.
            name: New label, or :data:`NULL` to clear it.
            filters: Replacement filter object (see
                :meth:`first_touch_subscriptions_create`).
            delivery_mode: ``'websocket'`` | ``'webhook'`` | ``'both'``.
            webhook_url: New HTTPS URL, or :data:`NULL` to clear it.
            is_active: Pause (``False``) or resume (``True``) the subscription.

        Route: ``PATCH /api/v1/rhc/kol/first-touches/subscriptions/{id}``.
        Tier: ULTRA. 400 when no fields are supplied.
        """
        return self._patch(
            f"/rhc/kol/first-touches/subscriptions/{subscription_id}",
            self._body(
                {
                    "name": name,
                    "filters": filters,
                    "delivery_mode": delivery_mode,
                    "webhook_url": webhook_url,
                    "is_active": is_active,
                }
            ),
        )

    def first_touch_subscriptions_delete(
        self, subscription_id: str
    ) -> t.DeletedResponse:
        """Delete a Robinhood Chain first-touch subscription (ULTRA+).

        Args:
            subscription_id: Subscription UUID.

        Route: ``DELETE /api/v1/rhc/kol/first-touches/subscriptions/{id}``.
        Tier: ULTRA.
        """
        return self._delete(
            f"/rhc/kol/first-touches/subscriptions/{subscription_id}"
        )

    # ── Streaming ──────────────────────────────────────────────────────────

    def stream_token(self) -> Dict[str, Any]:
        """Issue a 24h WebSocket streaming token (PRO+).

        Returns ``token``, ``expires_at``, ``next_refresh_at`` (rotate ~1h
        before expiry), ``ws_url`` (``wss://madeonsol.com/ws/v1/stream`` — the
        endpoint ALL six RHC channels ride; unlike Solana there is no separate
        RHC firehose endpoint), the full ``channels`` list the server accepts,
        a ``subscribe_example``, a human-readable ``usage`` string, and — on
        ULTRA/BUSINESS only — ``dex_ws_url``, the separate *Solana* DEX
        firehose endpoint (not used for RHC).

        Idempotent-ish: while your current token still has >6h of life (and
        your tier is unchanged) the same token is returned, so multi-process
        clients minting at boot do not invalidate each other. On rotation the
        previous token stays valid for a 60s grace window.

        Prefer :meth:`stream` unless you are hand-rolling the WebSocket.

        Route: ``POST /api/v1/stream/token``. Tier: PRO+.
        """
        return self._post("/stream/token")

    def stream(
        self, *, auto_reconnect: bool = True, max_backoff: float = 30.0
    ) -> "RobinhoodStream":
        """Open a managed real-time WebSocket stream — auto-reconnect, 24h-token
        refresh, and typed callbacks. Requires the optional ``websockets``
        extra::

            pip install "robinhood-chain[stream]"

        Example::

            stream = client.stream()
            stream.on("rhc:kol_trade", lambda d: print(d["token_address"]))
            stream.subscribe(["rhc:kol_trades"])
            await stream.run()

        The six channels are listed in :data:`robinhood_chain.stream.CHANNELS`
        (``rhc:dex_trades`` is ULTRA+; the rest are PRO+). If a subscribe names
        an invalid or tier-gated channel the server answers with a
        ``channels_rejected`` warning frame — register
        ``stream.on("warning", ...)`` to handle it, or it is raised through
        :func:`warnings.warn` so it can never pass silently.
        """
        from .stream import RobinhoodStream

        async def _token() -> Dict[str, Any]:
            return await asyncio.to_thread(self.stream_token)

        return RobinhoodStream(
            _token, auto_reconnect=auto_reconnect, max_backoff=max_backoff
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

    Each endpoint method (the 54 RHC operations plus ``stream_token``) is
    exposed as a coroutine with the same signature as its sync twin. The endpoint methods build their (path, params
    or JSON body) on the shared sync instance and dispatch through the async
    transport, so the two paths can never drift.
    """

    def __init__(self, sync: RobinhoodClient) -> None:
        self._sync = sync

    def __getattr__(self, name: str):
        if name not in _ENDPOINTS:
            raise AttributeError(name)
        sync_method = getattr(self._sync, name)

        async def _call(*args: Any, **kwargs: Any) -> Any:
            rec = _capture_request(self._sync, sync_method, args, kwargs)
            method = rec.get("method")
            if method == "POST":
                return await self._sync._apost(rec.get("path"), rec.get("json"))
            if method == "PATCH":
                return await self._sync._apatch(rec.get("path"), rec.get("json"))
            if method == "DELETE":
                return await self._sync._adelete(rec.get("path"))
            return await self._sync._aget(rec.get("path"), rec.get("params"))

        _call.__name__ = name
        _call.__doc__ = sync_method.__doc__
        return _call


# The GET endpoint methods (each ends in a single ``self._get``).
_GET_ENDPOINTS = frozenset(
    {
        "kol_feed",
        "kol_leaderboard",
        "kol_hot_tokens",
        "kol_coordination",
        "kol_first_touches",
        "kol_wallet",
        "trades",
        "lp_events",
        "tokens",
        "equities",
        "token",
        "token_candles",
        "token_kol_consensus",
        "token_buyer_quality",
        "token_bundle",
        "token_top_traders",
        "token_flow",
        "token_peak_history",
        "token_risk",
        "token_holders",
        "deployer_hunter_leaderboard",
        "deployer_hunter_profile",
        "deployer_hunter_alerts",
        "deployer_hunter_best_tokens",
        "deployer_hunter_recent_bonds",
        "deployer_hunter_stats",
        "deployer_hunter_trajectory",
        "deployer_hunter_tokens",
        "deployer_hunter_history",
        "alpha_wallets",
        # Rule-engine reads.
        "copytrade_subscriptions_list",
        "copytrade_subscriptions_get",
        "copytrade_signals",
        "price_alerts_list",
        "price_alerts_get",
        "price_alerts_events",
        "coordination_alerts_list",
        "coordination_alerts_get",
        "first_touch_subscriptions_list",
        "first_touch_subscriptions_get",
    }
)

# The POST endpoint methods (each ends in a single ``self._post``).
_POST_ENDPOINTS = frozenset(
    {
        "token_batch",
        "tokens_batch_buyer_quality",
        # Streaming token mint (POST /stream/token — shared surface, not
        # /rhc/*; kept here so aclient().stream_token() works).
        "stream_token",
        "copytrade_subscriptions_create",
        "price_alerts_create",
        "coordination_alerts_create",
        "first_touch_subscriptions_create",
    }
)

# The PATCH endpoint methods (each ends in a single ``self._patch``).
_PATCH_ENDPOINTS = frozenset(
    {
        "copytrade_subscriptions_update",
        "price_alerts_update",
        "coordination_alerts_update",
        "first_touch_subscriptions_update",
    }
)

# The DELETE endpoint methods (each ends in a single ``self._delete``).
_DELETE_ENDPOINTS = frozenset(
    {
        "copytrade_subscriptions_delete",
        "price_alerts_delete",
        "coordination_alerts_delete",
        "first_touch_subscriptions_delete",
    }
)

# Every dispatch-only endpoint method, whatever its verb.
_ENDPOINTS = (
    _GET_ENDPOINTS | _POST_ENDPOINTS | _PATCH_ENDPOINTS | _DELETE_ENDPOINTS
)

# Backwards-compatible alias — this used to be the GET-only set.
_ENDPOINTS_GET = _GET_ENDPOINTS


def _capture_request(
    client: RobinhoodClient, sync_method: Any, args: tuple, kwargs: dict
) -> Dict[str, Any]:
    """Run a sync endpoint method with its transport stubbed out to record the
    request it would have made — used to drive the async transport from the
    exact same argument-parsing code. Scoped to a fresh throwaway client copy so
    the live client's transport is never mutated.

    Returns ``{'method', 'path', 'params'}`` for a GET, ``{'method', 'path',
    'json'}`` for a POST/PATCH, or ``{'method', 'path'}`` for a DELETE."""
    recorder: Dict[str, Any] = {}

    def _get_stub(path: str, params: Optional[Dict[str, Any]] = None) -> None:
        recorder["method"] = "GET"
        recorder["path"] = path
        recorder["params"] = params
        return None

    def _post_stub(path: str, json_body: Optional[Dict[str, Any]] = None) -> None:
        recorder["method"] = "POST"
        recorder["path"] = path
        recorder["json"] = json_body
        return None

    def _patch_stub(path: str, json_body: Optional[Dict[str, Any]] = None) -> None:
        recorder["method"] = "PATCH"
        recorder["path"] = path
        recorder["json"] = json_body
        return None

    def _delete_stub(path: str) -> None:
        recorder["method"] = "DELETE"
        recorder["path"] = path
        return None

    # Bind the sync method to a shallow proxy whose only overrides are the four
    # transport methods, leaving the real client untouched (thread-safe, no
    # attribute mutation).
    proxy = _RecordingProxy(client, _get_stub, _post_stub, _patch_stub, _delete_stub)
    sync_method.__func__(proxy, *args, **kwargs)
    return recorder


class _RecordingProxy:
    """Delegates every attribute to the wrapped client except ``_get``,
    ``_post``, ``_patch`` and ``_delete``, which are replaced by recorders. Lets
    us reuse a sync method's body without touching the shared client
    instance."""

    def __init__(
        self,
        client: RobinhoodClient,
        get_stub: Any,
        post_stub: Any,
        patch_stub: Any,
        delete_stub: Any,
    ) -> None:
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_get", get_stub)
        object.__setattr__(self, "_post", post_stub)
        object.__setattr__(self, "_patch", patch_stub)
        object.__setattr__(self, "_delete", delete_stub)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_client"), name)


def _backoff(attempt: int) -> float:
    """Exponential backoff: 0.5s, 1s, 2s, ... capped at 8s."""
    return min(0.5 * (2 ** attempt), 8.0)
