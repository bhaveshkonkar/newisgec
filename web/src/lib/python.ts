/**
 * Server-side bridge to the private Python service.
 *
 * Everything here is server-only. The browser never learns the Python
 * origin, and no request is made on its behalf with a caller-supplied
 * project id -- the Python side receives already-authorised data.
 */

const PYTHON_ORIGIN =
  process.env.PYTHON_API_URL?.replace(/\/+$/, "") ?? "http://127.0.0.1:8000";

/** Shared secret so a stray local process cannot drive the engine. */
const PYTHON_TOKEN = process.env.PYTHON_INTERNAL_TOKEN ?? "";

export type PythonResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; error: string };

async function call<T>(
  path: string,
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<PythonResult<T>> {
  const { timeoutMs = 120_000, ...rest } = init;
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), timeoutMs);

  try {
    const res = await fetch(`${PYTHON_ORIGIN}${path}`, {
      ...rest,
      signal: ac.signal,
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...(PYTHON_TOKEN ? { "X-Internal-Token": PYTHON_TOKEN } : {}),
        ...(rest.headers ?? {}),
      },
    });

    const text = await res.text();
    let body: unknown = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      return {
        ok: false,
        status: res.status,
        error: `Python returned non-JSON: ${text.slice(0, 200)}`,
      };
    }

    if (!res.ok) {
      const detail =
        (body as { detail?: string; error?: string })?.detail ??
        (body as { error?: string })?.error ??
        `Python ${res.status}`;
      return { ok: false, status: res.status, error: detail };
    }
    return { ok: true, data: body as T };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return {
      ok: false,
      status: 503,
      error:
        msg === "This operation was aborted"
          ? `Python service timed out after ${Math.round(timeoutMs / 1000)}s`
          : `Python service unreachable: ${msg}`,
    };
  } finally {
    clearTimeout(timer);
  }
}

//---------------------------------------------------------------- selections

export type SelectRequest = {
  pn: number;
  ratio_req?: number | null;
  /** numeric service factor; the legacy engine takes "1.5" as a string but
   *  the internal API takes a float */
  sf?: number;
  n1_rpm?: number;
  cooling_type?: string;
  gear_type?: "any" | "helical" | "bevel_helical";
  hb?: string | null;
  mounting_type?: string | null;
  series?: string | null;
  vendor_id?: number | null;
};

/** Mirrors the dicts built in app/internal_api.py::gearbox_select. */
export type SelectionResult = {
  model: string;
  vendor_id: number;
  vendor_code: string;
  series: string;
  size: string;
  gear_type: string;
  power_kw: number;
  power_ok: boolean;
  required_kw: number;
  ratio_req: number | null;
  ratio_iN: string | number;
  ratio_dev: number;
  n1_rpm: number;
  n2_actual: number;
  cooling_type: string;
  forced_lube: boolean;
  /** the mounting that was asked for and confirmed for this series */
  mounting_type: string;
  /** every mounting the catalogue records for this series, e.g. ['foot','torque_arm'] */
  mountings_offered: string[];
  thermal_kw: number | null;
  thermal_kw_effective: number | null;
  thermal_ok: boolean;
  weight_kg: number | null;
  /** false => weight_kg is an estimate, never a catalogue figure */
  weight_published: boolean;
  weight_basis: string | null;
  /** weight_kg x the INR/kg steel rate. Steel content only, not a quote.
   *  null when no rate is configured or weight is unknown. */
  est_price_inr: number | null;
  warnings: string[];
};

/** Steel rate provenance, returned once per selection request. */
export type PriceQuote = {
  price_per_kg_inr: number | null;
  price_source: "metalcharts" | "manual" | null;
  price_fetched_at: string | null;
  price_note: string | null;
};

export function pythonSelect(body: SelectRequest) {
  return call<{ results: SelectionResult[] } & Partial<PriceQuote>>(
    "/api/gearbox/select",
    {
      method: "POST",
      body: JSON.stringify(body),
    }
  );
}

//---------------------------------------------------------------- explanation

