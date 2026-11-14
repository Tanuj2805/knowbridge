// End-to-end check of the bundled MCP server against a running KnowBridge, as an MCP client sees it.
//   KNOWBRIDGE_URL=http://localhost:3000 KNOWBRIDGE_TOKEN=kb_... node test/smoke.mjs [file path] [question]
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { fileURLToPath } from "node:url";

const server = fileURLToPath(new URL("../dist/knowbridge-mcp.mjs", import.meta.url));
const [path = "api/src/", question = ""] = process.argv.slice(2);

const client = new Client({ name: "knowbridge-smoke", version: "1.0.0" });
await client.connect(
  new StdioClientTransport({
    command: process.execPath,
    args: [server],
    env: { ...process.env, KNOWBRIDGE_URL: process.env.KNOWBRIDGE_URL, KNOWBRIDGE_TOKEN: process.env.KNOWBRIDGE_TOKEN },
  }),
);

const tools = (await client.listTools()).tools.map((t) => t.name);
console.log("tools:", tools.join(", "));

const show = async (name, args) => {
  const r = await client.callTool({ name, arguments: args });
  const text = r.content.map((c) => c.text).join("\n");
  console.log(`\n=== ${name} ${JSON.stringify(args)}${r.isError ? " (error)" : ""}\n${text.slice(0, 1400)}`);
  return text;
};

await show("project_info", {});
const found = await show("search_project", { query: "payments polling webhook", limit: 4 });
await show("file_context", { path });
const id = found.match(/claim id: ([0-9a-f-]{36})/)?.[1];
if (id) await show("get_claim", { claim_id: id });
await show("get_claim", { claim_id: "00000000-0000-0000-0000-000000000000" });
if (question) await show("ask_project", { question });
await client.close();
