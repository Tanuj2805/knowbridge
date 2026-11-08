import type { Metadata } from "next";
import Link from "next/link";
import { demoMode } from "@/auth";
import { EmptyState, PageHeader, Tag } from "@/components/ui";
import { api } from "@/lib/api";
import { plural } from "@/lib/format";
import { ROLE_LABEL, type ProjectSummary } from "@/lib/types";
import { LoadDemo } from "./load-demo";
import { NewProjectForm } from "./new-project-form";

export const metadata: Metadata = { title: "Projects" };

export default async function ProjectsPage() {
  const projects = await api<ProjectSummary[]>("/projects");

  return (
    <main className="mx-auto max-w-6xl px-4 sm:px-6 py-10">
      <PageHeader title="Projects">
        Each project is one team&apos;s work: its sources, its claim ledger, and the handovers made from it.
      </PageHeader>

      {projects.length === 0 ? (
        <div className="mt-8">
          <EmptyState title="Nothing here yet" action={demoMode ? <LoadDemo /> : undefined}>
            Start a project for a team where someone is about to leave. You&apos;ll connect its repository,
            notes and chats next.
          </EmptyState>
        </div>
      ) : (
        <ul className="mt-2 divide-y divide-rule">
          {projects.map((p) => (
            <li key={p.id}>
              <Link
                href={`/projects/${p.id}`}
                className="group grid gap-1 py-5 sm:grid-cols-[1fr_auto] sm:items-baseline rounded-sm"
              >
                <div className="min-w-0">
                  <span className="font-serif text-xl group-hover:text-accent transition-colors">{p.name}</span>
                  {p.description && <p className="text-ink-muted mt-0.5 line-clamp-2">{p.description}</p>}
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {p.my_roles.map((r) => (
                      <Tag key={r} tone={r === "admin" || r === "approver" ? "accent" : "neutral"}>
                        {ROLE_LABEL[r]}
                      </Tag>
                    ))}
                  </div>
                </div>
                <p className="font-mono text-[12px] text-ink-faint sm:text-right">
                  {plural(p.member_count, "person", "people")} · {plural(p.source_count, "source")} ·{" "}
                  {plural(p.claim_count, "claim")}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <section className="mt-14 border-t border-rule pt-8">
        <div className="grid gap-10 md:grid-cols-[1fr_18rem]">
          <div>
            <h2 className="font-serif text-xl mb-4">Start a new project</h2>
            <NewProjectForm />
          </div>
          {demoMode && projects.length > 0 && (
            <div className="text-[14px] text-ink-muted">
              <h2 className="font-serif text-xl mb-2 text-ink">Or explore the demo</h2>
              <p className="mb-4">
                Project Nimbus is a made-up college fest app with four months of commits, notes, a Trello board and
                chats, including planted secrets and a few contradictions.
              </p>
              <LoadDemo />
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
