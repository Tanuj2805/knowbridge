"use client";

import { useActionState, useState } from "react";
import { SubmitButton } from "@/components/submit-button";
import { Button, ErrorNote, Label, Select, Textarea } from "@/components/ui";
import type { Member } from "@/lib/types";
import { answerQuestion } from "../../actions";

export function AnswerForm({ projectId, handoverId, questionId, others }: {
  projectId: string;
  handoverId: string;
  questionId: string;
  others: Member[];
}) {
  const [state, action] = useActionState(answerQuestion.bind(null, projectId, handoverId, questionId), undefined);
  const [passing, setPassing] = useState(false);
  return (
    <form action={action} className="grid gap-3">
      <div>
        <Label htmlFor="answer" required hint="A sentence or two is plenty. Never paste passwords; say who holds the access.">
          Your answer
        </Label>
        <Textarea id="answer" name="answer" rows={4} autoFocus required />
      </div>
      {state?.error && <ErrorNote>{state.error}</ErrorNote>}
      <div className="flex flex-wrap items-center gap-2">
        <SubmitButton name="intent" value="answer" pendingText="Saving…">
          Save answer
        </SubmitButton>
        <Button type="submit" name="intent" value="skip" variant="secondary" formNoValidate>
          I don&apos;t know
        </Button>
        {!passing && others.length > 0 && (
          <Button type="button" variant="quiet" onClick={() => setPassing(true)}>
            Ask someone else
          </Button>
        )}
      </div>
      {passing && (
        <div className="flex flex-wrap items-end gap-2 rounded-md bg-paper-sunk p-3">
          <div className="min-w-48">
            <Label htmlFor="assignee_id" required>
              Who knows?
            </Label>
            <Select id="assignee_id" name="assignee_id" defaultValue={others[0]?.user.id}>
              {others.map((m) => (
                <option key={m.user.id} value={m.user.id}>
                  {m.user.name}
                </option>
              ))}
            </Select>
          </div>
          <Button type="submit" name="intent" value="reassign" variant="secondary" formNoValidate>
            Pass the question on
          </Button>
        </div>
      )}
    </form>
  );
}
