import "server-only";
import { SignJWT } from "jose";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export type AccountResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; code: string; message: string };

/** A one-minute token that says "this is the website" to the API's account routes. */
async function siteToken(): Promise<string> {
  return new SignJWT({})
    .setProtectedHeader({ alg: "HS256" })
    .setSubject("web")
    .setIssuer("knowbridge-web")
    .setAudience("knowbridge-accounts")
    .setIssuedAt()
    .setExpirationTime("1m")
    .sign(new TextEncoder().encode(process.env.API_JWT_SECRET));
}

/** Calls the API's email-and-password routes. Never throws: a failure comes back as a code. */
export async function accountsApi<T>(path: string, body?: unknown): Promise<AccountResult<T>> {
  try {
    const res = await fetch(`${API_URL}${path}`, {
      method: body === undefined ? "GET" : "POST",
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${await siteToken()}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const json = await res.json().catch(() => null);
    if (res.ok) return { ok: true, data: json as T };
    const detail = json?.detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      return { ok: false, status: res.status, code: String(detail.code ?? "error"), message: String(detail.message ?? "") };
    }
    return { ok: false, status: res.status, code: res.status === 422 ? "invalid_input" : "error", message: "" };
  } catch {
    return { ok: false, status: 0, code: "unreachable", message: "" };
  }
}

/** Whether email-and-password accounts are on, and whether emails really go out. */
export async function accountOptions(): Promise<{ password: boolean; email_delivery: boolean }> {
  const r = await accountsApi<{ password: boolean; email_delivery: boolean }>("/auth/options");
  return r.ok ? r.data : { password: false, email_delivery: false };
}
