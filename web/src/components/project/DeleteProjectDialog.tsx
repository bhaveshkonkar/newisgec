"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * Delete is destructive and unrecoverable (documents and chats go with it,
 * and the on-disk folder is swept), so it asks for the project name.
 */
export function DeleteProjectDialog({
  projectId,
  projectName,
  open,
  onOpenChange,
}: {
  projectId: string;
  projectName: string;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const router = useRouter();
  const [typed, setTyped] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setTyped("");
      setError(null);
    }
  }, [open]);

  const matches = typed.trim() === projectName;

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/projects/${projectId}`, { method: "DELETE" });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.error ?? "Delete failed");
      onOpenChange(false);
      router.push("/projects");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Trash2 className="h-4 w-4 text-red-400" strokeWidth={1.8} />
            Delete project
          </DialogTitle>
          <DialogDescription>
            This removes <strong className="text-white/80">{projectName}</strong> along with every
            document and chat message inside it. It cannot be undone.
          </DialogDescription>
        </DialogHeader>

        <div>
          <label
            htmlFor="confirm-name"
            className="mb-1.5 block text-[12.5px] font-medium text-white/60"
          >
            Type <span className="text-white/85">{projectName}</span> to confirm
          </label>
          <Input
            id="confirm-name"
            autoFocus
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={projectName}
            onKeyDown={(e) => {
              if (e.key === "Enter" && matches && !busy) void run();
            }}
          />
        </div>

        {error && (
          <p className="rounded-lg border border-red-500/25 bg-red-500/10 px-3 py-2 text-[12.5px] text-red-300">
            {error}
          </p>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="danger" onClick={() => void run()} disabled={!matches || busy}>
            {busy ? "Deleting…" : "Delete project"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}