"""EON-Series gearbox chat assistant.

Single-page chat UI served at / ; the chat API is POST /api/chat.

Flow:
  1. user says "gearbox" / selection intent -> server replies with an in-chat form
  2. user fills the form, submits   -> deterministic selection against the
                                       imported catalog, results returned
  3. user asks a catalog question (compare, specs, ranges) -> Groq answers
     using catalog context + conversation history
"""
import os
import re
import sys
import uuid
from collections import deque
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, Form as FastAPIForm
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine
import reasoning
import pricing
import internal_api

app = FastAPI(title='EON-Series gearbox selector')

# Server-only surface for the ISGEC AI Next.js backend. The legacy chat
# routes above are untouched; these are additive and may change freely.
app.include_router(internal_api.router)

# Simple in-memory session store: session_id -> deque of (role, content)
SESSIONS: dict[str, deque] = {}
# Last successfully-submitted requirement per session (for compare intents)
LAST_FORM: dict[str, dict] = {}
# Last priced/selected candidate per session (so "this model" resolves)
LAST_SELECTION: dict[str, dict] = {}
MAX_HISTORY = 8  # last 4 user/assistant pairs


def _get_session(session_id: str | None) -> deque:
    if not session_id:
        session_id = str(uuid.uuid4())
    if session_id not in SESSIONS:
        SESSIONS[session_id] = deque(maxlen=MAX_HISTORY)
    return SESSIONS[session_id]


def _add_to_history(session_id: str | None, role: str, content: str):
    hist = _get_session(session_id)
    hist.append({'role': role, 'content': content})


FORM = {
    'title': 'Gearbox requirement',
    'fields': [
        {'id': 'vendor_id', 'label': 'Vendor', 'type': 'select',
         'options': [],  # populated dynamically from /api/vendors
         'default': '1'},
        {'id': 'kw', 'label': 'Required mechanical power · KW (kW)',
         'type': 'number', 'required': True, 'min': 0.1, 'step': 0.1,
         'placeholder': 'e.g. 400'},
        {'id': 'rpm', 'label': 'Motor / input speed · RPM',
         'type': 'number', 'required': True, 'min': 100, 'step': 10,
         'placeholder': 'e.g. 1480'},
        {'id': 'gr', 'label': 'Reduction ratio · GR (e.g. 17:1 or 13)',
         'type': 'text', 'required': True,
         'placeholder': 'e.g. 17:1'},
        {'id': 'gear_type', 'label': 'Gear unit type · Type', 'type': 'select',
         'options': [
             {'value': 'any', 'label': 'Any'},
             {'value': 'helical', 'label': 'Helical (S-series)'},
             {'value': 'bevel_helical', 'label': 'Bevel-Helical (K-series)'}],
         'default': 'bevel_helical'},
        {'id': 'hb', 'label': 'Horizontal base · H/B', 'type': 'select',
         'options': ['YES', 'NO'], 'default': 'YES'},
        {'id': 'cooling', 'label': 'Cooling', 'type': 'select',
         'options': ['FAN', 'Natural', 'FLS'], 'default': 'FAN'},
        {'id': 'lubrication', 'label': 'Lubrication', 'type': 'select',
         'options': ['SPLASH', 'FLS', 'MDP'], 'default': 'SPLASH'},
        {'id': 'sf', 'label': 'Service factor · S/F',
         'type': 'number', 'required': True, 'min': 1, 'step': 0.05,
         'placeholder': 'e.g. 1.5', 'default': '1.5'},
    ],
}

NO_INTENT = ("I can help pick the right EON-Series gearbox from the Elecon "
             "catalog. Type **gearbox** to open the requirement form, or ask "
             "catalog questions like *'compare K3-19 vs K3-20'* or *'S3 size "
             "range'*.")

INTRO = ("Let's size your unit. Fill in the requirement columns (same "
         "nomenclature as the price list) and I'll scan the EON-Series "
         "catalog (S1–S4 helical, K2–K4 bevel-helical) for the best "
         "matching models with their catalog ratings.")

ERROR = "Hmm, that didn't parse. Could you check the fields and resubmit?"

