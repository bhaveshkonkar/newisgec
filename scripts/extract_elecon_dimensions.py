"""Extract the dimension tables Elecon prints on the same pages as the weights.

Every one of the weight pages (18..57) carries two more tables besides the
weight column:

  * the shaft table -- input/intermediate/output shaft diameters and the
    overall dimensions (V, W, D, L, M1, M2, A, d1, Y1):
      - S1 p18-19 : d l l d l l M V W D L M
      - S2 p20-23 : d l l d l l d l l M V W D L M d Y   (T: ... M V W M d Y)
      - S3 p26-29 : d l l d l l d l l M V W D L M A d Y (T: ... M V W M A d Y)
      - S4 p32-33 : d l d l M h D L M A d Y             (T: d l d l M h M A d Y)
      - K2 p36-39 : d l l d l l V W D L M M A d Y       (T: ... V W M A d Y)
      - K3 p44-47 : d l l d l l V W D L M M A d Y       (T: ... V W M A d Y)
      - K4 p54-57 : d l d l D L M M A d Y               (T: d l d l M A d Y)
  * the foundation table below it -- A B C C1 E F h H1 H2 J(K) N O P R S T
    (the torque-arm pages print A B C C1 G H H1 H2 J K O R instead).

The S2/K2 pages print every glyph twice, so the same de-doubling that unlocks
the weights unlocks the dimensions.  Column names are derived straight from the
header's own letters (shaft d/l blocks become d1/l1a/l1b..., the trailing d is
d_out, the repeated M is M1/M2, C and H repeats become C1/H1/H2), so the two
mounting layouts and the page-to-page wobble are handled without a table of
fixed column counts.  Values are mapped to columns by x-band (mid-point between
neighbouring header label centres), so a row where the extractor merged two
words still lands each surviving number in the right column instead of shifting
everything after the gap.

Run:  .venv/Scripts/python.exe scripts/extract_elecon_dimensions.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import extract_elecon_weights as W

FOOTNOTE_RE = re.compile(r"^\d\)$")
LETTER_RE = re.compile(r"[A-Za-z]")
DROP_HEADS = {"size", "oil", "litres", "liO", "quantity"}
HANDLED = {"V": "V", "W": "W", "D": "Dsh", "L": "Lsh",
           "A": "A1", "h": "h1", "Y": "Y1"}
ALLOWED_SERIES = {"S1", "S2", "S3", "S4", "K2", "K3", "K4"}
MAX_COLS = 22


def header_labels(tokens: list[dict]) -> list[tuple[str, float]]:
    """(letter, x-centre) in x order for a header token list.

    Footnotes ('1)', '2)') and size subscripts are dropped -- the catalogue puts
    the C1/H1/H2 values under the duplicate C/H letters themselves, not under
    the marker -- and non-dimension words (Weight, Oil, Size, ...) never become
    a column.
    """
    out: list[tuple[str, float]] = []
    for t in sorted(tokens, key=lambda w: w["x0"]):
        text = W.norm(t["text"].strip())
        if text.lower() in DROP_HEADS or FOOTNOTE_RE.match(text):
            continue
        if LETTER_RE.search(text):
            out.append((text, (t["x0"] + t["x1"]) / 2))
    return out


def shaft_names(letters: list[str]) -> list[str]:
    """Canonical column names for the shaft table, from its own letters."""
    names: list[str] = []
    shaft = 0
    l_count = 0
    m_count = 0
    housing = False
    for lab in letters:
        if lab == "d":
            if housing:
                names.append("d_out")
                continue
            shaft += 1
            l_count = 0
            names.append(f"d{shaft}")
        elif lab == "l":
            l_count += 1
            names.append(f"l{shaft}{'a' if l_count == 1 else 'b'}")
        elif lab == "M":
            m_count += 1
            names.append(f"M{m_count}")
            housing = True
        elif lab in HANDLED:
            names.append(HANDLED[lab])
            housing = True
        else:
            # CW/CCW rotation annotations never carry a value.
            continue
    return names


def foundation_names(letters: list[str]) -> list[str]:
    """Names for the foundation table; duplicate C/H become C1 and H1/H2."""
    names: list[str] = []
    c_seen = 0
    h_seen = 0
    for lab in letters:
        if lab == "C":
            c_seen += 1
            names.append("C1" if c_seen > 1 else "C")
        elif lab == "H":
            h_seen += 1
            names.append(f"H{h_seen}")
        else:
            names.append(lab)
    return names


def x_bands(centers: list[float]) -> list[tuple[float, float]]:
    """Column bands: mid-point boundaries, mirroring the outer gaps."""
    if len(centers) == 1:
        return [(centers[0] - 10.0, centers[0] + 10.0)]
    edges = [centers[0] - (centers[1] - centers[0])]
    edges += [(a + b) / 2 for a, b in zip(centers, centers[1:])]
    edges.append(centers[-1] + (centers[-1] - centers[-2]))
    return list(zip(edges, edges[1:]))


def map_values(names: list[str], labels: list[tuple[str, float]],
               row_vals: list[tuple[str, float]],
               cap_right: float | None = None) -> tuple[dict[str, float], list[str]]:
    """Assign each numeric token to the band whose centre contains it."""
    centers = [c for _, c in labels]
    bands = x_bands(centers)
    if cap_right is not None and names:
        i = min(len(names), len(bands)) - 1
        bands[i] = (bands[i][0], min(bands[i][1], (centers[i] + cap_right) / 2))
    out: dict[str, float] = {}
    problems: list[str] = []
    for name, band in zip(names, bands):
        hits = [(v, c) for v, c in row_vals if band[0] <= c <= band[1]]
        if len(hits) > 1:
            problems.append(f"{name} got {len(hits)} values")
        elif hits:
            out[name] = float(hits[0][0])
    return out, problems


def shaft_table(page, rows, h, first_size_top: float) -> list[dict]:
    """Per-size rows of the shaft table headed by a weight heading token."""
    header = [ww for r in rows if first_size_top - 16 <= r[0]["top"] < first_size_top - 1
              for ww in r]
    labels = header_labels(header)
    names = shaft_names([n for n, _ in labels])
    if len(labels) < 6 or len(names) > MAX_COLS:
        return []
    # The mirrored Weight heading sits above the header; the weight/oil values
    # are printed just right of the last dimension column, so the last dim
    # band is closed at the mid-point with the heading's own x0.
    out: list[dict] = []
    prev_top: float | None = None
    series_seen: str | None = None
    cap = ""
    for row in rows:
        top = row[0]["top"]
        if top <= first_size_top - 1:
            continue
        if prev_top is not None and top - prev_top > 18:
            break
        if {W.norm(w["text"]).lower() for w in row} & W.STOP_WORDS:
            break
        hit = W.size_of(row)
        if not hit:
            continue
        series, sz, doubled = hit
        if series not in ALLOWED_SERIES:
            continue
        if series_seen is None:
            series_seen, cap = series, W.caption(page, rows, top)
        elif series != series_seen:
            break
        prev_top = top
        text_of = (
            (lambda t: W.de_double(t.strip()) or t.strip())
            if doubled else (lambda t: t.strip())
        )
        row_vals = [(text_of(w["text"]), (w["x0"] + w["x1"]) / 2)
                    for w in row if W.NUM_RE.match(text_of(w["text"]))]
        dims, problems = map_values(names, labels, row_vals, cap_right=h["x0"])
        out.append({
            "series": series,
            "mounting": W.mounting_of(cap),
            "caption": cap,
            "size": sz,
            "dims": dims,
            "problems": problems,
            "mapped": len(dims),
            "expected": len(names),
        })
    return out


def foundation_table(page, rows) -> list[dict]:
    """The 'Foundation' block: a title, a header row of letters, size rows.

    The K-series horizontal pages print the same header without the title, so
    the header is also located from the 'Size' row that always follows it.
    """
    def size_norm(row) -> str:
        normed = W.norm(row[0]["text"].strip()) or ""
        return normed.split()[0].lower() if normed.split() else ""

    def is_header(row) -> bool:
        return sum(1 for w in row
                   if LETTER_RE.search(W.norm(w["text"]))) >= 5

    title = next((r for r in rows
                  if W.norm(r[0]["text"].strip()).lower() == "foundation"), None)
    if title is not None:
        title_top = title[0]["top"]
        header_row = next((r for r in rows
                           if r[0]["top"] > title_top + 4 and is_header(r)),
                          None)
    else:
        # K-series horizontal pages print the header with no title; it still
        # sits right below the last 'Size' row on the page.
        size_rows = [r for r in rows if size_norm(r) == "size"]
        header_row = None
        if size_rows:
            top = size_rows[-1][0]["top"]
            header_row = next((r for r in rows
                               if top - 6 <= r[0]["top"] < top and is_header(r)),
                              None)
    if header_row is None:
        return []
    labels = header_labels(header_row)
    names = foundation_names([n for n, _ in labels])
    if len(labels) < 6 or len(names) > MAX_COLS:
        return []
    header_top = header_row[0]["top"]
    out: list[dict] = []
    prev_top: float | None = None
    series_seen: str | None = None
    cap = ""
    for row in rows:
        if row[0]["top"] <= header_top:
            continue
        top = row[0]["top"]
        if prev_top is not None and top - prev_top > 18:
            break
        if {W.norm(w["text"]).lower() for w in row} & W.STOP_WORDS:
            break
        hit = W.size_of(row)
        if not hit:
            continue
        series, sz, doubled = hit
        if series not in ALLOWED_SERIES:
            continue
        if series_seen is None:
            series_seen, cap = series, W.caption(page, rows, top)
        elif series != series_seen:
            break
        prev_top = top
        text_of = (
            (lambda t: W.de_double(t.strip()) or t.strip())
            if doubled else (lambda t: t.strip())
        )
        row_vals = [(text_of(w["text"]), (w["x0"] + w["x1"]) / 2)
                    for w in row if W.NUM_RE.match(text_of(w["text"]))]
        dims, problems = map_values(names, labels, row_vals)
        out.append({
            "series": series,
            "mounting": W.mounting_of(cap),
            "caption": cap,
            "size": sz,
            "dims": dims,
            "problems": problems,
            "mapped": len(dims),
            "expected": len(names),
        })
    return out


def extract(pdf_path: Path, pages: list[int] | None = None) -> list[dict]:
    found: list[dict] = []
    with W.pdfplumber.open(pdf_path) as pdf:
        n = len(pdf.pages)
        idxs = range(17, min(n, 57)) if pages is None else [p - 1 for p in pages if 1 <= p <= n]
        for pi in idxs:
            page = pdf.pages[pi]
            words = [w for w in page.extract_words(x_tolerance=1.5, y_tolerance=2)
                     if 0.0 <= w["x0"] <= page.width]
            if not words:
                continue
            rows = W.cluster_rows(words)
            heads = [w for w in words if W.norm(w["text"].strip()) in W.WEIGHT_HEADS]
            if not heads:
                continue
            h = heads[0]
            first_size_top = next(
                (r[0]["top"] for r in rows if r[0]["top"] > h["top"] + 3 and W.size_of(r)),
                None,
            )
            if first_size_top is None:
                continue
            for s in shaft_table(page, rows, h, first_size_top):
                s["page"] = pi + 1
                found.append({**s, "table": "shaft"})
            for f in foundation_table(page, rows):
                f["page"] = pi + 1
                found.append({**f, "table": "foundation"})
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--strict", action="store_true",
                    help="fail on rows that mapped fewer than expected values")
    ap.add_argument("--write", action="store_true",
                    help="rewrite elecon_dimensions.json from the parse")
    ap.add_argument("--pages", help="e.g. 36-39")
    args = ap.parse_args()

    if not W.PDF.exists():
        print(f"PDF not found: {W.PDF}", file=sys.stderr)
        return 1

    pages: list[int] | None = None
    if args.pages:
        pages = []
        for part in args.pages.split(","):
            if "-" in part:
                a, b = part.split("-", 1)
                pages.extend(range(int(a), int(b) + 1))
            else:
                pages.append(int(part))

    rows = extract(W.PDF, pages)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    from collections import OrderedDict
    stack: dict[tuple[str, str, str, str], list[dict]] = {}
    for r in rows:
        stack.setdefault((r["table"], r["series"], r["mounting"], r["size"]), []).append(r)

    short = [r for r in rows
             if r["expected"] and r["mapped"] < r["expected"] * 0.8]
    multi = [r for r in rows if r["problems"]]
    print(f"{len(rows)} rows ({sum(1 for r in rows if r['table']=='shaft')} shaft, "
          f"{sum(1 for r in rows if r['table']=='foundation')} foundation), "
          f"{len(short)} short-parse rows, {len(multi)} multi-value rows")

    last_table = ""
    for key in sorted(stack, key=lambda k: (k[0], k[1], k[3] != "H", k[2], k[3])):
        if key[0] != last_table:
            print(f"\n  {key[0]}:")
            last_table = key[0]
        r = stack[key][0]
        sample = ", ".join(f"{k}={v:g}"
                           for k, v in sorted(r["dims"].items()))
        flag = "" if r["problems"] or r["mapped"] >= r["expected"] * 0.8 \
            else f"  !! only {r['mapped']}/{r['expected']}"
        print(f"   {key[1]} {key[2]} {key[3]} (p{r['page']}): "
              f"{sample}{flag}")

    if args.strict and (short or multi):
        return 2
    if args.write:
        out = Path(__file__).resolve().parent / "elecon_dimensions.json"
        out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())