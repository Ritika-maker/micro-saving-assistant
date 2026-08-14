"""
OCR module for the Micro-Savings Assistant.

Responsibility: turn a receipt image into clean, machine-readable TEXT.

Pipeline:
    Receipt image
      -> validation           (is_image_file / open + basic sanity checks)
      -> pre-processing       (preprocess_image)
      -> Tesseract OCR        (extract_text_from_image)
      -> text cleaning        (clean_ocr_text)
      -> receipt_processor.parse_receipt_text()   <- existing parser, unchanged flow

This module deliberately does NOT try to understand the receipt (items,
quantities, totals). Deciding what a line *means* stays the job of
receipt_processor.parse_receipt_text().
"""

import os
import re

try:
    import pytesseract
    from PIL import Image, ImageOps, ImageFilter, UnidentifiedImageError
    OCR_AVAILABLE = True
except ImportError:                                     # Pillow / pytesseract missing
    OCR_AVAILABLE = False

# Image formats the analyzer accepts (kept in one place so app.py can reuse it)
ALLOWED_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg')

# Pre-processing tuning constants
MIN_OCR_WIDTH = 1800          # upscale narrow images to at least this width
MAX_OCR_WIDTH = 2600          # but never blow them up beyond this (slow + no gain)
MIN_IMAGE_SIDE = 20           # anything smaller is treated as an empty image

# Tesseract settings.
# oem 3 = default LSTM engine, psm 6 = "a single uniform block of text",
# which matches the single-column layout of a shopping receipt.
OCR_CONFIG = '--oem 3 --psm 6'

# Mean word confidence reported by Tesseract (0-100).
GOOD_CONFIDENCE = 75          # above this the first attempt is accepted as-is
MIN_CONFIDENCE = 40           # below this the image is treated as unreadable


class OCRError(Exception):
    """Raised with a short, user-friendly message when OCR cannot be completed."""
    pass


# ── 1. File validation ────────────────────────────────────────────────────────

def is_image_file(filename):
    """True if the filename looks like a supported receipt image."""
    return bool(filename) and filename.lower().endswith(ALLOWED_IMAGE_EXTENSIONS)


# ── 2. Image pre-processing ───────────────────────────────────────────────────

def _otsu_threshold(gray_image):
    """
    Otsu's method: pick the grey level that best separates ink from paper.

    Works on the 256-bin histogram and chooses the threshold with the
    highest between-class variance. Pure Python, no extra dependency.
    """
    histogram = gray_image.histogram()[:256]
    total = sum(histogram)
    if total == 0:
        return 128

    sum_all = sum(i * histogram[i] for i in range(256))
    sum_background = 0.0
    weight_background = 0.0
    best_threshold, best_variance = 128, -1.0

    for t in range(256):
        weight_background += histogram[t]
        if weight_background == 0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break
        sum_background += t * histogram[t]
        mean_background = sum_background / weight_background
        mean_foreground = (sum_all - sum_background) / weight_foreground
        variance = weight_background * weight_foreground * \
            (mean_background - mean_foreground) ** 2
        if variance > best_variance:
            best_variance, best_threshold = variance, t

    return best_threshold


def _fix_orientation(image):
    """
    Correct rotation so the text is upright.

    First uses the EXIF orientation tag (phone photos), then asks Tesseract's
    orientation detection. OSD needs the optional 'osd' language data, so any
    failure is ignored and the image is returned unchanged.
    """
    image = ImageOps.exif_transpose(image)
    try:
        osd = pytesseract.image_to_osd(image)
        match = re.search(r'Rotate: (\d+)', osd)
        angle = int(match.group(1)) if match else 0
        if angle in (90, 180, 270):
            image = image.rotate(-angle, expand=True)
    except Exception:
        pass          # OSD unavailable or too little text - keep the original
    return image


