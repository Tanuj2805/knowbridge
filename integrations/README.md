# KnowBridge in the editor

Two ways to use a project's handover knowledge while coding. Both use a personal access token made in
KnowBridge (project → **Editor** → Make a token): read-only, one project, revocable, valid 90 days. They talk to
the website's `/api/v1/...` door, which passes token requests to the API; the API applies the same permission
checks as the website (approved claims only for successors, masked secrets, prompt-injection guardrails).

| Folder | What it is |
|---|---|
| `shared/` | The KnowBridge client and plain-text renderings both use |
| `mcp/` | MCP server (stdio) with five tools: `project_info`, `search_project`, `ask_project`, `file_context`, `get_claim` |
| `vscode/` | VS Code extension: the "This file" panel, a status bar item, *Ask about this project*, and the MCP server registered for Copilot's agent mode |

## Build

```bash
cd integrations/mcp && npm install && npm run check && npm run build      # dist/knowbridge-mcp.mjs
cd ../vscode && npm install && npm run check && npm run package           # dist/knowbridge-vscode.vsix
cp ../vscode/dist/knowbridge-vscode.vsix ../mcp/dist/knowbridge-mcp.mjs ../../apps/web/public/downloads/
```

## Try the MCP server against a running KnowBridge

```bash
cd integrations/mcp
KNOWBRIDGE_URL=http://localhost:3000 KNOWBRIDGE_TOKEN=kb_... node test/smoke.mjs api/src/ "Why polling?"
```

## Use it in an assistant

Claude Desktop (`claude_desktop_config.json`) or Cursor (`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "knowbridge": {
      "command": "node",
      "args": ["/path/to/knowbridge-mcp.mjs"],
      "env": { "KNOWBRIDGE_URL": "https://your-knowbridge-site", "KNOWBRIDGE_TOKEN": "kb_..." }
    }
  }
}
```

In VS Code, install `knowbridge-vscode.vsix` and run **KnowBridge: Connect**; Copilot's agent mode then lists
the KnowBridge tools without any extra settings.
