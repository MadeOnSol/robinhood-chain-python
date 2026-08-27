"""Real-time WebSocket streaming client for Robinhood Chain channels.

Wraps the connect -> token -> subscribe -> event loop with auto-reconnect,
heartbeat liveness (via websockets ping/pong), and typed callbacks, so
consumers never hand-roll connection management. Obtain one via
``client.stream()``. The stream token is fetched on every (re)connect; stream
tokens never expire (since 2026-08-27), so there is no refresh timer — a 4001
close means the token was rotated or the subscription lapsed, and the
reconnect simply mints again.

All six channels ride the main MadeOnSol stream endpoint
(``wss://madeonsol.com/ws/v1/stream``) — unlike Solana, the RHC DEX firehose
does NOT have a separate endpoint; it is the ``rhc:dex_trades`` channel here.

Requires the optional ``websockets`` dependency:
    pip install "robinhood-chain[stream]"
"""
from __future__ import annotations

import asyncio
import inspect
import json
import random
import warnings
from typing import Any, Awaitable, Callable

# The six Robinhood Chain channels you can subscribe to (tier gates are
# enforced server-side; the stream token itself is already PRO+):
#   rhc:kol_trades          - RHC KOL trade tape                    (PRO+)
#   rhc:dex_trades          - full RHC DEX firehose, ~40-55 ev/s    (ULTRA+)
#   rhc:copytrade:signals   - your copy-trade rule fires, user-scoped (PRO+)
#   rhc:price_alert:events  - your price-alert dips/recoveries, user-scoped,
#                             ~15s polled server-side — not sub-second (PRO+)
#   rhc:kol:coordination    - coordination alert fires               (PRO+)
#   rhc:kol:first_touches   - broadcast first-touch feed             (PRO+)
CHANNELS = (
    "rhc:kol_trades",
    "rhc:dex_trades",
    "rhc:copytrade:signals",
    "rhc:price_alert:events",
    "rhc:kol:coordination",
    "rhc:kol:first_touches",
)

# Event names delivered on those channels.
EVENT_NAMES = (
    "rhc:kol_trade",
    "rhc:dex_trade",
    "rhc:copytrade:signal",
    "rhc:price_alert:dip",
    "rhc:price_alert:recovery",
    "rhc:kol:coordination",
    "rhc:kol:first_touch",
)

# NOTE: runtime type-alias expressions must stay 3.9-compatible (this package
# supports Python 3.9; ``X | Y`` unions only evaluate on 3.10+). Annotations
# inside defs are fine — ``from __future__ import annotations`` defers them.
Handler = Callable[..., Any]  # sync or async handler
TokenProvider = Callable[[], Awaitable[dict]]


