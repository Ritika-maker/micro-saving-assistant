import sqlite3
import csv
import os
from datetime import datetime
from werkzeug.security import check_password_hash

DB_PATH = 'users.db'


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ── Core auth tables ────────────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT UNIQUE NOT NULL,
            password    TEXT NOT NULL,
            created_at  TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS analyses (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER,
            receipt_text  TEXT,
            total_spent   REAL,
            total_savings REAL,
            savings_pct   REAL,
            analysis_date TEXT,
            items_count   INTEGER,
            store_name    TEXT DEFAULT '',
            raw_data      TEXT DEFAULT '{}',
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    # ── Product catalogue (no prices here — prices live in store_prices) ───
    c.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT UNIQUE NOT NULL,
            category     TEXT DEFAULT '',
            brand        TEXT DEFAULT '',
            unit         TEXT DEFAULT '',
            health_score INTEGER DEFAULT 5,
            created_at   TEXT
        )
    ''')

    # ── Stores ──────────────────────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS stores (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            store_name TEXT UNIQUE NOT NULL,
            location   TEXT DEFAULT '',
            created_at TEXT
        )
    ''')

    # ── Per-store prices (one row per product × store, upsertable) ──────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS store_prices (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            store_id   INTEGER NOT NULL,
            price      REAL NOT NULL,
            unit_price REAL NOT NULL,
            updated_at TEXT,
            FOREIGN KEY (product_id) REFERENCES products (id),
            FOREIGN KEY (store_id)   REFERENCES stores (id),
            UNIQUE (product_id, store_id)
        )
    ''')

    conn.commit()

    # Add store_name column to analyses if upgrading from old schema
    try:
        c.execute("ALTER TABLE analyses ADD COLUMN store_name TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass  # column already exists

    # Migrate CSV → DB on first run (when products table is empty)
    c.execute("SELECT COUNT(*) FROM products")
    if c.fetchone()[0] == 0:
        _migrate_from_csv(conn)

    conn.close()


def _migrate_from_csv(conn):
    """
    One-time import: reads products2.csv (or products.csv as fallback)
    and populates products + store_prices under 'General Market'.
    """
    csv_path = None
    for candidate in ('products2.csv', 'products.csv'):
        if os.path.exists(candidate):
            csv_path = candidate
            break

    if not csv_path:
        print("[migration] No CSV found — starting with empty product catalogue.")
        return

    c = conn.cursor()
    now = datetime.now().isoformat()

    # Default store for all CSV data
    c.execute(
        "INSERT OR IGNORE INTO stores (store_name, location, created_at) VALUES (?, ?, ?)",
        ("General Market", "Kathmandu", now)
    )
    conn.commit()
    c.execute("SELECT id FROM stores WHERE store_name = 'General Market'")
    store_id = c.fetchone()[0]

    imported = 0
    with open(csv_path, newline='', encoding='utf-8') as f:
        sample = f.read(2048)
        f.seek(0)
        dialect = 'excel-tab' if sample.count('\t') > sample.count(',') else 'excel'
        reader = csv.DictReader(f, dialect=dialect)
        for row in reader:
            name = (row.get('product_name') or '').strip()
            if not name:
                continue

            try:
                price      = float(row.get('price', 0) or 0)
                unit_price = float(row.get('unit_price', price) or price)
                health     = int(float(row.get('health_score', 5) or 5))
            except (ValueError, TypeError):
                price = unit_price = 0
                health = 5

            # Insert product (ignore if already exists)
            c.execute('''
                INSERT OR IGNORE INTO products
                    (product_name, category, brand, unit, health_score, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                name,
                (row.get('category') or '').strip(),
                (row.get('brand')    or '').strip(),
                (row.get('unit')     or '').strip(),
                health, now
            ))
            conn.commit()

            c.execute("SELECT id FROM products WHERE product_name = ?", (name,))
            prod_id = c.fetchone()[0]

            # Upsert price for General Market
            c.execute('''
                INSERT INTO store_prices (product_id, store_id, price, unit_price, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(product_id, store_id) DO UPDATE SET
                    price      = excluded.price,
                    unit_price = excluded.unit_price,
                    updated_at = excluded.updated_at
            ''', (prod_id, store_id, price, unit_price, now))
            imported += 1

    conn.commit()
    print(f"[migration] Imported {imported} products from '{csv_path}' → DB (store: General Market).")


