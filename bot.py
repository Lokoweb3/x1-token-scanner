"""
X1 Token Scanner Telegram Bot
Rick-style security scanner for SPL tokens on X1 blockchain
"""

import asyncio
import logging
import os
import re
from typing import Optional
from collections import defaultdict
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

from analyzer import TokenAnalyzer, analyze_token, SecurityReport
from calls import record_call, get_user_calls, get_call, remove_call, get_all_calls
from badges import check_and_award_badge, get_user_badges, get_badge_leaderboard, BADGE_LEVELS
from tracking import log_scan, get_user_stats, get_popular_tokens, get_active_users, get_recent_scans, add_to_watchlist, remove_from_watchlist, get_watchlist, is_watching
from config import MESSAGES, X1_CONFIG

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize analyzer
analyzer = TokenAnalyzer()

# Track recent scans per chat
recent_scans = defaultdict(list)  # chat_id -> [(timestamp, address, name), ...]
MAX_RECENT = 20


def is_valid_solana_address(address: str) -> bool:
    """Check if string looks like a Solana address"""
    if not address or len(address) < 32 or len(address) > 44:
        return False
    base58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return all(c in base58_chars for c in address)


def extract_address(text: str) -> Optional[str]:
    """Extract token address from message text"""
    text = text.strip()
    if is_valid_solana_address(text):
        return text
    words = text.split()
    for word in words:
        clean_word = re.sub(r'[^\w]', '', word)
        if is_valid_solana_address(clean_word):
            return clean_word
    return None


def add_to_recent(chat_id: int, address: str, name: str):
    """Add token to recent scans list"""
    recent_scans[chat_id].insert(0, (datetime.now(), address, name or "Unknown"))
    recent_scans[chat_id] = recent_scans[chat_id][:MAX_RECENT]


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command"""
    keyboard = [
        [InlineKeyboardButton("📖 Commands", callback_data="help")],
        [
            InlineKeyboardButton("🌐 Explorer", url=X1_CONFIG["explorer_url"]),
            InlineKeyboardButton("📈 xDEX", url="https://app.xdex.xyz/swap?toTokenAddress=1111111111111111111111111111111111111111111"),
        ],
        [InlineKeyboardButton("🤖 Trade Bot", url="https://t.me/HoneyBadgerCoreBot?start=ref_HEBCU2E3")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        MESSAGES["welcome"],
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command"""
    help_text = """
━━━━━━━━━━━━━━━━━━━━━━━━
📖 *X1 Scanner Commands*
━━━━━━━━━━━━━━━━━━━━━━━━

*Scan Tokens*
├ `/x <address>` - Full scan
├ `/check <address>` - Alias for /x
└ Just paste an address!

*Quick Actions*
├ Reply `x` to rescan
├ Reply `z` for compact
└ Reply `del` to delete

*Group Features*
├ `/last` - Recent scans
├ `/hot` - Most scanned
└ `/settings` - Bot config

*Info*
├ `/help` - This message
└ `/start` - Welcome

━━━━━━━━━━━━━━━━━━━━━━━━
_X1 Scanner • SVM Chain_
"""
    await update.message.reply_text(
        help_text,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )



async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bot statistics"""
    popular = get_popular_tokens(5)
    active = get_active_users(5)
    recent = get_recent_scans(10)
    
    msg = "📊 *Bot Statistics*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    msg += "🔥 *Popular Tokens:*\n"
    for i, t in enumerate(popular, 1):
        name = t.get("name") or t.get("symbol") or t["mint"][:8]
        msg += f"{i}. {name} - {t['scans']} scans\n"
    
    msg += "\n👥 *Active Users:*\n"
    for i, u in enumerate(active, 1):
        name = u.get("username") or u.get("name") or str(u["user_id"])
        msg += f"{i}. @{name} - {u['scans']} scans\n"
    
    msg += "\n🕐 *Recent Scans:*\n"
    for s in recent[:5]:
        user_name = s.get("username") or s.get("name") or "Unknown"
        token = s.get("token_symbol") or s["mint"][:8]
        msg += f"• @{user_name} → ${token}\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def mystats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's personal stats"""
    user = update.message.from_user
    stats = get_user_stats(user.id)
    
    msg = f"📊 *Your Stats*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"🔍 Total Scans: {stats['total_scans']}\n"
    msg += f"🪙 Unique Tokens: {stats['unique_tokens']}\n\n"
    
    if stats['recent']:
        msg += "🕐 *Recent Scans:*\n"
        for s in stats['recent']:
            token = s.get("symbol") or s.get("name") or s["mint"][:8]
            msg += f"• ${token}\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def watch_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add token to watchlist"""
    user = update.message.from_user
    if not context.args:
        await update.message.reply_text("Usage: /watch <token_address>")
        return
    address = context.args[0]
    try:
        analyzer = TokenAnalyzer()
        report = await analyzer.analyze(address)
        add_to_watchlist(user.id, address, report.name, report.symbol)
        await update.message.reply_text(f"✅ Added *{report.name}* (${report.symbol}) to watchlist!", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def unwatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove token from watchlist"""
    user = update.message.from_user
    if not context.args:
        await update.message.reply_text("Usage: /unwatch <token_address>")
        return
    if remove_from_watchlist(user.id, context.args[0]):
        await update.message.reply_text("✅ Removed from watchlist!")
    else:
        await update.message.reply_text("❌ Token not in watchlist")

async def watchlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show watchlist with prices"""
    user = update.message.from_user
    watchlist = get_watchlist(user.id)
    if not watchlist:
        await update.message.reply_text("📋 Watchlist empty! Use /watch <address>")
        return
    msg = "📋 *Your Watchlist*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    analyzer = TokenAnalyzer()
    for item in watchlist:
        try:
            lp_info = await analyzer.rpc.get_lp_info(item["mint"], 9)
            if lp_info and lp_info.price_in_wxnt > 0:
                price = lp_info.price_in_wxnt
                price_str = f"{price:.8f}" if price < 0.0001 else f"{price:.4f}" if price < 1 else f"{price:,.2f}"
                change = await analyzer.rpc.get_price_change_24h(item["mint"], price)
                change_str = f" ({'🟢+' if change >= 0 else '🔴'}{change:.1f}%)" if change else ""
                name = item.get("name") or item["mint"][:8]
                symbol = item.get("symbol") or "???"
                msg += f"• *{name}* (${symbol})\n  💰 {price_str} XNT{change_str}\n\n"
            else:
                msg += f"• *{item.get('name') or item['mint'][:8]}* - No price\n\n"
        except:
            msg += f"• *{item.get('name') or item['mint'][:8]}* - Error\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")



