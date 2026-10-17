"""Internal API for the ISGEC AI Next.js frontend.

Separate from the legacy chat surface in ``main.py`` on purpose: those routes
are consumed by the old single-page UI and by ``scripts/``, and their shapes
are already depended upon. This module is the server-only BFF surface and may
change freely.

Two rules hold for everything in here:

  1. The browser never calls these endpoints. Only the Next.js server does,
     after it has already resolved the project and authorised the user. So
     ``project_id`` arriving in the body is informational, never trusted for
     access control.
  2. Selection is deterministic. The LLM may explain a result; it may never
     produce or alter one.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, BeforeValidator, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))

import docparse  # noqa: E402
import engine  # noqa: E402
import pricing  # noqa: E402
import reasoning  # noqa: E402

router = APIRouter()

# Bump when extraction changes, so a stored document can be re-parsed on demand.
# v3 returns per-page text (`pages`), which is what makes page-level citations
# possible. Anything parsed by v2 has no rows in isgec.document_pages.
PARSER_VERSION = "docparse-3"
UPLOAD_ROOT = Path(os.environ.get("UPLOAD_DIR", "D:/gearbox-selector/data/uploads"))

# Text kept per document. Enough to ground an answer, bounded so a 400-page
# RFQ cannot balloon a Postgres row.
MAX_TEXT_CHARS = 400_000

# Per-page ceiling. One 40-page table extract should not be allowed to consume
# the whole document budget on its own and starve every later page of context,
# and a page longer than this is either a drawing or an extraction failure --
# neither is worth quoting back at the model.
MAX_PAGE_CHARS = 20_000

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_T0 = time.time()


def _require_token(x_internal_token: str | None) -> None:
    """Shared secret so an unrelated local process cannot drive the engine.

    Disabled when the env var is unset, which is the case during local
    development only -- the frontend sends the header whenever it has one.
    """
    expected = os.environ.get("PYTHON_INTERNAL_TOKEN")
    if expected and x_internal_token != expected:
        raise HTTPException(status_code=401, detail="bad internal token")


# ==================================================================== health


@router.get("/health")
def health() -> dict:
    """Liveness plus a DB round-trip, so the frontend can tell 'Python is
    down' apart from 'the catalogue is empty'."""
    db_ok = True
    detail = ""
    try:
        engine.get_vendors()
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        db_ok = False
        detail = str(exc)[:200]
    return {
        "ok": db_ok,
        "version": "internal-1",
        "uptime_s": round(time.time() - _T0, 1),
        "db": "ok" if db_ok else f"error: {detail}",
    }


# ================================================================= pdf parse


class ParseIn(BaseModel):
    project_id: str
    storage_path: str
    file_name: str = "document.pdf"


