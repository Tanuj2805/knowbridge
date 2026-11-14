"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import type { Sensitivity } from "@/lib/types";

export async function buildSmartSearch(projectId: string): Promise<string | undefined> {
  try {
    await api(`/projects/${projectId}/evidence/reindex`, { method: "POST" });
  } catch (e) {
    return e instanceof ApiError ? e.message : "Couldn't start indexing.";
  }
  revalidatePath(`/projects/${projectId}`);
}

export async function relabelEvidence(
  projectId: string,
  evidenceId: string,
  sensitivity: Sensitivity,
): Promise<string | undefined> {
  try {
    await api(`/projects/${projectId}/evidence/${evidenceId}`, { method: "PATCH", json: { sensitivity } });
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      // Relabelled beyond the admin's own clearance: it's now hidden from them.
      redirect(`/projects/${projectId}/evidence?relabelled=1`);
    }
    return e instanceof ApiError ? e.message : "Couldn't change the label.";
  }
  revalidatePath(`/projects/${projectId}/evidence/${evidenceId}`);
}

/** Demo mode: rewrite an item as if it had changed in its tool, so drift detection runs on it. */
export async function simulateChange(
  projectId: string,
  evidenceId: string,
  text: string,
): Promise<{ error?: string; claims?: number }> {
  try {
    const r = await api<{ claims: number }>(`/projects/${projectId}/evidence/${evidenceId}/simulate-change`, {
      method: "POST",
      json: { text },
    });
    revalidatePath(`/projects/${projectId}/evidence/${evidenceId}`);
    revalidatePath(`/projects/${projectId}/ledger`);
    revalidatePath(`/projects/${projectId}/sources`);
    return { claims: r.claims };
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Couldn't make the change." };
  }
}