async def mycalls_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's calls with current X multiplier"""
    user = update.message.from_user
    calls = get_user_calls(user.id)
    
    if not calls:
        await update.message.reply_text("📞 No calls yet!\n\nScan a token and click 📞 Call to record your entry.")
        return
    
    msg = "📞 *Your Calls*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    analyzer = TokenAnalyzer()
    total_x = 0
    count = 0
    
    for call in calls:
        try:
            lp_info = await analyzer.rpc.get_lp_info(call["mint"], 9)
            
            if lp_info and lp_info.price_in_wxnt > 0:
                current_price = lp_info.price_in_wxnt
                entry_price = call["entry_price"]
                
                if entry_price > 0:
                    x_mult = current_price / entry_price
                    total_x += x_mult
                    count += 1
                    
                    # Format X multiplier and percentage
                    pct_change = (x_mult - 1) * 100
                    if x_mult >= 1:
                        x_str = f"🟢 {x_mult:.2f}x (+{pct_change:.1f}%)"
                    else:
                        x_str = f"🔴 {x_mult:.2f}x ({pct_change:.1f}%)"
                    
                    # Format mcap
                    entry_mcap = call["entry_mcap"]
                    if entry_mcap >= 1000000:
                        entry_mcap_str = f"{entry_mcap/1000000:.2f}M"
                    elif entry_mcap >= 1000:
                        entry_mcap_str = f"{entry_mcap/1000:.2f}K"
                    else:
                        entry_mcap_str = f"{entry_mcap:.2f}"
                    
                    # Current mcap (estimate from price ratio)
                    current_mcap = entry_mcap * x_mult
                    if current_mcap >= 1000000:
                        current_mcap_str = f"{current_mcap/1000000:.2f}M"
                    elif current_mcap >= 1000:
                        current_mcap_str = f"{current_mcap/1000:.2f}K"
                    else:
                        current_mcap_str = f"{current_mcap:.2f}"
                    
                    name = call.get("name") or call.get("symbol") or call["mint"][:8]
                    symbol = call.get("symbol") or "???"
                    
                    msg += f"• *{name}* (${symbol})\n"
                    msg += f"  Entry: {entry_mcap_str} → Now: {current_mcap_str}\n"
                    msg += f"  {x_str}\n\n"
                else:
                    msg += f"• *{call.get('name') or call['mint'][:8]}* - No entry price\n\n"
            else:
                msg += f"• *{call.get('name') or call['mint'][:8]}* - No price data\n\n"
        except Exception as e:
            msg += f"• *{call.get('name') or call['mint'][:8]}* - Error\n\n"
    
    # Average X
    if count > 0:
        avg_x = total_x / count
        msg += f"━━━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"📊 *Average:* {avg_x:.2f}x across {count} calls"
    
    await update.message.reply_text(msg, parse_mode="Markdown")



