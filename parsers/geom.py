"""Word-level geometry dump for a page: x position + y band per token."""
import sys
import pdfplumber

PDF = "D:/gearbox-selector/data/catalog/Elecon G B_EON-Series.pdf"
page_no = int(sys.argv[1])

with pdfplumber.open(PDF) as pdf:
    page = pdf.pages[page_no - 1]
    ws = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    for w in sorted(ws, key=lambda w: (round(w["top"], 1), w["x0"])):
        print(f"top={w['top']:7.1f} x0={w['x0']:7.1f} x1={w['x1']:7.1f}  {w['text']}")