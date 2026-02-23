#!/usr/bin/env python3
"""List all tokens burned in incinerator"""

import asyncio
import aiohttp

INCINERATOR = "1nc1nerator11111111111111111111111111111111"
RPC_URL = "https://rpc.mainnet.x1.xyz"

async def rpc_request(method: str, params: list):
    async with aiohttp.ClientSession() as session:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        async with session.post(RPC_URL, json=payload) as resp:
            result = await resp.json()
            return result.get("result")

async def main():
    print(f"Listing all tokens burned to: {INCINERATOR}")
    print("=" * 80)
    
    # Get all token accounts
    tokens = await rpc_request(
        "getTokenAccountsByOwner",
        [INCINERATOR, {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding": "jsonParsed"}]
    )
    
    if not tokens or not tokens.get("value"):
        print("No tokens found")
        return
    
    print(f"Total token accounts: {len(tokens['value'])}\n")
    print(f"{'#':<3} {'Token Mint':<46} {'Amount':>20} {'Decimals':>10}")
    print("-" * 80)
    
    for i, token_acc in enumerate(tokens["value"], 1):
        parsed = token_acc.get("account", {}).get("data", {}).get("parsed", {})
        info = parsed.get("info", {})
        mint = info.get("mint", "")
        amount_data = info.get("tokenAmount", {})
        amount = amount_data.get("uiAmountString", "0")
        decimals = amount_data.get("decimals", 0)
        
        print(f"{i:<3} {mint:<46} {amount:>20} {decimals:>10}")
    
    print("\n" + "=" * 80)
    print("To check if a specific token's LP is here, look for its LP mint address")
    print("Or run: python3 find_walk_lp.py (for WALK token)")

if __name__ == "__main__":
    asyncio.run(main())
