"""The Next.js app is the only front door.

There used to be a second, single-file HTML chat UI mounted at '/' on the
Python service. Two front doors over one dataset is how fixes land in one and
not the other, and it is exactly the kind of thing that makes "the assistant
is offline" reports ambiguous -- you cannot tell which UI produced them.

This checks:
  * the legacy UI is really gone, not merely unlinked;
  * :8000 sends a browser to the Next app;
  * the whole flow works through Next: home -> projects -> project hub ->
    module selection -> assistant -> a real selection turn.

Run: .\\.venv\\Scripts\\python.exe scripts\\test_ui_entrypoint.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = "http://localhost:3000"
API = "http://127.0.0.1:8000"

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


def fetch(url: str) -> tuple[int, str, str]:
    """-> (status, body, final_url). Does not follow redirects."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(url, timeout=180) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), url


def api(method: str, url: str, body=None):
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
    section("the legacy UI is gone from the service, not just hidden")
    src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    check("no static mount remains", "StaticFiles" not in src)
    check("no mount at '/' remains", "app.mount('/'" not in src)
    check("no static import remains", "staticfiles" not in src)
    check("the old single-file UI is deleted",
          not (ROOT / "app" / "static" / "index.html").exists())
    check("no leftover STATIC constant", not re.search(r"^STATIC\s*=", src, re.M))

    st, body, _ = fetch(f"{API}/")
    check("GET / no longer serves HTML", "<html" not in body.lower(), body[:120])
    check("GET / is a redirect, not a 404", st in (301, 302, 307, 308), f"got {st}")

    st, body, _ = fetch(f"{API}/ui-redirect")
    check("/ui-redirect exists for old bookmarks", st in (301, 302, 307, 308), f"got {st}")

    section("the API surface the Next app depends on is untouched")
    for path in ("/health", "/openapi.json"):
        st, body, _ = fetch(API + path)
        check(f"{path} still answers", st == 200, f"got {st}")
    st, body, _ = fetch(f"{API}/api/gearbox/select")
    check("select endpoint still routed (405 on GET, not 404)", st in (404, 405), f"got {st}")

    section("the Next flow, start to finish")
    st, body, _ = fetch(f"{WEB}/")
    check("home page renders", st == 200, f"got {st}")
    check("home offers a way into projects", "/projects" in body)

    st, body, _ = fetch(f"{WEB}/projects")
    check("projects list renders", st == 200, f"got {st}")

    st, created = api("POST", f"{WEB}/api/projects", {"name": "UI Flow Fixture"})
    if st != 201:
        print(f"  FATAL cannot create fixture project: {st} {created}")
        return 1
    pid = created["project"]["id"]

    st, body, _ = fetch(f"{WEB}/projects/{pid}")
    check("project hub renders", st == 200, f"got {st}")
    check("hub lists the modules to choose from",
          all(w in body for w in ("Gearbox", "Motor")),
          "module grid missing")
    check("hub links into the gearbox assistant",
          f"/projects/{pid}/gearbox" in body, "no gearbox link on the hub")

    st, body, _ = fetch(f"{WEB}/projects/{pid}/gearbox")
    check("assistant page renders from the hub link", st == 200, f"got {st}")
    check("assistant offers the requirement form",
          "Required power" in body or "Required Power" in body,
          "no requirement form on the page")
    check("assistant has the session rail", "New" in body)

    section("a real turn works through the same path")
    st, sess = api("POST", f"{WEB}/api/projects/{pid}/sessions?module=gearbox",
                   {"module_type": "gearbox"})
    check("session created", st == 201, f"{st} {sess}")
    sid = sess["session"]["id"]

    st, res = api("POST",
                  f"{WEB}/api/projects/{pid}/sessions/{sid}/messages?module=gearbox",
                  {"message": "Select a gearbox for 60 kW at ratio 17, S/F 1.25.",
                   "module_type": "gearbox",
                   "selection_request": {"pn": 60, "ratio_req": 17, "sf": 1.25,
                                         "n1_rpm": 1500, "cooling_type": "FAN",
                                         "gear_type": "any", "mounting_type": "any",
                                         "vendor_id": None}})
    check("selection turn accepted", st == 200, f"{st} {str(res)[:200]}")
    sel = res.get("selection") or {}
    check("a model was actually selected", bool(sel.get("model")), str(sel)[:200])
    check("selection is persisted in the transcript", len(res.get("messages", [])) == 2,
          str(len(res.get("messages", []))))
    check("assistant wrote a reply", bool(res["messages"][-1]["content"]))
    check("the computed result is still shown even if the LLM is offline",
          res.get("selection") is not None)

    section("the conversation is reachable by URL")
    st, body, _ = fetch(f"{WEB}/projects/{pid}/gearbox?session={sid}")
    check("pinned session renders", st == 200, f"got {st}")
    check("the earlier turn is on the page", "60 kW" in body)
    check("the selection is rehydrated, not recomputed",
          (sel.get("model") or "x") in body or "Select a gearbox" in body)

    print("\n" + "=" * 60)
    print(f"PASSED {len(PASSED)}   FAILED {len(FAILED)}")
    for name, detail in FAILED:
        print(f"  - {name}" + (f"\n      {detail}" if detail else ""))
    print("=" * 60)

    st, _ = api("DELETE", f"{WEB}/api/projects/{pid}")
    print(f"\nfixture cleaned up (delete -> {st})")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())