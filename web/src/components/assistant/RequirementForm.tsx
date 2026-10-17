"use client";

import * as React from "react";
import { Play, Loader2, Check, X, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { SelectionRequest, SelectionResult } from "@/components/assistant/types";

const GEAR_TYPES = [
  { value: "any", label: "Any" },
  { value: "helical", label: "Helical" },
  { value: "bevel_helical", label: "Bevel-helical" },
] as const;

const MOUNTINGS = [
  { value: "any", label: "Any", hint: "don't filter" },
  { value: "foot", label: "Foot base", hint: "H/B standard" },
  { value: "torque_arm", label: "Torque arm", hint: "K3/K4/S3/S4 only" },
] as const;

/**
 * The requirement form.
 *
 * Kept as discrete inputs rather than free text: these are the numbers an
 * engineer has to defend in a purchase enquiry, so every one of them must be
 * visible, typed and reproducible rather than inferred from a sentence.
 *
 * The form does not talk to the API itself. It hands a validated
 * SelectionRequest to onRun, and the parent owns session handling, so a
 * follow-up question and a selection cannot end up in different
 * conversations.
 */
export function RequirementForm({
  vendors,
  onRun,
  busy,
}: {
  vendors: Array<{ id: number; code: string; name: string }>;
  onRun: (req: SelectionRequest) => void;
  busy?: boolean;
}) {
  const [open, setOpen] = React.useState(true);
  const [pn, setPn] = React.useState("60");
  const [ratio, setRatio] = React.useState("17");
  const [sf, setSf] = React.useState("1.25");
  const [rpm, setRpm] = React.useState("1500");
  const [cooling, setCooling] = React.useState("FAN");
  const [gearType, setGearType] = React.useState<"any" | "helical" | "bevel_helical">("any");
  const [mounting, setMounting] = React.useState<"any" | "foot" | "torque_arm">("any");
  const [vendorId, setVendorId] = React.useState<string>("");
  const [invalid, setInvalid] = React.useState<string | null>(null);

  const numeric = (v: string) => {
    const n = Number(v);
    return Number.isFinite(n) && n > 0 ? n : undefined;
  };

  function run(e: React.FormEvent) {
    e.preventDefault();
    const pnNum = numeric(pn);
    if (!pnNum) {
      setInvalid("Required power (kW) must be a positive number.");
      return;
    }
    setInvalid(null);

    onRun({
      pn: pnNum,
      ratio_req: numeric(ratio) ?? null,
      sf: numeric(sf) ?? 1.0,
      n1_rpm: Number(rpm) || 1500,
      cooling_type: cooling,
      gear_type: gearType,
      mounting_type: mounting,
      vendor_id: vendorId ? Number(vendorId) : null,
    });
  }

  return (
// Bounded height with its own scroll. The form is a fixed strip at the bottom
    // of a panel that already scrolls, so when it expanded past the available
    // space it overflowed the panel and the Hide button became unreachable --
// the one control needed to undo the expansion. Capping it keeps the header
    // (and therefore Hide) permanently on screen.
    <form
      onSubmit={run}
      className="max-h-[min(46vh,420px)] shrink-0 overflow-y-auto overscroll-contain
                 border-t border-hair bg-white/[0.015]"
    >
      {/* Sticky so Hide stays clickable however far the form is scrolled. */}
      <div className="sticky top-0 z-10 flex items-center justify-between bg-white/[0.015]/95 px-4 pb-2 pt-3 backdrop-blur">
        <h3 className="text-[12.5px] font-medium uppercase tracking-[0.07em] text-white/45">
          Requirement
        </h3>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="rounded px-1.5 py-0.5 text-[11.5px] text-white/35 transition-colors
                     hover:bg-white/[0.06] hover:text-white/65"
        >
          {open ? "Hide" : "Show"}
        </button>
      </div>

{open && (
        <div className="px-4 pb-4">
          <div className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            <Field label="Power (kW)" hint="applied">
              <Input value={pn} onChange={(e) => setPn(e.target.value)} inputMode="decimal" />
            </Field>
            <Field label="Ratio iN" hint="reduction">
              <Input value={ratio} onChange={(e) => setRatio(e.target.value)} inputMode="decimal" />
            </Field>
            <Field label="S / F" hint="service factor">
              <Input value={sf} onChange={(e) => setSf(e.target.value)} inputMode="decimal" />
            </Field>
<Field label="n1 (rpm)">
              <Input value={rpm} onChange={(e) => setRpm(e.target.value)} inputMode="numeric" />
            </Field>
            <Field label="Cooling">
              <select
                value={cooling}
                onChange={(e) => setCooling(e.target.value)}
                className="h-9 w-full rounded-lg border border-hair bg-white/[0.03] px-2.5 text-[13px]
                           text-white/85 outline-none focus:border-white/20"
              >
                {["FAN", "FLS", "Natural"].map((c) => (
                  <option key={c} value={c} className="bg-panel">
                    {c}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Vendor">
              <select
                value={vendorId}
                onChange={(e) => setVendorId(e.target.value)}
                className="h-9 w-full rounded-lg border border-hair bg-white/[0.03] px-2.5 text-[13px]
                           text-white/85 outline-none focus:border-white/20"
              >
                <option value="" className="bg-panel">
                  All
                </option>
                {vendors.map((v) => (
                  <option key={v.id} value={v.id} className="bg-panel">
                    {v.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <div className="mt-3">
            <span className="mb-1.5 block text-[11.5px] font-medium text-white/45">
              Mounting arrangement
            </span>
            <div className="flex flex-wrap gap-1.5">
              {MOUNTINGS.map((m) => (
                <button
                  key={m.value}
                  type="button"
                  onClick={() => setMounting(m.value)}
                  title={m.hint}
                  className={cn(
                    "rounded-lg border px-2.5 py-1.5 text-[12px] transition-colors",
                    mounting === m.value
                      ? "border-accent/50 bg-accent/10 text-white/90"
                      : "border-hair text-white/45 hover:border-white/20 hover:text-white/70",
                  )}
                >
                  {m.label}
                </button>
              ))}
            </div>
            {mounting !== "any" && (
              <p className="mt-1.5 text-[11px] leading-relaxed text-white/25">
                Filters to series the catalogue actually publishes in that mounting. Series
                with no recorded mounting are left out and named in the result.
              </p>
            )}
          </div>

          <div className="mt-3">
            <span className="mb-1.5 block text-[11.5px] font-medium text-white/45">Gear type</span>
            <div className="flex gap-1.5">
              {GEAR_TYPES.map((g) => (
                <button
                  key={g.value}
                  type="button"
                  onClick={() => setGearType(g.value)}
                  className={cn(
                    "rounded-lg border px-2.5 py-1.5 text-[12px] transition-colors",
                    gearType === g.value
                      ? "border-accent/50 bg-accent/10 text-white/90"
                      : "border-hair text-white/45 hover:border-white/20 hover:text-white/70",
                  )}
                >
                  {g.label}
                </button>
              ))}
            </div>
          </div>

          {invalid && (
            <p className="mt-3 rounded-lg border border-red-500/25 bg-red-500/10 px-3 py-2 text-[12px] text-red-300">
              {invalid}
            </p>
          )}

          <Button type="submit" variant="primary" size="sm" className="mt-3.5 w-full" disabled={busy}>
            {busy ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Selecting
              </>
            ) : (
              <>
                <Play className="h-3.5 w-3.5" />
                Run selection
              </>
            )}
</Button>
        </div>
      )}
    </form>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11.5px] font-medium text-white/45">
        {label}
        {hint && <span className="ml-1 text-white/20">{hint}</span>}
      </span>
      {children}
    </label>
  );
}

/** Deterministic result card. Rendered above the transcript. */
export function SelectionCard({
  result,
  onAsk,
}: {
  result: SelectionResult & { weight_kg?: number | null; weight_published?: boolean };
  onAsk?: (q: string) => void;
}) {
  return (
    <div className="rounded-2xl border border-hair bg-panel/70 p-4 shadow-card">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <span className="text-[11px] uppercase tracking-[0.08em] text-white/35">Selected</span>
          <div className="mt-0.5 text-[19px] font-semibold tracking-[-0.02em] text-white">
            {result.model}
          </div>
        </div>
        <Badge ok={result.power_ok} label={result.power_ok ? "meets PN" : "below PN"} />
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2.5 sm:grid-cols-4">
        <Stat label="Rated power" value={`${result.power_kw} kW`} />
        <Stat label="Required PN" value={`${result.required_kw} kW`} />
        <Stat label="Ratio" value={`iN ${result.ratio_iN}`} />
        <Stat label="Output" value={`${result.n2_actual} rpm`} />
        <Stat
          label="Thermal (derated)"
          value={result.thermal_kw_effective != null ? `${result.thermal_kw_effective} kW` : "not published"}
        />
        <Stat
          label="Net weight"
          value={
            result.weight_kg != null
              ? `${result.weight_published ? "" : "~"}${result.weight_kg} kg`
              : "n/a"
          }
          muted={result.weight_published === false}
        />
        <Stat label="Cooling" value={result.cooling_type ?? "-"} />
        <Stat
          label="Mounting"
          value={
            result.mounting_type && result.mounting_type !== "any"
              ? result.mounting_type.replace("_", " ")
              : (result.mountings_offered?.join(", ") ?? "-")
          }
        />
        <Stat label="Forced lube" value={result.forced_lube ? "required" : "no"} />
        <Stat
          label="Est. steel cost"
          value={
            result.est_price_inr != null
              ? `₹${Math.round(result.est_price_inr).toLocaleString("en-IN")}`
              : "n/a"
          }
          muted={result.weight_published === false}
        />
      </dl>

      {result.est_price_inr != null && (
        <p className="mt-2.5 text-[11px] leading-relaxed text-white/35">
          Net weight × live steel rate = steel content only, not a price quote.
          {result.weight_published === false &&
            " Weight is estimated, so this figure is indicative."}
        </p>
      )}

      {result.warnings.length > 0 && (
        <ul className="mt-4 space-y-1.5 border-t border-hair pt-3">
          {result.warnings.map((w, i) => (
            <li key={i} className="flex items-start gap-2 text-[12px] leading-relaxed text-amber-200/70">
              <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" />
              {w}
            </li>
          ))}
        </ul>
      )}

      {onAsk && (
        <div className="mt-4 flex flex-wrap gap-2 border-t border-hair pt-3">
          {["Why this model?", "What is the thermal margin?", "What are the alternatives?"].map(
            (q) => (
              <button
                key={q}
                type="button"
                onClick={() => onAsk(q)}
                className="rounded-full border border-hair px-3 py-1 text-[11.5px] text-white/50
                           transition-colors hover:border-white/20 hover:text-white/80"
              >
                {q}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-[0.06em] text-white/30">{label}</dt>
      <dd className={cn("mt-0.5 text-[13px] tabular-nums", muted ? "text-white/45" : "text-white/85")}>
        {value}
      </dd>
    </div>
  );
}

function Badge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11.5px]",
        ok
          ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-300/90"
          : "border-amber-400/25 bg-amber-400/10 text-amber-300/90",
      )}
    >
      {ok ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
      {label}
    </span>
  );
}
