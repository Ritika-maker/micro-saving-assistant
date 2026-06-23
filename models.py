import sqlite3
from datetime import datetime
import os
from werkzeug.security import check_password_hash

DB_PATH = 'users.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT
        )
    ''')
    
    # Analysis history
    c.execute('''
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            receipt_text TEXT,
            total_spent REAL,
            total_savings REAL,
            savings_pct REAL,
            analysis_date TEXT,
            items_count INTEGER,
            raw_data TEXT,  -- JSON string for full details
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()

def register_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password, created_at) VALUES (?, ?, ?)",
                  (username, password, datetime.now().isoformat()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, password FROM users WHERE username=?", (username,))
    user = c.fetchone()
    conn.close()
    if user and check_password_hash(user[2], password):  # Need to import
        return (user[0], user[1])
    return None

def save_analysis(user_id, receipt_text, total_spent, total_savings, savings_pct, items_count=0, raw_data='{}'):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO analyses (user_id, receipt_text, total_spent, total_savings, savings_pct, 
                             analysis_date, items_count, raw_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, receipt_text, total_spent, total_savings, savings_pct, 
          datetime.now().isoformat(), items_count, raw_data))
    conn.commit()
    conn.close()

def get_user_history(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, user_id, receipt_text, total_spent, total_savings, savings_pct, 
               analysis_date, items_count 
        FROM analyses 
        WHERE user_id=? ORDER BY analysis_date DESC LIMIT 10
    """, (user_id,))
    history = c.fetchall()
    conn.close()
    return history