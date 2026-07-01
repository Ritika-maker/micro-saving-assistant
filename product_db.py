import sqlite3

DB_PATH = 'users.db'


def load_products(store_id=None):
    """
    Load all products with prices from the DB.

    - If store_id is given: use that store's price where available,
      fall back to the average across all stores for products the store
      doesn't stock yet.
    - If no store_id: use the average price across all stores.

    Returns a list of dicts that matches the old CSV structure exactly,
    so price_comparison.py / recommendation_engine.py need no changes.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if store_id:
        c.execute('''
            SELECT
                p.id,
                p.product_name,
                p.category,
                p.brand,
                p.unit,
                p.health_score,
                COALESCE(sp_specific.price,      AVG(sp_all.price))      AS price,
                COALESCE(sp_specific.unit_price, AVG(sp_all.unit_price)) AS unit_price
            FROM products p
            LEFT JOIN store_prices sp_specific
                ON  sp_specific.product_id = p.id
                AND sp_specific.store_id   = ?
            LEFT JOIN store_prices sp_all
                ON  sp_all.product_id = p.id
            GROUP BY p.id
        ''', (store_id,))
    else:
        c.execute('''
            SELECT
                p.id,
                p.product_name,
                p.category,
                p.brand,
                p.unit,
                p.health_score,
                COALESCE(AVG(sp.price),      0) AS price,
                COALESCE(AVG(sp.unit_price), 0) AS unit_price
            FROM products p
            LEFT JOIN store_prices sp ON sp.product_id = p.id
            GROUP BY p.id
        ''')

    rows = c.fetchall()
    conn.close()

    return [{
        "product_name": r["product_name"],
        "category":     r["category"]     or "",
        "brand":        r["brand"]        or "",
        "unit":         r["unit"]         or "",
        "health_score": r["health_score"] or 5,
        "price":        round(r["price"]      or 0),
        "unit_price":   round(r["unit_price"] or 0),
    } for r in rows]


def load_products_with_store_prices():
    """
    Returns every product with the full list of per-store prices.
    Used by price_comparison.py to build the store-to-store comparison
    shown inside recommendation cards.

    Return shape:
    [
      {
        "product_name": "Amul Milk 1L",
        "category": "Dairy",
        "brand": "Amul",
        "unit": "liter",
        "health_score": 8,
        "stores": [
          {"store_id": 1, "store_name": "General Market", "price": 90, "unit_price": 90},
          {"store_id": 2, "store_name": "Bhatbhateni",    "price": 85, "unit_price": 85},
        ]
      },
      ...
    ]
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute('''
        SELECT
            p.product_name,
            p.category,
            p.brand,
            p.unit,
            p.health_score,
            sp.price,
            sp.unit_price,
            s.id   AS store_id,
            s.store_name
        FROM products p
        JOIN store_prices sp ON sp.product_id = p.id
        JOIN stores       s  ON s.id          = sp.store_id
        ORDER BY p.product_name, sp.unit_price ASC
    ''')

    rows = c.fetchall()
    conn.close()

    # Group by product_name
    from collections import OrderedDict
    grouped = OrderedDict()
    for r in rows:
        key = r["product_name"]
        if key not in grouped:
            grouped[key] = {
                "product_name": r["product_name"],
                "category":     r["category"]     or "",
                "brand":        r["brand"]        or "",
                "unit":         r["unit"]         or "",
                "health_score": r["health_score"] or 5,
                "stores": [],
            }
        grouped[key]["stores"].append({
            "store_id":   r["store_id"],
            "store_name": r["store_name"],
            "price":      round(r["price"]),
            "unit_price": round(r["unit_price"]),
        })

    return list(grouped.values())


if __name__ == "__main__":
    # Quick smoke-test: python product_db.py
    import json
    products = load_products()
    print(f"Loaded {len(products)} products from DB")
    print(json.dumps(products[:3], indent=2))

    with_stores = load_products_with_store_prices()
    print(f"\nWith store prices: {len(with_stores)} products")
    print(json.dumps(with_stores[:2], indent=2))