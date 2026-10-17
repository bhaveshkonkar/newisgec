"""Text extraction for the document formats the uploader accepts.

The upload route accepts PDF, DOC/DOCX, XLS/XLSX, CSV and TXT. Only PDF had a
real parser. Everything else fell through to `bytes.decode("utf-8")`, which for
an OOXML file returns the ZIP local-header bytes as mojibake -- the upload
"succeeds", the document is marked parsed, and the assistant is then grounded
on garbage. Silent garbage is worse than a refusal, because nothing in the UI
tells the engineer the catalogue they uploaded is not actually readable.

So:
  * docx  -> read the OOXML package and pull paragraphs and tables in order
  * xlsx  -> openpyxl, values only (no formulas, no formatting)
  * doc/xls -> legacy OLE2, refused with an actionable message
  * csv/txt -> encoding sniffed, because Excel writes UTF-16 by default

Every extractor is bounded by max_chars and refuses rather than inventing text.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

# OOXML is a ZIP container. A tiny ZIP with a huge declared entry is the
# standard zip-bomb shape, and these files arrive from the internet.
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_MEMBERS = 5_000

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

# Legacy .doc/.xls are OLE2 compound files. If we see this magic we know the
# extension is telling the truth and we cannot parse it without a converter.
OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_MAGIC = b"PK\x03\x04"


class UnsupportedDocument(Exception):
    """The file is a real format we cannot read. Safe to show the user."""


# --------------------------------------------------------------------- zip


def _open_zip(path: Path) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise UnsupportedDocument(
            "not a readable Office file (the .docx/.xlsx extension does not match "
            "its contents -- re-save it from Office)"
        ) from exc

    if len(zf.infolist()) > MAX_MEMBERS:
        zf.close()
        raise UnsupportedDocument("Office file contains too many internal parts")

    total = 0
    for info in zf.infolist():
        total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            zf.close()
            raise UnsupportedDocument(
                "Office file expands to an implausible size and was rejected"
            )
    return zf


# -------------------------------------------------------------------- docx


def _docx_text(path: Path, max_chars: int) -> str:
    with _open_zip(path) as zf:
        names = set(zf.namelist())
        part = None
        for candidate in ("word/document.xml", "word/document2.xml"):
            if candidate in names:
                part = candidate
                break
        if part is None:
            raise UnsupportedDocument(
                "no Word document body found inside the file; it may be a "
                "spreadsheet renamed to .docx"
            )
        try:
            xml = zf.read(part)
        except (RuntimeError, zipfile.BadZipFile, OSError) as exc:
            raise UnsupportedDocument(f"Word file could not be decompressed: {exc}") from exc

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise UnsupportedDocument(f"Word document XML is malformed: {exc}") from exc

    body = root.find(f"{{{W_NS}}}body")
    if body is None:
        raise UnsupportedDocument("Word document has no body")

    lines: list[str] = []

    def para_text(node: ElementTree.Element) -> str:
        out: list[str] = []
        for el in node.iter():
            tag = el.tag
            if tag == f"{{{W_NS}}}t":
                out.append(el.text or "")
            elif tag == f"{{{W_NS}}}tab":
                out.append("\t")
            elif tag in (f"{{{W_NS}}}br", f"{{{W_NS}}}cr"):
                out.append("\n")
        return "".join(out).strip()

    def walk(container: ElementTree.Element) -> None:
        # Document order matters: a paragraph after a table is not the same
        # spec as one before it, so walk children rather than flattening.
        for child in container:
            if child.tag == f"{{{W_NS}}}p":
                t = para_text(child)
                if t:
                    lines.append(t)
            elif child.tag == f"{{{W_NS}}}tbl":
                for row in child.findall(f"{{{W_NS}}}tr"):
                    cells = []
                    for cell in row.findall(f"{{{W_NS}}}tc"):
                        cells.append(" ".join(
                            p for p in (para_text(p) for p in cell.findall(f"{{{W_NS}}}p"))
                            if p
                        ))
                    # keep empty cells: a blank column in a selection table is
                    # information ("not published") and must not silently shift
                    cells = [c if c else "-" for c in cells]
                    if any(c != "-" for c in cells):
                        lines.append(" | ".join(cells))

    walk(body)
    return "\n".join(lines)[:max_chars]


# -------------------------------------------------------------------- xlsx


def _xlsx_text(path: Path, max_chars: int) -> str:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedDocument(
            "spreadsheet support is unavailable on this service (openpyxl not installed)"
        ) from exc

    try:
        # Hand openpyxl a file object rather than a path: it dispatches on the
        # filename extension, so an xlsx that arrived as "catalogue.dat" would
        # be rejected by name even though its content is fine. We already
        # identified it by content, so let the content win.
        #
        # data_only=True -> cached values, so a formula cell yields the number
        # an engineer would see in Excel rather than "=SUM(A1:A9)".
        wb = openpyxl.load_workbook(
            io.BytesIO(path.read_bytes()), read_only=True, data_only=True,
            keep_links=False,
        )
    except Exception as exc:  # noqa: BLE001 - any failure is an unreadable file
        raise UnsupportedDocument(f"spreadsheet could not be opened: {exc}") from exc

    lines: list[str] = []
    try:
        for ws in wb.worksheets:
            if ws.sheet_state != "visible":
                continue
            lines.append(f"# sheet: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                cells = ["" if c is None else str(c).strip() for c in row]
                while cells and cells[-1] == "":
                    cells.pop()
                if not cells:
                    continue
                lines.append("\t".join(cells))
                if sum(len(x) for x in lines) > max_chars:
                    return "\n".join(lines)[:max_chars]
    finally:
        try:
            wb.close()
        except Exception:  # noqa: BLE001
            pass

    return "\n".join(lines)[:max_chars]


# ------------------------------------------------------------------ csv/txt

_BOMS = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)


def _sniff_text(raw: bytes) -> str:
    for bom, enc in _BOMS:
        if raw.startswith(bom):
            return raw.decode(enc, errors="replace")

    # Excel's "CSV UTF-8" and plain Notepad both save utf-8, but a .csv exported
    # from older Excel is UTF-16 with no BOM at all. A dense run of NULs in the
    # first block is the giveaway.
    head = raw[:4096]
    if head.count(0) > len(head) // 4 and len(head) > 16:
        return raw.decode("utf-16-le", errors="replace")

    return raw.decode("utf-8", errors="replace")


# ------------------------------------------------------------------- entry

TEXTUAL = {".csv", ".txt", ".md", ".tsv"}


def extract(path: Path, max_chars: int) -> tuple[str, int | None, dict]:
    """Return (text, page_count, metadata).

    page_count stays None for office formats: Word and Excel have no pages we
    can honestly count, and inventing one would put a number in the UI that
    means nothing.
    """
    suffix = path.suffix.lower()
    meta: dict = {"kind": suffix.lstrip(".") or "binary"}

    head = path.open("rb").read(8)

    if suffix in TEXTUAL:
        raw = path.read_bytes()
        text = _sniff_text(raw)
        meta["bytes"] = len(raw)
        if text.startswith("\ufeff"):
            text = text.lstrip("\ufeff")
        return text[:max_chars], None, meta

    if suffix in {".docx", ".docm", ".dotx"}:
        if head.startswith(OLE2_MAGIC):
            raise UnsupportedDocument(
                "this is a legacy Word 97-2003 .doc file; open it and use "
                "'Save As' .docx, then upload that"
            )
        text = _docx_text(path, max_chars)
        meta["kind"] = "docx"
        return text, None, meta

    if suffix in {".xlsx", ".xlsm", ".xltx"}:
        if head.startswith(OLE2_MAGIC):
            raise UnsupportedDocument(
                "this is a legacy Excel 97-2003 .xls file; open it and use "
                "'Save As' .xlsx, then upload that"
            )
        text = _xlsx_text(path, max_chars)
        meta["kind"] = "xlsx"
        meta["sheets"] = text.count("# sheet:")
        return text, None, meta

    if suffix in {".doc", ".xls"}:
        raise UnsupportedDocument(
            f"legacy {suffix[1:].upper()} files cannot be read; open it and use "
            f"'Save As' {'.docx' if suffix == '.doc' else '.xlsx'}, then upload that"
        )

    if suffix == ".pdf":
        raise UnsupportedDocument("handled by the PDF path")

    # Unknown extension. If it opens with ZIP magic it is still an Office file
    # under the wrong name, which is a common export bug worth naming.
    if head.startswith(ZIP_MAGIC):
        try:
            with _open_zip(path) as zf:
                names = set(zf.namelist())
        except UnsupportedDocument:
            names = set()
        if any(n.startswith("word/") for n in names):
            text = _docx_text(path, max_chars)
            meta["kind"] = "docx"
            meta["renamed_from"] = suffix
            return text, None, meta
        if any(n.startswith("xl/") for n in names):
            text = _xlsx_text(path, max_chars)
            meta["kind"] = "xlsx"
            meta["renamed_from"] = suffix
            return text, None, meta
        raise UnsupportedDocument(
            "this .zip archive contains no Word or Excel document"
        )

    if b"\x00" in path.open("rb").read(4096):
        raise UnsupportedDocument(
            "this looks like a binary file rather than a document we can read"
        )

    text = _sniff_text(path.read_bytes())
    meta["bytes"] = path.stat().st_size
    return text[:max_chars], None, meta


_GEARBOX_HINT = re.compile(
    r"(gear\s*box|gearbox|service\s*factor|ratio|transmission|kW|rpm)", re.IGNORECASE
)

# ------------------------------------------------------- plausibility checks

def is_readable_text(text: str, minimum: int = 16) -> bool:
    """Encoding sanity only. Applies to every textual kind.

    Catches the case where bytes were decoded with errors="replace" but the
    result is not actually prose: NUL runs, mostly-unprintable output, or
    nothing at all. Deliberately does *not* look for gearbox vocabulary --
    a legitimate vendor CSV full of bare numbers must not be flagged.
    """
    stripped = text.strip()
    if len(stripped) < minimum:
        return False
    if "\x00" in text:
        return False
    # ZIP/binary decoded as latin-1 yields long runs of box characters and
    # accented mojibake rather than words.
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\t")
    if printable / len(text) <= 0.9:
        return False
    replacement = text.count("�")
    return replacement / len(text) < 0.02


def looks_like_text(text: str, minimum: int = 40) -> bool:
    """Stricter: also expects gearbox vocabulary. Informational only."""
    return is_readable_text(text, minimum) and bool(_GEARBOX_HINT.search(text))