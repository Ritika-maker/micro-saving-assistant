import re
from difflib import SequenceMatcher

from unit_utils import parse_quantity_and_unit, calculate_unit_price

# Fuzzy-match confidence bands, used everywhere the UI shows a match
CONFIDENCE_LEVELS = (
    (0.75, 'high',   'High confidence'),
    (0.55, 'medium', 'Medium confidence'),
    (0.35, 'low',    'Low confidence'),
)
MATCH_THRESHOLD = 0.35          # below this we report no match at all

# Summary lines that carry a price but are not products. Needed because OCR
# reads the whole receipt, not just the item block, so 'TOTAL 540' would
# otherwise be counted as an item and inflate the amount spent.
SUMMARY_KEYWORDS = {
    'total', 'grand total', 'sub total', 'subtotal', 'net total',
    'total amount', 'amount', 'amount due', 'net payable', 'payable',
    'tax', 'vat', 'gst', 'service charge', 'discount', 'savings',
    'cash', 'card', 'paid', 'change', 'balance', 'tender', 'tendered',
    'items', 'qty', 'quantity',
}
TOTAL_KEYWORDS = {'total', 'grand total', 'net total', 'total amount',
                  'amount due', 'net payable', 'payable'}

# Header/footer labels ('Tel: 01-4567890', 'Date: 2026-08-14'). These only
# count as metadata when nothing but numbers follows the label, so a real
# product such as 'Date Palm 250' is still treated as an item.
METADATA_KEYWORDS = {
    'tel', 'phone', 'ph', 'mob', 'mobile', 'contact', 'fax',
    'date', 'time', 'invoice', 'bill', 'receipt', 'pan', 'vat', 'gst',
    'reg', 'ref', 'cashier', 'counter', 'customer', 'order', 'table',
}
LABEL_QUALIFIERS = re.compile(r'\b(?:no|number|num|id)\b', re.IGNORECASE)

# A date anywhere in the item name means the line is a header, not a product
DATE_PATTERN = re.compile(r'\d{1,4}[-/]\d{1,2}[-/]\d{1,4}')


def _summary_key(name_part):
    """Reduce a line label to letters only so 'TOTAL:' and 'Total' match."""
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z\s]', ' ', name_part.lower())).strip()


def _match_summary_keyword(key):
    """
    Return the summary keyword a line label stands for, or None.

    Exact matches are checked first; longer labels are then compared with
    difflib so that OCR slips such as 'OISCOUNT' still resolve to 'discount'.
    Short labels are only matched exactly, because words like 'tea' and 'tax'
    are too similar to guess safely.
    """
    if key in SUMMARY_KEYWORDS:
        return key
    if len(key) >= 5:
        for keyword in SUMMARY_KEYWORDS:
            if SequenceMatcher(None, key, keyword).ratio() >= 0.85:
                return keyword
    return None


def _is_metadata_line(name_part):
    """True for header lines such as 'Tel 01-4567890' or 'Invoice No 4521'."""
    words = name_part.split()
    if not words or _summary_key(words[0]) not in METADATA_KEYWORDS:
        return False
    rest = LABEL_QUALIFIERS.sub('', ' '.join(words[1:]))
    return not re.search(r'[A-Za-z]{2,}', rest)     # only numbers follow the label


def parse_receipt_text(raw_text, store_name=None):
    lines = raw_text.split('\n')
    items = []
    total = None
    for line in lines:
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

                # Receipt summary line (total, VAT, change ...) - not a product
                keyword = _match_summary_keyword(_summary_key(name))
                if keyword:
                    if keyword in TOTAL_KEYWORDS:
                        total = price
                    continue

                # Header/footer metadata (phone number, date, bill number ...)
                if _is_metadata_line(name) or DATE_PATTERN.search(name):
                    continue

                # A product name always contains letters; skip leftover noise
                if not re.search(r'[A-Za-z]{2,}', name):
                    continue

                items.append(build_item(name, price))
            except ValueError:
                continue
    return {"items": items, "store_name": store_name, "total": total}


