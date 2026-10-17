/**
 * Shared types for the assistant surface.
 *
 * These live here rather than in GearboxAssistant.tsx because the three
 * assistant components reference each other: GearboxAssistant renders ChatLog
 * and RequirementForm, and both need these shapes. Declaring them in the
 * parent would make every one of those imports circular.
 */

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
  mounting_type: string;
  mountings_offered: string[];
  thermal_kw: number | null;
  thermal_kw_effective: number | null;
  thermal_ok: boolean;
  weight_kg: number | null;
  weight_published: boolean;
  weight_basis: string | null;
  /** weight_kg x the INR/kg steel rate; null if no rate or no weight. */
  est_price_inr: number | null;
  warnings: string[];
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
  /** Project this message belongs to -- needed for source-link URLs. */
  projectId?: string;
};

export type AssistantMeta = {
  degraded?: boolean;
  reason?: string;
  selection?: SelectionResult;
  shortlist?: SelectionResult[];
  citations?: Array<{ document_id: string; file_name: string; page_no: number | null }>;
};

export type ModuleDoc = {
  id: string;
  file_name: string;
  status: string;
  error_detail: string | null;
  page_count: number | null;
};

export type SelectionRequest = {
  pn: number;
  ratio_req?: number | null;
  sf?: number;
  n1_rpm?: number;
  cooling_type?: string;
  gear_type?: "any" | "helical" | "bevel_helical";
  /**
   * "foot" | "torque_arm" | "any". Only filter on a value the catalogue
   * actually records; "any" is the safe default because a filter we cannot
   * satisfy hides real gearboxes.
   */
  mounting_type?: "any" | "foot" | "torque_arm";
  series?: string | null;
  vendor_id?: number | null;
};

export type SessionSummary = {
  id: string;
  title: string;
  updated_at: string;
};

/** A conversation picked from the `/` palette to import as lasting context. */
export type ImportTarget = {
  projectId: string;
  projectName: string;
  sessionId: string;
  sessionTitle: string;
};