"""
Generate the DEVELOPMENT/DEMO product and price dataset.

    python dataset/build_demo_dataset.py

IMPORTANT - this is synthetic project data, not market research:

* Product names are realistic examples of goods sold in Kathmandu grocery
  stores, but the catalogue is assembled by this script, not collected from
  any store.
* Prices are plausible NPR figures generated from a base price per category
  and a fixed per-store multiplier. They are NOT observed shelf prices and
  must never be presented as real pricing.
* health_score is a project dataset value (1-10) used to demonstrate the
  recommendation rules. It is not a nutritional assessment.
* updated_at values are staggered by a fixed number of days per store so the
  price-freshness feature can be demonstrated.

Everything is deterministic: running it twice produces identical files.
"""

import csv
import os
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))

# ── Stores (development/demo) ────────────────────────────────────────────────
# (store_name, location, price multiplier, price age in days)
STORES = [
    ("General Market",  "Kathmandu",   1.00, 0),
    ("Bhatbhateni",     "Kathmandu",   1.08, 1),
    ("Big Mart",        "Lalitpur",    1.05, 3),
    ("Salesways",       "Kathmandu",   1.06, 6),
    ("Namaste Super",   "Bhaktapur",   1.02, 12),
    ("Local Kirana",    "Kathmandu",   0.97, 25),
]

