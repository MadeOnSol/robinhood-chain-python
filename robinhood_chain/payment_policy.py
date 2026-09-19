"""Explicit USDG/RHC authorization policy. Budgets count signing attempts, not receipts."""
from __future__ import annotations

from dataclasses import dataclass
import re
import threading
from typing import Any, Awaitable, Callable, Mapping, Optional, Union
from types import MappingProxyType
from urllib.parse import urlsplit

from .errors import RobinhoodError

RHC_PAYMENT_NETWORK = "eip155:4663"
RHC_PAYMENT_ASSET = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"


class PaymentPolicyError(RobinhoodError):
    """A challenge or signing attempt exceeded the caller's explicit authorization."""


def _atomic(value: Any, name: str) -> int:
    if type(value) is not int and (not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,77}", value)):
        raise PaymentPolicyError(f"{name} must be a positive integer in atomic units")
    n = int(value)
    if n <= 0 or n >= 2**256:
        raise PaymentPolicyError(f"{name} is outside uint256")
    return n


def _address(value: Any) -> Optional[str]:
    if isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", value) and int(value, 16) != 0:
        return value.lower()
    return None


def payment_origin(url: str) -> str:
    try:
        p = urlsplit(url)
        port = p.port or 443
    except ValueError as exc:
        raise PaymentPolicyError("Invalid keyless payment URL") from exc
    if p.scheme != "https" or not p.hostname or p.username is not None or p.password is not None or p.fragment:
        raise PaymentPolicyError("Keyless payment URLs must use HTTPS without credentials or fragments")
    return f"https://{p.hostname.lower()}:{port}"


@dataclass(frozen=True)
class PaymentPolicy:
    """Required for keyless mode. Amounts are USDG atomic units (six decimals).

    Obtain pay_to independently of the challenge. Each client owns one budget;
    sharing a policy object does not share the budget across clients/processes.
    Only literal True from before_payment approves an otherwise valid payment.
    """
    pay_to: str
    max_amount_atomic: Union[int, str]
    max_total_amount_atomic: Union[int, str]
    timeout_seconds: float = 30.0
    authorization_ttl_seconds: int = 60
    before_payment: Optional[Callable[[Mapping[str, Any]], Union[bool, Awaitable[bool]]]] = None

    def __post_init__(self) -> None:
        address = _address(self.pay_to)
        if address is None:
            raise PaymentPolicyError("payment_policy.pay_to must be a nonzero EVM address")
        object.__setattr__(self, "pay_to", address)
        object.__setattr__(self, "max_amount_atomic", _atomic(self.max_amount_atomic, "max_amount_atomic"))
        object.__setattr__(self, "max_total_amount_atomic", _atomic(self.max_total_amount_atomic, "max_total_amount_atomic"))
        if type(self.timeout_seconds) not in (int, float) or not 0 < self.timeout_seconds <= 2147483:
            raise PaymentPolicyError("timeout_seconds is out of range")
        if type(self.authorization_ttl_seconds) is not int or not 1 <= self.authorization_ttl_seconds <= 300:
            raise PaymentPolicyError("authorization_ttl_seconds is out of range")
        if self.before_payment is not None and not callable(self.before_payment):
            raise PaymentPolicyError("before_payment must be callable")


class PaymentBudget:
    def __init__(self, policy: Optional[PaymentPolicy]) -> None:
        if not isinstance(policy, PaymentPolicy):
            raise PaymentPolicyError("Keyless mode requires payment_policy with pay_to, max_amount_atomic and max_total_amount_atomic")
        self.policy = policy
        self._used = 0
        self._lock = threading.Lock()  # One budget across sync threads and async calls.

    @property
    def authorized_amount_atomic(self) -> int:
        with self._lock:
            return self._used

    def select(self, challenge: Any, url: str) -> Mapping[str, Any]:
        payment_origin(url)
        if not isinstance(challenge, dict) or type(challenge.get("x402Version")) is not int or challenge.get("x402Version") != 2:
            raise PaymentPolicyError("Expected an x402 v2 challenge")
        accepts = challenge.get("accepts")
        if not isinstance(accepts, list) or len(accepts) > 32:
            raise PaymentPolicyError("Expected a bounded x402 accepts list")
        if "resource" in challenge:
            resource = challenge["resource"]
            if not isinstance(resource, dict) or not isinstance(resource.get("url"), str):
                raise PaymentPolicyError("Challenge resource does not match the requested URL")
            advertised, requested = urlsplit(resource["url"]), urlsplit(url)
            if payment_origin(resource["url"]) != payment_origin(url) or advertised.path != requested.path or (advertised.query and advertised.query != requested.query):
                raise PaymentPolicyError("Challenge resource does not match the requested URL")
        leg = next((a for a in accepts if isinstance(a, dict) and a.get("scheme") == "exact"
                    and a.get("network") == RHC_PAYMENT_NETWORK and _address(a.get("asset")) == RHC_PAYMENT_ASSET
                    and _address(a.get("payTo")) == self.policy.pay_to), None)
        if leg is None:
            raise PaymentPolicyError("No exact USDG/RHC offer for the trusted recipient")
        if not isinstance(leg.get("amount"), str):
            raise PaymentPolicyError("Challenge amount must be a decimal string")
        amount = _atomic(leg["amount"], "amount")
        if amount > self.policy.max_amount_atomic:
            raise PaymentPolicyError("Payment exceeds max_amount_atomic")
        timeout = leg.get("maxTimeoutSeconds")
        if type(timeout) is not int or not 1 <= timeout <= 2**53 - 1:
            raise PaymentPolicyError("maxTimeoutSeconds is out of range")
        if "extra" in leg:
            extra = leg["extra"]
            if not isinstance(extra, dict) or ("name" in extra and extra["name"] != "Global Dollar") or ("version" in extra and extra["version"] != "1"):
                raise PaymentPolicyError("Unexpected USDG signing domain")
        return MappingProxyType({"url": url, "network": RHC_PAYMENT_NETWORK, "scheme": "exact", "asset": RHC_PAYMENT_ASSET,
                                 "payTo": self.policy.pay_to, "amount": str(amount),
                                 "maxTimeoutSeconds": min(timeout, self.policy.authorization_ttl_seconds)})

    def reserve(self, proposal: Mapping[str, Any]) -> "_Reservation":
        amount = _atomic(proposal["amount"], "amount")
        with self._lock:
            if self._used + amount > self.policy.max_total_amount_atomic:
                raise PaymentPolicyError("Payment exceeds max_total_amount_atomic")
            self._used += amount
        return _Reservation(self, amount)


class _Reservation:
    def __init__(self, budget: PaymentBudget, amount: int) -> None:
        self.budget, self.amount = budget, amount
        self.retained = False
        self.released = False

    def signer_invoked(self) -> None:
        self.retained = True

    def release(self) -> None:
        with self.budget._lock:
            if not self.retained and not self.released:
                self.budget._used -= self.amount
                self.released = True
