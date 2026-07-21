"""Robinhood Chain SDK — EVM-native on-chain trading intelligence for Robinhood
Chain (chain id 4663). Bearer-key auth (``msk_``), same base URL and key as the
Solana MadeOnSol API."""

from importlib.metadata import version as _pkg_version, PackageNotFoundError

from .client import RobinhoodClient
from .errors import (
    RobinhoodError,
    RobinhoodAPIError,
    AuthError,
    TierError,
    NotFoundError,
    RateLimitError,
)

__all__ = [
    "RobinhoodClient",
    "RobinhoodError",
    "RobinhoodAPIError",
    "AuthError",
    "TierError",
    "NotFoundError",
    "RateLimitError",
]

# Single source of truth is pyproject.toml; read it from installed metadata so
# __version__ and the client User-Agent can never drift from the manifest.
try:
    __version__ = _pkg_version("robinhood-chain")
except PackageNotFoundError:  # running from source without an installed dist
    __version__ = "0.0.0"