# ── Catalogue definition ─────────────────────────────────────────────────────
# category -> list of (item, brands, unit kind, sizes, base price for size[0],
#                      health score)
CATALOGUE = {
    "Dairy": [
        ("Milk",         ["Amul", "Mother Dairy", "DDC", "Nestle", "Sujal"], "l",  ["1L", "500ml"], 90,  8),
        ("Yogurt",       ["Amul", "DDC", "Kwality"],                          "g",  ["500g", "200g"], 130, 8),
        ("Butter",       ["Amul", "Nestle"],                                  "g",  ["500g", "100g"], 620, 5),
        ("Cheese Slice", ["Amul", "Britannia"],                               "g",  ["200g"], 320, 6),
        ("Paneer",       ["Amul", "DDC"],                                     "g",  ["200g"], 190, 7),
        ("Ghee",         ["Amul", "Patanjali", "DDC"],                        "l",  ["1L", "500ml"], 1150, 5),
    ],
    "Bakery": [
        ("Whole Wheat Bread", ["Generic", "Krishna", "Nebico"], "g", ["400g", "800g"], 120, 9),
        ("White Bread",       ["Generic", "Krishna"],           "g", ["400g"], 90, 6),
        ("Bun Pack",          ["Generic", "Nebico"],            "pcs", ["6pcs"], 80, 6),
        ("Rusk",              ["Nebico", "Britannia"],          "g", ["300g"], 110, 5),
    ],
    "Grains": [
        ("Basmati Rice",   ["Generic", "Kohinoor", "Daawat"],   "kg", ["1kg", "5kg"], 180, 8),
        ("Brown Rice",     ["Generic"],                          "kg", ["1kg", "5kg"], 120, 9),
        ("Jeera Masino Rice", ["Generic", "Sona"],               "kg", ["5kg", "25kg"], 620, 7),
        ("Wheat Flour",    ["Generic", "Aashirvaad", "Patanjali"], "kg", ["1kg", "5kg"], 95, 8),
        ("Maida",          ["Generic", "Aashirvaad"],            "kg", ["1kg"], 90, 5),
        ("Oats",           ["Quaker", "Patanjali"],              "g",  ["500g", "1kg"], 280, 9),
        ("Beaten Rice",    ["Generic"],                          "kg", ["1kg"], 110, 7),
        ("Semolina",       ["Generic"],                          "kg", ["1kg"], 100, 7),
    ],
    "Protein": [
        ("Eggs",         ["Generic"],                 "pcs", ["12pcs", "6pcs", "30pcs"], 240, 7),
        ("Black Lentil", ["Generic", "Tulsi"],        "kg",  ["1kg"], 210, 8),
        ("Red Lentil",   ["Generic", "Tulsi"],        "kg",  ["1kg", "5kg"], 190, 8),
        ("Chickpeas",    ["Generic"],                 "kg",  ["1kg"], 180, 8),
        ("Soybean",      ["Generic"],                 "kg",  ["1kg"], 200, 8),
    ],
    "Meat": [
        ("Chicken Breast", ["Generic", "Nepali Farm"], "g", ["500g", "1kg"], 350, 6),
        ("Chicken Curry Cut", ["Generic"],             "kg", ["1kg"], 420, 6),
        ("Mutton",        ["Generic"],                 "kg", ["1kg"], 1250, 5),
        ("Fish Fillet",   ["Generic"],                 "g",  ["500g"], 380, 7),
    ],
    "Fruits": [
        ("Apples",   ["Generic"], "kg", ["1kg"], 280, 10),
        ("Bananas",  ["Generic"], "kg", ["1kg"], 100, 9),
        ("Oranges",  ["Generic"], "kg", ["1kg"], 220, 9),
        ("Grapes",   ["Generic"], "kg", ["1kg"], 320, 8),
        ("Papaya",   ["Generic"], "kg", ["1kg"], 130, 9),
        ("Pomegranate", ["Generic"], "kg", ["1kg"], 450, 9),
    ],
    "Vegetables": [
        ("Tomatoes", ["Generic"], "kg", ["1kg"], 80, 10),
        ("Potatoes", ["Generic"], "kg", ["1kg", "5kg"], 50, 9),
        ("Onions",   ["Generic"], "kg", ["1kg"], 90, 9),
        ("Cauliflower", ["Generic"], "kg", ["1kg"], 70, 9),
        ("Cabbage",  ["Generic"], "kg", ["1kg"], 60, 9),
        ("Carrot",   ["Generic"], "kg", ["1kg"], 95, 10),
        ("Spinach",  ["Generic"], "g",  ["500g"], 40, 10),
        ("Green Peas", ["Generic"], "kg", ["1kg"], 150, 9),
    ],
    "Beverages": [
        ("Coca Cola",  ["Coca Cola"], "l", ["2L", "1.25L", "500ml"], 160, 4),
        ("Pepsi",      ["Pepsi"],     "l", ["2L", "1.25L"], 150, 4),
        ("Sprite",     ["Coca Cola"], "l", ["2L"], 155, 4),
        ("Mango Juice", ["Real", "Frooti"], "l", ["1L", "200ml"], 210, 5),
        ("Black Tea",  ["Tokla", "Ilam", "Gorkha"], "g", ["200g", "500g"], 190, 7),
        ("Green Tea",  ["Tokla", "Ilam"],           "g", ["100g"], 240, 9),
        ("Instant Coffee", ["Nescafe", "Bru"],      "g", ["50g", "100g"], 320, 5),
        ("Mineral Water",  ["Generic"],             "l", ["1L", "5L"], 30, 8),
    ],
    "Oils": [
        ("Sunflower Oil", ["Fortune", "Dhara", "Generic"], "l", ["1L", "5L"], 280, 7),
        ("Mustard Oil",   ["Generic", "Patanjali"],        "l", ["1L", "5L"], 320, 6),
        ("Olive Oil",     ["Generic", "Figaro"],           "ml", ["500ml"], 850, 8),
        ("Soybean Oil",   ["Generic"],                     "l", ["1L", "5L"], 260, 6),
    ],
    "Snacks": [
        ("Potato Chips", ["Lays", "Kurkure"],     "g", ["50g", "100g"], 60, 3),
        ("Instant Noodles", ["Wai Wai", "Rara", "Mayos"], "g", ["75g"], 25, 3),
        ("Namkeen Mixture", ["Haldiram", "Generic"], "g", ["200g", "400g"], 130, 4),
        ("Popcorn",      ["Generic"],             "g", ["100g"], 90, 6),
    ],
    "Biscuits": [
        ("Digestive Biscuit", ["Britannia", "Nebico"], "g", ["250g", "400g"], 150, 6),
        ("Glucose Biscuit",   ["Britannia", "Parle"],  "g", ["200g"], 60, 4),
        ("Cream Biscuit",     ["Britannia", "Nebico", "Parle"], "g", ["150g"], 70, 3),
        ("Salt Biscuit",      ["Nebico"],              "g", ["200g"], 65, 5),
    ],
    "Breakfast": [
        ("Corn Flakes",  ["Kelloggs", "Patanjali"], "g", ["300g", "500g"], 420, 7),
        ("Muesli",       ["Kelloggs", "Bagrrys"],   "g", ["500g"], 620, 8),
        ("Honey",        ["Dabur", "Patanjali"],    "g", ["500g", "250g"], 560, 7),
        ("Peanut Butter", ["Pintola", "Generic"],   "g", ["400g"], 480, 7),
        ("Jam",          ["Kissan", "Generic"],     "g", ["500g"], 320, 4),
    ],
    "Spices": [
        ("Turmeric Powder", ["Everest", "MDH", "Generic"], "g", ["100g", "500g"], 70, 8),
        ("Chilli Powder",   ["Everest", "MDH"],            "g", ["100g", "500g"], 90, 7),
        ("Coriander Powder", ["Everest", "Generic"],       "g", ["100g"], 65, 8),
        ("Cumin Seed",      ["Generic"],                   "g", ["100g"], 120, 8),
        ("Garam Masala",    ["Everest", "MDH"],            "g", ["50g"], 85, 7),
        ("Salt",            ["Tata", "Generic"],           "kg", ["1kg"], 30, 6),
        ("Sugar",           ["Generic"],                   "kg", ["1kg", "5kg"], 110, 3),
    ],
    "Personal Care": [
        ("Toothpaste",  ["Colgate", "Close Up", "Dabur"],     "g",  ["100g", "200g"], 180, 7),
        ("Shampoo",     ["Head & Shoulders", "Sunsilk", "Clinic Plus"], "ml", ["200ml", "400ml"], 380, 6),
        ("Bath Soap",   ["Dove", "Lifebuoy", "Lux"],          "pcs", ["4pcs", "1pcs"], 250, 8),
        ("Hand Wash",   ["Dettol", "Lifebuoy"],               "ml", ["200ml"], 160, 7),
        ("Face Cream",  ["Nivea", "Ponds"],                   "g",  ["50g"], 290, 6),
        ("Hair Oil",    ["Parachute", "Dabur"],               "ml", ["200ml"], 210, 6),
    ],
    "Household": [
        ("Detergent Powder", ["Surf", "Wheel", "Rin"],   "kg", ["1kg", "500g"], 450, 5),
        ("Dishwash Liquid",  ["Vim", "Generic"],         "ml", ["500ml"], 190, 5),
        ("Toilet Cleaner",   ["Harpic", "Generic"],      "ml", ["500ml"], 230, 5),
        ("Floor Cleaner",    ["Lizol", "Generic"],       "ml", ["500ml"], 280, 5),
        ("Garbage Bags",     ["Generic"],                "pcs", ["30pcs"], 150, 5),
        ("Toilet Paper",     ["Generic", "Origami"],     "pcs", ["4pcs"], 220, 5),
    ],
}

