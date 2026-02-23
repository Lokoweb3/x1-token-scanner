"""
X1 Token Security Analyzer - OPTIMIZED FOR SPEED
Uses parallel RPC calls for fast analysis
"""

import asyncio
import sqlite3
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum

from blockchain import X1RPC, HolderAnalyzer, TokenInfo, LPInfo
from config import X1_CONFIG, RISK_THRESHOLDS


def load_token_list():
    """Load token list from JSON file"""
    try:
        with open('token_list.json', 'r') as f:
            return json.load(f)
    except:
        return {}


def get_indexed_holder_count(mint: str) -> int:
    """Get holder count from indexer database"""
    try:
        conn = sqlite3.connect('token_holders.db')
        c = conn.cursor()
        c.execute("SELECT holder_count FROM tokens WHERE mint = ?", (mint,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else 0
    except:
        return 0


class RiskLevel(Enum):
    SAFE = "SAFE"
    MEDIUM = "MEDIUM RISK"
    HIGH = "HIGH RISK"
    CRITICAL = "CRITICAL RISK"


@dataclass
class SecurityReport:
    """Complete security report for an X1 token"""
    mint_address: str
    name: Optional[str]
    symbol: Optional[str]
    decimals: int
    total_supply: float
    raw_supply: int
    
    mint_authority: Optional[str]
    mint_authority_enabled: bool
    freeze_authority: Optional[str]
    freeze_authority_enabled: bool
    
    top_holder_percent: float
    top_10_percent: float
    top_holders: List[Dict]
    holder_count: int
    
    lp_found: bool
    lp_burned: bool
    lp_burn_percent: float
    lp_address: Optional[str]
    lp_burn_tx: Optional[Dict]
    lp_total_supply: float
    lp_burned_amount: float
    lp_pools: List[Dict]
    lp_total_burn_percent: float
    lp_burn_tx_count: int
    
    price_xn: float
    price_usd: float
    xnt_usd_rate: float
    price_change_24h: Optional[float]
    liquidity_xn: float
    liquidity_usd: float
    token_reserve: float
    wxnt_reserve: float
    volume_24h: float
    volume_24h_usd: float
    mcap_usd: float
    
    age_str: str
    
    risk_level: RiskLevel
    risk_score: int
    warnings: List[str]
    positives: List[str]
    
    def to_telegram_message(self) -> str:
        """Format report for Telegram — matches Loko_AI audit format"""
        token_list = load_token_list()
        
        name = self.name or token_list.get(self.mint_address, {}).get("name") or "Unknown"
        symbol = self.symbol or token_list.get(self.mint_address, {}).get("symbol") or "???"
        
        # Risk emoji and label
        risk_data = {
            RiskLevel.SAFE: ("🟢", "SAFE"),
            RiskLevel.MEDIUM: ("🟡", "MEDIUM"),
            RiskLevel.HIGH: ("🔴", "HIGH"),
            RiskLevel.CRITICAL: ("☠️", "CRITICAL"),
        }.get(self.risk_level, ("⚪", "UNKNOWN"))
        risk_emoji, risk_label = risk_data
        
        # Price — USD primary, XNT secondary
        if self.price_usd > 0:
            price_str = self._format_usd(self.price_usd)
        elif self.price_xn > 0:
            price_str = f"{self._format_price_raw(self.price_xn)} XNT"
        else:
            price_str = "N/A"
        
        # Market cap in USD
        mcap_str = self._format_usd_short(self.mcap_usd) if self.mcap_usd > 0 else "N/A"
        
        # Liquidity in USD
        liq_str = self._format_usd_short(self.liquidity_usd) if self.liquidity_usd > 0 else "N/A"
        
        # Volume in USD
        vol_str = self._format_usd_short(self.volume_24h_usd) if self.volume_24h_usd > 0 else "$0.00"
        
        # Supply
        supply_str = self._format_number(self.total_supply)
        
        # Holder count
        holder_count = get_indexed_holder_count(self.mint_address)
        if holder_count == 0:
            holder_count = self.holder_count
        holder_count_str = f"{holder_count:,}"
        
        # Holder bar
        holder_bar = self._make_holder_bar(self.top_holder_percent)
        
        # Security
        mint_icon = "✅ REVOKED" if not self.mint_authority_enabled else "❌ ACTIVE"
        freeze_icon = "✅ REVOKED" if not self.freeze_authority_enabled else "❌ ACTIVE"
        
        # LP Safety %
        lp_safety_pct = self.lp_total_burn_percent
        if lp_safety_pct >= 90:
            lp_safety_str = f"🟢 {lp_safety_pct:.1f}%"
        elif lp_safety_pct >= 50:
            lp_safety_str = f"🟡 {lp_safety_pct:.1f}%"
        elif lp_safety_pct > 0:
            lp_safety_str = f"🔴 {lp_safety_pct:.1f}%"
        else:
            lp_safety_str = "🔴 0%"
        
        # Price change
        if self.price_change_24h is not None:
            if self.price_change_24h >= 0:
                price_change_str = f" (🟢 +{self.price_change_24h:.1f}%)"
            else:
                price_change_str = f" (🔴 {self.price_change_24h:.1f}%)"
        else:
            price_change_str = ""
        
        # Top holders table
        holder_table = self._format_holder_table()
        
        # LP burn section
        lp_str = self._format_lp_status(symbol)
        
        # Pools summary
        pools = self.lp_pools or []
        pool_count = len(pools)
        
        # Verdict
        if self.risk_level == RiskLevel.SAFE:
            verdict = f"✅ *LOW RISK* {risk_emoji}"
        elif self.risk_level == RiskLevel.MEDIUM:
            verdict = f"⚠️ *MEDIUM RISK* {risk_emoji}"
        elif self.risk_level == RiskLevel.HIGH:
            verdict = f"🚨 *HIGH RISK* {risk_emoji}"
        else:
            verdict = f"☠️ *CRITICAL RISK* {risk_emoji}"
        
        # Build message
        msg = f"""🪙 *{name}* (${symbol})
━━━━━━━━━━━━━━━━━━━━━━

📄 `{self.mint_address}`

💰 *Metrics*
├ Price: {price_str}{price_change_str}
├ MCap: {mcap_str}
├ Liquidity: {liq_str}
├ 24h Vol: {vol_str}
└ Supply: {supply_str}

🔐 *Security*
├ Mint: {mint_icon}
├ Freeze: {freeze_icon}
├ LP Safety: {lp_safety_str}
└ Risk: {self.risk_score}/100 {risk_emoji} {risk_label}

🔥 *LP Burn Status*
{lp_str}

👥 *Holders* ({holder_count_str})
├ Top: {self.top_holder_percent:.1f}% {holder_bar}
├ Top 10: {self.top_10_percent:.1f}%
{holder_table}

🏊 *Pools* ({pool_count} Found)
{self._format_pool_summary(symbol)}

🎯 *Verdict:* {verdict}
"""
        
        # The Good
        if self.positives:
            msg += "*The Good:*\n"
            for p in self.positives[:4]:
                msg += f"  • ✅ {p}\n"
        
        # The Concerns
        if self.warnings:
            msg += "*Concerns:*\n"
            for w in self.warnings[:4]:
                msg += f"  • ⚠️ {w}\n"
        
        # Risk guide
        msg += f"\n_Risk: 🟢 0-24 LOW | 🟡 25-49 MEDIUM | 🔴 50-74 HIGH | ☠️ 75+ CRITICAL_"
        
        return msg

    def _format_usd(self, amount: float) -> str:
        """Format USD price with appropriate decimals"""
        if amount >= 1:
            return f"${amount:,.2f}"
        elif amount >= 0.01:
            return f"${amount:.4f}"
        elif amount >= 0.0001:
            return f"${amount:.6f}"
        else:
            # Count leading zeros after decimal
            s = f"{amount:.12f}"
            return f"${amount:.8f}"

    def _format_usd_short(self, amount: float) -> str:
        """Format USD with K/M/B suffix"""
        if amount >= 1_000_000_000:
            return f"${amount/1_000_000_000:.2f}B"
        elif amount >= 1_000_000:
            return f"${amount/1_000_000:.2f}M"
        elif amount >= 1_000:
            return f"${amount/1_000:.2f}K"
        elif amount >= 1:
            return f"${amount:.2f}"
        else:
            return f"${amount:.2f}"

    def _format_price_raw(self, price: float) -> str:
        """Format raw price number"""
        if price >= 1:
            return f"{price:,.2f}"
        elif price >= 0.0001:
            return f"{price:.4f}"
        else:
            return f"{price:.8f}"

    def _format_holder_table(self) -> str:
        """Format top holders with addresses, amounts, and percentages"""
        if not self.top_holders:
            return ""
        
        lines = []
        show = min(5, len(self.top_holders))
        for i, h in enumerate(self.top_holders[:show]):
            addr = h.get("address", "")
            addr_short = f"`{addr[:6]}...{addr[-6:]}`" if len(addr) > 14 else f"`{addr}`"
            pct = h.get("percent", 0)
            amount = h.get("amount", 0)
            rank = h.get("rank", 0)
            
            connector = "└" if i == show - 1 else "├"
            
            amount_str = self._format_number(amount) if amount else "0"
            lines.append(f"{connector} #{rank} {addr_short} — {amount_str} ({pct:.1f}%)")
        
        return "\n".join(lines)

    def _format_lp_status(self, symbol: str) -> str:
        """Format LP burn status with burned totals"""
        if not self.lp_found:
            return "❓ No LP found"
        
        pools = self.lp_pools or []
        total_burned = sum(p.get("burned_amount", 0) for p in pools)
        total_burn_txs = sum(p.get("burn_tx_count", 0) for p in pools)
        burn_pct = self.lp_total_burn_percent
        
        if total_burned == 0:
            return "🔓 Not Burned — LP unlocked, dev can pull liquidity"
        
        burned_str = self._format_number(total_burned)
        
        lines = []
        lines.append(f"├ Burned: {burned_str} LP ({total_burn_txs} tx{'s' if total_burn_txs > 1 else ''})")
        lines.append(f"├ LP Safety: {'🟢' if burn_pct >= 90 else '🟡' if burn_pct >= 50 else '🔴'} {burn_pct:.1f}%")
        
        # Per-pool breakdown
        for pool in pools:
            pair = pool.get("pair_label", "Unknown")
            burned = pool.get("burned_amount", 0)
            pool_txs = pool.get("burn_tx_count", 0)
            method = pool.get("burn_method", "")
            lp_supply = pool.get("lp_original_supply", pool.get("lp_supply", 0))
            
            supply_str = self._format_number(lp_supply)
            
            if burned > 0:
                burned_pool_str = self._format_number(burned)
                method_str = f" [{method}]" if method else ""
                lines.append(f"├ {pair}/{symbol}: {burned_pool_str} burned ({pool_txs} tx){method_str} ✅")
            else:
                lines.append(f"├ {pair}/{symbol}: {supply_str} LP — not burned")
        
        # Burn tx link
        if self.lp_burn_tx:
            tx_sig = self.lp_burn_tx.get("tx_sig", "")
            burn_time = self.lp_burn_tx.get("burn_time", "")
            if tx_sig:
                lines.append(f"└ 📝 [View Burn TX](https://explorer.x1.xyz/tx/{tx_sig})")
            else:
                lines[-1] = lines[-1].replace("├", "└", 1) if lines else ""
        else:
            if lines:
                lines[-1] = lines[-1].replace("├", "└", 1)
        
        return "\n".join(lines)

    def _format_pool_summary(self, symbol: str) -> str:
        """Format pool summary like Loko_AI"""
        pools = self.lp_pools or []
        if not pools:
            return "None found"
        
        # Group by pair label
        from collections import Counter
        pair_counts = Counter()
        pair_burns = {}
        for p in pools:
            pair = p.get("pair_label", "Unknown")
            key = f"{pair}/{symbol}"
            pair_counts[key] += 1
            if p.get("burned_amount", 0) > 0:
                pair_burns[key] = True
        
        lines = []
        items = list(pair_counts.items())
        for i, (pair, count) in enumerate(items):
            connector = "└" if i == len(items) - 1 else "├"
            burn_note = " (with burns)" if pair in pair_burns else ""
            if count > 1:
                lines.append(f"{connector} {count}x {pair}{burn_note}")
            else:
                lines.append(f"{connector} {pair}{burn_note}")
        
        return "\n".join(lines)

    def _make_holder_bar(self, percent: float) -> str:
        filled = max(1, round(percent / 10)) if percent > 0 else 0
        filled = min(filled, 10)
        empty = 10 - filled
        if percent > 50:
            bar_char = "🟥"
        elif percent > 20:
            bar_char = "🟨"
        else:
            bar_char = "🟩"
        return bar_char * filled + "⬜" * empty
    
    def _format_number(self, num: float) -> str:
        if num >= 1_000_000_000_000:
            return f"{num/1_000_000_000_000:.2f}T"
        elif num >= 1_000_000_000:
            return f"{num/1_000_000_000:.2f}B"
        elif num >= 1_000_000:
            return f"{num/1_000_000:.2f}M"
        elif num >= 1_000:
            return f"{num/1_000:.2f}K"
        elif num >= 1:
            return f"{num:.2f}"
        elif num > 0:
            return f"{num:.4f}"
        return "0"


class TokenAnalyzer:
    """Main analyzer for X1 tokens - OPTIMIZED"""
    
    def __init__(self, rpc_url: str = None):
        self.rpc = X1RPC(rpc_url)
        self.holder_analyzer = HolderAnalyzer(self.rpc)
        self.token_list = load_token_list()
    
    async def analyze(self, mint_address: str) -> SecurityReport:
        """Perform FAST security analysis using parallel calls"""
        
        # Validate address
        if not self.rpc.is_valid_address(mint_address):
            raise ValueError("Invalid mint address format")
        
        # Check if it's a token
        if not await self.rpc.is_token_account(mint_address):
            raise ValueError("Address is not a valid SPL token mint")
        
        # Get token info first (needed for holder analysis)
        token_info = await self.rpc.get_token_info(mint_address)
        if not token_info:
            raise ValueError("Could not fetch token information")
        
        # Run these in PARALLEL for speed
        holder_task = self.holder_analyzer.analyze_holders(
            mint_address,
            token_info.supply,
            token_info.decimals
        )
        age_task = self.rpc.get_token_age(mint_address)
        lp_task = self.rpc.get_lp_info(mint_address, token_info.decimals)
        holder_count_task = self.rpc.get_accurate_holder_count(mint_address)
        
        # Wait for all parallel tasks
        holder_data, age_str, lp_info, accurate_count = await asyncio.gather(
            holder_task, age_task, lp_task, holder_count_task
        )
        
        # Get price change (after we have lp_info for current price)
        current_price = lp_info.price_in_wxnt if lp_info else 0
        price_change_24h = await self.rpc.get_price_change_24h(mint_address, current_price) if current_price > 0 else None
        
        # Get XNT/USD price
        xnt_usd_rate = await self.rpc.get_xnt_usd_price()
        price_usd = current_price * xnt_usd_rate if current_price > 0 and xnt_usd_rate > 0 else 0
        
        # Calculate USD values
        liquidity_xn = lp_info.liquidity_wxnt if lp_info else 0
        liquidity_usd = liquidity_xn * xnt_usd_rate if xnt_usd_rate > 0 else 0
        
        total_supply = token_info.supply / (10 ** token_info.decimals)
        mcap_usd = price_usd * total_supply if price_usd > 0 else 0
        
        # Check LP burn status (ALL pools)
        lp_status = await self.rpc.check_lp_status(mint_address)
        
        # Get burn tx details if LP is burned
        lp_burn_tx = None
        if lp_status.get("lp_burned") and lp_status.get("lp_mint"):
            lp_burn_tx = await self.rpc.get_lp_burn_tx(lp_status["lp_mint"])
        
        # Get 24h volume
        volume_24h = await self.rpc.get_24h_volume(mint_address)
        volume_24h_usd = volume_24h * xnt_usd_rate if xnt_usd_rate > 0 else 0
        
        if accurate_count > 0:
            holder_data["holder_count"] = accurate_count
        
        # Try to get metadata
        metadata = await self.rpc.get_token_metadata(mint_address)
        
        token_name = (metadata.name if metadata and metadata.name else None) or self.token_list.get(mint_address, {}).get("name")
        token_symbol = (metadata.symbol if metadata and metadata.symbol else None) or self.token_list.get(mint_address, {}).get("symbol")
        
        if not age_str:
            age_str = "Unknown"
        
        # ── Risk Scoring (matches Loko_AI methodology) ──────────────
        warnings = []
        positives = []
        risk_score = 0
        
        # Mint authority: +25 if active
        if token_info.mint_authority:
            risk_score += 25
            warnings.append("Mint authority active — supply can increase")
        else:
            positives.append("Mint authority revoked")
        
        # Freeze authority: +25 if active
        if token_info.freeze_authority:
            risk_score += 25
            warnings.append("Freeze authority active — tokens can be frozen")
        else:
            positives.append("Freeze authority revoked")
        
        # Holder concentration
        top_holder_pct = holder_data.get("top_holder_percent", 0)
        top_10_pct = holder_data.get("top_10_percent", 0)
        
        if top_holder_pct > 50:
            risk_score += 20
            warnings.append(f"Top holder owns {top_holder_pct:.1f}% (very high)")
        elif top_holder_pct > 20:
            risk_score += 10
            warnings.append(f"Top holder owns {top_holder_pct:.1f}% (moderate)")
        elif top_holder_pct > 10:
            risk_score += 5
            warnings.append(f"Top holder at {top_holder_pct:.1f}%")
        
        if top_10_pct > 80:
            risk_score += 5
            warnings.append(f"Top 10 hold {top_10_pct:.1f}%")
        
        # LP Burn risk — Loko_AI style
        lp_burn_pct = lp_status.get("total_burn_percent", 0)
        lp_found = lp_status.get("lp_found", False) or lp_info is not None
        
        if lp_found:
            if lp_burn_pct >= 90:
                positives.append(f"LP burns detected ({lp_burn_pct:.1f}%)")
            elif lp_burn_pct >= 50:
                risk_score += 5
                positives.append(f"Some LP burns ({lp_burn_pct:.1f}%)")
                warnings.append(f"LP Safety {lp_burn_pct:.1f}% (below 90%)")
            elif lp_burn_pct > 0:
                risk_score += 10
                warnings.append(f"LP Safety only {lp_burn_pct:.1f}% (below 50%)")
            else:
                risk_score += 15
                warnings.append("LP not burned — dev can pull liquidity")
        else:
            risk_score += 15
            warnings.append("No LP found")
        
        # Low liquidity
        if liquidity_usd > 0 and liquidity_usd < 5000:
            risk_score += 5
            warnings.append(f"Low liquidity ({self._format_usd_static(liquidity_usd)})")
        elif liquidity_usd == 0 and liquidity_xn > 0 and liquidity_xn < 2000:
            risk_score += 5
            warnings.append(f"Low liquidity ({self._format_number_static(liquidity_xn)} XNT)")
        
        # Determine risk level (matches Loko_AI thresholds)
        if risk_score >= 75:
            risk_level = RiskLevel.CRITICAL
        elif risk_score >= 50:
            risk_level = RiskLevel.HIGH
        elif risk_score >= 25:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.SAFE
        
        return SecurityReport(
            mint_address=mint_address,
            name=token_name,
            symbol=token_symbol,
            decimals=token_info.decimals,
            total_supply=total_supply,
            raw_supply=token_info.supply,
            mint_authority=token_info.mint_authority,
            mint_authority_enabled=token_info.mint_authority is not None,
            freeze_authority=token_info.freeze_authority,
            freeze_authority_enabled=token_info.freeze_authority is not None,
            top_holder_percent=holder_data.get("top_holder_percent", 0),
            top_10_percent=holder_data.get("top_10_percent", 0),
            top_holders=holder_data.get("top_holders", []),
            holder_count=holder_data.get("holder_count", 0),
            lp_found=lp_found,
            lp_burned=lp_status.get("lp_burned", False),
            lp_burn_percent=lp_status.get("lp_burn_percent", 0),
            lp_address=lp_status.get("lp_address"),
            lp_burn_tx=lp_burn_tx,
            lp_total_supply=lp_status.get("lp_total_supply", 0),
            lp_burned_amount=lp_status.get("lp_burned_amount", 0),
            lp_pools=lp_status.get("pools", []),
            lp_total_burn_percent=lp_status.get("total_burn_percent", 0),
            lp_burn_tx_count=lp_status.get("burn_tx_count", 0),
            price_xn=lp_info.price_in_wxnt if lp_info else 0,
            price_usd=price_usd,
            xnt_usd_rate=xnt_usd_rate,
            price_change_24h=price_change_24h,
            liquidity_xn=liquidity_xn,
            liquidity_usd=liquidity_usd,
            token_reserve=lp_info.token_reserve if lp_info else 0,
            wxnt_reserve=lp_info.wxnt_reserve if lp_info else 0,
            volume_24h=volume_24h,
            volume_24h_usd=volume_24h_usd,
            mcap_usd=mcap_usd,
            age_str=age_str,
            risk_level=risk_level,
            risk_score=min(100, risk_score),
            warnings=warnings,
            positives=positives,
        )
    
    @staticmethod
    def _format_number_static(num: float) -> str:
        if num >= 1_000_000:
            return f"{num/1_000_000:.2f}M"
        elif num >= 1_000:
            return f"{num/1_000:.2f}K"
        return f"{num:.2f}"

    @staticmethod
    def _format_usd_static(num: float) -> str:
        if num >= 1_000_000:
            return f"${num/1_000_000:.2f}M"
        elif num >= 1_000:
            return f"${num/1_000:.2f}K"
        return f"${num:.2f}"


async def analyze_token(address: str) -> str:
    """Convenience function to analyze a token"""
    analyzer = TokenAnalyzer()
    report = await analyzer.analyze(address)
    return report.to_telegram_message()


if __name__ == "__main__":
    import sys
    
    async def main():
        if len(sys.argv) < 2:
            print("Usage: python analyzer.py <token_mint_address>")
            return
        
        address = sys.argv[1]
        print(f"Analyzing {address}...")
        
        try:
            message = await analyze_token(address)
            print(message.replace("*", "").replace("`", ""))
        except Exception as e:
            print(f"Error: {e}")
    
    asyncio.run(main())
