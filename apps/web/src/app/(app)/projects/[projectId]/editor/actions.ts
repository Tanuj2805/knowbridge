"use server";

import { revalidatePath } from "next/cache";
import { ApiError, api } from "@/lib/api";
import type { NewApiToken } from "@/lib/types";

export type TokenState = { error?: string; token?: NewApiToken } | undefined;

export async function createToken(projectId: string, _: TokenState, form: FormData): Promise<TokenState> {
  const name = String(form.get("name") ?? "").trim();
  if (!name) return { error: "Give the token a name, like “VS Code on my laptop”." };
  try {
    const token = await api<NewApiToken>("/me/tokens", { method: "POST", json: { name, project_id: projectId } });
    revalidatePath(`/projects/${projectId}/editor`);
    return { token };
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Couldn't make the token." };
  }
}

export async function revokeToken(projectId: string, tokenId: string): Promise<string | undefined> {
  try {
    await api(`/me/tokens/${tokenId}`, { method: "DELETE" });
  } catch (e) {
    return e instanceof ApiError ? e.message : "Couldn't revoke the token.";
  }
  revalidatePath(`/projects/${projectId}/editor`);
}
