import { Download } from "lucide-react";
import type { Metadata } from "next";
import { headers } from "next/headers";
import { Card, CardHeader, PageHeader, Tag } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { ApiToken, ProjectSummary } from "@/lib/types";
import { CopyText, NewTokenForm, RevokeButton } from "./token-controls";

export const metadata: Metadata = { title: "Connect your editor" };

const VSIX = "/downloads/knowbridge-vscode.vsix";
const MCP = "/downloads/knowbridge-mcp.mjs";

function Snippet({ text }: { text: string }) {
  return (
    <div className="mt-3">
      <pre className="overflow-x-auto rounded-lg border border-rule bg-paper-sunk p-3 font-mono text-[12.5px] leading-relaxed text-ink">
        {text}
      </pre>
      <div className="mt-2">
        <CopyText text={text} label="Copy settings" />
      </div>
    </div>
  );
}

export default async function EditorPage({ params }: PageProps<"/projects/[projectId]/editor">) {
  const { projectId } = await params;
  const [project, tokens] = await Promise.all([
    api<ProjectSummary>(`/projects/${projectId}`),
    api<ApiToken[]>("/me/tokens"),
  ]);
  const mine = tokens.filter((t) => t.project_id === projectId);
  const h = await headers();
  const site = `${h.get("x-forwarded-proto") ?? "http"}://${h.get("x-forwarded-host") ?? h.get("host")}`;
  const approvedOnly = !project.my_roles.some((r) => r === "admin" || r === "approver");

  const mcpConfig = JSON.stringify(
    {
      mcpServers: {
        knowbridge: {
          command: "node",
          args: ["C:/path/to/knowbridge-mcp.mjs"],
          env: { KNOWBRIDGE_URL: site, KNOWBRIDGE_TOKEN: "kb_paste-your-token-here" },
        },
      },
    },
    null,
    2,
  );

  return (
    <div>
      <PageHeader title="Connect your editor">
        Bring {project.name}&apos;s handover knowledge into the place you write code: who owns the file you have open,
        the decisions and risks about it, and answers with sources from your AI coding assistant. Everything goes
        through the same permission checks as this website
        {approvedOnly ? ", and you see approved claims only" : ""}.
      </PageHeader>

      <div className="grid gap-14 lg:grid-cols-[1fr_22rem] lg:gap-16">
        <div className="min-w-0 space-y-14">
          <Card>
            <CardHeader title="1. Make an access token">
              A token lets the extension or your assistant read and search this project, as you. It can&apos;t change
              anything, it only opens {project.name}, and it stops working when you revoke it or after 90 days.
            </CardHeader>
            <div className="mt-5">
              <NewTokenForm projectId={projectId} />
            </div>
          </Card>

          <Card>
            <CardHeader title="2. VS Code">
              Install the extension, then run <strong>KnowBridge: Connect</strong> from the Command Palette and paste
              this site&apos;s address and your token. Open any file in the repository: the KnowBridge panel shows its
              owners, decisions, risks and the claims that cite it. The extension also gives Copilot&apos;s agent mode the
              KnowBridge tools.
            </CardHeader>
            <div className="mt-4 flex flex-wrap items-center gap-3 text-[14px]">
              <a href={VSIX} download className="inline-flex items-center gap-1.5 font-medium text-accent hover:underline">
                <Download className="size-4" aria-hidden="true" />
                knowbridge-vscode.vsix
              </a>
              <span className="text-ink-faint">Extensions view → ⋯ → Install from VSIX…</span>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-[13px] text-ink-muted">
              Site address: <code className="rounded bg-paper-sunk px-1.5 py-0.5 font-mono text-ink">{site}</code>
              <CopyText text={site} label="Copy address" />
            </div>
          </Card>

          <Card>
            <CardHeader title="3. Claude Desktop, Cursor and other MCP assistants">
              Download the KnowBridge MCP server (one file, needs Node 18 or newer) and add it to your assistant&apos;s MCP
              settings: <span className="font-mono text-[13px]">claude_desktop_config.json</span> for Claude Desktop,{" "}
              <span className="font-mono text-[13px]">.cursor/mcp.json</span> for Cursor. Your assistant can then search
              the project, ask it questions, read a file&apos;s context and open a claim, always with sources.
            </CardHeader>
            <div className="mt-4 text-[14px]">
              <a href={MCP} download className="inline-flex items-center gap-1.5 font-medium text-accent hover:underline">
                <Download className="size-4" aria-hidden="true" />
                knowbridge-mcp.mjs
              </a>
            </div>
            <Snippet text={mcpConfig} />
          </Card>
        </div>

        <Card as="aside" className="self-start">
          <CardHeader title="Your tokens">For {project.name}. Revoke any you no longer use.</CardHeader>
          {mine.length === 0 ? (
            <p className="mt-4 text-[14px] text-ink-muted">None yet.</p>
          ) : (
            <ul className="mt-3 divide-y divide-rule">
              {mine.map((t) => (
                <li key={t.id} className="flex items-start justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <p className="truncate text-[14px] font-medium text-ink">{t.name}</p>
                    <p className="font-mono text-[12px] text-ink-faint">{t.prefix}…</p>
                    <p className="text-[12px] text-ink-faint">
                      {t.revoked
                        ? "Revoked"
                        : t.last_used_at
                          ? `Last used ${formatDate(t.last_used_at)}`
                          : `Made ${formatDate(t.created_at)}, not used yet`}
                    </p>
                  </div>
                  {t.revoked ? <Tag>Revoked</Tag> : <RevokeButton projectId={projectId} tokenId={t.id} />}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