async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show leaderboard of all calls ranked by X gains"""
    all_calls = get_all_calls()
    
    if not all_calls:
        await update.message.reply_text("📊 No calls recorded yet!")
        return
    
    msg = "🏆 *Call Leaderboard*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    analyzer = TokenAnalyzer()
    
    # Calculate X for each call
    results = []
    for call in all_calls:
        try:
            lp_info = await analyzer.rpc.get_lp_info(call["mint"], 9)
            
            if lp_info and lp_info.price_in_wxnt > 0 and call["entry_price"] > 0:
                current_price = lp_info.price_in_wxnt
                x_mult = current_price / call["entry_price"]
                pct_change = (x_mult - 1) * 100
                
                results.append({
                    "username": call.get("username") or "Anonymous",
                    "symbol": call.get("symbol") or "???",
                    "name": call.get("name") or call["mint"][:8],
                    "x_mult": x_mult,
                    "pct_change": pct_change,
                    "entry_mcap": call.get("entry_mcap", 0)
                })
        except:
            continue
    
    # Sort by X multiplier (highest first)
    results.sort(key=lambda x: x["x_mult"], reverse=True)
    
    # Display top 10
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for i, r in enumerate(results[:10]):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        
        if r["x_mult"] >= 1:
            x_str = f"🟢 {r['x_mult']:.2f}x (+{r['pct_change']:.1f}%)"
        else:
            x_str = f"🔴 {r['x_mult']:.2f}x ({r['pct_change']:.1f}%)"
        
        # Format entry mcap
        mcap = r["entry_mcap"]
        if mcap >= 1000000:
            mcap_str = f"{mcap/1000000:.1f}M"
        elif mcap >= 1000:
            mcap_str = f"{mcap/1000:.1f}K"
        else:
            mcap_str = f"{mcap:.0f}"
        
        msg += f"{medal} @{r['username']}\n"
        msg += f"   ${r['symbol']} @ {mcap_str} → {x_str}\n\n"
    
    if len(results) > 10:
        msg += f"\n_...and {len(results) - 10} more calls_"
    
    msg += "\n━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📊 Total Calls: {len(results)}"
    
    await update.message.reply_text(msg, parse_mode="Markdown")



async def deletecall_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a call from your list"""
    user = update.message.from_user
    
    if not context.args:
        # Show user's calls with delete buttons
        calls = get_user_calls(user.id)
        if not calls:
            await update.message.reply_text("📞 No calls to delete!")
            return
        
        msg = "🗑️ *Select a call to delete:*\n\n"
        keyboard = []
        for call in calls[:10]:
            symbol = call.get("symbol") or call["mint"][:8]
            msg += f"• ${symbol} - `{call['mint'][:20]}...`\n"
            keyboard.append([InlineKeyboardButton(f"🗑️ Delete ${symbol}", callback_data=f"deletecall:{call['mint']}")])
        
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    address = context.args[0]
    if remove_call(user.id, address):
        await update.message.reply_text("✅ Call deleted!")
    else:
        await update.message.reply_text("❌ Call not found")

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """View a user's profile and calls"""
    from calls import get_all_calls
    
    all_calls = get_all_calls()
    
    # Get username to search
    if context.args:
        search_name = context.args[0].replace("@", "").lower()
    else:
        # Show own profile
        search_name = update.message.from_user.username.lower() if update.message.from_user.username else None
    
    if not search_name:
        await update.message.reply_text("Usage: /profile @username")
        return
    
    # Find user's calls
    user_calls = [c for c in all_calls if c.get("username", "").lower() == search_name]
    
    if not user_calls:
        await update.message.reply_text(f"❌ No calls found for @{search_name}")
        return
    
    msg = f"👤 *Profile: @{search_name}*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    analyzer = TokenAnalyzer()
    total_x = 0
    wins = 0
    losses = 0
    
    for call in user_calls:
        try:
            lp_info = await analyzer.rpc.get_lp_info(call["mint"], 9)
            
            if lp_info and lp_info.price_in_wxnt > 0 and call["entry_price"] > 0:
                x_mult = lp_info.price_in_wxnt / call["entry_price"]
                pct = (x_mult - 1) * 100
                total_x += x_mult
                
                if x_mult >= 1:
                    wins += 1
                    x_str = f"🟢 {x_mult:.2f}x (+{pct:.1f}%)"
                else:
                    losses += 1
                    x_str = f"🔴 {x_mult:.2f}x ({pct:.1f}%)"
                
                symbol = call.get("symbol") or "???"
                msg += f"• ${symbol} → {x_str}\n"
        except:
            continue
    
    avg_x = total_x / len(user_calls) if user_calls else 0
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    
    msg += f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📊 *Stats:*\n"
    msg += f"• Total Calls: {len(user_calls)}\n"
    msg += f"• Win Rate: {win_rate:.0f}% ({wins}W / {losses}L)\n"
    msg += f"• Average X: {avg_x:.2f}x"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def leaderboard_time_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show leaderboard with time filter"""
    from datetime import datetime, timedelta
    from calls import get_all_calls
    
    # Parse time filter
    filter_hours = 24  # default 24h
    filter_label = "24h"
    
    if context.args:
        arg = context.args[0].lower()
        if arg in ["7d", "7days", "week"]:
            filter_hours = 168
            filter_label = "7 days"
        elif arg in ["30d", "30days", "month"]:
            filter_hours = 720
            filter_label = "30 days"
        elif arg in ["24h", "1d", "day"]:
            filter_hours = 24
            filter_label = "24h"
        elif arg == "all":
            filter_hours = 999999
            filter_label = "All Time"
    
    all_calls = get_all_calls()
    
    # Filter by time
    cutoff = datetime.now() - timedelta(hours=filter_hours)
    filtered_calls = []
    for call in all_calls:
        try:
            call_time = datetime.strptime(call["called_at"], "%Y-%m-%d %H:%M:%S")
            if call_time >= cutoff:
                filtered_calls.append(call)
        except:
            filtered_calls.append(call)  # Include if can't parse
    
    if not filtered_calls:
        await update.message.reply_text(f"📊 No calls in the last {filter_label}")
        return
    
    msg = f"🏆 *Leaderboard ({filter_label})*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    analyzer = TokenAnalyzer()
    results = []
    
    for call in filtered_calls:
        try:
            lp_info = await analyzer.rpc.get_lp_info(call["mint"], 9)
            if lp_info and lp_info.price_in_wxnt > 0 and call["entry_price"] > 0:
                x_mult = lp_info.price_in_wxnt / call["entry_price"]
                pct = (x_mult - 1) * 100
                results.append({
                    "username": call.get("username") or "Anon",
                    "symbol": call.get("symbol") or "???",
                    "x_mult": x_mult,
                    "pct": pct,
                    "entry_mcap": call.get("entry_mcap", 0)
                })
        except:
            continue
    
    results.sort(key=lambda x: x["x_mult"], reverse=True)
    
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for i, r in enumerate(results[:10]):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        if r["x_mult"] >= 1:
            x_str = f"🟢 {r['x_mult']:.2f}x (+{r['pct']:.1f}%)"
        else:
            x_str = f"🔴 {r['x_mult']:.2f}x ({r['pct']:.1f}%)"
        
        mcap = r["entry_mcap"]
        mcap_str = f"{mcap/1000000:.1f}M" if mcap >= 1000000 else f"{mcap/1000:.1f}K" if mcap >= 1000 else f"{mcap:.0f}"
        
        msg += f"{medal} @{r['username']}\n   ${r['symbol']} @ {mcap_str} → {x_str}\n\n"
    
    # Add filter buttons
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("24h", callback_data="lb:24h"),
            InlineKeyboardButton("7d", callback_data="lb:7d"),
            InlineKeyboardButton("30d", callback_data="lb:30d"),
            InlineKeyboardButton("All", callback_data="lb:all"),
        ]
    ])
    
    msg += f"━━━━━━━━━━━━━━━━━━━━━━\n📊 Total: {len(results)} calls"
    
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)



async def badges_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's badges"""
    user = update.message.from_user
    badges = get_user_badges(user.id)
    
    if not badges:
        msg = "🏆 *Your Badges*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        msg += "No badges yet!\n\n"
        msg += "*How to earn badges:*\n"
        msg += "🥉 Bronze - 2x on a call\n"
        msg += "🥈 Silver - 5x on a call\n"
        msg += "🥇 Gold - 10x on a call\n"
        msg += "💎 Diamond - 25x on a call\n"
        msg += "👑 Crown - 50x on a call\n"
        msg += "🚀 Legend - 100x on a call\n\n"
        msg += "_Make calls and watch them moon!_"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return
    
    msg = f"🏆 *Your Badges* ({len(badges)} total)\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for badge in badges:
        msg += f"{badge['emoji']} *{badge['name']}* - ${badge['token_symbol']}\n"
        msg += f"   Achieved: {badge['x_achieved']:.1f}x\n\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def badge_leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show badge leaderboard"""
    leaders = get_badge_leaderboard()
    
    if not leaders:
        await update.message.reply_text("🏆 No badges earned yet!")
        return
    
    msg = "🏆 *Badge Leaderboard*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for i, leader in enumerate(leaders):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        username = leader.get("username") or "Anonymous"
        
        badge_str = ""
        if leader["legends"] > 0:
            badge_str += f"🚀{leader['legends']} "
        if leader["crowns"] > 0:
            badge_str += f"👑{leader['crowns']} "
        if leader["diamonds"] > 0:
            badge_str += f"💎{leader['diamonds']} "
        if leader["golds"] > 0:
            badge_str += f"🥇{leader['golds']} "
        if leader["silvers"] > 0:
            badge_str += f"🥈{leader['silvers']} "
        if leader["bronzes"] > 0:
            badge_str += f"🥉{leader['bronzes']} "
        
        msg += f"{medal} @{username}\n"
        msg += f"   {badge_str}\n"
        msg += f"   Best: {leader['best_x']:.1f}x | Total: {leader['total_badges']} badges\n\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def x_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /x command - full scan"""
    if not context.args:
        await update.message.reply_text(
            "Usage: `/x <token_address>`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    address = context.args[0]
    # Ask user first
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👀 Just Checking", callback_data=f"justscan:{address}"),
            InlineKeyboardButton("📞 Call It", callback_data=f"confirmcall:{address}"),
        ]
    ])
    short_addr = f"{address[:6]}...{address[-4:]}"
    await update.message.reply_text(f"📋 *Token:* `{short_addr}`\n\nWhat would you like to do?", parse_mode="Markdown", reply_markup=keyboard)

