"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import type { Handover } from "@/lib/types";

export type FormState = { error?: string } | undefined;

const message = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

export async function createHandover(projectId: string, _: FormState, form: FormData): Promise<FormState> {
  const body = {
    leaver_id: form.get("leaver_id"),
    successor_id: form.get("successor_id"),
    approver_id: form.get("approver_id"),
    leaver_last_day: form.get("leaver_last_day") || null,
    title: form.get("title") || "",
  };
  let created: Handover;
  try {
    created = await api<Handover>(`/projects/${projectId}/handovers`, { method: "POST", json: body });
  } catch (e) {
    return { error: message(e, "Couldn't start the handover.") };
  }
  revalidatePath(`/projects/${projectId}/handovers`);
  redirect(`/projects/${projectId}/handovers/${created.id}`);
}

/** Starts the Gap Interview. Returns an error message, or nothing on success. */
export async function startInterview(projectId: string, handoverId: string): Promise<string | undefined> {
  try {
    await api(`/projects/${projectId}/handovers/${handoverId}/interview`, { method: "POST" });
  } catch (e) {
    return message(e, "Couldn't start the interview.");
  }
  revalidatePath(`/projects/${projectId}/handovers/${handoverId}`);
}

export async function answerQuestion(
  projectId: string,
  handoverId: string,
  questionId: string,
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const action = String(form.get("intent") ?? "answer");
  try {
    await api(`/projects/${projectId}/handovers/${handoverId}/questions/${questionId}`, {
      method: "POST",
      json: {
        action,
        answer: String(form.get("answer") ?? ""),
        assignee_id: action === "reassign" ? form.get("assignee_id") || null : null,
      },
    });
  } catch (e) {
    return { error: message(e, "Couldn't save that.") };
  }
  revalidatePath(`/projects/${projectId}/handovers/${handoverId}`, "layout");
}

// --- the Handover Pack -------------------------------------------------------------

async function call(path: string, init: Parameters<typeof api>[1], fallback: string): Promise<string | undefined> {
  try {
    await api(path, init);
  } catch (e) {
    return message(e, fallback);
  }
}

export async function composePack(projectId: string, handoverId: string): Promise<string | undefined> {
  const err = await call(`/projects/${projectId}/handovers/${handoverId}/compose`, { method: "POST" },
    "Couldn't start writing the pack.");
  revalidatePath(`/projects/${projectId}/handovers/${handoverId}`, "layout");
  return err;
}

export async function publishPack(projectId: string, handoverId: string): Promise<string | undefined> {
  const err = await call(`/projects/${projectId}/handovers/${handoverId}/publish`, { method: "POST" },
    "Couldn't publish the pack.");
  revalidatePath(`/projects/${projectId}/handovers/${handoverId}`, "layout");
  return err;
}

export async function acknowledgeSection(projectId: string, handoverId: string, sectionId: string) {
  const err = await call(`/projects/${projectId}/handovers/${handoverId}/pack/sections/${sectionId}/acknowledge`,
    { method: "POST" }, "Couldn't save that.");
  revalidatePath(`/projects/${projectId}/handovers/${handoverId}`, "layout");
  return err;
}

export async function markPlanItem(projectId: string, handoverId: string, itemId: string, done: boolean) {
  const err = await call(`/projects/${projectId}/handovers/${handoverId}/pack/plan/${itemId}`,
    { method: "POST", json: { done } }, "Couldn't save that.");
  revalidatePath(`/projects/${projectId}/handovers/${handoverId}/pack`);
  return err;
}

export async function flagClaim(projectId: string, handoverId: string, claimId: string, note: string) {
  const err = await call(`/projects/${projectId}/handovers/${handoverId}/flags`,
    { method: "POST", json: { claim_id: claimId, note } }, "Couldn't send that.");
  revalidatePath(`/projects/${projectId}/handovers/${handoverId}`, "layout");
  return err;
}
