/**
 * The public door for the editor extension and MCP server. The API itself has no public address;
 * this passes requests that carry a personal access token ("Bearer kb_...") through to it, and
 * nothing else. The API decides what a token may reach (read-only routes, one project).
 */
import { type NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL ?? "http://localhost:8000";
const MAX_BODY = 64 * 1024;

async function pass(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const auth = req.headers.get("authorization") ?? "";
  if (!/^Bearer kb_[\w-]{20,}$/.test(auth)) {
    return NextResponse.json(
      { detail: "Use a KnowBridge access token: Authorization: Bearer kb_..." },
      { status: 401, headers: { "WWW-Authenticate": "Bearer" } },
    );
  }
  const { path } = await ctx.params;
  if (path.some((p) => p === ".." || p === "." || p.includes("\\"))) {
    return NextResponse.json({ detail: "Not found." }, { status: 404 });
  }
  const url = `${API_URL}/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;

  let body: string | undefined;
  if (req.method === "POST") {
    body = await req.text();
    if (body.length > MAX_BODY) return NextResponse.json({ detail: "Request too large." }, { status: 413 });
  }
  let res: Response;
  try {
    res = await fetch(url, {
      method: req.method,
      cache: "no-store",
      // Only what the API needs: never the browser's cookies.
      headers: { Authorization: auth, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body,
    });
  } catch {
    return NextResponse.json({ detail: "KnowBridge is unreachable right now. Try again shortly." }, { status: 502 });
  }
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "Content-Type": res.headers.get("content-type") ?? "application/json", "Cache-Control": "no-store" },
  });
}

export const GET = pass;
export const POST = pass;
