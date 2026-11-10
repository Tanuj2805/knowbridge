import { Database, ExternalLink, LockKeyhole, Tag as TagIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { KindTag, RedactedText, SensitivityTag } from "@/components/evidence-bits";
import { Avatar, BackLink, Card, Tag, buttonClass, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { EVIDENCE_KIND_LABEL, SOURCE_KIND_LABEL, type EvidenceDetail, type ProjectSummary } from "@/lib/types";
import { Relabel } from "./relabel";

export const metadata: Metadata = { title: "Evidence" };

function Fact({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="py-4 first:pt-0">
      <p className="flex items-center gap-2 text-[12px] font-medium uppercase tracking-[0.08em] text-ink-faint">
        {icon}
        {title}
      </p>
      <div className="mt-2 text-[14px] leading-relaxed text-ink">{children}</div>
    </div>
  );
}

export default async function EvidenceDetailPage({
  params,
}: PageProps<"/projects/[projectId]/evidence/[evidenceId]">) {
  const { projectId, evidenceId } = await params;
  let e: EvidenceDetail;
  try {
    e = await api<EvidenceDetail>(`/projects/${projectId}/evidence/${evidenceId}`);
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 422)) notFound();
    throw err;
  }
  const project = await api<ProjectSummary>(`/projects/${projectId}`);
  const admin = project.my_roles.includes("admin");
  const secrets = e.redactions.filter((r) => r.category === "secret").length;
  const personal = e.redactions.length - secrets;

  return (
    <article>
      <BackLink href={`/projects/${projectId}/evidence`}>All evidence</BackLink>

      <div className="mt-5 grid gap-12 lg:grid-cols-[1fr_19rem] lg:gap-16">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <KindTag>{EVIDENCE_KIND_LABEL[e.kind] ?? e.kind}</KindTag>
            <SensitivityTag value={e.sensitivity} />
            {e.removed && <Tag tone="danger">No longer in the source</Tag>}
          </div>
          <h1 className="mt-3 font-display text-[1.9rem] leading-[1.15] tracking-[-0.03em] text-ink">
            {/* a chat message's or meeting line's title is only where it was said */}
            {e.kind === "message" && "Message in "}
            {e.kind === "meeting_segment" && "From "}
            <RedactedText text={e.title || e.locator} />
          </h1>
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-ink-muted">
            {e.author && (
              <span className="inline-flex items-center gap-2">
                <Avatar name={e.author} size={22} />
                <span className="font-medium text-ink">{e.author}</span>
              </span>
            )}
            {e.occurred_at && <span>{formatDateTime(e.occurred_at)}</span>}
            {e.locator && <span className="text-ink-faint">{e.locator}</span>}
          </div>

          <Card framed className="mt-6 px-6 py-5">
            <p className="prose-ledger whitespace-pre-wrap break-words text-ink">
              <RedactedText text={e.text} />
            </p>
          </Card>

          {e.linked.length > 0 && (
            <section className="mt-8">
              <h2 className="font-display text-[1.15rem] text-ink">
                {e.meta.provider === "jira" ? "Commits, PRs and messages that mention it" : "Linked Jira issues"}
              </h2>
              <ul className="stagger mt-3 border-t border-rule">
                {e.linked.map((l) => (
                  <li key={l.id}>
                    <Link
                      href={`/projects/${projectId}/evidence/${l.id}`}
                      className="group block border-b border-rule py-3"
                    >
                      <p className="flex items-center gap-2">
                        <KindTag>{EVIDENCE_KIND_LABEL[l.kind] ?? l.kind}</KindTag>
                        <span className="truncate text-[14px] font-medium text-ink group-hover:text-accent">
                          <RedactedText text={l.title || l.locator} />
                        </span>
                      </p>
                      <p className="mt-1 text-[12px] text-ink-faint">
                        {[l.author, formatDateTime(l.occurred_at), l.locator].filter(Boolean).join(" · ")}
                      </p>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {e.context.length > 0 && (
            <section className="mt-8">
              <h2 className="font-display text-[1.15rem] text-ink">
                {e.kind === "meeting_segment" ? "Before and after in this meeting" : "Around this message"}
              </h2>
              <ol className="mt-3 grid gap-1">
                {e.context.map((c) => (
                  <li key={c.id}>
                    <Link
                      href={`/projects/${projectId}/evidence/${c.id}`}
                      className="group flex gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-paper-raised"
                    >
                      <Avatar name={c.author || "?"} size={30} />
                      <div className="min-w-0 flex-1">
                        <p className="text-[12px]">
                          <span className="font-semibold text-ink">{c.author}</span>
                          <span className="text-ink-faint"> · {formatDateTime(c.occurred_at)}</span>
                        </p>
                        <p className="mt-0.5 line-clamp-2 text-[14px] leading-relaxed text-ink-muted group-hover:text-ink">
                          <RedactedText text={c.snippet} />
                        </p>
                      </div>
                    </Link>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </div>

        <Card as="aside" className="self-start divide-y divide-rule lg:sticky lg:top-24">
          <Fact icon={<Database className="size-3.5" aria-hidden="true" />} title="Source">
            <p className="font-semibold">{e.source_name}</p>
            <p className="text-[13px] text-ink-muted">{SOURCE_KIND_LABEL[e.source_kind]}</p>
            {e.permalink && (
              <a
                href={e.permalink}
                target="_blank"
                rel="noreferrer noopener"
                className={cx(buttonClass("secondary", "sm"), "mt-3")}
              >
                Open the original
                <ExternalLink className="size-3.5" aria-hidden="true" />
              </a>
            )}
          </Fact>
          <Fact icon={<LockKeyhole className="size-3.5" aria-hidden="true" />} title="Masked by Sentinel">
            {e.redactions.length === 0 ? (
              <p className="text-ink-muted">Nothing in this item.</p>
            ) : (
              <p>
                {secrets > 0 && `${secrets} secret${secrets > 1 ? "s" : ""}`}
                {secrets > 0 && personal > 0 && ", "}
                {personal > 0 && `${personal} personal detail${personal > 1 ? "s" : ""}`}.{" "}
                <span className="text-ink-muted">The original values were never stored.</span>
              </p>
            )}
          </Fact>
          <Fact icon={<TagIcon className="size-3.5" aria-hidden="true" />} title="Why it has this label">
            {e.label_reasons.length > 0 ? (
              <p>
                Matched {e.label_reasons.length === 1 ? "a rule" : `${e.label_reasons.length} rules`} for {e.sensitivity}{" "}
                material.
              </p>
            ) : e.sensitivity === "team" ? (
              <p className="text-ink-muted">Nothing sensitive found; the source&apos;s default applies.</p>
            ) : (
              <p>The source, or the document itself, is marked {e.sensitivity}.</p>
            )}
            {admin && (
              <div className="mt-3">
                <Relabel projectId={projectId} evidenceId={e.id} value={e.sensitivity} />
              </div>
            )}
          </Fact>
        </Card>
      </div>
    </article>
  );
}
