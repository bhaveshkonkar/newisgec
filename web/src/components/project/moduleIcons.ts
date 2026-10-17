import type { LucideIcon } from "lucide-react";
import { Cog, Zap, Droplets, Wrench, FileSearch, MessagesSquare } from "lucide-react";

/**
 * Icon registry kept out of modules.ts so that file stays a plain data
 * module (it is imported by route handlers, which must not pull lucide
 * into server bundles).
 */
const ICONS: Record<string, LucideIcon> = {
  gearbox: Cog,
  motor: Zap,
  pump: Droplets,
  mechanical: Wrench,
  rfq: FileSearch,
  chat: MessagesSquare,
};

export function moduleIcon(key: string): LucideIcon {
  return ICONS[key] ?? Wrench;
}