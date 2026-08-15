import sqlite3
import csv
import json
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

    # ── Price history (append-only log of every price we observe) ───────────
    # store_prices keeps the CURRENT price; this table keeps the trail.
    c.execute('''
        CREATE TABLE IF NOT EXISTS price_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id  INTEGER NOT NULL,
            store_id    INTEGER NOT NULL,
            price       REAL NOT NULL,
            unit_price  REAL NOT NULL,
            recorded_at TEXT,
            source      TEXT DEFAULT 'receipt',
            FOREIGN KEY (product_id) REFERENCES products (id),
            FOREIGN KEY (store_id)   REFERENCES stores (id)
        )
    ''')

    # ── Structured analysis results ─────────────────────────────────────────
    # analyses.raw_data still stores the full JSON payload the results page
    # renders; these two tables store the same items in queryable form so
    # statistics can be worked out in SQL instead of by re-parsing JSON.
    c.execute('''
        CREATE TABLE IF NOT EXISTS analysis_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id     INTEGER NOT NULL,
            product_id      INTEGER,
            original_name   TEXT,
            normalized_name TEXT,
            quantity        INTEGER DEFAULT 1,
            unit            TEXT DEFAULT '',
            price           REAL,
            unit_price      REAL,
            confidence      INTEGER DEFAULT 0,
            FOREIGN KEY (analysis_id) REFERENCES analyses (id),
            FOREIGN KEY (product_id)  REFERENCES products (id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS recommendations (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_item_id       INTEGER NOT NULL,
            alternative_product_id INTEGER,
            alternative_store_id   INTEGER,
            alternative_name       TEXT,
            alternative_price      REAL,
            savings_amount         REAL,
            savings_percentage     REAL,
            recommendation_score   REAL,
            reason                 TEXT,
            rank                   INTEGER DEFAULT 0,
            FOREIGN KEY (analysis_item_id)       REFERENCES analysis_items (id),
            FOREIGN KEY (alternative_product_id) REFERENCES products (id),
            FOREIGN KEY (alternative_store_id)   REFERENCES stores (id)
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_analysis_items_analysis '
              'ON analysis_items (analysis_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_recommendations_item '
              'ON recommendations (analysis_item_id)')

    # ── Optional monthly savings goal, one row per user per month ───────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS savings_goals (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            month         INTEGER NOT NULL,
            year          INTEGER NOT NULL,
            target_amount REAL NOT NULL,
            created_at    TEXT,
            updated_at    TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE (user_id, month, year)
        )
    ''')

    conn.commit()

    # Columns added after the first release. Each ALTER is tried separately so
    # an existing database is upgraded in place without losing data.
    for statement in (
        "ALTER TABLE analyses ADD COLUMN store_name TEXT DEFAULT ''",
        "ALTER TABLE analyses ADD COLUMN actual_savings REAL DEFAULT 0",
    ):
        try:
            c.execute(statement)
            conn.commit()
        except Exception:
            pass  # column already exists

    # Migrate CSV → DB on first run (when products table is empty)
    c.execute("SELECT COUNT(*) FROM products")
    if c.fetchone()[0] == 0:
        _migrate_from_csv(conn)

    # One-time backfill of the structured tables for analyses that were saved
    # before they existed. Runs only while analysis_items is completely empty.
    c.execute("SELECT COUNT(*) FROM analysis_items")
    if c.fetchone()[0] == 0:
        c.execute("SELECT COUNT(*) FROM analyses")
        if c.fetchone()[0] > 0:
            conn.close()
            _backfill_analysis_items()
            return

    conn.close()


