"""Smoke tests for the robinhood-chain SDK — import, client shape, the 14
endpoint methods, param cleaning, and typed errors. No network calls.

Run: ``pytest`` (or ``python -m pytest``).
"""

import inspect

import pytest

import robinhood_chain
from robinhood_chain import (
    RobinhoodClient,
    RobinhoodError,
    RobinhoodAPIError,
    AuthError,
    TierError,
    NotFoundError,
    RateLimitError,
)
from robinhood_chain.errors import error_for_status


# The 14 GET endpoints from the Robinhood Chain OpenAPI, method -> route path.
ENDPOINTS = {
    "kol_feed": "/rhc/kol/feed",
    "kol_leaderboard": "/rhc/kol/leaderboard",
    "kol_hot_tokens": "/rhc/kol/hot-tokens",
    "kol_wallet": "/rhc/kol/",
    "trades": "/rhc/trades",
    "tokens": "/rhc/tokens",
    "token": "/rhc/tokens/",
    "token_candles": "/rhc/tokens/",
    "token_kol_consensus": "/rhc/tokens/",
    "token_buyer_quality": "/rhc/tokens/",
    "token_bundle": "/rhc/tokens/",
    "deployer_hunter_leaderboard": "/rhc/deployer-hunter/leaderboard",
    "deployer_hunter_profile": "/rhc/deployer-hunter/",
    "alpha_wallets": "/rhc/alpha-wallets",
}


def test_package_imports():
    assert robinhood_chain.__version__
    assert RobinhoodClient.chain == "robinhood"
    assert RobinhoodClient.chain_id == 4663


def test_all_14_endpoint_methods_exist():
    for name in ENDPOINTS:
        assert hasattr(RobinhoodClient, name), f"missing method {name}"
        assert callable(getattr(RobinhoodClient, name))


def test_endpoint_route_literals_present_in_source():
    """Every method's body must reference its real /rhc/* route path."""
    for name, route in ENDPOINTS.items():
        src = inspect.getsource(getattr(RobinhoodClient, name))
        assert route in src, f"{name} does not reference {route}"


def test_requires_api_key():
    with pytest.raises(ValueError):
        RobinhoodClient()
    with pytest.raises(ValueError):
        RobinhoodClient(api_key="not-a-real-prefix")


def test_client_shape_with_key():
    c = RobinhoodClient(api_key="msk_test_key")
    assert c.base_url == "https://madeonsol.com/api/v1"
    assert c._headers["Authorization"] == "Bearer msk_test_key"
    assert "robinhood-chain-python" in c._headers["User-Agent"]
    assert c.last_rate_limit["limit"] is None


def test_param_cleaning_drops_none_and_coerces_bools():
    clean = RobinhoodClient._clean(
        {"a": None, "b": True, "c": False, "d": 5, "e": "x"}
    )
    assert clean == {"b": "true", "c": "false", "d": 5, "e": "x"}
    assert RobinhoodClient._clean({"a": None}) is None
    assert RobinhoodClient._clean(None) is None


def test_error_status_mapping():
    assert isinstance(error_for_status(401, "no key"), AuthError)
    assert isinstance(error_for_status(403, "tier"), TierError)
    assert isinstance(error_for_status(404, "gone"), NotFoundError)
    assert isinstance(error_for_status(429, "slow"), RateLimitError)
    assert isinstance(error_for_status(500, "boom"), RobinhoodAPIError)
    # every mapped error is a RobinhoodError subclass
    for status in (401, 403, 404, 429, 500):
        assert isinstance(error_for_status(status, "x"), RobinhoodError)


def test_rate_limit_error_carries_reset():
    err = error_for_status(429, "slow", reset=1714000000)
    assert isinstance(err, RateLimitError)
    assert err.reset == 1714000000


def test_async_view_exposes_endpoint_coroutines():
    c = RobinhoodClient(api_key="msk_test_key")
    ac = c.aclient()
    for name in ENDPOINTS:
        method = getattr(ac, name)
        assert inspect.iscoroutinefunction(method), f"{name} is not a coroutine"
    with pytest.raises(AttributeError):
        _ = ac.nonexistent_method
