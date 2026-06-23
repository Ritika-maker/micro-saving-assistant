import json
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from receipt_processor import parse_receipt_text, fuzzy_match
from product_db import load_products
from price_comparison import find_alternatives
from recommendation_engine import recommend_alternatives
import pandas as pd

def main():
    # Load data
    products = load_products()
    products_df = pd.DataFrame(products)
    
    # Receipt
    with open('receipt_example.txt', 'r') as f:
        raw_text = f.read()
    
    receipt_data = parse_receipt_text(raw_text)
    
    # Process items
    total_spent = 0
    total_savings = 0
    all_recs = {}
    
    for item in receipt_data['items']:
        total_spent += item['price']
        # Normalize with fuzzy
        matched = fuzzy_match(item['name'], products)
        if matched:
            item['normalized'] = matched['product_name']
            item_for_comp = {"name": matched['product_name'], "price": item['price']}
        else:
            item['normalized'] = item['name']
            item_for_comp = item
        
        alts = find_alternatives(item_for_comp, products_df)
        recs = recommend_alternatives(item, products, alts)
        all_recs[item['name']] = recs
        
        if recs:
            best_saving = recs[0]['savings_pct']
            total_savings += (item['price'] * best_saving / 100)
    
    # Dashboard
    print("=== Micro-Savings Assistant Dashboard ===")
    print(f"Total Spent: ${total_spent:.2f}")
    print(f"Potential Savings: ${total_savings:.2f} ({(total_savings/total_spent*100 if total_spent > 0 else 0):.1f}%)")
    print("\nItem-wise Recommendations:")
    for item_name, recs in all_recs.items():
        print(f"\nFor {item_name}:")
        for r in recs:
            print(f"  - {r['alternative']}: {r['explanation']}")
    
    print("\n Top potential savings opportunities identified!")

if __name__ == "__main__":
    main()