import re
import json
from difflib import SequenceMatcher

def parse_receipt_text(raw_text):
    lines = raw_text.split('\n')
    items = []
    for line in lines:
        # Clean each line individually — preserve spaces within the line
        line = re.sub(r'[^\w\s\.\-\,]', ' ', line)
        line = re.sub(r'\s+', ' ', line).strip()
        if not line:
            continue
        price_match = re.search(r'(\d+\.?\d*)\s*$', line)
        if price_match:
            price_str = price_match.group(1)
            name_part = line[:price_match.start()].strip()
            try:
                price = float(price_str)
                name = name_part.strip()
                if not name:
                    continue
                items.append({"name": name, "quantity": 1, "price": price})
            except ValueError:
                continue
    return {"items": items}


def fuzzy_match(name, products):
    """
    Match user input to a product. Returns best match above threshold.
    Uses keyword overlap as primary signal (more reliable than sequence ratio for product names).
    """
    name_lower = name.lower().strip()
    name_words = set(w for w in name_lower.split() if len(w) > 2)

    best_match = None
    best_score = 0

    for prod in products:
        prod_name = prod['product_name'].lower()
        prod_words = set(w for w in prod_name.split() if len(w) > 2)

        if not name_words or not prod_words:
            continue

        # Keyword overlap: intersection / union (Jaccard)
        overlap = len(name_words & prod_words) / len(name_words | prod_words)

        # Sequence ratio as secondary signal (lower weight)
        seq = SequenceMatcher(None, name_lower, prod_name).ratio()

        score = overlap * 0.7 + seq * 0.3

        if score > best_score and score > 0.35:
            best_score = score
            best_match = prod

    return best_match


if __name__ == "__main__":
    with open('receipt_example.txt', 'r') as f:
        text = f.read()
    data = parse_receipt_text(text)
    print(json.dumps(data, indent=2))