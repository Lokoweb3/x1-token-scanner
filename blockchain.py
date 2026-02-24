"""
X1 Blockchain Interaction Module
Uses Solana-compatible RPC calls for the X1 SVM chain
"""

import asyncio
import aiohttp
import base64
import base58
import struct
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass

from config import X1_CONFIG, PROGRAM_IDS, BURN_ADDRESSES
from lp_cache import (
    get_cached_lp_status, set_cached_lp_status,
    get_cached_initial_supply, set_cached_initial_supply
)


@dataclass
class TokenInfo:
    """SPL Token information"""
    mint_address: str
    decimals: int
    supply: int
    mint_authority: Optional[str]
    freeze_authority: Optional[str]
    is_initialized: bool


@dataclass
class TokenMetadata:
    """Token Metadata (Metaplex standard)"""
    name: str
    symbol: str
    uri: str
    seller_fee_basis_points: int
    creators: List[Dict]


@dataclass
class LPInfo:
    """LP Pool information"""
    pool_address: str
    lp_mint: str
    token_reserve: float
    wxnt_reserve: float
    price_in_wxnt: float
    liquidity_wxnt: float
    pool_authority: str


class X1RPC:
    """Handles all X1 blockchain interactions via JSON-RPC"""
    
    def __init__(self, rpc_url: str = None):
        self.rpc_url = rpc_url or X1_CONFIG["rpc_url"]
        self._request_id = 0
    
    def _get_request_id(self) -> int:
        self._request_id += 1
        return self._request_id
    
    async def _rpc_request(self, method: str, params: List = None) -> Dict:
        """Make a JSON-RPC request to X1"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._get_request_id(),
            "method": method,
            "params": params or []
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.rpc_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            ) as response:
                result = await response.json()
                
                if "error" in result:
                    raise Exception(f"RPC Error: {result['error']}")
                
                return result.get("result")
    
    def is_valid_address(self, address: str) -> bool:
        """Validate Solana-style base58 address"""
        try:
            decoded = base58.b58decode(address)
            return len(decoded) == 32
        except Exception:
            return False
    
    async def get_account_info(self, address: str) -> Optional[Dict]:
        """Get account info for an address"""
        try:
            result = await self._rpc_request(
                "getAccountInfo",
                [address, {"encoding": "base64"}]
            )
            return result
        except Exception:
            return None
    
    async def is_token_account(self, address: str) -> bool:
        """Check if address is an SPL token mint"""
        account_info = await self.get_account_info(address)
        
        if not account_info or not account_info.get("value"):
            return False
        
        owner = account_info["value"].get("owner")
        return owner in [PROGRAM_IDS["token_program"], PROGRAM_IDS["token_2022_program"]]
    
    async def get_token_supply(self, mint_address: str) -> Optional[Dict]:
        """Get token supply info"""
        try:
            result = await self._rpc_request(
                "getTokenSupply",
                [mint_address]
            )
            return result
        except Exception:
            return None
    
    async def get_token_info(self, mint_address: str) -> Optional[TokenInfo]:
        """Parse token mint account data"""
        account_info = await self.get_account_info(mint_address)
        
        if not account_info or not account_info.get("value"):
            return None
        
        data = account_info["value"].get("data")
        if not data:
            return None
        
        try:
            raw_data = base64.b64decode(data[0])
        except Exception:
            return None
        
        if len(raw_data) < 82:
            return None
        
        try:
            mint_auth_option = struct.unpack("<I", raw_data[0:4])[0]
            mint_authority = None
            if mint_auth_option == 1:
                mint_authority = base58.b58encode(raw_data[4:36]).decode()
            
            supply = struct.unpack("<Q", raw_data[36:44])[0]
            decimals = raw_data[44]
            is_initialized = raw_data[45] == 1
            
            freeze_auth_option = struct.unpack("<I", raw_data[46:50])[0]
            freeze_authority = None
            if freeze_auth_option == 1:
                freeze_authority = base58.b58encode(raw_data[50:82]).decode()
            
            return TokenInfo(
                mint_address=mint_address,
                decimals=decimals,
                supply=supply,
                mint_authority=mint_authority,
                freeze_authority=freeze_authority,
                is_initialized=is_initialized,
            )
        except Exception as e:
            print(f"Error parsing token data: {e}")
            return None
    
    async def get_token_age(self, mint_address: str) -> Optional[str]:
        """Get token creation time by paginating through all transactions"""
        from datetime import datetime
        
        try:
            all_sigs = []
            before = None
            max_pages = 25
            
            for page in range(max_pages):
                params = [mint_address, {"limit": 1000}]
                if before:
                    params[1]["before"] = before
                
                result = await self._rpc_request("getSignaturesForAddress", params)
                
                if not result or len(result) == 0:
                    break
                
                all_sigs.extend(result)
                before = result[-1].get("signature")
                
                if len(result) < 1000:
                    break
                
                await asyncio.sleep(0.05)
            
            if not all_sigs:
                return None
            
            oldest_tx = all_sigs[-1]
            block_time = oldest_tx.get("blockTime")
            
            if not block_time:
                return None
            
            created_at = datetime.fromtimestamp(block_time)
            now = datetime.now()
            age_delta = now - created_at
            
            days = age_delta.days
            if days >= 365:
                return f"{days // 365}y"
            elif days >= 30:
                return f"{days // 30}mo"
            elif days >= 1:
                return f"{days}d"
            else:
                hours = int(age_delta.total_seconds() / 3600)
                if hours >= 1:
                    return f"{hours}h"
                else:
                    return "<1h"
                    
        except Exception as e:
            print(f"Error getting token age: {e}")
            return None

    async def get_deployer_info(self, mint_address: str) -> Optional[Dict]:
        """Get token deployer wallet and their history"""
        from datetime import datetime
        
        try:
            # Step 1: Find the oldest (creation) transaction
            all_sigs = []
            before = None
            for page in range(25):
                params = [mint_address, {"limit": 1000}]
                if before:
                    params[1]["before"] = before
                result = await self._rpc_request("getSignaturesForAddress", params)
                if not result:
                    break
                all_sigs.extend(result)
                before = result[-1].get("signature")
                if len(result) < 1000:
                    break
                await asyncio.sleep(0.05)

            if not all_sigs:
                return None

            # Get the oldest transaction (token creation)
            oldest_sig = all_sigs[-1].get("signature")
            creation_time = all_sigs[-1].get("blockTime")
            
            if not oldest_sig:
                return None

            tx = await self._rpc_request(
                "getTransaction",
                [oldest_sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
            )
            
            if not tx:
                return None

            # Step 2: Extract the deployer (fee payer / first signer)
            message = tx.get("transaction", {}).get("message", {})
            account_keys = message.get("accountKeys", [])
            
            deployer = None
            for key in account_keys:
                if isinstance(key, dict):
                    if key.get("signer", False):
                        deployer = key.get("pubkey", "")
                        break
                elif isinstance(key, str):
                    deployer = key
                    break

            if not deployer:
                return None

            # Step 3: Check how many tokens this deployer has created
            # Search for initializeMint transactions by this wallet
            deployer_sigs = await self._rpc_request(
                "getSignaturesForAddress",
                [deployer, {"limit": 1000}]
            )

            tokens_created = 0
            token_mints = []
            
            if deployer_sigs:
                # Sample up to 50 transactions to find token creations
                for sig_info in deployer_sigs[:50]:
                    sig = sig_info.get("signature")
                    if not sig:
                        continue
                    try:
                        dtx = await self._rpc_request(
                            "getTransaction",
                            [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                        )
                        if not dtx:
                            continue

                        d_message = dtx.get("transaction", {}).get("message", {})
                        d_instructions = d_message.get("instructions", [])
                        inner = dtx.get("meta", {}).get("innerInstructions", [])
                        all_ix = list(d_instructions)
                        for ig in inner:
                            all_ix.extend(ig.get("instructions", []))

                        for ix in all_ix:
                            parsed = ix.get("parsed", {})
                            if not isinstance(parsed, dict):
                                continue
                            ix_type = parsed.get("type", "")
                            if ix_type in ["initializeMint", "initializeMint2"]:
                                ix_mint = parsed.get("info", {}).get("mint", "")
                                if ix_mint and ix_mint not in token_mints:
                                    tokens_created += 1
                                    token_mints.append(ix_mint)
                    except:
                        continue

            # Step 4: Check if deployer still holds this token
            deployer_balance = 0
            try:
                balance_result = await self._rpc_request(
                    "getTokenAccountsByOwner",
                    [deployer, {"mint": mint_address}, {"encoding": "jsonParsed"}]
                )
                if balance_result and balance_result.get("value"):
                    for acc in balance_result["value"]:
                        info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                        amt = float(info.get("tokenAmount", {}).get("uiAmount", 0) or 0)
                        deployer_balance += amt
            except:
                pass

            created_str = ""
            if creation_time:
                created_str = datetime.fromtimestamp(creation_time).strftime("%Y-%m-%d")

            return {
                "deployer": deployer,
                "tokens_created": tokens_created,
                "token_mints": token_mints,
                "deployer_balance": deployer_balance,
                "creation_date": created_str,
                "creation_tx": oldest_sig,
            }

        except Exception as e:
            print(f"Error getting deployer info: {e}")
            return None
    
    async def get_token_largest_accounts(self, mint_address: str, limit: int = 20) -> List[Dict]:
        """Get largest token accounts"""
        try:
            result = await self._rpc_request(
                "getTokenLargestAccounts",
                [mint_address]
            )
            if result and result.get("value"):
                return result["value"][:limit]
            return []
        except Exception:
            return []
    
    async def get_lp_info(self, token_mint: str, decimals: int) -> Optional[LPInfo]:
        """Get LP pool info using transaction-based detection"""
        WXNT_MINT = "So11111111111111111111111111111111111111112"
        AMM_AUTHORITY = "9Dpjw2pB5kXJr6ZTHiqzEMfJPic3om9jgNacnwpLCoaU"
        
        try:
            sigs = await self._rpc_request(
                "getSignaturesForAddress",
                [token_mint, {"limit": 50}]
            )
            
            if not sigs:
                return None
            
            for sig_info in sigs[:20]:
                sig = sig_info.get("signature")
                if not sig:
                    continue
                
                tx = await self._rpc_request(
                    "getTransaction",
                    [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                )
                
                if not tx:
                    continue
                
                meta = tx.get("meta", {})
                post_balances = meta.get("postTokenBalances", [])
                
                token_balance = None
                wxnt_balance = None
                
                for bal in post_balances:
                    mint = bal.get("mint", "")
                    owner = bal.get("owner", "")
                    
                    if owner == AMM_AUTHORITY:
                        amount = float(bal.get("uiTokenAmount", {}).get("uiAmount", 0) or 0)
                        if mint == token_mint and amount > 0:
                            token_balance = amount
                        elif mint == WXNT_MINT and amount > 0:
                            # Pick the largest WXNT balance (main pool)
                            if wxnt_balance is None or amount > wxnt_balance:
                                wxnt_balance = amount
                
                if token_balance and wxnt_balance and token_balance > 0:
                    price = wxnt_balance / token_balance
                    liquidity = wxnt_balance * 2
                    
                    return LPInfo(
                        pool_address="",
                        lp_mint="",
                        token_reserve=token_balance,
                        wxnt_reserve=wxnt_balance,
                        price_in_wxnt=price,
                        liquidity_wxnt=liquidity,
                        pool_authority=AMM_AUTHORITY
                    )
            
            return None
            
        except Exception as e:
            print(f"Error getting LP info: {e}")
            return None
    
    async def check_lp_status(self, mint_address: str) -> Dict:
        """Check LP burn status across ALL pools for a token"""
        import time as _time
        _start = _time.time()

        # Check cache first
        cached = get_cached_lp_status(mint_address)
        if cached:
            return cached

        INCINERATOR = "1nc1nerator11111111111111111111111111111111"
        AMM_PROGRAM = "sEsYH97wqmfnkzHedjNcw3zyJdPvUmsa9AixhS4b4fN"

        result = {
            "lp_found": False,
            "lp_burned": False,
            "lp_burn_percent": 0.0,
            "lp_address": None,
            "lp_mint": None,
            "lp_total_supply": 0.0,
            "lp_burned_amount": 0.0,
            # NEW: Multi-pool data
            "pools": [],
            "total_lp_supply_all_pools": 0.0,
            "total_burned_all_pools": 0.0,
            "total_burn_percent": 0.0,
            "burn_tx_count": 0,
        }

        try:
            # Step 1: Find ALL pools containing this token
            # Search at multiple offsets where token mints appear in XDEX pool data
            pools = []
            search_offsets = [200, 232, 264, 168, 296, 328]
            for offset in search_offsets:
                try:
                    pool_result = await self._rpc_request(
                        "getProgramAccounts",
                        [
                            AMM_PROGRAM,
                            {
                                "encoding": "base64",
                                "filters": [
                                    {"memcmp": {"offset": offset, "bytes": mint_address}}
                                ]
                            }
                        ]
                    )
                    if pool_result:
                        for acc in pool_result:
                            pool_addr = acc.get("pubkey", "")
                            if pool_addr and pool_addr not in [p["address"] for p in pools]:
                                pools.append({
                                    "address": pool_addr,
                                    "data": acc.get("account", {}).get("data", [None])[0]
                                })
                except:
                    continue

            if not pools:
                return result

            result["lp_found"] = True

            # Step 2: For EACH pool, extract LP mint, supply, and burn data
            pool_details = []
            total_lp_supply = 0.0      # original supply (current + burned for BurnChecked)
            total_current_supply = 0.0  # current on-chain supply
            total_burned = 0.0
            total_burn_txs = 0

            for pool in pools:
                pool_data = pool.get("data")
                if not pool_data:
                    continue
                try:
                    import base64 as b64
                    raw_data = b64.b64decode(pool_data)
                    if len(raw_data) < 168:
                        continue

                    # Try multiple offsets for LP mint in pool data
                    lp_mint = None
                    known_mints = {mint_address}  # Skip the token we're searching for
                    WXNT_MINT = "So11111111111111111111111111111111111111112"
                    SKIP_MINTS = {
                        mint_address, WXNT_MINT,
                        PROGRAM_IDS["token_program"],
                        PROGRAM_IDS["token_2022_program"],
                        "sEsYH97wqmfnkzHedjNcw3zyJdPvUmsa9AixhS4b4fN",
                    }

                    # Scan all 32-byte aligned offsets for a mint that isn't the token or WXNT
                    for lp_offset in [136, 104, 72, 168, 200, 232, 264, 296, 328, 40, 8]:
                        if lp_offset + 32 > len(raw_data):
                            continue
                        potential_mint = raw_data[lp_offset:lp_offset + 32]
                        
                        # Skip null bytes
                        if all(b == 0 for b in potential_mint):
                            continue
                        
                        candidate = base58.b58encode(potential_mint).decode()
                        
                        # Skip known non-LP mints
                        if candidate in SKIP_MINTS:
                            continue
                        
                        # Verify it's a valid mint account
                        try:
                            mint_info = await self._rpc_request(
                                "getAccountInfo",
                                [candidate, {"encoding": "jsonParsed"}]
                            )
                            if mint_info and mint_info.get("value"):
                                data = mint_info["value"].get("data", {})
                                if isinstance(data, dict) and data.get("parsed", {}).get("type") == "mint":
                                    lp_mint = candidate
                                    break
                        except:
                            continue

                    if not lp_mint:
                        # Can't find LP mint — still include pool with 0 supply
                        # so it shows up in pool count
                        pair_label = await self._identify_pool_pair(pool["address"], mint_address, raw_data, None)
                        pool_info = {
                            "pool_address": pool["address"],
                            "lp_mint": None,
                            "lp_supply": 0,
                            "lp_original_supply": 0,
                            "burned_amount": 0,
                            "burn_percent": 0,
                            "burn_tx_count": 0,
                            "burn_account": None,
                            "burn_method": None,
                            "pair_label": pair_label,
                        }
                        pool_details.append(pool_info)
                        continue

                    # Re-fetch to get latest supply data
                    mint_info = await self._rpc_request(
                        "getAccountInfo",
                        [lp_mint, {"encoding": "jsonParsed"}]
                    )
                    if not mint_info or not mint_info.get("value"):
                        continue

                    lp_parsed = mint_info["value"].get("data", {}).get("parsed", {}).get("info", {})
                    supply = int(lp_parsed.get("supply", 0))
                    decimals = lp_parsed.get("decimals", 9)
                    supply_ui = supply / (10 ** decimals)

                    # Don't skip zero supply yet — BurnChecked might have destroyed all tokens
                    # We'll check for burns first and calculate original supply

                    # ── LP Burn Detection ──
                    initial_supply = await self._get_initial_lp_supply(lp_mint, decimals)
                    
                    # Method 1: Incinerator balance
                    incinerator_amount = 0.0
                    incinerator_txs = 0
                    burn_account = None
                    
                    burn_check = await self._rpc_request(
                        "getTokenAccountsByOwner",
                        [INCINERATOR, {"mint": lp_mint}, {"encoding": "jsonParsed"}]
                    )
                    if burn_check and burn_check.get("value"):
                        for tok in burn_check["value"]:
                            info = tok.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                            amt = float(info.get("tokenAmount", {}).get("uiAmount", 0) or 0)
                            if amt > 0:
                                incinerator_amount += amt
                                burn_account = tok.get("pubkey", "")
                                try:
                                    sigs = await self._rpc_request(
                                        "getSignaturesForAddress",
                                        [burn_account, {"limit": 20}]
                                    )
                                    if sigs:
                                        incinerator_txs = len(sigs)
                                except:
                                    incinerator_txs = 1

                    # Method 2: BurnChecked (for tx count display)
                    bc_burned, bc_tx_count = await self._check_burn_checked(lp_mint, decimals)

                    # Determine burn method label
                    if incinerator_amount > 0 and bc_burned > 0:
                        burn_method = "Both"
                    elif incinerator_amount > 0:
                        burn_method = "incinerator"
                    elif bc_burned > 0:
                        burn_method = "BurnChecked"
                    else:
                        burn_method = None
                    
                    burn_tx_count = incinerator_txs + bc_tx_count

                    # Calculate burned amount using adaptive formula:
                    # Case 1: initial >= current → supply diff method (Loko_AI style)
                    # Case 2: current > initial (LP grew) → use total removed / total minted
                    
                    if initial_supply > 0 and initial_supply >= supply_ui:
                        # Supply diff method: initial - current + incinerator
                        supply_diff = initial_supply - supply_ui
                        burned_amount = supply_diff + incinerator_amount
                        original_supply_for_pool = initial_supply + incinerator_amount if incinerator_amount > 0 else initial_supply
                    elif incinerator_amount > 0 or bc_burned > 0:
                        # LP supply grew after burns — use total removed / total minted
                        total_minted = await self._get_total_lp_minted(lp_mint, decimals)
                        if total_minted > 0:
                            burned_amount = incinerator_amount + bc_burned
                            original_supply_for_pool = total_minted
                        else:
                            burned_amount = incinerator_amount + bc_burned
                            original_supply_for_pool = supply_ui + bc_burned + incinerator_amount
                    else:
                        burned_amount = 0
                        original_supply_for_pool = supply_ui if supply_ui > 0 else (initial_supply if initial_supply > 0 else 1)
                    
                    burn_pct = (burned_amount / original_supply_for_pool * 100) if original_supply_for_pool > 0 else 0

                    # Identify the pair token for this pool
                    pair_label = await self._identify_pool_pair(pool["address"], mint_address, raw_data, lp_mint)

                    # Skip if original supply is truly 0 (no tokens ever existed)
                    if original_supply_for_pool == 0:
                        continue

                    # Skip duplicate LP mints (same pool found via different offsets)
                    if any(p["lp_mint"] == lp_mint for p in pool_details):
                        continue

                    pool_info = {
                        "pool_address": pool["address"],
                        "lp_mint": lp_mint,
                        "lp_supply": supply_ui,
                        "lp_original_supply": original_supply_for_pool,
                        "burned_amount": burned_amount,
                        "burn_percent": min(100, burn_pct),
                        "burn_tx_count": burn_tx_count,
                        "burn_account": burn_account,
                        "burn_method": burn_method,
                        "pair_label": pair_label,
                    }
                    pool_details.append(pool_info)

                    total_lp_supply += original_supply_for_pool
                    total_current_supply += supply_ui
                    total_burned += burned_amount
                    total_burn_txs += burn_tx_count

                except Exception:
                    continue

            if not pool_details:
                return result

            # Sort pools by original LP supply (largest first)
            pool_details.sort(key=lambda x: x["lp_original_supply"], reverse=True)

            # Main pool = largest by original supply
            main_pool = pool_details[0]

            # Calculate overall burn percentage
            # LP Safety = total supply difference / total initial supply
            # This matches Loko_AI's on-chain supply difference method
            overall_burn_pct = (total_burned / total_lp_supply * 100) if total_lp_supply > 0 else 0
            
            # Per-pool burn % of total
            for p in pool_details:
                p["burn_percent_of_total"] = (p["burned_amount"] / total_lp_supply * 100) if total_lp_supply > 0 else 0

            result["pools"] = pool_details
            result["total_lp_supply_all_pools"] = total_lp_supply
            result["total_burned_all_pools"] = total_burned
            result["total_burn_percent"] = min(100, overall_burn_pct)
            result["burn_tx_count"] = total_burn_txs

            # Main pool data (backward compatible)
            result["lp_mint"] = main_pool["lp_mint"]
            result["lp_total_supply"] = main_pool["lp_supply"]
            result["lp_burned_amount"] = main_pool["burned_amount"]
            result["lp_burn_percent"] = main_pool["burn_percent"]
            result["lp_address"] = main_pool["pool_address"]
            result["lp_burned"] = total_burned > 0

            # Cache the result
            _duration = _time.time() - _start
            set_cached_lp_status(mint_address, result, _duration)

            return result

        except Exception as e:
            print(f"Error checking LP status: {e}")
            return result

    async def _get_initial_lp_supply(self, lp_mint: str, decimals: int) -> float:
        """Get the FIRST LP mint amount (original pool creation supply).
        This matches Loko_AI's 'Original LP' value."""
        
        # Check permanent cache first (initial supply never changes)
        cached = get_cached_initial_supply(lp_mint)
        if cached is not None:
            return cached

        try:
            # Get ALL transactions for this LP mint (need oldest first)
            all_sigs = []
            before = None
            for page in range(10):
                params = [lp_mint, {"limit": 1000}]
                if before:
                    params[1]["before"] = before
                sigs = await self._rpc_request("getSignaturesForAddress", params)
                if not sigs:
                    break
                all_sigs.extend(sigs)
                before = sigs[-1].get("signature")
                if len(sigs) < 1000:
                    break

            if not all_sigs:
                return 0.0

            # Find the FIRST (oldest) mintTo transaction
            # Iterate from oldest to newest
            for sig_info in reversed(all_sigs):
                sig = sig_info.get("signature")
                if not sig:
                    continue
                try:
                    tx = await self._rpc_request(
                        "getTransaction",
                        [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                    )
                    if not tx:
                        continue

                    message = tx.get("transaction", {}).get("message", {})
                    instructions = message.get("instructions", [])
                    inner = tx.get("meta", {}).get("innerInstructions", [])
                    all_ix = list(instructions)
                    for ig in inner:
                        all_ix.extend(ig.get("instructions", []))

                    for ix in all_ix:
                        parsed = ix.get("parsed", {})
                        if not isinstance(parsed, dict):
                            continue
                        ix_type = parsed.get("type", "")
                        info = parsed.get("info", {})

                        if ix_type in ["mintTo", "mintToChecked"]:
                            ix_mint = info.get("mint", "")
                            if ix_mint and ix_mint == lp_mint:
                                token_amount = info.get("tokenAmount", {})
                                if token_amount and token_amount.get("uiAmount"):
                                    amount = float(token_amount.get("uiAmount", 0) or 0)
                                else:
                                    raw = int(info.get("amount", 0))
                                    amount = raw / (10 ** decimals) if raw > 0 else 0
                                if amount > 0:
                                    set_cached_initial_supply(lp_mint, amount)
                                    return amount  # Return FIRST mint only

                except:
                    continue

            return 0.0

        except Exception as e:
            print(f"Error getting initial LP supply: {e}")
            return 0.0

    async def _get_total_lp_minted(self, lp_mint: str, decimals: int) -> float:
        """Get TOTAL LP ever minted (sum of ALL mintTo transactions).
        This is the true denominator for burn % calculation."""
        
        # Check cache
        from lp_cache import get_cached_initial_supply, set_cached_initial_supply
        cache_key = f"total_{lp_mint}"
        cached = get_cached_initial_supply(cache_key)
        if cached is not None:
            return cached

        try:
            all_sigs = []
            before = None
            for page in range(10):
                params = [lp_mint, {"limit": 1000}]
                if before:
                    params[1]["before"] = before
                sigs = await self._rpc_request("getSignaturesForAddress", params)
                if not sigs:
                    break
                all_sigs.extend(sigs)
                before = sigs[-1].get("signature")
                if len(sigs) < 1000:
                    break

            if not all_sigs:
                return 0.0

            total_minted = 0.0

            for sig_info in reversed(all_sigs):
                sig = sig_info.get("signature")
                if not sig:
                    continue
                try:
                    tx = await self._rpc_request(
                        "getTransaction",
                        [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                    )
                    if not tx:
                        continue

                    message = tx.get("transaction", {}).get("message", {})
                    instructions = message.get("instructions", [])
                    inner = tx.get("meta", {}).get("innerInstructions", [])
                    all_ix = list(instructions)
                    for ig in inner:
                        all_ix.extend(ig.get("instructions", []))

                    for ix in all_ix:
                        parsed = ix.get("parsed", {})
                        if not isinstance(parsed, dict):
                            continue
                        ix_type = parsed.get("type", "")
                        info = parsed.get("info", {})

                        if ix_type in ["mintTo", "mintToChecked"]:
                            ix_mint = info.get("mint", "")
                            if ix_mint and ix_mint == lp_mint:
                                token_amount = info.get("tokenAmount", {})
                                if token_amount and token_amount.get("uiAmount"):
                                    amount = float(token_amount.get("uiAmount", 0) or 0)
                                else:
                                    raw = int(info.get("amount", 0))
                                    amount = raw / (10 ** decimals) if raw > 0 else 0
                                if amount > 0:
                                    total_minted += amount
                except:
                    continue

            if total_minted > 0:
                set_cached_initial_supply(cache_key, total_minted)
            return total_minted

        except Exception as e:
            print(f"Error getting total LP minted: {e}")
            return 0.0

    async def _check_burn_checked(self, lp_mint: str, decimals: int) -> tuple:
        """Check for BurnChecked transactions that destroyed LP tokens.
        Returns (total_burned_amount, burn_tx_count)"""
        try:
            # Get transaction history for the LP mint
            sigs = await self._rpc_request(
                "getSignaturesForAddress",
                [lp_mint, {"limit": 50}]
            )

            if not sigs:
                return 0.0, 0

            total_burned = 0.0
            burn_tx_count = 0

            for sig_info in sigs:
                sig = sig_info.get("signature")
                if not sig:
                    continue

                try:
                    tx = await self._rpc_request(
                        "getTransaction",
                        [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                    )

                    if not tx:
                        continue

                    # Check all instructions for burn/burnChecked
                    message = tx.get("transaction", {}).get("message", {})
                    instructions = message.get("instructions", [])

                    # Also check inner instructions
                    inner = tx.get("meta", {}).get("innerInstructions", [])
                    all_instructions = list(instructions)
                    for inner_group in inner:
                        all_instructions.extend(inner_group.get("instructions", []))

                    for ix in all_instructions:
                        parsed = ix.get("parsed", {})
                        if not isinstance(parsed, dict):
                            continue

                        ix_type = parsed.get("type", "")
                        info = parsed.get("info", {})

                        if ix_type in ["burn", "burnChecked"]:
                            # Verify it's for our LP mint
                            ix_mint = info.get("mint", "")
                            if ix_mint == lp_mint or ix_type == "burn":
                                token_amount = info.get("tokenAmount", {})
                                if token_amount:
                                    amount = float(token_amount.get("uiAmount", 0) or 0)
                                else:
                                    # Raw amount for 'burn' type
                                    raw_amount = int(info.get("amount", 0))
                                    amount = raw_amount / (10 ** decimals) if raw_amount > 0 else 0

                                if amount > 0:
                                    total_burned += amount
                                    burn_tx_count += 1

                except Exception:
                    continue

            return total_burned, burn_tx_count

        except Exception as e:
            print(f"Error checking BurnChecked: {e}")
            return 0.0, 0

    async def _identify_pool_pair(self, pool_address: str, known_mint: str, pool_raw_data: bytes = None, lp_mint: str = None) -> str:
        """Identify what token pair a pool is for by reading pool binary data"""
        KNOWN_TOKENS = {
            "So11111111111111111111111111111111111111112": "WXNT",
            "CAJeVEoSm1QQZccnCqYu9cnNF7TTD2fcUA3E5HQoxRvR": "USDC.X",
        }

        # Known program IDs to skip (not token mints)
        SKIP_ADDRESSES = {
            PROGRAM_IDS["token_program"],
            PROGRAM_IDS["token_2022_program"],
            PROGRAM_IDS["associated_token_program"],
            PROGRAM_IDS["metadata_program"],
            "sEsYH97wqmfnkzHedjNcw3zyJdPvUmsa9AixhS4b4fN",  # AMM program
            "11111111111111111111111111111111",  # System program
            known_mint,  # Skip the token we're searching for
        }
        if lp_mint:
            SKIP_ADDRESSES.add(lp_mint)

        try:
            # Method 1: Extract from binary pool data
            if pool_raw_data and len(pool_raw_data) >= 200:
                # Scan ALL 32-byte aligned positions in the pool data for token mints
                for offset in [200, 232, 264, 168, 296, 72, 104, 136, 328]:
                    if offset + 32 > len(pool_raw_data):
                        continue
                    mint_bytes = pool_raw_data[offset:offset + 32]
                    
                    # Skip null bytes
                    if all(b == 0 for b in mint_bytes):
                        continue
                    
                    try:
                        candidate = base58.b58encode(mint_bytes).decode()
                    except:
                        continue
                    
                    # Skip known program IDs and known addresses
                    if candidate in SKIP_ADDRESSES:
                        continue
                    
                    # Quick check: is this in our known tokens list?
                    if candidate in KNOWN_TOKENS:
                        return KNOWN_TOKENS[candidate]
                    
                    # Verify it's actually a token mint on-chain
                    try:
                        check = await self._rpc_request(
                            "getAccountInfo",
                            [candidate, {"encoding": "jsonParsed"}]
                        )
                        if check and check.get("value"):
                            owner = check["value"].get("owner", "")
                            data = check["value"].get("data", {})
                            # Must be owned by token program and be a mint type
                            if owner in [PROGRAM_IDS["token_program"], PROGRAM_IDS["token_2022_program"]]:
                                if isinstance(data, dict) and data.get("parsed", {}).get("type") == "mint":
                                    # It's a token mint but not the one we know — this is the pair
                                    metadata = await self.get_token_metadata(candidate)
                                    if metadata and metadata.symbol:
                                        return metadata.symbol
                                    return candidate[:6] + "..."
                    except:
                        continue

            # Method 2: Fallback - query pool's token accounts
            try:
                pool_tokens = await self._rpc_request(
                    "getTokenAccountsByOwner",
                    [pool_address, {"programId": PROGRAM_IDS["token_program"]}, {"encoding": "jsonParsed"}]
                )
                if pool_tokens and pool_tokens.get("value"):
                    for tok in pool_tokens["value"]:
                        info = tok.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                        mint = info.get("mint", "")
                        if mint and mint != known_mint and mint not in SKIP_ADDRESSES:
                            if mint in KNOWN_TOKENS:
                                return KNOWN_TOKENS[mint]
                            metadata = await self.get_token_metadata(mint)
                            if metadata and metadata.symbol:
                                return metadata.symbol
                            return mint[:6] + "..."
            except:
                pass

            return "Unknown"

        except:
            return "Unknown"

    async def get_24h_volume(self, token_mint: str) -> float:
        """Get 24h trading volume in XNT by counting swap transactions"""
        import time
        WXNT_MINT = "So11111111111111111111111111111111111111112"
        AMM_AUTHORITY = "9Dpjw2pB5kXJr6ZTHiqzEMfJPic3om9jgNacnwpLCoaU"

        try:
            now = int(time.time())
            cutoff = now - 86400  # 24h ago
            total_volume = 0.0

            before = None
            max_pages = 5

            for page in range(max_pages):
                params = [token_mint, {"limit": 200}]
                if before:
                    params[1]["before"] = before

                sigs = await self._rpc_request("getSignaturesForAddress", params)
                if not sigs:
                    break

                for sig_info in sigs:
                    block_time = sig_info.get("blockTime", 0)
                    if block_time and block_time < cutoff:
                        # Past 24h window, stop
                        return total_volume

                    sig = sig_info.get("signature")
                    if not sig:
                        continue

                    try:
                        tx = await self._rpc_request(
                            "getTransaction",
                            [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                        )
                        if not tx:
                            continue

                        meta = tx.get("meta", {})
                        pre_balances = meta.get("preTokenBalances", [])
                        post_balances = meta.get("postTokenBalances", [])

                        # Look for WXNT balance changes in AMM authority accounts
                        for pre_bal in pre_balances:
                            if pre_bal.get("owner") == AMM_AUTHORITY and pre_bal.get("mint") == WXNT_MINT:
                                pre_amount = float(pre_bal.get("uiTokenAmount", {}).get("uiAmount", 0) or 0)
                                # Find matching post balance
                                for post_bal in post_balances:
                                    if (post_bal.get("accountIndex") == pre_bal.get("accountIndex") and
                                        post_bal.get("mint") == WXNT_MINT):
                                        post_amount = float(post_bal.get("uiTokenAmount", {}).get("uiAmount", 0) or 0)
                                        diff = abs(post_amount - pre_amount)
                                        if diff > 0:
                                            total_volume += diff
                    except:
                        continue

                oldest_time = sigs[-1].get("blockTime", 0)
                if oldest_time and oldest_time < cutoff:
                    break

                before = sigs[-1].get("signature")
                if len(sigs) < 200:
                    break

            return total_volume

        except Exception as e:
            print(f"Error getting 24h volume: {e}")
            return 0.0

    async def get_holder_count(self, mint_address: str) -> int:
        """Get holder count (returns 20 as max from RPC)"""
        try:
            holders = await self.get_token_largest_accounts(mint_address, 20)
            return len(holders) if holders else 0
        except Exception:
            return 0
    
    async def get_token_metadata(self, mint_address: str) -> Optional[TokenMetadata]:
        """
        Try to get token metadata using multiple methods:
        1. Check for Token-2022 embedded metadata (fastest for Token-2022 tokens)
        2. Query Metaplex program accounts by mint filter (reliable for standard tokens)
        3. Derive Metaplex PDA and fetch directly (fallback)
        """
        try:
            # Method 1: Check if token uses Token-2022 with embedded metadata
            try:
                account_info = await self._rpc_request(
                    "getAccountInfo",
                    [mint_address, {"encoding": "jsonParsed"}]
                )
                
                if account_info and account_info.get("value"):
                    data = account_info["value"].get("data", {})
                    if isinstance(data, dict):
                        parsed = data.get("parsed", {})
                        info = parsed.get("info", {})
                        
                        extensions = info.get("extensions", [])
                        for ext in extensions:
                            ext_type = ext.get("extension", "")
                            if ext_type == "tokenMetadata":
                                state = ext.get("state", {})
                                name = state.get("name", "")
                                symbol = state.get("symbol", "")
                                uri = state.get("uri", "")
                                
                                if name or symbol:
                                    return TokenMetadata(
                                        name=name,
                                        symbol=symbol,
                                        uri=uri,
                                        seller_fee_basis_points=0,
                                        creators=[]
                                    )
            except Exception:
                pass
            
            # Method 2: Try using getProgramAccounts with memcmp filter
            try:
                METADATA_PROGRAM = PROGRAM_IDS["metadata_program"]
                
                result = await self._rpc_request(
                    "getProgramAccounts",
                    [
                        METADATA_PROGRAM,
                        {
                            "encoding": "base64",
                            "filters": [
                                {"memcmp": {"offset": 33, "bytes": mint_address}}
                            ]
                        }
                    ]
                )
                
                if result and len(result) > 0:
                    account_data = result[0].get("account", {}).get("data", [])
                    if account_data and len(account_data) > 0:
                        raw_data = base64.b64decode(account_data[0])
                        parsed = self._parse_metadata(raw_data)
                        if parsed:
                            return parsed
            except Exception:
                pass
            
            return None
        except Exception:
            return None
    
    def _parse_metadata(self, raw_data: bytes) -> Optional[TokenMetadata]:
        """Parse Metaplex metadata account data"""
        try:
            if len(raw_data) < 70:
                return None
            
            offset = 1 + 32 + 32
            
            if offset + 4 > len(raw_data):
                return None
            name_len = struct.unpack("<I", raw_data[offset:offset+4])[0]
            offset += 4
            
            name_len = min(name_len, 32)
            if offset + 32 > len(raw_data):
                return None
            name_bytes = raw_data[offset:offset+32]
            name = name_bytes[:name_len].decode('utf-8', errors='ignore').rstrip('\x00').strip()
            offset += 32
            
            if offset + 4 > len(raw_data):
                return TokenMetadata(name=name, symbol="", uri="", seller_fee_basis_points=0, creators=[])
            symbol_len = struct.unpack("<I", raw_data[offset:offset+4])[0]
            offset += 4
            
            symbol_len = min(symbol_len, 10)
            if offset + 10 > len(raw_data):
                return TokenMetadata(name=name, symbol="", uri="", seller_fee_basis_points=0, creators=[])
            symbol_bytes = raw_data[offset:offset+10]
            symbol = symbol_bytes[:symbol_len].decode('utf-8', errors='ignore').rstrip('\x00').strip()
            offset += 10
            
            uri = ""
            if offset + 4 <= len(raw_data):
                uri_len = struct.unpack("<I", raw_data[offset:offset+4])[0]
                offset += 4
                uri_len = min(uri_len, 200)
                if offset + uri_len <= len(raw_data):
                    uri_bytes = raw_data[offset:offset+min(200, len(raw_data)-offset)]
                    uri = uri_bytes[:uri_len].decode('utf-8', errors='ignore').rstrip('\x00').strip()
            
            if name or symbol:
                return TokenMetadata(
                    name=name,
                    symbol=symbol,
                    uri=uri,
                    seller_fee_basis_points=0,
                    creators=[]
                )
            
            return None
        except Exception:
            return None



    async def get_accurate_holder_count(self, mint_address: str) -> int:
        """Get accurate holder count using getProgramAccounts"""
        try:
            # Query all token accounts for this mint with balance > 0
            result = await self._rpc_request(
                "getProgramAccounts",
                [
                    PROGRAM_IDS["token_program"],
                    {
                        "encoding": "jsonParsed",
                        "filters": [
                            {"dataSize": 165},
                            {"memcmp": {"offset": 0, "bytes": mint_address}}
                        ]
                    }
                ]
            )
            
            if not result:
                result = await self._rpc_request(
                    "getProgramAccounts",
                    [
                        PROGRAM_IDS["token_2022_program"],
                        {
                            "encoding": "jsonParsed",
                            "filters": [
                                {"memcmp": {"offset": 0, "bytes": mint_address}}
                            ]
                        }
                    ]
                )
            
            if result:
                count = 0
                for acc in result:
                    try:
                        balance = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {}).get("tokenAmount", {}).get("uiAmount", 0)
                        if balance and float(balance) > 0:
                            count += 1
                    except:
                        pass
                return count
            return 0
        except Exception as e:
            print(f"Error getting holder count: {e}")
            return 0


    async def get_price_change_24h(self, token_mint: str, current_price: float) -> Optional[float]:
        """Get 24h price change by looking at transactions from ~24h ago"""
        import time
        
        if current_price <= 0:
            return None
            
        WXNT_MINT = "So11111111111111111111111111111111111111112"
        AMM_AUTHORITY = "9Dpjw2pB5kXJr6ZTHiqzEMfJPic3om9jgNacnwpLCoaU"
        
        try:
            now = int(time.time())
            target_time = now - 86400  # 24 hours ago
            
            before = None
            max_pages = 10
            
            for page in range(max_pages):
                params = [token_mint, {"limit": 1000}]
                if before:
                    params[1]["before"] = before
                
                sigs = await self._rpc_request("getSignaturesForAddress", params)
                
                if not sigs:
                    break
                
                oldest_time = sigs[-1].get("blockTime", 0)
                before = sigs[-1].get("signature")
                
                if oldest_time and oldest_time < target_time:
                    # Find transactions closest to 24h ago (2 hour window)
                    candidates = []
                    for sig_info in sigs:
                        block_time = sig_info.get("blockTime", 0)
                        if block_time and abs(block_time - target_time) < 7200:  # 2 hour window
                            candidates.append(sig_info)
                    
                    # Sort by closest to target time
                    candidates.sort(key=lambda s: abs(s.get("blockTime", 0) - target_time))
                    
                    # Try up to 5 candidates to find a valid price
                    for sig_info in candidates[:5]:
                        sig = sig_info.get("signature")
                        if not sig:
                            continue
                        
                        tx = await self._rpc_request(
                            "getTransaction",
                            [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                        )
                        
                        if not tx:
                            continue
                        
                        meta = tx.get("meta", {})
                        post_balances = meta.get("postTokenBalances", [])
                        
                        token_amount = None
                        wxnt_amount = None
                        
                        # Collect all AMM authority balances
                        token_balances = []
                        wxnt_balances = []
                        
                        for bal in post_balances:
                            mint = bal.get("mint", "")
                            owner = bal.get("owner", "")
                            
                            if owner == AMM_AUTHORITY:
                                amount = float(bal.get("uiTokenAmount", {}).get("uiAmount", 0) or 0)
                                if mint == token_mint and amount > 0:
                                    token_balances.append(amount)
                                elif mint == WXNT_MINT and amount > 0:
                                    wxnt_balances.append(amount)
                        
                        # Use largest token balance and smallest WXNT balance
                        # The direct token/WXNT pool has the most tokens and least WXNT
                        if token_balances and wxnt_balances:
                            token_amount = max(token_balances)
                            wxnt_amount = min(wxnt_balances)
                        
                        if token_amount and wxnt_amount and token_amount > 0:
                            old_price = wxnt_amount / token_amount
                            
                            # Sanity check: old price should be within 100x of current
                            # (skip outliers from pool creation/removal)
                            ratio = current_price / old_price if old_price > 0 else 0
                            if 0.01 < ratio < 100:
                                change = ((current_price - old_price) / old_price) * 100
                                return change
                    break
                
                if len(sigs) < 1000:
                    break
            
            return None
            
        except Exception as e:
            return None


    async def get_xnt_usd_price(self):
        """Get XNT price in USD using USDC/XNT pool"""
        USDC_MINT = "B69chRzqzDCmdB5WYB8NRu5Yv5ZA95ABiZcdzCgGm9Tq"
        try:
            lp_info = await self.get_lp_info(USDC_MINT, 6)
            if lp_info and lp_info.price_in_wxnt > 0:
                return 1 / lp_info.price_in_wxnt
        except:
            pass
        return 0


    async def get_lp_burn_tx(self, lp_mint: str) -> Optional[Dict]:
        """Get the LP burn transaction details"""
        INCINERATOR = "1nc1nerator11111111111111111111111111111111"
        
        try:
            # Get token accounts owned by incinerator for this LP mint
            result = await self._rpc_request(
                "getTokenAccountsByOwner",
                [INCINERATOR, {"mint": lp_mint}, {"encoding": "jsonParsed"}]
            )
            
            if not result or not result.get("value"):
                return None
            
            burn_account = result["value"][0].get("pubkey")
            if not burn_account:
                return None
            
            # Get transaction history for the burn account
            sigs = await self._rpc_request(
                "getSignaturesForAddress",
                [burn_account, {"limit": 1}]
            )
            
            if not sigs:
                return None
            
            tx_sig = sigs[0].get("signature")
            block_time = sigs[0].get("blockTime")
            
            # Get transaction details
            tx = await self._rpc_request(
                "getTransaction",
                [tx_sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
            )
            
            if not tx:
                return None
            
            # Find the transfer instruction
            message = tx.get("transaction", {}).get("message", {})
            instructions = message.get("instructions", [])
            
            burner = None
            amount = 0
            
            for ix in instructions:
                parsed = ix.get("parsed", {})
                if isinstance(parsed, dict):
                    ix_type = parsed.get("type", "")
                    if ix_type in ["transfer", "transferChecked"]:
                        info = parsed.get("info", {})
                        if info.get("mint") == lp_mint or ix_type == "transfer":
                            burner = info.get("authority", info.get("source", ""))
                            token_amount = info.get("tokenAmount", {})
                            amount = float(token_amount.get("uiAmount", 0) or info.get("amount", 0))
            
            from datetime import datetime
            burn_time = datetime.fromtimestamp(block_time).strftime("%Y-%m-%d %H:%M") if block_time else "Unknown"
            
            return {
                "tx_sig": tx_sig,
                "burner": burner,
                "amount": amount,
                "burn_time": burn_time,
                "burn_account": burn_account
            }
            
        except Exception as e:
            return None


class HolderAnalyzer:
    """Analyze token holder distribution"""
    
    def __init__(self, rpc: X1RPC):
        self.rpc = rpc
    
    async def analyze_holders(self, mint_address: str, total_supply: int, decimals: int) -> Dict[str, Any]:
        """Analyze holder concentration"""
        result = {
            "top_holders": [],
            "top_holder_percent": 0.0,
            "top_10_percent": 0.0,
            "holder_count": 0,
        }
        
        largest = await self.rpc.get_token_largest_accounts(mint_address, 20)
        
        if not largest or total_supply == 0:
            return result
        
        total_in_top_10 = 0
        holders = []
        
        for i, holder in enumerate(largest):
            amount = int(holder.get("amount", "0"))
            ui_amount = holder.get("uiAmount", 0)
            address = holder.get("address", "")
            
            percent = (amount / total_supply * 100) if total_supply > 0 else 0
            
            holders.append({
                "rank": i + 1,
                "address": address,
                "amount": ui_amount,
                "percent": percent,
            })
            
            if i < 10:
                total_in_top_10 += amount
            
            if i == 0:
                result["top_holder_percent"] = percent
        
        result["top_holders"] = holders
        result["top_10_percent"] = (total_in_top_10 / total_supply * 100) if total_supply > 0 else 0
        result["holder_count"] = len(holders)
        
        return result


async def test_connection():
    """Test X1 RPC connection"""
    rpc = X1RPC()
    
    print(f"Testing connection to {rpc.rpc_url}...")
    
    slot = await rpc._rpc_request("getSlot")
    print(f"Current slot: {slot}")


if __name__ == "__main__":
    asyncio.run(test_connection())