export type ExplainRequest = {
  /** the deterministic outcome -- the LLM may not contradict this */
  selection: SelectionResult | null;
  question: string;
  /** Documents the server has already authorised for this project. Only ids
   *  are sent; the Python side loads their page text directly from the DB.
   *  This avoids a 400-page RFQ blowing the token budget before the turn starts. */
  documents: Array<{ document_id: string; file_name: string; page_count: number | null }>;
  /** `system` entries carry imported-conversation context (see the import route). */
  history?: Array<{ role: "user" | "assistant" | "system"; content: string }>;
};

export function pythonExplain(body: ExplainRequest, timeoutMs = 180_000) {
  // degraded: true means the LLM could not be reached and the answer was built
  // from the catalogue rows directly. The UI shows that honestly rather than
  // presenting raw data as if the model had written it.
  return call<{ answer: string; citations: Array<{ document_id: string; file_name: string; page_no: number | null }>; degraded?: boolean; reason?: string }>(
    "/api/gearbox/explain",
    {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs,
    },
  );
}

//---------------------------------------------------------------- pdf parsing

export type ParseResponse = {
  page_count: number | null;
  text: string;
  /**
   * Per-page text, 1-based, so page_no lines up with the page the reader sees
   * in the viewer. Present as of parser docparse-3; older builds omit it.
   */
  pages?: Array<{ page_no: number; text: string }>;
  metadata: Record<string, unknown>;
  parser_version: string;
};

export function pythonParsePdf(projectId: string, storagePath: string, fileName: string) {
  return call<ParseResponse>("/api/pdf/parse", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, storage_path: storagePath, file_name: fileName }),
    timeoutMs: 180_000,
  });
}

/** Fetches raw bytes rather than JSON, so image responses survive the bridge. */
async function callBinary(
  path: string,
  body: unknown,
  timeoutMs = 60_000,
): Promise<{ ok: true; data: ArrayBuffer } | { ok: false; status: number; error: string }> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), timeoutMs);

  try {
    const res = await fetch(`${PYTHON_ORIGIN}${path}`, {
      method: "POST",
      signal: ac.signal,
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...(PYTHON_TOKEN ? { "X-Internal-Token": PYTHON_TOKEN } : {}),
      },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const text = await res.text();
      let detail = `Python ${res.status}`;
      try {
        const parsed = JSON.parse(text) as { detail?: string; error?: string };
        detail = parsed.detail ?? parsed.error ?? detail;
      } catch {
        // Non-JSON error body; the status line is all we can report.
      }
      return { ok: false, status: res.status, error: detail };
    }

    return { ok: true, data: await res.arrayBuffer() };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return {
      ok: false,
      status: 503,
      error:
        msg === "This operation was aborted"
          ? `Python service timed out after ${Math.round(timeoutMs / 1000)}s`
          : `Python service unreachable: ${msg}`,
    };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Rasterises a single page to PNG.
 *
 * Privacy browsers block the PDF plugin that an iframe viewer depends on, so
 * the page is rendered server-side and shipped as an image instead. Same
 * project id and storage path the parse call used, so the containment rule on
 * the Python side applies unchanged.
 */
export function pythonRenderPdfPage(
  projectId: string,
  storagePath: string,
  pageNo: number,
  opts: { targetWidth?: number; dpi?: number } = {},
) {
  return callBinary(
    "/api/pdf/render",
    {
      project_id: projectId,
      storage_path: storagePath,
      page_no: pageNo,
      // targetWidth derives the DPI from the page's physical size so the raster
      // matches real screen pixels; the browser then lays it out 1:1 instead of
      // upscaling a soft low-DPI image.
      ...(opts.targetWidth ? { target_width: opts.targetWidth } : { dpi: opts.dpi ?? 220 }),
    },
    60_000,
  );
}

//---------------------------------------------------------------- health

export function pythonHealth() {
  return call<{ ok: boolean; version?: string }>("/health", { timeoutMs: 4_000 });
}

export { PYTHON_ORIGIN };