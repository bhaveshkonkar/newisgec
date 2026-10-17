"""Structural recon of the Elecon EON-Series PDF.

Reads the catalog, reports per page:
  - text-layer status (is a page of selectable text or an image?)
  - first meaningful line (to identify section headers)
  - how many table-like grids pdfplumber detects, with column counts

Output: data/recon.txt (tab separated). Use to map page ranges per table type.
"""
import sys
from pathlib import Path

import pdfplumber

PDF = Path(__file__).resolve().parents[1] / "data/catalog/Elecon G B_EON-Series.pdf"
OUT = Path(__file__).resolve().parents[1] / "data/recon.txt"


def first_text(text: str, limit: int = 120) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ""
    head = lines[0]
    # pull a couple of lines until something resembles a title/header
    joined = " | ".join(lines[:3])
    return joined[:limit]


def main() -> int:
    with pdfplumber.open(PDF) as pdf:
        n = len(pdf.pages)
        rows = []
        for i, page in enumerate(pdf.pages, start=1):
            chars = len(page.chars)
            text = page.extract_text() or ""
            tbl = page.extract_tables()
            widths = sorted({len(t) for t in tbl})
            rows.append((i, chars, len(tbl), ",".join(map(str, widths)),
                         "TEXT" if chars > 50 else ("SCAN" if chars == 0 else "SPARSE"),
                         first_text(text)))
        OUT.write_text(
            "page\tchars\ttables\tcol_counts\tkind\thead\n" +
            "\n".join(f"{a}\t{b}\t{c}\t{d}\t{e}\t{f}" for a, b, c, d, e, f in rows) +
            "\n", encoding="utf-8")
        text_layers = sum(1 for r in rows if r[4] == "TEXT")
        scans = sum(1 for r in rows if r[4] == "SCAN")
        sparse = sum(1 for r in rows if r[4] == "SPARSE")
        print(f"pages={n}  text_layer={text_layers}  scanned_no_text={scans}  sparse={sparse}")
        print(f"recon written -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())