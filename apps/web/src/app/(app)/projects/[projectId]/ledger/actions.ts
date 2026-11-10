"use server";

import { revalidatePath } from "next/cache";
import { ApiError, api } from "@/lib/api";
import type { Run } from "@/lib/types";

/** Starts a "build claims" run. Returns an error message, or nothing on success. */
export async function startRun(projectId: string): Promise<string | undefined> {
  try {
    await api<Run>(`/projects/${projectId}/runs`, { method: "POST" });
  } catch (e) {
    return e instanceof ApiError ? e.message : "Couldn't start the run.";
  }
  revalidatePath(`/projects/${projectId}/ledger`);
}

export type ReviewInput = {
  action: "approve" | "edit" | "reject" | "reopen";
  statement?: string;
  rationale?: string;
  owner_name?: string;
  due_date?: string | null;
  note?: string;
};

/** Approve, edit, reject or reopen one claim. Returns an error message, or nothing on success. */
export async function reviewClaim(projectId: string, claimId: string, input: ReviewInput): Promise<string | undefined> {
  try {
    await api(`/projects/${projectId}/claims/${claimId}`, { method: "PATCH", json: input });
  } catch (e) {
    return e instanceof ApiError ? e.message : "Couldn't save that.";
  }
  revalidatePath(`/projects/${projectId}/ledger`);
}

/** Approves every draft with one of these grades. Returns a message for the person. */
export async function approveByGrade(projectId: string, grades: string[]): Promise<string> {
  try {
    const r = await api<{ approved: number }>(`/projects/${projectId}/claims/review`, {
      method: "POST",
      json: { grades },
    });
    revalidatePath(`/projects/${projectId}/ledger`);
    return r.approved ? `Approved ${r.approved}.` : "Nothing left to approve there.";
  } catch (e) {
    return e instanceof ApiError ? e.message : "Couldn't approve them.";
  }
}

/** Approves every claim still waiting for review. Returns a message for the person. */
export async function approveAll(projectId: string): Promise<string> {
  try {
    const r = await api<{ approved: number }>(`/projects/${projectId}/claims/review`, {
      method: "POST",
      json: { all: true },
    });
    revalidatePath(`/projects/${projectId}/ledger`);
    return r.approved ? `Approved ${r.approved}.` : "Nothing was waiting for review.";
  } catch (e) {
    return e instanceof ApiError ? e.message : "Couldn't approve them.";
  }
}
