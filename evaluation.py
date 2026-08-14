"""
Evaluation harness for the OCR + parsing pipeline.

Compares what the pipeline extracts from receipt images against hand-written
ground truth and reports accuracy, precision/recall/F1 and timings.

    python evaluation.py                       # uses dataset/ocr_receipts + dataset/ground_truth
    python evaluation.py --images my/images --truth my/truth
    python evaluation.py --csv results.csv     # also write a per-receipt CSV

Ground truth: one JSON file per image (see dataset/ground_truth/EXAMPLE_*.json).

NOTE: this script only reports numbers measured on the receipts you provide.
It never invents results - with no images present it reports that there is
nothing to evaluate.
"""

import argparse
import csv
import json
import os
import time

from ocr_processor import image_to_receipt_text, OCRError, is_image_file
from receipt_processor import parse_receipt_text
from unit_utils import normalize_unit

DEFAULT_IMAGES = os.path.join('dataset', 'ocr_receipts')
DEFAULT_TRUTH  = os.path.join('dataset', 'ground_truth')

NAME_MATCH_RATIO = 0.8      # extracted vs expected product name similarity
PRICE_TOLERANCE  = 0.01     # rupees


def _similar(a, b):
    from difflib import SequenceMatcher
    return SequenceMatcher(None, (a or '').lower().strip(),
                           (b or '').lower().strip()).ratio()


def _match_items(expected, extracted):
    """
    Pair up expected and extracted items by product name (greedy, best first).
    Returns (pairs, unmatched_expected, unmatched_extracted).
    """
    pairs, remaining = [], list(extracted)
    unmatched_expected = []
    for want in expected:
        best, best_ratio = None, 0.0
        for got in remaining:
            ratio = _similar(want.get('product_name'), got.get('product_name'))
            if ratio > best_ratio:
                best, best_ratio = got, ratio
        if best is not None and best_ratio >= NAME_MATCH_RATIO:
            remaining.remove(best)
            pairs.append((want, best))
        else:
            unmatched_expected.append(want)
    return pairs, unmatched_expected, remaining


def evaluate_receipt(image_path, truth):
    """Run the pipeline on one image and score it against its ground truth."""
    result = {
        "receipt": os.path.basename(image_path),
        "condition": truth.get('condition', ''),
        "ocr_seconds": None, "total_seconds": None,
        "expected": len(truth.get('items', [])),
        "extracted": 0, "name_ok": 0, "unit_ok": 0, "price_ok": 0,
        "quantity_ok": 0, "complete_ok": 0, "error": None,
    }

    started = time.perf_counter()
    try:
        ocr_start = time.perf_counter()
        text = image_to_receipt_text(image_path)
        result["ocr_seconds"] = round(time.perf_counter() - ocr_start, 3)
    except OCRError as e:
        result["error"] = str(e)
        result["total_seconds"] = round(time.perf_counter() - started, 3)
        return result

    items = parse_receipt_text(text)['items']
    result["extracted"] = len(items)
    result["total_seconds"] = round(time.perf_counter() - started, 3)

    pairs, _missed, _extra = _match_items(truth.get('items', []), items)
    for want, got in pairs:
        name_ok  = _similar(want.get('product_name'), got.get('product_name')) >= NAME_MATCH_RATIO
        unit_ok  = normalize_unit(want.get('unit')) == normalize_unit(got.get('unit'))
        price_ok = abs(float(want.get('price', 0)) - float(got.get('price', 0))) <= PRICE_TOLERANCE
        qty_ok   = int(want.get('quantity', 1)) == int(got.get('quantity', 1))

        result["name_ok"]     += int(name_ok)
        result["unit_ok"]     += int(unit_ok)
        result["price_ok"]    += int(price_ok)
        result["quantity_ok"] += int(qty_ok)
        result["complete_ok"] += int(name_ok and unit_ok and price_ok and qty_ok)
    return result


def summarise(results):
    """Aggregate per-receipt results into the report metrics."""
    scored = [r for r in results if not r["error"]]
    expected  = sum(r["expected"]  for r in scored)
    extracted = sum(r["extracted"] for r in scored)
    correct   = sum(r["complete_ok"] for r in scored)

    def pct(part, whole):
        return round(part / whole * 100, 1) if whole else 0.0

    precision = correct / extracted if extracted else 0.0
    recall    = correct / expected if expected else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    ocr_times = [r["ocr_seconds"] for r in scored if r["ocr_seconds"] is not None]
    all_times = [r["total_seconds"] for r in scored if r["total_seconds"] is not None]

    return {
        "receipts_evaluated":        len(scored),
        "receipts_failed":           len(results) - len(scored),
        "expected_items":            expected,
        "extracted_items":           extracted,
        "product_name_accuracy_pct": pct(sum(r["name_ok"] for r in scored), expected),
        "unit_accuracy_pct":         pct(sum(r["unit_ok"] for r in scored), expected),
        "price_accuracy_pct":        pct(sum(r["price_ok"] for r in scored), expected),
        "quantity_accuracy_pct":     pct(sum(r["quantity_ok"] for r in scored), expected),
        "complete_item_accuracy_pct": pct(correct, expected),
        "precision": round(precision, 3),
        "recall":    round(recall, 3),
        "f1_score":  round(f1, 3),
        "avg_ocr_seconds":   round(sum(ocr_times) / len(ocr_times), 3) if ocr_times else None,
        "avg_total_seconds": round(sum(all_times) / len(all_times), 3) if all_times else None,
    }


def run(images_dir, truth_dir, csv_path=None):
    if not os.path.isdir(images_dir):
        print(f"No image folder at '{images_dir}' - nothing to evaluate.")
        return None

    images = [f for f in sorted(os.listdir(images_dir)) if is_image_file(f)]
    if not images:
        print(f"No receipt images in '{images_dir}' - nothing to evaluate.\n"
              f"Add your own receipt images and matching ground-truth JSON files.")
        return None

    results = []
    for filename in images:
        stem = os.path.splitext(filename)[0]
        truth_path = os.path.join(truth_dir, f"{stem}.json")
        if not os.path.exists(truth_path):
            print(f"  skipping {filename}: no ground truth at {truth_path}")
            continue
        with open(truth_path, encoding='utf-8') as f:
            truth = json.load(f)
        result = evaluate_receipt(os.path.join(images_dir, filename), truth)
        results.append(result)
        status = result["error"] or (f"{result['complete_ok']}/{result['expected']} items fully correct")
        print(f"  {filename:35} {status}")

    if not results:
        print("No receipt/ground-truth pairs found - nothing to evaluate.")
        return None

    summary = summarise(results)
    # plain ASCII: the Windows console uses cp1252 and cannot print box drawing
    print("\n--- Evaluation summary ---------------------------")
    for key, value in summary.items():
        print(f"{key:30} {value}")

    if csv_path:
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(results)
        print(f"\nPer-receipt results written to {csv_path}")

    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', default=DEFAULT_IMAGES)
    parser.add_argument('--truth',  default=DEFAULT_TRUTH)
    parser.add_argument('--csv',    default=None)
    args = parser.parse_args()
    run(args.images, args.truth, args.csv)