def _backfill_analysis_items():
    """
    Rebuild analysis_items/recommendations from the JSON stored on older
    analyses. Only fills gaps - no existing row is changed or deleted.
    """
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute('''
        SELECT id, raw_data FROM analyses
        WHERE raw_data IS NOT NULL AND raw_data != '{}'
        ORDER BY id
    ''').fetchall()
    conn.close()

    filled = 0
    for analysis_id, raw in rows:
        try:
            data = json.loads(raw or '{}')
        except (TypeError, ValueError):
            continue
        items = data.get('items') or []
        if not items:
            continue
        save_analysis_items(analysis_id, items, data.get('recommendations') or {})
        filled += 1

    if filled:
        print(f"[migration] Backfilled structured items for {filled} existing analyses.")


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
    print(f"[migration] Imported {imported} products from '{csv_path}' -> DB (store: General Market).")


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
                         health_score, price, unit_price, store_id,
                         source='receipt'):
    """
    Insert product if new; upsert (insert or update) price for the given store,
    and append the observation to price_history.
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

    # Keep the trail of observed prices (store_prices keeps only the latest)
    c.execute('''
        INSERT INTO price_history
            (product_id, store_id, price, unit_price, recorded_at, source)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (prod_id, store_id, float(price), float(unit_price), now, source))

    conn.commit()
    conn.close()
    return prod_id


# ── Price freshness & history ────────────────────────────────────────────────

FRESHNESS_FRESH_DAYS  = 2      # updated today / yesterday
FRESHNESS_RECENT_DAYS = 14     # updated within a fortnight


def price_freshness(updated_at):
    """
    Describe how old a stored price is.
    Returns (level, label): 'fresh' / 'recent' / 'older' / 'unknown'.
    Prices come from the stored dataset and past receipts - never live feeds.
    """
    if not updated_at:
        return 'unknown', 'Date unknown'
    try:
        stamp = datetime.fromisoformat(str(updated_at))
    except ValueError:
        return 'unknown', 'Date unknown'

    days = (datetime.now() - stamp).days
    if days <= 0:
        return 'fresh', 'Updated today'
    if days == 1:
        return 'fresh', 'Updated yesterday'
    if days <= FRESHNESS_RECENT_DAYS:
        return ('recent' if days > FRESHNESS_FRESH_DAYS else 'fresh',
                f'Updated {days} days ago')
    if days < 60:
        return 'older', f'Updated {days} days ago'
    return 'older', f'Updated {days // 30} months ago'


def get_price_history(product_name, store_id=None, limit=60):
    """Recorded price observations for a product, oldest first."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    sql = '''
        SELECT ph.price, ph.unit_price, ph.recorded_at, ph.source,
               s.store_name, s.id AS store_id
        FROM price_history ph
        JOIN products p ON p.id = ph.product_id
        JOIN stores   s ON s.id = ph.store_id
        WHERE LOWER(p.product_name) = ?
    '''
    params = [product_name.lower()]
    if store_id:
        sql += " AND ph.store_id = ?"
        params.append(store_id)
    sql += " ORDER BY ph.recorded_at ASC LIMIT ?"
    params.append(limit)

    rows = c.execute(sql, params).fetchall()
    conn.close()
    return [{
        "price":       round(r["price"]),
        "unit_price":  round(r["unit_price"]),
        "recorded_at": r["recorded_at"],
        "date":        (r["recorded_at"] or '')[:10],
        "source":      r["source"],
        "store_name":  r["store_name"],
        "store_id":    r["store_id"],
    } for r in rows]


# ── Basket-level store comparison ────────────────────────────────────────────

def compare_basket_across_stores(product_names, min_coverage=0.6):
    """
    Estimate what the same basket would cost at each store.

    Missing products are never counted as zero: a store is reported with the
    number of items it can price, and stores below `min_coverage` are marked
    as having insufficient price data.
    """
    names = [n for n in {(n or '').strip().lower() for n in product_names} if n]
    if not names:
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    placeholders = ','.join('?' * len(names))
    rows = c.execute(f'''
        SELECT s.id AS store_id, s.store_name, p.product_name,
               sp.unit_price, sp.updated_at
        FROM store_prices sp
        JOIN products p ON p.id = sp.product_id
        JOIN stores   s ON s.id = sp.store_id
        WHERE LOWER(p.product_name) IN ({placeholders})
    ''', names).fetchall()
    conn.close()

    stores = {}
    for r in rows:
        store = stores.setdefault(r["store_id"], {
            "store_id": r["store_id"], "store_name": r["store_name"],
            "total": 0.0, "priced_items": [], "last_updated": None,
        })
        store["total"] += float(r["unit_price"] or 0)
        store["priced_items"].append(r["product_name"])
        if not store["last_updated"] or (r["updated_at"] or '') > store["last_updated"]:
            store["last_updated"] = r["updated_at"]

    results = []
    for store in stores.values():
        covered = len(store["priced_items"])
        coverage = covered / len(names)
        level, label = price_freshness(store["last_updated"])
        results.append({
            "store_id":        store["store_id"],
            "store_name":      store["store_name"],
            "total":           int(round(store["total"])),
            "items_priced":    covered,
            "items_requested": len(names),
            "coverage_pct":    round(coverage * 100),
            "sufficient_data": coverage >= min_coverage,
            "freshness_level": level,
            "freshness_label": label,
        })

    # Cheapest complete baskets first, stores with gaps afterwards
    results.sort(key=lambda s: (not s["sufficient_data"], s["total"]))
    return results


# ── Spending analytics (built from the stored analyses) ──────────────────────

def get_spending_summary(user_id):
    """Headline numbers for the dashboard cards."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute('''
        SELECT COUNT(*), COALESCE(SUM(total_spent), 0),
               COALESCE(SUM(total_savings), 0), COALESCE(AVG(savings_pct), 0),
               COALESCE(SUM(actual_savings), 0)
        FROM analyses WHERE user_id = ?
    ''', (user_id,)).fetchone()
    conn.close()
    return {
        "receipts":        row[0],
        "total_spent":     int(round(row[1])),
        "total_savings":   int(round(row[2])),
        "avg_savings_pct": round(row[3], 1),
        "actual_savings":  int(round(row[4] or 0)),
    }


def get_monthly_summary(user_id, year=None, month=None):
    """Spending/savings for one month (defaults to the current month)."""
    now = datetime.now()
    year = year or now.year
    month = month or now.month
    prefix = f"{year:04d}-{month:02d}"

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute('''
        SELECT COUNT(*), COALESCE(SUM(total_spent), 0),
               COALESCE(SUM(total_savings), 0), COALESCE(AVG(savings_pct), 0),
               COALESCE(SUM(actual_savings), 0)
        FROM analyses
        WHERE user_id = ? AND substr(analysis_date, 1, 7) = ?
    ''', (user_id, prefix)).fetchone()
    conn.close()
    return {
        "year": year, "month": month, "label": f"{prefix}",
        "receipts":        row[0],
        "total_spent":     int(round(row[1])),
        "total_savings":   int(round(row[2])),
        "avg_savings_pct": round(row[3], 1),
        "actual_savings":  int(round(row[4] or 0)),
    }


def get_spending_by_store(user_id, limit=8):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute('''
        SELECT COALESCE(NULLIF(store_name, ''), 'Unknown store') AS store,
               COUNT(*), COALESCE(SUM(total_spent), 0), COALESCE(SUM(total_savings), 0)
        FROM analyses
        WHERE user_id = ?
        GROUP BY store
        ORDER BY SUM(total_spent) DESC
        LIMIT ?
    ''', (user_id, limit)).fetchall()
    conn.close()
    return [{"store_name": r[0], "receipts": r[1],
             "total_spent": int(round(r[2])), "total_savings": int(round(r[3]))}
            for r in rows]


def get_savings_trend(user_id, limit=12):
    """Most recent analyses in chronological order, for the trend chart."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute('''
        SELECT analysis_date, total_spent, total_savings, savings_pct
        FROM analyses WHERE user_id = ?
        ORDER BY analysis_date DESC LIMIT ?
    ''', (user_id, limit)).fetchall()
    conn.close()
    return [{"date": (r[0] or '')[:10], "spent": int(round(r[1] or 0)),
             "savings": int(round(r[2] or 0)), "savings_pct": round(r[3] or 0, 1)}
            for r in reversed(rows)]


def get_top_savings_opportunities(user_id, limit=5, scan_analyses=20):
    """
    Best per-item savings seen across the user's recent analyses.

    Uses the structured analysis_items/recommendations tables. Analyses saved
    before those tables existed are still included by reading their stored
    JSON, so the dashboard shows a complete picture after upgrading.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    rows = c.execute('''
        SELECT ai.normalized_name AS item, ai.unit_price, ai.price,
               r.alternative_name, r.alternative_price, r.savings_amount,
               r.savings_percentage, a.store_name, s.store_name AS best_store
        FROM analysis_items ai
        JOIN analyses a       ON a.id = ai.analysis_id
        JOIN recommendations r ON r.analysis_item_id = ai.id AND r.rank = 0
        LEFT JOIN stores s     ON s.id = r.alternative_store_id
        WHERE a.user_id = ? AND r.savings_amount > 0
        ORDER BY r.savings_amount DESC
    ''', (user_id,)).fetchall()
    conn.close()

    best = {}
    for r in rows:
        name = r["item"]
        if name not in best:      # rows are already ordered by saving, desc
            best[name] = {
                "item":           name,
                "current_price":  int(round(r["unit_price"] or r["price"] or 0)),
                "alternative":    r["alternative_name"] or '',
                "alt_price":      int(round(r["alternative_price"] or 0)),
                "savings_amount": int(round(r["savings_amount"] or 0)),
                "savings_pct":    round(r["savings_percentage"] or 0, 1),
                "store_name":     r["best_store"] or r["store_name"] or '',
            }

    legacy = _legacy_savings_opportunities(user_id, scan_analyses)
    for name, opportunity in legacy.items():
        if name not in best or opportunity['savings_amount'] > best[name]['savings_amount']:
            best[name] = opportunity

    return sorted(best.values(), key=lambda o: o['savings_amount'], reverse=True)[:limit]


def _legacy_savings_opportunities(user_id, scan_analyses=20):
    """Same information for analyses that only have the stored JSON payload."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute('''
        SELECT raw_data, store_name FROM analyses
        WHERE user_id = ? AND raw_data IS NOT NULL AND raw_data != '{}'
        ORDER BY analysis_date DESC LIMIT ?
    ''', (user_id, scan_analyses)).fetchall()
    conn.close()

    best = {}
    for raw, store_name in rows:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for item in data.get('items', []):
            recs = (data.get('recommendations') or {}).get(item.get('name'), [])
            if not recs:
                continue
            rec = recs[0]
            saving = rec.get('savings_amount')
            if saving is None:          # analyses saved before this feature
                saving = max(0, round(item.get('price', 0) - rec.get('alt_price', 0)))
            if saving <= 0:
                continue
            name = item.get('product_name') or item.get('name', '')
            current = best.get(name)
            if not current or saving > current['savings_amount']:
                best[name] = {
                    "item":           name,
                    "current_price":  int(round(item.get('unit_price') or item.get('price', 0))),
                    "alternative":    rec.get('alternative', ''),
                    "alt_price":      rec.get('alt_price', 0),
                    "savings_amount": int(round(saving)),
                    "savings_pct":    rec.get('savings_pct', 0),
                    "store_name":     rec.get('best_store') or store_name or '',
                }

    return best


# ── Savings goal ─────────────────────────────────────────────────────────────

def set_savings_goal(user_id, target_amount, month=None, year=None):
    now = datetime.now()
    month = int(month or now.month)
    year = int(year or now.year)
    stamp = now.isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO savings_goals (user_id, month, year, target_amount, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, month, year) DO UPDATE SET
            target_amount = excluded.target_amount,
            updated_at    = excluded.updated_at
    ''', (user_id, month, year, float(target_amount), stamp, stamp))
    conn.commit()
    conn.close()
    return get_savings_goal(user_id, month, year)


