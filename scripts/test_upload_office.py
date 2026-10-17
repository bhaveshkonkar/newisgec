"""Office formats over the real upload route.

test_docparse.py proves the extractors work on files. This proves the wiring:
that a .docx or .xlsx actually posted through /api/projects/{id}/documents
lands as 'parsed' with real text attached, and that a legacy .doc lands as
'failed' with a message the engineer can act on.

The bug this guards against is silent: before, every office file decoded as
UTF-8, so a .docx uploaded fine, was marked parsed, and stored ZIP header
bytes as the grounding text. Nothing in the UI complained.

Run: .\\.venv\\Scripts\\python.exe scripts\\test_upload_office.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "scripts"))

import docparse  # noqa: E402

WEB = "http://localhost:3000"

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOC_MIME = "application/msword"
XLS_MIME = "application/vnd.ms-excel"


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
    hdrs = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def upload(pid: str, name: str, mime: str, data: bytes):
    """Build multipart by hand: urllib needs no ctypes for File objects."""
    b = "----isgec" + uuid.uuid4().hex
    parts = [
        f"--{b}\r\n".encode(),
        f'Content-Disposition: form-data; name="files"; filename="{name}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        data,
        f"\r\n--{b}--\r\n".encode(),
    ]
    body = b"".join(parts)
    req = urllib.request.Request(
        f"{WEB}/api/projects/{pid}/documents",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={b}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def docx_bytes() -> bytes:
    buf = Path(ROOT / "data" / "_tmp_office_fixture.docx")
    body = "".join(
        f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>"
        for p in [
            "Elecon G B_EON Series helical gearbox catalogue",
            "Service factor 1.25, input speed 1500 rpm, thermal capacity advisory.",
        ]
    )
    doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{docparse.W_NS}"><w:body>{body}</w:body></w:document>'
    )
    import io

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",
                    '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org'
                    '/package/2006/content-types"/>')
        zf.writestr("word/document.xml", doc)
    return out.getvalue()


def xlsx_bytes() -> bytes:
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "S3 Series"
    ws.append(["Series", "Size", "Power kW", "Ratio", "Service factor"])
    ws.append(["S3", "S3-40", "3.0", "17", "1.25"])
    ws.append(["S3", "S3-50", "4.0", "19", "1.30"])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def poll_document(pid: str, doc_id: str, tries: int = 40):
    """Parsing is dispatched; wait for it to settle."""
    for _ in range(tries):
        st, listing = call("GET", f"{WEB}/api/projects/{pid}/documents")
        if st != 200:
            return None
        for d in listing.get("documents", []):
            if d["id"] == doc_id:
                if d["status"] in ("parsed", "failed"):
                    return d
        import time

        time.sleep(1.0)
    return None


def first_id(res: dict) -> str | None:
    docs = res.get("documents") or []
    return docs[0]["id"] if docs else None


def main() -> int:
    st, created = call("POST", f"{WEB}/api/projects", {"name": "Office Upload Fixture"})
    if st != 201:
        print(f"  FATAL cannot create fixture project: {st} {created}")
        return 1
    pid = created["project"]["id"]
    print(f"fixture project {pid}")

    section("DOCX uploads and parses to real text")
    st, res = upload(pid, "Elecon G B_EON-Series.docx", DOCX_MIME, docx_bytes())
    check("docx accepted", st in (200, 201), f"{st} {str(res)[:200]}")
    doc_id = first_id(res)
    if not doc_id:
        print(f"  FATAL no document id returned: {res}")
        return 1
    d = poll_document(pid, doc_id)
    check("docx reaches a terminal status", d is not None, "still pending after 40s")
    if d:
        check("docx status is parsed", d["status"] == "parsed",
              f"{d['status']} / {d.get('error_detail')}")
        check("docx has no error detail", not d.get("error_detail"),
              str(d.get("error_detail")))
        text = d.get("extracted_text") or ""
        check("docx text was extracted", len(text) > 40, f"{len(text)} chars")
        check("docx kept its own wording, not ZIP noise",
              "Service factor 1.25" in text and "PK" not in text[:200], text[:160])
        check("docx table-free paragraphs are readable",
              "1500 rpm" in text, text[:200])
        check("parser version recorded", bool(d.get("parser_version")),
              str(d.get("parser_version")))
        check("page_count not invented for Word", d.get("page_count") is None,
              str(d.get("page_count")))

    section("XLSX uploads and parses to real text")
    st, res = upload(pid, "S3-Series.xlsx", XLSX_MIME, xlsx_bytes())
    check("xlsx accepted", st in (200, 201), f"{st} {str(res)[:200]}")
    x_id = first_id(res)
    d = poll_document(pid, x_id) if x_id else None
    check("xlsx reaches a terminal status", d is not None, "still pending")
    if d:
        check("xlsx status is parsed", d["status"] == "parsed",
              f"{d['status']} / {d.get('error_detail')}")
        text = d.get("extracted_text") or ""
        check("xlsx text was extracted", len(text) > 20, f"{len(text)} chars")
        check("sheet name kept", "S3 Series" in text, text[:160])
        for cell in ("S3-40", "S3-50", "1.25", "3.0"):
            check(f"xlsx cell {cell!r} survived", cell in text, text[:300])
        check("xlsx page_count not invented", d.get("page_count") is None,
              str(d.get("page_count")))

    section("legacy .doc fails loudly instead of storing mojibake")
    st, res = upload(pid, "old-catalogue.doc", DOC_MIME,
                     docparse.OLE2_MAGIC + b"\x00" * 2048)
    check("legacy doc is accepted by the type filter", st in (200, 201),
          f"{st} {str(res)[:200]}")
    o_id = first_id(res)
    d = poll_document(pid, o_id) if o_id else None
    check("legacy doc reaches a terminal status", d is not None, "still pending")
    if d:
        check("legacy doc is marked failed, not parsed", d["status"] == "failed",
              f"status={d['status']}")
        check("the error names the fix", "Save As" in (d.get("error_detail") or ""),
              repr(d.get("error_detail")))
        check("nothing was stored as grounding text",
              not (d.get("extracted_text") or "").strip(),
              repr((d.get("extracted_text") or "")[:80]))

    section("a docx renamed to .txt is flagged, not silently garbled")
    st, res = upload(pid, "sneaky.txt", "text/plain", docx_bytes())
    t_id = first_id(res)
    d = poll_document(pid, t_id) if t_id else None
    check("renamed binary reaches a terminal status", d is not None, "still pending")
    if d:
        check("it does not masquerade as clean text",
              d["status"] != "parsed" or (d.get("metadata") or {}).get("suspect_text") is True,
              f"status={d['status']} metadata={d.get('metadata')}")
        check("the record carries the warning",
              (d.get("metadata") or {}).get("suspect_text") is True
              or d["status"] == "failed",
              f"status={d['status']} metadata={d.get('metadata')}")

    section("a legitimate numeric CSV is not false-flagged")
    plain = b"Series,Size,kW,Ratio\r\nS3,S3-40,3.0,17\r\nS3,S3-50,4.0,19\r\n"
    st, res = upload(pid, "table.csv", "text/csv", plain)
    c_id = first_id(res)
    d = poll_document(pid, c_id) if c_id else None
    check("csv reaches a terminal status", d is not None, "still pending")
    if d:
        check("csv is parsed", d["status"] == "parsed",
              f"{d['status']} / {d.get('error_detail')}")
        check("csv is not flagged as suspect",
              not (d.get("metadata") or {}).get("suspect_text"), str(d.get("metadata")))
        check("csv text is intact", "S3-40,3.0,17" in (d.get("extracted_text") or ""),
              repr((d.get("extracted_text") or "")[:120]))

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