def preprocess_image(image, binarize=False):
    """
    Prepare an image for OCR.

    Steps (each one is a standard OCR preparation technique):
      1. grayscale      - colour carries no information for text recognition
      2. resize         - Tesseract needs roughly 300 DPI, so small photos are
                          upscaled and very large ones are shrunk for speed
      3. median filter  - removes speckle noise from photos and scans
      4. autocontrast   - stretches faded receipt print back to full black/white
      5. binarize       - optional Otsu thresholding (pure black & white)

    Binarization is optional and OFF by default: measured on test receipts it
    helps faded/low-contrast images but loses thin strokes on already clean
    ones, so extract_text_from_image() only falls back to it when the first
    attempt has low confidence. Sharpening was tested as well and consistently
    made digit recognition slightly worse, so it is not applied.

    Returns a new PIL image; the original is not modified.
    """
    image = image.convert('L')                                   # 1. grayscale

    width, height = image.size                                   # 2. resize
    scale = None
    if width < MIN_OCR_WIDTH:
        scale = MIN_OCR_WIDTH / width
    elif width > MAX_OCR_WIDTH:
        scale = MAX_OCR_WIDTH / width
    if scale:
        image = image.resize((int(width * scale), int(height * scale)),
                             Image.LANCZOS)

    image = image.filter(ImageFilter.MedianFilter(size=3))        # 3. denoise
    image = ImageOps.autocontrast(image, cutoff=2)                # 4. contrast

    if binarize:                                                  # 5. binarize
        threshold = _otsu_threshold(image)
        image = image.point(lambda p: 255 if p > threshold else 0)

    return image


# ── 3. OCR ────────────────────────────────────────────────────────────────────

