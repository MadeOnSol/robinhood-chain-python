"""PAY-05 — recovery of paid-but-lost x402 results (Python port).

Server contract: docs/audit/PAY05_PAID_RESULT_RECOVERY.md. Byte-for-byte parity
with the TypeScript clients (packages/madeonsol-x402/src/x402-recovery.ts) is
pinned by the shared vectors in packages/x402-recovery-vectors.json.

Rules for a paid GET (a request that carries a PAYMENT-SIGNATURE proof):
  * the exact proof and the exact URL are re-sent until a final answer; a new
    payment is NEVER created here and no payment budget is touched;
  * the original submission carries no PAYMENT-RECOVERY header; every retry
    carries one, signed by the payer (EIP-191) with a fresh ``issuedAt``;
  * payment id and request hash are computed LOCALLY (a server echo is only a
    fallback), so a server can never make the payer sign for another payment;
  * every wait honours ``Retry-After`` and is bounded (attempts + wall time);
    at the bound the caller gets a coded :class:`X402PaymentError` with
    ``resume()`` instead of a silently dropped proof;
  * only a proven ``402 not_paid`` allows a new payment
    (``new_payment_allowed``); 401 ``payment_recovery_invalid`` and 410 are final.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlsplit

from .errors import RobinhoodError

PAYMENT_RECOVERY_HEADER = "PAYMENT-RECOVERY"
X402_RECOVERY_VERSION = 1
_RHC_NETWORK = "eip155:4663"
_RHC_ASSET = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
_HEX64 = frozenset("0123456789abcdef")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _js_json(value: Any) -> str:
    """JSON.stringify-compatible serialisation for strings/lists/ints/dicts."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _utf16_key(s: str) -> bytes:
    # JavaScript compares strings by UTF-16 code units; big-endian UTF-16 bytes
    # order identically (this differs from Python's code-point order for astral
    # characters vs U+E000..U+FFFF).
    return s.encode("utf-16-be", "surrogatepass")


def x402_request_hash(method: str, url: str) -> str:
    """Canonical request identity (server: x402RequestHash)."""
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True, encoding="utf-8", errors="replace")
    pairs.sort(key=lambda kv: (_utf16_key(kv[0]), _utf16_key(kv[1])))
    path = parts.path or "/"
    body = _js_json(["madeonsol-x402-request-v1", method.upper(), path, [[k, v] for k, v in pairs]])
    return _sha256_hex(body.encode("utf-8"))


def recovery_message(payment_id: str, request_hash: str, issued_at: int) -> str:
    """The exact 5-line UTF-8 message the payer signs (no trailing newline)."""
    return "\n".join([
        "MadeOnSol x402 payment recovery",
        f"version: {X402_RECOVERY_VERSION}",
        f"payment_id: {payment_id}",
        f"request_hash: {request_hash}",
        f"issued_at: {issued_at}",
    ])


def encode_recovery_header(payment_id: str, request_hash: str, issued_at: int, signature: str) -> str:
    """base64(JSON {version, paymentId, requestHash, issuedAt, signature}) — this key order."""
    return base64.b64encode(_js_json({
        "version": X402_RECOVERY_VERSION, "paymentId": payment_id, "requestHash": request_hash,
        "issuedAt": issued_at, "signature": signature,
    }).encode("utf-8")).decode("ascii")


def payment_id_from_proof(rail: str, proof_header: str) -> Optional[str]:
    """Local payment identity from the PAYMENT-SIGNATURE header the client sent."""
    try:
        proof = json.loads(base64.b64decode(proof_header).decode("utf-8"))
        if rail == "solana":
            tx = (proof.get("payload") or {}).get("transaction")
            return _sha256_hex(base64.b64decode(tx)) if isinstance(tx, str) and tx else None
        inner = proof.get("payload") if isinstance(proof.get("payload"), dict) else proof
        auth = inner.get("authorization") or proof.get("authorization")
        if not isinstance(auth, dict) or not isinstance(auth.get("from"), str) or not isinstance(auth.get("nonce"), str):
            return None
        return _sha256_hex(_js_json(["rhc-x402-eip3009-v1", _RHC_NETWORK, _RHC_ASSET,
                                     auth["from"].lower(), auth["nonce"].lower()]).encode("utf-8"))
    except Exception:  # noqa: BLE001 - any malformed proof → no local id
        return None