@router.post("/api/pdf/parse")
def parse_pdf(body: ParseIn, x_internal_token: str | None = Header(default=None)) -> dict:
    _require_token(x_internal_token)

    if not _UUID_RE.match(body.project_id):
        raise HTTPException(status_code=400, detail="invalid project_id")

    # Containment is enforced here as well as in Node: this path arrives as a
    # string and must never escape the project's own folder.
    base = (UPLOAD_ROOT / body.project_id).resolve()
    target = (base / body.storage_path).resolve()
    if target != base and base not in target.parents:
        raise HTTPException(status_code=400, detail="path escapes project storage")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="stored file not found")

    suffix = target.suffix.lower()

    # `pages` is the point of this function. The blob used to be one string
    # joined with newlines, which threw away the only thing a citation needs:
    # which page a claim came from. Kept per page, 1-based, so page_no matches
    # what the reader sees in the PDF viewer rather than a library's zero-based
    # index -- otherwise every citation is off by one and lands on the wrong
    # table, which is worse than no citation at all.
    pages: list[dict] = []

    if suffix == ".pdf":
        try:
            import pdfplumber
        except ImportError as exc:  # pragma: no cover
            raise HTTPException(status_code=501, detail="pdfplumber not installed") from exc

        try:
            with pdfplumber.open(str(target)) as pdf:
                total = len(pdf.pages)
                kept = 0
                for idx, page in enumerate(pdf.pages, start=1):
                    if kept >= MAX_TEXT_CHARS:
                        break
                    try:
                        chunk = (page.extract_text() or "").strip()
                    except Exception:  # noqa: BLE001 - one bad page is not a bad PDF
                        chunk = ""
                    pages.append({"page_no": idx, "text": chunk[:MAX_PAGE_CHARS]})
                    kept += len(chunk)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - a corrupt file is a normal outcome
            raise HTTPException(status_code=422, detail=f"PDF unreadable: {exc}") from exc

        # Real page count, not the number of pages we managed to keep. The
        # viewer opens the original file, so a citation to page 80 of a 95-page
        # PDF has to be expressible even when only 40 pages were extracted.
        page_count: int | None = total
        metadata = {
            "kind": "pdf",
            "pages_extracted": len(pages),
            "paginated": True,
        }
        if len(pages) < total:
            metadata["truncated_pages"] = total - len(pages)

    else:
        # Office and text formats. These must not be allowed to "succeed" with
        # garbage: a .docx decoded as UTF-8 is ZIP header bytes, and the upload
        # would be marked parsed while the assistant grounds on noise.
        try:
            text, page_count, metadata = docparse.extract(target, MAX_TEXT_CHARS)
        except docparse.UnsupportedDocument as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - unreadable file is a normal outcome
            raise HTTPException(
                status_code=422, detail=f"{suffix} unreadable: {exc}"
            ) from exc

        # No page boundaries exist in this format, so it is stored as one page
        # instead of being faked into invented numbers. A citation that points
        # at "page 4 of 1" is a lie the reader has to catch.
        pages.append({"page_no": 1, "text": (text or "")[:MAX_PAGE_CHARS]})
        metadata = {**metadata, "paginated": False}

    full_text = "\n".join(p["text"] for p in pages)
    if len(full_text) > MAX_TEXT_CHARS:
        full_text = full_text[:MAX_TEXT_CHARS]
        metadata["truncated"] = True

    text = full_text

    # A parse that produced something unreadable is a fact the engineer has to
    # see. Flagging it leaves the document readable but marked, which beats
    # both extremes: failing a legitimate numeric CSV, and silently grounding
    # the assistant on ZIP header bytes.
    if not docparse.is_readable_text(text):
        metadata["suspect_text"] = True
        metadata["suspect_reason"] = "extraction produced no readable text"

    return {
        "page_count": page_count,
        "text": text,
        "pages": pages,
        "metadata": metadata,
        "parser_version": PARSER_VERSION,
    }


# ============================================================ page raster


class RenderIn(BaseModel):
    project_id: str
    storage_path: str
    page_no: int = Field(ge=1, description="1-based, matches citation page_no")
    dpi: int = Field(default=220, ge=48, le=420)
    target_width: int | None = Field(
        default=None,
        ge=64,
        le=6000,
        description="device pixels the page will occupy; derives DPI from the "
        "page's physical size so the raster matches the screen 1:1",
    )


# Raster sizes are bounded so a caller cannot ask for a 420 dpi A0 render and
# turn a page view into a multi-hundred-megabyte allocation. This is sized for
# the real case: an A4 catalogue page at ~2x a 1400px panel is ~16Mpx.
MAX_RASTER_PIXELS = 34_000_000


