"use client";

import { useActionState, useTransition } from "react";
import { SubmitButton } from "@/components/submit-button";
import { Button, ErrorNote, Input, Label, RequiredMark, RequiredNote, Select } from "@/components/ui";
import { ROLE_LABEL, type Role } from "@/lib/types";
import { removeMember, upsertMember } from "../../actions";

const ROLES: { role: Role; note: string }[] = [
  { role: "leaver", note: "Answers the Gap Interview" },
  { role: "successor", note: "Receives the handover pack" },
  { role: "approver", note: "Reviews and publishes" },
  { role: "viewer", note: "Reads the project brief" },
  { role: "admin", note: "Connects sources, manages people" },
];

export function MemberForm({ projectId }: { projectId: string }) {
  const [state, action] = useActionState(upsertMember.bind(null, projectId), undefined);
  return (
    <form action={action} className="grid gap-4">
      <RequiredNote />
      <div>
        <Label htmlFor="email" required>
          Email
        </Label>
        <Input id="email" name="email" type="email" required autoComplete="off" />
      </div>
      <div>
        <Label htmlFor="name" hint="Optional">
          Name
        </Label>
        <Input id="name" name="name" autoComplete="off" />
      </div>
      <fieldset>
        <legend className="mb-1.5 text-[14px] font-medium text-ink">
          Roles
          <RequiredMark />
          <span className="ml-1 font-normal text-ink-faint">(at least one)</span>
        </legend>
        <div className="grid gap-1.5">
          {ROLES.map(({ role, note }) => (
            <label key={role} className="flex items-start gap-2 text-[14px]">
              <input type="checkbox" name="roles" value={role} className="mt-1 accent-[var(--accent)]" />
              <span>
                {ROLE_LABEL[role]} <span className="text-ink-faint">— {note}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <div>
        <Label htmlFor="role_template" hint="Optional. Shapes what their handover pack focuses on.">
          Handover template
        </Label>
        <Select id="role_template" name="role_template" defaultValue="">
          <option value="">General</option>
          <option value="backend">Backend developer</option>
          <option value="frontend">Frontend developer</option>
          <option value="lead">Team / tech lead</option>
          <option value="treasurer">Treasurer / finance</option>
          <option value="events">Events &amp; sponsorship</option>
        </Select>
      </div>
      <fieldset>
        <legend className="mb-1.5 text-[14px] font-medium text-ink">
          Clearances <span className="font-normal text-ink-faint">(optional)</span>
        </legend>
        <label className="flex items-start gap-2 text-[14px]">
          <input type="checkbox" name="clearances" value="restricted" className="mt-1 accent-[var(--accent)]" />
          <span>
            Restricted <span className="text-ink-faint">— budgets, sponsor deals</span>
          </span>
        </label>
        <label className="flex items-start gap-2 text-[14px] mt-1.5">
          <input type="checkbox" name="clearances" value="confidential" className="mt-1 accent-[var(--accent)]" />
          <span>
            Confidential <span className="text-ink-faint">— HR, stipends, personal</span>
          </span>
        </label>
      </fieldset>
      {state?.error && <ErrorNote>{state.error}</ErrorNote>}
      {state?.ok && (
        <p role="status" className="text-sm text-accent">
          {state.ok}
        </p>
      )}
      <div>
        <SubmitButton pendingText="Saving…">Save</SubmitButton>
      </div>
    </form>
  );
}

export function RemoveMemberButton({ projectId, userId, name }: { projectId: string; userId: string; name: string }) {
  const [pending, start] = useTransition();
  return (
    <Button
      variant="quiet"
      size="sm"
      disabled={pending}
      onClick={() => {
        if (confirm(`Remove ${name} from this project? They lose access straight away.`)) {
          start(() => removeMember(projectId, userId));
        }
      }}
    >
      {pending ? "Removing…" : "Remove"}
    </Button>
  );
}
