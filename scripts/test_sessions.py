"""Session sidebar behaviour: list, switch, follow-up, delete.

Exercises the routes the rail is built on. The rail itself is React, so what
is verified here is the contract underneath it: a second conversation stays
separate, ?session= picks the right transcript, a follow-up lands in the
conversation it was asked in, and deleting only removes the target.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

WEB = "http://localhost:3000"
PY = "http://127.0.0.1:8000"

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def call(method: str, url: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def fetch_text(url: str) -> tuple[int, str]:
    """For HTML pages, which json.loads cannot read."""
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append((name, detail))
        print(f"  FAIL  {name}" + (f"\n          {detail}" if detail else ""))


def section(t: str) -> None:
    print(f"\n{t}\n" + "-" * len(t))


def ask(pid: str, sid: str, text: str, req=None):
    # Mirror the browser exactly, including `selection_request: null` for a
    # plain-text question. Omitting the key instead would hide the difference
    # between "absent" and "null", which is exactly where this broke.
    payload = {"message": text, "module_type": "gearbox", "selection_request": req}
    return call("POST", f"{WEB}/api/projects/{pid}/sessions/{sid}/messages?module=gearbox",
                payload)


def main() -> int:
    section("setup")
    st, created = call("POST", f"{WEB}/api/projects", {"name": "Rail Fixture"})
    if st != 201:
        print(f"  FATAL cannot create fixture project: {st} {created}")
        return 1
    pid = created["project"]["id"]

    section("two independent conversations")
    st, s1 = call("POST", f"{WEB}/api/projects/{pid}/sessions?module=gearbox",
                  {"module_type": "gearbox", "title": "60 kW conveyor"})
    st2, s2 = call("POST", f"{WEB}/api/projects/{pid}/sessions?module=gearbox",
                   {"module_type": "gearbox", "title": "Torque arm duty"})
    check("two sessions created", st == 201 and st2 == 201, f"{st} {st2}")
    a, b = s1["session"]["id"], s2["session"]["id"]

    ask(pid, a, "Select for 60 kW at ratio 17",
        {"pn": 60, "ratio_req": 17, "sf": 1.25, "n1_rpm": 1500, "cooling_type": "FAN"})
    ask(pid, b, "Select for 60 kW at ratio 17 torque arm",
        {"pn": 60, "ratio_req": 17, "sf": 1.25, "n1_rpm": 1500,
         "cooling_type": "FAN", "mounting_type": "torque_arm"})

    st, listing = call("GET", f"{WEB}/api/projects/{pid}/sessions?module=gearbox")
    sessions = listing.get("sessions", [])
    check("rail lists both conversations", len(sessions) == 2, str(len(sessions)))
    check("most recently updated is first",
          sessions and sessions[0]["id"] == b,
          f"first={sessions[0]['id'] if sessions else None} expected {b}")
    check("each has a title", all(s.get("title") for s in sessions),
          str([s.get("title") for s in sessions]))
    check("each has updated_at for the relative stamp",
          all(s.get("updated_at") for s in sessions))

    section("conversations stay separate")
    st, ma = call("GET", f"{WEB}/api/projects/{pid}/sessions/{a}/messages?module=gearbox")
    st, mb = call("GET", f"{WEB}/api/projects/{pid}/sessions/{b}/messages?module=gearbox")
    ta = [m["content"] for m in ma.get("messages", [])]
    tb = [m["content"] for m in mb.get("messages", [])]
    check("conversation A has its own 2 messages", len(ta) == 2, str(ta))
    check("conversation B has its own 2 messages", len(tb) == 2, str(tb))
    check("A did not receive B's torque-arm turn",
          not any("torque arm" in c for c in ta), str(ta))

    section("selection is rehydrated from the transcript")
    sel_a = next((m["metadata"].get("selection") for m in ma.get("messages", [])
                  if m["role"] == "assistant" and m["metadata"]), None)
    sel_b = next((m["metadata"].get("selection") for m in mb.get("messages", [])
                  if m["role"] == "assistant" and m["metadata"]), None)
    check("A persisted its selection", bool(sel_a), str(sel_a))
    check("B persisted its selection", bool(sel_b), str(sel_b))
    if sel_a and sel_b:
        check("the two selections differ because mounting was applied",
              sel_a["model"] != sel_b["model"] or sel_a["mounting_type"] != sel_b["mounting_type"],
              f"A={sel_a['model']}/{sel_a['mounting_type']} "
              f"B={sel_b['model']}/{sel_b['mounting_type']}")
        check("B's selection is a torque-arm series",
              sel_b["mounting_type"] == "torque_arm"
              and "torque_arm" in sel_b["mountings_offered"],
              str(sel_b.get("mountings_offered")))

    section("a follow-up lands in the conversation it was asked in")
    st, fu = ask(pid, a, "Why not the K3?")
    check("follow-up accepted", st == 200, f"{st} {str(fu)[:200]}")
    st, ma2 = call("GET", f"{WEB}/api/projects/{pid}/sessions/{a}/messages?module=gearbox")
    st, mb2 = call("GET", f"{WEB}/api/projects/{pid}/sessions/{b}/messages?module=gearbox")
    check("A now holds 4 messages", len(ma2.get("messages", [])) == 4,
          str(len(ma2.get("messages", []))))
    check("B is untouched by A's follow-up",
          len(mb2.get("messages", [])) == 2, str(len(mb2.get("messages", []))))
    check("follow-up question was stored",
          any("Why not the K3?" == m["content"] for m in ma2.get("messages", [])))

    section("a text-only question is accepted, not a validation error")
    # Regression: selection_request was .optional() but not .nullable(), and the
    # client sends an explicit null for a question with no requirement. Every
    # follow-up question therefore failed with "Expected object, received null".
    st, r = call("POST", f"{WEB}/api/projects/{pid}/sessions/{a}/messages?module=gearbox",
                 {"message": "Is forced lube needed?", "module_type": "gearbox",
                  "selection_request": None})
    check("selection_request: null is accepted", st == 200,
          f"{st} {str(r)[:160]}")
    check("it is answered, not silently dropped", bool(r.get("messages")), str(r)[:160])
    st, r2 = call("POST", f"{WEB}/api/projects/{pid}/sessions/{a}/messages?module=gearbox",
                  {"message": "And the ratio?", "module_type": "gearbox"})
    check("an omitted selection_request is still accepted", st == 200,
          f"{st} {str(r2)[:160]}")
    st, r3 = call("POST", f"{WEB}/api/projects/{pid}/sessions/{a}/messages?module=gearbox",
                  {"message": "  ", "module_type": "gearbox",
                   "selection_request": None})
    check("an empty message is still rejected", st == 400, f"{st} {str(r3)[:160]}")

    section("titles: explicit wins, opening message fills the gap, nothing renames later")
    st, listing = call("GET", f"{WEB}/api/projects/{pid}/sessions?module=gearbox")
    titles = {s["id"]: s["title"] for s in listing.get("sessions", [])}
    check("an explicit title is preserved, not overwritten by later turns",
          titles.get(a) == "60 kW conveyor", f"got {titles.get(a)!r}")

    # a session created with no title should be named after its first message
    st, s3 = call("POST", f"{WEB}/api/projects/{pid}/sessions?module=gearbox",
                  {"module_type": "gearbox"})
    c = s3["session"]["id"]
    check("a title-less session starts as the placeholder",
          s3["session"]["title"] == "New conversation", f"got {s3['session']['title']!r}")
    ask(pid, c, "Select for 25 kW at ratio 25, fan cooled",
        {"pn": 25, "ratio_req": 25, "sf": 1.0, "n1_rpm": 1500, "cooling_type": "FAN"})
    st, listing = call("GET", f"{WEB}/api/projects/{pid}/sessions?module=gearbox")
    t3 = next((s["title"] for s in listing.get("sessions", []) if s["id"] == c), None)
    check("the opening message titles it", bool(t3) and t3 != "New conversation"
          and "25 kW" in t3, f"got {t3!r}")
    ask(pid, c, "And is forced lube needed?")
    st, listing = call("GET", f"{WEB}/api/projects/{pid}/sessions?module=gearbox")
    t3b = next((s["title"] for s in listing.get("sessions", []) if s["id"] == c), None)
    check("a follow-up does not rename it", t3b == t3, f"{t3!r} -> {t3b!r}")

    st, _ = call("DELETE", f"{WEB}/api/projects/{pid}/sessions/{c}?module=gearbox")

    section("delete removes only the target")
    st, ma_now = call("GET", f"{WEB}/api/projects/{pid}/sessions/{a}/messages?module=gearbox")
    ma_len = len(ma_now.get("messages", []))
    st, _ = call("DELETE", f"{WEB}/api/projects/{pid}/sessions/{b}?module=gearbox")
    check("delete returns 200", st == 200, f"got {st}")
    st, listing = call("GET", f"{WEB}/api/projects/{pid}/sessions?module=gearbox")
    ids = [s["id"] for s in listing.get("sessions", [])]
    check("deleted session is gone from the rail", b not in ids, str(ids))
    check("the other session survives", a in ids, str(ids))
    st, _ = call("GET", f"{WEB}/api/projects/{pid}/sessions/{b}/messages?module=gearbox")
    check("deleted session's transcript is 404", st == 404, f"got {st}")
    st, ma4 = call("GET", f"{WEB}/api/projects/{pid}/sessions/{a}/messages?module=gearbox")
    check("the surviving transcript is untouched by the delete",
          len(ma4.get("messages", [])) == ma_len,
          f"{ma_len} -> {len(ma4.get('messages', []))}")

    section("the page opens a fresh conversation, and past ones stay listed")
    # no ?session= must mean "new conversation". If it silently resolved to the
    # newest session instead, the rail's New button would be a no-op and the
    # next requirement would be appended to the conversation the user was
    # trying to leave.
    st, page = fetch_text(f"{WEB}/projects/{pid}/gearbox")
    check("gearbox page renders without ?session=", st == 200, f"got {st}")
    check("existing conversation is still listed in the rail", a in str(page))
    check("saved title is still shown in the rail", "60 kW conveyor" in str(page))
    check("its transcript is NOT rendered into the new draft",
          "Why not the K3?" not in str(page), "draft leaked the previous transcript")

    st, page = fetch_text(f"{WEB}/projects/{pid}/gearbox?session={a}")
    check("?session= renders that conversation's transcript",
          st == 200 and "Why not the K3?" in str(page), f"got {st}")

    section("a stale ?session= id degrades to a draft, not an error")
    stale = "00000000-0000-4000-8000-0000000000ff"
    st, _ = call("GET",
                 f"{WEB}/api/projects/{pid}/sessions/{stale}/messages?module=gearbox")
    check("stale session id is 404 rather than 500", st == 404, f"got {st}")
    st, page = fetch_text(f"{WEB}/projects/{pid}/gearbox?session={stale}")
    check("page still renders with a stale ?session=", st == 200, f"got {st}")
    check("the real conversations are still offered", a in str(page))

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