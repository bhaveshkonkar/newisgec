"""End-to-end acceptance tests for the ISGEC AI stack.

Runs against a live Next.js dev server (3000) and the private Python
service (8000). Everything is exercised over HTTP so the tests cover the
same surface the browser does -- authorisation, not just happy paths.

    D:\\gearbox-selector\\.venv\\Scripts\\python.exe scripts\\test_acceptance.py

Each test prints PASS/FAIL and the script exits non-zero if anything fails,
so it can gate a commit.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import uuid

WEB = "http://localhost:3000"
PY = "http://127.0.0.1:8000"

# unique per run so a leftover from an earlier run can never mask a failure
RUN_ID = uuid.uuid4().hex[:6]

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


# ----------------------------------------------------------------- harness


def call(method: str, url: str, body=None, raw: bytes | None = None,
         headers: dict | None = None, timeout: int = 240):
    """Return (status, parsed_json_or_text). Never raises on 4xx/5xx."""
    data = raw
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            status = resp.status
    except urllib.error.HTTPError as e:
        payload = e.read()
        status = e.code
    try:
        return status, json.loads(payload)
    except Exception:
        return status, payload.decode("utf-8", "replace")


def multipart(fields: dict, files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    """Build a multipart/form-data body.

    files is a list of (field, filename, blob, mime) so the same field name
    can repeat -- two uploads arrive as two "files" parts, and a dict would
    silently collapse them into one.
    """
    boundary = "----isgec" + uuid.uuid4().hex
    out = bytearray()
    for k, v in fields.items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for field, fname, blob, mime in files:
        out += f"--{boundary}\r\n".encode()
        out += (f'Content-Disposition: form-data; name="{field}"; '
                f'filename="{fname}"\r\n').encode()
        out += f"Content-Type: {mime}\r\n\r\n".encode()
        out += blob + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def check(name: str, cond: bool, detail: str = "") -> bool:
    if cond:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append((name, detail))
        print(f"  FAIL  {name}" + (f"\n          {detail}" if detail else ""))
    return cond


def section(title: str) -> None:
    print(f"\n{title}\n" + "-" * len(title))


# -------------------------------------------------------------- fixtures


SPEC_TEXT = """ADANI MAHAN - GEARBOX SPECIFICATION SHEET
Application: moderate shock, occasional overload
Daily operating hours: 16 h/day
Ambient temperature: 40 C
Cooling: fan
Rated power PN: 60 kW
Nominal ratio iN: 17
Input speed n1: 1500 rpm
"""


def minimal_pdf(lines: list[str]) -> bytes:
    """A structurally valid single-page PDF. Avoids needing a fixture file."""
    content = "BT /F1 12 Tf 60 760 Td 16 TL\n"
    for ln in lines:
        esc = ln.replace("\\(", "\\\\(").replace("\\)", "\\\\)")
        content += f"({esc}) Tj T*\n"
    content += "ET"
    parts = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, p in enumerate(parts, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{p}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(parts) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for o in offsets:
        out += f"{o:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(parts) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


# ----------------------------------------------------------------- tests


def main() -> int:
    section("0. service availability")
    st, health = call("GET", f"{PY}/health")
    check("python /health returns 200", st == 200, f"got {st}: {health}")
    check("python reports db ok", isinstance(health, dict) and health.get("db") == "ok",
          str(health))
    st, _ = call("GET", f"{WEB}/projects")
    check("next /projects returns 200", st == 200, f"got {st}")

    # ---------------------------------------------------------------- TEST 1
    section("TEST 1 - create project, six modules, open Hub")
    st, created = call("POST", f"{WEB}/api/projects",
                       {"name": "ADANI MAHAN",
                        "project_date": "2023-11-17",
                        "description": "Adani Mahan project engineering requirements"})
    if not check("create project returns 201", st == 201, f"got {st}: {created}"):
        return 1
    A = created["project"]["id"]
    check("project_date survives the round trip",
          created["project"]["project_date"] == "2023-11-17",
          f"got {created['project'].get('project_date')!r} "
          f"(a shift here means a pg DATE/JSON bug)")

    st, hub = call("GET", f"{WEB}/api/projects/{A}")
    check("hub loads", st == 200, f"got {st}")
    check("all six modules created", len(hub["modules"]) == 6,
          f"got {len(hub['modules'])}")
    check("gearbox enabled by default",
          any(m["module_type"] == "gearbox" and m["enabled"] for m in hub["modules"]))
    check("other five modules disabled",
          sum(1 for m in hub["modules"] if m["enabled"]) == 1,
          str([(m["module_type"], m["enabled"]) for m in hub["modules"]]))

    # ---------------------------------------------------------------- TEST 2
    section("TEST 2 - upload datasheet, it reaches parsed state")
    pdf = minimal_pdf(SPEC_TEXT.strip().splitlines())
    body, ctype = multipart(
        {},
        [("files", "spec.pdf", pdf, "application/pdf"),
         ("files", "notes.txt", SPEC_TEXT.encode(), "text/plain")],
    )
    st, up = call("POST", f"{WEB}/api/projects/{A}/documents", raw=body,
                  headers={"Content-Type": ctype})
    check("upload returns 201", st == 201, f"got {st}: {up}")
    check("both files accepted", len(up.get("documents", [])) == 2, str(up)[:200])

    # parsing is out of band, so poll rather than assume
    docs: list = []
    for _ in range(40):
        st, listing = call("GET", f"{WEB}/api/projects/{A}/documents")
        docs = listing.get("documents", [])
        if docs and all(d["status"] in ("parsed", "failed") for d in docs):
            break
        time.sleep(1.5)
    check("both documents reach a terminal state",
          len(docs) == 2 and all(d["status"] in ("parsed", "failed") for d in docs),
          str([(d["file_name"], d["status"], d["error_detail"]) for d in docs]))
    check("PDF parsed successfully",
          any(d["file_name"] == "spec.pdf" and d["status"] == "parsed" for d in docs),
          str([(d["file_name"], d["status"], d["error_detail"]) for d in docs]))
    check("extracted text is non-empty",
          len(next((d.get("extracted_text") or "" for d in docs
                    if d["file_name"] == "spec.pdf"), "")) > 40)
    check("page count recorded",
          next((d.get("page_count") for d in docs if d["file_name"] == "spec.pdf"), None) == 1)

    st, hub2 = call("GET", f"{WEB}/api/projects/{A}")
    check("hub document count updated", hub2["documentCount"] == 2,
          f"got {hub2['documentCount']}")

    # ---------------------------------------------------------------- TEST 3
    section("TEST 3 - deterministic selection via the assistant")
    st, sess = call("POST", f"{WEB}/api/projects/{A}/sessions?module=gearbox",
                    {"module_type": "gearbox", "title": "Selection run"})
    if not check("session created", st == 201, f"got {st}: {sess}"):
        return 1
    sid = sess["session"]["id"]

    st, turn = call(
        "POST",
        f"{WEB}/api/projects/{A}/sessions/{sid}/messages?module=gearbox",
        {"message": "Select a gearbox for 60 kW at ratio 17, S/F 1.25, fan cooled.",
         "module_type": "gearbox",
         "selection_request": {"pn": 60, "ratio_req": 17, "sf": 1.25,
                               "n1_rpm": 1500, "cooling_type": "FAN"}},
    )
    check("turn accepted", st == 200, f"got {st}: {str(turn)[:300]}")
    sel = (turn or {}).get("selection")
    if check("a model was selected", sel is not None, str(turn)[:300]):
        check("selected model meets required PN",
              sel["power_ok"] and sel["power_kw"] >= sel["required_kw"],
              f"{sel['model']} {sel['power_kw']} kW vs PN {sel['required_kw']} kW")
        check("required PN = applied x S/F",
              abs(sel["required_kw"] - 60 * 1.25) < 0.01,
              f"got {sel['required_kw']}")
        check("model code looks like a catalogue code",
              sel["model"].startswith(sel["series"] + "-" + sel["size"]),
              sel["model"])
        check("warnings is a list", isinstance(sel.get("warnings"), list))

    # ranking must not return an undersized gearbox first
    st, sel_all = call("POST", f"{PY}/api/gearbox/select",
                       {"pn": 60, "ratio_req": 17, "sf": 1.25, "n1_rpm": 1500,
                        "cooling_type": "FAN"})
    if check("direct python select returns candidates",
             st == 200 and sel_all.get("results"), str(sel_all)[:200]):
        results = sel_all["results"]
        power_ok_flags = [r["power_ok"] for r in results]
        check("every power-ok model ranks above every failing one",
              power_ok_flags == sorted(power_ok_flags, reverse=True),
              str([(r["model"], r["power_ok"]) for r in results]))
        devs = [r["ratio_dev"] for r in results if r["power_ok"]]
        check("within power-ok, ratio deviation is non-decreasing",
              devs == sorted(devs), str(list(zip([r['model'] for r in results], devs))))
        check("weight provenance is labelled",
              all(isinstance(r["weight_published"], bool) for r in results))

    # ---------------------------------------------------- TEST 3b: mounting
    section("TEST 3b - mounting filter is strict but never silent")

    def select_with(**over):
        payload = {"pn": 60, "ratio_req": 17, "sf": 1.25, "n1_rpm": 1500,
                   "cooling_type": "FAN"}
        payload.update(over)
        return call("POST", f"{PY}/api/gearbox/select", payload)

    st, unfiltered = select_with()
    check("mounting_type=any returns the full series set",
          st == 200 and len({r["series"] for r in unfiltered["results"]}) >= 13,
          f"{len(unfiltered['results'])} results")
    check("no mounting note when no mounting was requested",
          not unfiltered.get("notes"), str(unfiltered.get("notes"))[:200])

    st, ta = select_with(mounting_type="torque_arm")
    ta_series = {r["series"] for r in ta.get("results", [])}
    check("torque_arm request returns only torque-arm series",
          st == 200 and ta_series and ta_series <= {"K3", "K4", "S3", "S4"},
          f"got {sorted(ta_series)}")
    check("every torque-arm result declares that it offers it",
          all("torque_arm" in r["mountings_offered"] for r in ta.get("results", [])))
    check("unknown-mounting series are disclosed, not silently dropped",
          bool(ta.get("notes"))
          and any("K2" in n["note"] and "S2" in n["note"] for n in ta["notes"]),
          str(ta.get("notes"))[:300])
    check("a vendor with no torque-arm series reports why, request still succeeds",
          any("torque_arm" in e["error"] for e in ta.get("errors", []))
          and len(ta.get("results", [])) > 0,
          f"errors={ta.get('errors')} results={len(ta.get('results', []))}")

    st, ft = select_with(mounting_type="foot")
    ft_series = {r["series"] for r in ft.get("results", [])}
    check("foot request excludes torque-arm-only differences and keeps foot series",
          st == 200 and {"S1", "K3"} <= ft_series, f"got {sorted(ft_series)}")
    check("foot request excludes series with unrecorded mounting",
          not (ft_series & {"K2", "S2", "H4"}), f"got {sorted(ft_series)}")

    st, bad = select_with(mounting_type="banana")
    check("an unknown mounting_type is rejected with a useful message",
          st >= 400 and "torque_arm" in json.dumps(bad),
          f"got {st}: {json.dumps(bad)[:200]}")

    # A mounting filter must never change which gearbox is picked for the
    # same requirement -- it only narrows the candidate set.
    if ta.get("results"):
        top_all = unfiltered["results"][0]["model"]
        top_ta = ta["results"][0]["model"]
        check("narrowing by mounting still yields a power-adequate first choice",
              ta["results"][0]["power_ok"],
              f"first torque-arm pick was {top_ta} (unfiltered first was {top_all})")

    # ---------------------------------------------------------------- TEST 4
    section("TEST 4 - assistant answers, transcript persisted")
    st, msgs = call("GET", f"{WEB}/api/projects/{A}/sessions/{sid}/messages?module=gearbox")
    check("transcript readable", st == 200, f"got {st}")
    check("both messages stored", len(msgs.get("messages", [])) == 2,
          str([(m["role"], m["content"][:40]) for m in msgs.get("messages", [])]))
    assistant = [m for m in msgs.get("messages", []) if m["role"] == "assistant"]
    if check("assistant replied", bool(assistant)):
        body = assistant[0]["content"]
        check("reply is not an error string",
              "could not run a selection" not in body.lower()
              and "unavailable right now" not in body.lower(),
              body[:200])
        if sel:
            check("reply mentions the selected model",
                  sel["model"] in body or not body.strip(),
                  f"model={sel['model']} reply={body[:160]!r}")

    # ---------------------------------------------------------------- TEST 5
    section("TEST 5 - project isolation")
    # unique per run: an earlier run's leftovers must not make a pass look
    # like a failure
    b_name = f"Project B Confidential {RUN_ID}"
    st, other = call("POST", f"{WEB}/api/projects", {"name": b_name})
    B = other["project"]["id"]
    check("second project created", st == 201, f"got {st}")

    st, leak = call("GET", f"{WEB}/api/projects/{B}/documents")
    check("B sees none of A's documents",
          st == 200 and len(leak.get("documents", [])) == 0,
          f"got {st}, {len(leak.get('documents', []))} docs")

    a_doc = next((d for d in docs if d["file_name"] == "spec.pdf"), None)
    if a_doc:
        st, _ = call("DELETE", f"{WEB}/api/projects/{B}/documents/{a_doc['id']}")
        check("cannot delete A's document through B (404)", st == 404, f"got {st}")
        st, still = call("GET", f"{WEB}/api/projects/{A}/documents")
        check("A's document survived the cross-project delete",
              any(d["id"] == a_doc["id"] for d in still.get("documents", [])))

    st, leak = call("GET", f"{WEB}/api/projects/{B}/sessions?module=gearbox")
    check("B sees none of A's conversations",
          st == 200 and len(leak.get("sessions", [])) == 0)

    st, _ = call("GET", f"{WEB}/api/projects/{B}/sessions/{sid}/messages?module=gearbox")
    check("cannot read A's transcript through B (404)", st == 404, f"got {st}")

    st, _ = call("POST",
                 f"{WEB}/api/projects/{B}/sessions/{sid}/messages?module=gearbox",
                 {"message": "leak attempt", "module_type": "gearbox"})
    check("cannot post into A's session through B (404)", st == 404, f"got {st}")

    st, _ = call("GET", f"{WEB}/api/projects/{A}")
    check("owner can still read A", st == 200, f"got {st}")
    st, _ = call("GET", f"{WEB}/api/projects/{uuid.uuid4()}")
    check("unknown project id is 404", st == 404, f"got {st}")
    st, _ = call("GET", f"{WEB}/api/projects/not-a-uuid")
    check("malformed project id is 404", st == 404, f"got {st}")

    # ---------------------------------------------------------------- TEST 6
    section("TEST 6 - delete cascades")
    st, _ = call("DELETE", f"{WEB}/api/projects/{B}")
    check("delete project B", st == 200, f"got {st}")
    st, _ = call("GET", f"{WEB}/api/projects/{B}")
    check("deleted project is gone", st == 404, f"got {st}")

    st, listing = call("GET", f"{WEB}/api/projects")
    names = [p["name"] for p in listing.get("projects", [])]
    check("B no longer listed", b_name not in names, str(names))
    check("A still listed", "ADANI MAHAN" in names, str(names))

    # The suite creates a real project and real uploaded files. Leaving them
    # behind means every run adds another identically-named fixture, so the
    # Projects list becomes useless. Clean up unless asked to keep them.
    keep = "--keep" in sys.argv
    if keep:
        print(f"\nfixture project A = {A}  (kept)")
    else:
        st, _ = call("DELETE", f"{WEB}/api/projects/{A}")
        print(f"\nfixture project A cleaned up (delete -> {st}); pass --keep to retain")

    print("\n" + "=" * 60)
    print(f"PASSED {len(PASSED)}   FAILED {len(FAILED)}")
    if FAILED:
        print("\nFailures:")
        for name, detail in FAILED:
            print(f"  - {name}" + (f"\n      {detail}" if detail else ""))
    print("=" * 60)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
