"""
Unit and quantity utilities for the Micro-Savings Assistant.

One place for every "how much did you actually buy?" question, so that
parsing, price comparison, recommendations and the UI all agree.

Two different ideas are kept apart on purpose:

  quantity  - how many of the item were bought   ('2 x Milk 1L'  -> 2)
  size      - how big one of them is             ('2 x Milk 1L'  -> 1 L)

and from those:

  unit_price = total line price / quantity       (200 / 2 = 100 per 1L pack)

Only conversions that are always true are performed (1 kg = 1000 g,
1 L = 1000 ml, 1 dozen = 12 pieces). A 'pack' is never assumed to contain a
particular number of pieces, because that depends on the product.
"""

import re

# ── Unit vocabulary ──────────────────────────────────────────────────────────
# Every spelling users/OCR produce -> (canonical unit, factor in base unit)

WEIGHT_UNITS = {
    'mg': ('mg', 0.001), 'g': ('g', 1.0), 'gm': ('g', 1.0), 'gms': ('g', 1.0),
    'gram': ('g', 1.0), 'grams': ('g', 1.0),
    'kg': ('kg', 1000.0), 'kgs': ('kg', 1000.0), 'kilo': ('kg', 1000.0),
    'kilos': ('kg', 1000.0), 'kilogram': ('kg', 1000.0), 'kilograms': ('kg', 1000.0),
}
VOLUME_UNITS = {
    'ml': ('ml', 1.0), 'mls': ('ml', 1.0), 'milliliter': ('ml', 1.0),
    'millilitre': ('ml', 1.0),
    'l': ('l', 1000.0), 'ltr': ('l', 1000.0), 'ltrs': ('l', 1000.0),
    'lt': ('l', 1000.0), 'litre': ('l', 1000.0), 'litres': ('l', 1000.0),
    'liter': ('l', 1000.0), 'liters': ('l', 1000.0),
}
COUNT_UNITS = {
    'pc': ('pcs', 1), 'pcs': ('pcs', 1), 'piece': ('pcs', 1), 'pieces': ('pcs', 1),
    'dozen': ('pcs', 12), 'dozens': ('pcs', 12), 'dz': ('pcs', 12),
}
# Containers: usable as a display unit, but their contents are unknown,
# so they are never converted into pieces/grams.
PACK_UNITS = {
    'pack': 'pack', 'packs': 'pack', 'packet': 'pack', 'packets': 'pack',
    'pkt': 'pack', 'box': 'box', 'bottle': 'bottle', 'btl': 'bottle',
    'can': 'can', 'jar': 'jar', 'tube': 'tube', 'bag': 'bag', 'tin': 'tin',
}

# Longest spellings first so 'kgs' is not matched as 'kg' + leftover 's'
_ALL_UNIT_WORDS = sorted(
    list(WEIGHT_UNITS) + list(VOLUME_UNITS) + list(COUNT_UNITS) + list(PACK_UNITS),
    key=len, reverse=True)

_NUMBER = r'\d+(?:[.,]\d+)?'
SIZE_PATTERN = re.compile(
    r'(?<![A-Za-z0-9])(' + _NUMBER + r')\s*(' +
    '|'.join(w for w in _ALL_UNIT_WORDS
             if w in WEIGHT_UNITS or w in VOLUME_UNITS) + r')(?![A-Za-z])',
    re.IGNORECASE)
COUNT_PATTERN = re.compile(
    r'(?<![A-Za-z0-9])(?:(' + _NUMBER + r')\s*)?(' +
    '|'.join(w for w in _ALL_UNIT_WORDS
             if w in COUNT_UNITS or w in PACK_UNITS) + r')(?![A-Za-z])',
    re.IGNORECASE)

# '2 x Milk', '2X Milk'
QTY_PREFIX_PATTERN = re.compile(r'^\s*(\d{1,3})\s*[x×*]\s*(?=\S)', re.IGNORECASE)
# 'Milk x2', 'Milk 2x'
QTY_SUFFIX_PATTERN = re.compile(r'\s*(?:[x×*]\s*(\d{1,3})|(\d{1,3})\s*[x×*])\s*$',
                                re.IGNORECASE)


def normalize_unit(text):
    """
    Reduce any unit spelling to its canonical short form.

        normalize_unit('KG')      -> 'kg'
        normalize_unit('litres')  -> 'l'
        normalize_unit('grams')   -> 'g'
        normalize_unit('1L')      -> 'l'
        normalize_unit('pieces')  -> 'pcs'
        normalize_unit('sachet')  -> ''      (unknown)
    """
    if not text:
        return ''
    word = re.sub(r'[^a-z]', '', str(text).lower())
    if word in WEIGHT_UNITS:
        return WEIGHT_UNITS[word][0]
    if word in VOLUME_UNITS:
        return VOLUME_UNITS[word][0]
    if word in COUNT_UNITS:
        return COUNT_UNITS[word][0]
    if word in PACK_UNITS:
        return PACK_UNITS[word]
    return ''


def unit_dimension(unit):
    """'kg' -> 'weight', 'ml' -> 'volume', 'pcs' -> 'count', 'pack' -> 'pack'."""
    unit = normalize_unit(unit)
    if not unit:
        return ''
    if unit in ('mg', 'g', 'kg'):
        return 'weight'
    if unit in ('ml', 'l'):
        return 'volume'
    if unit == 'pcs':
        return 'count'
    return 'pack'