def sign_recovery_evm(account: Any, message: str) -> str:
    """EIP-191 personal_sign by the authorizer (eth-account LocalAccount), 0x hex."""
    from eth_account.messages import encode_defunct  # type: ignore

    sig = account.sign_message(encode_defunct(text=message)).signature.hex()
    return sig if sig.startswith("0x") else "0x" + sig


# ── classification ───────────────────────────────────────────────────────────

def classify_paid_response(status: int, body: Optional[Dict[str, Any]]) -> str:
    """final | signature_required | in_progress | result_missing | uncertain | gateway | rate_limited."""
    if status < 300:
        return "final"
    code = body.get("code") if isinstance(body, dict) and isinstance(body.get("code"), str) else None
    pstatus = body.get("payment_status") if isinstance(body, dict) and isinstance(body.get("payment_status"), str) else None
    if status == 409 and (code == "payment_recovery_signature_required" or (not code and isinstance(body, dict) and body.get("reason") == "replay_detected")):
        return "signature_required"
    if status == 409 and code == "paid_result_in_progress":
        return "in_progress"
    if status >= 500 and pstatus == "paid_result_missing":
        return "result_missing"
    if status == 503 and pstatus == "payment_uncertain":
        return "uncertain"
    if status in (502, 503, 504) and not pstatus:
        return "gateway"
    if status == 429:
        # The per-IP burst cap answers before any payment state is read: it says
        # nothing about the payment (an earlier send may have settled). Wait, resend.
        return "rate_limited"
    return "final"


def _json_or_none(text: str) -> Optional[Dict[str, Any]]:
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _retry_after_seconds(headers: Any, body: Optional[Dict[str, Any]]) -> Optional[float]:
    raw = headers.get("retry-after") if headers is not None else None
    if raw is not None and raw.strip().isdigit():
        return float(raw.strip())
    if isinstance(body, dict):
        s = body.get("retry_after_seconds")
        if s is None and isinstance(body.get("paid_result"), dict):
            s = body["paid_result"].get("retry_after_seconds")
        if isinstance(s, (int, float)) and not isinstance(s, bool) and s >= 0:
            return float(s)
    return None


_PENDING_CODES = {"payment_uncertain", "payment_state_unavailable", "paid_result_in_progress",
                  "paid_result_missing", "payment_transport_error"}


