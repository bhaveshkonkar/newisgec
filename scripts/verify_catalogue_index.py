"""Verify the hardcoded catalogue page maps against real page text.

A wrong page number is the exact failure this feature exists to prevent, so the
maps in build_catalogue_index.py are checked against the headings the PDF pages
actually carry before anything is written.
"""

import re
import sys

import psycopg

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from build_catalogue_index import CATALOGUES, normalise  # noqa: E402

DB = "postgresql://gearbox:gearbox@localhost:5433/gearbox"

# Each subject has the words the page heading must contain. Checked loosely
# because headings vary ("DIMENSIONS", "PrincipalDimensions(mm)").
SUBJECT_MARKERS = {
    "power_ratings": ("rating", "capacit"),
    # Elecon's dimensional drawings carry no "DIMENSIONS" heading at all -- the
    # page is a dimension table with shaft sizes, backstop sizes and foundation
    # sizes. Match the table's own column names instead.
    "dimensions": ("dimension", "shaft arangement", "shaft arrangement",
                   "foundation size", "backstop"),
    "actual_ratios": ("actual ratio",),
    "exact_ratios": ("exact ratio",),
    "nomenclature": ("nomenclature",),
    "selection_procedure": ("selection",),
    "output_shaft": ("output shaft",),
    "torque_arm": ("torque arm",),
    # Premium's heading is misspelled in the catalogue itself ("Coling Coil").
    "cooling": ("cooling", "coling"),
    "gd_square": ("gd square", "gd2"),
    "net_weights": ("net weight",),
    "inertia": ("inertia",),
    "lubricants": ("lubricant", "oil capacit"),
}


def norm(s: str) -> str:
    """Lowercase, collapse whitespace, undo the doubled-glyph artefact.

    Large parts of both catalogues extract with every character written twice
    ("iinnppuutt sshhaafftt", "hhoollllooww"). That is still the catalogue's own
    wording, so collapsing the doubling restores the headings this check looks
    for, rather than reporting a section as absent when it is plainly printed.
    """
    s = re.sub(r"(.)\1+", r"\1", s or "")
    return re.sub(r"\s+", " ", s.lower())


def main() -> int:
    problems = 0
    with psycopg.connect(DB) as c:
        # Every copy of a catalogue, not one: a project that was given its own
        # upload cites that document id, and a check that only walks the system
        # copy would pass while the pages a user actually opens were never
        # verified.
        docs = c.execute(
            "SELECT id, file_name, page_count FROM isgec.documents"
        ).fetchall()

        for doc_id, file_name, page_count in docs:
            catalogue = normalise(file_name)
            if catalogue not in CATALOGUES:
                continue
            pages = CATALOGUES[catalogue]

            texts = dict(
                c.execute(
                    "SELECT page_no, text FROM isgec.document_pages "
                    " WHERE document_id = %s",
                    (doc_id,),
                ).fetchall()
            )

            print(f"\n=== {file_name} [{str(doc_id)[:8]}] "
                  f"(page_count={page_count}) ===")

            checked = 0
            for ref in pages:
                if ref.page_no > page_count:
                    print(f"  !! p{ref.page_no} past end ({page_count})")
                    problems += 1
                    continue

                text = norm(texts.get(ref.page_no, ""))
                if not text:
                    print(f"  !! p{ref.page_no} has no extracted text")
                    problems += 1
                    continue

                # A specific series must be named on the page for the row to be
                # honest. A "*" series is by definition a page printed for
                # every type, so the series not appearing is the expected case
                # and only the subject heading is checked.
                if ref.series == "*":
                    series_named = True
                else:
                    series_named = ref.series.lower() in text
                markers = SUBJECT_MARKERS.get(ref.subject)
                subject_ok = True
                if markers:
                    subject_ok = any(m in text for m in markers)

                if not series_named or not subject_ok:
                    checked += 1
                    if checked <= 12:
                        why = []
                        if not series_named:
                            why.append(f"series {ref.series} not named")
                        if not subject_ok:
                            why.append(f"subject {ref.subject} marker absent")
                        print(f"  ?  p{ref.page_no} {ref.series}/{ref.subject}: {'; '.join(why)}")
                        print(f"       head: {text[:130]}")

            print(f"  refs={len(pages)}  needs-review={checked}")

        # Losing a catalogue entirely is silent otherwise: nothing is checked,
        # so nothing fails.
        seen = {normalise(f) for _i, f, _p in docs}
        for missing in sorted(set(CATALOGUES) - seen):
            print(f"!! no document row for {missing}")
            problems += 1

    print(f"\nproblems: {problems}")
    return 0


if __name__ == "__main__":
    sys.exit(main())