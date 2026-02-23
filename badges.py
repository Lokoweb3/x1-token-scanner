import sqlite3
from datetime import datetime
from typing import List, Dict, Optional

BADGES_DB = "badges.db"

def init_badges_db():
    """Initialize the badges database"""
    conn = sqlite3.connect(BADGES_DB)
    c = conn.cursor()
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS badges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            badge_type TEXT,
            token_symbol TEXT,
            token_mint TEXT,
            x_achieved REAL,
            earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, token_mint, badge_type)
        )
    """)
    
    conn.commit()
    conn.close()

BADGE_LEVELS = {
    "2x": {"emoji": "🥉", "name": "Bronze", "threshold": 2.0},
    "5x": {"emoji": "🥈", "name": "Silver", "threshold": 5.0},
    "10x": {"emoji": "🥇", "name": "Gold", "threshold": 10.0},
    "25x": {"emoji": "💎", "name": "Diamond", "threshold": 25.0},
    "50x": {"emoji": "👑", "name": "Crown", "threshold": 50.0},
    "100x": {"emoji": "🚀", "name": "Legend", "threshold": 100.0},
}

def check_and_award_badge(user_id: int, username: str, token_symbol: str, token_mint: str, x_mult: float) -> Optional[Dict]:
    """Check if user earned a new badge and award it"""
    try:
        conn = sqlite3.connect(BADGES_DB)
        c = conn.cursor()
        
        new_badge = None
        for badge_type, badge_info in BADGE_LEVELS.items():
            if x_mult >= badge_info["threshold"]:
                c.execute(
                    "SELECT 1 FROM badges WHERE user_id = ? AND token_mint = ? AND badge_type = ?",
                    (user_id, token_mint, badge_type)
                )
                if not c.fetchone():
                    c.execute(
                        "INSERT INTO badges (user_id, username, badge_type, token_symbol, token_mint, x_achieved) VALUES (?, ?, ?, ?, ?, ?)",
                        (user_id, username, badge_type, token_symbol, token_mint, x_mult)
                    )
                    new_badge = {
                        "type": badge_type,
                        "emoji": badge_info["emoji"],
                        "name": badge_info["name"],
                        "threshold": badge_info["threshold"],
                        "x_achieved": x_mult,
                        "token_symbol": token_symbol
                    }
        
        conn.commit()
        conn.close()
        return new_badge
    except Exception as e:
        print(f"Error awarding badge: {e}")
        return None

def get_user_badges(user_id: int) -> List[Dict]:
    """Get all badges for a user"""
    try:
        conn = sqlite3.connect(BADGES_DB)
        c = conn.cursor()
        c.execute(
            """SELECT badge_type, token_symbol, token_mint, x_achieved, earned_at 
               FROM badges WHERE user_id = ? ORDER BY x_achieved DESC""",
            (user_id,)
        )
        results = c.fetchall()
        conn.close()
        
        badges = []
        for r in results:
            badge_info = BADGE_LEVELS.get(r[0], {})
            badges.append({
                "type": r[0],
                "emoji": badge_info.get("emoji", "🏆"),
                "name": badge_info.get("name", "Badge"),
                "token_symbol": r[1],
                "token_mint": r[2],
                "x_achieved": r[3],
                "earned_at": r[4]
            })
        return badges
    except Exception as e:
        print(f"Error getting badges: {e}")
        return []

def get_badge_leaderboard() -> List[Dict]:
    """Get users ranked by badge count"""
    try:
        conn = sqlite3.connect(BADGES_DB)
        c = conn.cursor()
        c.execute("""
            SELECT user_id, username, 
                   COUNT(*) as total_badges,
                   SUM(CASE WHEN badge_type = '100x' THEN 1 ELSE 0 END) as legends,
                   SUM(CASE WHEN badge_type = '50x' THEN 1 ELSE 0 END) as crowns,
                   SUM(CASE WHEN badge_type = '25x' THEN 1 ELSE 0 END) as diamonds,
                   SUM(CASE WHEN badge_type = '10x' THEN 1 ELSE 0 END) as golds,
                   SUM(CASE WHEN badge_type = '5x' THEN 1 ELSE 0 END) as silvers,
                   SUM(CASE WHEN badge_type = '2x' THEN 1 ELSE 0 END) as bronzes,
                   MAX(x_achieved) as best_x
            FROM badges
            GROUP BY user_id
            ORDER BY legends DESC, crowns DESC, diamonds DESC, golds DESC, silvers DESC, bronzes DESC
            LIMIT 10
        """)
        results = c.fetchall()
        conn.close()
        
        return [{
            "user_id": r[0],
            "username": r[1],
            "total_badges": r[2],
            "legends": r[3],
            "crowns": r[4],
            "diamonds": r[5],
            "golds": r[6],
            "silvers": r[7],
            "bronzes": r[8],
            "best_x": r[9]
        } for r in results]
    except Exception as e:
        print(f"Error getting badge leaderboard: {e}")
        return []

# Initialize
init_badges_db()
