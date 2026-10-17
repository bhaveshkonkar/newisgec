"""Citation attribution regressions.

Three failures reported against the running product, each of which cost the
reader a click to the wrong place:

  1. "hello" grew a source button. Attribution fell back to the answer's
     wording when the question named no section, and a greeting reply that
     mentions "gearbox selection" therefore sourced itself.
  2. A reply about one series was cited to another. The series came from the
     stored selection, which belonged to an earlier turn.
  3. Elecon's mirrored table headers ("Average Weight [kg]" extracting as
     "thgieW egarevA ]gk[") were invisible to every lexical step, so weight
     questions cited a page that does not print a weight.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import engine  # noqa: E402
import psycopg  # noqa: E402
import reasoning as R  # noqa: E402

ELEC = "29de1d97-1a82-4ded-bd2c-2920e38da314"


def check_unreverse() -> int:
    fails = 0

    flipped = R._unreverse_tokens(
        "thgieW egarevA ]gk[ ytitnauQ liO ]sertiL[")
    print(f"  mirrored run -> {flipped}")
    for word in ("Weight", "Average", "kg", "Quantity", "Oil"):
        if word not in flipped:
            print(f"  FAIL mirror did not restore {word!r}")
            fails += 1

    # Newlines are how the text is actually stored.
    nl = R._unreverse_tokens("thgieW\negarevA ]gk[\nytitnauQ")
    if "Weight" not in nl or "kg" not in nl:
        print(f"  FAIL newline form not repaired: {nl!r}")
        fails += 1
    else:
        print("  ok   newline-separated run repaired")

    for normal in (
        "Nominal Power Rating (kW) for gear unit size 22",
        "S2-22-HN-HB-FAN ratio 12.5",
        "K3..21 48 130 80 110",
        "Type - K2 Gear unit Size",
        "the size 14 to 26 range",
    ):
        if R._unreverse_tokens(normal) != normal:
            print(f"  FAIL ordinary text rewritten: {normal!r}")
            fails += 1
    print("  ok   ordinary text untouched")

    # The repair must be a no-op the second time round.
    once = R._unreverse_tokens("thgieW egarevA")
    if R._unreverse_tokens(once) != once:
        print("  FAIL repair is not idempotent")
        fails += 1
    else:
        print("  ok   idempotent")

    with psycopg.connect(engine.DB) as c, c.cursor() as cur:
        cur.execute(
            "select page_no, text from isgec.document_pages "
            "where document_id=%s and page_no in (18, 44, 45, 46, 54)",
            (ELEC,),
        )
        rows = cur.fetchall()
        if not rows:
            print("  skip no Elecon pages in this database")
            return fails
        for page_no, text in rows:
            repaired = R._unreverse_tokens(text or "")
            if "weight" not in repaired.lower():
                print(f"  FAIL Elecon p.{page_no} weight still unfindable")
                fails += 1
        print(f"  ok   weight findable on {len(rows)} mirrored Elecon pages")

        # A ratings table that was never mirrored must come back byte-identical.
        cur.execute(
            "select text from isgec.document_pages "
            "where document_id=%s and page_no=12", (ELEC,))
        row = cur.fetchone()
        if row and R._unreverse_tokens(row[0] or "") != (row[0] or ""):
            print("  FAIL unmirrored page was rewritten")
            fails += 1
        else:
            print("  ok   unmirrored page byte-identical")
    return fails


def check_chitchat() -> int:
    fails = 0
    cases = [
        ("hello", True),
        ("hi", True),
        ("thanks", True),
        ("ok", True),
        ("good morning", True),
        ("Hello!", True),
        ("what is the weight of K3-21", False),
        ("compare elecon and premium", False),
        ("which series are available", False),
        ("hello, what is the weight of K3", False),
        ("is the B3-400 suitable for 260 kW", False),
    ]
    for q, want in cases:
        got = R._is_chitchat(q)
        if got != want:
            print(f"  FAIL chitchat {q!r} -> {got} (want {want})")
            fails += 1
    print(f"  ok   chitchat: {len(cases)} cases")
    return fails


def check_non_answer() -> int:
    fails = 0
    cases = [
        ("Data unavailable.", True),
        ("data unavailable", True),
        ("", True),
        ("The assistant is unavailable right now.", True),
        ("No catalogue model matched that requirement.", True),
        ("The weight is not available in this catalogue.", True),
        ("Hello! How can I assist you with your gearbox "
         "application today?", False),
        ("**K2-23-HN-HB-FAN** rated 488 kW, ratio 17.1, weight 1060 kg. "
         "Thermal rating not available for this size.", False),
        ("**1060 kg**", False),
        ("**70 kg**", False),
    ]
    for answer, want in cases:
        got = R._is_non_answer(answer)
        if got != want:
            print(f"  FAIL non-answer {answer[:44]!r} -> {got} (want {want})")
            fails += 1
    print(f"  ok   non-answer: {len(cases)} cases")
    return fails


def check_dedupe() -> int:
    fails = 0
    cites = [
        {"file_name": "Premium helical gearboxes catalogue.pdf",
         "page_no": 23, "document_id": "a"},
        {"file_name": "Premium helical gearboxes catalogue (1).pdf",
         "page_no": 23, "document_id": "b"},
        {"file_name": "Elecon G B_EON-Series.pdf",
         "page_no": 12, "document_id": "c"},
        {"file_name": "elecon g b_eon-series (2).pdf",
         "page_no": 12, "document_id": "d"},
    ]
    out = R._dedupe_citations(cites)
    if len(out) != 2:
        print(f"  FAIL dedupe kept {len(out)} of {len(cites)}: "
              f"{[c['file_name'] for c in out]}")
        fails += 1
    else:
        print("  ok   duplicate uploads collapse to one button each")
    if R._dedupe_citations([]) != []:
        print("  FAIL dedupe of empty list")
        fails += 1
    return fails


def check_series_from_answer() -> int:
    """The series a citation names must be the one the reply is about.

    cite_from_index itself reads the page index, which makes it a database
    test rather than a decision test. What actually went wrong was upstream of
    the query: the stored selection (K3, from an earlier turn) was allowed to
    outrank the series the shipped reply names (K2). The decision lives in
    _series_in plus the ordering in cite_from_index, so assert the inputs to
    that ordering here.
    """
    fails = 0
    allowed = frozenset({"K2", "K3", "K4"})
    answer = "**Elecon K2-25-HN-HB-FAN** nominal power rating 488 kW at " \
             "ratio 17.1, weight 1 060 kg."

    named = R._series_in(answer, allowed)
    if named != ["K2"]:
        print(f"  FAIL answer series detection -> {named}")
        fails += 1
    else:
        print("  ok   answer names K2, not the stale selection's K3")

    stale = R._series_in("K3-21-HN-HB-FAN", allowed)
    if stale != ["K3"]:
        print(f"  FAIL selection series detection -> {stale}")
        fails += 1
    else:
        print("  ok   stale selection series detected as K3")

    # A reply with no designation must fall back rather than invent one.
    if R._series_in("**1060 kg**", allowed):
        print("  FAIL a bare figure produced a series")
        fails += 1
    else:
        print("  ok   bare figure names no series")
    return fails


def main() -> int:
    failures = 0
    print("=== mirrored page text ===")
    failures += check_unreverse()
    print("=== chitchat ===")
    failures += check_chitchat()
    print("=== non-answers ===")
    failures += check_non_answer()
    print("=== duplicate uploads ===")
    failures += check_dedupe()
    print("=== series attribution ===")
    failures += check_series_from_answer()
    print()
    print(f"{failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
