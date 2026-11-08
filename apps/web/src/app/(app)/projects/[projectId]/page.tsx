import Link from "next/link";
import { buttonClass } from "@/components/ui";
import { api } from "@/lib/api";
import type { EvidenceStats, ProjectSummary } from "@/lib/types";
import { SmartSearchStatus } from "./build-search";

function Step({ n, title, done, children }: { n: number; title: string; done: boolean; children: React.ReactNode }) {
  return (
    <li className="grid grid-cols-[2rem_1fr] gap-3 py-4">
      <span
        className={
          "mt-0.5 h-7 w-7 rounded-full border flex items-center justify-center font-mono text-[12px] " +
          (done ? "bg-accent border-accent text-on-accent" : "border-rule-strong text-ink-muted")
        }
        aria-label={done ? "Done" : `Step ${n}`}
      >
        {done ? "✓" : n}
      </span>
      <div>
        <p className="font-medium">{title}</p>
        <div className="text-ink-muted text-[15px] mt-0.5 leading-relaxed">{children}</div>
      </div>
    </li>
  );
}

export default async function ProjectOverview({ params }: PageProps<"/projects/[projectId]">) {
  const { projectId } = await params;
  const p = await api<ProjectSummary>(`/projects/${projectId}`);
  const base = `/projects/${projectId}`;
  const admin = p.my_roles.includes("admin");
  const staff = admin || p.my_roles.includes("approver");
  const stats = staff && p.evidence_count > 0 ? await api<EvidenceStats>(`/projects/${projectId}/evidence/stats`) : null;

  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_18rem]">
      <section>
        {p.description && <p className="prose-ledger text-ink max-w-2xl">{p.description}</p>}
        <h2 className="font-serif text-xl mt-8">Getting to a handover</h2>
        <ol className="mt-2 divide-y divide-rule border-y border-rule max-w-2xl">
          <Step n={1} title="Add the people involved" done={p.member_count > 1}>
            Who is leaving, who is taking over, and who signs off.{" "}
            <Link className="text-accent underline-offset-4 hover:underline" href={`${base}/members`}>
              Manage people
            </Link>
          </Step>
          <Step n={2} title="Connect what the team already wrote" done={p.source_count > 0}>
            The repository, meeting notes, task board and chat exports. Read-only, and secrets are masked on the
            way in.{" "}
            {staff && (
              <Link className="text-accent underline-offset-4 hover:underline" href={`${base}/sources`}>
                {p.source_count > 0 ? "See sources" : "Connect sources"}
              </Link>
            )}
          </Step>
          <Step n={3} title="Rebuild the project's state" done={p.claim_count > 0}>
            Nine agents pull out decisions, owners, risks and open questions, and a separate checker grades each
            one against its source.
          </Step>
          <Step n={4} title="Ask the leaver only what's missing" done={false}>
            About ten questions, not a twenty-page document.
          </Step>
          <Step n={5} title="Review, approve, hand over" done={false}>
            Nothing reaches the successor until the approver signs off.
          </Step>
        </ol>
      </section>

      <aside className="lg:border-l lg:border-rule lg:pl-8">
        <dl className="grid grid-cols-2 gap-y-4 lg:grid-cols-1">
          {[
            ["People", p.member_count],
            ["Sources", p.source_count],
            ["Evidence units", p.evidence_count],
            ["Claims", p.claim_count],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-[13px] text-ink-muted">{k}</dt>
              <dd className="font-serif text-2xl">{Number(v).toLocaleString("en-IN")}</dd>
            </div>
          ))}
        </dl>
        {stats && (
          <div className="mt-6 border-t border-rule pt-5 text-[14px] text-ink-muted grid gap-1.5">
            <p>
              <span className="text-ink font-medium">{stats.masked_secrets}</span> secret
              {stats.masked_secrets === 1 ? "" : "s"} and{" "}
              <span className="text-ink font-medium">{stats.masked_pii}</span> personal detail
              {stats.masked_pii === 1 ? "" : "s"} masked on the way in.
            </p>
            {(stats.by_sensitivity.restricted ?? 0) + (stats.by_sensitivity.confidential ?? 0) > 0 && (
              <p>
                {stats.by_sensitivity.restricted ?? 0} restricted and {stats.by_sensitivity.confidential ?? 0}{" "}
                confidential items you can see.
              </p>
            )}
            {stats.hidden > 0 && <p>{stats.hidden} items are outside your access.</p>}
            <SmartSearchStatus
              projectId={projectId}
              ready={stats.embedded}
              total={stats.visible}
              model={stats.search_model}
              admin={admin}
              external={stats.search_external}
              keptPrivate={stats.kept_private}
            />
            {stats.by_language["hi-en"] ? <p>{stats.by_language["hi-en"]} Hinglish messages.</p> : null}
          </div>
        )}
        {admin && (
          <Link href={`${base}/members`} className={buttonClass("secondary") + " mt-6"}>
            Add people
          </Link>
        )}
      </aside>
    </div>
  );
}