def get_savings_goal(user_id, month=None, year=None):
    """
    The user's goal for a month plus progress.

    Progress is measured against ACTUAL savings (recommendations the user
    confirmed using); potential savings are reported separately so the two are
    never confused.
    """
    now = datetime.now()
    month = int(month or now.month)
    year = int(year or now.year)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute('''
        SELECT target_amount FROM savings_goals
        WHERE user_id = ? AND month = ? AND year = ?
    ''', (user_id, month, year)).fetchone()
    conn.close()

    summary = get_monthly_summary(user_id, year, month)
    if not row:
        return {"has_goal": False, "month": month, "year": year,
                "target_amount": 0, "actual_savings": summary["actual_savings"],
                "potential_savings": summary["total_savings"],
                "progress_pct": 0, "remaining": 0}

    target = float(row[0])
    actual = summary["actual_savings"]
    progress = (actual / target * 100) if target > 0 else 0
    return {
        "has_goal":          True,
        "month":             month,
        "year":              year,
        "target_amount":     int(round(target)),
        "actual_savings":    actual,
        "potential_savings": summary["total_savings"],
        "progress_pct":      round(min(progress, 100), 1),
        "remaining":         max(0, int(round(target - actual))),
    }


def record_actual_savings(analysis_id, user_id, amount):
    """
    Called when the user confirms they actually used a recommendation.
    Nothing is counted as actual savings unless this is called.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE analyses
        SET actual_savings = COALESCE(actual_savings, 0) + ?
        WHERE id = ? AND user_id = ?
    ''', (float(amount), analysis_id, user_id))
    changed = c.rowcount
    conn.commit()
    conn.close()
    return changed > 0


def get_analysis(analysis_id, user_id):
    """One analysis with its stored JSON payload, or None."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    row = c.execute('''
        SELECT id, receipt_text, total_spent, total_savings, savings_pct,
               analysis_date, items_count, store_name, raw_data,
               COALESCE(actual_savings, 0) AS actual_savings
        FROM analyses WHERE id = ? AND user_id = ?
    ''', (analysis_id, user_id)).fetchone()
    conn.close()
    if not row:
        return None

    analysis = dict(row)
    try:
        analysis['data'] = json.loads(analysis['raw_data'] or '{}')
    except (TypeError, ValueError):
        analysis['data'] = {}
    return analysis


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
    analysis_id = c.lastrowid
    conn.commit()
    conn.close()
    return analysis_id


def save_analysis_items(analysis_id, items, recommendations):
    """
    Store the analysed items and their recommendations in structured form.

    `items` are the item dicts produced by the analysis pipeline and
    `recommendations` is the {item name: [rec, ...]} mapping. Products and
    stores are looked up by name; an unknown name simply stores NULL rather
    than inventing a row.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    product_ids = {name.lower(): pid for pid, name in
                   c.execute("SELECT id, product_name FROM products")}
    store_ids = {name.lower(): sid for sid, name in
                 c.execute("SELECT id, store_name FROM stores")}

    for item in items:
        normalized = item.get('normalized') or item.get('product_name') or item.get('name', '')
        c.execute('''
            INSERT INTO analysis_items
                (analysis_id, product_id, original_name, normalized_name,
                 quantity, unit, price, unit_price, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (analysis_id,
              product_ids.get(normalized.lower()),
              item.get('name', ''),
              normalized,
              int(item.get('quantity') or 1),
              item.get('unit', ''),
              float(item.get('price') or 0),
              float(item.get('unit_price') or item.get('price') or 0),
              int(item.get('confidence') or 0)))
        item_id = c.lastrowid

        for rank, rec in enumerate(recommendations.get(item.get('name'), [])):
            c.execute('''
                INSERT INTO recommendations
                    (analysis_item_id, alternative_product_id, alternative_store_id,
                     alternative_name, alternative_price, savings_amount,
                     savings_percentage, recommendation_score, reason, rank)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (item_id,
                  product_ids.get((rec.get('alternative') or '').lower()),
                  store_ids.get((rec.get('best_store') or '').lower()),
                  rec.get('alternative', ''),
                  float(rec.get('alt_price') or 0),
                  float(rec.get('savings_amount') or 0),
                  float(rec.get('savings_pct') or 0),
                  float(rec.get('recommendation_score') or 0),
                  rec.get('reason', ''),
                  rank))

    conn.commit()
    conn.close()


def get_analysis_items(analysis_id):
    """
    Structured items + recommendations for one analysis.
    Returns [] for analyses saved before these tables existed, so callers can
    fall back to the stored JSON.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    items = [dict(r) for r in c.execute('''
        SELECT * FROM analysis_items WHERE analysis_id = ? ORDER BY id
    ''', (analysis_id,))]

    if items:
        placeholders = ','.join('?' * len(items))
        recs = c.execute(f'''
            SELECT * FROM recommendations
            WHERE analysis_item_id IN ({placeholders})
            ORDER BY analysis_item_id, rank
        ''', [i['id'] for i in items]).fetchall()
        by_item = {}
        for rec in recs:
            by_item.setdefault(rec['analysis_item_id'], []).append(dict(rec))
        for item in items:
            item['recommendations'] = by_item.get(item['id'], [])

    conn.close()
    return items


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