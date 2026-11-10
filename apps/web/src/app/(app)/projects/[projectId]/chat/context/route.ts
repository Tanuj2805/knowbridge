import { apiText } from "@/lib/api";

const BUDGETS = new Set(["4000", "8000", "16000", "32000"]);

/** Downloads the whole project as one Markdown context file, to give any other model. */
export async function GET(request: Request, { params }: RouteContext<"/projects/[projectId]/chat/context">) {
  const { projectId } = await params;
  const asked = new URL(request.url).searchParams.get("tokens") ?? "8000";
  const tokens = BUDGETS.has(asked) ? asked : "8000";
  const res = await apiText(`/projects/${projectId}/rag/context.md?budget_tokens=${tokens}`);
  if (res.status !== 200) return new Response("Not available.", { status: res.status });
  return new Response(res.text, {
    headers: { "Content-Type": res.type, "Content-Disposition": 'attachment; filename="project-context.md"' },
  });
}
