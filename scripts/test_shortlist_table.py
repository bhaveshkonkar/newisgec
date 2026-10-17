"""The deterministic table has to reach the reply even when the LLM is down.

The 3-model shortlist is computed by the selection engine, so it must not
depend on Groq being available. This checks the data path end to end: form ->
engine -> shortlist metadata on the assistant message.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

WEB = "http://localhost:3000"
PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASSED if cond else FAILED).append(name if cond else (name, detail))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"\n          {detail}"))


def call(method: str, url: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def main() -> int:
    st, created = call("POST", f"{WEB}/api/projects", {"name": "Shortlist Fixture"})
    if st != 201:
        print(f"  FATAL cannot create project: {st} {created}")
        return 1
    pid = created["project"]["id"]
    st, s = call("POST", f"{WEB}/api/projects/{pid}/sessions?module=gearbox", {"module_type": "gearbox"})
    sid = s["session"]["id"]

    st, res = call(
        "POST",
        f"{WEB}/api/projects/{pid}/sessions/{sid}/messages?module=gearbox",
        {
            "message": "Select a gearbox for 60 kW at ratio 17, S/F 1.25.",
            "module_type": "gearbox",
            "selection_request": {
                "pn": 60, "ratio_req": 17, "sf": 1.25, "n1_rpm": 1500,
                "cooling_type": "FAN", "gear_type": "any",
                "mounting_type": "any", "vendor_id": None,
            },
        },
    )

    print("shortlist table")
    check("the request succeeded", st == 200, f"{st} {str(res)[:300]}")
    check("a selection came back", bool((res.get("selection") or {}).get("model")),
          str(res.get("selection"))[:200])

    # The table is persisted as message metadata, not returned as a one-off,
    # so it survives a reload and can be re-rendered from the transcript.
    st, msgs = call("GET", f"{WEB}/api/projects/{pid}/sessions/{sid}/messages?module=gearbox")
    rows = msgs.get("messages", [])
    meta = {}
    for m in reversed(rows):
        if m["role"] == "assistant" and m.get("metadata"):
            meta = m["metadata"]
            break

    shortlist = meta.get("shortlist") or []
    check("the shortlist is stored on the reply", len(shortlist) > 0, str(meta.keys()))
    check("it holds 3 models", len(shortlist) == 3, f"got {len(shortlist)}")

    if shortlist:
        first = shortlist[0]
        check("the best model is first and matches the selection",
              first["model"] == res["selection"]["model"],
              f"{first['model']} vs {res['selection']['model']}")
        check("every row carries the numbers the table renders",
              all(all(k in r for k in ("model", "power_kw", "required_kw",
                                      "ratio_iN", "ratio_dev", "n2_actual",
                                      "thermal_kw_effective", "weight_kg",
                                      "weight_published", "power_ok"))
                  for r in shortlist),
              str(sorted(shortlist[0].keys())))
        check("no row is below the required power",
              all(r["power_ok"] for r in shortlist),
              str([(r["model"], r["power_kw"], r["required_kw"]) for r in shortlist]))
        check("the rows are distinct models",
              len({r["model"] for r in shortlist}) == 3,
              str([r["model"] for r in shortlist]))

    print("\n" + "=" * 60)
    print(f"PASSED {len(PASSED)}   FAILED {len(FAILED)}")
    for f in FAILED:
        print(f"  - {f[0]}\n      {f[1]}")
    print("=" * 60)
    call("DELETE", f"{WEB}/api/projects/{pid}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())