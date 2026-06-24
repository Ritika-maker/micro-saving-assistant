FOOD_CATEGORIES = {'Dairy', 'Bakery', 'Grains', 'Protein', 'Meat', 'Fruits', 'Beverages', 'Vegetables', 'Oils'}

def recommend_alternatives(item, products, comparison_results):
    """
    Returns up to 3 alternatives, each with:
      - alternative  : product name
      - alt_price    : float
      - savings_pct  : % cheaper vs item price
      - is_healthier : True only for food categories with health_score > 7
      - reason       : one clear sentence
      - explanation  : same as reason (kept for app.py compatibility)
    """
    recs = []

    # Determine category of the matched item from comparison results
    item_category = ''
    if comparison_results:
        item_category = comparison_results[0].get('category', '')

    is_food = item_category in FOOD_CATEGORIES

    for alt in comparison_results[:3]:
        savings_pct = (item['price'] - alt['price']) / item['price'] * 100
        if savings_pct <= 0:
            continue

        health_score = alt.get('health_score', 0)
        # Only flag healthier for food items, and only when score is meaningfully high
        is_healthier = is_food and health_score >= 8

        brand = alt.get('brand', '').strip()
        brand_part = f"{brand} " if brand and brand.lower() != 'generic' else ""

        if is_healthier:
            reason = f"Saves {savings_pct:.0f}% and has a higher nutrition score ({health_score}/10)."
        else:
            reason = f"Same category, {savings_pct:.0f}% cheaper at NPR {alt['price']:.2f}."

        recs.append({
            "alternative":  alt['product_name'],
            "alt_price":    round(float(alt['price']), 2),
            "savings_pct":  round(savings_pct, 1),
            "is_healthier": is_healthier,
            "reason":       reason,
            "explanation":  reason,   # backward compat
        })

    return recs


if __name__ == "__main__":
    pass