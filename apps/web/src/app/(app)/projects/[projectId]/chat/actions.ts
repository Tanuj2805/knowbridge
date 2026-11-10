"use server";

import { revalidatePath } from "next/cache";
import { ApiError, api } from "@/lib/api";
import type { AskResult, ChatTurn } from "@/lib/types";

/** One chat turn: the question plus the conversation so far. */
export async function askProject(
  projectId: string,
  question: string,
  history: ChatTurn[],
): Promise<{ ok: true; result: AskResult } | { ok: false; error: string }> {
  try {
    const result = await api<AskResult>(`/projects/${projectId}/rag/ask`, {
      method: "POST",
      json: { question, history: history.slice(-12) },
    });
    return { ok: true, result };
  } catch (e) {
    return { ok: false, error: e instanceof ApiError ? e.message : "Couldn't reach the assistant. Try again." };
  }
}

/** Re-index the project: source items and claims that don't have vectors yet. */
export async function rebuildIndex(projectId: string): Promise<string | undefined> {
  try {
    await api(`/projects/${projectId}/rag/index`, { method: "POST" });
  } catch (e) {
    return e instanceof ApiError ? e.message : "Couldn't start indexing.";
  }
  revalidatePath(`/projects/${projectId}/chat`);
}
