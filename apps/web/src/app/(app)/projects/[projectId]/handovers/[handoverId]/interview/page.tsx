import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { KindTag, RedactedText } from "@/components/evidence-bits";
import { EmptyState } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { EVIDENCE_KIND_LABEL, type HandoverDetail, type Member, type User } from "@/lib/types";
import { AnswerForm } from "./answer-form";

export const metadata: Metadata = { title: "Gap Interview" };

export default async function InterviewPage({
  params,
}: PageProps<"/projects/[projectId]/handovers/[handoverId]/interview">) {
  const { projectId, handoverId } = await params;
  let h: HandoverDetail;
  try {
    h = await api<HandoverDetail>(`/projects/${projectId}/handovers/${handoverId}`);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422)) notFound();
    throw e;
  }
  const [me, members] = await Promise.all([
    api<User>("/me"),
    api<Member[]>(`/projects/${projectId}/members`),
  ]);
  const mine = h.questions.filter((q) => q.assignee.id === me.id || q.answered_by_name === me.name);
  const open = mine.filter((q) => q.status === "open" || q.status === "reassigned");
  const q = open[0];
  const done = mine.length - open.length;
  const back = `/projects/${projectId}/handovers/${handoverId}`;

  return (
    <div className="mx-auto max-w-2xl">
      <Link href={back} className="text-[13px] text-ink-muted hover:text-ink">
        ← {h.title}
      </Link>

      {!q ? (
        <div className="mt-8">
          <EmptyState
            title={mine.length ? "That's everything. Thank you." : "No questions for you"}
            action={
              <Link href={back} className="text-accent hover:underline">
                Back to the handover
              </Link>
            }
          >
            {mine.length
              ? `Your answers are in the claim ledger now, and ${h.successor.name} will see what they settled.`
              : "When the Gap Interviewer has questions for you, they'll appear here."}
          </EmptyState>
        </div>
      ) : (
        <article className="mt-6">
          <p className="text-[13px] text-ink-muted">
            Question {done + 1} of {mine.length}
            <span className="ml-2 inline-flex gap-1 align-middle" aria-hidden="true">
              {mine.map((m, i) => (
                <span key={m.id} className={`h-1.5 w-5 rounded-full ${i < done ? "bg-accent" : i === done ? "bg-ink-faint" : "bg-rule-strong"}`} />
              ))}
            </span>
          </p>
          <h1 className="mt-4 font-display text-[2rem] leading-[1.15] tracking-[-0.03em] text-ink">{q.question}</h1>
          {q.why_asked && <p className="mt-2 text-ink-muted leading-relaxed">{q.why_asked}</p>}

          {q.claims.length > 0 && (
            <section className="mt-8 border-t border-ink/80 pt-4">
              <h2 className="text-[13px] font-medium text-ink-muted">
                {q.kind === "choose" ? "What the sources say" : "What we found"}
              </h2>
              <ul className="mt-2 grid gap-4">
                {q.claims.map((c, i) => (
                  <li key={c.id}>
                    <p className="text-[15px]">
                      {q.kind === "choose" && <span className="mr-1 tabular-nums text-[12px] text-ink-faint">{i === 0 ? "A" : "B"}</span>}
                      <RedactedText text={c.statement} />
                    </p>
                    {c.evidence.slice(0, 2).map((e) => (
                      <p key={e.evidence_id} className="mt-1 border-l-2 border-rule-strong pl-3 text-[13px] text-ink-muted">
                        “<RedactedText text={e.quote} />”
                        <span className="ml-1 text-ink-faint">
                          <KindTag>{EVIDENCE_KIND_LABEL[e.kind] ?? e.kind}</KindTag> {e.source_name}
                          {e.occurred_at && `, ${formatDate(e.occurred_at)}`}
                        </span>
                      </p>
                    ))}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <div className="mt-6">
            <AnswerForm
              key={q.id}
              projectId={projectId}
              handoverId={handoverId}
              questionId={q.id}
              others={members.filter((m) => m.user.id !== me.id)}
            />
          </div>
        </article>
      )}
    </div>
  );
}
