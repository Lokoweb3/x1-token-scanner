#!/usr/bin/env python3
"""
Universal LP Burn Checker
Enter any token address to check if its LP is burned to the incinerator
"""

import asyncio
import aiohttp
import base58
import base64
import sys

INCINERATOR = "1nc1nerator11111111111111111111111111111111"
RPC_URL = "https://rpc.mainnet.x1.xyz"
AMM_PROGRAM = "sEsYH97wqmfnkzHedjNcw3zyJdPvUmsa9AixhS4b4fN"  # XDEX AMM

async def rpc_request(method: str, params: list):
    async with aiohttp.ClientSession() as session:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        async with session.post(RPC_URL, json=payload) as resp:
            result = await resp.json()
            return result.get("result")


async def get_burn_transaction(burn_account: str):
    """Get the burn transaction signature for this account"""
    try:
        sigs = await rpc_request(
            "getSignaturesForAddress",
            [burn_account, {"limit": 1}]
        )
        if sigs and len(sigs) > 0:
            return sigs[0].get("signature", "")
    except:
        pass
    return None


async def decode_burn_tx(tx_sig: str):
    """Decode and display the burn transaction details"""
    tx = await rpc_request("getTransaction", [tx_sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
    
    if not tx:
        print("   Could not fetch transaction")
        return
    
    from datetime import datetime
    
    block_time = tx.get("blockTime", 0)
    slot = tx.get("slot", 0)
    meta = tx.get("meta", {})
    fee = meta.get("fee", 0)
    
    print(f"   {'='*50}")
    if block_time:
        dt = datetime.fromtimestamp(block_time)
        print(f"   Date/Time: {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"   Slot: {slot}")
    print(f"   Status: ✅ Success")
    print(f"   Fee: {fee / 1e9:.9f} XN")
    
    # Token balance changes
    pre_balances = meta.get("preTokenBalances", [])
    post_balances = meta.get("postTokenBalances", [])
    
    if pre_balances or post_balances:
        print(f"   {'='*50}")
        print(f"   TOKEN BALANCE CHANGES")
        print(f"   {'='*50}")
        
        changes = {}
        for bal in pre_balances:
            idx = bal.get("accountIndex", 0)
            mint = bal.get("mint", "")
            owner = bal.get("owner", "")
            amount = float(bal.get("uiTokenAmount", {}).get("uiAmount", 0) or 0)
            key = f"{idx}_{mint}"
            changes[key] = {"mint": mint, "owner": owner, "pre": amount, "post": 0}
        
        for bal in post_balances:
            idx = bal.get("accountIndex", 0)
            mint = bal.get("mint", "")
            owner = bal.get("owner", "")
            amount = float(bal.get("uiTokenAmount", {}).get("uiAmount", 0) or 0)
            key = f"{idx}_{mint}"
            if key in changes:
                changes[key]["post"] = amount
            else:
                changes[key] = {"mint": mint, "owner": owner, "pre": 0, "post": amount}
        
        for key, data in changes.items():
            diff = data["post"] - data["pre"]
            if diff != 0:
                direction = "📈" if diff > 0 else "📉"
                owner_short = data['owner'][:12] + "..." + data['owner'][-4:] if len(data['owner']) > 20 else data['owner']
                is_burn = "1nc1nerator" in data['owner']
                burn_label = " 🔥 BURNED!" if is_burn and diff > 0 else ""
                
                print(f"   Token: {data['mint'][:20]}...")
                print(f"   Owner: {owner_short}{burn_label}")
                print(f"   Change: {direction} {diff:+,.6f} ({data['pre']:,.6f} → {data['post']:,.6f})")
                print()
    
    print(f"   {'='*50}")

async def get_burned_lp_mints():
    """Get all LP mints that have tokens burned to incinerator"""
    tokens = await rpc_request(
        "getTokenAccountsByOwner",
        [INCINERATOR, {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding": "jsonParsed"}]
    )
    
    burned = {}
    if tokens and tokens.get("value"):
        for tok in tokens["value"]:
            info = tok.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
            mint = info.get("mint", "")
            amount = float(info.get("tokenAmount", {}).get("uiAmount", 0) or 0)
            if amount > 0:
                burned[mint] = {
                    "amount": amount,
                    "account": tok.get("pubkey", "")
                }
    return burned

async def find_pools_for_token(token_mint: str):
    """Find all AMM pools that contain this token"""
    pools = []
    token_bytes = base58.b58decode(token_mint)
    
    # Get all accounts owned by the AMM program
    print("Searching for pools containing this token...")
    
    # Use getProgramAccounts with memcmp filter for the token mint
    # This searches for pools that have our token at common offsets
    for offset in [200, 232, 264]:  # Common offsets for token mints in pool data
        result = await rpc_request(
            "getProgramAccounts",
            [
                AMM_PROGRAM,
                {
                    "encoding": "base64",
                    "filters": [
                        {"memcmp": {"offset": offset, "bytes": token_mint}}
                    ]
                }
            ]
        )
        
        if result:
            for acc in result:
                pool_address = acc.get("pubkey", "")
                if pool_address and pool_address not in [p["address"] for p in pools]:
                    pools.append({
                        "address": pool_address,
                        "data": acc.get("account", {}).get("data", [None])[0]
                    })
    
    return pools

async def extract_lp_mint_from_pool(pool_data_b64: str):
    """Extract LP mint address from pool data"""
    if not pool_data_b64:
        return None
    
    try:
        raw_data = base64.b64decode(pool_data_b64)
        
        # LP mint is typically at offset 136 in XDEX pools
        # Try common offsets
        for offset in [136, 168, 104, 72]:
            if offset + 32 <= len(raw_data):
                potential_mint = raw_data[offset:offset+32]
                mint_str = base58.b58encode(potential_mint).decode()
                
                # Verify it's a valid mint
                mint_info = await rpc_request("getAccountInfo", [mint_str, {"encoding": "jsonParsed"}])
                if mint_info and mint_info.get("value"):
                    data = mint_info["value"].get("data", {})
                    if isinstance(data, dict) and data.get("parsed", {}).get("type") == "mint":
                        return mint_str
    except:
        pass
    
    return None

async def check_lp_burn(token_mint: str):
    """Main function to check LP burn for a token"""
    print(f"\n{'='*60}")
    print(f"Checking LP burn for token: {token_mint}")
    print(f"{'='*60}\n")
    
    # Step 1: Get all burned LP mints from incinerator
    print("Step 1: Fetching burned tokens from incinerator...")
    burned_lps = await get_burned_lp_mints()
    print(f"   Found {len(burned_lps)} tokens in incinerator\n")
    
    # Step 2: Find pools containing our token
    print("Step 2: Finding pools for this token...")
    pools = await find_pools_for_token(token_mint)
    print(f"   Found {len(pools)} pools\n")
    
    if not pools:
        print("❌ No pools found for this token")
        print("   The token may not have liquidity on XDEX")
        return None
    
    # Step 3: Check each pool's LP mint
    print("Step 3: Checking LP mints...")
    
    results = []
    for pool in pools:
        pool_addr = pool["address"]
        print(f"\n   Pool: {pool_addr}")
        
        lp_mint = await extract_lp_mint_from_pool(pool["data"])
        if not lp_mint:
            print(f"   Could not extract LP mint")
            continue
        
        print(f"   LP Mint: {lp_mint}")
        
        # Check if this LP is burned
        if lp_mint in burned_lps:
            burned_amount = burned_lps[lp_mint]["amount"]
            burn_account = burned_lps[lp_mint]["account"]
            
            # Get total supply
            lp_info = await rpc_request("getAccountInfo", [lp_mint, {"encoding": "jsonParsed"}])
            total_supply = 0
            if lp_info and lp_info.get("value"):
                lp_data = lp_info["value"].get("data", {}).get("parsed", {}).get("info", {})
                supply = int(lp_data.get("supply", 0))
                decimals = lp_data.get("decimals", 9)
                total_supply = supply / (10**decimals)
            
            burn_pct = (burned_amount / total_supply * 100) if total_supply > 0 else 0
            
            print(f"   🔥 LP BURNED!")
            print(f"   Burned Amount: {burned_amount:,.2f}")
            print(f"   Total Supply: {total_supply:,.2f}")
            print(f"   Burn %: {burn_pct:.2f}%")
            print(f"   Burn Account: {burn_account}")
            
            # Get burn transaction
            burn_tx = await get_burn_transaction(burn_account)
            
            results.append({
                "pool": pool_addr,
                "lp_mint": lp_mint,
                "burned": True,
                "burn_percent": burn_pct,
                "burn_amount": burned_amount,
                "total_supply": total_supply,
                "burn_account": burn_account,
                "burn_tx": burn_tx
            })
        else:
            print(f"   ❌ LP NOT burned to incinerator")
            results.append({
                "pool": pool_addr,
                "lp_mint": lp_mint,
                "burned": False
            })
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    
    burned_pools = [r for r in results if r.get("burned")]
    if burned_pools:
        best = max(burned_pools, key=lambda x: x["burn_percent"])
        print(f"✅ LP BURNED: {best['burn_percent']:.2f}%")
        print(f"   LP Mint: {best['lp_mint']}")
        print(f"   Pool: {best['pool']}")
        print(f"   Burn Account: https://explorer.x1.xyz/address/{best['burn_account']}")
        if best.get('burn_tx'):
            print(f"   Burn TX: https://explorer.x1.xyz/tx/{best['burn_tx']}")
            print(f"\n🔥 BURN TRANSACTION DETAILS:")
            await decode_burn_tx(best['burn_tx'])
        return best
    else:
        print("❌ No burned LP found for this token")
        return None

async def main():
    if len(sys.argv) > 1:
        token_mint = sys.argv[1]
    else:
        token_mint = input("Enter token mint address: ").strip()
    
    if not token_mint:
        print("No token address provided")
        return
    
    result = await check_lp_burn(token_mint)
    return result

if __name__ == "__main__":
    asyncio.run(main())