# ── Store helpers ────────────────────────────────────────────────────────────

def get_or_create_store(store_name):
    """Return store_id, inserting a new store row if it doesn't exist yet."""
    name = store_name.strip() or "General Market"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute(
        "INSERT OR IGNORE INTO stores (store_name, created_at) VALUES (?, ?)",
        (name, now)
    )
    conn.commit()
    c.execute("SELECT id FROM stores WHERE store_name = ?", (name,))
    store_id = c.fetchone()[0]
    conn.close()
    return store_id


def get_all_stores():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, store_name, location FROM stores ORDER BY store_name")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "store_name": r[1], "location": r[2] or ""} for r in rows]


# ── Product helpers ──────────────────────────────────────────────────────────

def upsert_product_price(product_name, category, brand, unit,
                         health_score, price, unit_price, store_id):
    """
    Insert product if new; upsert (insert or update) price for the given store.
    Returns the product_id.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()

    c.execute('''
        INSERT OR IGNORE INTO products
            (product_name, category, brand, unit, health_score, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (product_name, category or '', brand or '', unit or '',
          int(health_score or 5), now))
    conn.commit()

    c.execute("SELECT id FROM products WHERE product_name = ?", (product_name,))
    prod_id = c.fetchone()[0]

    c.execute('''
        INSERT INTO store_prices (product_id, store_id, price, unit_price, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(product_id, store_id) DO UPDATE SET
            price      = excluded.price,
            unit_price = excluded.unit_price,
            updated_at = excluded.updated_at
    ''', (prod_id, store_id, float(price), float(unit_price), now))

    conn.commit()
    conn.close()
    return prod_id


def search_products(query, limit=15):
    """
    Search product_name / category / brand. Returns rows with avg price across stores.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    q = f"%{query.lower()}%"
    c.execute('''
        SELECT p.product_name, p.category, p.brand, p.unit, p.health_score,
               ROUND(AVG(sp.price), 0)      AS avg_price,
               ROUND(AVG(sp.unit_price), 0) AS avg_unit_price,
               COUNT(DISTINCT sp.store_id)  AS store_count
        FROM products p
        LEFT JOIN store_prices sp ON sp.product_id = p.id
        WHERE LOWER(p.product_name) LIKE ?
           OR LOWER(p.category)     LIKE ?
           OR LOWER(p.brand)        LIKE ?
        GROUP BY p.id
        ORDER BY p.product_name
        LIMIT ?
    ''', (q, q, q, limit))
    rows = c.fetchall()
    conn.close()
    return [{
        "product_name":  r[0],
        "category":      r[1],
        "brand":         r[2],
        "unit":          r[3],
        "health_score":  r[4],
        "price":         int(r[5] or 0),
        "unit_price":    int(r[6] or 0),
        "store_count":   r[7],
    } for r in rows]


def get_store_price_comparison(product_name):
    """Return all store prices for a single product (for comparison table)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT s.store_name, sp.price, sp.unit_price, sp.updated_at
        FROM store_prices sp
        JOIN products p ON p.id = sp.product_id
        JOIN stores   s ON s.id = sp.store_id
        WHERE LOWER(p.product_name) = ?
        ORDER BY sp.unit_price ASC
    ''', (product_name.lower(),))
    rows = c.fetchall()
    conn.close()
    return [{"store_name": r[0], "price": int(r[1]),
             "unit_price": int(r[2]), "updated_at": r[3]} for r in rows]


# ── User helpers ─────────────────────────────────────────────────────────────

def register_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO users (username, password, created_at) VALUES (?, ?, ?)",
            (username, password, datetime.now().isoformat())
        )
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
    if user and check_password_hash(user[2], password):
        return (user[0], user[1])
    return None


def save_analysis(user_id, receipt_text, total_spent, total_savings,
                  savings_pct, items_count=0, store_name='', raw_data='{}'):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO analyses
            (user_id, receipt_text, total_spent, total_savings, savings_pct,
             analysis_date, items_count, store_name, raw_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, receipt_text, total_spent, total_savings, savings_pct,
          datetime.now().isoformat(), items_count, store_name, raw_data))
    conn.commit()
    conn.close()


def get_user_history(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT id, user_id, receipt_text, total_spent, total_savings,
               savings_pct, analysis_date, items_count, store_name
        FROM analyses
        WHERE user_id = ?
        ORDER BY analysis_date DESC
        LIMIT 20
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows