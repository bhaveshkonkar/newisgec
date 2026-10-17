import { NextResponse } from "next/server";
import { z } from "zod";
import { getCurrentUser, AuthError } from "@/lib/auth";
import { listProjects, createProject } from "@/lib/repos/projects";

export const dynamic = "force-dynamic";

const CreateProject = z.object({
  name: z.string().trim().min(1, "Project name is required").max(120),
  // <input type="date"> posts yyyy-mm-dd; empty string means "not set"
  project_date: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/, "Date must be yyyy-mm-dd")
    .or(z.literal(""))
    .optional()
    .transform((v) => (v ? v : null)),
  description: z.string().trim().max(2000).optional().or(z.literal("")),
});

export async function GET(req: Request) {
  try {
    const user = await getCurrentUser();
    const url = new URL(req.url);
    const search = url.searchParams.get("q") ?? undefined;
    const recent = url.searchParams.get("recent") !== "all";
    const projects = await listProjects(user.id, { search, recent });
    return NextResponse.json({ projects });
  } catch (err) {
    const status = err instanceof AuthError ? err.status : 500;
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to list projects" },
      { status },
    );
  }
}

export async function POST(req: Request) {
  try {
    const user = await getCurrentUser();
    const body = await req.json().catch(() => ({}));

    const parsed = CreateProject.safeParse(body);
    if (!parsed.success) {
      return NextResponse.json(
        { error: parsed.error.issues[0]?.message ?? "Invalid input" },
        { status: 400 },
      );
    }

    const project = await createProject(user.id, {
      name: parsed.data.name,
      project_date: parsed.data.project_date ?? null,
      description: parsed.data.description ?? null,
    });
    return NextResponse.json({ project }, { status: 201 });
  } catch (err) {
    const status = err instanceof AuthError ? err.status : 500;
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to create project" },
      { status },
    );
  }
}