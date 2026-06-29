import pandas as pd


def find_alternatives(item, products_df, item_brand=None):
    """
    Find cheaper alternatives in the same category.
    - Excludes the same brand (no point recommending what user already bought).
    - Compares by unit_price for fairness across pack sizes.
    - Falls back to price if unit_price missing.
    - Returns up to 3 alternatives cheaper than the item.
    """
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

    # Only exclude same brand when it's a real named brand (not Generic)
    if item_brand and item_brand.strip().lower() != 'generic':
        alts = alts[alts['brand'].str.lower() != item_brand.lower()]

    # Always use user's actual paid price as the reference for savings
    alts['_unit_price'] = alts.apply(
        lambda r: float(r.get('unit_price') or r.get('price')), axis=1
    )
    alts['savings'] = (user_price - alts['_unit_price']) / user_price * 100

    # Only exclude same product if user is NOT overpaying vs DB price
    if matched_product_name:
        same_product_mask = alts['product_name'].str.lower() == matched_product_name.lower()
        same_product_db_price = alts.loc[same_product_mask, '_unit_price']
        if not same_product_db_price.empty and user_price <= float(same_product_db_price.iloc[0]) * 1.05:
            # User paid fair price — exclude same product from alts
            alts = alts[~same_product_mask]
        # else: user overpaid even for same product — keep it in alts

    alts = alts[alts['savings'] > 5]
    alts = alts.sort_values('savings', ascending=False)
    return alts.head(3).to_dict('records')