@router.post("/api/pdf/render")
def render_pdf_page(
    body: RenderIn,
    x_internal_token: str | None = Header(default=None),
) -> Response:
    """Rasterise one catalogue page to PNG.

    The browser-side viewer used to embed the PDF in an iframe, which handed
    rendering to Chrome's built-in PDF plugin. Privacy-focused browsers (Ulaa
    and similar) block that plugin, and the plugin is not something a page can
    work around. Sending a plain PNG sidesteps it entirely: there is no viewer,
    no extension surface and no MIME type for a blocker to match on.

    `target_width` lets the caller state how many real device pixels the page
    will occupy on screen. The DPI is then derived from the page's own physical
    size, so the returned raster matches the display 1:1 instead of being
    upscaled by the browser -- which is what made small text look soft.

    Bytes are never cached by the frontend beyond the HTTP header below, since
    the response is per-request and the caller re-requests on zoom.
    """
    _require_token(x_internal_token)

    if not _UUID_RE.match(body.project_id):
        raise HTTPException(status_code=400, detail="invalid project_id")

    # Same containment rule as parse_pdf: the path is caller-supplied text and
    # must stay inside the project's own folder.
    base = (UPLOAD_ROOT / body.project_id).resolve()
    target = (base / body.storage_path).resolve()
    if target != base and base not in target.parents:
        raise HTTPException(status_code=400, detail="path escapes project storage")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="stored file not found")

    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(
            status_code=501, detail="pymupdf not installed"
        ) from exc

    try:
        with pymupdf.open(str(target)) as doc:
            if body.page_no > doc.page_count:
                raise HTTPException(
                    status_code=404,
                    detail=f"page {body.page_no} is past the end of a "
                    f"{doc.page_count}-page document",
                )
            page = doc[body.page_no - 1]
            rect = page.rect
            if rect.width <= 0 or rect.height <= 0:
                raise HTTPException(status_code=422, detail="page has no area")

            page_w_in = rect.width / 72.0
            page_h_in = rect.height / 72.0

            if body.target_width:
                # DPI is pixels per inch, so the physical page width is all we
                # need: requested device pixels divided by inches gives the
                # density that makes the raster 1:1 with the screen.
                dpi = int(round(body.target_width / page_w_in))
                dpi = max(48, min(dpi, 420))
            else:
                dpi = body.dpi

            # Guard the allocation before handing anything to the rasteriser.
            while dpi > 48 and (page_w_in * dpi) * (page_h_in * dpi) > MAX_RASTER_PIXELS:
                dpi -= 8
            pix = page.get_pixmap(dpi=dpi)
            data = pix.tobytes("png")
            width_px, height_px = pix.width, pix.height
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - a corrupt file is a normal outcome
        raise HTTPException(status_code=422, detail=f"PDF unreadable: {exc}") from exc

    return Response(
        content=data,
        media_type="image/png",
        headers={
            # Private: these are authenticated catalogue pages, so a shared or
            # proxy cache must not hold on to them.
            "Cache-Control": "private, max-age=60",
            "X-Content-Type-Options": "nosniff",
            # Lets the viewer lay the image out at its natural pixel size
            # instead of guessing from CSS width.
            "X-Raster-Width": str(width_px),
            "X-Raster-Height": str(height_px),
        },
    )


# =============================================================== selection


def _defaulted(default: object):
    """Accept ``null`` for a field that has a default.

    The UI (and any script) sends an explicit ``null`` for a parameter the
    operator left blank. Pydantic reads ``null`` as "this value is null" rather
    than "no value supplied", so ``sf=None`` failed validation with
    "Input should be a valid number" and the entire request was rejected --
    a 422 for an optional field the caller simply did not fill. Here ``None``
    means "unset", and unset means "use the default". ``pn`` is deliberately
    never defaulted: a requirement with no value cannot be sized, so that one
    fails loudly with a message naming the field instead.
    """
    def _coerce(v):
        return default if v is None else v

    return BeforeValidator(_coerce)


def _pn_required(v):
    """Turn "Input should be a valid number" into the actual requirement.

    ``pn`` is the only field that cannot default, so it is the only one an
    operator can get wrong that has to stop the request. Naming it saves a
    round trip through the stack trace to find out which number was missing.
    """
    if v is None:
        raise ValueError(
            "required power pn (kW) is required - send a number, not null")
    return v


class SelectIn(BaseModel):
    pn: Annotated[float, BeforeValidator(_pn_required), Field(
        gt=0, description="required power in kW")]
    ratio_req: float | None = None
    sf: Annotated[float, _defaulted(1.0)] = 1.0
    # float, not int: real motor speeds are 1440, 1420, 960, 1780 rpm and the
    # form now accepts whatever the nameplate actually says. The engine snaps
    # to the nearest catalogue rating speed and reports the shift.
    n1_rpm: Annotated[float, Field(gt=0), _defaulted(1500)] = 1500
    cooling_type: Annotated[str, _defaulted("FAN")] = "FAN"
    mounting_type: Annotated[str, _defaulted("any")] = "any"
    hb: str | None = None
    gear_type: Annotated[str, _defaulted("any")] = "any"
    series: str | None = None
    vendor_id: int | None = None


