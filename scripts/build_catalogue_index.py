"""Build a model/series -> catalogue page index.

Why this exists
---------------
Citations were produced by scoring the finished answer against extracted page
text with a bag-of-words overlap. That fails on gearbox catalogues for a
structural reason, not a tuning one:

  * Tables extract as numbers, not words. Premium p13 begins
    "Type H1 RATINGS ... Nominal Input Nominal UnitSize" followed by bare
    integers (140, 160, 180...). The model code "H3-315" never appears as a
    string anywhere, so no amount of ranking finds it.
  * Cell spacing leaks into the text. Elecon p6 reads
    "i = nominal transmission ratio N S 3 - 2 0 - H N - 1 - A 0 0 - 0 5 0 0".
    A real designation is shredded across spaces, so "S3-20-HN-1-A" is not a
    token the page contains either.
  * Several pages are literal duplicates (every Elecon drawing page appears
    twice: p8/p9 identical, p10/p11 identical, ...). Whichever copy ranks
    first is arbitrary, so the same model cites differently run to run.

So the mapping is derived from the catalogue's own printed structure instead
of inferred from its prose. Both catalogues label each spread with a heading
naming the type and the subject ("Type H3 RATINGS", "Type - K3 Bevel Helical -
Triple Stage"), which is exactly the (type, subject) pair a citation needs.

The result is stored as (document, series, subject, page) rows. Attribution
then looks the model up instead of searching for it, so a citation either names
the page the catalogue itself declares, or it is not made.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

DB = "postgresql://gearbox:gearbox@localhost:5433/gearbox"

# The two catalogues this indexes, keyed by the file name stored in
# isgec.documents. Both were read page by page to build the maps below; the
# heading on each page is quoted so a future re-run can be checked by eye.
ELECON_FILE = "Elecon G B_EON-Series.pdf"
PREMIUM_FILE = "Premium helical gearboxes catalogue.pdf"

# Vendor code per catalogue, for the provenance query below.
VENDOR_CODE = {ELECON_FILE: "elecon", PREMIUM_FILE: "premium"}


@dataclass(frozen=True)
class PageRef:
    """One catalogue page, labelled with what it actually contains.

    `series` is "*" for a page the catalogue publishes for every type -- the
    generic selection procedure, the all-series shaft table. Those rows are
    expanded against each series at lookup time. Claiming a specific series for
    them would be a guess, and a guess here becomes a wrong citation.
    """

    page_no: int
    series: str
    subject: str


# --------------------------------------------------------------- Elecon EON
#
# Read from the PDF: p2-3 contents, p8-9 S1 ratings, p10-11 S2+S3, p12-13 S4+K2,
# p14-15 K3+K4, p16-17 actual ratios, then dimension/weight blocks. Pages after
# 75 are the back cover.
#
# The catalogue prints each spread twice (p8 and p9 carry identical text), so
# both copies are indexed. Citing either is correct; citing neither is a miss.
ELECON_PAGES: tuple[PageRef, ...] = (
    # Nomenclature is common to every designation, so it is indexed against the
    # helical and bevel-helical families rather than one arbitrary series.
    PageRef(6, "*", "nomenclature"),
    PageRef(7, "*", "nomenclature"),
    # Selection tables. The printed contents page lists "Selection Tables &
    # Example .... 3 - 4" and printed page 3-4 is PDF page 8-9 (the printed
    # numbering runs five behind the PDF's, the same offset that puts
    # nomenclature at 1-2 / PDF 6-7). Both pages print the service-factor
    # thermal-capacity table, so they are indexed for all series. Without this
    # "how do I select a K3?" had no page to cite and fell back to the rating
    # table, which answers a different question.
    PageRef(8, "*", "selection_procedure"),
    PageRef(9, "*", "selection_procedure"),
    # ratings
    PageRef(8, "S1", "power_ratings"),
    PageRef(9, "S1", "power_ratings"),
    PageRef(10, "S2", "power_ratings"),
    PageRef(10, "S3", "power_ratings"),
    PageRef(11, "S2", "power_ratings"),
    PageRef(11, "S3", "power_ratings"),
    PageRef(12, "S4", "power_ratings"),
    PageRef(12, "K2", "power_ratings"),
    PageRef(13, "S4", "power_ratings"),
    PageRef(13, "K2", "power_ratings"),
    PageRef(14, "K3", "power_ratings"),
    PageRef(14, "K4", "power_ratings"),
    PageRef(15, "K3", "power_ratings"),
    PageRef(15, "K4", "power_ratings"),
    PageRef(16, "S1", "actual_ratios"),
    PageRef(16, "K2", "actual_ratios"),
    PageRef(17, "S1", "actual_ratios"),
    PageRef(17, "K2", "actual_ratios"),
    # Dimensional drawings. Confirmed by reading each page, not inferred from
    # page order. The catalogue runs two facing pages per drawing, so pages
    # come in pairs and the "type - XX" codes confirm which series a page
    # belongs to:
    #   p18-19  S1 shaft arrangement ("type - s1hn")
    #   p20-21  S2 backstop / shaft sizes ("type - s2h")
    #   p22-23  S2 torque-arm shaft sizes ("type - s2t")
    #   p24-25  S2 shaft arrangement ("type - s2")
    #   p26-27  S3 shaft sizes ("type - s3h")
    #   p28-31  S3 ("type - s3t" on p28/29, "type - s3" on p30/31)
    #   p32-35  S4 ("type - s4h"/"type - s4t" on p32/33, "type - s4" on p34/35)
    #   p36-43  K2 ("type - k2h" on p36/37, "type - k2t" on p38/39,
    #           "type - k2" on p40-43)
    #   p44-53  K3 (k3..14 sizes on p44-47, "type - k3" on p48-53)
    #   p54-63  K4 (k4..17..26 sizes on p54-57, "type - k4" on p58-63)
    PageRef(18, "S1", "dimensions"),
    PageRef(19, "S1", "dimensions"),
    PageRef(20, "S2", "dimensions"),
    PageRef(21, "S2", "dimensions"),
    PageRef(22, "S2", "dimensions"),
    PageRef(23, "S2", "dimensions"),
    PageRef(24, "S2", "dimensions"),
    PageRef(25, "S2", "dimensions"),
    PageRef(26, "S3", "dimensions"),
    PageRef(27, "S3", "dimensions"),
    PageRef(28, "S3", "dimensions"),
    PageRef(29, "S3", "dimensions"),
    PageRef(30, "S3", "dimensions"),
    PageRef(31, "S3", "dimensions"),
    PageRef(32, "S4", "dimensions"),
    PageRef(33, "S4", "dimensions"),
    PageRef(34, "S4", "dimensions"),
    PageRef(35, "S4", "dimensions"),
    PageRef(36, "K2", "dimensions"),
    PageRef(37, "K2", "dimensions"),
    PageRef(38, "K2", "dimensions"),
    PageRef(39, "K2", "dimensions"),
    PageRef(40, "K2", "dimensions"),
    PageRef(41, "K2", "dimensions"),
    PageRef(42, "K2", "dimensions"),
    PageRef(43, "K2", "dimensions"),
    PageRef(44, "K3", "dimensions"),
    PageRef(45, "K3", "dimensions"),
    PageRef(46, "K3", "dimensions"),
    PageRef(47, "K3", "dimensions"),
    PageRef(48, "K3", "dimensions"),
    PageRef(49, "K3", "dimensions"),
    PageRef(50, "K3", "dimensions"),
    PageRef(51, "K3", "dimensions"),
    PageRef(52, "K3", "dimensions"),
    PageRef(53, "K3", "dimensions"),
    PageRef(54, "K4", "dimensions"),
    PageRef(55, "K4", "dimensions"),
    PageRef(56, "K4", "dimensions"),
    PageRef(57, "K4", "dimensions"),
    PageRef(58, "K4", "dimensions"),
    PageRef(59, "K4", "dimensions"),
    PageRef(60, "K4", "dimensions"),
    PageRef(61, "K4", "dimensions"),
    PageRef(62, "K4", "dimensions"),
    PageRef(63, "K4", "dimensions"),
    # Shaft tables and mountings cover every type, so they are attached to the
    # families rather than one series the page never names.
    # p64/65: solid/keyed/splined/flanged output shaft size table, headed
    # "helical / bevel-helical gear units" -> every type.
    PageRef(64, "*", "output_shaft"),
    PageRef(65, "*", "output_shaft"),
    # p66/67: hollow output shaft, fitted key. p68/69: hollow output shaft,
    # shrink disc, plus intermediate shaft extensions (bevel-helical, i.e. the
    # K series). Confirmed from the page headings after the doubled-character
    # extraction artefact was collapsed.
    PageRef(66, "*", "output_shaft"),
    PageRef(67, "*", "output_shaft"),
    PageRef(68, "K2", "output_shaft"),
    PageRef(69, "K2", "output_shaft"),
    # p70/71: headed "torque arm mounting (shaft mounting) s1 / k2" -- it names
    # S1 and K2 explicitly, so it is filed under those two and nothing else.
    PageRef(70, "S1", "torque_arm"),
    PageRef(70, "K2", "torque_arm"),
    PageRef(71, "S1", "torque_arm"),
    PageRef(71, "K2", "torque_arm"),
    PageRef(72, "*", "cooling"),
    PageRef(73, "*", "cooling"),
    # p74/75: "gd square values (kg-m2) - k2, k3, k4". Also bevel-helical only.
    PageRef(74, "K2", "gd_square"),
    PageRef(74, "K3", "gd_square"),
    PageRef(74, "K4", "gd_square"),
    PageRef(75, "K2", "gd_square"),
    PageRef(75, "K3", "gd_square"),
    PageRef(75, "K4", "gd_square"),
)

# ---------------------------------------------------------------- Premium
#
# Read from the PDF: every type is a "RATINGS" pair of pages immediately
# followed by a "DIMENSIONS" pair, which makes the mapping mechanical.
PREMIUM_PAGES: tuple[PageRef, ...] = (
    PageRef(4, "*", "selection_procedure"),
    PageRef(5, "*", "selection_procedure"),
    PageRef(6, "*", "selection_procedure"),
    PageRef(7, "*", "selection_procedure"),
    PageRef(8, "*", "selection_procedure"),
    PageRef(9, "*", "selection_procedure"),
    PageRef(10, "*", "selection_procedure"),
    PageRef(11, "*", "selection_procedure"),
    PageRef(12, "*", "selection_procedure"),
    # ratings
    PageRef(13, "H1", "power_ratings"),
    PageRef(14, "H1", "power_ratings"),
    PageRef(15, "H2", "power_ratings"),
    PageRef(16, "H2", "power_ratings"),
    PageRef(17, "H3", "power_ratings"),
    PageRef(18, "H3", "power_ratings"),
    PageRef(19, "H4", "power_ratings"),
    PageRef(20, "H4", "power_ratings"),
    PageRef(21, "B2", "power_ratings"),
    PageRef(22, "B2", "power_ratings"),
    PageRef(23, "B3", "power_ratings"),
    PageRef(24, "B3", "power_ratings"),
    PageRef(25, "B4", "power_ratings"),
    PageRef(26, "B4", "power_ratings"),
    # dimensions
    PageRef(27, "H1", "dimensions"),
    PageRef(28, "H1", "dimensions"),
    PageRef(29, "H2", "dimensions"),
    PageRef(30, "H2", "dimensions"),
    PageRef(31, "H2", "dimensions"),
    PageRef(32, "H2", "dimensions"),
    PageRef(33, "H3", "dimensions"),
    PageRef(34, "H3", "dimensions"),
    PageRef(35, "H3", "dimensions"),
    PageRef(36, "H3", "dimensions"),
    PageRef(37, "H4", "dimensions"),
    PageRef(38, "H4", "dimensions"),
    PageRef(39, "H4", "dimensions"),
    PageRef(40, "H4", "dimensions"),
    PageRef(41, "B2", "dimensions"),
    PageRef(42, "B2", "dimensions"),
    PageRef(43, "B2", "dimensions"),
    PageRef(44, "B2", "dimensions"),
    PageRef(45, "B3", "dimensions"),
    PageRef(46, "B3", "dimensions"),
    PageRef(47, "B3", "dimensions"),
    PageRef(48, "B3", "dimensions"),
    PageRef(49, "B4", "dimensions"),
    PageRef(50, "B4", "dimensions"),
    PageRef(51, "B4", "dimensions"),
    PageRef(52, "B4", "dimensions"),
    # engineering. p69/70 are Moments of Inertia (heading "HE-505"), not GD
    # square -- verified against the page text before correcting.
    PageRef(63, "*", "output_shaft"),
    PageRef(64, "*", "output_shaft"),
    PageRef(65, "*", "torque_arm"),
    PageRef(66, "*", "cooling"),
    PageRef(69, "H1", "inertia"),
    PageRef(70, "B2", "inertia"),
    PageRef(71, "*", "exact_ratios"),
    PageRef(72, "*", "exact_ratios"),
    PageRef(73, "*", "net_weights"),
    PageRef(74, "*", "lubricants"),
)

CATALOGUES = {
    ELECON_FILE: ELECON_PAGES,
    PREMIUM_FILE: PREMIUM_PAGES,
}


def expand(file_name: str, pages: tuple[PageRef, ...]) -> list[tuple[str, str, int]]:
    """Turn PageRefs into (series, subject, page_no) rows.

    A "*" series is a page the catalogue prints for every type, so it is
    emitted once per series. Otherwise a reader asking about K3 and getting the
    generic selection procedure back would have been told nothing.
    """
    series_all = ALL_SERIES[file_name]
    rows: list[tuple[str, str, int]] = []
    for ref in pages:
        targets = series_all if ref.series == "*" else (ref.series,)
        for s in targets:
            rows.append((s, ref.subject, ref.page_no))
    return rows

DDL = """
CREATE TABLE IF NOT EXISTS isgec.catalogue_page_index (
    document_id UUID NOT NULL REFERENCES isgec.documents(id) ON DELETE CASCADE,
    series      TEXT NOT NULL,
    subject     TEXT NOT NULL,
    page_no     INT  NOT NULL CHECK (page_no >= 1),
    PRIMARY KEY (document_id, series, subject, page_no)
);

