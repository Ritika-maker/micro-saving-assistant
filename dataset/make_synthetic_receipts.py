"""
Generate SYNTHETIC receipt images and their ground truth.

    python dataset/make_synthetic_receipts.py            # 30 receipts
    python dataset/make_synthetic_receipts.py --count 50
    python dataset/make_synthetic_receipts.py --out /tmp/receipts

READ THIS BEFORE USING THE NUMBERS
----------------------------------
These are *rendered* receipts: clean digital text with simulated blur, noise,
downscaling and rotation. They are NOT photographs of real receipts.

* Use them to check that the pipeline works end to end, to compare two
  versions of the algorithm, and to find layout bugs.
* Accuracy measured on them is an OPTIMISTIC UPPER BOUND. Do not report it as
  "OCR accuracy" in the project report without saying it was measured on
  synthetic renders.
* For a defensible accuracy figure, photograph real receipts, put them in
  dataset/ocr_receipts/ and hand-write their ground truth.

Every generated file is named `synthetic_*` and its ground truth carries
"source": "synthetic" so it can never be mistaken for real data.

Output: <out>/ocr_receipts/synthetic_NNN.png|jpg
        <out>/ground_truth/synthetic_NNN.json
"""

import argparse
import json
import os
import random

from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))

STORES = [
    ("SUPER MART", "Kalimati, Kathmandu", "01-4567890"),
    ("BHATBHATENI SUPERSTORE", "Maharajgunj, Kathmandu", "01-4721234"),
    ("BIG MART", "Pulchowk, Lalitpur", "01-5551212"),
    ("NAMASTE SUPERMARKET", "Bhaktapur", "01-6612345"),
    ("LOCAL KIRANA STORE", "Baneshwor, Kathmandu", "9841000000"),
]

# (product name, unit shown on the receipt, unit price)
PRODUCTS = [
    ("Amul Milk", "1L", 90),        ("Mother Dairy Milk", "1L", 80),
    ("Whole Wheat Bread", "400g", 120), ("White Bread", "400g", 90),
    ("Basmati Rice", "5kg", 850),   ("Brown Rice", "1kg", 120),
    ("Sunflower Oil", "1L", 280),   ("Mustard Oil", "1L", 320),
    ("Coca Cola", "2L", 160),       ("Pepsi", "1.25L", 110),
    ("Wai Wai Instant Noodles", "75g", 25), ("Lays Potato Chips", "100g", 95),
    ("Colgate Toothpaste", "100g", 180), ("Dove Bath Soap", "4pcs", 250),
    ("Surf Detergent Powder", "1kg", 450), ("Tomatoes", "1kg", 80),
    ("Potatoes", "5kg", 240),       ("Apples", "1kg", 280),
    ("Tokla Black Tea", "200g", 190), ("Nescafe Instant Coffee", "50g", 320),
    ("Amul Butter", "500g", 620),   ("Quaker Oats", "500g", 280),
]
COUNT_PRODUCTS = [("Eggs", "pcs", 20), ("Bun Pack", "pcs", 14)]

# Rendering conditions, cycled so every batch covers all of them
CONDITIONS = ['clear', 'clear', 'small', 'blurry', 'noisy', 'low_contrast',
              'long', 'rotated', 'clear', 'small']