async def z_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /z command - compact scan"""
    if not context.args:
        await update.message.reply_text(
            "Usage: `/z <token_address>`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    address = context.args[0]
    await analyze_and_reply(update, address, compact=True)


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /check command"""
    if not context.args:
        await update.message.reply_text(
            "Usage: `/check <token_address>`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    address = context.args[0]
    # Ask user first
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👀 Just Checking", callback_data=f"justscan:{address}"),
            InlineKeyboardButton("📞 Call It", callback_data=f"confirmcall:{address}"),
        ]
    ])
    short_addr = f"{address[:6]}...{address[-4:]}"
    await update.message.reply_text(f"📋 *Token:* `{short_addr}`\n\nWhat would you like to do?", parse_mode="Markdown", reply_markup=keyboard)
    return


async def last_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /last command - show recent scans"""
    chat_id = update.effective_chat.id
    scans = recent_scans.get(chat_id, [])
    
    if not scans:
        await update.message.reply_text("No recent scans in this chat.")
        return
    
    msg = "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "📜 *Recent Scans*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for i, (ts, addr, name) in enumerate(scans[:10]):
        time_ago = datetime.now() - ts
        if time_ago.seconds < 60:
            time_str = f"{time_ago.seconds}s"
        elif time_ago.seconds < 3600:
            time_str = f"{time_ago.seconds // 60}m"
        else:
            time_str = f"{time_ago.seconds // 3600}h"
        
        addr_short = f"{addr[:4]}..{addr[-3:]}"
        msg += f"`{i+1}.` *{name}* `{addr_short}` _{time_str} ago_\n"
    
    msg += "\n_Click address to rescan_"
    
    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )


async def hot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /hot command - show most scanned tokens"""
    chat_id = update.effective_chat.id
    scans = recent_scans.get(chat_id, [])
    
    if not scans:
        await update.message.reply_text("No scans recorded yet.")
        return
    
    # Count occurrences
    counts = defaultdict(lambda: {"count": 0, "name": "Unknown"})
    for ts, addr, name in scans:
        counts[addr]["count"] += 1
        counts[addr]["name"] = name
    
    # Sort by count
    sorted_tokens = sorted(counts.items(), key=lambda x: x[1]["count"], reverse=True)[:5]
    
    msg = "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "🔥 *Hot Tokens*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for addr, data in sorted_tokens:
        addr_short = f"{addr[:4]}..{addr[-3:]}"
        msg += f"🔸 *{data['name']}* `{addr_short}` ({data['count']}x)\n"
    
    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings command"""
    msg = """