def build_item(raw_name, price, quantity=None, unit=None):
    """
    Turn one receipt line into a structured grocery item record.

    'quantity'/'unit' can be supplied to rebuild an item the user corrected on
    the review screen; otherwise they are read from the text.

        build_item('2 x Milk 1L', 200)
        -> product_name 'Milk', quantity 2, unit '1L',
           price 200 (line total), unit_price 100

    'name' keeps the original wording because fuzzy matching works better
    against the full description ('Amul Milk 1L') than a stripped one.
    """
    parsed = parse_quantity_and_unit(raw_name)
    if quantity is not None:
        try:
            parsed['quantity'] = max(1, int(quantity))
        except (TypeError, ValueError):
            pass
    if unit is not None:
        parsed['unit'] = str(unit).strip()

    price = float(price)
    return {
        "name":         raw_name.strip(),          # original text, used for matching
        "product_name": parsed['name'],            # cleaned name for display/export
        "quantity":     parsed['quantity'],
        "unit":         parsed['unit'],
        "size_unit":    parsed['size_unit'],
        "base_size":    parsed['base_size'],
        "price":        price,                     # total paid for this line
        "unit_price":   calculate_unit_price(price, parsed['quantity']),
    }


def classify_confidence(score):
    """
    Turn a 0.0-1.0 match score into a band the UI can show.
    Returns (level, label): 'high' / 'medium' / 'low' / 'none'.
    """
    score = float(score or 0)
    for threshold, level, label in CONFIDENCE_LEVELS:
        if score >= threshold:
            return level, label
    return 'none', 'No match'


WORD_MATCH_RATIO = 0.8      # two words count as the same word above this


def _keyword_overlap(name_words, prod_words):
    """
    Jaccard overlap that tolerates OCR damage inside a word.

    Plain set intersection scores 'Amu1 Mlilk' against 'Amul Milk' as zero
    overlap, so words are paired up when they are nearly identical (80%+
    character similarity) and each product word can only be used once.
    """
    matched = 0
    available = set(prod_words)
    for word in name_words:
        best_word, best_ratio = None, 0.0
        for candidate in available:
            ratio = 1.0 if word == candidate else \
                SequenceMatcher(None, word, candidate).ratio()
            if ratio > best_ratio:
                best_word, best_ratio = candidate, ratio
        if best_ratio >= WORD_MATCH_RATIO:
            matched += 1
            available.discard(best_word)

    union = len(name_words) + len(prod_words) - matched
    return matched / union if union else 0.0


def fuzzy_match(name, products):
    """
    Fuzzy keyword overlap (70%) + sequence ratio (30%).
    Returns (best_match_dict, confidence_score 0.0-1.0) or (None, 0.0).
    """
    name_lower = name.lower().strip()
    name_words = set(w for w in name_lower.split() if len(w) > 2)
    best_match = None
    best_score = 0.0

    for prod in products:
        prod_name = prod['product_name'].lower()
        prod_words = set(w for w in prod_name.split() if len(w) > 2)
        if not name_words or not prod_words:
            continue
        overlap = _keyword_overlap(name_words, prod_words)
        seq = SequenceMatcher(None, name_lower, prod_name).ratio()
        score = overlap * 0.7 + seq * 0.3
        if score > best_score and score > MATCH_THRESHOLD:
            best_score = score
            best_match = prod

    return best_match, best_score


def match_item(item, products):
    """
    Fuzzy match a structured item against the catalogue.

    Receipt wording and catalogue wording rarely line up ('2 x Milk 1L' vs
    'Amul Milk 1L'), so every sensible spelling of the item is tried and the
    best scoring one wins.

    Returns (product_or_None, score, level, label).
    """
    product_name = (item.get('product_name') or '').strip()
    unit = (item.get('unit') or '').strip()
    quantity = item.get('quantity') or 1

    candidates = [item.get('name') or product_name]
    if product_name and unit:
        candidates.append(f"{product_name} {unit}")
        if quantity > 1:
            candidates.append(f"{product_name} {quantity} {unit}")
    if product_name:
        candidates.append(product_name)

    seen, best, best_score = set(), None, 0.0
    for candidate in candidates:
        key = (candidate or '').strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        matched, score = fuzzy_match(candidate, products)
        if matched and score > best_score:
            best, best_score = matched, score

    level, label = classify_confidence(best_score)
    return best, best_score, level, label