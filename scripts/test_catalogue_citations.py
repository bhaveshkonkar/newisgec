"""Check that a catalogue answer cites the page the catalogue prints.

Each case names the series and the section the reader asked about, and the page
the catalogue puts that section on. The assertion is on the page number, not on
the fact that *some* citation came back: a citation that exists but points at
the wrong table is the failure this whole index exists to prevent.
"""

import sys

import psycopg

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("\\", 1)[0])

DB = "postgresql://gearbox:gearbox@localhost:5433/gearbox"
ELECON = "29de1d97-1a82-4ded-bd2c-2920e38da314"
PREMIUM = "97d922b0-c1fe-4b07-875b-97a4b986adda"

CASES = [
    # (label, doc, series, question, expected pages)
    ("Elecon S3 ratings", ELECON, "S3",
     "What is the rated power for series S3?", {10, 11}),
    ("Elecon S1 ratings", ELECON, "S1",
     "Rated power for S1 gearbox?", {8, 9}),
    ("Elecon K3 ratings", ELECON, "K3",
     "Power rating of K3?", {14, 15}),
    # S3's dimensional section opens at p26 ("type - s3h" shaft sizes).
    ("Elecon S3 dimensions", ELECON, "S3",
     "Show me the dimensions drawing for S3", {26, 27, 28, 29, 30, 31}),
    ("Elecon K4 dimensions", ELECON, "K4",
     "Dimensions for K4 series", {54, 55, 56, 57, 58, 59, 60, 61, 62, 63}),
    ("Elecon S2 dimensions", ELECON, "S2",
     "What are the S2 dimensions?", {20, 21, 22, 23, 24, 25}),
    ("Elecon K2 dimensions", ELECON, "K2",
     "Dimensions for K2", {36, 37, 38, 39, 40, 41, 42, 43}),
    ("Elecon S1 nomenclature", ELECON, "S1",
     "What is the nomenclature meaning of S1-20?", {6, 7}),
    ("Premium H2 ratings", PREMIUM, "H2",
     "Rated power for H2?", {15, 16}),
    ("Premium B3 ratings", PREMIUM, "B3",
     "What is the power rating of B3-315?", {23, 24}),
    ("Premium B4 ratings", PREMIUM, "B4",
     "Power rating of B4?", {25, 26}),
    ("Premium H3 dimensions", PREMIUM, "H3",
     "Dimensions drawing for H3", {33, 34, 35, 36}),
    ("Premium B2 dimensions", PREMIUM, "B2",
     "Dimensions for B2 series", {41, 42, 43, 44}),
    ("Premium H1 selection", PREMIUM, "H1",
     "How does the selection procedure work?", set(range(4, 13))),
]

# Cases where the honest answer is *no* citation. These matter as much as the
# positive ones: a wrong page number presented as a source is the failure this
# index exists to prevent, so refusing beats guessing.
NO_CITATION = [
    ("no series anywhere", [ELECON, PREMIUM], "It handles 40 kW.",
     "What power does it need?", None),
    ("no catalogue subject", [ELECON], "S3 is a good choice.", "Thanks!", "S3"),
    ("series not in this doc", [PREMIUM], "S3 rated power is 4 kW.",
     "Rated power for S3?", ""),
    ("subject not in catalogue", [ELECON], "S3 price is 5000 INR.",
     "What is the price of S3?", "S3"),
]

# A comparison question names VENDORS, not series. These assert the grounding
# facts identify which vendor owns which series, because without that the model
# cannot place either catalogue and answers "data unavailable" -- the bug that
# made "compare premium and elecon on same parameters" unusable.
VENDOR_FACT_CASES = [
    ("both vendors detected",
     "compare the premium and elecon on same parameters",
     ("premium", "elecon")),
    ("order follows the question",
     "elecon versus premium",
     ("elecon", "premium")),
    ("single vendor detected",
     "what sizes does elecon have",
     ("elecon",)),
    ("no vendor named",
     "what sizes does K3 have",
     ()),
]


def check_vendor_facts(failures):
    from app.reasoning import _catalog_context, vendors_named  # noqa: PLC0415

    for label, question, expected in VENDOR_FACT_CASES:
        got = tuple(vendors_named(question))
        if got != expected:
            print(f"FAIL {label}: vendors_named -> {got}, expected {expected}")
            failures += 1
        else:
            print(f"ok   {label}: {got}")

    # A vendor named in words must reach the fact blocks. "what about premium?"
    # carries no series, size or model, so it returned an empty context and the
    # model answered "Data unavailable" for the vendor just asked about.
    for label, question in (
        ("vendor name triggers facts", "what about premium"),
        ("vendor name triggers facts (order)", "premium vs this"),
    ):
        ctx = _catalog_context(question)
        if not ctx.strip():
            print(f"FAIL {label}: empty context for {question!r}")
            failures += 1
        elif "PREMIUM" not in ctx.upper():
            print(f"FAIL {label}: no PREMIUM rows in context")
            failures += 1
        else:
            print(f"ok   {label}")

    # Every series line must carry its vendor, or the model has no way to tell
    # the two catalogues apart.
    ctx = _catalog_context("compare the premium and elecon on same parameters")
    if not ctx.strip():
        print("FAIL vendor-attributed facts: context empty")
        return failures + 1
    missing = []
    for vendor in ("ELECON", "PREMIUM"):
        if f"{vendor} " not in ctx:
            missing.append(vendor)
    if missing:
        print(f"FAIL vendor-attributed facts: no '{missing}' rows in context")
        failures += 1
    else:
        print("ok   vendor-attributed facts: both vendors present")

    # Size codes are not kW. Premium '140' rates 5.24 kW at iN 106, so a bare
    # number here reads as a power rating and the model prints "140 kW".
    if "NOT power in kW" not in ctx:
        print("FAIL size codes labelled: no unit warning in context")
        failures += 1
    else:
        print("ok   size codes labelled: unit warning present")

    # A comparison needs a like-for-like axis or it degenerates into two size
    # lists that cannot be lined up against each other.
    if "COMPARABLE POWER BANDS" not in ctx:
        print("FAIL comparable bands: absent for a comparison question")
        failures += 1
    else:
        print("ok   comparable bands: present")

    failures = check_equivalent_selection(failures)
    return failures


