// Bundles the extension, and the MCP server it registers for Copilot, into dist/.
import { build } from "esbuild";

await build({
  entryPoints: ["src/extension.ts"],
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node18",
  external: ["vscode"],
  outfile: "dist/extension.js",
  logLevel: "info",
});

await build({
  entryPoints: ["../mcp/src/server.ts"],
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node18",
  outfile: "dist/knowbridge-mcp.mjs",
  banner: { js: "#!/usr/bin/env node" },
  nodePaths: ["node_modules"],
  logLevel: "info",
});
