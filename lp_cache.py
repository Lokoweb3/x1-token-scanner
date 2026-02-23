"""
LP Burn Cache — Caches LP burn data in SQLite for fast repeat scans.
Burns rarely change, so we cache for 6 hours by default.
"""

import sqlite3
import json
import time
from typing import Optional, Dict, List

CACHE_DB = "lp_cache.db"
CACHE_TTL = 6 * 3600  # 6 hours in seconds


def init_cache():
    """Initialize the LP cache database"""
    conn = sqlite3.connect(CACHE_DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS lp_cache (
            mint_address TEXT PRIMARY KEY,
            lp_data TEXT,
            cached_at REAL,
            scan_duration REAL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS lp_mint_cache (
            lp_mint TEXT PRIMARY KEY,
            initial_supply REAL,
            cached_at REAL
        )
    """)
    conn.commit()
    conn.close()


def get_cached_lp_status(mint_address: str) -> Optional[Dict]:
    """Get cached LP status for a token. Returns None if expired or not found."""
    try:
        conn = sqlite3.connect(CACHE_DB)
        c = conn.cursor()
        c.execute(
            "SELECT lp_data, cached_at FROM lp_cache WHERE mint_address = ?",
            (mint_address,)
        )
        row = c.fetchone()
        conn.close()

        if not row:
            return None

        lp_data_json, cached_at = row

        # Check TTL
        if time.time() - cached_at > CACHE_TTL:
            return None

        return json.loads(lp_data_json)

    except Exception:
        return None


def set_cached_lp_status(mint_address: str, lp_data: Dict, scan_duration: float = 0):
    """Cache LP status for a token."""
    try:
        conn = sqlite3.connect(CACHE_DB)
        c = conn.cursor()
        c.execute(
            """INSERT OR REPLACE INTO lp_cache 
               (mint_address, lp_data, cached_at, scan_duration) 
               VALUES (?, ?, ?, ?)""",
            (mint_address, json.dumps(lp_data), time.time(), scan_duration)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_cached_initial_supply(lp_mint: str) -> Optional[float]:
    """Get cached initial LP supply. These NEVER change so cache permanently."""
    try:
        conn = sqlite3.connect(CACHE_DB)
        c = conn.cursor()
        c.execute(
            "SELECT initial_supply FROM lp_mint_cache WHERE lp_mint = ?",
            (lp_mint,)
        )
        row = c.fetchone()
        conn.close()

        if row:
            return row[0]
        return None

    except Exception:
        return None


def set_cached_initial_supply(lp_mint: str, initial_supply: float):
    """Cache initial LP supply. This never changes (first mint is permanent)."""
    try:
        conn = sqlite3.connect(CACHE_DB)
        c = conn.cursor()
        c.execute(
            """INSERT OR REPLACE INTO lp_mint_cache 
               (lp_mint, initial_supply, cached_at) 
               VALUES (?, ?, ?)""",
            (lp_mint, initial_supply, time.time())
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def invalidate_cache(mint_address: str):
    """Force refresh cache for a specific token."""
    try:
        conn = sqlite3.connect(CACHE_DB)
        c = conn.cursor()
        c.execute("DELETE FROM lp_cache WHERE mint_address = ?", (mint_address,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_cache_stats() -> Dict:
    """Get cache statistics."""
    try:
        conn = sqlite3.connect(CACHE_DB)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM lp_cache")
        token_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM lp_mint_cache")
        mint_count = c.fetchone()[0]
        c.execute("SELECT AVG(scan_duration) FROM lp_cache WHERE scan_duration > 0")
        avg_duration = c.fetchone()[0] or 0
        conn.close()
        return {
            "cached_tokens": token_count,
            "cached_lp_mints": mint_count,
            "avg_scan_duration": round(avg_duration, 1),
        }
    except Exception:
        return {"cached_tokens": 0, "cached_lp_mints": 0, "avg_scan_duration": 0}


# Initialize on import
init_cache()
