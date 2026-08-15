# OCR receipt images

Put your own receipt images here (`.jpg`, `.jpeg`, `.png`), one file per
receipt, and add a matching ground-truth JSON in `../ground_truth/`.

This folder is intentionally empty: generating fake receipt images would give
meaningless accuracy figures, so the evaluation only runs on real receipts you
provide.

Suggested coverage for the report (~30–50 receipts):

| Condition            | What it tests                          |
|----------------------|----------------------------------------|
| clear                | baseline accuracy                      |
| blurry / low light   | pre-processing and the quality gate    |
| small / low-res      | upscaling                              |
| long receipt         | many items, line structure             |
| different layouts    | different stores and column styles     |
| with quantities      | `2 x Milk`, `Eggs 12 pcs`              |
| decimal prices       | `150.50`                               |
| thousands separators | `1,250`                                |
| different units      | kg, g, L, ml, pcs, pack, dozen         |

Then run:

```bash
python evaluation.py
```