━━━━━━━━━━━━━━━━━━━━━━━━
⚙️ *Bot Settings*
━━━━━━━━━━━━━━━━━━━━━━━━

*Current Config:*
├ Chain: `X1 Mainnet`
├ RPC: `rpc.mainnet.x1.xyz`
└ Mode: `Full Scan`

_Settings coming soon!_
"""
    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.MARKDOWN
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle regular messages"""
    text = update.message.text.strip().lower()
    
    # Check if replying to a bot message with x/z/del
    if update.message.reply_to_message:
        reply_text = update.message.reply_to_message.text or ""
        
        # Extract address from replied message
        address_match = re.search(r'`([1-9A-HJ-NP-Za-km-z]{32,44})`', reply_text)
        
        if text in ['x', '/x']:
            if address_match:
                await analyze_and_reply(update, address_match.group(1), compact=False)
                return
        elif text in ['z', '/z']:
            if address_match:
                await analyze_and_reply(update, address_match.group(1), compact=True)
                return
        elif text in ['del', 'delete', 'x']:
            # Try to delete the bot's message
            try:
                await update.message.reply_to_message.delete()
                await update.message.delete()
            except Exception:
                pass
            return
    
    # Try to extract address from message
    address = extract_address(update.message.text)
    
    if address:
        # Ask user first
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("👀 Just Checking", callback_data=f"justscan:{address}"),
                InlineKeyboardButton("📞 Call It", callback_data=f"confirmcall:{address}"),
            ]
        ])
        short_addr = f"{address[:6]}...{address[-4:]}"
        await update.message.reply_text(f"📋 *Token:* `{short_addr}`\n\nWhat would you like to do?", parse_mode="Markdown", reply_markup=keyboard)
        return
    # Don't respond to non-address messages in groups