# Selection intent = user wants a specific sizing (has numbers + action words)
SELECTION_TRIGGERS = ('select', 'size', 'find', 'pick', 'recommend', 'gearbox')

# Catalog QA intent = user asks about specs, comparisons, ranges
CATALOG_TRIGGERS = ('compare', 'vs', 'versus', 'difference', 'spec', 'specs',
                    'rating', 'capacity', 'power', 'thermal', 'ratio', 'speed',
                    'size', 'model', 'series', 'forced', 'mdp', 'cooling',
                    'fan', 'fls', 'natural', 'lubrication', 'range', 'what',
                    'which', 'how', 'tell', 'show', 'list', 'k3-', 'k2-',
                    'k4-', 's1-', 's2-', 's3-', 's4-')


# Price intent = user asks what a model costs in steel / per kg.
# Regex + word boundaries: "pricing", "prices", "rate" must match, but
# "separate"/"accurate" must not.
PRICE_RE = re.compile(
    r'\b(pric\w*|cost\w*|how\s+much|rupee\w*|rs\.?|inr|worth|estimat\w*|'
    r'budget|amount|weight\w*|per\s*kg|per\s*kilo\w*|material|steel)\b',
    re.I)

# Model code like B3-180, K2-25, H2-250, S3-19
MODEL_RE = re.compile(r'\b([A-Z]{1,2}\d{1,2})\s*[- ]\s*(\d{2,3})\b')


def _price_quote_note(quote: dict) -> str:
    """Provenance line for the steel rate used in a price answer."""
    per_kg = quote.get('per_kg_inr')
    if per_kg is None:
        return ('_No steel rate available: set `METALCHARTS_API_KEY` or '
                '`STEEL_PRICE_PER_KG_INR` in .env._')
    src = quote.get('source')
    if src == 'metalcharts':
        return (f"_Steel rate: MetalCharts {quote['metal']} "
                f"{quote['raw_price_usd']:,.2f} USD/{quote['quote_unit']} x "
                f"{quote['usd_inr']} USD/INR = ₹{per_kg:,.2f}/kg "
                f"(fetched {quote.get('fetched_at')})._")
    return (f"_Steel rate: ₹{per_kg:,.2f}/kg (manual fallback from "
            f"STEEL_PRICE_PER_KG_INR; live quote unavailable)._")


_VENDOR_NAMES: dict[int, str] = {}


def _series_belongs_to(series: str, vendor_id: int) -> bool:
    return engine.series_belongs_to(series, vendor_id)


def _vendor_label(row: dict) -> str:
    name = row.get('vendor_name') or row.get('vendor_code')
    if name:
        return name
    vid = row.get('vendor_id')
    if vid is None:
        return '—'
    if not _VENDOR_NAMES:
        for v in engine.get_vendors():
            _VENDOR_NAMES[v['id']] = v['name']
    return _VENDOR_NAMES.get(vid, f'vendor {vid}')


def _format_price_table(rows: list[dict], quote: dict, heading: str) -> str:
    lines = [f"**{heading}**", '',
             '| Vendor | Model | Net weight | Steel rate | Est. material cost |',
             '|---|---|---|---|---|']
    rate = ('₹' + f"{quote['per_kg_inr']:,.2f}/kg"
            if quote.get('per_kg_inr') else 'n/a')
    for r in rows:
        vendor = _vendor_label(r)
        model = r.get('model') or f"{r.get('series')}-{r.get('size')}"
        lines.append(f'| {vendor} | {model} | {_fmt_weight(r)} | '
                     f'{rate} | {_fmt_price(r)} |')
    lines.append('')
    est = next((r for r in rows if r.get('est_price_inr_indicative') is not None
                and r.get('weight_kg') is None), None)
    if est:
        b = est.get('estimate_basis') or {}
        lines.append(f'_Weight estimated from {b.get("donor_series")}-'
                     f'{b.get("donor_size")} ×{b.get("factor")}: the catalogue '
                     f'publishes no weight for {est["series"]}. Indicative '
                     f'only, not a published figure._')
        lines.append('')
    lines.append(_price_quote_note(quote))
    lines.append('_Estimate = catalogue approximate net weight x steel rate; '
                 'material cost only, not a selling price._')
    return '\n'.join(lines)


