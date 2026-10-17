/**
 * The six project modules.
 *
 * All six rows are created with a project (schema enforces the UNIQUE), so
 * adding Motor/Pump later is a UI change, not a migration. `href` is what
 * distinguishes "built" from "coming soon" -- a module without an href is
 * rendered disabled.
 */

export const MODULE_TYPES = [
  "gearbox",
  "motor",
  "pump",
  "mechanical_equipment",
  "rfq_analysis",
  "general_chat",
] as const;

export type ModuleType = (typeof MODULE_TYPES)[number];

export type ModuleDef = {
  type: ModuleType;
  label: string;
  description: string;
  /** path segment under /projects/[projectId] */
  segment: string;
  icon: "gearbox" | "motor" | "pump" | "mechanical" | "rfq" | "chat";
  live: boolean;
};

export const MODULES: ModuleDef[] = [
  {
    type: "gearbox",
    label: "Gearbox",
    description: "Selection, comparison and technical details",
    segment: "gearbox",
    icon: "gearbox",
    live: true,
  },
  {
    type: "motor",
    label: "Motor",
    description: "Sizing and compatibility check",
    segment: "motor",
    icon: "motor",
    live: false,
  },
  {
    type: "pump",
    label: "Pump",
    description: "Centrifugal and industrial pump selection",
    segment: "pump",
    icon: "pump",
    live: false,
  },
  {
    type: "mechanical_equipment",
    label: "Mechanical Equipment",
    description: "General mechanical equipment support",
    segment: "mechanical",
    icon: "mechanical",
    live: false,
  },
  {
    type: "rfq_analysis",
    label: "RFQ Analysis",
    description: "Parse and analyze RFQs",
    segment: "rfq",
    icon: "rfq",
    live: false,
  },
  {
    type: "general_chat",
    label: "General Chat",
    description: "Ask technical questions about this project",
    segment: "chat",
    icon: "chat",
    live: false,
  },
];

export function moduleByType(type: string): ModuleDef | undefined {
  return MODULES.find((m) => m.type === type);
}

export function isModuleType(v: string): v is ModuleType {
  return (MODULE_TYPES as readonly string[]).includes(v);
}