@router.post("/api/gearbox/select")
def gearbox_select(body: SelectIn, x_internal_token: str | None = Header(default=None)) -> dict:
    _require_token(x_internal_token)

    vendor_ids = [body.vendor_id] if body.vendor_id else [v["id"] for v in engine.get_vendors()]
    if not vendor_ids:
        raise HTTPException(status_code=503, detail="no vendors in catalogue")

    results: list[dict] = []
    errors: list[dict] = []
    notes: list[dict] = []

    # One steel quote for the whole request, so every row is priced off the
    # same rate instead of each candidate triggering its own fetch. Falls back
    # to the manual .env rate (or nothing) rather than failing the selection.
    quote = pricing.get_metal_price()
    per_kg = quote.get('per_kg_inr')

    for vid in vendor_ids:
        try:
            # engine.select() rather than select_multi_vendor(): the latter
            # ignores vendor_id and returns a nested {vendors: {code: {...}}}
            # shape, so it cannot honour a single-vendor request.
            out = engine.select(
                kw=body.pn,
                rpm=body.n1_rpm,
                gr=body.ratio_req if body.ratio_req else 17,
                gear_type=body.gear_type,
                hb=body.hb or "YES",
                cooling=body.cooling_type,
                sf=body.sf,
                select_closest_power=False,  # smallest rated power >= PN
                vendor_id=vid,
                mounting_type=body.mounting_type or "any",
            )
        except Exception as exc:  # noqa: BLE001 - one bad vendor must not sink the rest
            errors.append({"vendor_id": vid, "error": str(exc)[:200]})
            continue

        # A mounting filter can legitimately exclude every series for one
        # vendor. That is a real answer, so surface the reason instead of
        # letting the request look like it found nothing.
        if out.get("mounting_note"):
            notes.append({"vendor_id": vid, "note": out["mounting_note"]})

        for c in out.get("candidates", []):
            if body.series and c["series"] != body.series:
                continue

            # Weight provenance is decided here rather than in select(), which
            # only carries catalogue weights and is shared with the legacy
            # price path. Every Elecon series now publishes a net weight, so
            # this only fills in the estimate when the catalogue genuinely has
            # none for the series, and flags it as indicative.
            weight = c.get("weight_kg")
            weight_published = weight is not None
            weight_basis: str | None = None
            if weight is None:
                est = engine.indicative_weight(c["series"], c["size"], c["vendor_id"])
                weight = est.get("weight_kg") if est else None
                if est:
                    weight_basis = (
                        f"{est.get('factor')} x {est.get('donor_series')}-"
                        f"{est.get('donor_size')} -- {est.get('basis')}"
                    )

            warnings: list[str] = []
            if not c["power_ok"]:
                warnings.append(
                    f"No size in {c['series']} reaches the required {c['required_pn']} kW "
                    f"(largest is {c['power_kw']} kW)."
                )
            if c["thermal_kw_effective"] and not c["thermal_ok"]:
                warnings.append(
                    f"Thermal check failed: {c['thermal_kw_effective']} kW derated vs "
                    f"{c['required_pn']} kW required."
                )
            elif c["thermal_kw_effective"] is None:
                warnings.append(
                    "No thermal rating published for this size/ratio/cooling; "
                    "thermal adequacy is unverified."
                )
            if c.get("forced_lube"):
                warnings.append("Forced lubrication required for this ratio.")

            # A catalogue only prints discrete ratio classes, so some deviation
            # is unavoidable. Past ~15% the output speed is materially wrong
            # and the caller must be told rather than left to assume.
            if c["ratio_dev"] > 0.15:
                warnings.append(
                    f"Ratio {c['ratio_iN']} deviates {c['ratio_dev'] * 100:.0f}% from the "
                    f"requested {c['ratio_req']}: output is {c['n2_actual']} rpm instead of "
                    f"{round(c['n1_rpm'] / c['ratio_req'], 2)} rpm. Confirm this is acceptable."
                )
            # Power and thermal ratings only exist at the catalogue rating
            # speeds, so an entered speed is snapped to the nearest one. Say so
            # whenever that moved the number: 1440 rpm silently becoming 1500
            # rpm is exactly the kind of silent substitution an engineer will
            # not catch when defending the selection.
            if float(body.n1_rpm) != float(c["n1_rpm"]):
                shift = abs(float(c["n1_rpm"]) - float(body.n1_rpm))
                pct = (shift / float(body.n1_rpm) * 100) if body.n1_rpm else 0.0
                warnings.append(
                    f"Rated/thermal figures are taken at {c['n1_rpm']:.0f} rpm, the nearest "
                    f"catalogue rating speed to the requested {float(body.n1_rpm):g} rpm "
                    f"({pct:.0f}% away). Power available at the requested speed differs."
                )
            # The catalogue carries two different ratings for this exact
            # frame/ratio/speed. The engine used the lower one so the gearbox
            # cannot be undersized, but the disagreement is the vendor's to
            # settle, not ours to hide.
            if c.get("power_conflict"):
                lo, hi = c["power_conflict"]
                warnings.append(
                    f"IMPORT CONFLICT: the catalogue lists this size at iN {c['ratio_iN']} as both "
                    f"{lo:,.0f} kW and {hi:,.0f} kW. The lower figure ({lo:,.0f} kW) was used so "
                    f"the selection cannot be undersized. Confirm the rating with the vendor."
                )
            if weight is None:
                warnings.append("No net weight available, published or estimated.")
            elif not weight_published:
                warnings.append(
                    f"Net weight {weight:,.0f} kg is an ESTIMATE "
                    f"({c['series']} has no published weight) - confirm with the vendor."
                )

            # Material cost = net weight x steel rate in INR/kg. This is steel
            # content only, not a price quote: it ignores machining, gearbox
            # internals, lubricants and margin.
            est_price = round(weight * per_kg, 2) if (
                weight is not None and per_kg is not None) else None
            if body.mounting_type and body.mounting_type != "any":
                offered = c.get("mountings_offered") or []
                warnings.append(
                    f"Mounting {body.mounting_type} is confirmed for {c['series']} "
                    f"(catalogue also publishes: {', '.join(offered) or 'n/a'}). "
                    f"Confirm the exact housing variant on the drawing."
                )

            results.append(
                {
                    "model": c["model"],
                    "vendor_id": c["vendor_id"],
                    "vendor_code": _vendor_code(c["vendor_id"]),
                    "series": c["series"],
                    "size": c["size"],
                    "gear_type": c["gear_type"],
                    "power_kw": c["power_kw"],
                    "power_ok": c["power_ok"],
                    "required_kw": c["required_pn"],
                    "ratio_req": c["ratio_req"],
                    "ratio_iN": c["ratio_iN"],
                    "ratio_dev": c["ratio_dev"],
                    "n1_rpm": c["n1_rpm"],
                    "n2_actual": c["n2_actual"],
                    "cooling_type": c["cooling"],
                    "forced_lube": c["forced_lube"],
                    "mounting_type": c["mounting_type"],
                    "mountings_offered": c.get("mountings_offered", []),
                    "thermal_kw": c["thermal_kw"],
                    "thermal_kw_effective": c["thermal_kw_effective"],
                    "thermal_ok": c["thermal_ok"],
                    "weight_kg": weight,
                    "weight_published": weight_published,
                    "weight_basis": weight_basis,
                    "est_price_inr": est_price,
                    "power_conflict": c.get("power_conflict"),
                    "warnings": warnings,
                }
            )

    if not results and errors:
        raise HTTPException(status_code=502, detail=f"selection failed: {errors}")

    # Best fit first: a model that cannot carry the load never outranks one
    # that can, however well its ratio happens to match. Within the power-ok
    # group, the closest ratio wins, then the smaller (cheaper) gearbox.
    def rank(r):
        try:
            series_idx = engine.SERIES_ORDER.index(r["series"])
        except ValueError:
            series_idx = len(engine.SERIES_ORDER)
        return (not r["power_ok"], r["ratio_dev"], int(r["size"]), series_idx)

    results.sort(key=rank)
    return {
        "results": results,
        "errors": errors,
        "notes": notes,
        "price_per_kg_inr": per_kg,
        "price_source": quote.get("source"),
        "price_fetched_at": quote.get("fetched_at"),
        "price_note": _price_note(quote),
    }


