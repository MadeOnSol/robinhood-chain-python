"""Real-time WebSocket streaming client for Robinhood Chain channels.

Wraps the connect -> token -> subscribe -> event loop with auto-reconnect,
heartbeat liveness (via websockets ping/pong), and typed callbacks, so
consumers never hand-roll connection management. Obtain one via
``client.stream()``. The stream token is fetched on every (re)connect; stream
tokens never expire (since 2026-08-27), so there is no refresh timer — a 4001
close means the token was rotated or the subscription lapsed, and the
reconnect simply mints again.

All channels ride the main MadeOnSol stream endpoint
(``wss://madeonsol.com/ws/v1/stream``) — unlike Solana, the RHC DEX firehose
does NOT have a separate endpoint; it is the ``rhc:dex_trades`` channel here.

Recovery: the stream tracks a cursor ``{instance, seq, ts}`` of the last frame
your handlers finished, and resumes after it on every reconnect (v1 ``resume``,
falling back to ``replay_since_seq`` / ``replay_since_ts`` on an older server).
At-least-once, de-duplicated by event ``id``; a ``gap`` event reports what could
not be recovered. Close codes: 4001 re-fetches the token (bounded, then
``fatal``), 4002 (connection limit) waits >= 60 s, 4003 stops with ``fatal``,
4008 (slow consumer) reconnects and resumes.

Requires the optional ``websockets`` dependency:
    pip install "robinhood-chain[stream]"
"""
from __future__ import annotations

import asyncio
import inspect
import json
import random
import re
import warnings
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import quote

# The Robinhood Chain channels you can subscribe to (mirrors the server
# registry, services/shared/stream-channels.mjs; tier gates are enforced
# server-side, the stream token itself is already PRO+):
#   rhc:kol_trades              - RHC KOL trade tape                          (PRO+)
#   rhc:dex_trades              - full RHC DEX firehose, ~40-55 ev/s          (ULTRA+)
#   rhc:dex_trades_unattributed - trades on pools with no single "token" side
#                                 (e.g. WETH/USDG); subscribe with dex_trades
#                                 for full chain coverage                      (ULTRA+)
#   rhc:new_tokens              - a token's symbol/name/decimals first resolved (ULTRA+)
#   rhc:copytrade:signals       - your copy-trade rule fires, user-scoped     (PRO+)
#   rhc:price_alert:events      - your price-alert dips/recoveries, user-scoped;
#                                 event-driven off each RHC trade, with table
#                                 polls as a safety net                        (PRO+)
#   rhc:kol:coordination        - coordination alert fires                    (PRO+)
#   rhc:kol:first_touches       - broadcast first-touch feed                  (PRO+)
#   rhc:token_locks             - token lock / vesting contracts created      (PRO+)
#   rhc:token_prices            - per-token price ticks for filters.addresses
#                                 (address-scoped, 25/100/250 per connection):
#                                 one snapshot frame per address (snapshot=True)
#                                 then <= 1 tick / address / 250 ms, each with
#                                 quality fresh | stale | unreliable + reason  (PRO+)
#   rhc:lp_events               - liquidity add / remove / pool_created on
#                                 tracked Uniswap v2/v3/v4 pools with in_range,
#                                 active_share, share_of_reserves, material
#                                 (types.RhcLpStreamEvent); filters addresses,
#                                 pools, dexes, actions, material_only,
#                                 min_share; durable resume (2026-09-23)       (ULTRA+)
# rhc:token_locks with filters={"lifecycle": True} also delivers the unlock
# SCHEDULE: rhc:token_unlock_upcoming (an unlock within 24 h) and
# rhc:token_unlock_available (passed within 30 min — claimable per the
# schedule, NOT claimed; types.RhcTokenUnlockScheduleEvent). RHC claims,
# extensions and cancels are not observable (withdrawals_tracked False).
# WS Phase 4 (2026-09-23), all PRO+ and scoped (per-connection cap 25/100/250,
# rejected, never truncated, over the cap or without a scope):
#   rhc:token_candles           - live 1-minute candles for filters.addresses:
#                                 rhc:candle_closed / rhc:candle_revised (the
#                                 stored row; types.RhcCandleClosedEvent), and
#                                 with filters.updates=True rhc:candle_update
#                                 (in-progress minute, a state stream)         (PRO+)
#   rhc:token_risk              - rhc:risk_verdict_changed for filters.addresses
#                                 + an rhc:risk_verdict snapshot (risk_snapshot,
#                                 default True); score HIGHER = SAFER          (PRO+)
#   rhc:wallet_scores           - rhc:deployer_tier_changed for filters.wallets
#                                 (0x deployer addresses)                      (PRO+)
CHANNELS = (
    "rhc:kol_trades",
    "rhc:dex_trades",
    "rhc:dex_trades_unattributed",
    "rhc:new_tokens",
    "rhc:copytrade:signals",
    "rhc:price_alert:events",
    "rhc:kol:coordination",
    "rhc:kol:first_touches",
    "rhc:token_locks",
    "rhc:token_prices",
    "rhc:lp_events",
    "rhc:token_candles",
    "rhc:token_risk",
    "rhc:wallet_scores",
)

# Deprecated spellings the server still accepts (acked under the canonical
# name). ``rhc:trades`` was never a real channel; use ``rhc:dex_trades``.
DEPRECATED_CHANNEL_ALIASES = {"rhc:trades": "rhc:dex_trades"}

# Event names delivered on those channels.
EVENT_NAMES = (
    "rhc:kol_trade",
    "rhc:dex_trade",
    "rhc:dex_trade_unattributed",
    "rhc:new_token",
    "rhc:copytrade:signal",
    "rhc:price_alert:dip",
    "rhc:price_alert:recovery",
    "rhc:kol:coordination",
    "rhc:kol:first_touch",
    "rhc:token_lock",
    "rhc:token_unlock_upcoming",   # on rhc:token_locks with filters["lifecycle"] = True
    "rhc:token_unlock_available",  # same; claimable per the schedule, NOT claimed
    "rhc:token_price",  # on rhc:token_prices; the frame's snapshot=True marks the per-address snapshot
    "rhc:lp_event",     # on rhc:lp_events (ULTRA+)
    # WS Phase 4 (2026-09-23)
    "rhc:candle_closed",          # on rhc:token_candles — the stored 1-minute row, revision 0
    "rhc:candle_revised",         # on rhc:token_candles — the stored row rewritten (revision n > 0)
    "rhc:candle_update",          # on rhc:token_candles with filters["updates"] = True — a state stream
    "rhc:risk_verdict_changed",   # on rhc:token_risk
    "rhc:risk_verdict",           # on rhc:token_risk — snapshot frame (snapshot=True)
    "rhc:deployer_tier_changed",  # on rhc:wallet_scores
)

# ── Shared stream core ─────────────────────────────────────────────────────
# Everything below this line is IDENTICAL in madeonsol_x402/stream.py and
# robinhood_chain/stream.py (only the class name differs). Change it in both.
# Runtime expressions stay Python 3.9-compatible (no ``X | Y`` unions).

Handler = Callable[..., Any]  # sync or async handler
TokenProvider = Callable[[], Awaitable[dict]]

