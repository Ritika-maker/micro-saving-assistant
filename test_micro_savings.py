"""
Unit tests for the Micro-Savings Assistant algorithms.

Run with:   python -m unittest test_micro_savings -v
       or:  python test_micro_savings.py

The tests only exercise pure functions, so they do not touch users.db and can
be run safely at any time.
"""

import unittest

from ocr_processor import clean_ocr_text, is_image_file
from unit_utils import (normalize_unit, parse_quantity_and_unit,
                        calculate_unit_price, units_comparable, to_base_quantity)
from receipt_processor import (parse_receipt_text, build_item, fuzzy_match,
                               match_item, classify_confidence)
import price_comparison
from price_comparison import find_alternatives
from recommendation_engine import recommend_alternatives, _score_alternative

import pandas as pd


CATALOGUE = [
    {"product_name": "Amul Milk 1L", "category": "Dairy", "brand": "Amul",
     "unit": "liter", "health_score": 8, "price": 90, "unit_price": 90},
    {"product_name": "Mother Dairy Milk 1L", "category": "Dairy", "brand": "Mother Dairy",
     "unit": "liter", "health_score": 7, "price": 80, "unit_price": 80},
    {"product_name": "Nestle Milk 1L", "category": "Dairy", "brand": "Nestle",
     "unit": "liter", "health_score": 6, "price": 110, "unit_price": 110},
    {"product_name": "Basmati Rice 1kg", "category": "Grains", "brand": "Generic",
     "unit": "kg", "health_score": 8, "price": 180, "unit_price": 180},
    {"product_name": "Brown Rice 1kg", "category": "Grains", "brand": "Generic",
     "unit": "kg", "health_score": 9, "price": 120, "unit_price": 120},
]


class TestOcrTextNormalization(unittest.TestCase):
    """1. OCR number normalization and cleaning."""

    def test_thousands_separator_removed(self):
        self.assertIn("1250", clean_ocr_text("Basmati Rice 5kg   1,250"))

    def test_decimal_comma_becomes_point(self):
        self.assertIn("150.50", clean_ocr_text("Coca Cola 2L   150,50"))

    def test_currency_words_and_symbols_removed(self):
        cleaned = clean_ocr_text("Milk    Rs. 90")
        self.assertNotIn("Rs", cleaned)
        self.assertTrue(cleaned.endswith("90"))

    def test_letter_digit_confusion_fixed_inside_numbers(self):
        self.assertIn("250", clean_ocr_text("Noodles 25O"))
        self.assertIn("120", clean_ocr_text("Oil 1L l20"))

    def test_product_names_are_not_digit_corrected(self):
        # 'Ilam' and 'Oil' must survive - only numeric tokens are repaired
        self.assertIn("Ilam Tea 200g 350", clean_ocr_text("Ilam Tea 200g  350"))
        self.assertIn("Olive Oil", clean_ocr_text("Olive Oil 500ml 850"))

    def test_pack_size_letter_read_as_digit_is_repaired(self):
        self.assertIn("5kg", clean_ocr_text("Basmati Rice Skg 850"))
        self.assertIn("1kg", clean_ocr_text("Rice lkg 120"))

    def test_ordinary_words_ending_in_a_unit_letter_are_left_alone(self):
        # 'Log' must not become '10g', 'Bag' must not become '8ag'
        self.assertIn("Log Book", clean_ocr_text("Log Book 250"))
        self.assertIn("Bag of Rice", clean_ocr_text("Bag of Rice 500"))

    def test_artifacts_removed_but_lines_preserved(self):
        cleaned = clean_ocr_text("Milk 90\n=======\n\nBread 120")
        self.assertEqual(cleaned.splitlines(), ["Milk 90", "Bread 120"])

    def test_supported_image_extensions(self):
        self.assertTrue(is_image_file("receipt.JPG"))
        self.assertTrue(is_image_file("receipt.png"))
        self.assertFalse(is_image_file("receipt.pdf"))