_VENDOR_CACHE: dict[int, str] = {}


def _price_note(quote: dict) -> str:
    """Provenance line for the steel rate, so a price is never a bare number."""
    src = quote.get("source")
    if src == "metalcharts":
        return (
            f"Steel {quote.get('metal')} {quote.get('raw_price_usd'):,.2f} USD/"
            f"{quote.get('quote_unit')} x {quote.get('usd_inr')} INR/USD = "
            f"{quote.get('per_kg_inr'):,.2f} INR/kg (MetalCharts). Est. cost is "
            f"steel content only, not a price quote."
        )
    if src == "manual":
        note = " Set METALCHARTS_API_KEY for a live rate."
        rejected = quote.get("rejected_note")
        if rejected:
            note = f" Live feed refused: {rejected}"
        return f"Using manual rate {quote['per_kg_inr']:,.2f} INR/kg.{note}"
    return "No steel rate configured; set METALCHARTS_API_KEY or STEEL_PRICE_PER_KG_INR."


def _vendor_code(vendor_id: int) -> str:
    if not _VENDOR_CACHE:
        for v in engine.get_vendors():
            _VENDOR_CACHE[v["id"]] = v.get("code") or f"vendor{v['id']}"
    return _VENDOR_CACHE.get(vendor_id, f"vendor{vendor_id}")


