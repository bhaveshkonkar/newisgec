"""Compare the freshly extracted Elecon weights against the imported JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract_elecon_weights as E  # noqa: E402

OLD = Path(__file__).resolve().parent / "elecon_weights.json"


def main() -> int:
    old = json.loads(OLD.read_text(encoding="utf-8"))
    new = E.extract(E.PDF)
    print(f"old {len(old)}  new {len(new)}")
    print("old sample:", old[0])
    print("old variants:", sorted({r.get("variant") for r in old}))

    o = {(r["series"], r["size"], r.get("variant")): (r["weight_kg"], r.get("page")) for r in old}
    n = {(r["series"], r["size"], r["mounting"]): (r["weight_kg"], r["page"]) for r in new}
    print(f"old keys {len(o)}  new keys {len(n)}")

    print("ONLY IN OLD:", sorted(set(o) - set(n)))
    print("ONLY IN NEW:", sorted(set(n) - set(o)))

    diffs = [(k, o[k], n[k]) for k in sorted(set(o) & set(n)) if o[k][0] != n[k][0]]
    print(f"VALUE DIFFS: {len(diffs)}")
    for k, ov, nv in diffs:
        print(f"   {k}: old={ov} new={nv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
