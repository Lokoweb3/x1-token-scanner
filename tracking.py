
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional

TRACKING_DB = "user_activity.db"

def init_tracking_db():
    """Initialize the tracking database"""
    conn = sqlite3.connect(TRACKING_DB)
    c = conn.cursor()
    
    # User scans table
    c.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            mint_address TEXT,
            token_name TEXT,
            token_symbol TEXT,
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Watchlist table
    c.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            user_id INTEGER,
            mint_address TEXT,
            token_name TEXT,
            token_symbol TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, mint_address)
        )
    """)
    
    conn.commit()
    conn.close()

def log_scan(user_id: int, username: str, first_name: str, mint_address: str, token_name: str = None, token_symbol: str = None):
    """Log a token scan"""
    try:
        conn = sqlite3.connect(TRACKING_DB)
        c = conn.cursor()
        c.execute(
            "INSERT INTO scans (user_id, username, first_name, mint_address, token_name, token_symbol) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, first_name, mint_address, token_name, token_symbol)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error logging scan: {e}")

def get_user_stats(user_id: int) -> Dict:
    """Get stats for a user"""
    try:
        conn = sqlite3.connect(TRACKING_DB)
        c = conn.cursor()
        
        # Total scans
        c.execute("SELECT COUNT(*) FROM scans WHERE user_id = ?", (user_id,))
        total_scans = c.fetchone()[0]
        
        # Unique tokens
        c.execute("SELECT COUNT(DISTINCT mint_address) FROM scans WHERE user_id = ?", (user_id,))
        unique_tokens = c.fetchone()[0]
        
        # Recent scans
        c.execute(
            "SELECT mint_address, token_name, token_symbol, scanned_at FROM scans WHERE user_id = ? ORDER BY scanned_at DESC LIMIT 5",
            (user_id,)
        )
        recent = c.fetchall()
        
        conn.close()
        return {
            "total_scans": total_scans,
            "unique_tokens": unique_tokens,
            "recent": [{"mint": r[0], "name": r[1], "symbol": r[2], "time": r[3]} for r in recent]
        }
    except Exception as e:
        print(f"Error getting user stats: {e}")
        return {"total_scans": 0, "unique_tokens": 0, "recent": []}

def get_popular_tokens(limit: int = 10) -> List[Dict]:
    """Get most scanned tokens"""
    try:
        conn = sqlite3.connect(TRACKING_DB)
        c = conn.cursor()
        c.execute("""
            SELECT mint_address, token_name, token_symbol, COUNT(*) as scan_count
            FROM scans
            GROUP BY mint_address
            ORDER BY scan_count DESC
            LIMIT ?
        """, (limit,))
        results = c.fetchall()
        conn.close()
        return [{"mint": r[0], "name": r[1], "symbol": r[2], "scans": r[3]} for r in results]
    except Exception as e:
        print(f"Error getting popular tokens: {e}")
        return []

def get_active_users(limit: int = 10) -> List[Dict]:
    """Get most active users"""
    try:
        conn = sqlite3.connect(TRACKING_DB)
        c = conn.cursor()
        c.execute("""
            SELECT user_id, username, first_name, COUNT(*) as scan_count
            FROM scans
            GROUP BY user_id
            ORDER BY scan_count DESC
            LIMIT ?
        """, (limit,))
        results = c.fetchall()
        conn.close()
        return [{"user_id": r[0], "username": r[1], "name": r[2], "scans": r[3]} for r in results]
    except Exception as e:
        print(f"Error getting active users: {e}")
        return []

def get_recent_scans(limit: int = 20) -> List[Dict]:
    """Get recent scans across all users"""
    try:
        conn = sqlite3.connect(TRACKING_DB)
        c = conn.cursor()
        c.execute("""
            SELECT user_id, username, first_name, mint_address, token_name, token_symbol, scanned_at
            FROM scans
            ORDER BY scanned_at DESC
            LIMIT ?
        """, (limit,))
        results = c.fetchall()
        conn.close()
        return [{
            "user_id": r[0], 
            "username": r[1], 
            "name": r[2], 
            "mint": r[3], 
            "token_name": r[4], 
            "token_symbol": r[5], 
            "time": r[6]
        } for r in results]
    except Exception as e:
        print(f"Error getting recent scans: {e}")
        return []

# Watchlist functions
def add_to_watchlist(user_id: int, mint_address: str, name: str = None, symbol: str = None) -> bool:
    """Add a token to user watchlist"""
    try:
        conn = sqlite3.connect(TRACKING_DB)
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO watchlist (user_id, mint_address, token_name, token_symbol) VALUES (?, ?, ?, ?)",
            (user_id, mint_address, name, symbol)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error adding to watchlist: {e}")
        return False

def remove_from_watchlist(user_id: int, mint_address: str) -> bool:
    """Remove token from user watchlist"""
    try:
        conn = sqlite3.connect(TRACKING_DB)
        c = conn.cursor()
        c.execute("DELETE FROM watchlist WHERE user_id = ? AND mint_address = ?", (user_id, mint_address))
        deleted = c.rowcount > 0
        conn.commit()
        conn.close()
        return deleted
    except Exception as e:
        print(f"Error removing from watchlist: {e}")
        return False

def get_watchlist(user_id: int) -> List[Dict]:
    """Get user watchlist"""
    try:
        conn = sqlite3.connect(TRACKING_DB)
        c = conn.cursor()
        c.execute(
            "SELECT mint_address, token_name, token_symbol, added_at FROM watchlist WHERE user_id = ? ORDER BY added_at DESC",
            (user_id,)
        )
        results = c.fetchall()
        conn.close()
        return [{"mint": r[0], "name": r[1], "symbol": r[2], "added_at": r[3]} for r in results]
    except Exception as e:
        print(f"Error getting watchlist: {e}")
        return []

def is_watching(user_id: int, mint_address: str) -> bool:
    """Check if user is watching a token"""
    try:
        conn = sqlite3.connect(TRACKING_DB)
        c = conn.cursor()
        c.execute("SELECT 1 FROM watchlist WHERE user_id = ? AND mint_address = ?", (user_id, mint_address))
        result = c.fetchone() is not None
        conn.close()
        return result
    except:
        return False

# Initialize
init_tracking_db()