class TestUnitNormalization(unittest.TestCase):
    """2. Unit normalization."""

    def test_spellings_map_to_canonical_units(self):
        for text, expected in [('KG', 'kg'), ('kgs', 'kg'), ('grams', 'g'),
                               ('litre', 'l'), ('LITERS', 'l'), ('1L', 'l'),
                               ('ml', 'ml'), ('pieces', 'pcs'), ('dozen', 'pcs'),
                               ('packet', 'pack')]:
            self.assertEqual(normalize_unit(text), expected, text)

    def test_unknown_unit_returns_empty(self):
        self.assertEqual(normalize_unit('sachet'), '')

    def test_base_conversions(self):
        self.assertEqual(to_base_quantity(1, 'kg'), 1000.0)
        self.assertEqual(to_base_quantity(1, 'L'), 1000.0)
        self.assertEqual(to_base_quantity(500, 'ml'), 500.0)

    def test_pack_is_never_converted(self):
        # 1 pack must not silently become 10 pieces
        self.assertIsNone(to_base_quantity(1, 'pack'))
        self.assertFalse(units_comparable('pack', 'pcs'))

    def test_comparability(self):
        self.assertTrue(units_comparable('kg', 'g'))
        self.assertTrue(units_comparable('L', 'ml'))
        self.assertFalse(units_comparable('kg', 'L'))
        self.assertFalse(units_comparable('', 'kg'))


class TestQuantityExtraction(unittest.TestCase):
    """3. Quantity and unit extraction."""

    def test_quantity_formats(self):
        cases = {
            '2 x Milk 1L':      ('Milk', 2, '1L'),
            '2X Milk':          ('Milk', 2, ''),
            'Milk x2':          ('Milk', 2, ''),
            'Milk 2 pcs':       ('Milk', 2, 'pcs'),
            'Eggs 12 pcs':      ('Eggs', 12, 'pcs'),
            'Eggs 12pcs':       ('Eggs', 12, 'pcs'),
            'Basmati Rice 5kg': ('Basmati Rice', 1, '5kg'),
            'Sunflower Oil 1 litre': ('Sunflower Oil', 1, '1L'),
            'Eggs 1 dozen':     ('Eggs', 12, 'pcs'),
        }
        for text, (name, qty, unit) in cases.items():
            parsed = parse_quantity_and_unit(text)
            self.assertEqual((parsed['name'], parsed['quantity'], parsed['unit']),
                             (name, qty, unit), text)

    def test_container_word_in_the_name_does_not_hide_the_quantity(self):
        # 'Pack' belongs to the product name here; '6 pcs' is the quantity
        parsed = parse_quantity_and_unit('Bun Pack 6 pcs')
        self.assertEqual((parsed['name'], parsed['quantity'], parsed['unit']),
                         ('Bun Pack', 6, 'pcs'))

    def test_trailing_container_word_is_treated_as_the_unit(self):
        parsed = parse_quantity_and_unit('Oats 500g pack')
        self.assertEqual((parsed['name'], parsed['unit']), ('Oats', '500g'))

    def test_product_name_is_not_over_normalized(self):
        parsed = parse_quantity_and_unit('Amul Taaza Milk')
        self.assertEqual(parsed['name'], 'Amul Taaza Milk')
        self.assertEqual(parsed['quantity'], 1)

    def test_missing_quantity_defaults_to_one(self):
        self.assertEqual(parse_quantity_and_unit('Bread')['quantity'], 1)


