import re
import json
from difflib import SequenceMatcher

def clean_text(text):
    text = re.sub(r'\s+', ' ', text.strip())
    return text

def parse_receipt_text(raw_text):
    """Improved OCR post-processing"""
    # Clean OCR artifacts
    raw_text = re.sub(r'[^\w\s\.\-\,\$]', ' ', raw_text)  # Remove special chars
    raw_text = re.sub(r'\s+', ' ', raw_text).strip()
    
    lines = raw_text.split('\n')
    items = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Better regex: name + quantity/price patterns
        # Handles "Item Name 2.50", "Item 1x 3.99", etc.
        price_match = re.search(r'(\d+\.?\d*)\s*$', line)
        if price_match:
            price_str = price_match.group(1)
            name_part = line[:price_match.start()].strip()
            
            try:
                price = float(price_str)
                # Try to extract quantity if present (e.g., "1L", "12pcs")
                qty_match = re.search(r'(\d+)([a-zA-Z]*)', name_part)
                quantity = int(qty_match.group(1)) if qty_match else 1
                
                name = re.sub(r'\d+[a-zA-Z]*\s*', '', name_part).strip()
                if not name:
                    name = name_part.strip()
                
                items.append({
                    "name": name,
                    "quantity": quantity,
                    "price": price
                })
            except ValueError:
                continue
    return {"items": items}

def fuzzy_match(name, products):
    """Improved fuzzy matching"""
    name_lower = name.lower().strip()
    best_match = None
    best_score = 0
    
    for prod in products:
        prod_name = prod['product_name'].lower()
        # Multiple scoring methods
        score1 = SequenceMatcher(None, name_lower, prod_name).ratio()
        # Keyword overlap bonus
        score2 = len(set(name_lower.split()) & set(prod_name.split())) / max(len(name_lower.split()), 1)
        
        score = max(score1, score2 * 1.2)  # Boost keyword matches
        if score > best_score and score > 0.55:
            best_score = score
            best_match = prod
    return best_match

if __name__ == "__main__":
    with open('receipt_example.txt', 'r') as f:
        text = f.read()
    data = parse_receipt_text(text)
    print(json.dumps(data, indent=2))