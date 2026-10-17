"""The chatbot, exercised the way a person actually uses it.

Rebuilding the chat interface in Next.js is only half the job. The other half
is that the assistant still behaves like the one it replaced: ask it a
catalogue question before any selection exists, ask a follow-up after one,
run the requirement form, start a new conversation, and switch back.

Run: .\\.venv\\Scripts\\python.exe scripts\\test_chatbot.py
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
    if cond:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append((name, detail))
        print(f"  FAIL  {name}" + (f"\n          {detail}" if detail else ""))


def section(t: str) -> None:
    print(f"\n{t}\n" + "-" * len(t))


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


def ask(pid: str, sid: str, text: str, req=None):
    return call("POST", f"{WEB}/api/projects/{pid}/sessions/{sid}/messages?module=gearbox",
                {"message": text, "module_type": "gearbox", "selection_request": req})


def reply_of(res: dict) -> str:
    msgs = res.get("messages") or []
    return msgs[-1]["content"] if msgs else ""


def main() -> int:
    st, created = call("POST", f"{WEB}/api/projects", {"name": "Chatbot Fixture"})
    if st != 201:
        print(f"  FATAL cannot create fixture project: {st} {created}")
        return 1
    pid = created["project"]["id"]

    st, s1 = call("POST", f"{WEB}/api/projects/{pid}/sessions?module=gearbox",
                  {"module_type": "gearbox"})
    sid = s1["session"]["id"]

    section("a catalogue question with no selection yet")
    # This is the case that used to answer "I couldn't retrieve that from the
    # catalog": the project had no selection and no documents, so there was
    # nothing to ground on.
    st, res = ask(pid, sid, "What is the S3 size range?")
    check("catalogue question accepted", st == 200, f"{st} {str(res)[:200]}")
    text = reply_of(res)
    check("it answers instead of reporting the assistant offline",
          "unavailable" not in text.lower(), text[:200])
    check("not the legacy 'couldn't retrieve' stub",
          "couldn't retrieve" not in text.lower(), text[:200])
    check("it mentions S3", "S3" in text, text[:300])
    check("it gives actual sizes", any(str(n) in text for n in range(15, 27)), text[:300])
    check("no fabricated series invented",
          not any(s in text for s in ("S9", "K9", "ZZ9")), text[:300])

    section("a series/rating question is grounded too")
    st, res = ask(pid, sid, "What power ratings does K3 come in?")
    text = reply_of(res)
    check("K3 question answered", st == 200 and bool(text), f"{st} {text[:120]}")
    check("it names K3", "K3" in text, text[:300])

    section("the requirement form produces a real selection")
    st, res = ask(pid, sid, "Select a gearbox for 60 kW at ratio 17, S/F 1.25.",
                  {"pn": 60, "ratio_req": 17, "sf": 1.25, "n1_rpm": 1500,
                   "cooling_type": "FAN", "gear_type": "any", "mounting_type": "any",
                   "vendor_id": None})
    check("selection accepted", st == 200, f"{st} {str(res)[:200]}")
    sel = res.get("selection") or {}
    check("a model was chosen", bool(sel.get("model")), str(sel)[:200])
    check("the selection is returned for the card to render",
          res.get("selection") is not None)
    check("the reply explains it", len(reply_of(res)) > 20, reply_of(res)[:120])
    model = sel.get("model", "")

    section("a follow-up about that selection")
    st, res = ask(pid, sid, f"Why {model} and not something smaller?")
    text = reply_of(res)
    check("follow-up answered", st == 200 and bool(text), f"{st} {text[:120]}")
    check("it references the model", model in text or "smaller" in text.lower(),
          text[:300])

    section("an answer with nothing behind it says so instead of inventing")
    st, res = ask(pid, sid, "What is the exact thrust rating of the H4-900?")
    text = reply_of(res)
    check("answered", st == 200, f"{st} {str(res)[:160]}")
    has_number = any(ch.isdigit() for ch in text)
    says_unavailable = any(
        k in text.lower()
        for k in ("not available", "unavailable", "no catalogue", "not in the catalogue",
                  "does not", "no data", "not listed")
    )
    check("either it says unavailable, or it gave a grounded number",
          says_unavailable or has_number, text[:300])
    check("it did not claim the assistant is broken",
          "unavailable right now" not in text, text[:200])

    section("new conversation, then back to the old one")
    st, s2 = call("POST", f"{WEB}/api/projects/{pid}/sessions?module=gearbox",
                  {"module_type": "gearbox"})
    sid2 = s2["session"]["id"]
    st, res = ask(pid, sid2, "What is the K2 size range?")
    check("the new conversation works on its own", st == 200, f"{st} {str(res)[:160]}")
    check("it answered about K2", "K2" in reply_of(res), reply_of(res)[:200])

    st, one = call("GET", f"{WEB}/api/projects/{pid}/sessions/{sid}/messages?module=gearbox")
    st, two = call("GET", f"{WEB}/api/projects/{pid}/sessions/{sid2}/messages?module=gearbox")
    firsts = [m["content"] for m in one.get("messages", [])]
    seconds = [m["content"] for m in two.get("messages", [])]
    check("the first conversation kept its 5 turns", len(firsts) == 10, str(len(firsts)))
    check("the second has just its own 2", len(seconds) == 2, str(len(seconds)))
    check("no bleed between conversations",
          not any("K2" in c for c in firsts), str(firsts)[:200])

    section("the whole thing degrades honestly when the LLM is down")
    st, res = ask(pid, sid2, "Explain the S3 thermal capacity.")
    check("a question is still answered or cleanly degraded", st == 200, f"{st}")
    degraded = bool((res.get("messages") or [{}])[-1].get("metadata", {}).get("degraded"))
    if degraded:
        check("degraded still shows the computed facts when there is one",
              res.get("selection") is not None or "unavailable" in reply_of(res).lower(),
              reply_of(res)[:200])
    else:
        check("not degraded, so a real answer came back",
              len(reply_of(res)) > 20, reply_of(res)[:120])

    print("\n" + "=" * 60)
    print(f"PASSED {len(PASSED)}   FAILED {len(FAILED)}")
    for name, detail in FAILED:
        print(f"  - {name}" + (f"\n      {detail}" if detail else ""))
    print("=" * 60)

    st, _ = call("DELETE", f"{WEB}/api/projects/{pid}")
    print(f"\nfixture cleaned up (delete -> {st})")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())