# ============================================================== explanation


class ExplainIn(BaseModel):
    question: str
    selection: dict | None = None
    # Documents the caller has already authorised, by id. The page text is
    # fetched here rather than posted in: a 400-page RFQ is megabytes per turn,
    # and this endpoint is the wrong place to carry it. Ids only -- this never
    # widens the caller's scope, and an unknown id simply yields no pages.
    documents: list[dict] = Field(default_factory=list)
    history: list[dict] = Field(default_factory=list)


@router.post("/api/gearbox/explain")
def gearbox_explain(body: ExplainIn, x_internal_token: str | None = Header(default=None)) -> dict:
    _require_token(x_internal_token)

    if not body.question.strip():
        raise HTTPException(status_code=400, detail="empty question")

    pages = reasoning.load_document_pages(
        [d.get("document_id") for d in body.documents if d.get("document_id")]
    )

    try:
        result = reasoning.answer_project_question(
            question=body.question,
            selection=body.selection,
            pages=pages,
            history=body.history,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"explanation failed: {exc}") from exc

    if result:
        return {
            "answer": result["answer"],
            "citations": result["citations"],
            "degraded": False,
        }

    # The LLM is rate-limited or unconfigured. Most questions are pure
    # catalogue lookups that the database can answer exactly, so fall back
    # to the authoritative rows rather than reporting the assistant as
    # down. The caller shows this with a "degraded" marker.
    try:
        fallback = reasoning.deterministic_answer(
            question=body.question,
            selection=body.selection,
        )
    except Exception as exc:  # noqa: BLE001
        _log(f"[gearbox_explain] deterministic fallback failed: {exc}")
        fallback = None

    if fallback:
        # The fallback is read straight off the catalogue rows, so attribute it
        # through the catalogue page index: the pages it names are the pages
        # those rows were parsed from. Lexical scoring is deliberately not used
        # -- the fallback restates bare figures with no prose to match against,
        # so it would either find nothing or pick a plausible wrong page.
        doc_ids: list[str] = []
        for p in pages:
            did = p.get("document_id")
            if did and str(did) not in doc_ids:
                doc_ids.append(str(did))
        try:
            degraded_citations = reasoning.cite_selection(
                body.selection, body.question, doc_ids)
        except Exception as exc:  # noqa: BLE001 - attribution must not sink the turn
            _log(f"[gearbox_explain] degraded citation failed: {exc}")
            degraded_citations = []

        return {
            "answer": fallback,
            "citations": degraded_citations,
            "degraded": True,
            "reason": reasoning.last_failure_reason or "llm unavailable",
        }

    # Nothing to fall back on. Do not claim "no LLM configured" when a key
    # is present: a missing key is a deployment fix, a rate limit is not,
    # and an IP block is neither.
    raise HTTPException(
        status_code=503,
        detail=(
            f"LLM did not return an answer ({reasoning.last_failure_reason})"
            if reasoning._api_key()
            else "no LLM configured"
        ),
    )