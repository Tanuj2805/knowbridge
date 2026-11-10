import { apiText } from "@/lib/api";

const FORMATS = {
  md: { path: "pack.md", file: "handover-pack.md" },
  ics: { path: "plan.ics", file: "handover-plan.ics" },
} as const;

/** Downloads the pack as Markdown (?format=md) or the 30-day plan as a calendar (?format=ics). */
export async function GET(request: Request, { params }: RouteContext<"/projects/[projectId]/handovers/[handoverId]/export">) {
  const { projectId, handoverId } = await params;
  const format = new URL(request.url).searchParams.get("format") === "ics" ? "ics" : "md";
  const { path, file } = FORMATS[format];
  const res = await apiText(`/projects/${projectId}/handovers/${handoverId}/${path}`);
  if (res.status !== 200) return new Response("Not available.", { status: res.status });
  return new Response(res.text, {
    headers: { "Content-Type": res.type, "Content-Disposition": `attachment; filename="${file}"` },
  });
}
