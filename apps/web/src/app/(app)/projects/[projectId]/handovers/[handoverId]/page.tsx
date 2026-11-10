import { BookOpen, Check, Flag, MessageSquareText } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Working } from "@/components/agent-pipeline";
import { AutoRefresh } from "@/components/auto-refresh";
import { RedactedText } from "@/components/evidence-bits";
import { HandoverStages } from "@/components/handover-stages";
import { Avatar, Card, CardHeader, PageHeader, Progress, Tag, buttonClass } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatDate, formatDateTime, plural } from "@/lib/format";
import { HANDOVER_STATUS_LABEL, HANDOVER_STATUS_TONE, type GapQuestion, type HandoverDetail, type User } from "@/lib/types";
import { ComposeButton, PublishButton } from "./pack-actions";
import { StartInterview } from "./start-interview";

export const metadata: Metadata = { title: "Handover" };

const KIND_LABEL = { choose: "Sources disagree", confirm: "To confirm", fill: "Missing", "": "" } as const;
const KIND_TONE = { choose: "warning", confirm: "info", fill: "danger", "": "neutral" } as const;

function Person({ role, user, note }: { role: string; user: User; note?: string }) {
  return (
    <div className="flex items-center gap-3 py-4">
      <Avatar name={user.name} src={user.avatar_url} size={36} />
      <div className="min-w-0">
        <p className="text-[12px] font-medium text-ink-faint">{role}</p>
        <p className="truncate text-[15px] font-medium text-ink">{user.name}</p>
        {note && <p className="text-[12px] text-ink-muted">{note}</p>}
      </div>
    </div>
  );
}