class TestReceiptParsing(unittest.TestCase):
    """4. Receipt parsing into structured items."""

    RECEIPT = """SUPER MART
Kalimati, Kathmandu
Tel: 01-4567890
Date: 2026-08-14 14:32

Amul Milk 1L       100
Basmati Rice 5kg   750
Eggs 12 pcs        210
2 x Milk 1L        200

SUBTOTAL          1260
VAT 13%            163
TOTAL             1423
CASH              1500
CHANGE              77
"""

    def test_only_grocery_items_are_extracted(self):
        items = parse_receipt_text(self.RECEIPT)['items']
        self.assertEqual([i['product_name'] for i in items],
                         ['Amul Milk', 'Basmati Rice', 'Eggs', 'Milk'])

    def test_structured_fields(self):
        items = parse_receipt_text(self.RECEIPT)['items']
        self.assertEqual(
            {k: items[0][k] for k in ('product_name', 'quantity', 'unit', 'price')},
            {'product_name': 'Amul Milk', 'quantity': 1, 'unit': '1L', 'price': 100.0})
        self.assertEqual(
            {k: items[2][k] for k in ('product_name', 'quantity', 'unit', 'price')},
            {'product_name': 'Eggs', 'quantity': 12, 'unit': 'pcs', 'price': 210.0})

    def test_total_is_captured_but_not_counted_as_an_item(self):
        parsed = parse_receipt_text(self.RECEIPT)
        self.assertEqual(parsed['total'], 1423.0)
        self.assertNotIn('TOTAL', [i['name'].upper() for i in parsed['items']])

    def test_metadata_lines_skipped_but_real_products_kept(self):
        parsed = parse_receipt_text("Date Palm 250\nTotal Mix Bread 120\nTel 01-4567890")
        self.assertEqual([i['product_name'] for i in parsed['items']],
                         ['Date Palm', 'Total Mix Bread'])

    def test_plain_text_input_still_parses(self):
        items = parse_receipt_text("Amul Milk 1L    90\nWhole Wheat Bread 400g    120")['items']
        self.assertEqual(len(items), 2)
        self.assertEqual(items[1]['price'], 120.0)


class TestUnitPriceAndSavings(unittest.TestCase):
    """6. Quantity-aware unit price and savings calculation."""

    def test_unit_price_from_quantity(self):
        self.assertEqual(calculate_unit_price(200, 2), 100.0)
        self.assertEqual(calculate_unit_price(100, 1), 100.0)
        self.assertEqual(calculate_unit_price(210, 12), 17.5)

    def test_build_item_matches_specification(self):
        item = build_item('2 x Milk 1L', 200)
        self.assertEqual(item['product_name'], 'Milk')
        self.assertEqual(item['quantity'], 2)
        self.assertEqual(item['unit'], '1L')
        self.assertEqual(item['price'], 200)
        self.assertEqual(item['unit_price'], 100)

    def test_total_savings_multiplied_by_quantity(self):
        # 2 x Milk at NPR 100/unit vs an alternative at NPR 80/unit
        item = build_item('2 x Amul Milk 1L', 200)
        alts = [dict(CATALOGUE[1], size_similarity=1.0, unit_comparable=True,
                     best_store='General Market', store_prices=[], unit_display='1L')]
        recs = recommend_alternatives(item, CATALOGUE, alts, item_brand='Amul')
        self.assertEqual(recs[0]['savings_per_unit'], 20)
        self.assertEqual(recs[0]['savings_amount'], 40)     # 20 x 2 units


class TestFuzzyMatching(unittest.TestCase):
    """5. Fuzzy matching and 9. confidence classification."""

    def test_exact_name_matches_with_high_confidence(self):
        match, score = fuzzy_match('Amul Milk 1L', CATALOGUE)
        self.assertEqual(match['product_name'], 'Amul Milk 1L')
        self.assertEqual(classify_confidence(score)[0], 'high')

    def test_ocr_damaged_name_still_matches(self):
        match, score = fuzzy_match('Amu1 Mlilk 1L', CATALOGUE)
        self.assertIsNotNone(match)
        self.assertGreater(score, 0.35)

    def test_unrelated_name_does_not_match(self):
        match, score = fuzzy_match('Bicycle Tyre Tube', CATALOGUE)
        self.assertIsNone(match)
        self.assertEqual(classify_confidence(score)[0], 'none')

    def test_match_item_tries_several_spellings(self):
        item = build_item('2 x Milk 1L', 200)
        match, score, level, label = match_item(item, CATALOGUE)
        self.assertIsNotNone(match)
        self.assertIn(level, ('high', 'medium', 'low'))

    def test_confidence_bands(self):
        self.assertEqual(classify_confidence(0.92)[0], 'high')
        self.assertEqual(classify_confidence(0.75)[0], 'high')
        self.assertEqual(classify_confidence(0.60)[0], 'medium')
        self.assertEqual(classify_confidence(0.48)[0], 'low')
        self.assertEqual(classify_confidence(0.10)[0], 'none')


