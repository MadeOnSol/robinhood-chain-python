"""Typed errors for the Robinhood Chain SDK.

Every non-2xx API response is raised as a :class:`RobinhoodAPIError` (or a more
specific subclass by status code), carrying the parsed ``error`` message and the
``_rid`` request id from the API's error envelope when present.
"""

from __future__ import annotations

from typing import Any, Optional


class RobinhoodError(Exception):
    """Base class for every error raised by this SDK."""


class RobinhoodAPIError(RobinhoodError):
    """A non-2xx response from the Robinhood Chain API.

    Attributes:
        status: HTTP status code.
        message: Human-readable ``error`` string from the API envelope.
        request_id: The ``_rid`` request id — include it when reporting issues.
        body: The raw parsed JSON body (dict) or raw text when not JSON.
    """

    def __init__(
        self,
        status: int,
        message: str,
        *,
        request_id: Optional[str] = None,
        body: Any = None,
    ) -> None:
        self.status = status
        self.message = message
        self.request_id = request_id
        self.body = body
        rid = f" (rid={request_id})" if request_id else ""
        super().__init__(f"[{status}] {message}{rid}")


class AuthError(RobinhoodAPIError):
    """401 — missing or invalid API key."""


class TierError(RobinhoodAPIError):
    """403 — the endpoint or a parameter requires a higher tier (PRO/ULTRA)."""


class NotFoundError(RobinhoodAPIError):
    """404 — no Robinhood Chain data for the requested address/token."""


class RateLimitError(RobinhoodAPIError):
    """429 — rate limit exceeded. See ``reset`` for the retry window (epoch ms)."""

    def __init__(
        self,
        status: int,
        message: str,
        *,
        request_id: Optional[str] = None,
        body: Any = None,
        reset: Optional[int] = None,
    ) -> None:
        super().__init__(status, message, request_id=request_id, body=body)
        self.reset = reset


def error_for_status(
    status: int,
    message: str,
    *,
    request_id: Optional[str] = None,
    body: Any = None,
    reset: Optional[int] = None,
) -> RobinhoodAPIError:
    """Map an HTTP status code to the most specific error subclass."""
    if status == 401:
        return AuthError(status, message, request_id=request_id, body=body)
    if status == 403:
        return TierError(status, message, request_id=request_id, body=body)
    if status == 404:
        return NotFoundError(status, message, request_id=request_id, body=body)
    if status == 429:
        return RateLimitError(
            status, message, request_id=request_id, body=body, reset=reset
        )
    return RobinhoodAPIError(status, message, request_id=request_id, body=body)