export default async function HandoverPage({ params }: PageProps<"/projects/[projectId]/handovers/[handoverId]">) {
  const { projectId, handoverId } = await params;
  let h: HandoverDetail;
  try {
    h = await api<HandoverDetail>(`/projects/${projectId}/handovers/${handoverId}`);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422)) notFound();
    throw e;
  }
  const waitingOnAnswers = h.questions.some((q) => q.status === "answered" && q.effects.length === 0);
  const interviewUrl = `/projects/${projectId}/handovers/${handoverId}/interview`;
  const packUrl = `/projects/${projectId}/handovers/${handoverId}/pack`;

  return (
    <div>
      <AutoRefresh active={h.preparing || waitingOnAnswers || h.composing} every={2500} />
      <PageHeader
        back={{ href: `/projects/${projectId}/handovers`, label: "All handovers" }}
        eyebrow={
          <Tag tone={HANDOVER_STATUS_TONE[h.status]} dot>
            {HANDOVER_STATUS_LABEL[h.status]}
          </Tag>
        }
        title={h.title}
        actions={
          <>
            {h.my_open > 0 && (
              <Link href={interviewUrl} className={buttonClass("primary")}>
                <MessageSquareText className="size-4" aria-hidden="true" />
                Answer your {plural(h.my_open, "question")}
              </Link>
            )}
            {!h.can_manage && !h.can_publish && h.published_version > 0 && (
              <Link href={packUrl} className={buttonClass("primary")}>
                <BookOpen className="size-4" aria-hidden="true" />
                Read your handover pack
              </Link>
            )}
          </>
        }
      />

      <div className="grid border-y border-rule sm:grid-cols-3 sm:[&>*+*]:border-l sm:[&>*+*]:border-rule sm:[&>*+*]:pl-6">
        <Person
          role="Leaving"
          user={h.leaver}
          note={h.leaver_last_day ? `Last day ${formatDate(h.leaver_last_day)}` : undefined}
        />
        <Person role="Taking over" user={h.successor} />
        <Person role="Approves" user={h.approver} />
      </div>

      <div className="mt-8">
        <HandoverStages handover={h} />
      </div>

      <div className="mt-12 grid gap-12 lg:grid-cols-[1fr_21rem] lg:gap-16">
        <section aria-label="Gap Interview" className="min-w-0">
          <div className="flex flex-wrap items-end justify-between gap-3 border-t border-ink/80 pt-4">
            <div>
              <h2 className="font-display text-[1.2rem] text-ink">Gap Interview</h2>
              <p className="text-[13px] text-ink-muted">
                Questions for {h.leaver.name} about what the evidence leaves unclear.
              </p>
            </div>
            {h.questions.length > 0 && (
              <div className="w-56">
                <div className="mb-1 flex justify-between text-[12px] text-ink-muted">
                  <span>{h.questions_open > 0 ? `${h.questions_open} open` : "All answered"}</span>
                  <span className="tabular-nums">
                    {h.questions_answered}/{h.questions_total}
                  </span>
                </div>
                <Progress
                  size="sm"
                  value={(h.questions_total - h.questions_open) / Math.max(h.questions_total, 1)}
                  label="Questions answered"
                  tone={h.questions_open === 0 ? "success" : "accent"}
                />
              </div>
            )}
          </div>

          {h.questions.length === 0 ? (
            <div className="mt-4 max-w-2xl text-[14px] leading-relaxed text-ink-muted">
              {h.preparing ? (
                <Working>The Gap Interviewer is reading the claims and writing questions for {h.leaver.name}…</Working>
              ) : h.can_manage ? (
                <>
                  <p>
                    The Gap Interviewer looks for what the evidence leaves unclear (sources that disagree, questions
                    nobody answered, risks with no owner) and asks {h.leaver.name} about each, in about ten questions.
                    Answers go back into the claim ledger and change the grades.
                  </p>
                  <div className="mt-4">
                    <StartInterview projectId={projectId} handoverId={handoverId} disabled={!h.claims_ready} />
                    {!h.claims_ready && (
                      <p className="mt-2 text-[13px]">
                        Build claims first, on the{" "}
                        <Link href={`/projects/${projectId}/ledger`} className="font-medium text-accent hover:underline">
                          Claim ledger
                        </Link>
                        .
                      </p>
                    )}
                  </div>
                </>
              ) : (
                <p>Not started yet.</p>
              )}
            </div>
          ) : (
            <ol className="stagger mt-3">
              {h.questions.map((q) => (
                <QuestionRow key={q.id} q={q} />
              ))}
            </ol>
          )}
        </section>

        {(h.can_manage || h.can_publish) && (
          <Card as="aside" className="self-start lg:sticky lg:top-24">
            <CardHeader title="Handover pack">
              Written from approved claims only, filtered to what {h.successor.name} may see.
            </CardHeader>
            <div className="mt-5">
              {h.composing ? (
                <div className="text-[14px]">
                  <Working>The Composer is writing the pack. Usually under a minute; this page updates by itself.</Working>
                </div>
              ) : (
                <div className="grid gap-2">
                  <dl className="grid grid-cols-2 gap-4">
                    <div>
                      <dd className="font-display text-[1.75rem] leading-none tabular-nums text-ink">{h.latest_version || "—"}</dd>
                      <dt className="mt-1 text-[12px] text-ink-faint">Latest version</dt>
                    </div>
                    <div className="border-l border-rule pl-4">
                      <dd className="font-display text-[1.75rem] leading-none tabular-nums text-ink">{h.published_version || "—"}</dd>
                      <dt className="mt-1 text-[12px] text-ink-faint">Published</dt>
                    </div>
                  </dl>
                  <p className="mt-1 text-[13px] leading-relaxed text-ink-muted">
                    {h.latest_version === 0
                      ? `${plural(h.approved_claims, "claim")} approved so far. ${h.successor.name} sees nothing until you publish.`
                      : h.published_version === h.latest_version
                        ? `Version ${h.published_version} is live. ${h.successor.name} can read it.`
                        : `Version ${h.latest_version} is ready to preview.`}
                  </p>
                  {h.open_flags > 0 && (
                    <p className="flex items-start gap-2 text-[13px] text-[var(--grade-conflicting)]">
                      <Flag className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                      {h.successor.name} flagged {plural(h.open_flags, "claim")} as possibly wrong. See them in the pack.
                    </p>
                  )}
                </div>
              )}
              <div className="mt-4 grid gap-2">
                {h.can_publish && h.latest_version > h.published_version && !h.composing && (
                  <PublishButton projectId={projectId} handoverId={handoverId} version={h.latest_version} to={h.successor.name} />
                )}
                {h.latest_version > 0 && (
                  <Link href={packUrl} className={buttonClass("secondary")}>
                    <BookOpen className="size-4" aria-hidden="true" />
                    {h.published_version === h.latest_version ? "Open the pack" : `Preview version ${h.latest_version}`}
                  </Link>
                )}
                {h.can_publish && (
                  <ComposeButton
                    projectId={projectId}
                    handoverId={handoverId}
                    again={h.latest_version > 0}
                    disabled={h.composing || h.approved_claims === 0}
                  />
                )}
              </div>
              {h.approved_claims === 0 && h.can_publish && (
                <p className="mt-3 text-[13px] text-ink-muted">
                  Approve claims on the{" "}
                  <Link href={`/projects/${projectId}/ledger?review=todo`} className="font-medium text-accent hover:underline">
                    Claim ledger
                  </Link>{" "}
                  first.
                </p>
              )}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

function QuestionRow({ q }: { q: GapQuestion }) {
  return (
    <li className="border-b border-rule py-5">
      <div className="flex flex-wrap items-center gap-2 text-[12px]">
        <span className="tabular-nums text-[12px] text-ink-faint">Q{String(q.position).padStart(2, "0")}</span>
        {q.kind && <Tag tone={KIND_TONE[q.kind]}>{KIND_LABEL[q.kind]}</Tag>}
        <span className="ml-auto text-ink-faint">
          {q.status === "answered" ? (
            <span className="inline-flex items-center gap-1 text-[var(--grade-verified)]">
              <Check className="size-3.5" strokeWidth={3} aria-hidden="true" />
              Answered by {q.answered_by_name}
            </span>
          ) : q.status === "skipped" ? (
            `${q.answered_by_name} didn't know`
          ) : (
            <span className="inline-flex items-center gap-1.5 text-accent">
              <span className="size-1.5 rounded-full bg-accent motion-safe:animate-pulse" aria-hidden="true" />
              Waiting for {q.assignee.name}
            </span>
          )}
        </span>
      </div>
      <p className="mt-2 text-[16px] font-medium leading-snug text-ink">{q.question}</p>
      {q.status === "answered" && (
        <div className="mt-3 border-l-2 border-[var(--grade-attested)] pl-3.5">
          <p className="text-[14px] text-ink">
            “<RedactedText text={q.answer} />”
          </p>
          <p className="mt-1 text-[12px] text-ink-faint">{formatDateTime(q.answered_at)}</p>
        </div>
      )}
      {q.effects.length > 0 ? (
        <div className="mt-3">
          <p className="text-[12px] font-semibold text-ink-muted">What changed in the ledger</p>
          <ul className="mt-1 grid gap-1">
            {q.effects.map((effect, i) => (
              <li key={i} className="flex gap-2 text-[13px] text-ink-muted">
                <Check className="mt-0.5 size-3.5 shrink-0 text-[var(--grade-verified)]" aria-hidden="true" />
                {effect}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        q.status === "answered" && (
          <div className="mt-3 text-[13px]">
            <Working>Updating the claim ledger…</Working>
          </div>
        )
      )}
    </li>
  );
}