async def analyze_and_reply(update: Update, address: str, compact: bool = False, user_data: dict = None) -> None:
    """Analyze token and send report"""
    # Send "scanning" message
    status_msg = await update.message.reply_text(
        MESSAGES["analyzing"].format(address[:8] + "..." + address[-4:]),
        parse_mode=ParseMode.MARKDOWN
    )
    
    try:
        # Perform analysis
        token_analyzer = TokenAnalyzer()
        report = await token_analyzer.analyze(address)
        
        # Add to recent scans
        chat_id = update.effective_chat.id
        add_to_recent(chat_id, address, report.name)
        
        # Delete status message
        await status_msg.delete()
        
        # Format message based on mode
        if compact:
            message = format_compact_report(report)
        else:
            message = report.to_telegram_message()
        
        # Create action buttons
        keyboard = [
            [
                InlineKeyboardButton("🔍 Explorer", url=f"{X1_CONFIG['explorer_url']}/address/{address}"),
                InlineKeyboardButton("📈 xDEX", url=f"https://app.xdex.xyz/swap?fromTokenAddress={address}&toTokenAddress=1111111111111111111111111111111111111111111"),
                InlineKeyboardButton("🤖 Trade", url="https://t.me/HoneyBadgerCoreBot?start=ref_HEBCU2E3"),
            ],
            [
                InlineKeyboardButton("📞 Call", callback_data=f"call:{address}"),
                InlineKeyboardButton("🔄 Refresh", callback_data=f"scan:{address}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
        
    except ValueError as e:
        await status_msg.edit_text(
            f"❌ {str(e)}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error analyzing token: {e}")
        await status_msg.edit_text(
            "❌ Error scanning token. Try again.",
            parse_mode=ParseMode.MARKDOWN
        )


def format_compact_report(report: SecurityReport) -> str:
    """Format a compact version of the report"""
    risk_icons = {
        "SAFE": "🟢",
        "MEDIUM": "🟡", 
        "HIGH": "🔴",
        "CRITICAL": "☠️",
    }
    
    risk_icon = risk_icons.get(report.risk_level.name, "❓")
    name = report.name or "???"
    symbol = report.symbol or "???"
    
    mint_icon = "🔴" if report.mint_authority_enabled else "🟢"
    freeze_icon = "🔴" if report.freeze_authority_enabled else "🟢"
    
    return f"""{risk_icon} *{name}* `${symbol}` │ `{report.mint_address[:6]}..{report.mint_address[-3:]}`
├ {mint_icon} Mint {freeze_icon} Freeze │ Top: `{report.top_holder_percent:.1f}%`
└ Risk: `{report.risk_score}/100` │ Supply: `{report._format_number(report.total_supply)}`"""


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "help":
        await help_command(update, context)
    
    elif data.startswith("call:"):
        address = data.split(":")[1]
        # Show confirmation buttons
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("👀 Just Checking", callback_data=f"checking:{address}"),
                InlineKeyboardButton("📞 Confirm Call", callback_data=f"confirmcall:{address}"),
            ]
        ])
        await query.answer()
        await query.message.reply_text(
            "What would you like to do?\n\n"
            "👀 *Just Checking* - Only viewing, no record\n"
            "📞 *Confirm Call* - Record entry for tracking X gains",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return
    
    elif data.startswith("checking:"):
        await query.answer("👀 Just checking - no call recorded!", show_alert=True)
        await query.message.delete()
        return
    
    elif data.startswith("justscan:"):
        address = data.split(":")[1]
        await query.answer("Loading full analysis...")
        
        try:
            analyzer = TokenAnalyzer()
            report = await analyzer.analyze(address)
            
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔍 Explorer", url=f"https://explorer.x1.xyz/address/{address}"),
                    InlineKeyboardButton("📈 xDEX", url=f"https://app.xdex.xyz/swap?fromTokenAddress={address}&toTokenAddress=1111111111111111111111111111111111111111111"),
                    InlineKeyboardButton("🐸 Trade", url=f"https://t.me/HoneyBadgerCoreBot?start=ref_HEBCU2E3"),
                ],
                [
                    InlineKeyboardButton("📞 Call", callback_data=f"call:{address}"),
                    InlineKeyboardButton("🔄 Refresh", callback_data=f"scan:{address}"),
                ]
            ])
            
            await query.message.edit_text(
                report.to_telegram_message(),
                parse_mode="Markdown",
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception as e:
            await query.message.edit_text(f"❌ Error: {str(e)}")
        return
    
    elif data == "mycalls":
        user = query.from_user
        calls = get_user_calls(user.id)
        
        if not calls:
            await query.answer("No calls yet!", show_alert=True)
            return
        
        msg = "📞 *Your Calls*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        analyzer = TokenAnalyzer()
        total_x = 0
        count = 0
        
        for call in calls:
            try:
                lp_info = await analyzer.rpc.get_lp_info(call["mint"], 9)
                
                if lp_info and lp_info.price_in_wxnt > 0 and call["entry_price"] > 0:
                    x_mult = lp_info.price_in_wxnt / call["entry_price"]
                    pct_change = (x_mult - 1) * 100
                    total_x += x_mult
                    count += 1
                    
                    if x_mult >= 1:
                        x_str = f"🟢 {x_mult:.2f}x (+{pct_change:.1f}%)"
                    else:
                        x_str = f"🔴 {x_mult:.2f}x ({pct_change:.1f}%)"
                    
                    entry_mcap = call["entry_mcap"]
                    mcap_str = f"{entry_mcap/1000000:.1f}M" if entry_mcap >= 1000000 else f"{entry_mcap/1000:.1f}K" if entry_mcap >= 1000 else f"{entry_mcap:.0f}"
                    
                    current_mcap = entry_mcap * x_mult
                    current_mcap_str = f"{current_mcap/1000000:.1f}M" if current_mcap >= 1000000 else f"{current_mcap/1000:.1f}K" if current_mcap >= 1000 else f"{current_mcap:.0f}"
                    
                    symbol = call.get("symbol") or "???"
                    msg += f"• *{call.get('name') or symbol}* (${symbol})\n"
                    msg += f"  Entry: {mcap_str} → Now: {current_mcap_str}\n"
                    msg += f"  {x_str}\n\n"
            except:
                continue
        
        if count > 0:
            avg_x = total_x / count
            msg += f"━━━━━━━━━━━━━━━━━━━━━━\n📊 *Average:* {avg_x:.2f}x across {count} calls"
        
        await query.answer()
        await query.message.reply_text(msg, parse_mode="Markdown")
        return
    
    elif data == "mycalls":
        user = query.from_user
        calls = get_user_calls(user.id)
        
        if not calls:
            await query.answer("No calls yet!", show_alert=True)
            return
        
        msg = "📞 *Your Calls*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        analyzer = TokenAnalyzer()
        total_x = 0
        count = 0
        
        for call in calls:
            try:
                lp_info = await analyzer.rpc.get_lp_info(call["mint"], 9)
                
                if lp_info and lp_info.price_in_wxnt > 0 and call["entry_price"] > 0:
                    x_mult = lp_info.price_in_wxnt / call["entry_price"]
                    pct_change = (x_mult - 1) * 100
                    total_x += x_mult
                    count += 1
                    
                    if x_mult >= 1:
                        x_str = f"🟢 {x_mult:.2f}x (+{pct_change:.1f}%)"
                    else:
                        x_str = f"🔴 {x_mult:.2f}x ({pct_change:.1f}%)"
                    
                    entry_mcap = call["entry_mcap"]
                    mcap_str = f"{entry_mcap/1000000:.1f}M" if entry_mcap >= 1000000 else f"{entry_mcap/1000:.1f}K" if entry_mcap >= 1000 else f"{entry_mcap:.0f}"
                    
                    current_mcap = entry_mcap * x_mult
                    current_mcap_str = f"{current_mcap/1000000:.1f}M" if current_mcap >= 1000000 else f"{current_mcap/1000:.1f}K" if current_mcap >= 1000 else f"{current_mcap:.0f}"
                    
                    symbol = call.get("symbol") or "???"
                    msg += f"• *{call.get('name') or symbol}* (${symbol})\n"
                    msg += f"  Entry: {mcap_str} → Now: {current_mcap_str}\n"
                    msg += f"  {x_str}\n\n"
            except:
                continue
        
        if count > 0:
            avg_x = total_x / count
            msg += f"━━━━━━━━━━━━━━━━━━━━━━\n📊 *Average:* {avg_x:.2f}x across {count} calls"
        
        await query.answer()
        await query.message.reply_text(msg, parse_mode="Markdown")
        return
    
    elif data == "mycalls":
        user = query.from_user
        calls = get_user_calls(user.id)
        
        if not calls:
            await query.answer("No calls yet!", show_alert=True)
            return
        
        msg = "📞 *Your Calls*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        analyzer = TokenAnalyzer()
        total_x = 0
        count = 0
        
        for call in calls:
            try:
                lp_info = await analyzer.rpc.get_lp_info(call["mint"], 9)
                
                if lp_info and lp_info.price_in_wxnt > 0 and call["entry_price"] > 0:
                    x_mult = lp_info.price_in_wxnt / call["entry_price"]
                    pct_change = (x_mult - 1) * 100
                    total_x += x_mult
                    count += 1
                    
                    if x_mult >= 1:
                        x_str = f"🟢 {x_mult:.2f}x (+{pct_change:.1f}%)"
                    else:
                        x_str = f"🔴 {x_mult:.2f}x ({pct_change:.1f}%)"
                    
                    entry_mcap = call["entry_mcap"]
                    mcap_str = f"{entry_mcap/1000000:.1f}M" if entry_mcap >= 1000000 else f"{entry_mcap/1000:.1f}K" if entry_mcap >= 1000 else f"{entry_mcap:.0f}"
                    
                    current_mcap = entry_mcap * x_mult
                    current_mcap_str = f"{current_mcap/1000000:.1f}M" if current_mcap >= 1000000 else f"{current_mcap/1000:.1f}K" if current_mcap >= 1000 else f"{current_mcap:.0f}"
                    
                    symbol = call.get("symbol") or "???"
                    msg += f"• *{call.get('name') or symbol}* (${symbol})\n"
                    msg += f"  Entry: {mcap_str} → Now: {current_mcap_str}\n"
                    msg += f"  {x_str}\n\n"
            except:
                continue
        
        if count > 0:
            avg_x = total_x / count
            msg += f"━━━━━━━━━━━━━━━━━━━━━━\n📊 *Average:* {avg_x:.2f}x across {count} calls"
        
        await query.answer()
        await query.message.reply_text(msg, parse_mode="Markdown")
        return
    
    elif data.startswith("deletecall:"):
        address = data.split(":")[1]
        user = query.from_user
        if remove_call(user.id, address):
            await query.answer("✅ Call deleted!", show_alert=True)
            await query.message.delete()
        else:
            await query.answer("❌ Error deleting call", show_alert=True)
        return
    
    elif data.startswith("lb:"):
        time_filter = data.split(":")[1]
        from datetime import datetime, timedelta
        
        filter_map = {"24h": 24, "7d": 168, "30d": 720, "all": 999999}
        filter_hours = filter_map.get(time_filter, 24)
        filter_label = {"24h": "24h", "7d": "7 days", "30d": "30 days", "all": "All Time"}.get(time_filter, "24h")
        
        all_calls = get_all_calls()
        cutoff = datetime.now() - timedelta(hours=filter_hours)
        
        filtered = []
        for call in all_calls:
            try:
                call_time = datetime.strptime(call["called_at"], "%Y-%m-%d %H:%M:%S")
                if call_time >= cutoff:
                    filtered.append(call)
            except:
                filtered.append(call)
        
        analyzer = TokenAnalyzer()
        results = []
        
        for call in filtered:
            try:
                lp_info = await analyzer.rpc.get_lp_info(call["mint"], 9)
                if lp_info and lp_info.price_in_wxnt > 0 and call["entry_price"] > 0:
                    x_mult = lp_info.price_in_wxnt / call["entry_price"]
                    pct = (x_mult - 1) * 100
                    results.append({
                        "username": call.get("username") or "Anon",
                        "symbol": call.get("symbol") or "???",
                        "x_mult": x_mult,
                        "pct": pct,
                        "entry_mcap": call.get("entry_mcap", 0)
                    })
            except:
                continue
        
        results.sort(key=lambda x: x["x_mult"], reverse=True)
        
        msg = f"🏆 *Leaderboard ({filter_label})*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        
        for i, r in enumerate(results[:10]):
            medal = medals[i] if i < len(medals) else f"{i+1}."
            x_str = f"🟢 {r['x_mult']:.2f}x (+{r['pct']:.1f}%)" if r["x_mult"] >= 1 else f"🔴 {r['x_mult']:.2f}x ({r['pct']:.1f}%)"
            mcap = r["entry_mcap"]
            mcap_str = f"{mcap/1000000:.1f}M" if mcap >= 1000000 else f"{mcap/1000:.1f}K" if mcap >= 1000 else f"{mcap:.0f}"
            msg += f"{medal} @{r['username']}\n   ${r['symbol']} @ {mcap_str} → {x_str}\n\n"
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("24h", callback_data="lb:24h"),
                InlineKeyboardButton("7d", callback_data="lb:7d"),
                InlineKeyboardButton("30d", callback_data="lb:30d"),
                InlineKeyboardButton("All", callback_data="lb:all"),
            ]
        ])
        
        msg += f"━━━━━━━━━━━━━━━━━━━━━━\n📊 Total: {len(results)} calls"
        
        await query.answer()
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=keyboard)
        return
    
    elif data.startswith("confirmcall:"):
        address = data.split(":")[1]
        user = query.from_user
        
        try:
            analyzer = TokenAnalyzer()
            report = await analyzer.analyze(address)
            
            # Calculate market cap
            mcap = report.price_xn * report.total_supply if report.price_xn > 0 else 0
            
            # Record the call
            record_call(
                user_id=user.id,
                username=user.username or user.first_name,
                mint_address=address,
                token_name=report.name,
                token_symbol=report.symbol,
                entry_price=report.price_xn,
                entry_mcap=mcap
            )
            
            # Format mcap
            if mcap >= 1000000:
                mcap_str = f"{mcap/1000000:.2f}M"
            elif mcap >= 1000:
                mcap_str = f"{mcap/1000:.2f}K"
            else:
                mcap_str = f"{mcap:.2f}"
            
            await query.answer(f"📞 Called {report.symbol} at {mcap_str} MCap!", show_alert=True)
            
            # Show full analysis
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔍 Explorer", url=f"https://explorer.x1.xyz/address/{address}"),
                    InlineKeyboardButton("📈 xDEX", url=f"https://app.xdex.xyz/swap?fromTokenAddress={address}&toTokenAddress=1111111111111111111111111111111111111111111"),
                    InlineKeyboardButton("🐸 Trade", url=f"https://t.me/HoneyBadgerCoreBot?start=ref_HEBCU2E3"),
                ],
                [
                    InlineKeyboardButton("📞 My Calls", callback_data="mycalls"),
                    InlineKeyboardButton("🔄 Refresh", callback_data=f"scan:{address}"),
                ]
            ])
            
            msg = f"✅ *CALLED!* Entry recorded\n\n" + report.to_telegram_message()
            
            await query.message.edit_text(
                msg,
                parse_mode="Markdown",
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception as e:
            await query.answer(f"Error: {str(e)}", show_alert=True)
        return
    
    elif data.startswith("scan:"):
        address = data.split(":", 1)[1]
        try:
            token_analyzer = TokenAnalyzer()
            report = await token_analyzer.analyze(address)
            message = report.to_telegram_message()
            
            keyboard = [
                [
                    InlineKeyboardButton("🔍 Explorer", url=f"{X1_CONFIG['explorer_url']}/address/{address}"),
                    InlineKeyboardButton("📈 xDEX", url=f"https://app.xdex.xyz/swap?fromTokenAddress={address}&toTokenAddress=1111111111111111111111111111111111111111111"),
                    InlineKeyboardButton("🤖 Trade", url="https://t.me/HoneyBadgerCoreBot?start=ref_HEBCU2E3"),
                ],
                [
                    InlineKeyboardButton("📞 Call", callback_data=f"call:{address}"),
                InlineKeyboardButton("🔄 Refresh", callback_data=f"scan:{address}"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.message.edit_text(
                message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
        except Exception as e:
            await query.answer(f"Error: {str(e)}", show_alert=True)
    
    elif data.startswith("compact:"):
        address = data.split(":", 1)[1]
        try:
            token_analyzer = TokenAnalyzer()
            report = await token_analyzer.analyze(address)
            message = format_compact_report(report)
            
            keyboard = [
                [
                    InlineKeyboardButton("🔍 Full Scan", callback_data=f"scan:{address}"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.message.edit_text(
                message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
        except Exception as e:
            await query.answer(f"Error: {str(e)}", show_alert=True)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")


def main():
    """Start the bot"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    
    if not token:
        print("=" * 50)
        print("X1 TOKEN SCANNER")
        print("=" * 50)
        print("\nSet your bot token:")
        print("  export TELEGRAM_BOT_TOKEN='your_token'")
        print("\nThen run: python3 bot.py")
        print("=" * 50)
        return
    
    # Build application
    application = Application.builder().token(token).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("x", x_command))
    application.add_handler(CommandHandler("z", z_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("last", last_command))
    application.add_handler(CommandHandler("hot", hot_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("mystats", mystats_command))
    application.add_handler(CommandHandler("watch", watch_command))
    application.add_handler(CommandHandler("unwatch", unwatch_command))
    application.add_handler(CommandHandler("watchlist", watchlist_command))
    application.add_handler(CommandHandler("mycalls", mycalls_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("lb", leaderboard_time_command))
    application.add_handler(CommandHandler("deletecall", deletecall_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("badges", badges_command))
    application.add_handler(CommandHandler("badgeleaderboard", badge_leaderboard_command))
    application.add_handler(CommandHandler("bl", badge_leaderboard_command))
    application.add_handler(CommandHandler("lb", leaderboard_time_command))
    application.add_handler(CommandHandler("deletecall", deletecall_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("badges", badges_command))
    application.add_handler(CommandHandler("badgeleaderboard", badge_leaderboard_command))
    application.add_handler(CommandHandler("bl", badge_leaderboard_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    print("━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🔍 X1 Token Scanner")
    print("━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"RPC: {X1_CONFIG['rpc_url']}")
    print("Bot is running...")
    print("━━━━━━━━━━━━━━━━━━━━━━━━")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
