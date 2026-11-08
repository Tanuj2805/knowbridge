"use server";

import { revalidatePath } from "next/cache";
import { ApiError, api } from "@/lib/api";
import type { Source } from "@/lib/types";

export type FormState = { error?: string; ok?: string } | undefined;

export async function connectSource(projectId: string, _: FormState, form: FormData): Promise<FormState> {
  const body = new FormData();
  for (const key of [
    "kind", "name", "default_sensitivity", "repo", "scope_from", "scope_to",
    "jira_site", "jira_email", "jira_token", "jql", "github_token", "meeting_date",
  ]) {
    const v = form.get(key);
    if (typeof v === "string" && v.trim()) body.append(key, v.trim());
  }
  if (form.get("audience") === "some") {
    const readers = form.getAll("readers").map(String);
    if (readers.length === 0) return { error: "Pick at least one person who can see this source." };
    readers.forEach((r) => body.append("readers", r));
  }
  for (const f of form.getAll("files")) {
    if (f instanceof File && f.size > 0) body.append("files", f, f.name);
  }
  try {
    const s = await api<Source>(`/projects/${projectId}/sources`, { method: "POST", body });
    revalidatePath(`/projects/${projectId}/sources`);
    return { ok: `Connected ${s.name}. Reading it now…` };
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Couldn't connect that source." };
  }
}

export async function updateConnection(
  projectId: string,
  sourceId: string,
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const token = String(form.get("token") ?? "").trim();
  const jql = String(form.get("jql") ?? "").trim();
  if (!token && !jql) return { error: "Enter a new token or a new filter." };
  try {
    await api(`/projects/${projectId}/sources/${sourceId}`, {
      method: "PATCH",
      json: { ...(token ? { token } : {}), ...(jql ? { jql } : {}) },
    });
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Couldn't update the connection." };
  }
  revalidatePath(`/projects/${projectId}/sources`);
  return { ok: "Saved. Syncing again with the new settings…" };
}

export async function syncSource(projectId: string, sourceId: string, full = false): Promise<string | undefined> {
  try {
    await api(`/projects/${projectId}/sources/${sourceId}/sync${full ? "?full=true" : ""}`, { method: "POST" });
  } catch (e) {
    return e instanceof ApiError ? e.message : "Couldn't start the sync.";
  }
  revalidatePath(`/projects/${projectId}/sources`);
}

export async function removeSource(projectId: string, sourceId: string): Promise<void> {
  await api(`/projects/${projectId}/sources/${sourceId}`, { method: "DELETE" });
  revalidatePath(`/projects/${projectId}/sources`);
}