CREATE INDEX IF NOT EXISTS idx_catalogue_pages_lookup
    ON isgec.catalogue_page_index (document_id, series, subject);
"""

# Elecon prints net weight inside its dimension table rather than in a weights
# table of its own, so a hand-written map either duplicates every dimension
# page or silently leaves weight questions uncitable. The parser already records
# which page each weight came from (`dimension.source_page`), so the index is
# derived from that instead: the citation then points at the page the number was
# actually read off, which is the only claim worth making.
WEIGHT_SOURCE_SQL = """
    SELECT DISTINCT s.series_code, d.source_page
      FROM dimension d
      JOIN gear_size g ON g.id = d.gear_size_id
      JOIN gear_series s ON s.id = g.series_id
      JOIN isgec.documents doc ON doc.file_name = %s
     WHERE d.dim_name = 'net_weight_kg'
       AND d.weight_kg IS NOT NULL
       AND d.source_page IS NOT NULL
       AND s.vendor_id = (SELECT v.id FROM vendor v WHERE v.code = %s)
"""


def weight_pages(cur, file_name: str, vendor_code: str) -> list[tuple[str, int]]:
    """(series, page printing net weight) for one catalogue.

    One row per distinct page, not one per series: a triple-stage series
    spreads its sizes over two pages (e.g. K3-14-18 on p44, K3-19-26 on p45),
    so a single "first page" citation points at the wrong spread for half the
    sizes. The topic ranker then picks the page the asked-about size actually
    sits on.
    """
    return [(r[0], int(r[1]))
            for r in cur.execute(WEIGHT_SOURCE_SQL,
                                 (file_name, vendor_code)).fetchall()]


# Every subject the assistant can ask about. Kept explicit so a typo in a map
# above fails loudly here instead of silently returning no citation.
VALID_SUBJECTS = frozenset(
    {
        "nomenclature",
        "selection_procedure",
        "power_ratings",
        "actual_ratios",
        "exact_ratios",
        "dimensions",
        "thermal_capacity",
        "output_shaft",
        "torque_arm",
        "cooling",
        "gd_square",
        "net_weights",
        "lubricants",
        "inertia",
    }
)

# Which types each catalogue publishes. "*" rows are written out once per
# series so a lookup for, say, B3 finds the generic selection procedure.
ELECON_SERIES = ("S1", "S2", "S3", "S4", "K2", "K3", "K4")
PREMIUM_SERIES = ("H1", "H2", "H3", "H4", "B2", "B3", "B4")

ALL_SERIES = {
    ELECON_FILE: ELECON_SERIES,
    PREMIUM_FILE: PREMIUM_SERIES,
}


def normalise(file_name: str) -> str:
    """Strip the name a browser gives a second upload of the same file.

    Uploading "Premium helical gearboxes catalogue.pdf" twice stores the second
    copy as "... (1).pdf". Those are different document ids holding the same
    printed pages, and the index is keyed by document id -- so the copy a
    project actually cites had no rows at all, and every citation in that
    project fell through to bag-of-words scoring, which is the failure this
    whole module exists to avoid.
    """
    return re.sub(r"\s*\(\d+\)(?=\.[A-Za-z0-9]+$)", "", file_name or "")


def load() -> dict[str, tuple[PageRef, ...]]:
    return CATALOGUES


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute(DDL)

        # Every document, not one per file name: the same catalogue is often
        # stored once in the system project and again inside each project that
        # was given a copy. All of them are citable, so all of them are indexed.
        doc_rows = cur.execute(
            "SELECT id, file_name, page_count FROM isgec.documents"
        ).fetchall()

        targets = [(doc_id, file_name, page_count)
                   for doc_id, file_name, page_count in doc_rows
                   if normalise(file_name) in CATALOGUES]

        if not targets:
            print("No catalogue documents found", file=sys.stderr)
            return 1

        total = 0
        for doc_id, file_name, page_count in targets:
            pages = CATALOGUES[normalise(file_name)]

            for ref in pages:
                if ref.subject not in VALID_SUBJECTS:
                    raise SystemExit(
                        f"{file_name} p{ref.page_no}: unknown subject {ref.subject!r}"
                    )

            # A citation to a page the document does not have is worse than no
            # citation, so every ref is checked against the stored page_count
            # before anything is written.
            bad = [r.page_no for r in pages if r.page_no > int(page_count)]
            if bad:
                raise SystemExit(
                    f"{file_name}: page refs beyond page_count "
                    f"{page_count}: {sorted(set(bad))}"
                )

            rows = expand(normalise(file_name), pages)

            # Weight pages come from the parser's own provenance, not the hand
            # map, and never displace a page the map already claims for weights.
            catalogue = normalise(file_name)
            derived = weight_pages(cur, catalogue, VENDOR_CODE[catalogue])
            claimed = {(s, sub) for s, sub, _p in rows if sub == "net_weights"}
            added = 0
            for series, page_no in derived:
                if (series, "net_weights") in claimed:
                    continue
                if page_no > int(page_count):
                    raise SystemExit(
                        f"{file_name}: derived weight page {page_no} for "
                        f"{series} exceeds page_count {page_count}"
                    )
                rows.append((series, "net_weights", page_no))
                added += 1

            total += len(rows)

            if args.dry_run:
                for s, subject, p in rows:
                    print(f"  {file_name} p{p} {s} {subject}")
                continue

            # Rebuild this document's rows so a corrected map also removes pages
            # that are no longer claimed; a stale row is a wrong citation.
            cur.execute(
                "DELETE FROM isgec.catalogue_page_index WHERE document_id = %s",
                (doc_id,),
            )

            for series, subject, page_no in rows:
                cur.execute(
                    """
                    INSERT INTO isgec.catalogue_page_index
                        (document_id, series, subject, page_no)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (doc_id, series, subject, page_no),
                )

            print(f"{file_name} [{str(doc_id)[:8]}]: indexed {len(pages)} page "
                  f"refs -> {len(rows)} rows ({added} weight pages from parser "
                  f"provenance)")

        if not args.dry_run:
            conn.commit()

    print(f"total rows: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())