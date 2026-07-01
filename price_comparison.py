import pandas as pd
from product_db import load_products_with_store_prices

def find_alternatives(item, products_df, item_brand=None, current_store=None):
    item_name_lower = item['name'].lower()
    user_price = float(item['price'])
    category = None
    matched_product_name = None

    for prod in products_df.to_dict('records'):
        prod_name_lower = prod['product_name'].lower()
        if (prod_name_lower in item_name_lower or
            item_name_lower in prod_name_lower or
            any(word in prod_name_lower for word in item_name_lower.split() if len(word) > 3)):
            category = prod['category']
            matched_product_name = prod['product_name']
            break

    if not category:
        return []

    alts = products_df[products_df['category'] == category].copy()

    # Skip same brand only for real named brands
    if item_brand and item_brand.strip().lower() != 'generic':
        alts = alts[alts['brand'].str.lower() != item_brand.lower()]

    alts = alts.copy()
    alts['_unit_price'] = alts.apply(
        lambda r: float(r.get('unit_price') or r.get('price') or 0), axis=1
    )
    alts['savings'] = (user_price - alts['_unit_price']) / user_price * 100

    # Remove same product if user didn't overpay
    if matched_product_name:
        same_mask = alts['product_name'].str.lower() == matched_product_name.lower()
        same_prices = alts.loc[same_mask, '_unit_price']
        if not same_prices.empty and user_price <= float(same_prices.iloc[0]) * 1.05:
            alts = alts[~same_mask]

    alts = alts[alts['savings'] > 5]
    alts = alts.sort_values('savings', ascending=False)
    results = alts.head(3).to_dict('records')

    # Enrich with store-level prices
    all_with_stores = load_products_with_store_prices()
    store_map = {p['product_name']: p['stores'] for p in all_with_stores}

    for alt in results:
        stores_data = store_map.get(alt['product_name'], [])
        if stores_data:
            best  = min(stores_data, key=lambda s: s['unit_price'])
            worst = max(stores_data, key=lambda s: s['unit_price'])
            alt['store_prices']      = stores_data
            alt['best_store']        = best['store_name']
            alt['best_store_price']  = best['unit_price']
            alt['worst_store']       = worst['store_name']
            alt['price_range']       = f"NPR {best['unit_price']} – {worst['unit_price']}"
        else:
            alt['store_prices']     = []
            alt['best_store']       = current_store or 'General Market'
            alt['best_store_price'] = int(alt.get('unit_price') or alt.get('price') or 0)
            alt['price_range']      = None

    return results