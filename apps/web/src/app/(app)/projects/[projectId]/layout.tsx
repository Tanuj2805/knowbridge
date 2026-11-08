import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import type { ProjectSummary } from "@/lib/types";
import { ProjectTabs } from "./tabs";

export default async function ProjectLayout({ children, params }: LayoutProps<"/projects/[projectId]">) {
  const { projectId } = await params;
  let project: ProjectSummary;
  try {
    project = await api<ProjectSummary>(`/projects/${projectId}`);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422)) notFound();
    throw e;
  }
  const staff = project.my_roles.some((r) => r === "admin" || r === "approver");

  const tabs = [
    { href: "", label: "Overview" },
    ...(staff
      ? [
          { href: "/sources", label: "Sources" },
          { href: "/evidence", label: "Evidence" },
          { href: "/ledger", label: "Claim ledger" },
        ]
      : []),
    { href: "/handovers", label: "Handovers" },
    { href: "/members", label: "People" },
    ...(staff ? [{ href: "/audit", label: "Audit log" }] : []),
  ];

  return (
    <div>
      <div className="border-b border-rule bg-paper-sunk/60">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 pt-6">
          <p className="text-[13px] text-ink-muted">
            <Link href="/projects" className="hover:text-ink">
              Projects
            </Link>{" "}
            <span aria-hidden="true">/</span>
          </p>
          <h1 className="font-serif text-[1.75rem] leading-tight mt-1">{project.name}</h1>
          <div className="mt-3">
            <ProjectTabs base={`/projects/${projectId}`} tabs={tabs} />
          </div>
        </div>
      </div>
      <main className="mx-auto max-w-6xl px-4 sm:px-6 py-8">{children}</main>
    </div>
  );
}