def check_equivalent_selection(failures):
    """The second column of a comparison must be a real selection, not a blank.

    The deterministic engine covers one vendor, so comparing it with another
    left every row of the second vendor as "Data unavailable". The engine is
    replayed against the other vendor with the identical requirement.
    """
    import re as _re

    from app.engine import select  # noqa: PLC0415
    from app.reasoning import _catalog_context  # noqa: PLC0415

    out = select(kw=364, rpm=1480, gr=13, gear_type="any", hb="YES",
                 cooling="FAN", sf=1.0, select_closest_power=False)
    sel = dict(out["candidates"][0])
    required = sel["required_pn"]

    for label, question in (
        ("equivalent: vendor named", "what about premium"),
        ("equivalent: vendor unnamed", "compare them"),
        ("equivalent: vs phrasing", "premium vs this"),
    ):
        ctx = _catalog_context(question, sel)
        if "EQUIVALENT" not in ctx:
            print(f"FAIL {label}: no computed column for {question!r}")
            failures += 1
            continue
        m = _re.search(r"required ([0-9.]+) kW", ctx)
        if not m:
            print(f"FAIL {label}: equivalent block has no required kW")
            failures += 1
            continue
        # Reading power_kw instead of required_pn sizes the second vendor
        # against the first vendor's CHOICE, silently changing the demand.
        if float(m.group(1)) != float(required):
            print(f"FAIL {label}: required {m.group(1)} kW, "
                  f"expected {required} kW")
            failures += 1
            continue
        if "PREMIUM EQUIVALENT" not in ctx:
            print(f"FAIL {label}: second column not labelled PREMIUM")
            failures += 1
            continue
        print(f"ok   {label}: required {required} kW preserved")

    # A non-comparison question must not start running the engine for other
    # vendors on every turn.
    ctx = _catalog_context("what is the thermal capacity of this", sel)
    if "EQUIVALENT" in ctx:
        print("FAIL no-comparison question: unexpectedly ran other vendors")
        failures += 1
    else:
        print("ok   no-comparison question: other vendors not queried")

    # The leaf function passing is not the point -- the caller has to thread
    # the selection through. _project_context called _catalog_context(question)
    # with no second argument, so every assembled prompt lost the comparison
    # column while the unit test below still reported the leaf as working.
    from app.reasoning import _project_context  # noqa: PLC0415

    assembled = _project_context(sel, [], "what about premium")
    if "PREMIUM EQUIVALENT" not in assembled:
        print("FAIL assembled prompt: selection not threaded to catalogue")
        failures += 1
    elif "required 364" not in assembled:
        print("FAIL assembled prompt: requirement not preserved")
        failures += 1
    elif "Estimated steel cost" not in assembled:
        # The first column already carries a material cost; a blank second
        # column makes the comparison unusable without doing the maths twice.
        print("FAIL assembled prompt: no cost for the computed column")
        failures += 1
    else:
        print("ok   assembled prompt: comparison column reaches the model")

    return failures


def main():
    from app.reasoning import cite_from_index  # noqa: PLC0415

    failures = 0
    with psycopg.connect(DB) as c:
        names = dict(c.execute(
            "SELECT id, file_name FROM isgec.documents WHERE id IN (%s, %s)",
            (ELECON, PREMIUM),
        ).fetchall())

    for label, doc, series, question, expected in CASES:
        cites = cite_from_index(
            f"The {series} series is the right choice here.",
            question,
            {"series": series},
            [doc],
        )
        if not cites:
            print(f"FAIL {label}: no citation")
            failures += 1
            continue
        got = {c["page_no"] for c in cites}
        # The resolver must land inside the section, not merely return a page.
        if not got & expected:
            print(f"FAIL {label}: got {sorted(got)}, expected one of {sorted(expected)}")
            failures += 1
            continue
        stray = got - expected
        note = f"  (extra {sorted(stray)})" if stray else ""
        print(f"ok   {label}: {sorted(got)}{note}")

    for label, docs, answer, question, series in NO_CITATION:
        cites = cite_from_index(
            answer, question, {"series": series or ""}, docs
        )
        if cites:
            print(f"FAIL {label}: expected no citation, got {cites}")
            failures += 1
        else:
            print(f"ok   {label}: no citation (correct)")

    failures = check_vendor_facts(failures)

    # Cases + citations + the fixed vendor-fact and equivalent-selection groups.
    total = (len(CASES) + len(NO_CITATION) + len(VENDOR_FACT_CASES)
             + 5          # vendor triggers, attribution, units, bands
             + 5)         # equivalent selection + negative + assembled prompt
    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())