"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import type { Handover } from "@/lib/types";

/** Starts (or reopens) a knowledge capture for one area; opens it. Returns an error message on failure. */
export async function startCapture(projectId: string, area: string): Promise<string | undefined> {
  let capture: Handover;
  try {
    capture = await api<Handover>(`/projects/${projectId}/radar/capture`, { method: "POST", json: { area } });
  } catch (e) {
    return e instanceof ApiError ? e.message : "Couldn't start the knowledge capture.";
  }
  revalidatePath(`/projects/${projectId}/radar`);
  redirect(`/projects/${projectId}/handovers/${capture.id}`);
}

/** Groups the latest claims into areas again. Returns an error message on failure. */
export async function regroupAreas(projectId: string): Promise<string | undefined> {
  try {
    await api(`/projects/${projectId}/radar/regroup`, { method: "POST" });
  } catch (e) {
    return e instanceof ApiError ? e.message : "Couldn't regroup the areas.";
  }
  revalidatePath(`/projects/${projectId}/radar`);
}
