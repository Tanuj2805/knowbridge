import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { KindTag, RedactedText, SensitivityTag } from "@/components/evidence-bits";
import { buttonClass } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { EVIDENCE_KIND_LABEL, SOURCE_KIND_LABEL, type EvidenceDetail, type ProjectSummary } from "@/lib/types";
import { Relabel } from "./relabel";

export const metadata: Metadata = { title: "Evidence" };

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
    <article className="grid gap-10 lg:grid-cols-[1fr_17rem]">
      <div className="min-w-0">
        <Link href={`/projects/${projectId}/evidence`} className="text-[13px] text-ink-muted hover:text-ink">
          ← All evidence
        </Link>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <KindTag>{EVIDENCE_KIND_LABEL[e.kind] ?? e.kind}</KindTag>
          <SensitivityTag value={e.sensitivity} />
          {e.removed && <span className="text-[12px] text-danger">No longer in the source</span>}
        </div>
        <h2 className="font-serif text-2xl mt-2 leading-snug">
          <RedactedText text={e.title || e.locator} />
        </h2>
        <p className="font-mono text-[12px] text-ink-faint mt-2">
          {[e.author, formatDateTime(e.occurred_at), e.locator].filter(Boolean).join(" · ")}
        </p>

        <div className="mt-6 rounded-lg border border-rule bg-paper-raised px-5 py-4">
          <p className="prose-ledger whitespace-pre-wrap break-words">
            <RedactedText text={e.text} />
          </p>
        </div>

        {e.linked.length > 0 && (
          <section className="mt-8">
            <h3 className="text-sm font-medium">
              {e.meta.provider === "jira" ? "Commits, PRs and messages that mention it" : "Linked Jira issues"}
            </h3>
            <ul className="mt-2 divide-y divide-rule border-y border-rule">
              {e.linked.map((l) => (
                <li key={l.id}>
                  <Link href={`/projects/${projectId}/evidence/${l.id}`} className="group block py-2.5">
                    <p className="flex items-baseline gap-2">
                      <KindTag>{EVIDENCE_KIND_LABEL[l.kind] ?? l.kind}</KindTag>
                      <span className="text-[14px] group-hover:text-accent">
                        <RedactedText text={l.title || l.locator} />
                      </span>
                    </p>
                    <p className="font-mono text-[12px] text-ink-faint">
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
            <h3 className="text-sm font-medium">{e.kind === "meeting_segment" ? "Before and after in this meeting" : "Around this message"}</h3>
            <ol className="mt-2 border-l-2 border-rule pl-4 grid gap-3">
              {e.context.map((c) => (
                <li key={c.id}>
                  <Link href={`/projects/${projectId}/evidence/${c.id}`} className="block group">
                    <p className="font-mono text-[12px] text-ink-faint">
                      {c.author} · {formatDateTime(c.occurred_at)}
                    </p>
                    <p className="text-[14px] text-ink-muted group-hover:text-ink line-clamp-2">
                      <RedactedText text={c.snippet} />
                    </p>
                  </Link>
                </li>
              ))}
            </ol>
          </section>
        )}
      </div>

      <aside className="grid content-start gap-6 text-[14px] lg:border-l lg:border-rule lg:pl-6">
        <div>
          <p className="text-[13px] text-ink-muted">Source</p>
          <p className="font-medium">{e.source_name}</p>
          <p className="text-[13px] text-ink-faint">{SOURCE_KIND_LABEL[e.source_kind]}</p>
          {e.permalink && (
            <a href={e.permalink} target="_blank" rel="noreferrer noopener" className={buttonClass("secondary", "sm") + " mt-2"}>
              Open the original ↗
            </a>
          )}
        </div>

        <div>
          <p className="text-[13px] text-ink-muted">Masked by Sentinel</p>
          {e.redactions.length === 0 ? (
            <p>Nothing in this item.</p>
          ) : (
            <p>
              {secrets > 0 && `${secrets} secret${secrets > 1 ? "s" : ""}`}
              {secrets > 0 && personal > 0 && ", "}
              {personal > 0 && `${personal} personal detail${personal > 1 ? "s" : ""}`}. The original values were
              never stored.
            </p>
          )}
        </div>

        <div>
          <p className="text-[13px] text-ink-muted">Why it has this label</p>
          {e.label_reasons.length > 0 ? (
            <p>Matched {e.label_reasons.length === 1 ? "a rule" : `${e.label_reasons.length} rules`} for {e.sensitivity} material.</p>
          ) : e.sensitivity === "team" ? (
            <p>Nothing sensitive found; the source&apos;s default applies.</p>
          ) : (
            <p>The source, or the document itself, is marked {e.sensitivity}.</p>
          )}
          {admin && (
            <div className="mt-3">
              <Relabel projectId={projectId} evidenceId={e.id} value={e.sensitivity} />
            </div>
          )}
        </div>
      </aside>
    </article>
  );
}
