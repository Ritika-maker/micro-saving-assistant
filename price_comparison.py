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
    category = None
    item_unit_price = None

    # Find the matched product's category and unit_price
    for prod in products_df.to_dict('records'):
        prod_name_lower = prod['product_name'].lower()
        if (prod_name_lower in item_name_lower or
            item_name_lower in prod_name_lower or
            any(word in prod_name_lower for word in item_name_lower.split() if len(word) > 3)):
            category = prod['category']
            item_unit_price = float(prod.get('unit_price') or prod.get('price') or item['price'])
            break

    if not category:
        return []

    alts = products_df[products_df['category'] == category].copy()

    # Exclude same brand as what the user bought
    if item_brand:
        alts = alts[alts['brand'].str.lower() != item_brand.lower()]

    # Also exclude the exact matched product name
    alts = alts[alts['product_name'].str.lower() != item['name'].lower()]

    # Use unit_price for comparison
    ref_price = item_unit_price if item_unit_price else item['price']
    alts['_unit_price'] = alts.apply(
        lambda r: float(r.get('unit_price') or r.get('price')), axis=1
    )
    alts['savings'] = (ref_price - alts['_unit_price']) / ref_price * 100
    alts = alts[alts['savings'] > 5]  # at least 5% cheaper per unit
    alts = alts.sort_values('savings', ascending=False)
    return alts.head(3).to_dict('records')