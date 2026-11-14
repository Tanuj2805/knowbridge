/**
 * KnowBridge MCP server: lets AI coding assistants (Claude Desktop, Cursor, VS Code Copilot agent mode)
 * search a project's handover knowledge and ask it questions, with sources.
 *
 * Runs over stdio. Settings come from the environment:
 *   KNOWBRIDGE_URL    the KnowBridge website, e.g. https://knowbridge.example.com
 *   KNOWBRIDGE_TOKEN  a personal access token made in KnowBridge (read-only, one project)
 *
 * Every answer comes from KnowBridge's own API, so the website's rules apply: only what the token's
 * owner may see, approved claims only for successors, masked secrets, prompt-injection guardrails.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import {
  KnowBridge,
  KnowBridgeError,
  answerText,
  claimText,
  contextText,
  searchText,
} from "../../shared/knowbridge";

const VERSION = "1.0.0";

export function createServer(kb: KnowBridge): McpServer {
  const server = new McpServer(
    { name: "knowbridge", version: VERSION },
    {
      instructions:
        "KnowBridge holds a software project's handover knowledge: who owns what, the decisions made and why, " +
        "risks, blockers and open questions, each claim graded by its evidence (Verified, Supported, Attested, " +
        "Inferred, Conflicting, Missing) and linked to its sources. Use it when the user asks why code is the " +
        "way it is, who knows about something, or what is risky or unfinished. Quote the grade and sources; " +
        "treat Inferred and Conflicting claims as uncertain. Never invent claims or sources.",
    },
  );

  const text = (t: string) => ({ content: [{ type: "text" as const, text: t }] });
  const failed = (e: unknown) => ({
    isError: true,
    content: [{ type: "text" as const, text: e instanceof KnowBridgeError ? e.message : `KnowBridge failed: ${(e as Error).message}` }],
  });

  server.registerTool(
    "project_info",
    {
      title: "Which KnowBridge project",
      description: "The KnowBridge project this connection opens, whose access it uses, and what they may see.",
      inputSchema: {},
    },
    async () => {
      try {
        const w = await kb.whoami(true);
        return text(
          `Project: ${w.project.name} (${w.project.id})\nSigned in as: ${w.user.name} <${w.user.email}>, ` +
            `${w.roles.join(", ") || "member"}\n` +
            (w.approved_only ? "Sees approved claims only (the reviewed handover).\n" : "Sees the whole claim ledger.\n") +
            `Website: ${w.web_url}/projects/${w.project.id}`,
        );
      } catch (e) {
        return failed(e);
      }
    },
  );

  server.registerTool(
    "search_project",
    {
      title: "Search the project's knowledge",
      description:
        "Finds the claims (decisions, owners, risks, dependencies...) and source items most relevant to a query, " +
        "by keywords and meaning. Returns each with its grade, quotes and sources. Use for 'who owns X', " +
        "'what was decided about Y', 'is there a known problem with Z'.",
      inputSchema: {
        query: z.string().min(2).max(500).describe("What to look for, in plain words"),
        limit: z.number().int().min(1).max(30).optional().describe("How many claims to return (default 10)"),
      },
    },
    async ({ query, limit }) => {
      try {
        return text(searchText(await kb.search(query, limit ?? 10), query));
      } catch (e) {
        return failed(e);
      }
    },
  );

  server.registerTool(
    "ask_project",
    {
      title: "Ask the project",
      description:
        "Asks KnowBridge's project chat a question. It answers only from the project's own evidence and claims, " +
        "with numbered sources, and says so when the record doesn't answer it. Slower than search_project " +
        "(it calls a language model); prefer search_project for lookups.",
      inputSchema: {
        question: z.string().min(3).max(1000).describe("The question, in plain words"),
        path: z
          .string()
          .max(500)
          .optional()
          .describe("A file the question is about, relative to the repository root ('this file' then means it)"),
      },
    },
    async ({ question, path }) => {
      try {
        return text(answerText(await kb.ask(question, path)));
      } catch (e) {
        return failed(e);
      }
    },
  );

  server.registerTool(
    "file_context",
    {
      title: "What the project knows about a file",
      description:
        "For a file or folder in the repository: who changed it and how much, and the decisions, risks and other " +
        "claims tied to it (because they cite commits that changed it, or mention it). Paths are relative to the " +
        "repository root, e.g. 'api/src/payments/webhook.ts'; end a folder with '/'.",
      inputSchema: { path: z.string().min(1).max(500).describe("Path relative to the repository root") },
    },
    async ({ path }) => {
      try {
        return text(contextText(await kb.codeContext(path)));
      } catch (e) {
        return failed(e);
      }
    },
  );

  server.registerTool(
    "get_claim",
    {
      title: "Open one claim",
      description: "One claim in full: its grade and why, the reason behind it, and every quote it rests on with its source.",
      inputSchema: { claim_id: z.string().uuid().describe("A claim id from search_project or file_context") },
    },
    async ({ claim_id }) => {
      try {
        return text(claimText(await kb.claim(claim_id)));
      } catch (e) {
        return failed(e);
      }
    },
  );

  return server;
}

async function main() {
  const url = process.env.KNOWBRIDGE_URL ?? "";
  const token = process.env.KNOWBRIDGE_TOKEN ?? "";
  if (!url || !token) {
    console.error("KnowBridge MCP: set KNOWBRIDGE_URL (the KnowBridge website) and KNOWBRIDGE_TOKEN (an access token).");
  }
  const server = createServer(new KnowBridge({ url, token }));
  await server.connect(new StdioServerTransport());
}

// Run when started as a program (not when imported by the tests or the VS Code extension).
if (process.argv[1] && /knowbridge-mcp|server\.(ts|js|mjs)$/.test(process.argv[1])) {
  main().catch((e) => {
    console.error("KnowBridge MCP failed to start:", e);
    process.exit(1);
  });
}