def _arity(fn: Handler) -> int:
    try:
        return len(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return 1


class RobinhoodStream:
    """Managed WebSocket stream for Robinhood Chain channels.

    Example::

        stream = client.stream()

        @stream.on("rhc:kol_trade")
        async def on_trade(data, evt):
            print(data["token_address"], data["action"])

        stream.subscribe(["rhc:kol_trades", "rhc:kol:first_touches"])
        await stream.run()   # blocks; manages connection + reconnects
    """

    def __init__(
        self,
        get_token: TokenProvider,
        *,
        auto_reconnect: bool = True,
        max_backoff: float = 30.0,
    ) -> None:
        self._get_token = get_token
        self.auto_reconnect = auto_reconnect
        self.max_backoff = max_backoff
        self._handlers: dict[str, list[Handler]] = {}
        self._channels: set[str] = set()
        self._filters: dict[str, Any] = {}
        self._ws: Any = None
        self._running = False
        self._attempt = 0

    def on(self, event: str, fn: Handler | None = None):
        """Register a handler. Use an event name, ``"*"`` for all events, or a
        lifecycle event (``open`` / ``close`` / ``reconnect`` / ``subscribed`` /
        ``heartbeat`` / ``warning`` / ``error``). Usable as a decorator.

        ``warning`` fires on server warning frames — most importantly
        ``channels_rejected``, sent when a subscribe named a channel that does
        not exist or that your tier cannot hold (the payload carries
        ``rejected`` with a per-channel ``reason``, plus ``valid_channels``).
        If no ``warning`` handler is registered the frame is surfaced through
        :func:`warnings.warn` instead — it is never dropped silently, because a
        rejected channel means you will simply receive nothing on it."""
        def register(f: Handler) -> Handler:
            self._handlers.setdefault(event, []).append(f)
            return f
        return register(fn) if fn is not None else register

    def subscribe(self, channels: list[str], filters: dict[str, Any] | None = None) -> "RobinhoodStream":
        """Subscribe to channels (sent on connect, or immediately if connected)."""
        self._channels.update(channels)
        if filters:
            self._filters.update(filters)
        if self._ws is not None:
            asyncio.ensure_future(self._send_subscribe())
        return self

    def unsubscribe(self, channels: list[str]) -> "RobinhoodStream":
        for c in channels:
            self._channels.discard(c)
        if self._ws is not None:
            asyncio.ensure_future(self._ws.send(json.dumps({"type": "unsubscribe", "channels": channels})))
        return self

    async def _send_subscribe(self) -> None:
        if self._ws is None or not self._channels:
            return
        msg: dict[str, Any] = {"type": "subscribe", "channels": sorted(self._channels)}
        if self._filters:
            msg["filters"] = self._filters
        await self._ws.send(json.dumps(msg))

    async def _emit(self, event: str, data: Any, evt: dict | None = None) -> None:
        for fn in self._handlers.get(event, []):
            try:
                result = fn(data, evt) if _arity(fn) >= 2 else fn(data)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # user handler error must not kill the stream
                pass

    async def run(self) -> None:
        """Connect and run the receive loop, reconnecting on drop. Blocks until
        :meth:`close` is called (or ``auto_reconnect`` is False and the socket
        drops)."""
        try:
            import websockets  # noqa: F401  (optional dependency)
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "WebSocket streaming requires the 'websockets' package. "
                "Install with: pip install \"robinhood-chain[stream]\""
            ) from exc
        import websockets

        self._running = True
        while self._running:
            try:
                tok = await self._get_token()
                url = f"{tok['ws_url']}?token={tok['token']}"
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    self._ws = ws
                    self._attempt = 0
                    if self._channels:
                        await self._send_subscribe()
                    await self._emit("open", None)
                    async for raw in ws:
                        await self._handle(raw)
            except Exception as exc:  # noqa: BLE001 — surface, then reconnect
                await self._emit("error", exc)
            finally:
                self._ws = None
                await self._emit("close", None)
            if not self._running or not self.auto_reconnect:
                break
            delay = min(2 ** self._attempt, self.max_backoff)
            self._attempt += 1
            await self._emit("reconnect", {"attempt": self._attempt, "delay": delay})
            await asyncio.sleep(delay / 2 + random.random() * delay / 2)

    async def _handle(self, raw: Any) -> None:
        try:
            msg = json.loads(raw)
        except Exception:
            await self._emit("error", ValueError("failed to parse stream message"))
            return
        mtype = msg.get("type")
        if mtype == "heartbeat":
            await self._emit("heartbeat", msg.get("ts"))
            return
        if mtype == "connected":
            return
        if mtype == "subscribed":
            await self._emit("subscribed", msg.get("channels"))
            return
        if mtype == "warning":
            # Server warning frames — e.g. {type: "warning", code:
            # "channels_rejected", rejected: [{channel, reason}, ...],
            # valid_channels: [...]} when a subscribe named an invalid or
            # tier-gated channel. NEVER swallowed: a rejected channel means
            # silence on it, which is indistinguishable from a quiet market
            # unless someone tells you.
            await self._surface_warning(msg)
            return
        if msg.get("channel") and msg.get("event"):
            await self._emit(msg["event"], msg.get("data"), msg)
            await self._emit("*", msg.get("data"), msg)

    async def _surface_warning(self, msg: dict) -> None:
        if self._handlers.get("warning"):
            await self._emit("warning", msg, msg)
            return
        # No handler registered — fall back to the stdlib warnings machinery so
        # the frame still reaches stderr rather than vanishing.
        code = msg.get("code")
        if code == "channels_rejected":
            rejected = msg.get("rejected") or []
            detail = ", ".join(
                f"{r.get('channel')} ({r.get('reason')})" if isinstance(r, dict) else str(r)
                for r in rejected
            )
            warnings.warn(
                "stream subscribe rejected channels: "
                f"{detail or rejected} — you will receive NO events on them. "
                f"Valid channels: {msg.get('valid_channels')}. "
                "Register stream.on('warning', ...) to handle this yourself.",
                RuntimeWarning,
                stacklevel=2,
            )
        else:
            warnings.warn(f"stream warning ({code}): {msg}", RuntimeWarning, stacklevel=2)

    async def close(self) -> None:
        """Stop reconnecting and close the socket."""
        self._running = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
