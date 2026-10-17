"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input, Textarea, Label, DateInput } from "@/components/ui/input";

/**
 * Minimal by design: three fields, two buttons. On success the router
 * navigates to the new project so the Hub opens directly (TEST 1).
 */
export function CreateProjectModal({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const router = useRouter();
  const [name, setName] = React.useState("");
  const [date, setDate] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setName("");
      setDate("");
      setDescription("");
      setError(null);
    }
  }, [open]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Project name is required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, project_date: date, description }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.error ?? "Could not create project");
      onOpenChange(false);
      router.push(`/projects/${json.project.id}`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create project");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New project</DialogTitle>
          <DialogDescription>
            A project keeps its documents and engineering workspaces separate.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <Label htmlFor="p-name">Project name</Label>
            <Input
              id="p-name"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="ADANI MAHAN"
              maxLength={120}
            />
          </div>

          <div>
            <Label htmlFor="p-date">Project date</Label>
            {/* native date input; the browser renders dd/mm/yyyy for en-GB */}
            <DateInput id="p-date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>

          <div>
            <Label htmlFor="p-desc">
              Description <span className="normal-case tracking-normal text-white/25">(optional)</span>
            </Label>
            <Textarea
              id="p-desc"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Adani Mahan project engineering requirements"
              maxLength={2000}
            />
          </div>

          {error && (
            <p className="rounded-lg border border-red-500/25 bg-red-500/10 px-3 py-2 text-[12.5px] text-red-300">
              {error}
            </p>
          )}

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={busy || !name.trim()}>
              {busy ? "Creating…" : "Create project"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}