import pandas as pd
from product_db import load_products_with_store_prices
from receipt_processor import match_item
from unit_utils import parse_quantity_and_unit, units_comparable, size_ratio

MIN_SAVINGS_PCT = 5          # ignore alternatives that save less than this
MAX_ALTERNATIVES = 3


def find_alternatives(item, products_df, item_brand=None, current_store=None):
    """
    Find cheaper products in the same category.

    Comparison is done on UNIT price (price of one item), never on the line
    total, so '2 x Milk = NPR 200' is compared as NPR 100 per litre against
    an alternative's NPR 90 per litre.
    """
    # unit price falls back to the line price for callers that don't supply one
    user_price = float(item.get('unit_price') or item.get('price') or 0)
    item_size = parse_quantity_and_unit(item.get('name', ''))

    # Identify what the user actually bought, so the search can be limited to
    # that product's category. This reuses match_item() - the same scored
    # fuzzy match the review screen shows - instead of taking the first
    # product that happens to share a word. Picking the first share-a-word
    # match sent 'Kelloggs Corn Flakes 300g' to Snacks (via 'corn' inside
    # 'Popcorn') and 'Tokla Black Tea 200g' to Protein (via 'black').
    matched, _score, _level, _label = match_item(item, products_df.to_dict('records'))

    if not matched:
        return []
    category = matched['category']
    matched_product_name = matched['product_name']

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

    alts = alts[alts['savings'] > MIN_SAVINGS_PCT]
    alts = alts.sort_values('savings', ascending=False)
    # keep a few extra candidates: the recommendation engine re-ranks them on
    # more than price alone, so the cheapest is not automatically the winner
    results = alts.head(MAX_ALTERNATIVES * 3).to_dict('records')

    # Enrich with store-level prices
    all_with_stores = load_products_with_store_prices()
    store_map = {p['product_name']: p['stores'] for p in all_with_stores}

    for alt in results:
        # How comparable is this pack to what the user bought?
        alt_size = parse_quantity_and_unit(alt['product_name'])
        alt['unit_display']    = alt_size['unit']
        alt['unit_comparable'] = units_comparable(item_size['size_unit'],
                                                  alt_size['size_unit'])
        alt['size_similarity'] = (size_ratio(item_size['base_size'],
                                             alt_size['base_size'])
                                  if alt['unit_comparable'] else None)

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