# Close codes the server uses (see the stream docs).
CLOSE_TOKEN_REJECTED = 4001   # token rotated / subscription lapsed -> re-fetch, bounded
CLOSE_CONNECTION_LIMIT = 4002  # another socket holds your slot -> long backoff
CLOSE_AUTH_ERROR = 4003        # stop: "fatal"
CLOSE_SLOW_CONSUMER = 4008     # reconnect and resume from the cursor

_HELD_LIVE_CAP = 10_000

# Named subscriptions (Phase 2): a subscribe without sub_id is the connection's
# implicit "default" subscription; a client-chosen sub_id (1-64 chars of
# A-Z a-z 0-9 _ . -) opens an independent one with its own channels + filters.
DEFAULT_SUB_ID = "default"
_SUB_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _sub_id_of(msg: Dict[str, Any]) -> str:
    v = msg.get("sub_id")
    return v if isinstance(v, str) and v else DEFAULT_SUB_ID


class StreamConnectionLimitError(RuntimeError):
    """Emitted on ``error`` when the server closes with 4002 (connection limit)."""

    def __init__(self, reason: str = "") -> None:
        super().__init__(f"stream connection limit reached{': ' + reason if reason else ''}")
        self.code = CLOSE_CONNECTION_LIMIT
        self.reason = reason


