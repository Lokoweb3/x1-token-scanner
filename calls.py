import sqlite3
from datetime import datetime
from typing import List, Dict, Optional

CALLS_DB = "calls.db"

def init_calls_db():
    """Initialize the calls database"""
    conn = sqlite3.connect(CALLS_DB)
    c = conn.cursor()
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            mint_address TEXT,
            token_name TEXT,
            token_symbol TEXT,
            entry_price REAL,
            entry_mcap REAL,
            called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, mint_address)
        )
    """)
    
    conn.commit()
    conn.close()

def record_call(user_id: int, username: str, mint_address: str, token_name: str, token_symbol: str, entry_price: float, entry_mcap: float) -> bool:
    """Record a call (entry point)"""
    try:
        conn = sqlite3.connect(CALLS_DB)
        c = conn.cursor()
        c.execute(
            """INSERT OR REPLACE INTO calls 
               (user_id, username, mint_address, token_name, token_symbol, entry_price, entry_mcap, called_at) 
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (user_id, username, mint_address, token_name, token_symbol, entry_price, entry_mcap)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error recording call: {e}")
        return False

def get_user_calls(user_id: int) -> List[Dict]:
    """Get all calls for a user"""
    try:
        conn = sqlite3.connect(CALLS_DB)
        c = conn.cursor()
        c.execute(
            """SELECT mint_address, token_name, token_symbol, entry_price, entry_mcap, called_at 
               FROM calls WHERE user_id = ? ORDER BY called_at DESC""",
            (user_id,)
        )
        results = c.fetchall()
        conn.close()
        return [{
            "mint": r[0],
            "name": r[1],
            "symbol": r[2],
            "entry_price": r[3],
            "entry_mcap": r[4],
            "called_at": r[5]
        } for r in results]
    except Exception as e:
        print(f"Error getting calls: {e}")
        return []

def get_call(user_id: int, mint_address: str) -> Optional[Dict]:
    """Get a specific call"""
    try:
        conn = sqlite3.connect(CALLS_DB)
        c = conn.cursor()
        c.execute(
            """SELECT token_name, token_symbol, entry_price, entry_mcap, called_at 
               FROM calls WHERE user_id = ? AND mint_address = ?""",
            (user_id, mint_address)
        )
        r = c.fetchone()
        conn.close()
        if r:
            return {
                "name": r[0],
                "symbol": r[1],
                "entry_price": r[2],
                "entry_mcap": r[3],
                "called_at": r[4]
            }
        return None
    except:
        return None

def remove_call(user_id: int, mint_address: str) -> bool:
    """Remove a call"""
    try:
        conn = sqlite3.connect(CALLS_DB)
        c = conn.cursor()
        c.execute("DELETE FROM calls WHERE user_id = ? AND mint_address = ?", (user_id, mint_address))
        deleted = c.rowcount > 0
        conn.commit()
        conn.close()
        return deleted
    except:
        return False

def get_all_calls() -> List[Dict]:
    """Get all calls (for leaderboard)"""
    try:
        conn = sqlite3.connect(CALLS_DB)
        c = conn.cursor()
        c.execute(
            """SELECT user_id, username, mint_address, token_name, token_symbol, entry_price, entry_mcap, called_at 
               FROM calls ORDER BY called_at DESC"""
        )
        results = c.fetchall()
        conn.close()
        return [{
            "user_id": r[0],
            "username": r[1],
            "mint": r[2],
            "name": r[3],
            "symbol": r[4],
            "entry_price": r[5],
            "entry_mcap": r[6],
            "called_at": r[7]
        } for r in results]
    except:
        return []

# Initialize
init_calls_db()
