"""
Configuration for X1 Token Scanner Bot
X1 is a Solana Virtual Machine (SVM) compatible blockchain
"""

# X1 Network Configuration
X1_CONFIG = {
    "chain_name": "X1 Mainnet",
    "native_token": "XNT",
    "rpc_url": "https://rpc.mainnet.x1.xyz",
    "explorer_url": "https://explorer.x1.xyz",
    "testnet_rpc": "https://xolana.xen.network",
}

# SPL Token Program IDs (same as Solana)
PROGRAM_IDS = {
    "token_program": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "token_2022_program": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    "associated_token_program": "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
    "metadata_program": "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s",  # Metaplex
}

# Known burn/null addresses for LP burn detection
BURN_ADDRESSES = [
    "1nc1nerator11111111111111111111111111111111",  # X1 Incinerator (main burn address)
    "1111111111111111111111111111111111111111111",  # System null address
    "11111111111111111111111111111111",  # 32-byte null
]

# Known DEX Programs on X1
DEX_PROGRAMS = {
    "xdex": "XDEX111111111111111111111111111111111111111",  # Update with real XDEX program
    "raydium_amm": "",
    "orca": "",
}

# Risk scoring thresholds
RISK_THRESHOLDS = {
    "top_holder_high": 50,
    "top_holder_medium": 20,
    "top_10_high": 80,
    "freeze_authority_risk": 30,
    "mint_authority_risk": 25,
}

# Bot Messages
MESSAGES = {
    "welcome": """
━━━━━━━━━━━━━━━━━━━━━━━━
🔍 *X1 Token Scanner*
⚠️ _BETA - Features may change, report bugs to admin_
━━━━━━━━━━━━━━━━━━━━━━━━

Drop a contract address to scan any token on X1 blockchain.

*What I check:*
├ 🔐 Mint & Freeze Authority
├ 👥 Holder Distribution  
├ 📊 Supply & Decimals
├ 🔥 LP Burn Status (all pools)
└ ⚠️ Risk Assessment

*Commands:*
├ Just paste a token address
├ /check `<address>` - Scan token
└ /help - More info

_Powered by direct X1 RPC queries_
━━━━━━━━━━━━━━━━━━━━━━━━
""",
    "analyzing": "🔍 Scanning `{}`...",
    "invalid_address": "❌ Invalid address. Send a valid X1 token mint address.",
    "not_token": "❌ Not a valid SPL token on X1.",
    "error": "❌ Error: {}",
}

# Telegram Bot Settings
TELEGRAM_SETTINGS = {
    "parse_mode": "Markdown",
    "disable_web_page_preview": True,
}