class TestPriceComparison(unittest.TestCase):
    """8. Price comparison uses unit prices, not line totals."""

    def setUp(self):
        # find_alternatives enriches results from the DB; stub that out so the
        # test stays independent of users.db
        self._original = price_comparison.load_products_with_store_prices
        price_comparison.load_products_with_store_prices = lambda: []

    def tearDown(self):
        price_comparison.load_products_with_store_prices = self._original

    def test_alternatives_are_cheaper_and_same_category(self):
        item = build_item('Basmati Rice 1kg', 250)
        alts = find_alternatives(dict(item, name='Basmati Rice 1kg'),
                                 pd.DataFrame(CATALOGUE))
        self.assertTrue(alts)
        self.assertTrue(all(a['category'] == 'Grains' for a in alts))
        self.assertTrue(all(a['unit_price'] < 250 for a in alts))

    def test_line_total_is_not_compared_directly(self):
        # 2 x Milk for NPR 200 is NPR 100/unit: NOT 20% cheaper than Amul at 90
        item = build_item('2 x Amul Milk 1L', 200)
        alts = find_alternatives(dict(item, name='Amul Milk 1L'),
                                 pd.DataFrame(CATALOGUE))
        for alt in alts:
            self.assertLess(alt['unit_price'], item['unit_price'])
            self.assertLess(alt['savings'], 100)


class TestRecommendationScoring(unittest.TestCase):
    """7. Weighted, explainable recommendation scoring."""

    def test_score_is_weighted_sum(self):
        score, parts = _score_alternative(savings_pct=50, name_similarity=1.0,
                                          size_similarity=1.0, health_score=10,
                                          same_category=True, different_brand=True)
        self.assertEqual(parts, {"savings": 1.0, "similarity": 1.0,
                                 "health": 1.0, "relevance": 1.0})
        self.assertAlmostEqual(score, 1.0, places=3)

    def test_cheapest_is_not_automatically_the_winner(self):
        # Two alternatives with almost the same saving: the one that is a
        # comparable product (same pack size, similar name) must rank first,
        # even though it is one rupee more expensive.
        item = build_item('Amul Milk 1L', 100)
        slightly_cheaper_but_unrelated = dict(CATALOGUE[3], unit_price=79,
                                              category='Dairy', size_similarity=None,
                                              unit_comparable=False,
                                              store_prices=[], best_store='')
        similar_product = dict(CATALOGUE[1], unit_price=80, size_similarity=1.0,
                               unit_comparable=True, store_prices=[],
                               best_store='General Market')
        recs = recommend_alternatives(item, CATALOGUE,
                                      [slightly_cheaper_but_unrelated, similar_product],
                                      item_brand='Amul')
        self.assertEqual(recs[0]['alternative'], 'Mother Dairy Milk 1L')
        self.assertGreater(recs[0]['recommendation_score'],
                           recs[1]['recommendation_score'])

    def test_every_recommendation_explains_itself(self):
        item = build_item('Amul Milk 1L', 100)
        alts = [dict(CATALOGUE[1], size_similarity=1.0, unit_comparable=True,
                     store_prices=[], best_store='General Market', unit_display='1L')]
        rec = recommend_alternatives(item, CATALOGUE, alts, item_brand='Amul')[0]
        self.assertTrue(rec['reason'])
        self.assertTrue(rec['factors'])
        self.assertIn('savings', rec['score_components'])

    def test_same_brand_alternatives_are_skipped(self):
        item = build_item('Amul Milk 1L', 100)
        alts = [dict(CATALOGUE[0], unit_price=70, size_similarity=1.0,
                     unit_comparable=True, store_prices=[], best_store='')]
        self.assertEqual(recommend_alternatives(item, CATALOGUE, alts,
                                                item_brand='Amul'), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