def _run_tesseract(image):
    """
    Run Tesseract once and return (text, mean_word_confidence).

    image_to_data is used instead of image_to_string because it also reports
    how confident the engine was about every word. Words are regrouped into
    their original lines, so the receipt's line structure is preserved for
    the parser.
    """
    try:
        data = pytesseract.image_to_data(image, config=OCR_CONFIG,
                                         output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractNotFoundError:
        raise OCRError("OCR engine (Tesseract) is not installed or not on PATH.")
    except Exception as e:
        raise OCRError(f"OCR engine failed while reading the image: {e}")

    lines = {}
    confidences = []
    for i, word in enumerate(data['text']):
        word = word.strip()
        if not word:
            continue
        key = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
        lines.setdefault(key, []).append(word)
        try:
            conf = float(data['conf'][i])
        except (TypeError, ValueError):
            conf = -1
        if conf >= 0:
            confidences.append(conf)

    text = '\n'.join(' '.join(words) for _, words in sorted(lines.items()))
    mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return text, mean_confidence


def extract_text_from_image(image_path):
    """
    Read a receipt image and return the RAW text produced by Tesseract.

    The lightly pre-processed image is tried first. If Tesseract is not
    confident about that read, the binarized version is tried as well and the
    more confident of the two results is used.

    Raises OCRError with a user-friendly message on any failure.
    """
    if not OCR_AVAILABLE:
        raise OCRError("OCR is not available: install Pillow and pytesseract.")

    if not os.path.exists(image_path):
        raise OCRError("The uploaded image could not be found on the server.")
    if os.path.getsize(image_path) == 0:
        raise OCRError("The uploaded image is empty.")

    try:
        with Image.open(image_path) as opened:
            opened.load()                    # forces decoding -> catches corruption
            image = opened.copy()
    except UnidentifiedImageError:
        raise OCRError("Unsupported or invalid image file. Please upload a JPG or PNG.")
    except OSError:
        raise OCRError("The image file appears to be corrupted and cannot be read.")

    if min(image.size) < MIN_IMAGE_SIDE:
        raise OCRError("The image is too small to contain readable receipt text.")

    image = _fix_orientation(image)

    # Attempt 1: light pre-processing (best for clear photos and scans)
    best_text, best_confidence = _run_tesseract(preprocess_image(image))

    # Attempt 2: binarized image, only needed when the first read was weak
    if best_confidence < GOOD_CONFIDENCE:
        text, confidence = _run_tesseract(preprocess_image(image, binarize=True))
        if confidence > best_confidence:
            best_text, best_confidence = text, confidence

    if not best_text.strip():
        raise OCRError("No readable text was found in this image. "
                       "Try a clearer, well-lit photo of the receipt.")
    if best_confidence < MIN_CONFIDENCE:
        raise OCRError("The image quality is too low to read the receipt "
                       "reliably. Please upload a sharper, well-lit photo.")

    return best_text


# ── 4. Text cleaning / normalization ──────────────────────────────────────────

# Currency words and symbols written right before a price ("Rs.250", "NPR 90")
_CURRENCY_PREFIX = re.compile(r'\b(?:rs|npr|inr)\b\.?\s*(?=\d)', re.IGNORECASE)
_CURRENCY_SYMBOLS = re.compile(r'[₹$£€]')
# A token that should be a number but may contain letters Tesseract confused
_NUMERIC_TOKEN = re.compile(r'(?<![A-Za-z])[0-9OolI|]{2,}(?:[.,][0-9OolI|]+)*(?![A-Za-z])')
# A pack size whose number was read as a letter: 'Skg' -> '5kg', 'lkg' -> '1kg'
_SIZE_TOKEN = re.compile(r'(?<![A-Za-z0-9])([0-9OoIlSsBZz]{1,5})(kg|mg|ml|g|l)(?![A-Za-z])')
_LETTER_TO_DIGIT = {'O': '0', 'o': '0', 'I': '1', 'l': '1', '|': '1',
                    'S': '5', 's': '5', 'B': '8', 'Z': '2', 'z': '2'}


def _fix_numeric_token(match):
    """
    Repair digit-lookalike characters inside a token that is clearly a number.

    Only tokens that already contain at least one real digit are touched, so
    product names such as 'Oil' or 'Ilam Tea' are never modified.
    """
    token = match.group(0)
    if not any(ch.isdigit() for ch in token):
        return token
    return (token.replace('O', '0').replace('o', '0')
                 .replace('I', '1').replace('l', '1').replace('|', '1'))


def _fix_size_token(match):
    """
    Repair a pack size where the digit was read as a letter ('Skg' -> '5kg').

    Only a SINGLE leading letter is corrected, or a token that already
    contains a real digit. That keeps ordinary words safe: 'log' would become
    '10g' if two letters were allowed to change, so it is left alone.
    """
    number, unit = match.group(1), match.group(2)
    if not any(ch.isdigit() for ch in number) and len(number) > 1:
        return match.group(0)
    fixed = ''.join(_LETTER_TO_DIGIT.get(ch, ch) for ch in number)
    if not fixed.isdigit():
        return match.group(0)
    return f"{fixed}{unit}"


def _normalize_numbers(line):
    """
    Make numbers safe for the existing parser.

      1,250      -> 1250      (thousands separator removed)
      1250,00    -> 1250.00   (decimal comma becomes a decimal point)
      25O / 12l  -> 250 / 121 (OCR letter/digit confusion inside numbers)

    The parser's price pattern is (\\d+\\.?\\d*)$, so a comma left inside a
    number would make it read '1,250' as just 250 - hence this step.
    """
    line = _CURRENCY_SYMBOLS.sub(' ', line)
    line = _CURRENCY_PREFIX.sub('', line)
    line = _NUMERIC_TOKEN.sub(_fix_numeric_token, line)
    line = _SIZE_TOKEN.sub(_fix_size_token, line)

    # thousands separators: comma followed by exactly three digits
    while re.search(r'\d,\d{3}(?!\d)', line):
        line = re.sub(r'(\d),(\d{3})(?!\d)', r'\1\2', line)
    # decimal comma: comma followed by exactly two digits at the end of a number
    line = re.sub(r'(\d),(\d{2})(?!\d)', r'\1.\2', line)
    return line


def clean_ocr_text(raw_text):
    """
    Clean raw OCR output before it reaches the receipt parser.

    Removes noise while carefully preserving the things the parser needs:
    line structure, item names, quantities, numbers and decimal points.
    """
    if not raw_text:
        return ''

    cleaned_lines = []
    for line in raw_text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        line = line.replace('\t', ' ')
        # strip decorative separators such as ---- , ==== , ****
        line = re.sub(r'[-=_*~]{3,}', ' ', line)
        line = _normalize_numbers(line)
        line = re.sub(r'\s+', ' ', line).strip()
        # drop leading/trailing OCR artifacts, keep letters/digits at the edges
        line = re.sub(r'^[^\w]+|[^\w%.)]+$', '', line).strip()

        if not line:
            continue
        if not any(ch.isalnum() for ch in line):        # pure punctuation noise
            continue
        if len(line) < 2:                               # stray single character
            continue
        cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)


def image_to_receipt_text(image_path):
    """
    Convenience wrapper used by the /upload route:
    image file -> pre-processing -> OCR -> cleaned text ready for the parser.
    """
    return clean_ocr_text(extract_text_from_image(image_path))


if __name__ == '__main__':
    # Quick manual check:  python ocr_processor.py uploads/receipt.jpg
    import sys
    if len(sys.argv) < 2:
        print("Usage: python ocr_processor.py <image path>")
    else:
        try:
            print(image_to_receipt_text(sys.argv[1]))
        except OCRError as err:
            print(f"OCR error: {err}")
