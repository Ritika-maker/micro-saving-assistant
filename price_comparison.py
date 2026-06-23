import pandas as pd

def find_alternatives(item, products_df, threshold=0.3):
    """Find cheaper alternatives in same category"""
    item_name_lower = item['name'].lower()
    category = None
    for prod in products_df.to_dict('records'):
        prod_name_lower = prod['product_name'].lower()
        if (prod_name_lower in item_name_lower or 
            item_name_lower in prod_name_lower or 
            any(word in prod_name_lower for word in item_name_lower.split() if len(word) > 3)):
            category = prod['category']
            break
    if not category:
        return []
    
    alts = products_df[products_df['category'] == category].copy()
    alts['savings'] = (item['price'] - alts['price']) / item['price'] * 100
    alts = alts[alts['savings'] > 5]  # Only consider alternatives that are at least 5% cheaper
    alts = alts.sort_values('savings', ascending=False)
    return alts.head(3).to_dict('records')