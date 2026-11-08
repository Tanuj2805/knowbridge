import "server-only";
import { SignJWT } from "jose";
import { redirect } from "next/navigation";
import { auth } from "@/auth";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function apiToken(): Promise<string> {
  const session = await auth();
  const email = session?.user?.email;
  if (!email) redirect("/signin");
  const secret = new TextEncoder().encode(process.env.API_JWT_SECRET);
  return new SignJWT({
    name: session.user?.name ?? undefined,
    picture: session.user?.image ?? undefined,
    provider: session.provider,
  })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(email)
    .setIssuer("knowbridge-web")
    .setAudience("knowbridge-api")
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(secret);
}

/** Call the KnowBridge API as the signed-in user. Server-side only. */
export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(`${API_URL}${path}`, {
    ...rest,
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${await apiToken()}`,
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (res.status === 401) redirect("/signin");
  if (!res.ok) {
    let message = `Something went wrong (${res.status}).`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
