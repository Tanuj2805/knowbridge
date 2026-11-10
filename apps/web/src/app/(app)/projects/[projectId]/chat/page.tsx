import { api } from "@/lib/api";
import type { ProjectSummary, RagStatus } from "@/lib/types";
import { Chat } from "./chat";
import { KnowledgePanel } from "./knowledge-panel";

export default async function ChatPage({ params }: PageProps<"/projects/[projectId]/chat">) {
  const { projectId } = await params;
  const [project, status] = await Promise.all([
    api<ProjectSummary>(`/projects/${projectId}`),
    api<RagStatus>(`/projects/${projectId}/rag/status`),
  ]);
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[minmax(0,1fr)_17rem]">
      <Chat projectId={projectId} projectName={project.name} staff={status.can_index} ready={status.ready} />
      <KnowledgePanel projectId={projectId} status={status} />
    </div>
  );
}
