#!/usr/bin/env python3
"""
LP History Tracker
Shows the history of LP mints, burns, and who added liquidity
"""

import asyncio
import aiohttp
import sys
from datetime import datetime

RPC_URL = "https://rpc.mainnet.x1.xyz"
INCINERATOR = "1nc1nerator11111111111111111111111111111111"

async def rpc_request(method: str, params: list):
    async with aiohttp.ClientSession() as session:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        async with session.post(RPC_URL, json=payload) as resp:
            result = await resp.json()
            return result.get("result")

async def get_lp_holders_with_history(lp_mint: str):
    """Get all LP holders and their current balances"""
    
    print(f"\nLP Mint: {lp_mint}")
    print("=" * 70)
    
    # Get LP mint info
    lp_info = await rpc_request("getAccountInfo", [lp_mint, {"encoding": "jsonParsed"}])
    
    if not lp_info or not lp_info.get("value"):
        print("Could not get LP info")
        return
    
    lp_data = lp_info["value"].get("data", {}).get("parsed", {}).get("info", {})
    total_supply = int(lp_data.get("supply", 0))
    decimals = lp_data.get("decimals", 9)
    total_supply_ui = total_supply / (10 ** decimals)
    
    print(f"Total LP Supply: {total_supply_ui:,.2f}")
    print(f"Decimals: {decimals}")
    
    # Get all LP holders
    print(f"\n{'='*70}")
    print("CURRENT LP HOLDERS")
    print(f"{'='*70}")
    
    holders = await rpc_request("getTokenLargestAccounts", [lp_mint])
    
    if not holders or not holders.get("value"):
        print("No holders found")
        return
    
    burned_total = 0
    other_total = 0
    holder_list = []
    
    for h in holders["value"]:
        addr = h.get("address", "")
        amount = float(h.get("uiAmount", 0) or 0)
        
        if amount <= 0:
            continue
        
        # Get owner
        h_info = await rpc_request("getAccountInfo", [addr, {"encoding": "jsonParsed"}])
        owner = ""
        if h_info and h_info.get("value"):
            owner = h_info["value"].get("data", {}).get("parsed", {}).get("info", {}).get("owner", "")
        
        is_incinerator = owner == INCINERATOR
        pct = (amount / total_supply_ui * 100) if total_supply_ui > 0 else 0
        
        if is_incinerator:
            burned_total += amount
            status = "🔥 BURNED (Incinerator)"
        else:
            other_total += amount
            status = f"Holder: {owner[:20]}..."
        
        holder_list.append({
            "address": addr,
            "amount": amount,
            "pct": pct,
            "owner": owner,
            "is_burned": is_incinerator
        })
        
        print(f"\n  Account: {addr}")
        print(f"  Amount: {amount:,.2f} ({pct:.2f}%)")
        print(f"  Status: {status}")
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"Total LP Supply:     {total_supply_ui:,.2f}")
    print(f"🔥 Burned to Incinerator: {burned_total:,.2f} ({burned_total/total_supply_ui*100:.2f}%)")
    print(f"👥 Held by Others:   {other_total:,.2f} ({other_total/total_supply_ui*100:.2f}%)")
    
    print(f"\n{'='*70}")
    print("INTERPRETATION")
    print(f"{'='*70}")
    
    if burned_total > 0:
        print(f"✅ The original LP provider burned {burned_total:,.2f} LP tokens")
        if other_total > 0:
            print(f"📊 Since then, other users added liquidity, creating {other_total:,.2f} new LP tokens")
            print(f"📉 This diluted the burn % from 100% to {burned_total/total_supply_ui*100:.2f}%")
        else:
            print(f"🔒 No additional liquidity has been added - burn remains at 100%")
    else:
        print(f"⚠️ No LP tokens have been burned to the incinerator")
    
    # Try to get transaction history for the burn
    print(f"\n{'='*70}")
    print("TRANSACTION SIGNATURES (for burn account)")
    print(f"{'='*70}")
    
    # Find the burn account
    burn_account = None
    for h in holder_list:
        if h["is_burned"]:
            burn_account = h["address"]
            break
    
    if burn_account:
        print(f"Burn Account: {burn_account}")
        
        # Get signatures for this account
        sigs = await rpc_request(
            "getSignaturesForAddress",
            [burn_account, {"limit": 10}]
        )
        
        if sigs:
            print(f"\nRecent transactions:")
            for sig in sigs:
                signature = sig.get("signature", "")
                block_time = sig.get("blockTime", 0)
                if block_time:
                    dt = datetime.fromtimestamp(block_time)
                    time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    time_str = "Unknown"
                
                print(f"  {time_str}: {signature[:30]}...")
                print(f"    View: https://explorer.x1.xyz/tx/{signature}")

async def main():
    if len(sys.argv) > 1:
        lp_mint = sys.argv[1]
    else:
        # Default to the LP mint from the dev's token
        lp_mint = input("Enter LP Mint address (or press Enter for default): ").strip()
        if not lp_mint:
            lp_mint = "9JoeLMmFgeyJLqoxxGo2cXwJLtdCjCHYz2r1uetp4HGF"
    
    await get_lp_holders_with_history(lp_mint)

if __name__ == "__main__":
    asyncio.run(main())
