import { Lock } from "lucide-react";
import type { Metadata } from "next";
import { Avatar, Card, CardHeader, PageHeader, Tag } from "@/components/ui";
import { api } from "@/lib/api";
import { plural } from "@/lib/format";
import { ROLE_LABEL, type Member, type ProjectSummary, type Role } from "@/lib/types";
import { MemberForm, RemoveMemberButton } from "./member-form";

export const metadata: Metadata = { title: "People" };

const ROLE_TONE: Record<Role, "accent" | "teal" | "warning" | "info" | "neutral"> = {
  admin: "accent",
  approver: "teal",
  leaver: "warning",
  successor: "info",
  viewer: "neutral",
};

export default async function MembersPage({ params }: PageProps<"/projects/[projectId]/members">) {
  const { projectId } = await params;
  const [project, members] = await Promise.all([
    api<ProjectSummary>(`/projects/${projectId}`),
    api<Member[]>(`/projects/${projectId}/members`),
  ]);
  const admin = project.my_roles.includes("admin");

  return (
    <div>
      <PageHeader title="People">
        Roles decide what each person can do. Clearances decide whether they can see restricted or confidential
        material at all; a role alone never unlocks confidential items.
      </PageHeader>

      <div className="grid gap-12 lg:grid-cols-[1fr_24rem] lg:gap-16">
        <Card as="section">
          <CardHeader
            title="On this project"
            action={<span className="text-[13px] text-ink-faint">{plural(members.length, "person", "people")}</span>}
          />
          <ul className="stagger mt-3 divide-y divide-rule">
            {members.map((m) => (
              <li key={m.user.id} className="flex items-center gap-4 py-4">
                <Avatar name={m.user.name} src={m.user.avatar_url} size={40} />
                <div className="min-w-0 flex-1">
                  <p className="text-[15px] font-medium text-ink">{m.user.name}</p>
                  <p className="truncate text-[13px] text-ink-faint">{m.user.email}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {m.roles.map((r) => (
                      <Tag key={r} tone={ROLE_TONE[r]}>
                        {ROLE_LABEL[r]}
                      </Tag>
                    ))}
                    {m.role_template && <Tag>{m.role_template} handover</Tag>}
                    {m.clearances.map((c) => (
                      <Tag key={c} tone={c === "confidential" ? "danger" : "warning"}>
                        <Lock className="size-3" aria-hidden="true" />
                        Cleared: {c}
                      </Tag>
                    ))}
                  </div>
                </div>
                {admin && !m.roles.includes("admin") && (
                  <RemoveMemberButton projectId={projectId} userId={m.user.id} name={m.user.name} />
                )}
              </li>
            ))}
          </ul>
        </Card>

        {admin && (
          <Card as="aside" className="self-start lg:sticky lg:top-24">
            <CardHeader title="Add or update someone">
              Use the email they&apos;ll sign in with. Saving again with the same email updates them.
            </CardHeader>
            <div className="mt-5">
              <MemberForm projectId={projectId} />
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