def _arity(fn: Handler) -> int:
    try:
        return len(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return 1


def _valid_cursor(c: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(c, dict):
        return None
    inst, seq, ts = c.get("instance"), c.get("seq"), c.get("ts")
    if not isinstance(inst, str) or not inst:
        return None
    if isinstance(seq, bool) or not isinstance(seq, (int, float)) or seq < 0:
        return None
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or ts < 0:
        return None
    return {"instance": inst, "seq": seq, "ts": ts}


# Fallback classification for servers that send no ``retryable`` flag: reasons
# asking again can never fill. The server's own transient list is
# backpressure | closed | source_busy | source_error | late_ingest_possible | row_cap.
PERMANENT_GAPS = frozenset({"not_reconstructable", "state_stream", "window_exceeded",
                            "ring_truncated", "instance_changed"})
# The server's transient list - a channel with one of these is worth asking again.
TRANSIENT_GAPS = frozenset({"backpressure", "closed", "source_busy", "source_error",
                            "late_ingest_possible", "row_cap"})


def _str(v: Any) -> Optional[str]:
    return v if isinstance(v, str) and v else None


def _step_cursor(c: Optional[Dict[str, Any]], instance: Optional[str], seq: Optional[float], ts: float) -> Optional[Dict[str, Any]]:
    """Move a cursor: never back within one instance; seq None frames only advance time."""
    if seq is not None and instance:
        if c and c["instance"] == instance:
            return {"instance": instance, "seq": max(c["seq"], seq), "ts": max(c["ts"], ts)}
        return {"instance": instance, "seq": seq, "ts": ts}
    # Unsequenced frame (durable backfill, seq None): keep the last real seq, advance time.
    if c:
        return {"instance": c["instance"], "seq": c["seq"], "ts": max(c["ts"], ts)}
    return None


def _close_info(exc: Any) -> Tuple[Optional[int], str]:
    """(code, reason) of the close frame the SERVER sent, if any."""
    rcvd = getattr(exc, "rcvd", None)
    if rcvd is not None:
        return getattr(rcvd, "code", None), getattr(rcvd, "reason", "") or ""
    code = getattr(exc, "code", None)
    return (code if isinstance(code, int) else None), getattr(exc, "reason", "") or ""


class _Recovery:
    __slots__ = (
        "protocol", "from_cursor", "channels", "request", "acked", "suppress_ack",
        "instance_changed", "start", "received", "delivered", "duplicates", "held", "deadline",
        "max_seq", "max_ts", "pending", "starts", "ends",
    )

    def __init__(self, protocol: str, from_cursor: Optional[Dict[str, Any]], channels: List[str], request: Dict[str, Any],
                 pending: Optional[set] = None) -> None:
        self.protocol = protocol  # "detect" | "resume" | "legacy"
        self.from_cursor = from_cursor
        self.channels = channels
        self.request = request
        self.acked = False
        self.suppress_ack = False
        self.instance_changed = False
        self.start: Optional[Dict[str, Any]] = None
        self.received = 0
        self.delivered = 0
        self.duplicates = 0
        self.held: List[Dict[str, Any]] = []
        self.deadline: Optional[float] = None  # loop time
        # Highest seq / ts among replayed frames (commit fallback for older servers).
        self.max_seq: Optional[float] = None
        self.max_ts: Optional[float] = None
        # Subscriptions ("default" included) whose replay_end is still awaited,
        # and the replay_start / replay_end frames per subscription.
        self.pending: set = set(pending) if pending is not None else {DEFAULT_SUB_ID}
        self.starts: Dict[str, Dict[str, Any]] = {}
        self.ends: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()


class RobinhoodStream:
    """Managed WebSocket stream with cursor tracking and resume.

    Recovery (v1 resume): the stream remembers a cursor ``{instance, seq, ts}``
    — the last frame whose handlers finished (sync handler returned / async
    handler awaited) — and on every reconnect asks the server to resume after
    it. Against an older server it falls back to ``replay_since_seq`` (same
    server process) or ``replay_since_ts`` (restarted). Delivery is
    at-least-once and de-duplicated by event ``id``; a ``gap`` event reports
    what could NOT be recovered. ``seq`` gaps are normal and never mean loss.

    Two positions are kept: :meth:`get_progress` (every handled frame,
    replayed ones included) and :meth:`get_cursor` — the COMMITTED, safe
    cursor, the only one to persist and resume from. Live frames commit as
    they are handled. During a resume, replayed frames are delivered but do
    NOT commit (the server replays channel by channel): the cursor moves to the
    server's ``last_seq`` / ``last_ts`` only when ``replay_end`` says
    ``complete: True`` with no incomplete / best-effort channel. After an
    INCOMPLETE recovery (or a close mid-replay) it stays at the pre-resume
    point and later live frames are delivered but not committed until a
    recovery completes, so the next reconnect re-requests the unrecovered range
    (duplicates are dropped by id). Call :meth:`accept_gap` once you have
    backfilled (or decided to skip) that range.

    Persist :meth:`get_cursor` (or the ``cursor`` event) and pass it back as
    ``resume=`` to continue after a process restart.
    """

    def __init__(
        self,
        get_token: TokenProvider,
        *,
        auto_reconnect: bool = True,
        max_backoff: float = 30.0,
        resume: Optional[Dict[str, Any]] = None,
        dedupe_size: int = 10_000,
        max_auth_retries: int = 3,
        connection_limit_backoff: float = 60.0,
        resume_detect: float = 3.0,
        legacy_replay_timeout: float = 15.0,
        max_resume_retries: int = 5,
        resume_retry_delay: float = 30.0,
        on_unrecoverable_gap: str = "advance",
    ) -> None:
        self._get_token = get_token
        self.auto_reconnect = auto_reconnect
        self.max_backoff = max_backoff
        self.dedupe_size = max(0, int(dedupe_size))
        self.max_auth_retries = max(0, int(max_auth_retries))
        self.connection_limit_backoff = max(0.0, float(connection_limit_backoff))
        self.resume_detect = max(0.0, float(resume_detect))
        self.legacy_replay_timeout = max(0.0, float(legacy_replay_timeout))
        self.max_resume_retries = max(0, int(max_resume_retries))
        self.resume_retry_delay = max(0.0, float(resume_retry_delay))
        # "advance" (default): report a final gap on the ``gap`` event
        # (advanced_past_gap + skipped) and continue past it. "stop": keep the
        # cursor, stop the stream and emit ``fatal`` so the caller decides.
        self.on_unrecoverable_gap = "stop" if on_unrecoverable_gap == "stop" else "advance"
        self._last_gap: Optional[Dict[str, Any]] = None
        # Automatic re-resume after a retryable gap.
        self._retry_at: Optional[float] = None
        self._retry_from: Optional[Dict[str, Any]] = None
        self._resume_retries = 0
        self._handlers: Dict[str, List[Handler]] = {}
        self._channels: set = set()
        self._filters: Dict[str, Any] = {}
        # Named subscriptions (Phase 2), in creation order: sub_id -> {"channels": set, "filters": dict}.
        self._named: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        # sub_ids of the subscribes sent on this connection whose ack is still due (acks arrive in order).
        self._ack_expect: List[str] = []
        self._named_unsupported_warned = False
        self._list_waiters: List["asyncio.Future[List[Dict[str, Any]]]"] = []
        self._retry_only: Optional[List[str]] = None
        self._ws: Any = None
        self._running = False
        self._attempt = 0
        self._auth_failures = 0
        self._server_instance: Optional[str] = None
        self._first_subscribe_sent = False
        # COMMITTED (safe) cursor — the one to persist and resume from.
        self._cursor: Optional[Dict[str, Any]] = _valid_cursor(resume)
        # Received progress — every handled frame, including replayed ones.
        self._progress: Optional[Dict[str, Any]] = dict(self._cursor) if self._cursor else None
        # True after an incomplete recovery: live frames are not committed until one completes.
        self._unsafe = False
        self._seen: "OrderedDict[str, bool]" = OrderedDict()
        self._recovery: Optional[_Recovery] = None
        self._wake: Optional[asyncio.Event] = None
        #: (code, reason) of the last close, or None.
        self.last_close: Optional[Tuple[Optional[int], str]] = None

    # ── public API ──────────────────────────────────────────────────────────

    def on(self, event: str, fn: Optional[Handler] = None):
        """Register a handler. Use an event name, ``"*"`` for all events, or a
        lifecycle event: ``open`` / ``close`` ({code, reason}) / ``reconnect`` /
        ``subscribed`` / ``heartbeat`` / ``warning`` / ``cursor`` / ``replay`` /
        ``gap`` / ``fatal`` / ``error``. Usable as a decorator.

        ``warning`` fires on server warning frames — ``channels_rejected`` (a
        subscribe named a channel that does not exist or that your tier cannot
        hold) and ``channels_revoked`` (the server dropped a channel you held).
        If no ``warning`` handler is registered the frame is surfaced through
        :func:`warnings.warn` instead — it is never dropped silently."""
        def register(f: Handler) -> Handler:
            self._handlers.setdefault(event, []).append(f)
            return f
        return register(fn) if fn is not None else register

    def get_cursor(self) -> Optional[Dict[str, Any]]:
        """The COMMITTED resume cursor (last safe point) — persist this one. None before the first."""
        return dict(self._cursor) if self._cursor else None

    def get_progress(self) -> Optional[Dict[str, Any]]:
        """Received progress: the last handled frame, replayed ones included (NOT safe to resume from)."""
        return dict(self._progress) if self._progress else None

    def is_recovery_incomplete(self) -> bool:
        """True while an incomplete recovery holds the committed cursor back."""
        return self._unsafe

    def accept_gap(self) -> None:
        """Accept the last reported gap: commit the received progress as the
        cursor and let live frames commit again. Call it after you backfilled
        the range the ``gap`` event named (or decided you do not need it). It
        re-reports the gap first, with ``source: "manual"`` and the range being
        skipped."""
        self._unsafe = False
        moves = bool(self._progress) and self._progress != self._cursor
        if self._last_gap is not None:
            g = dict(self._last_gap)
            g["advanced_past_gap"] = moves
            g["source"] = "manual"
            g["skipped"] = {
                "channels": list(self._last_gap["skipped"]["channels"]),
                "from": dict(self._cursor) if self._cursor else None,
                "to": dict(self._progress) if moves else None,
            }
            self._last_gap = None
            self._emit_sync("gap", g)
        if moves:
            self._cursor = dict(self._progress)
            self._emit_sync("cursor", dict(self._cursor))

    def _emit_sync(self, event: str, data: Any) -> None:
        for fn in self._handlers.get(event, []):
            try:
                result = fn(data, None) if _arity(fn) >= 2 else fn(data)
                if inspect.isawaitable(result):
                    asyncio.ensure_future(result)
            except Exception:
                pass

    def subscribe(self, channels: List[str], filters: Optional[Dict[str, Any]] = None, *,
                  sub_id: Optional[str] = None) -> "RobinhoodStream":
        """Subscribe to channels (sent on connect, or immediately if connected).

        Without ``sub_id`` this is the connection's default subscription. With
        ``sub_id`` it opens (or extends) a NAMED subscription with its own
        channels and filters; frames delivered under it carry ``evt["sub_id"]``.
        An event matching several subscriptions is delivered once per matching
        subscription (deduped per ``(sub_id, id)``), so the same event CAN reach
        a handler twice, under two sub_ids. A named subscription's ``filters``
        are REPLACED when given. Caps per connection (default included):
        PRO 5 / ULTRA 10 / BUSINESS 20."""
        if sub_id is None or sub_id == DEFAULT_SUB_ID:
            self._channels.update(channels)
            if filters:
                self._filters.update(filters)
            if self._ws is not None:
                asyncio.ensure_future(self._send_subscribe(only=[DEFAULT_SUB_ID]))
            return self
        if not isinstance(sub_id, str) or not _SUB_ID_RE.match(sub_id):
            raise ValueError("sub_id must be 1-64 characters of A-Z a-z 0-9 _ . -")
        entry = self._named.get(sub_id) or {"channels": set(), "filters": {}}
        entry["channels"].update(channels)
        if filters is not None:
            entry["filters"] = dict(filters)
        self._named[sub_id] = entry
        if self._ws is not None:
            asyncio.ensure_future(self._send_subscribe(only=[sub_id]))
        return self

    def update_subscription(self, sub_id: str, filters: Dict[str, Any]) -> "RobinhoodStream":
        """Replace the filters of a subscription (``"default"`` for the plain
        one). The server acks with an ``updated`` frame; a refused update (for
        example a ``token:prices`` subscription without valid ``mints``) comes
        back as a ``warning`` with code ``invalid_filters`` and the previous
        filters stay."""
        if sub_id == DEFAULT_SUB_ID:
            self._filters = dict(filters)
        else:
            if sub_id not in self._named:
                raise ValueError(f"unknown subscription {sub_id}")
            self._named[sub_id]["filters"] = dict(filters)
        if self._ws is not None:
            msg: Dict[str, Any] = {"type": "update", "filters": filters}
            if sub_id != DEFAULT_SUB_ID:
                msg["sub_id"] = sub_id
            asyncio.ensure_future(self._ws.send(json.dumps(msg)))
        return self

    def unsubscribe(self, channels: Union[List[str], str, None] = None, *,
                    sub_id: Optional[str] = None) -> "RobinhoodStream":
        """``unsubscribe([channels])`` stops those channels on the default
        subscription; ``unsubscribe("my-sub")`` / ``unsubscribe(sub_id="my-sub")``
        removes a whole named subscription."""
        if isinstance(channels, str):
            sub_id, channels = channels, None
        if sub_id is not None and sub_id != DEFAULT_SUB_ID:
            self._named.pop(sub_id, None)
            self._forget_pending(sub_id)
            if self._ws is not None:
                asyncio.ensure_future(self._ws.send(json.dumps({"type": "unsubscribe", "sub_id": sub_id})))
            return self
        channels = list(channels or self._channels)
        for c in channels:
            self._channels.discard(c)
        if self._ws is not None:
            asyncio.ensure_future(self._ws.send(json.dumps({"type": "unsubscribe", "channels": channels})))
        return self

    def get_subscriptions(self) -> List[Dict[str, Any]]:
        """Every subscription this client asks for (local view, no round trip):
        ``[{"sub_id", "channels", "filters"}, ...]``."""
        out: List[Dict[str, Any]] = []
        if self._channels:
            out.append({"sub_id": DEFAULT_SUB_ID, "channels": sorted(self._channels), "filters": dict(self._filters)})
        for sid, e in self._named.items():
            out.append({"sub_id": sid, "channels": sorted(e["channels"]), "filters": dict(e["filters"])})
        return out

    async def list_subscriptions(self, timeout: float = 5.0) -> List[Dict[str, Any]]:
        """Ask the server what this connection holds (``list`` -> ``subscriptions``).
        Falls back to the local view when not connected or when the server does
        not answer within ``timeout`` seconds."""
        if self._ws is None:
            return self.get_subscriptions()
        fut: "asyncio.Future[List[Dict[str, Any]]]" = asyncio.get_running_loop().create_future()
        self._list_waiters.append(fut)
        try:
            await self._ws.send(json.dumps({"type": "list"}))
            return await asyncio.wait_for(fut, timeout)
        except (asyncio.TimeoutError, Exception):
            if fut in self._list_waiters:
                self._list_waiters.remove(fut)
            return self.get_subscriptions()

    async def _collapse_pending(self, r: "_Recovery") -> None:
        """A pre-Phase-2 server (ignores sub_id) answers every resume with ONE
        replay for the whole connection, reported without sub_id: only
        "default" can still be awaited. Finishes the recovery at once when that
        one has already ended."""
        if r.pending == {DEFAULT_SUB_ID}:
            return
        r.pending.clear()
        if DEFAULT_SUB_ID not in r.ends:
            r.pending.add(DEFAULT_SUB_ID)
        if not r.pending and r.protocol != "detect":
            await self._finish_recovery(r.ends.get(DEFAULT_SUB_ID))

    def _forget_pending(self, sub_id: str) -> None:
        """A subscription removed while its replay was still awaited: stop waiting for it."""
        r = self._recovery
        if r is None or sub_id not in r.pending:
            return
        r.pending.discard(sub_id)
        if not r.pending and r.protocol != "detect":
            last = next(reversed(r.ends.values())) if r.ends else None
            asyncio.ensure_future(self._finish_recovery(last))

    def _settle_list_waiters(self, answer: Optional[List[Dict[str, Any]]] = None) -> None:
        waiters, self._list_waiters = self._list_waiters, []
        for fut in waiters:
            if not fut.done():
                fut.set_result(answer if answer is not None else self.get_subscriptions())

    async def close(self) -> None:
        """Stop reconnecting and close the socket."""
        self._running = False
        if self._wake is not None:
            self._wake.set()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def run(self) -> None:
        """Connect and run the receive loop, reconnecting on drop. Blocks until
        :meth:`close` is called, the stream goes ``fatal`` (4003, or 4001 after
        bounded token refreshes), or ``auto_reconnect`` is False and the socket
        drops."""
        try:
            import websockets  # noqa: F401  (optional dependency)
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError((
                "WebSocket streaming requires the 'websockets' package. "
                "Install with: pip install \"robinhood-chain[stream]\""
            )) from exc
        import websockets

        self._running = True
        self._wake = asyncio.Event()
        while self._running:
            try:
                tok = await self._get_token()
            except Exception as exc:  # noqa: BLE001
                await self._emit("error", exc)
                if self._auth_failures > 0:
                    # Token re-fetch after a 4001 failed — counts toward the bounded retries.
                    self._auth_failures += 1
                    if self._auth_failures > self.max_auth_retries:
                        await self._fatal(CLOSE_TOKEN_REJECTED, "stream token refresh failed")
                        break
                if not self.auto_reconnect or not await self._backoff(None, 0.0):
                    break
                continue
            url = f"{tok['ws_url']}?token={quote(str(tok['token']), safe='')}"
            code: Optional[int] = None
            reason = ""
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    self._ws = ws
                    self._server_instance = None
                    self._first_subscribe_sent = False
                    self._ack_expect = []
                    # The automatic re-resume budget is per CONNECTION (the docs say so).
                    self._resume_retries = 0
                    # The backoff attempt is NOT reset on open — only a `subscribed`
                    # ack proves the connection is usable.
                    if self._channels or self._named:
                        await self._send_subscribe()
                    await self._emit("open", None)
                    code, reason = await self._receive_loop(ws, websockets)
            except Exception as exc:  # noqa: BLE001 — surface, then reconnect
                code, reason = _close_info(exc) if isinstance(exc, websockets.ConnectionClosed) else (None, "")
                if code is None:
                    await self._emit("error", exc)
            finally:
                self._ws = None
                self._server_instance = None
                self._retry_at = None
                self._retry_from = None
                self._retry_only = None
                self._ack_expect = []
                self._settle_list_waiters()
                # An unfinished recovery is abandoned: held live frames are dropped
                # undelivered and replayed frames never moved the cursor, so the
                # next resume starts from the same pre-resume position.
                self._recovery = None
            self.last_close = (code, reason)
            await self._emit("close", {"code": code, "reason": reason})
            if not self._running:
                break
            if code == CLOSE_AUTH_ERROR:
                await self._fatal(code, reason or "authentication error")
                break
            if code == CLOSE_TOKEN_REJECTED:
                self._auth_failures += 1
                if self._auth_failures > self.max_auth_retries:
                    await self._fatal(code, reason or "stream token rejected")
                    break
            if not self.auto_reconnect:
                break
            min_delay = 0.0
            if code == CLOSE_CONNECTION_LIMIT:
                await self._emit("error", StreamConnectionLimitError(reason))
                min_delay = self.connection_limit_backoff
            # 4008 (slow consumer) and everything else: reconnect and resume.
            if not await self._backoff(code, min_delay):
                break
        self._running = False

    # ── internals ───────────────────────────────────────────────────────────

    async def _backoff(self, code: Optional[int], min_delay: float) -> bool:
        base = min(2 ** self._attempt, self.max_backoff)
        delay = base / 2 + random.random() * base / 2
        if min_delay > 0:
            delay = max(delay, min_delay + random.random() * min_delay / 2)
        self._attempt += 1
        await self._emit("reconnect", {"attempt": self._attempt, "delay": delay, "code": code})
        if self._wake is None:
            self._wake = asyncio.Event()
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
        return self._running

    async def _halt_for_gap(self, gap: Optional[Dict[str, Any]]) -> None:
        """``on_unrecoverable_gap="stop"``: stop the stream and hand the decision
        to the caller (accept_gap() + run() again continues)."""
        self._running = False
        if self._wake is not None:
            self._wake.set()
        if self._ws is not None:
            try:
                await self._ws.close(1000, "unrecoverable gap")
            except Exception:
                pass
        reason = (gap or {}).get("reason", "unknown")
        await self._emit("fatal", {"code": None, "reason": f"unrecoverable gap: {reason}", "gap": gap})

    async def _fatal(self, code: Optional[int], reason: str) -> None:
        self._running = False
        await self._emit("fatal", {"code": code, "reason": reason})

    async def _receive_loop(self, ws: Any, websockets: Any) -> Tuple[Optional[int], str]:
        loop = asyncio.get_running_loop()
        while True:
            r = self._recovery
            deadlines = [d for d in ((r.deadline if r is not None else None), self._retry_at) if d is not None]
            timeout = max(0.0, min(deadlines) - loop.time()) if deadlines else None
            try:
                if timeout is None:
                    raw = await ws.recv()
                else:
                    raw = await asyncio.wait_for(ws.recv(), timeout)
            except asyncio.TimeoutError:
                await self._on_deadline()
                continue
            except websockets.ConnectionClosed as exc:
                return _close_info(exc)
            await self._handle(raw)

    async def _on_deadline(self) -> None:
        loop = asyncio.get_running_loop()
        if self._retry_at is not None and loop.time() >= self._retry_at:
            frm, self._retry_at, self._retry_from = self._retry_from, None, None
            only, self._retry_only = self._retry_only, None
            if self._ws is not None and self._recovery is None and frm:
                # Only the subscriptions whose replay was incomplete are asked again.
                await self._send_subscribe(frm, only=only)
        r = self._recovery
        if r is None or r.deadline is None or loop.time() < r.deadline:
            return
        r.deadline = None
        if r.protocol == "detect":
            await self._fallback_to_legacy()
        elif r.protocol == "legacy":
            await self._finish_recovery(None)

    def _subscribe_frames(self, only: Optional[List[str]] = None) -> List[Tuple[str, Dict[str, Any]]]:
        """The subscribe frames for the given subscriptions (default first, then named in creation order)."""
        out: List[Tuple[str, Dict[str, Any]]] = []
        if (only is None or DEFAULT_SUB_ID in only) and self._channels:
            msg: Dict[str, Any] = {"type": "subscribe", "channels": sorted(self._channels)}
            if self._filters:
                msg["filters"] = self._filters
            out.append((DEFAULT_SUB_ID, msg))
        for sid, e in self._named.items():
            if (only is not None and sid not in only) or not e["channels"]:
                continue
            out.append((sid, {"type": "subscribe", "sub_id": sid, "channels": sorted(e["channels"]), "filters": e["filters"]}))
        return out

    async def _send_subscribe(self, resume_override: Optional[Dict[str, Any]] = None,
                              only: Optional[List[str]] = None) -> None:
        """Send the subscribe(s). On a connection's FIRST subscribe (or an
        explicit retry after a retryable gap) every subscription is sent with
        the SAME resume cursor: the server serves one replay per subscription,
        one after another, and holds live frames until the last replay_end. A
        later subscribe adds channels live (no resume)."""
        if self._ws is None:
            return
        frames = self._subscribe_frames(only)
        if not frames:
            return
        if (not self._first_subscribe_sent or resume_override) and self._cursor and self._recovery is None:
            frm = dict(resume_override or self._cursor)
            channels: set = set()
            for _, msg in frames:
                msg["resume"] = frm
                channels.update(msg["channels"])
            self._recovery = _Recovery("detect", frm, sorted(channels), {"resume": frm}, pending={sid for sid, _ in frames})
        self._first_subscribe_sent = True
        for sid, msg in frames:
            self._ack_expect.append(sid)
            await self._ws.send(json.dumps(msg))

    async def _fallback_to_legacy(self) -> None:
        """The server did not answer ``resume`` (older deployment): retry with
        the legacy replay fields. Such a server has no named subscriptions
        either, so the one legacy replay covers the union of channels and
        resolves every pending subscription at once."""
        r = self._recovery
        if r is None or r.protocol != "detect" or not r.from_cursor or self._ws is None:
            return
        r.protocol = "legacy"
        r.pending = {DEFAULT_SUB_ID}
        r.instance_changed = not self._server_instance or self._server_instance != r.from_cursor["instance"]
        # Same process -> its ring still indexes our seq. Restarted -> use time.
        legacy = {"replay_since_ts": r.from_cursor["ts"]} if r.instance_changed else {"replay_since_seq": r.from_cursor["seq"]}
        r.request = legacy
        r.suppress_ack = True
        msg: Dict[str, Any] = {"type": "subscribe", "channels": r.channels}
        msg.update(legacy)
        if self._filters:
            msg["filters"] = self._filters
        r.deadline = asyncio.get_running_loop().time() + self.legacy_replay_timeout
        try:
            await self._ws.send(json.dumps(msg))
        except Exception:
            pass

    @staticmethod
    def _aggregate_ends(r: "_Recovery", last_end: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """One ``replay_end`` per subscription -> one aggregate the single-replay
        logic runs on unchanged: complete only when every subscription is; the
        commit position is the SMALLEST last_seq / last_ts across them (a later
        subscription's replay covered more, but the earlier one's live frames
        from that point on are still only in the live flush); channel entries
        keyed ``"<sub_id>/<channel>"`` for named subscriptions; ``retryable``
        when any subscription says so."""
        ends = list(r.ends.items())
        if not ends:
            return last_end
        if len(ends) == 1 and ends[0][0] == DEFAULT_SUB_ID:
            return ends[0][1]

        def _num(v: Any) -> Optional[float]:
            return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

        def _min(a: Optional[float], b: Optional[float]) -> Optional[float]:
            return b if a is None else (a if b is None else min(a, b))

        agg: Dict[str, Any] = dict(last_end if last_end is not None else ends[-1][1])
        channels: Dict[str, Any] = {}
        complete, retryable_known, retryable, truncated = True, True, False, False
        last_seq = last_ts = live_from = retry_after = hint = None
        count = sent = matched = 0
        reason: Optional[str] = None
        limits: Any = None
        for sid, e in ends:
            if e.get("complete") is False:
                complete = False
                if reason is None and isinstance(e.get("reason"), str):
                    reason = e["reason"]
            if not isinstance(e.get("retryable"), bool):
                retryable_known = False
            elif e["retryable"]:
                retryable = True
            if e.get("replay_truncated") is True:
                truncated = True
            chs = e.get("channels")
            if isinstance(chs, dict):
                for ch, raw in chs.items():
                    channels[ch if sid == DEFAULT_SUB_ID else f"{sid}/{ch}"] = raw
            last_seq = _min(last_seq, _num(e.get("last_seq")))
            last_ts = _min(last_ts, _num(e.get("last_ts")))
            live_from = _min(live_from, _num(e.get("live_from_seq")))
            ra = _num(e.get("retry_after_ms"))
            if ra is not None:
                retry_after = ra if retry_after is None else max(retry_after, ra)
            hint = _min(hint, _num(e.get("resume_ts_hint")))
            count += _num(e.get("count")) or 0
            sent += _num(e.get("sent")) or 0
            matched += _num(e.get("matched")) or 0
            if limits is None and isinstance(e.get("limits"), dict):
                limits = e["limits"]
        agg["complete"] = complete
        agg["reason"] = None if complete else (reason or "incomplete")
        agg["channels"] = channels
        if retryable_known:
            agg["retryable"] = retryable
        else:
            agg.pop("retryable", None)
        if truncated:
            agg["replay_truncated"] = True
        agg["last_seq"], agg["last_ts"], agg["live_from_seq"] = last_seq, last_ts, live_from
        if retry_after is not None:
            agg["retry_after_ms"] = retry_after
        else:
            agg.pop("retry_after_ms", None)
        if hint is not None:
            agg["resume_ts_hint"] = hint
        else:
            agg.pop("resume_ts_hint", None)
        agg["count"], agg["sent"], agg["matched"] = count, sent, matched
        if limits is not None:
            agg["limits"] = limits
        return agg

    async def _finish_recovery(self, last_end: Optional[Dict[str, Any]]) -> None:
        r = self._recovery
        if r is None:
            return
        self._recovery = None
        end = self._aggregate_ends(r, last_end)
        # Subscriptions whose own replay_end was incomplete and retryable (or,
        # on a server that does not say, incomplete): the automatic retry asks only for them.
        retry_subs = [sid for sid, e in r.ends.items() if e.get("complete") is False and e.get("retryable") is not False]
        reasons: List[str] = []
        # Reasons of the channels the server reported incomplete, with their retryability.
        channel_reasons: List[str] = []
        retryable_channel_reasons: List[str] = []
        gap_channels: Dict[str, Any] = {}
        # A v1 server answers with complete/sent/matched; an older one with count only.
        v1 = end is not None and any(k in end for k in ("complete", "sent", "matched"))
        if (r.start or {}).get("replay_truncated") is True or (end or {}).get("replay_truncated") is True \
                or any(s.get("replay_truncated") is True for s in r.starts.values()):
            reasons.append("ring_truncated")
        if end is None:
            reasons.append("replay_timeout")
        elif v1:
            if end.get("complete") is False:
                reasons.append(_str(end.get("reason")) or "incomplete")
            chs = end.get("channels")
            if isinstance(chs, dict):
                for ch, raw in chs.items():
                    if ch == "token:prices":
                        continue  # a state stream: the server re-sends a snapshot, never a log
                    info = raw if isinstance(raw, dict) else {}
                    gap = info.get("gap")
                    late = info.get("late_ingest_possible") is True
                    if info.get("complete") is False or gap or info.get("mode") == "none" or late:
                        # raw entry: mode, reason, gap, time_basis, retry_after_ms, ...
                        gap_channels[ch] = raw
                        gr = gap.get("reason") if isinstance(gap, dict) else gap
                        reason = _str(info.get("reason")) or _str(gr)
                        if not reason:
                            if info.get("mode") == "none":
                                reason = "not_reconstructable"
                            elif late:
                                reason = "late_ingest_possible"
                            else:
                                reason = "incomplete"
                        reasons.append(reason)
                        channel_reasons.append(reason)
                        if info.get("retryable") is True or (info.get("retryable") is not False
                                                             and reason in TRANSIENT_GAPS):
                            retryable_channel_reasons.append(reason)
        else:
            # Legacy server: `count` is what it meant to send; fewer arrived -> backpressure.
            count = end.get("count")
            if isinstance(count, int) and r.received < count:
                reasons.append("backpressure")
            # Legacy server + restart: the old process's buffer is gone, no durable backfill.
            if r.protocol == "legacy" and r.instance_changed:
                reasons.append("instance_changed")
        uniq: List[str] = []
        for x in reasons:
            if x not in uniq:
                uniq.append(x)
        result = {
            "protocol": "resume" if (v1 or r.protocol == "resume") else "legacy",
            "from": r.from_cursor,
            "request": r.request,
            "received": r.received,
            "delivered": r.delivered,
            "duplicates": r.duplicates,
            "complete": not uniq,
            "mode": end.get("mode") if end is not None and isinstance(end.get("mode"), str) else None,
            "resume_reason": end.get("resume_reason") if end is not None and isinstance(end.get("resume_reason"), str) else None,
            "start": r.start,
            "end": end,
            # The subscriptions this recovery covered and their raw replay_end frames.
            "subscriptions": list(r.ends) if r.ends else (sorted(r.pending) if r.pending else [DEFAULT_SUB_ID]),
            "ends": dict(r.ends),
        }
        # Final vs retryable. The server says which (``retryable``): True only
        # when an incomplete channel's reason is transient (backpressure, closed,
        # source_busy, source_error, late_ingest_possible, row_cap). Older
        # servers send no ``retryable``; then the reason list decides.
        def _num(v: Any) -> Optional[float]:
            return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
        server_says = end is not None and isinstance(end.get("retryable"), bool)
        if not uniq:
            retryable = False
        elif server_says:
            retryable = end.get("retryable") is True
        else:
            retryable = not all(x in PERMANENT_GAPS for x in uniq)
        permanent = bool(uniq) and not retryable
        retry_after_ms = _num((end or {}).get("retry_after_ms"))
        resume_ts_hint = _num((end or {}).get("resume_ts_hint"))
        # The position the server says is safe to continue from.
        seq = cts = None
        if not retryable:
            if v1:
                # {seq: last_seq or previous, ts: last_ts or previous}
                seq = _num((end or {}).get("last_seq"))
                cts = _num((end or {}).get("last_ts"))
                if cts is None and seq is not None:
                    cts = self._cursor["ts"] if self._cursor else None
            else:
                live_from = _num((end or {}).get("live_from_seq"))
                held_seqs = [f.get("seq") for f in r.held if isinstance(f.get("seq"), (int, float))]
                seq = r.max_seq
                if seq is None:
                    seq = (min(held_seqs) - 1) if held_seqs else (live_from - 1 if live_from is not None else None)
                cts = r.max_ts if r.max_ts is not None else (self._cursor["ts"] if self._cursor else None)
            if seq is not None and seq < 0:
                seq = None
        # Continuing past a FINAL gap is the SDK's own decision, never the user's
        # approval: it is reported on the gap event (advanced_past_gap / skipped)
        # and ``on_unrecoverable_gap="stop"`` turns it off.
        # resume_ts_hint is a row_cap device: it says "everything up to here was
        # sent for the capped channel". If another channel is incomplete for a
        # RETRYABLE reason (source_error, source_busy, ...), resuming from the
        # hint would step past its unread range and the next reply would claim
        # complete. Channels with a FINAL gap are ignored here: asking again
        # never recovers them anyway, and the gap event reports them. Same
        # predicate as the server, checked here so the client never depends on it.
        if retryable_channel_reasons:
            cap_candidates = retryable_channel_reasons
        elif channel_reasons:
            cap_candidates = []
        else:
            cap_candidates = [x for x in uniq if x in TRANSIENT_GAPS]
        cap_only = bool(cap_candidates) and all(x == "row_cap" for x in cap_candidates)
        exhausted = retryable and self._resume_retries >= self.max_resume_retries
        strict = bool(uniq) and not retryable and self.on_unrecoverable_gap == "stop"
        will_advance = (not retryable) and not strict
        await self._emit("replay", result)
        gap = None
        if uniq:
            gap = {
                "reason": uniq[0], "reasons": uniq, "permanent": permanent, "retryable": retryable,
                "retry_after_ms": retry_after_ms, "resume_ts_hint": resume_ts_hint,
                "channels": gap_channels, "from": r.from_cursor, "replay": result, "exhausted": exhausted,
                "limits": (end or {}).get("limits") or (r.start or {}).get("limits"),
                # What the client does about it — always reported BEFORE it happens.
                "advanced_past_gap": will_advance,
                "source": "auto",
                # The range that MAY be incomplete (never a count of lost events).
                "skipped": {
                    "channels": list(gap_channels),
                    "from": dict(self._cursor) if self._cursor else None,
                    "to": (_step_cursor(self._cursor, self._server_instance, seq, cts)
                           if (will_advance and cts is not None) else None),
                },
            }
            self._last_gap = gap
            await self._emit("gap", gap)
        if will_advance:
            self._unsafe = False
            self._resume_retries = 0
            if cts is not None:
                await self._advance(self._server_instance, seq, cts, True)
        elif retryable:
            self._unsafe = True
            if server_says:
                self._schedule_resume_retry(retry_after_ms, resume_ts_hint if cap_only else None,
                                            retry_subs or None)
        else:
            # strict: stop instead of skipping what cannot be recovered.
            self._unsafe = True
            await self._halt_for_gap(gap)
        # Live frames that arrived during a client-side replay go out now, after it.
        for f in r.held:
            await self._deliver(f)

    def _schedule_resume_retry(self, retry_after_ms: Optional[float], hint_ts: Optional[float],
                               only: Optional[List[str]] = None) -> None:
        """A retryable gap: ask the server again on this connection after its
        retry_after_ms (row_cap resumes from resume_ts_hint), for the
        subscriptions in ``only`` (all when None). Bounded — the next reconnect
        resumes anyway."""
        if self._retry_at is not None or not self._cursor:
            return
        if self._resume_retries >= self.max_resume_retries:
            return
        self._resume_retries += 1
        delay = retry_after_ms / 1000.0 if (retry_after_ms is not None and retry_after_ms >= 0) else self.resume_retry_delay
        frm = dict(self._cursor)
        if hint_ts is not None and hint_ts > frm["ts"]:
            frm["ts"] = hint_ts
        self._retry_from = frm
        self._retry_only = only
        self._retry_at = asyncio.get_running_loop().time() + delay

    async def _emit(self, event: str, data: Any, evt: Optional[dict] = None) -> None:
        for fn in self._handlers.get(event, []):
            try:
                result = fn(data, evt) if _arity(fn) >= 2 else fn(data)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # user handler error must not kill the stream
                pass

    async def _dispatch(self, event: str, data: Any, evt: dict) -> None:
        """Like _emit for data frames, but a handler error is reported on ``error``."""
        for fn in self._handlers.get(event, []):
            try:
                result = fn(data, evt) if _arity(fn) >= 2 else fn(data)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # noqa: BLE001
                await self._emit("error", exc)

    async def _handle(self, raw: Any) -> None:
        try:
            msg = json.loads(raw)
        except Exception:
            await self._emit("error", ValueError("failed to parse stream message"))
            return
        if not isinstance(msg, dict):
            return
        mtype = msg.get("type")
        if mtype == "heartbeat":
            await self._emit("heartbeat", msg.get("ts"))
            return
        if mtype == "connected":
            if isinstance(msg.get("instance"), str):
                self._server_instance = msg["instance"]
            if not self._channels and not self._named:
                self._attempt = 0
                self._auth_failures = 0
            return
        if mtype == "subscribed":
            if isinstance(msg.get("instance"), str):
                self._server_instance = msg["instance"]
            self._attempt = 0
            self._auth_failures = 0
            r = self._recovery
            if r is not None and r.suppress_ack:
                r.suppress_ack = False  # ack of our own fallback subscribe
                return
            # Acks arrive in the order the subscribes were sent: a named subscribe
            # answered WITHOUT sub_id means the server ignores sub_id (older
            # deployment) — every subscription then collapsed into one on the
            # server. Said once, never silently.
            expected = self._ack_expect.pop(0) if self._ack_expect else DEFAULT_SUB_ID
            # The subscription this ack is about: the server's sub_id, else the
            # one we sent in this position (an older server echoes none).
            acked_id = msg["sub_id"] if isinstance(msg.get("sub_id"), str) and msg["sub_id"] else expected
            if expected != DEFAULT_SUB_ID and not isinstance(msg.get("sub_id"), str):
                if not self._named_unsupported_warned:
                    self._named_unsupported_warned = True
                    await self._surface_warning({
                        "type": "warning", "code": "named_subscriptions_unsupported", "sub_id": expected,
                        "message": "The server ignored sub_id: it predates named subscriptions, so every subscription "
                                   "on this connection shares one channel set and one filter object.",
                    })
                # Such a server runs ONE replay for the whole connection and
                # reports it without sub_id ("default"): every named id must
                # leave `pending` or the recovery would never finish and the
                # cursor would freeze.
                if r is not None:
                    await self._collapse_pending(r)
            await self._emit("subscribed", msg.get("channels"), msg)
            if r is not None and r.protocol == "detect" and not r.acked:
                r.acked = True
                if "resume" in msg:
                    r.protocol = "resume"  # server echoed resume: it understood
                else:
                    r.deadline = asyncio.get_running_loop().time() + self.resume_detect
            echo = msg.get("resume")
            if r is not None and isinstance(echo, dict) and echo.get("accepted") is False:
                # Refused for THIS subscription (replay_in_progress: it already has
                # a replay running or queued): no replay_end will come for it. When
                # nothing at all was accepted, nothing was recovered, so the
                # committed cursor must not move until a later recovery completes.
                r.pending.discard(acked_id)
                if not r.pending and not r.ends:
                    self._recovery = None
                    self._unsafe = True
                elif not r.pending and r.protocol != "detect":
                    await self._finish_recovery(next(reversed(r.ends.values())) if r.ends else None)
            return
        if mtype == "replay_start":
            r = self._recovery
            if r is None:
                r = self._recovery = _Recovery("resume", None, [], {}, pending={_sub_id_of(msg)})
                r.acked = True
            if r.protocol == "detect":
                r.protocol = "resume"
                r.deadline = None
            r.starts[_sub_id_of(msg)] = msg
            if r.start is None:
                r.start = msg
            return
        if mtype == "replay_end":
            r = self._recovery
            if r is None:
                return
            sid = _sub_id_of(msg)
            r.ends[sid] = msg
            r.pending.discard(sid)
            # Every subscription's replay has ended (a legacy server answers
            # once, for the whole connection) -> aggregate and commit.
            if not r.pending or r.protocol == "legacy":
                await self._finish_recovery(msg)
            return
        if mtype == "updated":
            await self._emit("updated", msg)
            return
        if mtype == "unsubscribed":
            await self._emit("unsubscribed", msg)
            return
        if mtype == "subscriptions":
            raw_list = msg.get("list") if isinstance(msg.get("list"), list) else []
            answer = [{
                "sub_id": s.get("sub_id") if isinstance(s.get("sub_id"), str) else DEFAULT_SUB_ID,
                "channels": list(s.get("channels") or []),
                "filters": dict(s.get("filters") or {}),
            } for s in raw_list if isinstance(s, dict)]
            self._settle_list_waiters(answer)
            return
        if mtype == "warning":
            sid = msg.get("sub_id") if isinstance(msg.get("sub_id"), str) else None
            code = msg.get("code")
            if code == "channels_revoked":
                # The server dropped these (e.g. plan downgrade): stop re-subscribing them.
                names = [c for c in (msg.get("channels") or []) if isinstance(c, str)]
                for x in msg.get("revoked") or []:
                    if isinstance(x, str):
                        names.append(x)
                    elif isinstance(x, dict) and isinstance(x.get("channel"), str):
                        names.append(x["channel"])
                if sid and sid != DEFAULT_SUB_ID:
                    entry = self._named.get(sid)
                    if entry is not None:
                        for c in names:
                            entry["channels"].discard(c)
                        if not entry["channels"]:
                            self._named.pop(sid, None)
                else:
                    for c in names:
                        self._channels.discard(c)
            elif code in ("too_many_subscriptions", "invalid_sub_id") and sid and sid != DEFAULT_SUB_ID:
                # The server will refuse it on every reconnect too: forget it, and do not wait for its replay.
                self._named.pop(sid, None)
                self._forget_pending(sid)
            await self._surface_warning(msg)
            return
        if not (msg.get("channel") and msg.get("event")):
            return
        # Bus-recovered frames (recovered == "bus") are re-sent live, not part of a replay.
        in_replay = msg.get("replayed") is True and msg.get("recovered") != "bus"
        r = self._recovery
        if r is not None:
            if not in_replay and r.protocol == "detect" and r.acked:
                await self._fallback_to_legacy()  # live before replay_start -> old server
            if not in_replay and r.protocol == "legacy":
                if len(r.held) < _HELD_LIVE_CAP:
                    r.held.append(msg)
                    return
                held, r.held = r.held, []
                for f in held:
                    await self._deliver(f)
            if in_replay:
                r.received += 1
        await self._deliver(msg)

    async def _deliver(self, msg: Dict[str, Any]) -> None:
        """Dedupe by id, run the handlers, then advance the cursor."""
        in_replay = msg.get("replayed") is True and msg.get("recovered") != "bus"
        rec = self._recovery
        if in_replay and rec is not None:
            s_, t_ = msg.get("seq"), msg.get("ts")
            if isinstance(s_, (int, float)) and not isinstance(s_, bool):
                rec.max_seq = s_ if rec.max_seq is None else max(rec.max_seq, s_)
            if isinstance(t_, (int, float)) and not isinstance(t_, bool):
                rec.max_ts = t_ if rec.max_ts is None else max(rec.max_ts, t_)
        raw_id = msg.get("id")
        fid = str(raw_id) if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else None
        if fid is not None and self.dedupe_size > 0:
            # Dedupe is per (sub_id, channel, id): the same event delivered under
            # two named subscriptions is two legitimate deliveries.
            key = f"{_sub_id_of(msg)}\x00{msg.get('channel')}\x00{fid}"
            if key in self._seen:
                self._seen.move_to_end(key)
                if in_replay and self._recovery is not None:
                    self._recovery.duplicates += 1
                return
            self._seen[key] = True
            if len(self._seen) > self.dedupe_size:
                self._seen.popitem(last=False)
        if in_replay and self._recovery is not None:
            self._recovery.delivered += 1
        data = msg.get("data")
        evt = dict(msg)
        evt["replayed"] = msg.get("replayed") is True or (isinstance(data, dict) and data.get("replayed") is True)
        seq = msg.get("seq")
        seq = seq if isinstance(seq, (int, float)) and not isinstance(seq, bool) else None
        ts = msg.get("ts")
        ts = ts if isinstance(ts, (int, float)) and not isinstance(ts, bool) else None
        instance = self._server_instance
        # Progress always moves; the COMMITTED cursor only for live frames outside
        # a recovery and not after an incomplete one (see _finish_recovery).
        commit = self._recovery is None and not self._unsafe
        await self._dispatch(msg["event"], data, evt)
        await self._dispatch("*", data, evt)
        # Only sequenced/identified frames move the cursor (price ticks are
        # state) — and none while a recovery runs: _finish_recovery commits the
        # server's replay_end position if, and only if, it is complete.
        if (seq is not None or fid is not None) and ts is not None:
            await self._advance(instance, seq, ts, commit)

    async def _advance(self, instance: Optional[str], seq: Optional[float], ts: float, commit: bool) -> None:
        """Move progress (always) and the committed cursor (when ``commit``)."""
        p = _step_cursor(self._progress, instance, seq, ts)
        if p is not None:
            self._progress = p
        if not commit:
            return
        c = self._cursor
        nxt = _step_cursor(c, instance, seq, ts)
        if nxt is None or c == nxt:
            return
        self._cursor = nxt
        await self._emit("cursor", dict(nxt))

    async def _surface_warning(self, msg: dict) -> None:
        # Server warning frames (channels_rejected, channels_revoked, ...). NEVER
        # swallowed: a rejected/revoked channel is silent, indistinguishable
        # from a quiet market unless someone says so.
        if self._handlers.get("warning"):
            await self._emit("warning", msg, msg)
            return
        code = msg.get("code")
        if code in ("channels_rejected", "channels_revoked"):
            items = msg.get("rejected") or msg.get("revoked") or []
            detail = ", ".join(
                f"{r.get('channel')} ({r.get('reason')})" if isinstance(r, dict) else str(r)
                for r in items
            )
            warnings.warn(
                f"stream {code}: {detail or items} — you will receive NO events on them. "
                f"Valid channels: {msg.get('valid_channels')}. "
                "Register stream.on('warning', ...) to handle this yourself.",
                RuntimeWarning,
                stacklevel=2,
            )
        else:
            warnings.warn(f"stream warning ({code}): {msg}", RuntimeWarning, stacklevel=2)
