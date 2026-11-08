import type { Metadata } from "next";
import { Avatar, Tag } from "@/components/ui";
import { api } from "@/lib/api";
import { ROLE_LABEL, type Member, type ProjectSummary } from "@/lib/types";
import { MemberForm, RemoveMemberButton } from "./member-form";

export const metadata: Metadata = { title: "People" };

export default async function MembersPage({ params }: PageProps<"/projects/[projectId]/members">) {
  const { projectId } = await params;
  const [project, members] = await Promise.all([
    api<ProjectSummary>(`/projects/${projectId}`),
    api<Member[]>(`/projects/${projectId}/members`),
  ]);
  const admin = project.my_roles.includes("admin");

  return (
    <div className="grid gap-12 lg:grid-cols-[1fr_22rem]">
      <section>
        <h2 className="font-serif text-xl">People on this project</h2>
        <p className="text-ink-muted text-[15px] mt-1 max-w-xl">
          Roles decide what each person can do. Clearances decide whether they can see restricted or
          confidential material at all — a role alone never unlocks confidential items.
        </p>
        <ul className="mt-5 divide-y divide-rule border-y border-rule">
          {members.map((m) => (
            <li key={m.user.id} className="flex items-start gap-3 py-4">
              <Avatar name={m.user.name} src={m.user.avatar_url} size={34} />
              <div className="flex-1 min-w-0">
                <p className="font-medium">{m.user.name}</p>
                <p className="text-[13px] text-ink-muted truncate">{m.user.email}</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {m.roles.map((r) => (
                    <Tag key={r} tone={r === "admin" || r === "approver" ? "accent" : "neutral"}>
                      {ROLE_LABEL[r]}
                    </Tag>
                  ))}
                  {m.role_template && <Tag>{m.role_template} handover</Tag>}
                  {m.clearances.map((c) => (
                    <Tag key={c}>cleared: {c}</Tag>
                  ))}
                </div>
              </div>
              {admin && !m.roles.includes("admin") && (
                <RemoveMemberButton projectId={projectId} userId={m.user.id} name={m.user.name} />
              )}
            </li>
          ))}
        </ul>
      </section>

      {admin && (
        <aside>
          <h2 className="font-serif text-xl">Add or update someone</h2>
          <p className="text-ink-muted text-[14px] mt-1 mb-5">
            Use the email they&apos;ll sign in with. Saving again with the same email updates them.
          </p>
          <MemberForm projectId={projectId} />
        </aside>
      )}
    </div>
  );
}
