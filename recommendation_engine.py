def recommend_alternatives(item, products, comparison_results):
    recs = []
    for alt in comparison_results[:3]:
        savings_pct = (item['price'] - alt['price']) / item['price'] * 100
        explanation = f"You can save {savings_pct:.0f}% by switching to {alt['brand']} {alt['product_name']}. It's in the same category and cheaper."
        if alt.get('health_score', 0) > 7:
            explanation += " Also healthier option."
        recs.append({
            "alternative": alt['product_name'],
            "savings_pct": round(savings_pct, 1),
            "explanation": explanation
        })
    return recs

if __name__ == "__main__":
    # Test later
    pass