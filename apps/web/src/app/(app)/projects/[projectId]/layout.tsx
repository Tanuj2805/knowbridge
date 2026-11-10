import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import { ROLE_LABEL, type ProjectSummary } from "@/lib/types";
import { ProjectNav, type Tab } from "./project-nav";

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
  const base = `/projects/${projectId}`;

  const tabs: Tab[] = [
    { href: "", label: "Overview" },
    { href: "/chat", label: "Chat" },
    ...(staff
      ? ([
          { href: "/sources", label: "Sources", count: project.source_count },
          { href: "/evidence", label: "Evidence", count: project.evidence_count },
          { href: "/ledger", label: "Claim ledger", count: project.claim_count },
        ] satisfies Tab[])
      : []),
    { href: "/handovers", label: "Handovers", count: project.handover_count },
    { href: "/members", label: "People", count: project.member_count },
    ...(staff ? ([{ href: "/audit", label: "Audit log" }] satisfies Tab[]) : []),
  ];


  return (
    <div className="flex flex-1 flex-col">
      <div className="border-b border-rule print:hidden">
        <div className="mx-auto max-w-[80rem] px-4 pt-5 sm:px-6">
          <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-[13px] text-ink-faint">
            <Link href="/projects" className="hover:text-ink">
              Projects
            </Link>
            <ChevronRight className="size-3.5" aria-hidden="true" />
            <span className="truncate text-ink-muted">{project.name}</span>
          </nav>
          <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <p className="truncate font-display text-[1.6rem] leading-tight tracking-[-0.03em] text-ink">{project.name}</p>
            <p className="text-[13px] text-ink-faint">
              You&apos;re {project.my_roles.map((r) => ROLE_LABEL[r].toLowerCase()).join(" and ") || "a member"} here
            </p>
          </div>
          <div className="mt-3">
            <ProjectNav base={base} tabs={tabs} />
          </div>
        </div>
      </div>
      <main className="mx-auto w-full max-w-[80rem] flex-1 px-4 py-8 sm:px-6">{children}</main>
    </div>
  );
}
