# Dataset folder

Everything in this folder is **development / demo data for the project**.
None of it is collected market data, and none of it should be presented as
real pricing or as a nutritional assessment.

```
dataset/
├── build_demo_dataset.py   # generates products.csv, stores.csv, store_prices.csv
├── load_demo_dataset.py    # loads the CSVs into a database
├── products.csv            # 233 demo grocery products (15 categories)
├── stores.csv              # 6 demo stores
├── store_prices.csv        # price per product per store
├── product_aliases.csv     # OCR-style misspellings for fuzzy-matching tests
├── make_synthetic_receipts.py  # generates rendered test receipts + ground truth
├── ocr_receipts/           # receipt images (synthetic_*, plus your own)
└── ground_truth/           # one JSON per receipt image
```

## How the demo data is produced

`build_demo_dataset.py` builds the catalogue from a fixed table of
category → product → brand → pack size, and prices each product from a base
price multiplied by:

* a **size factor** (a 5 kg bag costs ~4.7x a 1 kg bag), and
* a fixed **per-store multiplier** (0.97 – 1.08).

`updated_at` is staggered per store (0, 1, 3, 6, 12 and 25 days old) so the
price-freshness labels can be demonstrated. Re-running the script always
produces the same files.

To regenerate:

```bash
python dataset/build_demo_dataset.py
```

## Loading it

```bash
python dataset/load_demo_dataset.py                # writes demo.db (safe default)
python dataset/load_demo_dataset.py --db users.db  # load into the app database
```

The loader calls the same `models.upsert_product_price()` the app uses, so
existing rows are updated rather than deleted, and every price is also written
to `price_history` with `source='demo-dataset'`.

## OCR evaluation data

There are two kinds of evaluation data, and it matters which one you quote.

### a) Synthetic receipts (included, for development)

```bash
python dataset/make_synthetic_receipts.py --count 30
```

This renders 30 receipts (`ocr_receipts/synthetic_*.png|jpg`) with matching
ground truth, covering clear, small, blurry, noisy, low-contrast, long and
rotated (180°) conditions, three layouts, quantities, decimal prices,
thousands separators and mixed units. Every file is named `synthetic_*` and
its ground truth carries `"source": "synthetic"`.

They are **rendered images, not photographs**. Use them to check the pipeline
end to end and to compare algorithm versions. Accuracy measured on them is an
**optimistic upper bound** - if you quote it in the report, say so.

Measured on this synthetic set (30 receipts, 176 items):

| Metric | Result |
|---|---|
| Product name accuracy | 91.5% |
| Unit accuracy | 85.8% |
| Price accuracy | 79.5% |
| Quantity accuracy | 88.6% |
| Complete item accuracy | 73.9% |
| Precision / Recall / F1 | 0.769 / 0.739 / 0.754 |
| Avg OCR time | 1.44 s per receipt |
| Rejected as too low quality | 2 of 30 |

### b) Real receipts (you must supply these)

For a figure you can defend in a viva, photograph real receipts:

1. Put them (`.jpg` / `.jpeg` / `.png`) in `ocr_receipts/`.
   Aim for ~30–50 covering: clear receipts, blurry photos, long receipts,
   different layouts and stores, receipts with quantities, decimal prices and
   different units.
2. For each image `receipt_001.jpg`, hand-write `ground_truth/receipt_001.json`
   using the format in `ground_truth/EXAMPLE_receipt_001.json`:

```json
{
  "receipt_id": "receipt_001",
  "image_file": "receipt_001.jpg",
  "condition": "clear",
  "items": [
    { "product_name": "Amul Milk", "quantity": 1, "unit": "1L", "price": 100 }
  ],
  "total": 100
}
```

3. Run the evaluation:

```bash
python evaluation.py
```

It reports product-name / unit / price / quantity / complete-item accuracy,
precision, recall, F1 and average OCR and total processing times **for the
receipts present in the folder**. With no images present it says so instead of
producing numbers.

Delete the `synthetic_*` files first if you want figures for real receipts
only, otherwise the two sets are averaged together.

## Product aliases

`product_aliases.csv` lists OCR-style misspellings (`Amu1 Milk 1L`,
`Basmati Rce 1kg`, …) and the catalogue product each one should match. Use it
to check fuzzy-matching behaviour after changing the matching algorithm.
