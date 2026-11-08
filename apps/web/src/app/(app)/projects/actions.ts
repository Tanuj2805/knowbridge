"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import type { Member, ProjectSummary, Role } from "@/lib/types";

export type FormState = { error?: string; ok?: string } | undefined;

export async function createProject(_: FormState, form: FormData): Promise<FormState> {
  let project: ProjectSummary;
  try {
    project = await api<ProjectSummary>("/projects", {
      method: "POST",
      json: {
        name: String(form.get("name") ?? ""),
        description: String(form.get("description") ?? ""),
      },
    });
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Couldn't create the project." };
  }
  redirect(`/projects/${project.id}`);
}

export async function loadDemo(): Promise<FormState> {
  let project: { id: string };
  try {
    project = await api<{ id: string }>("/demo/nimbus", { method: "POST" });
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Couldn't load the demo." };
  }
  redirect(`/projects/${project.id}/sources`);
}

export async function upsertMember(projectId: string, _: FormState, form: FormData): Promise<FormState> {
  const roles = form.getAll("roles").map(String) as Role[];
  if (roles.length === 0) return { error: "Pick at least one role." };
  try {
    const m = await api<Member>(`/projects/${projectId}/members`, {
      method: "PUT",
      json: {
        email: String(form.get("email") ?? ""),
        name: String(form.get("name") ?? "") || null,
        roles,
        role_template: String(form.get("role_template") ?? "") || null,
        clearances: form.getAll("clearances").map(String),
      },
    });
    revalidatePath(`/projects/${projectId}/members`);
    return { ok: `Saved ${m.user.name}.` };
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Couldn't save that member." };
  }
}

export async function removeMember(projectId: string, userId: string): Promise<void> {
  await api(`/projects/${projectId}/members/${userId}`, { method: "DELETE" });
  revalidatePath(`/projects/${projectId}/members`);
}
