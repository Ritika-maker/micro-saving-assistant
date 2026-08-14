"""
Rule-based recommendation engine.

Every alternative is scored with a transparent weighted formula - no machine
learning - so the app can always answer "why was this recommended?".

    score = 0.50 x price savings
          + 0.25 x product similarity (name + comparable pack size)
          + 0.15 x health score
          + 0.10 x category/brand relevance

The weights below are the only place these numbers appear; change them here
and the whole application follows.
"""

from difflib import SequenceMatcher

from unit_utils import calculate_unit_price

FOOD_CATEGORIES = {'Dairy', 'Bakery', 'Grains', 'Protein', 'Meat',
                   'Fruits', 'Beverages', 'Vegetables', 'Oils'}

# ── Scoring weights (must add up to 1.0) ─────────────────────────────────────
WEIGHT_SAVINGS    = 0.50
WEIGHT_SIMILARITY = 0.25
WEIGHT_HEALTH     = 0.15
WEIGHT_RELEVANCE  = 0.10

# A 50% saving already scores full marks for the savings component
SAVINGS_FULL_MARK_PCT = 50.0
# Within the similarity component: how much comes from the name vs pack size
NAME_SIMILARITY_SHARE = 0.6
HEALTHY_SCORE_MIN     = 8          # health score that counts as "healthier"
MAX_RECOMMENDATIONS   = 3


def _name_similarity(item_name, alt_name):
    return SequenceMatcher(None, item_name.lower().strip(),
                           alt_name.lower().strip()).ratio()


def _score_alternative(savings_pct, name_similarity, size_similarity,
                       health_score, same_category, different_brand):
    """
    Weighted 0.0-1.0 score. Returns (score, components) so the UI can show
    exactly what contributed.
    """
    savings_part = min(max(savings_pct, 0) / SAVINGS_FULL_MARK_PCT, 1.0)

    # An unknown pack size scores a neutral 0.5 rather than 0 - we simply
    # don't know whether the sizes match, so neither reward nor punish it.
    size_part = 0.5 if size_similarity is None else size_similarity
    similarity_part = (name_similarity * NAME_SIMILARITY_SHARE +
                       size_part * (1 - NAME_SIMILARITY_SHARE))

    health_part = min(max(int(health_score or 0), 0), 10) / 10
    relevance_part = 0.5 * (1.0 if same_category else 0.0) + \
                     0.5 * (1.0 if different_brand else 0.0)

    components = {
        "savings":    round(savings_part, 3),
        "similarity": round(similarity_part, 3),
        "health":     round(health_part, 3),
        "relevance":  round(relevance_part, 3),
    }
    score = (WEIGHT_SAVINGS * savings_part +
             WEIGHT_SIMILARITY * similarity_part +
             WEIGHT_HEALTH * health_part +
             WEIGHT_RELEVANCE * relevance_part)
    return round(score, 4), components


def _build_factors(alt, savings_pct, is_healthier, size_similarity,
                   freshness_label):
    """The tick-list shown under 'Why this recommendation?'."""
    factors = []
    if alt.get('category'):
        factors.append(f"Same category ({alt['category']})")
    if size_similarity == 1.0:
        factors.append(f"Same pack size ({alt.get('unit_display') or 'n/a'})")
    elif size_similarity is not None:
        factors.append("Comparable pack size, compared per unit")
    else:
        factors.append("Pack size not comparable - compared per item")
    factors.append(f"{savings_pct:.0f}% cheaper per unit")
    if is_healthier:
        factors.append(f"Better health score ({int(alt.get('health_score', 0))}/10)")
    if alt.get('best_store'):
        factors.append(f"Cheapest at {alt['best_store']}")
    if freshness_label:
        factors.append(f"Price {freshness_label.lower()}")
    return factors


