"""Read Elecon's own weight column out of the PDF and report what is missing.

Two things make this catalogue awkward:

  * the glyphs for "Weight Average [kg]" come out of the PDF mirrored
    ("thgieW", "egarevA", "]gk[") while the model codes in the same row do not,
    so a parse that searches for "weight" finds nothing on half the pages and
    silently leaves whole series without a weight;
  * every page carries a second, off-canvas copy of its table (x < 0 or
    x > page width) -- bleed from the printed spread. Reading it produces
    plausible-looking weights for the wrong mounting type.
  * the S2 and K2 spreads draw every glyph twice ('SS22....1144',
    'tthhggiieeWW'), so a literal search for the size labels or the heading
    finds nothing at all and those two series were silently skipped. Like the
    mirroring, this is undone with an exact transform (de-double when
    even-indexed chars equal odd-indexed chars, only trusted for a size code
    or a heading).

So: keep only the words that sit inside the page, take the Weight heading's
column by mid-pointing it against its neighbours in the header block (the
heading is one column wide; the ratio bands belong to the shaft columns, not to
it), and walk the contiguous block of size rows beneath it until the table ends.
A size the catalogue gives no weight for produces no row instead of a guess.

Run:  .venv/Scripts/python.exe scripts/extract_elecon_weights.py [--pages 44-47]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data" / "uploads" / "00000000-0000-0000-0000-000000000001" / "Elecon_G_B_EON-Series.pdf"

SIZE_RE = re.compile(r"^(?P<ser>[A-Za-z]\d)\.\.?(?P<size>\d+)$")
NUM_RE = re.compile(r"^\d+(\.\d+)?$")
WEIGHT_HEADS = {"weight", "thgieW"}
OIL_HEADS = {"quantity", "ytitnauQ"}
CAPTION_STARTS = ("type", "tyPe", "ty e")
STOP_WORDS = {"foundation", "selection", "note", "notes"}


def cluster_rows(words: list[dict], tol: float = 4.0) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(w["top"] - rows[-1][0]["top"]) <= tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w["x0"]) for r in rows]


def de_double(text: str) -> str | None:
    """Undo a page whose glyphs were each printed twice.

    The S2 and K2 tables come out of the PDF as 'SS22....1144' and
    'tthhggiieeWW'. The test is exact (every even-indexed character equals the
    odd-indexed one), and it is only ever trusted where the answer is
    unambiguous: a size code or a heading. A bare '22' or '2200' passes the
    test too, so values are only de-doubled once the row they belong to has
    already been identified as doubled through its size code.
    """
    if len(text) >= 2 and len(text) % 2 == 0 and text[::2] == text[1::2]:
        return text[::2]
    return None


def norm(text: str) -> str:
    """Readable form of a token, whether or not the page doubled its glyphs."""
    d = de_double(text)
    return d if d is not None else text


def size_of(row: list[dict]) -> tuple[str, str, bool] | None:
    """(series, size, row_is_doubled) for a data row, or None."""
    for w in row:
        raw = w["text"].strip()
        m = SIZE_RE.match(raw)
        if m:
            return m.group("ser").upper(), m.group("size"), False
        d = de_double(raw)
        if d and len(raw) >= 6:
            m = SIZE_RE.match(d)
            if m:
                return m.group("ser").upper(), m.group("size"), True
    return None


def caption(page, rows: list[list[dict]], first_row_top: float) -> str:
    """The 'Type - K3H Horizontal Mounting ...' line that names the mounting."""
    for row in rows:
        if row[0]["top"] >= first_row_top:
            break
        text = re.sub(r"\s+", " ", " ".join(norm(w["text"]) for w in row)).strip()
        if re.search(r"(?i)(mounting|\btype\b)", text):
            return text
    return ""


def mounting_of(caption_text: str) -> str:
    """H = horizontal foot/flange, T = torque arm.

    The type code carries it when the words around it do not: "Type - S4T" says
    torque arm without ever printing the word 'mounting'.
    """
    low = caption_text.lower()
    if "torque arm" in low:
        return "T"
    if "horizontal" in low:
        return "H"
    m = re.search(r"\b([A-Za-z]\d)([HT])N?\b", caption_text, re.I)
    return m.group(2).upper() if m else ""


def extract(pdf_path: Path, pages: list[int] | None = None) -> list[dict]:
    found: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        n = len(pdf.pages)
        idxs = range(n) if pages is None else [p - 1 for p in pages if 1 <= p <= n]
        for pi in idxs:
            page = pdf.pages[pi]
            lo, hi = 0.0, page.width
            # Bleed: a second, off-canvas copy of the same table.
            words = [w for w in page.extract_words(x_tolerance=1.5, y_tolerance=2)
                     if lo <= w["x0"] <= hi]
            if not words:
                continue
            rows = cluster_rows(words)
            # S2 and K2 print every glyph twice, so the heading reads
            # 'tthhggiieeWW' on those pages and a literal match finds nothing.
            heads = [w for w in words if norm(w["text"].strip()) in WEIGHT_HEADS]
            if not heads:
                continue

            for h in heads:
                # Header block: everything between this heading and the first
                # size row -- that is where the column labels live.
                first_size_top = next(
                    (r[0]["top"] for r in rows if r[0]["top"] > h["top"] + 3 and size_of(r)),
                    h["top"] + 60,
                )
                # Start just above the heading: a footnote that sits higher up
                # ("refer page 60 to 64") would otherwise supply the right-hand
                # edge and open the band wide enough to take the litres column
                # with it.
                header = [w for w in words if h["top"] - 6 < w["top"] < first_size_top - 1]
                left_edge = max((w["x1"] for w in header if w["x1"] <= h["x0"]), default=None)
                # The Quantity heading sits just right of the Weight one and
                # marks the end of the weight column. Without it, fall back to
                # the heading's own footprint plus a column.
                oil_x0 = min(
                    (w["x0"] for w in words
                     if norm(w["text"].strip()) in OIL_HEADS and w["x0"] > h["x0"]
                     and w["x0"] < h["x0"] + 70 and abs(w["top"] - h["top"]) < 60),
                    default=None,
                )
                # The heading is stacked across three lines ("Weight" / "Average"
                # / "[kg]"), so its own footprint must be measured before the
                # next column is looked for -- otherwise "[kg]" is mistaken for
                # the neighbour and the band closes on itself.
                stack_limit = oil_x0 if oil_x0 is not None else h["x0"] + 45
                stack_x1 = max(
                    (w["x1"] for w in header if h["x0"] - 2 <= w["x0"] < stack_limit),
                    default=h["x1"],
                )
                if oil_x0 is not None:
                    band = (
                        h["x0"] if left_edge is None else (left_edge + h["x0"]) / 2,
                        (stack_x1 + oil_x0) / 2,
                    )
                else:
                    right_edge = min(
                        (w["x0"] for w in header if w["x0"] > stack_x1 + 1),
                        default=None,
                    )
                    # No Quantity heading on this page (p.26 prints it only on
                    # the off-canvas copy), so close the band one column to the
                    # right of the heading instead of at the next word, which
                    # would be far enough to swallow the litres column.
                    band = (
                        h["x0"] if left_edge is None else (left_edge + h["x0"]) / 2,
                        h["x0"] + 18 if right_edge is None
                        else (stack_x1 + right_edge) / 2,
                    )

                cap = ""
                prev_top: float | None = None
                series_seen: str | None = None
                for row in rows:
                    if row[0]["top"] <= h["top"] + 3:
                        continue
                    top = row[0]["top"]
                    if prev_top is not None and top - prev_top > 18:
                        break
                    if {norm(w["text"]).lower() for w in row} & STOP_WORDS:
                        break
                    hit = size_of(row)
                    if not hit:
                        continue
                    series, sz, doubled = hit
                    if series_seen is None:
                        series_seen, cap = series, caption(page, rows, top)
                    elif series != series_seen:
                        break
                    prev_top = top
                    text_of = (
                        (lambda t: de_double(t.strip()) or t.strip())
                        if doubled else (lambda t: t.strip())
                    )
                    vals = [text_of(w["text"]) for w in row
                            if band[0] <= (w["x0"] + w["x1"]) / 2 <= band[1]
                            and NUM_RE.match(text_of(w["text"]))]
                    if not vals:
                        continue
                    oil = [text_of(w["text"]) for w in row
                           if (w["x0"] + w["x1"]) / 2 > band[1]
                           and NUM_RE.match(text_of(w["text"]))]
                    found.append({
                        "page": pi + 1,
                        "series": series,
                        "size": sz,
                        "weight_kg": float(vals[0]),
                        "band_values": [float(v) for v in vals],
                        "oil_litres": float(oil[0]) if oil else None,
                        "mounting": mounting_of(cap),
                        "caption": cap,
                    })
    return found


def to_weights_json(rows: list[dict]) -> list[dict]:
    """The shape scripts/migrate_elecon_weights.py reads."""
    out = []
    for r in sorted(rows, key=lambda r: (r["series"], int(r["size"]), r["mounting"])):
        out.append({
            "series": r["series"],
            "size": r["size"],
            "variant": r["mounting"] or "H",
            "weight_kg": r["weight_kg"],
            "oil_l": r["oil_litres"],
            "page": r["page"],
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pages", help="e.g. 44-47 or 19,27,33")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--strict", action="store_true",
                    help="fail if a weight column held more than one number")
    ap.add_argument("--write", action="store_true",
                    help="rewrite elecon_weights.json from the parsed weights")
    args = ap.parse_args()

    pages: list[int] | None = None
    if args.pages:
        pages = []
        for part in args.pages.split(","):
            if "-" in part:
                a, b = part.split("-", 1)
                pages.extend(range(int(a), int(b) + 1))
            else:
                pages.append(int(part))

    if not PDF.exists():
        print(f"PDF not found: {PDF}", file=sys.stderr)
        return 1

    rows = extract(PDF, pages)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    seen: dict[tuple[str, str, str], dict] = {}
    dupes: list[tuple[str, str, str, int, int]] = []
    for r in rows:
        key = (r["series"], r["mounting"], r["size"])
        if key in seen:
            dupes.append((*key, seen[key]["page"], r["page"]))
        else:
            seen[key] = r

    order: dict[str, dict[str, list[tuple[int, dict]]]] = {}
    for (ser, mount, sz), r in seen.items():
        order.setdefault(ser, {}).setdefault(mount, []).append((int(sz), r))
    for ser in sorted(order):
        print(f"{ser}:")
        for mount in sorted(order[ser], key=lambda m: (m != "H", m)):
            items = sorted(order[ser][mount])
            label = {"H": "horizontal", "T": "torque arm"}.get(mount, "unknown")
            print(f"   {label}: {len(items)} sizes")
            for sz, r in items:
                flag = "" if len(r["band_values"]) == 1 else f"  !! band={r['band_values']}"
                print(f"      {ser}-{sz:>3}  {r['weight_kg']:>8.1f} kg   p{r['page']}"
                      f"  {str(r['oil_litres']) or '-':>6} L{flag}")

    multi = [r for r in rows if len(r["band_values"]) > 1]
    unmounted = [r for r in rows if not r["mounting"]]
    print(f"\n{len(rows)} hits, {len(seen)} (series,mounting,size), "
          f"{len(dupes)} duplicates, {len(multi)} rows with >1 value in band, "
          f"{len(unmounted)} without a mounting caption")
    for d in dupes:
        print(f"   duplicate {d[0]}-{d[2]} {d[1]}: p{d[3]} vs p{d[4]}")
    if args.strict and (multi or unmounted or dupes):
        return 2
    if args.write:
        JSON_OUT = Path(__file__).resolve().parent / "elecon_weights.json"
        JSON_OUT.write_text(json.dumps(to_weights_json(rows), indent=1), encoding="utf-8")
        print(f"wrote {JSON_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
