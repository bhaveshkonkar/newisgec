"""Dump raw text of selected pages for layout study."""
import sys
import pdfplumber

PDF = "D:/gearbox-selector/data/catalog/Elecon G B_EON-Series.pdf"
pages = [int(a) for a in sys.argv[1:]]

with pdfplumber.open(PDF) as pdf:
    for p in pages:
        print(f"\n================ PAGE {p} ================")
        print(pdf.pages[p - 1].extract_text())