class X402PaymentError(RobinhoodError):
    """A paid call that did not end in an answer. Never means "pay again" unless
    ``new_payment_allowed`` (a proven 402 ``not_paid``)."""

    def __init__(self, message: str, *, status: int, code: Optional[str] = None, reason: Optional[str] = None,
                 payment_status: Optional[str] = None, payment_id: Optional[str] = None,
                 request_hash: Optional[str] = None, retry_after_seconds: Optional[float] = None,
                 body: Any = None, resume: Optional[Callable[[], Any]] = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.reason = reason
        self.payment_status = payment_status
        self.payment_id = payment_id
        self.request_hash = request_hash
        self.retry_after_seconds = retry_after_seconds
        self.body = body
        pending = code in _PENDING_CODES or (payment_status == "paid_result_missing" and status >= 500)
        #: Still recoverable with the SAME proof (never by a new payment).
        self.retryable = bool(pending and status != 410)
        #: Only a proven not_paid (HTTP 402) allows a new payment for this request.
        self.new_payment_allowed = status == 402 and (code == "not_paid" or payment_status == "not_paid")
        #: Continue recovery with the same proof and URL (sync: returns the data; async client: awaitable).
        self.resume = resume if (resume is not None and self.retryable) else None


def error_from_response(status: int, headers: Any, text: str, message: str, ids: Tuple[Optional[str], Optional[str]],
                        resume: Optional[Callable[[], Any]] = None) -> X402PaymentError:
    body = _json_or_none(text)
    code = None
    if isinstance(body, dict):
        if isinstance(body.get("paid_result"), dict) and body["paid_result"].get("code") == "paid_result_missing":
            code = "paid_result_missing"
        elif isinstance(body.get("code"), str):
            code = body["code"]
        elif status == 409 and body.get("reason") == "replay_detected":
            code = "payment_recovery_signature_required"
    reason = body.get("reason") if isinstance(body, dict) and isinstance(body.get("reason"), str) else (
        body.get("code") if code == "paid_result_missing" and isinstance(body, dict) else None)
    return X402PaymentError(
        message, status=status, code=code, reason=reason,
        payment_status=body.get("payment_status") if isinstance(body, dict) else None,
        payment_id=headers.get("x-payment-id") or (body.get("paymentId") if isinstance(body, dict) else None) or ids[0],
        request_hash=headers.get("x-request-hash") or ids[1],
        retry_after_seconds=_retry_after_seconds(headers, body), body=body if body is not None else text, resume=resume,
    )


def paid_result_provenance(headers: Any, attempts: int, ids: Tuple[Optional[str], Optional[str]]) -> Optional[Dict[str, Any]]:
    """Provenance of a paid answer (None when the server sent no PAY-05 headers)."""
    h = headers
    if not h.get("x-payment-id") and not h.get("x-paid-result-status"):
        return None
    origin = h.get("x-paid-result-origin")
    stored = h.get("x-paid-result-stored")
    return {
        "payment_id": h.get("x-payment-id") or ids[0], "request_hash": h.get("x-request-hash") or ids[1],
        "status": h.get("x-paid-result-status"), "source": h.get("x-paid-result-source"), "origin": origin,
        "deferred": origin == "deferred", "stored": None if stored is None else stored == "true",
        "paid_at": h.get("x-paid-at"), "generated_at": h.get("x-paid-result-generated-at"),
        "sha256": h.get("x-paid-result-sha256"), "attempts": attempts,
    }


@dataclass
class RecoveryOptions:
    """Bounds of the recovery phase of one paid call."""
    max_attempts: int = 8
    max_elapsed_seconds: float = 600.0
    max_result_missing_retries: int = 2
    sleep: Optional[Callable[[float], Any]] = None
    now: Optional[Callable[[], float]] = None  # wall clock, seconds


class _Plan:
    """Shared decision state of one recovery loop (sync and async drive it)."""

    def __init__(self, options: RecoveryOptions, sign: Callable[[str], str], payment_id: Optional[str], request_hash: Optional[str]):
        self.o = options
        self.sign = sign
        self.local = (payment_id, request_hash)
        self.ids = [payment_id, request_hash]
        self.now = options.now or time.time

    def recovery_header(self) -> Optional[str]:
        pid, rh = self.ids
        if not pid or not rh:
            return None
        issued = int(self.now())
        return encode_recovery_header(pid, rh, issued, self.sign(recovery_message(pid, rh, issued)))

    def remember(self, headers: Any, body: Optional[Dict[str, Any]]) -> None:
        pid = headers.get("x-payment-id") or (body or {}).get("paymentId") or ((body or {}).get("recovery") or {}).get("payment_id")
        rh = headers.get("x-request-hash") or ((body or {}).get("recovery") or {}).get("request_hash")
        if not self.local[0] and isinstance(pid, str) and len(pid) == 64 and set(pid) <= _HEX64:
            self.ids[0] = pid
        if not self.local[1] and isinstance(rh, str) and len(rh) == 64 and set(rh) <= _HEX64:
            self.ids[1] = rh


def run_sync(send: Callable[[Dict[str, str]], Any], base_headers: Dict[str, str], plan: _Plan,
             counter: List[int], start_with_header: bool) -> Tuple[Any, bool]:
    """Drive one bounded recovery loop. Returns (response, pending). Raises
    X402PaymentError(payment_transport_error) when transport fails at the bound."""
    o = plan.o
    sleep = o.sleep or time.sleep
    started = plan.now()
    attempts = missing = gateway = 0
    signature_retried = False
    send_header = start_with_header
    while True:
        attempts += 1
        counter[0] += 1
        headers = dict(base_headers)
        if send_header:
            h = plan.recovery_header()
            if h:
                headers[PAYMENT_RECOVERY_HEADER] = h
        sent_header = PAYMENT_RECOVERY_HEADER in headers
        try:
            resp = send(headers)
        except Exception as exc:  # noqa: BLE001 - transport outcome unknown after the proof was sent
            wait = min(30.0, float(2 ** gateway)); gateway += 1
            if attempts >= o.max_attempts or plan.now() - started + wait > o.max_elapsed_seconds:
                raise X402PaymentError(
                    f"x402 paid request outcome unknown after {counter[0]} send(s): {exc}",
                    status=0, code="payment_transport_error", payment_status="payment_uncertain",
                    payment_id=plan.ids[0], request_hash=plan.ids[1],
                ) from exc
            sleep(wait)
            send_header = True
            continue
        body = _json_or_none(resp.text) if resp.status_code >= 300 else None
        plan.remember(resp.headers, body)
        kind = classify_paid_response(resp.status_code, body)
        if kind == "final":
            return resp, False
        hinted = _retry_after_seconds(resp.headers, body)
        if kind == "signature_required":
            if sent_header or signature_retried:
                return resp, False
            signature_retried = True
            wait = 0.0
        elif kind == "result_missing":
            if missing >= o.max_result_missing_retries:
                return resp, True
            missing += 1
            wait = hinted if hinted is not None else 30.0
        elif kind == "gateway":
            wait = hinted if hinted is not None else min(30.0, float(2 ** gateway)); gateway += 1
        elif kind == "rate_limited":
            wait = hinted if hinted is not None else 60.0
        else:
            wait = hinted if hinted is not None else 5.0
        if attempts >= o.max_attempts or plan.now() - started + wait > o.max_elapsed_seconds:
            return resp, True
        if wait > 0:
            sleep(wait)
        send_header = True


async def run_async(send: Callable[[Dict[str, str]], Awaitable[Any]], base_headers: Dict[str, str], plan: _Plan,
                    counter: List[int], start_with_header: bool) -> Tuple[Any, bool]:
    """Async twin of :func:`run_sync` (same decisions)."""
    o = plan.o
    sleep = o.sleep or asyncio.sleep
    started = plan.now()
    attempts = missing = gateway = 0
    signature_retried = False
    send_header = start_with_header
    while True:
        attempts += 1
        counter[0] += 1
        headers = dict(base_headers)
        if send_header:
            h = plan.recovery_header()
            if h:
                headers[PAYMENT_RECOVERY_HEADER] = h
        sent_header = PAYMENT_RECOVERY_HEADER in headers
        try:
            resp = await send(headers)
        except asyncio.CancelledError:
            raise  # the caller gave up: never retry behind its back
        except Exception as exc:  # noqa: BLE001
            wait = min(30.0, float(2 ** gateway)); gateway += 1
            if attempts >= o.max_attempts or plan.now() - started + wait > o.max_elapsed_seconds:
                raise X402PaymentError(
                    f"x402 paid request outcome unknown after {counter[0]} send(s): {exc}",
                    status=0, code="payment_transport_error", payment_status="payment_uncertain",
                    payment_id=plan.ids[0], request_hash=plan.ids[1],
                ) from exc
            r = sleep(wait)
            if asyncio.iscoroutine(r):
                await r
            send_header = True
            continue
        body = _json_or_none(resp.text) if resp.status_code >= 300 else None
        plan.remember(resp.headers, body)
        kind = classify_paid_response(resp.status_code, body)
        if kind == "final":
            return resp, False
        hinted = _retry_after_seconds(resp.headers, body)
        if kind == "signature_required":
            if sent_header or signature_retried:
                return resp, False
            signature_retried = True
            wait = 0.0
        elif kind == "result_missing":
            if missing >= o.max_result_missing_retries:
                return resp, True
            missing += 1
            wait = hinted if hinted is not None else 30.0
        elif kind == "gateway":
            wait = hinted if hinted is not None else min(30.0, float(2 ** gateway)); gateway += 1
        elif kind == "rate_limited":
            wait = hinted if hinted is not None else 60.0
        else:
            wait = hinted if hinted is not None else 5.0
        if attempts >= o.max_attempts or plan.now() - started + wait > o.max_elapsed_seconds:
            return resp, True
        if wait > 0:
            r = sleep(wait)
            if asyncio.iscoroutine(r):
                await r
        send_header = True
