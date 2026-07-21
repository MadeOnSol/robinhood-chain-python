"""Robinhood Chain SDK — quick start.

    pip install robinhood-chain
    export MADEONSOL_API_KEY=msk_...   # free key at https://madeonsol.com/pricing
    python examples/quickstart.py
"""

import os

from robinhood_chain import RobinhoodClient

client = RobinhoodClient(api_key=os.environ["MADEONSOL_API_KEY"])

# 1) Real-time KOL trade feed on Robinhood Chain (chain id 4663) — BASIC.
feed = client.kol_feed(limit=10, action="buy")
print(f"chain={feed['chain']} count={feed.get('count')}")
for tr in feed["trades"]:
    print(
        f"  {tr.get('kol_name') or tr['evm_address'][:10]} "
        f"{tr['action']} {tr.get('token_symbol') or tr['token_address'][:10]} "
        f"for {tr.get('eth_amount')} ETH "
        f"(x{tr.get('mc_multiple_since_trade')}) tx={tr['tx_hash'][:12]}"
    )

# 2) Consensus tokens — bought by 2+ KOLs in the last hour — BASIC.
hot = client.kol_hot_tokens(window="1h")
for tok in hot["tokens"]:
    print(f"  {tok.get('token_symbol')} — {tok['kols_buying']} KOLs, {tok['buy_eth']} ETH")

# 3) One token: snapshot + launch-bundle + early-buyer quality — BASIC.
addr = feed["trades"][0]["token_address"] if feed["trades"] else "0x0000000000000000000000000000000000000000"
detail = client.token(addr)
bundle = client.token_bundle(addr)
quality = client.token_buyer_quality(addr)
print(f"\n{addr}")
print(f"  mc_usd={detail.get('market_cap_usd')} liq_usd={detail.get('liquidity_usd')}")
print(f"  bundle_kind={bundle['bundle']['bundle_kind']} held_ratio={bundle['bundle'].get('held_ratio')}")
print(f"  buyer_quality={quality['quality']['score']} ({quality['quality']['signal']})")

# 4) Deployer reputation leaderboard — BASIC.
lb = client.deployer_hunter_leaderboard(sort="runner_rate", tier="elite", limit=5)
for dep in lb["deployers"]:
    print(f"  {dep['deployer_address'][:12]} {dep['tier']} runner_rate={dep['runner_rate']}")

# Rate-limit headers from the most recent call:
print("\nrate limit:", client.last_rate_limit)