def _font(size):
    for name in ("consola.ttf", "cour.ttf", "DejaVuSansMono.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _receipt_lines(rng, condition):
    """Build the receipt text and the matching ground-truth items."""
    store, address, phone = rng.choice(STORES)
    item_count = rng.randint(10, 16) if condition == 'long' else rng.randint(4, 8)
    layout = rng.choice(['simple', 'simple', 'qty_prefix', 'columns'])

    lines = [store, address, f"Tel: {phone}",
             f"Date: 2026-08-{rng.randint(10, 28):02d}  {rng.randint(9, 20)}:{rng.randint(10, 59)}",
             ""]
    items, subtotal = [], 0.0

    for _ in range(item_count):
        if rng.random() < 0.2:
            name, unit, unit_price = rng.choice(COUNT_PRODUCTS)
            quantity = rng.choice([6, 12, 30])
            display_unit = unit
        else:
            name, unit, unit_price = rng.choice(PRODUCTS)
            quantity = rng.choice([1, 1, 1, 2, 3]) if layout == 'qty_prefix' else 1
            display_unit = unit

        total = unit_price * quantity
        # decimal prices on some lines
        if rng.random() < 0.25:
            total = round(total + rng.choice([0.5, 0.25, 0.75]), 2)
        subtotal += total

        printed_total = f"{total:,.2f}" if isinstance(total, float) and total % 1 else f"{total:,.0f}"

        # A size written as a piece count ('4pcs') is a quantity, matching how
        # the parser reads 'Eggs 12 pcs' -> quantity 12, unit 'pcs'
        # (the printed line total is unchanged - only how the pack is described)
        if display_unit.endswith('pcs') and display_unit[:-3].isdigit():
            quantity, display_unit = int(display_unit[:-3]), 'pcs'

        if display_unit == 'pcs':
            text = f"{name} {quantity} pcs"
        elif layout == 'qty_prefix' and quantity > 1:
            text = f"{quantity} x {name} {display_unit}"
        else:
            text = f"{name} {display_unit}"

        if layout == 'columns' and quantity > 1:
            line = f"{text:<34}{quantity} x {unit_price:<6}{printed_total:>9}"
        else:
            line = f"{text:<40}{printed_total:>9}"
        lines.append(line)

        items.append({"product_name": name, "quantity": quantity,
                      "unit": display_unit, "price": round(total, 2)})

    vat = round(subtotal * 0.13, 2)
    total_due = round(subtotal + vat, 2)
    lines += ["",
              f"{'SUBTOTAL':<40}{subtotal:>9,.2f}",
              f"{'VAT 13%':<40}{vat:>9,.2f}",
              f"{'TOTAL':<40}{total_due:>9,.2f}",
              f"{'CASH':<40}{total_due + 100:>9,.2f}",
              f"{'CHANGE':<40}{100:>9,.2f}",
              "", "Thank you, visit again!"]

    return lines, items, round(total_due, 2), store


def _render(lines, condition, rng):
    size = 22
    font = _font(size)
    width, line_height, pad = 780, size + 8, 30
    image = Image.new("RGB", (width, pad * 2 + line_height * len(lines)), "white")
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(lines):
        draw.text((pad, pad + i * line_height), line, fill="black", font=font)

    if condition == 'small':
        image = image.resize((int(width * 0.42), int(image.height * 0.42)), Image.LANCZOS)
    elif condition == 'blurry':
        image = image.resize((int(width * 0.7), int(image.height * 0.7)), Image.LANCZOS)
        image = image.filter(ImageFilter.GaussianBlur(0.7))
    elif condition == 'noisy':
        pixels = image.load()
        for _ in range(int(image.width * image.height * 0.02)):
            x, y = rng.randrange(image.width), rng.randrange(image.height)
            grey = rng.randrange(60, 200)
            pixels[x, y] = (grey, grey, grey)
    elif condition == 'low_contrast':
        image = Image.blend(image, Image.new("RGB", image.size, (150, 150, 150)), 0.4)
    elif condition == 'rotated':
        image = image.rotate(180, expand=True)
    return image


def generate(out_dir, count, seed=20260814):
    rng = random.Random(seed)
    images_dir = os.path.join(out_dir, 'ocr_receipts')
    truth_dir = os.path.join(out_dir, 'ground_truth')
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(truth_dir, exist_ok=True)

    for index in range(1, count + 1):
        condition = CONDITIONS[(index - 1) % len(CONDITIONS)]
        lines, items, total, store = _receipt_lines(rng, condition)
        image = _render(lines, condition, rng)

        stem = f"synthetic_{index:03d}"
        extension = '.jpg' if condition in ('blurry', 'noisy') else '.png'
        image.save(os.path.join(images_dir, stem + extension))

        with open(os.path.join(truth_dir, stem + '.json'), 'w', encoding='utf-8') as f:
            json.dump({
                "receipt_id": stem,
                "image_file": stem + extension,
                "source": "synthetic",
                "condition": condition,
                "store_name": store,
                "note": "Rendered test receipt, not a photograph of a real receipt.",
                "items": items,
                "total": total,
            }, f, indent=2)

    print(f"Generated {count} synthetic receipts in {images_dir}")
    print(f"Ground truth written to {truth_dir}")
    print("\nREMINDER: these are rendered images. Accuracy measured on them is an\n"
          "optimistic upper bound - photograph real receipts for the report figures.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=30)
    parser.add_argument('--out', default=HERE)
    args = parser.parse_args()
    generate(args.out, args.count)