def recommend_alternatives(item, products, comparison_results,
                           item_brand=None, match_confidence=None):
    """
    Rank the alternatives found by price_comparison.find_alternatives().

    Savings are calculated per unit and then multiplied by how many the user
    bought, so '2 x Milk' saves twice as much as one.
    """
    recs = []
    item_category = comparison_results[0].get('category', '') if comparison_results else ''
    is_food = item_category in FOOD_CATEGORIES
    seen_names = set()
    item_name_lower = (item.get('product_name') or item['name']).lower()
    quantity = int(item.get('quantity') or 1)
    # compare like with like: price of ONE of what the user bought
    item_unit_price = float(item.get('unit_price') or
                            calculate_unit_price(item['price'], quantity))

    for alt in comparison_results:
        alt_brand = alt.get('brand', '').strip().lower()

        if item_brand and item_brand.strip().lower() != 'generic':
            if alt_brand == item_brand.strip().lower():
                continue

        alt_name = alt['product_name']
        if alt_name in seen_names:
            continue
        seen_names.add(alt_name)

        alt_unit_price = float(alt.get('unit_price') or alt.get('price') or 0)
        if alt_unit_price <= 0 or item_unit_price <= 0:
            continue
        savings_pct = (item_unit_price - alt_unit_price) / item_unit_price * 100
        if savings_pct <= 0:
            continue

        savings_per_unit = item_unit_price - alt_unit_price
        savings_amount   = savings_per_unit * quantity

        health_score = alt.get('health_score', 0)
        is_healthier = is_food and int(health_score or 0) >= HEALTHY_SCORE_MIN
        size_similarity = alt.get('size_similarity')

        score, components = _score_alternative(
            savings_pct      = savings_pct,
            name_similarity  = _name_similarity(item_name_lower, alt_name),
            size_similarity  = size_similarity,
            health_score     = health_score,
            same_category    = bool(alt.get('category')) and
                               alt.get('category') == item_category,
            different_brand  = alt_brand != (item_brand or '').strip().lower(),
        )

        is_same_product = (alt_name.lower() == item_name_lower or
                           alt_name.lower() in item_name_lower or
                           item_name_lower in alt_name.lower())

        best_store      = alt.get('best_store', '')
        store_prices    = alt.get('store_prices', [])
        price_range     = alt.get('price_range')
        freshness_label = alt.get('freshness_label')

        if is_same_product:
            reason = (f"You overpaid - standard price is NPR "
                      f"{int(round(alt_unit_price))} per unit ({savings_pct:.0f}% cheaper).")
        elif is_healthier and size_similarity == 1.0:
            reason = (f"Same category and pack size, {savings_pct:.0f}% cheaper "
                      f"with a better health score ({int(health_score)}/10).")
        elif is_healthier:
            reason = (f"Similar product with a better health score "
                      f"({int(health_score)}/10) and {savings_pct:.0f}% lower unit price.")
        elif size_similarity == 1.0:
            reason = (f"Same category and unit size, {savings_pct:.0f}% cheaper"
                      + (f". Best price at {best_store}." if best_store else "."))
        elif best_store and len(store_prices) > 1:
            reason = (f"Same category, {savings_pct:.0f}% cheaper per unit. "
                      f"Best price at {best_store} ({price_range}).")
        else:
            reason = f"Same category, {savings_pct:.0f}% cheaper per unit."

        recs.append({
            "alternative":          alt_name,
            "alt_price":            int(round(alt_unit_price)),
            "savings_pct":          round(savings_pct, 1),
            "savings_per_unit":     int(round(savings_per_unit)),
            "savings_amount":       int(round(savings_amount)),
            "quantity":             quantity,
            "recommendation_score": score,
            "score_components":     components,
            "unit_display":         alt.get('unit_display', ''),
            "unit_comparable":      bool(alt.get('unit_comparable')),
            "is_healthier":         is_healthier,
            "reason":               reason,
            "explanation":          reason,
            "factors":              _build_factors(alt, savings_pct, is_healthier,
                                                   size_similarity, freshness_label),
            "best_store":           best_store,
            "store_prices":         store_prices,
            "price_range":          price_range,
            "freshness_label":      freshness_label,
            "match_confidence":     round(match_confidence * 100) if match_confidence else None,
        })

    # Best overall recommendation first - not simply the cheapest
    recs.sort(key=lambda r: r['recommendation_score'], reverse=True)
    return recs[:MAX_RECOMMENDATIONS]