def _price_reply(msg: str, session_id: str | None) -> str:
    """Deterministic steel-cost answer: never delegated to the LLM."""
    key = session_id or ''
    last = LAST_FORM.get(key)
    m = MODEL_RE.search(msg.upper())

    if m:
        series, size = m.group(1), m.group(2)
        rows = engine.weights_for(series, size,
                                  vendor_id=(last or {}).get('vendor_id'))
        if rows:
            quote = pricing.enrich(rows)
            if rows[0].get('weight_kg') is not None:
                LAST_SELECTION[key] = rows[0]
            return _format_price_table(
                rows, quote, f'Steel cost for {series}-{size}')
        # a model was named explicitly -> never answer with a different model
        if engine.series_size_exists(series, size):
            vid = (last or {}).get('vendor_id')
            row = {'vendor_id': vid, 'series': series, 'size': size,
                   'model': f'{series}-{size}-HN-HB-FAN', 'weight_kg': None}
            if vid is None:
                for v in engine.get_vendors():
                    if _series_belongs_to(series, v['id']):
                        row['vendor_id'] = vid = v['id']
                        break
            quote = pricing.enrich([row])
            if row.get('est_price_inr_indicative') is not None:
                LAST_SELECTION[key] = row
                return _format_price_table(
                    [row], quote, f'Steel cost for {series}-{size}')
            have = ', '.join(engine.series_with_weights(vid))
            return (f'**{series}-{size}** is in the catalog, but this '
                    f'catalogue publishes no net weight for it and there is '
                    f'no estimate basis, so I cannot give a weight-based '
                    f'steel cost. Series with published weights: {have}.')
        return (f'I have no {series}-{size} in the imported catalogs. Check '
                f'the model code, e.g. B3-180, K2-25, H2-250 or S3-19.')

    sel = LAST_SELECTION.get(key)
    if last:
        try:
            req = engine.select(**last)
        except Exception:
            req = None
        if req and req.get('candidates'):
            cands = req['candidates'][:5]
            quote = pricing.enrich(cands)
            LAST_SELECTION[key] = cands[0]
            return _format_price_table(
                cands, quote,
                'Steel cost for your selection (' + ', '.join(
                    f"{c['model']}" for c in cands[:3]) + ')')
    if sel:
        quote = pricing.enrich([sel])
        return _format_price_table([sel], quote,
                                   f'Steel cost for {sel.get("model")}')

    return ("Tell me the model code (e.g. **B3-180**, **K2-25**, **H2-250**, "
            "**S3-19**) or submit the requirement form, and I will return "
            "net weight x live steel rate in INR.")


def _looks_like_price(msg: str) -> bool:
    if not msg:
        return False
    if PRICE_RE.search(msg):
        return True
    return '₹' in msg


def _looks_like_selection(msg: str) -> bool:
    """Heuristic: message looks like a sizing request (has numbers + trigger)."""
    ml = msg.lower()
    has_trigger = any(t in ml for t in SELECTION_TRIGGERS)
    has_numbers = bool(re.search(r'\d', msg))
    return has_trigger and has_numbers


def _fmt_price(r: dict) -> str:
    """Price cell: published basis, else the clearly-marked estimate."""
    if r.get('est_price_inr') is not None:
        return '₹' + f"{r['est_price_inr']:,.0f}"
    if r.get('est_price_inr_indicative') is not None:
        return '~₹' + f"{r['est_price_inr_indicative']:,.0f} (est.)"
    return 'n/a'


def _fmt_weight(r: dict) -> str:
    if r.get('weight_kg') is not None:
        return f"{r['weight_kg']:,.0f} kg"
    if r.get('weight_kg_indicative') is not None:
        return f"~{r['weight_kg_indicative']:,.0f} kg (est.)"
    return 'not in catalogue'


