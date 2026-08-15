"""
Lightweight performance measurement.

Used to report how long each algorithm stage takes (OCR, parsing, matching,
comparison, recommendation). Timings are stored with the analysis and printed
to the console in debug mode - they are never shown to normal users.

Usage:
    timings = Timings()
    with timings.measure('ocr'):
        text = image_to_receipt_text(path)
    timings.as_dict()   -> {'ocr': 1.241, 'total': 1.33}
"""

import time
from contextlib import contextmanager


class Timings:
    """Collects named stage durations in seconds (rounded to milliseconds)."""

    def __init__(self):
        self._started = time.perf_counter()
        self._stages = {}

    @contextmanager
    def measure(self, stage):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.add(stage, time.perf_counter() - start)

    def add(self, stage, seconds):
        """Add to a stage, so a stage measured inside a loop accumulates."""
        self._stages[stage] = round(self._stages.get(stage, 0.0) + seconds, 3)

    def as_dict(self):
        data = dict(self._stages)
        data['total'] = round(time.perf_counter() - self._started, 3)
        return data

    def log(self, label='processing'):
        parts = ', '.join(f"{stage}: {value:.3f}s"
                          for stage, value in self.as_dict().items())
        print(f"[perf] {label} - {parts}")
