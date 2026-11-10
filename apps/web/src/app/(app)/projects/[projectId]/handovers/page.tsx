import { ArrowRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Avatar, Card, CardHeader, EmptyState, PageHeader, Progress, Tag, buttonClass } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate, plural } from "@/lib/format";
import {
  HANDOVER_STATUS_LABEL,
  HANDOVER_STATUS_TONE,
  type Handover,
  type Member,
  type ProjectSummary,
} from "@/lib/types";
import { NewHandoverForm } from "./new-handover-form";

export const metadata: Metadata = { title: "Handovers" };


export default async function HandoversPage({ params }: PageProps<"/projects/[projectId]/handovers">) {
  const { projectId } = await params;
  const [handovers, project] = await Promise.all([
    api<Handover[]>(`/projects/${projectId}/handovers`),
    api<ProjectSummary>(`/projects/${projectId}`),
  ]);
  const staff = project.my_roles.some((r) => r === "admin" || r === "approver");
  const members = staff ? await api<Member[]>(`/projects/${projectId}/members`) : [];

  return (
    <div>
      <PageHeader
        title="Handovers"
        actions={
          staff && (
            <a href="#new-handover" className={buttonClass("primary")}>
              Start a handover
            </a>
          )
        }
      >
        One person passing their part of the project to another. KnowBridge asks the person leaving about what the
        evidence leaves unclear, then an approver reviews everything before it&apos;s shared.
      </PageHeader>

      {handovers.length === 0 ? (
        <EmptyState title="No handovers yet">
          {staff
            ? "Start one below when someone is about to leave or change roles."
            : "When someone hands their work to you, or you hand yours over, it appears here."}
        </EmptyState>
      ) : (
        <ul className="stagger border-t border-ink/80">
          {handovers.map((h) => (
            <li key={h.id} className="border-b border-rule">
              <Link
                href={`/projects/${projectId}/handovers/${h.id}`}
                className="group grid items-center gap-x-8 gap-y-3 py-5 md:grid-cols-[1fr_12rem_11rem_auto]"
              >
                <div className="flex min-w-0 items-center gap-4">
                  <div className="flex shrink-0 items-center">
                    <Avatar name={h.leaver.name} size={34} />
                    <span className="-ml-2 rounded-full ring-2 ring-paper">
                      <Avatar name={h.successor.name} size={34} />
                    </span>
                  </div>
                  <div className="min-w-0">
                    <p className="truncate font-display text-[1.2rem] tracking-[-0.02em] text-ink transition-colors group-hover:text-accent">
                      {h.title}
                    </p>
                    <p className="truncate text-[13px] text-ink-faint">
                      Approved by {h.approver.name}
                      {h.leaver_last_day && ` · last day ${formatDate(h.leaver_last_day)}`}
                    </p>
                  </div>
                </div>
                <div>
                  <Tag tone={HANDOVER_STATUS_TONE[h.status]}>{HANDOVER_STATUS_LABEL[h.status]}</Tag>
                  {h.my_open > 0 && (
                    <p className="mt-1 text-[12px] font-medium text-accent">{plural(h.my_open, "question")} for you</p>
                  )}
                </div>
                <div>
                  {h.questions_total > 0 ? (
                    <>
                      <p className="mb-1.5 tabular-nums text-[12px]  text-ink-muted">
                        {h.questions_answered}/{h.questions_total} answered
                      </p>
                      <Progress size="sm" value={h.questions_answered / h.questions_total} label="Questions answered" />
                    </>
                  ) : (
                    <p className="text-[13px] text-ink-faint">Interview not started</p>
                  )}
                </div>
                <ArrowRight
                  className="hidden size-5 text-ink-faint transition-transform duration-200 group-hover:translate-x-1 group-hover:text-accent md:block"
                  aria-hidden="true"
                />
              </Link>
            </li>
          ))}
        </ul>
      )}

      {staff && (
        <Card as="section" id="new-handover" className="mt-14 max-w-4xl scroll-mt-24">
          <CardHeader title="Start a handover">
            Pick who&apos;s leaving, who&apos;s taking over, and who approves. The Gap Interview comes next.
          </CardHeader>
          <div className="mt-5">
            <NewHandoverForm projectId={projectId} members={members} />
          </div>
        </Card>
      )}
    </div>
  );
}