def _format_compare_reply(rows: list, vals: dict) -> str:
    """Render the deterministic cross-vendor comparison as a markdown table."""
    def num(x, d=1):
        return f"{x:,.{d}f}" if isinstance(x, (int, float)) else '—'

    header = (f"**Cross-vendor comparison** — {num(vals.get('kw'))} kW · "
              f"{num(vals.get('rpm'))} rpm · GR {vals.get('gr')} · "
              f"{str(vals.get('gear_type') or 'any')} · S/F "
              f"{num(vals.get('sf'))}")

    lines = [header, "", "| Vendor | Model | Ratio iN | Rated kW | vs PN | "
             "Thermal (eff) | Weight | Est. price | Verdict |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        verdict = 'MATCH'
        if not r['power_ok']:
            verdict = 'NO SIZE ≥ PN'
        elif not r['thermal_ok']:
            verdict = 'thermal note (advisory)'
        vs_pn = 'OK' if r['power_ok'] else 'SHORT'
        th = (num(r['thermal_kw_effective']) + ' kW'
              if r.get('thermal_kw_effective') is not None else '—')
        wt = _fmt_weight(r)
        price = _fmt_price(r)
        lines.append(
            f"| {r['vendor_name']} | {r['model']} | {r['ratio_iN']} "
            f"({r['n2_actual']} rpm) | {num(r['power_kw'])} | {vs_pn} | "
            f"{th} | {wt} | {price} | {verdict} |")
    if rows and rows[0].get('price_per_kg_inr'):
        src = rows[0].get('price_source')
        lines.append('')
        lines.append(f"_Est. price = weight × ₹{rows[0]['price_per_kg_inr']:,.2f}/kg "
                     f"({src}); catalogue approximate net weight. "
                     f"~ = weight estimated, not published._")
    return '\n'.join(lines)


def _pricing_note(candidates: list[dict]) -> str:
    """One-line price summary for the chat reply (weight x metal price/kg)."""
    top = next((c for c in candidates if c.get('weight_kg') is not None), None)
    if not top:
        est = next((c for c in candidates
                    if c.get('est_price_inr_indicative') is not None), None)
        if est:
            b = est.get('estimate_basis') or {}
            return (f"\n\n**Price estimate (indicative)** — {est['model']}: "
                    f"~{est['weight_kg_indicative']:,.0f} kg × "
                    f"₹{est['price_per_kg_inr']:,.2f}/kg = "
                    f"~₹{est['est_price_inr_indicative']:,.0f}. "
                    f"Weight is estimated from {b.get('donor_series')}-"
                    f"{b.get('donor_size')} because this catalogue publishes "
                    f"no weight for {est['series']}; not a published figure.")
        return ('\n\n_Price: set `METALCHARTS_API_KEY` (or '
                '`STEEL_PRICE_PER_KG_INR`) in .env to show weight-based '
                'estimates._')
    return (f"\n\n**Price estimate** — {top['model']}: net weight "
            f"{top['weight_kg']:,.0f} kg × ₹{top['price_per_kg_inr']:,.2f}/kg "
            f"= **₹{top['est_price_inr']:,.0f}** "
            f"({top['price_source']} rate, approximate).")


def _looks_like_catalog_qa(msg: str) -> bool:
    """Heuristic: message asks about catalog data (specs, comparisons)."""
    ml = msg.lower()
    return any(t in ml for t in CATALOG_TRIGGERS)


class ChatIn(BaseModel):
    message: str = Field(default='')
    form: dict | None = None
    session_id: str | None = None


def _clean_form(raw: dict) -> dict:
    """Coerce + whitelist form values; raise ValueError on bad input."""
    vals = {}
    vals['kw'] = float(raw.get('kw'))
    vals['rpm'] = float(raw.get('rpm'))
    vals['gr'] = str(raw.get('gr')).strip()
    vals['gear_type'] = str(raw.get('gear_type') or 'any')
    vals['hb'] = str(raw.get('hb')).strip().upper()
    vals['cooling'] = str(raw.get('cooling')).strip()
    vals['lubrication'] = str(raw.get('lubrication')).strip()
    vals['sf'] = float(raw.get('sf'))
    vendor_id_raw = raw.get('vendor_id')
    if vendor_id_raw is None or str(vendor_id_raw).lower() in ('', 'undefined'):
        vals['vendor_id'] = 1
    else:
        try:
            vals['vendor_id'] = int(vendor_id_raw)
        except (ValueError, TypeError):
            vals['vendor_id'] = 1
    if vals['kw'] <= 0 or vals['rpm'] <= 0 or vals['sf'] <= 0:
        raise ValueError
    if not vals['gr']:
        raise ValueError
    if vals['gear_type'] not in ('any', 'helical', 'bevel_helical'):
        raise ValueError
    if vals['hb'] not in ('YES', 'NO'):
        raise ValueError
    if vals['cooling'].upper() not in ('FAN', 'NATURAL', 'FLS', 'YES', 'NA'):
        raise ValueError
    if vals['lubrication'].upper() not in ('SPLASH', 'FLS', 'MDP', 'LUBE PUMP'):
        raise ValueError
    return vals


@app.post('/api/chat')
async def chat(body: ChatIn):
    session_id = body.session_id
    hist = _get_session(session_id)

    # 1) Form submitted → run selection + explanation
    if body.form is not None:
        try:
            vals = _clean_form(body.form)
            req = engine.select(**vals)
        except (ValueError, TypeError, KeyError) as e:
            print(f"DEBUG: Validation error: {e}")
            return {'reply': ERROR, 'form': FORM, 'results': None, 'session_id': session_id}
        except Exception as exc:
            import traceback
            traceback.print_exc()
            return {'reply': f'Sorry — the catalog lookup failed: {exc}',
                    'form': None, 'results': None, 'session_id': session_id}

        pricing.enrich(req['candidates'])

        reason = await reasoning.explain(
            req, {**vals, 'n1_rpm': engine.nearest_speed(vals['rpm'])})

        LAST_FORM[session_id or ''] = dict(vals)
        if req['candidates']:
            LAST_SELECTION[session_id or ''] = req['candidates'][0]

        reply_text = engine.summarize(req) + _pricing_note(req['candidates'])
        _add_to_history(session_id, 'user', 'form submitted')
        _add_to_history(session_id, 'assistant', reply_text + ('\n' + reason if reason else ''))

        return {'reply': reply_text, 'form': None,
                'results': req['candidates'], 'reason': reason,
                'session_id': session_id}

    # 2) No form → check intent
    msg = body.message or ''

    # Selection intent → show form
    if _looks_like_selection(msg) or 'gearbox' in msg.lower():
        _add_to_history(session_id, 'user', msg)
        _add_to_history(session_id, 'assistant', INTRO)
        # Attach vendors to form dynamically
        form_with_vendors = FORM.copy()
        form_with_vendors['fields'] = FORM['fields'][:]
        form_with_vendors['fields'][0]['options'] = engine.get_vendors()
        return {'reply': INTRO, 'form': form_with_vendors, 'results': None, 'session_id': session_id}

    # Price intent → deterministic weight x steel rate (never via the LLM)
    if _looks_like_price(msg):
        _add_to_history(session_id, 'user', msg)
        answer = _price_reply(msg, session_id)
        _add_to_history(session_id, 'assistant', answer)
        return {'reply': answer, 'form': None, 'results': None,
                'session_id': session_id}

    # Catalog QA intent → answer with Groq + catalog context + history
    if _looks_like_catalog_qa(msg):
        _add_to_history(session_id, 'user', msg)
        # Cross-vendor compare intent with stored requirements → deterministic
        ml = msg.lower()
        compares = any(t in ml for t in ('compare', 'vs', 'versus', 'with elecon',
                                         'with premium'))
        last = LAST_FORM.get(session_id or '')
        if compares and last:
            try:
                rows = engine.compare_vendors(**last)
            except Exception:
                rows = None
            if rows:
                pricing.enrich(rows)
                answer = _format_compare_reply(rows, last)
                _add_to_history(session_id, 'assistant', answer)
                return {'reply': answer, 'form': None, 'results': None,
                        'session_id': session_id}
        # Build conversation context for the LLM
        history_msgs = list(hist)
        answer = await reasoning.catalog_qa(msg, history_msgs)
        if answer:
            _add_to_history(session_id, 'assistant', answer)
            return {'reply': answer, 'form': None, 'results': None, 'session_id': session_id}
        return {'reply': 'Sorry, I couldn\'t retrieve that from the catalog.',
                'form': None, 'results': None, 'session_id': session_id}

    # Unknown intent
    return {'reply': NO_INTENT, 'form': None, 'results': None, 'session_id': session_id}


# --- Vendor Management ---

@app.get('/api/vendors')
async def list_vendors():
    """Return list of available vendors."""
    return engine.get_vendors()


@app.post('/api/vendors/upload')
async def upload_vendor_catalog(
    vendor_code: str = FastAPIForm(...),
    vendor_name: str = FastAPIForm(...),
    vendor_description: str = FastAPIForm(default=''),
    file: UploadFile = File(...)
):
    """Upload a vendor PDF catalog and trigger parsing pipeline."""
    if not file.filename.lower().endswith('.pdf'):
        return JSONResponse({'error': 'Only PDF files are supported'}, status_code=400)
    
    # Save file temporarily
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        # Create or get vendor
        import psycopg
        DB = 'postgresql://gearbox:gearbox@localhost:5433/gearbox'
        with psycopg.connect(DB) as conn:
            vendor_row = conn.execute(
                'SELECT id FROM vendor WHERE code = %s', (vendor_code,)
            ).fetchone()
            if vendor_row:
                vendor_id = vendor_row[0]
                conn.execute(
                    'UPDATE vendor SET name = %s, description = %s WHERE id = %s',
                    (vendor_name, vendor_description, vendor_id)
                )
            else:
                vendor_id = conn.execute(
                    'INSERT INTO vendor (code, name, description) VALUES (%s, %s, %s) RETURNING id',
                    (vendor_code, vendor_name, vendor_description)
                ).fetchone()[0]
        
        # Log import
        with psycopg.connect(DB) as conn:
            conn.execute(
                'INSERT INTO import_log (vendor_id, source_file, status) VALUES (%s, %s, %s)',
                (vendor_id, file.filename, 'pending')
            )
        
        # TODO: Trigger async parsing pipeline here
        # For now, return success with instructions
        return {
            'success': True,
            'vendor_id': vendor_id,
            'vendor_code': vendor_code,
            'message': f'PDF uploaded for {vendor_name}. Parsing pipeline to be implemented.',
            'file_size': len(content)
        }
    finally:
        os.unlink(tmp_path)


@app.post('/api/compare')
async def compare_vendors(body: ChatIn):
    """Multi-vendor comparison for given requirements."""
    try:
        vals = _clean_form(body.form)
    except (ValueError, TypeError, KeyError):
        return JSONResponse({'error': 'Invalid form data'}, status_code=400)
    
    comparison = engine.compare_vendors(**vals)
    quote = pricing.enrich(comparison)
    return {
        'comparison': comparison,
        'price_per_kg_inr': quote['per_kg_inr'],
        'price_source': quote['source'],
        'price_fetched_at': quote['fetched_at'],
        'session_id': body.session_id
    }


# --- Root ---
# This service used to mount a single-file HTML chat UI at '/'. That UI is
# gone: the Next.js app is the product now, and running two front doors over
# the same data meant fixes landing in one and not the other. This service
# keeps what it is actually for -- the deterministic engine, catalogue
# queries, document parsing and the grounded LLM calls -- and the browser is
# sent to the app that presents them.
#
# NEXT_UI_URL exists so a deployment can point at a real hostname instead of
# assuming localhost.
NEXT_UI_URL = os.environ.get('NEXT_UI_URL', 'http://localhost:3000').rstrip('/')


@app.get('/')
async def root():
    """Send browsers to the Next.js app; this service has no UI of its own."""
    return RedirectResponse(url=f'{NEXT_UI_URL}/', status_code=307)


@app.get('/ui-redirect')
async def ui_redirect():
    """Explicit target, so an old bookmark lands somewhere real."""
    return RedirectResponse(url=f'{NEXT_UI_URL}/projects', status_code=307)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000)