# How a size relates to the base size of its product (index 0 = base price)
SIZE_FACTORS = {
    "1L": 1.0, "500ml": 0.55, "1.25L": 0.68, "2L": 1.0, "5L": 4.6, "200ml": 0.3,
    "100ml": 0.2, "400ml": 1.9, "50g": 0.55, "100g": 1.0, "150g": 1.4,
    "200g": 1.0, "250g": 0.62, "300g": 1.0, "400g": 1.0, "500g": 1.0,
    "800g": 1.9, "1kg": 1.0, "5kg": 4.7, "25kg": 22.0, "75g": 1.0,
    "6pcs": 1.0, "12pcs": 1.0, "30pcs": 1.0, "4pcs": 1.0, "1pcs": 0.3,
}
UNIT_LABEL = {"l": "liter", "ml": "ml", "kg": "kg", "g": "g", "pcs": "pcs"}


def build_products():
    """Return the demo product rows (deterministic order)."""
    rows = []
    for category, entries in CATALOGUE.items():
        for item, brands, unit_kind, sizes, base_price, health in entries:
            for size_index, size in enumerate(sizes):
                factor = SIZE_FACTORS.get(size, 1.0)
                if size_index > 0:
                    factor = factor / SIZE_FACTORS.get(sizes[0], 1.0)
                for brand_index, brand in enumerate(brands):
                    # A small, fixed brand premium keeps alternatives interesting
                    brand_factor = 1.0 + 0.06 * brand_index
                    price = round(base_price * factor * brand_factor)
                    name = f"{item} {size}" if brand == "Generic" \
                        else f"{brand} {item} {size}"
                    rows.append({
                        "product_name": name,
                        "category":     category,
                        "brand":        brand,
                        "unit":         UNIT_LABEL.get(unit_kind, unit_kind),
                        "price":        price,
                        "unit_price":   price,
                        "health_score": health,
                    })
    return rows


def build_store_prices(products):
    """Per-store prices derived from the base price with a fixed multiplier."""
    today = datetime.now()
    rows = []
    for store_name, _location, multiplier, age_days in STORES:
        updated = (today - timedelta(days=age_days)).isoformat()
        for product in products:
            price = round(product["price"] * multiplier)
            rows.append({
                "product_name": product["product_name"],
                "store_name":   store_name,
                "price":        price,
                "unit_price":   price,
                "updated_at":   updated,
            })
    return rows


def write_csv(path, rows, fieldnames):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path} ({len(rows)} rows)")


if __name__ == '__main__':
    products = build_products()
    write_csv(os.path.join(HERE, 'products.csv'), products,
              ["product_name", "category", "brand", "unit",
               "price", "unit_price", "health_score"])

    write_csv(os.path.join(HERE, 'stores.csv'),
              [{"store_name": s[0], "location": s[1]} for s in STORES],
              ["store_name", "location"])

    write_csv(os.path.join(HERE, 'store_prices.csv'), build_store_prices(products),
              ["product_name", "store_name", "price", "unit_price", "updated_at"])

    categories = sorted({p['category'] for p in products})
    print(f"\n{len(products)} demo products across {len(categories)} categories:")
    print(', '.join(categories))
