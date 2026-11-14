# KnowBridge for VS Code

Your project's handover knowledge, next to the code it is about.

- **This file panel:** open any file in the repository and the KnowBridge panel shows who changed it, and
  the decisions, risks and other claims about it, each with its evidence grade and a link to its source.
- **Ask the project:** ask a question from the panel (or run *KnowBridge: Ask about this project*). The answer
  comes from the project's own record, with sources.
- **Copilot agent mode:** the extension adds the KnowBridge MCP server, so Copilot can search the project,
  read a file's context and open claims while it works.

## Set up

1. In KnowBridge, open your project, go to **Editor**, and make an access token.
2. In VS Code, run **KnowBridge: Connect** and paste your KnowBridge address and the token.

The token is read-only, opens one project, and is kept in VS Code's secret storage. KnowBridge applies the
same rules as on the website: you only see what you are allowed to see, successors see approved claims
only, and secrets are masked.