def to_base_quantity(value, unit):
    """
    Convert a size to its base unit (g for weight, ml for volume, pcs for count).
    Returns None when the unit cannot be converted safely (pack, box, unknown).

        to_base_quantity(5, 'kg')  -> 5000.0
        to_base_quantity(1, 'L')   -> 1000.0
        to_base_quantity(2, 'pack')-> None
    """
    if value is None:
        return None
    word = re.sub(r'[^a-z]', '', str(unit).lower())
    for table in (WEIGHT_UNITS, VOLUME_UNITS, COUNT_UNITS):
        if word in table:
            return float(value) * table[word][1]
    return None


def units_comparable(unit_a, unit_b):
    """
    True when two units measure the same kind of thing and can be compared.
    Unknown units and containers ('pack') are not comparable, because one
    pack of biscuits is not one pack of rice.
    """
    dim_a, dim_b = unit_dimension(unit_a), unit_dimension(unit_b)
    if not dim_a or not dim_b or dim_a != dim_b:
        return False
    return dim_a in ('weight', 'volume', 'count')


def format_size(value, unit):
    """Display form of a size: format_size(1, 'l') -> '1L', (500, 'g') -> '500g'."""
    unit = normalize_unit(unit)
    if not unit or value is None:
        return unit or ''
    number = int(value) if float(value).is_integer() else round(float(value), 2)
    return f"{number}{'L' if unit == 'l' else unit}"


def parse_quantity_and_unit(text):
    """
    Split a receipt item description into product name, quantity and size.

        '2 x Milk 1L'      -> name 'Milk',        quantity 2,  unit '1L'
        'Basmati Rice 5kg' -> name 'Basmati Rice',quantity 1,  unit '5kg'
        'Eggs 12 pcs'      -> name 'Eggs',        quantity 12, unit 'pcs'
        'Amul Taaza Milk'  -> name 'Amul Taaza Milk', quantity 1, unit ''

    Returns a dict: name, quantity, unit, size_value, size_unit, base_size.
    The product name keeps its brand and descriptive words - it is only
    stripped of the quantity/size tokens, never reduced to a bare category.
    """
    original = (text or '').strip()
    name = original
    quantity = 1

    # 1. Explicit multipliers: '2 x Milk' or 'Milk x2'
    prefix = QTY_PREFIX_PATTERN.search(name)
    if prefix:
        quantity = int(prefix.group(1))
        name = name[prefix.end():]
    else:
        suffix = QTY_SUFFIX_PATTERN.search(name)
        if suffix:
            quantity = int(suffix.group(1) or suffix.group(2))
            name = name[:suffix.start()]

    # 2. Pack size: '1L', '500 g', '5kg'
    size_value = size_unit = None
    size = SIZE_PATTERN.search(name)
    if size:
        size_value = float(size.group(1).replace(',', '.'))
        size_unit = normalize_unit(size.group(2))
        name = (name[:size.start()] + ' ' + name[size.end():])

    # 3. Countable units: '12 pcs', '1 dozen', '4 pack'
    #
    # A product name can itself contain a container word ('Bun Pack 6 pcs'),
    # so a token WITH a number always wins. A bare container word is only
    # treated as the unit when it trails the name ('Oats 500g pack'),
    # otherwise it belongs to the product name.
    count_unit = None
    count = None
    candidates = list(COUNT_PATTERN.finditer(name))
    for candidate in candidates:
        if candidate.group(1):
            count = candidate
            break
    if count is None:
        for candidate in candidates:
            if candidate.end() >= len(name.rstrip()):
                count = candidate
                break
    if count:
        raw_unit = count.group(2)
        canonical = normalize_unit(raw_unit)
        number = float(count.group(1)) if count.group(1) else None
        if canonical == 'pcs':
            # 'dozen' always means 12 pieces; '12 pcs' means 12 pieces
            per_unit = COUNT_UNITS[re.sub(r'[^a-z]', '', raw_unit.lower())][1]
            if number or per_unit > 1:
                quantity = int((number or 1) * per_unit)
            count_unit = 'pcs'
        else:
            # container units: keep as display unit, quantity only if written
            if number and prefix is None:
                quantity = int(number)
            count_unit = canonical
        name = (name[:count.start()] + ' ' + name[count.end():])

    name = re.sub(r'\s+', ' ', name).strip(' -,.')

    # Prefer the measurable size for display ('1L'), fall back to the
    # countable/container unit ('pcs', 'pack')
    if size_unit:
        unit_display = format_size(size_value, size_unit)
    elif count_unit:
        unit_display = count_unit
    else:
        unit_display = ''

    return {
        "name":       name or original,
        "quantity":   max(1, int(quantity)),
        "unit":       unit_display,
        "size_value": size_value,
        "size_unit":  size_unit or count_unit or '',
        "base_size":  to_base_quantity(size_value, size_unit) if size_unit else None,
    }


def calculate_unit_price(total_price, quantity):
    """
    Price of ONE item from the line total.

        calculate_unit_price(200, 2) -> 100.0
    """
    try:
        total_price = float(total_price)
        quantity = int(quantity or 1)
    except (TypeError, ValueError):
        return 0.0
    if quantity <= 0:
        return round(total_price, 2)
    return round(total_price / quantity, 2)


def size_ratio(size_a, size_b):
    """
    How similar two pack sizes are, 0.0-1.0 (1.0 = identical size).
    Returns None when the sizes are not comparable, so callers can decide
    what to do instead of silently treating them as equal.
    """
    if not size_a or not size_b or size_a <= 0 or size_b <= 0:
        return None
    return min(size_a, size_b) / max(size_a, size_b)
