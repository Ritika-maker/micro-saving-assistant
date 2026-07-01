FOOD_CATEGORIES = {'Dairy', 'Bakery', 'Grains', 'Protein', 'Meat',
                   'Fruits', 'Beverages', 'Vegetables', 'Oils'}

def recommend_alternatives(item, products, comparison_results,
                           item_brand=None, match_confidence=None):
    recs = []
    item_category = comparison_results[0].get('category', '') if comparison_results else ''
    is_food = item_category in FOOD_CATEGORIES
    seen_names = set()
    item_name_lower = item['name'].lower()

    for alt in comparison_results[:3]:
        alt_brand = alt.get('brand', '').strip().lower()

        if item_brand and item_brand.strip().lower() != 'generic':
            if alt_brand == item_brand.strip().lower():
                continue

        alt_name = alt['product_name']
        if alt_name in seen_names:
            continue
        seen_names.add(alt_name)

        alt_unit_price = float(alt.get('unit_price') or alt.get('price') or 0)
        item_price = float(item['price'])
        savings_pct = (item_price - alt_unit_price) / item_price * 100
        if savings_pct <= 0:
            continue

        health_score = alt.get('health_score', 0)
        is_healthier = is_food and int(health_score) >= 8

        is_same_product = (alt_name.lower() == item_name_lower or
                           alt_name.lower() in item_name_lower or
                           item_name_lower in alt_name.lower())

        best_store = alt.get('best_store', '')
        store_prices = alt.get('store_prices', [])
        price_range = alt.get('price_range')

        if is_same_product:
            reason = f"You overpaid — standard price is NPR {int(round(alt_unit_price))} ({savings_pct:.0f}% cheaper)."
        elif is_healthier and best_store:
            reason = f"Saves {savings_pct:.0f}% with better nutrition ({health_score}/10). Cheapest at {best_store}."
        elif is_healthier:
            reason = f"Saves {savings_pct:.0f}% and has a better nutrition score ({int(health_score)}/10)."
        elif best_store and len(store_prices) > 1:
            reason = f"Same category, {savings_pct:.0f}% cheaper. Best price at {best_store} ({price_range})."
        else:
            reason = f"Same category, {savings_pct:.0f}% cheaper per unit."

        recs.append({
            "alternative":      alt_name,
            "alt_price":        int(round(alt_unit_price)),
            "savings_pct":      round(savings_pct, 1),
            "is_healthier":     is_healthier,
            "reason":           reason,
            "explanation":      reason,
            "best_store":       best_store,
            "store_prices":     store_prices,
            "price_range":      price_range,
            "match_confidence": round(match_confidence * 100) if match_confidence else None,
        })
    return recs