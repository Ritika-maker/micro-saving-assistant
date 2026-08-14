"""
Load the demo dataset into a SQLite database.

    python dataset/load_demo_dataset.py                 # -> demo.db (safe default)
    python dataset/load_demo_dataset.py --db users.db   # -> the app database

The default target is demo.db so that running this script can never overwrite
prices in the live application database by accident. Pass --db users.db
deliberately when you want the app to use the larger demo catalogue.

Existing products/prices are updated, not deleted: the loader reuses
models.upsert_product_price(), the same function the app uses, so every price
is also appended to price_history with source='demo-dataset'.
"""

import argparse
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import models


def load(db_path):
    models.DB_PATH = db_path
    models.init_db()

    products = {}
    with open(os.path.join(HERE, 'products.csv'), newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            products[row['product_name']] = row

    stores = {}
    with open(os.path.join(HERE, 'stores.csv'), newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            stores[row['store_name']] = models.get_or_create_store(row['store_name'])

    loaded = 0
    with open(os.path.join(HERE, 'store_prices.csv'), newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            product = products.get(row['product_name'])
            store_id = stores.get(row['store_name'])
            if not product or not store_id:
                continue
            models.upsert_product_price(
                product_name = product['product_name'],
                category     = product['category'],
                brand        = product['brand'],
                unit         = product['unit'],
                health_score = int(product['health_score']),
                price        = float(row['price']),
                unit_price   = float(row['unit_price']),
                store_id     = store_id,
                source       = 'demo-dataset',
            )
            loaded += 1

    print(f"Loaded {len(products)} demo products and {loaded} store prices into {db_path}")
    print("Reminder: these are development/demo values, not observed market prices.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='demo.db',
                        help="target database file (default: demo.db)")
    args = parser.parse_args()
    load(args.db)
