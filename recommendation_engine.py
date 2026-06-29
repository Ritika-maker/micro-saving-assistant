
FOOD_CATEGORIES = {'Dairy', 'Bakery', 'Grains', 'Protein', 'Meat', 'Fruits', 'Beverages', 'Vegetables', 'Oils'}

def recommend_alternatives(item, products, comparison_results, item_brand=None):
    """
    Returns up to 3 alternatives. Rules:
    - Never recommend the same brand the user already bought.
    - If a same-brand product is cheaper (different product line), suggest it too — but only if brand differs from matched item.
    - is_healthier only for food categories.
    - No floats in prices — integers (NPR).
    """
    recs = []
    item_category = comparison_results[0].get('category', '') if comparison_results else ''
    is_food = item_category in FOOD_CATEGORIES
    seen_names = set()
    item_name_lower = item['name'].lower()

    for alt in comparison_results[:3]:
        alt_brand = alt.get('brand', '').strip().lower()

        # Skip same brand only for real named brands (not Generic)
        if item_brand and item_brand.strip().lower() != 'generic':
            if alt_brand == item_brand.strip().lower():
                continue

        alt_name = alt['product_name']
        if alt_name in seen_names:
            continue
        seen_names.add(alt_name)

        alt_unit_price = float(alt.get('unit_price') or alt.get('price'))
        item_price = float(item['price'])
        savings_pct = (item_price - alt_unit_price) / item_price * 100
        if savings_pct <= 0:
            continue

        health_score = alt.get('health_score', 0)
        is_healthier = is_food and int(health_score) >= 8

        # Detect if this is the same product (user overpaid)
        is_same_product = alt_name.lower() == item_name_lower or \
                          alt_name.lower() in item_name_lower or \
                          item_name_lower in alt_name.lower()

        if is_same_product:
            reason = f"You overpaid — standard price is NPR {int(round(alt_unit_price))} ({savings_pct:.0f}% cheaper)."
        elif is_healthier:
            reason = f"Saves {savings_pct:.0f}% and has a better nutrition score ({int(health_score)}/10)."
        else:
            reason = f"Same category, {savings_pct:.0f}% cheaper per unit."

        recs.append({
            "alternative":  alt_name,
            "alt_price":    int(round(alt_unit_price)),
            "savings_pct":  round(savings_pct, 1),
            "is_healthier": is_healthier,
            "reason":       reason,
            "explanation":  reason,
        })
    return recs

if __name__ == "__main__":
    pass